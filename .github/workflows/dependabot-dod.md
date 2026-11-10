---
name: Dependabot DoD
description: Validates the definition of done after Dependabot QA succeeds
on:
  workflow_run:
    workflows: [Dependabot QA]
    types: [completed]
    branches: ["dependabot/github_actions/**"]
permissions:
  contents: read
  pull-requests: read
  issues: read
  actions: read
  checks: read
max-ai-credits: 25
engine:
  id: copilot
  agent: dod-validator-agent
network: defaults
tools:
  github:
    toolsets: [pull_requests, actions, issues, repos]
jobs:
  readiness:
    runs-on: ubuntu-latest
    permissions:
      checks: read
      pull-requests: read
    outputs:
      ready: ${{ steps.gate.outputs.ready }}
    steps:
      - name: Check QA and CI success
        id: gate
        uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
        with:
          script: |
            const run = context.payload.workflow_run;
            const { owner, repo } = context.repo;
            const linkedPr = run.pull_requests?.find(candidate => candidate.number);
            if (!linkedPr?.number) {
              core.setOutput('ready', 'false');
              core.notice('No associated pull request; DoD is not applicable.');
              return;
            }

            const pr = (await github.rest.pulls.get({
              owner,
              repo,
              pull_number: linkedPr.number
            })).data;

            if (pr.user.login !== 'dependabot[bot]' ||
                pr.base.ref !== 'main' ||
                pr.head.sha !== run.head_sha) {
              core.setOutput('ready', 'false');
              core.notice('The event is not for the current Dependabot PR head.');
              return;
            }

            const runs = await github.paginate(github.rest.checks.listForRef, {
              owner,
              repo,
              ref: run.head_sha,
              per_page: 100
            });
            runs.sort((a, b) =>
              Date.parse(a.started_at || a.created_at) -
              Date.parse(b.started_at || b.created_at)
            );
            const latest = new Map(runs.map(check => [check.name, check]));
            const requiredCi = [
              'unit-tests',
              'Component Tests (make up && make component-tests)',
              'Sanity Tests (make up && make sanity-tests)',
              'Static Review (checkstyle)',
              'analyze',
              'dependency-review',
              'secret-scan'
            ];
            const allCiPassed = requiredCi.every(name => {
              const check = latest.get(name);
              return check?.status === 'completed' &&
                check.conclusion === 'success';
            });
            const review = latest.get('PR Review');
            const qa = latest.get('QA Agent');
            const dodAlreadyReported = latest.has('Definition of Done');
            const ready = allCiPassed &&
              review?.status === 'completed' &&
              review.conclusion === 'success' &&
              qa?.status === 'completed' &&
              qa.conclusion === 'success' &&
              !dodAlreadyReported;

            core.setOutput('ready', String(ready));
            core.info(`DoD readiness: ${ready}; CI passed: ${allCiPassed}; ` +
              `PR Review: ${review?.conclusion || 'not reported'}; ` +
              `QA Agent: ${qa?.conclusion || 'not reported'}.`);
  agent:
    needs: readiness
    if: needs.readiness.outputs.ready == 'true'
safe-outputs:
  create-check-run:
    name: Definition of Done
    target: "${{ github.event.workflow_run.pull_requests[0].number }}"
    max: 1
  add-comment:
    target: "${{ github.event.workflow_run.pull_requests[0].number }}"
    max: 1
    issues: false
    pull-requests: true
---

# Dependabot Definition of Done

The readiness job starts this agent only when the current Dependabot PR head has successful `PR Review`, `QA Agent`,
and all required CI checks. Confirm those results and the exact head SHA again before evaluating acceptance criteria.

The linked Dependabot tracking issue may contain only a generic checklist. For this GitHub Actions dependency update,
use these policy acceptance criteria when the issue has no explicit acceptance criteria:

1. Every changed action reference is pinned to a full 40-character commit SHA, with a matching version comment.
2. The SHA and version correspond to the intended upstream action release, and every use of the updated action in the
   PR is updated consistently.
3. The diff is limited to the requested GitHub Actions dependency update; it does not change workflow logic,
   permissions, secrets, or unrelated dependencies.
4. `PR Review`, `QA Agent`, and all required CI checks succeeded on the same current head SHA.

For each criterion, provide concrete evidence from the PR diff, upstream release/tag, or check runs. Mark the result
`success` only if every criterion is met; otherwise mark it `failure` and identify each weak or missing criterion.
Publish one PR comment with the marker `<!-- dod-validation sha:<head-sha> -->` and the complete table using columns
`# | Acceptance criterion | Evidence | Verdict`. Create exactly one check run named `Definition of Done` with the
reviewed SHA and the evidence table in its summary. Do not merge the PR or call GitHub write APIs directly.

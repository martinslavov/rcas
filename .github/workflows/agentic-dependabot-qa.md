---
name: Dependabot QA
description: Runs the QA gate after Dependabot PR review and required CI checks complete
on:
  workflow_run:
    workflows:
      - Dependabot PR Review
      - CI Unit Tests
      - CI Component Tests
      - CI Sanity Tests
      - CI Static Review
      - CI Dependency Review
      - CI Secret Scan
      - CodeQL
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
  agent: senior-qa-engineer
network: defaults
tools:
  github:
    toolsets: [pull_requests, actions, issues]
jobs:
  readiness:
    runs-on: ubuntu-latest
    permissions:
      checks: read
      pull-requests: read
    outputs:
      ready: ${{ steps.gate.outputs.ready }}
    steps:
      - name: Check PR review and CI completion
        id: gate
        uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
        with:
          script: |
            const run = context.payload.workflow_run;
            const { owner, repo } = context.repo;
            const linkedPr = run.pull_requests?.find(candidate => candidate.number);
            if (!linkedPr?.number) {
              core.setOutput('ready', 'false');
              core.notice('No associated pull request; QA is not applicable.');
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
            const ciComplete = requiredCi.every(name =>
              latest.get(name)?.status === 'completed'
            );
            const review = latest.get('PR Review');
            const qaAlreadyReported = latest.has('QA Agent');
            const ready = ciComplete &&
              review?.status === 'completed' &&
              review.conclusion === 'success' &&
              !qaAlreadyReported;

            core.setOutput('ready', String(ready));
            core.info(`QA readiness: ${ready}; CI complete: ${ciComplete}; ` +
              `PR Review: ${review?.conclusion || 'not reported'}.`);
  agent:
    needs: readiness
    if: needs.readiness.outputs.ready == 'true'
safe-outputs:
  create-check-run:
    name: QA Agent
    target: "${{ github.event.workflow_run.pull_requests[0].number }}"
    max: 1
  add-comment:
    target: "${{ github.event.workflow_run.pull_requests[0].number }}"
    max: 1
    issues: false
    pull-requests: true
---

# Dependabot QA

The triggering workflow run may be one of several independent CI runs. The deterministic readiness job waits until
all required CI checks have completed and `PR Review` is successful on the same current head SHA before starting
this agent. If it is not ready, do not report a QA result.

Verify the PR is authored by `dependabot[bot]` and the head SHA matches
`${{ github.event.workflow_run.head_sha }}`. Review the diff and the CI checks on that exact SHA. A GitHub Actions
dependency update is not a runtime application change, but this repository requires `./gradlew build` for workflow
changes; the `unit-tests` check runs that build, and the component and sanity checks run independently as required CI.
Do not claim to have run a command locally. Do not mark QA successful if any required CI check failed, is missing, or
belongs to another SHA.

Publish one concise PR comment with QA results and exactly one check run named `QA Agent`. Use `success` only when
all required CI checks and the QA review pass. Otherwise use `failure` and list the failed checks or evidence gaps.
The check-run summary must identify the head SHA and the checks actually verified. Do not merge the PR or call
GitHub write APIs directly.

---
name: ship-pr
description: Ship the current work end to end - ensure a task issue exists, commit, push, create a PR, run PR Review and QA, then merge when every gate succeeds on the current head SHA. Optional arguments add PR labels; with `agent-read` it hands review to automation. Use when the user runs /ship-pr [labels] or asks to ship, finish or merge the current change.
---

# Ship PR

Run the delivery pipeline for the change in the working tree. The main agent only coordinates; reviews are done by the
custom agents. Repository: `martinslavov/rcas`. Record `date +%s` at the start for the elapsed time.

## Arguments

`/ship-pr [label[,label...]]` - optional extra PR labels, separated by commas or spaces.

- No arguments: only the default labels (type `bug`/`documentation`/`enhancement` and impact `minor`/`major`).
- With arguments: default labels plus the given ones. A label that does not exist is reported to the user, never created silently.
- `needs-human-review` is refused as an argument; only a human applies or removes it.
- **`agent-read` mode.** If `agent-read` is among the arguments, the automation (Copilot dispatch → PR Review → QA and
  the auto-merge gate) owns the review pipeline. Create or reuse the task issue, create/reuse the `/ship-pr` PR, then run
  `orchestrator.py intake-pr-review <issue> --pr <pr> --agent-read`. This records the current head SHA and start marker,
  moves the task directly to PR Review, removes `agent-read` from the issue, and adds it to the PR. Do not set status gates,
  invoke review/QA agents, or merge; report that automation continues. The issue must not be in `TODO` with issue-level
  `agent-read`, since that means Architect/Engineer automation has not completed. See `.github/docs/agent-automation.md`.

## Rules

- **Definition of Done is manual only.** Never run `dod-validator-agent` and never wait for or require the `Definition of Done`
  status; it is not a merge gate. Run it only if the user explicitly asks.
- **Reuse the current branch.** Run `git branch --show-current`. If it is a `feature/*` or `hotfix/*` branch, work on it and do
  not create a new branch. Only when on `main` (or detached) create `feature/<slug>` (lowercase ASCII, digits, `-`) from an up to
  date `main`. Never commit or push to `main`.
- If continuing an Engineer handoff, check out the exact branch the Engineer pushed before running the skill; do not create a
  second branch for the same implementation.
- **Issue first.** Reuse the task issue explicitly associated with the work. If none is identified, create one before creating
  the PR, using the normal issue template and Product Owner-style acceptance criteria. Do not add `agent-read` or `backlog`
  to an issue created by this skill.
- **PR creation is through this skill.** If an open PR exists for the branch and its body lacks `<!-- ship-pr -->`, stop:
  do not adopt, relabel, or rewrite a PR created outside this skill. Reuse an existing PR only when it already has that marker.
  New PR bodies must preserve the pull request template and include `<!-- ship-pr -->` plus `Closes #<issue>`.
  This is the supported repository process; GitHub permissions may still allow a person to create a PR manually, but automation
  ignores PRs without the marker.
- Before creating an issue, check for an open PR on the branch with
  `gh pr list -R martinslavov/rcas --head <branch> --state open --json number,body`. Stop on an unmarked PR before creating
  anything.
- Nothing to commit and no commits ahead of `main`: stop and tell the user.
- Never stage secrets or unrelated files; review `git status` and `git diff --stat` before committing.
- Never merge when any gate is pending, failed, skipped or unknown, when `needs-human-review` is present, or when human
  comments or unresolved blocker/major findings remain. Never bypass the orchestrator or branch protection.
- PR descriptions must not contain review, QA or check-status claims; the testing section lists only commands actually run.

## Steps

1. **Commit.** Stage the intended changes and commit with a clear message ending with the trailer
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`. If the tree is clean, skip the commit.
2. **Push.** `git push -u origin <branch>`.
3. **Task issue.** If there is no task issue explicitly identified for this work, delegate the task summary and relevant
   change context to `product-owner-agent` to check for duplicates and create the issue using `.github/ISSUE_TEMPLATE/issue.yml`.
   Keep the issue in TODO (no `backlog` label) and do not add `agent-read`. Because this code is already implemented, this
   intake does not dispatch Architect or Engineer; `/ship-pr agent-read` enters at PR Review, as the user explicitly chose.
   Store the issue number as `<issue>`.
4. **Pull request.** If no marked open PR exists for the branch, create one with
   `gh pr create -R martinslavov/rcas --base main --assignee @me` and a body built from
   `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md` (keep headings, comments, checklist items, and order; include
   `Closes #<issue>`, local test commands with results, the acceptance criteria table, and `<!-- ship-pr -->`).
   Add the labels the template asks for (type and impact) plus any labels passed as arguments except `agent-read`, which the
   intake command adds only after recording the task state. Store the PR number as `<pr>`.
5. **Record PR Review intake.** Check the issue's task-state record with
   `python3 .github/scripts/orchestrator.py state <issue>`. If the Issue Board workflow has not seeded it yet, wait for that
   workflow. If it has completed but the record is still missing, seed only the initial state with
   `python3 .github/scripts/orchestrator.py init <issue> --state todo --agent human`; if that reports an existing record,
   re-read the state instead of overwriting it. Then run
   `python3 .github/scripts/orchestrator.py intake-pr-review <issue> --pr <pr>`; add `--agent-read` only when that label was
   passed as a `/ship-pr` argument. This records the PR head SHA and automation start marker and removes issue-level
   `agent-read` after a completed implementation. If the command fails, stop and report the error; do not bypass the
   orchestrator or add labels manually.
6. **Agent-read handoff.** If `agent-read` was requested, stop here: the intake command adds the label to the PR, which starts
   PR Review. Do not reset gates, invoke review/QA agents, or merge.
7. **Reset gates.** For the manual-review path, set `PR Review` and `QA Agent` to `pending` on the head SHA
   (`gh pr view <number> -R martinslavov/rcas --json headRefOid -q .headRefOid`) as described in the pull request rules of
   `.github/copilot-instructions.md`.
8. **PR Review.** Delegate to `pr-review-agent`: `Review PR #<pr> in martinslavov/rcas.`
9. **Wait for `PR Review`** to be `success` on the current head SHA
   (`gh api repos/martinslavov/rcas/commits/<sha>/status --jq '.statuses[] | select(.context=="PR Review") | .state'`),
   polling every 30-60 seconds. On `failure` with blocker/major findings: fix them (delegate to
   `senior-java-software-engineer` if the fix is non-trivial), commit, push, and restart at step 7. The head SHA may change
   after a push; always compare against the current one.
10. **QA.** Delegate to `senior-qa-engineer`: `Run QA for PR #<pr> in martinslavov/rcas.` Wait for `QA Agent` = `success`.
   On failure fix and restart from step 7.
11. **Merge.** Verify with `gh pr checks <pr> -R martinslavov/rcas` that every required check and the `PR Review` and `QA Agent` statuses
   are `success` on the current head SHA, and that
   `gh api repos/martinslavov/rcas/issues/<pr>/labels -q '.[].name | select(. == "needs-human-review")'` is empty.
   Then `gh pr merge <pr> -R martinslavov/rcas --merge --delete-branch`.
12. **Report.** Give the task issue and PR links, merge status and total elapsed time. Record elapsed time with
    `.github/scripts/post_task_elapsed.sh <issue> <pr> <start-epoch>`.

## Loop limits

PR Review and QA failures each have a bounded loop of 5 rounds. The CI-fix loop is stricter: at most 3 attempts, and it stops
immediately when the failure signature repeats the previous attempt's. The exact counting rules (round markers, signatures)
are in `.github/copilot-instructions.md`; follow them and do not re-derive them here. If the label `needs-human-review` is
present, or any limit is reached, stop, summarize the open findings for the user and do not fix, push or merge further.
Only a human removing `needs-human-review` resumes the work: then continue numbering above the original limit without
re-applying it (keep all round markers); the repeated CI failure signature stop still applies.

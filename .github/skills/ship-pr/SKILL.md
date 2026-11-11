---
name: ship-pr
description: Ship the current work end to end - commit, push, open a PR, run PR Review, QA and DoD, then merge when every gate succeeds on the current head SHA. Use when the user runs /ship-pr or asks to ship, finish or merge the current change.
---

# Ship PR

Run the delivery pipeline for the change in the working tree. The main agent only coordinates; reviews are done by the
custom agents. Repository: `martinslavov/rcas`. Record `date +%s` at the start for the elapsed time.

## Rules

- **Reuse the current branch.** Run `git branch --show-current`. If it is a `feature/*` or `hotfix/*` branch, work on it and do
  not create a new branch. Only when on `main` (or detached) create `feature/<slug>` (lowercase ASCII, digits, `-`) from an up to
  date `main`. Never commit or push to `main`.
- **Reuse an existing PR.** `gh pr list -R martinslavov/rcas --head <branch> --state open --json number -q '.[0].number'`.
  If one exists, use its number and skip PR creation; otherwise create it.
- Nothing to commit and no commits ahead of `main`: stop and tell the user.
- Never stage secrets or unrelated files; review `git status` and `git diff --stat` before committing.
- Never merge when any gate is pending, failed, skipped or unknown, when `needs-human-review` is present, or when human
  comments or unresolved blocker/major findings remain. Never bypass the orchestrator or branch protection.
- PR descriptions must not contain review, QA or check-status claims; the testing section lists only commands actually run.

## Steps

1. **Commit.** Stage the intended changes and commit with a clear message ending with the trailer
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`. If the tree is clean, skip the commit.
2. **Push.** `git push -u origin <branch>`.
3. **Pull request.** Use the existing PR or create one with `gh pr create -R martinslavov/rcas --base main --assignee @me`
   and a body built from `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md` (keep headings and order; fill the
   description, `Closes #<issue>` if an issue exists, local test commands with results, the acceptance criteria table).
   Add the labels the template asks for (type and impact). Store the PR number as `<number>`; use it in every step below.
4. **Reset gates.** Set `PR Review`, `QA Agent` and `Definition of Done` to `pending` on the head SHA
   (`gh pr view <number> -R martinslavov/rcas --json headRefOid -q .headRefOid`) as described in the pull request rules of
   `.github/copilot-instructions.md`.
5. **PR Review.** Delegate to `pr-review-agent`: `Review PR #<number> in martinslavov/rcas.`
6. **Wait for `PR Review`** to be `success` on the current head SHA
   (`gh api repos/martinslavov/rcas/commits/<sha>/status --jq '.statuses[] | select(.context=="PR Review") | .state'`),
   polling every 30-60 seconds. On `failure` with blocker/major findings: fix them (delegate to
   `senior-java-software-engineer` if the fix is non-trivial), commit, push, go back to step 4. The head SHA may change after a
   push; always compare against the current one.
7. **QA.** Delegate to `senior-qa-engineer`: `Run QA for PR #<number> in martinslavov/rcas.` Wait for `QA Agent` = `success`.
   On failure fix and restart from step 4.
8. **DoD.** Delegate to `dod-validator-agent`: `Validate Definition of Done for PR #<number> in martinslavov/rcas.` Wait for
   `Definition of Done` = `success`. On failure add the missing evidence and restart from step 4.
9. **Merge.** Verify with `gh pr checks <number> -R martinslavov/rcas` that every required check and all three agent statuses
   are `success` on the current head SHA, and that
   `gh api repos/martinslavov/rcas/issues/<number>/labels -q '.[].name | select(. == "needs-human-review")'` is empty.
   Then `gh pr merge <number> -R martinslavov/rcas --merge --delete-branch`.
10. **Report.** Give the PR link, merge status and total elapsed time. If a task issue exists, record the elapsed time with
    `.github/scripts/post_task_elapsed.sh <issue> <number> <start-epoch>`.

## Loop limits

Each of PR Review, QA, DoD and CI-fix has its own bounded loop of 5 rounds (see `.github/copilot-instructions.md`). If the
label `needs-human-review` is applied, or a gate keeps failing after 5 rounds, stop, summarize the open findings for the user
and do not merge.

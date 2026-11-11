---
name: ship-pr
description: Ship the current work end to end - commit, push, open a PR, run PR Review and QA, then merge when every gate succeeds on the current head SHA. Optional arguments add PR labels; with `agent-read` it stops after opening the PR. Use when the user runs /ship-pr [labels] or asks to ship, finish or merge the current change.
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
  the auto-merge gate) owns the review pipeline. Then do steps 1-3 only (commit, push, PR with the labels, including
  `agent-read`) and **do not** run steps 4-9: do not set the gates to `pending`, do not invoke `pr-review-agent`,
  or `senior-qa-engineer`, and do not merge. This avoids duplicate reviews and conflicting statuses.
  Report the PR link and that the agent automation continues; see `.github/docs/agent-automation.md`.

## Rules

- **Definition of Done is manual only.** Never run `dod-validator-agent` and never wait for or require the `Definition of Done`
  status; it is not a merge gate. Run it only if the user explicitly asks.
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
   Add the labels the template asks for (type and impact) plus any labels passed as arguments (see "Arguments"; if the PR
   already exists, add the missing labels to it). Store the PR number as `<number>`; use it in every step below.
4. **Reset gates.** Set `PR Review` and `QA Agent` to `pending` on the head SHA
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
8. **Merge.** Verify with `gh pr checks <number> -R martinslavov/rcas` that every required check and the `PR Review` and `QA Agent` statuses
   are `success` on the current head SHA, and that
   `gh api repos/martinslavov/rcas/issues/<number>/labels -q '.[].name | select(. == "needs-human-review")'` is empty.
   Then `gh pr merge <number> -R martinslavov/rcas --merge --delete-branch`.
9. **Report.** Give the PR link, merge status and total elapsed time. If a task issue exists, record the elapsed time with
    `.github/scripts/post_task_elapsed.sh <issue> <number> <start-epoch>`.

## Loop limits

PR Review and QA failures each have a bounded loop of 5 rounds. The CI-fix loop is stricter: at most 3 attempts, and it stops
immediately when the failure signature repeats the previous attempt's. The exact counting rules (round markers, signatures)
are in `.github/copilot-instructions.md`; follow them and do not re-derive them here. If the label `needs-human-review` is
present, or any limit is reached, stop, summarize the open findings for the user and do not fix, push or merge further.
Only a human removing `needs-human-review` resumes the work: then continue numbering above the original limit without
re-applying it (keep all round markers); the repeated CI failure signature stop still applies.

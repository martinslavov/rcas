---
name: create-pr-cloud
description: Create a task-linked PR and hand it to cloud automation for PR Review, QA, bounded fixes and gated automatic merge.
---

# Create PR with cloud automation

Run the delivery pipeline for the change in the working tree. The main agent only coordinates; reviews are done by the
custom agents. Repository: `martinslavov/rcas`. Record `date +%s` at the start for the elapsed time.

## Arguments

`/create-pr-cloud [label[,label...]]` - optional extra PR labels, separated by commas or spaces.

- No arguments: only the default labels (type `bug`/`documentation`/`enhancement` and impact `minor`/`major`).
- With arguments: default labels plus the given ones. A label that does not exist is reported to the user, never created silently.
- `needs-human-review` is refused as an argument; only a human applies or removes it.
- **Cloud handoff is the default.** The automation (Copilot dispatch → PR Review → QA and auto-merge) owns the review pipeline.
  Create or reuse the task issue and marked PR, then run
  `orchestrator.py intake-pr-review <issue> --pr <pr> --cloud-agent`. For cloud issues created from `TAG: cloud-agent`, do not
  invoke this skill after the Engineer push: the guarded five-minute cloud workflow creates/reuses the PR and runs the same
  intake. In either path do not set status gates, invoke review/QA agents, or merge; report that automation continues. See
  `.github/docs/agent-automation.md`.

## Rules

- **Definition of Done is manual only.** Never run `dod-validator-agent` and never wait for or require the `Definition of Done`
  status; it is not a merge gate. Run it only if the user explicitly asks.
- **Reuse the current branch.** Run `git branch --show-current`. If it is a `feature/*` or `hotfix/*` branch, work on it and do
  not create a new branch. Only when on `main` (or detached) create `feature/<slug>` (lowercase ASCII, digits, `-`) from an up to
  date `main`. Never commit or push to `main`.
- If continuing an Engineer handoff, check out the exact branch the Engineer pushed before running the skill; do not create a
  second branch for the same implementation.
- **Issue first.** Reuse the task issue explicitly associated with the work. If none is identified, create one before creating
  the PR, using the normal issue template and Product Owner-style acceptance criteria. Do not add `cloud-agent` or `backlog`
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
- If the user asks to keep the PR open, do not opt it into cloud automation: create or reuse the PR without cloud intake
  and report that review, QA and merge were not started. If the PR is already cloud-opted-in, stop and report that its
  automation is already active; do not claim it will remain open.
- PR descriptions must not contain review, QA or check-status claims; the testing section lists only commands actually run.

## Steps

1. **Commit.** Stage the intended changes and commit with a clear message ending with the trailer
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`. If the tree is clean, skip the commit.
2. **Push.** `git push -u origin <branch>`.
3. **Task issue.** If there is no task issue explicitly identified for this work, delegate the task summary and relevant
   change context to `product-owner-agent` to check for duplicates and create the issue using `.github/ISSUE_TEMPLATE/issue.yml`.
   Keep the issue in TODO (no `backlog` label) and do not add `cloud-agent`. Because this code is already implemented, this
   intake does not dispatch Architect or Engineer; `/create-pr-cloud` enters at PR Review.
   Store the issue number as `<issue>`.
4. **Pull request.** If no marked open PR exists for the branch, create one with
   `gh pr create -R martinslavov/rcas --base main --assignee @me` and a body built from
   `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md` (keep headings, comments, checklist items, and order; include
   `Closes #<issue>`, local test commands with results, the acceptance criteria table, and `<!-- ship-pr -->`).
   Add the labels the template asks for (type and impact) plus any labels passed as arguments except `cloud-agent`, which the
   intake command adds only after recording the task state. Store the PR number as `<pr>`.
5. **Record PR Review intake.** If the user asked to keep the PR open, stop here without intake or `cloud-agent`; report
   the issue and PR links. Otherwise check the issue's task-state record with
   `python3 .github/scripts/orchestrator.py state <issue>`. If the Issue Board workflow has not seeded it yet, wait for that
   workflow. If it has completed but the record is still missing, seed only the initial state with
   `python3 .github/scripts/orchestrator.py init <issue> --state todo --agent human`; if that reports an existing record,
   re-read the state instead of overwriting it. Then run
   `python3 .github/scripts/orchestrator.py intake-pr-review <issue> --pr <pr> --cloud-agent`. This records the PR head SHA and automation start marker and removes issue-level
   `cloud-agent` after a completed implementation. If the command fails, stop and report the error; do not bypass the
   orchestrator or add labels manually.
6. **Cloud-agent handoff.** Stop here: intake adds the label and cloud automation starts PR Review, then QA, bounded fix
   loops and automatic merge when all gates pass. Do not reset gates, invoke review/QA agents, or merge locally.
   Report the issue and PR links and that the handoff is pending; do not claim a merge has happened.

## Loop limits

PR Review and QA failures each have a bounded loop of 5 rounds. The CI-fix loop is stricter: at most 3 attempts, and it stops
immediately when the failure signature repeats the previous attempt's. The exact counting rules (round markers, signatures)
are in `.github/copilot-instructions.md`; follow them and do not re-derive them here. If the label `needs-human-review` is
present, or any limit is reached, stop, summarize the open findings for the user and do not fix, push or merge further.
Only a human removing `needs-human-review` resumes the work: then continue numbering above the original limit without
re-applying it (keep all round markers); the repeated CI failure signature stop still applies.

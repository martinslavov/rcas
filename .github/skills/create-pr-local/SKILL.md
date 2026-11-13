---
name: create-pr-local
description: Create a PR without a task issue, run local PR Review and QA agents, and merge when all required gates pass.
---

# Create a PR locally without a task issue

This flow creates no task issue. The current local session coordinates PR Review, QA and gated merge; it does not dispatch
Copilot cloud automation. Follow `.github/copilot-instructions.md`, the PR template and the agent profiles.

## Rules

- Never create or link a task issue. Include `<!-- no-task-issue -->` in the PR body; the tracking workflow skips it.
- Do not add `<!-- ship-pr -->`, `<!-- quick-pr-cloud-auto-merge -->`, `Closes #N`, or `cloud-agent`.
- Never commit or push to `main`. Reuse an existing `feature/*` or `hotfix/*` branch; only create a branch from an up-to-date `main`.
- Do not stage unrelated files or secrets. Stop if an unmarked PR already exists for the branch.
- The coordinator must verify every required check and both agent statuses on the current head SHA, absence of
  `needs-human-review`, human comments or reviews, and unresolved blocker/major findings. Never bypass these gates.
- If the user asks to keep the PR open, do not merge.
- On review, QA or CI failure stop and report actionable findings; do not merge. A later fix must reset statuses on its
  new head and repeat PR Review before QA.
- Set `PR Review`, `QA Agent` and informational `Definition of Done` to `pending` on the current head SHA after opening the PR and
  after each push. Run PR Review first and QA only after current-head PR Review succeeds.
- The Acceptance criteria → evidence table describes the requested change directly and cites only evidence that exists.
  Do not claim a check passed unless it was run and passed.

## Steps

1. Inspect `git status`, `git diff`, the task request, and the repository PR template. Choose a short branch slug from the task.
   If on `main`, fetch and fast-forward to `origin/main`, then create `feature/<slug>`. Otherwise reuse the current feature/hotfix
   branch and stop if it is unrelated to the requested change. Do not adopt a PR without `<!-- no-task-issue -->` or one
   with the cloud opt-in marker or label.
2. Implement the small change, add focused tests when appropriate, and run the relevant documented checks. Stage only intended
   files; commit with a clear message ending in
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.
3. Push the branch. If there is no open PR for it, create one from
   `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`, preserving its headings and order. Replace the tracking issue
   sentence with `No task issue by design.`; remove the `Closes #<issue>` placeholder; include `<!-- no-task-issue -->`.
   Keep the rest of the template and its checklist, fill the description, testing results and acceptance evidence accurately,
   assign `@me`, and add the appropriate type and impact labels.
4. Read the PR number and current head SHA. Set the three status contexts to `pending` using the status commands documented in
   `.github/copilot-instructions.md`.
5. Delegate PR Review to `pr-review-agent` in the current local session and wait for `PR Review` success on the current
   head SHA. Delegate QA to `senior-qa-engineer` only after review succeeds and wait for `QA Agent` success on that SHA.
   Both use the PR description as scope and the PR number as the `issue` value in their agent-run records. QA is
   verification-only; neither agent pushes changes. DoD is manual only.
6. Wait for in-progress checks using `gh pr checks <pr> -R martinslavov/rcas --watch`, then verify all ruleset-required
   checks and both agent commit statuses are successful on the current head SHA, there is no
   `needs-human-review` label, human PR comment or review, or unresolved blocker/major finding. If any gate is pending,
   failed, skipped, unknown, or cannot be determined, do not merge. Read the current ruleset and check runs/statuses with
   `gh pr checks <pr> -R martinslavov/rcas` and the commit status API; inspect paginated issue comments, PR reviews and
   inline review comments as described in `.github/copilot-instructions.md`. Honor a request to keep the PR open.
7. When every gate passes and the user has not asked to keep it open, run
   `gh pr merge <pr> -R martinslavov/rcas --merge --delete-branch --match-head-commit <verified-head-sha>`.
   Report the PR URL and actual merge status.

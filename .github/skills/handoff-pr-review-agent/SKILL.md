---
name: handoff-pr-review-agent
description: Start local PR Review and QA handoff for an existing local-flow PR in the current session.
---

# Execute local PR handoff for an existing PR

Use this when a local-flow PR is open (`<!-- no-task-issue -->`) and `PR Review` / `QA Agent` are pending. This skill keeps
all checks local to the current session and does not dispatch cloud automation.

## Arguments

`/handoff-pr-review-agent <pr-number>`

Optional: append `--dry-run` to validate local handoff prerequisites without changing statuses.

## Rules

- This skill is for local-flow PRs (`<!-- no-task-issue -->`) and must not be used for cloud task PRs.
- If the PR contains `<!-- ship-pr -->` or the `cloud-agent` label, stop and use `/handoff-pr-review-cloud`.
- PR must be open, non-draft, and target `main`.
- Run `pr-review-agent` first; run `senior-qa-engineer` only after `PR Review` is `success` on the current head SHA.

## Steps

1. Run `.github/scripts/execute_pr_check_local.sh <pr-number>` (or add `--dry-run` first).
2. Read the current head SHA for the PR and verify that `PR Review`, `QA Agent`, and `Definition of Done` are `pending`.
3. Delegate the PR to `pr-review-agent` and wait for a final `PR Review` status on the current head SHA.
4. If `PR Review` succeeds, delegate the PR to `senior-qa-engineer` and wait for a final `QA Agent` status on the same SHA.
5. Watch checks with `gh pr checks <pr-number> -R martinslavov/rcas --watch`.


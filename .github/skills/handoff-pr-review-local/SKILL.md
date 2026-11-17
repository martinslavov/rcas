---
name: handoff-pr-review-local
description: Start local PR Review and QA handoff for an existing local-flow PR in the current session.
---

# Execute local PR handoff for an existing PR

Use this when a local-flow PR is open (`<!-- no-task-issue -->`) and `PR Review` / `QA Agent` are pending. This skill keeps
checks local by invoking `pr-review-agent` and `senior-qa-engineer` through local Copilot CLI.

## Arguments

`/handoff-pr-review-local <pr-number>`

Optional: append `--dry-run` to validate local handoff prerequisites without changing statuses.

## Rules

- This skill is for local-flow PRs (`<!-- no-task-issue -->`) and must not be used for cloud task PRs.
- If the PR contains `<!-- ship-pr -->` or the `cloud-agent` label, stop and use `/handoff-pr-review-cloud`.
- PR must be open, non-draft, and target `main`.
- Run `pr-review-agent` first; run `senior-qa-engineer` only after `PR Review` is `success` on the current head SHA.
- Requires authenticated `gh` and `copilot` CLIs in the current shell.

## Steps

1. Run `.github/scripts/handoff_pr_review_local.sh <pr-number>` (or add `--dry-run` first).
2. The script initializes pending statuses via `execute_pr_check_local.sh`, runs `pr-review-agent`, then runs `senior-qa-engineer` only when `PR Review` is `success` on the unchanged head SHA.
3. If needed, pass `--no-watch` to skip the final `gh pr checks ... --watch` step.

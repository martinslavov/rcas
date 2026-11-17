---
name: handoff-pr-review-cloud
description: Trigger PR Review and QA automation for an existing task-linked PR through cloud intake.
---

# Execute cloud PR handoff for an existing PR

Use this when a task-linked PR is open but `PR Review` and `QA Agent` are still pending and you want to trigger the
cloud automation handoff again in a safe, repeatable way.

## Arguments

`/handoff-pr-review-cloud <pr-number>`

Optional: append `--dry-run` to validate inputs without changing issue/PR state.

## Rules

- This skill is for task-linked PRs created through the normal task flow (`<!-- ship-pr -->` and `Closes #<issue>`).
- It does not run review or QA directly; it runs orchestrator intake with `--cloud-agent`, which triggers dispatch.
- Do not use it for docs-only local flow PRs that intentionally avoid cloud automation.
- If the PR is draft, closed, does not target `main`, or lacks issue linkage, stop and report the reason.

## Steps

1. Run `.github/scripts/execute_pr_check.sh <pr-number>` (or add `--dry-run` first).
2. Confirm the command reports the linked issue and successful intake output.
3. Watch the checks with `gh pr checks <pr-number> -R martinslavov/rcas --watch`.
4. If statuses stay pending for too long, check `.github/workflows/ci-agent-dispatch.yml` runs and report failures.


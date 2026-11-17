---
name: handoff-pr-review
description: Legacy alias. Use handoff-pr-review-cloud for cloud intake and handoff-pr-review-local for local handoff.
---

# Legacy handoff alias

This skill name is kept for backward compatibility.

Use one of the explicit commands instead:

- `/handoff-pr-review-cloud <pr-number>` for task-linked cloud intake (`<!-- ship-pr -->`).
- `/handoff-pr-review-local <pr-number>` for local-flow PR checks (`<!-- no-task-issue -->`).

If in doubt, inspect the PR body markers first and choose the matching flow.
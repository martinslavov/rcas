---
name: create-issue
description: Ask the Product Owner to create a TODO issue without starting implementation or PR automation.
---

# Create a manual task issue

Use this flow when the user wants a well-defined GitHub issue and intends to implement it later. Follow the Product Owner
contract in `.github/agents/product-owner.agent.md` and the task intake rules in `.github/copilot-instructions.md`.

## Rules

- Invoke `product-owner-agent` to refine the task and create the issue.
- Create a normal TODO issue without `cloud-agent`, `local-agent`, or `backlog`.
- Stop after the Product Owner reports the issue URL. Do not start Architect, Engineer, create a branch, or create a PR.

## Steps

1. Pass the user's task description to `product-owner-agent`, using the standard `TASK-NAME:<name>` intake format.
2. Verify the Product Owner's report identifies a newly created issue and its URL.
3. Report the issue link and stop.

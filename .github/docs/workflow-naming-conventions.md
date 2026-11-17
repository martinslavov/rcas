# Workflow naming conventions

This document defines naming conventions for GitHub Actions workflows, jobs, and commit-status contexts.

## Goals

- Keep PR checks readable and consistent.
- Avoid accidental breakage of required checks due to rename-only changes.
- Distinguish between user-controlled names and GitHub-managed names.

## Naming rules

### Workflow name (`name:` at file root)

- Use **Title Case**.
- Keep names short and descriptive.
- Prefix CI workflows with `CI` when they are part of the required CI pipeline.

Examples:

- `CI Unit Tests`
- `CI Secret Scan`
- `Copilot Agent Dispatch`

### Job id (`jobs.<id>`)

- Use **lowercase kebab-case**.
- Treat job ids as stable identifiers.

Examples:

- `unit-tests`
- `secret-scan`
- `create-issue`

### Job display name (`jobs.<id>.name`)

- For non-required checks, use **Title Case** display names to improve readability in PR UI.
- Do not rename required checks unless branch protection/rulesets are updated in the same change window.

Examples:

- `Dispatch`
- `Create Issue`

### Status contexts set through API

Use exact canonical names:

- `PR Review`
- `QA Agent`
- `Definition of Done`

These are case-sensitive in practice and must remain stable.

## Required checks: rename policy

The following required checks are treated as frozen names unless rulesets are updated first:

- `unit-tests`
- `Component Tests (make up && make component-tests)`
- `Sanity Tests (make up && make sanity-tests)`
- `Static Review (checkstyle)`
- `QA Agent`
- `analyze`
- `dependency-review`
- `secret-scan`
- `PR Review`

## GitHub-managed check names

Some check names are controlled by GitHub and should not be normalized in repository code.

Example:

- `Code scanning results / CodeQL`


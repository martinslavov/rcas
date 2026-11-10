---
name: Dependabot PR Review
description: Reviews Dependabot GitHub Actions updates and reports the PR Review gate
on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main]
  bots: ["dependabot[bot]"]
permissions:
  contents: read
  pull-requests: read
  checks: read
max-ai-credits: 25
engine:
  id: copilot
  agent: pr-review-agent
network: defaults
tools:
  github:
    toolsets: [pull_requests, repos]
safe-outputs:
  create-check-run:
    name: PR Review
    target: triggering
    max: 1
  add-comment:
    target: triggering
    max: 1
    issues: false
    pull-requests: true
---

# Dependabot pull request review

Review only the Dependabot GitHub Actions update that triggered this workflow. Confirm the PR author is
`dependabot[bot]`, the base branch is `main`, and the head SHA is the current PR head. Use the `pr-review-agent`
review checklist and finding severities.

Do not run shell commands, modify files, merge the PR, or call GitHub write APIs directly. Publish one concise PR
comment with the review summary and exactly one check run named `PR Review`. Set the check run to `failure` if any
blocker or major finding exists; otherwise set it to `success`, including when only minor or nit findings remain.
Include the reviewed head SHA, findings, and actionable suggestions in the check run summary. Do not claim a finding
was fixed unless a later commit proves it.

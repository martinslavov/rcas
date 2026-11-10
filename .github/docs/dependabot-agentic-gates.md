# Automated Dependabot gates

Dependabot pull requests for GitHub Actions are reviewed by three GitHub Agentic Workflows in order:

1. **PR Review** runs when Dependabot opens or updates a PR. Blocker or major findings fail the gate.
2. **QA Agent** starts only after PR Review succeeds and all required CI checks have completed on the same head SHA.
3. **Definition of Done** starts only after QA and every required CI check succeed. When the tracking issue has no
   acceptance criteria, it applies the dependency-update criteria documented in the workflow.

The workflows are restricted to `dependabot[bot]` PRs targeting `main`. Agent jobs have read-only repository access;
GitHub Agentic Workflows publish the named check runs through their safe-output jobs. They never merge PRs. Each stage
is capped at 25 AI credits (up to $0.25 per stage and $0.75 for all three stages on one PR). A cap reached before a
valid result leaves the gate unsuccessful; it does not create a success result.

## One-time Copilot setup

This repository is user-owned, so the Copilot engine requires a fine-grained personal access token for inference:

1. Create a fine-grained token owned by your GitHub user account and grant only the **Copilot Requests: read** account
   permission.
2. In repository **Settings → Secrets and variables → Dependabot**, create the Dependabot secret
   `COPILOT_GITHUB_TOKEN`. Dependabot-triggered `pull_request` workflows cannot read ordinary Actions secrets.
3. Also create an Actions secret with the same name for the later `workflow_run` stages; GitHub's documented pattern
   for workflows that cross Dependabot and other event contexts is to use identically named secrets in both stores.
4. Never commit or paste the token into chat. Rotate or revoke it in GitHub if it is exposed.

The token is only used by GitHub Agentic Workflows for Copilot inference; the agent does not receive it as a tool
credential. GitHub Actions uses its own short-lived token for narrowly-scoped check runs and run-record comments.

Copilot Pro includes a monthly AI-credit allowance. The per-stage limit prevents one PR from consuming more than the
configured amount, but repeated PRs can use the monthly allowance. Review Copilot usage and ensure additional-usage
spending is disabled or budgeted in account billing settings if you do not want charges beyond the included allowance.

## Manual verification and recovery

The status checks are tied to the PR head SHA. A new push starts a fresh review chain. If an agentic run cannot
authenticate, exhausts its credit cap, or fails before publishing its check run, the required status remains missing
or fails and the PR stays blocked. Check the `Agent Run Records` workflow and the Agentic Workflow run logs; fix the
underlying problem and push a new Dependabot commit or rerun the workflow after correcting the setup.

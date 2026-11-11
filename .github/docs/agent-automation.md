# Issue-to-PR agent automation

## Setup

The workflow uses the GitHub Copilot cloud-agent assignment API with the repository's existing custom-agent profiles.
Copilot cloud agent must be enabled for the repository. Create a fine-grained user-to-server token for the repository
owner with Metadata read and Actions, Contents, Issues, and Pull requests read/write permissions, then save it as the
repository Actions secret `COPILOT_AGENT_TOKEN` under **Settings → Secrets and variables → Actions**. The workflow fails
with an actionable message if the secret is missing when a dispatch is requested. Do not put tokens in issue text.

The `agent-read` repository label is the opt-in switch. Create an issue using the normal issue template, include
acceptance criteria, then apply `agent-read` to start the flow. The label is read on the issue (starts the
Architect/Engineer stages) or on the PR (enables the PR Review → QA → merge stages for the linked issue); either
level is sufficient for PR stages, and a PR with no `PR Review` status yet starts at PR Review:

1. `architect-agent` posts a design note or auditable skip. If approval is required, the workflow waits for the repository
   owner to post `<!-- architecture-approved -->` with `Approved by @<owner> at <UTC timestamp>`; otherwise it dispatches
   the Engineer after the note.
2. `senior-java-software-engineer` implements the task and opens a PR with `Closes #<issue>`, then sets the agent status
   gates to pending.
3. `pr-review-agent` and `senior-qa-engineer` are dispatched in order from the corresponding
   status changes. `dod-validator-agent` is never dispatched by the automation (manual only; its status is informational).
   Failed agent gates or required CI checks dispatch the Engineer for a bounded fix iteration.
   The dispatcher also polls every five minutes to recover if a GitHub Actions-generated check event is not delivered.
   CI fix attempts are recorded on the PR across commit SHAs; a third failed attempt or a repeated failure signature
   adds `needs-human-review`, notifies the repository owner, and stops further dispatch until a human removes the label.
4. `ci-agent-auto-merge.yml` merges only an open PR linked to an issue, where the issue or the PR has `agent-read`, when all ruleset-required checks,
   `PR Review` and `QA Agent` succeed on the current head SHA and there are no human PR comments
   or reviews. It also checks `needs-human-review`. A five-minute poll handles check completion; a human can remove
   `needs-human-review` to resume a stopped task. After merge it records elapsed time on the issue and PR.

The five-minute poll also copies the label from the linked open `agent-read` issue (`Closes #N`) to its PR. No
`pull_request_target` trigger is used (see `security.md`).

**Latency:** labels added by `GITHUB_TOKEN` do not trigger workflows, and a label added manually to a PR only is not an
event the dispatcher reacts to. The label copy and the next stage therefore start at the nearest five-minute poll
(`*/5 * * * *`), not immediately. Status and check-suite events still dispatch the following stages immediately.

The workflows check out only the default branch and do not execute issue or PR content while handling the Copilot token
or merge permissions. If dispatch fails, inspect the `Copilot Agent Dispatch` run for a missing token, insufficient
token permissions, disabled cloud agent, or a GitHub API assignment error.

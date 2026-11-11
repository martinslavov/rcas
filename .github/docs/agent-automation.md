# Issue-to-PR agent automation

## Setup

The workflow uses the GitHub Copilot cloud-agent assignment API with the repository's existing custom-agent profiles.
Copilot cloud agent must be enabled for the repository. Create a fine-grained user-to-server token for the repository
owner with Metadata read and Actions, Contents, Issues, and Pull requests read/write permissions, then save it as the
repository Actions secret `COPILOT_AGENT_TOKEN` under **Settings → Secrets and variables → Actions**. The dispatch step fails
with an actionable message if the secret is missing when an assignment is requested. The cloud PR workflow also uses this
same existing secret only in its trusted PR-creation step: only its `POST /pulls` uses the user-to-server token so required
CI checks run. Checkout and all untrusted-content steps receive no such secret; the workflow `GITHUB_TOKEN` performs the
remaining guarded checks and intake. No additional secret is needed. Do not put tokens in issue text.

The `agent-read` repository label is the opt-in switch. On an issue, it starts Architect/Engineer automation. Input may be
prefixed with `TAG: agent-read`; the Product Owner consumes that metadata (using `.github/scripts/task_input.py`) and creates
the issue with `agent-read`, never copying the TAG line into the title/body. Plain `TASK-NAME:` remains the local/default flow;
`LABEL:BACKLOG,TASK-NAME:` retains its backlog behavior.

For the cloud path, the Engineer pushes `feature/<issue-number>-<task-name-slug>`. The isolated `ci-agent-pr-creation.yml`
workflow runs only from its trusted default-branch five-minute schedule; feature-branch pushes cannot execute its workflow
YAML with access to `COPILOT_AGENT_TOKEN`. The helper checks queued authorization records and validates the expected actor
against the GitHub user API, feature-branch-to-issue numbering, the open issue and `agent-read` label, implementation task
state, Engineer dispatch, and required Architect approval. It checks out only the trusted default branch. The helper
reuses a conforming PR with the workflow `GITHUB_TOKEN`; for a new PR, its single trusted helper step uses
`COPILOT_AGENT_TOKEN` only for PR creation (so required CI checks trigger), then uses
`GITHUB_TOKEN` for the guarded `orchestrator.py intake-pr-review <issue> --pr <pr> --agent-read`. Intake
removes issue-level `agent-read`, adds it to the PR, and starts the existing PR Review → QA → merge flow. The Engineer never
creates a PR. For auto-created cloud PRs, `pr-review-agent` owns filling the template's **Acceptance criteria → evidence**
section from the linked issue and implementation evidence before posting its review; the Engineer's tests and documentation
are the evidence sources.

For local work or work with an existing implementation branch but no cloud issue flow, use `/ship-pr agent-read` to
create/reuse the task issue and PR and start directly at PR Review. That skill uses the same PR template, relation and marker.
Its guarded intake records the PR head SHA and start marker. The PR label starts review without re-running Architect or Engineer:

1. `architect-agent` posts a design note or auditable skip. If approval is required, the workflow waits for the repository
   owner to post `<!-- architecture-approved -->` with `Approved by @<owner> at <UTC timestamp>`; otherwise it dispatches
   the Engineer after the note.
2. `senior-java-software-engineer` implements the task, commits and pushes its branch. For TAG cloud tasks the guarded
   PR-creation workflow creates/reuses the PR; for local tasks the main agent runs `/ship-pr`. The Engineer never creates a PR.
   For failure-fix assignments on an existing PR, it pushes the fix to that PR's branch.
3. When `/ship-pr agent-read` adds the label to the marked PR, `pr-review-agent` and `senior-qa-engineer` are dispatched in order from the corresponding
   status changes. `dod-validator-agent` is never dispatched by the automation (manual only; its status is informational).
   Failed agent gates or required CI checks dispatch the Engineer for a bounded fix iteration.
   The dispatcher also polls every five minutes to recover if a GitHub Actions-generated check event is not delivered.
   CI fix attempts are recorded on the PR across commit SHAs; a third failed attempt or a repeated failure signature
   adds `needs-human-review`, notifies the repository owner, and stops further dispatch until a human removes the label.
4. `ci-agent-auto-merge.yml` merges only an open `/ship-pr`-marked PR linked to an open issue, with `agent-read` on the PR,
   when all ruleset-required checks,
   `PR Review` and `QA Agent` succeed on the current head SHA and there are no human PR comments
   or reviews. It also checks `needs-human-review`. A five-minute poll handles check completion; a human can remove
   `needs-human-review` to resume a stopped task. After merge it records elapsed time on the issue and PR.

The dispatcher listens for a PR `labeled` event and also polls every five minutes to recover missed dispatches. The cloud
PR-creation workflow independently polls every five minutes from the default branch for its bot-authored authorization
comments, revalidates the current branch SHA and issue guards, and reuses an existing PR if creation succeeded but intake
did not. This recovers from interrupted creation/intake and GITHUB_TOKEN-authored labels/comments that do not emit
follow-up workflow events. It ignores
PRs without the `/ship-pr` marker,
an open linked task issue, and `agent-read` on the PR. No `pull_request_target` trigger is used (see `security.md`).

**Latency:** PR labels added with the user's `gh` credentials trigger the PR-label dispatcher. Labels added by
`GITHUB_TOKEN` do not trigger workflows, so the five-minute poll (`*/5 * * * *`) is the recovery path. Status and
check-suite events dispatch subsequent stages immediately.

The `<!-- ship-pr -->` marker and skill instructions make `/ship-pr` the supported PR creation route, but GitHub repository
permissions may still allow manual PR creation. Such PRs are not eligible for this automation unless they carry the marker,
link an open task issue, and have `agent-read` on the PR.

The workflows check out only the default branch and do not execute issue or PR content while handling the Copilot token
or merge permissions. If dispatch fails, inspect the `Copilot Agent Dispatch` run for a missing token, insufficient
token permissions, disabled cloud agent, or a GitHub API assignment error.

## Task-state record for every issue

`Issue Board Tracking` (`ci-issue-board.yml`) runs on every opened issue. After placing it on the board it seeds the
orchestrator task-state record with `orchestrator.py init <issue> --state backlog|todo --agent human` (`backlog` when the
issue has the `backlog` label, otherwise `todo`). Issues created directly with `gh issue create` or the web form therefore
also get a `state:*` label and canonical record, so later `orchestrator.py transition` calls do not fail. The `/ship-pr`
handoff uses the dedicated `intake-pr-review <issue> --pr <pr> [--agent-read]` command, which validates the linked marked PR
and permits only the narrow `todo|implementation → pr-review` entry; ordinary transition rules remain unchanged. If the Product
Owner already seeded a record, the step is a no-op. The step authenticates repository calls (comment, labels) with the job `GITHUB_TOKEN` (`issues: write`); `PROJECT_TOKEN` is passed only as `PROJECT_TOKEN` and used by `task_queue.sh` for the Projects GraphQL calls. Issues opened before this workflow change are not backfilled; seed
them manually with `orchestrator.py init`.

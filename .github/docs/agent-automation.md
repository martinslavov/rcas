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

The `cloud-agent` repository label is the opt-in switch. On an issue, it starts Architect/Engineer automation. Canonical
task input starts with `TASK-NAME:<name>`, optionally followed by `DEVELOPMENT: low|medium|high` and
`TAG: cloud-agent,local-agent,skip-architect,skip-product-owner` (any supported subset; do not combine the two worker labels), then a description (optionally introduced by
`DESCRIPTION:`). `.github/scripts/task_input.py` consumes this metadata; `DEVELOPMENT` becomes a `development:<level>`
issue label, and control lines are never copied into the issue title/body. `skip-product-owner` tells the main agent to
create a concise task issue directly instead of invoking Product Owner. `skip-architect` lets the selected flow start Engineer directly and
explicitly bypasses architecture comments and approval, including the `architecture-approval-required` gate. This opt-out
does not bypass cloud branch/actor verification, PR creation safeguards, CI, PR Review, QA or merge gates. The legacy
first-line TAG order remains accepted. `LABEL:BACKLOG,TASK-NAME:` retains its backlog behavior and may also have metadata.

For the cloud path, the Engineer pushes `feature/<issue-number>-<task-name-slug>`. The isolated `ci-agent-pr-creation.yml`
workflow runs only from its trusted default-branch five-minute schedule; feature-branch pushes cannot execute its workflow
YAML with access to `COPILOT_AGENT_TOKEN`. Each scheduled poll itself discovers eligible work: it reads the newest `PushEvent` per `feature/<issue>-*` branch
from the GitHub repository events feed (all pages GitHub exposes, up to 300 events; actor identity is recorded by GitHub, never taken from commit author text). As a durable fallback for pushes that aged out of that feed, it lists the `feature/<issue>-*` branches of open `cloud-agent` issues and reads each branch's GitHub push activity (`/activity?ref=…&activity_type=push`); a branch that fails (deleted, rate limited) is skipped and retried on the next poll. It then
writes an authorization record only after re-validating it, and also retries queued records. It validates the expected
actor and id against the GitHub user API, that the pushed SHA is still the branch head, feature-branch-to-issue numbering, the open issue and `cloud-agent` label, implementation task
state, Engineer dispatch, and required Architect approval unless `skip-architect` is present. It checks out only the trusted default branch. The helper
reuses a conforming PR with the workflow `GITHUB_TOKEN`; for a new PR, its single trusted helper step uses
`COPILOT_AGENT_TOKEN` only for PR creation (so required CI checks trigger), then uses
`GITHUB_TOKEN` for the guarded `orchestrator.py intake-pr-review <issue> --pr <pr> --cloud-agent`. Intake
removes issue-level `cloud-agent`, adds it to the PR, and starts the existing PR Review → QA → merge flow. The Engineer never
creates a PR. For auto-created cloud PRs, `pr-review-agent` owns filling the template's **Acceptance criteria → evidence**
section from the linked issue and implementation evidence before posting its review; the Engineer's tests and documentation
are the evidence sources.

For local work or work with an existing implementation branch but no cloud issue flow, use `/create-pr-cloud` to
create/reuse the task issue and PR and start directly at PR Review. That skill uses the same PR template, relation and marker.
Its guarded intake records the PR head SHA and start marker. The PR label starts review without re-running Architect or Engineer:

1. `architect-agent` posts a design note or auditable skip. If approval is required, the workflow waits for the repository
   owner to post `<!-- architecture-approved -->` with `Approved by @<owner> at <UTC timestamp>`; otherwise it dispatches
   the Engineer after the note. With `skip-architect`, it dispatches Engineer directly and the explicit label bypasses
   this architecture approval gate.
2. `senior-java-software-engineer` implements the task, commits and pushes its branch. For TAG cloud tasks the guarded
   PR-creation workflow creates/reuses the PR; local worker or interactive task coordinators handle local task PRs. The Engineer never creates a PR.
   For failure-fix assignments on an existing PR, it pushes the fix to that PR's branch.
3. When `/create-pr-cloud` adds the label to the marked PR, `pr-review-agent` and `senior-qa-engineer` are dispatched in order from the corresponding
   status changes. `dod-validator-agent` is never dispatched by the automation (manual only; its status is informational).
   Failed agent gates or required CI checks dispatch the Engineer for a bounded fix iteration.
   The dispatcher also polls every five minutes to recover if a GitHub Actions-generated check event is not delivered.
   CI fix attempts are recorded on the PR across commit SHAs; a third failed attempt or a repeated failure signature
   adds `needs-human-review`, notifies the repository owner, and stops further dispatch until a human removes the label.
4. For task PRs, `ci-agent-auto-merge.yml` merges only an open PR bearing `<!-- ship-pr -->` linked to an open issue, with `cloud-agent` on the PR,
   when all ruleset-required checks,
   `PR Review` and `QA Agent` succeed on the current head SHA and there are no human PR comments
   or reviews. It also checks `needs-human-review`. A five-minute poll handles check completion; a human can remove
   `needs-human-review` to resume a stopped task. After merge it records elapsed time on the issue and PR.

The dispatcher listens for a PR `labeled` event and also polls every five minutes to recover missed dispatches. The cloud
PR-creation workflow independently polls every five minutes from the default branch for its bot-authored authorization
comments, revalidates the current branch SHA and issue guards, and reuses an existing PR if creation succeeded but intake
did not. This recovers from interrupted creation/intake and GITHUB_TOKEN-authored labels/comments that do not emit
follow-up workflow events. Task PRs need the `<!-- ship-pr -->` marker, an open linked task issue and `cloud-agent` on the PR.
No `pull_request_target` trigger is used
(see `security.md`).

**Latency:** PR labels added with the user's `gh` credentials trigger the PR-label dispatcher. Labels added by
`GITHUB_TOKEN` do not trigger workflows, so the five-minute poll (`*/5 * * * *`) is the recovery path. Status and
check-suite events dispatch subsequent stages immediately.

For task PRs, the `<!-- ship-pr -->` marker and skill instructions make `/create-pr-cloud` the supported creation route. Other
PRs are not eligible for task automation unless they carry that marker, link an open task issue, and have `cloud-agent`
on the PR.

The workflows check out only the default branch and do not execute issue or PR content while handling the Copilot token
or merge permissions. If dispatch fails, inspect the `Copilot Agent Dispatch` run for a missing token, insufficient
token permissions, disabled cloud agent, or a GitHub API assignment error.

## Local autonomous worker

The cloud path above remains the GitHub-hosted option: create an owner-authored issue with `cloud-agent`, and GitHub Actions
assigns its Architect/Engineer stages to Copilot cloud agent. `COPILOT_AGENT_TOKEN` and enabled cloud-agent access are
required; the local worker does not repair or replace that setup.

For local execution, create an owner-authored issue with `local-agent` instead of `cloud-agent`. The tags are mutually
exclusive, and the worker rejects issues authored by anyone other than `martinslavov`, as well as `backlog`,
`requires-pro`, failed, or human-review tasks. Issues without either label are never picked up by a background worker.
After issue creation, the current session reports the issue URL and stops without invoking or waiting for the worker or
any implementation, review or QA agent. This handoff applies regardless of skip tags: `skip-product-owner` makes the
current session create the issue directly, and `skip-architect` makes the worker start Engineer without Architect or
architecture approval. The worker must be started separately; the issue waits if it is not running or its task-state
record is not yet available. Backlog tasks remain parked.
Use `/create-issue` for Product Owner intake only, then implement the TODO issue yourself. The no-task-issue shortcut is
`/create-pr-local`; it creates a PR directly and does not create the automatic PR tracking issue.

Run the local worker manually from a clean, up-to-date `main` checkout:

```bash
python3 .github/scripts/local_agent_worker.py
python3 .github/scripts/local_agent_worker.py --once
python3 .github/scripts/local_agent_worker.py --workers 2
```

The default polls every 60 seconds and processes one task at a time; `--workers N` runs independent issues concurrently.
Use `Ctrl+C` to stop it. A repository-local file lock prevents a second worker process from taking the same queue. Each task
has a dedicated worktree under `../rcas-sessions/` and named Copilot CLI sessions for Architect, Engineer, PR Review and QA.
If the Mac sleeps or is off, the queue waits; restarting the command resumes from the issue's recorded state, branch and PR.
No Copilot model is invoked while the queue is empty; eligible tasks consume normal Copilot CLI usage.

The worker requires `gh` authenticated as `@martinslavov`, the Copilot CLI, write access to the repository, and Docker/JDK
availability for tests that require them. It runs Copilot in non-interactive `--allow-all-tools` mode, which permits code
and shell tools in the isolated worktree. Only use it for owner-authored issues that you trust. It does not expose a cloud
Actions secret, but local GitHub credentials are available to the worker process. Architecture approval is required when
applicable unless `skip-architect` is present. PR Review, QA, all required CI checks on the current head SHA, absence of
human PR comments, and absence of `needs-human-review` are required before merge. If a stage fails, the worker adds
`local-agent-failed` and will not spend more tokens on that issue;
inspect the failure, then remove that label to retry. If `needs-human-review` is also present, only a human may remove it;
remove both labels when explicitly resuming. The worker never force-pushes, merges while a gate is pending, or bypasses a
failed orchestrator transition.

## Manual and quick PR flows

- **Manual issue:** invoke `/create-issue` with the task description. Product Owner creates a TODO issue and stops; no worker,
  Architect, Engineer, branch, or PR starts. Implement it yourself later, or start a separate task flow when ready.
- **Local PR:** invoke `/create-pr-local` for a small change without a task issue. The PR body contains
  `<!-- no-task-issue -->`, so PR Issue Tracking skips its usual tracking issue. The current local session invokes PR Review
  and then QA, verifies all current-head merge gates and merges if they pass. A failure stops for human action; an explicit
  request to keep the PR open is honored. The local flow never adds `cloud-agent` or the cloud opt-in marker.
  Previously opted-in no-issue cloud PRs retain their existing guarded dispatch and merge behavior.

## Task-state record for every issue

`Issue Board Tracking` (`ci-issue-board.yml`) runs on every opened issue. After placing it on the board it seeds the
orchestrator task-state record with `orchestrator.py init <issue> --state backlog|todo --agent human` (`backlog` when the
issue has the `backlog` label, otherwise `todo`). Issues created directly with `gh issue create` or the web form therefore
also get a `state:*` label and canonical record, so later `orchestrator.py transition` calls do not fail. The `/create-pr-cloud`
handoff uses the dedicated `intake-pr-review <issue> --pr <pr> --cloud-agent` command, which validates the linked marked PR
and permits only the narrow `todo|implementation → pr-review` entry; ordinary transition rules remain unchanged. If the Product
Owner already seeded a record, the step is a no-op. The step authenticates repository calls (comment, labels) with the job `GITHUB_TOKEN` (`issues: write`); `PROJECT_TOKEN` is passed only as `PROJECT_TOKEN` and used by `task_queue.sh` for the Projects GraphQL calls. Issues opened before this workflow change are not backfilled; seed
them manually with `orchestrator.py init`.

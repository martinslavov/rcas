# Task workflow rules

Write all repository documentation in English, including documentation updates, README content, skills, agent instructions, and workflow guides.

These rules apply when task input starts with `TASK-NAME:<task-name>` (for example `TASK-NAME:code-review-agent` or `TASK-NAME:Code review agent`), optionally followed by `DEVELOPMENT: low|medium|high` and `TAG: <label[,label...]>`. Supported tags are `cloud-agent`, `local-agent`, `skip-architect`, and `skip-product-owner`. A `DESCRIPTION: <text>` prefix on the description is optional. The legacy order with `TAG: cloud-agent` on line 1 remains accepted, as does `LABEL:BACKLOG,TASK-NAME:<task-name>` with optional metadata after the task name. Tasks without a task-name control line are handled normally, without creating an issue or branch unless needed. Use `/create-pr-cloud` to hand a task-linked PR to cloud automation and `/create-pr-local` for local review of a PR without a task issue.

The supported task tags are `cloud-agent`, `local-agent`, `skip-architect`, and `skip-product-owner`; `cloud-agent` and
`local-agent` are mutually exclusive. `/create-pr-local` is the no-task-issue PR path.

## Task input and queue (Backlog / TODO)

The RCAS Tracking board has the Status columns `Backlog`, `Assessment`, `Defining`, `TODO`, `In Progress` and `Done`.
`.github/scripts/task_queue.sh list` prints open `TODO` issues oldest first. `task_queue.sh move` is an internal board projection only; agents must not use it to change task stages.

- Canonical input starts with `TASK-NAME:<name>`, optionally followed by `DEVELOPMENT: low|medium|high`, then
  `TAG: cloud-agent,local-agent,skip-architect,skip-product-owner` (any supported subset), and then the description. Metadata lines may
  appear in either order. The optional `DEVELOPMENT` value is recorded as a `development:<level>` issue label. An optional
  leading `DESCRIPTION:` prefix is stripped. Never include control lines in the issue title/body.
- `skip-product-owner` means do not invoke `product-owner-agent`; the main agent parses the input and creates a concise task
  issue directly, preserving the supplied description and labeling it with all parsed metadata. Without this tag, follow
  the normal Product Owner intake.
- `skip-architect` means do not invoke `architect-agent`; the Engineer starts directly from `TODO` and may proceed without
  design comments or architecture approval, even when `architecture-approval-required` is present. This is an explicit
  user opt-out. With `cloud-agent`, cloud dispatch starts the Engineer directly; the guarded branch/actor/PR checks and all
  post-implementation review, QA, CI and merge gates remain in force.
- `local-agent` opts an owner-authored issue into `.github/scripts/local_agent_worker.py`; it runs local Copilot CLI sessions
  in separate Git worktrees and handles PR Review, QA, CI and merge. Never combine it with `cloud-agent`. Issues from other
  authors, `backlog`, `requires-pro`, failed, or human-review tasks are not run.
- **Local-worker handoff takes precedence over all task-stage instructions below.** For any `local-agent` task, create the
  issue with every parsed label, report its URL and that it is queued for the separately started local worker, and end the
  current turn. Do not start or wait for Architect, Engineer, PR Review, QA, CI or merge in the current session, and do not
  start the worker on the user's behalf. This applies with or without either skip tag. Do not claim that the worker is
  running or has picked up the issue unless verified. A `backlog` issue remains parked.
- Cloud tasks use the `cloud-agent` label and `/create-pr-cloud` handoffs.
- `/create-issue` invokes the Product Owner and stops after creating a normal TODO issue; no Architect, Engineer, branch,
  or PR is started. Use it when you want to implement the issue yourself later.
- When both skip tags are present, create the issue directly. For `local-agent`, end the current turn as described above;
  the worker starts the Engineer. For other eligible task flows, start the Engineer through that flow. Other labels and issue
  controls, including `backlog`, continue to apply.
- `TASK-NAME:<name>` (default, no TAG): the Product Owner creates the issue without `backlog`, `cloud-agent` or `local-agent`;
  it lands in `TODO` for the interactive local flow and is not picked up by a background worker. Use `/create-issue` when
  you want Product Owner intake only and will implement the issue yourself later.
- `TASK-NAME:<name>` with `TAG: local-agent`: create an owner-authored issue through Product Owner unless
  `skip-product-owner` is present, in which case the main agent creates it directly. Report the URL and stop. The separately
  started worker creates an isolated worktree and local Copilot sessions, creates a marked PR, runs the normal review/QA/CI
  gates and merges only when every required condition passes.
- `LABEL:BACKLOG,TASK-NAME:<name>` (the `LABEL:` prefix is case-insensitive; the description follows as usual): the Product
  Owner creates the issue with the `backlog` label, so it lands in `Backlog`. Stop after the issue is created and report its
  link; no Architect, branch or PR. Backlog items are never processed while they are in `Backlog`. An optional second-line
  `TAG: cloud-agent` adds both labels; cloud processing still waits until the issue is moved out of Backlog.
- To start a backlog task, seed a missing record with `orchestrator.py init <issue> --state backlog --agent human`, then the human uses
  `orchestrator.py transition <issue> todo --agent human`; the transition projects the board Status and removes the legacy
  `backlog` label. Agents must not use `task_queue.sh move` directly to change a task stage.
- TODO items are picked up when a session is active: after every merged task and whenever the user asks to process the queue
  (for example `RUN-QUEUE`), run `task_queue.sh list` and process items one at a time, oldest first. For a queued issue the
  Product Owner step is already done: the Architect starts it with `todo → architecture` using its own agent id. Merging
  projects the item to `Done`. For queued issues, elapsed time starts when picked up from `TODO`.
- For an issue that is ready for autonomous work, add the `cloud-agent` label. The Copilot cloud-agent workflow starts
  `architect-agent` first, unless `skip-architect` explicitly opts out; otherwise it starts the Engineer only after an
  auditable skip/design note says approval is not required, or after the repository owner posts
  `<!-- architecture-approved -->` for an issue labelled `architecture-approval-required`. For `TAG: cloud-agent` tasks,
  the Engineer pushes the issue-numbered feature branch;
  `ci-agent-pr-creation.yml` creates/reuses the marked PR and performs guarded PR Review intake. For local/manual tasks, the
  main agent runs `/create-pr-cloud` after the Engineer handoff. Both paths put `cloud-agent` on the PR (not the issue),
  then proceed through PR Review → QA. A failed stage returns to the
  Engineer, and `needs-human-review` stops dispatch until a human removes that label. A separate merge gate merges only
  cloud-agent PRs whose required checks and the `PR Review` and `QA Agent` statuses succeed on the current
  head SHA, with no human PR comments/reviews. Dispatch and merge gates poll every five minutes while checks/statuses are
  pending.
  Setup and token permissions are documented in `.github/docs/agent-automation.md` and `.github/docs/security.md`.
- For local autonomous work, use `local-agent` instead of `cloud-agent` and start
  `python3 .github/scripts/local_agent_worker.py` from a clean, up-to-date `main` checkout. It processes owner-authored
  issues oldest first, one per local session by default; `--workers N` or multiple worker processes enable independent concurrent
  issue worktrees. Per-issue locks coordinate processes sharing the same Git repository, not separate clones. It
  uses Copilot CLI's non-interactive `--allow-all-tools` mode, so only explicitly opted-in trusted tasks may be processed.
  An issue stopped by a local failure receives `local-agent-failed`; remove that label to retry. The worker does not process
  `requires-pro`, backlog, or `needs-human-review` tasks. See `.github/docs/agent-automation.md`.
- **EPICs** group related sub-issues (GitHub sub-issues) and carry the `epic` label. Move an EPIC to `In Progress` when it is
  created; it is never processed from the queue itself and has no branch or PR. Its sub-issues are normal tasks (usually created
  in `Backlog` and moved to `TODO` when ready, respecting dependencies listed in the EPIC). Close the EPIC when all sub-issues
  are closed. The roadmap of EPICs is in `.github/docs/roadmap.md`.
- **Roadmap improvement tasks** (the five roadmap tasks): each task becomes one EPIC with feasible sub-issues in `Backlog`,
  each needing its own architecture approval. The project runs on GitHub Free and Copilot Free: any part that needs a paid
  plan (or an organization-owned repository) becomes a separate `Backlog` issue with the `requires-pro` label and is added
  to `.github/docs/pro-plan.md`. Never start `requires-pro` issues on the current plan.

## Workflow orchestrator

`.github/scripts/orchestrator.py` owns each task's canonical state record and projects it to one `state:<state>` label and the board Status. Use `python3 .github/scripts/orchestrator.py state <issue>` to inspect it, `init <issue> --agent <id> [--state <state>]` once to seed an issue that has no record (only `backlog` or `todo` may be seeded, for any agent including `human`; any other `--state` is refused before any GitHub call, and every later state must be reached through `transition`, which enforces the owner and edge table), `reconcile <issue>` to idempotently repair the `state:*` label and board Status from the canonical record after a projection failure, and `transition <issue> <to> --agent <id> [--head-sha <sha>] [--dry-run]` for every stage change. Never overwrite an existing record with `init`. The acting agent passes its own id; human-only changes use `--agent human`. `--agent` is self-declared and is not an authorization. Migrating in-flight tasks to later states is out of scope for #101: it is a separate, human-performed rollout step to be designed later (for example, the remaining EPIC #107 work can add a verified migration).

Rollout starts in report mode: if an orchestrator call fails, report the failure and do not silently bypass it or proceed as though the transition succeeded.

## Agents

Six custom agents (in `.github/agents/`) do the work:

- `product-owner-agent`: Senior Product Owner, analyzes the task and creates the issue.
- `architect-agent`: Senior Software Architect, posts a design note or an auditable skip and identifies changes requiring user approval; never changes code.
- `senior-java-software-engineer`: Senior Java Software Engineer, implements the issue and pushes the branch. PR creation is handled through `/create-pr-cloud`.
- `pr-review-agent`: independent PR Reviewer, reviews the complete diff, posts severity-ranked findings and sets `PR Review`.
- `senior-qa-engineer`: Senior QA Engineer, reviews and tests the PR and sets the `QA Agent` commit status.
- `dod-validator-agent`: Definition of Done Validator, **manual only**: no workflow, orchestrator stage or other agent starts it; it runs only when the user explicitly asks. Maps every acceptance criterion of the linked issue to
  concrete behaviour-verifying evidence, posts the AC → evidence table and sets the `Definition of Done` commit status; never
  changes code.

For `local-agent`, perform only issue intake and return as specified in **Local-worker handoff** above; the worker owns
all later stages. For other `TASK-NAME:` tasks, run the applicable stages in order (the main agent coordinates):
Product Owner (unless `skip-product-owner`) → Architect (unless `skip-architect`) → user approval when required →
Engineer → `/create-pr-cloud` → PR Review → QA → merge → elapsed time recorded on the issue and PR:

1. Unless `skip-product-owner` is present, delegate the whole input to `product-owner-agent`. It returns the issue number,
   URL and the branch name. With `skip-product-owner`, parse the input with `.github/scripts/task_input.py` and create the
   issue directly using the parsed task name, description and labels; do not invoke Product Owner. For `local-agent`, report
   the issue URL and stop here; do not proceed to step 2 or any later step in this session.
2. Unless `skip-architect` is present, delegate the issue to `architect-agent`. It posts exactly one design note comment containing
   `<!-- architect-design-note -->` with affected components, interfaces/contracts, data/migrations, risks/mitigations,
   test plan and `Approval required: yes/no`, or an auditable skip comment containing `<!-- architect-skipped -->` and
   `skipped: <reason>`.
3. If the issue has `architecture-approval-required` and does not have `skip-architect`, show the design note to the user and stop before the Engineer starts.
   Do not proceed on silence or inferred consent. Continue only after the user explicitly approves and the issue has an
   `<!-- architecture-approved -->` comment that records who approved and when. Approval is required for architecture
   changes (new module/layer/component or cache topology), database schema/migrations, messaging/Kafka, public HTTP API
   (endpoints, payloads or status codes), or security (authentication, authorization, secrets, cryptography or
   security-relevant dependencies).
4. Delegate the issue (number, branch name, Architect comment if applicable, and original input) to
   `senior-java-software-engineer` after the approval gate is satisfied, Architect has documented a skip, or
   `skip-architect` is present. It implements the task, commits and pushes the
   branch, then hands it back to the main agent. It must not create a PR. The main agent fetches and checks out that exact
   branch. For `TAG: cloud-agent` issues, the isolated trusted workflow creates/reuses the template PR and runs guarded PR
   Review intake. For a cloud handoff, the main agent uses `/create-pr-cloud`, whose guarded intake starts cloud PR Review
   without re-running Architect or Engineer; stop local coordination after handoff. For issue-backed interactive local work,
   the coordinator creates the marked task PR and calls `orchestrator.py intake-pr-review <issue> --pr <pr>` without
   `--cloud-agent`, sets gates to pending, and owns the PR template's "Acceptance criteria → evidence" section.
5. For the interactive local task path only, delegate the PR number to `pr-review-agent`. It independently reads the issue and full diff, posts its findings, and always
   sets a final `PR Review` status on the current head SHA. For `architecture-approval-required` issues, it also verifies
   the implementation against the approved design note; a material deviation is at least `major`, and it requires backward
   compatibility evidence plus migration and rollback considerations for schema changes. On blocker/major findings, the engineer fixes them, pushes, resets the
   gates (`PR Review`, `QA Agent`; `Definition of Done` stays informational) to `pending`, and hands the updated PR back to PR Review. The loop is bounded at five rounds; on a
   round-5 failure, the agent applies `needs-human-review` and escalates to the user. Only a human removing the label resumes it.
6. For the interactive local task path only, after `PR Review` is `success` on the current head SHA, delegate the PR number to `senior-qa-engineer`. QA reviews the
   change, runs the relevant checks and sets `QA Agent` on the head SHA to `success` or `failure` (it must always set a final
   status). On QA failures before round 5, the engineer fixes and pushes, resets the statuses to `pending`, and hands over to PR
   Review first, then QA after PR Review succeeds. QA round-5 failure has the same human-review stop and resumption semantics.
7. **DoD is manual only and is not part of any automatic flow.** Never delegate to `dod-validator-agent` unless the user explicitly asks for it; it is not required for merge. When the user does ask, it reads the issue
   linked by `Closes #N`, maps every acceptance criterion to concrete evidence (a test that verifies the behaviour, not merely that
   a class exists; e.g. cache expiry needs a test asserting expiration after the TTL; for docs/process criteria a `file:line` or a
   verified command output), posts a PR comment with `<!-- dod-validation sha:<head-sha> -->` and a table
   `# | Acceptance criterion | Evidence | Verdict` (`met`, `weak`, `missing`), and always sets `Definition of Done` on the head SHA:
   `success` only when every criterion is `met`, otherwise `failure` (also `no acceptance criteria` when the issue has none).
   A manual DoD failure is reported to the user and does not dispatch the engineer. Its rounds use `<!-- dod-round:N -->` markers (count per PR, independent of
   the other counters).
8. For the interactive local task path, report the issue and PR links, merge status and total elapsed time (see "Elapsed time" below). The main agent merges by default
   only when all required checks pass, `PR Review` and `QA Agent` are `success` on the current head SHA, `needs-human-review`
   is absent, and no human comments or unresolved blocker/major findings remain. Resolved findings do not block after the relevant current-head
   status succeeds. Do not merge if the user asks to keep the PR open. After the merge, record the elapsed time on the issue and
   the PR with `.github/scripts/post_task_elapsed.sh` (see "Elapsed time"). Then check the queue (`task_queue.sh list`) and
   continue with the oldest `TODO` issue, if any.

The steps below are what the agents follow:

1. **Issue.** Create a GitHub issue for the task with `gh issue create` (title from the task name, written as readable text and a short description of the goal).
   The issue form is `.github/ISSUE_TEMPLATE/issue.yml`; the `CI Issue Board` workflow puts it on the board as `Backlog` when it has the
   `backlog` label, otherwise as `TODO` (see "Task input and queue").
2. **Branch.** Create the branch from an up-to-date `main` and work only there. For a cloud `cloud-agent` issue use
   `feature/<issue-number>-<task-name-slug>` (for example `feature/198-cloud-agent-flow`); the issue number is the trusted
   association used by the cloud PR-creation guard. For local work retain `feature/<task-name>`. If the value after
   `TASK-NAME:` is already a slug (lowercase, words separated by `-`), use it as is. Otherwise derive a short meaningful slug
   in lowercase ASCII letters, digits and `-` only. Only `feature/*` and `hotfix/*` branches can be created.
3. **Work.** Before creating a branch or implementing, the engineer reads the Architect design note or confirms the skip comment, unless `skip-architect` is present. If `architecture-approval-required` is present without `skip-architect`, the engineer must find the explicit `<!-- architecture-approved -->` user comment first; otherwise stop without creating a branch or changing files. Commit the changes with clear messages. Never push to `main` directly.
4. **Pull request.** When implementation is complete, the Engineer pushes the branch and hands it to the main agent. For a cloud
   handoff, run `/create-pr-cloud`; for an issue-backed interactive local task, the coordinator creates the PR against `main`
   using `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md` and performs intake without `--cloud-agent`.
   Reference that issue under
   "Pull-request relations" as `Closes #N`: GitHub closes it on merge and `PR Issue Close` moves it to Done. Include the
   `<!-- ship-pr -->` marker. The Engineer never runs `gh pr create`.
   The `PR Issue Tracking` workflow adds the tracking issue link to the description. Do not put review, QA or CI/check-status
   claims in the PR description (including "no review performed" or "QA pending"); commit statuses and check runs are the
   source of truth. The testing section may list only local commands actually run and their results; if none were run, leave it without test-result entries rather than adding prose about unrun tests. Required checks (unit, component and sanity tests and
   all agent statuses) must pass before merging. In the interactive local task path, right after opening the PR and after every new
   push, the coordinator sets the agent gates to pending (`Definition of Done` is informational):
   `gh api -X POST repos/martinslavov/rcas/statuses/<head-sha> -f state=pending -f context="PR Review" -f description="Waiting for PR review"`
   `gh api -X POST repos/martinslavov/rcas/statuses/<head-sha> -f state=pending -f context="QA Agent" -f description="Waiting for QA"`
   `gh api -X POST repos/martinslavov/rcas/statuses/<head-sha> -f state=pending -f context="Definition of Done" -f description="Manual only - not run by flows"`
   (head SHA: `gh pr view <n> -R martinslavov/rcas --json headRefOid -q .headRefOid`). PR Review runs before QA; DoD runs only on explicit user request.
   In `/create-pr-cloud`, the intake action adds `cloud-agent` to the PR and the dispatcher starts PR Review;
   the cloud push workflow performs the same guarded intake for `TAG: cloud-agent` issues. Do not set these gates manually or
   invoke review/QA agents directly.
   On blocker/major findings, the engineer fixes, pushes, resets the statuses to pending and hands back to PR Review. Minor/nit
   findings are reported but do not block QA. Count rounds from PR comments containing `<!-- pr-review-round:N -->`; on round 5
   failure apply `needs-human-review`, mention `@martinslavov`, and stop. Only a human removing the label resumes; retain all markers.
5. **Bounded PR Review loop.** Every PR Review report includes `<!-- pr-review-round:N -->`. Derive the round from issue comments and review bodies (the report is posted as an issue comment; duplicate N are deduplicated):
   `(gh api repos/martinslavov/rcas/issues/<pr>/comments --paginate --jq '.[].body'; gh api repos/martinslavov/rcas/pulls/<pr>/reviews --paginate --jq '.[].body') | grep -o '<!-- pr-review-round:[0-9]* -->' | sort -u | wc -l`
   Round = distinct marker count + 1. Blocker/major findings fail the status; the engineer fixes and pushes, resets all three statuses, then PR Review
   repeats before QA. Minor/nit findings do not block QA. On round 5 failure, apply `needs-human-review`, mention `@martinslavov`,
   and stop agent work. Only a human removing the label resumes the loop; retain markers and continue counting above round 5.
6. **Bounded QA loop.** Every QA failure report comment includes a hidden `<!-- qa-round:N -->` marker. QA derives the next round from the
   count of these markers on that PR (not agent memory; the count is per PR), using this exact command with `<pr>` replaced by the PR number:
   `gh api repos/martinslavov/rcas/issues/<pr>/comments --paginate -q '[.[] | select(.body | contains("<!-- qa-round:"))] | length'`.
   Below round 5, QA sets `QA Agent` to `failure` with actionable findings; the engineer fixes, pushes, resets all three statuses and sends the PR through PR Review before QA retests. A human removing the label resumes this loop; thereafter, continue it for subsequent rounds, retaining all markers. On round 5 failure,
   QA sets failure with description `QA iteration limit (5) reached – human review required`, applies `needs-human-review`, and posts an
   escalation comment mentioning `@martinslavov` that summarizes open findings and the round count. Create the label if missing using:
   `gh label create needs-human-review -R martinslavov/rcas --color B60205 --description "Automated iteration limit reached; human review required" 2>/dev/null || true`.
   Add it via `gh api -X POST repos/martinslavov/rcas/issues/<pr>/labels -f 'labels[]=needs-human-review'`; do not use `gh pr edit` because it
   fails with a Projects classic error. The engineer makes no further fix commits or merge while the label is present. Automated agents never
   remove it; only a human removing it explicitly resumes the loop. Existing round markers remain the source of truth after resumption.
7. **Bounded CI fix loop.** For failed non-agent required checks (including `analyze`, `dependency-review` and `secret-scan`),
   the engineer follows the diagnosis/reproduction commands and signature rules in `engineer.agent.md`.
   Read the current head's failed checks with `gh pr checks <pr> -R martinslavov/rcas --json name,state,link`; identify the
   matching run from `gh run list -R martinslavov/rcas --branch <branch> --json databaseId,name,conclusion,headSha,url`,
   read `gh run view <id> -R martinslavov/rcas --log-failed` and download test reports when available. The first failing
   test or normalized error defines `<check name>|<test id or error>`; prefix infrastructure failures with `infra:`.
   Each fix attempt (including the one allowed infrastructure `gh run rerun <id> -R martinslavov/rcas --failed`) gets one
   PR issue comment **before** the fix/re-run with `<!-- ci-fix-attempt:N -->` and `<!-- ci-failure-signature:<sig> -->`.
   N is the count of existing marker comments plus one, not agent memory:
   `gh api repos/martinslavov/rcas/issues/<pr>/comments --paginate -q '[.[] | select(.body | contains("<!-- ci-fix-attempt:"))] | length'`.
   If paginated, aggregate via `gh api repos/martinslavov/rcas/issues/<pr>/comments --paginate --slurp | jq '[.[][] | select(.body | contains("<!-- ci-fix-attempt:"))] | length'`.
   After a push, reset all three agent statuses and repeat PR Review before QA. If attempt 3 still fails, or if the current
   signature matches the immediately preceding attempt's signature (even below 3), stop: apply `needs-human-review` via
   the Issues API and mention `@martinslavov` with check name, run URL, signature, count and short log excerpt. No fourth
   attempt, further commit or merge. CI attempts, QA failure rounds (`<!-- qa-round:N -->`) and PR Review rounds
   (`<!-- pr-review-round:N -->`) are **independent** counters. Any stop uses the same label, with description
   `Automated iteration limit reached; human review required`. No agent commits or merges while the label is present;
   automated agents never remove it. Only a human removing it explicitly resumes the loop: keep all markers and continue
   numbering above the original numeric limit without re-applying that limit; repeated-signature early stop still applies.
8. **Merge (default).** The main agent waits for all checks and `PR Review` and `QA Agent` success on the current head SHA (`Definition of Done` is not required). Before any merge, check the review label with
   `gh api repos/martinslavov/rcas/issues/<pr>/labels -q '.[].name | select(. == "needs-human-review")'`; if present, do not merge.
   Ignore tracking/workflow automation comments. Resolved QA findings do not by themselves block auto-merge after QA succeeds on the current
   head SHA; unresolved blocker/major findings and any human (non-agent/non-automation) comment continue to block it. If all checks pass, the label is absent,
   and no human comments or unresolved blocker/major findings remain, merge with `gh pr merge <n> -R martinslavov/rcas --merge --delete-branch`; this closes
   the task issue (`Closes #N`) and tracking issue and moves the board item to Done. If checks fail, are pending/unknown, the label is present,
   or status/comments cannot be determined, do not merge and report/escalate. Honor an explicit request to keep the PR open.

Commit messages end with the trailer `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.

### Required checks

The `Main protection` ruleset currently requires these status checks: `unit-tests`, `Component Tests (make up && make component-tests)`, `Sanity Tests (make up && make sanity-tests)`, `Static Review (checkstyle)`, `QA Agent`, `analyze` (CodeQL), `dependency-review`, `secret-scan` and `PR Review`. `PR Review` is a workflow gate that must be `success` on the current head SHA before QA or merge; it is also a required status check in the ruleset (ruleset 25822954). `Definition of Done` is manual only, stays visible on the PR, and is neither required nor a merge gate (do not add it to the ruleset). **No agent may merge unless every ruleset-required check and the agent statuses (`PR Review`, `QA Agent`) are successful on the current head SHA** (pending, skipped, unknown or failed means do not merge).
Check the current head SHA with `gh pr checks <n> -R martinslavov/rcas`. The unit-tests job also enforces the JaCoCo coverage minimums
(`./gradlew build`; report with `./gradlew jacocoTestReport`). Dependabot security-update PRs get no `QA Agent` status automatically:
they need the normal agent flow or a human.

### Workflow security

New or changed workflows must use `permissions: {}` at the top level with minimal job-level grants, and every `uses:` pinned to a full 40-character commit SHA with the version tag as a trailing comment (Dependabot keeps pins current). Secrets go only to the step that needs them. See `.github/docs/security.md`.

### QA test scope and status

- A PR is docs-only only if every changed file matches `*.md`, `.github/agents/**`, `.github/copilot-instructions.md`, `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`, or `.github/ISSUE_TEMPLATE/**`. QA reviews the documentation and its consistency; tests are not required. Any other changed file means the PR is not docs-only.
- Architect may skip a design note for docs-only changes under that exact definition, or for a small, narrowly scoped change touching no public API, database schema/migrations, messaging, security, configuration, dependencies, architecture or cache topology. Every Architect skip is auditable: post an issue comment with `<!-- architect-skipped -->` and `skipped: <reason>`. Otherwise, post the design note. Approval triggers still apply whenever present, except when the user explicitly supplied the `skip-architect` label.
- For any change under `src/**`, `component-tests/**`, `.github/checkstyle/**`, or `.github/scripts/**`, or to `build.gradle`, `settings.gradle`, `gradle/**`, `Dockerfile`, `docker-compose.yml`, `docker/**`, `Makefile`, `.github/workflows/**`, or `db.migration/**`, QA runs the relevant tests, at minimum `./gradlew build` with JDK 25.
- For runtime-affecting changes (application source or configuration, runtime dependencies or packaging, database migrations, or Docker/Compose runtime setup; including changes in `src/**`, `db.migration/**`, `Dockerfile`, `docker-compose.yml`, and `docker/**`), QA additionally runs `make build && make up && make component-tests && make sanity-tests && make down`.
- When in doubt, QA runs the tests.
- The `QA Agent` status description identifies the checks actually executed and their results, e.g. `docs-only review`, `build passed`, or `build+component+sanity passed`. It includes failures and never implies an unrun check passed.

## Elapsed time (every task)

At the very beginning of every task the main (orchestrating) agent records the start time with `date +%s` (the moment it receives the user's input).
At the end, after everything is merged and all agents are done, it runs `date +%s` again and the final report to the user MUST state the total
elapsed time (end minus start, as minutes and seconds) from the user's input until everything is merged and all agents have finished.
Sub-agents report their own durations to the main agent when asked; the total is always computed by the main agent.

Right after the merge (and before the final report) the main agent also records the elapsed time on the task issue and the PR:
`.github/scripts/post_task_elapsed.sh <issue> <pr> <start-epoch>`. It upserts an "Elapsed time" block at the top of the issue and PR
descriptions (between `<!-- task-elapsed:begin -->` and `<!-- task-elapsed:end -->`, the rest of the description is kept) and one
`<!-- task-elapsed -->` comment on each, so a re-run (e.g. after a follow-up merge for the same task) replaces both instead of adding new ones.
Never edit or remove the block by hand. For an epic, run it
for every sub-issue/PR pair and once more for the epic issue with the last PR and the epic's start time.


## Agent run records

Every agent run must append exactly one hidden, single-line JSON record to its durable GitHub comment before it finishes.
Product Owner and Architect post on the task issue; Engineer posts on the task issue before an initial PR exists and on the PR
for an existing-PR fix assignment; PR Review, QA and DoD post on the PR. Use
`date -u +%Y-%m-%dT%H:%M:%SZ` for the UTC `start` and `end` timestamps and `date +%s` at both points to compute
`duration_s` as elapsed whole seconds. Post via `gh issue comment <issue-or-pr-number> -R martinslavov/rcas --body '<marker>'`.
For issue-only runs with no PR or head commit, use `null` for `pr` and/or `sha`. Use the same issue number throughout
the task. Capture only actual failed check names and retries performed by that agent; never include secrets, credentials,
tokens, or sensitive comment excerpts. A skipped or successful run has `failure_source: null`; failure/escalation runs
classify the primary cause as `po`, `implementation`, `tests`, or `infrastructure`.

The exact marker shape is `<!-- agent-run: {"v":1,"agent":"<agent-id>","issue":63,"pr":64,"sha":"<head-sha>","start":"2026-10-25T20:00:00Z","end":"2026-10-25T20:07:30Z","duration_s":450,"checks_failed":["unit-tests"],"retries":1,"status":"failure","failure_source":"tests"} -->`. Required fields are `v` (currently `1`), `agent`, positive `issue`, `pr` (positive number or `null`), `sha` (string or `null`), UTC ISO-8601 `start`/`end`, non-negative integer `duration_s`/`retries`, `checks_failed` (array of check names), `status` (`success`, `failure`, `skipped`, `escalated`), and `failure_source` (`po`, `implementation`, `tests`, `infrastructure`, or `null`). `failure_source` is non-null for `failure`/`escalated` and null for `success`/`skipped`.

Failure source means: `po` for unclear, missing or changed acceptance criteria; `implementation` for code/design defects;
`tests` for failing or missing tests/evidence; and `infrastructure` for runner, Docker, network or GitHub outages. The
dashboard deduplicates exact replays using `(agent, issue, pr, sha, start, end)`; timestamps make legitimate reruns distinct.
The dashboard is a derived view from all issue/PR comments and can be regenerated. It updates exactly the issue numbered by the Actions variable
`AGENT_DASHBOARD_ISSUE` (verified to contain `<!-- agent-dashboard -->`; the workflow never creates one, `--create` is one-time bootstrap); this issue must not be added to the task board. If the workflow log warns that its token cannot
pin the issue, an owner must pin it once with `gh issue pin <dashboard-issue-number> -R martinslavov/rcas`.

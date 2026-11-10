# RCAS – Reactive Cache Service

> Reactive cache service with Caffeine (L1), Redis (L2) and PostgreSQL over R2DBC, built on Spring Boot WebFlux

**RCAS** (Reactive Cache Service) is a reactive caching service built with Spring Boot WebFlux. It serves user and subscription data without blocking threads and puts a two-level cache in front of the database:

1. **Caffeine**: a fast in-memory (L1) cache inside the application.
2. **Redis**: a shared (L2) reactive cache, accessed through reactive Redis operations.
3. **PostgreSQL**: the source of truth, accessed through non-blocking R2DBC.

A read goes through the caches first and only falls back to the database on a miss, so repeated requests are served without hitting PostgreSQL. All layers are non-blocking, which keeps the service responsive under load with a small number of threads.

## Tech stack

- Java 25
- Spring Boot 4.1.2 (WebFlux, Data R2DBC, Data Redis Reactive, Actuator, Cache)
- PostgreSQL 15 and Redis 7
- Gradle 9.8.2 (wrapper)
- Docker / Docker Compose

## Prerequisites

- JDK 25 (`JAVA_HOME` must point to it)
- Docker with Docker Compose
- Access to the Docker Hardened Images registry (`docker login dhi.io`), needed to build the Docker image

## Build

```bash
./gradlew clean build        # compile + run all tests
./gradlew bootJar            # only build the executable jar (build/libs/rcas-0.0.1-SNAPSHOT.jar)
```

The tests use Testcontainers, so Docker must be running.

## Run

### Docker Compose profiles

`docker-compose.yml` splits the stack into infrastructure and the application, so you can choose what to start:

| Command | What starts |
|---------|-------------|
| `docker compose up -d` | Only the infrastructure: PostgreSQL and Redis |
| `docker compose --profile app up -d` | Infrastructure and the `rcas` application |

`rcas` belongs to the `app` profile, so it is **not** started by default. This lets you run the dependencies in Docker and start the service yourself from the IDE.

Stop everything (the `--profile app` flag is needed to also stop the service):

```bash
docker compose --profile app down        # stop and remove containers and network
docker compose --profile app down -v     # also remove volumes
```

### Option 1: everything in Docker

The image copies the jar from `build/libs`, so build it first:

```bash
./gradlew bootJar
docker compose --profile app up -d --build
```

### Option 2: dependencies in Docker, service from the IDE

```bash
docker compose up -d
```

Then run `com.gbp.rcas.RcasApplication` from the IDE (or `./gradlew bootRun`) with the Spring profile `dev`:

```bash
SPRING_PROFILES_ACTIVE=dev ./gradlew bootRun
```

The `dev` profile connects to PostgreSQL on `127.0.0.1:5432` (`testdb`, user and password `test`) and Redis on `localhost:6379`. Both ports are published by Compose.

## Published release images

Each stable release publishes the same multi-architecture image digest to `ghcr.io/martinslavov/rcas:vX.Y.Z` and `docker.io/martinslavov/rcas:vX.Y.Z`. Both registries' `latest` aliases point to the greatest stable SemVer release (numeric ordering), so rerunning an older release never moves either alias backwards. The release notes begin with both pull commands, the shared digest and links to both package pages. The workflow retains images for the newest two stable releases; older Docker Hub tags and GHCR image versions are deleted before their GitHub releases and Git tags. Historical releases can be backfilled by running **CI Release** with `workflow_dispatch` and an existing strict `vX.Y.Z` tag. After Docker Hub publishing is configured, backfill `v0.1.0` and `v0.1.1` to publish the historical images and update their release notes.

For example, start PostgreSQL and Redis from the Compose configuration, then run a published image on its network:

```bash
docker compose up -d
docker pull ghcr.io/martinslavov/rcas:v0.1.0
# Or use the matching Docker Hub image:
docker pull docker.io/martinslavov/rcas:v0.1.0
docker run --rm --name rcas --network rcas-docker-network -p 8080:8080 \
  -e SPRING_PROFILES_ACTIVE=dev \
  -e SPRING_R2DBC_URL=r2dbc:postgresql://postgres:5432/testdb \
  -e SPRING_R2DBC_USERNAME=test -e SPRING_R2DBC_PASSWORD=test \
  -e SPRING_DATA_REDIS_HOST=redis -e SPRING_DATA_REDIS_PORT=6379 \
  ghcr.io/martinslavov/rcas:v0.1.0
```

Then visit <http://localhost:8080/app/actuator/health>. `docker pull ghcr.io/martinslavov/rcas:latest` or `docker pull docker.io/martinslavov/rcas:latest` selects the newest stable release. The GHCR package and Docker Hub repository may initially be private: the owner must make each public in its registry settings for anonymous pulls. Release publication links the GHCR package to this repository through its OCI source label.

## Docker services

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `postgres` | `postgres:15.2` | 5432 | `db.migration/init.sql`, `V2__InsertUser.sql` and `V3__InsertSubscription.sql` run on first start |
| `redis` | `redis:7` | 6379 | |
| `rcas` | built from `Dockerfile` | 8080 | profile `app` |

All containers share the `rcas-docker-network` network. The Compose project name is `rcas`.

The database scripts run only when the Postgres container is created for the first time. After changing them, recreate the data with `docker compose --profile app down -v`.

## Monitoring (profile `monitoring`)

An optional monitoring stack is available in the `monitoring` Compose profile. It is not started by `docker compose up`, `make up` or CI.

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| `otel-collector` | `otel/opentelemetry-collector:0.116.1` | 4317 (gRPC), 4318 (HTTP) | receives OTLP; logs go to Loki, traces to the collector log (`debug` exporter) |
| `prometheus` | `prom/prometheus:v3.0.1` | 9090 | scrapes `rcas:8080/app/actuator/prometheus` and the collector |
| `loki` | `grafana/loki:3.3.2` | 3100 | log storage (OTLP ingestion on `/otlp`) |
| `grafana` | `grafana/grafana:11.4.0` | 3000 | provisioned datasources Prometheus and Loki, anonymous admin access (local use only) |

```bash
make monitoring-up      # RCAS + dependencies + monitoring, OTLP export enabled in RCAS
make monitoring-down    # stop everything and remove volumes
```

`make monitoring-up` passes `docker/monitoring/monitoring.env`, which switches RCAS to `log4j2-otel.yaml` (console plus the OpenTelemetry log appender) and enables OTLP trace and log export to the collector (traces are sampled at 100%). Without that file the OTLP export is off, so tests and the default stack need no collector. Configuration lives in `docker/monitoring/`.

Open Grafana at <http://localhost:3000> (Explore, datasource `Loki`, query `{service_name="rcas"}`; or `Prometheus`), Prometheus targets at <http://localhost:9090/targets>.

## Configuring the JVM

The image is based on a hardened Temurin image that has no shell, so JVM options are passed through the `JDK_JAVA_OPTIONS` environment variable, which the `java` launcher reads itself. Separate multiple options with spaces:

```yaml
environment:
  JDK_JAVA_OPTIONS: "-XX:MaxRAMPercentage=75 -Dspring.profiles.active=prod"
```

Setting the variable replaces the default from the Dockerfile (`-XX:MaxRAMPercentage=75`), it does not append to it. Spring properties can also be set as environment variables, for example `SPRING_R2DBC_URL`.

## Health check

The image is single-stage on the hardened runtime (`dhi.io/eclipse-temurin:25`): no `RUN`, compiler, shell or `curl`, and it runs as `nonroot`.
The health check is a tiny Java class (`src/healthcheck/java/HealthCheck.java`, Gradle source set `healthcheck`) that `make build`
(`./gradlew bootJar healthCheckClass`, also part of `./gradlew build`) compiles to `build/healthcheck/HealthCheck.class`; the Dockerfile copies it next to the jar.

The Dockerfile defines `HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD ["java", "-cp", "/app", "HealthCheck"]`.
The class calls `http://127.0.0.1:8080/app/actuator/health` inside the container (an optional URL argument overrides it) and exits `0` only on HTTP 200,
with 2 s connect/read timeouts. The container becomes `unhealthy` after 3 consecutive failures once the 40 s start period is over.
`docker-compose.yml` reuses the image health check and only adds `start_interval: 2s` (with the same `start_period: 40s`, which Compose requires) so that `make up` turns `healthy` quickly.
`docker compose ps` shows `rcas` as `healthy` when it succeeds.

## Endpoints

All paths are under the `/app` base path.

| URL | Description |
|-----|-------------|
| `http://localhost:8080/app/user/{id}` | Get a user |
| `http://localhost:8080/app/user/{id}/subscription` | Get a user with the subscription |
| `http://localhost:8080/app/subscription/{id}` | Get a subscription |
| `http://localhost:8080/app/subscriptions/{ids}` | Get several subscriptions |
| `http://localhost:8080/app/actuator/health` | Health (includes PostgreSQL and Redis) |
| `http://localhost:8080/app/actuator/prometheus` | Prometheus metrics |
| `http://localhost:8080/app/swagger-ui-custom.html` | Swagger UI |
| `http://localhost:8080/app/v3/api-docs` | OpenAPI document |

The Docker database is seeded with three users (ids 1 to 3) and three subscriptions for user 1 (ids 1 to 3), so every endpoint returns data out of the box.

## Tests

```bash
./gradlew test
```

Integration tests start PostgreSQL through Testcontainers, so they need a running Docker daemon.

### Component tests

Component tests live in the separate Gradle subproject `component-tests`. They call the running service over HTTP, so they exercise the whole stack: the RCAS image, PostgreSQL and Redis. They do not depend on the application code and are not run by `./gradlew build` (it only compiles them).

```bash
make build             # build the jar used by the Docker image
make up                # build the image, start the stack and wait until it is healthy
make component-tests   # ./gradlew :component-tests:componentTest against http://localhost:8080/app
make sanity-tests      # only the fast sanity (smoke) tests (@Tag("sanity"))
make down              # stop the stack and remove containers, network and volumes
```

Set `RCAS_BASE_URL` to test a service running somewhere else. `make logs` prints the container logs.

### Logging

RCAS logs only to the console (stdout), so the container runtime collects the logs; no log files are written. Use `make logs` or `docker compose --profile app logs rcas` to read them.

## CI/CD (GitHub Actions)

Workflows live in `.github/workflows`:

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci-unit-tests.yml` (CI Unit Tests) | pull request, push to `main`, manual | `./gradlew build` on JDK 25: compiles, runs unit and integration tests, uploads the test report and the JaCoCo `coverage-report`; `check` fails when LINE or BRANCH coverage drops below the minimums in `build.gradle` (45 % / 15 %; run `./gradlew jacocoTestReport`, report in `build/reports/jacoco/test/`) |
| `ci-component-tests.yml` (CI Component Tests) | pull request, push to `main`, manual | Builds the image, starts the stack with docker compose (`make up`), runs the component tests, collects the logs and tears everything down (`make down`) |
| `ci-sanity-tests.yml` (CI Sanity Tests) | pull request, push to `main`, manual | Starts the stack with docker compose and runs only the fast sanity tests (`make sanity-tests`) |
| `ci-static-review.yml` (CI Static Review) | pull request | Automatic static code review with Checkstyle (`.github/checkstyle/checkstyle.xml`, derived from `.github/docs/code-review-guidelines.md`); run locally with `./gradlew checkstyleMain checkstyleTest` |
| `ci-dependency-review.yml` (CI Dependency Review) | pull request | `dependency-review` job: fails the PR when it adds dependencies with known high or critical vulnerabilities |
| `ci-secret-scan.yml` (CI Secret Scan) | pull request, push to `main` | `secret-scan` job: gitleaks over the full history (`.gitleaks.toml`, allowlist entries need a documented reason) |
| `ci-tag.yml` (CI Tag) | merged PR into `main`; push fallback for fork PRs | Plans the tag in a read-only job from the `major` / `enhancement` labels, creates it in a minimal write job without checkout, then calls CI Release |
| `ci-release.yml` (CI Release) | push of a tag `v*`, reusable workflow call, manual backfill | Builds/tests the selected tag, publishes or verifies the same image digest in GHCR and Docker Hub before release creation, puts both pull commands and links at the top of release notes, advances both `latest` aliases to the highest stable SemVer, and prunes images before the two-release retention cleanup |
| `ci-artifact-roundtrip.yml` (CI Artifact Round Trip) | pull request changing `ci-release.yml` or this workflow, manual | Side-effect-free check of the CI Release `release-image-context` artifact contract: packs a generated fixture like the release `build` job, uploads it with the same pinned `upload-artifact`, downloads it with the same pinned `download-artifact` into `$RUNNER_TEMP/release-image-context`, restores it with the release `tar -xzf` command and verifies the path, listing, content and SHA-256 digests. Runs with `permissions: {}` and no secrets; never calls CI Release, uses tags, logs in to registries, publishes, edits releases or prunes |
| `ci-code-review.yml` (CodeQL) | pull request and push to `main`, weekly | Static security analysis, results appear in the Security tab |
| `ci-pr-issue-tracking.yml` (PR Issue Tracking) | pull request opened | Creates one tracking issue per PR (found again by a hidden marker, so it is never duplicated) and links it in a PR comment |

Releases are created automatically for merged PRs into `main`: add the `major` label for a major bump or `enhancement` for a minor bump; otherwise the version receives a patch bump. The first automatic release is `v0.1.0`. A commit already carrying a stable `vX.Y.Z` tag is not tagged again. Fork PR merges are handled by a `main` push fallback that verifies the commit belongs to a merged PR from a fork. The mutating jobs (CI Tag `tag` and CI Release `publish`, `dockerhub`, `release`, `latest`, `dockerhub-latest` and `prune`) share one job-level concurrency group `release-tag` with `queue: max` and no cancellation, so automatic releases, image publication, latest alias movement and cleanup are serialized in one FIFO queue (pending jobs not replaced), and tag-reference creation retries against the latest tags to avoid losing a merge when concurrent releases choose the same next version. Manual `v*` tag pushes still create releases and apply the two-release retention policy. The **CI Release** `workflow_dispatch` input is restricted by workflow validation to an existing strict stable `vX.Y.Z` tag for backfills. Retention and `latest` selection consider stable versions in numeric SemVer order:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Recommended repository settings:

- Settings → Actions → General → Workflow permissions: allow workflows to create issues and pull request comments (the PR Issue Tracking workflow also declares its permissions in the YAML).
- Branch protection / rulesets for `main`: `Main protection` currently requires `unit-tests`, `Component Tests (make up && make component-tests)`, `Sanity Tests (make up && make sanity-tests)`, `Static Review (checkstyle)`, `QA Agent`, `analyze` (CodeQL), `dependency-review`, `secret-scan` and `PR Review`. `PR Review` must succeed on the current head SHA before QA or merge. **No agent may merge unless every ruleset-required check and all agent statuses (`PR Review`, `QA Agent`, `Definition of Done`) are successful on the current head SHA** (pending, skipped, unknown or failed means do not merge). `Definition of Done` is validated after QA and joins the ruleset after it has reported once.
- Security: secret scanning, push protection, Dependabot alerts and security updates enabled. The `Branch naming` ruleset excludes `dependabot/**` so Dependabot can create its branches.
- Repository secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (read-only): used for Docker Hardened Images (`dhi.io`) pulls by CI Component Tests, CI Sanity Tests and the release image build. Add a separate `DOCKERHUB_PUSH_TOKEN` Docker Hub PAT with Read, Write & Delete permissions for release publication, `latest` and retention pruning; the workflow fails with an actionable error if it is missing. The owner must make the GHCR package and Docker Hub repository public for anonymous pulls, then manually backfill `v0.1.0` and `v0.1.1` through CI Release.
- Code scanning must be available for the repository to see the CodeQL results.

PRs from forks get a read-only token, so PR Issue Tracking cannot create issues for them.

See [Security and permissions](.github/docs/security.md) for per-workflow permissions, SHA pinning and Dependabot, fork PR behaviour, token scopes (`PROJECT_TOKEN`, read-only `DOCKERHUB_TOKEN`, and write/delete `DOCKERHUB_PUSH_TOKEN`) and per-agent permissions.

## Branch workflow

Commits (and pushes) from `main`/`master` are blocked by the versioned hooks in `.githooks`. Enable them once per clone and work in a branch:

```bash
git config core.hooksPath .githooks
git checkout -b feature/my-change
```

For real enforcement on GitHub also enable branch protection for `main` (see Settings → Rules).

## Agents and task workflow

Custom agents live in `.github/agents/`:

| Agent | Role |
|-------|------|
| `product-owner-agent` | Senior Product Owner: analyzes the input and creates a GitHub issue with acceptance criteria |
| `architect-agent` | Senior Software Architect: posts a design note or an auditable skip, and gates high-risk changes on explicit user approval |
| `senior-java-software-engineer` | Senior Java Software Engineer: implements the issue on a `feature/*` branch, tests it and opens a PR |
| `pr-review-agent` | Independent PR Reviewer: reads the issue and full diff, posts severity-ranked findings and sets `PR Review`; never changes code |
| `senior-qa-engineer` | Senior QA Engineer: starts after current-head `PR Review` success, tests the PR, reports bugs and sets `QA Agent` |
| `dod-validator-agent` | Definition of Done Validator: starts after current-head `QA Agent` success, maps every acceptance criterion to behaviour-verifying evidence, posts the AC → evidence table and sets `Definition of Done`; never changes code |

Give a task as `TASK-NAME:<name>` followed by the description. The workflow is Product Owner → Architect (design note or auditable skip) →
explicit user approval when required → Engineer → PR Review → QA → DoD → merge → elapsed time recorded on the issue and PR
(`.github/scripts/post_task_elapsed.sh`). For architecture changes (new module/layer/component or cache
topology), database schema/migrations, messaging/Kafka, public HTTP API or security changes, the Architect applies
`architecture-approval-required`; the orchestrator must wait for the user's explicit approval recorded on the issue as
`<!-- architecture-approved -->` before the Engineer creates a branch or starts implementation. The Engineer reads the design note
before implementation. Architect skips only docs-only changes (per the QA definition below) or small changes that touch none of the
listed risk areas, configuration, dependencies, architecture or cache topology; every skip has an issue comment with
`<!-- architect-skipped -->` and `skipped: <reason>`.

### Workflow orchestrator

Inspect or seed an issue state with `python3 .github/scripts/orchestrator.py state <issue>` or `python3 .github/scripts/orchestrator.py init <issue> --agent <id> [--state <state>]` (only when the issue has no record yet; `init` seeds only `backlog` or `todo` for any agent, including `human`, and refuses any other `--state` before any GitHub call; later states are reached only through `transition`, which enforces the owner and edge table). If a transition reports that projection failed, run `python3 .github/scripts/orchestrator.py reconcile <issue>`: it idempotently re-projects the canonical state to the single `state:*` label and the board Status without changing the record. Every workflow stage change goes through `python3 .github/scripts/orchestrator.py transition <issue> <to> --agent <id>` (add `--head-sha <sha>` for the current PR head or `--dry-run` to validate without writing); each agent uses its own id, and human-only transitions use `--agent human`. Rollout starts in report mode: report an orchestrator failure and do not bypass it silently. Migrating in-flight tasks to later states is out of scope for #101; it is a separate, human-performed rollout step to be designed later (for example, the remaining EPIC #107 work can add a verified migration).

The PR Review Agent independently reads the issue, the complete diff and surrounding code, then posts findings using severity
`blocker`, `major`, `minor` or `nit`, including file and line where known. Blocker/major findings fail `PR Review` and return the
PR to the engineer; minor/nit findings are reported but do not block QA. QA starts only after `PR Review` is `success` on the
current head SHA. The engineer sets `PR Review`, `QA Agent` and `Definition of Done` to `pending` immediately after opening the PR and after every
push. After each fix push, PR Review must succeed on the new head before QA resumes.

After QA succeeds on the current head SHA, the DoD Validator reads the issue linked by `Closes #N`, maps every acceptance criterion
to concrete evidence (a test asserting the behaviour, not merely the existence of a class — e.g. cache expiry needs a test asserting
expiration after the TTL; for docs/process criteria a `file:line` or verified command output), posts the AC → evidence table
(`<!-- dod-validation sha:<head-sha> -->`, verdicts `met`/`weak`/`missing`) as a PR comment and sets `Definition of Done`
(`success` only if every criterion is `met`). The PR template has a matching "Acceptance criteria → evidence" section. DoD failure
rounds use `<!-- dod-round:N -->` markers with the same five-round / `needs-human-review` rule as QA.

Both review loops are bounded at five failure rounds. Each PR Review report includes `<!-- pr-review-round:N -->`; round numbers
are derived from all such PR comment markers, not agent memory. On round-5 failure the agent applies `needs-human-review`,
mentions `@martinslavov`, and stops. Only a human removing that label resumes automated work; markers remain the source of truth.
No agent commits or merges while the label is present. QA uses its own `<!-- qa-round:N -->` markers and the same human-review
stop. For issues labelled `architecture-approval-required`, PR Review also checks conformance to the approved design note (material
deviations are at least major), backward compatibility and, for schema changes, migration and rollback evidence. PR descriptions
must not claim review, QA or CI/check statuses (for example, "no review performed" or "QA pending"); commit statuses and check
runs are the source of truth. The test section may list only local commands actually run and their results; if none were run, leave it without test-result entries rather than adding prose about unrun tests.

CI fix attempts are a separate three-attempt loop tracked by `<!-- ci-fix-attempt:N -->` and
`<!-- ci-failure-signature:<check name>|<test id or normalized error> -->` in PR comments. The engineer reads the failed
check and its Actions log/test report, reproduces and re-runs locally before pushing; one `infra:` retry counts as an
attempt. If attempt 3 still fails or the same signature appears twice consecutively, the engineer applies
`needs-human-review` and mentions `@martinslavov` with the check, run URL, signature, count and log excerpt. No agent
commits or merges while the label is present; only a human removes it to resume, retaining the separate CI, QA and PR
Review markers. After resumption numeric limits are not reapplied, but a repeated CI signature still stops the loop.
Auto-merge requires all existing ruleset checks plus `PR Review`, `QA Agent` and `Definition of Done` success on the current head SHA (the latter is added to the ruleset after its first report), no
`needs-human-review` label, and no human comments or unresolved blocker/major findings. `PR Review` is also a required check in the
`Main protection` ruleset. Rules are in `.github/copilot-instructions.md`.

### Task queue: Backlog and TODO

The RCAS Tracking board has the Status columns `Backlog`, `Assessment`, `Defining`, `TODO`, `In Progress` and `Done`.

| Input | Result |
|-------|--------|
| `TASK-NAME:<name>` | Issue created in `TODO` (default) and the full flow runs immediately |
| `LABEL:BACKLOG,TASK-NAME:<name>` | Issue created with the `backlog` label in `Backlog`; nothing else runs |

To start a backlog task without a state record, first seed it with `orchestrator.py init <issue> --state backlog --agent human`,
then use `orchestrator.py transition <issue> todo --agent human`; it updates the board and removes the legacy `backlog` label.
A board change cannot wake up the local Copilot session, so TODO items are picked up oldest first
after every merged task, or when you ask (for example `RUN-QUEUE`). Agents change stages only through the orchestrator;
its board projection moves active implementation/review work to `In Progress` and merge to `Done`.

EPICs (label `epic`) group related sub-issues; they stay `In Progress`, are never processed from the queue themselves and are
closed when all their sub-issues are done. The roadmap (five levels, the Level 1 Workflow Orchestrator and the features
deferred because of the GitHub Free / Copilot Free plan) is in [`.github/docs/roadmap.md`](.github/docs/roadmap.md). Each
of the five roadmap improvement tasks is one EPIC; parts that need a paid plan are `Backlog` issues labelled `requires-pro`
and listed, with order and prerequisites, in [`.github/docs/pro-plan.md`](.github/docs/pro-plan.md).

```bash
.github/scripts/task_queue.sh list                         # open TODO issues, oldest first
python3 .github/scripts/orchestrator.py init 96 --state todo --agent human # seed an existing issue without a record
python3 .github/scripts/orchestrator.py transition 96 architecture --agent architect-agent
```

### Running agents without approval prompts

Approval prompts for file edits and shell commands come from the Copilot CLI/IDE, not from repository rules, so they
cannot be disabled in `.github/copilot-instructions.md`. To keep the agent workflow from waiting on you, start the CLI
with a scoped allow-list:

```bash
copilot --allow-tool='write' \
  --allow-tool='shell(git:*)' --allow-tool='shell(gh:*)' \
  --allow-tool='shell(make:*)' --allow-tool='shell(./gradlew:*)' \
  --allow-tool='shell(docker:*)' --allow-tool='shell(python3:*)' \
  --deny-tool='shell(git push --force)' --deny-tool='shell(rm -rf)'
```

Broader alternatives: `copilot --allow-all-tools` (all tools) or `copilot --yolo` (all tools, paths and URLs); inside a
running session use `/allow-all`, or answer a prompt with "Yes, and don't ask again". In the JetBrains Copilot plugin,
enable auto-approve under **Settings → Tools → GitHub Copilot → Chat** (agent auto-approve for file edits and terminal
commands). Check `copilot --help` for the flags of your version. The GitHub rulesets (required checks, no direct push to
`main`) remain the safety net when prompts are off.

### QA test scope and status

- A PR is docs-only only if every changed file matches `*.md`, `.github/agents/**`, `.github/copilot-instructions.md`, `.github/PULL_REQUEST_TEMPLATE/pull_request_template.md`, or `.github/ISSUE_TEMPLATE/**`. QA reviews the documentation and its consistency; tests are not required. Any other changed file means the PR is not docs-only.
- For any change under `src/**`, `component-tests/**`, `.github/checkstyle/**`, or `.github/scripts/**`, or to `build.gradle`, `settings.gradle`, `gradle/**`, `Dockerfile`, `docker-compose.yml`, `docker/**`, `Makefile`, `.github/workflows/**`, or `db.migration/**`, QA runs the relevant tests, at minimum `./gradlew build` with JDK 25.
- For runtime-affecting changes (application source or configuration, runtime dependencies or packaging, database migrations, or Docker/Compose runtime setup; including changes in `src/**`, `db.migration/**`, `Dockerfile`, `docker-compose.yml`, and `docker/**`), QA additionally runs `make build && make up && make component-tests && make sanity-tests && make down`.
- When in doubt, QA runs the tests.
- The `QA Agent` status description identifies the checks actually executed and their results, e.g. `docs-only review`, `build passed`, or `build+component+sanity passed`. It includes failures and never implies an unrun check passed.

By default the engineer merges with a merge commit and deletes the branch only after every ruleset-required check and all agent statuses
are successful on the current head SHA, the label is absent, and no human comments or unresolved blocker/major findings remain. Merging closes the task
issue (`Closes #N`) and the tracking issue and moves the board item to Done. A failing, pending or unknown check blocks the merge. Add
"leave the PR open" or "do not merge" to the task to keep the PR open.

## Task reports: elapsed time

At the end of every task the agent reports the total elapsed time from the user's input until everything is merged and all agents are done.
The main (orchestrating) agent records the start with `date +%s` at the beginning of the task and computes the difference at the end
(see `.github/copilot-instructions.md`).

After the merge the same time (start, end and total) is shown at the top of the task issue and PR descriptions
(an "Elapsed time" note) and recorded as a `<!-- task-elapsed -->` comment on both. Re-running updates both instead of
duplicating them:

```bash
.github/scripts/post_task_elapsed.sh <issue> <pr> <start-epoch> [end-epoch]
```


### Agent run records and dashboard

Each agent appends one versioned, secret-free `<!-- agent-run: {{...}} -->` JSON comment at the end of its run. The schema,
UTC timestamp requirements and failure-source definitions are in `.github/copilot-instructions.md`. The
`Agent Workflow Dashboard` (runs on every push to `main`, daily, and manually from `main`; never on `pull_request`/forks) aggregates issue/PR comments. Its single issue is explicit configuration: the repository Actions variable `AGENT_DASHBOARD_ISSUE` holds its issue number (the job fails with a clear error if unset; there is no fallback and the workflow never creates issues). The script updates (and reopens if closed) exactly that issue after verifying it starts with `<!-- agent-dashboard -->`. One-time bootstrap: `GH_TOKEN=... python3 .github/scripts/agent_dashboard.py --repo martinslavov/rcas --create`, then `gh variable set AGENT_DASHBOARD_ISSUE -b <number> -R martinslavov/rcas`. The dashboard issue is
excluded from the task board. If automatic pinning is denied, a repository owner pins the created dashboard once.

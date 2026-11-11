# Security and permissions

Least-privilege rules for workflows, tokens and agents (EPIC #119, task 2.4, issue #118).

## Workflow permissions

Every workflow sets `permissions: {}` at the top level; each job declares only the grants it needs.

| Workflow | Job | Job permissions | Secrets used |
|----------|-----|-----------------|--------------|
| `ci-unit-tests.yml` | `unit-tests` | `contents: read` | none |
| `ci-component-tests.yml` | `component-tests` | `contents: read` | `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (login step only, before checkout) |
| `ci-sanity-tests.yml` | `sanity-tests` | `contents: read` | `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (login step only, before checkout) |
| `ci-static-review.yml` | `static-review` | `contents: read` | none |
| `ci-secret-scan.yml` | `secret-scan` | `contents: read` | none |
| `ci-dependency-review.yml` | `dependency-review` | `contents: read` | none |
| `ci-code-review.yml` (CodeQL) | `analyze` | `contents: read`, `actions: read`, `security-events: write` | none |
| `ci-agent-dashboard.yml` | `update-dashboard` | `contents: read`, `pull-requests: read`, `issues: write` | none |
| `ci-agent-dispatch.yml` | `dispatch` | `contents: read`, `issues: write`, `pull-requests: read`, `checks: read`, `statuses: read` | `COPILOT_AGENT_TOKEN` (agent assignment step only) |
| `ci-agent-pr-creation.yml` | `create-pr` | `contents: read`, `issues: write`, `pull-requests: write` | `COPILOT_AGENT_TOKEN` (PR-creation step only); `GITHUB_TOKEN` (guarded checks, recovery marker and intake) |
| `ci-agent-auto-merge.yml` | `merge` | `contents: write`, `issues: write`, `pull-requests: write`, `checks: read`, `statuses: read` | none |
| `ci-pr-issue-tracking.yml` | `create-issue` | `contents: read`, `issues: write`, `pull-requests: write` | `PROJECT_TOKEN` (board step only) |
| `ci-pr-issue-close.yml` | `close-issue` | `contents: read`, `issues: write`, `pull-requests: read` | `PROJECT_TOKEN` (board step only) |
| `ci-issue-board.yml` | `add-to-board` | none (`permissions: {}`) | `PROJECT_TOKEN` |
| `ci-tag.yml` | `plan` | `contents: read`, `pull-requests: read` | `GITHUB_TOKEN` (read-only; checks out and runs the release helper) |
| `ci-tag.yml` | `tag` | `contents: write` | `GITHUB_TOKEN` (create tag; no checkout, runs no repository code) |
| `ci-tag.yml` | `release` caller | `contents: write`, `packages: write` | Reusable-workflow permission ceiling; forwards Docker Hub secrets only to CI Release |
| `ci-release.yml` | `resolve`, `build` | `contents: read` | `GITHUB_TOKEN` (validate tag and fetch source) |
| `ci-release.yml` | `publish` | `contents: read`, `packages: write` | `GITHUB_TOKEN`, `DOCKERHUB_USERNAME`, read-only `DOCKERHUB_TOKEN` (`dhi.io` pull only) |
| `ci-release.yml` | `dockerhub` | `contents: read`, `packages: read` | `GITHUB_TOKEN`, `DOCKERHUB_USERNAME`, `DOCKERHUB_PUSH_TOKEN` (GHCR-to-Docker-Hub digest copy) |
| `ci-release.yml` | `release` | `contents: write` | `GITHUB_TOKEN` (create/update notes and attach jar only for a new release) |
| `ci-release.yml` | `latest` | `contents: read`, `packages: write` | `GITHUB_TOKEN` (alias the highest stable GHCR image) |
| `ci-release.yml` | `dockerhub-latest` | `contents: read`, `packages: read` | `GITHUB_TOKEN`, `DOCKERHUB_USERNAME`, `DOCKERHUB_PUSH_TOKEN` (alias the highest stable Docker Hub image) |
| `ci-release.yml` | `prune` | `contents: write`, `packages: write` | `GITHUB_TOKEN`; `DOCKERHUB_USERNAME`, `DOCKERHUB_PUSH_TOKEN` (Docker Hub tag deletion step only) |

`ci-tag.yml` writes a tag only for a merged PR targeting `main`; the push fallback verifies that the commit is associated
with a merged PR from a fork. It does not execute PR code. Privilege is separated: the read-only `plan` job looks up the PR and calculates the tag with the checked-out helper, while the `contents: write` `tag` job does not check out the repository or run repository scripts. It treats the plan outputs as untrusted: the tag must match strict stable SemVer `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`, the bump must be `major`, `minor` or `patch`, and the commit (taken from the event context, never from a job output) must be a 40-hex SHA that exists in the repository. It recomputes the version from the live tags on each attempt, so a plan that raced or went stale cannot allocate a wrong or duplicate version, and returns the existing tag when the commit is already tagged. The mutating jobs (`ci-tag.yml` `tag`, and `ci-release.yml` `publish`, `dockerhub`, `release`, `latest`,
`dockerhub-latest` and `prune`) use the
job-level `release-tag` concurrency group with `queue: max` and no cancellation. This keeps tag pushes, image/release
updates, latest alias movement and cleanup serialized without a workflow-level group that could block a reusable call.
The `ci-tag.yml` reusable-workflow caller grants the maximum `contents: write`/`packages: write` permissions required by
CI Release and explicitly passes `DOCKERHUB_USERNAME`, read-only `DOCKERHUB_TOKEN`, and `DOCKERHUB_PUSH_TOKEN`; each called
job still declares its own narrower token permissions. The old token is used only to pull from `dhi.io`; the new push token
is exposed only to Docker Hub publish, latest and prune steps. `DOCKERHUB_PUSH_TOKEN` is optional in the reusable-workflow
signature so missing configuration reaches the jobs' explicit actionable failure instead of silently omitting required
release output.
CI Release accepts only an existing strict stable `vX.Y.Z` tag (including `workflow_dispatch` backfills), resolves it to
a commit, builds/tests at that immutable commit, and passes only the same-run jar and health-check class to its image job.
The `publish` job receives the read-only Docker Hub token only for its `dhi.io` pull and logs out of `dhi.io` and `ghcr.io`
on every exit before checking that credentials are absent. It reuses a GHCR image only after checking its OCI revision
matches the tag commit. The separate `dockerhub` job logs into GHCR and Docker Hub, copies the already-published manifest
by digest with `skopeo copy --all --preserve-digests` (no rebuild or manifest-list wrapping), refuses a mismatching
existing Hub tag (the only repair is replacing a manifest list whose sole child is the expected digest), verifies the
copied top-level digest and logs out of both registries, including both Docker Hub names (`docker.io` and
`https://index.docker.io/v1/`). `release` runs only after that copy succeeds and updates the top-of-notes Docker image section idempotently;
existing jar assets are not replaced. `latest` and `dockerhub-latest` independently select the numerically greatest stable
release and point their registry aliases to that exact manifest.

The agent dispatcher and `ci-agent-pr-creation.yml` check out only the trusted default branch and never execute issue or PR
content. PR-creation privilege is isolated in the latter workflow/job. `COPILOT_AGENT_TOKEN` is exposed only as a step-level
environment variable on the trusted PR helper step, never to checkout or any step that runs untrusted content. The helper
uses it only for the `POST /pulls` that creates a new PR, so GitHub starts the required CI checks; reads, bot-authored recovery
markers, existing-PR validation and guarded intake use the workflow `GITHUB_TOKEN`. Reused PRs do not require the Copilot token.
Its secret-bearing path is schedule-only on the trusted default branch (there is no feature-branch `push` trigger); it
validates the expected Copilot actor against the GitHub Users API and checks the feature branch has the issue-number prefix.
It also requires the open issue opt-in, `implementation` task state, Engineer dispatch, and design-note/approval guards. The
five-minute default-branch schedule recovers an interrupted create/intake using only an unedited bot-authored marker bound
to the issue, actor and current branch SHA. The dispatch workflow `GITHUB_TOKEN` inspects event targets and records bounded
CI fix attempts, human-review labels and escalation comments; it uses
`COPILOT_AGENT_TOKEN` only for the GitHub GraphQL Copilot assignment API, because that API requires a user-to-server token and does not accept the Actions installation token.
The dispatch token is not passed to the merge workflow.
Auto-merge checks the current PR head, linked `agent-read` issue, all required status/check contexts plus Definition of
Done, the `needs-human-review` label, and human PR comments/reviews before calling the merge API. The merge job checks out
only the default branch and runs no PR-controlled code. It records task elapsed time after merge from the start marker
written when Architect is dispatched. The dispatcher and auto-merge workflows poll open agent-read PRs every five minutes; the PR-creation workflow polls its
authorized issue/branch records on the same interval. Stage dispatch, intake recovery and merge therefore do not depend on
follow-up events emitted by Actions runs.

The `prune` job has no checkout and runs no repository helper. It first deletes stale Docker Hub tags through the Hub API
(HTTP 204 and already-absent 404 are accepted); any other response fails closed before GitHub release/tag deletion. It
then protects retained versions and every shared/non-stale GHCR package tag and deletes eligible GHCR versions before
release/tag metadata. If the package API cannot be read or image deletion is denied (including plans that do not permit
GITHUB_TOKEN version deletion), it fails visibly and keeps the release/tag; there is no PAT fallback. The owner must review
package Actions access/deletion capability before relying on automatic image pruning. The tag job dereferences
annotated Git tags before checking whether the merge commit already has a tag.

Checkout steps use `persist-credentials: false`, so the job token is not left in `.git/config` while build and test
code runs. `pull_request_target` and `workflow_run` are not used; do not add them without a separate security review,
because they run with secrets and a write token.

### Docker registry credential boundary

`docker/login-action` stores registry credentials in the runner Docker config (`~/.docker/config.json`), where later
steps could read them; `persist-credentials: false` does not affect this config.

Component and sanity tests keep Docker Hub credentials away from PR-controlled code:

1. Log in to `dhi.io` only when the read-only Docker Hub secrets are available.
2. Pull the fixed image list in `DHI_IMAGES`, defined in the workflow itself (not read from the Dockerfile or other PR
   files); `test_workflow_security.py` keeps it aligned with Dockerfile `FROM` lines.
3. Run `docker logout dhi.io` with `if: always()` and fail if `dhi.io` remains under `auths` or `credHelpers`.
4. Only then check out repository code and run the build/tests. Compose reuses the already pulled base image without
   `--pull`; PostgreSQL and Redis are pulled anonymously.

For releases, the `publish` job checks out the selected validated tag with `persist-credentials: false` and downloads
only this run's build artifact before registry login. Its read-only Docker Hub credential is used only for the `dhi.io`
base-image pull; `dhi.io` and `ghcr.io` are logged out on all exits, then the config is checked for residual credentials.
The separate `dockerhub` and `dockerhub-latest` jobs use the write-capable PAT only for their Docker Hub login steps,
log out of Docker Hub and GHCR on all exits, and verify that neither registry remains in the Docker config. The GHCR
`latest` publisher also logs out and verifies cleanup. No release job checks out untrusted PR code; the image build uses
only the validated release tag.
The package must be linked to the repository for the `GITHUB_TOKEN` package API access to work. A user-owned GHCR package
may start private; the owner must make it public once in package settings to allow anonymous pulls. Package-version
deletion may not be enabled for user-owned packages on every plan. In that case pruning fails closed before deleting the
corresponding release/tag and asks the owner to grant package-version deletion access; there is no PAT fallback.

No PR-controlled code (make, Gradle, scripts or Compose) runs while component/sanity test credentials are stored. The
workflow files are still part of same-repository PRs, so changes to these secret-handling steps require review like any
other security-sensitive changes.

## SHA pinning and Dependabot

- Every `uses:` reference is pinned to a full 40-character commit SHA with the release tag as a trailing comment,
  e.g. `actions/checkout@<sha> # v7.0.1`. Tags are mutable, SHAs are not.
- `.github/dependabot.yml` enables the `github-actions` ecosystem (directory `/`, weekly), so Dependabot opens PRs that
  bump the SHA and the version comment. Review these PRs like code changes (release notes, new permissions).
- Resolve a SHA with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`; for an annotated tag (`type: tag`) dereference
  it with `gh api repos/<owner>/<repo>/git/tags/<sha>` and use the commit SHA.

## Fork pull requests

Workflows triggered by `pull_request` from a fork get a read-only token and no repository secrets.

- Nothing runs PR code with secrets or a write token (no `pull_request_target` / `workflow_run`).
- Component and sanity tests check whether the Docker Hub secrets exist and skip only the login and base-image
  pull steps when they do not; the build, `make up` and the tests still run (a missing login is never a reason to skip
  tests). Hardened-image (`dhi.io`) pulls may fail without credentials; the job then fails visibly instead of passing.
- Dependabot PRs get Dependabot secrets, not Actions secrets; the same rule applies.
- PR Issue Tracking cannot create issues for fork PRs (read-only token).

## Token scopes

| Secret | Used by | Minimum scope |
|--------|---------|---------------|
| `PROJECT_TOKEN` | `ci-issue-board.yml`, `ci-pr-issue-tracking.yml`, `ci-pr-issue-close.yml` (GraphQL: read the user project `RCAS Tracking`, add items, update the `Status` field) | Fine-grained personal access token owned by the project owner, **user permission "Projects": read and write**; no repository permissions are needed because issue and PR access comes from the job `GITHUB_TOKEN`. Set a short expiry and rotate. |
| `COPILOT_AGENT_TOKEN` | `ci-agent-dispatch.yml` (assign Copilot cloud agent with a selected custom agent) | User-to-server token for the repository owner with **Metadata: read** and **Actions, Contents, Issues, Pull requests: read and write**. GitHub's Copilot issue-assignment API does not accept `GITHUB_TOKEN`; expose this token only to the dispatch script. Set a short expiry and rotate. |
| `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` | Component/sanity base-image pulls and `ci-release.yml` `publish` (`dhi.io` only) | Docker Hub access token with **read-only (public repo read)** permission. Never a password or a write-capable token. |
| `DOCKERHUB_PUSH_TOKEN` | `ci-release.yml` Docker Hub publish, latest and prune steps only | Separate Docker Hub PAT with **Read, Write & Delete** permissions. Required for release output and retention; add this repository secret before enabling releases. Never reuse the read-only `DOCKERHUB_TOKEN`. |
| `GITHUB_TOKEN` | all workflows | Per job, see the table above. For GHCR, `packages: write` is limited to publication, `latest`, and prune jobs; no personal access token is used. |

Secrets are exposed only to the step that needs them, never at workflow or job level. The owner must create `DOCKERHUB_PUSH_TOKEN` before release publishing can complete; this new credential is separate from the read-only token and is never passed to `dhi.io` pull jobs. After configuring it, run CI Release with `workflow_dispatch` for historical tags `v0.1.0` and `v0.1.1` so the Docker Hub images and release-note sections are backfilled.

## Agent permissions

Agents run locally under the user's `gh` identity; `tools:` in `.github/agents/*.agent.md` limits the editor tooling,
it does not replace GitHub authorization. Separate identities per agent are deferred (#114, `requires-pro`).

| Agent | `tools:` | May change |
|-------|----------|------------|
| `product-owner-agent` | read, search, execute | Creates/updates GitHub issues only; no code |
| `architect-agent` | read, search, execute | Issue comments and the approval label only; no code |
| `senior-java-software-engineer` | read, edit, search, execute | Source, tests, docs and workflows on a `feature/*` branch; pushes implementation branches and fixes on existing PRs; PR creation is handled through `/ship-pr` |
| `pr-review-agent` | read, search, execute | PR comments and the `PR Review` status; no code |
| `senior-qa-engineer` | read, edit, search, execute | Adds or improves tests on the PR branch (`edit` is needed for that), PR comments, the `QA Agent` status; no production code |
| `dod-validator-agent` | read, search, execute | PR comments and the `Definition of Done` status; no code |

Analysing agents (product owner, architect, PR review, DoD) already have no `edit` tool, so `tools:` was left unchanged.
`execute` is required by all agents because they use the `gh` CLI.

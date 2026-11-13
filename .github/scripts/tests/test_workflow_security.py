import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3] / ".github"
WORKFLOWS = sorted((ROOT / "workflows").glob("*.yml"))
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*\S*$")
DOCKER_LOGIN_WORKFLOWS = ("ci-component-tests.yml", "ci-sanity-tests.yml")
DOWNLOAD_ARTIFACT_V8 = "9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2"
UPLOAD_ARTIFACT_V7 = "cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2"


def _steps(text):
    body = text.split("\n    steps:\n", 1)[1]
    return re.split(r"(?m)^      - ", body)[1:]


def _index(steps, predicate):
    matches = [i for i, step in enumerate(steps) if predicate(step)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one matching step, found {len(matches)}")
    return matches[0]


def _jobs(text):
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([\w-]+):\n", body)[1:]
    return dict(zip(parts[::2], parts[1::2]))


RELEASE_QUEUE = "    concurrency:\n      group: release-tag\n      queue: max\n"


class WorkflowSecurityTest(unittest.TestCase):
    def test_workflows_found(self):
        self.assertTrue(WORKFLOWS)

    def test_top_level_permissions_are_empty(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                self.assertRegex(path.read_text(encoding="utf-8"), r"(?m)^permissions: \{\}\s*$")

    def test_every_action_is_pinned_to_a_full_sha(self):
        for path in WORKFLOWS:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.match(r"\s*(?:- )?uses:\s*(.+)$", line)
                if match and not match.group(1).startswith("./.github/workflows/"):
                    with self.subTest(workflow=path.name, uses=match.group(1)):
                        self.assertRegex(match.group(1), PINNED)

    def test_cloud_pr_creation_workflow_has_isolated_minimum_permissions(self):
        path = ROOT / "workflows" / "ci-agent-pr-creation.yml"
        text = path.read_text(encoding="utf-8")
        job = _jobs(text)["create-pr"]

        self.assertIn("permissions: {}", text.split("jobs:", 1)[0])
        self.assertIn("cron: \"*/5 * * * *\"", text)
        self.assertIn("queue: max", text)
        self.assertIn("contents: read", job)
        self.assertIn("issues: write", job)
        self.assertIn("pull-requests: write", job)
        self.assertNotIn("contents: write", job)
        self.assertNotIn("actions: write", job)
        self.assertIn("ref: " + chr(36) + "{{ github.event.repository.default_branch }}", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("run: python3 .github/scripts/cloud_agent_pr.py", job)
        steps = _steps(text)
        secret_step = _index(steps, lambda step: "COPILOT_AGENT_TOKEN: ${{ secrets.COPILOT_AGENT_TOKEN }}" in step)
        self.assertIn("Create or recover the guarded task PR", steps[secret_step])
        self.assertIn("run: python3 .github/scripts/cloud_agent_pr.py", steps[secret_step])
        self.assertNotIn("COPILOT_AGENT_TOKEN", "".join(steps[:secret_step] + steps[secret_step + 1:]))
        self.assertNotIn("uses:", steps[secret_step])
        self.assertEqual(1, text.count("secrets.COPILOT_AGENT_TOKEN"))
        self.assertNotIn("env:\n      COPILOT_AGENT_TOKEN", job)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", steps[secret_step])
        self.assertNotIn(chr(36) + "{{ github.event.ref }}", text)
        self.assertNotIn(chr(36) + "{{ github.event.head_commit", text)
        helper = (ROOT / "scripts" / "cloud_agent_pr.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", helper)
        self.assertNotIn("os.system", helper)

    def test_quick_prs_with_no_task_issue_skip_tracking_issue_creation(self):
        text = (ROOT / "workflows" / "ci-pr-issue-tracking.yml").read_text(encoding="utf-8")
        job = _jobs(text)["create-issue"]

        self.assertIn("<!-- no-task-issue -->", job)
        self.assertIn("!contains(github.event.pull_request.body", job)

    def test_cloud_pr_creation_if_expression_uses_single_quoted_literals(self):
        text = (ROOT / "workflows" / "ci-agent-pr-creation.yml").read_text(encoding="utf-8")
        expressions = re.findall(r"(?m)^\s+if:\s*(.+)$", text)

        self.assertEqual(1, len(expressions))
        condition = expressions[0]
        self.assertNotRegex(condition, r'"[^"]*"')
        self.assertRegex(
            condition,
            r"^github\.ref == format\('refs/heads/\{0\}', github\.event\.repository\.default_branch\)$",
        )

    def test_cloud_pr_creation_secret_path_has_no_branch_controlled_trigger(self):
        text = (ROOT / "workflows" / "ci-agent-pr-creation.yml").read_text(encoding="utf-8")
        triggers = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        trigger_names = re.findall(r"(?m)^  ([A-Za-z_]+):", triggers)

        self.assertEqual(["schedule"], trigger_names)
        self.assertIn("COPILOT_AGENT_TOKEN: ${{ secrets.COPILOT_AGENT_TOKEN }}", text)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", text)

    def test_no_privileged_untrusted_triggers(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("pull_request_target", text)
                self.assertNotIn("workflow_run", text)

    def test_registry_logout_happens_before_pr_code_runs(self):
        for name in DOCKER_LOGIN_WORKFLOWS:
            with self.subTest(workflow=name):
                steps = _steps((ROOT / "workflows" / name).read_text(encoding="utf-8"))
                login = _index(steps, lambda s: "docker/login-action@" in s)
                pull = _index(steps, lambda s: "docker pull" in s)
                logout = _index(steps, lambda s: "docker logout dhi.io" in s)
                checkout = _index(steps, lambda s: "actions/checkout@" in s)
                pr_code = [i for i, s in enumerate(steps) if re.search(r"run:.*\b(make|gradle|gradlew)\b", s, re.S)]
                self.assertTrue(pr_code)
                self.assertLess(login, pull)
                self.assertLess(pull, logout)
                self.assertIn("if: always()", steps[logout])
                self.assertLess(logout, checkout)
                self.assertLess(logout, min(pr_code))

    def test_pulled_images_cover_dockerfile_base_images(self):
        dockerfile = (ROOT.parent / "Dockerfile").read_text(encoding="utf-8")
        base_images = set(re.findall(r"(?m)^FROM\s+(?:--\S+\s+)*(\S+)", dockerfile))
        for name in DOCKER_LOGIN_WORKFLOWS:
            with self.subTest(workflow=name):
                text = (ROOT / "workflows" / name).read_text(encoding="utf-8")
                pulled = set(re.search(r"DHI_IMAGES:\s*(.+)", text).group(1).split())
                self.assertTrue({i for i in base_images if i.startswith("dhi.io/")} <= pulled)

    def test_dependabot_updates_github_actions(self):
        text = (ROOT / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("package-ecosystem: github-actions", text)
        self.assertRegex(text, r"directory: /\s")
        self.assertIn("interval: weekly", text)

    def test_release_tagging_is_limited_to_merged_main_prs_and_fork_fallback(self):
        text = (ROOT / "workflows" / "ci-tag.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("types: [closed]", text)
        self.assertIn("github.event.pull_request.merged == true", text)
        self.assertIn("github.event.pull_request.base.ref == 'main'", text)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", text)
        self.assertIn("github.event_name == 'push'", text)
        self.assertIn(".head.repo.full_name != $repo", text)
        self.assertIn("pull-requests: read", text)
        self.assertIn("contents: write", text)
        self.assertEqual(text.count("github.event.pull_request.merge_commit_sha || github.sha"), 2)
        self.assertIn("git/tags/$object_sha", text)
        self.assertIn("release_tag.py existing --sha", text)
        self.assertIn("uses: ./.github/workflows/ci-release.yml", text)
        self.assertNotIn("merge_commit_sha ||", text.split("jobs:")[0])
        self.assertIn("for attempt in $(seq 1 10)", text)

    def test_reusable_release_declares_every_secret_passed_by_tag_workflow(self):
        caller = _jobs((ROOT / "workflows" / "ci-tag.yml").read_text(encoding="utf-8"))["release"]
        called = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        forwarded_secrets = re.findall(
            r"(?m)^      ([A-Z][A-Z0-9_]*): \$\{\{ secrets\.([A-Z][A-Z0-9_]*) }}$", caller
        )
        workflow_call = re.search(
            r"(?ms)^  workflow_call:\n(?P<section>.*?)(?=^  workflow_dispatch:)", called
        )
        self.assertIsNotNone(workflow_call)
        declarations = dict(
            (name, required == "true")
            for name, required in re.findall(
                r"(?m)^      ([A-Z][A-Z0-9_]*):\n        required: (true|false)$",
                workflow_call.group("section"),
            )
        )
        self.assertTrue(forwarded_secrets)
        for caller_name, secret_name in forwarded_secrets:
            with self.subTest(secret=secret_name):
                self.assertEqual(caller_name, secret_name)
                self.assertIn(secret_name, declarations)
                self.assertEqual(declarations[secret_name], secret_name != "DOCKERHUB_PUSH_TOKEN")
        self.assertIn("DOCKERHUB_PUSH_TOKEN", dict(forwarded_secrets).values())

    def test_release_builds_tag_and_prunes_with_job_scoped_write_permissions(self):
        text = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        jobs = _jobs(text)
        self.assertIn('tags: ["v**"]', text)
        self.assertIn("workflow_call:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("required: true", text)
        self.assertIn("contents: write", text)
        self.assertIn("ref: refs/tags/${{ needs.resolve.outputs.tag }}", text)
        self.assertIn("ref: ${{ needs.resolve.outputs.commit }}", text)
        self.assertIn("packages: write", text)
        self.assertIn("./gradlew build", text)
        self.assertIn("build/libs/*.jar", text)
        self.assertEqual(text.count("name: release-image-context"), 3)
        self.assertIn("actions/upload-artifact@", jobs["build"])
        self.assertIn("actions/download-artifact@", jobs["publish"])
        self.assertIn("actions/download-artifact@", jobs["release"])
        self.assertIn("gh release create", text)
        self.assertIn("org.opencontainers.image.revision", text)
        self.assertIn('--build-arg "OCI_REVISION=$COMMIT"', text)
        self.assertIn('gh api -X DELETE "repos/$REPO/git/refs/tags/$tag"', text)
        self.assertIn('gh api -X DELETE "user/packages/container/rcas/versions/$id"', text)
        self.assertIn("retaining all releases and tags", text)

    def test_release_download_artifact_consumers_are_pinned_to_v8_0_2(self):
        jobs = _jobs((ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8"))
        for job in ("publish", "release"):
            with self.subTest(job=job):
                self.assertEqual(jobs[job].count(f"actions/download-artifact@{DOWNLOAD_ARTIFACT_V8}"), 1)
                self.assertIn("path: ${{ runner.temp }}/release-image-context", jobs[job])
                self.assertIn('tar -xzf "$RUNNER_TEMP/release-image-context/release-image-context.tar.gz"', jobs[job])

    def test_artifact_round_trip_mirrors_release_contract_without_side_effects(self):
        text = (ROOT / "workflows" / "ci-artifact-roundtrip.yml").read_text(encoding="utf-8")
        release = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        on_block = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", on_block), ["pull_request", "workflow_dispatch"])
        self.assertIn("      - .github/workflows/ci-release.yml\n      - .github/workflows/ci-artifact-roundtrip.yml\n", on_block)
        jobs = _jobs(text)
        self.assertEqual(sorted(jobs), ["download", "upload"])
        for name, job in jobs.items():
            with self.subTest(job=name):
                self.assertIn("    permissions: {}\n", job)
        self.assertIn(f"actions/upload-artifact@{UPLOAD_ARTIFACT_V7}", jobs["upload"])
        self.assertIn(f"actions/upload-artifact@{UPLOAD_ARTIFACT_V7}", release)
        self.assertIn(f"actions/download-artifact@{DOWNLOAD_ARTIFACT_V8}", jobs["download"])
        self.assertIn("name: release-image-context", jobs["upload"])
        self.assertIn("name: release-image-context", jobs["download"])
        self.assertIn('tar -czf release-image-context.tar.gz "$jar" build/healthcheck/HealthCheck.class', jobs["upload"])
        self.assertIn('tar -czf release-image-context.tar.gz "$jar" build/healthcheck/HealthCheck.class', release)
        self.assertIn("path: ${{ runner.temp }}/release-image-context", jobs["download"])
        self.assertIn('run: tar -xzf "$RUNNER_TEMP/release-image-context/release-image-context.tar.gz"', jobs["download"])
        self.assertIn("sha256sum -c -", jobs["download"])
        self.assertIn("tar -tzf", jobs["download"])
        for forbidden in ("secrets.", "GITHUB_TOKEN", "GH_TOKEN", "ci-release.yml\n", "uses: ./", "login",
                          "docker ", "skopeo", "gh release", "gh api", "git tag", "refs/tags", "tags:",
                          "write", "DELETE", "delete", "prune", "checkout"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text.split("\nname:", 1)[1].replace("- .github/workflows/ci-release.yml\n", ""))

    def test_dockerfile_declares_oci_labels_and_workflow_inspects_each_label(self):
        dockerfile = (ROOT.parent / "Dockerfile").read_text(encoding="utf-8")
        jobs = _jobs((ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8"))
        publish = jobs["publish"]
        for label in ("source", "version", "revision"):
            name = f"org.opencontainers.image.{label}"
            with self.subTest(label=label):
                self.assertIn(f"{name}=", dockerfile)
                self.assertIn(f'"{name}"', publish)
        self.assertIn("[ -f build/healthcheck/HealthCheck.class ]", publish)
        self.assertIn("Expected exactly one boot jar", jobs["build"])

    def test_release_jobs_follow_image_before_release_and_limit_registry_secrets(self):
        text = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        jobs = _jobs(text)
        self.assertIn("needs: [resolve, build]", jobs["publish"])
        self.assertIn("needs: [resolve, build, publish, dockerhub]", jobs["release"])
        self.assertIn("needs: [release]", jobs["latest"])
        self.assertIn("needs: [resolve, publish]", jobs["dockerhub"])
        self.assertIn("needs: [resolve, latest]", jobs["dockerhub-latest"])
        self.assertIn("needs: [dockerhub-latest]", jobs["prune"])
        self.assertIn("packages: write", jobs["publish"])
        self.assertNotIn("contents: write", jobs["publish"])
        self.assertIn("contents: write", jobs["release"])
        self.assertNotIn("packages: write", jobs["release"])
        self.assertIn("packages: write", jobs["latest"])
        self.assertIn("packages: write", jobs["prune"])
        self.assertIn("secrets.DOCKERHUB_USERNAME", jobs["publish"])
        self.assertIn("secrets.DOCKERHUB_TOKEN", jobs["publish"])
        self.assertNotIn("DOCKERHUB_PUSH_TOKEN", jobs["publish"])
        for job_name in ("resolve", "build", "release", "latest"):
            self.assertNotIn("DOCKERHUB_PUSH_TOKEN", jobs[job_name])
        self.assertNotIn("DOCKERHUB_TOKEN", jobs["dockerhub"])
        self.assertNotIn("DOCKERHUB_TOKEN", jobs["dockerhub-latest"])
        for job_name in ("dockerhub", "dockerhub-latest", "prune"):
            with self.subTest(job=job_name):
                self.assertIn("secrets.DOCKERHUB_USERNAME", jobs[job_name])
                self.assertIn("secrets.DOCKERHUB_PUSH_TOKEN", jobs[job_name])
                self.assertNotIn("secrets.DOCKERHUB_PUSH_TOKEN", jobs[job_name].split("    steps:", 1)[0])
        self.assertIn("docker logout ghcr.io", jobs["publish"])
        self.assertIn("docker logout dhi.io", jobs["publish"])
        self.assertIn("if: always()", jobs["publish"])
        self.assertIn("Verify no registry credentials remain", jobs["publish"])
        for job_name in ("dockerhub", "dockerhub-latest"):
            self.assertIn("docker logout docker.io", jobs[job_name])
            self.assertIn("docker logout https://index.docker.io/v1/", jobs[job_name])
            self.assertIn("skopeo copy --all --preserve-digests", jobs[job_name])
            self.assertNotIn("imagetools create", jobs[job_name])
            self.assertIn("docker logout ghcr.io", jobs[job_name])
            self.assertIn("if: always()", jobs[job_name])
            self.assertIn("Verify no registry credentials remain", jobs[job_name])
            self.assertIn('has("docker.io")', jobs[job_name])
            self.assertIn('has("https://index.docker.io/v1/")', jobs[job_name])
            self.assertIn('has("ghcr.io")', jobs[job_name])
            self.assertLess(jobs[job_name].index("docker logout docker.io"),
                            jobs[job_name].index("Verify no registry credentials remain"))
        self.assertIn("docker logout ghcr.io", jobs["latest"])
        self.assertIn("Verify no GHCR credentials remain", jobs["latest"])
        self.assertIn("workflow_dispatch", text.split("jobs:", 1)[0])
        self.assertIn("strict stable vX.Y.Z", jobs["resolve"])

    def test_release_and_tag_headers_describe_image_publishing_and_pruning(self):
        for name in ("ci-release.yml", "ci-tag.yml"):
            header = (ROOT / "workflows" / name).read_text(encoding="utf-8").split("name:", 1)[0]
            with self.subTest(workflow=name):
                self.assertIn("image", header.lower())
                self.assertIn("prun", header.lower())

    def test_prune_job_does_not_execute_repository_code_with_write_token(self):
        text = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        prune = _jobs(text)["prune"]
        self.assertIn("contents: write", prune)
        self.assertNotIn("actions/checkout", prune)
        self.assertNotIn(".github/scripts", prune)
        self.assertNotRegex(prune, r"\bpython3?\b")

    def test_prune_lists_releases_once_and_does_not_treat_release_view_errors_as_absence(self):
        text = (ROOT / "workflows" / "ci-release.yml").read_text(encoding="utf-8")
        prune = _jobs(text)["prune"]
        self.assertEqual(prune.count('gh api --paginate "repos/$REPO/releases?per_page=100"'), 1)
        self.assertNotIn("gh release view", prune)
        self.assertIn("set -euo pipefail", prune)
        self.assertIn("awk -F '\\t' -v tag=\"$tag\"", prune)

    def test_mutating_release_jobs_share_one_global_job_level_queue(self):
        critical = {"ci-tag.yml": ("tag",), "ci-release.yml": ("publish", "dockerhub", "release", "latest", "dockerhub-latest", "prune")}
        for workflow, job_names in critical.items():
            text = (ROOT / "workflows" / workflow).read_text(encoding="utf-8")
            with self.subTest(workflow=workflow):
                self.assertNotRegex(text.split("\njobs:\n", 1)[0], r"(?m)^concurrency:")
                self.assertNotIn("cancel-in-progress", text)
                self.assertEqual(text.count("group:"), len(job_names))
            jobs = _jobs(text)
            for job in job_names:
                with self.subTest(workflow=workflow, job=job):
                    self.assertIn(RELEASE_QUEUE, jobs[job])
        caller = _jobs((ROOT / "workflows" / "ci-tag.yml").read_text(encoding="utf-8"))["release"]
        self.assertNotIn("concurrency:", caller)
        self.assertIn("packages: write", caller)
        self.assertIn("DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}", caller)
        self.assertIn("DOCKERHUB_TOKEN: ${{ secrets.DOCKERHUB_TOKEN }}", caller)
        self.assertIn("DOCKERHUB_PUSH_TOKEN: ${{ secrets.DOCKERHUB_PUSH_TOKEN }}", caller)

    def test_tag_write_job_is_separated_from_the_read_only_plan_job(self):
        jobs = _jobs((ROOT / "workflows" / "ci-tag.yml").read_text(encoding="utf-8"))
        plan, tag = jobs["plan"], jobs["tag"]
        self.assertIn("contents: read", plan)
        self.assertIn("pull-requests: read", plan)
        self.assertNotIn("write", plan)
        self.assertNotIn("concurrency:", plan)
        self.assertIn("actions/checkout@", plan)
        self.assertIn("release_tag.py next", plan)
        self.assertIn("needs: plan", tag)
        self.assertIn("contents: write", tag)
        self.assertNotIn("pull-requests", tag)
        self.assertNotIn("actions/checkout", tag)
        self.assertNotIn("uses:", tag)
        self.assertNotIn(".github/scripts", tag)
        self.assertNotIn("release_tag.py", tag)
        self.assertNotRegex(tag, r"\bpython3?\b")

    def test_tag_write_job_validates_inputs_and_recomputes_from_live_tags(self):
        tag = _jobs((ROOT / "workflows" / "ci-tag.yml").read_text(encoding="utf-8"))["tag"]
        self.assertIn(r"semver='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'", tag)
        self.assertIn("[[ \"$SHA\" =~ ^[0-9a-f]{40}$ ]]", tag)
        self.assertIn("[[ \"$PLAN_TAG\" =~ $semver ]]", tag)
        self.assertIn("major | minor | patch)", tag)
        self.assertIn('repos/$REPO/commits/$SHA" --jq \'.sha\'', tag)
        self.assertIn("SHA: ${{ github.event.pull_request.merge_commit_sha || github.sha }}", tag)
        self.assertNotIn("needs.plan.outputs.sha", tag)
        self.assertLess(tag.index("[[ \"$PLAN_TAG\" =~ $semver ]]"), tag.index("-X POST"))
        self.assertLess(tag.index("=~ ^[0-9a-f]{40}$"), tag.index("-X POST"))
        self.assertIn("is stale; allocating", tag)
        self.assertIn("already tagged", tag)
        self.assertIn("for attempt in $(seq 1 10)", tag)


    def test_pr_issue_tracking_keeps_tracking_actions_and_scoped_board_secret(self):
        path = ROOT / "workflows" / "ci-pr-issue-tracking.yml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("pull_request:\n    types: [opened]", text)
        self.assertNotIn("pull_request_target", text)
        self.assertIn("permissions: {}", text)
        job = _jobs(text)["create-issue"]
        self.assertIn("contents: read", job)
        self.assertIn("issues: write", job)
        self.assertIn("pull-requests: write", job)
        self.assertNotIn("secrets.PROJECT_TOKEN", job.split("- name: Add tracking issue to RCAS Tracking board", 1)[0])

        steps = _steps(text)
        tracking = _index(steps, lambda step: "name: Create or find linked issue" in step)
        board = _index(steps, lambda step: "name: Add tracking issue to RCAS Tracking board" in step)
        self.assertLess(tracking, board)
        self.assertIn("actions/github-script@", steps[tracking])
        for operation in ("github.rest.issues.create", "github.rest.issues.createComment", "github.rest.pulls.update"):
            with self.subTest(operation=operation):
                self.assertIn(operation, steps[tracking])
        self.assertIn("secrets.PROJECT_TOKEN", steps[board])

    def test_agent_dispatch_uses_only_trusted_default_branch_and_scoped_user_token(self):
        text = (ROOT / "workflows" / "ci-agent-dispatch.yml").read_text(encoding="utf-8")
        self.assertIn("issues:\n    types: [labeled, unlabeled]", text)
        self.assertIn("issue_comment:\n    types: [created, edited]", text)
        self.assertIn("\n  status:\n", text)
        self.assertIn('cron: "*/5 * * * *"', text)
        self.assertIn("pull_request:\n    types: [labeled]", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("workflow_run", text)
        self.assertIn("permissions: {}", text)
        self.assertIn("check_suite:\n    types: [completed]", text)
        job = _jobs(text)["dispatch"]
        for permission in ("contents: read", "issues: write", "pull-requests: read", "checks: read", "statuses: read"):
            with self.subTest(permission=permission):
                self.assertIn(permission, job)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("COPILOT_AGENT_TOKEN: ${{ secrets.COPILOT_AGENT_TOKEN }}", job)
        self.assertNotIn("secrets.COPILOT_AGENT_TOKEN", job.split("- name: Checkout trusted default-branch automation", 1)[0])

    def test_agent_auto_merge_checks_current_head_without_pr_code_or_secret(self):
        text = (ROOT / "workflows" / "ci-agent-auto-merge.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "*/5 * * * *"', text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("workflow_run", text)
        self.assertNotIn("secrets.", text)
        job = _jobs(text)["merge"]
        for permission in (
            "contents: write",
            "issues: write",
            "pull-requests: write",
            "checks: read",
            "statuses: read",
        ):
            with self.subTest(permission=permission):
                self.assertIn(permission, job)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("MODE: merge", job)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from copilot_agent_automation import (
    Dispatch,
    ENTRY_LABEL,
    HUMAN_REVIEW_LABEL,
    REQUIRED_CHECKS,
    get_dispatches,
    merge_if_ready,
)


class FakeGitHub:
    owner = "martinslavov"
    name = "rcas"
    repository = "martinslavov/rcas"

    def __init__(self):
        self.issue = {"number": 42, "state": "open", "labels": [{"name": ENTRY_LABEL}]}
        self.pr = {
            "number": 43,
            "state": "open",
            "draft": False,
            "body": "Closes #42\n<!-- ship-pr -->",
            "base": {"ref": "main"},
            "head": {
                "sha": "a" * 40,
                "ref": "feature/automated-task",
                "repo": {"full_name": self.repository},
            },
            "labels": [{"name": ENTRY_LABEL}],
        }
        self.statuses = [
            {"context": name, "state": "success", "updated_at": "2026-01-01T00:00:00Z"}
            for name in ("PR Review", "QA Agent", "Definition of Done")
        ]
        self.check_runs = [
            {
                "id": index,
                "name": name,
                "status": "completed",
                "conclusion": "success",
                "completed_at": "2026-01-01T00:00:00Z",
            }
            for index, name in enumerate(REQUIRED_CHECKS, start=1)
            if name not in {"PR Review", "QA Agent"}
        ]
        self.comments = [
            {
                "body": "<!-- agent-automation-start:1794315503 -->",
                "user": {"login": self.owner},
            }
        ]
        self.issue_comments = [
            {
                "body": "<!-- agent-automation-start:1794315503 -->",
                "user": {"login": self.owner},
            }
        ]
        self.merged = False

    def pages(self, path):
        if "/issues?" in path:
            return [self.issue]
        if path.endswith("/issues/43/comments"):
            return self.comments
        if path.endswith("/issues/42/comments"):
            return self.issue_comments
        if path.endswith("/pulls") or "/pulls?" in path:
            return [self.pr]
        if path.endswith("/comments") or path.endswith("/reviews"):
            return self.comments
        return []

    def request(self, method, path, body=None):
        if method == "POST" and path.endswith("/issues/43/comments"):
            self.comments.append(
                {
                    "body": body["body"],
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                    "created_at": f"2026-01-01T00:00:{len(self.comments):02d}Z",
                }
            )
            return self.comments[-1]
        if method == "POST" and path.endswith("/issues/43/labels"):
            self.pr["labels"] = [{"name": name} for name in body["labels"]]
            return self.pr["labels"]
        if path.endswith("/pulls/43") and method == "GET":
            return self.pr
        if path.endswith("/issues/42") and method == "GET":
            return self.issue
        if path.endswith("/issues/43/labels") and method == "GET":
            return self.pr["labels"]
        if path.startswith("/repos/martinslavov/rcas/commits/") and path.endswith("/status") and method == "GET":
            return {"statuses": self.statuses}
        if "/check-runs?" in path and method == "GET":
            return {"check_runs": self.check_runs}
        if path.endswith("/pulls/43/merge") and method == "PUT":
            self.merged = True
            return {"merged": True, "message": "Pull Request successfully merged"}
        if path.endswith("/git/refs/heads/feature/automated-task") and method == "DELETE":
            return None
        raise AssertionError(f"Unexpected request: {method} {path}")


class CopilotDispatchTest(unittest.TestCase):
    @staticmethod
    def add_ci_attempt(api, number, sha, signature, second=0):
        api.comments.append(
            {
                "body": (
                    f"<!-- ci-fix-attempt:{number} -->\n"
                    f"<!-- ci-failure-signature:{signature} -->\n"
                    f"<!-- ci-fix-state:{sha}:{'f' * 64} -->"
                ),
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "created_at": f"2026-01-01T00:01:{second:02d}Z",
            }
        )

    def test_agent_read_label_starts_architect(self):
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "issue": {"number": 42, "state": "open", "labels": []},
        }
        self.assertEqual(
            [Dispatch("issue", 42, "architect-agent")],
            get_dispatches("issues", event, FakeGitHub()),
        )

    def test_architecture_note_without_approval_starts_engineer(self):
        api = FakeGitHub()
        body = "<!-- architect-design-note -->\nApproval required: no"
        api.issue_comments.extend(
            [
                {"body": Dispatch("issue", 42, "architect-agent").marker, "user": {"login": api.owner}},
                {"body": body, "user": {"login": "copilot-swe-agent[bot]"}},
            ]
        )
        event = {
            "action": "created",
            "issue": {
                "number": 42,
                "state": "open",
                "labels": [{"name": ENTRY_LABEL}],
            },
            "comment": {
                "body": body,
                "user": {"login": "copilot-swe-agent[bot]"},
            },
        }
        self.assertEqual(
            [Dispatch("issue", 42, "senior-java-software-engineer")],
            get_dispatches("issue_comment", event, api),
        )

    def test_architecture_approval_must_be_by_repository_owner(self):
        api = FakeGitHub()
        note = "<!-- architect-design-note -->\nApproval required: yes"
        api.issue["labels"].append({"name": "architecture-approval-required"})
        api.issue_comments.extend(
            [
                {"body": Dispatch("issue", 42, "architect-agent").marker, "user": {"login": api.owner}},
                {"body": note, "user": {"login": "copilot-swe-agent[bot]"}},
            ]
        )
        event = {
            "action": "created",
            "issue": {
                "number": 42,
                "state": "open",
                "labels": [
                    {"name": ENTRY_LABEL},
                    {"name": "architecture-approval-required"},
                ],
            },
            "comment": {
                "body": (
                    "<!-- architecture-approved --> "
                    "Approved by @martinslavov at 2026-11-10T12:00:00Z"
                ),
                "user": {"login": "someone-else"},
            },
        }
        self.assertEqual([], get_dispatches("issue_comment", event, api))
        event["comment"]["user"]["login"] = api.owner
        api.issue_comments.append(event["comment"])
        self.assertEqual(
            [Dispatch("issue", 42, "senior-java-software-engineer")],
            get_dispatches("issue_comment", event, api),
        )

    def test_review_success_dispatches_qa_for_current_agent_pr(self):
        api = FakeGitHub()
        event = {"context": "PR Review", "state": "success", "sha": "a" * 40}
        self.assertEqual(
            [Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)],
            get_dispatches("status", event, api),
        )

    def test_stale_status_does_not_dispatch_for_newer_head(self):
        api = FakeGitHub()
        api.pr["head"]["sha"] = "b" * 40
        event = {"context": "PR Review", "state": "success", "sha": "a" * 40}
        self.assertEqual([], get_dispatches("status", event, api))

    def test_round_five_failure_waits_for_human_review(self):
        api = FakeGitHub()
        api.comments = [{"body": "<!-- qa-round:5 -->", "user": {"login": api.owner}}]
        event = {"context": "QA Agent", "state": "failure", "sha": "a" * 40}
        self.assertEqual([], get_dispatches("status", event, api))

    def test_failed_required_ci_check_dispatches_engineer(self):
        api = FakeGitHub()
        api.check_runs[0]["conclusion"] = "failure"
        api.check_runs[0]["output"] = {
            "title": "Unit tests failed",
            "text": "FAILED: CacheServiceTest.expiresAfterTtl",
        }
        event = {
            "action": "completed",
            "check_suite": {"head_sha": "a" * 40, "conclusion": "failure"},
        }
        self.assertEqual(
            [Dispatch("pull", 43, "senior-java-software-engineer", "a" * 40)],
            get_dispatches("check_suite", event, api),
        )
        self.assertIn("<!-- ci-fix-attempt:1 -->", api.comments[-1]["body"])
        self.assertIn("<!-- ci-failure-signature:unit-tests|FAILED: CacheServiceTest.expiresAfterTtl -->", api.comments[-1]["body"])

    def test_check_suite_stops_at_attempt_limit_across_head_shas(self):
        api = FakeGitHub()
        for attempt in range(1, 4):
            self.add_ci_attempt(api, attempt, f"{attempt:x}" * 40, f"unit-tests|failure-{attempt}", attempt)
        api.check_runs[0]["conclusion"] = "failure"
        api.check_runs[0]["id"] = 20
        sha = "a" * 40
        event = {"action": "completed", "check_suite": {"head_sha": sha, "conclusion": "failure"}}

        self.assertEqual([], get_dispatches("check_suite", event, api))
        self.assertEqual({HUMAN_REVIEW_LABEL}, {item["name"] for item in api.pr["labels"]})
        self.assertIn("@martinslavov", api.comments[-1]["body"])
        self.assertIn("attempt limit was reached", api.comments[-1]["body"])

    def test_check_suite_stops_on_repeated_failure_signature_on_new_sha(self):
        api = FakeGitHub()
        self.add_ci_attempt(api, 1, "b" * 40, "unit-tests|AssertionError: expected true", 1)
        api.check_runs[0]["conclusion"] = "failure"
        api.check_runs[0]["id"] = 20
        api.check_runs[0]["output"] = {"text": "AssertionError: expected true"}
        event = {
            "action": "completed",
            "check_suite": {"head_sha": "a" * 40, "conclusion": "failure"},
        }

        self.assertEqual([], get_dispatches("check_suite", event, api))
        self.assertEqual({HUMAN_REVIEW_LABEL}, {item["name"] for item in api.pr["labels"]})
        self.assertIn("failure signature repeated", api.comments[-1]["body"])

    def test_schedule_stops_ci_retry_at_limit_across_head_shas(self):
        api = FakeGitHub()
        sha = "b" * 40
        api.pr["head"]["sha"] = sha
        api.issue_comments.extend(
            [
                {"body": Dispatch("issue", 42, "architect-agent").marker},
                {"body": Dispatch("issue", 42, "senior-java-software-engineer").marker},
            ]
        )
        for attempt in range(1, 4):
            self.add_ci_attempt(api, attempt, f"{attempt:x}" * 40, f"unit-tests|failure-{attempt}", attempt)
        api.check_runs[0]["conclusion"] = "failure"
        api.check_runs[0]["id"] = 20

        self.assertEqual([], get_dispatches("schedule", {}, api))
        self.assertEqual({HUMAN_REVIEW_LABEL}, {item["name"] for item in api.pr["labels"]})
        self.assertIn("attempt limit was reached", api.comments[-1]["body"])

    def test_removing_human_review_label_resumes_engineer_once(self):
        api = FakeGitHub()
        api.statuses[0]["state"] = "failure"
        event = {
            "action": "unlabeled",
            "label": {"name": HUMAN_REVIEW_LABEL},
            "issue": {"number": 43, "pull_request": {}, "labels": []},
        }
        self.assertEqual(
            [
                Dispatch(
                    "pull",
                    43,
                    "senior-java-software-engineer",
                    "a" * 40,
                    resume=True,
                )
            ],
            get_dispatches("issues", event, api),
        )

    def test_schedule_dispatches_next_agent_from_current_head_statuses(self):
        api = FakeGitHub()
        api.issue_comments.extend(
            [
                {"body": Dispatch("issue", 42, "architect-agent").marker},
                {"body": Dispatch("issue", 42, "senior-java-software-engineer").marker},
            ]
        )
        next(item for item in api.statuses if item["context"] == "QA Agent")["state"] = "pending"
        self.assertEqual(
            [Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)],
            get_dispatches("schedule", {}, api),
        )

    def test_schedule_recovers_architect_dispatch_for_labeled_issue(self):
        api = FakeGitHub()
        api.pr["labels"] = []
        self.assertEqual(
            [Dispatch("issue", 42, "architect-agent")],
            get_dispatches("schedule", {}, api),
        )

    def test_issue_agent_read_is_not_copied_to_the_pr(self):
        api = FakeGitHub()
        api.pr["labels"] = []
        get_dispatches("schedule", {}, api)
        self.assertEqual([], api.pr["labels"])

    def test_unmarked_or_unlabeled_pr_is_not_automation_eligible(self):
        api = FakeGitHub()
        api.issue["labels"] = []
        api.pr["labels"] = []
        self.assertEqual([], get_dispatches("schedule", {}, api))
        api.pr["labels"] = [{"name": ENTRY_LABEL}]
        api.pr["body"] = "Closes #42"
        self.assertEqual([], get_dispatches("schedule", {}, api))

    def test_agent_read_pr_label_starts_review_without_restarting_engineer_stages(self):
        api = FakeGitHub()
        api.statuses = []
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "pull_request": {"number": 43},
        }
        self.assertEqual(
            [Dispatch("pull", 43, "pr-review-agent", "a" * 40)],
            get_dispatches("pull_request", event, api),
        )

    def test_agent_read_pr_label_starts_qa_when_review_succeeded_and_qa_status_is_absent(self):
        api = FakeGitHub()
        api.statuses = [
            status for status in api.statuses
            if status["context"] != "QA Agent"
        ]
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "pull_request": {"number": 43},
        }
        expected = [Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)]
        self.assertEqual(expected, get_dispatches("pull_request", event, api))
        api.issue["labels"] = []
        self.assertEqual(expected, get_dispatches("schedule", {}, api))

    def test_agent_read_pr_label_starts_qa_when_qa_status_is_pending(self):
        api = FakeGitHub()
        next(status for status in api.statuses if status["context"] == "QA Agent")["state"] = "pending"
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "pull_request": {"number": 43},
        }
        self.assertEqual(
            [Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)],
            get_dispatches("pull_request", event, api),
        )

    def test_pr_label_event_requires_open_linked_ship_pr_and_no_human_review(self):
        api = FakeGitHub()
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "pull_request": {"number": 43},
        }
        api.pr["labels"] = [{"name": HUMAN_REVIEW_LABEL}, {"name": ENTRY_LABEL}]
        self.assertEqual([], get_dispatches("pull_request", event, api))
        api.pr["labels"] = [{"name": ENTRY_LABEL}]
        api.pr["body"] = "Closes #42"
        self.assertEqual([], get_dispatches("pull_request", event, api))
        event["action"] = "unlabeled"
        self.assertEqual([], get_dispatches("pull_request", event, api))

    def test_pr_label_alone_enables_pr_stages(self):
        api = FakeGitHub()
        api.issue["labels"] = []
        api.pr["labels"] = [{"name": ENTRY_LABEL}]
        next(item for item in api.statuses if item["context"] == "QA Agent")["state"] = "pending"
        self.assertEqual(
            [Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)],
            get_dispatches("schedule", {}, api),
        )

    def test_pr_without_review_status_starts_pr_review(self):
        api = FakeGitHub()
        api.statuses = []
        api.issue["labels"] = []
        api.pr["labels"] = [{"name": ENTRY_LABEL}]
        self.assertEqual(
            [Dispatch("pull", 43, "pr-review-agent", "a" * 40)],
            get_dispatches("schedule", {}, api),
        )

    def test_dod_is_never_dispatched(self):
        for state in ("pending", "failure", "error", "success"):
            api = FakeGitHub()
            api.issue["labels"] = []
            api.pr["labels"] = [{"name": ENTRY_LABEL}]
            for item in api.statuses:
                if item["context"] == "Definition of Done":
                    item["state"] = state
            self.assertEqual([], get_dispatches("schedule", {}, api))
        for context, state in (("QA Agent", "success"), ("Definition of Done", "pending"), ("Definition of Done", "failure")):
            api = FakeGitHub()
            event = {"context": context, "state": state, "sha": "a" * 40}
            self.assertEqual([], get_dispatches("status", event, api))


class AutoMergeTest(unittest.TestCase):
    def test_merges_only_when_checks_statuses_and_comments_are_clear(self):
        api = FakeGitHub()
        with patch("copilot_agent_automation.subprocess.run") as run:
            self.assertTrue(merge_if_ready(api, 43))
        self.assertEqual(
            [
                "bash",
                ".github/scripts/post_task_elapsed.sh",
                "42",
                "43",
                "1794315503",
            ],
            run.call_args.args[0],
        )
        self.assertTrue(api.merged)

    def test_definition_of_done_does_not_gate_merge(self):
        api = FakeGitHub()
        api.statuses = [item for item in api.statuses if item["context"] != "Definition of Done"]
        with patch("copilot_agent_automation.subprocess.run"):
            self.assertTrue(merge_if_ready(api, 43))
        self.assertTrue(api.merged)

    def test_failed_required_check_blocks_merge(self):
        api = FakeGitHub()
        api.check_runs[0]["conclusion"] = "failure"
        self.assertFalse(merge_if_ready(api, 43))
        self.assertFalse(api.merged)

    def test_human_comment_blocks_merge(self):
        api = FakeGitHub()
        api.comments = [{"body": "Please review this behavior", "user": {"login": api.owner}}]
        self.assertFalse(merge_if_ready(api, 43))
        self.assertFalse(api.merged)

    def test_human_review_label_blocks_merge(self):
        api = FakeGitHub()
        api.pr["labels"] = [{"name": HUMAN_REVIEW_LABEL}]
        self.assertFalse(merge_if_ready(api, 43))
        self.assertFalse(api.merged)


class AssignToCopilotQueryTest(unittest.TestCase):
    class GraphQLGitHub:
        owner = "martinslavov"
        name = "rcas"
        repository = "martinslavov/rcas"

        def __init__(self):
            self.queries = []
            self.comments = []

        def pages(self, path):
            return []

        def request(self, method, path, body=None):
            self.comments.append((path, body))
            return {}

        def graphql(self, query, variables):
            self.queries.append(query)
            if "addAssigneesToAssignable" in query:
                return {"addAssigneesToAssignable": {"assignable": {"id": "ITEM"}}}
            repository = {
                "id": "REPO",
                "suggestedActors": {"nodes": [{"login": "copilot-swe-agent", "id": "BOT"}]},
            }
            if "issue(number" in query:
                repository["issue"] = {"id": "ITEM"}
            if "pullRequest(number" in query:
                repository["pullRequest"] = {"id": "ITEM"}
            return {"repository": repository}

    def test_pull_request_dispatch_queries_only_pull_request(self):
        from copilot_agent_automation import assign_to_copilot

        api = self.GraphQLGitHub()
        assign_to_copilot(api, Dispatch("pull", 190, "pr-review-agent", "a" * 40))

        lookup = api.queries[0]
        self.assertIn("pullRequest(number", lookup)
        self.assertNotIn("issue(number", lookup)
        self.assertEqual(2, len(api.queries))

    def test_issue_dispatch_queries_only_issue(self):
        from copilot_agent_automation import assign_to_copilot

        api = self.GraphQLGitHub()
        assign_to_copilot(api, Dispatch("issue", 189, "senior-java-software-engineer"))

        lookup = api.queries[0]
        self.assertIn("issue(number", lookup)
        self.assertNotIn("pullRequest(number", lookup)


if __name__ == "__main__":
    unittest.main()

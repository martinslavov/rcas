import unittest
from unittest.mock import patch

from copilot_agent_automation import (
    Dispatch,
    ENTRY_LABEL,
    HUMAN_REVIEW_LABEL,
    LOCAL_AGENT_LABEL,
    QUICK_PR_AUTO_MARKER,
    QUICK_PR_MARKER,
    REQUIRED_CHECKS,
    _event_pr_numbers,
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

    def make_quick_pr(self):
        self.pr["user"] = {"login": self.owner}
        self.pr["body"] = f"{QUICK_PR_MARKER}\n{QUICK_PR_AUTO_MARKER}"
        self.issue["labels"] = []

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

    def test_cloud_agent_label_starts_architect(self):
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "issue": {"number": 42, "state": "open", "labels": [{"name": ENTRY_LABEL}]},
        }
        self.assertEqual(
            [Dispatch("issue", 42, "architect-agent")],
            get_dispatches("issues", event, FakeGitHub()),
        )

    def test_skip_architect_dispatches_engineer_without_architecture_comments(self):
        labels = [
            {"name": ENTRY_LABEL},
            {"name": "skip-architect"},
            {"name": "architecture-approval-required"},
        ]
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "issue": {"number": 42, "state": "open", "labels": labels},
        }

        self.assertEqual(
            [Dispatch("issue", 42, "senior-java-software-engineer")],
            get_dispatches("issues", event, FakeGitHub()),
        )

    def test_backlog_cloud_agent_issue_waits_until_moved_to_todo(self):
        api = FakeGitHub()
        api.issue["labels"].append({"name": "backlog"})
        api.pr["labels"] = []
        event = {
            "action": "labeled",
            "label": {"name": ENTRY_LABEL},
            "issue": {
                "number": 42,
                "state": "open",
                "labels": [{"name": ENTRY_LABEL}, {"name": "backlog"}],
            },
        }

        self.assertEqual([], get_dispatches("issues", event, api))
        self.assertEqual([], get_dispatches("schedule", {}, api))

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

    def test_design_note_requires_approval_even_if_approval_label_is_missing(self):
        api = FakeGitHub()
        note = "<!-- architect-design-note -->\nApproval required: yes"
        api.issue_comments.extend([
            {"body": Dispatch("issue", 42, "architect-agent").marker, "user": {"login": api.owner}},
            {"body": note, "user": {"login": "copilot-swe-agent[bot]"}},
        ])
        event = {
            "action": "created",
            "issue": {"number": 42, "state": "open", "labels": [{"name": ENTRY_LABEL}]},
            "comment": {"body": note, "user": {"login": "copilot-swe-agent[bot]"}},
        }

        self.assertEqual([], get_dispatches("issue_comment", event, api))

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

    def test_local_agent_issue_is_not_dispatched_to_cloud_agent(self):
        api = FakeGitHub()
        api.issue["labels"].append({"name": LOCAL_AGENT_LABEL})
        event = {
            "issue": api.issue,
            "comment": {
                "body": "<!-- architect-skipped --> skipped: low risk",
                "user": {"login": api.owner},
            },
        }

        self.assertEqual([], get_dispatches("issue_comment", event, api))
        self.assertEqual([], get_dispatches("schedule", {}, api))
        self.assertEqual(
            [],
            get_dispatches(
                "status",
                {"context": "PR Review", "state": "success", "sha": api.pr["head"]["sha"]},
                api,
            ),
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

    def test_issue_cloud_agent_is_not_copied_to_the_pr(self):
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

    def test_cloud_agent_pr_label_starts_review_without_restarting_engineer_stages(self):
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

    def test_cloud_agent_pr_label_starts_qa_when_review_succeeded_and_qa_status_is_absent(self):
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

    def test_cloud_agent_pr_label_starts_qa_when_qa_status_is_pending(self):
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

    def test_quick_pr_dispatches_review_then_qa(self):
        api = FakeGitHub()
        api.make_quick_pr()
        api.statuses = []
        event = {"action": "labeled", "label": {"name": ENTRY_LABEL}, "pull_request": {"number": 43}}
        self.assertEqual([Dispatch("pull", 43, "pr-review-agent", "a" * 40)],
                         get_dispatches("pull_request", event, api))
        api.statuses = [{"context": "PR Review", "state": "success"}]
        self.assertEqual([Dispatch("pull", 43, "senior-qa-engineer", "a" * 40)],
                         get_dispatches("status", {"context": "PR Review", "state": "success", "sha": "a" * 40}, api))
        api.statuses[0]["state"] = "failure"
        self.assertEqual([], get_dispatches("status", {"context": "PR Review", "state": "success", "sha": "a" * 40}, api))
        self.assertEqual([], get_dispatches("schedule", {}, api))

    def test_quick_pr_requires_all_opt_in_and_trust_guards(self):
        cases = (
            ("missing auto marker", lambda pr: pr.update(body=QUICK_PR_MARKER)),
            ("missing no-issue marker", lambda pr: pr.update(body=QUICK_PR_AUTO_MARKER)),
            ("ship marker", lambda pr: pr.update(body=pr["body"] + "\n<!-- ship-pr -->")),
            ("linked issue", lambda pr: pr.update(body=pr["body"] + "\nCloses #42")),
            ("other author", lambda pr: pr.update(user={"login": "someone"})),
            ("other repo", lambda pr: pr["head"].update(repo={"full_name": "someone/rcas"})),
            ("wrong branch", lambda pr: pr["head"].update(ref="main")),
            ("draft", lambda pr: pr.update(draft=True)),
            ("missing label", lambda pr: pr.update(labels=[])),
            ("human review", lambda pr: pr["labels"].append({"name": HUMAN_REVIEW_LABEL})),
        )
        for name, change in cases:
            with self.subTest(name=name):
                api = FakeGitHub()
                api.make_quick_pr()
                change(api.pr)
                self.assertEqual([], get_dispatches("schedule", {}, api))
                self.assertFalse(merge_if_ready(api, 43))

    def test_quick_pr_never_dispatches_engineer_on_failure(self):
        api = FakeGitHub()
        api.make_quick_pr()
        api.statuses[0]["state"] = "failure"
        event = {"context": "PR Review", "state": "failure", "sha": "a" * 40}
        self.assertEqual([], get_dispatches("status", event, api))
        self.assertEqual([], get_dispatches("schedule", {}, api))
        api.check_runs[0]["conclusion"] = "failure"
        event = {"action": "completed", "check_suite": {"head_sha": "a" * 40, "conclusion": "failure"}}
        self.assertEqual([], get_dispatches("check_suite", event, api))
        api.statuses = [
            {"context": "PR Review", "state": "success"},
            {"context": "QA Agent", "state": "failure"},
        ]
        event = {"action": "labeled", "label": {"name": ENTRY_LABEL}, "pull_request": {"number": 43}}
        self.assertEqual([], get_dispatches("pull_request", event, api))
        self.assertEqual([], get_dispatches("status", {"context": "PR Review", "state": "success", "sha": "a" * 40}, api))


class AutoMergeTest(unittest.TestCase):
    def test_quick_pr_merges_without_issue_elapsed_record(self):
        api = FakeGitHub()
        api.make_quick_pr()
        api.comments = []
        with patch("copilot_agent_automation.subprocess.run") as run:
            self.assertTrue(merge_if_ready(api, 43))
        self.assertTrue(api.merged)
        run.assert_not_called()

    def test_quick_pr_is_discovered_from_events_and_schedule(self):
        api = FakeGitHub()
        api.make_quick_pr()
        self.assertEqual([43], _event_pr_numbers("schedule", {}, api))
        self.assertEqual([43], _event_pr_numbers("status", {"sha": "a" * 40}, api))
        self.assertEqual([43], _event_pr_numbers("check_suite", {"check_suite": {"head_sha": "a" * 40}}, api))
        self.assertEqual([], _event_pr_numbers("status", {"sha": "b" * 40}, api))

    def test_quick_pr_obeys_every_merge_gate(self):
        for name in REQUIRED_CHECKS:
            for state in ("failure", "pending", "skipped"):
                with self.subTest(name=name, state=state):
                    api = FakeGitHub()
                    api.make_quick_pr()
                    if name in {"PR Review", "QA Agent"}:
                        next(item for item in api.statuses if item["context"] == name)["state"] = state
                    else:
                        next(item for item in api.check_runs if item["name"] == name)["conclusion"] = state
                    self.assertFalse(merge_if_ready(api, 43))
                    self.assertFalse(api.merged)
        api = FakeGitHub()
        api.make_quick_pr()
        api.comments = [{"body": "Please wait", "user": {"login": api.owner}}]
        self.assertFalse(merge_if_ready(api, 43))
        api.comments = []
        api.statuses = [item for item in api.statuses if item["context"] != "QA Agent"]
        self.assertFalse(merge_if_ready(api, 43))
        api.check_runs.append({
            "name": "QA Agent", "conclusion": "success", "completed_at": "2026-01-02T00:00:00Z",
        })
        self.assertFalse(merge_if_ready(api, 43))

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
            if method == "GET" and "/pulls/" in path:
                return {}
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

    def test_assignment_mutation_uses_assignee_ids(self):
        from copilot_agent_automation import assign_to_copilot

        api = self.GraphQLGitHub()
        assign_to_copilot(api, Dispatch("pull", 190, "pr-review-agent", "a" * 40))

        mutation = api.queries[1]
        self.assertIn("assigneeIds: [$actor]", mutation)
        self.assertNotIn("actorIds", mutation)

    def test_issue_dispatch_queries_only_issue(self):
        from copilot_agent_automation import assign_to_copilot

        api = self.GraphQLGitHub()
        assign_to_copilot(api, Dispatch("issue", 189, "senior-java-software-engineer"))

        lookup = api.queries[0]
        self.assertIn("issue(number", lookup)
        self.assertNotIn("pullRequest(number", lookup)
        self.assertTrue(any("agent-automation-start:" in body["body"] for _, body in api.comments))

    def test_quick_pr_dispatch_instructs_agent_to_use_pr_scope(self):
        from copilot_agent_automation import assign_to_copilot

        api = self.GraphQLGitHub()
        quick_pr = FakeGitHub()
        quick_pr.make_quick_pr()
        original_request = api.request
        api.request = lambda method, path, body=None: (
            quick_pr.pr if method == "GET" and "/pulls/" in path
            else original_request(method, path, body)
        )
        api.owner = quick_pr.owner
        api.repository = quick_pr.repository
        captured = []
        original_graphql = api.graphql
        api.graphql = lambda query, variables: (
            captured.append(variables) or original_graphql(query, variables)
        )
        assign_to_copilot(api, Dispatch("pull", 43, "senior-qa-engineer", "a" * 40))
        self.assertIn("no task issue", captured[-1]["instructions"])
        self.assertIn("Do not edit or push code", captured[-1]["instructions"])


if __name__ == "__main__":
    unittest.main()

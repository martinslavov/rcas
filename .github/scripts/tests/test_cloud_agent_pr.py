import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_agent_pr import SHIP_PR_MARKER, CloudPrError, run


SHA = "a" * 40
BRANCH = "feature/42-cloud-flow"


class FakeGitHubApi:
    repository = "martinslavov/rcas"

    def __init__(self):
        self.issue = {
            "number": 42,
            "title": "Cloud flow",
            "state": "open",
            "labels": [
                {"name": "agent-read"},
                {"name": "architecture-approval-required"},
            ],
        }
        state = {
            "v": 1,
            "issue": 42,
            "state": "implementation",
            "owner_agent": "senior-java-software-engineer",
            "actions": {},
        }
        self.comments = [
            {
                "body": "<!-- task-state: " + json.dumps(state) + " -->",
                "user": {"login": "martinslavov"},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            {
                "body": "<!-- copilot-agent-dispatch:senior-java-software-engineer:issue -->",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "body": "<!-- architect-design-note --> Approval required: yes",
                "user": {"login": "copilot-swe-agent[bot]"},
            },
            {
                "body": "<!-- architecture-approved --> Approved by @martinslavov at 2026-11-11T13:30:01Z",
                "user": {"login": "martinslavov"},
            },
        ]
        self.branch_sha = SHA
        self.prs = []
        self.requests = []
        self.activity = []
        self.refs = [{"ref": "refs/heads/" + BRANCH}]
        self.events_pages = None
        self.events = [{
            "type": "PushEvent",
            "actor": {"login": "copilot-swe-agent", "id": 88},
            "payload": {"ref": "refs/heads/" + BRANCH, "head": SHA},
        }]

    def pages(self, path):
        if (path.startswith("/repos/martinslavov/rcas/issues?state=open&labels=agent-read")
                and any(label["name"] == "agent-read" for label in self.issue["labels"])):
            return [self.issue]
        if (path.startswith("/repos/martinslavov/rcas/issues?state=open&labels=state%3Apr-review")
                and any(label["name"] == "state:pr-review" for label in self.issue["labels"])):
            return [self.issue]
        if path.startswith("/repos/martinslavov/rcas/issues/42/comments"):
            return list(self.comments)
        if path.startswith("/repos/martinslavov/rcas/issues/43/comments"):
            return []
        if path.startswith("/repos/martinslavov/rcas/git/matching-refs/heads/feature/42-"):
            return list(self.refs)
        if "/pulls?state=open&head=" in path:
            return list(self.prs)
        return []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if path.startswith("/repos/martinslavov/rcas/events"):
            if self.events_pages is not None:
                page = int(path.rsplit("page=", 1)[1])
                if page > len(self.events_pages):
                    raise CloudPrError("HTTP 422")
                return list(self.events_pages[page - 1])
            return list(self.events)
        if path.startswith("/repos/martinslavov/rcas/activity?"):
            return list(self.activity)
        if path == "/users/copilot-swe-agent":
            return {"login": "copilot-swe-agent", "id": 88, "type": "Bot"}
        if path.startswith("/repos/martinslavov/rcas/branches/feature%2F"):
            return {"commit": {"sha": self.branch_sha}}
        if path.startswith("/repos/martinslavov/rcas/issues/") and method == "GET":
            number = int(path.rsplit("/", 1)[1])
            return dict(self.issue, number=number)
        if path.startswith("/repos/martinslavov/rcas/pulls/") and method == "GET":
            number = int(path.rsplit("/", 1)[1])
            return next(pr for pr in self.prs if pr["number"] == number)
        if path == "/repos/martinslavov/rcas/issues/42/comments" and method == "POST":
            self.comments.append({
                "body": body["body"],
                "user": {"login": "github-actions[bot]"},
                "created_at": "2026-01-01T00:10:00Z",
                "updated_at": "2026-01-01T00:10:00Z",
            })
            return self.comments[-1]
        if path == "/repos/martinslavov/rcas/pulls" and method == "POST":
            pr = {
                "number": 43,
                "state": "open",
                "body": body["body"],
                "base": {"ref": "main"},
                "head": {"ref": body["head"], "sha": SHA, "repo": {"full_name": self.repository}},
            }
            self.prs.append(pr)
            return pr
        raise AssertionError(f"Unexpected request: {method} {path}")


class FakePrCreationApi:
    repository = "martinslavov/rcas"

    def __init__(self, delegate):
        self.delegate = delegate
        self.requests = []

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return self.delegate.request(method, path, body)


class CloudAgentPrTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHubApi()
        self.pr_creation_api = FakePrCreationApi(self.api)
        self.root = Path(__file__).resolve().parents[3]
        self.event = {
            "ref": "refs/heads/" + BRANCH,
            "after": SHA,
            "sender": {"login": "copilot-swe-agent", "id": 88},
        }
        self.calls = []

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_verified_approved_push_creates_template_pr_and_runs_guarded_intake(self):
        with patch.dict("os.environ", {
            "GITHUB_TOKEN": "test-token",
            "COPILOT_AGENT_TOKEN": "copilot-token",
        }):
            self.assertTrue(run("push", self.event, self.api, self.root, self.runner, self.pr_creation_api))

        created = [call for call in self.pr_creation_api.requests
                   if call[0] == "POST" and call[1] == "/repos/martinslavov/rcas/pulls"]
        self.assertEqual(1, len(created))
        body = created[0][2]["body"]
        self.assertIn("Closes #42", body)
        self.assertEqual(1, body.count("Closes #42"))
        self.assertIn(SHIP_PR_MARKER, body)
        self.assertIn("# Acceptance criteria → evidence", body)
        self.assertEqual(1, len(self.calls))
        command = self.calls[0][0]
        self.assertEqual(["intake-pr-review", "42", "--pr", "43", "--agent-read"], command[-5:])
        self.assertEqual("test-token", self.calls[0][1]["env"]["GH_TOKEN"])
        self.assertNotIn("COPILOT_AGENT_TOKEN", self.calls[0][1]["env"])
        self.assertTrue(any("cloud-agent-pr-authorized:" in comment["body"] for comment in self.api.comments))

    def test_schedule_recovers_failed_intake_and_reuses_created_pr(self):
        def fail_once(command, **kwargs):
            self.calls.append(command)
            if len(self.calls) == 1:
                state = json.loads(self.api.comments[0]["body"].split("<!-- task-state: ", 1)[1].split(" -->", 1)[0])
                state.update({"state": "pr-review", "owner_agent": "pr-review-agent", "head_sha": SHA,
                              "actions": {"ship_pr_intake": {"pr": 43, "head_sha": SHA}}})
                self.api.comments[0]["body"] = "<!-- task-state: " + json.dumps(state) + " -->"
                self.api.issue["labels"] = [label for label in self.api.issue["labels"] if label["name"] != "agent-read"]
                self.api.issue["labels"].append({"name": "state:pr-review"})
                return subprocess.CompletedProcess(command, 1, "", "retry")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}):
            with self.assertRaisesRegex(RuntimeError, "scheduled recovery"):
                run("push", self.event, self.api, self.root, fail_once, self.pr_creation_api)
            self.assertTrue(run("schedule", {}, self.api, self.root, fail_once, self.pr_creation_api))

        created = [call for call in self.pr_creation_api.requests
                   if call[0] == "POST" and call[1] == "/repos/martinslavov/rcas/pulls"]
        self.assertEqual(1, len(created))
        self.assertEqual(2, len(self.calls))

    def run_schedule(self, api=None):
        api = api or self.api
        with patch.dict("os.environ", {"GITHUB_TOKEN": "t", "COPILOT_AGENT_TOKEN": "c"}):
            return api, run("schedule", {}, api, self.root, self.runner, FakePrCreationApi(api))

    def created_prs(self, api):
        return [r for r in api.requests if r[0] == "POST" and r[1] == "/repos/martinslavov/rcas/pulls"]

    def test_schedule_alone_discovers_fresh_push_and_creates_exactly_one_pr(self):
        self.assertFalse(any("cloud-agent-pr-authorized:" in c["body"] for c in self.api.comments))

        _, result = self.run_schedule()

        self.assertTrue(result)
        self.assertEqual(1, len(self.created_prs(self.api)))
        self.assertEqual(1, len(self.calls))
        self.assertEqual(["intake-pr-review", "42", "--pr", "43", "--agent-read"], self.calls[0][0][-5:])
        self.assertNotIn("COPILOT_AGENT_TOKEN", self.calls[0][1]["env"])
        self.run_schedule()
        self.assertEqual(1, len(self.created_prs(self.api)))

    def test_schedule_discovers_push_beyond_first_events_page(self):
        api = FakeGitHubApi()
        noise = {"type": "WatchEvent", "actor": {"login": "x", "id": 1}, "payload": {}}
        api.events_pages = [[noise] * 100, [noise] * 100, api.events]

        _, result = self.run_schedule(api)

        self.assertTrue(result)
        self.assertEqual(1, len(self.created_prs(api)))

    def test_schedule_falls_back_to_branch_activity_when_push_aged_out_of_events(self):
        api = FakeGitHubApi()
        api.activity = [{"ref": "refs/heads/" + BRANCH, "after": SHA,
                         "actor": {"login": "copilot-swe-agent", "id": 88}}]
        api.events = []

        _, result = self.run_schedule(api)

        self.assertTrue(result)
        self.assertEqual(1, len(self.created_prs(api)))

    def test_activity_fallback_rejects_forged_actor_and_empty_activity(self):
        for activity in ([{"ref": "refs/heads/" + BRANCH, "after": SHA,
                           "actor": {"login": "martinslavov", "id": 99}}], []):
            api = FakeGitHubApi()
            api.events = []
            api.activity = activity
            self.calls = []
            self.run_schedule(api)
            self.assertEqual([], self.created_prs(api))

    def test_schedule_discovery_rejections(self):
        def forged_actor(api):
            api.events[0]["actor"] = {"login": "martinslavov", "id": 99}

        def wrong_actor_id(api):
            api.events[0]["actor"]["id"] = 99

        def stale_sha(api):
            api.branch_sha = "b" * 40

        def not_feature(api):
            api.events[0]["payload"]["ref"] = "refs/heads/topic/42-cloud-flow"

        def other_issue(api):
            api.events[0]["payload"]["ref"] = "refs/heads/feature/43-cloud-flow"

        def unapproved(api):
            api.comments = [c for c in api.comments if "architecture-approved" not in c["body"]]

        def backlog(api):
            api.issue["labels"].append({"name": "backlog"})

        def no_events(api):
            api.events = []

        for mutate in (forged_actor, wrong_actor_id, stale_sha, not_feature, other_issue,
                       unapproved, backlog, no_events):
            with self.subTest(case=mutate.__name__):
                api = FakeGitHubApi()
                mutate(api)
                self.calls = []
                self.run_schedule(api)
                self.assertEqual([], self.created_prs(api))
                self.assertEqual([], self.calls)
                self.assertFalse(any("cloud-agent-pr-authorized:" in c["body"] for c in api.comments
                                     if c["user"]["login"] == "github-actions[bot]"
                                     and "created_at" in c))

    def test_new_pr_requires_copilot_token_before_creation(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "workflow-token"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "COPILOT_AGENT_TOKEN is required"):
                run("push", self.event, self.api, self.root, self.runner)

        self.assertFalse(any(request[0] == "POST" and request[1] == "/repos/martinslavov/rcas/pulls"
                             for request in self.api.requests))
        self.assertEqual([], self.calls)

    def test_existing_contract_pr_is_reused_without_duplicate_creation(self):
        self.api.prs.append({
            "number": 77,
            "state": "open",
            "body": "Closes #42\n" + SHIP_PR_MARKER,
            "base": {"ref": "main"},
            "head": {"ref": BRANCH, "sha": SHA, "repo": {"full_name": self.api.repository}},
        })

        self.assertTrue(run("push", self.event, self.api, self.root, self.runner))
        self.assertFalse(any(call[0] == "POST" and call[1] == "/repos/martinslavov/rcas/pulls" for call in self.api.requests))
        self.assertIn("77", self.calls[0][0])

    def test_rejects_non_agent_read_issue_non_feature_branch_and_unexpected_actor(self):
        cases = []
        no_label = FakeGitHubApi()
        no_label.issue["labels"] = []
        cases.append((no_label, self.event))
        non_feature = dict(self.event, ref="refs/heads/topic/42-cloud-flow")
        cases.append((FakeGitHubApi(), non_feature))
        unexpected = dict(self.event, sender={"login": "martinslavov", "id": 99})
        cases.append((FakeGitHubApi(), unexpected))

        for api, event in cases:
            with self.subTest(event=event):
                self.assertFalse(run("push", event, api, self.root, self.runner))
                self.assertFalse(any(request[1] == "/repos/martinslavov/rcas/pulls" for request in api.requests))
                self.assertEqual([], self.calls)

    def test_expected_actor_id_is_verified_against_github_user_api(self):
        event = dict(self.event, sender={"login": "copilot-swe-agent", "id": 99})

        self.assertFalse(run("push", event, self.api, self.root, self.runner))
        self.assertFalse(any(request[1] == "/repos/martinslavov/rcas/pulls" for request in self.api.requests))
        self.assertEqual([], self.calls)

    def test_backlog_label_blocks_cloud_pr_creation(self):
        self.api.issue["labels"].append({"name": "backlog"})

        self.assertFalse(run("push", self.event, self.api, self.root, self.runner))
        self.assertFalse(any("cloud-agent-pr-authorized:" in comment["body"] for comment in self.api.comments))
        self.assertEqual([], self.calls)

    def test_branch_issue_number_must_match_the_authoritative_issue(self):
        event = dict(self.event, ref="refs/heads/feature/43-cloud-flow")

        self.assertFalse(run("push", event, self.api, self.root, self.runner))
        self.assertFalse(any("cloud-agent-pr-authorized:" in comment["body"] for comment in self.api.comments))
        self.assertFalse(any(request[1] == "/repos/martinslavov/rcas/pulls" for request in self.api.requests))
        self.assertEqual([], self.calls)

    def test_required_approval_missing_fails_closed_before_authorization_or_pr(self):
        self.api.comments = [comment for comment in self.api.comments if "architecture-approved" not in comment["body"]]

        self.assertFalse(run("push", self.event, self.api, self.root, self.runner))
        self.assertFalse(any(request[1] == "/repos/martinslavov/rcas/pulls" for request in self.api.requests))
        self.assertFalse(any("cloud-agent-pr-authorized:" in comment["body"] for comment in self.api.comments))
        self.assertEqual([], self.calls)

    def test_design_note_requires_approval_even_without_approval_label(self):
        self.api.issue["labels"] = [label for label in self.api.issue["labels"]
                                    if label["name"] != "architecture-approval-required"]
        self.api.comments = [comment for comment in self.api.comments
                             if "architecture-approved" not in comment["body"]]

        self.assertFalse(run("push", self.event, self.api, self.root, self.runner))
        self.assertFalse(any("cloud-agent-pr-authorized:" in comment["body"] for comment in self.api.comments))
        self.assertEqual([], self.calls)

    def test_changed_branch_head_does_not_authorize_event_or_schedule_recovery(self):
        self.api.branch_sha = "b" * 40

        self.assertFalse(run("push", self.event, self.api, self.root, self.runner))
        self.assertEqual([], self.api.prs)
        self.assertEqual([], self.calls)


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import json
import pathlib
import re
import unittest

from agent_dashboard import (
    DASHBOARD_MARKER, GitHubClient, is_dashboard, parse_comments, render_dashboard, validate_record,
)


FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def top_level_block(text, key):
    lines = text.splitlines()
    start = lines.index(f"{key}:")
    block = []
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        if line.strip():
            block.append(line)
    return block


class FakeClient(GitHubClient):
    def __init__(self, pages=None, issues=None):
        super().__init__("token")
        self.pages = pages or {}
        self.issues = issues or {}
        self.calls = []

    def request(self, method, url, payload=None):
        self.calls.append((method, url, payload))
        if method == "GET" and url in self.issues:
            return self.issues[url], {}
        if method == "GET":
            body, link = self.pages[url]
            return body, ({"Link": f'<{link}>; rel="next"'} if link else {})
        if method == "POST" and url.endswith("/issues"):
            return {"number": 7, "html_url": "https://x/7", "url": "https://api/7", "node_id": "N", "state": "open"}, {}
        if method == "PATCH":
            return {"number": 7, "html_url": "https://x/7", "url": url, "node_id": "N", "state": "open"}, {}
        return {"data": {"node": {"isPinned": True}}}, {}


class AgentDashboardTests(unittest.TestCase):
    def test_parses_valid_records_and_deduplicates_exact_replays(self):
        comments = load_fixture("valid_comments.json")
        records = parse_comments(comments + [comments[0]])

        self.assertEqual(["product-owner-agent", "senior-qa-engineer"], [record.agent for record in records])
        self.assertEqual(("unit-tests",), records[1].checks_failed)
        self.assertEqual(1, records[1].retries)

    def test_warns_and_skips_malformed_records(self):
        warnings = []
        records = parse_comments(load_fixture("malformed_comments.json"), warnings.append)

        self.assertEqual([], records)
        self.assertEqual(2, len(warnings))
        self.assertTrue(all("skipped malformed" in warning for warning in warnings))

    def test_missing_records_are_silently_ignored(self):
        warnings = []
        records = parse_comments(load_fixture("missing_comments.json"), warnings.append)

        self.assertEqual([], records)
        self.assertEqual([], warnings)

    def test_rejects_inconsistent_duration_and_failure_without_source(self):
        valid = {
            "v": 1, "agent": "qa", "issue": 2, "pr": 3, "sha": "abc",
            "start": "2026-10-25T20:00:00Z", "end": "2026-10-25T20:01:00Z",
            "duration_s": 10, "checks_failed": [], "retries": 0,
            "status": "failure", "failure_source": None,
        }
        with self.assertRaisesRegex(ValueError, "duration_s"):
            validate_record(valid)
        valid["duration_s"] = 60
        with self.assertRaisesRegex(ValueError, "failure_source is required"):
            validate_record(valid)

    def test_renders_task_agent_failure_and_timestamp_aggregates(self):
        records = parse_comments(load_fixture("valid_comments.json"))
        comments = {
            63: [{"body": "<!-- qa-round:1 -->"}],
            64: [{"body": "<!-- qa-round:1 -->\n<!-- ci-fix-attempt:1 -->"}],
        }
        markdown = render_dashboard(records, comments, dt.datetime(2026, 10, 25, 21, tzinfo=dt.timezone.utc))

        self.assertIn("<!-- agent-dashboard -->", markdown)
        self.assertIn("Last updated: 2026-10-25T21:00:00Z", markdown)
        self.assertIn("| #63 | #64 |", markdown)
        self.assertIn("product-owner-agent (1), senior-qa-engineer (1)", markdown)
        self.assertIn("420s | 1 | 1 | 1 | failure", markdown)
        self.assertIn("| senior-qa-engineer | 1 | 0.0% | 330.0s | 330.0s | 1 |", markdown)
        self.assertIn("| tests | 1 | 100.0% |", markdown)
        self.assertIn("| infrastructure | 0 | 0.0% |", markdown)

    def test_renders_empty_dashboard_without_records(self):
        markdown = render_dashboard([], {}, dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc))

        self.assertIn("| — | — | — | 0s | 0 | 0 | 0 | no records |", markdown)
        self.assertIn("| **Total classified failures** | 0 | 0.0% |", markdown)

    def test_every_agent_documents_run_record_posting(self):
        # Agent file names are a short, stable slug (e.g. "architect.agent.md") decoupled from the
        # agent id posted in run records, which lives in the frontmatter "name:" field instead.
        root = pathlib.Path(__file__).resolve().parents[3]
        agent_names = {
            "product-owner-agent", "architect-agent", "senior-java-software-engineer",
            "pr-review-agent", "senior-qa-engineer", "dod-validator-agent",
        }
        files = list((root / ".github/agents").glob("*.agent.md"))
        self.assertEqual(len(agent_names), len(files))
        found_names = [
            re.search(r"(?m)^name:\s*(\S+)\s*$", path.read_text(encoding="utf-8")).group(1)
            for path in files
        ]
        self.assertEqual(len(found_names), len(set(found_names)))
        self.assertCountEqual(agent_names, found_names)
        for path in files:
            name = re.search(r"(?m)^name:\s*(\S+)\s*$", path.read_text(encoding="utf-8")).group(1)
            with self.subTest(agent=name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("agent-run:", content)
                self.assertIn("date -u +%Y-%m-%dT%H:%M:%SZ", content)
                self.assertIn("gh issue comment", content)

    def test_dashboard_and_board_workflows_have_expected_guards_and_permissions(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        dashboard = (root / ".github/workflows/ci-agent-dashboard.yml").read_text(encoding="utf-8")
        board = (root / ".github/workflows/ci-issue-board.yml").read_text(encoding="utf-8")
        # No YAML parser in the stdlib: check top-level blocks by indentation instead of substrings.
        on_block = top_level_block(dashboard, "on")
        self.assertEqual(["push:", "schedule:", "workflow_dispatch:"],
                         [line.strip() for line in on_block if line.startswith("  ") and not line.startswith("   ")])
        self.assertIn("    branches: [main]", on_block)
        self.assertNotIn("pull_request", dashboard)
        self.assertIn("permissions: {}", dashboard.splitlines())
        job_permissions = dashboard.split("    permissions:\n", 1)[1].splitlines()[:3]
        self.assertEqual(["contents: read", "pull-requests: read", "issues: write"],
                         [line.strip() for line in job_permissions])
        self.assertTrue(any("cancel-in-progress: false" in line for line in top_level_block(dashboard, "concurrency")))
        self.assertIn("if: github.ref == 'refs/heads/main'", dashboard)
        self.assertIn("agent-dashboard", board)


    def test_get_all_follows_pagination_links(self):
        client = FakeClient({"u1": ([1, 2], "u2"), "u2": ([3], "")})
        self.assertEqual([1, 2, 3], client.get_all("u1"))
        self.assertEqual(["u1", "u2"], [call[1] for call in client.calls])

    ISSUE_URL = "https://api.github.com/repos/o/r/issues/7"

    def dashboard_client(self, **fields):
        issue = {"number": 7, "html_url": "https://x/7", "node_id": "N", "state": "open",
                 "body": DASHBOARD_MARKER + "\nold", **fields}
        return FakeClient(issues={self.ISSUE_URL: issue})

    def writes(self, client):
        return [call for call in client.calls if call[0] in {"POST", "PATCH"} and "graphql" not in call[1]]

    def test_publish_updates_explicit_issue_in_place_without_listing(self):
        client = self.dashboard_client()
        self.assertIn("updated", client.publish("o/r", 7, "new"))
        self.assertEqual([("PATCH", self.ISSUE_URL, {"body": "new"})], self.writes(client))
        self.assertEqual([("GET", self.ISSUE_URL)], [c[:2] for c in client.calls if c[0] == "GET"])

    def test_publish_reopens_closed_dashboard(self):
        client = self.dashboard_client(state="closed")
        client.publish("o/r", 7, "new")
        self.assertEqual({"body": "new", "state": "open"}, self.writes(client)[0][2])

    def test_publish_refuses_issue_without_marker_or_pull_request(self):
        for fields in ({"body": "someone else's issue"}, {"body": f"quote {DASHBOARD_MARKER}"},
                       {"pull_request": {}}):
            client = self.dashboard_client(**fields)
            with self.assertRaisesRegex(RuntimeError, "not the agent dashboard"):
                client.publish("o/r", 7, "new")
            self.assertEqual([], self.writes(client))

    def test_publish_without_number_fails_and_never_creates(self):
        client = FakeClient()
        with self.assertRaisesRegex(RuntimeError, "AGENT_DASHBOARD_ISSUE is not configured"):
            client.publish("o/r", None, "new")
        self.assertEqual([], client.calls)

    def test_publish_creates_only_with_explicit_create_flag(self):
        client = FakeClient()
        self.assertIn("created", client.publish("o/r", None, "body", create=True))
        self.assertEqual("POST", self.writes(client)[0][0])
        with self.assertRaises(RuntimeError):
            FakeClient().publish("o/r", 7, "body", create=True)

    def test_workflow_passes_configured_issue_and_never_creates(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        workflow = (root / ".github/workflows/ci-agent-dashboard.yml").read_text(encoding="utf-8")
        self.assertIn("AGENT_DASHBOARD_ISSUE: ${{ vars.AGENT_DASHBOARD_ISSUE }}", workflow)
        self.assertNotIn("--create", workflow)

    def test_dashboard_detection_ignores_pull_requests_and_quoted_markers(self):
        self.assertFalse(is_dashboard({"body": f"mentions {DASHBOARD_MARKER} in prose"}))
        self.assertFalse(is_dashboard({"body": DASHBOARD_MARKER, "pull_request": {}}))
        self.assertTrue(is_dashboard({"body": DASHBOARD_MARKER + "\n# Agent Workflow Dashboard"}))


if __name__ == "__main__":
    unittest.main()

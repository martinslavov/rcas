import unittest
from pathlib import Path

from local_agent_worker import (
    LOCAL_FAILED_LABEL,
    LocalAgentWorker,
    build_pr_body,
    eligible_issue,
    task_slug,
    task_state,
)


class LocalAgentWorkerTest(unittest.TestCase):
    def test_only_owner_authored_local_issues_are_eligible(self):
        issue = {
            "state": "open",
            "user": {"login": "martinslavov"},
            "labels": [{"name": "local-agent"}],
        }
        self.assertTrue(eligible_issue(issue))
        for label in ("cloud-agent", "backlog", "requires-pro", LOCAL_FAILED_LABEL, "needs-human-review"):
            with self.subTest(label=label):
                rejected = {**issue, "labels": [*issue["labels"], {"name": label}]}
                self.assertFalse(eligible_issue(rejected))
        self.assertFalse(eligible_issue({**issue, "user": {"login": "contributor"}}))

    def test_reads_one_task_state_comment(self):
        comments = [{"body": '<!-- task-state: {"issue": 41, "state": "todo"} -->'}]
        self.assertEqual("todo", task_state(comments, 41)["state"])
        self.assertIsNone(task_state([], 41))
        with self.assertRaisesRegex(RuntimeError, "multiple"):
            task_state(comments * 2, 41)

    def test_branch_slug_is_ascii_safe_and_has_fallback(self):
        self.assertEqual("cache-refactor", task_slug("Cache refactor!"))
        self.assertEqual("task", task_slug("Локална задача"))

    def test_pr_body_closes_issue_and_maps_acceptance_criteria(self):
        template = (
            "# Description\n\n# Pull-request relations\n- Closes #<issue>\n\n"
            "# Acceptance criteria → evidence\n"
            "| <acceptance criterion> | <e.g. `FooTest#expiresAfterTtl` asserts the entry is gone after the TTL> |\n"
        )
        body = build_pr_body(
            template,
            41,
            "### Acceptance criteria\n- [ ] Cache expires after its TTL\n- Return a safe error\n\n### Notes\nNo schema change",
        )
        self.assertIn("- Closes #41", body)
        self.assertIn("| Cache expires after its TTL |", body)
        self.assertIn("| Return a safe error |", body)
        self.assertIn("<!-- ship-pr -->", body)

    def test_local_agent_prompts_keep_review_and_qa_gated(self):
        worker = LocalAgentWorker(Path.cwd(), poll_seconds=60, max_rounds=5)
        issue = {"number": 41}

        review = worker.issue_prompt(issue, "review", pr=77)
        qa = worker.issue_prompt(issue, "qa", pr=77)

        self.assertIn("Do not post inline PR reviews", review)
        self.assertIn("verification-only local-worker run", qa)
        self.assertIn("do not edit files or push", qa)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import patch

from local_agent_worker import (
    LOCAL_FAILED_LABEL,
    LocalAgentWorker,
    WorkerError,
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

    def test_skip_architect_hands_todo_directly_to_engineer(self):
        worker = LocalAgentWorker(Path.cwd(), poll_seconds=60, max_rounds=5)
        issue = {"number": 41}
        labels = {"local-agent", "skip-architect", "skip-product-owner", "architecture-approval-required"}
        with (
            patch.object(worker, "run_agent") as run_agent,
            patch.object(worker, "orchestrator", return_value={"state": "implementation"}) as orchestrator,
        ):
            result = worker.advance_to_implementation(issue, labels, [], {"state": "todo"}, "session")

        self.assertEqual("implementation", result["state"])
        orchestrator.assert_called_once_with(
            "transition", "41", "implementation", "--agent", "senior-java-software-engineer",
        )
        run_agent.assert_not_called()

    def test_worker_runs_engineer_in_worktree_after_skipped_architecture(self):
        worker = LocalAgentWorker(Path.cwd(), poll_seconds=60, max_rounds=5)
        issue = {
            "number": 41,
            "labels": [{"name": label} for label in (
                "local-agent", "skip-architect", "skip-product-owner",
            )],
        }
        worktree = Path("/tmp/rcas-issue-41")
        with (
            patch.object(worker, "issue_details", return_value=(issue, [])),
            patch.object(worker, "comments_and_state", return_value=([], {"state": "todo"})),
            patch.object(worker, "record_start", return_value=123),
            patch.object(worker, "prepare_worktree", return_value=(worktree, "feature/task", "issue-41")),
            patch("local_agent_worker._run", return_value="[]"),
            patch.object(worker, "orchestrator", side_effect=[{"state": "implementation"}, {}]),
            patch.object(worker, "run_agent") as run_agent,
            patch.object(worker, "verify_pushed_branch"),
            patch.object(worker, "create_or_reuse_pr", return_value=77),
            patch.object(worker, "pr_info", return_value={"head": {"sha": "a" * 40}}),
            patch.object(worker, "set_pending_statuses"),
            patch.object(worker, "finish_pr") as finish_pr,
        ):
            worker.run_issue(41)

        self.assertEqual(1, run_agent.call_count)
        self.assertEqual("senior-java-software-engineer", run_agent.call_args.args[0])
        self.assertEqual(worktree, run_agent.call_args.args[2])
        self.assertEqual((issue, 77, worktree, "issue-41", 123), finish_pr.call_args.args[:5])
        self.assertEqual("pr-review", finish_pr.call_args.args[-1])

    def test_merge_uses_validated_head_and_stops_when_head_changes(self):
        sha = "a" * 40
        issue = {"number": 41, "title": "test"}
        eligible = {"state": "open", "user": {"login": "martinslavov"}, "labels": [{"name": "local-agent"}]}
        worker = LocalAgentWorker(Path.cwd(), poll_seconds=60, max_rounds=5)
        worker.owner = "martinslavov"
        merge_command = [
            "gh", "pr", "merge", "77", "-R", "martinslavov/rcas", "--merge",
            "--delete-branch", "--match-head-commit", sha,
        ]
        with (
            patch("local_agent_worker._gh_json", return_value=eligible),
            patch.object(worker, "pr_info", side_effect=[
                {"head": {"sha": sha}, "state": "open", "draft": False},
                {"head": {"sha": "b" * 40}, "state": "open", "merged": False},
            ]),
            patch.object(worker, "labels", return_value=set()),
            patch.object(worker, "status_for", return_value="success"),
            patch.object(worker, "ci_state", return_value="success"),
            patch.object(worker, "has_human_comments", return_value=False),
            patch.object(worker, "orchestrator", return_value={"state": "merge"}) as orchestrator,
            patch("local_agent_worker._run", side_effect=WorkerError("head changed")) as run,
        ):
            with self.assertRaisesRegex(WorkerError, "head changed"):
                worker.merge_if_ready(issue, 77, sha, 123)
            run.assert_called_once_with(merge_command)
            orchestrator.assert_called_once_with("state", "41")


if __name__ == "__main__":
    unittest.main()

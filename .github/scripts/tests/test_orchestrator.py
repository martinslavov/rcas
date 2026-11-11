import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock

from orchestrator import (
    ACTIVE_STATES,
    ATTEMPT_LOOPS,
    ENTRY_LABEL,
    PR_REVIEW_INTAKE_ACTION,
    SHIP_PR_MARKER,
    STATE_TABLE,
    Orchestrator,
    OrchestratorError,
    default_record,
    main,
    parse_record,
    pr_review_intake_record,
    serialize_record,
    transition_record,
    validate_transition,
)


class OrchestratorStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.now = "2026-10-26T09:00:00Z"

    def record(self, state="implementation"):
        return default_record(101, state, "human", self.now)

    def test_every_allowed_edge(self):
        for source, (owner, targets) in STATE_TABLE.items():
            for target in targets:
                with self.subTest(source=source, target=target):
                    actor = owner or "human"
                    record = self.record(source)
                    updated = transition_record(record, target, actor, now=self.now)
                    self.assertEqual(updated["state"], target)
            if source in ACTIVE_STATES:
                for target in ("blocked", "human-review"):
                    with self.subTest(source=source, target=target, actor="stage owner"):
                        actor = owner or "human"
                        updated = transition_record(self.record(source), target, actor, now=self.now)
                        self.assertEqual(updated["resume_state"], source)
                    with self.subTest(source=source, target=target, actor="human"):
                        updated = transition_record(self.record(source), target, "human", now=self.now)
                        self.assertEqual(updated["resume_state"], source)

    def test_blocked_and_human_review_resume_only_to_saved_state(self):
        for exceptional in ("blocked", "human-review"):
            with self.subTest(state=exceptional):
                paused = transition_record(self.record("implementation"), exceptional, "human", now=self.now)
                self.assertEqual(paused["resume_state"], "implementation")
                resumed = transition_record(paused, "implementation", "human", now=self.now)
                self.assertIsNone(resumed["resume_state"])
                self.assertEqual(resumed["owner_agent"], "senior-java-software-engineer")
                with self.assertRaisesRegex(OrchestratorError, "saved resume_state"):
                    transition_record(paused, "pr-review", "human", now=self.now)
                with self.assertRaisesRegex(OrchestratorError, "only human"):
                    transition_record(paused, "implementation", "senior-java-software-engineer", now=self.now)

    def test_qa_cannot_transition_to_dod(self):
        with self.assertRaises(OrchestratorError):
            transition_record(self.record("qa"), "dod", "senior-qa-engineer", now=self.now)

    def test_rejected_edges(self):
        for source, (_, targets) in STATE_TABLE.items():
            allowed = set(targets)
            if source in ACTIVE_STATES:
                allowed.update({"blocked", "human-review"})
            for target in STATE_TABLE:
                if target not in allowed and source not in {"blocked", "human-review"}:
                    with self.subTest(source=source, target=target):
                        with self.assertRaises(OrchestratorError):
                            validate_transition(self.record(source), target, STATE_TABLE[source][0] or "human")

    def test_wrong_agent_is_rejected(self):
        with self.assertRaisesRegex(OrchestratorError, "cannot transition"):
            validate_transition(self.record("implementation"), "pr-review", "pr-review-agent")
        with self.assertRaisesRegex(OrchestratorError, "cannot transition"):
            validate_transition(self.record("architecture"), "implementation", "senior-java-software-engineer")

    def test_rejected_pure_requests_make_zero_gh_calls(self):
        runner = Mock()
        orchestrator = Orchestrator(runner)
        with self.assertRaises(OrchestratorError):
            orchestrator.prepare_transition(self.record("implementation"), "done", "senior-java-software-engineer")
        with self.assertRaises(OrchestratorError):
            orchestrator.prepare_transition(self.record("implementation"), "pr-review", "qa-agent")
        runner.assert_not_called()

    def test_approval_pending_requires_an_explicit_owner_approval_comment(self):
        approval_record = self.record("approval-pending")
        body = serialize_record(approval_record)
        runner = Mock(return_value=json.dumps({"id": 101, "body": body, "author": "martinslavov"}))
        orchestrator = Orchestrator(runner)
        with self.assertRaisesRegex(OrchestratorError, "architecture-approved"):
            orchestrator.transition(101, "implementation", "human", None, dry_run=False)
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(all("-X" not in call.args[0] for call in runner.call_args_list))

    def test_record_serialization_and_parse_round_trip(self):
        record = self.record()
        encoded = serialize_record(record)
        self.assertTrue(encoded.startswith("<!-- task-state: {"))
        self.assertTrue(encoded.endswith("} -->"))
        self.assertEqual(parse_record(encoded), record)
        self.assertEqual(record["lock"]["ttl_s"], 1800)
        self.assertEqual(record["actions"], {})
        self.assertEqual(set(record["attempts"]), set(ATTEMPT_LOOPS))
        self.assertTrue(all(v == {"count": 0, "last_reason": None, "last_signature": None}
                            for v in record["attempts"].values()))

    def test_parse_requires_exactly_one_valid_record(self):
        with self.assertRaisesRegex(OrchestratorError, "found 0"):
            parse_record("no state here")
        encoded = serialize_record(self.record())
        with self.assertRaisesRegex(OrchestratorError, "found 2"):
            parse_record(encoded + "\n" + encoded)
        malformed = "<!-- task-state: {not-json} -->"
        with self.assertRaisesRegex(OrchestratorError, "invalid task-state JSON"):
            parse_record(malformed)

    def test_transition_edits_canonical_comment_before_label_and_board_projection(self):
        record = self.record()
        calls = []

        def runner(args):
            calls.append(args)
            if args[-1] == f"repos/martinslavov/rcas/issues/101/comments":
                return json.dumps({"id": 987, "body": serialize_record(record), "author": "martinslavov"})
            if args[-1] == "repos/martinslavov/rcas/issues/101/labels":
                return "state:implementation"
            return ""

        orchestrator = Orchestrator(runner)
        updated = orchestrator.transition(101, "pr-review", "senior-java-software-engineer", None, False)
        self.assertEqual(updated["state"], "pr-review")
        patch_index = next(i for i, call in enumerate(calls) if "-X" in call and "PATCH" in call)
        label_index = next(i for i, call in enumerate(calls) if call[:3] == ["gh", "label", "create"])
        board_index = next(i for i, call in enumerate(calls) if call[-3:] == ["move", "101", "In Progress"])
        self.assertLess(patch_index, label_index)
        self.assertLess(label_index, board_index)
        self.assertTrue(any("-X" in call and "POST" in call for call in calls))
        self.assertTrue(any("-X" in call and "DELETE" in call and call[-1].endswith("state:implementation")
                            for call in calls))

    def test_projection_failure_reports_comment_is_already_canonical(self):
        record = self.record()
        calls = []

        def runner(args):
            calls.append(args)
            if args[-1] == "repos/martinslavov/rcas/issues/101/comments":
                return json.dumps({"id": 987, "body": serialize_record(record), "author": "martinslavov"})
            if args[:3] == ["gh", "label", "create"]:
                raise RuntimeError("label service unavailable")
            return ""

        orchestrator = Orchestrator(runner)
        with self.assertRaisesRegex(OrchestratorError, "state comment was updated, but projection failed"):
            orchestrator.transition(101, "pr-review", "senior-java-software-engineer", None, False)
        self.assertTrue(any("PATCH" in call for call in calls))
        self.assertFalse(any("task_queue.sh" in call[0] for call in calls))

    def test_transition_updates_head_sha_and_metadata(self):
        updated = transition_record(
            self.record(), "pr-review", "senior-java-software-engineer",
            "0123456789abcdef", now=self.now,
        )
        self.assertEqual(updated["head_sha"], "0123456789abcdef")
        self.assertEqual(updated["updated_by"], "senior-java-software-engineer")
        self.assertEqual(updated["updated_at"], self.now)

    def test_ship_pr_intake_moves_only_supported_states_into_pr_review(self):
        for state in ("todo", "implementation"):
            with self.subTest(state=state):
                updated = pr_review_intake_record(
                    self.record(state), 202, "a" * 40, now=self.now,
                )
                self.assertEqual(updated["state"], "pr-review")
                self.assertEqual(updated["owner_agent"], "pr-review-agent")
                self.assertEqual(updated["head_sha"], "a" * 40)
                self.assertEqual(updated["updated_by"], "ship-pr")
                self.assertEqual(
                    updated["actions"][PR_REVIEW_INTAKE_ACTION],
                    {"pr": 202, "head_sha": "a" * 40},
                )

    def test_ship_pr_intake_is_idempotent_for_the_same_pr_and_head(self):
        first = pr_review_intake_record(self.record("implementation"), 202, "a" * 40, now=self.now)
        repeated = pr_review_intake_record(
            first, 202, "a" * 40, now="2026-10-26T10:00:00Z",
        )
        self.assertEqual(repeated, first)
        updated = pr_review_intake_record(first, 202, "b" * 40, now="2026-10-26T10:00:00Z")
        self.assertEqual(updated["head_sha"], "b" * 40)

    def test_ship_pr_intake_rejects_invalid_states_shas_and_different_prs(self):
        for state in ("backlog", "architecture", "approval-pending", "qa", "done"):
            with self.subTest(state=state):
                with self.assertRaisesRegex(OrchestratorError, "cannot start PR Review"):
                    pr_review_intake_record(self.record(state), 202, "a" * 40)
        with self.assertRaisesRegex(OrchestratorError, "head SHA"):
            pr_review_intake_record(self.record(), 202, "not-a-sha")
        first = pr_review_intake_record(self.record(), 202, "a" * 40, now=self.now)
        with self.assertRaisesRegex(OrchestratorError, "different ship-pr PR"):
            pr_review_intake_record(first, 203, "b" * 40)

    def test_ship_pr_intake_requires_linked_ship_pr_and_orders_label_dispatch_last(self):
        record = self.record("implementation")
        comments = [{"id": 987, "body": serialize_record(record), "author": "x"}]
        issue = {
            "number": 101,
            "state": "open",
            "labels": [{"name": ENTRY_LABEL}],
        }
        pr = {
            "number": 202,
            "state": "open",
            "body": f"Closes #101\n{SHIP_PR_MARKER}",
            "base": {"ref": "main"},
            "head": {"sha": "a" * 40},
            "labels": [],
        }
        calls = []

        def runner(args):
            calls.append(args)
            endpoint = args[-1]
            if endpoint == "repos/martinslavov/rcas/issues/101":
                return json.dumps(issue)
            if endpoint == "repos/martinslavov/rcas/pulls/202":
                return json.dumps(pr)
            if endpoint == "repos/martinslavov/rcas/issues/101/comments":
                return "\n".join(json.dumps(comment) for comment in comments)
            if endpoint == "repos/martinslavov/rcas/issues/101/labels":
                return "state:implementation\nagent-read"
            return ""

        updated = Orchestrator(runner).intake_pr_review(101, 202, True, False)
        self.assertEqual(updated["state"], "pr-review")
        patch_index = next(i for i, call in enumerate(calls) if "PATCH" in call)
        start_index = next(
            i for i, call in enumerate(calls)
            if "POST" in call and any("agent-automation-start:" in value for value in call)
        )
        issue_label_removal_index = next(
            i for i, call in enumerate(calls)
            if "DELETE" in call and call[-1].endswith(f"/labels/{ENTRY_LABEL}")
        )
        pr_label_index = next(
            i for i, call in enumerate(calls)
            if "POST" in call and call[-1] == f"labels[]={ENTRY_LABEL}"
        )
        self.assertLess(patch_index, start_index)
        self.assertLess(start_index, issue_label_removal_index)
        self.assertLess(issue_label_removal_index, pr_label_index)

    def test_ship_pr_intake_refuses_unlinked_or_unmarked_pr_without_mutations(self):
        record = self.record("todo")
        issue = {"number": 101, "state": "open", "labels": []}
        pr = {
            "number": 202,
            "state": "open",
            "body": "Closes #101",
            "base": {"ref": "main"},
            "head": {"sha": "a" * 40},
            "labels": [],
        }
        calls = []

        def runner(args):
            calls.append(args)
            endpoint = args[-1]
            if endpoint == "repos/martinslavov/rcas/issues/101":
                return json.dumps(issue)
            if endpoint == "repos/martinslavov/rcas/pulls/202":
                return json.dumps(pr)
            if endpoint == "repos/martinslavov/rcas/issues/101/comments":
                return json.dumps({"id": 987, "body": serialize_record(record), "author": "x"})
            return ""

        with self.assertRaisesRegex(OrchestratorError, "created by /ship-pr"):
            Orchestrator(runner).intake_pr_review(101, 202, True, False)
        self.assertFalse(any("-X" in call for call in calls))

    def test_ship_pr_intake_without_agent_read_does_not_opt_into_automation(self):
        record = self.record("todo")
        comments = [{"id": 987, "body": serialize_record(record), "author": "x"}]
        issue = {"number": 101, "state": "open", "labels": []}
        pr = {
            "number": 202,
            "state": "open",
            "body": f"Closes #101\n{SHIP_PR_MARKER}",
            "base": {"ref": "main"},
            "head": {"sha": "a" * 40},
            "labels": [],
        }
        calls = []

        def runner(args):
            calls.append(args)
            endpoint = args[-1]
            if endpoint == "repos/martinslavov/rcas/issues/101":
                return json.dumps(issue)
            if endpoint == "repos/martinslavov/rcas/pulls/202":
                return json.dumps(pr)
            if endpoint == "repos/martinslavov/rcas/issues/101/comments":
                return "\n".join(json.dumps(comment) for comment in comments)
            if endpoint == "repos/martinslavov/rcas/issues/101/labels":
                return "state:todo"
            return ""

        updated = Orchestrator(runner).intake_pr_review(101, 202, False, False)
        self.assertEqual(updated["state"], "pr-review")
        self.assertFalse(any(
            "POST" in call
            and call[-2:] == ["-f", f"labels[]={ENTRY_LABEL}"]
            for call in calls
        ))

    def issue_runner(self, calls, comments, label_fail=False, board_fail=False):
        def runner(args):
            calls.append(args)
            if args[-1] == "repos/martinslavov/rcas/issues/101":
                return json.dumps({"number": 101})
            if args[-1] == "repos/martinslavov/rcas/issues/101/comments":
                return "\n".join(json.dumps(c) for c in comments)
            if args[-1] == "repos/martinslavov/rcas/issues/101/labels":
                return "state:qa\nstate:implementation\nbug"
            if label_fail and args[:3] == ["gh", "label", "create"]:
                raise RuntimeError("label down")
            if board_fail and args[0].endswith("task_queue.sh"):
                raise RuntimeError("board down")
            return ""
        return runner

    def test_init_refuses_later_states_for_every_agent_including_human(self):
        for state in sorted(set(STATE_TABLE) - {"backlog", "todo"}):
            for agent in ("senior-java-software-engineer", "architect-agent", "human"):
                with self.subTest(state=state, agent=agent):
                    calls = []
                    orchestrator = Orchestrator(self.issue_runner(calls, []))
                    with self.assertRaisesRegex(OrchestratorError, "may seed only backlog or todo"):
                        orchestrator.init(101, state, agent)
                    self.assertEqual(calls, [])

    def test_init_cli_refuses_later_state_with_non_zero_exit_and_no_gh_calls(self):
        for state, agent in (("qa", "human"), ("done", "human"), ("implementation", "senior-java-software-engineer")):
            with self.subTest(state=state, agent=agent):
                runner = Mock(return_value="")
                with redirect_stderr(io.StringIO()) as err:
                    code = main(["init", "101", "--state", state, "--agent", agent], runner=runner)
                self.assertNotEqual(code, 0)
                self.assertIn("may seed only backlog or todo", err.getvalue())
                runner.assert_not_called()

    def test_init_allows_backlog_and_todo_for_any_agent(self):
        for state in ("backlog", "todo"):
            for agent in ("architect-agent", "human"):
                with self.subTest(state=state, agent=agent):
                    calls = []
                    record = Orchestrator(self.issue_runner(calls, [])).init(101, state, agent)
                    self.assertEqual(record["state"], state)
                    self.assertEqual(record["updated_by"], agent)
                    self.assertTrue(any("POST" in c and c[-1].startswith("body=<!-- task-state:") for c in calls))

    def test_init_refused_when_record_exists(self):
        calls = []
        comments = [{"id": 5, "body": serialize_record(self.record()), "author": "x"}]
        with self.assertRaisesRegex(OrchestratorError, "already has a task-state record"):
            Orchestrator(self.issue_runner(calls, comments)).init(101, "todo", "human")
        self.assertFalse(any("POST" in c or "PATCH" in c for c in calls))

    def test_init_requires_agent(self):
        with self.assertRaisesRegex(OrchestratorError, "--agent is required"):
            Orchestrator(self.issue_runner([], [])).init(101, "todo", "")

    def test_reconcile_projects_canonical_state_without_changing_record(self):
        calls = []
        comments = [{"id": 5, "body": serialize_record(self.record()), "author": "x"}]
        record = Orchestrator(self.issue_runner(calls, comments)).reconcile(101)
        self.assertEqual(record, self.record())
        self.assertFalse(any("PATCH" in c or c[-1].startswith("body=") for c in calls))
        self.assertTrue(any(c[:3] == ["gh", "label", "create"] and "state:implementation" in c for c in calls))
        self.assertTrue(any("-X" in c and "DELETE" in c and c[-1].endswith("state:qa") for c in calls))
        self.assertFalse(any("DELETE" in c and c[-1].endswith("state:implementation") for c in calls))
        self.assertTrue(any(c[-3:] == ["move", "101", "In Progress"] for c in calls))

    def test_reconcile_recovers_after_each_projection_failure(self):
        for kwargs in ({"label_fail": True}, {"board_fail": True}):
            with self.subTest(failure=kwargs):
                comments = [{"id": 5, "body": serialize_record(self.record("pr-review")), "author": "x"}]
                with self.assertRaisesRegex(OrchestratorError, "reconcile 101"):
                    Orchestrator(self.issue_runner([], comments, **kwargs)).transition(
                        101, "qa", "pr-review-agent", None, False)
                # canonical record is already qa, so reconcile (no failure) repairs projection
                comments = [{"id": 5, "body": serialize_record(self.record("qa")), "author": "x"}]
                calls = []
                self.assertEqual(Orchestrator(self.issue_runner(calls, comments)).reconcile(101)["state"], "qa")
                self.assertTrue(any(c[-3:] == ["move", "101", "In Progress"] for c in calls))

    def test_reconcile_requires_record(self):
        with self.assertRaisesRegex(OrchestratorError, "found 0"):
            Orchestrator(self.issue_runner([], [])).reconcile(101)


if __name__ == "__main__":
    unittest.main()

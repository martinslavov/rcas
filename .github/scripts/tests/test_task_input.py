import contextlib
import io
import unittest
from unittest.mock import patch

from task_input import TaskInputError, main, parse_task_input


class TaskInputTest(unittest.TestCase):
    def test_canonical_task_then_tag_order_consumes_control_lines(self):
        parsed = parse_task_input("TASK-NAME:cloud-flow\nTAG: agent-read\nDo the work")

        self.assertEqual("cloud-flow", parsed.task_name)
        self.assertEqual("Do the work", parsed.description)
        self.assertEqual(("agent-read",), parsed.labels)
        self.assertNotIn("TAG:", parsed.description)

    def test_development_and_multiple_tags_become_issue_labels(self):
        parsed = parse_task_input(
            "TASK-NAME:cloud-flow\n"
            "DEVELOPMENT: high\n"
            "TAG: agent-read,skip-architect,skip-product-owner\n"
            "DESCRIPTION: Do the work")

        self.assertEqual("Do the work", parsed.description)
        self.assertEqual(
            ("agent-read", "skip-architect", "skip-product-owner", "development:high"),
            parsed.labels)

    def test_supported_tags_can_be_used_independently(self):
        parsed = parse_task_input("TASK-NAME:task\nTAG: skip-architect\nDo this")

        self.assertEqual(("skip-architect",), parsed.labels)
        self.assertEqual("Do this", parsed.description)

    def test_development_is_optional_and_case_insensitive(self):
        parsed = parse_task_input("TASK-NAME:task\nDEVELOPMENT: Medium\nDo this")

        self.assertEqual(("development:medium",), parsed.labels)

    def test_plain_task_name_keeps_local_default(self):
        parsed = parse_task_input("TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("cloud-flow", "Do the work", ()),
                         (parsed.task_name, parsed.description, parsed.labels))

    def test_legacy_tag_first_order_remains_supported(self):
        parsed = parse_task_input("TAG: agent-read\nTASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("cloud-flow", "Do the work", ("agent-read",)),
                         (parsed.task_name, parsed.description, parsed.labels))

    def test_backlog_prefix_is_case_insensitive_and_keeps_backlog_label(self):
        parsed = parse_task_input("label:BACKLOG,TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("backlog",), parsed.labels)
        self.assertEqual("Do the work", parsed.description)

    def test_tag_on_second_line_combines_with_backlog_label(self):
        parsed = parse_task_input(
            "LABEL:BACKLOG,TASK-NAME:cloud-flow\nTAG: agent-read\nDo the work")

        self.assertEqual(("agent-read", "backlog"), parsed.labels)
        self.assertEqual("Do the work", parsed.description)

    def test_legacy_tag_first_order_combines_with_backlog_label(self):
        parsed = parse_task_input(
            "TAG: agent-read\nLABEL:BACKLOG,TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("agent-read", "backlog"), parsed.labels)
        self.assertEqual("Do the work", parsed.description)

    def test_description_prefix_is_removed_but_text_is_preserved(self):
        parsed = parse_task_input("TASK-NAME:task\nDESCRIPTION: Do the work\nTAG: in prose")

        self.assertEqual("Do the work\nTAG: in prose", parsed.description)

    def test_tag_later_in_description_is_not_a_control_line(self):
        parsed = parse_task_input("TASK-NAME:task\nDo this\nTAG: agent-read")

        self.assertEqual((), parsed.labels)
        self.assertEqual("Do this\nTAG: agent-read", parsed.description)

    def test_invalid_inputs_are_rejected(self):
        for text in (
            "",
            "TAG: agent-read",
            "TAG: other\nTASK-NAME:task",
            "TAG: agent-read extra\nTASK-NAME:task",
            "TASK-NAME:task\nTAG: other",
            "TASK-NAME:task\nTAG: agent-read extra",
            "TASK-NAME:task\nTAG: agent-read,other",
            "TASK-NAME:task\nTAG: agent-read, skip-architect",
            "TASK-NAME:task\nDEVELOPMENT: hight",
            "TASK-NAME:task\nDEVELOPMENT: low\nDEVELOPMENT: high",
            "TAG: agent-read\nnot-a-task",
            "TASK-NAME:",
            "LABEL:BACKLOG,TASK-NAME:   ",
        ):
            with self.subTest(text=text), self.assertRaises(TaskInputError):
                parse_task_input(text)

    def test_invalid_input_returns_exit_code_two_with_clear_error(self):
        stderr = io.StringIO()
        with patch("sys.stdin", io.StringIO("TASK-NAME:task\nTAG: unsupported")), \
                contextlib.redirect_stderr(stderr):
            exit_code = main()

        self.assertEqual(2, exit_code)
        self.assertIn("unsupported TAG", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

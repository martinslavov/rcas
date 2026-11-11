import unittest

from task_input import TaskInputError, parse_task_input


class TaskInputTest(unittest.TestCase):
    def test_agent_read_tag_is_consumed_and_applies_opt_in_label(self):
        parsed = parse_task_input("TAG: agent-read\nTASK-NAME:cloud-flow\nDo the work")

        self.assertEqual("cloud-flow", parsed.task_name)
        self.assertEqual("Do the work", parsed.description)
        self.assertEqual(("agent-read",), parsed.labels)
        self.assertNotIn("TAG:", parsed.description)

    def test_plain_task_name_keeps_local_default(self):
        parsed = parse_task_input("TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("cloud-flow", "Do the work", ()),
                         (parsed.task_name, parsed.description, parsed.labels))

    def test_backlog_prefix_is_case_insensitive_and_keeps_backlog_label(self):
        parsed = parse_task_input("label:BACKLOG,TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("backlog",), parsed.labels)
        self.assertEqual("Do the work", parsed.description)

    def test_tag_can_precede_existing_backlog_contract_without_changing_labels(self):
        parsed = parse_task_input("TAG: agent-read\nLABEL:BACKLOG,TASK-NAME:cloud-flow\nDo the work")

        self.assertEqual(("agent-read", "backlog"), parsed.labels)
        self.assertEqual("Do the work", parsed.description)

    def test_other_tags_and_malformed_control_lines_are_rejected(self):
        for text in (
            "TAG: other\nTASK-NAME:task",
            "TAG: agent-read extra\nTASK-NAME:task",
            "TAG: agent-read",
            "TAG: agent-read\nnot-a-task",
        ):
            with self.subTest(text=text), self.assertRaises(TaskInputError):
                parse_task_input(text)


if __name__ == "__main__":
    unittest.main()

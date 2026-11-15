import unittest

from architecture_assessment import (
    NOT_REQUIRED,
    REQUIRED,
    UNCERTAIN,
    assessment_from_body,
    has_current_approval,
    reassessment_count,
    requires_architect,
)


class ArchitectureAssessmentTest(unittest.TestCase):
    @staticmethod
    def body(value):
        return (
            "### Architecture assessment\n"
            f"<!-- architecture-assessment: {value} -->\n"
            f"Decision: {value}\n"
            "Rationale: Documentation-only task with no runtime or contract change."
        )

    def test_only_one_known_not_required_marker_skips_architect(self):
        body = self.body(NOT_REQUIRED)
        self.assertEqual(NOT_REQUIRED, assessment_from_body(body))
        self.assertFalse(requires_architect(body))

    def test_required_uncertain_missing_malformed_and_duplicate_markers_fail_safe(self):
        for body, expected in (
            (self.body(REQUIRED), REQUIRED),
            (self.body(UNCERTAIN), UNCERTAIN),
            (None, REQUIRED),
            ("not assessed", REQUIRED),
            ("<!-- architecture-assessment: invalid -->", REQUIRED),
            (
                "### Architecture assessment\n"
                "<!-- architecture-assessment: not-required -->\n"
                "<!-- architecture-assessment: unknown -->\n"
                "Decision: not-required\nRationale: Not applicable.",
                REQUIRED,
            ),
            (
                "### Architecture assessment\n"
                "<!-- architecture-assessment: not-required -->\n"
                "<!-- architecture-assessment: not-required -->\n"
                "Decision: not-required\nRationale: Not applicable.",
                REQUIRED,
            ),
            (
                "### Architecture assessment\n"
                "<!-- architecture-assessment: not-required -->\n"
                "Decision: not-required",
                REQUIRED,
            ),
            (
                "### Architecture assessment\n"
                "<!-- architecture-assessment: not-required -->\n"
                "Decision: required\n"
                "Rationale: Mismatched decision.",
                REQUIRED,
            ),
        ):
            with self.subTest(body=body):
                self.assertEqual(expected, assessment_from_body(body))
                self.assertTrue(requires_architect(body))

    def test_explicit_opt_out_precedes_assessment_and_approval_label(self):
        self.assertFalse(requires_architect(
            self.body(REQUIRED),
            {"skip-architect", "architecture-approval-required"},
        ))
        self.assertTrue(requires_architect(
            self.body(NOT_REQUIRED),
            {"architecture-approval-required"},
        ))

    def test_reassessment_count_counts_each_durable_request_comment_once(self):
        comments = [
            {"body": "<!-- architecture-review-requested --> scope changed"},
            {"body": "ordinary note"},
            {"body": "<!-- architecture-review-requested --> more scope"},
        ]
        self.assertEqual(2, reassessment_count(comments))

    def test_only_approval_after_latest_architect_review_is_current(self):
        old_approval = {
            "body": (
                "<!-- architecture-approved --> "
                "Approved by @martinslavov at 2026-01-01T00:00:00Z"
            ),
            "user": {"login": "martinslavov"},
        }
        design = {
            "body": "<!-- architect-design-note -->\nApproval required: yes",
            "user": {"login": "copilot-swe-agent[bot]"},
        }
        self.assertFalse(has_current_approval([old_approval, design], "martinslavov"))
        self.assertTrue(has_current_approval(
            [design, old_approval], "martinslavov",
        ))


if __name__ == "__main__":
    unittest.main()

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILLS = ROOT / ".github" / "skills"


class PrSkillContractsTest(unittest.TestCase):
    def test_cloud_handoff_is_default_and_keeps_merge_gates(self):
        skill = (SKILLS / "create-pr-cloud" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: create-pr-cloud", skill)
        self.assertIn("intake-pr-review <issue> --pr <pr> --cloud-agent", skill)
        self.assertIn("bounded fix", skill)
        self.assertIn("automatic merge when all gates pass", skill)
        self.assertIn("<!-- ship-pr -->", skill)
        self.assertIn("keep the PR open", skill)
        self.assertFalse((SKILLS / "ship-pr" / "SKILL.md").exists())

    def test_local_pr_has_no_cloud_handoff_and_verifies_before_merge(self):
        skill = (SKILLS / "create-pr-local" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: create-pr-local", skill)
        self.assertIn("<!-- no-task-issue -->", skill)
        self.assertIn("Do not add `<!-- ship-pr -->`", skill)
        self.assertIn("Delegate PR Review to `pr-review-agent`", skill)
        self.assertIn("Delegate QA to `senior-qa-engineer`", skill)
        self.assertIn("--match-head-commit <verified-head-sha>", skill)
        self.assertIn("human PR comment or review", skill)
        self.assertIn("DoD is manual only", skill)
        self.assertFalse((SKILLS / "create-quick-pr" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()

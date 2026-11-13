"""Exercise worktree cleanup against isolated local Git repositories."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("worktree-session.sh").resolve()


class WorktreeCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.repo = root / "repo"
        self.target = root / "repo-sessions" / "example"
        self.environment = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.run_command("git", "init", "--bare", str(root / "remote.git"), cwd=root)
        self.repo.mkdir()
        self.git("init", "-b", "main")
        destination = self.repo / ".github/scripts"
        destination.mkdir(parents=True)
        shutil.copyfile(SCRIPT, destination / SCRIPT.name)
        self.git("add", ".")
        self.git("commit", "-m", "Initial helper")
        self.git("remote", "add", "origin", str(root / "remote.git"))
        self.git("push", "-u", "origin", "main")
        self.helper("start", "example", "--no-open")

    def run_command(self, *args, cwd=None, check=True):
        return subprocess.run(
            args, cwd=cwd or self.repo, env=self.environment,
            text=True, capture_output=True, check=check,
        )

    def git(self, *args, cwd=None):
        return self.run_command("git", *args, cwd=cwd)

    def helper(self, *args, check=True):
        return self.run_command(
            "bash", str(self.repo / ".github/scripts" / SCRIPT.name),
            *args, check=check,
        )

    def assert_cleanup_refused(self, message):
        result = self.helper("cleanup", "example", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertTrue(self.target.is_dir())

    def test_removes_merged_session_feature_and_hotfix_branches(self):
        for prefix in ("session", "feature", "hotfix"):
            with self.subTest(prefix=prefix):
                if not self.target.exists():
                    self.helper("start", "example", "--no-open")
                branch = f"{prefix}/example"
                if prefix != "session":
                    self.git("branch", "-m", branch, cwd=self.target)
                (self.target / "change").write_text(prefix)
                self.git("add", "change", cwd=self.target)
                self.git("commit", "-m", "Worktree change", cwd=self.target)
                self.git("merge", "--no-ff", branch, "-m", "Merge worktree")
                self.git("push", "origin", "main")
                self.helper("cleanup", "example")
                self.assertFalse(self.target.exists())
                self.assertNotEqual(self.run_command(
                    "git", "show-ref", "--verify", f"refs/heads/{branch}", check=False,
                ).returncode, 0)

    def test_refuses_unrelated_branch_and_detached_head(self):
        self.git("branch", "-m", "feature/different", cwd=self.target)
        self.assert_cleanup_refused("expected session/example")
        self.git("checkout", "--detach", cwd=self.target)
        self.assert_cleanup_refused("expected session/example")

    def test_refuses_untracked_and_modified_files(self):
        self.git("branch", "-m", "feature/example", cwd=self.target)
        extra = self.target / "untracked"
        extra.write_text("keep")
        self.assert_cleanup_refused("uncommitted or untracked")
        extra.unlink()
        with (self.target / ".github/scripts" / SCRIPT.name).open("a") as script:
            script.write("\n# local edit\n")
        self.assert_cleanup_refused("uncommitted or untracked")

    def test_refuses_unmerged_feature_branch(self):
        self.git("branch", "-m", "feature/example", cwd=self.target)
        (self.target / "unmerged").write_text("keep")
        self.git("add", "unmerged", cwd=self.target)
        self.git("commit", "-m", "Not merged", cwd=self.target)
        self.assert_cleanup_refused("not merged into origin/main")


if __name__ == "__main__":
    unittest.main()

"""Agent scratch files (result.json reports) must never be staged into a PR."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.runner import clean_build_artifacts


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _staged_after_clean(cwd: Path) -> list[str]:
    clean_build_artifacts(cwd)
    _git(cwd, "add", "-A")
    return _git(cwd, "diff", "--cached", "--name-only").split()


class ArtifactHygieneTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "app.py").write_text("x = 1\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        self._tmp.cleanup()

    def test_untracked_result_json_is_not_staged(self):
        (self.repo / "app.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "result.json").write_text('{"status": "DONE"}', encoding="utf-8")
        (self.repo / "slot-1.result.json").write_text("{}", encoding="utf-8")

        self.assertEqual(_staged_after_clean(self.repo), ["app.py"])

    def test_tracked_result_json_changes_are_still_staged(self):
        (self.repo / "result.json").write_text("{}", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "track result.json")
        (self.repo / "result.json").write_text('{"v": 2}', encoding="utf-8")

        self.assertEqual(_staged_after_clean(self.repo), ["result.json"])

    def test_rules_added_when_exclude_already_has_pycache(self):
        exclude = self.repo / ".git" / "info" / "exclude"
        exclude.write_text("__pycache__/\n", encoding="utf-8")
        (self.repo / "result.json").write_text("{}", encoding="utf-8")

        self.assertEqual(_staged_after_clean(self.repo), [])


if __name__ == "__main__":
    unittest.main()

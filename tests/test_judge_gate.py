"""Judge gate: the judge avoids the coder's engine, and a bugfix's new tests must fail without the fix."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew import loop_helpers, runner
from auto_dev_crew.evaluator import pick_judge_pool


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    *args], cwd=cwd, check=True, capture_output=True)


class PickJudgePoolTests(unittest.TestCase):
    def setUp(self):
        self.a = {"name": "opencode-a"}
        self.b = {"name": "opencode-b"}

    def test_no_exclusion_keeps_all(self):
        self.assertEqual(pick_judge_pool([self.a, self.b], None), ([self.a, self.b], False))

    def test_coder_engine_is_removed_from_pool(self):
        self.assertEqual(pick_judge_pool([self.a, self.b], "opencode-a"), ([self.b], False))

    def test_only_coder_engine_left_is_kept_and_flagged(self):
        self.assertEqual(pick_judge_pool([self.a], "opencode-a"), ([self.a], True))

    def test_empty_pool_stays_empty(self):
        self.assertEqual(pick_judge_pool([], "opencode-a"), ([], False))


class TestFileDetectionTests(unittest.TestCase):
    def test_test_files_are_selected(self):
        files = ["calc.py", "tests/test_calc.py", "src/app.test.js", "pkg/util_test.py", "docs/readme.md"]
        self.assertEqual(loop_helpers.test_files(files),
                         ["tests/test_calc.py", "src/app.test.js", "pkg/util_test.py"])

    def test_touched_tests_agrees_with_test_files(self):
        self.assertFalse(loop_helpers.touched_tests(["calc.py"]))
        self.assertTrue(loop_helpers.touched_tests(["calc.py", "tests/test_calc.py"]))


class ReproTestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")  # the bug
        (self.repo / "tests").mkdir()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.steps = [f'"{sys.executable}" -m unittest discover -s tests -p "test_*.py"']
        self.env = dict(os.environ)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_test(self, body: str) -> None:
        (self.repo / "tests" / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n\n"
            "class T(unittest.TestCase):\n"
            f"    def test_add(self):\n        {body}\n",
            encoding="utf-8")

    def test_test_that_fails_on_base_reproduces_bug(self):
        self._write_test("self.assertEqual(add(2, 2), 4)")
        self.assertTrue(runner._new_tests_fail_on_base(self.repo, ["tests/test_calc.py"], self.steps, self.env))

    def test_test_that_passes_on_base_does_not_reproduce(self):
        self._write_test("self.assertEqual(add(2, 0), 2)")
        self.assertFalse(runner._new_tests_fail_on_base(self.repo, ["tests/test_calc.py"], self.steps, self.env))

    def test_real_worktree_is_left_alone(self):
        self._write_test("self.assertEqual(add(2, 2), 4)")
        runner._new_tests_fail_on_base(self.repo, ["tests/test_calc.py"], self.steps, self.env)
        listing = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True,
                                 check=True).stdout
        self.assertEqual(len([line for line in listing.splitlines() if line.strip()]), 1)
        self.assertIn("return a - b", (self.repo / "calc.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

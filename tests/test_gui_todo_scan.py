import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from auto_dev_crew import gui

CFG = {"labels": {"task": "ai-task"}}
PULL_OK = SimpleNamespace(returncode=0, stdout="", stderr="")


class TestGuiTodoScan(unittest.TestCase):
    def _root(self, d):
        (Path(d) / "a.py").write_text("# [AI-TODO] do it\n", encoding="utf-8")
        return Path(d)

    @patch("auto_dev_crew.gui.load_cfg", return_value=CFG)
    @patch("auto_dev_crew.runner.gh")
    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.todo_scan.subprocess.run", return_value=PULL_OK)
    def test_create_false_never_calls_gh(self, mock_pull, mock_dir, mock_gh, _cfg):
        with tempfile.TemporaryDirectory() as d:
            mock_dir.return_value = self._root(d)
            res = gui.act("/api/todo-scan", {"repo": "o/r", "create": False})
        self.assertTrue(res["ok"])
        self.assertEqual(res["items"][0]["path"], "a.py")
        self.assertNotIn("created", res)
        mock_gh.assert_not_called()
        self.assertEqual(mock_pull.call_args.args[0], ["git", "pull", "--ff-only"])

    @patch("auto_dev_crew.gui.load_cfg", return_value=CFG)
    @patch("auto_dev_crew.runner.gh")
    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.todo_scan.subprocess.run", return_value=PULL_OK)
    def test_create_true_creates_issue(self, mock_pull, mock_dir, mock_gh, _cfg):
        def fake(*args, **kw):
            return "[]" if args[:2] == ("issue", "list") else "https://x/issues/1"
        mock_gh.side_effect = fake
        with tempfile.TemporaryDirectory() as d:
            mock_dir.return_value = self._root(d)
            res = gui.act("/api/todo-scan", {"repo": "o/r", "create": True})
        self.assertEqual(res["created"], ["https://x/issues/1"])
        self.assertEqual(res["errors"], [])

    def test_missing_repo_rejected(self):
        with self.assertRaises(ValueError):
            gui.act("/api/todo-scan", {"create": False})


if __name__ == "__main__":
    unittest.main()

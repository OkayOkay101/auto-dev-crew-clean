"""CLI entry `python -m auto_dev_crew --scan-todos <owner/repo>`."""
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew import runner


class TestScanTodosCli(unittest.TestCase):
    def _run(self, argv, scan_result=None):
        """Run auto_dev_crew.__main__ with argv; returns (exit_code, run_scan_mock)."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.yaml").write_text("labels:\n  task: ai-task\n", encoding="utf-8")
            with patch.object(sys, "argv", ["auto_dev_crew", *argv]), \
                 patch.object(runner, "ROOT", Path(d)), \
                 patch("auto_dev_crew.todo_scan.run_scan", return_value=scan_result) as scan, \
                 patch("auto_dev_crew.runner.main", side_effect=AssertionError("runner.main must not run")), \
                 self.assertRaises(SystemExit) as cm:
                runpy.run_module("auto_dev_crew", run_name="__main__")
        return cm.exception.code, scan

    def test_prints_items_and_never_creates(self):
        res = {"items": [{"path": "a.py", "line": 3, "text": "add retry"}], "warnings": []}
        with patch("builtins.print") as pr:
            code, scan = self._run(["--scan-todos", "o/r"], res)
        self.assertEqual(code, 0)
        scan.assert_called_once()
        self.assertEqual(scan.call_args.args[0], "o/r")
        self.assertEqual(scan.call_args.args[1], {"labels": {"task": "ai-task"}})
        self.assertIs(scan.call_args.kwargs["create"], False)
        printed = [c.args[0] for c in pr.call_args_list]
        self.assertIn("a.py:3 add retry", printed)
        self.assertIn("พบ 1 รายการ", printed)

    def test_missing_repo_exits_2(self):
        with patch("builtins.print"):
            code, scan = self._run(["--scan-todos"])
        self.assertEqual(code, 2)
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()

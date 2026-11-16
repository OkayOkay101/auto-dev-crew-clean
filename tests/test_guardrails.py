import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.guardrails import (
    truncate_tool_output,
    check_deterministic_pre_eval,
    prune_resolved_evidence,
)
from auto_dev_crew.evaluator import evaluate_diff


class TestGuardrails(unittest.TestCase):
    def test_truncate_tool_output_short(self):
        text = "short output"
        self.assertEqual(truncate_tool_output(text, max_chars=100), text)

    def test_truncate_tool_output_long(self):
        head_part = "START" * 50
        tail_part = "END" * 50
        middle_part = "M" * 5000
        full_text = head_part + middle_part + tail_part
        truncated = truncate_tool_output(full_text, max_chars=500)
        self.assertLessEqual(len(truncated), 600)  # max_chars + message length
        self.assertIn("START", truncated)
        self.assertIn("END", truncated)
        self.assertIn("[... Truncated", truncated)

    def test_check_deterministic_pre_eval_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            good_file = tmppath / "valid.py"
            good_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
            
            ok, msg = check_deterministic_pre_eval(tmppath, changed_files=["valid.py"])
            self.assertTrue(ok)
            self.assertIn("passed", msg.lower())

    def test_check_deterministic_pre_eval_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            bad_file = tmppath / "bad.py"
            bad_file.write_text("def broken(:\n    invalid syntax\n", encoding="utf-8")
            
            ok, msg = check_deterministic_pre_eval(tmppath, changed_files=["bad.py"])
            self.assertFalse(ok)
            self.assertIn("Syntax Error", msg)

    def test_prune_resolved_evidence(self):
        history = [
            {"step": 1, "action": "test", "status": "failed", "output": "Traceback:\n" + ("x" * 2000)},
            {"step": 2, "action": "edit", "status": "ok", "output": "edited foo.py"},
            {"step": 3, "action": "test", "status": "ok", "output": "All 10 passed"},
        ]
        pruned = prune_resolved_evidence(history)
        self.assertEqual(len(pruned), 3)
        # Step 1 failed test should be pruned to tombstone because step 3 resolved it
        self.assertIn("resolved", pruned[0]["output"].lower())
        self.assertLess(len(pruned[0]["output"]), 200)
        # Step 3 should remain intact
        self.assertEqual(pruned[2]["output"], "All 10 passed")

    def test_evaluator_blocks_syntax_error_before_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            bad_file = tmppath / "bad.py"
            bad_file.write_text("def broken(:\n", encoding="utf-8")

            cfg = {
                "evaluation": {
                    "enabled": True,
                    "engine": "judge-eng",
                    "min_pass_score": 0.75,
                }
            }
            # evaluate_diff should fail fast without calling LLM when syntax error exists
            diff = "--- a/bad.py\n+++ b/bad.py\n@@ -0,0 +1 @@\n+def broken(:"
            res = evaluate_diff(diff, "Task description", "test output", cfg, tmppath)
            self.assertFalse(res.passed)
            self.assertEqual(res.score, 0.0)
            self.assertIn("Syntax Error", res.critique_th)


    def test_evaluator_blocks_empty_diff_without_calling_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            cfg = {"evaluation": {"enabled": True, "engine": "judge-eng"}}
            res = evaluate_diff("", "Task description", "test output", cfg, tmppath)
            self.assertFalse(res.passed)
            self.assertEqual(res.score, 0.0)
            self.assertIn("diff ว่างเปล่า", res.critique_th)

    def test_evaluator_ignores_unrelated_broken_files_in_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Create an unrelated broken file (e.g. template or fixture)
            broken = tmppath / "unrelated_broken.py"
            broken.write_text("def error(:\n", encoding="utf-8")
            # Create a valid changed file
            valid = tmppath / "valid.py"
            valid.write_text("def ok(): return True\n", encoding="utf-8")

            cfg = {"evaluation": {"enabled": False}}  # so it returns pass without LLM call
            diff = "--- a/valid.py\n+++ b/valid.py\n@@ -0,0 +1 @@\n+def ok(): return True"
            # It should not fail on unrelated_broken.py
            res = evaluate_diff(diff, "Task description", "test output", cfg, tmppath)
            self.assertTrue(res.passed)


if __name__ == "__main__":
    unittest.main()

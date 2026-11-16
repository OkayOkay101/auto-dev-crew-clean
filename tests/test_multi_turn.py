import unittest

from auto_dev_crew.experimental.multi_turn import (
    build_multi_turn_history,
    format_delta_turn,
)


class TestMultiTurn(unittest.TestCase):
    def test_format_delta_turn_combines_errors_and_rubric(self):
        delta = format_delta_turn(
            test_failure_output="AssertionError: 42 != 43 in test_math.py",
            rubric_feedback="Alignment score 0.4: did not address the root issue",
            ast_syntax_error="SyntaxError: invalid syntax on line 12",
        )
        self.assertIn("## Verification Feedback & Errors (Delta)", delta)
        self.assertIn("SyntaxError: invalid syntax on line 12", delta)
        self.assertIn("AssertionError: 42 != 43", delta)
        self.assertIn("Alignment score 0.4", delta)
        self.assertIn("DO NOT restart from scratch", delta)

    def test_build_multi_turn_history_3_turns(self):
        initial = "Fix bug #42 in calculator"
        diff = "diff --git a/calc.py b/calc.py\n+ return a + b"
        err = "FAILED tests/test_calc.py - NameError: name 'a' is not defined"

        turns = build_multi_turn_history(
            initial_prompt=initial,
            previous_diff=diff,
            test_failure_output=err,
            rubric_feedback=None,
        )

        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[0].content, initial)
        self.assertTrue(turns[0].cache_control)

        self.assertEqual(turns[1].role, "assistant")
        self.assertEqual(turns[1].content, diff)

        self.assertEqual(turns[2].role, "user")
        self.assertIn("FAILED tests/test_calc.py", turns[2].content)
        # Verify delta turn does not duplicate initial prompt
        self.assertNotIn("Fix bug #42 in calculator", turns[2].content)


if __name__ == "__main__":
    unittest.main()

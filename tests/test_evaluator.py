import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew.evaluator import parse_eval_response, check_convergence, evaluate_diff


class TestEvaluator(unittest.TestCase):
    def test_parse_eval_response_json_fenced(self):
        raw = """Here is the evaluation:
```json
{
  "task_alignment": 0.9,
  "safety_cleanliness": 0.8,
  "quality": 0.85,
  "critique_th": "ปรับปรุงโค้ดดีมาก ไม่พบปัญหา"
}
```
"""
        weights = {"alignment_weight": 0.4, "safety_cleanliness_weight": 0.3, "quality_weight": 0.3}
        res = parse_eval_response(raw, min_score=0.75, weights=weights)
        self.assertTrue(res.passed)
        self.assertAlmostEqual(res.score, 0.855, places=2)
        self.assertIn("ปรับปรุงโค้ดดีมาก", res.critique_th)
        self.assertEqual(res.dimensions["task_alignment"], 0.9)

    def test_parse_eval_response_fail_threshold(self):
        raw = """{
  "task_alignment": 0.4,
  "safety_cleanliness": 0.5,
  "quality": 0.4,
  "critique_th": "โค้ดยังไม่ตอบโจทย์ และมี debug print หลงเหลือ"
}"""
        weights = {"alignment_weight": 0.4, "safety_cleanliness_weight": 0.3, "quality_weight": 0.3}
        res = parse_eval_response(raw, min_score=0.75, weights=weights)
        self.assertFalse(res.passed)
        self.assertLess(res.score, 0.75)
        self.assertIn("debug print", res.critique_th)

    def test_parse_eval_response_fallback_on_corrupt(self):
        raw = "Sorry I cannot evaluate this diff because it was too large."
        res = parse_eval_response(raw, min_score=0.75)
        self.assertFalse(res.passed)
        self.assertEqual(res.score, 0.0)
        self.assertIn("ไม่สามารถแยกผลการประเมิน", res.critique_th)

    def test_parse_eval_response_null_and_invalid_types(self):
        raw = """```json
{
  "task_alignment": null,
  "safety_cleanliness": "not-a-number",
  "quality": 0.8,
  "critique_th": "ทดสอบค่า null"
}
```"""
        # Must not raise TypeError or ValueError, must treat null/non-number as 0.0
        res = parse_eval_response(raw, min_score=0.75)
        self.assertFalse(res.passed)
        self.assertEqual(res.dimensions["task_alignment"], 0.0)
        self.assertEqual(res.dimensions["safety_cleanliness"], 0.0)
        self.assertEqual(res.dimensions["quality"], 0.8)

    def test_convergence_detection(self):
        # Improving scores -> not converged
        self.assertFalse(check_convergence([0.5, 0.7]))
        self.assertFalse(check_convergence([0.7]))
        self.assertFalse(check_convergence([]))
        # Non-improving scores -> converged
        self.assertTrue(check_convergence([0.6, 0.55]))
        self.assertTrue(check_convergence([0.7, 0.7]))
        self.assertTrue(check_convergence([0.4, 0.8, 0.79]))

    def test_evaluate_diff_dedicated_engine_routing(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {
                "enabled": True,
                "engine": "judge-eng",
                "min_pass_score": 0.75
            },
            "engines": [
                {"name": "coder-eng", "command": "opencode", "model": "m1", "enabled": True},
                {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent:
            mock_agent.return_value = {
                "status": "SUCCESS",
                "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่าน"}'
            }
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            # Verify call_agent was passed target_cfg with judge-eng
            passed_cfg = mock_agent.call_args[0][0]
            self.assertEqual(len(passed_cfg["engines"]), 1)
            self.assertEqual(passed_cfg["engines"][0]["name"], "judge-eng")

    def test_evaluate_diff_auto_routing_by_key_role(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {
                "enabled": True,
                "engine": "auto",
                "min_pass_score": 0.75
            },
            "engines": [
                {"name": "coder-eng", "command": "opencode", "model": "m1", "enabled": True, "api_keys": ["${KEY_CODER}"]},
                {"name": "pollinations-judge", "command": "opencode", "model": "m2", "enabled": True, "api_keys": ["${KEY_JUDGE}"]}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent, \
             patch("auto_dev_crew.runner.load_dotenv", return_value={"KEY_CODER": "val1", "KEY_JUDGE": "val2"}), \
             patch("auto_dev_crew.runner.get_key_effective_roles", side_effect=lambda var: ["judge"] if var == "KEY_JUDGE" else ["coder"]):
            mock_agent.return_value = {
                "status": "SUCCESS",
                "response": '{"task_alignment": 0.95, "safety_cleanliness": 0.95, "quality": 0.95, "critique_th": "ผ่าน"}'
            }
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            passed_cfg = mock_agent.call_args[0][0]
            self.assertEqual(len(passed_cfg["engines"]), 1)
            self.assertEqual(passed_cfg["engines"][0]["name"], "pollinations-judge")

    def test_evaluate_diff_disabled(self):
        cfg = {
            "evaluation": {
                "enabled": False,
                "engine": "auto",
            },
            "engines": [
                {"name": "eng", "command": "opencode", "model": "m", "enabled": True}
            ]
        }
        res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
        self.assertTrue(res.passed)
        self.assertEqual(res.score, 1.0)
        self.assertIn("ข้ามการประเมิน", res.critique_th)

    def test_evaluate_diff_fallback_to_default_when_judge_fails(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {
                "enabled": True,
                "engine": "judge-eng",
                "min_pass_score": 0.75
            },
            "engines": [
                {"name": "default-coder", "command": "opencode", "model": "m1", "enabled": True},
                {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent:
            mock_agent.side_effect = [
                {"status": "ERROR", "response": "Model not found on dedicated judge"},
                {"status": "SUCCESS", "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่านการประเมินโดย fallback"}'}
            ]
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            self.assertGreaterEqual(res.score, 0.75)
            self.assertIn("ผ่านการประเมินโดย fallback", res.critique_th)
            self.assertEqual(mock_agent.call_count, 2)

    def test_evaluate_diff_fallback_when_judge_raises_exception(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {
                "enabled": True,
                "engine": "judge-eng",
                "min_pass_score": 0.75
            },
            "engines": [
                {"name": "default-coder", "command": "opencode", "model": "m1", "enabled": True},
                {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent:
            mock_agent.side_effect = [
                RuntimeError("Connection reset by peer"),
                {"status": "SUCCESS", "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "กู้คืนสำเร็จ"}'}
            ]
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            self.assertEqual(mock_agent.call_count, 2)
            self.assertIn("กู้คืนสำเร็จ", res.critique_th)
            self.assertTrue(res.judge_fallback)

    def test_dedicated_judge_verdict_is_not_marked_as_fallback(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {"enabled": True, "engine": "judge-eng", "min_pass_score": 0.75},
            "engines": [
                {"name": "default-coder", "command": "opencode", "model": "m1", "enabled": True},
                {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent:
            mock_agent.side_effect = [
                {"status": "SUCCESS", "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่านจาก judge หลัก"}'}
            ]
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            self.assertFalse(res.judge_fallback)
            self.assertEqual(mock_agent.call_count, 1)

    def test_fallback_after_timeout_exception_is_marked_as_fallback(self):
        from unittest.mock import patch
        cfg = {
            "evaluation": {"enabled": True, "engine": "judge-eng", "min_pass_score": 0.75},
            "engines": [
                {"name": "default-coder", "command": "opencode", "model": "m1", "enabled": True},
                {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.runner.call_agent") as mock_agent:
            mock_agent.side_effect = [
                RuntimeError("agent timed out after 300.0s"),
                {"status": "SUCCESS", "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่านจาก fallback"}'}
            ]
            res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
            self.assertTrue(res.passed)
            self.assertTrue(res.judge_fallback)


def test_judge_runs_outside_worktree(tmp_path):
    """MED-13: the judge runs --auto, so it must not run inside the job's worktree."""
    from unittest.mock import patch
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    cfg = {"evaluation": {"enabled": True}, "engines": [{"name": "e", "command": "opencode", "enabled": True}]}
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = {"status": "SUCCESS", "response":
                                   '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9}'}
        evaluate_diff("diff", "task", "out", cfg, worktree)
    judge_cwd = Path(mock_agent.call_args.args[2]).resolve()
    assert judge_cwd != worktree.resolve()
    assert worktree.resolve() not in judge_cwd.parents


def test_judge_prompt_placeholders_in_task_are_not_expanded(tmp_path):
    """LOW-04: a task body containing {{git_diff}} must reach the judge literally."""
    from unittest.mock import patch
    cfg = {"evaluation": {"enabled": True}, "engines": [{"name": "e", "command": "opencode", "enabled": True}]}
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = {"status": "SUCCESS", "response":
                                   '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9}'}
        evaluate_diff("DIFFCONTENT", "use {{git_diff}} literally", "out", cfg, tmp_path)
    prompt = mock_agent.call_args.args[1]
    assert "use {{git_diff}} literally" in prompt


def _added_diff(n: int) -> str:
    body = "".join(f"+line{i}" + chr(10) for i in range(n))
    return "--- a/x.txt" + chr(10) + "+++ b/x.txt" + chr(10) + f"@@ -0,0 +1,{n} @@" + chr(10) + body


def _fast_cfg(**eval_overrides) -> dict:
    ev = {"enabled": True}
    ev.update(eval_overrides)
    return {"evaluation": ev, "engines": [{"name": "e", "command": "opencode", "enabled": True}]}


_OK_JUDGE = {"status": "SUCCESS", "response":
             '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9}'}


def test_fast_mode_rejects_diff_over_cap(tmp_path):
    from unittest.mock import patch
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = _OK_JUDGE
        res = evaluate_diff(_added_diff(31), "task", "out", _fast_cfg(), tmp_path, mode="fast")
    assert res.passed is False
    assert res.score == 0.0
    assert "30" in res.critique_th
    mock_agent.assert_not_called()


def test_fast_mode_allows_diff_at_cap(tmp_path):
    from unittest.mock import patch
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = _OK_JUDGE
        evaluate_diff(_added_diff(30), "task", "out", _fast_cfg(), tmp_path, mode="fast")
    mock_agent.assert_called()


def test_heavy_mode_ignores_cap(tmp_path):
    from unittest.mock import patch
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = _OK_JUDGE
        evaluate_diff(_added_diff(200), "task", "out", _fast_cfg(), tmp_path, mode="heavy")
    mock_agent.assert_called()


def test_fast_cap_configurable(tmp_path):
    from unittest.mock import patch
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = _OK_JUDGE
        res = evaluate_diff(_added_diff(6), "task", "out", _fast_cfg(max_fast_diff_lines=5),
                            tmp_path, mode="fast")
    assert res.passed is False
    assert "5" in res.critique_th
    mock_agent.assert_not_called()


def test_fast_cap_counts_lockfile_only_diff(tmp_path):
    """Lock/generated files get no exemption: a package-lock.json-only diff over the cap is rejected."""
    from unittest.mock import patch
    diff = _added_diff(31).replace("x.txt", "package-lock.json")
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.return_value = _OK_JUDGE
        res = evaluate_diff(diff, "task", "out", _fast_cfg(), tmp_path, mode="fast")
    assert res.passed is False
    assert res.score == 0.0
    mock_agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""O27 / O25 wiring tests: Graceful Drain, quiet hours, convergence guard in the eval gate, bug-check windows."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import autonomous_upgrades, quality_gates, runner
from auto_dev_crew.evaluator import EvaluationResult


def _result(score: float, passed: bool) -> EvaluationResult:
    return EvaluationResult(score=score, passed=passed, critique_th="ทดสอบ", dimensions={})


class TestGracefulDrainWiring(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self._patch = mock.patch.object(runner, "STATE", self.state)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_drain_flag_follows_the_drain_file(self):
        self.assertFalse(runner._graceful_drain_requested())
        autonomous_upgrades.request_graceful_drain(state_dir=self.state)
        self.assertTrue(runner._graceful_drain_requested())
        autonomous_upgrades.clear_graceful_drain(self.state)
        self.assertFalse(runner._graceful_drain_requested())

    def test_worker_takes_no_new_job_while_draining(self):
        autonomous_upgrades.request_graceful_drain(state_dir=self.state)
        with mock.patch.object(runner, "process_slot", side_effect=AssertionError("must not pick a job")):
            # loop=True would normally keep polling; the drain must end the worker before any job starts.
            runner.slot_worker_loop(1, {}, {"name": "r"}, True, True, None, None, None)


class TestQuietHoursWiring(unittest.TestCase):
    def test_default_schedule_is_always_open(self):
        self.assertTrue(runner._persona_window_open({}))

    def test_nightly_window_that_never_matches_closes_personas(self):
        cfg = {"personas": {"schedule": {"mode": "nightly", "start_hour": 0, "end_hour": 0}}}
        self.assertFalse(runner._persona_window_open(cfg))

    def test_nightly_window_covering_the_day_is_open(self):
        cfg = {"personas": {"schedule": {"mode": "nightly", "start_hour": 0, "end_hour": 24}}}
        self.assertTrue(runner._persona_window_open(cfg))


class TestConvergenceGuardInEvalGate(unittest.TestCase):
    """Drive runner._eval_gate with the judge scores scripted and everything external stubbed."""

    def _run_gate(self, scores: list[_result], cfg: dict):
        job = runner.Job("persona", "quality", "quality", "")
        evaluate = mock.Mock(side_effect=scores)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(runner, "clean_build_artifacts"), \
                mock.patch.object(runner, "run", return_value=mock.Mock(stdout="diff")), \
                mock.patch.object(runner, "diff_stats", return_value=(1, ["a.py"])), \
                mock.patch.object(runner, "task_description_for_job", return_value="task"), \
                mock.patch.object(runner, "_evaluate_guarded", evaluate), \
                mock.patch.object(runner, "_escalate_fast_if_over_budget", side_effect=lambda r, m, *a, **k: (r, m)), \
                mock.patch.object(runner, "call_agent", return_value={}), \
                mock.patch.object(runner, "run_steps", return_value=(True, "")), \
                mock.patch.object(runner, "append_history"), \
                mock.patch.object(runner.loop_helpers, "is_bugfix", return_value=False):
            outcome = runner._eval_gate(
                job, cfg, Path(d), {}, [], "", {"engine": "coder"}, Path(d) / "r.json", "base",
                {"working": "w", "failed": "f", "pr": "p"}, "owner/repo", True, None)
        return outcome, evaluate.call_count

    def test_stops_refining_when_score_does_not_improve(self):
        cfg = {"evaluation": {"enabled": True, "max_eval_refinements": 2}}
        outcome, calls = self._run_gate([_result(0.6, False), _result(0.5, False), _result(0.95, True)], cfg)
        self.assertEqual(calls, 2)  # initial judge + one refinement, then the plateau stops the loop
        self.assertIsNotNone(outcome)  # still not passed, so the PR stays blocked

    def test_keeps_refining_while_scores_improve(self):
        cfg = {"evaluation": {"enabled": True, "max_eval_refinements": 2}}
        outcome, calls = self._run_gate([_result(0.6, False), _result(0.7, False), _result(0.95, True)], cfg)
        self.assertEqual(calls, 3)
        self.assertIsNone(outcome)

    def test_plateau_stop_can_be_switched_off(self):
        cfg = {"evaluation": {"enabled": True, "max_eval_refinements": 2, "plateau_stop": False}}
        outcome, calls = self._run_gate([_result(0.6, False), _result(0.5, False), _result(0.95, True)], cfg)
        self.assertEqual(calls, 3)
        self.assertIsNone(outcome)


class TestBugCheckWindowCoversLateCitedLines(unittest.TestCase):
    """O25 regression: a 3,244-line index.html cited at line 899 must reach the judge."""

    def test_cited_line_past_406_is_in_the_block(self):
        lines = [f'<div id="l{i}"></div>' for i in range(1, 3245)]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "index.html").write_text("\n".join(lines), encoding="utf-8")
            block = quality_gates.read_files_block(Path(d), ["index.html"], focus="index.html:899 ปุ่มลบไม่ทำงาน")
        self.assertIn('899: <div id="l899"></div>', block)
        self.assertIn("[ข้าม บรรทัด 1–838]", block)

    def test_file_without_citation_is_sent_whole_within_limit(self):
        lines = [f'<div id="l{i}"></div>' for i in range(1, 3245)]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "index.html").write_text("\n".join(lines), encoding="utf-8")
            block = quality_gates.read_files_block(Path(d), ["index.html"])
        self.assertIn("3244: ", block)
        self.assertNotIn("[ตัดทอน", block)


if __name__ == "__main__":
    unittest.main()

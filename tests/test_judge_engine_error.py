"""BUG-6 eval side: a judge that never ran is an engine error, not a quality verdict."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from auto_dev_crew import runner
from auto_dev_crew.evaluator import EvaluationResult, evaluate_diff
from auto_dev_crew.runner import EngineBusy, Job


def _cfg() -> dict:
    return {
        "evaluation": {"enabled": True, "min_pass_score": 0.75},
        "engines": [{"name": "judge", "command": "opencode", "model": "m", "enabled": True}],
    }


def test_judge_engine_busy_marks_engine_error(tmp_path):
    def busy_agent(*_a, **_k):
        raise EngineBusy("Engine judge กำลังถูกใช้งานโดย Slot อื่น")

    res = evaluate_diff("diff", "task", "out", _cfg(), tmp_path, call_agent=busy_agent)
    assert res.passed is False
    assert res.engine_error is True


def test_real_low_score_is_not_engine_error(tmp_path):
    low = {"status": "SUCCESS", "response": '{"task_alignment": 0.2, "safety_cleanliness": 0.2, "quality": 0.2, "critique_th": "แย่"}'}
    res = evaluate_diff("diff", "task", "out", _cfg(), tmp_path, call_agent=lambda *a, **k: low)
    assert res.passed is False
    assert res.engine_error is False


def test_fix_loop_does_not_refine_on_judge_engine_error(monkeypatch, tmp_path):
    busy_res = EvaluationResult(score=0.0, passed=False, critique_th="การประเมินขัดข้อง",
                                dimensions={}, engine_error=True)
    monkeypatch.setattr(runner, "_evaluate_guarded", lambda *a, **k: busy_res)
    monkeypatch.setattr(runner, "clean_build_artifacts", lambda cwd: None)
    monkeypatch.setattr(runner, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))
    coder = mock.Mock(return_value={"status": "SUCCESS"})
    monkeypatch.setattr(runner, "call_agent", coder)
    job = Job("issue", "6", "title", "body")
    cfg = {"evaluation": {"enabled": True, "max_eval_refinements": 2}, "labels": {"working": "w", "failed": "f"}}
    with pytest.raises(EngineBusy):
        runner._eval_gate(job, cfg, Path(tmp_path), {}, [], "", {}, tmp_path / "r.json", "base",
                          cfg["labels"], "o/r", False, None)
    coder.assert_not_called()

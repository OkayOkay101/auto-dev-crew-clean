"""Tests verifying judge timeout and fallback non-auto-merge behavior (decision item 4)."""

from pathlib import Path
from unittest.mock import patch

from auto_dev_crew.evaluator import evaluate_diff


def _two_engine_cfg():
    return {
        "evaluation": {"enabled": True, "engine": "judge-eng", "min_pass_score": 0.75},
        "engines": [
            {"name": "default-coder", "command": "opencode", "model": "m1", "enabled": True},
            {"name": "judge-eng", "command": "opencode", "model": "m2", "enabled": True},
        ],
    }


def test_primary_judge_timeout_error_status_marks_judge_fallback():
    cfg = _two_engine_cfg()
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.side_effect = [
            {"status": "ERROR", "response": "agent timed out after 180s"},
            {
                "status": "SUCCESS",
                "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่านจาก fallback"}',
            },
        ]
        res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
    assert res.passed is True
    assert res.judge_fallback is True
    assert mock_agent.call_count == 2


def test_primary_judge_timeout_exception_marks_judge_fallback():
    cfg = _two_engine_cfg()
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.side_effect = [
            RuntimeError("agent timed out after 300.0s"),
            {
                "status": "SUCCESS",
                "response": '{"task_alignment": 0.9, "safety_cleanliness": 0.9, "quality": 0.9, "critique_th": "ผ่านจาก fallback"}',
            },
        ]
        res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
    assert res.passed is True
    assert res.judge_fallback is True
    assert mock_agent.call_count == 2


def test_both_primary_and_fallback_timeout_blocks_eval():
    cfg = _two_engine_cfg()
    with patch("auto_dev_crew.runner.call_agent") as mock_agent:
        mock_agent.side_effect = [
            RuntimeError("agent timed out after 300.0s"),
            RuntimeError("fallback timed out after 300.0s"),
        ]
        res = evaluate_diff("diff", "task", "test output", cfg, Path("."))
    assert res.passed is False
    assert res.score == 0.0
    assert mock_agent.call_count == 2

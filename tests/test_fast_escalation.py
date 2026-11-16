"""F-8: a fast-path diff that blows the Hard Gate budget is re-triaged as heavy, not squeezed."""
import subprocess
from pathlib import Path

from auto_dev_crew import runner
from auto_dev_crew.evaluator import EvaluationResult

GATE = "⛔ Hard Gate FAILED: diff เกินงบ"


def _res(passed, critique):
    return EvaluationResult(score=1.0 if passed else 0.2, passed=passed, critique_th=critique,
                            dimensions={"task_alignment": 1.0, "safety_cleanliness": 1.0, "quality": 1.0})


def _setup(monkeypatch, results):
    modes, agent_calls = [], []

    def fake_eval(diff_text, task_desc, test_out, cfg, cwd, slot_id=None, mode="auto", exclude_engine=None):
        modes.append(mode)
        return results.pop(0)

    monkeypatch.setattr(runner, "_evaluate_guarded", fake_eval)
    monkeypatch.setattr(runner, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(runner, "clean_build_artifacts", lambda cwd: None)
    monkeypatch.setattr(runner, "call_agent", lambda *a, **k: agent_calls.append(a))
    monkeypatch.setattr(runner, "run_steps", lambda *a, **k: (True, ""))
    monkeypatch.setattr(runner, "append_history", lambda e: None)
    monkeypatch.setattr(runner, "gh", lambda *a, **k: None)
    return modes, agent_calls


def _gate(mode, entry):
    job = runner.Job(kind="persona", key="p", title="t", body="b")
    return runner._eval_gate(job, {"evaluation": {"enabled": True}}, Path("."), {}, [], "", entry,
                             Path("r.json"), "base", {"working": "w", "failed": "f"}, "o/r", True,
                             None, mode=mode)


def test_fast_hard_gate_escalates_to_heavy(monkeypatch):
    modes, agent_calls = _setup(monkeypatch, [_res(False, GATE), _res(True, "ok")])
    entry = {}
    assert _gate("fast", entry) is None
    assert modes == ["fast", "heavy"]
    assert agent_calls == []
    assert entry["triage_path"] == "heavy"
    assert entry["triage_escalated"] is True


def test_fast_non_gate_failure_still_refines(monkeypatch):
    modes, agent_calls = _setup(monkeypatch, [_res(False, "quality low"), _res(True, "ok")])
    entry = {}
    assert _gate("fast", entry) is None
    assert modes == ["fast", "fast"]
    assert len(agent_calls) == 1
    assert "triage_escalated" not in entry


def test_heavy_mode_unchanged(monkeypatch):
    modes, agent_calls = _setup(monkeypatch, [_res(False, GATE), _res(True, "ok")])
    entry = {}
    _gate("heavy", entry)
    assert "triage_escalated" not in entry
    assert modes == ["heavy", "heavy"]
    assert len(agent_calls) == 1


def test_escalated_refinement_prompt_drops_fast_prefix(monkeypatch):
    modes, agent_calls = _setup(monkeypatch, [_res(False, GATE), _res(False, "quality low"), _res(True, "ok")])
    entry = {}
    job = runner.Job(kind="persona", key="p", title="t", body="b")
    runner._eval_gate(job, {"evaluation": {"enabled": True}}, Path("."), {}, [], "", entry,
                      Path("r.json"), runner.FAST_PATH_PREFIX + "base", {"working": "w", "failed": "f"},
                      "o/r", True, None, mode="fast")
    assert modes == ["fast", "heavy", "heavy"]
    assert len(agent_calls) == 1
    ref_prompt = agent_calls[0][1]
    assert "FAST-PATH" not in ref_prompt
    assert ref_prompt.startswith("base")

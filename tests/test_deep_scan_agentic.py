"""Phase 1: agentic deep scan, shared call budget, and the GUI passing the repo clone as cwd."""
import json
import subprocess
from pathlib import Path

import pytest

from auto_dev_crew import gui, multi_repo, runner
from auto_dev_crew.deep_scan import (
    BudgetExhausted,
    CallBudget,
    build_agentic_scan_prompt,
    call_budget_limit,
    run_deep_scan,
    scan_mode,
)


class _Done:
    returncode = 0
    stdout = ""
    stderr = ""


def _env(tmp_path, monkeypatch, files):
    root = tmp_path / "repo"
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: root)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    return root, tmp_path / "state"


def _item(path="a.py", line=1):
    return {"category": "bug", "title": "t", "path": path, "line": line,
            "evidence": "x", "suggested_fix": "f"}


# ---- prompt ---------------------------------------------------------------

def test_agentic_prompt_lists_files_but_not_their_text():
    prompt = build_agentic_scan_prompt("lib", ["lib/util.py"], 7)
    assert "'lib'" in prompt and "- lib/util.py" in prompt
    assert "max_findings: 7" in prompt
    assert "read tool" in prompt and "glob" in prompt
    assert "y = 2" not in prompt  # the agent reads the file itself; no inline text


def test_scan_mode_defaults_to_agentic_and_rejects_garbage():
    assert scan_mode({}) == "agentic"
    assert scan_mode({"deep_scan": {"mode": "inline"}}) == "inline"
    assert scan_mode({"deep_scan": {"mode": "whatever"}}) == "agentic"


# ---- budget ---------------------------------------------------------------

def test_call_budget_refuses_after_limit():
    budget = CallBudget(2)
    guarded = budget.wrap(lambda p: "ok")
    assert guarded("a") == "ok" and guarded("b") == "ok"
    with pytest.raises(BudgetExhausted):
        guarded("c")
    assert budget.used == 2


def test_call_budget_limit_from_config_and_bad_values():
    assert call_budget_limit({}) == 300
    assert call_budget_limit({"deep_scan": {"max_calls_per_run": 5}}) == 5
    assert call_budget_limit({"deep_scan": {"max_calls_per_run": "x"}}) == 300
    assert call_budget_limit({"deep_scan": {"max_calls_per_run": -4}}) == 0


def test_run_stops_at_budget_and_warns(tmp_path, monkeypatch):
    files = {f"d{i}/a.py": "x\n" for i in range(4)}  # four chunks = four calls without a budget
    _, state = _env(tmp_path, monkeypatch, files)
    budget = CallBudget(2)
    calls = []

    def model(prompt):
        calls.append(prompt)
        return "[]"

    res = run_deep_scan("o/r", {}, state, budget.wrap(model), run_id="r1")
    assert len(calls) == 2
    assert any("หยุดสแกน" in w and "ถึงเพดาน 2" in w for w in res["warnings"])


def test_run_uses_agentic_prompt_by_default(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "secret_line_marker = 1\n"})
    seen = []
    run_deep_scan("o/r", {}, state, lambda p: seen.append(p) or "[]", run_id="r1")
    assert "read tool" in seen[0]
    assert "secret_line_marker" not in seen[0]


def test_run_inline_mode_still_pastes_file_text(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "secret_line_marker = 1\n"})
    seen = []
    run_deep_scan("o/r", {"deep_scan": {"mode": "inline"}}, state,
                  lambda p: seen.append(p) or "[]", run_id="r1")
    assert "secret_line_marker" in seen[0]


def test_agentic_findings_still_validated(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\ny\n"})
    ghost = dict(_item(line=99), evidence="this text is not in the file")  # invented -> dropped
    raw = json.dumps([_item(), ghost])
    res = run_deep_scan("o/r", {}, state, lambda p: raw, run_id="r1")
    assert [f["line"] for f in res["findings"]] == [1]


def test_wrong_line_is_relocated_to_the_evidence_line(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\ny\nz\n"})
    raw = json.dumps([dict(_item(line=99), evidence="y")])  # claimed 99, file has 3 lines, text 'y' is on line 2
    res = run_deep_scan("o/r", {}, state, lambda p: raw, run_id="r1")
    assert [f["line"] for f in res["findings"]] == [2]


def test_model_line_kept_when_inside_file(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\ny\nx\n"})
    raw = json.dumps([dict(_item(line=3), evidence="x")])  # 'x' is on lines 1 and 3; claimed 3 is valid
    res = run_deep_scan("o/r", {}, state, lambda p: raw, run_id="r1")
    assert [f["line"] for f in res["findings"]] == [3]


# ---- GUI passes the repo clone as cwd in agentic mode --------------------

def _gui_env(tmp_path, monkeypatch, cfg_extra):
    root, _ = _env(tmp_path, monkeypatch, {"app/a.py": "x\ny\n"})
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    cwds = []

    def fake_call_agent(cfg, prompt, cwd, role=None, engine_name=None, **kw):
        cwds.append(Path(cwd))
        return {"status": "SUCCESS", "response": "[]"}

    monkeypatch.setattr(runner, "call_agent", fake_call_agent)
    # feature plans are tested separately; keep the scan-only assertions exact
    cfg = {"repos": [{"name": "o/r"}], "feature_gen": {"enabled": False}, **cfg_extra}
    return root, cwds, cfg


def test_gui_agentic_scan_runs_in_repo_clone(tmp_path, monkeypatch):
    root, cwds, cfg = _gui_env(tmp_path, monkeypatch, {})
    res = gui._api_deep_scan({"repo": "o/r", "engine": "eng"}, cfg)
    assert cwds and all(c == root for c in cwds)
    assert res["calls_used"] == len(cwds)


def test_gui_inline_scan_uses_temp_dir(tmp_path, monkeypatch):
    root, cwds, cfg = _gui_env(tmp_path, monkeypatch, {"deep_scan": {"mode": "inline"}})
    gui._api_deep_scan({"repo": "o/r", "engine": "eng"}, cfg)
    assert cwds and all(c != root for c in cwds)


def test_gui_budget_is_shared_with_verify(tmp_path, monkeypatch):
    root, cwds, cfg = _gui_env(tmp_path, monkeypatch, {"deep_scan": {"max_calls_per_run": 1}})
    res = gui._api_deep_scan({"repo": "o/r", "engine": "eng"}, cfg)
    assert res["calls_used"] == 1
    assert len(cwds) == 1


@pytest.mark.real_feature_cycle
def test_feature_cycle_runs_in_repo_clone_and_files_plans(tmp_path, monkeypatch):
    root, _ = _env(tmp_path, monkeypatch, {"app/a.py": "x\ny\n"})
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    seen = []
    proposal = json.dumps([{"title": "Dark mode", "why": "eyes", "plan": ["add toggle"],
                            "files": ["app/theme.py"], "tests": "t"}])

    def fake_call_agent(cfg, prompt, cwd, role=None, engine_name=None, **kw):
        seen.append((Path(cwd), "propose new features" in prompt))
        return {"status": "SUCCESS", "response": proposal if "propose new features" in prompt else "[]"}

    gh_calls = []

    def fake_gh(*args, **kw):
        gh_calls.append(args)
        return "https://github.com/o/r/issues/9" if args[:2] == ("issue", "create") else ""

    monkeypatch.setattr(runner, "call_agent", fake_call_agent)
    monkeypatch.setattr(runner, "gh", fake_gh)
    cfg = {"repos": [{"name": "o/r", "feature_gen": {"enabled": True}}], "deep_scan": {"mode": "inline"}}
    res = gui._api_deep_scan({"repo": "o/r", "engine": "eng"}, cfg)
    proposal_calls = [cwd for cwd, is_prop in seen if is_prop]
    assert proposal_calls == [root]  # proposals read the repo clone even in inline scan mode
    assert res["feature_plans"]["ran"] is True and res["feature_plans"]["created"] == 1
    created = [a for a in gh_calls if a[:2] == ("issue", "create")]
    assert created and "ai-plan" in created[0]
    assert res["calls_used"] == len(seen)

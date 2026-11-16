from pathlib import Path
from unittest.mock import MagicMock

from auto_dev_crew import runner


def _opencode_env(monkeypatch, tmp_path: Path, role):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "engine_cmd", lambda eng: ["opencode", "run"])
    mock = MagicMock(return_value={"status": "SUCCESS", "response": "ok"})
    monkeypatch.setattr(runner, "run_opencode_stream", mock)
    eng = {"name": "opencode-x", "provider": "x", "command": "opencode", "model": "m"}
    runner.call_single_engine(eng, "prompt", tmp_path, role=role)
    return mock.call_args.kwargs["env"]


def test_scan_role_opencode_gets_readonly_config(monkeypatch, tmp_path):
    env = _opencode_env(monkeypatch, tmp_path, role="scan")
    assert "OPENCODE_CONFIG_CONTENT" in env
    assert '"bash": "deny"' in env["OPENCODE_CONFIG_CONTENT"]
    assert '"edit": "deny"' in env["OPENCODE_CONFIG_CONTENT"]


def test_coder_role_opencode_is_not_restricted(monkeypatch, tmp_path):
    env = _opencode_env(monkeypatch, tmp_path, role="coder")
    assert "OPENCODE_CONFIG_CONTENT" not in env


def test_scan_role_skips_non_opencode_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "get_engines", lambda cfg: [
        {"name": "agy-x", "command": "agy", "model": "m"},
        {"name": "opencode-x", "command": "opencode", "model": "m"},
    ])
    monkeypatch.setattr(runner, "engine_skip_reason", lambda *a, **k: None)
    monkeypatch.setattr(runner, "load_engine_status", lambda: {})
    monkeypatch.setattr(runner, "load_key_status", lambda: {})
    monkeypatch.setattr(runner, "get_engine_key_entries", lambda *a, **k: [])
    seen = []

    def fake_call(eng, prompt, cwd, active_key=None, *, role=None):
        seen.append((eng["name"], role))
        return {"status": "SUCCESS", "response": "ok"}

    monkeypatch.setattr(runner, "call_single_engine", fake_call)
    runner._call_agent_pass({}, "prompt", tmp_path, None, "scan")
    assert seen == [("opencode-x", "scan")]

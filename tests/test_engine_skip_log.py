from pathlib import Path

import pytest

from auto_dev_crew import runner


def _cfg(enabled: bool):
    return {"engines": [{
        "name": "opencode-nvidia",
        "enabled": enabled,
        "command": "opencode",
        "model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
        "provider": "nvidia",
    }]}


def test_skipped_engine_logs_reason(monkeypatch):
    messages = []
    monkeypatch.setattr(runner, "log", lambda msg, slot_id=None: messages.append(msg))
    with pytest.raises(runner.QuotaExhausted):
        runner.call_agent(_cfg(enabled=False), "p", Path("."), role="coder")
    skip_lines = [m for m in messages if "ข้าม Engine opencode-nvidia" in m]
    assert len(skip_lines) == 1
    assert "ปิดใช้งานใน config" in skip_lines[0]
    assert "บทบาท: coder" in skip_lines[0]


def test_engine_skip_reason_none_when_ready(monkeypatch):
    eng = {"name": "free-engine", "enabled": True, "command": "opencode", "model": "m"}
    assert runner.engine_skip_reason(eng, status={}, key_status={}) is None
    assert runner.is_engine_ready(eng, status={}, key_status={}) is True


def _nvidia_eng():
    return {"name": "opencode-nvidia", "enabled": True, "command": "opencode",
            "model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b", "api_keys": ["${NVIDIA_API_KEY_1}"]}


def test_opencode_auth_key_falls_back_for_engine(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY_1", raising=False)
    monkeypatch.setattr(runner, "load_dotenv", lambda *a, **k: {})
    monkeypatch.setattr(runner, "get_opencode_auth_keys", lambda: {"nvidia": "auth-test-value"})
    entries = runner.get_engine_key_entries(_nvidia_eng(), env_vars={}, role=None)
    assert [val for _, val in entries] == ["auth-test-value"]


def test_env_key_takes_precedence_over_opencode_auth(monkeypatch):
    monkeypatch.setattr(runner, "get_opencode_auth_keys", lambda: {"nvidia": "auth-test-value"})
    entries = runner.get_engine_key_entries(_nvidia_eng(), env_vars={"NVIDIA_API_KEY_1": "env-test-value"}, role=None)
    assert [val for _, val in entries] == ["env-test-value"]


def test_opencode_auth_does_not_leak_to_other_providers(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY_1", raising=False)
    monkeypatch.setattr(runner, "load_dotenv", lambda *a, **k: {})
    monkeypatch.setattr(runner, "get_opencode_auth_keys", lambda: {"groq": "auth-test-value"})
    eng = {"name": "opencode-nvidia", "enabled": True, "command": "opencode",
           "model": "m", "api_keys": ["${NVIDIA_API_KEY_1}"]}
    assert runner.get_engine_key_entries(eng, env_vars={}, role=None) == []


def test_is_engine_ready_matches_skip_reason_for_disabled_engine():
    eng = {"name": "x", "enabled": False, "command": "opencode", "model": "m"}
    assert runner.engine_skip_reason(eng, status={}, key_status={}) is not None
    assert runner.is_engine_ready(eng, status={}, key_status={}) is False

from pathlib import Path

import pytest

from auto_dev_crew import runner


def _setup(monkeypatch, first_response: str, keyed: bool = False, cfg_extra: dict | None = None):
    engines = [
        {"name": "A", "command": "a", "model": "m"},
        {"name": "B", "command": "b", "model": "m"},
    ]
    monkeypatch.setattr(runner, "get_engines", lambda cfg: engines)
    monkeypatch.setattr(runner, "load_engine_status", lambda: {})
    monkeypatch.setattr(runner, "load_key_status", lambda: {})
    monkeypatch.setattr(runner, "is_engine_ready", lambda *a, **k: True)

    def fake_entries(eng, env_vars=None, role=None, allow_fallback=True):
        return [("A#1", "k1")] if keyed and eng["name"] == "A" else []

    monkeypatch.setattr(runner, "get_engine_key_entries", fake_entries)

    def fake_call(eng, prompt, cwd, active_key=None, *, role=None):
        if eng["name"] == "A":
            return {"status": "ERROR", "response": first_response}
        return {"status": "SUCCESS", "response": "ok"}

    monkeypatch.setattr(runner, "call_single_engine", fake_call)
    calls: list[tuple] = []
    monkeypatch.setattr(
        runner, "mark_engine_quota",
        lambda name, cooldown_hours=1.0, error="": calls.append((name, cooldown_hours, error)),
    )
    cfg = dict(cfg_extra or {})
    return cfg, calls


def test_timeout_cools_down_keyless_engine(monkeypatch):
    cfg, calls = _setup(monkeypatch, "agent timed out after 1800s")
    assert runner.call_agent(cfg, "p", Path("."))["engine_used"] == "B"
    assert len(calls) == 1
    assert calls[0][0] == "A"
    assert calls[0][1] == pytest.approx(20 / 60)


def test_timeout_cools_down_keyed_engine(monkeypatch):
    cfg, calls = _setup(monkeypatch, "agent timed out after 1800s", keyed=True)
    assert runner.call_agent(cfg, "p", Path("."))["engine_used"] == "B"
    assert len(calls) == 1
    assert calls[0][0] == "A"
    assert calls[0][1] == pytest.approx(20 / 60)


def test_idle_stall_counts_as_timeout(monkeypatch):
    cfg, calls = _setup(monkeypatch, "agent timed out: no output for 300s")
    runner.call_agent(cfg, "p", Path("."))
    assert [c[0] for c in calls] == ["A"]


def test_non_timeout_error_not_cooled(monkeypatch):
    cfg, calls = _setup(monkeypatch, "Model not found")
    assert runner.call_agent(cfg, "p", Path("."))["engine_used"] == "B"
    assert calls == []


def test_cooldown_disabled_by_zero(monkeypatch):
    cfg, calls = _setup(
        monkeypatch, "agent timed out after 1800s",
        cfg_extra={"engine_timeout_cooldown_minutes": 0},
    )
    runner.call_agent(cfg, "p", Path("."))
    assert calls == []


# --- engine-level cooldown must apply to engines with API keys (real is_engine_ready) ---

import time as _time


def _keyed_engine(name: str = "keyed-cooldown-engine") -> dict:
    return {"name": name, "command": "a", "model": "m", "enabled": True, "api_keys": ["literal-key-1"]}


def test_is_engine_ready_honours_engine_cooldown_for_keyed_engine():
    eng = _keyed_engine()
    cooling = {eng["name"]: {"cooldown_until": _time.time() + 1200}}
    assert runner.is_engine_ready(eng, status=cooling, key_status={}) is False


def test_is_engine_ready_keyed_engine_ready_without_cooldown():
    eng = _keyed_engine()
    assert runner.is_engine_ready(eng, status={}, key_status={}) is True


def test_keyed_engine_skipped_on_next_call_after_timeout(monkeypatch):
    eng_a = _keyed_engine("A")
    eng_b = {"name": "B", "command": "b", "model": "m", "enabled": True}
    monkeypatch.setattr(runner, "get_engines", lambda cfg: [eng_a, eng_b])
    engine_status: dict = {}
    monkeypatch.setattr(runner, "load_engine_status", lambda: dict(engine_status))
    monkeypatch.setattr(runner, "load_key_status", lambda: {})
    monkeypatch.setattr(runner, "load_dotenv", lambda: {})

    def fake_mark(name, cooldown_hours=1.0, error=""):
        engine_status[name] = {"cooldown_until": _time.time() + cooldown_hours * 3600}

    monkeypatch.setattr(runner, "mark_engine_quota", fake_mark)
    called: list[str] = []

    def fake_call(eng, prompt, cwd, active_key=None, *, role=None):
        called.append(eng["name"])
        if eng["name"] == "A":
            return {"status": "ERROR", "response": "agent timed out after 1800s"}
        return {"status": "SUCCESS", "response": "ok"}

    monkeypatch.setattr(runner, "call_single_engine", fake_call)
    assert runner.call_agent({}, "p", Path("."))["engine_used"] == "B"
    assert called == ["A", "B"]
    called.clear()
    assert runner.call_agent({}, "p", Path("."))["engine_used"] == "B"
    assert called == ["B"]


def test_no_ready_engine_message_mentions_timeout_rest(monkeypatch):
    eng = _keyed_engine("A")
    monkeypatch.setattr(runner, "get_engines", lambda cfg: [eng])
    monkeypatch.setattr(runner, "load_engine_status", lambda: {"A": {"cooldown_until": _time.time() + 1200}})
    monkeypatch.setattr(runner, "load_key_status", lambda: {})
    monkeypatch.setattr(runner, "load_dotenv", lambda: {})
    with pytest.raises(runner.QuotaExhausted, match="โควตาหมดหรือพักหลังหมดเวลา"):
        runner.call_agent({}, "p", Path("."))


def test_idle_timeout_seconds_handles_none_and_negative():
    assert runner._idle_timeout_seconds({}) == 300
    assert runner._idle_timeout_seconds({"idle_timeout_minutes": None}) == 300
    assert runner._idle_timeout_seconds({"idle_timeout_minutes": 2}) == 120
    assert runner._idle_timeout_seconds({"idle_timeout_minutes": 0}) == 0
    assert runner._idle_timeout_seconds({"idle_timeout_minutes": -3}) == 0

"""BUG-6: a busy engine is waited for, not turned into a failed job or an eval 0.00."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from auto_dev_crew import runner
from auto_dev_crew.runner import EngineBusy, call_agent


def _single_engine_cfg(max_wait_minutes: float = 15, retry_seconds: float = 30) -> dict:
    return {
        "engines": [{"name": "A", "command": "opencode", "model": "m", "enabled": True}],
        "parallel": {"busy_retry_seconds": retry_seconds, "busy_max_wait_minutes": max_wait_minutes},
    }


@pytest.fixture
def fake_sleep(monkeypatch):
    # time.sleep เป็นของโมดูล time ทั้งตัว (global) จึงบันทึกเฉพาะ sleep ของเทรดหลัก
    # เทรดพื้นหลังจากเทสต์ก่อนหน้าจะได้ sleep จริง ไม่ปนเข้าลิสต์
    import threading
    import time as _time

    sleeps: list[float] = []
    real_sleep = _time.sleep
    main_thread = threading.main_thread()

    def _sleep(seconds):
        if threading.current_thread() is main_thread:
            sleeps.append(seconds)
        else:
            real_sleep(seconds)

    monkeypatch.setattr(runner.time, "sleep", _sleep)
    return sleeps


def test_all_busy_then_free_retries_and_returns(fake_sleep):
    ok = {"status": "SUCCESS", "response": "done", "usage": {"total_tokens": 1}}
    with mock.patch.object(runner, "call_single_engine",
                           side_effect=[EngineBusy("lock"), EngineBusy("lock"), ok]):
        res = call_agent(_single_engine_cfg(), "p", Path("."))
    assert res["engine_used"] == "A"
    assert fake_sleep == [30, 30]


def test_all_busy_past_budget_raises_engine_busy(fake_sleep):
    # budget 1 min, retry 30 s -> two waits, then the third busy pass gives up
    with mock.patch.object(runner, "call_single_engine", side_effect=EngineBusy("lock")) as m:
        with pytest.raises(EngineBusy) as ctx:
            call_agent(_single_engine_cfg(max_wait_minutes=1, retry_seconds=30), "p", Path("."))
    assert not isinstance(ctx.value, RuntimeError)
    assert not isinstance(ctx.value, runner.QuotaExhausted)
    assert m.call_count == 3
    assert fake_sleep == [30, 30]


def test_busy_mixed_with_real_error_still_raises_runtime_error(fake_sleep):
    cfg = {
        "engines": [
            {"name": "A", "command": "opencode", "model": "m", "enabled": True},
            {"name": "B", "command": "opencode", "model": "m", "enabled": True},
        ],
        "parallel": {"busy_retry_seconds": 30, "busy_max_wait_minutes": 15},
    }
    side = [EngineBusy("lock"), {"status": "ERROR", "response": "boom"}]
    with mock.patch.object(runner, "call_single_engine", side_effect=side):
        with pytest.raises(RuntimeError) as ctx:
            call_agent(cfg, "p", Path("."))
    assert "ทุก Engine ล้มเหลว (ไม่ใช่โควตา)" in str(ctx.value)
    assert not isinstance(ctx.value, EngineBusy)
    assert fake_sleep == []


def test_busy_job_is_not_recorded_as_error_or_failed_label(monkeypatch):
    appended: list[dict] = []
    gh_calls: list[tuple] = []
    monkeypatch.setattr(runner, "append_history", lambda entry: appended.append(entry))
    monkeypatch.setattr(runner, "release_issue", lambda *a, **k: None)
    monkeypatch.setattr(runner, "gh", lambda *args, **kw: gh_calls.append(args))
    job = runner.Job("issue", "6", "title", "body")
    cfg = {"labels": {"failed": "ai-failed", "working": "ai-working"}}
    line = runner._handle_job_exception(EngineBusy("lock timeout"), job, cfg, "o/r", False, slot_id=1)
    assert appended == []
    assert not any("ai-failed" in " ".join(map(str, c)) for c in gh_calls)
    assert "ไม่นับเป็นความล้มเหลว" in line


def test_real_job_error_still_recorded(monkeypatch):
    appended: list[dict] = []
    monkeypatch.setattr(runner, "append_history", lambda entry: appended.append(entry))
    monkeypatch.setattr(runner, "release_issue", lambda *a, **k: None)
    monkeypatch.setattr(runner, "gh", lambda *a, **k: None)
    monkeypatch.setattr(runner, "load_history", lambda: appended)
    job = runner.Job("issue", "6", "title", "body")
    runner._handle_job_exception(RuntimeError("boom"), job, {"labels": {"failed": "f"}}, "o/r", False, slot_id=1)
    assert appended and appended[0]["state"] == "ERROR"


def test_fake_sleep_ignores_sleeps_from_background_threads(fake_sleep):
    # regression: an earlier test's background thread calling time.sleep must not leak into this list
    import threading
    import time

    stop = threading.Event()

    def _ticker():
        while not stop.is_set():
            time.sleep(0.001)

    t = threading.Thread(target=_ticker, daemon=True)
    t.start()
    try:
        time.sleep(0.05)  # ตัวจริงของเทสต์ ต้องถูกบันทึก
    finally:
        stop.set()
        t.join(timeout=2)
    assert fake_sleep == [0.05]

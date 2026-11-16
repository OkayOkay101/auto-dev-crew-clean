"""Single-concurrency engine lock + EngineBusy failover."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_dev_crew import runner
from auto_dev_crew.locks import file_lock
from auto_dev_crew.runner import (
    EngineBusy, _is_single_concurrency, call_agent, call_single_engine,
    load_engine_status, load_key_status,
)


def test_is_single_concurrency_flag_and_pollinations():
    assert _is_single_concurrency({"single_concurrency": True}) is True
    assert _is_single_concurrency({"name": "pollinations-x"}) is True
    assert _is_single_concurrency({"provider": "Pollinations"}) is True
    assert _is_single_concurrency({"name": "gemini"}) is False


@patch("auto_dev_crew.runner.call_single_engine")
def test_busy_engine_fails_over_without_cooldown(mock_call):
    cfg = {"engines": [
        {"name": "busy-eng", "command": "opencode", "model": "m", "enabled": True, "api_keys": ["k1"]},
        {"name": "ok-eng", "command": "opencode", "model": "m2", "enabled": True},
    ]}
    mock_call.side_effect = [
        EngineBusy("lock timeout"),
        {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}},
    ]
    res = call_agent(cfg, "prompt", Path("."))
    assert res["engine_used"] == "ok-eng"
    assert load_key_status() == {}
    assert load_engine_status() == {}


@patch("auto_dev_crew.runner.call_single_engine", side_effect=[EngineBusy("a"), EngineBusy("b")])
def test_all_busy_with_no_wait_budget_raises_engine_busy_not_quota(_mock):
    # BUG-6: all-busy waits up to parallel.busy_max_wait_minutes, then raises EngineBusy (not quota).
    cfg = {"engines": [
        {"name": "a", "command": "opencode", "model": "m", "enabled": True},
        {"name": "b", "command": "opencode", "model": "m", "enabled": True},
    ], "parallel": {"busy_max_wait_minutes": 0}}
    with pytest.raises(EngineBusy) as ctx:
        call_agent(cfg, "prompt", Path("."))
    assert not isinstance(ctx.value, runner.QuotaExhausted)
    assert load_engine_status() == {}


def test_lock_released_after_exception():
    eng = {"name": "poll", "command": "agy", "model": "m", "single_concurrency": True}
    with patch("auto_dev_crew.runner.engine_cmd", return_value=["fake"]), \
            patch("auto_dev_crew.runner.run", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            call_single_engine(eng, "prompt", Path("."))
    lock_path = runner.STATE / "engine_locks" / "poll.lock"
    with file_lock(lock_path, timeout=0.1):
        pass


def test_lock_timeout_becomes_engine_busy():
    eng = {"name": "poll", "command": "agy", "model": "m", "single_concurrency": True,
           "lock_timeout_seconds": 0.1}
    lock_path = runner.STATE / "engine_locks" / "poll.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    import threading
    held, release = threading.Event(), threading.Event()

    def holder():
        with file_lock(lock_path):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    try:
        with patch("auto_dev_crew.runner.engine_cmd", return_value=["fake"]), \
                patch("auto_dev_crew.runner.run") as mock_run:
            # run in another thread so the lock is not re-entrant for the holder
            result = {}

            def caller():
                try:
                    call_single_engine(eng, "prompt", Path("."))
                except Exception as exc:  # noqa: BLE001
                    result["exc"] = exc
            c = threading.Thread(target=caller)
            c.start()
            c.join(5)
            assert isinstance(result.get("exc"), EngineBusy)
            mock_run.assert_not_called()
    finally:
        release.set()
        t.join()


def test_concurrency_hint_in_output_raises_busy():
    eng = {"name": "x", "command": "agy", "model": "m"}
    out = json.dumps({"status": "ERROR", "response": "Pollinations answers 1 request at a time per IP"})
    with patch("auto_dev_crew.runner.engine_cmd", return_value=["fake"]), \
            patch("auto_dev_crew.runner.run",
                  return_value=subprocess.CompletedProcess([], 1, out, "")):
        with pytest.raises(EngineBusy):
            call_single_engine(eng, "prompt", Path("."))


def test_success_response_mentioning_hint_is_not_busy():
    eng = {"name": "x", "command": "agy", "model": "m"}
    out = json.dumps({"status": "SUCCESS", "response": "docs say: 1 request at a time"})
    with patch("auto_dev_crew.runner.engine_cmd", return_value=["fake"]), \
            patch("auto_dev_crew.runner.run",
                  return_value=subprocess.CompletedProcess([], 0, out, "")):
        data = call_single_engine(eng, "prompt", Path("."))
    assert data["status"] == "SUCCESS"


def test_all_busy_via_held_engine_locks_raises_engine_busy_end_to_end():
    """ทุก engine ที่ single_concurrency ถูกล็อกโดย Slot อื่น → call_agent ต้องโยน EngineBusy
    (ไม่ใช่ quota) และไม่เรียก engine จริง. ใช้ lock จริงผ่าน thread ที่ถือล็อกไว้ ไม่ mock call_single_engine."""
    import threading

    engines = [
        {"name": "poll-a", "command": "agy", "model": "m", "single_concurrency": True, "lock_timeout_seconds": 0.1},
        {"name": "poll-b", "command": "agy", "model": "m", "single_concurrency": True, "lock_timeout_seconds": 0.1},
    ]
    cfg = {"engines": engines, "parallel": {"busy_max_wait_minutes": 0}}
    lock_dir = runner.STATE / "engine_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    held = [threading.Event(), threading.Event()]
    release = threading.Event()

    def holder(lock_path: Path, ev: threading.Event):
        with file_lock(lock_path):
            ev.set()
            release.wait(10)

    threads = [
        threading.Thread(target=holder, args=(lock_dir / f"{e['name']}.lock", ev))
        for e, ev in zip(engines, held)
    ]
    for t in threads:
        t.start()
    try:
        for ev in held:
            assert ev.wait(5)
        with patch("auto_dev_crew.runner.engine_cmd", return_value=["fake"]), \
                patch("auto_dev_crew.runner.run") as mock_run:
            with pytest.raises(EngineBusy) as ctx:
                call_agent(cfg, "prompt", Path("."))
            assert not isinstance(ctx.value, runner.QuotaExhausted)
            mock_run.assert_not_called()
    finally:
        release.set()
        for t in threads:
            t.join(5)

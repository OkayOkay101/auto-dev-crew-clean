import datetime as dt
import json

import pytest

from auto_dev_crew import gui, runner


def _usage_rows():
    path = runner.STATE / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _reset_usage():
    path = runner.STATE / "usage.jsonl"
    if path.exists():
        path.unlink()


def _write_rows(rows):
    path = runner.STATE / "usage.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_record_usage_tags_key_id_from_context():
    _reset_usage()
    eng = {"name": "eng-ctx", "command": "opencode", "model": "m"}
    runner._call_with_usage_key("eng-ctx#K1", runner.record_usage, eng, {"status": "SUCCESS"}, False)
    assert _usage_rows()[-1]["key_id"] == "eng-ctx#K1"


def test_record_usage_without_key_has_null_key_id():
    _reset_usage()
    eng = {"name": "eng-nokey", "command": "agy", "model": "m"}
    runner.record_usage(eng, {"status": "SUCCESS"}, False)
    assert _usage_rows()[-1]["key_id"] is None


def test_key_context_is_reset_after_call():
    runner._call_with_usage_key("eng#K9", lambda: None)
    assert runner._USAGE_KEY_ID.get() is None


def test_call_agent_records_success_and_failure_per_key(monkeypatch):
    _reset_usage()
    monkeypatch.setenv("TEST_KEYOUT_1", "value-one")
    runner.save_key_status({})
    runner.save_engine_status({})
    cfg = {"engines": [{"name": "eng-outcome", "command": "opencode", "model": "m", "enabled": True,
                        "api_keys": ["${TEST_KEYOUT_1}"]}]}
    outcomes = iter(["ERROR", "SUCCESS"])

    def fake_call(eng, prompt, cwd, active_key=None, *, role=None):
        status = next(outcomes)
        runner.record_usage(eng, {"status": status}, False)
        return {"status": status, "response": "ok"}

    monkeypatch.setattr(runner, "call_single_engine", fake_call)
    # First run ends in ERROR: call_agent moves on to the next engine (none here), so it raises.
    with pytest.raises(RuntimeError):
        runner.call_agent(cfg, "prompt", runner.ROOT, role="coder")
    runner.call_agent(cfg, "prompt", runner.ROOT, role="coder")
    rows = [r for r in _usage_rows() if r.get("engine_name") == "eng-outcome"]
    assert [(r["key_id"], r["status"]) for r in rows] == [
        ("eng-outcome#TEST_KEYOUT_1", "ERROR"),
        ("eng-outcome#TEST_KEYOUT_1", "SUCCESS"),
    ]


def test_usage_summary_counts_success_and_failed_per_key():
    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    _write_rows([
        {"ts": f"{today}T10:00:00", "engine_name": "e", "key_id": "e#K1", "status": "SUCCESS"},
        {"ts": f"{today}T10:05:00", "engine_name": "e", "key_id": "e#K1", "status": "ERROR"},
        {"ts": f"{yesterday}T10:00:00", "engine_name": "e", "key_id": "e#K1", "status": "QUOTA"},
        {"ts": f"{today}T11:00:00", "engine_name": "e", "key_id": "e#K2", "status": "SUCCESS"},
        {"ts": f"{today}T11:30:00", "engine_name": "e", "status": "SUCCESS"},
    ])
    cfg = {"engines": [{"name": "e", "command": "opencode", "model": "m", "enabled": True}]}
    keys = {k["key_id"]: k for k in gui.usage_summary(cfg)["keys"]}
    assert keys["e#K1"] == {"key_id": "e#K1", "engine_name": "e", "success": 1, "failed": 2, "quota": 1,
                            "today_success": 1, "today_failed": 1}
    assert keys["e#K2"]["success"] == 1 and keys["e#K2"]["failed"] == 0
    assert len(keys) == 2  # the row without key_id is not counted

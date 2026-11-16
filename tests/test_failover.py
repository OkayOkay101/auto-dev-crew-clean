import datetime as dt
import json
from unittest import mock

from auto_dev_crew import runner


def _row(engine_name, tokens, ts=None):
    return json.dumps({
        "ts": ts or dt.datetime.now().isoformat(timespec="seconds"),
        "engine_name": engine_name,
        "tokens": tokens,
        "status": "SUCCESS",
    })


def _write_usage(lines):
    (runner.STATE / "usage.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_today_usage_counts_only_this_engine_and_today():
    yesterday = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    _write_usage([
        _row("groq", 100),
        _row("groq", 50),
        _row("groq", 999, ts=yesterday),
        _row("nvidia", 700),
        "not json",
    ])
    assert runner.today_usage("groq") == (2, 150)
    assert runner.today_usage("nvidia") == (1, 700)
    assert runner.today_usage("missing") == (0, 0)


def test_today_usage_without_file_is_zero():
    assert runner.today_usage("groq") == (0, 0)


def test_near_limit_triggers_at_80_percent_of_requests():
    _write_usage([_row("groq", 1)] * 8)
    assert runner.near_daily_limit({"name": "groq", "daily_request_limit": 10})
    assert not runner.near_daily_limit({"name": "groq", "daily_request_limit": 11})


def test_near_limit_triggers_at_80_percent_of_tokens():
    _write_usage([_row("groq", 800)])
    assert runner.near_daily_limit({"name": "groq", "daily_token_limit": 1000})
    assert not runner.near_daily_limit({"name": "groq", "daily_token_limit": 1001})


def test_no_limit_configured_never_near():
    _write_usage([_row("groq", 10**9)] * 5)
    assert not runner.near_daily_limit({"name": "groq"})


def test_engine_near_limit_is_not_ready():
    _write_usage([_row("groq", 1)] * 9)
    eng = {"name": "groq", "enabled": True, "daily_request_limit": 10}
    assert not runner.is_engine_ready(eng, status={}, key_status={})


def test_engine_below_limit_is_ready():
    _write_usage([_row("groq", 1)] * 2)
    eng = {"name": "groq", "enabled": True, "daily_request_limit": 10}
    assert runner.is_engine_ready(eng, status={}, key_status={})


def test_handoff_prompt_carries_partial_output():
    out = runner.build_handoff_prompt("ORIGINAL TASK", "half done", "groq")
    assert out.startswith("ORIGINAL TASK")
    assert "half done" in out
    assert "groq" in out


def test_handoff_prompt_unchanged_without_partial():
    assert runner.build_handoff_prompt("ORIGINAL TASK", "   ", "groq") == "ORIGINAL TASK"


def test_handoff_prompt_keeps_only_tail_of_long_output():
    out = runner.build_handoff_prompt("T", "a" * 5000 + "END", "groq")
    assert "END" in out
    assert len(out) < 4500


def test_quota_exception_keeps_partial_output():
    exc = runner.QuotaExhausted("quota", partial="work so far")
    assert str(exc) == "quota"
    assert exc.partial == "work so far"
    assert runner.QuotaExhausted("x").partial == ""


def _cfg(*engines):
    return {"engines": [
        {"name": n, "command": "opencode", "model": "m", "enabled": True, **extra}
        for n, extra in engines
    ]}


def test_call_agent_hands_off_partial_to_next_engine(tmp_path):
    cfg = _cfg(("eng-a", {}), ("eng-b", {}))
    seen = []

    def fake(eng, prompt, cwd, active_key=None):
        seen.append((eng["name"], prompt))
        if eng["name"] == "eng-a":
            raise runner.QuotaExhausted("quota", partial="half done")
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        data = runner.call_agent(cfg, "ORIGINAL TASK", tmp_path)
    assert data["engine_used"] == "eng-b"
    assert seen[0] == ("eng-a", "ORIGINAL TASK")
    assert seen[1][0] == "eng-b"
    assert seen[1][1].startswith("ORIGINAL TASK")
    assert "half done" in seen[1][1]


def test_call_agent_busy_engine_does_not_change_prompt(tmp_path):
    cfg = _cfg(("eng-a", {}), ("eng-b", {}))
    seen = []

    def fake(eng, prompt, cwd, active_key=None):
        seen.append(prompt)
        if eng["name"] == "eng-a":
            raise runner.EngineBusy("busy")
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        runner.call_agent(cfg, "ORIGINAL TASK", tmp_path)
    assert seen == ["ORIGINAL TASK", "ORIGINAL TASK"]


def test_call_agent_skips_near_limit_engine_without_cooldown(tmp_path):
    cfg = _cfg(("eng-a", {"daily_request_limit": 10}), ("eng-b", {}))
    _write_usage([_row("eng-a", 1)] * 8)
    called = []

    def fake(eng, prompt, cwd, active_key=None):
        called.append(eng["name"])
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        runner.call_agent(cfg, "T", tmp_path)
    assert called == ["eng-b"]
    assert "eng-a" not in runner.load_engine_status()

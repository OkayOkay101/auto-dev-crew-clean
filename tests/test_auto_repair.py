"""Auto-repair of ai-failed issues: a fixable failure goes back to ai-task for up to max_attempts rounds."""
from __future__ import annotations

import pytest

from auto_dev_crew import runner
from auto_dev_crew.runner import Job

LABELS = {"task": "ai-task", "working": "ai-working", "failed": "ai-failed", "needs_human": "ai-needs-human"}
JOB = Job("issue", "42", "title", "body")


@pytest.fixture
def _gh_recorder(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(runner, "gh", lambda *args, **kw: calls.append(args))
    return calls


def _history_with(*entries):
    return list(entries)


def test_settings_default_to_enabled_with_two_rounds():
    assert runner.auto_repair_settings({}) == (True, 2)
    assert runner.auto_repair_settings({"auto_repair": {"enabled": False, "max_attempts": 5}}) == (False, 5)


def test_first_test_failure_is_queued_for_repair(monkeypatch, _gh_recorder):
    monkeypatch.setattr(runner, "load_history", lambda: [])
    entry = {"kind": "issue", "key": "42", "repo": "o/r", "engine": "eng-a", "state": "FAILED"}
    runner._settle_failure(JOB, {}, "o/r", LABELS, entry, "เทสต์ไม่ผ่าน", "boom trace", False, repairable=True)

    assert entry["repair_attempt"] == 1
    assert entry["repair_feedback"]["test_out"] == "boom trace"
    flat = [" ".join(map(str, c)) for c in _gh_recorder]
    assert any("--remove-label ai-working" in c for c in flat)
    assert not any("ai-failed" in c or "ai-needs-human" in c for c in flat)


def test_exhausted_rounds_escalate_to_needs_human(monkeypatch, _gh_recorder):
    prior = [{"kind": "issue", "key": "42", "repo": "o/r", "repair_attempt": 2, "state": "FAILED"}]
    monkeypatch.setattr(runner, "load_history", lambda: prior)
    entry = {"kind": "issue", "key": "42", "repo": "o/r", "state": "FAILED"}
    runner._settle_failure(JOB, {}, "o/r", LABELS, entry, "เทสต์ไม่ผ่าน", "boom", False, repairable=True)

    assert "repair_attempt" not in entry
    flat = " ".join(" ".join(map(str, c)) for c in _gh_recorder)
    assert "ai-failed" in flat and "ai-needs-human" in flat


def test_blocked_refusal_goes_straight_to_needs_human(monkeypatch, _gh_recorder):
    monkeypatch.setattr(runner, "load_history", lambda: [])
    entry = {"kind": "issue", "key": "42", "repo": "o/r", "state": "NO_ACTION"}
    runner._settle_failure(JOB, {}, "o/r", LABELS, entry, "ถูกบล็อก", "", False, repairable=True, blocked=True)

    assert "repair_attempt" not in entry
    flat = " ".join(" ".join(map(str, c)) for c in _gh_recorder)
    assert "ai-needs-human" in flat


def test_non_repairable_failure_keeps_old_label_only(monkeypatch, _gh_recorder):
    monkeypatch.setattr(runner, "load_history", lambda: [])
    entry = {"kind": "issue", "key": "42", "repo": "o/r", "state": "FAILED"}
    runner._settle_failure(JOB, {}, "o/r", LABELS, entry, "judge ต่ำ", "", False, repairable=False)

    assert "repair_attempt" not in entry
    flat = " ".join(" ".join(map(str, c)) for c in _gh_recorder)
    assert "ai-failed" in flat and "ai-needs-human" not in flat


def test_disabled_auto_repair_keeps_old_behaviour(monkeypatch, _gh_recorder):
    monkeypatch.setattr(runner, "load_history", lambda: [])
    cfg = {"auto_repair": {"enabled": False}}
    entry = {"kind": "issue", "key": "42", "repo": "o/r", "state": "FAILED"}
    runner._settle_failure(JOB, cfg, "o/r", LABELS, entry, "เทสต์ไม่ผ่าน", "", False, repairable=True)

    assert "repair_attempt" not in entry
    flat = " ".join(" ".join(map(str, c)) for c in _gh_recorder)
    assert "ai-failed" in flat and "ai-needs-human" not in flat


def test_dry_run_and_persona_jobs_touch_nothing(monkeypatch, _gh_recorder):
    monkeypatch.setattr(runner, "load_history", lambda: [])
    entry = {"kind": "persona", "key": "bolt", "state": "FAILED"}
    runner._settle_failure(Job("persona", "bolt", "bolt", ""), {}, "o/r", LABELS, entry, "x", "", False, repairable=True)
    runner._settle_failure(JOB, {}, "o/r", LABELS, {"kind": "issue", "key": "42"}, "x", "", True, repairable=True)
    assert _gh_recorder == []


def test_repair_suffix_carries_previous_failure(monkeypatch):
    history = _history_with({
        "kind": "issue", "key": "42", "repo": "o/r", "repair_attempt": 1,
        "repair_feedback": {"reason": "เทสต์ไม่ผ่าน", "test_out": "AssertionError: x", "critique": "ขาดเคสศูนย์"},
    })
    text = runner.repair_prompt_suffix(JOB, "o/r", history, 2)
    assert "รอบซ่อมอัตโนมัติ 1/2" in text
    assert "AssertionError: x" in text
    assert "ขาดเคสศูนย์" in text
    assert runner.repair_prompt_suffix(JOB, "o/r", [], 2) == ""


def test_prefer_engine_moves_previous_engine_first():
    engines = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert [e["name"] for e in runner._prefer_engine(engines, "c")] == ["c", "a", "b"]
    assert [e["name"] for e in runner._prefer_engine(engines, "zzz")] == ["a", "b", "c"]


def test_needs_human_issues_are_not_picked_up(monkeypatch):
    issues = [
        {"number": 1, "title": "t", "body": "", "author": {"login": "owner"}, "labels": [{"name": "ai-task"}]},
        {"number": 2, "title": "t", "body": "", "author": {"login": "owner"},
         "labels": [{"name": "ai-task"}, {"name": "ai-needs-human"}]},
    ]
    monkeypatch.setattr(runner, "gh_json", lambda *a: [dict(i) for i in issues])
    cfg = {"owner": "owner", "labels": dict(LABELS)}
    assert [j.key for j in runner.get_available_issues("o/r", cfg)] == ["1"]


def test_r2_refusal_reported_as_no_action_is_detected():
    # #114: the coder refused under R2 but replied NO_ACTION, so the BLOCKED status alone missed it.
    refusal = {"status": "NO_ACTION", "summary_th": "ไม่ได้แก้ไขไฟล์ตามข้อกำหนด R2 ที่ให้หยุดเมื่อได้รับคำสั่งให้แก้ CI workflows"}
    assert runner.is_rule_refusal(refusal) is True
    assert runner.is_rule_refusal({"status": "BLOCKED", "summary_th": ""}) is True


def test_ordinary_no_action_is_not_a_refusal():
    assert runner.is_rule_refusal({"status": "NO_ACTION", "summary_th": "ไม่พบสิ่งที่ควรแก้"}) is False
    assert runner.is_rule_refusal({}) is False

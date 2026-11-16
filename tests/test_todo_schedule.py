import json

import pytest

from auto_dev_crew import runner, todo_scan

NOW = 1_000_000.0


def _cfg(minutes=None, repos=None):
    tcfg = {}
    if minutes is not None:
        tcfg["schedule_minutes"] = minutes
    if repos is not None:
        tcfg["repos"] = repos
    return {
        "todo_scan": tcfg,
        "repos": [{"name": "o/a"}, {"name": "o/off", "enabled": False}, {"name": "o/b", "enabled": True}],
    }


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, repo, cfg):
        self.calls.append(repo)
        return {"ok": True, "repo": repo, "created": []}


def test_disabled_by_default(tmp_path):
    state = tmp_path / "s.json"
    scan = Recorder()
    assert todo_scan.maybe_run_scheduled(_cfg(), state, now=NOW, scan=scan) == []
    assert todo_scan.maybe_run_scheduled(_cfg(0), state, now=NOW, scan=scan) == []
    assert scan.calls == []
    assert not state.exists()


def test_runs_when_due_and_records(tmp_path):
    state = tmp_path / "s.json"
    scan = Recorder()
    res = todo_scan.maybe_run_scheduled(_cfg(60), state, now=NOW, scan=scan)
    assert scan.calls == ["o/a", "o/b"]
    assert [r["repo"] for r in res] == ["o/a", "o/b"]
    assert json.loads(state.read_text(encoding="utf-8")) == {"o/a": NOW, "o/b": NOW}


def test_not_due_skips(tmp_path):
    state = tmp_path / "s.json"
    scan = Recorder()
    state.write_text(json.dumps({"o/a": NOW - 59 * 60}), encoding="utf-8")
    todo_scan.maybe_run_scheduled(_cfg(60, ["o/a"]), state, now=NOW, scan=scan)
    assert scan.calls == []
    state.write_text(json.dumps({"o/a": NOW - 60 * 60}), encoding="utf-8")
    todo_scan.maybe_run_scheduled(_cfg(60, ["o/a"]), state, now=NOW, scan=scan)
    assert scan.calls == ["o/a"]


def test_explicit_repo_list(tmp_path):
    scan = Recorder()
    todo_scan.maybe_run_scheduled(_cfg(60, ["o/x"]), tmp_path / "s.json", now=NOW, scan=scan)
    assert scan.calls == ["o/x"]


def test_scan_error_captured_and_recorded(tmp_path):
    state = tmp_path / "s.json"
    key = "sk-" + "a" * 40

    def boom(repo, cfg):
        raise RuntimeError("boom " + key)

    res = todo_scan.maybe_run_scheduled(_cfg(60, ["o/x"]), state, now=NOW, scan=boom)
    assert len(res) == 1 and res[0]["ok"] is False and res[0]["repo"] == "o/x"
    assert key not in res[0]["error"]
    assert json.loads(state.read_text(encoding="utf-8")) == {"o/x": NOW}


@pytest.mark.parametrize("raises", [False, True])
def test_worker_loop_calls_scheduler_only_on_slot1(monkeypatch, tmp_path, raises):
    calls = []

    def fake_sched(cfg, state_path, *a, **k):
        calls.append(state_path)
        if raises:
            raise RuntimeError("scheduler down")
        return []

    processed = []
    monkeypatch.setattr(todo_scan, "maybe_run_scheduled", fake_sched)
    monkeypatch.setattr(runner, "process_slot", lambda *a, **k: processed.append(a[0]) or False)
    monkeypatch.setattr(runner, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(runner, "STATE", tmp_path)
    for slot in (1, 2):
        runner.slot_worker_loop(slot_id=slot, cfg={"parallel": {}}, rcfg={"name": "o/r"},
                                dry_run=False, loop=False)
    assert len(calls) == 1
    assert calls[0] == tmp_path / "todo_scan_schedule.json"
    assert processed == [1, 2]


def test_worker_loop_skips_scheduler_in_dry_run(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(todo_scan, "maybe_run_scheduled", lambda *a, **k: calls.append(1) or [])
    monkeypatch.setattr(runner, "process_slot", lambda *a, **k: False)
    monkeypatch.setattr(runner, "load_history", lambda *a, **k: [])
    monkeypatch.setattr(runner, "STATE", tmp_path)
    runner.slot_worker_loop(slot_id=1, cfg={"parallel": {}}, rcfg={"name": "o/r"},
                            dry_run=True, loop=False)
    assert calls == []

"""CI failure policy: let the agent fix a failing required check before holding the PR."""
from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

from auto_dev_crew import ci_sync, runner


def _noop_lock(*a, **k):
    return contextlib.nullcontext()


def _rcfg(tmp_path: Path) -> dict:
    return {"name": "o/r", "base": "main"}


def test_try_merge_returns_retry_marker_without_labelling(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "file_lock", _noop_lock)
    monkeypatch.setattr(runner, "wait_for_required_checks", lambda *a, **k: "fail")
    monkeypatch.setattr(runner, "gh", lambda *a, **k: calls.append(a) or "")
    cfg = {"merge_mode": "auto", "ci": {"enabled": True, "required_checks": ["test"]}}
    out = runner.try_merge("o/r", 5, cfg, False, rcfg=_rcfg(tmp_path), hold_ci_failure=False)
    assert out == runner.CI_FAIL_RETRY
    assert not any("ci-failed" in " ".join(map(str, c)) for c in calls)


def test_try_merge_holds_when_retries_exhausted(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "file_lock", _noop_lock)
    monkeypatch.setattr(runner, "wait_for_required_checks", lambda *a, **k: "fail")
    monkeypatch.setattr(runner, "gh", lambda *a, **k: calls.append(a) or "")
    cfg = {"merge_mode": "auto", "ci": {"enabled": True, "required_checks": ["test"]}}
    out = runner.try_merge("o/r", 5, cfg, False, rcfg=_rcfg(tmp_path), hold_ci_failure=True)
    assert runner.HOLD_PR_MARKER in out
    assert any("ci-failed" in " ".join(map(str, c)) for c in calls)


def _patch_finish(monkeypatch, responses, fix_results):
    seen = {"hold": [], "fix": 0, "gh": []}
    it = iter(responses)

    def fake_try_merge(repo, pr, cfg, small, hold_ci_failure=True, **kw):
        seen["hold"].append(hold_ci_failure)
        r = next(it)
        return r(hold_ci_failure) if callable(r) else r

    fix_it = iter(fix_results)

    def fake_fix(*a, **k):
        seen["fix"] += 1
        return next(fix_it)

    monkeypatch.setattr(runner, "try_merge", fake_try_merge)
    monkeypatch.setattr(runner, "fix_ci_failure", fake_fix)
    monkeypatch.setattr(runner, "append_history", lambda *a, **k: None)
    monkeypatch.setattr(runner, "gh", lambda *a, **k: seen["gh"].append(a) or "")
    return seen


def _finish(tmp_path, cfg=None):
    entry = {"pr": 5, "kind": "persona", "key": "dev", "branch": "ai/b", "title": "t", "state": "PUSHED",
             "pr_title": "t", "pr_body": "b"}
    return runner.finish_pr(entry, cfg or {"labels": {"pr": "x"}, "merge_mode": "auto"},
                            {"name": "o/r", "base": "main"}, [], slot_id=None,
                            cwd=tmp_path, branch="ai/b", test_steps=["pytest -q"], env={"PATH": "x"})


def test_finish_pr_fixes_then_merges(monkeypatch, tmp_path):
    seen = _patch_finish(monkeypatch, [runner.CI_FAIL_RETRY, "merge แล้ว ✅"], [True])
    out = _finish(tmp_path)
    assert out.endswith("(merge แล้ว ✅)")
    assert seen["fix"] == 1
    assert seen["hold"] == [False, False]


def test_finish_pr_holds_after_budget_is_spent(monkeypatch, tmp_path):
    def hold_when_forced(hold):
        return runner.CI_FAIL_RETRY if not hold else f"CI ไม่ผ่าน — {runner.HOLD_PR_MARKER}"

    seen = _patch_finish(monkeypatch, [hold_when_forced] * 3, [True, True])
    out = _finish(tmp_path)
    assert runner.HOLD_PR_MARKER in out
    assert seen["fix"] == 2  # default fix_attempts = 2
    assert seen["hold"] == [False, False, True]


def test_finish_pr_holds_when_fix_fails(monkeypatch, tmp_path):
    seen = _patch_finish(monkeypatch, [runner.CI_FAIL_RETRY], [False])
    out = _finish(tmp_path)
    assert runner.HOLD_PR_MARKER in out
    assert seen["fix"] == 1
    assert any("ci-failed" in " ".join(map(str, c)) for c in seen["gh"])


def test_finish_pr_zero_budget_holds_immediately(monkeypatch, tmp_path):
    def hold_when_forced(hold):
        return runner.CI_FAIL_RETRY if not hold else f"CI ไม่ผ่าน — {runner.HOLD_PR_MARKER}"

    seen = _patch_finish(monkeypatch, [hold_when_forced], [])
    cfg = {"labels": {"pr": "x"}, "merge_mode": "auto", "ci": {"fix_attempts": 0}}
    out = _finish(tmp_path, cfg)
    assert runner.HOLD_PR_MARKER in out
    assert seen["fix"] == 0
    assert seen["hold"] == [True]


def test_wait_for_run_on_sha_finds_matching_run():
    runs = [{"headSha": "aaa", "status": "completed"}, {"headSha": "bbb", "status": "queued"}]
    orig = ci_sync._gh_json
    ci_sync._gh_json = lambda args: runs
    try:
        assert ci_sync.wait_for_run_on_sha("o/r", "b", "bbb", timeout_seconds=1, poll_interval=0) is True
    finally:
        ci_sync._gh_json = orig


def test_wait_for_run_on_sha_times_out(monkeypatch):
    monkeypatch.setattr(ci_sync, "_gh_json", lambda args: [{"headSha": "old"}])
    monkeypatch.setattr(ci_sync.time, "sleep", lambda s: None)
    assert ci_sync.wait_for_run_on_sha("o/r", "b", "new", timeout_seconds=0, poll_interval=0) is False


def test_fetch_failed_run_log_uses_newest_failed_run(monkeypatch):
    def fake_gh_json(args):
        return [{"databaseId": 11, "conclusion": "success"}, {"databaseId": 22, "conclusion": "failure"}]

    viewed = []

    def fake_run(cmd, **kw):
        viewed.append(cmd)
        return SimpleNamespace(stdout="line1\nFAILED test_x\n", stderr="", returncode=0)

    monkeypatch.setattr(ci_sync, "_gh_json", fake_gh_json)
    monkeypatch.setattr(ci_sync.subprocess, "run", fake_run)
    text = ci_sync.fetch_failed_run_log("o/r", "b")
    assert "FAILED test_x" in text
    assert viewed[0][:4] == ["gh", "run", "view", "22"]
    assert "--log-failed" in viewed[0]


def test_fetch_failed_run_log_empty_when_nothing_failed(monkeypatch):
    monkeypatch.setattr(ci_sync, "_gh_json", lambda args: [{"databaseId": 1, "conclusion": "success"}])
    assert ci_sync.fetch_failed_run_log("o/r", "b") == ""

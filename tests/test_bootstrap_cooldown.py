"""runner.check_and_bootstrap_ci: repos with CI and failed attempts must not be re-cloned on every poll."""
import datetime as dt

from auto_dev_crew import runner
from auto_dev_crew.ci_bootstrap import CiBootstrapResult

REPO = "example-owner/demo"
CFG = {"ci": {"auto_bootstrap_ci": True}, "labels": {"pr": "ai-pr"}}
RCFG = {"name": REPO, "base": "main"}


def _setup(monkeypatch, result):
    calls = []
    appended = []
    monkeypatch.setattr(runner, "open_ai_prs", lambda repo, cfg: [])
    monkeypatch.setattr(runner, "append_history", lambda e: appended.append(dict(e)))
    monkeypatch.setattr(runner, "log", lambda *a, **k: None)

    def fake_bootstrap(*a, **k):
        calls.append(1)
        return result
    monkeypatch.setattr(runner, "bootstrap_ci", fake_bootstrap)
    return calls, appended


def _ago(hours):
    return (dt.datetime.now() - dt.timedelta(hours=hours)).strftime("%Y%m%d-%H%M")


def test_skipped_repo_is_recorded_and_not_recloned(monkeypatch):
    calls, appended = _setup(monkeypatch, CiBootstrapResult("skipped", "มี workflow อยู่แล้ว"))
    history = []
    assert runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False) is False
    assert appended[-1]["state"] == "SKIPPED"
    assert runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False) is False
    assert len(calls) == 1, "second poll must not clone again within 24 h"


def test_skipped_repo_rechecked_after_24h(monkeypatch):
    calls, _ = _setup(monkeypatch, CiBootstrapResult("skipped", "มี workflow อยู่แล้ว"))
    history = [{"repo": REPO, "kind": "bootstrap", "key": "ci", "state": "SKIPPED", "date": _ago(25)}]
    runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False)
    assert len(calls) == 1


def test_failed_attempt_waits_six_hours(monkeypatch):
    calls, appended = _setup(monkeypatch, CiBootstrapResult("failed", "เครือข่ายขัดข้อง"))
    history = [{"repo": REPO, "kind": "bootstrap", "key": "ci", "state": "FAILED", "date": _ago(1)}]
    assert runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False) is False
    assert calls == []


def test_issue_fallback_counts_as_done(monkeypatch):
    calls, appended = _setup(monkeypatch, CiBootstrapResult("issue_opened", "x", url="https://github.com/o/r/issues/5"))
    history = []
    assert runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False) is True
    assert appended[-1]["state"] == "ISSUE_OPENED"
    assert runner.check_and_bootstrap_ci(REPO, RCFG, CFG, history, dry_run=False) is False
    assert len(calls) == 1

"""resume_pending must respect the per-repo merge level before the global merge_mode.

Bug: with merge_mode=review-all, resume_pending returned early for every repo, so a repo with
merge_level 3 (merge when CI passes) never reached try_merge and its open AI PRs sat forever.
Fake gh/finish_pr only; nothing is merged for real.
"""
from auto_dev_crew import runner

REPO = "o/r"


def _cfg(level, mode):
    entry = {"name": REPO}
    if level is not None:
        entry["merge_level"] = level
    return {"merge_mode": mode, "repos": [entry], "ci": {"enabled": False}, "labels": {}}


def _setup(monkeypatch, calls):
    monkeypatch.setattr(runner, "open_ai_prs", lambda repo, cfg: [{"number": 5, "title": "t", "headRefName": "ai/x"}])
    monkeypatch.setattr(runner, "gh_json", lambda *a, **k: {"state": "OPEN"})
    monkeypatch.setattr(runner, "append_history", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_report_safely", lambda *a, **k: None)

    def fake_finish(entry, cfg, rcfg, history, slot_id=None, branch=None, **kw):
        calls.append(entry["pr"])
        return "merge แล้ว"

    monkeypatch.setattr(runner, "finish_pr", fake_finish)


def test_level_3_pr_is_finished_even_when_global_mode_is_review_all(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    cfg = _cfg(3, "review-all")
    assert runner.resume_pending(cfg, cfg["repos"][0], [], slot_id=1) is True
    assert calls == [5]


def test_no_level_keeps_legacy_review_all_hold(monkeypatch):
    calls = []
    _setup(monkeypatch, calls)
    cfg = _cfg(None, "review-all")
    assert runner.resume_pending(cfg, cfg["repos"][0], [], slot_id=1) is False
    assert calls == []

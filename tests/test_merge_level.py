"""Phase 3: per-repo merge level inside try_merge. Fake gh only; nothing is merged for real."""
import json

import pytest

from auto_dev_crew import runner

REPO = "o/r"


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls = []
    state = {"files": ["src/game.py"]}

    def fake_gh(*args, **kw):
        calls.append(args)
        if args[:2] == ("pr", "view") and "files" in args:
            return json.dumps({"files": [{"path": p} for p in state["files"]]})
        if args[:2] == ("pr", "view"):
            return json.dumps({"mergeStateStatus": "CLEAN", "state": "OPEN"})
        return ""

    monkeypatch.setattr(runner, "gh", fake_gh)
    monkeypatch.setattr(runner, "MERGE_LOCK", tmp_path / "merge.lock")
    monkeypatch.setattr(runner, "repo_has_workflows", lambda *a, **k: False)
    return calls, state


def _merged(calls):
    return any(c[:3] == ("pr", "merge", "5") or (c[:2] == ("pr", "merge")) for c in calls)


def _cfg(level, mode="merge-all"):
    repo_entry = {"name": REPO}
    if level is not None:
        repo_entry["merge_level"] = level
    return {"merge_mode": mode, "repos": [repo_entry], "ci": {"enabled": False}}


def test_level_1_never_merges(env):
    calls, _ = env
    msg = runner.try_merge(REPO, 5, _cfg(1), small=False)
    assert "ระดับ 1" in msg
    assert not _merged(calls)


def test_level_2_safe_pr_merges(env):
    calls, state = env
    state["files"] = ["src/game.py"]
    runner.try_merge(REPO, 5, _cfg(2), small=False)
    assert _merged(calls)


def test_level_2_risky_pr_waits_for_human(env):
    calls, state = env
    state["files"] = ["requirements.txt", "src/game.py"]
    msg = runner.try_merge(REPO, 5, _cfg(2), small=False)
    assert "รอคนอนุมัติ" in msg
    assert not _merged(calls)


def test_level_2_unreadable_file_list_fails_closed(env):
    calls, state = env
    state["files"] = []
    msg = runner.try_merge(REPO, 5, _cfg(2), small=False)
    assert "รอคนอนุมัติ" in msg and not _merged(calls)


def test_level_3_merges_even_when_global_mode_is_review_all(env):
    calls, _ = env
    runner.try_merge(REPO, 5, _cfg(3, mode="review-all"), small=False)
    assert _merged(calls)


def test_no_level_keeps_legacy_review_all(env):
    calls, _ = env
    msg = runner.try_merge(REPO, 5, _cfg(None, mode="review-all"), small=False)
    assert msg == "รอรีวิว"
    assert not _merged(calls)


def test_no_level_keeps_legacy_merge_all(env):
    calls, _ = env
    runner.try_merge(REPO, 5, _cfg(None, mode="merge-all"), small=False)
    assert _merged(calls)

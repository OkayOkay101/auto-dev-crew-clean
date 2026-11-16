"""find_or_prepare_repo_dir ต้อง refresh cache clone จาก origin ก่อนใช้ (auto_dev_crew/multi_repo.py)
ไม่งั้นด่าน 1 / deep-scan / todo-scan อ่านโค้ดเก่าจาก cache ที่ไม่เคย fetch."""
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from auto_dev_crew import multi_repo


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    monkeypatch.setattr(multi_repo, "REPOS_CACHE_DIR", tmp_path)
    repo = tmp_path / "Owner_repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def _recorder(monkeypatch, returncode=0):
    calls = []

    def fake_run_cmd(cmd, timeout=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(multi_repo, "run_cmd", fake_run_cmd)
    return calls


def test_stale_cache_is_fetched_and_reset(cache_root, monkeypatch):
    calls = _recorder(monkeypatch)
    result = multi_repo.find_or_prepare_repo_dir("Owner/repo")
    assert result == cache_root.resolve()
    assert "fetch" in calls[0] and "origin" in calls[0]
    assert "reset" in calls[1] and "--hard" in calls[1] and "FETCH_HEAD" in calls[1]


def test_recent_fetch_is_throttled(cache_root, monkeypatch):
    fetch_head = cache_root / ".git" / "FETCH_HEAD"
    fetch_head.write_text("", encoding="utf-8")
    calls = _recorder(monkeypatch)
    multi_repo.find_or_prepare_repo_dir("Owner/repo")
    assert calls == []


def test_old_fetch_head_triggers_refresh(cache_root, monkeypatch):
    fetch_head = cache_root / ".git" / "FETCH_HEAD"
    fetch_head.write_text("", encoding="utf-8")
    old = time.time() - multi_repo.CACHE_REFRESH_SECONDS - 10
    os.utime(fetch_head, (old, old))
    calls = _recorder(monkeypatch)
    multi_repo.find_or_prepare_repo_dir("Owner/repo")
    assert len(calls) == 2


def test_failed_fetch_keeps_old_clone_usable(cache_root, monkeypatch):
    calls = _recorder(monkeypatch, returncode=1)
    result = multi_repo.find_or_prepare_repo_dir("Owner/repo")
    assert result == cache_root.resolve()
    assert len(calls) == 1  # fetch failed, so no reset is attempted


def test_timeout_is_not_fatal(cache_root, monkeypatch):
    def boom(cmd, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(multi_repo, "run_cmd", boom)
    assert multi_repo.refresh_cache_clone(cache_root, force=True) is False
    assert multi_repo.find_or_prepare_repo_dir("Owner/repo") == cache_root.resolve()

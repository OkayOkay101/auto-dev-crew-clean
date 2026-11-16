"""clean_work must remove stale clones even when git left read-only object files (Windows)."""
import os
import stat
import time
from pathlib import Path

from auto_dev_crew import runner


def _make_clone(root: Path, name: str, age_hours: float) -> Path:
    clone = root / name
    obj = clone / ".git" / "objects" / "ab" / "cdef"
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b"blob")
    os.chmod(obj, stat.S_IREAD)  # git writes loose objects read-only
    old = time.time() - age_hours * 3600
    os.utime(clone, (old, old))
    return clone


def test_stale_clone_with_readonly_objects_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "WORK", tmp_path)
    stale = _make_clone(tmp_path, "repo-old", runner.STALE_WORK_HOURS + 1)

    runner.clean_work()

    assert not stale.exists()


def test_recent_clone_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "WORK", tmp_path)
    fresh = _make_clone(tmp_path, "repo-new", 1)

    runner.clean_work()

    assert fresh.exists()


def test_force_rmtree_removes_readonly_tree(tmp_path):
    clone = _make_clone(tmp_path, "repo-x", 0)

    runner.force_rmtree(clone)

    assert not clone.exists()

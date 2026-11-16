"""atomic_write_text ต้องทนการล็อกชั่วคราวบน Windows (WinError 5) โดยลองซ้ำ (auto_dev_crew/locks.py)."""
import errno

import pytest

from auto_dev_crew import locks


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "active_slots.json"
    target.write_text("old", encoding="utf-8")
    real_replace = locks.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(errno.EACCES, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(locks.os, "replace", flaky_replace)
    monkeypatch.setattr(locks.time, "sleep", lambda s: None)
    locks.atomic_write_text(target, "new")
    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_gives_up_after_attempts(tmp_path, monkeypatch):
    target = tmp_path / "x.json"

    def always_locked(src, dst):
        raise PermissionError(errno.EACCES, "Access is denied")

    monkeypatch.setattr(locks.os, "replace", always_locked)
    monkeypatch.setattr(locks.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        locks.atomic_write_text(target, "new")
    assert not target.exists()

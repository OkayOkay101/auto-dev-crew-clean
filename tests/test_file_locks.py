import time
import pytest
from auto_dev_crew.file_locks import (
    acquire_file_locks,
    release_file_locks,
    get_active_file_locks,
    clean_expired_locks,
    normalize_file_path,
)


@pytest.fixture
def temp_lock_file(tmp_path):
    return tmp_path / "file_locks.json"


def test_normalize_file_path():
    assert normalize_file_path("./core.js") == "core.js"
    assert normalize_file_path("src/../core.js") == "core.js"
    assert normalize_file_path("src\\sub\\test.py") == "src/sub/test.py"
    assert normalize_file_path("/index.html") == "index.html"


def test_acquire_and_release_file_locks(temp_lock_file):
    repo = "example-owner/example-repo-2"
    target_files = ["core.js", "index.html"]

    ok, conflicts = acquire_file_locks(repo, slot_id=2, target_files=target_files, lock_file=temp_lock_file)
    assert ok is True
    assert conflicts == []

    active = get_active_file_locks(lock_file=temp_lock_file)
    assert repo in active
    assert "core.js" in active[repo]
    assert active[repo]["core.js"]["slot_id"] == 2
    assert "index.html" in active[repo]
    assert active[repo]["index.html"]["slot_id"] == 2

    release_file_locks(slot_id=2, repo=repo, lock_file=temp_lock_file)
    active_after = get_active_file_locks(lock_file=temp_lock_file)
    assert repo not in active_after or len(active_after[repo]) == 0


def test_acquire_conflict_detection(temp_lock_file):
    repo = "example-owner/example-repo-2"
    ok1, _ = acquire_file_locks(repo, slot_id=2, target_files=["core.js", "index.html"], lock_file=temp_lock_file)
    assert ok1 is True

    # Slot 3 tries to lock overlapping file
    ok2, conflicts = acquire_file_locks(repo, slot_id=3, target_files=["index.html", "bench.js"], lock_file=temp_lock_file)
    assert ok2 is False
    assert "index.html" in conflicts

    # Slot 3 tries to lock non-overlapping file
    ok3, conflicts3 = acquire_file_locks(repo, slot_id=3, target_files=["bench.js", "README.md"], lock_file=temp_lock_file)
    assert ok3 is True
    assert conflicts3 == []


def test_different_repos_do_not_conflict(temp_lock_file):
    repo1 = "example-owner/example-repo-2"
    repo2 = "example-owner/example-repo"

    ok1, _ = acquire_file_locks(repo1, slot_id=2, target_files=["index.html"], lock_file=temp_lock_file)
    ok2, _ = acquire_file_locks(repo2, slot_id=3, target_files=["index.html"], lock_file=temp_lock_file)

    assert ok1 is True
    assert ok2 is True


def test_expired_locks_cleaned_up(temp_lock_file):
    repo = "example-owner/example-repo-2"
    # Lock with 1 second TTL
    ok1, _ = acquire_file_locks(repo, slot_id=2, target_files=["core.js"], ttl_seconds=1, lock_file=temp_lock_file)
    assert ok1 is True

    time.sleep(1.1)

    # Slot 3 should be able to acquire because slot 2 lock expired
    ok2, conflicts = acquire_file_locks(repo, slot_id=3, target_files=["core.js"], lock_file=temp_lock_file)
    assert ok2 is True
    assert conflicts == []


def test_clean_expired_locks_helper(temp_lock_file):
    repo = "example-owner/example-repo-2"
    acquire_file_locks(repo, slot_id=2, target_files=["core.js"], ttl_seconds=1, lock_file=temp_lock_file)
    time.sleep(1.1)
    cleaned = clean_expired_locks(lock_file=temp_lock_file)
    assert cleaned >= 1
    active = get_active_file_locks(lock_file=temp_lock_file)
    assert repo not in active or "core.js" not in active[repo]

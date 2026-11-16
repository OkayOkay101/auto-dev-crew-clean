"""File-Scope Locking & Multi-Slot Concurrency Protection.

Prevents multiple parallel AI slots from concurrently modifying the same files
in the same repository, eliminating merge conflicts before coding begins.
"""
from __future__ import annotations

import posixpath
import time
from pathlib import Path
from typing import Any

from auto_dev_crew.locks import file_lock, locked_json_read, locked_json_write

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK_FILE = ROOT / "state" / "file_locks.json"
DEFAULT_TTL_SECONDS = 1800  # 30 minutes


def normalize_file_path(path_str: str) -> str:
    """Normalize file path to POSIX relative form without leading dots/slashes."""
    if not path_str:
        return ""
    # Standardize slashes
    p = path_str.replace("\\", "/").strip()
    # Normalize components (resolve . and ..)
    p = posixpath.normpath(p)
    # Strip leading / or ./
    p = p.lstrip("./").lstrip("/")
    return p


def _get_lock_file(lock_file: Path | None = None) -> Path:
    return Path(lock_file) if lock_file is not None else DEFAULT_LOCK_FILE


def clean_expired_locks(lock_file: Path | None = None) -> int:
    """Purge expired file locks. Returns count of cleaned locks."""
    target = _get_lock_file(lock_file)
    lock_mutex = target.parent / f"{target.name}.lock"
    now = time.time()
    cleaned = 0

    with file_lock(lock_mutex):
        data: dict[str, dict[str, Any]] = locked_json_read(target, default={})
        modified = False

        for repo, file_map in list(data.items()):
            for file_path, lock_info in list(file_map.items()):
                expires_at = lock_info.get("expires_at", 0)
                if now > expires_at:
                    del file_map[file_path]
                    cleaned += 1
                    modified = True
            if not file_map:
                del data[repo]
                modified = True

        if modified:
            locked_json_write(target, data)

    return cleaned


def acquire_file_locks(
    repo: str,
    slot_id: int,
    target_files: list[str],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    lock_file: Path | None = None,
) -> tuple[bool, list[str]]:
    """Attempt to acquire locks for all target files in repo for slot_id.

    Returns (True, []) if all files were locked successfully.
    Returns (False, [conflicting_files]) if one or more files are currently locked by another slot.
    """
    target = _get_lock_file(lock_file)
    lock_mutex = target.parent / f"{target.name}.lock"
    now = time.time()
    expires_at = now + ttl_seconds

    normalized_targets = [normalize_file_path(f) for f in target_files if f.strip()]
    if not normalized_targets:
        return True, []

    with file_lock(lock_mutex):
        data: dict[str, dict[str, Any]] = locked_json_read(target, default={})
        file_map = data.setdefault(repo, {})

        # Check for conflicts
        conflicts: list[str] = []
        for file_path in normalized_targets:
            existing = file_map.get(file_path)
            if existing:
                # If expired, ignore conflict
                if now > existing.get("expires_at", 0):
                    continue
                # If held by another slot, record conflict
                if existing.get("slot_id") != slot_id:
                    conflicts.append(file_path)

        if conflicts:
            return False, conflicts

        # No conflicts: acquire all files
        for file_path in normalized_targets:
            file_map[file_path] = {
                "slot_id": slot_id,
                "acquired_at": now,
                "expires_at": expires_at,
            }

        locked_json_write(target, data)
        return True, []


def release_file_locks(
    slot_id: int,
    repo: str | None = None,
    lock_file: Path | None = None,
) -> None:
    """Release all file locks held by slot_id, optionally scoped to repo."""
    target = _get_lock_file(lock_file)
    lock_mutex = target.parent / f"{target.name}.lock"

    with file_lock(lock_mutex):
        data: dict[str, dict[str, Any]] = locked_json_read(target, default={})
        modified = False

        repos_to_check = [repo] if repo else list(data.keys())
        for r in repos_to_check:
            file_map = data.get(r, {})
            for file_path, lock_info in list(file_map.items()):
                if lock_info.get("slot_id") == slot_id:
                    del file_map[file_path]
                    modified = True
            if not file_map and r in data:
                del data[r]
                modified = True

        if modified:
            locked_json_write(target, data)


def get_active_file_locks(lock_file: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return dictionary of all currently active (non-expired) file locks."""
    target = _get_lock_file(lock_file)
    now = time.time()
    data: dict[str, dict[str, Any]] = locked_json_read(target, default={})

    active: dict[str, dict[str, Any]] = {}
    for repo, file_map in data.items():
        active_files = {}
        for file_path, lock_info in file_map.items():
            if now <= lock_info.get("expires_at", 0):
                active_files[file_path] = lock_info
        if active_files:
            active[repo] = active_files

    return active

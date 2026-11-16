"""Cross-platform atomic file locking and safe JSON read/write helpers."""
from __future__ import annotations

import json
import logging
import os
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_LOCAL_STATE = threading.local()


def _get_thread_lock(key: str) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        if key not in _THREAD_LOCKS:
            _THREAD_LOCKS[key] = threading.RLock()
        return _THREAD_LOCKS[key]


class LockTimeout(TimeoutError):
    """Raised when a file lock cannot be acquired within timeout."""
    pass


@contextmanager
def file_lock(
    path: Path | str,
    timeout: float = 30.0,
    stale_seconds: float = 900.0,
    poll_interval: float = 0.05
) -> Generator[Path, None, None]:
    """Acquire a cross-platform file lock with retry, timeout, and stale lock recovery.

    Supports re-entrant acquisition in the same thread to prevent self-deadlocks.
    Uses an in-process thread lock plus OS-level file locking (msvcrt on Windows, fcntl on Unix).

    The OS lock is released automatically when the holding process dies, so lock files
    are never unlinked by age. ``stale_seconds`` is accepted for backward compatibility
    but is ignored: deleting a lock file that a slow (but live) holder still owns would
    let two holders run at once.
    """
    lock_path = Path(path).resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_key = str(lock_path)
    t_lock = _get_thread_lock(lock_key)

    if not hasattr(_LOCAL_STATE, "held_locks"):
        _LOCAL_STATE.held_locks = {}

    # If this thread already holds the file lock, support re-entrancy
    current_depth = _LOCAL_STATE.held_locks.get(lock_key, 0)
    if current_depth > 0:
        _LOCAL_STATE.held_locks[lock_key] = current_depth + 1
        try:
            yield lock_path
        finally:
            _LOCAL_STATE.held_locks[lock_key] -= 1
        return

    # 1. Acquire in-process thread lock with timeout
    acquired_thread = t_lock.acquire(timeout=timeout)
    if not acquired_thread:
        raise LockTimeout(f"Timed out acquiring in-process thread lock for {lock_path}")

    fd = None
    start_time = time.time()
    try:
        while True:
            try:
                # Open or create file for read/write
                fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
                if os.name == "nt":
                    import msvcrt
                    # Non-blocking lock on 1 byte
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Touch file to refresh mtime
                try:
                    os.utime(str(lock_path), None)
                except OSError:
                    pass
                break
            except (OSError, IOError, PermissionError):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    fd = None

                if time.time() - start_time >= timeout:
                    raise LockTimeout(f"Timed out after {timeout}s waiting for file lock: {lock_path}")
                time.sleep(poll_interval)

        _LOCAL_STATE.held_locks[lock_key] = 1
        try:
            yield lock_path
        finally:
            _LOCAL_STATE.held_locks[lock_key] = 0

    finally:
        if fd is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    try:
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                os.close(fd)
            except OSError:
                pass

        t_lock.release()


_logger = logging.getLogger(__name__)


def _quarantine_corrupt(target: Path) -> Path | None:
    """Move an unparseable JSON file aside so the next write cannot silently erase it."""
    dest = target.parent / f"{target.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000}"
    try:
        os.replace(target, dest)
        return dest
    except OSError as exc:
        _logger.error("could not quarantine corrupt JSON %s: %s", target, exc)
        return None


def locked_json_read(path: Path | str, default: Any = None) -> Any:
    """Read and parse JSON under an atomic file lock.

    A file that exists but cannot be parsed is moved to ``<name>.corrupt-<ts>`` and a
    warning is logged; the default is returned so the caller starts from a clean state
    without overwriting the damaged data.
    """
    target = Path(path)
    lock_file = target.parent / f"{target.name}.lock"
    with file_lock(lock_file):
        if not target.exists():
            return default
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            moved = _quarantine_corrupt(target)
            _logger.warning(
                "corrupt JSON in %s (%s); quarantined to %s",
                target, exc, moved if moved else "(failed)",
            )
            return default


def cfg_file_lock(path: Path | str):
    """Lock context for read-modify-write of a config-like file (e.g. config.yaml, .env).

    Uses the sibling ``<name>.lock`` file, the same convention as ``locked_json_*``.
    Re-entrant per thread, so nested helpers can take it again safely.
    """
    target = Path(path)
    return file_lock(target.parent / f"{target.name}.lock")


def _replace_with_retry(src: Path, dst: Path, attempts: int = 20, delay_s: float = 0.1) -> None:
    """os.replace บน Windows ล้มด้วย WinError 5 ถ้ามี process อื่นเปิดไฟล์ปลายทางค้างไว้ (เช่น GUI อ่านสถานะ)
    จึงลองซ้ำสั้น ๆ ก่อนยอมแพ้ ไฟล์ปลายทางยังเป็นของเดิมจนกว่าจะเขียนสำเร็จ"""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_s)


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Replace a file's content atomically: write a sibling tmp file, fsync, then os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = target.parent / f"{target.name}.tmp.{os.getpid()}_{threading.get_ident()}"
    try:
        with open(tmp_file, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp_file, target)
    finally:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass


def locked_json_write(path: Path | str, data: Any) -> None:
    """Write data as formatted JSON under an atomic file lock safely."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.parent / f"{target.name}.lock"
    with file_lock(lock_file):
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        atomic_write_text(target, payload)

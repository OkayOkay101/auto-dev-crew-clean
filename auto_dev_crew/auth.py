"""Password login for the control GUI: scrypt hashing, sessions, and a login rate limiter.

Only stdlib is used. The password itself is never stored; the file keeps a scrypt hash.
Set the password from a terminal: ``python -m auto_dev_crew.auth set-password``.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import secrets
import sys
import time
from collections.abc import Callable
from pathlib import Path

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
MIN_PASSWORD_LENGTH = 8
SESSION_TTL_SECONDS = 12 * 3600


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("password must not be empty")
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                            p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                   n=int(n), r=int(r), p=int(p), dklen=len(digest_hex) // 2)
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


class SessionStore:
    """In-memory login sessions. A server restart signs everyone out, which is acceptable here."""

    def __init__(self, ttl_seconds: float = SESSION_TTL_SECONDS, clock: Callable[[], float] = time.time) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._expires: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._expires[token] = self._clock() + self._ttl
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        expires = self._expires.get(token)
        if expires is None:
            return False
        if self._clock() >= expires:
            self._expires.pop(token, None)
            return False
        return True

    def revoke(self, token: str | None) -> None:
        if token:
            self._expires.pop(token, None)


class LoginLimiter:
    """Locks one client key after too many failed logins inside a time window."""

    def __init__(self, max_failures: int = 5, window_seconds: float = 900, lock_seconds: float = 900,
                 clock: Callable[[], float] = time.time) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._lock = lock_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> bool:
        until = self._locked_until.get(key)
        if until is None:
            return False
        if self._clock() >= until:
            self._locked_until.pop(key, None)
            self._failures.pop(key, None)
            return False
        return True

    def record_failure(self, key: str) -> None:
        now = self._clock()
        recent = [t for t in self._failures.get(key, []) if now - t < self._window]
        recent.append(now)
        self._failures[key] = recent
        if len(recent) >= self._max:
            self._locked_until[key] = now + self._lock

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


def load_password_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    stored = data.get("password_hash")
    return stored if isinstance(stored, str) and stored else None


def save_password_hash(path: Path, stored: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"password_hash": stored}, ensure_ascii=False), encoding="utf-8")


def set_password_cli(path: Path, prompt: Callable[[str], str] = getpass.getpass) -> int:
    """Ask twice (input is hidden), then store only the hash. Returns a process exit code."""
    first = prompt("รหัสผ่านใหม่: ")
    second = prompt("ยืนยันรหัสผ่านอีกครั้ง: ")
    if first != second:
        print("รหัสผ่านสองครั้งไม่ตรงกัน ยังไม่ได้บันทึก", file=sys.stderr)
        return 1
    if len(first) < MIN_PASSWORD_LENGTH:
        print(f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร", file=sys.stderr)
        return 1
    save_password_hash(path, hash_password(first))
    print(f"บันทึกรหัสผ่านแล้วที่ {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["set-password"]:
        print("ใช้งาน: python -m auto_dev_crew.auth set-password", file=sys.stderr)
        return 2
    from . import runner
    return set_password_cli(runner.STATE / "auth.json")


if __name__ == "__main__":
    raise SystemExit(main())

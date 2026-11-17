"""Auto Dev Crew — 1-Click System Doctor Pre-Flight & Opt-In Cloud Authentication Guard."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import runner
from .redact import redact_secrets

RISKY_GH_SCOPES = frozenset({"delete_repo", "admin:org", "admin:public_key", "admin:gpg_key"})
PBKDF2_ITERATIONS = 600_000


def parse_gh_scopes(status_text: str) -> list[str]:
    """Parse token scopes from `gh auth status` text without reading or storing raw credentials."""
    scopes: list[str] = []
    for line in (status_text or "").splitlines():
        if "Token scopes:" in line:
            tail = line.split("Token scopes:", 1)[1]
            for item in tail.replace("'", "").replace('"', "").split(","):
                tok = item.strip()
                if tok:
                    scopes.append(tok)
    return scopes


_GH_LOGIN_RE = re.compile(r"Logged in to \S+ (?:account|as) ([A-Za-z0-9][A-Za-z0-9-]*)")


def parse_gh_login(status_text: str) -> dict[str, Any]:
    """Read only the logged-in account name from `gh auth status` output. Never returns token text."""
    for line in (status_text or "").splitlines():
        m = _GH_LOGIN_RE.search(line)
        if m:
            return {"logged_in": True, "account": m.group(1)}
    return {"logged_in": False, "account": None}


def gh_login_status(which=shutil.which, run=subprocess.run) -> dict[str, Any]:
    """Read-only GitHub CLI login state for the GitHub setup status.

    Returns only installed / logged_in / account. The raw `gh` output is redacted and parsed here,
    so no token or other credential text can reach the caller.
    """
    gh_bin = which("gh")
    if not gh_bin:
        return {"installed": False, "logged_in": False, "account": None}
    try:
        proc = run([gh_bin, "auth", "status"], capture_output=True, text=True, timeout=8, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return {"installed": True, "logged_in": False, "account": None}
    combined = redact_secrets((proc.stdout or "") + "\n" + (proc.stderr or ""))
    parsed = parse_gh_login(combined)
    logged_in = bool(parsed["logged_in"]) and proc.returncode == 0
    return {"installed": True, "logged_in": logged_in, "account": parsed["account"] if logged_in else None}


def run_doctor_checks(root: Path | None = None, state_dir: Path | None = None) -> dict[str, Any]:
    """Run non-destructive health, environment, and security hygiene checks."""
    repo_root = root or runner.ROOT
    st_dir = state_dir or runner.STATE
    checks: list[dict[str, Any]] = []

    # 1. Python 3.12+ Runtime
    py_ok = sys.version_info >= (3, 12)
    checks.append({
        "id": "python_version",
        "ok": py_ok,
        "severity": "info" if py_ok else "error",
        "title": f"Python Runtime ({sys.version.split()[0]})",
        "detail": "Python 3.12+ active." if py_ok else "Auto Dev Crew requires Python 3.12 or newer.",
    })

    # 2. GitHub CLI & Least-Privilege Scope Audit (STATE.md O22)
    gh_bin = shutil.which("gh")
    if not gh_bin:
        checks.append({
            "id": "gh_auth_scopes",
            "ok": False,
            "severity": "error",
            "title": "GitHub CLI (gh) Not Found",
            "detail": "Install GitHub CLI and run `gh auth login`.",
        })
    else:
        try:
            proc = subprocess.run(
                [gh_bin, "auth", "status"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            combined = redact_secrets((proc.stdout or "") + "\n" + (proc.stderr or ""))
            scopes = parse_gh_scopes(combined)
            risky = sorted(set(scopes) & RISKY_GH_SCOPES)
            if risky:
                checks.append({
                    "id": "gh_auth_scopes",
                    "ok": False,
                    "severity": "warning",
                    "title": "GitHub Token Scope Advisory (O22)",
                    "detail": (
                        f"Token includes over-privileged scope(s): {', '.join(risky)}. "
                        "Run `gh auth refresh -h github.com -s repo,workflow` to drop delete_repo."
                    ),
                })
            else:
                ok_auth = proc.returncode == 0
                checks.append({
                    "id": "gh_auth_scopes",
                    "ok": ok_auth,
                    "severity": "info" if ok_auth else "error",
                    "title": "GitHub CLI Least-Privilege Check",
                    "detail": "Authenticated with least-privilege scopes." if ok_auth else "gh auth status returned non-zero.",
                })
        except subprocess.TimeoutExpired:
            checks.append({
                "id": "gh_auth_scopes",
                "ok": False,
                "severity": "warning",
                "title": "GitHub CLI Timeout",
                "detail": "`gh auth status` timed out after 8 seconds.",
            })

    # 3. Owner config.yaml Untracked Hygiene (Rubric 8.3)
    git_bin = shutil.which("git")
    cfg_tracked = False
    if git_bin and (repo_root / ".git").exists():
        res = subprocess.run(
            [git_bin, "ls-files", "--error-unmatch", "config.yaml"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        cfg_tracked = res.returncode == 0
    checks.append({
        "id": "config_untracked",
        "ok": not cfg_tracked,
        "severity": "info" if not cfg_tracked else "error",
        "title": "Personal config.yaml Commit Guard",
        "detail": "config.yaml is untracked by Git." if not cfg_tracked else "CRITICAL: config.yaml is tracked! Run `git rm --cached config.yaml`.",
    })

    # 4. File Lock Registry Integrity
    locks_path = st_dir / "file_locks.json"
    locks_ok = True
    lock_count = 0
    if locks_path.exists():
        try:
            parsed = json.loads(locks_path.read_text(encoding="utf-8") or "{}")
            if isinstance(parsed, dict):
                lock_count = len(parsed)
            else:
                locks_ok = False
        except (OSError, ValueError):
            locks_ok = False
    checks.append({
        "id": "file_locks_health",
        "ok": locks_ok,
        "severity": "info" if locks_ok else "error",
        "title": "Parallel File Lock Registry",
        "detail": f"Valid JSON ({lock_count} active file lock(s))." if locks_ok else "Corrupted state/file_locks.json detected.",
    })

    passed = sum(1 for c in checks if c["ok"])
    return {
        "ok": passed == len(checks),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }


class RemoteSessionGuard:
    """Opt-in PBKDF2-HMAC-SHA256 login + sliding-window brute-force limiter for cloud VMs."""

    def __init__(
        self,
        password_hash_hex: str,
        salt_hex: str,
        *,
        max_failures: int = 5,
        window_sec: int = 300,
    ) -> None:
        self._expected = bytes.fromhex(password_hash_hex)
        self._salt = bytes.fromhex(salt_hex)
        self._max_failures = max_failures
        self._window_sec = window_sec
        self._failures: dict[str, list[float]] = {}
        self._sessions: dict[str, float] = {}

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
        if len(password) < 12:
            raise ValueError("Remote admin password must be at least 12 characters")
        salt_bytes = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            PBKDF2_ITERATIONS,
        )
        return digest.hex(), salt_bytes.hex()

    def is_rate_limited(self, client_ip: str, now: float | None = None) -> bool:
        ts = now if now is not None else time.monotonic()
        recent = [t for t in self._failures.get(client_ip, []) if ts - t < self._window_sec]
        self._failures[client_ip] = recent
        return len(recent) >= self._max_failures

    def authenticate(self, client_ip: str, password: str, ttl_sec: int = 43_200) -> str | None:
        now = time.monotonic()
        if self.is_rate_limited(client_ip, now):
            raise PermissionError("Too many failed login attempts; IP temporarily rate-limited")
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            self._salt,
            PBKDF2_ITERATIONS,
        )
        if not hmac.compare_digest(candidate, self._expected):
            self._failures.setdefault(client_ip, []).append(now)
            return None
        self._failures.pop(client_ip, None)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + ttl_sec
        return token

    def verify_session(self, token: str | None, now: float | None = None) -> bool:
        if not token:
            return False
        ts = now if now is not None else time.monotonic()
        matched = False
        for sid, expires_at in list(self._sessions.items()):
            if ts >= expires_at:
                self._sessions.pop(sid, None)
            elif hmac.compare_digest(sid, token):
                matched = True
        return matched

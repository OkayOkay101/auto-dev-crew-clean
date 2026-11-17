"""Security hardening and bug-fix helpers for auto_dev_crew/gui.py and gui_check.py.

Remediates audit findings BG-SEC-01 through BG-BUG-05 without adding external dependencies.
"""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import hmac
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import key_ping, keys, runner
from .redact import redact_secrets

REPO_ALLOW_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
FORBIDDEN_READ_NAMES = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    "config.yaml",
    "oauth_creds.json",
    "google_accounts.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
})
FORBIDDEN_READ_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".kdbx", ".jks", ".keystore"})
FORBIDDEN_READ_PREFIXES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")


def is_forbidden_read_path(fpath: str) -> bool:
    """True when a repo-relative path names a secret, credential, or git internals (.git/config may hold tokens)."""
    parts = [p for p in re.split(r"[\\/]+", str(fpath or "")) if p not in ("", ".")]
    if not parts:
        return True
    for part in parts:
        low = part.lower()
        if low == ".git" or low in FORBIDDEN_READ_NAMES:
            return True
        if low.startswith(FORBIDDEN_READ_PREFIXES):
            return True
        if Path(low).suffix in FORBIDDEN_READ_SUFFIXES:
            return True
    return False


def require_registered_repo(repo_raw: Any, cfg: dict[str, Any]) -> str:
    """Validate owner/repo syntax (blocking leading '-' CLI flags) and verify config membership."""
    repo = str(repo_raw or "").strip()
    if not REPO_ALLOW_RE.fullmatch(repo):
        raise ValueError(_i18n.t("ชื่อ repo ไม่ถูกต้อง (ต้องอยู่ในรูปแบบ owner/repo และห้ามขึ้นต้นด้วย '-')"))
    configured = {
        r.get("name")
        for r in (cfg.get("repos") or [])
        if isinstance(r, dict) and isinstance(r.get("name"), str)
    }
    if repo not in configured:
        raise ValueError(_i18n.t("ไม่พบ repo {p0} ใน config.yaml", p0=repo))
    return repo


def verify_request_security(
    headers: Mapping[str, str],
    expected_token: str,
    *,
    require_token: bool,
) -> tuple[bool, str]:
    """Enforce Sec-Fetch-Site browser isolation and constant-time X-Token verification."""
    sec_site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if sec_site and sec_site not in ("same-origin", "none"):
        return False, "ปฏิเสธคำขอข้ามโดเมน (Sec-Fetch-Site ไม่ใช่ same-origin)"

    if require_token:
        supplied = headers.get("X-Token") or ""
        if not supplied or not hmac.compare_digest(
            supplied.encode("utf-8"),
            expected_token.encode("utf-8"),
        ):
            return False, _i18n.t("token ไม่ถูกต้อง")
    return True, ""


def resolve_safe_worktree_path(target_raw: str | Path, work_root: Path | None = None) -> Path:
    """Ensure a requested workdir or file stays strictly inside runner.WORK and blocks secret filenames."""
    base = (work_root or runner.WORK).resolve()
    candidate = Path(target_raw).resolve()
    if candidate == base or not candidate.is_relative_to(base):
        raise PermissionError(_i18n.t("path นอกพื้นที่ทำงาน"))
    for part in candidate.relative_to(base).parts:
        if part in FORBIDDEN_READ_NAMES:
            raise PermissionError(_i18n.t("ไม่อนุญาตให้อ่านไฟล์ความลับหรือไฟล์ตั้งค่าส่วนตัว"))
    if candidate.name in FORBIDDEN_READ_NAMES:
        raise PermissionError(_i18n.t("ไม่อนุญาตให้อ่านไฟล์ความลับหรือไฟล์ตั้งค่าส่วนตัว"))
    return candidate


def start_gui_without_fd_leak(
    root: Path,
    log_path: Path,
    port: int = 8765,
) -> subprocess.Popen[bytes]:
    """Spawn headless GUI for smoke checks while closing the parent's logfile descriptor cleanly."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-u",
        "-m",
        "auto_dev_crew.gui",
        "--no-browser",
        "--keep-slots",
        "--port",
        str(int(port)),
    ]
    with log_path.open("a", encoding="utf-8") as logfile:
        return subprocess.Popen(
            cmd,
            cwd=root,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )


def resolve_provider_and_key_for_models(
    provider_arg: str,
    explicit_key: str | None,
    cfg: dict[str, Any],
) -> tuple[str, str | None]:
    """Unified provider ID and stored API-key resolver for both GET and POST /api/models."""
    provider = (provider_arg or "").strip()
    if not provider:
        raise ValueError(_i18n.t("ต้องระบุชื่อ provider"))
    fetch_id = provider
    api_key = explicit_key if explicit_key else None
    eng = next((e for e in runner.get_engines(cfg) if runner.key_engine_name(e) == provider), None)
    if eng is not None:
        model_head = str(eng.get("model") or "").split("/", 1)[0]
        candidates = ["opencode-" + runner.auth_provider_for(eng), "opencode-" + model_head]
        fetch_id = next((c for c in candidates if c in keys.PROVIDER_MODEL_ENDPOINTS), candidates[0])
        if not api_key:
            specs = key_ping.list_engine_key_specs(eng)
            api_key = next((s["value"] for s in specs if s.get("value")), None)
    return fetch_id, api_key


def safe_error_payload(exc: BaseException) -> dict[str, Any]:
    """Redact any accidental token/key substrings before returning HTTP error JSON."""
    return {"ok": False, "error": redact_secrets(str(exc))}

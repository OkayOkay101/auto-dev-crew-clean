"""ลบความลับ (API key / token) ออกจากข้อความก่อน log หรือส่งขึ้น GitHub — regex + ค่าจาก os.environ ที่ชื่อเป็น KEY/TOKEN/SECRET."""
from __future__ import annotations

import os
import re

PLACEHOLDER = "[PROTECTED_SECRET]"

# ลำดับสำคัญ: pattern เฉพาะเจาะจงก่อน pattern กว้าง
_SECRET_PATTERNS = [re.compile(p) for p in (
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}",
    r"(?<![A-Za-z0-9])sk-or-v1-[A-Za-z0-9]{32,}",
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}",
    r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}",
    r"(?<![A-Za-z0-9])gsk_[A-Za-z0-9]{20,}",
    r"(?<![A-Za-z0-9])csk-[A-Za-z0-9_-]{20,}",
    r"(?<![A-Za-z0-9])sk_[A-Za-z0-9_-]{20,}",
    r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{20,}",
    r"(?<![A-Za-z0-9])nvapi-[A-Za-z0-9_-]{20,}",
    r"(?i:Bearer)\s+[A-Za-z0-9._~+/=-]{30,}",
)]


_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET)", re.I)
_MIN_ENV_SECRET_LEN = 12


def _env_secret_values() -> list[str]:
    vals = {v for k, v in os.environ.items()
            if _SECRET_NAME.search(k) and len(v) >= _MIN_ENV_SECRET_LEN and not v.startswith("${")}
    return sorted(vals, key=len, reverse=True)  # ค่ายาวก่อน กันแทนที่ไม่ครบ


def redact_secrets(text: str) -> str:
    if not text:
        return text
    for pat in _SECRET_PATTERNS:
        text = pat.sub(PLACEHOLDER, text)
    for val in _env_secret_values():
        text = text.replace(val, PLACEHOLDER)
    return text


def redact_gh_args(args) -> tuple:
    """ลบความลับจากค่าหลัง --body / -b และรูปแบบ --body=... ก่อนส่ง argv ให้ gh.
    จุดเดียวที่ใช้ร่วมกันโดย runner, multi_repo และ ci_bootstrap."""
    out = []
    for i, a in enumerate(args):
        if isinstance(a, str):
            prev = args[i - 1] if i else None
            if prev in ("--body", "-b") or a.startswith("--body="):
                a = redact_secrets(a)
        out.append(a)
    return tuple(out)

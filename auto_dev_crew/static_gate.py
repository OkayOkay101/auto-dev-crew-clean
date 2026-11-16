"""ด่านตรวจก่อนประเมิน (ระบบของเรา ไม่พึ่งการตั้งค่าบน GitHub): ความลับในบรรทัดที่เพิ่ม + ไวยากรณ์ของไฟล์ที่แก้.

ใช้แทนการตั้ง required check บน GitHub ซึ่งเจ้าของยังไม่อนุมัติ. ตรวจเฉพาะสิ่งที่ตรวจได้แน่นอนและไม่ต้องติดตั้ง
เครื่องมือเพิ่ม: รูปแบบความลับเดียวกับ redact.py และ `py_compile` / `node --check`.
โมดูลนี้ไม่เรียก AI และไม่แตะ GitHub.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .redact import redact_secrets

MAX_PROBLEMS = 10


def secret_problems(diff_text: str) -> list[str]:
    """คืนรายการปัญหาเมื่อบรรทัดที่ 'เพิ่ม' ใน diff มีรูปแบบความลับ (ไม่ดูบรรทัดที่ลบ)."""
    problems: list[str] = []
    current = "?"
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        if redact_secrets(body) != body:
            problems.append(f"พบรูปแบบความลับในบรรทัดที่เพิ่มของ {current}")
            if len(problems) >= MAX_PROBLEMS:
                break
    return problems


def _run_check(cmd: list[str], cwd: Path) -> str | None:
    """คืนข้อความ error ถ้าเครื่องมือไม่ผ่าน; None = ผ่าน."""
    try:
        res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"รันไม่ได้: {exc}"
    if res.returncode == 0:
        return None
    return (res.stderr or res.stdout or "").strip()[-300:] or f"exit {res.returncode}"


def syntax_problems(cwd: Path, files: list[str]) -> list[str]:
    """ไฟล์ .py ต้อง compile ได้ และไฟล์ .js ต้องผ่าน `node --check` (ถ้ามี node). ไฟล์ที่ถูกลบข้าม."""
    problems: list[str] = []
    node = shutil.which("node")
    for rel in files:
        path = Path(cwd) / rel
        if not path.is_file():
            continue
        err = None
        if rel.endswith(".py"):
            err = _run_check([sys.executable, "-m", "py_compile", str(path)], cwd)
        elif rel.endswith((".js", ".mjs", ".cjs")) and node:
            err = _run_check([node, "--check", str(path)], cwd)
        if err:
            problems.append(f"ไวยากรณ์ไม่ผ่าน {rel}: {err}")
            if len(problems) >= MAX_PROBLEMS:
                break
    return problems


def static_gate_problems(cwd: Path, diff_text: str, files: list[str]) -> list[str]:
    """รวมผลด่าน: คืนรายการปัญหา; ว่าง = ผ่าน."""
    return secret_problems(diff_text)[:MAX_PROBLEMS] + syntax_problems(cwd, files)[:MAX_PROBLEMS]

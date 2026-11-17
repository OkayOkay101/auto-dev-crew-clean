"""ติดตั้ง Playwright + Chromium ใน venv ของ repo ที่เปิดใช้เอง (opt-in ต่อ repo).

- ค่าเริ่มต้นไม่ติดตั้งอะไร: repo ที่ไม่ได้ตั้ง `playwright: true` (หรือ `playwright: {enabled: true}`)
  ใน config.yaml จะไม่ได้รับ Playwright เพิ่ม จึงไม่กระทบ repo ที่ไม่มี UI.
- Chromium ถูกเก็บในแคชกลางของ Playwright (ไม่ใช่ใน venv) จึงติดตั้งครั้งเดียวแล้วใช้ร่วมกันได้.
- มี marker `.playwright_ready` ใน venv กันการติดตั้งซ้ำ. venv ถูกสร้างใหม่เมื่อไหร่ marker หายไปเอง.
- ความล้มเหลวทุกกรณีแค่คืน False และลงผลผ่าน callback log เท่านั้น ไม่ raise เพื่อไม่หยุดลูป.
"""

from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

MARKER_NAME = ".playwright_ready"
INSTALL_TIMEOUT_S = 900


def detect_playwright_needed(cwd: Path | None) -> bool:
    """ตรวจจับอัตโนมัติว่า repo ใน cwd มีการใช้งาน Playwright หรือไม่."""
    if cwd is None or not isinstance(cwd, Path) or not cwd.exists():
        return False
    # ตรวจ requirements*.txt
    for req in cwd.glob("requirements*.txt"):
        try:
            if "playwright" in req.read_text(encoding="utf-8", errors="ignore").lower():
                return True
        except OSError:
            pass
    # ตรวจ package.json
    pkg = cwd / "package.json"
    if pkg.is_file():
        try:
            if "playwright" in pkg.read_text(encoding="utf-8", errors="ignore").lower():
                return True
        except OSError:
            pass
    # ตรวจ pyproject.toml
    pyproject = cwd / "pyproject.toml"
    if pyproject.is_file():
        try:
            if "playwright" in pyproject.read_text(encoding="utf-8", errors="ignore").lower():
                return True
        except OSError:
            pass
    # ตรวจไฟล์เทสต์ใน tests/
    tests_dir = cwd / "tests"
    if tests_dir.is_dir():
        for _ in tests_dir.glob("**/*playwright*.py"):
            return True
        for tfile in tests_dir.glob("**/test_*.py"):
            try:
                content = tfile.read_text(encoding="utf-8", errors="ignore")
                if "from playwright" in content or "import playwright" in content:
                    return True
            except OSError:
                pass
    return False


def is_opted_in(rcfg: dict | None) -> bool:
    """True เมื่อ repo ตั้ง playwright เป็นเปิดใช้อย่างชัดเจน (Opt-in ชัดเจนจากผู้ใช้)."""
    pw = (rcfg or {}).get("playwright")
    if pw is True:
        return True
    return isinstance(pw, dict) and pw.get("enabled") is True


def venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    # ไม่ใช้ shell: คำสั่งคงที่ ไม่มีค่าจาก config ต่อท้าย
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=INSTALL_TIMEOUT_S, check=False,
    )


def ensure_playwright(venv_path: Path, log: Callable[[str], None]) -> bool:
    """ติดตั้ง playwright (pip) และ chromium ใน venv นี้ถ้ายังไม่เคยติดตั้ง. คืน True เมื่อพร้อมใช้."""
    try:
        marker = venv_path / MARKER_NAME
        if marker.exists():
            return True
        py = venv_python(venv_path)
        if not py.exists():
            log(f"⚠️ ติดตั้ง Playwright ข้าม: ไม่พบ python ใน venv ({venv_path.name})")
            return False
        steps = [
            [str(py), "-m", "pip", "install", "--disable-pip-version-check", "playwright"],
            [str(py), "-m", "playwright", "install", "chromium"],
        ]
        for cmd in steps:
            res = _run(cmd)
            if res.returncode != 0:
                tail = (res.stderr or res.stdout or "")[-500:]
                log(f"⚠️ ติดตั้ง Playwright ไม่สำเร็จ ({' '.join(cmd[3:])}): {tail}")
                return False
        marker.write_text("ok\n", encoding="utf-8")
        log(f"✅ ติดตั้ง Playwright + Chromium ใน venv ({venv_path.name}) แล้ว")
        return True
    except Exception as exc:  # noqa: BLE001 - the loop must keep running
        log(f"⚠️ ติดตั้ง Playwright ล้มเหลวด้วยข้อผิดพลาด: {exc}")
        return False


def gui_url(rcfg: dict | None) -> str | None:
    """URL ของ GUI ของ repo (ตั้งเป็น playwright.url ใน config). None = repo นี้ไม่มี GUI ที่ตั้งไว้."""
    pw = (rcfg or {}).get("playwright")
    if isinstance(pw, dict) and isinstance(pw.get("url"), str) and pw["url"].strip():
        return pw["url"].strip()
    return None


def _open_http(url: str, timeout: float):
    """เปิด URL เฉพาะ http/https เท่านั้น — กัน scheme แปลก (file:, ftp:)"""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(_i18n.t("อนุญาตเฉพาะ http/https URL: {p0}", p0=repr(url)))
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - scheme ถูกตรวจด้านบนแล้ว


def _url_up(url: str) -> bool:
    try:
        with _open_http(url, timeout=3):
            return True
    except Exception:  # noqa: BLE001 - any failure means "not up"
        return False


def post_test_gui_check(rcfg: dict | None, name: str, log: Callable[[str], None], shot_dir: Path) -> bool | None:
    """ตรวจหน้า GUI ของ repo ด้วย Playwright หลังเทสต์ผ่าน. ผลลง log เท่านั้น ไม่หยุดลูป.

    คืน None เมื่อข้าม (ไม่ opt-in / ไม่มี GUI / เซิร์ฟเวอร์ของ repo ไม่ได้เปิด), True/False เมื่อตรวจแล้ว.
    ไม่ใช้ run_gui_check: นั่นตรวจ GUI ของ Auto Dev Crew เอง (/api/status, เปิดเองที่พอร์ต 8765)
    ซึ่งไม่ใช่ GUI ของ repo อื่น จึงใช้ gui_check.check_page กับ URL ของ repo โดยตรงและไม่เปิด server ให้."""
    try:
        if not is_opted_in(rcfg):
            return None
        url = gui_url(rcfg)
        if url is None:
            log(f"ตรวจ Playwright ข้าม ({name}): repo นี้ไม่มี GUI (ไม่ได้ตั้ง playwright.url ใน config)")
            return None
        if not _url_up(url):
            log(f"ตรวจ Playwright ข้าม ({name}): ไม่มีเซิร์ฟเวอร์ที่ {url} ลูปไม่เปิด server ให้ repo อื่น")
            return None
        from . import gui_check
        safe = "".join(c if c.isalnum() else "_" for c in name)
        shot = shot_dir / f"playwright_{safe}.png"
        problems = gui_check.check_page(url, shot)
        if problems:
            log(f"⚠️ ตรวจ Playwright ไม่ผ่าน ({name}): " + " | ".join(problems))
            return False
        log(f"✅ ตรวจ Playwright ผ่าน ({name}): หน้าโหลดไม่มี JS error, ภาพ {shot}")
        return True
    except Exception as exc:  # noqa: BLE001 - the loop must keep running
        log(f"⚠️ ตรวจ Playwright ล้มเหลวด้วยข้อผิดพลาด ({name}): {exc}")
        return False

"""ตรวจ GUI ด้วย Playwright (headless Chromium) จากลูปหลักของ runner.

ใช้ร่วมกันระหว่าง `scripts/gui_smoke.py` และ `runner.main()`:
  1. /api/status ตอบ JSON
  2. หน้าหลักโหลดได้โดยไม่มี uncaught JS error / console.error
  3. เซฟภาพหน้าจอไว้ที่ state/gui_smoke.png

การตรวจนี้อ่านอย่างเดียว ไม่กดปุ่มที่รันงาน.
ถ้า GUI ยังไม่เปิด `run_gui_check` จะเปิด GUI เองแบบ `--keep-slots` (ไม่ล้างสถานะ slot
ของ runner ที่กำลังทำงานอยู่) แล้วปิดคืนเมื่อตรวจเสร็จ ถ้าเป็น process ที่ลูปเปิดเอง.
ผลทุกอย่างลง log เท่านั้น ความล้มเหลวไม่ทำให้ลูปหยุด.
"""

from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
GUI_PORT = 8765
GUI_URL = f"http://127.0.0.1:{GUI_PORT}"
SHOT_PATH = ROOT / "state" / "gui_smoke.png"
GUI_LOG_PATH = ROOT / "state" / "gui_loop_check.log"
START_TIMEOUT_S = 30.0
PAGE_TIMEOUT_MS = 20000


def _open_http(url: str, timeout: float):
    """เปิด URL เฉพาะ http/https เท่านั้น — กัน scheme แปลก (file:, ftp:)"""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(_i18n.t("อนุญาตเฉพาะ http/https URL: {p0}", p0=repr(url)))
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - scheme ถูกตรวจด้านบนแล้ว


def check_api(base: str) -> list[str]:
    try:
        with _open_http(f"{base}/api/status", timeout=5) as r:
            json.loads(r.read().decode("utf-8"))
        return []
    except Exception as exc:  # noqa: BLE001 - report any failure as a finding
        return [f"/api/status failed: {exc}"]


def check_page(base: str, shot: Path) -> list[str]:
    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda exc: problems.append(f"uncaught JS error: {exc}"))
        page.on(
            "console",
            lambda msg: problems.append(f"console.error: {msg.text}") if msg.type == "error" else None,
        )
        try:
            page.goto(base + "/", wait_until="networkidle", timeout=PAGE_TIMEOUT_MS)
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot), full_page=True)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"page load failed: {exc}")
        finally:
            browser.close()
    return problems


def gui_is_up(base: str = GUI_URL) -> bool:
    try:
        with _open_http(f"{base}/api/status", timeout=2):
            return True
    except Exception:  # noqa: BLE001 - any failure means "not up"
        return False


def start_gui(port: int = GUI_PORT) -> subprocess.Popen:
    """เปิด GUI เป็น process ลูก แบบไม่ล้าง slot และไม่เปิดเบราว์เซอร์"""
    from . import gui_patches  # import ตอนเรียกใช้ เพื่อกัน circular import กับ runner

    return gui_patches.start_gui_without_fd_leak(ROOT, GUI_LOG_PATH, port=port)


def wait_gui_up(proc: subprocess.Popen | None, base: str = GUI_URL, timeout: float = START_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gui_is_up(base):
            return True
        if proc is not None and proc.poll() is not None:
            return False  # GUI exited before it started serving
        time.sleep(0.5)
    return False


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_gui_check(log: Callable[[str], None], base: str = GUI_URL, shot: Path = SHOT_PATH) -> bool:
    """ตรวจ GUI หนึ่งรอบ คืน True ถ้าผ่านทั้งหมด. ไม่ raise ออกมา."""
    proc: subprocess.Popen | None = None
    try:
        if gui_is_up(base):
            log("ตรวจ GUI: เปิดอยู่แล้ว ใช้ตัวเดิม")
        else:
            log("ตรวจ GUI: ยังไม่เปิด — ลูปเปิด GUI ให้ (--keep-slots)")
            proc = start_gui(int(base.rsplit(":", 1)[1]))
            if not wait_gui_up(proc, base):
                log(f"⚠️ ตรวจ GUI: เปิด GUI ไม่สำเร็จภายใน {int(START_TIMEOUT_S)} วินาที (ดู {GUI_LOG_PATH.name})")
                return False  # finally stops the process

        problems = check_api(base) + check_page(base, shot)
        if problems:
            log("⚠️ ตรวจ GUI (Playwright) ไม่ผ่าน: " + " | ".join(problems))
            return False
        log(f"✅ ตรวจ GUI (Playwright) ผ่าน: API ตอบ, หน้าโหลดไม่มี JS error, ภาพ {shot}")
        return True
    except Exception as exc:  # noqa: BLE001 - the loop must keep running
        log(f"⚠️ ตรวจ GUI (Playwright) ล้มเหลวด้วยข้อผิดพลาด: {exc}")
        return False
    finally:
        if proc is not None:
            _stop(proc)

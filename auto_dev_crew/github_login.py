"""เชื่อม GitHub จากหน้าเว็บด้วย `gh auth login --web` (device flow).

แอปไม่รับรหัสผ่านและไม่เก็บ token: gh แสดงรหัสสั้น ๆ ให้ผู้ใช้ไปกรอกที่ github.com/login/device
ผู้ใช้ยืนยันตัวตนบนเว็บ GitHub เอง แล้ว gh บันทึก token ไว้ในเครื่องตามปกติ
ข้อความจาก gh ผ่าน redact_secrets ก่อนส่งกลับหน้าเว็บทุกครั้ง
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from typing import Any, Callable

from .redact import redact_secrets

DEVICE_URL = "https://github.com/login/device"
# รหัส device ของ GitHub รูปแบบ XXXX-XXXX (ตัวพิมพ์ใหญ่และตัวเลข)
CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
LOGIN_ARGS = ["auth", "login", "--hostname", "github.com", "--web",
              "--git-protocol", "https", "--skip-ssh-key", "--scopes", "repo,workflow"]


class _Run:
    """สถานะของการล็อกอินหนึ่งครั้ง (มี gh process หนึ่งตัว)."""

    def __init__(self, proc) -> None:
        self.proc = proc
        self.code: str | None = None
        self.cancelled = False
        self.tail: list[str] = []
        self.code_found = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True)

    def _read(self) -> None:
        for raw in self.proc.stdout:
            line = redact_secrets(str(raw).rstrip())
            self.tail = (self.tail + [line])[-20:]
            if self.code is None:
                m = CODE_RE.search(line)
                if m:
                    self.code = m.group(1)
                    self.code_found.set()


class GhLoginManager:
    def __init__(self, which: Callable[[str], str | None] = shutil.which,
                 popen: Callable[..., Any] = subprocess.Popen, code_timeout: float = 15.0) -> None:
        self._which = which
        self._popen = popen
        self._code_timeout = code_timeout
        self._lock = threading.Lock()
        self._run: _Run | None = None

    def _is_running(self, run: _Run) -> bool:
        return not run.cancelled and run.proc.poll() is None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._run is not None and self._is_running(self._run) and self._run.code:
                return {"ok": True, "pending": True, "code": self._run.code, "url": DEVICE_URL,
                        "already_running": True}
            gh = self._which("gh")
            if not gh:
                return {"ok": False, "error": "ยังไม่ได้ติดตั้ง GitHub CLI (gh) ติดตั้งก่อนแล้วกดเชื่อมอีกครั้ง"}
            try:
                proc = self._popen(
                    [gh, *LOGIN_ARGS],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env={**os.environ, "GH_PROMPT_DISABLED": "1"},
                )
            except OSError as exc:
                return {"ok": False, "error": redact_secrets(f"เริ่ม gh ไม่ได้: {exc}")}
            run = _Run(proc)
            self._run = run
            run.reader.start()

        if not run.code_found.wait(self._code_timeout) or not run.code:
            self.cancel()
            return {"ok": False, "error": "ไม่ได้รับรหัสจาก gh ลองใหม่อีกครั้ง"}
        return {"ok": True, "pending": True, "code": run.code, "url": DEVICE_URL}

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            run = self._run
            if run is not None and self._is_running(run):
                run.cancelled = True
                run.proc.kill()
        return {"ok": True, "pending": False}

    def status(self) -> dict[str, Any]:
        with self._lock:
            run = self._run
        if run is None:
            return {"pending": False, "finished": False, "exit_code": None,
                    "code": None, "error": None, "url": DEVICE_URL}
        rc = run.proc.poll()
        if run.cancelled or rc is None:
            return {"pending": not run.cancelled, "finished": False, "exit_code": None,
                    "code": run.code if not run.cancelled else None, "error": None, "url": DEVICE_URL}
        # จบแล้ว: รอให้ thread อ่านบรรทัดสุดท้ายให้ครบก่อนอ่านข้อความผิดพลาด
        run.reader.join(timeout=2)
        error = None
        if rc != 0:
            error = "\n".join(run.tail[-5:])[:400] or "gh auth login ไม่สำเร็จ"
        return {"pending": False, "finished": True, "exit_code": rc,
                "code": None, "error": error, "url": DEVICE_URL}

"""End-to-end check of the GUI run button with Playwright (headless Chromium).

Usage (GUI must be running; pick a TEST repo, never a repo you care about):
    python scripts/gui_e2e.py --repo OWNER/NAME [--url http://127.0.0.1:8765] [--shot state/gui_e2e.png]

What it does:
  1. refuses to run if an agent slot is already busy (it never disturbs a running job)
  2. opens the main page, picks --repo, ticks "ทดลองรัน" (dry run: does not touch GitHub)
  3. clicks "ทำงาน 1 ครั้ง" and waits until /api/status reports agent.running = True
  4. saves a screenshot, then clicks "หยุด" and accepts that stop confirm()
     (this confirm only stops the run this script started; nothing is skipped)
  5. waits until agent.running = False

Exit code 0 = PASS, 1 = a check failed, 2 = usage or precondition error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def _open_http(target: str | urllib.request.Request, timeout: float):
    """เปิด URL เฉพาะ http/https เท่านั้น — กัน scheme แปลก (file:, ftp:)"""
    url = target.full_url if isinstance(target, urllib.request.Request) else target
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"อนุญาตเฉพาะ http/https URL: {url!r}")
    return urllib.request.urlopen(target, timeout=timeout)  # nosec B310 - scheme ถูกตรวจด้านบนแล้ว


def agent_running(base: str) -> bool:
    with _open_http(f"{base}/api/status", timeout=5) as r:
        return bool(json.loads(r.read().decode("utf-8"))["agent"]["running"])


def page_token(base: str) -> str:
    """The GUI injects a per-process X-Token into the page; read it the same way the page does."""
    import re

    html = _open_http(base + "/", timeout=5).read().decode("utf-8")
    i = html.find("TOKEN")
    m = re.search(r'["\']([A-Za-z0-9_\-]{20,})["\']', html[i:i + 200]) if i >= 0 else None
    if not m:
        raise RuntimeError("หา token ของ GUI ในหน้าไม่เจอ")
    return m.group(1)


def stop_agent_via_api(base: str) -> None:
    """Cleanup only: stop the run this script started if the browser path failed."""
    if not agent_running(base):
        return
    req = urllib.request.Request(
        base + "/api/stop",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-Token": page_token(base)},
    )
    _open_http(req, timeout=10).read()


def wait_for(predicate, timeout: float, step: float = 0.5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


def main() -> int:
    # Windows consoles may default to cp1252; the GUI labels are Thai.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="repo ที่ใช้ทดสอบ เช่น OWNER/NAME")
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--shot", default=str(ROOT / "state" / "gui_e2e.png"))
    args = ap.parse_args()

    try:
        if agent_running(args.url):
            print("SKIP  agent slot กำลังทำงานอยู่ จะไม่รัน E2E ทับ")
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  เข้าถึง /api/status ไม่ได้: {exc}")
        return 2

    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda exc: problems.append(f"uncaught JS error: {exc}"))
        page.on(
            "console",
            lambda msg: problems.append(f"console.error: {msg.text}") if msg.type == "error" else None,
        )
        # The stop button asks confirm(); accept it only for the run this script started.
        page.on("dialog", lambda d: d.accept())
        try:
            page.goto(args.url + "/", wait_until="networkidle", timeout=20000)
            page.select_option("#agentRepoSelect", args.repo)
            page.check("#dryRun")
            page.click("#runOnce")
            if not wait_for(lambda: agent_running(args.url), timeout=30):
                problems.append("agent.running ไม่เป็น True ภายใน 30 วินาทีหลังกดทำงาน")
            else:
                Path(args.shot).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=args.shot, full_page=True)
                # The stop button can sit in a hidden panel; call its own click handler directly.
                page.evaluate("document.getElementById('stopBtn').click()")
                if not wait_for(lambda: not agent_running(args.url), timeout=60):
                    problems.append("agent.running ยังเป็น True หลังกดหยุด")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"E2E step failed: {exc}")
        finally:
            browser.close()
            # Never leave a run this script started going unattended.
            try:
                # The pre-check guaranteed the slot was free, so any run seen here is this script's run.
                stop_agent_via_api(args.url)
                if not wait_for(lambda: not agent_running(args.url), timeout=30):
                    problems.append("cleanup: agent ยังทำงานอยู่")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"cleanup failed: {exc}")

    if problems:
        print("FAIL")
        for line in problems:
            print(" -", line)
        return 1
    print(f"PASS  run button starts agent (dry run on {args.repo}), stop button ends it, screenshot: {args.shot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

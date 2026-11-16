"""Watchdog for the Auto Dev Crew GUI server.

Checks http://127.0.0.1:<port>/api/status. If it does not answer, starts the GUI
again (`python -m auto_dev_crew.gui --no-browser --auto`) in a detached process.

Run once:        python scripts/gui_watchdog.py
Run forever:     python scripts/gui_watchdog.py --loop --interval 60
Manual stop:     create state/gui_watchdog.off  (watchdog then does nothing)
Log:             state/gui_watchdog.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
OFF_FLAG = STATE / "gui_watchdog.off"
LOG = STATE / "gui_watchdog.log"

# Backoff after failed starts: 1, 2, 4, ... capped at 15 minutes.
MAX_BACKOFF = 15 * 60


def log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _open_http(url: str, timeout: float):
    """Allow only http/https schemes before opening the URL."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed: {url!r}")
    return urllib.request.urlopen(url, timeout=timeout)  # nosec B310 - scheme validated above


def is_healthy(port: int, timeout: float = 5.0) -> bool:
    """True when the GUI server answers HTTP 200 on the page root.

    /api/status is deliberately not used here: it calls gh for every repo and can
    take many seconds, which made slow-but-alive servers look dead and triggered
    restarts that piled up duplicate servers on the same port.
    """
    url = f"http://127.0.0.1:{port}/"
    try:
        with _open_http(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_gui(port: int) -> None:
    """Start the GUI detached so it survives this watchdog process."""
    args = [sys.executable, "-m", "auto_dev_crew.gui", "--port", str(port), "--no-browser", "--auto"]
    kwargs: dict = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        # Do NOT use DETACHED_PROCESS: a detached GUI has no console, so every
        # console child it spawns (gh, git, taskkill, the runner) opens a visible
        # window. CREATE_NO_WINDOW gives the GUI a hidden console that its children
        # inherit, so nothing pops up; CREATE_NEW_PROCESS_GROUP keeps it alive after
        # this watchdog exits.
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    else:
        kwargs["start_new_session"] = True
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    subprocess.Popen(args, **kwargs)


def check_once(port: int, failures: int) -> int:
    """Run one check. Returns the new consecutive-failure count."""
    if OFF_FLAG.exists():
        return 0
    if is_healthy(port):
        if failures:
            log(f"GUI healthy again on port {port} after {failures} failed check(s)")
        return 0
    failures += 1
    log(f"GUI not responding on port {port} (failure #{failures}); starting it")
    start_gui(port)
    # Give it time to bind before the next check.
    for _ in range(20):
        time.sleep(1)
        if is_healthy(port):
            log(f"GUI started on port {port}")
            return 0
    log(f"GUI still not responding after start attempt (failure #{failures})")
    return failures


def main() -> int:
    p = argparse.ArgumentParser(description="Keep the Auto Dev Crew GUI running.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--loop", action="store_true", help="keep checking forever")
    p.add_argument("--interval", type=int, default=60, help="seconds between checks in --loop mode")
    args = p.parse_args()

    failures = 0
    if not args.loop:
        check_once(args.port, failures)
        return 0 if is_healthy(args.port) or OFF_FLAG.exists() else 1

    while True:
        failures = check_once(args.port, failures)
        wait = args.interval
        if failures:
            wait = min(args.interval * (2 ** (failures - 1)), MAX_BACKOFF)
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())

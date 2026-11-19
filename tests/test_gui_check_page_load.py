"""check_page must not fail just because the page keeps one request open (long-poll).

Regression: `page.goto(..., wait_until="networkidle")` waits for 500 ms with no
network activity. The GUI keeps a long-poll request open, so the smoke check timed
out even though the page loaded and had no JS errors.
"""
from __future__ import annotations

import http.server
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

from auto_dev_crew import gui_check  # noqa: E402

PAGE = (
    b"<!doctype html><html><head><meta charset='utf-8'><title>t</title></head>"
    b"<body><p>ok</p><script>fetch('/hang').catch(function () {});</script></body></html>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        if self.path == "/hang":
            # Keep this request open for longer than the test runs, like a long-poll.
            time.sleep(60)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):  # keep test output quiet
        pass


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture
def long_poll_server():
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _chromium_available() -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 - browser not installed on this machine
        return False


def test_check_page_passes_when_one_request_stays_open(long_poll_server, tmp_path, monkeypatch):
    if not _chromium_available():
        pytest.skip("Chromium for Playwright is not installed")
    monkeypatch.setattr(gui_check, "PAGE_TIMEOUT_MS", 5000)

    problems = gui_check.check_page(long_poll_server, tmp_path / "shot.png")

    assert problems == []
    assert (tmp_path / "shot.png").exists()

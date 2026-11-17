"""Public read-only status page for Auto Dev Crew.

Serves only aggregate counts. It never returns repo names, issue/PR titles, the
owner, engine names, key status, logs, or any control endpoint. Control stays in
``gui.py`` bound to 127.0.0.1 and is reached over an SSH tunnel.

Run: ``python -m auto_dev_crew.public_view --port 8080``
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PUBLIC_DIR = Path(__file__).parent / "public"
_MAX_DRAIN_BYTES = 64 * 1024  # largest rejected body we read before answering 405

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                               "img-src 'self' data:; frame-ancestors 'none'",
}


def build_public_snapshot(cfg: dict, history: list[dict], now: dt.datetime | None = None) -> dict:
    """Aggregates only. Nothing identifying (names, titles, keys, reasons) is copied."""
    now = now or dt.datetime.now()
    states = Counter(str(item.get("state") or "UNKNOWN") for item in history)
    dates = [item["date"] for item in history if isinstance(item.get("date"), str)]
    engines = cfg.get("engines") or []
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "runs": {
            "total": len(history),
            "by_state": dict(states),
            "last_at": max(dates) if dates else None,
        },
        "repos_tracked": len(cfg.get("repos") or []),
        "engines_enabled": sum(1 for e in engines if isinstance(e, dict) and e.get("enabled", True)),
    }


def make_server(host: str, port: int, cfg_loader: Callable[[], dict],
                history_loader: Callable[[], list[dict]]) -> ThreadingHTTPServer:
    """Build the read-only HTTP server. Loaders are injected so tests need no real state."""

    class PublicHandler(BaseHTTPRequestHandler):
        server_version = "AutoDevCrewPublic"
        _head_only = False  # True while answering HEAD: same headers, no body

        def log_message(self, *_):  # keep the console quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if not self._head_only:
                self.wfile.write(body)

        def do_HEAD(self) -> None:
            self._head_only = True
            try:
                self.do_GET()
            finally:
                self._head_only = False

        def _json(self, code: int, payload: dict, extra: dict | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(code, body, "application/json; charset=utf-8", extra)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                html = (PUBLIC_DIR / "index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
            if path == "/api/public":
                try:
                    snapshot = build_public_snapshot(cfg_loader(), history_loader())
                except Exception:
                    # Never echo loader errors: they can contain local paths or secrets.
                    return self._json(503, {"error": "unavailable"})
                return self._json(200, snapshot, {"Cache-Control": "public, max-age=30"})
            return self._json(404, {"error": "not found"})

        def _not_allowed(self) -> None:
            # Read a small body first so the client's send completes before we answer.
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if 0 < n <= _MAX_DRAIN_BYTES:
                self.rfile.read(n)
            self.close_connection = True
            self._json(405, {"error": "method not allowed"}, {"Allow": "GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _not_allowed

    return ThreadingHTTPServer((host, port), PublicHandler)


def _default_cfg_loader(config_path: Path) -> Callable[[], dict]:
    def load() -> dict:
        from . import yaml_io
        return yaml_io.load_text(config_path.read_text(encoding="utf-8")) or {}
    return load


def _default_history_loader() -> list[dict]:
    from . import runner
    return runner.load_history()


def main() -> None:
    from . import runner
    p = argparse.ArgumentParser(prog="auto-dev-crew-public")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--config", default=None, help="config.yaml to read (default: project config.yaml)")
    args = p.parse_args()
    config_path = Path(args.config) if args.config else runner.ROOT / "config.yaml"
    server = make_server(args.host, args.port, _default_cfg_loader(config_path), _default_history_loader)
    print(f"Auto Dev Crew public view: http://{args.host}:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

"""Public read-only view: must expose aggregates only and no control or secret surface."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from auto_dev_crew import public_view


CFG = {
    "owner": "secret-owner-name",
    "merge_mode": "auto",
    "repos": [{"name": "secret-owner/private-repo", "enabled": True}],
    "engines": [
        {"name": "opencode-x", "command": "opencode", "model": "p/m", "enabled": True,
         "api_keys": ["sk-LEAKME-123456789012345"]},
        {"name": "off", "command": "gemini", "model": "g", "enabled": False},
    ],
}

HISTORY = [
    {"repo": "secret-owner/private-repo", "kind": "issue", "key": "42", "date": "20261101-1200",
     "title": "Fix SECRET-TITLE-XYZ", "state": "DONE"},
    {"repo": "secret-owner/private-repo", "kind": "pr", "key": "7", "date": "20261105-0900",
     "title": "PR SECRET-TITLE-ABC", "state": "NO_BUG", "fail_reason": "reason SECRET-REASON"},
    {"repo": "secret-owner/private-repo", "kind": "issue", "key": "43", "date": "20261110-1000",
     "title": "again", "state": "DONE"},
]


class SnapshotTests(unittest.TestCase):
    def test_snapshot_has_aggregates_only(self):
        snap = public_view.build_public_snapshot(CFG, HISTORY)
        self.assertEqual(snap["runs"]["total"], 3)
        self.assertEqual(snap["runs"]["by_state"], {"DONE": 2, "NO_BUG": 1})
        self.assertEqual(snap["runs"]["last_at"], "20261110-1000")
        self.assertEqual(snap["repos_tracked"], 1)
        self.assertEqual(snap["engines_enabled"], 1)
        self.assertIn("generated_at", snap)

    def test_snapshot_never_contains_names_titles_keys_or_reasons(self):
        text = json.dumps(public_view.build_public_snapshot(CFG, HISTORY))
        for secret in ("secret-owner", "private-repo", "SECRET-TITLE", "SECRET-REASON",
                       "LEAKME", "sk-", "api_keys", "opencode-x", "owner", "PR SECRET"):
            self.assertNotIn(secret, text, f"public snapshot leaked {secret!r}")

    def test_empty_history_is_safe(self):
        snap = public_view.build_public_snapshot({"repos": [], "engines": []}, [])
        self.assertEqual(snap["runs"], {"total": 0, "by_state": {}, "last_at": None})
        self.assertEqual(snap["repos_tracked"], 0)


class _Server:
    def __enter__(self):
        self.srv = public_view.make_server(
            "127.0.0.1", 0, cfg_loader=lambda: CFG, history_loader=lambda: HISTORY)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()

    def request(self, path, method="GET", data=None):
        req = urllib.request.Request(self.base + path, method=method, data=data)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()


class HandlerTests(unittest.TestCase):
    def test_public_api_returns_snapshot_json(self):
        with _Server() as s:
            status, headers, body = s.request("/api/public")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(json.loads(body)["runs"]["total"], 3)

    def test_homepage_served_with_security_headers(self):
        with _Server() as s:
            status, headers, body = s.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/public", body)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))

    def test_control_surface_is_not_reachable(self):
        paths = ["/api/status", "/api/log", "/api/keys", "/api/run", "/api/task",
                 "/api/repos/add", "/api/server/shutdown", "/classic", "/api/repo/file-content",
                 "/api/engine", "/api/doctor", "/api/metrics", "/api/models"]
        with _Server() as s:
            for path in paths:
                status, _, body = s.request(path)
                self.assertEqual(status, 404, path)
                self.assertNotIn(b"TOKEN", body)

    def test_head_returns_headers_without_body(self):
        with _Server() as s:
            req = urllib.request.Request(s.base + "/", method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
                self.assertEqual(resp.read(), b"")

    def test_write_methods_are_rejected(self):
        with _Server() as s:
            for method in ("POST", "PUT", "DELETE", "PATCH"):
                status, _, _ = s.request("/api/public", method=method, data=b"{}")
                self.assertEqual(status, 405, method)

    def test_path_traversal_and_unknown_paths_404(self):
        with _Server() as s:
            for path in ("/../config.yaml", "/static/../../config.yaml", "/%2e%2e/config.yaml",
                         "/nope", "/api/public/../status"):
                status, _, _ = s.request(path)
                self.assertEqual(status, 404, path)

    def test_loader_failure_returns_generic_503(self):
        def boom():
            raise RuntimeError("secret path C:\\Users\\x\\.env")
        srv = public_view.make_server("127.0.0.1", 0, cfg_loader=boom, history_loader=lambda: [])
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/api/public"
            try:
                urllib.request.urlopen(url, timeout=5)
                self.fail("expected 503")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 503)
                self.assertNotIn(b"secret path", exc.read())
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()

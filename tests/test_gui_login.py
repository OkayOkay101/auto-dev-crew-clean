"""Password login on the control GUI: gate, login/logout, cookie flags, rate limit, CSRF still required.

Runs a live server on 127.0.0.1:0 with its own auth file and fresh session/limiter objects,
so the real state/auth.json and real sessions are never touched.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from auto_dev_crew import auth, gui

PASSWORD = "gui-login-pass-1"


class _LoginServer:
    def __init__(self, tmp: Path, *, require_login: bool = True) -> None:
        self.auth_file = tmp / "auth.json"
        auth.save_password_hash(self.auth_file, auth.hash_password(PASSWORD))
        self.patches = mock.patch.multiple(
            gui,
            REQUIRE_LOGIN=require_login,
            AUTH_FILE=self.auth_file,
            SESSIONS=auth.SessionStore(ttl_seconds=3600),
            LOGIN_LIMITER=auth.LoginLimiter(max_failures=5, window_seconds=900, lock_seconds=900),
        )
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "_LoginServer":
        self.patches.start()
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.patches.stop()

    def request(self, method: str, path: str, headers: dict | None = None, body: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            hdrs = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
            if payload is not None:
                hdrs["Content-Type"] = "application/json"
                hdrs["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=hdrs)
            resp = conn.getresponse()
            return resp.status, resp.getheaders(), resp.read()
        finally:
            conn.close()

    def login(self, password: str = PASSWORD) -> str:
        status, headers, _ = self.request("POST", "/api/login", body={"password": password})
        assert status == 200, status
        cookie = next(v for k, v in headers if k.lower() == "set-cookie")
        return cookie.split(";", 1)[0].split("=", 1)[1]


def _cookie(token: str) -> dict:
    return {"Cookie": f"adc_session={token}"}


class GateTests(unittest.TestCase):
    def test_index_redirects_to_login_without_session(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, headers, _ = s.request("GET", "/")
        self.assertEqual(status, 302)
        self.assertEqual(dict((k.lower(), v) for k, v in headers)["location"], "/login")

    def test_api_without_session_gets_401(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, _, body = s.request("GET", "/api/favorites")
        self.assertEqual(status, 401)
        self.assertIn("error", json.loads(body))

    def test_forged_session_cookie_gets_401(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, _, _ = s.request("GET", "/api/favorites", headers=_cookie("guessed-token"))
        self.assertEqual(status, 401)

    def test_login_page_is_public_and_does_not_leak_the_gui_token(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, _, body = s.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/login", body)
        self.assertNotIn(gui.TOKEN.encode("utf-8"), body)

    def test_byop_callback_stays_reachable_without_session(self):
        # Cross-site redirect from the provider cannot carry a SameSite=Strict cookie.
        # Its protection is the server-side state + PKCE, so the session gate must not block it.
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, _, _ = s.request("GET", "/api/byop/callback?state=none&code=none")
        self.assertNotIn(status, (401, 302))

    def test_gate_is_off_when_login_not_required(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp), require_login=False) as s:
            status, _, _ = s.request("GET", "/api/favorites")
        self.assertEqual(status, 200)


class LoginFlowTests(unittest.TestCase):
    def test_correct_password_sets_hardened_session_cookie(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, headers, _ = s.request("POST", "/api/login", body={"password": PASSWORD})
            set_cookie = next(v for k, v in headers if k.lower() == "set-cookie")
        self.assertEqual(status, 200)
        flags = set_cookie.lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/", "max-age="):
            self.assertIn(flag, flags)

    def test_session_from_login_opens_the_api(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            token = s.login()
            status, _, _ = s.request("GET", "/api/favorites", headers=_cookie(token))
        self.assertEqual(status, 200)

    def test_wrong_password_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, headers, _ = s.request("POST", "/api/login", body={"password": "wrong-pass-999"})
            has_cookie = any(k.lower() == "set-cookie" for k, _ in headers)
        self.assertEqual(status, 401)
        self.assertFalse(has_cookie)

    def test_five_wrong_passwords_lock_out_even_the_right_one(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            for _ in range(5):
                s.request("POST", "/api/login", body={"password": "wrong-pass-999"})
            status, _, _ = s.request("POST", "/api/login", body={"password": PASSWORD})
        self.assertEqual(status, 429)

    def test_logout_revokes_the_session(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            token = s.login()
            out_status, _, _ = s.request("POST", "/api/logout", headers=_cookie(token))
            after, _, _ = s.request("GET", "/api/favorites", headers=_cookie(token))
        self.assertEqual(out_status, 200)
        self.assertEqual(after, 401)

    def test_login_refused_for_foreign_origin(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            status, _, _ = s.request("POST", "/api/login", headers={"Origin": "https://evil.example"},
                                     body={"password": PASSWORD})
        self.assertEqual(status, 403)


class CsrfStillRequiredTests(unittest.TestCase):
    def test_session_alone_does_not_pass_the_post_token_check(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            token = s.login()
            status, _, _ = s.request("POST", "/api/does-not-exist", headers=_cookie(token), body={})
        self.assertEqual(status, 403)

    def test_session_plus_gui_token_reaches_routing(self):
        with tempfile.TemporaryDirectory() as tmp, _LoginServer(Path(tmp)) as s:
            token = s.login()
            headers = {**_cookie(token), "X-Token": gui.TOKEN}
            status, _, _ = s.request("POST", "/api/does-not-exist", headers=headers, body={})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

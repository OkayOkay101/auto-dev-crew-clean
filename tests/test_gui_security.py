"""Security regression tests for the local GUI server (CRIT-01, LOW-07).

The server is started on an ephemeral port (127.0.0.1:0) inside the test process,
so nothing touches the real config.yaml, .env, opencode.json or state/ folder.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
import threading

import yaml

from auto_dev_crew import gui, keys, multi_repo
from auto_dev_crew.keys import add_engine


class _LiveServer:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), gui.Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "_LiveServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def request(self, method: str, path: str, headers: dict | None = None, body: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()


def _good_host(port: int) -> str:
    return f"127.0.0.1:{port}"


class TestHostOriginGuard(unittest.TestCase):
    def setUp(self):
        self.server = _LiveServer().__enter__()

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def test_forged_host_gets_403_on_index(self):
        status, body = self.server.request("GET", "/", headers={"Host": "evil.example:%d" % self.server.port})
        self.assertEqual(status, 403)
        self.assertNotIn(gui.TOKEN.encode(), body)

    def test_good_host_gets_index_with_token(self):
        status, body = self.server.request("GET", "/", headers={"Host": _good_host(self.server.port)})
        self.assertEqual(status, 200)
        self.assertIn(gui.TOKEN.encode(), body)

    def test_localhost_host_is_accepted(self):
        status, _ = self.server.request("GET", "/api/favorites", headers={"Host": "localhost:%d" % self.server.port})
        self.assertEqual(status, 200)

    def test_forged_host_gets_403_on_api_get(self):
        status, _ = self.server.request("GET", "/api/favorites", headers={"Host": "evil.example:%d" % self.server.port})
        self.assertEqual(status, 403)

    def test_forged_host_gets_403_on_post(self):
        body = json.dumps({"key_id": "x#key_0"}).encode()
        status, _ = self.server.request(
            "POST", "/api/key/reset",
            headers={"Host": "evil.example:%d" % self.server.port, "X-Token": gui.TOKEN,
                     "Content-Type": "application/json", "Content-Length": str(len(body))},
            body=body,
        )
        self.assertEqual(status, 403)

    def test_bad_origin_on_post_gets_403(self):
        body = json.dumps({"key_id": "x#key_0"}).encode()
        status, _ = self.server.request(
            "POST", "/api/key/reset",
            headers={"Host": _good_host(self.server.port), "Origin": "https://evil.example",
                     "X-Token": gui.TOKEN, "Content-Type": "application/json",
                     "Content-Length": str(len(body))},
            body=body,
        )
        self.assertEqual(status, 403)

    def test_good_origin_and_host_on_post_is_accepted(self):
        body = json.dumps({"key_id": "x#key_0"}).encode()
        status, _ = self.server.request(
            "POST", "/api/key/reset",
            headers={"Host": _good_host(self.server.port), "Origin": "http://127.0.0.1:%d" % self.server.port,
                     "X-Token": gui.TOKEN, "Content-Type": "application/json",
                     "Content-Length": str(len(body))},
            body=body,
        )
        self.assertEqual(status, 200)


class TestRequestBodyLimits(unittest.TestCase):
    def setUp(self):
        self.server = _LiveServer().__enter__()

    def tearDown(self):
        self.server.__exit__(None, None, None)

    def _post(self, length_header: str):
        return self.server.request(
            "POST", "/api/key/reset",
            headers={"Host": _good_host(self.server.port), "X-Token": gui.TOKEN,
                     "Content-Type": "application/json", "Content-Length": length_header},
            body=b"",
        )

    def test_oversized_body_gets_413(self):
        status, _ = self._post(str(1024 * 1024 + 1))
        self.assertEqual(status, 413)

    def test_negative_content_length_gets_400(self):
        status, _ = self._post("-5")
        self.assertEqual(status, 400)

    def test_non_integer_content_length_gets_400(self):
        status, _ = self._post("abc")
        self.assertEqual(status, 400)


class TestRunCommandAndEngineCommandAllowlist(unittest.TestCase):
    def test_unknown_check_type_raises_value_error_without_running_shell(self):
        with mock.patch.object(multi_repo.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                multi_repo.run_repo_verification("example-owner/some-repo", "calc", {})
            run.assert_not_called()

    def test_act_run_command_unknown_check_type_is_error(self):
        with mock.patch.object(gui, "load_cfg", return_value={}),                 mock.patch.object(multi_repo.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                gui.act("/api/repo/run-command", {"repo": "example-owner/some-repo", "check_type": "calc.exe"})
            run.assert_not_called()

    def test_add_engine_rejects_arbitrary_command(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text("engines: []\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                add_engine({"name": "evil", "command": "calc", "model": "m"}, cfg_path=cfg)
            self.assertEqual(yaml.safe_load(cfg.read_text(encoding="utf-8")), {"engines": []})

    def test_add_engine_rejects_path_not_matching_command(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text("engines: []\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                add_engine({"name": "p", "command": "opencode", "model": "opencode/m",
                            "path": "C:\\Windows\\System32\\calc.exe"}, cfg_path=cfg)

    def test_add_engine_accepts_matching_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text("engines: []\n", encoding="utf-8")
            self.assertTrue(add_engine({"name": "p", "command": "opencode", "model": "opencode/m",
                                        "path": "C:\\Tools\\opencode.cmd"}, cfg_path=cfg))


class TestBodySizeHelper(unittest.TestCase):
    def test_body_limit_constant_is_one_megabyte(self):
        self.assertEqual(gui.MAX_BODY_BYTES, 1024 * 1024)


if __name__ == "__main__":
    unittest.main()


class TestCfgPathNotAcceptedFromClient(unittest.TestCase):
    """MED-14: the HTTP API must never choose which file gets overwritten."""

    def test_act_with_cfg_path_does_not_modify_that_file(self):
        original = "engines:\n- name: decoy\n  provider: P\n  command: opencode\n  model: m\n  enabled: true\n"
        with tempfile.TemporaryDirectory() as d:
            decoy = Path(d) / "decoy.yaml"
            decoy.write_text(original, encoding="utf-8")
            with mock.patch.object(keys, "ROOT", Path(d) / "root"):
                (Path(d) / "root").mkdir()
                (Path(d) / "root" / "config.yaml").write_text("engines: []\n", encoding="utf-8")
                res = gui.act("/api/engine/create", {
                    "name": "api-made", "provider": "P", "command": "opencode", "model": "opencode/m",
                    "cfg_path": str(decoy),
                })
                self.assertTrue(res.get("ok"))
                res = gui.act("/api/engine/delete", {"name": "decoy", "cfg_path": str(decoy)})
                self.assertIn("ok", res)
            self.assertEqual(decoy.read_text(encoding="utf-8"), original)
            written = yaml.safe_load((Path(d) / "root" / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual([e["name"] for e in written["engines"]], ["api-made"])

"""Pollinations BYOP: PKCE, state handling, authorize URL, connect flow (network mocked)."""
import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import byop, providers
from auto_dev_crew import gui


class PkceTests(unittest.TestCase):
    def test_rfc7636_known_vector(self):
        # ตัวอย่างจาก RFC 7636 Appendix B
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        self.assertEqual(byop._b64url(hashlib.sha256(verifier.encode()).digest()), expected)

    def test_make_pkce_pair_length_and_charset(self):
        verifier, challenge = byop.make_pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertNotIn("=", challenge)
        self.assertEqual(len(challenge), 43)


class AuthorizeUrlTests(unittest.TestCase):
    def test_contains_required_params_and_clamps_budget(self):
        url = byop.build_authorize_url(app_key="pk_x", redirect_uri="http://localhost/api/byop/callback",
                                       state="s1", code_challenge="c1", budget=999, expiry=7)
        self.assertTrue(url.startswith("https://enter.pollinations.ai/authorize?"))
        self.assertIn("client_id=pk_x", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("scope=usage", url)
        self.assertIn("models=text", url)
        self.assertIn("state=s1", url)
        self.assertNotIn("sk_", url)
        self.assertEqual(byop.clamp_budget(999), 10.0)
        self.assertEqual(byop.clamp_budget("abc"), 5.0)
        self.assertEqual(byop.clamp_expiry(0), 1)
        self.assertEqual(byop.clamp_expiry(500), 30)


class StateTests(unittest.TestCase):
    def setUp(self):
        byop._pending.clear()

    def test_state_is_single_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("POLLINATIONS_APP_KEY=pk_test\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(byop.APP_KEY_ENV, None)
                res = byop.start_authorization(redirect_uri="http://localhost/api/byop/callback", env_path=env)
        state = res["authorize_url"].split("state=")[1].split("&")[0]
        self.assertIsNotNone(byop.consume_state(state))
        self.assertIsNone(byop.consume_state(state))

    def test_unknown_or_empty_state_rejected(self):
        self.assertIsNone(byop.consume_state("nope"))
        self.assertIsNone(byop.consume_state(""))

    def test_expired_state_rejected(self):
        byop._pending["old"] = ("v", time.monotonic() - byop.STATE_TTL_SECONDS - 1)
        self.assertIsNone(byop.consume_state("old"))

    def test_start_requires_pk_app_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(byop.APP_KEY_ENV, None)
                with self.assertRaises(byop.ByopError):
                    byop.start_authorization(redirect_uri="http://localhost/cb", env_path=env)


class ConnectTests(unittest.TestCase):
    def setUp(self):
        byop._pending.clear()

    def _workspace(self, tmp: str):
        root = Path(tmp)
        env = root / ".env"
        env.write_text("POLLINATIONS_APP_KEY=pk_test_app\n", encoding="utf-8")
        cfg = root / "config.yaml"
        cfg.write_text("engines: []\n", encoding="utf-8")
        return {
            "env_path": env,
            "cfg_path": cfg,
            "providers_path": root / "providers.json",
            "opencode_path": root / "opencode.json",
        }

    def test_connect_registers_provider_and_stores_key_in_env(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            paths = self._workspace(tmp)
            os.environ.pop(byop.APP_KEY_ENV, None)
            os.environ.pop(byop.key_var(), None)
            byop._pending["st1"] = ("verifier-1", time.monotonic())
            redirect = "http://localhost:8765/api/byop/callback"
            with mock.patch("auto_dev_crew.byop.exchange_code", return_value="sk_test_abcdefghijkl") as ex:
                res = byop.connect(code="code-1", state="st1", redirect_uri=redirect, **paths)
            ex.assert_called_once()
            self.assertEqual(ex.call_args.kwargs["verifier"], "verifier-1")
            self.assertEqual(ex.call_args.kwargs["app_key"], "pk_test_app")
            self.assertNotIn("sk_test", str(res))  # ค่าคีย์ไม่ถูกส่งกลับ มีเฉพาะค่าที่ mask
            env_text = paths["env_path"].read_text(encoding="utf-8")
            self.assertIn("POLLINATIONS_API_KEY_1=sk_test_abcdefghijkl", env_text)
            reg = providers.load_providers(paths["providers_path"], paths["opencode_path"])
            self.assertIn(byop.PROVIDER_ID, reg)
            self.assertEqual(reg[byop.PROVIDER_ID]["base_url"], byop.BASE_URL)
            cfg_text = paths["cfg_path"].read_text(encoding="utf-8")
            self.assertIn("opencode-pollinations", cfg_text)

    def test_connect_rejects_bad_state_without_network(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            paths = self._workspace(tmp)
            with mock.patch("auto_dev_crew.byop.exchange_code") as ex:
                with self.assertRaises(byop.ByopError):
                    byop.connect(code="c", state="forged", redirect_uri="http://localhost/cb", **paths)
            ex.assert_not_called()

    def test_reconnect_replaces_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            paths = self._workspace(tmp)
            paths["env_path"].write_text(
                "POLLINATIONS_APP_KEY=pk_test_app\nPOLLINATIONS_API_KEY_1=sk_old_value_1234\n", encoding="utf-8")
            byop._pending["st2"] = ("v2", time.monotonic())
            with mock.patch("auto_dev_crew.byop.exchange_code", return_value="sk_new_value_5678"):
                byop.connect(code="c2", state="st2", redirect_uri="http://localhost/cb", **paths)
            env_text = paths["env_path"].read_text(encoding="utf-8")
            self.assertIn("sk_new_value_5678", env_text)
            self.assertNotIn("sk_old_value_1234", env_text)
            self.assertEqual(env_text.count("POLLINATIONS_API_KEY_1="), 1)


class StatusAndDisconnectTests(unittest.TestCase):
    def test_status_and_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            env = Path(tmp) / ".env"
            env.write_text("POLLINATIONS_APP_KEY=pk_x\nPOLLINATIONS_API_KEY_1=sk_abcdefghijklmnop\n", encoding="utf-8")
            st = byop.status(env_path=env)
            self.assertTrue(st["connected"])
            self.assertTrue(st["app_key_configured"])
            self.assertNotIn("abcdefghijklmnop", st["masked"])
            res = byop.disconnect(env_path=env)
            self.assertTrue(res["disconnected"])
            self.assertFalse(byop.status(env_path=env)["connected"])


class CallbackPageTests(unittest.TestCase):
    def test_message_is_escaped(self):
        page = gui._byop_page("<script>alert(1)</script>", ok=False)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)


if __name__ == "__main__":
    unittest.main()

"""Provider registry: URL and key-variable names live in one place and sync to opencode.json."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import key_ping, providers


class ValidationTests(unittest.TestCase):
    def test_base_url_must_be_https_without_spaces(self):
        self.assertEqual(providers.validate_base_url(" https://api.deepseek.com/v1/ "),
                         "https://api.deepseek.com/v1")
        for bad in ["", "http://api.example.com", "file:///etc/passwd", "https://", "https://a b.com"]:
            with self.subTest(url=bad), self.assertRaises(ValueError):
                providers.validate_base_url(bad)

    def test_provider_id_format(self):
        self.assertEqual(providers.validate_provider_id("DeepSeek"), "deepseek")
        for bad in ["a", "deep seek", "1abc", "x" * 40]:
            with self.subTest(pid=bad), self.assertRaises(ValueError):
                providers.validate_provider_id(bad)

    def test_key_var_naming(self):
        self.assertEqual(providers.provider_key_var("my-api"), "MY_API_API_KEY_1")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.opencode = self.dir / "opencode.json"
        self.providers_file = self.dir / "providers.json"
        self.env = self.dir / ".env"
        self.cfg = self.dir / "config.yaml"
        self.cfg.write_text("engines: []\n", encoding="utf-8")

    def tearDown(self):
        os.environ.pop("DEEPSEEK_API_KEY_1", None)
        self.tmp.cleanup()

    def _write_opencode(self, data):
        self.opencode.write_text(json.dumps(data), encoding="utf-8")

    def test_seed_reads_base_url_and_key_var_from_opencode(self):
        self._write_opencode({"provider": {"pollinations": {
            "name": "Pollinations AI",
            "options": {"baseURL": "https://gen.pollinations.ai/v1", "apiKey": "{env:POLLINATIONS_API_KEY_1}"}}}})
        seeded = providers.seed_from_opencode(self.opencode)
        self.assertEqual(seeded["pollinations"], {"display_name": "Pollinations AI",
                                                  "base_url": "https://gen.pollinations.ai/v1",
                                                  "key_var": "POLLINATIONS_API_KEY_1"})

    def test_sync_updates_url_and_keeps_models(self):
        self._write_opencode({
            "provider": {"deepseek": {"name": "DeepSeek", "options": {"baseURL": "https://old.example.com"},
                                      "models": {"deepseek-chat": {"name": "Chat"}}}},
            "providers": {"deepseek": {"settings": {"baseURL": "https://old.example.com"}}},
        })
        providers.sync_opencode(
            {"deepseek": {"display_name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                          "key_var": "DEEPSEEK_API_KEY_1"}},
            opencode_path=self.opencode)
        data = json.loads(self.opencode.read_text(encoding="utf-8"))
        block = data["provider"]["deepseek"]
        self.assertEqual(block["options"]["baseURL"], "https://api.deepseek.com/v1")
        self.assertEqual(block["options"]["apiKey"], "{env:DEEPSEEK_API_KEY_1}")
        self.assertIn("deepseek-chat", block["models"], "existing models must survive a sync")
        self.assertEqual(data["providers"]["deepseek"]["settings"]["baseURL"], "https://api.deepseek.com/v1")

    def test_add_provider_writes_engine_key_registry_and_opencode(self):
        self._write_opencode({"provider": {}})
        result = providers.add_provider(
            pid="deepseek", display_name="DeepSeek AI", base_url="https://api.deepseek.com/v1/",
            api_key="sk-secret-value-123", model="deepseek/deepseek-chat",
            providers_path=self.providers_file, opencode_path=self.opencode, cfg_path=self.cfg, env_path=self.env)

        self.assertNotIn("sk-secret-value-123", json.dumps(result), "the key must not be returned")
        self.assertEqual(result["key_var"], "DEEPSEEK_API_KEY_1")
        cfg_text = self.cfg.read_text(encoding="utf-8")
        self.assertIn("opencode-deepseek", cfg_text)
        self.assertIn("provider_id: deepseek", cfg_text)
        self.assertIn("${DEEPSEEK_API_KEY_1}", cfg_text)
        self.assertIn("DEEPSEEK_API_KEY_1=sk-secret-value-123", self.env.read_text(encoding="utf-8"))
        registry = json.loads(self.providers_file.read_text(encoding="utf-8"))["providers"]
        self.assertEqual(registry["deepseek"]["base_url"], "https://api.deepseek.com/v1")
        data = json.loads(self.opencode.read_text(encoding="utf-8"))
        self.assertEqual(data["provider"]["deepseek"]["options"]["baseURL"], "https://api.deepseek.com/v1")
        self.assertIn("deepseek-chat", data["provider"]["deepseek"]["models"])

    def test_duplicate_provider_is_rejected_without_touching_env(self):
        self._write_opencode({"provider": {}})
        kwargs = dict(pid="deepseek", display_name="DeepSeek", base_url="https://api.deepseek.com/v1",
                      api_key="sk-one", model="deepseek/deepseek-chat", providers_path=self.providers_file,
                      opencode_path=self.opencode, cfg_path=self.cfg, env_path=self.env)
        providers.add_provider(**kwargs)
        env_before = self.env.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            providers.add_provider(**{**kwargs, "api_key": "sk-two"})
        self.assertEqual(self.env.read_text(encoding="utf-8"), env_before)

    def test_existing_env_key_is_never_overwritten(self):
        self._write_opencode({"provider": {}})
        self.env.write_text("DEEPSEEK_API_KEY_1=old-value\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            providers.add_provider(pid="deepseek", display_name="DeepSeek", base_url="https://api.deepseek.com/v1",
                                   api_key="sk-new", model="deepseek/deepseek-chat",
                                   providers_path=self.providers_file, opencode_path=self.opencode,
                                   cfg_path=self.cfg, env_path=self.env)
        self.assertIn("DEEPSEEK_API_KEY_1=old-value", self.env.read_text(encoding="utf-8"))

    def test_failure_after_engine_is_added_rolls_back(self):
        self._write_opencode({"provider": {}})
        with mock.patch.object(providers, "sync_opencode", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                providers.add_provider(pid="deepseek", display_name="DeepSeek", base_url="https://api.deepseek.com/v1",
                                       api_key="sk-rollback", model="deepseek/deepseek-chat",
                                       providers_path=self.providers_file, opencode_path=self.opencode,
                                       cfg_path=self.cfg, env_path=self.env)
        self.assertNotIn("opencode-deepseek", self.cfg.read_text(encoding="utf-8"))
        self.assertNotIn("DEEPSEEK_API_KEY_1", self.env.read_text(encoding="utf-8") if self.env.exists() else "")

    def test_rejects_http_url_before_writing_anything(self):
        self._write_opencode({"provider": {}})
        with self.assertRaises(ValueError):
            providers.add_provider(pid="deepseek", display_name="DeepSeek", base_url="http://insecure.example.com",
                                   api_key="sk-x", model="deepseek/deepseek-chat",
                                   providers_path=self.providers_file, opencode_path=self.opencode,
                                   cfg_path=self.cfg, env_path=self.env)
        self.assertNotIn("opencode-deepseek", self.cfg.read_text(encoding="utf-8"))
        self.assertFalse(self.env.exists())


class KeyPingRegistryTests(unittest.TestCase):
    def test_registry_engine_does_not_guess_base_url_from_name(self):
        eng = {"name": "opencode-pollinations-x", "provider": "Pollinations", "command": "opencode",
               "provider_id": "deepseek"}
        env = key_ping._key_env(eng, "DEEPSEEK_API_KEY_1", "sk-test")
        self.assertEqual(env["DEEPSEEK_API_KEY_1"], "sk-test")
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertNotIn("POLLINATIONS_API_KEY", env)

    def test_legacy_engine_keeps_existing_behaviour(self):
        eng = {"name": "opencode-pollinations", "provider": "Pollinations.ai", "command": "opencode"}
        env = key_ping._key_env(eng, "POLLINATIONS_API_KEY_1", "sk-test")
        self.assertEqual(env["OPENAI_BASE_URL"], "https://gen.pollinations.ai/v1")


if __name__ == "__main__":
    unittest.main()

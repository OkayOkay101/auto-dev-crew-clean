"""engine 'opencode free' ต้องผูกกับ OPENCODE_API_KEY_1 เพื่อให้การ์ดแสดงคีย์และการปิงใช้คีย์จริง."""
import os
import unittest
from unittest.mock import patch

from auto_dev_crew import key_ping
from auto_dev_crew.keys import get_keys_catalog

KEY = "sk-opencode-test-" + "b" * 32


def _eng():
    return {
        "name": "opencode free",
        "provider": "Opencode",
        "command": "opencode",
        "model": "opencode/nemotron-3.5-super-vl-free",
        "api_keys": ["${OPENCODE_API_KEY_1}"],
    }


class TestOpencodeFreeKeyCard(unittest.TestCase):
    def test_card_reports_key_when_env_var_is_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCODE_API_KEY_1", None)
            cat = get_keys_catalog({"engines": [_eng()]}, env_vars={"OPENCODE_API_KEY_1": KEY})
        prov = cat["providers"][0]
        self.assertTrue(prov["has_configured_key"])
        self.assertEqual(prov["keys"][0]["env_var"], "OPENCODE_API_KEY_1")
        self.assertTrue(prov["keys"][0]["configured"])

    def test_card_reports_unset_without_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENCODE_API_KEY_1", None)
            cat = get_keys_catalog({"engines": [_eng()]}, env_vars={})
        prov = cat["providers"][0]
        self.assertFalse(prov["has_configured_key"])
        self.assertFalse(prov["keys"][0]["configured"])


class TestOpencodeFreePingEnv(unittest.TestCase):
    def test_ping_env_exposes_key_as_opencode_api_key(self):
        env = key_ping._key_env(_eng(), "OPENCODE_API_KEY_1", KEY)
        self.assertEqual(env["OPENCODE_API_KEY"], KEY)
        self.assertEqual(env["OPENCODE_API_KEY_1"], KEY)

    def test_non_opencode_provider_does_not_get_opencode_key(self):
        eng = {"name": "opencode-nvidia", "provider": "NVIDIA build", "command": "opencode", "api_keys": []}
        env = key_ping._key_env(eng, "NVIDIA_API_KEY_1", KEY)
        self.assertNotIn("OPENCODE_API_KEY", env)


if __name__ == "__main__":
    unittest.main()

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from auto_dev_crew.keys import get_opencode_auth_keys, get_keys_catalog


class TestOpenCodeAuthIntegration(unittest.TestCase):
    def test_get_opencode_auth_keys_from_auth_file(self):
        with TemporaryDirectory() as tmpdir:
            auth_dir = Path(tmpdir) / ".local" / "share" / "opencode"
            auth_dir.mkdir(parents=True, exist_ok=True)
            auth_file = auth_dir / "auth.json"
            auth_file.write_text(
                json.dumps({
                    "nvidia": {
                        "type": "api",
                        "key": "sk-or-v1-mock-key-12345"
                    }
                }),
                encoding="utf-8"
            )

            with patch.dict(os.environ, {"USERPROFILE": tmpdir, "HOME": tmpdir}):
                keys = get_opencode_auth_keys()
                self.assertIn("nvidia", keys)
                self.assertEqual(keys["nvidia"], "sk-or-v1-mock-key-12345")

    def test_catalog_fallback_to_opencode_auth(self):
        with TemporaryDirectory() as tmpdir:
            auth_dir = Path(tmpdir) / ".local" / "share" / "opencode"
            auth_dir.mkdir(parents=True, exist_ok=True)
            auth_file = auth_dir / "auth.json"
            auth_file.write_text(
                json.dumps({
                    "nvidia": {
                        "type": "api",
                        "key": "sk-or-v1-test-abcde-99999"
                    }
                }),
                encoding="utf-8"
            )

            mock_cfg = {
                "engines": [
                    {
                        "name": "opencode-nvidia",
                        "command": "opencode",
                        "model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
                        "api_keys": ["${NVIDIA_API_KEY_1}"]
                    }
                ]
            }

            with patch.dict(os.environ, {"USERPROFILE": tmpdir, "HOME": tmpdir}):
                # Pass empty env so .env has nothing
                catalog = get_keys_catalog(mock_cfg, env_vars={})
                p = catalog["providers"][0]
                self.assertTrue(p["has_configured_key"])
                key_detail = p["keys"][0]
                self.assertTrue(key_detail["configured"])
                self.assertEqual(key_detail["source"], "opencode_auth")
                self.assertIn("[OpenCode Auth]", key_detail["masked"])


if __name__ == "__main__":
    unittest.main()

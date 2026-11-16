"""ปุ่ม "ดึงโมเดลจาก API" ส่งชื่อ engine (เช่น nvidia-nemotron) มาที่ /api/models.

บั๊กเดิม: keys.fetch_provider_models หาคีย์และ endpoint จากชื่อ catalog (opencode-*)
ไม่ใช่ชื่อ engine → ขึ้น "ไม่พบ API Key" ทั้งที่คีย์มีอยู่ และ NVIDIA ไม่มี endpoint.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

from auto_dev_crew import gui, keys

NVIDIA_KEY = "nvapi-" + "t" * 40


def _cfg():
    return {
        "engines": [
            {
                "name": "nvidia-nemotron",
                "auth_provider": "nvidia",
                "provider": "NVIDIA build",
                "command": "opencode",
                "model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
                "api_keys": ["${NVIDIA_API_KEY_1}"],
            },
        ]
    }


def _fake_urlopen(payload, seen):
    def _open(req, timeout=None):
        seen.append(req)
        cm = MagicMock()
        cm.read.return_value = json.dumps(payload).encode("utf-8")
        cm.__enter__.return_value = cm
        return cm
    return _open


class TestApiModelsResolvesEngine(unittest.TestCase):
    def setUp(self):
        for p in (
            patch("auto_dev_crew.key_ping.load_dotenv", return_value={"NVIDIA_API_KEY_1": NVIDIA_KEY}),
            patch("auto_dev_crew.key_ping.get_opencode_auth_keys", return_value={}),
            patch("auto_dev_crew.keys.get_opencode_auth_keys", return_value={}),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_engine_name_uses_its_env_key_and_nvidia_endpoint(self):
        seen = []
        payload = {"data": [{"id": "nvidia/nemotron-3-ultra-550b-a55b"}, {"id": "nvidia/some-embed-model"}]}
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen(payload, seen)):
            res = gui._api_models({"provider": "nvidia-nemotron"}, _cfg())
        self.assertTrue(res["ok"])
        self.assertIn("nvidia/nemotron-3-ultra-550b-a55b", res["models"])
        self.assertFalse(any("embed" in m for m in res["models"]))
        req = seen[0]
        self.assertEqual(req.full_url, "https://integrate.api.nvidia.com/v1/models")
        self.assertEqual(req.get_header("Authorization"), f"Bearer {NVIDIA_KEY}")

    def test_catalog_id_still_works(self):
        seen = []
        payload = {"data": [{"id": "llama-3.1-8b-instant"}]}
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen(payload, seen)):
            res = gui._api_models({"provider": "opencode-groq", "key": "gsk_test"}, _cfg())
        self.assertEqual(res["models"], ["groq/llama-3.1-8b-instant"])

    def test_engine_with_unknown_auth_provider_uses_model_provider_endpoint(self):
        cfg = {"engines": [{
            "name": "pollinations-deepseek", "auth_provider": "pollinations-deepseek",
            "command": "opencode", "model": "pollinations/deepseek/deepseek-v4.1-flash",
            "api_keys": ["${NVIDIA_API_KEY_1}"],
        }]}
        seen = []
        payload = [{"name": "deepseek/deepseek-v4.1-flash"}]  # รูปแบบของ gen.pollinations.ai/models คือ list + name
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen(payload, seen)):
            res = gui._api_models({"provider": "pollinations-deepseek", "key": "sk_test"}, cfg)
        self.assertEqual(seen[0].full_url, "https://gen.pollinations.ai/models")
        self.assertIn("pollinations/deepseek/deepseek-v4.1-flash", res["models"])

    def test_nvidia_endpoint_is_registered(self):
        self.assertIn("opencode-nvidia", keys.PROVIDER_MODEL_ENDPOINTS)


if __name__ == "__main__":
    unittest.main()

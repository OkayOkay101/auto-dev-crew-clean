import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_dev_crew.keys import fetch_provider_models, update_engine_model


class TestFetchModels(unittest.TestCase):
    def test_fetch_provider_models_openai_format(self):
        mock_response = {
            "data": [
                {"id": "llama-3.3-70b-versatile"},
                {"id": "whisper-large-v3"},
                {"id": "llama-3.1-8b-instant"},
                {"id": "text-embedding-3-small"},
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_cm.__enter__.return_value = mock_cm
            mock_urlopen.return_value = mock_cm

            models = fetch_provider_models("opencode-groq", api_key="gsk_test")
            self.assertIn("groq/llama-3.3-70b-versatile", models)
            self.assertIn("groq/llama-3.1-8b-instant", models)
            self.assertFalse(any("whisper" in m for m in models))
            self.assertFalse(any("embedding" in m for m in models))

    def test_fetch_provider_models_unauthorized_error(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            err = urllib.error.HTTPError(
                url="https://api.groq.com/openai/v1/models",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=io.BytesIO(b'{"error": "Invalid API Key"}'),
            )
            mock_urlopen.side_effect = err

            with self.assertRaises(ValueError) as ctx:
                fetch_provider_models("opencode-groq", api_key="invalid_key")
            self.assertIn("ไม่ถูกต้อง", str(ctx.exception))

    @patch("auto_dev_crew.keys.load_env_file", return_value={})
    @patch.dict("os.environ", {}, clear=True)
    def test_fetch_provider_models_missing_key(self, mock_env):
        with self.assertRaises(ValueError) as ctx:
            fetch_provider_models("opencode-groq", api_key="")
        self.assertIn("ไม่พบ API Key", str(ctx.exception))

    def test_update_engine_model(self):
        sample_yaml = """# Config header
engines:
  - name: opencode-groq
    command: opencode
    model: groq/old-model
    enabled: true
  - name: opencode-cerebras
    command: opencode
    model: cerebras/llama3.3-70b
"""
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write(sample_yaml)
            cfg_path = Path(f.name)

        try:
            ok = update_engine_model("opencode-groq", "groq/new-llama-model", cfg_path=cfg_path)
            self.assertTrue(ok)
            content = cfg_path.read_text(encoding="utf-8")
            self.assertIn("# Config header", content)
            self.assertIn("model: groq/new-llama-model", content)
            self.assertIn("cerebras/llama3.3-70b", content)
        finally:
            if cfg_path.exists():
                cfg_path.unlink()

    def test_gui_act_models_endpoint(self):
        from auto_dev_crew import gui

        with patch("auto_dev_crew.keys.fetch_provider_models", return_value=["groq/test-model-1"]):
            res = gui.act("/api/models", {"provider": "opencode-groq"})
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("models"), ["groq/test-model-1"])

    def test_gui_act_engine_model(self):
        from auto_dev_crew import gui

        with patch("auto_dev_crew.keys.update_engine_model", return_value=True) as mock_update:
            res = gui.act("/api/engine-model", {"name": "opencode-groq", "model": "groq/llama-new"})
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("model"), "groq/llama-new")
            mock_update.assert_called_once_with("opencode-groq", "groq/llama-new")


if __name__ == "__main__":
    unittest.main()

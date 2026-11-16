import tempfile
import unittest
from pathlib import Path
import yaml

from auto_dev_crew import gui, runner, keys


class TestGuiEvaluation(unittest.TestCase):
    def test_evaluation_toggle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            cfg_path = tmp_root / "config.yaml"
            cfg_path.write_text("evaluation:\n  enabled: true\n  engine: auto\n", encoding="utf-8")

            orig_runner_root = runner.ROOT
            orig_keys_root = keys.ROOT
            try:
                runner.ROOT = tmp_root
                keys.ROOT = tmp_root

                # 1. Toggle off
                res = gui.act("/api/evaluation/toggle", {})
                self.assertTrue(res["ok"])
                self.assertFalse(res["enabled"])

                raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                self.assertFalse(raw["evaluation"]["enabled"])

                # 2. Toggle back on explicitly
                res2 = gui.act("/api/evaluation/toggle", {"enabled": True})
                self.assertTrue(res2["ok"])
                self.assertTrue(res2["enabled"])

                raw2 = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                self.assertTrue(raw2["evaluation"]["enabled"])
            finally:
                runner.ROOT = orig_runner_root
                keys.ROOT = orig_keys_root

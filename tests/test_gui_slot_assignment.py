import unittest
from unittest.mock import patch
from pathlib import Path
import yaml

from auto_dev_crew.gui import _api_slots_assign


class TestGuiSlotAssignment(unittest.TestCase):
    def test_api_slots_assign(self, tmp_path_factory=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cfg = Path(tmpdir) / "config.yaml"
            tmp_cfg.write_text("parallel:\n  slots: 3\n", encoding="utf-8")

            with patch("auto_dev_crew.runner.ROOT", Path(tmpdir)):
                # Assign slot 2
                res = _api_slots_assign({"slot_id": 2, "persona": "quality", "repo": "example-owner/example-repo-2"}, {})
                self.assertTrue(res["ok"])
                self.assertIn("slot_2", res["assignments"])
                self.assertEqual(res["assignments"]["slot_2"]["persona"], "quality")

                # Verify written to config.yaml
                content = yaml.safe_load(tmp_cfg.read_text(encoding="utf-8"))
                self.assertEqual(content["parallel"]["assignments"]["slot_2"]["persona"], "quality")
                self.assertEqual(content["parallel"]["assignments"]["slot_2"]["repo"], "example-owner/example-repo-2")

                # Clear assignment
                res_clear = _api_slots_assign({"slot_id": 2, "persona": "auto", "repo": "auto"}, {})
                self.assertTrue(res_clear["ok"])
                self.assertNotIn("slot_2", res_clear["assignments"])


if __name__ == "__main__":
    unittest.main()

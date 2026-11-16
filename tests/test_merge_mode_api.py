"""/api/merge-mode: the GUI sets merge_mode only to a known value and keeps the rest of the config."""
import tempfile
import unittest
from pathlib import Path

import yaml

from auto_dev_crew import gui


SAMPLE = {"owner": "o", "merge_mode": "merge-all", "engines": [{"name": "e1", "enabled": True}]}


class TestMergeModeApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8", suffix=".yaml")
        yaml.safe_dump(SAMPLE, self.tmp, allow_unicode=True, sort_keys=False)
        self.tmp.close()
        self.path = Path(self.tmp.name)
        gui.set_config_path(self.path)

    def tearDown(self):
        gui.set_config_path(None)
        self.path.unlink(missing_ok=True)

    def _saved(self):
        return yaml.safe_load(self.path.read_text(encoding="utf-8"))

    def test_sets_review_all_and_keeps_other_keys(self):
        res = gui._api_merge_mode({"mode": "review-all"}, {})
        self.assertTrue(res["ok"])
        self.assertEqual(res["previous"], "merge-all")
        saved = self._saved()
        self.assertEqual(saved["merge_mode"], "review-all")
        self.assertEqual(saved["owner"], "o")
        self.assertEqual(saved["engines"], SAMPLE["engines"])

    def test_accepts_small_only(self):
        gui._api_merge_mode({"mode": "small-only"}, {})
        self.assertEqual(self._saved()["merge_mode"], "small-only")

    def test_rejects_unknown_mode_and_leaves_file_unchanged(self):
        with self.assertRaises(ValueError):
            gui._api_merge_mode({"mode": "yolo"}, {})
        with self.assertRaises(ValueError):
            gui._api_merge_mode({}, {})
        self.assertEqual(self._saved()["merge_mode"], "merge-all")

    def test_route_is_registered(self):
        self.assertIs(gui.ROUTES["/api/merge-mode"], gui._api_merge_mode)


if __name__ == "__main__":
    unittest.main()

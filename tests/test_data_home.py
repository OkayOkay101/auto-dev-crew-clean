"""Data-dir migration and browser-storage compatibility after the ai-optimizer -> Auto Dev Crew rename."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew.data_home import resolve_data_home

STATIC = Path(__file__).resolve().parents[1] / "auto_dev_crew" / "static"


class ResolveDataHomeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_install_returns_new_dir_without_creating_it(self):
        self.assertEqual(resolve_data_home(self.home), self.home / ".auto-dev-crew")
        self.assertFalse((self.home / ".auto-dev-crew").exists())

    def test_legacy_folder_is_moved_once_and_venvs_set_aside(self):
        legacy = self.home / ".ai-optimizer"
        (legacy / "work").mkdir(parents=True)
        (legacy / "work" / "keep.txt").write_text("x", encoding="utf-8")
        (legacy / "venvs" / "repo1").mkdir(parents=True)
        result = resolve_data_home(self.home)
        self.assertEqual(result, self.home / ".auto-dev-crew")
        self.assertTrue((result / "work" / "keep.txt").exists())
        self.assertFalse(legacy.exists())
        self.assertFalse((result / "venvs").exists())  # venv launchers embed the old path
        self.assertTrue((result / "venvs.moved" / "repo1").exists())  # nothing deleted

    def test_existing_new_folder_wins_and_legacy_is_left_alone(self):
        legacy = self.home / ".ai-optimizer"
        legacy.mkdir()
        new = self.home / ".auto-dev-crew"
        new.mkdir()
        self.assertEqual(resolve_data_home(self.home), new)
        self.assertTrue(legacy.exists())

    def test_failed_rename_keeps_using_legacy_folder(self):
        legacy = self.home / ".ai-optimizer"
        legacy.mkdir()
        with mock.patch("auto_dev_crew.data_home.os.replace", side_effect=PermissionError("locked")):
            self.assertEqual(resolve_data_home(self.home), legacy)
        self.assertTrue(legacy.exists())
        self.assertFalse((self.home / ".auto-dev-crew").exists())


class StoredStateFallbackTests(unittest.TestCase):
    def test_both_pages_read_legacy_keys_as_fallback(self):
        for name in ("index.html", "index_sidebar.html"):
            html = (STATIC / name).read_text(encoding="utf-8")
            self.assertIn("'ai_optimizer_' + key.slice('auto_dev_crew_'.length)", html, name)
            self.assertIn('loadStoredState("auto_dev_crew_cached_models"', html, name)


if __name__ == "__main__":
    unittest.main()

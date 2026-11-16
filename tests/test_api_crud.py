import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.keys import (
    add_engine,
    get_engine,
    list_engines,
    update_engine,
    delete_engine,
    reorder_engines,
    load_favorite_keys,
    save_favorite_keys,
    toggle_favorite_key,
)
from auto_dev_crew.runner import (
    save_engine_status,
    mark_engine_quota,
    load_engine_status,
)
from auto_dev_crew import gui


SAMPLE_CONFIG = """
owner: example-owner
engines:
  - name: test-engine-1
    provider: Provider One
    command: agy
    model: gemini-3.8-flash
    timeout_minutes: 30
    trains_on_data: false
    enabled: true

  - name: test-engine-2
    provider: Provider Two
    command: opencode
    model: test-model-2
    timeout_minutes: 15
    trains_on_data: true
    enabled: false
    api_keys:
      - ${TEST_KEY_1}
"""


class TestApiCrud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8")
        self.tmp.write(SAMPLE_CONFIG)
        self.tmp.close()
        self.cfg_path = Path(self.tmp.name)
        save_engine_status({})

    def tearDown(self):
        self.cfg_path.unlink(missing_ok=True)

    def test_list_engines(self):
        engines = list_engines(cfg_path=self.cfg_path)
        self.assertEqual(len(engines), 2)
        self.assertEqual(engines[0]["name"], "test-engine-1")
        self.assertEqual(engines[1]["name"], "test-engine-2")

    def test_get_engine(self):
        eng = get_engine("test-engine-1", cfg_path=self.cfg_path)
        self.assertIsNotNone(eng)
        self.assertEqual(eng["provider"], "Provider One")
        self.assertEqual(eng["model"], "gemini-3.8-flash")
        self.assertTrue(eng["enabled"])

        none_eng = get_engine("non-existent", cfg_path=self.cfg_path)
        self.assertIsNone(none_eng)

    def test_add_engine(self):
        new_data = {
            "name": "test-engine-3",
            "provider": "Provider Three",
            "command": "opencode",
            "model": "deepseek/deepseek-v4",
            "timeout_minutes": 20,
            "trains_on_data": False,
            "enabled": True,
            "api_keys": ["${KEY_3}"],
        }
        res = add_engine(new_data, cfg_path=self.cfg_path)
        self.assertTrue(res)

        engines = list_engines(cfg_path=self.cfg_path)
        self.assertEqual(len(engines), 3)
        self.assertEqual(engines[2]["name"], "test-engine-3")
        self.assertEqual(engines[2]["model"], "deepseek/deepseek-v4")

        # Duplicate name should raise ValueError
        with self.assertRaises(ValueError):
            add_engine(new_data, cfg_path=self.cfg_path)

        # Missing required field
        with self.assertRaises(ValueError):
            add_engine({"name": "no-model", "command": "agy"}, cfg_path=self.cfg_path)

    def test_update_engine(self):
        updates = {
            "model": "gemini-3.8-pro",
            "timeout_minutes": 45,
            "enabled": False,
        }
        ok = update_engine("test-engine-1", updates, cfg_path=self.cfg_path)
        self.assertTrue(ok)

        eng = get_engine("test-engine-1", cfg_path=self.cfg_path)
        self.assertEqual(eng["model"], "gemini-3.8-pro")
        self.assertEqual(eng["timeout_minutes"], 45)
        self.assertFalse(eng["enabled"])

        # Rename engine
        ok_rename = update_engine("test-engine-1", {"name": "renamed-engine-1"}, cfg_path=self.cfg_path)
        self.assertTrue(ok_rename)
        self.assertIsNone(get_engine("test-engine-1", cfg_path=self.cfg_path))
        self.assertIsNotNone(get_engine("renamed-engine-1", cfg_path=self.cfg_path))

    def test_delete_engine(self):
        mark_engine_quota("test-engine-1", cooldown_hours=2.0)
        status_before = load_engine_status()
        self.assertIn("test-engine-1", status_before)

        ok = delete_engine("test-engine-1", cfg_path=self.cfg_path)
        self.assertTrue(ok)

        engines = list_engines(cfg_path=self.cfg_path)
        self.assertEqual(len(engines), 1)
        self.assertEqual(engines[0]["name"], "test-engine-2")

        # Cooldown record should be removed
        status_after = load_engine_status()
        self.assertNotIn("test-engine-1", status_after)

    def test_reorder_engines(self):
        ok = reorder_engines(["test-engine-2", "test-engine-1"], cfg_path=self.cfg_path)
        self.assertTrue(ok)

        engines = list_engines(cfg_path=self.cfg_path)
        self.assertEqual(engines[0]["name"], "test-engine-2")
        self.assertEqual(engines[1]["name"], "test-engine-1")

    def test_favorite_keys(self):
        # Initial empty or reset
        save_favorite_keys(set())
        favs = load_favorite_keys()
        self.assertNotIn("GROQ_API_KEY_1", favs)

        # Toggle on
        res = toggle_favorite_key("GROQ_API_KEY_1", True)
        self.assertTrue(res)
        favs = load_favorite_keys()
        self.assertIn("GROQ_API_KEY_1", favs)

        # Toggle off
        res = toggle_favorite_key("GROQ_API_KEY_1", False)
        self.assertFalse(res)
        favs = load_favorite_keys()
        self.assertNotIn("GROQ_API_KEY_1", favs)

        # Toggle via API endpoint
        res = gui.act("/api/key/favorite", {"key": "opencode-groq", "favorite": True})
        self.assertTrue(res.get("ok"))
        self.assertTrue(res.get("favorite"))
        favs = load_favorite_keys()
        self.assertIn("opencode-groq", favs)

        res = gui.act("/api/key/favorite", {"key": "opencode-groq", "favorite": False})
        self.assertTrue(res.get("ok"))
        self.assertFalse(res.get("favorite"))

    def test_gui_actions(self):
        # Test act() in gui.py. The GUI no longer accepts cfg_path from the client (MED-14),
        # so the config under test is supplied by pointing keys.ROOT at a temp folder.
        import shutil
        from unittest.mock import patch
        from auto_dev_crew import keys as keys_mod
        tmp_root = Path(tempfile.mkdtemp())
        try:
            shutil.copy(self.cfg_path, tmp_root / "config.yaml")
            with patch.object(keys_mod, "ROOT", tmp_root):
                self._run_gui_actions(tmp_root / "config.yaml")
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def _run_gui_actions(self, cfg):
        # 1. create
        res = gui.act("/api/engine/create", {
            "name": "gui-created",
            "provider": "GUI Provider",
            "command": "opencode",
            "model": "opencode/gui-model",
        })
        self.assertTrue(res.get("ok"))
        self.assertIsNotNone(get_engine("gui-created", cfg_path=cfg))

        # 2. update
        res = gui.act("/api/engine/update", {
            "name": "gui-created",
            "updates": {"model": "opencode/updated-gui-model"},
        })
        self.assertTrue(res.get("ok"))
        self.assertEqual(get_engine("gui-created", cfg_path=cfg)["model"], "opencode/updated-gui-model")

        # 3. reorder
        res = gui.act("/api/engine/reorder", {
            "order": ["gui-created", "test-engine-1", "test-engine-2"],
        })
        self.assertTrue(res.get("ok"))
        engines = list_engines(cfg_path=cfg)
        self.assertEqual(engines[0]["name"], "gui-created")

        # 4. delete
        res = gui.act("/api/engine/delete", {
            "name": "gui-created",
        })
        self.assertTrue(res.get("ok"))
        self.assertIsNone(get_engine("gui-created", cfg_path=cfg))

    def test_gui_html_crud_and_favorite_elements(self):
        html_path = Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html"
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('id="openNewEngineBtn"', html)
        self.assertIn('<dialog id="newEngineDlg"', html)
        self.assertIn('<dialog id="editEngineDlg"', html)
        self.assertIn('id="saveNewEngineBtn"', html)
        self.assertIn('id="saveEditEngineBtn"', html)
        self.assertIn('data-edit-engine=', html)
        self.assertIn('data-delete-engine=', html)
        self.assertIn('data-engine-up=', html)
        self.assertIn('data-engine-down=', html)
        self.assertIn('id="favoriteFilterBtn"', html)
        self.assertIn('data-toggle-fav=', html)
        self.assertIn('id="countFavorite"', html)
        self.assertIn('/api/engine/create', html)
        self.assertIn('/api/engine/update', html)
        self.assertIn('/api/engine/delete', html)
        self.assertIn('/api/engine/reorder', html)
        self.assertIn('/api/key/favorite', html)


if __name__ == "__main__":
    unittest.main()

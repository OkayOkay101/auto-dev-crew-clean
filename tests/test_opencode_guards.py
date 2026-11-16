"""Regression guards for the OpenCode engine: model must be provider/model, and the
workspace schema drift in opencode.db must be detected/repaired safely."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew import keys, opencode_db

OLD_WORKSPACE = """CREATE TABLE workspace (
  id text PRIMARY KEY, provider text NOT NULL, binding text,
  created_at integer NOT NULL, last_used_at integer NOT NULL)"""


class ModelFormatGuardTests(unittest.TestCase):
    def test_bare_model_rejected_for_opencode(self):
        with self.assertRaises(ValueError):
            keys._check_engine_model("opencode", "nemotron-3.5-super-vl-free")

    def test_prefixed_model_accepted(self):
        keys._check_engine_model("opencode", "opencode/nemotron-3.5-super-vl-free")

    def test_other_commands_not_checked(self):
        keys._check_engine_model("agy", "gemini-3.8-flash-high")

    def test_update_engine_rejects_bare_model_and_keeps_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.yaml"
            cfg.write_text(
                "engines:\n- name: oc\n  command: opencode\n  model: opencode/a-model\n  enabled: true\n",
                encoding="utf-8")
            with self.assertRaises(ValueError):
                keys.update_engine("oc", {"model": "a-model"}, cfg_path=cfg)
            self.assertIn("model: opencode/a-model", cfg.read_text(encoding="utf-8"))
            self.assertTrue(keys.update_engine("oc", {"model": "opencode/b-model"}, cfg_path=cfg))
            self.assertIn("model: opencode/b-model", cfg.read_text(encoding="utf-8"))


class WorkspaceRepairTests(unittest.TestCase):
    def _make_db(self, root: Path, rows: int = 0) -> Path:
        db = root / "opencode.db"
        conn = sqlite3.connect(db)
        conn.executescript(f"""
            CREATE TABLE project (id text PRIMARY KEY);
            {OLD_WORKSPACE};
        """)
        for i in range(rows):
            conn.execute("INSERT INTO workspace VALUES (?, 'p', NULL, 0, 0)", (f"w{i}",))
        conn.commit()
        conn.close()
        return db

    def test_detects_old_schema_and_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            db = self._make_db(Path(d))
            rep = opencode_db.repair(db, apply=False)
            self.assertTrue(rep["needs_repair"])
            self.assertFalse(rep["applied"])
            conn = sqlite3.connect(db)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(workspace)")}
            conn.close()
            self.assertNotIn("project_id", cols)

    def test_apply_repairs_empty_table_and_backs_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = self._make_db(root)
            rep = opencode_db.repair(db, backup_dir=root / "bk", apply=True)
            self.assertTrue(rep["applied"])
            self.assertTrue(Path(rep["backup"]).exists())
            conn = sqlite3.connect(db)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(workspace)")}
            conn.close()
            self.assertIn("project_id", cols)
            self.assertFalse(opencode_db.diagnose(db)["needs_repair"])

    def test_refuses_to_touch_table_with_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            db = self._make_db(root, rows=2)
            rep = opencode_db.repair(db, backup_dir=root / "bk", apply=True)
            self.assertFalse(rep["applied"])
            self.assertIsNone(rep["backup"])
            conn = sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM workspace").fetchone()[0], 2)
            conn.close()


if __name__ == "__main__":
    unittest.main()

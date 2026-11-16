import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew.slots import SlotRegistry


class TestSlots(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "scratch_slots"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.registry = SlotRegistry(state_dir=self.test_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_slot_registry_lifecycle(self):
        self.assertFalse(self.registry.is_job_active("persona", "bolt"))
        
        self.registry.register_slot(
            slot_id=1,
            kind="persona",
            key="bolt",
            branch="ai/bolt-123",
            active_files=["data_handler.py"]
        )
        self.assertTrue(self.registry.is_job_active("persona", "bolt"))
        self.assertEqual(self.registry.get_colliding_files(excluding_slot_id=2), {"data_handler.py"})
        self.assertEqual(self.registry.get_colliding_files(excluding_slot_id=1), set())

        # Update files
        self.registry.update_active_files(slot_id=1, files=["data_handler.py", "utils.py"])
        self.assertEqual(
            self.registry.get_colliding_files(excluding_slot_id=2),
            {"data_handler.py", "utils.py"}
        )

        # Release slot
        self.registry.release_slot(1)
        self.assertFalse(self.registry.is_job_active("persona", "bolt"))
        self.assertEqual(self.registry.get_colliding_files(excluding_slot_id=2), set())

    def test_slot_registry_no_duplicate_persona(self):
        self.registry.register_slot(2, "persona", "bolt", "ai/bolt-1", [])
        self.assertTrue(self.registry.is_job_active("persona", "bolt"))
        self.assertFalse(self.registry.is_job_active("persona", "sentinel"))

    def test_is_job_active_excluding_own_slot(self):
        self.registry.register_slot(2, "persona", "bolt", "ai/bolt-1", [])
        self.assertTrue(self.registry.is_job_active("persona", "bolt"))
        self.assertFalse(self.registry.is_job_active("persona", "bolt", excluding_slot_id=2))
        self.assertTrue(self.registry.is_job_active("persona", "bolt", excluding_slot_id=3))

    def test_slot_state_and_summary(self):
        self.registry.register_slot(1, "issue", "42", "ai/issue-42", ["app.py"])
        self.registry.update_slot_state(1, "testing")
        jobs = self.registry.get_active_jobs()
        self.assertIn("slot_1", jobs)
        self.assertEqual(jobs["slot_1"]["state"], "testing")
        self.assertEqual(jobs["slot_1"]["key"], "42")


if __name__ == "__main__":
    unittest.main()

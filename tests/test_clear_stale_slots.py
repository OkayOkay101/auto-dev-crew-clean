"""GUI startup drops slot entries left behind by a runner that was killed."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import gui, runner
from auto_dev_crew.slots import SlotRegistry


class TestClearStaleSlots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.registry = SlotRegistry(self.dir)
        self.registry.register_slot(2, "persona", "bolt", "ai/bolt-test", ["a.py"])
        self.patch = mock.patch.object(runner, "REGISTRY", self.registry)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_stale_entry_is_removed_on_start(self):
        self.assertIn("slot_2", json.loads((self.dir / "active_slots.json").read_text(encoding="utf-8")))
        gui._clear_stale_slots()
        self.assertEqual(json.loads((self.dir / "active_slots.json").read_text(encoding="utf-8")), {})

    def test_no_file_is_fine(self):
        (self.dir / "active_slots.json").unlink()
        gui._clear_stale_slots()
        self.assertEqual(self.registry.get_active_jobs(), {})


if __name__ == "__main__":
    unittest.main()

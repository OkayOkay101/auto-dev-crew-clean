import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_dev_crew import gui, runner
from auto_dev_crew.slots import SlotRegistry


class TestStopReleasesSlots(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.registry = SlotRegistry(state_dir=self.tmp)
        self.registry.register_slot(1, "persona", "bolt", "ai/bolt-1", ["a.py"])
        self.registry.register_slot(2, "issue", "5", "ai/issue-5", [])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stop_clears_stale_slots_after_runner_killed(self):
        agent = gui.Agent()
        fake_proc = MagicMock()
        fake_proc.pid = 4242
        fake_proc.poll.return_value = None  # still running
        agent.proc = fake_proc
        with patch.object(runner, "REGISTRY", self.registry), patch("auto_dev_crew.gui.subprocess.run"):
            agent.stop()
        self.assertEqual(self.registry.get_active_jobs(), {})

    def test_stop_when_not_running_keeps_registry(self):
        agent = gui.Agent()  # no proc at all
        with patch.object(runner, "REGISTRY", self.registry):
            agent.stop()
        self.assertEqual(len(self.registry.get_active_jobs()), 2)


if __name__ == "__main__":
    unittest.main()

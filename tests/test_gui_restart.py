import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew import gui


class TestGuiRestart(unittest.TestCase):
    def test_agent_restart_when_running(self):
        agent = gui.Agent()
        mock_proc = mock.MagicMock()
        mock_proc.poll.return_value = None  # running
        agent.proc = mock_proc
        agent.args = ["--loop", "--repo", "owner/repo1"]

        with mock.patch.object(agent, "stop") as mock_stop, \
             mock.patch.object(agent, "start") as mock_start:
            target = agent.restart(["--loop", "--repo", "owner/repo2"])
            self.assertEqual(target, ["--loop", "--repo", "owner/repo2"])
            mock_stop.assert_called_once()
            mock_start.assert_called_once_with(["--loop", "--repo", "owner/repo2"])

    def test_agent_restart_when_idle(self):
        agent = gui.Agent()
        agent.proc = None
        agent.args = []

        with mock.patch.object(agent, "stop") as mock_stop, \
             mock.patch.object(agent, "start") as mock_start:
            target = agent.restart()
            self.assertEqual(target, ["--loop"])
            mock_stop.assert_not_called()
            mock_start.assert_called_once_with(["--loop"])

    def test_act_api_restart_with_custom_body(self):
        # Restart with --loop must NOT turn AutoPilot on: the user starts runs manually.
        with mock.patch.object(gui.AGENT, "restart", return_value=["--loop", "--repo", "test/repo"]) as mock_restart, \
             mock.patch.object(gui.AUTO, "enable") as mock_auto_enable, \
             mock.patch.object(gui, "load_cfg", return_value={"repos": [{"name": "test/repo"}]}):
            res = gui.act("/api/restart", {"loop": True, "repo": "test/repo"})
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("args"), ["--loop", "--repo", "test/repo"])
            mock_restart.assert_called_once_with(["--loop", "--repo", "test/repo"])
            mock_auto_enable.assert_not_called()

    def test_act_api_restart_preserves_args_and_disables_auto_if_not_loop(self):
        with mock.patch.object(gui.AGENT, "restart", return_value=["--dry-run", "--persona", "bolt"]) as mock_restart, \
             mock.patch.object(gui.AUTO, "disable") as mock_auto_disable:
            res = gui.act("/api/restart", {"dry_run": True, "persona": "bolt"})
            self.assertTrue(res.get("ok"))
            self.assertEqual(res.get("args"), ["--dry-run", "--persona", "bolt"])
            mock_restart.assert_called_once_with(["--dry-run", "--persona", "bolt"])
            mock_auto_disable.assert_called_once()

    def test_concurrent_start_spawns_once(self):
        import threading
        import time

        agent = gui.Agent()
        spawned = []
        spawn_lock = threading.Lock()

        def slow_popen(*args, **kwargs):
            time.sleep(0.05)  # widen the check-then-spawn window
            proc = mock.MagicMock()
            proc.poll.return_value = None
            proc.stdout = iter([])
            with spawn_lock:
                spawned.append(proc)
            return proc

        barrier = threading.Barrier(10)
        errors = []

        def worker():
            barrier.wait()
            try:
                agent.start(["--loop"])
            except RuntimeError:
                errors.append("busy")

        with mock.patch.object(gui.subprocess, "Popen", side_effect=slow_popen):
            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        self.assertEqual(len(spawned), 1)
        self.assertEqual(len(errors), 9)

    def test_act_api_restart_invalid_persona_raises(self):
        with self.assertRaises(ValueError):
            gui.act("/api/restart", {"persona": "non_existent_persona"})


if __name__ == "__main__":
    unittest.main()

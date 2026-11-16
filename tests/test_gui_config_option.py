import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_dev_crew import gui, runner


class TestGuiConfigOption(unittest.TestCase):
    """F-9: the GUI must be able to read and write a config other than ROOT/config.yaml."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.custom = self.tmp / "temp-config.yaml"
        self.custom.write_text("repos: []\nengines: []\n", encoding="utf-8")
        self._saved = gui._CONFIG_OVERRIDE

    def tearDown(self):
        gui.set_config_path(self._saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_path_is_root_config(self):
        self.assertEqual(gui.config_path(), runner.ROOT / "config.yaml")

    def test_load_cfg_reads_the_chosen_file(self):
        gui.set_config_path(self.custom)
        self.assertEqual(gui.load_cfg(), {"repos": [], "engines": []})

    def test_agent_passes_config_to_runner_when_custom(self):
        gui.set_config_path(self.custom)
        fake = MagicMock()
        fake.stdout = iter([])
        fake.poll.return_value = 0
        with patch("auto_dev_crew.gui.subprocess.Popen", return_value=fake) as popen, \
                patch.object(gui, "RUNS", self.tmp / "runs"):
            agent = gui.Agent()
            agent.start(["--loop", "--dry-run"])
        cmd = popen.call_args.args[0]
        self.assertIn("--config", cmd)
        self.assertEqual(cmd[cmd.index("--config") + 1], str(self.custom))

    def test_agent_adds_no_config_flag_for_default_path(self):
        gui.set_config_path(None)
        fake = MagicMock()
        fake.stdout = iter([])
        fake.poll.return_value = 0
        with patch("auto_dev_crew.gui.subprocess.Popen", return_value=fake) as popen, \
                patch.object(gui, "RUNS", self.tmp / "runs"):
            agent = gui.Agent()
            agent.start(["--loop"])
        self.assertNotIn("--config", popen.call_args.args[0])

    def test_engine_writes_go_to_chosen_file_not_root_config(self):
        """Live-run finding: engine delete/add/update still wrote ROOT/config.yaml with --config set."""
        root = self.tmp / "root"
        root.mkdir()
        real = root / "config.yaml"
        real.write_text(
            "engines:\n- name: opencode-real\n  command: opencode\n  enabled: true\n", encoding="utf-8")
        custom = self.tmp / "custom.yaml"
        custom.write_text(
            "engines:\n- name: opencode-x\n  command: opencode\n  enabled: true\n"
            "- name: opencode-y\n  command: opencode\n  enabled: true\n", encoding="utf-8")
        real_before = real.read_text(encoding="utf-8")
        gui.set_config_path(custom)
        with patch.object(runner, "ROOT", root), patch.object(runner, "STATE", self.tmp / "state"):
            res = gui.act("/api/engine/delete", {"name": "opencode-x"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(real.read_text(encoding="utf-8"), real_before)
        self.assertNotIn("opencode-x", custom.read_text(encoding="utf-8"))
        self.assertIn("opencode-y", custom.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

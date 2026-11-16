"""Tests for the autonomous mode on/off/status control (spec section 3.3)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import autonomous_common as common  # noqa: E402
import autonomous_ctl as ctl  # noqa: E402


class EnableTests(unittest.TestCase):
    def test_enable_writes_flag_and_mission_and_resets_counter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            common.write_counter(root, 17)  # stale counter from an earlier run
            ctl.enable(root, "เพิ่มเทสต์ให้ triage.py")
            self.assertTrue(common.is_enabled(root))
            self.assertIn("เพิ่มเทสต์ให้ triage.py", common.mission_path(root).read_text(encoding="utf-8"))
            self.assertEqual(common.read_counter(root), 0)

    def test_enable_rejects_empty_mission(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ctl.enable(Path(d), "   ")
            self.assertFalse(common.is_enabled(Path(d)))


class DisableTests(unittest.TestCase):
    def test_disable_removes_flag_and_logs_reason(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ctl.enable(root, "งาน X")
            self.assertTrue(ctl.disable(root, "ผู้ใช้สั่งหยุด"))
            self.assertFalse(common.is_enabled(root))
            text = common.mission_path(root).read_text(encoding="utf-8")
            self.assertIn("ผู้ใช้สั่งหยุด", text)

    def test_disable_when_already_off_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(ctl.disable(Path(d), "หยุด"))


class StatusTests(unittest.TestCase):
    def test_status_reports_state_turns_and_cap(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(ctl.status(root), {"enabled": False, "turns": 0, "max_turns": 40})
            ctl.enable(root, "งาน Y")
            common.write_counter(root, 5)
            self.assertEqual(ctl.status(root), {"enabled": True, "turns": 5, "max_turns": 40})


class CliTests(unittest.TestCase):
    def test_on_then_off_via_cli_main(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            import os

            old = os.environ.get("AUTONOMOUS_ROOT")
            os.environ["AUTONOMOUS_ROOT"] = str(root)
            try:
                self.assertEqual(ctl.main(["on", "--mission", "งาน Z"]), 0)
                self.assertTrue(common.is_enabled(root))
                self.assertEqual(ctl.main(["off", "--reason", "จบงาน"]), 0)
                self.assertFalse(common.is_enabled(root))
                self.assertEqual(ctl.main(["status"]), 0)
            finally:
                if old is None:
                    os.environ.pop("AUTONOMOUS_ROOT", None)
                else:
                    os.environ["AUTONOMOUS_ROOT"] = old


if __name__ == "__main__":
    unittest.main()

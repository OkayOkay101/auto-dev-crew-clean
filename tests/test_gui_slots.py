import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew import gui


class TestGuiSlots(unittest.TestCase):
    def test_gui_status_contains_slots(self):
        stat = gui.status()
        self.assertIn("slots", stat)
        self.assertIsInstance(stat["slots"], dict)
        # Should contain entries for configured slots 1, 2, 3
        self.assertIn("slot_1", stat["slots"])
        self.assertIn("slot_2", stat["slots"])
        self.assertIn("slot_3", stat["slots"])
        self.assertIn("activity", stat)
        self.assertIn("is_all_done", stat["activity"])

    def test_system_activity_summary_resting(self):
        cfg = {"personas": {"enabled": ["bolt", "sentinel"]}}
        slots = {"slot_1": {"state": "idle"}, "slot_2": {"state": "idle"}}
        repos = [{"issues": []}]
        # Use a run time just now so the 24-hour rest window is still open, regardless of the clock.
        import datetime as dt
        recent = dt.datetime.now().strftime("%Y%m%d-%H%M")
        history = [
            {"kind": "persona", "key": "bolt", "state": "NO_ACTION", "date": recent},
            {"kind": "persona", "key": "sentinel", "state": "NO_ACTION", "date": recent},
        ]
        summary = gui.system_activity_summary(cfg, slots, repos, history)
        self.assertTrue(summary["is_all_done"])
        self.assertEqual(summary["state"], "all_done")
        self.assertTrue(summary["persona_resting"])
        self.assertTrue(summary["can_wake"])

    def test_wake_personas_action(self):
        # Test wake personas action cleans trailing NO_ACTION
        history = [
            {"kind": "persona", "key": "bolt", "state": "MERGED"},
            {"kind": "persona", "key": "sentinel", "state": "NO_ACTION"},
        ]
        with unittest.mock.patch("auto_dev_crew.runner.load_history", return_value=history.copy()), \
             unittest.mock.patch("auto_dev_crew.runner.save_history") as mock_save:
            res = gui.act("/api/wake-personas", {})
            self.assertTrue(res["ok"])
            mock_save.assert_called_once()
            saved_history = mock_save.call_args[0][0]
            self.assertEqual(len(saved_history), 1)
            self.assertEqual(saved_history[0]["state"], "MERGED")


class TestUsageSummaryRobust(unittest.TestCase):
    def test_usage_summary_skips_bad_lines(self):
        import datetime as dt
        from auto_dev_crew import runner

        today = dt.date.today().isoformat()
        path = runner.STATE / "usage.jsonl"
        path.write_text(
            "this is not json\n"
            "[1, 2, 3]\n"
            f'{{"ts": "{today}T10:00:00", "status": "QUOTA", "tokens": 5, "seconds": 60}}\n',
            encoding="utf-8",
        )
        cfg = {"engines": []}
        summary = gui.usage_summary(cfg)
        self.assertEqual(summary["today"]["calls"], 1)
        self.assertEqual(summary["today"]["tokens"], 5)
        self.assertIsNotNone(summary["last_quota"])


if __name__ == "__main__":
    unittest.main()

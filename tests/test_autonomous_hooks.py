"""Tests for autonomous mode hooks (spec: docs/superpowers/specs/2026-11-09-autonomous-mode-design.md)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import autonomous_common as common  # noqa: E402
import autonomous_guard_hook as guard  # noqa: E402
import autonomous_stop_hook as stop  # noqa: E402


def _make_root(tmp: Path, *, flag: bool, max_turns: int | None = None, turns: int = 0) -> Path:
    (tmp / "state").mkdir(parents=True, exist_ok=True)
    if flag:
        (tmp / "state" / "autonomous.flag").write_text("on", encoding="utf-8")
        (tmp / "state" / "mission.md").write_text("# mission\nทำ X\n", encoding="utf-8")
    if max_turns is not None:
        (tmp / "config.yaml").write_text(
            f"autonomous:\n  max_turns_per_session: {max_turns}\n", encoding="utf-8"
        )
    if turns:
        (tmp / "state" / "autonomous_counter.json").write_text(
            json.dumps({"turns": turns}), encoding="utf-8"
        )
    return tmp


class CommonTests(unittest.TestCase):
    def test_default_max_turns_when_config_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=False)
            self.assertEqual(common.load_settings(root)["max_turns_per_session"], 40)

    def test_reads_max_turns_from_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=False, max_turns=7)
            self.assertEqual(common.load_settings(root)["max_turns_per_session"], 7)

    def test_flag_detection(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=False)
            self.assertFalse(common.is_enabled(root))
            (root / "state" / "autonomous.flag").write_text("on", encoding="utf-8")
            self.assertTrue(common.is_enabled(root))


class StopHookTests(unittest.TestCase):
    def test_allows_stop_when_flag_absent(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=False)
            self.assertIsNone(stop.decide(root, {}))

    def test_blocks_stop_and_increments_counter_when_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True, max_turns=5)
            out = stop.decide(root, {})
            self.assertIsNotNone(out)
            self.assertEqual(out["decision"], "block")
            self.assertIn("state/mission.md", out["reason"])
            counter = json.loads((root / "state" / "autonomous_counter.json").read_text(encoding="utf-8"))
            self.assertEqual(counter["turns"], 1)

    def test_stops_at_cap_and_disables_mode_with_reason(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True, max_turns=3, turns=3)
            self.assertIsNone(stop.decide(root, {}))
            self.assertFalse((root / "state" / "autonomous.flag").exists())
            mission = (root / "state" / "mission.md").read_text(encoding="utf-8")
            self.assertIn("ครบเพดาน", mission)

    def test_invalid_stdin_payload_does_not_trap_user(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True, max_turns=5)
            self.assertIsNotNone(stop.decide(root, {}))  # payload optional
            self.assertIsNone(stop.decide(root, "not-a-dict"))  # malformed -> allow stop


class GuardHookTests(unittest.TestCase):
    def _bash(self, command: str) -> dict:
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def _write(self, tool: str, path: str) -> dict:
        return {"tool_name": tool, "tool_input": {"file_path": path}}

    def _assert_denied(self, out):
        self.assertIsNotNone(out)
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "PreToolUse")
        self.assertEqual(spec["permissionDecision"], "deny")
        self.assertTrue(spec["permissionDecisionReason"])

    def test_allows_everything_when_flag_absent(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=False)
            self.assertIsNone(guard.decide(root, self._bash("git push origin main")))

    def test_denies_irreversible_bash_commands_when_enabled(self):
        denied = [
            "git push origin main",
            "git push --force",
            "gh pr merge 12 --squash",
            "gh release create v1",
            "rm -rf build",
            "git reset --hard HEAD~1",
            "git clean -fdx",
            "./deploy.sh production",
            "Remove-Item -Recurse -Force C:\\x",
        ]
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True)
            for cmd in denied:
                with self.subTest(cmd=cmd):
                    self._assert_denied(guard.decide(root, self._bash(cmd)))

    def test_allows_normal_bash_commands_when_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True)
            for cmd in ["python -m unittest discover -s tests", "git status", "git diff", "ls"]:
                with self.subTest(cmd=cmd):
                    self.assertIsNone(guard.decide(root, self._bash(cmd)))

    def test_denies_self_disable_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True)
            self._assert_denied(guard.decide(root, self._write("Write", "state/autonomous.flag")))
            self._assert_denied(guard.decide(root, self._write("Edit", ".claude/settings.json")))
            self._assert_denied(guard.decide(root, self._write("Write", str(root / "state" / "autonomous.flag"))))

    def test_allows_ordinary_file_edits_when_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = _make_root(Path(d), flag=True)
            self.assertIsNone(guard.decide(root, self._write("Edit", "auto_dev_crew/runner.py")))


if __name__ == "__main__":
    unittest.main()

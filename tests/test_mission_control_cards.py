"""Tests for the Mission Control card: read-only Context Slicer preview endpoint and static UI wiring."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import gui

ROOT_JS = Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "mission_control.js"


class TestContextSlicerPreview(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        body = "\n".join(f"x_{i} = {i}" for i in range(1, 601))
        (self.root / "src" / "big.py").write_text("def f():\n    return 1\n" + body + "\n", encoding="utf-8")
        (self.root / "state").mkdir()
        (self.root / "state" / "history.json").write_text("{}", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN_X=secret", encoding="utf-8")
        self._patch = mock.patch.object(gui.runner, "ROOT", self.root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def _preview(self, **body):
        return gui._api_context_slicer_preview(body, {})

    def test_returns_cited_windows_for_far_line(self):
        out = self._preview(path="src/big.py", reference="ปัญหาอยู่ที่ line 550 ของไฟล์")
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], "src/big.py")
        self.assertIn(550, out["cited_lines"])
        self.assertTrue(any(start <= 550 <= end for start, end in out["windows"]))
        self.assertIn("## Around L550", out["preview"])
        self.assertIn("550 | x_548 = 548", out["preview"])

    def test_small_file_returns_full_numbered_source(self):
        small = self.root / "small.md"
        small.write_text("alpha\nbeta\n", encoding="utf-8")
        out = self._preview(path="small.md")
        self.assertEqual(out["total_lines"], 2)
        self.assertIn("    2 | beta", out["preview"])
        self.assertFalse(out["truncated"])

    def test_rejects_path_traversal_and_absolute_paths(self):
        for bad in ("../outside.py", "src/../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                self._preview(path=bad)

    def test_refuses_env_state_and_non_text_files(self):
        for bad in (".env", "state/history.json"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                self._preview(path=bad)
        binary = self.root / "image.png"
        binary.write_bytes(b"\x89PNG")
        with self.assertRaises(ValueError):
            self._preview(path="image.png")

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError):
            self._preview(path="src/none.py")

    def test_route_is_registered(self):
        self.assertIn("/api/context-slicer/preview", gui.ROUTES)


class TestMissionControlCardWiring(unittest.TestCase):
    def setUp(self):
        self.js = ROOT_JS.read_text(encoding="utf-8")

    def test_card_builds_expected_controls(self):
        for marker in (
            'id: "toolMissionControl"',
            "mcDrainStart",
            "mcDrainClear",
            "mcDrainStatus",
            "/api/graceful-drain",
            "/api/context-slicer/preview",
            "/api/status",
            'data-mode-btn',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.js)

    def test_graceful_drain_keeps_native_confirm(self):
        self.assertIn("window.confirm(", self.js)

    def test_card_never_writes_server_output_as_html(self):
        card_start = self.js.index("// 4. Mission Control card")
        card_src = self.js[card_start:]
        self.assertNotIn("innerHTML", card_src)
        self.assertNotIn("insertAdjacentHTML", card_src)


if __name__ == "__main__":
    unittest.main()

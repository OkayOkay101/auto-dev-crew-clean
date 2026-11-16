import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.runner import engine_cmd


class TestEngineCmd(unittest.TestCase):
    def _layout(self, tmpdir: str, with_native: bool):
        npm = Path(tmpdir)
        shim = npm / "opencode.CMD"
        shim.write_text("@echo off\r\n", encoding="utf-8")
        native = npm / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if with_native:
            native.parent.mkdir(parents=True)
            native.write_bytes(b"MZ")
        return shim, native

    def test_engine_cmd_uses_native_exe_not_cmd_shim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shim, native = self._layout(tmpdir, with_native=True)
            cmd = engine_cmd({"command": "opencode", "path": str(shim), "model": "m"})
            self.assertEqual(cmd[0], str(native))
            self.assertFalse(cmd[0].lower().endswith(".cmd"))

    def test_engine_cmd_refuses_cmd_shim_without_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shim, _ = self._layout(tmpdir, with_native=False)
            with self.assertRaises(RuntimeError):
                engine_cmd({"command": "opencode", "path": str(shim), "model": "m"})


if __name__ == "__main__":
    unittest.main()

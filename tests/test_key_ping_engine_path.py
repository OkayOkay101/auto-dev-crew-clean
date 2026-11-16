"""ping ต้องใช้ path ของ engine (native opencode.exe) ไม่ใช่ค้นจาก PATH.

บั๊กเดิม: key_ping.ping_key เรียก resolve_cli_exe("opencode") โดยไม่ส่ง eng["path"]
→ shutil.which หาเจอ shim opencode.CMD ของ npm → procs.resolve_cli_exe ปฏิเสธ
→ ทุกคีย์ถูกรายงานว่าใช้ไม่ได้ ทั้งที่คีย์ใช้งานได้จริง.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_dev_crew import key_ping

SECRET = "sk_" + "a" * 32
NATIVE = "~/.opencode-bin/opencode.exe"


def _eng(path=NATIVE):
    eng = {
        "name": "pollinations-luna",
        "provider": "Pollinations.ai (OpenAI Compatible)",
        "command": "opencode",
        "model": "pollinations/openai/gpt-6-luna",
        "auth_provider": "pollinations",
        "api_keys": ["${POLLINATIONS_API_KEY_1}"],
    }
    if path is not None:
        eng["path"] = path
    return eng


def _spec():
    return {"key_id": "pollinations-luna#POLLINATIONS_API_KEY_1", "var_name": "POLLINATIONS_API_KEY_1",
            "value": SECRET, "source": "env"}


class TestPingUsesEnginePath(unittest.TestCase):
    def test_resolve_receives_configured_engine_path(self):
        proc = subprocess.CompletedProcess([], 0, stdout="OK\n", stderr="")
        resolve = MagicMock(return_value="C:/fake/opencode.exe")
        with patch.object(key_ping, "resolve_cli_exe", resolve), \
                patch.object(key_ping.subprocess, "run", return_value=proc):
            res = key_ping.ping_key(_eng(), _spec())
        resolve.assert_called_once_with("opencode", NATIVE)
        self.assertTrue(res["ok"])

    def test_engine_without_path_falls_back_to_path_lookup(self):
        proc = subprocess.CompletedProcess([], 0, stdout="OK\n", stderr="")
        resolve = MagicMock(return_value="C:/fake/opencode.exe")
        with patch.object(key_ping, "resolve_cli_exe", resolve), \
                patch.object(key_ping.subprocess, "run", return_value=proc):
            key_ping.ping_key(_eng(path=None), _spec())
        resolve.assert_called_once_with("opencode", None)

    def test_npm_shim_on_path_does_not_break_ping_when_native_path_set(self):
        """ใช้ resolve_cli_exe จริง: path ของ engine ชี้ไป native exe → ต้องไม่โดนปฏิเสธเพราะ shim."""
        proc = subprocess.CompletedProcess([], 0, stdout="OK\n", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / "opencode.exe"
            native.write_bytes(b"")
            shim = str(Path(tmp) / "opencode.CMD")
            with patch("auto_dev_crew.procs.shutil.which", return_value=shim), \
                    patch.object(key_ping.subprocess, "run", return_value=proc) as run:
                res = key_ping.ping_key(_eng(path=str(native)), _spec())
        self.assertTrue(res["ok"], res["message"])
        self.assertEqual(run.call_args.args[0][0], str(native))


if __name__ == "__main__":
    unittest.main()

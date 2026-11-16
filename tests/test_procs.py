import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew.procs import run_tree, resolve_cli_exe


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, errors="replace",
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class TestProcs(unittest.TestCase):
    def test_timeout_kills_child_tree(self):
        fd, pidfile = tempfile.mkstemp(suffix=".pid")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(pidfile) and os.remove(pidfile))

        code = (
            "import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "open(sys.argv[1], 'w').write(str(p.pid))\n"
            "time.sleep(120)\n"
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            run_tree([sys.executable, "-c", code, pidfile], timeout=5)

        grandchild = int(Path(pidfile).read_text().strip())
        deadline = time.time() + 10
        while time.time() < deadline and _pid_alive(grandchild):
            time.sleep(0.2)
        self.assertFalse(_pid_alive(grandchild), "grandchild survived the timeout kill")

    def test_run_tree_returns_completed_process(self):
        res = run_tree(
            [sys.executable, "-c", "print('hello')"],
            timeout=30, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "hello")


class TestResolveCliExe(unittest.TestCase):
    def _make_npm_layout(self, tmpdir: str, with_native: bool) -> tuple[Path, Path]:
        npm = Path(tmpdir)
        shim = npm / "opencode.CMD"
        shim.write_text("@echo off\r\n", encoding="utf-8")
        native = npm / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if with_native:
            native.parent.mkdir(parents=True)
            native.write_bytes(b"MZ")
        return shim, native

    def test_resolve_cli_exe_maps_cmd_shim_to_native_exe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shim, native = self._make_npm_layout(tmpdir, with_native=True)
            self.assertEqual(resolve_cli_exe("opencode", str(shim)), str(native))

    def test_resolve_cli_exe_refuses_cmd_shim_without_native(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shim, _ = self._make_npm_layout(tmpdir, with_native=False)
            with self.assertRaises(RuntimeError):
                resolve_cli_exe("opencode", str(shim))

    def test_resolve_cli_exe_missing_raises(self):
        from unittest.mock import patch
        with patch("auto_dev_crew.procs.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                resolve_cli_exe("opencode")


if __name__ == "__main__":
    unittest.main()

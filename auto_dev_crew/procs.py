"""Subprocess helpers that kill the whole process tree on timeout.

On Windows, ``subprocess.run(timeout=...)`` only kills the direct child (often
``cmd.exe`` for ``shell=True``), leaving grandchildren such as npm/pytest/node
running. These helpers start the child in its own process group and kill the
entire tree with ``taskkill /T`` (Windows) or ``os.killpg`` (POSIX).
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

IS_WINDOWS = os.name == "nt"


def resolve_cli_exe(command: str, path: str | None = None) -> str:
    """Return a real executable path for a CLI, refusing ``.cmd``/``.bat`` shims.

    On Windows, npm installs ``<cmd>.CMD`` shims. Running a shim goes through
    cmd.exe, which re-parses the argv and allows command injection through
    prompt text (``& | > ^ %``). When a shim is found, this maps it to the
    sibling ``node_modules/<cmd>-ai/bin/<cmd>.exe`` binary. If no native binary
    exists, it raises RuntimeError instead of returning the shim.
    """
    candidate = os.path.expanduser(path) if path else shutil.which(command)
    if not candidate or not Path(candidate).exists():
        raise RuntimeError(f"ไม่พบ {command} — ติดตั้งหรือแก้ engine.path ใน config.yaml")
    if candidate.lower().endswith((".cmd", ".bat")):
        native = Path(candidate).parent / "node_modules" / f"{command}-ai" / "bin" / f"{command}.exe"
        if not native.exists():
            raise RuntimeError(
                f"ไม่สามารถใช้ {command} ผ่าน shim {Path(candidate).name} ได้ (ไม่พบ {native.name} แบบ native)"
            )
        candidate = str(native)
    return candidate


def _popen_group_kwargs() -> dict[str, Any]:
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree_pid(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdin=subprocess.DEVNULL, capture_output=True, check=False,
        )
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill ``proc`` and all of its descendants, then reap it."""
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        try:
            _kill_tree_pid(pid)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_tree(cmd, timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
    """Like ``subprocess.run`` but kills the whole process tree on timeout.

    Accepts ``capture_output=True`` as a shorthand for piping stdout/stderr.
    Raises ``subprocess.TimeoutExpired`` after killing the tree.
    """
    if kw.pop("capture_output", False):
        kw.setdefault("stdout", subprocess.PIPE)
        kw.setdefault("stderr", subprocess.PIPE)
    input_data = kw.pop("input", None)

    proc = subprocess.Popen(cmd, **_popen_group_kwargs(), **kw)
    try:
        out, err = proc.communicate(input_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        raise
    except BaseException:
        kill_tree(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

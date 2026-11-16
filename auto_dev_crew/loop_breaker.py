from __future__ import annotations

import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .guardrails import truncate_tool_output
from .procs import kill_tree, run_tree
from .redact import redact_secrets


class LoopDetector:
    """Detects repeated tool calls, commands, or errors from OpenCode streaming output."""

    def __init__(self, repeat_threshold: int = 3):
        self.repeat_threshold = repeat_threshold
        self.last_action: str | None = None
        self.action_streak: int = 0
        self.last_error: str | None = None
        self.error_streak: int = 0

    def extract_action_signature(self, ev: dict[str, Any]) -> str | None:
        ev_type = ev.get("type")
        part = ev.get("part") or {}
        if ev_type == "tool_call" or part.get("type") == "tool_call":
            tool = part.get("tool") or ev.get("tool", "unknown")
            call = part.get("call") or ev.get("call") or {}
            if isinstance(call, dict):
                cmd = call.get("command") or call.get("path") or json.dumps(call, sort_keys=True)
            else:
                cmd = str(call)
            return f"tool:{tool}:{cmd.strip()}"
        return None

    def extract_error_signature(self, ev: dict[str, Any]) -> str | None:
        if ev.get("type") == "error":
            err = ev.get("error") or ev.get("message")
            if isinstance(err, (dict, list)):
                return json.dumps(err, sort_keys=True)
            return str(err).strip()
        return None

    def check_line(self, line: str) -> tuple[bool, str]:
        """Inspect a single JSON line from OpenCode stdout.

        Returns (is_stagnant, reason).
        """
        line_clean = line.strip()
        if not line_clean:
            return False, ""

        try:
            ev = json.loads(line_clean)
        except ValueError:
            return False, ""

        action_sig = self.extract_action_signature(ev)
        if action_sig:
            if action_sig == self.last_action:
                self.action_streak += 1
            else:
                self.last_action = action_sig
                self.action_streak = 1

            if self.action_streak >= self.repeat_threshold:
                return True, f"Command repeated {self.action_streak} times sequentially: {action_sig}"

        error_sig = self.extract_error_signature(ev)
        if error_sig:
            if error_sig == self.last_error:
                self.error_streak += 1
            else:
                self.last_error = error_sig
                self.error_streak = 1

            if self.error_streak >= self.repeat_threshold:
                return True, f"Error repeated {self.error_streak} times sequentially: {error_sig}"

        return False, ""


def build_intervention_prompt(reason: str) -> str:
    """Prompt sent via `opencode run --continue` when loop stagnation is detected."""
    return (
        f"⚠️ SYSTEM INTERVENTION: Stagnation / Loop Detected!\n\n"
        f"Detail: {reason}\n\n"
        f"INSTRUCTION: You have repeated the exact same command or error 3+ times without making progress. "
        f"Do NOT execute the same command again. Change your strategy immediately: try an alternative "
        f"approach, investigate underlying assumptions, or implement a different solution path."
    )


_SESSION_KEYS = ("sessionID", "sessionId", "session_id")


def extract_session_id(line: str) -> str | None:
    """Return the opencode session id carried by a JSON event line, if any."""
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict):
        return None
    for container in (ev, ev.get("part"), ev.get("properties")):
        if isinstance(container, dict):
            for key in _SESSION_KEYS:
                val = container.get(key)
                if isinstance(val, str) and val:
                    return val
    return None


def parse_opencode(stdout: str, seconds: float, max_response_chars: int = 2500) -> dict:
    tokens, errors, text = 0, [], []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "step_finish":
            tokens += (part.get("tokens") or {}).get("total", 0)
        elif ev.get("type") == "error":
            errors.append(json.dumps(ev.get("error") or ev, ensure_ascii=False)[:1000])
        elif part.get("type") == "text":
            text.append(part.get("text", ""))
    response_text = "\n".join(errors or text)
    response_text = truncate_tool_output(response_text, max_chars=max_response_chars)
    return {
        "status": "ERROR" if errors or not tokens else "SUCCESS",
        "response": response_text,
        "partial_text": truncate_tool_output("\n".join(text), max_chars=2500),
        "usage": {"total_tokens": tokens},
        "duration_seconds": seconds,
    }


class AgentSpawnError(RuntimeError):
    """The agent process could not be started (missing binary, WinError 206 for an oversized argv, ...)."""


# The real prompt travels in a file attached with -f, so it never counts against the
# Windows command-line limit (about 32,767 characters). This message is only the argv text.
ATTACHED_PROMPT_MESSAGE = "Follow the instructions in the attached file."


def run_opencode_stream(
    base_cmd: list[str],
    prompt: str,
    cwd: Path,
    env: dict | None,
    timeout: float,
    model: str | None = None,
    logger: Callable[[str], None] | None = None,
    raw_log: Path | None = None,
    idle_timeout: float | None = None,
    max_response_chars: int = 2500,
) -> dict:
    """Run OpenCode with the prompt attached as a temp file (MED-02) and stream its output.

    Raises AgentSpawnError if the process cannot be started.
    """
    fd, prompt_path = tempfile.mkstemp(prefix="opencode-prompt-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        return _stream_attached_prompt(
            base_cmd, prompt_path, cwd, env, timeout, model, logger,
            raw_log=raw_log, prompt_chars=len(prompt), idle_timeout=idle_timeout,
            max_response_chars=max_response_chars,
        )
    finally:
        try:
            os.unlink(prompt_path)
        except OSError:
            pass


class _RawLog:
    """Best-effort redacted raw-stdout log. Never raises: if the file cannot be
    opened or written, capture is silently disabled and the run continues."""

    def __init__(self, path: Path | None) -> None:
        self._fh = None
        if path is None:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8", errors="replace")
        except OSError:
            self._fh = None

    def write(self, text: str) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(redact_secrets(text))
            self._fh.flush()
        except (OSError, ValueError):
            self._fh = None

    def marker(self, text: str) -> None:
        self.write(f"\n{text}\n")

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def _stream_attached_prompt(
    base_cmd: list[str],
    prompt_path: str,
    cwd: Path,
    env: dict | None,
    timeout: float,
    model: str | None,
    logger: Callable[[str], None] | None,
    raw_log: Path | None = None,
    prompt_chars: int = 0,
    idle_timeout: float | None = None,
    max_response_chars: int = 2500,
) -> dict:
    raw = _RawLog(raw_log)
    try:
        raw.write(f"# cmd: {' '.join(base_cmd)} (prompt omitted, {prompt_chars} chars)\n")
        return _stream_attached_prompt_impl(
            base_cmd, prompt_path, cwd, env, timeout, model, logger, raw,
            idle_timeout=idle_timeout, max_response_chars=max_response_chars,
        )
    finally:
        raw.close()


def _stream_attached_prompt_impl(
    base_cmd: list[str],
    prompt_path: str,
    cwd: Path,
    env: dict | None,
    timeout: float,
    model: str | None,
    logger: Callable[[str], None] | None,
    raw: _RawLog,
    idle_timeout: float | None = None,
    max_response_chars: int = 2500,
) -> dict:
    """Stream stdout from OpenCode process, detect stagnation, and intervene with opencode run --session <id> if needed."""
    detector = LoopDetector(repeat_threshold=3)
    all_lines: list[str] = []
    started = time.time()
    last_output = started

    full_cmd = list(base_cmd)
    if "--dir" not in full_cmd:
        full_cmd.extend(["--dir", str(cwd)])
    # `-f` is an array option: put it after the message so it can never swallow the
    # message as a second file (verified: `opencode run "<msg>" -f <file>` parses).
    full_cmd.extend([ATTACHED_PROMPT_MESSAGE, "-f", prompt_path])

    try:
        proc = subprocess.Popen(
            full_cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise AgentSpawnError(f"Failed to spawn opencode: {exc}") from exc

    stagnant = False
    stagnation_reason = ""
    session_id: str | None = None

    out_queue: queue.Queue[str] = queue.Queue()

    def reader_worker() -> None:
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    out_queue.put(line)
        except Exception:
            pass
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

    reader_thread = threading.Thread(target=reader_worker, daemon=True)
    reader_thread.start()

    while True:
        elapsed = time.time() - started
        if elapsed > timeout:
            raw.marker(f"# STOP: timeout after {timeout}s")
            kill_tree(proc)
            return {
                "status": "ERROR",
                "response": f"agent timed out after {timeout}s",
                "usage": {"total_tokens": 0},
                "duration_seconds": elapsed,
            }

        if idle_timeout and time.time() - last_output > idle_timeout:
            raw.marker(f"# STOP: idle for {idle_timeout}s")
            kill_tree(proc)
            return {
                "status": "ERROR",
                "response": f"agent timed out: no output for {int(idle_timeout)}s",
                "usage": {"total_tokens": 0},
                "duration_seconds": elapsed,
            }

        try:
            line = out_queue.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                while not out_queue.empty():
                    try:
                        tail = out_queue.get_nowait()
                    except queue.Empty:
                        break
                    all_lines.append(tail)
                    raw.write(tail)
                raw.marker(
                    f"# END: process exited, returncode={proc.returncode}, "
                    f"elapsed={time.time() - started:.1f}s"
                )
                break
            continue

        last_output = time.time()
        all_lines.append(line)
        raw.write(line)
        if session_id is None:
            session_id = extract_session_id(line)
        is_stagnant, reason = detector.check_line(line)
        if is_stagnant:
            stagnant = True
            stagnation_reason = reason
            raw.marker(f"# STOP: stagnation detected: {reason}")
            msg = f"⚠️ ตรวจพบลูปซ้ำซาก ({reason}) — สั่งระงับ process เพื่อส่งแทรกแซง..."
            if logger:
                logger(msg)
            try:
                proc.terminate()
            except Exception:
                pass
            kill_tree(proc)
            break

    # If stagnation was detected, resume THIS run's session by id (MED-18). `--continue`
    # would resume the latest session in the shared config dir, possibly another slot's.
    if stagnant and not session_id:
        msg = "⚠️ ไม่พบ session id ใน stream — ข้ามการแทรกแซง (ไม่ใช้ --continue เพื่อไม่ให้ไปต่อ session ของ slot อื่น)"
        if logger:
            logger(msg)
        all_lines.append("\nloop-breaker intervention skipped: no session id in stream\n")
    elif stagnant:
        remaining_timeout = max(30.0, timeout - (time.time() - started))
        intervention_prompt = build_intervention_prompt(stagnation_reason)
        continue_cmd = [base_cmd[0], "run", "--session", session_id, "--auto", "--format", "json"]
        if model:
            continue_cmd.extend(["-m", model])
        continue_cmd.extend(["--dir", str(cwd), intervention_prompt])

        msg = f"🔄 กำลังส่ง opencode run --session {session_id} เพื่อแทรกแซงและบังคับเปลี่ยนแนวทาง..."
        if logger:
            logger(msg)

        try:
            # run_tree kills the whole process tree on timeout (HIGH-08).
            cont_res = run_tree(
                continue_cmd,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=remaining_timeout,
            )
            if cont_res.stdout:
                all_lines.append(cont_res.stdout)
                raw.write(cont_res.stdout)
            if cont_res.stderr:
                all_lines.append(cont_res.stderr)
                raw.write(cont_res.stderr)
        except subprocess.TimeoutExpired:
            all_lines.append(f"\nagent intervention timed out after {remaining_timeout}s\n")
        except Exception as exc:
            all_lines.append(f"\nintervention failed: {exc}\n")

    combined_stdout = "".join(all_lines)
    data = parse_opencode(combined_stdout, time.time() - started, max_response_chars=max_response_chars)
    return data

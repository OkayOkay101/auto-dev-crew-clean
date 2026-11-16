import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew.loop_breaker import LoopDetector, build_intervention_prompt


class TestLoopBreaker(unittest.TestCase):
    def setUp(self):
        self.detector = LoopDetector(repeat_threshold=3)

    def test_repeating_tool_command_triggers_stagnation(self):
        # 3 identical bash tool commands
        tool_call_json = json.dumps({
            "type": "tool_call",
            "part": {
                "tool": "bash",
                "call": {"command": "pytest tests/test_app.py"}
            }
        })

        is_stagnant, reason = self.detector.check_line(tool_call_json)
        self.assertFalse(is_stagnant)

        is_stagnant, reason = self.detector.check_line(tool_call_json)
        self.assertFalse(is_stagnant)

        is_stagnant, reason = self.detector.check_line(tool_call_json)
        self.assertTrue(is_stagnant)
        self.assertIn("pytest tests/test_app.py", reason)

    def test_repeating_error_triggers_stagnation(self):
        error_json = json.dumps({
            "type": "error",
            "error": "ModuleNotFoundError: No module named 'fake_module'"
        })

        is_stagnant, _ = self.detector.check_line(error_json)
        self.assertFalse(is_stagnant)

        is_stagnant, _ = self.detector.check_line(error_json)
        self.assertFalse(is_stagnant)

        is_stagnant, reason = self.detector.check_line(error_json)
        self.assertTrue(is_stagnant)
        self.assertIn("fake_module", reason)

    def test_different_actions_reset_or_do_not_trigger(self):
        cmd1 = json.dumps({"type": "tool_call", "part": {"tool": "bash", "call": {"command": "git status"}}})
        cmd2 = json.dumps({"type": "tool_call", "part": {"tool": "bash", "call": {"command": "ls -la"}}})

        self.assertFalse(self.detector.check_line(cmd1)[0])
        self.assertFalse(self.detector.check_line(cmd1)[0])
        self.assertFalse(self.detector.check_line(cmd2)[0])
        self.assertFalse(self.detector.check_line(cmd1)[0])

    def test_intervention_prompt_content(self):
        prompt = build_intervention_prompt("Command repeated 3 times: 'git status'")
        self.assertIn("Command repeated 3 times", prompt)
        self.assertIn("alternative", prompt.lower())

    def test_run_opencode_stream_intervenes_on_stagnation(self):
        from unittest import mock
        from auto_dev_crew.loop_breaker import run_opencode_stream

        # Simulated stuck stdout: repeated bash commands
        stuck_line = json.dumps({
            "type": "tool_call",
            "sessionID": "ses_slot2",
            "part": {"tool": "bash", "call": {"command": "cat non_existent.txt"}}
        }) + "\n"

        lines = [stuck_line, stuck_line, stuck_line, "extra line\n"]

        mock_proc = mock.MagicMock()
        mock_proc.stdout.readline.side_effect = lines
        mock_proc.poll.side_effect = [None, None, None, 0]

        mock_continue_res = mock.MagicMock()
        mock_continue_res.returncode = 0
        mock_continue_res.stdout = json.dumps({"type": "step_finish", "part": {"tokens": {"total": 500}}}) + "\n"
        mock_continue_res.stderr = ""

        # MED-18: the intervention must resume THIS run's session by id, never `--continue`
        # (which resumes the latest session, possibly another slot's).
        # HIGH-08: the intervention now goes through run_tree so a timeout kills the whole tree.
        with mock.patch("subprocess.Popen", return_value=mock_proc):
            with mock.patch("auto_dev_crew.loop_breaker.run_tree", return_value=mock_continue_res) as mock_run:
                res = run_opencode_stream(
                    base_cmd=["opencode", "run", "--auto", "--format", "json", "-m", "test-model"],
                    prompt="Solve issue",
                    cwd=Path("."),
                    env={},
                    timeout=60,
                    model="test-model"
                )

                # Verified that terminate was called on stuck proc
                mock_proc.terminate.assert_called()
                # Verified that opencode run --session <id> was invoked
                mock_run.assert_called_once()
                continue_args = mock_run.call_args[0][0]
                self.assertNotIn("--continue", continue_args)
                self.assertIn("--session", continue_args)
                self.assertEqual(continue_args[continue_args.index("--session") + 1], "ses_slot2")
                self.assertIn("test-model", continue_args)
                self.assertEqual(res["usage"]["total_tokens"], 500)
                self.assertEqual(res["status"], "SUCCESS")

    def test_intervention_skipped_without_session_id(self):
        from unittest import mock
        from auto_dev_crew.loop_breaker import run_opencode_stream

        stuck_line = json.dumps({
            "type": "tool_call",
            "part": {"tool": "bash", "call": {"command": "cat non_existent.txt"}}
        }) + "\n"
        mock_proc = mock.MagicMock()
        mock_proc.stdout.readline.side_effect = [stuck_line] * 3 + [""]
        mock_proc.poll.side_effect = [None, None, None, 0]

        with mock.patch("subprocess.Popen", return_value=mock_proc):
            with mock.patch("auto_dev_crew.loop_breaker.run_tree") as mock_run:
                res = run_opencode_stream(
                    base_cmd=["opencode", "run", "--auto", "--format", "json"],
                    prompt="Solve issue", cwd=Path("."), env={}, timeout=60,
                )
        mock_run.assert_not_called()
        self.assertEqual(res["status"], "ERROR")

    def test_run_opencode_stream_times_out_when_stdout_silent(self):
        from unittest import mock
        from auto_dev_crew.loop_breaker import run_opencode_stream
        import time

        mock_proc = mock.MagicMock()
        def slow_readline():
            time.sleep(0.5)
            return ""

        mock_proc.stdout.readline.side_effect = slow_readline
        mock_proc.poll.return_value = None

        with mock.patch("subprocess.Popen", return_value=mock_proc):
            res = run_opencode_stream(
                base_cmd=["opencode", "run", "--auto", "--format", "json", "-m", "test-model"],
                prompt="Solve issue",
                cwd=Path("."),
                env={},
                timeout=0.3,
                model="test-model"
            )

            mock_proc.kill.assert_called()
            self.assertEqual(res["status"], "ERROR")
            self.assertIn("timed out", res["response"])

    def test_spawn_failure_raises(self):
        from unittest import mock
        from auto_dev_crew.loop_breaker import AgentSpawnError, run_opencode_stream

        with mock.patch("subprocess.Popen", side_effect=OSError(206, "The filename or extension is too long")):
            with self.assertRaises(AgentSpawnError):
                run_opencode_stream(
                    base_cmd=["opencode", "run", "--auto", "--format", "json"],
                    prompt="Solve issue", cwd=Path("."), env={}, timeout=5,
                )

    def test_prompt_is_attached_as_file_not_argv(self):
        from unittest import mock
        from auto_dev_crew.loop_breaker import AgentSpawnError, run_opencode_stream

        big_prompt = "X" * 50000
        seen = {}

        def fake_popen(argv, **kwargs):
            seen["argv"] = list(argv)
            seen["file"] = argv[argv.index("-f") + 1]
            seen["content"] = Path(seen["file"]).read_text(encoding="utf-8")
            raise OSError(206, "The filename or extension is too long")

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with self.assertRaises(AgentSpawnError):
                run_opencode_stream(
                    base_cmd=["opencode", "run", "--auto", "--format", "json", "-m", "m"],
                    prompt=big_prompt, cwd=Path("."), env={}, timeout=5,
                )

        self.assertIn("-f", seen["argv"])
        self.assertEqual(seen["content"], big_prompt)
        self.assertTrue(all(len(arg) < 1000 for arg in seen["argv"]), "prompt must not travel in argv")
        self.assertFalse(Path(seen["file"]).exists(), "temporary prompt file must be removed")


def _run_child(code, tmp_path, raw_log, timeout=10, prompt="SECRET-PROMPT-TEXT"):
    from auto_dev_crew.loop_breaker import run_opencode_stream
    return run_opencode_stream(
        base_cmd=[sys.executable, "-c", code],
        prompt=prompt, cwd=tmp_path, env=None, timeout=timeout, raw_log=raw_log,
    )


def test_raw_log_captures_stdout_and_end_marker(tmp_path):
    raw = tmp_path / "raw.log"
    _run_child("print('hello')", tmp_path, raw)
    text = raw.read_text(encoding="utf-8")
    assert text.startswith("# cmd: ")
    assert "(prompt omitted, 18 chars)" in text
    assert "hello" in text
    assert "# END: process exited, returncode=0" in text
    assert "SECRET-PROMPT-TEXT" not in text


def test_raw_log_redacts_secrets(tmp_path):
    raw = tmp_path / "raw.log"
    key = "gsk_" + "a" * 52
    _run_child(f"print({key!r})", tmp_path, raw)
    text = raw.read_text(encoding="utf-8")
    assert "[PROTECTED_SECRET]" in text
    assert key not in text


def test_raw_log_timeout_marker(tmp_path):
    raw = tmp_path / "raw.log"
    res = _run_child("import time; time.sleep(20)", tmp_path, raw, timeout=2)
    assert res["status"] == "ERROR"
    assert "# STOP: timeout after 2" in raw.read_text(encoding="utf-8")


def test_raw_log_unwritable_path_does_not_break_run(tmp_path):
    res = _run_child("print('hello')", tmp_path, tmp_path)  # a directory
    assert res["status"] != "EXCEPTION"
    assert isinstance(res, dict)


if __name__ == "__main__":
    unittest.main()

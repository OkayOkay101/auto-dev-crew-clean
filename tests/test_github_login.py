import json
import queue
import threading
import unittest
from pathlib import Path

from auto_dev_crew import github_login
from auto_dev_crew.github_login import DEVICE_URL, GhLoginManager

ROOT = Path(__file__).resolve().parent.parent
GUI_SRC = (ROOT / "auto_dev_crew" / "gui.py").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")


class FakeStream:
    def __init__(self, q):
        self._q = q

    def __iter__(self):
        while True:
            line = self._q.get()
            if line is None:
                return
            yield line


class FakeProc:
    """Stands in for subprocess.Popen: prints lines, then stays alive until finish() or kill()."""

    def __init__(self, lines):
        self._q = queue.Queue()
        for line in lines:
            self._q.put(line)
        self.stdout = FakeStream(self._q)
        self.returncode = None
        self.killed = False
        self._done = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._q.put(None)
        self._done.set()

    def finish(self, code, last_lines=()):
        for line in last_lines:
            self._q.put(line)
        self.returncode = code
        self._q.put(None)
        self._done.set()


class Recorder:
    """Records Popen calls and hands back a prepared FakeProc."""

    def __init__(self, proc):
        self.proc = proc
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return self.proc


def _which_gh(_name):
    return "/usr/bin/gh"


CODE_LINES = [
    "! One-time code (C845-4177) copied to clipboard\n",
    "Open this URL to continue in your web browser: https://github.com/login/device\n",
]


class TestGhLoginStart(unittest.TestCase):
    def test_start_returns_one_time_code_and_device_url(self):
        proc = FakeProc(CODE_LINES)
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(proc), code_timeout=2)
        try:
            res = mgr.start()
            self.assertTrue(res["ok"])
            self.assertTrue(res["pending"])
            self.assertEqual(res["code"], "C845-4177")
            self.assertEqual(res["url"], DEVICE_URL)
            self.assertEqual(DEVICE_URL, "https://github.com/login/device")
        finally:
            mgr.cancel()

    def test_gh_missing_is_a_clear_error(self):
        mgr = GhLoginManager(which=lambda _n: None, popen=Recorder(FakeProc([])), code_timeout=0.2)
        res = mgr.start()
        self.assertFalse(res["ok"])
        self.assertIn("gh", res["error"])

    def test_no_code_in_time_kills_process_and_reports_error(self):
        proc = FakeProc(["error: something went wrong\n"])
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(proc), code_timeout=0.2)
        res = mgr.start()
        self.assertFalse(res["ok"])
        self.assertTrue(proc.killed)
        self.assertFalse(mgr.status()["pending"])

    def test_second_start_reuses_running_login(self):
        rec = Recorder(FakeProc(CODE_LINES))
        mgr = GhLoginManager(which=_which_gh, popen=rec, code_timeout=2)
        try:
            first = mgr.start()
            second = mgr.start()
            self.assertEqual(len(rec.calls), 1, "must not start a second gh process")
            self.assertEqual(second["code"], first["code"])
        finally:
            mgr.cancel()

    def test_process_runs_non_interactive_with_least_privilege_scopes(self):
        rec = Recorder(FakeProc(CODE_LINES))
        mgr = GhLoginManager(which=_which_gh, popen=rec, code_timeout=2)
        try:
            mgr.start()
            args, kwargs = rec.calls[0]
            self.assertEqual(args[:3], ["/usr/bin/gh", "auth", "login"])
            self.assertIn("--web", args)
            self.assertIn("--skip-ssh-key", args)
            self.assertEqual(kwargs.get("stdin"), github_login.subprocess.DEVNULL)
            self.assertEqual(kwargs.get("env", {}).get("GH_PROMPT_DISABLED"), "1")
            self.assertIn("repo,workflow", args)
        finally:
            mgr.cancel()


class TestGhLoginStatusAndCancel(unittest.TestCase):
    def test_cancel_kills_running_login(self):
        proc = FakeProc(CODE_LINES)
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(proc), code_timeout=2)
        mgr.start()
        res = mgr.cancel()
        self.assertTrue(res["ok"])
        self.assertTrue(proc.killed)
        self.assertFalse(mgr.status()["pending"])

    def test_status_while_waiting_shows_code(self):
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(FakeProc(CODE_LINES)), code_timeout=2)
        try:
            mgr.start()
            st = mgr.status()
            self.assertTrue(st["pending"])
            self.assertEqual(st["code"], "C845-4177")
            self.assertFalse(st["finished"])
        finally:
            mgr.cancel()

    def test_successful_login_marks_finished_with_zero_exit(self):
        proc = FakeProc(CODE_LINES)
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(proc), code_timeout=2)
        mgr.start()
        proc.finish(0)
        st = mgr.status()
        self.assertFalse(st["pending"])
        self.assertTrue(st["finished"])
        self.assertEqual(st["exit_code"], 0)

    def test_failed_login_keeps_redacted_error_tail(self):
        secret = "gho_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # รูปแบบ token จริงของ GitHub (ยาวพอให้ redact จับได้)
        proc = FakeProc(CODE_LINES)
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(proc), code_timeout=2)
        mgr.start()
        proc.finish(1, last_lines=[f"error: denied, token {secret}\n"])
        st = mgr.status()
        self.assertTrue(st["finished"])
        self.assertEqual(st["exit_code"], 1)
        self.assertIn("denied", st["error"])
        self.assertNotIn(secret, json.dumps(st))

    def test_status_idle_by_default(self):
        mgr = GhLoginManager(which=_which_gh, popen=Recorder(FakeProc([])), code_timeout=0.2)
        self.assertEqual(mgr.status(), {"pending": False, "finished": False, "exit_code": None,
                                        "code": None, "error": None, "url": DEVICE_URL})


def _must_contain(haystack, needle):
    # แจ้งเฉพาะข้อความที่หาไม่เจอ (ไม่พิมพ์ทั้งไฟล์ออกมาใน assertion)
    if needle not in haystack:
        raise AssertionError(f"missing in source: {needle!r}")


class TestGithubLoginRoutesAndUi(unittest.TestCase):
    def test_post_start_and_cancel_registered_in_act_table(self):
        _must_contain(GUI_SRC, '"/api/github/login/start": _api_github_login_start')
        _must_contain(GUI_SRC, '"/api/github/login/cancel": _api_github_login_cancel')

    def test_get_state_route_registered(self):
        _must_contain(GUI_SRC, 'url.path == "/api/github/login/state"')

    def test_step2_has_connect_controls(self):
        start = SIDEBAR.index('data-simple-step="2"')
        end = SIDEBAR.index('data-simple-step="3"')
        step2 = SIDEBAR[start:end]
        for id_ in ["simpleGhLoginBtn", "simpleGhCancelBtn", "simpleGhCode"]:
            _must_contain(step2, f'id="{id_}"')

    def test_frontend_calls_endpoints_with_token_and_no_innerhtml(self):
        _must_contain(SIDEBAR, 'fetch("/api/github/login/start"')
        _must_contain(SIDEBAR, 'fetch("/api/github/login/cancel"')
        _must_contain(SIDEBAR, 'fetch("/api/github/login/state"')
        start = SIDEBAR.index("async function loadSimpleGhStatus")
        end = SIDEBAR.index("/* end simple-gh */", start)
        block = SIDEBAR[start:end]
        if "innerHTML" in block:
            raise AssertionError("innerHTML must not be used in the GitHub connect code")
        _must_contain(block, '"X-Token": TOKEN')


if __name__ == "__main__":
    unittest.main()

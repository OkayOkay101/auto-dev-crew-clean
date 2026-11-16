import json
import subprocess
import unittest
from pathlib import Path

from auto_dev_crew import doctor

ROOT = Path(__file__).resolve().parent.parent
GUI_SRC = (ROOT / "auto_dev_crew" / "gui.py").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")


def _fake_run(stdout="", stderr="", returncode=0):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)
    return run


def _which_gh(_name):
    return "/usr/bin/gh"


class TestParseGhLogin(unittest.TestCase):
    def test_new_gh_format_reads_account(self):
        text = "github.com\n  ✓ Logged in to github.com account octocat (keyring)\n  - Active account: true\n"
        self.assertEqual(doctor.parse_gh_login(text), {"logged_in": True, "account": "octocat"})

    def test_old_gh_format_reads_account(self):
        text = "github.com\n  ✓ Logged in to github.com as octocat (keyring)\n"
        self.assertEqual(doctor.parse_gh_login(text), {"logged_in": True, "account": "octocat"})

    def test_not_logged_in(self):
        text = "You are not logged into any GitHub hosts. Run gh auth login to authenticate."
        self.assertEqual(doctor.parse_gh_login(text), {"logged_in": False, "account": None})

    def test_empty_output(self):
        self.assertEqual(doctor.parse_gh_login(""), {"logged_in": False, "account": None})


class TestGhLoginStatus(unittest.TestCase):
    def test_gh_missing_reports_not_installed(self):
        status = doctor.gh_login_status(which=lambda _name: None, run=_fake_run())
        self.assertEqual(status, {"installed": False, "logged_in": False, "account": None})

    def test_logged_in_with_zero_exit(self):
        run = _fake_run(stdout="  ✓ Logged in to github.com account octocat (keyring)\n")
        status = doctor.gh_login_status(which=_which_gh, run=run)
        self.assertEqual(status, {"installed": True, "logged_in": True, "account": "octocat"})

    def test_nonzero_exit_is_not_logged_in(self):
        # token ที่หมดอายุ: gh จะออกด้วยรหัสไม่เป็นศูนย์ ต้องไม่ถือว่าเชื่อมแล้ว
        run = _fake_run(stdout="  X Failed to log in to github.com account octocat\n", returncode=1)
        status = doctor.gh_login_status(which=_which_gh, run=run)
        self.assertFalse(status["logged_in"])

    def test_timeout_does_not_crash(self):
        def run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="gh", timeout=8)
        status = doctor.gh_login_status(which=_which_gh, run=run)
        self.assertEqual(status, {"installed": True, "logged_in": False, "account": None})

    def test_token_never_leaves_the_function(self):
        secret = "gho_SECRETTOKEN1234567890"
        run = _fake_run(stdout=f"  ✓ Logged in to github.com account octocat (keyring)\n  - Token: {secret}\n")
        status = doctor.gh_login_status(which=_which_gh, run=run)
        self.assertNotIn(secret, json.dumps(status))
        self.assertEqual(set(status), {"installed", "logged_in", "account"})


class TestGithubStatusRoute(unittest.TestCase):
    def test_get_route_is_registered(self):
        self.assertIn('url.path == "/api/github/status"', GUI_SRC)
        self.assertIn("doctor.gh_login_status(", GUI_SRC)


class TestGithubStepInGuide(unittest.TestCase):
    def test_step2_shows_github_status_slot(self):
        start = SIDEBAR.index('data-simple-step="2"')
        end = SIDEBAR.index('data-simple-step="3"')
        step2 = SIDEBAR[start:end]
        self.assertIn('id="simpleGhStatus"', step2)
        self.assertIn("gh auth login", step2)

    def test_frontend_fetches_status_endpoint_without_innerhtml(self):
        self.assertIn('fetch("/api/github/status")', SIDEBAR)
        start = SIDEBAR.index('fetch("/api/github/status")')
        block = SIDEBAR[start:start + 900]
        self.assertNotIn("innerHTML", block)


if __name__ == "__main__":
    unittest.main()

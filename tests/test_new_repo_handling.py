import subprocess
import unittest
from pathlib import Path
from unittest import mock
import datetime as dt

from auto_dev_crew import runner
from auto_dev_crew.runner import SlotRegistry
from auto_dev_crew.multi_repo import generate_default_repo_config


class TestNewRepoHandling(unittest.TestCase):
    def setUp(self):
        self.tmp = Path("state/test_new_repo")
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.registry = SlotRegistry(state_dir=self.tmp)

    def tearDown(self):
        import shutil
        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persona_not_blocked_by_other_repo_rest(self):
        """When another repo had 4 NO_ACTIONs, a new repo should NOT be blocked by rest hours."""
        cfg = {
            "owner": "example-owner",
            "personas": {"enabled": ["bolt", "sentinel", "palette", "quality"]},
            "parallel": {"slots": 3}
        }
        now_str = dt.datetime.now().strftime("%Y%m%d-%H%M")
        # History has 4 NO_ACTIONs for old-repo
        history = [
            {"repo": "example-owner/old-repo", "kind": "persona", "key": "bolt", "state": "NO_ACTION", "date": now_str},
            {"repo": "example-owner/old-repo", "kind": "persona", "key": "sentinel", "state": "NO_ACTION", "date": now_str},
            {"repo": "example-owner/old-repo", "kind": "persona", "key": "palette", "state": "NO_ACTION", "date": now_str},
            {"repo": "example-owner/old-repo", "kind": "persona", "key": "quality", "state": "NO_ACTION", "date": now_str},
        ]

        # For old-repo, it is blocked
        blocked_job = runner.pick_task_for_slot(
            slot_id=2,
            cfg=cfg,
            history=history,
            issues=[],
            registry=self.registry,
            repo_name="example-owner/old-repo"
        )
        self.assertIsNone(blocked_job)

        # For new-repo, it should NOT be blocked
        new_repo_job = runner.pick_task_for_slot(
            slot_id=2,
            cfg=cfg,
            history=history,
            issues=[],
            registry=self.registry,
            repo_name="example-owner/example-repo-2"
        )
        self.assertIsNotNone(new_repo_job)
        self.assertEqual(new_repo_job.kind, "persona")

    def test_run_steps_skips_missing_requirements_txt(self):
        """run_steps should skip requirements.txt gracefully if not present in cwd."""
        cwd = self.tmp
        env = {}
        steps = ["python -m pip install -q -r requirements.txt"]
        ok, out = runner.run_steps(steps, cwd, env)
        self.assertTrue(ok)
        self.assertIn("ข้าม: ไม่พบ requirements.txt", out)

    def test_generate_default_repo_config_js(self):
        """Detects JS / non-python repo and does not hardcode pytest or pip requirements."""
        with mock.patch("auto_dev_crew.multi_repo.gh", autospec=True) as mock_gh:
            mock_gh.return_value = "index.html\ntest-runner.js\nREADME.md"
            rcfg = generate_default_repo_config("example-owner/example-repo-2")
            self.assertEqual(rcfg["setup"], [])
            self.assertEqual(rcfg["test"], ["node test-runner.js"])

    def test_generate_default_repo_config_js_at_run_cmd_level(self):
        """Regression: gh() got check=False -> TypeError swallowed -> JS repo got the Python config.
        Mock at run_cmd (the real gh path) so the real gh() signature is exercised."""
        listing = subprocess.CompletedProcess(
            ["gh"], 0, stdout="index.html\ntest-runner.js\nREADME.md\n", stderr=""
        )
        with mock.patch("auto_dev_crew.multi_repo.run_cmd", return_value=listing) as mock_run:
            rcfg = generate_default_repo_config("example-owner/example-repo-2", base_branch="main")
        self.assertEqual(rcfg["test"], ["node test-runner.js"])
        self.assertEqual(rcfg["setup"], [])
        self.assertEqual(mock_run.call_args[0][0][:2], ["gh", "api"])


def test_default_python_unittest_step_finds_tests_through_shell(tmp_path):
    """Phase 3 live E2E: run_steps uses shell=True; on Windows cmd.exe keeps single quotes,
    so `-p 'test_*.py'` matched nothing ("NO TESTS RAN", exit 5) and every new Python repo failed."""
    import sys
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n", encoding="utf-8"
    )
    with mock.patch("auto_dev_crew.multi_repo.gh", autospec=True) as mock_gh:
        mock_gh.return_value = "calc.py\nrequirements.txt"
        rcfg = generate_default_repo_config("example-owner/py-repo", base_branch="main")
    unittest_steps = [s for s in rcfg["test"] + rcfg["scanners"]["quality"] if "unittest discover" in s]
    assert unittest_steps
    for step in unittest_steps:
        cmd = step.replace("python", f'"{sys.executable}"', 1)
        res = subprocess.run(cmd, shell=True, cwd=tmp_path, capture_output=True, text=True)
        assert res.returncode == 0, (step, res.stderr[-300:])


def test_default_python_test_steps_pass_for_pytest_only_repo(tmp_path):
    """Phase 3 live E2E: a repo with only pytest-style test functions (the common case) failed
    the default test steps because `unittest discover` found 0 tests and exited 5."""
    import sys
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8"
    )
    with mock.patch("auto_dev_crew.multi_repo.gh", autospec=True) as mock_gh:
        mock_gh.return_value = "calc.py\nconftest.py\nrequirements.txt\ntests"
        rcfg = generate_default_repo_config("example-owner/py-repo", base_branch="main")
    for step in rcfg["test"]:
        cmd = step.replace("python", f'"{sys.executable}"', 1)
        res = subprocess.run(cmd, shell=True, cwd=tmp_path, capture_output=True, text=True)
        assert res.returncode == 0, (step, (res.stdout + res.stderr)[-300:])

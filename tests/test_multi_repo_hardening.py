"""HIGH-08 (timeouts / tree kill) and MED-17 (cache-only repo dir, no shell from file names)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew import multi_repo

CFG = {
    "owner": "example-owner",
    "repos": [{"name": "example-owner/test-repo", "test": ["pytest -q"],
               "scanners": {"sentinel": ["bandit -q -r ."]}}],
}


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess(["x"], rc, stdout=out, stderr=err)


class TestVerificationTimeouts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "app.py").write_text("x = 1\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.multi_repo.run_tree")
    def test_verification_runs_through_run_tree_with_timeout(self, mock_tree, mock_find):
        mock_find.return_value = self.tmp
        mock_tree.return_value = _cp(0, "3 passed")
        res = multi_repo.run_repo_verification("example-owner/test-repo", "test", CFG)
        self.assertTrue(res["ok"])
        self.assertEqual(mock_tree.call_args.args[0], "pytest -q")
        self.assertEqual(mock_tree.call_args.kwargs["timeout"], 1800)

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.multi_repo.run_tree")
    def test_verification_timeout_returns_failed_result(self, mock_tree, mock_find):
        mock_find.return_value = self.tmp
        mock_tree.side_effect = subprocess.TimeoutExpired("pytest -q", 1800)
        res = multi_repo.run_repo_verification("example-owner/test-repo", "test", CFG)
        self.assertFalse(res["ok"])
        self.assertEqual(res["exit_code"], 124)
        self.assertIn("timed out", res["stderr"])

    @patch("auto_dev_crew.multi_repo.run_tree")
    def test_run_cmd_has_default_timeout(self, mock_tree):
        mock_tree.return_value = _cp(0, "ok")
        multi_repo.run_cmd(["git", "status"])
        self.assertEqual(mock_tree.call_args.kwargs["timeout"], 300)

    @patch("auto_dev_crew.multi_repo.run_tree", side_effect=subprocess.TimeoutExpired(["gh"], 300))
    def test_run_cmd_timeout_propagates_as_timeout_expired(self, _mock_tree):
        with self.assertRaises(subprocess.TimeoutExpired):
            multi_repo.run_cmd(["gh", "api", "x"])


class TestCacheOnlyRepoDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = self.tmp / "repos"
        p = patch.object(multi_repo, "REPOS_CACHE_DIR", self.cache)
        p.start()
        self.addCleanup(p.stop)
        old_cwd = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)

    def test_cwd_named_like_repo_is_never_used(self):
        repo = self.tmp / "test-repo"
        (repo / ".git").mkdir(parents=True)
        os.chdir(repo)
        with patch("auto_dev_crew.multi_repo.run_cmd", return_value=_cp(1, "", "not found")):
            with self.assertRaises(RuntimeError):
                multi_repo.find_or_prepare_repo_dir("example-owner/test-repo")

    def test_failed_clone_raises_and_leaves_no_empty_folder(self):
        with patch("auto_dev_crew.multi_repo.run_cmd", return_value=_cp(1, "", "auth required")):
            with self.assertRaises(RuntimeError) as ctx:
                multi_repo.find_or_prepare_repo_dir("example-owner/test-repo")
        self.assertIn("auth required", str(ctx.exception))
        self.assertFalse((self.cache / "example-owner_test-repo").exists())

    def test_clone_that_exits_zero_without_git_dir_raises(self):
        with patch("auto_dev_crew.multi_repo.run_cmd", return_value=_cp(0)):
            with self.assertRaises(RuntimeError):
                multi_repo.find_or_prepare_repo_dir("example-owner/test-repo")

    def test_existing_cache_is_returned_without_clone(self):
        target = self.cache / "example-owner_test-repo"
        (target / ".git").mkdir(parents=True)
        with patch("auto_dev_crew.multi_repo.run_cmd") as mock_run:
            got = multi_repo.find_or_prepare_repo_dir("example-owner/test-repo")
        self.assertEqual(got, target.resolve())
        # cache ที่มีอยู่แล้วจะ fetch จาก origin (refresh) แต่ต้องไม่ clone ใหม่
        for call in mock_run.call_args_list:
            self.assertNotIn("clone", call.args[0])

    def test_successful_clone_goes_to_cache(self):
        def fake_clone(cmd, timeout=None):
            (Path(cmd[4]) / ".git").mkdir(parents=True)
            return _cp(0)
        with patch("auto_dev_crew.multi_repo.run_cmd", side_effect=fake_clone):
            got = multi_repo.find_or_prepare_repo_dir("example-owner/test-repo")
        self.assertEqual(got, (self.cache / "example-owner_test-repo").resolve())

    def test_invalid_repo_name_is_rejected(self):
        with self.assertRaises(ValueError):
            multi_repo.find_or_prepare_repo_dir(r"..\evil")


class TestSyntaxModeNoShell(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "app.py").write_text("x = 1\n", encoding="utf-8")
        (self.tmp / "evil&whoami.py").write_text("y = 2\n", encoding="utf-8")

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.multi_repo.run_tree")
    def test_syntax_check_uses_argv_list_and_no_shell(self, mock_tree, mock_find):
        mock_find.return_value = self.tmp
        mock_tree.return_value = _cp(0)
        multi_repo.run_repo_verification("example-owner/test-repo", "syntax", CFG)
        argv = mock_tree.call_args.args[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[:3], [sys.executable, "-m", "py_compile"])
        self.assertIn("evil&whoami.py", argv)
        self.assertNotEqual(mock_tree.call_args.kwargs.get("shell"), True)


if __name__ == "__main__":
    unittest.main()


class TestProcessSlotRejectsForeignTarget(unittest.TestCase):
    """MED-16 at the runner level: a Target-Repo outside the allowlist must not retarget the job."""

    def setUp(self):
        from auto_dev_crew import runner
        self.runner = runner
        for s in range(1, 4):
            runner.REGISTRY.release_slot(s)
        self.cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "pause": "ai-pause", "working": "ai-working",
                       "failed": "ai-failed", "pr": "ai-pr"},
            "personas": {"enabled": ["bolt", "sentinel"]},
            "repos": [{"name": "example-owner/repo-alpha", "base": "main"}],
            "parallel": {"slots": 3},
            "merge_mode": "merge-all",
        }

    @patch("auto_dev_crew.runner.get_available_issues")
    @patch("auto_dev_crew.runner.paused", return_value=False)
    @patch("auto_dev_crew.runner.resume_pending", return_value=False)
    @patch("auto_dev_crew.runner.open_ai_prs", return_value=[])
    @patch("auto_dev_crew.runner.execute", return_value="Done")
    def test_foreign_owner_target_is_ignored(self, mock_execute, _prs, _resume, _paused, mock_issues):
        from auto_dev_crew.runner import Job
        mock_issues.return_value = [
            Job("issue", "7", "Steal", "Target-Repo: evil-org/victim\nplease")
        ]
        rcfg = self.cfg["repos"][0]
        gh_json_patch = patch("auto_dev_crew.multi_repo.gh_json", return_value={"defaultBranchRef": {"name": "main"}})
        gh_patch = patch("auto_dev_crew.multi_repo.gh", side_effect=AssertionError("real gh must not run"))
        with gh_json_patch, gh_patch:
            self.runner.process_slot(slot_id=1, cfg=self.cfg, rcfg=rcfg, dry_run=True)
        self.assertTrue(mock_execute.called)
        self.assertEqual(mock_execute.call_args[0][2]["name"], "example-owner/repo-alpha")

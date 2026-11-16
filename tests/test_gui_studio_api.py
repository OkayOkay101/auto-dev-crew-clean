import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil

from auto_dev_crew import gui, multi_repo


class TestGuiStudioApi(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.test_dir) / "test-repo"
        self.repo_dir.mkdir()
        (self.repo_dir / "app.py").write_text("def hello(name: str) -> str:\n    '''Say hello.'''\n    return f'Hello, {name}'\n", encoding="utf-8")
        (self.repo_dir / "requirements.txt").write_text("fastapi>=0.100.0\npytest>=7.0.0\n", encoding="utf-8")
        (self.repo_dir / "tests").mkdir()
        (self.repo_dir / "tests" / "test_app.py").write_text("def test_hello():\n    assert True\n", encoding="utf-8")

        self.cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "pause": "ai-pause", "working": "ai-working", "failed": "ai-failed", "pr": "ai-generated"},
            "repos": [
                {
                    "name": "example-owner/test-repo",
                    "base": "main",
                    "setup": ["pip install -r requirements.txt"],
                    "test": ["pytest -q"],
                    "scanners": {
                        "sentinel": ["bandit -q -r ."],
                        "quality": ["pytest -q"],
                    },
                }
            ],
            "engines": [{"name": "opencode-zen", "enabled": True}],
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.multi_repo.gh_json")
    def test_get_repo_workspace_info(self, mock_gh_json, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir
        mock_gh_json.return_value = [
            {"number": 12, "title": "Fix login bug", "state": "OPEN", "url": "https://github.com/...", "createdAt": "2026-11-07T12:00:00Z"}
        ]

        info = multi_repo.get_repo_workspace_info("example-owner/test-repo", self.cfg)
        self.assertEqual(info["name"], "example-owner/test-repo")
        self.assertEqual(info["base"], "main")
        self.assertEqual(info["stack_profile"]["primary_language"], "python")
        self.assertIn("fastapi", info["stack_profile"]["frameworks"])
        self.assertIn("app.py", info["files"])
        self.assertEqual(len(info["issues"]), 1)
        self.assertEqual(info["issues"][0]["number"], 12)

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    def test_get_repo_file_content_full_and_ast(self, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir

        # 1. Full content
        res_full = multi_repo.get_repo_file_content("example-owner/test-repo", "app.py", mode="full")
        self.assertIn("return f'Hello, {name}'", res_full["content"])
        self.assertEqual(res_full["mode"], "full")

        # 2. AST Skeleton
        res_ast = multi_repo.get_repo_file_content("example-owner/test-repo", "app.py", mode="ast")
        self.assertIn("def hello(name: str) -> str: ...", res_ast["content"])
        self.assertNotIn("return f'Hello, {name}'", res_ast["content"])
        self.assertEqual(res_ast["mode"], "ast")

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.multi_repo.run_tree")
    def test_run_repo_verification(self, mock_subproc_run, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir
        mock_res = MagicMock(returncode=0, stdout="3 passed in 0.12s", stderr="")
        mock_subproc_run.return_value = mock_res

        res = multi_repo.run_repo_verification("example-owner/test-repo", "test", self.cfg)
        self.assertTrue(res["ok"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("3 passed", res["stdout"])

    @patch("auto_dev_crew.multi_repo.gh")
    def test_dispatch_studio_coding_task_live(self, mock_gh):
        mock_gh.return_value = "https://github.com/example-owner/test-repo/issues/99"
        res = multi_repo.dispatch_studio_coding_task(
            "example-owner/test-repo",
            prompt="Refactor database queries",
            persona="bolt",
            mode="surgical",
            engine="opencode-zen",
            sandbox=False,
            cfg=self.cfg,
        )
        self.assertTrue(res["ok"])
        self.assertFalse(res["sandbox"])
        self.assertEqual(res["issue_url"], "https://github.com/example-owner/test-repo/issues/99")

    @patch("auto_dev_crew.gui.load_cfg")
    @patch("auto_dev_crew.multi_repo.run_repo_verification")
    def test_gui_act_run_command(self, mock_run_verify, mock_load_cfg):
        mock_load_cfg.return_value = self.cfg
        mock_run_verify.return_value = {"ok": True, "exit_code": 0, "stdout": "All checks passed", "stderr": ""}

        res = gui.act("/api/repo/run-command", {"repo": "example-owner/test-repo", "check_type": "test"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["stdout"], "All checks passed")

    @patch("auto_dev_crew.gui.load_cfg")
    @patch("auto_dev_crew.multi_repo.dispatch_studio_coding_task")
    def test_gui_act_dispatch_task(self, mock_dispatch, mock_load_cfg):
        mock_load_cfg.return_value = self.cfg
        mock_dispatch.return_value = {"ok": True, "sandbox": True, "diff": "+ new code"}

        res = gui.act("/api/repo/dispatch-task", {
            "repo": "example-owner/test-repo",
            "prompt": "Add cache headers",
            "persona": "bolt",
            "mode": "surgical",
            "engine": "opencode-zen",
            "sandbox": True,
        })
        self.assertTrue(res["ok"])
        self.assertTrue(res["sandbox"])
        self.assertEqual(res["diff"], "+ new code")

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    def test_get_repo_file_content_not_found(self, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir
        with self.assertRaises(FileNotFoundError):
            multi_repo.get_repo_file_content("example-owner/test-repo", "non_existent.py")

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    def test_get_repo_file_content_path_traversal(self, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir
        with self.assertRaises(PermissionError):
            multi_repo.get_repo_file_content("example-owner/test-repo", "../../../secret.txt")

    def test_dispatch_studio_coding_task_empty_prompt(self):
        with self.assertRaises(ValueError):
            multi_repo.dispatch_studio_coding_task("example-owner/test-repo", prompt="")

    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("subprocess.run")
    def test_sync_repo_success(self, mock_subproc_run, mock_find_dir):
        mock_find_dir.return_value = self.repo_dir
        mock_res = MagicMock(returncode=0, stdout="Already up to date.", stderr="")
        mock_subproc_run.return_value = mock_res

        res = multi_repo.sync_repo("example-owner/test-repo", self.cfg)
        self.assertTrue(res["ok"])
        self.assertEqual(res["stdout"], "Already up to date.")

    @patch("auto_dev_crew.gui.load_cfg")
    @patch("auto_dev_crew.multi_repo.sync_repo")
    def test_gui_act_sync(self, mock_sync, mock_load_cfg):
        mock_load_cfg.return_value = self.cfg
        mock_sync.return_value = {"ok": True, "message": "Synced"}

        res = gui.act("/api/repo/sync", {"repo": "example-owner/test-repo"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["message"], "Synced")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch
from auto_dev_crew.runner import Job
from auto_dev_crew import runner


class TestRunnerMultiRepo(unittest.TestCase):
    def setUp(self):
        for s in range(1, 4):
            runner.REGISTRY.release_slot(s)
        self.cfg = {
            "owner": "example-owner",
            "labels": {
                "task": "ai-task",
                "pause": "ai-pause",
                "working": "ai-working",
                "failed": "ai-failed",
                "pr": "ai-pr",
            },
            "personas": {"enabled": ["bolt", "sentinel"]},
            "repos": [
                {"name": "example-owner/repo-alpha", "base": "main"},
                {"name": "example-owner/repo-beta", "base": "main"},
            ],
            "parallel": {"slots": 3},
            "merge_mode": "merge-all",
        }

    @patch("auto_dev_crew.runner.get_available_issues")
    @patch("auto_dev_crew.runner.paused", return_value=False)
    @patch("auto_dev_crew.runner.resume_pending", return_value=False)
    @patch("auto_dev_crew.runner.open_ai_prs", return_value=[])
    @patch("auto_dev_crew.runner.execute")
    def test_slot_1_finds_issue_in_second_repo(
        self, mock_execute, mock_open_prs, mock_resume, mock_paused, mock_get_issues
    ):
        """Slot 1 should scan all configured repos and pick up issue from repo-beta if repo-alpha is empty."""
        def get_issues_side_effect(repo, cfg):
            if repo == "example-owner/repo-alpha":
                return []
            elif repo == "example-owner/repo-beta":
                return [Job("issue", "42", "Beta Feature", "Details here")]
            return []

        mock_get_issues.side_effect = get_issues_side_effect
        mock_execute.return_value = "Done"

        rcfg = self.cfg["repos"][0]
        progressed = runner.process_slot(
            slot_id=1,
            cfg=self.cfg,
            rcfg=rcfg,
            dry_run=True,
        )
        self.assertTrue(progressed)
        self.assertTrue(mock_execute.called)
        called_rcfg = mock_execute.call_args[0][2]
        self.assertEqual(called_rcfg["name"], "example-owner/repo-beta")

    @patch("auto_dev_crew.runner.get_available_issues")
    @patch("auto_dev_crew.runner.paused", return_value=False)
    @patch("auto_dev_crew.runner.resume_pending", return_value=False)
    @patch("auto_dev_crew.runner.open_ai_prs", return_value=[])
    @patch("auto_dev_crew.runner.execute")
    def test_cross_repo_dispatch_via_issue_body(
        self, mock_execute, mock_open_prs, mock_resume, mock_paused, mock_get_issues
    ):
        """Issue on repo-alpha containing Target-Repo: repo-gamma should dispatch execution to repo-gamma."""
        mock_get_issues.return_value = [
            Job("issue", "99", "Cross Repo Task", "Target-Repo: example-owner/repo-gamma\nDo something here")
        ]
        mock_execute.return_value = "Done"

        rcfg = self.cfg["repos"][0]
        with patch("auto_dev_crew.multi_repo.gh_json", return_value={"defaultBranchRef": {"name": "main"}}):
            progressed = runner.process_slot(
                slot_id=1,
                cfg=self.cfg,
                rcfg=rcfg,
                dry_run=True,
            )
        self.assertTrue(progressed)
        self.assertTrue(mock_execute.called)
        called_rcfg = mock_execute.call_args[0][2]
        self.assertEqual(called_rcfg["name"], "example-owner/repo-gamma")

    @patch("auto_dev_crew.multi_repo.gh_json")
    @patch("auto_dev_crew.runner.slot_worker_loop")
    @patch("auto_dev_crew.runner.clean_work")
    def test_main_cli_unconfigured_repo_does_not_crash(
        self, mock_clean, mock_worker_loop, mock_gh_json
    ):
        """Passing --repo with unconfigured repo should auto-create rcfg and not raise IndexError."""
        mock_gh_json.return_value = {"defaultBranchRef": {"name": "main"}}

        with patch("sys.argv", ["auto-dev-crew", "--repo", "example-owner/unconfigured-repo", "--dry-run", "--slot", "1"]):
            exit_code = runner.main()
            self.assertEqual(exit_code, 0)
            self.assertTrue(mock_worker_loop.called)
            called_rcfg = mock_worker_loop.call_args[0][2]
            self.assertEqual(called_rcfg["name"], "example-owner/unconfigured-repo")

    @patch("auto_dev_crew.runner.get_available_issues")
    @patch("auto_dev_crew.runner.paused", return_value=False)
    @patch("auto_dev_crew.runner.resume_pending", return_value=False)
    @patch("auto_dev_crew.runner.open_ai_prs", return_value=[])
    @patch("auto_dev_crew.runner.execute")
    def test_process_slot_respects_repo_filter(
        self, mock_execute, mock_open_prs, mock_resume, mock_paused, mock_get_issues
    ):
        """When repo_filter is specified, slot 1 must ONLY scan the filtered repo."""
        def get_issues_side_effect(repo, cfg):
            if repo == "example-owner/repo-alpha":
                return [Job("issue", "1", "Alpha Task", "body")]
            elif repo == "example-owner/repo-beta":
                return [Job("issue", "2", "Beta Task", "body")]
            return []

        mock_get_issues.side_effect = get_issues_side_effect
        mock_execute.return_value = "Done"

        rcfg = self.cfg["repos"][0]
        progressed = runner.process_slot(
            slot_id=1,
            cfg=self.cfg,
            rcfg=rcfg,
            dry_run=True,
            repo_filter="example-owner/repo-beta"
        )
        self.assertTrue(progressed)
        self.assertTrue(mock_execute.called)
        called_rcfg = mock_execute.call_args[0][2]
        self.assertEqual(called_rcfg["name"], "example-owner/repo-beta")

    @patch("auto_dev_crew.runner.get_available_issues")
    @patch("auto_dev_crew.runner.paused", return_value=False)
    @patch("auto_dev_crew.runner.resume_pending", return_value=False)
    @patch("auto_dev_crew.runner.open_ai_prs", return_value=[])
    @patch("auto_dev_crew.runner.execute")
    def test_process_slot_skips_disabled_repo(
        self, mock_execute, mock_open_prs, mock_resume, mock_paused, mock_get_issues
    ):
        """Disabled repos (enabled: False) should be skipped during candidate selection."""
        cfg = dict(self.cfg)
        cfg["repos"] = [
            {"name": "example-owner/repo-disabled", "base": "main", "enabled": False},
            {"name": "example-owner/repo-enabled", "base": "main", "enabled": True},
        ]
        def get_issues_side_effect(repo, cfg):
            if repo == "example-owner/repo-disabled":
                return [Job("issue", "1", "Should Skip", "body")]
            elif repo == "example-owner/repo-enabled":
                return [Job("issue", "2", "Should Run", "body")]
            return []

        mock_get_issues.side_effect = get_issues_side_effect
        mock_execute.return_value = "Done"

        rcfg = cfg["repos"][0]
        progressed = runner.process_slot(
            slot_id=1,
            cfg=cfg,
            rcfg=rcfg,
            dry_run=True,
        )
        self.assertTrue(progressed)
        self.assertTrue(mock_execute.called)
        called_rcfg = mock_execute.call_args[0][2]
        self.assertEqual(called_rcfg["name"], "example-owner/repo-enabled")


ORIGIN_REPO = "example-owner/repo-alpha"
TARGET_REPO = "example-owner/repo-gamma"


def test_cross_repo_issue_ops_target_origin_repo(fake_gh, fake_pipeline):
    """HIGH-04: an issue found in repo-alpha but executed in repo-gamma must be labelled/commented
    in repo-alpha, and the PR must close repo-alpha#99 (not repo-gamma#99)."""
    cfg = {
        "owner": "example-owner",
        "labels": {"task": "ai-task", "pause": "ai-pause", "working": "ai-working",
                   "failed": "ai-failed", "pr": "ai-pr"},
        "max_fix_attempts": 2,
        "merge_mode": "merge-all",
        "small_pr": {"max_lines": 50, "protected_paths": []},
        "evaluation": {"enabled": False},
        "triage": {"enabled": False},
        "ci": {"enabled": False, "auto_rebase": False},
        "parallel": {"slots": 3},
        "personas": {"enabled": []},
        "repos": [{"name": ORIGIN_REPO, "base": "main", "test": []},
                  {"name": TARGET_REPO, "base": "main", "test": []}],
    }
    issue = {"number": 99, "title": "Cross Repo Task",
             "body": f"Target-Repo: {TARGET_REPO}\nDo something here",
             "author": {"login": "example-owner"}, "labels": []}
    fake_gh.on(("issue", "list"), lambda args: [issue] if "ai-task" in args else [])
    fake_gh.on(("pr", "create"), f"https://github.com/{TARGET_REPO}/pull/12")

    rcfg = cfg["repos"][0]
    assert runner.process_slot(slot_id=1, cfg=cfg, rcfg=rcfg, dry_run=False)

    origin_ops = [c for c in fake_gh.calls
                  if c[:2] in (("issue", "edit"), ("issue", "comment")) and c[2] == "99"]
    assert origin_ops, "no issue operations recorded for #99"
    for call in origin_ops:
        assert call[call.index("-R") + 1] == ORIGIN_REPO, call

    assert ("issue", "edit", "99", "-R", ORIGIN_REPO, "--add-label", "ai-working") in fake_gh.calls
    assert ("issue", "edit", "99", "-R", ORIGIN_REPO, "--remove-label", "ai-working") in fake_gh.calls

    pr_create = fake_gh.calls_with("pr", "create")
    assert pr_create, "PR was not opened"
    body = pr_create[0][pr_create[0].index("--body") + 1]
    assert f"Closes {ORIGIN_REPO}#99" in body
    assert "Closes #99" not in body
    assert "## Test Checklist" in body

    history = runner.load_history()
    entry = next(h for h in history if h.get("key") == "99")
    assert entry.get("origin_repo") == ORIGIN_REPO



if __name__ == "__main__":
    unittest.main()

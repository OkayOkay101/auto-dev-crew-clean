import unittest
from unittest import mock

from auto_dev_crew.ci_sync import wait_for_required_checks


class TestCISync(unittest.TestCase):
    def test_all_required_checks_pass(self):
        # gh pr checks JSON output with both required checks passed
        mock_checks = [
            {"name": "python-functional", "state": "SUCCESS", "status": "COMPLETED", "conclusion": "success"},
            {"name": "python-syntax", "state": "SUCCESS", "status": "COMPLETED", "conclusion": "success"},
            {"name": "codeql", "state": "SUCCESS", "status": "COMPLETED", "conclusion": "success"},
        ]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                repo="example-owner/example-repo",
                pr=10,
                required_checks=["python-functional", "python-syntax"],
                timeout_seconds=10,
                poll_interval=1,
                max_polls=1
            )
            self.assertEqual(result, "pass")

    def test_one_required_check_fails(self):
        mock_checks = [
            {"name": "python-functional", "state": "SUCCESS", "status": "COMPLETED", "conclusion": "success"},
            {"name": "python-syntax", "state": "FAILURE", "status": "COMPLETED", "conclusion": "failure"},
        ]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                repo="example-owner/example-repo",
                pr=10,
                required_checks=["python-functional", "python-syntax"],
                timeout_seconds=10,
                poll_interval=1,
                max_polls=1
            )
            self.assertEqual(result, "fail")

    def test_required_checks_pending_then_timeout(self):
        # Checks are queued / pending
        mock_checks = [
            {"name": "python-functional", "state": "PENDING", "status": "IN_PROGRESS", "conclusion": None},
            {"name": "python-syntax", "state": "PENDING", "status": "QUEUED", "conclusion": None},
        ]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                repo="example-owner/example-repo",
                pr=10,
                required_checks=["python-functional", "python-syntax"],
                timeout_seconds=1,
                poll_interval=0.1,
                max_polls=2
            )
            self.assertEqual(result, "timeout")

    def test_checks_not_yet_reported_does_not_return_none_if_required(self):
        # Empty list returned because Actions hasn't registered yet
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=[]):
            result = wait_for_required_checks(
                repo="example-owner/example-repo",
                pr=10,
                required_checks=["python-functional"],
                timeout_seconds=1,
                poll_interval=0.1,
                max_polls=2
            )
            # Must NOT return 'none' when required checks are configured; must wait or timeout
            self.assertEqual(result, "timeout")


    def test_empty_required_checks_returns_pass_or_none(self):
        # Case 1: No checks exist -> returns 'none'
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=[]):
            res = wait_for_required_checks("repo", 1, required_checks=[])
            self.assertEqual(res, "none")

        # Case 2: General checks exist and passed -> returns 'pass'
        all_ok = [{"name": "ci", "conclusion": "success", "state": "SUCCESS"}]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=all_ok):
            res = wait_for_required_checks("repo", 1, required_checks=[])
            self.assertEqual(res, "pass")


    def test_fetch_pr_checks_parses_on_nonzero_exit(self):
        """gh exits 8 while checks are pending and 1 when one failed; stdout is still valid JSON."""
        import subprocess
        from auto_dev_crew.ci_sync import fetch_pr_checks

        payload = '[{"name": "python-syntax", "state": "FAILURE", "bucket": "fail"}]'
        completed = subprocess.CompletedProcess(["gh"], 1, stdout=payload, stderr="")
        with mock.patch("auto_dev_crew.ci_sync.subprocess.run", return_value=completed):
            checks = fetch_pr_checks("example-owner/repo", 7)
        self.assertEqual(checks, [{"name": "python-syntax", "state": "FAILURE", "bucket": "fail"}])

    def test_fetch_pr_checks_pending_exit_8_is_parsed(self):
        import subprocess
        from auto_dev_crew.ci_sync import fetch_pr_checks

        payload = '[{"name": "ci", "state": "PENDING", "bucket": "pending"}]'
        completed = subprocess.CompletedProcess(["gh"], 8, stdout=payload, stderr="")
        with mock.patch("auto_dev_crew.ci_sync.subprocess.run", return_value=completed):
            checks = fetch_pr_checks("example-owner/repo", 7)
        self.assertEqual(checks[0]["name"], "ci")

    def test_fetch_pr_checks_non_json_nonzero_returns_empty(self):
        import subprocess
        from auto_dev_crew.ci_sync import fetch_pr_checks

        completed = subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="boom")
        with mock.patch("auto_dev_crew.ci_sync.subprocess.run", return_value=completed):
            self.assertEqual(fetch_pr_checks("example-owner/repo", 7), [])

    def test_required_names_missing_falls_back_to_all_existing_checks(self):
        """Repo without 'python-functional' but with other checks: after 3 polls the gate
        switches to 'every existing check must pass' and returns pass."""
        logs = []
        mock_checks = [{"name": "js-test", "state": "SUCCESS", "bucket": "pass", "conclusion": "success"}]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                repo="example-owner/example-repo-2",
                pr=3,
                required_checks=["python-functional", "python-syntax"],
                timeout_seconds=30,
                poll_interval=0.01,
                max_polls=10,
                logger=logs.append,
            )
        self.assertEqual(result, "pass")
        self.assertTrue(any("fallback" in m.lower() or "ทุก check" in m for m in logs), logs)

    def test_fallback_mode_fails_when_an_existing_check_fails(self):
        mock_checks = [
            {"name": "js-test", "state": "FAILURE", "bucket": "fail", "conclusion": "failure"},
        ]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                "repo", 3, required_checks=["python-functional"],
                timeout_seconds=30, poll_interval=0.01, max_polls=10,
            )
        self.assertEqual(result, "fail")

    def test_no_fallback_before_three_polls(self):
        """Missing required names must not switch modes on the first polls."""
        mock_checks = [{"name": "js-test", "state": "SUCCESS", "bucket": "pass", "conclusion": "success"}]
        with mock.patch("auto_dev_crew.ci_sync.fetch_pr_checks", return_value=mock_checks):
            result = wait_for_required_checks(
                "repo", 3, required_checks=["python-functional"],
                timeout_seconds=30, poll_interval=0.01, max_polls=2,
            )
        self.assertEqual(result, "timeout")



if __name__ == "__main__":
    unittest.main()

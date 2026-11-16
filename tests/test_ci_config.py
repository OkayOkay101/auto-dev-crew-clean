import unittest
from unittest import mock

from auto_dev_crew.runner import ci_config_for, try_merge


class TestCIConfig(unittest.TestCase):
    def test_ci_config_for_global_defaults(self):
        cfg = {
            "ci": {
                "enabled": True,
                "required_checks": ["build"],
                "allow_no_ci": True,
                "auto_bootstrap_ci": False,
            }
        }
        rcfg = {"name": "user/repo1"}
        combined = ci_config_for(cfg, rcfg)
        self.assertTrue(combined["enabled"])
        self.assertEqual(combined["required_checks"], ["build"])
        self.assertTrue(combined["allow_no_ci"])
        self.assertFalse(combined["auto_bootstrap_ci"])

    def test_ci_config_for_repo_override(self):
        cfg = {
            "ci": {
                "enabled": True,
                "required_checks": ["build"],
                "allow_no_ci": True,
                "auto_bootstrap_ci": False,
            }
        }
        rcfg = {
            "name": "user/repo2",
            "ci": {
                "required_checks": ["custom-test"],
                "allow_no_ci": False,
                "auto_bootstrap_ci": True,
            },
        }
        combined = ci_config_for(cfg, rcfg)
        self.assertEqual(combined["required_checks"], ["custom-test"])
        self.assertFalse(combined["allow_no_ci"])
        self.assertTrue(combined["auto_bootstrap_ci"])

    @mock.patch("auto_dev_crew.runner.wait_for_checks", return_value="none")
    @mock.patch("auto_dev_crew.runner.gh")
    def test_try_merge_allow_no_ci_true(self, mock_gh, mock_wait):
        cfg = {
            "merge_mode": "merge-all",
            "ci": {"enabled": True, "allow_no_ci": True},
        }
        rcfg = {"name": "user/repo-no-ci", "base": "main"}
        result = try_merge("user/repo-no-ci", 10, cfg, small=False, rcfg=rcfg)
        self.assertIn("merge แล้ว ✅", result)
        self.assertIn("repo ไม่มี CI", result)
        mock_gh.assert_any_call("pr", "merge", "10", "-R", "user/repo-no-ci", "--squash", "--delete-branch")

    @mock.patch("auto_dev_crew.runner.wait_for_checks", return_value="none")
    @mock.patch("auto_dev_crew.runner.gh")
    def test_try_merge_allow_no_ci_false(self, mock_gh, mock_wait):
        cfg = {
            "merge_mode": "merge-all",
            "ci": {"enabled": True, "allow_no_ci": False},
        }
        rcfg = {"name": "user/repo-no-ci", "base": "main"}
        result = try_merge("user/repo-no-ci", 10, cfg, small=False, rcfg=rcfg)
        self.assertIn("รอ CI", result)
        self.assertIn("allow_no_ci ปิดอยู่", result)
        # Should not call merge
        for call_args in mock_gh.call_args_list:
            self.assertNotIn("merge", call_args[0])


if __name__ == "__main__":
    unittest.main()

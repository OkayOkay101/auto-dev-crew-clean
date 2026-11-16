import unittest
from unittest.mock import patch

from auto_dev_crew import runner


GLOBAL_CFG = {
    "merge_mode": "merge-all",
    "ci": {"enabled": True, "required_checks": ["python-functional", "python-syntax"], "timeout_minutes": 1},
    "parallel": {"merge_lock_timeout_minutes": 1},
}


class TestPerRepoRequiredChecks(unittest.TestCase):
    def _merge(self, rcfg, cfg=GLOBAL_CFG):
        with patch("auto_dev_crew.runner.wait_for_required_checks", return_value="pass") as waiter, \
                patch("auto_dev_crew.runner.wait_for_checks", return_value="none") as generic, \
                patch("auto_dev_crew.runner.repo_has_workflows", return_value=None), \
                patch("auto_dev_crew.runner.gh", return_value=""):
            result = runner.try_merge("example-owner/js-app", 5, cfg, False, rcfg=rcfg)
        return result, waiter, generic

    def test_repo_level_required_checks_override_global(self):
        rcfg = {"name": "example-owner/js-app", "ci": {"required_checks": ["js-test"]}}
        result, waiter, _ = self._merge(rcfg)
        self.assertTrue(waiter.called)
        self.assertEqual(waiter.call_args[0][2], ["js-test"])
        self.assertTrue(result.startswith("merge แล้ว"))

    def test_absent_repo_key_falls_back_to_global(self):
        rcfg = {"name": "example-owner/py-app", "base": "main"}
        _, waiter, _ = self._merge(rcfg)
        self.assertEqual(waiter.call_args[0][2], ["python-functional", "python-syntax"])

    def test_explicit_empty_repo_list_means_no_required_checks(self):
        rcfg = {"name": "example-owner/nocheck", "ci": {"required_checks": []}}
        result, waiter, generic = self._merge(rcfg)
        self.assertFalse(waiter.called)
        self.assertTrue(generic.called)
        self.assertTrue(result.startswith("merge แล้ว"))

    def test_no_rcfg_uses_global(self):
        with patch("auto_dev_crew.runner.wait_for_required_checks", return_value="pass") as waiter, \
                patch("auto_dev_crew.runner.gh", return_value=""):
            runner.try_merge("example-owner/x", 5, GLOBAL_CFG, False)
        self.assertEqual(waiter.call_args[0][2], ["python-functional", "python-syntax"])


if __name__ == "__main__":
    unittest.main()

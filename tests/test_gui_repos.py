import unittest
from unittest.mock import patch
from auto_dev_crew import gui


class TestGuiRepos(unittest.TestCase):
    @patch("auto_dev_crew.runner.ensure_labels")
    @patch("auto_dev_crew.gui.add_repo_to_config")
    @patch("auto_dev_crew.gui.load_cfg")
    def test_add_repo_success(self, mock_load_cfg, mock_add_repo, mock_ensure_labels):
        mock_load_cfg.return_value = {"repos": []}
        mock_add_repo.return_value = {"name": "example-owner/new-service", "base": "main"}

        res = gui.act("/api/repos/add", {"repo": "example-owner/new-service"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("repo", {}).get("name"), "example-owner/new-service")
        self.assertTrue(mock_ensure_labels.called)

    def test_add_repo_invalid_name(self):
        with self.assertRaises(ValueError):
            gui.act("/api/repos/add", {"repo": "invalid_name_without_slash"})

    @patch("auto_dev_crew.multi_repo.toggle_repo_in_config", return_value=True)
    def test_toggle_repo(self, mock_toggle):
        res = gui.act("/api/repos/toggle", {"repo": "example-owner/example-repo", "enabled": False})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("enabled"), False)
        self.assertTrue(mock_toggle.called)

    @patch("auto_dev_crew.multi_repo.delete_repo_from_config", return_value=True)
    def test_delete_repo(self, mock_delete):
        res = gui.act("/api/repos/delete", {"repo": "example-owner/old-repo"})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("deleted"), "example-owner/old-repo")
        self.assertTrue(mock_delete.called)

    @patch("auto_dev_crew.gui.load_cfg", return_value={"repos": [{"name": "example-owner/custom-target"}]})
    @patch("auto_dev_crew.gui.AGENT.start")
    @patch("auto_dev_crew.gui.AUTO.enable")
    def test_run_with_selected_repo(self, mock_auto, mock_agent, mock_load_cfg):
        res = gui.act("/api/run", {
            "loop": True,
            "dry_run": False,
            "repo": "example-owner/custom-target"
        })
        self.assertTrue(res.get("ok"))
        mock_agent.assert_called_with(["--loop", "--repo", "example-owner/custom-target"])
        # Running is manual now: a run with --loop must not turn AutoPilot on.
        mock_auto.assert_not_called()

    @patch("auto_dev_crew.multi_repo.scan_user_repositories")
    def test_scan_repos_endpoint(self, mock_scan):
        mock_scan.return_value = [
            {"name": "example-owner/repo-1", "can_automate": True, "is_configured": True, "enabled": True},
            {"name": "example-owner/repo-2", "can_automate": True, "is_configured": False, "enabled": False},
        ]
        res = gui.act("/api/repos/scan", {})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("count"), 2)
        self.assertEqual(len(res.get("repositories")), 2)


if __name__ == "__main__":
    unittest.main()

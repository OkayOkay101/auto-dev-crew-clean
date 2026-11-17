"""Guards for the 2026-11-18 cleanup: removed leftovers must stay removed."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI_PY = (ROOT / "auto_dev_crew" / "gui.py").read_text(encoding="utf-8")


class TestRemovedLeftovers(unittest.TestCase):
    def test_github_login_endpoints_removed_from_gui(self):
        self.assertNotIn("/api/github/", GUI_PY)
        self.assertNotIn("github_login", GUI_PY)

    def test_github_login_module_deleted(self):
        self.assertFalse((ROOT / "auto_dev_crew" / "github_login.py").exists())

    def test_classic_route_removed(self):
        self.assertNotIn('url.path == "/classic"', GUI_PY)

    def test_oracle_deploy_folder_deleted(self):
        self.assertFalse((ROOT / "deploy" / "oracle").exists())

    def test_config_example_is_tracked_template_without_personal_repo(self):
        example = ROOT / "config.example.yaml"
        self.assertTrue(example.exists(), "config.example.yaml must exist: config.yaml is untracked")
        self.assertNotIn("OkayOkay101", example.read_text(encoding="utf-8"))

    def test_ci_copies_config_example_before_tests_and_ui(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertGreaterEqual(ci.count("config.example.yaml config.yaml"), 2)

    def test_reserve_for_issues_not_in_local_config(self):
        cfg = ROOT / "config.yaml"
        if not cfg.exists():
            self.skipTest("config.yaml is local and not present")
        self.assertNotIn("reserve_for_issues", cfg.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew.multi_repo import (
    parse_target_repo,
    is_target_repo_allowed,
    ensure_repo_config,
    add_repo_to_config,
    toggle_repo_in_config,
    delete_repo_from_config,
    scan_user_repositories,
)


class TestMultiRepo(unittest.TestCase):
    def test_parse_target_repo_from_body(self):
        title = "Fix database connection leak"
        body = "Please investigate this issue.\nTarget-Repo: example-owner/another-service\nDetails here..."
        target_repo, clean_title, clean_body = parse_target_repo(title, body, default_repo="example-owner/default-repo")
        self.assertEqual(target_repo, "example-owner/another-service")
        self.assertEqual(clean_title, "Fix database connection leak")
        self.assertNotIn("Target-Repo:", clean_body)

    def test_parse_target_repo_from_title(self):
        title = "[example-owner/another-service] Fix database connection leak"
        body = "Details here..."
        target_repo, clean_title, clean_body = parse_target_repo(title, body, default_repo="example-owner/default-repo")
        self.assertEqual(target_repo, "example-owner/another-service")
        self.assertEqual(clean_title, "Fix database connection leak")
        self.assertEqual(clean_body, "Details here...")

    def test_parse_target_repo_fallback_to_default(self):
        title = "Normal issue title"
        body = "Some description without any target repo declaration"
        target_repo, clean_title, clean_body = parse_target_repo(title, body, default_repo="example-owner/default-repo")
        self.assertEqual(target_repo, "example-owner/default-repo")
        self.assertEqual(clean_title, "Normal issue title")
        self.assertEqual(clean_body, body)

    def test_ensure_repo_config_existing(self):
        cfg = {
            "repos": [
                {"name": "example-owner/existing", "base": "main", "test": ["pytest"]}
            ]
        }
        rcfg = ensure_repo_config(cfg, "example-owner/existing")
        self.assertEqual(rcfg["name"], "example-owner/existing")
        self.assertEqual(rcfg["base"], "main")
        self.assertEqual(rcfg["test"], ["pytest"])

    @patch("auto_dev_crew.multi_repo.gh_json")
    def test_ensure_repo_config_unconfigured_queries_github(self, mock_gh_json):
        mock_gh_json.return_value = {"defaultBranchRef": {"name": "develop"}}
        cfg = {"repos": []}
        rcfg = ensure_repo_config(cfg, "example-owner/new-repo")
        self.assertEqual(rcfg["name"], "example-owner/new-repo")
        self.assertEqual(rcfg["base"], "develop")
        self.assertIn("test", rcfg)
        self.assertIn("setup", rcfg)
        self.assertIn("scanners", rcfg)

    @patch("auto_dev_crew.multi_repo.gh")
    @patch("auto_dev_crew.multi_repo.gh_json")
    def test_add_repo_to_config(self, mock_gh_json, mock_gh):
        mock_gh_json.return_value = {"defaultBranchRef": {"name": "main"}}
        mock_gh.return_value = "ok"

        import tempfile
        import yaml
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tf:
            yaml.safe_dump({"owner": "example-owner", "repos": [{"name": "example-owner/repo1", "base": "main"}]}, tf)
            tpath = Path(tf.name)

        try:
            rcfg = add_repo_to_config(tpath, "example-owner/repo2")
            self.assertEqual(rcfg["name"], "example-owner/repo2")
            self.assertEqual(rcfg["base"], "main")

            # Check saved file
            saved = yaml.safe_load(tpath.read_text(encoding="utf-8"))
            repo_names = [r["name"] for r in saved["repos"]]
            self.assertIn("example-owner/repo2", repo_names)
        finally:
            if tpath.exists():
                tpath.unlink()

    def test_toggle_and_delete_repo_in_config(self):
        import tempfile
        import yaml
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w", encoding="utf-8") as tf:
            yaml.safe_dump({
                "owner": "example-owner",
                "repos": [
                    {"name": "example-owner/repo1", "base": "main", "enabled": True},
                    {"name": "example-owner/repo2", "base": "main", "enabled": True},
                ]
            }, tf)
            tpath = Path(tf.name)

        try:
            # Toggle repo1 to disabled
            ok = toggle_repo_in_config(tpath, "example-owner/repo1", False)
            self.assertTrue(ok)
            saved = yaml.safe_load(tpath.read_text(encoding="utf-8"))
            r1 = next(r for r in saved["repos"] if r["name"] == "example-owner/repo1")
            self.assertEqual(r1["enabled"], False)

            # Delete repo2
            ok_del = delete_repo_from_config(tpath, "example-owner/repo2")
            self.assertTrue(ok_del)
            saved2 = yaml.safe_load(tpath.read_text(encoding="utf-8"))
            self.assertEqual(len(saved2["repos"]), 1)
            self.assertEqual(saved2["repos"][0]["name"], "example-owner/repo1")
        finally:
            if tpath.exists():
                tpath.unlink()

    @patch("auto_dev_crew.multi_repo.gh_json")
    def test_scan_user_repositories(self, mock_gh_json):
        mock_gh_json.return_value = [
            {
                "nameWithOwner": "example-owner/active-repo",
                "name": "active-repo",
                "description": "Active Project",
                "isPrivate": False,
                "isArchived": False,
                "defaultBranchRef": {"name": "main"},
                "pushedAt": "2026-11-08T00:00:00Z"
            },
            {
                "nameWithOwner": "example-owner/archived-repo",
                "name": "archived-repo",
                "description": "Old Project",
                "isPrivate": True,
                "isArchived": True,
                "defaultBranchRef": {"name": "main"},
                "pushedAt": "2025-01-01T00:00:00Z"
            }
        ]
        cfg = {
            "owner": "example-owner",
            "repos": [{"name": "example-owner/active-repo", "enabled": True}]
        }
        repos = scan_user_repositories(cfg)
        self.assertTrue(len(repos) >= 2)

        active = next(r for r in repos if r["name"] == "example-owner/active-repo")
        self.assertTrue(active["can_automate"])
        self.assertTrue(active["is_configured"])
        self.assertTrue(active["enabled"])

        archived = next(r for r in repos if r["name"] == "example-owner/archived-repo")
        self.assertFalse(archived["can_automate"])
        self.assertFalse(archived["is_configured"])


class TestTargetRepoAllowlist(unittest.TestCase):
    CFG = {
        "owner": "example-owner",
        "repos": [
            {"name": "example-owner/app", "base": "main"},
            {"name": "partner-org/shared-lib", "base": "main"},
        ],
    }
    DEFAULT = "example-owner/app"

    def test_repo_key_form_is_not_a_directive(self):
        body = "Please fix.\nrepo: example-owner/other\nmore"
        target, _, clean = parse_target_repo("Bug", body, self.DEFAULT, cfg=self.CFG)
        self.assertEqual(target, self.DEFAULT)
        self.assertEqual(clean, body)

    def test_target_repo_underscore_form_is_not_a_directive(self):
        body = "target_repo: example-owner/other"
        target, _, _ = parse_target_repo("Bug", body, self.DEFAULT, cfg=self.CFG)
        self.assertEqual(target, self.DEFAULT)

    def test_disallowed_owner_directive_is_ignored_and_logged(self):
        logged = []
        body = "Details\nTarget-Repo: evil-org/victim\nmore"
        target, title, clean = parse_target_repo(
            "Bug", body, self.DEFAULT, cfg=self.CFG, on_reject=logged.append
        )
        self.assertEqual(target, self.DEFAULT)
        self.assertEqual(title, "Bug")
        self.assertEqual(clean, body)
        self.assertEqual(len(logged), 1)
        self.assertIn("evil-org/victim", logged[0])

    def test_disallowed_title_bracket_is_ignored(self):
        target, title, _ = parse_target_repo(
            "[evil-org/victim] Bug", "x", self.DEFAULT, cfg=self.CFG
        )
        self.assertEqual(target, self.DEFAULT)
        self.assertEqual(title, "[evil-org/victim] Bug")

    def test_owner_match_is_allowed_even_if_not_configured(self):
        target, _, _ = parse_target_repo(
            "Bug", "Target-Repo: example-owner/brand-new", self.DEFAULT, cfg=self.CFG
        )
        self.assertEqual(target, "example-owner/brand-new")

    def test_configured_repo_from_other_owner_is_allowed(self):
        target, _, _ = parse_target_repo(
            "Bug", "Target-Repo: partner-org/shared-lib", self.DEFAULT, cfg=self.CFG
        )
        self.assertEqual(target, "partner-org/shared-lib")

    def test_is_target_repo_allowed_without_owner_key_uses_configured_owners(self):
        cfg = {"repos": [{"name": "acme/app"}]}
        self.assertTrue(is_target_repo_allowed("acme/other", cfg))
        self.assertFalse(is_target_repo_allowed("mallory/victim", cfg))



if __name__ == "__main__":
    unittest.main()

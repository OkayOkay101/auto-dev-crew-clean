"""Regression tests: secret-file read blocking and engine-update field allowlist."""
import unittest

from auto_dev_crew import gui, gui_patches


class ForbiddenReadPathTests(unittest.TestCase):
    def test_blocks_git_internals_and_credentials(self):
        for path in [
            ".git/config",
            "sub/.git/config",
            "repo\\.git\\config",
            ".npmrc",
            "deploy/.pypirc",
            ".netrc",
            ".git-credentials",
            "certs/server.pem",
            "keys/private.key",
            "id_rsa",
            "home/id_ed25519",
            ".env.example",
            "config.yaml",
            "",
        ]:
            with self.subTest(path=path):
                self.assertTrue(gui_patches.is_forbidden_read_path(path))

    def test_allows_normal_source_and_docs(self):
        for path in ["src/main.py", "docs/.gitignore", "README.md", "id_generator.py", "secrets_utils.py"]:
            with self.subTest(path=path):
                self.assertFalse(gui_patches.is_forbidden_read_path(path))


class EngineUpdateAllowlistTests(unittest.TestCase):
    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            gui.act("/api/engine/update", {"name": "x", "updates": {"base_url": "https://evil.example"}})

    def test_rejects_non_object_updates(self):
        with self.assertRaises(ValueError):
            gui.act("/api/engine/update", {"name": "x", "updates": ["model"]})


if __name__ == "__main__":
    unittest.main()

"""สวิตช์ auto_bootstrap_ci รายรีโป (ค่าเริ่มต้นปิด)."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from auto_dev_crew import gui, multi_repo

CFG_TEXT = """\
owner: example-owner
labels:
  task: ai-task
  pr: ai-pr
  working: ai-working
  failed: ai-failed
ci:
  allow_no_ci: true
repos:
- name: example-owner/with-flag
  base: main
  ci:
    auto_bootstrap_ci: true
- name: example-owner/no-flag
  base: main
"""


class BootstrapToggleEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.yaml"
        self.path.write_text(CFG_TEXT, encoding="utf-8")
        gui.set_config_path(self.path)

    def tearDown(self):
        gui.set_config_path(None)
        self.tmp.cleanup()

    def _repo(self, name: str) -> dict:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        return next(r for r in raw["repos"] if r["name"] == name)

    def test_turn_off_and_on_per_repo(self):
        res = gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/with-flag", "auto_bootstrap_ci": False})
        self.assertTrue(res.get("ok"))
        self.assertFalse(res["auto_bootstrap_ci"])
        self.assertFalse(self._repo("example-owner/with-flag")["ci"]["auto_bootstrap_ci"])

        res = gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/no-flag", "auto_bootstrap_ci": True})
        self.assertTrue(res["auto_bootstrap_ci"])
        self.assertTrue(self._repo("example-owner/no-flag")["ci"]["auto_bootstrap_ci"])

    def test_does_not_touch_allow_no_ci(self):
        gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/no-flag", "auto_bootstrap_ci": True})
        self.assertNotIn("allow_no_ci", self._repo("example-owner/no-flag").get("ci", {}))

    def test_toggle_clears_cached_repo_status(self):
        key = "repo:example-owner/no-flag"
        gui._cache[key] = (time.time(), {"auto_bootstrap_ci": False})
        gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/no-flag", "auto_bootstrap_ci": True})
        self.assertNotIn(key, gui._cache)

    def test_allow_no_ci_toggle_clears_cached_repo_status(self):
        key = "repo:example-owner/no-flag"
        gui._cache[key] = (time.time(), {"allow_no_ci": True})
        gui.act("/api/ci/toggle", {"repo": "example-owner/no-flag", "allow_no_ci": False})
        self.assertNotIn(key, gui._cache)

    def test_rejects_missing_repo(self):
        with self.assertRaises(ValueError):
            gui.act("/api/ci/bootstrap-toggle", {"auto_bootstrap_ci": True})

    def test_rejects_unknown_repo(self):
        with self.assertRaises(ValueError):
            gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/missing", "auto_bootstrap_ci": True})

    def test_rejects_missing_value(self):
        with self.assertRaises(ValueError):
            gui.act("/api/ci/bootstrap-toggle", {"repo": "example-owner/no-flag"})


class RepoStatusDefaultTests(unittest.TestCase):
    def test_repo_without_setting_reports_off(self):
        cfg = yaml.safe_load(CFG_TEXT)
        with patch.object(gui.runner, "gh_json", return_value=[]), \
                patch.object(gui.runner, "paused", return_value=False):
            status = gui.repo_status(cfg, "example-owner/no-flag")
        self.assertIs(status["auto_bootstrap_ci"], False)

    def test_repo_with_setting_reports_on(self):
        cfg = yaml.safe_load(CFG_TEXT)
        with patch.object(gui.runner, "gh_json", return_value=[]), \
                patch.object(gui.runner, "paused", return_value=False):
            status = gui.repo_status(cfg, "example-owner/with-flag")
        self.assertIs(status["auto_bootstrap_ci"], True)


class NewRepoConfigDefaultTests(unittest.TestCase):
    def test_generated_config_writes_bootstrap_off(self):
        with patch.object(multi_repo, "gh", return_value="requirements.txt\n"):
            rcfg = multi_repo.generate_default_repo_config("example-owner/new-repo", base_branch="main")
        self.assertEqual(rcfg["ci"], {"auto_bootstrap_ci": False})


if __name__ == "__main__":
    unittest.main()

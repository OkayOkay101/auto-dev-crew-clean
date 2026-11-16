import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from auto_dev_crew.runner import (
    find_conflict_files,
    ai_resolve_conflicts,
    try_merge,
)


class TestConflictResolver(unittest.TestCase):
    def test_find_conflict_files(self):
        with patch("auto_dev_crew.runner.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="core.js\nindex.html\n")
            files = find_conflict_files(Path("dummy/cwd"))
            self.assertEqual(files, ["core.js", "index.html"])

    def test_find_conflict_files_empty(self):
        with patch("auto_dev_crew.runner.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            files = find_conflict_files(Path("dummy/cwd"))
            self.assertEqual(files, [])

    def test_ai_resolve_conflicts_success(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            f1 = tmp_path / "core.js"
            f1.write_text("<<<<<<< HEAD\nvar a = 1;\n=======\nvar a = 2;\n>>>>>>> origin/main", encoding="utf-8")

            fake_agent = MagicMock(return_value={"response": "var a = 2;\n// both handled"})
            with patch("auto_dev_crew.runner.call_agent", fake_agent), \
                 patch("auto_dev_crew.runner.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="")
                resolved = ai_resolve_conflicts(tmp_path, ["core.js"], cfg={}, slot_id=2)
                self.assertTrue(resolved)
                self.assertNotIn("<<<<<<<", f1.read_text(encoding="utf-8"))
                self.assertIn("var a = 2;", f1.read_text(encoding="utf-8"))

    def test_try_merge_does_not_close_pr_on_unresolvable_conflict(self):
        repo = "example-owner/example-repo-2"
        pr = 15
        cfg = {
            "merge_mode": "auto",
            "ci": {"enabled": False},
            "parallel": {"merge_lock_timeout_minutes": 1}
        }

        with patch("auto_dev_crew.runner.gh") as mock_gh, \
             patch("auto_dev_crew.runner.wait_for_checks", return_value="pass"), \
             patch("auto_dev_crew.runner.file_lock"):
            def fake_gh(*args, **kwargs):
                if args[:2] == ("pr", "merge"):
                    raise RuntimeError("Pull request is not mergeable: the merge commit cannot be cleanly created.")
                return ""
            mock_gh.side_effect = fake_gh

            result = try_merge(repo, pr, cfg, small=True, slot_id=2)
            # Verify PR is NOT closed and branch is NOT deleted
            close_calls = [c for c in mock_gh.call_args_list if len(c[0]) >= 2 and c[0][:2] == ("pr", "close")]
            self.assertEqual(len(close_calls), 0, "PR should NEVER be closed on merge conflict!")

            # Verify label needs-rebase is added
            edit_calls = [c for c in mock_gh.call_args_list if len(c[0]) >= 2 and c[0][:2] == ("pr", "edit")]
            self.assertTrue(any("--add-label" in c[0] and "needs-rebase" in c[0] for c in edit_calls))

            self.assertIn("ติด conflict", result)


if __name__ == "__main__":
    unittest.main()

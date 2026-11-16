"""build_prompt must not crash when a history entry has no 'title' (hand-written or old entries)."""
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.runner import Job, build_prompt


class TestBuildPromptHistoryWithoutTitle(unittest.TestCase):
    def test_persona_history_entry_without_title_does_not_raise(self):
        job = Job(kind="persona", key="quality", title="Quality", body="")
        rcfg = {"name": "o/r", "scanners": {}}
        history = [{"repo": "o/r", "key": "quality", "kind": "persona", "state": "MERGED", "pr": 7}]
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_prompt(job, rcfg, cwd=Path(tmp), env={}, history=history,
                                  result_path=Path(tmp) / "r.json")
        self.assertIn("[MERGED]", prompt)

    def test_history_entry_with_title_still_listed(self):
        job = Job(kind="persona", key="quality", title="Quality", body="")
        rcfg = {"name": "o/r", "scanners": {}}
        history = [{"repo": "o/r", "key": "quality", "kind": "persona", "state": "MERGED",
                    "pr": 7, "title": "tighten tests"}]
        with tempfile.TemporaryDirectory() as tmp:
            prompt = build_prompt(job, rcfg, cwd=Path(tmp), env={}, history=history,
                                  result_path=Path(tmp) / "r.json")
        self.assertIn("tighten tests", prompt)


if __name__ == "__main__":
    unittest.main()

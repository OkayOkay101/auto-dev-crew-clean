"""BUG-7: a persona whose PR is still OPEN is not run again (the sandbox got 3 near-identical PRs)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew import runner
from auto_dev_crew.slots import SlotRegistry


class TestPersonaOpenPr(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.registry = SlotRegistry(state_dir=self.test_dir)
        self.cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {"enabled": ["quality", "bolt"]},
            "parallel": {"slots": 3},
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_persona_with_open_pr_is_skipped(self):
        # Rotation would pick "quality" next (last run was "bolt"), but quality still has an OPEN PR.
        history = [{"repo": "o/r", "kind": "persona", "key": "quality", "state": "OPEN", "pr": 10},
                   {"repo": "o/r", "kind": "persona", "key": "bolt", "state": "MERGED", "pr": 9}]
        job = runner.pick_task_for_slot(slot_id=2, cfg=self.cfg, history=history, issues=[],
                                        registry=self.registry, repo_name="o/r")
        self.assertIsNotNone(job)
        self.assertEqual((job.kind, job.key), ("persona", "bolt"))

    def test_persona_with_closed_pr_is_pickable_again(self):
        history = [{"repo": "o/r", "kind": "persona", "key": "quality", "state": "CLOSED", "pr": 10},
                   {"repo": "o/r", "kind": "persona", "key": "bolt", "state": "MERGED", "pr": 11}]
        job = runner.pick_task_for_slot(slot_id=2, cfg=self.cfg, history=history, issues=[],
                                        registry=self.registry, repo_name="o/r")
        self.assertIsNotNone(job)
        self.assertEqual(job.key, "quality")

    def test_open_pr_of_other_repo_does_not_block(self):
        history = [{"repo": "other/r", "kind": "persona", "key": "quality", "state": "OPEN", "pr": 10}]
        job = runner.pick_task_for_slot(slot_id=2, cfg=self.cfg, history=history, issues=[],
                                        registry=self.registry, repo_name="o/r")
        self.assertIsNotNone(job)
        self.assertEqual(job.key, "quality")

    def test_all_personas_with_open_prs_returns_none(self):
        history = [{"repo": "o/r", "kind": "persona", "key": "quality", "state": "OPEN", "pr": 10},
                   {"repo": "o/r", "kind": "persona", "key": "bolt", "state": "OPEN", "pr": 11}]
        job = runner.pick_task_for_slot(slot_id=2, cfg=self.cfg, history=history, issues=[],
                                        registry=self.registry, repo_name="o/r")
        self.assertIsNone(job)


if __name__ == "__main__":
    unittest.main()

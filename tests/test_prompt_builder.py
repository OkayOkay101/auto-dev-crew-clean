import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.runner import Job
from auto_dev_crew.experimental.prompt_builder import (
    TieredPrompt,
    build_tiered_prompt,
    format_provider_payload,
    normalize_to_repo_relative,
)


class TestPromptBuilder(unittest.TestCase):
    def test_normalize_to_repo_relative(self):
        repo_root = Path("/projects/my-repo")
        text_with_abs = "Error in /projects/my-repo/src/main.py and /projects/my-repo/tests/test_main.py"
        normalized = normalize_to_repo_relative(text_with_abs, repo_root)
        self.assertEqual(normalized, "Error in src/main.py and tests/test_main.py")

        # Windows paths support
        win_root = Path(r"C:\Users\example\Documents\auto-dev-crew")
        win_text = r"Check file C:\Users\example\Documents\auto-dev-crew\auto_dev_crew\runner.py"
        win_norm = normalize_to_repo_relative(win_text, win_root)
        self.assertEqual(win_norm, "Check file auto_dev_crew/runner.py")

    def test_cross_slot_byte_deterministic_caching(self):
        """Tier A and Tier B must be byte-for-byte identical across Slot 1 and Slot 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            slot1_dir = base_dir / "_slot_1"
            slot2_dir = base_dir / "_slot_2"
            slot1_dir.mkdir()
            slot2_dir.mkdir()

            (slot1_dir / "app.py").write_text("def hello(): pass\n", encoding="utf-8")
            (slot2_dir / "app.py").write_text("def hello(): pass\n", encoding="utf-8")

            job1 = Job(kind="issue", key=101, title="Crash on login", body="details")
            job2 = Job(kind="issue", key=102, title="Crash on checkout", body="checkout details")
            rcfg = {"name": "test-org/repo"}

            # Build prompt for slot 1 and slot 2
            p1 = build_tiered_prompt(job1, rcfg, cwd=slot1_dir, env={}, history=[], result_path=slot1_dir / "res.json", slot_id=1)
            p2 = build_tiered_prompt(job2, rcfg, cwd=slot2_dir, env={}, history=[], result_path=slot2_dir / "res.json", slot_id=2)

            # Tier A must match 100%
            self.assertEqual(p1.tier_a_static, p2.tier_a_static)
            # Tier B (Repo Context + Stack Guidelines + Repo Skeleton) must match 100%
            self.assertEqual(p1.tier_b_semi_static, p2.tier_b_semi_static)

            # Tier C contains slot and issue differences
            self.assertNotEqual(p1.tier_c_dynamic, p2.tier_c_dynamic)
            self.assertIn("#101", p1.tier_c_dynamic)
            self.assertIn("#102", p2.tier_c_dynamic)

    def test_format_provider_payload_anthropic(self):
        prompt = TieredPrompt(
            tier_a_static="System static instructions",
            tier_b_semi_static="Repo skeleton and guidelines",
            tier_c_dynamic="Dynamic task #42"
        )
        payload = format_provider_payload(prompt, provider="anthropic")
        self.assertIsInstance(payload, dict)
        self.assertIn("system", payload)
        # Should have ephemeral cache control on static blocks
        system_blocks = payload["system"]
        self.assertEqual(len(system_blocks), 2)
        self.assertEqual(system_blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(system_blocks[1]["cache_control"], {"type": "ephemeral"})

    def test_persona_prompt_tiered_structure(self):
        job = Job(kind="persona", key="bolt", title="", body="")
        rcfg = {"name": "test-org/repo", "scanners": {}}
        prompt = build_tiered_prompt(job, rcfg, cwd=Path("."), env={}, history=[], result_path=Path("res.json"), slot_id=2)

        self.assertTrue(prompt.tier_a_static.startswith("# Role: ⚡ Bolt — Performance Engineer"))
        self.assertIn("## Performance Engineering Workflow", prompt.tier_a_static)
        self.assertIn("## Detected Tech Stack Guidelines", prompt.tier_b_semi_static)
        self.assertIn("# Final Result Delivery", prompt.tier_c_dynamic)

    def test_tiered_prompt_has_three_tiers(self):
        result_file = Path("state/test_tiered_result.json")
        job = Job(kind="issue", key=99, title="Optimize query latency", body="Query is too slow")
        rcfg = {"name": "test-org/test-repo"}
        tiered_prompt = build_tiered_prompt(job, rcfg, cwd=Path("."), env={}, history=[], result_path=result_file)

        self.assertTrue(hasattr(tiered_prompt, "tier_a_static"))
        self.assertTrue(hasattr(tiered_prompt, "tier_b_semi_static"))
        self.assertTrue(hasattr(tiered_prompt, "tier_c_dynamic"))
        self.assertIn("# Role: Senior Autonomous Software Engineer", tiered_prompt.tier_a_static)
        self.assertIn("Optimize query latency", tiered_prompt.tier_c_dynamic)


if __name__ == "__main__":
    unittest.main()

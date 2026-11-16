import unittest
from pathlib import Path

from auto_dev_crew.skill_registry import SkillRegistry


class TestSkillRegistry(unittest.TestCase):
    def test_builtin_skills_registration(self):
        registry = SkillRegistry(search_paths=[])
        registry.register_builtin_skills()
        skills = registry.scan_skills()
        self.assertIn("memory-leak-debugging", skills)
        self.assertIn("a11y-debugging", skills)
        self.assertIn("improve-codebase-architecture", skills)
        self.assertIn("security-audit", skills)

    def test_persona_matching_bolt(self):
        registry = SkillRegistry(search_paths=[])
        registry.register_builtin_skills()
        matched = registry.get_skills_for_persona("bolt", limit=2)
        matched_names = [s.name for s in matched]
        self.assertIn("memory-leak-debugging", matched_names)

    def test_persona_matching_palette(self):
        registry = SkillRegistry(search_paths=[])
        registry.register_builtin_skills()
        matched = registry.get_skills_for_persona("palette", limit=2)
        matched_names = [s.name for s in matched]
        self.assertIn("a11y-debugging", matched_names)

    def test_configured_skills_override(self):
        registry = SkillRegistry(search_paths=[])
        registry.register_builtin_skills()
        matched = registry.get_skills_for_persona(
            "bolt",
            configured_skills=["security-audit"]
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].name, "security-audit")

    def test_format_skills_for_prompt(self):
        registry = SkillRegistry(search_paths=[])
        registry.register_builtin_skills()
        skills = registry.get_skills_for_persona("sentinel")
        formatted = registry.format_skills_for_prompt(skills)
        self.assertIn("security-audit", formatted)
        self.assertTrue(formatted.startswith("- **"))

    def test_scan_local_skills_folder(self):
        local_skills_dir = Path(__file__).resolve().parent.parent / "skills"
        registry = SkillRegistry(search_paths=[local_skills_dir])
        skills = registry.scan_skills()
        self.assertIn("memory-leak-debugging", skills)
        self.assertEqual(skills["memory-leak-debugging"].name, "memory-leak-debugging")
        self.assertIn("performance", skills["memory-leak-debugging"].tags)


if __name__ == "__main__":
    unittest.main()

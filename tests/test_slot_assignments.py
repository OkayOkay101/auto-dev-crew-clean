import unittest
from auto_dev_crew.runner import (
    get_slot_assignment,
    parse_issue_persona_directive,
)


class TestSlotAssignments(unittest.TestCase):
    def test_get_slot_assignment(self):
        cfg = {
            "parallel": {
                "slots": 3,
                "assignments": {
                    "slot_2": {"persona": "quality", "repo": "example-owner/example-repo-2"},
                    "slot_3": {"persona": "bolt", "repo": "example-owner/example-repo"},
                }
            }
        }
        assign2 = get_slot_assignment(2, cfg)
        self.assertEqual(assign2, {"persona": "quality", "repo": "example-owner/example-repo-2"})

        assign3 = get_slot_assignment(3, cfg)
        self.assertEqual(assign3, {"persona": "bolt", "repo": "example-owner/example-repo"})

        assign1 = get_slot_assignment(1, cfg)
        self.assertIsNone(assign1)

    def test_parse_issue_persona_directive(self):
        title = "Fix audio bug"
        body = "Please look at this.\nPersona: Quality\nMore details."
        persona, clean_b = parse_issue_persona_directive(title, body)
        self.assertEqual(persona, "quality")
        self.assertNotIn("Persona: Quality", clean_b)

        # In title
        title2 = "[Persona: Bolt] Speed up escapeHtml"
        body2 = "Speed is slow"
        persona2, clean_b2 = parse_issue_persona_directive(title2, body2)
        self.assertEqual(persona2, "bolt")

        # No directive
        p_none, b_none = parse_issue_persona_directive("Normal title", "Normal body")
        self.assertIsNone(p_none)
        self.assertEqual(b_none, "Normal body")


if __name__ == "__main__":
    unittest.main()

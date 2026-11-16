import unittest

from auto_dev_crew import runner
from auto_dev_crew.runner import Job


class TestPersonaJudgeGoal(unittest.TestCase):
    """F-11: the eval judge must get a real goal for persona jobs, not the placeholder text."""

    def test_persona_job_goal_is_not_placeholder(self):
        job = Job(kind="persona", key="palette", title="Persona palette", body="")
        desc = runner.task_description_for_job(job)
        self.assertNotEqual(desc, "Persona palette goal")
        self.assertIn("UX", desc)

    def test_every_builtin_persona_has_a_concrete_goal(self):
        for key in ("bolt", "sentinel", "palette", "quality"):
            job = Job(kind="persona", key=key, title="", body="")
            desc = runner.task_description_for_job(job)
            self.assertGreater(len(desc), 60, key)
            self.assertNotIn("goal", desc.lower().split(), key)

    def test_low_value_personas_forbid_cosmetic_and_impossible_input_work(self):
        palette = runner.task_description_for_job(Job(kind="persona", key="palette", title="", body=""))
        quality = runner.task_description_for_job(Job(kind="persona", key="quality", title="", body=""))
        self.assertIn("Do NOT make cosmetic-only changes", palette)
        self.assertIn("Symbol or BigInt", quality)
        self.assertIn("NOT add tests that only search source code", quality)

    def test_issue_job_keeps_title_and_body(self):
        job = Job(kind="issue", key="7", title="add hello()", body="return 'hi'")
        self.assertEqual(runner.task_description_for_job(job), "add hello()\n\nreturn 'hi'")


if __name__ == "__main__":
    unittest.main()

import unittest

from auto_dev_crew.experimental.auditor import (
    PatchSpec,
    PatchTarget,
    build_auditor_prompt,
    build_worker_prompt,
    parse_patch_spec,
)


class TestAuditor(unittest.TestCase):
    def test_parse_patch_spec_from_json_string(self):
        raw_json = '''```json
{
  "summary": "Fix race condition in central merge queue",
  "targets": [
    {
      "file": "auto_dev_crew/locks.py",
      "line_range": [45, 60],
      "issue": "Lock file is not flushed before checking existence",
      "instruction": "Add file.flush() and os.fsync(file.fileno()) before returning lock handle"
    }
  ],
  "verification_command": "pytest tests/test_locks.py -q"
}
```'''
        spec = parse_patch_spec(raw_json)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.summary, "Fix race condition in central merge queue")
        self.assertEqual(len(spec.targets), 1)
        self.assertEqual(spec.targets[0].file, "auto_dev_crew/locks.py")
        self.assertEqual(spec.targets[0].line_range, [45, 60])
        self.assertEqual(spec.verification_command, "pytest tests/test_locks.py -q")

    def test_parse_patch_spec_invalid_json(self):
        self.assertIsNone(parse_patch_spec("Not a valid json output"))

    def test_build_auditor_prompt(self):
        prompt = build_auditor_prompt(
            repo="test-org/test-repo",
            task_desc="Fix memory leak in websocket connection",
            repo_skeleton="class WSConnection: ...",
        )
        self.assertIn("# Role: Tier-1 Senior Diagnostic Auditor", prompt)
        self.assertIn("Fix memory leak in websocket connection", prompt)
        self.assertIn("class WSConnection: ...", prompt)
        self.assertIn("Strict JSON Patch Spec", prompt)

    def test_build_worker_prompt(self):
        spec = PatchSpec(
            summary="Fix division by zero",
            targets=[
                PatchTarget(
                    file="calc.py",
                    line_range=[10, 15],
                    issue="ZeroDivisionError when b == 0",
                    instruction="Add check if b == 0: raise ValueError('Cannot divide by zero')",
                )
            ],
            verification_command="pytest tests/test_calc.py -q",
        )
        file_snippets = {"calc.py": "def divide(a, b):\n    return a / b\n"}
        prompt = build_worker_prompt(spec, file_snippets, repo="test-org/calc")

        self.assertIn("# Role: Tier-2 Surgical Code Worker", prompt)
        self.assertIn("Fix division by zero", prompt)
        self.assertIn("`calc.py` (Lines 10-15)", prompt)
        self.assertIn("pytest tests/test_calc.py -q", prompt)
        self.assertIn("def divide(a, b):", prompt)


if __name__ == "__main__":
    unittest.main()

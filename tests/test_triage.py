import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew.runner import Job
from auto_dev_crew.triage import classify_task


class TestTriageEngine(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "triage": {
                "enabled": True,
                "use_llm_fallback": False,
                "fast_labels": ["quick-fix", "typo", "docs", "minor"],
                "heavy_labels": ["feature", "architecture", "refactor", "breaking", "security"],
            }
        }

    def test_fast_path_by_label(self):
        job = Job("issue", "1", "Fix typo in readme", "Just fix spelling", labels=["typo"])
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "fast")
        self.assertEqual(result.method, "heuristic")
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_heavy_path_by_label(self):
        job = Job("issue", "2", "Add payment gateway", "Large implementation", labels=["feature"])
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "heavy")
        self.assertEqual(result.method, "heuristic")
        self.assertGreaterEqual(result.confidence, 0.9)

    def test_fast_path_short_description(self):
        job = Job("issue", "3", "Fix spelling", "one line text", labels=[])
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "fast")
        self.assertEqual(result.method, "heuristic")

    def test_heavy_path_long_description(self):
        long_body = "x" * 2000
        job = Job("issue", "4", "Big migration plan", long_body, labels=[])
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "heavy")
        self.assertEqual(result.method, "heuristic")

    def test_persona_sentinel_is_heavy(self):
        job = Job("persona", "sentinel", "sentinel", "")
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "heavy")

    def test_persona_palette_is_fast(self):
        job = Job("persona", "palette", "palette", "")
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "fast")

    def test_ambiguous_falls_back_to_heavy_when_no_llm(self):
        # Medium length, no labels
        job = Job("issue", "5", "Investigate cache issue", "A" * 400, labels=[])
        result = classify_task(job, self.cfg)
        self.assertEqual(result.path, "heavy")
        self.assertEqual(result.method, "heuristic_default")

    def test_llm_fallback_when_ambiguous(self):
        cfg_with_llm = dict(self.cfg)
        cfg_with_llm["triage"] = {
            "enabled": True,
            "use_llm_fallback": True,
            "fast_labels": ["quick-fix"],
            "heavy_labels": ["feature"],
        }
        job = Job("issue", "6", "Moderate task", "A" * 400, labels=[])
        mock_response = '```json\n{"path": "fast", "reason": "Self-contained single function fix", "confidence": 0.85}\n```'
        with mock.patch("auto_dev_crew.triage._call_llm_classifier", return_value=mock_response):
            result = classify_task(job, cfg_with_llm)
            self.assertEqual(result.path, "fast")
            self.assertEqual(result.method, "llm")
            self.assertAlmostEqual(result.confidence, 0.85)

    def test_llm_classifier_runs_in_temp_dir_not_project_root(self):
        from auto_dev_crew.triage import _call_llm_classifier
        job = Job("issue", "10", "Check cwd", "Body", labels=[])
        seen = {}

        def fake_call(cfg, prompt, cwd, **kwargs):
            seen["cwd"] = Path(cwd)
            seen["existed"] = Path(cwd).is_dir()
            return {"status": "SUCCESS", "response": '{"path": "fast"}'}

        with mock.patch("auto_dev_crew.runner.call_agent", side_effect=fake_call):
            _call_llm_classifier(job, self.cfg)
        self.assertTrue(seen["existed"])
        self.assertNotEqual(seen["cwd"].resolve(), Path.cwd().resolve())
        self.assertNotEqual(seen["cwd"].resolve(), Path(__file__).resolve().parent.parent)
        self.assertFalse(seen["cwd"].exists())  # scratch dir is cleaned up

    def test_llm_fallback_error_is_logged_not_swallowed(self):
        cfg = {"triage": {"enabled": True, "use_llm_fallback": True,
                          "fast_labels": [], "heavy_labels": []}}
        job = Job("issue", "11", "Moderate task", "A" * 400, labels=[])
        with mock.patch("auto_dev_crew.triage._call_llm_classifier", side_effect=RuntimeError("boom")):
            with self.assertLogs("auto_dev_crew.triage", level="WARNING") as cm:
                result = classify_task(job, cfg)
        self.assertEqual(result.method, "heuristic_default")
        self.assertIn("boom", "\n".join(cm.output))

    def test_call_llm_classifier_handles_dict_response_from_runner(self):
        from auto_dev_crew.triage import _call_llm_classifier
        job = Job("issue", "7", "Check dict handling", "Body", labels=[])
        dict_resp = {
            "status": "SUCCESS",
            "response": '```json\n{"path": "fast", "reason": "Quick fix", "confidence": 0.9}\n```'
        }
        with mock.patch("auto_dev_crew.runner.call_agent", return_value=dict_resp):
            resp_str = _call_llm_classifier(job, self.cfg)
            self.assertIsInstance(resp_str, str)
            self.assertIn('"path": "fast"', resp_str)


if __name__ == "__main__":
    unittest.main()

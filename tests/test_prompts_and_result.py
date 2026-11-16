import json
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.runner import build_prompt, read_result, Job


class TestPromptsAndModelCompatibility(unittest.TestCase):
    def test_rules_has_no_dynamic_placeholders(self):
        rules_text = (Path(__file__).parent.parent / "prompts" / "_rules.md").read_text(encoding="utf-8")
        self.assertNotIn("{{repo}}", rules_text)
        self.assertNotIn("{{result_path}}", rules_text)
        self.assertIn("## Core Rules (Non-negotiable)", rules_text)
        self.assertIn("## Output Schema", rules_text)

    def test_task_prompt_static_prefix(self):
        result_file = Path("state/test_result.json")
        job = Job(kind="issue", key=42, title="Fix login crash", body="Crash occurs when password is empty")
        rcfg = {"name": "test-org/test-repo"}
        prompt = build_prompt(job, rcfg, cwd=Path("."), env={}, history=[], result_path=result_file)

        # Static prefix must be at the very beginning
        self.assertTrue(prompt.startswith("# Role: Senior Autonomous Software Engineer"))
        self.assertIn("## Core Rules (Non-negotiable)", prompt)
        self.assertIn("## Engineering Workflow", prompt)

        # Dynamic context must appear lower in the prompt
        idx_workflow = prompt.index("## Engineering Workflow")
        idx_repo = prompt.index("- **Repository**: `test-org/test-repo`")
        idx_issue = prompt.index("- **Assigned Issue**: #42")
        idx_delivery = prompt.index("# Final Result Delivery")

        self.assertLess(idx_workflow, idx_repo)
        self.assertLess(idx_repo, idx_issue)
        self.assertLess(idx_issue, idx_delivery)
        self.assertIn(str(result_file), prompt)

    def test_persona_prompt_static_prefix(self):
        result_file = Path("state/test_bolt_result.json")
        job = Job(kind="persona", key="bolt", title="", body="")
        rcfg = {"name": "test-org/test-repo", "scanners": {}}
        prompt = build_prompt(job, rcfg, cwd=Path("."), env={}, history=[], result_path=result_file)

        # Static role and workflow first
        self.assertTrue(prompt.startswith("# Role: ⚡ Bolt — Performance Engineer"))
        self.assertIn("## Core Rules (Non-negotiable)", prompt)
        self.assertIn("## Performance Engineering Workflow", prompt)

        idx_workflow = prompt.index("## Performance Engineering Workflow")
        idx_context = prompt.index("# Target Execution Context")
        idx_delivery = prompt.index("# Final Result Delivery")

        self.assertLess(idx_workflow, idx_context)
        self.assertLess(idx_context, idx_delivery)
        self.assertIn(str(result_file), prompt)

    def test_persona_dynamic_stack_injection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "requirements.txt").write_text("streamlit\npandas\n", encoding="utf-8")
            result_file = tmp / "result.json"

            job = Job(kind="persona", key="bolt", title="", body="")
            rcfg = {"name": "test-org/test-repo", "scanners": {}}
            prompt = build_prompt(job, rcfg, cwd=tmp, env={}, history=[], result_path=result_file)

            self.assertIn("## Detected Tech Stack Guidelines", prompt)
            self.assertIn("Streamlit Framework Guidelines", prompt)
            self.assertIn("Pandas Optimization Guidelines", prompt)
            # Ensure hardcoded TOU domain specifics are no longer present in bolt prompt
            self.assertNotIn("tou_analyzer.py", prompt)
            self.assertNotIn("TOU electricity data", prompt)
            # Ensure dynamic skill injection is present
            self.assertIn("## Active Specialized Skills", prompt)
            self.assertIn("memory-leak-debugging", prompt)

    def test_persona_configured_skills_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result_file = tmp / "result.json"

            job = Job(kind="persona", key="sentinel", title="", body="")
            rcfg = {
                "name": "test-org/test-repo",
                "scanners": {},
                "personas": {
                    "skills": {
                        "sentinel": ["custom-waf-guard", "security-audit"]
                    }
                }
            }
            prompt = build_prompt(job, rcfg, cwd=tmp, env={}, history=[], result_path=result_file)

            self.assertIn("## Active Specialized Skills", prompt)
            self.assertIn("custom-waf-guard", prompt)
            self.assertIn("security-audit", prompt)

    def test_read_result_various_model_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # 1. Pure valid JSON
            f1 = tmp / "pure.json"
            f1.write_text(json.dumps({"status": "DONE", "title_th": "ทดสอบ 1"}), encoding="utf-8")
            self.assertEqual(read_result(f1).get("status"), "DONE")

            # 2. Markdown fenced JSON (```json ... ```)
            f2 = tmp / "fenced.json"
            f2.write_text('```json\n{"status": "DONE", "title_th": "ทดสอบ 2"}\n```', encoding="utf-8")
            self.assertEqual(read_result(f2).get("status"), "DONE")
            self.assertEqual(read_result(f2).get("title_th"), "ทดสอบ 2")

            # 3. Conversational preamble + JSON block
            f3 = tmp / "conversational.json"
            f3.write_text(
                'Here is the final required JSON output file:\n```json\n{"status": "NO_ACTION", "title_th": "ไม่ทำ"}\n```\nHope this helps!',
                encoding="utf-8"
            )
            self.assertEqual(read_result(f3).get("status"), "NO_ACTION")

            # 4. Empty or missing file
            f4 = tmp / "missing.json"
            self.assertEqual(read_result(f4), {})

            f5 = tmp / "empty.json"
            f5.write_text("", encoding="utf-8")
            self.assertEqual(read_result(f5), {})


def test_issue_body_placeholders_are_not_expanded():
    """LOW-04: an issue body containing {{result_path}} must stay literal (single-pass substitution)."""
    result_file = Path("state/test_single_pass.json")
    job = Job(kind="issue", key=7, title="t", body="see {{result_path}} and {{repo}} literally")
    rcfg = {"name": "test-org/test-repo"}
    prompt = build_prompt(job, rcfg, cwd=Path("."), env={}, history=[], result_path=result_file)
    assert "see {{result_path}} and {{repo}} literally" in prompt


def test_persona_skills_read_from_cfg_personas():
    """LOW-04: personas live in cfg; configured skills must be read from cfg (rcfg as fallback)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        job = Job(kind="persona", key="sentinel", title="", body="")
        rcfg = {"name": "test-org/test-repo", "scanners": {}}
        cfg = {"personas": {"skills": {"sentinel": ["cfg-only-skill"]}}}
        prompt = build_prompt(job, rcfg, cwd=tmp, env={}, history=[], result_path=tmp / "r.json", cfg=cfg)
        assert "cfg-only-skill" in prompt


def test_is_small_matches_protected_paths_by_segment():
    """LOW-03: 'config' must not match src/configuration_view.js; real protected files still match."""
    from auto_dev_crew.runner import is_small
    cfg = {"small_pr": {"max_lines": 50, "protected_paths": [".github/", "requirements", ".jules/quality", "config"]}}
    assert is_small(cfg, 10, ["src/configuration_view.js"]) is True
    assert is_small(cfg, 10, ["src/myconfig.py"]) is True
    assert is_small(cfg, 10, ["config.yaml"]) is False
    assert is_small(cfg, 10, ["config/app.toml"]) is False
    assert is_small(cfg, 10, ["src/config/app.toml"]) is False
    assert is_small(cfg, 10, ["requirements.txt"]) is False
    assert is_small(cfg, 10, [".github/workflows/ci.yml"]) is False
    assert is_small(cfg, 10, [".jules/quality/rules.md"]) is False
    assert is_small(cfg, 60, ["src/a.py"]) is False


if __name__ == "__main__":
    unittest.main()

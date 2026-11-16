import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.stack_detector import (
    detect_stack,
    format_stack_guidelines,
    load_stack_guideline,
)


class TestStackDetector(unittest.TestCase):
    def test_load_stack_guideline_from_templates(self):
        prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
        guideline = load_stack_guideline("streamlit", prompts_dir=prompts_dir)
        self.assertIn("Streamlit Framework Guidelines", guideline)
        self.assertIn("st.cache_data", guideline)

    def test_detect_python_streamlit_pandas_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "requirements.txt").write_text("streamlit>=1.30.0\npandas>=2.0.0\npytest\n", encoding="utf-8")
            (p / "app.py").write_text("import streamlit as st\nimport pandas as pd\n", encoding="utf-8")

            profile = detect_stack(p)
            self.assertEqual(profile.primary_language, "python")
            self.assertIn("streamlit", profile.frameworks)
            self.assertIn("pandas", profile.frameworks)
            self.assertIn("pytest", profile.test_frameworks)

            guidelines = format_stack_guidelines(profile)
            self.assertIn("Streamlit", guidelines)
            self.assertIn("Pandas", guidelines)

    def test_detect_node_typescript_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "package.json").write_text('{"dependencies": {"react": "^18.0.0", "next": "^14.0.0"}}', encoding="utf-8")
            (p / "tsconfig.json").write_text('{}', encoding="utf-8")

            profile = detect_stack(p)
            self.assertEqual(profile.primary_language, "typescript")
            self.assertIn("react", profile.frameworks)
            self.assertIn("next", profile.frameworks)

            guidelines = format_stack_guidelines(profile)
            self.assertIn("TypeScript", guidelines)

    def test_detect_empty_or_unknown_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            profile = detect_stack(p)
            self.assertEqual(profile.primary_language, "unknown")
            self.assertEqual(profile.frameworks, [])

            guidelines = format_stack_guidelines(profile)
            self.assertIn("General", guidelines)


if __name__ == "__main__":
    unittest.main()

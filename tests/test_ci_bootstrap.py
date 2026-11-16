import tempfile
import unittest

import yaml
from pathlib import Path
from unittest import mock

from auto_dev_crew.ci_bootstrap import (
    has_ci_workflows,
    generate_ci_workflow_content,
    bootstrap_ci_workflow,
    create_bootstrap_ci_pr,
)


def _steps(content: str) -> list:
    return yaml.safe_load(content)["jobs"]["test"]["steps"]


class TestCIBootstrap(unittest.TestCase):
    def test_has_ci_workflows_empty_and_populated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            self.assertFalse(has_ci_workflows(p))

            wf_dir = p / ".github" / "workflows"
            wf_dir.mkdir(parents=True)
            self.assertFalse(has_ci_workflows(p))

            (wf_dir / "ci.yml").write_text("name: CI\n", encoding="utf-8")
            self.assertTrue(has_ci_workflows(p))

    def test_generate_ci_workflow_content_python(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "requirements.txt").write_text("pytest\n", encoding="utf-8")
            (p / "main.py").write_text("print('hello')\n", encoding="utf-8")

            rcfg = {
                "name": "user/python-repo",
                "base": "main",
                "setup": ["python -m pip install -r requirements.txt"],
                "test": ["python -m pytest -q"],
            }
            content = generate_ci_workflow_content(p, "user/python-repo", rcfg)
            self.assertIn("name: CI", content)
            self.assertIn("actions/checkout@v4", content)
            self.assertIn("actions/setup-python@v5", content)
            self.assertIn("python -m pytest -q", content)

    def test_generate_ci_workflow_content_nodejs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "package.json").write_text('{"name": "test-app"}', encoding="utf-8")
            (p / "test-runner.js").write_text("process.exit(0);", encoding="utf-8")

            rcfg = {
                "name": "user/node-repo",
                "base": "main",
                "setup": [],
                "test": ["node test-runner.js"],
            }
            content = generate_ci_workflow_content(p, "user/node-repo", rcfg)
            self.assertIn("name: CI", content)
            self.assertIn("actions/setup-node@v4", content)
            self.assertIn("node test-runner.js", content)

    def test_generate_ci_workflow_content_zero_dependency_js(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "core.js").write_text("console.log(1);", encoding="utf-8")
            (p / "test-runner.js").write_text("process.exit(0);", encoding="utf-8")

            rcfg = {
                "name": "user/zero-dep-repo",
                "base": "main",
                "setup": [],
                "test": ["node test-runner.js"],
            }
            content = generate_ci_workflow_content(p, "user/zero-dep-repo", rcfg)
            doc = yaml.safe_load(content)
            self.assertIn("actions/setup-node@v4", content)
            self.assertNotIn("cache", next(s for s in _steps(content) if s.get("uses") == "actions/setup-node@v4")["with"])
            self.assertFalse(any("npm install" in s.get("run", "") for s in _steps(content)))
            self.assertEqual(doc[True]["push"]["branches"], ["main", "master"])  # PyYAML reads on: as True  # base deduplicated against main/master

    def test_generate_ci_workflow_content_with_lockfile(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "package.json").write_text('{"name": "app"}', encoding="utf-8")
            (p / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")

            rcfg = {"name": "user/lock-repo", "base": "main"}
            content = generate_ci_workflow_content(p, "user/lock-repo", rcfg)
            steps = _steps(content)
            node_step = next(s for s in steps if s.get("uses") == "actions/setup-node@v4")
            self.assertEqual(node_step["with"]["cache"], "npm")
            self.assertTrue(any("npm ci" in s.get("run", "") for s in steps))

    def test_generate_ci_workflow_content_python_no_manifest(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "app.py").write_text("print(1)", encoding="utf-8")
            rcfg = {
                "name": "user/std-py-repo",
                "base": "main",
                "setup": [],
                "test": ["python -m unittest discover -s tests"],
            }
            content = generate_ci_workflow_content(p, "user/std-py-repo", rcfg)
            self.assertIn("actions/setup-python@v5", content)
            self.assertNotIn('cache: "pip"', content)

    def test_generate_ci_workflow_content_hybrid_node_and_python(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "core.js").write_text("module.exports = {};", encoding="utf-8")
            (p / "test-runner.js").write_text("process.exit(0);", encoding="utf-8")
            tests_dir = p / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_sample.py").write_text("import unittest", encoding="utf-8")

            rcfg = {
                "name": "user/hybrid-repo",
                "base": "main",
                "setup": [],
                "test": [
                    "node test-runner.js",
                    "python -m unittest discover -s tests -p 'test_*.py'",
                ],
            }
            content = generate_ci_workflow_content(p, "user/hybrid-repo", rcfg)
            self.assertIn("actions/setup-node@v4", content)
            self.assertIn("actions/setup-python@v5", content)
            self.assertIn("node test-runner.js", content)
            self.assertIn("python -m unittest discover", content)

    def test_bootstrap_ci_workflow_file_creation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir)
            (p / "requirements.txt").write_text("requests\n", encoding="utf-8")
            created = bootstrap_ci_workflow(p, "user/test-repo", {})
            self.assertIsNotNone(created)
            self.assertTrue(created.is_file())
            self.assertEqual(created.name, "ci.yml")

            # Subsequent call returns None since it now exists
            second_call = bootstrap_ci_workflow(p, "user/test-repo", {})
            self.assertIsNone(second_call)

    @mock.patch("auto_dev_crew.ci_bootstrap.clone")
    @mock.patch("auto_dev_crew.ci_bootstrap.gh")
    @mock.patch("auto_dev_crew.ci_bootstrap.run")
    def test_create_bootstrap_ci_pr_success(self, mock_run, mock_gh, mock_clone):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_path = Path(tmp_dir) / "workspace"
            repo_path.mkdir(parents=True)
            (repo_path / "app.py").write_text("print(1)\n", encoding="utf-8")
            mock_clone.return_value = repo_path

            mock_run.return_value = mock.MagicMock(returncode=0, stdout="ok", stderr="")
            mock_gh.return_value = "https://github.com/user/test-repo/pull/42"

            cfg = {"labels": {"pr": "ai-generated"}}
            rcfg = {"name": "user/test-repo", "base": "main"}

            url = create_bootstrap_ci_pr("user/test-repo", rcfg, cfg)
            self.assertEqual(url, "https://github.com/user/test-repo/pull/42")
            mock_gh.assert_called()


if __name__ == "__main__":
    unittest.main()

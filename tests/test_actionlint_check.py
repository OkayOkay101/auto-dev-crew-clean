"""actionlint gate for generated CI workflows."""
from __future__ import annotations

import shutil

import pytest

from auto_dev_crew import ci_bootstrap

HAS_ACTIONLINT = shutil.which("actionlint") is not None

GOOD = """name: CI
on:
  push:
    branches: [ main ]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo hi
"""


@pytest.mark.skipif(not HAS_ACTIONLINT, reason="actionlint not installed")
def test_valid_workflow_passes_actionlint():
    assert ci_bootstrap.actionlint_errors(GOOD) == []


@pytest.mark.skipif(not HAS_ACTIONLINT, reason="actionlint not installed")
def test_unknown_runner_label_is_reported():
    bad = GOOD.replace("runs-on: ubuntu-latest", "runs-on: ubuntu-latest-xx")
    errors = ci_bootstrap.actionlint_errors(bad)
    assert errors and any("ubuntu-latest-xx" in e for e in errors)


@pytest.mark.skipif(not HAS_ACTIONLINT, reason="actionlint not installed")
def test_undefined_expression_variable_is_reported():
    bad = GOOD.replace("echo hi", "echo ${{ foo.bar }}")
    errors = ci_bootstrap.actionlint_errors(bad)
    assert errors and any("foo" in e for e in errors)


def test_missing_actionlint_returns_none(monkeypatch):
    monkeypatch.setattr(ci_bootstrap.shutil, "which", lambda name: None)
    assert ci_bootstrap.actionlint_errors(GOOD) is None


@pytest.mark.skipif(not HAS_ACTIONLINT, reason="actionlint not installed")
def test_generated_workflow_passes_actionlint(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    content = ci_bootstrap.generate_ci_workflow_content(tmp_path, "o/r", {"test": ["pytest -q"]})
    assert ci_bootstrap.actionlint_errors(content) == []

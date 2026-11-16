"""Helpers for the smarter agent loop: bugfix and test-file detection, the regression-test gate
prompt, and a snapshot of the agent's working diff for the failure prompt."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_BUGFIX = re.compile(r"\b(?:bug|fix)", re.IGNORECASE)  # "bug", "fixes", "fixed"; not "debug" or "prefix"
_DEEP_SCAN_MARKER = "<!-- deep-scan:"  # first line of every issue rendered by deep_scan.render_issue_body
_DEEP_SCAN_CATEGORY = re.compile(r"^\*\*Category:\*\*[ \t]*(\S+)", re.MULTILINE)
_TEST_FILE = re.compile(r"^test_.*\.py$|_test\.py$|\.test\.js$")
_TEST_DIRS = {"tests", "test"}
_DIFF_TIMEOUT_S = 30


def is_bugfix(job) -> bool:
    """Issue jobs whose title, body or labels say bug or fix. Persona jobs are never bugfixes.

    Deep-scan issues are decided by their **Category:** field only (bug is the one bugfix category);
    their boilerplate ("**Suggested fix:**", the finding title) must not make them bugfixes."""
    if getattr(job, "kind", None) != "issue":
        return False
    body = job.body or ""
    if body.lstrip().startswith(_DEEP_SCAN_MARKER):
        match = _DEEP_SCAN_CATEGORY.search(body)
        return match is not None and match.group(1) == "bug"
    labels = getattr(job, "labels", None) or []
    text = " ".join([job.title or "", body, *(str(label) for label in labels)])
    return _BUGFIX.search(text) is not None


def test_files(files: list[str]) -> list[str]:
    """Changed paths that are test files: under a tests/ or test/ directory, or a test file by name."""
    found = []
    for path in files:
        parts = path.replace("\\", "/").split("/")
        if any(part in _TEST_DIRS for part in parts[:-1]) or _TEST_FILE.search(parts[-1]):
            found.append(path)
    return found


def touched_tests(files: list[str]) -> bool:
    """True when any changed path is a test file (see test_files)."""
    return bool(test_files(files))


def needs_test_gate(job, cfg: dict, status: str, files: list[str]) -> bool:
    """Gate a bugfix whose agent reported DONE but changed no test file (loop.require_test_for_bugfix, default true)."""
    if not ((cfg.get("loop") or {}).get("require_test_for_bugfix", True)):
        return False
    return status == "DONE" and is_bugfix(job) and bool(files) and not touched_tests(files)


def regression_test_prompt(result_path: Path) -> str:
    return (
        "## Regression test required\n"
        "This is a bugfix, but your changes do not touch any test file. "
        "Add a regression test that fails without your fix and passes with it. "
        "Keep every existing test unchanged. Then overwrite the result JSON at: "
        f"{result_path}"
    )


def current_diff(cwd: Path, max_chars: int = 4000) -> str:
    """Tracked changes (staged and unstaged) against HEAD, truncated head+tail. Empty string on any error."""
    try:
        res = subprocess.run(["git", "diff", "HEAD"], cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                             timeout=_DIFF_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    if res.returncode != 0:
        return ""
    text = res.stdout
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    return text[:head] + "\n... [truncated] ...\n" + text[-(max_chars - head):]

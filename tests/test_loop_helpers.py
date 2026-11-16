"""Task 3 helpers: bugfix detection, test-file detection and the working-diff snapshot for the fix prompt."""
from __future__ import annotations

import subprocess
from pathlib import Path

from auto_dev_crew import loop_helpers
from auto_dev_crew.runner import Job


def test_is_bugfix_matches_title_body_or_label():
    assert loop_helpers.is_bugfix(Job("issue", "1", "Fix crash", ""))
    assert loop_helpers.is_bugfix(Job("issue", "1", "Login broken", "This is a bug in login"))
    assert loop_helpers.is_bugfix(Job("issue", "1", "Thing", "", labels=["Bug"]))


def test_is_bugfix_rejects_features_and_substrings_like_debug():
    assert not loop_helpers.is_bugfix(Job("issue", "1", "Add thing", "please add thing"))
    assert not loop_helpers.is_bugfix(Job("issue", "1", "Add debug panel", ""))


def test_is_bugfix_false_for_persona_jobs():
    assert not loop_helpers.is_bugfix(Job("persona", "fixer", "Fix things", "bug"))


def _deep_scan_body(category: str, title: str = "Tab-navigation benchmark results are discarded") -> str:
    return (
        "<!-- deep-scan:auto_dev_crew/bench.py:abcd1234 -->\n\n"
        "`auto_dev_crew/bench.py:10`\n\n"
        f"**Category:** {category}\n\n"
        "**Severity:** low\n\n"
        f"**{title}**\n\n"
        "```\nresults = []\n```\n\n"
        "**Suggested fix:** keep the results and add a regression test for the fix.\n"
    )


def test_is_bugfix_false_for_deep_scan_quality_issue_with_suggested_fix_text():
    job = Job("issue", "92", "[deep-scan] Tab-navigation benchmark results are discarded",
              _deep_scan_body("quality"), labels=["ai-task"])
    assert not loop_helpers.is_bugfix(job)


def test_is_bugfix_true_for_deep_scan_bug_category():
    job = Job("issue", "93", "[deep-scan] Results are discarded",
              _deep_scan_body("bug", title="Results are discarded"), labels=["ai-task"])
    assert loop_helpers.is_bugfix(job)


def test_is_bugfix_deep_scan_ignores_title_words_when_category_is_not_bug():
    job = Job("issue", "94", "[deep-scan] Bug and fix needed here", _deep_scan_body("missing-test"))
    assert not loop_helpers.is_bugfix(job)


def test_is_bugfix_human_issue_titled_fix_is_still_bugfix():
    job = Job("issue", "95", "fix crash on empty input", "Steps to reproduce below.", labels=["ai-task"])
    assert loop_helpers.is_bugfix(job)


def test_touched_tests_detects_test_dirs_and_test_file_names():
    assert loop_helpers.touched_tests(["tests/test_a.py"])
    assert loop_helpers.touched_tests(["test/helper.py"])
    assert loop_helpers.touched_tests(["pkg/test_util.py"])
    assert loop_helpers.touched_tests(["src/foo_test.py"])
    assert loop_helpers.touched_tests(["web/app.test.js"])
    assert loop_helpers.touched_tests(["auto_dev_crew/x.py", "tests/test_b.py"])
    assert loop_helpers.touched_tests(["tests\\test_win.py"])


def test_touched_tests_false_without_test_files():
    assert not loop_helpers.touched_tests([])
    assert not loop_helpers.touched_tests(["auto_dev_crew/x.py", "README.md"])


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_current_diff_shows_uncommitted_changes(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")

    diff = loop_helpers.current_diff(tmp_path)

    assert "+x = 2" in diff
    assert "-x = 1" in diff


def test_current_diff_empty_outside_git(tmp_path):
    assert loop_helpers.current_diff(tmp_path) == ""


def test_current_diff_truncates_long_output(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "big.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "big.txt").write_text("".join(f"line {i}\n" for i in range(5000)), encoding="utf-8")

    diff = loop_helpers.current_diff(tmp_path, max_chars=500)

    assert "[truncated]" in diff
    assert len(diff) < 700


def test_needs_test_gate_only_for_done_bugfix_without_tests():
    job = Job("issue", "5", "Fix crash", "")
    assert loop_helpers.needs_test_gate(job, {}, "DONE", ["auto_dev_crew/x.py"])
    assert not loop_helpers.needs_test_gate(job, {}, "DONE", ["tests/test_x.py"])
    assert not loop_helpers.needs_test_gate(job, {}, "NO_ACTION", ["auto_dev_crew/x.py"])
    assert not loop_helpers.needs_test_gate(Job("issue", "5", "Add thing", ""), {}, "DONE", ["auto_dev_crew/x.py"])
    assert not loop_helpers.needs_test_gate(job, {"loop": {"require_test_for_bugfix": False}}, "DONE", ["auto_dev_crew/x.py"])
    assert loop_helpers.needs_test_gate(job, {"loop": None}, "DONE", ["auto_dev_crew/x.py"])

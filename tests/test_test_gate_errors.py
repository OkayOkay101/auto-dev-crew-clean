"""Task 3 fix round 1: the regression-test gate round must survive agent ERROR returns and exceptions,
recompute lines/files after the round, and follow the NO_ACTION path when the round leaves no changes."""
from __future__ import annotations

from unittest import mock

from auto_dev_crew import runner
from auto_dev_crew.runner import Job

REPO = "example-owner/repo-alpha"
PR_URL = "https://github.com/example-owner/repo-alpha/pull/7"


def make_cfg(**overrides) -> dict:
    cfg = {
        "owner": "example-owner",
        "labels": {"task": "ai-task", "pause": "ai-pause", "working": "ai-working",
                   "failed": "ai-failed", "pr": "ai-pr"},
        "max_fix_attempts": 2,
        "merge_mode": "merge-all",
        "small_pr": {"max_lines": 50, "protected_paths": []},
        "evaluation": {"enabled": True, "max_eval_refinements": 0},
        "triage": {"enabled": False},
        "ci": {"enabled": False, "auto_rebase": False},
        "parallel": {"slots": 3},
        "personas": {"enabled": []},
        "repos": [{"name": REPO, "base": "main"}],
    }
    cfg.update(overrides)
    return cfg


def make_rcfg() -> dict:
    return {"name": REPO, "base": "main", "setup": [], "test": ["make test"]}


def bugfix() -> Job:
    return Job("issue", "5", "Fix crash in login", "login crashes on empty password")


def history_entry(key: str = "5") -> dict:
    entries = [e for e in runner.load_history() if e.get("key") == key]
    assert entries, "execute() did not append a history entry"
    return entries[-1]


def scripted_tests(pipeline, outcomes: list[tuple[bool, str]]) -> None:
    """Empty step lists are setup and always pass; test runs consume `outcomes` in order, then repeat the last."""
    queue = list(outcomes)

    def steps(test_steps, cwd, env, *args, **kwargs):
        if not test_steps:
            return True, ""
        return queue.pop(0) if len(queue) > 1 else queue[0]

    pipeline.run_steps.side_effect = steps


def gate_round_does(pipeline, action) -> None:
    """Run `action` in place of the agent on the second call_agent call (the gate round); earlier calls use the fake."""
    inner = pipeline.call_agent.side_effect

    def agent(cfg, prompt, cwd, slot_id=None, role="coder"):
        if pipeline.call_agent.call_count == 2:
            return action()
        return inner(cfg, prompt, cwd, slot_id=slot_id, role=role)

    pipeline.call_agent.side_effect = agent


def gate_round_returns_error() -> dict:
    return {"status": "ERROR", "response": "engine exploded"}


def gate_round_raises():
    raise RuntimeError("engine crashed mid-round")


def test_gate_error_return_with_passing_tests_still_opens_pr(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])
    gate_round_does(fake_pipeline, gate_round_returns_error)

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 2
    assert fake_pipeline.run_steps.call_count >= 2, "tests must rerun after a failed gate round"
    entry = history_entry()
    assert entry["test_gate_error"] is True
    assert "test_gate_round" not in entry
    assert fake_gh.calls_with("pr", "create")


def test_gate_error_return_with_failing_tests_marks_failed(fake_gh, fake_pipeline):
    scripted_tests(fake_pipeline, [(True, "ok"), (False, "FAILED test_gate\nboom")])
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])
    gate_round_does(fake_pipeline, gate_round_returns_error)

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert not fake_gh.calls_with("pr", "create")
    entry = history_entry()
    assert entry["state"] == "FAILED"
    assert entry["test_gate_error"] is True
    assert "boom" in entry["fail_reason"]


def test_gate_exception_with_passing_tests_still_opens_pr(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])
    gate_round_does(fake_pipeline, gate_round_raises)

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    entry = history_entry()
    assert entry["test_gate_error"] is True
    assert "test_gate_round" not in entry
    assert fake_gh.calls_with("pr", "create")


def test_gate_exception_with_failing_tests_marks_failed(fake_gh, fake_pipeline):
    scripted_tests(fake_pipeline, [(True, "ok"), (False, "FAILED test_gate\nboom")])
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])
    gate_round_does(fake_pipeline, gate_round_raises)

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert not fake_gh.calls_with("pr", "create")
    entry = history_entry()
    assert entry["state"] == "FAILED"
    assert entry["test_gate_error"] is True


def test_gate_recomputes_lines_and_files_after_round(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)

    def stats(cwd):
        if fake_pipeline.call_agent.call_count >= 2:  # the gate round wrote a regression test
            return (40, ["auto_dev_crew/x.py", "tests/test_x.py"])
        return (12, ["auto_dev_crew/x.py"])

    fake_pipeline.diff_stats.side_effect = stats

    # The pipeline is mocked, so there is no real base worktree to run the new test against.
    # Stub the reproduction check as "the new test fails without the fix" (tested in test_judge_gate.py).
    with mock.patch.object(runner, "_new_tests_fail_on_base", return_value=True):
        runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    entry = history_entry()
    assert entry["lines"] == 40
    assert entry["test_gate_round"] is True
    assert "no_test_added" not in entry
    assert fake_gh.calls_with("pr", "create")


def test_gate_round_leaving_no_changes_takes_no_action_path(fake_gh, fake_pipeline):
    def stats(cwd):
        if fake_pipeline.call_agent.call_count >= 2:
            return (0, [])
        return (12, ["auto_dev_crew/x.py"])

    fake_pipeline.diff_stats.side_effect = stats

    msg = runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่มีการเปลี่ยนแปลง" in msg
    assert not fake_gh.calls_with("pr", "create"), "no PR for an empty result"
    entry = history_entry()
    assert entry["state"] == "NO_ACTION"
    assert fake_pipeline.evaluate_diff.call_count == 0, "eval must not run on an empty diff"

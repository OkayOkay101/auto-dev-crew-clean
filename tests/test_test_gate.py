"""Task 3: the failure prompt carries the delta and the working diff; bugfix jobs without a test change
get one extra agent round asking for a regression test (execute() path, FakePipeline)."""
from __future__ import annotations

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


def test_bugfix_without_test_change_gets_one_regression_round(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 2
    gate_prompt = fake_pipeline.call_agent.call_args_list[1].args[1]
    assert "regression test" in gate_prompt
    entry = history_entry()
    assert entry["test_gate_round"] is True
    assert entry["no_test_added"] is True
    assert fake_gh.calls_with("pr", "create"), "gate must not block the PR when no test was added"


def test_gate_not_run_when_a_test_file_changed(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py", "tests/test_x.py"])

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 1
    assert "test_gate_round" not in history_entry()


def test_gate_not_run_for_non_bugfix(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 1


def test_gate_disabled_by_config(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(bugfix(), make_cfg(loop={"require_test_for_bugfix": False}), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 1


def test_gate_skipped_when_agent_status_not_done(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), PR_URL)
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "ไม่ต้องแก้"}
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=True)

    assert fake_pipeline.call_agent.call_count == 1


def test_gate_round_test_failure_marks_job_failed(fake_gh, fake_pipeline):
    scripted_tests(fake_pipeline, [(True, "ok"), (False, "FAILED test_gate\nboom")])
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.call_agent.call_count == 2
    assert not fake_gh.calls_with("pr", "create"), "PR must not open when tests fail after the gate round"
    entry = history_entry()
    assert entry["state"] == "FAILED"
    assert "boom" in entry["fail_reason"]


def test_gate_also_runs_in_dry_run(fake_gh, fake_pipeline):
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(bugfix(), make_cfg(), make_rcfg(), [], dry_run=True)

    assert fake_pipeline.call_agent.call_count == 2
    entry = history_entry()
    assert entry["state"] == "DRY_RUN"
    assert entry["test_gate_round"] is True


def test_failure_prompt_carries_delta_feedback_and_working_diff(fake_gh, fake_pipeline):
    scripted_tests(fake_pipeline, [(False, "FAILED test_a\nboom"), (True, "ok")])
    fake_pipeline.diff_stats.return_value = (12, ["auto_dev_crew/x.py"])

    runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=True)

    retry_prompt = fake_pipeline.call_agent.call_args_list[1].args[1]
    assert "## Verification Feedback & Errors (Delta)" in retry_prompt
    assert "FAILED test_a" in retry_prompt
    assert "## Your changes so far" in retry_prompt

"""Phase 0: execute() records which engine finished the job, how many agent rounds ran,
and (on FAILED) the tail of the failing test output, into the history entry."""
from __future__ import annotations

from auto_dev_crew import runner
from auto_dev_crew.runner import Job

REPO = "example-owner/repo-alpha"


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
    # Not a pytest command: _prepare_workspace drops pytest steps when the (fake, empty) clone has no .py files.
    return {"name": REPO, "base": "main", "setup": [], "test": ["make test"]}


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


def report_engine(pipeline, engine: str | None) -> None:
    """Make the fake agent report which engine served the call (as call_agent does)."""
    inner = pipeline.call_agent.side_effect

    def agent(cfg, prompt, cwd, slot_id=None, role="coder"):
        inner(cfg, prompt, cwd, slot_id=slot_id, role=role)
        return {"status": "DONE", "engine_used": engine}

    pipeline.call_agent.side_effect = agent


def test_success_entry_records_engine_and_fix_rounds(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/7")
    report_engine(fake_pipeline, "nvidia")

    runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=False)

    entry = history_entry()
    assert entry["engine"] == "nvidia"
    assert entry["fix_rounds"] == 1


def test_fix_rounds_counts_every_agent_call(fake_gh, fake_pipeline):
    scripted_tests(fake_pipeline, [(False, "FAILED test_a\nboom"), (True, "ok")])
    report_engine(fake_pipeline, "mistral")

    runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=True)

    entry = history_entry()
    assert entry["fix_rounds"] == 2
    assert entry["engine"] == "mistral"


def test_engine_omitted_when_agent_reports_none(fake_gh, fake_pipeline):
    """engine/fix_rounds are copied only when present; a missing engine_used is not written as a key."""
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/7")

    runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=False)

    entry = history_entry()
    assert "engine" not in entry
    assert entry["fix_rounds"] == 1


def test_failed_entry_records_fail_reason_tail(fake_gh, fake_pipeline):
    long_out = "x" * 500 + " FAILED test_a TAILMARK"
    scripted_tests(fake_pipeline, [(False, long_out)])
    report_engine(fake_pipeline, "opencode")

    result = runner.execute(Job("issue", "5", "Add thing", "please add thing"), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "เทสต์ไม่ผ่าน" in result
    entry = history_entry()
    assert entry["state"] == "FAILED"
    assert entry["fail_reason"] == long_out[-300:]
    assert len(entry["fail_reason"]) == 300
    assert entry["engine"] == "opencode"
    assert entry["fix_rounds"] == 2

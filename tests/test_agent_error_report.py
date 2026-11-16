"""MED-02 characterization: an engine ERROR raises and is never reported as 'no change'.

These pin existing behaviour (they pass on first run); they are not RED tests of a new feature.
"""
from __future__ import annotations

import pytest

from auto_dev_crew import runner
from auto_dev_crew.runner import Job

REPO = "example-owner/repo-alpha"
ERR = {"status": "ERROR", "response": "401 Header of type authorization was missing"}


def make_cfg(**overrides) -> dict:
    cfg = {
        "owner": "example-owner",
        "labels": {"task": "ai-task", "pause": "ai-pause", "working": "ai-working",
                   "failed": "ai-failed", "pr": "ai-pr"},
        "max_fix_attempts": 2,
        "merge_mode": "merge-all",
        "small_pr": {"max_lines": 50, "protected_paths": []},
        "evaluation": {"enabled": False},
        "triage": {"enabled": False},
        "ci": {"enabled": False, "auto_rebase": False},
        "parallel": {"slots": 3},
        "personas": {"enabled": []},
        "repos": [{"name": REPO, "base": "main"}],
    }
    cfg.update(overrides)
    return cfg


def make_rcfg() -> dict:
    return {"name": REPO, "base": "main", "setup": [], "test": ["python -m pytest -q"]}


def issue_job() -> Job:
    return Job("issue", "5", "Add thing", "please add thing")


def _comment_bodies(fake_gh) -> list[str]:
    return [c[c.index("--body") + 1] for c in fake_gh.calls
            if c[:2] in (("issue", "comment"), ("pr", "comment")) and "--body" in c]


def test_engine_error_raises_and_is_not_reported_as_no_change(fake_gh, fake_pipeline):
    fake_pipeline.call_agent.side_effect = None
    fake_pipeline.call_agent.return_value = ERR

    with pytest.raises(RuntimeError, match="401"):
        runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert not any("ไม่มีการเปลี่ยนแปลง" in b for b in _comment_bodies(fake_gh))
    assert not [h for h in runner.load_history() if h.get("state") == "NO_ACTION"]
    # run_steps is only called once for (empty) setup before the agent; never for the test steps.
    assert all(call.args[0] != make_rcfg()["test"] for call in fake_pipeline.run_steps.call_args_list)
    assert fake_pipeline.call_agent.call_count == 1


def test_genuine_no_change_still_reports_no_change(fake_gh, fake_pipeline):
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "ไม่พบ"}
    fake_pipeline.diff_stats.return_value = (0, [])

    msg = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่มีการเปลี่ยนแปลง" in msg
    assert [h for h in runner.load_history() if h.get("state") == "NO_ACTION"]


def test_process_slot_records_engine_error_as_error_not_no_action(fake_gh, fake_pipeline):
    fake_pipeline.call_agent.side_effect = None
    fake_pipeline.call_agent.return_value = ERR

    handled = runner.process_slot(1, make_cfg(), make_rcfg(), [], dry_run=True, persona_override="docs")

    assert handled is True
    hist = runner.load_history()
    assert hist[-1]["state"] == "ERROR"
    assert "401" in hist[-1]["error"]
    assert not [h for h in hist if h.get("state") == "NO_ACTION"]

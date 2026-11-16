"""Regression tests: a PR that conflicts with main (mergeStateStatus DIRTY) gets no CI run,
so it must NOT be reported as "repo has no CI" and must be rebased locally first."""
import json
from contextlib import nullcontext

from auto_dev_crew import runner

CFG_NO_CI_OK = {
    "merge_mode": "merge-all",
    "ci": {"enabled": True, "required_checks": [], "auto_rebase": False, "allow_no_ci": True},
}


class FakeGh:
    def __init__(self, merge_state):
        self.merge_state = merge_state
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ("pr", "view"):
            return json.dumps({"mergeStateStatus": self.merge_state})
        return ""

    def ops(self):
        return [c[:2] for c in self.calls]


def _setup(monkeypatch, merge_state="CLEAN", has_workflows=True, checks="pass"):
    gh = FakeGh(merge_state)
    waits = []
    monkeypatch.setattr(runner, "gh", gh)
    monkeypatch.setattr(runner, "file_lock", lambda *a, **k: nullcontext())
    monkeypatch.setattr(runner, "repo_has_workflows", lambda repo, cwd, ref=None: has_workflows)

    def fake_wait(repo, pr):
        waits.append(1)
        return checks

    monkeypatch.setattr(runner, "wait_for_checks", fake_wait)
    return gh, waits


def test_pr_merge_state_reads_merge_state_status(monkeypatch):
    _setup(monkeypatch, merge_state="DIRTY")
    assert runner.pr_merge_state("o/r", 5) == "DIRTY"


def test_pr_merge_state_is_none_when_gh_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gh down")

    monkeypatch.setattr(runner, "gh", boom)
    assert runner.pr_merge_state("o/r", 5) is None


def test_dirty_pr_rebases_locally_before_waiting_for_ci(monkeypatch, tmp_path):
    gh, waits = _setup(monkeypatch, merge_state="DIRTY")
    local_calls = []

    def fake_local(*a, **k):
        local_calls.append(1)
        return "merge แล้ว ✅ (ผ่าน AI Conflict Resolver)"

    monkeypatch.setattr(runner, "_local_rebase_and_merge", fake_local)
    out = runner.try_merge("o/r", 5, CFG_NO_CI_OK, small=True, cwd=tmp_path, branch="ai/x")
    assert local_calls == [1]
    assert waits == [], "CI must not be waited on for a conflicting PR"
    assert out.startswith("merge แล้ว")


def test_dirty_pr_without_local_workspace_is_marked_needs_rebase(monkeypatch):
    gh, waits = _setup(monkeypatch, merge_state="DIRTY")
    out = runner.try_merge("o/r", 5, CFG_NO_CI_OK, small=True, cwd=None, branch="ai/x")
    assert waits == []
    assert ("pr", "merge") not in gh.ops()
    assert ("pr", "close") not in gh.ops(), "PR must never be closed on conflict"
    assert ("pr", "edit") in gh.ops()
    assert "ติด conflict" in out


def test_unresolvable_dirty_pr_is_kept_with_needs_rebase(monkeypatch, tmp_path):
    gh, waits = _setup(monkeypatch, merge_state="DIRTY")
    monkeypatch.setattr(runner, "_local_rebase_and_merge", lambda *a, **k: None)
    out = runner.try_merge("o/r", 5, CFG_NO_CI_OK, small=True, cwd=tmp_path, branch="ai/x")
    assert waits == []
    assert ("pr", "merge") not in gh.ops()
    assert ("pr", "close") not in gh.ops()
    assert "ติด conflict" in out


def test_workflows_exist_but_no_checks_ran_does_not_merge_as_no_ci(monkeypatch):
    # allow_no_ci is on: the old code merged here, treating "no check runs" as "no CI".
    gh, waits = _setup(monkeypatch, merge_state="CLEAN", has_workflows=True, checks="none")
    out = runner.try_merge("o/r", 5, CFG_NO_CI_OK, small=True, cwd=None, branch="ai/x")
    assert waits == [1]
    assert ("pr", "merge") not in gh.ops()
    assert ("pr", "close") not in gh.ops()
    assert out.startswith("รอ CI")

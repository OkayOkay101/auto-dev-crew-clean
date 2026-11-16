"""Lifecycle tests for runner.execute / finish_pr / try_merge using FakeGh and FakePipeline.

No real gh, git, agent, network or venv is touched; see conftest.py fixtures.
"""
from __future__ import annotations

from auto_dev_crew import runner
from auto_dev_crew.evaluator import EvaluationResult
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
        "evaluation": {"enabled": True, "max_eval_refinements": 2},
        "triage": {"enabled": False},
        "ci": {"enabled": False, "auto_rebase": False},
        "parallel": {"slots": 3},
        "personas": {"enabled": []},
        "repos": [{"name": REPO, "base": "main"}],
    }
    cfg.update(overrides)
    return cfg


def make_rcfg(**overrides) -> dict:
    rcfg = {"name": REPO, "base": "main", "setup": [], "test": ["python -m pytest -q"]}
    rcfg.update(overrides)
    return rcfg


def issue_job(key: str = "5") -> Job:
    return Job("issue", key, "Add thing", "please add thing")


def issue_calls(fake_gh, verb: str, key: str = "5"):
    return [c for c in fake_gh.calls if c[:2] == ("issue", verb) and len(c) > 2 and c[2] == key]


def pass_eval(pipeline):
    pipeline.evaluate_diff.return_value = EvaluationResult(score=0.9, passed=True, critique_th="ดี", dimensions={})


def test_success_opens_pr_and_merges(fake_gh, fake_pipeline):
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/7")
    cfg, rcfg = make_cfg(), make_rcfg()

    result = runner.execute(issue_job(), cfg, rcfg, [], dry_run=False)

    assert fake_gh.calls_with("pr", "create"), "PR was not opened"
    assert ("pr", "merge", "7", "-R", REPO, "--squash", "--delete-branch") in fake_gh.calls
    assert "merge แล้ว" in result
    assert issue_calls(fake_gh, "edit")[0][:4] == ("issue", "edit", "5", "-R")


def test_ci_fail_keeps_pr_open_and_marks_issue_failed(fake_gh, fake_pipeline, monkeypatch):
    """CI failure must never close the PR or delete its branch; a human inspects it instead."""
    monkeypatch.setattr(runner, "repo_has_workflows", lambda repo, cwd, ref=None: None)
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/8")
    fake_pipeline.wait_for_checks.return_value = "fail"

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "คง PR ไว้" in result
    assert not fake_gh.calls_with("pr", "close"), "PR must not be closed"
    assert not any("--delete-branch" in c for c in fake_gh.calls if c[:2] == ("pr", "close")), "branch must not be deleted"
    assert ("pr", "edit", "8", "-R", REPO, "--add-label", "ci-failed") in fake_gh.calls
    failed_adds = [c for c in issue_calls(fake_gh, "edit") if "--add-label" in c and "ai-failed" in c]
    assert failed_adds, "issue must be marked failed so the queue does not open a duplicate PR"


def test_merge_fail_keeps_pr_open(fake_gh, fake_pipeline, monkeypatch):
    """Non-conflict merge error: PR is kept and labelled, not closed, and the branch is kept."""
    monkeypatch.setattr(runner, "repo_has_workflows", lambda repo, cwd, ref=None: False)
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/12")
    fake_gh.on(("pr", "merge"), RuntimeError("some fatal merge error"))

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "คง PR ไว้" in result
    assert not fake_gh.calls_with("pr", "close"), "PR must not be closed"
    assert ("pr", "edit", "12", "-R", REPO, "--add-label", "merge-failed") in fake_gh.calls
    assert any("--add-label" in c and "ai-failed" in c for c in issue_calls(fake_gh, "edit"))


def test_eval_fail_blocks_pr_and_marks_failed(fake_gh, fake_pipeline):
    fake_pipeline.evaluate_diff.return_value = EvaluationResult(
        score=0.3, passed=False, critique_th="ไม่ดี", dimensions={})

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่ผ่านการประเมิน" in result
    assert not fake_gh.calls_with("pr", "create")
    assert any("--add-label" in c and "ai-failed" in c for c in issue_calls(fake_gh, "edit"))


def test_no_action_marks_issue_failed(fake_gh, fake_pipeline):
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "ไม่มีอะไรต้องแก้"}
    fake_pipeline.diff_stats.return_value = (0, [])

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่มีการเปลี่ยนแปลง" in result
    assert not fake_gh.calls_with("pr", "create")
    # first failure is queued for an automatic repair: no ai-failed label, ai-working is removed
    assert not any("ai-failed" in c for c in issue_calls(fake_gh, "edit"))
    assert any("--remove-label" in c and "ai-working" in c for c in issue_calls(fake_gh, "edit"))


def test_no_action_marks_issue_failed_when_auto_repair_disabled(fake_gh, fake_pipeline):
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "ไม่มีอะไรต้องแก้"}
    fake_pipeline.diff_stats.return_value = (0, [])
    cfg = make_cfg()
    cfg["auto_repair"] = {"enabled": False}

    runner.execute(issue_job(), cfg, make_rcfg(), [], dry_run=False)

    assert any("--add-label" in c and "ai-failed" in c for c in issue_calls(fake_gh, "edit"))


def test_no_action_with_diff_from_earlier_round_still_opens_pr(fake_gh, fake_pipeline):
    """Phase 3 live E2E: round 1 edited files, a later (failover) engine saw them and replied
    NO_ACTION ("already implemented"). The non-empty diff must not be thrown away as no change."""
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "มีอยู่แล้ว",
                                  "title_th": "เพิ่ม hello", "commit_message": "feat: hello"}
    pass_eval(fake_pipeline)
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/8")

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่มีการเปลี่ยนแปลง" not in result
    assert fake_gh.calls_with("pr", "create"), "diff from earlier round was discarded"


def test_refine_uses_adapted_test_steps(fake_gh, fake_pipeline):
    """MED-01: a Node repo (package.json, no .py) gets npm test; refine round must use it too."""
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/10")
    evals = [EvaluationResult(score=0.2, passed=False, critique_th="แก้", dimensions={}),
             EvaluationResult(score=0.9, passed=True, critique_th="ดี", dimensions={})]
    fake_pipeline.evaluate_diff.side_effect = evals
    original_clone = fake_pipeline.clone.side_effect

    def clone_with_package_json(*a, **k):
        d = original_clone(*a, **k)
        (d / "package.json").write_text("{}", encoding="utf-8")
        return d

    fake_pipeline.clone.side_effect = clone_with_package_json

    runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    test_runs = [c.args[0] for c in fake_pipeline.run_steps.call_args_list if c.args[0]]
    assert len(test_runs) >= 2, "expected a test run and a refine-round test run"
    assert all(steps == ["npm test"] for steps in test_runs), test_runs


def test_scratch_removed_on_no_action(fake_gh, fake_pipeline):
    """LOW-06: scratch clone and result json are removed on NO_ACTION."""
    fake_pipeline.agent_result = {"status": "NO_ACTION", "summary_th": "ไม่มี"}
    fake_pipeline.diff_stats.return_value = (0, [])

    runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    clone = fake_pipeline.clone_dirs[0]
    assert not clone.exists()
    assert not (clone.parent / f"{clone.name}.result.json").exists()


def test_scratch_removed_on_exception(fake_gh, fake_pipeline):
    """LOW-06: scratch clone and result json are removed when execute raises."""
    fake_pipeline.run_steps.side_effect = None
    fake_pipeline.run_steps.return_value = (False, "setup boom")

    try:
        runner.execute(issue_job(), make_cfg(), make_rcfg(setup=["npm install"]), [], dry_run=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("execute should have raised on setup failure")

    clone = fake_pipeline.clone_dirs[0]
    assert not clone.exists()
    assert not (clone.parent / f"{clone.name}.result.json").exists()


def test_judge_that_edits_worktree_blocks_pr(fake_gh, fake_pipeline, monkeypatch):
    """MED-13: if the judge changed the worktree, the evaluation fails and no PR is opened."""
    import itertools
    ticks = itertools.count()  # every judge call sees the tree change
    monkeypatch.setattr(runner, "_worktree_fingerprint", lambda cwd: str(next(ticks)), raising=False)
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/11")
    pass_eval(fake_pipeline)

    result = runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert "ไม่ผ่านการประเมิน" in result
    assert not fake_gh.calls_with("pr", "create")


def _force_path(monkeypatch, path):
    from auto_dev_crew.triage import TriageResult
    monkeypatch.setattr(runner, "classify_task",
                        lambda *a, **k: TriageResult(path=path, reason="t", confidence=1.0, method="test"))


def test_fast_path_passes_fast_mode_to_evaluator(fake_gh, fake_pipeline, monkeypatch):
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/7")
    _force_path(monkeypatch, "fast")

    runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.evaluate_diff.call_args.kwargs["mode"] == "fast"


def test_heavy_path_passes_heavy_mode_to_evaluator(fake_gh, fake_pipeline, monkeypatch):
    fake_gh.on(("pr", "create"), "https://github.com/example-owner/repo-alpha/pull/7")
    _force_path(monkeypatch, "heavy")

    runner.execute(issue_job(), make_cfg(), make_rcfg(), [], dry_run=False)

    assert fake_pipeline.evaluate_diff.call_args.kwargs["mode"] == "heavy"


def test_ensure_labels_creates_pr_hold_labels(fake_gh):
    """PR hold labels must exist in the repo, or gh pr edit --add-label fails silently."""
    fake_gh.on(("label", "list"), [{"name": "ai-task"}])
    runner.ensure_labels(REPO, make_cfg())
    created = {c[2] for c in fake_gh.calls if c[:2] == ("label", "create")}
    assert {"ci-failed", "merge-failed", "needs-rebase"} <= created

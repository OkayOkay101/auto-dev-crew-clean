"""F-7: skip the "no CI" poll when the repo has no workflows."""
from contextlib import nullcontext
import subprocess

from auto_dev_crew import runner


def _cp(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_has_workflows_from_clone(tmp_path, monkeypatch):
    def no_gh(*a, **k):
        raise AssertionError("gh must not be called when a clone is available")

    monkeypatch.setattr(runner, "run", no_gh)
    assert runner.repo_has_workflows("o/r", tmp_path) is False
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    assert runner.repo_has_workflows("o/r", tmp_path) is True


def test_has_workflows_via_api_404_is_false(monkeypatch):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return _cp(1, "", "gh: Not Found (HTTP 404)")

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.repo_has_workflows("o/r", None) is False
    assert calls == [["gh", "api", "repos/o/r/contents/.github/workflows", "--jq", "length"]]


def test_has_workflows_via_api_nonempty_true(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda cmd, **k: _cp(0, "2\n"))
    assert runner.repo_has_workflows("o/r", None) is True
    monkeypatch.setattr(runner, "run", lambda cmd, **k: _cp(0, "0\n"))
    assert runner.repo_has_workflows("o/r", None) is False


def test_has_workflows_api_other_error_unknown(monkeypatch):
    monkeypatch.setattr(runner, "run", lambda cmd, **k: _cp(1, "", "HTTP 401"))
    assert runner.repo_has_workflows("o/r", None) is None


def test_has_workflows_api_exception_unknown(monkeypatch):
    def boom(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(runner, "run", boom)
    assert runner.repo_has_workflows("o/r", None) is None


CFG = {"merge_mode": "merge-all", "ci": {"allow_no_ci": True, "auto_rebase": False}}


def _patch_merge(monkeypatch, has, waited):
    monkeypatch.setattr(runner, "repo_has_workflows", lambda repo, cwd, ref=None: has)
    monkeypatch.setattr(runner, "wait_for_checks", lambda repo, pr: waited() or "none")
    monkeypatch.setattr(runner, "gh", lambda *a, **k: "")
    monkeypatch.setattr(runner, "file_lock", lambda *a, **k: nullcontext())


def test_try_merge_skips_poll_without_workflows(monkeypatch):
    def fail():
        raise AssertionError("wait_for_checks must not be called")

    _patch_merge(monkeypatch, False, fail)
    out = runner.try_merge("o/r", 5, CFG, small=True, cwd=None)
    assert out.startswith("merge แล้ว")


def test_try_merge_polls_when_unknown(monkeypatch):
    called = []
    _patch_merge(monkeypatch, None, lambda: called.append(1))
    out = runner.try_merge("o/r", 5, CFG, small=True, cwd=None)
    assert called == [1]
    assert out.startswith("merge แล้ว")


# --- F-7 follow-up: check the PR head, not the default branch (bootstrap-CI PRs) ---

def test_has_workflows_via_api_uses_ref(monkeypatch):
    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        return _cp(0, "1\n")

    monkeypatch.setattr(runner, "run", fake_run)
    assert runner.repo_has_workflows("o/r", None, ref="ai/bootstrap-ci-123") is True
    assert calls == [["gh", "api", "repos/o/r/contents/.github/workflows?ref=ai/bootstrap-ci-123",
                      "--jq", "length"]]


def test_try_merge_checks_pr_head_for_workflows(monkeypatch):
    def fake_run(cmd, **k):
        if cmd[:2] == ["gh", "api"] and cmd[2].endswith("?ref=ai/bootstrap-ci-123"):
            return _cp(0, "1\n")
        return _cp(1, "", "gh: Not Found (HTTP 404)")

    called = []
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "wait_for_checks", lambda repo, pr: called.append(1) or "pass")
    monkeypatch.setattr(runner, "gh", lambda *a, **k: "")
    monkeypatch.setattr(runner, "file_lock", lambda *a, **k: nullcontext())
    cfg = {"merge_mode": "merge-all", "ci": {"allow_no_ci": False, "auto_rebase": False}}
    out = runner.try_merge("o/r", 5, cfg, small=True, cwd=None, branch="ai/bootstrap-ci-123")
    assert called == [1]
    assert out.startswith("merge แล้ว")


def test_resume_pending_passes_pr_head_branch(monkeypatch):
    entry = {"repo": "o/r", "kind": "bootstrap", "key": "ci", "state": "OPEN", "pr": 7,
             "branch": "ai/bootstrap-ci", "title": "ci: add GitHub Actions CI workflow"}
    monkeypatch.setattr(runner, "open_ai_prs",
                        lambda repo, cfg: [{"number": 7, "title": "ci", "headRefName": "ai/bootstrap-ci-123"}])
    monkeypatch.setattr(runner, "gh_json", lambda *a, **k: {"state": "OPEN"})
    monkeypatch.setattr(runner, "append_history", lambda e: None)
    monkeypatch.setattr(runner, "_report_safely", lambda *a, **k: None)
    seen = {}

    def fake_finish(e, cfg, rcfg, history, slot_id=None, branch=None, **k):
        seen["branch"] = branch
        return "done"

    monkeypatch.setattr(runner, "finish_pr", fake_finish)
    assert runner.resume_pending({"merge_mode": "merge-all"}, {"name": "o/r"}, [entry]) is True
    assert seen["branch"] == "ai/bootstrap-ci-123"

"""End-to-end flow of ci_bootstrap.bootstrap_ci with gh/git mocked: draft, fallbacks, and guards."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

from auto_dev_crew.ci_bootstrap import (
    build_workflow_spec,
    bootstrap_ci,
    plan_ci_bootstrap,
    render_workflow,
    validate_workflow,
)

REPO = "example-owner/demo"
RCFG = {"name": REPO, "base": "main", "setup": [], "test": ["python -m pytest -q"]}
CFG = {"labels": {"pr": "ai-pr"}}
AUTH_OK = SimpleNamespace(returncode=0, stdout="", stderr="Token scopes: 'repo', 'workflow'")


class Fake:
    """Dispatches the mocked gh/git calls and records what was called."""

    def __init__(self, *, scopes_ok=True, push_error=None, pr_fail_with_label=False,
                 pr_fail_all=False, perm="WRITE", auth_rc=0, push_errors=None,
                 existing_pr=None, base_exists=True):
        self.calls: list[tuple] = []
        self.push_errors = list(push_errors or [])  # per-attempt errors, consumed first
        self.existing_pr = existing_pr
        self.base_exists = base_exists
        self.push_error = push_error
        self.pr_fail_with_label = pr_fail_with_label
        self.pr_fail_all = pr_fail_all
        self.perm = perm
        self.auth_rc = auth_rc
        self.scopes = "'repo', 'workflow'" if scopes_ok else "'repo'"

    def run(self, cmd, cwd=None, check=True, timeout=300):
        self.calls.append(tuple(cmd))
        if cmd[:3] == ["gh", "auth", "status"]:
            return SimpleNamespace(returncode=self.auth_rc, stdout="",
                                   stderr=f"Token scopes: {self.scopes}" if self.auth_rc == 0 else "invalid token")
        if cmd[:2] == ["git", "push"] and "--delete" not in cmd:
            if self.push_errors:
                raise RuntimeError(f"Command failed (1): git push\n{self.push_errors.pop(0)}")
            if self.push_error:
                raise RuntimeError(f"Command failed (1): git push\n{self.push_error}")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def gh(self, *args, check=True):
        self.calls.append(("gh",) + args)
        if args[0] == "api":
            return "main" if self.base_exists else ""
        if args[:2] == ("pr", "list"):
            return json.dumps([{"url": self.existing_pr}]) if self.existing_pr else "[]"
        if args[:2] == ("repo", "view"):
            return f'{{"viewerPermission": "{self.perm}"}}'
        if args[:2] == ("pr", "create"):
            if self.pr_fail_all or (self.pr_fail_with_label and "--label" in args):
                raise RuntimeError("label not found: ai-pr")
            return "https://github.com/example-owner/demo/pull/21"
        if args[:2] == ("issue", "create"):
            return "https://github.com/example-owner/demo/issues/5"
        return ""

    def pushes(self):
        return [c for c in self.calls if c[:2] == ("git", "push") and "--delete" not in c]

    def pr_creates(self):
        return [c for c in self.calls if c[:3] == ("gh", "pr", "create")]


@pytest.fixture
def repo_dir():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "workspace"
        p.mkdir()
        (p / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (p / "main.py").write_text("print(1)\n", encoding="utf-8")
        yield p


def _patch(fake: Fake, repo_dir: Path):
    return (
        mock.patch("auto_dev_crew.ci_bootstrap.run", side_effect=fake.run),
        mock.patch("auto_dev_crew.ci_bootstrap.gh", side_effect=fake.gh),
        mock.patch("auto_dev_crew.ci_bootstrap.clone", return_value=repo_dir),
    )


def _go(fake, repo_dir, **kw):
    patches = _patch(fake, repo_dir)
    with patches[0], patches[1], patches[2]:
        return bootstrap_ci(REPO, RCFG, CFG, **kw)


def test_dry_run_draws_plan_without_side_effects(repo_dir):
    fake = Fake()
    res = _go(fake, repo_dir, dry_run=True)
    assert res.status == "dry_run"
    assert not fake.pushes() and not fake.pr_creates()
    assert not any(c[:2] == ("gh", "issue") for c in fake.calls)
    assert any(s.name == "push branch" and s.status == "skip" for s in res.steps)
    assert validate_workflow(res.workflow) == []


def test_happy_path_opens_pr(repo_dir):
    fake = Fake()
    res = _go(fake, repo_dir)
    assert res.status == "pr_opened"
    assert res.url.endswith("/pull/21")
    assert len(fake.pushes()) == 1
    assert ("gh", "pr", "create", "-R", REPO, "--base", "main") == fake.pr_creates()[0][:7]


def test_push_refused_falls_back_to_issue_with_file(repo_dir):
    fake = Fake(push_error="refusing to allow an OAuth App to create or update workflow without `workflow` scope")
    res = _go(fake, repo_dir)
    assert res.status == "issue_opened"
    assert not fake.pr_creates()
    issue = next(c for c in fake.calls if c[:3] == ("gh", "issue", "create"))
    body = issue[issue.index("--body") + 1]
    assert "name: CI" in body and ".github/workflows/ci.yml" in body


def test_missing_label_retries_without_label(repo_dir):
    fake = Fake(pr_fail_with_label=True)
    res = _go(fake, repo_dir)
    assert res.status == "pr_opened"
    creates = fake.pr_creates()
    assert len(creates) == 2
    assert "--label" in creates[0] and "--label" not in creates[1]


def test_pr_failure_falls_back_to_issue_and_removes_branch(repo_dir):
    fake = Fake(pr_fail_all=True)
    res = _go(fake, repo_dir)
    assert res.status == "issue_opened"
    assert any(c[:4] == ("git", "push", "origin", "--delete") for c in fake.calls)


def test_existing_workflow_is_skipped(repo_dir):
    wf = repo_dir / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: x\n", encoding="utf-8")
    fake = Fake()
    res = _go(fake, repo_dir)
    assert res.status == "skipped"
    assert not fake.pushes()


def test_auth_failure_stops_before_clone(repo_dir):
    fake = Fake(auth_rc=1)
    clone_mock = mock.patch("auto_dev_crew.ci_bootstrap.clone")
    with mock.patch("auto_dev_crew.ci_bootstrap.run", side_effect=fake.run), \
         mock.patch("auto_dev_crew.ci_bootstrap.gh", side_effect=fake.gh), clone_mock as cl:
        res = bootstrap_ci(REPO, RCFG, CFG)
    assert res.status == "failed"
    cl.assert_not_called()
    assert any(s.name == "gh login" and s.status == "fail" for s in res.steps)


def test_no_write_permission_fails(repo_dir):
    fake = Fake(perm="READ")
    res = _go(fake, repo_dir)
    assert res.status == "failed"
    assert not fake.pushes()


def test_secret_in_config_is_not_committed(repo_dir):
    fake = Fake()
    rcfg = {"name": REPO, "base": "main", "setup": [], "test": ["echo sk-or-v1-" + "a" * 40]}
    patches = _patch(fake, repo_dir)
    with patches[0], patches[1], patches[2]:
        res = bootstrap_ci(REPO, rcfg, CFG)
    assert res.status == "failed"
    assert not fake.pushes()


def test_token_scope_warning_when_workflow_missing(repo_dir):
    fake = Fake(scopes_ok=False)
    res = _go(fake, repo_dir, dry_run=True)
    assert any(s.name == "token scope workflow" and s.status == "warn" for s in res.steps)


def test_plan_wrapper_is_dry_run(repo_dir):
    fake = Fake()
    patches = _patch(fake, repo_dir)
    with patches[0], patches[1], patches[2]:
        res = plan_ci_bootstrap(REPO, RCFG, CFG)
    assert res.status == "dry_run" and not fake.pushes()


def test_unsafe_branch_name_is_dropped(repo_dir):
    spec, _ = build_workflow_spec(repo_dir, {"base": "main, evil]"})
    assert spec["on"]["push"]["branches"] == ["main", "master"]


def test_render_uses_plain_on_key_and_literal_blocks(repo_dir):
    text = render_workflow(build_workflow_spec(repo_dir, RCFG)[0])
    assert text.startswith("name: CI\non:\n")
    assert "run: |" in text
    assert validate_workflow(text) == []


def test_pytest_installed_when_requirements_lack_it(repo_dir):
    (repo_dir / "requirements.txt").write_text("requests\n", encoding="utf-8")
    res = _go(Fake(), repo_dir, dry_run=True)
    names = [s["name"] for s in yaml.safe_load(res.workflow)["jobs"]["test"]["steps"]]
    assert "Install pytest" in names
    assert names.index("Install pytest") < names.index("Run tests")


def test_pytest_not_reinstalled_when_requirements_have_it(repo_dir):
    (repo_dir / "requirements.txt").write_text("pytest==8.0\n", encoding="utf-8")
    res = _go(Fake(), repo_dir, dry_run=True)
    names = [s["name"] for s in yaml.safe_load(res.workflow)["jobs"]["test"]["steps"]]
    assert "Install pytest" not in names


def test_missing_base_branch_fails_before_clone(repo_dir):
    fake = Fake(base_exists=False)
    clone_mock = mock.patch("auto_dev_crew.ci_bootstrap.clone")
    with mock.patch("auto_dev_crew.ci_bootstrap.run", side_effect=fake.run), \
         mock.patch("auto_dev_crew.ci_bootstrap.gh", side_effect=fake.gh), clone_mock as cl:
        res = bootstrap_ci(REPO, RCFG, CFG)
    assert res.status == "failed" and "สาขาฐาน" in res.message or any(s.name == "สาขาฐาน" for s in res.steps)
    cl.assert_not_called()


def test_transient_push_error_is_retried_then_succeeds(repo_dir):
    fake = Fake(push_errors=["could not resolve host: github.com", "RPC failed; HTTP 502"])
    # Patch the `time` name inside ci_bootstrap only: patching `time.sleep` globally
    # also counts sleeps from unrelated background threads (flaky on CI).
    with mock.patch("auto_dev_crew.ci_bootstrap.time") as tm:
        res = _go(fake, repo_dir)
    assert res.status == "pr_opened"
    assert len(fake.pushes()) == 3
    assert tm.sleep.call_count == 2


def test_transient_push_error_exhausted_is_retryable_not_issue(repo_dir):
    fake = Fake(push_errors=["Connection timed out"] * 10)
    with mock.patch("auto_dev_crew.ci_bootstrap.time.sleep"):
        res = _go(fake, repo_dir)
    assert res.status == "failed"
    assert not any(c[:3] == ("gh", "issue", "create") for c in fake.calls)


def test_existing_pr_found_after_create_failure_keeps_branch(repo_dir):
    fake = Fake(pr_fail_all=True, existing_pr="https://github.com/example-owner/demo/pull/30")
    res = _go(fake, repo_dir)
    assert res.status == "pr_opened" and res.url.endswith("/pull/30")
    assert not any(c[:4] == ("git", "push", "origin", "--delete") for c in fake.calls)


def test_scope_check_is_exact_match(repo_dir):
    fake = Fake(scopes_ok=False)
    fake.scopes = "'repo', 'read:workflow'"
    res = _go(fake, repo_dir, dry_run=True)
    assert any(s.name == "token scope workflow" and s.status == "warn" for s in res.steps)


def test_branch_names_are_unique_within_same_second(repo_dir):
    names = set()
    for _ in range(5):
        fake = Fake()
        _go(fake, repo_dir)
        names.update(c[c.index("--head") + 1] if "--head" in c else "" for c in fake.pr_creates())
        names.update(c[3] for c in fake.pushes())
    assert len(names - {""}) >= 5


def test_validate_rejects_bad_uses_reference():
    bad = "name: x\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n    - uses: notaref\n"
    assert any("uses" in e for e in validate_workflow(bad))


def test_no_test_command_is_a_warning(repo_dir):
    # no python / node / go / rust markers and no configured test command
    empty = repo_dir.parent / "bare"
    empty.mkdir(exist_ok=True)
    (empty / "notes.txt").write_text("hi", encoding="utf-8")
    _, warnings = build_workflow_spec(empty, {"base": "main"})
    assert any("ไม่พบคำสั่งทดสอบ" in w for w in warnings)


def test_validate_reports_structural_problems():
    assert validate_workflow("name: x\non: push\njobs: {}\n") == ["ไม่มี jobs"]
    bad = yaml.safe_dump({"name": "x", "on": "push", "jobs": {"t": {"steps": [{}]}}})
    errs = validate_workflow(bad)
    assert any("runs-on" in e for e in errs)
    assert any("step 1" in e for e in errs)
    assert validate_workflow("key: [unclosed")[0].startswith("YAML ไม่ถูกต้อง")

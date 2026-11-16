"""Every gh wrapper must redact secrets in --body / -b values before they reach GitHub."""
from __future__ import annotations

from auto_dev_crew import ci_bootstrap, multi_repo
from auto_dev_crew.redact import PLACEHOLDER, redact_gh_args

SECRET = "sk-or-v1-" + "a" * 40


def test_redact_gh_args_covers_body_forms():
    out = redact_gh_args(("pr", "comment", "1", "--body", f"key {SECRET}", "-b", f"x {SECRET}", f"--body={SECRET}"))
    assert SECRET not in " ".join(out)
    assert " ".join(out).count(PLACEHOLDER) == 3


def test_redact_gh_args_leaves_other_args_alone():
    args = ("issue", "list", "--title", f"title {SECRET}")
    assert redact_gh_args(args) == args


def test_multi_repo_gh_redacts_before_run(monkeypatch):
    seen = {}

    class Res:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        return Res()

    monkeypatch.setattr(multi_repo, "run_cmd", fake_run)
    multi_repo.gh("pr", "comment", "3", "--body", SECRET)
    assert SECRET not in " ".join(seen["cmd"])


def test_ci_bootstrap_gh_redacts_before_run(monkeypatch):
    seen = {}

    class Res:
        stdout = ""

    def fake_run(cmd, *a, **k):
        seen["cmd"] = cmd
        return Res()

    monkeypatch.setattr(ci_bootstrap, "run", fake_run)
    ci_bootstrap.gh("pr", "comment", "3", "--body", SECRET)
    assert SECRET not in " ".join(seen["cmd"])

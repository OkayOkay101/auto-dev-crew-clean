"""Phase 2 + 3: feature proposals, filing, approval -> task issue, risk rules, and the throttled approval loop.

Every GitHub call goes through a fake `run`; nothing here touches a real repository.
"""
import json

from auto_dev_crew import feature_gen as fg
from auto_dev_crew.feature_gen import (
    APPROVED_LABEL,
    PLAN_LABEL,
    enqueue_approved,
    file_plans,
    maybe_process_approvals,
    path_risk,
    plan_marker,
    pr_risk,
    propose,
    read_roadmap,
    risk_reasons,
    settings_for,
    merge_level_for,
    validate_proposals,
    render_plan_body,
    build_proposal_prompt,
)

REPO = "o/r"


class FakeGH:
    """Records calls and answers the handful of `gh` shapes feature_gen uses."""

    def __init__(self, plan_bodies=(), task_bodies=(), approved=(), files=None):
        self.calls = []
        self.plan_bodies = list(plan_bodies)
        self.task_bodies = list(task_bodies)
        self.approved = list(approved)
        self.files = files or []
        self.created = []

    def __call__(self, *args, **kw):
        self.calls.append(args)
        if args[:2] == ("label", "create"):
            return ""
        if args[:2] == ("issue", "list"):
            if PLAN_LABEL in args:
                return json.dumps([{"body": b} for b in self.plan_bodies])
            if APPROVED_LABEL in args:
                return json.dumps(self.approved)
            return json.dumps([{"body": b} for b in self.task_bodies])
        if args[:2] == ("issue", "create"):
            title = args[args.index("--title") + 1]
            body = args[args.index("--body") + 1]
            self.created.append({"title": title, "body": body, "label": args[args.index("--label") + 1]})
            return f"https://github.com/{REPO}/issues/{100 + len(self.created)}\n"
        if args[:2] == ("pr", "view") and "files" in args:
            return json.dumps({"files": [{"path": p} for p in self.files]})
        return ""


def _prop(**kw):
    base = {"title": "Dark mode", "why": "eyes", "plan": ["add toggle"], "files": ["ui/theme.css"], "tests": "t"}
    base.update(kw)
    return base


# ---- risk ---------------------------------------------------------------

def test_path_risk_kinds():
    assert path_risk(".github/workflows/ci.yml") == "CI/workflow"
    assert path_risk("config.yaml") == "config/key"
    assert path_risk("app/.env") == "config/key"
    assert path_risk("src/api_key.py") == "config/key"
    assert path_risk("requirements.txt") == "dependency"
    assert path_risk("web/package-lock.json") == "dependency"
    assert path_risk("db/migrations/001.sql") == "migration"
    assert path_risk("src/game.py") is None


def test_risk_reasons_large_change_and_dedupe():
    assert risk_reasons(["src/a.py"]) == []
    many = [f"src/f{i}.py" for i in range(9)]
    assert any("แก้ไฟล์จำนวนมาก" in r for r in risk_reasons(many, large_threshold=8))
    assert risk_reasons([".github/a.yml", ".github/b.yml"]) == ["CI/workflow: .github/a.yml", "CI/workflow: .github/b.yml"]


def test_pr_risk_fails_closed_when_files_unknown():
    gh = FakeGH(files=[])
    assert pr_risk(REPO, 5, {}, run=gh)  # empty list -> treated as a failure, not as safe
    assert pr_risk(REPO, 5, {}, run=FakeGH(files=["src/ok.py"])) == []


def test_pr_risk_flags_risky_file():
    reasons = pr_risk(REPO, 5, {}, run=FakeGH(files=["requirements.txt", "src/ok.py"]))
    assert reasons == ["dependency: requirements.txt"]


# ---- settings -----------------------------------------------------------

def test_always_on_by_default_and_switches_off():
    cfg = {"repos": [{"name": REPO}]}
    s = settings_for(cfg, REPO)
    assert s["enabled"] is False  # off by default: ai-plan issues need an explicit opt-in
    assert settings_for({"repos": [{"name": REPO, "feature_gen": {"enabled": True}}]}, REPO)["enabled"] is True
    assert settings_for({"feature_gen": {"enabled": True}, "repos": [{"name": REPO}]}, REPO)["enabled"] is True
    assert s["whole_repo"] and s["roadmap"] and s["scan_gaps"]
    assert s["max_proposals"] == 3
    assert settings_for({"feature_gen": {"enabled": False}, "repos": [{"name": REPO}]}, REPO)["enabled"] is False
    assert settings_for({"repos": [{"name": REPO, "feature_gen": {"enabled": False}}]}, REPO)["enabled"] is False


def test_max_proposals_is_capped_at_three():
    cfg = {"repos": [{"name": REPO, "feature_gen": {"max_proposals": 50}}]}
    assert settings_for(cfg, REPO)["max_proposals"] == 3


def test_merge_level_only_valid_values():
    assert merge_level_for({"repos": [{"name": REPO, "merge_level": 2}]}, REPO) == 2
    assert merge_level_for({"repos": [{"name": REPO, "merge_level": 9}]}, REPO) is None
    assert merge_level_for({"repos": [{"name": REPO}]}, REPO) is None


# ---- proposals ----------------------------------------------------------

def test_validate_drops_bad_items_and_caps():
    raw = [
        "not a dict",
        {"title": "", "plan": ["x"]},
        {"title": "No plan", "plan": []},
        {"title": "Escape", "plan": ["x"], "files": ["../etc/passwd", "/abs.py", "C:/x.py", "ok.py"]},
        _prop(title="Dark mode"),
        _prop(title="dark MODE"),  # duplicate by case-insensitive title
        _prop(title="Second"),
        _prop(title="Third"),
    ]
    out = validate_proposals(raw, max_items=2)
    assert [p["title"] for p in out] == ["Escape", "Dark mode"]  # duplicate dropped, cap of 2 reached
    escape = next(p for p in validate_proposals(raw, 5) if p["title"] == "Escape")
    assert escape["files"] == ["ok.py"]


def test_marker_is_stable_across_case_and_spacing():
    assert plan_marker("Dark  Mode") == plan_marker("dark mode")
    assert plan_marker("Dark mode") != plan_marker("Light mode")


def test_render_body_has_marker_approval_hint_and_redacts():
    secret = "ghp_" + "a" * 36
    p = {**_prop(title=f"Feat {secret}", why=f"token {secret}"), "risk": ["dependency: requirements.txt"]}
    body = render_plan_body(p)
    assert plan_marker(p["title"]) in body
    assert f"`{APPROVED_LABEL}`" in body
    assert "dependency: requirements.txt" in body
    assert secret not in body


def test_propose_uses_model_and_attaches_risk(tmp_path):
    seen = []
    raw = json.dumps([_prop(files=["requirements.txt"])])

    def model(prompt):
        seen.append(prompt)
        return raw

    out = propose(REPO, {"repos": [{"name": REPO}]}, tmp_path, model, gaps=["- [bug/high] X (a.py:1)"],
                  roadmap="# Plans\n- dark mode")
    assert out[0]["risk"] == ["dependency: requirements.txt"]
    assert "Read the repository in your working directory" in seen[0]  # whole_repo default on
    assert "- [bug/high] X (a.py:1)" in seen[0] and "dark mode" in seen[0]


def test_propose_without_whole_repo_says_so(tmp_path):
    prompt = build_proposal_prompt(REPO, "", ["- gap"], whole_repo=False, max_items=3)
    assert "only on the roadmap and the gaps" in prompt
    assert "Read the repository" not in prompt


def test_read_roadmap_first_existing_and_truncated(tmp_path):
    assert read_roadmap(tmp_path) == ""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap.md").write_text("A" * 9000, encoding="utf-8")
    text = read_roadmap(tmp_path)
    assert len(text) == fg.ROADMAP_MAX_CHARS


# ---- filing and approval ------------------------------------------------

def test_file_plans_creates_issue_with_label_and_skips_duplicates():
    proposals = [{**_prop(), "risk": []}]
    gh = FakeGH()
    first = file_plans(REPO, proposals, run=gh)
    assert first["created"] == 1 and first["urls"]
    assert gh.created[0]["label"] == PLAN_LABEL
    assert gh.created[0]["title"].startswith("[plan] Dark mode")
    # second time the marker is already in an existing (open or closed) plan issue
    again = file_plans(REPO, proposals, run=FakeGH(plan_bodies=[gh.created[0]["body"]]))
    assert again["created"] == 0 and again["skipped"] == 1


def test_file_plans_reports_label_failure_without_raising():
    def boom(*a, **k):
        raise RuntimeError("no gh")

    out = file_plans(REPO, [_prop()], run=boom)
    assert out["created"] == 0 and out["errors"]


def test_enqueue_approved_creates_task_once():
    plan_issue = {"number": 7, "title": "[plan] Dark mode", "body": "plan body", "url": "https://x/7"}
    gh = FakeGH(approved=[plan_issue])
    cfg = {"labels": {"task": "ai-task"}}
    res = enqueue_approved(REPO, cfg, run=gh)
    assert res["enqueued"] == 1
    task = gh.created[0]
    assert task["label"] == "ai-task" and task["title"].startswith("[feature] Dark mode")
    assert "<!-- plan-issue:7 -->" in task["body"]
    assert any(c[:2] == ("issue", "comment") for c in gh.calls)
    # the task already exists (its marker is in an open/closed task issue) -> nothing new
    again = enqueue_approved(REPO, cfg, run=FakeGH(approved=[plan_issue], task_bodies=[task["body"]]))
    assert again["enqueued"] == 0 and again["skipped"] == 1


def test_enqueue_with_no_approved_does_nothing():
    gh = FakeGH(approved=[])
    assert enqueue_approved(REPO, {}, run=gh) == {"enqueued": 0, "skipped": 0, "errors": [], "urls": []}
    assert not gh.created


def test_maybe_process_approvals_is_throttled(tmp_path):
    cfg = {"repos": [{"name": REPO}]}
    gh = FakeGH(approved=[])
    first = maybe_process_approvals(cfg, tmp_path, now=1000.0, min_interval_s=600, run=gh)
    assert first and first[0]["repo"] == REPO
    assert maybe_process_approvals(cfg, tmp_path, now=1100.0, min_interval_s=600, run=gh) == []
    assert maybe_process_approvals(cfg, tmp_path, now=1700.0, min_interval_s=600, run=gh)


def test_maybe_process_skips_disabled_repos(tmp_path):
    cfg = {"repos": [{"name": REPO, "enabled": False}]}
    assert maybe_process_approvals(cfg, tmp_path, now=1.0, min_interval_s=0, run=FakeGH()) == []


def test_propose_raises_when_reply_is_not_a_json_array(tmp_path):
    # Bad output must be an error, not a silent "0 plans" (that hid a real failure before).
    import pytest
    with pytest.raises(ValueError):
        propose(REPO, {"repos": [{"name": REPO}]}, tmp_path, lambda p: "sorry, I cannot help")


# ---- closing plans whose task is done -----------------------------------

class FakeTaskGH:
    """Answers the approved-plan list and the task list (with number/state/url) for close_done_plans."""

    def __init__(self, approved=(), tasks=(), fail_close=False):
        self.approved = list(approved)
        self.tasks = list(tasks)
        self.fail_close = fail_close
        self.calls = []

    def __call__(self, *args, **kw):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps(self.approved if APPROVED_LABEL in args else self.tasks)
        if args[:2] == ("issue", "close") and self.fail_close:
            raise RuntimeError("gh down")
        return ""

    def closes(self):
        return [c for c in self.calls if c[:2] == ("issue", "close")]


def _plan(number):
    return {"number": number, "title": f"[plan] feature {number}", "body": "", "url": f"https://x/{number}"}


def _task(plan_number, state, number=500):
    return {"number": number, "state": state, "url": f"https://x/{number}",
            "body": f"<!-- plan-issue:{plan_number} -->\n\nแผนที่อนุมัติแล้ว"}


def test_close_done_plans_closes_plan_when_its_task_is_closed():
    gh = FakeTaskGH(approved=[_plan(157)], tasks=[_task(157, "CLOSED", number=159)])
    res = fg.close_done_plans(REPO, {}, run=gh)
    assert res == {"closed": 1, "errors": []}
    (close,) = gh.closes()
    assert close[:3] == ("issue", "close", "157")
    assert "--comment" in close and "https://x/159" in close[close.index("--comment") + 1]


def test_close_done_plans_keeps_plan_open_while_task_is_open():
    gh = FakeTaskGH(approved=[_plan(158)], tasks=[_task(158, "OPEN")])
    assert fg.close_done_plans(REPO, {}, run=gh) == {"closed": 0, "errors": []}
    assert gh.closes() == []


def test_close_done_plans_keeps_plan_open_when_no_task_exists():
    gh = FakeTaskGH(approved=[_plan(7)], tasks=[_task(999, "CLOSED")])
    assert fg.close_done_plans(REPO, {}, run=gh) == {"closed": 0, "errors": []}
    assert gh.closes() == []


def test_close_done_plans_with_nothing_approved_does_not_list_tasks():
    gh = FakeTaskGH(approved=[], tasks=[_task(1, "CLOSED")])
    assert fg.close_done_plans(REPO, {}, run=gh) == {"closed": 0, "errors": []}
    assert not any(c[:2] == ("issue", "list") and "--state" in c for c in gh.calls if APPROVED_LABEL not in c)


def test_close_done_plans_reports_close_failure_without_raising():
    gh = FakeTaskGH(approved=[_plan(157)], tasks=[_task(157, "CLOSED")], fail_close=True)
    res = fg.close_done_plans(REPO, {}, run=gh)
    assert res["closed"] == 0 and res["errors"] and "#157" in res["errors"][0]


def test_maybe_process_approvals_closes_done_plan_in_the_same_cycle(tmp_path):
    cfg = {"repos": [{"name": REPO}]}
    gh = FakeTaskGH(approved=[_plan(157)], tasks=[_task(157, "CLOSED", number=159)])
    (row,) = maybe_process_approvals(cfg, tmp_path, now=1.0, min_interval_s=0, run=gh)
    assert row["repo"] == REPO and row["closed"] == 1 and row["errors"] == []
    assert row["enqueued"] == 0 and row["skipped"] == 1  # the existing task is not duplicated


def test_propose_empty_array_is_a_real_zero_not_an_error(tmp_path):
    out = propose(REPO, {"repos": [{"name": REPO}]}, tmp_path, lambda p: "[]")
    assert out == []


def test_last_result_round_trip(tmp_path):
    from auto_dev_crew.feature_gen import load_last, save_last
    assert load_last(tmp_path, REPO) is None
    save_last(tmp_path, REPO, {"ran": True, "proposed": 2, "created": 1, "skipped": 0, "errors": []})
    got = load_last(tmp_path, REPO)
    assert got["proposed"] == 2 and got["created"] == 1 and got["at"]
    assert (tmp_path / "feature_gen" / "o__r.last.json").is_file()

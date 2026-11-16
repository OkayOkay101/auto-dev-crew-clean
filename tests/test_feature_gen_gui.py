"""Phase 4: GUI API for feature plans (settings, view, approve, propose). Temp config; fake gh."""
import json

import pytest
import yaml

from auto_dev_crew import gui, multi_repo, runner
from auto_dev_crew.gui import DeepScanHttpError

REPO = "o/r"
CFG = {"repos": [{"name": REPO, "feature_gen": {"enabled": True}}]}  # handlers validate the repo against the cfg they receive
CFG_TEXT = """\
repos:
- name: o/r
  enabled: true
  base: main
  feature_gen:
    enabled: true
merge_mode: merge-all
"""


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(CFG_TEXT, encoding="utf-8")
    monkeypatch.setattr(gui, "config_path", lambda: path)
    monkeypatch.setattr(gui, "load_cfg", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    return path


def _entry(path):
    return next(r for r in yaml.safe_load(path.read_text(encoding="utf-8"))["repos"] if r["name"] == REPO)


def test_settings_writes_flags_and_merge_level(cfg_file):
    res = gui._api_feature_gen_settings({"repo": REPO, "enabled": False, "merge_level": 2,
                                         "max_proposals": 2}, CFG)
    entry = _entry(cfg_file)
    assert entry["feature_gen"] == {"enabled": False, "max_proposals": 2}
    assert entry["merge_level"] == 2
    assert res["settings"]["enabled"] is False and res["merge_level"] == 2


def test_settings_keeps_other_repo_fields(cfg_file):
    gui._api_feature_gen_settings({"repo": REPO, "roadmap": False}, CFG)
    entry = _entry(cfg_file)
    assert entry["base"] == "main" and entry["enabled"] is True


@pytest.mark.parametrize("body", [
    {"enabled": "yes"},
    {"max_proposals": 4},
    {"max_proposals": True},
    {"merge_level": 9},
    {"merge_level": "2"},
    {},
])
def test_settings_rejects_bad_values_without_writing(cfg_file, body):
    before = cfg_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        gui._api_feature_gen_settings({"repo": REPO, **body}, CFG)
    assert cfg_file.read_text(encoding="utf-8") == before


def test_settings_unknown_repo_is_400(cfg_file):
    with pytest.raises(DeepScanHttpError):
        gui._api_feature_gen_settings({"repo": "x/y", "enabled": True}, CFG)


def test_merge_level_null_clears_level(cfg_file):
    gui._api_feature_gen_settings({"repo": REPO, "merge_level": 3}, CFG)
    res = gui._api_feature_gen_settings({"repo": REPO, "merge_level": None}, CFG)
    assert res["merge_level"] is None


def test_view_marks_approved_plans(monkeypatch, cfg_file):
    plans = [{"number": 4, "title": "[plan] A", "url": "https://x/4"},
             {"number": 5, "title": "[plan] B", "url": "https://x/5"}]

    def fake_gh(*args, **kw):
        if "--json" in args and args[args.index("--json") + 1] == "number,title,url":
            return json.dumps(plans)
        if args[:2] == ("issue", "list") and "ai-plan-approved" in args:
            return json.dumps([{"number": 5, "title": "[plan] B", "body": "", "url": "https://x/5"}])
        return "[]"

    monkeypatch.setattr(runner, "gh", fake_gh)
    view = gui._api_feature_gen_view(REPO, yaml.safe_load(cfg_file.read_text(encoding="utf-8")))
    assert [(p["number"], p["approved"]) for p in view["plans"]] == [(4, False), (5, True)]
    assert view["settings"]["enabled"] is True


def test_view_survives_github_failure(monkeypatch, cfg_file):
    def boom(*a, **k):
        raise RuntimeError("gh down")

    monkeypatch.setattr(runner, "gh", boom)
    view = gui._api_feature_gen_view(REPO, yaml.safe_load(cfg_file.read_text(encoding="utf-8")))
    assert view["settings"] and "error" in view and view["plans"] == []


def test_approve_adds_label_and_enqueues(monkeypatch, cfg_file):
    calls = []

    def fake_gh(*args, **kw):
        calls.append(args)
        if args[:2] == ("issue", "list") and "ai-plan-approved" in args:
            return json.dumps([{"number": 5, "title": "[plan] B", "body": "b", "url": "https://x/5"}])
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/r/issues/77"
        return ""

    monkeypatch.setattr(runner, "gh", fake_gh)
    res = gui._api_feature_gen_approve({"repo": REPO, "number": 5}, {"labels": {"task": "ai-task"}, "repos": [{"name": REPO}]})
    assert res["ok"] is True and res["enqueue"]["enqueued"] == 1
    assert ("issue", "edit", "5", "-R", REPO, "--add-label", "ai-plan-approved") in calls


@pytest.mark.parametrize("number", [0, -1, True, "5", None])
def test_approve_rejects_bad_number(cfg_file, number):
    with pytest.raises(ValueError):
        gui._api_feature_gen_approve({"repo": REPO, "number": number}, CFG)


def test_propose_unknown_engine_is_400(monkeypatch, cfg_file):
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    with pytest.raises(DeepScanHttpError):
        gui._api_feature_gen_propose({"repo": REPO, "engine": "nope"}, {"repos": [{"name": REPO, "feature_gen": {"enabled": True}}]})


@pytest.mark.real_feature_cycle
def test_propose_files_plans_through_budget(monkeypatch, cfg_file, tmp_path):
    root = tmp_path / "clone"
    (root / "app").mkdir(parents=True)
    (root / "app" / "a.py").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: root)
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    proposal = json.dumps([{"title": "Dark mode", "why": "w", "plan": ["p"], "files": ["app/a.py"], "tests": "t"}])
    monkeypatch.setattr(runner, "call_agent", lambda cfg, prompt, cwd, **kw: {"status": "SUCCESS", "response": proposal})
    created = []

    def fake_gh(*args, **kw):
        if args[:2] == ("issue", "create"):
            created.append(args)
            return "https://github.com/o/r/issues/3"
        return ""

    monkeypatch.setattr(runner, "gh", fake_gh)
    res = gui._api_feature_gen_propose({"repo": REPO, "engine": "eng"}, {"repos": [{"name": REPO, "feature_gen": {"enabled": True}}]})
    assert res["ok"] is True and res["ran"] is True and res["created"] == 1
    assert res["calls_used"] == 1
    assert created and "ai-plan" in created[0]

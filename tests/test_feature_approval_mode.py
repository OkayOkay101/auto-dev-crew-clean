"""Approval mode for feature plans: manual (default, a human adds the label) or auto (the first N
plans of a proposal round get the approved label when filed). Every GitHub call is faked."""
import json

import pytest
import yaml

from auto_dev_crew import gui, multi_repo, runner
from auto_dev_crew.feature_gen import APPROVED_LABEL, PLAN_LABEL, file_plans, settings_for

REPO = "o/r"


def _prop(title, **kw):
    base = {"title": title, "why": "w", "plan": ["step"], "files": ["app/a.py"], "tests": "t", "risk": []}
    base.update(kw)
    return base


class _GH:
    def __init__(self):
        self.created = []

    def __call__(self, *args, **kw):
        if args[:2] == ("label", "create"):
            return ""
        if args[:2] == ("issue", "list"):
            return "[]"
        if args[:2] == ("issue", "create"):
            self.created.append({"label": args[args.index("--label") + 1], "body": args[args.index("--body") + 1]})
            return f"https://github.com/{REPO}/issues/{len(self.created)}"
        return ""


# ---- settings ------------------------------------------------------------

def test_default_is_manual_with_one_auto_slot():
    s = settings_for({"repos": [{"name": REPO}]}, REPO)
    assert s["approval_mode"] == "manual"
    assert s["auto_approve_max"] == 1


def test_auto_mode_and_count_read_from_repo_entry():
    cfg = {"repos": [{"name": REPO, "feature_gen": {"approval_mode": "auto", "auto_approve_max": 2}}]}
    s = settings_for(cfg, REPO)
    assert s["approval_mode"] == "auto" and s["auto_approve_max"] == 2


def test_unknown_mode_falls_back_to_manual():
    cfg = {"repos": [{"name": REPO, "feature_gen": {"approval_mode": "yolo"}}]}
    assert settings_for(cfg, REPO)["approval_mode"] == "manual"


@pytest.mark.parametrize("raw,expected", [(0, 1), (-5, 1), (99, 3), ("x", 1)])
def test_auto_approve_max_is_clamped(raw, expected):
    cfg = {"repos": [{"name": REPO, "feature_gen": {"auto_approve_max": raw}}]}
    assert settings_for(cfg, REPO)["auto_approve_max"] == expected


# ---- filing ----------------------------------------------------------------

def test_manual_mode_files_without_approved_label():
    gh = _GH()
    out = file_plans(REPO, [_prop("A"), _prop("B")], run=gh)
    assert out["created"] == 2 and out["auto_approved"] == 0
    assert all(c["label"] == PLAN_LABEL for c in gh.created)
    assert all("รอการอนุมัติ" in c["body"] for c in gh.created)


def test_auto_approve_labels_only_first_n_plans():
    gh = _GH()
    out = file_plans(REPO, [_prop("A"), _prop("B"), _prop("C")], run=gh, auto_approve=2)
    assert out["created"] == 3 and out["auto_approved"] == 2
    labels = [c["label"] for c in gh.created]
    assert labels[0] == f"{PLAN_LABEL},{APPROVED_LABEL}"
    assert labels[1] == f"{PLAN_LABEL},{APPROVED_LABEL}"
    assert labels[2] == PLAN_LABEL
    assert "อนุมัติอัตโนมัติ" in gh.created[0]["body"]


def test_auto_approve_zero_is_manual():
    gh = _GH()
    out = file_plans(REPO, [_prop("A")], run=gh, auto_approve=0)
    assert out["auto_approved"] == 0 and gh.created[0]["label"] == PLAN_LABEL


# ---- GUI API ---------------------------------------------------------------

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


def test_settings_api_saves_mode_and_count(cfg_file):
    cfg = {"repos": [{"name": REPO}]}
    res = gui._api_feature_gen_settings({"repo": REPO, "approval_mode": "auto", "auto_approve_max": 2}, cfg)
    assert _entry(cfg_file)["feature_gen"] == {"enabled": True, "approval_mode": "auto", "auto_approve_max": 2}
    assert res["settings"]["approval_mode"] == "auto" and res["settings"]["auto_approve_max"] == 2


@pytest.mark.parametrize("body", [
    {"approval_mode": "always"},
    {"approval_mode": True},
    {"auto_approve_max": 0},
    {"auto_approve_max": 4},
    {"auto_approve_max": True},
    {"auto_approve_max": "2"},
])
def test_settings_api_rejects_bad_mode_or_count(cfg_file, body):
    before = cfg_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        gui._api_feature_gen_settings({"repo": REPO, **body}, {"repos": [{"name": REPO}]})
    assert cfg_file.read_text(encoding="utf-8") == before


@pytest.mark.real_feature_cycle
def test_propose_in_auto_mode_files_approved_plan(monkeypatch, cfg_file, tmp_path):
    root = tmp_path / "clone"
    (root / "app").mkdir(parents=True)
    (root / "app" / "a.py").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: root)
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    proposal = json.dumps([
        {"title": "Dark mode", "why": "w", "plan": ["p"], "files": ["app/a.py"], "tests": "t"},
        {"title": "Export", "why": "w", "plan": ["p"], "files": ["app/a.py"], "tests": "t"},
    ])
    monkeypatch.setattr(runner, "call_agent", lambda cfg, prompt, cwd, **kw: {"status": "SUCCESS", "response": proposal})
    created = []

    def fake_gh(*args, **kw):
        if args[:2] == ("issue", "create"):
            created.append(args[args.index("--label") + 1])
            return f"https://github.com/o/r/issues/{len(created)}"
        return ""

    monkeypatch.setattr(runner, "gh", fake_gh)
    cfg = {"repos": [{"name": REPO, "feature_gen": {"enabled": True, "approval_mode": "auto", "auto_approve_max": 1}}]}
    res = gui._api_feature_gen_propose({"repo": REPO, "engine": "eng"}, cfg)
    assert res["ok"] is True and res["created"] == 2 and res["auto_approved"] == 1
    assert created == [f"{PLAN_LABEL},{APPROVED_LABEL}", PLAN_LABEL]

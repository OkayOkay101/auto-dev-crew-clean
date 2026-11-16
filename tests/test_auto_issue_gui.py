import pytest
import yaml

from auto_dev_crew import gui


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("merge_mode: merge-all\nrepos: []\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", path)
    return path


def _saved(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_get_returns_safe_defaults_when_section_missing(cfg_file):
    res = gui._api_auto_issue_get({}, {})
    assert res == {"ok": True, "enabled": False, "trigger": "after_scan", "min_severity": "low"}


def test_post_enables_and_sets_severity_and_keeps_other_keys(cfg_file):
    res = gui._api_auto_issue_set({"enabled": True, "min_severity": "high"}, {})
    assert res["ok"] is True
    assert res["enabled"] is True
    assert res["min_severity"] == "high"
    saved = _saved(cfg_file)
    assert saved["auto_issue"] == {"enabled": True, "trigger": "after_scan", "min_severity": "high"}
    assert saved["merge_mode"] == "merge-all"
    assert saved["repos"] == []


def test_post_partial_update_only_changes_given_fields(cfg_file):
    gui._api_auto_issue_set({"enabled": True, "min_severity": "medium"}, {})
    gui._api_auto_issue_set({"enabled": False}, {})
    saved = _saved(cfg_file)["auto_issue"]
    assert saved == {"enabled": False, "trigger": "after_scan", "min_severity": "medium"}


@pytest.mark.parametrize("body", [
    {"trigger": "weekly"},
    {"min_severity": "critical"},
    {"enabled": "yes"},
])
def test_post_rejects_invalid_values_without_writing(cfg_file, body):
    before = cfg_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        gui._api_auto_issue_set(body, {})
    assert cfg_file.read_text(encoding="utf-8") == before


def test_scan_route_result_includes_auto_issue_summary(cfg_file, monkeypatch):
    seen = {}

    def fake_auto(repo, cfg, state_dir, items, label="ai-task", run=None, verify=None):
        seen["called"] = (repo, label)
        return {"ran": True, "created": 1, "skipped": 0, "errors": []}

    monkeypatch.setattr(gui.deep_scan, "file_findings_automatically", fake_auto)
    monkeypatch.setattr(gui.deep_scan, "run_deep_scan",
                        lambda repo, cfg, state, call_model: {"ok": True, "findings": [], "warnings": []})
    monkeypatch.setattr(gui, "deep_scan_engines", lambda cfg: ["eng"])
    monkeypatch.setattr(gui, "_deep_scan_repo", lambda body, cfg: "o/r")
    monkeypatch.setattr(gui, "_feature_cycle", lambda *a, **k: {"ran": False})  # not under test here
    monkeypatch.setattr(gui.multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: ".")
    res = gui._api_deep_scan({"repo": "o/r", "engine": "eng"}, {"labels": {"task": "ai-task"}})
    assert res["auto_issue"]["created"] == 1
    assert seen["called"] == ("o/r", "ai-task")

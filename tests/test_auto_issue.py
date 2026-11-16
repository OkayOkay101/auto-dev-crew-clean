import json

from auto_dev_crew.deep_scan import (
    Finding,
    auto_issue_settings,
    fetch_issue_bodies,
    file_findings_automatically,
    load_run,
    render_issue_body,
    save_run,
)

ON = {"auto_issue": {"enabled": True}}


def _f(title, severity):
    return Finding(category="bug", title=title, path="a.py", line=1,
                   evidence="x = 1", suggested_fix="fix", severity=severity)


def _saved(tmp_path, findings, repo="o/r"):
    data = save_run(tmp_path, repo, findings, "r1")
    return data["findings"]


def _make_run(calls, closed_bodies=(), fail_titles=()):
    def run(*args):
        calls.append(args)
        if args[0] == "issue" and args[1] == "list":
            return json.dumps([{"body": b} for b in closed_bodies])
        if args[0] == "issue" and args[1] == "create":
            title = args[args.index("--title") + 1]
            if any(t in title for t in fail_titles):
                raise RuntimeError("gh boom")
            return f"https://github.com/o/r/issues/{len(calls)}"
        raise AssertionError(f"unexpected gh call: {args}")
    return run


def _creates(calls):
    return [c for c in calls if c[0] == "issue" and c[1] == "create"]


def test_disabled_by_default_makes_no_gh_calls(tmp_path):
    items = _saved(tmp_path, [_f("A", "high")])
    calls = []
    res = file_findings_automatically("o/r", {}, tmp_path, items, run=_make_run(calls))
    assert res["ran"] is False
    assert calls == []
    assert load_run(tmp_path, "o/r")["findings"][0]["status"] == "new"


def test_enabled_creates_issue_per_new_finding_and_marks_filed(tmp_path):
    items = _saved(tmp_path, [_f("A", "high"), _f("B", "low")])
    calls = []
    res = file_findings_automatically("o/r", ON, tmp_path, items, run=_make_run(calls))
    assert res["ran"] is True
    assert res["created"] == 2
    assert res["errors"] == []
    creates = _creates(calls)
    assert len(creates) == 2
    assert all(c[c.index("--label") + 1] == "ai-task" for c in creates)
    statuses = {f["title"]: f["status"] for f in load_run(tmp_path, "o/r")["findings"]}
    assert statuses == {"A": "filed", "B": "filed"}


def test_min_severity_high_skips_lower_findings(tmp_path):
    cfg = {"auto_issue": {"enabled": True, "min_severity": "high"}}
    items = _saved(tmp_path, [_f("H", "high"), _f("M", "medium"), _f("L", "low")])
    calls = []
    res = file_findings_automatically("o/r", cfg, tmp_path, items, run=_make_run(calls))
    assert res["created"] == 1
    assert len(_creates(calls)) == 1
    statuses = {f["title"]: f["status"] for f in load_run(tmp_path, "o/r")["findings"]}
    assert statuses == {"H": "filed", "M": "new", "L": "new"}


def test_marker_in_closed_issue_is_skipped_and_marked_filed(tmp_path):
    items = _saved(tmp_path, [_f("A", "high")])
    closed_body = render_issue_body(_f("A", "high"))
    calls = []
    res = file_findings_automatically("o/r", ON, tmp_path, items,
                                      run=_make_run(calls, closed_bodies=[closed_body]))
    assert res["created"] == 0
    assert res["skipped"] == 1
    assert _creates(calls) == []
    assert load_run(tmp_path, "o/r")["findings"][0]["status"] == "filed"


def test_gh_failure_on_one_finding_continues_and_keeps_it_new(tmp_path):
    items = _saved(tmp_path, [_f("A", "high"), _f("B", "high")])
    calls = []
    res = file_findings_automatically("o/r", ON, tmp_path, items,
                                      run=_make_run(calls, fail_titles=("] A",)))
    assert res["created"] == 1
    assert len(res["errors"]) == 1
    statuses = {f["title"]: f["status"] for f in load_run(tmp_path, "o/r")["findings"]}
    assert statuses == {"A": "new", "B": "filed"}


def test_manual_trigger_does_not_create_automatically(tmp_path):
    cfg = {"auto_issue": {"enabled": True, "trigger": "manual"}}
    items = _saved(tmp_path, [_f("A", "high")])
    calls = []
    res = file_findings_automatically("o/r", cfg, tmp_path, items, run=_make_run(calls))
    assert res["ran"] is False
    assert calls == []


def test_invalid_settings_fall_back_to_defaults():
    cfg = {"auto_issue": {"enabled": True, "min_severity": "bogus", "trigger": "weird"}}
    assert auto_issue_settings(cfg) == {"enabled": True, "trigger": "after_scan", "min_severity": "low"}
    assert auto_issue_settings({}) == {"enabled": False, "trigger": "after_scan", "min_severity": "low"}


def test_fetch_issue_bodies_checks_open_and_closed(tmp_path):
    calls = []
    fetch_issue_bodies("o/r", "ai-task", run=_make_run(calls, closed_bodies=["x"]))
    list_call = next(c for c in calls if c[1] == "list")
    assert list_call[list_call.index("--state") + 1] == "all"

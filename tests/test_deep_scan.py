import json
import subprocess
from pathlib import Path

import pytest

from auto_dev_crew import runner
from auto_dev_crew.deep_scan import (
    CATEGORIES,
    Finding,
    build_scan_prompt,
    chunk_by_top_folder,
    create_finding_issue,
    fetch_open_bodies,
    finding_marker,
    parse_model_output,
    load_run,
    run_deep_scan,
    render_issue_body,
    save_run,
    set_status,
    state_path,
    validate_findings,
)

GOOD = {
    "category": "bug",
    "title": "t",
    "path": "a.py",
    "line": 2,
    "evidence": "x = 1",
    "suggested_fix": "fix",
}


def _repo(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return tmp_path


def test_parse_fenced_json():
    raw = '```json\n[{"a": 1}]\n```'
    assert parse_model_output(raw) == [{"a": 1}]


def test_parse_leading_text():
    assert parse_model_output('Here you go:\n[{"a": 1}, {"b": 2}] done') == [{"a": 1}, {"b": 2}]


def test_parse_no_json():
    assert parse_model_output("nothing here") == []


def test_parse_skips_brackets_in_prose_before_json():
    # M1: วงเล็บในข้อความก่อน JSON ต้องไม่ทำให้ parse พัง
    raw = 'See note [1] for context.\n[{"a": 1}]'
    assert parse_model_output(raw) == [{"a": 1}]
    assert parse_model_output("[not json]") == []


def test_valid_item_passes(tmp_path):
    out = validate_findings([GOOD], _repo(tmp_path))
    assert len(out) == 1
    assert isinstance(out[0], Finding)
    assert out[0].to_dict() == {
        "category": "bug", "title": "t", "path": "a.py", "line": 2,
        "evidence": "x = 1", "suggested_fix": "fix", "severity": "low",
    }
    assert out[0].category in CATEGORIES


def test_line_at_last_line_passes_and_one_past_is_dropped(tmp_path):
    repo = _repo(tmp_path)  # a.py has 3 lines
    assert len(validate_findings([{**GOOD, "line": 3}], repo)) == 1
    assert validate_findings([{**GOOD, "line": 4}], repo) == []


def test_symlink_escaping_repo_dropped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("one\ntwo\nthree\n", encoding="utf-8")
    try:
        (repo / "link.py").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    assert validate_findings([{**GOOD, "path": "link.py"}], repo) == []


def test_directory_junction_escaping_repo_dropped(tmp_path):
    # M4 บน Windows: symlink ต้องมีสิทธิ์พิเศษ จึงใช้ junction (ไม่ต้องใช้สิทธิ์ admin) แทน
    import os
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    link = repo / "linkdir"
    made = False
    try:
        link.symlink_to(outside, target_is_directory=True)
        made = True
    except (OSError, NotImplementedError):
        if os.name == "nt":
            res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                 capture_output=True, text=True)
            made = res.returncode == 0
    if not made:
        pytest.skip("cannot create a symlink or junction on this platform")
    assert validate_findings([{**GOOD, "path": "linkdir/a.py"}], repo) == []


def test_parent_path_dropped(tmp_path):
    assert validate_findings([{**GOOD, "path": "../x"}], _repo(tmp_path)) == []


def test_absolute_path_dropped(tmp_path):
    repo = _repo(tmp_path)
    assert validate_findings([{**GOOD, "path": str(repo / "a.py")}], repo) == []


def test_missing_file_dropped(tmp_path):
    assert validate_findings([{**GOOD, "path": "nope.py"}], _repo(tmp_path)) == []


def test_line_out_of_range_dropped(tmp_path):
    repo = _repo(tmp_path)
    assert validate_findings([{**GOOD, "line": 9999}], repo) == []
    assert validate_findings([{**GOOD, "line": 0}], repo) == []
    assert validate_findings([{**GOOD, "line": True}], repo) == []


def test_severity_normalised(tmp_path):
    repo = _repo(tmp_path)
    out = validate_findings([{**GOOD, "severity": "  HIGH "}], repo)
    assert out[0].severity == "high"


def test_missing_or_invalid_severity_becomes_low(tmp_path):
    repo = _repo(tmp_path)
    no_sev = validate_findings([GOOD], repo)
    bad = validate_findings([{**GOOD, "severity": "critical"}, {**GOOD, "severity": 5}], repo)
    assert [f.severity for f in no_sev + bad] == ["low", "low", "low"]


def test_bad_category_dropped(tmp_path):
    assert validate_findings([{**GOOD, "category": "style"}], _repo(tmp_path)) == []


def test_empty_evidence_dropped(tmp_path):
    assert validate_findings([{**GOOD, "evidence": "  "}], _repo(tmp_path)) == []


def _tree(tmp_path):
    for rel, text in {
        "app/main.py": "print('app')\n",
        "lib/util.py": "x = 1\ny = 2\n",
        "top.py": "t = 0\n",
        ".git/config": "secret\n",
        "node_modules/p/i.js": "1\n",
        ".venv-x/a.py": "1\n",
        "_slot_1/a.py": "1\n",
    }.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return tmp_path


def test_chunk_groups_by_top_folder_and_skips(tmp_path):
    chunks = dict(chunk_by_top_folder(_tree(tmp_path)))
    assert chunks == {"(root)": ["top.py"], "app": ["app/main.py"], "lib": ["lib/util.py"]}


def test_chunk_empty_repo(tmp_path):
    assert chunk_by_top_folder(tmp_path) == []


def test_chunk_skips_binary_and_large(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "bin.dat").write_bytes(b"ab" + bytes([0]) + b"cd")
    (tmp_path / "d" / "big.txt").write_bytes(b"a" * (1024 * 1024 + 1))
    (tmp_path / "d" / "ok.py").write_text("ok\n", encoding="utf-8")
    assert chunk_by_top_folder(tmp_path) == [("d", ["d/ok.py"])]


def test_prompt_contents(tmp_path):
    root = _tree(tmp_path)
    prompt = build_scan_prompt("lib", ["lib/util.py"], root, 7)
    assert prompt.lstrip().startswith("Return ONLY a JSON array")
    assert "lib" in prompt
    assert "lib/util.py" in prompt
    assert "y = 2" in prompt
    assert "max_findings: 7" in prompt
    assert 'prefixed with "N: " for reference only' in prompt
    assert 'no "N:" prefix' in prompt
    for field in ("category", "title", "path", "line", "evidence", "suggested_fix", "severity"):
        assert field in prompt
    assert "high, medium, low" in prompt


def test_prompt_truncates_and_redacts(tmp_path):
    (tmp_path / "a.py").write_text(
        "\n".join(f"line{i}" for i in range(4100)) + "\n", encoding="utf-8")
    (tmp_path / "k.py").write_text("key = 'sk-ant-api03-" + "A" * 40 + "'\n", encoding="utf-8")
    prompt = build_scan_prompt("(root)", ["a.py", "k.py"], tmp_path, 3)
    assert "line3999" in prompt
    assert "line4000" not in prompt
    assert "[truncated: 100 more lines not shown]" in prompt
    assert "[truncated" not in build_scan_prompt("(root)", ["k.py"], tmp_path, 3)
    assert "A" * 40 not in prompt


SECRET = "sk-abcdefghijklmnopqrstuvwx"


def _finding(**kw):
    base = dict(category="bug", title="Off by one", path="a.py", line=3,
                evidence="x = 1", suggested_fix="use <=")
    base.update(kw)
    return Finding(**base)


def test_marker_stable_and_line_independent():
    assert finding_marker(_finding()) == finding_marker(_finding(line=99))
    assert finding_marker(_finding()).startswith("<!-- deep-scan:a.py:")
    assert finding_marker(_finding()) != finding_marker(_finding(title="Other"))


def test_issue_body_has_marker_location_and_redacts_secret():
    f = _finding(evidence=f"key = '{SECRET}'")
    body = render_issue_body(f)
    assert finding_marker(f) in body
    assert "a.py:3" in body
    assert "**Severity:** low" in body
    assert "**Severity:** high" in render_issue_body(_finding(severity="high"))
    assert SECRET not in body


def test_create_issue_skips_when_marker_present():
    f = _finding()
    calls = []
    assert create_finding_issue("o/r", f, [render_issue_body(f)], run=lambda *a: calls.append(a)) is None
    assert calls == []


def test_create_issue_uses_custom_label():
    calls = []

    def run(*args):
        calls.append(args)
        return "https://github.com/o/r/issues/2"

    create_finding_issue("o/r", _finding(), [], label="custom-label", run=run)
    assert calls[0][calls[0].index("--label") + 1] == "custom-label"


def test_create_issue_calls_run_and_redacts_title():
    calls = []

    def run(*args):
        calls.append(args)
        return "https://github.com/o/r/issues/1\n"

    f = _finding(title=f"leak {SECRET}")
    url = create_finding_issue("o/r", f, ["unrelated"], run=run)
    assert url == "https://github.com/o/r/issues/1"
    args = calls[0]
    assert args[:4] == ("issue", "create", "-R", "o/r")
    assert args[args.index("--label") + 1] == "ai-task"
    assert SECRET not in args[args.index("--title") + 1]
    assert finding_marker(f) in args[args.index("--body") + 1]


def test_fetch_open_bodies_uses_open_state():
    seen = []

    def run(*args):
        seen.append(args)
        return '[{"body": "a"}, {"body": null}]'

    assert fetch_open_bodies("o/r", "ai-task", run=run) == ["a", ""]
    assert "open" in seen[0] and "--json" in seen[0]


def test_state_path_replaces_slash(tmp_path):
    assert state_path(tmp_path, "o/r") == tmp_path / "deep_scan" / "o__r.json"


def test_state_path_rejects_double_underscore(tmp_path):
    # M10: "a__b/c" กับ "a/b__c" จะชนกันหลังแทน "/" ด้วย "__" จึงต้องปฏิเสธ
    with pytest.raises(ValueError):
        state_path(tmp_path, "a__b/c")
    with pytest.raises(ValueError):
        state_path(tmp_path, "a/b__c")


def test_load_run_missing_returns_none(tmp_path):
    assert load_run(tmp_path, "o/r") is None


def test_save_run_roundtrip_status_new(tmp_path):
    f1, f2 = _finding(), _finding(title="Other", line=5)
    saved = save_run(tmp_path, "o/r", [f1, f2], "run1")
    loaded = load_run(tmp_path, "o/r")
    assert loaded == saved
    assert loaded["run_id"] == "run1"
    assert [x["status"] for x in loaded["findings"]] == ["new", "new"]
    assert [x["id"] for x in loaded["findings"]] == ["run1-0", "run1-1"]
    assert loaded["findings"][0]["title"] == "Off by one"
    assert loaded["findings"][1]["line"] == 5
    assert [x["severity"] for x in loaded["findings"]] == ["low", "low"]
    save_run(tmp_path, "o/r", [_finding(severity="high")], "run2")
    assert load_run(tmp_path, "o/r")["findings"][0]["severity"] == "high"


def test_set_status_filed_persists(tmp_path):
    save_run(tmp_path, "o/r", [_finding(), _finding(title="B")], "r")
    set_status(tmp_path, "o/r", "r-1", "filed")
    statuses = {x["id"]: x["status"] for x in load_run(tmp_path, "o/r")["findings"]}
    assert statuses == {"r-0": "new", "r-1": "filed"}


def test_set_status_bogus_raises(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r")
    with pytest.raises(ValueError):
        set_status(tmp_path, "o/r", "r-0", "bogus")
    assert load_run(tmp_path, "o/r")["findings"][0]["status"] == "new"


def test_set_status_unknown_id_raises(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r")
    with pytest.raises(KeyError):
        set_status(tmp_path, "o/r", "nope", "filed")


def _status_of(tmp_path, title):
    return {x["title"]: x["status"] for x in load_run(tmp_path, "o/r")["findings"]}[title]


def test_save_run_carries_dismissed_forward(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r1")
    set_status(tmp_path, "o/r", "r1-0", "dismissed")
    save_run(tmp_path, "o/r", [_finding(line=99)], "r2")
    assert _status_of(tmp_path, "Off by one") == "dismissed"


def test_save_run_carries_filed_forward(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r1")
    set_status(tmp_path, "o/r", "r1-0", "filed")
    save_run(tmp_path, "o/r", [_finding()], "r2")
    assert _status_of(tmp_path, "Off by one") == "filed"


def test_save_run_unmatched_finding_stays_new(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r1")
    set_status(tmp_path, "o/r", "r1-0", "dismissed")
    save_run(tmp_path, "o/r", [_finding(), _finding(title="Brand new")], "r2")
    assert _status_of(tmp_path, "Off by one") == "dismissed"
    assert _status_of(tmp_path, "Brand new") == "new"


def test_save_run_previous_new_does_not_block(tmp_path):
    save_run(tmp_path, "o/r", [_finding()], "r1")
    save_run(tmp_path, "o/r", [_finding()], "r2")
    loaded = load_run(tmp_path, "o/r")
    assert loaded["run_id"] == "r2"
    assert [x["status"] for x in loaded["findings"]] == ["new"]


def test_save_run_redacts_secret_in_raw_file(tmp_path):
    f = _finding(title=f"t {SECRET}", evidence=f"key = '{SECRET}'", suggested_fix=f"rm {SECRET}")
    save_run(tmp_path, "o/r", [f], "r")
    raw = state_path(tmp_path, "o/r").read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "[PROTECTED_SECRET]" in raw


class _Done:
    returncode = 0
    stdout = ""
    stderr = ""


def _scan_env(tmp_path, monkeypatch, files):
    from auto_dev_crew import multi_repo
    root = tmp_path / "repo"
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: root)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    return root, tmp_path / "state"


def _item(path="a.py", line=1):
    return {"category": "bug", "title": "t", "path": path, "line": line,
            "evidence": "x", "suggested_fix": "f"}


def test_run_deep_scan_returns_validated_findings(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\ny\n"})
    raw = json.dumps([_item(), {"category": "bogus", "path": "a.py", "line": 1, "evidence": "x"}])
    res = run_deep_scan("o/r", {}, state, lambda prompt: raw, run_id="r1")
    assert res["ok"] is True and res["repo"] == "o/r" and res["run_id"] == "r1"
    assert [f["path"] for f in res["findings"]] == ["a.py"]
    assert res["warnings"] == []


def test_run_deep_scan_caps_at_15_by_default(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\n" * 30})
    raw = json.dumps([_item(line=i) for i in range(1, 21)])
    res = run_deep_scan("o/r", {}, state, lambda prompt: raw, run_id="r1")
    assert len(res["findings"]) == 15


def test_run_deep_scan_high_from_last_chunk_survives_cap(tmp_path, monkeypatch):
    files = {f"d{i:02d}/a.py": "x\n" * 30 for i in range(4)}
    _, state = _scan_env(tmp_path, monkeypatch, files)
    calls = []

    def model(prompt):
        calls.append(prompt)
        if len(calls) < 4:
            return json.dumps([{**_item(f"d{len(calls)-1:02d}/a.py", i), "severity": "low"}
                               for i in range(1, 6)])
        return json.dumps([{**_item("d03/a.py", 1), "title": "the high one", "severity": "high"}])

    res = run_deep_scan("o/r", {}, state, model, run_id="r1")
    assert len(calls) == 4
    assert len(res["findings"]) == 15
    assert res["findings"][0]["title"] == "the high one"
    assert res["findings"][0]["severity"] == "high"
    assert [f["path"] for f in res["findings"][1:6]] == ["d00/a.py"] * 5


def test_run_deep_scan_same_severity_keeps_chunk_order(tmp_path, monkeypatch):
    # M12: เมื่อ severity เท่ากัน ลำดับต้องเป็นตามชื่อกลุ่ม (a ก่อน b) แม้ model ตอบกลับสลับกัน
    _, state = _scan_env(tmp_path, monkeypatch, {"b/y.py": "x\n", "a/x.py": "x\n"})

    def model(prompt):
        path = "b/y.py" if "'b'" in prompt else "a/x.py"
        return json.dumps([{**_item(path, 1), "severity": "low"}])

    res = run_deep_scan("o/r", {}, state, model, run_id="r1")
    assert [f["path"] for f in res["findings"]] == ["a/x.py", "b/y.py"]


def test_run_deep_scan_warns_when_cap_drops_findings(tmp_path, monkeypatch):
    # M11: เกินเพดานต้องมี warning; ไม่เกินต้องไม่มี
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\n" * 30})
    raw = json.dumps([_item(line=i) for i in range(1, 21)])
    res = run_deep_scan("o/r", {"deep_scan": {"max_findings_per_run": 3}}, state, lambda prompt: raw, run_id="r1")
    assert any("เกินเพดาน 3" in w and "17" in w for w in res["warnings"])
    res2 = run_deep_scan("o/r", {}, state, lambda prompt: json.dumps([_item(line=1)]), run_id="r2")
    assert res2["warnings"] == []


def test_run_deep_scan_cap_from_config(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\n" * 30})
    raw = json.dumps([_item(line=i) for i in range(1, 21)])
    cfg = {"deep_scan": {"max_findings_per_run": 3}}
    res = run_deep_scan("o/r", cfg, state, lambda prompt: raw, run_id="r1")
    assert len(res["findings"]) == 3


def test_run_deep_scan_failing_chunk_becomes_warning(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"bad/a.py": "x\n", "good/b.py": "x\n"})

    def model(prompt):
        if "'bad'" in prompt:
            raise RuntimeError("boom")
        return json.dumps([_item("good/b.py")])

    res = run_deep_scan("o/r", {}, state, model, run_id="r1")
    assert [f["path"] for f in res["findings"]] == ["good/b.py"]
    assert len(res["warnings"]) == 1 and "bad" in res["warnings"][0] and "boom" in res["warnings"][0]


def test_run_deep_scan_warning_is_redacted(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\n"})
    secret = "ghp_" + "a" * 36

    def model(prompt):
        raise RuntimeError(f"token {secret}")

    res = run_deep_scan("o/r", {}, state, model, run_id="r1")
    assert res["warnings"] and secret not in res["warnings"][0]


def test_run_deep_scan_writes_state_file(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\ny\n"})
    raw = json.dumps([_item()])
    run_deep_scan("o/r", {}, state, lambda prompt: raw, run_id="r1")
    saved = load_run(state, "o/r")
    assert saved["run_id"] == "r1" and saved["findings"][0]["status"] == "new"
    assert state_path(state, "o/r").exists()


def test_run_deep_scan_git_pull_failure_is_warning(tmp_path, monkeypatch):
    _, state = _scan_env(tmp_path, monkeypatch, {"a.py": "x\n"})

    def boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", boom)
    res = run_deep_scan("o/r", {}, state, lambda prompt: "[]", run_id="r1")
    assert res["ok"] is True and any("git pull" in w for w in res["warnings"])


def _engine_filter_env(monkeypatch):
    engines = [
        {"name": "opencode-other", "command": "a", "model": "m"},
        {"name": "opencode-nvidia", "command": "b", "model": "m"},
    ]
    monkeypatch.setattr(runner, "get_engines", lambda cfg: engines)
    monkeypatch.setattr(runner, "load_engine_status", lambda: {})
    monkeypatch.setattr(runner, "load_key_status", lambda: {})
    monkeypatch.setattr(runner, "engine_skip_reason", lambda *a, **k: None)
    monkeypatch.setattr(runner, "get_engine_key_entries", lambda *a, **k: [])
    used = []

    def fake_call(eng, prompt, cwd, active_key=None):
        used.append(eng["name"])
        return {"status": "SUCCESS", "response": "ok"}

    monkeypatch.setattr(runner, "call_single_engine", fake_call)
    return used


def test_call_agent_engine_name_uses_only_named_engine(monkeypatch):
    used = _engine_filter_env(monkeypatch)
    res = runner.call_agent({}, "p", Path("."), engine_name="opencode-nvidia")
    assert res["engine_used"] == "opencode-nvidia"
    assert used == ["opencode-nvidia"]


def test_call_agent_engine_name_none_keeps_order(monkeypatch):
    used = _engine_filter_env(monkeypatch)
    res = runner.call_agent({}, "p", Path("."))
    assert res["engine_used"] == "opencode-other"
    assert used == ["opencode-other"]


def test_call_agent_engine_name_unknown_raises_value_error(monkeypatch):
    used = _engine_filter_env(monkeypatch)
    with pytest.raises(ValueError, match="ไม่พบ engine"):
        runner.call_agent({}, "p", Path("."), engine_name="nope")
    assert used == []

"""ด่าน 4 ของ deep-scan: ตรวจซ้ำก่อนสร้าง issue (auto_dev_crew/deep_scan.py)."""
from __future__ import annotations

import json
from pathlib import Path

from auto_dev_crew import deep_scan as ds
from auto_dev_crew.deep_scan import Finding

ON = {"auto_issue": {"enabled": True, "trigger": "after_scan", "min_severity": "low"}}


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.js").write_text("const a = 1;\nlet total = a + '';\n", encoding="utf-8")
    return root


def _finding(line: int = 2) -> Finding:
    return Finding(category="bug", title="String concat in total", path="a.js", line=line,
                   evidence="let total = a + '';", suggested_fix="use Number", severity="high")


def _item(f: Finding, status: str = "new") -> dict:
    d = f.to_dict()
    d.update({"id": "r1-0", "status": status})
    return d


def _make_run(calls: list):
    def run(*args: str, **_):
        calls.append(args)
        if args[:2] == ("issue", "list"):
            return "[]"
        return "https://github.com/o/r/issues/9"
    return run


# ---- การแยกผลตรวจ ----------------------------------------------------------------------------

def test_parse_verify_accepts_quoted_real_line(tmp_path: Path):
    root = _repo(tmp_path)
    raw = json.dumps({"confirmed": True, "evidence": "let total = a + '';  เป็นการต่อสตริง"})
    ok, ev = ds.parse_verify_output(raw, _finding(2), root)
    assert ok is True and "let total" in ev


def test_parse_verify_rejects_paraphrase_without_code(tmp_path: Path):
    root = _repo(tmp_path)
    raw = json.dumps({"confirmed": True, "evidence": "ดูเหมือนมีปัญหาการต่อค่า"})
    assert ds.parse_verify_output(raw, _finding(2), root) == (False, "")


def test_parse_verify_rejects_confirmed_false_and_garbage(tmp_path: Path):
    root = _repo(tmp_path)
    assert ds.parse_verify_output(json.dumps({"confirmed": False, "evidence": "let total = a + '';"}),
                                  _finding(2), root) == (False, "")
    assert ds.parse_verify_output("no json", _finding(2), root) == (False, "")
    assert ds.parse_verify_output(None, _finding(2), root) == (False, "")  # type: ignore[arg-type]


def test_verify_finding_treats_model_error_as_unverified(tmp_path: Path):
    root = _repo(tmp_path)

    def boom(prompt: str) -> str:
        raise RuntimeError("engine down")

    assert ds.verify_finding(_finding(2), root, boom) == (False, "")


def test_verify_prompt_contains_numbered_file(tmp_path: Path):
    root = _repo(tmp_path)
    prompt = ds.build_verify_prompt(_finding(2), root)
    assert "2: let total = a + '';" in prompt
    assert "Claimed line 2" in prompt


# ---- การเชื่อมกับ file_findings_automatically -----------------------------------------------

def test_unverified_finding_gets_no_issue_and_is_marked(tmp_path: Path):
    _repo(tmp_path)
    state = tmp_path / "state"
    ds.save_run(state, "o/r", [_finding(2)], "r1")
    calls: list = []
    res = ds.file_findings_automatically(
        "o/r", ON, state, [_item(_finding(2))], run=_make_run(calls),
        verify=lambda f: (False, ""))
    assert res["unverified"] == 1 and res["created"] == 0
    assert not [c for c in calls if c[:2] == ("issue", "create")]
    assert ds.load_run(state, "o/r")["findings"][0]["status"] == ds.VERIFY_STATUS


def test_verified_finding_creates_issue_with_evidence(tmp_path: Path):
    _repo(tmp_path)
    state = tmp_path / "state"
    ds.save_run(state, "o/r", [_finding(2)], "r1")
    calls: list = []
    bodies: list = []

    def run(*args, **kw):
        if args[:2] == ("issue", "create"):
            bodies.append(args[args.index("--body") + 1])
        return _make_run(calls)(*args, **kw)

    res = ds.file_findings_automatically(
        "o/r", ON, state, [_item(_finding(2))], run=run,
        verify=lambda f: (True, "let total = a + '';"))
    assert res["created"] == 1 and res["unverified"] == 0
    assert bodies and "Verification (ตรวจซ้ำแล้ว)" in bodies[0]
    assert ds.load_run(state, "o/r")["findings"][0]["status"] == "filed"


def test_without_verify_behaves_as_before(tmp_path: Path):
    state = tmp_path / "state"
    ds.save_run(state, "o/r", [_finding(2)], "r1")
    calls: list = []
    res = ds.file_findings_automatically("o/r", ON, state, [_item(_finding(2))], run=_make_run(calls))
    assert res["created"] == 1 and res["unverified"] == 0


def test_real_verify_path_end_to_end_with_fake_model(tmp_path: Path):
    """verify_finding + file_findings_automatically: โมเดลที่ยืนยันด้วยโค้ดจริงทำให้เกิด issue."""
    root = _repo(tmp_path)
    state = tmp_path / "state"
    f = _finding(2)
    ds.save_run(state, "o/r", [f], "r1")
    reply = json.dumps({"confirmed": True, "evidence": "let total = a + '';"})
    calls: list = []
    res = ds.file_findings_automatically(
        "o/r", ON, state, [_item(f)], run=_make_run(calls),
        verify=lambda ff: ds.verify_finding(ff, root, lambda p: reply))
    assert res["created"] == 1

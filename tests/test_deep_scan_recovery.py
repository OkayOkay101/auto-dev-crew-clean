"""Deep scan recovery: long replies are kept, malformed replies are retried and warned, not counted as []."""
import json
import subprocess

from auto_dev_crew import multi_repo
from auto_dev_crew.deep_scan import RETRY_NOTE, run_deep_scan, validate_findings
from auto_dev_crew.guardrails import truncate_tool_output
from auto_dev_crew.loop_breaker import parse_opencode


class _Done:
    returncode = 0
    stdout = ""
    stderr = ""


def _env(tmp_path, monkeypatch, files):
    root = tmp_path / "repo"
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    monkeypatch.setattr(multi_repo, "find_or_prepare_repo_dir", lambda repo, cfg: root)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    return root, tmp_path / "state"


def _item(path="a.py", line=1, evidence="x", title="t"):
    return {"category": "bug", "title": title, "path": path, "line": line,
            "evidence": evidence, "suggested_fix": "f", "severity": "medium"}


def _opencode_stdout(text: str) -> str:
    """One OpenCode JSON-stream text event followed by a finished step."""
    return (json.dumps({"type": "text", "part": {"type": "text", "text": text}}) + "\n"
            + json.dumps({"type": "step_finish", "part": {"tokens": {"total": 10}}}) + "\n")


def test_scan_sized_reply_survives_parsing(tmp_path):
    items = [_item(title=f"finding {i}", evidence="x" * 300) for i in range(8)]  # > 2,500 chars as JSON
    text = json.dumps(items)
    assert len(text) > 2500
    small = parse_opencode(_opencode_stdout(text), 1.0)["response"]  # default limit: the old behaviour
    big = parse_opencode(_opencode_stdout(text), 1.0, max_response_chars=60_000)["response"]
    assert "Truncated" in small
    assert json.loads(big) == items  # nothing cut, JSON intact


def test_default_limit_is_unchanged_for_other_roles():
    assert truncate_tool_output("a" * 3000, max_chars=2500).count("Truncated") == 1


def test_malformed_reply_is_retried_once_and_then_recovered(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\ny\n"})
    good = json.dumps([_item()])
    replies = iter(["sorry, I cannot produce JSON right now", good])
    prompts = []

    def call(prompt):
        prompts.append(prompt)
        return next(replies)

    res = run_deep_scan("o/r", {}, state, call, run_id="r1")
    assert len(prompts) == 2
    assert prompts[1] == prompts[0] + RETRY_NOTE  # same prompt plus the JSON-only sentence
    assert len(res["findings"]) == 1
    assert res["warnings"] == []


def test_malformed_twice_is_warned_not_counted_as_empty(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\n"})
    res = run_deep_scan("o/r", {}, state, lambda p: "no json here", run_id="r1")
    assert res["findings"] == []
    assert any("ตอบผิดรูปแบบ" in w for w in res["warnings"])
    saved = json.loads((state / "deep_scan" / "o__r.json").read_text(encoding="utf-8"))
    assert any("ตอบผิดรูปแบบ" in w for w in saved["warnings"])


def test_empty_array_is_a_real_result_with_no_warning(tmp_path, monkeypatch):
    _, state = _env(tmp_path, monkeypatch, {"a.py": "x\n"})
    calls = []
    res = run_deep_scan("o/r", {}, state, lambda p: calls.append(p) or "[]", run_id="r1")
    assert len(calls) == 1  # no retry for a real empty answer
    assert res["findings"] == [] and res["warnings"] == []


def test_validate_relocates_line_by_evidence(tmp_path):
    root = tmp_path / "repo"
    (root / "t").mkdir(parents=True)
    (root / "t" / "m.py").write_text("import os\n\ndef gen():\n    pass\n    generate_mock_data()\n", encoding="utf-8")
    out = validate_findings([_item(path="t/m.py", line=87, evidence="    generate_mock_data()")], root)
    assert [f.line for f in out] == [5]

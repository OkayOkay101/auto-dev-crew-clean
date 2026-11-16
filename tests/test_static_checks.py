"""ด่านตรวจแบบกำหนดผลได้ (static_checks) สแกนเฉพาะบรรทัดที่เพิ่มใหม่ใน diff ก่อนส่งให้ judge."""
from pathlib import Path

from auto_dev_crew import static_checks as sc
from auto_dev_crew.evaluator import evaluate_diff


def _diff(path: str, added: list[str], start: int = 1, context_before: list[str] | None = None) -> str:
    """สร้าง diff แบบย่อ: hunk เดียว มีบรรทัด context (ถ้ามี) ตามด้วยบรรทัดที่เพิ่ม."""
    ctx = context_before or []
    body = [" " + c for c in ctx] + ["+" + a for a in added]
    total = len(ctx) + len(added)
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},0 +{start},{total} @@\n" + "\n".join(body) + "\n"
    )


def _rules(findings):
    return [f.rule for f in findings]


# ---- Python: การกลืน error ---------------------------------------------------------------------

def test_bare_except_pass_is_blocking():
    diff = _diff("app/core.py", ["try:", "    run()", "except:", "    pass"])
    findings = sc.scan_diff(diff)
    assert _rules(findings) == ["broad-except-swallow"]
    assert findings[0].blocking is True
    assert findings[0].path == "app/core.py"
    assert findings[0].line == 3  # บรรทัดของ `except:` ในไฟล์ใหม่


def test_except_exception_pass_is_blocking():
    diff = _diff("app/core.py", ["except Exception:", "    pass"])
    assert _rules(sc.scan_diff(diff)) == ["broad-except-swallow"]


def test_narrow_except_pass_is_allowed():
    diff = _diff("app/core.py", ["except ValueError:", "    pass"])
    assert sc.scan_diff(diff) == []


def test_broad_except_that_logs_is_allowed():
    diff = _diff("app/core.py", ["except Exception as exc:", "    log(exc)", "    raise"])
    assert sc.scan_diff(diff) == []


# ---- JavaScript: catch ว่าง ---------------------------------------------------------------------

def test_inline_empty_catch_arrow_is_blocking():
    diff = _diff("static/app.js", ["navigator.serviceWorker.register('sw.js').catch(() => {});"])
    findings = sc.scan_diff(diff)
    assert _rules(findings) == ["js-empty-catch"]
    assert findings[0].blocking is True


def test_multiline_empty_catch_is_blocking():
    diff = _diff("static/app.js", ["try {", "  run();", "} catch (e) {", "}"])
    assert _rules(sc.scan_diff(diff)) == ["js-empty-catch"]


def test_catch_that_handles_error_is_allowed():
    diff = _diff("static/app.js", ["} catch (e) {", "  showError(e);", "}"])
    assert sc.scan_diff(diff) == []


# ---- ร่องรอยการดีบัก ---------------------------------------------------------------------------

def test_debugger_statement_is_blocking():
    diff = _diff("static/app.js", ["  debugger;"])
    assert _rules(sc.scan_diff(diff)) == ["debug-artifact"]


def test_python_breakpoint_and_pdb_are_blocking():
    diff = _diff("app/core.py", ["breakpoint()", "import pdb; pdb.set_trace()"])
    assert _rules(sc.scan_diff(diff)) == ["debug-artifact", "debug-artifact"]


def test_focused_test_only_is_blocking():
    diff = _diff("tests/app.test.js", ["it.only('keeps working', () => {});"])
    assert _rules(sc.scan_diff(diff)) == ["debug-artifact"]


# ---- ความลับที่ฝังในโค้ด ------------------------------------------------------------------------

def test_hardcoded_api_key_is_blocking():
    diff = _diff("app/client.py", ['API_KEY = "sk-live-abcdefghijklmnop1234"'])
    findings = sc.scan_diff(diff)
    assert _rules(findings) == ["hardcoded-secret"]
    assert findings[0].blocking is True


def test_short_or_placeholder_values_are_not_secrets():
    diff = _diff("app/client.py", ['api_key = "changeme"', 'token = "your-token-here"'])
    assert sc.scan_diff(diff) == []


# ---- TODO ที่ไม่อ้าง issue (เป็นคำเตือน ไม่บล็อก) ------------------------------------------------

def test_todo_without_issue_is_advisory_only():
    diff = _diff("app/core.py", ["# TODO: handle empty input"])
    findings = sc.scan_diff(diff)
    assert _rules(findings) == ["todo-without-issue"]
    assert findings[0].blocking is False
    assert sc.blocking_findings(findings) == []


def test_todo_with_issue_reference_is_clean():
    diff = _diff("app/core.py", ["# TODO(#123): handle empty input"])
    assert sc.scan_diff(diff) == []


# ---- ขอบเขตการสแกน ----------------------------------------------------------------------------

def test_removed_and_context_lines_are_not_scanned():
    diff = (
        "diff --git a/app/core.py b/app/core.py\n--- a/app/core.py\n+++ b/app/core.py\n"
        "@@ -1,3 +1,2 @@\n"
        " except:\n"          # context: เดิมอยู่แล้ว ไม่ใช่ของใหม่
        "-    debugger\n"     # ถูกลบออก
        "     pass\n"
    )
    assert sc.scan_diff(diff) == []


def test_line_numbers_follow_hunk_header():
    diff = _diff("app/core.py", ["except:", "    pass"], start=40, context_before=["x = 1", "y = 2"])
    findings = sc.scan_diff(diff)
    assert findings[0].line == 42  # hunk เริ่มที่ 40, มี context 2 บรรทัดก่อน `except:`


def test_format_findings_names_path_line_and_rule():
    diff = _diff("app/core.py", ["except:", "    pass"])
    text = sc.format_findings(sc.blocking_findings(sc.scan_diff(diff)))
    assert "app/core.py:1" in text
    assert "broad-except-swallow" in text


# ---- เชื่อมกับ evaluate_diff: ผลบล็อกต้องเกิดก่อนเรียก LLM ------------------------------------------

def test_evaluate_diff_fails_fast_on_blocking_finding(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "core.py").write_text("try:\n    run()\nexcept:\n    pass\n", encoding="utf-8")
    diff = _diff("app/core.py", ["except:", "    pass"])
    res = evaluate_diff(diff, "fix core", "", {}, tmp_path,
                        call_agent=lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not run")))
    assert res.passed is False
    assert res.score == 0.0
    assert "broad-except-swallow" in res.critique_th
    assert res.fix_location == ["app/core.py:1"]  # diff นี้เพิ่ม `except:` เป็นบรรทัดแรกของ hunk


def test_evaluate_diff_passes_static_scan_when_clean_and_reports_advisory(tmp_path: Path):
    diff = _diff("app/core.py", ["# TODO: later"])
    assert sc.blocking_findings(sc.scan_diff(diff)) == []
    advisory = sc.format_advisory(sc.scan_diff(diff))
    assert "todo-without-issue" in advisory


def test_judge_prompt_declares_static_findings_and_test_quality_rule():
    tmpl = (Path(sc.__file__).resolve().parent.parent / "prompts" / "evaluator.md").read_text(encoding="utf-8")
    assert "{{static_findings}}" in tmpl
    assert "concrete value" in tmpl.lower() or "ค่าที่คาดหวัง" in tmpl


def test_coder_prompt_states_big_company_bar():
    tmpl = (Path(sc.__file__).resolve().parent.parent / "prompts" / "task.md").read_text(encoding="utf-8")
    assert "## Engineering Standards" in tmpl
    assert "except: pass" in tmpl or "swallow" in tmpl.lower()
    assert "debugger" in tmpl
    assert "concrete value" in tmpl.lower()
    assert "TODO" in tmpl

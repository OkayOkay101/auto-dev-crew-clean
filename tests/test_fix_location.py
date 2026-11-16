"""fix_location จาก judge: parse อย่างปลอดภัย, ส่งเข้ารอบปรับปรุง, และด่าน 3 ยอมรับไฟล์ที่ judge ชี้."""
from types import SimpleNamespace

from auto_dev_crew import evaluator, quality_gates, runner

JSON_OK = (
    '```json\n{"task_alignment": 0.4, "safety_cleanliness": 0.9, "quality": 0.8, '
    '"critique_th": "แก้ผิดที่", "fix_location": %s}\n```'
)


def test_parse_reads_fix_location():
    res = evaluator.parse_eval_response(JSON_OK % '["src/app.js:12", "lib/util.py:3-9"]')
    assert res.fix_location == ["src/app.js:12", "lib/util.py:3-9"]


def test_parse_missing_or_bad_fix_location_is_empty():
    assert evaluator.parse_eval_response(JSON_OK % "null").fix_location == []
    assert evaluator.parse_eval_response(JSON_OK % '"app.js"').fix_location == []
    assert evaluator.parse_eval_response(JSON_OK % '[1, null, {"a": 1}]').fix_location == []


def test_parse_dedupes_and_caps_entries():
    items = ['"a.py:%d"' % i for i in range(9)] + ['"a.py:0"']
    res = evaluator.parse_eval_response(JSON_OK % ("[" + ", ".join(items) + "]"))
    assert len(res.fix_location) == evaluator.MAX_FIX_LOCATIONS
    assert len(set(res.fix_location)) == len(res.fix_location)


def test_parse_failure_path_has_no_fix_location():
    res = evaluator.parse_eval_response("ไม่ใช่ JSON")
    assert res.fix_location == []


def test_hint_empty_when_no_location():
    assert runner._fix_location_hint(evaluator.EvaluationResult(0.5, False, "", {})) == ""


def test_hint_lists_locations():
    res = evaluator.EvaluationResult(0.5, False, "", {}, fix_location=["src/app.js:12"])
    hint = runner._fix_location_hint(res)
    assert "src/app.js:12" in hint
    assert "จุดที่ reviewer ชี้ว่าควรแก้" in hint


def test_fix_location_files_strips_line_and_keeps_production_only():
    res = SimpleNamespace(fix_location=["src/app.js:12", "tests/test_app.py:3", "src/app.js:40-50", "lib/x.py"])
    assert runner._fix_location_files(res) == ["src/app.js", "lib/x.py"]


def test_gate3_accepts_file_named_by_judge_not_by_issue():
    # issue อ้าง a.js แต่ judge ชี้ b.js: diff แก้ b.js ต้องผ่านด่าน 3
    named = ["a.js"] + ["b.js"]
    assert quality_gates.repair_gate_violation(named, ["b.js"]) is None


def test_gate3_still_blocks_when_neither_named_file_touched():
    named = ["a.js", "b.js"]
    assert quality_gates.repair_gate_violation(named, ["c.js"]) is not None

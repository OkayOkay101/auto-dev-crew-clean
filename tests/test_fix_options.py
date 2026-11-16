"""fix_options จาก judge: parse อย่างปลอดภัย, ไม่กระทบคะแนน, และส่งเข้ารอบปรับปรุง."""
import json

from auto_dev_crew import evaluator, runner

BASE = {"task_alignment": 0.4, "safety_cleanliness": 0.9, "quality": 0.8, "critique_th": "แก้ผิดที่"}


def _raw(extra: dict | None = None) -> str:
    data = dict(BASE, **(extra or {}))
    return "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"


def test_parse_reads_options_with_pros_and_cons():
    opts = [{"approach": "ย้ายเช็คค่าว่างขึ้นก่อน", "pros": "สั้น", "cons": "ต้องแก้สองจุด"}]
    res = evaluator.parse_eval_response(_raw({"fix_options": opts}))
    assert res.fix_options == opts


def test_parse_bad_or_missing_options_is_empty():
    assert evaluator.parse_eval_response(_raw()).fix_options == []
    assert evaluator.parse_eval_response(_raw({"fix_options": "x"})).fix_options == []
    assert evaluator.parse_eval_response(_raw({"fix_options": [1, None, "a"]})).fix_options == []
    assert evaluator.parse_eval_response(_raw({"fix_options": [{"pros": "x"}]})).fix_options == []


def test_parse_caps_count_and_text_length():
    items = [{"approach": "ก" * 1000, "pros": 5, "cons": "ข"} for _ in range(5)]
    res = evaluator.parse_eval_response(_raw({"fix_options": items}))
    assert len(res.fix_options) == evaluator.MAX_FIX_OPTIONS
    assert len(res.fix_options[0]["approach"]) == evaluator.MAX_FIX_OPTION_TEXT
    assert res.fix_options[0]["pros"] == ""  # non-string becomes empty, not an error


def test_options_do_not_change_score_or_pass():
    plain = evaluator.parse_eval_response(_raw())
    with_opts = evaluator.parse_eval_response(
        _raw({"fix_options": [{"approach": "แก้", "pros": "เร็ว", "cons": "เสี่ยง"}]}))
    assert with_opts.score == plain.score
    assert with_opts.passed == plain.passed


def test_parse_failure_path_has_no_options():
    assert evaluator.parse_eval_response("ไม่ใช่ JSON").fix_options == []


def test_hint_empty_when_nothing_suggested():
    assert runner._fix_location_hint(evaluator.EvaluationResult(0.5, False, "", {})) == ""


def test_hint_includes_options_with_pros_and_cons():
    res = evaluator.EvaluationResult(
        0.5, False, "", {},
        fix_options=[{"approach": "วิธี A", "pros": "ข้อดี A", "cons": "ข้อเสีย A"}])
    hint = runner._fix_location_hint(res)
    assert "ทางเลือกการแก้" in hint
    assert "วิธี A" in hint and "ข้อดี A" in hint and "ข้อเสีย A" in hint

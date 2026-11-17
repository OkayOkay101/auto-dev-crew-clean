"""พจนานุกรมอังกฤษ auto_dev_crew/locales/en.json

คีย์เป็นข้อความไทยต้นฉบับ (ค่าเริ่มต้นไม่มีไฟล์ th.json: ถ้าไม่มีคำแปลจะแสดงไทยเอง)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "auto_dev_crew" / "locales"
THAI = re.compile(r"[฀-๿]")


def _en() -> dict[str, str]:
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def test_en_json_is_a_flat_string_map():
    data = _en()
    assert isinstance(data, dict) and data
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())


def test_en_values_are_not_empty():
    assert [k for k, v in _en().items() if not v.strip()] == []


def test_en_values_contain_no_thai_characters():
    assert [k for k, v in _en().items() if THAI.search(v)] == []


def test_known_pairs_from_old_dictionaries_are_kept():
    data = _en()
    assert data["ภาษาไทย"] == "Thai"  # จาก EN_TEXT เดิม
    assert data["(ปิด)"] == "(off)"  # จาก i18n_en.js เดิม

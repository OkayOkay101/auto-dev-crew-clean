"""ความครบถ้วนของการแปลไทย/อังกฤษ (กลไกคีย์: auto_dev_crew/locales/en.json)

- ทุกคีย์ไทยที่หน้าเว็บใช้ (data-i18n, data-i18n-attr, i18n("...")) ต้องมีคำแปลใน en.json
- ทุกคีย์ที่ Backend ใช้ (_i18n.t("...")) ต้องมีคำแปลใน en.json
- ค่าเริ่มต้นเป็นไทยทั้งฝั่งเว็บและ Backend
"""
from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "auto_dev_crew" / "static"
PKG = ROOT / "auto_dev_crew"
THAI = re.compile(r"[฀-๿]")
CALL = re.compile(r'\bi18n\("((?:[^"\\\n]|\\.)*)"')
BACKEND_CALL = re.compile(r'_i18n\.t\("((?:[^"\\\n]|\\.)*)"')


def _en() -> dict[str, str]:
    return json.loads((PKG / "locales" / "en.json").read_text(encoding="utf-8"))


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.keys: set[str] = set()
        self.stack: list[list] = []  # [tag, has_i18n, is_html, buf]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in ("br", "img", "input", "hr", "meta", "link"):
            # data-i18n แบบไม่มีค่าให้ค่าเป็น None ต้องตรวจการมีอยู่ของ attribute ไม่ใช่ค่า
            self.stack.append([tag, "data-i18n" in a, a.get("data-i18n") == "html", []])
        for name in (a.get("data-i18n-attr") or "").split():
            value = a.get(name)
            if value and THAI.search(value):
                self.keys.add(value.strip())

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                _tag, has, is_html, buf = self.stack.pop(i)
                text = "".join(buf).strip()
                if has and not is_html and text:
                    self.keys.add(text)
                break

    def handle_data(self, data):
        # ข้อความเป็นของ data-i18n ที่อยู่ชั้นในสุด (เหมือนตัวแปลฝั่งเว็บ)
        for item in reversed(self.stack):
            if item[1] and not item[2]:
                item[3].append(data)
                break


def _html_keys(path: Path) -> set[str]:
    parser = _Collector()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.keys


def _js_keys(text: str) -> set[str]:
    return {json.loads('"' + m.group(1) + '"') for m in CALL.finditer(text)}


class TestEnglishCoverage(unittest.TestCase):
    def test_every_web_key_has_english(self):
        used: set[str] = set()
        for name in ("index_sidebar.html", "index.html"):
            path = STATIC / name
            used |= _html_keys(path)
            used |= _js_keys(path.read_text(encoding="utf-8"))
        used |= _js_keys((STATIC / "mission_control.js").read_text(encoding="utf-8"))
        used = {k for k in used if THAI.search(k)}
        en = _en()
        missing = sorted(k for k in used if k not in en)
        self.assertEqual(missing, [], f"คีย์หน้าเว็บที่ยังไม่มีคำแปล ({len(missing)})")

    def test_every_backend_key_has_english(self):
        used: set[str] = set()
        for path in sorted(PKG.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in BACKEND_CALL.finditer(text):
                used.add(json.loads('"' + m.group(1) + '"'))
        en = _en()
        missing = sorted(k for k in used if k not in en)
        self.assertEqual(missing, [], f"คีย์ Backend ที่ยังไม่มีคำแปล ({len(missing)})")

    def test_english_values_have_no_thai(self):
        self.assertEqual([k for k, v in _en().items() if THAI.search(v)], [])

    def test_default_language_is_thai_on_both_sides(self):
        from auto_dev_crew import i18n

        self.assertEqual(i18n.DEFAULT, "th")
        self.assertEqual(i18n.normalize_lang(None), "th")
        sb = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
        self.assertIn('const uiLang = window.adcLang || "th";', sb)
        js = (STATIC / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('var lang = "th";', js)


if __name__ == "__main__":
    unittest.main()

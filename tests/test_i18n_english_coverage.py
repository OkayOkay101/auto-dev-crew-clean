"""ความครอบคลุมการแปลหน้า GUI เป็นอังกฤษ (EN) และค่าเริ่มต้นเป็นไทย

เทสต์นี้จำลองพฤติกรรมของ auto_dev_crew/static/i18n.js:
- แปลข้อความทั้งช่องถ้าตรงกับคีย์พอดี (หลังตัดช่องว่างหัวท้าย)
- ไม่เช่นนั้นแทนวลีที่เป็น "phrase" ในข้อความ (ยาว >= 12 ตัว หรือมีช่องว่าง/วงเล็บและยาว >= 3)
ถ้าหลังแปลแล้วยังเหลืออักษรไทยในข้อความที่ผู้ใช้เห็น ถือว่ายังไม่ได้แปล
"""
from __future__ import annotations

import html as html_lib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "auto_dev_crew" / "static"
THAI = re.compile(r"[฀-๿]")
PAIR_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"\s*:\s*"((?:[^"\\\n]|\\.)*)"')


def _load_pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in PAIR_RE.findall(text):
        out[json.loads('"' + k + '"')] = json.loads('"' + v + '"')
    return out


def _dictionaries() -> tuple[dict[str, str], dict[str, str]]:
    adc = _load_pairs((STATIC / "i18n_en.js").read_text(encoding="utf-8"))
    sb = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
    m = re.search(r"const EN_TEXT = \{(.*?)\n\};", sb, re.S)
    en_text = _load_pairs(m.group(1)) if m else {}
    return adc, en_text


def _is_phrase(k: str) -> bool:
    t = k.strip()
    return len(t) >= 12 or (bool(re.search(r"[\s()]", k)) and len(t) >= 2)


def _translate(s: str, adc: dict[str, str], en_text: dict[str, str]) -> str:
    """จำลอง tr() ของ index_sidebar.html + translateText() ของ i18n.js"""
    t = s.strip().replace("\r\n", "\n")
    if t in en_text:
        return en_text[t]
    if t in adc:
        return adc[t]
    out = s
    for k in sorted(list(adc) + list(en_text), key=len, reverse=True):
        if not k.strip() or not _is_phrase(k):
            continue
        value = adc.get(k, en_text.get(k))
        if k in out:
            out = out.replace(k, value)
    return out


def _strip_js_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


def _html_text_nodes(html: str) -> list[str]:
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    return [html_lib.unescape(t) for t in re.findall(r">([^<>]*)<", body) if THAI.search(t)]


def _html_attr_values(html: str) -> list[str]:
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    attrs = r'(?:title|placeholder|aria-label)="([^"]*)"'
    return [html_lib.unescape(v) for v in re.findall(attrs, body) if THAI.search(v)]


def _remove_expressions(lit: str) -> str:
    """ตัด ${...} ทั้งก้อน รวมวงเล็บปีกกาที่ซ้อนอยู่ข้างใน"""
    out, i = [], 0
    while i < len(lit):
        if lit.startswith("${", i):
            depth, j = 0, i + 1
            while j < len(lit):
                if lit[j] == "{":
                    depth += 1
                elif lit[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append("\x00")
            i = j + 1
        else:
            out.append(lit[i])
            i += 1
    return "".join(out)


def _js_nodes(js: str) -> list[str]:
    """ข้อความที่เบราว์เซอร์แสดงจาก string/template literal ของ JS

    ${...} แทนด้วย X (ค่าที่เปลี่ยนตามข้อมูลจริง), HTML tag แบ่งเป็นคนละ text node,
    และค่า title/placeholder/aria-label ก็เป็น text node ของตัวเอง
    """
    js = _strip_js_comments(js)
    raw: list[str] = []
    for pat in (r'"((?:[^"\\\n]|\\.)*)"', r"'((?:[^'\\\n]|\\.)*)'"):
        # สตริงแบบ "..." / '...' ที่มี ${ มักอยู่ข้างในบล็อก template (เช่น title="…${r}…") จึงให้ template จัดการแทน
        raw.extend(lit for lit in re.findall(pat, js) if "${" not in lit)
    raw.extend(re.findall(r"`([^`]*)`", js))
    nodes: list[str] = []
    for lit in raw:
        if not THAI.search(lit):
            continue
        rendered = re.sub(r"\$\{[^}]*\}", "X", lit)
        for attr in re.findall(r'(?:title|placeholder|aria-label)=\\?"((?:[^"\\]|\\(?!"))*)\\?"', rendered):
            nodes.append(attr.replace("\\n", "\n"))
        for piece in re.split(r"<[^>]+>", rendered):
            piece = piece.replace("\\n", "\n")
            if THAI.search(piece) and not re.search(r"[{}]", piece):
                nodes.append(piece)
    return nodes


PY_UI_FIELD = re.compile(
    r"""["'](title|description|label|detail|details|message|msg|hint|error|reason|summary|warning|text|help|"""
    r"""tooltip|caption|subtitle|body|heading|desc|note)["']\s*:\s*(f?)(["'])((?:(?!\3).)*)\3"""
)
PY_UI_SKIP = {"quality_gates.py"}  # เทมเพลต prompt ที่ AI อ่าน ไม่ใช่ข้อความที่ผู้ใช้เห็น


def _python_ui_strings() -> list[str]:
    """ข้อความไทยในฟิลด์ที่เซิร์ฟเวอร์ส่งให้หน้า GUI (ค่าใน f-string แทนด้วย X เหมือนที่แสดงจริง)"""
    out: list[str] = []
    for path in sorted((ROOT / "auto_dev_crew").glob("*.py")):
        if path.name in PY_UI_SKIP:
            continue
        src = path.read_text(encoding="utf-8")
        for m in PY_UI_FIELD.finditer(src):
            text = m.group(4)
            if not THAI.search(text):
                continue
            if m.group(2) == "f":
                # {'เปิด' if c else 'ปิด'} คือข้อความสองแบบ จึงต้องตรวจทั้งสองทาง
                for alt in _conditional_variants(text):
                    out.append(re.sub(r"\{[^{}]*\}", "X", alt))
            else:
                out.append(text)
    return out


COND_EXPR = re.compile(r"\{'([^']*)' if [^{}]*? else '([^']*)'\}")


def _conditional_variants(text: str) -> list[str]:
    m = COND_EXPR.search(text)
    if not m:
        return [text]
    return [
        *_conditional_variants(text[: m.start()] + m.group(1) + text[m.end():]),
        *_conditional_variants(text[: m.start()] + m.group(2) + text[m.end():]),
    ]


def _untranslated(texts: list[str], adc: dict[str, str], en_text: dict[str, str]) -> list[str]:
    """ข้อความที่ยังไม่มีคำแปลในบริบทจริง: หลังแทนด้วย i18n.js แล้วยังมีอักษรไทยเหลือ"""
    missing = []
    for text in dict.fromkeys(texts):
        if THAI.search(_translate(text, adc, en_text)):
            missing.append(text)
    return missing


class TestEnglishCoverage(unittest.TestCase):
    def setUp(self):
        self.adc, self.en_text = _dictionaries()

    def test_dictionary_values_are_english(self):
        bad = [k for k, v in {**self.adc, **self.en_text}.items() if THAI.search(v)]
        self.assertEqual(bad, [], "คำแปลยังเป็นภาษาไทย")

    def test_sidebar_html_text_is_translated(self):
        html = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
        missing = _untranslated(_html_text_nodes(html), self.adc, self.en_text)
        self.assertEqual(missing, [], f"index_sidebar.html ข้อความที่ยังไม่มีคำแปล ({len(missing)})")

    def test_sidebar_attributes_are_translated(self):
        html = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
        missing = _untranslated(_html_attr_values(html), self.adc, self.en_text)
        self.assertEqual(missing, [], f"index_sidebar.html attribute ที่ยังไม่มีคำแปล ({len(missing)})")

    def test_sidebar_script_strings_are_translated(self):
        html = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
        scripts = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
        missing = _untranslated(_js_nodes(scripts), self.adc, self.en_text)
        self.assertEqual(missing, [], f"index_sidebar.html สตริงใน script ที่ยังไม่มีคำแปล ({len(missing)})")

    def test_classic_page_is_translated(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        texts = _html_text_nodes(html) + _html_attr_values(html)
        scripts = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
        texts += _js_nodes(scripts)
        missing = _untranslated(texts, self.adc, self.en_text)
        self.assertEqual(missing, [], f"index.html (/classic) ที่ยังไม่มีคำแปล ({len(missing)})")

    def test_server_messages_are_translated(self):
        # ข้อความที่เซิร์ฟเวอร์ส่งให้หน้า GUI แสดง (title / message / error / reason ฯลฯ) ต้องมีคำแปลด้วย
        # quality_gates.py ไม่รวม: เป็นเทมเพลต prompt ที่ AI อ่าน ไม่ใช่ข้อความที่ผู้ใช้เห็น
        missing = _untranslated(_python_ui_strings(), self.adc, self.en_text)
        self.assertEqual(missing, [], f"ข้อความฝั่งเซิร์ฟเวอร์ที่ยังไม่มีคำแปล ({len(missing)})")

    def test_default_language_is_thai(self):
        i18n = (STATIC / "i18n.js").read_text(encoding="utf-8")
        sb = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
        mc = (STATIC / "mission_control.js").read_text(encoding="utf-8")
        self.assertIn('let uiLang = "th";', sb)
        self.assertIn('storageGet("adc_lang", "th") === "en"', mc)
        # ผู้ใช้ที่เคยเก็บค่า en ไว้ในเบราว์เซอร์ ต้องถูกตั้งกลับเป็นไทยครั้งเดียวตามการเปลี่ยนค่าเริ่มต้น
        self.assertIn('localStorage.setItem("adc_lang", "th")', i18n)
        self.assertIn("adc_lang_default", i18n)


if __name__ == "__main__":
    unittest.main()

"""GUI wording for gates 3 and 4 must match the code (docs/troubleshooting.md row 16, 2026-11-18)."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")
EN = json.loads((ROOT / "auto_dev_crew" / "locales" / "en.json").read_text(encoding="utf-8"))

GATE_3_TH = "ด่าน 3: ทุกการทำงานของ issue ที่ระบุไฟล์ ต้องแตะไฟล์นั้น"
GATE_3_EN = "Gate 3: every issue run that names a file must touch that file"
DEEP_SCAN_TH = ("ให้ AI อ่านโค้ดทีละส่วนแล้วรายงานปัญหา ผลที่ผ่านด่าน 4 สร้างเป็น issue ai-task ได้ "
                "เมื่อเปิดสร้างอัตโนมัติ (ปุ่มสร้างทีละรายการไม่ผ่านด่าน 4)")
DEEP_SCAN_EN = ("AI reads the code section by section and reports problems. Results that pass gate 4 "
                "become ai-task issues when automatic creation is on (the per-finding create button skips gate 4)")


class TestGateWordingGui(unittest.TestCase):
    def test_gate_3_text_says_every_run_not_only_repair_rounds(self):
        self.assertIn(GATE_3_TH, SIDEBAR)
        self.assertNotIn("ด่าน 3: รอบซ่อมต้องแตะไฟล์ที่ issue ระบุ", SIDEBAR)

    def test_gate_3_has_english_translation(self):
        full_th = ("ด่าน 1: judge ยืนยันว่าบั๊กใน issue มีจริงก่อนแก้ · ด่าน 2: judge เห็นไฟล์เต็มหลังแก้ ไม่ใช่แค่ diff · "
                   + GATE_3_TH + " · ด่าน 4: deep-scan ตรวจซ้ำก่อนสร้าง issue")
        self.assertIn(full_th, SIDEBAR)
        self.assertIn(GATE_3_EN, EN.get(full_th, ""))

    def test_deep_scan_text_says_gate_4_skipped_by_per_item_button(self):
        self.assertIn(DEEP_SCAN_TH, SIDEBAR)
        self.assertEqual(EN.get(DEEP_SCAN_TH), DEEP_SCAN_EN)


if __name__ == "__main__":
    unittest.main()

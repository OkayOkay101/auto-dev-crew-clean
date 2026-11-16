"""การ์ด BYOP ต้องมีส่วนเลือกโมเดลเอง (ปุ่มดึงโมเดล + ตัวเลือก) โดยการ์ดคีย์ที่ผู้ใช้วางเองยังเหมือนเดิม."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDEBAR = (ROOT / "auto_dev_crew" / "static" / "index_sidebar.html").read_text(encoding="utf-8")


def _byop_card() -> str:
    start = SIDEBAR.index('id="byopCard"')
    end = SIDEBAR.index('id="keyManagerCard"', start)
    return SIDEBAR[start:end]


class ByopModelPickerTests(unittest.TestCase):
    def test_byop_card_has_its_own_fetch_button_and_hidden_picker_section(self):
        # ชื่อ engine จริงของ Pollinations คือ opencode-pollinations (ตรงกับ config.yaml และการ์ดคีย์)
        card = _byop_card()
        self.assertIn('data-fetch-models="opencode-pollinations"', card)
        self.assertIn('data-scope="byop"', card)
        self.assertIn('id="byop-model-box-opencode-pollinations"', card)
        section_open_tag = card.split('id="byopModelSection"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", section_open_tag)  # ซ่อนจนกว่าจะเชื่อมต่อแล้ว

    def test_byop_status_no_longer_points_to_another_card(self):
        self.assertNotIn("การ์ด Pollinations.ai", SIDEBAR)


class ManualKeyProviderCardTests(unittest.TestCase):
    def test_provider_card_keeps_its_model_picker_for_manually_entered_keys(self):
        self.assertIn('data-fetch-models="${esc(p.name)}"', SIDEBAR)
        self.assertIn('id="model-box-${esc(p.name)}"', SIDEBAR)


if __name__ == "__main__":
    unittest.main()

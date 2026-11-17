"""ข้อความที่ส่งไปหน้าเว็บ/การแจ้งเตือนใน gui.py ต้องผ่าน _i18n.t (ไม่ใช่ f-string ไทยตรง ๆ)

log (_emit), PR body และ print ตอนเริ่มระบบยังคงเป็นไทยตามการตัดสินใจของโปรเจกต์
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

GUI = Path(__file__).resolve().parent.parent / "auto_dev_crew" / "gui.py"
THAI = re.compile(r"[฀-๿]")
# รูปแบบข้อความที่ผู้ใช้เห็น: "message"/"error"/"title" ใน dict, raise ValueError(f"..."),
# msg = f"..." / msg = (f"...", else f"...", redact_secrets(f"...")
USER_FACING_FSTRING = re.compile(
    r'(?:"message"|"error"|"title"|ValueError\(|msg\s*=\s*\(?|else\s+|redact_secrets\()\s*:?\s*\(?\s*f"[^"\n]*'
)


class TestGuiUserMessagesUseI18n(unittest.TestCase):
    def test_no_thai_fstring_user_messages_in_gui(self):
        offenders = []
        for lineno, line in enumerate(GUI.read_text(encoding="utf-8").splitlines(), 1):
            for m in USER_FACING_FSTRING.finditer(line):
                if THAI.search(m.group(0)):
                    offenders.append(f"{lineno}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], f"ข้อความ UI ที่ยังไม่ผ่าน i18n ({len(offenders)})")


if __name__ == "__main__":
    unittest.main()

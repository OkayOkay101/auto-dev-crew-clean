"""ระบบล็อกอินด้วยรหัสผ่านของ GUI ถูกลบแล้ว (ไม่ใช้อีกต่อไป)

หน้าสาธารณะ (public_view) และ gh device login (github_login) ไม่ได้อยู่ในขอบเขตนี้
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "auto_dev_crew"
GUI_SRC = (PKG / "gui.py").read_text(encoding="utf-8")


class TestPasswordLoginRemoved(unittest.TestCase):
    def test_auth_module_is_gone(self):
        self.assertIsNone(importlib.util.find_spec("auto_dev_crew.auth"))

    def test_login_page_is_gone(self):
        self.assertFalse((PKG / "static" / "login.html").exists())

    def test_gui_has_no_login_gate_or_routes(self):
        for needle in ("REQUIRE_LOGIN", "_logged_in", "SESSIONS", "LOGIN_LIMITER",
                       "AUTH_FILE", "/api/login", "/api/logout", '"/login"', "--require-login"):
            self.assertNotIn(needle, GUI_SRC, needle)

    def test_public_view_still_exists(self):
        self.assertTrue((PKG / "public_view.py").exists())


if __name__ == "__main__":
    unittest.main()

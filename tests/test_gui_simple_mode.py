import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "auto_dev_crew" / "static"
SIDEBAR = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
MC_JS = (STATIC / "mission_control.js").read_text(encoding="utf-8")


def _open_tag_with_id(html, id_):
    m = re.search(r"<[a-zA-Z][^>]*\bid=\"" + re.escape(id_) + r"\"[^>]*>", html)
    return m.group(0) if m else ""


class TestSimpleModeDefault(unittest.TestCase):
    def test_first_run_defaults_to_simple(self):
        # ผู้ใช้ครั้งแรก (ยังไม่เคยเลือกโหมด) ต้องเห็นโหมดง่าย
        self.assertIn('storageGet("adc_ui_mode", "simple")', MC_JS)
        self.assertNotIn('storageGet("adc_ui_mode", "pro")', MC_JS)

    def test_init_does_not_overwrite_saved_choice(self):
        # การโหลดหน้าต้องไม่เขียนทับค่าที่ผู้ใช้เคยเลือก (เช่น "pro")
        init = MC_JS[MC_JS.index("function bindModeSwitch"):MC_JS.index("function initMissionControl")]
        self.assertIn('applyUiMode(storageGet("adc_ui_mode", "simple"))', init)
        self.assertNotIn("setUiComplexityMode(storageGet", MC_JS)

    def test_user_click_still_persists_mode(self):
        body = MC_JS[MC_JS.index("function setUiComplexityMode"):MC_JS.index("// 2. Category 8")]
        self.assertIn('storageSet("adc_ui_mode", clean)', body)
        self.assertIn("applyUiMode(clean)", body)

    def test_no_flash_script_sets_mode_before_paint(self):
        head = SIDEBAR[:SIDEBAR.index("</head>")]
        self.assertIn('localStorage.getItem("adc_ui_mode")', head)
        self.assertIn('"simple"', head)


class TestSimpleModeCss(unittest.TestCase):
    def test_simple_mode_hides_pro_only(self):
        self.assertIn('html[data-ui-mode="simple"] [data-pro-only]', SIDEBAR)
        rule = SIDEBAR[SIDEBAR.index('html[data-ui-mode="simple"] [data-pro-only]'):]
        self.assertIn("display: none !important", rule.split("}", 1)[0])

    def test_advanced_blocks_tagged_pro_only(self):
        for id_ in ["mergeCard", "toolsCard", "studioFindTools", "failoverCard", "subRecent"]:
            self.assertIn("data-pro-only", _open_tag_with_id(SIDEBAR, id_), id_)

    def test_beginner_core_not_hidden(self):
        # หน้าหลักที่ผู้เริ่มต้นต้องใช้ต้องไม่ถูกซ่อน
        for id_ in ["newTaskBtn", "langBtn", "openTutorialBtn", "langCard", "glossary"]:
            self.assertNotIn("data-pro-only", _open_tag_with_id(SIDEBAR, id_), id_)


class TestTutorial(unittest.TestCase):
    def test_settings_has_reopen_button(self):
        self.assertIn('id="openTutorialBtn"', SIDEBAR)

    def test_tutorial_storage_flag_and_open_fn(self):
        self.assertIn('"adc_tutorial_done"', MC_JS)
        self.assertIn("function openTutorial", MC_JS)

    def test_tutorial_auto_opens_only_on_first_run(self):
        self.assertRegex(MC_JS, r"if \(!tutorialDone\(\)\)\s*\{?\s*[^\n]*openTutorial")

    def test_tutorial_covers_every_main_panel(self):
        steps = MC_JS[MC_JS.index("const TUTORIAL_STEPS"):MC_JS.index("function tutorialDone")]
        for target in ["overview", "work", "studio", "keys", "settings"]:
            self.assertIn(f'target: "{target}"', steps, target)

    def test_tutorial_has_thai_and_english_text(self):
        steps = MC_JS[MC_JS.index("const TUTORIAL_STEPS"):MC_JS.index("function tutorialDone")]
        self.assertGreaterEqual(steps.count("th:"), 6)
        self.assertGreaterEqual(steps.count("en:"), 6)

    def test_tutorial_uses_textcontent_only(self):
        self.assertNotIn("innerHTML", MC_JS)

    def test_tutorial_fallback_when_dialog_unsupported(self):
        self.assertIn('setAttribute("open"', MC_JS)

    def test_mission_control_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        result = subprocess.run([node, "--check", str(STATIC / "mission_control.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

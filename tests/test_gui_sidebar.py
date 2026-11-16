import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "auto_dev_crew" / "static"
SIDEBAR = (STATIC / "index_sidebar.html").read_text(encoding="utf-8")
GUI_PY = (ROOT / "auto_dev_crew" / "gui.py").read_text(encoding="utf-8")


class TestGuiSidebarVariant(unittest.TestCase):
    def test_root_serves_sidebar_with_token(self):
        self.assertIn('url.path == "/":', GUI_PY)
        self.assertIn('STATIC / "index_sidebar.html"', GUI_PY)
        self.assertIn("{{TOKEN}}", SIDEBAR)

    def test_classic_route_keeps_old_ui(self):
        self.assertIn('url.path == "/classic"', GUI_PY)
        self.assertIn('STATIC / "index.html"', GUI_PY)

    def test_nav_tabs_match_main_panels(self):
        nav = re.search(r'<nav class="side"[^>]*>(.*?)</nav>', SIDEBAR, re.S).group(1)
        values = sorted(re.findall(r'data-main="([^"]+)"', nav))
        self.assertEqual(values, ["keys", "overview", "settings", "studio", "work"])
        for v in values:
            self.assertIn(f'id="main-{v}"', SIDEBAR, v)

    def test_required_ids_kept_for_shared_js(self):
        ids = ["dot", "agentText", "mergeMode", "newTaskBtn", "themeBtn", "pageTitle", "topSlots",
               "bigStatus", "navIssueCount", "sideMerge", "runOnce", "runLoop", "agentRepoSelect",
               "persona", "dryRun", "stopBtn", "restartBtn", "serverToggleBtn", "needsList",
               "needsCount", "stats", "ciToggleBtn", "evalToggleBtn", "mergeModeSel", "repos",
               "toast", "log", "studioRepoSelect", "historyRows", "taskRepo", "createTask"]
        for id_ in ids:
            self.assertIn(f'id="{id_}"', SIDEBAR, id_)

    def test_shell_wrappers_balanced(self):
        self.assertEqual(SIDEBAR.count('<div class="app">'), 1)
        self.assertEqual(SIDEBAR.count('<div class="shell">'), 1)
        # app + shell ต้องปิดหลัง </main> ก่อน dialog
        close_main = SIDEBAR.index("</main>\n</div>\n</div>")
        self.assertLess(close_main, SIDEBAR.index('<dialog id="shutdownDlg"'))

    def test_confirm_dialogs_not_removed(self):
        # ข้อกำหนดใน AGENTS.md: GUI ต้องมี confirm() ก่อนสแกน/สร้าง issue
        self.assertGreaterEqual(SIDEBAR.count("confirm("), 3)


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")


def _block(pattern):
    m = re.search(pattern, HTML, re.S)
    return m.group(1) if m else ""


class TestGuiLayout(unittest.TestCase):
    def test_app_branding(self):
        html_content = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>Auto Dev Crew</title>", html_content)
        self.assertIn("<h1>Auto Dev Crew</h1>", html_content)

    def test_token_placeholder_kept(self):
        self.assertIn('const TOKEN = "{{TOKEN}}"', HTML)

    def test_new_task_entry_in_header(self):
        header = _block(r"<header>(.*?)</header>")
        self.assertIn('id="newTaskBtn"', header)
        self.assertIn('<dialog id="newTaskDlg"', HTML)

    def test_new_task_form_ids_inside_dialog(self):
        dlg = _block(r'<dialog id="newTaskDlg"[^>]*>(.*?)</dialog>')
        for id_ in ["taskRepo", "taskTitle", "taskBody", "createTask", "taskMsg", "closeNewTask"]:
            self.assertIn(f'id="{id_}"', dlg, id_)

    def test_repo_selection_and_scanning_ui(self):
        html_content = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="agentRepoSelect"', html_content)
        self.assertIn('id="scanReposBtn"', html_content)
        self.assertIn('id="scanRepoModal"', html_content)
        self.assertIn('id="addAllAutoCapableBtn"', html_content)
        self.assertIn('id="scanRepoSearch"', html_content)

    def test_single_save_button(self):
        self.assertIn('id="saveKeysBtn"', HTML)
        self.assertNotIn("saveKeysBtnTop", HTML)
        self.assertNotIn("saveKeysBtnBottom", HTML)

    def test_agent_restart_buttons(self):
        html_content = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="restartBtn"', html_content)
        self.assertIn('id="logRestartBtn"', html_content)
        self.assertIn('button.warning', html_content)
        self.assertIn('post("/api/restart"', html_content)

    def test_provider_filters(self):
        block = _block(r'id="providerFilters"(.*?)</div>')
        values = re.findall(r'data-filter="([^"]+)"', block)
        self.assertEqual(sorted(values), ["all", "configured", "cooldown", "judge", "scan"])

    def test_key_role_ui_elements(self):
        self.assertIn('id="countJudge"', HTML)
        self.assertIn('id="countScan"', HTML)
        self.assertIn('id="newKeyRole"', HTML)
        self.assertIn('data-filter="judge"', HTML)
        self.assertIn('data-filter="scan"', HTML)

    def test_main_tabs(self):
        nav = _block(r"<nav[^>]*>(.*?)</nav>")
        values = re.findall(r'data-main="([^"]+)"', nav)
        self.assertEqual(sorted(values), ["keys", "overview", "settings", "studio", "work"])


    def test_coding_studio_elements(self):
        self.assertIn('data-main="studio"', HTML)
        self.assertIn('id="main-studio"', HTML)
        studio_ids = [
            "studioRepoSelect", "studioSyncBtn", "studioAddRepoBtn", "studioStackBadges",
            "studioIssueList", "studioIssueCount", "studioFileList", "studioFileCount",
            "studioFileFilter", "studioPersona", "studioMode", "studioEngine", "studioPrompt",
            "studioSandboxCheck", "studioDispatchBtn", "studioBtnTest", "studioBtnSyntax",
            "studioBtnSecurity", "studioTabDiff", "studioTabCode", "studioTabConsole",
            "studioDiffPanel", "studioCodePanel", "studioConsolePanel",
            "studioDiffOutput", "studioCodeOutput", "studioConsoleOutput",
        ]
        for id_ in studio_ids:
            self.assertIn(f'id="{id_}"', HTML, f"Missing id: {id_}")

    def test_sub_tabs_grouped(self):
        nav = _block(r"<nav[^>]*>(.*?)</nav>")
        self.assertIn('role="group"', HTML)
        subs = re.findall(r'data-sub="([^"]+)"', HTML)
        self.assertEqual(sorted(subs), ["apikeys", "failover", "history", "log", "recent"])
        self.assertEqual(nav.count('data-sub='), 0)

    def test_required_element_ids_kept(self):
        for id_ in ["taskRepo", "taskTitle", "taskBody", "createTask", "taskMsg", "reloadKeysBtn",
                    "providerSearch", "providerFilters", "providerGrid", "engineRows", "usageRows",
                    "usageStats", "log", "historyRows", "diffDlg", "toast"]:
            self.assertIn(f'id="{id_}"', HTML, id_)


    def test_todo_list_reset_on_repo_switch(self):
        body = _block(r"async function loadStudioWorkspace\(repoName\) \{(.*?)\n\}")
        self.assertIn("resetStudioTodo()", body)
        reset = _block(r"function resetStudioTodo\(\) \{(.*?)\n\}")
        self.assertIn('$("#studioTodoList").innerHTML = ""', reset)
        self.assertIn('$("#studioTodoCreateBtn").style.display = "none"', reset)

    def test_todo_scan_ignores_stale_repo_result(self):
        body = _block(r"async function studioTodoScan\(create\) \{(.*?)\n\}")
        self.assertIn("if (studioCurrentRepo !== repo) return;", body)

    def test_toast_is_live_status_region(self):
        self.assertIn('id="toast" role="status" aria-live="polite"', HTML)

    def test_focus_outline_not_removed(self):
        self.assertNotIn("outline: none", HTML)
        self.assertNotIn("outline:none", HTML)
        self.assertIn(":focus-visible", HTML)

    def test_masked_values_still_skipped_on_save(self):
        self.assertIn('!val.includes("...") && !val.includes("***")', HTML)

    def test_empty_provider_state_message_kept(self):
        self.assertIn("ไม่พบผู้ให้บริการที่ตรงกับเงื่อนไขการค้นหา", HTML)

    def test_show_hide_key_button_has_aria_pressed(self):
        self.assertIn('aria-pressed="false"', HTML)
        self.assertIn('aria-label="แสดงหรือซ่อนคีย์', HTML)


    def test_key_inputs_have_accessible_name(self):
        self.assertIn('aria-label="API Key ${esc(k.env_var)}"', HTML)


    def test_new_task_dialog_not_relying_on_invoker_commands(self):
        self.assertNotIn('command="show-modal"', HTML)
        self.assertNotIn('commandfor=', HTML)
        self.assertIn('$("#newTaskBtn").onclick', HTML)


    def test_dialog_modal_overscroll_containment(self):
        self.assertIn("dialog:modal { overscroll-behavior: contain; }", HTML)
        self.assertIn("overscroll-behavior: contain", HTML)

    def test_dialog_light_dismiss_fallback(self):
        self.assertIn('$("#newTaskDlg").addEventListener("click"', HTML)
        self.assertIn('$("#diffDlg").addEventListener("click"', HTML)
        self.assertIn('$("#newKeyDlg").addEventListener("click"', HTML)

    def test_work_subnav_order_log_before_history(self):
        work_block = _block(r'data-group="work"[^>]*>(.*?)</div>')
        pos_log = work_block.find('data-sub="log"')
        pos_hist = work_block.find('data-sub="history"')
        self.assertNotEqual(pos_log, -1)
        self.assertNotEqual(pos_hist, -1)
        self.assertLess(pos_log, pos_hist, "Log สด ต้องอยู่ก่อน ประวัติ ในเมนูย่อยของหน้างาน")
        self.assertIn('DEFAULT_SUB = {work: "log"', HTML)

    def test_timing_in_issues_and_prs(self):
        self.assertIn("${when(p.createdAt)}", HTML)
        self.assertIn("${when(i.createdAt)}", HTML)
        self.assertIn("<th>เวลาสร้าง</th>", HTML)

    def test_crud_keys_ui_elements(self):
        html_content = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<dialog id="newKeyDlg"', html_content)
        self.assertIn('id="newKeyName"', html_content)
        self.assertIn('id="newKeyValue"', html_content)
        self.assertIn('id="saveNewKeySubmit"', html_content)
        self.assertIn('id="knownKeySuggestions"', html_content)
        self.assertIn('data-delete-key=', html_content)
        self.assertIn('data-reset-cooldown=', html_content)

    def test_dynamic_model_fetcher_elements(self):
        self.assertIn("data-fetch-models=", HTML)
        self.assertIn("data-save-model=", HTML)
        self.assertIn("data-cancel-model=", HTML)
        self.assertIn("🔍 ดึงโมเดลจาก API", HTML)
        self.assertIn("/api/models", HTML)
        self.assertIn("/api/engine-model", HTML)
        self.assertIn("model-filter-input", HTML)
        self.assertIn("cachedModels", HTML)
        self.assertIn("openModelBoxes", HTML)

    def test_slot_assignments_and_file_locks_ui(self):
        html_content = (Path(__file__).resolve().parent.parent / "auto_dev_crew" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="slotAssignmentBox"', html_content)
        self.assertIn('id="slot2Persona"', html_content)
        self.assertIn('id="slot2Repo"', html_content)
        self.assertIn('id="saveSlot2Btn"', html_content)
        self.assertIn('id="slot3Persona"', html_content)
        self.assertIn('id="slot3Repo"', html_content)
        self.assertIn('id="saveSlot3Btn"', html_content)
        self.assertIn('id="activeLocksBadge"', html_content)
        self.assertIn('/api/slots/assignments', html_content)
        self.assertIn('/api/file-locks', html_content)
    def test_deep_scan_panel_ids(self):
        for id_ in ["studioDeepScanBtn", "studioDeepScanEngine", "studioDeepScanList"]:
            self.assertIn(f'id="{id_}"', HTML, id_)
        self.assertIn("/api/deep-scan/engines", HTML)
        self.assertIn("/api/deep-scan/file", HTML)
        self.assertIn("/api/deep-scan/dismiss", HTML)

    def test_deep_scan_renders_model_text_safely_and_confirms(self):
        body = _block(r"function renderDeepScan\(.*?\) \{(.*?)\n\}")
        self.assertTrue(body, "renderDeepScan missing")
        self.assertNotIn("innerHTML", body)
        self.assertIn("textContent", body)
        file_fn = _block(r"async function deepScanFile\(.*?\) \{(.*?)\n\}")
        self.assertIn("confirm(", file_fn)
        self.assertLess(file_fn.find("confirm("), file_fn.find("/api/deep-scan/file"))

    def test_deep_scan_inline_script_passes_node_check(self):
        import shutil
        import subprocess
        import tempfile
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        scripts = re.findall(r"<script>(.*?)</script>", HTML, re.S)
        self.assertTrue(scripts)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "inline.js"
            p.write_text("\n".join(scripts), encoding="utf-8")
            res = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()

"""Unit and security regression tests for MCP, Doctor, Context Slicer, Upgrades, Playground & GUI Patches."""
from __future__ import annotations

import datetime as dt
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import (
    autonomous_upgrades,
    context_slicer,
    doctor,
    gui_patches,
    mcp_server,
    playground,
)


class TestGuiSecurityPatches(unittest.TestCase):
    def test_require_registered_repo_blocks_cli_flags_and_unlisted_repos(self):
        cfg = {"repos": [{"name": "example-owner/auto-dev-crew"}]}
        for bad in ("-R/evil", "--help/repo", "../etc/passwd", "example-owner/not-in-config", ""):
            with self.assertRaises(ValueError):
                gui_patches.require_registered_repo(bad, cfg)
        self.assertEqual(
            gui_patches.require_registered_repo("example-owner/auto-dev-crew", cfg),
            "example-owner/auto-dev-crew",
        )

    def test_verify_request_security_checks_sec_fetch_site_and_hmac_token(self):
        ok, _ = gui_patches.verify_request_security(
            {"Sec-Fetch-Site": "cross-site", "X-Token": "tok123"},
            "tok123",
            require_token=True,
        )
        self.assertFalse(ok)

        ok_bad_tok, _ = gui_patches.verify_request_security(
            {"Sec-Fetch-Site": "same-origin", "X-Token": "wrong"},
            "tok123",
            require_token=True,
        )
        self.assertFalse(ok_bad_tok)

        ok_good, _ = gui_patches.verify_request_security(
            {"Sec-Fetch-Site": "same-origin", "X-Token": "tok123"},
            "tok123",
            require_token=True,
        )
        self.assertTrue(ok_good)

    def test_resolve_safe_worktree_path_blocks_outside_and_secret_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            work_root = Path(tmp) / "work"
            slot = work_root / "slot_1"
            slot.mkdir(parents=True)
            safe_py = slot / "app.py"
            safe_py.write_text("x = 1\n", encoding="utf-8")
            secret_env = slot / ".env"
            secret_env.write_text("API_KEY=secret\n", encoding="utf-8")

            self.assertEqual(gui_patches.resolve_safe_worktree_path(safe_py, work_root), safe_py.resolve())
            with self.assertRaises(PermissionError):
                gui_patches.resolve_safe_worktree_path(work_root, work_root)
            with self.assertRaises(PermissionError):
                gui_patches.resolve_safe_worktree_path(secret_env, work_root)
            with self.assertRaises(PermissionError):
                gui_patches.resolve_safe_worktree_path(Path(tmp) / "outside.txt", work_root)


class TestMcpServerAndRoleGuards(unittest.TestCase):
    def test_initialize_and_prompts_list(self):
        res = mcp_server.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(res["result"]["serverInfo"]["name"], "auto-dev-crew")
        prompts = mcp_server.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})
        names = {p["name"] for p in prompts["result"]["prompts"]}
        self.assertIn("adc-morning-briefing", names)
        self.assertIn("adc-review-protected-prs", names)

    def test_create_ai_task_requires_explicit_confirm_true(self):
        fake_cfg = {"repos": [{"name": "example-owner/example-repo-2"}]}
        with mock.patch.object(mcp_server.gui, "load_cfg", return_value=fake_cfg):
            denied = mcp_server.handle_rpc({
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "adc_create_ai_task",
                    "arguments": {"repo": "example-owner/example-repo-2", "title": "Fix timer", "confirm": False},
                },
            })
            self.assertEqual(denied["error"]["code"], -32001)

    def test_external_mcp_blocks_writable_server_for_judge_and_scan(self):
        writable_cfg = {"name": "worktree-fs", "command": "python -m fs_server", "read_only": False}
        with self.assertRaises(PermissionError):
            mcp_server.validate_external_mcp_client(writable_cfg, role="judge")
        with self.assertRaises(PermissionError):
            mcp_server.validate_external_mcp_client(writable_cfg, role="scan")

    def test_external_mcp_blocks_metacharacters_and_unlisted_binaries(self):
        for bad_cmd in ("npx server; calc.exe", "powershell -NoProfile", "bash -c ls"):
            with self.assertRaises(ValueError):
                mcp_server.validate_external_mcp_client(
                    {"name": "bad-mcp", "command": bad_cmd, "read_only": True},
                    role="scan",
                )


class TestDoctorSlicerUpgradesAndPlayground(unittest.TestCase):
    def test_parse_gh_scopes_flags_delete_repo(self):
        sample = "  - Token scopes: 'delete_repo', 'repo', 'workflow'\n"
        self.assertEqual(doctor.parse_gh_scopes(sample), ["delete_repo", "repo", "workflow"])

    def test_remote_session_guard_enforces_pbkdf2_and_rate_limit(self):
        pw_hash, salt = doctor.RemoteSessionGuard.hash_password("StrongCloudPassphrase#2026")
        guard = doctor.RemoteSessionGuard(pw_hash, salt, max_failures=3, window_sec=300)
        self.assertIsNone(guard.authenticate("192.0.2.10", "wrong-1"))
        self.assertIsNone(guard.authenticate("192.0.2.10", "wrong-2"))
        tok = guard.authenticate("192.0.2.10", "StrongCloudPassphrase#2026")
        self.assertIsNotNone(tok)
        self.assertTrue(guard.verify_session(tok))

        # Trigger lockout on a second IP
        for _ in range(3):
            self.assertIsNone(guard.authenticate("198.51.100.8", "bad"))
        with self.assertRaises(PermissionError):
            guard.authenticate("198.51.100.8", "StrongCloudPassphrase#2026")

    def test_context_slicer_captures_ast_and_far_line_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            big_file = Path(tmp) / "large_module.py"
            body = ["class EngineRunner:\n    def run_slot(self, slot_id: int):\n        pass"]
            body.extend(f"val_{i} = {i}" for i in range(1, 2600))
            big_file.write_text("\n".join(body), encoding="utf-8")

            sliced = context_slicer.slice_file_for_gate(
                big_file,
                "Regression observed at large_module.py:2420",
                radius=15,
                max_chars=25_000,
            )
            self.assertIn("class EngineRunner:", sliced)
            self.assertIn("2420 |", sliced)

    def test_quorum_holds_single_fallback_when_primary_times_out(self):
        outcomes = {"judge_primary": None, "judge_fallback_1": 0.91}
        res = autonomous_upgrades.evaluate_with_quorum(
            ["coder_main", "judge_primary", "judge_fallback_1"],
            "coder_main",
            lambda eng: outcomes[eng],
            require_quorum_on_fallback=True,
        )
        self.assertFalse(res["passed"])
        self.assertTrue(res["awaiting_human"])

    def test_protected_paths_and_safe_revert_plan(self):
        flagged = autonomous_upgrades.touches_protected_path(["docs/README.md", "auto_dev_crew/runner.py"])
        self.assertEqual(flagged, ["auto_dev_crew/runner.py"])

        cfg = {"repos": [{"name": "example-owner/auto-dev-crew"}]}
        plan = autonomous_upgrades.build_safe_revert_plan("example-owner/auto-dev-crew", "2517e71", 81, cfg)
        self.assertEqual(plan["branch"], "self/revert-pr-81")
        with self.assertRaises(ValueError):
            autonomous_upgrades.build_safe_revert_plan("example-owner/auto-dev-crew", "bad;rm -rf", 81, cfg)

    def test_quiet_hours_window_and_disposable_playground(self):
        self.assertTrue(autonomous_upgrades.is_persona_window_open("nightly", dt.datetime(2026, 11, 15, 2, 30)))
        self.assertFalse(autonomous_upgrades.is_persona_window_open("nightly", dt.datetime(2026, 11, 15, 14, 0)))

        with tempfile.TemporaryDirectory() as tmp:
            res = playground.reset_or_create_playground(Path(tmp))
            self.assertTrue(res["ok"])
            self.assertEqual(res["remotes"], [])
            self.assertTrue((Path(res["path"]) / "toy_app" / "paginator.py").exists())

    def test_playground_reset_twice_removes_readonly_git_objects(self):
        # regression: รีเซ็ตซ้ำบน Windows เคยล้มเพราะไฟล์ .git/objects เป็น read-only
        with tempfile.TemporaryDirectory() as tmp:
            first = playground.reset_or_create_playground(Path(tmp))
            obj = Path(first["path"]) / "toy_app" / "paginator.py"
            obj.chmod(stat.S_IREAD)
            second = playground.reset_or_create_playground(Path(tmp))
            self.assertTrue(second["ok"])
            self.assertEqual(second["remotes"], [])

    def test_playground_default_path_resolves_under_data_home(self):
        # regression: default base_dir เคยเรียก data_home.data_root() ที่ไม่มีอยู่จริง
        target = playground.resolve_playground_dir()
        self.assertEqual(target.name, playground.PLAYGROUND_DIR_NAME)
        self.assertEqual(target.parent, playground.DATA_HOME.resolve())


if __name__ == "__main__":
    unittest.main()

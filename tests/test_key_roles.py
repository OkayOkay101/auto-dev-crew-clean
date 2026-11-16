import os
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew.keys import (
    get_key_effective_roles,
    load_key_roles,
    save_key_roles,
    set_key_roles,
)
from auto_dev_crew.runner import (
    get_engine_keys,
    is_engine_ready,
    call_agent,
)
import auto_dev_crew.evaluator as evaluator
from auto_dev_crew import gui


class TestKeyRoles(unittest.TestCase):
    def setUp(self):
        # Reset KEY_ROLES for testing
        save_key_roles({})

    def tearDown(self):
        save_key_roles({})

    def test_naming_convention_roles(self):
        # Default keys without special suffix should be coder
        self.assertEqual(get_key_effective_roles("GEMINI_API_KEY_1"), ["coder"])
        self.assertEqual(get_key_effective_roles("NVIDIA_API_KEY_2"), ["coder"])
        self.assertEqual(get_key_effective_roles("NVIDIA_API_KEY"), ["coder"])

        # Keys with _JUDGE suffix or segment
        self.assertEqual(get_key_effective_roles("GEMINI_API_KEY_JUDGE"), ["judge"])
        self.assertEqual(get_key_effective_roles("NVIDIA_JUDGE_KEY"), ["judge"])
        self.assertEqual(get_key_effective_roles("JUDGE_API_KEY"), ["judge"])

        # Keys with _SCAN suffix or segment
        self.assertEqual(get_key_effective_roles("GROQ_API_KEY_SCAN"), ["scan"])
        self.assertEqual(get_key_effective_roles("SCAN_API_KEY_1"), ["scan"])
        self.assertEqual(get_key_effective_roles("CEREBRAS_SCAN_KEY"), ["scan"])

    def test_state_persistence_override(self):
        # Custom setting should override naming convention
        set_key_roles("GEMINI_API_KEY_1", ["judge", "scan"])
        self.assertEqual(get_key_effective_roles("GEMINI_API_KEY_1"), ["judge", "scan"])

        # Re-save multiple roles
        save_key_roles({
            "KEY_A": ["judge"],
            "KEY_B": ["coder", "scan"],
        })
        roles_map = load_key_roles()
        self.assertEqual(roles_map.get("KEY_A"), ["judge"])
        self.assertEqual(roles_map.get("KEY_B"), ["coder", "scan"])

    def test_get_engine_keys_with_roles_isolation(self):
        env = {
            "CODER_KEY": "val-coder",
            "JUDGE_KEY": "val-judge",
            "SCAN_KEY": "val-scan",
        }
        # Explicitly set roles
        save_key_roles({
            "CODER_KEY": ["coder"],
            "JUDGE_KEY": ["judge"],
            "SCAN_KEY": ["scan"],
        })
        eng = {
            "name": "multi-role-eng",
            "api_keys": ["${CODER_KEY}", "${JUDGE_KEY}", "${SCAN_KEY}"],
        }

        # Role = coder -> should only get CODER_KEY
        coder_keys = get_engine_keys(eng, env_vars=env, role="coder")
        self.assertEqual(coder_keys, ["val-coder"])

        # Role = judge -> should get JUDGE_KEY
        judge_keys = get_engine_keys(eng, env_vars=env, role="judge")
        self.assertEqual(judge_keys, ["val-judge"])

        # Role = scan -> should get SCAN_KEY
        scan_keys = get_engine_keys(eng, env_vars=env, role="scan")
        self.assertEqual(scan_keys, ["val-scan"])

    def test_fallback_to_coder_key_when_role_key_missing(self):
        env = {
            "CODER_KEY": "val-coder",
        }
        save_key_roles({
            "CODER_KEY": ["coder"],
        })
        eng = {
            "name": "coder-only-eng",
            "api_keys": ["${CODER_KEY}"],
        }

        # When judge key is requested but none configured, with fallback enabled -> borrow coder key
        judge_keys = get_engine_keys(eng, env_vars=env, role="judge", allow_fallback=True)
        self.assertEqual(judge_keys, ["val-coder"])

        # When fallback is disabled -> empty
        judge_keys_no_fallback = get_engine_keys(eng, env_vars=env, role="judge", allow_fallback=False)
        self.assertEqual(judge_keys_no_fallback, [])

        # Coder role should NEVER fallback to borrowing judge-only keys
        env_judge_only = {"JUDGE_KEY": "val-judge"}
        save_key_roles({"JUDGE_KEY": ["judge"]})
        eng_judge = {"name": "judge-eng", "api_keys": ["${JUDGE_KEY}"]}
        coder_keys = get_engine_keys(eng_judge, env_vars=env_judge_only, role="coder", allow_fallback=True)
        self.assertEqual(coder_keys, [])

    def test_evaluator_passes_judge_role(self):
        cfg = {
            "evaluation": {
                "enabled": True,
                "engine": "test-eng",
            },
            "engines": [
                {"name": "test-eng", "command": "opencode", "model": "test-model", "enabled": True}
            ]
        }
        with patch("auto_dev_crew.evaluator.runner.call_agent") as mock_call:
            mock_call.return_value = {
                "response": '{"score": 0.9, "passed": true, "reason": "all good"}'
            }
            evaluator.evaluate_diff("diff content", "task description", "all tests passed", cfg, Path("."))
            # Verify role="judge" was passed to call_agent
            _, kwargs = mock_call.call_args
            self.assertEqual(kwargs.get("role"), "judge")

    def test_gui_key_roles_endpoints(self):
        # Test act() with /api/key/roles
        res = gui.act("/api/key/roles", {"key": "CUSTOM_KEY", "roles": ["judge", "scan"]})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("roles"), ["judge", "scan"])
        self.assertEqual(get_key_effective_roles("CUSTOM_KEY"), ["judge", "scan"])

        # Test invalid roles filtered
        res2 = gui.act("/api/key/roles", {"key": "CUSTOM_KEY", "roles": ["invalid_role", "coder"]})
        self.assertTrue(res2.get("ok"))
        self.assertEqual(res2.get("roles"), ["coder"])

    def test_is_engine_ready_with_missing_configured_keys(self):
        eng = {
            "name": "test-missing-key",
            "enabled": True,
            "api_keys": ["${COMPLETELY_UNSET_KEY_XYZ_123}"],
        }
        self.assertFalse(is_engine_ready(eng))

        eng_no_keys = {
            "name": "test-no-key",
            "enabled": True,
        }
        self.assertTrue(is_engine_ready(eng_no_keys))


class TestKeyIdStability(unittest.TestCase):
    def setUp(self):
        save_key_roles({})
        from auto_dev_crew.runner import save_key_status, save_engine_status
        save_key_status({})
        save_engine_status({})

    def tearDown(self):
        save_key_roles({})

    def test_judge_quota_does_not_cool_coder_key(self):
        from auto_dev_crew.runner import QuotaExhausted, get_active_engine_key, get_engine_key_entries, load_key_status

        save_key_roles({"HIGH06_CODER_KEY": ["coder"], "HIGH06_JUDGE_KEY": ["judge"]})
        cfg = {
            "engines": [
                {"name": "high06-eng", "command": "opencode", "model": "m", "enabled": True,
                 "api_keys": ["${HIGH06_CODER_KEY}", "${HIGH06_JUDGE_KEY}"]},
                {"name": "high06-backup", "command": "opencode", "model": "b", "enabled": True},
            ]
        }

        def fake_call(eng, prompt, cwd, active_key=None):
            if eng["name"] == "high06-eng":
                raise QuotaExhausted("429 rate limit on judge key")
            return {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}}

        env = {"HIGH06_CODER_KEY": "val-coder", "HIGH06_JUDGE_KEY": "val-judge"}
        with patch.dict(os.environ, env), \
                patch("auto_dev_crew.runner.call_single_engine", side_effect=fake_call):
            call_agent(cfg, "prompt", Path("."), role="judge")

        st = load_key_status()
        self.assertIn("high06-eng#HIGH06_JUDGE_KEY", st)
        self.assertGreater(st["high06-eng#HIGH06_JUDGE_KEY"]["cooldown_until"], 0)
        self.assertNotIn("high06-eng#HIGH06_CODER_KEY", st)

        # The coder key must still be selectable after the judge key was rate limited
        coder_entries = get_engine_key_entries(cfg["engines"][0], env_vars=env, role="coder")
        key_id, key = get_active_engine_key(coder_entries, st)
        self.assertEqual((key_id, key), ("high06-eng#HIGH06_CODER_KEY", "val-coder"))


if __name__ == "__main__":
    unittest.main()

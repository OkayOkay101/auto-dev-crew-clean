import os
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

import hashlib
import json
import subprocess
import time

from auto_dev_crew.keys import key_id_for
from auto_dev_crew.loop_breaker import AgentSpawnError
from auto_dev_crew.runner import (
    QuotaExhausted,
    call_agent,
    call_single_engine,
    get_active_engine_key,
    get_engine_key_entries,
    get_engine_keys,
    is_engine_ready,
    is_quota_error,
    is_transient,
    load_dotenv,
    mark_key_quota,
    resolve_key_value,
)


class TestKeyPoolResolution(unittest.TestCase):
    def test_load_dotenv_basic(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("# comment line\nKEY1=value1\nKEY2=\"quoted value\"\nKEY3='single quoted'\nEMPTY=\n")
            f_path = Path(f.name)
        try:
            env = load_dotenv(f_path)
            self.assertEqual(env.get("KEY1"), "value1")
            self.assertEqual(env.get("KEY2"), "quoted value")
            self.assertEqual(env.get("KEY3"), "single quoted")
            self.assertEqual(env.get("EMPTY"), "")
        finally:
            f_path.unlink(missing_ok=True)

    def test_resolve_key_value(self):
        env = {"MY_SECRET": "secret123", "ANOTHER": "val456"}
        self.assertEqual(resolve_key_value("${MY_SECRET}", env), "secret123")
        self.assertEqual(resolve_key_value("$ANOTHER", env), "val456")
        self.assertEqual(resolve_key_value("literal_key", env), "literal_key")
        self.assertEqual(resolve_key_value("${UNSET_KEY}", env), "")

    def test_get_engine_keys(self):
        env = {"K1": "val1", "K2": "val2"}
        eng = {"name": "test", "api_keys": ["${K1}", "${K2}", "literal", ""]}
        keys = get_engine_keys(eng, env)
        self.assertEqual(keys, ["val1", "val2", "literal"])

        # Single key fallback
        eng_single = {"name": "test-single", "api_key": "${K1}"}
        keys_single = get_engine_keys(eng_single, env)
        self.assertEqual(keys_single, ["val1"])


class TestKeyStatusCooldown(unittest.TestCase):
    def setUp(self):
        from auto_dev_crew.runner import save_key_status, save_engine_status
        save_key_status({})
        save_engine_status({})

    def test_key_cooldown_and_selection(self):
        eng_name = "test-cooldown-engine"
        entries = [(key_id_for(eng_name, value=v), v) for v in ("k-0", "k-1", "k-2")]
        ids = [kid for kid, _ in entries]
        # Initially k-0
        key_id, key = get_active_engine_key(entries)
        self.assertEqual(key_id, ids[0])
        self.assertEqual(key, "k-0")

        # Mark k-0
        mark_key_quota(ids[0], cooldown_hours=1.0, error="rate limit 429")
        key_id, key = get_active_engine_key(entries)
        self.assertEqual(key_id, ids[1])
        self.assertEqual(key, "k-1")

        # Mark k-1 and k-2
        mark_key_quota(ids[1], cooldown_hours=1.0)
        mark_key_quota(ids[2], cooldown_hours=1.0)
        key_id, key = get_active_engine_key(entries)
        self.assertIsNone(key_id)
        self.assertIsNone(key)

    def test_is_engine_ready_with_keys(self):
        eng = {
            "name": "test-ready-engine",
            "enabled": True,
            "api_keys": ["key1", "key2"]
        }
        self.assertTrue(is_engine_ready(eng))

        # Cooldown key 0
        mark_key_quota(key_id_for("test-ready-engine", value="key1"), cooldown_hours=1.0)
        self.assertTrue(is_engine_ready(eng))

        # Cooldown key 1 -> now engine is not ready
        mark_key_quota(key_id_for("test-ready-engine", value="key2"), cooldown_hours=1.0)
        self.assertFalse(is_engine_ready(eng))


class TestStableKeyIds(unittest.TestCase):
    def setUp(self):
        from auto_dev_crew.runner import save_key_status, save_engine_status
        save_key_status({})
        save_engine_status({})

    def test_key_id_uses_env_var_name_or_value_hash(self):
        self.assertEqual(key_id_for("eng", "NVIDIA_API_KEY_1"), "eng#NVIDIA_API_KEY_1")
        digest = hashlib.sha256(b"literal-secret").hexdigest()[:12]
        kid = key_id_for("eng", value="literal-secret")
        self.assertEqual(kid, f"eng#sha256:{digest}")
        self.assertNotIn("literal-secret", kid)

    def test_entries_carry_env_var_based_ids(self):
        env = {"STABLE_A": "va", "STABLE_B": "vb"}
        eng = {"name": "stable-eng", "api_keys": ["${STABLE_A}", "$STABLE_B"]}
        entries = get_engine_key_entries(eng, env_vars=env)
        self.assertEqual(entries, [("stable-eng#STABLE_A", "va"), ("stable-eng#STABLE_B", "vb")])

    def test_usage_summary_counts_ready_keys_by_stable_id(self):
        from unittest.mock import patch
        from auto_dev_crew import gui
        from auto_dev_crew.runner import save_key_status
        cfg = {"engines": [{"name": "stable-gui", "command": "opencode", "model": "m", "enabled": True,
                            "api_keys": ["${STABLE_GUI_1}", "${STABLE_GUI_2}"]}]}
        with patch.dict(os.environ, {"STABLE_GUI_1": "g1", "STABLE_GUI_2": "g2"}):
            save_key_status({"stable-gui#STABLE_GUI_2": {"cooldown_until": time.time() + 3600}})
            eng = gui.usage_summary(cfg=cfg)["engines"][0]
        self.assertEqual(eng["key_count"], 2)
        self.assertEqual(eng["ready_key_count"], 1)


class TestQuotaDetection(unittest.TestCase):
    def test_success_output_mentioning_quota_words_is_not_quota(self):
        data = {"status": "SUCCESS", "response": "Handled the 429 retry path and the subscription tier check"}
        self.assertFalse(is_quota_error(data))

    def test_error_output_with_quota_signal_is_quota(self):
        self.assertTrue(is_quota_error({"status": "ERROR", "response": "Error: 429 Too Many Requests"}))
        self.assertTrue(is_quota_error({"status": "ERROR", "response": "RESOURCE_EXHAUSTED: quota exceeded"}))
        self.assertTrue(is_quota_error({"status": "ERROR", "response": "You have exhausted your monthly allowance"}))

    def test_error_output_without_quota_signal_is_not_quota(self):
        self.assertFalse(is_quota_error({"status": "ERROR", "response": "agent timed out after 30s"}))
        self.assertFalse(is_quota_error({"status": "ERROR", "response": "Failed to spawn opencode: WinError 206"}))

    def test_numbers_must_match_as_whole_words(self):
        self.assertFalse(is_quota_error({"status": "ERROR", "response": "SyntaxError at line 1429"}))
        self.assertFalse(is_quota_error({"status": "ERROR", "response": "port 4290 refused"}))

    def test_eof_matches_only_as_a_word(self):
        self.assertFalse(is_transient("EOFError: pickle data was truncated"))
        self.assertTrue(is_transient("ssl: unexpected EOF while reading"))

    @patch("auto_dev_crew.runner.engine_cmd", return_value=["fake-agent"])
    @patch("auto_dev_crew.runner.run")
    def test_successful_non_opencode_call_mentioning_429_does_not_raise(self, mock_run, _cmd):
        mock_run.return_value = subprocess.CompletedProcess(
            [], 0, json.dumps({"status": "SUCCESS", "response": "fixed 429 handling"}), "")
        data = call_single_engine({"name": "x", "command": "agy", "model": "m"}, "prompt", Path("."))
        self.assertEqual(data["status"], "SUCCESS")


class TestAgentFailover(unittest.TestCase):
    def setUp(self):
        from auto_dev_crew.runner import save_key_status, save_engine_status
        save_key_status({})
        save_engine_status({})

    @staticmethod
    def _cfg():
        return {"engines": [
            {"name": "first-eng", "command": "opencode", "model": "m", "enabled": True},
            {"name": "second-eng", "command": "opencode", "model": "m2", "enabled": True},
        ]}

    @patch("auto_dev_crew.runner.call_single_engine")
    def test_spawn_failure_fails_over_to_next_engine(self, mock_call):
        mock_call.side_effect = [
            AgentSpawnError("Failed to spawn opencode: WinError 206"),
            {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}},
        ]
        res = call_agent(self._cfg(), "prompt", Path("."))
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["engine_used"], "second-eng")
        self.assertEqual(mock_call.call_count, 2)

    @patch("auto_dev_crew.runner.call_single_engine")
    def test_error_result_fails_over_to_next_engine(self, mock_call):
        mock_call.side_effect = [
            {"status": "ERROR", "response": "boom"},
            {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}},
        ]
        res = call_agent(self._cfg(), "prompt", Path("."))
        self.assertEqual(res["engine_used"], "second-eng")
        self.assertEqual(mock_call.call_count, 2)

    @patch("auto_dev_crew.runner.call_single_engine")
    def test_spawn_failure_on_keyed_engine_fails_over(self, mock_call):
        cfg = {"engines": [
            {"name": "keyed-eng", "command": "opencode", "model": "m", "enabled": True, "api_keys": ["k1", "k2"]},
            {"name": "plain-eng", "command": "opencode", "model": "m2", "enabled": True},
        ]}
        mock_call.side_effect = [
            AgentSpawnError("WinError 206"),
            {"status": "SUCCESS", "response": "ok", "usage": {"total_tokens": 1}},
        ]
        res = call_agent(cfg, "prompt", Path("."))
        self.assertEqual(res["engine_used"], "plain-eng")
        self.assertEqual(mock_call.call_args_list[0].kwargs.get("active_key"), "k1")

    @patch("auto_dev_crew.runner.call_single_engine")
    def test_all_engines_failing_without_quota_raises_runtime_error(self, mock_call):
        mock_call.side_effect = [
            AgentSpawnError("WinError 206"),
            {"status": "ERROR", "response": "boom"},
        ]
        with self.assertRaises(RuntimeError) as ctx:
            call_agent(self._cfg(), "prompt", Path("."))
        self.assertNotIsInstance(ctx.exception, QuotaExhausted)


class TestGranularFailover(unittest.TestCase):
    def setUp(self):
        from auto_dev_crew.runner import save_key_status, save_engine_status
        save_key_status({})
        save_engine_status({})

    @patch("auto_dev_crew.runner.call_single_engine")
    def test_call_agent_rotates_keys_before_engine_failover(self, mock_call):
        cfg = {
            "engines": [
                {
                    "name": "multi-key-eng",
                    "command": "opencode",
                    "model": "test-model",
                    "enabled": True,
                    "api_keys": ["k1", "k2"]
                },
                {
                    "name": "backup-eng",
                    "command": "opencode",
                    "model": "backup-model",
                    "enabled": True
                }
            ]
        }
        # First call on k1 raises QuotaExhausted, second call on k2 succeeds
        mock_call.side_effect = [
            QuotaExhausted("429 rate limit on k1"),
            {"status": "SUCCESS", "response": "ok from k2", "usage": {"total_tokens": 100}}
        ]
        res = call_agent(cfg, "prompt", Path("."))
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(mock_call.call_count, 2)
        self.assertEqual(mock_call.call_args_list[0].kwargs.get("active_key"), "k1")
        self.assertEqual(mock_call.call_args_list[1].kwargs.get("active_key"), "k2")


class TestGuiKeyStatus(unittest.TestCase):
    def test_gui_reports_engine_keys(self):
        from auto_dev_crew import gui
        cfg = {
            "engines": [
                {
                    "name": "test-gui-eng",
                    "command": "opencode",
                    "model": "m",
                    "enabled": True,
                    "api_keys": ["k1", "k2", "k3"]
                }
            ]
        }
        status_data = gui.usage_summary(cfg=cfg)
        engines = status_data["engines"]
        self.assertEqual(len(engines), 1)
        self.assertEqual(engines[0]["key_count"], 3)
        self.assertIn("ready_key_count", engines[0])
        self.assertEqual(engines[0]["ready_key_count"], 3)
        self.assertEqual(engines[0]["keys_status"], "3/3 keys ready")


if __name__ == "__main__":
    unittest.main()

import subprocess
import unittest
from unittest.mock import patch

from auto_dev_crew import key_ping
from auto_dev_crew.runner import select_slot_ids

SECRET = "sk-or-v1-" + "a" * 40


def _eng(keys=None, command="opencode", name="opencode-nvidia"):
    return {
        "name": name,
        "provider": "NVIDIA build",
        "command": command,
        "model": "nvidia/nvidia/nemotron-3-ultra-550b-a55b",
        "api_keys": keys if keys is not None else ["${NVIDIA_API_KEY_1}", "${NVIDIA_API_KEY_2}"],
    }


class TestListKeySpecs(unittest.TestCase):
    def setUp(self):
        # ทดสอบต้องไม่ขึ้นกับ ~/.local/share/opencode/auth.json จริงของเครื่อง
        patcher = patch.object(key_ping, "get_opencode_auth_keys", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_keys_with_values_are_listed(self):
        env = {"NVIDIA_API_KEY_1": SECRET}
        specs = key_ping.list_engine_key_specs(_eng(), env_vars=env)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["var_name"], "NVIDIA_API_KEY_1")
        self.assertEqual(specs[0]["value"], SECRET)
        self.assertTrue(specs[0]["key_id"])

    def test_no_keys_configured_returns_empty(self):
        self.assertEqual(key_ping.list_engine_key_specs(_eng(keys=[]), env_vars={}), [])


class TestOpencodeAuthKeys(unittest.TestCase):
    """คีย์ที่อยู่ใน auth store ของ opencode (ไม่อยู่ใน env) ต้องปิงได้ โดยไม่เปิดเผยค่าคีย์."""

    def test_auth_store_key_is_listed_without_value(self):
        with patch.object(key_ping, "get_opencode_auth_keys", return_value={"nvidia": SECRET}):
            specs = key_ping.list_engine_key_specs(_eng(keys=["${NVIDIA_API_KEY_1}"]), env_vars={})
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["var_name"], "NVIDIA_API_KEY_1")
        self.assertEqual(specs[0]["key_id"], "opencode-nvidia#NVIDIA_API_KEY_1")
        self.assertEqual(specs[0]["source"], "opencode_auth")
        self.assertNotIn(SECRET, repr(specs))

    def test_env_key_wins_over_auth_store(self):
        with patch.object(key_ping, "get_opencode_auth_keys", return_value={"nvidia": "other"}):
            specs = key_ping.list_engine_key_specs(
                _eng(keys=["${NVIDIA_API_KEY_1}"]), env_vars={"NVIDIA_API_KEY_1": SECRET})
        self.assertEqual(specs[0]["value"], SECRET)
        self.assertEqual(specs[0]["source"], "env")

    def test_no_auth_entry_and_no_env_is_empty(self):
        with patch.object(key_ping, "get_opencode_auth_keys", return_value={}):
            self.assertEqual(key_ping.list_engine_key_specs(_eng(keys=["${NVIDIA_API_KEY_1}"]), env_vars={}), [])

    def test_ping_auth_key_runs_opencode_without_injecting_key(self):
        spec = {"key_id": "kid1", "var_name": "NVIDIA_API_KEY_1", "value": "", "source": "opencode_auth"}
        proc = subprocess.CompletedProcess([], 0, stdout="OK\n", stderr="")
        with patch.object(key_ping, "resolve_cli_exe", return_value="opencode"), \
                patch.object(key_ping.subprocess, "run", return_value=proc) as run:
            res = key_ping.ping_key(_eng(), spec)
        self.assertTrue(res["ok"])
        env = run.call_args.kwargs["env"]
        self.assertNotIn("NVIDIA_API_KEY", env)
        self.assertNotIn("NVIDIA_API_KEY_1", env)
        self.assertIn("opencode", res["message"])
        # opencode ค้างรอ stdin ถ้า stdin เป็น pipe ที่เปิดอยู่ → ต้องปิดด้วย DEVNULL
        self.assertIs(run.call_args.kwargs["stdin"], subprocess.DEVNULL)


class TestPingKey(unittest.TestCase):
    def _spec(self):
        return {"key_id": "kid1", "var_name": "NVIDIA_API_KEY_1", "value": SECRET}

    def test_ok_when_opencode_returns_output(self):
        proc = subprocess.CompletedProcess([], 0, stdout="OK\n", stderr="")
        with patch.object(key_ping, "resolve_cli_exe", return_value="opencode"), \
                patch.object(key_ping.subprocess, "run", return_value=proc) as run:
            res = key_ping.ping_key(_eng(), self._spec())
        self.assertTrue(res["ok"])
        self.assertEqual(res["key_id"], "kid1")
        self.assertNotIn(SECRET, res["message"])
        # คีย์ต้องถูกส่งผ่าน env ไม่ใช่ใน argv
        args, kwargs = run.call_args
        self.assertNotIn(SECRET, " ".join(args[0]))
        self.assertEqual(kwargs["env"]["NVIDIA_API_KEY"], SECRET)

    def test_unauthorized_output_is_failure_and_redacted(self):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr=f"401 Unauthorized key={SECRET}")
        with patch.object(key_ping, "resolve_cli_exe", return_value="opencode"), \
                patch.object(key_ping.subprocess, "run", return_value=proc):
            res = key_ping.ping_key(_eng(), self._spec())
        self.assertFalse(res["ok"])
        self.assertNotIn(SECRET, res["message"])

    def test_timeout_is_reported(self):
        with patch.object(key_ping, "resolve_cli_exe", return_value="opencode"), \
                patch.object(key_ping.subprocess, "run", side_effect=subprocess.TimeoutExpired("opencode", 5)):
            res = key_ping.ping_key(_eng(), self._spec(), timeout=5)
        self.assertFalse(res["ok"])
        self.assertIn("หมดเวลา", res["message"])

    def test_non_opencode_engine_is_not_pinged(self):
        res = key_ping.ping_key(_eng(command="agy"), self._spec())
        self.assertFalse(res["ok"])
        self.assertIn("opencode", res["message"])


class TestPingEngineKeys(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(key_ping, "get_opencode_auth_keys", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_key_id_pings_single_key(self):
        env = {"NVIDIA_API_KEY_1": SECRET, "NVIDIA_API_KEY_2": SECRET + "b"}
        specs = key_ping.list_engine_key_specs(_eng(), env_vars=env)
        target = specs[1]["key_id"]
        with patch.object(key_ping, "ping_key", side_effect=lambda eng, s, timeout: {"key_id": s["key_id"], "ok": True}) as p:
            results = key_ping.ping_engine_keys(_eng(), only_key_id=target, env_vars=env)
        self.assertEqual([r["key_id"] for r in results], [target])
        self.assertEqual(p.call_count, 1)

    def test_all_keys_pinged_when_no_key_id(self):
        env = {"NVIDIA_API_KEY_1": SECRET, "NVIDIA_API_KEY_2": SECRET + "b"}
        with patch.object(key_ping, "ping_key", side_effect=lambda eng, s, timeout: {"key_id": s["key_id"], "ok": True}):
            results = key_ping.ping_engine_keys(_eng(), env_vars=env)
        self.assertEqual(len(results), 2)


class TestSelectSlotIds(unittest.TestCase):
    def test_default_runs_all_slots(self):
        self.assertEqual(select_slot_ids({"slots": 3, "enabled": True}), [1, 2, 3])

    def test_active_slot_runs_only_that_slot(self):
        self.assertEqual(select_slot_ids({"slots": 3, "active_slot": 2}), [2])

    def test_null_active_slot_runs_all(self):
        self.assertEqual(select_slot_ids({"slots": 3, "active_slot": None}), [1, 2, 3])

    def test_out_of_range_active_slot_falls_back_to_all(self):
        self.assertEqual(select_slot_ids({"slots": 2, "active_slot": 3}), [1, 2])

    def test_disabled_parallel_still_single_slot(self):
        self.assertEqual(select_slot_ids({"slots": 3, "enabled": False, "active_slot": 1}), [1])


if __name__ == "__main__":
    unittest.main()


class TestRepoOpencodeConfig(unittest.TestCase):
    """ping ต้องโหลด opencode.json ของ repo (provider pollinations อยู่ที่นั่น)."""

    def test_key_env_points_opencode_at_repo_config(self):
        eng = {"name": "opencode-pollinations", "provider": "Pollinations.ai", "command": "opencode"}
        env = key_ping._key_env(eng, "POLLINATIONS_API_KEY_1", "sk_test_value")
        self.assertTrue(key_ping.REPO_OPENCODE_CONFIG.exists())
        self.assertEqual(env["OPENCODE_CONFIG"], str(key_ping.REPO_OPENCODE_CONFIG))

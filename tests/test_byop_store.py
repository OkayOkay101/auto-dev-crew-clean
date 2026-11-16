"""BYOP multi-key pool, key scan, and role-tagged model list (byop_store).

ทุกเทสต์ใช้ไฟล์ .env และ state ชั่วคราว ไม่แตะไฟล์จริงของโปรเจกต์ และไม่เรียกเครือข่ายจริง.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import byop, byop_store, providers

KEY1 = "sk_first_key_aaaa1111"
KEY2 = "sk_second_key_bbbb2222"
KEY3 = "sk_third_key_cccc3333"
MODEL_LUNA = "pollinations/openai/gpt-6-luna"
MODEL_SEARCH = "pollinations/perplexity-fast"


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.env = self.root / ".env"
        self.env.write_text("POLLINATIONS_APP_KEY=pk_test_app\n", encoding="utf-8")
        self.state = self.root / "byop_store.json"
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_2", "POLLINATIONS_API_KEY_3"):
            os.environ.pop(var, None)

    def tearDown(self):
        self._tmp.cleanup()

    def add_env_keys(self, *tokens):
        lines = [f"POLLINATIONS_API_KEY_{i}={tok}" for i, tok in enumerate(tokens, start=1)]
        self.env.write_text("POLLINATIONS_APP_KEY=pk_test_app\n" + "\n".join(lines) + "\n", encoding="utf-8")


class AddKeyTests(_Workspace):
    def test_add_key_appends_next_index_and_keeps_existing_keys(self):
        self.add_env_keys(KEY1, KEY2)
        var = byop_store.add_key(KEY3, env_path=self.env)
        self.assertEqual(var, "POLLINATIONS_API_KEY_3")
        text = self.env.read_text(encoding="utf-8")
        self.assertIn(f"POLLINATIONS_API_KEY_1={KEY1}", text)
        self.assertIn(f"POLLINATIONS_API_KEY_2={KEY2}", text)
        self.assertIn(f"POLLINATIONS_API_KEY_3={KEY3}", text)

    def test_first_key_uses_index_one(self):
        self.assertEqual(byop_store.add_key(KEY1, env_path=self.env), "POLLINATIONS_API_KEY_1")

    def test_rejects_app_key_as_user_key(self):
        with self.assertRaises(byop.ByopError):
            byop_store.add_key("pk_not_a_user_key", env_path=self.env)
        self.assertNotIn("pk_not_a_user_key", self.env.read_text(encoding="utf-8"))


class ListAndSelectTests(_Workspace):
    def test_list_keys_masks_values_and_selects_all_by_default(self):
        self.add_env_keys(KEY1, KEY2)
        rows = byop_store.list_keys(env_path=self.env, state_path=self.state)
        self.assertEqual([r["var"] for r in rows], ["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_2"])
        self.assertTrue(all(r["selected"] for r in rows))
        blob = json.dumps(rows)
        self.assertNotIn(KEY1, blob)
        self.assertNotIn(KEY2, blob)

    def test_set_selected_allows_several_keys_and_drops_the_rest(self):
        self.add_env_keys(KEY1, KEY2, KEY3)
        byop_store.set_selected(["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_3"],
                                env_path=self.env, state_path=self.state)
        self.assertEqual(byop_store.active_keys(env_path=self.env, state_path=self.state),
                         ["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_3"])
        rows = {r["var"]: r["selected"] for r in byop_store.list_keys(env_path=self.env, state_path=self.state)}
        self.assertEqual(rows, {"POLLINATIONS_API_KEY_1": True,
                                "POLLINATIONS_API_KEY_2": False,
                                "POLLINATIONS_API_KEY_3": True})

    def test_set_selected_rejects_key_that_is_not_in_env(self):
        self.add_env_keys(KEY1)
        with self.assertRaises(byop.ByopError):
            byop_store.set_selected(["POLLINATIONS_API_KEY_9"], env_path=self.env, state_path=self.state)


class RemoveKeyTests(_Workspace):
    def test_remove_key_deletes_it_from_env_and_from_selection(self):
        self.add_env_keys(KEY1, KEY2)
        byop_store.set_selected(["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_2"],
                                env_path=self.env, state_path=self.state)
        byop_store.remove_key("POLLINATIONS_API_KEY_1", env_path=self.env, state_path=self.state)
        text = self.env.read_text(encoding="utf-8")
        self.assertNotIn(KEY1, text)
        self.assertIn(KEY2, text)
        self.assertEqual(byop_store.active_keys(env_path=self.env, state_path=self.state),
                         ["POLLINATIONS_API_KEY_2"])


class ScanTests(_Workspace):
    def test_scan_marks_valid_and_rejected_keys_separately(self):
        self.add_env_keys(KEY1, KEY2)
        seen = {}

        def fake_fetch(token):
            seen[token] = True
            return 200 if token == KEY1 else 401

        results = byop_store.scan_keys(env_path=self.env, state_path=self.state, fetch=fake_fetch)
        self.assertEqual(results, [
            {"var": "POLLINATIONS_API_KEY_1", "ok": True, "status": 200, "message": "ใช้งานได้"},
            {"var": "POLLINATIONS_API_KEY_2", "ok": False, "status": 401, "message": "คีย์ถูกปฏิเสธ (401)"},
        ])
        self.assertEqual(set(seen), {KEY1, KEY2})

    def test_scan_network_failure_is_reported_not_raised(self):
        self.add_env_keys(KEY1)

        def broken_fetch(token):
            raise OSError("connection refused")

        results = byop_store.scan_keys(env_path=self.env, state_path=self.state, fetch=broken_fetch)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertIsNone(results[0]["status"])
        self.assertNotIn(KEY1, json.dumps(results))

    def test_scan_result_never_contains_the_token(self):
        self.add_env_keys(KEY1)
        results = byop_store.scan_keys(env_path=self.env, state_path=self.state, fetch=lambda t: 200)
        self.assertNotIn(KEY1, json.dumps(results))


class ModelListTests(_Workspace):
    def test_add_model_stores_id_and_roles(self):
        byop_store.add_model(MODEL_LUNA, ["coder"], state_path=self.state)
        self.assertEqual(byop_store.list_models(state_path=self.state),
                         [{"id": MODEL_LUNA, "roles": ["coder"]}])

    def test_add_model_rejects_non_pollinations_id(self):
        with self.assertRaises(byop.ByopError):
            byop_store.add_model("openai/gpt-4", ["coder"], state_path=self.state)

    def test_add_model_rejects_unknown_role(self):
        with self.assertRaises(byop.ByopError):
            byop_store.add_model(MODEL_LUNA, ["boss"], state_path=self.state)

    def test_adding_same_model_again_merges_roles(self):
        byop_store.add_model(MODEL_LUNA, ["coder"], state_path=self.state)
        byop_store.add_model(MODEL_LUNA, ["scan"], state_path=self.state)
        self.assertEqual(byop_store.list_models(state_path=self.state),
                         [{"id": MODEL_LUNA, "roles": ["coder", "scan"]}])

    def test_model_for_role_picks_the_model_tagged_with_that_role(self):
        byop_store.add_model(MODEL_LUNA, ["coder"], state_path=self.state)
        byop_store.add_model(MODEL_SEARCH, ["scan"], state_path=self.state)
        self.assertEqual(byop_store.model_for_role("scan", state_path=self.state), MODEL_SEARCH)
        self.assertIsNone(byop_store.model_for_role("judge", state_path=self.state))

    def test_remove_model_drops_it_from_the_list(self):
        byop_store.add_model(MODEL_LUNA, ["coder"], state_path=self.state)
        byop_store.remove_model(MODEL_LUNA, state_path=self.state)
        self.assertEqual(byop_store.list_models(state_path=self.state), [])


class ConnectAddsKeyTests(_Workspace):
    def test_connect_adds_a_second_key_instead_of_replacing_the_first(self):
        import time
        self.add_env_keys(KEY1)
        providers_path = self.root / "providers.json"
        providers.save_providers({byop.PROVIDER_ID: {
            "display_name": byop.PROVIDER_NAME, "base_url": byop.BASE_URL, "model": byop.DEFAULT_MODEL,
        }}, providers_path)
        byop._pending.clear()
        byop._pending["st9"] = ("verifier-9", time.monotonic())
        with mock.patch("auto_dev_crew.byop.exchange_code", return_value=KEY2):
            byop.connect(code="c9", state="st9", redirect_uri="http://localhost/cb",
                         env_path=self.env, cfg_path=self.root / "config.yaml",
                         providers_path=providers_path,
                         opencode_path=self.root / "opencode.json")
        text = self.env.read_text(encoding="utf-8")
        self.assertIn(f"POLLINATIONS_API_KEY_1={KEY1}", text)
        self.assertIn(f"POLLINATIONS_API_KEY_2={KEY2}", text)


if __name__ == "__main__":
    unittest.main()

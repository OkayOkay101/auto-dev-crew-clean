"""ระบบเพิ่มโมเดล BYOP: ตรวจกับแคตตาล็อก, ย้ายบทบาท (บทบาทหนึ่งมีโมเดลเดียว), ตั้งบทบาทจากชิป, ทดสอบโมเดล.

ทุกเทสต์ใช้ไฟล์ชั่วคราว และฉีดฟังก์ชันเครือข่ายเข้าไป จึงไม่แตะ .env / state จริง และไม่เรียก Pollinations.
"""
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from auto_dev_crew import byop_store, gui

LUNA = "pollinations/openai/gpt-6-luna"
SEARCH = "pollinations/perplexity-fast"
SECRET = "sk_secret_value_zzzz9999"


class _Workspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.state = root / "byop_store.json"
        self.env = root / ".env"
        self.env.write_text(f"POLLINATIONS_API_KEY_1={SECRET}\n", encoding="utf-8")

    def roles_of(self):
        return {m["id"]: m["roles"] for m in byop_store.list_models(self.state)}


class CatalogCheckTests(_Workspace):
    def test_unknown_model_is_rejected_and_nothing_is_saved(self):
        with self.assertRaises(byop_store.ByopError):
            byop_store.add_model("pollinations/typo-model", ["coder"], self.state,
                                 known_ids={LUNA})
        self.assertEqual(self.roles_of(), {})

    def test_known_model_is_accepted(self):
        res = byop_store.add_model(LUNA, ["coder"], self.state, known_ids={LUNA})
        self.assertEqual(res["roles"], ["coder"])
        self.assertEqual(res["moved_from"], [])

    def test_without_known_ids_no_catalog_check_is_done(self):
        byop_store.add_model("pollinations/anything", ["scan"], self.state)
        self.assertEqual(self.roles_of(), {"pollinations/anything": ["scan"]})


class RoleExclusivityTests(_Workspace):
    def test_adding_a_taken_role_moves_it_and_drops_empty_model(self):
        byop_store.add_model(LUNA, ["coder"], self.state)
        res = byop_store.add_model(SEARCH, ["coder"], self.state)
        self.assertEqual(res["moved_from"], [LUNA])
        self.assertEqual(self.roles_of(), {SEARCH: ["coder"]})

    def test_moving_one_role_keeps_the_other_roles_of_the_old_model(self):
        byop_store.add_model(LUNA, ["coder", "judge"], self.state)
        res = byop_store.add_model(SEARCH, ["judge"], self.state)
        self.assertEqual(res["moved_from"], [LUNA])
        self.assertEqual(self.roles_of(), {LUNA: ["coder"], SEARCH: ["judge"]})

    def test_each_role_resolves_to_exactly_one_model(self):
        byop_store.add_model(LUNA, ["coder", "scan"], self.state)
        byop_store.add_model(SEARCH, ["scan"], self.state)
        self.assertEqual(byop_store.model_for_role("scan", self.state), SEARCH)
        self.assertEqual(byop_store.model_for_role("coder", self.state), LUNA)

    def test_set_roles_replaces_the_whole_set_and_steals_conflicts(self):
        byop_store.add_model(LUNA, ["coder"], self.state)
        byop_store.add_model(SEARCH, ["judge"], self.state)
        res = byop_store.set_roles(LUNA, ["coder", "judge"], self.state)
        self.assertEqual(res["moved_from"], [SEARCH])
        self.assertEqual(self.roles_of(), {LUNA: ["coder", "judge"]})

    def test_set_roles_empty_removes_the_model(self):
        byop_store.add_model(LUNA, ["coder"], self.state)
        res = byop_store.set_roles(LUNA, [], self.state)
        self.assertEqual(res["roles"], [])
        self.assertEqual(self.roles_of(), {})

    def test_set_roles_rejects_unknown_role(self):
        byop_store.add_model(LUNA, ["coder"], self.state)
        with self.assertRaises(byop_store.ByopError):
            byop_store.set_roles(LUNA, ["boss"], self.state)
        self.assertEqual(self.roles_of(), {LUNA: ["coder"]})


class ActiveKeyTests(_Workspace):
    def test_returns_first_active_key_value(self):
        self.assertEqual(byop_store.active_key_value(self.env, self.state), SECRET)

    def test_returns_none_when_no_key(self):
        self.env.write_text("", encoding="utf-8")
        self.assertIsNone(byop_store.active_key_value(self.env, self.state))


class CheckModelTests(_Workspace):
    def test_200_means_ok(self):
        res = byop_store.check_model(LUNA, self.env, self.state, probe=lambda t, m: 200)
        self.assertTrue(res["ok"])

    def test_403_reports_no_access_without_leaking_the_key(self):
        res = byop_store.check_model(LUNA, self.env, self.state, probe=lambda t, m: 403)
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], 403)
        self.assertNotIn(SECRET, str(res))

    def test_network_failure_is_reported_not_raised(self):
        def boom(token, model):
            raise OSError("offline")
        res = byop_store.check_model(LUNA, self.env, self.state, probe=boom)
        self.assertFalse(res["ok"])
        self.assertIsNone(res["status"])

    def test_probe_receives_the_active_key_and_the_model(self):
        seen = {}

        def spy(token, model):
            seen.update(token=token, model=model)
            return 200
        byop_store.check_model(LUNA, self.env, self.state, probe=spy)
        self.assertEqual(seen, {"token": SECRET, "model": LUNA})

    def test_no_key_raises_a_user_message(self):
        self.env.write_text("", encoding="utf-8")
        with self.assertRaises(byop_store.ByopError):
            byop_store.check_model(LUNA, self.env, self.state, probe=lambda t, m: 200)

    def test_chat_probe_strips_provider_prefix_and_sends_one_token(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            import json as _json
            captured["body"] = _json.loads(req.data.decode("utf-8"))
            captured["url"] = req.full_url
            resp = mock.MagicMock()
            resp.__enter__.return_value.status = 200
            return resp
        with mock.patch.object(byop_store.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(byop_store._chat_probe(SECRET, LUNA), 200)
        self.assertEqual(captured["body"]["model"], "openai/gpt-6-luna")
        self.assertEqual(captured["body"]["max_tokens"], 1)
        self.assertEqual(captured["url"], byop_store.CHAT_URL)

    def test_chat_probe_returns_http_error_code(self):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        with mock.patch.object(byop_store.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(byop_store._chat_probe(SECRET, LUNA), 401)


class RouteTests(_Workspace):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(byop_store, "_state_file", lambda path=None: self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_catalog_route_keeps_only_pollinations_ids(self):
        raw = ["pollinations/openai/gpt-6-luna", "other/thing"]
        with mock.patch.object(gui.keys, "fetch_provider_models", return_value=raw):
            res = gui._api_byop_models_catalog({}, {})
        self.assertEqual(res["models"], ["pollinations/openai/gpt-6-luna"])

    def test_add_route_checks_catalog_before_saving(self):
        with mock.patch.object(gui, "_byop_catalog_ids", return_value={LUNA}):
            with self.assertRaises(byop_store.ByopError):
                gui._api_byop_models_add({"id": "pollinations/nope", "roles": ["coder"]}, {})
            gui._api_byop_models_add({"id": LUNA, "roles": ["coder"]}, {})
        self.assertEqual(self.roles_of(), {LUNA: ["coder"]})

    def test_roles_route_returns_moved_from(self):
        byop_store.add_model(LUNA, ["coder"], self.state)
        byop_store.add_model(SEARCH, ["judge"], self.state)
        res = gui._api_byop_models_roles({"id": LUNA, "roles": ["coder", "judge"]}, {})
        self.assertEqual(res["model"]["moved_from"], [SEARCH])

    def test_test_route_delegates_to_check_model(self):
        with mock.patch.object(byop_store, "check_model", return_value={"id": LUNA, "ok": True}) as chk:
            res = gui._api_byop_models_test({"id": LUNA}, {})
        chk.assert_called_once_with(LUNA)
        self.assertTrue(res["result"]["ok"])

    def test_pool_view_exposes_default_model_from_single_source(self):
        view = gui._byop_pool_view()
        self.assertEqual(view["default_model"], gui.byop.DEFAULT_MODEL)

    def test_new_post_routes_are_registered(self):
        for path in ("/api/byop/models/catalog", "/api/byop/models/roles", "/api/byop/models/test"):
            self.assertIn(path, gui.ROUTES)


if __name__ == "__main__":
    unittest.main()

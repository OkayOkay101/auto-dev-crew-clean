"""GUI routes for the BYOP key pool, scan, and role-tagged models.

เทสต์ชี้ keys.ROOT และ keys.STATE ไปยังโฟลเดอร์ชั่วคราว จึงไม่แตะ .env หรือ state จริงของโปรเจกต์.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_dev_crew import byop_store, gui, keys

TOKEN1 = "sk_first_key_aaaa1111"
TOKEN2 = "sk_second_key_bbbb2222"


class _RouteWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / ".env").write_text(
            f"POLLINATIONS_APP_KEY=pk_test_app\nPOLLINATIONS_API_KEY_1={TOKEN1}\nPOLLINATIONS_API_KEY_2={TOKEN2}\n",
            encoding="utf-8")
        self.env_file = root / ".env"
        for patcher in (mock.patch.object(keys, "ROOT", root),
                        mock.patch.object(keys, "STATE", root / "state"),
                        mock.patch.dict(os.environ, {}, clear=False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()


class PoolViewTests(_RouteWorkspace):
    def test_pool_view_lists_masked_keys_and_roles_but_no_token(self):
        view = gui._byop_pool_view()
        self.assertEqual([k["var"] for k in view["keys"]],
                         ["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_2"])
        self.assertEqual(view["roles"], ["coder", "judge", "scan"])
        self.assertEqual(view["models"], [])
        blob = json.dumps(view)
        self.assertNotIn(TOKEN1, blob)
        self.assertNotIn(TOKEN2, blob)


class SelectAndRemoveRouteTests(_RouteWorkspace):
    def test_select_route_stores_several_keys(self):
        res = gui._api_byop_keys_select({"keys": ["POLLINATIONS_API_KEY_1", "POLLINATIONS_API_KEY_2"]}, {})
        self.assertTrue(res["ok"])
        selected = [k["selected"] for k in gui._byop_pool_view()["keys"]]
        self.assertEqual(selected, [True, True])

    def test_select_route_rejects_unknown_key(self):
        with self.assertRaises(byop_store.ByopError):
            gui._api_byop_keys_select({"keys": ["POLLINATIONS_API_KEY_9"]}, {})

    def test_remove_route_deletes_key_from_env(self):
        gui._api_byop_keys_remove({"key": "POLLINATIONS_API_KEY_1"}, {})
        text = self.env_file.read_text(encoding="utf-8")
        self.assertNotIn(TOKEN1, text)
        self.assertIn(TOKEN2, text)


class ScanRouteTests(_RouteWorkspace):
    def test_scan_route_reports_each_key_status(self):
        with mock.patch("auto_dev_crew.byop_store._fetch_status", side_effect=[200, 401]):
            res = gui._api_byop_keys_scan({}, {})
        self.assertEqual([(r["var"], r["status"]) for r in res["results"]],
                         [("POLLINATIONS_API_KEY_1", 200), ("POLLINATIONS_API_KEY_2", 401)])
        self.assertNotIn(TOKEN1, json.dumps(res))


class ModelRouteTests(_RouteWorkspace):
    def test_add_then_remove_model_through_routes(self):
        catalog = {"pollinations/openai/gpt-6-luna", "pollinations/perplexity-fast"}
        with mock.patch.object(gui, "_byop_catalog_ids", return_value=catalog):
            gui._api_byop_models_add({"id": "pollinations/openai/gpt-6-luna", "roles": ["coder"]}, {})
            gui._api_byop_models_add({"id": "pollinations/perplexity-fast", "roles": ["scan"]}, {})
        self.assertEqual([m["id"] for m in gui._byop_pool_view()["models"]],
                         ["pollinations/openai/gpt-6-luna", "pollinations/perplexity-fast"])
        res = gui._api_byop_models_remove({"id": "pollinations/openai/gpt-6-luna"}, {})
        self.assertTrue(res["removed"])
        self.assertEqual([m["id"] for m in gui._byop_pool_view()["models"]], ["pollinations/perplexity-fast"])


class RouteRegistrationTests(unittest.TestCase):
    def test_post_routes_are_registered(self):
        for path in ("/api/byop/keys/select", "/api/byop/keys/remove", "/api/byop/keys/scan",
                     "/api/byop/models/add", "/api/byop/models/remove"):
            self.assertIn(path, gui.ROUTES)

    def test_pool_get_requires_token(self):
        self.assertIn("/api/byop/pool", gui._GET_TOKEN_PATHS)


if __name__ == "__main__":
    unittest.main()

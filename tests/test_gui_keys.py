import os
import tempfile
import time
import unittest
from pathlib import Path

from auto_dev_crew.keys import (
    delete_dotenv_key,
    get_keys_catalog,
    load_env_file,
    mask_key,
    reset_key_cooldown,
    save_dotenv,
)
from auto_dev_crew.runner import (
    load_key_status,
    save_key_status,
    save_engine_status,
    mark_key_quota,
    mark_engine_quota,
)
from auto_dev_crew import gui


class TestGuiKeysManager(unittest.TestCase):
    def setUp(self):
        save_key_status({})
        save_engine_status({})

    def test_mask_key(self):
        self.assertEqual(mask_key(""), "")
        self.assertEqual(mask_key("nvapi-1234567890abcdef"), "nvapi...cdef")
        self.assertEqual(mask_key("123456"), "12...56")
        self.assertEqual(mask_key("abc"), "***")

    def test_save_dotenv_safe_merge(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("# Existing comment\nEXISTING_KEY=old_val\nNVIDIA_API_KEY_1=original_nvidia\n")
            f_path = Path(f.name)
        try:
            # Masked value should be ignored (not overwrite original)
            save_dotenv({"NVIDIA_API_KEY_1": "nvapi...cdef", "NEW_KEY": "new_secret"}, path=f_path)
            env = load_env_file(f_path)
            self.assertEqual(env.get("NVIDIA_API_KEY_1"), "original_nvidia")
            self.assertEqual(env.get("NEW_KEY"), "new_secret")
            self.assertEqual(env.get("EXISTING_KEY"), "old_val")

            # Real update should work
            save_dotenv({"NVIDIA_API_KEY_1": "nvapi-brand-new"}, path=f_path)
            env = load_env_file(f_path)
            self.assertEqual(env.get("NVIDIA_API_KEY_1"), "nvapi-brand-new")
        finally:
            f_path.unlink(missing_ok=True)

    def test_reset_key_cooldown(self):
        mark_key_quota("opencode-nvidia#NVIDIA_API_KEY_1", cooldown_hours=2.0)
        mark_engine_quota("opencode-nvidia", cooldown_hours=2.0)

        # Before reset, should be in cooldown
        st = load_key_status()
        self.assertIn("opencode-nvidia#NVIDIA_API_KEY_1", st)
        self.assertGreater(st["opencode-nvidia#NVIDIA_API_KEY_1"]["cooldown_until"], time.time())

        # Reset key directly
        ok = reset_key_cooldown(key_id="opencode-nvidia#NVIDIA_API_KEY_1")
        self.assertTrue(ok)
        st = load_key_status()
        self.assertEqual(st["opencode-nvidia#NVIDIA_API_KEY_1"]["cooldown_until"], 0)

        # Reset engine directly
        ok_eng = reset_key_cooldown(engine_name="opencode-nvidia")
        self.assertTrue(ok_eng)
        from auto_dev_crew.runner import load_engine_status
        eng_st = load_engine_status()
        self.assertEqual(eng_st["opencode-nvidia"]["cooldown_until"], 0)

    def test_get_keys_catalog(self):
        cfg = {
            "engines": [
                {
                    "name": "opencode-nvidia",
                    "provider": "NVIDIA Build",
                    "command": "opencode",
                    "model": "nvidia/deepseek-ai/deepseek-v4.1-flash",
                    "trains_on_data": False,
                    "enabled": True,
                    "api_keys": ["${NVIDIA_API_KEY_1}", "${NVIDIA_API_KEY_2}"],
                },
                {
                    "name": "opencode",
                    "provider": "OpenCode",
                    "command": "opencode",
                    "model": "opencode/deepseek-v4.1-flash-free",
                    "trains_on_data": False,
                    "enabled": True,
                }
            ]
        }
        test_env = {"NVIDIA_API_KEY_1": "nvapi-test-secret-12345"}
        res = get_keys_catalog(cfg, env_vars=test_env)
        self.assertIn("providers", res)
        self.assertIn("summary", res)
        self.assertEqual(res["summary"]["total_providers"], 2)
        self.assertEqual(res["summary"]["configured_count"], 1)  # opencode now needs a key (none set), nvidia has key 1

        nvidia_item = next(p for p in res["providers"] if p["name"] == "opencode-nvidia")
        self.assertEqual(nvidia_item["tier"], "core")
        self.assertEqual(nvidia_item["portal_url"], "https://build.nvidia.com")
        self.assertFalse(nvidia_item["trains_on_data"])
        self.assertEqual(len(nvidia_item["keys"]), 2)
        self.assertTrue(nvidia_item["keys"][0]["configured"])
        self.assertEqual(nvidia_item["keys"][0]["masked"], "nvapi...2345")
        self.assertFalse(nvidia_item["keys"][1]["configured"])

    def test_delete_dotenv_key(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("KEEP_KEY=123\nTO_DELETE=456\nOTHER=789\n")
            f_path = Path(f.name)
        try:
            os.environ["TO_DELETE"] = "456"
            deleted = delete_dotenv_key("TO_DELETE", path=f_path)
            self.assertTrue(deleted)
            self.assertNotIn("TO_DELETE", os.environ)
            env = load_env_file(f_path)
            self.assertNotIn("TO_DELETE", env)
            self.assertEqual(env.get("KEEP_KEY"), "123")
            self.assertEqual(env.get("OTHER"), "789")

            # Deleting non-existent key returns False
            self.assertFalse(delete_dotenv_key("NON_EXISTENT", path=f_path))
        finally:
            f_path.unlink(missing_ok=True)

    def test_gui_api_act_keys(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f_path = Path(f.name)
        try:
            # Call act("/api/keys", ...)
            from unittest.mock import patch
            with patch("auto_dev_crew.keys.ROOT", f_path.parent):
                res = gui.act("/api/keys", {"keys": {"TEST_API_KEY": "secret_abc"}})
                self.assertTrue(res.get("ok"))
                self.assertIn("TEST_API_KEY", res.get("updated"))

                # Test delete via act
                res_del = gui.act("/api/key/delete", {"key": "TEST_API_KEY"})
                self.assertTrue(res_del.get("ok"))
                self.assertEqual(res_del.get("deleted"), "TEST_API_KEY")

            # Test reset via act
            res_reset = gui.act("/api/key/reset", {"key_id": "opencode-test#key_0"})
            self.assertTrue(res_reset.get("ok"))
        finally:
            f_path.unlink(missing_ok=True)


class TestDotenvConcurrency(unittest.TestCase):
    def test_concurrent_save_dotenv_keeps_all_keys(self):
        import threading
        names = [f"CONC_TEST_KEY_{i}" for i in range(20)]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env_path = Path(tmp) / ".env"
                env_path.write_text("# comment\nEXISTING=1\n", encoding="utf-8")
                errors = []

                def worker(i):
                    try:
                        save_dotenv({names[i]: f"value_{i}"}, path=env_path)
                    except Exception as exc:  # pragma: no cover - reported below
                        errors.append(exc)

                threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                self.assertEqual(errors, [])
                env = load_env_file(env_path)
                for i, name in enumerate(names):
                    self.assertEqual(env.get(name), f"value_{i}", f"lost update for {name}")
                self.assertEqual(env.get("EXISTING"), "1")
        finally:
            for name in names:
                os.environ.pop(name, None)



def test_save_dotenv_rejects_path_and_newlines(tmp_path):
    """MED-15: reserved env names and values with line breaks must be refused, nothing written."""
    import pytest
    from auto_dev_crew.keys import save_dotenv as _save, delete_dotenv_key as _delete

    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING=1\n", encoding="utf-8")
    path_before = os.environ.get("PATH")

    for bad_name in ("PATH", "PYTHONPATH", "NODE_OPTIONS", "SOMETHING_ELSE"):
        with pytest.raises(ValueError):
            _save({bad_name: "x"}, path=env_path)
    with pytest.raises(ValueError):
        _save({"NVIDIA_API_KEY_1": "abc\nEVIL_LINE=1"}, path=env_path)
    with pytest.raises(ValueError):
        _save({"NVIDIA_API_KEY_1": "abc\rEVIL_LINE=1"}, path=env_path)
    with pytest.raises(ValueError):
        _delete("PATH", path=env_path)

    assert env_path.read_text(encoding="utf-8") == "EXISTING=1\n"
    assert os.environ.get("PATH") == path_before

    # Legitimate names, including role-suffixed variants, still work.
    updated = _save({"GROQ_API_KEY_1": "gsk_ok", "GEMINI_API_KEY_JUDGE": "g_ok", "NVIDIA_JUDGE_KEY": "n_ok"}, path=env_path)
    assert sorted(updated) == ["GEMINI_API_KEY_JUDGE", "GROQ_API_KEY_1", "NVIDIA_JUDGE_KEY"]
    os.environ.pop("GROQ_API_KEY_1", None)
    os.environ.pop("GEMINI_API_KEY_JUDGE", None)
    os.environ.pop("NVIDIA_JUDGE_KEY", None)


class TestToggleEngineExactName(unittest.TestCase):
    def test_toggle_engine_exact_name(self):
        import yaml
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "config.yaml"
            cfg.write_text(
                "engines:\n"
                "  - name: opencode-nim\n"
                "    command: opencode\n"
                "    model: m\n"
                "    enabled: true\n"
                "  - name: opencode-nim-eval\n"
                "    command: opencode\n"
                "    model: m\n"
                "    enabled: true\n"
                "repos:\n"
                "  - name: owner/opencode-nim\n"
                "    enabled: true\n",
                encoding="utf-8",
            )
            with mock.patch.object(gui.runner, "ROOT", root):
                ok = gui.toggle_engine_in_config("opencode-nim", False)
            self.assertTrue(ok)
            raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            engines = {e["name"]: e for e in raw["engines"]}
            self.assertFalse(engines["opencode-nim"]["enabled"])
            self.assertTrue(engines["opencode-nim-eval"]["enabled"])
            self.assertTrue(raw["repos"][0]["enabled"])


if __name__ == "__main__":
    unittest.main()

"""engine_for_role: engine Pollinations ใช้โมเดลที่ผูกกับบทบาทนั้น; engine อื่นไม่เปลี่ยน."""
import unittest
from pathlib import Path
import tempfile
from unittest import mock

from auto_dev_crew import byop_store, keys

LUNA = "pollinations/openai/gpt-6-luna"
SEARCH = "pollinations/perplexity-fast"


def _pollinations_engine() -> dict:
    return {"name": "opencode-pollinations", "command": "opencode", "model": LUNA,
            "provider_id": "pollinations", "enabled": True}


class EngineForRoleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(keys, "STATE", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_scan_role_uses_the_model_mapped_to_scan(self):
        byop_store.add_model(SEARCH, ["scan"])
        eng = byop_store.engine_for_role(_pollinations_engine(), "scan")
        self.assertEqual(eng["model"], SEARCH)

    def test_role_without_a_mapping_keeps_the_engine_model(self):
        byop_store.add_model(SEARCH, ["scan"])
        eng = byop_store.engine_for_role(_pollinations_engine(), "judge")
        self.assertEqual(eng["model"], LUNA)

    def test_original_engine_dict_is_not_mutated(self):
        byop_store.add_model(SEARCH, ["scan"])
        original = _pollinations_engine()
        byop_store.engine_for_role(original, "scan")
        self.assertEqual(original["model"], LUNA)

    def test_no_role_keeps_the_engine_model(self):
        byop_store.add_model(SEARCH, ["scan"])
        eng = byop_store.engine_for_role(_pollinations_engine(), None)
        self.assertEqual(eng["model"], LUNA)

    def test_non_pollinations_engine_ignores_the_mapping(self):
        byop_store.add_model(SEARCH, ["scan"])
        other = {"name": "opencode-groq", "command": "opencode", "model": "groq/llama-3",
                 "provider_id": "groq"}
        eng = byop_store.engine_for_role(other, "scan")
        self.assertEqual(eng["model"], "groq/llama-3")


class RolePassThroughTests(unittest.TestCase):
    """บทบาทต้องไปถึง call_single_engine ทุกบทบาท ไม่ใช่แค่ scan; ไม่งั้นโมเดลที่ผูกไว้จะไม่ถูกใช้."""

    def test_every_role_is_passed_to_the_engine_call(self):
        from auto_dev_crew import runner
        for role in ("coder", "judge", "scan"):
            self.assertEqual(runner._role_kwargs(role), {"role": role})

    def test_no_role_passes_nothing(self):
        from auto_dev_crew import runner
        self.assertEqual(runner._role_kwargs(None), {})


class RunnerUsesRoleModelTests(unittest.TestCase):
    """ทดสอบเส้นทางจริงของ _execute_single_engine: โมเดลที่ไปถึง opencode ต้องเป็นโมเดลของบทบาท."""

    def test_scan_call_sends_the_scan_model_to_opencode(self):
        from auto_dev_crew import runner
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = {}

            def fake_stream(**kwargs):
                captured["model"] = kwargs.get("model")
                return {"response": "ok"}

            with mock.patch.object(keys, "STATE", root / "state"), \
                 mock.patch.object(runner, "ROOT", root), \
                 mock.patch.object(runner, "STATE", root / "state"), \
                 mock.patch.object(runner, "engine_cmd", return_value=["opencode-fake"]), \
                 mock.patch.object(runner, "run_opencode_stream", side_effect=fake_stream):
                byop_store.add_model(SEARCH, ["scan"])
                runner._execute_single_engine(_pollinations_engine(), "ping", root, None, role="scan")
        self.assertEqual(captured["model"], SEARCH)


if __name__ == "__main__":
    unittest.main()

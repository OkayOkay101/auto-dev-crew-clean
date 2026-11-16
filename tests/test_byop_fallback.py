"""fallback หลายโมเดลของบทบาทเดียว (BYOP): ลองโมเดลหลักก่อน ล้มเหลวแล้วสลับไปโมเดลถัดไป และพักแยกต่อโมเดล.

ฉีด call_single_engine ด้วย mock จึงไม่เรียก Pollinations จริง. STATE/ENGINE_STATUS ถูกย้ายไปโฟลเดอร์ชั่วคราวโดย conftest.
"""
from unittest import mock

import pytest

from auto_dev_crew import byop_store, runner

M1 = "pollinations/openai/gpt-6-luna"
M2 = "pollinations/perplexity-fast"
ENGINE = {
    "name": "pollen-test",
    "provider": "pollinations",
    "provider_id": "pollinations",
    "command": "opencode",
    "model": "stale-model",
    "enabled": True,
}


@pytest.fixture
def byop_state(tmp_path, monkeypatch):
    path = tmp_path / "byop_store.json"
    monkeypatch.setattr(byop_store, "_state_file", lambda state_path=None: path)
    return path


def _cfg():
    return {"engines": [dict(ENGINE)]}


# ---------------------------------------------------------------- engines_for_role

def test_multi_model_role_yields_ordered_pinned_copies(byop_state):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    out = byop_store.engines_for_role(ENGINE, "coder", byop_state)
    assert [e["model"] for e in out] == [M1, M2]
    assert [e["byop_model"] for e in out] == [M1, M2]
    assert ENGINE["model"] == "stale-model"  # ไม่แก้ dict เดิม


def test_single_model_role_keeps_the_old_primary_mapping(byop_state):
    byop_store.add_model(M1, ["coder"], byop_state)
    out = byop_store.engines_for_role(ENGINE, "coder", byop_state)
    assert len(out) == 1
    assert out[0]["model"] == M1
    assert "byop_model" not in out[0]


def test_no_role_or_other_provider_returns_engine_unchanged(byop_state):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    assert byop_store.engines_for_role(ENGINE, None, byop_state) == [ENGINE]
    other = {"name": "groq", "provider_id": "groq", "model": "x"}
    assert byop_store.engines_for_role(other, "coder", byop_state) == [other]


def test_opencode_declaration_registers_pollinations_model_only():
    decl = byop_store.opencode_declaration(M2)
    assert decl == {"provider": {"pollinations": {"models": {"perplexity-fast": {"name": "perplexity-fast"}}}}}
    assert byop_store.opencode_declaration("pollinations/openai/gpt-oss-20b")["provider"]["pollinations"]["models"] \
        == {"openai/gpt-oss-20b": {"name": "openai/gpt-oss-20b"}}
    assert byop_store.opencode_declaration("openai/gpt-4") == {}
    assert byop_store.opencode_declaration(None) == {}


def test_declaration_is_sent_to_opencode_and_scan_config_is_kept(byop_state, tmp_path):
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(kwargs["env"].get("OPENCODE_CONFIG_CONTENT"))
        raise OSError("stop after capturing env")

    eng = {**ENGINE, "model": M1, "api_keys": []}
    with mock.patch.object(runner, "resolve_cli_exe", return_value="opencode"), \
            mock.patch.object(runner.subprocess, "Popen", side_effect=fake_run):
        for role in ("coder", "scan"):
            try:
                runner._execute_single_engine(eng, "p", tmp_path, None, role=role)
            except Exception:
                pass
    import json as _json
    coder, scan = (_json.loads(c) for c in captured)
    assert coder["provider"]["pollinations"]["models"] == {"openai/gpt-6-luna": {"name": "openai/gpt-6-luna"}}
    assert "permission" not in coder
    assert "permission" in scan and "provider" in scan


def test_status_name_is_per_model_and_key_name_stays_the_same():
    pinned = {**ENGINE, "byop_model": M1}
    assert runner._status_name(ENGINE) == "pollen-test"
    assert runner._status_name(pinned) == f"pollen-test@{M1}"
    assert runner.key_engine_name(pinned) == "pollen-test"


# ---------------------------------------------------------------- call_agent fallback

def test_quota_on_primary_falls_back_to_second_model(byop_state, tmp_path):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    seen = []

    def fake(eng, prompt, cwd, active_key=None, *, role=None):
        seen.append(eng["model"])
        if eng["model"] == M1:
            raise runner.QuotaExhausted("quota")
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        data = runner.call_agent(_cfg(), "T", tmp_path, role="coder")

    assert seen == [M1, M2]
    assert data["engine_used"] == f"pollen-test@{M2}"
    status = runner.load_engine_status()
    assert f"pollen-test@{M1}" in status
    assert "pollen-test" not in status  # ไม่พักทั้ง engine เพราะยังมีโมเดลสำรอง


def test_error_result_on_primary_also_falls_back(byop_state, tmp_path):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    seen = []

    def fake(eng, prompt, cwd, active_key=None, *, role=None):
        seen.append(eng["model"])
        if eng["model"] == M1:
            return {"status": "ERROR", "response": "model not found"}
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        data = runner.call_agent(_cfg(), "T", tmp_path, role="coder")

    assert seen == [M1, M2]
    assert data["engine_used"] == f"pollen-test@{M2}"


def test_cooled_primary_is_skipped_on_the_next_call(byop_state, tmp_path):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    seen = []

    def fake(eng, prompt, cwd, active_key=None, *, role=None):
        seen.append(eng["model"])
        if eng["model"] == M1:
            raise runner.QuotaExhausted("quota")
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        runner.call_agent(_cfg(), "T", tmp_path, role="coder")
        seen.clear()
        runner.call_agent(_cfg(), "T", tmp_path, role="coder")

    assert seen == [M2]  # รอบที่สองข้าม M1 ที่พักอยู่ ใช้ M2 ทันที


def test_primary_model_is_used_when_healthy(byop_state, tmp_path):
    byop_store.add_model(M1, ["coder"], byop_state)
    byop_store.add_model(M2, ["coder"], byop_state)
    seen = []

    def fake(eng, prompt, cwd, active_key=None, *, role=None):
        seen.append(eng["model"])
        return {"status": "SUCCESS", "response": "ok"}

    with mock.patch.object(runner, "call_single_engine", side_effect=fake):
        data = runner.call_agent(_cfg(), "T", tmp_path, role="coder")

    assert seen == [M1]
    assert data["engine_used"] == f"pollen-test@{M1}"

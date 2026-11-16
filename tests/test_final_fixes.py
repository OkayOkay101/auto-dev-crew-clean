"""Final-review fix wave: I1-I4, M1, M2."""
import json
import os
import subprocess
from unittest import mock

import pytest

from auto_dev_crew import loop_breaker, runner
from auto_dev_crew.redact import PLACEHOLDER, redact_secrets


# ---- I1: main() must not leak the real .env into the test process
def test_main_export_is_neutralised_by_default():
    # conftest replaces export_dotenv_to_environ with a no-op for every test
    assert runner.export_dotenv_to_environ() == 0


# ---- I2: exported .env names are stripped from the test-step env
def test_venv_env_strips_dotenv_exported_names(tmp_path, monkeypatch, real_export):
    monkeypatch.delenv("FAKE_EXPORTED_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("FAKE_EXPORTED_API_KEY=supersecretvalue123\n", encoding="utf-8")
    monkeypatch.setattr(runner, "VENVS", tmp_path / "venvs")
    (tmp_path / "venvs" / "o__r").mkdir(parents=True)
    assert real_export(env_file) == 1
    assert os.environ["FAKE_EXPORTED_API_KEY"] == "supersecretvalue123"
    env = runner.venv_env("o/r")
    assert "FAKE_EXPORTED_API_KEY" not in env
    assert "PATH" in env


# ---- I3: partial handoff uses assistant text only
def _ev(**kw):
    return json.dumps(kw)


def test_parse_opencode_partial_text_excludes_errors():
    out = "\n".join([
        _ev(type="text", part={"type": "text", "text": "wrote foo.py"}),
        _ev(type="error", error={"message": "quota exceeded"}),
    ])
    data = loop_breaker.parse_opencode(out, 1.0)
    assert data["partial_text"] == "wrote foo.py"
    assert "quota" not in data["partial_text"]
    assert "quota" in data["response"]


def _quota_eng(monkeypatch, tmp_path, data):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "engine_cmd", lambda eng: ["opencode", "run"])
    monkeypatch.setattr(runner, "run_opencode_stream", mock.MagicMock(return_value=data))
    return {"name": "oc", "provider": "Groq", "command": "opencode", "model": "m"}


def test_execute_quota_partial_is_text_events_only(monkeypatch, tmp_path):
    eng = _quota_eng(monkeypatch, tmp_path, {
        "status": "ERROR", "response": "429 quota exceeded rate limit",
        "partial_text": "half done work"})
    with pytest.raises(runner.QuotaExhausted) as ctx:
        runner._execute_single_engine(eng, "p", tmp_path)
    assert ctx.value.partial == "half done work"


def test_execute_quota_with_only_error_gives_no_handoff(monkeypatch, tmp_path):
    eng = _quota_eng(monkeypatch, tmp_path, {
        "status": "ERROR", "response": "429 quota exceeded rate limit", "partial_text": ""})
    with pytest.raises(runner.QuotaExhausted) as ctx:
        runner._execute_single_engine(eng, "p", tmp_path)
    assert ctx.value.partial == ""
    assert runner.build_handoff_prompt("ORIG", ctx.value.partial, "oc") == "ORIG"


def test_execute_quota_non_opencode_partial_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "engine_cmd", lambda eng: ["x"])
    monkeypatch.setattr(runner, "run", lambda *a, **k: subprocess.CompletedProcess(
        [], 1, "", "429 quota exceeded rate limit"))
    with pytest.raises(runner.QuotaExhausted) as ctx:
        runner._execute_single_engine({"name": "c", "command": "claude", "model": "m"}, "p", tmp_path)
    assert ctx.value.partial == ""


# ---- I4: redaction
@pytest.mark.parametrize("tok", [
    "csk-" + "a1B2c3D4e5" * 3,
    "sk_" + "a1B2c3D4e5" * 3,
    "hf_" + "a1B2c3D4e5" * 3,
])
def test_more_token_formats_redacted(tok):
    out = redact_secrets(f"leak {tok} end")
    assert tok not in out and PLACEHOLDER in out


def test_env_value_redacted(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "abcdefghijklmnop1234")
    assert "abcdefghijklmnop1234" not in redact_secrets("x abcdefghijklmnop1234 y")


def test_env_short_or_nonsecret_untouched(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "short123")
    monkeypatch.setenv("MY_PATH", "abcdefghijklmnop1234")
    out = redact_secrets("short123 abcdefghijklmnop1234")
    assert out == "short123 abcdefghijklmnop1234"


def test_env_placeholder_ref_untouched(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "${GROQ_API_KEY}")
    assert redact_secrets("use ${GROQ_API_KEY} here") == "use ${GROQ_API_KEY} here"


@pytest.mark.parametrize("form", ["short", "equals"])
def test_gh_short_b_and_equals_body_redacted(monkeypatch, form):
    seen = []
    monkeypatch.setattr(runner, "run", lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))[1])
    key = "ghp_" + "aB3dE5gH7j" * 3 + "xYzAbC"
    args = ("-b", f"x {key}") if form == "short" else (f"--body=x {key}",)
    runner.gh("pr", "create", *args)
    assert key not in " ".join(seen[0]) and PLACEHOLDER in " ".join(seen[0])


# ---- M1
def test_today_usage_skips_malformed_tokens():
    import datetime as dt
    ts = dt.datetime.now().isoformat(timespec="seconds")
    (runner.STATE / "usage.jsonl").write_text("\n".join([
        json.dumps({"engine_name": "g", "ts": ts, "tokens": "abc"}),
        json.dumps({"engine_name": "g", "ts": ts, "tokens": 5}),
    ]) + "\n", encoding="utf-8")
    assert runner.today_usage("g") == (1, 5)


# ---- M2
def test_safe_engine_filename():
    name = runner.safe_engine_filename("a/b:c")
    assert "/" not in name and ":" not in name


def test_raw_log_filename_sanitised_with_pid(monkeypatch, tmp_path):
    mockrun = mock.MagicMock(return_value={"status": "SUCCESS", "response": "ok"})
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "engine_cmd", lambda eng: ["opencode", "run"])
    monkeypatch.setattr(runner, "run_opencode_stream", mockrun)
    runner._execute_single_engine({"name": "a/b:c", "command": "opencode", "model": "m"}, "p", tmp_path)
    name = mockrun.call_args.kwargs["raw_log"].name
    assert "/" not in name and ":" not in name and str(os.getpid()) in name

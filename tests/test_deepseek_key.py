from pathlib import Path
from unittest.mock import MagicMock

from auto_dev_crew import runner


def _patch_opencode(monkeypatch, tmp_path: Path) -> MagicMock:
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "engine_cmd", lambda eng: ["opencode", "run"])
    mock = MagicMock(return_value={"status": "SUCCESS", "response": "ok"})
    monkeypatch.setattr(runner, "run_opencode_stream", mock)
    return mock


def test_deepseek_engine_gets_deepseek_api_key(monkeypatch, tmp_path):
    mock = _patch_opencode(monkeypatch, tmp_path)
    eng = {
        "name": "opencode-deepseek",
        "provider": "DeepSeek",
        "command": "opencode",
        "model": "deepseek/deepseek-flash",
    }

    runner.call_single_engine(eng, "prompt", tmp_path, active_key="sk-test-deepseek")

    env = mock.call_args.kwargs["env"]
    assert env["DEEPSEEK_API_KEY"] == "sk-test-deepseek"


def test_non_deepseek_engine_does_not_get_deepseek_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mock = _patch_opencode(monkeypatch, tmp_path)
    eng = {
        "name": "opencode-groq",
        "provider": "Groq",
        "command": "opencode",
        "model": "groq/llama",
    }

    runner.call_single_engine(eng, "prompt", tmp_path, active_key="gsk-test")

    env = mock.call_args.kwargs["env"]
    assert "DEEPSEEK_API_KEY" not in env
    assert env["GROQ_API_KEY"] == "gsk-test"


def test_opencode_run_gets_raw_log_under_state_runs(monkeypatch, tmp_path):
    mock = _patch_opencode(monkeypatch, tmp_path)
    eng = {"name": "opencode-groq", "provider": "Groq", "command": "opencode", "model": "groq/llama"}

    runner.call_single_engine(eng, "prompt", tmp_path, active_key="gsk-test")

    raw_log = mock.call_args.kwargs["raw_log"]
    assert raw_log.parent == runner.STATE / "runs"
    assert raw_log.name.startswith("opencode-raw-") and raw_log.name.endswith("-opencode-groq.log")

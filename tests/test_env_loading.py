import os
from unittest import mock

import pytest

from auto_dev_crew import runner
from auto_dev_crew.runner import export_dotenv_to_environ

KEYS = ("TEST_CLI_KEY_A", "TEST_CLI_KEY_B", "TEST_CLI_KEY_C")


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / ".env"
    p.write_text("TEST_CLI_KEY_A=alpha-value\nTEST_CLI_KEY_B=beta-value\nTEST_CLI_KEY_C=\n", encoding="utf-8")
    yield p
    for k in KEYS:  # export เขียน os.environ ตรง ๆ ต้องล้างเอง
        os.environ.pop(k, None)


def test_exports_missing_keys_into_environ(env_file):
    assert export_dotenv_to_environ(env_file) == 2
    assert os.environ["TEST_CLI_KEY_A"] == "alpha-value"
    assert os.environ["TEST_CLI_KEY_B"] == "beta-value"


def test_existing_environ_value_wins(env_file, monkeypatch):
    monkeypatch.setenv("TEST_CLI_KEY_A", "already-set")
    export_dotenv_to_environ(env_file)
    assert os.environ["TEST_CLI_KEY_A"] == "already-set"
    assert os.environ["TEST_CLI_KEY_B"] == "beta-value"


def test_empty_value_not_exported(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_CLI_KEY_C", raising=False)
    p = tmp_path / ".env"
    p.write_text("TEST_CLI_KEY_C=\n", encoding="utf-8")
    assert export_dotenv_to_environ(p) == 0
    assert "TEST_CLI_KEY_C" not in os.environ


def test_missing_file_is_noop(tmp_path):
    assert export_dotenv_to_environ(tmp_path / "no-such.env") == 0


def test_main_exports_dotenv_before_loading_config(tmp_path):
    with mock.patch.object(runner, "export_dotenv_to_environ") as m:
        with pytest.raises(FileNotFoundError):
            runner.main(["--config", str(tmp_path / "missing.yaml")])
    m.assert_called_once()

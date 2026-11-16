"""Regression tests for the security hardening pass (bandit + audit follow-ups)."""
from __future__ import annotations

import hashlib
import importlib.util
import urllib.request
from pathlib import Path

import pytest

from auto_dev_crew import gui_check, keys, playwright_env, runner, todo_scan

ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scripts.{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scrub_agent_env_drops_secrets_but_keeps_config_refs(tmp_path: Path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text('{"apiKey": "{env:NVIDIA_API_KEY}"}', encoding="utf-8")
    base = {
        "PATH": "/usr/bin",
        "HOME": "/root",
        "GH_TOKEN": "ghp_secret",
        "DB_PASSWORD": "hunter2",
        "NVIDIA_API_KEY": "nvapi-x",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
    }
    out = runner.scrub_agent_env(base, cfg)
    assert out["PATH"] == "/usr/bin" and out["HOME"] == "/root"
    assert "NVIDIA_API_KEY" in out  # referenced by opencode.json
    assert "GH_TOKEN" not in out
    assert "DB_PASSWORD" not in out
    assert "SSH_AUTH_SOCK" not in out


def test_scrub_agent_env_missing_config_still_scrubs(tmp_path: Path):
    out = runner.scrub_agent_env({"GITHUB_TOKEN": "t", "LANG": "C"}, tmp_path / "missing.json")
    assert out == {"LANG": "C"}


def test_open_https_rejects_non_https():
    req = urllib.request.Request("http://example.com/x")
    with pytest.raises(ValueError):
        keys._open_https(req, timeout=1)


def test_open_https_rejects_file_scheme():
    req = urllib.request.Request("file:///etc/passwd")
    with pytest.raises(ValueError):
        keys._open_https(req, timeout=1)


@pytest.mark.parametrize("bad_url", ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"])
def test_open_http_helpers_reject_non_http_schemes(bad_url: str):
    gui_e2e = _load_script("gui_e2e")
    gui_watchdog = _load_script("gui_watchdog")
    for helper in (playwright_env._open_http, gui_check._open_http, gui_e2e._open_http, gui_watchdog._open_http):
        with pytest.raises(ValueError):
            helper(bad_url, timeout=1)


def test_gui_e2e_rejects_non_http_url():
    gui_e2e = _load_script("gui_e2e")
    req = urllib.request.Request("file:///etc/passwd")
    with pytest.raises(ValueError):
        gui_e2e._open_http(req, timeout=1)
    with pytest.raises(ValueError):
        gui_e2e.agent_running("file:///etc")
    with pytest.raises(ValueError):
        gui_e2e.page_token("file:///etc")
    with pytest.raises(ValueError):
        gui_e2e.stop_agent_via_api("file:///etc")


def test_todo_marker_unchanged_by_usedforsecurity_flag():
    # The marker digest must stay identical so existing issues are still matched.
    text = "TODO: fix"
    expected = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    assert todo_scan._marker("a.py", text) == f"<!-- ai-todo:a.py:{expected} -->"

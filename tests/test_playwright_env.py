"""Playwright opt-in ต่อ repo และการติดตั้งใน venv (ไม่ติดตั้งจริง: subprocess ถูก mock)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from auto_dev_crew import playwright_env, runner


def _logger():
    lines: list[str] = []
    return lines, lines.append


def _fake_venv(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "bin").mkdir(parents=True)
    for py in (venv / "Scripts" / "python.exe", venv / "bin" / "python"):
        py.write_text("", encoding="utf-8")
    return venv


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_is_opted_in_defaults_to_off():
    assert playwright_env.is_opted_in({}) is False
    assert playwright_env.is_opted_in(None) is False
    assert playwright_env.is_opted_in({"playwright": False}) is False
    assert playwright_env.is_opted_in({"playwright": {"enabled": False}}) is False


def test_is_opted_in_accepts_true_and_enabled_dict():
    assert playwright_env.is_opted_in({"playwright": True}) is True
    assert playwright_env.is_opted_in({"playwright": {"enabled": True}}) is True


def test_detect_playwright_needed(tmp_path):
    # 1. Plain repo: no playwright files
    assert playwright_env.detect_playwright_needed(tmp_path) is False

    # 2. Repo with playwright in requirements-dev.txt
    (tmp_path / "requirements-dev.txt").write_text("playwright==1.65.1\n", encoding="utf-8")
    assert playwright_env.detect_playwright_needed(tmp_path) is True

    # 3. Repo with test importing playwright
    ui_repo = tmp_path / "ui_repo"
    (ui_repo / "tests").mkdir(parents=True)
    (ui_repo / "tests" / "test_ui.py").write_text("from playwright.sync_api import sync_playwright\n", encoding="utf-8")
    assert playwright_env.detect_playwright_needed(ui_repo) is True


def test_is_opted_in_requires_explicit_opt_in():
    # Option 2: Must be explicitly enabled by user
    assert playwright_env.is_opted_in({}) is False
    assert playwright_env.is_opted_in(None) is False
    assert playwright_env.is_opted_in({"playwright": False}) is False
    assert playwright_env.is_opted_in({"playwright": True}) is True
    assert playwright_env.is_opted_in({"playwright": {"enabled": True}}) is True


def test_ensure_installs_pip_and_chromium_then_writes_marker(tmp_path):
    venv = _fake_venv(tmp_path)
    lines, log = _logger()
    with mock.patch.object(playwright_env, "_run", return_value=_ok()) as run:
        assert playwright_env.ensure_playwright(venv, log) is True

    cmds = [c.args[0] for c in run.call_args_list]
    assert len(cmds) == 2
    assert cmds[0][1:] == ["-m", "pip", "install", "--disable-pip-version-check", "playwright"]
    assert cmds[1][1:] == ["-m", "playwright", "install", "chromium"]
    assert (venv / playwright_env.MARKER_NAME).exists()
    assert any("ติดตั้ง Playwright" in line and "✅" in line for line in lines)


def test_ensure_skips_when_marker_present(tmp_path):
    venv = _fake_venv(tmp_path)
    (venv / playwright_env.MARKER_NAME).write_text("ok\n", encoding="utf-8")
    lines, log = _logger()
    with mock.patch.object(playwright_env, "_run") as run:
        assert playwright_env.ensure_playwright(venv, log) is True
    run.assert_not_called()
    assert lines == []


def test_ensure_failure_returns_false_logs_and_writes_no_marker(tmp_path):
    venv = _fake_venv(tmp_path)
    lines, log = _logger()
    failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="no network")
    with mock.patch.object(playwright_env, "_run", return_value=failed) as run:
        assert playwright_env.ensure_playwright(venv, log) is False
    assert run.call_count == 1  # หยุดที่ขั้น pip ไม่ไปขั้น chromium
    assert not (venv / playwright_env.MARKER_NAME).exists()
    assert any("ไม่สำเร็จ" in line and "no network" in line for line in lines)


def test_ensure_never_raises_on_exception(tmp_path):
    venv = _fake_venv(tmp_path)
    lines, log = _logger()
    with mock.patch.object(playwright_env, "_run", side_effect=OSError("boom")):
        assert playwright_env.ensure_playwright(venv, log) is False
    assert any("ล้มเหลว" in line for line in lines)


def test_ensure_skips_when_venv_has_no_python(tmp_path):
    lines, log = _logger()
    with mock.patch.object(playwright_env, "_run") as run:
        assert playwright_env.ensure_playwright(tmp_path / "missing", log) is False
    run.assert_not_called()
    assert any("ข้าม" in line for line in lines)


def test_prepare_workspace_installs_only_for_opted_in_repo(tmp_path):
    rcfg_off = {"name": "o/plain", "setup": [], "test": []}
    rcfg_on = {"name": "o/ui", "setup": [], "test": [], "playwright": True}
    with mock.patch.object(runner, "venv_env", return_value={}), \
         mock.patch.object(runner, "run_steps", return_value=(True, "")), \
         mock.patch.object(runner.playwright_env, "ensure_playwright", return_value=True) as ensure:
        runner._prepare_workspace(tmp_path, "o/plain", rcfg_off, None)
        ensure.assert_not_called()

        runner._prepare_workspace(tmp_path, "o/ui", rcfg_on, 2)
        ensure.assert_called_once()
        assert ensure.call_args.args[0] == runner.venv_path("o/ui", 2)


def test_prepare_workspace_survives_playwright_install_failure(tmp_path):
    rcfg_on = {"name": "o/ui", "setup": [], "test": [], "playwright": {"enabled": True}}
    with mock.patch.object(runner, "venv_env", return_value={}), \
         mock.patch.object(runner, "run_steps", return_value=(True, "")), \
         mock.patch.object(runner.playwright_env, "_run", side_effect=OSError("no pip")):
        env, test_steps = runner._prepare_workspace(tmp_path, "o/ui", rcfg_on, None)
    assert env == {}
    assert test_steps == []


def test_venv_path_matches_venv_env_location():
    assert runner.venv_path("o/r", 3).name == "o__r_slot_3"
    assert runner.venv_path("o/r").name == "o__r"


# ---- ขั้นตรวจ Playwright หลังเทสต์ (post_test_gui_check)

def test_post_test_check_off_when_not_opted_in(tmp_path):
    lines, log = _logger()
    with mock.patch.object(playwright_env, "_url_up") as up, \
         mock.patch("auto_dev_crew.gui_check.check_page") as page:
        assert playwright_env.post_test_gui_check({"playwright": False, "playwright_url": "x"}, "o/r", log, tmp_path) is None
        assert playwright_env.post_test_gui_check({}, "o/r", log, tmp_path) is None
    up.assert_not_called()
    page.assert_not_called()
    assert lines == []


def test_post_test_check_skips_when_opted_in_without_gui(tmp_path):
    lines, log = _logger()
    with mock.patch("auto_dev_crew.gui_check.check_page") as page:
        assert playwright_env.post_test_gui_check({"playwright": True}, "o/data", log, tmp_path) is None
    page.assert_not_called()
    assert any("ข้าม" in line and "ไม่มี GUI" in line for line in lines)


def test_post_test_check_skips_when_server_not_running(tmp_path):
    lines, log = _logger()
    rcfg = {"playwright": {"enabled": True, "url": "http://127.0.0.1:5999"}}
    with mock.patch.object(playwright_env, "_url_up", return_value=False), \
         mock.patch("auto_dev_crew.gui_check.check_page") as page:
        assert playwright_env.post_test_gui_check(rcfg, "o/ui", log, tmp_path) is None
    page.assert_not_called()
    assert any("ข้าม" in line and "5999" in line for line in lines)


def test_post_test_check_passes_and_logs(tmp_path):
    lines, log = _logger()
    rcfg = {"playwright": {"enabled": True, "url": "http://127.0.0.1:5999"}}
    with mock.patch.object(playwright_env, "_url_up", return_value=True), \
         mock.patch("auto_dev_crew.gui_check.check_page", return_value=[]) as page:
        assert playwright_env.post_test_gui_check(rcfg, "o/ui", log, tmp_path) is True
    page.assert_called_once()
    assert any("ผ่าน" in line for line in lines)


def test_post_test_check_reports_problems_without_raising(tmp_path):
    lines, log = _logger()
    rcfg = {"playwright": {"enabled": True, "url": "http://127.0.0.1:5999"}}
    with mock.patch.object(playwright_env, "_url_up", return_value=True), \
         mock.patch("auto_dev_crew.gui_check.check_page", return_value=["uncaught JS error: boom"]):
        assert playwright_env.post_test_gui_check(rcfg, "o/ui", log, tmp_path) is False
    assert any("ไม่ผ่าน" in line and "boom" in line for line in lines)


def test_post_test_check_survives_playwright_exception(tmp_path):
    lines, log = _logger()
    rcfg = {"playwright": {"enabled": True, "url": "http://127.0.0.1:5999"}}
    with mock.patch.object(playwright_env, "_url_up", return_value=True), \
         mock.patch("auto_dev_crew.gui_check.check_page", side_effect=RuntimeError("no browser")):
        assert playwright_env.post_test_gui_check(rcfg, "o/ui", log, tmp_path) is False
    assert any("ล้มเหลว" in line for line in lines)

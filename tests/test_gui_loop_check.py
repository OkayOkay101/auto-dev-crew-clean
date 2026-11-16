"""ลูปหลักตรวจ GUI ด้วย Playwright: เปิด GUI เองถ้ายังไม่เปิด, ลงผลใน log, ไม่หยุดลูป."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from auto_dev_crew import gui, gui_check, runner


def _logger():
    lines: list[str] = []
    return lines, lines.append


def _fake_proc(poll=None):
    proc = mock.MagicMock()
    proc.poll.return_value = poll
    return proc


def test_run_gui_check_uses_running_gui_and_passes(tmp_path):
    lines, log = _logger()
    with mock.patch.object(gui_check, "gui_is_up", return_value=True), \
         mock.patch.object(gui_check, "start_gui") as start, \
         mock.patch.object(gui_check, "check_api", return_value=[]), \
         mock.patch.object(gui_check, "check_page", return_value=[]) as page:
        assert gui_check.run_gui_check(log, shot=tmp_path / "s.png") is True

    start.assert_not_called()
    page.assert_called_once()
    assert any("เปิดอยู่แล้ว" in line for line in lines)
    assert any("ผ่าน" in line for line in lines)


def test_run_gui_check_starts_gui_when_down_and_stops_it_after(tmp_path):
    lines, log = _logger()
    proc = _fake_proc(poll=None)
    with mock.patch.object(gui_check, "gui_is_up", return_value=False), \
         mock.patch.object(gui_check, "start_gui", return_value=proc) as start, \
         mock.patch.object(gui_check, "wait_gui_up", return_value=True), \
         mock.patch.object(gui_check, "check_api", return_value=[]), \
         mock.patch.object(gui_check, "check_page", return_value=[]):
        assert gui_check.run_gui_check(log, shot=tmp_path / "s.png") is True

    start.assert_called_once()
    proc.terminate.assert_called_once()
    assert any("ลูปเปิด GUI ให้" in line for line in lines)


def test_run_gui_check_reports_js_error_as_failure_without_raising(tmp_path):
    lines, log = _logger()
    proc = _fake_proc(poll=None)
    with mock.patch.object(gui_check, "gui_is_up", return_value=False), \
         mock.patch.object(gui_check, "start_gui", return_value=proc), \
         mock.patch.object(gui_check, "wait_gui_up", return_value=True), \
         mock.patch.object(gui_check, "check_api", return_value=[]), \
         mock.patch.object(gui_check, "check_page", return_value=["uncaught JS error: boom"]):
        assert gui_check.run_gui_check(log, shot=tmp_path / "s.png") is False

    proc.terminate.assert_called_once()
    assert any("ไม่ผ่าน" in line and "boom" in line for line in lines)


def test_run_gui_check_gives_up_when_gui_never_starts(tmp_path):
    lines, log = _logger()
    proc = _fake_proc(poll=None)
    with mock.patch.object(gui_check, "gui_is_up", return_value=False), \
         mock.patch.object(gui_check, "start_gui", return_value=proc), \
         mock.patch.object(gui_check, "wait_gui_up", return_value=False), \
         mock.patch.object(gui_check, "check_page") as page:
        assert gui_check.run_gui_check(log, shot=tmp_path / "s.png") is False

    page.assert_not_called()
    proc.terminate.assert_called_once()
    assert any("เปิด GUI ไม่สำเร็จ" in line for line in lines)


def test_run_gui_check_swallows_unexpected_errors(tmp_path):
    lines, log = _logger()
    with mock.patch.object(gui_check, "gui_is_up", return_value=True), \
         mock.patch.object(gui_check, "check_api", return_value=[]), \
         mock.patch.object(gui_check, "check_page", side_effect=RuntimeError("playwright missing")):
        assert gui_check.run_gui_check(log, shot=tmp_path / "s.png") is False

    assert any("ล้มเหลว" in line and "playwright missing" in line for line in lines)


def test_start_gui_runs_without_clearing_slots_or_browser():
    with mock.patch.object(gui_check.subprocess, "Popen") as popen, \
         mock.patch.object(Path, "mkdir"), mock.patch.object(Path, "open", mock.mock_open()):
        gui_check.start_gui(8765)

    cmd = popen.call_args[0][0]
    assert "auto_dev_crew.gui" in cmd
    assert "--keep-slots" in cmd
    assert "--no-browser" in cmd


def test_gui_check_at_start_skips_dry_run_and_disabled_config():
    with mock.patch.object(runner, "run_gui_check") as check:
        assert runner.gui_check_at_start({}, dry_run=True) is None
        assert runner.gui_check_at_start({"gui_check": {"enabled": False}}, dry_run=False) is None
    check.assert_not_called()


def test_gui_check_at_start_runs_by_default():
    with mock.patch.object(runner, "run_gui_check", return_value=True) as check:
        assert runner.gui_check_at_start({}, dry_run=False) is True
    check.assert_called_once()


def _run_gui_main(argv: list[str]):
    server = mock.MagicMock()
    server.serve_forever.side_effect = KeyboardInterrupt
    with mock.patch.object(gui, "ThreadingHTTPServer", return_value=server), \
         mock.patch.object(gui, "_clear_stale_slots") as clear, \
         mock.patch.object(gui, "AUTO"), mock.patch.object(gui, "AGENT"), \
         mock.patch("sys.argv", ["auto-dev-crew-gui", *argv]):
        gui.main()
    return clear


def test_gui_main_clears_slots_by_default():
    clear = _run_gui_main(["--no-browser", "--port", "8799"])
    clear.assert_called_once()


def test_gui_main_keep_slots_skips_clearing():
    clear = _run_gui_main(["--no-browser", "--keep-slots", "--port", "8799"])
    clear.assert_not_called()

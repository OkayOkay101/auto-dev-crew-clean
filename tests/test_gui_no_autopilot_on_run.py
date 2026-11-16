"""Running from the GUI is the user's explicit action: it must never turn AutoPilot on."""

from unittest import mock

from auto_dev_crew import gui


def test_run_with_loop_does_not_enable_autopilot():
    with mock.patch.object(gui.AGENT, "start") as mock_start, \
         mock.patch.object(gui.AUTO, "enable") as mock_enable:
        res = gui._api_run({"loop": True, "repo": "owner/repo"}, {})
    assert res == {"ok": True}
    mock_start.assert_called_once()
    mock_enable.assert_not_called()


def test_run_without_loop_does_not_enable_autopilot():
    with mock.patch.object(gui.AGENT, "start"), \
         mock.patch.object(gui.AUTO, "enable") as mock_enable:
        gui._api_run({}, {})
    mock_enable.assert_not_called()


def test_restart_with_loop_does_not_enable_autopilot():
    with mock.patch.object(gui.AGENT, "restart", return_value=["--loop", "--repo", "owner/repo"]), \
         mock.patch.object(gui.AUTO, "enable") as mock_enable:
        gui._api_restart({"loop": True, "repo": "owner/repo"}, {})
    mock_enable.assert_not_called()

"""The GUI must see a runner started outside it (e.g. from a terminal) and must not spawn a second one."""

import pytest

from auto_dev_crew import gui


def test_parse_picks_runner_and_skips_gui_and_others():
    rows = [
        (100, '"C:\\Python312\\python.exe" -m auto_dev_crew.gui --no-browser'),
        (200, 'C:\\Python312\\python.exe -u -m auto_dev_crew --loop --repo example-owner/example-repo-2'),
        (300, '"C:\\Python312\\python.exe" -u -m auto_dev_crew --loop'),
        (400, "python -m pytest -q"),
        (500, None),
        ("bad", "python -m auto_dev_crew --loop"),
    ]
    assert gui.parse_runner_pids(rows) == [200, 300]


def test_parse_honours_exclude():
    rows = [(200, "python -m auto_dev_crew --loop"), (300, "python -m auto_dev_crew --loop")]
    assert gui.parse_runner_pids(rows, exclude={200}) == [300]


def test_agent_sees_external_runner_as_running(monkeypatch):
    monkeypatch.setattr(gui, "_scan_runner_pids", lambda: [4242])
    agent = gui.Agent()
    assert agent.proc is None
    assert agent.running is True
    assert agent.external_pids() == [4242]


def test_agent_refuses_second_runner_when_external_one_exists(monkeypatch):
    monkeypatch.setattr(gui, "_scan_runner_pids", lambda: [4242])
    agent = gui.Agent()
    with pytest.raises(RuntimeError, match="นอก GUI"):
        agent.start(["--loop"])


def test_agent_not_running_when_nothing_found(monkeypatch):
    monkeypatch.setattr(gui, "_scan_runner_pids", lambda: [])
    agent = gui.Agent()
    assert agent.running is False
    assert agent.external_pids() == []

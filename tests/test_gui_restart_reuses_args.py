"""Bug: restart after an idle agent came back as a bare `--loop` (real mode on every repo).

Restart must keep the args of the last run. With no body it reuses them; if there are
none it refuses instead of silently starting a real loop.
"""

import re
from pathlib import Path

import pytest

from auto_dev_crew import gui

DATA_REPO = "example-owner/example-repo"
LAST_RUN = ["--loop", "--dry-run", "--repo", DATA_REPO]
ROOT = Path(__file__).resolve().parent.parent


def test_restart_without_body_reuses_last_run_args(monkeypatch):
    monkeypatch.setattr(gui.AGENT, "args", list(LAST_RUN))
    seen = []

    def fake_restart(args=None):
        seen.append(args)
        return args

    monkeypatch.setattr(gui.AGENT, "restart", fake_restart)
    res = gui.act("/api/restart", {})
    assert seen == [LAST_RUN]
    assert res["args"] == LAST_RUN


def test_restart_without_body_and_no_previous_args_is_refused(monkeypatch):
    monkeypatch.setattr(gui.AGENT, "args", [])
    called = []
    monkeypatch.setattr(gui.AGENT, "restart", lambda args=None: called.append(args))
    with pytest.raises(ValueError):
        gui.act("/api/restart", {})
    assert called == []  # never fall back to a silent real `--loop`


def test_restart_button_does_not_send_default_loop_payload():
    """Both UIs: the restart handler must not send loop/dry_run/repo defaults read from the form."""
    for name in ("index_sidebar.html", "index.html"):
        html = (ROOT / "auto_dev_crew" / "static" / name).read_text(encoding="utf-8")
        match = re.search(r"async function restartRun\(\) \{(.*?)\n\}", html, re.S)
        assert match, f"{name}: restartRun not found"
        block = match.group(1)
        assert "loop: true" not in block, f"{name}: restart still forces loop"
        assert "dry_run:" not in block, f"{name}: restart still reads the dry-run checkbox"
        assert 'post("/api/restart", {})' in block, f"{name}: restart must send an empty body"

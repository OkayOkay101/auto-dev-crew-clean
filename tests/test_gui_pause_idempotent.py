"""Bug: pressing "หยุดชั่วคราว" created one "⏸️ หยุดเอเจนต์ชั่วคราว" issue per click.

Pausing must be idempotent: when an open ai-pause issue already exists, no new one is created,
and concurrent requests create at most one.
"""

import threading
import time

from auto_dev_crew import gui

REPO = "example-owner/example-repo"
CFG = {"labels": {"pause": "ai-pause"}}


def _patch_gh(monkeypatch, open_numbers, create_log, list_delay=0.0):
    """Fake gh: `issue list` returns the open pause issues; `issue create` opens a new one."""
    lock = threading.Lock()

    def fake_gh_json(*args):
        time.sleep(list_delay)  # widen the check-then-create window
        with lock:
            return [{"number": n} for n in open_numbers]

    def fake_gh(*args, **kwargs):
        if args[:2] == ("issue", "create"):
            with lock:
                create_log.append(args)
                open_numbers.append(len(open_numbers) + 1)
        return ""

    monkeypatch.setattr(gui.runner, "ensure_labels", lambda repo, cfg: None)
    monkeypatch.setattr(gui.runner, "gh_json", fake_gh_json)
    monkeypatch.setattr(gui.runner, "gh", fake_gh)


def test_pause_on_does_not_create_when_open_pause_issue_exists(monkeypatch):
    creates = []
    _patch_gh(monkeypatch, open_numbers=[7], create_log=creates)
    assert gui._api_pause({"repo": REPO, "on": True}, CFG) == {"ok": True}
    assert creates == []


def test_pause_on_creates_one_issue_when_none_open(monkeypatch):
    creates = []
    _patch_gh(monkeypatch, open_numbers=[], create_log=creates)
    gui._api_pause({"repo": REPO, "on": True}, CFG)
    assert len(creates) == 1


def test_pause_on_does_not_duplicate_when_issue_list_lags_behind_create(monkeypatch):
    """Live bug: GitHub's issue list did not show a fresh pause issue yet, so a second click created another one.
    The issue this GUI just opened must count even while the list is stale."""
    gui._PAUSE_ISSUES.pop(REPO, None)
    creates = []

    def fake_gh_json(*args):
        if args[:2] == ("issue", "view"):
            return {"state": "OPEN"}
        return []  # the list is stale: it never shows the new issue

    def fake_gh(*args, **kwargs):
        if args[:2] == ("issue", "create"):
            creates.append(args)
            return "https://github.com/example-owner/example-repo/issues/4242"
        return ""

    monkeypatch.setattr(gui.runner, "ensure_labels", lambda repo, cfg: None)
    monkeypatch.setattr(gui.runner, "gh_json", fake_gh_json)
    monkeypatch.setattr(gui.runner, "gh", fake_gh)
    gui._api_pause({"repo": REPO, "on": True}, CFG)
    gui._api_pause({"repo": REPO, "on": True}, CFG)
    assert len(creates) == 1
    gui._PAUSE_ISSUES.pop(REPO, None)


def test_pause_on_concurrent_clicks_create_exactly_one_issue(monkeypatch):
    creates = []
    open_numbers = []
    _patch_gh(monkeypatch, open_numbers=open_numbers, create_log=creates, list_delay=0.05)
    barrier = threading.Barrier(8)
    errors = []

    def click():
        barrier.wait()
        try:
            gui._api_pause({"repo": REPO, "on": True}, CFG)
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=click) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == []
    assert len(creates) == 1
    assert len(open_numbers) == 1

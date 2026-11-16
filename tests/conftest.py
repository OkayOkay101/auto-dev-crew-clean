"""Shared pytest fixtures.

Every test runs with the module-level ``state/`` paths redirected to a temp dir so
the suite never reads or writes the real ``state/`` folder of the working copy.
Tests that patch these paths themselves still win, because their patches are
applied after this autouse fixture.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

# Isolate HOME before importing the package: importing it resolves the data dir
# (~/.ai-optimizer may be moved to ~/.auto-dev-crew), which tests must never touch.
import atexit
import shutil
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="adc-test-home-")
os.environ["HOME"] = _TEST_HOME
os.environ["USERPROFILE"] = _TEST_HOME
atexit.register(shutil.rmtree, _TEST_HOME, ignore_errors=True)

from auto_dev_crew import gui, keys, runner, sentinel_tracker  # noqa: E402
from auto_dev_crew.evaluator import EvaluationResult
from auto_dev_crew.slots import SlotRegistry


_ROOT = Path(__file__).resolve().parent.parent
_GUARDED = (_ROOT / "config.yaml", _ROOT / ".env", _ROOT / "opencode.json")


def _stamp(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


@pytest.fixture(autouse=True)
def _real_config_untouched():
    """Fail any test that writes the working copy's real config/.env/opencode.json."""
    before = {p: _stamp(p) for p in _GUARDED}
    yield
    changed = [p.name for p in _GUARDED if _stamp(p) != before[p]]
    assert not changed, f"test modified real project files: {changed} — use tmp_path"


_REAL_EXPORT = runner.export_dotenv_to_environ


@pytest.fixture
def real_export():
    """The genuine export_dotenv_to_environ (the autouse fixture below neutralises it)."""
    return _REAL_EXPORT


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Never let a test copy the real .env into os.environ, and restore os.environ afterwards."""
    with mock.patch.dict(os.environ):
        monkeypatch.setattr(runner, "export_dotenv_to_environ", lambda path=None: 0)
        monkeypatch.setattr(runner, "_DOTENV_EXPORTED", set())
        yield


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()

    monkeypatch.setattr(keys, "STATE", state)
    monkeypatch.setattr(keys, "ENGINE_STATUS", state / "engine_status.json")
    monkeypatch.setattr(keys, "KEY_STATUS", state / "key_status.json")
    monkeypatch.setattr(keys, "FAVORITE_KEYS", state / "favorite_keys.json")
    monkeypatch.setattr(keys, "KEY_ROLES", state / "key_roles.json")

    monkeypatch.setattr(runner, "STATE", state)
    monkeypatch.setattr(runner, "HISTORY", state / "history.json")
    monkeypatch.setattr(runner, "ENGINE_STATUS", state / "engine_status.json")
    monkeypatch.setattr(runner, "KEY_STATUS", state / "key_status.json")
    monkeypatch.setattr(runner, "MERGE_LOCK", state / "merge.lock")
    monkeypatch.setattr(runner, "SLOTS_DIR", state / "slots")
    monkeypatch.setattr(runner, "REGISTRY", SlotRegistry(state))

    monkeypatch.setattr(sentinel_tracker, "STATE", state)
    monkeypatch.setattr(sentinel_tracker, "SENTINEL_ISSUES", state / "sentinel_issues.json")

    monkeypatch.setattr(gui, "RUNS", state / "runs")
    yield state


# ---------------------------------------------------------------- runner fakes (non-autouse)

class FakeGh:
    """Stands in for ``runner.gh`` / ``runner.gh_json``.

    Every call is recorded in ``calls`` as the args tuple (e.g. ``("issue", "edit", "5", ...)``).
    ``on(prefix, value)`` programs a response for calls whose args start with ``prefix``;
    the longest matching prefix wins. ``value`` may be a string/list/dict, an exception
    instance (raised), or a callable taking the args tuple. Default: ``""`` for gh, ``[]`` for gh_json.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self._table: dict[tuple, object] = {}

    def on(self, prefix: tuple, value) -> None:
        self._table[tuple(prefix)] = value

    def _lookup(self, args: tuple):
        best = None
        for prefix in self._table:
            if args[:len(prefix)] == prefix and (best is None or len(prefix) > len(best)):
                best = prefix
        return None if best is None else self._table[best]

    def _resolve(self, args: tuple):
        self.calls.append(tuple(args))
        value = self._lookup(tuple(args))
        if callable(value):
            value = value(tuple(args))
        if isinstance(value, BaseException):
            raise value
        return value

    def gh(self, *args, cwd=None, check=True) -> str:
        value = self._resolve(args)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def gh_json(self, *args):
        value = self._resolve(args)
        if value is None:
            return []
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value

    def calls_with(self, *prefix) -> list[tuple]:
        return [c for c in self.calls if c[:len(prefix)] == tuple(prefix)]


@pytest.fixture
def fake_gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(runner, "gh", fake.gh)
    monkeypatch.setattr(runner, "gh_json", fake.gh_json)
    return fake


class FakePipeline:
    """Fakes the world around ``runner.execute``: clone, venv, shell/git, agent, eval, prompts.

    ``agent_result`` is the JSON the fake agent writes to its result file on each call.
    ``clone_dirs`` lists every scratch clone handed out. Mocks are autospec'd where practical.
    """

    def __init__(self, fake_gh: FakeGh, tmp_path: Path, monkeypatch):
        self.gh = fake_gh
        self.agent_result = {"status": "DONE", "title_th": "แก้ไขตัวอย่าง",
                             "summary_th": "ทำงานเรียบร้อย", "commit_message": "fix: example"}
        self.clone_dirs: list[Path] = []
        self._tmp = tmp_path
        self._mp = monkeypatch

        def fake_clone(repo, base, branch, slot_id=None):
            d = tmp_path / f"clone-{len(self.clone_dirs) + 1}"
            d.mkdir(parents=True)
            self.clone_dirs.append(d)
            return d

        def fake_agent(cfg, prompt, cwd, slot_id=None, role="coder"):
            (cwd.parent / f"{cwd.name}.result.json").write_text(
                json.dumps(self.agent_result), encoding="utf-8")
            return {}

        def fake_run(cmd, cwd=None, check=True, env=None, timeout=None, shell=False):
            return subprocess.CompletedProcess(cmd, 0, "", "")

        self.run = mock.create_autospec(runner.run, side_effect=fake_run)
        self.run_steps = mock.create_autospec(runner.run_steps, return_value=(True, "ok"))
        self.call_agent = mock.create_autospec(runner.call_agent, side_effect=fake_agent)
        self.evaluate_diff = mock.create_autospec(
            runner.evaluate_diff,
            return_value=EvaluationResult(score=0.9, passed=True, critique_th="ดี", dimensions={}))
        self.diff_stats = mock.create_autospec(runner.diff_stats, return_value=(12, ["auto_dev_crew/x.py"]))
        self.build_prompt = mock.create_autospec(runner.build_prompt, return_value="PROMPT")
        self.wait_for_checks = mock.create_autospec(runner.wait_for_checks, return_value="pass")
        self.clone = mock.create_autospec(runner.clone, side_effect=fake_clone)
        self.venv_env = mock.create_autospec(runner.venv_env, return_value={})

        for name, fake in (("run", self.run), ("run_steps", self.run_steps),
                           ("call_agent", self.call_agent), ("evaluate_diff", self.evaluate_diff),
                           ("diff_stats", self.diff_stats), ("build_prompt", self.build_prompt),
                           ("wait_for_checks", self.wait_for_checks), ("clone", self.clone),
                           ("venv_env", self.venv_env)):
            monkeypatch.setattr(runner, name, fake)


@pytest.fixture
def fake_pipeline(fake_gh, tmp_path, monkeypatch) -> FakePipeline:
    return FakePipeline(fake_gh, tmp_path, monkeypatch)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_feature_cycle: keep the real gui._feature_cycle (otherwise stubbed out)")


@pytest.fixture(autouse=True)
def _no_real_feature_cycle(request, monkeypatch):
    """STATE 2026-11-11: GUI actions ran the real feature cycle whenever the working copy's
    config.yaml had feature_gen enabled. Stub it everywhere except tests that opt in."""
    if request.node.get_closest_marker("real_feature_cycle"):
        return
    monkeypatch.setattr(gui, "_feature_cycle", lambda *a, **k: {"ran": False})


@pytest.fixture(autouse=True)
def _no_external_runner_scan(monkeypatch):
    """Tests must not see a real `python -m auto_dev_crew` loop running on this machine."""
    monkeypatch.setattr(gui, "_scan_runner_pids", lambda: [])

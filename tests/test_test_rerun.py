"""Unit tests for auto_dev_crew.test_rerun and the narrowed rerun in the fix loop."""
from __future__ import annotations

from pathlib import Path

from auto_dev_crew import runner
from auto_dev_crew.test_rerun import failed_test_ids, failure_tail, narrow_test_command

PYTEST_OUT = """\
$ python -m pytest -q
============================= test session starts =============================
collected 7 items

tests/test_a.py ..F..                                                    [ 71%]
tests/test_b.py .F                                                       [100%]

=========================== short test summary info ===========================
FAILED tests/test_a.py::test_one - assert 1 == 2
FAILED tests/test_b.py::TestX::test_two[param 1] - AssertionError
FAILED tests/test_a.py::test_one - assert 1 == 2
========================= 2 failed, 5 passed in 0.12s =========================
"""

IDS = ["tests/test_a.py::test_one", "tests/test_b.py::TestX::test_two[param 1]"]


def test_failed_test_ids_parses_and_dedupes():
    assert failed_test_ids(PYTEST_OUT) == IDS


def test_failed_test_ids_error_lines_need_double_colon():
    out = "ERROR tests/test_c.py::test_x - boom\nERROR tests/test_d.py - collection\n"
    assert failed_test_ids(out) == ["tests/test_c.py::test_x"]


def test_failed_test_ids_empty():
    assert failed_test_ids("3 passed in 0.01s") == []


def test_narrow_appends_plain_ids_exactly():
    assert narrow_test_command("python -m pytest -q", ["a.py::t1", "b.py::t2"]) == "python -m pytest -q a.py::t1 b.py::t2"


def test_narrow_quotes_with_double_quotes_only():
    cmd = narrow_test_command("pytest", IDS)
    assert cmd == 'pytest tests/test_a.py::test_one "tests/test_b.py::TestX::test_two[param 1]"'
    assert "'" not in cmd


def test_narrow_none_cases():
    assert narrow_test_command("npm test", IDS) is None
    assert narrow_test_command("python -m unittest discover", IDS) is None
    assert narrow_test_command("pytest -q", []) is None
    for chain in ("pip install -r r.txt && pytest", "pytest || true", "pytest; echo x", "pytest | tee o"):
        assert narrow_test_command(chain, IDS) is None


def test_narrow_none_when_positional_path_present():
    # `pytest tests/ <ids>` would still collect the whole path -> full suite runs again
    assert narrow_test_command("pytest tests/", IDS) is None
    assert narrow_test_command("python -m pytest -q tests/test_a.py", IDS) is None


def test_narrow_keeps_option_only_commands():
    assert narrow_test_command("python -m pytest -q --maxfail=2", ["a.py::t"]) == "python -m pytest -q --maxfail=2 a.py::t"


def test_failure_tail_keeps_last_lines():
    out = "\n".join(f"l{i}" for i in range(40))
    assert failure_tail(out).split("\n") == [f"l{i}" for i in range(25, 40)]


def test_failure_tail_drops_blank_trailing_lines_and_caps_chars():
    result = failure_tail("x" * 5000 + "\n\n\n")
    assert len(result) <= 1500
    assert not result.endswith("\n")


def test_failure_tail_empty():
    assert failure_tail("") == ""


# ---- fix loop wiring

def _loop(monkeypatch, tmp_path, steps, outputs, logs=None):
    """Run _agent_fix_loop with scripted run_steps results; return (calls, result).

    If `logs` is a list, every runner.log message is appended to it."""
    calls: list[str] = []
    queue = list(outputs)

    def fake_run_steps(s, cwd, env):
        calls.append(" | ".join(s))
        return queue.pop(0)

    monkeypatch.setattr(runner, "run_steps", fake_run_steps)
    monkeypatch.setattr(runner, "call_agent", lambda *a, **k: {"status": "OK"})
    monkeypatch.setattr(runner, "read_result", lambda p: {"status": "DONE"})
    monkeypatch.setattr(runner, "diff_stats", lambda cwd: (1, ["f.py"]))
    monkeypatch.setattr(runner, "log", lambda msg, *a, **k: logs.append(msg) if logs is not None else None)
    monkeypatch.setattr(runner, "render", lambda *a, **k: "FIX")
    res = runner._agent_fix_loop({}, "base", Path(tmp_path), {}, steps, Path(tmp_path) / "r.json", 3, None)
    return calls, res


def test_fix_loop_full_then_narrowed_then_full_confirm(monkeypatch, tmp_path):
    steps = ["python -m pytest -q"]
    calls, (ok, _out, _res) = _loop(monkeypatch, tmp_path, steps, [
        (False, PYTEST_OUT),
        (True, "2 passed"),
        (True, "7 passed"),
    ])
    assert ok is True
    assert calls == [
        "python -m pytest -q",
        'python -m pytest -q tests/test_a.py::test_one "tests/test_b.py::TestX::test_two[param 1]"',
        "python -m pytest -q",
    ]


def test_fix_loop_narrowed_failure_is_round_result_without_full_run(monkeypatch, tmp_path):
    steps = ["python -m pytest -q"]
    still = "FAILED tests/test_a.py::test_one - still\n1 failed in 0.1s"
    calls, (ok, out, _res) = _loop(monkeypatch, tmp_path, steps, [
        (False, PYTEST_OUT),
        (False, still),
        (False, still),
    ])
    assert ok is False
    assert out == still
    assert calls[0] == "python -m pytest -q"
    assert calls[1].startswith("python -m pytest -q tests/test_a.py::test_one")
    assert calls[2] == "python -m pytest -q tests/test_a.py::test_one"


def test_fix_loop_narrowed_inconclusive_falls_back_to_full_run(monkeypatch, tmp_path):
    steps = ["python -m pytest -q"]
    calls, (ok, out, _res) = _loop(monkeypatch, tmp_path, steps, [
        (False, PYTEST_OUT),
        (False, "ERROR: not found: tests/test_a.py::test_renamed" + chr(10) + "no tests ran in 0.01s"),
        (True, "7 passed"),
    ])
    assert ok is True and out == "7 passed"
    assert calls[1].startswith("python -m pytest -q tests/test_a.py::test_one")
    assert calls[2] == "python -m pytest -q"


def test_fix_loop_logs_failure_tail(monkeypatch, tmp_path):
    logs: list[str] = []
    _loop(monkeypatch, tmp_path, ["npm test"], [
        (False, "noise\nFAILED tests/t.py::x - boom"),
        (True, "ok"),
    ], logs=logs)
    assert any("FAILED tests/t.py::x - boom" in m for m in logs)


def test_fix_loop_non_pytest_runs_full_every_round(monkeypatch, tmp_path):
    calls, (ok, _out, _res) = _loop(monkeypatch, tmp_path, ["npm test"], [
        (False, "FAILED tests/test_a.py::test_one - x"),
        (True, "ok"),
    ])
    assert ok is True
    assert calls == ["npm test", "npm test"]

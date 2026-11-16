"""Retention for state/runs/opencode-raw-*.log: keep the newest N, never touch other files."""
from __future__ import annotations

from auto_dev_crew import runner


def _make(runs, n: int) -> list:
    paths = []
    for i in range(n):
        p = runs / f"opencode-raw-20261109-0{i:02d}000-1-eng.log"
        p.write_text("x", encoding="utf-8")
        paths.append(p)
    return paths


def test_prune_keeps_newest_n(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    paths = _make(runs, 5)

    removed = runner.prune_raw_logs(runs, keep=3)

    assert removed == 2
    assert not paths[0].exists() and not paths[1].exists()
    assert all(p.exists() for p in paths[2:])


def test_prune_ignores_unrelated_files(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _make(runs, 3)
    other = runs / "20261109-000000.log"
    other.write_text("keep", encoding="utf-8")

    runner.prune_raw_logs(runs, keep=1)

    assert other.exists()


def test_prune_keep_zero_disables(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    paths = _make(runs, 3)

    assert runner.prune_raw_logs(runs, keep=0) == 0
    assert all(p.exists() for p in paths)


def test_prune_missing_dir_is_noop(tmp_path):
    assert runner.prune_raw_logs(tmp_path / "missing", keep=5) == 0

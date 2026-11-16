"""Persona runs must not commit `.jules/` notes into the target repo (STATE 2026-11-12, PR #187/#190).

The note is kept under state/persona_notes instead, and the working tree is left with no `.jules/` change,
so a run that only wrote a note is treated as NO_ACTION.
"""
import subprocess

from auto_dev_crew import runner


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".jules").mkdir()
    (root / ".jules" / "bolt.md").write_text("# Bolt\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_jules_only_change_is_dropped_and_kept_outside_repo(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    (root / ".jules" / "bolt.md").write_text("# Bolt\n## 2026-11-12 - no change\n", encoding="utf-8")
    (root / ".jules" / "new.md").write_text("new note\n", encoding="utf-8")
    runner.clean_build_artifacts(root)
    _, files = runner.diff_stats(root)
    job = runner.Job("persona", "bolt", "bolt", "")

    dropped = runner._drop_persona_notes(job, root, files, "o/r")

    assert sorted(dropped) == [".jules/bolt.md", ".jules/new.md"]
    assert runner.diff_stats(root)[1] == []
    assert not (root / ".jules" / "new.md").exists()
    kept = (tmp_path / "state" / "persona_notes" / "o__r" / "bolt.md").read_text(encoding="utf-8")
    assert "no change" in kept and "new note" in kept


def test_source_change_is_left_alone(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    (root / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    (root / ".jules" / "bolt.md").write_text("# Bolt\nnote\n", encoding="utf-8")
    runner.clean_build_artifacts(root)
    _, files = runner.diff_stats(root)
    job = runner.Job("persona", "bolt", "bolt", "")

    dropped = runner._drop_persona_notes(job, root, files, "o/r")

    assert dropped == [".jules/bolt.md"]
    assert runner.diff_stats(root)[1] == ["src/a.py"]


def test_issue_jobs_are_not_touched(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    monkeypatch.setattr(runner, "STATE", tmp_path / "state")
    (root / ".jules" / "bolt.md").write_text("changed\n", encoding="utf-8")
    runner.clean_build_artifacts(root)
    _, files = runner.diff_stats(root)
    job = runner.Job("issue", "7", "t", "")

    assert runner._drop_persona_notes(job, root, files, "o/r") == []
    assert runner.diff_stats(root)[1] == [".jules/bolt.md"]

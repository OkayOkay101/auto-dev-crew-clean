"""Location of the on-disk data directory (work trees, repo cache, venvs).

The project was renamed from ai-optimizer, so the data folder moves from
``~/.ai-optimizer`` to ``~/.auto-dev-crew``. The move happens once, when the new
code starts and the old folder exists while the new one does not:

- the whole folder is renamed (a single rename on the same volume);
- ``venvs`` is renamed to ``venvs.moved``: venv launchers embed absolute paths,
  so the runner builds fresh venvs instead of reusing broken ones. Nothing is
  deleted; ``venvs.moved`` can be removed by hand later;
- stale git worktree entries in the cached repos are pruned (they pointed at the
  old path).

If the rename fails (for example a file is still locked by a running old process),
the old folder keeps being used and nothing is lost.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

LEGACY_NAME = ".ai-optimizer"
NEW_NAME = ".auto-dev-crew"


def resolve_data_home(home: Path) -> Path:
    """Return the data dir under ``home``, moving the legacy folder there once if needed."""
    new = home / NEW_NAME
    legacy = home / LEGACY_NAME
    if new.exists() or not legacy.exists():
        return new
    try:
        os.replace(legacy, new)
    except OSError:
        return legacy  # keep using the old folder; nothing was moved
    _after_move(new)
    return new


def _after_move(data: Path) -> None:
    venvs = data / "venvs"
    moved = data / "venvs.moved"
    if venvs.exists() and not moved.exists():
        try:
            os.replace(venvs, moved)
        except OSError:
            pass  # the runner would then reuse the old venvs; visible in logs
    repos = data / "repos"
    if repos.is_dir():
        for repo in repos.iterdir():
            if (repo / ".git").exists():
                try:
                    subprocess.run(
                        ["git", "-C", str(repo), "worktree", "prune"],
                        capture_output=True, check=False, timeout=60,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass


DATA_HOME = resolve_data_home(Path.home())

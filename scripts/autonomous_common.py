"""Shared helpers for autonomous mode (spec: docs/superpowers/specs/2026-11-09-autonomous-mode-design.md)."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MAX_TURNS = 40


def project_root() -> Path:
    """Project root. AUTONOMOUS_ROOT overrides it (used by tests)."""
    env = os.environ.get("AUTONOMOUS_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def state_dir(root: Path) -> Path:
    return root / "state"


def flag_path(root: Path) -> Path:
    return state_dir(root) / "autonomous.flag"


def mission_path(root: Path) -> Path:
    return state_dir(root) / "mission.md"


def counter_path(root: Path) -> Path:
    return state_dir(root) / "autonomous_counter.json"


def is_enabled(root: Path) -> bool:
    return flag_path(root).is_file()


def load_settings(root: Path) -> dict:
    """Read the `autonomous:` block from config.yaml, falling back to defaults."""
    settings = {"max_turns_per_session": DEFAULT_MAX_TURNS}
    cfg = root / "config.yaml"
    if not cfg.is_file():
        return settings
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return settings
    block = data.get("autonomous") if isinstance(data, dict) else None
    if isinstance(block, dict):
        value = block.get("max_turns_per_session")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            settings["max_turns_per_session"] = value
    return settings


def read_counter(root: Path) -> int:
    path = counter_path(root)
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("turns", 0))
    except (OSError, ValueError, AttributeError):
        return 0


def write_counter(root: Path, turns: int) -> None:
    counter_path(root).parent.mkdir(parents=True, exist_ok=True)
    counter_path(root).write_text(json.dumps({"turns": turns}), encoding="utf-8")

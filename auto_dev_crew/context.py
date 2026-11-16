"""Prompt context helpers: per-repo test commands, repo map and repo notes."""
from __future__ import annotations

from pathlib import Path

from .ast_skeleton import generate_repo_skeleton

DEFAULT_TEST_COMMANDS = "- Run the repository's existing test commands."
NOTES_FILES = ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md")


def format_test_commands(rcfg: dict) -> str:
    cmds = [str(c).strip() for c in (rcfg or {}).get("test", []) or [] if str(c).strip()]
    if not cmds:
        return DEFAULT_TEST_COMMANDS
    return "\n".join(f"- `{c}`" for c in cmds)


def build_repo_map(cwd: Path, cfg: dict | None) -> str:
    try:
        context_cfg = (cfg or {}).get("context") or {}
        if not context_cfg.get("repo_map", True):
            return ""
        max_chars = int(context_cfg.get("repo_map_chars", 6000))
        return generate_repo_skeleton(cwd, max_chars=max_chars)
    except Exception:
        return ""


def load_repo_notes(cwd: Path, max_chars: int = 4000) -> str:
    for name in NOTES_FILES:
        path = cwd / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            except OSError:
                return ""
    return ""

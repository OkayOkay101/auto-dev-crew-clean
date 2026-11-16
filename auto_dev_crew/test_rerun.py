"""Narrow a pytest command down to the cases that failed in the previous run."""
from __future__ import annotations

import re

_FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S.*?)(?: - .*)?$", re.MULTILINE)
_SAFE_ID_RE = re.compile(r"^[\w./:\-\[\]]+$")
_PYTEST_RE = re.compile(r"(?:^|[\s/\\])(?:pytest|py\.test)(?:\.exe)?(?:\s|$)")
_CHAIN_RE = re.compile(r"&&|\|\||;|\|")


def failure_tail(output: str, max_lines: int = 15, max_chars: int = 1500) -> str:
    """Last `max_lines` lines (capped to `max_chars` chars) of a failing test run."""
    tail = "\n".join(output.rstrip().split("\n")[-max_lines:])
    return tail[-max_chars:]


def failed_test_ids(output: str) -> list[str]:
    """Return node ids from pytest `FAILED path::name` / `ERROR path::name` lines, in order, deduped."""
    ids: list[str] = []
    for m in _FAILED_RE.finditer(output or ""):
        node = m.group(1).strip()
        if "::" in node and node not in ids:
            ids.append(node)
    return ids


def _quote(node: str) -> str:
    # Double quotes only: single quotes stay literal under Windows cmd.exe.
    if _SAFE_ID_RE.match(node):
        return node
    return '"' + node.replace('"', '\\"') + '"'


def narrow_test_command(cmd: str, failed: list[str]) -> str | None:
    """`cmd` restricted to the failed ids, or None if it can't be narrowed safely."""
    m = _PYTEST_RE.search(cmd) if failed else None
    if not m or _CHAIN_RE.search(cmd):
        return None
    # A positional arg (e.g. `pytest tests/`) keeps collecting that whole path, so the ids
    # would not narrow anything. Conservative: any non-option token after pytest -> None.
    if any(not tok.startswith("-") for tok in cmd[m.end():].split()):
        return None
    return cmd + " " + " ".join(_quote(i) for i in failed)

"""Harness Guardrails: Deterministic Pre-Eval, Output Truncation, and Evidence-based Pruning."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def truncate_tool_output(output: str, max_chars: int = 2500) -> str:
    """Truncates output exceeding max_chars while retaining both head and tail context."""
    if max_chars <= 0:
        return ""
    if len(output) <= max_chars:
        return output

    half = max_chars // 2
    head = output[:half]
    tail = output[-half:]
    omitted = len(output) - (len(head) + len(tail))
    return f"{head}\n[... Truncated {omitted} characters ...]\n{tail}"


def check_deterministic_pre_eval(cwd: Path, changed_files: list[str] | None = None) -> tuple[bool, str]:
    """Performs deterministic verification (Python AST syntax parse) before invoking LLM judge."""
    files_to_check: list[str] = []
    if changed_files is not None:
        files_to_check = [f for f in changed_files if f.endswith(".py")]
    else:
        # Check all python files in cwd
        for p in cwd.glob("**/*.py"):
            if not any(part.startswith(".") or part in ("venv", "__pycache__", "build", "dist") for part in p.parts):
                files_to_check.append(str(p.relative_to(cwd)))

    for rel_path in files_to_check:
        full_path = cwd / rel_path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            ast.parse(content, filename=str(rel_path))
        except SyntaxError as e:
            return False, f"Python Syntax Error in {rel_path} line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, f"Failed to parse {rel_path}: {e}"

    return True, "Deterministic pre-eval checks passed"


def prune_resolved_evidence(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evidence-based pruning: squashes verbose error outputs for steps that were subsequently resolved."""
    if not history:
        return []

    pruned = [dict(h) for h in history]
    # Track actions that succeeded later in the trajectory
    succeeded_actions = set()
    for item in reversed(pruned):
        action = item.get("action")
        status = str(item.get("status", "")).lower()
        if status in ("ok", "passed", "success"):
            if action:
                succeeded_actions.add(action)
        elif status in ("failed", "error"):
            if action in succeeded_actions:
                # This failure was resolved by a subsequent action of the same type
                step_num = item.get("step", "?")
                item["output"] = f"[Previous failure in step {step_num} resolved by subsequent successful {action}]"

    return pruned

"""Smart AST Skeleton + Line-Window Context Slicer for Gate 1 & Gate 2 (Solves STATE.md O25).

Prevents large files (such as 3,200+ line HTML/JS or runner.py) from losing critical lines past
character cutoffs while keeping token usage compact for free-tier Judge engines.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

LINE_CITATION_RE = re.compile(r"(?:line\s+|lines\s+|#L|:)(\d{1,6})\b", re.IGNORECASE)


def extract_cited_lines(text: str, total_lines: int) -> list[int]:
    """Find valid 1-based line numbers referenced in an issue body, diff, or traceback."""
    if not text or total_lines < 1:
        return []
    nums = {int(m.group(1)) for m in LINE_CITATION_RE.finditer(text)}
    return sorted(n for n in nums if 1 <= n <= total_lines)


def build_python_ast_map(source: str) -> str:
    """Extract top-level classes, methods, and function signatures with line numbers."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    rows: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            rows.append(f"L{node.lineno}: class {node.name}:")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = ast.unparse(item.args) if hasattr(ast, "unparse") else "..."
                    rows.append(f"  L{item.lineno}: def {item.name}({sig})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
            rows.append(f"L{node.lineno}: def {node.name}({sig})")
    return "\n".join(rows)


def merge_line_windows(anchors: list[int], total_lines: int, radius: int = 80) -> list[tuple[int, int]]:
    """Build merged (start_line, end_line) 1-based inclusive windows around cited anchor lines."""
    if total_lines < 1:
        return []
    if not anchors:
        return [(1, min(total_lines, max(1, radius * 2)))]
    raw = sorted((max(1, a - radius), min(total_lines, a + radius)) for a in anchors)
    merged: list[tuple[int, int]] = [raw[0]]
    for start, end in raw[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 6:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def slice_file_for_gate(
    path: Path,
    reference_text: str = "",
    *,
    radius: int = 80,
    max_chars: int = 120_000,
) -> str:
    """Return full numbered file if small, or AST outline + cited line windows when large."""
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    total = len(lines)
    if len(content) <= max_chars // 3:
        return "\n".join(f"{idx:5d} | {line}" for idx, line in enumerate(lines, 1))[:max_chars]

    anchors = extract_cited_lines(reference_text, total)
    blocks: list[str] = [f"# Smart Context Slice: {path.name} ({total} lines, {len(content)} chars)"]

    if path.suffix == ".py":
        outline = build_python_ast_map(content)
        if outline:
            blocks.append("## Python AST Symbol Map\n" + outline[:15_000])

    for start, end in merge_line_windows(anchors, total, radius=radius):
        snippet = "\n".join(f"{ln:5d} | {lines[ln - 1]}" for ln in range(start, end + 1))
        blocks.append(f"## Source Window L{start}..L{end}\n{snippet}")

    return "\n\n".join(blocks)[:max_chars]

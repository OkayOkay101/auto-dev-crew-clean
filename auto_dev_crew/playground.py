"""Disposable local toy repository (`~/.auto-dev-crew/playground-demo`) for zero-risk beginner practice."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from .data_home import DATA_HOME

PLAYGROUND_DIR_NAME = "playground-demo"

TOY_PAGINATOR_PY = '''"""Toy Module 1: Paginator with an off-by-one slice bug on line 11."""
from __future__ import annotations

def paginate_items(items: list, page: int, per_page: int = 5) -> list:
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    start = (page - 1) * per_page
    end = start + per_page
    # Seeded Toy Bug #1: drops the final item on every full page
    return items[start : max(start, end - 1)]
'''

TOY_BADGE_PY = '''"""Toy Module 2: HTML badge formatter missing html.escape() on line 7."""
from __future__ import annotations

def format_badge(label: str) -> str:
    # Seeded Toy Bug #2: raw interpolation breaks HTML if label has '<' or '&'
    return f"<span class='badge'>{label}</span>"
'''

TOY_TESTS_PY = '''import unittest
from toy_app.paginator import paginate_items
from toy_app.badge_render import format_badge

class TestToyAppBaseline(unittest.TestCase):
    def test_invalid_page_rejected(self):
        with self.assertRaises(ValueError):
            paginate_items([1, 2, 3], 0)

    def test_basic_badge(self):
        self.assertEqual(format_badge("Ready"), "<span class='badge'>Ready</span>")

if __name__ == "__main__":
    unittest.main()
'''


def _rmtree_writable(path: Path) -> None:
    """ลบโฟลเดอร์ Git ทั้งชุด รวมไฟล์ read-only ที่ git เขียนไว้ (Windows จะปฏิเสธ rmtree ธรรมดา)"""
    def _retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=_retry)


def resolve_playground_dir(base_dir: Path | None = None) -> Path:
    root = (base_dir if base_dir is not None else DATA_HOME).resolve()
    target = (root / PLAYGROUND_DIR_NAME).resolve()
    if target == root or not target.is_relative_to(root):
        raise PermissionError("Playground path escaped DATA_HOME boundary")
    return target


def reset_or_create_playground(base_dir: Path | None = None) -> dict[str, object]:
    """Create a clean local Git repository with 2 seeded bugs and strictly zero GitHub remotes."""
    target = resolve_playground_dir(base_dir)
    if target.exists():
        _rmtree_writable(target)

    pkg_dir = target / "toy_app"
    tests_dir = target / "tests"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "paginator.py").write_text(TOY_PAGINATOR_PY, encoding="utf-8")
    (pkg_dir / "badge_render.py").write_text(TOY_BADGE_PY, encoding="utf-8")
    (tests_dir / "test_toy_app.py").write_text(TOY_TESTS_PY, encoding="utf-8")

    git_bin = shutil.which("git")
    git_initialized = False
    if git_bin:
        subprocess.run([git_bin, "init", "-b", "main"], cwd=target, capture_output=True, check=True)
        subprocess.run([git_bin, "config", "user.name", "Auto Dev Crew Playground"], cwd=target, capture_output=True, check=True)
        subprocess.run([git_bin, "config", "user.email", "playground@localhost"], cwd=target, capture_output=True, check=True)
        subprocess.run(
            [
                git_bin,
                "add",
                "toy_app/__init__.py",
                "toy_app/paginator.py",
                "toy_app/badge_render.py",
                "tests/test_toy_app.py",
            ],
            cwd=target,
            capture_output=True,
            check=True,
        )
        subprocess.run([git_bin, "commit", "-m", "chore: initialize disposable toy repo"], cwd=target, capture_output=True, check=True)
        remotes = subprocess.run([git_bin, "remote"], cwd=target, capture_output=True, text=True, check=True).stdout.strip()
        if remotes:
            raise RuntimeError("Playground must never have a remote configured")
        git_initialized = True

    return {
        "ok": True,
        "path": str(target),
        "git_initialized": git_initialized,
        "remotes": [],
        "bugs": [
            {"id": "bug1", "file": "toy_app/paginator.py", "line": 11, "summary": "Off-by-one slice end - 1"},
            {"id": "bug2", "file": "toy_app/badge_render.py", "line": 7, "summary": "Missing html.escape(label)"},
        ],
    }

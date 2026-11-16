import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.ast_skeleton import extract_ast_skeleton, generate_repo_skeleton


class TestAstSkeleton(unittest.TestCase):
    def test_extract_ast_skeleton_classes_and_functions(self):
        sample_code = '''"""Module docstring."""
import os
from typing import Optional

CONSTANT_VAL = 42

class DatabaseManager:
    """Manages db connections."""
    def __init__(self, dsn: str, timeout: int = 30) -> None:
        self.dsn = dsn
        self.conn = None
        self._setup()

    def query(self, sql: str, params: Optional[dict] = None) -> list:
        """Executes a query and returns rows."""
        # complex logic
        rows = []
        for x in range(10):
            rows.append(x)
        return rows

    def _private_helper(self):
        return True

def standalone_task(user_id: int, flag: bool = False) -> bool:
    """Executes standalone task."""
    x = 100
    return flag
'''
        skeleton = extract_ast_skeleton(sample_code, file_path="db.py")
        self.assertIn("class DatabaseManager:", skeleton)
        self.assertIn("def __init__(self, dsn: str, timeout: int = 30) -> None: ...", skeleton)
        self.assertIn("def query(self, sql: str, params: Optional[dict] = None) -> list: ...", skeleton)
        self.assertIn("def standalone_task(user_id: int, flag: bool = False) -> bool: ...", skeleton)
        # Verify internal implementation bodies are stripped
        self.assertNotIn("rows = []", skeleton)
        self.assertNotIn("x = 100", skeleton)
        # Docstrings included
        self.assertIn('"""Manages db connections."""', skeleton)

    def test_generate_repo_skeleton(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            pkg = p / "pkg"
            pkg.mkdir()
            (pkg / "core.py").write_text("class CoreEngine:\n    def run(self) -> None:\n        print('running')\n", encoding="utf-8")
            (pkg / "utils.py").write_text("def helper(x: int) -> int:\n    return x * 2\n", encoding="utf-8")
            
            # Subdirectory to ignore
            tests_dir = p / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_core.py").write_text("def test_ok(): pass\n", encoding="utf-8")

            summary = generate_repo_skeleton(p, max_chars=5000)
            self.assertIn("pkg/core.py", summary.replace("\\", "/"))
            self.assertIn("class CoreEngine:", summary)
            self.assertIn("def run(self) -> None: ...", summary)
            self.assertIn("def helper(x: int) -> int: ...", summary)
            # test directory should be excluded
            self.assertNotIn("test_core.py", summary)


if __name__ == "__main__":
    unittest.main()

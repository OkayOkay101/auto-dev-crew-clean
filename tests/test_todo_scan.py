import hashlib
import tempfile
import unittest
from pathlib import Path

from auto_dev_crew.todo_scan import TodoItem, create_todo_issues, fetch_existing_bodies, scan_todos


def _item(path="a.py", line=3, text="add retry", ctx="ctx"):
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return TodoItem(path, line, text, ctx, f"<!-- ai-todo:{path}:{h} -->")


class TestScanTodos(unittest.TestCase):
    def test_scan_finds_items_and_skips_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.py").write_text("l1\nl2\n# [AI-TODO] add retry\nl4\nl5\nl6\nl7\nl8\n", encoding="utf-8")
            (root / "b.js").write_text("// [AI-TODO] x\n", encoding="utf-8")
            (root / "plain.py").write_text("# TODO: generic\n# FIXME: no\n", encoding="utf-8")
            for skip in ("node_modules", ".git", ".venv-x", "_slot_1"):
                (root / skip).mkdir()
                (root / skip / "c.js").write_text("// [AI-TODO] hidden\n", encoding="utf-8")
            items = scan_todos(root)
            self.assertEqual(sorted(i.path for i in items), ["a.py", "b.js"])
            a = next(i for i in items if i.path == "a.py")
            self.assertEqual(a.line, 3)
            self.assertEqual(a.text, "add retry")
            self.assertIn("l1", a.context)
            self.assertIn("l6", a.context)
            self.assertNotIn("l7", a.context)
            sha = hashlib.sha1(b"add retry").hexdigest()[:8]
            self.assertEqual(a.marker, f"<!-- ai-todo:a.py:{sha} -->")

    def test_latin1_binary_and_large_files_do_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "l.py").write_bytes("# caf\xe9\n# [AI-TODO] latin ok\n".encode("latin-1"))
            (root / "bin.dat").write_bytes(b"\x00\x01# [AI-TODO] binary\n")
            (root / "big.txt").write_text("# [AI-TODO] big\n" + "x" * (1024 * 1024 + 10), encoding="utf-8")
            items = scan_todos(root)
            self.assertEqual([i.path for i in items], ["l.py"])

    def test_nested_path_is_posix(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sub").mkdir()
            (root / "sub" / "m.py").write_text("# [AI-TODO] nested\n", encoding="utf-8")
            self.assertEqual(scan_todos(root)[0].path, "sub/m.py")


class TestCreateIssues(unittest.TestCase):
    def test_skips_existing_dedupes_and_limits(self):
        calls = []

        def run(*argv):
            calls.append(argv)
            return f"https://github.com/o/r/issues/{len(calls)}"

        items = [_item("a.py", 1, "one"), _item("b.py", 2, "two"), _item("b.py", 9, "two"),
                 _item("c.py", 3, "three"), _item("d.py", 4, "four")]
        existing = [f"body\n{items[0].marker}\n"]
        urls = create_todo_issues("o/r", items, existing, limit=2, run=run)
        self.assertEqual(len(urls), 2)
        self.assertEqual(len(calls), 2)
        titles = [c[c.index("--title") + 1] for c in calls]
        self.assertEqual(titles, ["[AI-TODO] b.py:2 two", "[AI-TODO] c.py:3 three"])

    def test_argv_label_body_and_title_cut(self):
        calls = []
        long_text = "y" * 120
        it = _item("a.py", 5, long_text, "line with sk-" + "A" * 30)
        create_todo_issues("o/r", [it], [], run=lambda *a: calls.append(a) or "url")
        argv = calls[0]
        self.assertEqual(argv[:3], ("issue", "create", "-R"))
        self.assertEqual(argv[argv.index("--label") + 1], "ai-task")
        self.assertEqual(argv[argv.index("--title") + 1], "[AI-TODO] a.py:5 " + "y" * 80)
        body = argv[argv.index("--body") + 1]
        self.assertIn(it.marker, body)
        self.assertIn("a.py:5", body)
        self.assertIn("```", body)
        self.assertNotIn("A" * 30, body)

    def test_custom_label(self):
        calls = []
        create_todo_issues("o/r", [_item()], [], label="x-task", run=lambda *a: calls.append(a) or "u")
        self.assertEqual(calls[0][calls[0].index("--label") + 1], "x-task")

    def test_partial_failure_keeps_urls_and_records_error(self):
        n = []

        def run(*argv):
            n.append(argv)
            if len(n) == 2:
                raise RuntimeError("gh boom")
            return f"https://x/issues/{len(n)}"

        items = [_item("a.py", 1, "one"), _item("b.py", 2, "two"), _item("c.py", 3, "three")]
        errors = []
        urls = create_todo_issues("o/r", items, [], run=run, errors=errors)
        self.assertEqual(urls, ["https://x/issues/1", "https://x/issues/3"])
        self.assertEqual(len(errors), 1)
        self.assertIn("b.py:2", errors[0])
        self.assertIn("gh boom", errors[0])


class TestFetchExisting(unittest.TestCase):
    def test_label_listing_without_search(self):
        calls = []

        def run(*argv):
            calls.append(argv)
            return '[{"body": "b1"}, {"body": null}]'

        self.assertEqual(fetch_existing_bodies("o/r", run=run, label="ai-task"), ["b1", ""])
        argv = calls[0]
        self.assertNotIn("--search", argv)
        self.assertEqual(argv[argv.index("--label") + 1], "ai-task")
        self.assertEqual(argv[argv.index("--limit") + 1], "1000")
        self.assertEqual(argv[argv.index("--state") + 1], "all")



class TestHardening(unittest.TestCase):
    def _scan(self, content):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "f.txt").write_text(content, encoding="utf-8")
            return scan_todos(Path(d))

    def test_comment_markers_match_and_string_literals_do_not(self):
        content = "\n".join([
            "x = 1  # [AI-TODO] after code",
            "/* [AI-TODO] block */",
            " * [AI-TODO] star",
            "<!-- [AI-TODO] html -->",
            "-- [AI-TODO] sql",
            "#[AI-TODO] tight",
            'TAG = "[AI-TODO]"',
            'msg = "see [AI-TODO] later"',
            "# [AI-TODO]",
            "// [AI-TODO]   ",
        ])
        texts = [i.text for i in self._scan(content)]
        self.assertEqual(texts, ["after code", "block */", "star", "html -->", "sql", "tight"])

    def test_context_lines_truncated_and_fence_safe(self):
        long = "y" * 1000
        content = f"{long}\n# [AI-TODO] fix\n```python\nprint(1)\n```\n"
        item = self._scan(content)[0]
        self.assertTrue(all(len(c) <= 300 for c in item.context.split("\n")))
        from auto_dev_crew.todo_scan import _issue_body
        body = _issue_body(item)
        self.assertIn("````\n", body)
        self.assertTrue(body.rstrip().endswith("````"))

    def test_line_shift_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.py"
            f.write_text("x = 1\n# [AI-TODO] add retry\ny = 2\n", encoding="utf-8")
            created = []

            def run(*argv):
                created.append(argv[argv.index("--body") + 1])
                return "https://x/issues/1"

            first = create_todo_issues("o/r", scan_todos(Path(d)), [], run=run)
            self.assertEqual(len(first), 1)
            f.write_text("# new\n# lines\n# above\nx = 1\n# [AI-TODO] add retry\ny = 2\n", encoding="utf-8")
            calls = []
            second = create_todo_issues("o/r", scan_todos(Path(d)), created, run=lambda *a: calls.append(a) or "u")
            self.assertEqual(second, [])
            self.assertEqual(calls, [])

    def test_secret_redacted_in_title(self):
        key = "sk-" + "a" * 40
        title_args = []

        def run(*argv):
            title_args.append(argv[argv.index("--title") + 1])
            return "u"

        create_todo_issues("o/r", [_item("a.py", 1, f"rotate {key} now")], [], run=run)
        self.assertNotIn(key, title_args[0])


class TestRunScan(unittest.TestCase):
    def _run(self, pull):
        from unittest.mock import patch
        from auto_dev_crew import todo_scan
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("# [AI-TODO] one\n", encoding="utf-8")
            with patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir", return_value=Path(d)), \
                 patch("auto_dev_crew.todo_scan.subprocess.run", side_effect=pull) as m:
                return todo_scan.run_scan("o/r", {}), m

    def test_pull_attempted(self):
        from types import SimpleNamespace
        res, m = self._run(lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertEqual(m.call_args.args[0], ["git", "pull", "--ff-only"])
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(res["warnings"], [])

    def test_pull_failure_is_warning(self):
        def boom(*a, **k):
            raise OSError("no git")
        res, _ = self._run(boom)
        self.assertEqual(len(res["items"]), 1)
        self.assertEqual(len(res["warnings"]), 1)

    def test_pull_nonzero_is_warning(self):
        from types import SimpleNamespace
        res, _ = self._run(lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="diverged"))
        self.assertEqual(len(res["items"]), 1)
        self.assertIn("diverged", res["warnings"][0])

    def test_pull_disables_terminal_prompt(self):
        from types import SimpleNamespace
        _, m = self._run(lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.assertEqual(m.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")


class TestSymlinks(unittest.TestCase):
    def test_is_symlink_files_skipped(self):
        # Portable check (Windows often forbids creating real symlinks).
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "real.py").write_text("# [AI-TODO] inside\n", encoding="utf-8")
            (Path(d) / "link.py").write_text("# [AI-TODO] via link\n", encoding="utf-8")
            orig = Path.is_symlink
            with patch.object(Path, "is_symlink", lambda p: p.name == "link.py" or orig(p)):
                self.assertEqual([i.path for i in scan_todos(Path(d))], ["real.py"])

    def test_symlinked_file_skipped(self):
        import os
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.py"
            target.write_text("# [AI-TODO] outside\n", encoding="utf-8")
            (Path(d) / "real.py").write_text("# [AI-TODO] inside\n", encoding="utf-8")
            try:
                os.symlink(target, Path(d) / "link.py")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not permitted on this platform")
            self.assertEqual([i.path for i in scan_todos(Path(d))], ["real.py"])


if __name__ == "__main__":
    unittest.main()

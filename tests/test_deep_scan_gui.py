import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew import deep_scan, gui

FINDING = deep_scan.Finding("bug", "t", "a.py", 1, "ev", "fix")
CFG = {"repos": [{"name": "o/r"}], "labels": {"task": "ai-task"},
       "engines": [{"name": "eng", "command": "x", "api_keys": ["${SCAN_KEY}"]},
                   {"name": "other", "command": "y", "api_keys": ["${PLAIN}"]}]}


class TestDeepScanGui(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, kw in (("auto_dev_crew.gui.load_cfg", {"return_value": CFG}),
                           ("auto_dev_crew.keys.get_key_effective_roles",
                            {"side_effect": lambda v: ["scan"] if v == "SCAN_KEY" else ["coder"]}),
                           ("auto_dev_crew.runner.STATE", {"new": Path(self.tmp.name)})):
            p = patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        deep_scan.save_run(Path(self.tmp.name), "o/r", [FINDING], "run1")

    def test_repo_outside_config_is_400(self):
        for path in ("/api/deep-scan", "/api/deep-scan/file", "/api/deep-scan/dismiss"):
            with self.assertRaises(gui.DeepScanHttpError) as c:
                gui.act(path, {"repo": "x/y", "engine": "eng", "finding_id": "run1-0"})
            self.assertEqual(c.exception.status, 400)

    def test_unknown_engine_is_400(self):
        with self.assertRaises(gui.DeepScanHttpError) as c:
            gui.act("/api/deep-scan", {"repo": "o/r", "engine": "nope"})
        self.assertEqual(c.exception.status, 400)

    def test_non_scan_engine_is_400(self):
        with self.assertRaises(gui.DeepScanHttpError) as c:
            gui.act("/api/deep-scan", {"repo": "o/r", "engine": "other"})
        self.assertEqual(c.exception.status, 400)

    @patch("auto_dev_crew.deep_scan.set_status", side_effect=KeyError("x"))
    @patch("auto_dev_crew.runner.gh", side_effect=lambda *a, **k: "[]" if a[:2] == ("issue", "list") else "https://x/issues/9")
    def test_status_failure_after_create_is_warning(self, _gh, _set):
        res = gui.act("/api/deep-scan/file", {"repo": "o/r", "finding_id": "run1-0"})
        self.assertTrue(res["ok"])
        self.assertEqual((res["url"], res["status"]), ("https://x/issues/9", "new"))
        self.assertIn("warning", res)

    def test_unknown_finding_is_404(self):
        for path in ("/api/deep-scan/file", "/api/deep-scan/dismiss"):
            with self.assertRaises(gui.DeepScanHttpError) as c:
                gui.act(path, {"repo": "o/r", "finding_id": "missing"})
            self.assertEqual(c.exception.status, 404)

    def test_dismiss_sets_status(self):
        res = gui.act("/api/deep-scan/dismiss", {"repo": "o/r", "finding_id": "run1-0"})
        self.assertTrue(res["ok"])
        self.assertEqual(deep_scan.load_run(Path(self.tmp.name), "o/r")["findings"][0]["status"], "dismissed")

    @patch("auto_dev_crew.runner.gh")
    def test_file_then_duplicate_skipped(self, mock_gh):
        calls = []

        def fake(*args, **kw):
            calls.append(args[:2])
            if args[:2] == ("issue", "list"):
                return json.dumps([{"body": deep_scan.finding_marker(FINDING)}]) if len(calls) > 2 else "[]"
            return "https://x/issues/1"
        mock_gh.side_effect = fake
        res = gui.act("/api/deep-scan/file", {"repo": "o/r", "finding_id": "run1-0"})
        self.assertEqual(res["url"], "https://x/issues/1")
        self.assertEqual(deep_scan.load_run(Path(self.tmp.name), "o/r")["findings"][0]["status"], "filed")
        res = gui.act("/api/deep-scan/file", {"repo": "o/r", "finding_id": "run1-0"})
        self.assertEqual(res, {"ok": True, "skipped": True})
        self.assertEqual(deep_scan.load_run(Path(self.tmp.name), "o/r")["findings"][0]["status"], "filed")
        self.assertEqual(calls.count(("issue", "list")), 2)  # fresh fetch each click

    @patch("auto_dev_crew.runner.gh", side_effect=RuntimeError("boom ghp_" + "a" * 36))
    def test_create_failure_is_clean_payload(self, _gh):
        res = gui.act("/api/deep-scan/file", {"repo": "o/r", "finding_id": "run1-0"})
        self.assertFalse(res["ok"])
        self.assertNotIn("a" * 36, res["error"])
        self.assertEqual(deep_scan.load_run(Path(self.tmp.name), "o/r")["findings"][0]["status"], "new")

    # These pin the inline (temp-dir) behaviour; agentic mode (repo clone as cwd) is covered in test_deep_scan_agentic.py
    @patch("auto_dev_crew.gui._feature_cycle", return_value={"ran": False})
    @patch("auto_dev_crew.deep_scan.scan_mode", return_value="inline")
    @patch("auto_dev_crew.runner.call_agent")
    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.deep_scan.subprocess.run")
    def test_scan_binds_call_agent(self, _pull, mock_dir, mock_agent, _mode, _fc):
        repo_dir = Path(self.tmp.name) / "clone"
        (repo_dir / "src").mkdir(parents=True)
        (repo_dir / "src" / "a.py").write_text("x\n", encoding="utf-8")
        mock_dir.return_value = repo_dir
        mock_agent.return_value = {"status": "SUCCESS", "response": "[]", "engine_used": "eng"}
        res = gui.act("/api/deep-scan", {"repo": "o/r", "engine": "eng"})
        self.assertTrue(res["ok"])
        kw = mock_agent.call_args.kwargs
        self.assertEqual((kw["role"], kw["engine_name"]), ("scan", "eng"))
        cwd = mock_agent.call_args.args[2]
        self.assertNotEqual(cwd, repo_dir)
        self.assertNotIn(repo_dir.resolve(), Path(cwd).resolve().parents)
        self.assertNotIn(Path(cwd).resolve(), repo_dir.resolve().parents)
        self.assertNotEqual(Path(cwd).resolve(), repo_dir.resolve())

    @patch("auto_dev_crew.gui._feature_cycle", return_value={"ran": False})
    @patch("auto_dev_crew.deep_scan.scan_mode", return_value="inline")
    @patch("auto_dev_crew.runner.call_agent")
    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.deep_scan.subprocess.run")
    def test_scan_temp_cwd_is_empty_and_removed(self, _pull, mock_dir, mock_agent, _mode, _fc):
        repo_dir = Path(self.tmp.name) / "clone"
        (repo_dir / "src").mkdir(parents=True)
        (repo_dir / "src" / "a.py").write_text("x\n", encoding="utf-8")
        mock_dir.return_value = repo_dir
        seen = {}

        def fake(cfg, prompt, cwd, **kw):
            seen["cwd"] = Path(cwd)
            seen["existed"] = Path(cwd).is_dir()
            seen["empty"] = not any(Path(cwd).iterdir())
            return {"status": "SUCCESS", "response": "[]"}
        mock_agent.side_effect = fake
        gui.act("/api/deep-scan", {"repo": "o/r", "engine": "eng"})
        self.assertTrue(seen["existed"] and seen["empty"])
        self.assertFalse(seen["cwd"].exists())

    @patch("auto_dev_crew.runner.call_agent", return_value={"status": "ERROR", "response": "bad"})
    @patch("auto_dev_crew.multi_repo.find_or_prepare_repo_dir")
    @patch("auto_dev_crew.deep_scan.subprocess.run")
    def test_scan_error_status_becomes_warning(self, _pull, mock_dir, _agent):
        repo_dir = Path(self.tmp.name) / "clone"
        (repo_dir / "src").mkdir(parents=True)
        (repo_dir / "src" / "a.py").write_text("x\n", encoding="utf-8")
        mock_dir.return_value = repo_dir
        res = gui.act("/api/deep-scan", {"repo": "o/r", "engine": "eng"})
        self.assertEqual(res["findings"], [])
        self.assertTrue(any("bad" in w for w in res["warnings"]))

    @patch("auto_dev_crew.keys.get_key_effective_roles",
           side_effect=lambda v: ["scan"] if v == "SCAN_KEY" else ["coder"])
    def test_scan_engines_filter(self, _roles):
        self.assertEqual(gui.deep_scan_engines(CFG), ["eng"])


if __name__ == "__main__":
    unittest.main()

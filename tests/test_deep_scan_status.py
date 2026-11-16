import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_dev_crew import deep_scan, gui

FINDING = deep_scan.Finding("bug", "Tree export", "a.py", 3, "ev line", "fix it", severity="high")


def _issue(number, state="OPEN", labels=(), body=None, url=None):
    return {"number": number, "state": state, "url": url or f"https://github.com/o/r/issues/{number}",
            "labels": [{"name": n} for n in labels],
            "body": body if body is not None else deep_scan.render_issue_body(FINDING)}


class TestFindingIssueState(unittest.TestCase):
    def test_no_issue_is_unknown(self):
        self.assertEqual(deep_scan.finding_issue_state(None), "unknown")

    def test_closed_issue_is_closed(self):
        self.assertEqual(deep_scan.finding_issue_state(_issue(1, state="CLOSED")), "closed")

    def test_closed_wins_over_stuck_labels(self):
        self.assertEqual(deep_scan.finding_issue_state(_issue(1, "CLOSED", ["ai-failed"])), "closed")

    def test_open_with_failed_label_is_stuck(self):
        self.assertEqual(deep_scan.finding_issue_state(_issue(1, labels=["ai-task", "ai-needs-human"])), "stuck")

    def test_plain_open_issue_is_open(self):
        self.assertEqual(deep_scan.finding_issue_state(_issue(1, labels=["ai-task"])), "open")


class TestWithIssueState(unittest.TestCase):
    def _run(self, *items):
        return {"repo": "o/r", "run_id": "r1", "findings": list(items)}

    def _item(self, id_, status="filed", **extra):
        base = {k: getattr(FINDING, k) for k in deep_scan._FINDING_FIELDS}
        base.update(id=id_, status=status, severity="high", **extra)
        return base

    def test_filed_finding_gets_state_matched_by_marker(self):
        other = deep_scan.Finding("bug", "Other", "b.py", 9, "x", "y")
        index = [_issue(7, state="CLOSED", body=deep_scan.render_issue_body(other)),
                 _issue(8, state="CLOSED")]
        data = deep_scan.with_issue_state(self._run(self._item("r1-0")), index)
        item = data["findings"][0]
        self.assertEqual(item["issue_state"], "closed")
        self.assertEqual(item["issue_number"], 8)
        self.assertTrue(item["issue_url"].endswith("/issues/8"))

    def test_filed_finding_without_issue_is_unknown(self):
        data = deep_scan.with_issue_state(self._run(self._item("r1-0")), [])
        self.assertEqual(data["findings"][0]["issue_state"], "unknown")

    def test_new_and_dismissed_findings_are_untouched(self):
        data = deep_scan.with_issue_state(
            self._run(self._item("r1-0", status="new"), self._item("r1-1", status="dismissed")), [_issue(8)])
        for item in data["findings"]:
            self.assertNotIn("issue_state", item)

    def test_none_run_is_returned_as_none(self):
        self.assertIsNone(deep_scan.with_issue_state(None, []))


class TestIssueIndex(unittest.TestCase):
    def setUp(self):
        deep_scan.forget_issue_index("o/r", "ai-task")
        self.addCleanup(deep_scan.forget_issue_index, "o/r", "ai-task")

    def test_fetch_asks_gh_for_all_states_and_fields(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            return json.dumps([_issue(1)])

        index = deep_scan.fetch_issue_index("o/r", "ai-task", run=fake_run)
        self.assertEqual(len(index), 1)
        args = calls[0]
        self.assertIn("--state", args)
        self.assertEqual(args[args.index("--state") + 1], "all")
        self.assertIn("number,state,body,url,labels", args)

    def test_cache_avoids_second_gh_call_until_forgotten(self):
        calls = []

        def fake_run(*args):
            calls.append(args)
            return "[]"

        deep_scan.cached_issue_index("o/r", "ai-task", run=fake_run)
        deep_scan.cached_issue_index("o/r", "ai-task", run=fake_run)
        self.assertEqual(len(calls), 1)
        deep_scan.forget_issue_index("o/r", "ai-task")
        deep_scan.cached_issue_index("o/r", "ai-task", run=fake_run)
        self.assertEqual(len(calls), 2)


class TestSetStatusStoresUrl(unittest.TestCase):
    def test_issue_url_is_saved_with_filed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            deep_scan.save_run(state, "o/r", [FINDING], "run1")
            deep_scan.set_status(state, "o/r", "run1-0", "filed", issue_url="https://github.com/o/r/issues/9")
            item = deep_scan.load_run(state, "o/r")["findings"][0]
            self.assertEqual(item["status"], "filed")
            self.assertEqual(item["issue_url"], "https://github.com/o/r/issues/9")

    def test_status_without_url_keeps_existing_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            deep_scan.save_run(state, "o/r", [FINDING], "run1")
            deep_scan.set_status(state, "o/r", "run1-0", "filed", issue_url="https://github.com/o/r/issues/9")
            deep_scan.set_status(state, "o/r", "run1-0", "dismissed")
            self.assertEqual(deep_scan.load_run(state, "o/r")["findings"][0]["issue_url"],
                             "https://github.com/o/r/issues/9")


class TestGuiView(unittest.TestCase):
    CFG = {"labels": {"task": "ai-task"}}

    def test_github_outage_returns_saved_run_with_error(self):
        data = {"repo": "o/r", "findings": [{"status": "filed", "id": "r1-0"}]}
        with patch("auto_dev_crew.deep_scan.cached_issue_index", side_effect=RuntimeError("no network")):
            out = gui._deep_scan_view("o/r", self.CFG, data)
        self.assertIn("issue_state_error", out)
        self.assertNotIn("issue_state", out["findings"][0])

    def test_no_filed_findings_skips_github(self):
        data = {"repo": "o/r", "findings": [{"status": "new", "id": "r1-0"}]}
        with patch("auto_dev_crew.deep_scan.cached_issue_index") as idx:
            gui._deep_scan_view("o/r", self.CFG, data)
        idx.assert_not_called()


if __name__ == "__main__":
    unittest.main()

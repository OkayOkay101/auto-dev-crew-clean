import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew import sentinel_tracker
from auto_dev_crew.slots import SlotRegistry
from auto_dev_crew import runner


class TestSentinelTracker(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "scratch_sentinel"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.issues_file = self.test_dir / "sentinel_issues.json"
        self.registry = SlotRegistry(state_dir=self.test_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_record_and_load_sentinel_issues(self):
        # 1. Record an open issue
        issue1 = {
            "id": "sec-001",
            "title": "File size limit bypass",
            "severity": "Medium",
            "status": "open",
            "pr": None,
            "branch": "ai/sentinel-test-1"
        }
        sentinel_tracker.record_sentinel_issue(issue1, path=self.issues_file)

        issues = sentinel_tracker.load_sentinel_issues(path=self.issues_file)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["id"], "sec-001")
        self.assertEqual(issues[0]["status"], "open")

        # 2. Update issue to resolved
        sentinel_tracker.resolve_sentinel_issue("sec-001", pr=122, path=self.issues_file)
        issues_updated = sentinel_tracker.load_sentinel_issues(path=self.issues_file)
        self.assertEqual(len(issues_updated), 1)
        self.assertEqual(issues_updated[0]["status"], "resolved")
        self.assertEqual(issues_updated[0]["pr"], 122)

    def test_debounce_check_recent_vs_old_commit(self):
        from unittest import mock

        # Case 1: Fresh commit 10 minutes ago -> should NOT be debounced (returns False)
        ten_mins_ago = time.time() - 600
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout=str(int(ten_mins_ago)))
            debounced = sentinel_tracker.is_sentinel_debounced(Path("."), debounce_hours=1.0)
            self.assertFalse(debounced)

        # Case 2: Old commit 2 hours ago -> should be debounced (returns True)
        two_hours_ago = time.time() - 7200
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stdout=str(int(two_hours_ago)))
            debounced = sentinel_tracker.is_sentinel_debounced(Path("."), debounce_hours=1.0)
            self.assertTrue(debounced)

    def test_runner_skips_sentinel_when_not_debounced(self):
        from unittest import mock

        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {
                "enabled": ["sentinel", "bolt"],
                "sentinel": {"debounce_hours": 1.0}
            },
            "parallel": {"slots": 3}
        }

        # Mock is_sentinel_debounced to return False (not debounced yet)
        with mock.patch("auto_dev_crew.sentinel_tracker.is_sentinel_debounced", return_value=False):
            job = runner.pick_task_for_slot(
                slot_id=2,
                cfg=cfg,
                history=[],
                issues=[],
                registry=self.registry
            )
            # Sentinel was first candidate, but skipped because of debounce -> bolt is chosen!
            self.assertIsNotNone(job)
            self.assertEqual(job.kind, "persona")
            self.assertEqual(job.key, "bolt")


# ---------------------------------------------------------------- MED-05: debounce uses the target repo

def _iso_ago(seconds: float) -> str:
    import datetime as dt
    ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_debounce_uses_target_repo_commit_not_cwd(tmp_path, monkeypatch):
    """Sentinel debounce must look at the target repo via gh, never at the cwd git repo."""
    from unittest import mock

    seen = []

    def fetcher(repo_name):
        seen.append(repo_name)
        return _iso_ago(600)  # target repo committed 10 minutes ago

    with mock.patch("subprocess.run") as local_git:
        allowed = sentinel_tracker.is_sentinel_debounced(
            debounce_hours=1.0, repo_name="example-owner/target", fetch_commit_date=fetcher)
    assert allowed is False
    assert seen == ["example-owner/target"]
    local_git.assert_not_called()


def test_debounce_allows_when_target_commit_is_old(tmp_path):
    fetcher = lambda repo_name: _iso_ago(7200)
    assert sentinel_tracker.is_sentinel_debounced(
        debounce_hours=1.0, repo_name="o/r", fetch_commit_date=fetcher) is True


def test_debounce_fails_open_when_gh_fails(tmp_path):
    def boom(repo_name):
        raise RuntimeError("gh down")
    assert sentinel_tracker.is_sentinel_debounced(
        debounce_hours=1.0, repo_name="o/r", fetch_commit_date=boom) is True


def test_pick_task_checks_target_repo_via_gh(fake_gh, tmp_path):
    from auto_dev_crew.slots import SlotRegistry as _Reg
    cfg = {
        "owner": "example-owner",
        "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
        "repos": [{"name": "example-owner/target", "base": "main"}],
        "personas": {"enabled": ["sentinel"], "sentinel": {"debounce_hours": 1.0}},
        "parallel": {"slots": 3},
    }
    fake_gh.on(("api",), _iso_ago(600))
    registry = _Reg(state_dir=tmp_path / "reg")

    job = runner.pick_task_for_slot(slot_id=2, cfg=cfg, history=[], issues=[],
                                    registry=registry, repo_name="example-owner/target")

    assert job is None  # committed 10 min ago -> debounced
    assert fake_gh.calls_with("api", "repos/example-owner/target/commits/main")


if __name__ == "__main__":
    unittest.main()

import sys
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_dev_crew import runner
from auto_dev_crew.slots import SlotRegistry


class TestParallelRunner(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "scratch_runner"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.registry = SlotRegistry(state_dir=self.test_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_next_task_for_slot_1_only_issues(self):
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {
                "enabled": ["bolt", "sentinel"],
                "sentinel": {"debounce_hours": 0.0}
            },
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        job = runner.pick_task_for_slot(
            slot_id=1,
            cfg=cfg,
            history=[],
            issues=[],
            registry=self.registry
        )
        self.assertIsNone(job)

    def test_next_task_for_slot_2_picks_persona(self):
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {
                "enabled": ["bolt", "sentinel"],
                "sentinel": {"debounce_hours": 0.0}
            },
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        job = runner.pick_task_for_slot(
            slot_id=2,
            cfg=cfg,
            history=[],
            issues=[],
            registry=self.registry
        )
        self.assertIsNotNone(job)
        self.assertEqual(job.kind, "persona")
        self.assertEqual(job.key, "bolt")

    def test_persona_deduplication_between_slots(self):
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {
                "enabled": ["bolt", "sentinel"],
                "sentinel": {"debounce_hours": 0.0}
            },
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        self.registry.register_slot(2, "persona", "bolt", "ai/bolt-1", [])
        
        job = runner.pick_task_for_slot(
            slot_id=3,
            cfg=cfg,
            history=[],
            issues=[],
            registry=self.registry
        )
        self.assertIsNotNone(job)
        self.assertEqual(job.kind, "persona")
        self.assertEqual(job.key, "sentinel")

    def test_issue_with_open_pr_in_history_is_not_picked_again(self):
        # Live E2E (Phase 3 step 6): after PR #7 for issue 5 was opened (review-all, not merged),
        # slot 1 claimed issue 5 again 20 s later because only the ai-working/ai-failed labels
        # were checked. An issue whose PR is still OPEN must not be re-queued.
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {"enabled": ["bolt"]},
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        history = [
            {"repo": "o/r", "kind": "issue", "key": "5", "state": "OPEN", "pr": 7},
            {"repo": "other/repo", "kind": "issue", "key": "6", "state": "OPEN", "pr": 3},
        ]
        issues = [runner.Job("issue", "5", "add mul", ""), runner.Job("issue", "6", "add div", "")]

        job1 = runner.pick_task_for_slot(slot_id=1, cfg=cfg, history=history, issues=issues,
                                         registry=self.registry, repo_name="o/r")
        self.assertEqual((job1.kind, job1.key), ("issue", "6"))

        only5 = [runner.Job("issue", "5", "add mul", "")]
        job2 = runner.pick_task_for_slot(slot_id=2, cfg=cfg, history=history, issues=only5,
                                         registry=self.registry, repo_name="o/r", issues_only=True)
        self.assertIsNone(job2)

    def test_overflow_issue_pickup_by_slot_2(self):
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {"enabled": ["bolt"]},
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        issues = [
            runner.Job("issue", "10", "Issue 10", "body 10"),
            runner.Job("issue", "11", "Issue 11", "body 11")
        ]
        self.registry.register_slot(1, "issue", "10", "ai/issue-10", [])

        job = runner.pick_task_for_slot(
            slot_id=2,
            cfg=cfg,
            history=[],
            issues=issues,
            registry=self.registry
        )
        self.assertIsNotNone(job)
        self.assertEqual(job.kind, "issue")
        self.assertEqual(job.key, "11")

    def test_concurrent_claim_task_prevents_duplicate_personas(self):
        cfg = {
            "owner": "example-owner",
            "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
            "personas": {"enabled": ["bolt", "sentinel", "palette"]},
            "parallel": {"slots": 3, "reserve_for_issues": 1}
        }
        claimed_jobs = {}
        barrier = threading.Barrier(2)

        def worker(slot_id):
            barrier.wait()
            job = runner.claim_task_for_slot(
                slot_id=slot_id,
                cfg=cfg,
                history=[],
                issues=[],
                registry=self.registry
            )
            claimed_jobs[slot_id] = job

        t1 = threading.Thread(target=worker, args=(2,))
        t2 = threading.Thread(target=worker, args=(3,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIsNotNone(claimed_jobs[2])
        self.assertIsNotNone(claimed_jobs[3])
        # Crucial: Slot 2 and Slot 3 must NOT have claimed the same persona!
        self.assertNotEqual(claimed_jobs[2].key, claimed_jobs[3].key)

    @unittest.mock.patch("venv.create")
    def test_slot_venv_isolation(self, mock_create):
        env1 = runner.venv_env("test/mock_repo", slot_id=1)
        env2 = runner.venv_env("test/mock_repo", slot_id=2)
        self.assertIn("slot_1", env1["VIRTUAL_ENV"])
        self.assertIn("slot_2", env2["VIRTUAL_ENV"])
        self.assertNotEqual(env1["VIRTUAL_ENV"], env2["VIRTUAL_ENV"])

    def test_append_history_concurrency(self):
        history_file = self.test_dir / "history.json"
        
        def worker(idx):
            for i in range(5):
                entry = {"repo": "r", "key": f"{idx}_{i}", "state": "DONE"}
                runner.append_history(entry, path=history_file)
                time.sleep(0.005)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        final_history = runner.locked_json_read(history_file, default=[])
        self.assertEqual(len(final_history), 20)



    def test_quiet_standby_and_issue_trigger(self):
        logs = []
        with mock.patch("auto_dev_crew.runner.log", side_effect=lambda msg, slot_id=None: logs.append((slot_id, msg))):
            with mock.patch("auto_dev_crew.runner.paused", return_value=False):
                with mock.patch("auto_dev_crew.runner.refresh_history"):
                    with mock.patch("auto_dev_crew.runner.open_ai_prs", return_value=[]):
                        with mock.patch("auto_dev_crew.runner.get_available_issues", return_value=[]):
                            with mock.patch("auto_dev_crew.runner.claim_task_for_slot", return_value=None):
                                cfg = {"labels": {"pause": "ai-pause", "pr": "ai-pr"}, "parallel": {"slots": 3}}
                                rcfg = {"name": "test/repo"}
                                if hasattr(runner.process_slot, "_idle_slots"):
                                    runner.process_slot._idle_slots.clear()

                                # รอบที่ 1: แจ้งสแตนด์บาย
                                runner.process_slot(1, cfg, rcfg, dry_run=True)
                                self.assertEqual(len(logs), 1)
                                self.assertIn("สแตนด์บาย", logs[0][1])

                                # รอบที่ 2: เงียบ (ไม่ส่งล็อกซ้ำ)
                                runner.process_slot(1, cfg, rcfg, dry_run=True)
                                self.assertEqual(len(logs), 1)

                                # รอบที่ 3: ผู้ใช้เปิด Issue เข้ามา -> แจ้งเริ่มงานทันที
                                with mock.patch("auto_dev_crew.runner.claim_task_for_slot", return_value=runner.Job("issue", "101", "Task", "")):
                                    with mock.patch("auto_dev_crew.runner.execute", return_value="Done"):
                                        runner.process_slot(1, cfg, rcfg, dry_run=True)
                                        self.assertEqual(len(logs), 3)
                                        self.assertIn("พบงานใหม่", logs[1][1])

    def test_resume_pending_skips_already_merged_branch(self):
        cfg = {"merge_mode": "small-only", "labels": {"pr": "ai-pr"}}
        rcfg = {"name": "test/repo"}
        history = [
            {"repo": "test/repo", "branch": "ai/feat-1", "state": "PUSHED"},
            {"repo": "test/repo", "branch": "ai/feat-1", "state": "MERGED", "pr": 100}
        ]
        with mock.patch("auto_dev_crew.runner.finish_pr") as mock_finish, \
             mock.patch("auto_dev_crew.runner.open_ai_prs", return_value=[]):
            resumed = runner.resume_pending(cfg, rcfg, history, slot_id=1)
            self.assertFalse(resumed)
            mock_finish.assert_not_called()

    def test_slot_worker_loop_hot_reloads_config(self):
        import yaml
        cfg_file = self.test_dir / "test_config.yaml"
        initial_cfg = {
            "owner": "example-owner",
            "parallel": {"slots": 3, "poll_interval_seconds": 0.01},
            "repos": [{"name": "test/repo", "version": "1.0"}]
        }
        cfg_file.write_text(yaml.dump(initial_cfg), encoding="utf-8")

        observed_configs = []
        stop_event = threading.Event()

        def fake_process_slot(slot_id, cfg, rcfg, history, dry_run, persona_override=None):
            observed_configs.append(dict(cfg))
            if len(observed_configs) == 1:
                # Update config on disk for next cycle
                new_cfg = {
                    "owner": "example-owner",
                    "parallel": {"slots": 3, "poll_interval_seconds": 0.01},
                    "repos": [{"name": "test/repo", "version": "2.0"}]
                }
                cfg_file.write_text(yaml.dump(new_cfg), encoding="utf-8")
            elif len(observed_configs) >= 2:
                stop_event.set()
            return True

        with mock.patch("auto_dev_crew.runner.process_slot", side_effect=fake_process_slot):
            with mock.patch("auto_dev_crew.runner.load_history", return_value=[]):
                with mock.patch("time.sleep"):
                    runner.slot_worker_loop(
                        slot_id=1,
                        cfg=initial_cfg,
                        rcfg={"name": "test/repo", "version": "1.0"},
                        dry_run=True,
                        loop=True,
                        stop_event=stop_event,
                        config_path=cfg_file
                    )

        self.assertEqual(len(observed_configs), 2)
        self.assertEqual(observed_configs[0]["repos"][0]["version"], "1.0")
        self.assertEqual(observed_configs[1]["repos"][0]["version"], "2.0")

    def test_run_steps_timeout_returns_false(self):
        import subprocess as sp
        timeout_exc = sp.TimeoutExpired(cmd="npm test", timeout=1800)
        with mock.patch("auto_dev_crew.runner.run", side_effect=timeout_exc):
            ok, out = runner.run_steps(["npm test"], cwd=self.test_dir, env={})
        self.assertFalse(ok)
        self.assertIn("npm test", out)
        self.assertIn("timed out", out.lower())

    def test_gh_passes_default_timeout_to_run(self):
        completed = mock.MagicMock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch("auto_dev_crew.runner.run", return_value=completed) as mock_run:
            out = runner.gh("issue", "list")
        self.assertEqual(out, "ok")
        self.assertEqual(mock_run.call_args.kwargs.get("timeout"), runner.GH_TIMEOUT_SECONDS)


# ---------------------------------------------------------------- pytest-style runner tests (MED-06, MED-12, LOW-02, LOW-05)

import pytest  # noqa: E402


def _write_min_config(path):
    import yaml
    path.write_text(yaml.dump({
        "owner": "example-owner",
        "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed", "pr": "ai-pr", "pause": "ai-pause"},
        "parallel": {"slots": 3},
        "personas": {"enabled": ["bolt", "sentinel"]},
        "repos": [{"name": "example-owner/repo-x", "base": "main"}],
    }), encoding="utf-8")
    return path


def test_persona_override_single_slot(tmp_path, monkeypatch):
    """MED-06: --persona must reach only one worker slot, not every slot > 1."""
    monkeypatch.setattr(runner, "clean_work", lambda: None)
    cfg_path = _write_min_config(tmp_path / "config.yaml")
    with mock.patch("auto_dev_crew.runner.slot_worker_loop") as worker:
        runner.main(["--config", str(cfg_path), "--dry-run", "--persona", "bolt"])
    overrides = {c.args[0]: c.args[5] for c in worker.call_args_list}
    assert overrides[1] is None
    assert overrides[2] == "bolt"
    assert overrides[3] is None


def test_worker_survives_repeated_errors(monkeypatch):
    """MED-12: a worker keeps running after repeated errors, backing off up to 15 min."""

    class RecordingStop:
        def __init__(self):
            self.waits = []
            self._set = False

        def is_set(self):
            return self._set

        def wait(self, timeout=None):
            self.waits.append(timeout)
            return self._set

        def set(self):
            self._set = True

    stop = RecordingStop()
    calls = {"n": 0}

    def fake_process_slot(*a, **k):
        calls["n"] += 1
        if calls["n"] == 7:
            stop.set()
            return True
        raise RuntimeError(f"boom {calls['n']}")

    monkeypatch.setattr(runner, "process_slot", fake_process_slot)
    monkeypatch.setattr(runner, "load_history", lambda *a, **k: [])
    runner.slot_worker_loop(slot_id=2, cfg={"parallel": {}}, rcfg={"name": "o/r"},
                            dry_run=True, loop=True, stop_event=stop)

    assert calls["n"] == 7, "worker died after a few errors instead of retrying"
    assert stop.waits[:6] == [60, 120, 240, 480, 900, 900]


def test_process_slot_handles_empty_exception_message(fake_gh, monkeypatch):
    """MED-12: an exception with an empty message (e.g. StopIteration) must not raise IndexError."""
    monkeypatch.setattr(runner, "execute", mock.Mock(side_effect=StopIteration()))
    fake_gh.on(("issue", "create"), "https://github.com/example-owner/repo-x/issues/3")
    cfg = {"labels": {"working": "ai-working"}, "repos": []}
    rcfg = {"name": "example-owner/repo-x"}

    assert runner.process_slot(2, cfg, rcfg, dry_run=False, persona_override="bolt") is True
    comments = fake_gh.calls_with("issue", "comment")
    assert comments, "failure was not reported"
    assert any("ล้มเหลว: StopIteration" in str(c) for c in comments)


def test_resume_pending_survives_report_failure(monkeypatch):
    """MED-12: a failing report() must not escape the slot loop."""
    cfg = {"merge_mode": "merge-all", "labels": {"pr": "ai-pr"}}
    rcfg = {"name": "example-owner/repo-x"}
    history = [{"repo": "example-owner/repo-x", "branch": "ai/feat-2", "state": "PUSHED"}]
    monkeypatch.setattr(runner, "finish_pr", lambda *a, **k: "line")
    monkeypatch.setattr(runner, "report", mock.Mock(side_effect=RuntimeError("gh outage")))
    assert runner.resume_pending(cfg, rcfg, history, slot_id=1) is True


def test_main_returns_3_when_every_slot_hits_quota(tmp_path, monkeypatch):
    """LOW-02: exit code 3 tells AutoPilot that quota ran out on every slot."""
    from auto_dev_crew.runner import QuotaExhausted
    monkeypatch.setattr(runner, "clean_work", lambda: None)
    monkeypatch.setattr(runner, "process_slot", mock.Mock(side_effect=QuotaExhausted("429")))
    cfg_path = _write_min_config(tmp_path / "config.yaml")
    assert runner.main(["--config", str(cfg_path), "--dry-run"]) == 3


def test_main_returns_0_when_quota_hit_on_only_some_slots(tmp_path, monkeypatch):
    from auto_dev_crew.runner import QuotaExhausted
    monkeypatch.setattr(runner, "clean_work", lambda: None)

    def proc(slot_id, *a, **k):
        if slot_id == 1:
            raise QuotaExhausted("429")
        return False

    monkeypatch.setattr(runner, "process_slot", proc)
    cfg_path = _write_min_config(tmp_path / "config.yaml")
    assert runner.main(["--config", str(cfg_path), "--dry-run"]) == 0


def test_refresh_history_empty_output(fake_gh):
    """LOW-05: gh pr view with empty output must not crash refresh_history."""
    fake_gh.on(("pr", "view"), "")
    history = [{"repo": "example-owner/repo-x", "pr": 5, "state": "OPEN"}]
    runner.refresh_history("example-owner/repo-x", history)
    assert history[0]["state"] == "OPEN"


def test_get_available_issues_ghost_author(fake_gh):
    """LOW-05: a deleted (ghost) author is None in gh output; skip the issue instead of crashing."""
    fake_gh.on(("issue", "list"), [{"number": 1, "title": "t", "body": "b", "author": None, "labels": []}])
    cfg = {"owner": "example-owner", "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"}}
    assert runner.get_available_issues("example-owner/repo-x", cfg) == []


def test_repo_cfg_missing_raises_clear_error():
    """LOW-05: unknown repo name gives a ValueError, not a bare StopIteration."""
    with pytest.raises(ValueError):
        runner.repo_cfg({"repos": [{"name": "a/b"}]}, "x/y")


def test_persona_rotation_not_skipped_by_own_slot(monkeypatch):
    """MED-04: the repo loop's claim must not reserve a persona that the fallback then skips.

    History says sentinel ran last, so bolt is next. With no issues the slot must run bolt,
    not sentinel (the repo-loop claim used to register bolt on the slot and block it).
    """
    rcfg = {"name": "example-owner/repo-x"}
    cfg = {
        "labels": {"task": "ai-task", "working": "ai-working", "failed": "ai-failed"},
        "personas": {"enabled": ["bolt", "sentinel"], "sentinel": {"debounce_hours": 0.0}},
        "parallel": {"slots": 3},
        "repos": [rcfg],
    }
    history = [{"repo": rcfg["name"], "kind": "persona", "key": "sentinel", "state": "DONE",
                "date": "20260101-0000"}]
    executed = []
    monkeypatch.setattr(runner, "load_history", lambda *a, **k: list(history))
    monkeypatch.setattr(runner, "paused", lambda *a, **k: False)
    monkeypatch.setattr(runner, "refresh_history", lambda *a, **k: None)
    monkeypatch.setattr(runner, "get_available_issues", lambda *a, **k: [])
    monkeypatch.setattr(runner, "log", lambda *a, **k: None)
    monkeypatch.setattr(runner, "execute", lambda job, *a, **k: executed.append(job) or "line")

    assert runner.process_slot(2, cfg, rcfg, dry_run=True) is True
    assert [j.key for j in executed] == ["bolt"]


def test_pick_task_issues_only_never_returns_persona(tmp_path):
    """MED-04: issues_only=True makes the repo-loop claim pick issues only, never a persona."""
    registry = SlotRegistry(tmp_path)
    cfg = {"personas": {"enabled": ["bolt"]}, "labels": {}}
    assert runner.pick_task_for_slot(2, cfg, [], [], registry, issues_only=True) is None
    assert runner.claim_task_for_slot(2, cfg, [], [], registry, issues_only=True) is None
    assert registry.get_active_jobs() == {}


if __name__ == "__main__":
    unittest.main()


def test_hot_reload_keeps_cli_repo_not_in_config(tmp_path, monkeypatch):
    """Phase 3 live E2E: `--repo X --slot N` with X absent from config.yaml must stay on X.

    The per-cycle config hot-reload used to drop the dynamic repo and fall back to repos[0],
    so a sandbox run silently scanned the first configured (production) repo instead.
    """
    cfg_path = _write_min_config(tmp_path / "config.yaml")  # repos: [example-owner/repo-x]
    seen = []

    def fake_process_slot(slot_id, cfg, rcfg, history, dry_run, persona_override=None, repo_filter=None):
        seen.append((rcfg["name"], [r["name"] for r in cfg.get("repos", [])], repo_filter))
        return False

    monkeypatch.setattr(runner, "process_slot", fake_process_slot)
    monkeypatch.setattr(runner, "load_history", lambda *a, **k: [])
    dyn = {"name": "example-owner/sandbox", "base": "main"}
    runner.slot_worker_loop(slot_id=1, cfg={"repos": [dyn]}, rcfg=dyn, dry_run=True, loop=False,
                            config_path=cfg_path, repo_filter="example-owner/sandbox")

    rcfg_name, cfg_repo_names, repo_filter = seen[0]
    assert rcfg_name == "example-owner/sandbox"
    assert "example-owner/sandbox" in cfg_repo_names
    assert repo_filter == "example-owner/sandbox"

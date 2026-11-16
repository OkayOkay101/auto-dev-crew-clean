"""Regression: a scan call on a single-concurrency engine (the lock branch) must keep role="scan".

Before the fix the locked branch dropped `role`, so the scan reply was cut at the 2,500-char default
(JSON broke) and the scan read-only config was skipped.
"""
from pathlib import Path

from auto_dev_crew import runner


def test_locked_engine_call_keeps_scan_role(tmp_path, monkeypatch):
    seen = {}

    def fake_execute(eng, prompt, cwd, active_key=None, *, role=None):
        seen["role"] = role
        return {"status": "SUCCESS", "response": "[]"}

    monkeypatch.setattr(runner, "_is_single_concurrency", lambda eng: True)
    monkeypatch.setattr(runner, "_execute_single_engine", fake_execute)
    monkeypatch.setattr(runner, "STATE", tmp_path)
    monkeypatch.setattr(runner, "key_engine_name", lambda eng: "lock-test-engine")

    runner.call_single_engine({"name": "lock-test-engine"}, "p", Path(tmp_path), None, role="scan")
    assert seen["role"] == "scan"

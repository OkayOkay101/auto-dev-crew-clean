"""ด่าน 1 (ยืนยันบั๊ก) ต้องรันทุกรอบ รวมถึง issue ที่มีประวัติซ่อมแล้ว (auto_dev_crew/runner.py)."""
from auto_dev_crew import runner


def test_bug_check_runs_on_first_attempt():
    assert runner._bug_check_enabled({}, dry_run=False) is True


def test_bug_check_runs_on_repair_rounds_too():
    # ไม่มีเงื่อนไขตามจำนวนรอบซ่อมแล้ว: issue ที่ซ่อมไปแล้วก็ต้องถูกตรวจซ้ำกับ base ปัจจุบัน
    cfg = {"evaluation": {"enabled": True}}
    assert runner._bug_check_enabled(cfg, dry_run=False) is True


def test_bug_check_skipped_in_dry_run():
    assert runner._bug_check_enabled({}, dry_run=True) is False


def test_bug_check_skipped_when_evaluation_disabled():
    assert runner._bug_check_enabled({"evaluation": {"enabled": False}}, dry_run=False) is False

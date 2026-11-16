from auto_dev_crew.pr_body import build_pr_body
from auto_dev_crew.redact import PLACEHOLDER

FAKE_KEY = "sk-" + "a" * 40


def _body(**kw):
    args = dict(job_title="T", job_ref="12", persona="", summary="สรุป", files_changed=["a.py", "b.py"],
                test_cmd="pytest -q", test_passed=True, eval_score=8.5)
    args.update(kw)
    return build_pr_body(**args)


def test_has_sections():
    b = _body()
    assert "## Summary" in b and "## Changes" in b and "## Test Checklist" in b
    assert "- a.py" in b and "- b.py" in b


def test_closes_numeric_ref():
    assert "Closes #12" in _body(job_ref="12")


def test_closes_cross_repo_ref_verbatim():
    b = _body(job_ref="owner/repo#12")
    assert "Closes owner/repo#12" in b and "Closes #12" not in b


def test_persona_line_when_no_ref():
    b = _body(job_ref=None, persona="bolt")
    assert "ตัวละคร: bolt" in b and "Closes" not in b


def test_checklist_pass_and_fail():
    assert "- [x] pytest -q" in _body(test_passed=True)
    assert "- [ ] pytest -q" in _body(test_passed=False)


def test_eval_score_na_and_lines():
    b = _body(eval_score=None, lines=7)
    assert "N/A" in b and "แก้ 7 บรรทัด" in b


def test_empty_files():
    assert "## Changes" in _body(files_changed=[])


def test_secret_redacted():
    b = _body(summary=f"leak {FAKE_KEY} x", test_cmd=f"run {FAKE_KEY}")
    assert FAKE_KEY not in b and PLACEHOLDER in b


def test_no_test_steps_renders_unticked_box():
    b = _body(test_cmd="(no test steps)", test_passed=bool([]))
    assert "- [ ] (no test steps)" in b


def test_manual_check_section_flags_web_files_for_human_review():
    b = _body(files_changed=["index.html", "core.js"])
    assert "## วิธีตรวจด้วยมือ" in b
    assert "แตะหน้าเว็บ (index.html" in b
    assert "ผู้รีวิวเป็นคน: ยังไม่มี" in b


def test_manual_check_section_for_non_web_change():
    b = _body(files_changed=["auto_dev_crew/pr_body.py"])
    assert "ไม่มีไฟล์หน้าเว็บที่เปลี่ยน" in b
    assert "แตะหน้าเว็บ" not in b

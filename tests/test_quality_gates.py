"""ด่านตรวจคุณภาพ (auto_dev_crew/quality_gates.py) และการเชื่อมต่อใน runner.

ครอบคลุม: การหาไฟล์ที่ issue อ้าง, ด่าน 3 (รอบซ่อมต้องแตะไฟล์ production ที่ issue ระบุ),
ด่าน 2 (judge เห็นไฟล์เต็ม), ด่าน 1 (ยืนยันบั๊กก่อน coder; ผลลบ → ai-needs-human).
"""
from __future__ import annotations

from pathlib import Path

from auto_dev_crew import quality_gates as qg
from auto_dev_crew import runner
from auto_dev_crew.runner import Job


# ---- การหาไฟล์และแยกไฟล์ test ---------------------------------------------------------------

def test_named_files_skips_tests_and_dedupes():
    text = "แก้ netrunner_leveling.js (ดู tests/test_netrunner_leveling.py และ src/app.py) netrunner_leveling.js"
    assert qg.named_files(text) == ["netrunner_leveling.js", "src/app.py"]


def test_is_test_path_variants():
    for p in ["tests/x.py", "test_a.py", "pkg/test_b.py", "a.test.js", "a.spec.ts", "test-runner.js", "x_test.py"]:
        assert qg.is_test_path(p), p
    for p in ["netrunner_leveling.js", "src/testing_utils.py", "app/main.py"]:
        assert not qg.is_test_path(p), p


def test_existing_named_files_only_keeps_real_files(tmp_path: Path):
    (tmp_path / "netrunner_leveling.js").write_text("x", encoding="utf-8")
    assert qg.existing_named_files(tmp_path, "see netrunner_leveling.js and ghost.js") == ["netrunner_leveling.js"]


# ---- ด่าน 3: รอบซ่อมต้องแตะไฟล์ production ที่ issue ระบุ -----------------------------------

def test_repair_gate_blocks_test_only_diff():
    assert qg.repair_gate_violation(["netrunner_leveling.js"], ["tests/test_netrunner_leveling.py"]) is not None


def test_repair_gate_passes_when_named_file_changed():
    assert qg.repair_gate_violation(["netrunner_leveling.js"],
                                    ["netrunner_leveling.js", "tests/test_x.py"]) is None


def test_repair_gate_blocks_when_only_other_production_file_changed():
    msg = qg.repair_gate_violation(["netrunner_leveling.js"], ["other.js"])
    assert msg is not None and "netrunner_leveling.js" in msg


def test_repair_gate_inactive_without_named_files():
    assert qg.repair_gate_violation([], ["tests/only.py"]) is None


# ---- ด่าน 2: judge เห็นไฟล์ production เต็ม ------------------------------------------------

def test_full_files_block_includes_numbered_production_file_not_tests(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.js").write_text("const x = 1;\nconst y = 2;\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("SHOULD_NOT_APPEAR\n", encoding="utf-8")
    block = qg.full_files_block(tmp_path, ["src/a.js", "tests/t.py"])
    assert "=== FILE: src/a.js ===" in block
    assert "2: const y = 2;" in block
    assert "SHOULD_NOT_APPEAR" not in block


def test_full_files_block_truncates_large_files(tmp_path: Path):
    (tmp_path / "big.js").write_text("x\n" * 50000, encoding="utf-8")
    block = qg.full_files_block(tmp_path, ["big.js"], limit=1000)
    assert len(block) < 2000
    assert "ตัดทอน" in block


def test_evaluator_prompt_declares_full_files_placeholder():
    tmpl = (Path(qg.__file__).resolve().parent.parent / "prompts" / "evaluator.md").read_text(encoding="utf-8")
    assert "{{full_files}}" in tmpl
    assert "Full Production Files" in tmpl


# ---- ด่าน 1: ยืนยันบั๊กก่อน coder -----------------------------------------------------------

def test_parse_bug_check_accepts_json_block():
    raw = 'เหตุผล...\n```json\n{"bug_exists": false, "reason": "line 3 already rejects 12junk"}\n```'
    assert qg.parse_bug_check(raw) == {"bug_exists": False, "reason": "line 3 already rejects 12junk"}


def test_parse_bug_check_rejects_non_bool_or_garbage():
    assert qg.parse_bug_check('{"bug_exists": "no"}') is None
    assert qg.parse_bug_check("not json at all") is None
    assert qg.parse_bug_check(None) is None  # type: ignore[arg-type]


def _issue_job() -> Job:
    return Job(kind="issue", key="131", title="Stored EXP accepts malformed numeric strings",
               body="ดู netrunner_leveling.js ฟังก์ชัน parseStoredExp")


def test_confirm_bug_exists_skips_when_no_named_file(tmp_path: Path, monkeypatch):
    called = []
    monkeypatch.setattr(runner, "call_agent", lambda *a, **k: called.append(1) or {})
    assert runner._confirm_bug_exists(_issue_job(), {}, tmp_path, None) is None
    assert called == []  # ไม่มีไฟล์ให้ตรวจ → ไม่เรียก judge


def test_confirm_bug_exists_returns_negative_verdict(tmp_path: Path, monkeypatch):
    (tmp_path / "netrunner_leveling.js").write_text("function parseStoredExp(v){return /^\\d+$/.test(v)}\n",
                                                    encoding="utf-8")
    seen = {}

    def fake_agent(cfg, prompt, cwd, slot_id=None, role="coder", **kw):
        seen["prompt"], seen["role"] = prompt, role
        return {"status": "SUCCESS", "response": '{"bug_exists": false, "reason": "regex rejects 12junk"}'}

    monkeypatch.setattr(runner, "call_agent", fake_agent)
    verdict = runner._confirm_bug_exists(_issue_job(), {}, tmp_path, None)
    assert verdict == {"bug_exists": False, "reason": "regex rejects 12junk"}
    assert seen["role"] == "judge"
    assert "1: function parseStoredExp" in seen["prompt"]  # judge เห็นไฟล์เต็มพร้อมเลขบรรทัด


def test_confirm_bug_exists_fails_open_on_error(tmp_path: Path, monkeypatch):
    (tmp_path / "netrunner_leveling.js").write_text("x\n", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(runner, "call_agent", boom)
    assert runner._confirm_bug_exists(_issue_job(), {}, tmp_path, None) is None


def test_stop_no_bug_labels_needs_human_and_records_history(monkeypatch):
    calls, history = [], []
    monkeypatch.setattr(runner, "gh", lambda *a, **k: calls.append(a) or "")
    monkeypatch.setattr(runner, "append_history", lambda entry, path=None: history.append(entry))
    labels = {"working": "ai-working", "needs_human": "ai-needs-human"}
    msg = runner._stop_no_bug(_issue_job(), labels, "o/r", "o/r", "20261111-1200", "regex rejects 12junk")
    assert "ไม่พบบั๊ก" in msg
    edit = [c for c in calls if c[0] == "issue" and c[1] == "edit"]
    assert edit and "ai-needs-human" in edit[0] and "ai-working" in edit[0]
    assert history[0]["state"] == "NO_BUG"


def test_repro_tests_recorded_in_pr_body():
    from auto_dev_crew.pr_body import build_pr_body
    body = build_pr_body("t", "131", "", "s", ["a.js"], "npm test", True, 0.9,
                         repro_tests=["tests/test_a.py"])
    assert "## Repro" in body and "tests/test_a.py" in body
    assert "## Repro" not in build_pr_body("t", "131", "", "s", ["a.js"], "npm test", True, 0.9)


# ---- ด่าน 1: judge เห็นเฉพาะช่วงรอบบรรทัดที่ issue อ้าง ------------------------------------------

def _numbered_file(tmp_path: Path, name: str, n: int) -> None:
    (tmp_path / name).write_text("".join(f"L{i}\n" for i in range(1, n + 1)), encoding="utf-8")


def test_line_refs_parses_single_line_and_range():
    text = "ดู index.html:1961 และ index.html:100-120 กับ other.js:5"
    assert qg.line_refs(text, "index.html") == [(1961, 1961), (100, 120)]
    assert qg.line_refs(text, "other.js") == [(5, 5)]
    assert qg.line_refs(text, "ghost.js") == []


def test_read_files_block_sends_only_window_around_cited_line(tmp_path: Path):
    _numbered_file(tmp_path, "index.html", 3000)
    block = qg.read_files_block(tmp_path, ["index.html"], focus="แก้ index.html:1961 ผิด")
    # 1961 ±60 = บรรทัด 1901–2021 พร้อมเลขบรรทัดเดิม
    assert "1961: L1961" in block
    assert "1901: L1901" in block and "2021: L2021" in block
    assert "L1900" not in block and "L2022" not in block and "L1000" not in block
    assert "[ข้าม บรรทัด 1–1900]" in block
    assert "[ข้าม บรรทัด 2022–3000]" in block
    assert len(block) < 5000  # ไม่ใช่ไฟล์เต็ม 3000 บรรทัด


def test_read_files_block_merges_overlapping_windows_and_marks_gaps(tmp_path: Path):
    _numbered_file(tmp_path, "a.js", 400)
    block = qg.read_files_block(tmp_path, ["a.js"], focus="a.js:100 และ a.js:130 กับ a.js:300")
    # 100±60=40–160, 130±60=70–190 → รวมเป็น 40–190; 300±60=240–360
    assert "[ข้าม บรรทัด 1–39]" in block
    assert "40: L40" in block and "190: L190" in block
    assert "[ข้าม บรรทัด 191–239]" in block
    assert "240: L240" in block and "360: L360" in block
    assert "[ข้าม บรรทัด 361–400]" in block
    assert block.count("[ข้าม") == 3


def test_read_files_block_without_line_refs_keeps_old_behavior(tmp_path: Path):
    (tmp_path / "a.js").write_text("const x = 1;\nconst y = 2;\n", encoding="utf-8")
    assert qg.read_files_block(tmp_path, ["a.js"], focus="ดู a.js ฟังก์ชัน parse") == \
        qg.read_files_block(tmp_path, ["a.js"])
    assert qg.read_files_block(tmp_path, ["a.js"]) == "=== FILE: a.js ===\n1: const x = 1;\n2: const y = 2;\n"


def test_read_files_block_falls_back_when_cited_line_outside_file(tmp_path: Path):
    (tmp_path / "a.js").write_text("x\ny\n", encoding="utf-8")
    assert qg.read_files_block(tmp_path, ["a.js"], focus="a.js:999") == "=== FILE: a.js ===\n1: x\n2: y\n"


def test_bug_check_prompt_notes_only_when_block_is_cut():
    cut = qg.bug_check_prompt("t", "b", "=== FILE: a.js ===\n[ข้าม บรรทัด 1–9]\n")
    whole = qg.bug_check_prompt("t", "b", "=== FILE: a.js ===\n1: x\n")
    assert "ถ้าบรรทัดที่ issue อ้างไม่อยู่ในช่วงที่แสดง" in cut
    assert "ถ้าบรรทัดที่ issue อ้างไม่อยู่ในช่วงที่แสดง" not in whole


def test_confirm_bug_exists_judge_sees_only_cited_window(tmp_path: Path, monkeypatch):
    _numbered_file(tmp_path, "netrunner_leveling.js", 3000)
    job = Job(kind="issue", key="150", title="Off by one near end",
              body="พังที่ netrunner_leveling.js:2500 เมื่อค่าเป็นศูนย์")
    seen = {}

    def fake_agent(cfg, prompt, cwd, slot_id=None, role="coder", **kw):
        seen["prompt"] = prompt
        return {"status": "SUCCESS", "response": '{"bug_exists": true, "reason": "ok"}'}

    monkeypatch.setattr(runner, "call_agent", fake_agent)
    verdict = runner._confirm_bug_exists(job, {}, tmp_path, None)
    assert verdict == {"bug_exists": True, "reason": "ok"}
    assert "2500: L2500" in seen["prompt"]
    assert "[ข้าม บรรทัด 1–2439]" in seen["prompt"]
    assert "[ข้าม บรรทัด 2561–3000]" in seen["prompt"]
    assert "L1000" not in seen["prompt"]

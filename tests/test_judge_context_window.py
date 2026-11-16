"""Tests verifying MAX_CONTEXT_CHARS truncation and cited-line windowing for judge (decision item 5)."""

from pathlib import Path

from auto_dev_crew import quality_gates as qg
from auto_dev_crew import runner
from auto_dev_crew.runner import Job


def _write_numbered_file(tmp_path: Path, name: str, total_lines: int) -> None:
    content = "".join(f"L{i}: const line_{i} = 'payload_padding_for_context_test';\n" for i in range(1, total_lines + 1))
    (tmp_path / name).write_text(content, encoding="utf-8")


def test_read_files_block_shows_cited_lines_on_long_file(tmp_path: Path):
    _write_numbered_file(tmp_path, "index.html", 3244)
    block = qg.read_files_block(
        tmp_path,
        ["index.html"],
        focus="ตรวจสอบบั๊กที่ index.html:899-900 และ index.html:1961",
    )
    assert "899: L899:" in block
    assert "900: L900:" in block
    assert "1961: L1961:" in block
    assert "[ข้าม บรรทัด 1–838]" in block
    assert "[ข้าม บรรทัด 961–1900]" in block
    assert "[ข้าม บรรทัด 2022–3244]" in block


def test_full_files_block_truncates_beyond_max_context_chars(tmp_path: Path):
    _write_numbered_file(tmp_path, "index.html", 3244)
    assert qg.MAX_CONTEXT_CHARS == 120000
    block = qg.full_files_block(tmp_path, ["index.html"])
    assert "[ตัดทอน: เกินขนาดที่ส่งได้]" in block
    assert "1961: L1961:" not in block


def test_confirm_bug_exists_passes_cited_lines_to_judge_prompt(tmp_path: Path, monkeypatch):
    _write_numbered_file(tmp_path, "index.html", 3244)
    job = Job(
        kind="issue",
        key="227",
        title="Verify cited lines beyond 30k chars",
        body="จุดที่ผิดอยู่ที่ index.html:899-900 และ index.html:1961",
    )
    captured = {}

    def fake_agent(cfg, prompt, cwd, slot_id=None, role="coder", **kw):
        captured["prompt"] = prompt
        return {"status": "SUCCESS", "response": '{"bug_exists": true, "reason": "เห็นบรรทัดที่อ้างแล้ว"}'}

    monkeypatch.setattr(runner, "call_agent", fake_agent)
    verdict = runner._confirm_bug_exists(job, {}, tmp_path, None)
    assert verdict == {"bug_exists": True, "reason": "เห็นบรรทัดที่อ้างแล้ว"}
    assert "899: L899:" in captured["prompt"]
    assert "1961: L1961:" in captured["prompt"]

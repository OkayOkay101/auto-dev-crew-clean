"""สร้าง PR body มาตรฐาน: Summary / Changes / Test Checklist (ผ่าน redact_secrets ก่อนส่งออก)."""
from __future__ import annotations

import datetime as dt

from .redact import redact_secrets


_WEB_SUFFIXES = (".html", ".htm", ".css", ".js", ".jsx", ".tsx", ".vue")


def manual_check_lines(files_changed: list[str]) -> str:
    """ข้อความ 'วิธีตรวจด้วยมือ' ให้ผู้รีวิวรู้ว่า PR นี้ต้องดูด้วยตาหรือไม่ (ผู้รีวิวเป็นคนเสมอ ไม่ใช่แค่ CI)."""
    web = [f for f in files_changed if f.lower().endswith(_WEB_SUFFIXES)]
    lines = ["- ผู้รีวิวเป็นคน: ยังไม่มี; ผลตรวจมาจาก CI และด่านอัตโนมัติเท่านั้น"]
    if web:
        names = ", ".join(web[:5])
        lines.append(f"- แตะหน้าเว็บ ({names}): เปิดในเบราว์เซอร์แล้วลองใช้ฟีเจอร์ที่เปลี่ยนก่อน merge")
    else:
        lines.append("- ไม่มีไฟล์หน้าเว็บที่เปลี่ยน: เทสต์อัตโนมัติเป็นหลักฐานหลัก")
    return "\n".join(lines)


def build_pr_body(job_title: str, job_ref: str | None, persona: str, summary: str,
                  files_changed: list[str], test_cmd: str, test_passed: bool,
                  eval_score: float | None, *, lines: int | None = None,
                  repro_tests: list[str] | None = None) -> str:
    if job_ref:
        ref = f"#{job_ref}" if job_ref.isdigit() else job_ref
        link = f"Closes {ref}"
    else:
        link = f"ตัวละคร: {persona}"
    changes = "\n".join(f"- {f}" for f in files_changed) or "- (ไม่มีไฟล์ที่เปลี่ยน)"
    mark = "x" if test_passed else " "
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    score = "N/A" if eval_score is None else eval_score
    lines_part = f" · แก้ {lines} บรรทัด" if lines is not None else ""
    repro = ""
    if repro_tests:  # หลักฐานบั๊ก: เทสต์ที่เพิ่มถูกยืนยันแล้วว่า fail บนโค้ดเดิม (ก่อนแก้)
        listed = "\n".join(f"- {t}" for t in repro_tests)
        repro = f"## Repro\nเทสต์ที่ยืนยันบั๊กนี้ (fail บนโค้ดเดิมก่อนแก้ แล้วผ่านหลังแก้):\n{listed}\n\n"
    body = (f"## Summary\n{summary}\n\n"
            f"{link}\n\n"
            f"## Changes\n{changes}\n\n"
            f"{repro}"
            f"## วิธีตรวจด้วยมือ\n{manual_check_lines(files_changed)}\n\n"
            f"## Test Checklist\n- [{mark}] {test_cmd}\n\n"
            f"---\n🕒 เวลาสร้าง: {now} · agentic-eval: {score}{lines_part} · {len(files_changed)} ไฟล์\n"
            f"🤖 สร้างโดย Auto Dev Crew")
    return redact_secrets(body)

"""ด่านตรวจคุณภาพก่อนและหลัง coder สำหรับ issue (ตามแผน docs/draft-quality-gates.md).

- ด่าน 1: ก่อนให้ coder แก้ ให้ judge ยืนยันว่าบั๊กที่ issue อ้างมีจริงในไฟล์ปัจจุบัน
- ด่าน 2: judge ต้องเห็นไฟล์ production เต็ม ไม่ใช่แค่ diff
- ด่าน 3: รอบซ่อมที่ diff ไม่แตะไฟล์ production ที่ issue ระบุ ถูกบล็อกก่อนถึง judge

โมดูลนี้ไม่เรียก AI และไม่แตะ GitHub เอง: เป็นฟังก์ชันบริสุทธิ์ที่ runner/evaluator เรียกใช้.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ไฟล์ที่ issue มักอ้างถึง: path แบบ a/b.js หรือ file.py โดยไม่มี "/" นำหน้า
_PATH_RE = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:js|jsx|mjs|cjs|ts|tsx|py|css|html|json|yaml|yml|md))(?![\w/])"
)
_TEST_RE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|_test\.py$|\.(test|spec)\.[a-z]+$|(^|/)test-runner\.js$")
_SKIP_PREFIXES = (".github/",)
MAX_CONTEXT_CHARS = 120000
# จำนวนบรรทัดรอบแต่ละจุดที่ issue อ้าง (name:line) ที่ส่งให้ judge ด่านยืนยันบั๊ก
BUG_CONTEXT_PAD = 60


def is_test_path(path: str) -> bool:
    return bool(_TEST_RE.search(path.replace("\\", "/")))


def production_files(files: list[str]) -> list[str]:
    return [f for f in files if not is_test_path(f) and not f.startswith(_SKIP_PREFIXES)]


def named_files(text: str) -> list[str]:
    """ไฟล์ production ที่ issue (ชื่อ+เนื้อหา) อ้างถึง ตามลำดับที่พบ ไม่ซ้ำ."""
    seen: list[str] = []
    for m in _PATH_RE.finditer(text or ""):
        p = m.group(1)
        if is_test_path(p) or p.startswith(_SKIP_PREFIXES) or p in seen:
            continue
        seen.append(p)
    return seen


def existing_named_files(cwd: Path, text: str) -> list[str]:
    """เฉพาะไฟล์ที่อ้างถึงแล้วมีอยู่จริงใน worktree (ไฟล์ที่ issue พูดถึงแต่ไม่มีจะไม่ใช้เป็นเกณฑ์)."""
    return [p for p in named_files(text) if (Path(cwd) / p).is_file()]


def repair_gate_violation(named: list[str], changed: list[str]) -> str | None:
    """ด่าน 3: คืนข้อความเหตุผลเมื่อ diff ไม่แตะไฟล์ production ที่ issue ระบุเลย; None = ผ่าน."""
    if not named:
        return None
    touched = set(production_files(changed))
    if any(n in touched for n in named):
        return None
    shown = ", ".join(named[:5])
    got = ", ".join(sorted(touched)[:5]) or "(ไม่มีไฟล์ production)"
    return (f"diff ไม่แตะไฟล์ production ที่ issue ระบุ (issue อ้าง: {shown}; diff แก้: {got}) "
            "— บล็อกก่อนให้ judge ประเมิน")


def _numbered(text: str) -> str:
    return "\n".join(f"{i}: {ln}" for i, ln in enumerate(text.splitlines(), 1))


def line_refs(text: str, name: str) -> list[tuple[int, int]]:
    """บรรทัดที่ text อ้างถึงไฟล์ name ในรูป name:line หรือ name:line-line เป็นคู่ (เริ่ม, จบ) ตามลำดับที่พบ."""
    pat = re.compile(r"(?<![\w/.-])" + re.escape(name) + r":(\d+)(?:\s*[-–]\s*(\d+))?(?!\d)")
    refs: list[tuple[int, int]] = []
    for m in pat.finditer(text or ""):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if min(a, b) >= 1:
            refs.append((min(a, b), max(a, b)))
    return refs


def _focus_spans(refs: list[tuple[int, int]], n_lines: int, pad: int = BUG_CONTEXT_PAD) -> list[tuple[int, int]]:
    """ช่วงบรรทัด (เริ่ม, จบ) รอบแต่ละจุดที่อ้าง ขยายด้วย pad แล้วรวมช่วงที่ทับหรือติดกัน.
    คืนลิสต์ว่างเมื่อไม่มีจุดใดอยู่ในไฟล์ (ให้ผู้เรียกใช้พฤติกรรมเดิม)."""
    spans: list[tuple[int, int]] = []
    for lo, hi in refs:
        if lo > n_lines:
            continue
        spans.append((max(1, lo - pad), min(n_lines, hi + pad)))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _windowed(lines: list[str], spans: list[tuple[int, int]]) -> str:
    """เฉพาะช่วงที่เลือก พร้อมเลขบรรทัดเดิม และตัวคั่นบอกช่วงที่ข้ามไป."""
    out: list[str] = []
    prev = 0
    for lo, hi in spans:
        if lo > prev + 1:
            out.append(f"[ข้าม บรรทัด {prev + 1}–{lo - 1}]")
        out.extend(f"{i}: {lines[i - 1]}" for i in range(lo, hi + 1))
        prev = hi
    if prev < len(lines):
        out.append(f"[ข้าม บรรทัด {prev + 1}–{len(lines)}]")
    return "\n".join(out)


def read_files_block(cwd: Path, names: list[str], limit: int = MAX_CONTEXT_CHARS, focus: str = "") -> str:
    """ไฟล์ (มีเลขบรรทัด) สำหรับส่งให้ judge; ตัดเมื่อเกิน limit และบอกชัดเจน.
    focus = ข้อความ issue: ถ้าอ้าง name:line ไว้ จะส่งเฉพาะช่วงรอบบรรทัดนั้น (มีตัวคั่น [ข้าม บรรทัด a–b]);
    ไม่มีการอ้างบรรทัดของไฟล์นั้น = ส่งไฟล์เต็มตั้งแต่ต้นแบบเดิม."""
    parts: list[str] = []
    used = 0
    for name in names:
        try:
            text = (Path(cwd) / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            parts.append(f"=== FILE: {name} ===\n[อ่านไม่ได้]\n")
            continue
        lines = text.splitlines()
        spans = _focus_spans(line_refs(focus, name), len(lines))
        body = _windowed(lines, spans) if spans else _numbered(text)
        if used + len(body) > limit:
            body = body[: max(limit - used, 0)] + "\n[ตัดทอน: เกินขนาดที่ส่งได้]"
        used += len(body)
        parts.append(f"=== FILE: {name} ===\n{body}\n")
        if used >= limit:
            break
    return "\n".join(parts) if parts else "(ไม่มีไฟล์ production ให้อ่าน)"


def full_files_block(cwd: Path, changed: list[str], limit: int = MAX_CONTEXT_CHARS) -> str:
    """ด่าน 2: ไฟล์ production ที่ diff แตะ ในสถานะปัจจุบันทั้งไฟล์ (หลังแก้แล้ว)."""
    return read_files_block(cwd, production_files(changed), limit=limit)


def bug_check_prompt(title: str, body: str, files_block: str) -> str:
    # ถ้าบางไฟล์ถูกตัดเหลือเฉพาะช่วงรอบบรรทัดที่ issue อ้าง ต้องบอก judge ให้ชัด (prompt เดิมไม่เปลี่ยนเมื่อไม่มีการตัด)
    note = ("- บางไฟล์แสดงเฉพาะช่วงรอบบรรทัดที่ issue อ้าง (ดูตัวคั่น [ข้าม บรรทัด …]) "
            "ถ้าบรรทัดที่ issue อ้างไม่อยู่ในช่วงที่แสดง ให้ตอบ bug_exists=true\n") if "[ข้าม บรรทัด" in files_block else ""
    return (
        "# Role: Bug Verifier\n"
        "ตรวจว่าบั๊กที่ issue อ้างมีอยู่จริงในโค้ดปัจจุบันหรือไม่ อ่านไฟล์เต็มด้านล่างเท่านั้น\n"
        "- ตอบ bug_exists=false เฉพาะเมื่อโค้ดปัจจุบันทำงานถูกต้องตามที่ issue ระบุอยู่แล้วชัดเจน (อ้างบรรทัด)\n"
        "- ถ้าไม่แน่ใจ ให้ตอบ bug_exists=true\n"
        "- ห้ามเดาจาก issue อย่างเดียว\n"
        f"{note}\n"
        "ตอบเป็น JSON object เดียวใน ```json ... ``` เท่านั้น:\n"
        '{"bug_exists": true, "reason": "<เหตุผลสั้น ๆ ภาษาไทย อ้างบรรทัด>"}\n\n'
        f"## Issue\n{title}\n\n{body}\n\n"
        f"## ไฟล์ production ปัจจุบัน\n{files_block}\n"
    )


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_bug_check(raw: str) -> dict | None:
    """คืน {"bug_exists": bool, "reason": str} หรือ None ถ้าอ่านไม่ได้ (ไม่บล็อกโดยไม่มีหลักฐาน)."""
    if not isinstance(raw, str):
        return None
    m = _JSON_OBJ_RE.search(raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("bug_exists"), bool):
        return None
    return {"bug_exists": data["bug_exists"], "reason": str(data.get("reason") or "").strip()}


REPRO_STEPS = (
    "## ขั้นตอนบังคับสำหรับบั๊ก\n"
    "1. เขียนเทสต์ที่ fail กับโค้ดปัจจุบันก่อน (ยืนยันว่าบั๊กมีจริง)\n"
    "2. แก้ไฟล์ production ที่ issue ระบุ\n"
    "3. รันเทสต์ทั้งหมดให้ผ่าน\n"
    "ถ้าเทสต์ที่เขียนผ่านตั้งแต่แรก แปลว่าไม่มีบั๊ก ให้รายงานใน result แทนการแก้โค้ดที่ไม่จำเป็น"
)

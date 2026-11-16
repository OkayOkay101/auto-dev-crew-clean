"""ด่านตรวจแบบกำหนดผลได้ (deterministic) ที่รันก่อน judge ประเมิน diff.

สแกนเฉพาะบรรทัดที่ "เพิ่มใหม่" ใน diff (บรรทัด `+`) ไม่สแกน context หรือบรรทัดที่ถูกลบ
กฎที่ blocking=True จะทำให้ diff ไม่ผ่านทันที โดยไม่เสียโควตา judge; กฎที่เป็นคำเตือนจะส่งให้ judge เป็นข้อมูลประกอบ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_DOC_SUFFIXES = {".md", ".txt", ".rst", ".csv"}
_JS_SUFFIXES = {".js", ".mjs", ".jsx", ".ts", ".tsx", ".html"}

# Python: จับ exception กว้างแล้วกลืนทิ้ง (except: / except Exception: แล้วบรรทัดถัดไปเป็น pass)
_PY_BROAD_EXCEPT = re.compile(r"^\s*except\s*(?:(?:Exception|BaseException)\s*(?:as\s+\w+\s*)?)?:\s*(?:#.*)?$")
_PY_PASS = re.compile(r"^\s*pass\s*(?:#.*)?$")
_PY_DEBUG = re.compile(r"\bbreakpoint\(\)|\bpdb\.set_trace\(")

# JavaScript/HTML: catch ว่าง (บรรทัดเดียว หรือ `catch (e) {` แล้วบรรทัดถัดไปเป็น `}`)
_JS_CATCH_INLINE = re.compile(
    r"\.catch\(\s*(?:\(\s*\w*\s*\)|\w+)\s*=>\s*\{\s*\}\s*\)"
    r"|\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}"
)
_JS_CATCH_OPEN = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*(?://.*)?$")
_JS_CLOSE = re.compile(r"^\s*\}\s*;?\s*$")

# ร่องรอยการดีบักที่หลุดเข้า production
_DEBUGGER = re.compile(r"^\s*debugger\s*;?\s*(?://.*)?$")
_FOCUSED_TEST = re.compile(r"\b(?:it|test|describe)\.only\(")

# ความลับที่ฝังในโค้ด (ข้ามไฟล์เทสต์และค่าที่เป็นตัวอย่าง/ตัวยึดตำแหน่ง)
_SECRET = re.compile(
    r"""(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*["']([A-Za-z0-9_\-+/=.]{16,})["']"""
)
_PLACEHOLDER_HINTS = ("example", "your", "changeme", "xxxx", "placeholder", "<", "${", "dummy")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|fixtures?|examples?)/|(^|/)test_[^/]*$|\.(test|spec)\.[a-z]+$")

# TODO/FIXME ต้องอ้าง issue (เป็นคำเตือน ไม่บล็อก)
_TODO = re.compile(r"\b(?:TODO|FIXME)\b")
_ISSUE_REF = re.compile(r"#\d+|/issues/\d+")

RULE_HINTS = {
    "broad-except-swallow": "จับ exception กว้างแล้วกลืนทิ้ง (except: pass) ให้จับเฉพาะชนิดที่คาดไว้ หรือ log/raise ใหม่",
    "js-empty-catch": "catch ว่างกลืน error ให้จัดการ แสดงผล หรือส่งต่อ",
    "debug-artifact": "มีโค้ดดีบักหลงเหลือ (debugger / breakpoint / pdb / .only)",
    "hardcoded-secret": "ฝังค่าความลับไว้ในโค้ด ให้อ่านจาก environment หรือไฟล์ .env ที่ไม่ commit",
    "todo-without-issue": "TODO/FIXME ไม่ได้อ้าง issue (เช่น #123)",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str
    blocking: bool


def _added_lines(diff: str) -> list[tuple[str, int, str]]:
    """คืน (path, เลขบรรทัดในไฟล์ใหม่, ข้อความ) ของทุกบรรทัดที่เพิ่มใน diff."""
    out: list[tuple[str, int, str]] = []
    path: str | None = None
    new_line: int | None = None  # None = อยู่นอก hunk
    for raw in (diff or "").splitlines():
        if raw.startswith("diff --git "):
            path, new_line = None, None
            continue
        if raw.startswith("@@"):
            m = _HUNK_RE.match(raw)
            new_line = int(m.group(1)) if m else None
            continue
        if new_line is None:  # หัวไฟล์ (--- / +++) ก่อน hunk
            if raw.startswith("+++ "):
                target = raw[4:].strip()
                if target == "/dev/null":
                    path = None
                else:
                    path = target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("+"):
            if path is not None:
                out.append((path, new_line, raw[1:]))
            new_line += 1
        elif raw.startswith(" "):
            new_line += 1
        # บรรทัด `-` และ `\ No newline` ไม่อยู่ในไฟล์ใหม่ จึงไม่นับ
    return out


def _is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path.replace("\\", "/")))


def _looks_like_placeholder(value: str) -> bool:
    low = value.lower()
    return any(hint in low for hint in _PLACEHOLDER_HINTS)


def _contiguous(nxt, path: str, line: int) -> bool:
    return nxt is not None and nxt[0] == path and nxt[1] == line + 1


def scan_diff(diff: str) -> list[Finding]:
    """สแกนบรรทัดที่เพิ่มใหม่ของ diff แล้วคืนรายการพบ (ว่างถ้าสะอาด)."""
    added = _added_lines(diff)
    findings: list[Finding] = []

    def add(path: str, line: int, rule: str, text: str, blocking: bool) -> None:
        findings.append(Finding(path=path, line=line, rule=rule, text=text.strip()[:160], blocking=blocking))

    for idx, (path, line, text) in enumerate(added):
        suffix = Path(path).suffix.lower()
        if suffix in _DOC_SUFFIXES:
            continue
        nxt = added[idx + 1] if idx + 1 < len(added) else None

        if suffix == ".py":
            if _PY_BROAD_EXCEPT.match(text) and _contiguous(nxt, path, line) and _PY_PASS.match(nxt[2]):
                add(path, line, "broad-except-swallow", text, True)
            if _PY_DEBUG.search(text):
                add(path, line, "debug-artifact", text, True)

        if suffix in _JS_SUFFIXES:
            if _JS_CATCH_INLINE.search(text):
                add(path, line, "js-empty-catch", text, True)
            elif _JS_CATCH_OPEN.search(text) and _contiguous(nxt, path, line) and _JS_CLOSE.match(nxt[2]):
                add(path, line, "js-empty-catch", text, True)
            if _DEBUGGER.match(text):
                add(path, line, "debug-artifact", text, True)

        if _FOCUSED_TEST.search(text):
            add(path, line, "debug-artifact", text, True)

        if not _is_test_path(path):
            m = _SECRET.search(text)
            if m and not _looks_like_placeholder(m.group(1)):
                add(path, line, "hardcoded-secret", text, True)

        if _TODO.search(text) and not _ISSUE_REF.search(text):
            add(path, line, "todo-without-issue", text, False)

    return findings


def blocking_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.blocking]


def format_findings(findings: list[Finding]) -> str:
    """ข้อความสำหรับ critique (ภาษาไทยชี้ตำแหน่งและกฎ)."""
    lines = [f"- {f.path}:{f.line} [{f.rule}] {RULE_HINTS.get(f.rule, '')}" for f in findings]
    return "\n".join(lines)


def format_advisory(findings: list[Finding]) -> str:
    """ข้อมูลประกอบที่ใส่ใน prompt ของ judge; ไม่มีรายการให้คืน 'ไม่มี'."""
    if not findings:
        return "ไม่มี"
    lines = []
    for f in findings:
        tag = "blocking" if f.blocking else "advisory"
        lines.append(f"- [{tag}] {f.path}:{f.line} [{f.rule}] `{f.text}`")
    return "\n".join(lines)

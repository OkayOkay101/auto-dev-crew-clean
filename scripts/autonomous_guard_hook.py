"""PreToolUse guard: while autonomous mode is on, hard-deny irreversible or self-disabling actions.

These are denied outright, not asked, so the loop cannot push, merge, deploy, wipe files,
or switch its own flag or settings off. Denial is returned as Claude Code's permission decision.
"""
from __future__ import annotations

import json
import re
import sys

import autonomous_common as common

DENY_BASH = [
    (r"\bgit\s+push\b", "บล็อกในโหมดอัตโนมัติ: git push ต้องได้รับอนุญาตจากผู้ใช้ก่อน"),
    (r"\bgh\s+pr\s+merge\b", "บล็อกในโหมดอัตโนมัติ: merge PR ต้องได้รับอนุญาตจากผู้ใช้ก่อน"),
    (r"\bgh\s+release\b", "บล็อกในโหมดอัตโนมัติ: release ต้องได้รับอนุญาตจากผู้ใช้ก่อน"),
    (r"\bdeploy\b", "บล็อกในโหมดอัตโนมัติ: deploy ต้องได้รับอนุญาตจากผู้ใช้ก่อน"),
    (r"\bgit\s+reset\s+--hard\b", "บล็อกในโหมดอัตโนมัติ: git reset --hard ทำลายงานที่ยังไม่ commit"),
    (r"\bgit\s+clean\b.*-\w*f", "บล็อกในโหมดอัตโนมัติ: git clean -f ลบไฟล์ที่ไม่ได้ track"),
    (r"\brm\s+(-\w+\s+)*-\w*[rR]\w*", "บล็อกในโหมดอัตโนมัติ: rm แบบเรียกซ้ำ/บังคับลบข้อมูล"),
    (r"\bRemove-Item\b.*-Recurse", "บล็อกในโหมดอัตโนมัติ: Remove-Item -Recurse ลบข้อมูลเป็นกลุ่ม"),
    (r"\bdel\s+/[sS]\b", "บล็อกในโหมดอัตโนมัติ: del /s ลบข้อมูลเป็นกลุ่ม"),
    (
        r"(\brm\b|\bdel\b|\bRemove-Item\b|\bunlink\b).*autonomous\.flag",
        "บล็อกในโหมดอัตโนมัติ: ห้ามลบไฟล์ธงเอง ให้ผู้ใช้เป็นผู้ปิดโหมด",
    ),
]

WRITE_TOOLS = {"Write", "Edit", "MultiEdit"}
PROTECTED_PATH = re.compile(r"(^|/)state/autonomous\.flag$|(^|/)\.claude/settings(\.local)?\.json$")


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def decide(root, payload):
    """Return a deny decision dict, or None to let the normal permission flow continue."""
    if not isinstance(payload, dict) or not common.is_enabled(root):
        return None

    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None

    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        for pattern, reason in DENY_BASH:
            if re.search(pattern, command, re.IGNORECASE):
                return _deny(reason)
    elif tool in WRITE_TOOLS:
        path = str(tool_input.get("file_path", "")).replace("\\", "/")
        if PROTECTED_PATH.search(path):
            return _deny("บล็อกในโหมดอัตโนมัติ: ห้ามแก้ไขไฟล์ธงหรือการตั้งค่า hook ระหว่างโหมดทำงาน")
    return None


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        return 0
    try:
        out = decide(common.project_root(), payload)
    except OSError:
        return 0
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

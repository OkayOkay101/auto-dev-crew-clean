"""Stop hook: keep autonomous mode running until the flag is removed or the turn cap is reached.

Claude Code passes the event payload on stdin. Printing {"decision": "block", "reason": ...}
makes Claude continue with `reason` as the next instruction. Printing nothing lets it stop.
"""
from __future__ import annotations

import json
import sys

import autonomous_common as common


def _disable(root, why: str) -> None:
    common.flag_path(root).unlink(missing_ok=True)
    with common.mission_path(root).open("a", encoding="utf-8") as fh:
        fh.write(f"\n## ปิดโหมดอัตโนมัติ\n- {why}\n")


def decide(root, payload):
    """Return a block decision dict, or None to allow the stop."""
    if not isinstance(payload, dict):
        return None  # malformed input must never trap the user
    if not common.is_enabled(root):
        return None

    max_turns = common.load_settings(root)["max_turns_per_session"]
    turns = common.read_counter(root)
    if turns >= max_turns:
        _disable(root, f"ครบเพดาน {max_turns} รอบต่อเซสชัน ปิดโหมดอัตโนมัติ")
        return None

    common.write_counter(root, turns + 1)
    return {
        "decision": "block",
        "reason": (
            f"โหมดอัตโนมัติยังเปิดอยู่ (รอบ {turns + 1}/{max_turns}) "
            "ทำต่อจาก state/mission.md: ตรวจสถานะล่าสุด รันงานขั้นถัดไป "
            "แก้ข้อผิดพลาดแล้วรันต่อ ถ้าครบเพดานให้เขียน handoff ใน docs/"
        ),
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        payload = None
    try:
        out = decide(common.project_root(), payload)
    except OSError:
        out = None  # fail open: never trap the user on an IO error
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Turn autonomous mode on, off, or inspect it.

Usage (from the project root):
    python scripts/autonomous_ctl.py on --mission "เป้าหมายงาน"   # or --mission-file path
    python scripts/autonomous_ctl.py off --reason "เหตุผล"
    python scripts/autonomous_ctl.py status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import autonomous_common as common


def enable(root: Path, mission: str) -> None:
    """Write the mission, reset the turn counter, and raise the flag."""
    text = mission.strip()
    if not text:
        raise ValueError("mission ต้องไม่ว่าง")
    common.state_dir(root).mkdir(parents=True, exist_ok=True)
    common.mission_path(root).write_text(f"# เป้าหมาย\n\n{text}\n", encoding="utf-8")
    common.write_counter(root, 0)
    common.flag_path(root).write_text("on", encoding="utf-8")


def disable(root: Path, reason: str) -> bool:
    """Lower the flag and record why. Returns False if the mode was already off."""
    flag = common.flag_path(root)
    if not flag.is_file():
        return False
    flag.unlink()
    with common.mission_path(root).open("a", encoding="utf-8") as fh:
        fh.write(f"\n## ปิดโหมดอัตโนมัติ\n- {reason.strip() or 'ปิดด้วยผู้ใช้'}\n")
    return True


def status(root: Path) -> dict:
    return {
        "enabled": common.is_enabled(root),
        "turns": common.read_counter(root),
        "max_turns": common.load_settings(root)["max_turns_per_session"],
    }


def _say(message: str, *, err: bool = False) -> None:
    """Print UTF-8 regardless of console code page (Windows consoles default to cp1252)."""
    stream = sys.stderr if err else sys.stdout
    data = (message + "\n").encode("utf-8")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:
        stream.write(message + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autonomous_ctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_on = sub.add_parser("on", help="เปิดโหมดพร้อมเป้าหมาย")
    group = p_on.add_mutually_exclusive_group(required=True)
    group.add_argument("--mission", help="ข้อความเป้าหมาย")
    group.add_argument("--mission-file", help="ไฟล์ที่มีข้อความเป้าหมาย")

    p_off = sub.add_parser("off", help="ปิดโหมด")
    p_off.add_argument("--reason", default="ปิดด้วยผู้ใช้")

    sub.add_parser("status", help="แสดงสถานะ")

    args = parser.parse_args(argv)
    root = common.project_root()

    try:
        if args.cmd == "on":
            mission = args.mission
            if args.mission_file:
                mission = Path(args.mission_file).read_text(encoding="utf-8")
            enable(root, mission)
            _say("เปิดโหมดอัตโนมัติแล้ว")
        elif args.cmd == "off":
            _say("ปิดโหมดแล้ว" if disable(root, args.reason) else "โหมดปิดอยู่แล้ว")
        else:
            _say(json.dumps(status(root), ensure_ascii=False))
    except (OSError, ValueError) as exc:
        _say(f"ผิดพลาด: {exc}", err=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

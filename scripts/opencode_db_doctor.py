"""ตรวจ/ซ่อม opencode.db (ตาราง workspace ไม่มี project_id).

ค่าเริ่มต้นเป็น dry-run: แค่ตรวจและรายงาน. ใส่ --apply เพื่อสำรองแล้วซ่อมจริง.
ควรปิด OpenCode ทุกตัวก่อนรัน --apply.

    python scripts/opencode_db_doctor.py
    python scripts/opencode_db_doctor.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_dev_crew import opencode_db  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows console อาจเป็น cp1252 และพิมพ์ภาษาไทยไม่ได้
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=opencode_db.DEFAULT_DB)
    ap.add_argument("--apply", action="store_true", help="สำรองแล้วซ่อมจริง (ค่าเริ่มต้นคือ dry-run)")
    args = ap.parse_args()

    report = opencode_db.repair(args.db, apply=args.apply)
    print(f"DB: {report['db']}")
    print(f"สถานะ: {report['reason']}")
    print(f"ต้องซ่อม: {report['needs_repair']} | แถวใน workspace: {report['workspace_rows']}")
    if report["applied"]:
        print(f"ซ่อมแล้ว | สำรองที่: {report['backup']}")
    elif report["needs_repair"] and not args.apply:
        print("dry-run: ยังไม่ได้แก้ไข รันอีกครั้งด้วย --apply เพื่อซ่อม")
    return 0 if (not report["needs_repair"] or report["applied"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

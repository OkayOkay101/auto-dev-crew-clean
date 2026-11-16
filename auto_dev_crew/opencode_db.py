"""ตรวจและซ่อมสคีมาตาราง `workspace` ใน opencode.db ที่ค้างจากเวอร์ชันเก่า.

อาการ: รัน `opencode` ในโฟลเดอร์ที่ resolve เป็น project แล้วขึ้น `no such column: project_id`
สาเหตุ: ตาราง workspace ใน DB เป็นสคีมาเก่า (provider/binding) ไม่มีคอลัมน์ project_id
ที่ OpenCode เวอร์ชันปัจจุบันใช้ค้นหา. การซ่อมจะสร้างตารางตามสคีมาปัจจุบันใหม่
แต่ทำเฉพาะเมื่อตารางว่าง (ไม่มีข้อมูลที่จะสูญหาย) และสำรอง DB ก่อนเสมอ.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

WORKSPACE_DDL = """CREATE TABLE `workspace` (
  `id` text PRIMARY KEY,
  `type` text NOT NULL,
  `name` text DEFAULT '' NOT NULL,
  `branch` text,
  `directory` text,
  `extra` text,
  `project_id` text NOT NULL,
  CONSTRAINT `fk_workspace_project_id_project_id_fk` FOREIGN KEY (`project_id`) REFERENCES `project`(`id`) ON DELETE CASCADE
)"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info(`{table}`)")}


def diagnose(db_path: Path = DEFAULT_DB) -> dict:
    """คืนสถานะของ DB โดยไม่แก้ไขอะไร."""
    report = {"db": str(db_path), "exists": db_path.exists(), "needs_repair": False,
              "workspace_rows": None, "reason": ""}
    if not report["exists"]:
        report["reason"] = "ไม่พบไฟล์ DB (ยังไม่เคยใช้ OpenCode หรือ path ไม่ถูก)"
        return report
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        cols = _columns(conn, "workspace")
        if not cols:
            report["reason"] = "ไม่มีตาราง workspace (ไม่ต้องซ่อม)"
            return report
        report["workspace_rows"] = conn.execute("SELECT COUNT(*) FROM workspace").fetchone()[0]
        if "project_id" in cols:
            report["reason"] = "สคีมา workspace ถูกต้องแล้ว"
            return report
        report["needs_repair"] = True
        if report["workspace_rows"]:
            report["reason"] = (f"workspace มีข้อมูล {report['workspace_rows']} แถว และสคีมาเก่า "
                                "ต้องตรวจด้วยตนเองก่อน (สคริปต์นี้ไม่ทับข้อมูล)")
        else:
            report["reason"] = "workspace ว่างและสคีมาเก่า ซ่อมได้อย่างปลอดภัย"
        return report
    finally:
        conn.close()


def repair(db_path: Path = DEFAULT_DB, backup_dir: Path | None = None, apply: bool = False) -> dict:
    """ซ่อม workspace ถ้าจำเป็น. apply=False คือ dry-run (ค่าเริ่มต้น)."""
    report = diagnose(db_path)
    report["applied"] = False
    report["backup"] = None
    if not report["needs_repair"] or not apply:
        return report
    if report["workspace_rows"]:
        return report  # diagnose() already explained; never touch rows

    backup_dir = backup_dir or db_path.parent / "oc_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"opencode-{dt.datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup)
    try:
        src.backup(dst)  # สำรองก่อนแก้ทุกครั้ง
    finally:
        dst.close()
        src.close()
    report["backup"] = str(backup)

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE `workspace`")
        conn.execute(WORKSPACE_DDL)
        conn.execute("COMMIT")
        if "project_id" not in _columns(conn, "workspace"):
            raise RuntimeError("สร้าง workspace แล้วยังไม่มี project_id")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("integrity_check ไม่ผ่านหลังซ่อม")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    report["applied"] = True
    report["needs_repair"] = False
    report["reason"] = "ซ่อมสคีมา workspace แล้ว (สำรองไว้ที่ backup)"
    return report

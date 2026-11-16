"""Active slot registry and collision tracking across concurrent runner slots."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from .locks import locked_json_read, locked_json_write, file_lock

STALE_SLOT_SECONDS = 7200.0   # 2 hours


class SlotRegistry:
    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "active_slots.json"
        self.lock_file = self.state_dir / "active_slots.json.lock"

    def _load_and_prune(self) -> dict[str, dict]:
        data = locked_json_read(self.state_file, default={})
        now = time.time()
        pruned = {}
        changed = False
        for slot_k, slot_v in data.items():
            heartbeat = slot_v.get("updated_at_ts", 0)
            if now - heartbeat < STALE_SLOT_SECONDS:
                pruned[slot_k] = slot_v
            else:
                changed = True
        if changed:
            locked_json_write(self.state_file, pruned)
        return pruned

    def register_slot(
        self,
        slot_id: int,
        kind: str,
        key: str,
        branch: str,
        active_files: list[str] | None = None
    ) -> None:
        with file_lock(self.lock_file):
            slots = locked_json_read(self.state_file, default={})
            slot_key = f"slot_{slot_id}"
            now = time.time()
            slots[slot_key] = {
                "slot_id": slot_id,
                "kind": kind,
                "key": key,
                "branch": branch,
                "active_files": list(active_files or []),
                "state": "working",
                "started_at": dt.datetime.now().isoformat(timespec="seconds"),
                "updated_at_ts": now,
            }
            locked_json_write(self.state_file, slots)

    def update_active_files(self, slot_id: int, files: list[str]) -> None:
        with file_lock(self.lock_file):
            slots = locked_json_read(self.state_file, default={})
            slot_key = f"slot_{slot_id}"
            if slot_key in slots:
                slots[slot_key]["active_files"] = list(files)
                slots[slot_key]["updated_at_ts"] = time.time()
                locked_json_write(self.state_file, slots)

    def update_slot_state(self, slot_id: int, state: str) -> None:
        with file_lock(self.lock_file):
            slots = locked_json_read(self.state_file, default={})
            slot_key = f"slot_{slot_id}"
            if slot_key in slots:
                slots[slot_key]["state"] = state
                slots[slot_key]["updated_at_ts"] = time.time()
                locked_json_write(self.state_file, slots)

    def release_slot(self, slot_id: int) -> None:
        with file_lock(self.lock_file):
            slots = locked_json_read(self.state_file, default={})
            slot_key = f"slot_{slot_id}"
            if slot_key in slots:
                del slots[slot_key]
                locked_json_write(self.state_file, slots)

    def clear_all(self) -> None:
        """Drop every slot entry. Only for when the runner that owned them has been killed."""
        with file_lock(self.lock_file):
            locked_json_write(self.state_file, {})

    def get_active_jobs(self) -> dict[str, dict]:
        return self._load_and_prune()

    def get_colliding_files(self, excluding_slot_id: int) -> set[str]:
        slots = self._load_and_prune()
        excl_key = f"slot_{excluding_slot_id}"
        files: set[str] = set()
        for k, v in slots.items():
            if k != excl_key:
                for f in v.get("active_files", []):
                    files.add(f)
        return files

    def is_job_active(self, kind: str, key: str, excluding_slot_id: int | None = None) -> bool:
        slots = self._load_and_prune()
        excl_key = f"slot_{excluding_slot_id}" if excluding_slot_id is not None else None
        for k, v in slots.items():
            if excl_key is not None and k == excl_key:
                continue
            if v.get("kind") == kind and str(v.get("key")) == str(key):
                return True
        return False

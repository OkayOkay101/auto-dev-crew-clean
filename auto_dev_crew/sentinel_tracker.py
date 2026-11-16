from __future__ import annotations

import datetime as dt
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .locks import file_lock, locked_json_read, locked_json_write

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
SENTINEL_ISSUES = STATE / "sentinel_issues.json"


def load_sentinel_issues(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or SENTINEL_ISSUES
    return locked_json_read(target, default=[])


def save_sentinel_issues(issues: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or SENTINEL_ISSUES
    target.parent.mkdir(parents=True, exist_ok=True)
    locked_json_write(target, issues)


def record_sentinel_issue(issue_data: dict[str, Any], path: Path | None = None) -> None:
    target = path or SENTINEL_ISSUES
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.parent / f"{target.name}.lock"

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    item = dict(issue_data)
    item.setdefault("first_seen", now_iso)
    item["last_seen"] = now_iso

    with file_lock(lock_file):
        items = locked_json_read(target, default=[])
        existing_idx = next(
            (i for i, x in enumerate(items) if x.get("id") == item.get("id")),
            None
        )
        if existing_idx is not None:
            # Preserve first_seen from original
            item["first_seen"] = items[existing_idx].get("first_seen", item["first_seen"])
            items[existing_idx].update(item)
        else:
            items.append(item)
        locked_json_write(target, items)


def resolve_sentinel_issue(issue_id: str, pr: int | None = None, path: Path | None = None) -> bool:
    target = path or SENTINEL_ISSUES
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.parent / f"{target.name}.lock"

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    with file_lock(lock_file):
        items = locked_json_read(target, default=[])
        found = False
        for item in items:
            if item.get("id") == issue_id:
                item["status"] = "resolved"
                item["resolved_at"] = now_iso
                if pr is not None:
                    item["pr"] = pr
                found = True
                break
        if found:
            locked_json_write(target, items)
        return found


def parse_commit_timestamp(text: str) -> float | None:
    """Accept an ISO-8601 date (as gh api prints it, e.g. 2026-11-08T10:00:00Z) or epoch seconds."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _gh_commit_date(repo_name: str, base: str = "main") -> str:
    res = subprocess.run(
        ["gh", "api", f"repos/{repo_name}/commits/{base}", "--jq", ".commit.committer.date"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "gh api failed")
    return res.stdout


def is_sentinel_debounced(
    repo_cwd: Path | str | None = None,
    debounce_hours: float = 1.0,
    *,
    repo_name: str | None = None,
    fetch_commit_date: Callable[[str], str] | None = None,
) -> bool:
    """Return True when the sentinel may run, i.e. the last commit is >= debounce_hours old.

    The commit checked is the TARGET repo's (repo_name, via fetch_commit_date which returns the
    ISO date of its last commit). repo_cwd is kept for callers that point at a git checkout.
    Nothing given, or any lookup failure, fails open (returns True) so the runner never stalls.
    """
    try:
        if repo_name:
            fetch = fetch_commit_date or _gh_commit_date
            commit_ts = parse_commit_timestamp(fetch(repo_name))
        elif repo_cwd:
            res = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                cwd=Path(repo_cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return True
            commit_ts = float(res.stdout.strip())
        else:
            return True
        if commit_ts is None:
            return True
        return (time.time() - commit_ts) >= (debounce_hours * 3600.0)
    except Exception:
        # gh/git timeout or unexpected error: fail-open safely
        return True

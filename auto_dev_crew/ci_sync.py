"""GitHub Require CI Sync: Precise status check polling and merge gate protection."""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Callable

# After this many polls, if none of the configured required check names exist on the PR
# but other checks do, the gate switches to "every existing check must pass".
MISSING_REQUIRED_POLLS = 3


def fetch_pr_checks(repo: str, pr: int) -> list[dict[str, Any]]:
    """Fetches JSON list of checks for PR via gh CLI.

    gh exits 8 while checks are pending and 1 when a check failed, but with
    ``--json`` stdout is still valid JSON in both cases, so parse stdout whenever it
    is valid JSON instead of treating any non-zero exit as "no checks".
    """
    try:
        res = subprocess.run(
            ["gh", "pr", "checks", str(pr), "-R", repo, "--json", "name,state,bucket"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if not res.stdout or not res.stdout.strip():
            return []
        data = json.loads(res.stdout)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _check_status(c: dict[str, Any]) -> str:
    """Classify one gh check entry as 'fail', 'pass' or 'pending'."""
    conclusion = str(c.get("conclusion") or "").lower()
    bucket = str(c.get("bucket") or "").lower()
    state = str(c.get("state") or "").upper()
    if conclusion in ("failure", "timed_out", "cancelled", "action_required") or bucket in ("fail", "failure", "cancel") or state in ("FAILURE", "TIMED_OUT"):
        return "fail"
    if conclusion == "success" or bucket == "pass" or state == "SUCCESS":
        return "pass"
    return "pending"


def wait_for_required_checks(
    repo: str,
    pr: int,
    required_checks: list[str],
    timeout_seconds: int = 1200,
    poll_interval: float = 15.0,
    max_polls: int | None = None,
    logger: Callable[[str], None] | None = None,
) -> str:
    """Polls PR checks until all required checks complete successfully, fail, or time out.

    If the required check names never show up on the PR (repo has different CI jobs)
    while other checks exist, the gate falls back to "all existing checks must pass".

    Returns:
    - 'pass': all required checks completed with success
    - 'fail': at least one required check failed or was cancelled
    - 'timeout': polling exceeded timeout without conclusion
    - 'none': only if required_checks is empty and repo has no checks
    """
    if not required_checks:
        checks = fetch_pr_checks(repo, pr)
        if not checks:
            return "none"
        statuses = [_check_status(c) for c in checks if isinstance(c, dict)]
        if "fail" in statuses:
            return "fail"
        return "pass" if all(s == "pass" for s in statuses) else "timeout"

    start_time = time.time()
    poll_count = 0
    fallback_all = False

    while True:
        poll_count += 1
        checks = [c for c in fetch_pr_checks(repo, pr) if isinstance(c, dict)]
        checks_by_name = {c.get("name"): c for c in checks}

        if not fallback_all and poll_count >= MISSING_REQUIRED_POLLS and checks \
                and not any(name in checks_by_name for name in required_checks):
            fallback_all = True
            if logger:
                logger(
                    f"[CI-Sync] ไม่พบ required checks ({', '.join(required_checks)}) ใน PR นี้ "
                    f"แต่มี check อื่น — fallback: ทุก check ที่มีอยู่ต้องผ่าน"
                )

        if fallback_all:
            statuses = {c.get("name"): _check_status(c) for c in checks}
            failed = [n for n, s in statuses.items() if s == "fail"]
            if failed:
                if logger:
                    logger(f"[CI-Sync] check ล้มเหลว (fallback): {failed}")
                return "fail"
            if statuses and all(s == "pass" for s in statuses.values()):
                if logger:
                    logger("[CI-Sync] check ที่มีอยู่ผ่านครบทุกตัว (fallback) ✅")
                return "pass"
            pending = [n for n, s in statuses.items() if s != "pass"]
        else:
            # 1. Check for explicit failures
            for name in required_checks:
                c = checks_by_name.get(name)
                if c and _check_status(c) == "fail":
                    if logger:
                        logger(
                            f"[CI-Sync] Check '{name}' ล้มเหลว (bucket={c.get('bucket')}, "
                            f"state={c.get('state')}, conclusion={c.get('conclusion')})"
                        )
                    return "fail"

            # 2. Check if all required checks passed
            if required_checks and all(
                name in checks_by_name and _check_status(checks_by_name[name]) == "pass"
                for name in required_checks
            ):
                if logger:
                    logger(f"[CI-Sync] Required checks ผ่านครบทุกตัว ({', '.join(required_checks)}) ✅")
                return "pass"

            pending = [
                name for name in required_checks
                if name not in checks_by_name or _check_status(checks_by_name[name]) != "pass"
            ]

        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds or (max_polls is not None and poll_count >= max_polls):
            if logger:
                logger(f"[CI-Sync] หมดเวลารอ CI ({elapsed:.0f}s) — checks ที่ยังค้าง: {pending}")
            return "timeout"

        time.sleep(poll_interval)


def _gh_json(args: list[str]) -> Any:
    """Run gh with --json output and return the parsed value, or None when it fails."""
    try:
        res = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
        if res.returncode != 0 or not res.stdout.strip():
            return None
        return json.loads(res.stdout)
    except Exception:
        return None


def wait_for_run_on_sha(
    repo: str,
    branch: str,
    sha: str,
    timeout_seconds: int = 600,
    poll_interval: float = 15.0,
    logger: Callable[[str], None] | None = None,
) -> bool:
    """Wait until a workflow run exists for ``sha`` on ``branch``.

    Without this, the merge gate could read the failed checks of the previous commit
    right after a fix is pushed. Returns False on timeout.
    """
    deadline = time.time() + timeout_seconds
    while True:
        runs = _gh_json(["run", "list", "-R", repo, "--branch", branch, "--limit", "10",
                         "--json", "headSha,status,conclusion"]) or []
        if any(isinstance(r, dict) and r.get("headSha") == sha for r in runs):
            return True
        if time.time() >= deadline:
            if logger:
                logger(f"⚠️ ไม่พบ CI run ของ commit {sha[:8]} บน {branch} ภายใน {timeout_seconds} วินาที")
            return False
        time.sleep(poll_interval)


def fetch_failed_run_log(repo: str, branch: str, max_chars: int = 6000) -> str:
    """Return the tail of the log of the newest failed run on ``branch``.

    Falls back to the run summary when ``--log-failed`` is not available. The caller must
    redact the text before sending it to an agent or to GitHub.
    """
    runs = _gh_json(["run", "list", "-R", repo, "--branch", branch, "--limit", "10",
                     "--json", "databaseId,conclusion"]) or []
    failed = [r for r in runs if isinstance(r, dict) and str(r.get("conclusion") or "").lower() in
              ("failure", "timed_out", "cancelled", "action_required", "startup_failure")]
    if not failed:
        return ""
    run_id = str(failed[0].get("databaseId") or "")
    if not run_id:
        return ""
    texts = []
    for extra in (["--log-failed"], []):
        try:
            res = subprocess.run(["gh", "run", "view", run_id, "-R", repo, *extra],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if res.stdout.strip():
                texts.append(res.stdout)
                break
        except Exception:
            continue
    text = "\n".join(texts)
    return text[-max_chars:]

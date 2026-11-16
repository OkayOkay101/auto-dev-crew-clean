"""Autonomous Upgrades: Graceful Drain, Checkpoints, Convergence, Quorum, Quiet Hours & Safe Revert."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import evaluator, gui_patches, keys, runner

COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
PROTECTED_PREFIXES = (
    "auto_dev_crew/runner.py",
    "runner.py",
    "config.yaml",
    ".github/workflows/",
    ".env",
    "auto_dev_crew/keys.py",
    "keys.py",
    "auto_dev_crew/providers.py",
    "providers.py",
)


# ---------------------------------------------------------------- 1. Graceful Drain Stop / Restart
def _drain_path(state_dir: Path | None = None) -> Path:
    return (state_dir or runner.STATE) / "graceful_drain.json"


def request_graceful_drain(
    restart_args: list[str] | None = None,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Signal active worker slots to finish current PRs/tests and halt cleanly before picking new jobs."""
    path = _drain_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "draining": True,
        "requested_at": int(time.time()),
        "restart_args": list(restart_args) if restart_args else None,
    }
    keys.atomic_write_text(path, json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def read_drain_state(state_dir: Path | None = None) -> dict[str, Any]:
    path = _drain_path(state_dir)
    if not path.exists():
        return {"draining": False, "restart_args": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"draining": False, "restart_args": None}
    except (OSError, ValueError):
        return {"draining": False, "restart_args": None}


def clear_graceful_drain(state_dir: Path | None = None) -> None:
    _drain_path(state_dir).unlink(missing_ok=True)


# ---------------------------------------------------------------- 2. Persistent Session Checkpoint
def save_session_checkpoint(args: list[str], state_dir: Path | None = None) -> dict[str, Any]:
    """Persist explicit runner CLI args (such as --loop --repo owner/name) across GUI restarts."""
    cleaned = [str(a).strip() for a in args if str(a).strip()]
    path = (state_dir or runner.STATE) / "session_checkpoint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"args": cleaned, "saved_at": int(time.time())}
    keys.atomic_write_text(path, json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def load_session_checkpoint(state_dir: Path | None = None) -> list[str] | None:
    path = (state_dir or runner.STATE) / "session_checkpoint.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        args = raw.get("args") if isinstance(raw, dict) else None
        return [str(x) for x in args if str(x).strip()] if isinstance(args, list) and args else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- 3. Repair Convergence Guard (#19)
def should_escalate_repair(scores: list[float]) -> tuple[bool, str]:
    """Wire evaluator.check_convergence(scores) so plateauing repair rounds stop burning quota."""
    if len(scores) >= 2 and evaluator.check_convergence(scores):
        trail = " -> ".join(f"{s:.2f}" for s in scores)
        return True, f"Judge scores plateaued ({trail}); escalating instead of repeating same repair."
    return False, ""


# ---------------------------------------------------------------- 4. Cross-Family Judge Quorum (O24)
def evaluate_with_quorum(
    judge_pool: list[str],
    coder_engine: str,
    score_fn: Callable[[str], float | None],
    *,
    pass_bar: float = 0.75,
    require_quorum_on_fallback: bool = True,
) -> dict[str, Any]:
    """Ensure Coder never grades itself and enforce a 2-Judge tie-breaker if Primary Judge times out."""
    candidates = [eng for eng in judge_pool if eng and eng != coder_engine]
    if not candidates:
        return {
            "passed": False,
            "awaiting_human": True,
            "score": None,
            "reason": "No independent Judge engine available (Coder engine excluded).",
        }

    primary = candidates[0]
    primary_score = score_fn(primary)
    if primary_score is not None:
        return {
            "passed": primary_score >= pass_bar,
            "awaiting_human": False,
            "score": round(primary_score, 3),
            "judges": [primary],
            "fallback_used": False,
        }

    fallbacks = candidates[1:]
    if not fallbacks:
        return {
            "passed": False,
            "awaiting_human": True,
            "score": None,
            "reason": f"Primary Judge ({primary}) timed out and no fallback Judge is available.",
        }

    fb1 = fallbacks[0]
    fb1_score = score_fn(fb1)
    if fb1_score is None or fb1_score < pass_bar:
        return {
            "passed": False,
            "awaiting_human": False,
            "score": fb1_score,
            "judges": [fb1],
            "fallback_used": True,
        }

    if require_quorum_on_fallback:
        if len(fallbacks) < 2:
            return {
                "passed": False,
                "awaiting_human": True,
                "score": round(fb1_score, 3),
                "judges": [fb1],
                "fallback_used": True,
                "reason": (
                    f"Primary Judge ({primary}) timed out; fallback ({fb1}) scored {fb1_score:.2f}, "
                    "pausing for human review per O24 quorum policy."
                ),
            }
        fb2 = fallbacks[1]
        fb2_score = score_fn(fb2)
        both_pass = fb2_score is not None and fb2_score >= pass_bar
        mean_score = round((fb1_score + (fb2_score or 0.0)) / 2.0, 3)
        return {
            "passed": both_pass,
            "awaiting_human": not both_pass,
            "score": mean_score,
            "judges": [fb1, fb2],
            "fallback_used": True,
        }

    return {
        "passed": True,
        "awaiting_human": False,
        "score": round(fb1_score, 3),
        "judges": [fb1],
        "fallback_used": True,
    }


# ---------------------------------------------------------------- 5. Quiet-Hours Nightly Scheduler
def is_persona_window_open(
    schedule_mode: str = "always",
    now_local: dt.datetime | None = None,
    start_hour: int = 0,
    end_hour: int = 6,
) -> bool:
    """User ai-task issues run 24/7; Personas & Deep-Scan optionally run only during quiet hours."""
    if schedule_mode != "nightly":
        return True
    cur = now_local or dt.datetime.now()
    if start_hour <= end_hour:
        return start_hour <= cur.hour < end_hour
    return cur.hour >= start_hour or cur.hour < end_hour


# ---------------------------------------------------------------- 6. Protected-Path & Explainability
def touches_protected_path(changed_files: list[str]) -> list[str]:
    """Return any changed file paths that trigger mandatory human merge review per AGENTS.md."""
    flagged: list[str] = []
    for raw in changed_files:
        norm = raw.strip().replace("\\", "/").lstrip("./")
        if any(norm == p or norm.startswith(p) for p in PROTECTED_PREFIXES):
            flagged.append(norm)
    return sorted(set(flagged))


def explain_gate_in_plain_language(code: str, detail: str = "") -> str:
    """Translate technical gate codes into calm, beginner-friendly explanations."""
    messages = {
        "PROTECTED_PATH": (
            f"Paused for your review because this PR edits protected file(s) ({detail or 'core config/runner'}). "
            "Auto Dev Crew never auto-merges changes to its own core safety files."
        ),
        "GATE_1_UNCONFIRMED": (
            "Stopped before writing code because Gate 1 checked the live file and could not find the bug "
            "described in the issue—preventing unnecessary edits."
        ),
        "GATE_3_WRONG_TARGET": (
            f"Gate 3 blocked this repair attempt because the AI edited {detail or 'generated/test files'} "
            "instead of the real source script named in the issue."
        ),
        "JUDGE_QUORUM_HOLD": (
            "Primary Judge timed out and only one fallback Judge responded, so auto-merge paused "
            "for your quick check (O24 safety rule)."
        ),
        "CONVERGENCE_ESCALATED": (
            "Repair loop stopped early because Judge scores stopped improving across retries, saving your daily quota."
        ),
    }
    return messages.get(code, detail or "Paused safely for owner review.")


# ---------------------------------------------------------------- 7. Safe 1-Click Revert PR Builder
def build_safe_revert_plan(
    repo_raw: str,
    merge_sha: str,
    pr_number: int,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Build a strictly parameterized git revert + gh pr create plan (zero force-push, zero main push)."""
    repo = gui_patches.require_registered_repo(repo_raw, cfg)
    sha = (merge_sha or "").strip()
    if not COMMIT_SHA_RE.fullmatch(sha):
        raise ValueError("Invalid merge commit SHA")
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
        raise ValueError("Invalid PR number")

    branch = f"self/revert-pr-{pr_number}"
    return {
        "repo": repo,
        "branch": branch,
        "commands": [
            ["git", "checkout", "-b", branch, "origin/main"],
            ["git", "revert", "--no-edit", sha],
            ["git", "push", "-u", "origin", branch],
            [
                "gh",
                "pr",
                "create",
                "-R",
                repo,
                "--head",
                branch,
                "--title",
                f"Revert PR #{pr_number}",
                "--body",
                f"Automated safe revert of commit `{sha}` (PR #{pr_number}) requested from Mission Control.",
            ],
        ],
    }

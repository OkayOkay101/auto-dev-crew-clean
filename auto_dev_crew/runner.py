"""Auto Dev Crew: background coding agent that turns GitHub issues into PRs.

Supports concurrent execution slots (Slot 1 reserved for user issues, Slots 2-3 for rotating personas),
central merge queue, active collision detection, and pre-PR agentic-eval rubric gate.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from contextvars import ContextVar
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import threading
import urllib.parse
import venv
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .locks import LockTimeout, file_lock, locked_json_read, locked_json_write
from .file_locks import (
    acquire_file_locks,
    release_file_locks,
    clean_expired_locks,
)
from .procs import run_tree, resolve_cli_exe
from .data_home import DATA_HOME
from .pr_body import build_pr_body
from .test_rerun import failed_test_ids, failure_tail, narrow_test_command
from .redact import redact_gh_args, redact_secrets
from .slots import SlotRegistry
from .evaluator import evaluate_diff, EvaluationResult
from .keys import (
    key_id_for,
    get_key_effective_roles,
    get_opencode_auth_keys,
)
from .loop_breaker import AgentSpawnError, run_opencode_stream
from . import sentinel_tracker
from .triage import classify_task
from .gui_check import run_gui_check
from . import gui_check, playwright_env
from .ci_sync import wait_for_required_checks, wait_for_run_on_sha, fetch_failed_run_log
from .ci_bootstrap import bootstrap_ci, has_ci_workflows
from .guardrails import truncate_tool_output, prune_resolved_evidence
from .stack_detector import detect_stack, format_stack_guidelines
from .context import DEFAULT_TEST_COMMANDS, build_repo_map, format_test_commands, load_repo_notes
from .lessons import format_examples, format_lessons
from .experimental.multi_turn import format_delta_turn
from . import loop_helpers, quality_gates, routing, feature_gen, static_gate
from .skill_registry import SkillRegistry
from .multi_repo import ensure_repo_config, parse_target_repo
from .todo_scan import parse_todo_issue, todo_remediation_prompt, todo_still_present

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
STATE = ROOT / "state"
HISTORY = STATE / "history.json"
ENGINE_STATUS = STATE / "engine_status.json"
KEY_STATUS = STATE / "key_status.json"
MERGE_LOCK = STATE / "merge.lock"
SLOTS_DIR = STATE / "slots"
WORK = DATA_HOME / "work"
VENVS = DATA_HOME / "venvs"
REGISTRY = SlotRegistry(STATE)

# Quota signals are matched as whole words and only against error output (see is_quota_error).
QUOTA_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b429\b", r"\brate[\s_-]?limit", r"\bquota\b", r"\bresource_exhausted\b", r"\bexhausted your\b",
    r"\btoo many requests\b", r"\binsufficient_quota\b", r"\bout of credits\b", r"\bsubscription tier\b",
))
# Regex fragments, searched in lower-cased text. "eof" is a word so "EOFError" does not count.
TRANSIENT_HINTS = ("something went wrong", "502", "503", "504", "bad gateway", "service unavailable",
                   "timeout", "timed out", "connection reset", "connection refused", r"\beof\b", "tls handshake",
                   "could not resolve host", "secondary rate limit", "internal server error")
GH_RETRIES = 4
GH_TIMEOUT_SECONDS = 120
STALE_WORK_HOURS = 24
PERSONA_REST_HOURS = 24
ICONS = {"bolt": "⚡", "sentinel": "🛡️", "palette": "🎨", "quality": "🧪"}

# Concrete goal text the eval judge scores a persona's diff against (F-11). A persona job has no
# issue body, so without this the judge got the placeholder "Persona <key> goal" and scored ~0.7.
PERSONA_GOALS = {
    "bolt": "Performance persona: find one measurable performance improvement (slow loop, redundant I/O, "
            "unneeded copies, missing cache) and keep behaviour identical. Tests must still pass.",
    "sentinel": "Security persona: find one real security issue (unsafe input handling, secret exposure, "
                "unsafe subprocess or file use) and fix it without changing expected behaviour.",
    # ข้อจำกัดด้านล่างมีไว้กัน PR ที่รีวิวแล้วไม่มีคุณค่า (งานตกแต่งล้วน / ด่านป้องกันค่าที่เกิดไม่ได้จริง)
    "palette": "UX/UI persona: fix one real, user-visible problem in one flow (a control with a missing or wrong "
               "accessible name, an error or empty state that is unclear, a label that is wrong). Point to the exact "
               "code that causes it. Do NOT make cosmetic-only changes (spacing, borders, colours, rewording a label "
               "that already works) and do not change core logic.",
    "quality": "Quality persona: fix one concrete defect that a user can actually hit, or add one test that checks real "
               "behaviour. Do NOT add defensive checks for inputs this app cannot receive (for example Symbol or BigInt "
               "values, which localStorage and JSON never produce), and do NOT add tests that only search source code "
               "for strings.",
}


def task_description_for_job(job: Job) -> str:
    """Text the eval judge scores the diff against."""
    if job.kind == "issue":
        return f"{job.title}\n\n{job.body}"
    return PERSONA_GOALS.get(job.key, f"Persona {job.key}: improve one concrete part of the repo without regressions.")


PRESWITCH_RATIO = 0.8  # สลับไปเอนจินถัดไปเมื่อใช้ถึงสัดส่วนนี้ของโควตารายวัน


class QuotaExhausted(Exception):
    def __init__(self, msg: str = "", partial: str = ""):
        super().__init__(msg)
        self.partial = partial  # ผลลัพธ์บางส่วนก่อนโควตาหมด ใช้เป็น handoff ให้เอนจินถัดไป


class EngineBusy(Exception):
    """Engine is temporarily busy (single-concurrency lock held or provider says 1 request at a time)."""


CONCURRENCY_HINTS = (
    "previous request is still running",
    "answers 1 request at a time per ip",
    "1 request at a time",
)


@dataclass
class Job:
    kind: str                 # "issue" | "persona"
    key: str                  # issue number or persona name
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    origin_repo: str | None = None  # repo the issue lives in when executed cross-repo (Target-Repo)


def _todo_prompt_suffix(job: Job) -> str:
    """AI-TODO remediation section for issue jobs created by todo_scan; "" otherwise."""
    parsed = parse_todo_issue(job.body) if job.kind == "issue" else None
    return todo_remediation_prompt(*parsed) if parsed else ""


def _check_todo_removed(job: Job, cwd: Path, entry: dict, slot_id: int | None) -> None:
    parsed = parse_todo_issue(job.body) if job.kind == "issue" else None
    if parsed and todo_still_present(cwd, *parsed):
        log(f"⚠️ [AI-TODO] คอมเมนต์ยังอยู่ใน {parsed[0]} — เอเจนต์ไม่ได้ลบ", slot_id=slot_id)
        entry["todo_left"] = True


for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def log(msg: str, slot_id: int | None = None) -> None:
    prefix = f"[Slot {slot_id}] " if slot_id is not None else ""
    text = redact_secrets(f"{prefix}[{dt.datetime.now():%H:%M:%S}] {msg}")
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="backslashreplace").decode("ascii"), flush=True)

    if slot_id is not None:
        try:
            SLOTS_DIR.mkdir(parents=True, exist_ok=True)
            with (SLOTS_DIR / f"slot_{slot_id}.log").open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass


def run(cmd, cwd=None, check=True, env=None, timeout=None, shell=False) -> subprocess.CompletedProcess:
    # run_tree kills the whole process tree on timeout (cmd.exe -> npm -> node, etc.)
    # shell=True รับได้เฉพาะคำสั่งจาก config.yaml ของเจ้าของ (ไม่ใช่ข้อความจาก issue/PR)
    res = run_tree(cmd, cwd=cwd, env=env, timeout=timeout, shell=shell, stdin=subprocess.DEVNULL,  # nosec B604
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise RuntimeError(f"command failed ({res.returncode}): {cmd}\n{res.stdout}\n{res.stderr}")
    return res


def is_transient(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(h, lowered) for h in TRANSIENT_HINTS)


def is_quota_error(data: dict) -> bool:
    """True only when an ERROR result's error output names a quota or rate-limit condition.

    Successful output is never inspected: agent prose may legitimately mention 429 or quotas.
    """
    if not isinstance(data, dict) or data.get("status") != "ERROR":
        return False
    error_text = " ".join(str(data[k]) for k in ("response", "error", "message") if data.get(k))
    return any(p.search(error_text) for p in QUOTA_PATTERNS)


def gh(*args, cwd=None, check=True) -> str:
    """Run gh, retrying with backoff when GitHub/network fails transiently."""
    # จุดเดียวที่ทุก PR/คอมเมนต์ผ่าน: ลบความลับออกจากค่าหลัง --body ก่อนส่งขึ้น GitHub
    args = redact_gh_args(args)
    for attempt in range(1, GH_RETRIES + 1):
        try:
            res = run(["gh", *args], cwd=cwd, check=False, timeout=GH_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # A hung gh call is treated as transient: retry, then give up.
            if attempt == GH_RETRIES:
                raise RuntimeError(f"gh timed out after {GH_TIMEOUT_SECONDS}s x{GH_RETRIES}: gh {args[:3]}")
            wait = 15 * 2 ** (attempt - 1)
            log(f"gh หมดเวลา {GH_TIMEOUT_SECONDS} วินาที — ลองใหม่ใน {wait} วินาที ({attempt}/{GH_RETRIES})")
            time.sleep(wait)
            continue
        if res.returncode == 0 or not check:
            return res.stdout.strip()
        if attempt == GH_RETRIES or not is_transient(res.stdout + res.stderr):
            raise RuntimeError(f"command failed ({res.returncode}): gh {args[:3]}\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
        wait = 15 * 2 ** (attempt - 1)
        log(f"gh {args[0]} {args[1] if len(args) > 1 else ''} ล้มชั่วคราว — ลองใหม่ใน {wait} วินาที ({attempt}/{GH_RETRIES})")
        time.sleep(wait)


def gh_json(*args):
    out = gh(*args)
    return json.loads(out) if out else []


# ---------------------------------------------------------------- state

def load_cfg(path: Path | str | None = None) -> dict:
    target = Path(path) if path else (ROOT / "config.yaml")
    if not target.exists():
        return {}
    try:
        content = target.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        log(f"⚠️ โหลด config จาก {target} ไม่สำเร็จ: {exc}")
        return {}


def load_history(path: Path | None = None) -> list[dict]:
    target = path or HISTORY
    return locked_json_read(target, default=[])


def save_history(items: list[dict], path: Path | None = None) -> None:
    target = path or HISTORY
    target.parent.mkdir(parents=True, exist_ok=True)
    locked_json_write(target, items)


def append_history(entry: dict, path: Path | None = None) -> None:
    target = path or HISTORY
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_file = target.parent / f"{target.name}.lock"
    with file_lock(lock_file):
        items = locked_json_read(target, default=[])
        # Update existing record if it shares the same branch or PR number, otherwise append
        updated = False
        target_branch = entry.get("branch")
        target_pr = entry.get("pr")
        if target_branch or target_pr:
            for i in reversed(range(len(items))):
                item = items[i]
                if (target_branch and item.get("branch") == target_branch) or (target_pr and item.get("pr") == target_pr):
                    item.update(entry)
                    updated = True
                    break
        if not updated:
            items.append(entry)
        locked_json_write(target, items)


def refresh_history(repo: str, history: list[dict]) -> None:
    for item in history:
        if item.get("repo") == repo and item.get("pr") and item.get("state") in (None, "OPEN"):
            info = gh_json("pr", "view", str(item["pr"]), "-R", repo, "--json", "state")
            if isinstance(info, dict) and info:  # empty gh output -> keep the previous state
                item["state"] = info.get("state")


# ---------------------------------------------------------------- task selection

def paused(repo: str, cfg: dict) -> bool:
    issues = gh_json("issue", "list", "-R", repo, "--state", "open",
                     "--label", cfg["labels"]["pause"], "--json", "number")
    return bool(issues)


def open_ai_prs(repo: str, cfg: dict) -> list[dict]:
    return gh_json("pr", "list", "-R", repo, "--state", "open", "--label", cfg["labels"]["pr"],
                   "--json", "number,title,headRefName")


def get_available_issues(repo: str, cfg: dict) -> list[Job]:
    labels = cfg["labels"]
    raw_issues = gh_json("issue", "list", "-R", repo, "--state", "open", "--label", labels["task"],
                         "--json", "number,title,body,author,labels", "--limit", "100")
    raw_issues.sort(key=lambda i: i["number"])
    jobs = []
    for issue in raw_issues:
        names = {l["name"] for l in issue["labels"]}
        author = (issue.get("author") or {}).get("login") or ""  # deleted users come back as None
        if author.lower() != cfg["owner"].lower():
            continue
        if names & {labels["working"], labels["failed"], labels.get("needs_human", "ai-needs-human")}:
            continue
        jobs.append(Job("issue", str(issue["number"]), issue["title"], issue["body"] or "", labels=list(names)))
    return jobs


def next_issue(repo: str, cfg: dict) -> Job | None:
    issues = get_available_issues(repo, cfg)
    return issues[0] if issues else None


def pick_task_for_slot(
    slot_id: int,
    cfg: dict,
    history: list[dict],
    issues: list[Job],
    registry: SlotRegistry,
    repo_dir: Path | str | None = None,
    repo_name: str | None = None,
    issues_only: bool = False,
) -> Job | None:
    """Select task for specific slot respecting priority allocation:
    - Slot 1: Dedicated solely to user issues (idles if no issue).
    - Slot 2-3: Handle personas, or assist with surplus issues when >= 2 issues exist.
    - issues_only: return only an issue (or None), never a persona.
    """
    # An issue whose PR is still OPEN (waiting for review/CI) is done for now: finish_pr removes
    # ai-working once the PR exists, so without this check the issue was claimed again right away.
    open_pr_issues = {str(h.get("key")) for h in history
                      if h.get("kind") == "issue" and h.get("state") == "OPEN"
                      and (not repo_name or (h.get("origin_repo") or h.get("repo")) == repo_name)}
    unclaimed_issues = [i for i in issues
                        if i.key not in open_pr_issues
                        and not registry.is_job_active("issue", i.key, excluding_slot_id=slot_id)]

    if slot_id == 1:
        # Dedicated Priority Slot for user issues
        return unclaimed_issues[0] if unclaimed_issues else None

    # Slots > 1: Check for user slot assignment
    slot_assign = get_slot_assignment(slot_id, cfg)
    assigned_persona = slot_assign.get("persona") if slot_assign else None

    # Check for surplus user issues or issues directed to assigned persona
    if unclaimed_issues:
        if assigned_persona:
            for iss in unclaimed_issues:
                iss_persona, _ = parse_issue_persona_directive(iss.title, iss.body)
                if iss_persona == assigned_persona:
                    return iss

        active_jobs = registry.get_active_jobs()
        slot_1_has_issue = any(v.get("kind") == "issue" for k, v in active_jobs.items() if k == "slot_1")
        if slot_1_has_issue or len(unclaimed_issues) > 1:
            for iss in reversed(unclaimed_issues):
                if not registry.is_job_active("issue", iss.key, excluding_slot_id=slot_id):
                    return iss

    if issues_only:
        return None

    # Fall back to personas
    enabled = cfg.get("personas", {}).get("enabled", [])
    if not enabled:
        return None
    # O27 quiet hours: issues run 24/7; personas run only inside the configured window (default: always).
    if not _persona_window_open(cfg):
        return None

    # BUG-7: a persona whose PR is still OPEN already has work waiting for review; running it again
    # produced near-identical PRs. refresh_history() keeps OPEN entries in sync with GitHub.
    open_persona_keys = {str(h.get("key")) for h in history
                         if h.get("kind") == "persona" and h.get("state") == "OPEN"
                         and (not repo_name or (h.get("origin_repo") or h.get("repo")) == repo_name)}
    available_personas = [p for p in enabled
                          if p not in open_persona_keys
                          and not registry.is_job_active("persona", p, excluding_slot_id=slot_id)]
    if not available_personas:
        return None

    if assigned_persona and assigned_persona in available_personas:
        return Job("persona", assigned_persona, assigned_persona, "")

    repo_history = [h for h in history if not repo_name or h.get("repo") == repo_name]
    recent = [h for h in repo_history if h.get("kind") == "persona"][-len(enabled):]
    if len(recent) == len(enabled) and all(h.get("state") == "NO_ACTION" for h in recent):
        try:
            last_run = dt.datetime.strptime(recent[-1]["date"], "%Y%m%d-%H%M")
        except (KeyError, ValueError):
            last_run = dt.datetime.now()
        if dt.datetime.now() - last_run < dt.timedelta(hours=PERSONA_REST_HOURS):
            return None

    last = next((h["key"] for h in reversed(repo_history) if h.get("kind") == "persona"), None)
    idx = (enabled.index(last) + 1) % len(enabled) if last in enabled else 0
    debounce_h = float(cfg.get("personas", {}).get("sentinel", {}).get("debounce_hours", 1.0))
    for i in range(len(enabled)):
        candidate = enabled[(idx + i) % len(enabled)]
        if candidate in available_personas:
            if candidate == "sentinel":
                # Debounce on the TARGET repo's last commit, never on auto-dev-crew's own checkout
                if not sentinel_tracker.is_sentinel_debounced(
                        repo_dir, debounce_hours=debounce_h, repo_name=repo_name,
                        fetch_commit_date=lambda name: _target_commit_date(cfg, name)):
                    continue
            return Job("persona", candidate, candidate, "")

    return None


def claim_task_for_slot(
    slot_id: int,
    cfg: dict,
    history: list[dict],
    issues: list[Job],
    registry: SlotRegistry,
    repo_dir: Path | str | None = None,
    repo_name: str | None = None,
    issues_only: bool = False,
) -> Job | None:
    """Atomically pick and register a task for the slot to eliminate TOCTOU race conditions."""
    with file_lock(registry.lock_file):
        job = pick_task_for_slot(slot_id, cfg, history, issues, registry, repo_dir=repo_dir,
                                 repo_name=repo_name, issues_only=issues_only)
        if not job:
            return None
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        branch = f"ai/issue-{job.key}-{stamp}" if job.kind == "issue" else f"ai/{job.key}-{stamp}"
        registry.register_slot(slot_id, job.kind, job.key, branch, [])
        return job


def _target_commit_date(cfg: dict, repo_name: str) -> str:
    """ISO date of the last commit on the target repo's base branch (via gh)."""
    base = next((r.get("base") for r in cfg.get("repos", []) if r.get("name") == repo_name and r.get("base")), "main")
    return gh("api", f"repos/{repo_name}/commits/{base}", "--jq", ".commit.committer.date")


# ---------------------------------------------------------------- workspace

def repo_cfg(cfg: dict, name: str) -> dict:
    match = next((r for r in cfg.get("repos", []) if r.get("name") == name), None)
    if match is None:
        raise ValueError(f"ไม่พบ repo {name!r} ใน config")
    return match


def venv_path(repo: str, slot_id: int | None = None) -> Path:
    slot_suffix = f"_slot_{slot_id}" if slot_id is not None else ""
    return VENVS / f"{repo.replace('/', '__')}{slot_suffix}"


def venv_env(repo: str, slot_id: int | None = None) -> dict:
    path = venv_path(repo, slot_id)
    if not path.exists():
        log(f"สร้าง venv สำหรับ {repo} ({path.name})", slot_id=slot_id)
        venv.create(path, with_pip=True)
    bindir = path / ("Scripts" if os.name == "nt" else "bin")
    # ขั้นตอนทดสอบรันโค้ดที่ AI เขียน: ห้ามส่งต่อค่าที่ export มาจาก .env
    env = {k: v for k, v in os.environ.items() if k not in _DOTENV_EXPORTED}
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    env["VIRTUAL_ENV"] = str(path)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_steps(steps: list[str], cwd: Path, env: dict) -> tuple[bool, str]:
    out = []
    for step in steps:
        if "requirements.txt" in step and not (cwd / "requirements.txt").exists():
            out.append(f"$ {step}\n(ข้าม: ไม่พบ requirements.txt ใน {cwd.name})")
            continue
        try:
            # shell=True ตั้งใจ: step มาจาก config.yaml ที่เจ้าของ repo เขียน (เทียบเท่าคำสั่ง test ใน repo เอง)
            res = run(step, cwd=cwd, env=env, check=False, shell=True, timeout=1800)  # nosec B604
        except subprocess.TimeoutExpired:
            out.append(f"$ {step}\n(timed out after 1800s / หมดเวลา — ยกเลิกคำสั่งและโปรเซสลูกทั้งหมดแล้ว)")
            return False, "\n".join(out)
        out.append(f"$ {step}\n{res.stdout[-4000:]}\n{res.stderr[-4000:]}")
        if res.returncode != 0:
            return False, "\n".join(out)
    return True, "\n".join(out)


def force_rmtree(path: Path) -> None:
    """rmtree that also deletes read-only files. git writes objects read-only, and on Windows
    plain rmtree(ignore_errors=True) then silently leaves the whole clone behind."""
    def _make_writable_and_retry(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onexc=_make_writable_and_retry)


def clean_work() -> None:
    """Drop scratch clones left behind by failed/NO_ACTION/killed jobs."""
    if not WORK.exists():
        return
    cutoff = time.time() - STALE_WORK_HOURS * 3600
    for path in WORK.iterdir():
        try:
            if path.stat().st_mtime < cutoff:
                force_rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        except OSError:
            pass


# Untracked files matching these never reach a PR. git's info/exclude only hides untracked
# files, so a repo that really tracks e.g. result.json still gets its changes committed.
ARTIFACT_EXCLUDES = ("__pycache__/", "*.pyc", "*.pyo", ".pytest_cache/",
                     "/result.json", "*.result.json")


def clean_build_artifacts(cwd: Path) -> None:
    """Exclude compiled artifacts and agent scratch reports, and remove caches, before git operations."""
    exclude_file = cwd / ".git" / "info" / "exclude"
    if exclude_file.parent.exists():
        try:
            existing = exclude_file.read_text(encoding="utf-8", errors="replace") if exclude_file.exists() else ""
            have = set(existing.splitlines())
            missing = [r for r in ARTIFACT_EXCLUDES if r not in have]
            if missing:
                with exclude_file.open("a", encoding="utf-8") as f:
                    f.write("\n" + "\n".join(missing) + "\n")
        except OSError:
            pass
    for pyc_dir in cwd.glob("**/__pycache__"):
        import shutil
        shutil.rmtree(pyc_dir, ignore_errors=True)
    for pyc_file in cwd.glob("**/*.pyc"):
        try:
            pyc_file.unlink(missing_ok=True)
        except OSError:
            pass


def clone(repo: str, base: str, branch: str, slot_id: int | None = None) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    prefix = f"slot-{slot_id}-{repo.split('/')[1]}-" if slot_id is not None else f"{repo.split('/')[1]}-"
    dest = Path(tempfile.mkdtemp(prefix=prefix, dir=WORK))
    gh("repo", "clone", repo, str(dest), "--", "--depth", "50", "--branch", base)
    run(["git", "checkout", "-b", branch], cwd=dest)
    clean_build_artifacts(dest)
    return dest


# ---------------------------------------------------------------- agent

def load_dotenv(path: Path | None = None) -> dict[str, str]:
    if path is None:
        path = ROOT / ".env"
    env: dict[str, str] = {}
    if not path.exists():
        return env
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return env
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        env[k] = v
    return env


_DOTENV_EXPORTED: set[str] = set()


def export_dotenv_to_environ(path: Path | None = None) -> int:
    """Copy .env values into os.environ for keys not already set. Returns how many were exported.

    Needed because child processes (agent CLIs such as opencode, whose opencode.json may
    reference provider env vars) receive dict(os.environ) and a plain CLI run does not otherwise
    read .env. resolve_key_value / get_engine_key_entries already read load_dotenv() themselves.
    Exported names are recorded in _DOTENV_EXPORTED so venv_env keeps them away from the
    AI-written test steps.
    """
    exported = 0
    for k, v in load_dotenv(path).items():
        if v and k not in os.environ:
            os.environ[k] = v
            _DOTENV_EXPORTED.add(k)
            exported += 1
    return exported


def resolve_key_value(val: str, env_vars: dict[str, str] | None = None) -> str:
    if not isinstance(val, str):
        return ""
    val = val.strip()
    if not val:
        return ""
    dotenv_vars = load_dotenv() if env_vars is None else {}
    combined_env = {**dotenv_vars, **os.environ, **(env_vars or {})}
    m = re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", val)
    if m:
        return combined_env.get(m.group(1), "")
    m = re.match(r"^\$([A-Za-z_][A-Za-z0-9_]*)$", val)
    if m:
        return combined_env.get(m.group(1), "")
    return val


def key_engine_name(eng: dict) -> str:
    """Engine name used in key ids. Must match gui.usage_summary and keys.get_keys_catalog."""
    return eng.get("name", eng.get("command", "default"))


def auth_provider_for(eng: dict) -> str:
    """Provider id used to look up the OpenCode auth store.

    ``auth_provider`` in config wins; otherwise it is derived from the engine name by
    dropping the ``opencode-`` prefix (the old naming scheme).
    """
    explicit = str(eng.get("auth_provider") or "").strip()
    if explicit:
        return explicit.lower()
    return key_engine_name(eng).replace("opencode-", "").lower()


def get_engine_key_entries(
    eng: dict,
    env_vars: dict[str, str] | None = None,
    role: str | None = None,
    allow_fallback: bool = True,
) -> list[tuple[str, str]]:
    """Return (key_id, key_value) pairs for the engine, filtered by role.

    key_id is stable (env var name or value hash), so it does not change when the role
    filter or the key order changes (HIGH-06).
    """
    if env_vars is None:
        env_vars = load_dotenv()
    engine_name = key_engine_name(eng)
    raw_keys = []
    if "api_keys" in eng and isinstance(eng["api_keys"], list):
        raw_keys.extend(eng["api_keys"])
    elif "api_key" in eng and eng["api_key"]:
        raw_keys.append(eng["api_key"])

    if not any(raw_keys):
        from .keys import PROVIDERS_CATALOG
        cat_meta = PROVIDERS_CATALOG.get(eng.get("name", ""))
        if cat_meta and cat_meta.get("default_keys"):
            raw_keys = [f"${{{dk}}}" for dk in cat_meta["default_keys"]]

    raw_engine_roles = eng.get("roles")
    engine_roles = {str(r).strip().lower() for r in raw_engine_roles} if isinstance(raw_engine_roles, list) else None
    resolved_items: list[tuple[str, str, list[str]]] = []  # (key_id, value, roles)
    # OpenCode Auth (~/.local/share/opencode/auth.json) is a fallback when the env var is unset,
    # matching keys.py's Control Hub view. Env vars always win.
    auth_provider = auth_provider_for(eng)
    auth_keys = None
    for k in raw_keys:
        if not k:
            continue
        k_str = str(k).strip()
        val = resolve_key_value(k_str, env_vars)
        m = re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", k_str) or re.match(r"^\$([A-Za-z_][A-Za-z0-9_]*)$", k_str)
        var_name = m.group(1) if m else ""
        if not val and var_name:
            if auth_keys is None:
                auth_keys = get_opencode_auth_keys()
            val = (auth_keys.get(auth_provider) or "").strip()
        if not val:
            continue
        roles = get_key_effective_roles(var_name) if var_name else ["coder"]
        if engine_roles is not None:  # engine-level `roles` narrows the key's roles for this engine only
            roles = [r for r in roles if r in engine_roles]
        resolved_items.append((key_id_for(engine_name, var_name=var_name, value=val), val, roles))

    if role is None:
        return [(kid, val) for kid, val, _ in resolved_items]

    target_role = role.lower()
    matched = [(kid, val) for kid, val, roles in resolved_items if target_role in roles]
    if matched:
        return matched

    if allow_fallback and target_role in ("judge", "scan"):
        return [(kid, val) for kid, val, roles in resolved_items if "coder" in roles]

    return []


def get_engine_keys(
    eng: dict,
    env_vars: dict[str, str] | None = None,
    role: str | None = None,
    allow_fallback: bool = True,
) -> list[str]:
    return [val for _, val in get_engine_key_entries(eng, env_vars, role=role, allow_fallback=allow_fallback)]

def get_engines(cfg: dict) -> list[dict]:
    if "engines" in cfg and isinstance(cfg["engines"], list):
        return cfg["engines"]
    if "engine" in cfg and isinstance(cfg["engine"], dict):
        eng = dict(cfg["engine"])
        eng.setdefault("name", eng.get("command", "default"))
        eng.setdefault("provider", eng.get("command", "default"))
        eng.setdefault("trains_on_data", False)
        eng.setdefault("enabled", True)
        return [eng]
    return []


def load_engine_status() -> dict:
    return locked_json_read(ENGINE_STATUS, default={})


def save_engine_status(status: dict) -> None:
    STATE.mkdir(exist_ok=True)
    locked_json_write(ENGINE_STATUS, status)


def mark_engine_quota(engine_name: str, cooldown_hours: float = 1.0, error: str = "") -> None:
    with file_lock(STATE / "engine_status.json.lock"):
        status = locked_json_read(ENGINE_STATUS, default={})
        status[engine_name] = {
            "cooldown_until": time.time() + cooldown_hours * 3600,
            "last_error": error[:500],
            "updated_at": dt.datetime.now().isoformat(timespec="seconds")
        }
        locked_json_write(ENGINE_STATUS, status)


def _cool_down_after_timeout(cfg: dict, eng_name: str, reason: str, slot_id: int | None) -> None:
    """Rest an engine that just timed out so the next call does not retry it straight away."""
    minutes = cfg.get("engine_timeout_cooldown_minutes", 20)
    if minutes <= 0:
        return
    mark_engine_quota(eng_name, cooldown_hours=minutes / 60, error=reason[:300])
    log(f"⏸️ Engine {eng_name} หมดเวลา — พัก {minutes} นาที", slot_id=slot_id)


def load_key_status() -> dict:
    return locked_json_read(KEY_STATUS, default={})


def save_key_status(status: dict) -> None:
    STATE.mkdir(exist_ok=True)
    locked_json_write(KEY_STATUS, status)


def mark_key_quota(key_id: str, cooldown_hours: float = 1.0, error: str = "") -> None:
    with file_lock(STATE / "key_status.json.lock"):
        status = locked_json_read(KEY_STATUS, default={})
        status[key_id] = {
            "cooldown_until": time.time() + cooldown_hours * 3600,
            "last_error": error[:500],
            "updated_at": dt.datetime.now().isoformat(timespec="seconds")
        }
        locked_json_write(KEY_STATUS, status)


def get_active_engine_key(entries: list[tuple[str, str]], status: dict | None = None) -> tuple[str, str] | tuple[None, None]:
    """Return the first (key_id, value) whose cooldown has expired, or (None, None)."""
    if not entries:
        return None, None
    if status is None:
        status = load_key_status()
    now = time.time()
    for key_id, key in entries:
        cooldown_until = status.get(key_id, {}).get("cooldown_until", 0)
        if now >= cooldown_until:
            return key_id, key
    return None, None


def today_usage(engine_name: str) -> tuple[int, int]:
    """จำนวนคำขอและ tokens ของเอนจินนี้ในวันนี้ จาก usage.jsonl"""
    path = STATE / "usage.jsonl"
    if not path.exists():
        return 0, 0
    today = dt.date.today().isoformat()
    requests = tokens = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("engine_name") != engine_name or not str(row.get("ts", "")).startswith(today):
            continue
        try:
            row_tokens = int(row.get("tokens") or 0)
        except (TypeError, ValueError):
            continue
        requests += 1
        tokens += row_tokens
    return requests, tokens


def near_daily_limit(eng: dict) -> bool:
    """True เมื่อใช้ถึง PRESWITCH_RATIO ของ daily_request_limit หรือ daily_token_limit ที่ตั้งไว้ใน config"""
    req_lim = eng.get("daily_request_limit")
    tok_lim = eng.get("daily_token_limit")
    if not req_lim and not tok_lim:
        return False
    requests, tokens = today_usage(eng.get("name", eng.get("command", "")))
    if req_lim and requests >= PRESWITCH_RATIO * req_lim:
        return True
    return bool(tok_lim and tokens >= PRESWITCH_RATIO * tok_lim)


def build_handoff_prompt(prompt: str, partial: str, from_engine: str) -> str:
    """prompt เดิม + ผลบางส่วนจากเอนจินก่อนหน้า เพื่อให้เอนจินถัดไปทำต่อจากจุดที่ค้าง"""
    if not partial.strip():
        return prompt
    return (prompt + f"\n\n---\n[HANDOFF] เอนจิน {from_engine} โควตาหมดกลางงาน ผลลัพธ์บางส่วนที่ได้แล้ว:\n"
            + partial[-4000:] + "\n\nทำงานต่อจากจุดนี้ ไม่ต้องเริ่มใหม่ทั้งหมด")


def engine_skip_reason(eng: dict, status: dict | None = None, key_status: dict | None = None, role: str | None = None) -> str | None:
    """เหตุผลที่ engine นี้ใช้งานไม่ได้ตอนนี้ (ข้อความภาษาไทย) หรือ None ถ้าพร้อมใช้งาน"""
    name = eng.get("name", "")
    if not eng.get("enabled", True):
        return "ปิดใช้งานใน config (enabled: false)"
    if near_daily_limit(eng):
        return "ใกล้ถึงโควตารายวันแล้ว"
    configured_keys = [k for k in (eng.get("api_keys") or ([eng["api_key"]] if eng.get("api_key") else [])) if k]
    if not configured_keys:
        from .keys import PROVIDERS_CATALOG
        cat_meta = PROVIDERS_CATALOG.get(name)
        if cat_meta and cat_meta.get("default_keys"):
            configured_keys = [f"${{{dk}}}" for dk in cat_meta["default_keys"]]
    if status is None:
        status = load_engine_status()
    # Engine-level cooldown (timeout rest, all keys exhausted) applies to keyed engines too.
    cooldown_until = status.get(name, {}).get("cooldown_until", 0)
    if cooldown_until > time.time():
        return f"กำลังพักถึง {dt.datetime.fromtimestamp(cooldown_until):%H:%M}"
    if configured_keys:
        entries = get_engine_key_entries(eng, role=role)
        if not entries:
            return "ไม่มีคีย์ที่ใช้ได้ (ตัวแปรคีย์ใน .env ไม่มีหรือว่าง หรือไม่ตรงกับบทบาท)"
        key_id, _ = get_active_engine_key(entries, status=key_status)
        if key_id is None:
            return f"คีย์ทั้ง {len(entries)} ตัวพักหรือโควตาหมด"
    return None


def is_engine_ready(eng: dict, status: dict | None = None, key_status: dict | None = None, role: str | None = None) -> bool:
    return engine_skip_reason(eng, status, key_status, role=role) is None


def engine_cmd(eng: dict) -> list[str]:
    path = resolve_cli_exe(eng["command"], eng.get("path") or None)
    if eng["command"] == "agy":
        return [path, "--dangerously-skip-permissions", "--output-format", "json",
                "--model", eng["model"], "-p"]
    if eng["command"] == "opencode":
        return [path, "run", "--auto", "--format", "json", "-m", eng["model"]]
    return [path, "--yolo", "--output-format", "json", "-m", eng["model"], "-p"]


def _is_single_concurrency(eng: dict) -> bool:
    """True for engines that allow only one request at a time (e.g. Pollinations, 1 req/IP)."""
    prov = (eng.get("provider") or "").lower()
    name = (eng.get("name") or "").lower()
    return bool(eng.get("single_concurrency") or "pollinations" in prov or "pollinations" in name)


def safe_engine_filename(name: str) -> str:
    """ชื่อ engine ที่ปลอดภัยสำหรับใช้เป็นชื่อไฟล์ (ไม่มี / : ฯลฯ)"""
    return re.sub(r"[^\w.-]", "_", str(name))


def _scan_kwargs(role: str | None) -> dict:
    """ส่ง role ให้ call_single_engine เฉพาะบทบาท scan (บทบาทอื่นคงการเรียกเดิม)"""
    return {"role": "scan"} if role == "scan" else {}


def call_single_engine(eng: dict, prompt: str, cwd: Path, active_key: str | None = None, *, role: str | None = None) -> dict:
    if not _is_single_concurrency(eng):
        return _execute_single_engine(eng, prompt, cwd, active_key, role=role)
    eng_name = key_engine_name(eng)
    lock_path = STATE / "engine_locks" / f"{safe_engine_filename(eng_name)}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_timeout = float(eng.get("lock_timeout_seconds", 90.0))
    try:
        with file_lock(lock_path, timeout=lock_timeout):
            # role must reach the locked call too: without it a scan reply is cut at 2,500 chars
            # (broken JSON) and the scan read-only config is skipped.
            return _execute_single_engine(eng, prompt, cwd, active_key, role=role)
    except LockTimeout as exc:
        raise EngineBusy(f"Engine {eng_name} กำลังถูกใช้งานโดย Slot อื่น (รอล็อกเกิน {lock_timeout}s)") from exc


def _idle_timeout_seconds(eng: dict) -> float:
    """OpenCode no-output limit in seconds: unset/None → 5 min; 0 or negative → 0 (disabled)."""
    minutes = eng.get("idle_timeout_minutes")
    minutes = 5.0 if minutes is None else float(minutes)
    return max(minutes, 0.0) * 60


_AGENT_SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)
_OPENCODE_ENV_REF = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def scrub_agent_env(base: dict, config_path: Path) -> dict:
    """ตัดตัวแปรที่เป็นความลับออกจาก env ของเอเจนต์ (มีสิทธิ์ shell ในโฟลเดอร์งาน)
    คงไว้เฉพาะชื่อที่ opencode.json อ้างถึงด้วย {env:NAME} เท่านั้น
    เช่น GH_TOKEN หรือ DB password ที่อยู่ในเครื่องจะไม่ถูกส่งให้เอเจนต์"""
    try:
        refs = set(_OPENCODE_ENV_REF.findall(config_path.read_text(encoding="utf-8")))
    except OSError:
        refs = set()
    return {k: v for k, v in base.items() if k in refs or not _AGENT_SECRET_NAME.search(k)}


SCAN_READONLY_OPENCODE_CONFIG = {
    # บทบาท scan ห้ามแก้ไฟล์หรือรันคำสั่ง: ทับ config ของ OpenCode ด้วย OPENCODE_CONFIG_CONTENT
    "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"},
    "tools": {"write": False, "edit": False, "bash": False},
}


def _execute_single_engine(eng: dict, prompt: str, cwd: Path, active_key: str | None = None, *,
                           role: str | None = None) -> dict:
    timeout = eng.get("timeout_minutes", 30) * 60
    try:
        base_cmd = engine_cmd(eng)
    except RuntimeError as exc:  # executable not found or only a .cmd shim available
        raise AgentSpawnError(str(exc)) from exc
    env = None
    if eng["command"] == "opencode":
        (ROOT / ".opencode-runner").mkdir(exist_ok=True)
        env = {**scrub_agent_env(os.environ, ROOT / "opencode.json"), "OPENCODE_CONFIG": str(ROOT / "opencode.json"),
               "OPENCODE_CONFIG_DIR": str(ROOT / ".opencode-runner"), "OPENCODE_DISABLE_CLAUDE_CODE": "1",
               "PWD": str(cwd)}
        if role == "scan":
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(SCAN_READONLY_OPENCODE_CONFIG)
        if active_key:
            env["OPENAI_API_KEY"] = active_key
            prov = (eng.get("provider") or "").lower()
            name = (eng.get("name") or "").lower()
            if "nvidia" in prov or "nvidia" in name:
                env["NVIDIA_API_KEY"] = active_key
            elif "groq" in prov or "groq" in name:
                env["GROQ_API_KEY"] = active_key
            elif "mistral" in prov or "mistral" in name:
                env["MISTRAL_API_KEY"] = active_key
            elif "gemini" in prov or "google" in prov or "gemini" in name:
                env["GEMINI_API_KEY"] = active_key
                env["GOOGLE_GENERATIVE_AI_API_KEY"] = active_key
            elif "cerebras" in prov or "cerebras" in name:
                env["CEREBRAS_API_KEY"] = active_key
            elif "cloudflare" in prov or "cloudflare" in name:
                env["CLOUDFLARE_API_KEY"] = active_key
            elif "pollinations" in prov or "pollinations" in name:
                env["OPENAI_BASE_URL"] = "https://gen.pollinations.ai/v1"
                env["POLLINATIONS_API_KEY"] = active_key
                env["POLLINATIONS_API_KEY_1"] = active_key
            elif "deepseek" in prov or "deepseek" in name:
                env["DEEPSEEK_API_KEY"] = active_key
            if prov.strip() == "opencode":
                # OpenCode's own provider reads OPENCODE_API_KEY, not the numbered _1 name.
                env["OPENCODE_API_KEY"] = active_key
            if eng.get("api_key_env"):
                env[eng["api_key_env"]] = active_key
            for k_spec in eng.get("api_keys", []) or []:
                m_var = re.match(r"^\$\{([^}]+)\}$", str(k_spec).strip())
                if m_var:
                    env[m_var.group(1)] = active_key

    if eng["command"] == "opencode":
        prune_raw_logs(STATE / "runs", keep=RAW_LOG_KEEP)
        raw_log = STATE / "runs" / f"opencode-raw-{dt.datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}-{safe_engine_filename(eng.get('name', 'default'))}.log"
        log(f"📝 บันทึก raw stdout ของ OpenCode (ปิดบัง secret แล้ว) ที่ {raw_log}")
        data = run_opencode_stream(
            base_cmd=base_cmd,
            prompt=prompt,
            cwd=cwd,
            env=env,
            timeout=timeout,
            model=eng.get("model"),
            logger=log,
            raw_log=raw_log,
            idle_timeout=_idle_timeout_seconds(eng),
            max_response_chars=SCAN_RESPONSE_MAX_CHARS if role == "scan" else 2500,
        )
        text = data.get("response", "")
    else:
        try:
            res = run(base_cmd + [prompt], cwd=cwd, check=False, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            res = subprocess.CompletedProcess([], 1, "", f"agent timed out after {timeout}s")
        except OSError as exc:  # WinError 206 (argv too long), missing binary, etc.
            raise AgentSpawnError(f"Failed to spawn {eng['command']}: {exc}") from exc
        text = (res.stdout + res.stderr)
        try:
            data = json.loads(res.stdout[res.stdout.index("{"):])
        except ValueError:
            data = {"status": "ERROR", "response": text[-2000:]}
        if data.get("status") != "SUCCESS":
            # Anything that is not an explicit success is an error; keep the raw output so the
            # quota check and the log still see the agent's message.
            data = {**data, "status": "ERROR", "response": data.get("response") or text[-2000:]}

    if data.get("status") != "SUCCESS" and any(h in text.lower() for h in CONCURRENCY_HINTS):
        raise EngineBusy(f"คำขอชนกับคำขออื่นบน IP เดียวกัน: {text[-200:]}")

    quota = is_quota_error(data)
    record_usage(eng, data, quota)
    if quota:
        raise QuotaExhausted(text[-500:], partial=data.get("partial_text") or "")
    return data


RAW_LOG_KEEP = 100  # จำนวน raw OpenCode log ล่าสุดที่เก็บไว้ (0 = ไม่ลบ)
SCAN_RESPONSE_MAX_CHARS = 60_000  # role=scan: ผลสแกนยาวกว่า 2,500 ตัวอักษรได้ (ไม่งั้น JSON เสียทั้งกลุ่ม)


def prune_raw_logs(runs_dir: Path, keep: int = RAW_LOG_KEEP) -> int:
    """ลบ opencode-raw-*.log เก่า เก็บ `keep` ไฟล์ล่าสุด (ชื่อขึ้นต้นด้วยเวลา จึงเรียงตามเวลาได้).
    คืนจำนวนไฟล์ที่ลบ; ข้อผิดพลาดของไฟล์เดียวไม่ทำให้การตัดไฟล์อื่นหยุด."""
    if keep <= 0 or not runs_dir.is_dir():
        return 0
    files = sorted(runs_dir.glob("opencode-raw-*.log"), key=lambda p: p.name)
    removed = 0
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _busy_wait_budget(cfg: dict) -> tuple[float, float]:
    """(seconds between retries, total seconds to wait) when every engine is busy (BUG-6)."""
    par = cfg.get("parallel") or {}
    retry = max(float(par.get("busy_retry_seconds", 30)), 1.0)
    max_wait = max(float(par.get("busy_max_wait_minutes", 15)), 0.0) * 60
    return retry, max_wait


def call_agent(cfg: dict, prompt: str, cwd: Path, slot_id: int | None = None, role: str = "coder",
               *, engine_name: str | None = None) -> dict:
    """Run one agent call. If every engine was only busy (EngineBusy), wait and retry until the budget
    (parallel.busy_max_wait_minutes) is used up, then re-raise EngineBusy. A busy engine is not a failure."""
    retry_s, max_wait_s = _busy_wait_budget(cfg)
    waited = 0.0
    while True:
        try:
            return _call_agent_pass(cfg, prompt, cwd, slot_id, role, engine_name=engine_name)
        except EngineBusy:
            if waited + retry_s > max_wait_s:
                raise
            waited += retry_s
            log(f"⏳ ทุก Engine ไม่ว่าง — รอ {retry_s:.0f}s แล้วลองใหม่ ({waited:.0f}/{max_wait_s:.0f}s)", slot_id=slot_id)
            time.sleep(retry_s)


def _call_agent_pass(cfg: dict, prompt: str, cwd: Path, slot_id: int | None, role: str,
                     *, engine_name: str | None = None) -> dict:
    engines = get_engines(cfg)
    if not engines:
        raise RuntimeError("ไม่พบการตั้งค่า engine ใน config.yaml")
    if engine_name is not None:
        engines = [e for e in engines if key_engine_name(e) == engine_name]
        if not engines:
            raise ValueError(f"ไม่พบ engine ชื่อ '{engine_name}' ใน config.yaml")
    status = load_engine_status()
    key_status = load_key_status()
    candidates = []
    for e in engines:
        reason = engine_skip_reason(e, status, key_status, role=role)
        if reason is None and role == "scan" and e.get("command") != "opencode":
            # บทบาท scan ใช้ได้เฉพาะ OpenCode เพราะจำกัดเครื่องมือได้ผ่าน config; CLI อื่นรันด้วย --yolo
            log(f"⏭️ ข้าม Engine {key_engine_name(e)} [บทบาท: scan] — ไม่รองรับโหมดอ่านอย่างเดียว", slot_id=slot_id)
            continue
        if reason is None:
            candidates.append(e)
        else:
            log(f"⏭️ ข้าม Engine {key_engine_name(e)} [บทบาท: {role}] — {reason}", slot_id=slot_id)
    if not candidates:
        active_cooldowns = [f"{e.get('name')}: พักถึง {dt.datetime.fromtimestamp(status[e.get('name')]['cooldown_until']):%H:%M}"
                            for e in engines if e.get("name") in status and status[e.get("name")].get("cooldown_until", 0) > time.time()]
        msg = f"ทุก Engine สำหรับบทบาท '{role}' โควตาหมดหรือพักหลังหมดเวลา (" + ", ".join(active_cooldowns) + ")" if active_cooldowns else f"ไม่มี Engine ที่เปิดใช้งานสำหรับบทบาท '{role}'"
        raise QuotaExhausted(msg)

    last_exc: Exception | None = None
    saw_quota = False  # True when at least one engine or key failed because of quota
    saw_busy = False  # True when at least one engine was busy (EngineBusy)
    other_failure = False  # True when at least one engine failed for a reason other than busy/quota
    current_prompt = prompt  # เปลี่ยนเป็น handoff prompt เมื่อสลับจากเอนจินที่โควตาหมดกลางงาน

    for eng in candidates:
        eng_name = key_engine_name(eng)
        entries = get_engine_key_entries(eng, role=role)
        if entries:
            while True:
                key_id, active_key = get_active_engine_key(entries, key_status)
                if key_id is None:
                    other_failure = True
                    mark_engine_quota(eng_name, cooldown_hours=1.0, error=str(last_exc or "all keys exhausted"))
                    log(f"⚠️ Engine {eng_name} คีย์ทั้งหมด ({len(entries)} คีย์) โควตาหมด — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                    break
                key_pos = next(i for i, (kid, _) in enumerate(entries) if kid == key_id) + 1
                role_label = f" [บทบาท: {role}]" if role else ""
                log(f"เรียกเอเจนต์ด้วย {eng_name} ({eng.get('provider', eng['command'])}){role_label} [คีย์ #{key_pos}/{len(entries)}]", slot_id=slot_id)
                try:
                    data = _call_with_usage_key(key_id, call_single_engine, eng, current_prompt, cwd,
                                                active_key=active_key, **_scan_kwargs(role))
                except AgentSpawnError as exc:
                    last_exc = exc
                    other_failure = True
                    log(f"⚠️ Engine {eng_name} เปิดโปรเซสไม่ได้ ({str(exc)[:200]}) — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                    break
                except EngineBusy as exc:
                    last_exc = exc
                    saw_busy = True
                    log(f"⚠️ Engine {eng_name} ติดข้อจำกัด Concurrency ({str(exc)[:200]}) — ข้ามไป Engine ถัดไปชั่วคราว (ไม่ติดคูลดาวน์)...", slot_id=slot_id)
                    break
                except QuotaExhausted as exc:
                    saw_quota = True
                    last_exc = exc
                    current_prompt = build_handoff_prompt(prompt, exc.partial, eng_name)
                    mark_key_quota(key_id, cooldown_hours=1.0, error=str(exc))
                    key_status = load_key_status()
                    next_id, _ = get_active_engine_key(entries, key_status)
                    if next_id is not None:
                        log(f"⚠️ คีย์ #{key_pos} ของ {eng_name} โควตาหมด -> สลับไปคีย์ถัดไปทันที...", slot_id=slot_id)
                    else:
                        mark_engine_quota(eng_name, cooldown_hours=1.0, error=str(exc))
                        log(f"⚠️ Engine {eng_name} โควตาหมด — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                        break
                    continue
                if data.get("status") == "ERROR":
                    reason = data.get("response") or ""
                    last_exc = RuntimeError(reason)
                    other_failure = True
                    if "timed out" in reason.lower():
                        _cool_down_after_timeout(cfg, eng_name, reason, slot_id)
                        log(f"⚠️ Engine {eng_name} หมดเวลาตอบกลับ — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                    else:
                        log(f"⚠️ Engine {eng_name} ตอบกลับด้วยข้อผิดพลาด — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                    break
                data["engine_used"] = eng_name
                data["key_index"] = key_pos - 1
                return data
        else:
            log(f"เรียกเอเจนต์ด้วย {eng_name} ({eng.get('provider', eng['command'])})", slot_id=slot_id)
            try:
                data = call_single_engine(eng, current_prompt, cwd, **_scan_kwargs(role))
            except AgentSpawnError as exc:
                last_exc = exc
                other_failure = True
                log(f"⚠️ Engine {eng_name} เปิดโปรเซสไม่ได้ ({str(exc)[:200]}) — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                continue
            except EngineBusy as exc:
                last_exc = exc
                saw_busy = True
                log(f"⚠️ Engine {eng_name} ติดข้อจำกัด Concurrency ({str(exc)[:200]}) — ข้ามไป Engine ถัดไปชั่วคราว (ไม่ติดคูลดาวน์)...", slot_id=slot_id)
                continue
            except QuotaExhausted as exc:
                saw_quota = True
                last_exc = exc
                current_prompt = build_handoff_prompt(prompt, exc.partial, eng_name)
                mark_engine_quota(eng_name, cooldown_hours=1.0, error=str(exc))
                log(f"⚠️ Engine {eng_name} โควตาหมด — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                continue
            if data.get("status") == "ERROR":
                reason = data.get("response") or ""
                last_exc = RuntimeError(reason)
                other_failure = True
                if "timed out" in reason.lower():
                    _cool_down_after_timeout(cfg, eng_name, reason, slot_id)
                    log(f"⚠️ Engine {eng_name} หมดเวลาตอบกลับ — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                else:
                    log(f"⚠️ Engine {eng_name} ตอบกลับด้วยข้อผิดพลาด — สลับไป Engine ตัวถัดไป...", slot_id=slot_id)
                continue
            data["engine_used"] = eng_name
            return data

    if saw_quota:
        raise QuotaExhausted(f"ทุก Engine สำรองโควตาหมดแล้ว: {last_exc}")
    if saw_busy and not other_failure:
        raise EngineBusy(f"ทุก Engine ไม่ว่าง (กำลังถูกใช้โดย Slot อื่น): {last_exc}")
    raise RuntimeError(f"ทุก Engine ล้มเหลว (ไม่ใช่โควตา): {last_exc}")


# key id ของคีย์ที่กำลังใช้เรียก engine (เช่น "opencode-gemini#GEMINI_API_KEY_1").
# ตั้งค่าโดย call_agent รอบการเรียกที่มีคีย์ เพื่อให้ record_usage บันทึกว่าคีย์ใดสำเร็จ/ไม่สำเร็จ
# โดยไม่ต้องเปลี่ยน signature ของ call_single_engine (เทสต์หลายตัว mock ฟังก์ชันนี้)
_USAGE_KEY_ID: ContextVar[str | None] = ContextVar("usage_key_id", default=None)


def _call_with_usage_key(key_id: str | None, fn, *args, **kwargs):
    token = _USAGE_KEY_ID.set(key_id)
    try:
        return fn(*args, **kwargs)
    finally:
        _USAGE_KEY_ID.reset(token)


def record_usage(eng: dict, data: dict, quota: bool) -> None:
    usage = data.get("usage") or {}
    line = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
            "engine_name": eng.get("name", eng["command"]),
            "engine": eng["command"], "model": eng["model"],
            "key_id": _USAGE_KEY_ID.get(),
            "status": "QUOTA" if quota else data.get("status", "ERROR"),
            "tokens": usage.get("total_tokens", 0),
            "seconds": round(data.get("duration_seconds", 0))}
    STATE.mkdir(exist_ok=True)
    with file_lock(STATE / "usage.jsonl.lock"):
        with (STATE / "usage.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")


GLOBAL_SKILL_REGISTRY = SkillRegistry()
GLOBAL_SKILL_REGISTRY.register_builtin_skills()


_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def fill_template(template: str, values: dict) -> str:
    """Single-pass {{name}} substitution. Inserted values are never re-scanned, so an issue body
    containing a placeholder such as {{result_path}} stays literal. Unknown names are left as-is."""
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


def render(name: str, **values) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    fills = {
        "test_commands": DEFAULT_TEST_COMMANDS,
        "repo_notes": "",
        "repo_map": "",
        "lessons": "",
        "examples": "",
        "stack_guidelines": "",
        "available_skills": "",
    }
    fills.update({key: str(val) for key, val in values.items()})
    if "rules" in values:
        fills["rules"] = str(values["rules"])
    else:
        fills["rules"] = fill_template((PROMPTS / "_rules.md").read_text(encoding="utf-8"), fills)
    return fill_template(text, fills)


def _configured_skills(cfg: dict | None, rcfg: dict | None, persona: str):
    """Personas live in cfg; a per-repo override in rcfg is the fallback."""
    for source in (cfg or {}, rcfg or {}):
        skills = (source.get("personas") or {}).get("skills") or {}
        if persona in skills:
            return skills[persona]
    return None


def build_prompt(
    job: Job,
    rcfg: dict,
    cwd: Path,
    env: dict,
    history: list[dict],
    result_path: Path,
    slot_id: int | None = None,
    cfg: dict | None = None,
) -> str:
    history = prune_resolved_evidence(history)
    stack_profile = detect_stack(cwd)
    stack_guidelines = format_stack_guidelines(stack_profile, prompts_dir=PROMPTS)
    common = dict(result_path=result_path, repo=rcfg["name"], stack_guidelines=stack_guidelines,
                  test_commands=format_test_commands(rcfg),
                  repo_notes=load_repo_notes(cwd), repo_map=build_repo_map(cwd, cfg),
                  lessons=format_lessons(history, rcfg["name"]),
                  examples=format_examples(history, rcfg["name"], job.kind, job.key))
    if job.kind == "issue":
        base = render("task.md", issue_number=job.key, issue_title=job.title,
                      issue_body=job.body[:8000], **common)
    else:
        configured_skills = _configured_skills(cfg, rcfg, job.key)
        matched_skills = GLOBAL_SKILL_REGISTRY.get_skills_for_persona(
            str(job.key),
            tech_stack=stack_profile,
            limit=3,
            configured_skills=configured_skills
        )
        available_skills = GLOBAL_SKILL_REGISTRY.format_skills_for_prompt(matched_skills)
        persona_common = dict(**common, available_skills=available_skills)

        scans = []
        for cmd in rcfg.get("scanners", {}).get(job.key, []):
            # shell=True ตั้งใจ: scanner จาก config.yaml ของเจ้าของ (ไม่รับค่าจาก issue/PR)
            res = run(cmd, cwd=cwd, env=env, check=False, shell=True, timeout=900)  # nosec B604
            scans.append(f"$ {cmd} (exit {res.returncode})\n{(res.stdout + res.stderr)[-3000:]}")
        past = [f"- [{h.get('state') or 'ไม่มี PR'}] {h.get('title') or '(ไม่มีชื่อ)'}" for h in history
                if h.get("repo") == rcfg["name"] and h.get("key") == job.key][-30:]
        if job.key == "sentinel":
            tracked = sentinel_tracker.load_sentinel_issues()
            if tracked:
                tracked_summary = [f"- [TRACKED {item.get('status', 'open').upper()}] {item.get('id')}: {item.get('title')}" for item in tracked[-20:]]
                past.extend(tracked_summary)
        base = render(f"personas/{job.key}.md", scan_results="\n\n".join(scans) or "(ไม่มีผลสแกนอัตโนมัติ — สำรวจโค้ดเอง)",
                      history="\n".join(past) or "(ยังไม่เคยเสนอ)", **persona_common)

    if slot_id is not None:
        colliding = REGISTRY.get_colliding_files(excluding_slot_id=slot_id)
        if colliding:
            file_list = ", ".join(f"`{f}`" for f in sorted(colliding))
            base += (
                f"\n\n---\n\n"
                f"⚠️ **CONCURRENCY CONSTRAINT:** Other parallel workers are currently modifying: {file_list}.\n"
                f"You MUST NOT modify or delete any of these files to avoid merge conflicts."
            )
    return base


_VALID_JSON_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _repair_json_escapes(text: str) -> str:
    """Double every backslash that is not part of a valid JSON escape
    (agents often write markdown such as a backslash before a paren inside JSON strings)"""
    return _VALID_JSON_ESCAPE.sub(lambda m: m.group(0) if m.group(1) else '\\\\', text)


def _loads_lenient(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_json_escapes(text))


def _as_dict(value) -> dict:
    """Callers call .get() on the result, so anything that is not a JSON object becomes {}."""
    return value if isinstance(value, dict) else {}


def read_result(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        try:
            return _as_dict(_loads_lenient(raw))
        except json.JSONDecodeError:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            return _as_dict(_loads_lenient(match.group(1)))
        match = re.search(r"(\{.*\})", raw, re.DOTALL)
        if match:
            return _as_dict(_loads_lenient(match.group(1)))
        return {}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


# ---------------------------------------------------------------- pr / merge

def diff_stats(cwd: Path) -> tuple[int, list[str]]:
    clean_build_artifacts(cwd)
    run(["git", "add", "-A"], cwd=cwd)
    files = run(["git", "diff", "--cached", "--name-only"], cwd=cwd).stdout.split()
    numstat = run(["git", "diff", "--cached", "--numstat"], cwd=cwd).stdout.splitlines()
    lines = sum(int(a) + int(d) for a, d, _ in (l.split("\t") for l in numstat) if a.isdigit() and d.isdigit())
    return lines, files


PERSONA_NOTES_DIR = "persona_notes"


def _drop_persona_notes(job: Job, cwd: Path, files: list[str], repo: str) -> list[str]:
    """Persona runs may not commit `.jules/` notes: a note is not a product change, and a PR made only of
    notes wastes a review. The note text is kept under state/persona_notes (outside the target repo).
    Returns the paths that were dropped (empty for issue jobs or when nothing under .jules/ changed)."""
    notes = [f for f in files if f.replace("\\", "/").startswith(".jules/")]
    if job.kind != "persona" or not notes:
        return []
    diff_text = run(["git", "diff", "--cached", "--", ".jules"], cwd=cwd, check=False).stdout
    if diff_text.strip():
        target = STATE / PERSONA_NOTES_DIR / repo.replace("/", "__") / f"{job.key}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## {stamp}\n```diff\n{diff_text[-6000:]}\n```\n")
    run(["git", "reset", "-q", "--", ".jules"], cwd=cwd, check=False)
    run(["git", "checkout", "--", ".jules"], cwd=cwd, check=False)
    run(["git", "clean", "-fdq", "--", ".jules"], cwd=cwd, check=False)
    return notes


def _matches_protected(path: str, pattern: str) -> bool:
    """The pattern must start at a path-segment boundary and end at a segment boundary
    (end of path, '/', or the '.' of an extension). 'config' matches config.yaml and config/x,
    but not configuration_view.js or myconfig.py."""
    pat = pattern.rstrip("/")
    return re.search(rf"(?:^|/){re.escape(pat)}(?=$|[/.])", path) is not None


def is_small(cfg: dict, lines: int, files: list[str]) -> bool:
    rule = cfg["small_pr"]
    return lines <= rule["max_lines"] and not any(
        _matches_protected(f, p) for f in files for p in rule["protected_paths"])


def ensure_labels(repo: str, cfg: dict) -> None:
    existing = {l["name"] for l in gh_json("label", "list", "-R", repo, "--json", "name", "--limit", "200")}
    colors = {"task": "1d76db", "pause": "b60205", "working": "fbca04", "failed": "d93f0b", "pr": "0e8a16"}
    for key, name in cfg["labels"].items():
        if name not in existing:
            gh("label", "create", name, "-R", repo, "--color", colors.get(key, "cccccc"))
    if "ai-report" not in existing:
        gh("label", "create", "ai-report", "-R", repo, "--color", "5319e7")
    needs_human = cfg["labels"].get("needs_human", "ai-needs-human")
    if needs_human not in existing:
        gh("label", "create", needs_human, "-R", repo, "--color", "b60205")
    for name, color in PR_HOLD_LABELS.items():
        if name not in existing:
            gh("label", "create", name, "-R", repo, "--color", color)


def _report_safely(repo: str, line: str, slot_id: int | None = None) -> None:
    """report() must never take a slot down: a gh outage only costs the daily report line."""
    try:
        report(repo, line)
    except Exception as exc:
        log(f"เขียนรายงานรายวันไม่สำเร็จ: {exc}", slot_id=slot_id)


def report(repo: str, line: str) -> None:
    title = f"🤖 สรุปงาน Auto Dev Crew {dt.date.today():%Y-%m-%d}"
    with file_lock(STATE / "report.lock"):
        found = gh_json("issue", "list", "-R", repo, "--state", "open", "--label", "ai-report",
                        "--search", f'"{title}" in:title', "--json", "number,title")
        number = next((i["number"] for i in found if i["title"] == title), None)
        if number is None:
            url = gh("issue", "create", "-R", repo, "--title", title, "--label", "ai-report",
                     "--body", "บันทึกงานที่เอเจนต์ทำวันนี้ (อัปเดตอัตโนมัติ)")
            number = int(url.rstrip("/").split("/")[-1])
        gh("issue", "comment", str(number), "-R", repo, "--body", f"{dt.datetime.now():%H:%M} — {line}")


def clean_body(text: str, cwd: Path | None = None) -> str:
    text = re.sub(r"\[([^\]]+)\]\(file:[^)]*\)", r"`\1`", text)
    text = re.sub(r"file:///\S+", "", text)
    if cwd:
        for form in {str(cwd), cwd.as_posix()}:
            text = text.replace(form + ("\\" if "\\" in form else "/"), "").replace(form, ".")
    return text


def create_pr(repo: str, base: str, branch: str, title: str, body: str, label: str) -> str:
    try:
        return gh("pr", "create", "-R", repo, "--base", base, "--head", branch,
                  "--title", title, "--body", body, "--label", label)
    except RuntimeError:
        found = gh_json("pr", "list", "-R", repo, "--state", "all", "--head", branch, "--json", "url")
        if found:
            return found[0]["url"]
        raise


def wait_for_checks(repo: str, pr: int) -> str:
    for _ in range(12):
        res = run(["gh", "pr", "checks", str(pr), "-R", repo], check=False)
        if "no checks reported" not in (res.stdout + res.stderr).lower():
            break
        time.sleep(10)
    else:
        return "none"
    for _ in range(3):
        res = run(["gh", "pr", "checks", str(pr), "-R", repo, "--watch", "--fail-fast", "-i", "20"],
                  check=False, timeout=3600)
        if res.returncode == 0:
            return "pass"
        if not is_transient(res.stdout + res.stderr):
            return "fail"
        time.sleep(30)
    return "fail"


def repo_has_workflows(repo: str, cwd: Path | None, ref: str | None = None) -> bool | None:
    """True/False when we know whether the repo has GitHub Actions workflows, None when unknown.

    Uses the local clone when given; otherwise asks the GitHub contents API at ``ref`` (the PR
    head branch; default branch when None). Only a 404 or an empty listing means "no
    workflows" — any other failure is unknown (caller keeps polling)."""
    if cwd is not None and Path(cwd).is_dir():
        return has_ci_workflows(Path(cwd))
    path = f"repos/{repo}/contents/.github/workflows"
    if ref:
        path += f"?ref={urllib.parse.quote(ref, safe='/')}"
    try:
        res = run(["gh", "api", path, "--jq", "length"], check=False, timeout=GH_TIMEOUT_SECONDS)
    except Exception:
        return None
    if res.returncode == 0:
        try:
            return int((res.stdout or "").strip() or 0) > 0
        except ValueError:
            return None
    out = f"{res.stdout}\n{res.stderr}"
    if "404" in out or "Not Found" in out:
        return False
    return None


def required_checks_for(cfg: dict, rcfg: dict | None) -> list[str]:
    """Per-repo ``ci.required_checks`` wins. The global list applies only when the repo
    has no such key (an explicit empty list means "this repo has no required checks")."""
    repo_ci = (rcfg or {}).get("ci")
    if isinstance(repo_ci, dict) and "required_checks" in repo_ci:
        return list(repo_ci.get("required_checks") or [])
    return list((cfg.get("ci") or {}).get("required_checks") or [])


def ci_config_for(cfg: dict, rcfg: dict | None) -> dict:
    """Returns effective CI configuration combining global cfg['ci'] and per-repo rcfg['ci'].
    Per-repo settings take precedence over global settings.
    """
    global_ci = cfg.get("ci") or {}
    repo_ci = (rcfg or {}).get("ci") if isinstance(rcfg, dict) else {}
    if not isinstance(repo_ci, dict):
        repo_ci = {}

    req_checks = required_checks_for(cfg, rcfg)

    return {
        "enabled": repo_ci.get("enabled", global_ci.get("enabled", True)),
        "required_checks": req_checks,
        "timeout_minutes": int(repo_ci.get("timeout_minutes", global_ci.get("timeout_minutes", 15))),
        "poll_interval_seconds": float(repo_ci.get("poll_interval_seconds", global_ci.get("poll_interval_seconds", 15))),
        "auto_rebase": bool(repo_ci.get("auto_rebase", global_ci.get("auto_rebase", True))),
        "allow_no_ci": bool(repo_ci.get("allow_no_ci", global_ci.get("allow_no_ci", True))),
        "auto_bootstrap_ci": bool(repo_ci.get("auto_bootstrap_ci", global_ci.get("auto_bootstrap_ci", False))),
        "fix_attempts": int(repo_ci.get("fix_attempts", global_ci.get("fix_attempts", 2))),
    }


def find_conflict_files(cwd: Path) -> list[str]:
    """Find files that have unresolved merge conflicts."""
    res = run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=cwd, check=False)
    if res.returncode == 0 and res.stdout.strip():
        return [f.strip() for f in res.stdout.splitlines() if f.strip()]
    return []


def ai_resolve_conflicts(cwd: Path, conflict_files: list[str], cfg: dict, slot_id: int | None = None) -> bool:
    """Use Auditor/Fast AI model to resolve git conflict markers in conflicting files."""
    if not conflict_files:
        return True

    log(f"🤖 [Conflict-Resolver] เริ่มวิเคราะห์และแก้ไขข้อขัดแย้งใน {len(conflict_files)} ไฟล์: {', '.join(conflict_files)}", slot_id=slot_id)
    all_resolved = True

    for rel_path in conflict_files:
        file_path = cwd / rel_path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            all_resolved = False
            continue

        if "<<<<<<<" not in content:
            continue

        prompt = (
            f"You are an expert software engineer resolving a git merge conflict in `{rel_path}`.\n"
            "Below is the conflicting file containing git conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).\n"
            "Resolve the conflict cleanly by preserving BOTH upstream changes and local features/bugfixes.\n"
            "IMPORTANT: Output ONLY the complete, resolved code for this file without any conflict markers and without any markdown fence (no ```).\n\n"
            f"--- BEGIN CONFLICTING FILE: {rel_path} ---\n"
            f"{content}\n"
            f"--- END CONFLICTING FILE ---\n"
        )

        try:
            resp = call_agent(cfg, prompt, cwd, slot_id=slot_id, role="coder")
            resolved_code = resp.get("response") if isinstance(resp, dict) else str(resp)
            if resolved_code and isinstance(resolved_code, str):
                clean_code = resolved_code.strip()
                if clean_code.startswith("```"):
                    lines = clean_code.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    clean_code = "\n".join(lines)
                if "<<<<<<<" not in clean_code:
                    file_path.write_text(clean_code, encoding="utf-8")
                    run(["git", "add", rel_path], cwd=cwd, check=False)
                    log(f"✅ [Conflict-Resolver] แก้ไขข้อขัดแย้งใน `{rel_path}` สำเร็จ", slot_id=slot_id)
                else:
                    log(f"⚠️ [Conflict-Resolver] โมเดลยังคงมี conflict marker ใน `{rel_path}`", slot_id=slot_id)
                    all_resolved = False
            else:
                all_resolved = False
        except Exception as exc:
            log(f"⚠️ [Conflict-Resolver] เกิดข้อผิดพลาดขณะ resolve `{rel_path}`: {exc}", slot_id=slot_id)
            all_resolved = False

    return all_resolved


def get_slot_assignment(slot_id: int, cfg: dict) -> dict | None:
    """Return configured assignment for slot_id (e.g. {'persona': 'quality', 'repo': '...'}) or None."""
    parallel_cfg = cfg.get("parallel", {})
    assignments = parallel_cfg.get("assignments", {})
    key = f"slot_{slot_id}"
    assign = assignments.get(key)
    if isinstance(assign, dict) and (assign.get("persona") or assign.get("repo")):
        return assign
    return None


def parse_issue_persona_directive(title: str, body: str) -> tuple[str | None, str]:
    """Parse persona directive like 'Persona: Quality' or '[Persona: Quality]' or 'Assignee: @Quality'."""
    pattern = r"(?:\[?(?:Persona|Assignee):\s*@?([A-Za-z0-9_-]+)\]?)"
    found = re.search(pattern, title, re.IGNORECASE)
    clean_body = body
    if found:
        return found.group(1).lower(), clean_body

    found = re.search(pattern, body, re.IGNORECASE)
    if found:
        matched_str = found.group(0)
        clean_body = re.sub(re.escape(matched_str), "", body).strip()
        return found.group(1).lower(), clean_body

    return None, clean_body


HOLD_PR_MARKER = "คง PR ไว้"
# Returned by try_merge when a required check failed and the caller may still retry with a fix.
CI_FAIL_RETRY = "CI ไม่ผ่าน — รอให้เอเจนต์แก้"
# PR labels applied when a PR is kept open for a human; ensure_labels creates them so gh pr edit does not fail silently.
PR_HOLD_LABELS = {"ci-failed": "b60205", "merge-failed": "b60205", "needs-rebase": "fbca04"}


def _hold_pr_for_human(repo: str, pr: int, label: str, reason: str, detail: str = "", slot_id: int | None = None) -> str:
    """Keep a PR that failed CI or merge open (never close it or delete its branch).

    Adds a label and a comment so a human can inspect it. The caller marks the issue failed.
    """
    log(f"⚠️ {reason} — {HOLD_PR_MARKER} PR #{pr} ติดป้าย '{label}' (ไม่ปิด/ไม่ลบ branch)", slot_id=slot_id)
    # The label may not exist yet on repos that never ran ensure_labels; create or update it first.
    gh("label", "create", label, "-R", repo, "--color", PR_HOLD_LABELS.get(label, "cccccc"), "--force", check=False)
    gh("pr", "edit", str(pr), "-R", repo, "--add-label", label, check=False)
    body = f"🤖 {reason} — ระบบคง PR นี้ไว้ ไม่ปิดและไม่ลบ branch ต้องให้มนุษย์ตรวจสอบ"
    if detail:
        body += f"\n\n```\n{detail}\n```"
    gh("pr", "comment", str(pr), "-R", repo, "--body", body, check=False)
    return f"{reason} — {HOLD_PR_MARKER} (ติดป้าย {label})"


def pr_merge_state(repo: str, pr: int) -> str | None:
    """GitHub mergeStateStatus of the PR (CLEAN, BEHIND, DIRTY, ...) or None when unknown.

    DIRTY means the PR conflicts with its base. GitHub then runs no pull_request checks for it,
    so "no checks reported" says nothing about whether the repo has CI."""
    try:
        data = json.loads(gh("pr", "view", str(pr), "-R", repo, "--json", "mergeStateStatus") or "{}")
    except Exception:
        return None
    state = data.get("mergeStateStatus") if isinstance(data, dict) else None
    return str(state).upper() if state else None


def _local_rebase_and_merge(
    repo: str,
    pr: int,
    cfg: dict,
    cwd: Path | None,
    branch: str | None,
    base_branch: str,
    test_steps: list[str] | None,
    env: dict | None,
    slot_id: int | None,
) -> str | None:
    """Merge the base into the PR branch locally, AI-resolve conflicts, run tests, push and merge.

    Returns the success message, or None when the PR has to stay open."""
    if cwd is None or branch is None:
        return None
    log(f"⚠️ [Merge-Conflict] PR #{pr} ติดข้อขัดแย้ง — เริ่มกระบวนการ Local Auto-Rebase & AI Resolver...", slot_id=slot_id)
    run(["git", "fetch", "origin", base_branch], cwd=cwd, check=False)
    merge_res = run(["git", "merge", f"origin/{base_branch}"], cwd=cwd, check=False)
    conflict_files = find_conflict_files(cwd)
    if conflict_files:
        if not ai_resolve_conflicts(cwd, conflict_files, cfg, slot_id=slot_id):
            return None
    elif merge_res.returncode != 0:
        return None
    run(["git", "commit", "-m", f"chore: resolve merge conflicts with {base_branch}"], cwd=cwd, check=False)
    test_ok = True
    if test_steps:
        test_ok, _ = run_steps(test_steps, cwd, env or {})
    if not test_ok:
        return None
    push_res = run(["git", "push", "origin", branch], cwd=cwd, check=False)
    if push_res.returncode != 0:
        return None
    try:
        gh("pr", "merge", str(pr), "-R", repo, "--squash", "--delete-branch")
    except Exception as e2:
        log(f"⚠️ Merge หลัง resolve ล้มเหลว: {e2}", slot_id=slot_id)
        return None
    return "merge แล้ว ✅ (ผ่าน AI Conflict Resolver)"


def try_merge(
    repo: str,
    pr: int,
    cfg: dict,
    small: bool,
    slot_id: int | None = None,
    rcfg: dict | None = None,
    cwd: Path | None = None,
    branch: str | None = None,
    test_steps: list[str] | None = None,
    env: dict | None = None,
    hold_ci_failure: bool = True,
) -> str:
    mode = cfg["merge_mode"]
    # Per-repo merge level (feature_gen): 1 = human merges, 2 = auto-merge only low-risk PRs, 3 = merge when CI passes.
    # Without a level the legacy global merge_mode applies unchanged.
    level = feature_gen.merge_level_for(cfg, repo)
    if level == 1:
        return "รอรีวิว (merge ระดับ 1: คนกด merge เอง)"
    if level == 2:
        reasons = feature_gen.pr_risk(repo, pr, cfg)
        if reasons:
            log(f"PR #{pr} มีความเสี่ยง จึงไม่ auto-merge (merge ระดับ 2): {'; '.join(reasons)[:300]}", slot_id=slot_id)
            return "รอคนอนุมัติ — ไฟล์เสี่ยง (merge ระดับ 2)"
    elif level is None and (mode == "review-all" or (mode == "small-only" and not small)):
        return "รอรีวิว"

    ci_cfg = ci_config_for(cfg, rcfg)
    ci_timeout_mins = int(ci_cfg.get("timeout_minutes", 15)) if ci_cfg.get("enabled", True) else 0
    cfg_lock_mins = int(cfg.get("parallel", {}).get("merge_lock_timeout_minutes", 25))
    timeout = max(cfg_lock_mins, ci_timeout_mins + 5) * 60

    log(f"รอจอง Central Merge Lock เพื่อ merge PR #{pr}...", slot_id=slot_id)
    with file_lock(MERGE_LOCK, timeout=timeout):
        log(f"ได้รับ Central Merge Lock สำหรับ PR #{pr} แล้ว — เริ่มตรวจสอบ CI และ Rebase", slot_id=slot_id)
        base_branch = (rcfg.get("base") if rcfg else None) or "main"

        if ci_cfg.get("auto_rebase", True):
            try:
                gh("pr", "update-branch", str(pr), "-R", repo, check=False)
            except Exception as exc:
                log(f"⚠️ update-branch ของ PR #{pr} ล้มเหลว ({exc}) — ดำเนินการต่อด้วยการตรวจ CI", slot_id=slot_id)

        # A conflicting PR gets no CI run at all. Resolve it locally first; if that fails,
        # keep it open with needs-rebase. Never wait for CI or call it "no CI" here.
        if pr_merge_state(repo, pr) == "DIRTY":
            msg = _local_rebase_and_merge(repo, pr, cfg, cwd, branch, base_branch, test_steps, env, slot_id)
            return msg or _hold_pr_for_human(
                repo, pr, "needs-rebase", "ติด conflict กับ base (mergeStateStatus=DIRTY)", slot_id=slot_id)

        required_checks = ci_cfg.get("required_checks", [])
        if ci_cfg.get("enabled", True) and required_checks:
            timeout_s = int(ci_cfg.get("timeout_minutes", 20)) * 60
            poll_i = float(ci_cfg.get("poll_interval_seconds", 15))
            checks = wait_for_required_checks(
                repo, pr, required_checks,
                timeout_seconds=timeout_s,
                poll_interval=poll_i,
                logger=lambda m: log(m, slot_id=slot_id)
            )
            if checks == "timeout":
                log(f"⚠️ [CI-Sync] PR #{pr} รัน CI นานเกินกำหนด — ปลด lock ให้คิวอื่นทำต่อและรอเช็คใหม่รอบถัดไป", slot_id=slot_id)
                return "รอ CI ทำงานต่อ"
        else:
            has_workflows = repo_has_workflows(repo, cwd, ref=branch)
            if has_workflows is False:
                log(f"ไม่พบ workflow ใน repo — ข้ามการรอ CI (PR #{pr})", slot_id=slot_id)
                checks = "none"
            else:
                checks = wait_for_checks(repo, pr)
                if checks == "none" and has_workflows is True:
                    # Workflows exist but none ran on this PR: that is not "no CI". Do not merge.
                    log(f"⚠️ [CI-Gate] PR #{pr} มี workflow ใน repo แต่ยังไม่มี check รันบน PR — ยังไม่ merge (รอรอบถัดไป)", slot_id=slot_id)
                    return "รอ CI — workflow มีอยู่แต่ยังไม่มี check รันบน PR"

        if checks == "fail":
            if not hold_ci_failure:
                return CI_FAIL_RETRY  # finish_pr gives the agent a chance to fix CI first
            return _hold_pr_for_human(repo, pr, "ci-failed", "CI ไม่ผ่าน", slot_id=slot_id)

        if checks == "none" and not ci_cfg.get("allow_no_ci", True):
            log(f"⚠️ [CI-Gate] PR #{pr} บน repo {repo} ไม่มี CI และ allow_no_ci ปิดอยู่ — ไม่อนุญาตให้ merge", slot_id=slot_id)
            return "รอ CI — allow_no_ci ปิดอยู่"

        try:
            gh("pr", "merge", str(pr), "-R", repo, "--squash", "--delete-branch")
            return "merge แล้ว ✅" + (" (repo ไม่มี CI — ใช้ผลเทสต์ในเครื่อง)" if checks == "none" else "")
        except RuntimeError as exc:
            exc_str = str(exc)
            is_conflict = (
                "not mergeable" in exc_str
                or "cannot be cleanly created" in exc_str
                or "conflict" in exc_str.lower()
            )
            if is_conflict:
                msg = _local_rebase_and_merge(repo, pr, cfg, cwd, branch, base_branch, test_steps, env, slot_id)
                return msg or _hold_pr_for_human(
                    repo, pr, "needs-rebase", "ติด conflict — รอ rebase", detail=exc_str[-1500:], slot_id=slot_id)

            # Non-conflict fatal errors: keep the PR and its branch for a human to inspect.
            return _hold_pr_for_human(repo, pr, "merge-failed", "merge ไม่สำเร็จ", detail=exc_str[-1500:], slot_id=slot_id)

# ---------------------------------------------------------------- job

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def _prepare_workspace(cwd: Path, repo: str, rcfg: dict, slot_id: int | None) -> tuple[dict, list[str]]:
    env = venv_env(repo, slot_id=slot_id)
    if playwright_env.is_opted_in(rcfg):
        # opt-in ต่อ repo เท่านั้น; ล้มเหลวได้โดยไม่หยุดลูป (ดู playwright_env.ensure_playwright)
        playwright_env.ensure_playwright(venv_path(repo, slot_id),
                                         lambda msg: log(msg, slot_id=slot_id))
    elif playwright_env.detect_playwright_needed(cwd):
        log(f"💡 ตรวจพบว่า {repo} มีโค้ดหรือชุดทดสอบ Playwright แต่ยังไม่ได้เปิดใช้งาน (playwright: true) — โปรดระบุ 'playwright: true' ใน config.yaml หากต้องการอนุญาตให้ติดตั้ง",
            slot_id=slot_id)

    # Adapt setup & test steps if configured with Python defaults on non-Python or non-standard repos
    setup_steps = list(rcfg.get("setup", []))
    test_steps = list(rcfg.get("test", []))
    if any("requirements.txt" in s for s in setup_steps) and not (cwd / "requirements.txt").exists():
        setup_steps = [s for s in setup_steps if "requirements.txt" not in s]
    if any("pytest" in s or "unittest" in s for s in test_steps) and not any(cwd.glob("**/*.py")):
        if (cwd / "test-runner.js").exists():
            test_steps = ["node test-runner.js"]
        elif (cwd / "package.json").exists():
            test_steps = ["npm test"]
        else:
            test_steps = []

    ok, out = run_steps(setup_steps, cwd, env)
    if not ok:
        raise RuntimeError(f"setup ล้มเหลว:\n{out}")
    return env, test_steps


def _run_round_tests(test_steps: list[str], prev_out: str, cwd: Path, env: dict, slot_id: int | None) -> tuple[bool, str]:
    """Round 2+: rerun only the pytest cases that failed last round; confirm with one full run when they pass."""
    failed = failed_test_ids(prev_out)
    narrowed = [c for c in (narrow_test_command(s, failed) for s in test_steps) if c]
    if not narrowed:
        return run_steps(test_steps, cwd, env)
    log(f"รันเฉพาะเทสต์ที่ล้ม {len(failed)} เคส", slot_id=slot_id)
    ok, out = run_steps(narrowed, cwd, env)
    if not ok and failed_test_ids(out):
        return ok, out
    # passed -> confirm with a full run; failed without any FAILED id (rc=4 not found / collection error) -> inconclusive
    return run_steps(test_steps, cwd, env)


def _test_gate_round(cfg: dict, base_prompt: str, cwd: Path, env: dict, test_steps: list[str], result_path: Path,
                     slot_id: int | None, entry: dict) -> tuple[bool, str]:
    """Bugfix without a test change: one extra agent round asking for a regression test, then rerun the tests.
    An ERROR return or an exception is logged and recorded, and the tests still decide the outcome,
    because the round may have edited files before it failed."""
    log("งานแก้บั๊กไม่มีการแก้ไฟล์เทสต์ — ขอให้เอเจนต์เพิ่มเทสต์ regression อีก 1 รอบ", slot_id=slot_id)
    try:
        prompt = base_prompt + "\n\n---\n\n" + loop_helpers.regression_test_prompt(result_path)
        res = call_agent(cfg, prompt, cwd, slot_id=slot_id)
        if (res or {}).get("status") == "ERROR":
            raise RuntimeError(str((res or {}).get("response") or "")[:500])
        entry["test_gate_round"] = True
    except Exception as exc:  # the round is optional; never fail the job just for it
        log(f"รอบเทสต์ regression ล้มเหลว: {exc}", slot_id=slot_id)
        entry["test_gate_error"] = True
    return run_steps(test_steps, cwd, env)


def _agent_fix_loop(cfg: dict, base_prompt: str, cwd: Path, env: dict, test_steps: list[str], result_path: Path, max_attempts: int, slot_id: int | None) -> tuple[bool, str, dict]:
    prompt = base_prompt
    tests_ok, test_out, result = False, "", {}
    agent_res: dict = {}
    fix_rounds = 0
    for attempt in range(1, max_attempts + 1):
        log(f"เรียกเอเจนต์ รอบ {attempt}", slot_id=slot_id)
        if slot_id is not None:
            REGISTRY.update_slot_state(slot_id, f"agent_round_{attempt}")
        agent_res = call_agent(cfg, prompt, cwd, slot_id=slot_id)
        fix_rounds += 1
        if agent_res.get("status") == "ERROR":
            # MED-02: an agent error is not a silent round. Stop this job's fix loop.
            raise RuntimeError(f"เอเจนต์ส่งข้อผิดพลาดในรอบ {attempt}: {str(agent_res.get('response') or '')[:1000]}")
        result = read_result(result_path)
        if result.get("status") == "NO_ACTION" and not diff_stats(cwd)[1]:
            break  # genuine no change; NO_ACTION over an earlier round's edits still gets tested

        if slot_id is not None:
            _, touched = diff_stats(cwd)
            REGISTRY.update_active_files(slot_id, touched)
            REGISTRY.update_slot_state(slot_id, "testing")

        tests_ok, test_out = _run_round_tests(test_steps, test_out, cwd, env, slot_id) if attempt > 1 else run_steps(test_steps, cwd, env)
        log(f"เทสต์ {'ผ่าน' if tests_ok else 'ไม่ผ่าน'}", slot_id=slot_id)
        if tests_ok:
            break
        log("ท้ายผลเทสต์ที่ล้ม:\n" + failure_tail(test_out), slot_id=slot_id)
        test_snippet = format_delta_turn(test_failure_output=truncate_tool_output(test_out, max_chars=4000))
        prompt = base_prompt + "\n\n---\n\n" + render("fix_tests.md", test_output=test_snippet, result_path=result_path,
                                                        previous_diff=loop_helpers.current_diff(cwd))
    if isinstance(result, dict):  # Phase 0 metrics: which engine served the last round, and how many rounds ran
        result["engine_used"] = agent_res.get("engine_used")
        result["fix_rounds"] = fix_rounds
    return tests_ok, test_out, result


FAST_PATH_PREFIX = (
    "## FAST-PATH EXECUTION MODE\n"
    "- This task is classified as a small, focused fix or polish.\n"
    "- Make surgical edits only (prefer < 20 lines).\n"
    "- Run only the relevant tests, avoid unnecessary file reading, and complete the task promptly.\n\n"
)


def _escalate_fast_if_over_budget(eval_res: EvaluationResult, mode: str, diff_text: str, task_desc: str, test_out: str,
                                  cfg: dict, cwd: Path, entry: dict, slot_id: int | None) -> tuple[EvaluationResult, str]:
    """F-8: a fast-path diff that fails the Hard Gate is re-triaged as heavy and re-evaluated once,
    instead of being squeezed under the fast cap. Returns (eval_res, mode) for the caller to keep using."""
    if mode != "fast" or eval_res.passed or not eval_res.critique_th.startswith("⛔ Hard Gate"):
        return eval_res, mode
    log("[Triage] diff เกินงบ fast-path — ยกระดับเป็น HEAVY-PATH และประเมินใหม่", slot_id=slot_id)
    entry["triage_path"] = "heavy"
    entry["triage_escalated"] = True
    return _evaluate_guarded(diff_text, task_desc, test_out, cfg, cwd, slot_id=slot_id, mode="heavy"), "heavy"


def _new_tests_fail_on_base(cwd: Path, test_paths: list[str], test_steps: list[str], env: dict) -> bool:
    """A bugfix's new or changed tests must fail without the fix. Copies those test files into a
    throwaway worktree at HEAD (no source changes) and runs the tests there. True when they fail,
    which means they reproduce the bug. The real worktree is never touched."""
    if not test_steps:
        return True
    base = Path(tempfile.gettempdir()) / f"repro-{os.getpid()}-{time.time_ns()}"
    run(["git", "worktree", "add", "--detach", str(base), "HEAD"], cwd=cwd)
    try:
        for rel in test_paths:
            src = cwd / rel
            if src.is_file():
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, base / rel)
        ok, _ = run_steps(test_steps, base, env)
        return not ok
    finally:
        run(["git", "worktree", "remove", "--force", str(base)], cwd=cwd, check=False)
        shutil.rmtree(base, ignore_errors=True)


# ---- Auto-repair of failed issues -------------------------------------------------------
# A failure the coder can plausibly fix (tests fail, or the coder changed nothing) goes back to ai-task
# for up to `max_attempts` repair rounds, and the previous failure is fed into the next prompt.
# Refusals (BLOCKED, e.g. rule R2), exhausted rounds, and every other failure type are not repaired.
AUTO_REPAIR_DEFAULT_ATTEMPTS = 2


def auto_repair_settings(cfg: dict | None) -> tuple[bool, int]:
    ar = (cfg or {}).get("auto_repair") or {}
    return bool(ar.get("enabled", True)), int(ar.get("max_attempts", AUTO_REPAIR_DEFAULT_ATTEMPTS))


_RULE_REFUSAL_RE = re.compile(r"\bR2\b|\bBLOCKED\b|prompt.?injection|ถูกบล็อก|บล็อกโดย", re.IGNORECASE)


def is_rule_refusal(result: dict) -> bool:
    """True when the coder refused under a safety rule (R2), even if it replied NO_ACTION instead of BLOCKED.

    A refusal is never repaired: retrying it only spends quota and gets the same refusal (issue #114).
    """
    if (result or {}).get("status") == "BLOCKED":
        return True
    return bool(_RULE_REFUSAL_RE.search(str((result or {}).get("summary_th", ""))))


def _issue_entries(job: Job, issue_repo: str, history: list[dict]) -> list[dict]:
    return [h for h in history
            if h.get("kind") == "issue" and str(h.get("key")) == str(job.key)
            and (h.get("origin_repo") or h.get("repo")) == issue_repo]


def repair_rounds_used(job: Job, issue_repo: str, history: list[dict]) -> int:
    return max((int(h.get("repair_attempt") or 0) for h in _issue_entries(job, issue_repo, history)), default=0)


def _latest_repair_feedback(job: Job, issue_repo: str, history: list[dict]) -> dict | None:
    for h in reversed(_issue_entries(job, issue_repo, history)):
        if h.get("repair_feedback"):
            return h
    return None


def repair_prompt_suffix(job: Job, issue_repo: str, history: list[dict], max_attempts: int) -> str:
    """Prompt section describing the previous failed attempt, or '' when this is a first attempt."""
    if job.kind != "issue":
        return ""
    prev = _latest_repair_feedback(job, issue_repo, history)
    if not prev:
        return ""
    fb = prev["repair_feedback"]
    n = int(prev.get("repair_attempt") or 1)
    parts = [f"## รอบซ่อมอัตโนมัติ {n}/{max_attempts}", "รอบก่อนหน้าล้มเหลวด้วยเหตุผลนี้:", str(fb.get("reason", ""))]
    if fb.get("critique"):
        parts += ["คำวิจารณ์จาก judge:", str(fb["critique"])]
    if fb.get("test_out"):
        parts += ["ผลเทสต์ที่ล้ม (ท้ายสุด):", "```", str(fb["test_out"]), "```"]
    parts.append("แก้ให้ตรงกับข้อความ issue และทำให้เทสต์ผ่าน ห้ามแก้ไฟล์ใน .github/workflows")
    return "\n\n---\n\n" + "\n".join(parts)


def _prefer_engine(engines: list[dict], name: str) -> list[dict]:
    """Move the engine that failed last time to the front; the rest keep their order."""
    first = [e for e in engines if e.get("name") == name]
    return first + [e for e in engines if e.get("name") != name]


def _settle_failure(job: Job, cfg: dict | None, issue_repo: str, labels: dict, entry: dict, msg: str,
                    test_out: str, dry_run: bool, *, repairable: bool, blocked: bool = False) -> None:
    """Label and comment a failed issue. Sets the repair fields on `entry`; the caller appends history."""
    if job.kind != "issue" or dry_run:
        return
    enabled, max_attempts = auto_repair_settings(cfg)
    used = repair_rounds_used(job, issue_repo, load_history())
    needs_human = labels.get("needs_human", "ai-needs-human")
    body = f"🤖 {msg}" + (f"\n\n```\n{test_out[-3000:]}\n```" if test_out else "")
    if repairable and enabled and not blocked and used < max_attempts:
        entry["repair_attempt"] = used + 1
        entry["repair_feedback"] = {"reason": msg, "test_out": (test_out or "")[-1500:],
                                    "critique": entry.get("eval_critique", "")}
        gh("issue", "comment", job.key, "-R", issue_repo,
           "--body", body + f"\n\n🔁 จะลองซ่อมอัตโนมัติ รอบ {used + 1}/{max_attempts}")
        gh("issue", "edit", job.key, "-R", issue_repo, "--remove-label", labels["working"])
        return
    if repairable and enabled:
        reason = "ถูกบล็อกโดยกฎความปลอดภัย" if blocked else f"ซ่อมอัตโนมัติครบ {max_attempts} รอบแล้วยังไม่ผ่าน"
        gh("issue", "comment", job.key, "-R", issue_repo, "--body", body + f"\n\n⛔ {reason} — ต้องให้คนตรวจ")
        gh("issue", "edit", job.key, "-R", issue_repo, "--remove-label", labels["working"], "--add-label", labels["failed"])
        gh("issue", "edit", job.key, "-R", issue_repo, "--add-label", needs_human, check=False)
        return
    gh("issue", "comment", job.key, "-R", issue_repo, "--body", body)
    gh("issue", "edit", job.key, "-R", issue_repo, "--remove-label", labels["working"], "--add-label", labels["failed"])


def _block_job(job: Job, entry: dict, labels: dict, issue_repo: str, dry_run: bool, msg: str, test_out: str,
               *, cfg: dict | None = None, repairable: bool = False) -> str:
    """Stop this job before a PR: record it as FAILED, label/comment the issue, and return the reason."""
    entry["state"] = "FAILED"
    if test_out:
        entry["fail_reason"] = test_out[-300:]
    _settle_failure(job, cfg, issue_repo, labels, entry, msg, test_out, dry_run, repairable=repairable)
    append_history(entry)
    log(f"⛔ {msg} — บล็อกการเปิด PR")
    return msg


_FIX_LOC_SUFFIX_RE = re.compile(r":\s*\d[\d\-, ]*$")


def _fix_location_files(eval_res) -> list[str]:
    """ไฟล์ production ที่ judge ชี้ใน fix_location (ตัด ':line' ออก); ว่างถ้า judge ไม่ได้ชี้."""
    paths = []
    for loc in getattr(eval_res, "fix_location", None) or []:
        path = _FIX_LOC_SUFFIX_RE.sub("", loc).strip().replace("\\", "/")
        if path and path not in paths:
            paths.append(path)
    return quality_gates.production_files(paths)


def _fix_location_hint(eval_res) -> str:
    """ข้อความแนะนำจุดแก้และทางเลือกการแก้สำหรับรอบปรับปรุง; ว่างเมื่อ judge ไม่ได้ชี้อะไรเลย."""
    locs = [loc for loc in (getattr(eval_res, "fix_location", None) or []) if loc]
    options = [o for o in (getattr(eval_res, "fix_options", None) or []) if o.get("approach")]
    if not locs and not options:
        return ""
    out = ""
    if locs:
        lines = "\n".join(f"- {loc}" for loc in locs)
        out += ("\n## จุดที่ reviewer ชี้ว่าควรแก้\n" + lines +
                "\nตรวจจุดเหล่านี้ด้วยตัวเองก่อนแก้ ถ้าไม่ตรงกับโค้ดจริงให้แก้ตามโค้ดจริง\n")
    if options:
        blocks = []
        for i, o in enumerate(options, 1):
            blocks.append(f"{i}. {o['approach']}\n   ข้อดี: {o.get('pros') or '-'}\n   ข้อเสีย: {o.get('cons') or '-'}")
        out += ("\n## ทางเลือกการแก้ที่ reviewer เสนอ\n" + "\n".join(blocks) +
                "\nเลือกทางที่เหมาะกับโค้ดจริงที่สุด ถ้าทั้งสองไม่เหมาะให้แก้เองตามความเหมาะสม\n")
    return out


def _eval_gate(job: Job, cfg: dict, cwd: Path, env: dict, test_steps: list[str], test_out: str, entry: dict, result_path: Path, base_prompt: str, labels: dict, issue_repo: str, dry_run: bool, slot_id: int | None, mode: str = "auto") -> str | None:
    # Pre-PR agentic-eval Gate
    if cfg.get("evaluation", {}).get("enabled", True):
        if slot_id is not None:
            REGISTRY.update_slot_state(slot_id, "evaluating")
        clean_build_artifacts(cwd)
        # The judge scores only against a fresh test run made here, never against the coder's own report.
        if test_steps:
            tests_ok, test_out = run_steps(test_steps, cwd, env)
            clean_build_artifacts(cwd)
            if not tests_ok:
                return _block_job(job, entry, labels, issue_repo, dry_run,
                                  f"{job.kind}:{job.key} เทสต์ไม่ผ่านตอนรันซ้ำก่อนประเมิน", test_out,
                                  cfg=cfg, repairable=True)
        run(["git", "add", "-A"], cwd=cwd)
        _, changed = diff_stats(cwd)
        if (cfg.get("loop") or {}).get("require_repro_test_for_bugfix", True) and loop_helpers.is_bugfix(job):
            new_tests = loop_helpers.test_files(changed)
            if new_tests and not _new_tests_fail_on_base(cwd, new_tests, test_steps, env):
                return _block_job(job, entry, labels, issue_repo, dry_run,
                                  f"{job.kind}:{job.key} บั๊กต้องมีเทสต์ที่ fail ก่อนแก้ — เทสต์ที่เพิ่มยังผ่านบนโค้ดเดิม",
                                  "")
            if new_tests:
                entry["repro_tests"] = new_tests  # ด่าน 1: แสดงใน PR body ว่าเทสต์นี้ fail ก่อนแก้จริง
        diff_text = run(["git", "diff", "--cached"], cwd=cwd, check=False).stdout
        task_desc = task_description_for_job(job)
        if job.kind == "issue":  # ด่าน 3: รอบซ่อมต้องแตะไฟล์ production ที่ issue ระบุ
            violation = quality_gates.repair_gate_violation(
                quality_gates.existing_named_files(cwd, task_desc), changed)
            if violation:
                return _block_job(job, entry, labels, issue_repo, dry_run,
                                  f"{job.kind}:{job.key} {violation}", "", cfg=cfg, repairable=True)
        # Judge prefers an engine other than the coder's (entry["engine"] is the coder's engine).
        coder_engine = entry.get("engine")
        eval_res = _evaluate_guarded(diff_text, task_desc, test_out, cfg, cwd, slot_id=slot_id, mode=mode,
                                     exclude_engine=coder_engine)
        if eval_res.engine_error:
            # BUG-6: the judge never ran. Do not refine or block the PR; the job is retried later.
            raise EngineBusy("judge engine ไม่ว่าง — ยังไม่ได้ประเมิน จึงไม่นับเป็นคะแนนต่ำ")
        eval_res, mode = _escalate_fast_if_over_budget(eval_res, mode, diff_text, task_desc, test_out, cfg, cwd, entry, slot_id)
        if entry.get("triage_escalated"):
            base_prompt = base_prompt.removeprefix(FAST_PATH_PREFIX)  # heavy refinement: drop the "< 20 lines" brief
        entry["eval_score"] = round(eval_res.score, 2)
        entry["eval_critique"] = eval_res.critique_th
        entry["fix_options"] = eval_res.fix_options
        entry["judge_engine"] = eval_res.judge_engine
        entry["judge_same_as_coder"] = eval_res.judge_same_as_coder
        entry["judge_fallback"] = eval_res.judge_fallback

        # Refinement loop
        max_refines = cfg.get("evaluation", {}).get("max_eval_refinements", 2)
        score_trail = [eval_res.score]
        if not eval_res.passed and max_refines > 0:
            for ref_round in range(1, max_refines + 1):
                log(f"[agentic-eval] ไม่ผ่านเกณฑ์ ({eval_res.score:.2f}) — สั่งปรับปรุงรอบ {ref_round}/{max_refines}", slot_id=slot_id)
                ref_prompt = (
                    f"{base_prompt}\n\n---\n\n"
                    f"## PRE-PR EVALUATION FEEDBACK\n"
                    f"Your code passed unit tests but failed quality evaluation with score {eval_res.score:.2f}.\n"
                    f"Critique: {eval_res.critique_th}\n"
                    f"{_fix_location_hint(eval_res)}"
                    f"Please refine your changes to address this feedback and write the updated result JSON to: {result_path}"
                )
                call_agent(cfg, ref_prompt, cwd, slot_id=slot_id)
                tests_ok, test_out = run_steps(test_steps, cwd, env)
                if not tests_ok:
                    log(f"[agentic-eval] เทสต์ล้มเหลวหลังปรับปรุงรอบ {ref_round}", slot_id=slot_id)
                    break
                clean_build_artifacts(cwd)
                run(["git", "add", "-A"], cwd=cwd)
                if job.kind == "issue":  # ด่าน 3 ซ้ำหลังปรับปรุง: รอบปรับปรุงห้ามทิ้งไฟล์ production ที่ issue ระบุ
                    _, changed_now = diff_stats(cwd)
                    # ไฟล์ที่ issue ระบุ + ไฟล์ที่ judge ชี้ใน fix_location: แก้ไฟล์ที่ judge ชี้ต้องไม่ถูกบล็อก
                    named_now = quality_gates.existing_named_files(cwd, task_desc) + [
                        f for f in _fix_location_files(eval_res)
                        if (cwd / f).is_file() and f not in quality_gates.existing_named_files(cwd, task_desc)]
                    violation = quality_gates.repair_gate_violation(named_now, changed_now)
                    if violation:
                        return _block_job(job, entry, labels, issue_repo, dry_run,
                                          f"{job.kind}:{job.key} {violation}", "", cfg=cfg, repairable=True)
                diff_text = run(["git", "diff", "--cached"], cwd=cwd, check=False).stdout
                eval_res = _evaluate_guarded(diff_text, task_desc, test_out, cfg, cwd, slot_id=slot_id, mode=mode,
                                             exclude_engine=coder_engine)
                if eval_res.engine_error:
                    raise EngineBusy("judge engine ไม่ว่าง — ยังไม่ได้ประเมินรอบปรับปรุง")
                entry["eval_score"] = round(eval_res.score, 2)
                entry["eval_critique"] = eval_res.critique_th
                entry["fix_options"] = eval_res.fix_options
                entry["judge_engine"] = eval_res.judge_engine
                entry["judge_same_as_coder"] = eval_res.judge_same_as_coder
                entry["judge_fallback"] = eval_res.judge_fallback
                if eval_res.passed:
                    log(f"[agentic-eval] ผ่านการประเมินแล้ว! (คะแนน {eval_res.score:.2f})", slot_id=slot_id)
                    break
                score_trail.append(eval_res.score)
                if _plateau_stop_enabled(cfg):
                    from . import autonomous_upgrades  # local import: autonomous_upgrades imports this module
                    stalled, why = autonomous_upgrades.should_escalate_repair(score_trail)
                    if stalled:
                        log(f"[agentic-eval] {why} — หยุดปรับปรุง ไม่ใช้โควตาซ้ำ", slot_id=slot_id)
                        break

        # If still failing evaluation, BLOCK PR creation!
        if not eval_res.passed:
            msg = f"{job.kind}:{job.key} ไม่ผ่านการประเมิน agentic-eval (คะแนน {eval_res.score:.2f}): {eval_res.critique_th}"
            entry["state"] = "EVAL_FAILED"
            if job.kind == "issue" and not dry_run:
                gh("issue", "comment", job.key, "-R", issue_repo,
                   "--body", f"🤖 {msg}\n\nบล็อกการเปิด PR เพื่อรักษาความปลอดภัยของโค้ด")
                gh("issue", "edit", job.key, "-R", issue_repo, "--remove-label", labels["working"], "--add-label", labels["failed"])
            append_history(entry)
            log(f"⛔ {msg} — บล็อกการเปิด PR", slot_id=slot_id)
            return msg
    return None


def _push_and_open_pr(job: Job, cfg: dict, rcfg: dict, history: list[dict], entry: dict, cwd: Path, branch: str, result: dict, lines: int, files: list[str], repo: str, issue_repo: str, slot_id: int | None, test_steps: list[str] | None = None, env: dict | None = None) -> str:
    # Re-stage any modifications from refinement loop
    clean_build_artifacts(cwd)
    run(["git", "add", "-A"], cwd=cwd)
    commit_msg = result.get("commit_message") or f"chore: [ADC] {job.kind} {job.key}"
    run(["git", "commit", "-m", commit_msg], cwd=cwd)
    for attempt in range(1, GH_RETRIES + 1):
        res = run(["git", "push", "-u", "origin", branch], cwd=cwd, check=False)
        if res.returncode == 0:
            break
        if attempt == GH_RETRIES:
            raise RuntimeError(f"git push ล้มเหลว:\n{res.stderr[-1500:]}")
        time.sleep(15 * 2 ** (attempt - 1))

    job_ref = None
    if job.kind == "issue":
        job_ref = f"{issue_repo}#{job.key}" if issue_repo != repo else job.key
    body = build_pr_body(
        job_title=entry["title"], job_ref=job_ref, persona=job.key if job.kind != "issue" else "",
        summary=clean_body(result.get("summary_th", ""), cwd), files_changed=files,
        test_cmd=" && ".join(test_steps) if test_steps else "(no test steps)",
        test_passed=bool(test_steps), eval_score=entry.get("eval_score"), lines=lines,
        repro_tests=entry.get("repro_tests"))
    entry.update(state="PUSHED", branch=branch, pr_title=f"{ICONS.get(job.key, '🤖')} {entry['title']}",
                 pr_body=body, small=is_small(cfg, lines, files))
    append_history(entry)
    if slot_id is not None:
        REGISTRY.update_slot_state(slot_id, "merging")
    return finish_pr(entry, cfg, rcfg, history, slot_id=slot_id, cwd=cwd, branch=branch, test_steps=test_steps, env=env)


def _confirm_bug_exists(job: Job, cfg: dict, cwd: Path, slot_id: int | None) -> dict | None:
    """ด่าน 1 (docs/draft-quality-gates.md): judge ตรวจว่าบั๊กที่ issue อ้างมีจริงก่อน coder แก้.
    None = ตรวจไม่ได้ (ไม่มีไฟล์ที่อ้าง, judge ล้มเหลว, อ่านผลไม่ได้) — ไม่บล็อกงานเพราะการตรวจล้มเหลว."""
    task_desc = task_description_for_job(job)
    names = quality_gates.existing_named_files(cwd, task_desc)
    if not names:
        log("[bug-check] issue ไม่ได้อ้างไฟล์ production ที่มีอยู่จริง — ข้ามด่านยืนยันบั๊ก", slot_id=slot_id)
        return None
    prompt = quality_gates.bug_check_prompt(
        job.title, job.body or "", quality_gates.read_files_block(cwd, names, focus=task_desc))
    try:
        with tempfile.TemporaryDirectory(prefix="bugcheck-") as judge_dir:
            res = call_agent(cfg, prompt, Path(judge_dir), slot_id=slot_id, role="judge")
    except EngineBusy:
        raise  # เหมือน judge ของ _eval_gate: ให้งานรอและลองใหม่ ไม่ตัดสินจากการตรวจที่ไม่ได้ทำ
    except Exception as exc:  # noqa: BLE001
        log(f"[bug-check] ตรวจไม่สำเร็จ ({exc}) — ดำเนินการต่อ", slot_id=slot_id)
        return None
    if res.get("status") == "ERROR":
        log("[bug-check] judge ตอบกลับไม่ได้ — ดำเนินการต่อ", slot_id=slot_id)
        return None
    verdict = quality_gates.parse_bug_check(res.get("response") or "")
    if verdict is None:
        log("[bug-check] อ่านผลการตรวจไม่ได้ — ดำเนินการต่อ", slot_id=slot_id)
        return None
    log(f"[bug-check] บั๊กมีจริง={verdict['bug_exists']} — {verdict['reason']}", slot_id=slot_id)
    return verdict


def _bug_check_enabled(cfg: dict, dry_run: bool) -> bool:
    """ด่าน 1 รันเมื่อไม่ใช่ dry run และ evaluation เปิดอยู่ (judge เป็นตัวตรวจ)."""
    return not dry_run and bool(cfg.get("evaluation", {}).get("enabled", True))


def _stop_no_bug(job: Job, labels: dict, repo: str, issue_repo: str, stamp: str, reason: str) -> str:
    """ด่าน 1 ผลลบ: issue อ้างบั๊กที่ไม่มีอยู่จริง → ตั้ง ai-needs-human ให้คนตรวจ ไม่เข้าลูปซ่อม."""
    msg = f"{job.kind}:{job.key} ไม่พบบั๊กตามที่ issue อ้าง — ต้องให้คนตรวจ"
    gh("issue", "comment", job.key, "-R", issue_repo,
       "--body", f"🤖 {msg}\n\nเหตุผลจากการตรวจก่อนเริ่มงาน: {reason}")
    gh("issue", "edit", job.key, "-R", issue_repo, "--remove-label", labels["working"],
       "--add-label", labels.get("needs_human", "ai-needs-human"), check=False)
    append_history({"repo": repo, "kind": job.kind, "key": job.key, "date": stamp, "title": job.title,
                    "origin_repo": job.origin_repo, "state": "NO_BUG", "fail_reason": reason[:300]})
    log(f"⛔ {msg}")
    return msg


def execute(
    job: Job,
    cfg: dict,
    rcfg: dict,
    history: list[dict],
    dry_run: bool,
    slot_id: int | None = None
) -> str:
    repo, labels = rcfg["name"], cfg["labels"]
    issue_repo = job.origin_repo or repo  # issues are labelled/commented in the repo they were filed in
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    branch = f"ai/issue-{job.key}-{stamp}" if job.kind == "issue" else f"ai/{job.key}-{stamp}"
    log(f"เริ่มงาน {job.kind}:{job.key} {job.title!r} -> {branch}", slot_id=slot_id)

    # Slot was claimed atomically before calling execute, but ensure branch is recorded
    if slot_id is not None:
        REGISTRY.register_slot(slot_id, job.kind, job.key, branch, [])

    if job.kind == "issue" and not dry_run:
        gh("issue", "edit", job.key, "-R", issue_repo, "--add-label", labels["working"])

    cwd: Path | None = None
    result_path: Path | None = None
    try:
        cwd = clone(repo, rcfg["base"], branch, slot_id=slot_id)
        env, test_steps = _prepare_workspace(cwd, repo, rcfg, slot_id)

        result_path = cwd.parent / f"{cwd.name}.result.json"
        triage = classify_task(job, cfg, cwd=cwd, call_agent=call_agent)
        log(f"[Triage] {job.kind}:{job.key} จัดเข้า {triage.path.upper()}-PATH ({triage.method}: {triage.reason})", slot_id=slot_id)
        routing_cfg = cfg.get("routing") or {}
        engines = get_engines(cfg)
        if routing_cfg.get("enabled", True) and engines:
            # Per-job view only: the caller's cfg and history are left untouched.
            cfg = {**cfg, "engines": routing.order_engines(
                engines, history, triage.path, int(routing_cfg.get("min_samples", 5)),
                float(routing_cfg.get("demote_below", 0.2)))}
            order = ", ".join(str(e.get("name", "?")) for e in cfg["engines"])
            log(f"[Routing] ลำดับเอเจนต์ {triage.path.upper()}-PATH: {order}", slot_id=slot_id)

        base_prompt = build_prompt(job, rcfg, cwd, env, history, result_path, slot_id=slot_id, cfg=cfg)
        if triage.path == "fast":
            base_prompt = FAST_PATH_PREFIX + base_prompt
        base_prompt += _todo_prompt_suffix(job)
        if job.kind == "issue":
            history_now = load_history()
            _, repair_max = auto_repair_settings(cfg)
            base_prompt += repair_prompt_suffix(job, issue_repo, history_now, repair_max)
            base_prompt += "\n\n" + quality_gates.REPRO_STEPS  # ด่าน 1: เทสต์ที่ fail ก่อนแก้
            if _bug_check_enabled(cfg, dry_run):
                # ด่าน 1: ยืนยันบั๊กก่อนให้ coder แก้ — รันทุกรอบรวมรอบซ่อม เพราะ cwd เป็น clone สดจาก base เสมอ
                verdict = _confirm_bug_exists(job, cfg, cwd, slot_id)
                if verdict is not None and not verdict["bug_exists"]:
                    return _stop_no_bug(job, labels, repo, issue_repo, stamp, verdict["reason"])
            prev_repair = _latest_repair_feedback(job, issue_repo, history_now)
            if prev_repair and prev_repair.get("engine") and cfg.get("engines"):
                cfg = {**cfg, "engines": _prefer_engine(cfg["engines"], prev_repair["engine"])}

        max_attempts = int(cfg.get("max_fix_attempts", 2))
        tests_ok, test_out, result = _agent_fix_loop(cfg, base_prompt, cwd, env, test_steps, result_path, max_attempts, slot_id)

        if _drop_persona_notes(job, cwd, diff_stats(cwd)[1], repo):
            log(f"{job.kind}:{job.key} เขียนบันทึกลง .jules/ — ตัดออก เก็บไว้ใน state/{PERSONA_NOTES_DIR}", slot_id=slot_id)
        lines, files = diff_stats(cwd)
        entry = {"repo": repo, "kind": job.kind, "key": job.key, "date": stamp,
                 "title": result.get("title_th") or job.title, "lines": lines,
                 "triage_path": triage.path, "triage_reason": triage.reason,
                 "origin_repo": job.origin_repo}
        if result.get("engine_used"):
            entry["engine"] = result["engine_used"]
        if "fix_rounds" in result:
            entry["fix_rounds"] = result["fix_rounds"]
        _check_todo_removed(job, cwd, entry, slot_id)

        if result.get("status") == "NO_ACTION" and files:
            # A later round (often a failover engine) found an earlier round's edits already in
            # place and replied NO_ACTION; the diff is real work, so keep going to tests/eval.
            log(f"{job.kind}:{job.key} เอเจนต์ตอบ NO_ACTION แต่มีไฟล์ที่แก้แล้ว {len(files)} ไฟล์ — ทำต่อ", slot_id=slot_id)
        if tests_ok and loop_helpers.needs_test_gate(job, cfg, result.get("status", ""), files):
            tests_ok, test_out = _test_gate_round(cfg, base_prompt, cwd, env, test_steps, result_path, slot_id, entry)
            _drop_persona_notes(job, cwd, diff_stats(cwd)[1], repo)
            lines, files = diff_stats(cwd)
            entry["lines"] = lines
            if not loop_helpers.touched_tests(files):
                entry["no_test_added"] = True

        if not files:
            msg = f"{job.kind}:{job.key} ไม่มีการเปลี่ยนแปลง ({result.get('summary_th', 'ไม่พบสิ่งที่ควรแก้')})"
            entry["state"] = "NO_ACTION"
            _settle_failure(job, cfg, issue_repo, labels, entry, msg, "", dry_run,
                            repairable=True, blocked=is_rule_refusal(result))
            append_history(entry)
            return msg

        if not tests_ok:
            msg = f"{job.kind}:{job.key} เทสต์ไม่ผ่านหลังแก้ {max_attempts} รอบ"
            entry["state"] = "FAILED"
            entry["fail_reason"] = test_out[-300:]
            _settle_failure(job, cfg, issue_repo, labels, entry, msg, test_out, dry_run, repairable=True)
            append_history(entry)
            return msg

        # ขั้นตรวจ Playwright หลังเทสต์ (opt-in ต่อ repo) ผลลง log อย่างเดียว ไม่บล็อกงาน
        playwright_env.post_test_gui_check(rcfg, repo, lambda msg: log(msg, slot_id=slot_id),
                                           gui_check.ROOT / "state")

        static_problems = static_gate.static_gate_problems(cwd, run(["git", "diff", "--cached"], cwd=cwd, check=False).stdout, files)
        if static_problems:  # ด่านก่อนประเมิน: ความลับในบรรทัดที่เพิ่ม / ไวยากรณ์ไฟล์ที่แก้ (ไม่พึ่ง GitHub)
            entry["static_gate"] = static_problems[:3]
            return _block_job(job, entry, labels, issue_repo, dry_run,
                              f"{job.kind}:{job.key} ไม่ผ่านด่านตรวจก่อนประเมิน: " + "; ".join(static_problems[:3]),
                              "", cfg=cfg, repairable=True)
        blocked = _eval_gate(job, cfg, cwd, env, test_steps, test_out, entry, result_path, base_prompt, labels, issue_repo, dry_run, slot_id, mode=triage.path)
        if blocked is not None:
            return blocked

        if dry_run:
            stat = run(["git", "diff", "--cached", "--stat"], cwd=cwd).stdout
            log(f"[dry-run] ไม่ push — งานอยู่ที่ {cwd}\n{stat}", slot_id=slot_id)
            entry.update(state="DRY_RUN", workdir=str(cwd), summary=result.get("summary_th", ""))
            append_history(entry)
            return f"[dry-run] {entry['title']} ({lines} บรรทัด) — {cwd}"

        if slot_id is not None:
            REGISTRY.update_slot_state(slot_id, "pushing")

        if files:
            lock_ok, lock_conflicts = acquire_file_locks(repo, slot_id=slot_id or 1, target_files=files)
            if not lock_ok:
                log(f"⚠️ [File-Locks] ตรวจพบไฟล์ชนกับ Slot อื่น: {', '.join(lock_conflicts)}", slot_id=slot_id)

        return _push_and_open_pr(job, cfg, rcfg, history, entry, cwd, branch, result, lines, files, repo, issue_repo, slot_id, test_steps=test_steps, env=env)
    finally:
        if not dry_run:  # dry-run keeps its workdir on purpose
            if cwd is not None:
                try:
                    force_rmtree(cwd)
                except OSError:
                    pass
            if result_path is not None:
                result_path.unlink(missing_ok=True)
        release_file_locks(slot_id or 1, repo=repo)
        if slot_id is not None:
            REGISTRY.release_slot(slot_id)


def _worktree_fingerprint(cwd: Path) -> str:
    """Hash of the worktree state (status, unstaged and staged diff). Any edit changes it."""
    parts = [
        run(["git", "status", "--porcelain"], cwd=cwd, check=False).stdout,
        run(["git", "diff"], cwd=cwd, check=False).stdout,
        run(["git", "diff", "--cached"], cwd=cwd, check=False).stdout,
    ]
    return hashlib.sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()


def _evaluate_guarded(diff_text: str, task_desc: str, test_out: str, cfg: dict, cwd: Path,
                      slot_id: int | None = None, mode: str = "auto", exclude_engine: str | None = None) -> EvaluationResult:
    """Run the judge, but fail the evaluation if it changed the worktree. The judge runs in a
    scratch dir already; this is defence in depth, because anything it edits would be committed
    by the next git add -A."""
    before = _worktree_fingerprint(cwd)
    result = evaluate_diff(diff_text, task_desc, test_out, cfg, cwd, call_agent=call_agent, mode=mode,
                           exclude_engine=exclude_engine)
    if _worktree_fingerprint(cwd) != before:
        log("[agentic-eval] ⛔ ผู้ประเมินแก้ไขไฟล์ในพื้นที่งาน — ไม่อนุญาตให้ผ่าน", slot_id=slot_id)
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th="⛔ ผู้ประเมินแก้ไขไฟล์ในพื้นที่งาน (ไม่อนุญาต)",
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
        )
    return result


def _ci_fix_budget(cfg: dict, rcfg: dict | None) -> int:
    """จำนวนรอบที่เอเจนต์แก้ CI ได้ต่อ 1 PR (ค่า ci.fix_attempts, 0 = ปิด ให้พัก PR ทันที)."""
    try:
        return max(0, int(ci_config_for(cfg, rcfg)["fix_attempts"]))
    except (TypeError, ValueError, KeyError):
        return 2


def fix_ci_failure(cfg: dict, rcfg: dict, repo: str, pr: int, branch: str, cwd: Path, env: dict,
                   test_steps: list[str], entry: dict, round_no: int, slot_id: int | None = None) -> bool:
    """ให้เอเจนต์อ่าน log ของ CI ที่ล้มแล้วแก้ใน branch เดิม ทดสอบ แล้ว push.

    คืน True เมื่อ push การแก้ไขแล้วและพบ CI run ของ commit ใหม่; False เมื่อแก้ไม่ได้ (ให้พัก PR)
    ไม่ push โค้ดที่เทสต์ในเครื่องไม่ผ่าน
    """
    try:
        ci_log = redact_secrets(fetch_failed_run_log(repo, branch))
        if not ci_log.strip():
            log(f"[CI-Fix] ไม่พบ log ของ CI ที่ล้มสำหรับ {branch} — ไม่ลองแก้", slot_id=slot_id)
            return False
        result_path = cwd.parent / f"{cwd.name}.ci-fix-{round_no}.result.json"
        prompt = render("fix_ci.md", ci_log=truncate_tool_output(ci_log, max_chars=4000), result_path=result_path)
        if slot_id is not None:
            REGISTRY.update_slot_state(slot_id, f"ci_fix_{round_no}")
        agent_res = call_agent(cfg, prompt, cwd, slot_id=slot_id)
        if agent_res.get("status") == "ERROR":
            log("[CI-Fix] เอเจนต์ส่งข้อผิดพลาด — พัก PR", slot_id=slot_id)
            return False
        result = read_result(result_path)
        if not diff_stats(cwd)[1]:
            log("[CI-Fix] เอเจนต์ไม่ได้แก้ไฟล์ — พัก PR", slot_id=slot_id)
            return False
        tests_ok, _ = run_steps(test_steps, cwd, env) if test_steps else (True, "")
        if not tests_ok:
            log("[CI-Fix] เทสต์ในเครื่องไม่ผ่านหลังแก้ CI — ทิ้งการแก้และพัก PR", slot_id=slot_id)
            run(["git", "reset", "--hard", "HEAD"], cwd=cwd, check=False)
            run(["git", "clean", "-fd"], cwd=cwd, check=False)
            return False
        clean_build_artifacts(cwd)
        run(["git", "add", "-A"], cwd=cwd)
        run(["git", "commit", "-m", result.get("commit_message") or f"fix(ci): แก้ CI รอบ {round_no}"], cwd=cwd)
        for attempt in range(1, GH_RETRIES + 1):
            res = run(["git", "push", "origin", branch], cwd=cwd, check=False)
            if res.returncode == 0:
                break
            if attempt == GH_RETRIES:
                raise RuntimeError(f"git push ล้มเหลว:\n{res.stderr[-1500:]}")
            time.sleep(15 * 2 ** (attempt - 1))
        sha = run(["git", "rev-parse", "HEAD"], cwd=cwd).stdout.strip()
        entry["ci_fix_rounds"] = round_no
        append_history(entry)
        log(f"[CI-Fix] push การแก้รอบ {round_no} แล้ว รอ CI ของ commit {sha[:8]}", slot_id=slot_id)
        return wait_for_run_on_sha(repo, branch, sha, logger=lambda m: log(m, slot_id=slot_id))
    except Exception as exc:  # any failure here must hold the PR, never crash the slot
        log(f"[CI-Fix] แก้ CI ไม่สำเร็จ: {exc} — พัก PR", slot_id=slot_id)
        return False


def finish_pr(
    entry: dict,
    cfg: dict,
    rcfg: dict,
    history: list[dict],
    slot_id: int | None = None,
    cwd: Path | None = None,
    branch: str | None = None,
    test_steps: list[str] | None = None,
    env: dict | None = None,
) -> str:
    repo, labels = rcfg["name"], cfg["labels"]
    issue_repo = entry.get("origin_repo") or repo
    if not entry.get("pr"):
        url = create_pr(repo, rcfg["base"], entry["branch"], entry["pr_title"], entry["pr_body"], labels["pr"])
        entry.update(pr=int(url.rstrip("/").split("/")[-1]), state="OPEN")
        append_history(entry)
        if entry["kind"] == "issue":
            gh("issue", "comment", entry["key"], "-R", issue_repo, "--body", f"🤖 เปิด PR แล้ว: {url}")
            gh("issue", "edit", entry["key"], "-R", issue_repo, "--remove-label", labels["working"])
    url = f"https://github.com/{repo}/pull/{entry['pr']}"
    if entry.get("judge_fallback"):
        # The dedicated judge never ran (it failed or timed out), so the pass came from the default engine.
        # The PR stays open for a human; it is not auto-merged on that verdict.
        log(f"PR #{entry['pr']} ผ่านการประเมินด้วย judge สำรองเท่านั้น — ไม่ auto-merge รอคนอนุมัติ", slot_id=slot_id)
        entry["state"] = "OPEN"
        append_history(entry)
        return "รอคนอนุมัติ — ประเมินด้วย judge สำรอง (ไม่ auto-merge)"
    eff_branch = branch or entry.get("branch")
    budget = _ci_fix_budget(cfg, rcfg) if (cwd and eff_branch and env is not None) else 0
    ci_round = 0
    while True:
        merged = try_merge(repo, entry["pr"], cfg, entry.get("small", False), slot_id=slot_id, rcfg=rcfg,
                           cwd=cwd, branch=eff_branch, test_steps=test_steps, env=env,
                           hold_ci_failure=ci_round >= budget)
        if merged != CI_FAIL_RETRY:
            break
        ci_round += 1
        log(f"⚠️ CI ไม่ผ่าน — ให้เอเจนต์แก้ รอบ {ci_round}/{budget}", slot_id=slot_id)
        if not fix_ci_failure(cfg, rcfg, repo, entry["pr"], eff_branch, cwd, env, test_steps or [],
                              entry, ci_round, slot_id=slot_id):
            merged = _hold_pr_for_human(repo, entry["pr"], "ci-failed", "CI ไม่ผ่านและแก้ไม่สำเร็จ", slot_id=slot_id)
            break
    entry["state"] = "MERGED" if merged.startswith("merge แล้ว") else "OPEN"
    append_history(entry)

    if entry.get("kind") == "issue" and HOLD_PR_MARKER in merged:
        # The PR is kept open for a human, so mark the issue failed to stop the queue from opening a duplicate PR.
        gh("issue", "edit", entry["key"], "-R", issue_repo, "--add-label", labels["failed"], check=False)
        gh("issue", "comment", entry["key"], "-R", issue_repo,
           "--body", f"🤖 PR #{entry['pr']} ยังเปิดอยู่ ({merged}) — หยุดสร้าง PR ซ้ำ ต้องให้มนุษย์ตรวจสอบ",
           check=False)

    if entry.get("kind") == "persona" and entry.get("key") == "sentinel":
        try:
            status_val = "resolved" if entry.get("state") == "MERGED" else "open"
            branch_val = entry.get("branch", "")
            issue_id = branch_val.replace("ai/sentinel-", "") if branch_val else dt.datetime.now().strftime("%Y%m%d-%H%M")
            sentinel_tracker.record_sentinel_issue({
                "id": issue_id,
                "title": entry.get("pr_title") or entry.get("title", "Security Fix"),
                "status": status_val,
                "pr": entry.get("pr"),
                "branch": branch_val,
            })
        except Exception as exc:
            log(f"⚠️ บันทึก sentinel_issues.json ไม่สำเร็จ: {exc}", slot_id=slot_id)

    return f"{entry['pr_title']} → {url} ({merged})"


BOOTSTRAP_RETRY_HOURS = 6
BOOTSTRAP_RECHECK_HOURS = 24


def check_and_bootstrap_ci(
    repo_name: str,
    rcfg: dict,
    cfg: dict,
    history: list[dict],
    dry_run: bool,
    slot_id: int | None = None,
) -> bool:
    """Checks if repo lacks CI workflows, and if auto_bootstrap_ci is enabled,
    creates and opens a PR with GitHub Actions CI workflow automatically.
    """
    ci_cfg = ci_config_for(cfg, rcfg)
    if not ci_cfg.get("auto_bootstrap_ci", False) or dry_run:
        return False

    # A PR, or an issue holding the file for a human, counts as done. A failed attempt is retried
    # only after BOOTSTRAP_RETRY_HOURS so a broken repo does not clone on every poll.
    now = dt.datetime.now()
    for h in history:
        if (h.get("repo") != repo_name and h.get("origin_repo") != repo_name) or h.get("kind") != "bootstrap" or h.get("key") != "ci":
            continue
        if h.get("state") in ("OPEN", "MERGED", "ISSUE_OPENED"):
            return False
        # Cooldowns: a failure is retried after 6 h; a repo that already has CI is re-checked after 24 h.
        hours = {"FAILED": BOOTSTRAP_RETRY_HOURS, "SKIPPED": BOOTSTRAP_RECHECK_HOURS}.get(h.get("state"))
        if hours is not None:
            try:
                last = dt.datetime.strptime(h.get("date", ""), "%Y%m%d-%H%M")
            except ValueError:
                return False
            if now - last < dt.timedelta(hours=hours):
                return False

    try:
        open_prs = open_ai_prs(repo_name, cfg)
        if any("bootstrap-ci" in p.get("headRefName", "").lower() or "ci: add github actions" in p.get("title", "").lower() for p in open_prs):
            return False
    except Exception:
        pass

    result = bootstrap_ci(
        repo_name,
        rcfg,
        cfg,
        slot_id=slot_id,
        logger=lambda m: log(m, slot_id=slot_id),
    )
    base_entry = {
        "repo": repo_name,
        "kind": "bootstrap",
        "key": "ci",
        "date": dt.datetime.now().strftime("%Y%m%d-%H%M"),
        "title": "ci: add GitHub Actions CI workflow",
    }
    if result.status == "pr_opened" and result.url:
        entry = {**base_entry, "state": "OPEN", "branch": "ai/bootstrap-ci",
                 "pr": int(result.url.rstrip("/").split("/")[-1]) if "/" in result.url else None}
    elif result.status == "issue_opened":
        entry = {**base_entry, "state": "ISSUE_OPENED", "issue_url": result.url}
    elif result.status == "failed":
        entry = {**base_entry, "state": "FAILED", "error": result.message[-300:]}
    elif result.status == "skipped":
        entry = {**base_entry, "state": "SKIPPED"}
    else:  # dry_run: nothing to remember
        return False
    append_history(entry)
    history.append(entry)
    return result.status in ("pr_opened", "issue_opened")


# ---------------------------------------------------------------- main loop

def _candidate_repos(cfg: dict, rcfg: dict, repo_filter: str | None) -> list[dict]:
    all_configured_repos = cfg.get("repos", []) or [rcfg]
    if repo_filter:
        return [r for r in all_configured_repos if r.get("name") == repo_filter] or [rcfg]
    enabled_repos = [r for r in all_configured_repos if r.get("enabled", True) is not False] or [rcfg]
    # rcfg first, then the rest in configured order
    primary = [r for r in enabled_repos if r.get("name") == rcfg.get("name")]
    others = [r for r in enabled_repos if r.get("name") != rcfg.get("name")]
    return primary + others or [rcfg]


def _adopt_cross_repo(job: Job, t_name: str, cfg: dict, target_rcfg: dict, slot_id: int | None) -> dict:
    """Apply a cross-repo dispatch directive in the issue and clean title/body. Returns the target rcfg."""
    target_repo_name, clean_title, clean_body = parse_target_repo(
        job.title, job.body, t_name, cfg=cfg, on_reject=lambda m: log(m, slot_id=slot_id))
    if target_repo_name != t_name:
        target_rcfg = ensure_repo_config(cfg, target_repo_name)
        job.origin_repo = t_name
    job.title = clean_title
    job.body = clean_body
    return target_rcfg


def _pick_job_slot1(slot_id: int, cfg: dict, rcfg: dict, candidates: list[dict], current_history: list[dict],
                    dry_run: bool) -> tuple[Job | None, dict, bool]:
    """Slot 1 picks user issues across repos. Returns (job, rcfg, handled); handled=True means
    this slot already did its work (CI bootstrap or resumed PR) and must stop."""
    for target_rcfg in candidates:
        t_name = target_rcfg.get("name", "")
        if paused(t_name, cfg):
            continue
        refresh_history(t_name, current_history)
        if not dry_run and check_and_bootstrap_ci(t_name, target_rcfg, cfg, current_history, dry_run, slot_id=slot_id):
            return None, target_rcfg, True
        if not dry_run and resume_pending(cfg, target_rcfg, current_history, slot_id=slot_id):
            return None, target_rcfg, True
        pending = open_ai_prs(t_name, cfg)
        max_slots = cfg.get("parallel", {}).get("slots", 3)
        if not dry_run and len(pending) >= max_slots:
            continue
        issues = get_available_issues(t_name, cfg)
        job = claim_task_for_slot(slot_id, cfg, current_history, issues, REGISTRY, repo_name=t_name)
        if job:
            return job, _adopt_cross_repo(job, t_name, cfg, target_rcfg, slot_id), False
    return None, rcfg, False


def _pick_job_other_slot(slot_id: int, cfg: dict, rcfg: dict, candidates: list[dict],
                         current_history: list[dict]) -> tuple[Job | None, dict]:
    """Slots > 1 take surplus user issues first, then fall back to a persona for rcfg."""
    for target_rcfg in candidates:
        t_name = target_rcfg.get("name", "")
        if paused(t_name, cfg):
            continue
        refresh_history(t_name, current_history)
        issues = get_available_issues(t_name, cfg)
        job = claim_task_for_slot(slot_id, cfg, current_history, issues, REGISTRY, repo_name=t_name,
                                  issues_only=True)
        if job and job.kind == "issue":
            return job, _adopt_cross_repo(job, t_name, cfg, target_rcfg, slot_id)
    job = claim_task_for_slot(slot_id, cfg, current_history, [], REGISTRY, repo_dir=None, repo_name=rcfg.get("name"))
    return job, rcfg


def _record_job_failure(exc: Exception, job: Job, cfg: dict, repo: str, dry_run: bool, slot_id: int | None) -> str:
    """Log and record a failed job; labels the issue failed after 3 ERROR entries. Returns the summary line."""
    first_line = next((ln for ln in str(exc).splitlines() if ln.strip()), type(exc).__name__)
    line = f"{job.kind}:{job.key} ล้มเหลว: {first_line[:300]}"
    log(f"ข้อผิดพลาด:\n{str(exc)[-2000:]}", slot_id=slot_id)
    issue_repo = job.origin_repo or repo
    err_entry = {"repo": repo, "kind": job.kind, "key": job.key, "title": job.title,
                 "date": dt.datetime.now().strftime("%Y%m%d-%H%M"), "state": "ERROR",
                 "error": str(exc)[-1000:], "origin_repo": job.origin_repo}
    append_history(err_entry)
    release_issue(job, cfg, repo, dry_run)
    errors = sum(1 for h in load_history() if (h.get("origin_repo") or h.get("repo")) == issue_repo
                 and h.get("kind") == "issue" and h.get("key") == job.key and h.get("state") == "ERROR")
    if job.kind == "issue" and errors >= 3 and not dry_run:
        gh("issue", "edit", job.key, "-R", issue_repo, "--add-label", cfg["labels"]["failed"], check=False)
        gh("issue", "comment", job.key, "-R", issue_repo,
           "--body", f"🤖 ล้มเหลว {errors} ครั้ง — หยุดลองใหม่\n\n```\n{str(exc)[-1500:]}\n```", check=False)
    return line


def _handle_job_exception(exc: Exception, job: Job, cfg: dict, repo: str, dry_run: bool, slot_id: int | None) -> str:
    """A job that ended with EngineBusy is released and kept retryable: no ERROR entry (so it does not
    count toward the 3-strike limit) and no ai-failed label (BUG-6). Any other error is recorded as before."""
    if isinstance(exc, EngineBusy):
        release_issue(job, cfg, repo, dry_run)
        first_line = next((ln for ln in str(exc).splitlines() if ln.strip()), "EngineBusy")
        log(f"⏳ {job.kind}:{job.key} ไม่ได้ทำงาน เพราะ Engine ไม่ว่าง — ไม่นับเป็นความล้มเหลว ({first_line[:200]})", slot_id=slot_id)
        return f"{job.kind}:{job.key} รอ Engine ไม่ว่าง (ไม่นับเป็นความล้มเหลว): {first_line[:300]}"
    return _record_job_failure(exc, job, cfg, repo, dry_run, slot_id)


def process_slot(
    slot_id: int,
    cfg: dict,
    rcfg: dict,
    history: list[dict] | None = None,
    dry_run: bool = False,
    persona_override: str | None = None,
    repo_filter: str | None = None,
) -> bool:
    clean_expired_locks()
    current_history = load_history()

    slot_assign = get_slot_assignment(slot_id, cfg)
    if slot_assign and not repo_filter and slot_assign.get("repo"):
        repo_filter = slot_assign.get("repo")
    candidate_repos = _candidate_repos(cfg, rcfg, repo_filter)

    active_job: Job | None = None
    active_rcfg: dict = rcfg
    if persona_override:
        active_job = Job("persona", persona_override, persona_override, "")
        REGISTRY.register_slot(slot_id, active_job.kind, active_job.key, f"ai/{active_job.key}", [])
    elif slot_id == 1:
        active_job, active_rcfg, handled = _pick_job_slot1(slot_id, cfg, rcfg, candidate_repos, current_history, dry_run)
        if handled:
            return True
    else:
        active_job, active_rcfg = _pick_job_other_slot(slot_id, cfg, rcfg, candidate_repos, current_history)

    if not active_job:
        is_idle_before = getattr(process_slot, "_idle_slots", set())
        if slot_id not in is_idle_before:
            log(f"{rcfg['name']}: ไม่มีงานสำหรับช่องนี้ (สแตนด์บาย)", slot_id=slot_id)
            if not hasattr(process_slot, "_idle_slots"):
                process_slot._idle_slots = set()
            process_slot._idle_slots.add(slot_id)
        return False

    if hasattr(process_slot, "_idle_slots") and slot_id in process_slot._idle_slots:
        process_slot._idle_slots.discard(slot_id)
        log(f"{active_rcfg['name']}: พบงานใหม่! เริ่มปฏิบัติการ {active_job.kind}:{active_job.key}", slot_id=slot_id)

    repo = active_rcfg["name"]
    try:
        line = execute(active_job, cfg, active_rcfg, current_history, dry_run, slot_id=slot_id)
    except QuotaExhausted:
        release_issue(active_job, cfg, repo, dry_run)
        raise
    except Exception as exc:
        line = _handle_job_exception(exc, active_job, cfg, repo, dry_run, slot_id)

    log(line, slot_id=slot_id)
    if not dry_run:
        _report_safely(repo, line, slot_id=slot_id)
    return True


def process_repo(cfg: dict, rcfg: dict, history: list[dict], dry_run: bool, skip_issues: bool = False) -> bool:
    return process_slot(1, cfg, rcfg, history, dry_run)


def release_issue(job: Job, cfg: dict, repo: str, dry_run: bool) -> None:
    if job.kind == "issue" and not dry_run:
        gh("issue", "edit", job.key, "-R", job.origin_repo or repo, "--remove-label", cfg["labels"]["working"], check=False)


def resume_pending(
    cfg: dict,
    rcfg: dict,
    history: list[dict],
    slot_id: int | None = None
) -> bool:
    repo = rcfg["name"]
    for entry in history:
        if entry.get("repo") == repo and entry.get("state") == "PUSHED":
            branch = entry.get("branch")
            # ถ้ามีประวัติที่ระบุว่า branch หรือ PR นี้ merge หรือปิดไปแล้ว ให้ข้ามทันที
            already_done = any(h.get("branch") == branch and h.get("state") in ("MERGED", "CLOSED") for h in history)
            if already_done:
                entry["state"] = "MERGED"
                append_history(entry)
                continue
            log(f"ทำต่อจากครั้งก่อน: เปิด PR ให้ branch {entry['branch']}", slot_id=slot_id)
            entry["resume_attempts"] = entry.get("resume_attempts", 0) + 1
            if entry["resume_attempts"] > 3:
                entry["state"] = "ERROR"
                append_history(entry)
                continue
            append_history(entry)
            line = finish_pr(entry, cfg, rcfg, history, slot_id=slot_id)
            append_history(entry)
            log(line, slot_id=slot_id)
            _report_safely(repo, line, slot_id=slot_id)
            return True

    # The global mode only applies to repos without a per-repo merge level; try_merge decides for the rest.
    level = feature_gen.merge_level_for(cfg, repo)
    if level is None and cfg["merge_mode"] == "review-all":
        return False

    for pr in open_ai_prs(repo, cfg):
        entry = next((h for h in history if h.get("repo") == repo and h.get("pr") == pr["number"]), None)
        if entry and entry.get("state") in ("MERGED", "CLOSED"):
            continue
        if (gh_json("pr", "view", str(pr["number"]), "-R", repo, "--json", "state") or {}).get("state") != "OPEN":
            continue
        if entry is None:
            entry = {"repo": repo, "kind": "pr", "key": str(pr["number"]), "title": pr["title"],
                     "date": dt.datetime.now().strftime("%Y%m%d-%H%M"), "pr": pr["number"]}
            append_history(entry)
        entry.setdefault("pr_title", pr["title"])
        if level is None and cfg["merge_mode"] == "small-only" and not entry.get("small"):
            return False
        log(f"ทำต่อจากครั้งก่อน: ตรวจ CI/merge PR #{pr['number']}", slot_id=slot_id)
        line = finish_pr(entry, cfg, rcfg, history, slot_id=slot_id, branch=pr.get("headRefName") or None)
        append_history(entry)
        log(line, slot_id=slot_id)
        _report_safely(repo, line, slot_id=slot_id)
        return True
    return False


def clear_stale_labels(repo: str, cfg: dict) -> None:
    label = cfg["labels"]["working"]
    for issue in gh_json("issue", "list", "-R", repo, "--state", "open", "--label", label, "--json", "number"):
        log(f"ลบป้าย {label} ที่ค้างจาก issue #{issue['number']}")
        gh("issue", "edit", str(issue["number"]), "-R", repo, "--remove-label", label, check=False)


def _run_feature_approvals(cfg: dict) -> None:
    """Approved feature plans -> task issues. Throttled inside feature_gen; never raises."""
    try:
        for res in feature_gen.maybe_process_approvals(cfg, STATE):
            if res.get("enqueued") or res.get("errors"):
                err = f" (ผิดพลาด: {res['errors'][0][:120]})" if res.get("errors") else ""
                log(f"🧩 แผนฟีเจอร์ {res['repo']}: สร้างงาน {res.get('enqueued', 0)} รายการ{err}")
    except Exception as exc:  # noqa: BLE001
        log(f"⚠️ ตรวจแผนฟีเจอร์ที่อนุมัติไม่สำเร็จ: {redact_secrets(str(exc))}")


def _run_scheduled_todo_scan(cfg: dict) -> None:
    """Opt-in scheduled AI-TODO scan (slot 1 only); never raises."""
    try:
        from . import todo_scan
        for res in todo_scan.maybe_run_scheduled(cfg, STATE / "todo_scan_schedule.json"):
            if res.get("ok"):
                log(f"[AI-TODO] สแกนตามรอบ {res.get('repo')}: สร้าง {len(res.get('created') or [])} issue")
            else:
                log(f"[AI-TODO] สแกนตามรอบ {res.get('repo')} ล้มเหลว: {res.get('error')}")
    except Exception as exc:
        log(f"[AI-TODO] สแกนตามรอบผิดพลาด: {exc}")


def _graceful_drain_requested() -> bool:
    """O27 Graceful Drain: True when the GUI asked running workers to stop after their current job."""
    from . import autonomous_upgrades  # local import: autonomous_upgrades imports this module
    return bool(autonomous_upgrades.read_drain_state(STATE).get("draining"))


def _persona_window_open(cfg: dict) -> bool:
    """O27 quiet hours from config personas.schedule (mode: always | nightly, start_hour, end_hour)."""
    from . import autonomous_upgrades  # local import: autonomous_upgrades imports this module
    sched = (cfg.get("personas") or {}).get("schedule") or {}
    try:
        start, end = int(sched.get("start_hour", 0)), int(sched.get("end_hour", 6))
    except (TypeError, ValueError):
        start, end = 0, 6
    return autonomous_upgrades.is_persona_window_open(str(sched.get("mode", "always")), None, start, end)


def _plateau_stop_enabled(cfg: dict | None) -> bool:
    """O27 convergence guard: stop refinement when the judge score stops improving (default on)."""
    return bool(((cfg or {}).get("evaluation") or {}).get("plateau_stop", True))


def slot_worker_loop(
    slot_id: int,
    cfg: dict,
    rcfg: dict,
    dry_run: bool,
    loop: bool,
    persona_override: str | None = None,
    stop_event: threading.Event | None = None,
    config_path: Path | str | None = None,
    repo_filter: str | None = None,
    outcomes: dict | None = None,
) -> None:
    """Worker loop for a single slot with dynamic config hot-reload.

    Errors never end the loop: each consecutive error waits 60 s, doubling, capped at 15 min,
    and the wait is on stop_event so shutdown is immediate. outcomes[slot_id] is set to "quota"
    when the worker stops because of QuotaExhausted (used for the exit code).
    A Graceful Drain request is checked before each new job, so the current job always finishes.
    """
    errors = 0
    current_cfg = dict(cfg)
    current_rcfg = dict(rcfg)

    while stop_event is None or not stop_event.is_set():
        if _graceful_drain_requested():
            log("Graceful Drain เปิดอยู่ — ไม่รับงานใหม่ ช่องนี้หยุดหลังงานปัจจุบัน", slot_id=slot_id)
            break
        try:
            if config_path:
                reloaded = load_cfg(config_path)
                if reloaded:
                    current_cfg = reloaded
                    repo_name = repo_filter or current_rcfg.get("name")
                    repos = current_cfg.get("repos", [])
                    matched = next((r for r in repos if r.get("name") == repo_name), None)
                    if matched:
                        current_rcfg = matched
                    elif repo_filter and current_rcfg.get("name") == repo_filter:
                        # --repo given on the CLI but not in config.yaml: keep that dynamic repo
                        # (falling back to repos[0] would silently work on a different repo).
                        current_cfg.setdefault("repos", []).append(current_rcfg)
                    elif repos:
                        current_rcfg = repos[0]

            if slot_id == 1 and not dry_run:
                _run_scheduled_todo_scan(current_cfg)
                _run_feature_approvals(current_cfg)
            history = load_history()
            if repo_filter is not None:
                progressed = process_slot(
                    slot_id, current_cfg, current_rcfg, history, dry_run, persona_override, repo_filter=repo_filter
                )
            else:
                progressed = process_slot(slot_id, current_cfg, current_rcfg, history, dry_run, persona_override)
            errors = 0
            if not loop:
                break
            poll_interval = current_cfg.get("parallel", {}).get("poll_interval_seconds", 120)
            wait_time = min(15, poll_interval) if progressed else (poll_interval if slot_id == 1 else 30)
            if stop_event:
                if stop_event.wait(wait_time):
                    break
            else:
                time.sleep(wait_time)
        except QuotaExhausted as exc:
            log(f"โควตาหมด — พักชั่วคราว ({exc})", slot_id=slot_id)
            if not loop:
                if outcomes is not None:
                    outcomes[slot_id] = "quota"
                break
            if stop_event:
                stop_event.wait(300)
            else:
                time.sleep(300)
        except Exception as exc:
            errors += 1
            delay = min(60 * 2 ** min(errors - 1, 10), 900)
            log(f"ข้อผิดพลาดในลูป (ครั้งที่ {errors}) — พัก {delay} วินาทีแล้วลองใหม่: {exc}", slot_id=slot_id)
            if not loop:
                break
            if stop_event is not None:
                if stop_event.wait(delay):
                    break
            else:
                time.sleep(delay)


def select_slot_ids(parallel_cfg: dict) -> list[int]:
    """คืนรายการ slot ที่ต้องรันจริง.

    - ``parallel.active_slot`` = 1/2/3 → รันเฉพาะช่องนั้น (โหมดทีละช่อง)
    - ไม่ตั้งค่า/null → รันทุกช่องตาม ``slots`` และ ``enabled`` (พฤติกรรมเดิม)
    """
    num_slots = parallel_cfg.get("slots", 3) if parallel_cfg.get("enabled", True) else 1
    all_ids = list(range(1, int(num_slots) + 1))
    active = parallel_cfg.get("active_slot")
    if active is None or active == "":
        return all_ids
    try:
        active_id = int(active)
    except (TypeError, ValueError):
        return all_ids
    return [active_id] if active_id in all_ids else all_ids


def gui_check_at_start(cfg: dict, dry_run: bool = False) -> bool | None:
    """ตรวจ GUI ด้วย Playwright ตอนเริ่มลูปหลัก แล้วลงผลใน log. ไม่หยุดลูปไม่ว่าผลจะเป็นอย่างไร.
    คืน None เมื่อไม่ได้ตรวจ (dry-run หรือปิดด้วย gui_check.enabled: false ใน config)."""
    if dry_run or not (cfg.get("gui_check") or {}).get("enabled", True):
        return None
    return run_gui_check(lambda msg: log(msg))


def main(argv: list[str] | None = None) -> int:
    import argparse
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="auto-dev-crew")
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("--repo", help="ทำเฉพาะ repo นี้ (owner/name)")
    p.add_argument("--dry-run", action="store_true", help="ทำงานในเครื่อง ไม่ push/เปิด PR/คอมเมนต์")
    p.add_argument("--loop", action="store_true", help="ทำต่อเนื่องจนไม่มีงานหรือโควตาหมด")
    p.add_argument("--persona", help="บังคับใช้ตัวละครนี้ (ข้ามคิว issue)")
    p.add_argument("--slot", type=int, help="ระบุรันเฉพาะ Slot นี้ (1, 2, 3)")
    p.add_argument("--engine", help="แทน engine.command ใน config (agy / opencode / gemini)")
    p.add_argument("--model", help="แทน engine.model ใน config (opencode ใช้รูปแบบ provider/model)")
    args = p.parse_args(argv)
    export_dotenv_to_environ()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.engine or args.model:
        engines = get_engines(cfg)
        if engines:
            eng = dict(engines[0])
            if args.engine:
                eng["command"] = args.engine
                eng["name"] = f"{args.engine}-override"
                eng["path"] = None
            if args.model:
                eng["model"] = args.model
            cfg["engines"] = [eng]
    if args.persona:
        cfg.setdefault("personas", {})["enabled"] = [args.persona]

    if args.repo:
        matched = [r for r in cfg.get("repos", []) if r.get("name") == args.repo]
        if matched:
            repos = matched
        else:
            dyn_rcfg = ensure_repo_config(cfg, args.repo)
            repos = [dyn_rcfg]
            cfg.setdefault("repos", []).append(dyn_rcfg)
    else:
        repos = cfg.get("repos", [])
        if not repos:
            dyn_rcfg = ensure_repo_config(cfg, "example-owner/example-repo")
            repos = [dyn_rcfg]
    clean_work()
    SLOTS_DIR.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        for r in repos:
            try:
                ensure_labels(r["name"], cfg)
                clear_stale_labels(r["name"], cfg)
            except Exception as exc:
                log(f"ตรวจสอบฉลาก GitHub ไม่สำเร็จ: {exc}")

    gui_check_at_start(cfg, args.dry_run)

    parallel_cfg = cfg.get("parallel", {})
    num_slots = parallel_cfg.get("slots", 3) if parallel_cfg.get("enabled", True) else 1
    active_ids = select_slot_ids(parallel_cfg)

    outcomes: dict[int, str] = {}
    if args.slot:
        rcfg = repos[0]
        slot_worker_loop(
            args.slot, cfg, rcfg, args.dry_run, args.loop, args.persona,
            config_path=Path(args.config), repo_filter=args.repo, outcomes=outcomes
        )
        return 3 if outcomes.get(args.slot) == "quota" else 0

    rcfg = repos[0]
    stop_event = threading.Event()
    threads = []
    if len(active_ids) == 1:
        log(f"โหมดทีละช่อง: รันเฉพาะ Slot {active_ids[0]} (ช่องอื่นหยุดพัก)")
    else:
        log(f"เริ่มการทำงานขนาน {num_slots} ช่อง (Slot 1: สำรอง Issue, Slot 2-{num_slots}: Personas)")
    # --persona goes to ONE worker only (slot 2, the first persona slot; slot 1 if there is only one slot).
    # Giving it to every slot made all parallel workers run the same persona at once.
    persona_slot = 2 if num_slots >= 2 else 1
    if len(active_ids) == 1:
        persona_slot = active_ids[0]

    try:
        for s_id in active_ids:
            t = threading.Thread(
                target=slot_worker_loop,
                args=(s_id, cfg, rcfg, args.dry_run, args.loop,
                      args.persona if s_id == persona_slot else None, stop_event),
                kwargs={"config_path": Path(args.config), "repo_filter": args.repo, "outcomes": outcomes},
                name=f"slot-{s_id}-worker",
                daemon=True
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()
        # Exit 3 (quota) only when every slot worker stopped because its quota ran out.
        all_quota = len(outcomes) == len(active_ids) and all(v == "quota" for v in outcomes.values())
        return 3 if all_quota else 0
    except KeyboardInterrupt:
        log("ผู้ใช้สั่งหยุดการทำงาน — กำลังปิด worker ทุกช่อง...")
        stop_event.set()
        # Give each slot worker time to finish its current job (and release its slot)
        # instead of letting daemon threads die mid-job.
        for t in threads:
            t.join(timeout=30)
        still_running = [t.name for t in threads if t.is_alive()]
        if still_running:
            log(f"worker ยังทำงานอยู่หลังรอ 30 วินาที: {', '.join(still_running)}")
        return 130


if __name__ == "__main__":
    sys.exit(main())

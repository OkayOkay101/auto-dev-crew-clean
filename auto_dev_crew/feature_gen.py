"""Feature generation: the agent proposes new features and files them as issues waiting for human approval.

Flow: propose (scan + roadmap + whole-repo reading) -> file `ai-plan` issues -> a human adds
`ai-plan-approved` -> enqueue_approved creates an ordinary `ai-task` issue -> the normal pipeline builds it
and opens a PR -> try_merge applies the per-repo merge level. When that task issue is closed,
close_done_plans closes the plan issue too (otherwise the plan stays open forever).
"""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Callable

from . import deep_scan
from .locks import locked_json_read, locked_json_write
from .redact import redact_secrets

PLAN_LABEL = "ai-plan"
APPROVED_LABEL = "ai-plan-approved"
MAX_PROPOSALS_PER_REPO = 3
DEFAULT_LARGE_CHANGE_FILES = 8
MERGE_LEVELS = (1, 2, 3)
APPROVAL_MODES = ("manual", "auto")  # manual = a human adds the approved label; auto = first N plans get it at filing
DEFAULT_AUTO_APPROVE_MAX = 1
ROADMAP_FILES = ("FEATURES.md", "ROADMAP.md", "docs/ROADMAP.md", "docs/roadmap.md", "docs/features.md")
ROADMAP_MAX_CHARS = 8000
GAP_MAX_ITEMS = 20
MAX_STEPS = 12
MAX_FILES = 30
TITLE_MAX = 120

_RISKY_BASENAMES = frozenset({
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "pipfile.lock", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile", "gemfile.lock", "opencode.json",
})


# ---------------------------------------------------------------- settings

def _repo_entry(cfg: dict | None, repo: str) -> dict:
    return next((r for r in (cfg or {}).get("repos") or []
                 if isinstance(r, dict) and r.get("name") == repo), {})


def settings_for(cfg: dict | None, repo: str) -> dict:
    """Feature-gen settings for one repo. Off by default (ai-plan issues need an explicit opt-in);
    an explicit `enabled: true` in the repo entry or globally turns it on, `false` turns it off."""
    global_fg = (cfg or {}).get("feature_gen")
    global_fg = global_fg if isinstance(global_fg, dict) else {}
    entry = _repo_entry(cfg, repo)
    repo_fg = entry.get("feature_gen") if isinstance(entry.get("feature_gen"), dict) else {}

    def flag(key: str) -> bool:
        return repo_fg.get(key, True) is not False

    try:
        max_props = int(repo_fg.get("max_proposals", global_fg.get("max_proposals", MAX_PROPOSALS_PER_REPO)))
    except (TypeError, ValueError):
        max_props = MAX_PROPOSALS_PER_REPO
    try:
        large = int(repo_fg.get("large_change_files", global_fg.get("large_change_files", DEFAULT_LARGE_CHANGE_FILES)))
    except (TypeError, ValueError):
        large = DEFAULT_LARGE_CHANGE_FILES
    mode = repo_fg.get("approval_mode", global_fg.get("approval_mode", "manual"))
    try:
        auto_max = int(repo_fg.get("auto_approve_max", global_fg.get("auto_approve_max", DEFAULT_AUTO_APPROVE_MAX)))
    except (TypeError, ValueError):
        auto_max = DEFAULT_AUTO_APPROVE_MAX
    return {
        "enabled": repo_fg.get("enabled", global_fg.get("enabled", False)) is True,
        "whole_repo": flag("whole_repo"),
        "roadmap": flag("roadmap"),
        "scan_gaps": flag("scan_gaps"),
        "max_proposals": min(max(max_props, 1), MAX_PROPOSALS_PER_REPO),
        "large_change_files": max(large, 1),
        "approval_mode": mode if mode in APPROVAL_MODES else "manual",
        "auto_approve_max": min(max(auto_max, 1), MAX_PROPOSALS_PER_REPO),
    }


def merge_level_for(cfg: dict | None, repo: str) -> int | None:
    """1 = a human merges every PR, 2 = auto-merge only low-risk PRs, 3 = merge when CI passes. None = legacy global mode."""
    level = _repo_entry(cfg, repo).get("merge_level")
    return level if level in MERGE_LEVELS else None


# ---------------------------------------------------------------- risk

def path_risk(path: str) -> str | None:
    """Name the risk kind of one path, or None. Risky paths always need a human, never auto-merge."""
    norm = path.replace("\\", "/").strip("/")
    low = norm.lower()
    base = low.rsplit("/", 1)[-1]
    if low.startswith(".github/"):
        return "CI/workflow"
    if base == ".env" or base.startswith(".env.") or base.endswith(".env"):
        return "config/key"
    if base.startswith("config.") or base in {"config.yaml", "config.yml"}:
        return "config/key"
    if "key" in base or "secret" in base or "credential" in base:
        return "config/key"
    if base in _RISKY_BASENAMES or base.endswith(".lock"):
        return "dependency"
    if "migration" in low or base.endswith(".sql"):
        return "migration"
    return None


def risk_reasons(files: list[str], large_threshold: int = DEFAULT_LARGE_CHANGE_FILES) -> list[str]:
    reasons: list[str] = []
    for f in files:
        kind = path_risk(f)
        if kind:
            reason = f"{kind}: {f}"
            if reason not in reasons:
                reasons.append(reason)
    if len(files) > large_threshold:
        reasons.append(f"แก้ไฟล์จำนวนมาก ({len(files)} ไฟล์ > {large_threshold})")
    return reasons


def pr_risk(repo: str, pr: int, cfg: dict | None, run: Callable[..., str] | None = None) -> list[str]:
    """Risk reasons for a PR's changed files. A failure to read the file list counts as risky (fail closed)."""
    run = run or deep_scan._default_run
    try:
        data = json.loads(run("pr", "view", str(pr), "-R", repo, "--json", "files") or "{}")
    except Exception as exc:  # noqa: BLE001 — unknown file list must not auto-merge
        return [redact_secrets(f"อ่านรายการไฟล์ของ PR ไม่สำเร็จ: {exc}")]
    files = [f.get("path", "") for f in data.get("files", []) if isinstance(f, dict) and f.get("path")]
    if not files:
        return ["อ่านรายการไฟล์ของ PR ไม่สำเร็จ (ว่างเปล่า)"]
    threshold = settings_for(cfg, repo)["large_change_files"]
    return risk_reasons(files, threshold)


# ---------------------------------------------------------------- proposals

def validate_proposals(raw_items: list, max_items: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        title = " ".join(title.split())[:TITLE_MAX]
        if title.lower() in seen:
            continue
        raw_plan = item.get("plan")
        if not isinstance(raw_plan, list):
            continue
        steps = [s.strip() for s in raw_plan if isinstance(s, str) and s.strip()][:MAX_STEPS]
        if not steps:
            continue
        files: list[str] = []
        raw_files = item.get("files")
        for f in (raw_files if isinstance(raw_files, list) else []):
            if not isinstance(f, str):
                continue
            p = f.strip().replace("\\", "/")
            if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/"):
                continue
            if p not in files:
                files.append(p)
        seen.add(title.lower())
        out.append({
            "title": title,
            "why": str(item.get("why") or "").strip(),
            "plan": steps,
            "files": files[:MAX_FILES],
            "tests": str(item.get("tests") or "").strip(),
        })
        if len(out) >= max_items:
            break
    return out


def plan_marker(title: str) -> str:
    # Idempotency key: the same feature title is never filed twice (open or closed). Not a security hash.
    digest = hashlib.sha1(" ".join(title.lower().split()).encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"<!-- feature-plan:{digest} -->"


def render_plan_body(p: dict) -> str:
    files = "\n".join(f"- `{f}`" for f in p["files"]) or "- (ไม่ระบุ)"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(p["plan"], 1))
    risk = "\n".join(f"- {r}" for r in p.get("risk", [])) or "- ไม่มี"
    body = (
        f"{plan_marker(p['title'])}\n\n"
        f"**เหตุผล:** {p.get('why') or '-'}\n\n"
        f"**ไฟล์ที่คาดว่าจะแก้:**\n{files}\n\n"
        f"**ขั้นตอน:**\n{steps}\n\n"
        f"**วิธีทดสอบ:** {p.get('tests') or '-'}\n\n"
        f"**ความเสี่ยงที่ตรวจพบ:**\n{risk}\n\n"
        "---\n"
        + (
            "🤖 แผนนี้อนุมัติอัตโนมัติแล้ว (โหมด auto) ระบบจะเริ่มสร้างงานตามแผนภายในไม่กี่นาที\n"
            if p.get("auto_approved") else
            f"🤖 แผนนี้รอการอนุมัติ: เพิ่มป้าย `{APPROVED_LABEL}` บน issue นี้ ระบบจึงจะเริ่มสร้างฟีเจอร์ตามแผน\n"
        )
    )
    return redact_secrets(body)


def read_roadmap(root: Path) -> str:
    for rel in ROADMAP_FILES:
        f = Path(root) / rel
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            return redact_secrets(text[:ROADMAP_MAX_CHARS])
    return ""


def gap_lines(run_data: dict | None) -> list[str]:
    """Open findings from the latest scan, as plain lines for the proposal prompt."""
    lines: list[str] = []
    for it in (run_data or {}).get("findings", []) or []:
        if it.get("status") in ("dismissed", "unverified"):
            continue
        lines.append(f"- [{it.get('category')}/{it.get('severity')}] {it.get('title')} ({it.get('path')}:{it.get('line')})")
        if len(lines) >= GAP_MAX_ITEMS:
            break
    return lines


def build_proposal_prompt(repo: str, roadmap: str, gaps: list[str], whole_repo: bool, max_items: int) -> str:
    parts = [
        "Return ONLY a JSON array, no other text. คืนค่าเป็น JSON array เท่านั้น ห้ามมีข้อความอื่น\n",
        f"You propose new features for the repository {repo}. เสนอฟีเจอร์ใหม่สำหรับ repo นี้\n",
    ]
    if whole_repo:
        parts.append("Read the repository in your working directory first (glob, grep, read) so that you do not "
                     "propose something that already exists.\n")
    else:
        parts.append("Base the proposals only on the roadmap and the gaps below; do not read unrelated code.\n")
    parts.append(
        f"Propose at most {max_items} features. Each must be new (not already in the code) and useful for this "
        "project. Do not edit files and do not run commands.\n"
        "Each item is an object with fields: title (short), why (one or two sentences), plan (array of concrete "
        "implementation steps), files (array of repo-relative paths you expect to change), tests (how to verify it).\n"
    )
    if roadmap:
        parts.append("=== ROADMAP ===\n" + roadmap + "\n")
    if gaps:
        parts.append("=== GAPS FROM CODE SCAN ===\n" + "\n".join(gaps) + "\n")
    return redact_secrets("".join(parts))


def propose(repo: str, cfg: dict | None, root: Path, call_model: Callable[[str], str],
            gaps: list[str] | None = None, roadmap: str = "") -> list[dict]:
    """Ask the model for proposals. A reply with no JSON array at all raises (bad output must not look
    like 'no ideas'); a real empty array or items that all fail validation return []."""
    s = settings_for(cfg, repo)
    prompt = build_proposal_prompt(repo, roadmap, gaps or [], s["whole_repo"], s["max_proposals"])
    raw = call_model(prompt)
    parsed = deep_scan._parse_model_array(raw)
    if parsed is None:
        raise ValueError(_i18n.t("โมเดลตอบไม่เป็น JSON array (ผิดรูปแบบ) จึงอ่านแผนไม่ได้"))
    items = validate_proposals(parsed, s["max_proposals"])
    for p in items:
        p["risk"] = risk_reasons(p["files"], s["large_change_files"])
    return items


LAST_DIR = "feature_gen"


def _last_path(state_dir: Path, repo: str) -> Path:
    return Path(state_dir) / LAST_DIR / (repo.replace("/", "__") + ".last.json")


def save_last(state_dir: Path, repo: str, result: dict) -> None:
    """Keep the most recent feature-plan result per repo so the panel can show what happened."""
    path = _last_path(state_dir, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    locked_json_write(path, {**result, "at": dt.datetime.now().isoformat(timespec="seconds")})


def load_last(state_dir: Path, repo: str) -> dict | None:
    data = locked_json_read(_last_path(state_dir, repo), default=None)
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- GitHub

def _ensure_labels(repo: str, run: Callable[..., str]) -> None:
    run("label", "create", PLAN_LABEL, "-R", repo, "--color", "0E8A16", "--force")
    run("label", "create", APPROVED_LABEL, "-R", repo, "--color", "1D76DB", "--force")


def file_plans(repo: str, proposals: list[dict], run: Callable[..., str] | None = None,
               auto_approve: int = 0) -> dict:
    """File each proposal as an `ai-plan` issue. Skips a title whose marker already exists (open or closed).
    The first `auto_approve` plans that are actually filed also get the approved label (auto mode)."""
    run = run or deep_scan._default_run
    summary: dict = {"created": 0, "skipped": 0, "errors": [], "urls": [], "auto_approved": 0}
    if not proposals:
        return summary
    try:
        _ensure_labels(repo, run)
        bodies = deep_scan.fetch_issue_bodies(repo, PLAN_LABEL, run=run)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(redact_secrets(f"เตรียม label/อ่าน issue เดิมไม่สำเร็จ: {exc}"))
        return summary
    for p in proposals:
        marker = plan_marker(p["title"])
        if any(marker in (b or "") for b in bodies):
            summary["skipped"] += 1
            continue
        auto = summary["auto_approved"] < auto_approve
        labels = f"{PLAN_LABEL},{APPROVED_LABEL}" if auto else PLAN_LABEL
        body = render_plan_body({**p, "auto_approved": auto})
        try:
            url = run("issue", "create", "-R", repo, "--title", redact_secrets(f"[plan] {p['title'][:80]}"),
                      "--body", body, "--label", labels).strip()
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(redact_secrets(f"{p['title'][:40]}: สร้าง issue ไม่สำเร็จ: {exc}"))
            continue
        summary["created"] += 1
        if auto:
            summary["auto_approved"] += 1
        summary["urls"].append(url)
        bodies.append(body)
    return summary


def approved_plan_issues(repo: str, run: Callable[..., str] | None = None) -> list[dict]:
    run = run or deep_scan._default_run
    out = run("issue", "list", "-R", repo, "--label", APPROVED_LABEL, "--state", "open",
              "--limit", "100", "--json", "number,title,body,url")
    return json.loads(out) if out else []


def enqueue_approved(repo: str, cfg: dict | None, run: Callable[..., str] | None = None) -> dict:
    """For each approved plan issue, create one ordinary task issue (idempotent by marker)."""
    run = run or deep_scan._default_run
    labels = (cfg or {}).get("labels")
    task_label = labels.get("task", "ai-task") if isinstance(labels, dict) else "ai-task"
    summary: dict = {"enqueued": 0, "skipped": 0, "errors": [], "urls": []}
    try:
        approved = approved_plan_issues(repo, run=run)
        if not approved:
            return summary
        task_bodies = deep_scan.fetch_issue_bodies(repo, task_label, run=run)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(redact_secrets(f"อ่านแผนที่อนุมัติไม่สำเร็จ: {exc}"))
        return summary
    for issue in approved:
        number = issue.get("number")
        marker = f"<!-- plan-issue:{number} -->"
        if any(marker in (b or "") for b in task_bodies):
            summary["skipped"] += 1
            continue
        title = re.sub(r"^\[plan\]\s*", "", issue.get("title") or "").strip() or f"plan #{number}"
        body = redact_secrets(
            f"{marker}\n\nแผนที่อนุมัติแล้ว: {issue.get('url', '')} (#{number})\n\n{issue.get('body') or ''}\n")
        try:
            url = run("issue", "create", "-R", repo, "--title", redact_secrets(f"[feature] {title[:100]}"),
                      "--body", body, "--label", task_label).strip()
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(redact_secrets(f"#{number}: สร้าง issue งานไม่สำเร็จ: {exc}"))
            continue
        summary["enqueued"] += 1
        summary["urls"].append(url)
        task_bodies.append(body)
        try:
            run("issue", "comment", str(number), "-R", repo, "--body",
                f"🤖 สร้าง issue งาน {url} แล้ว ระบบจะเริ่มสร้างฟีเจอร์ตามแผนนี้")
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(redact_secrets(f"#{number}: คอมเมนต์ไม่สำเร็จ: {exc}"))
    return summary


PLAN_MARKER_RE = re.compile(r"<!-- plan-issue:(\d+) -->")


def close_done_plans(repo: str, cfg: dict | None, run: Callable[..., str] | None = None) -> dict:
    """Close an approved plan once the task issue made from it (marker `plan-issue:N`) is closed.
    A closed task means the feature is done, so the plan issue must not stay open. Idempotent: a closed
    plan is no longer listed as approved, so it is never processed twice."""
    run = run or deep_scan._default_run
    labels = (cfg or {}).get("labels")
    task_label = labels.get("task", "ai-task") if isinstance(labels, dict) else "ai-task"
    summary: dict = {"closed": 0, "errors": []}
    try:
        approved = approved_plan_issues(repo, run=run)
        if not approved:
            return summary
        out = run("issue", "list", "-R", repo, "--label", task_label, "--state", "all",
                  "--limit", "1000", "--json", "number,state,body,url")
        tasks = json.loads(out) if out else []
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(redact_secrets(f"อ่านงานที่สร้างจากแผนไม่สำเร็จ: {exc}"))
        return summary
    done_task_url: dict[int, str] = {}
    for t in tasks:
        m = PLAN_MARKER_RE.search(t.get("body") or "")
        if m and str(t.get("state", "")).upper() == "CLOSED":
            done_task_url[int(m.group(1))] = t.get("url") or ""
    for issue in approved:
        number = issue.get("number")
        if number not in done_task_url:
            continue
        task_url = done_task_url[number]
        note = f" ({task_url})" if task_url else ""
        try:
            run("issue", "close", str(number), "-R", repo, "--comment",
                redact_secrets(f"✅ งานที่สร้างจากแผนนี้{note} ถูกปิดแล้ว ระบบจึงปิดแผนนี้ให้อัตโนมัติ"))
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(redact_secrets(f"#{number}: ปิดแผนไม่สำเร็จ: {exc}"))
            continue
        summary["closed"] += 1
    return summary


SCHEDULE_NAME = "approvals_schedule.json"


def maybe_process_approvals(cfg: dict | None, state_dir: Path, now: float | None = None,
                            min_interval_s: float = 600, run: Callable[..., str] | None = None) -> list[dict]:
    """Throttled: check approved plans in every enabled repo at most once per interval."""
    now = time.time() if now is None else now
    path = Path(state_dir) / "feature_gen" / SCHEDULE_NAME
    last = (locked_json_read(path, default={}) or {}).get("last", 0)
    if now - float(last) < min_interval_s:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    locked_json_write(path, {"last": now, "at": dt.datetime.fromtimestamp(now).isoformat(timespec="seconds")})
    out: list[dict] = []
    for r in (cfg or {}).get("repos") or []:
        if not isinstance(r, dict) or not r.get("name") or r.get("enabled", True) is False:
            continue
        try:
            res = enqueue_approved(r["name"], cfg, run=run)
            closed = close_done_plans(r["name"], cfg, run=run)
            out.append({"repo": r["name"], **res, "closed": closed["closed"],
                        "errors": res["errors"] + closed["errors"]})
        except Exception as exc:  # noqa: BLE001
            out.append({"repo": r["name"], "errors": [redact_secrets(str(exc))]})
    return out

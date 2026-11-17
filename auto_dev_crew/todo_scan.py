"""สแกนแท็ก [AI-TODO] ในโค้ดแล้วแปลงเป็น issue ติดป้าย ai-task (ไม่สแกน TODO/FIXME ทั่วไป กัน issue ท่วม)."""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .redact import redact_secrets

TAG = "[AI-TODO]"
MAX_FILE_BYTES = 1024 * 1024
CONTEXT_LINES = 3
TITLE_TEXT_MAX = 80
DEFAULT_LIMIT = 5
CONTEXT_LINE_MAX = 300
_TAG_RE = re.compile(r"(?:#|//|/\*|\*|<!--|--)\s*" + re.escape(TAG))


@dataclass
class TodoItem:
    path: str      # POSIX-style, relative to scan root
    line: int      # 1-based
    text: str      # text after the tag
    context: str   # +-3 lines around the tag
    marker: str    # dedupe marker for the issue body (no line number)

    def to_dict(self) -> dict:
        return asdict(self)


def _skip_dir(name: str) -> bool:
    return name == ".git" or name == "node_modules" or name.startswith(".venv") or name.startswith("_slot_")


def _marker(path: str, text: str) -> str:
    # ใช้เพียงแยกเครื่องหมายซ้ำ ไม่ใช่งานด้านความปลอดภัย
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"<!-- ai-todo:{path}:{digest} -->"


def scan_todos(root: Path) -> list[TodoItem]:
    root = Path(root)
    items: list[TodoItem] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        for name in sorted(filenames):
            fpath = Path(dirpath) / name
            try:
                if fpath.is_symlink() or fpath.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = fpath.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192] or TAG.encode() not in data:
                continue
            rel = fpath.relative_to(root).as_posix()
            lines = data.decode("utf-8", errors="replace").splitlines()
            for idx, line in enumerate(lines):
                m = _TAG_RE.search(line)
                if not m:
                    continue
                text = line[m.end():].strip()
                if not text:
                    continue
                lo, hi = max(0, idx - CONTEXT_LINES), min(len(lines), idx + CONTEXT_LINES + 1)
                ctx = "\n".join(c[:CONTEXT_LINE_MAX] for c in lines[lo:hi])
                items.append(TodoItem(rel, idx + 1, text, ctx, _marker(rel, text)))
    return items


def _default_run(*args: str) -> str:
    from . import runner
    return runner.gh(*args)


def fetch_existing_bodies(repo: str, run: Callable[..., str] | None = None,
                          label: str = "ai-task") -> list[str]:
    # ไม่ใช้ --search (eventually consistent): ดึงทุก issue ที่มี label แล้วเทียบ marker ตรง ๆ
    run = run or _default_run
    out = run("issue", "list", "-R", repo, "--state", "all", "--label", label,
              "--limit", "1000", "--json", "body")
    return [r.get("body") or "" for r in (json.loads(out) if out else [])]


def _issue_body(item: TodoItem) -> str:
    fence = "```"
    while fence in item.context:
        fence += "`"
    return (f"{item.marker}\n\n`{item.path}:{item.line}`\n\n{TAG} {item.text}\n\n"
            f"{fence}\n{item.context}\n{fence}\n")


_MARKER_RE = re.compile(r"<!-- ai-todo:(.+):[0-9a-f]{8} -->")


def parse_todo_issue(body: str) -> tuple[str, str] | None:
    """(path, text) of a body made by `_issue_body`, or None if it is not a TODO issue."""
    m = _MARKER_RE.search(body or "")
    if not m:
        return None
    prefix = TAG + " "
    for line in body.splitlines():
        if line.startswith(prefix):
            return m.group(1), line[len(prefix):].strip()
    return None


def todo_remediation_prompt(path: str, text: str) -> str:
    return (
        "## AI-TODO REMEDIATION\n"
        f"- This issue comes from a `{TAG}` comment in `{path}`: {text}\n"
        "- Implement what the TODO asks for.\n"
        f"- Then delete the whole `{TAG}` comment line (not just the tag) from `{path}`.\n\n"
    )


def todo_still_present(cwd: Path, path: str, text: str) -> bool:
    root = Path(cwd).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return False
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        m = _TAG_RE.search(line)
        if m and line[m.end():].strip() == text.strip():
            return True
    return False


def create_todo_issues(repo: str, items: list[TodoItem], existing_bodies: list[str],
                       limit: int = DEFAULT_LIMIT, run: Callable[..., str] | None = None,
                       label: str = "ai-task", errors: list[str] | None = None) -> list[str]:
    """Returns created issue URLs. A failing create is recorded in `errors` (if given) and skipped."""
    run = run or _default_run
    seen = "\n".join(existing_bodies)
    batch: set[str] = set()
    urls: list[str] = []
    for item in items:
        if len(urls) >= limit:
            break
        if item.marker in seen or item.marker in batch:
            continue
        batch.add(item.marker)
        title = redact_secrets(f"{TAG} {item.path}:{item.line} {item.text[:TITLE_TEXT_MAX]}")
        try:
            url = run("issue", "create", "-R", repo, "--title", title,
                      "--body", redact_secrets(_issue_body(item)), "--label", label)
        except Exception as exc:  # keep URLs of issues already created
            if errors is not None:
                errors.append(redact_secrets(f"{item.path}:{item.line}: {exc}"))
            continue
        urls.append(url.strip())
    return urls


def run_scan(repo: str, cfg: dict, create: bool = False) -> dict:
    """Scan repo's cache clone; with create=True also open issues (dedup vs existing)."""
    from . import multi_repo
    root = multi_repo.find_or_prepare_repo_dir(repo, cfg)
    warnings: list[str] = []
    try:  # best-effort: the cache clone is shallow and may be stale
        res = subprocess.run(["git", "pull", "--ff-only"], cwd=str(root), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if res.returncode != 0:
            warnings.append(redact_secrets(_i18n.t("git pull ล้มเหลว (สแกนจากข้อมูลเดิม): {p0}", p0=(res.stderr or res.stdout).strip()[:300])))
    except Exception as exc:
        warnings.append(redact_secrets(_i18n.t("git pull ล้มเหลว (สแกนจากข้อมูลเดิม): {p0}", p0=exc)))
    items = scan_todos(root)
    result: dict = {"ok": True, "repo": repo, "items": [i.to_dict() for i in items], "warnings": warnings}
    if create:
        limit = int((cfg.get("todo_scan") or {}).get("max_issues_per_run", DEFAULT_LIMIT))
        label = (cfg.get("labels") or {}).get("task", "ai-task")
        bodies = fetch_existing_bodies(repo, label=label)
        errors: list[str] = []
        result["created"] = create_todo_issues(repo, items, bodies, limit=limit, label=label, errors=errors)
        result["errors"] = errors
    return result


def maybe_run_scheduled(cfg: dict, state_path: Path, now: float | None = None,
                        scan: Callable[[str, dict], dict] | None = None) -> list[dict]:
    """Opt-in periodic scan: run `scan` for each repo whose last run is >= schedule_minutes ago.

    schedule_minutes missing or <= 0 disables it (returns [] and touches nothing). The run time is
    recorded before scanning so a failing repo is not retried on every loop.
    """
    tcfg = cfg.get("todo_scan") or {}
    try:
        minutes = float(tcfg.get("schedule_minutes") or 0)
    except (TypeError, ValueError):
        return []
    if minutes <= 0:
        return []
    now = time.time() if now is None else now
    repos = tcfg.get("repos") or [r["name"] for r in cfg.get("repos", []) if r.get("enabled", True)]
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    scan = scan or (lambda r, c: run_scan(r, c, create=True))
    results: list[dict] = []
    for repo in repos:
        try:
            last = float(state.get(repo, 0))
        except (TypeError, ValueError):
            last = 0.0
        if now - last < minutes * 60:
            continue
        state[repo] = now
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(state), encoding="utf-8")
        try:
            results.append(scan(repo, cfg))
        except Exception as exc:
            results.append({"ok": False, "repo": repo, "error": redact_secrets(str(exc))})
    return results

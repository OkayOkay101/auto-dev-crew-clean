"""Deep scan: validate and clean findings returned by a model."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .locks import file_lock, locked_json_read, locked_json_write
from .redact import redact_secrets

CATEGORIES = frozenset({"bug", "security", "missing-test", "quality"})
MAX_FILE_BYTES = 1024 * 1024
MAX_LINES_PER_FILE = 4000
ROOT_CHUNK = "(root)"
SEVERITIES = ("high", "medium", "low")
DEFAULT_SEVERITY = "low"


@dataclass
class Finding:
    category: str
    title: str
    path: str
    line: int
    evidence: str
    suggested_fix: str
    severity: str = DEFAULT_SEVERITY

    def to_dict(self) -> dict:
        return asdict(self)


def parse_model_output(raw: str) -> list[dict]:
    """Extract a JSON array from model text (fences / leading prose allowed)."""
    if not isinstance(raw, str):
        return []
    # ลองทุก "[" ตามลำดับ แล้วใช้ array แรกที่ parse ได้และมี object อยู่ข้างใน
    # (วงเล็บในข้อความ เช่น "[1]" จะไม่ทำให้อ่าน JSON จริงไม่ได้)
    decoder = json.JSONDecoder()
    for start, ch in enumerate(raw):
        if ch != "[":
            continue
        try:
            data, _ = decoder.raw_decode(raw, start)
        except ValueError:
            continue
        if isinstance(data, list) and any(isinstance(x, dict) for x in data):
            return [x for x in data if isinstance(x, dict)]
    return []


def _parse_model_array(raw) -> list[dict] | None:
    """None = no usable JSON array in the reply (bad output). [] = the model really returned an empty array."""
    if not isinstance(raw, str):
        return None
    decoder = json.JSONDecoder()
    for start, ch in enumerate(raw):
        if ch != "[":
            continue
        try:
            data, _ = decoder.raw_decode(raw, start)
        except ValueError:
            continue
        if isinstance(data, list) and all(isinstance(x, dict) for x in data):
            return list(data)
    return None


RETRY_NOTE = "\nReturn ONLY a JSON array, no other text. ตอบ JSON เท่านั้น ห้ามมีข้อความอื่น\n"


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _clean_severity(value) -> str:
    sev = value.strip().lower() if isinstance(value, str) else ""
    return sev if sev in SEVERITIES else DEFAULT_SEVERITY


def _resolve_line(claimed, evidence: str, file_lines: list[str]) -> int | None:
    """Keep the claimed line when it is inside the file. Otherwise find the line whose text holds the
    evidence (nearest to the claimed number). None when the evidence is not in the file at all."""
    total = len(file_lines)
    is_int = isinstance(claimed, int) and not isinstance(claimed, bool)
    if is_int and 1 <= claimed <= total:
        return claimed
    needle = " ".join(evidence.split())
    if not needle:
        return None
    hits = [n for n, text in enumerate(file_lines, 1) if needle in " ".join(text.split())]
    if not hits:
        return None
    return min(hits, key=lambda n: abs(n - claimed)) if is_int else hits[0]


def validate_findings(raw_items: list[dict], repo_root: Path) -> list[Finding]:
    root = Path(repo_root).resolve()
    out: list[Finding] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        if category not in CATEGORIES:
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not rel.strip():
            continue
        rel_path = Path(rel)
        if rel_path.is_absolute() or rel_path.drive or ".." in rel_path.parts:
            continue
        try:
            target = (root / rel_path).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                continue
            file_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        line = _resolve_line(item.get("line"), evidence, file_lines)
        if line is None:  # เลขบรรทัดผิดและหา evidence ในไฟล์ไม่เจอ → โมเดลแต่งขึ้นมา
            continue
        out.append(Finding(
            category=category,
            title=str(item.get("title") or "").strip(),
            path=rel_path.as_posix(),
            line=line,
            evidence=evidence,
            suggested_fix=str(item.get("suggested_fix") or ""),
            severity=_clean_severity(item.get("severity")),
        ))
    return out


def _skip_dir(name: str) -> bool:
    return name == ".git" or name == "node_modules" or name.startswith(".venv") or name.startswith("_slot_")


def chunk_by_top_folder(root: Path) -> list[tuple[str, list[str]]]:
    """Group source files by top-level folder; root-level files go to "(root)"."""
    root = Path(root)
    groups: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        for name in sorted(filenames):
            fpath = Path(dirpath) / name
            try:
                if fpath.is_symlink() or fpath.stat().st_size > MAX_FILE_BYTES:
                    continue
                with fpath.open("rb") as fh:
                    if b"\x00" in fh.read(8192):
                        continue
            except OSError:
                continue
            rel = fpath.relative_to(root)
            key = rel.parts[0] if len(rel.parts) > 1 else ROOT_CHUNK
            groups.setdefault(key, []).append(rel.as_posix())
    return sorted(groups.items())


def build_scan_prompt(chunk_name: str, files: list[str], root: Path, max_findings: int) -> str:
    root = Path(root)
    parts = [
        "Return ONLY a JSON array, no other text. คืนค่าเป็น JSON array เท่านั้น ห้ามมีข้อความอื่น\n"
        f"Review the source files in group '{chunk_name}' for real bugs, security issues, "
        "missing tests and quality problems. ตรวจโค้ดกลุ่มนี้หาบั๊ก ช่องโหว่ ส่วนที่ขาดเทสต์ และปัญหาคุณภาพ\n"
        f"max_findings: {max_findings} (return at most {max_findings} items; an empty array [] is fine).\n"
        "Each item is an object with fields: category (one of bug, security, missing-test, quality), "
        "title, path (relative path exactly as shown), line (1-based line number that exists in the file), "
        "evidence (quote the actual code at that line), suggested_fix, "
        "severity (one of high, medium, low).\n"
        "Severity meaning: high = bug or security issue that breaks behaviour; "
        "medium = likely problem or real test gap; low = quality or style.\n"
        "Do not invent findings; every item must cite real lines. อ้างบรรทัดจริงเท่านั้น\n"
        'Each file line is prefixed with "N: " for reference only. `line` must be that N. '
        '`evidence` must be the code text alone, with no "N:" prefix.\n'
    ]
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            parts.append(f"\n=== FILE: {rel} ===\n[skipped: unreadable]\n")
            continue
        all_lines = text.splitlines()
        lines = all_lines[:MAX_LINES_PER_FILE]
        numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines, 1))
        section = f"\n=== FILE: {rel} ===\n{redact_secrets(numbered)}\n"
        extra = len(all_lines) - len(lines)
        if extra > 0:
            section += f"[truncated: {extra} more lines not shown]\n"
        parts.append(section)
    return "".join(parts)


TITLE_MAX = 80


def finding_marker(f: Finding) -> str:
    # ไม่ใส่เลขบรรทัด เพื่อให้ marker คงเดิมเมื่อโค้ดขยับ; sha1 ใช้แยกซ้ำเท่านั้น ไม่ใช่งานด้านความปลอดภัย
    key = f"{f.category}|{f.title}".encode("utf-8")
    digest = hashlib.sha1(key, usedforsecurity=False).hexdigest()[:8]
    return f"<!-- deep-scan:{f.path}:{digest} -->"


def _fence_for(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def render_issue_body(f: Finding, verification: str = "") -> str:
    fence = _fence_for(f.evidence)
    parts = [
        finding_marker(f),
        f"`{f.path}:{f.line}`",
        f"**Category:** {f.category}",
        f"**Severity:** {f.severity}",
        f"**{f.title}**",
        f"{fence}\n{f.evidence}\n{fence}",
        f"**Suggested fix:** {f.suggested_fix}",
    ]
    if verification:  # ด่าน 4: หลักฐานจากการตรวจซ้ำ
        parts.append(f"**Verification (ตรวจซ้ำแล้ว):** {verification}")
    return redact_secrets("\n\n".join(parts) + "\n")


# ---- ด่าน 4 (docs/draft-quality-gates.md): ตรวจซ้ำก่อนสร้าง issue ----------------------------
VERIFY_STATUS = "unverified"


def build_verify_prompt(f: Finding, root: Path) -> str:
    """ให้โมเดลอ่านไฟล์จริงแล้วยืนยันบรรทัดที่อ้าง พร้อมคัดลอกโค้ดจริงเป็นหลักฐาน."""
    root = Path(root)
    try:
        text = (root / f.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(text.splitlines(), 1))
    return (
        "Return ONLY a JSON object, no other text. คืนค่าเป็น JSON object เท่านั้น\n"
        "Verify whether this finding is real by reading the file below. "
        "ตรวจว่าปัญหานี้มีจริงในโค้ดบรรทัดที่อ้างหรือไม่\n"
        'Format: {"confirmed": true or false, "evidence": "<copy the exact code text of line '
        f'{f.line} verbatim, then explain briefly in Thai why it is a real {f.category}>"}}\n'
        "Set confirmed=false if the line does not show the problem or the problem is already handled.\n"
        f"Finding: [{f.severity}] {f.title}\nClaimed line {f.line} in {f.path}\n"
        f"Claimed evidence: {f.evidence}\n\n"
        f"=== FILE: {f.path} ===\n{redact_secrets(numbered)}\n"
    )


def parse_verify_output(raw: str, f: Finding, root: Path) -> tuple[bool, str]:
    """True + หลักฐาน เมื่อโมเดลยืนยัน และคัดลอกบรรทัดจริงมาอ้างได้; อื่น ๆ = False."""
    if not isinstance(raw, str):
        return False, ""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return False, ""
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return False, ""
    if not isinstance(data, dict) or data.get("confirmed") is not True:
        return False, ""
    evidence = data.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        return False, ""
    try:
        lines = (Path(root) / f.path).read_text(encoding="utf-8", errors="replace").splitlines()
        actual = lines[f.line - 1].strip() if 1 <= f.line <= len(lines) else ""
    except OSError:
        return False, ""
    # หลักฐานต้องมีโค้ดจริงของบรรทัดนั้น ไม่ใช่คำอธิบายลอย ๆ
    if not actual or actual not in evidence:
        return False, ""
    return True, evidence.strip()


def verify_finding(f: Finding, root: Path, call_model: Callable[[str], str]) -> tuple[bool, str]:
    """ด่าน 4: ให้โมเดลตรวจซ้ำ. ล้มเหลว/อ่านไม่ได้ = ไม่ยืนยัน (ไม่สร้าง issue โดยไม่มีหลักฐาน)."""
    try:
        raw = call_model(build_verify_prompt(f, root))
    except Exception:  # noqa: BLE001 — ผู้เรียกจะบันทึกเป็น unverified
        return False, ""
    return parse_verify_output(raw, f, root)



def _default_run(*args: str) -> str:
    from . import runner
    return runner.gh(*args)


def fetch_open_bodies(repo: str, label: str, run: Callable[..., str] | None = None) -> list[str]:
    run = run or _default_run
    out = run("issue", "list", "-R", repo, "--state", "open", "--label", label,
              "--limit", "1000", "--json", "body")
    return [r.get("body") or "" for r in (json.loads(out) if out else [])]


def fetch_issue_bodies(repo: str, label: str, run: Callable[..., str] | None = None,
                       state: str = "all") -> list[str]:
    """Bodies of issues (open AND closed by default) so a closed finding is not re-filed."""
    run = run or _default_run
    out = run("issue", "list", "-R", repo, "--state", state, "--label", label,
              "--limit", "1000", "--json", "body")
    return [r.get("body") or "" for r in (json.loads(out) if out else [])]


def create_finding_issue(repo: str, f: Finding, existing_bodies: list[str],
                         label: str = "ai-task",
                         run: Callable[..., str] | None = None,
                         verification: str = "") -> str | None:
    """Create an issue for `f`; None when its marker is already in an open issue."""
    marker = finding_marker(f)
    if any(marker in (b or "") for b in existing_bodies):
        return None
    run = run or _default_run
    title = redact_secrets(f"[deep-scan] {f.title[:TITLE_MAX]}")
    url = run("issue", "create", "-R", repo, "--title", title,
              "--body", render_issue_body(f, verification), "--label", label)
    return url.strip()


STATUSES = frozenset({"new", "filed", "dismissed", "unverified"})


def state_path(state_dir: Path, repo: str) -> Path:
    # M10: กัน collision ระหว่าง "a__b/c" กับ "a/b__c" หลังแทน "/" เป็น "__"
    if "__" in repo:
        raise ValueError(f"repo name must not contain '__': {repo!r}")
    return Path(state_dir) / "deep_scan" / f"{repo.replace('/', '__')}.json"


_FINDING_FIELDS = ("category", "title", "path", "line", "evidence", "suggested_fix")


def _lock_path(path: Path) -> Path:
    return path.parent / f"{path.name}.lock"


def save_run(state_dir: Path, repo: str, findings: list[Finding], run_id: str,
             warnings: list[str] | None = None) -> dict:
    """Write one run's findings (secrets redacted); dismissed/filed status carries over by marker."""
    path = state_path(state_dir, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = []
    with file_lock(_lock_path(path)):
        previous = locked_json_read(path, default=None) or {}
        carried = {}
        for old in previous.get("findings", []):
            if old.get("status") in ("dismissed", "filed"):
                try:
                    carried[finding_marker(Finding(**{k: old[k] for k in _FINDING_FIELDS}))] = old["status"]
                except (KeyError, TypeError):
                    continue
        for i, f in enumerate(findings):
            item = {k: (redact_secrets(v) if isinstance(v, str) else v)
                    for k, v in f.to_dict().items()}
            item["id"] = f"{run_id}-{i}"
            marker = finding_marker(Finding(**{k: item[k] for k in _FINDING_FIELDS}))
            item["status"] = carried.get(marker, "new")
            items.append(item)
        data = {"repo": repo, "run_id": run_id, "findings": items}
        if warnings:  # e.g. a group that gave malformed output twice
            data["warnings"] = list(warnings)
        locked_json_write(path, data)
    return data


def load_run(state_dir: Path, repo: str) -> dict | None:
    return locked_json_read(state_path(state_dir, repo), default=None)


def set_status(state_dir: Path, repo: str, finding_id: str, status: str,
               issue_url: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    path = state_path(state_dir, repo)
    with file_lock(_lock_path(path)):
        data = locked_json_read(path, default=None)
        if not data:
            raise KeyError(finding_id)
        for item in data.get("findings", []):
            if item.get("id") == finding_id:
                item["status"] = status
                if issue_url:
                    item["issue_url"] = issue_url
                locked_json_write(path, data)
                return
    raise KeyError(finding_id)


# ---- issue status of filed findings (the GitHub issue is the source of truth, not the saved run)

ISSUE_INDEX_TTL = 30.0  # seconds; keeps repeated GUI refreshes from calling gh every time
STUCK_LABELS = frozenset({"ai-failed", "ai-needs-human"})
_index_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}


def fetch_issue_index(repo: str, label: str, run: Callable[..., str] | None = None) -> list[dict]:
    """Every issue with `label` (open and closed) with the fields needed to tell whether a finding is done."""
    run = run or _default_run
    out = run("issue", "list", "-R", repo, "--state", "all", "--label", label, "--limit", "1000",
              "--json", "number,state,body,url,labels")
    return json.loads(out) if out else []


def cached_issue_index(repo: str, label: str, run: Callable[..., str] | None = None) -> list[dict]:
    import time
    key = (repo, label)
    hit = _index_cache.get(key)
    if hit and time.monotonic() - hit[0] < ISSUE_INDEX_TTL:
        return hit[1]
    index = fetch_issue_index(repo, label, run=run)
    _index_cache[key] = (time.monotonic(), index)
    return index


def forget_issue_index(repo: str, label: str) -> None:
    _index_cache.pop((repo, label), None)


def finding_issue_state(issue: dict | None) -> str:
    """open = issue still being worked; stuck = issue waits for a human; closed = issue done; unknown = no issue found."""
    if issue is None:
        return "unknown"
    if str(issue.get("state", "")).upper() == "CLOSED":
        return "closed"
    names = {(lbl or {}).get("name") for lbl in issue.get("labels") or []}
    return "stuck" if names & STUCK_LABELS else "open"


def _finding_of(item: dict) -> Finding | None:
    try:
        return Finding(**{k: item[k] for k in _FINDING_FIELDS}, severity=item.get("severity", DEFAULT_SEVERITY))
    except (KeyError, TypeError):
        return None


def with_issue_state(data: dict, index: list[dict]) -> dict:
    """Attach issue_state (and the issue link) to every filed finding, matched by its marker in the issue body."""
    for item in (data or {}).get("findings", []):
        if item.get("status") != "filed":
            continue
        finding = _finding_of(item)
        marker = finding_marker(finding) if finding else None
        issue = next((i for i in index if marker and marker in (i.get("body") or "")), None)
        item["issue_state"] = finding_issue_state(issue)
        if issue:
            item["issue_url"] = issue.get("url") or item.get("issue_url")
            item["issue_number"] = issue.get("number")
    return data


DEFAULT_MAX_FINDINGS = 15
DEFAULT_MAX_CALLS = 300  # เพดาน call โมเดลต่อหนึ่งการสแกน (สแกนกลุ่ม + ตรวจซ้ำ)
SCAN_MODES = ("agentic", "inline")


class BudgetExhausted(RuntimeError):
    """Raised when one run has used up its model-call budget (deep_scan.max_calls_per_run)."""


class CallBudget:
    """Counts model calls for one run. `wrap` returns a call_model that refuses once the limit is reached."""

    def __init__(self, limit: int):
        self.limit = max(int(limit), 0)
        self.used = 0

    def wrap(self, call_model: Callable[[str], str]) -> Callable[[str], str]:
        def guarded(prompt: str) -> str:
            if self.used >= self.limit:
                raise BudgetExhausted(f"ถึงเพดาน {self.limit} call ต่อรันแล้ว")
            self.used += 1
            return call_model(prompt)
        return guarded


def call_budget_limit(cfg: dict | None) -> int:
    raw = ((cfg or {}).get("deep_scan") or {}).get("max_calls_per_run", DEFAULT_MAX_CALLS)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return DEFAULT_MAX_CALLS


def scan_mode(cfg: dict | None) -> str:
    """`agentic` (default): the agent reads the repo itself. `inline`: the file text is pasted into the prompt."""
    mode = ((cfg or {}).get("deep_scan") or {}).get("mode")
    return mode if mode in SCAN_MODES else "agentic"


def build_agentic_scan_prompt(chunk_name: str, files: list[str], max_findings: int) -> str:
    """Agentic scan: the agent opens the files with its own tools and follows calls into other files."""
    listing = "\n".join(f"- {rel}" for rel in files)
    return (
        "Return ONLY a JSON array, no other text. คืนค่าเป็น JSON array เท่านั้น ห้ามมีข้อความอื่น\n"
        f"You are auditing the folder group '{chunk_name}' of the repository in your working directory. "
        "ตรวจกลุ่มนี้ของ repo ที่อยู่ใน working directory\n"
        "Work in steps: (1) open every file listed below with your read tool; (2) for each suspicion, open the "
        "other files that the code imports or calls and confirm the behaviour there; (3) report only what you "
        "confirmed. Use glob or grep to find definitions. Do not edit files and do not run commands.\n"
        f"max_findings: {max_findings} (return at most {max_findings} items; an empty array [] is fine).\n"
        "Each item is an object with fields: category (one of bug, security, missing-test, quality), "
        "title, path (relative path from the repo root), line (1-based line number as the read tool shows it), "
        "evidence (the exact code text of that line, without the line-number prefix), suggested_fix, "
        "severity (one of high, medium, low).\n"
        "Severity meaning: high = bug or security issue that breaks behaviour; medium = likely problem or real "
        "test gap; low = quality or style.\n"
        "Do not invent findings; every item must cite lines you actually read.\n"
        "Files in this group:\n"
        f"{listing}\n"
    )


def run_deep_scan(repo: str, cfg: dict, state_dir: Path, call_model: Callable[[str], str],
                  run_id: str | None = None) -> dict:
    """Scan repo's cache clone chunk by chunk with `call_model`; save capped, validated findings."""
    from . import multi_repo
    run_id = run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        cap = int((cfg.get("deep_scan") or {}).get("max_findings_per_run", DEFAULT_MAX_FINDINGS))
    except (TypeError, ValueError):
        cap = DEFAULT_MAX_FINDINGS
    cap = max(cap, 0)
    root = Path(multi_repo.find_or_prepare_repo_dir(repo, cfg))
    warnings: list[str] = []
    try:  # best-effort: the cache clone is shallow and may be stale
        res = subprocess.run(["git", "pull", "--ff-only"], cwd=str(root), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if res.returncode != 0:
            warnings.append(redact_secrets(f"git pull ล้มเหลว (สแกนจากข้อมูลเดิม): {(res.stderr or res.stdout).strip()[:300]}"))
    except Exception as exc:
        warnings.append(redact_secrets(f"git pull ล้มเหลว (สแกนจากข้อมูลเดิม): {exc}"))
    findings: list[Finding] = []
    agentic = scan_mode(cfg) == "agentic"
    for name, files in chunk_by_top_folder(root):
        try:
            prompt = (build_agentic_scan_prompt(name, files, cap) if agentic
                      else build_scan_prompt(name, files, root, cap))
            items = _parse_model_array(call_model(prompt))
            if items is None:  # ผิดรูปแบบ (ไม่ใช่ [] ที่ตั้งใจ) → ลองซ้ำ 1 ครั้งด้วยพรอมพ์เดิม + คำสั่ง JSON
                items = _parse_model_array(call_model(prompt + RETRY_NOTE))
            if items is None:
                warnings.append(f"กลุ่ม {name} ตอบผิดรูปแบบ (ไม่พบ JSON) แม้ลองซ้ำแล้ว ผลกลุ่มนี้ไม่ถูกนับ")
                continue
            findings.extend(validate_findings(items, root))
        except BudgetExhausted as exc:
            warnings.append(redact_secrets(f"หยุดสแกนที่กลุ่ม {name}: {exc} (กลุ่มที่เหลือยังไม่ได้สแกน)"))
            break
        except Exception as exc:
            warnings.append(redact_secrets(f"สแกนกลุ่ม {name} ล้มเหลว: {exc}"))
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: rank.get(f.severity, len(SEVERITIES)))  # stable: chunk order kept per rank
    dropped = max(len(findings) - cap, 0)
    findings = findings[:cap]
    if dropped:  # M11 ruling: scan every chunk (R9), but say when the cap hid findings
        warnings.append(f"พบ {dropped} รายการเกินเพดาน {cap} จึงไม่ได้บันทึก (เรียงตามความรุนแรงแล้ว)")
    data = save_run(state_dir, repo, findings, run_id, warnings=warnings)
    return {"ok": True, "repo": repo, "run_id": run_id, "findings": data["findings"], "warnings": warnings}


AUTO_TRIGGERS = frozenset({"after_scan", "manual"})


def auto_issue_settings(cfg: dict | None) -> dict:
    """Read `auto_issue` from config; any bad value falls back to the safe default (off)."""
    raw = (cfg or {}).get("auto_issue")
    if not isinstance(raw, dict):
        raw = {}
    trigger = raw.get("trigger")
    min_sev = raw.get("min_severity")
    return {
        "enabled": raw.get("enabled") is True,
        "trigger": trigger if trigger in AUTO_TRIGGERS else "after_scan",
        "min_severity": min_sev if min_sev in SEVERITIES else DEFAULT_SEVERITY,
    }


def _severity_passes(severity: str, min_sev: str) -> bool:
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    return rank.get(severity, len(SEVERITIES)) <= rank[min_sev]


def file_findings_automatically(repo: str, cfg: dict | None, state_dir: Path, items: list[dict],
                                label: str = "ai-task", run: Callable[..., str] | None = None,
                                verify: Callable[[Finding], tuple[bool, str]] | None = None) -> dict:
    """Create issues for saved `new` findings at or above min_severity (only when enabled, trigger=after_scan).

    `verify` (ด่าน 4) re-checks each finding against the file; a finding it does not confirm with quoted
    evidence is marked `unverified` and gets no issue. A finding whose issue fails is kept as `new`
    and the error is recorded; the rest still run.
    """
    settings = auto_issue_settings(cfg)
    summary: dict = {"ran": False, "created": 0, "skipped": 0, "unverified": 0, "errors": []}
    if not settings["enabled"] or settings["trigger"] != "after_scan":
        return summary
    summary["ran"] = True
    pending = [it for it in items
               if it.get("status") == "new"
               and _severity_passes(it.get("severity", DEFAULT_SEVERITY), settings["min_severity"])]
    if not pending:
        return summary
    try:
        bodies = fetch_issue_bodies(repo, label, run=run)
    except Exception as exc:
        summary["errors"].append(redact_secrets(f"อ่าน issue เดิมไม่สำเร็จ: {exc}"))
        return summary
    for it in pending:
        try:
            finding = Finding(**{k: it[k] for k in _FINDING_FIELDS}, severity=it.get("severity", DEFAULT_SEVERITY))
        except (KeyError, TypeError) as exc:
            summary["errors"].append(redact_secrets(f"{it.get('id')}: ข้อมูล finding ไม่ครบ: {exc}"))
            continue
        verification = ""
        if verify is not None:
            confirmed, verification = verify(finding)
            if not confirmed:  # ด่าน 4: ไม่มีหลักฐานจากการตรวจซ้ำ → ไม่สร้าง issue
                summary["unverified"] += 1
                try:
                    set_status(state_dir, repo, it["id"], VERIFY_STATUS)
                except Exception as exc:
                    summary["errors"].append(redact_secrets(f"{it.get('id')}: บันทึกสถานะไม่สำเร็จ: {exc}"))
                continue
        try:
            url = create_finding_issue(repo, finding, bodies, label=label, run=run, verification=verification)
        except Exception as exc:
            summary["errors"].append(redact_secrets(f"{it.get('id')}: สร้าง issue ไม่สำเร็จ: {exc}"))
            continue
        if url is None:
            summary["skipped"] += 1
        else:
            summary["created"] += 1
            bodies.append(render_issue_body(finding, verification))
            forget_issue_index(repo, label)
        try:
            set_status(state_dir, repo, it["id"], "filed", issue_url=url)
        except Exception as exc:
            summary["errors"].append(redact_secrets(f"{it.get('id')}: บันทึกสถานะไม่สำเร็จ: {exc}"))
    return summary

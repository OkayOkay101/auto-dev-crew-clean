"""GitHub Multi-Repo Support & Cross-Repo Dispatching."""

from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import dataclasses
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
import yaml

from .ast_skeleton import extract_ast_skeleton
from .stack_detector import detect_stack
from .locks import atomic_write_text, cfg_file_lock
from .procs import run_tree
from .data_home import DATA_HOME
from .redact import redact_gh_args

# Only the explicit ``Target-Repo: owner/name`` body line is a cross-repo directive.
TARGET_REPO_PATTERN = re.compile(
    r"(?:^|\n)\s*Target-Repo:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
TITLE_REPO_PATTERN = re.compile(
    r"^\s*\[([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\]\s*",
    re.IGNORECASE,
)


GH_TIMEOUT_SECONDS = 300
CLONE_TIMEOUT_SECONDS = 900
VERIFY_TIMEOUT_SECONDS = 1800
# Persistent clone cache. Only this directory is ever used for repo work; the user's own
# working copies (cwd, ~/Documents/<name>) are never touched.
REPOS_CACHE_DIR = DATA_HOME / "repos"
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# find_or_prepare_repo_dir ใช้ cache นี้ทั้ง scan และ GUI; ถ้าไม่ fetch จะอ่านโค้ดเก่าได้
# (เคยเจอ cache ค้างที่ 8f9b4bd ทั้งที่ origin/main ไปถึง b1798c3 แล้ว) จึง refresh ก่อนใช้ทุกครั้ง
# แต่จำกัดความถี่เพื่อไม่ให้ทุก request ของ GUI เรียก git fetch
CACHE_REFRESH_SECONDS = 300


def run_cmd(cmd: list[str], timeout: float = GH_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Runs a git/gh command with a timeout; kills the whole process tree on timeout."""
    return run_tree(
        cmd,
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )


def gh(*args: str) -> str:
    args = redact_gh_args(args)
    res = run_cmd(["gh", *args])
    if res.returncode != 0:
        raise RuntimeError(f"gh command failed: gh {' '.join(args)}\n{res.stderr}")
    return res.stdout.strip()


def gh_json(*args: str) -> Any:
    out = gh(*args)
    return json.loads(out) if out else {}


def is_target_repo_allowed(repo_name: str, cfg: dict | None) -> bool:
    """A cross-repo target is allowed when it is a configured repo or belongs to cfg['owner'].

    If cfg has no ``owner`` key, the owners of the configured repos are the allowed owners.
    """
    if not cfg or not repo_name or "/" not in repo_name:
        return False
    owner = repo_name.split("/", 1)[0].lower()
    configured = [r.get("name") for r in cfg.get("repos", []) or [] if isinstance(r, dict)]
    if any(isinstance(n, str) and n.lower() == repo_name.lower() for n in configured):
        return True
    cfg_owner = cfg.get("owner")
    if cfg_owner:
        return owner == str(cfg_owner).lower()
    allowed_owners = {n.split("/", 1)[0].lower() for n in configured if isinstance(n, str) and "/" in n}
    return owner in allowed_owners


def _parse_directive(title: str, body: str, default_repo: str) -> tuple[str, str, str]:
    # 1. Check title bracket syntax: [owner/repo] Title
    tm = TITLE_REPO_PATTERN.match(title)
    if tm:
        target_repo = tm.group(1).strip()
        cleaned_title = TITLE_REPO_PATTERN.sub("", title).strip()
        return target_repo, cleaned_title, body

    # 2. Check body key-value: Target-Repo: owner/repo
    bm = TARGET_REPO_PATTERN.search(body)
    if bm:
        target_repo = bm.group(1).strip()
        # Remove the directive line from body cleanly
        cleaned_body = TARGET_REPO_PATTERN.sub("", body).strip()
        return target_repo, title, cleaned_body

    return default_repo, title, body


def parse_target_repo(
    title: str,
    body: str,
    default_repo: str,
    cfg: dict | None = None,
    on_reject: Callable[[str], None] | None = None,
) -> tuple[str, str, str]:
    """Inspects issue title and body for an explicit target repo override.
    Returns (target_repo, cleaned_title, cleaned_body).

    When ``cfg`` is given, a target that is not allowed (see is_target_repo_allowed) is
    ignored: the default repo is returned with title and body untouched, and on_reject
    receives a message.
    """
    target_repo, cleaned_title, cleaned_body = _parse_directive(title, body, default_repo)
    if cfg is not None and target_repo != default_repo and not is_target_repo_allowed(target_repo, cfg):
        if on_reject:
            on_reject(f"[multi-repo] ละคำสั่ง Target-Repo ไป {target_repo!r} — repo นี้ไม่อยู่ในรายการที่อนุญาต")
        return default_repo, title, body
    return target_repo, cleaned_title, cleaned_body


def get_default_branch(repo_name: str) -> str:
    """Queries GitHub for default branch of repo_name via gh CLI."""
    try:
        data = gh_json("repo", "view", repo_name, "--json", "defaultBranchRef")
        if isinstance(data, dict):
            branch_info = data.get("defaultBranchRef")
            if isinstance(branch_info, dict) and "name" in branch_info:
                return branch_info["name"]
    except Exception:
        pass
    return "main"


def generate_default_repo_config(repo_name: str, base_branch: str | None = None) -> dict:
    """Generates an intelligent stack-aware default configuration for a repo."""
    detected_base = base_branch or get_default_branch(repo_name)

    top_filenames: list[str] = []
    try:
        raw = gh("api", f"repos/{repo_name}/contents", "--jq", ".[].name")
        if raw:
            top_filenames = [line.strip() for line in raw.splitlines() if line.strip()]
    except Exception as exc:
        print(f"[multi_repo] อ่านรายการไฟล์ของ {repo_name} ไม่ได้ ใช้ค่าเริ่มต้น Python: {exc}", file=sys.stderr)

    has_package_json = "package.json" in top_filenames
    has_test_runner_js = "test-runner.js" in top_filenames
    has_requirements = "requirements.txt" in top_filenames
    has_pyproject = "pyproject.toml" in top_filenames
    has_py_files = any(f.endswith(".py") for f in top_filenames)

    if has_package_json or has_test_runner_js or (
        not has_requirements and not has_pyproject and not has_py_files and any(f.endswith(".js") or f.endswith(".html") for f in top_filenames)
    ):
        setup = ["npm install"] if has_package_json else []
        test = ["node test-runner.js"] if has_test_runner_js else (["npm test"] if has_package_json else [])
        scanners = {
            "sentinel": ["npm audit"] if has_package_json else [],
            "quality": test,
        }
    else:
        setup = ["python -m pip install -q -r requirements.txt"] if has_requirements else []
        setup.append("python -m pip install -q pytest")
        # pytest alone: it also collects unittest.TestCase classes, while `unittest discover`
        # finds 0 tests (exit 5) in a pytest-function-only repo and failed every run.
        test = ["python -m pytest -q"]
        scanners = {
            "sentinel": [
                "python -m pip install -q pip-audit bandit",
                "python -m pip_audit" if has_requirements else "python -m bandit -q -r .",
                "python -m bandit -q -r .",
            ],
            "quality": [
                "python -m unittest discover -s tests -p \"test_*.py\"",
            ],
        }

    return {
        "name": repo_name,
        "base": detected_base,
        "setup": setup,
        "test": test,
        "scanners": scanners,
        # ปิดไว้ก่อน: ไม่เปิด PR เพิ่ม workflow ในรีโปของคนอื่นจนกว่าเจ้าของจะเปิดเอง
        "ci": {"auto_bootstrap_ci": False},
    }


def ensure_repo_config(cfg: dict, repo_name: str) -> dict:
    """Finds existing repo config in cfg or generates a sensible default config dynamically."""
    repos = cfg.get("repos", [])
    for r in repos:
        if r.get("name") == repo_name:
            return r

    return generate_default_repo_config(repo_name)


def add_repo_to_config(config_path: Path, repo_name: str, base_branch: str | None = None) -> dict:
    """Validates repo with GitHub CLI and appends to config.yaml safely."""
    target_path = Path(config_path)
    with cfg_file_lock(target_path):
        if not target_path.exists():
            cfg = {"repos": []}
        else:
            content = target_path.read_text(encoding="utf-8")
            cfg = yaml.safe_load(content) or {}

        repos = cfg.setdefault("repos", [])
        for r in repos:
            if r.get("name") == repo_name:
                return r

        new_rcfg = generate_default_repo_config(repo_name, base_branch=base_branch)
        new_rcfg["enabled"] = True

        repos.append(new_rcfg)
        atomic_write_text(target_path, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return new_rcfg


def toggle_repo_in_config(config_path: Path, repo_name: str, enabled: bool) -> bool:
    """Toggles the enabled status of a repo in config.yaml."""
    target_path = Path(config_path)
    with cfg_file_lock(target_path):
        if not target_path.exists():
            return False
        content = target_path.read_text(encoding="utf-8")
        cfg = yaml.safe_load(content) or {}
        repos = cfg.get("repos", [])
        updated = False
        for r in repos:
            if r.get("name") == repo_name:
                r["enabled"] = enabled
                updated = True
                break
        if updated:
            atomic_write_text(target_path, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return updated


def delete_repo_from_config(config_path: Path, repo_name: str) -> bool:
    """Removes a repo entry from config.yaml."""
    target_path = Path(config_path)
    with cfg_file_lock(target_path):
        if not target_path.exists():
            return False
        content = target_path.read_text(encoding="utf-8")
        cfg = yaml.safe_load(content) or {}
        repos = cfg.get("repos", [])
        before_len = len(repos)
        cfg["repos"] = [r for r in repos if r.get("name") != repo_name]
        if len(cfg["repos"]) < before_len:
            atomic_write_text(target_path, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
            return True
        return False


def scan_user_repositories(cfg: dict | None = None) -> list[dict]:
    """Scans all available GitHub repositories for the authenticated user and local workspaces.
    Determines automation capability, stack profiles, and configuration status.
    """
    configured_status: dict[str, bool] = {}
    if cfg and "repos" in cfg:
        for r in cfg.get("repos", []):
            if isinstance(r, dict) and "name" in r:
                configured_status[r["name"]] = r.get("enabled", True)

    results_map: dict[str, dict] = {}

    # 1. GitHub CLI scan (gh repo list)
    try:
        raw_repos = gh_json(
            "repo", "list",
            "--limit", "100",
            "--json", "nameWithOwner,name,description,isPrivate,isArchived,defaultBranchRef,pushedAt,updatedAt"
        )
        if isinstance(raw_repos, list):
            for item in raw_repos:
                full_name = item.get("nameWithOwner") or item.get("name")
                if not full_name:
                    continue
                is_archived = bool(item.get("isArchived", False))
                branch_obj = item.get("defaultBranchRef") or {}
                default_branch = branch_obj.get("name", "main") if isinstance(branch_obj, dict) else "main"
                is_configured = full_name in configured_status
                enabled = configured_status.get(full_name, False) if is_configured else False
                can_automate = not is_archived

                results_map[full_name] = {
                    "name": full_name,
                    "short_name": item.get("name", full_name.split("/")[-1]),
                    "description": item.get("description") or "",
                    "is_private": bool(item.get("isPrivate", False)),
                    "is_archived": is_archived,
                    "default_branch": default_branch,
                    "pushed_at": item.get("pushedAt") or item.get("updatedAt") or "",
                    "is_configured": is_configured,
                    "enabled": enabled,
                    "can_automate": can_automate,
                    "source": "github",
                    "local_path": None,
                    "stack_hint": None,
                    "has_ci": None,
                }
    except Exception:
        pass

    # 2. Local directories scan (~/Documents, cwd)
    scan_roots = [Path.cwd()]
    doc_dir = Path.home() / "Documents"
    if doc_dir.exists() and doc_dir not in scan_roots:
        scan_roots.append(doc_dir)

    for root in scan_roots:
        try:
            candidates = []
            if (root / ".git").exists():
                candidates.append(root)
            else:
                for p in root.iterdir():
                    if p.is_dir() and (p / ".git").exists():
                        candidates.append(p)

            for p in candidates:
                remote_out = run_cmd(["git", "-C", str(p), "remote", "get-url", "origin"]).stdout.strip()
                repo_name = None
                if remote_out:
                    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", remote_out, re.IGNORECASE)
                    if m:
                        repo_name = m.group(1)
                if not repo_name:
                    owner = cfg.get("owner", "user") if cfg else "user"
                    repo_name = f"{owner}/{p.name}"

                stack = None
                try:
                    profile = detect_stack(p)
                    stack = profile.primary_language
                except Exception:
                    pass

                wf_dir = p / ".github" / "workflows"
                has_ci = wf_dir.is_dir() and any(f.is_file() and f.suffix in (".yml", ".yaml") for f in wf_dir.iterdir())

                if repo_name in results_map:
                    results_map[repo_name]["local_path"] = str(p)
                    results_map[repo_name]["has_ci"] = has_ci
                    if stack:
                        results_map[repo_name]["stack_hint"] = stack
                else:
                    is_conf = repo_name in configured_status
                    results_map[repo_name] = {
                        "name": repo_name,
                        "short_name": p.name,
                        "description": f"Local repository at {p.name}",
                        "is_private": False,
                        "is_archived": False,
                        "default_branch": "main",
                        "pushed_at": "",
                        "is_configured": is_conf,
                        "enabled": configured_status.get(repo_name, False) if is_conf else False,
                        "can_automate": True,
                        "source": "local",
                        "local_path": str(p),
                        "stack_hint": stack,
                        "has_ci": has_ci,
                    }
        except Exception:
            pass

    # Also make sure any repo already in config.yaml is included
    if cfg and "repos" in cfg:
        for r in cfg.get("repos", []):
            rname = r.get("name")
            if rname and rname not in results_map:
                results_map[rname] = {
                    "name": rname,
                    "short_name": rname.split("/")[-1],
                    "description": "Configured repository",
                    "is_private": False,
                    "is_archived": False,
                    "default_branch": r.get("base", "main"),
                    "pushed_at": "",
                    "is_configured": True,
                    "enabled": r.get("enabled", True),
                    "can_automate": True,
                    "source": "config",
                    "local_path": None,
                    "stack_hint": None,
                    "has_ci": None,
                }

    repo_list = list(results_map.values())
    repo_list.sort(key=lambda r: (
        0 if r["is_configured"] and r["enabled"] else 1 if r["is_configured"] else 2 if r["can_automate"] else 3,
        r["name"].lower()
    ))
    return repo_list


IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".superpowers", ".claude"}


def _validate_repo_name(repo_name: str) -> str:
    if not isinstance(repo_name, str) or not REPO_NAME_RE.match(repo_name) or ".." in repo_name.split("/"):
        raise ValueError(_i18n.t("ชื่อ repo ไม่ถูกต้อง: {p0}", p0=repr(repo_name)))
    return repo_name


def refresh_cache_clone(cached_repo: Path, force: bool = False) -> bool:
    """Fetch origin's default branch into an existing cache clone and move the working tree to it.

    Throttled by CACHE_REFRESH_SECONDS (measured on .git/FETCH_HEAD) unless force=True.
    Returns True when the clone was updated. A failed fetch is not fatal: the older clone
    stays usable, so the caller simply gets the last known state.
    """
    fetch_head = cached_repo / ".git" / "FETCH_HEAD"
    if not force:
        try:
            if fetch_head.exists() and time.time() - fetch_head.stat().st_mtime < CACHE_REFRESH_SECONDS:
                return False
        except OSError:
            pass
    try:
        fetched = run_cmd(["git", "-C", str(cached_repo), "fetch", "--quiet", "origin", "HEAD"],
                          timeout=CLONE_TIMEOUT_SECONDS)
        if fetched.returncode != 0:
            return False
        reset = run_cmd(["git", "-C", str(cached_repo), "reset", "--hard", "--quiet", "FETCH_HEAD"],
                        timeout=GH_TIMEOUT_SECONDS)
        return reset.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def find_or_prepare_repo_dir(repo_name: str, cfg: dict | None = None) -> Path:
    """Returns the cache clone of repo_name, cloning it when missing.

    An existing clone is refreshed from origin first (throttled, see refresh_cache_clone),
    so callers never read a snapshot that is older than origin's default branch by much.
    Raises RuntimeError when the clone fails (no empty folder is left behind).
    """
    _validate_repo_name(repo_name)
    cached_repo = REPOS_CACHE_DIR / repo_name.replace("/", "_")
    if (cached_repo / ".git").exists():
        refresh_cache_clone(cached_repo)
        return cached_repo.resolve()

    cached_repo.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = run_cmd(
            ["gh", "repo", "clone", repo_name, str(cached_repo), "--", "--depth", "1"],
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(cached_repo, ignore_errors=True)
        raise RuntimeError(_i18n.t("clone {p0} หมดเวลา ({p1}s)", p0=repo_name, p1=CLONE_TIMEOUT_SECONDS)) from exc

    if res.returncode != 0 or not (cached_repo / ".git").exists():
        shutil.rmtree(cached_repo, ignore_errors=True)
        detail = (res.stderr or res.stdout or "").strip() or "no .git directory created"
        raise RuntimeError(_i18n.t("clone {p0} ไม่สำเร็จ: {p1}", p0=repo_name, p1=detail))
    return cached_repo.resolve()


def list_repo_files(repo_dir: Path, max_files: int = 200) -> list[str]:
    files = []
    if not repo_dir.exists():
        return files
    for p in repo_dir.rglob("*"):
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file():
            try:
                rel = str(p.relative_to(repo_dir)).replace("\\", "/")
                files.append(rel)
                if len(files) >= max_files:
                    break
            except ValueError:
                pass
    return sorted(files)


def get_repo_workspace_info(repo_name: str, cfg: dict) -> dict:
    rcfg = ensure_repo_config(cfg, repo_name)
    repo_dir = find_or_prepare_repo_dir(repo_name, cfg)
    stack_profile = detect_stack(repo_dir)
    files = list_repo_files(repo_dir)

    issues = []
    try:
        raw_issues = gh_json("issue", "list", "-R", repo_name, "--state", "open", "--limit", "30",
                             "--json", "number,title,state,url,createdAt")
        if isinstance(raw_issues, list):
            issues = raw_issues
    except Exception:
        issues = []

    return {
        "name": repo_name,
        "base": rcfg.get("base", "main"),
        "stack_profile": dataclasses.asdict(stack_profile),
        "files": files,
        "issues": issues,
        "setup": rcfg.get("setup", []),
        "test": rcfg.get("test", []),
        "scanners": rcfg.get("scanners", {}),
    }


def get_repo_file_content(repo_name: str, rel_path: str, mode: str = "full", cfg: dict | None = None) -> dict:
    repo_dir = find_or_prepare_repo_dir(repo_name, cfg)
    clean_rel = rel_path.lstrip("/\\")
    target = (repo_dir / clean_rel).resolve()
    if repo_dir.resolve() not in target.parents and target != repo_dir.resolve():
        raise PermissionError(_i18n.t("Path นอกขอบเขตของ repository"))

    if not target.exists() or not target.is_file():
        raise FileNotFoundError(_i18n.t("ไม่พบไฟล์: {p0}", p0=rel_path))

    raw_text = target.read_text(encoding="utf-8", errors="replace")
    if mode == "ast" and clean_rel.endswith(".py"):
        content = extract_ast_skeleton(raw_text, clean_rel)
    else:
        content = raw_text

    return {
        "path": clean_rel,
        "content": content,
        "mode": mode,
        "lines": len(content.splitlines()),
    }


VERIFICATION_CHECKS = ("test", "syntax", "security", "setup")


def run_repo_verification(repo_name: str, check_type: str, cfg: dict) -> dict:
    # Only the named checks may run. Anything else used to be executed as a raw shell
    # command, which made /api/repo/run-command a remote-code-execution path (CRIT-01).
    if check_type not in VERIFICATION_CHECKS:
        raise ValueError(_i18n.t("check_type ไม่ถูกต้อง: {p0} (ใช้ได้: {p1})", p0=repr(check_type), p1=', '.join(VERIFICATION_CHECKS)))

    rcfg = ensure_repo_config(cfg, repo_name)
    repo_dir = find_or_prepare_repo_dir(repo_name, cfg)

    # Each entry is either a config shell string (test/security/setup) or an argv list.
    # File names never go through a shell: syntax checks use an argv list.
    cmds: list[str | list[str]] = []
    if check_type == "test":
        cmds = list(rcfg.get("test", ["python -m pytest -q"]))
    elif check_type == "syntax":
        files = [
            str(f.relative_to(repo_dir))
            for f in repo_dir.rglob("*.py")
            if not any(ign in f.parts for ign in IGNORE_DIRS)
        ][:20]
        if files:
            cmds = [[sys.executable, "-m", "py_compile", *files]]
        else:
            cmds = [[sys.executable, "-c", "print('No python files found or syntax valid')"]]
    elif check_type == "security":
        cmds = list(rcfg.get("scanners", {}).get("sentinel", ["python -m bandit -q -r ."]))
    elif check_type == "setup":
        cmds = list(rcfg.get("setup", ["python -m pip install -q -r requirements.txt"]))

    combined_stdout = []
    combined_stderr = []
    labels = []
    last_rc = 0

    for cmd in cmds:
        label = cmd if isinstance(cmd, str) else " ".join(cmd)
        labels.append(label)
        kwargs: dict = dict(
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERIFY_TIMEOUT_SECONDS,
        )
        if isinstance(cmd, str):
            kwargs["shell"] = True
        try:
            res = run_tree(cmd, **kwargs)
            last_rc = res.returncode
            if res.stdout:
                combined_stdout.append(res.stdout)
            if res.stderr:
                combined_stderr.append(res.stderr)
            if res.returncode != 0:
                break
        except subprocess.TimeoutExpired:
            last_rc = 124
            combined_stderr.append(f"Command timed out after {VERIFY_TIMEOUT_SECONDS}s: {label}")
            break
        except Exception as exc:
            last_rc = 1
            combined_stderr.append(str(exc))
            break

    return {
        "ok": last_rc == 0,
        "exit_code": last_rc,
        "stdout": "\n".join(combined_stdout),
        "stderr": "\n".join(combined_stderr),
        "command": " && ".join(labels),
    }


def dispatch_studio_coding_task(
    repo_name: str,
    prompt: str,
    persona: str = "bolt",
    mode: str = "surgical",
    engine: str = "opencode",
    sandbox: bool = False,
    cfg: dict | None = None,
) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("ต้องระบุคำสั่ง prompt สำหรับการเขียนโค้ด")

    if sandbox:
        repo_dir = find_or_prepare_repo_dir(repo_name, cfg)
        return {
            "ok": True,
            "sandbox": True,
            "diff": f"# Sandbox preview for {repo_name}\n# Persona: {persona} (Mode: {mode})\n# Engine: {engine}\n+ # Changes simulated for: {prompt[:80]}",
            "message": "Sandbox preview generated",
            "workdir": str(repo_dir),
        }
    else:
        title = f"[{mode.upper()}][{persona.upper()}] {prompt[:60].strip()}"
        body = f"{prompt}\n\n---\nTarget-Repo: {repo_name}\nMode: {mode}\nPersona: {persona}\nEngine: {engine}"
        labels = cfg.get("labels", {}) if cfg else {}
        task_label = labels.get("task", "ai-task")

        issue_url = gh(
            "issue", "create",
            "-R", repo_name,
            "--title", title,
            "--body", body,
            "--label", task_label,
        )
        return {
            "ok": True,
            "sandbox": False,
            "issue_url": issue_url,
            "message": _i18n.t("สั่งงานลงคิว GitHub เรียบร้อยแล้ว ({p0})", p0=issue_url),
        }


def sync_repo(repo_name: str, cfg: dict | None = None) -> dict:
    repo_dir = find_or_prepare_repo_dir(repo_name, cfg)
    try:
        res = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return {
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "message": _i18n.t("ซิงค์ repository สำเร็จ") if res.returncode == 0 else _i18n.t("เกิดข้อผิดพลาดในการซิงค์"),
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


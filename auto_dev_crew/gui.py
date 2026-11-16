"""Local web GUI for Auto Dev Crew (F5). Stdlib only; binds to 127.0.0.1.

Run: python -m auto_dev_crew.gui  [--port 8765] [--no-browser]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import yaml_io

from . import runner, multi_repo, todo_scan, ci_bootstrap, deep_scan, feature_gen
from . import autonomous_upgrades, context_slicer, doctor, gui_patches, mcp_server, metrics, playground, routing
from .redact import redact_secrets
from . import keys, key_ping, providers, byop, byop_store
from .multi_repo import add_repo_to_config
# หมายเหตุ: mcp_server import gui กลับ จึง import แบบ lazy ใน _api_mcp_call_preview เพื่อกัน circular import

STATIC = Path(__file__).parent / "static"
RUNS = runner.STATE / "runs"
_CONFIG_OVERRIDE: Path | None = None  # set by --config (F-9); None = ROOT/config.yaml


def config_path() -> Path:
    """Config file the GUI reads and edits. Resolved per call so runner.ROOT patches still apply."""
    return _CONFIG_OVERRIDE or runner.ROOT / "config.yaml"


def set_config_path(path) -> None:
    global _CONFIG_OVERRIDE
    _CONFIG_OVERRIDE = Path(path) if path else None


TOKEN = secrets.token_urlsafe(24)   # required on every POST (blocks drive-by requests from other sites)
MAX_BODY_BYTES = 1024 * 1024        # largest POST body accepted (LOW-07)


def _engine_cfg_kw() -> dict:
    """Extra cfg_path kwarg for keys.* engine calls. Empty unless --config was given, so the default
    call signatures (and keys.ROOT defaults that tests patch) stay exactly as before."""
    return {"cfg_path": _CONFIG_OVERRIDE} if _CONFIG_OVERRIDE is not None else {}


def load_cfg() -> dict:
    return yaml_io.load_text(config_path().read_text(encoding="utf-8"))


def _require_repo(repo_raw, cfg: dict) -> str:
    """Validate owner/repo syntax (blocking leading '-' CLI flags) and, when cfg defines repos, config membership."""
    if "repos" in cfg:
        return gui_patches.require_registered_repo(repo_raw, cfg)
    repo = str(repo_raw or "").strip()
    if not gui_patches.REPO_ALLOW_RE.fullmatch(repo):
        raise ValueError("ชื่อ repo ไม่ถูกต้อง (ต้องอยู่ในรูปแบบ owner/repo และห้ามขึ้นต้นด้วย '-')")
    return repo


# ---------------------------------------------------------------- runner process

_RUNNER_RE = re.compile(r"-m\s+auto_dev_crew(?=\s|$|\")")


def parse_runner_pids(rows, exclude=()) -> list[int]:
    """Pick out runner processes (`python -m auto_dev_crew ...`) from (pid, cmdline) rows.

    `auto_dev_crew.gui` does not match: the character after `auto_dev_crew` must be whitespace, quote or end.
    """
    found: list[int] = []
    for pid, cmd in rows:
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_i in exclude or not cmd:
            continue
        if _RUNNER_RE.search(str(cmd)):
            found.append(pid_i)
    return sorted(found)


def _scan_runner_pids() -> list[int]:
    """Runner processes on this machine, including ones started from a terminal instead of this GUI."""
    try:
        if os.name == "nt":
            ps = ("Get-CimInstance Win32_Process -Filter \"name LIKE 'python%'\" "
                  "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=10).stdout
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            rows = [(d.get("ProcessId"), d.get("CommandLine")) for d in data]
        else:
            out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=10).stdout
            rows = [tuple(line.strip().split(None, 1)) for line in out.splitlines() if line.strip()]
    except Exception:
        return []
    return parse_runner_pids(rows, exclude={os.getpid()})


class Agent:
    """Owns at most one runner subprocess and fans its output out to the log viewers."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.args: list[str] = []
        self.started: str | None = None
        self.lines: deque[str] = deque(maxlen=2000)
        self.seq = 0
        self.cond = threading.Condition()
        # Serialises start/stop/restart so the AutoPilot thread and HTTP handlers cannot both spawn a runner.
        self.lock = threading.RLock()
        self._ext: list[int] = []
        self._ext_at = 0.0

    def external_pids(self) -> list[int]:
        """Runner processes this GUI did not start. Cached for 5 s so the status poll stays cheap."""
        now = time.monotonic()
        if now - self._ext_at > 5:
            own = {self.proc.pid} if self.proc is not None else set()
            self._ext = [p for p in _scan_runner_pids() if p not in own]
            self._ext_at = now
        return self._ext

    @property
    def running(self) -> bool:
        return (self.proc is not None and self.proc.poll() is None) or bool(self.external_pids())

    def start(self, args: list[str]) -> None:
        with self.lock:
            if self.external_pids():
                raise RuntimeError("มี runner เปิดอยู่นอก GUI แล้ว — กดหยุดก่อนค่อยเริ่มใหม่")
            if self.running:
                raise RuntimeError("เอเจนต์กำลังทำงานอยู่แล้ว")
            if _CONFIG_OVERRIDE is not None and "--config" not in args:
                # The runner must read the same file the GUI edits (F-9).
                args = [*args, "--config", str(_CONFIG_OVERRIDE)]
            RUNS.mkdir(parents=True, exist_ok=True)
            self.args, self.started = args, dt.datetime.now().isoformat(timespec="seconds")
            try:
                autonomous_upgrades.save_session_checkpoint(args, runner.STATE)
            except Exception:
                pass
            logfile = RUNS / f"{dt.datetime.now():%Y%m%d-%H%M%S}.log"
            self.proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "auto_dev_crew", *args], cwd=runner.ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                start_new_session=os.name != "nt")
            self._emit(f"▶ เริ่ม: auto_dev_crew {' '.join(args)}")
            threading.Thread(target=self._pump, args=(self.proc, logfile), daemon=True).start()

    def stop(self) -> None:
        with self.lock:
            own_running = self.proc is not None and self.proc.poll() is None
            ext = self.external_pids()
            if own_running or ext:
                if own_running:
                    # Kill the whole tree: terminating only the runner would leave agy using quota.
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
                    else:
                        os.killpg(self.proc.pid, signal.SIGTERM)
                for pid in ext:
                    # Runner started outside the GUI: stop it too, so the button does what it says.
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                    else:
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except OSError:
                            pass
                # The runner's own finally blocks never run after a kill, so its slots would
                # stay "busy" in the Overview until the 2 h heartbeat expiry (F-12).
                runner.REGISTRY.clear_all()
                self._ext_at = 0.0
                self._emit("■ ผู้ใช้สั่งหยุด" + (f" (รวม runner ที่เปิดนอก GUI: PID {', '.join(map(str, ext))})" if ext else ""))

    def restart(self, args: list[str] | None = None) -> list[str]:
        with self.lock:
            target_args = list(args) if args is not None else (list(self.args) if self.args else ["--loop"])
            if not target_args:
                target_args = ["--loop"]
            if self.running:
                self.stop()
                if self.proc:
                    try:
                        self.proc.wait(timeout=5)
                    except Exception:
                        pass
            self._emit("🔄 กำลังรีสตาร์ทเอเจนต์...")
            self.start(target_args)
            return target_args

    def _pump(self, proc: subprocess.Popen, logfile: Path) -> None:
        with logfile.open("w", encoding="utf-8") as fh:
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
                self._emit(line.rstrip("\n"))
        code = proc.wait()
        if code == WIN_DLL_INIT_FAILED:
            self._emit("⚠️ Windows ปฏิเสธการเริ่มโปรเซส (0xC0000142: DLL init failed) — มักเกิดจากทรัพยากรระบบไม่พอชั่วคราว ระบบจะลองใหม่ให้เอง")
        self._emit(f"● จบการทำงาน (exit {code})")

    def _emit(self, line: str) -> None:
        with self.cond:
            self.seq += 1
            self.lines.append(line)
            self.cond.notify_all()


AGENT = Agent()

# Windows NTSTATUS STATUS_DLL_INIT_FAILED: the process never started (transient resource shortage), so retry soon.
WIN_DLL_INIT_FAILED = 0xC0000142

# Wait before restarting the loop, by runner exit code (0 = no work / PR pending, 3 = quota, else error).
AUTO_WAIT = {0: 15 * 60, 3: 60 * 60, WIN_DLL_INIT_FAILED: 60}
AUTO_WAIT_ERROR = 5 * 60


class AutoPilot:
    """Keeps `--loop` running forever while enabled: restarts it after it exits.
    The ■ stop button turns it off; the start buttons turn it back on."""

    def __init__(self) -> None:
        self.enabled = False
        self.next_run: float | None = None
        self.args: list[str] = ["--loop"]
        threading.Thread(target=self._watch, daemon=True).start()

    def enable(self, args: list[str] | None = None) -> None:
        self.enabled, self.next_run = True, None if AGENT.running else time.time()
        self.args = list(args) if args else ["--loop"]

    def disable(self) -> None:
        self.enabled, self.next_run = False, None

    def _watch(self) -> None:
        while True:
            time.sleep(5)
            if not self.enabled or AGENT.running:
                continue
            if self.next_run is None:   # the loop just ended: schedule the next one
                code = AGENT.proc.returncode if AGENT.proc else 0
                wait = AUTO_WAIT.get(code, AUTO_WAIT_ERROR)
                self.next_run = time.time() + wait
                AGENT._emit(f"⏱ โหมดอัตโนมัติ: เริ่มรอบใหม่ใน {wait // 60} นาที (exit {code})")
            elif time.time() >= self.next_run:
                try:
                    AGENT.start(self.args)
                except RuntimeError:
                    pass
                self.next_run = None


AUTO = AutoPilot()


# ---------------------------------------------------------------- data

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def repo_status(cfg: dict, name: str) -> dict:
    labels = cfg["labels"]
    issues = runner.gh_json("issue", "list", "-R", name, "--state", "all", "--label", labels["task"],
                            "--json", "number,title,state,labels,author,createdAt,url", "--limit", "50")
    prs = runner.gh_json("pr", "list", "-R", name, "--state", "all", "--label", labels["pr"],
                         "--json", "number,title,state,url,additions,deletions,createdAt", "--limit", "30")
    for issue in issues:
        names = {l["name"] for l in issue.pop("labels")}
        issue["author"] = issue["author"]["login"]
        issue["status"] = ("closed" if issue["state"] == "CLOSED" else
                           "working" if labels["working"] in names else
                           "failed" if labels["failed"] in names else
                           "ignored" if issue["author"].lower() != cfg["owner"].lower() else "queued")
    enabled = next((r.get("enabled", True) for r in cfg.get("repos", []) if r.get("name") == name), True)
    rcfg_match = next((r for r in cfg.get("repos", []) if r.get("name") == name), {})
    r_ci = rcfg_match.get("ci") or {}
    allow_no_ci = r_ci.get("allow_no_ci", cfg.get("ci", {}).get("allow_no_ci", True))
    auto_bootstrap_ci = bool(r_ci.get("auto_bootstrap_ci", cfg.get("ci", {}).get("auto_bootstrap_ci", False)))
    return {"name": name, "enabled": enabled, "allow_no_ci": allow_no_ci, "auto_bootstrap_ci": auto_bootstrap_ci,
            "paused": runner.paused(name, cfg), "issues": issues, "prs": prs}


def toggle_engine_in_config(name: str, enabled: bool) -> bool:
    # keys.update_engine matches the exact engine name under `engines:` and writes under the config lock.
    return keys.update_engine(name, {"enabled": enabled}, cfg_path=config_path())


def _num(value) -> float:
    """Keep a usage-log numeric field as is; anything else (missing, string, bool) counts as 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def usage_summary(cfg: dict) -> dict:
    path = runner.STATE / "usage.jsonl"
    rows: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:   # one corrupt line must not take the whole status page down
                continue
            if isinstance(row, dict):
                rows.append(row)
    today = dt.date.today().isoformat()
    todays = [r for r in rows if str(r.get("ts", "")).startswith(today)]
    last_quota = next((r.get("ts") for r in reversed(rows) if r.get("status") == "QUOTA"), None)
    account = None
    try:
        account = json.loads((Path.home() / ".gemini" / "google_accounts.json").read_text(encoding="utf-8")).get("active")
    except (OSError, ValueError):
        pass

    engines = runner.get_engines(cfg)
    status_map = runner.load_engine_status()
    key_status = runner.load_key_status()
    engine_list = []
    now = time.time()
    for i, eng in enumerate(engines, 1):
        name = eng.get("name", eng["command"])
        eng_stat = status_map.get(name, {})
        cooldown = eng_stat.get("cooldown_until", 0)
        enabled = eng.get("enabled", True)
        entries = runner.get_engine_key_entries(eng)
        key_count = len(entries)
        ready_key_count = sum(1 for key_id, _ in entries if now >= key_status.get(key_id, {}).get("cooldown_until", 0))
        if not enabled:
            state = "disabled"
        elif (key_count > 0 and ready_key_count == 0) or (key_count == 0 and cooldown > now):
            state = "quota"
        else:
            state = "ok"

        engine_list.append({
            "order": i,
            "name": name,
            "provider": eng.get("provider", eng["command"]),
            "engine": eng["command"],
            "model": eng["model"],
            "trains_on_data": eng.get("trains_on_data", False),
            "enabled": enabled,
            "account": account if eng["command"] == "agy" else None,
            "state": state,
            "key_count": key_count,
            "ready_key_count": ready_key_count,
            "keys_status": f"{ready_key_count}/{key_count} keys ready" if key_count > 0 else None,
            "cooldown_until": dt.datetime.fromtimestamp(cooldown).isoformat(timespec="seconds") if cooldown > now else None,
        })

    return {
        "engines": engine_list,
        "today": {"calls": len(todays), "tokens": sum(_num(r.get("tokens")) for r in todays),
                  "minutes": round(sum(_num(r.get("seconds")) for r in todays) / 60)},
        "last_quota": last_quota,
        "keys": _key_outcomes(rows, today),
        "recent": rows[-20:][::-1],
    }


def _key_outcomes(rows: list[dict], today: str) -> list[dict]:
    """นับผลต่อ API key: success = เสร็จ (SUCCESS), failed = ไม่เสร็จ (ERROR หรือ QUOTA).
    แถวที่ไม่มี key_id (เช่น engine ที่ไม่มีคีย์ หรือแถวเก่าก่อนมีการบันทึก key) ไม่ถูกนับ."""
    totals: dict[str, dict] = {}
    for r in rows:
        key_id = r.get("key_id")
        if not key_id:
            continue
        stat = totals.setdefault(key_id, {"key_id": key_id, "engine_name": r.get("engine_name"),
                                          "success": 0, "failed": 0, "quota": 0,
                                          "today_success": 0, "today_failed": 0})
        ok = r.get("status") == "SUCCESS"
        is_today = str(r.get("ts", "")).startswith(today)
        stat["success" if ok else "failed"] += 1
        if r.get("status") == "QUOTA":
            stat["quota"] += 1
        if is_today:
            stat["today_success" if ok else "today_failed"] += 1
    return sorted(totals.values(), key=lambda s: s["key_id"])


def slots_summary(cfg: dict) -> dict:
    parallel_cfg = cfg.get("parallel", {})
    num_slots = parallel_cfg.get("slots", 3) if parallel_cfg.get("enabled", True) else 1
    active_jobs = runner.REGISTRY.get_active_jobs()
    slots = {}
    for s_id in range(1, num_slots + 1):
        s_key = f"slot_{s_id}"
        info = active_jobs.get(s_key)
        if info:
            slots[s_key] = {
                "slot_id": s_id,
                "state": info.get("state", "working"),
                "kind": info.get("kind"),
                "key": info.get("key"),
                "branch": info.get("branch"),
                "active_files": info.get("active_files", []),
                "started_at": info.get("started_at"),
            }
        else:
            slots[s_key] = {
                "slot_id": s_id,
                "state": "idle",
                "kind": None,
                "key": None,
                "branch": None,
                "active_files": [],
                "started_at": None,
            }
    return slots


def system_activity_summary(cfg: dict, slots: dict, repos: list[dict], history: list[dict]) -> dict:
    active_slots = [s for s in slots.values() if s.get("state") and s.get("state") != "idle"]
    active_count = len(active_slots)
    queued_issues = 0
    for r in repos:
        for i in r.get("issues", []):
            if i.get("status") == "queued":
                queued_issues += 1

    enabled_personas = cfg.get("personas", {}).get("enabled", [])
    recent_personas = [h for h in history if h.get("kind") == "persona"][-len(enabled_personas):] if enabled_personas else []
    all_no_action = (
        bool(enabled_personas)
        and len(recent_personas) == len(enabled_personas)
        and all(h.get("state") == "NO_ACTION" for h in recent_personas)
    )

    persona_resting = False
    rest_remaining_minutes = 0
    if all_no_action and recent_personas:
        try:
            last_run = dt.datetime.strptime(recent_personas[-1]["date"], "%Y%m%d-%H%M")
        except Exception:
            last_run = dt.datetime.now()
        elapsed = (dt.datetime.now() - last_run).total_seconds()
        rest_total = getattr(runner, "PERSONA_REST_HOURS", 24) * 3600
        if elapsed < rest_total:
            persona_resting = True
            rest_remaining_minutes = max(1, int((rest_total - elapsed) / 60))

    if active_count > 0:
        return {
            "state": "working",
            "is_all_done": False,
            "title": f"กำลังทำงาน ({active_count} ช่อง)",
            "message": f"มีงานกำลังประมวลผลอยู่ในขณะนี้ {active_count} ช่อง",
            "persona_resting": False,
            "rest_remaining_minutes": 0,
            "rest_time_str": "",
            "queued_issues": queued_issues,
            "can_wake": False,
        }
    elif persona_resting and queued_issues == 0:
        hours = rest_remaining_minutes // 60
        mins = rest_remaining_minutes % 60
        time_str = f"{hours} ชม. {mins} นาที" if hours > 0 else f"{mins} นาที"
        return {
            "state": "all_done",
            "is_all_done": True,
            "title": "ไม่มีอะไรทำงานแล้ว — ทุกช่องสแตนด์บายสมบูรณ์",
            "message": (
                "ไม่มี Issue ค้างใน GitHub และตัวละคร Persona ทั้งหมด (Bolt, Sentinel, Palette, Quality) "
                "สแกนโค้ดครบถ้วนแล้วและไม่พบสิ่งที่ต้องแก้ไข (NO_ACTION) จึงพักผ่อนเพื่อประหยัดโควตา API"
            ),
            "persona_resting": True,
            "rest_remaining_minutes": rest_remaining_minutes,
            "rest_time_str": time_str,
            "queued_issues": 0,
            "can_wake": True,
        }
    else:
        return {
            "state": "idle",
            "is_all_done": (queued_issues == 0),
            "title": "ทุกช่องว่าง (สแตนด์บาย)",
            "message": "พร้อมรับงาน Issue ทันที หรือรอรอบการหมุนเวียนตรวจจับงาน",
            "persona_resting": persona_resting,
            "rest_remaining_minutes": rest_remaining_minutes,
            "rest_time_str": "",
            "queued_issues": queued_issues,
            "can_wake": persona_resting,
        }


def status() -> dict:
    cfg = load_cfg()
    def _repo(r: dict) -> dict:
        try:
            return cached("repo:" + r["name"], 20, lambda n=r["name"]: repo_status(cfg, n))
        except Exception as exc:   # keep the page usable when gh is offline
            return {"name": r["name"], "error": str(exc)[:300], "issues": [], "prs": []}

    # gh calls take seconds each; fetch repos in parallel so /api/status stays responsive.
    repo_list = cfg["repos"]
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(repo_list)))) as pool:
        repos = list(pool.map(_repo, repo_list))
    raw_history = runner.load_history()
    slots = slots_summary(cfg)
    activity = system_activity_summary(cfg, slots, repos, raw_history)
    return {
        "agent": {"running": AGENT.running, "args": AGENT.args, "started": AGENT.started,
                  "auto": AUTO.enabled,
                  "next_run": dt.datetime.fromtimestamp(AUTO.next_run).isoformat(timespec="seconds")
                  if AUTO.enabled and AUTO.next_run else None},
        "drain": autonomous_upgrades.read_drain_state(runner.STATE),
        "merge_mode": cfg["merge_mode"], "personas": cfg["personas"]["enabled"], "owner": cfg["owner"],
        "repos": repos, "slots": slots, "active_slot": cfg.get("parallel", {}).get("active_slot"),
        "history": raw_history[-50:][::-1], "usage": usage_summary(cfg),
        "keys_catalog": keys.get_keys_catalog(cfg),
        "activity": activity,
        "evaluation": {
            "enabled": cfg.get("evaluation", {}).get("enabled", True),
            "engine": cfg.get("evaluation", {}).get("engine", "auto"),
        },
        "ci": {
            "enabled": cfg.get("ci", {}).get("enabled", True),
            "allow_no_ci": cfg.get("ci", {}).get("allow_no_ci", True),
            "auto_bootstrap_ci": cfg.get("ci", {}).get("auto_bootstrap_ci", False),
        },
    }


def diff_for(q: dict) -> str:
    if "pr" in q:
        repo = _require_repo(q.get("repo"), load_cfg())
        pr_num = str(q["pr"]).strip()
        if not pr_num.isdigit():
            raise ValueError("หมายเลข PR ไม่ถูกต้อง")
        return redact_secrets(runner.gh("pr", "diff", pr_num, "-R", repo, check=False))
    work = gui_patches.resolve_safe_worktree_path(q["workdir"], runner.WORK)
    if not work.exists():
        return "(ไม่พบโฟลเดอร์งานนี้แล้ว — อาจถูกลบไป)"
    return redact_secrets(runner.run(["git", "diff", "--cached"], cwd=work, check=False).stdout)


# ---------------------------------------------------------------- actions

def _api_run(body: dict, cfg: dict) -> dict:
    args = []
    if body.get("loop"):
        args.append("--loop")
    if body.get("dry_run"):
        args.append("--dry-run")
    if body.get("persona"):
        if body["persona"] not in cfg["personas"]["enabled"]:
            raise ValueError("ไม่รู้จักตัวละครนี้")
        args += ["--persona", body["persona"]]
    if body.get("repo"):
        repo_val = _require_repo(body["repo"], cfg)
        args += ["--repo", repo_val]
    # Running is always the user's explicit action: this never turns AutoPilot on (that is `--auto` at GUI start).
    autonomous_upgrades.clear_graceful_drain(runner.STATE)  # a new run must not start already draining
    AGENT.start(args)
    return {"ok": True}


def _api_stop(body: dict, cfg: dict) -> dict:
    AUTO.disable()
    AGENT.stop()
    return {"ok": True}


_RESTART_RUN_KEYS = ("loop", "dry_run", "persona", "repo")


def _api_restart(body: dict, cfg: dict) -> dict:
    """Restart the agent. With no run settings in the body it keeps the args of the last run.

    Never falls back to a bare `--loop` (that would start a real run on every repo): if there is
    no previous run to keep and no explicit settings, the request is refused.
    """
    if any(key in body for key in _RESTART_RUN_KEYS):
        args = []
        if body.get("loop"):
            args.append("--loop")
        if body.get("dry_run"):
            args.append("--dry-run")
        if body.get("persona"):
            if body["persona"] not in cfg["personas"]["enabled"]:
                raise ValueError("ไม่รู้จักตัวละครนี้")
            args += ["--persona", body["persona"]]
        if body.get("repo"):
            repo_val = _require_repo(body["repo"], cfg)
            args += ["--repo", repo_val]
        if not args:
            raise ValueError("ยังไม่ได้เลือกโหมดหรือ repo — ไม่รีสตาร์ทเป็นโหมดจริงทุก repo โดยไม่ตั้งใจ")
    elif body.get("resume_checkpoint"):
        saved = autonomous_upgrades.load_session_checkpoint(runner.STATE)
        if not saved:
            raise ValueError("ไม่พบ session checkpoint ที่บันทึกไว้")
        args = list(saved)
    else:
        if not AGENT.args:
            raise ValueError("ไม่มีค่าเดิมของรอบล่าสุดให้คงไว้ — เริ่มงานด้วยปุ่มเริ่มก่อน แล้วค่อยรีสตาร์ท")
        args = list(AGENT.args)

    autonomous_upgrades.clear_graceful_drain(runner.STATE)  # a restart must not start already draining
    final_args = AGENT.restart(args)
    # Restart never turns AutoPilot on; a non-loop restart turns it off.
    if "--loop" not in final_args or "--dry-run" in final_args or "--persona" in final_args:
        AUTO.disable()
    return {"ok": True, "args": final_args, "message": "รีสตาร์ทเอเจนต์สำเร็จแล้ว"}


def _api_task(body: dict, cfg: dict) -> dict:
    repo = gui_patches.require_registered_repo(body.get("repo"), cfg)
    title = (body.get("title") or "").strip()
    if not title:
        raise ValueError("ต้องเลือก repo และใส่ชื่องาน")
    runner.ensure_labels(repo, cfg)
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body_content = (body.get("body") or "(สร้างจาก Auto Dev Crew GUI)").strip()
    body_content += f"\n\n---\n🕒 สั่งงานเมื่อ: {now_str}"
    url = runner.gh("issue", "create", "-R", repo, "--title", title,
                    "--body", body_content, "--label", cfg["labels"]["task"])
    _cache.pop("repo:" + repo, None)
    return {"ok": True, "url": url}


# Serialises the check-then-create in _api_pause so double clicks cannot open two pause issues.
_PAUSE_LOCK = threading.Lock()
# repo -> number of the pause issue this GUI opened. GitHub's issue list can lag behind a fresh
# create, so the list alone cannot prove a pause issue exists yet.
_PAUSE_ISSUES: dict[str, int] = {}


def _open_pause_issue(repo: str, label: str) -> int | None:
    """Number of an open pause issue for `repo`, or None. Checks the issue this GUI opened first (a single
    issue view is consistent), then falls back to the label list."""
    number = _PAUSE_ISSUES.get(repo)
    if number is not None:
        if runner.gh_json("issue", "view", str(number), "-R", repo, "--json", "state").get("state") == "OPEN":
            return number
        _PAUSE_ISSUES.pop(repo, None)
    listed = runner.gh_json("issue", "list", "-R", repo, "--state", "open",
                            "--label", label, "--json", "number")
    return listed[0]["number"] if listed else None


def _api_pause(body: dict, cfg: dict) -> dict:
    repo = _require_repo(body.get("repo"), cfg)
    label = cfg["labels"]["pause"]
    if body.get("on"):
        runner.ensure_labels(repo, cfg)
        with _PAUSE_LOCK:
            # Paused state is derived from the open pause issue, so a second one would be a duplicate.
            if _open_pause_issue(repo, label) is None:
                url = runner.gh("issue", "create", "-R", repo, "--title", "⏸️ หยุดเอเจนต์ชั่วคราว",
                                "--body", "ปิด issue นี้เพื่อให้เอเจนต์ทำงานต่อ", "--label", label)
                tail = (url or "").strip().rstrip("/").rsplit("/", 1)[-1]
                if tail.isdigit():
                    _PAUSE_ISSUES[repo] = int(tail)
    else:
        cached = _PAUSE_ISSUES.pop(repo, None)
        numbers = {i["number"] for i in runner.gh_json("issue", "list", "-R", repo, "--state", "open",
                                                       "--label", label, "--json", "number")}
        # Also close the issue this GUI opened, in case the list has not caught up with it yet.
        if cached is not None and cached not in numbers and \
                runner.gh_json("issue", "view", str(cached), "-R", repo, "--json", "state").get("state") == "OPEN":
            numbers.add(cached)
        for number in sorted(numbers):
            runner.gh("issue", "close", str(number), "-R", repo)
    _cache.pop("repo:" + repo, None)
    return {"ok": True}


def _api_engine(body: dict, cfg: dict) -> dict:
    name = body.get("name")
    enabled = bool(body.get("enabled"))
    if not name:
        raise ValueError("ต้องระบุชื่อ engine")
    ok = toggle_engine_in_config(name, enabled)
    return {"ok": ok}


def _api_repos_add(body: dict, cfg: dict) -> dict:
    repo_name = (body.get("repo") or body.get("name") or "").strip()
    if not gui_patches.REPO_ALLOW_RE.fullmatch(repo_name):
        raise ValueError("ต้องระบุชื่อ repo ในรูปแบบ owner/repo เช่น example-owner/my-repo")
    base = body.get("base")
    rcfg = add_repo_to_config(config_path(), repo_name, base_branch=base)
    try:
        runner.ensure_labels(repo_name, cfg)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("สร้างป้าย PR ของ %s ไม่สำเร็จ: %s", repo_name, exc)
    _cache.clear()
    return {"ok": True, "repo": rcfg}


def _api_repos_toggle(body: dict, cfg: dict) -> dict:
    name = (body.get("name") or body.get("repo") or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อ repo")
    enabled = bool(body.get("enabled", True))
    ok = multi_repo.toggle_repo_in_config(config_path(), name, enabled)
    _cache.clear()
    return {"ok": ok, "repo": name, "enabled": enabled}


def _api_repos_delete(body: dict, cfg: dict) -> dict:
    name = (body.get("name") or body.get("repo") or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อ repo")
    ok = multi_repo.delete_repo_from_config(config_path(), name)
    _cache.clear()
    return {"ok": ok, "deleted": name}


def _api_repos_scan(body: dict, cfg: dict) -> dict:
    scanned = multi_repo.scan_user_repositories(cfg)
    return {"ok": True, "repositories": scanned, "count": len(scanned)}


def _api_todo_scan(body: dict, cfg: dict) -> dict:
    repo = _require_repo(body.get("repo"), cfg)
    return todo_scan.run_scan(repo, cfg, create=bool(body.get("create")))


class DeepScanHttpError(Exception):
    """Carries an HTTP status for the deep-scan handlers (400 bad input, 404 unknown finding)."""
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _deep_scan_repo(body: dict, cfg: dict) -> str:
    repo = (body.get("repo") or "").strip()
    if not repo or repo not in {r.get("name") for r in cfg.get("repos", []) or [] if isinstance(r, dict)}:
        raise DeepScanHttpError(400, "repo ไม่อยู่ใน config")
    return repo


def deep_scan_engines(cfg: dict) -> list[str]:
    """Engine names with at least one ${VAR} api key whose effective roles include 'scan'."""
    names = []
    for eng in cfg.get("engines", []) or []:
        for entry in eng.get("api_keys") or []:
            m = re.fullmatch(r"\$\{([^}]+)\}", str(entry).strip())
            if m and "scan" in keys.get_key_effective_roles(m.group(1)):
                names.append(runner.key_engine_name(eng))
                break
    return names


def _scan_agent_call(prompt: str, cfg: dict, engine: str, cwd: Path) -> str:
    res = runner.call_agent(cfg, prompt, cwd, role="scan", engine_name=engine)
    if res.get("status") != "SUCCESS":
        raise RuntimeError(str(res.get("response") or res.get("status")))
    return res["response"]


def _run_scan_agent(prompt: str, cfg: dict, engine: str, repo_dir: Path) -> str:
    # agentic: the agent reads the repo clone itself (role=scan allows read/grep/glob only).
    # inline: the prompt already holds the file text, so run in an empty temp dir instead.
    if deep_scan.scan_mode(cfg) == "agentic":
        return _scan_agent_call(prompt, cfg, engine, repo_dir)
    with tempfile.TemporaryDirectory() as tmp_cwd:
        return _scan_agent_call(prompt, cfg, engine, Path(tmp_cwd))


def _api_deep_scan(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    engine = (body.get("engine") or "").strip()
    if engine not in deep_scan_engines(cfg):
        raise DeepScanHttpError(400, "ไม่พบ engine ที่ใช้สแกนได้")
    repo_dir = Path(multi_repo.find_or_prepare_repo_dir(repo, cfg))
    budget = deep_scan.CallBudget(deep_scan.call_budget_limit(cfg))  # one budget shared by scan + verify
    call_model = budget.wrap(lambda prompt: _run_scan_agent(prompt, cfg, engine, repo_dir))

    result = deep_scan.run_deep_scan(repo, cfg, runner.STATE, call_model)
    try:  # feature plans (ai-plan) are on by default; a failure must not hide the scan result
        result["feature_plans"] = _feature_cycle(repo, cfg, repo_dir, budget, engine)
    except Exception as exc:  # noqa: BLE001
        result["feature_plans"] = {"ran": True, "errors": [redact_secrets(f"สร้างแผนฟีเจอร์ไม่สำเร็จ: {exc}")]}
    label = (cfg.get("labels") or {}).get("task", "ai-task")

    def verify(f):  # ด่าน 4: ตรวจซ้ำกับไฟล์จริงก่อนสร้าง issue (ดู docs/draft-quality-gates.md)
        return deep_scan.verify_finding(f, repo_dir, call_model)

    try:  # auto-issue is opt-in (auto_issue.enabled); its failure must not hide the scan result
        result["auto_issue"] = deep_scan.file_findings_automatically(
            repo, cfg, runner.STATE, result.get("findings", []), label=label, verify=verify)
    except Exception as exc:
        result["auto_issue"] = {"ran": True, "created": 0, "skipped": 0,
                                "errors": [redact_secrets(f"auto-issue ล้มเหลว: {exc}")]}
    result["calls_used"] = budget.used  # after feature plans and verify, so it counts every call of the run
    return result


def _deep_scan_view(repo: str, cfg: dict, data: dict | None) -> dict | None:
    """Add each filed finding's live issue state from GitHub. If GitHub is unreachable the saved run is returned as-is."""
    if not data or not any(i.get("status") == "filed" for i in data.get("findings", [])):
        return data
    label = (cfg.get("labels") or {}).get("task", "ai-task")
    try:
        index = deep_scan.cached_issue_index(repo, label)
    except Exception as exc:  # noqa: BLE001 — the panel must still load when GitHub is down
        data["issue_state_error"] = redact_secrets(f"อ่านสถานะ issue ไม่สำเร็จ: {exc}")
        return data
    return deep_scan.with_issue_state(data, index)


def _feature_cycle(repo: str, cfg: dict, repo_dir: Path, budget: deep_scan.CallBudget, engine: str) -> dict:
    """Propose features and file them as ai-plan issues. The agent always runs in the repo clone here."""
    s = feature_gen.settings_for(cfg, repo)
    if not s["enabled"]:
        return {"ran": False, "reason": "ปิดอยู่: เปิดสวิตช์ 'เปิดใช้' ของ repo นี้ในแผงแผนฟีเจอร์ก่อน"}
    gaps = feature_gen.gap_lines(deep_scan.load_run(runner.STATE, repo)) if s["scan_gaps"] else []
    roadmap = feature_gen.read_roadmap(repo_dir) if s["roadmap"] else ""
    if not (s["whole_repo"] or gaps or roadmap):
        return {"ran": False, "reason": "ไม่มีแหล่งไอเดียที่เปิดอยู่"}
    call_repo = budget.wrap(lambda prompt: _scan_agent_call(prompt, cfg, engine, repo_dir))
    try:
        proposals = feature_gen.propose(repo, cfg, repo_dir, call_repo, gaps=gaps, roadmap=roadmap)
    except Exception as exc:  # noqa: BLE001 — bad model output is reported, not hidden as "0 plans"
        result = {"ran": True, "proposed": 0, "created": 0, "skipped": 0, "urls": [],
                  "errors": [redact_secrets(f"เสนอฟีเจอร์ไม่สำเร็จ: {exc}")]}
        feature_gen.save_last(runner.STATE, repo, result)
        return result
    auto_n = s["auto_approve_max"] if s["approval_mode"] == "auto" else 0
    filed = feature_gen.file_plans(repo, proposals, auto_approve=auto_n)
    result = {"ran": True, "proposed": len(proposals), **filed}
    if not proposals:
        result["reason"] = "โมเดลไม่เสนอแผนที่ใช้ได้ (ไม่มีรายการผ่านการตรวจรูปแบบ)"
    feature_gen.save_last(runner.STATE, repo, result)
    return result


def _api_feature_gen_propose(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    engine = (body.get("engine") or "").strip()
    if engine not in deep_scan_engines(cfg):
        raise DeepScanHttpError(400, "ไม่พบ engine ที่ใช้สแกนได้")
    repo_dir = Path(multi_repo.find_or_prepare_repo_dir(repo, cfg))
    budget = deep_scan.CallBudget(deep_scan.call_budget_limit(cfg))
    try:
        return {"ok": True, **_feature_cycle(repo, cfg, repo_dir, budget, engine), "calls_used": budget.used}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": redact_secrets(f"เสนอฟีเจอร์ไม่สำเร็จ: {exc}")}


def _api_feature_gen_view(repo: str, cfg: dict) -> dict:
    """Settings plus open ai-plan issues (approved ones flagged). A GitHub failure still returns the settings."""
    view = {"ok": True, "repo": repo, "settings": feature_gen.settings_for(cfg, repo),
            "merge_level": feature_gen.merge_level_for(cfg, repo), "plans": [], "approved": [],
            "last": feature_gen.load_last(runner.STATE, repo)}
    try:
        plans = json.loads(runner.gh("issue", "list", "-R", repo, "--label", feature_gen.PLAN_LABEL,
                                     "--state", "open", "--limit", "100", "--json", "number,title,url") or "[]")
        approved = {i.get("number") for i in feature_gen.approved_plan_issues(repo)}
    except Exception as exc:  # noqa: BLE001
        view["error"] = redact_secrets(f"อ่านแผนจาก GitHub ไม่สำเร็จ: {exc}")
        return view
    view["plans"] = [{**p, "approved": p.get("number") in approved} for p in plans]
    return view


def _update_repo_entry(repo: str, updates: dict) -> None:
    """Write fields of one repo entry in config.yaml (comments kept by ruamel via yaml_io)."""
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        raw = yaml_io.load_text(cfg_path.read_text(encoding="utf-8")) or {}
        entry = next((r for r in raw.get("repos") or [] if isinstance(r, dict) and r.get("name") == repo), None)
        if entry is None:
            raise ValueError("ไม่พบ repo ใน config")
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(entry.get(key), dict):
                entry[key].update(value)
            else:
                entry[key] = value
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")


def _api_feature_gen_settings(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    flags: dict = {}
    for key in ("enabled", "whole_repo", "roadmap", "scan_gaps"):
        if key in body:
            if not isinstance(body[key], bool):
                raise ValueError(f"{key} ต้องเป็น true หรือ false")
            flags[key] = body[key]
    if "max_proposals" in body:
        mp = body["max_proposals"]
        if isinstance(mp, bool) or not isinstance(mp, int) or not 1 <= mp <= feature_gen.MAX_PROPOSALS_PER_REPO:
            raise ValueError(f"max_proposals ต้องเป็นจำนวนเต็ม 1–{feature_gen.MAX_PROPOSALS_PER_REPO}")
        flags["max_proposals"] = mp
    if "approval_mode" in body:
        if body["approval_mode"] not in feature_gen.APPROVAL_MODES:
            raise ValueError("approval_mode ต้องเป็น manual หรือ auto")
        flags["approval_mode"] = body["approval_mode"]
    if "auto_approve_max" in body:
        am = body["auto_approve_max"]
        if isinstance(am, bool) or not isinstance(am, int) or not 1 <= am <= feature_gen.MAX_PROPOSALS_PER_REPO:
            raise ValueError(f"auto_approve_max ต้องเป็นจำนวนเต็ม 1–{feature_gen.MAX_PROPOSALS_PER_REPO}")
        flags["auto_approve_max"] = am
    updates: dict = {}
    if flags:
        updates["feature_gen"] = flags
    if "merge_level" in body:
        level = body["merge_level"]
        if level is not None and level not in feature_gen.MERGE_LEVELS:
            raise ValueError("merge_level ต้องเป็น 1, 2, 3 หรือ null")
        updates["merge_level"] = level
    if not updates:
        raise ValueError("ไม่มีค่าที่จะบันทึก")
    _update_repo_entry(repo, updates)
    fresh = load_cfg()
    return {"ok": True, "repo": repo, "settings": feature_gen.settings_for(fresh, repo),
            "merge_level": feature_gen.merge_level_for(fresh, repo)}


def _api_feature_gen_approve(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    number = body.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError("number ต้องเป็นหมายเลข issue")
    runner.gh("label", "create", feature_gen.APPROVED_LABEL, "-R", repo, "--color", "1D76DB", "--force", check=False)
    runner.gh("issue", "edit", str(number), "-R", repo, "--add-label", feature_gen.APPROVED_LABEL)
    summary = feature_gen.enqueue_approved(repo, cfg)
    return {"ok": True, "number": number, "enqueue": summary,
            "message": f"อนุมัติ issue #{number} แล้ว: สร้างงาน {summary.get('enqueued', 0)} รายการ"}


def _api_deep_scan_file(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    fid = body.get("finding_id")
    data = deep_scan.load_run(runner.STATE, repo)
    item = next((i for i in (data or {}).get("findings", []) if i.get("id") == fid), None)
    if item is None:
        raise DeepScanHttpError(404, "ไม่พบ finding")
    label = (cfg.get("labels") or {}).get("task", "ai-task")
    try:
        finding = deep_scan.Finding(**{k: item[k] for k in
                                       ("category", "title", "path", "line", "evidence", "suggested_fix")})
        bodies = deep_scan.fetch_issue_bodies(repo, label)  # fresh on every click; open + closed (no re-file)
        url = deep_scan.create_finding_issue(repo, finding, bodies, label=label)
    except Exception as exc:
        return {"ok": False, "error": redact_secrets(f"สร้าง issue ไม่สำเร็จ: {exc}")}
    try:
        deep_scan.forget_issue_index(repo, label)
        deep_scan.set_status(runner.STATE, repo, fid, "filed", issue_url=url)
    except Exception:  # M14: KeyError หรือ I/O error ระหว่างบันทึก — issue ถูกสร้างแล้ว
        return {"ok": True, "url": url, "status": "new",
                "warning": "สร้าง issue แล้วแต่บันทึกสถานะไม่สำเร็จ"}
    if url is None:
        return {"ok": True, "skipped": True}
    return {"ok": True, "url": url, "status": "filed"}


def _api_deep_scan_dismiss(body: dict, cfg: dict) -> dict:
    repo = _deep_scan_repo(body, cfg)
    try:
        deep_scan.set_status(runner.STATE, repo, body.get("finding_id"), "dismissed")
    except KeyError:
        raise DeepScanHttpError(404, "ไม่พบ finding")
    return {"ok": True, "status": "dismissed"}


def _bootstrap_result_payload(res) -> dict:
    """Shape a CiBootstrapResult for the GUI: ok flag, one-line message, and the step list."""
    ok = res.status in ("pr_opened", "issue_opened", "dry_run", "skipped")
    return {
        "ok": ok,
        "status": res.status,
        "url": res.url,
        "message": res.message if not res.url else f"{res.message}: {res.url}",
        "steps": [{"name": s.name, "status": s.status, "detail": s.detail} for s in res.steps],
        "workflow": res.workflow,
    }


def _api_repos_bootstrap_ci(body: dict, cfg: dict) -> dict:
    name = (body.get("name") or body.get("repo") or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อ repo")
    name = _require_repo(name, cfg)
    rcfg = multi_repo.ensure_repo_config(cfg, name)
    res = ci_bootstrap.bootstrap_ci(name, rcfg, cfg)
    _cache.clear()
    return _bootstrap_result_payload(res)


def _api_repos_bootstrap_ci_plan(body: dict, cfg: dict) -> dict:
    """Draft only: runs the preflight and generates the workflow, but pushes and opens nothing."""
    name = (body.get("name") or body.get("repo") or "").strip()
    if not name:
        raise ValueError("ต้องระบุชื่อ repo")
    name = _require_repo(name, cfg)
    rcfg = multi_repo.ensure_repo_config(cfg, name)
    return _bootstrap_result_payload(ci_bootstrap.plan_ci_bootstrap(name, rcfg, cfg))


def _api_keys(body: dict, cfg: dict) -> dict:
    keys_data = body.get("keys", {})
    if not isinstance(keys_data, dict):
        raise ValueError("รูปแบบข้อมูล keys ไม่ถูกต้อง (ต้องเป็น object)")
    updated = keys.save_dotenv(keys_data)
    return {"ok": True, "updated": updated}


def _api_key_reset(body: dict, cfg: dict) -> dict:
    key_id = body.get("key_id")
    engine_name = body.get("engine")
    if not key_id and not engine_name:
        raise ValueError("ต้องระบุ key_id หรือ engine เพื่อล้างคูลดาวน์")
    keys.reset_key_cooldown(key_id=key_id, engine_name=engine_name)
    return {"ok": True}


def _api_key_delete(body: dict, cfg: dict) -> dict:
    key = body.get("key")
    if not key:
        raise ValueError("ต้องระบุ key ที่ต้องการลบ")
    deleted = keys.delete_dotenv_key(key)
    return {"ok": True, "deleted": key, "found": deleted}


def _api_models(body: dict, cfg: dict) -> dict:
    provider = body.get("provider", "")
    key = body.get("key", "")
    fetch_id, api_key = gui_patches.resolve_provider_and_key_for_models(provider, key or None, cfg)
    models = keys.fetch_provider_models(fetch_id, api_key=api_key)
    return {"ok": True, "provider": provider, "models": models}


def _api_engine_model(body: dict, cfg: dict) -> dict:
    name = body.get("name")
    model = body.get("model")
    if not name or not model:
        raise ValueError("ต้องระบุชื่อ engine และ model")
    ok = keys.update_engine_model(name, model, **_engine_cfg_kw())
    return {"ok": ok, "name": name, "model": model}


def _api_key_favorite(body: dict, cfg: dict) -> dict:
    key = body.get("key")
    if not key:
        raise ValueError("ต้องระบุชื่อ key หรือ engine")
    fav = keys.toggle_favorite_key(key, is_favorite=body.get("favorite"))
    return {"ok": True, "key": key, "favorite": fav}


def _api_key_roles(body: dict, cfg: dict) -> dict:
    key = body.get("key")
    roles = body.get("roles")
    if not key or not isinstance(roles, list):
        raise ValueError("ต้องระบุชื่อ key และ roles (list)")
    updated_roles = keys.set_key_roles(key, roles)
    return {"ok": True, "key": key, "roles": updated_roles}


def _api_engine_create(body: dict, cfg: dict) -> dict:
    ok = keys.add_engine(body, **_engine_cfg_kw())
    return {"ok": ok, "engine": body.get("name")}


def _api_provider_add(body: dict, cfg: dict) -> dict:
    """เพิ่มผู้ให้บริการใหม่ (URL + คีย์ + โมเดล) ในขั้นตอนเดียว. คีย์ไม่ถูกส่งกลับ"""
    result = providers.add_provider(
        pid=str(body.get("id", "")), display_name=str(body.get("display_name", "")),
        base_url=str(body.get("base_url", "")), api_key=str(body.get("api_key", "")),
        model=str(body.get("model", "")), timeout_minutes=int(body.get("timeout_minutes", 30) or 30),
        trains_on_data=bool(body.get("trains_on_data", False)), enabled=bool(body.get("enabled", True)),
        **_engine_cfg_kw())
    return {"ok": True, **result}


def _api_byop_disconnect(body: dict, cfg: dict) -> dict:
    return byop.disconnect()


def _byop_pool_view() -> dict:
    """คลังคีย์ BYOP (mask แล้ว) + โมเดลตามบทบาท. ไม่มีค่าคีย์ดิบ."""
    return {
        "ok": True,
        "keys": byop_store.list_keys(),
        "models": byop_store.list_models(),
        "roles": sorted(keys.VALID_ROLES),
        "default_model": byop.DEFAULT_MODEL,
    }


def _byop_catalog_ids() -> set[str]:
    """รายการโมเดลจริงของ Pollinations (ใช้คีย์ที่เลือกอยู่ถ้ามี). ดึงไม่ได้ให้ raise ValueError."""
    names = keys.fetch_provider_models("opencode-pollinations", api_key=byop_store.active_key_value())
    return {str(n) for n in names if str(n).startswith(byop_store.PROVIDER_ID + "/")}


def _api_byop_models_catalog(body: dict, cfg: dict) -> dict:
    return {"ok": True, "models": sorted(_byop_catalog_ids())}


def _api_byop_models_roles(body: dict, cfg: dict) -> dict:
    result = byop_store.set_roles(str(body.get("id") or ""), list(body.get("roles") or []))
    return {"ok": True, "model": result}


def _api_byop_models_promote(body: dict, cfg: dict) -> dict:
    return {"ok": True, "models": byop_store.promote_model(str(body.get("id") or ""))}


def _api_byop_models_test(body: dict, cfg: dict) -> dict:
    return {"ok": True, "result": byop_store.check_model(str(body.get("id") or ""))}


def _api_byop_pool(body: dict, cfg: dict) -> dict:
    return _byop_pool_view()


def _api_byop_keys_select(body: dict, cfg: dict) -> dict:
    selected = byop_store.set_selected([str(n) for n in (body.get("keys") or [])])
    return {"ok": True, "selected": selected}


def _api_byop_keys_remove(body: dict, cfg: dict) -> dict:
    byop_store.remove_key(str(body.get("key") or ""))
    return {"ok": True}


def _api_byop_keys_scan(body: dict, cfg: dict) -> dict:
    return {"ok": True, "results": byop_store.scan_keys()}


def _api_byop_models_add(body: dict, cfg: dict) -> dict:
    # ตรวจกับรายการจริงของ Pollinations ก่อนบันทึก (ไม่ให้ชื่อโมเดลพิมพ์ผิดค้างใน state)
    model = byop_store.add_model(str(body.get("id") or ""), list(body.get("roles") or []),
                                 known_ids=_byop_catalog_ids())
    return {"ok": True, "model": model}


def _api_byop_models_remove(body: dict, cfg: dict) -> dict:
    return {"ok": True, "removed": byop_store.remove_model(str(body.get("id") or ""))}


_ENGINE_UPDATE_FIELDS = frozenset({
    "name", "provider", "command", "model", "timeout_minutes", "path",
    "trains_on_data", "enabled", "api_keys",
})


def _api_engine_update(body: dict, cfg: dict) -> dict:
    name = body.get("name")
    updates = body.get("updates", {})
    if not name:
        raise ValueError("ต้องระบุชื่อ engine ที่ต้องการแก้ไข")
    if not isinstance(updates, dict):
        raise ValueError("updates ต้องเป็น object")
    unknown = sorted(set(updates) - _ENGINE_UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"ไม่อนุญาตให้แก้ฟิลด์: {', '.join(unknown)}")
    ok = keys.update_engine(name, updates, **_engine_cfg_kw())
    return {"ok": ok, "name": name}


def _api_engine_delete(body: dict, cfg: dict) -> dict:
    name = body.get("name")
    if not name:
        raise ValueError("ต้องระบุชื่อ engine ที่ต้องการลบ")
    ok = keys.delete_engine(name, **_engine_cfg_kw())
    return {"ok": ok, "deleted": name}


def _api_engine_reorder(body: dict, cfg: dict) -> dict:
    order = body.get("order")
    if not isinstance(order, list):
        raise ValueError("รูปแบบ order ต้องเป็น list ของชื่อ engine")
    ok = keys.reorder_engines(order, **_engine_cfg_kw())
    return {"ok": ok, "order": order}


def _api_parallel_active_slot(body: dict, cfg: dict) -> dict:
    """ตั้งโหมดทีละช่อง: slot 1/2/3 = รันเฉพาะช่องนั้น, null/"all" = รันทุกช่อง."""
    raw_slot = body.get("slot")
    if raw_slot in (None, "", "all"):
        new_value = None
    else:
        try:
            new_value = int(raw_slot)
        except (TypeError, ValueError):
            raise ValueError("slot ต้องเป็น 1, 2, 3 หรือ null")
        if new_value not in (1, 2, 3):
            raise ValueError("slot ต้องเป็น 1, 2, 3 หรือ null")
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        parallel_cfg = raw.setdefault("parallel", {})
        parallel_cfg["active_slot"] = new_value
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
    msg = (f"ตั้งโหมดทีละช่อง: รันเฉพาะ Slot {new_value}" if new_value
           else "ตั้งกลับเป็นรันทุกช่องแบบขนาน")
    return {"ok": True, "active_slot": new_value, "message": msg}


def _api_keys_ping(body: dict, cfg: dict) -> dict:
    """ปิงคีย์: ระบุ engine + key_id เพื่อปิงทีละคีย์, หรือระบุ engine เพียวๆ เพื่อปิงทั้ง engine."""
    engine_name = str(body.get("engine", "")).strip()
    if not engine_name:
        raise ValueError("ต้องระบุ engine")
    eng = next((e for e in runner.get_engines(cfg) if runner.key_engine_name(e) == engine_name), None)
    if eng is None:
        raise ValueError(f"ไม่พบ engine: {engine_name}")
    only_key = str(body.get("key_id") or "").strip() or None
    timeout = int(body.get("timeout", key_ping.DEFAULT_PING_TIMEOUT))
    results = key_ping.ping_engine_keys(eng, only_key_id=only_key, timeout=timeout)
    if only_key and not results:
        raise ValueError("ไม่พบคีย์นี้ใน engine (หรือคีย์ยังไม่ได้ตั้งค่า)")
    ok_count = sum(1 for r in results if r["ok"])
    return {"ok": True, "engine": engine_name, "results": results,
            "message": f"ปิงแล้ว {len(results)} คีย์ — ใช้ได้ {ok_count}, ใช้ไม่ได้ {len(results) - ok_count}"}


def _api_wake_personas(body: dict, cfg: dict) -> dict:
    raw_history = runner.load_history()
    removed = 0
    while raw_history and raw_history[-1].get("kind") == "persona" and raw_history[-1].get("state") == "NO_ACTION":
        raw_history.pop()
        removed += 1
    if removed > 0:
        runner.save_history(raw_history)
    _cache.clear()
    return {"ok": True, "message": f"ปลุก Persona สำเร็จ (ล้างสถานะพัก {removed} รายการ) ระบบจะเริ่มงานในรอบถัดไป"}


def _api_repo_run_command(body: dict, cfg: dict) -> dict:
    repo = _require_repo(body.get("repo"), cfg)
    return multi_repo.run_repo_verification(repo, body.get("check_type", "test"), cfg)


def _api_repo_dispatch_task(body: dict, cfg: dict) -> dict:
    repo = _require_repo(body.get("repo"), cfg)
    return multi_repo.dispatch_studio_coding_task(
        repo,
        prompt=body.get("prompt", ""),
        persona=body.get("persona", "bolt"),
        mode=body.get("mode", "surgical"),
        engine=body.get("engine", "opencode"),
        sandbox=bool(body.get("sandbox", False)),
        cfg=cfg,
    )


def _api_repo_sync(body: dict, cfg: dict) -> dict:
    repo = _require_repo(body.get("repo"), cfg)
    return multi_repo.sync_repo(repo, cfg)


def _api_graceful_drain(body: dict, cfg: dict) -> dict:
    if body.get("clear"):
        autonomous_upgrades.clear_graceful_drain(runner.STATE)
        return {"ok": True, "draining": False, "message": "ยกเลิกโหมด Graceful Drain แล้ว"}
    restart_args = body.get("restart_args")
    if restart_args is not None and not isinstance(restart_args, list):
        raise ValueError("restart_args ต้องเป็น list ของ string")
    clean_args = [str(a) for a in restart_args] if restart_args else None
    AUTO.disable()
    state = autonomous_upgrades.request_graceful_drain(restart_args=clean_args, state_dir=runner.STATE)
    return {"ok": True, **state, "message": "เปิดโหมด Graceful Drain — รอให้ช่องที่กำลังทำงานเสร็จก่อนหยุด"}


_SLICER_PREVIEW_SUFFIXES = {".py", ".js", ".html", ".css", ".md", ".yaml", ".yml", ".txt", ".json"}


def _api_context_slicer_preview(body: dict, cfg: dict) -> dict:
    """Read-only preview of what the Gate 1/2 Context Slicer would send for one file.

    Never writes anything. Paths are limited to files inside the project root, and
    `.env*`, `state/` and `.git/` are refused so secrets and runtime data cannot be previewed.
    """
    rel = str(body.get("path") or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or ":" in rel or ".." in rel.split("/"):
        raise ValueError("path ต้องเป็นพาธสัมพัทธ์ภายในโปรเจกต์")
    root = runner.ROOT.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("ไม่พบไฟล์ หรือไฟล์อยู่นอกโปรเจกต์")
    parts = target.relative_to(root).parts
    if target.name.startswith(".env") or parts[0] in {"state", ".git"}:
        raise ValueError("ไฟล์นี้ไม่อนุญาตให้ดูตัวอย่าง")
    if target.suffix.lower() not in _SLICER_PREVIEW_SUFFIXES:
        raise ValueError("รองรับเฉพาะไฟล์ข้อความของโค้ด/เอกสาร")
    if target.stat().st_size > 2_000_000:
        raise ValueError("ไฟล์ใหญ่เกิน 2 MB")
    reference = str(body.get("reference") or "")[:20_000]
    content = target.read_text(encoding="utf-8", errors="replace")
    total = len(content.splitlines())
    cited = context_slicer.extract_cited_lines(reference, total)
    windows = context_slicer.merge_line_windows(cited, total, radius=80)
    sliced = context_slicer.slice_file_for_gate(target, reference)
    # Human-readable preview: a few lines around each cited line (or the file head when nothing is cited).
    lines = content.splitlines()
    if cited:
        chunks = []
        for line_no in cited[:5]:
            start, end = max(1, line_no - 6), min(total, line_no + 6)
            body_lines = "\n".join(f"{ln:5d} | {lines[ln - 1]}" for ln in range(start, end + 1))
            chunks.append(f"## Around L{line_no}\n{body_lines}")
        preview_src = "\n\n".join(chunks)
    else:
        preview_src = "\n".join(f"{ln:5d} | {lines[ln - 1]}" for ln in range(1, min(total, 60) + 1))
    return {
        "ok": True,
        "path": target.relative_to(root).as_posix(),
        "total_lines": total,
        "chars": len(content),
        "cited_lines": cited[:200],
        "windows": [[start, end] for start, end in windows[:50]],
        "sliced_chars": len(sliced),
        "preview": preview_src[:4000],
        "truncated": len(preview_src) > 4000,
    }


def _api_doctor_run(body: dict, cfg: dict) -> dict:
    return doctor.run_doctor_checks(root=runner.ROOT, state_dir=runner.STATE)


def _api_playground_reset(body: dict, cfg: dict) -> dict:
    return playground.reset_or_create_playground()


def _api_mcp_call_preview(body: dict, cfg: dict) -> dict:
    method = str(body.get("method") or "tools/list")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    rpc_resp = mcp_server.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return {"ok": True, "rpc": rpc_resp}


def _api_safe_revert_plan(body: dict, cfg: dict) -> dict:
    plan = autonomous_upgrades.build_safe_revert_plan(
        str(body.get("repo") or ""),
        str(body.get("merge_sha") or ""),
        body.get("pr_number"),
        cfg,
    )
    return {"ok": True, **plan}


def _api_evaluation_toggle(body: dict, cfg: dict) -> dict:
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        eval_cfg = raw.setdefault("evaluation", {})
        current = eval_cfg.get("enabled", True)
        new_state = bool(body["enabled"]) if "enabled" in body else not current
        eval_cfg["enabled"] = new_state
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        return {
            "ok": True,
            "enabled": new_state,
            "message": f"{'เปิด' if new_state else 'ปิด'}ระบบประเมินผล (Agentic Evaluation) เรียบร้อยแล้ว",
        }


def _forget_repo_status(repo_name: str) -> None:
    """ล้างแคชสถานะรีโปหลังแก้ config ไม่งั้นหน้าเว็บจะเห็นค่าเก่าจนกว่าแคชจะหมดอายุ (20 วินาที)."""
    _cache.pop("repo:" + repo_name, None)


def _api_ci_toggle(body: dict, cfg: dict) -> dict:
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        repo_name = body.get("repo")
        if repo_name:
            repos = raw.setdefault("repos", [])
            matched = next((r for r in repos if r.get("name") == repo_name), None)
            if not matched:
                raise ValueError(f"ไม่พบ repo {repo_name} ในการตั้งค่า")
            r_ci = matched.setdefault("ci", {})
            current = r_ci.get("allow_no_ci", raw.get("ci", {}).get("allow_no_ci", True))
            new_state = bool(body["allow_no_ci"]) if "allow_no_ci" in body else not current
            r_ci["allow_no_ci"] = new_state
            keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
            _forget_repo_status(repo_name)
            msg = f"{'เปิดให้ทำงานแม้ไม่มี CI (allow_no_ci=true)' if new_state else 'บังคับต้องมี CI เท่านั้น (allow_no_ci=false)'} สำหรับ {repo_name}"
            return {"ok": True, "allow_no_ci": new_state, "repo": repo_name, "message": msg}
        else:
            global_ci = raw.setdefault("ci", {})
            current = global_ci.get("allow_no_ci", True)
            new_state = bool(body["allow_no_ci"]) if "allow_no_ci" in body else not current
            global_ci["allow_no_ci"] = new_state
            keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
            msg = f"{'เปิดให้ทำงานแม้ไม่มี CI (allow_no_ci=true)' if new_state else 'บังคับต้องมี CI checks เท่านั้น (allow_no_ci=false)'} (Global)"
            return {"ok": True, "allow_no_ci": new_state, "message": msg}


def _api_ci_bootstrap_toggle(body: dict, cfg: dict) -> dict:
    """เปิด/ปิด auto_bootstrap_ci ของรีโปหนึ่ง (ค่าเริ่มต้นปิด). ไม่มี repo ใน body = ปฏิเสธ."""
    repo_name = body.get("repo")
    if not repo_name:
        raise ValueError("ต้องระบุ repo")
    if "auto_bootstrap_ci" not in body:
        raise ValueError("ต้องระบุ auto_bootstrap_ci เป็น true หรือ false")
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        raw = yaml_io.load_text(cfg_path.read_text(encoding="utf-8")) or {}
        repos = raw.setdefault("repos", [])
        matched = next((r for r in repos if r.get("name") == repo_name), None)
        if not matched:
            raise ValueError(f"ไม่พบ repo {repo_name} ในการตั้งค่า")
        new_state = bool(body["auto_bootstrap_ci"])
        matched.setdefault("ci", {})["auto_bootstrap_ci"] = new_state
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        _forget_repo_status(repo_name)
    msg = (f"เปิดการเปิด PR CI อัตโนมัติสำหรับ {repo_name} แล้ว" if new_state
           else f"ปิดการเปิด PR CI อัตโนมัติสำหรับ {repo_name} แล้ว")
    return {"ok": True, "auto_bootstrap_ci": new_state, "repo": repo_name, "message": msg}


MERGE_MODES = {
    "review-all": "รอคนรีวิวและ merge เอง (ระบบไม่ merge ให้)",
    "small-only": "merge อัตโนมัติเฉพาะ PR เล็ก ที่เหลือรอคนรีวิว",
    "merge-all": "merge อัตโนมัติเมื่อ CI ผ่าน",
}


def _api_merge_mode(body: dict, cfg: dict) -> dict:
    mode = body.get("mode")
    if mode not in MERGE_MODES:
        raise ValueError("merge_mode ต้องเป็น review-all, small-only หรือ merge-all")
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        raw = yaml_io.load_text(cfg_path.read_text(encoding="utf-8")) or {}
        previous = raw.get("merge_mode")
        raw["merge_mode"] = mode
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
    return {"ok": True, "merge_mode": mode, "previous": previous,
            "message": f"ตั้ง merge_mode = {mode}: {MERGE_MODES[mode]}"}


def _auto_issue_view(cfg: dict) -> dict:
    return {"ok": True, **deep_scan.auto_issue_settings(cfg)}


def _api_auto_issue_get(body: dict, cfg: dict) -> dict:
    return _auto_issue_view(cfg)


def _api_auto_issue_set(body: dict, cfg: dict) -> dict:
    """Partial update of config `auto_issue`; invalid values are rejected before anything is written."""
    updates: dict = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise ValueError("enabled ต้องเป็น true หรือ false")
        updates["enabled"] = body["enabled"]
    if "trigger" in body:
        if body["trigger"] not in deep_scan.AUTO_TRIGGERS:
            raise ValueError("trigger ต้องเป็น after_scan หรือ manual")
        updates["trigger"] = body["trigger"]
    if "min_severity" in body:
        if body["min_severity"] not in deep_scan.SEVERITIES:
            raise ValueError("min_severity ต้องเป็น high, medium หรือ low")
        updates["min_severity"] = body["min_severity"]
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        raw = yaml_io.load_text(cfg_path.read_text(encoding="utf-8")) or {}
        section = raw.get("auto_issue")
        if not isinstance(section, dict):
            section = {}
        section.update(updates)
        section.setdefault("enabled", False)
        section.setdefault("trigger", "after_scan")
        section.setdefault("min_severity", "low")
        raw["auto_issue"] = section
        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
    view = _auto_issue_view({"auto_issue": section})
    state = "เปิด" if view["enabled"] else "ปิด"
    return {**view, "message": f"{state}การสร้าง issue อัตโนมัติหลังสแกนลึก (ความรุนแรงขั้นต่ำ: {view['min_severity']})"}


def _api_slots_assign(body: dict, cfg: dict) -> dict:
    cfg_path = config_path()
    with keys.cfg_file_lock(cfg_path):
        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        parallel_cfg = raw.setdefault("parallel", {})
        assignments = parallel_cfg.setdefault("assignments", {})

        slot_id = int(body.get("slot_id", 2))
        slot_key = f"slot_{slot_id}"
        persona = body.get("persona")
        repo = body.get("repo")

        if persona or repo:
            slot_data = assignments.setdefault(slot_key, {})
            if persona is not None:
                if persona == "" or persona.lower() == "auto":
                    slot_data.pop("persona", None)
                else:
                    slot_data["persona"] = persona.lower()
            if repo is not None:
                if repo == "" or repo.lower() == "auto":
                    slot_data.pop("repo", None)
                else:
                    slot_data["repo"] = _require_repo(repo, cfg)
            if not slot_data:
                assignments.pop(slot_key, None)
        else:
            assignments.pop(slot_key, None)

        keys.atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        return {
            "ok": True,
            "assignments": assignments,
            "message": f"อัปเดตการมอบหมายงาน Slot {slot_id} เรียบร้อยแล้ว",
        }


def _api_doctor_run(body: dict, cfg: dict) -> dict:
    return {"ok": True, **doctor.run_doctor_checks()}


def _api_playground_reset(body: dict, cfg: dict) -> dict:
    return {"ok": True, **playground.reset_or_create_playground()}


def _api_mcp_call_preview(body: dict, cfg: dict) -> dict:
    from . import mcp_server  # lazy: mcp_server imports gui

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": str(body.get("method") or "tools/call"),
        "params": body.get("params") or {},
    }
    return {"ok": True, "rpc": mcp_server.handle_rpc(req)}


def _api_metrics_view(cfg: dict, by: str = "engine") -> dict:
    if by not in ("engine", "kind"):
        raise ValueError("by ต้องเป็น engine หรือ kind")
    hist = runner.load_history()
    engs = runner.get_engines(cfg)
    return {
        "ok": True,
        "by": by,
        "summary": metrics.summarize(hist, by=by),
        "routed_bugfix": [e.get("name") for e in routing.order_engines(engs, hist, "bugfix")],
    }


def _byop_page(message: str, *, ok: bool) -> str:
    """หน้าสั้นหลัง callback. ข้อความถูก escape และไม่มีค่าคีย์ใด ๆ."""
    from html import escape
    color = "#2e7d32" if ok else "#c62828"
    return (
        '<!doctype html><html lang="th"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="refresh" content="4;url=/"><title>Pollinations BYOP</title></head>'
        '<body style="font-family:sans-serif;padding:24px">'
        f'<h2 style="color:{color}">{escape(message)}</h2>'
        '<p>กำลังกลับไปยังหน้าหลัก... <a href="/">กลับหน้าหลัก</a></p></body></html>'
    )


_GET_TOKEN_PATHS = frozenset({"/api/repo/file-content", "/api/byop/status", "/api/byop/pool"})  # GET ที่ต้องส่ง X-Token

ROUTES: dict[str, Callable[[dict, dict], dict]] = {
    "/api/slots/assign": _api_slots_assign,
    "/api/run": _api_run,
    "/api/stop": _api_stop,
    "/api/restart": _api_restart,
    "/api/graceful-drain": _api_graceful_drain,
    "/api/context-slicer/preview": _api_context_slicer_preview,
    "/api/doctor": _api_doctor_run,
    "/api/playground/reset": _api_playground_reset,
    "/api/mcp/preview": _api_mcp_call_preview,
    "/api/revert/plan": _api_safe_revert_plan,
    "/api/task": _api_task,
    "/api/pause": _api_pause,
    "/api/engine": _api_engine,
    "/api/repos/add": _api_repos_add,
    "/api/repos/toggle": _api_repos_toggle,
    "/api/repos/delete": _api_repos_delete,
    "/api/repos/remove": _api_repos_delete,
    "/api/repos/scan": _api_repos_scan,
    "/api/repos/bootstrap-ci": _api_repos_bootstrap_ci,
    "/api/repos/bootstrap-ci-plan": _api_repos_bootstrap_ci_plan,
    "/api/todo-scan": _api_todo_scan,
    "/api/deep-scan": _api_deep_scan,
    "/api/deep-scan/file": _api_deep_scan_file,
    "/api/deep-scan/dismiss": _api_deep_scan_dismiss,
    "/api/feature-gen/propose": _api_feature_gen_propose,
    "/api/feature-gen/settings": _api_feature_gen_settings,
    "/api/feature-gen/approve": _api_feature_gen_approve,
    "/api/deep-scan/auto-issue": _api_auto_issue_set,
    "/api/keys": _api_keys,
    "/api/key/reset": _api_key_reset,
    "/api/key/delete": _api_key_delete,
    "/api/models": _api_models,
    "/api/engine-model": _api_engine_model,
    "/api/key/favorite": _api_key_favorite,
    "/api/key/roles": _api_key_roles,
    "/api/engine/create": _api_engine_create,
    "/api/provider/add": _api_provider_add,
    "/api/engine/update": _api_engine_update,
    "/api/engine/delete": _api_engine_delete,
    "/api/engine/reorder": _api_engine_reorder,
    "/api/merge-mode": _api_merge_mode,
    "/api/keys/ping": _api_keys_ping,
    "/api/parallel/active-slot": _api_parallel_active_slot,
    "/api/wake-personas": _api_wake_personas,
    "/api/repo/run-command": _api_repo_run_command,
    "/api/repo/dispatch-task": _api_repo_dispatch_task,
    "/api/repo/sync": _api_repo_sync,
    "/api/evaluation/toggle": _api_evaluation_toggle,
    "/api/ci/toggle": _api_ci_toggle,
    "/api/ci/bootstrap-toggle": _api_ci_bootstrap_toggle,
    "/api/byop/disconnect": _api_byop_disconnect,
    "/api/byop/keys/select": _api_byop_keys_select,
    "/api/byop/keys/remove": _api_byop_keys_remove,
    "/api/byop/keys/scan": _api_byop_keys_scan,
    "/api/byop/models/add": _api_byop_models_add,
    "/api/byop/models/remove": _api_byop_models_remove,
    "/api/byop/models/catalog": _api_byop_models_catalog,
    "/api/byop/models/roles": _api_byop_models_roles,
    "/api/byop/models/promote": _api_byop_models_promote,
    "/api/byop/models/test": _api_byop_models_test,
}


def act(path: str, body: dict) -> dict:
    cfg = load_cfg()
    handler = ROUTES.get(path)
    if handler is None:
        raise LookupError(path)
    return handler(body, cfg)


# ---------------------------------------------------------------- http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):   # keep the console quiet
        pass

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _host_ok(self) -> bool:
        """DNS-rebinding guard: the Host header must name this server exactly (CRIT-01)."""
        return self.headers.get("Host", "") in self._allowed_hosts()

    def _origin_ok(self) -> bool:
        """A browser-sent Origin, when present, must also be this server (CRIT-01)."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _send(self, code: int, payload, ctype="application/json; charset=utf-8") -> None:
        try:
            data = payload if isinstance(payload, bytes) else (
                payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, {"error": "Host ไม่ถูกต้อง"})
        url = urlparse(self.path)
        if url.path == "/api/byop/callback":
            # redirect กลับจาก enter.pollinations.ai เป็น cross-site จึงข้ามการเช็ก Sec-Fetch-Site ได้เฉพาะ path นี้
            # การป้องกันจริงคือ state ที่สร้างฝั่งเซิร์ฟเวอร์ (ใช้ครั้งเดียว) และ PKCE verifier
            return self._byop_callback(parse_qs(url.query))
        # endpoint ที่อ่านข้อมูลจาก repo ต้องมี token ด้วย (กันการอ่านจากสคริปต์ในเครื่องเดียวกันที่ไม่ใช่หน้า UI)
        needs_token = url.path in _GET_TOKEN_PATHS
        ok_sec, sec_err = gui_patches.verify_request_security(self.headers, TOKEN, require_token=needs_token)
        if not ok_sec:
            return self._send(403, {"error": sec_err})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":  # UI หลัก = แบบ B (sidebar)
                html = (STATIC / "index_sidebar.html").read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN)
                if "/static/mission_control.js" not in html:
                    html = html.replace("</body>", '<script src="/static/mission_control.js"></script>\n</body>', 1)
                return self._send(200, html, "text/html; charset=utf-8")
            if url.path == "/classic":  # UI เดิม A เก็บไว้เผื่อย้อนกลับ
                html = (STATIC / "index.html").read_text(encoding="utf-8").replace("{{TOKEN}}", TOKEN)
                if "/static/mission_control.js" not in html:
                    html = html.replace("</body>", '<script src="/static/mission_control.js"></script>\n</body>', 1)
                return self._send(200, html, "text/html; charset=utf-8")
            if url.path.startswith("/static/"):  # เสิร์ฟเฉพาะ .js/.css และกัน path traversal
                asset = (STATIC / url.path[len("/static/"):]).resolve()
                ctype = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}.get(asset.suffix)
                if ctype is None or not asset.is_relative_to(STATIC.resolve()) or not asset.is_file():
                    return self._send(404, {"error": "not found"})
                return self._send(200, asset.read_bytes(), ctype)
            if url.path == "/api/status":
                return self._send(200, status())
            if url.path == "/api/byop/status":
                return self._send(200, byop.status())
            if url.path == "/api/byop/pool":
                return self._send(200, _byop_pool_view())
            if url.path == "/api/doctor":
                return self._send(200, doctor.run_doctor_checks(root=runner.ROOT, state_dir=runner.STATE))
            if url.path == "/api/github/status":
                # อ่านอย่างเดียว: คืนแค่ว่าติดตั้ง gh / ล็อกอินหรือยัง และชื่อบัญชี (ไม่มี token)
                return self._send(200, {"ok": True, **doctor.gh_login_status()})
            if url.path == "/api/metrics":
                group_by = q.get("by", "engine")
                if group_by not in metrics.GROUP_FIELDS:
                    return self._send(400, {"ok": False, "error": f"by ต้องเป็นหนึ่งใน {metrics.GROUP_FIELDS}"})
                return self._send(200, {"ok": True, "by": group_by, "groups": metrics.summarize(runner.load_history(), by=group_by)})
            if url.path == "/api/keys":
                return self._send(200, keys.get_keys_catalog(load_cfg()))
            if url.path == "/api/engines":
                return self._send(200, {"ok": True, "engines": keys.list_engines(**_engine_cfg_kw())})
            if url.path == "/api/engine":
                eng_name = q.get("name", "")
                if not eng_name:
                    return self._send(400, {"ok": False, "error": "ต้องระบุ name"})
                eng = keys.get_engine(eng_name, **_engine_cfg_kw())
                if not eng:
                    return self._send(404, {"ok": False, "error": "ไม่พบ engine"})
                return self._send(200, {"ok": True, "engine": eng})
            if url.path == "/api/favorites":
                return self._send(200, {"ok": True, "favorites": sorted(list(keys.load_favorite_keys()))})
            if url.path == "/api/key-roles":
                return self._send(200, {"ok": True, "roles": keys.load_key_roles()})
            if url.path == "/api/deep-scan/auto-issue":
                return self._send(200, _auto_issue_view(load_cfg()))
            if url.path == "/api/feature-gen":
                cfg = load_cfg()
                return self._send(200, _api_feature_gen_view(_deep_scan_repo(q, cfg), cfg))
            if url.path == "/api/deep-scan/engines":
                return self._send(200, {"ok": True, "engines": deep_scan_engines(load_cfg())})
            if url.path == "/api/deep-scan":
                cfg = load_cfg()
                repo = _deep_scan_repo(q, cfg)
                return self._send(200, _deep_scan_view(repo, cfg, deep_scan.load_run(runner.STATE, repo)))
            if url.path == "/api/models":
                provider = q.get("provider", "")
                if "key" in q:
                    # API key ห้ามอยู่ใน query string (จะไปค้างใน history/log) ให้ใช้ POST /api/models แทน
                    return self._send(400, {"ok": False, "error": "ห้ามส่ง key ผ่าน query string ให้ใช้ POST /api/models"})
                if not provider:
                    return self._send(400, {"ok": False, "error": "ต้องระบุชื่อ provider"})
                fetch_id, api_key = gui_patches.resolve_provider_and_key_for_models(provider, None, load_cfg())
                models = keys.fetch_provider_models(fetch_id, api_key=api_key)
                return self._send(200, {"ok": True, "provider": provider, "models": models})
            if url.path == "/api/diff":
                if "pr" in q and not q.get("repo"):
                    return self._send(400, {"ok": False, "error": "ต้องระบุ repo เมื่อใช้ pr"})
                if "pr" not in q and not q.get("workdir"):
                    return self._send(400, {"ok": False, "error": "ต้องระบุ pr หรือ workdir"})
                try:
                    return self._send(200, diff_for(q), "text/plain; charset=utf-8")
                except PermissionError as exc:
                    return self._send(403, {"ok": False, "error": redact_secrets(str(exc))})
            if url.path == "/api/repos/scan":
                scanned = multi_repo.scan_user_repositories(load_cfg())
                return self._send(200, {"ok": True, "repositories": scanned, "count": len(scanned)})
            if url.path == "/api/repo/workspace":
                repo = q.get("repo", "")
                if not repo:
                    return self._send(400, {"ok": False, "error": "ต้องระบุชื่อ repo"})
                cfg = load_cfg()
                repo = _require_repo(repo, cfg)
                return self._send(200, multi_repo.get_repo_workspace_info(repo, cfg))
            if url.path == "/api/repo/file-content":
                repo = q.get("repo", "")
                fpath = q.get("path", "")
                mode = q.get("mode", "full")
                if not repo or not fpath:
                    return self._send(400, {"ok": False, "error": "ต้องระบุ repo และ path"})
                cfg = load_cfg()
                repo = _require_repo(repo, cfg)
                if gui_patches.is_forbidden_read_path(fpath):
                    return self._send(403, {"ok": False, "error": "ไม่อนุญาตให้อ่านไฟล์ความลับหรือไฟล์ตั้งค่าส่วนตัว"})
                res = multi_repo.get_repo_file_content(repo, fpath, mode=mode, cfg=cfg)
                if isinstance(res.get("content"), str):
                    res["content"] = redact_secrets(res["content"])
                return self._send(200, res)
            if url.path == "/api/slots/assignments":
                cfg = load_cfg()
                assigns = cfg.get("parallel", {}).get("assignments", {})
                return self._send(200, {"ok": True, "assignments": assigns})
            if url.path == "/api/file-locks":
                active_locks = runner.get_active_file_locks()
                return self._send(200, {"ok": True, "locks": active_locks})
            if url.path == "/api/log":
                slot_arg = q.get("slot")
                slot_id = int(slot_arg) if slot_arg and slot_arg.isdigit() else None
                return self._stream_log(slot_id)
            if url.path == "/api/doctor":
                return self._send(200, {"ok": True, **doctor.run_doctor_checks()})
            if url.path == "/api/metrics":
                by = q.get("by", "engine")
                try:
                    return self._send(200, _api_metrics_view(load_cfg(), by=by))
                except ValueError as exc:
                    return self._send(400, {"ok": False, "error": str(exc)})
            self._send(404, {"error": "not found"})
        except DeepScanHttpError as exc:
            self._send(exc.status, {"error": redact_secrets(str(exc))})
        except Exception as exc:
            self._send(500, {"error": redact_secrets(str(exc))})

    def _byop_redirect_uri(self) -> str:
        # เอกสาร BYOP: loopback http://localhost ใช้ได้ทุกพอร์ต จึงลงทะเบียน http://localhost/api/byop/callback ได้ครั้งเดียว
        return f"http://localhost:{self.server.server_address[1]}/api/byop/callback"

    def _byop_callback(self, q: dict) -> None:
        params = {k: v[0] for k, v in q.items()}
        if "error" in params:
            page, code = _byop_page("ยกเลิกการเชื่อมต่อ Pollinations แล้ว", ok=False), 200
        else:
            try:
                byop.connect(code=params.get("code", ""), state=params.get("state", ""),
                             redirect_uri=self._byop_redirect_uri(), **_engine_cfg_kw())
                page, code = _byop_page("เชื่อมต่อ Pollinations (BYOP) สำเร็จ", ok=True), 200
            except byop.ByopError as exc:
                page, code = _byop_page(redact_secrets(str(exc)), ok=False), 400
            except Exception:
                page, code = _byop_page("เกิดข้อผิดพลาดระหว่างเชื่อมต่อ ลองใหม่อีกครั้ง", ok=False), 500
        self._send(code, page, "text/html; charset=utf-8")

    def _drain_small_body(self) -> None:
        """Read a small rejected body so the client's send completes before we answer."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < n <= MAX_BODY_BYTES:
            self.rfile.read(n)

    def do_POST(self) -> None:
        if not self._host_ok():
            self._drain_small_body()
            return self._send(403, {"error": "Host ไม่ถูกต้อง"})
        if not self._origin_ok():
            self._drain_small_body()
            return self._send(403, {"error": "Origin ไม่ถูกต้อง"})
        ok_sec, sec_err = gui_patches.verify_request_security(self.headers, TOKEN, require_token=True)
        if not ok_sec:
            self._drain_small_body()
            return self._send(403, {"error": sec_err})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "Content-Length ไม่ถูกต้อง"})
        if length < 0:
            return self._send(400, {"error": "Content-Length ไม่ถูกต้อง"})
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            return self._send(413, {"error": "ข้อมูลที่ส่งมาใหญ่เกินไป (สูงสุด 1 MB)"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if urlparse(self.path).path == "/api/byop/start":
                # ต้องรู้พอร์ตของเซิร์ฟเวอร์เพื่อสร้าง redirect_uri จึงจัดการที่นี่ ไม่รับ redirect_uri จาก client
                redirect = self._byop_redirect_uri()
                return self._send(200, byop.start_authorization(
                    redirect_uri=redirect, budget=body.get("budget"), expiry=body.get("expiry")))
            if urlparse(self.path).path == "/api/server/shutdown":
                # ปิดทั้ง GUI server: หยุดเอเจนต์และการรีสตาร์ทอัตโนมัติ แล้วปิด HTTP server
                AUTO.disable()
                AGENT.stop()
                self._send(200, {"ok": True, "message": "ปิด GUI server แล้ว"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._send(200, act(urlparse(self.path).path, body))
        except LookupError:
            self._send(404, {"error": "not found"})
        except DeepScanHttpError as exc:
            self._send(exc.status, {"error": redact_secrets(str(exc))})
        except Exception as exc:
            self._send(400, {"error": redact_secrets(str(exc))})

    def _stream_log(self, slot_id: int | None = None) -> None:
        """Server-sent events: replay the buffer, then push new lines as they arrive."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with AGENT.cond:
            seen = AGENT.seq - len(AGENT.lines)
        try:
            while True:
                with AGENT.cond:
                    AGENT.cond.wait_for(lambda: AGENT.seq > seen, timeout=15)
                    new = list(AGENT.lines)[-(AGENT.seq - seen):] if AGENT.seq > seen else []
                    seen = AGENT.seq
                if slot_id is not None:
                    target_tag = f"[Slot {slot_id}]"
                    new = [l for l in new if target_tag in l or l.startswith("▶") or l.startswith("●")]
                payload = "".join(f"data: {json.dumps(l, ensure_ascii=False)}\n\n" for l in new) or ": ping\n\n"
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def _clear_stale_slots() -> None:
    """A fresh GUI process owns no runner, so slot entries left in state/active_slots.json are stale.

    Without this the GUI keeps showing a slot as "กำลังทำงาน" after the runner was killed.
    """
    runner.REGISTRY.clear_all()


def main() -> None:
    import argparse
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="auto-dev-crew-gui")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--auto", action="store_true", help="keep the runner (--loop) going forever, restarting it after it exits")
    p.add_argument("--config", default=None, help="config file to read and edit (default: ROOT/config.yaml)")
    p.add_argument("--keep-slots", action="store_true",
                   help="ไม่ล้างสถานะ slot ตอนเริ่ม (ใช้เมื่อลูป runner เปิด GUI เองเพื่อตรวจ เพราะ runner อื่นอาจกำลังทำงานอยู่)")
    args = p.parse_args()
    if args.config:
        set_config_path(args.config)
    if not args.keep_slots:
        _clear_stale_slots()
    # On Windows SO_REUSEADDR lets a second process bind the same port silently,
    # so a restart while an old instance is alive produced duplicate servers.
    # Keep it on for POSIX (fast restart after TIME_WAIT) and off on Windows.
    ThreadingHTTPServer.allow_reuse_address = sys.platform != "win32"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Auto Dev Crew GUI: {url}  (กด Ctrl+C เพื่อปิด)", flush=True)
    if args.auto:
        AUTO.enable()
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AUTO.disable()
        AGENT.stop()
        server.server_close()


if __name__ == "__main__":
    main()

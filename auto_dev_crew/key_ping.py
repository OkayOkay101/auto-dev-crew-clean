"""ปิง (ping) คีย์ API ของแต่ละ engine เพื่อตรวจว่าคีย์ใช้งานได้จริงหรือไม่.

ใช้ OpenCode CLI ส่งข้อความสั้นๆ 1 ครั้งต่อคีย์ — ไม่มีการแก้ไขไฟล์ในโปรเจกต์
(รันในโฟลเดอร์ temp ที่ว่างเปล่า) และไม่บันทึกค่าคีย์ลงไฟล์ใดๆ
ผลลัพธ์ที่ส่งกลับมีเฉพาะ key_id (ชื่อตัวแปร/แฮช), สถานะ, เวลาที่ใช้ และข้อความ error ที่ถูกปิดบังความลับแล้ว.
"""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .keys import get_opencode_auth_keys, key_id_for, mask_key
from .procs import resolve_cli_exe
from .redact import redact_secrets
from .runner import auth_provider_for, key_engine_name, load_dotenv, resolve_key_value

PING_PROMPT = "Reply with the single word OK and nothing else."
REPO_OPENCODE_CONFIG = Path(__file__).resolve().parent.parent / "opencode.json"
DEFAULT_PING_TIMEOUT = 60
_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "USERPROFILE", "HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA")
_VAR_RE = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")


def _key_env(eng: dict, var_name: str, value: str) -> dict[str, str]:
    """สร้าง environment สำหรับ opencode โดยผูกคีย์นี้เข้ากับตัวแปรที่ provider ใช้.

    value ว่าง = คีย์อยู่ใน auth store ของ opencode เอง → ไม่ผูกอะไรเพิ่ม ให้ opencode ใช้ credential ของมัน
    """
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if os.environ.get(k)}
    if not value:
        return env
    if var_name:
        env[var_name] = value
    # ผู้ให้บริการในทะเบียน (มี provider_id): URL อยู่ใน opencode.json ที่ซิงก์แล้ว จึงไม่เดาจากชื่ออีก
    blob = "" if eng.get("provider_id") else f"{eng.get('name', '')} {eng.get('provider', '')}".lower()
    if "nvidia" in blob:
        env["NVIDIA_API_KEY"] = value
    elif "gemini" in blob or "google" in blob:
        env["GEMINI_API_KEY"] = value
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = value
    elif "pollinations" in blob:
        env["OPENAI_BASE_URL"] = "https://gen.pollinations.ai/v1"
        env["POLLINATIONS_API_KEY"] = value
    elif "deepseek" in blob:
        env["DEEPSEEK_API_KEY"] = value
    if (eng.get("provider") or "").strip().lower() == "opencode":
        env["OPENCODE_API_KEY"] = value
    if REPO_OPENCODE_CONFIG.exists():
        # ping รันใน temp dir จึงไม่เจอ opencode.json ของ repo; ต้องชี้ไปเองเพื่อให้ provider เช่น pollinations ถูกโหลด
        env["OPENCODE_CONFIG"] = str(REPO_OPENCODE_CONFIG)
    return env


def list_engine_key_specs(eng: dict, env_vars: dict[str, str] | None = None) -> list[dict]:
    """คืนรายการคีย์ของ engine: [{key_id, var_name, value, source}] — เฉพาะคีย์ที่มีค่าจริง.

    source = "env" (ค่ามาจาก env/.env) หรือ "opencode_auth" (ค่าอยู่ใน auth store ของ opencode:
    คืน value ว่างเสมอ เพราะ opencode ป้อน credential เอง และเราไม่ต้องอ่านหรือแสดงค่านั้น).
    """
    if env_vars is None:
        env_vars = load_dotenv()
    engine_name = key_engine_name(eng)
    auth_provider = auth_provider_for(eng)
    auth_has_key: bool | None = None
    specs: list[dict] = []
    for raw in eng.get("api_keys") or ([eng["api_key"]] if eng.get("api_key") else []):
        if not raw:
            continue
        raw_str = str(raw).strip()
        value = resolve_key_value(raw_str, env_vars)
        m = _VAR_RE.match(raw_str)
        var_name = m.group(1) if m else ""
        source = "env"
        if not value and var_name:
            # เหมือน runner.get_engine_key_entries / keys.get_keys_catalog: env ชนะเสมอ ไม่มีค่อยดู auth store
            if auth_has_key is None:
                auth_has_key = bool((get_opencode_auth_keys().get(auth_provider) or "").strip())
            if auth_has_key:
                source = "opencode_auth"
        if not value and source != "opencode_auth":
            continue
        specs.append({
            "key_id": key_id_for(engine_name, var_name=var_name, value=value),
            "var_name": var_name,
            "value": value,
            "source": source,
        })
    return specs


def ping_key(eng: dict, spec: dict, timeout: int = DEFAULT_PING_TIMEOUT) -> dict:
    """ปิงคีย์เดียว แล้วคืน {key_id, ok, latency_ms, message}."""
    key_id = spec["key_id"]
    from_auth_store = not spec["value"]
    masked = mask_key(spec["value"]) if spec["value"] else ""
    if eng.get("command") != "opencode":
        return {"key_id": key_id, "ok": False, "latency_ms": 0,
                "message": _i18n.t("ปิงได้เฉพาะ engine ที่ใช้ opencode (engine นี้ใช้ {p0})", p0=eng.get('command'))}
    try:
        # ต้องส่ง path ของ engine: ไม่งั้น PATH จะเจอ shim opencode.CMD ของ npm แล้วถูกปฏิเสธทุกคีย์
        opencode_bin = resolve_cli_exe("opencode", eng.get("path") or None)
    except RuntimeError as exc:
        return {"key_id": key_id, "ok": False, "latency_ms": 0, "message": str(exc)}

    env = _key_env(eng, spec["var_name"], spec["value"])
    model = eng.get("model") or ""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="key-ping-") as work_dir:
            cmd = [opencode_bin, "run"]
            if model:
                cmd += ["-m", model]
            cmd += ["--dir", work_dir, PING_PROMPT]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                cwd=work_dir, env=env, encoding="utf-8", errors="replace",
            )
        latency = int((time.monotonic() - started) * 1000)
        out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
        ok = proc.returncode == 0 and bool(out) and not re.search(r"error|unauthori[sz]ed|invalid|401|403", out, re.I)
        message = _i18n.t("ใช้งานได้") if ok else redact_secrets(out[-300:]) or f"returncode={proc.returncode}"
        if ok:
            message = _i18n.t("ใช้งานได้ (คีย์จาก opencode auth)") if from_auth_store else _i18n.t("ใช้งานได้ (คีย์ {p0})", p0=masked)
        return {"key_id": key_id, "ok": ok, "latency_ms": latency, "message": message}
    except subprocess.TimeoutExpired:
        return {"key_id": key_id, "ok": False, "latency_ms": int(timeout * 1000),
                "message": _i18n.t("หมดเวลา ({p0} วินาที)", p0=timeout)}
    except Exception as exc:  # noqa: BLE001 — รายงานผลให้ UI ไม่ให้ล้มทั้ง request
        return {"key_id": key_id, "ok": False, "latency_ms": 0,
                "message": redact_secrets(_i18n.t("เกิดข้อผิดพลาด: {p0}", p0=exc))}


def ping_engine_keys(eng: dict, only_key_id: str | None = None,
                     timeout: int = DEFAULT_PING_TIMEOUT, env_vars: dict[str, str] | None = None) -> list[dict]:
    """ปิงคีย์ของ engine ทั้งหมด หรือเฉพาะ key_id ที่ระบุ (ทีละคีย์ ตามลำดับ)."""
    specs = list_engine_key_specs(eng, env_vars=env_vars)
    if only_key_id:
        specs = [s for s in specs if s["key_id"] == only_key_id]
    return [ping_key(eng, s, timeout=timeout) for s in specs]

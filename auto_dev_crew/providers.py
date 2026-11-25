"""ทะเบียนผู้ให้บริการ (Provider Registry): URL และชื่อตัวแปรคีย์อยู่ที่เดียว.

ดู docs/superpowers/specs/2026-11-10-provider-registry-design.md
- state/providers.json เก็บ {id: {display_name, base_url, key_var}}
- sync ค่าไปยัง opencode.json (บล็อก provider และ providers) โดยไม่แตะรายการโมเดลที่มีอยู่
- add_provider เพิ่ม engine + คีย์ .env + ทะเบียน + sync ในครั้งเดียว และ rollback engine ถ้าขั้นหลังล้มเหลว
"""

from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from . import keys
from .locks import atomic_write_text, file_lock

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
PROVIDERS_FILE = STATE / "providers.json"
OPENCODE_JSON = ROOT / "opencode.json"

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_ENV_REF_RE = re.compile(r"^\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")


def validate_provider_id(pid: str) -> str:
    pid = (pid or "").strip().lower()
    if not _ID_RE.match(pid):
        raise ValueError("id ผู้ให้บริการต้องเป็นตัวอักษรภาษาอังกฤษพิมพ์เล็ก ตัวเลข หรือ - ยาว 2–31 ตัว เช่น deepseek")
    return pid


def validate_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url or any(c.isspace() for c in url):
        raise ValueError("URL ต้องไม่ว่างและห้ามมีช่องว่าง")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("URL ต้องขึ้นต้นด้วย https:// และมีชื่อโดเมน")
    return url.rstrip("/")


def provider_key_var(pid: str) -> str:
    """ชื่อตัวแปรคีย์มาตรฐานของผู้ให้บริการ เช่น deepseek -> DEEPSEEK_API_KEY_1"""
    return pid.upper().replace("-", "_") + "_API_KEY_1"


def seed_from_opencode(opencode_path: Path) -> dict[str, dict]:
    """อ่านค่าเริ่มต้นจากบล็อก provider ของ opencode.json (ไม่เขียนไฟล์)"""
    if not opencode_path.exists():
        return {}
    data = json.loads(opencode_path.read_text(encoding="utf-8") or "{}")
    out: dict[str, dict] = {}
    for pid, block in (data.get("provider") or {}).items():
        opts = block.get("options") or {}
        base = str(opts.get("baseURL") or "").strip()
        m = _ENV_REF_RE.match(str(opts.get("apiKey") or "").strip())
        if not base or not m:
            continue
        out[pid] = {"display_name": block.get("name", pid), "base_url": base, "key_var": m.group(1)}
    return out


def load_providers(path: Path | None = None, opencode_path: Path | None = None) -> dict[str, dict]:
    path = path or PROVIDERS_FILE
    if not path.exists():
        return seed_from_opencode(opencode_path or OPENCODE_JSON)
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    return dict(data.get("providers") or {})


def save_providers(providers: dict[str, dict], path: Path | None = None) -> None:
    path = path or PROVIDERS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_name(path.name + ".lock")):
        atomic_write_text(path, json.dumps({"providers": providers}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def sync_opencode(providers: dict[str, dict], *, opencode_path: Path | None = None) -> None:
    """ทำให้ baseURL และ apiKey ใน opencode.json ตรงกับทะเบียน โดยคงรายการโมเดลเดิมไว้"""
    opencode_path = opencode_path or OPENCODE_JSON
    data = json.loads(opencode_path.read_text(encoding="utf-8")) if opencode_path.exists() else {}
    data.setdefault("$schema", "https://opencode.ai/config.json")
    provider_block = data.setdefault("provider", {})
    providers_block = data.get("providers")

    for pid, info in providers.items():
        base = info["base_url"]
        env_ref = "{env:%s}" % info["key_var"]
        block = provider_block.setdefault(pid, {})
        block.setdefault("name", info.get("display_name", pid))
        options = block.setdefault("options", {})
        options["baseURL"] = base
        options["apiKey"] = env_ref
        if isinstance(providers_block, dict) and pid in providers_block:
            settings = providers_block[pid].setdefault("settings", {})
            settings["baseURL"] = base

    atomic_write_text(opencode_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_model_to_opencode(pid: str, model: str, *, opencode_path: Path | None = None) -> None:
    """เพิ่มโมเดลเข้าบล็อก provider ของ opencode.json ถ้ายังไม่มี (ไม่ลบรายการเดิม)"""
    opencode_path = opencode_path or OPENCODE_JSON
    data = json.loads(opencode_path.read_text(encoding="utf-8")) if opencode_path.exists() else {}
    block = (data.get("provider") or {}).get(pid)
    if block is None:
        return
    models = block.setdefault("models", {})
    short = model.split("/", 1)[1] if "/" in model else model
    if short not in models:
        models[short] = {"name": short}
    atomic_write_text(opencode_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_provider(*, pid: str, display_name: str, base_url: str, api_key: str, model: str,
                 timeout_minutes: int = 30, trains_on_data: bool = False, enabled: bool = True,
                 providers_path: Path | None = None, opencode_path: Path | None = None,
                 cfg_path: Path | None = None, env_path: Path | None = None) -> dict:
    """เพิ่มผู้ให้บริการใหม่ในขั้นตอนเดียว คืนสรุปที่ไม่มีค่าคีย์"""
    pid = validate_provider_id(pid)
    base_url = validate_base_url(base_url)
    api_key = (api_key or "").strip()
    model = (model or "").strip()
    if not api_key:
        raise ValueError("ต้องระบุ API Key")
    if "/" not in model:
        raise ValueError("โมเดลต้องอยู่ในรูป provider/model เช่น deepseek/deepseek-chat")
    display_name = (display_name or "").strip() or pid

    providers = load_providers(providers_path, opencode_path)
    if pid in providers:
        raise ValueError(f"มีผู้ให้บริการ '{pid}' อยู่แล้ว")
    engine_name = f"opencode-{pid}"
    engine_kw = {"cfg_path": cfg_path} if cfg_path is not None else {}
    if keys.get_engine(engine_name, **engine_kw):
        raise ValueError(f"มี Engine ชื่อ '{engine_name}' อยู่แล้ว")

    key_var = keys.validate_dotenv_key_name(provider_key_var(pid))
    if keys.load_env_file(env_path).get(key_var):
        raise ValueError(f"มีคีย์ {key_var} ใน .env อยู่แล้ว ไม่เขียนทับ")

    engine = {
        "name": engine_name, "provider": display_name, "command": "opencode", "model": model,
        "timeout_minutes": int(timeout_minutes), "trains_on_data": bool(trains_on_data),
        "enabled": bool(enabled), "api_keys": ["${%s}" % key_var], "provider_id": pid,
    }
    keys.add_engine(engine, **engine_kw)
    try:
        keys.save_dotenv({key_var: api_key}, path=env_path)
        providers[pid] = {"display_name": display_name, "base_url": base_url, "key_var": key_var}
        save_providers(providers, providers_path)
        sync_opencode(providers, opencode_path=opencode_path)
        add_model_to_opencode(pid, model, opencode_path=opencode_path)
    except Exception:
        # ย้อนกลับ: ลบ engine และบรรทัดคีย์ที่เพิ่งเขียน (ไม่แตะคีย์ที่มีอยู่ก่อนหน้า เพราะเช็คไว้แล้ว)
        keys.delete_engine(engine_name, **engine_kw)
        keys.delete_dotenv_key(key_var, path=env_path)
        raise
    return {"id": pid, "engine": engine_name, "key_var": key_var, "base_url": base_url, "model": model}

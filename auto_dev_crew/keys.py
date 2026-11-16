"""auto_dev_crew.keys - จัดการ API Keys, Provider Catalog, และ .env สำหรับระบบ GUI

รองรับ:
- Provider Catalog ข้อมูลโควตา ลิมิต และลิงก์ขอคีย์ 30 ผู้ให้บริการฟรีถาวร (งบ 0 บาท)
- อัปเดตและบันทึกคีย์ลง .env อย่างปลอดภัย (Masking, No-leak, Git-ignored)
- ระบบตรวจสอบและล้างสถานะ Cooldown รายคีย์ / ราย Engine
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from . import yaml_io

from .locks import file_lock, locked_json_read, locked_json_write, atomic_write_text, cfg_file_lock

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
ENGINE_STATUS = STATE / "engine_status.json"
KEY_STATUS = STATE / "key_status.json"
FAVORITE_KEYS = STATE / "favorite_keys.json"
KEY_ROLES = STATE / "key_roles.json"
VALID_ROLES = {"coder", "judge", "scan"}

# แคตตาล็อกข้อมูลโควตา ลิงก์ และระดับความสำคัญของผู้ให้บริการฟรีทั้งหมด
PROVIDERS_CATALOG: dict[str, dict] = {
    "opencode": {
        "display_name": "OpenCode",
        "tier": "core",
        "description": "OpenCode CLI - ต้องกรอก API Key",
        "portal_url": "https://opencode.ai",
        "quota_label": "ตามผู้ให้บริการ",
        "rate_limit": "ตามผู้ให้บริการ",
        "keyless": False,
        "default_keys": ["OPENCODE_API_KEY_1"],
    },
    "opencode-nvidia": {
        "display_name": "NVIDIA Build",
        "tier": "core",
        "description": "NVIDIA NIM Inference - โมเดล DeepSeek V4.1 Flash ความเร็วสูง 1,000 เครดิตฟรี/บัญชี",
        "portal_url": "https://build.nvidia.com",
        "quota_label": "1,000 เครดิตฟรี/บัญชี",
        "rate_limit": "40 RPM",
        "keyless": False,
        "default_keys": ["NVIDIA_API_KEY_1", "NVIDIA_API_KEY_2"],
    },
    "opencode-groq": {
        "display_name": "GroqCloud",
        "tier": "core",
        "description": "LPU Inference เร็วที่สุดในโลก 300+ tokens/sec เหมาะกับงานเขียนโค้ดและทดสอบด่วน",
        "portal_url": "https://console.groq.com/keys",
        "quota_label": "สูงสุด 14,400 RPD ฟรี",
        "rate_limit": "30 RPM",
        "keyless": False,
        "default_keys": ["GROQ_API_KEY_1", "GROQ_API_KEY_2"],
    },
    "opencode-cerebras": {
        "display_name": "Cerebras Cloud",
        "tier": "core",
        "description": "ชิป Wafer-Scale Engine ความเร็วสูงมาก โควตาฟรี 1,000,000 โทเคนต่อวัน",
        "portal_url": "https://cloud.cerebras.ai",
        "quota_label": "1,000,000 tokens/วัน ฟรีตลอดไป",
        "rate_limit": "30 RPM",
        "keyless": False,
        "default_keys": ["CEREBRAS_API_KEY_1"],
    },
    "opencode-cloudflare": {
        "display_name": "Cloudflare Workers AI",
        "tier": "core",
        "description": "Serverless AI บนเครือข่าย Edge ทั่วโลก โควตาฟรี 10,000 Neurons ทุกวันตลอดชีพ",
        "portal_url": "https://dash.cloudflare.com",
        "quota_label": "10,000 Neurons/วัน ฟรีตลอดไป",
        "rate_limit": "100 req/min",
        "keyless": False,
        "default_keys": ["CLOUDFLARE_API_KEY_1", "CLOUDFLARE_ACCOUNT_ID"],
    },
    "opencode-pollinations": {
        "display_name": "Pollinations.ai",
        "tier": "standby",
        "description": "OpenAI-compatible Endpoint รองรับโมเดล DeepSeek V4.1 และ GPT-6 Luna",
        "portal_url": "https://enter.pollinations.ai",
        "quota_label": "ฟรี Fair Use / Pollen",
        "rate_limit": "30 RPM",
        "keyless": False,
        "default_keys": ["POLLINATIONS_API_KEY_1"],
    },
    "agy-ai-pro": {
        "display_name": "Google AI Pro (CLI)",
        "tier": "standby",
        "description": "Google Antigravity CLI Account หลักในเครื่อง",
        "portal_url": "https://antigravity.google",
        "quota_label": "บัญชี CLI ประจำเครื่อง",
        "rate_limit": "CLI Managed",
        "keyless": True,
        "default_keys": [],
    },
}


def _open_https(req: urllib.request.Request, timeout: float):
    """เปิด URL เฉพาะ https เท่านั้น — กัน scheme แปลก (file:, ftp:) ถ้า URL ถูกแก้โดยไม่ตั้งใจ"""
    if urllib.parse.urlsplit(req.full_url).scheme != "https":
        raise ValueError("อนุญาตเฉพาะการเชื่อมต่อ https")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310 - scheme ถูกตรวจด้านบนแล้ว

def mask_key(val: str) -> str:
    """ซ่อนส่วนตรงกลางของคีย์เพื่อความปลอดภัยใน UI"""
    if not val:
        return ""
    val = val.strip()
    if len(val) >= 12:
        return f"{val[:5]}...{val[-4:]}"
    if len(val) >= 6:
        return f"{val[:2]}...{val[-2:]}"
    return "***"


def load_env_file(path: Path | None = None) -> dict[str, str]:
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


# Env names that change how the GUI or spawned runners execute (MED-15). Always refused.
_DOTENV_DENY = {
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "HOME", "USERPROFILE", "PYTHONPATH", "PYTHONHOME",
    "PYTHONSTARTUP", "PYTHONUSERBASE", "NODE_OPTIONS", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "BASH_ENV", "ENV", "PS1", "IFS",
}
_DOTENV_DENY_PREFIXES = ("LD_", "DYLD_", "PYTHON", "NODE_")
_DOTENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*_(API_KEY|KEY|TOKEN|ACCOUNT_ID)(_\d+)?$")
_DOTENV_ROLE_SUFFIX_RE = re.compile(r"_(JUDGE|SCAN|CODER)$")
_DOTENV_SHAPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _catalog_env_names() -> set[str]:
    return {k for cat in PROVIDERS_CATALOG.values() for k in cat.get("default_keys", [])}


def _is_denied_env_name(name: str) -> bool:
    upper = name.upper()
    return upper in _DOTENV_DENY or upper.startswith(_DOTENV_DENY_PREFIXES)


def validate_dotenv_key_name(name: str) -> str:
    """Only API-key-like names may be written to .env (MED-15).

    Accepts names such as NVIDIA_API_KEY_1, NVIDIA_JUDGE_KEY, GROQ_API_KEY_SCAN or a name
    listed in PROVIDERS_CATALOG. Reserved process variables (PATH, PYTHONPATH, ...) are refused.
    """
    name = name.strip()
    if _is_denied_env_name(name):
        raise ValueError(f"ไม่อนุญาตให้ตั้งค่าตัวแปร {name!r} ผ่าน GUI")
    if name in _catalog_env_names():
        return name
    if _DOTENV_KEY_RE.match(name):
        return name
    base = _DOTENV_ROLE_SUFFIX_RE.sub("", name)
    if base != name and _DOTENV_KEY_RE.match(base):
        return name
    raise ValueError(f"ชื่อ key {name!r} ไม่ถูกต้อง (ต้องลงท้ายด้วย _API_KEY, _KEY, _TOKEN หรือ _ACCOUNT_ID)")


def _validate_dotenv_delete_name(name: str) -> str:
    """Deleting only removes a line, so the shape check is looser; reserved names are still refused."""
    name = name.strip()
    if not _DOTENV_SHAPE_RE.match(name) or _is_denied_env_name(name):
        raise ValueError(f"ไม่อนุญาตให้ลบตัวแปร {name!r}")
    return name


def save_dotenv(updates: dict[str, str], path: Path | None = None) -> list[str]:
    """บันทึกคู่ key-value ลงไฟล์ .env โดยคงข้อความเดิม/comment ไว้ครบถ้วน

    - หากค่าที่ส่งมามี '...' หรือ '***' (ค่าที่ mask ไว้) จะข้ามไม่แก้ไขค่าเดิม
    - อัปเดต os.environ ทันทีเพื่อให้โปรเซสที่กำลังทำงานหยิบไปใช้ได้
    - ชื่อและค่าทั้งหมดถูกตรวจก่อนเขียนไฟล์ (MED-15): ชื่อต้องเป็น key ที่รู้จัก, ค่าห้ามมี CR/LF
    """
    if path is None:
        path = ROOT / ".env"

    for raw_name, raw_value in updates.items():
        if not str(raw_name).strip():
            continue
        validate_dotenv_key_name(str(raw_name))
        if "\r" in str(raw_value) or "\n" in str(raw_value):
            raise ValueError(f"ค่าของ {str(raw_name).strip()} ต้องไม่มีการขึ้นบรรทัดใหม่")

    with cfg_file_lock(path):
        existing_content = ""
        if path.exists():
            try:
                existing_content = path.read_text(encoding="utf-8")
            except Exception:
                existing_content = ""

        lines = existing_content.splitlines() if existing_content else []
        existing_keys: dict[str, int] = {}
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                existing_keys[k.strip()] = idx

        updated_keys: list[str] = []
        for k, v in updates.items():
            k = k.strip()
            v = str(v).strip()
            if not k:
                continue
            # หากเป็นค่าที่ถูก Mask มาจาก UI (มี ... หรือ ***) ถือว่าผู้ใช้ไม่ได้แก้ ข้ามการทับ
            if "..." in v or "***" in v:
                continue

            updated_keys.append(k)
            formatted_line = f"{k}={v}"
            if k in existing_keys:
                lines[existing_keys[k]] = formatted_line
            else:
                lines.append(formatted_line)
                existing_keys[k] = len(lines) - 1

            # ซิงก์เข้า process environment ทันที
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

        new_content = "\n".join(lines).strip()
        if new_content:
            new_content += "\n"
        atomic_write_text(path, new_content, encoding="utf-8")
        return updated_keys


def key_id_for(engine_name: str, var_name: str = "", value: str = "") -> str:
    """Stable cooldown id for one key of an engine (HIGH-06).

    The id must not depend on the key's position in a role-filtered or reordered list.
    Keys that come from an env var use the var name (``engine#NVIDIA_API_KEY_1``); literal
    keys use a hash of the value so the secret itself is never stored in key_status.json.
    """
    if var_name:
        return f"{engine_name}#{var_name}"
    digest = hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]
    return f"{engine_name}#sha256:{digest}"


def reset_key_cooldown(key_id: str | None = None, engine_name: str | None = None) -> bool:
    """ล้างคูลดาวน์สำหรับ key_id (เช่น opencode-nvidia#NVIDIA_API_KEY_1) หรือทั้ง Engine"""
    with file_lock(STATE / "key_status.json.lock"):
        status = locked_json_read(KEY_STATUS, default={})
        if key_id and key_id in status:
            status[key_id]["cooldown_until"] = 0
            status[key_id]["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        if engine_name:
            for k in list(status.keys()):
                if k == engine_name or k.startswith(f"{engine_name}#"):
                    status[k]["cooldown_until"] = 0
                    status[k]["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        locked_json_write(KEY_STATUS, status)

    if engine_name:
        with file_lock(STATE / "engine_status.json.lock"):
            eng_status = locked_json_read(ENGINE_STATUS, default={})
            if engine_name in eng_status:
                eng_status[engine_name]["cooldown_until"] = 0
                eng_status[engine_name]["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            locked_json_write(ENGINE_STATUS, eng_status)
    return True


def get_opencode_auth_keys() -> dict[str, str]:
    """อ่าน API keys จาก ~/.local/share/opencode/auth.json (ถ้ามี) แบบ Read-only"""
    try:
        home_dir = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if home_dir:
            auth_file = Path(home_dir) / ".local" / "share" / "opencode" / "auth.json"
        else:
            auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    except Exception:
        return {}

    if not auth_file.exists():
        return {}
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
        res = {}
        for prov, val in data.items():
            if isinstance(val, dict) and val.get("key"):
                res[prov.lower()] = val["key"].strip()
            elif isinstance(val, str) and val.strip():
                res[prov.lower()] = val.strip()
        return res
    except Exception:
        return {}


def _catalog_env_var_names(eng: dict, cat: dict) -> list[str]:
    """ชื่อตัวแปรคีย์ที่ engine ใช้ (จาก config แล้วต่อด้วย default_keys ของ catalog)"""
    raw_keys = []
    if "api_keys" in eng and isinstance(eng["api_keys"], list):
        raw_keys.extend(eng["api_keys"])
    elif "api_key" in eng and eng["api_key"]:
        raw_keys.append(eng["api_key"])

    env_keys: list[str] = []
    for rk in raw_keys:
        m = re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$", str(rk).strip())
        if m:
            env_keys.append(m.group(1))
        elif str(rk).startswith("$"):
            env_keys.append(str(rk)[1:].strip())
    for dk in cat.get("default_keys", []):
        if dk not in env_keys:
            env_keys.append(dk)
    return env_keys


def _catalog_key_detail(evar: str, name: str, combined_env: dict, opencode_auth_val: str,
                        key_status: dict, eng_cool: float, is_engine_cooldown: bool,
                        favorite_keys: set, now: float) -> tuple[dict, bool, bool]:
    """รายละเอียดคีย์หนึ่งตัว. คืน (detail, configured, in_cooldown)"""
    raw_val = combined_env.get(evar, "").strip()
    from_opencode_auth = False
    if not raw_val and opencode_auth_val:
        raw_val = opencode_auth_val
        from_opencode_auth = True
    is_cfg = bool(raw_val)

    k_id = key_id_for(name, var_name=evar)
    k_cool = key_status.get(k_id, {}).get("cooldown_until", 0)
    in_cooldown = (k_cool > now) or is_engine_cooldown
    cool_until_ts = max(k_cool, eng_cool if is_engine_cooldown else 0)

    if is_cfg:
        status_str = "cooldown" if in_cooldown else "ready"
    else:
        status_str = "cooldown" if in_cooldown else "unset"

    detail = {
        "env_var": evar,
        "configured": is_cfg,
        "masked": mask_key(raw_val) + (" [OpenCode Auth]" if from_opencode_auth else ""),
        "source": "opencode_auth" if from_opencode_auth else ("env" if is_cfg else "none"),
        "status": status_str,
        "key_id": k_id,
        "cooldown_until": dt.datetime.fromtimestamp(cool_until_ts).isoformat(timespec="seconds") if in_cooldown else None,
        "cooldown_remaining_sec": max(0, int(cool_until_ts - now)) if in_cooldown else 0,
        "is_favorite": evar in favorite_keys,
        "roles": get_key_effective_roles(evar),
    }
    return detail, is_cfg, in_cooldown


def get_keys_catalog(cfg: dict, env_vars: dict[str, str] | None = None) -> dict:
    """สร้างข้อมูลสรุปแคตตาล็อกผู้ให้บริการทั้งหมดพร้อมสถานะคีย์สำหรับส่งให้ GUI"""
    if env_vars is None:
        file_env = load_env_file()
        combined_env = {**file_env, **os.environ}
    else:
        combined_env = {**os.environ, **env_vars}

    key_status = locked_json_read(KEY_STATUS, default={})
    eng_status = locked_json_read(ENGINE_STATUS, default={})
    now = time.time()
    favorite_keys = load_favorite_keys()
    opencode_auth = get_opencode_auth_keys()

    engines = cfg.get("engines", [])
    if not engines and "engine" in cfg:
        engines = [cfg["engine"]]

    provider_items = []
    counts = {"configured": 0, "unset": 0, "cooldown": 0, "privacy_safe": 0,
              "core": 0, "standby": 0, "total_keys": 0, "favorite": 0}
    all_known_vars: set[str] = set()

    for eng in engines:
        name = eng.get("name", eng.get("command", "default"))
        cat = PROVIDERS_CATALOG.get(name, {})
        display_name = cat.get("display_name") or eng.get("provider", name)
        tier = cat.get("tier", "standby")
        counts["core" if tier == "core" else "standby"] += 1

        trains_on_data = eng.get("trains_on_data", cat.get("trains_on_data", False))
        if not trains_on_data:
            counts["privacy_safe"] += 1

        keyless = cat.get("keyless", False) or eng.get("command") == "agy" or name in ("opencode-ollama-local",)
        env_keys = _catalog_env_var_names(eng, cat)

        is_fav = (name in favorite_keys) or any(k in favorite_keys for k in env_keys)
        all_known_vars.update(env_keys)
        if is_fav:
            counts["favorite"] += 1

        eng_cool = eng_status.get(name, {}).get("cooldown_until", 0)
        is_engine_cooldown = eng_cool > now
        prov_clean = name.replace("opencode-", "").lower()
        opencode_auth_val = opencode_auth.get(prov_clean, "")

        key_details = []
        has_any_configured = False
        for evar in env_keys:
            detail, is_cfg, in_cooldown = _catalog_key_detail(
                evar, name, combined_env, opencode_auth_val, key_status,
                eng_cool, is_engine_cooldown, favorite_keys, now)
            key_details.append(detail)
            if is_cfg:
                has_any_configured = True
                counts["total_keys"] += 1
            if in_cooldown:
                counts["cooldown"] += 1

        if keyless:
            has_any_configured = True
        counts["configured" if has_any_configured else "unset"] += 1

        provider_items.append({
            "name": name,
            "display_name": display_name,
            "tier": tier,
            "description": cat.get("description", ""),
            "portal_url": cat.get("portal_url", ""),
            "quota_label": cat.get("quota_label", "ฟรี 0 บาท"),
            "rate_limit": cat.get("rate_limit", "Fair Use"),
            "trains_on_data": trains_on_data,
            "command": eng.get("command", "opencode"),
            "model": eng.get("model", ""),
            "enabled": eng.get("enabled", True),
            "keyless": keyless,
            "keys": key_details,
            "has_configured_key": has_any_configured,
            "is_cooldown": is_engine_cooldown or any(k["status"] == "cooldown" for k in key_details),
            "is_favorite": is_fav,
        })

    return {
        "providers": provider_items,
        "custom_keys": [
            {
                "env_var": ev_k,
                "configured": bool(ev_v),
                "masked": mask_key(ev_v),
                "roles": get_key_effective_roles(ev_k),
                "is_custom": True,
            }
            for ev_k, ev_v in load_env_file().items()
            if ev_k not in all_known_vars and ("KEY" in ev_k or "TOKEN" in ev_k or "SECRET" in ev_k or ev_k.endswith(("_JUDGE", "_SCAN")))
        ],
        "favorites": sorted(list(favorite_keys)),
        "key_roles": load_key_roles(),
        "summary": {
            "total_providers": len(provider_items),
            "core_count": counts["core"],
            "standby_count": counts["standby"],
            "configured_count": counts["configured"],
            "unset_count": counts["unset"],
            "cooldown_count": counts["cooldown"],
            "privacy_safe_count": counts["privacy_safe"],
            "total_keys": counts["total_keys"],
            "favorite_count": counts["favorite"],
            "budget_thb_monthly": 0,
        }
    }


# ---------------------------------------------------------------- Favorite Keys

def load_favorite_keys() -> set[str]:
    """โหลดรายการคีย์/ผู้ให้บริการโปรด (Favorite) จาก state/favorite_keys.json"""
    data = locked_json_read(FAVORITE_KEYS, default=[])
    if isinstance(data, list):
        return set(data)
    if isinstance(data, dict):
        return set(data.get("favorites", []))
    return set()


def save_favorite_keys(favorites: set[str] | list[str]) -> None:
    """บันทึกรายการคีย์/ผู้ให้บริการโปรด (Favorite) ลง state/favorite_keys.json"""
    STATE.mkdir(parents=True, exist_ok=True)
    fav_list = sorted(list(favorites))
    locked_json_write(FAVORITE_KEYS, fav_list)


def toggle_favorite_key(key: str, is_favorite: bool | None = None) -> bool:
    """เปิด/ปิดสถานะ Favorite ให้กับคีย์หรือ Engine (หากไม่ระบุ is_favorite จะสลับค่าเดิม)"""
    with file_lock(STATE / "favorite_keys.json.lock"):
        favs = load_favorite_keys()
        if is_favorite is None:
            new_state = key not in favs
        else:
            new_state = bool(is_favorite)

        if new_state:
            favs.add(key)
        else:
            favs.discard(key)
        save_favorite_keys(favs)
        return new_state


# ---------------------------------------------------------------- Key Roles (Coder / Judge / Scan)

def load_key_roles() -> dict[str, list[str]]:
    """โหลดการจับคู่บทบาทของ API Key (coder, judge, scan) จาก state/key_roles.json"""
    data = locked_json_read(KEY_ROLES, default={})
    if isinstance(data, dict):
        return {k: list(v) for k, v in data.items() if isinstance(v, (list, set))}
    return {}


def save_key_roles(roles_map: dict[str, list[str]]) -> None:
    """บันทึกการจับคู่บทบาทของ API Key ลง state/key_roles.json"""
    STATE.mkdir(parents=True, exist_ok=True)
    with file_lock(STATE / "key_roles.json.lock"):
        cleaned = {
            k: sorted(list(set(r for r in roles if r in VALID_ROLES)))
            for k, roles in roles_map.items()
            if roles
        }
        locked_json_write(KEY_ROLES, cleaned)


def set_key_roles(key_name: str, roles: list[str]) -> list[str]:
    """กำหนดบทบาทให้กับคีย์ที่ระบุ"""
    with file_lock(STATE / "key_roles.json.lock"):
        current = load_key_roles()
        valid = sorted(list(set(r for r in roles if r in VALID_ROLES)))
        if valid:
            current[key_name] = valid
        else:
            current.pop(key_name, None)
        save_key_roles(current)
        return valid


def get_key_effective_roles(key_name: str) -> list[str]:
    """ดึงบทบาทที่มีผลบังคับใช้ของคีย์: หากมีการตั้งค่าใน key_roles.json จะใช้ค่านั้นก่อน
    มิฉะนั้นจะตรวจสอบตาม Naming Convention:
    - มี '_JUDGE' ในชื่อ -> ['judge']
    - มี '_SCAN' ในชื่อ -> ['scan']
    - ค่าเริ่มต้น -> ['coder']
    """
    roles_map = load_key_roles()
    if key_name in roles_map and roles_map[key_name]:
        return sorted(list(roles_map[key_name]))

    upper = key_name.upper()
    if "_JUDGE" in upper or upper.startswith("JUDGE_"):
        return ["judge"]
    if "_SCAN" in upper or upper.startswith("SCAN_"):
        return ["scan"]
    return ["coder"]


# ---------------------------------------------------------------- Engine CRUD

def list_engines(cfg_path: Path | None = None) -> list[dict]:
    """อ่านรายการ Engines ทั้งหมดจาก config.yaml"""
    cfg_path = cfg_path or (ROOT / "config.yaml")
    if not cfg_path.exists():
        return []
    raw = yaml_io.load_text(cfg_path.read_text(encoding="utf-8")) or {}
    if "engines" in raw and isinstance(raw["engines"], list):
        return raw["engines"]
    if "engine" in raw and isinstance(raw["engine"], dict):
        eng = dict(raw["engine"])
        eng.setdefault("name", eng.get("command", "default"))
        return [eng]
    return []


def get_engine(engine_name: str, cfg_path: Path | None = None) -> dict | None:
    """ดึงข้อมูลการตั้งค่าของ Engine ตามชื่อ"""
    for eng in list_engines(cfg_path):
        if eng.get("name") == engine_name:
            return dict(eng)
    return None


ALLOWED_ENGINE_COMMANDS = ("opencode", "agy", "gemini")


def _check_engine_command(command: str, path: str | None) -> None:
    """Only known agent CLIs may be configured as an engine command (CRIT-01).

    An arbitrary command used to be stored in config.yaml and later executed. If a
    path is given, its file name must be the same command (with .exe/.cmd optional).
    """
    if command not in ALLOWED_ENGINE_COMMANDS:
        raise ValueError(f"command ไม่ได้รับอนุญาต: {command!r} (ใช้ได้: {', '.join(ALLOWED_ENGINE_COMMANDS)})")
    if path:
        base = re.split(r"[\\/]", path.strip())[-1].lower()
        for suffix in (".exe", ".cmd"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        if base != command:
            raise ValueError(f"path {path!r} ไม่ตรงกับ command {command!r}")


def _check_engine_model(command: str, model: str) -> None:
    """OpenCode ต้องการ model รูป provider/model (เช่น opencode/xxx); ไม่มี provider = เรียกโมเดลไม่ได้.

    เกิดขึ้นจริงเมื่อ GUI บันทึก model โดยตัด prefix ออก (เช่น engine "opencode free").
    """
    model = (model or "").strip()
    if command == "opencode" and "/" not in model:
        raise ValueError(f"model {model!r} ของ opencode ต้องอยู่ในรูป provider/model เช่น opencode/{model}")


def add_engine(engine_data: dict, cfg_path: Path | None = None) -> bool:
    """เพิ่ม Engine ใหม่ลงใน config.yaml"""
    cfg_path = cfg_path or (ROOT / "config.yaml")
    with cfg_file_lock(cfg_path):
        if not cfg_path.exists():
            return False

        name = str(engine_data.get("name", "")).strip()
        command = str(engine_data.get("command", "")).strip()
        model = str(engine_data.get("model", "")).strip()
        if not name or not command or not model:
            raise ValueError("ข้อมูลไม่ครบถ้วน: ต้องระบุ name, command, และ model")
        _check_engine_command(command, str(engine_data.get("path") or "").strip())
        _check_engine_model(command, model)

        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        engines = raw.get("engines")
        if engines is None:
            engines = []
            raw["engines"] = engines

        if any(e.get("name") == name for e in engines):
            raise ValueError(f"มี Engine ชื่อ '{name}' อยู่ในระบบแล้ว")

        new_engine = {
            "name": name,
            "provider": str(engine_data.get("provider", name)).strip() or name,
            "command": command,
            "model": model,
            "timeout_minutes": int(engine_data.get("timeout_minutes", 30)),
            "trains_on_data": bool(engine_data.get("trains_on_data", False)),
            "enabled": bool(engine_data.get("enabled", True)),
        }
        if engine_data.get("path"):
            new_engine["path"] = str(engine_data["path"]).strip()
        if engine_data.get("api_keys"):
            keys = engine_data["api_keys"]
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split(",") if k.strip()]
            new_engine["api_keys"] = list(keys)
        if engine_data.get("provider_id"):
            new_engine["provider_id"] = str(engine_data["provider_id"]).strip()

        engines.append(new_engine)
        atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        return True


def update_engine(engine_name: str, updates: dict, cfg_path: Path | None = None) -> bool:
    """แก้ไขการตั้งค่าของ Engine ใน config.yaml โดยคงคอมเมนต์ไว้เมื่อทำได้"""
    cfg_path = cfg_path or (ROOT / "config.yaml")
    with cfg_file_lock(cfg_path):
        if not cfg_path.exists():
            return False

        text = cfg_path.read_text(encoding="utf-8")

        if "model" in updates:
            cur = next((e for e in ((yaml_io.load_text(text) or {}).get("engines") or []) if e.get("name") == engine_name), {})
            _check_engine_model(str(updates.get("command", cur.get("command", ""))).strip(), str(updates["model"]))

        # If only model is being updated, do text replacement to preserve comments
        if list(updates.keys()) == ["model"]:
            new_model = updates["model"]
            lines = text.splitlines(keepends=True)
            new_lines = []
            in_target = False
            updated = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("- name:") or stripped.startswith("name:"):
                    cur_name = stripped.split(":", 1)[1].strip()
                    in_target = (cur_name == engine_name)
                elif in_target and stripped.startswith("- name:"):
                    in_target = False
                elif in_target and stripped.startswith("model:"):
                    indent = line[:len(line) - len(line.lstrip())]
                    line = f"{indent}model: {new_model}\n"
                    updated = True
                    in_target = False
                new_lines.append(line)
            if updated:
                atomic_write_text(cfg_path, "".join(new_lines), encoding="utf-8")
                return True

        raw = yaml_io.load_text(text) or {}
        engines = raw.get("engines")
        if not engines or not isinstance(engines, list):
            return False

        target = None
        for eng in engines:
            if eng.get("name") == engine_name:
                target = eng
                break
        if target is None:
            return False

        if "command" in updates or "path" in updates:
            eff_command = str(updates.get("command", target.get("command", ""))).strip()
            eff_path = str(updates["path"]).strip() if "path" in updates else str(target.get("path") or "").strip()
            _check_engine_command(eff_command, eff_path)

        new_name = updates.get("name")
        if new_name and new_name != engine_name:
            new_name_clean = str(new_name).strip()
            if any(e.get("name") == new_name_clean for e in engines):
                raise ValueError(f"มี Engine ชื่อ '{new_name_clean}' อยู่ในระบบแล้ว")
            target["name"] = new_name_clean

        for field in ("provider", "command", "model", "path"):
            if field in updates:
                val = str(updates[field]).strip()
                if val:
                    target[field] = val
                elif field in target and field == "path":
                    target.pop(field, None)

        if "timeout_minutes" in updates:
            target["timeout_minutes"] = int(updates["timeout_minutes"])
        if "trains_on_data" in updates:
            target["trains_on_data"] = bool(updates["trains_on_data"])
        if "enabled" in updates:
            target["enabled"] = bool(updates["enabled"])
        if "api_keys" in updates:
            keys = updates["api_keys"]
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split(",") if k.strip()]
            target["api_keys"] = list(keys)

        atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        return True


def update_engine_model(engine_name: str, new_model: str, cfg_path: Path | None = None) -> bool:
    """อัปเดตโมเดลของ Engine"""
    return update_engine(engine_name, {"model": new_model}, cfg_path=cfg_path)


def delete_engine(engine_name: str, cfg_path: Path | None = None) -> bool:
    """ลบ Engine ออกจาก config.yaml พร้อมล้างสถานะ Cooldown"""
    cfg_path = cfg_path or (ROOT / "config.yaml")
    with cfg_file_lock(cfg_path):
        if not cfg_path.exists():
            return False

        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        engines = raw.get("engines")
        if not engines or not isinstance(engines, list):
            return False

        orig_len = len(engines)
        raw["engines"] = [e for e in engines if e.get("name") != engine_name]
        if len(raw["engines"]) == orig_len:
            return False

        atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")

        if ENGINE_STATUS.exists():
            with file_lock(STATE / "engine_status.json.lock"):
                status = locked_json_read(ENGINE_STATUS, default={})
                if engine_name in status:
                    status.pop(engine_name, None)
                    locked_json_write(ENGINE_STATUS, status)

        return True


def reorder_engines(ordered_names: list[str], cfg_path: Path | None = None) -> bool:
    """จัดเรียงลำดับ Engines ใน config.yaml ตามรายชื่อที่ส่งมา"""
    cfg_path = cfg_path or (ROOT / "config.yaml")
    with cfg_file_lock(cfg_path):
        if not cfg_path.exists():
            return False

        text = cfg_path.read_text(encoding="utf-8")
        raw = yaml_io.load_text(text) or {}
        engines = raw.get("engines")
        if not engines or not isinstance(engines, list):
            return False

        engine_map = {e.get("name"): e for e in engines}
        new_engines = []
        for name in ordered_names:
            if name in engine_map:
                new_engines.append(engine_map.pop(name))
        new_engines.extend(engine_map.values())

        raw["engines"] = new_engines
        atomic_write_text(cfg_path, yaml_io.dump_text(raw), encoding="utf-8")
        return True


# ---------------------------------------------------------------- Delete .env Key

def delete_dotenv_key(key_name: str, path: Path | None = None) -> bool:
    """ลบคีย์ออกจาก .env และ os.environ"""
    key_name = _validate_dotenv_delete_name(key_name)
    path = path or (ROOT / ".env")
    with cfg_file_lock(path):
        deleted = False
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith(f"{key_name}=") or stripped == key_name:
                    deleted = True
                    continue
                new_lines.append(line)
            if deleted:
                new_content = "\n".join(new_lines)
                if new_content:
                    new_content += "\n"
                atomic_write_text(path, new_content, encoding="utf-8")
        if key_name in os.environ:
            os.environ.pop(key_name, None)
            deleted = True
        return deleted


# ---------------------------------------------------------------- Fetch Models

PROVIDER_MODEL_ENDPOINTS: dict[str, dict] = {
    "opencode-groq": {"url": "https://api.groq.com/openai/v1/models", "prefix": "groq/"},
    "opencode-cerebras": {"url": "https://api.cerebras.ai/v1/models", "prefix": "cerebras/"},
    "opencode-mistral": {"url": "https://api.mistral.ai/v1/models", "prefix": "mistral/"},
    "opencode-together": {"url": "https://api.together.xyz/v1/models", "prefix": "together/"},
    "opencode-sambanova": {"url": "https://api.sambanova.ai/v1/models", "prefix": "sambanova/"},
    "opencode-deepseek": {"url": "https://api.deepseek.com/models", "prefix": "deepseek/"},
    "opencode-pollinations": {"url": "https://gen.pollinations.ai/models", "type": "pollinations", "prefix": "pollinations/"},
    "opencode-nvidia": {"url": "https://integrate.api.nvidia.com/v1/models", "prefix": "nvidia/"},
}

EXCLUDED_MODEL_KEYWORDS = [
    "embedding", "embed", "whisper", "tts", "moderation", "audio", "rerank", "realtime", "guard", "safeguard"
]


def fetch_provider_models(provider_name: str, api_key: str | None = None) -> list[str]:
    """ดึงรายชื่อโมเดลแชท/โค้ดดิ้งจาก API ของผู้ให้บริการ"""
    config = PROVIDER_MODEL_ENDPOINTS.get(provider_name)
    if not config:
        # Generic fallback
        config = {"url": f"https://api.{provider_name.replace('opencode-', '')}.com/v1/models", "prefix": f"{provider_name.replace('opencode-', '')}/"}

    url = config["url"]
    req_type = config.get("type", "openai")
    prefix = config.get("prefix", "")

    key = (api_key or "").strip()
    if not key:
        env = {**load_env_file(), **os.environ}
        cat = PROVIDERS_CATALOG.get(provider_name, {})
        for default_k in cat.get("default_keys", []):
            if env.get(default_k):
                key = env[default_k].strip()
                break
        if not key:
            prov_clean = provider_name.replace("opencode-", "").lower()
            auth_map = get_opencode_auth_keys()
            key = auth_map.get(prov_clean, "")

    if not key and req_type != "pollinations":
        raise ValueError(f"ไม่พบ API Key สำหรับ {provider_name} กรุณาระบุหรือบันทึกคีย์ก่อน")

    headers = {
        "User-Agent": "auto-dev-crew/1.0",
        "Accept": "application/json",
    }

    if req_type == "pollinations":
        if key:
            headers["Authorization"] = f"Bearer {key}"
    else:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with _open_https(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise ValueError(f"API Key ไม่ถูกต้อง หรือไม่มีสิทธิ์เข้าถึง ({err.code} Unauthorized)")
        raise ValueError(f"เรียก API ไม่สำเร็จ ({err.code}): {err.reason}")
    except Exception as exc:
        raise ValueError(f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {exc}")

    models = []
    if req_type == "pollinations":
        raw_list = data if isinstance(data, list) else data.get("data", [])
        for item in raw_list:
            name = item.get("name", "")
            if name and not any(kw in name.lower() for kw in EXCLUDED_MODEL_KEYWORDS):
                models.append(f"{prefix}{name}" if not name.startswith(prefix) else name)
    else:
        raw_list = data.get("data", [])
        if isinstance(raw_list, list):
            for item in raw_list:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                if not any(kw in m_id.lower() for kw in EXCLUDED_MODEL_KEYWORDS):
                    models.append(f"{prefix}{m_id}" if not m_id.startswith(prefix) else m_id)

    # กรอง duplicates และเรียงลำดับ
    seen = set()
    deduped = []
    for m in models:
        if m not in seen:
            seen.add(m)
            deduped.append(m)

    return sorted(deduped)

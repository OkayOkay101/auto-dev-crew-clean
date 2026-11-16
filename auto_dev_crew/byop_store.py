"""BYOP (Pollinations): คลังคีย์หลายตัว, การสแกนคีย์, และรายการโมเดลที่ผูกกับบทบาท.

- คีย์ผู้ใช้ (sk_...) เก็บใน .env เป็น POLLINATIONS_API_KEY_<n> (ไม่เขียนทับของเดิม)
- ผู้ใช้เลือกคีย์ที่จะใช้ได้หลายตัว; ค่าที่เลือกเก็บใน state/byop_store.json
- โมเดลเก็บใน state เดียวกัน แต่ละตัวมีบทบาท (coder / judge / scan) ตาม keys.VALID_ROLES
- ค่าคีย์ไม่ถูกส่งกลับไปที่ UI (มีเฉพาะค่าที่ mask แล้ว)
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import keys

PROVIDER_ID = "pollinations"
KEY_PREFIX = "POLLINATIONS_API_KEY_"
KEY_VAR_RE = re.compile(r"^POLLINATIONS_API_KEY_(\d+)$")
MODEL_ID_RE = re.compile(r"^pollinations/[A-Za-z0-9._:/-]+$")
MODELS_URL = "https://gen.pollinations.ai/v1/models"
CHAT_URL = "https://gen.pollinations.ai/v1/chat/completions"
SCAN_TIMEOUT = 20


class ByopError(Exception):
    """ข้อผิดพลาดที่แสดงให้ผู้ใช้เห็นได้ (ไม่มีค่าคีย์อยู่ในข้อความ)."""


def _state_file(state_path: Path | None) -> Path:
    return state_path or (keys.STATE / "byop_store.json")


def _load_state(state_path: Path | None) -> dict:
    path = _state_file(state_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    models = data.get("models") if isinstance(data.get("models"), list) else []
    selected = data.get("selected") if isinstance(data.get("selected"), list) else None
    return {"selected": selected, "models": models}


def _save_state(state: dict, state_path: Path | None) -> None:
    path = _state_file(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys.atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def pool_vars(env_path: Path | None) -> list[str]:
    """ชื่อคีย์ POLLINATIONS_API_KEY_<n> ที่มีค่าอยู่ใน .env เรียงตามหมายเลข."""
    env = keys.load_env_file(env_path)
    found = []
    for name, value in env.items():
        m = KEY_VAR_RE.match(name)
        if m and str(value).strip():
            found.append((int(m.group(1)), name))
    return [name for _, name in sorted(found)]


# ---------------------------------------------------------------- คลังคีย์

def add_key(token: str, env_path: Path | None = None) -> str:
    """เพิ่มคีย์ผู้ใช้ใหม่เป็นหมายเลขถัดไป คืนชื่อตัวแปรที่ใช้เก็บ."""
    token = (token or "").strip()
    if not token.startswith("sk_"):
        raise ByopError("คีย์ผู้ใช้ต้องขึ้นต้นด้วย sk_ (ไม่ใช่ App Key pk_)")
    used = [int(m.group(1)) for name in keys.load_env_file(env_path)
            if (m := KEY_VAR_RE.match(name))]
    var = f"{KEY_PREFIX}{max(used, default=0) + 1}"
    keys.save_dotenv({var: token}, path=env_path)
    return var


def active_keys(env_path: Path | None = None, state_path: Path | None = None) -> list[str]:
    """คีย์ที่เลือกใช้อยู่ (ถ้ายังไม่เคยเลือก ถือว่าเลือกทุกคีย์)."""
    pool = pool_vars(env_path)
    selected = _load_state(state_path)["selected"]
    if selected is None:
        return pool
    return [v for v in pool if v in selected]


def list_keys(env_path: Path | None = None, state_path: Path | None = None) -> list[dict]:
    env = keys.load_env_file(env_path)
    active = set(active_keys(env_path, state_path))
    return [
        {"var": var, "masked": keys.mask_key(env[var]), "selected": var in active}
        for var in pool_vars(env_path)
    ]


def set_selected(names: list[str], env_path: Path | None = None, state_path: Path | None = None) -> list[str]:
    pool = pool_vars(env_path)
    unknown = [n for n in names if n not in pool]
    if unknown:
        raise ByopError("ไม่พบคีย์ใน .env: " + ", ".join(unknown))
    wanted = set(names)
    state = _load_state(state_path)
    state["selected"] = [v for v in pool if v in wanted]
    _save_state(state, state_path)
    return state["selected"]


def remove_key(var: str, env_path: Path | None = None, state_path: Path | None = None) -> bool:
    if var not in pool_vars(env_path):
        raise ByopError(f"ไม่พบคีย์ {var} ใน .env")
    keys.delete_dotenv_key(var, path=env_path)
    state = _load_state(state_path)
    if state["selected"] is not None:
        state["selected"] = [v for v in state["selected"] if v != var]
        _save_state(state, state_path)
    return True


# ---------------------------------------------------------------- สแกนคีย์

def _fetch_status(token: str) -> int:
    """เรียก /v1/models ด้วยคีย์นั้น แล้วคืนรหัส HTTP (ไม่ log ค่าคีย์)."""
    req = urllib.request.Request(
        MODELS_URL, method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=SCAN_TIMEOUT) as resp:  # nosec B310 - URL คงที่ เป็น https
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def scan_keys(env_path: Path | None = None, state_path: Path | None = None, fetch=None) -> list[dict]:
    """ตรวจทุกคีย์ใน .env ทีละตัว. ผลลัพธ์ไม่มีค่าคีย์."""
    do_fetch = fetch or _fetch_status
    env = keys.load_env_file(env_path)
    results = []
    for var in pool_vars(env_path):
        try:
            status = do_fetch(env[var])
        except (OSError, ValueError):
            results.append({"var": var, "ok": False, "status": None,
                            "message": "เชื่อมต่อ Pollinations ไม่สำเร็จ ลองใหม่อีกครั้ง"})
            continue
        ok = status == 200
        if ok:
            message = "ใช้งานได้"
        elif status in (401, 403):
            message = f"คีย์ถูกปฏิเสธ ({status})"
        else:
            message = f"ตรวจไม่สำเร็จ ({status})"
        results.append({"var": var, "ok": ok, "status": status, "message": message})
    return results


# ---------------------------------------------------------------- โมเดลตามบทบาท

def list_models(state_path: Path | None = None) -> list[dict]:
    return [{"id": m["id"], "roles": sorted(m["roles"])} for m in _load_state(state_path)["models"]]


def _clean_model_id(model_id: str) -> str:
    mid = (model_id or "").strip()
    if not MODEL_ID_RE.match(mid):
        raise ByopError("รหัสโมเดลต้องขึ้นต้นด้วย pollinations/ และมีแต่ตัวอักษรที่ใช้ได้")
    return mid


def _clean_roles(roles) -> set[str]:
    wanted = set(roles or [])
    bad = sorted(r for r in wanted if r not in keys.VALID_ROLES)
    if bad:
        raise ByopError("บทบาทไม่ถูกต้อง: " + ", ".join(bad))
    return wanted


def add_model(model_id: str, roles: list[str], state_path: Path | None = None,
              known_ids: set[str] | None = None) -> dict:
    """เพิ่มหรือผูกบทบาทให้โมเดล (บทบาทหนึ่งมีได้หลายโมเดล). ถ้าส่ง known_ids จะปฏิเสธโมเดลที่ไม่อยู่ในแคตตาล็อก."""
    mid = _clean_model_id(model_id)
    wanted = _clean_roles(roles)
    if not wanted:
        raise ByopError("ต้องเลือกบทบาทอย่างน้อยหนึ่งอย่าง")
    if known_ids is not None and mid not in known_ids:
        raise ByopError("ไม่พบโมเดลนี้ในรายการของ Pollinations กดดึงรายการใหม่แล้วเลือกจากรายการ")
    state = _load_state(state_path)
    entry = next((m for m in state["models"] if m["id"] == mid), None)
    if entry is None:
        entry = {"id": mid, "roles": []}
        state["models"].append(entry)
    entry["roles"] = sorted(set(entry["roles"]) | wanted)
    _save_state(state, state_path)
    return {"id": mid, "roles": entry["roles"]}


def set_roles(model_id: str, roles: list[str], state_path: Path | None = None) -> dict:
    """ตั้งบทบาททั้งชุดของโมเดลหนึ่งตัว (ใช้กับการกดชิปบทบาท). roles ว่าง = ลบโมเดลออก.

    แก้เฉพาะโมเดลนี้ โมเดลอื่นที่ถือบทบาทเดียวกันยังอยู่ครบ.
    """
    mid = _clean_model_id(model_id)
    wanted = _clean_roles(roles)
    state = _load_state(state_path)
    if not wanted:
        state["models"] = [m for m in state["models"] if m["id"] != mid]
        _save_state(state, state_path)
        return {"id": mid, "roles": []}
    entry = next((m for m in state["models"] if m["id"] == mid), None)
    if entry is None:
        entry = {"id": mid, "roles": []}
        state["models"].append(entry)
    entry["roles"] = sorted(wanted)
    _save_state(state, state_path)
    return {"id": mid, "roles": entry["roles"]}


def promote_model(model_id: str, state_path: Path | None = None) -> list[dict]:
    """ย้ายโมเดลไปต้นรายการ = เป็นโมเดลหลักของทุกบทบาทที่มันถืออยู่. คืนรายการใหม่."""
    mid = _clean_model_id(model_id)
    state = _load_state(state_path)
    target = next((m for m in state["models"] if m["id"] == mid), None)
    if target is None:
        raise ByopError("ไม่พบโมเดลนี้ในรายการที่ผูกบทบาทไว้")
    state["models"] = [target] + [m for m in state["models"] if m is not target]
    _save_state(state, state_path)
    return list_models(state_path)


def active_key_value(env_path: Path | None = None, state_path: Path | None = None) -> str | None:
    """ค่าคีย์ผู้ใช้ตัวแรกที่เลือกใช้อยู่ (ใช้เรียก API ภายในเซิร์ฟเวอร์เท่านั้น ห้ามส่งกลับ UI)."""
    env = keys.load_env_file(env_path)
    for var in active_keys(env_path, state_path):
        value = str(env.get(var, "")).strip()
        if value:
            return value
    return None


def _chat_probe(token: str, model_id: str) -> int:
    """ส่งข้อความสั้นไปที่ chat completions แล้วคืนรหัส HTTP.

    max_tokens ต้องมากพอสำหรับโมเดลที่คิดก่อนตอบ (เช่น gpt-oss): ที่ 1 โทเคนจะได้ 400
    "output_token_limit_exceeded" ทั้งที่โมเดลใช้งานได้ จึงใช้ 64.
    """
    body = json.dumps({
        "model": model_id.split("/", 1)[1],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 64,
    }).encode("utf-8")
    req = urllib.request.Request(
        CHAT_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=SCAN_TIMEOUT) as resp:  # nosec B310 - URL คงที่ เป็น https
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def check_model(model_id: str, env_path: Path | None = None, state_path: Path | None = None,
                probe=None) -> dict:
    """ทดสอบโมเดลด้วยคีย์ที่เลือกอยู่ 1 ครั้ง. เรียกเฉพาะเมื่อผู้ใช้กดปุ่มเอง (ใช้โควตา Pollen จริง)."""
    mid = _clean_model_id(model_id)
    token = active_key_value(env_path, state_path)
    if not token:
        raise ByopError("ยังไม่มีคีย์ที่เลือกใช้ ให้เชื่อมต่อหรือเลือกคีย์ก่อน")
    do_probe = probe or _chat_probe
    try:
        status = do_probe(token, mid)
    except (OSError, ValueError):
        return {"id": mid, "ok": False, "status": None,
                "message": "เชื่อมต่อ Pollinations ไม่สำเร็จ ลองใหม่อีกครั้ง"}
    if status == 200:
        return {"id": mid, "ok": True, "status": status, "message": "โมเดลใช้งานได้"}
    if status in (401, 403):
        return {"id": mid, "ok": False, "status": status, "message": f"คีย์ไม่มีสิทธิ์ใช้โมเดลนี้ ({status})"}
    if status == 404:
        return {"id": mid, "ok": False, "status": status, "message": "ไม่พบโมเดลนี้บน Pollinations (404)"}
    return {"id": mid, "ok": False, "status": status, "message": f"ทดสอบไม่สำเร็จ ({status})"}


def remove_model(model_id: str, state_path: Path | None = None) -> bool:
    state = _load_state(state_path)
    before = len(state["models"])
    state["models"] = [m for m in state["models"] if m["id"] != model_id]
    if len(state["models"]) == before:
        return False
    _save_state(state, state_path)
    return True


def models_for_role(role: str, state_path: Path | None = None) -> list[str]:
    """โมเดลทั้งหมดที่ถือบทบาทนี้ เรียงตามลำดับ (ตัวแรก = โมเดลหลัก)."""
    return [m["id"] for m in _load_state(state_path)["models"] if role in m["roles"]]


def model_for_role(role: str, state_path: Path | None = None) -> str | None:
    """โมเดลหลักของบทบาท (ตัวแรกในลำดับ) หรือ None ถ้าไม่มี."""
    found = models_for_role(role, state_path)
    return found[0] if found else None


def opencode_declaration(model_id: str | None) -> dict:
    """ส่วนของ config OpenCode ที่ประกาศโมเดล Pollinations ให้รู้จัก (ส่งผ่าน OPENCODE_CONFIG_CONTENT ตอนรัน).

    opencode รู้จักเฉพาะโมเดลที่ประกาศใน opencode.json; โมเดล BYOP ที่เพิ่มใหม่จึงต้องประกาศตอนรัน
    มิฉะนั้นจะได้ "Model not found". โมเดลที่ไม่ใช่ pollinations/... คืน dict ว่าง.
    """
    mid = (model_id or "").strip()
    if not mid.startswith(PROVIDER_ID + "/"):
        return {}
    short = mid.split("/", 1)[1]
    return {"provider": {PROVIDER_ID: {"models": {short: {"name": short}}}}}


def engines_for_role(eng: dict, role: str | None, state_path: Path | None = None) -> list[dict]:
    """ลำดับ engine ที่ต้องลองสำหรับบทบาทนี้ (ตามลำดับโมเดลหลัก -> สำรอง).

    Pollinations ที่บทบาทมีหลายโมเดล: คืนหนึ่งสำเนาต่อโมเดล โดยปักโมเดลไว้ที่ key "byop_model"
    (runner จะใช้สถานะ cooldown แยกต่อโมเดล). กรณีอื่นคืน engine เดิม (จาก engine_for_role).
    """
    if not role or eng.get("provider_id") != PROVIDER_ID:
        return [eng]
    mids = models_for_role(role, state_path)
    if len(mids) <= 1:
        return [engine_for_role(eng, role, state_path)]
    return [{**eng, "model": m, "byop_model": m} for m in mids]


def engine_for_role(eng: dict, role: str | None, state_path: Path | None = None) -> dict:
    """คืนสำเนาของ engine ที่ใช้โมเดลตามบทบาท (เฉพาะ engine ของ Pollinations).

    engine อื่นและกรณีที่บทบาทไม่มีโมเดลผูกไว้ คืน engine เดิมโดยไม่เปลี่ยนแปลง.
    """
    if not role or eng.get("provider_id") != PROVIDER_ID:
        return eng
    model = model_for_role(role, state_path)
    if not model or model == eng.get("model"):
        return eng
    return {**eng, "model": model}

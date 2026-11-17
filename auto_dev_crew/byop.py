"""Pollinations BYOP (Bring Your Own Pollen): ผู้ใช้อนุญาตให้โปรแกรมใช้ Pollen ของตัวเอง.

อ้างอิง: https://github.com/pollinations/pollinations/blob/main/BRING_YOUR_OWN_POLLEN.md

ขั้นตอน (OAuth authorization code + PKCE, ไม่มี client secret):
1. start_authorization() สร้าง verifier/challenge/state เก็บไว้ในหน่วยความจำ (อายุ 10 นาที) แล้วคืน authorize URL
2. ผู้ใช้อนุมัติที่ enter.pollinations.ai แล้วถูก redirect กลับมาที่ /api/byop/callback?code=...&state=...
3. connect() ตรวจ state (ใช้ได้ครั้งเดียว) แลก code เป็นคีย์ sk_... แล้วบันทึกลง .env ผ่าน providers.add_provider

คีย์ sk_... ไม่ถูกใส่ใน URL, ไม่ถูกส่งกลับไปที่เบราว์เซอร์ และแสดงเฉพาะค่าที่ mask แล้ว.
"""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import byop_store, keys, providers
from .byop_store import PROVIDER_ID, ByopError
from .redact import redact_secrets

PROVIDER_NAME = "Pollinations"
BASE_URL = "https://gen.pollinations.ai/v1"
AUTH_BASE = "https://enter.pollinations.ai"
TOKEN_URL = f"{AUTH_BASE}/api/oauth/token"
APP_KEY_ENV = "POLLINATIONS_APP_KEY"
DEFAULT_MODEL = "pollinations/openai/gpt-6-luna"  # ตรงกับ engine pollinations-luna ใน config.yaml
DEFAULT_BUDGET = 5        # Pollen cap ตามเอกสาร
MAX_BUDGET = 10           # ลิงก์ที่สร้างจากแอปตั้งได้สูงสุด 10 ตามเอกสาร
DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30
SCOPE = "usage"           # ขอเฉพาะสิทธิ์ที่ต้องใช้ (ไม่ขอ keys / profile)
MODELS = "text"
STATE_TTL_SECONDS = 600   # เอกสารกำหนดว่า authorization code มีอายุ 10 นาที

_pending: dict[str, tuple[str, float]] = {}   # state -> (verifier, created_at)
_pending_lock = threading.Lock()


def key_var() -> str:
    return providers.provider_key_var(PROVIDER_ID)


def get_app_key(env_path: Path | None = None) -> str:
    """App Key (pk_...) จาก environment หรือ .env. ค่านี้เป็น publishable key จึงไม่ถือเป็นความลับ."""
    value = (os.environ.get(APP_KEY_ENV) or keys.load_env_file(env_path).get(APP_KEY_ENV) or "").strip()
    return value


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    """คืน (verifier, challenge) ตาม RFC 7636 แบบ S256."""
    verifier = secrets.token_urlsafe(64)  # 86 ตัวอักษรในชุด [A-Za-z0-9_-] ตามข้อกำหนด 43-128
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def clamp_budget(value) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        num = float(DEFAULT_BUDGET)
    return min(max(num, 0.1), float(MAX_BUDGET))


def clamp_expiry(value) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        days = DEFAULT_EXPIRY_DAYS
    return min(max(days, 1), MAX_EXPIRY_DAYS)


def build_authorize_url(*, app_key: str, redirect_uri: str, state: str, code_challenge: str,
                        budget: float = DEFAULT_BUDGET, expiry: int = DEFAULT_EXPIRY_DAYS) -> str:
    params = {
        "response_type": "code",
        "client_id": app_key,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "models": MODELS,
        "budget": f"{budget:g}",
        "expiry": str(expiry),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_BASE}/authorize?{urllib.parse.urlencode(params)}"


def _prune_locked(now: float) -> None:
    for st in [s for s, (_, t) in _pending.items() if now - t > STATE_TTL_SECONDS]:
        _pending.pop(st, None)


def start_authorization(*, redirect_uri: str, budget=DEFAULT_BUDGET, expiry=DEFAULT_EXPIRY_DAYS,
                        env_path: Path | None = None) -> dict:
    app_key = get_app_key(env_path)
    if not app_key.startswith("pk_"):
        raise ByopError(_i18n.t("ยังไม่ได้ตั้งค่า {p0} (App Key ที่ขึ้นต้นด้วย pk_) ใน .env", p0=APP_KEY_ENV))
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _pending_lock:
        _prune_locked(now)
        _pending[state] = (verifier, now)
    url = build_authorize_url(
        app_key=app_key, redirect_uri=redirect_uri, state=state, code_challenge=challenge,
        budget=clamp_budget(budget), expiry=clamp_expiry(expiry),
    )
    return {"ok": True, "authorize_url": url, "redirect_uri": redirect_uri}


def consume_state(state: str) -> str | None:
    """คืน verifier ของ state ที่ยังไม่หมดอายุ แล้วลบทิ้ง (ใช้ได้ครั้งเดียว)."""
    if not state:
        return None
    now = time.monotonic()
    with _pending_lock:
        _prune_locked(now)
        entry = _pending.pop(state, None)
    return entry[0] if entry else None


def exchange_code(*, code: str, verifier: str, app_key: str, redirect_uri: str, timeout: float = 20) -> str:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": app_key,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }).encode("ascii")
    req = urllib.request.Request(
        TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - URL คงที่ เป็น https
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8") or "{}").get("error", "")
        except (ValueError, AttributeError):
            err = ""
        raise ByopError(_i18n.t("Pollinations ปฏิเสธการแลกรหัส ({p0})", p0=err or exc.code)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ByopError(_i18n.t("เชื่อมต่อ Pollinations ไม่สำเร็จ ลองใหม่อีกครั้ง")) from None
    token = str(data.get("access_token") or "").strip()
    if not token.startswith("sk_"):
        raise ByopError(_i18n.t("Pollinations ไม่ได้ส่งคีย์ที่ใช้ได้กลับมา"))
    return token


def connect(*, code: str, state: str, redirect_uri: str, env_path: Path | None = None,
            providers_path: Path | None = None, opencode_path: Path | None = None,
            cfg_path: Path | None = None) -> dict:
    """ขั้นตอนหลังผู้ใช้อนุมัติ: ตรวจ state, แลกคีย์, บันทึกลง .env และลงทะเบียน provider."""
    verifier = consume_state(state)
    if verifier is None:
        raise ByopError(_i18n.t("state ไม่ถูกต้องหรือหมดอายุ กรุณากด Connect ใหม่อีกครั้ง"))
    if not code:
        raise ByopError(_i18n.t("ไม่มี authorization code จาก Pollinations"))
    app_key = get_app_key(env_path)
    if not app_key.startswith("pk_"):
        raise ByopError(_i18n.t("ยังไม่ได้ตั้งค่า {p0} ใน .env", p0=APP_KEY_ENV))
    token = exchange_code(code=code, verifier=verifier, app_key=app_key, redirect_uri=redirect_uri)

    kw = {"cfg_path": cfg_path} if cfg_path is not None else {}
    registered = PROVIDER_ID in providers.load_providers(providers_path, opencode_path)
    has_pool = bool(byop_store.pool_vars(env_path))
    if not registered and not has_pool:
        # การเชื่อมต่อครั้งแรก: ลงทะเบียน provider พร้อมคีย์ตัวแรก (POLLINATIONS_API_KEY_1)
        providers.add_provider(
            pid=PROVIDER_ID, display_name=PROVIDER_NAME, base_url=BASE_URL, api_key=token,
            model=DEFAULT_MODEL, providers_path=providers_path, opencode_path=opencode_path,
            env_path=env_path, **kw,
        )
        var = key_var()
    else:
        # เชื่อมต่อครั้งถัดไป: เพิ่มเป็นคีย์ใหม่ต่อท้าย ไม่แตะคีย์เดิม
        var = byop_store.add_key(token, env_path=env_path)
    return {"ok": True, "provider": PROVIDER_ID, "key_var": var, "registered": registered or not has_pool,
            "masked": keys.mask_key(token)}


def status(*, env_path: Path | None = None) -> dict:
    var = key_var()
    value = keys.load_env_file(env_path).get(var) or os.environ.get(var) or ""
    return {
        "ok": True,
        "app_key_configured": get_app_key(env_path).startswith("pk_"),
        "connected": bool(value),
        "key_var": var,
        "masked": keys.mask_key(value) if value else "",
    }


def disconnect(*, env_path: Path | None = None) -> dict:
    removed = keys.delete_dotenv_key(key_var(), path=env_path)
    return {"ok": True, "disconnected": bool(removed)}


def safe_message(exc: Exception) -> str:
    return redact_secrets(str(exc))

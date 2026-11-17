"""แกนกลาง i18n ฝั่ง Backend: ข้อความไทย/อังกฤษจาก auto_dev_crew/locales/{th,en}.json

- ภาษาที่ใช้เก็บใน config.yaml คีย์ ui_language (ค่า th หรือ en; ค่าอื่นหรืออ่านไม่ได้ = th)
- t(key, **params) แทนค่าตัวแปร {name}; ถ้าไม่พบคีย์ในภาษาที่ขอ ใช้ไทยแทน; ถ้าไม่พบทั้งสองภาษา คืนคีย์
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from auto_dev_crew import yaml_io

SUPPORTED: tuple[str, ...] = ("th", "en")
DEFAULT = "th"

ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = Path(__file__).resolve().parent / "locales"
CONFIG_PATH = ROOT / "config.yaml"

_PARAM = re.compile(r"\{(\w+)\}")
_cache: dict[Path, dict[str, str]] = {}


def normalize_lang(value: object) -> str:
    """คืน "th" หรือ "en" เสมอ"""
    return value if isinstance(value, str) and value in SUPPORTED else DEFAULT


def current_lang(config_path: Path | None = None) -> str:
    """อ่าน ui_language จาก config.yaml; ไฟล์หายหรืออ่านไม่ได้ คืน DEFAULT"""
    path = config_path or CONFIG_PATH
    try:
        data = yaml_io.load_text(path.read_text(encoding="utf-8"))
        value = data.get("ui_language") if hasattr(data, "get") else None
    except Exception:
        return DEFAULT
    return normalize_lang(value)


def load_locale(lang: str) -> dict[str, str]:
    """พจนานุกรมของภาษานั้น (แคชไว้); ไฟล์หายคืน dict ว่าง"""
    path = LOCALES_DIR / f"{normalize_lang(lang)}.json"
    if path not in _cache:
        try:
            _cache[path] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache[path] = {}
    return _cache[path]


def t(key: str, lang: str | None = None, **params: object) -> str:
    """ข้อความของ key ในภาษาที่ขอ (ถ้า lang เป็น None ใช้ค่าจาก config)"""
    code = normalize_lang(lang) if lang is not None else current_lang()
    text = load_locale(code).get(key)
    if text is None:
        text = load_locale(DEFAULT).get(key)
    if text is None:
        text = key  # ไม่มีคำแปล: ใช้ข้อความต้นฉบับ (ไทย) แล้วยังต้องแทนตัวแปรด้วย
    return _PARAM.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)

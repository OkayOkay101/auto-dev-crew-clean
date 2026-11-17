"""ตรรกะ endpoint ภาษา (ไม่มีการตรวจ token ที่นี่: gui.py ตรวจก่อนเรียกเสมอ)

- GET  /api/i18n                  -> {"lang": "th"|"en", "dict": {ไทย: อังกฤษ}} (dict ว่างเมื่อเป็นไทย)
- POST /api/settings/language     body {"lang": "th"|"en"} -> เขียน ui_language ใน config.yaml
"""
from __future__ import annotations

from pathlib import Path

from auto_dev_crew import i18n, yaml_io
from auto_dev_crew.locks import atomic_write_text


def handle_get(path: str, config_path: Path | None = None) -> tuple[int, dict] | None:
    if path != "/api/i18n":
        return None
    lang = i18n.current_lang(config_path)
    dict_ = i18n.load_locale("en") if lang == "en" else {}
    return 200, {"lang": lang, "dict": dict_}


def handle_post(path: str, body: object, config_path: Path | None = None) -> tuple[int, dict] | None:
    if path != "/api/settings/language":
        return None
    if not isinstance(body, dict):
        return 400, {"error": i18n.t("body ต้องเป็น JSON object")}
    value = body.get("lang")
    if value not in i18n.SUPPORTED:
        return 400, {"error": i18n.t("lang ต้องเป็น th หรือ en")}
    target = config_path or i18n.CONFIG_PATH
    try:
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        data = yaml_io.load_text(text) if text.strip() else {}
        if data is None:
            data = {}
        data["ui_language"] = value
        atomic_write_text(target, yaml_io.dump_text(data), encoding="utf-8")
    except Exception as exc:  # คืนข้อความให้ UI แสดงได้ ไม่ทำให้เซิร์ฟเวอร์ล่ม
        return 500, {"error": i18n.t("บันทึกภาษาไม่สำเร็จ: {error}", error=exc)}
    return 200, {"lang": value}

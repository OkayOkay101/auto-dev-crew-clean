"""ตรรกะ endpoint ภาษา: auto_dev_crew/i18n_routes.py (การผูกกับ gui.py อยู่ในงานที่ยังบล็อก)"""
from __future__ import annotations

import json
from pathlib import Path

from auto_dev_crew import i18n, i18n_routes


def _en_dict() -> dict:
    return json.loads((Path(i18n_routes.i18n.LOCALES_DIR) / "en.json").read_text(encoding="utf-8"))


def test_get_i18n_returns_english_dict_when_config_says_en(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: en\n", encoding="utf-8")
    code, body = i18n_routes.handle_get("/api/i18n", cfg)
    assert code == 200
    assert body["lang"] == "en"
    assert body["dict"]["ภาษาไทย"] == "Thai"


def test_get_i18n_returns_empty_dict_for_thai(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: th\n", encoding="utf-8")
    code, body = i18n_routes.handle_get("/api/i18n", cfg)
    assert (code, body) == (200, {"lang": "th", "dict": {}})


def test_get_i18n_ignores_other_paths(tmp_path):
    assert i18n_routes.handle_get("/api/status", tmp_path / "config.yaml") is None


def test_post_language_writes_config_and_keeps_comments(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# ตั้งค่าของผู้ใช้\nmodel: x  # คอมเมนต์ท้ายบรรทัด\n", encoding="utf-8")
    code, body = i18n_routes.handle_post("/api/settings/language", {"lang": "en"}, cfg)
    assert (code, body) == (200, {"lang": "en"})
    text = cfg.read_text(encoding="utf-8")
    assert "ui_language: en" in text
    assert "# ตั้งค่าของผู้ใช้" in text
    assert "# คอมเมนต์ท้ายบรรทัด" in text
    assert i18n.current_lang(cfg) == "en"


def test_post_invalid_language_is_rejected_and_file_unchanged(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model: x\n", encoding="utf-8")
    code, body = i18n_routes.handle_post("/api/settings/language", {"lang": "xx"}, cfg)
    assert code == 400
    assert "error" in body
    assert cfg.read_text(encoding="utf-8") == "model: x\n"


def test_post_non_dict_body_is_rejected(tmp_path):
    code, _ = i18n_routes.handle_post("/api/settings/language", ["en"], tmp_path / "config.yaml")
    assert code == 400


def test_post_creates_config_when_missing(tmp_path):
    cfg = tmp_path / "config.yaml"
    code, _ = i18n_routes.handle_post("/api/settings/language", {"lang": "th"}, cfg)
    assert code == 200
    assert i18n.current_lang(cfg) == "th"


def test_post_ignores_other_paths(tmp_path):
    assert i18n_routes.handle_post("/api/other", {"lang": "en"}, tmp_path / "config.yaml") is None

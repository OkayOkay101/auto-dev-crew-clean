"""แกนกลาง i18n ฝั่ง Backend: auto_dev_crew/i18n.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_dev_crew import i18n


def _write_locales(folder: Path, th: dict, en: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "th.json").write_text(json.dumps(th, ensure_ascii=False), encoding="utf-8")
    (folder / "en.json").write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def locales(tmp_path, monkeypatch):
    folder = tmp_path / "locales"
    _write_locales(
        folder,
        th={"test.greet": "สวัสดี {name}", "test.thai_only": "ข้อความไทย"},
        en={"test.greet": "Hello {name}"},
    )
    monkeypatch.setattr(i18n, "LOCALES_DIR", folder)
    return folder


def test_normalize_lang_accepts_only_th_and_en():
    assert i18n.normalize_lang("en") == "en"
    assert i18n.normalize_lang("th") == "th"
    assert i18n.normalize_lang("fr") == "en"
    assert i18n.normalize_lang("") == "en"
    assert i18n.normalize_lang(None) == "en"
    assert i18n.normalize_lang(123) == "en"


def test_current_lang_reads_ui_language_from_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("# คอมเมนต์\nui_language: th\n", encoding="utf-8")
    assert i18n.current_lang(cfg) == "th"


def test_current_lang_missing_file_is_english(tmp_path):
    assert i18n.current_lang(tmp_path / "nope.yaml") == "en"


def test_current_lang_broken_yaml_is_english(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: [unclosed\n", encoding="utf-8")
    assert i18n.current_lang(cfg) == "en"


def test_current_lang_unknown_value_is_english(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: fr\n", encoding="utf-8")
    assert i18n.current_lang(cfg) == "en"


def test_t_uses_given_language_and_substitutes_params(locales):
    assert i18n.t("test.greet", "en", name="Ann") == "Hello Ann"
    assert i18n.t("test.greet", "th", name="แอน") == "สวัสดี แอน"


def test_t_falls_back_to_thai_when_english_is_missing(locales):
    assert i18n.t("test.thai_only", "en") == "ข้อความไทย"


def test_t_returns_key_when_no_locale_has_it(locales):
    assert i18n.t("missing.key", "en") == "missing.key"


def test_t_keeps_placeholder_when_param_not_given(locales):
    assert i18n.t("test.greet", "en") == "Hello {name}"


def test_t_without_lang_follows_config(locales, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: en\n", encoding="utf-8")
    monkeypatch.setattr(i18n, "CONFIG_PATH", cfg)
    assert i18n.t("test.greet", name="Ann") == "Hello Ann"

"""ตัวโหลดฝั่งเว็บ static/i18n.js: ตรวจโครงสร้างไฟล์ (ไม่รัน browser ในเทสนี้)"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "auto_dev_crew" / "static" / "i18n.js").read_text(encoding="utf-8")


def test_exposes_t_applyI18n_setLanguage_and_ready_promise():
    for needle in ("window.i18n =", "window.applyI18n =", "window.setLanguage =", "window.adcLoadI18n =", "window.adcI18nReady"):
        assert needle in JS, needle


def test_loads_dictionary_from_api_with_token_header():
    assert "/api/i18n" in JS
    assert '"X-Token"' in JS


def test_language_change_posts_to_settings_endpoint():
    assert "/api/settings/language" in JS


def test_old_substring_replacement_is_gone():
    assert "ADC_EN" not in JS
    assert "THAI" not in JS
    assert "MutationObserver" not in JS

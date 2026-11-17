"""gui.py ฝังค่าภาษา window.ADC_INIT ลงหน้า UI และมี route ของภาษา"""
import json

from auto_dev_crew import gui


def test_inject_adc_init_places_payload_before_i18n_script(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: en\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", cfg)
    html = '<html><body><script src="/static/i18n.js"></script></body></html>'

    out = gui._inject_adc_init(html)

    init_at = out.index("window.ADC_INIT = ")
    assert init_at < out.index('<script src="/static/i18n.js"></script>')
    payload = out[init_at + len("window.ADC_INIT = "):].split(";</script>", 1)[0]
    data = json.loads(payload)
    assert data["lang"] == "en"
    assert data["dict"]  # พจนานุกรมอังกฤษต้องไม่ว่าง


def test_inject_adc_init_defaults_to_thai_with_empty_dict(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", cfg)
    out = gui._inject_adc_init('<body><script src="/static/i18n.js"></script></body>')
    payload = out.split("window.ADC_INIT = ", 1)[1].split(";</script>", 1)[0]
    assert json.loads(payload) == {"lang": "th", "dict": {}}


def test_inject_adc_init_is_idempotent(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", cfg)
    once = gui._inject_adc_init('<body><script src="/static/i18n.js"></script></body>')
    assert gui._inject_adc_init(once) == once


def test_inject_adc_init_not_skipped_by_comment_mentioning_name(tmp_path, monkeypatch):
    # index_sidebar.html มีคอมเมนต์ที่เอ่ยถึงชื่อ window.ADC_INIT ต้องยังฝังค่าจริงได้
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", cfg)
    html = ('<body><!-- window.ADC_INIT ใน i18n.js -->\n'
            '<script src="/static/i18n.js"></script></body>')
    out = gui._inject_adc_init(html)
    assert "<script>window.ADC_INIT = " in out


def test_backend_translation_follows_config_override(tmp_path, monkeypatch):
    # เมื่อเปิดด้วย --config ข้อความฝั่ง Backend ต้องอ่านภาษาจากไฟล์นั้น ไม่ใช่ config.yaml ของโปรเจกต์
    from auto_dev_crew import i18n
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ui_language: en\n", encoding="utf-8")
    monkeypatch.setattr(gui, "_CONFIG_OVERRIDE", None)
    monkeypatch.setattr(i18n, "CONFIG_PATH", i18n.CONFIG_PATH)  # ให้ monkeypatch คืนค่าเดิมหลังเทสต์
    gui.set_config_path(cfg)
    translated = i18n.t("ต้องระบุ repo และ path")
    assert translated != "ต้องระบุ repo และ path"
    assert not any("฀" <= ch <= "๿" for ch in translated)  # ต้องเป็นอังกฤษ ไม่ใช่ไทย

# รองรับไทย/อังกฤษทั้ง Web UI และ Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ทำให้ทุกข้อความที่ผู้ใช้เห็น (หน้าเว็บและ Backend) สลับระหว่างไทยกับอังกฤษได้ ค่าเริ่มต้นเป็นไทย โดยใช้แหล่งคีย์เดียวกัน

**Architecture:** พจนานุกรมสองไฟล์ `auto_dev_crew/locales/th.json` และ `en.json` เป็นแหล่งความจริง ฝั่ง Backend เรียก `t(key, **params)` จาก `auto_dev_crew/i18n.py` ฝั่งเว็บโหลดพจนานุกรมผ่าน `/api/i18n` และใช้ `data-i18n` กับ `t()` ภาษาที่ใช้เก็บใน `config.yaml` คีย์ `ui_language`

**Tech Stack:** Python 3 (ไลบรารีมาตรฐาน, PyYAML ที่มีอยู่แล้ว), JavaScript ธรรมดาในไฟล์ static, pytest

**Spec:** `docs/superpowers/specs/2026-11-18-bilingual-th-en-design.md` (อ่านคู่กับแผนนี้เสมอ)

## Global Constraints

- ค่าเริ่มต้นของ `ui_language` คือ `th` ค่าที่รับได้มีเพียง `th` และ `en` ค่าอื่นทุกกรณีตกเป็น `th`
- ห้าม commit และ push (คำสั่งของผู้ใช้) ขั้น "checkpoint" ในแผนหมายถึงรันเทสแล้วหยุดเท่านั้น
- ห้ามแก้งานล็อกอินที่ยังไม่ commit ใน `gui.py`, `auth.py`, `public_view.py`, `deploy/`, `tests/test_auth.py`, `tests/test_gui_login.py`, `tests/test_public_view.py`
- ค่าที่ผู้ใช้ยังไม่ได้ตอบในส่วนที่ 9 ของ spec ใช้ค่าเริ่มต้นนี้: เก็บภาษาใน `config.yaml`; prompt ที่ส่งให้ AI คงเป็นไทย; ข้อความ log ของ slot และ PR body คงเป็นไทย; `/classic` ยังคงอยู่; ขั้น `gui.py` รอให้ผู้ใช้ commit งานล็อกอินก่อน
- ข้อมูลจริงของผู้ใช้ (ชื่อ issue, repo, log ดิบจากเอนจิน) ไม่แปล
- ชื่อคีย์ใช้รูปแบบ `ส่วน.ชื่อ` เช่น `nav.overview`, `keys.add`, `error.repo_not_found` ใช้ตัวพิมพ์เล็กและ `_` เท่านั้น
- ตัวแปรในข้อความใช้รูปแบบ `{name}` เช่น `"พบ {count} รายการ"`

## Review Focus

1. `ui_language` ใน `config.yaml` มีค่าแปลก ๆ หรือไฟล์ config เสีย → ระบบต้องไม่ล่ม และแสดงเป็นไทย (ทดสอบในงาน 1)
2. คีย์ที่ขาดในภาษาอังกฤษ → แสดงข้อความไทยแทน และเทสต้องล้มเหลวทันที (ทดสอบในงาน 2)
3. POST เปลี่ยนภาษาโดยไม่มี token → ตอบ 403 และไม่เขียน config (ทดสอบในงาน 4)
4. เปลี่ยนภาษาแล้ว config อื่นที่มีคอมเมนต์ยังอยู่ครบ (ใช้ `yaml_io` เดิม) (ทดสอบในงาน 4)
5. ข้อมูลที่บันทึกไว้ในไฟล์สถานะ (job, slot) เก็บเป็นคีย์หรือค่าดิบ ไม่เก็บข้อความที่แปลแล้ว เพื่อให้สลับภาษาแล้วแสดงถูกต้อง (ทดสอบในงาน 7)

---

### Task 1: แกนกลาง i18n ฝั่ง Backend

**Files:**
- Create: `auto_dev_crew/i18n.py`
- Test: `tests/test_i18n_core.py`

**Interfaces:**
- Consumes: `auto_dev_crew/yaml_io.py` (อ่านไฟล์ config), `config.yaml` ที่รากโปรเจกต์
- Produces:
  - `SUPPORTED: tuple[str, ...] = ("th", "en")`, `DEFAULT = "th"`
  - `normalize_lang(value: object) -> str` คืน `"th"` หรือ `"en"` เสมอ
  - `current_lang(config_path: Path | None = None) -> str` อ่าน `ui_language` ถ้าอ่านไม่ได้คืน `DEFAULT`
  - `t(key: str, lang: str | None = None, **params) -> str` ถ้า `lang` เป็น None ใช้ `current_lang()` ถ้าไม่พบคีย์คืนค่า `key` เอง ถ้าตัวแปรไม่ครบคืนข้อความที่ยังไม่แทนค่า
  - `load_locale(lang: str) -> dict[str, str]` มีแคชในหน่วยความจำ

- [ ] **Step 1: เขียนเทสที่ล้มเหลว**

```python
def test_normalize_lang_defaults_to_thai():
    assert normalize_lang("en") == "en"
    assert normalize_lang("th") == "th"
    assert normalize_lang("fr") == "th"
    assert normalize_lang(None) == "th"

def test_current_lang_reads_config_and_survives_broken_file(tmp_path):
    # config ที่มี ui_language: en -> "en"; ไฟล์เสีย (YAML ผิด) -> "th"
    ...

def test_t_substitutes_params_and_falls_back_to_key():
    assert t("test.greet", "en", name="A") == "Hello A"   # ใช้ fixture locale ทดสอบ
    assert t("missing.key", "en") == "missing.key"
```

- [ ] **Step 2: รันเทสให้ล้มเหลว**

Run: `pytest tests/test_i18n_core.py -v`
Expected: FAIL เพราะยังไม่มีโมดูล `auto_dev_crew.i18n`

- [ ] **Step 3: เขียน `auto_dev_crew/i18n.py`**

ใช้ `json.loads` อ่าน `locales/{lang}.json` และแคชผลไว้ ไม่มี dependency ใหม่ ส่วน `current_lang` ใช้ `yaml.safe_load` ผ่าน `try/except` ทุกชนิดข้อผิดพลาด

- [ ] **Step 4: รันเทสให้ผ่าน**

Run: `pytest tests/test_i18n_core.py -v`
Expected: PASS ทั้งหมด

- [ ] **Step 5: Checkpoint (ไม่ commit)** รัน `pytest tests/test_i18n_core.py -q` ซ้ำอีกครั้ง

---

### Task 2: พจนานุกรม `th.json` และ `en.json` และเทสความครบถ้วน

**Files:**
- Create: `auto_dev_crew/locales/th.json`, `auto_dev_crew/locales/en.json`
- Create (ใช้ครั้งเดียว ไม่เก็บในโปรเจกต์): สคริปต์ดึงคู่คำจาก `static/i18n_en.js` และ `EN_TEXT` ใน `static/index_sidebar.html` ไปไว้ใน `$SCRATCH` (`C:\Users\Smart\AppData\Local\Temp\claude\b4c71f013946e855\d691417a-4fff-461c-b8b2-228818ac47af\scratchpad`)
- Test: `tests/test_locales_parity.py`

**Interfaces:**
- Consumes: `auto_dev_crew/i18n.py` จากงาน 1 (`load_locale`)
- Produces: ไฟล์ JSON แบบ flat คีย์ → ข้อความ; คีย์ที่ใช้ในโค้ดต้องมีครบทั้งสองไฟล์

- [ ] **Step 1: เขียนเทสที่ล้มเหลว**

```python
def test_th_and_en_have_same_keys():
    th = json.loads((LOCALES / "th.json").read_text(encoding="utf-8"))
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    assert set(th) == set(en)

def test_no_empty_values():
    for name in ("th.json", "en.json"):
        data = json.loads((LOCALES / name).read_text(encoding="utf-8"))
        assert [k for k, v in data.items() if not str(v).strip()] == []

def test_en_has_no_thai_characters():
    data = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    assert [k for k, v in data.items() if THAI.search(v)] == []
```

- [ ] **Step 2: รันเทสให้ล้มเหลว**

Run: `pytest tests/test_locales_parity.py -v`
Expected: FAIL เพราะยังไม่มีไฟล์ locale

- [ ] **Step 3: สร้าง `th.json` และ `en.json`**

- ข้อความไทยมาจาก `EN_TEXT` (คีย์ = ไทย) และ `i18n_en.js` (คีย์ = ไทย) รวมกัน
- ตั้งชื่อคีย์ตามตำแหน่งในหน้าหรือโมดูล และเขียนลงไฟล์ตามผลสคริปต์
- ค่าอังกฤษให้ใช้ค่าที่มีอยู่แล้วก่อน ถ้าเป็นค่าที่ไม่สม่ำเสมอให้แก้ทีหลังในงาน 3-7
- ตัวแปรใน `i18n_en.js` ที่มี `{}` หรือ `%` ให้แปลงเป็น `{name}`

- [ ] **Step 4: รันเทสให้ผ่าน**

Run: `pytest tests/test_locales_parity.py -v`
Expected: PASS ทั้งสามเคส

- [ ] **Step 5: Checkpoint** `pytest tests/test_locales_parity.py -q`

---

### Task 3: ตัวโหลดฝั่งเว็บ `static/i18n.js` (แทนของเดิม)

**Files:**
- Rewrite: `auto_dev_crew/static/i18n.js` (เดิมคือตัวค้นหาข้อความย่อย)
- Test: `tests/test_i18n_js_loader.py` (ตรวจโครงสร้างไฟล์ด้วยการค้นข้อความ ไม่รัน browser ในเทสนี้)

**Interfaces:**
- Consumes: `GET /api/i18n` ที่งาน 4 จะสร้าง คืน `{"lang": "th"|"en", "dict": {key: text}}`
- Produces (ใช้ในหน้า HTML):
  - `window.adcLang: "th"|"en"`
  - `window.t(key, params?) -> string` คืนคีย์ถ้าไม่พบ
  - `window.applyI18n(root = document) -> void` แทน `textContent` ของ `[data-i18n]` และ `title`/`placeholder`/`aria-label` ผ่าน `data-i18n-attr="title:key"` ที่กำหนดเอง
  - `window.setLanguage(lang) -> Promise<void>` POST `/api/settings/language` แล้วโหลดหน้าใหม่
- ก่อนโหลดพจนานุกรมได้ ต้องมี token จาก `{{TOKEN}}` ของหน้าเดิม (ส่งเป็น header เดิมที่ใช้ทุก API)

- [ ] **Step 1: เขียนเทสที่ล้มเหลว** ตรวจว่าไฟล์มี `window.t =`, `window.applyI18n =`, `window.setLanguage =`, `/api/i18n`, `/api/settings/language`, และไม่มี `ADC_EN` หรือ `THAI.test`

- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_i18n_js_loader.py -v`

- [ ] **Step 3: เขียน `i18n.js` ใหม่** ใช้ `fetch` พร้อม token; ถ้าโหลดพจนานุกรมไม่ได้ให้ใช้คีย์แทนข้อความและบันทึกคำเตือนใน console

- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_i18n_js_loader.py -v`

- [ ] **Step 5: Checkpoint** `pytest tests/test_i18n_js_loader.py -q`

---

### Task 4: endpoint `/api/i18n` และ `/api/settings/language` ใน `gui.py`

**สถานะ: BLOCKED** รอให้ผู้ใช้ commit งานล็อกอินใน `auto_dev_crew/gui.py` ก่อน หรือให้ผู้ใช้อนุญาตให้เพิ่มเฉพาะ hunk ที่ไม่แตะงานล็อกอิน

**Files:**
- Create: `auto_dev_crew/i18n_routes.py` (ตรรกะทั้งหมดอยู่ที่นี่ เพื่อให้ gui.py เปลี่ยนแค่สองสามบรรทัด)
- Modify (เฉพาะ hunk ที่ระบุ): `auto_dev_crew/gui.py` ใน `do_GET` (ใกล้บรรทัด 1798-1811) และ `do_POST` (บรรทัด 1961)
- Test: `tests/test_i18n_routes.py`

**Interfaces:**
- Consumes: `auto_dev_crew/i18n.py` (`load_locale`, `normalize_lang`, `current_lang`), `auto_dev_crew/yaml_io.py` (เขียน config ที่คงคอมเมนต์)
- Produces: `handle_get(path: str, lang: str) -> tuple[int, dict] | None`, `handle_post(path: str, body: dict, config_path: Path) -> tuple[int, dict] | None`

- [ ] **Step 1: เขียนเทสที่ล้มเหลว**
  - GET `/api/i18n` คืน `lang` ที่ถูกต้องและ `dict` ที่มีคีย์เดียวกับ `en.json`
  - POST `/api/settings/language` ด้วย `{"lang": "en"}` เขียน `ui_language: en` และยังมีคอมเมนต์เดิมในไฟล์
  - POST ค่า `"xx"` คืน 400 และไม่เขียนไฟล์
  - POST โดยไม่มี token คืน 403 (ตรวจผ่านฟังก์ชันตรวจสิทธิ์เดิมของ `gui.py`, ใช้ `gui_patches.verify_request_security`)

- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_i18n_routes.py -v`

- [ ] **Step 3: เขียน `i18n_routes.py` และเพิ่มการเรียกใน `gui.py`** ต้องเปลี่ยนเฉพาะบรรทัดที่เรียกฟังก์ชันใหม่ ห้ามจัดรูปแบบไฟล์ทั้งไฟล์

- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_i18n_routes.py -v`

- [ ] **Step 5: Checkpoint** `pytest tests/test_i18n_routes.py -q`

---

### Task 5: ย้าย `static/index_sidebar.html` (หน้าหลัก)

**Files:**
- Modify: `auto_dev_crew/static/index_sidebar.html` (ข้อความไทยประมาณ 926 บรรทัด; `data-i18n` 70 จุด; `const EN_TEXT` ที่บรรทัด ~1598)
- Reads (no change): `auto_dev_crew/locales/th.json`, `en.json` จากงาน 2
- Test: `tests/test_locales_coverage.py` (ใหม่ ใช้แทนเทสเก่าในงาน 9)

**Interfaces:**
- Consumes: `window.t`, `window.applyI18n` จากงาน 3
- Produces: `data-i18n="ส่วน.ชื่อ"` ในทุกข้อความของหน้า; สคริปต์ใช้ `t("ส่วน.ชื่อ")` แทนสตริงไทย

แบ่งเป็นสามส่วนตามลำดับการทำงาน (แต่ละส่วนรันเทสได้เอง):

- [ ] **Step 1: เขียนเทสที่ล้มเหลว** ทุกคีย์ที่ถูกอ้างด้วย `data-i18n="..."` หรือ `t("...")` ใน `index_sidebar.html` มีอยู่ใน `th.json` และ `en.json`; และไม่มีอักษรไทยนอก `data-i18n`/`t()` ในข้อความที่ผู้ใช้เห็น (ยกเว้น allowlist ที่เขียนในเทส)

- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_locales_coverage.py -v`

- [ ] **Step 3: ย้ายทีละส่วน** ส่วน (ก) nav และ sidebar, (ข) ภาพรวมและงาน, (ค) สตูดิโอ คีย์ AI ตั้งค่า และสคริปต์ที่แสดง toast/confirm/alert ทั้งหมด ลบ `EN_TEXT` และ `applyLang` เดิมเมื่อจบส่วน (ค) และแทนด้วยการเรียก `applyI18n()` ตอนโหลด

- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_locales_coverage.py -v`

- [ ] **Step 5: Checkpoint** `pytest tests/test_locales_coverage.py -q`

---

### Task 6: ย้าย `index.html` (/classic), `login.html`, `mission_control.js`

**Files:**
- Modify: `auto_dev_crew/static/index.html` (ข้อความไทย 587 บรรทัด)
- Modify: `auto_dev_crew/static/login.html` (5 บรรทัด)
- Modify: `auto_dev_crew/static/mission_control.js` (30 บรรทัด)
- Test: เพิ่มกรณีใน `tests/test_locales_coverage.py`

**Interfaces:** เหมือนงาน 5

- [ ] **Step 1: เพิ่มเทสที่ล้มเหลว** สามไฟล์ต้องไม่มีอักษรไทยในข้อความที่ผู้ใช้เห็น (นอก `t()`/`data-i18n`)
- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_locales_coverage.py -v`
- [ ] **Step 3: ย้ายแต่ละไฟล์** `login.html` ต้องทำงานได้โดยไม่ต้องรอ `/api/i18n` หากโหลดไม่ได้ให้แสดงไทย (ไฟล์นี้ต้องใช้ได้ก่อนล็อกอิน จึงใช้เฉพาะคีย์จาก `/api/i18n` ที่ไม่ต้องมี token ได้ หรือฝัง dict ของ login ไว้ในหน้า) — ตัดสินใจตอนลงมือและบันทึกเหตุผลไว้ในรายงาน
- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_locales_coverage.py -v`
- [ ] **Step 5: Checkpoint** `pytest tests/test_locales_coverage.py -q`

---

### Task 7: ย้ายข้อความ Backend ในโมดูลที่ไม่ใช่ `gui.py`

**Files (จำนวนบรรทัดที่มีไทย):** `runner.py` (244, เฉพาะข้อความที่ผู้ใช้เห็น), `keys.py` (74), `byop_store.py` (53), `ci_bootstrap.py` (66), `deep_scan.py` (37), `quality_gates.py` (42, เฉพาะข้อความที่ผู้ใช้เห็น ไม่ใช่ prompt), `evaluator.py` (34), `playwright_env.py` (31), `playground.py`, `byop.py` (27), `feature_gen.py` (25), `providers.py` (19), `opencode_db.py` (17), `multi_repo.py` (15), `pr_body.py` (13, คงเป็นไทยตามค่าเริ่มต้น), `static_checks.py` (21), `static_gate.py` (11), `key_ping.py` (21), `gui_check.py` (21), `github_login.py` (11), `ci_sync.py` (8), `gui_patches.py` (8), `redact.py` (5), `todo_scan.py` (5), `yaml_io.py` (6), `locks.py` (2), `loop_breaker.py` (3), `procs.py` (2), `__main__.py` (2), `auth.py` (6, คงเป็นไทยตามงานล็อกอิน)
- Test: `tests/test_backend_i18n.py`

**Interfaces:**
- Consumes: `t(key, **params)` จากงาน 1
- Produces: ข้อความที่ผู้ใช้เห็นทั้งหมดเป็น `t("ส่วน.ชื่อ", **params)`; ค่าที่เก็บในไฟล์สถานะเป็นคีย์ ไม่ใช่ข้อความที่แปลแล้ว

**กฎการย้าย:** เฉพาะข้อความที่ไปถึงหน้าจอ, error ที่ API คืน, ผล CLI, และสถานะที่แสดงใน UI ไม่แตะ prompt ของเอนจิน ไม่แตะ log ไฟล์ slot และ PR body (ใช้ค่าเริ่มต้นตาม Global Constraints) ไม่แตะคอมเมนต์โค้ด

- [ ] **Step 1: เขียนเทสที่ล้มเหลว** เทสสแกนหาสตริงไทยในข้อความที่ส่งให้ผู้ใช้ผ่านการเรียก `raise`, `return {"error": ...}`, `print` ที่เป็น CLI และพิมพ์ทดสอบ `t()` ด้วย `lang="en"` ว่ามีคีย์ครบ
- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_backend_i18n.py -v`
- [ ] **Step 3: ย้ายทีละโมดูล** เรียงจากโมดูลที่มีจำนวนน้อยไปมาก แต่ละโมดูลรัน `pytest` ของเทสที่เกี่ยวข้องก่อนไปโมดูลถัดไป
- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_backend_i18n.py -v`
- [ ] **Step 5: Checkpoint** รัน `pytest -q` เต็ม ต้องไม่แย่กว่าเกณฑ์ตั้งต้น (1413 passed, 6 skipped) ถ้าเทสเดิมที่ assert ข้อความไทยดิบล้มเหลว ให้แก้ไปใช้คีย์ ไม่ใช่ลบเทส

---

### Task 8: ย้ายข้อความใน `gui.py` (รอ login commit)

**สถานะ: BLOCKED** เหมือนงาน 4 จะทำได้เมื่อ `gui.py` ไม่มีการแก้ไขค้างจากงานล็อกอิน

**Files:**
- Modify: `auto_dev_crew/gui.py` (ข้อความไทย 173 บรรทัด, `load_cfg` บรรทัด 67)
- Test: เพิ่มกรณีใน `tests/test_backend_i18n.py`

**Interfaces:** เหมือนงาน 7

- [ ] **Step 1: เพิ่มเทส** ข้อความจาก `gui.py` ที่ผู้ใช้เห็นต้องเป็นคีย์
- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_backend_i18n.py -v`
- [ ] **Step 3: ย้ายข้อความ** ห้ามจัดรูปแบบ `gui.py` ทั้งไฟล์
- [ ] **Step 4: รันให้ผ่าน** `pytest tests/test_backend_i18n.py -v`
- [ ] **Step 5: Checkpoint** `pytest -q`

---

### Task 9: ลบกลไกเดิมและปรับเทส

**Files:**
- Delete: `auto_dev_crew/static/i18n_en.js`
- Rewrite: `tests/test_i18n_english_coverage.py` (เทสเดิมอ้าง `i18n_en.js` และ `EN_TEXT` ซึ่งถูกลบ)
- Keep: `tests/test_locales_parity.py`, `tests/test_locales_coverage.py`, `tests/test_backend_i18n.py`, `tests/test_i18n_core.py`, `tests/test_i18n_js_loader.py`, `tests/test_i18n_routes.py`

**Interfaces:** ไม่มีการเปลี่ยนแปลง API

- [ ] **Step 1: เขียนเทสที่ล้มเหลว** ไม่มีไฟล์ `i18n_en.js`, ไม่มี `ADC_EN` ในโค้ด, ไม่มี `const EN_TEXT`
- [ ] **Step 2: รันให้ล้มเหลว** `pytest tests/test_i18n_english_coverage.py -v`
- [ ] **Step 3: ลบไฟล์และเขียน `test_i18n_english_coverage.py` ใหม่** ให้เป็นเทสที่ตรวจข้อ 1
- [ ] **Step 4: รันให้ผ่าน** `pytest -q`
- [ ] **Step 5: Checkpoint** `pytest -q`

---

### Task 10: ตรวจจริงทั้งสองภาษา

**Files:**
- Create: `outputs/` (ภาพ screenshot ของขั้นสำคัญ ตาม INSTRUCTIONS.md ข้อ 6)

**Interfaces:** ไม่มี

- [ ] **Step 1: รันเทสเต็ม** `pytest -q` แสดงผลจริง
- [ ] **Step 2: รัน GUI** `python -m auto_dev_crew` ที่ `127.0.0.1:8765` (ถ้ามี process เดิมอยู่ให้ตรวจก่อนว่าไม่ชนพอร์ต)
- [ ] **Step 3: ทดสอบในเบราว์เซอร์ภาษาไทย** เปิดหน้า `/` หน้า `/classic` หน้า login คลิกหน้าหลักทุกเมนู ตรวจว่าไม่มีอักษรไทยที่ไม่ควรมี
- [ ] **Step 4: สลับเป็นอังกฤษ** ใช้ปุ่มสลับ ตรวจทุกหน้าซ้ำ และตรวจ toast/confirm
- [ ] **Step 5: สลับกลับเป็นไทย** และตรวจว่าค่าใน `config.yaml` เป็น `th`
- [ ] **Step 6: บันทึกผล** ระบุในรายงานว่าทดสอบอะไร ผ่านหรือไม่ และส่วนที่ไม่ได้ทดสอบ

---

### Task 11: อัปเดต STATE.md

**Files:**
- Modify: `STATE.md` (รักษาขนาดไม่เกิน 3 KB)

- [ ] **Step 1: อ่าน STATE.md ใหม่** ก่อนแก้
- [ ] **Step 2: ย้ายงานที่เสร็จไปหัวข้อ Done** พร้อมผลเทสจริง และอัปเดต Open ตามสถานะงาน 4 และ 8
- [ ] **Step 3: ตรวจขนาด** `wc -c STATE.md`

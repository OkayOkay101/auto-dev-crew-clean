# STATE: auto-dev-crew-clean

ID: B
Updated 2026-11-18. Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean`. Git remote `origin` = https://github.com/OkayOkay101/auto-dev-crew-clean (private). Default branch `master`; `chore/remove-dead-features` is merged into it.

## Goal
Auto Dev Crew: local GUI (`auto_dev_crew/gui.py`) + runner. Thai and English UI (Thai default).

## Open
- [x] B1 ยกเลิก: ลบระบบล็อกอินรหัสผ่านทั้งหมดแล้ว (`auth.py`, `static/login.html`, `--require-login`, `/login`, `/api/login`, `/api/logout`) — ไม่ต้องแปลหน้า login อีก
- [x] B2 แปลข้อความ UI ใน gui.py (30 จุด, ไม่แตะ log/PR body/print) — เสร็จ 2026-11-18 (tests/test_gui_user_messages_i18n.py)
- [x] B3 แปลข้อความ "token ไม่ถูกต้อง" ใน `gui_patches.py` — เสร็จ 2026-11-18 (เทสต์ใหม่ใน test_mission_control_and_security.py)
- [x] B4 เพิกถอน Pollinations key ที่ enter.pollinations.ai — user ทำแล้ว 2026-11-18
- [x] B5 อัปโหลด GitHub แบบ private — สร้าง repo private และ push 2026-11-18 (ตรวจ secret ใน working tree และ history แล้ว: ไม่พบ key จริง)
- [x] B6 endpoint `/api/github/*` และ `github_login.py` ที่ UI ไม่ใช้: ลบแล้ว 2026-11-18 (อนุมัติโดยผู้ใช้)
- [x] B7 ลบ route `/classic` แล้ว 2026-11-18 (อนุมัติโดยผู้ใช้) — ไฟล์ `static/index.html` ยังอยู่เพราะ test_gui_layout และ test_api_crud ยังอ่านไฟล์นี้ (ไม่ถูกเสิร์ฟ)
- [x] B8 ลบ `deploy/oracle/` และ config.yaml ที่ผูกกับ Oracle ออกจาก git (commit `6d9e186`); เหลือ `config.example.yaml` เป็นไฟล์ tracked
- [x] B9 ทำเอกสารให้ตรงกับโค้ด: README หลักเป็นภาษาอังกฤษ, ภาษาไทยอยู่ทั้งใน README.md (ส่วนท้าย) และ `README.th.md`; GitHub description เป็นภาษาอังกฤษ (2026-11-18)
- [ ] B10 ให้คนที่อ่านภาษาอังกฤษได้ตรวจ `docs/en/` และ README.md ส่วนอังกฤษ (ยังไม่ได้ทำ; ผู้ช่วยทำเองไม่ได้)
- [ ] B11 เทียบเอกสารไทย/อังกฤษทีละประโยค (ตรวจแล้วแค่ส่วนที่มีความต่างชัดเจนและ token ในโค้ด)

## In progress
- ไม่มี งานที่ค้างอยู่ระหว่างทำ

## Done (verified)
- Commits: `60f941c` (login + ฐาน i18n), `badfc44` (ADC_INIT, /api/i18n, /api/settings/language, แปล 46 ข้อความ error ฝั่ง backend), `890be71` (แก้ flaky test fake_sleep), `6d9e186` (ลบ Oracle/GitHub login), `e054139`, `eedfc7d` (sync เอกสาร และ gate 3/4 wording), `fed6d2b` (README อังกฤษหลัก), `dab0da5` (handoff)
- ล่าสุด: `master` = `a548555` (merge ของ `chore/remove-dead-features`)
- pytest เต็มชุด (2026-11-18, หลังทุกการเปลี่ยนแปลง): 1401 passed, 6 skipped, 55 subtests passed
- ทดสอบเบราว์เซอร์พอร์ต 8766 แล้ว: UI และ error backend เป็นอังกฤษ, config จริงไม่ถูกแก้
- Restart GUI พอร์ต 8765 แล้ว (PID 15456, โค้ดใหม่, ADC_INIT และ /api/i18n ตอบปกติ)

## Files
- Core: `auto_dev_crew/i18n.py`, `i18n_routes.py`, `locales/en.json`, `static/i18n.js`
- gui.py: `_inject_adc_init`, `set_config_path`, route `/api/i18n`, `/api/settings/language`
- README: `README.md` (อังกฤษ + ไทย), `README.th.md` (ไทย)
- Handoff: `docs/HANDOFF.md`
- Plan: `docs/superpowers/plans/2026-11-18-bilingual-th-en.md`; spec: `docs/superpowers/specs/2026-11-18-bilingual-th-en-design.md`

## How to check
- `python -m pytest -q -p no:cacheprovider` (expect 1401 passed, 6 skipped)
- เปิดเว็บ http://127.0.0.1:8765/ แล้วสลับภาษาใน Settings (`#langSel`)
- restart: python -m auto_dev_crew.gui --port 8765

## Decisions (2026-11-18, user)
- Oracle Cloud dropped; use VPS or home PC + Cloudflare Tunnel.
- Simple mode (โหมดง่าย) removed completely.
- Pollinations is only an AI model provider here, not a hosting platform.
- Bilingual approach B: key = ข้อความไทย, `ui_language` ใน config.yaml (default `th`).
- AI prompts, logs, PR bodies stay Thai.
- Documentation: write English first, Thai afterward. GitHub README shows both languages.
- GitHub repo description (About) is in English and says what the program does.

## Summary
- สองภาษาใช้งานได้ทั้ง UI และเอกสาร; B1–B9 ปิดแล้ว
- เหลือ B10 (ผู้อ่านภาษาอังกฤษตรวจ) และ B11 (เทียบเอกสารทีละประโยค) ซึ่งต้องทำโดยคน/ทำเพิ่มภายหลัง
- ไม่มีระบบล็อกอินรหัสผ่านใน GUI แล้ว หน้า control ผูกกับ 127.0.0.1 และเข้าผ่าน SSH tunnel

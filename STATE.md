# STATE: auto-dev-crew-clean

ID: B
Updated 2026-11-18. Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean` (no git remote). Nothing pushed.

## Goal
Auto Dev Crew: local GUI (`auto_dev_crew/gui.py`) + runner. Thai and English UI (Thai default).

## Open
- [ ] B1 ขออนุมัติแปลหน้า login (`static/login.html`), ข้อความ `auth.py`, และฝัง ADC_INIT ในหน้า login — user · P2 · needs-approval
- [x] B2 แปลข้อความ UI ใน gui.py (30 จุด, ไม่แตะ log/PR body/print) — เสร็จ 2026-11-18 (tests/test_gui_user_messages_i18n.py)
- [x] B3 แปลข้อความ "token ไม่ถูกต้อง" ใน `gui_patches.py` — เสร็จ 2026-11-18 (เทสต์ใหม่ใน test_mission_control_and_security.py)
- [x] B4 เพิกถอน Pollinations key ที่ enter.pollinations.ai — user ทำแล้ว 2026-11-18
- [x] B5 อัปโหลด GitHub แบบ private — สร้าง repo private และ push 2026-11-18 (ตรวจ secret ใน working tree และ history แล้ว: ไม่พบ key จริง)
- [ ] B6 endpoint `/api/github/*` และ `github_login.py` ที่ UI ไม่ใช้: เก็บหรือลบ — user · P3 · needs-approval
- [ ] B7 เก็บ `/classic` หรือลบ — user · P3 · needs-approval

## In progress
- ไม่มี งานที่ค้างอยู่ระหว่างทำ

## Done (verified)
- Commits: `60f941c` (login + ฐาน i18n), `badfc44` (ADC_INIT, /api/i18n, /api/settings/language, แปล 46 ข้อความ error ฝั่ง backend), `890be71` (แก้ flaky test fake_sleep)
- pytest เต็มชุด: 1442 passed, 6 skipped
- ทดสอบเบราว์เซอร์พอร์ต 8766 แล้ว: UI และ error backend เป็นอังกฤษ, config จริงไม่ถูกแก้
- Restart GUI พอร์ต 8765 แล้ว (PID 15456, โค้ดใหม่, ADC_INIT และ /api/i18n ตอบปกติ)

## Files
- Core: `auto_dev_crew/i18n.py`, `i18n_routes.py`, `locales/en.json`, `static/i18n.js`
- gui.py: `_inject_adc_init`, `set_config_path`, route `/api/i18n`, `/api/settings/language`
- Plan: `docs/superpowers/plans/2026-11-18-bilingual-th-en.md`; spec: `docs/superpowers/specs/2026-11-18-bilingual-th-en-design.md`

## How to check
- `python -m pytest -q -p no:cacheprovider` (expect 1442 passed, 6 skipped)
- เปิดเว็บ http://127.0.0.1:8765/ แล้วสลับภาษาใน Settings (`#langSel`)
- restart: python -m auto_dev_crew.gui --port 8765

## Decisions (2026-11-18, user)
- Oracle Cloud dropped; use VPS or home PC + Cloudflare Tunnel.
- Simple mode (โหมดง่าย) removed completely.
- Pollinations is only an AI model provider here, not a hosting platform.
- Bilingual approach B: key = ข้อความไทย, `ui_language` ใน config.yaml (default `th`).
- AI prompts, logs, PR bodies stay Thai.

## Summary
- สองภาษาใช้งานได้; เหลือ B1 (หน้า login), B6, B7 รอผู้ใช้ตัดสิน

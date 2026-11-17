# STATE: auto-dev-crew-clean

Updated 2026-11-18. Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean` (no git remote). Nothing committed or pushed.

## Goal
Auto Dev Crew: local GUI (`auto_dev_crew/gui.py`) + runner for AI engines. Thai and English for web UI and backend.

## Open
- [ ] Wire `gui.py` for language: inject `window.ADC_INIT` in `/`, `/classic`, login; routes `GET /api/i18n`, `POST /api/settings/language` (logic in `i18n_routes.py`); translate ~146 Thai strings there. Needs approval (login work uncommitted in same file). — user · needs-decision
- [ ] Commit login work (`gui.py`, `auth.py`, `public_view.py`, `login.html`, `deploy/`, `tests/test_auth.py`) — user · needs-decision
- [ ] Login page and `auth.py` still Thai (login work, untouched) — user
- [ ] Revoke Pollinations key at enter.pollinations.ai — user
- [ ] Upload to GitHub: private or public; no git remote yet — user · needs-decision
- [ ] GitHub connect endpoints (`/api/github/*`, `github_login.py`) unused by UI: keep or delete — user · needs-decision

## In progress
- Bilingual: tests pass; web UI checked in browser. Server on 8765 runs OLD code.

## Done (verified)
- Bilingual core in place (`i18n.py`, `locales/en.json` 1,588 keys, `static/i18n.js`). Old dictionary removed.
- Backend messages wrapped in ~20 modules (not gui/auth/github_login/quality_gates/pr_body).
- Full pytest: 1436 passed, 6 skipped.
- Browser checked via test proxy (no gui.py change): switch works both ways. Leftover Thai = user content and gui.py messages.
- Design: `docs/superpowers/specs/2026-11-18-bilingual-th-en-design.md` (sec. 13-14). Plan: `docs/superpowers/plans/2026-11-18-bilingual-th-en.md`.

## Files
- New: `auto_dev_crew/i18n.py`, `i18n_routes.py`, `locales/en.json`, `tests/test_i18n_*.py`, `tests/test_locales_parity.py`
- Changed: `static/i18n.js`, `index_sidebar.html`, `index.html`, `mission_control.js`, backend modules, 3 test files
- Deleted: `static/i18n_en.js`

## How to check
- `python -m pytest -q` (expect 1436 passed, 6 skipped)
- `python -m auto_dev_crew.gui --port 8765`, open http://127.0.0.1:8765/, switch language in Settings.
- Restart 8765 after the gui.py step (Ctrl-C, then start again).

## Decisions (2026-11-18, user)
- Oracle Cloud dropped; use VPS or home PC + Cloudflare Tunnel.
- Simple mode (โหมดง่าย) removed completely.
- Pollinations is only an AI model provider here, not a hosting platform.
- Bilingual approach B. Defaults: language in `config.yaml` key `ui_language` (default `th`); AI prompts, logs, PR bodies stay Thai.

## Summary
- ระบบสองภาษาทำงานในหน้าเว็บและ backend ยกเว้น gui.py และหน้า login
- รอผู้ใช้อนุมัติแก้ gui.py และ commit งานล็อกอิน
- เทสผ่าน 1436 และทดสอบเบราว์เซอร์แล้วทั้งสองภาษา

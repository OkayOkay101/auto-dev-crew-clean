# STATE: auto-dev-crew-clean

Updated 2026-11-16. Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean` (not a git repo).

## Goal
Auto Dev Crew: local GUI (`auto_dev_crew/gui.py`) and runner for AI coding engines. Current work: GUI security, Pollinations BYOP (Bring Your Own Pollen), user-supplied keys.

## Open
- [ ] Run a real Pollinations BYOP OAuth round trip: user creates App Key with redirect `http://localhost/api/byop/callback`, sets `POLLINATIONS_APP_KEY=pk_...` in `.env` — user · needs-approval
- [ ] Confirm `pollinations/openai/gpt-6-luna` works via opencode with a live key — AI · stuck: needs live key
- [ ] Confirm the scan rule with a live key: scan treats HTTP 200 on `https://gen.pollinations.ai/v1/models` as valid, 401/403 as rejected — user/AI · stuck: needs live key
- [ ] Skill loading from Library Router is not in the app: the Library Router runs on the Claude side. The app now sends the role's model to the Pollinations engine, so this is only the mapping for that engine — user · needs-decision
- [ ] Confirm the reading that no new "coder system" was added: only the existing coder/judge/scan role tags were reused — user · needs-approval
- [ ] Commit changes (no commit made) — user · needs-approval

## In progress
Nothing running.

## Done (verified unless noted)
- GUI hardening in `gui.py` / `gui_patches.py`: `is_forbidden_read_path` blocks `.git/`, `.npmrc`, `*.pem`, `id_rsa*`, `.env*`; file-content needs `X-Token`; `/api/models` rejects `key=`; `/api/engine/update` allows only UI fields.
- `pip-audit -r requirements.txt`: no known vulnerabilities (no lock file, `>=` pins).
- BYOP in `auto_dev_crew/byop.py`. HTTP checks pass on a temp server; OAuth round trip NOT verified.
- BYOP card + JS added to classic `auto_dev_crew/static/index.html` (matches `index_sidebar.html`). Pytest passes; not clicked through in a browser.
- `.env.example` and `.env` regenerated with no key entries (user decision).
- `python -m pytest -q` on 2026-11-16: 1265 passed, 6 skipped (after removing 20 standby providers).
- Page loads with 6 model-fetch buttons and 7 provider titles (checked in browser, no JS error on load).
- Pollinations.ai card (`opencode-pollinations`): "📦 Backup" badge hidden in `index.html` and `index_sidebar.html` (`tierBadge`). Verified in browser. Other standby engine cards still show the badge.

- 2026-11-16 (TDD): BYOP key pool. `auto_dev_crew/byop_store.py` adds keys as `POLLINATIONS_API_KEY_<n>` without replacing, selects several keys, removes keys, and scans each key. Models carry roles (coder/judge/scan) and `model_for_role()` picks one. `connect` appends a new key after the first connect. Routes: `/api/byop/pool` (GET, token), `/api/byop/keys/{select,remove,scan}`, `/api/byop/models/{add,remove}`. UI added to the BYOP card in both static pages (`node --check` passes, not clicked in a browser). Role→model wiring: `byop_store.engine_for_role` swaps in the role's model for the Pollinations engine (`provider_id: pollinations`) inside `runner._execute_single_engine`. `_scan_kwargs` became `_role_kwargs` and passes every role, not only scan; 7 test fakes got `*, role=None` to match the real signature. Mutation check: removing the hook fails the integration test. 34 new tests in total.

## Files
- New: `auto_dev_crew/byop_store.py`, `tests/test_byop_store.py`, `tests/test_byop_routes.py`, `tests/test_byop_role_model.py`, `tests/test_secret_read_and_engine_update.py`
- Changed: `auto_dev_crew/byop.py`, `auto_dev_crew/gui.py`, `auto_dev_crew/runner.py`, `auto_dev_crew/static/index_sidebar.html`, `auto_dev_crew/static/index.html`, `tests/test_byop.py`, `tests/test_deep_scan.py`, `tests/test_engine_timeout_cooldown.py`, `tests/test_failover.py`, `tests/test_key_outcomes.py`, `tests/test_key_roles.py`, `STATE.md`
- Not mine: `config.yaml` was already modified at session start (the `opencode-pollinations` engine entry is missing from the working copy; `HEAD` has it). I did not touch it.

## How to check
- `cd C:\Users\Smart\Documents\auto-dev-crew-clean` then `python -m pytest -q` → expect `1301 passed, 6 skipped` (verified 2026-11-16).
- `restart: python -m auto_dev_crew.gui --port 8765 --no-browser`, open `http://127.0.0.1:8765/`, Ctrl+C to stop.

## Decisions
- 2026-11-16 | user | All key entries removed from `.env.example` and `.env`; users supply their own.
- 2026-11-16 | user | Standby "backup" providers removed from `PROVIDERS_CATALOG` (20 entries) in `keys.py`, `index.html`, `index_sidebar.html`. Kept `opencode-pollinations` (enabled engine) and `agy-ai-pro` (engine in config.yaml). Supersedes the earlier "catalog kept" note. Backups: scratchpad `backup-2026-11-16\`, outside this project.
- 2026-11-16 | user | Pollinations model choice happens only in the Pollinations.ai card's "🔍 ดึงโมเดลจาก API" picker; the BYOP card only connects and points there.
- 2026-11-16 | user | BYOP stays and is upgraded, because users will use it too.
- 2026-11-16 | AI (unverified) | BYOP: OAuth code + PKCE, scope `usage`, models `text`, budget 5 Pollen, expiry 7 days, model `pollinations/openai/gpt-6-luna`.
- 2026-11-16 | AI (unverified) | Callback skips `Sec-Fetch-Site` (cross-site redirect); `state` + PKCE protect it.

## Summary
- ทำความปลอดภัย GUI และ pip-audit เสร็จ เทสต์ผ่าน 1293 รายการ (รวม 26 เทสต์ใหม่ของคลังคีย์ BYOP)
- เพิ่มคลังคีย์ BYOP หลายคีย์ เลือกใช้ได้หลายตัว สแกนรายคีย์ และผูกโมเดลกับบทบาท coder/judge/scan; engine Pollinations ใช้โมเดลของบทบาทนั้นแล้ว (ยังไม่ได้โหลดสกิลจาก Library Router ในแอป)
- เพิ่ม BYOP card ในหน้า index.html แบบคลาสสิกแล้ว ยังไม่ได้ทดสอบ OAuth จริง
- เก็บ PROVIDERS_CATALOG ไว้ใน keys.py เพราะ engine ใช้ ผู้ใช้ใส่คีย์เอง

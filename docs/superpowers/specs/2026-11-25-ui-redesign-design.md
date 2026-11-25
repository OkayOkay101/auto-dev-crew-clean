# Auto Dev Crew — UI/UX Redesign Specification

**Date:** 2026-11-25  
**Scope:** Full UI/UX restructure of `auto_dev_crew/static/index_sidebar.html` and `auto_dev_crew/static/mission_control.js` (plus `tests/test_gui_sidebar.py` and i18n keys as needed).  
**Backend / API:** Preserve all existing backend endpoints and data contracts (`gui.py`, `/api/*`, `ADC_INIT`, `/api/i18n`, `/api/settings/language`).

---

## 1. Design Direction & Principles
- **Aesthetic:** Modern SaaS / Linear-inspired Clean UI — spacious, low visual noise, crisp 1px borders (`--line`), subtle elevation, and color reserved strictly for meaningful status (`running`, `success`, `warning`, `error`, primary CTA). Supports **Auto / Light / Dark** themes.
- **Typography:** `Plus Jakarta Sans` + `Noto Sans Thai` + `JetBrains Mono` (code/logs/diff).
- **Copy & Terminology:**
  - Cut verbose inline explanations by 50%+. Labels must be self-evident.
  - Move deep explanations and technical terms (`slot`, `Eval/judge`, `ai-plan`) into `(?)` tooltips.
  - Use plain, natural Thai for primary UI labels (with full `TH / EN` i18n support).

---

## 2. Information Architecture (4 Main Menus)

Collapsible left Navigation Rail on Desktop (`240px` expanded / `68px` collapsed) + responsive Drawer/Bottom Nav on narrow viewports (`< 768px`):

1. **ภาพรวม (Overview)** — Action-First Dashboard
   - **Agent Control & Live Status:** Compact hero bar with agent state, primary run controls (`ทำ 1 งาน`, `ทำต่อเนื่อง`, `หยุด`), Repo selector, Task mode, and Dry-run toggle.
   - **Action Inbox (รอคุณตัดสินใจ):** Directly actionable items (failed issues with one-click **ลองใหม่ / ดู Log**, PRs awaiting review with direct **รีวิว / Merge** actions). Badge count accurately reflects real actionable items.
   - **3-Slot Status Strip:** Single-row compact strip showing Slot 1–3 states + dropdown/popover to choose which slots run (`ทุกช่อง` / `เฉพาะช่อง 1–3`).
   - **KPI Summary Row:** Clean 4-metric strip (`งานรอคิว`, `PR รอรีวิว`, `PR merge แล้ว`, `เรียกเอเจนต์วันนี้`).
   - **Repositories (คลังโค้ด):** Compact expandable rows/table (name, status, failed/PR counts, quick actions; expand for per-repo settings).
2. **งาน & บันทึก (Jobs & Logs)**
   - Unified view with sub-tabs: **บันทึกสด (Live Log)**, **คิวงาน / งานล้มเหลว**, and **ประวัติงาน (History)**.
   - Slot filter chips (`ทุกช่อง`, `ช่อง 1`, `ช่อง 2`, `ช่อง 3`), auto-scroll, clear, and restart agent controls.
3. **สตูดิโอ (Studio)** — 2-Column Workspace
   - **Left Column:** Repo selector + Pull/Add Repo, Prompt input, Role/Size/Model selectors, Dry-run option, `สั่ง AI เขียนโค้ด` CTA, Quick Checks (`รันเทสต์`, `ตรวจไวยากรณ์`, `สแกนความปลอดภัย`), and collapsible Repo Files / Open Issues / AI Scan / Feature Plan panels.
   - **Right Column:** Dedicated live output viewer with tabs (`ผลต่างโค้ด Diff`, `ดูไฟล์`, `ผลการรัน`).
4. **ตั้งค่า (Settings)** — Sub-tabbed Hub
   - **ทั่วไป & ภาษา:** UI Language (`TH / EN`), Theme preference.
   - **กฎก่อน Merge:** Merge mode (`review-all`, etc.), CI check policy, AI Quality Judge toggle.
   - **คีย์ AI & โมเดล:** Clean compact model rows with role badges (`coder`, `judge`, `scan`) and a `...` overflow menu (`ทดสอบ`, `ตั้งเป็นหลัก`, `ลบ`), plus Pollinations BYOP connection, Failover order, and Recent usage sub-sections.
   - **เครื่องมือระบบ:** Doctor, Playground, MCP Hub, Security tests, Safe Revert plan, Engine metrics.

---

## 3. Clean Top Bar
- Left: Sidebar collapse/expand button + Page Title + Live slot badge (`กำลังทำงาน 0/3 ช่อง`).
- Right: Single primary CTA (`+ สั่งงาน` opening the unified task modal) + Theme toggle (`Auto / Light / Dark`).
- Removed duplicates: `TH/EN` moved to Settings; duplicate `merge: review-all` pill removed from top bar (kept subtle in sidebar footer or Settings).

---

## 4. Verification & Test Plan
- Preserve essential DOM IDs / `data-*` hooks used by `mission_control.js` and backend integration.
- Update `tests/test_gui_sidebar.py` to match the new 4-menu structure and clean UI.
- Run `python -m pytest -q -k gui` and capture Playwright screenshots across all 4 pages (Light & Dark, Desktop & Mobile) to verify visual quality and zero console/layout errors.

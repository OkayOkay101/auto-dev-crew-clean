# Auto Dev Crew UI/UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely restructure `auto_dev_crew/static/index_sidebar.html` into a clean, Modern SaaS / Linear-inspired 4-menu Action-First interface with progressive disclosure, 2-column Studio, clickable Action Inbox, sub-tabbed Settings (including compact AI Keys), and responsive mobile support.

**Architecture:** Single-file SPA template in `auto_dev_crew/static/index_sidebar.html` paired with `auto_dev_crew/static/mission_control.js`, `auto_dev_crew/static/i18n.js`, and `auto_dev_crew/locales/en.json`. Preserves all backend `/api/*` contracts and required test hooks (`checkCiPlans`, `restartRun`, `loadStoredState`, `byopCard`..`keyManagerCard`, `#repoDropdown` + `#repos > .card[data-repo-card]`, `data-work-table`, gate wording strings).

**Tech Stack:** Vanilla HTML5, CSS3 Custom Properties (Linear-style Light/Dark tokens), Vanilla JS, Google Fonts (`Plus Jakarta Sans`, `Noto Sans Thai`, `JetBrains Mono`), Material Symbols Rounded, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-25-ui-redesign-design.md`

## Global Constraints
- 4 main sidebar items: `overview`, `work`, `studio`, `settings`.
- Clean top bar: sidebar toggle, page title, live slot badge, single `+ สั่งงาน` CTA, theme switcher (no `TH/EN` or duplicate `merge` pill in top bar).
- Progressive disclosure: cut inline walls of text; use `(?)` tooltips and collapsible sections.
- Preserve every Thai i18n key coverage in `auto_dev_crew/locales/en.json`.

## Review Focus
- `Action Inbox` empty/populated states: clicking failed issues or open PRs navigates/scrolls directly to actionable item without dead ends.
- `Studio` 2-column layout on desktop (`>= 1024px`) and clean single-column stack on mobile (`< 768px`), plus helpful empty state when `0 files`.
- `Settings` sub-tabs (`general`, `apikeys`, `failover`, `recent`, `tools`): `mission_control.js` still mounts `#toolMissionControl` before `#toolRevert`.
- `AI Keys` compact model rows: overflow `...` menu opens/closes cleanly via keyboard and click without clipping.
- `i18n` & `pytest -q -k gui`: zero missing English translations and 100% passing GUI tests.

---

### Task 1: Restructure HTML shell & Linear-style CSS in `auto_dev_crew/static/index_sidebar.html`
- **Files:** `auto_dev_crew/static/index_sidebar.html`
- Replace CSS tokens with Linear-inspired Modern SaaS Light/Dark palette, 4-menu collapsible rail + mobile bottom nav, clean 56px topbar, Action-First overview layout, 3-slot single-row strip, compact expandable repo cards, 2-column Studio workspace, and sub-tabbed Settings + compact AI Keys overflow menus.
- Keep `byopCard` immediately before `keyManagerCard`, keep `repoDropdown` + `repos`, keep `toolRevert` in Settings › Tools, and include `(?)` tooltips + compact glossary containing required gate wording.

### Task 2: Update UI JS controller in `auto_dev_crew/static/index_sidebar.html` & `mission_control.js`
- **Files:** `auto_dev_crew/static/index_sidebar.html`, `auto_dev_crew/static/mission_control.js`
- Update `MAIN_SUBS`, `DEFAULT_SUB`, `SUB_SECTION`, `go()` with backward-compatible aliases (`keys` -> `settings/apikeys`, `tools` -> `settings/tools`).
- Render clickable Action Inbox items (`needsList`), compact 3-slot strip + slot run-mode dropdown, compact expandable repo cards (preserving `applyRepoFilter` & `applyAllWorkFilters`), unified `งาน & บันทึก` queue/failed table, and compact BYOP model rows with `...` action menu.
- Fix empty state in Studio file list (`0 ไฟล์` -> explain & offer Sync button).

### Task 3: Sync `auto_dev_crew/locales/en.json` and update `tests/test_gui_sidebar.py`
- **Files:** `auto_dev_crew/locales/en.json`, `tests/test_gui_sidebar.py`
- Add English translations for all new/updated Thai strings in `en.json`.
- Update `tests/test_gui_sidebar.py` for the 4-menu structure (`overview`, `settings`, `studio`, `work`), clean topbar, and Linear/Modern SaaS tokens.

### Task 4: Verify with `pytest` and Playwright visual screenshots
- Run `python -m pytest -q -k gui` and `tests/test_i18n_english_coverage.py`.
- Restart local GUI server on port `8765`, capture screenshots across all 4 pages (Light, Dark, Desktop `1440x900`, Mobile `390x844`), inspect every screenshot via `read_file`, and update `STATE.md`.

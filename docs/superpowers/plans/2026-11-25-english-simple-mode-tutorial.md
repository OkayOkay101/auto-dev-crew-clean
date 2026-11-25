# English Default, Remove Security Quiz, Simple Mode & Guided Tutorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or OpenRouter Fusion Triad delegation as chosen by user) to implement this plan task-by-task.

**Goal:** Switch default UI/backend language to English, remove the Security Quiz, add Simple Mode (default), and add a 4-step Spotlight Guided Tutorial.

**Architecture:** Backend default language lives in `auto_dev_crew/i18n.py`; frontend i18n loader and fallback live in `auto_dev_crew/static/i18n.js` and `auto_dev_crew/static/index_sidebar.html` backed by `auto_dev_crew/locales/en.json`. Security quiz removal cleans `index_sidebar.html` and `mission_control.js` while keeping a 1-click confirm for `merge-all`. Simple Mode and Guided Tutorial are implemented in `index_sidebar.html` using CSS classes on `document.body` (`simple-mode`), `localStorage` persistence, and an accessible spotlight overlay.

**Tech Stack:** Python (FastAPI/pytest), Vanilla JS, HTML/CSS, JSON locales.

**Spec:** `docs/superpowers/specs/2026-11-25-english-simple-mode-tutorial-design.md`

---

### Task 1: Default Language to English
**Files:**
- Modify: `auto_dev_crew/i18n.py` (`DEFAULT = "en"`)
- Modify: `auto_dev_crew/static/i18n.js` (`var lang = "en";`, fallback `lang = "en"`)
- Modify: `auto_dev_crew/static/index_sidebar.html` (`const uiLang = window.adcLang || "en";`)
- Modify: `tests/test_i18n_core.py`, `tests/test_i18n_english_coverage.py`
- Verify: `python -m pytest -q tests/test_i18n_core.py tests/test_i18n_routes.py tests/test_i18n_js_loader.py tests/test_i18n_english_coverage.py`

### Task 2: Remove Security Quiz & Add 1-Click `merge-all` Confirmation
**Files:**
- Modify: `auto_dev_crew/static/mission_control.js` (remove `QUIZ_ITEMS`, `hasPassedSafetyQuiz`, `guardHighAutonomySelection`; export clean API)
- Modify: `auto_dev_crew/static/index_sidebar.html` (remove `#toolSafety`, `#quizBox`, `#kpiQuiz`, `renderSafetyQuiz()`, `gradeSafetyQuiz()`, and wire `merge-all` 1-click confirm)
- Test: `tests/test_gui_sidebar.py` (verify no `#quizBox` / `QUIZ_ITEMS` and `merge-all` confirm exists)

### Task 3: Add Simple Mode (Default) + Topbar & Settings Toggle
**Files:**
- Modify: `auto_dev_crew/static/index_sidebar.html` (CSS for `body.simple-mode`, Topbar `#modeToggleBtn`, Settings sync, `localStorage` `adc_ui_mode` defaulting to `"simple"`, auto-switch to `overview` if active tab is hidden)
- Modify: `auto_dev_crew/locales/en.json` (add English translations for Simple/Advanced Mode strings)
- Test: `tests/test_gui_sidebar.py`, `tests/test_i18n_english_coverage.py`

### Task 4: Add 4-Step Spotlight Guided Tutorial
**Files:**
- Modify: `auto_dev_crew/static/index_sidebar.html` (Spotlight overlay + tooltip HTML/CSS/JS, Topbar `#tourBtn`, auto-start when `adc_tutorial_done` not set, `Back`/`Next`/`Skip`/`Esc`, `prefers-reduced-motion`)
- Modify: `auto_dev_crew/locales/en.json` (add English translations for all 4 tutorial steps and buttons)
- Test: `tests/test_gui_sidebar.py`, `tests/test_i18n_english_coverage.py`

# Design Spec: English Default, Remove Security Quiz, Simple Mode, and Guided Tutorial

**Date:** 2026-11-25  
**Status:** Approved by user

## Goals
1. **Default language = English**: Make `"en"` the default language across backend (`auto_dev_crew/i18n.py`) and frontend (`auto_dev_crew/static/i18n.js`, `auto_dev_crew/static/index_sidebar.html`), while keeping the EN/TH language switcher in Settings and updating `auto_dev_crew/locales/en.json` to cover all new UI strings.
2. **Remove Security Quiz**: Remove the 5-question safety quiz (`#quizBox`, `renderSafetyQuiz()`, `gradeSafetyQuiz()`, `QUIZ_ITEMS`, `hasPassedSafetyQuiz()`, `adc_safety_quiz_passed`) from Studio/Settings and Mission Control. Keep a simple 1-click confirmation dialog when switching `merge_mode` to `merge-all`.
3. **Simple Mode (default for new users)**: Add a `Simple / Advanced` mode toggle in the Topbar (synced with Settings and persisted in `localStorage` under `adc_ui_mode`, defaulting to `"simple"`).
   - **Simple Mode** hides `Work & Logs` and `Studio` tabs in the sidebar (auto-navigating to `Overview` if currently on a hidden tab), and hides advanced Overview controls (`persona`, `dryRun`, `runLoop`, `restartBtn`, `slotsCard`, `#stats` KPI grid).
   - **Simple Mode** keeps: status card (`bigStatus`, `agentText`, `runOnce`, `stopBtn`, `agentRepoSelect`), `needsCard` ("Waiting for your decision"), `New Task` (`#newTaskBtn`), and `Settings`.
4. **Guided Tutorial (Spotlight Walkthrough)**: Auto-start on first visit (`localStorage` key `adc_tutorial_done`), with a `Tour` button in the Topbar to replay anytime.
   - 4-step spotlight + tooltip walkthrough (`Back`, `Next`, `Skip`, `Esc`, `prefers-reduced-motion` support):
     1. Status & Repository selector (`#agentRepoSelect` / hero card)
     2. Create a new task (`#newTaskBtn`)
     3. Run 1 Task & Review Decisions (`#runOnce` / `#needsCard`)
     4. Switch between Simple & Advanced Mode (`#modeToggleBtn`)

## Non-Goals
- Removing Thai language support.
- Changing backend task execution, merge logic, or API contracts beyond `i18n.DEFAULT`.

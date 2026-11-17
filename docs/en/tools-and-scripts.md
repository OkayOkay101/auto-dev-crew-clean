# Tools, Scripts, and CI

This page covers the scripts in `scripts/`, the MCP server, autonomous mode for Claude Code, tests, and CI.

---

## 1. Scripts in `scripts/`

| File | What it does | How to run |
|---|---|---|
| `gui_smoke.py` | Checks that the GUI starts and the page loads without JavaScript errors. Read-only; does not press run buttons. | `python scripts/gui_smoke.py [--url http://127.0.0.1:8765] [--shot state/gui_smoke.png]` |
| `gui_e2e.py` | Presses the run button in a dry run with Playwright. Use a test repository only. Run when slots are idle. | `python scripts/gui_e2e.py --repo OWNER/NAME` |
| `gui_watchdog.py` | Checks `/api/status`. If it does not answer, starts the GUI again with `--no-browser --auto` in a separate process. | `python scripts/gui_watchdog.py` (it does not schedule itself; set up a repeating task in your operating system if you want it to run regularly) |
| `engine_judge_eval.py` | Evaluates OpenCode engines with an LLM-as-judge, after deterministic checks. | Read the file header for its arguments. |
| `opencode_db_doctor.py` | Checks and repairs `opencode.db` (a workspace table missing `project_id`). Dry run by default. | `python scripts/opencode_db_doctor.py` (add `--apply` to back up and repair; close OpenCode first) |
| `autonomous_ctl.py` | Turns autonomous mode for Claude Code on or off, and shows its status. | See section 3. |
| `autonomous_common.py` | Shared helpers for autonomous mode. | Not run directly. |
| `autonomous_guard_hook.py` | PreToolUse hook that blocks dangerous commands while autonomous mode is on. | Configure as a Claude Code hook. |
| `autonomous_stop_hook.py` | Stop hook that keeps a session going until the flag is removed or the turn limit is reached. | Configure as a Claude Code hook. |

---

## 2. MCP server

`auto_dev_crew/mcp_server.py` is a stdio MCP server with no extra dependencies. It speaks JSON-RPC 2.0 using only the Python 3.12 standard library.

```bash
python -m auto_dev_crew.mcp_server --transport stdio
```

The tools are read-only. They include daemon status, slot status, `merge_mode`, the health of F6 engines, and a summary of PRs merged overnight with pending approval requests.

Use it with any MCP client that supports stdio, and configure the client according to its own documentation.

---

## 3. Autonomous mode (for Claude Code)

This mode lets a Claude Code session keep working toward a mission. It is separate from the Auto Dev Crew runner.

```bash
python scripts/autonomous_ctl.py on --mission "goal of the work"
python scripts/autonomous_ctl.py on --mission-file path/to/mission.md
python scripts/autonomous_ctl.py off
python scripts/autonomous_ctl.py status
```

How it works:
- A flag file at `state/autonomous.flag` turns the mode on. While the flag exists, the mode is active.
- `autonomous_stop_hook.py` stops the session from ending by itself, until the flag is removed or `autonomous.max_turns_per_session` is reached (default 40).
- `autonomous_guard_hook.py` immediately blocks these actions:
  - `git push`
  - `gh pr merge`
  - `gh release`
  - `deploy`
  - `git reset --hard`
  - `git clean` with `-f`
  - recursive or forced `rm`
  - `Remove-Item -Recurse`
  - `del /s`
  - deleting the `autonomous.flag` file
- The hook also blocks Write, Edit, and MultiEdit changes to `state/autonomous.flag` and `.claude/settings*.json`.

**Note:** blocking `git push` blocks every push, not only force-push. Force-push has no separate block.

---

## 4. Tests

### Full test suite
```bash
python -m pytest -q -p no:cacheprovider
```
Latest recorded result (2026-11-18): **1442 passed, 6 skipped** (see `STATE.md`).

The `tests/` folder holds about 170 entries, including test files and some support files.

### Notable test files
| File | What it tests |
|---|---|
| `tests/test_redact.py` | Hiding tokens in logs. |
| `tests/test_loop_helpers.py`, `tests/test_test_gate.py` | The `require_test_for_bugfix` gate. |
| `tests/test_static_gate.py` | The deterministic gate. |
| `tests/test_runner_parallel.py` | Parallel slot behaviour. |
| `tests/test_gui_user_messages_i18n.py` | GUI messages in Thai and English. |
| `tests/test_login_removed.py` | Confirms the password login is gone from the GUI. |

### Manual GUI testing
1. Start the GUI: `python -m auto_dev_crew.gui --no-browser`.
2. Check `curl http://127.0.0.1:8765/api/status` returns JSON.
3. `python scripts/gui_smoke.py` should print `PASS`.
4. `python scripts/gui_e2e.py --repo OWNER/NAME` uses a test repository, and runs only when slots are idle.

---

## 5. CI (GitHub Actions)

The workflow in `.github/workflows/ci.yml` runs on pushes to `main`, on pull requests, and on manual dispatch. It has four jobs:

| Job | Runner | What it does |
|---|---|---|
| `tests` | `windows-latest` | Installs requirements and pytest, then runs `python -m pytest -q`. |
| `lint` | `ubuntu-latest` | Runs ruff with `--select E9,F` to catch syntax errors and pyflakes issues (style is not enforced). |
| `security` | `ubuntu-latest` | Runs pip-audit for dependency vulnerabilities and bandit at `-lll` (blocks only High severity). |
| `ui` | `windows-latest` | Installs Chromium and runs the GUI check through Playwright (`gui_check.run_gui_check`), read-only. |

Notes:
- CI does not run `gui_e2e.py`, because that needs a test repository and a running GUI.
- The `concurrency` setting cancels older runs only for PRs. On `main`, every merge runs to completion.
- The `tests` job sets a CI git identity for tests that use git.

---

## 6. Recommended checks before committing

```bash
python -m pytest -q -p no:cacheprovider
python -m ruff check --select E9,F auto_dev_crew scripts tests
```

If you changed the GUI, also run `python scripts/gui_smoke.py`.

# Control Panel (GUI)

The GUI is a local web server built with Python's `http.server`. It uses no external web framework.

- Address: `http://127.0.0.1:8765/` (change the port with `--port`).
- It is bound to `127.0.0.1` only, so other machines on the network cannot reach it directly.

## 1. GUI security

- **Token:** each time the server starts, it generates a random token (`secrets.token_urlsafe`) and embeds it in the page. Requests that change data (POST) must send this token in the `X-Token` header. This stops other websites open in the same browser from sending commands.
- **Some read endpoints also require the token:** `/api/repo/file-content`, `/api/byop/status`, and `/api/byop/pool`.
- **Body size:** at most 1 MB per request. Larger requests get `413`.
- **Confirmation:** buttons that scan or create issues ask for confirmation first (`confirm()`). Do not bypass this with JavaScript.
- **Limits:** there is no password login in the GUI any more; the login system was removed. Remote access requires an SSH tunnel or another method set up by the administrator.

## 2. The five left-menu pages

### 2.1 Overview
- **▶ Run one job:** do one piece of work, then stop automatically.
- **⟳ Run continuously:** start `--loop` mode; keep working until you press stop or work runs out.
- **■ Stop:** cancel the job in progress. You are asked to confirm.
- **🔄 Restart:** under "More". Cancels the job in progress and starts a new round with the same settings. Open PRs are not closed.
- **Slot cards (3 slots):** show each slot's status; you can assign a persona or repository to a slot.
- **Repository cards:** show each repository with its status, enabled state, and merge level.
- **The `merge:` badge** in the top-right shows the current `merge_mode`.

Before restarting or stopping, check whether slots are idle. If a job is running, it will be cancelled.

### 2.2 Jobs
- **Live log:** the runner's log, updated in real time.
- **Job history:** past jobs. You can open the diff of each one.

### 2.3 Studio
- Ask the AI to change code in a selected repository.
- Review the resulting diff.
- Find `[AI-TODO]` tags and create issues from them.
- Run a deep scan. See [architecture.md](architecture_EN.md#10-deep-scan).
- Feature plans (`ai-plan`). See [github-workflow.md](github-workflow_EN.md#4-feature-plans-ai-plan).

### 2.4 Keys (AI keys)
- View and add provider keys.
- Assign roles: `coder`, `judge`, `scan`.
- Set the failover order of engines.
- See today's usage per engine (from `state/usage.jsonl`).

Details: [providers-and-keys.md](providers-and-keys_EN.md).

### 2.5 Settings
- Merge mode (`review-all`, `small-only`, `merge-all`).
- CI checks (`allow_no_ci`).
- Quality gate (judge) on or off.
- UI language (`th` / `en`).
- **Glossary:** explains the system's terms.
- **Shut down the server.**

## 3. Terms you will see

| Term | Meaning |
|---|---|
| Slot | One worker. Up to three can run in parallel. |
| Judge | The AI that scores code before a PR. Needs a key with the judge role. |
| Gates 1–4 | Checks before a PR is opened. See [architecture.md](architecture_EN.md#6-quality-gates). |
| Key role | `coder` (writes the main code), `judge` (scores), `scan` (looks for problems). |
| F6 failover | Move to the next provider when a quota runs out. |
| `ai-task` | An issue the agent will pick up. |
| `ai-plan` | An issue proposing a feature plan, waiting for approval. |
| Deep scan | The AI reads code section by section and reports problems. |

## 4. Things to know when changing values

- **If you edit `config.yaml` by hand, or change a key role:** restart the agent, and reload the page first. The engine list in the dropdown is read when the page loads.
- **A new `merge_mode`:** applies to the next merge decision. If you edited the file yourself, restart to be certain.
- **Switching to `merge-all`:** the GUI asks for confirmation first.

## 5. Running a runner outside the GUI

If you run `python -m auto_dev_crew --loop` from a terminal, the GUI sees that runner and can stop it with the stop button.

## 6. Testing the GUI

- `python scripts/gui_smoke.py`: read-only check that the page loads with no JavaScript errors. The GUI must be running and slots must be idle.
- `python scripts/gui_e2e.py --repo OWNER/NAME`: presses the run button in a dry run. Use a test repository only, and run only when slots are idle.

Details: [tools-and-scripts.md](tools-and-scripts_EN.md).

## 7. Known limitations

See [troubleshooting.md](troubleshooting_EN.md#2-known-limitations).

# Command-Line Reference

There are two entry points from a terminal:

1. **Runner:** `python -m auto_dev_crew` (the main worker that reads the queue and opens PRs)
2. **GUI:** `python -m auto_dev_crew.gui` (the web control panel, see [gui.md](gui.md))

There are also helper tools: `python -m auto_dev_crew.mcp_server` and the scripts in `scripts/` (see [tools-and-scripts.md](tools-and-scripts.md)).

Run every command from the project root, because `config.yaml` and `.env` are resolved from there.

---

## 1. Runner: `python -m auto_dev_crew`

The entry point `main()` is in `auto_dev_crew/runner.py` (around line 3094).

| Option | Value | Meaning |
|---|---|---|
| `--config <path>` | default: `config.yaml` in the root | Use a different settings file. |
| `--repo <owner/name>` | none | Work only on this repository. |
| `--dry-run` | off | Work locally only. No push, no PR, no comments on GitHub. |
| `--loop` | off | Keep working until there is no more work, the quota runs out, or a stop condition is met. |
| `--persona <name>` | none | Force one persona and skip the issue queue (`bolt`, `sentinel`, `palette`, `quality`). |
| `--slot <1-3>` | none | Run only this slot. |
| `--engine <name>` | none | Override `engine.command` from the config (for example `agy`, `opencode`, `gemini`). |
| `--model <name>` | none | Override `engine.model` from the config (with OpenCode, use `provider/model`). |

Examples:

```bash
# Try locally without touching GitHub
python -m auto_dev_crew --dry-run

# Try only the bolt persona
python -m auto_dev_crew --dry-run --persona bolt

# Do one job and open a PR according to the merge mode
python -m auto_dev_crew

# Keep going
python -m auto_dev_crew --loop

# One repository only
python -m auto_dev_crew --repo OkayOkay101/cyberpunk-pomodoro --dry-run
```

### Recommended first sequence
1. `--dry-run` to see which job is chosen and whether the engine responds.
2. `--dry-run --persona <name>` to see the result of one persona.
3. A real single run, `python -m auto_dev_crew`, then review the PR before using `--loop`.

### What `--dry-run` does not do
- It does not push branches.
- It does not open or merge PRs.
- It does not comment on issues or change their labels.
- It still calls the engine, which may use quota.

---

## 2. GUI: `python -m auto_dev_crew.gui`

| Option | Default | Meaning |
|---|---|---|
| `--port <n>` | `8765` | Port to listen on. The server is bound to `127.0.0.1` only. |
| `--no-browser` | off | Do not open a browser automatically. |
| `--auto` | off | Start the runner in `--loop` mode right away, and restart it automatically when it exits. |
| `--config <path>` | `config.yaml` | Settings file the GUI reads and edits. |
| `--keep-slots` | off | Do not clear slot state at startup. Used when a runner started the GUI itself to check things, because another runner may still be working. |

Examples:

```bash
python -m auto_dev_crew.gui                    # control panel only
python -m auto_dev_crew.gui --auto             # open and start the agent in continuous mode
python -m auto_dev_crew.gui --no-browser --port 8766
```

---

## 3. `--scan-todos`: read-only scan for `[AI-TODO]` tags

```bash
python -m auto_dev_crew --scan-todos OkayOkay101/cyberpunk-pomodoro
```

Prints each `[AI-TODO]` hit as `path:line text` and exits. It never creates issues.

To create issues from the results, use the **Studio** page in the GUI, or schedule scans with `todo_scan.schedule_minutes` (see [configuration.md](configuration.md)).

---

## 4. MCP server: `python -m auto_dev_crew.mcp_server`

| Option | Value | Meaning |
|---|---|---|
| `--transport` | `stdio` (only) | JSON-RPC 2.0 over stdin and stdout. |
| `--config <path>` | `config.yaml` | Alternative settings file. |

The server exposes read-only tools to MCP clients, for example daemon status, slot status, `merge_mode`, the health of F6 engines, and a summary of PRs merged overnight with pending approval requests.

Configure your MCP client as described in its own documentation.

---

## 5. Environment variables and file locations

| Item | Value |
|---|---|
| `.env` | All API keys. Read by `runner.load_dotenv()`. |
| `config.yaml` | Settings. |
| `state/` | State, history, locks, and logs (not committed). |
| `~/.auto-dev-crew/` | External data folder: scratch work, repository cache, and venvs. |

The location `~/.auto-dev-crew/` comes from `auto_dev_crew/data_home.py`. If an older `~/.ai-optimizer/` folder exists and the new one does not, it is moved once.

---

## 6. Stopping and exit

- Stop a `--loop` runner with `Ctrl+C`, from the GUI's stop button, or by opening an issue labeled `ai-pause`.
- Restarting from the GUI cancels the job in progress and starts a new round with the same settings. Open PRs are not closed.

The exit codes for each case have not been catalogued yet.

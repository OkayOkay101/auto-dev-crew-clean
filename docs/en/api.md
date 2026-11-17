# GUI API Reference

The GUI serves an HTTP API at `http://127.0.0.1:<port>`. The web page uses it, and scripts on the same machine can call it too.

This page lists **paths and what they are for**. It does not yet document the request and response schema of each endpoint. For details, read the function that handles the path.

---

## 1. General rules

| Topic | Details |
|---|---|
| Address | Bound to `127.0.0.1` only. |
| Format | JSON for request bodies and responses. |
| Body size | At most 1 MB (larger gets `413`). |
| Content-Length | Must be valid, otherwise `400`. |
| Token | POST requests must send `X-Token` with the value embedded in the page. Otherwise they are refused. |
| GET endpoints that need a token | `/api/repo/file-content`, `/api/byop/status`, `/api/byop/pool` |
| Status codes seen | `200` success, `400` invalid input, `413` body too large. |
| Language | Error messages follow `ui_language`. |

A missing or wrong token is refused (checked in `gui_patches.verify_request_security`).

---

## 2. GET (read)

### Pages
| Path | Meaning |
|---|---|
| `/` | Main control panel. |
| `/static/*` | Static files (HTML, JS, CSS). |

### Status and checks
| Path | Meaning |
|---|---|
| `/api/status` | Agent status, repository and slot information, and more. The `gui_watchdog.py` script uses it to confirm the server answers. |
| `/api/doctor` | System health check. |
| `/api/metrics` | Metrics computed from `history.json`. |
| `/api/log` | The runner's log. |
| `/api/i18n` | Translation strings for the page. |

### Keys and engines
| Path | Meaning |
|---|---|
| `/api/keys` | Keys with their status. |
| `/api/key-roles` | Role assignments for keys. |
| `/api/engines` | Engine list. |
| `/api/engine` | One engine. |
| `/api/models` | Model list. |
| `/api/favorites` | Pinned keys. |

### BYOP (bring your own provider key through OAuth)
| Path | Meaning |
|---|---|
| `/api/byop/callback` | OAuth callback receiver. |
| `/api/byop/status` | Connection status (needs token). |
| `/api/byop/pool` | Key pool (needs token). |

### GitHub
No GitHub endpoints remain (`/api/github/*` was removed on 2026-11-18).

### Repositories and jobs
| Path | Meaning |
|---|---|
| `/api/repos/scan` | Scan the repository list. |
| `/api/repo/workspace` | Workspace of a repository. |
| `/api/repo/file-content` | Contents of a file in a repository (needs token). |
| `/api/diff` | Diff of a job. |
| `/api/slots/assignments` | Persona or repository assigned to each slot. |
| `/api/file-locks` | Files currently locked by jobs. |
| `/api/feature-gen` | Feature plans. |
| `/api/deep-scan` | Deep-scan results. |
| `/api/deep-scan/engines` | Engines used for deep-scan. |
| `/api/deep-scan/auto-issue` | Automatic issue creation settings. |

---

## 3. POST (change data or start work)

Every POST needs `X-Token`. The table below groups endpoints by purpose. The system dispatches them through the `ROUTES` table in `gui.py` (around line 1626).

### Running work
| Path | Meaning |
|---|---|
| `/api/run` | Start work (one job or continuous). |
| `/api/stop` | Stop the job in progress (the page asks for confirmation). |
| `/api/restart` | Restart the agent. |
| `/api/pause` | Pause temporarily. |
| `/api/graceful-drain` | Let the current job finish, then stop. |
| `/api/task` | Submit a new task. |
| `/api/wake-personas` | Wake personas to start work. |
| `/api/merge-mode` | Change the merge mode. |
| `/api/slots/assign` | Assign a persona or repository to a slot. |
| `/api/parallel/active-slot` | Set the selected slot. |

### Repositories
| Path | Meaning |
|---|---|
| `/api/repos/add` | Add a repository. |
| `/api/repos/remove` | Remove a repository from the config. |
| `/api/repos/delete` | Remove a repository from the AI system (does not delete code on GitHub; the page asks first). |
| `/api/repos/toggle` | Enable or disable a repository. |
| `/api/repos/scan` | Scan a repository. |
| `/api/repos/bootstrap-ci` | Install CI in a repository. |
| `/api/repos/bootstrap-ci-plan` | Show the CI installation plan before doing it. |
| `/api/repo/sync` | Sync a repository. |
| `/api/repo/run-command` | Run a command in a repository. |
| `/api/repo/dispatch-task` | Send a task to a repository. |
| `/api/revert/plan` | Plan a PR revert. |
| `/api/ci/toggle` | Turn CI checks on or off. |
| `/api/ci/bootstrap-toggle` | Turn automatic CI installation on or off. |
| `/api/evaluation/toggle` | Turn the judge on or off. |

### Keys and engines
| Path | Meaning |
|---|---|
| `/api/keys` | Add or change keys. |
| `/api/keys/ping` | Test a key. |
| `/api/key/delete` | Delete a key. |
| `/api/key/reset` | Reset a key's status. |
| `/api/key/favorite` | Pin a key. |
| `/api/key/roles` | Set a key's roles. |
| `/api/provider/add` | Add a provider (see [providers-and-keys.md](providers-and-keys.md)). |
| `/api/engine/create` | Add an engine. |
| `/api/engine/update` | Change an engine. |
| `/api/engine/delete` | Delete an engine. |
| `/api/engine/reorder` | Change the failover order. |
| `/api/engine-model` | Change an engine's model. |
| `/api/models` | Manage the model list. |

### BYOP
| Path | Meaning |
|---|---|
| `/api/byop/start` | Start authorization. The server builds the redirect URI from its own port; the client cannot supply it. |
| `/api/byop/callback` | Callback receiver (see GET). |
| `/api/byop/status` | Status (see GET). |
| `/api/byop/pool` | Key pool (see GET). |
| `/api/byop/keys/select` | Select a key. |
| `/api/byop/keys/scan` | Scan keys. |
| `/api/byop/keys/remove` | Remove a key. |
| `/api/byop/models/add` | Add a model. |
| `/api/byop/models/remove` | Remove a model. |
| `/api/byop/models/promote` | Promote a model. |
| `/api/byop/models/roles` | Set model roles. |
| `/api/byop/models/catalog` | Show the model catalog. |
| `/api/byop/models/test` | Test a model. |
| `/api/byop/disconnect` | Disconnect. |

### Scanning and feature plans
| Path | Meaning |
|---|---|
| `/api/deep-scan` | Start a deep scan. |
| `/api/deep-scan/file` | Scan one file. |
| `/api/deep-scan/dismiss` | Dismiss an unwanted finding. |
| `/api/deep-scan/auto-issue` | Set automatic issue creation. |
| `/api/todo-scan` | Scan for `[AI-TODO]`. |
| `/api/feature-gen/propose` | Ask the AI to propose a feature plan. |
| `/api/feature-gen/approve` | Approve a plan (creates `ai-task` issues). |
| `/api/feature-gen/settings` | Plan settings (including `merge_level`). |
| `/api/context-slicer/preview` | Preview the context that would be sent to the AI. |
| `/api/mcp/preview` | Preview MCP data. |
| `/api/playground/reset` | Reset the playground. |

### GitHub
No GitHub endpoints remain (`/api/github/*` was removed on 2026-11-18).

### System
| Path | Meaning |
|---|---|
| `/api/settings/language` | Set UI language to `th` or `en` (writes `ui_language` into `config.yaml`). |
| `/api/server/shutdown` | Shut down the server. |

---

## 4. Example with curl

Get the token only from the page or from code that embeds it. Never write a token value into documentation.

```bash
# Read status (GET needs no token)
curl http://127.0.0.1:8765/api/status

# Stop work (POST needs X-Token)
curl -X POST http://127.0.0.1:8765/api/stop -H "X-Token: <value from the page>" -H "Content-Type: application/json" -d "{}"
```

---

## 5. Cautions

- Endpoints that start real work can use quota or change GitHub. When unsure, use `--dry-run` or the GUI.
- Deleting a key cannot be undone. `/api/repos/delete` only removes a repository from the AI system; it does not delete code on GitHub.
- Do not expose the server to an external network without additional protection.

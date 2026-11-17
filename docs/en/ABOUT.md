# About Auto Dev Crew

This document explains what the program does, how it works, where AI is used (both to build it and at runtime), and which parts of the GUI are still incomplete. Installation steps and commands are in the [README](../../README.md). Requirements are in [REQUIREMENTS.md](../../REQUIREMENTS.md), which is an early draft (see [the index](README.md)).

> Status: **experimental project, not production-ready.** The repository is private.

---

## 1. What it does

Auto Dev Crew is a coding agent that runs on the owner's own machine. It works like a junior developer who never sleeps:

- **Takes work from GitHub issues.** Open an issue in a target repository and add the label `ai-task`. The agent picks it up, edits the code, runs the tests, and opens a Pull Request.
- **Looks for improvements by itself.** When the queue is empty, four personas scan the code for problems within their own focus and create work for themselves:
  - `bolt`: performance
  - `sentinel`: security
  - `palette`: UX and UI
  - `quality`: tests and code quality
- **Lets you control merging.** Choose whether a human merges (`review-all`), the agent merges only small PRs that do not touch sensitive paths (`small-only`), or the agent merges every PR once CI passes (`merge-all`).

The project is designed to run at zero cost by rotating between several AI providers when a free quota runs out.

---

## 2. How it works (overview)

```
GitHub issue (ai-task)  or  deep-scan / persona
        │
        ▼
  runner.py: job queue (up to 3 slots in parallel)
        │  clone repo → separate venv per repo
        ▼
  AI coder edits code (Antigravity CLI, with fallback providers via F6)
        │
        ▼
  local tests + quality gates 1–4 (judge, file checks, re-check)
        │
        ▼
  open Pull Request → CI on GitHub → merge according to mode
```

### Main components

| Component | Role |
|---|---|
| `auto_dev_crew/runner.py` | Queue, clone, engine calls, tests, PRs, merging, reports |
| `auto_dev_crew/gui.py` | Local web GUI (`127.0.0.1:8765`) to start work, read logs, and change settings |
| `auto_dev_crew/providers.py`, `keys.py` | AI provider registry and key management |
| `auto_dev_crew/routing.py` | Orders engines by past merge results (`state/history.json`) |
| `auto_dev_crew/redact.py` | Hides tokens and keys before they are shown or logged |
| `auto_dev_crew/static_gate.py`, `quality_gates.py` | Safety and quality checks before a PR is opened |
| `prompts/` | Prompts for issue work, test repair, and the four personas (`_rules.md` holds the shared rules) |

### Concepts to know

- **Slots:** up to three jobs run at the same time. Slot 1 handles issues you request. Slots 2 and 3 handle personas or extra issues.
- **F6 failover:** when one provider's quota is used up, the agent moves to the next engine in the configured order.
- **Quality gates 1–4:** gate 1, the judge confirms a bug is real before a fix; gate 2, the judge reviews the whole file after the fix; gate 3, a repair round must touch the files named in the issue; gate 4, deep-scan re-checks findings before an issue is created. (This is the description used in the GUI; see [architecture](architecture.md#6-quality-gates).)
- **ai-plan:** a proposed feature waiting for approval. When approved, the system creates `ai-task` issues for it.
- **ai-pause:** add this label to any issue to stop new work in that repository.
- **Memory:** `state/history.json` records what was already proposed and how it turned out. It is not committed.

### Boundaries and safety

- The GUI listens only on `127.0.0.1`. Actions that change data (POST) need a token embedded in the page.
- API keys live in `.env`, which is git-ignored.
- Autonomous-mode hooks for Claude Code block `git push`, `gh pr merge`, `git reset --hard`, and recursive deletes. They do **not** single out force-push.
- Code written by the agent must pass tests, quality gates, and CI before merging. It has **not** undergone a professional security audit.

---

## 3. How AI was used to build this program

**This program was built with help from AI.** The developer used Claude Code (a Claude model) as a coding assistant to write and change code, under the developer's direction.

- Many parts of the project were done together with AI: the GUI translation, removing the password login, and fixing a flaky test. Progress is recorded in `STATE.md` and `docs/superpowers/`.
- The developer set the goals, made architecture decisions, and checked the results.
- The most recent recorded test run (2026-11-18) was `pytest`: **1442 passed, 6 skipped**.
- **AI-written code can still contain bugs or security issues nobody has found yet.** Read and test it before relying on it.

The program **also uses AI while it runs**. It sends code from the target repository to the configured AI providers (Antigravity, OpenCode, NVIDIA Build, Pollinations.ai, Mistral, and others). Code from those repositories therefore leaves your machine and is processed by those providers under their terms.

---

## 4. The GUI is not finished

The GUI works overall, but it is **not complete**. Known gaps:

| Area | Status |
|---|---|
| Language (Thai/English) | Main GUI text and backend error messages are translated. **Logs, PR bodies, and print output stay in Thai** by design. |
| Login | The password login was removed. The GUI relies on binding to `127.0.0.1`. |
| `/classic` page | Still present. Waiting for a decision: keep or remove. |
| `/api/github/*` and `github_login.py` | Still present, but the UI does not use them. Waiting for a decision. |
| Convergence check | `check_convergence` runs in the repair loop when `evaluation.plateau_stop` is enabled (default). |
| Simple mode | Removed by decision. |
| Browser coverage | Tested in a local browser; not tested across all browsers and screen sizes. |

If you find a GUI problem that is not in this table, treat it as not yet checked and report it.

---

## 5. Before you use it

- **Never commit or share `.env`.** Do not print key values into logs or chat.
- `config.yaml` holds owner-specific settings and should not be committed to a public repository. It is currently tracked in this private repo.
- Automatic merging (`merge-all`) can put unreviewed code into the main branch. Start with `review-all`.
- Run `--dry-run` first whenever you change settings or add a new repository.

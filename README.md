# Auto Dev Crew 🤖

A background coding agent that takes work from GitHub issues and opens pull requests. When its queue is empty, it lets its personas (⚡🛡️🎨🧪) look for improvements on their own.
It uses the **Antigravity CLI (`agy`)** with a Google AI Pro account as the main engine, and supports **Multi-Engine Failover (F6)**: when a quota runs out, it switches automatically to OpenCode or NVIDIA Build (primary) and Pollinations.ai or Mistral (backup). Budget: 0 THB.

Full requirements: [REQUIREMENTS.md](REQUIREMENTS.md) (early draft, kept as design history; see the note below).
Detailed description, AI usage, and GUI status: [docs/en/ABOUT.md](docs/en/ABOUT.md)
Thai version of this README: [README.th.md](README.th.md) · Thai docs: [docs/README.md](docs/README.md)

## Install (once)
1. Install Python 3.12+, Git, the GitHub CLI (`gh auth login`), and the Antigravity CLI (signed in with the AI Pro account).
2. `pip install -r requirements.txt`
3. Edit `config.yaml` (repo, merge mode, personas).

## How to give work
- Open an issue in the target repo and add the label **`ai-task`** (only the `owner` account set in the config counts).
- Emergency stop: open any issue and add the label **`ai-pause`** (close the issue to resume).

## GUI (local web page)
```bash
python -m auto_dev_crew.gui          # opens http://127.0.0.1:8765 automatically
python -m auto_dev_crew.gui --auto   # same, plus starts the agent in --loop mode right away
# (the Desktop button / start-auto-dev-crew.bat opens the GUI and waits for you to press start)
```
The main page is `http://127.0.0.1:8765/`. The left menu has 5 pages:
- **Overview**: press **▶ Run 1 task** (does one item and stops) or **⟳ Run continuously** (keeps going until you stop). **■ Stop** cancels the current task (asks for confirmation). **🔄 Restart** is under "More". Shows the 3 work slots and a card for each repo.
- **Jobs**: live logs and job history (view diffs).
- **Studio**: ask the AI to change code in a chosen repo, view diffs, find `[AI-TODO]`, run a deep scan, and make feature plans (`ai-plan`).
- **AI keys**: keys and providers, failover order, recent usage.
- **Settings**: merge mode, CI checks, quality checks (judge), the full glossary, and shutting down the server.

The GUI only listens on this machine (127.0.0.1). Requests that change data (POST) need a token embedded in the page.

**Restart the agent when**: you edit `config.yaml` directly, or change a key's role (Coder/Judge/Scan). Press restart on the Overview page (this cancels the current task and starts a new round with the same settings; open PRs are not closed).
- After changing a key's role, **reload the page** first, because the engine list in the dropdown is read when the page loads, and then restart.
- Before restarting or stopping, check on the Overview page whether the slots are empty. If a task is running, it will be cancelled.
- If you run `python -m auto_dev_crew --loop` outside the GUI yourself, the GUI will see that runner and you can stop it with the stop button.

**Key terms** (full list on Settings › Glossary):
- **Slot**: one worker. Up to 3 can run in parallel. Slot 1 handles issues you request; slots 2–3 look for improvements on their own according to their persona.
- **judge**: the AI that scores the changed code before a PR is opened. Needs a key with the Judge role.
- **Gates 1–4**: Gate 1, the judge confirms the bug before a fix · Gate 2, the judge sees the full file after the fix · Gate 3, every issue run that names a file must touch that file · Gate 4, deep-scan re-checks before an issue is created.
- **key role**: Coder = writes the main code (default for every key) · Judge = scores · Scan = looks for problems. Variable names containing `_JUDGE` or `_SCAN` get that role automatically if you do not set it yourself.
- **F6 failover (fallback order)**: switch to the next provider when a quota runs out. The top one is tried first.
- **ai-task**: an issue the agent picks up (you requested it, or the system created it from deep-scan or an approved plan).
- **ai-plan**: an issue proposing a feature that waits for approval. Once approved, the system creates an `ai-task` for it.
- **deep-scan**: the AI reads the code section by section and reports problems. Results that pass Gate 4 can become `ai-task` issues. Gate 4 applies only to automatic issue creation; the per-finding create button skips it.
- **check_convergence** (`auto_dev_crew/evaluator.py`): checks whether the score has stopped improving. It runs in the repair loop after evaluation (`runner.py`) when `evaluation.plateau_stop` is true (the default). If the score does not improve, the repair rounds stop and no more quota is spent.

## Command-line usage
```bash
python -m auto_dev_crew --dry-run                 # try locally, does not touch GitHub
python -m auto_dev_crew --dry-run --persona bolt  # try one persona
python -m auto_dev_crew                           # do one task, then open a PR
python -m auto_dev_crew --loop                    # keep going until no work / quota out / PRs pending
```

Personas: `bolt` (performance) · `sentinel` (security) · `palette` (UX/UI) · `quality` (tests/quality)

## Merge modes (`merge_mode` in config.yaml or the Settings page)
This is the global default for the whole system. The mode in use is shown in the `merge:` badge at the top right of the GUI and in the Settings page. The code reads this value directly from config.yaml, so the file must always contain it.

| Mode | Result |
|---|---|
| `review-all` | Only opens PRs. The system does not merge. A person merges. |
| `small-only` | Merges by itself only small PRs (no more than `small_pr.max_lines` lines; the value in config.yaml is 50) that do not touch `small_pr.protected_paths`, such as `.github/` and `requirements*`. Everything else waits for review. |
| `merge-all` | Merges every PR by itself when CI passes. The GUI asks for confirmation before switching to this mode. |

- **Merge level per repo** (set in a new feature plan in the GUI, or `merge_level` per repo): if a repo has its own level, that level is used instead of the global mode.
- **New values apply to the next merge decision** (the system rereads the config while it runs). If you edit the file yourself, restart to be sure.

## CI check before merge (`ci.allow_no_ci` global, can be set per repo)
- **Flexible** (`allow_no_ci: true`): a repo with no CI on GitHub can merge once the local tests pass.
- **Strict** (`allow_no_ci: false`): a repo with no CI never merges. CI must exist and pass on GitHub.
- In both cases: if CI exists and fails, nothing merges. If a workflow exists but no check has run on the PR yet, the system waits for the next round.

## judge (quality check before a PR is opened)
The judge is an AI that scores the diff. It passes when the score reaches the threshold and it meets the safety and task-match conditions. It needs a key with the `judge` role (the system chooses keys by role). You can turn it off on the Settings page.

## Harness settings
These are set under `context` in `config.yaml`. You do not need to edit the file; the defaults are in the code.
- `context.repo_map` (default `true`): attaches the structure of Python code (function and class names and signatures) to the prompt. Set to `false` to turn it off.
- `context.repo_map_chars` (default `6000`): maximum characters for the repo map.
- `loop.require_test_for_bugfix` (default `true`): a bug fix (an issue containing "bug" or "fix") that does not touch any test file gets one more round in which the agent adds a regression test, before the result is evaluated. Set to `false` to turn it off.
- `routing.enabled` (default `true`): orders the engines by merge results in the job history (`state/history.json`), separately for each triage path. An engine with at least `routing.min_samples` summarized results moves up first (sorted by merge rate, high to low). The rest keep their order from config.yaml. Set to `false` to always use the order in config.yaml.
- `routing.min_samples` (default `5`): minimum number of summarized results per engine before its data is used for ordering.
- `routing.demote_below` (default `0.2`): an engine whose merge rate is below this value (and that has enough samples) moves to the end, after engines with no data yet. No engine is removed.

If the repo contains `AGENTS.md`, `CLAUDE.md`, or `.github/copilot-instructions.md`, it is attached automatically as "Repository Notes" (up to 4000 characters).

## Files
- `auto_dev_crew/runner.py`: job queue, clone, calling the agent, tests, PRs, merge, reports
- `prompts/`: prompts for issue work, test fixes, and the 4 personas (`_rules.md` = shared rules)
- `state/history.json`: memory of what was already proposed (not committed)
- Temporary work: `~/.auto-dev-crew/work`; the venv for each repo: `~/.auto-dev-crew/venvs`

## Important rules
- Never force-push, and never push straight to `main`. Merge only through a PR.
- Never commit `config.yaml` (it holds owner-specific values).
- Never print or copy values from `.env`. You may check only variable names or lengths.
- Never delete or skip tests. If a test looks wrong, stop and ask the owner.
- The scan and create-issue buttons in the GUI ask for `confirm()` first. Do not bypass this with JavaScript.
- Agent branches start with `ai/` and can open PRs (the name `self/*` is used only in revert plans).

## Check that the system still works
1. Full test suite: `python -m pytest -q -p no:cacheprovider` (there must be no failures).
2. Open the GUI: `python -m auto_dev_crew.gui --no-browser`, then `curl http://127.0.0.1:8765/api/status` should return JSON.
3. Smoke test (the GUI must be open and a slot free): `python scripts/gui_smoke.py` should print `PASS`. This step only reads and does not press run buttons.
4. e2e test (the GUI must be open and a slot free): `python scripts/gui_e2e.py --repo OWNER/NAME` presses the run button in a real dry run. Run it only when a slot is free, because if a slot is busy it may collide with a running task.

> **Note:** [REQUIREMENTS.md](REQUIREMENTS.md) is an early v0.2 draft. The system now uses the Antigravity CLI (`agy`) as the main engine and does not run on GitHub Actions as that draft describes. Read it as design history, not as the current specification.

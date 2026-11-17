# Auto Dev Crew 🤖

**Auto Dev Crew is a local AI coding agent.** It takes work from GitHub issues and opens pull requests for that work. When its queue is empty, four personas (⚡🛡️🎨🧪) scan the code on their own and look for improvements.

**Languages:** English (this file) · [ภาษาไทย](README_TH.md)

It uses the **Antigravity CLI (`agy`)** with a Google AI Pro account as its main engine, and supports **Multi-Engine Failover (F6)**: when a quota runs out, it switches to the next engine in the failover order (for example OpenCode, NVIDIA Build, Pollinations.ai, or Mistral). The engine list lives in `config.example.yaml`.

> **Status:** experimental project, private repository.

- Full requirements: [REQUIREMENTS.md](REQUIREMENTS.md) (early draft, kept as design history; see the note at the end).
- Detailed description, AI usage, and GUI status: [docs/en/ABOUT.md](docs/en/ABOUT.md)
- More English docs: [docs/en/README.md](docs/en/README.md)

## Requirements
- Python 3.12 (the version used by CI in `.github/workflows/ci.yml`)
- Git
- GitHub CLI (`gh`), signed in with `gh auth login`
- Antigravity CLI (`agy`), signed in with the AI Pro account
- Python packages in `requirements.txt`: `pyyaml`, `ruamel.yaml`, `playwright`

## Install
1. Install the requirements above.
2. From the project folder, run `pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` and edit it (owner, repo, merge mode, personas). `config.yaml` is not committed; the example file is the tracked template.

## How to give work
- Open an issue in the target repo and add the label **`ai-task`**. Only the account set as `owner` in the config counts.
- Emergency stop: open any issue and add the label **`ai-pause`**. Close the issue to resume.

## GUI (local web page)
```bash
python -m auto_dev_crew.gui          # opens http://127.0.0.1:8765 in the browser
python -m auto_dev_crew.gui --auto   # same, and starts the agent in --loop mode at once
```
Options in `auto_dev_crew/gui.py`: `--port` (default `8765`), `--no-browser`, `--auto`, `--config`, `--keep-slots`.

The GUI listens only on `127.0.0.1`. Requests that change data (POST) need a token embedded in the page.

The GUI has five pages: **Overview** (run one task or run continuously, stop, restart), **Jobs** (live logs and job history), **Studio** (ask the AI to change code, view diffs, deep scan, feature plans), **AI keys** (keys, providers, failover order), and **Settings** (merge mode, CI checks, quality checks, glossary).

For the full page-by-page guide, see [docs/en/gui.md](docs/en/gui.md).

## Command line
```bash
python -m auto_dev_crew --dry-run                 # try locally, does not touch GitHub
python -m auto_dev_crew --dry-run --persona bolt  # try one persona
python -m auto_dev_crew                           # do one task, then open a PR
python -m auto_dev_crew --loop                    # keep going until no work, quota out, or PRs pending
python -m auto_dev_crew --scan-todos owner/repo   # list [AI-TODO] items; does not create issues
```
Other flags (from `auto_dev_crew/runner.py`): `--config`, `--repo owner/name`, `--persona`, `--slot 1|2|3`, `--engine`, `--model`.

Personas: `bolt` (performance) · `sentinel` (security) · `palette` (UX/UI) · `quality` (tests and code quality).

## Configuration
Settings live in `config.yaml`. Key settings and their defaults (from `config.example.yaml` and the code):

| Setting | Default | Meaning |
|---|---|---|
| `merge_mode` | `review-all` | `review-all`: only opens PRs · `small-only`: merges small PRs by itself · `merge-all`: merges when CI passes |
| `small_pr.max_lines` | `50` | Maximum changed lines for a "small" PR (used by `small-only`) |
| `small_pr.protected_paths` | `.github/`, `requirements`, `.jules/quality`, `config` | Paths that never count as small |
| `ci.allow_no_ci` | `true` | If `true`, a repo with no CI can merge after local tests pass; if `false`, CI must exist and pass |
| `parallel.slots` | `3` | Number of parallel slots |
| `max_fix_attempts` | `3` | Maximum fix attempts |
| `loop.require_test_for_bugfix` | `true` | A bug fix that touches no test file gets one more round to add a regression test |
| `routing.enabled` | `true` | Orders engines by past merge results |
| `routing.min_samples` | `5` | Results needed per engine before its data is used for ordering |
| `routing.demote_below` | `0.2` | Engines with a lower merge rate move to the end (none are removed) |
| `context.repo_map` | `true` | Adds Python function and class signatures to the prompt |
| `context.repo_map_chars` | `6000` | Maximum size of the repo map |

Merge levels can also be set per repo in `config.yaml` (`merge_level`). A repo-level level replaces the global `merge_mode`.

Environment variables are read from `.env`. Do not copy values from `.env` into issues, logs, or docs; check only variable names.

For the full list, see [docs/en/configuration.md](docs/en/configuration.md).

## Tests
```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```
This is the same command CI runs. The `tests/` folder holds about 170 test files.

## Project layout
- `auto_dev_crew/`: the package. `runner.py` holds the job queue, clone, agent call, tests, PRs, merge, and reports. `gui.py` is the local web GUI.
- `prompts/`: prompts for issue work, test fixes, and the four personas. `_rules.md` holds the shared rules.
- `scripts/`: helper scripts, such as `gui_smoke.py` and `gui_e2e.py`.
- `tests/`: pytest test suite.
- `docs/`: Thai documentation. `docs/en/`: English documentation.
- `config.example.yaml`: the tracked config template.
- `state/`: local job history (`state/history.json`). It is not committed.
- Temporary work: `~/.auto-dev-crew/work`. Per-repo virtual environments: `~/.auto-dev-crew/venvs`.

## Important rules
- Never force-push, and never push straight to `main`. Merge only through a PR.
- Never commit `config.yaml`.
- Never delete or skip tests. If a test looks wrong, stop and ask the owner.
- Agent branches start with `ai/`.

## Check that the system works
1. Run the test suite: `python -m pytest -q`. It must report no failures.
2. Open the GUI without a browser: `python -m auto_dev_crew.gui --no-browser`. Then `curl http://127.0.0.1:8765/api/status` should return JSON.
3. Smoke test (GUI open and a slot free): `python scripts/gui_smoke.py` should print `PASS`. It only reads and does not press run buttons.
4. End-to-end test (GUI open and a slot free): `python scripts/gui_e2e.py --repo OWNER/NAME` presses the run button in a real dry run. Run it only when a slot is free.

> **Note:** [REQUIREMENTS.md](REQUIREMENTS.md) is an early v0.2 draft. The system now uses the Antigravity CLI (`agy`) as the main engine and does not run on GitHub Actions as that draft describes. Read it as design history, not as the current specification.

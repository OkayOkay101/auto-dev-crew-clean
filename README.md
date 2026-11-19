# Auto Dev Crew 🤖

**Auto Dev Crew is a local AI coding agent.** It takes work from GitHub issues and opens pull requests for that work. When no issues are waiting, four [personas](docs/glossary_EN.md) scan the code and look for improvements.

**Languages:** English (this file) · [ภาษาไทย](README_TH.md)

> **Status:** experimental project, private repository.

## Requirements
- Python 3.12 (the version CI uses)
- Git
- GitHub CLI (`gh`), signed in with `gh auth login`
- Antigravity CLI (`agy`), the main AI engine
- Python packages listed in `requirements.txt`

## Install
1. Install the requirements above.
2. From the project folder, run `pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` and set `owner` to your GitHub login. `config.yaml` stays on your machine and is never committed.

## Give the agent work
- Open an issue in the target repository and add the label `ai-task`. Only issues opened by the `owner` account count.
- To stop the agent, add the label `ai-pause` to any open issue. Close that issue to resume.

## Run it
Open the local web GUI. It listens only on `127.0.0.1`:
```bash
python -m auto_dev_crew.gui
```
It opens http://127.0.0.1:8765 in your browser. Options: `--port`, `--no-browser`, `--auto`.

![Auto Dev Crew main page](docs/images/gui_main.png)

Or use the command line:
```bash
python -m auto_dev_crew --dry-run   # try locally; does not touch GitHub
python -m auto_dev_crew             # do one task, then open a PR
python -m auto_dev_crew --loop      # keep going until no work is left
```

## Settings to change first
| Setting | Default | Meaning |
|---|---|---|
| `owner` | `example-owner` (placeholder) | Your GitHub login. Only issues from this account are picked up. |
| `merge_mode` | `review-all` | `review-all` only opens PRs · `small-only` merges small PRs · `merge-all` merges when CI passes |
| `parallel.slots` | `3` | Number of parallel slots |

Provider API keys go in `.env`. Copy variable names from `.env.example`. Never paste key values into issues, logs, or docs.

## Run the tests
```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

## Project layout
- `auto_dev_crew/`: the Python package. `runner.py` runs the job queue. `gui.py` is the local web GUI.
- `prompts/`: prompts for issue work, test fixes, and the personas.
- `skills/`: skill folders (each has a `SKILL.md`). The skill registry loads them from here.
- `scripts/`: helper scripts, such as `gui_smoke.py` and `gui_e2e.py`.
- `tests/`: the pytest suite.
- `docs/`: documentation. Each page has an English file and a Thai file with the same name, for example `glossary_EN.md` and `glossary_TH.md`.
- `config.example.yaml`: the tracked config template. You create `config.yaml` from it on your machine.
- `state/`: local job history. It is not committed.

## Learn more
- [Glossary](docs/glossary_EN.md): short definitions of project terms.
- [Documentation index](docs/README_EN.md): every page. Start with the [About page](docs/ABOUT_EN.md).
- [Configuration](docs/configuration_EN.md): every setting and its default.
- [GUI guide](docs/gui_EN.md) and [command line](docs/cli_EN.md).
- [Contributing](CONTRIBUTING.md): rules, checks, and project layout.
- [REQUIREMENTS.md](REQUIREMENTS.md): early design draft, kept as history. It is not the current spec.

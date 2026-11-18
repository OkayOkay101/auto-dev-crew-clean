# Contributing

This page is for people who change the code. To use the program, start with the [README](README.md). Terms are defined in the [glossary](docs/glossary_EN.md).

## Set up

1. Use Python 3.12, the version CI uses (`.github/workflows/ci.yml`).
2. Install the requirements and pytest:
   ```bash
   python -m pip install -r requirements.txt pytest
   ```
3. Copy the example config. `config.yaml` is local only and is never committed:
   ```bash
   cp config.example.yaml config.yaml
   ```

## Before you commit

Run the same checks CI runs:

```bash
python -m pytest -q
python -m ruff check --select E9,F auto_dev_crew scripts tests
```

Install ruff with `python -m pip install ruff==0.17.1` (the version pinned in CI). CI runs the test job on Windows, so tests that use paths or processes should pass there too.

If you changed the GUI, also run `python scripts/gui_smoke.py` while the GUI is open (see [tools-and-scripts.md](docs/tools-and-scripts_EN.md)).

## Rules

- Never commit `config.yaml`, `.env`, or any key.
- Never force-push.
- Never push straight to the default branch. Merge only through a pull request.
- Never delete or skip a test. If a test looks wrong, stop and ask the owner.
- Branches that the agent creates start with `ai/`. Name your own branches differently.

## Project layout

- `auto_dev_crew/`: the package. `runner.py` runs the job queue, clone, agent call, tests, PRs, merge, and reports. `gui.py` is the local web GUI.
- `prompts/`: prompts for issue work, test fixes, and the personas.
- `scripts/`: helper scripts, such as `gui_smoke.py` and `gui_e2e.py`.
- `tests/`: the pytest suite.
- `docs/`: documentation. Each page has an English file (`NAME_EN.md`) and a Thai file (`NAME_TH.md`) with the same name.
- `config.example.yaml`: the tracked config template.
- `state/`: local job history (`state/history.json`). It is not committed.

## Where things are

- [docs/architecture_EN.md](docs/architecture_EN.md): how one job flows through the runner, the slots, the quality gates, and the merge decision.
- [docs/configuration_EN.md](docs/configuration_EN.md): every setting and its default.
- [docs/tools-and-scripts_EN.md](docs/tools-and-scripts_EN.md): the test suite, CI jobs, and helper scripts.
- [docs/github-workflow_EN.md](docs/github-workflow_EN.md): labels, the life of an issue, and feature plans.
- `prompts/`: the prompts for issue work, test fixes, and personas. `prompts/_rules.md` holds the rules the agent follows when it edits code.

## Pull requests

Describe what changed and why. Include the output of the checks above. A bug fix should come with a test that fails before the fix and passes after it.

## Documentation

When you change an English page, change its Thai pair with the same name in the same pull request. Keep the headings and links in the same order in both files of a pair. The root `README.md` and `README_TH.md` follow the same rule.

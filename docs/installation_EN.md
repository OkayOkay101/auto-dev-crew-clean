# Installation

This page covers preparing a machine and running Auto Dev Crew for the first time.

## 1. Requirements

| Item | Why |
|---|---|
| Windows (the tested platform) | The runner, GUI, and process handling are designed for Windows. CI also runs on `windows-latest`. |
| Python 3.12 | CI uses 3.12 and the code targets this version. |
| Git | Cloning target repositories and creating branches and PRs. |
| GitHub CLI (`gh`) | The runner calls `gh` for issues, PRs, and labels. It must be logged in. |
| Antigravity CLI (`agy`) | The main coder engine in the default configuration. |
| A GitHub account that owns the work | Only issues written by the account named as `owner` in the config are picked up. |
| Optional: Node.js / OpenCode | Needed only if you enable OpenCode-based engines or providers that require it. |

## 2. Log in to GitHub CLI

```bash
gh auth login
gh auth status
```

You should see `Logged in to github.com`, with the `repo` scope. Without `repo`, the runner cannot open PRs or manage labels.

## 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` contains three packages:

| Package | Used for |
|---|---|
| `pyyaml>=6` | Reading `config.yaml` |
| `ruamel.yaml>=0.18` | Writing `config.yaml` while keeping comments and key order |
| `playwright>=1.65` | GUI smoke tests (`scripts/gui_smoke.py`) and the UI job in CI |

After the first install of Playwright, install the Chromium browser for the smoke test:

```bash
python -m playwright install chromium
```

This step is not needed to run the agent normally, only the GUI tests.

## 4. Configure `config.yaml`

The file lives in the project root and has defaults that work out of the box, but change at least:

1. `owner`: your GitHub username (default `example-owner`).
2. `repos`: the target repositories, in `owner/name` form.
3. `engines`: enable only the engines you have keys or executables for (`enabled: true`).

Every key is explained in [configuration.md](configuration_EN.md).

**Caution:** `config.yaml` is no longer tracked by git (removed from the index in `6d9e186`). Use `config.example.yaml` as the template and keep owner-specific values on your machine only. See [troubleshooting.md](troubleshooting_EN.md#2-known-limitations).

## 5. Set API keys

Keys live in a `.env` file in the project root. The file is git-ignored.

```bash
# Example variable names (put the real values in yourself; never paste them into chat or commit them)
POLLINATIONS_API_KEY_1=
NVIDIA_API_KEY_1=
```

- The standard name is `<PROVIDER>_API_KEY_<n>`. The provider name is upper-cased and `-` becomes `_`.
- You can also add keys from the **Keys** page in the GUI. The system writes them to `.env` for you.
- Never print or copy values from `.env`. You may check only variable names and value lengths.

## 6. Check that everything works

```bash
python -m auto_dev_crew --dry-run
```

`--dry-run` works locally only. It does not push, open PRs, or comment on GitHub. Use it to confirm that the config, keys, git, and `gh` work.

Then check system health from the GUI (`/api/doctor`) or the **Settings** page.

## 7. Open the control panel (GUI)

```bash
python -m auto_dev_crew.gui
```

This opens `http://127.0.0.1:8765/` automatically. See [gui.md](gui_EN.md).

On Windows you can also double-click `start-auto-dev-crew.bat`. It starts the GUI in a minimized window. If the server is already running, it just opens the page.

## 8. Common installation problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `gh: command not found` | GitHub CLI is not installed or not on PATH | Install `gh`, then open a new terminal |
| `gh` is logged in but PRs fail | The token lacks the `repo` scope | `gh auth refresh -s repo` |
| `ModuleNotFoundError: playwright` | Requirements not installed | Run `pip install -r requirements.txt` again |
| GUI does not start, port 8765 is busy | An old server is still running | Stop the old process, or start with `--port 8766` |

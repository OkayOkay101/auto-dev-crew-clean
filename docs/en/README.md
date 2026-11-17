# Auto Dev Crew Documentation (English)

Index of the English documentation. Start with the page that matches what you want to do.

| File | Read it when |
|---|---|
| [ABOUT.md](ABOUT.md) | You want the overview, how AI was used, and the GUI status |
| [installation.md](installation.md) | Installing for the first time and running once |
| [configuration.md](configuration.md) | You need the meaning of every key in `config.yaml` |
| [cli.md](cli.md) | Running from a terminal with `python -m auto_dev_crew` |
| [gui.md](gui.md) | Using the local control panel, page by page |
| [architecture.md](architecture.md) | You want to know how a job flows from issue to merge |
| [github-workflow.md](github-workflow.md) | Labels and the life cycle of issues and PRs |
| [providers-and-keys.md](providers-and-keys.md) | Adding AI providers, setting keys, assigning roles |
| [api.md](api.md) | GUI endpoints for developers or scripts |
| [tools-and-scripts.md](tools-and-scripts.md) | Scripts in `scripts/`, MCP server, autonomous mode, CI and tests |
| [troubleshooting.md](troubleshooting.md) | Common problems and the list of known limitations |

## Notes
- The Thai documentation in [`../`](../) is the original. This English set is a translation of the same content and is kept in step with it. If the two ever disagree, the code is the source of truth.
- [REQUIREMENTS.md](../../REQUIREMENTS.md) is an early draft (v0.2, 2026-10-30). The system now uses the Antigravity CLI (`agy`) as the main engine, not GitHub Actions as described there. Read it as design history, not as the current specification.
- `docs/superpowers/` contains the specs and plans for individual pieces of work and records past decisions.

All statements here were checked against the code in this repository as of 2026-11-18. When the code changes, update the code-linked pages.

# Auto Dev Crew Documentation (English)

Index of the English documentation. Start with the page that matches what you want to do. Each English page has a Thai pair with the same name ending in `_TH.md`.

| File | Read it when |
|---|---|
| [ABOUT_EN.md](ABOUT_EN.md) | You want the overview, how AI was used, and the GUI status |
| [installation_EN.md](installation_EN.md) | Installing for the first time and running once |
| [configuration_EN.md](configuration_EN.md) | You need the meaning of every key in `config.yaml` |
| [cli_EN.md](cli_EN.md) | Running from a terminal with `python -m auto_dev_crew` |
| [gui_EN.md](gui_EN.md) | Using the local control panel, page by page |
| [architecture_EN.md](architecture_EN.md) | You want to know how a job flows from issue to merge |
| [github-workflow_EN.md](github-workflow_EN.md) | Labels and the life cycle of issues and PRs |
| [providers-and-keys_EN.md](providers-and-keys_EN.md) | Adding AI providers, setting keys, assigning roles |
| [api_EN.md](api_EN.md) | GUI endpoints for developers or scripts |
| [tools-and-scripts_EN.md](tools-and-scripts_EN.md) | Scripts in `scripts/`, MCP server, autonomous mode, CI and tests |
| [troubleshooting_EN.md](troubleshooting_EN.md) | Common problems and the list of known limitations |
| [glossary_EN.md](glossary_EN.md) | You meet a project term and want its short meaning |

## Notes
- Write the English page first, then the Thai pair with the same headings and links. If the two ever disagree, the code is the source of truth.
- The root [README.md](../README.md) is the front page. [CONTRIBUTING.md](../CONTRIBUTING.md) is for people who change the code.
- [REQUIREMENTS.md](../REQUIREMENTS.md) is an early draft (v0.2, 2026-10-30). The system now uses the Antigravity CLI (`agy`) as the main engine, not GitHub Actions as described there. Read it as design history, not as the current specification.
- `docs/superpowers/` contains the specs and plans for individual pieces of work and records past decisions.

## Source of the facts

Pages were checked against the code in this repository on 2026-11-18. A full sentence-by-sentence review by a native English speaker has not been done yet. When the code changes, update the code-linked pages.

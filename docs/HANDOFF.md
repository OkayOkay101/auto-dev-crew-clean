# Handoff: Auto Dev Crew (clean copy)

Updated: 2026-11-18 (after closing all open items). Read this first when starting a new chat. Then read `STATE.md`.

## 1. Where things stand

- Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean`
- Branch: see the commit and push result recorded in section 2 (`chore/remove-dead-features` was committed and merged into `master`).
- Remote: `https://github.com/OkayOkay101/auto-dev-crew-clean` is **PRIVATE**. Verified with `gh repo view`.
- Repo About description (set in English): "Local AI coding agent that turns GitHub issues into pull requests, with personas that scan for improvements. Experimental, private."
- Last test run (2026-11-18, after all changes below): `python -m pytest -q -p no:cacheprovider` → see section 2.

## 2. Work closed on 2026-11-18

| Item | Result |
|---|---|
| config.yaml untracked | Done (`6d9e186`). Only `config.example.yaml` is tracked. |
| `deploy/oracle/` | Deleted. Oracle Cloud dropped. |
| `REQUIREMENTS.md` | Kept as history. It has a banner saying it is not the current spec. |
| `/api/github/*`, `github_login.py` | Deleted. Guarded by `tests/test_removed_leftovers.py`. |
| `/classic` route | Deleted. |
| `reserve_for_issues` | Not in the local config. Not read by running code. Test fixtures still pass it, harmlessly. |
| `merge_level` 1/2/3 | Traced in `runner.py` and documented in `docs/architecture.md` section 8.1. |
| GUI gate 3 and gate 4 wording | Fixed in `static/index_sidebar.html`, `static/index.html`, `locales/en.json`. Guarded by `tests/test_gate_wording_gui.py`. |
| STATE.md mention of Oracle | Already says the folder was deleted. |

Commit and push: see the final message of the session for the commit hash and the push/merge result. Nothing is recorded here before it is verified.

## 3. Working rules from the user (apply in the next chat)

- Reply in Thai. Write documentation in English first, Thai later (user said: English version first).
- Use the Library Router search once per chat.
- Do not spawn subagents unless the user asks.
- Commit or push only when the user asks.
- Before writing about a file, check it against the code.
- Memory: this project note is `shared-ai-memory/projects/auto-dev-crew-clean-49a311320893.md`. Decisions from the user go there, not into this file.

## 4. Facts verified against code (use these, not older docs)

- `check_convergence` **is** called in the repair loop (`runner.py` ~2234 via `autonomous_upgrades.should_escalate_repair`), gated by `evaluation.plateau_stop` (default true).
- The guard hook (`scripts/autonomous_guard_hook.py`) blocks **all** `git push`, not only force-push.
- The agent's branches are `ai/issue-<n>-<stamp>` and `ai/<persona>-<stamp>`. `self/*` only appears in the revert plan (`autonomous_upgrades.py`).
- The GUI token protects POST and a few GET paths (`_GET_TOKEN_PATHS`), not every request.
- `max_fix_attempts`: code default 2, config value 3 (config wins).
- `owner` check is on the issue author (`runner.py` ~318).
- `ai-pause` stops new work while any open issue has the label (`paused()`).
- `merge_lock_timeout_minutes` is used as `max(that, ci.timeout_minutes + 5)` minutes.
- Gate 3 applies to every issue run that names a production file (`quality_gates.repair_gate_violation`), not only repair rounds. Gate 4 applies only to the automatic issue path, not the per-finding button.

## 5. Open items

None from the 2026-11-18 list. Possible follow-ups, not started:
- Thai docs (`docs/`) may drift from the English set (`docs/en/`). Sync if the user wants it.
- English docs in `docs/en/` have not been reviewed by a native reviewer.
- Test fixtures still contain `reserve_for_issues` (no effect). Clean up only if the user wants.

## 6. Practical notes for the next session

- The `Edit` tool needs a `Read` of the file in the current chat first, even after `Write`.
- Anchors in docs use GitHub numbering, e.g. `#8-merge-decisions`, `#2-known-limitations`. Keep the numbers when linking.
- Git prints CRLF warnings on every commit. They are harmless.
- `gh` is logged in as `OkayOkay101` with the `repo` scope.
- `state/`, `.env`, `.env.lock`, `config.yaml.lock` are git-ignored. Never print values from `.env`.

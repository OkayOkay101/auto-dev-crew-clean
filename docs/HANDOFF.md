# Handoff: Auto Dev Crew (clean copy)

Updated: 2026-11-18. Read this first when starting a new chat. Then read `STATE.md`.

## 1. Where things stand

- Folder: `C:\Users\Smart\Documents\auto-dev-crew-clean`
- Remote: `https://github.com/OkayOkay101/auto-dev-crew-clean` is **PRIVATE** (checked with `gh repo view`).
- Branches:
  - `chore/remove-dead-features` holds all of this session's work. Tip: `fed6d2b`, pushed to origin.
  - `master` is merged with that branch and pushed to origin. Run `git log --oneline -1 master` for the current tip.
- Working tree: clean after the handoff commit.
- Repo About description (set in English): "Local AI coding agent that turns GitHub issues into pull requests, with personas that scan for improvements. Experimental, private."
- Last test run: `python -m pytest -q -p no:cacheprovider` → 1401 passed, 6 skipped (2026-11-18, after all changes below).

## 2. Work closed on 2026-11-18

| Item | Commit | Result |
|---|---|---|
| config.yaml untracked | `6d9e186` | Only `config.example.yaml` is tracked. |
| `deploy/oracle/` | `6d9e186` | Deleted. Oracle Cloud dropped. |
| `/api/github/*`, `github_login.py`, `/classic` | `6d9e186` | Deleted. Guarded by `tests/test_removed_leftovers.py`. |
| `REQUIREMENTS.md` | (banner, 2026-11-18) | Kept as history. Banner says it is not the current spec. |
| `reserve_for_issues` | `e054139` | Removed from test fixtures. Config guard test stays. |
| `merge_level` 1/2/3 | (traced) | Matches `runner.py`; documented in `docs/architecture.md` section 8.1. |
| GUI gate 3 and gate 4 wording | `eedfc7d` | Fixed in `static/index_sidebar.html`, `static/index.html`, `locales/en.json`. Guarded by `tests/test_gate_wording_gui.py`. |
| Docs sync (Thai vs English) | `e054139` | Guard-hook list, config.yaml tracking statements, and English README note fixed. Checked by structure and inline code tokens only, not sentence by sentence. |
| Main README in English | `fed6d2b` | `README.md` is English. Thai text moved to `README.th.md`. Both link to each other. Later, `README.md` was made English only and the Thai file became `README_TH.md` (`6b22e13`); `README.th.md` was removed (`f32b0e2`). |

## 3. Working rules from the user (apply in the next chat)

- Reply in Thai.
- Documentation: write in English first, Thai afterward. The main `README.md` is English; `README_TH.md` is the Thai version.
- Use the Library Router search once per chat.
- Do not spawn subagents unless the user asks.
- Commit or push only when the user asks. Push was requested on 2026-11-18.
- Before writing about a file, check it against the code.
- Memory: this project note is `shared-ai-memory/projects/auto-dev-crew-clean-49a311320893.md`. Decisions from the user go there, not into this file.

## 4. Facts verified against code (use these, not older docs)

- `check_convergence` **is** called in the repair loop (`runner.py` ~2234 via `autonomous_upgrades.should_escalate_repair`), gated by `evaluation.plateau_stop` (default true).
- The guard hook (`scripts/autonomous_guard_hook.py`) blocks `git push`, `gh pr merge`, `gh release`, `deploy`, `git reset --hard`, `git clean -f`, recursive deletes (`rm -r…`, `Remove-Item -Recurse`, `del /s`), and deletion of the autonomous flag file. It does **not** single out force-push.
- The agent's branches are `ai/issue-<n>-<stamp>` and `ai/<persona>-<stamp>`. `self/*` only appears in the revert plan (`autonomous_upgrades.py`).
- The GUI token protects POST and a few GET paths (`_GET_TOKEN_PATHS`), not every request.
- The GUI page served is `static/index_sidebar.html`. `static/index.html` is not served but tests still read it.
- `max_fix_attempts`: code default 2, config value 3 (config wins).
- `owner` check is on the issue author (`runner.py` ~318).
- `ai-pause` stops new work while any open issue has the label (`paused()`).
- `merge_lock_timeout_minutes` is used as `max(that, ci.timeout_minutes + 5)` minutes.
- Gate 3 applies to every issue run that names a production file (`quality_gates.repair_gate_violation`), not only repair rounds. Gate 4 applies only to the automatic issue path, not the per-finding button.

## 5. Open items

- **Native-speaker review of `docs/en/` and `README.md`**: not done. It needs a person who reads English well. Nobody on the assistant side can do this.
- **Thai/English docs sync**: only the flagged differences were fixed. A sentence-by-sentence comparison of all ~3000 lines has not been done.
- **Test count**: 1401 now, versus 1442 recorded earlier. The likely cause is the GitHub login tests removed in `6d9e186`. Not confirmed by a line-by-line count.
- **Old doc text in `static/index.html`**: updated, but the file is not served.

## 6. Practical notes for the next session

- The `Edit` tool needs a `Read` of the file in the current chat first, even after `Write`.
- Anchors in docs use GitHub numbering, e.g. `#8-merge-decisions`, `#2-known-limitations`. Keep the numbers when linking.
- Git prints CRLF warnings on every commit. They are harmless.
- `gh` is logged in as `OkayOkay101` with the `repo` scope.
- `state/`, `.env`, `.env.lock`, `config.yaml.lock` are git-ignored. Never print values from `.env`.

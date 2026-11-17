# Troubleshooting and Known Limitations

This page lists common problems, how to check them, and the limitations that are not fixed yet.

---

## 1. Common problems

### 1.1 No job gets picked up

| Check | How |
|---|---|
| The issue is open and labeled `ai-task` | Look on GitHub. |
| The issue author matches `owner` in `config.yaml` | If not, the system skips it silently. |
| The issue has no `ai-working`, `ai-failed`, or `ai-needs-human` label | If it does, remove the label yourself to retry. |
| No open issue carries `ai-pause` | If one does, the runner starts no new work. |
| The repository is in `repos` with `enabled: true` | Check `config.yaml`. |
| Slots are free | Check the **Overview** page in the GUI. |
| Persona schedule | Personas run only in the window set by `personas.schedule`. |
| Engine quota is used up | Check the **Keys** page and the log. |

### 1.2 Jobs keep failing

1. Read the live log (the **Jobs** page) or the latest files in `state/runs/`.
2. If the status is `EVAL_FAILED`, read the comment on the issue (it contains the judge's critique).
3. If tests fail, run the repository's tests yourself in the working copy to see the real result.
4. If no engine works at all, press **ping** on the **Keys** page.

### 1.3 No engine is available to judge

The system uses the coder's engine as the judge and records `judge_same_as_coder`. To use a different judge, add a key with the `judge` role and enable an engine that has it.

### 1.4 A PR was opened but not merged

| Likely cause | Check |
|---|---|
| Mode is `review-all` | This is the intended behaviour. |
| Mode is `small-only` but the PR is larger than `max_lines` or touches `protected_paths` | Count the changed lines and files. |
| CI has not passed or has failed | Check the PR's checks. |
| The repository has no CI and `allow_no_ci: false` | Change the setting or add CI. |
| Another slot holds the merge lock for too long | Look for `Central Merge Lock` in the log. |

### 1.5 The GUI will not start, or the port is busy

- Stop the old process using port 8765, or start with `--port`.
- If the GUI freezes, restart it (see [gui.md](gui.md)).

### 1.6 Changes to `config.yaml` have no effect

- Restart the agent. Some values are read only at startup.
- If you changed a key role, reload the page before restarting.
- Check that the YAML is still valid, especially indentation.

### 1.7 Thai and English text mixed together

- The page follows `ui_language`.
- Logs, prompts, PR bodies, and printed output are in Thai by design (see the Decisions section of `STATE.md`).

### 1.8 `opencode.db` is damaged

```bash
python scripts/opencode_db_doctor.py          # check only
python scripts/opencode_db_doctor.py --apply  # back up, then repair (close OpenCode first)
```

### 1.9 The data folder was renamed

If an old `~/.ai-optimizer` folder exists, the system moves it once to `~/.auto-dev-crew` at startup (`data_home.py`). If the move fails, the old folder keeps being used and nothing is lost. A leftover `venvs.moved` folder can be deleted by hand once you no longer need it.

---

## 2. Known limitations

Checked against the code as of 2026-11-18.

| # | Topic | Details | Status |
|---|---|---|---|
| 1 | `config.yaml` is tracked in git | The file holds owner-specific values, and the README says it should not be committed. | Decision pending |
| 2 | `deploy/oracle/` | The project dropped Oracle Cloud. | Removed 2026-11-18 |
| 3 | `REQUIREMENTS.md` is an old draft | Written for the v0.2 design; it does not match the current system. | Kept as history only |
| 4 | `/api/github/*` and `github_login.py` | The UI does not use them. | Removed (B6) |
| 5 | The `/classic` page | Still present next to the new page. | Removed (B7) |
| 6 | Translation is incomplete | Logs, PR bodies, and printed output are Thai only. | By design |
| 7 | `reserve_for_issues` has no effect | The key is in the config, but the running code does not read it (only tests do). | Removed 2026-11-18 |
| 8 | Default for `max_fix_attempts` differs from the config | Code uses 2 when unset; the config sets 3. | The config value applies |
| 9 | The guard hook does not single out force-push | In autonomous mode it blocks all `git push`. | Intentional or not, not yet decided |
| 10 | Some README wording about branch `self/*` | Agents create branches named `ai/...`. `self/*` is used only in revert plans. | Documentation fixed in the Thai README; English docs follow the code |
| 11 | `merge_level` values 1, 2, 3 | Not yet traced to confirm which mode each number maps to. | Needs checking |
| 12 | The GUI is not tested in every browser or screen size | Tested in a local browser only. | Testing limit |
| 13 | Gates 1–4 | The wording in the GUI and README has not been traced for every gate line by line. | Needs checking |
| 14 | `trains_on_data` | Informational only; the system does not enforce it. | By design |
| 15 | Quota shown is the system's own count | It may differ from the provider's real balance. | Limit of the counting method |

Note: an older statement said `check_convergence` was never called. That is no longer true. The function runs in the repair loop when `plateau_stop` is enabled (the default).

---

## 3. When you hit a problem not listed here

1. Record the symptom, the time, and the relevant log lines.
2. Search the code for the error text (`grep`) to find where it comes from.
3. If it is a bug, write a failing test first, then fix it, then run the full test suite.
4. If it is a limitation you cannot fix yet, add it to the table in section 2.

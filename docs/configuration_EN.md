# `config.yaml` Reference

`config.yaml` in the project root is the main settings file. It is read by `runner.py`, `gui.py`, and other modules.

**How values are read:** if a key is missing from the file, the code uses the default listed in the "Code default" column. Some keys have a different value in the file than in the code. The file value always wins.

**Editing:** you can edit the file by hand, or use the GUI, which writes the values for you. After a manual edit, restart the agent so the change takes effect for sure (see [gui.md](gui_EN.md)).

---

## 1. Top-level keys

| Key | Type | Value in file | Code default | Meaning |
|---|---|---|---|---|
| `owner` | string | `example-owner` | (none) | GitHub account of the owner. Issues are picked up only if their author matches this value (case-insensitive). If unset, the agent picks up nothing. |
| `merge_mode` | string | `review-all` | `review-all` | Global merge policy: `review-all`, `small-only`, or `merge-all`. See [architecture.md](architecture_EN.md#8-merge-decisions). |
| `max_fix_attempts` | integer | `3` | `2` | Maximum repair rounds when tests fail or the coder changes nothing. The file value (3) applies. |
| `engine_timeout_cooldown_minutes` | number | `20` | `20` | After an engine times out, it is paused for this many minutes. |
| `ui_language` | string | (not in file) | `en` | UI and backend message language: `en` or `th`. Any other or unreadable value falls back to `en`. Set from the **Settings** page or `POST /api/settings/language`. |

---

## 2. `parallel`: running slots

| Key | Value in file | Code default | Meaning |
|---|---|---|---|
| `enabled` | `true` | (n/a) | Enables parallel slots. |
| `slots` | `3` | (n/a) | Number of slots that run at the same time. |
| `poll_interval_seconds` | `120` | `120` | How often the queue is checked for new work (seconds). |
| `merge_lock_timeout_minutes` | `25` | `25` | Maximum time to wait for the central merge lock. The system uses the larger of this value and `ci.timeout_minutes + 5`. A slot that cannot get the lock within that time does not merge in that round. |
| `assignments` | `slot_2`, `slot_3` with empty persona and repo | (n/a) | Assigns a persona or repository to a slot. The GUI writes this when you assign on the **Overview** page. |
| `active_slot` | `2` | (n/a) | The slot selected in the control panel. |

Slot 1 is reserved for issues you request. Slots 2 and 3 are for personas, or for extra issues.

---

## 3. `evaluation`: quality gate (judge)

| Key | Value in file | Code default | Meaning |
|---|---|---|---|
| `enabled` | `true` | (n/a) | Enables evaluation before a PR is opened. |
| `engine` | `auto` | (n/a) | Engine used as judge. `auto` picks from keys with the judge role. |
| `timeout_minutes` | `5` | `3` | Maximum time for one evaluation. The file value (5) applies. If the engine has a shorter own timeout, the shorter one is used. |
| `rubric.alignment_weight` | `0.4` | `0.4` | Weight for matching the task. |
| `rubric.safety_cleanliness_weight` | `0.3` | `0.3` | Weight for safety and cleanliness. |
| `rubric.quality_weight` | `0.3` | `0.3` | Weight for code quality. |
| `min_pass_score` | `0.75` | `0.75` | Minimum total score (0–1) to pass. |
| `max_eval_refinements` | `2` | `2` | Number of times the coder may revise according to the judge's critique before giving up. |
| `convergence_check` | `true` | (n/a) | Present in the file, but the code that checks convergence does not read this key directly. The key that matters is `plateau_stop`. |
| `plateau_stop` | (not in file) | `true` | When the judge's score stops improving during repair rounds, stop the rounds and do not spend quota again. Implemented by `check_convergence` in `evaluator.py`. |

The three rubric weights add up to 1.0.

---

## 4. `triage`: classifying issues

| Key | Value in file | Meaning |
|---|---|---|
| `enabled` | `true` | Enables issue classification. |
| `use_llm_fallback` | `false` | When labels cannot decide the path, whether an LLM should decide. `false` means labels and heuristics only. |
| `fast_labels` | `quick-fix, typo, docs, documentation, minor, small, lint` | Labels that mark a small, quick task (the `fast` path). |
| `heavy_labels` | `feature, architecture, refactor, breaking, complex, security` | Labels that mark a large task (the `heavy` path). The `sentinel` persona is always heavy. |

The result is a `fast` or `heavy` path. `routing` uses that path to keep separate merge histories per engine. Tasks that match no label fall back to heuristics.

---

## 5. `ci`: checks before merging

| Key | Value in file | Code default | Meaning |
|---|---|---|---|
| `enabled` | `true` | (n/a) | Enables waiting for CI results. |
| `required_checks` | `[]` | (n/a) | Checks that must pass. If empty, all checks CI runs must pass. |
| `timeout_minutes` | `15` | (n/a) | Maximum time to wait for CI. |
| `poll_interval_seconds` | `15` | `15` | How often CI is polled (seconds). |
| `auto_rebase` | `true` | `true` | If a PR is behind the base branch, rebase it before merging. |
| `allow_no_ci` | `true` | `true` | `true`: a repository with no CI may merge after local tests pass. `false`: CI must exist and pass. |
| `auto_bootstrap_ci` | `false` | (n/a) | If a repository has no CI, create a workflow file automatically. Off by default so the repository is not changed unexpectedly. |

---

## 6. `engines`: engines for coding and evaluation

`engines` is a list. Its order is the failover order: the first entry is tried first, unless `routing.enabled` reorders it based on results.

| Field | Meaning |
|---|---|
| `name` | Name used inside the system. Must be unique. |
| `provider` | Provider name shown in the GUI. |
| `command` | Program to run, for example `agy` or `opencode`. |
| `path` | Location of the program. `~` is supported. |
| `model` | Model name. With OpenCode, use the form `provider/model`. |
| `auth_provider` | Name used to find the OpenCode credential: the system looks for a key named `opencode-<auth_provider>` first. |
| `provider_id` | Provider ID in the registry (optional). |
| `timeout_minutes` | Maximum time per call. |
| `trains_on_data` | Informational flag recording whether the provider may train on data. The system does not enforce anything with it. |
| `enabled` | `true` = usable. `false` = skipped. |
| `roles` | Roles this engine serves: `coder`, `judge`, `scan`. |
| `api_keys` | Names of key variables in `.env`, such as `${POLLINATIONS_API_KEY_1}`. The values are not in this file. |

Currently only `opencode-pollinations` is enabled. The others are set to `enabled: false`.

Details on keys and roles: [providers-and-keys.md](providers-and-keys_EN.md).

---

## 7. `labels`: GitHub label names

| Key | Value | Meaning |
|---|---|---|
| `task` | `ai-task` | Label for work the agent should pick up. |
| `pause` | `ai-pause` | If any open issue has this label, the runner does not start new work in that repository. |
| `working` | `ai-working` | Added while the agent works on that issue. |
| `failed` | `ai-failed` | Added when the job fails or does not pass evaluation. |
| `pr` | `ai-generated` | Added to PRs the agent opens. |

The life cycle of these labels is described in [github-workflow.md](github-workflow_EN.md).

---

## 8. `small_pr`: small-PR rule for `small-only`

| Key | Value | Meaning |
|---|---|---|
| `max_lines` | `50` | Maximum changed lines for a PR to count as small. |
| `protected_paths` | `.github/`, `requirements`, `.jules/quality`, `config` | PRs that touch these paths are not small and need a human. Matching respects path boundaries: `config` matches `config.yaml` and `config/x`, but not `myconfig.py`. |

---

## 9. `personas`: improvement personas

| Key | Value | Meaning |
|---|---|---|
| `enabled` | `bolt`, `sentinel`, `palette`, `quality` | Personas that are active. |
| `skills` | per persona, for example `bolt: [memory-leak-debugging, caveman-persona]` | Skills added to that persona's prompt. |
| `schedule` | (not in file) | When personas may run. `mode`: `always` (default) or `nightly`. `start_hour` (default 0), `end_hour` (default 6). |

Personas run only when the issue queue is empty and their assigned slot is free.

---

## 10. `repos`: target repositories

Each entry in the list has these keys:

| Key | Meaning |
|---|---|
| `name` | `owner/name` of the repository. |
| `base` | Base branch for PRs (the code default is usually `main`). |
| `setup` | List of commands run before tests, for example installing dependencies. |
| `test` | List of commands that run the tests. |
| `scanners` | Map from persona name to the list of scan commands run for that persona in this repository. |
| `ci` | Per-repository override of `ci` settings, such as `auto_bootstrap_ci`. |
| `enabled` | `false` = skip this repository. |
| `merge_level` | (not in file) Per-repository merge level, set from a feature plan in the GUI: 1 = human reviews, 2 = auto-merge once CI passes and no risky files, 3 = auto-merge once CI passes. If unset, the global `merge_mode` applies (see [architecture](architecture_EN.md#8-merge-decisions)). |

Repository currently in the file: `OkayOkay101/cyberpunk-pomodoro` (base `main`, test `node test-runner.js`).

---

## 11. `autonomous`, `todo_scan`, and `auto_issue`

| Section | Key | Value | Meaning |
|---|---|---|---|
| `autonomous` | `max_turns_per_session` | `40` | Maximum turns for one autonomous-mode session in Claude Code (used by `scripts/autonomous_common.py`). |
| `todo_scan` | `max_issues_per_run` | `5` | Maximum issues created from `[AI-TODO]` tags in one run. |
| `todo_scan` | `schedule_minutes` | `0` | Repeat scan interval in minutes. `0` or unset = no scheduled scan. |
| `auto_issue` | `enabled` | `false` | Whether deep-scan findings create issues automatically. |
| `auto_issue` | `trigger` | `after_scan` | When issues are created. The value supported in the code is `after_scan`. |
| `auto_issue` | `min_severity` | `low` | Lowest severity that creates an issue. |

---

## 12. `context`, `loop`, and `routing` (not in the file; code defaults)

| Key | Default | Meaning |
|---|---|---|
| `context.repo_map` | `true` | Attach a map of Python code (function and class names with signatures) to the prompt. |
| `context.repo_map_chars` | `6000` | Maximum characters in the repo map. |
| `loop.require_test_for_bugfix` | `true` | A bug fix that the coder reports as done but that changed no test file gets one extra round to add a regression test. |
| `routing.enabled` | `true` | Order engines by merge results in the history (`state/history.json`). |
| `routing.min_samples` | `5` | Minimum finished outcomes per engine before results are used for ordering. |
| `routing.demote_below` | `0.2` | Engines whose merge rate falls below this (with enough data) move to the end. No engine is removed. |

If `AGENTS.md`, `CLAUDE.md`, or `.github/copilot-instructions.md` exists in a target repository, its contents are attached automatically as "Repository Notes" (up to 4000 characters).

---

## 13. Common examples

**Start cautiously (a human reviews every PR):**
```yaml
merge_mode: review-all
```

**Let the agent merge only small PRs:**
```yaml
merge_mode: small-only
small_pr:
  max_lines: 50
```

**Require CI in every repository before merging:**
```yaml
ci:
  allow_no_ci: false
```

**Turn off the repo map to save tokens:**
```yaml
context:
  repo_map: false
```

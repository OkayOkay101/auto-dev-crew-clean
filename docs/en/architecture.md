# Architecture and Job Flow

This page explains how one job moves through the code, from an issue or persona to a merge. References in parentheses point to the functions in the repository.

---

## 1. Module overview

| Group | Main files | Role |
|---|---|---|
| Core | `runner.py` (about 3,100 lines) | Queue, slots, clone, engine calls, tests, PRs, merging, reports |
| Evaluation | `evaluator.py`, `static_checks.py`, `static_gate.py`, `quality_gates.py` | Gates and judge scores |
| Routing | `routing.py`, `triage.py`, `providers.py`, `keys.py` | Choose engines by history and classify jobs |
| Discovery | `deep_scan.py`, `todo_scan.py`, `feature_gen.py`, `multi_repo.py` | Scan code and create issues |
| Safety | `redact.py`, `guardrails.py`, `gui_patches.py` | Hide secrets, truncate long output, check tokens |
| Web | `gui.py`, `static/`, `i18n*.py`, `locales/` | GUI and translation |
| Support | `context.py`, `context_slicer.py`, `ast_skeleton.py`, `locks.py`, `file_locks.py`, `metrics.py`, `doctor.py` | Repo map, file locks, metrics, health checks |

---

## 2. Life cycle of one job

```
┌───────────────────────────────────────────────────────────────┐
│ 1. Intake: issue (ai-task) or persona                         │
│ 2. Slot: slot 1 = owner issues; slots 2–3 = the rest          │
│ 3. Prepare: clone/worktree, setup, check locked files         │
│ 4. Code: coder engine edits code → tests → repair ≤ max_fix   │
│ 5. Evaluate: gates + judge → refine ≤ max_eval_refinements    │
│ 6. Not passed → ai-failed + comment on the issue, no PR       │
│ 7. Passed → push branch, open PR (label ai-generated)         │
│ 8. Merge per mode → merge lock → rebase → wait CI → merge     │
│ 9. Record: history.json, usage.jsonl, raw log in state/runs   │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Choosing work

### 3.1 Issues (`runner.py`, around lines 310–325)
Open issues labeled `ai-task` are filtered as follows:
- The issue author must match `owner` in the settings (case-insensitive).
- Issues labeled `ai-working`, `ai-failed`, or `ai-needs-human` are skipped.
- Issues are sorted by number, lowest first.

### 3.2 Slots and personas (`slot_worker_loop`, around line 2981)
- Slot 1 takes only owner issues.
- Slots 2 and 3 take personas, or help with extra issues when at least two issues exist.
- Personas run only inside the time window set by `personas.schedule`, and only when the persona has no open PR waiting for review.
- If any open issue in the repository carries the `ai-pause` label, the runner starts no new work (`paused()`).

### 3.3 Personas
Each persona has its own goal in the code (`runner.py`, around lines 91–103). For example, bolt looks for a measurable performance gain, and sentinel looks for real security weaknesses.

---

## 4. Preparation

- Branch names: `ai/issue-<number>-<timestamp>` for issues, and `ai/<persona>-<timestamp>` for personas (`runner.py`, lines 447 and 2342).
- Working directories sit under `~/.auto-dev-crew/work`, with a repository cache in `~/.auto-dev-crew/repos`.
- Each repository has its own venv under `~/.auto-dev-crew/venvs`.
- The `setup` commands from the config run before tests.
- Files locked by another job are tracked through `file_locks.py`, so two slots do not edit the same file at once.

---

## 5. Coding (`execute`, around line 2331)

1. The coder engine receives a prompt from `prompts/task.md` (issue work) or `prompts/fix_tests.md` (test repair), plus the shared rules in `prompts/_rules.md`, the repo map (if enabled), and Repository Notes.
2. The engine is called in the order `routing` produces. If it fails or its quota is used up, the next engine is tried (F6).
3. The repository's test commands run (`repos[].test`).
4. If tests fail or the coder changed nothing, repair runs again, up to `max_fix_attempts` rounds (3 in the file; 2 is the code default).
5. A bug fix that the coder reports as done without changing any test file gets an extra round to add a regression test (`loop.require_test_for_bugfix`, `loop_helpers.py`).

---

## 6. Quality gates

Checks are run by `_evaluate_guarded` (around line 2487) and `evaluator.py`.

| Step | What is checked | Result on failure |
|---|---|---|
| 0 | The diff is empty | Stop immediately |
| 1 | Deterministic check: Python files must parse (`guardrails.check_deterministic_pre_eval`) | Stop; the judge is not called |
| 2 | Static checks (`static_checks.py`) | Stop if there are serious findings |
| 3 | The judge scores against the rubric: alignment 0.4, safety and cleanliness 0.3, quality 0.3 | Below `min_pass_score` (0.75): the coder revises using the critique |
| 4 | Refinement up to `max_eval_refinements` rounds, stopping early when the score plateaus (`plateau_stop`) | Still failing → `EVAL_FAILED` |

If no other engine is available to judge, the coder's engine judges, and the log records it (stored as `judge_same_as_coder`).

### Gates 1–4 as described in the GUI
The GUI and README describe the gates this way:
- **Gate 1:** the judge confirms a bug is real before it is fixed.
- **Gate 2:** the judge sees the whole file after the fix.
- **Gate 3:** a repair round must touch the file the issue names.
- **Gate 4:** deep-scan re-checks a finding before an issue is created.

Note: this wording comes from the GUI and README. The code has not yet been traced for every gate line by line. To verify, search the code for `gate` or `ด่าน`.

---

## 7. Opening the PR

- If every gate passes, the system pushes the branch and opens the PR with `create_pr` (`runner.py`, line 1491).
- The PR receives the label `ai-generated`.
- The PR body is built by `pr_body.py` (the full list of what it includes has not been traced line by line).
- A job that does not pass is labeled `ai-failed`, the reason is posted as a comment on the issue, and no PR is opened.

---

## 8. Merge decisions

Handled by `try_merge` (around line 1752) and `_local_rebase_and_merge` (line 1710).

### 8.1 Merge level
1. If the repository has its own `merge_level`, that level is used.
2. Otherwise the global `merge_mode` is used.

| Mode | Behaviour |
|---|---|
| `review-all` | No automatic merge. A human merges. |
| `small-only` | Merge automatically when the PR has at most `small_pr.max_lines` changed lines and touches no `protected_paths` (checked by `_matches_protected`, line 1431). |
| `merge-all` | Merge automatically once CI passes. |

### 8.2 Merge sequence
1. Acquire the central merge lock (`MERGE_LOCK`). The wait time is computed from `merge_lock_timeout_minutes` and `ci.timeout_minutes`.
2. Rebase onto the base branch if `ci.auto_rebase` is true.
3. Wait for CI results (`ci_sync.wait_for_required_checks`) up to `ci.timeout_minutes`.
4. If there is no CI, the outcome depends on `ci.allow_no_ci`.
5. If CI fails, do not merge.
6. After merging, record the outcome in `history.json`.

---

## 9. Recording and learning

| File | Contents | Notes |
|---|---|---|
| `state/history.json` | Outcome of each job (status, engine, score, merged or not) | Used by `routing` and `metrics`. Not committed. |
| `state/usage.jsonl` | Requests and tokens per engine per day | Shown on the **Keys** page. |
| `state/runs/` | Raw logs for each round | Trimmed to the most recent entries (`prune_raw_logs`). |
| `state/session_checkpoint.json` | Session checkpoint | Used on restart. |
| `state/active_slots.json` | Current slot status | Read by the GUI. |

`routing` uses `history.json` to order engines. An engine whose merge rate is below `routing.demote_below`, with at least `min_samples` results, moves to the end. Nothing is removed.

---

## 10. Deep-scan

`deep_scan.py` has an AI read code section by section and report problems with a severity. Findings that pass gate 4 and reach `auto_issue.min_severity` can create issues when `auto_issue.enabled: true`.

Deep-scan results are stored in `state/deep_scan/<owner>__<repo>.json`, with a matching `.lock` file.

---

## 11. Handling problems along the way

| Situation | Behaviour |
|---|---|
| Engine timeout | Pause that engine for `engine_timeout_cooldown_minutes`, then move to the next one. |
| Quota used up | Move to the next engine in order (F6). |
| No judge available | Use a fallback engine or the coder's engine, and record it. |
| Score plateaus during repair | Stop repairing (`plateau_stop`) and do not spend quota again. |
| Two slots touch the same file | `file_locks.py` prevents it. |
| Restart in the middle of a job | A checkpoint is saved, and the restart uses the same settings. The unfinished job is cancelled. |

---

## 12. Things to know before changing code

- `runner.py` is large, with 144 top-level functions. Read the related tests before changing it.
- Many modules import `runner.py`. Renaming a public function means finding every reference first.
- Config values can be read more than once during a run, so changing settings in the middle of work can have uneven effects. Restart after changes.

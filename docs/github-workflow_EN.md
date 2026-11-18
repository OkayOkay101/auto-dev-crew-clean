# GitHub Workflow: Labels, Issues, and PRs

This page describes what you do on GitHub and how the system responds.

---

## 1. Labels

Labels are created automatically when a repository is set up (`runner.py`, around line 1446), if they do not already exist.

| Label | Config key | Who adds it | Meaning |
|---|---|---|---|
| `ai-task` | `labels.task` | You | An issue for the agent to pick up. |
| `ai-pause` | `labels.pause` | You | Pauses the agent for the repository while any open issue carries it. |
| `ai-working` | `labels.working` | System | Added while the agent works on that issue. |
| `ai-failed` | `labels.failed` | System | The job failed or did not pass evaluation. The system will not retry it automatically. |
| `ai-needs-human` | `labels.needs_human` (default `ai-needs-human`) | System | Needs a person to look. The system will not pick it up again. |
| `ai-generated` | `labels.pr` | System | Added to PRs the agent opens. |
| `ai-report` | (fixed) | System | Label for the daily report. |
| `ai-plan` | (fixed) | System | An issue proposing a feature plan, waiting for approval. |
| `ai-plan-approved` | (fixed) | You | You approve a plan; the system creates `ai-task` issues from it. |

The names of the first five labels can be changed in `labels` in `config.yaml`. `ai-plan`, `ai-plan-approved`, and `ai-report` are fixed in the code.

---

## 2. Life cycle of an issue you request

```
You open an issue
     │
     ▼
Add label ai-task  ──► (author not equal to owner → the system skips it)
     │
     ▼
The system picks it up → adds ai-working
     │
     ├── Passes all gates → opens PR (ai-generated)
     │         │
     │         └── Depending on merge mode → merges automatically, or waits for a reviewer
     │
     └── Fails → removes ai-working, adds ai-failed, comments the reason on the issue
```

**What you should do**
- Write the issue clearly and make it testable: say what should happen, and name the test command or expected behavior.
- Add `ai-task` yourself. If someone else adds it, the system does not pick the issue up.
- To retry after a failure, remove `ai-failed` yourself, and remove `ai-needs-human` as well if it is present.

---

## 3. Pausing and resuming

### Emergency stop
- Open any issue and add `ai-pause`. The runner will not start new work in its next round.
- Work already in progress may finish that round first.
- You can also press stop in the GUI to cancel the job in progress.

### Resuming
- Close the issues that carry `ai-pause`. The system resumes in its next round (the condition is that no open issue has the label).

---

## 4. Feature plans (`ai-plan`)

Flow:
1. On the **Studio** page of the GUI, ask the AI to propose a feature plan. The system creates an issue labeled `ai-plan`.
2. Read the plan, then add `ai-plan-approved`.
3. The system creates an `ai-task` issue for each step of the plan.
4. From there, the normal issue flow applies.

Proposing and approving go through `/api/feature-gen/propose` and `/api/feature-gen/approve` (see [api.md](api_EN.md)).

The merge level for a plan can be set when it is created (per-repository `merge_level`).

---

## 5. PRs the system opens

- Branch names: `ai/issue-<number>-<timestamp>` for issues, or `ai/<persona>-<timestamp>` for personas.
- Label: `ai-generated`.
- Titles carry an icon that depends on the job type (`ICONS` in the code).
- The body is built by `pr_body.py` (the full list of what it includes has not been traced line by line).

Reviewers should check:
- Whether the diff matches the issue.
- Test results and CI.
- The judge's score and critique. A low score deserves extra care.

---

## 6. Permissions and tokens

- The GitHub account used by `gh` needs write access to the target repository, to push branches, open PRs, create labels, and comment.
- The system does not force-push, according to the rules in this documentation. (The enforced limits are described in [troubleshooting.md](troubleshooting_EN.md#2-known-limitations).)
- Never paste a token into an issue or comment. The system hides known token formats (`redact.py`) before showing or logging text, but cannot guarantee that every format is caught.

---

## 7. Daily report

The system writes a report into an issue labeled `ai-report` (`report()` in `runner.py`). If `gh` fails while writing the report, the slot keeps running (`_report_safely`).

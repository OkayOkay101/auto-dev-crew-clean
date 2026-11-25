# Glossary

Short definitions of the project's terms. Each entry links to the page with the details.

| Term | Meaning | Details |
|---|---|---|
| **Owner** | The GitHub account set as `owner` in `config.yaml`. Only issues opened by this account count as work for the agent. | [github-workflow.md](github-workflow_EN.md) |
| **`ai-task`** | Label an owner adds to an issue to give it to the agent. | [github-workflow.md](github-workflow_EN.md) |
| **`ai-pause`** | Label that stops the agent for a repository while any open issue carries it. Closing the issue lets it resume. | [github-workflow.md](github-workflow_EN.md) |
| **Slot** | One of the parallel workers (`parallel.slots`, default `3`). Slot 1 takes only owner issues. Slots 2 and 3 take personas, or extra issues. | [architecture.md](architecture_EN.md) |
| **Persona** | An autonomous agent that scans the code for one kind of improvement when no issues are waiting. The enabled personas are `bolt` (performance), `sentinel` (security), `palette` (UX/UI), and `quality` (tests and code quality). | [architecture.md](architecture_EN.md) |
| **Engine** | An AI service that does the coding or judging. The main engine is the Antigravity CLI (`agy`). | [providers-and-keys.md](providers-and-keys_EN.md) |
| **F6 failover** | When an engine's quota runs out or it times out, the system tries the next engine in the failover order. A timed-out engine is paused for `engine_timeout_cooldown_minutes`. | [providers-and-keys.md](providers-and-keys_EN.md) |
| **Routing** | Orders engines by past merge results when `routing.enabled` is `true`. Engines need `routing.min_samples` results before their data is used. | [configuration.md](configuration_EN.md) |
| **Merge mode** | The global rule for merging PRs: `review-all` (a person merges), `small-only` (small PRs merge by themselves), or `merge-all` (merge once CI passes). | [architecture.md](architecture_EN.md) |
| **Merge level** | A per-repository override of the merge mode, with values `1`, `2`, or `3`. Level 1 always waits for a person. Level 2 merges automatically unless the file risk check finds risky files. Level 3 merges automatically once CI passes. | [architecture.md](architecture_EN.md) |
| **Protected paths** | Paths that never count as a small PR, such as `.github/` and `requirements`. | [configuration.md](configuration_EN.md) |
| **Quality gates** | Checks a change must pass before a PR opens: the diff is not empty, Python files parse, static checks pass, and the judge scores the change at or above `min_pass_score` (0.75). | [architecture.md](architecture_EN.md) |
| **Judge (evaluator)** | The AI step that scores a change against a rubric. If no other engine is available, the coder's own engine judges it. | [architecture.md](architecture_EN.md) |
| **Feature plan (`ai-plan`)** | A proposed set of features filed as an issue. After a person adds `ai-plan-approved`, the system creates one `ai-task` issue per step. | [github-workflow.md](github-workflow_EN.md) |
| **Deep scan** | A scan of the whole repository that can file new issues. | [architecture.md](architecture_EN.md) |
| **Dry run** | A local run that does not touch GitHub. Use `--dry-run`. | [cli.md](cli_EN.md) |
| **`[AI-TODO]`** | A marker in code comments that `--scan-todos` lists. The scan does not create issues. | [cli.md](cli_EN.md) |
| **Small PR** | A PR with at most `small_pr.max_lines` changed lines (default `50`) that touches no protected path. | [configuration.md](configuration_EN.md) |

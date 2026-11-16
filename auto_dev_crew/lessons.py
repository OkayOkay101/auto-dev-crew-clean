"""Memory from past runs for the prompt: recent rejected attempts (lessons) and recent merged
changes (few-shot examples). History text comes from GitHub and earlier AI output, so every
field is flattened to one line or truncated before it reaches the prompt."""
from __future__ import annotations

_LESSON_STATES = ("CLOSED", "EVAL_FAILED", "FAILED")
_LESSON_REASON_CHARS = 200
_EXAMPLE_TITLE_CHARS = 200
_EXAMPLE_SUMMARY_CHARS = 400


def _one_line(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _repo_of(entry: dict) -> str | None:
    return entry.get("origin_repo") or entry.get("repo")


def format_lessons(history: list[dict], repo: str, limit: int = 6) -> str:
    """Last `limit` rejected or failed entries for `repo`, one `- [STATE] title — reason` line each."""
    if limit <= 0:
        return ""
    picked = [h for h in history
              if _repo_of(h) == repo and h.get("state") in _LESSON_STATES][-limit:]
    lines = []
    for entry in picked:
        reason = _one_line(entry.get("eval_critique") or entry.get("fail_reason"), _LESSON_REASON_CHARS)
        line = f"- [{entry['state']}] {_one_line(entry.get('title'), _EXAMPLE_TITLE_CHARS)}"
        lines.append(f"{line} — {reason}" if reason else line)
    return "\n".join(lines)


def format_examples(history: list[dict], repo: str, kind: str, key, limit: int = 2) -> str:
    """Last `limit` merged entries for `repo` and `kind`, each as a `### title` block with its summary.
    Persona entries must also match `key`; issue entries ignore it (their key is the issue number)."""
    if limit <= 0:
        return ""
    # Merged entries carry pr_body rather than summary in most cases; skip those with no text at all.
    candidates = []
    for entry in history:
        if _repo_of(entry) != repo or entry.get("state") != "MERGED" or entry.get("kind") != kind:
            continue
        if kind != "issue" and str(entry.get("key")) != str(key):
            continue
        text = str(entry.get("summary") or entry.get("pr_body") or "").strip()[:_EXAMPLE_SUMMARY_CHARS]
        if text:
            candidates.append((entry, text))
    blocks = []
    for entry, text in candidates[-limit:]:
        title = _one_line(entry.get("title"), _EXAMPLE_TITLE_CHARS)
        blocks.append(f"### {title}\n{text}")
    return "\n\n".join(blocks)

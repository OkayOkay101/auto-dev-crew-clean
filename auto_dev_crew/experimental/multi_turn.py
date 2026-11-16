from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConversationTurn:
    role: str  # "user" | "assistant"
    content: str
    cache_control: bool = False


def format_delta_turn(
    test_failure_output: str = "",
    rubric_feedback: str | None = None,
    ast_syntax_error: str | None = None,
) -> str:
    """Formats verification feedback and failures as a concise error delta turn."""
    parts = [
        "## Verification Feedback & Errors (Delta)",
        "Your previous code changes failed automated verification checks.",
        "⚠️ **INSTRUCTION:** Fix ONLY the specific errors identified below. DO NOT restart from scratch, do not touch unrelated files, and do not repeat previous failed patterns.",
    ]

    if ast_syntax_error:
        parts.append(f"### AST Syntax Error Gate Failure\n```\n{ast_syntax_error.strip()}\n```")

    if test_failure_output:
        # Keep head and tail of failure if long
        cleaned_err = test_failure_output.strip()
        if len(cleaned_err) > 3000:
            cleaned_err = cleaned_err[:1200] + "\n... [truncated] ...\n" + cleaned_err[-1500:]
        parts.append(f"### Test Execution Failures\n```\n{cleaned_err}\n```")

    if rubric_feedback:
        parts.append(f"### Evaluator Rubric Feedback\n{rubric_feedback.strip()}")

    return "\n\n".join(parts)


def build_multi_turn_history(
    initial_prompt: str,
    previous_diff: str,
    test_failure_output: str = "",
    rubric_feedback: str | None = None,
    ast_syntax_error: str | None = None,
) -> list[ConversationTurn]:
    """Builds an append-only 3-turn message sequence where only the new error/feedback is sent in the final turn."""
    turns: list[ConversationTurn] = []

    # Turn 1: Initial Prompt (Cached)
    turns.append(
        ConversationTurn(
            role="user",
            content=initial_prompt.strip(),
            cache_control=True,
        )
    )

    # Turn 2: Previous Diff / Assistant Attempt
    assistant_content = previous_diff.strip() if previous_diff else "I attempted the solution."
    turns.append(
        ConversationTurn(
            role="assistant",
            content=assistant_content,
            cache_control=False,
        )
    )

    # Turn 3: Error Delta
    delta_content = format_delta_turn(
        test_failure_output=test_failure_output,
        rubric_feedback=rubric_feedback,
        ast_syntax_error=ast_syntax_error,
    )
    turns.append(
        ConversationTurn(
            role="user",
            content=delta_content,
            cache_control=False,
        )
    )

    return turns

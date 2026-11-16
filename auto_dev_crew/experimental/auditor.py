from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass


@dataclass
class PatchTarget:
    file: str
    line_range: list[int]
    issue: str
    instruction: str


@dataclass
class PatchSpec:
    summary: str
    targets: list[PatchTarget]
    verification_command: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_patch_spec(raw: str | dict) -> PatchSpec | None:
    """Parses a PatchSpec from a dictionary or JSON markdown string."""
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        cleaned = raw.strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        try:
            data = json.loads(cleaned)
        except Exception:
            match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                except Exception:
                    return None
            else:
                return None
    else:
        return None

    try:
        summary = str(data.get("summary", ""))
        verification_command = str(data.get("verification_command", ""))
        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            return None

        targets: list[PatchTarget] = []
        for t in raw_targets:
            if not isinstance(t, dict):
                continue
            lr = t.get("line_range", [1, 1])
            if not isinstance(lr, list) or len(lr) < 2:
                lr = [1, 1]
            targets.append(
                PatchTarget(
                    file=str(t.get("file", "")),
                    line_range=[int(lr[0]), int(lr[1])],
                    issue=str(t.get("issue", "")),
                    instruction=str(t.get("instruction", "")),
                )
            )

        if not summary or not targets:
            return None

        return PatchSpec(
            summary=summary,
            targets=targets,
            verification_command=verification_command,
        )
    except Exception:
        return None


def build_auditor_prompt(repo: str, task_desc: str, repo_skeleton: str) -> str:
    """Generates the prompt for the Tier-1 Diagnostic Auditor model."""
    return f"""# Role: Tier-1 Senior Diagnostic Auditor

You are an expert diagnostic systems architect for `{repo}`.
Your objective is to inspect the problem, examine the repository structure, diagnose root causes, and output a **Strict JSON Patch Spec**.

## Operational Constraints:
- DO NOT rewrite full source files.
- DO NOT output free-form conversational chatter.
- Identify the exact target files, approximate line numbers, and surgical instruction for Tier-2 workers.
- Define a precise verification command (e.g. `pytest tests/test_target.py -q`).

## Target Task / Issue
{task_desc.strip()}

## Codebase Skeleton
```python
{repo_skeleton.strip()}
```

## Output Format
Respond ONLY with a valid JSON block:
```json
{{
  "summary": "Concise summary of the diagnosis and required fix",
  "targets": [
    {{
      "file": "path/to/file.py",
      "line_range": [start_line, end_line],
      "issue": "Root cause explanation",
      "instruction": "Exact code modification instruction"
    }}
  ],
  "verification_command": "pytest tests/test_example.py -q"
}}
```
"""


def build_worker_prompt(
    patch_spec: PatchSpec,
    target_files_content: dict[str, str],
    repo: str,
) -> str:
    """Generates the prompt for the Tier-2 Surgical Code Worker model."""
    targets_md: list[str] = []
    for t in patch_spec.targets:
        lines_str = f"Lines {t.line_range[0]}-{t.line_range[1]}"
        snippet = target_files_content.get(t.file, "(File content not provided)")
        targets_md.append(
            f"### Target: `{t.file}` ({lines_str})\n"
            f"- **Issue:** {t.issue}\n"
            f"- **Instruction:** {t.instruction}\n\n"
            f"**Current Content:**\n```python\n{snippet.strip()}\n```"
        )

    targets_section = "\n\n".join(targets_md)

    return f"""# Role: Tier-2 Surgical Code Worker

You are a fast surgical coding worker executing a verified diagnosis on `{repo}`.
Summary: {patch_spec.summary}

## Instructions:
1. Apply surgical edits ONLY to the specified target files and line ranges.
2. Do not refactor unrelated code.
3. Verify your changes with the verification command: `{patch_spec.verification_command}`.

## Execution Targets:
{targets_section}

Deliver the modified files or diff accurately.
"""

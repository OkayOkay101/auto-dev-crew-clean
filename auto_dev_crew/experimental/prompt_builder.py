from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..ast_skeleton import generate_repo_skeleton
from ..context import DEFAULT_TEST_COMMANDS
from ..guardrails import prune_resolved_evidence
from ..sentinel_tracker import load_sentinel_issues
from ..stack_detector import detect_stack, format_stack_guidelines

if TYPE_CHECKING:
    from ..runner import Job

ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = ROOT / "prompts"


@dataclass
class TieredPrompt:
    tier_a_static: str      # System prompt, roles, schemas, standards
    tier_b_semi_static: str # Repo structure, AST skeleton, stack guidelines
    tier_c_dynamic: str     # Issue/task details, errors, slot runtime constraints

    @property
    def full_text(self) -> str:
        parts = [p.strip() for p in (self.tier_a_static, self.tier_b_semi_static, self.tier_c_dynamic) if p.strip()]
        return "\n\n---\n\n".join(parts)


def normalize_to_repo_relative(text: str, repo_root: Path | str) -> str:
    """Replaces absolute directory paths with repo-relative paths to ensure KV-cache hits across slot worktrees."""
    if not text:
        return text

    candidates: list[str] = [str(repo_root)]
    if isinstance(repo_root, Path):
        try:
            candidates.append(str(repo_root.resolve()))
        except Exception:
            pass

    patterns = set()
    for root_str in candidates:
        root_norm = root_str.replace("\\", "/").rstrip("/")
        patterns.add(root_norm + "/")
        patterns.add(root_norm)
        # Windows drive backslash variants
        root_win = root_str.replace("/", "\\").rstrip("\\")
        patterns.add(root_win + "\\")
        patterns.add(root_win)

    result = text
    for p in sorted(patterns, key=len, reverse=True):
        if p:
            result = result.replace(p, "")

    return result.replace("\\", "/")


def build_tiered_prompt(
    job: Job,
    rcfg: dict,
    cwd: Path,
    env: dict,
    history: list[dict],
    result_path: Path,
    slot_id: int | None = None,
    repo_skeleton: str = "",
) -> TieredPrompt:
    """Constructs a deterministic 3-tier prompt ensuring prefix cache reusability."""
    # 1. Tier A: Pure Static Prefix
    # Read the base template to extract static role and workflow
    template_name = "task.md" if job.kind == "issue" else f"personas/{job.key}.md"
    raw_template = (PROMPTS / template_name).read_text(encoding="utf-8")
    rules_text = (PROMPTS / "_rules.md").read_text(encoding="utf-8")
    rules_text = rules_text.replace("{{test_commands}}", DEFAULT_TEST_COMMANDS)

    # Split template at '# Target Execution Context' or '---'
    split_match = re.search(r"\n---\s*\n\s*# Target Execution Context", raw_template)
    if split_match:
        static_part = raw_template[:split_match.start()].strip()
    else:
        static_part = raw_template.split("---")[0].strip()

    static_part = static_part.replace("{{rules}}", rules_text)
    tier_a_static = static_part.strip()

    # 2. Tier B: Semi-Static Repo Context (Cached at repo level)
    stack_profile = detect_stack(cwd)
    stack_guidelines = format_stack_guidelines(stack_profile, prompts_dir=PROMPTS)
    
    if not repo_skeleton:
        repo_skeleton = generate_repo_skeleton(cwd, max_chars=8000)

    tier_b_blocks = [
        "# Repository Context",
        f"- **Repository**: `{rcfg.get('name', 'repository')}`",
    ]
    if stack_guidelines:
        tier_b_blocks.append(f"## Detected Tech Stack Guidelines\n{stack_guidelines}")

    if job.kind != "issue":
        try:
            from .runner import GLOBAL_SKILL_REGISTRY
            configured_skills = rcfg.get("personas", {}).get("skills", {}).get(job.key)
            matched_skills = GLOBAL_SKILL_REGISTRY.get_skills_for_persona(
                str(job.key),
                tech_stack=stack_profile,
                limit=3,
                configured_skills=configured_skills
            )
            available_skills = GLOBAL_SKILL_REGISTRY.format_skills_for_prompt(matched_skills)
            if available_skills:
                tier_b_blocks.append(f"## Active Specialized Skills\n{available_skills}")
        except Exception:
            pass

    if repo_skeleton:
        tier_b_blocks.append(f"## Codebase AST Skeleton Overview\n```python\n{repo_skeleton}\n```")

    tier_b_semi_static = "\n\n".join(tier_b_blocks).strip()

    # 3. Tier C: Dynamic Suffix (Task, Issue, Scans, Delivery, Slot Constraints)
    tier_c_blocks = ["# Task & Execution Specifics"]

    if job.kind == "issue":
        tier_c_blocks.append(f"- **Assigned Issue**: #{job.key}\n- **Issue Title**: {job.title}\n\n### Issue Description\n{job.body[:8000]}")
    else:
        scans: list[str] = []
        for cmd in rcfg.get("scanners", {}).get(job.key, []):
            try:
                # shell=True ตั้งใจ: scanner มาจาก config.yaml ของเจ้าของ repo (ไม่รับค่าจาก issue/PR)
                res = subprocess.run(cmd, cwd=cwd, env=env, check=False, shell=True, timeout=900, capture_output=True, text=True)  # nosec B602
                scans.append(f"$ {cmd} (exit {res.returncode})\n{(res.stdout + res.stderr)[-3000:]}")
            except Exception as e:
                scans.append(f"$ {cmd} (failed to run: {e})")

        history_pruned = prune_resolved_evidence(history)
        past = [
            f"- [{h.get('state') or 'ไม่มี PR'}] {h['title']}"
            for h in history_pruned
            if h.get("repo") == rcfg.get("name") and h.get("key") == job.key
        ][-30:]

        if job.key == "sentinel":
            try:
                tracked = load_sentinel_issues()
                if tracked:
                    tracked_summary = [
                        f"- [TRACKED {item.get('status', 'open').upper()}] {item.get('id')}: {item.get('title')}"
                        for item in tracked[-20:]
                    ]
                    past.extend(tracked_summary)
            except Exception:
                pass

        scan_text = "\n\n".join(scans) or "(ไม่มีผลสแกนอัตโนมัติ — สำรวจโค้ดเอง)"
        hist_text = "\n".join(past) or "(ยังไม่เคยเสนอ)"

        tier_c_blocks.append(f"### Scan Results\n{scan_text}")
        tier_c_blocks.append(f"### History (Never repeat)\n{hist_text}")

    # Final Result Delivery Block
    rel_result_path = str(result_path)
    tier_c_blocks.append(
        f"# Final Result Delivery\n"
        f"Write final JSON (UTF-8) strictly to:\n"
        f"`{rel_result_path}`\n\n"
        f"Important: Ensure the JSON file is completely valid and follows the Output Schema defined above without conversational markdown or text outside the JSON."
    )

    # Concurrency constraint (if slot_id provided)
    if slot_id is not None:
        try:
            from .runner import REGISTRY
            colliding = REGISTRY.get_colliding_files(excluding_slot_id=slot_id)
            if colliding:
                file_list = ", ".join(f"`{f}`" for f in sorted(colliding))
                tier_c_blocks.append(
                    f"⚠️ **CONCURRENCY CONSTRAINT:** Other parallel workers are currently modifying: {file_list}.\n"
                    f"You MUST NOT modify or delete any of these files to avoid merge conflicts."
                )
        except Exception:
            pass

    tier_c_dynamic = "\n\n".join(tier_c_blocks).strip()

    return TieredPrompt(
        tier_a_static=tier_a_static,
        tier_b_semi_static=tier_b_semi_static,
        tier_c_dynamic=tier_c_dynamic,
    )


def format_provider_payload(prompt: TieredPrompt, provider: str = "default") -> dict | str:
    """Formats payload for Anthropic (with cache_control breakpoints), OpenAI, or standard text."""
    prov_lower = provider.lower()
    if "anthropic" in prov_lower or "claude" in prov_lower:
        return {
            "system": [
                {
                    "type": "text",
                    "text": prompt.tier_a_static,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": prompt.tier_b_semi_static,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {
                    "role": "user",
                    "content": prompt.tier_c_dynamic,
                }
            ],
        }

    return prompt.full_text

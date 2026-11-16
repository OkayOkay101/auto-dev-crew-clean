from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .stack_detector import StackProfile


@dataclass
class SkillEntry:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    instructions: str = ""
    path: Path | None = None


class SkillRegistry:
    PERSONA_TAG_MAP: dict[str, list[str]] = {
        "bolt": ["performance", "optimization", "profiling", "memory", "speed"],
        "palette": ["ui", "ux", "accessibility", "frontend", "design", "a11y"],
        "quality": ["testing", "code-quality", "refactoring", "debugging", "architecture"],
        "sentinel": ["security", "vulnerability", "audit", "hardening", "secrets"],
    }

    def __init__(self, search_paths: list[Path] | None = None):
        self._skills: dict[str, SkillEntry] = {}
        if search_paths is not None:
            self.search_paths = search_paths
        else:
            root = Path(__file__).resolve().parent.parent
            default_paths = [root / "skills"]
            home_skills = Path.home() / ".agents" / "skills"
            if home_skills.is_dir():
                default_paths.append(home_skills)
            self.search_paths = default_paths

    def register_builtin_skills(self) -> None:
        """Populates baseline fallback skills so agent personas always have domain guidance."""
        builtins = [
            SkillEntry(
                name="memory-leak-debugging",
                description="Diagnose memory leaks, object retention, and uncollected references.",
                tags=["performance", "memory", "profiling", "speed"],
                instructions="Use weak references, clear persistent global caches, and avoid accumulating unbounded lists across function executions."
            ),
            SkillEntry(
                name="a11y-debugging",
                description="Ensure WCAG accessibility, descriptive component labels, and keyboard usability.",
                tags=["ui", "ux", "accessibility", "a11y", "frontend"],
                instructions="Verify every interactive widget has an explicit aria/label, ensure high color contrast, and test tab-navigation order."
            ),
            SkillEntry(
                name="improve-codebase-architecture",
                description="Reduce module coupling, modularize oversized functions, and clean abstractions.",
                tags=["architecture", "code-quality", "refactoring", "testing"],
                instructions="Decouple business logic from UI/I/O handlers, extract single-responsibility helper functions, and preserve existing caller interfaces."
            ),
            SkillEntry(
                name="security-audit",
                description="Audit code for OWASP vulnerabilities, sanitization issues, and secret leaks.",
                tags=["security", "audit", "vulnerability", "hardening", "secrets"],
                instructions="Sanitize all untrusted inputs, enforce strict path traversal guards, avoid exposing raw tracebacks to users, and never commit secrets."
            ),
        ]
        for b in builtins:
            self._skills[b.name] = b

    def scan_directory(self, directory: Path) -> list[SkillEntry]:
        """Scans a directory containing skill subdirectories each with a SKILL.md file."""
        found = []
        if not directory.exists() or not directory.is_dir():
            return found

        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            entry = self._parse_skill_file(skill_file, default_name=skill_dir.name)
            if entry:
                found.append(entry)
                self._skills[entry.name] = entry
        return found

    def _parse_skill_file(self, skill_file: Path, default_name: str) -> SkillEntry | None:
        try:
            content = skill_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        name = default_name
        description = ""
        tags: list[str] = []

        # Check for YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                for line in frontmatter.splitlines():
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"\'')
                    elif line.startswith("tags:"):
                        raw_tags = line.split(":", 1)[1].strip()
                        if raw_tags.startswith("[") and raw_tags.endswith("]"):
                            tags = [t.strip().strip('"\'') for t in raw_tags[1:-1].split(",") if t.strip()]

        if not description:
            # Fall back to first non-heading paragraph
            lines = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.startswith("#") and not ln.startswith("---")]
            description = lines[0] if lines else "Custom agent skill."

        if not tags:
            # Infer tags from name
            tokens = re.split(r"[-_\s]+", name.lower())
            tags = [t for t in tokens if len(t) > 2]

        # Extract brief instructions (first ~300 chars after overview/headings)
        body = content.replace("---" + (parts[1] if content.startswith("---") and len(parts) >= 3 else "") + "---", "")
        instructions = body.strip()[:400].replace("\n", " ")

        return SkillEntry(name=name, description=description, tags=tags, instructions=instructions, path=skill_file)

    def scan_skills(self) -> dict[str, SkillEntry]:
        """Scans all configured search paths and returns the aggregated registry."""
        for path in self.search_paths:
            self.scan_directory(path)
        return self._skills

    def get_skills_for_persona(
        self,
        persona: str,
        tech_stack: StackProfile | None = None,
        limit: int = 3,
        configured_skills: list[str] | None = None
    ) -> list[SkillEntry]:
        """Matches relevant skills for a given persona, respecting explicit config overrides and limits."""
        if not self._skills:
            self.scan_skills()

        # 1. Explicit configuration takes highest priority
        if configured_skills is not None:
            result = []
            for name in configured_skills:
                if name in self._skills:
                    result.append(self._skills[name])
                else:
                    # Provide an ad-hoc skill entry for user-configured skill names
                    result.append(SkillEntry(name=name, description=f"Configured skill: {name}"))
            return result[:limit]

        # 2. Match by persona tags
        target_tags = set(self.PERSONA_TAG_MAP.get(persona.lower(), []))
        if tech_stack and tech_stack.frameworks:
            target_tags.update(tech_stack.frameworks)

        scored: list[tuple[int, SkillEntry]] = []
        for entry in self._skills.values():
            entry_tags = set(entry.tags)
            overlap = len(target_tags.intersection(entry_tags))
            if overlap > 0:
                scored.append((overlap, entry))

        # Sort by overlap score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        matched = [entry for _, entry in scored]

        return matched[:limit]

    def format_skills_for_prompt(self, skills: list[SkillEntry]) -> str:
        """Formats matched skills into concise, actionable prompt instructions."""
        if not skills:
            return "(No specialized skills currently loaded for this cycle — rely on core engineering workflow)"

        lines = []
        for s in skills:
            instr = f" Guidance: {s.instructions.strip()}" if s.instructions else ""
            lines.append(f"- **{s.name}**: {s.description}.{instr}")
        return "\n".join(lines)

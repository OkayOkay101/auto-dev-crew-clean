from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StackProfile:
    primary_language: str = "unknown"  # "python", "typescript", "javascript", "go", "rust", "unknown"
    frameworks: list[str] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)
    guidelines: list[str] = field(default_factory=list)


def detect_stack(repo_dir: Path) -> StackProfile:
    """Inspects top-level files in repo_dir to detect primary language and key frameworks."""
    profile = StackProfile()
    if not repo_dir.exists() or not repo_dir.is_dir():
        return profile

    repo_dir = repo_dir.resolve()
    top_files = {f.name: f for f in repo_dir.iterdir() if f.is_file()}

    # 1. Detect Python
    python_manifests = ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "setup.cfg"]
    has_python_manifest = any(m in top_files for m in python_manifests)
    has_py_files = any(f.endswith(".py") for f in top_files)

    # 2. Detect Node / TypeScript
    has_package_json = "package.json" in top_files
    has_tsconfig = "tsconfig.json" in top_files

    # 3. Detect Go / Rust
    has_go_mod = "go.mod" in top_files
    has_cargo = "Cargo.toml" in top_files

    if has_tsconfig or (has_package_json and any(f.endswith(".ts") or f.endswith(".tsx") for f in top_files)):
        profile.primary_language = "typescript"
    elif has_package_json:
        profile.primary_language = "javascript"
    elif has_python_manifest or has_py_files:
        profile.primary_language = "python"
    elif has_go_mod:
        profile.primary_language = "go"
    elif has_cargo:
        profile.primary_language = "rust"
    else:
        profile.primary_language = "unknown"

    # Scan dependencies from manifests
    dep_text = ""
    if "requirements.txt" in top_files:
        try:
            dep_text += " " + top_files["requirements.txt"].read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            pass

    if "pyproject.toml" in top_files:
        try:
            dep_text += " " + top_files["pyproject.toml"].read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            pass

    if "package.json" in top_files:
        try:
            pkg_data = json.loads(top_files["package.json"].read_text(encoding="utf-8", errors="ignore"))
            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
            dep_text += " " + " ".join(deps.keys()).lower()
        except Exception:
            pass

    # Quick scan of top-level code files for imports if dep_text is sparse
    for fname, fpath in list(top_files.items())[:20]:
        if fname.endswith((".py", ".js", ".ts", ".tsx")):
            try:
                head = fpath.read_text(encoding="utf-8", errors="ignore")[:2000].lower()
                dep_text += " " + head
            except Exception:
                pass

    # Detect Frameworks
    def match_word(word: str, text: str) -> bool:
        return bool(re.search(rf"\b{re.escape(word)}\b", text))

    frameworks_to_check = [
        "streamlit", "pandas", "fastapi", "flask", "django",
        "react", "next", "vue", "express", "pytorch", "tensorflow"
    ]
    for fw in frameworks_to_check:
        if match_word(fw, dep_text):
            if fw not in profile.frameworks:
                profile.frameworks.append(fw)

    # Detect Test Frameworks
    test_fw_check = ["pytest", "unittest", "jest", "vitest", "mocha"]
    for tfw in test_fw_check:
        if match_word(tfw, dep_text) or (tfw == "pytest" and "pytest.ini" in top_files):
            if tfw not in profile.test_frameworks:
                profile.test_frameworks.append(tfw)

    return profile


def load_stack_guideline(stack_name: str, prompts_dir: Path | None = None) -> str:
    """Loads a guideline markdown file from prompts/stacks/<stack_name>.md if available."""
    if prompts_dir is None:
        prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    guideline_file = prompts_dir / "stacks" / f"{stack_name}.md"
    if guideline_file.is_file():
        try:
            return guideline_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return ""


def format_stack_guidelines(profile: StackProfile, prompts_dir: Path | None = None) -> str:
    """Formats detected stack guidelines into a markdown section."""
    sections = []

    # Check for dedicated stack templates
    if profile.primary_language == "python":
        tmpl = load_stack_guideline("python_general", prompts_dir)
        sections.append(tmpl or "### Python Environment Guidelines\n- Write idiomatic, PEP8 compliant code.\n- Ensure proper type annotations.")

    if "streamlit" in profile.frameworks:
        tmpl = load_stack_guideline("streamlit", prompts_dir)
        sections.append(tmpl or "### Streamlit Framework Guidelines\n- Leverage `st.cache_data` and `st.cache_resource` effectively.\n- Ensure fast rerun execution without heavy repeated computations.")

    if "pandas" in profile.frameworks:
        tmpl = load_stack_guideline("pandas", prompts_dir)
        sections.append(tmpl or "### Pandas Guidelines\n- Avoid `.iterrows()` or `.apply()` on large datasets; use vectorized operations.\n- Specify dtypes where possible.")

    if "fastapi" in profile.frameworks:
        tmpl = load_stack_guideline("fastapi", prompts_dir)
        sections.append(tmpl or "### FastAPI Guidelines\n- Use asynchronous endpoints where I/O bound.\n- Enforce strict Pydantic models for validation.")

    if profile.primary_language in ("typescript", "javascript"):
        tmpl = load_stack_guideline("nodejs", prompts_dir)
        sections.append(tmpl or "### TypeScript/Node.js Guidelines\n- Enforce strict type definitions and clean async/await patterns.")

    if not sections:
        tmpl = load_stack_guideline("general", prompts_dir)
        sections.append(tmpl or "### General Engineering Guidelines\n- Keep code modular, well-tested, and maintainable.\n- Verify all changes before committing.")

    return "\n\n".join(sections)

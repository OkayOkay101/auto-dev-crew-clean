# github-docs Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `github-docs` skill: it writes and checks README, user guide, About text, and release notes in Thai and English, verifies each claim against the code, and hands off a PR only after the user approves.

**Architecture:** One skill folder with a workflow in `SKILL.md`, reference files per document type, and four stdlib-only Python checkers. Each checker is a small CLI that exits 0 on pass and 1 with a report on failure.

**Tech Stack:** Python 3 standard library only (`unittest`, `re`, `pathlib`, `subprocess`), Markdown.

**Spec:** [docs/superpowers/specs/2026-11-18-github-docs-design.md](../specs/2026-11-18-github-docs-design.md)

## Global Constraints

- Python standard library only; no `pip install` in any task.
- Documents are Thai and English. Thai file names: `README_TH.md`.
- Release notes: under 2000 characters; a `Breaking Changes` heading is always present, even when empty.
- No commit, push, PR, merge, or release-asset replacement without the user's explicit instruction.
- Do not copy code or text from doc-drift-detector (MIT + Commons Clause) or travcunn/diataxis-skill (CC BY-SA 4.0).
- Skill location is open (spec section 11, item 1). Tasks 1-7 build in `auto-dev-crew-clean/skills/github-docs/`; Task 8 moves or syncs it to the chosen location.

## Review Focus

1. **Thai UTF-8 with BOM or CRLF (Windows)**: the checkers must read `README_TH.md` written by Windows editors and still match headings and links. Test in Task 5.
2. **Windows path separators in links**: `docs\guide.md` or `..\x` in Markdown links must resolve like `/`. Test in Task 2.
3. **Links inside fenced code blocks**: examples in code must not count as broken links. Test in Task 2.
4. **Repo without git tags or PR history**: release-notes flow must stop with a clear message, not guess a range. Test in Task 4.
5. **Claim that matches a word, not a symbol**: `port` in prose must not count as a claim that the code defines it. Test in Task 3.

## File Structure

- Create: `skills/github-docs/SKILL.md` — workflow (spec 7.2)
- Create: `skills/github-docs/references/{readme,user-guide,release-notes,about-text,diataxis}.md`
- Create: `skills/github-docs/scripts/{check_links,check_claims,check_release_notes,check_bilingual}.py`
- Create: `skills/github-docs/tests/test_*.py` — one test module per script
- Create: `skills/github-docs/scripts/_md.py` — shared Markdown helpers (fence stripping, heading list, link extraction, UTF-8 BOM-safe read)

---

### Task 1: Shared Markdown helpers

**Files:**
- Create: `skills/github-docs/scripts/_md.py`
- Test: `skills/github-docs/tests/test_md.py`

**Interfaces:**
- Produces: `read_text(path: Path) -> str` (strips UTF-8 BOM, normalises CRLF to LF); `strip_fences(text: str) -> str` (blanks fenced code blocks, keeps line count); `headings(text: str) -> list[tuple[int, str]]` (level, title, outside fences); `links(text: str) -> list[tuple[int, str]]` (line number, target, outside fences).

- [ ] **Step 1: Write the failing test**

```python
def test_read_text_strips_bom_and_crlf(tmp_path):
    p = tmp_path / "README_TH.md"
    p.write_bytes("\ufeff# หัวข้อ\r\n".encode("utf-8"))
    assert read_text(p) == "# หัวข้อ\n"

def test_links_ignore_fenced_blocks():
    text = "[ok](a.md)\n```\n[fake](missing.md)\n```\n"
    assert links(text) == [(1, "a.md")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest skills/github-docs/tests/test_md.py -v`
Expected: FAIL with `ModuleNotFoundError: _md`

- [ ] **Step 3: Implement the four helpers in `skills/github-docs/scripts/_md.py`**

Fence detection toggles on lines starting with three backticks or tildes. `strip_fences` replaces fenced lines with empty lines so line numbers stay correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest skills/github-docs/tests/test_md.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit** — only when the user asks (see Global Constraints).

---

### Task 2: check_links.py

**Files:**
- Create: `skills/github-docs/scripts/check_links.py`
- Test: `skills/github-docs/tests/test_check_links.py`

**Interfaces:**
- Consumes: `_md.read_text`, `_md.links`, `_md.headings`.
- Produces: `check_file(md: Path, root: Path) -> list[str]` returning one message per broken link; CLI `python check_links.py <root>` exits 1 when any message exists.

- [ ] **Step 1: Write the failing tests**

```python
def test_missing_relative_file_is_reported(tmp_path):
    (tmp_path / "README.md").write_text("[g](docs/guide.md)\n", encoding="utf-8")
    msgs = check_file(tmp_path / "README.md", tmp_path)
    assert len(msgs) == 1 and "docs/guide.md" in msgs[0]

def test_windows_separator_resolves(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("[g](docs\\guide.md)\n", encoding="utf-8")
    assert check_file(tmp_path / "README.md", tmp_path) == []

def test_missing_anchor_is_reported(tmp_path):
    (tmp_path / "README.md").write_text("# Title\n[x](#nope)\n", encoding="utf-8")
    assert len(check_file(tmp_path / "README.md", tmp_path)) == 1

def test_link_in_code_fence_is_ignored(tmp_path):
    (tmp_path / "README.md").write_text("```\n[x](missing.md)\n```\n", encoding="utf-8")
    assert check_file(tmp_path / "README.md", tmp_path) == []

def test_external_urls_are_skipped(tmp_path):
    (tmp_path / "README.md").write_text("[x](https://example.com/a)\n", encoding="utf-8")
    assert check_file(tmp_path / "README.md", tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest skills/github-docs/tests/test_check_links.py -v`
Expected: FAIL with `ImportError: check_links`

- [ ] **Step 3: Implement `check_file` and the CLI**

Replace `\` with `/` before resolving. Skip `http(s)://`, `mailto:`. For `#anchor`, compare with GitHub-style slugs of the file's own headings (lowercase, spaces to `-`, drop punctuation except `-` and `_`; Thai characters kept).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest skills/github-docs/tests/test_check_links.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit** — only when the user asks.

---

### Task 3: check_claims.py

**Files:**
- Create: `skills/github-docs/scripts/check_claims.py`
- Test: `skills/github-docs/tests/test_check_claims.py`

**Interfaces:**
- Consumes: `_md.read_text`, `_md.strip_fences`.
- Produces: `extract_claims(text: str) -> list[Claim]` where `Claim` is `(line: int, kind: str, value: str)`, kind is `path` or `command`; `find_evidence(claim, repo: Path) -> str | None` returns `path:line` or `None`; CLI prints `claim -> path:line` or `UNSUPPORTED`, and exits 1 on any unsupported claim.

Only inline code spans are claims (backticks). Prose words are not claims. A `path` claim is a span containing `/` or `\` or ending in a known extension (`.py .md .json .ps1 .bat .toml .yml`). A `command` claim is a span starting with `python`, `npm`, `git`, `gh`, or `./`.

- [ ] **Step 1: Write the failing tests**

```python
def test_inline_path_is_extracted_and_prose_is_not():
    claims = extract_claims("Run `scripts/run.py` to start. The port is important.\n")
    assert [(c.kind, c.value) for c in claims] == [("path", "scripts/run.py")]

def test_path_with_evidence(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("x\ny\n", encoding="utf-8")
    assert find_evidence(Claim(1, "path", "scripts/run.py"), tmp_path) == "scripts/run.py:1"

def test_missing_path_is_unsupported(tmp_path):
    assert find_evidence(Claim(1, "path", "scripts/nope.py"), tmp_path) is None

def test_windows_path_claim_resolves(tmp_path):
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "build.ps1").write_text("x", encoding="utf-8")
    assert find_evidence(Claim(1, "path", "packaging\\build.ps1"), tmp_path) is not None

def test_fenced_span_is_not_a_claim():
    assert extract_claims("```\n`scripts/run.py`\n```\n") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest skills/github-docs/tests/test_check_claims.py -v`
Expected: FAIL with `ImportError: check_claims`

- [ ] **Step 3: Implement extraction, evidence lookup, and CLI**

For `command` claims, evidence is the first file under `repo` whose name matches the script in the command (e.g., `tests/test_launcher.py`). If none, report `UNSUPPORTED`. Keep command checks shallow; do not execute anything.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest skills/github-docs/tests/test_check_claims.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit** — only when the user asks.

---

### Task 4: check_release_notes.py

**Files:**
- Create: `skills/github-docs/scripts/check_release_notes.py`
- Test: `skills/github-docs/tests/test_check_release_notes.py`

**Interfaces:**
- Consumes: `_md.read_text`, `_md.headings`.
- Produces: `check_notes(text: str) -> list[str]` (empty list means pass); CLI `python check_release_notes.py <file>`. Also `range_from_tags(repo: Path) -> tuple[str, str] | None` that returns `None` when the repo has fewer than two tags, with a message telling the user to supply the range manually.

- [ ] **Step 1: Write the failing tests**

```python
def test_long_notes_fail():
    assert any("2000" in m for m in check_notes("# v1\n" + "a" * 2001 + "\n## Breaking Changes\n- none\n"))

def test_missing_breaking_heading_fails():
    assert any("Breaking Changes" in m for m in check_notes("# v1\n- fix\n"))

def test_thai_notes_counted_by_characters_pass():
    assert check_notes("# v1\n## Breaking Changes\n- ไม่มี\n") == []

def test_range_from_tags_returns_none_with_fewer_than_two_tags(tmp_path, monkeypatch):
    monkeypatch.setattr("check_release_notes._git_tags", lambda repo: ["v1.0.0"])
    assert range_from_tags(tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest skills/github-docs/tests/test_check_release_notes.py -v`
Expected: FAIL with `ImportError: check_release_notes`

- [ ] **Step 3: Implement `check_notes`, `range_from_tags`, `_git_tags` (wraps `git tag --sort=-creatordate`), and the CLI**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest skills/github-docs/tests/test_check_release_notes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit** — only when the user asks.

---

### Task 5: check_bilingual.py

**Files:**
- Create: `skills/github-docs/scripts/check_bilingual.py`
- Test: `skills/github-docs/tests/test_check_bilingual.py`

**Interfaces:**
- Consumes: `_md.read_text`, `_md.headings`, `_md.links`.
- Produces: `compare(en: Path, th: Path) -> list[str]` comparing heading levels in order and link targets in order; CLI `python check_bilingual.py <en> <th>`.

- [ ] **Step 1: Write the failing tests**

```python
def test_same_structure_passes(tmp_path):
    en = tmp_path / "README.md"; th = tmp_path / "README_TH.md"
    en.write_text("# A\n## B\n[x](a.md)\n", encoding="utf-8")
    th.write_text("\ufeff# ก\r\n## ข\r\n[x](a.md)\r\n", encoding="utf-8")
    assert compare(en, th) == []

def test_missing_heading_in_thai_fails(tmp_path):
    en = tmp_path / "README.md"; th = tmp_path / "README_TH.md"
    en.write_text("# A\n## B\n", encoding="utf-8")
    th.write_text("# ก\n", encoding="utf-8")
    assert any("heading" in m for m in compare(en, th))

def test_link_target_mismatch_fails(tmp_path):
    en = tmp_path / "README.md"; th = tmp_path / "README_TH.md"
    en.write_text("[x](docs/a.md)\n", encoding="utf-8")
    th.write_text("[x](docs/b.md)\n", encoding="utf-8")
    assert any("link" in m for m in compare(en, th))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest skills/github-docs/tests/test_check_bilingual.py -v`
Expected: FAIL with `ImportError: check_bilingual`

- [ ] **Step 3: Implement `compare` and the CLI**

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest skills/github-docs/tests/test_check_bilingual.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit** — only when the user asks.

---

### Task 6: SKILL.md and reference files

**Files:**
- Create: `skills/github-docs/SKILL.md`
- Create: `skills/github-docs/references/readme.md`, `user-guide.md`, `release-notes.md`, `about-text.md`, `diataxis.md`

**Interfaces:**
- Consumes: the four CLIs from Tasks 2-5 (names and exit codes exactly as above).
- Produces: nothing for code; the workflow steps the agent follows.

- [ ] **Step 1: Check frontmatter with a one-off command**

Run: `python -c "import pathlib,re; t=pathlib.Path('skills/github-docs/SKILL.md').read_text(encoding='utf-8'); assert re.match(r'^---\nname: github-docs\ndescription: .+\n---', t), 'bad frontmatter'; print('ok')"`
Expected: `ok` (this step fails until Step 2 is done)

- [ ] **Step 2: Write `SKILL.md`** with frontmatter (`name: github-docs`, one-line `description` that says when to use it), then the seven workflow steps from spec 7.2, the four check commands, and the rule that PR and release steps wait for user approval. Keep it under 150 lines; put detail in references.

- [ ] **Step 3: Write the five reference files.** Each one covers one doc type: section order, required headings, and what counts as evidence. `diataxis.md` is used only when the user asks for Diátaxis structure.

- [ ] **Step 4: Run the Step 1 command again**

Expected: `ok`

- [ ] **Step 5: Commit** — only when the user asks.

---

### Task 7: Dry run on a real repo

**Files:**
- None created. Output goes to the chat report only.

**Interfaces:**
- Consumes: all four CLIs and the SKILL.md workflow.

- [ ] **Step 1: Run the four checks against `C:\Users\Smart\Documents\DATAelectricWORKs`** (read-only; no files written there)

Run: `python skills/github-docs/scripts/check_links.py C:/Users/Smart/Documents/DATAelectricWORKs`
Run: `python skills/github-docs/scripts/check_bilingual.py C:/Users/Smart/Documents/DATAelectricWORKs/README.md C:/Users/Smart/Documents/DATAelectricWORKs/README_TH.md`
Expected: each exits 0, or lists specific real problems to report. Do not fix the target repo.

- [ ] **Step 2: Report results** to the user with the exact output. Mark anything not checked (for example, command claims) as not verified.

---

### Task 8: Install into the chosen location and verify catalog search

**Files:**
- Depends on the user's answer to spec section 11, item 1.

**Interfaces:**
- Consumes: the finished folder from Tasks 1-7.

- [ ] **Step 1: Ask the user** where the skill lives (local `~/.claude/skills` or catalog checkout `C:\Users\Smart\Documents\ChatGPT\test`). Do not guess.

- [ ] **Step 2: Copy the folder to that location** and, for the catalog, run `scripts/sync_local_skills.py` from that checkout.

- [ ] **Step 3: Verify.** Run `search_skills` for "github docs README" and confirm `github-docs` appears. Report found, loaded, and tested as three separate lines. Searching only proves found.

---

## Self-Review Notes

- Spec coverage: sections 7.1-7.4 map to Tasks 1-6; section 9 testing maps to each task's tests and Task 7; section 11 items map to Task 8 and the Global Constraints note.
- Types: `Claim(line, kind, value)`, `check_file`, `check_notes`, `range_from_tags`, and `compare` are used with the same names in every task that references them.
- Review Focus lines each have a test in their owning task (Tasks 5, 2, 2, 4, 3).

# STATE: github-docs skill (Library Router)

## Goal
Build a deep, reusable skill `github-docs` in the Library Router catalog. When the user asks in this app to "write documentation" for a repo, the agent reads the code, verifies every claim, writes Thai and English docs, runs checks, and opens a PR. It may also cover release notes and repo About text. Chosen approach: option 1 (one broad skill with reference files per doc type).

## Open
- [ ] Write the full design doc (file path TBD, under docs/superpowers/specs or the catalog) — AI · ready
- [ ] User approves the design doc — user · needs-approval
- [ ] Build skill dir + check_links.py / check_claims.py / release-notes length check — AI · needs-approval (after approval)
- [ ] Add to catalog and sync with scripts/sync_local_skills.py, then verify search returns it — AI · needs-approval
- [ ] Decide where the skill lives: a local source folder read by the sync script (e.g. ~/.claude/skills) vs. the catalog checkout — user · ready

## In progress (for the next agent)
Research done, no files written. Comparison:
- github/awesome-copilot documentation-writer: Diataxis, no code checks, no PR flow.
- antinomyhq/forge write-release-notes: GitHub release/PR fetch, length check (under 2000 chars).
- Our edge: claim checks, link checks, bilingual pairs, PR/release flow in one skill.

## Done (verified unless noted)
- DATAelectricWORKs: PR #203 (user guide + README EN/TH) merged, commit 17d8650.
- DATAelectricWORKs: PR #204 (build script + launcher) merged, commit c28bc9c.
- Release v1.0.0 asset rebuilt from c28bc9c; checksum matches 1ee624a7…c409c4; exe health 200.
- Repo description and topics set. Not verified: upload flow in the exe; guide screenshots.

## Files
- C:\Users\Smart\Documents\DATAelectricWORKs (README*, docs\USER_GUIDE_*, packaging\, tests\test_launcher.py)
- Router skill: C:\Users\Smart\.claude\skills\library-router-plugin\skills\router\SKILL.md
- Catalog checkout: C:\Users\Smart\Documents\ChatGPT\test (scripts\sync_local_skills.py)

## How to check
restart: read this file, then write the design doc. Do not build before approval.
- cd C:\Users\Smart\Documents\DATAelectricWORKs; python -m unittest discover -s tests -p "test_*.py" (expect 203 tests, 1 skipped)
- gh release view v1.0.0 -R OkayOkay101/DATAelectricWORKs

## Decisions
- Work starts from this app (not @claude on GitHub). Build the skill in the Library Router.
- Option 1: one broad skill with reference files, not a skill family.
- Release and PR steps: merge only after the user says so; replace release assets only after a build check.

## Summary
- เป้าหมาย: สร้างสกิล github-docs ใน Library Router ให้เขียนเอกสาร GitHub ได้ลึก
- ค้นสกิลคล้ายกันแล้ว ยังไม่มีตัวไหนตรวจกับโค้ดและทำ PR ครบ
- รอคุณอนุมัติ design doc ก่อนสร้างสกิล

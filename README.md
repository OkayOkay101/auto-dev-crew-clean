# Auto Dev Crew 🤖

## English

**Auto Dev Crew is a local AI coding agent.** It takes work from GitHub issues and opens pull requests for that work. When its queue is empty, four personas (⚡🛡️🎨🧪) scan the code on their own and look for improvements.

**Languages:** English (this section) · [ภาษาไทย](#ภาษาไทย) · Thai-only file: [README.th.md](README.th.md)

It uses the **Antigravity CLI (`agy`)** with a Google AI Pro account as its main engine, and supports **Multi-Engine Failover (F6)**: when a quota runs out, it switches automatically to OpenCode or NVIDIA Build (primary) and Pollinations.ai or Mistral (backup). Budget target: 0 THB.

> **Status:** experimental project, private repository.

- Full requirements: [REQUIREMENTS.md](REQUIREMENTS.md) (early draft, kept as design history; see the note at the end).
- Detailed description, AI usage, and GUI status: [docs/en/ABOUT.md](docs/en/ABOUT.md)
- Thai docs: [docs/README.md](docs/README.md)

## Install (once)
1. Install Python 3.12+, Git, the GitHub CLI (`gh auth login`), and the Antigravity CLI (signed in with the AI Pro account).
2. `pip install -r requirements.txt`
3. Edit `config.yaml` (repo, merge mode, personas). Start from `config.example.yaml`, which is the tracked template.

## How to give work
- Open an issue in the target repo and add the label **`ai-task`** (only the `owner` account set in the config counts).
- Emergency stop: open any issue and add the label **`ai-pause`** (close the issue to resume).

## GUI (local web page)
```bash
python -m auto_dev_crew.gui          # opens http://127.0.0.1:8765 automatically
python -m auto_dev_crew.gui --auto   # same, plus starts the agent in --loop mode right away
# (the Desktop button / start-auto-dev-crew.bat opens the GUI and waits for you to press start)
```
The main page is `http://127.0.0.1:8765/`. The left menu has 5 pages:
- **Overview**: press **▶ Run 1 task** (does one item and stops) or **⟳ Run continuously** (keeps going until you stop). **■ Stop** cancels the current task (asks for confirmation). **🔄 Restart** is under "More". Shows the 3 work slots and a card for each repo.
- **Jobs**: live logs and job history (view diffs).
- **Studio**: ask the AI to change code in a chosen repo, view diffs, find `[AI-TODO]`, run a deep scan, and make feature plans (`ai-plan`).
- **AI keys**: keys and providers, failover order, recent usage.
- **Settings**: merge mode, CI checks, quality checks (judge), the full glossary, and shutting down the server.

The GUI only listens on this machine (127.0.0.1). Requests that change data (POST) need a token embedded in the page.

**Restart the agent when**: you edit `config.yaml` directly, or change a key's role (Coder/Judge/Scan). Press restart on the Overview page (this cancels the current task and starts a new round with the same settings; open PRs are not closed).
- After changing a key's role, **reload the page** first, because the engine list in the dropdown is read when the page loads, and then restart.
- Before restarting or stopping, check on the Overview page whether the slots are empty. If a task is running, it will be cancelled.
- If you run `python -m auto_dev_crew --loop` outside the GUI yourself, the GUI will see that runner and you can stop it with the stop button.

**Key terms** (full list on Settings › Glossary):
- **Slot**: one worker. Up to 3 can run in parallel. Slot 1 handles issues you request; slots 2–3 look for improvements on their own according to their persona.
- **judge**: the AI that scores the changed code before a PR is opened. Needs a key with the Judge role.
- **Gates 1–4**: Gate 1, the judge confirms the bug before a fix · Gate 2, the judge sees the full file after the fix · Gate 3, every issue run that names a file must touch that file · Gate 4, deep-scan re-checks before an issue is created.
- **key role**: Coder = writes the main code (default for every key) · Judge = scores · Scan = looks for problems. Variable names containing `_JUDGE` or `_SCAN` get that role automatically if you do not set it yourself.
- **F6 failover (fallback order)**: switch to the next provider when a quota runs out. The top one is tried first.
- **ai-task**: an issue the agent picks up (you requested it, or the system created it from deep-scan or an approved plan).
- **ai-plan**: an issue proposing a feature that waits for approval. Once approved, the system creates an `ai-task` for it.
- **deep-scan**: the AI reads the code section by section and reports problems. Results that pass Gate 4 can become `ai-task` issues. Gate 4 applies only to automatic issue creation; the per-finding create button skips it.
- **check_convergence** (`auto_dev_crew/evaluator.py`): checks whether the score has stopped improving. It runs in the repair loop after evaluation (`runner.py`) when `evaluation.plateau_stop` is true (the default). If the score does not improve, the repair rounds stop and no more quota is spent.

## Command-line usage
```bash
python -m auto_dev_crew --dry-run                 # try locally, does not touch GitHub
python -m auto_dev_crew --dry-run --persona bolt  # try one persona
python -m auto_dev_crew                           # do one task, then open a PR
python -m auto_dev_crew --loop                    # keep going until no work / quota out / PRs pending
```

Personas: `bolt` (performance) · `sentinel` (security) · `palette` (UX/UI) · `quality` (tests/quality)

## Merge modes (`merge_mode` in config.yaml or the Settings page)
This is the global default for the whole system. The mode in use is shown in the `merge:` badge at the top right of the GUI and in the Settings page. The code reads this value directly from config.yaml, so the file must always contain it.

| Mode | Result |
|---|---|
| `review-all` | Only opens PRs. The system does not merge. A person merges. |
| `small-only` | Merges by itself only small PRs (no more than `small_pr.max_lines` lines; the value in config.yaml is 50) that do not touch `small_pr.protected_paths`, such as `.github/` and `requirements*`. Everything else waits for review. |
| `merge-all` | Merges every PR by itself when CI passes. The GUI asks for confirmation before switching to this mode. |

- **Merge level per repo** (set in a new feature plan in the GUI, or `merge_level` per repo): if a repo has its own level, that level is used instead of the global mode.
- **New values apply to the next merge decision** (the system rereads the config while it runs). If you edit the file yourself, restart to be sure.

## CI check before merge (`ci.allow_no_ci` global, can be set per repo)
- **Flexible** (`allow_no_ci: true`): a repo with no CI on GitHub can merge once the local tests pass.
- **Strict** (`allow_no_ci: false`): a repo with no CI never merges. CI must exist and pass on GitHub.
- In both cases: if CI exists and fails, nothing merges. If a workflow exists but no check has run on the PR yet, the system waits for the next round.

## judge (quality check before a PR is opened)
The judge is an AI that scores the diff. It passes when the score reaches the threshold and it meets the safety and task-match conditions. It needs a key with the `judge` role (the system chooses keys by role). You can turn it off on the Settings page.

## Harness settings
These are set under `context`, `loop`, and `routing` in `config.yaml`. You do not need to edit the file; the defaults are in the code.
- `context.repo_map` (default `true`): attaches the structure of Python code (function and class names and signatures) to the prompt. Set to `false` to turn it off.
- `context.repo_map_chars` (default `6000`): maximum characters for the repo map.
- `loop.require_test_for_bugfix` (default `true`): a bug fix (an issue containing "bug" or "fix") that does not touch any test file gets one more round in which the agent adds a regression test, before the result is evaluated. Set to `false` to turn it off.
- `routing.enabled` (default `true`): orders the engines by merge results in the job history (`state/history.json`), separately for each triage path. An engine with at least `routing.min_samples` summarized results moves up first (sorted by merge rate, high to low). The rest keep their order from config.yaml. Set to `false` to always use the order in config.yaml.
- `routing.min_samples` (default `5`): minimum number of summarized results per engine before its data is used for ordering.
- `routing.demote_below` (default `0.2`): an engine whose merge rate is below this value (and that has enough samples) moves to the end, after engines with no data yet. No engine is removed.

If the repo contains `AGENTS.md`, `CLAUDE.md`, or `.github/copilot-instructions.md`, it is attached automatically as "Repository Notes" (up to 4000 characters).

## Files
- `auto_dev_crew/runner.py`: job queue, clone, calling the agent, tests, PRs, merge, reports
- `prompts/`: prompts for issue work, test fixes, and the 4 personas (`_rules.md` = shared rules)
- `state/history.json`: memory of what was already proposed (not committed)
- Temporary work: `~/.auto-dev-crew/work`; the venv for each repo: `~/.auto-dev-crew/venvs`

## Important rules
- Never force-push, and never push straight to `main`. Merge only through a PR.
- Never commit `config.yaml` (it holds owner-specific values).
- Never print or copy values from `.env`. You may check only variable names or lengths.
- Never delete or skip tests. If a test looks wrong, stop and ask the owner.
- The scan and create-issue buttons in the GUI ask for `confirm()` first. Do not bypass this with JavaScript.
- Agent branches start with `ai/` and can open PRs (the name `self/*` is used only in revert plans).

## Check that the system still works
1. Full test suite: `python -m pytest -q -p no:cacheprovider` (there must be no failures).
2. Open the GUI: `python -m auto_dev_crew.gui --no-browser`, then `curl http://127.0.0.1:8765/api/status` should return JSON.
3. Smoke test (the GUI must be open and a slot free): `python scripts/gui_smoke.py` should print `PASS`. This step only reads and does not press run buttons.
4. e2e test (the GUI must be open and a slot free): `python scripts/gui_e2e.py --repo OWNER/NAME` presses the run button in a real dry run. Run it only when a slot is free, because if a slot is busy it may collide with a running task.

> **Note:** [REQUIREMENTS.md](REQUIREMENTS.md) is an early v0.2 draft. The system now uses the Antigravity CLI (`agy`) as the main engine and does not run on GitHub Actions as that draft describes. Read it as design history, not as the current specification.

---

## ภาษาไทย
เอเจนต์เขียนโค้ดเบื้องหลังแทน Jules — รับงานจาก GitHub issue แล้วเปิด PR, และเมื่อคิวว่างให้ตัวละคร ⚡🛡️🎨🧪 หาจุดปรับปรุงเอง
ใช้ **Antigravity CLI (`agy`)** บัญชี Google AI Pro เป็นหลัก และรองรับ **Multi-Engine Failover (F6)** สลับไปยัง OpenCode หรือ NVIDIA Build (ค่าหลัก) และ Pollinations.ai หรือ Mistral (สำรอง) อัตโนมัติเมื่อโควตาหมด งบ 0 บาท

ดูข้อกำหนดทั้งหมดใน [REQUIREMENTS.md](REQUIREMENTS.md)
คำอธิบายการทำงานอย่างละเอียด การใช้ AI และสถานะ GUI ดูที่ [docs/ABOUT.md](docs/ABOUT.md)
English: [English section](#english) · English docs (About, configuration, API, and more): [docs/en/README.md](docs/en/README.md)

## ติดตั้ง (ครั้งเดียว)
1. ติดตั้ง Python 3.12+, Git, GitHub CLI (`gh auth login`) และ Antigravity CLI (ล็อกอินบัญชี AI Pro แล้ว)
2. `pip install -r requirements.txt`
3. แก้ `config.yaml` (repo, โหมด merge, ตัวละคร)

## วิธีสั่งงาน
- เปิด issue ใน repo เป้าหมาย แล้วติดป้าย **`ai-task`** (ต้องเป็นบัญชี `owner` ใน config เท่านั้น)
- หยุดเอเจนต์ฉุกเฉิน: เปิด issue ใดก็ได้แล้วติดป้าย **`ai-pause`** (ปิด issue เพื่อให้ทำต่อ)

## GUI (เว็บในเครื่อง)
```bash
python -m auto_dev_crew.gui          # เปิด http://127.0.0.1:8765 ให้อัตโนมัติ
python -m auto_dev_crew.gui --auto   # เหมือนข้างบน + เริ่มเอเจนต์ --loop ทันที
# (ปุ่ม Desktop / start-auto-dev-crew.bat จะเปิด GUI แบบรอเรากดเริ่มเอง)
```
หน้าหลักคือ `http://127.0.0.1:8765/` เมนูซ้ายมี 5 หน้า:
- **ภาพรวม**: กด **▶ ทำ 1 งาน** (ทำหนึ่งชิ้นแล้วหยุดเอง) หรือ **⟳ ทำต่อเนื่อง** (ทำไปเรื่อย ๆ จนกดหยุด) · **■ หยุด** ยกเลิกงานที่กำลังทำ (ถามยืนยันก่อน) · **🔄 รีสตาร์ท** อยู่ในหัวข้อ "เพิ่มเติม" · ดูช่องทำงาน 3 ช่อง และการ์ดคลังโค้ดแต่ละ repo
- **งาน**: บันทึกสด (log) และประวัติงาน (ดู diff)
- **สตูดิโอ**: สั่ง AI แก้โค้ดใน repo ที่เลือก, ดู diff, หา `[AI-TODO]`, สแกนลึก, แผนฟีเจอร์ (`ai-plan`)
- **คีย์ AI**: คีย์และผู้ให้บริการ, ลำดับสำรอง (failover), การใช้งานล่าสุด
- **ตั้งค่า**: โหมด merge, การตรวจ CI, การตรวจคุณภาพ (judge), คำศัพท์ทั้งหมด, ปิดเซิร์ฟเวอร์

GUI เปิดให้เฉพาะเครื่องนี้ (127.0.0.1) และคำสั่งที่เปลี่ยนแปลงข้อมูล (POST) ต้องมี token ที่ฝังในหน้าเว็บ

**ต้องรีสตาร์ทเอเจนต์เมื่อ**: แก้ `config.yaml` โดยตรง หรือเปลี่ยนบทบาทของคีย์ (Coder/Judge/Scan) — กดรีสตาร์ทในหน้าภาพรวม (ผลคือยกเลิกงานที่กำลังทำ แล้วเริ่มรอบใหม่ด้วยค่าเดิม; PR ที่เปิดแล้วไม่ถูกปิด)
- หลังเปลี่ยนบทบาทคีย์ ให้**รีโหลดหน้า** ก่อน เพราะรายการ engine ใน dropdown อ่านค่าตอนโหลดหน้า แล้วจึงรีสตาร์ท
- ก่อนรีสตาร์ทหรือหยุด ให้ดูว่าช่องทำงานว่างหรือไม่ในหน้าภาพรวม ถ้ามีงานกำลังทำ งานนั้นจะถูกยกเลิก
- ถ้ารัน `python -m auto_dev_crew --loop` นอก GUI เอง GUI จะเห็น runner นั้นและหยุดได้จากปุ่มหยุด

**คำศัพท์หลัก** (อธิบายครบในหน้า ตั้งค่า › คำศัพท์):
- **ช่อง (slot)**: ตัวทำงาน 1 ตัว รันได้พร้อมกัน 3 ช่อง · ช่อง 1 ทำ issue ที่คุณสั่ง · ช่อง 2–3 หาจุดปรับปรุงเองตามบทบาท
- **judge**: AI ที่ให้คะแนนโค้ดที่แก้ก่อนเปิด PR ต้องใช้คีย์บทบาท Judge
- **ด่านตรวจ 1–4**: ด่าน 1 judge ยืนยันบั๊กก่อนแก้ · ด่าน 2 judge เห็นไฟล์เต็มหลังแก้ · ด่าน 3 รอบซ่อมต้องแตะไฟล์ที่ issue ระบุ · ด่าน 4 deep-scan ตรวจซ้ำก่อนสร้าง issue
- **key role**: Coder = เขียนโค้ดหลัก (ค่าเริ่มต้นของคีย์ทุกตัว) · Judge = ให้คะแนน · Scan = สแกนหาปัญหา · ชื่อตัวแปรที่มี `_JUDGE` / `_SCAN` ได้บทบาทนั้นอัตโนมัติถ้าไม่ได้ตั้งเอง
- **F6 failover (ลำดับสำรอง)**: สลับไปผู้ให้บริการตัวถัดไปเมื่อโควตาหมด ตัวบนสุดก่อน
- **ai-task**: issue ที่เอเจนต์หยิบไปทำ (คุณสั่งเอง หรือระบบสร้างจาก deep-scan / แผนที่อนุมัติ)
- **ai-plan**: issue เสนอฟีเจอร์ที่รอการอนุมัติ เมื่ออนุมัติแล้วระบบสร้าง `ai-task` ให้
- **deep-scan (สแกนลึก)**: ให้ AI อ่านโค้ดทีละส่วนแล้วรายงานปัญหา ผลที่ผ่านด่าน 4 สร้างเป็น `ai-task` ได้
- **check_convergence** (`auto_dev_crew/evaluator.py`): ตรวจว่าคะแนนค้างแล้วหรือยัง ถูกเรียกในลูปซ่อมหลังประเมิน (`runner.py`) เมื่อ `evaluation.plateau_stop` เป็น true (ค่าเริ่มต้น) ถ้าคะแนนไม่ดีขึ้นจะหยุดรอบซ่อมและไม่ใช้โควตาซ้ำ

## วิธีรันแบบคำสั่ง
```bash
python -m auto_dev_crew --dry-run                 # ทดลองในเครื่อง ไม่แตะ GitHub
python -m auto_dev_crew --dry-run --persona bolt  # ทดลองตัวละครตัวเดียว
python -m auto_dev_crew                           # ทำ 1 งาน แล้วเปิด PR
python -m auto_dev_crew --loop                    # ทำต่อเนื่องจนหมดงาน/โควตาหมด/มี PR ค้าง
```

ตัวละคร: `bolt` (performance) · `sentinel` (security) · `palette` (UX/UI) · `quality` (เทสต์/คุณภาพ)

## โหมด merge (`merge_mode` ใน config.yaml หรือหน้า ตั้งค่า)
ค่านี้เป็นค่ากลางของทั้งระบบ ค่าที่ใช้อยู่ตอนนี้ดูได้ที่ป้าย `merge:` มุมขวาบนของ GUI และตัวเลือกในหน้า ตั้งค่า · โค้ดอ่านค่านี้จาก config.yaml โดยตรง จึงต้องมีค่าในไฟล์เสมอ

| โหมด | ผล |
|---|---|
| `review-all` | เปิด PR อย่างเดียว ระบบไม่ merge เอง คนเป็นผู้ merge |
| `small-only` | merge เองเฉพาะ PR เล็ก (ไม่เกิน `small_pr.max_lines` บรรทัด ค่าใน config.yaml = 50) และไม่แตะ `small_pr.protected_paths` เช่น `.github/`, `requirements*` ที่เหลือรอคนตรวจ |
| `merge-all` | merge เองทุก PR เมื่อ CI ผ่าน (GUI จะถามยืนยันก่อนเปลี่ยนมาเป็นโหมดนี้) |

- **ระดับ merge รายคลังโค้ด** (ตั้งในแผนฟีเจอร์ใหม่ใน GUI หรือ `merge_level` ต่อ repo): ถ้า repo มีระดับของตัวเอง จะใช้ระดับนั้นแทนค่ากลาง
- **ค่าใหม่มีผลกับการตัดสิน merge ครั้งถัดไป** (ระบบอ่าน config ใหม่ระหว่างทำงาน) แต่ถ้าแก้ไฟล์เองให้รีสตาร์ทเพื่อความแน่นอน

## ตรวจ CI ก่อน merge (`ci.allow_no_ci` ค่ากลาง, ตั้งรายคลังโค้ดได้)
- **ยืดหยุ่น** (`allow_no_ci: true`): repo ที่ไม่มี CI บน GitHub → merge ได้หลังเทสต์ในเครื่องผ่าน
- **บังคับ** (`allow_no_ci: false`): repo ที่ไม่มี CI → ไม่ merge เลย ต้องมี CI และผ่านบน GitHub
- ทั้งสองแบบ: ถ้ามี CI แล้วล้มเหลว จะไม่ merge; ถ้ามี workflow แต่ยังไม่มี check รันบน PR ระบบจะรอรอบถัดไป

## judge (ตรวจคุณภาพก่อนเปิด PR)
judge คือ AI ที่ให้คะแนน diff ผ่านเมื่อคะแนนถึงเกณฑ์และผ่านเงื่อนไขความปลอดภัย/ความตรงกับงาน ต้องมีคีย์ที่มีบทบาท `judge` (ระบบจะเลือกคีย์ตามบทบาท) ปิดได้ที่หน้า ตั้งค่า

## Harness settings
ตั้งค่าเพิ่มเติมใต้ `context` ใน `config.yaml` (ไม่ต้องแก้ไฟล์ — ค่าเริ่มต้นอยู่ในโค้ด)
- `context.repo_map` (ค่าเริ่มต้น `true`) — แนบโครงสร้างโค้ด Python (ชื่อฟังก์ชัน/คลาสและ signature) ลงใน prompt; ตั้งเป็น `false` เพื่อปิด
- `context.repo_map_chars` (ค่าเริ่มต้น `6000`) — จำนวนตัวอักษรสูงสุดของ repo map
- `loop.require_test_for_bugfix` (ค่าเริ่มต้น `true`) — งานแก้บั๊ก (issue ที่มีคำว่า bug/fix) ที่ไม่ได้แก้ไฟล์เทสต์เลย จะได้เอเจนต์เพิ่มเทสต์ regression อีก 1 รอบก่อนประเมินผล; ตั้งเป็น `false` เพื่อปิด
- `routing.enabled` (ค่าเริ่มต้น `true`) — จัดลำดับเอ็นจินตามผล merge ในประวัติงาน (`state/history.json`) แยกตาม triage path; เอ็นจินที่มีผลสรุปอย่างน้อย `routing.min_samples` ครั้งจะถูกย้ายขึ้นก่อน (เรียงตาม merge rate มาก→น้อย) ที่เหลือคงลำดับใน `config.yaml`; ตั้งเป็น `false` เพื่อใช้ลำดับใน config เสมอ
- `routing.min_samples` (ค่าเริ่มต้น `5`) — จำนวนผลสรุปขั้นต่ำต่อเอ็นจินก่อนจะใช้ข้อมูลในการจัดลำดับ
- `routing.demote_below` (ค่าเริ่มต้น `0.2`) — เอ็นจินที่มี merge rate ต่ำกว่าค่านี้ (และมีข้อมูลครบ `min_samples`) จะถูกย้ายไปท้ายสุด หลังเอ็นจินที่ยังไม่มีข้อมูล; ไม่มีการตัดเอ็นจินออก

ไฟล์ `AGENTS.md` หรือ `CLAUDE.md` (หรือ `.github/copilot-instructions.md`) ในรีโพจะถูกแนบเป็น "Repository Notes" อัตโนมัติ (สูงสุด 4000 ตัวอักษร)

## ไฟล์
- `auto_dev_crew/runner.py` — คิวงาน, clone, เรียกเอเจนต์, เทสต์, PR, merge, รายงาน
- `prompts/` — prompt งาน issue, การแก้เทสต์, และตัวละครทั้ง 4 (`_rules.md` = กฎร่วม)
- `state/history.json` — ความจำว่าเคยเสนออะไรไปแล้ว (ไม่ commit)
- งานชั่วคราว: `~/.auto-dev-crew/work`, venv ของแต่ละ repo: `~/.auto-dev-crew/venvs`

## ข้อห้ามสำคัญ
- ห้าม force-push และห้าม push เข้า `main` ตรง ๆ ต้อง merge ผ่าน PR เท่านั้น
- ห้าม commit `config.yaml` (ค่าเฉพาะของเจ้าของ)
- ห้ามพิมพ์หรือคัดลอกค่าใน `.env` ตรวจได้แค่ชื่อตัวแปรหรือความยาว
- ห้ามลบหรือข้ามเทสต์ ถ้าเทสต์ดูผิดจริงให้หยุดแล้วถามเจ้าของ
- ปุ่มสแกนและสร้าง issue ใน GUI มี `confirm()` ก่อนทำงาน ห้ามข้ามด้วย JavaScript
- เอเจนต์สร้าง branch ที่ขึ้นต้นด้วย `ai/` และเปิด PR ได้ (ชื่อ `self/*` ใช้เฉพาะแผน revert)

## ตรวจว่าระบบยังใช้งานได้
1. เทสต์ชุดเต็ม: `python -m pytest -q -p no:cacheprovider` (ต้องไม่มี failed)
2. เปิด GUI: `python -m auto_dev_crew.gui --no-browser` แล้วทดสอบ `curl http://127.0.0.1:8765/api/status` ต้องได้ JSON
3. smoke test (GUI ต้องเปิดอยู่และ slot ว่าง): `python scripts/gui_smoke.py` ต้องขึ้น `PASS` ขั้นนี้อ่านอย่างเดียว ไม่กดปุ่มรันงาน
4. e2e test (GUI ต้องเปิดอยู่และ slot ว่าง): `python scripts/gui_e2e.py --repo OWNER/NAME` กดปุ่มทำงานแบบ dry-run จริง รันเมื่อ slot ว่างเท่านั้น เพราะถ้า slot ไม่ว่างอาจชนกับงานที่รันอยู่

# เครื่องมือ สคริปต์ และ CI

เอกสารนี้รวบรวมสคริปต์ในโฟลเดอร์ `scripts/`, MCP server, โหมด autonomous ของ Claude Code, การทดสอบ และ CI

---

## 1. สคริปต์ใน `scripts/`

| ไฟล์ | ใช้ทำอะไร | วิธีรัน |
|---|---|---|
| `gui_smoke.py` | ตรวจว่า GUI เปิดได้ โหลดหน้าได้โดยไม่มี JS error อ่านอย่างเดียว ไม่กดปุ่มรันงาน | `python scripts/gui_smoke.py [--url http://127.0.0.1:8765] [--shot state/gui_smoke.png]` |
| `gui_e2e.py` | กดปุ่มทำงานแบบ dry-run ด้วย Playwright ใช้ repo ทดสอบเท่านั้น ควรรันเมื่อช่องว่าง | `python scripts/gui_e2e.py --repo OWNER/NAME` |
| `gui_watchdog.py` | ตรวจ `/api/status` ถ้าไม่ตอบจะเริ่ม GUI ใหม่แบบ `--no-browser --auto` ในโปรเซสแยก | `python scripts/gui_watchdog.py` (ระบบไม่ได้ตั้งเวลารันให้ ถ้าต้องการให้รันซ้ำเป็นระยะ ต้องตั้งเองในระบบปฏิบัติการ) |
| `engine_judge_eval.py` | ประเมิน engine ของ OpenCode ด้วยวิธี LLM-as-judge และตรวจแบบกำหนดตายตัวก่อน | อ่านหัวไฟล์สำหรับอาร์กิวเมนต์ |
| `opencode_db_doctor.py` | ตรวจและซ่อม `opencode.db` (ตาราง workspace ไม่มี `project_id`) ค่าเริ่มต้นเป็น dry-run | `python scripts/opencode_db_doctor.py` (ใส่ `--apply` เพื่อสำรองแล้วซ่อมจริง ควรปิด OpenCode ก่อน) |
| `autonomous_ctl.py` | เปิด ปิด หรือดูสถานะโหมด autonomous ของ Claude Code | ดูหัวข้อ 3 |
| `autonomous_common.py` | ฟังก์ชันร่วมของโหมด autonomous | ไม่รันโดยตรง |
| `autonomous_guard_hook.py` | hook PreToolUse ที่บล็อกคำสั่งอันตรายขณะเปิดโหมด autonomous | ตั้งเป็น hook ของ Claude Code |
| `autonomous_stop_hook.py` | hook Stop ที่ให้เซสชันทำต่อจนกว่าจะลบธง หรือถึงจำนวนรอบสูงสุด | ตั้งเป็น hook ของ Claude Code |

---

## 2. MCP server

`auto_dev_crew/mcp_server.py` เป็น MCP server แบบ stdio ที่ไม่ต้องมี dependency เพิ่ม (ใช้ JSON-RPC 2.0 บน Python 3.12 stdlib)

```bash
python -m auto_dev_crew.mcp_server --transport stdio
```

tool ที่มีเป็นแบบอ่านอย่างเดียว เช่น สถานะ daemon สถานะช่อง `merge_mode` และสุขภาพ engine (F6) และสรุป PR ที่ merge แล้วข้ามคืนพร้อมคำขออนุมัติที่ค้าง

ใช้ได้กับ MCP client ที่รองรับ stdio ตั้งค่าใน client ตามเอกสารของ client นั้น

---

## 3. โหมด autonomous (สำหรับ Claude Code)

โหมดนี้ให้เซสชัน Claude Code ทำงานต่อเนื่องตามเป้าหมาย (mission) แยกจาก runner ของ Auto Dev Crew

```bash
python scripts/autonomous_ctl.py on --mission "เป้าหมายงาน"
python scripts/autonomous_ctl.py on --mission-file path/to/mission.md
python scripts/autonomous_ctl.py off
python scripts/autonomous_ctl.py status
```

กลไก:
- มีธงที่ `state/autonomous.flag` เมื่อธงอยู่ โหมดทำงาน
- `autonomous_stop_hook.py` ทำให้เซสชันไม่หยุดเองจนกว่าจะลบธงหรือถึง `autonomous.max_turns_per_session` (ค่าเริ่มต้น 40)
- `autonomous_guard_hook.py` บล็อกคำสั่งต่อไปนี้ทันที:
  - `git push`
  - `gh pr merge`
  - `gh release`
  - `deploy`
  - `git reset --hard`
  - `git clean` ที่มี `-f`
  - `rm` แบบเรียกซ้ำหรือบังคับ
  - `Remove-Item -Recurse`
  - `del /s`
  - การลบธง `autonomous.flag`
- hook ยังบล็อกการแก้ไข `state/autonomous.flag` และ `.claude/settings*.json` จากเครื่องมือ Write, Edit, MultiEdit

**สิ่งที่ควรรู้:** การบล็อก `git push` เป็นการบล็อกทุกการ push ไม่ใช่เฉพาะ force-push ส่วน force-push ไม่มีการบล็อกเฉพาะเจาะจง

---

## 4. การทดสอบ

### เทสต์ชุดเต็ม
```bash
python -m pytest -q -p no:cacheprovider
```
ผลที่บันทึกล่าสุด (2026-11-18): **1442 passed, 6 skipped** (ดู `STATE.md`)

โฟลเดอร์ `tests/` มีไฟล์ประมาณ 170 รายการ รวมไฟล์เทสต์และไฟล์สนับสนุนบางตัว

### รายการทดสอบที่ควรรู้
| ไฟล์ | ทดสอบอะไร |
|---|---|
| `tests/test_redact.py` | การซ่อน token ใน log |
| `tests/test_loop_helpers.py`, `tests/test_test_gate.py` | ด่าน `require_test_for_bugfix` |
| `tests/test_static_gate.py` | ด่านตรวจแบบกำหนดตายตัว |
| `tests/test_runner_parallel.py` | การทำงานหลายช่อง |
| `tests/test_gui_user_messages_i18n.py` | ข้อความ GUI ภาษาไทยและอังกฤษ |
| `tests/test_login_removed.py` | ยืนยันว่าไม่มีระบบล็อกอินรหัสผ่านใน GUI แล้ว |

### การทดสอบ GUI ด้วยมือ
1. เปิด GUI: `python -m auto_dev_crew.gui --no-browser`
2. ทดสอบ `curl http://127.0.0.1:8765/api/status` ต้องได้ JSON
3. `python scripts/gui_smoke.py` ต้องขึ้น `PASS`
4. `python scripts/gui_e2e.py --repo OWNER/NAME` ใช้ repo ทดสอบ และรันเฉพาะเมื่อช่องว่าง

---

## 5. CI (GitHub Actions)

ไฟล์ `.github/workflows/ci.yml` ทำงานเมื่อ push ไป `main`, เปิด PR และรันด้วยมือ (`workflow_dispatch`) มี 4 งาน:

| งาน | ระบบปฏิบัติการ | ทำอะไร |
|---|---|---|
| `tests` | `windows-latest` | ติดตั้ง requirements และ pytest รัน `python -m pytest -q` |
| `lint` | `ubuntu-latest` | ruff `--select E9,F` ตรวจข้อผิดพลาดซินแท็กซ์และ pyflakes (ไม่บังคับสไตล์) |
| `security` | `ubuntu-latest` | pip-audit ตรวจช่องโหว่ของ dependency และ bandit `-lll` (บล็อกเฉพาะความเสี่ยงระดับ High) |
| `ui` | `windows-latest` | ติดตั้ง Chromium แล้วรันการตรวจ GUI ผ่าน Playwright (`gui_check.run_gui_check`) โดยอ่านอย่างเดียว |

หมายเหตุ:
- CI ไม่ได้รัน `gui_e2e.py` เพราะต้องมี repo ทดสอบและ GUI ที่ทำงานอยู่
- `concurrency` ยกเลิกรันเก่าเฉพาะ PR เท่านั้น บน `main` ทุก merge จะรันจนจบ
- งาน `tests` ตั้งค่า git identity ของ CI ไว้ให้เทสต์ที่ใช้ git

---

## 6. การตรวจก่อน commit ที่แนะนำ

```bash
python -m pytest -q -p no:cacheprovider
python -m ruff check --select E9,F auto_dev_crew scripts tests
```

ถ้าแก้ GUI ให้เพิ่ม `python scripts/gui_smoke.py` ด้วย

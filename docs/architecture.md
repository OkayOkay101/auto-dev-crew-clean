# สถาปัตยกรรมและการไหลของงาน

เอกสารนี้อธิบายว่างานหนึ่งชิ้นไหลผ่านโค้ดอย่างไร ตั้งแต่ issue หรือตัวละครจนถึง merge ตำแหน่งในวงเล็บชี้ไปยังฟังก์ชันจริงในรีโป

---

## 1. ภาพรวมโมดูล

| กลุ่ม | ไฟล์หลัก | หน้าที่ |
|---|---|---|
| แกนหลัก | `runner.py` (~3100 บรรทัด) | คิวงาน, ช่อง, clone, เรียก engine, เทสต์, เปิด PR, merge, รายงาน |
| ผู้ประเมิน | `evaluator.py`, `static_checks.py`, `static_gate.py`, `quality_gates.py` | ด่านตรวจและคะแนน judge |
| การจัดลำดับ | `routing.py`, `triage.py`, `providers.py`, `keys.py` | เลือก engine ตามประวัติ และจัดประเภทงาน |
| ตัวค้นหาปัญหา | `deep_scan.py`, `todo_scan.py`, `feature_gen.py`, `multi_repo.py` | สแกนโค้ดและสร้าง issue |
| ความปลอดภัย | `redact.py`, `guardrails.py`, `gui_patches.py` | ซ่อนความลับ, ตัดผลลัพธ์ยาว, ตรวจ token |
| หน้าเว็บ | `gui.py`, `static/`, `i18n*.py`, `locales/` | GUI และการแปลภาษา |
| สนับสนุน | `context.py`, `context_slicer.py`, `ast_skeleton.py`, `locks.py`, `file_locks.py`, `metrics.py`, `doctor.py` | repo map, ล็อกไฟล์, metrics, ตรวจสุขภาพ |

---

## 2. วงจรของงานหนึ่งชิ้น

```
┌───────────────────────────────────────────────────────────────┐
│ 1. รับงาน: issue (ai-task) หรือ ตัวละคร (persona)            │
│ 2. เลือกช่อง: ช่อง 1 = issue ของผู้ใช้, ช่อง 2–3 = ส่วนที่เหลือ│
│ 3. เตรียม: clone/worktree, setup, ตรวจไฟล์ที่ถูกล็อก        │
│ 4. ลงมือ: coder engine แก้โค้ด → เทสต์ → ซ่อมซ้ำ ≤ max_fix  │
│ 5. ประเมิน: ด่านตรวจ + judge → ปรับปรุงซ้ำ ≤ max_eval_refine  │
│ 6. ถ้าไม่ผ่าน → ai-failed + คอมเมนต์ใน issue, ไม่เปิด PR    │
│ 7. ถ้าผ่าน → push branch, เปิด PR (ป้าย ai-generated)       │
│ 8. ตามโหมด merge → ล็อก merge → rebase → รอ CI → merge      │
│ 9. บันทึก: history.json, usage.jsonl, raw log ใน state/runs  │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. การเลือกงาน

### 3.1 issue (`runner.py` ประมาณบรรทัด 310–325)
รายการ issue ที่เปิดอยู่และมีป้าย `ai-task` จะถูกกรองดังนี้
- ผู้เขียน issue ต้องตรงกับ `owner` ในไฟล์ตั้งค่า (ไม่สนตัวพิมพ์ใหญ่เล็ก)
- ข้าม issue ที่มีป้าย `ai-working`, `ai-failed` หรือ `ai-needs-human`
- เรียงตามหมายเลข issue จากน้อยไปมาก

### 3.2 ช่องและตัวละคร (`slot_worker_loop`, ประมาณบรรทัด 2981)
- ช่อง 1 รับเฉพาะ issue ของผู้ใช้
- ช่อง 2–3 รับตัวละคร หรือช่วย issue ส่วนเกินเมื่อมี issue อย่างน้อย 2 รายการ
- ตัวละครทำงานได้เฉพาะในช่วงเวลาที่ `personas.schedule` อนุญาต และเมื่อ persona นั้นไม่มี PR ค้างรอตรวจ
- ถ้ามี issue ที่เปิดอยู่และติดป้าย `ai-pause` ทั้ง repo runner จะไม่เริ่มงานใหม่ (`paused()`)

### 3.3 ตัวละคร
ตัวละครแต่ละตัวมีโจทย์เป้าหมายเฉพาะในโค้ด (`runner.py` ประมาณบรรทัด 91–103) เช่น bolt ให้มองหาการปรับประสิทธิภาพที่วัดได้ และ sentinel ให้มองหาช่องโหว่ด้านความปลอดภัยจริง

---

## 4. การเตรียมงาน

- ชื่อ branch: `ai/issue-<หมายเลข>-<เวลา>` สำหรับ issue และ `ai/<ชื่อตัวละคร>-<เวลา>` สำหรับตัวละคร (`runner.py` บรรทัด 447 และ 2342)
- ที่ทำงาน: โฟลเดอร์ใต้ `~/.auto-dev-crew/work` และ repo cache ใน `~/.auto-dev-crew/repos`
- venv แยกต่อ repo อยู่ใต้ `~/.auto-dev-crew/venvs`
- ขั้น `setup` จาก config รันก่อนเทสต์
- ไฟล์ที่ถูกล็อกโดยงานอื่นจะถูกตรวจผ่าน `file_locks.py` เพื่อกันสองช่องแก้ไฟล์เดียวกัน

---

## 5. การลงมือแก้โค้ด (`execute`, ประมาณบรรทัด 2331)

1. coder engine ได้รับ prompt จาก `prompts/task.md` (งาน issue) หรือ `prompts/fix_tests.md` (ซ่อมเทสต์) พร้อมกฎร่วม `prompts/_rules.md` และ repo map (ถ้าเปิดไว้) และ Repository Notes
2. เรียก engine ตามลำดับที่ `routing` จัดให้ ถ้า engine ล้มเหลวหรือโควตาหมดจะสลับไปตัวถัดไป (F6)
3. รันคำสั่งเทสต์ของ repo (`repos[].test`)
4. ถ้าเทสต์ไม่ผ่านหรือ coder ไม่ได้แก้อะไร จะให้ซ่อมซ้ำ สูงสุด `max_fix_attempts` รอบ (ค่าในไฟล์ 3, ค่าเริ่มต้นในโค้ด 2)
5. งานแก้บั๊กที่ coder รายงานว่าเสร็จแต่ไม่ได้แก้ไฟล์เทสต์เลย จะได้รอบเพิ่มเพื่อเพิ่มเทสต์ regression (`loop.require_test_for_bugfix`, `loop_helpers.py`)

---

## 6. ด่านตรวจ

ตรวจโดย `_evaluate_guarded` (ประมาณบรรทัด 2487) และ `evaluator.py`

| ลำดับ | ตรวจอะไร | ผลเมื่อไม่ผ่าน |
|---|---|---|
| 0 | diff ว่างเปล่า | หยุดทันที |
| 1 | ตรวจแบบกำหนดตายตัว: ไฟล์ Python ต้อง parse ได้ (`guardrails.check_deterministic_pre_eval`) | หยุด ไม่เรียก judge |
| 2 | static checks (`static_checks.py`) | หยุด ถ้ามีจุดรุนแรง |
| 3 | judge ให้คะแนนตาม rubric: ความตรงกับโจทย์ 0.4, ความปลอดภัยและความสะอาด 0.3, คุณภาพ 0.3 | ถ้าต่ำกว่า `min_pass_score` (0.75) จะให้ปรับปรุงตาม critique |
| 4 | ปรับปรุงซ้ำไม่เกิน `max_eval_refinements` รอบ และหยุดเมื่อคะแนนค้าง (`plateau_stop`) | ถ้ายังไม่ผ่าน → `EVAL_FAILED` |

ถ้าไม่มี engine อื่นพร้อมให้เป็น judge ระบบจะใช้ engine ของ coder เป็น judge และแจ้งในบันทึก (ผลนี้จะถูกบันทึกเป็น `judge_same_as_coder`)

### ด่านตรวจ 1–4 ตามที่ GUI อธิบาย
ฉบับ GUI ใช้คำว่า "ด่าน 1–4" ดังนี้
- **ด่าน 1:** judge ยืนยันว่าบั๊กมีจริงก่อนแก้
- **ด่าน 2:** judge เห็นไฟล์เต็มหลังแก้
- **ด่าน 3:** รอบซ่อมต้องแตะไฟล์ที่ issue ระบุ
- **ด่าน 4:** deep-scan ตรวจซ้ำก่อนสร้าง issue

หมายเหตุ: คำอธิบายนี้มาจากข้อความใน GUI และ README ยังไม่ได้ไล่ตรวจทุกด่านจนถึงระดับบรรทัด ถ้าต้องการความแน่นอน ให้ค้นหาคำว่า `gate` หรือ `ด่าน` ในโค้ด

---

## 7. การเปิด PR

- ถ้าผ่านทุกด่าน ระบบ push branch และเปิด PR ด้วย `create_pr` (`runner.py` บรรทัด 1491)
- PR ได้ป้าย `ai-generated`
- PR body สร้างจาก `pr_body.py`
- งานที่ไม่ผ่านจะถูกติดป้าย `ai-failed` และคอมเมนต์เหตุผลใน issue (ไม่เปิด PR)

---

## 8. การตัดสิน merge

เกิดขึ้นใน `try_merge` (ประมาณบรรทัด 1752) และ `_local_rebase_and_merge` (บรรทัด 1710)

### 8.1 ระดับการ merge
1. ถ้า repo มี `merge_level` ของตัวเอง ใช้ระดับนั้น
2. ไม่เช่นนั้นใช้ `merge_mode` กลาง

| โหมด | พฤติกรรม |
|---|---|
| `review-all` | ไม่ merge เอง คนเป็นผู้ merge |
| `small-only` | merge เองเมื่อ PR มีไม่เกิน `small_pr.max_lines` บรรทัด และไม่แตะ `protected_paths` (ตรวจด้วย `_matches_protected` บรรทัด 1431) |
| `merge-all` | merge เองเมื่อ CI ผ่าน |

### 8.2 ลำดับการ merge
1. จองล็อก merge กลาง (`MERGE_LOCK`) รอได้ตามเวลาที่คำนวณจาก `merge_lock_timeout_minutes` และ `ci.timeout_minutes`
2. rebase บน base branch ถ้า `ci.auto_rebase` เป็น true
3. รอผล CI (`ci_sync.wait_for_required_checks`) จนครบ `ci.timeout_minutes`
4. ถ้าไม่มี CI: ผ่านหรือไม่ผ่านตาม `ci.allow_no_ci`
5. ถ้า CI ล้มเหลว ไม่ merge
6. merge แล้วบันทึกผลลง `history.json`

---

## 9. การบันทึกผลและการเรียนรู้

| ไฟล์ | เก็บอะไร | หมายเหตุ |
|---|---|---|
| `state/history.json` | ผลของแต่ละงาน (สถานะ, engine, คะแนน, merge หรือไม่) | ใช้โดย `routing` และ `metrics` ไม่ commit |
| `state/usage.jsonl` | จำนวนคำขอและ token ต่อ engine ต่อวัน | ใช้แสดงในหน้า **คีย์ AI** |
| `state/runs/` | raw log ของแต่ละรอบ | ตัดให้เหลือจำนวนล่าสุด (`prune_raw_logs`) |
| `state/session_checkpoint.json` | จุดตรวจสอบของเซสชัน | ใช้ตอนรีสตาร์ท |
| `state/active_slots.json` | สถานะช่องที่กำลังทำงาน | GUI อ่านเพื่อแสดงผล |

`routing` ใช้ `history.json` จัดลำดับ engine: engine ที่มี merge rate ต่ำกว่า `routing.demote_below` และมีข้อมูลครบ `min_samples` จะถูกย้ายไปท้าย (ไม่ตัดออก)

---

## 10. Deep-scan

`deep_scan.py` ให้ AI อ่านโค้ดทีละส่วนแล้วรายงานปัญหาพร้อมความรุนแรง ผลที่ผ่านด่าน 4 และความรุนแรงถึง `auto_issue.min_severity` สามารถสร้าง issue ได้ ถ้า `auto_issue.enabled: true`

ผล deep-scan เก็บใน `state/deep_scan/<owner>__<repo>.json` และไฟล์ `.lock` ที่คู่กัน

---

## 11. การแก้ปัญหาที่เกิดระหว่างทาง

| สถานการณ์ | พฤติกรรม |
|---|---|
| engine timeout | พัก engine นั้น `engine_timeout_cooldown_minutes` นาที แล้วสลับไปตัวถัดไป |
| โควตาหมด | สลับไปตัวถัดไปตามลำดับ (F6) |
| judge ไม่พร้อม | ใช้ fallback engine หรือ engine ของ coder (บันทึกไว้) |
| คะแนนค้างระหว่างรอบซ่อม | หยุดรอบซ่อม (`plateau_stop`) ไม่ใช้โควตาซ้ำ |
| ช่องชนกันที่ไฟล์เดียวกัน | ใช้ `file_locks.py` ป้องกัน |
| รีสตาร์ทกลางงาน | บันทึก checkpoint และเริ่มใหม่ด้วยค่าเดิม งานที่ทำค้างจะถูกยกเลิก |

---

## 12. จุดที่ควรรู้ก่อนแก้โค้ด

- `runner.py` เป็นไฟล์ใหญ่และมีฟังก์ชันจำนวนมาก (144 ฟังก์ชันระดับบนสุด) ก่อนแก้ควรอ่านเทสต์ที่เกี่ยวข้องก่อน
- `runner.py` ถูก import โดยโมดูลอื่นหลายตัว การแก้ชื่อฟังก์ชันสาธารณะต้องค้นหาการอ้างอิงทั้งหมด
- ค่า `config.yaml` ที่โหลดระหว่างทำงานอาจถูกอ่านซ้ำ ดังนั้นการแก้ไฟล์กลางงานอาจมีผลไม่สม่ำเสมอ ให้รีสตาร์ทหลังแก้

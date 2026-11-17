# คู่มืออ้างอิง `config.yaml`

ไฟล์ `config.yaml` อยู่ที่รากโปรเจกต์ เป็นแหล่งตั้งค่าหลักของระบบ อ่านโดย `runner.py`, `gui.py` และโมดูลอื่น ๆ

**หลักการอ่านค่า:** ถ้าคีย์ไม่มีในไฟล์ โค้ดจะใช้ค่าเริ่มต้นที่ระบุไว้ในคอลัมน์ "ค่าเริ่มต้นในโค้ด" บางคีย์ค่าในไฟล์ต่างจากค่าเริ่มต้นในโค้ด ระบบใช้ค่าในไฟล์เสมอ

**การแก้ไข:** แก้ด้วยมือได้ หรือผ่านหน้า GUI ที่เขียนค่าลงไฟล์ให้เอง หลังแก้ไฟล์ด้วยมือ ให้รีสตาร์ทเอเจนต์เพื่อให้มีผลแน่นอน (ดู [gui.md](gui.md))

---

## 1. ค่าระดับบนสุด

| คีย์ | ชนิด | ค่าในไฟล์ | ค่าเริ่มต้นในโค้ด | ความหมาย |
|---|---|---|---|---|
| `owner` | สตริง | `example-owner` | (ไม่มี) | ชื่อบัญชี GitHub ของเจ้าของ งานจาก issue จะถูกหยิบเฉพาะถ้าผู้เขียนตรงกับค่านี้ (ไม่สนตัวพิมพ์ใหญ่เล็ก) ค่าที่ไม่ตั้งทำให้เอเจนต์ไม่หยิบงานใด |
| `merge_mode` | สตริง | `review-all` | `review-all` | โหมดการ merge กลางของระบบ ค่าที่ใช้ได้: `review-all`, `small-only`, `merge-all` รายละเอียดที่ [architecture.md](architecture.md#8-การตัดสิน-merge) |
| `max_fix_attempts` | จำนวนเต็ม | `3` | `2` | จำนวนรอบแก้ซ้ำสูงสุดเมื่อเทสต์ไม่ผ่านหรือ coder ไม่ได้แก้อะไร ค่าในไฟล์ (3) มีผลจริง |
| `engine_timeout_cooldown_minutes` | จำนวน | `20` | `20` | เมื่อ engine เกิด timeout จะพักการใช้ engine นั้นเป็นเวลาเท่านี้ก่อนลองอีก |
| `ui_language` | สตริง | (ไม่มีในไฟล์ปัจจุบัน) | `th` | ภาษาของ UI และข้อความ backend ค่าที่ใช้ได้: `th` หรือ `en` ค่าอื่นหรืออ่านไม่ได้ให้ใช้ `th` ตั้งได้จากหน้า **ตั้งค่า** หรือ `POST /api/settings/language` |

---

## 2. `parallel` การทำงานพร้อมกันของช่อง (slot)

| คีย์ | ค่าในไฟล์ | ค่าเริ่มต้นในโค้ด | ความหมาย |
|---|---|---|---|
| `enabled` | `true` | — | เปิดการทำงานแบบหลายช่อง |
| `slots` | `3` | — | จำนวนช่องทำงานพร้อมกัน |
| `poll_interval_seconds` | `120` | `120` | ความถี่ในการตรวจคิวงานใหม่ (วินาที) |
| `merge_lock_timeout_minutes` | `25` | `25` | เวลารอสูงสุดในการจอง Central Merge Lock (ระบบใช้ค่ามากกว่าระหว่างค่านี้กับ `ci.timeout_minutes + 5`) ช่องที่จองไม่ได้ภายในเวลานี้จะไม่ merge ในรอบนั้น |
| `assignments` | `slot_2`, `slot_3` (persona และ repo ว่าง) | — | กำหนดตัวละครหรือ repo ให้แต่ละช่อง ค่านี้ GUI เขียนให้เมื่อกดกำหนดในหน้า **ภาพรวม** |
| `active_slot` | `2` | — | ค่าที่ GUI ใช้บันทึกช่องที่กำลังเลือกไว้ในหน้าควบคุม |

ช่อง 1 สงวนไว้สำหรับ issue ที่ผู้ใช้สั่ง ช่อง 2–3 ใช้กับตัวละครหรืองาน issue ส่วนเกิน

---

## 3. `evaluation` ด่านประเมินคุณภาพ (judge)

| คีย์ | ค่าในไฟล์ | ค่าเริ่มต้นในโค้ด | ความหมาย |
|---|---|---|---|
| `enabled` | `true` | — | เปิดการประเมินก่อนเปิด PR |
| `engine` | `auto` | — | engine ที่ใช้เป็น judge `auto` = เลือกจากคีย์ที่มีบทบาท judge |
| `timeout_minutes` | `5` | `3` | เวลาสูงสุดของการประเมินหนึ่งครั้ง ค่าในไฟล์ (5) มีผลจริง ถ้า engine ตัวนั้นตั้ง timeout ของตัวเองสั้นกว่า จะใช้ค่าที่สั้นกว่า |
| `rubric.alignment_weight` | `0.4` | `0.4` | น้ำหนักความตรงกับโจทย์ |
| `rubric.safety_cleanliness_weight` | `0.3` | `0.3` | น้ำหนักความปลอดภัยและความสะอาดของโค้ด |
| `rubric.quality_weight` | `0.3` | `0.3` | น้ำหนักคุณภาพโค้ด |
| `min_pass_score` | `0.75` | `0.75` | คะแนนรวมขั้นต่ำ (0–1) ที่ถือว่าผ่าน |
| `max_eval_refinements` | `2` | `2` | จำนวนรอบที่ให้ coder ปรับปรุงตาม critique ของ judge ก่อนยอมแพ้ |
| `convergence_check` | `true` | — | คีย์นี้อยู่ในไฟล์ แต่โค้ดที่ตรวจไม่ได้อ่านคีย์นี้โดยตรง ใช้ `plateau_stop` แทน (ดูด้านล่าง) |
| `plateau_stop` | (ไม่มีในไฟล์) | `true` | เมื่อคะแนนของ judge ค้างหรือไม่ดีขึ้นระหว่างรอบซ่อม จะหยุดรอบซ่อมและไม่ใช้โควตาซ้ำ ใช้ `check_convergence` ใน `evaluator.py` |

น้ำหนักทั้งสามรวมกันได้ 1.0 ตามที่ตั้งไว้

---

## 4. `triage` การจัดประเภท issue

| คีย์ | ค่าในไฟล์ | ความหมาย |
|---|---|---|
| `enabled` | `true` | เปิดการจัดประเภท issue |
| `use_llm_fallback` | `false` | เมื่อจัดประเภทด้วยป้ายไม่ได้ ให้ใช้ LLM ช่วยตัดสินหรือไม่ ค่าปิดหมายถึงใช้เฉพาะกฎป้าย |
| `fast_labels` | `quick-fix, typo, docs, documentation, minor, small, lint` | ป้ายที่ถือว่าเป็นงานเล็ก เร็ว |
| `heavy_labels` | `feature, architecture, refactor, breaking, complex, security` | ป้ายที่ถือว่าเป็นงานใหญ่ (เส้นทาง `heavy`) งาน persona `sentinel` ถูกจัดเป็น heavy เสมอ |

ผลการจัดประเภทคือเส้นทาง `fast` หรือ `heavy` และ `routing` ใช้เส้นทางนี้แยกประวัติการ merge ของแต่ละ engine (งานที่ไม่ตรงป้ายใดจะใช้ heuristic หรือการตัดสินตามชนิดงาน)

---

## 5. `ci` การตรวจ CI ก่อน merge

| คีย์ | ค่าในไฟล์ | ค่าเริ่มต้นในโค้ด | ความหมาย |
|---|---|---|---|
| `enabled` | `true` | — | เปิดการรอผล CI |
| `required_checks` | `[]` | — | รายชื่อ check ที่ต้องผ่านทั้งหมด ถ้าว่าง ใช้ทุก check ที่ CI รัน |
| `timeout_minutes` | `15` | — | เวลาสูงสุดที่รอผล CI |
| `poll_interval_seconds` | `15` | `15` | ความถี่ในการถามผล CI (วินาที) |
| `auto_rebase` | `true` | `true` | ถ้า PR ตามหลัง base branch ให้ rebase อัตโนมัติก่อน merge |
| `allow_no_ci` | `true` | `true` | `true` = repo ที่ไม่มี CI ยัง merge ได้หลังเทสต์ในเครื่องผ่าน `false` = ต้องมี CI และผ่านเท่านั้น |
| `auto_bootstrap_ci` | `false` | — | ถ้า repo ยังไม่มี CI ให้สร้างไฟล์ workflow ให้อัตโนมัติหรือไม่ ปิดไว้เพื่อไม่ให้แก้ repo โดยไม่ตั้งใจ |

---

## 6. `engines` รายการ engine ที่ใช้เขียนโค้ด/ประเมิน

`engines` เป็นลิสต์ ลำดับในไฟล์คือลำดับสำรอง (failover) ตัวบนสุดถูกลองก่อน ยกเว้นเมื่อ `routing.enabled` จัดลำดับใหม่ตามผลจริง

| ฟิลด์ | ความหมาย |
|---|---|
| `name` | ชื่อ engine ที่ใช้ในระบบ ต้องไม่ซ้ำ |
| `provider` | ชื่อผู้ให้บริการที่แสดงใน GUI |
| `command` | โปรแกรมที่เรียก เช่น `agy` หรือ `opencode` |
| `path` | ตำแหน่งไฟล์โปรแกรม รองรับ `~` |
| `model` | ชื่อโมเดล ถ้าใช้ OpenCode ใช้รูป `provider/model` |
| `auth_provider` | ชื่อที่ระบบใช้ผูกกับคีย์การยืนยันตัวตนของ OpenCode (ระบบค้นหาคีย์ชื่อ `opencode-<auth_provider>` ก่อน) |
| `provider_id` | รหัสผู้ให้บริการในทะเบียน (ไม่บังคับ) |
| `timeout_minutes` | เวลาสูงสุดต่อการเรียกหนึ่งครั้ง |
| `trains_on_data` | บันทึกข้อมูลว่าผู้ให้บริการอาจนำข้อมูลไปเทรนโมเดลหรือไม่ ใช้เป็นข้อมูลประกอบการตัดสินใจ ไม่ได้บังคับพฤติกรรม |
| `enabled` | `true` = ใช้ได้ `false` = ข้าม |
| `roles` | บทบาท (`coder`, `judge`, `scan`) ที่ engine นี้รับผิดชอบ |
| `api_keys` | ชื่อตัวแปรคีย์ใน `.env` เช่น `${POLLINATIONS_API_KEY_1}` ค่าจริงไม่อยู่ในไฟล์นี้ |

engine ที่เปิดใช้อยู่ในไฟล์ตอนนี้: `opencode-pollinations` (เท่านั้น) ตัวอื่นตั้งเป็น `enabled: false` ไว้

รายละเอียดคีย์และบทบาทอยู่ที่ [providers-and-keys.md](providers-and-keys.md)

---

## 7. `labels` ชื่อป้ายใน GitHub

| คีย์ | ค่า | ความหมาย |
|---|---|---|
| `task` | `ai-task` | ป้ายงานที่ให้เอเจนต์หยิบ |
| `pause` | `ai-pause` | ถ้ามี issue ที่เปิดอยู่ติดป้ายนี้ อีกบางรายการ runner จะหยุดทำงานใหม่ |
| `working` | `ai-working` | ติดระหว่างที่เอเจนต์กำลังทำงานนั้น |
| `failed` | `ai-failed` | ติดเมื่อทำงานไม่สำเร็จ |
| `pr` | `ai-generated` | ป้ายที่ติดบน PR ที่เอเจนต์เปิด |

วงจรชีวิตของป้ายอยู่ที่ [github-workflow.md](github-workflow.md)

---

## 8. `small_pr` เกณฑ์ PR เล็กสำหรับโหมด `small-only`

| คีย์ | ค่า | ความหมาย |
|---|---|---|
| `max_lines` | `50` | จำนวนบรรทัดที่เปลี่ยนสูงสุดของ PR ที่ถือว่าเล็ก |
| `protected_paths` | `.github/`, `requirements`, `.jules/quality`, `config` | PR ที่แตะไฟล์ในกลุ่มนี้ไม่ถือว่าเล็ก ต้องให้คนตรวจ การจับคู่ต้องตรงกับขอบเขตของ path: `config` ตรงกับ `config.yaml` และ `config/x` แต่ไม่ตรงกับ `myconfig.py` |

---

## 9. `personas` ตัวละครที่หาจุดปรับปรุงเอง

| คีย์ | ค่า | ความหมาย |
|---|---|---|
| `enabled` | `bolt`, `sentinel`, `palette`, `quality` | ตัวละครที่เปิดใช้ |
| `skills` | ต่อตัวละคร เช่น `bolt: [memory-leak-debugging, caveman-persona]` | สกิลที่ฉีดเข้า prompt ของตัวละครนั้น |
| `schedule` | (ไม่มีในไฟล์) | ช่วงเวลาที่ตัวละครทำงานได้ ค่าที่อ่านได้: `mode` เป็น `always` (ค่าเริ่มต้น) หรือ `nightly`, `start_hour` (ค่าเริ่มต้น 0), `end_hour` (ค่าเริ่มต้น 6) |

ตัวละครทำงานเฉพาะเมื่อคิว issue ว่าง และช่องที่กำหนดให้ตัวละครนั้นว่าง

---

## 10. `repos` รายการ repo เป้าหมาย

แต่ละรายการในลิสต์มีคีย์ดังนี้

| คีย์ | ความหมาย |
|---|---|
| `name` | `owner/name` ของ repo |
| `base` | branch หลักสำหรับเปิด PR (ค่าเริ่มต้นในโค้ดมักเป็น `main`) |
| `setup` | ลิสต์คำสั่งที่รันก่อนเทสต์ เช่น ติดตั้ง dependency |
| `test` | ลิสต์คำสั่งเทสต์ของ repo |
| `scanners` | ชื่อตัวละคร → ลิสต์คำสั่งสแกนที่รันให้ตัวละครนั้นใน repo นี้ |
| `ci` | ค่า override ของ `ci` ระดับ repo เช่น `auto_bootstrap_ci` |
| `enabled` | `false` = ข้าม repo นี้ |
| `merge_level` | (ไม่มีในไฟล์) ระดับ merge ต่อ repo ตั้งได้จากแผนฟีเจอร์ใน GUI: 1 = คนรีวิว, 2 = merge เองเมื่อ CI ผ่านและไม่มีไฟล์เสี่ยง, 3 = merge เองเมื่อ CI ผ่าน (ดู [architecture](architecture.md#8-การตัดสิน-merge)) ถ้าไม่ตั้งใช้ `merge_mode` กลาง |

repo ที่มีในไฟล์ตอนนี้: `OkayOkay101/cyberpunk-pomodoro` (base `main`, test `node test-runner.js`)

---

## 11. `autonomous` และ `todo_scan` และ `auto_issue`

| ส่วน | คีย์ | ค่าในไฟล์ | ความหมาย |
|---|---|---|---|
| `autonomous` | `max_turns_per_session` | `40` | จำนวนรอบสูงสุดของโหมด autonomous ต่อหนึ่งเซสชัน (ใช้โดย `scripts/autonomous_common.py`) |
| `todo_scan` | `max_issues_per_run` | `5` | จำนวน issue สูงสุดที่สร้างจากแท็ก `[AI-TODO]` ต่อการรันหนึ่งครั้ง |
| `todo_scan` | `schedule_minutes` | `0` | สแกนซ้ำทุกกี่นาที `0` หรือไม่ตั้ง = ไม่สแกนตามเวลา |
| `auto_issue` | `enabled` | `false` | สร้าง issue จากผล deep-scan อัตโนมัติหรือไม่ |
| `auto_issue` | `trigger` | `after_scan` | เวลาที่สร้าง ค่าที่รองรับในโค้ด: `after_scan` |
| `auto_issue` | `min_severity` | `low` | ความรุนแรงขั้นต่ำที่จะสร้าง issue |

---

## 12. `context` และ `loop` และ `routing` (ไม่มีในไฟล์ ใช้ค่าเริ่มต้นในโค้ด)

| คีย์ | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `context.repo_map` | `true` | แนบโครงสร้างโค้ด Python (ชื่อฟังก์ชัน คลาส และ signature) ลงใน prompt |
| `context.repo_map_chars` | `6000` | จำนวนตัวอักษรสูงสุดของ repo map |
| `loop.require_test_for_bugfix` | `true` | งานแก้บั๊กที่ coder รายงานว่าเสร็จแต่ไม่ได้แก้ไฟล์เทสต์เลย จะให้รอบเพิ่มเพื่อเพิ่มเทสต์ regression |
| `routing.enabled` | `true` | จัดลำดับ engine ตามผล merge ในประวัติ (`state/history.json`) |
| `routing.min_samples` | `5` | จำนวนผลสรุปขั้นต่ำต่อ engine ก่อนนำมาใช้จัดลำดับ |
| `routing.demote_below` | `0.2` | engine ที่ merge rate ต่ำกว่าค่านี้ (และมีข้อมูลครบ) ถูกย้ายไปท้ายสุด ไม่มีการตัด engine ออก |

ไฟล์ `AGENTS.md` หรือ `CLAUDE.md` (หรือ `.github/copilot-instructions.md`) ในรีโปเป้าหมายจะถูกแนบเป็น "Repository Notes" อัตโนมัติ สูงสุด 4000 ตัวอักษร

---

## 13. ตัวอย่างการตั้งค่าที่พบบ่อย

**เริ่มอย่างระมัดระวัง (ทุก PR ให้คนตรวจ):**
```yaml
merge_mode: review-all
```

**ให้ merge เองเฉพาะ PR เล็ก:**
```yaml
merge_mode: small-only
small_pr:
  max_lines: 50
```

**บังคับให้ทุก repo ต้องมี CI ก่อน merge:**
```yaml
ci:
  allow_no_ci: false
```

**ปิดการแนบโครงสร้างโค้ดเพื่อประหยัด token:**
```yaml
context:
  repo_map: false
```

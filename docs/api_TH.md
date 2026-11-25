# อ้างอิง API ของ GUI

GUI เปิด HTTP API ที่ `http://127.0.0.1:<port>` สำหรับหน้าเว็บ และใช้ได้กับสคริปต์ในเครื่องเดียวกัน

เอกสารนี้ระบุ **ชื่อ path และกลุ่มการใช้งาน** เท่านั้น ยังไม่ได้ระบุ schema ของ request/response ทุกตัว ให้อ่านโค้ดที่ฟังก์ชันที่ระบุไว้เพื่อดูรายละเอียด

---

## 1. กฎทั่วไป

| เรื่อง | รายละเอียด |
|---|---|
| ที่อยู่ | ผูกกับ `127.0.0.1` เท่านั้น |
| รูปแบบข้อมูล | JSON สำหรับ body และการตอบกลับ |
| ขนาด body | สูงสุด 1 MB (เกินได้ `413`) |
| Content-Length | ต้องถูกต้อง มิฉะนั้นได้ `400` |
| token | คำสั่ง POST ต้องส่ง `X-Token` พร้อมค่าที่ฝังในหน้าเว็บ มิฉะนั้นถูกปฏิเสธ |
| GET ที่ต้องมี token | `/api/repo/file-content`, `/api/byop/status`, `/api/byop/pool` |
| รหัสตอบกลับที่พบ | `200` สำเร็จ, `400` ข้อมูลไม่ถูกต้อง, `413` ข้อมูลใหญ่เกิน |
| ภาษา | ข้อความ error ใช้ภาษาตาม `ui_language` |

ถ้า token ผิดหรือไม่ส่ง ระบบจะปฏิเสธคำขอ (ตรวจใน `gui_patches.verify_request_security`)

---

## 2. GET (อ่านข้อมูล)

### หน้าเว็บ
| path | ความหมาย |
|---|---|
| `/` | หน้าควบคุมหลัก |
| `/static/*` | ไฟล์ static (HTML, JS, CSS) |

### สถานะและการตรวจ
| path | ความหมาย |
|---|---|
| `/api/status` | สถานะเอเจนต์ ช่อง repo และอื่น ๆ (ตัวที่ใช้ `gui_watchdog.py` ตรวจว่า server ยังตอบ) |
| `/api/doctor` | ตรวจสุขภาพระบบ |
| `/api/metrics` | ตัวชี้วัดจาก `history.json` |
| `/api/log` | log ของ runner |
| `/api/i18n` | ข้อความแปลสำหรับหน้าเว็บ |

### คีย์และ engine
| path | ความหมาย |
|---|---|
| `/api/keys` | รายการคีย์และสถานะ |
| `/api/key-roles` | การจับคู่บทบาทของคีย์ |
| `/api/engines` | รายการ engine |
| `/api/engine` | ข้อมูล engine เดี่ยว |
| `/api/models` | รายการโมเดล |
| `/api/favorites` | คีย์ที่ปักหมุด |

### BYOP (การนำคีย์ของตัวเองมาใช้ผ่าน OAuth)
| path | ความหมาย |
|---|---|
| `/api/byop/callback` | รับ callback ของ OAuth |
| `/api/byop/status` | สถานะการเชื่อมต่อ (ต้องมี token) |
| `/api/byop/pool` | พูลคีย์ (ต้องมี token) |

### GitHub
ไม่มี endpoint ของ GitHub เหลือแล้ว (`/api/github/*` ถูกลบเมื่อ 2026-11-18)

### repo และงาน
| path | ความหมาย |
|---|---|
| `/api/repos/scan` | สแกนรายการ repo |
| `/api/repo/workspace` | ที่ทำงานของ repo |
| `/api/repo/file-content` | เนื้อหาไฟล์ใน repo (ต้องมี token) |
| `/api/diff` | diff ของงาน |
| `/api/slots/assignments` | การกำหนดช่องให้ persona หรือ repo |
| `/api/file-locks` | ไฟล์ที่ถูกล็อกโดยงานต่าง ๆ |
| `/api/feature-gen` | แผนฟีเจอร์ |
| `/api/deep-scan` | ผล deep-scan |
| `/api/deep-scan/engines` | engine ที่ใช้ deep-scan |
| `/api/deep-scan/auto-issue` | การตั้งค่าการสร้าง issue อัตโนมัติ |

---

## 3. POST (เปลี่ยนแปลงข้อมูลหรือสั่งงาน)

ทุก POST ต้องมี `X-Token` ตารางนี้จัดตามกลุ่มการใช้งาน ระบบเรียกผ่านตาราง `ROUTES` ใน `gui.py` (ประมาณบรรทัด 1626)

### การทำงาน
| path | ความหมาย |
|---|---|
| `/api/run` | เริ่มงาน (ทำ 1 งาน หรือต่อเนื่อง) |
| `/api/stop` | หยุดงานที่กำลังทำ (ถามยืนยันในหน้า) |
| `/api/restart` | รีสตาร์ทเอเจนต์ |
| `/api/pause` | หยุดชั่วคราว |
| `/api/graceful-drain` | ให้งานปัจจุบันจบก่อนแล้วหยุด |
| `/api/task` | สั่งงานใหม่ |
| `/api/wake-personas` | ปลุกตัวละครให้เริ่มงาน |
| `/api/merge-mode` | เปลี่ยนโหมด merge |
| `/api/slots/assign` | กำหนด persona หรือ repo ให้ช่อง |
| `/api/parallel/active-slot` | ตั้งช่องที่เลือกไว้ |

### Repo
| path | ความหมาย |
|---|---|
| `/api/repos/add` | เพิ่ม repo |
| `/api/repos/remove` | เอา repo ออกจาก config |
| `/api/repos/delete` | เอา repo ออกจากระบบ AI (ไม่ลบโค้ดบน GitHub; หน้าเว็บถามยืนยันก่อน) |
| `/api/repos/toggle` | เปิดหรือปิด repo |
| `/api/repos/scan` | สแกน repo |
| `/api/repos/bootstrap-ci` | ติดตั้ง CI ให้ repo |
| `/api/repos/bootstrap-ci-plan` | แสดงแผนการติดตั้ง CI ก่อนทำจริง |
| `/api/repo/sync` | ซิงก์ repo |
| `/api/repo/run-command` | รันคำสั่งใน repo |
| `/api/repo/dispatch-task` | ส่งงานไปยัง repo |
| `/api/revert/plan` | วางแผน revert PR |
| `/api/ci/toggle` | เปิดหรือปิดการตรวจ CI |
| `/api/ci/bootstrap-toggle` | เปิดหรือปิดการติดตั้ง CI อัตโนมัติ |
| `/api/evaluation/toggle` | เปิดหรือปิด judge |

### คีย์และ engine
| path | ความหมาย |
|---|---|
| `/api/keys` | เพิ่มหรือแก้ไขคีย์ |
| `/api/keys/ping` | ทดสอบคีย์ |
| `/api/key/delete` | ลบคีย์ |
| `/api/key/reset` | รีเซ็ตสถานะคีย์ |
| `/api/key/favorite` | ปักหมุดคีย์ |
| `/api/key/roles` | กำหนดบทบาทของคีย์ |
| `/api/provider/add` | เพิ่มผู้ให้บริการ (ดู [providers-and-keys.md](providers-and-keys_TH.md)) |
| `/api/engine/create` | เพิ่ม engine |
| `/api/engine/update` | แก้ไข engine |
| `/api/engine/delete` | ลบ engine |
| `/api/engine/reorder` | จัดลำดับ failover |
| `/api/engine-model` | เปลี่ยนโมเดลของ engine |
| `/api/models` | จัดการรายการโมเดล |

### BYOP
| path | ความหมาย |
|---|---|
| `/api/byop/start` | เริ่มการยืนยันตัวตน (ระบบสร้าง redirect URI เองจากพอร์ตของเซิร์ฟเวอร์ ไม่รับจาก client) |
| `/api/byop/callback` | รับ callback (ดู GET) |
| `/api/byop/status` | สถานะ (ดู GET) |
| `/api/byop/pool` | พูลคีย์ (ดู GET) |
| `/api/byop/keys/select` | เลือกคีย์ |
| `/api/byop/keys/scan` | สแกนคีย์ |
| `/api/byop/keys/remove` | ลบคีย์ |
| `/api/byop/models/add` | เพิ่มโมเดล |
| `/api/byop/models/remove` | ลบโมเดล |
| `/api/byop/models/promote` | เลื่อนโมเดล |
| `/api/byop/models/roles` | กำหนดบทบาทโมเดล |
| `/api/byop/models/catalog` | ดูแคตตาล็อกโมเดล |
| `/api/byop/models/test` | ทดสอบโมเดล |
| `/api/byop/disconnect` | ยกเลิกการเชื่อมต่อ |

### งานสแกนและแผนฟีเจอร์
| path | ความหมาย |
|---|---|
| `/api/deep-scan` | เริ่ม deep-scan |
| `/api/deep-scan/file` | สแกนไฟล์เดียว |
| `/api/deep-scan/dismiss` | ปิดผลที่ไม่ต้องการ |
| `/api/deep-scan/auto-issue` | ตั้งค่าการสร้าง issue อัตโนมัติ |
| `/api/todo-scan` | สแกน `[AI-TODO]` |
| `/api/feature-gen/propose` | ให้ AI เสนอแผนฟีเจอร์ |
| `/api/feature-gen/approve` | อนุมัติแผน (สร้าง `ai-task`) |
| `/api/feature-gen/settings` | ตั้งค่าแผน (รวม `merge_level`) |
| `/api/context-slicer/preview` | ดูตัวอย่างการตัดบริบทที่จะส่งให้ AI |
| `/api/mcp/preview` | ดูตัวอย่างข้อมูลของ MCP |
| `/api/playground/reset` | รีเซ็ต playground |

### GitHub
ไม่มี endpoint ของ GitHub เหลือแล้ว (`/api/github/*` ถูกลบเมื่อ 2026-11-18)

### ระบบ
| path | ความหมาย |
|---|---|
| `/api/settings/language` | ตั้งภาษา UI เป็น `th` หรือ `en` (เขียนลง `ui_language` ใน `config.yaml`) |
| `/api/server/shutdown` | ปิดเซิร์ฟเวอร์ |

---

## 4. ตัวอย่างการเรียกด้วย curl

ดึง token ต้องอ่านจากหน้าเว็บหรือโค้ดที่ฝัง token เท่านั้น ห้ามเขียนค่า token ลงในเอกสาร

```bash
# อ่านสถานะ (GET ไม่ต้องมี token)
curl http://127.0.0.1:8765/api/status

# สั่งหยุด (POST ต้องมี X-Token)
curl -X POST http://127.0.0.1:8765/api/stop -H "X-Token: <ค่าจากหน้าเว็บ>" -H "Content-Type: application/json" -d "{}"
```

---

## 5. ข้อควรระวัง

- endpoint ที่สั่งงานจริงอาจใช้โควตาหรือเปลี่ยน GitHub ได้ ให้ใช้ `--dry-run` หรือหน้าจอ GUI เมื่อยังไม่แน่ใจ
- การลบคีย์ไม่มีการกู้คืน `/api/repos/delete` เอา repo ออกจากระบบ AI เท่านั้น ไม่ลบโค้ดบน GitHub
- ห้ามเปิดเซิร์ฟเวอร์ให้เครือข่ายภายนอกโดยไม่มีการป้องกันเพิ่ม

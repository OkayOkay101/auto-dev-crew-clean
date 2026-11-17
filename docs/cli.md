# คู่มือคำสั่ง (CLI)

ระบบมีสองจุดเข้าใช้งานจาก terminal:

1. **runner** `python -m auto_dev_crew` (ตัวทำงานหลัก อ่านคิวและเปิด PR)
2. **GUI** `python -m auto_dev_crew.gui` (หน้าเว็บควบคุม ดู [gui.md](gui.md))

และมีเครื่องมือเสริม `python -m auto_dev_crew.mcp_server` และ `scripts/` (ดู [tools-and-scripts.md](tools-and-scripts.md))

ทุกคำสั่งรันจากรากโปรเจกต์ เพราะ `config.yaml` และ `.env` อ้างจากตำแหน่งนั้น

---

## 1. runner: `python -m auto_dev_crew`

ฟังก์ชัน `main()` อยู่ที่ `auto_dev_crew/runner.py` (บรรทัด 3094 ขึ้นไป)

| ตัวเลือก | ค่า | ความหมาย |
|---|---|---|
| `--config <path>` | ค่าเริ่มต้น `config.yaml` ในรากโปรเจกต์ | ใช้ไฟล์ตั้งค่าอื่น |
| `--repo <owner/name>` | — | ทำงานเฉพาะ repo นี้ |
| `--dry-run` | ปิดอยู่ | ทำงานในเครื่องอย่างเดียว ไม่ push ไม่เปิด PR ไม่คอมเมนต์ |
| `--loop` | ปิดอยู่ | ทำงานต่อเนื่องจนไม่มีงาน โควตาหมด หรือมี PR ค้างตามเงื่อนไข |
| `--persona <ชื่อ>` | — | บังคับใช้ตัวละครนี้ ข้ามคิว issue (`bolt`, `sentinel`, `palette`, `quality`) |
| `--slot <1–3>` | — | รันเฉพาะช่องนี้ |
| `--engine <ชื่อ>` | — | แทนค่า `engine.command` ใน config (เช่น `agy`, `opencode`, `gemini`) |
| `--model <ชื่อ>` | — | แทนค่า `engine.model` ใน config (ถ้าใช้ OpenCode ให้ใช้รูป `provider/model`) |

ตัวอย่าง:

```bash
# ทดลองในเครื่อง ไม่แตะ GitHub
python -m auto_dev_crew --dry-run

# ทดลองตัวละคร bolt อย่างเดียว
python -m auto_dev_crew --dry-run --persona bolt

# ทำ 1 งาน แล้วเปิด PR ตามโหมด merge
python -m auto_dev_crew

# ทำต่อเนื่อง
python -m auto_dev_crew --loop

# เฉพาะ repo เดียว
python -m auto_dev_crew --repo OkayOkay101/cyberpunk-pomodoro --dry-run
```

### ลำดับที่ควรใช้ครั้งแรก
1. `--dry-run` เพื่อดูว่าเลือกงานอะไร และเรียก engine ได้หรือไม่
2. `--dry-run --persona <ชื่อ>` เพื่อดูผลของตัวละครหนึ่งตัว
3. รันจริงแบบ `python -m auto_dev_crew` (ทำ 1 งาน) และดู PR ก่อนเปิด `--loop`

### สิ่งที่ `--dry-run` ไม่ได้ทำ
- ไม่ push branch
- ไม่เปิด PR และไม่ merge
- ไม่คอมเมนต์หรือเปลี่ยนป้ายใน issue
- ยังเรียก engine จริง ซึ่งอาจใช้โควตา

---

## 2. GUI: `python -m auto_dev_crew.gui`

| ตัวเลือก | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `--port <n>` | `8765` | พอร์ตที่ฟัง (ผูกกับ `127.0.0.1` เท่านั้น) |
| `--no-browser` | ปิด | ไม่เปิดเบราว์เซอร์อัตโนมัติ |
| `--auto` | ปิด | เปิดแล้วเริ่ม runner `--loop` ทันที และเริ่มใหม่เองเมื่อ runner จบ |
| `--config <path>` | `config.yaml` | ไฟล์ตั้งค่าที่ GUI อ่านและแก้ |
| `--keep-slots` | ปิด | ไม่ล้างสถานะช่องตอนเริ่ม ใช้เมื่อ runner เปิด GUI เองเพื่อตรวจ เพราะ runner อื่นอาจยังทำงานอยู่ |

ตัวอย่าง:

```bash
python -m auto_dev_crew.gui                    # เปิดหน้าควบคุมอย่างเดียว
python -m auto_dev_crew.gui --auto             # เปิดและเริ่มเอเจนต์ต่อเนื่องทันที
python -m auto_dev_crew.gui --no-browser --port 8766
```

---

## 3. `--scan-todos` (สแกนแท็ก `[AI-TODO]` แบบอ่านอย่างเดียว)

```bash
python -m auto_dev_crew --scan-todos OkayOkay101/cyberpunk-pomodoro
```

พิมพ์รายการ `[AI-TODO]` ที่พบในรูปแบบ `path:line ข้อความ` แล้วจบ ไม่สร้าง issue (`create=False`)

การสร้าง issue จริงทำได้จาก GUI (หน้า **สตูดิโอ**) หรือเปิดการสแกนตามเวลาด้วย `todo_scan.schedule_minutes` ดู [configuration.md](configuration.md)

---

## 4. MCP server: `python -m auto_dev_crew.mcp_server`

| ตัวเลือก | ค่า | ความหมาย |
|---|---|---|
| `--transport` | `stdio` (เท่านั้น) | ใช้ JSON-RPC 2.0 ผ่าน stdin/stdout |
| `--config <path>` | `config.yaml` | ไฟล์ตั้งค่าทางเลือก |

เซิร์ฟเวอร์นี้เปิด tool แบบอ่านอย่างเดียวสำหรับ MCP client เช่น สถานะ daemon, สถานะช่องทำงาน, `merge_mode` และสุขภาพของ engine (F6) ตัวอย่างหนึ่งคือสรุป PR ที่ merge แล้วข้ามคืน

---

## 5. ตัวแปรสภาพแวดล้อมและตำแหน่งไฟล์

| รายการ | ค่า |
|---|---|
| `.env` | คีย์ API ทั้งหมด อ่านโดย `runner.load_dotenv()` |
| `config.yaml` | ค่าตั้งค่า |
| `state/` | สถานะ ประวัติ lock และ log (ไม่ commit) |
| `~/.auto-dev-crew/` | โฟลเดอร์ข้อมูลภายนอก: งานชั่วคราว repo cache และ venv |

ตำแหน่ง `~/.auto-dev-crew/` มาจาก `auto_dev_crew/data_home.py` ถ้ามี `~/.ai-optimizer/` เก่าและยังไม่มีโฟลเดอร์ใหม่ ระบบจะย้ายให้ครั้งเดียว

---

## 6. รหัสออกและการหยุด

- หยุด runner ที่รันแบบ `--loop` ด้วย `Ctrl+C` หรือจาก GUI (ปุ่มหยุด) หรือเปิด issue ที่มีป้าย `ai-pause`
- ระหว่างรีสตาร์ทจาก GUI งานที่กำลังทำจะถูกยกเลิก และรอบใหม่เริ่มด้วยค่าตั้งค่าเดิม PR ที่เปิดไปแล้วไม่ถูกปิด

ยังไม่ได้ยืนยันรายการรหัสออก (exit code) ของแต่ละกรณี

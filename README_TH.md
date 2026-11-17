# Auto Dev Crew 🤖

**Auto Dev Crew คือเอเจนต์เขียนโค้ด AI ที่รันในเครื่องของคุณ** รับงานจาก GitHub issue แล้วเปิด pull request ให้ เมื่อคิวงานว่าง ตัวละครทั้งสี่ (⚡🛡️🎨🧪) จะสแกนโค้ดเองและหาจุดที่ควรปรับปรุง

**ภาษา:** [English](README.md) · ภาษาไทย (ไฟล์นี้)

ใช้ **Antigravity CLI (`agy`)** กับบัญชี Google AI Pro เป็นเอนจินหลัก และรองรับ **Multi-Engine Failover (F6)** คือเมื่อโควตาหมด ระบบจะสลับไปยังเอนจินถัดไปตามลำดับสำรอง (เช่น OpenCode, NVIDIA Build, Pollinations.ai หรือ Mistral) รายการเอนจินอยู่ใน `config.example.yaml`

> **สถานะ:** โครงการทดลอง เป็น repository แบบส่วนตัว

- ข้อกำหนดทั้งหมด: [REQUIREMENTS.md](REQUIREMENTS.md) (ร่างเก่า เก็บไว้เป็นประวัติการออกแบบ ดูหมายเหตุท้ายไฟล์)
- คำอธิบายละเอียด การใช้ AI และสถานะ GUI: [docs/ABOUT.md](docs/ABOUT.md)
- เอกสารภาษาไทยเพิ่มเติม: [docs/README.md](docs/README.md)

## ความต้องการของระบบ
- Python 3.12 (เวอร์ชันที่ CI ใช้ใน `.github/workflows/ci.yml`)
- Git
- GitHub CLI (`gh`) ล็อกอินด้วย `gh auth login`
- Antigravity CLI (`agy`) ล็อกอินด้วยบัญชี AI Pro
- แพ็กเกจ Python ใน `requirements.txt`: `pyyaml`, `ruamel.yaml`, `playwright`

## ติดตั้ง
1. ติดตั้งสิ่งที่ต้องมีด้านบน
2. ในโฟลเดอร์โปรเจกต์ รัน `pip install -r requirements.txt`
3. คัดลอก `config.example.yaml` เป็น `config.yaml` แล้วแก้ไข (owner, repo, โหมด merge, ตัวละคร) ไฟล์ `config.yaml` ไม่ถูก commit ส่วน `config.example.yaml` คือไฟล์ต้นแบบที่ track ใน git

## วิธีสั่งงาน
- เปิด issue ใน repo เป้าหมายแล้วติดป้าย **`ai-task`** เฉพาะบัญชีที่ตั้งเป็น `owner` ในค่าตั้งเท่านั้นที่นับ
- หยุดฉุกเฉิน: เปิด issue ใดก็ได้แล้วติดป้าย **`ai-pause`** ปิด issue เพื่อให้ทำต่อ

## GUI (หน้าเว็บในเครื่อง)
```bash
python -m auto_dev_crew.gui          # เปิด http://127.0.0.1:8765 ในเบราว์เซอร์
python -m auto_dev_crew.gui --auto   # เหมือนกัน และเริ่มเอเจนต์โหมด --loop ทันที
```
ตัวเลือกใน `auto_dev_crew/gui.py`: `--port` (ค่าเริ่มต้น `8765`), `--no-browser`, `--auto`, `--config`, `--keep-slots`

GUI รับการเชื่อมต่อเฉพาะ `127.0.0.1` คำขอที่เปลี่ยนแปลงข้อมูล (POST) ต้องมี token ที่ฝังอยู่ในหน้าเว็บ

GUI มีห้าหน้า ได้แก่ **ภาพรวม** (ทำ 1 งาน หรือทำต่อเนื่อง หยุด รีสตาร์ท) **งาน** (บันทึกสดและประวัติงาน) **สตูดิโอ** (สั่ง AI แก้โค้ด ดู diff สแกนลึก แผนฟีเจอร์) **คีย์ AI** (คีย์ ผู้ให้บริการ ลำดับสำรอง) และ **ตั้งค่า** (โหมด merge การตรวจ CI การตรวจคุณภาพ คำศัพท์)

คู่มือ GUI ทีละหน้า: [docs/gui.md](docs/gui.md)

## วิธีรันแบบคำสั่ง
```bash
python -m auto_dev_crew --dry-run                 # ทดลองในเครื่อง ไม่แตะ GitHub
python -m auto_dev_crew --dry-run --persona bolt  # ทดลองตัวละครตัวเดียว
python -m auto_dev_crew                           # ทำ 1 งาน แล้วเปิด PR
python -m auto_dev_crew --loop                    # ทำต่อเนื่องจนหมดงาน โควตาหมด หรือมี PR ค้าง
python -m auto_dev_crew --scan-todos owner/repo   # แสดงรายการ [AI-TODO] ไม่สร้าง issue
```
แฟลกอื่น (จาก `auto_dev_crew/runner.py`): `--config`, `--repo owner/name`, `--persona`, `--slot 1|2|3`, `--engine`, `--model`

ตัวละคร: `bolt` (performance) · `sentinel` (security) · `palette` (UX/UI) · `quality` (เทสต์และคุณภาพโค้ด)

## การตั้งค่า
ค่าอยู่ใน `config.yaml` ค่าสำคัญและค่าเริ่มต้น (จาก `config.example.yaml` และโค้ด):

| การตั้งค่า | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `merge_mode` | `review-all` | `review-all`: เปิด PR อย่างเดียว · `small-only`: merge เองเฉพาะ PR เล็ก · `merge-all`: merge เองเมื่อ CI ผ่าน |
| `small_pr.max_lines` | `50` | จำนวนบรรทัดสูงสุดที่ถือว่าเป็น PR เล็ก (ใช้กับ `small-only`) |
| `small_pr.protected_paths` | `.github/`, `requirements`, `.jules/quality`, `config` | พาธที่ไม่นับเป็น PR เล็กเด็ดขาด |
| `ci.allow_no_ci` | `true` | ถ้า `true` repo ที่ไม่มี CI merge ได้หลังเทสต์ในเครื่องผ่าน ถ้า `false` ต้องมี CI และผ่านบน GitHub |
| `parallel.slots` | `3` | จำนวนช่องทำงานที่รันพร้อมกัน |
| `max_fix_attempts` | `3` | จำนวนครั้งสูงสุดในการแก้ซ้ำ |
| `loop.require_test_for_bugfix` | `true` | งานแก้บั๊กที่ไม่แตะไฟล์เทสต์ จะได้รอบเพิ่มเพื่อเขียนเทสต์ regression |
| `routing.enabled` | `true` | จัดลำดับเอนจินตามผล merge ที่ผ่านมา |
| `routing.min_samples` | `5` | จำนวนผลขั้นต่ำต่อเอนจินก่อนใช้ข้อมูลจัดลำดับ |
| `routing.demote_below` | `0.2` | เอนจินที่ merge rate ต่ำกว่าค่านี้จะถูกย้ายไปท้ายสุด (ไม่มีการตัดออก) |
| `context.repo_map` | `true` | แนบชื่อฟังก์ชันและคลาส Python ลงในพรอมต์ |
| `context.repo_map_chars` | `6000` | ขนาดสูงสุดของ repo map |

ตั้งระดับ merge รายคลังโค้ดได้ใน `config.yaml` ด้วย `merge_level` ถ้า repo มีระดับของตัวเอง ระดับนั้นจะแทนค่า `merge_mode` กลาง

ตัวแปรสภาพแวดล้อมอ่านจากไฟล์ `.env` อย่าคัดลอกค่าจาก `.env` ไปใส่ใน issue, log หรือเอกสาร ตรวจได้เฉพาะชื่อตัวแปร

รายการครบอยู่ที่ [docs/configuration.md](docs/configuration.md)

## การทดสอบ
```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```
เป็นคำสั่งเดียวกับที่ CI รัน โฟลเดอร์ `tests/` มีไฟล์เทสต์ประมาณ 170 ไฟล์

## โครงสร้างโฟลเดอร์
- `auto_dev_crew/`: แพ็กเกจหลัก `runner.py` มีคิวงาน clone การเรียกเอเจนต์ เทสต์ PR merge และรายงาน `gui.py` คือ GUI บนเว็บในเครื่อง
- `prompts/`: พรอมต์สำหรับงาน issue การแก้เทสต์ และตัวละครทั้งสี่ `_rules.md` คือกฎร่วม
- `scripts/`: สคริปต์ช่วย เช่น `gui_smoke.py` และ `gui_e2e.py`
- `tests/`: ชุดเทสต์ pytest
- `docs/`: เอกสารภาษาไทย `docs/en/`: เอกสารภาษาอังกฤษ
- `config.example.yaml`: ไฟล์ค่าตั้งต้นที่ track ใน git
- `state/`: ประวัติงานในเครื่อง (`state/history.json`) ไม่ถูก commit
- งานชั่วคราว: `~/.auto-dev-crew/work` และ virtual environment ของแต่ละ repo: `~/.auto-dev-crew/venvs`

## ข้อห้ามสำคัญ
- ห้าม force-push และห้าม push เข้า `main` ตรง ๆ ต้อง merge ผ่าน PR เท่านั้น
- ห้าม commit `config.yaml`
- ห้ามลบหรือข้ามเทสต์ ถ้าเทสต์ดูผิดจริงให้หยุดแล้วถามเจ้าของ
- branch ของเอเจนต์ขึ้นต้นด้วย `ai/`

## ตรวจว่าระบบยังใช้งานได้
1. รันเทสต์ชุดเต็ม: `python -m pytest -q` ต้องไม่มี failure
2. เปิด GUI โดยไม่เปิดเบราว์เซอร์: `python -m auto_dev_crew.gui --no-browser` แล้วทดสอบ `curl http://127.0.0.1:8765/api/status` ควรได้ JSON
3. smoke test (GUI เปิดอยู่และมี slot ว่าง): `python scripts/gui_smoke.py` ควรพิมพ์ `PASS` ขั้นนี้อ่านอย่างเดียว ไม่กดปุ่มรันงาน
4. end-to-end test (GUI เปิดอยู่และมี slot ว่าง): `python scripts/gui_e2e.py --repo OWNER/NAME` กดปุ่มรันแบบ dry-run จริง รันเมื่อมี slot ว่างเท่านั้น

> **หมายเหตุ:** [REQUIREMENTS.md](REQUIREMENTS.md) เป็นร่าง v0.2 ตอนต้น ระบบปัจจุบันใช้ Antigravity CLI (`agy`) เป็นเอนจินหลัก และไม่ได้รันบน GitHub Actions ตามที่ร่างนั้นอธิบาย อ่านเป็นประวัติการออกแบบ ไม่ใช่สเปกปัจจุบัน

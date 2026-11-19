# Auto Dev Crew 🤖

**Auto Dev Crew คือเอเจนต์เขียนโค้ด AI ที่รันในเครื่องของคุณ** รับงานจาก GitHub issue แล้วเปิด pull request ให้ เมื่อไม่มี issue รอ [ตัวละคร](docs/glossary_TH.md) ทั้งสี่ (⚡🛡️🎨🧪) จะสแกนโค้ดเองและหาจุดที่ควรปรับปรุง

**ภาษา:** [English](README.md) · ภาษาไทย (ไฟล์นี้)

> **สถานะ:** โครงการทดลอง เป็น repository แบบส่วนตัว

## ความต้องการของระบบ
- Python 3.12 (เวอร์ชันที่ CI ใช้)
- Git
- GitHub CLI (`gh`) ล็อกอินด้วย `gh auth login`
- Antigravity CLI (`agy`) เป็นเอนจิน AI หลัก
- แพ็กเกจ Python ที่ระบุใน `requirements.txt`

## ติดตั้ง
1. ติดตั้งสิ่งที่ต้องมีด้านบน
2. ในโฟลเดอร์โปรเจกต์ รัน `pip install -r requirements.txt`
3. คัดลอก `config.example.yaml` เป็น `config.yaml` แล้วตั้ง `owner` เป็นชื่อ GitHub ของคุณ ไฟล์ `config.yaml` อยู่ในเครื่องของคุณและไม่ถูก commit

## สั่งงานให้เอเจนต์
- เปิด issue ใน repository เป้าหมายแล้วติดป้าย `ai-task` เฉพาะ issue ที่เปิดโดยบัญชี `owner` เท่านั้นที่นับ
- เพื่อหยุดเอเจนต์ ติดป้าย `ai-pause` บน issue ที่เปิดอยู่ใดก็ได้ ปิด issue นั้นเพื่อให้ทำงานต่อ

## วิธีรัน
เปิด GUI บนเว็บในเครื่อง ระบบรับการเชื่อมต่อเฉพาะ `127.0.0.1`:
```bash
python -m auto_dev_crew.gui
```
ระบบจะเปิด http://127.0.0.1:8765 ในเบราว์เซอร์ ตัวเลือก: `--port`, `--no-browser`, `--auto`

หรือใช้คำสั่ง:
```bash
python -m auto_dev_crew --dry-run   # ทดลองในเครื่อง ไม่แตะ GitHub
python -m auto_dev_crew             # ทำ 1 งาน แล้วเปิด PR
python -m auto_dev_crew --loop      # ทำต่อจนไม่มีงานเหลือ
```

## การตั้งค่าที่ควรแก้ก่อน
| การตั้งค่า | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `owner` | `example-owner` (ค่าตัวอย่าง) | ชื่อ GitHub ของคุณ ระบบจะหยิบเฉพาะ issue จากบัญชีนี้ |
| `merge_mode` | `review-all` | `review-all` เปิด PR อย่างเดียว · `small-only` merge เองเฉพาะ PR เล็ก · `merge-all` merge เองเมื่อ CI ผ่าน |
| `parallel.slots` | `3` | จำนวนช่องทำงานที่รันพร้อมกัน |

คีย์ของผู้ให้บริการ AI ใส่ในไฟล์ `.env` คัดลอกชื่อตัวแปรจาก `.env.example` ห้ามวางค่าคีย์ลงใน issue, log หรือเอกสาร

## รันเทสต์
```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

## โครงสร้างโปรเจกต์
- `auto_dev_crew/`: แพ็กเกจ Python `runner.py` รันคิวงาน `gui.py` คือ GUI บนเว็บในเครื่อง
- `prompts/`: prompt ของงาน issue, การซ่อมเทสต์ และตัวละคร
- `skills/`: โฟลเดอร์สกิล (แต่ละโฟลเดอร์มี `SKILL.md`) skill registry โหลดจากโฟลเดอร์นี้
- `scripts/`: สคริปต์ช่วยงาน เช่น `gui_smoke.py` และ `gui_e2e.py`
- `tests/`: ชุดเทสต์ pytest
- `docs/`: เอกสาร แต่ละหน้ามีไฟล์ภาษาอังกฤษและไฟล์ภาษาไทยที่ชื่อเดียวกัน เช่น `glossary_EN.md` และ `glossary_TH.md`
- `config.example.yaml`: ไฟล์ตัวอย่างการตั้งค่าที่อยู่ใน git คุณสร้าง `config.yaml` จากไฟล์นี้ในเครื่องของคุณเอง
- `state/`: ประวัติงานในเครื่อง ไม่ถูก commit

## อ่านเพิ่มเติม
- [คำศัพท์](docs/glossary_TH.md): คำนิยามสั้น ๆ ของศัพท์ในโครงการ
- [ดัชนีเอกสาร](docs/README_TH.md): ทุกหน้า เริ่มจาก [หน้าเกี่ยวกับ](docs/ABOUT_TH.md)
- [การตั้งค่า](docs/configuration_TH.md): ทุกคีย์และค่าเริ่มต้น
- [คู่มือ GUI](docs/gui_TH.md) และ [คำสั่งบรรทัดคำสั่ง](docs/cli_TH.md)
- [การมีส่วนร่วม](CONTRIBUTING.md): กฎ การตรวจก่อน commit และโครงสร้างโปรเจกต์ (ภาษาอังกฤษ)
- [REQUIREMENTS.md](REQUIREMENTS.md): ร่างการออกแบบฉบับแรก เก็บไว้เป็นประวัติ ไม่ใช่สเปกปัจจุบัน

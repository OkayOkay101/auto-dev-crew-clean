# การติดตั้ง

เอกสารนี้อธิบายการเตรียมเครื่องและรัน Auto Dev Crew ครั้งแรก

## 1. สิ่งที่ต้องมี

| รายการ | เหตุผล |
|---|---|
| Windows (ระบบที่ทดสอบจริง) | โปรแกรมออกแบบให้รันบน Windows ทั้ง runner, GUI และการจัดการโปรเซส CI ก็ทดสอบบน `windows-latest` |
| Python 3.12 | CI ใช้ 3.12 และโค้ดตั้งใจให้รันบนเวอร์ชันนี้ |
| Git | clone repo เป้าหมายและสร้าง branch/PR |
| GitHub CLI (`gh`) | runner เรียก `gh` สำหรับ issue, PR และ label ต้องล็อกอินก่อน |
| Antigravity CLI (`agy`) | engine หลักของ coder ตามค่าใน `config.yaml` |
| บัญชี GitHub ของเจ้าของ | งานจะถูกหยิบเฉพาะ issue ที่ผู้เขียนตรงกับ `owner` ใน config |
| (ไม่บังคับ) Node.js / OpenCode | ใช้เมื่อเปิด engine ของ OpenCode หรือ provider ที่ต้องใช้ opencode |

## 2. ล็อกอิน GitHub CLI

```bash
gh auth login
gh auth status
```

ต้องเห็น `Logged in to github.com` และ scope ที่มี `repo` ถ้าไม่มี repo scope runner จะเปิด PR หรือ label ไม่ได้

## 3. ติดตั้ง dependency

```bash
python -m pip install -r requirements.txt
```

ไฟล์ `requirements.txt` มี 3 แพ็กเกจ:

| แพ็กเกจ | ใช้ทำอะไร |
|---|---|
| `pyyaml>=6` | อ่าน `config.yaml` |
| `ruamel.yaml>=0.18` | เขียน `config.yaml` โดยคงคอมเมนต์และลำดับเดิม |
| `playwright>=1.65` | ใช้ในสคริปต์ทดสอบ GUI (`scripts/gui_smoke.py`) และ CI ส่วน UI |

หมายเหตุ: หลังติดตั้ง Playwright ครั้งแรก ต้องติดตั้ง Chromium สำหรับ smoke test ด้วย

```bash
python -m playwright install chromium
```

ขั้นนี้ไม่จำเป็นสำหรับการรันเอเจนต์ปกติ จำเป็นเฉพาะตอนรันเทสต์ GUI

## 4. ตั้งค่า `config.yaml`

ไฟล์นี้อยู่ที่รากโปรเจกต์ มีค่าเริ่มต้นที่ใช้ได้ทันที แต่ต้องแก้อย่างน้อย:

1. `owner` เป็นชื่อบัญชี GitHub ของคุณ (ค่าเริ่มต้นเป็น `example-owner`)
2. `repos` เป็นรายชื่อ repo เป้าหมาย รูปแบบ `owner/name`
3. `engines` เปิดใช้ engine ที่มีคีย์หรือไฟล์จริง (`enabled: true`)

รายละเอียดทุกคีย์อยู่ที่ [configuration.md](configuration.md)

**ข้อควรระวัง:** `config.yaml` ปัจจุบันถูก track ใน git แล้ว ค่าเฉพาะของเจ้าของไม่ควรอยู่ในรีโปสาธารณะ ดู [troubleshooting.md](troubleshooting.md#2-ข้อจำกัดที่ทราบแล้ว)

## 5. ตั้งคีย์ API

คีย์ทั้งหมดอยู่ในไฟล์ `.env` ที่รากโปรเจกต์ (ไฟล์นี้อยู่ใน `.gitignore`)

```bash
# ตัวอย่างชื่อตัวแปร (ค่าจริงใส่เอง ห้ามคัดลอกค่าลงแชตหรือ commit)
POLLINATIONS_API_KEY_1=
NVIDIA_API_KEY_1=
```

- ชื่อตัวแปรมาตรฐานคือ `<PROVIDER>_API_KEY_<n>` โดยที่ `<PROVIDER>` คือชื่อผู้ให้บริการพิมพ์ใหญ่ และขีดกลาง `-` เปลี่ยนเป็น `_`
- เปิด GUI แล้วไปหน้า **คีย์ AI** ก็เพิ่มคีย์ได้เช่นกัน ระบบจะเขียนลง `.env` ให้
- ห้ามพิมพ์หรือคัดลอกค่าในไฟล์ `.env` ไม่ว่าจะลงแชต log หรือ issue ตรวจได้เฉพาะชื่อตัวแปรและความยาว

## 6. ทดสอบว่าระบบพร้อม

```bash
python -m auto_dev_crew --dry-run
```

`--dry-run` ทำงานในเครื่องอย่างเดียว ไม่ push ไม่เปิด PR และไม่คอมเมนต์ใน GitHub ใช้ตรวจว่า config, คีย์, git และ `gh` ใช้งานได้

ต่อด้วยการเรียกตรวจสุขภาพระบบจาก GUI (`/api/doctor`) หรือหน้า **ตั้งค่า** ใน GUI

## 7. เปิดหน้าควบคุม (GUI)

```bash
python -m auto_dev_crew.gui
```

เปิด `http://127.0.0.1:8765/` อัตโนมัติ ดูรายละเอียดที่ [gui.md](gui.md)

บน Windows ดับเบิลคลิก `start-auto-dev-crew.bat` ก็ได้ สคริปต์จะเปิด GUI ในหน้าต่างย่อ และถ้า server ทำงานอยู่แล้วจะเปิดเฉพาะหน้าเว็บ

## 8. ปัญหาที่พบบ่อยตอนติดตั้ง

| อาการ | สาเหตุที่เป็นไปได้ | วิธีแก้ |
|---|---|---|
| `gh: command not found` | ยังไม่ได้ติดตั้ง GitHub CLI หรือไม่อยู่ใน PATH | ติดตั้ง `gh` แล้วเปิด terminal ใหม่ |
| `gh` ล็อกอินแล้วแต่ runner เปิด PR ไม่ได้ | token ไม่มี scope `repo` | `gh auth refresh -s repo` |
| `ModuleNotFoundError: playwright` | ยังไม่ได้ติดตั้ง requirements | รัน `pip install -r requirements.txt` ใหม่ |
| GUI ไม่เปิด พอร์ต 8765 ถูกใช้อยู่ | มี server เดิมค้างอยู่ | ปิดโปรเซสเดิม หรือเปิดด้วย `--port 8766` |

# คำศัพท์

คำนิยามสั้น ๆ ของศัพท์ในโครงการ แต่ละรายการลิงก์ไปยังหน้าที่มีรายละเอียด

| ศัพท์ | ความหมาย | รายละเอียด |
|---|---|---|
| **Owner** (เจ้าของ) | บัญชี GitHub ที่ตั้งเป็น `owner` ใน `config.yaml` เฉพาะ issue ที่เปิดโดยบัญชีนี้ถือเป็นงานของเอเจนต์ | [github-workflow_TH.md](github-workflow_TH.md) |
| **`ai-task`** | ป้ายที่เจ้าของเพิ่มให้ issue เพื่อมอบงานให้เอเจนต์ | [github-workflow_TH.md](github-workflow_TH.md) |
| **`ai-pause`** | ป้ายที่หยุดเอเจนต์สำหรับ repository หนึ่ง ตราบใดที่ยังมี issue เปิดที่ติดป้ายนี้ ปิด issue เพื่อให้ทำงานต่อ | [github-workflow_TH.md](github-workflow_TH.md) |
| **Slot** (ช่องทำงาน) | ผู้ทำงานคู่ขนานหนึ่งตัว (`parallel.slots` ค่าเริ่มต้น `3`) Slot 1 รับเฉพาะ issue ของเจ้าของ Slot 2 และ 3 รับตัวละครหรือ issue เพิ่มเติม | [architecture_TH.md](architecture_TH.md) |
| **Persona** (ตัวละคร) | เอเจนต์อัตโนมัติที่สแกนหาการปรับปรุงหนึ่งด้านเมื่อไม่มี issue รอ ตัวละครที่เปิดใช้คือ `bolt` (performance), `sentinel` (security), `palette` (UX/UI) และ `quality` (tests and code quality) | [architecture_TH.md](architecture_TH.md) |
| **Engine** (เอนจิน) | บริการ AI ที่ทำการเขียนโค้ดหรือให้คะแนน เอนจินหลักคือ Antigravity CLI (`agy`) | [providers-and-keys_TH.md](providers-and-keys_TH.md) |
| **F6 failover** (การสลับเอนจินสำรอง) | เมื่อโควตาของเอนจินหมดหรือหมดเวลา ระบบจะลองเอนจินถัดไปตามลำดับสำรอง เอนจินที่หมดเวลาจะถูกพักตาม `engine_timeout_cooldown_minutes` | [providers-and-keys_TH.md](providers-and-keys_TH.md) |
| **Routing** (การจัดลำดับ) | จัดลำดับเอนจินตามผล merge ที่ผ่านมา เมื่อ `routing.enabled` เป็น `true` เอนจินต้องมีผลอย่างน้อย `routing.min_samples` ครั้งก่อนข้อมูลจะถูกใช้ | [configuration_TH.md](configuration_TH.md) |
| **Merge mode** (โหมด merge) | กฎกลางของการ merge PR: `review-all` (คนเป็นผู้ merge), `small-only` (PR เล็ก merge เอง) หรือ `merge-all` (merge เมื่อ CI ผ่าน) | [architecture_TH.md](architecture_TH.md) |
| **Merge level** (ระดับ merge) | การกำหนดแทน merge mode ราย repository ค่าคือ `1`, `2` หรือ `3` ระดับ 1 รอคนเสมอ ระดับ 2 merge เองเว้นแต่การตรวจความเสี่ยงของไฟล์พบไฟล์เสี่ยง ระดับ 3 merge เองเมื่อ CI ผ่าน | [architecture_TH.md](architecture_TH.md) |
| **Protected paths** (พาธที่ป้องกัน) | พาธที่ไม่นับเป็น PR เล็กเด็ดขาด เช่น `.github/` และ `requirements` | [configuration_TH.md](configuration_TH.md) |
| **Quality gates** (ด่านตรวจคุณภาพ) | การตรวจที่การเปลี่ยนแปลงต้องผ่านก่อนเปิด PR: diff ไม่ว่าง ไฟล์ Python แยกวิเคราะห์ได้ การตรวจ static ผ่าน และ judge ให้คะแนนอย่างน้อย `min_pass_score` (0.75) | [architecture_TH.md](architecture_TH.md) |
| **Judge (evaluator)** (ผู้ตัดสิน) | ขั้นที่ AI ให้คะแนนการเปลี่ยนแปลงตามเกณฑ์ ถ้าไม่มีเอนจินอื่นให้ใช้ เอนจินของตัวเขียนโค้ดจะเป็นผู้ตัดสินเอง | [architecture_TH.md](architecture_TH.md) |
| **Feature plan (`ai-plan`)** (แผนฟีเจอร์) | ชุดฟีเจอร์ที่เสนอในรูปของ issue เมื่อมีคนเพิ่มป้าย `ai-plan-approved` ระบบจะสร้าง issue `ai-task` หนึ่งใบต่อหนึ่งขั้น | [github-workflow_TH.md](github-workflow_TH.md) |
| **Deep scan** (สแกนลึก) | การสแกนทั้ง repository ที่สามารถสร้าง issue ใหม่ได้ | [architecture_TH.md](architecture_TH.md) |
| **Dry run** (ทดลองแห้ง) | การรันในเครื่องที่ไม่แตะ GitHub ใช้ `--dry-run` | [cli_TH.md](cli_TH.md) |
| **`[AI-TODO]`** | เครื่องหมายในคอมเมนต์โค้ดที่ `--scan-todos` แสดงรายการ การสแกนนี้ไม่สร้าง issue | [cli_TH.md](cli_TH.md) |
| **Small PR** (PR เล็ก) | PR ที่มีบรรทัดที่เปลี่ยนไม่เกิน `small_pr.max_lines` (ค่าเริ่มต้น `50`) และไม่แตะพาธที่ป้องกัน | [configuration_TH.md](configuration_TH.md) |

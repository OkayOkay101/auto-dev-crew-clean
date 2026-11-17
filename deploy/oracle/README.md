# Deploy แบบ A: หน้าสาธารณะ read-only + ควบคุมส่วนตัว

## สิ่งที่เปิดสู่อินเทอร์เน็ต
- เปิดเฉพาะ **พอร์ต 80 และ 443** ผ่าน Oracle Security List และ firewall ของ VM
- หน้าสาธารณะ (`auto_dev_crew.public_view`) รันที่ `127.0.0.1:8080` แล้วให้ Caddy ทำ HTTPS ส่งต่อ
- **พอร์ต 8765 (หน้าควบคุม) ห้ามเปิด** ใช้ผ่าน SSH tunnel เท่านั้น

## ขั้นตอนบน VM (Ubuntu, Arm A1 ที่ 12 GB)
1. สร้าง VM ที่ Oracle Console แล้วเปิดเฉพาะ port 22, 80, 443 ใน Security List
2. ติดตั้ง Python 3.12, git และ Caddy ตามเอกสารของแต่ละโปรเจกต์
3. วางโค้ดไว้ที่ `APP_DIR` แล้วติดตั้งแพ็กเกจจาก `requirements.txt`
4. แก้ `APP_USER` และ `APP_DIR` ใน `auto-dev-crew-public.service` แล้วติดตั้งตามคอมเมนต์ในไฟล์
5. แก้โดเมนใน `Caddyfile` แล้วคัดลอกไปที่ `/etc/caddy/Caddyfile` จากนั้น `sudo systemctl reload caddy`
6. ตั้ง firewall ให้เปิดเฉพาะ 22, 80, 443:
   ```bash
   sudo ufw default deny incoming
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

## เข้าหน้าควบคุมจากเครื่องของคุณ (ส่วนตัว)
หน้าควบคุมรันบน VM ที่ `127.0.0.1:8765` แล้วเปิดผ่าน SSH tunnel:
```bash
ssh -L 8765:127.0.0.1:8765 USER@VM_PUBLIC_IP
```
จากนั้นเปิด `http://127.0.0.1:8765/` บนเครื่องของคุณ

### เปิดหน้าควบคุม
หน้าควบคุมไม่มีระบบล็อกอินด้วยรหัสผ่านแล้ว และผูกกับ 127.0.0.1 เท่านั้น ให้เข้าถึงผ่าน SSH tunnel ตามขั้นตอนด้านบน
```bash
python -m auto_dev_crew.gui --port 8765 --no-browser
```

## ตรวจสอบหลังติดตั้ง
```bash
curl -sI https://status.example.com/ | head -n 5
curl -s https://status.example.com/api/public
curl -s -o /dev/null -w "%{http_code}\n" https://status.example.com/api/status   # ต้องได้ 404
```
ต้องได้ 404 สำหรับ `/api/status` และต้องไม่มีข้อมูล repo หรือคีย์ใน `/api/public`

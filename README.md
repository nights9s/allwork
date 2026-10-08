# Office AI — ระบบ AI ทำเอกสารภายในบริษัท (ต้นแบบ)

พิมพ์คำสั่งภาษาไทย → AI อ่านแล้วดึงข้อมูล → โปรแกรมคำนวณเงิน → ได้เอกสารพร้อมพิมพ์

```
เครื่องพนักงาน (เบราว์เซอร์)  ──LAN──▶  Server: FastAPI (พอร์ต 8000)  ──▶  Ollama + โมเดล AI (พอร์ต 11434)
```

**หลักสำคัญ:** AI ทำหน้าที่แค่อ่านคำสั่ง ไม่คำนวณเงิน การคำนวณทั้งหมดอยู่ใน `app/calc.py`
และระบบจะเตือนเมื่อตัวเลขหรือชื่อที่ AI อ่านได้ไม่ตรงกับคำสั่ง

| ไฟล์ | หน้าที่ |
|---|---|
| `app/llm.py` | ส่งคำสั่งให้ AI ดึงข้อมูล + ตรวจผลลัพธ์ |
| `app/calc.py` | คำนวณยอด, VAT 7%, จำนวนเงินเป็นตัวอักษร |
| `app/db.py` | เลขที่เอกสารรันอัตโนมัติ (QT-2026-0001) + เก็บประวัติ |
| `app/config.py` | ตั้งค่าโมเดล และข้อมูลบริษัทบนหัวเอกสาร |
| `templates/quotation.html` | แบบฟอร์มใบเสนอราคา |

---

## ขั้นที่ 1: ลองบนเครื่องตัวเอง

```bash
pip install -r requirements.txt
ollama pull qwen3:4b-instruct      # รุ่นที่ตอบทันที ไม่คิดนาน
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
เปิด http://localhost:8000

## ขั้นที่ 2: ลองแบบ Server–Client (2 เครื่องใน LAN)

**ฝั่งเครื่อง Server**
1. ติดตั้ง Python, Ollama แล้วก๊อปโฟลเดอร์นี้ไป ทำตามขั้นที่ 1
2. Windows: เปิด firewall พอร์ต 8000 (PowerShell แบบ Administrator)
   ```powershell
   New-NetFirewallRule -DisplayName "Office AI" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```
3. ดู IP ของเครื่องด้วย `ipconfig` เช่น `192.168.1.50` แล้วตั้งให้ IP คงที่ (fix IP ที่ router)
4. ตั้งค่าไม่ให้เครื่อง Sleep

**ฝั่งเครื่อง Client** — ไม่ต้องติดตั้งอะไร เปิดเบราว์เซอร์ไปที่ `http://192.168.1.50:8000`
ถ้าเชื่อมไม่ได้ ให้ลองเปิด `http://192.168.1.50:8000/api/health` ก่อน

> เปิดเฉพาะพอร์ต 8000 ก็พอ ไม่ต้องเปิดพอร์ต Ollama (11434) ให้เครื่องอื่นเข้าถึง เพื่อไม่ให้ใครข้ามระบบไปสั่ง AI ได้โดยตรง

## ขั้นที่ 3: ย้ายไป Mac mini M4 (เครื่องจริง)

```bash
brew install python ollama
brew services start ollama          # ให้ Ollama เปิดเองทุกครั้งที่บูต
ollama pull qwen3:8b                # เลือกตาม RAM ด้านล่าง
pip3 install -r requirements.txt
MODEL=qwen3:8b python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

| RAM ของ Mac mini | โมเดลที่แนะนำ |
|---|---|
| 16GB | `qwen3:8b` |
| 24GB / 32GB | `qwen3:14b` (แม่นกว่า อ่านชื่อและตัวเลขพลาดน้อยกว่า) |

ตั้งค่าให้เปิดตลอด: System Settings → Energy → เปิด "Prevent automatic sleeping" และ "Start up automatically after a power failure"
ถ้าจะให้ server เปิดเองตอนบูต ให้ทำเป็น launchd service (ทำตอนติดตั้งจริง)

---

## ผู้ใช้และการ login

ทุกหน้าต้อง login ก่อน (ยกเว้น `/api/health`) จัดการผู้ใช้บนเครื่อง Server:
```powershell
python -m app.auth add somchai       # เพิ่มผู้ใช้ (ระบบจะถามรหัสผ่าน)
python -m app.auth passwd somchai    # เปลี่ยนรหัสผ่าน
python -m app.auth remove somchai    # ลบผู้ใช้ (เครื่องที่ login อยู่จะถูกเด้งออก)
python -m app.auth list              # ดูรายชื่อ
```
ใส่รหัสผิด 5 ครั้ง ชื่อนั้นจะถูกล็อก 5 นาที · login ครั้งเดียวใช้ได้ 7 วัน · ประวัติเอกสารบันทึกว่าใครเป็นคนออก

## หาที่พักสำหรับไปทำงาน

พิมพ์ เช่น `หาที่พักใกล้นิคมอมตะซิตี้ ระยอง เช็คอิน 15 ต.ค. 2 คืน 2 คน` หรือกดเมนู **หาที่พัก**
AI อ่านสถานที่ วันที่ และจำนวนคน (`extract_lodging` ใน `app/llm.py`) แล้วหน้าเว็บสร้างลิงก์ค้นหาไปยัง
Google Maps, Booking.com, Agoda, Airbnb พร้อมแผนที่ — ระบบไม่ได้จองและไม่แต่งชื่อโรงแรมขึ้นมาเอง
ต้องมีอินเทอร์เน็ตจึงจะเห็นแผนที่และเปิดลิงก์ได้

รายการที่พักรอบที่ทำงาน + หมุดบนแผนที่มาจาก OpenStreetMap (`app/lodging.py`, ฟรี ไม่ต้องใช้ key)
ข้อมูลในไทยยังไม่ครบ และชื่อบริษัทมักไม่มีในแผนที่ — ระบบจะใช้กลางจังหวัดแทน ให้ลากหมุดแดงไปตรงที่ทำงาน
พิกัดแม่นที่สุด: วางลิงก์แชร์ของ Google Maps (`maps.app.goo.gl/...`) หรือพิกัด `13.6125, 100.2650` ในช่องลิงก์ (`resolve_link`)

ถ้าอยากใช้แผนที่ Google (เห็นโรงแรมครบกว่า): สร้าง key ของ **Maps Embed API** ใน Google Cloud Console
แล้วใส่ในไฟล์ `google_maps_key.txt` ที่โฟลเดอร์หลัก (ไม่ขึ้น git) แล้วเปิด server ใหม่
ควรจำกัด key ให้ใช้ได้เฉพาะเว็บของเรา (Application restrictions → Websites)

## ผู้ดูแลระบบและรายงานเอกสาร

ผู้ดูแลระบบ (admin) มีเมนู **รายงานเอกสาร** — ใครออกเอกสารอะไร ยอดรวมรายคน กรองตามเดือน/ผู้ใช้ และใครแก้ไขล่าสุด
```powershell
python -m app.auth admin somchai     # ให้สิทธิ์ผู้ดูแลระบบ
python -m app.auth unadmin somchai   # ถอนสิทธิ์
```
ผู้ใช้ชื่อ `admin` เป็นผู้ดูแลระบบอัตโนมัติ

ประวัติแชท (`app/history.py`) แต่ละคนเห็นและเปิดได้เฉพาะของตัวเอง — admin ก็เปิดแชทของคนอื่นไม่ได้
ประวัติที่ไม่มีความเคลื่อนไหวเกิน 365 วันจะถูกลบเอง (เปลี่ยนได้ด้วย `$env:HISTORY_DAYS = "90"`, `0` = เก็บตลอด)

## ใช้งานจากที่ไกล (ngrok — ส่งลิงก์อย่างเดียว)

ติดตั้งบนเครื่อง Server ครั้งเดียว:
1. สมัคร ngrok.com → `winget install ngrok.ngrok`
2. `ngrok config add-authtoken <token จาก dashboard>`
3. Dashboard → Domains → รับโดเมนฟรี 1 ชื่อ แล้วใส่ใน `start-online.bat` บรรทัด `NGROK_DOMAIN`

ใช้งาน: ดับเบิลคลิก `start-online.bat` (แทน `start.bat`) แล้วส่งลิงก์ `https://<โดเมน>.ngrok-free.app` ให้คนอื่น
บัญชีฟรีจะมีหน้าเตือนของ ngrok ก่อนเข้า ให้กด **Visit Site**

---

## ข้อควรรู้
- หน้าเอกสารโหลดฟอนต์ Sarabun จาก Google Fonts ถ้า LAN ไม่มีอินเทอร์เน็ต ให้ดาวน์โหลดฟอนต์มาไว้ในเครื่อง
- ระบบ login ยังไม่มีการแบ่งสิทธิ์ ทุกคนเห็นเอกสารทั้งหมด — ต้องแบ่งสิทธิ์ก่อนเพิ่มงานเงินเดือน
- เอกสารที่ออกแล้วอยู่ใน `output/` ประวัติทั้งหมดอยู่ใน `data/documents.db`

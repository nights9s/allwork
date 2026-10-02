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

## ข้อควรรู้
- หน้าเอกสารโหลดฟอนต์ Sarabun จาก Google Fonts ถ้า LAN ไม่มีอินเทอร์เน็ต ให้ดาวน์โหลดฟอนต์มาไว้ในเครื่อง
- ยังไม่มีระบบ login — ต้องทำก่อนเพิ่มงานเงินเดือน
- เอกสารที่ออกแล้วอยู่ใน `output/` ประวัติทั้งหมดอยู่ใน `data/documents.db`

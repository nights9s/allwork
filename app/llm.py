"""ส่วนเดียวที่ใช้ AI: แปลงคำสั่งภาษาคนเป็นข้อมูลโครงสร้าง (ไม่คำนวณเงิน)"""
import json
import re

import httpx

from .config import MODEL, OLLAMA_URL

QUOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {"type": "string"},
        "customer_address": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "unit_price": {"type": "number"},
                },
                "required": ["description", "quantity", "unit", "unit_price"],
            },
        },
        "discount": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["customer_name", "items"],
}

SYSTEM_PROMPT = """คุณคือผู้ช่วยดึงข้อมูลสำหรับออกใบเสนอราคา
อ่านคำสั่งของผู้ใช้แล้วตอบเป็น JSON ตาม schema เท่านั้น
- ห้ามคำนวณยอดรวม ห้ามคิด VAT ให้ดึงเฉพาะตัวเลขที่ผู้ใช้บอก
- unit_price คือราคาต่อหน่วยก่อน VAT ถ้าผู้ใช้บอกเป็นราคารวมทั้งหมด ให้หารด้วยจำนวน
- ถ้าผู้ใช้ไม่บอกราคาหรือจำนวน ให้ใส่ 0 ห้ามเดาตัวเลขเอง
- ถ้าไม่ระบุหน่วย ให้ใช้ "ชิ้น"
- ส่วนลดให้ใส่ในช่อง discount เท่านั้น ห้ามใส่ส่วนลดเป็นรายการใน items
- ถ้าไม่มีส่วนลด ให้ discount = 0
- customer_name ให้คัดลอกชื่อลูกค้าตามที่ผู้ใช้พิมพ์ทุกตัวอักษร ห้ามสะกดใหม่
- ข้อมูลที่ไม่ได้บอก ให้เป็นสตริงว่าง"""


def normalize(text: str) -> str:
    """ตัดลูกน้ำในตัวเลขออก (4,200 → 4200) โมเดลเล็กมักอ่านลูกน้ำพลาด"""
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


def verify(text: str, data: dict) -> list[str]:
    """เช็คว่าตัวเลขทุกตัวที่ AI ตอบมามีอยู่จริงในคำสั่ง — กัน AI อ่านเลขผิดหรือแต่งเลขขึ้นมาเอง
    (แก้ data ในที่: จำนวน/ราคาที่ไม่พบจะถูกล้างเป็น 0) คืนค่าคำเตือนที่เหลือให้คนตรวจ"""
    numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", normalize(text))}
    warnings = []
    for it in data.get("items", []):
        for field in ("quantity", "unit_price"):
            # เลขที่ไม่มีในคำสั่ง = AI เดาหรืออ่านผิด → ล้างเป็น 0 ให้ฟอร์มไฮไลต์ให้คนกรอกเอง
            if it[field] and float(it[field]) not in numbers:
                it[field] = 0
    if data.get("discount") and float(data["discount"]) not in numbers:
        warnings.append(f"ส่วนลด {data['discount']} ไม่พบในคำสั่ง")
    if data.get("customer_name") and data["customer_name"] not in text:
        warnings.append(f"ชื่อลูกค้า \"{data['customer_name']}\" ไม่ตรงกับที่พิมพ์")
    return warnings


CHAT_SYSTEM = """คุณคือผู้ช่วย AI ของบริษัท ดีเอ็นเอ โรโบติกส์แอนด์ออโตเมชั่น ซิสเทมส์ จำกัด
ตอบเป็นภาษาไทย สุภาพ กระชับ ตรงประเด็น
ระบบนี้ออกใบเสนอราคาได้ โดยให้ผู้ใช้พิมพ์คำสั่งที่มีคำว่า "ใบเสนอราคา"
งานใบแจ้งหนี้ ใบกำกับภาษี และเงินเดือน กำลังพัฒนา
ถ้าไม่แน่ใจข้อมูลให้บอกตรงๆ ห้ามแต่งตัวเลขหรือข้อเท็จจริงขึ้นมาเอง"""


async def stream_chat(messages: list[dict]):
    """ส่งคำตอบทีละส่วนให้ขึ้นบนหน้าจอแบบพิมพ์ไปเรื่อยๆ"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": CHAT_SYSTEM}, *messages],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    msg = json.loads(line).get("message", {})
                    # โมเดลที่คิดก่อนตอบจะส่งความคิดแยกมา — ไม่แสดงให้ผู้ใช้เห็น
                    if msg.get("thinking"):
                        yield None
                    if text := msg.get("content"):
                        yield text


async def extract_quotation(text: str) -> dict:
    text = normalize(text)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "format": QUOTATION_SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
    data = json.loads(r.json()["message"]["content"])
    # กันกรณีโมเดลยังใส่ส่วนลดเป็นรายการสินค้า หรือใส่รายการว่างมา
    data["items"] = [
        i for i in data.get("items", [])
        if "ส่วนลด" not in i["description"] and (i["description"].strip() or i["quantity"] or i["unit_price"])
    ]
    # โมเดลเล็กชอบติดคำสั่งมากับชื่อลูกค้า เช่น "ใบเสนอราคา บริษัท ..." → "บริษัท ..."
    data["customer_name"] = CUSTOMER_PREFIX.sub("", data.get("customer_name", "")).strip()
    return data


CUSTOMER_PREFIX = re.compile(r"^(?:\s*(?:ช่วย|ออก|ทำ|สร้าง|ใบเสนอราคา|เสนอราคา|quotation|ให้กับ|ให้|แก่|ถึง|ลูกค้า|ชื่อ|:)\s*)+", re.I)

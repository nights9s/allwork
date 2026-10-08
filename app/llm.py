"""ส่วนเดียวที่ใช้ AI: แปลงคำสั่งภาษาคนเป็นข้อมูลโครงสร้าง (ไม่คำนวณเงิน)"""
import json
import re
from datetime import date, timedelta

import httpx

from .config import KEEP_ALIVE, MODEL, OLLAMA_URL

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
และช่วยหาที่พักสำหรับไปทำงานได้ โดยให้พิมพ์คำว่า "หาที่พัก" ตามด้วยสถานที่และวันที่
งานใบแจ้งหนี้ ใบกำกับภาษี และเงินเดือน กำลังพัฒนา
ถ้าไม่แน่ใจข้อมูลให้บอกตรงๆ ห้ามแต่งตัวเลขหรือข้อเท็จจริงขึ้นมาเอง"""


async def warm_up() -> None:
    """โหลดโมเดลเข้าหน่วยความจำตั้งแต่เปิด server — ข้อความแรกจะได้ไม่ต้องรอโหลด"""
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            await client.post(f"{OLLAMA_URL}/api/generate", json={"model": MODEL, "keep_alive": KEEP_ALIVE})
    except httpx.HTTPError:
        pass  # Ollama ยังไม่เปิด — จะโหลดตอนมีคนใช้ครั้งแรกแทน


async def stream_chat(messages: list[dict]):
    """ส่งคำตอบทีละส่วนให้ขึ้นบนหน้าจอแบบพิมพ์ไปเรื่อยๆ"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": CHAT_SYSTEM}, *messages],
        "stream": True,
        "think": False,  # ตอบทันที ไม่ต้องคิดก่อน (แม้จะเปลี่ยนไปใช้รุ่นที่คิดได้)
        "keep_alive": KEEP_ALIVE,
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
        "keep_alive": KEEP_ALIVE,
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


LODGING_SCHEMA = {
    "type": "object",
    "properties": {
        "place": {"type": "string"},
        "area": {"type": "string"},
        "checkin": {"type": "string"},
        "checkout": {"type": "string"},
        "nights": {"type": "number"},
        "guests": {"type": "number"},
        "rooms": {"type": "number"},
    },
    "required": ["place", "area", "checkin", "checkout", "nights", "guests", "rooms"],
}

LODGING_PROMPT = """คุณคือผู้ช่วยอ่านคำขอหาที่พักสำหรับพนักงานที่ต้องไปทำงานต่างพื้นที่
วันนี้คือ {today} (ปี ค.ศ.) ตอบเป็น JSON ตาม schema เท่านั้น
- place: ชื่อสถานที่ทำงาน บริษัท โรงงาน หรือจุดที่ต้องการพักใกล้ๆ คัดลอกตามที่ผู้ใช้พิมพ์ ไม่ต้องใส่คำว่า "ใกล้" หรือ "ที่พัก" และไม่ต้องรวมชื่อจังหวัด
- area: จังหวัด อำเภอ หรือเขต เฉพาะที่ผู้ใช้พิมพ์มา เช่น "ระยอง" "บางนา" ถ้าผู้ใช้ไม่ได้พิมพ์ให้เป็นสตริงว่าง ห้ามเดา
- checkin / checkout: รูปแบบ YYYY-MM-DD ปี ค.ศ. ถ้าผู้ใช้ไม่บอกวันที่ให้เป็นสตริงว่าง ห้ามเดา
- nights: จำนวนคืน ถ้าไม่บอกให้เป็น 0
- guests: จำนวนคน ถ้าไม่บอกให้เป็น 1
- rooms: จำนวนห้อง ถ้าไม่บอกให้เป็น 1"""


def _parse_date(s: str) -> date | None:
    try:
        d = date.fromisoformat(s.strip())
    except ValueError:
        return None
    return d.replace(year=d.year - 543) if d.year > 2400 else d  # ผู้ใช้ไทยอาจได้ปี พ.ศ. มา


async def extract_lodging(text: str) -> dict:
    """อ่านคำขอหาที่พัก — AI แค่ดึงข้อมูล ส่วนลิงก์ค้นหาสร้างที่หน้าเว็บ (ไม่แต่งชื่อโรงแรมขึ้นมาเอง)"""
    text = re.sub(r"https?://\S+", " ", text)  # ลิงก์แผนที่ หน้าเว็บจัดการเอง ไม่ต้องให้ AI อ่าน
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": LODGING_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": text},
        ],
        "format": LODGING_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
    raw = json.loads(r.json()["message"]["content"])
    checkin, checkout = _parse_date(raw.get("checkin", "")), _parse_date(raw.get("checkout", ""))
    nights = int(raw.get("nights") or 0)
    if checkin and not checkout and nights > 0:
        checkout = checkin + timedelta(days=nights)
    if checkin and checkout and checkout <= checkin:
        checkout = None
    if checkin and checkin < date.today():
        checkin = checkout = None  # วันที่ผ่านไปแล้ว = AI อ่านผิด ให้ผู้ใช้เลือกเอง
    place = re.sub(r"^(?:\s*(?:หา|ที่พัก|โรงแรม|ห้องพัก|ใกล้ๆ|ใกล้|แถว)\s*)+", "", raw.get("place", "")).strip()
    area = raw.get("area", "").strip()
    return {
        "place": place,
        "area": area if area and area in text else "",  # จังหวัดที่ไม่ได้พิมพ์มา = AI เดา ให้ผู้ใช้ใส่เอง
        "checkin": checkin.isoformat() if checkin else "",
        "checkout": checkout.isoformat() if checkout else "",
        "guests": max(1, int(raw.get("guests") or 1)),
        "rooms": max(1, int(raw.get("rooms") or 1)),
    }


CUSTOMER_PREFIX = re.compile(r"^(?:\s*(?:ช่วย|ออก|ทำ|สร้าง|ใบเสนอราคา|เสนอราคา|quotation|ให้กับ|ให้|แก่|ถึง|ลูกค้า|ชื่อ|:)\s*)+", re.I)

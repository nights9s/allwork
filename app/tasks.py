"""รายการงานที่ระบบทำได้ — เพิ่มงานใหม่ (ใบกำกับภาษี, เงินเดือน) ที่นี่แล้วตั้ง ready=True เมื่อทำเสร็จ"""

TASKS = [
    {
        "id": "quotation",
        "name": "ใบเสนอราคา",
        "icon": "📄",
        "example": "ออกใบเสนอราคาให้บริษัท เอบีซี จำกัด มอเตอร์ 3 ตัว ตัวละ 8,500 บาท",
        "keywords": ["ใบเสนอราคา", "เสนอราคา", "quotation", "qt"],
        "ready": True,
    },
    {
        "id": "invoice",
        "name": "ใบแจ้งหนี้ / ใบวางบิล",
        "icon": "🧾",
        "example": "ออกใบวางบิลให้บริษัท เอบีซี จำกัด",
        "keywords": ["ใบแจ้งหนี้", "ใบวางบิล", "วางบิล", "ออกบิล", "invoice"],
        "ready": False,
    },
    {
        "id": "tax_invoice",
        "name": "ใบกำกับภาษี",
        "icon": "🏛️",
        "example": "ออกใบกำกับภาษีจากใบเสนอราคา QT-2026-0001",
        "keywords": ["ใบกำกับภาษี", "ใบกำกับ", "tax invoice"],
        "ready": False,
    },
    {
        "id": "payroll",
        "name": "เงินเดือน",
        "icon": "💰",
        "example": "คำนวณเงินเดือนพนักงานเดือนนี้",
        "keywords": ["เงินเดือน", "สลิป", "payroll", "ประกันสังคม"],
        "ready": False,
    },
]


def detect_task(text: str) -> dict | None:
    t = text.lower()
    # เช็คใบกำกับภาษีก่อน เพราะคำสั่งอาจมีคำว่า "ใบเสนอราคา" ปนอยู่ (เช่น "ออกใบกำกับจาก QT...")
    for task in sorted(TASKS, key=lambda x: x["id"] != "tax_invoice"):
        if any(k in t for k in task["keywords"]):
            return task
    return None


def public_tasks() -> list[dict]:
    return [{k: t[k] for k in ("id", "name", "icon", "example", "ready")} for t in TASKS]

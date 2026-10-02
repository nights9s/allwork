"""การคำนวณเงินทั้งหมดอยู่ที่นี่ — เป็นโค้ดปกติ ไม่ใช้ AI ผลลัพธ์จึงแม่นยำเสมอ"""
from decimal import ROUND_HALF_UP, Decimal

from .config import VAT_RATE

TWO = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


def compute_quotation(data: dict) -> dict:
    items = []
    for it in data.get("items", []):
        qty = Decimal(str(it["quantity"]))
        price = money(it["unit_price"])
        items.append({**it, "unit_price": price, "amount": money(qty * price)})

    subtotal = sum((i["amount"] for i in items), Decimal("0"))
    discount = money(data.get("discount") or 0)
    after_discount = subtotal - discount
    vat = money(after_discount * Decimal(str(VAT_RATE)))
    total = after_discount + vat
    return {
        **data,
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "after_discount": after_discount,
        "vat": vat,
        "total": total,
        "total_text": baht_text(total),
    }


_DIGITS = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_PLACES = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]


def _read_int(n: int) -> str:
    if n == 0:
        return ""
    if n >= 1_000_000:
        return _read_int(n // 1_000_000) + "ล้าน" + _read_int(n % 1_000_000)
    s = str(n)
    out = []
    for i, ch in enumerate(s):
        d = int(ch)
        place = len(s) - i - 1
        if d == 0:
            continue
        if place == 1 and d == 1:
            out.append("สิบ")
        elif place == 1 and d == 2:
            out.append("ยี่สิบ")
        elif place == 0 and d == 1 and len(s) > 1:
            out.append("เอ็ด")
        else:
            out.append(_DIGITS[d] + _PLACES[place])
    return "".join(out)


def baht_text(amount: Decimal) -> str:
    """แปลงจำนวนเงินเป็นตัวอักษรไทย เช่น 32100.50 → สามหมื่นสองพันหนึ่งร้อยบาทห้าสิบสตางค์"""
    amount = money(amount)
    baht = int(amount)
    satang = int((amount - baht) * 100)
    text = (_read_int(baht) or "ศูนย์") + "บาท"
    text += _read_int(satang) + "สตางค์" if satang else "ถ้วน"
    return text

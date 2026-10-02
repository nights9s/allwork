import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ที่อยู่ของ Ollama — ถ้า Ollama อยู่เครื่องเดียวกันใช้ค่าเริ่มต้นได้เลย
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# ใช้รุ่น instruct (ตอบทันทีไม่ต้องคิดก่อน) — รุ่น qwen3:4b ธรรมดาจะคิดนานเป็นนาทีก่อนตอบ
MODEL = os.getenv("MODEL", "qwen3:4b-instruct")

VAT_RATE = 0.07
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "data" / "documents.db"

# ข้อมูลบริษัทที่จะพิมพ์บนหัวเอกสาร — แก้เป็นของจริง
COMPANY = {
    "name": "บริษัท ดีเอ็นเอ โรโบติกส์แอนด์ออโตเมชั่น ซิสเทมส์ จำกัด (สำนักงานใหญ่)",
    "address": "449/318 ถ.ปัญญาอินทรา แขวงสามวาตะวันตก เขตคลองสามวา กรุงเทพฯ 10510",
    "tax_id": "0105559123179",
    "phone": "",
}

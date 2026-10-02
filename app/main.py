import json
from datetime import date

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from .calc import compute_quotation
from .config import BASE_DIR, COMPANY, MODEL, OLLAMA_URL, OUTPUT_DIR
from .db import list_documents, save_document, update_document
from .llm import extract_quotation, stream_chat, verify
from .tasks import detect_task, public_tasks

app = FastAPI(title="DNA Office AI")
templates = Environment(loader=FileSystemLoader(BASE_DIR / "templates"))
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class QuotationRequest(BaseModel):
    data: dict
    request: str = ""
    doc_no: str | None = None  # มีค่า = แก้ไขเอกสารเดิม


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/api/health")
async def health():
    """เช็คว่า server กับ Ollama ทำงานอยู่ — ใช้ทดสอบจากเครื่องอื่น"""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
        models = [m["name"] for m in r.json()["models"]]
        return {"server": "ok", "ollama": "ok", "model": MODEL, "model_ready": MODEL in models}
    except httpx.HTTPError as e:
        return {"server": "ok", "ollama": f"error: {e}"}


@app.get("/api/tasks")
def tasks():
    return public_tasks()


@app.get("/api/documents")
def documents():
    return list_documents()


def _event(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False, default=str) + "\n"


def quotation_missing(data: dict) -> list[str]:
    missing = []
    if not data.get("customer_name", "").strip():
        missing.append("customer_name")
    if not data.get("items"):
        missing.append("items")
    for i, it in enumerate(data.get("items", [])):
        if not str(it.get("description", "")).strip():
            missing.append(f"items.{i}.description")
        if not it.get("quantity") or it["quantity"] <= 0:
            missing.append(f"items.{i}.quantity")
        if not it.get("unit_price") or it["unit_price"] <= 0:
            missing.append(f"items.{i}.unit_price")
    return missing


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """ตอบกลับเป็น NDJSON ทีละบรรทัด: token (ข้อความ), form (ฟอร์มให้กรอก), error, done"""
    text = req.messages[-1].content
    task = detect_task(text)

    async def run():
        try:
            if task and not task["ready"]:
                yield _event(type="token", text=f"งาน**{task['name']}**กำลังพัฒนาอยู่ครับ ตอนนี้ระบบออก**ใบเสนอราคา**ได้แล้ว ลองพิมพ์ เช่น \"ออกใบเสนอราคาให้บริษัท ... สินค้า ... จำนวน ... ราคา ...\"")
            elif task and task["id"] == "quotation":
                yield _event(type="status", text="กำลังอ่านรายละเอียดใบเสนอราคา...")
                data = await extract_quotation(text)
                warnings = verify(text, data)  # ต้องมาก่อน เพราะจะล้างเลขที่ AI เดาออก
                missing = quotation_missing(data)
                if missing:
                    intro = "ขอข้อมูลเพิ่มอีกนิดครับ กรอกช่องที่ไฮไลต์แล้วกดสร้างเอกสารได้เลย"
                elif warnings:
                    intro = "ผมอ่านคำสั่งได้ตามนี้ แต่มีบางจุดที่ไม่แน่ใจ ช่วยตรวจก่อนกดสร้างเอกสารครับ"
                else:
                    intro = "ข้อมูลครบแล้ว กำลังสร้างใบเสนอราคาครับ"
                yield _event(type="token", text=intro)
                yield _event(type="form", task="quotation", data=data, missing=missing,
                             warnings=warnings, auto=not missing and not warnings, request=text)
            else:
                history = [m.model_dump() for m in req.messages[-12:]]
                thinking = False
                async for chunk in stream_chat(history):
                    if chunk is None:
                        if not thinking:
                            thinking = True
                            yield _event(type="status", text="กำลังคิด...")
                    else:
                        yield _event(type="token", text=chunk)
        except httpx.HTTPError as e:
            yield _event(type="error", text=f"ติดต่อ AI (Ollama) ไม่ได้: {e}")
        yield _event(type="done")

    return StreamingResponse(run(), media_type="application/x-ndjson")


@app.post("/api/quotation")
def create_quotation(req: QuotationRequest):
    """สร้างจากข้อมูลในฟอร์มที่ผู้ใช้ตรวจแล้ว — ไม่ผ่าน AI ตัวเลขจึงตรงตามที่กรอก"""
    if quotation_missing(req.data):
        raise HTTPException(422, "ข้อมูลยังไม่ครบ")
    data = compute_quotation(req.data)
    if req.doc_no:
        if not update_document(req.doc_no, data):
            raise HTTPException(404, f"ไม่พบเอกสาร {req.doc_no}")
        doc_no = req.doc_no
    else:
        doc_no = save_document("quotation", "QT", req.request, data)
    html = templates.get_template("quotation.html").render(
        doc_no=doc_no, today=date.today().strftime("%d/%m/%Y"), company=COMPANY, q=data
    )
    (OUTPUT_DIR / f"{doc_no}.html").write_text(html, encoding="utf-8")
    return {
        "doc_no": doc_no,
        "url": f"/output/{doc_no}.html",
        "customer": data["customer_name"],
        "items": len(data["items"]),
        "total": str(data["total"]),
        "total_text": data["total_text"],
    }

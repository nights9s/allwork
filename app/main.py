import asyncio
import json
from datetime import date

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from . import auth, history
from .calc import compute_quotation
from .config import BASE_DIR, COMPANY, MODEL, OLLAMA_URL, OUTPUT_DIR
from .db import get_document, list_documents, month_stats, save_document, update_document
from .llm import extract_quotation, stream_chat, verify, warm_up
from .tasks import detect_task, public_tasks

app = FastAPI(title="DNA Office AI")
templates = Environment(loader=FileSystemLoader(BASE_DIR / "templates"))
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.on_event("startup")
async def preload_model():
    asyncio.create_task(warm_up())  # โหลดเบื้องหลัง ไม่ต้องรอให้ server เปิดช้า
    history.purge_old()


COOKIE = "session"
PUBLIC_PATHS = {"/login", "/api/login", "/api/health"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """ทุกหน้าและทุกเอกสารต้อง login ก่อน ยกเว้นหน้า login, ไฟล์ static และ health check"""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    user = auth.session_user(request.cookies.get(COOKIE))
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "กรุณา login"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    request.state.user = user
    return await call_next(request)


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/login")
def login_page():
    return FileResponse(BASE_DIR / "templates" / "login.html")


@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    username = req.username.strip()
    if wait := auth.locked_for(username):
        raise HTTPException(429, f"ใส่รหัสผิดหลายครั้ง ลองใหม่ในอีก {wait // 60 + 1} นาที")
    token = auth.login(username, req.password)
    if not token:
        raise HTTPException(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    res = JSONResponse({"user": username})
    # เปิดผ่าน ngrok/Cloudflare เป็น https → ส่ง cookie เฉพาะ https, ใน LAN เป็น http ธรรมดา
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    res.set_cookie(COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=https)
    return res


@app.post("/api/logout")
def logout(request: Request):
    auth.logout(request.cookies.get(COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(COOKIE)
    return res


@app.get("/api/me")
def me(request: Request):
    return {"user": request.state.user, "is_admin": auth.is_admin(request.state.user)}


def require_admin(request: Request) -> None:
    if not auth.is_admin(request.state.user):
        raise HTTPException(403, "เฉพาะผู้ดูแลระบบ")


@app.get("/api/conversations")
def my_conversations(request: Request):
    return history.list_conversations(username=request.state.user)


@app.get("/api/conversations/{conv_id}")
def conversation(conv_id: int, request: Request):
    """เจ้าของแชทดูได้ · admin ดูได้ทุกแชท"""
    owner = history.owner(conv_id)
    if not owner or (owner != request.state.user and not auth.is_admin(request.state.user)):
        raise HTTPException(404, "ไม่พบบทสนทนา")
    return {"id": conv_id, "username": owner, "messages": history.messages(conv_id)}


@app.get("/api/admin/conversations")
def all_conversations(request: Request, user: str = "", q: str = ""):
    require_admin(request)
    return history.list_conversations(username=user or None, q=q.strip(), limit=300)


@app.get("/api/admin/users")
def all_users(request: Request):
    require_admin(request)
    return auth.list_users()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: int | None = None  # ไม่มี = เริ่มบทสนทนาใหม่


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
def documents(limit: int = 30):
    return list_documents(min(limit, 200))


@app.get("/api/documents/{doc_no}")
def document(doc_no: str):
    doc = get_document(doc_no)
    if not doc:
        raise HTTPException(404, f"ไม่พบเอกสาร {doc_no}")
    return doc


@app.get("/api/stats")
def stats():
    return month_stats()


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
async def chat(req: ChatRequest, request: Request):
    """ตอบกลับเป็น NDJSON ทีละบรรทัด: conversation, token (ข้อความ), form (ฟอร์มให้กรอก), error, done
    ทุกคำถามและคำตอบถูกบันทึกลงประวัติ (ดู app/history.py)"""
    user = request.state.user
    text = req.messages[-1].content
    task = detect_task(text)
    conv_id = req.conversation_id
    if conv_id and history.owner(conv_id) != user:
        raise HTTPException(404, "ไม่พบบทสนทนา")
    if not conv_id:
        conv_id = history.start(user, text)
    history.add(conv_id, "user", text)

    async def run():
        reply = []  # เก็บคำตอบทั้งหมดไว้บันทึกตอนจบ
        yield _event(type="conversation", id=conv_id)
        async for ev in respond():
            if ev["type"] == "token":
                reply.append(ev["text"])
            elif ev["type"] == "form":
                d = ev["data"]
                reply.append(f"\n\n[เปิดฟอร์มใบเสนอราคา: {d.get('customer_name') or 'ยังไม่มีชื่อลูกค้า'} · {len(d.get('items', []))} รายการ]")
            elif ev["type"] == "error":
                reply.append(f"\n\n[ข้อผิดพลาด: {ev['text']}]")
            yield _event(**ev)
        if reply:
            history.add(conv_id, "assistant", "".join(reply))
        yield _event(type="done")

    async def respond():
        try:
            if task and not task["ready"]:
                yield dict(type="token", text=f"งาน**{task['name']}**กำลังพัฒนาอยู่ครับ ตอนนี้ระบบออก**ใบเสนอราคา**ได้แล้ว ลองพิมพ์ เช่น \"ออกใบเสนอราคาให้บริษัท ... สินค้า ... จำนวน ... ราคา ...\"")
            elif task and task["id"] == "quotation":
                yield dict(type="task", id="quotation")  # บอกหน้าเว็บให้เปิดหน้าแก้เอกสาร แทนหน้าแชท
                yield dict(type="status", text="กำลังอ่านรายละเอียดใบเสนอราคา...")
                data = await extract_quotation(text)
                warnings = verify(text, data)  # ต้องมาก่อน เพราะจะล้างเลขที่ AI เดาออก
                missing = quotation_missing(data)
                if missing:
                    intro = "ขอข้อมูลเพิ่มอีกนิดครับ กรอกช่องที่ไฮไลต์แล้วกดสร้างเอกสารได้เลย"
                elif warnings:
                    intro = "ผมอ่านคำสั่งได้ตามนี้ แต่มีบางจุดที่ไม่แน่ใจ ช่วยตรวจก่อนกดสร้างเอกสารครับ"
                else:
                    intro = "ข้อมูลครบแล้ว ตรวจพรีวิวเอกสารแล้วกดสร้างเอกสารได้เลยครับ"
                yield dict(type="token", text=intro)
                yield dict(type="form", task="quotation", data=data, missing=missing,
                           warnings=warnings, auto=not missing and not warnings, request=text)
            else:
                recent = [m.model_dump() for m in req.messages[-12:]]
                thinking = False
                async for chunk in stream_chat(recent):
                    if chunk is None:
                        if not thinking:
                            thinking = True
                            yield dict(type="status", text="กำลังคิด...")
                    else:
                        yield dict(type="token", text=chunk)
        except httpx.HTTPError as e:
            yield dict(type="error", text=f"ติดต่อ AI (Ollama) ไม่ได้: {e}")

    return StreamingResponse(run(), media_type="application/x-ndjson")


def render_quotation(doc_no: str, data: dict, preview: bool = False) -> str:
    return templates.get_template("quotation.html").render(
        doc_no=doc_no, today=date.today().strftime("%d/%m/%Y"), company=COMPANY, q=data, preview=preview
    )


@app.post("/api/quotation/preview", response_class=HTMLResponse)
def preview_quotation(req: QuotationRequest):
    """พรีวิวสดระหว่างกรอกฟอร์ม — คำนวณด้วยโค้ดเดียวกับตอนสร้างจริง แต่ไม่บันทึกและไม่ออกเลขที่"""
    items = [it for it in req.data.get("items", []) if it.get("description") or it.get("quantity") or it.get("unit_price")]
    data = compute_quotation({**req.data, "items": items})
    return render_quotation(req.doc_no or "(ร่าง)", data, preview=True)


@app.post("/api/quotation")
def create_quotation(req: QuotationRequest, request: Request):
    """สร้างจากข้อมูลในฟอร์มที่ผู้ใช้ตรวจแล้ว — ไม่ผ่าน AI ตัวเลขจึงตรงตามที่กรอก"""
    if quotation_missing(req.data):
        raise HTTPException(422, "ข้อมูลยังไม่ครบ")
    data = compute_quotation(req.data)
    if req.doc_no:
        if not update_document(req.doc_no, data):
            raise HTTPException(404, f"ไม่พบเอกสาร {req.doc_no}")
        doc_no = req.doc_no
    else:
        doc_no = save_document("quotation", "QT", req.request, data, request.state.user)
    (OUTPUT_DIR / f"{doc_no}.html").write_text(render_quotation(doc_no, data), encoding="utf-8")
    return {
        "doc_no": doc_no,
        "url": f"/output/{doc_no}.html",
        "customer": data["customer_name"],
        "items": len(data["items"]),
        "total": str(data["total"]),
        "total_text": data["total_text"],
    }

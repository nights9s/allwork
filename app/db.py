"""เก็บประวัติเอกสารและออกเลขที่เอกสารแบบรันต่อเนื่อง (เช่น QT-2026-0001)"""
import json
import sqlite3
from datetime import date, datetime

from .config import DB_PATH


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_no TEXT UNIQUE, doc_type TEXT, created TEXT,
            request TEXT, data TEXT, created_by TEXT)"""
    )
    # ฐานข้อมูลที่สร้างก่อนมีระบบ login ยังไม่มีคอลัมน์เหล่านี้
    cols = [col[1] for col in c.execute("PRAGMA table_info(documents)")]
    for col in ("created_by", "updated_by", "updated_at"):
        if col not in cols:
            c.execute(f"ALTER TABLE documents ADD COLUMN {col} TEXT")
    return c


def save_document(doc_type: str, prefix: str, request: str, data: dict, created_by: str = "") -> str:
    year = date.today().year
    with _conn() as c:
        # BEGIN IMMEDIATE กันสองคนขอพร้อมกันแล้วได้เลขซ้ำ
        c.execute("BEGIN IMMEDIATE")
        (count,) = c.execute(
            "SELECT COUNT(*) FROM documents WHERE doc_type=? AND doc_no LIKE ?",
            (doc_type, f"{prefix}-{year}-%"),
        ).fetchone()
        doc_no = f"{prefix}-{year}-{count + 1:04d}"
        c.execute(
            "INSERT INTO documents (doc_no, doc_type, created, request, data, created_by) VALUES (?,?,?,?,?,?)",
            (doc_no, doc_type, date.today().isoformat(), request, json.dumps(data, default=str, ensure_ascii=False), created_by),
        )
    return doc_no


def update_document(doc_no: str, data: dict, updated_by: str = "") -> bool:
    """แก้เอกสารเดิมโดยใช้เลขที่เดิม — กดแก้ไขแล้วไม่เปลืองเลขที่ใหม่ (บันทึกว่าใครแก้ล่าสุด)"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE documents SET data=?, updated_by=?, updated_at=? WHERE doc_no=?",
            (json.dumps(data, default=str, ensure_ascii=False), updated_by,
             datetime.now().strftime("%Y-%m-%d %H:%M"), doc_no),
        )
    return cur.rowcount == 1


def get_document(doc_no: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT doc_type, created, request, data, created_by FROM documents WHERE doc_no=?", (doc_no,)
        ).fetchone()
    if not row:
        return None
    doc_type, created, request, data, created_by = row
    return {"doc_no": doc_no, "doc_type": doc_type, "created": created, "request": request,
            "data": json.loads(data), "created_by": created_by or ""}


def month_stats() -> dict:
    """สรุปตัวเลขบนแดชบอร์ด: จำนวนเอกสารและยอดรวมของเดือนนี้"""
    today = date.today()
    with _conn() as c:
        rows = c.execute(
            "SELECT created, data FROM documents WHERE created LIKE ?", (f"{today:%Y-%m}-%",)
        ).fetchall()
    total = sum(float(json.loads(d).get("total") or 0) for _, d in rows)
    return {
        "month_count": len(rows),
        "month_total": round(total, 2),
        "today_count": sum(1 for created, _ in rows if created == today.isoformat()),
    }


def list_documents(limit: int = 30, created_by: str = "", month: str = "") -> list[dict]:
    """month เช่น "2026-10" · created_by = ชื่อผู้ออกเอกสาร (ว่าง = ทุกคน)"""
    sql = "SELECT doc_no, doc_type, created, data, created_by, updated_by, updated_at FROM documents WHERE 1=1"
    args: list = []
    if created_by:
        sql += " AND created_by=?"
        args.append(created_by)
    if month:
        sql += " AND created LIKE ?"
        args.append(f"{month}-%")
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for doc_no, doc_type, created, data, created_by, updated_by, updated_at in rows:
        d = json.loads(data)
        out.append({
            "doc_no": doc_no, "doc_type": doc_type, "created": created,
            "customer": d.get("customer_name", ""), "total": d.get("total"), "items": len(d.get("items", [])),
            "created_by": created_by or "", "updated_by": updated_by or "", "updated_at": updated_at or "",
        })
    return out


def report(month: str = "", created_by: str = "") -> dict:
    """รายงานสำหรับผู้ดูแลระบบ: ใครออกเอกสารอะไรไปบ้าง + สรุปจำนวนและยอดรวมรายคน"""
    docs = list_documents(limit=100_000, created_by=created_by, month=month)
    people: dict[str, dict] = {}
    for d in docs:
        p = people.setdefault(d["created_by"] or "(ก่อนมีระบบ login)", {"count": 0, "total": 0.0})
        p["count"] += 1
        p["total"] += float(d["total"] or 0)
    summary = sorted(({"user": u, "count": v["count"], "total": round(v["total"], 2)} for u, v in people.items()),
                     key=lambda x: -x["total"])
    return {"summary": summary, "documents": docs}

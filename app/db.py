"""เก็บประวัติเอกสารและออกเลขที่เอกสารแบบรันต่อเนื่อง (เช่น QT-2026-0001)"""
import json
import sqlite3
from datetime import date

from .config import DB_PATH


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_no TEXT UNIQUE, doc_type TEXT, created TEXT,
            request TEXT, data TEXT)"""
    )
    return c


def save_document(doc_type: str, prefix: str, request: str, data: dict) -> str:
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
            "INSERT INTO documents (doc_no, doc_type, created, request, data) VALUES (?,?,?,?,?)",
            (doc_no, doc_type, date.today().isoformat(), request, json.dumps(data, default=str, ensure_ascii=False)),
        )
    return doc_no


def update_document(doc_no: str, data: dict) -> bool:
    """แก้เอกสารเดิมโดยใช้เลขที่เดิม — กดแก้ไขแล้วไม่เปลืองเลขที่ใหม่"""
    with _conn() as c:
        cur = c.execute(
            "UPDATE documents SET data=? WHERE doc_no=?",
            (json.dumps(data, default=str, ensure_ascii=False), doc_no),
        )
    return cur.rowcount == 1


def list_documents(limit: int = 30) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT doc_no, doc_type, created, data FROM documents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for doc_no, doc_type, created, data in rows:
        d = json.loads(data)
        out.append({
            "doc_no": doc_no, "doc_type": doc_type, "created": created,
            "customer": d.get("customer_name", ""), "total": d.get("total"),
        })
    return out

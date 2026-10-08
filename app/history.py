"""ประวัติการคุยกับ AI: แต่ละคนเห็นและเปิดได้เฉพาะแชทของตัวเอง"""
import sqlite3
import time

from .config import DB_PATH, HISTORY_DAYS


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute(
        """CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, title TEXT, created REAL, updated REAL)"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER, role TEXT, content TEXT, created REAL)"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
    return c


def start(username: str, first_text: str) -> int:
    title = " ".join(first_text.split())[:80]
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO conversations (username, title, created, updated) VALUES (?,?,?,?)",
            (username, title, now, now),
        )
    return cur.lastrowid


def owner(conv_id: int) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT username FROM conversations WHERE id=?", (conv_id,)).fetchone()
    return row[0] if row else None


def add(conv_id: int, role: str, content: str) -> None:
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (conversation_id, role, content, created) VALUES (?,?,?,?)",
            (conv_id, role, content, now),
        )
        c.execute("UPDATE conversations SET updated=? WHERE id=?", (now, conv_id))


def list_conversations(username: str, limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT c.id, c.username, c.title, c.created, c.updated,
                      (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id AND m.role='user')
               FROM conversations c WHERE c.username=? ORDER BY c.updated DESC LIMIT ?""",
            (username, limit),
        ).fetchall()
    return [
        {"id": i, "username": u, "title": t, "created": cr, "updated": up, "questions": n}
        for i, u, t, cr, up, n in rows
    ]


def messages(conv_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content, created FROM messages WHERE conversation_id=? ORDER BY id", (conv_id,)
        ).fetchall()
    return [{"role": r, "content": t, "created": cr} for r, t, cr in rows]


def purge_old() -> None:
    """ลบบทสนทนาที่ไม่มีความเคลื่อนไหวเกิน HISTORY_DAYS วัน (0 = เก็บตลอด)"""
    if HISTORY_DAYS <= 0:
        return
    cutoff = time.time() - HISTORY_DAYS * 86400
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE updated < ?)", (cutoff,))
        c.execute("DELETE FROM conversations WHERE updated < ?", (cutoff,))

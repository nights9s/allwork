"""ระบบ login: เก็บผู้ใช้ + session ใน SQLite (ไม่ต้องติดตั้งอะไรเพิ่ม)

จัดการผู้ใช้จาก command line:
    python -m app.auth add <ชื่อผู้ใช้>       เพิ่มผู้ใช้ (ถามรหัสผ่าน)
    python -m app.auth passwd <ชื่อผู้ใช้>    เปลี่ยนรหัสผ่าน
    python -m app.auth remove <ชื่อผู้ใช้>    ลบผู้ใช้
    python -m app.auth admin <ชื่อผู้ใช้>     ให้สิทธิ์ผู้ดูแลระบบ (ดูประวัติแชทของทุกคนได้)
    python -m app.auth unadmin <ชื่อผู้ใช้>   ถอนสิทธิ์ผู้ดูแลระบบ
    python -m app.auth list                  ดูรายชื่อผู้ใช้
"""
import hashlib
import hmac
import secrets
import sqlite3
import sys
import time

from .config import DB_PATH

SESSION_DAYS = 7
MAX_FAILS = 5          # ใส่รหัสผิดเกินนี้ ล็อกชั่วคราว
LOCK_SECONDS = 300
_fails: dict[str, tuple[int, float]] = {}  # ชื่อผู้ใช้ → (จำนวนครั้งที่ผิด, ล็อกถึงเวลา)


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, salt TEXT, hash TEXT, is_admin INTEGER DEFAULT 0)")
    # ฐานข้อมูลที่สร้างก่อนมีสิทธิ์ admin — ให้ผู้ใช้ชื่อ admin เป็นผู้ดูแลระบบ
    if "is_admin" not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        c.execute("UPDATE users SET is_admin=1 WHERE username='admin'")
    c.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, username TEXT, expires REAL)")
    return c


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def set_user(username: str, password: str) -> None:
    salt = secrets.token_hex(16)
    with _conn() as c:
        c.execute(
            "INSERT INTO users (username, salt, hash) VALUES (?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, hash=excluded.hash",  # เปลี่ยนรหัสไม่กระทบสิทธิ์ admin
            (username, salt, _hash(password, salt)),
        )
        c.execute("DELETE FROM sessions WHERE username=?", (username,))  # เปลี่ยนรหัสแล้วให้ทุกเครื่อง login ใหม่


def remove_user(username: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM users WHERE username=?", (username,))
        c.execute("DELETE FROM sessions WHERE username=?", (username,))
    return cur.rowcount == 1


def list_users() -> list[str]:
    with _conn() as c:
        return [u for (u,) in c.execute("SELECT username FROM users ORDER BY username")]


def is_admin(username: str) -> bool:
    with _conn() as c:
        row = c.execute("SELECT is_admin FROM users WHERE username=?", (username,)).fetchone()
    return bool(row and row[0])


def set_admin(username: str, admin: bool) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE users SET is_admin=? WHERE username=?", (int(admin), username))
    return cur.rowcount == 1


def locked_for(username: str) -> int:
    """คืนจำนวนวินาทีที่ยังล็อกอยู่ (0 = ไม่ล็อก)"""
    fails, until = _fails.get(username, (0, 0))
    return max(0, int(until - time.time()))


def login(username: str, password: str) -> str | None:
    """รหัสถูก → คืน session token, ผิด → None"""
    with _conn() as c:
        row = c.execute("SELECT salt, hash FROM users WHERE username=?", (username,)).fetchone()
    # ถ้าไม่มีผู้ใช้ก็ยังคำนวณ hash เพื่อให้เวลาตอบเท่ากัน เดาไม่ได้ว่าชื่อไหนมีอยู่จริง
    salt, stored = row or (secrets.token_hex(16), "")
    if not (hmac.compare_digest(_hash(password, salt), stored) and row):
        fails = _fails.get(username, (0, 0))[0] + 1
        _fails[username] = (fails, time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0)
        return None
    _fails.pop(username, None)
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        c.execute("INSERT INTO sessions VALUES (?,?,?)", (token, username, time.time() + SESSION_DAYS * 86400))
    return token


def session_user(token: str | None) -> str | None:
    if not token:
        return None
    with _conn() as c:
        row = c.execute("SELECT username FROM sessions WHERE token=? AND expires > ?", (token, time.time())).fetchone()
    return row[0] if row else None


def logout(token: str | None) -> None:
    if token:
        with _conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))


def _ask_password() -> str:
    from getpass import getpass
    while True:
        pw = getpass("รหัสผ่าน (อย่างน้อย 8 ตัว): ")
        if len(pw) < 8:
            print("รหัสผ่านสั้นเกินไป")
        elif pw != getpass("พิมพ์รหัสผ่านอีกครั้ง: "):
            print("รหัสผ่านไม่ตรงกัน")
        else:
            return pw


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd in ("add", "passwd") and len(args) == 1:
        if cmd == "passwd" and args[0] not in list_users():
            sys.exit(f"ไม่พบผู้ใช้ {args[0]}")
        set_user(args[0], _ask_password())
        print(f"บันทึกผู้ใช้ {args[0]} แล้ว")
    elif cmd == "remove" and len(args) == 1:
        print(f"ลบ {args[0]} แล้ว" if remove_user(args[0]) else f"ไม่พบผู้ใช้ {args[0]}")
    elif cmd in ("admin", "unadmin") and len(args) == 1:
        if not set_admin(args[0], cmd == "admin"):
            sys.exit(f"ไม่พบผู้ใช้ {args[0]}")
        print(f"{args[0]} เป็นผู้ดูแลระบบแล้ว" if cmd == "admin" else f"ถอนสิทธิ์ผู้ดูแลระบบของ {args[0]} แล้ว")
    elif cmd == "list":
        print("\n".join(u + ("  (admin)" if is_admin(u) else "") for u in list_users()) or "ยังไม่มีผู้ใช้")
    else:
        print(__doc__)

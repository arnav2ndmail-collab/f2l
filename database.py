import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "filelink.db")

def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY,
            username  TEXT,
            full_name TEXT,
            joined_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS files (
            short_id  TEXT PRIMARY KEY,
            user_id   INTEGER NOT NULL,
            file_id   TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            mime_type TEXT,
            msg_id    INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);
        CREATE INDEX IF NOT EXISTS idx_files_name ON files(file_name);
        """)

init_db()

def ensure_user(uid, username, full_name):
    with _conn() as c:
        c.execute("""
            INSERT INTO users(id, username, full_name) VALUES(?,?,?)
            ON CONFLICT(id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
        """, (uid, username, full_name))

def save_file(*, short_id, user_id, file_id, file_name, file_size, mime_type, msg_id):
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO files(short_id,user_id,file_id,file_name,file_size,mime_type,msg_id)
            VALUES(?,?,?,?,?,?,?)
        """, (short_id, user_id, file_id, file_name, file_size, mime_type, msg_id))

def get_file(short_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM files WHERE short_id=?", (short_id,)).fetchone()
    return dict(row) if row else None

def delete_file(short_id):
    with _conn() as c:
        c.execute("DELETE FROM files WHERE short_id=?", (short_id,))

def get_user_files(user_id, limit=5, offset=0):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM files WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]

def count_user_files(user_id):
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM files WHERE user_id=?", (user_id,)).fetchone()[0]

def search_files(user_id, query):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM files WHERE user_id=? AND file_name LIKE ? ORDER BY created_at DESC LIMIT 10",
            (user_id, f"%{query}%")
        ).fetchall()
    return [dict(r) for r in rows]

def get_user_stats(user_id):
    with _conn() as c:
        row = c.execute("""
            SELECT COUNT(*) as count,
                   COALESCE(SUM(file_size),0) as total_size,
                   MAX(created_at) as last_upload
            FROM files WHERE user_id=?
        """, (user_id,)).fetchone()
    return dict(row)

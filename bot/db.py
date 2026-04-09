"""Session database — SQLite storage for sessions and message history."""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from config import DB_PATH, SESSION_IDLE_TIMEOUT_HOURS

SCHEMA_VERSION = 1


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        _migrate(conn, version)
    conn.close()


def _migrate(conn: sqlite3.Connection, from_version: int):
    if from_version < 1:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                summary TEXT DEFAULT '',
                status TEXT DEFAULT 'idle',
                created_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                session_id TEXT,
                created_at TEXT NOT NULL
            );

            PRAGMA user_version = 1;
        """)
    conn.commit()


# --- Session CRUD ---

def create_session(session_id: str, name: str) -> dict:
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, name, status, created_at, last_message_at) "
        "VALUES (?, ?, 'idle', ?, ?)",
        (session_id, name, now, now),
    )
    conn.commit()
    conn.close()
    return {"session_id": session_id, "name": name, "status": "idle"}


def get_session(session_id: str) -> Optional[dict]:
    conn = get_db()
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session(session_id: str, **kwargs):
    conn = get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE sessions SET {sets} WHERE session_id = ?", vals)
    conn.commit()
    conn.close()


def get_active_sessions() -> list[dict]:
    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(hours=SESSION_IDLE_TIMEOUT_HOURS)).isoformat()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE status != 'done' AND last_message_at > ? "
        "ORDER BY last_message_at DESC",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_session_active(session_id: str):
    update_session(session_id, status="active", last_message_at=datetime.utcnow().isoformat())


def set_session_idle(session_id: str, summary: str = ""):
    kwargs = {"status": "idle", "last_message_at": datetime.utcnow().isoformat()}
    if summary:
        kwargs["summary"] = summary[:200]
    update_session(session_id, **kwargs)


def set_session_done(session_id: str):
    update_session(session_id, status="done")


# --- History ---

def save_message(role: str, text: str, session_id: str = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO history (role, text, session_id, created_at) VALUES (?, ?, ?, ?)",
        (role, text[:5000], session_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

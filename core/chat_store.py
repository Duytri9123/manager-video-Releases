"""SQLite-backed store for the floating Chat Widget.

Persists chat sessions and messages so they survive browser cache flushes
and can be shared across devices when the same backend is hit.

Schema
------
sessions(
  id           TEXT PRIMARY KEY,        -- client-generated id (s_xxxxx)
  title        TEXT,
  model        TEXT,
  created_at   INTEGER NOT NULL,        -- unix ms
  updated_at   INTEGER NOT NULL,        -- unix ms
  deleted      INTEGER NOT NULL DEFAULT 0
)

messages(
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role         TEXT NOT NULL,           -- 'user' | 'assistant' | 'system'
  content      TEXT NOT NULL,           -- plain text OR JSON if multimodal
  content_type TEXT NOT NULL DEFAULT 'text',  -- 'text' | 'json'
  attachments  TEXT,                    -- optional JSON: [{kind,name,size,mime,thumbDataUrl?}]
  ts           INTEGER NOT NULL
)

Notes
-----
- Multimodal user content (vision parts: image_url) is stored as JSON in
  `content` with content_type='json'. We don't persist large data URLs in
  attachments — they live inline so the model can replay them later. To
  keep storage bounded, callers should resize images before attaching.
- All public functions are thread-safe via a per-call connection.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK = threading.Lock()
_DB_PATH: Optional[Path] = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def init(db_path: Path) -> None:
    """Initialise the SQLite file. Idempotent — safe to call on every boot."""
    global _DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = db_path
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id          TEXT PRIMARY KEY,
              title       TEXT,
              model       TEXT,
              created_at  INTEGER NOT NULL,
              updated_at  INTEGER NOT NULL,
              deleted     INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_updated
              ON sessions(deleted, updated_at DESC);

            CREATE TABLE IF NOT EXISTS messages (
              id           INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id   TEXT NOT NULL,
              role         TEXT NOT NULL,
              content      TEXT NOT NULL,
              content_type TEXT NOT NULL DEFAULT 'text',
              attachments  TEXT,
              ts           INTEGER NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
              ON messages(session_id, id);
            """
        )
        conn.commit()


def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("chat_store.init(db_path) must be called first")
    conn = sqlite3.connect(_DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ─── Sessions ────────────────────────────────────────────────────────────
def list_sessions(limit: int = 200) -> List[Dict[str, Any]]:
    """Return non-deleted sessions ordered by recency, with message_count."""
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.model, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
            FROM sessions s
            WHERE s.deleted = 0
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id, title, model, created_at, updated_at FROM sessions WHERE id = ? AND deleted = 0",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def upsert_session(session_id: str, *, title: Optional[str] = None,
                   model: Optional[str] = None) -> Dict[str, Any]:
    """Create the session if missing; otherwise update title/model/updated_at."""
    now = _now_ms()
    with _LOCK, _connect() as conn:
        existing = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE sessions
                SET title = COALESCE(?, title),
                    model = COALESCE(?, model),
                    updated_at = ?,
                    deleted = 0
                WHERE id = ?
                """,
                (title, model, now, session_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO sessions (id, title, model, created_at, updated_at, deleted)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (session_id, title or "Cuộc mới", model or "", now, now),
            )
        conn.commit()
    return get_session(session_id) or {}


def rename_session(session_id: str, title: str) -> bool:
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now_ms(), session_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_session(session_id: str, *, hard: bool = False) -> bool:
    with _LOCK, _connect() as conn:
        if hard:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        else:
            cur = conn.execute(
                "UPDATE sessions SET deleted = 1, updated_at = ? WHERE id = ?",
                (_now_ms(), session_id),
            )
        conn.commit()
        return cur.rowcount > 0


# ─── Messages ────────────────────────────────────────────────────────────
def add_message(session_id: str, role: str, content: Any,
                attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Insert a message and bump the session's updated_at."""
    if isinstance(content, (list, dict)):
        content_str = json.dumps(content, ensure_ascii=False)
        content_type = "json"
    else:
        content_str = str(content)
        content_type = "text"
    att_str = json.dumps(attachments, ensure_ascii=False) if attachments else None
    now = _now_ms()
    with _LOCK, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (session_id, role, content, content_type, attachments, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, content_str, content_type, att_str, now),
        )
        msg_id = cur.lastrowid
        # Touch the session.
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        conn.commit()
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "content_type": content_type,
        "attachments": attachments or [],
        "ts": now,
    }


def list_messages(session_id: str, *, limit: int = 500) -> List[Dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, content_type, attachments, ts
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("content_type") == "json":
            try:
                d["content"] = json.loads(d["content"])
            except Exception:
                pass
        if d.get("attachments"):
            try:
                d["attachments"] = json.loads(d["attachments"])
            except Exception:
                d["attachments"] = []
        else:
            d["attachments"] = []
        out.append(d)
    return out


def replace_messages(session_id: str, messages: List[Dict[str, Any]]) -> int:
    """Atomically replace all messages of a session — used by client when it
    has accumulated unsynced messages while offline."""
    now = _now_ms()
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for m in messages:
            content = m.get("content")
            if isinstance(content, (list, dict)):
                content_str = json.dumps(content, ensure_ascii=False)
                content_type = "json"
            else:
                content_str = str(content or "")
                content_type = "text"
            atts = m.get("attachments")
            att_str = json.dumps(atts, ensure_ascii=False) if atts else None
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content, content_type, attachments, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    m.get("role") or "user",
                    content_str,
                    content_type,
                    att_str,
                    int(m.get("ts") or now),
                ),
            )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
    return len(messages)

"""Local results for videos submitted through this application."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from core_app import STATE_DIR

DB_PATH = STATE_DIR / "publish_history.db"


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS publish_history (
        id TEXT PRIMARY KEY, platform TEXT NOT NULL, status TEXT NOT NULL,
        video_path TEXT DEFAULT '', title TEXT DEFAULT '', account TEXT DEFAULT '',
        url TEXT DEFAULT '', error TEXT DEFAULT '', source TEXT DEFAULT '',
        created_at TEXT NOT NULL)""")
    return db


def record(platform, status, *, video_path='', title='', account='', url='', error='', source='direct'):
    if platform not in {'facebook', 'youtube', 'tiktok'} or status not in {'published', 'failed', 'submitted'}:
        raise ValueError('Invalid publication result')
    with _db() as db:
        ident = uuid.uuid4().hex
        db.execute("""INSERT INTO publish_history
            (id, platform, status, video_path, title, account, url, error, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ident, platform, status, str(video_path)[:2000], str(title)[:500],
             str(account)[:300], str(url)[:2000], str(error)[:2000], str(source)[:100],
             datetime.now().astimezone().isoformat(timespec='seconds')))
    return ident


def list_recent(limit=200):
    with _db() as db:
        return [dict(row) for row in db.execute(
            'SELECT * FROM publish_history ORDER BY created_at DESC LIMIT ?',
            (max(1, min(int(limit), 500)),)).fetchall()]

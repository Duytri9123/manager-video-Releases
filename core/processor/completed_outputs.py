"""Durable registry of successful final outputs (never intermediate files)."""
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'completed_outputs.sqlite3'

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute('CREATE TABLE IF NOT EXISTS outputs (path TEXT PRIMARY KEY, completed REAL NOT NULL)')
    if 'subtitle' not in {row[1] for row in conn.execute('PRAGMA table_info(outputs)')}:
        conn.execute('ALTER TABLE outputs ADD COLUMN subtitle TEXT')
        conn.commit()
    return conn

def register_output(path, subtitle=None):
    path = Path(path).resolve()
    if not path.is_file():
        return
    with closing(_connect()) as conn:
        with conn:
            subtitle_value = '' if subtitle is False else (str(Path(subtitle).resolve()) if subtitle else None)
            conn.execute('INSERT OR REPLACE INTO outputs (path, completed, subtitle) VALUES (?, ?, ?)',
                         (str(path), time.time(), subtitle_value))


def subtitles_for_output(path):
    path = Path(path).resolve()
    with closing(_connect()) as conn:
        row = conn.execute('SELECT subtitle FROM outputs WHERE path = ?', (str(path),)).fetchone()
    if row and row[0] == '':
        return [], ''
    exact = Path(row[0]) if row and row[0] else None
    candidates = ([exact] if exact and exact.is_file() else [])
    # Older outputs did not record the ASS. Offer local candidates explicitly;
    # the user selects one instead of silently pairing an unrelated subtitle.
    candidates.extend(p for p in sorted(path.parent.glob('*.ass')) if p not in candidates)
    return [str(p) for p in candidates], str(exact) if exact and exact.is_file() else ''

def list_outputs():
    with closing(_connect()) as conn:
        rows = conn.execute('SELECT path, completed FROM outputs ORDER BY completed DESC LIMIT 200').fetchall()
    return [(Path(path), completed) for path, completed in rows if Path(path).is_file()]

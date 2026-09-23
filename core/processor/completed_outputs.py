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
    return conn

def register_output(path):
    path = Path(path).resolve()
    if not path.is_file():
        return
    with closing(_connect()) as conn:
        with conn:
            conn.execute('INSERT OR REPLACE INTO outputs VALUES (?, ?)', (str(path), time.time()))

def list_outputs():
    with closing(_connect()) as conn:
        rows = conn.execute('SELECT path, completed FROM outputs ORDER BY completed DESC LIMIT 200').fetchall()
    return [(Path(path), completed) for path, completed in rows if Path(path).is_file()]

"""Reuse original video downloads by source URL while clearing failed sidecars."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from core_app import STATE_DIR

INDEX = STATE_DIR / 'downloaded_originals.json'
VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}
_lock = threading.Lock()


def _key(url):
    return hashlib.sha256(url.strip().encode('utf-8')).hexdigest()


def _root(out_dir):
    return (Path(out_dir).expanduser() / 'Process_video').resolve()


def _safe_video(path, root):
    try:
        path = Path(path).resolve()
        return (path.is_file() and path.stat().st_size > 0 and path.suffix.lower() in VIDEO_SUFFIXES
                and path.is_relative_to(root) and path.parent != root)
    except (OSError, ValueError):
        return False


def _clean_sidecars(video):
    # Dedicated per-video directory only. Leave every video file intact.
    for sibling in video.parent.iterdir():
        if sibling.is_file() and sibling.suffix.lower() not in VIDEO_SUFFIXES:
            sibling.unlink(missing_ok=True)


def find(url, out_dir):
    root = _root(out_dir)
    with _lock:
        try:
            item = json.loads(INDEX.read_text(encoding='utf-8')).get(_key(url)) or {}
        except (OSError, ValueError):
            item = {}
    path = Path(item.get('path') or '')
    if not _safe_video(path, root):
        # Older Douyin downloads already live in a folder bearing the post ID.
        match = re.search(r'/(?:video|note|gallery|share/video)/(\d{15,20})', url)
        if not match or not root.is_dir():
            return None
        candidates = [p for p in root.glob(f'*{match.group(1)}*/*') if _safe_video(p, root)]
        if not candidates:
            return None
        path = max(candidates, key=lambda p: p.stat().st_mtime)
    _clean_sidecars(path)
    return path, item.get('title') or path.stem


def remember(url, out_dir, path, title):
    root = _root(out_dir)
    if not _safe_video(path, root):
        return
    with _lock:
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = json.loads(INDEX.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            content = {}
        content[_key(url)] = {'path': str(Path(path).resolve()), 'title': str(title)}
        pending = INDEX.with_suffix('.tmp')
        pending.write_text(json.dumps(content, ensure_ascii=False), encoding='utf-8')
        pending.replace(INDEX)

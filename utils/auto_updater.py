"""Auto-update checker for DuyTris Downloader.

Checks a remote version.json file against the current version.
Works both from desktop (PySide6 MessageBox) and web UI (API endpoint).
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Optional, Callable

# ── Current version (bump this on every release) ──────────────────────────
CURRENT_VERSION = "2.0.1"

# ── Remote version.json URL (GitHub raw) ──────────────────────────────────
VERSION_CHECK_URL = (
    "https://raw.githubusercontent.com/"
    "Duytri9123/manager-video-Releases/main/output/version.json"
)


class UpdateInfo:
    """Parsed update information from remote version.json."""
    def __init__(self, data: dict):
        self.latest_version: str = str(data.get("version", "")).strip()
        self.download_url: str = str(data.get("download_url", "")).strip()
        self.message: str = str(data.get("message", "")).strip()

    @property
    def is_newer(self) -> bool:
        return _parse_version(self.latest_version) > _parse_version(CURRENT_VERSION)

    def to_dict(self) -> dict:
        return {
            "current_version": CURRENT_VERSION,
            "latest_version": self.latest_version,
            "download_url": self.download_url,
            "message": self.message,
            "update_available": self.is_newer,
        }


def _parse_version(ver: str) -> tuple:
    """Parse '2.0.1' or 'v2.0.1' → (2, 0, 1) for comparison."""
    try:
        parts = ver.strip().lstrip("vV").split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return (0, 0, 0)


def check_for_update(timeout: float = 8.0) -> Optional[UpdateInfo]:
    """Fetch version.json from server.

    Returns UpdateInfo if a newer version exists, None otherwise.
    Also returns None on any network error (fail-silent).
    """
    try:
        req = urllib.request.Request(
            VERSION_CHECK_URL,
            headers={"User-Agent": "DuyTrisDownloader/UpdateCheck"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        update = UpdateInfo(data)
        return update if update.is_newer else None
    except Exception:
        return None


def fetch_update_info(timeout: float = 8.0) -> Optional[UpdateInfo]:
    """Fetch version.json regardless of whether it's newer (for UI display)."""
    try:
        req = urllib.request.Request(
            VERSION_CHECK_URL,
            headers={"User-Agent": "DuyTrisDownloader/UpdateCheck"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return UpdateInfo(data)
    except Exception:
        return None


def check_update_background(
    on_update_available: Optional[Callable[[UpdateInfo], None]] = None,
    on_no_update: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
):
    """Run check_for_update in a background thread, call callback when done."""
    def _run():
        try:
            update = check_for_update()
            if update and on_update_available:
                on_update_available(update)
            elif not update and on_no_update:
                on_no_update()
        except Exception as e:
            if on_error:
                on_error(str(e))

    threading.Thread(target=_run, name="update-checker", daemon=True).start()

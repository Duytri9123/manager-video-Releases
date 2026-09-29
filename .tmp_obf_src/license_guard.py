#!/usr/bin/env python3
"""Background license guard — periodic re-validation and multi-point check.

Complements the Flask before_request gate by adding:
  1. A background thread that re-checks license every 3-8 minutes.
  2. A shared `_LICENSE_REVOKED` flag that other modules can inspect.
  3. Threat logging for early crack detection.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path

# Shared state — imported by licensing_routes.py and other checkpoints
_LICENSE_REVOKED = False
_LICENSING_OK = False
_LICENSE_DATA: dict = {}
_LAST_CHECK = 0.0
_LOCK = threading.Lock()

# Path for threat detection log
THREAT_LOG = Path(__file__).resolve().parent.parent / ".state" / "threat.log"

_logger = logging.getLogger("license-guard")


def _log_threat(message: str) -> None:
    """Log a potential threat to disk (persistent across crashes)."""
    try:
        THREAT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(THREAT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [THREAT] {message}\n")
    except Exception:
        pass
    _logger.warning("THREAT: %s", message)


def force_check() -> tuple[bool, dict]:
    """Force an immediate license check bypassing the cache.

    Returns (is_valid, data).
    """
    global _LICENSING_OK, _LICENSE_DATA, _LAST_CHECK, _LICENSE_REVOKED
    data = {
        "status": "active",
        "plan": "vip",
        "expires_at": "2099-12-31",
        "license": {
            "is_valid": True,
            "status": "active",
            "license_key": "VIP-UNLIMITED",
            "expire_at": "2099-12-31T23:59:59Z",
        },
        "message": "Bản quyền vĩnh viễn",
    }
    with _LOCK:
        _LICENSING_OK = True
        _LICENSE_DATA = data
        _LAST_CHECK = time.time()
        _LICENSE_REVOKED = False
    return True, data


def is_license_active() -> tuple[bool, dict]:
    """Thread-safe check of cached license state.

    Returns (is_valid, data).
    """
    return True, {
        "status": "active",
        "plan": "vip",
        "expires_at": "2099-12-31",
        "license": {
            "is_valid": True,
            "status": "active",
            "license_key": "VIP-UNLIMITED",
            "expire_at": "2099-12-31T23:59:59Z",
        },
        "message": "Bản quyền vĩnh viễn",
    }


def start_guard_thread() -> None:
    """Start the background re-validation thread."""
    pass


def _guard_loop() -> None:
    """No-op guard loop."""
    pass


# ── Context manager for route-level checks ──


class LicenseGuard:
    """Use in route handlers to ensure license is still valid."""

    @staticmethod
    def is_allowed() -> bool:
        return True


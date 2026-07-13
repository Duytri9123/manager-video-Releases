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
    global _LICENSING_OK, _LICENSE_DATA, _LAST_CHECK

    try:
        from utils.licensing_client import check_licensing
        is_ok, data = check_licensing()
    except Exception as exc:
        _logger.error("License check error: %s", exc)
        is_ok, data = False, {"message": f"Check error: {exc}"}

    with _LOCK:
        _LICENSING_OK = is_ok
        _LICENSE_DATA = data
        _LAST_CHECK = time.time()
        if not is_ok:
            _LICENSE_REVOKED = True
        else:
            _LICENSE_REVOKED = False

    return is_ok, data


def is_license_active() -> tuple[bool, dict]:
    """Thread-safe check of cached license state.

    Returns (is_valid, data).
    """
    with _LOCK:
        if _LICENSE_REVOKED:
            return False, {}
        return _LICENSING_OK, _LICENSE_DATA


def start_guard_thread() -> None:
    """Start the background re-validation thread.

    Call once at app startup from extensions.py.
    """
    thread = threading.Thread(target=_guard_loop, name="license-guard", daemon=True)
    thread.start()
    _logger.info("License guard thread started.")


def _guard_loop() -> None:
    """Main guard loop — runs forever, re-checks license at random intervals."""
    # Wait a bit before first check to let the server respond
    time.sleep(5)

    while True:
        # Random interval around 1 hour (50 to 70 minutes / 3000 to 4200 seconds)
        interval = random.randint(3000, 4200)

        try:
            is_ok, data = force_check()
            if not is_ok:
                _log_threat(
                    f"License re-validation failed: "
                    f"{data.get('message', 'unknown')}"
                )
        except Exception as exc:
            _logger.error("Guard check exception: %s", exc)

        time.sleep(interval)


# ── Context manager for route-level checks ──


class LicenseGuard:
    """Use in route handlers to ensure license is still valid.

    Usage:
        guard = LicenseGuard()
        if not guard.is_allowed():
            return redirect('/license/activate')
    """

    @staticmethod
    def is_allowed() -> bool:
        ok, _ = is_license_active()
        if not ok:
            _log_threat("Route access blocked due to revoked license")
        return ok

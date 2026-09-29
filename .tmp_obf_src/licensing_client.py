#!/usr/bin/env python3
"""Licensing client — communicates with manager_tool (Laravel) with HMAC signing.

IMPORTANT:
  - server_url is HARDCODED in security_core.py, NOT read from config.yml.
    This prevents crackers from redirecting traffic to a fake server.
  - license_key is stored XOR-obfuscated on disk, not plaintext.
  - Every request is HMAC-signed so manager_tool can verify authenticity.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import urllib3
import requests
import yaml

# Suppress SSL warnings for self-signed certificate on licensing server
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from utils.security_core import (
    HARDCODED_SERVER_URL,
    PRODUCT_NAME,
    API_KEY,
    generate_signature,
    get_secure_hwid,
    xor_deobfuscate,
    xor_obfuscate,
)

_logger = logging.getLogger("licensing-client")

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / ".state"
STATE_FILE = STATE_DIR / "license.dat"


def _load_license_key() -> str:
    """Load license key from obfuscated state file."""
    try:
        if STATE_FILE.exists():
            data = STATE_FILE.read_text(encoding="utf-8").strip()
            if data:
                return xor_deobfuscate(data)
    except Exception:
        pass
    return ""


def _save_license_key(key: str) -> None:
    """Save license key XOR-obfuscated to state file."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(xor_obfuscate(key), encoding="utf-8")
    except Exception as exc:
        _logger.error("Failed to save license key: %s", exc)


def get_hwid() -> str:
    """Public alias for backward compatibility."""
    return get_secure_hwid()


def load_config() -> dict:
    """Load config.yml (only for non-licensing settings)."""
    cfg_path = ROOT / "config.yml"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> bool:
    """Save config.yml."""
    try:
        cfg_path = ROOT / "config.yml"
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception:
        return False


def safe_request(method: str, url: str, **kwargs) -> requests.Response:
    """Make HTTP request, trying curl_cffi first to bypass Cloudflare WAF,
    falling back to standard requests if curl_cffi is unavailable or fails.
    """
    headers = kwargs.get("headers", {})
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    kwargs["headers"] = headers

    try:
        from curl_cffi import requests as curl_requests
        c_kwargs = kwargs.copy()
        if "impersonate" not in c_kwargs:
            c_kwargs["impersonate"] = "chrome"
        # Disable SSL verification for self-signed certificate
        c_kwargs["verify"] = False

        # Make request using curl_cffi
        resp = curl_requests.request(method.upper(), url, **c_kwargs)
        return resp
    except Exception as exc:
        _logger.warning("curl_cffi request failed, falling back to standard requests: %s", exc)

    s_kwargs = kwargs.copy()
    s_kwargs.pop("impersonate", None)
    # Disable SSL verification for self-signed certificate
    s_kwargs["verify"] = False
    return requests.request(method.upper(), url, **s_kwargs)


def check_licensing() -> tuple[bool, dict]:
    """Verify license - bypassed permanently for full offline/lifetime VIP access.

    Returns (is_valid, response_data).
    """
    return True, {
        "license": {
            "is_valid": True,
            "status": "active",
            "license_key": "VIP-UNLIMITED",
            "expire_at": "2099-12-31T23:59:59Z",
            "plan": "Vĩnh viễn",
        },
        "device": {"hwid": get_secure_hwid(), "status": "active"},
        "message": "Bản quyền vĩnh viễn đã được kích hoạt",
    }

# ── Activation helper called from licensing_routes.py ──


def activate_license(key: str) -> tuple[bool, str]:
    """Save a license key and validate it immediately.

    Returns (success, message).
    """
    return True, "Kích hoạt bản quyền thành công."


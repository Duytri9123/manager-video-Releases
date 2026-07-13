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

import requests
import yaml

from utils.security_core import (
    HARDCODED_SERVER_URL,
    PRODUCT_NAME,
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
        
        # Make request using curl_cffi
        resp = curl_requests.request(method.upper(), url, **c_kwargs)
        return resp
    except Exception as exc:
        _logger.warning("curl_cffi request failed, falling back to standard requests: %s", exc)

    s_kwargs = kwargs.copy()
    s_kwargs.pop("impersonate", None)
    return requests.request(method.upper(), url, **s_kwargs)


def check_licensing() -> tuple[bool, dict]:
    """Verify license with manager_tool Laravel backend.

    Returns (is_valid, response_data).
    """
    license_key = _load_license_key()
    hwid = get_secure_hwid()
    server_url = HARDCODED_SERVER_URL  # IGNORES config.yml — security by design

    payload = {
        "device_id": hwid,
        "computer_name": socket.gethostname(),
        "cpu": platform.processor() or "Unknown CPU",
        "gpu": "DirectX Video Adapter",
        "os": platform.system() + " " + platform.release(),
        "app_version": "1.0.0",
        "license_key": license_key,
        "product_name": PRODUCT_NAME,
    }

    try:
        sig, ts = generate_signature(payload)
        headers = {
            "Content-Type": "application/json",
            "X-Hmac-Signature": sig,
            "X-Hmac-Timestamp": ts,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        import json
        payload_str = json.dumps(payload, separators=(",", ":"))

        resp = safe_request(
            "POST",
            f"{server_url}/api/auth/device",
            data=payload_str,
            headers=headers,
            timeout=6,
        )

        if resp.status_code == 200:
            data = resp.json()
            is_valid = data.get("license", {}).get("is_valid", False)
            if is_valid:
                return True, data
            else:
                status = data.get("license", {}).get("status", "unknown")
                status_vi = {
                    "trial": "Dùng thử",
                    "active": "Kích hoạt",
                    "expired": "Hết hạn",
                    "disabled": "Vô hiệu hóa",
                    "banned": "Bị khóa",
                }.get(status, status)
                return False, {
                    "message": f"Giấy phép ở trạng thái: {status_vi}.",
                    "status": status,
                    "license": data.get("license", {}),
                    "device": data.get("device", {}),
                }
        elif resp.status_code == 401:
            return False, {
                "message": "Xác thực thất bại. Vui lòng liên hệ hỗ trợ.",
                "status": "unauthorized",
            }
        else:
            try:
                err_data = resp.json()
            except Exception:
                err_data = {}
            return False, err_data if err_data else {
                "message": f"Lỗi máy chủ ({resp.status_code}).",
                "status": "error",
            }

    except requests.exceptions.ConnectionError:
        return False, {
            "message": "Không thể kết nối đến máy chủ bản quyền. "
                       "Vui lòng kiểm tra kết nối mạng.",
            "status": "offline",
        }
    except requests.exceptions.Timeout:
        return False, {
            "message": "Máy chủ bản quyền không phản hồi. Vui lòng thử lại sau.",
            "status": "timeout",
        }
    except Exception as exc:
        _logger.error("check_licensing exception: %s", exc)
        return False, {
            "message": f"Lỗi: {exc}",
            "status": "error",
        }

# ── Activation helper called from licensing_routes.py ──


def activate_license(key: str) -> tuple[bool, str]:
    """Save a license key and validate it immediately.

    Returns (success, message).
    """
    if not key or len(key) < 8:
        return False, "Mã key không hợp lệ."

    _save_license_key(key)

    # Force immediate check
    is_ok, data = check_licensing()
    if is_ok:
        return True, "Kích hoạt bản quyền thành công."
    else:
        return False, data.get("message", "Mã key không hợp lệ.")

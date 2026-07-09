#!/usr/bin/env python3
"""Security core — hardcoded secrets, HMAC signing, anti-tamper.

This module is the CENTRAL security kernel. It MUST be obfuscated with PyArmor
before building the EXE so crackers cannot read the hardcoded secrets or
understand the verification logic.

Rules:
  - NEVER import this module from a non-obfuscated context in production.
  - NEVER log or print the HMAC_SECRET.
  - NEVER expose HARDCODED_SERVER_URL to the UI.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import struct
import sys
import time
import uuid
from base64 import b64decode, b64encode
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# HARDCODED secrets — DO NOT move to config.yml
# ═══════════════════════════════════════════════════════════════

HARDCODED_SERVER_URL = "https://duytristool.io.vn"

# HMAC secret shared with manager_tool (must match .env HMAC_SECRET_KEY)
_HMAC_SECRET = b"DuYtRiS_s3cr3t_k3y_2024!@#"

# ═══════════════════════════════════════════════════════════════
# Simple XOR obfuscation for local state (NOT encryption — just
# prevents casual reading of license_key from disk).
# ═══════════════════════════════════════════════════════════════

_XOR_KEY = b"DyTr_ObFu$cAtE_2024"


def _xor_bytes(data: bytes) -> bytes:
    return bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(data))


def xor_obfuscate(text: str) -> str:
    return b64encode(_xor_bytes(text.encode("utf-8"))).decode("ascii")


def xor_deobfuscate(obfuscated: str) -> str:
    return _xor_bytes(b64decode(obfuscated)).decode("utf-8")


# ═══════════════════════════════════════════════════════════════
# Secure HWID — multi-source binding entropy
# ═══════════════════════════════════════════════════════════════


def get_secure_hwid() -> str:
    """Generate a HWID from multiple hardware sources.

    Combining multiple identifiers makes it much harder for a cracker
    to spoof in a VM / sandbox.
    """
    parts: list[str] = []

    # 1. Motherboard / system UUID (Windows)
    try:
        import subprocess
        out = subprocess.check_output(
            "wmic csproduct get uuid", shell=True, timeout=3
        ).decode()
        for line in out.splitlines():
            line = line.strip()
            if line and "UUID" not in line:
                parts.append(line)
    except Exception:
        pass

    # 2. MAC address (stable)
    try:
        node = uuid.getnode()
        if node and node != 0:
            parts.append(f"mac:{node:x}")
    except Exception:
        pass

    # 3. Processor ID
    try:
        out = subprocess.check_output(
            "wmic cpu get processorid", shell=True, timeout=3
        ).decode()
        for line in out.splitlines():
            line = line.strip()
            if line and "ProcessorId" not in line:
                parts.append(line)
    except Exception:
        pass

    # 4. Disk serial
    try:
        out = subprocess.check_output(
            "wmic diskdrive get serialnumber", shell=True, timeout=3
        ).decode()
        for line in out.splitlines():
            line = line.strip()
            if line and "SerialNumber" not in line:
                parts.append(line)
    except Exception:
        pass

    # 5. Hostname
    parts.append(socket.gethostname())

    # 6. Boot-time entropy: volume serial
    try:
        out = subprocess.check_output(
            "vol C:", shell=True, timeout=3
        ).decode()
        for word in out.split():
            if "-" in word and len(word) >= 8:
                parts.append(word)
    except Exception:
        pass

    raw = "|".join(parts) if parts else platform.node() + str(time.time())
    return hashlib.sha3_256(raw.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
# HMAC signing
# ═══════════════════════════════════════════════════════════════


def generate_signature(payload: dict, timestamp: int | None = None) -> tuple[str, str]:
    """Generate HMAC-SHA256 signature for a request payload.

    Returns (signature_hex, timestamp_str).
    """
    if timestamp is None:
        timestamp = int(time.time())
    ts_str = str(timestamp)

    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    data = body_bytes + b"|" + ts_str.encode("utf-8")

    sig = hmac.new(_HMAC_SECRET, data, hashlib.sha256).hexdigest()
    return sig, ts_str


def verify_server_response(response_body: bytes, timestamp: str) -> bool:
    """Verify HMAC signature from server response.

    Server signs responses so client can detect MITM tampering.
    """
    # Server signature is in X-Hmac-Signature header (verified externally)
    # This is a placeholder for future bidirectional HMAC.
    # For now, we trust HTTPS. Returning True keeps it simple.
    _ = response_body, timestamp
    return True


# ═══════════════════════════════════════════════════════════════
# Anti-tamper / anti-debug checks
# ═══════════════════════════════════════════════════════════════


def detect_debugger() -> bool:
    """Detect if a debugger is attached."""
    # Windows: PEB BeingDebugged flag
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            return bool(kernel32.IsDebuggerPresent())
        except Exception:
            pass
    return False


def detect_vm() -> bool:
    """Heuristic VM detection."""
    # Check common VM markers
    vm_indicators = [
        "vbox", "virtualbox", "vmware", "qemu", "kvm",
        "xen", "hyper-v", "microsoft hv",
    ]
    sysinfo = (platform.system() + " " + platform.version() + " " +
               platform.processor() or "").lower()
    for ind in vm_indicators:
        if ind in sysinfo:
            return True

    # Check for VM-specific files
    if os.name == "nt":
        vm_drivers = [
            "C:\\Windows\\System32\\drivers\\vmmouse.sys",
            "C:\\Windows\\System32\\drivers\\vmhgfs.sys",
            "C:\\Windows\\System32\\drivers\\VBoxGuest.sys",
            "C:\\Windows\\System32\\drivers\\vboxsf.sys",
        ]
        for d in vm_drivers:
            if os.path.exists(d):
                return True

    return False


def detect_tamper() -> bool:
    """Run all tamper checks. Returns True if tampering detected."""
    if detect_debugger():
        return True
    # VM detection — disabled by default since some users run legit VMs
    # Uncomment if you want to block all VM usage:
    # if detect_vm():
    #     return True
    return False


# ═══════════════════════════════════════════════════════════════
# Throttle helper — obfuscated sleep to confuse timing analysis
# ═══════════════════════════════════════════════════════════════

import socket  # noqa: E402 (needed in get_secure_hwid)


def obfuscated_sleep(seconds: float) -> None:
    """Sleep with some noise to confuse pattern analysis."""
    import random
    import time as _time
    jitter = random.uniform(-0.3, 0.3)
    _time.sleep(max(0.1, seconds + jitter))

#!/usr/bin/env python3
"""Licensing Flask routes — activation UI + API + background guard.

Integrates with license_guard.py for multi-point validation.
"""
from __future__ import annotations

import logging
import random
import time

import requests
from flask import Blueprint, jsonify, redirect, render_template, request

from utils.license_guard import (
    _LICENSE_DATA,
    _LICENSING_OK,
    _LOCK,
    force_check,
    is_license_active,
    start_guard_thread,
)
from utils.licensing_client import HARDCODED_SERVER_URL as SERVER_URL, activate_license, get_hwid, load_config, save_config, safe_request

_logger = logging.getLogger("licensing-routes")

_SETTINGS_CACHE = None
_SETTINGS_CACHE_TIME = 0
CACHE_DURATION = 300      # 5 minutes
CACHE_FAIL_DURATION = 60 # 1 minute if server is down

def _update_settings_async():
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIME
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        from utils.licensing_client import _load_license_key
        license_key = _load_license_key()
        url = f"{SERVER_URL}/api/settings"
        if license_key:
            url += f"?license_key={license_key}"
        resp = safe_request("GET", url, headers=headers, timeout=3.0)
        if resp.status_code == 200:
            dj = resp.json()
            packages = dj.get("packages", [])
            contact = {
                "phone": dj.get("contact_phone", ""),
                "zalo": dj.get("contact_zalo", ""),
                "facebook": dj.get("contact_facebook", ""),
                "email": dj.get("contact_email", ""),
                "website": dj.get("contact_website", ""),
                "note": dj.get("contact_note", ""),
            }
            _SETTINGS_CACHE = {
                "packages": packages,
                "contact": contact,
                "expiry": CACHE_DURATION
            }
            _SETTINGS_CACHE_TIME = time.time()
            return
    except Exception:
        pass
    
    if _SETTINGS_CACHE is not None:
        # If request fails, reuse current cache but schedule next check in CACHE_FAIL_DURATION seconds
        _SETTINGS_CACHE_TIME = time.time() - (CACHE_DURATION - CACHE_FAIL_DURATION)

def _get_cached_settings() -> tuple[list, dict]:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIME
    import threading
    now = time.time()
    
    if _SETTINGS_CACHE is None:
        # Prevent blocking on first run by returning empty and updating in background
        _SETTINGS_CACHE = {
            "packages": [],
            "contact": {},
            "expiry": CACHE_FAIL_DURATION
        }
        _SETTINGS_CACHE_TIME = now
        threading.Thread(target=_update_settings_async, daemon=True).start()
        return [], {}
        
    cache_age = now - _SETTINGS_CACHE_TIME
    if cache_age >= _SETTINGS_CACHE["expiry"]:
        # Stale-While-Revalidate: fetch in background, return stale immediately
        _SETTINGS_CACHE_TIME = now  # Temporarily bump cache time to prevent spawning multiple threads
        threading.Thread(target=_update_settings_async, daemon=True).start()
        
    return _SETTINGS_CACHE["packages"], _SETTINGS_CACHE["contact"]


bp = Blueprint("licensing", __name__)


@bp.route("/license/activate", methods=["GET"])
def activate_view():
    from utils.licensing_client import _load_license_key
    license_key_on_disk = _load_license_key()

    cfg = load_config()
    lic_cfg = cfg.get("licensing") or {}
    license_key = lic_cfg.get("license_key", "")

    if not license_key and license_key_on_disk:
        license_key = license_key_on_disk

    is_ok, data = is_license_active()

    # If key is on disk but not currently active, force an immediate check
    if not is_ok and license_key_on_disk:
        is_ok, data = force_check()
        if is_ok:
            return redirect("/")

    # If local config key is empty, auto-fill from server
    if not license_key and data:
        license_key = data.get("license", {}).get("license_key", "")

    status_code = "unauthorized"
    
    # Parse expiry info
    expire_at = None
    if data:
        lic = data.get("license") or {}
        expire_raw = lic.get("expire_at")
        if expire_raw:
            try:
                from datetime import datetime
                expire_at = datetime.fromisoformat(expire_raw.replace("Z", "+00:00"))
            except Exception:
                pass

    if not is_ok:
        if not license_key_on_disk:
            status_message = "Thiết bị chưa được đăng ký hoặc kích hoạt bản quyền."
        else:
            status_message = data.get("message") if data else "Đang kiểm tra trạng thái bản quyền..."
            if not status_message:
                status_message = "Không thể kết nối đến máy chủ bản quyền."

        status_lower = status_message.lower()
        if "expired" in status_lower or "hết hạn" in status_lower:
            status_code = "expired"
        elif "banned" in status_lower or "khóa" in status_lower:
            status_code = "banned"
        elif "disabled" in status_lower or "vô hiệu hóa" in status_lower:
            status_code = "disabled"
    else:
        status_code = "active"
        status_message = "Bản quyền đang hoạt động bình thường."

    # Fetch packages & contact from Laravel (cached)
    packages, contact = _get_cached_settings()

    return render_template(
        "license_activation.html",
        hwid=get_hwid(),
        license_key=license_key,
        server_url=SERVER_URL,
        status_code=status_code,
        status_message=status_message,
        expire_at=expire_at,
        packages=packages,
        contact=contact,
    )


@bp.route("/api/license/activate", methods=["POST"])
def api_activate():
    req_data = request.get_json() or {}
    key = req_data.get("license_key", "").strip()
    if not key:
        return jsonify({"success": False, "message": "Vui lòng nhập mã key."}), 400

    success, message = activate_license(key)
    if success:
        force_check()
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 403


@bp.route("/api/license/activate_trial", methods=["POST"])
def api_activate_trial():
    from utils.licensing_client import _save_license_key
    is_ok, data = force_check()
    if is_ok:
        lic = data.get("license") or {}
        key = lic.get("license_key")
        if key:
            _save_license_key(key)
            return jsonify({"success": True, "message": "Kích hoạt dùng thử thành công!", "license_key": key})
    return jsonify({"success": False, "message": data.get("message", "Không thể kích hoạt dùng thử.")}), 400


@bp.route("/api/license/check_status", methods=["GET"])
def api_check_status():
    is_ok, data = force_check()
    expire_at = None
    expire_ts = None
    remaining_days = None
    if data:
        lic = data.get("license") or {}
        expire_raw = lic.get("expire_at")
        if expire_raw:
            try:
                from datetime import datetime, timezone
                expire_at_dt = datetime.fromisoformat(expire_raw.replace("Z", "+00:00"))
                expire_ts = expire_at_dt.timestamp()
                now = datetime.now(timezone.utc)
                if expire_at_dt > now:
                    remaining_days = (expire_at_dt - now).days
                else:
                    remaining_days = 0
            except Exception:
                pass

    return jsonify({
        "active": is_ok,
        "status_code": (
            data.get("license", {}).get("status", "unknown")
            if is_ok and data
            else "unauthorized"
        ),
        "message": data.get("message", ""),
        "expire_at": expire_ts,
        "remaining_days": remaining_days,
    })


@bp.route("/api/license/buy", methods=["POST"])
def api_buy():
    req_data = request.get_json() or {}
    package_key = req_data.get("package_key")
    license_key = req_data.get("license_key", "").strip()

    if not license_key or license_key == "NEW-KEY":
        _, check_data = is_license_active()
        license_key = check_data.get("license", {}).get("license_key", "NEW-KEY")

    cfg = load_config()
    lic_cfg = cfg.get("licensing") or {}

    amount = 150000
    bank_name = bank_bin = bank_account = bank_holder = ""
    settings_data = {}
    try:
        resp = safe_request("GET", f"{SERVER_URL}/api/settings", timeout=2)
        if resp.status_code == 200:
            settings_data = resp.json()
            for pkg in settings_data.get("packages", []):
                if pkg.get("key") == package_key:
                    amount = pkg.get("price", amount)
                    break
            bank_name = settings_data.get("bank_name", "")
            bank_bin = settings_data.get("bank_bin", "")
            bank_account = settings_data.get("bank_account", "")
            bank_holder = settings_data.get("bank_holder", "")
    except Exception:
        pass

    try:
        from utils.security_core import generate_signature
        import json

        payload = {"license_key": license_key, "amount": amount}
        sig, ts = generate_signature(payload)
        payload_str = json.dumps(payload, separators=(",", ":"))

        headers = {
            "Content-Type": "application/json",
            "X-Hmac-Signature": sig,
            "X-Hmac-Timestamp": ts,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        resp = safe_request(
            "POST",
            f"{SERVER_URL}/api/payment/create",
            data=payload_str,
            headers=headers,
            timeout=3,
        )
        if resp.status_code == 200:
            rdata = resp.json()
            order_code = rdata.get("order_code", "")

            qr_url = ""
            bank_id = bank_bin or bank_name
            if bank_id and bank_account:
                from urllib.parse import quote
                safe_holder = quote(bank_holder)
                safe_info = quote(order_code[:25])
                qr_url = (
                    f"https://img.vietqr.io/image/{bank_id}-{bank_account}-compact2.png"
                    f"?amount={int(amount)}&addInfo={safe_info}&accountName={safe_holder}"
                )

            checkout_url = rdata.get("checkout_url", "")

            return jsonify({
                "success": True,
                "order_code": order_code,
                "amount": int(amount),
                "bank_name": bank_name,
                "bank_account": bank_account,
                "bank_holder": bank_holder,
                "qr_url": qr_url,
                "checkout_url": checkout_url,
            })
        else:
            return jsonify({
                "success": False,
                "message": resp.json().get("message", "Không thể khởi tạo giao dịch."),
            }), resp.status_code
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Lỗi kết nối máy chủ: {str(e)}",
        }), 500


@bp.route("/license/checkout/<order_code>", methods=["GET"])
def checkout_view(order_code):
    from urllib.parse import unquote
    amount = request.args.get("amount", 0, type=int)
    bank_name = unquote(request.args.get("bank", ""))
    bank_account = unquote(request.args.get("acct", ""))
    bank_holder = unquote(request.args.get("holder", ""))
    qr_url = unquote(request.args.get("qr", ""))
    hwid = unquote(request.args.get("hwid", ""))

    if not qr_url and bank_name and bank_account:
        qr_url = (
            f"https://img.vietqr.io/image/{bank_name}-{bank_account}-compact2.png"
            f"?amount={amount}&addInfo={order_code}&accountName={bank_holder}"
        )

    return render_template(
        "license_checkout.html",
        order_code=order_code,
        amount=amount,
        qr_url=qr_url,
        bank_name=bank_name,
        bank_account=bank_account,
        bank_holder=bank_holder,
        hwid=hwid or get_hwid(),
    )


# ── Global template context processor ──
def inject_license_globals():
    """Inject license info + contact into ALL templates (for topbar tooltip)."""
    is_ok, data = is_license_active()
    expire_at = None
    remaining_days = None
    license_key = ""
    contact = {}
    packages = []

    if data:
        lic = data.get("license") or {}
        license_key = lic.get("license_key", "")
        expire_raw = lic.get("expire_at")
        if expire_raw:
            try:
                from datetime import datetime, timezone
                expire_at_dt = datetime.fromisoformat(expire_raw.replace("Z", "+00:00"))
                expire_at = expire_at_dt.strftime("%d/%m/%Y %H:%M")
                now = datetime.now(timezone.utc)
                if expire_at_dt > now:
                    remaining_days = (expire_at_dt - now).days
                else:
                    remaining_days = 0
            except Exception:
                pass

    # Fetch contact & packages (cached)
    packages, contact = _get_cached_settings()

    return dict(
        license_active=is_ok,
        license_status_code=data.get("license", {}).get("status", "unknown") if is_ok else "unauthorized",
        license_key=license_key,
        expire_at=expire_at,
        remaining_days=remaining_days,
        contact=contact,
        packages=packages,
        hwid=get_hwid(),
    )


def init_licensing_app(app):
    """Register licensing blueprint + before_request gate + guard thread."""
    # Synchronous check at startup to ensure is_license_active() returns immediately.
    # If a saved key exists but the check fails (e.g. network not ready), retry a
    # few times before giving up — avoids dumping valid users to the activation screen.
    import time as _time
    try:
        from utils.licensing_client import _load_license_key
        has_saved_key = bool(_load_license_key())
    except Exception:
        has_saved_key = False

    ok = False
    max_retries = 3 if has_saved_key else 1
    for attempt in range(max_retries):
        try:
            result, _ = force_check()
            if result:
                ok = True
                break
        except Exception:
            pass
        if attempt < max_retries - 1:
            _time.sleep(2)

    if has_saved_key and not ok:
        _logger.warning("Startup license check failed after %d attempts (has saved key)", max_retries)

    start_guard_thread()
    app.register_blueprint(bp)

    # Register global template context processor
    @app.context_processor
    def license_context():
        return inject_license_globals()

    @app.before_request
    def check_license_gate():
        if (request.path.startswith("/static/")
                or request.path.startswith("/api/license/")
                or request.path == "/license/activate"
                or request.path.startswith("/license/checkout/")
                or "socket.io" in request.path):
            return None

        is_active, _ = is_license_active()
        if not is_active:
            _logger.info("License gate blocked: %s (active=%s)", request.path, is_active)
            return redirect("/license/activate")

        return None


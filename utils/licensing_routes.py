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
from utils.licensing_client import HARDCODED_SERVER_URL as SERVER_URL, activate_license, get_hwid, load_config, save_config

_logger = logging.getLogger("licensing-routes")

bp = Blueprint("licensing", __name__)


@bp.route("/license/activate", methods=["GET"])
def activate_view():
    cfg = load_config()
    lic_cfg = cfg.get("licensing") or {}
    license_key = lic_cfg.get("license_key", "")

    is_ok, data = is_license_active()

    # If local config key is empty, auto-fill from server
    if not license_key and data:
        license_key = data.get("license", {}).get("license_key", "")

    status_code = "unauthorized"
    status_message = "Thiết bị chưa được đăng ký hoặc kích hoạt bản quyền."

    if not is_ok:
        status_message = data.get("message", "Không thể kết nối đến máy chủ bản quyền.")
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

    # Fetch packages & contact from Laravel
    packages = []
    contact = {}
    try:
        # HMAC exempt on settings (GET, public)
        resp = requests.get(f"{SERVER_URL}/api/settings", timeout=2.5)
        if resp.status_code == 200:
            data_json = resp.json()
            packages = data_json.get("packages", [])
            contact = {
                "phone": data_json.get("contact_phone", ""),
                "zalo": data_json.get("contact_zalo", ""),
                "facebook": data_json.get("contact_facebook", ""),
                "email": data_json.get("contact_email", ""),
                "website": data_json.get("contact_website", ""),
                "note": data_json.get("contact_note", ""),
            }
    except Exception:
        pass

    return render_template(
        "license_activation.html",
        hwid=get_hwid(),
        license_key=license_key,
        server_url=SERVER_URL,
        status_code=status_code,
        status_message=status_message,
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
        # Clear guard cache to force re-check
        force_check()
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "message": message}), 403


@bp.route("/api/license/check_status", methods=["GET"])
def api_check_status():
    # Bypass cache — force real check
    is_ok, data = force_check()

    return jsonify({
        "active": is_ok,
        "status_code": (
            data.get("license", {}).get("status", "unknown")
            if is_ok and data
            else "unauthorized"
        ),
        "message": data.get("message", ""),
    })


@bp.route("/api/license/buy", methods=["POST"])
def api_buy():
    req_data = request.get_json() or {}
    package_key = req_data.get("package_key")
    license_key = req_data.get("license_key", "").strip()

    # Resolve key from server if empty
    if not license_key or license_key == "NEW-KEY":
        _, check_data = is_license_active()
        license_key = check_data.get("license", {}).get("license_key", "NEW-KEY")

    cfg = load_config()
    lic_cfg = cfg.get("licensing") or {}

    # Fetch packages + bank info
    amount = 150000
    bank_name = bank_bin = bank_account = bank_holder = ""
    settings_data = {}
    try:
        resp = requests.get(f"{SERVER_URL}/api/settings", timeout=2)
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

    # Create order on Laravel
    try:
        payload = {"license_key": license_key, "amount": amount}
        resp = requests.post(
            f"{SERVER_URL}/api/payment/create",
            json=payload,
            timeout=3,
        )
        if resp.status_code == 200:
            rdata = resp.json()
            order_code = rdata.get("order_code", "")

            # VietQR URL
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

            payment_gateway = settings_data.get("payment_gateway", "vietqr_only")
            if payment_gateway in ["sepay", "payos"]:
                checkout_url = rdata.get("checkout_url", "")
                if checkout_url:
                    return jsonify({"success": True, "checkout_url": checkout_url})

            from urllib.parse import urlencode
            params = urlencode({
                "amount": int(amount),
                "bank": bank_name,
                "bin": bank_bin,
                "acct": bank_account,
                "holder": bank_holder,
                "qr": qr_url,
            })
            return jsonify({
                "success": True,
                "checkout_url": f"/license/checkout/{order_code}?{params}",
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
    )


def init_licensing_app(app):
    """Register licensing blueprint + before_request gate + guard thread."""
    # Start the background guard
    start_guard_thread()

    # Register blueprint
    app.register_blueprint(bp)

    # Before-request gate — multi-point check #1
    @app.before_request
    def check_license_gate():
        # Allowlist
        if (request.path.startswith("/static/")
                or request.path.startswith("/api/license/")
                or request.path == "/license/activate"
                or request.path.startswith("/license/checkout/")
                or "socket.io" in request.path):
            return None

        # Check license state (cached)
        is_active, _ = is_license_active()
        if not is_active:
            _logger.info(
                "License gate blocked: %s (active=%s)",
                request.path, is_active,
            )
            return redirect("/license/activate")

        return None

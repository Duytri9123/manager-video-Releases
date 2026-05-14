"""Accounts Blueprint — Multi-account management for YouTube & Facebook."""
import json
from flask import Blueprint, jsonify, request
from auth.account_manager import (
    get_youtube_account_manager,
    get_facebook_account_manager,
)

bp = Blueprint("accounts", __name__)


# ── YouTube Accounts ──────────────────────────────────────────────────────────

@bp.route("/api/accounts/youtube", methods=["GET"])
def youtube_list_accounts():
    """List all YouTube accounts."""
    mgr = get_youtube_account_manager()
    accounts = mgr.list_accounts()
    active = mgr.get_active_account()
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "active_id": active["id"] if active else None,
    })


@bp.route("/api/accounts/youtube/active", methods=["POST"])
def youtube_set_active():
    """Set active YouTube account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_youtube_account_manager()
    if mgr.set_active_account(account_id):
        # Reset the YouTube uploader singleton to use new account
        from core_app import _reset_youtube_uploader
        _reset_youtube_uploader()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/youtube/remove", methods=["POST"])
def youtube_remove_account():
    """Remove a YouTube account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_youtube_account_manager()
    if mgr.remove_account(account_id):
        from core_app import _reset_youtube_uploader
        _reset_youtube_uploader()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/youtube/migrate", methods=["POST"])
def youtube_migrate():
    """Migrate existing single-account token to multi-account system."""
    mgr = get_youtube_account_manager()
    mgr.migrate_existing_token()
    accounts = mgr.list_accounts()
    return jsonify({"ok": True, "accounts": accounts})


# ── Facebook Accounts ─────────────────────────────────────────────────────────

@bp.route("/api/accounts/facebook", methods=["GET"])
def facebook_list_accounts():
    """List all Facebook accounts."""
    mgr = get_facebook_account_manager()
    accounts = mgr.list_accounts()
    active = mgr.get_active_account()
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "active_id": active["id"] if active else None,
    })


@bp.route("/api/accounts/facebook/connect", methods=["POST"])
def facebook_add_account():
    """Add a new Facebook account with access token."""
    import urllib.request
    import urllib.parse
    import urllib.error

    data = request.json or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Thiếu access token"}), 400

    # Validate token and get user info
    FB_API = "https://graph.facebook.com/v25.0"
    try:
        url = f"{FB_API}/me?access_token={urllib.parse.quote(token)}&fields=id,name,picture"
        with urllib.request.urlopen(url, timeout=15) as r:
            user_data = json.loads(r.read().decode())
    except Exception as e:
        return jsonify({"ok": False, "error": f"Token không hợp lệ: {e}"}), 400

    user_id = user_data.get("id", "")
    user_name = user_data.get("name", "Unknown")
    profile_pic = (user_data.get("picture", {}).get("data", {}).get("url", ""))

    # Get pages
    pages = []
    try:
        url = f"{FB_API}/me/accounts?access_token={urllib.parse.quote(token)}&fields=id,name,access_token,picture"
        with urllib.request.urlopen(url, timeout=15) as r:
            pages_data = json.loads(r.read().decode())
        for p in pages_data.get("data", []):
            pages.append({
                "id": p["id"],
                "name": p.get("name", ""),
                "access_token": p.get("access_token", ""),
                "picture": (p.get("picture", {}).get("data", {}).get("url", "")),
            })
    except Exception:
        pass

    mgr = get_facebook_account_manager()
    account = mgr.add_account(
        account_id=user_id,
        name=user_name,
        token=token,
        pages=pages,
        profile_pic=profile_pic,
    )

    return jsonify({
        "ok": True,
        "account": account,
        "pages": pages,
    })


@bp.route("/api/accounts/facebook/active", methods=["POST"])
def facebook_set_active():
    """Set active Facebook account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_facebook_account_manager()
    if mgr.set_active_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/facebook/remove", methods=["POST"])
def facebook_remove_account():
    """Remove a Facebook account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_facebook_account_manager()
    if mgr.remove_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/facebook/migrate", methods=["POST"])
def facebook_migrate():
    """Migrate existing single-account token to multi-account system."""
    mgr = get_facebook_account_manager()
    mgr.migrate_existing_token()
    accounts = mgr.list_accounts()
    return jsonify({"ok": True, "accounts": accounts})


# ── Hardware Info (bonus: expose hardware detection to UI) ────────────────────

@bp.route("/api/hardware_info", methods=["GET"])
def hardware_info():
    """Get detected hardware info and selected FFmpeg preset."""
    try:
        from core.hardware_presets import get_hardware_info, get_all_presets
        from core.video_processor import find_ffmpeg
        ffmpeg = find_ffmpeg()
        info = get_hardware_info(ffmpeg)
        presets = get_all_presets()
        return jsonify({"ok": True, "hardware": info, "available_presets": presets})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

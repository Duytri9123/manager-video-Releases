"""Accounts Blueprint — Multi-account management for YouTube, Facebook, TikTok & Douyin."""
import asyncio
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request
from auth.account_manager import (
    ROOT,
    get_youtube_account_manager,
    get_facebook_account_manager,
    get_tiktok_account_manager,
    get_douyin_account_manager,
)
from utils.cookie_utils import parse_cookie_header
from auth.session_validation import has_authenticated_session

logger = logging.getLogger(__name__)

bp = Blueprint("accounts", __name__)


@bp.route('/api/accounts/saved_sessions', methods=['GET'])
def saved_sessions():
    """Report saved credentials per account without exposing cookie or token values."""
    from templates.pages.publish.tiktok import _has_login_cookies
    from templates.pages.publish.facebook_browser import _profile as fb_browser_profile
    result = {'youtube': {}, 'facebook': {}, 'tiktok': {}, 'douyin': {}}
    yt = get_youtube_account_manager()
    for account in yt.list_accounts():
        aid = str(account['id'])
        oauth_saved = yt.get_token_path(aid).is_file() or yt.get_token_json_path(aid).is_file()
        result['youtube'][aid] = {'saved': oauth_saved, 'method': 'OAuth'}
    tt = get_tiktok_account_manager()
    for account in tt.list_accounts():
        aid = str(account['id'])
        result['tiktok'][aid] = {'saved': _has_login_cookies(tt.get_profile_dir(aid)), 'method': 'Trình duyệt'}
    fb = get_facebook_account_manager()
    for account in fb.list_accounts():
        aid = str(account['id'])
        token_saved = bool(fb.get_token(aid).get('access_token'))
        browser_saved = (fb_browser_profile(aid) / '.connected').is_file()
        result['facebook'][aid] = {'saved': token_saved or browser_saved,
                                   'method': 'Graph API' if token_saved else 'Trình duyệt' if browser_saved else ''}
    dy = get_douyin_account_manager()
    for account in dy.list_accounts():
        aid = str(account['id'])
        try:
            cookies = json.loads((dy.accounts_dir / f'{aid}.json').read_text(encoding='utf-8'))
            saved = bool(cookies)
        except (OSError, ValueError):
            saved = False
        result['douyin'][aid] = {'saved': saved, 'method': 'Cookie'}
    return jsonify({'ok': True, 'sessions': result})


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


@bp.route("/api/accounts/youtube/refresh_info", methods=["POST"])
def youtube_refresh_info():
    """Fetch real channel name/thumbnail from YouTube API and update accounts registry.
    Call this after OAuth login to replace 'YouTube (default)' with the real channel name.
    """
    from core_app import _get_youtube_uploader
    try:
        uploader = _get_youtube_uploader()
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Chưa đăng nhập YouTube"}), 401

        channel = uploader.get_channel_info()
        if not channel or not channel.get("title"):
            return jsonify({"ok": False, "error": "Không lấy được thông tin kênh"}), 500

        mgr = get_youtube_account_manager()
        account_id = getattr(uploader, "_account_id", None) or channel.get("id") or "default"
        account = mgr.add_account(
            account_id=account_id,
            name=channel["title"],
            channel_id=channel.get("id", ""),
            channel_title=channel["title"],
            thumbnail=channel.get("thumbnail", ""),
        )
        return jsonify({
            "ok": True,
            "account": account,
            "channel": channel,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


# ── TikTok Accounts ───────────────────────────────────────────────────────────

@bp.route("/api/accounts/tiktok", methods=["GET"])
def tiktok_list_accounts():
    """List all TikTok accounts."""
    mgr = get_tiktok_account_manager()
    accounts = mgr.list_accounts()
    active = mgr.get_active_account()
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "active_id": active["id"] if active else None,
    })


@bp.route("/api/accounts/tiktok/active", methods=["POST"])
def tiktok_set_active():
    """Set active TikTok account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_tiktok_account_manager()
    if mgr.set_active_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/tiktok/remove", methods=["POST"])
def tiktok_remove_account():
    """Remove a TikTok account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_tiktok_account_manager()
    if mgr.remove_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/tiktok/add", methods=["POST"])
def tiktok_add_account():
    """Manually add or edit a TikTok account."""
    data = request.json or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Thiếu tên tài khoản"}), 400
    account_id = str(data.get("account_id") or "").strip() or f"tt_{uuid.uuid4().hex[:8]}"
    username = str(data.get("username") or "").strip()
    avatar = str(data.get("avatar") or "").strip()
    mgr = get_tiktok_account_manager()
    account = mgr.add_account(account_id, name, username=username, avatar=avatar)
    return jsonify({"ok": True, "account": account})


@bp.route("/api/accounts/tiktok/login", methods=["POST"])
def tiktok_open_login_account():
    """Mở trình duyệt để đăng nhập một tài khoản TikTok mới (hoặc cập nhật account cụ thể)."""
    data = request.json or {}
    account_name = str(data.get("account_name") or "").strip()
    account_id = str(data.get("account_id") or "").strip() or f"tt_{uuid.uuid4().hex[:8]}"
    if not account_name:
        account_name = f"TikTok {account_id[-4:]}"

    mgr = get_tiktok_account_manager()
    profile_dir = mgr.get_profile_dir(account_id)

    # Use tiktok.py session system
    from templates.pages.publish.tiktok import (
        _new_session, _sessions, _sessions_lock, _log, _set_status,
        _cleanup_profile_locks, _load_tiktok_state, _save_tiktok_state,
        TIKTOK_UPLOAD_URL,
    )
    from playwright.async_api import async_playwright

    sid = "tt-login-" + uuid.uuid4().hex[:8]
    with _sessions_lock:
        _sessions[sid] = _new_session()

    _log(sid, f"Mở trình duyệt đăng nhập TikTok: {account_name}")

    async def _login_task():
        profile_dir.mkdir(parents=True, exist_ok=True)
        _cleanup_profile_locks(profile_dir)
        _set_status(sid, "launching")
        stop_event = _sessions[sid]["stop_event"]

        async with async_playwright() as pw:
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **_account_browser_options(),
                    headless=False,
                    viewport={"width": 1440, "height": 900},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
            except Exception as exc:
                _set_status(sid, "error", error=f"Không mở được trình duyệt: {exc}", done=True)
                return

            with _sessions_lock:
                _sessions[sid]["_context"] = context

            try:
                await _load_tiktok_state(context, profile_dir, sid)
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
                except Exception as exc:
                    _log(sid, f"Goto chậm: {exc}", "warning")

                _set_status(sid, "waiting_login")
                _log(sid, "Đăng nhập trong trình duyệt. Hệ thống chỉ lưu khi có phiên đăng nhập hợp lệ.", "info")
                authenticated = False
                deadline = time.time() + 600
                while time.time() < deadline and not stop_event.is_set():
                    if page.is_closed():
                        break
                    cookies = await context.cookies("https://www.tiktok.com")
                    authenticated = has_authenticated_session(cookies, "tiktok.com")
                    if authenticated:
                        break
                    await asyncio.sleep(1.5)
                if not authenticated:
                    _set_status(sid, "error", error="Chưa đăng nhập TikTok; chưa lưu tài khoản", done=True)
                    return

                _log(sid, "Đăng nhập thành công! Đang lưu phiên...", "success")
                await asyncio.sleep(2)
                await _save_tiktok_state(context, profile_dir, sid)

                # Try to extract user info
                extracted_name = account_name
                username = ""
                avatar = ""
                try:
                    for sel in ['[data-e2e="user-title"]', '.user-title', '.avatar-wrapper + div']:
                        el = await page.query_selector(sel)
                        if el:
                            txt = (await el.inner_text()).strip()
                            if txt:
                                extracted_name = txt
                                username = txt
                                break
                    img_el = await page.query_selector('img[class*="avatar" i], [data-e2e="user-avatar"]')
                    if img_el:
                        src = await img_el.get_attribute("src")
                        if src:
                            avatar = src
                except Exception:
                    pass

                mgr.add_account(
                    account_id=account_id,
                    name=extracted_name,
                    username=username,
                    avatar=avatar,
                    profile_dir=str(profile_dir),
                )
                mgr.set_active_account(account_id)
                _set_status(sid, "ready", done=True)
                _log(sid, f"Đã lưu tài khoản: {extracted_name}", "success")
            finally:
                try:
                    await _save_tiktok_state(context, profile_dir, sid)
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass

    def _runner():
        try:
            asyncio.run(_login_task())
        except Exception as exc:
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"Lỗi: {exc}", "error")

    threading.Thread(target=_runner, daemon=True).start()
    return jsonify({"ok": True, "session_id": sid, "account_id": account_id})


# ── Douyin Accounts ───────────────────────────────────────────────────────────

@bp.route("/api/accounts/douyin", methods=["GET"])
def douyin_list_accounts():
    """List all Douyin accounts."""
    mgr = get_douyin_account_manager()
    accounts = mgr.list_accounts()
    active = mgr.get_active_account()
    return jsonify({
        "ok": True,
        "accounts": accounts,
        "active_id": active["id"] if active else None,
    })


@bp.route("/api/accounts/douyin/active", methods=["POST"])
def douyin_set_active():
    """Set active Douyin account and sync its cookies across the system."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_douyin_account_manager()
    if mgr.set_active_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/douyin/remove", methods=["POST"])
def douyin_remove_account():
    """Remove a Douyin account."""
    data = request.json or {}
    account_id = str(data.get("account_id") or "").strip()
    if not account_id:
        return jsonify({"ok": False, "error": "Thiếu account_id"}), 400

    mgr = get_douyin_account_manager()
    if mgr.remove_account(account_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Không tìm thấy tài khoản"}), 404


@bp.route("/api/accounts/douyin/add", methods=["POST"])
def douyin_add_account():
    """Add a Douyin account by pasting raw cookie string or JSON dictionary."""
    data = request.json or {}
    name = str(data.get("name") or "").strip()
    raw = str(data.get("raw") or data.get("cookie_raw") or "").strip()
    cookies = data.get("cookies")

    if not cookies and raw:
        cookies = parse_cookie_header(raw)

    if not cookies or not isinstance(cookies, dict):
        return jsonify({"ok": False, "error": "Không tìm thấy cookie hợp lệ. Vui lòng kiểm tra lại chuỗi cookie hoặc JSON."}), 400

    account_id = str(data.get("account_id") or "").strip() or f"dy_{uuid.uuid4().hex[:8]}"
    if not name:
        name = f"Douyin {account_id[-4:]}"

    mgr = get_douyin_account_manager()
    account = mgr.add_account(
        account_id=account_id,
        name=name,
        cookies=cookies,
        nickname=str(data.get("nickname") or ""),
        avatar=str(data.get("avatar") or ""),
    )
    # Set as active
    mgr.set_active_account(account_id)
    return jsonify({"ok": True, "account": account})


@bp.route("/api/accounts/douyin/login", methods=["POST"])
def douyin_open_login_account():
    """Mở trình duyệt để đăng nhập tài khoản Douyin và tự bắt Cookie lưu vào hồ sơ."""
    data = request.json or {}
    account_name = str(data.get("account_name") or "").strip()
    account_id = str(data.get("account_id") or "").strip() or f"dy_{uuid.uuid4().hex[:8]}"
    if not account_name:
        account_name = f"Douyin {account_id[-4:]}"

    from templates.pages.publish.tiktok import (
        _new_session, _sessions, _sessions_lock, _log, _set_status,
    )
    from playwright.async_api import async_playwright

    sid = "dy-login-" + uuid.uuid4().hex[:8]
    with _sessions_lock:
        _sessions[sid] = _new_session()

    _log(sid, f"Mở trình duyệt đăng nhập Douyin: {account_name}")

    async def _douyin_login_task():
        _set_status(sid, "launching")
        stop_event = _sessions[sid]["stop_event"]

        profile_dir = ROOT / ".accounts" / "douyin_profiles" / account_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as pw:
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    **_account_browser_options(),
                    headless=False,
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
            except Exception as exc:
                _set_status(sid, "error", error=f"Không mở được trình duyệt: {exc}", done=True)
                return

            with _sessions_lock:
                _sessions[sid]["_context"] = context

            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)

                _set_status(sid, "waiting_login")
                _log(sid, "Quét mã QR hoặc đăng nhập bằng SĐT trên cửa sổ Douyin. Hệ thống sẽ tự nhận diện khi đăng nhập xong.", "info")

                deadline = time.time() + 600
                captured = {}
                nickname = ""
                avatar = ""

                while time.time() < deadline and not stop_event.is_set():
                    if page.is_closed():
                        break
                    try:
                        all_cookies = await context.cookies()
                        matched = {
                            c["name"]: c["value"]
                            for c in all_cookies
                            if (c.get("domain") or "").lower().lstrip('.') == "douyin.com" or (c.get("domain") or "").lower().endswith('.douyin.com')
                        }
                        if has_authenticated_session(all_cookies, "douyin.com"):
                            captured = matched
                            try:
                                title = await page.title()
                                if "验证码" not in title:
                                    name_el = await page.query_selector('.avatar-wrapper + div, [class*="user-info"], [class*="account-name"]')
                                    if name_el:
                                        t = (await name_el.inner_text()).strip()
                                        if t:
                                            nickname = t
                                    img_el = await page.query_selector('img[class*="avatar"]')
                                    if img_el:
                                        src = await img_el.get_attribute("src")
                                        if src:
                                            avatar = src
                            except Exception:
                                pass

                            if "sessionid" in matched or "sessionid_ss" in matched:
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                if not captured:
                    _set_status(sid, "error", error="Không bắt được cookie Douyin. Hãy thử lại.", done=True)
                    return

                final_name = nickname or account_name
                mgr = get_douyin_account_manager()
                mgr.add_account(
                    account_id=account_id,
                    name=final_name,
                    cookies=captured,
                    nickname=nickname,
                    avatar=avatar,
                )
                mgr.set_active_account(account_id)
                _log(sid, f"Đã lưu tài khoản Douyin: {final_name} ({len(captured)} cookies)", "success")
                _set_status(sid, "ready", done=True)
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

    def _runner():
        try:
            asyncio.run(_douyin_login_task())
        except Exception as exc:
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"Lỗi: {exc}", "error")

    threading.Thread(target=_runner, daemon=True).start()
    return jsonify({"ok": True, "session_id": sid, "account_id": account_id})


@bp.route("/api/accounts/migrate", methods=["POST"])
def accounts_migrate_all():
    """Migrate all platforms (YouTube, Facebook, TikTok, Douyin)."""
    get_youtube_account_manager().migrate_existing_token()
    get_facebook_account_manager().migrate_existing_token()
    get_tiktok_account_manager().migrate_existing()
    get_douyin_account_manager().migrate_existing()
    return jsonify({
        "ok": True,
        "youtube": get_youtube_account_manager().list_accounts(),
        "facebook": get_facebook_account_manager().list_accounts(),
        "tiktok": get_tiktok_account_manager().list_accounts(),
        "douyin": get_douyin_account_manager().list_accounts(),
    })


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


def _account_browser_options():
    import os
    for base, relative in [(os.environ.get('PROGRAMFILES', ''), 'Google/Chrome/Application/chrome.exe'),
                           (os.environ.get('PROGRAMFILES(X86)', ''), 'Microsoft/Edge/Application/msedge.exe'),
                           (os.environ.get('LOCALAPPDATA', ''), 'Google/Chrome/Application/chrome.exe')]:
        if base and (Path(base) / relative).is_file():
            return {"executable_path": str(Path(base) / relative)}
    return {}

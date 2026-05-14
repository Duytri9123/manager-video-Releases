"""Facebook Blueprint — Graph API integration for page management and video publishing."""
import json as _j
import os
import tempfile
import shutil
import subprocess
from pathlib import Path
from flask import Blueprint, jsonify, request, Response, stream_with_context
from core_app import ROOT, load_cfg, save_cfg

bp = Blueprint("facebook", __name__)

FB_API_BASE = "https://graph.facebook.com/v25.0"
FB_TOKEN_FILE = ROOT / ".facebook_token.json"

# Facebook error codes that indicate the user must re-authenticate OR
# re-request permissions (which also requires a new token with those scopes).
# https://developers.facebook.com/docs/graph-api/guides/error-handling/
FB_TOKEN_ERROR_CODES = {190, 102, 463, 467}
# Code 100 = "No permission to publish the video" / missing scope → need new token
# Code 200 = "Requires extended permission" → need new token
FB_PERMISSION_ERROR_CODES = {100, 200, 10}
FB_TOKEN_ERROR_SUBCODES = {458, 460, 463, 464, 467, 493}


def _is_token_error(err: dict) -> bool:
    """Detect if a Graph API error is a token / auth / permission problem
    that the user can fix by pasting a new token with the right scopes."""
    if not err:
        return False
    try:
        code = int(err.get("code", 0))
        subcode = int(err.get("error_subcode", 0) or 0)
        msg = str(err.get("message", "")).lower()
    except Exception:
        return False
    if code in FB_TOKEN_ERROR_CODES:
        return True
    if code in FB_PERMISSION_ERROR_CODES:
        return True
    if subcode in FB_TOKEN_ERROR_SUBCODES:
        return True
    if any(s in msg for s in (
        "access token", "session", "expired", "invalidated", "checkpoint",
        "permissions", "login required", "password", "oauth",
        "no permission", "publish_video", "pages_manage_posts",
    )):
        return True
    return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def _load_fb_token() -> dict:
    """Load saved Facebook token data."""
    try:
        if FB_TOKEN_FILE.exists():
            return _j.loads(FB_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_fb_token(data: dict):
    """Save Facebook token data."""
    try:
        FB_TOKEN_FILE.write_text(_j.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _clear_fb_token():
    try:
        if FB_TOKEN_FILE.exists():
            FB_TOKEN_FILE.unlink()
    except Exception:
        pass


def _resolve_page_token(td: dict, page_id: str) -> tuple[str, str]:
    """Return (page_token, error_message). Guarantees the token belongs to a
    PAGE — not the user — so video/post is published on the Page, not on the
    user's personal timeline.
    """
    if not page_id:
        return "", "Thiếu page_id"
    user_id = str(td.get("user_id") or "").strip()
    if user_id and page_id == user_id:
        return "", (
            "page_id trùng với user_id. Đây là token của tài khoản cá nhân, "
            "không phải Page. Hãy chọn một Page trong danh sách."
        )
    for p in td.get("pages", []) or []:
        if str(p.get("id")) != page_id:
            continue
        page_token = str(p.get("access_token") or "").strip()
        if not page_token:
            return "", "Page không có access_token — hãy kết nối lại Facebook."
        # Ensure it's truly a PAGE token (not the user's token copy)
        user_token = str(td.get("user_token") or "").strip()
        if user_token and page_token == user_token:
            return "", (
                "Token của Page trùng với User token. Graph API sẽ đăng vào "
                "timeline cá nhân. Hãy kết nối lại để lấy đúng Page token "
                "(cần quyền pages_manage_posts + pages_show_list)."
            )
        return page_token, ""
    return "", "Không tìm thấy page_id trong danh sách Page đã kết nối."


def _fb_get(path: str, token: str, params: dict = None) -> dict:
    """Make a GET request to Facebook Graph API."""
    import urllib.request
    import urllib.parse
    import urllib.error
    p = {"access_token": token}
    if params:
        p.update(params)
    url = f"{FB_API_BASE}/{path}?{urllib.parse.urlencode(p)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return _j.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Read the error body — Facebook puts the real error message here
        try:
            body = _j.loads(e.read().decode())
            return {"error": body.get("error", {"message": str(e), "code": e.code})}
        except Exception:
            return {"error": {"message": str(e), "code": e.code}}
    except Exception as e:
        return {"error": {"message": str(e)}}


def _fb_post(path: str, token: str, data: dict = None, files: dict = None) -> dict:
    """Make a POST request to Facebook Graph API."""
    import urllib.request
    import urllib.parse
    import urllib.error
    payload = {"access_token": token}
    if data:
        payload.update(data)
    encoded = urllib.parse.urlencode(payload).encode()
    url = f"{FB_API_BASE}/{path}"
    try:
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=30) as r:
            return _j.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = _j.loads(e.read().decode())
            return {"error": body.get("error", {"message": str(e), "code": e.code})}
        except Exception:
            return {"error": {"message": str(e), "code": e.code}}
    except Exception as e:
        return {"error": {"message": str(e)}}


# ── /api/facebook/connect ─────────────────────────────────────────────────────

REQUIRED_FB_PERMS = {"pages_manage_posts", "pages_read_engagement", "pages_show_list"}


def _fb_check_token_permissions(token: str) -> tuple[set, set]:
    """Return (granted_perms, declined_perms) for this user token."""
    resp = _fb_get("me/permissions", token)
    if "error" in resp:
        return set(), set()
    granted, declined = set(), set()
    for p in resp.get("data", []):
        name = p.get("permission")
        status = p.get("status")
        if not name:
            continue
        if status == "granted":
            granted.add(name)
        else:
            declined.add(name)
    return granted, declined


def _fb_debug_token(token: str) -> dict:
    """Inspect a token via the debug_token endpoint; returns normalized info."""
    try:
        d = _fb_get("debug_token", token, {"input_token": token})
        info = (d.get("data") or {})
        return {
            "app_id": info.get("app_id"),
            "type": info.get("type"),  # USER | PAGE | APP
            "is_valid": bool(info.get("is_valid")),
            "expires_at": info.get("expires_at"),
            "scopes": info.get("scopes") or [],
        }
    except Exception:
        return {}


@bp.route("/api/facebook/connect", methods=["POST"])
def fb_connect():
    """Connect with a User Access Token and fetch pages."""
    data = request.json or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Thiếu access token"}), 400

    # Verify token and get user info
    me = _fb_get("me", token, {"fields": "id,name,picture"})
    if "error" in me:
        return jsonify({"ok": False, "error": me["error"].get("message", "Token không hợp lệ")}), 400

    # ── Check required permissions ──
    granted, declined = _fb_check_token_permissions(token)
    missing = REQUIRED_FB_PERMS - granted

    # ── Inspect token type (USER vs PAGE) ──
    debug = _fb_debug_token(token)
    token_type = debug.get("type", "")
    # Accept either USER token (recommended) or a direct PAGE token
    if token_type == "PAGE":
        # User pasted a PAGE token directly — treat it as a single-page account
        # and skip me/accounts call.
        pages = [{
            "id": me.get("id"),
            "name": me.get("name") or "Page",
            "access_token": token,
            "category": "",
            "tasks": [],
        }]
        pages_warning = ("Bạn đang dùng PAGE TOKEN — chỉ đăng được cho đúng Page này. "
                         "Khuyên dùng USER TOKEN để quản lý nhiều Page.")
    else:
        # USER token (or unknown type) — fetch the user's pages
        pages_resp = _fb_get("me/accounts", token)
        pages = pages_resp.get("data", []) or []
        pages_warning = ""

    # Save token + user info
    token_data = {
        "user_token": token,
        "user_id": me.get("id"),
        "user_name": me.get("name"),
        "token_type": token_type,
        "granted_perms": sorted(granted),
        "missing_perms": sorted(missing),
        "pages": [
            {
                "id": p["id"],
                "name": p["name"],
                "access_token": p["access_token"],
                "category": p.get("category", ""),
                "tasks": p.get("tasks", []),
            }
            for p in pages
        ],
    }
    _save_fb_token(token_data)

    # Build a warning list so the client can show actionable hints
    warnings = []
    if missing:
        warnings.append(
            "Thiếu quyền: " + ", ".join(sorted(missing))
            + ". Quay lại Graph API Explorer, cấp đủ rồi sinh token mới."
        )
    if not pages:
        warnings.append(
            "Không tìm thấy Page nào. Bạn phải là admin thật của Page và "
            "Page đã liên kết với Business (nếu cần)."
        )
    if pages_warning:
        warnings.append(pages_warning)

    return jsonify({
        "ok": True,
        "user": {"id": me.get("id"), "name": me.get("name")},
        "pages": token_data["pages"],
        "token_type": token_type,
        "granted_perms": sorted(granted),
        "missing_perms": sorted(missing),
        "warnings": warnings,
    })


@bp.route("/api/facebook/status", methods=["GET"])
def fb_status():
    """Get current Facebook connection status."""
    td = _load_fb_token()
    if not td or not td.get("user_token"):
        return jsonify({"ok": True, "connected": False})
    return jsonify({
        "ok": True,
        "connected": True,
        "user": {"id": td.get("user_id"), "name": td.get("user_name")},
        "pages": td.get("pages", []),
    })


@bp.route("/api/facebook/disconnect", methods=["POST"])
def fb_disconnect():
    """Disconnect Facebook account."""
    _clear_fb_token()
    return jsonify({"ok": True, "message": "Đã ngắt kết nối Facebook"})


# ── /api/facebook/page_info ───────────────────────────────────────────────────

@bp.route("/api/facebook/page_info", methods=["POST"])
def fb_page_info():
    """Get detailed info for a page."""
    data = request.json or {}
    page_id = str(data.get("page_id") or "").strip()
    td = _load_fb_token()
    if not td:
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook"}), 401

    # Find page token (validated: must be a PAGE token, not user token)
    page_token, perr = _resolve_page_token(td, page_id)
    if not page_token:
        return jsonify({"ok": False, "error": perr}), 404

    info = _fb_get(page_id, page_token, {
        "fields": "id,name,fan_count,followers_count,picture,category,link"
    })
    if "error" in info:
        return jsonify({"ok": False, "error": info["error"].get("message")}), 400

    return jsonify({"ok": True, "page": info})


# ── /api/facebook/post_video ──────────────────────────────────────────────────

@bp.route("/api/facebook/post_video", methods=["POST"])
def fb_post_video():
    """Upload and publish a video to a Facebook Page."""
    td = _load_fb_token()
    if not td:
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook"}), 401

    page_id = str(request.form.get("page_id") or "").strip()
    title = str(request.form.get("title") or "").strip()
    description = str(request.form.get("description") or "").strip()
    scheduled_time = str(request.form.get("scheduled_time") or "").strip() or None
    video_path_str = str(request.form.get("video_path") or "").strip()
    # Facebook Pages don't expose per-post privacy like user timelines — the
    # post always inherits the Page's public visibility.

    # Find page token (validated: must be PAGE token, not user token)
    page_token, perr = _resolve_page_token(td, page_id)
    if not page_token:
        return jsonify({"ok": False, "error": perr}), 404

    # Handle file upload
    video_file = request.files.get("video_file")
    tmp_dir = None
    if video_file and video_file.filename:
        tmp_dir = Path(tempfile.mkdtemp(prefix="fb_upload_"))
        video_path = tmp_dir / video_file.filename
        video_file.save(str(video_path))
    elif video_path_str:
        video_path = Path(video_path_str)
        if not video_path.is_absolute():
            video_path = ROOT / video_path
    else:
        return jsonify({"ok": False, "error": "Thiếu file video"}), 400

    def generate():
        def send(**kw):
            return _j.dumps(kw, ensure_ascii=False) + "\n"

        try:
            if not video_path.exists():
                yield send(log=f"❌ File không tồn tại: {video_path}", level="error")
                return

            yield send(log=f"📤 Bắt đầu upload lên Facebook Page...", level="info", overall=5)
            yield send(log=f"📁 File: {video_path.name} ({video_path.stat().st_size // 1024 // 1024} MB)", level="info", overall=10)

            # Use requests for multipart upload if available, else urllib
            try:
                import requests as _req
                files_data = {"source": (video_path.name, open(str(video_path), "rb"), "video/mp4")}
                post_data = {"access_token": page_token}
                if title:
                    post_data["title"] = title
                if description:
                    post_data["description"] = description
                if scheduled_time:
                    # Scheduled posts must be unpublished until the scheduled time
                    post_data["scheduled_publish_time"] = scheduled_time
                    post_data["published"] = "false"
                else:
                    post_data["published"] = "true"
                # NOTE: no "privacy" field — Page posts inherit the Page's
                # public visibility; sending user-timeline privacy values
                # causes Graph API to return #100.

                yield send(log="🔗 Đang gửi video lên Facebook...", level="info", overall=30)
                resp = _req.post(
                    f"{FB_API_BASE}/{page_id}/videos",
                    data=post_data,
                    files=files_data,
                    timeout=300,
                )
                result = resp.json()
            except ImportError:
                # Fallback: urllib multipart
                import urllib.request
                import urllib.parse
                import uuid

                boundary = uuid.uuid4().hex
                body_parts = []
                published_value = "false" if scheduled_time else "true"
                fields = [
                    ("access_token", page_token),
                    ("title", title),
                    ("description", description),
                    ("published", published_value),
                ]
                if scheduled_time:
                    fields.append(("scheduled_publish_time", scheduled_time))
                for k, v in fields:
                    if v:
                        body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}'.encode())

                with open(str(video_path), "rb") as vf:
                    video_bytes = vf.read()
                body_parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="{video_path.name}"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
                    + video_bytes
                )
                body_parts.append(f'--{boundary}--'.encode())
                body = b'\r\n'.join(body_parts)

                yield send(log="🔗 Đang gửi video lên Facebook...", level="info", overall=30)
                req = urllib.request.Request(
                    f"{FB_API_BASE}/{page_id}/videos",
                    data=body,
                    method="POST",
                )
                req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
                with urllib.request.urlopen(req, timeout=300) as r:
                    result = _j.loads(r.read().decode())

            if "error" in result:
                err = result["error"]
                err_msg = err.get("message", "Upload thất bại")
                is_token = _is_token_error(err)
                yield send(
                    log=f"❌ Lỗi Facebook: {err_msg}",
                    level="error",
                    overall=0,
                    token_error=is_token,
                    error=err_msg,
                )
                return

            video_id = result.get("id", "")
            page_url = f"https://www.facebook.com/{page_id}/videos/{video_id}" if video_id else ""
            yield send(log=f"✅ Upload thành công! Video ID: {video_id}", level="success", overall=100)
            if page_url:
                yield send(log=f"🔗 {page_url}", level="success", url=page_url)
            yield send(ok=True, video_id=video_id, url=page_url)

        except Exception as exc:
            yield send(log=f"❌ Lỗi: {exc}", level="error", overall=0)
        finally:
            if tmp_dir:
                shutil.rmtree(str(tmp_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ── /api/facebook/post_text ───────────────────────────────────────────────────

@bp.route("/api/facebook/post_text", methods=["POST"])
def fb_post_text():
    """Post a text/link post to a Facebook Page."""
    td = _load_fb_token()
    if not td:
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook"}), 401

    data = request.json or {}
    page_id = str(data.get("page_id") or "").strip()
    message = str(data.get("message") or "").strip()
    link    = str(data.get("link") or "").strip()
    # Page posts are always public according to the Page's visibility.

    if not page_id or not message:
        return jsonify({"ok": False, "error": "Thiếu page_id hoặc message"}), 400

    page_token, perr = _resolve_page_token(td, page_id)
    if not page_token:
        return jsonify({"ok": False, "error": perr}), 404

    post_data = {
        "message": message,
    }
    if link:
        post_data["link"] = link

    result = _fb_post(f"{page_id}/feed", page_token, post_data)
    if "error" in result:
        return jsonify({"ok": False, "error": result["error"].get("message")}), 400

    post_id = result.get("id", "")
    return jsonify({"ok": True, "post_id": post_id, "message": "Đã đăng bài thành công!"})


# ── /api/facebook/page_posts ──────────────────────────────────────────────────

@bp.route("/api/facebook/page_posts", methods=["POST"])
def fb_page_posts():
    """Get recent posts from a Facebook Page."""
    td = _load_fb_token()
    if not td:
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook"}), 401

    data = request.json or {}
    page_id = str(data.get("page_id") or "").strip()
    limit = int(data.get("limit") or 10)

    page_token, perr = _resolve_page_token(td, page_id)
    if not page_token:
        return jsonify({"ok": False, "error": perr}), 404

    errors = []

    # Try 1: published_posts (requires pages_read_engagement)
    result = _fb_get(f"{page_id}/published_posts", page_token, {
        "fields": "id,message,story,created_time,permalink_url,likes{id},comments{id}",
        "limit": limit,
    })
    if "error" in result:
        errors.append(f"published_posts: {result['error']}")

        # Try 2: feed
        result = _fb_get(f"{page_id}/feed", page_token, {
            "fields": "id,message,story,created_time,permalink_url,likes{id},comments{id}",
            "limit": limit,
        })
        if "error" in result:
            errors.append(f"feed: {result['error']}")

            # Try 3: posts (legacy, minimal fields)
            result = _fb_get(f"{page_id}/posts", page_token, {
                "fields": "id,message,story,created_time,permalink_url",
                "limit": limit,
            })
            if "error" in result:
                errors.append(f"posts: {result['error']}")
                err_detail = "; ".join(str(e) for e in errors)
                return jsonify({"ok": False, "error": err_detail, "debug_errors": errors}), 400

    return jsonify({"ok": True, "posts": result.get("data", []), "endpoint_used": "ok"})


# ── /api/facebook/post_reel ───────────────────────────────────────────────────

def _probe_video_dims(path: Path) -> tuple[int, int, float]:
    """Return (width, height, duration_sec) via ffprobe. Falls back to (0,0,0)."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height:format=duration",
                "-of", "json",
                str(path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        data = _j.loads(out.decode("utf-8", errors="ignore"))
        w = int((data.get("streams") or [{}])[0].get("width") or 0)
        h = int((data.get("streams") or [{}])[0].get("height") or 0)
        dur = float((data.get("format") or {}).get("duration") or 0)
        return w, h, dur
    except Exception:
        return 0, 0, 0.0


def _validate_reel(path: Path) -> tuple[bool, str]:
    """Check Facebook Reel requirements: 9:16, ≥540x960, 4-90s, MP4."""
    if path.suffix.lower() not in (".mp4", ".mov"):
        return False, "Reel phải là file MP4"
    w, h, dur = _probe_video_dims(path)
    if w == 0 or h == 0:
        # Couldn't probe — let Facebook validate server-side
        return True, ""
    if w >= h:
        return False, f"Reel yêu cầu 9:16 (dọc). Hiện tại: {w}x{h}"
    ratio = h / w if w else 0
    # 9:16 = 1.777; accept 1.7-1.9 (some tolerance)
    if ratio < 1.5 or ratio > 2.0:
        return False, f"Tỷ lệ không phải 9:16. Hiện tại: {w}x{h} ({ratio:.2f})"
    if w < 540 or h < 960:
        return False, f"Kích thước tối thiểu 540x960. Hiện tại: {w}x{h}"
    if dur > 0 and (dur < 3 or dur > 90):
        return False, f"Reel dài 3-90 giây. Hiện tại: {dur:.1f}s"
    return True, ""


@bp.route("/api/facebook/post_reel", methods=["POST"])
def fb_post_reel():
    """
    Upload and publish a Reel to a Facebook Page using the 3-phase flow.
    1. POST /{page_id}/video_reels  upload_phase=start  → get video_id + upload_url
    2. POST {upload_url}            file binary          → upload the bytes
    3. POST /{page_id}/video_reels  upload_phase=finish  → publish
    """
    import urllib.request
    import urllib.parse
    import urllib.error

    td = _load_fb_token()
    if not td:
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook", "token_error": True}), 401

    page_id = str(request.form.get("page_id") or "").strip()
    description = str(request.form.get("description") or "").strip()
    scheduled_time = str(request.form.get("scheduled_time") or "").strip() or None
    video_path_str = str(request.form.get("video_path") or "").strip()

    # Find page token (validated)
    page_token, perr = _resolve_page_token(td, page_id)
    if not page_token:
        return jsonify({"ok": False, "error": perr}), 404

    # Handle file upload
    video_file = request.files.get("video_file")
    tmp_dir = None
    if video_file and video_file.filename:
        tmp_dir = Path(tempfile.mkdtemp(prefix="fb_reel_"))
        video_path = tmp_dir / video_file.filename
        video_file.save(str(video_path))
    elif video_path_str:
        video_path = Path(video_path_str)
        if not video_path.is_absolute():
            video_path = ROOT / video_path
    else:
        return jsonify({"ok": False, "error": "Thiếu file video"}), 400

    def generate():
        def send(**kw):
            return _j.dumps(kw, ensure_ascii=False) + "\n"

        try:
            if not video_path.exists():
                yield send(log=f"❌ File không tồn tại: {video_path}", level="error")
                return

            # ── Validate Reel requirements ──
            ok, msg = _validate_reel(video_path)
            if not ok:
                yield send(log=f"❌ {msg}", level="error", overall=0, error=msg)
                return

            file_size = video_path.stat().st_size
            file_size_mb = file_size / 1024 / 1024
            yield send(log=f"📤 Bắt đầu upload Reel: {video_path.name} ({file_size_mb:.1f} MB)",
                       level="info", overall=5)

            # ── Phase 1: start ──
            yield send(log="🚀 Phase 1/3: Khởi tạo upload...", level="info", overall=10)
            start_result = _fb_post(
                f"{page_id}/video_reels",
                page_token,
                {"upload_phase": "start"},
            )
            if "error" in start_result:
                err = start_result["error"]
                is_token = _is_token_error(err)
                yield send(
                    log=f"❌ Phase start: {err.get('message')}",
                    level="error",
                    overall=0,
                    token_error=is_token,
                    error=err.get("message"),
                )
                return

            video_id = start_result.get("video_id")
            upload_url = start_result.get("upload_url")
            if not video_id or not upload_url:
                yield send(log="❌ Không nhận được video_id / upload_url từ Facebook",
                           level="error", overall=0)
                return

            yield send(log=f"✅ Video ID: {video_id}", level="info", overall=20)

            # ── Phase 2: upload binary to upload_url ──
            yield send(log="⬆ Phase 2/3: Đang upload file video...", level="info", overall=30)
            with open(str(video_path), "rb") as vf:
                video_bytes = vf.read()

            upload_req = urllib.request.Request(upload_url, data=video_bytes, method="POST")
            upload_req.add_header("Authorization", f"OAuth {page_token}")
            upload_req.add_header("offset", "0")
            upload_req.add_header("file_size", str(file_size))
            upload_req.add_header("Content-Type", "application/octet-stream")

            try:
                with urllib.request.urlopen(upload_req, timeout=600) as r:
                    upload_resp = _j.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                try:
                    body = _j.loads(e.read().decode())
                    err = body.get("error", {"message": str(e), "code": e.code})
                except Exception:
                    err = {"message": str(e), "code": e.code}
                is_token = _is_token_error(err)
                yield send(
                    log=f"❌ Phase upload: {err.get('message')}",
                    level="error",
                    overall=0,
                    token_error=is_token,
                    error=err.get("message"),
                )
                return

            if not upload_resp.get("success"):
                yield send(log=f"❌ Upload không thành công: {upload_resp}",
                           level="error", overall=0)
                return

            yield send(log="✅ Upload file xong", level="info", overall=75)

            # ── Phase 3: finish / publish ──
            yield send(log="🎬 Phase 3/3: Publish Reel...", level="info", overall=85)
            finish_data = {
                "video_id": video_id,
                "upload_phase": "finish",
                "video_state": "SCHEDULED" if scheduled_time else "PUBLISHED",
            }
            if description:
                finish_data["description"] = description
            if scheduled_time:
                finish_data["scheduled_publish_time"] = scheduled_time

            finish_result = _fb_post(f"{page_id}/video_reels", page_token, finish_data)
            if "error" in finish_result:
                err = finish_result["error"]
                is_token = _is_token_error(err)
                yield send(
                    log=f"❌ Phase finish: {err.get('message')}",
                    level="error",
                    overall=0,
                    token_error=is_token,
                    error=err.get("message"),
                )
                return

            if not finish_result.get("success", True):
                yield send(log=f"❌ Publish thất bại: {finish_result}",
                           level="error", overall=0)
                return

            page_url = f"https://www.facebook.com/reel/{video_id}"
            yield send(log=f"✅ Reel đã đăng! Video ID: {video_id}",
                       level="success", overall=100)
            yield send(log=f"🔗 {page_url}", level="success", url=page_url)
            yield send(ok=True, video_id=video_id, url=page_url)

        except Exception as exc:
            yield send(log=f"❌ Lỗi: {exc}", level="error", overall=0)
        finally:
            if tmp_dir:
                shutil.rmtree(str(tmp_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ── /api/facebook/validate_reel ───────────────────────────────────────────────

@bp.route("/api/facebook/validate_reel", methods=["POST"])
def fb_validate_reel():
    """Check if a video file meets Facebook Reel requirements."""
    data = request.json or {}
    path_str = str(data.get("video_path") or "").strip()
    if not path_str:
        return jsonify({"ok": False, "error": "Thiếu video_path"}), 400
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return jsonify({"ok": False, "error": "File không tồn tại"}), 404
    ok, msg = _validate_reel(p)
    w, h, dur = _probe_video_dims(p)
    return jsonify({
        "ok": ok,
        "error": msg if not ok else "",
        "width": w,
        "height": h,
        "duration": dur,
        "ratio": (h / w) if w else 0,
        "is_vertical_9_16": 1.7 <= (h / w if w else 0) <= 1.85,
    })


# ── /api/facebook/diagnose ────────────────────────────────────────────────────

@bp.route("/api/facebook/diagnose", methods=["GET"])
def fb_diagnose():
    """Run a checklist against the saved token and the first page to help
    users figure out why publish fails (common: #100 No permission)."""
    td = _load_fb_token()
    if not td or not td.get("user_token"):
        return jsonify({"ok": False, "error": "Chưa kết nối Facebook"}), 401

    user_token = td["user_token"]
    checks = []

    # 1. Token valid?
    me = _fb_get("me", user_token, {"fields": "id,name"})
    checks.append({
        "label": "Token hợp lệ",
        "ok": "error" not in me,
        "detail": me.get("name") if "error" not in me else me.get("error", {}).get("message"),
    })

    # 2. Token type (USER vs PAGE)
    debug = _fb_debug_token(user_token)
    t_type = debug.get("type", "?")
    checks.append({
        "label": f"Loại token: {t_type}",
        "ok": t_type in ("USER", "PAGE"),
        "detail": "Nên dùng USER token" if t_type == "PAGE" else None,
    })

    # 3. Required permissions
    granted, declined = _fb_check_token_permissions(user_token)
    missing = REQUIRED_FB_PERMS - granted
    checks.append({
        "label": "Permissions",
        "ok": not missing,
        "detail": ("Đã cấp: " + ", ".join(sorted(granted))) if not missing
                  else ("Thiếu: " + ", ".join(sorted(missing))),
    })

    # 4. Has at least one page
    pages = td.get("pages", [])
    checks.append({
        "label": f"Số Page quản lý: {len(pages)}",
        "ok": len(pages) > 0,
        "detail": "Phải là admin thật của Page" if not pages else None,
    })

    # 5. For each page, check page-token publish capability
    for p in pages[:3]:  # limit to first 3
        pt = p["access_token"]
        pt_info = _fb_debug_token(pt)
        pt_type = pt_info.get("type", "?")
        checks.append({
            "label": f"Page '{p['name']}' token",
            "ok": pt_type == "PAGE" and pt_info.get("is_valid"),
            "detail": f"type={pt_type}, valid={pt_info.get('is_valid')}, scopes={pt_info.get('scopes')}",
        })

    # 6. Token expiry
    exp = debug.get("expires_at")
    if exp:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
            checks.append({
                "label": "Token hết hạn",
                "ok": dt > datetime.now(timezone.utc),
                "detail": dt.strftime("%Y-%m-%d %H:%M UTC"),
            })
        except Exception:
            pass

    all_ok = all(c["ok"] for c in checks)
    return jsonify({"ok": True, "all_ok": all_ok, "checks": checks})

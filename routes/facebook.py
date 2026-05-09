"""Facebook Blueprint — Graph API integration for page management and video publishing."""
import json as _j
import os
import tempfile
import shutil
from pathlib import Path
from flask import Blueprint, jsonify, request, Response, stream_with_context
from core_app import ROOT, load_cfg, save_cfg

bp = Blueprint("facebook", __name__)

FB_API_BASE = "https://graph.facebook.com/v25.0"
FB_TOKEN_FILE = ROOT / ".facebook_token.json"


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

    # Get pages
    pages_resp = _fb_get("me/accounts", token)
    pages = pages_resp.get("data", [])

    # Save token + user info
    token_data = {
        "user_token": token,
        "user_id": me.get("id"),
        "user_name": me.get("name"),
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

    return jsonify({
        "ok": True,
        "user": {"id": me.get("id"), "name": me.get("name")},
        "pages": token_data["pages"],
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

    # Find page token
    page_token = None
    for p in td.get("pages", []):
        if p["id"] == page_id:
            page_token = p["access_token"]
            break
    if not page_token:
        return jsonify({"ok": False, "error": "Không tìm thấy page"}), 404

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
    privacy = str(request.form.get("privacy") or "EVERYONE").strip().upper()
    # Validate privacy value
    if privacy not in ("EVERYONE", "FRIENDS", "ONLY_ME"):
        privacy = "EVERYONE"

    # Find page token
    page_token = None
    for p in td.get("pages", []):
        if p["id"] == page_id:
            page_token = p["access_token"]
            break
    if not page_token:
        return jsonify({"ok": False, "error": "Không tìm thấy page token"}), 404

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
                    post_data["scheduled_publish_time"] = scheduled_time
                    post_data["published"] = "false"
                else:
                    post_data["published"] = "true"
                # Privacy only applies to non-scheduled posts
                if not scheduled_time:
                    post_data["privacy"] = _j.dumps({"value": privacy})

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
                for k, v in [("access_token", page_token), ("title", title), ("description", description), ("published", "true")]:
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
                err_msg = result["error"].get("message", "Upload thất bại")
                yield send(log=f"❌ Lỗi Facebook: {err_msg}", level="error", overall=0)
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
    privacy = str(data.get("privacy") or "EVERYONE").strip().upper()
    if privacy not in ("EVERYONE", "FRIENDS", "ONLY_ME"):
        privacy = "EVERYONE"

    if not page_id or not message:
        return jsonify({"ok": False, "error": "Thiếu page_id hoặc message"}), 400

    page_token = None
    for p in td.get("pages", []):
        if p["id"] == page_id:
            page_token = p["access_token"]
            break
    if not page_token:
        return jsonify({"ok": False, "error": "Không tìm thấy page token"}), 404

    post_data = {
        "message": message,
        "privacy": _j.dumps({"value": privacy}),
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

    page_token = None
    for p in td.get("pages", []):
        if p["id"] == page_id:
            page_token = p["access_token"]
            break
    if not page_token:
        return jsonify({"ok": False, "error": "Không tìm thấy page token"}), 404

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

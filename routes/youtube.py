"""YouTube Blueprint — OAuth, channel info, upload, logout routes."""
import json as _j
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context
from core_app import _get_youtube_uploader, ROOT
import os

bp = Blueprint("youtube", __name__)


@bp.route("/api/youtube_auth", methods=["GET", "POST"])
def youtube_auth():
    """Get YouTube OAuth URL or handle OAuth callback."""
    try:
        uploader = _get_youtube_uploader()

        if request.method == "POST":
            uploader.revoke_auth()
            auth_url = uploader.get_auth_url()
            if auth_url:
                return jsonify({"ok": True, "authenticated": False, "auth_url": auth_url})
            err_msg = str(getattr(uploader, "last_error", "") or "").strip()
            return jsonify({
                "ok": False,
                "authenticated": False,
                "error_code": "auth_failed",
                "error": err_msg or "Unable to start OAuth flow",
            }), 401

        # GET: return auth URL or authenticated status
        if uploader.authenticate():
            channel = uploader.get_channel_info()
            return jsonify({"ok": True, "authenticated": True, "channel": channel})

        auth_url = uploader.get_auth_url()
        if not auth_url:
            err_msg = str(getattr(uploader, "last_error", "") or "").strip()
            # Return 200 so JS doesn't throw — just shows "not configured"
            return jsonify({
                "ok": False,
                "authenticated": False,
                "error_code": "auth_url_unavailable",
                "error": err_msg or "client_secrets.json not found",
            }), 200

        return jsonify({"ok": True, "authenticated": False, "auth_url": auth_url})
    except ModuleNotFoundError as e:
        return jsonify({
            "ok": False,
            "authenticated": False,
            "error_code": "missing_dependency",
            "error": f"Missing dependency: {e}",
        }), 500
    except FileNotFoundError as e:
        return jsonify({
            "ok": False,
            "authenticated": False,
            "error_code": "missing_file",
            "error": str(e),
        }), 200  # 200 so JS handles gracefully
    except Exception as e:
        return jsonify({
            "ok": False,
            "authenticated": False,
            "error_code": "internal_error",
            "error": f"YouTube auth error: {e}",
        }), 500


@bp.route("/oauth2callback", methods=["GET"])
def youtube_oauth2_callback():
    """Handle Google OAuth callback and close popup window."""
    uploader = _get_youtube_uploader()
    state = str(request.args.get("state") or "")
    ok = uploader.complete_auth_callback(request.url, state=state)
    if ok:
        return """
<!doctype html>
<html><head><meta charset="utf-8"><title>YouTube Connected</title></head>
<body style="font-family:Arial,sans-serif;padding:24px;line-height:1.5;">
    <h3>YouTube connected successfully.</h3>
    <p>You can close this window and return to the app.</p>
    <script>
        try { window.close(); } catch (e) {}
    </script>
</body></html>
"""
    err = str(getattr(uploader, "last_error", "") or "OAuth callback failed")
    return f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>YouTube OAuth Error</title></head>
<body style="font-family:Arial,sans-serif;padding:24px;line-height:1.5;">
    <h3>Failed to connect YouTube.</h3>
    <p>{err}</p>
    <p>Please close this window and click "Đăng nhập YouTube" again.</p>
</body></html>
""", 400


@bp.route("/api/youtube_channel", methods=["GET"])
def youtube_channel():
    """Get authenticated YouTube channel info."""
    uploader = _get_youtube_uploader()
    if not uploader.credentials:
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Not authenticated"}), 401

    channel = uploader.get_channel_info()
    if channel:
        return jsonify({"ok": True, "channel": channel})
    return jsonify({"ok": False, "error": "Failed to fetch channel"}), 500


@bp.route("/api/youtube_upload", methods=["POST"])
def youtube_upload():
    """Upload video to YouTube."""
    is_temp_file = False
    if request.is_json:
        data = request.json or {}
        video_path = str(data.get("video_path") or "").strip()
        title = str(data.get("title") or "").strip()
        description = str(data.get("description") or "").strip()
        tags = data.get("tags") or []
        privacy_status = str(data.get("privacy_status") or "private").strip().lower()
        is_short = bool(data.get("is_short", False))
        publish_at = str(data.get("publish_at") or "").strip() or None
    else:
        video_file = request.files.get("video_file")
        if video_file:
            temp_dir = Path("temp_uploads")
            temp_dir.mkdir(exist_ok=True)
            video_path = str(temp_dir / video_file.filename)
            video_file.save(video_path)
            is_temp_file = True
        else:
            video_path = str(request.form.get("video_path") or "").strip()

        title = str(request.form.get("title") or "").strip()
        description = str(request.form.get("description") or "").strip()
        tags_str = request.form.get("tags") or "[]"
        try:
            tags = _j.loads(tags_str)
        except Exception:
            tags = []
        privacy_status = str(request.form.get("privacy_status") or "private").strip().lower()
        is_short = request.form.get("is_short", "false").lower() in ("true", "1", "yes")
        publish_at = str(request.form.get("publish_at") or "").strip() or None

    if not title and video_path:
        title = Path(video_path).stem

    if not video_path or not title:
        return jsonify({"ok": False, "error": "Missing video_path or title"}), 400

    video_path = Path(video_path)
    if not video_path.exists():
        return jsonify({"ok": False, "error": f"Video not found: {video_path}"}), 404

    uploader = _get_youtube_uploader()
    if not uploader.credentials:
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Not authenticated with YouTube"}), 401

    def generate():
        def send(**kw):
            return _j.dumps(kw, ensure_ascii=False) + "\n"

        try:
            yield send(log="[YouTube] Bắt đầu upload...", level="info")
            result = uploader.upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                privacy_status=privacy_status,
                is_short=is_short,
                publish_at=publish_at,
            )

            if result:
                yield send(
                    log=f"[YouTube] ✓ Upload thành công! {result['url']}",
                    level="success",
                    video_id=result["id"],
                    url=result["url"],
                )
            else:
                yield send(log="[YouTube] ✗ Upload thất bại", level="error")
        except Exception as e:
            yield send(log=f"[YouTube] ✗ Lỗi: {str(e)}", level="error")
        finally:
            if is_temp_file and video_path.exists():
                try:
                    video_path.unlink()
                except Exception:
                    pass

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@bp.route("/api/youtube_logout", methods=["POST"])
def youtube_logout():
    """Logout from YouTube (revoke token)."""
    uploader = _get_youtube_uploader()
    if uploader.revoke_auth():
        return jsonify({"ok": True, "message": "Logged out from YouTube"})
    return jsonify({"ok": False, "error": "Failed to logout"}), 500


@bp.route("/api/youtube_videos", methods=["GET"])
def youtube_videos():
    """Get list of uploaded videos from authenticated channel."""
    uploader = _get_youtube_uploader()
    if not uploader.credentials:
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Not authenticated"}), 401

    page_token = request.args.get("page_token") or None
    max_results = int(request.args.get("max_results") or 20)

    try:
        yt = uploader.youtube
        if not yt:
            return jsonify({"ok": False, "error": "YouTube client not initialized"}), 500

        # Get uploads playlist ID from channel
        ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
        if not ch_resp.get("items"):
            return jsonify({"ok": False, "error": "No channel found"}), 404

        uploads_playlist = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # List videos from uploads playlist
        params = {
            "part": "snippet,contentDetails",
            "playlistId": uploads_playlist,
            "maxResults": min(max_results, 50),
        }
        if page_token:
            params["pageToken"] = page_token

        pl_resp = yt.playlistItems().list(**params).execute()
        video_ids = [item["contentDetails"]["videoId"] for item in pl_resp.get("items", [])]

        if not video_ids:
            return jsonify({"ok": True, "videos": [], "next_page_token": None, "total": 0})

        # Get video details (status, statistics, contentDetails, fileDetails)
        vid_resp = yt.videos().list(
            part="snippet,status,statistics,contentDetails,localizations",
            id=",".join(video_ids),
        ).execute()

        videos = []
        for v in vid_resp.get("items", []):
            snippet    = v.get("snippet", {})
            status     = v.get("status", {})
            stats      = v.get("statistics", {})
            content    = v.get("contentDetails", {})
            thumbs     = snippet.get("thumbnails", {})
            thumb_url  = (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            duration   = content.get("duration", "")  # ISO 8601 e.g. PT4M13S

            videos.append({
                "id":              v["id"],
                "title":           snippet.get("title", ""),
                "description":     snippet.get("description", ""),
                "published_at":    snippet.get("publishedAt", ""),
                "thumbnail":       thumb_url,
                "privacy":         status.get("privacyStatus", ""),
                "license":         status.get("license", "youtube"),        # youtube | creativeCommon
                "embeddable":      status.get("embeddable", True),
                "made_for_kids":   status.get("madeForKids", False),
                "upload_status":   status.get("uploadStatus", ""),
                "views":           int(stats.get("viewCount",    0)),
                "likes":           int(stats.get("likeCount",    0)),
                "comments":        int(stats.get("commentCount", 0)),
                "favorites":       int(stats.get("favoriteCount",0)),
                "duration":        duration,
                "definition":      content.get("definition", ""),           # hd | sd
                "caption":         content.get("caption", "false"),         # true | false
                "url":             f"https://youtu.be/{v['id']}",
                "tags":            snippet.get("tags", []),
                "category_id":     snippet.get("categoryId", ""),
                "default_language":snippet.get("defaultLanguage", ""),
            })

        return jsonify({
            "ok": True,
            "videos": videos,
            "next_page_token": pl_resp.get("nextPageToken"),
            "prev_page_token": pl_resp.get("prevPageToken"),
            "total": pl_resp.get("pageInfo", {}).get("totalResults", len(videos)),
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/youtube_video_update", methods=["POST"])
def youtube_video_update():
    """Update video title, description, tags, privacy."""
    uploader = _get_youtube_uploader()
    if not uploader.credentials:
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data = request.json or {}
    video_id    = str(data.get("video_id") or "").strip()
    title       = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    tags        = data.get("tags") or []
    privacy     = str(data.get("privacy") or "").strip()
    license_val = str(data.get("license") or "").strip()
    made_for_kids = data.get("made_for_kids")

    if not video_id:
        return jsonify({"ok": False, "error": "Missing video_id"}), 400

    try:
        yt = uploader.youtube
        body = {"id": video_id, "snippet": {}, "status": {}}
        parts = []

        if title or description or tags:
            body["snippet"]["title"]       = title or "Untitled"
            body["snippet"]["description"] = description
            body["snippet"]["tags"]        = tags if isinstance(tags, list) else []
            body["snippet"]["categoryId"]  = "22"
            parts.append("snippet")

        if privacy in ("public", "private", "unlisted"):
            body["status"]["privacyStatus"] = privacy
            parts.append("status")

        if license_val in ("youtube", "creativeCommon"):
            body["status"]["license"] = license_val
            if "status" not in parts:
                parts.append("status")

        if made_for_kids is not None:
            body["status"]["madeForKids"] = bool(made_for_kids)
            if "status" not in parts:
                parts.append("status")

        if not parts:
            return jsonify({"ok": False, "error": "Nothing to update"}), 400

        yt.videos().update(part=",".join(parts), body=body).execute()
        return jsonify({"ok": True, "message": "Đã cập nhật video thành công"})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/youtube_video_delete", methods=["POST"])
def youtube_video_delete():
    """Delete a YouTube video."""
    uploader = _get_youtube_uploader()
    if not uploader.credentials:
        if not uploader.authenticate():
            return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data     = request.json or {}
    video_id = str(data.get("video_id") or "").strip()
    if not video_id:
        return jsonify({"ok": False, "error": "Missing video_id"}), 400

    try:
        uploader.youtube.videos().delete(id=video_id).execute()
        return jsonify({"ok": True, "message": f"Đã xóa video {video_id}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── TikTok stubs (removed TikTok uploader, return not-supported) ──────────────
@bp.route("/api/tiktok_auth", methods=["GET", "POST"])
def tiktok_auth_stub():
    """TikTok upload removed — return stub so JS doesn't get 404."""
    return jsonify({
        "ok": False,
        "authenticated": False,
        "error_code": "not_supported",
        "error": "TikTok upload not supported in this version",
    }), 200  # 200 so JS doesn't throw, just shows unauthenticated


@bp.route("/api/tiktok_logout", methods=["POST"])
def tiktok_logout_stub():
    return jsonify({"ok": True, "message": "TikTok not configured"})


@bp.route("/api/tiktok_upload", methods=["POST"])
def tiktok_upload_stub():
    return jsonify({"ok": False, "error": "TikTok upload not supported"}), 400

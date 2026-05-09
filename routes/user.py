"""User Blueprint — /api/user_videos_page, /api/user_info, /api/proxy_image routes."""
import asyncio
from datetime import datetime
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context
from core_app import (
    load_cfg, CONFIG_FILE,
    get_cookies_with_fallback, _extract_cover,
)

bp = Blueprint("user", __name__)


# ── /api/user_videos_page ─────────────────────────────────────────────────────
@bp.route("/api/user_videos_page", methods=["POST"])
def user_videos_page():
    data = request.json or {}
    url    = data.get("url", "").strip()
    cursor = int(data.get("cursor", 0))
    count  = int(data.get("count", 20))
    offset = int(data.get("offset", 0))
    if not url:
        return jsonify({"error": "No URL"}), 400

    def parse_items(items):
        videos = []
        for item in items:
            cover = _extract_cover(item)
            ts = item.get("create_time", 0)
            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
            videos.append({
                "aweme_id": item.get("aweme_id", ""),
                "desc":     (item.get("desc", "") or "")[:80],
                "cover":    cover,
                "date":     dt,
                "ts":       ts,
                "play":     (item.get("statistics") or {}).get("play_count", 0),
                "like":     (item.get("statistics") or {}).get("digg_count", 0),
                "comment":  (item.get("statistics") or {}).get("comment_count", 0),
                "type":     "gallery" if item.get("images") else "video",
                "duration": (item.get("video") or {}).get("duration", 0) or
                            (item.get("video") or {}).get("video_duration", 0) or
                            item.get("duration", 0) or 0,
            })
        return videos

    async def fetch():
        from config import ConfigLoader
        from auth import CookieManager
        from core import DouyinAPIClient, URLParser
        config = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user":
            return {"error": "Invalid user URL"}
        sec_uid = parsed.get("sec_uid", "")
        async with DouyinAPIClient(cm.get_cookies(), proxy=config.get("proxy")) as api:
            if cursor == 0 and offset > 0:
                all_items = []
                cur = 0
                seen_ids = set()
                for _ in range(20):
                    result = await api.get_user_post(sec_uid, max_cursor=cur, count=20)
                    page_items = result.get("items") or result.get("aweme_list") or []
                    added = 0
                    for item in page_items:
                        aid = item.get("aweme_id")
                        if aid and aid not in seen_ids:
                            seen_ids.add(aid)
                            all_items.append(item)
                            added += 1
                    new_cursor = int(result.get("max_cursor", 0) or 0)
                    if added == 0 or new_cursor == cur or len(all_items) >= offset + count:
                        break
                    cur = new_cursor
                has_more_final = len(all_items) > offset + count
                slice_items = all_items[offset:offset + count]
                return {
                    "videos":      parse_items(slice_items),
                    "has_more":    has_more_final,
                    "next_cursor": cur,
                    "offset":      offset + len(slice_items),
                }
            else:
                result = await api.get_user_post(sec_uid, max_cursor=cursor, count=count)
                items  = result.get("items") or result.get("aweme_list") or []
                return {
                    "videos":      parse_items(items),
                    "has_more":    result.get("has_more", False),
                    "next_cursor": result.get("max_cursor", 0),
                    "offset":      offset + len(items),
                }

    try:
        return jsonify(asyncio.run(fetch()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/user_videos (streaming NDJSON) ──────────────────────────────────────
@bp.route("/api/user_videos", methods=["POST"])
def user_videos():
    data = request.json or {}
    url = data.get("url", "").strip()
    max_count = int(data.get("max_count", 0))
    if not url:
        return jsonify({"error": "No URL"}), 400

    import json as _j

    def generate():
        async def fetch_all():
            from config import ConfigLoader
            from auth import CookieManager
            from core import DouyinAPIClient, URLParser
            config = ConfigLoader(str(CONFIG_FILE))
            cm = CookieManager()
            cm.set_cookies(get_cookies_with_fallback())
            parsed = URLParser.parse(url)
            if not parsed or parsed.get("type") != "user":
                yield {"error": "Invalid user URL"}
                return
            sec_uid = parsed.get("sec_uid", "")
            cursor = 0
            page = 0
            total = 0

            async with DouyinAPIClient(cm.get_cookies(), proxy=config.get("proxy")) as api:
                while True:
                    page += 1
                    result = await api.get_user_post(sec_uid, max_cursor=cursor, count=20)
                    items = result.get("items") or result.get("aweme_list") or []
                    if not items:
                        break
                    videos = []
                    for item in items:
                        cover = ""
                        vc = (item.get("video") or {}).get("cover") or \
                             (item.get("video") or {}).get("origin_cover") or {}
                        ul = vc.get("url_list") or []
                        if ul:
                            cover = ul[0]
                        if not cover:
                            imgs = item.get("images") or []
                            if imgs:
                                ul2 = (imgs[0].get("url_list") or [])
                                if ul2:
                                    cover = ul2[0]
                        ts = item.get("create_time", 0)
                        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
                        videos.append({
                            "aweme_id": item.get("aweme_id", ""),
                            "desc":     (item.get("desc", "") or "")[:80],
                            "cover":    cover,
                            "date":     dt,
                            "ts":       ts,
                            "play":     (item.get("statistics") or {}).get("play_count", 0),
                            "like":     (item.get("statistics") or {}).get("digg_count", 0),
                            "comment":  (item.get("statistics") or {}).get("comment_count", 0),
                            "type":     "gallery" if item.get("images") else "video",
                            "duration": (item.get("video") or {}).get("duration", 0) or
                                        (item.get("video") or {}).get("video_duration", 0) or
                                        item.get("duration", 0) or 0,
                        })
                    total += len(videos)
                    yield {"page": page, "videos": videos, "total_so_far": total,
                           "has_more": result.get("has_more", False)}
                    if not result.get("has_more"):
                        break
                    if max_count > 0 and total >= max_count:
                        break
                    cursor = result.get("max_cursor", 0)
                    if not cursor:
                        break

        import asyncio as _asyncio

        async def run():
            async for chunk in fetch_all():
                yield _j.dumps(chunk) + "\n"

        loop = _asyncio.new_event_loop()
        agen = run()
        try:
            while True:
                try:
                    chunk = loop.run_until_complete(agen.__anext__())
                    yield chunk
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ── /api/proxy_image ──────────────────────────────────────────────────────────
@bp.route("/api/proxy_image")
def proxy_image():
    import urllib.request
    from urllib.parse import urlparse as _up
    url = request.args.get("url", "")
    if not url:
        return "", 400
    allowed = ("douyinpic.com", "byteimg.com", "tiktokcdn.com",
               "douyin.com", "pstatp.com", "bytedance.com", "ixigua.com")
    host = _up(url).hostname or ""
    if not any(host.endswith(d) for d in allowed):
        return "", 403
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer":    "https://www.douyin.com/",
            "Accept":     "image/webp,image/apng,image/*,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ct   = resp.headers.get("Content-Type", "image/jpeg")
        r = Response(data, content_type=ct)
        r.headers["Cache-Control"] = "public, max-age=86400"
        return r
    except Exception:
        return "", 404


# ── /api/user_info ────────────────────────────────────────────────────────────
@bp.route("/api/user_info", methods=["POST"])
def user_info():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL"}), 400

    async def fetch():
        import asyncio as _asyncio
        from config import ConfigLoader
        from auth import CookieManager
        from core import DouyinAPIClient, URLParser
        config = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user":
            return None, [], False
        sec_uid = parsed.get("sec_uid", "")
        async with DouyinAPIClient(cm.get_cookies(), proxy=config.get("proxy")) as api:
            info = await api.get_user_info(sec_uid)
            if not info:
                return None, [], False

            all_items = []
            seen_ids = set()
            cursor = 0
            pagination_blocked = False
            for _ in range(200):
                result = await api.get_user_post(sec_uid, max_cursor=cursor, count=20)
                page_items = result.get("items") or result.get("aweme_list") or []
                added = 0
                for item in page_items:
                    aid = item.get("aweme_id")
                    if aid and aid not in seen_ids:
                        seen_ids.add(aid)
                        all_items.append(item)
                        added += 1
                new_cursor = int(result.get("max_cursor", 0) or 0)
                if added == 0 or new_cursor == cursor:
                    pagination_blocked = True
                    break
                cursor = new_cursor
                await _asyncio.sleep(0.3)

            return info, all_items, pagination_blocked

    def parse_item(item):
        cover = _extract_cover(item)
        ts = item.get("create_time", 0)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
        return {
            "aweme_id": item.get("aweme_id", ""),
            "desc":     (item.get("desc", "") or "")[:80],
            "cover":    cover,
            "date":     dt,
            "ts":       ts,
            "play":     (item.get("statistics") or {}).get("play_count", 0),
            "like":     (item.get("statistics") or {}).get("digg_count", 0),
            "type":     "gallery" if item.get("images") else "video",
            "duration": (item.get("video") or {}).get("duration", 0) or
                        (item.get("video") or {}).get("video_duration", 0) or
                        item.get("duration", 0) or 0,
        }

    try:
        info, all_items, pagination_blocked = asyncio.run(fetch())
        if not info:
            return jsonify({"error": "User not found or invalid URL"}), 404

        videos = [parse_item(i) for i in all_items]
        aweme_count = info.get("aweme_count", 0)
        return jsonify({
            "nickname":    info.get("nickname", ""),
            "uid":         info.get("uid", ""),
            "sec_uid":     info.get("sec_uid", ""),
            "signature":   info.get("signature", ""),
            "avatar":      ((info.get("avatar_thumb") or {}).get("url_list") or [""])[0],
            "follower":    info.get("follower_count", 0),
            "following":   info.get("following_count", 0),
            "aweme_count": aweme_count,
            "videos":      videos,
            "has_more":    False,
            "next_cursor": 0,
            "pagination_blocked": pagination_blocked,
            "fetched_count": len(videos),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

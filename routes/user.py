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
        from core.proxy_resolver import resolve_proxy
        config = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user":
            return {"error": "Invalid user URL"}
        sec_uid = parsed.get("sec_uid", "")
        async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(config)) as api:
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
            from core.proxy_resolver import resolve_proxy
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

            async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(config)) as api:
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


# ── /api/user_videos_all (browser fallback, NDJSON stream) ───────────────────
@bp.route("/api/user_videos_all", methods=["POST"])
def user_videos_all():
    """Dùng Playwright quét trang user Douyin để lấy đủ aweme_id khi API bị
    giới hạn pagination. Stream NDJSON về UI để hiển thị tiến độ.

    Payload: { url: str, known_ids?: [str] }
    """
    data = request.json or {}
    url = (data.get("url") or "").strip()
    known_ids = set(str(x) for x in (data.get("known_ids") or []) if x)
    if not url:
        return jsonify({"error": "No URL"}), 400

    import json as _j
    import queue as _queue
    import threading as _threading

    # Kiểm tra Playwright có sẵn không — nếu không, trả lỗi ngay.
    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "error": "Playwright chưa được cài. Chạy: pip install playwright && playwright install chromium",
        }), 500

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
            "comment":  (item.get("statistics") or {}).get("comment_count", 0),
            "type":     "gallery" if item.get("images") else "video",
            "duration": (item.get("video") or {}).get("duration", 0) or
                        (item.get("video") or {}).get("video_duration", 0) or
                        item.get("duration", 0) or 0,
        }

    # Hàng đợi cho cầu async → generator SSE-like
    q: "_queue.Queue[str]" = _queue.Queue()
    SENTINEL = object()

    def _emit(kind: str, **payload):
        payload["kind"] = kind
        q.put(_j.dumps(payload, ensure_ascii=False) + "\n")

    async def run_fetch():
        from config import ConfigLoader
        from auth import CookieManager
        from core import DouyinAPIClient, URLParser
        from core.proxy_resolver import resolve_proxy
        config = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user":
            _emit("error", message="Invalid user URL")
            return
        sec_uid = parsed.get("sec_uid", "")

        browser_cfg = (config.get("browser_fallback") or {}) if hasattr(config, "get") else {}
        headless = bool(browser_cfg.get("headless", False))
        max_scrolls = int(browser_cfg.get("max_scrolls", 240) or 240)
        idle_rounds = int(browser_cfg.get("idle_rounds", 8) or 8)
        wait_timeout_seconds = int(browser_cfg.get("wait_timeout_seconds", 600) or 600)

        async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(config)) as api:
            _emit("status", message="Mở trình duyệt để lấy danh sách video...")
            try:
                aweme_ids = await api.collect_user_post_ids_via_browser(
                    sec_uid,
                    expected_count=0,
                    headless=headless,
                    max_scrolls=max_scrolls,
                    idle_rounds=idle_rounds,
                    wait_timeout_seconds=wait_timeout_seconds,
                )
            except Exception as exc:
                _emit("error", message=f"Browser fallback lỗi: {exc}")
                return

            if not aweme_ids:
                _emit("error", message="Không lấy được video qua trình duyệt (có thể cần đăng nhập hoặc giải captcha).")
                return

            # Tận dụng items đã bắt được từ network khi scroll (không phải gọi lại API detail)
            cached_items = {}
            try:
                cached_items = api.pop_browser_post_aweme_items() or {}
            except Exception:
                cached_items = {}

            missing_ids = [aid for aid in aweme_ids if str(aid) not in known_ids]
            _emit(
                "progress",
                collected=len(aweme_ids),
                missing=len(missing_ids),
                cached=len([a for a in missing_ids if str(a) in cached_items]),
            )

            # Phát video có sẵn từ cache trước (nhanh, không tốn request)
            emitted_batch = []
            for aid in missing_ids:
                item = cached_items.get(str(aid))
                if not item:
                    continue
                emitted_batch.append(parse_item(item))
                if len(emitted_batch) >= 10:
                    _emit("videos", videos=emitted_batch)
                    emitted_batch = []
            if emitted_batch:
                _emit("videos", videos=emitted_batch)
                emitted_batch = []

            # Những id còn lại chưa có item → gọi API detail
            remaining = [aid for aid in missing_ids if str(aid) not in cached_items]
            total_remain = len(remaining)
            for idx, aid in enumerate(remaining, start=1):
                try:
                    detail = await api.get_video_detail(str(aid), suppress_error=True)
                except Exception:
                    detail = None
                if detail:
                    emitted_batch.append(parse_item(detail))
                if emitted_batch and (len(emitted_batch) >= 5 or idx == total_remain):
                    _emit("videos", videos=emitted_batch)
                    emitted_batch = []
                if idx == 1 or idx == total_remain or idx % 5 == 0:
                    _emit("progress", fetched=idx, total=total_remain, phase="detail")

            _emit("done", total_ids=len(aweme_ids))

    def worker():
        try:
            asyncio.run(run_fetch())
        except Exception as exc:  # noqa: BLE001
            _emit("error", message=str(exc))
        finally:
            q.put(SENTINEL)

    t = _threading.Thread(target=worker, daemon=True)
    t.start()

    def generate():
        while True:
            chunk = q.get()
            if chunk is SENTINEL:
                break
            yield chunk

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
        from core.proxy_resolver import resolve_proxy
        config = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user":
            return None, [], False
        sec_uid = parsed.get("sec_uid", "")
        async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(config)) as api:
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

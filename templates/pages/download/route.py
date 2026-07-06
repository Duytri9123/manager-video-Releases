"""Download Blueprint — SocketIO handle_download + /api/history + /api/files routes."""
import asyncio
import threading
import logging
import os
import mimetypes
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, Response
from flask_socketio import emit
from core_app import (
    socketio, load_cfg, CONFIG_FILE, LOGGER,
    get_cookies_with_fallback, SocketProgress,
    _dl_queue, _queue_lock,
)
import core_app as _ca

bp = Blueprint("download", __name__)


# ── /api/files — duyệt file đã tải ──────────────────────────────────────────
@bp.route("/api/files", methods=["GET"])
def list_files():
    """Liệt kê file trong thư mục Downloaded."""
    cfg = load_cfg()
    base_dir = Path(cfg.get("path") or "./Downloaded").expanduser().resolve()
    sub = request.args.get("dir", "").strip().lstrip("/\\")

    # Security: chỉ cho phép duyệt bên trong base_dir
    target = (base_dir / sub).resolve() if sub else base_dir
    try:
        target.relative_to(base_dir)
    except ValueError:
        return jsonify({"error": "Access denied"}), 403

    if not target.exists():
        return jsonify({"items": [], "path": str(sub), "base": str(base_dir)})

    _VIDEO_EXTS  = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv', '.ogv', '.3gp', '.ts'}
    _AUDIO_EXTS  = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.opus', '.flac', '.wma'}
    _IMAGE_EXTS  = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg', '.tiff'}
    _SUB_EXTS    = {'.srt', '.ass', '.vtt', '.ssa', '.lrc'}
    _DOC_EXTS    = {'.txt', '.json', '.csv', '.md', '.log', '.xml', '.yaml', '.yml'}

    def _file_type(ext: str) -> str:
        if ext in _VIDEO_EXTS:  return "video"
        if ext in _AUDIO_EXTS:  return "audio"
        if ext in _IMAGE_EXTS:  return "image"
        if ext in _SUB_EXTS:    return "subtitle"
        if ext in _DOC_EXTS:    return "document"
        return "other"

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            rel = entry.relative_to(base_dir)
            stat = entry.stat()
            size = stat.st_size if entry.is_file() else 0
            mtime = stat.st_mtime
            ext = entry.suffix.lower() if entry.is_file() else ""
            ftype = _file_type(ext) if entry.is_file() else "dir"

            # Count children for directories
            child_count = None
            if entry.is_dir():
                try:
                    child_count = sum(1 for _ in entry.iterdir())
                except Exception:
                    child_count = 0

            items.append({
                "name": entry.name,
                "path": str(rel).replace("\\", "/"),
                "abs_path": str(entry),
                "is_dir": entry.is_dir(),
                "size": size,
                "size_str": _fmt_size(size),
                "mtime": datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M"),
                "mtime_full": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "ext": ext,
                "file_type": ftype,
                "child_count": child_count,
            })
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403

    return jsonify({
        "items": items,
        "path": str(sub).replace("\\", "/"),
        "base": str(base_dir),
        "parent": str(Path(sub).parent).replace("\\", "/") if sub else None,
    })


@bp.route("/api/files/download")
def download_file():
    """Tải file về thiết bị."""
    cfg = load_cfg()
    base_dir = Path(cfg.get("path") or "./Downloaded").expanduser().resolve()
    file_path = request.args.get("path", "").strip().lstrip("/\\")

    if not file_path:
        return jsonify({"error": "No path"}), 400

    target = (base_dir / file_path).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        return jsonify({"error": "Access denied"}), 403

    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404

    mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return send_file(
        str(target),
        mimetype=mime,
        as_attachment=True,
        download_name=target.name,
    )


@bp.route("/api/files/preview")
def preview_file():
    """Phục vụ file để xem trước ngay trong trình duyệt (inline, hỗ trợ tua video)."""
    cfg = load_cfg()
    base_dir = Path(cfg.get("path") or "./Downloaded").expanduser().resolve()
    file_path = request.args.get("path", "").strip().lstrip("/\\")

    if not file_path:
        return jsonify({"error": "No path"}), 400

    target = (base_dir / file_path).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        return jsonify({"error": "Access denied"}), 403

    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404

    mime = mimetypes.guess_type(str(target))[0]
    if not mime:
        # Cho phép xem văn bản/phụ đề dưới dạng text
        if target.suffix.lower() in (".srt", ".ass", ".vtt", ".txt", ".log"):
            mime = "text/plain; charset=utf-8"
        else:
            mime = "application/octet-stream"

    # conditional=True cho phép HTTP Range request → tua/seek video, audio
    return send_file(
        str(target),
        mimetype=mime,
        as_attachment=False,
        conditional=True,
        download_name=target.name,
    )


@bp.route("/api/files/open", methods=["POST"])
def open_in_explorer():
    """Mở thư mục chứa file trong trình quản lý file của HĐH (tool chạy local).

    - File  → mở Explorer/Finder và highlight file đó.
    - Thư mục → mở thẳng thư mục.
    """
    import sys
    import subprocess

    cfg = load_cfg()
    base_dir = Path(cfg.get("path") or "./Downloaded").expanduser().resolve()
    data = request.json or {}
    file_path = str(data.get("path") or "").strip().lstrip("/\\")

    target = (base_dir / file_path).resolve() if file_path else base_dir
    try:
        target.relative_to(base_dir)
    except ValueError:
        return jsonify({"ok": False, "error": "Access denied"}), 403

    if not target.exists():
        return jsonify({"ok": False, "error": "Không tìm thấy đường dẫn"}), 404

    try:
        if sys.platform.startswith("win"):
            if target.is_file():
                # /select, highlight file trong Explorer
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]  # chỉ có trên Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file()
                             else ["open", str(target)])
        else:
            folder = target if target.is_dir() else target.parent
            subprocess.Popen(["xdg-open", str(folder)])
        return jsonify({"ok": True, "path": str(target)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/files/delete", methods=["POST"])
def delete_file():
    """Xóa file."""
    cfg = load_cfg()
    base_dir = Path(cfg.get("path") or "./Downloaded").expanduser().resolve()
    data = request.json or {}
    file_path = str(data.get("path") or "").strip().lstrip("/\\")

    if not file_path:
        return jsonify({"error": "No path"}), 400

    target = (base_dir / file_path).resolve()
    try:
        target.relative_to(base_dir)
    except ValueError:
        return jsonify({"error": "Access denied"}), 403

    if not target.exists():
        return jsonify({"error": "Not found"}), 404

    try:
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size/1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size/1024**2:.1f} MB"
    return f"{size/1024**3:.2f} GB"



# ── /api/history ──────────────────────────────────────────────────────────────
@bp.route("/api/history", methods=["GET"])
def get_history():
    cfg = load_cfg()
    db_path = cfg.get("database_path", "dy_downloader.db") or "dy_downloader.db"

    async def fetch():
        from storage import Database
        db = Database(db_path=db_path)
        await db.initialize()
        conn = await db._get_conn()
        cur = await conn.execute(
            "SELECT download_time,url,url_type,total_count,success_count "
            "FROM download_history ORDER BY id DESC LIMIT 200"
        )
        rows = await cur.fetchall()
        await db.close()
        return rows

    try:
        rows = asyncio.run(fetch())
        data = []
        for r in rows:
            ts = datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d %H:%M") if r[0] else "—"
            data.append({"time": ts, "url": r[1], "type": r[2], "total": r[3], "success": r[4]})
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/history/clear", methods=["POST"])
def clear_history():
    cfg = load_cfg()
    db_path = cfg.get("database_path", "dy_downloader.db") or "dy_downloader.db"

    async def do():
        from storage import Database
        db = Database(db_path=db_path)
        await db.initialize()
        conn = await db._get_conn()
        await conn.execute("DELETE FROM download_history")
        await conn.commit()
        await db.close()

    asyncio.run(do())
    return jsonify({"ok": True})


# ── SocketIO: start_download ──────────────────────────────────────────────────
def register_socketio_handlers():
    """Call this after socketio is bound to the app."""

    @socketio.on("start_download")
    def handle_download(data):
        if _ca._dl_running:
            emit("log", {"msg": "Already running", "level": "warning"})
            return
        _ca._dl_running = True
        sid = request.sid
        use_queue = (data or {}).get("use_queue", False)
        extra_url = (data or {}).get("extra_url", "").strip()
        post_process = (data or {}).get("post_process") or {}

        def run():
            try:
                from config import ConfigLoader
                from auth import CookieManager
                from storage import Database, FileManager
                from control import QueueManager, RateLimiter, RetryHandler
                from core import DouyinAPIClient, URLParser, DownloaderFactory
                from core.downloader_base import DownloadResult
                from utils.logger import set_console_log_level
                import json as _j
                set_console_log_level(logging.CRITICAL)

                prog = SocketProgress(sid)
                config = ConfigLoader(str(CONFIG_FILE))

                # build URL list
                queue_snapshot = []
                if use_queue:
                    with _queue_lock:
                        queue_snapshot = list(_dl_queue)
                        urls = [i["url"] for i in queue_snapshot]
                elif extra_url:
                    urls = [extra_url]
                else:
                    urls = config.get_links()

                if not urls:
                    prog.print_error("No URLs to download")
                    return

                config.update(link=urls)

                if queue_snapshot:
                    custom_titles = {}
                    for item in queue_snapshot:
                        item_url = str(item.get("url") or "").strip()
                        item_desc = str(item.get("desc") or "").strip()
                        if not item_url or not item_desc:
                            continue
                        parsed_item = URLParser.parse(item_url) or {}
                        aweme_id = str(parsed_item.get("aweme_id") or "").strip()
                        if aweme_id:
                            custom_titles[aweme_id] = item_desc
                    if custom_titles:
                        config.update(custom_titles=custom_titles)

                vp_cfg = dict(config.get("video_process") or {})
                tr_cfg = dict(config.get("translation") or {})
                transcript_cfg = dict(config.get("transcript") or {})
                pp_enabled = bool(post_process.get("enabled", True))
                if pp_enabled:
                    vp_cfg.update({
                        "enabled": True,
                        "burn_subs": bool(post_process.get("burn_subs", True)),
                        "translate_subs": bool(post_process.get("translate_subs", True)),
                        "burn_vi_subs": bool(post_process.get("burn_vi_subs", True)),
                        "voice_convert": bool(post_process.get("voice_convert", True)),
                        "keep_bg_music": bool(post_process.get("keep_bg_music", True)),
                    })
                    translate_provider = str(post_process.get("translate_provider") or "").strip()
                    if translate_provider:
                        if translate_provider == "auto":
                            translate_provider = tr_cfg.get("preferred_provider") or "auto"
                        tr_cfg["preferred_provider"] = translate_provider
                    groq_api_key = str(post_process.get("groq_api_key") or "").strip()
                    groq_model = str(post_process.get("groq_model") or "").strip()
                    if groq_api_key:
                        transcript_cfg["groq_api_key"] = groq_api_key
                    if groq_model:
                        transcript_cfg["groq_model"] = groq_model
                elif post_process:
                    vp_cfg.update({"enabled": False})

                if vp_cfg:
                    config.update(video_process=vp_cfg)
                if tr_cfg:
                    config.update(translation=tr_cfg)
                if transcript_cfg:
                    config.update(transcript=transcript_cfg)

                if not config.validate():
                    prog.print_error("Invalid config")
                    return

                cm = CookieManager()
                cm.set_cookies(get_cookies_with_fallback())
                if not cm.validate_cookies():
                    prog.print_warning("Cookies may be invalid")

                db = None
                if config.get("database"):
                    db = Database(db_path=str(config.get("database_path", "dy_downloader.db")))

                async def _run():
                    if db:
                        await db.initialize()
                        prog.print_success("Database initialized")
                    prog.print_info(f"Found {len(urls)} URL(s)")
                    prog.start_download_session(len(urls))
                    results = []
                    try:
                        for i, url in enumerate(urls, 1):
                            prog.start_url(i, len(urls), url)
                            orig = url
                            socketio.emit("downloading_url", {"url": orig, "index": i, "total": len(urls)}, to=sid)
                            socketio.emit("queue_item_state", {"url": orig, "state": "running"}, to=sid)
                            try:
                                fm = FileManager(config.get("path"))
                                rl = RateLimiter(max_per_second=float(config.get("rate_limit", 5) or 5))
                                rh = RetryHandler(max_retries=config.get("retry_times", 3))
                                qm = QueueManager(max_workers=int(config.get("thread", 5) or 5))
                                from core.proxy_resolver import resolve_proxy as _resolve_proxy
                                # ── Nền tảng khác Douyin (TikTok/YouTube/...) → yt-dlp ──
                                from core.multi_platform import (
                                    is_douyin as _is_dy,
                                    detect_platform as _detect_pf,
                                    download_video as _dl_generic,
                                )
                                if not _is_dy(url):
                                    pf = _detect_pf(url)
                                    prog.advance_step("解析链接", pf)
                                    prog.advance_step("创建下载器", pf)
                                    out_dir = config.get("path") or "./Downloaded"

                                    def _yt_hook(d, _pf=pf):
                                        try:
                                            if d.get("status") == "downloading":
                                                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                                                done = d.get("downloaded_bytes") or 0
                                                pct = int(done / total * 100) if total else 0
                                                prog._emit("progress", {"type": "step", "pct": pct,
                                                                        "label": f"{_pf} {pct}%"})
                                        except Exception:
                                            pass

                                    prog.advance_step("执行下载", "")
                                    dl_res = await asyncio.to_thread(
                                        _dl_generic, url, out_dir,
                                        cookiefile=None,
                                        proxy=_resolve_proxy(config),
                                        progress_hook=_yt_hook,
                                    )
                                    prog.advance_step("记录历史", "")
                                    if dl_res.get("ok"):
                                        rr = DownloadResult()
                                        rr.total = 1
                                        rr.success = 1
                                        if db:
                                            await db.add_history({
                                                "url": orig, "url_type": pf,
                                                "total_count": 1, "success_count": 1,
                                                "config": "{}",
                                            })
                                        results.append(rr)
                                        prog.print_success(f"{pf}: {dl_res.get('title') or dl_res.get('file')}")
                                        prog.complete_url(rr)
                                        socketio.emit("queue_item_state", {"url": orig, "state": "success"}, to=sid)
                                        if use_queue:
                                            with _queue_lock:
                                                for idx2, qi in enumerate(_dl_queue):
                                                    if qi["url"] == orig:
                                                        del _dl_queue[idx2]
                                                        break
                                            socketio.emit("queue_update", list(_dl_queue), to=sid)
                                    else:
                                        socketio.emit("queue_item_state", {"url": orig, "state": "failed"}, to=sid)
                                        prog.fail_url(dl_res.get("error") or "download failed")
                                    continue

                                async with DouyinAPIClient(cm.get_cookies(), proxy=_resolve_proxy(config)) as api:
                                    prog.advance_step("解析链接", "")
                                    if url.startswith("https://v.douyin.com"):
                                        r = await api.resolve_short_url(url)
                                        if r:
                                            url = r
                                    parsed = URLParser.parse(url)
                                    if not parsed:
                                        prog.fail_url("URL parse failed")
                                        continue
                                    prog.advance_step("创建下载器", parsed["type"])
                                    dl = DownloaderFactory.create(
                                        parsed["type"], config, api, fm, cm, db, rl, rh, qm,
                                        progress_reporter=prog
                                    )
                                    if not dl:
                                        prog.fail_url("No downloader")
                                        continue
                                    prog.advance_step("执行下载", "")
                                    result = await dl.download(parsed)
                                    prog.advance_step("记录历史", "")
                                    if result and db:
                                        safe = {k: v for k, v in config.config.items()
                                                if k not in ("cookies", "cookie", "transcript")}
                                        await db.add_history({
                                            "url": orig, "url_type": parsed["type"],
                                            "total_count": result.total, "success_count": result.success,
                                            "config": _j.dumps(safe, ensure_ascii=False),
                                        })
                                    prog.advance_step("收尾", "")
                                    if result:
                                        results.append(result)
                                        prog.complete_url(result)
                                        socketio.emit("queue_item_state", {"url": orig, "state": "success"}, to=sid)
                                        if use_queue:
                                            with _queue_lock:
                                                for idx2, qi in enumerate(_dl_queue):
                                                    if qi["url"] == orig:
                                                        del _dl_queue[idx2]
                                                        break
                                            socketio.emit("queue_update", list(_dl_queue), to=sid)
                                    else:
                                        socketio.emit("queue_item_state", {"url": orig, "state": "failed"}, to=sid)
                                        prog.fail_url("No result")
                            except Exception as e:
                                socketio.emit("queue_item_state", {"url": orig, "state": "failed"}, to=sid)
                                prog.fail_url(str(e))
                                prog.print_error(str(e))
                    finally:
                        prog.stop_download_session()
                        if db:
                            await db.close()
                    if results:
                        tot = DownloadResult()
                        for r in results:
                            tot.total += r.total
                            tot.success += r.success
                            tot.failed += r.failed
                            tot.skipped += r.skipped
                        prog.show_result(tot)
                    socketio.emit("done", {"ok": True}, to=sid)

                asyncio.run(_run())
            except Exception as e:
                socketio.emit("log", {"msg": f"Fatal: {e}", "level": "error"}, to=sid)
                socketio.emit("done", {"ok": False}, to=sid)
            finally:
                _ca._dl_running = False

        threading.Thread(target=run, daemon=True).start()

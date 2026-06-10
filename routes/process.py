"""Process Blueprint — /api/process_video, /api/upload_anti_fp_image, /api/make_vertical_video."""
import asyncio
import tempfile
import time
import json as _j
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context
from core_app import load_cfg, CONFIG_FILE, ROOT, get_cookies_with_fallback, _resolve_naming_title

bp = Blueprint("process", __name__)

# ── Pause/Resume state ────────────────────────────────────────────────────────
import threading as _threading

_proc_pause_event = _threading.Event()
_proc_pause_event.set()  # not paused by default
_proc_review_event = _threading.Event()
_proc_review_event.set()  # not waiting for review by default

# Thumbnail config được set bởi user khi chọn từ modal sau review ASS.
# Pipeline sẽ đọc dict này thay vì giá trị ban đầu trong request body.
_proc_thumb_override: dict = {}
_proc_thumb_lock = _threading.Lock()

# State cho retry thumbnail khi AI fail.
# Pipeline emit thumb_failed → đợi user resolve qua /api/proc_retry_thumb.
_proc_thumb_retry_event = _threading.Event()
_proc_thumb_retry_event.set()  # not waiting by default
_proc_thumb_retry_action: dict = {}  # {action: 'retry'|'upload'|'skip', path?: str}
_proc_thumb_retry_lock = _threading.Lock()


@bp.route("/api/proc_retry_thumb", methods=["POST"])
def proc_retry_thumb():
    """User chọn cách xử lý khi AI thumbnail fail.

    Body:
      action: 'retry' | 'upload' | 'skip'
      path:   (chỉ với action='upload') đường dẫn server của ảnh user upload
    """
    data = request.json or {}
    action = str(data.get("action") or "").strip().lower()
    if action not in ("retry", "upload", "skip"):
        return jsonify({"ok": False, "error": "Invalid action"}), 400
    payload = {"action": action}
    if action == "upload":
        path_str = str(data.get("path") or "").strip()
        if not path_str:
            return jsonify({"ok": False, "error": "Missing path for upload action"}), 400
        payload["path"] = path_str
    with _proc_thumb_retry_lock:
        _proc_thumb_retry_action.clear()
        _proc_thumb_retry_action.update(payload)
    _proc_thumb_retry_event.set()
    return jsonify({"ok": True})


def wait_thumb_retry_action(timeout: float = 600.0) -> dict:
    """Pipeline gọi để đợi user resolve thumbnail failure.

    Trả về {'action': 'retry'|'upload'|'skip', 'path'?: str}.
    Nếu timeout → trả {'action': 'skip'}.
    """
    _proc_thumb_retry_event.clear()
    got = _proc_thumb_retry_event.wait(timeout=timeout)
    _proc_thumb_retry_event.set()
    if not got:
        return {"action": "skip"}
    with _proc_thumb_retry_lock:
        cfg = dict(_proc_thumb_retry_action)
        _proc_thumb_retry_action.clear()
    return cfg or {"action": "skip"}


@bp.route("/api/proc_set_thumb", methods=["POST"])
def proc_set_thumb():
    """Set thumbnail config from frontend modal (sau khi review ASS xong).

    Pipeline đọc giá trị này để override config thumbnail trước khi tạo.
    Reset sau mỗi lần đọc để tránh leak giữa các video trong batch.
    """
    data = request.json or {}
    cfg = {
        "thumb_enabled": bool(data.get("thumb_enabled")),
        "thumb_mode": str(data.get("thumb_mode") or "none").lower(),
        "thumb_path": str(data.get("thumb_path") or "").strip(),
        "thumb_title": str(data.get("thumb_title") or "").strip(),
        "thumb_duration": float(data.get("thumb_duration") or 2.0),
        "thumb_timestamp": float(data.get("thumb_timestamp") or 5.0),
    }
    with _proc_thumb_lock:
        _proc_thumb_override.clear()
        _proc_thumb_override.update(cfg)
    return jsonify({"ok": True})


def get_proc_thumb_override() -> dict:
    """Pop thumbnail config that user picked. Returns {} if not set."""
    with _proc_thumb_lock:
        cfg = dict(_proc_thumb_override)
        _proc_thumb_override.clear()
    return cfg


@bp.route("/api/proc_resume", methods=["POST"])
def proc_resume():
    """Signal the processing pipeline to pause, resume, or continue after review."""
    data = request.json or {}
    action = str(data.get("action") or "").strip().lower()
    if action == "pause":
        _proc_pause_event.clear()
        return jsonify({"ok": True, "state": "paused"})
    elif action == "resume":
        _proc_pause_event.set()
        return jsonify({"ok": True, "state": "running"})
    elif action == "continue":
        _proc_review_event.set()
        _proc_pause_event.set()
        return jsonify({"ok": True, "state": "continued"})
    return jsonify({"ok": False, "error": "Unknown action"}), 400


@bp.route("/api/proc_read_ass", methods=["POST"])
def proc_read_ass():
    """Read an ASS subtitle file for review."""
    data = request.json or {}
    path_str = str(data.get("path") or "").strip()
    if not path_str:
        return jsonify({"ok": False, "error": "Missing path"}), 400
    p = Path(path_str)
    if not p.exists():
        return jsonify({"ok": False, "error": "File not found"}), 404
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return jsonify({"ok": True, "content": content})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/proc_save_ass", methods=["POST"])
def proc_save_ass():
    """Save edited ASS subtitle file after review."""
    data = request.json or {}
    path_str = str(data.get("path") or "").strip()
    content  = str(data.get("content") or "")
    if not path_str:
        return jsonify({"ok": False, "error": "Missing path"}), 400
    p = Path(path_str)
    try:
        p.write_text(content, encoding="utf-8")
        return jsonify({"ok": True, "path": str(p.resolve()), "mtime": p.stat().st_mtime})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/video_frame", methods=["POST"])
def video_frame():
    """Extract a frame from a video at a given timestamp and return as base64 JPEG.
    Handles Unicode filenames by copying to temp dir with safe name."""
    import base64
    import subprocess
    import shutil
    from core.video_processor import find_ffmpeg

    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    timestamp = float(data.get("timestamp") or 0.0)

    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    vp = Path(video_path_str).expanduser()
    if not vp.is_absolute():
        vp = ROOT / vp
    if not vp.exists():
        return jsonify({"ok": False, "error": f"Video không tồn tại: {vp}"}), 404

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

    try:
        with tempfile.TemporaryDirectory(prefix="vframe_") as tmpdir:
            # Copy video to temp with safe ASCII name to avoid Unicode path issues
            tmp_video = Path(tmpdir) / f"input{vp.suffix}"
            shutil.copy2(str(vp), str(tmp_video))

            tmp_jpg = Path(tmpdir) / "frame.jpg"

            result = subprocess.run([
                ffmpeg, "-ss", str(timestamp),
                "-i", str(tmp_video),
                "-vframes", "1",
                "-q:v", "2",
                "-vf", "scale=720:-1",
                str(tmp_jpg), "-y", "-loglevel", "error"
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

            if not tmp_jpg.exists() or tmp_jpg.stat().st_size == 0:
                err_msg = (result.stderr or "").strip()[:200] if result else ""
                return jsonify({"ok": False, "error": f"Không thể extract frame. {err_msg}"}), 500

            with open(tmp_jpg, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

        return jsonify({"ok": True, "image": f"data:image/jpeg;base64,{img_b64}"})

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Timeout khi extract frame (>30s)"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/video_filmstrip", methods=["POST"])
def video_filmstrip():
    """Extract N evenly-spaced small thumbnails from a local video for the
    editor timeline filmstrip. Returns the duration and a list of base64 JPEGs.

    Body: { video_path: str, count?: int }
    Resp: { ok, duration, count, frames: [dataURL, ...] }
    """
    import base64
    import subprocess
    import shutil
    from core.video_processor import find_ffmpeg
    from utils.ffprobe import probe_video

    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    try:
        count = int(data.get("count") or 12)
    except (TypeError, ValueError):
        count = 12
    count = max(4, min(40, count))

    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    vp = Path(video_path_str).expanduser()
    if not vp.is_absolute():
        vp = ROOT / vp
    if not vp.exists():
        return jsonify({"ok": False, "error": f"Video không tồn tại: {vp}"}), 404

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

    # Duration (best effort)
    try:
        _w, _h, duration = probe_video(vp)
    except Exception:
        duration = 0.0
    if not duration or duration <= 0:
        duration = 0.0

    try:
        with tempfile.TemporaryDirectory(prefix="vstrip_") as tmpdir:
            tmp_video = Path(tmpdir) / f"input{vp.suffix}"
            shutil.copy2(str(vp), str(tmp_video))

            frames: list[str] = []

            if duration > 0:
                # Single pass: evenly spaced frames via fps filter.
                fps_expr = f"{count}/{duration:.6f}"
                out_pat = Path(tmpdir) / "f_%03d.jpg"
                subprocess.run([
                    ffmpeg, "-i", str(tmp_video),
                    "-vf", f"fps={fps_expr},scale=160:-1",
                    "-frames:v", str(count),
                    "-q:v", "5",
                    str(out_pat), "-y", "-loglevel", "error"
                ], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=60)
                for i in range(1, count + 1):
                    fp = Path(tmpdir) / f"f_{i:03d}.jpg"
                    if fp.exists() and fp.stat().st_size > 0:
                        with open(fp, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                        frames.append(f"data:image/jpeg;base64,{b64}")
            else:
                # Unknown duration: grab a few frames by seeking small offsets.
                for i in range(count):
                    ts = i * 2.0
                    fp = Path(tmpdir) / f"f_{i:03d}.jpg"
                    subprocess.run([
                        ffmpeg, "-ss", str(ts), "-i", str(tmp_video),
                        "-vframes", "1", "-q:v", "5",
                        "-vf", "scale=160:-1",
                        str(fp), "-y", "-loglevel", "error"
                    ], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=20)
                    if fp.exists() and fp.stat().st_size > 0:
                        with open(fp, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                        frames.append(f"data:image/jpeg;base64,{b64}")

            if not frames:
                return jsonify({"ok": False, "error": "Không tạo được dải khung hình"}), 500

        return jsonify({
            "ok": True,
            "duration": round(duration, 3),
            "count": len(frames),
            "frames": frames,
        })

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Timeout khi tạo filmstrip (>60s)"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/video_frame_from_url", methods=["POST"])
def video_frame_from_url():
    """Fetch thumbnail/cover from video URL via Douyin API."""
    data = request.json or {}
    url = str(data.get("url") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "Chưa nhập URL video"}), 400

    # Fetch thumbnail/cover from URL via Douyin API
    thumb_result = _fetch_thumbnail_from_url(url)
    if thumb_result:
        return jsonify(thumb_result)

    return jsonify({"ok": False, "error": "Không lấy được thumbnail từ URL"}), 404


def _fetch_thumbnail_from_url(url: str) -> dict | None:
    """Fetch video thumbnail/cover image from Douyin API given a video URL."""
    import re
    import base64
    import httpx
    from urllib.parse import urlparse, parse_qs

    try:
        from config import ConfigLoader
        from auth import CookieManager
        from core import DouyinAPIClient, URLParser

        cfg_loader = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())

        def _pick_url(raw: str) -> str:
            text = str(raw or "").strip()
            if not text:
                return ""
            m = re.search(r"https?://[^\s]+", text)
            if m:
                return m.group(0).rstrip("\"'.,;)")
            if text.startswith("v.douyin.com/") or text.startswith("www.douyin.com/"):
                return "https://" + text
            return text

        def _extract_aweme_id(u: str, parsed: dict | None) -> str:
            if parsed:
                aid = str(parsed.get("aweme_id") or "").strip()
                if aid:
                    return aid
            qs = parse_qs(urlparse(u).query or "")
            for key in ("modal_id", "item_id", "group_id", "aweme_id"):
                val = str((qs.get(key) or [""])[0]).strip()
                if val.isdigit():
                    return val
            m = re.search(r"/(?:video|note|gallery|slides|share/video)/(\d{15,20})", u)
            if m:
                return m.group(1)
            return ""

        async def _do_fetch():
            from core.proxy_resolver import resolve_proxy
            async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(cfg_loader)) as api:
                normalized_url = _pick_url(url)
                if not normalized_url:
                    return None

                resolved_url = normalized_url
                if "v.douyin.com" in resolved_url:
                    redirected = await api.resolve_short_url(resolved_url)
                    if redirected:
                        resolved_url = redirected

                parsed = URLParser.parse(resolved_url)
                aweme_id = _extract_aweme_id(resolved_url, parsed)
                if not aweme_id:
                    aweme_id = _extract_aweme_id(normalized_url, URLParser.parse(normalized_url))
                if not aweme_id:
                    return None

                detail = await api.get_video_detail(aweme_id)
                if not detail:
                    return None

                # Extract cover URL — prefer static images (origin_cover, cover) over animated (dynamic_cover)
                video_info = detail.get("video") or {}
                cover_url = ""
                for field in ("origin_cover", "cover"):
                    ul = (video_info.get(field) or {}).get("url_list") or []
                    if ul:
                        cover_url = ul[0]
                        break

                if not cover_url:
                    # Try images (gallery post)
                    imgs = detail.get("images") or []
                    if imgs:
                        ul = (imgs[0].get("url_list") or [])
                        if ul:
                            cover_url = ul[0]

                if not cover_url:
                    return None

                return cover_url, detail.get("desc") or "video"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_do_fetch())
        finally:
            loop.close()

        if not result:
            return None

        cover_url, title = result

        # Download the cover image and convert to base64
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(cover_url)
            if resp.status_code == 200 and len(resp.content) > 0:
                content_type = resp.headers.get("content-type", "image/jpeg")
                if "webp" in content_type:
                    mime = "image/webp"
                elif "png" in content_type:
                    mime = "image/png"
                else:
                    mime = "image/jpeg"
                img_b64 = base64.b64encode(resp.content).decode()
                return {
                    "ok": True,
                    "image": f"data:{mime};base64,{img_b64}",
                    "video_name": title,
                    "source": "thumbnail",
                }

    except Exception:
        pass

    return None


@bp.route("/api/upload_anti_fp_image", methods=["POST"])
def upload_anti_fp_image():
    """Upload an overlay / logo image for anti-fingerprint processing."""
    from utils.validators import sanitize_filename

    upload_file = request.files.get("file") if request.files else None
    if not upload_file or not upload_file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    img_type = str(request.form.get("type") or "overlay")
    safe_name = sanitize_filename(upload_file.filename)
    upload_dir = ROOT / "temp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    save_path = upload_dir / f"anti-fp-{img_type}-{safe_name}"
    upload_file.save(str(save_path))

    return jsonify({"ok": True, "path": str(save_path)})


@bp.route("/api/upload_batch_video", methods=["POST"])
def upload_batch_video():
    """Upload a video file for batch publishing. Returns server path."""
    from utils.validators import sanitize_filename

    upload_file = request.files.get("file") if request.files else None
    if not upload_file or not upload_file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    safe_name = sanitize_filename(upload_file.filename)
    upload_dir = ROOT / "temp_uploads" / "batch_pub"
    upload_dir.mkdir(parents=True, exist_ok=True)

    save_path = upload_dir / safe_name
    # Avoid overwrite
    if save_path.exists():
        import time as _time
        stem = save_path.stem
        save_path = upload_dir / f"{stem}_{int(_time.time())}{save_path.suffix}"

    upload_file.save(str(save_path))
    return jsonify({"ok": True, "path": str(save_path)})


@bp.route("/api/upload_process_video", methods=["POST"])
def upload_process_video():
    """Upload a video file. Each video gets its own subfolder under
    Downloaded/Process_video/<video_name>/ so processed outputs are grouped
    per video. If the same video name is uploaded again, it goes into the
    same folder (resume cache works)."""
    from utils.validators import sanitize_filename

    upload_file = request.files.get("file") if request.files else None
    if not upload_file or not upload_file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    cfg = load_cfg()
    download_dir_str = str(cfg.get("path") or "./Downloaded").strip()
    base_dir = Path(download_dir_str).expanduser()
    if not base_dir.is_absolute():
        base_dir = ROOT / base_dir

    # Per-video folder: Downloaded/Process_video/<safe_stem>/
    # Dùng cùng logic _safe_stem (slugify ASCII, max 60 chars) như pipeline
    # để folder + tên file đồng bộ + tránh vượt MAX_PATH 260 trên Windows.
    from core.video_processor import _safe_stem
    original_name = Path(upload_file.filename).name
    raw_stem = Path(original_name).stem
    suffix = Path(original_name).suffix.lower() or ".mp4"
    safe_stem = _safe_stem(raw_stem)

    video_dir = base_dir / "Process_video" / safe_stem
    video_dir.mkdir(parents=True, exist_ok=True)

    # Tên file lưu cũng dùng safe_stem để khớp với folder và tránh tên dài
    save_path = video_dir / f"{safe_stem}{suffix}"

    # If the same file already exists in this folder, keep it (don't overwrite
    # to preserve resume cache). User can manually delete if they want a fresh start.
    if save_path.exists() and save_path.stat().st_size > 0:
        return jsonify({
            "ok": True,
            "path": str(save_path.resolve()),
            "name": save_path.name,
            "dir": str(video_dir.resolve()),
            "reused": True,
        })

    upload_file.save(str(save_path))
    return jsonify({
        "ok": True,
        "path": str(save_path.resolve()),
        "name": save_path.name,
        "dir": str(video_dir.resolve()),
        "reused": False,
    })


@bp.route("/api/read_subtitle", methods=["POST"])
def read_subtitle():
    """Read a subtitle file (.srt, .ass) from local path."""
    data = request.json or {}
    path_str = data.get("path", "").strip()
    if not path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn file"}), 400

    p = Path(path_str).expanduser()
    if not p.exists():
        return jsonify({"ok": False, "error": f"File không tồn tại: {path_str}"}), 404

    if p.suffix.lower() not in (".srt", ".ass"):
        return jsonify({"ok": False, "error": "Chỉ hỗ trợ file .srt hoặc .ass"}), 400

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return jsonify({"ok": True, "content": content, "filename": p.name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/detect_subtitles", methods=["POST"])
def detect_subtitles():
    """Find matching subtitle files in the same directory as the video."""
    data = request.json or {}
    video_path_str = data.get("video_path", "").strip()
    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    vp = Path(video_path_str).expanduser()
    if not vp.exists():
        return jsonify({"ok": False, "error": "Video không tồn tại"}), 404

    folder = vp.parent
    stem = vp.stem
    
    # Try to find subs
    # Patterns: stem.srt, stem.ass, stem_vi.ass, 
    # or if stem has a timestamp suffix like _1778256302, try removing it
    import re
    clean_stem = re.sub(r'_\d{10,}$', '', stem) # Remove timestamp suffix if exists
    
    candidates = []
    video_mtime = vp.stat().st_mtime
    
    try:
        for f in folder.iterdir():
            if f.suffix.lower() in (".srt", ".ass"):
                f_mtime = f.stat().st_mtime
                time_diff = abs(f_mtime - video_mtime)
                
                priority = 10
                # Exact match or prefix match
                if f.stem == stem or f.stem == clean_stem or f.stem.startswith(clean_stem):
                    priority -= 5
                
                # Proximity match (created around the same time, e.g. within 60s)
                if time_diff < 60:
                    priority -= 3
                
                # Language match
                if "_vi" in f.name.lower():
                    priority -= 4
                
                # Only include if there's some reasonable connection
                if priority < 10:
                    candidates.append({
                        "path": str(f.resolve()),
                        "name": f.name,
                        "priority": priority,
                        "time_diff": time_diff
                    })
    except Exception:
        pass

    # Sort by priority (lower is better)
    candidates.sort(key=lambda x: (x["priority"], x["time_diff"]))
    
    return jsonify({
        "ok": True, 
        "subtitles": candidates,
        "best_match": candidates[0]["path"] if candidates else None
    })


@bp.route("/api/process_video", methods=["POST"])
def process_video():
    data = {}
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        data.update(request.get_json(silent=True) or {})

    uploaded_file = request.files.get("video_file") if request.files else None
    if uploaded_file and uploaded_file.filename:
        from utils.validators import sanitize_filename
        upload_dir = Path(tempfile.mkdtemp(prefix="proc_upload_"))
        original_name = Path(uploaded_file.filename).name
        safe_name = sanitize_filename(Path(original_name).stem) + Path(original_name).suffix
        saved_path = upload_dir / safe_name
        uploaded_file.save(saved_path)
        data["video_path"] = str(saved_path)
        data["video_file_name"] = original_name

    def generate():
        from config import ConfigLoader
        from auth import CookieManager
        from core import DouyinAPIClient, URLParser
        from core.video_downloader import VideoDownloader
        from control import QueueManager, RateLimiter, RetryHandler
        from storage import FileManager
        from core.video_processor import process_video_full

        async def _download_video_from_url(video_url: str, out_dir: str) -> tuple:
            import re
            from urllib.parse import urlparse, parse_qs

            def _pick_url(raw: str) -> str:
                text = str(raw or "").strip()
                if not text:
                    return ""
                m = re.search(r"https?://[^\s]+", text)
                if m:
                    return m.group(0).rstrip("\"'.,;)")
                if text.startswith("v.douyin.com/") or text.startswith("www.douyin.com/"):
                    return "https://" + text
                return text

            def _extract_aweme_id(url: str, parsed_url: dict | None) -> str:
                if parsed_url:
                    aid = str(parsed_url.get("aweme_id") or "").strip()
                    if aid:
                        return aid
                qs = parse_qs(urlparse(url).query or "")
                for key in ("modal_id", "item_id", "group_id", "aweme_id"):
                    val = str((qs.get(key) or [""])[0]).strip()
                    if val.isdigit():
                        return val
                m = re.search(r"/(?:video|note|gallery|slides|share/video)/(\d{15,20})", url)
                if m:
                    return m.group(1)
                return ""

            cfg = ConfigLoader(str(CONFIG_FILE))
            cm = CookieManager()
            cm.set_cookies(get_cookies_with_fallback())
            if not cm.validate_cookies():
                raise RuntimeError("Cookies may be invalid")

            from core.proxy_resolver import resolve_proxy as _resolve_proxy
            async with DouyinAPIClient(cm.get_cookies(), proxy=_resolve_proxy(cfg)) as api:
                normalized_url = _pick_url(video_url)
                if not normalized_url:
                    raise RuntimeError("URL is empty")

                resolved_url = normalized_url
                if "v.douyin.com" in resolved_url:
                    redirected = await api.resolve_short_url(resolved_url)
                    if redirected:
                        resolved_url = redirected

                parsed = URLParser.parse(resolved_url)
                aweme_id = _extract_aweme_id(resolved_url, parsed)
                if not aweme_id:
                    aweme_id = _extract_aweme_id(normalized_url, URLParser.parse(normalized_url))
                if not aweme_id:
                    raise RuntimeError("Invalid video URL. Please use a specific Douyin post link.")

                if parsed and parsed.get("type") not in ("video", "gallery") and not aweme_id:
                    raise RuntimeError("URL is not a video post")

                aweme_data = await api.get_video_detail(aweme_id)
                if not aweme_data:
                    raise RuntimeError("Failed to fetch video detail")

                raw_title = str(aweme_data.get("desc") or "video").strip() or "video"
                resolved_title = _resolve_naming_title(raw_title)

                out_path = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")
                file_manager = FileManager(str(out_path))
                downloader = VideoDownloader(
                    config=cfg,
                    api_client=api,
                    file_manager=file_manager,
                    cookie_manager=cm,
                    database=None,
                    rate_limiter=RateLimiter(max_per_second=float(cfg.get("rate_limit", 5) or 5)),
                    retry_handler=RetryHandler(max_retries=int(cfg.get("retry_times", 3) or 3)),
                    queue_manager=QueueManager(max_workers=1),
                    progress_reporter=None,
                )

                if downloader._detect_media_type(aweme_data) != "video":
                    raise RuntimeError("URL is not a video post")

                play_info = downloader._build_no_watermark_url(aweme_data)
                if not play_info:
                    raise RuntimeError("No playable video URL found")

                play_url, headers = play_info
                from utils.validators import sanitize_filename
                from core.video_processor import _safe_stem

                # Slugify title sang ASCII + giới hạn chiều dài để folder + tên file
                # nhất quán và không vượt MAX_PATH trên Windows.
                slug = _safe_stem(resolved_title)
                base_name = f"{slug}_{aweme_id}"
                # Lưu vào Downloaded/Process_video/<base_name>/<base_name>.mp4
                # cùng cấu trúc với upload manual để pipeline xử lý nhất quán.
                save_dir = out_path / "Process_video" / base_name
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{base_name}.mp4"

                if save_path.exists():
                    save_path = save_dir / f"{base_name}_{int(time.time())}.mp4"

                session = await api.get_session()
                ok = await file_manager.download_file(
                    play_url, save_path, session,
                    headers=headers, proxy=api.proxy,
                )
                if not ok or not save_path.exists():
                    raise RuntimeError("Download failed")

                return save_path.resolve(), resolved_title

        try:
            req = dict(data or {})
            video_path = str(req.get("video_path") or "").strip()
            video_url = str(req.get("video_url") or "").strip()
            req.setdefault("cleanup_outputs", True)
            req.setdefault("delete_source_after_process", False)

            if not video_path and video_url:
                yield _j.dumps({"log": f"Resolving URL: {video_url}", "level": "info"}, ensure_ascii=False) + "\n"
                yield _j.dumps({"overall": 2, "overall_lbl": "Resolving URL..."}, ensure_ascii=False) + "\n"
                try:
                    downloaded_path, downloaded_title = asyncio.run(
                        _download_video_from_url(video_url, str(req.get("out_dir") or "").strip())
                    )
                    req["video_path"] = str(downloaded_path)
                    req["video_title"] = downloaded_title
                    req["delete_source_after_process"] = True
                    yield _j.dumps({"log": f"Downloaded video: {downloaded_path}", "level": "success"}, ensure_ascii=False) + "\n"
                    yield _j.dumps({"overall": 4, "overall_lbl": "Download done, start processing..."}, ensure_ascii=False) + "\n"
                except Exception as e:
                    yield _j.dumps({"log": f"URL download failed: {e}", "level": "error"}, ensure_ascii=False) + "\n"
                    yield _j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=False) + "\n"
                    return
            elif not video_path:
                yield _j.dumps({"log": "Please provide video_path or video_url", "level": "error"}, ensure_ascii=False) + "\n"
                yield _j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=False) + "\n"
                return

            for line in process_video_full(req):
                yield line
        except Exception as e:
            yield _j.dumps({"log": f"Fatal error: {e}", "level": "error"}, ensure_ascii=False) + "\n"
            yield _j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=False) + "\n"

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


@bp.route("/api/download_original_video", methods=["POST"])
def download_original_video():
    """Download video from URL and save it to the output folder."""
    data = request.json or {}
    video_url = str(data.get("url") or "").strip()
    out_dir = str(data.get("out_dir") or "").strip()

    if not video_url:
        return jsonify({"ok": False, "error": "Chưa nhập URL video"}), 400

    from config import ConfigLoader
    from auth import CookieManager
    from core import DouyinAPIClient, URLParser
    from core.video_downloader import VideoDownloader
    from control import QueueManager, RateLimiter, RetryHandler
    from storage import FileManager
    import re
    from urllib.parse import urlparse, parse_qs

    def _pick_url(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        m = re.search(r"https?://[^\s]+", text)
        if m:
            return m.group(0).rstrip("\"'.,;)")
        if text.startswith("v.douyin.com/") or text.startswith("www.douyin.com/"):
            return "https://" + text
        return text

    def _extract_aweme_id(url: str, parsed_url: dict | None) -> str:
        if parsed_url:
            aid = str(parsed_url.get("aweme_id") or "").strip()
            if aid:
                return aid
        qs = parse_qs(urlparse(url).query or "")
        for key in ("modal_id", "item_id", "group_id", "aweme_id"):
            val = str((qs.get(key) or [""])[0]).strip()
            if val.isdigit():
                return val
        m = re.search(r"/(?:video|note|gallery|slides|share/video)/(\d{15,20})", url)
        if m:
            return m.group(1)
        return ""

    async def _do_download():
        cfg = ConfigLoader(str(CONFIG_FILE))
        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        if not cm.validate_cookies():
            raise RuntimeError("Cookies may be invalid")

        from core.proxy_resolver import resolve_proxy as _resolve_proxy
        async with DouyinAPIClient(cm.get_cookies(), proxy=_resolve_proxy(cfg)) as api:
            normalized_url = _pick_url(video_url)
            if not normalized_url:
                raise RuntimeError("URL is empty")

            resolved_url = normalized_url
            if "v.douyin.com" in resolved_url:
                redirected = await api.resolve_short_url(resolved_url)
                if redirected:
                    resolved_url = redirected

            parsed = URLParser.parse(resolved_url)
            aweme_id = _extract_aweme_id(resolved_url, parsed)
            if not aweme_id:
                aweme_id = _extract_aweme_id(normalized_url, URLParser.parse(normalized_url))
            if not aweme_id:
                raise RuntimeError("Invalid video URL. Please use a specific Douyin post link.")

            if parsed and parsed.get("type") not in ("video", "gallery") and not aweme_id:
                raise RuntimeError("URL is not a video post")

            aweme_data = await api.get_video_detail(aweme_id)
            if not aweme_data:
                raise RuntimeError("Failed to fetch video detail")

            raw_title = str(aweme_data.get("desc") or "video").strip() or "video"
            resolved_title = _resolve_naming_title(raw_title)

            out_path = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")
            file_manager = FileManager(str(out_path))
            downloader = VideoDownloader(
                config=cfg,
                api_client=api,
                file_manager=file_manager,
                cookie_manager=cm,
                database=None,
                rate_limiter=RateLimiter(max_per_second=float(cfg.get("rate_limit", 5) or 5)),
                retry_handler=RetryHandler(max_retries=int(cfg.get("retry_times", 3) or 3)),
                queue_manager=QueueManager(max_workers=1),
                progress_reporter=None,
            )

            if downloader._detect_media_type(aweme_data) != "video":
                raise RuntimeError("URL is not a video post")

            play_info = downloader._build_no_watermark_url(aweme_data)
            if not play_info:
                raise RuntimeError("No playable video URL found")

            play_url, headers = play_info
            from core.video_processor import _safe_stem

            slug = _safe_stem(resolved_title)
            base_name = f"{slug}_{aweme_id}"
            save_dir = out_path / "Process_video" / base_name
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f"{base_name}.mp4"

            if save_path.exists():
                save_path = save_dir / f"{base_name}_{int(time.time())}.mp4"

            session = await api.get_session()
            ok = await file_manager.download_file(
                play_url, save_path, session,
                headers=headers, proxy=api.proxy,
            )
            if not ok or not save_path.exists():
                raise RuntimeError("Download failed")

            return save_path.resolve(), resolved_title

    try:
        loop = asyncio.new_event_loop()
        try:
            downloaded_path, downloaded_title = loop.run_until_complete(_do_download())
        finally:
            loop.close()

        return jsonify({
            "ok": True,
            "path": str(downloaded_path),
            "title": downloaded_title
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/make_vertical_video", methods=["POST"])
def make_vertical_video_route():
    """Convert landscape video to 9:16 vertical with blurred gradient layers."""
    from core.video_processor import make_vertical_video, find_ffmpeg

    data = request.json or {}
    video_path = data.get("video_path", "").strip()
    if not video_path:
        return jsonify({"ok": False, "error": "Thiếu video_path"}), 400

    vp = Path(video_path).expanduser()
    if not vp.exists():
        return jsonify({"ok": False, "error": f"File không tồn tại: {vp}"}), 404

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "ffmpeg không tìm thấy"}), 500

    out_dir = Path(data.get("out_dir", "")).expanduser() if data.get("out_dir") else vp.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{vp.stem}_vertical.mp4"

    ok, err = make_vertical_video(
        video_path=vp,
        output_path=output_path,
        ffmpeg=ffmpeg,
        title=str(data.get("title") or ""),
        title_size_pct=float(data.get("title_size_pct") or 5.0),
        title_color=str(data.get("title_color") or "#000000"),
        blur_w_pct=float(data.get("blur_w_pct") or 15.0),
        blur_opacity=float(data.get("blur_opacity") or 0.6),
        blur_mode=str(data.get("blur_mode") or "overlay"),
        logo_path=str(data.get("logo_path") or "") or None,
        logo_size_pct=float(data.get("logo_size_pct") or 12.0),
        logo_top_pct=float(data.get("logo_top_pct") or 3.0),
        logo_left_pct=float(data.get("logo_left_pct") or 3.0),
        logo_radius_pct=float(data.get("logo_radius_pct") or 50.0),        target_w=int(data.get("target_w") or 1080),
        target_h=int(data.get("target_h") or 1920),
    )

    if ok:
        return jsonify({"ok": True, "output_path": str(output_path.resolve())})
    return jsonify({"ok": False, "error": err}), 500


def _preload_whisper_model():
    """Preload faster-whisper model in background so first video processes faster."""
    try:
        import os
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        cfg = load_cfg()
        model_name = (cfg.get("video_process") or {}).get("model", "base")
        from core.video_processor import _whisper_model_cache
        if model_name not in _whisper_model_cache:
            from faster_whisper import WhisperModel
            _whisper_model_cache[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception:
        pass


@bp.route("/api/video_frame_upload", methods=["POST"])
def video_frame_upload():
    """Extract a frame from an uploaded video file at a given timestamp."""
    import base64
    import subprocess
    from core.video_processor import find_ffmpeg

    video_file = request.files.get("video_file")
    timestamp = float(request.form.get("timestamp") or 0.0)

    if not video_file:
        return jsonify({"ok": False, "error": "Chưa chọn file video"}), 400

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

    try:
        # Save uploaded video to temp
        upload_dir = ROOT / "temp_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        tmp_video = upload_dir / f"_frame_tmp_{video_file.filename}"
        video_file.save(str(tmp_video))

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        subprocess.run([
            ffmpeg, "-ss", str(timestamp),
            "-i", str(tmp_video),
            "-vframes", "1",
            "-q:v", "3",
            "-vf", "scale=640:-1",
            tmp_path, "-y", "-loglevel", "error"
        ], capture_output=True, timeout=15)

        if not Path(tmp_path).exists() or Path(tmp_path).stat().st_size == 0:
            tmp_video.unlink(missing_ok=True)
            return jsonify({"ok": False, "error": "Không thể extract frame"}), 500

        with open(tmp_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        Path(tmp_path).unlink(missing_ok=True)
        # Keep tmp_video for later processing
        return jsonify({"ok": True, "image": f"data:image/jpeg;base64,{img_b64}", "tmp_path": str(tmp_video)})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/burn_subtitle_only", methods=["POST"])
def burn_subtitle_only():
    """Burn subtitle + optional frame into video (upload-based, streaming progress)."""
    import shutil
    import json as _json
    from core.video_processor import burn_subtitles, find_ffmpeg

    video_file = request.files.get("video_file")
    ass_file = request.files.get("ass_file")

    if not video_file:
        return jsonify({"ok": False, "error": "Chưa chọn file video"}), 400
    if not ass_file:
        return jsonify({"ok": False, "error": "Chưa chọn file phụ đề"}), 400

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

    # Save uploads
    upload_dir = ROOT / "temp_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_video = upload_dir / f"_burn_{video_file.filename}"
    tmp_ass = upload_dir / f"_burn_{ass_file.filename}"
    video_file.save(str(tmp_video))
    ass_file.save(str(tmp_ass))

    # Parse params
    font_size_pct = float(request.form.get("font_size") or 5)
    font_size_px = max(8, int(720 * font_size_pct / 100))
    font_color = request.form.get("font_color") or "yellow"
    margin_v_pct = float(request.form.get("margin_v") or 7)
    margin_v_px = max(0, int(720 * margin_v_pct / 100))
    subtitle_position = request.form.get("subtitle_position") or "bottom"
    blur_original = request.form.get("blur_original") == "1"
    frame_enabled = request.form.get("frame_enabled") == "1"
    frame_title = request.form.get("frame_title") or ""
    frame_title_size_pct = float(request.form.get("frame_title_size_pct") or 5)
    frame_title_color = request.form.get("frame_title_color") or "#000000"
    frame_blur_w_pct = float(request.form.get("frame_blur_w_pct") or 15)
    frame_blur_opacity = float(request.form.get("frame_blur_opacity") or 0.6)

    out_dir_str = request.form.get("out_dir") or ""
    if out_dir_str:
        out_dir = Path(out_dir_str).expanduser()
    else:
        out_dir = tmp_video.parent

    stem = tmp_video.stem.replace("_burn_", "")
    output_name = f"{stem}_subbed.mp4" if not frame_enabled else f"{stem}_subbed_framed.mp4"
    output_path = out_dir / output_name

    def generate():
        logs = []

        def _log_cb(msg, level="info"):
            logs.append(_json.dumps({"log": msg, "level": level}) + "\n")

        yield _json.dumps({"log": "🚀 Bắt đầu xử lý...", "level": "info", "overall": 5, "overall_lbl": "Chuẩn bị..."}) + "\n"

        ok, err = burn_subtitles(
            video_path=tmp_video,
            srt_path=tmp_ass,
            output_path=output_path,
            ffmpeg=ffmpeg,
            blur_original=blur_original,
            font_size=font_size_px,
            font_color=font_color,
            margin_v=margin_v_px,
            subtitle_position=subtitle_position,
            subtitle_format="ass",
            frame_enabled=frame_enabled,
            frame_title=frame_title,
            frame_title_size_pct=frame_title_size_pct,
            frame_title_color=frame_title_color,
            frame_blur_w_pct=frame_blur_w_pct,
            frame_blur_opacity=frame_blur_opacity,
            log_callback=_log_cb,
        )

        # Flush all collected logs
        for log_line in logs:
            yield log_line

        if ok:
            yield _json.dumps({"log": f"✅ Hoàn tất: {output_path.name}", "level": "success", "overall": 100, "overall_lbl": "Hoàn tất!"}) + "\n"
        else:
            yield _json.dumps({"log": f"❌ Lỗi: {err}", "level": "error", "overall": 100, "overall_lbl": "Thất bại"}) + "\n"

        # Cleanup temp files
        tmp_video.unlink(missing_ok=True)
        tmp_ass.unlink(missing_ok=True)

    return Response(stream_with_context(generate()), mimetype="text/plain")


@bp.route("/api/generate_thumbnail", methods=["POST"])
def generate_thumbnail_route():
    """Generate a thumbnail image from a video frame with title bar and content box."""
    import base64
    from core.video_processor import generate_thumbnail, find_ffmpeg

    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    timestamp = float(data.get("timestamp") or 2.0)
    title = str(data.get("title") or "Trạm giải trí").strip()
    subtitle_text = str(data.get("subtitle_text") or "").strip()
    width = int(data.get("width") or 1080)
    height = int(data.get("height") or 1920)
    corner_radius = int(data.get("corner_radius") or 40)
    logo_path = str(data.get("logo_path") or data.get("frame_logo_path") or "").strip()

    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    vp = Path(video_path_str).expanduser()
    if not vp.is_absolute():
        vp = ROOT / vp
    if not vp.exists():
        return jsonify({"ok": False, "error": f"Video không tồn tại: {vp}"}), 404

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

    # Output path: cùng thư mục với video, tên _thumbnail.jpg
    out_dir = vp.parent
    output_path = out_dir / f"{vp.stem}_thumbnail.jpg"

    ok, result = generate_thumbnail(
        video_path=vp,
        output_path=output_path,
        ffmpeg=ffmpeg,
        timestamp=timestamp,
        title=title,
        subtitle_text=subtitle_text,
        width=width,
        height=height,
        corner_radius=corner_radius,
        logo_path=logo_path,
    )

    if ok:
        # Trả về cả path và base64 preview
        try:
            with open(output_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            return jsonify({
                "ok": True,
                "output_path": str(output_path.resolve()),
                "image": f"data:image/jpeg;base64,{img_b64}",
            })
        except Exception as e:
            return jsonify({"ok": True, "output_path": str(output_path.resolve()), "error_preview": str(e)})

    return jsonify({"ok": False, "error": result}), 500


@bp.route("/api/generate_thumbnail_ai", methods=["POST"])
def generate_thumbnail_ai():
    """Generate thumbnail using AI (Gemini).
    
    Flow:
    1. Extract frame from video (or use provided image)
    2. Send frame to Gemini Vision to analyze content and generate a creative thumbnail prompt
    3. Use Gemini native image generation to create an eye-catching thumbnail
    
    Body JSON:
      video_path (str) — path to local video file
      timestamp (float) — time to extract frame (default 2.0)
      title (str) — channel/brand title to include
      style (str) — thumbnail style hint (e.g. "youtube", "tiktok", "cinematic")
      custom_prompt (str) — optional custom prompt override
      aspect_ratio (str) — "9:16" (vertical) or "16:9" (horizontal)
    """
    import base64
    import json as _json
    import urllib.request
    import urllib.error
    import os

    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    
    # Fallback: Tự động tìm video .mp4 mới nhất trong thư mục Downloaded hoặc temp_uploads nếu thiếu video_path
    if not video_path_str:
        try:
            mp4_files = []
            downloaded_dir = ROOT / "Downloaded"
            if downloaded_dir.exists():
                for p in downloaded_dir.rglob("*.mp4"):
                    if p.is_file():
                        mp4_files.append((p, p.stat().st_mtime))
            temp_uploads_dir = ROOT / "temp_uploads"
            if temp_uploads_dir.exists():
                for p in temp_uploads_dir.rglob("*.mp4"):
                    if p.is_file():
                        mp4_files.append((p, p.stat().st_mtime))
            if mp4_files:
                mp4_files.sort(key=lambda x: x[1], reverse=True)
                video_path_str = str(mp4_files[0][0])
        except Exception:
            pass

    timestamp = float(data.get("timestamp") or 2.0)
    title = str(data.get("title") or "").strip()
    style = str(data.get("style") or "youtube").strip()
    custom_prompt = str(data.get("custom_prompt") or "").strip()
    
    # Auto-detect aspect ratio from video dimensions if available
    aspect_ratio = str(data.get("aspect_ratio") or "9:16").strip()
    if video_path_str:
        try:
            from core.video_processor import find_ffmpeg
            ffmpeg = find_ffmpeg()
            if ffmpeg:
                vp = Path(video_path_str).expanduser()
                if not vp.is_absolute():
                    vp = ROOT / vp
                if vp.exists():
                    import subprocess, re
                    _vr = subprocess.run([ffmpeg, "-i", str(vp)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
                    _vm = re.search(r"(\d{2,5})x(\d{2,5})", _vr.stderr or "")
                    if _vm:
                        _vw, _vh = int(_vm.group(1)), int(_vm.group(2))
                        aspect_ratio = "9:16" if _vw < _vh else "16:9"
        except Exception:
            pass

    subtitle_text = str(data.get("subtitle_text") or "").strip()

    # Mô hình AI tạo ảnh do người dùng chọn ở UI Thumbnail trước khi bấm 🤖.
    #   "auto"               → 9Router (nếu cấu hình) rồi fallback Gemini
    #   "gemini*"/"imagen*"  → ép dùng Gemini native image
    #   còn lại (vd cx/...)  → ép dùng 9Router với đúng model đó
    image_model = str(data.get("image_model") or "auto").strip() or "auto"

    # Get API keys (need at least 1 of: 9Router or Gemini)
    cfg = load_cfg()
    api_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    nr_check = cfg.get("nine_router") or {}
    has_9router = bool((nr_check.get("endpoint") or "").strip() and (nr_check.get("api_key") or "").strip())
    if not api_key and not has_9router:
        return jsonify({"ok": False, "error": "Chưa cấu hình 9Router (nine_router) hoặc Gemini API key (gemini_video.api_key)"}), 400

    # ── Step 1: Extract frame from video ──────────────────────────────────────
    frame_b64 = data.get("frame_b64") or None
    if not frame_b64 and video_path_str:
        from core.video_processor import find_ffmpeg
        import subprocess
        import shutil

        vp = Path(video_path_str).expanduser()
        if not vp.is_absolute():
            vp = ROOT / vp
        if not vp.exists():
            return jsonify({"ok": False, "error": f"Video không tồn tại: {vp}"}), 404

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return jsonify({"ok": False, "error": "FFmpeg không tìm thấy"}), 500

        try:
            with tempfile.TemporaryDirectory(prefix="ai_thumb_") as tmpdir:
                tmp_video = Path(tmpdir) / f"input{vp.suffix}"
                shutil.copy2(str(vp), str(tmp_video))
                tmp_jpg = Path(tmpdir) / "frame.jpg"

                subprocess.run([
                    ffmpeg, "-ss", str(timestamp),
                    "-i", str(tmp_video),
                    "-vframes", "1", "-q:v", "2",
                    str(tmp_jpg), "-y", "-loglevel", "error"
                ], capture_output=True, timeout=30)

                if tmp_jpg.exists() and tmp_jpg.stat().st_size > 0:
                    frame_b64 = base64.b64encode(tmp_jpg.read_bytes()).decode()
        except Exception:
            pass  # Continue without frame

    # ── Step 2: Build prompt ──────────────────────────────────────────────────
    is_editing_existing_thumb = bool(data.get("is_editing_existing_thumb"))

    if custom_prompt:
        gen_prompt = custom_prompt
    else:
        # Use Gemini Vision to analyze frame và viết prompt — chỉ khi có Gemini key.
        # Nếu không có (chỉ có 9Router) thì dùng prompt mặc định dựa trên title/subtitle.
        if frame_b64 and api_key:
            gen_prompt = _ai_thumbnail_prompt_from_frame(api_key, frame_b64, title, subtitle_text, style, aspect_ratio, is_editing_existing_thumb)
        else:
            content_desc = subtitle_text or title or "entertaining video content"
            if is_editing_existing_thumb:
                gen_prompt = (
                    f"Modify this existing video thumbnail. "
                    f"Make it more eye-catching, vibrant colors, high contrast. "
                    f"Include bold text overlay: '{title}' clearly onto the existing composition. "
                    f"Add details related to content: '{content_desc}' while maintaining the original layout."
                )
            else:
                gen_prompt = (
                    f"Create a professional {style} video thumbnail image. "
                    f"Content: {content_desc}. "
                    f"Style: eye-catching, vibrant colors, high contrast, professional quality. "
                    f"Aspect ratio: {aspect_ratio}. "
                    f"Include bold text overlay: '{title}' if applicable. "
                    f"Make it click-worthy and engaging."
                )

    # ── Step 3: Generate thumbnail — ưu tiên 9Router, fallback Gemini ─────────
    cfg_full = load_cfg()
    nr_cfg = cfg_full.get("nine_router") or {}
    nr_endpoint = (nr_cfg.get("endpoint") or "").strip().rstrip("/")
    nr_key = (nr_cfg.get("api_key") or "").strip()

    img_b64_data = None
    used_provider = None

    nr_error = None  # lỗi thật từ 9Router (nếu có) để báo cho người dùng

    # Phân loại lựa chọn model của người dùng
    _model_lc = image_model.lower()
    explicit_choice = bool(image_model and image_model != "auto")
    force_gemini = _model_lc.startswith(("gemini", "imagen"))
    # User chọn 1 model 9Router cụ thể (vd: nb/nanobanana-flash, cx/gpt-5.5-image)
    forced_9router_model = image_model if (explicit_choice and not force_gemini) else None

    # Priority 1: 9Router — dùng khi auto hoặc user chọn 1 model 9Router (bỏ qua nếu ép Gemini)
    if nr_endpoint and nr_key and not force_gemini:
        model_id = (forced_9router_model or nr_cfg.get("default_image_model") or "cx/gpt-5.5-image").strip() or "cx/gpt-5.5-image"
        try:
            size_map = {"9:16": "1024x1792", "16:9": "1792x1024", "1:1": "1024x1024"}
            size_str = size_map.get(aspect_ratio, "1024x1792")
            payload = {
                "model": model_id,
                "prompt": gen_prompt[:2000],
                "n": 1,
                "size": size_str,
                "quality": "auto",
                "response_format": "b64_json",
            }
            if frame_b64:
                payload["images"] = [frame_b64]
                payload["image"] = frame_b64
            body = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{nr_endpoint}/images/generations",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {nr_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=240) as resp:
                rdata = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
            img_data = (rdata.get("data") or [{}])[0]
            if img_data.get("b64_json"):
                img_b64_data = img_data["b64_json"]
                used_provider = f"9Router ({model_id})"
            elif img_data.get("url"):
                with urllib.request.urlopen(img_data["url"], timeout=180) as dl:
                    img_b64_data = base64.b64encode(dl.read()).decode("ascii")
                used_provider = f"9Router ({model_id})"
            else:
                nr_error = ((rdata.get("error") or {}).get("message")
                            if isinstance(rdata.get("error"), dict) else rdata.get("error")) \
                           or "9Router không trả về ảnh"
        except urllib.error.HTTPError as e:
            try:
                ebody = e.read().decode("utf-8", "replace")
                ej = _json.loads(ebody)
                nr_error = (ej.get("error") or {}).get("message") or ebody[:300]
            except Exception:
                nr_error = f"HTTP {e.code}"
        except Exception as e:
            nr_error = str(e)[:300]

    # Nếu user CHỌN model 9Router cụ thể mà thất bại → báo đúng lỗi, KHÔNG fallback Gemini
    # (tránh hiện lỗi quota Gemini gây hiểu lầm khi user đã chọn nanobanana/codex…)
    if forced_9router_model and not img_b64_data:
        return jsonify({
            "ok": False,
            "error": f"Model '{forced_9router_model}' (9Router) lỗi: {nr_error or 'không tạo được ảnh'}",
        }), 502

    # Priority 2: Gemini — chỉ khi auto fallback, hoặc user chọn model Gemini
    if not img_b64_data:
        if not api_key:
            return jsonify({"ok": False, "error": nr_error or "Chưa có 9Router cũng như Gemini API key"}), 400
        gemini_model = image_model if (force_gemini and _model_lc.startswith("gemini")) else "gemini-2.5-flash-image"
        result = _ai_generate_thumbnail_image(api_key, gen_prompt, frame_b64, aspect_ratio, gemini_model)
        if result.get("ok"):
            img_b64_data = result["image_b64"]
            used_provider = f"Gemini ({gemini_model})"
        else:
            msg = result.get("error", "AI thumbnail generation failed")
            if nr_error:
                msg = f"9Router lỗi: {nr_error} · Gemini lỗi: {msg}"
            return jsonify({"ok": False, "error": msg}), 500

    # Save to file
    img_data = base64.b64decode(img_b64_data)
    if video_path_str:
        vp = Path(video_path_str).expanduser()
        if not vp.is_absolute():
            vp = ROOT / vp
        out_dir = vp.parent
        output_path = out_dir / f"{vp.stem}_ai_thumbnail.png"
    else:
        out_dir = ROOT / "temp_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"ai_thumbnail_{int(time.time())}.png"

    output_path.write_bytes(img_data)

    return jsonify({
        "ok": True,
        "image": f"data:image/png;base64,{img_b64_data}",
        "output_path": str(output_path.resolve()),
        "prompt_used": gen_prompt[:200],
        "provider": used_provider,
    })


def _ai_thumbnail_prompt_from_frame(api_key: str, frame_b64: str, title: str, subtitle: str, style: str, aspect_ratio: str, is_editing_existing_thumb: bool = False) -> str:
    """Use Gemini Vision to analyze a video frame and generate a creative thumbnail prompt."""
    import json as _json
    import urllib.request
    import urllib.error

    model = "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    if is_editing_existing_thumb:
        system_instruction = f"""You are an expert thumbnail editor. 
Analyze the provided existing thumbnail image and output a prompt for AI image generation that modifies and refines it.

Rules for modification:
- Do NOT generate a completely new composition or change the core elements.
- Analyze the layout, colors, and key items of this existing image.
- Write a prompt instructing the generator to add a prominent, stylish text overlay showing: '{title}'.
- The prompt must specify to keep the existing background and elements, but enhance contrast, dramatic lighting, and add details matching the content: '{subtitle or title}'.
- Output ONLY the prompt text to edit this image, keeping the exact style, nothing else. Keep it under 150 words."""
    else:
        system_instruction = f"""You are an expert thumbnail designer for {style} videos.
Analyze the video frame and create a prompt for AI image generation that will produce an eye-catching thumbnail.

Rules:
- The thumbnail should be visually striking and click-worthy
- Use vibrant colors, high contrast, dramatic lighting
- Include relevant visual elements from the video content
- Aspect ratio: {aspect_ratio}
- If a title/brand is provided, incorporate it naturally
- Keep the prompt concise (under 150 words)
- Output ONLY the image generation prompt, nothing else

Title/Brand: {title or 'N/A'}
Content hint: {subtitle or 'N/A'}"""

    payload = {
        "contents": [{
            "parts": [
                {"text": system_instruction},
                {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                {"text": "Generate a creative thumbnail prompt based on this video frame:"},
            ]
        }],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 300},
    }

    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")

        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                text = part.get("text", "").strip()
                if text:
                    return text
    except Exception:
        pass

    # Fallback prompt
    return (
        f"Create a professional {style} video thumbnail. "
        f"Eye-catching design with vibrant colors and high contrast. "
        f"Content: {subtitle or title or 'entertaining video'}. "
        f"Aspect ratio: {aspect_ratio}. Professional quality, click-worthy."
    )


def _ai_generate_thumbnail_image(api_key: str, prompt: str, reference_frame_b64: str | None, aspect_ratio: str, model: str = "gemini-2.5-flash-image") -> dict:
    """Generate thumbnail image using Gemini native image generation."""
    import json as _json
    import urllib.request
    import urllib.error

    model = (model or "gemini-2.5-flash-image").strip() or "gemini-2.5-flash-image"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    # Build parts — include reference frame if available
    parts = []
    if reference_frame_b64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": reference_frame_b64}})
        parts.append({"text": f"Based on this video frame, generate a professional thumbnail image. {prompt}"})
    else:
        parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", "replace")
            err_json = _json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body[:300])
        except Exception:
            err_msg = err_body[:300] or f"HTTP {e.code}"
        return {"ok": False, "error": f"Gemini API error: {err_msg}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Parse response — look for image in candidates
    candidates = data.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or {}
            if inline.get("mimeType", "").startswith("image/"):
                img_b64 = inline.get("data", "")
                if img_b64:
                    return {"ok": True, "image_b64": img_b64}

    return {"ok": False, "error": "Gemini không trả về ảnh. Thử lại hoặc đổi prompt."}



@bp.route("/api/check_gemini_api", methods=["POST"])
def check_gemini_api():
    """Preflight check: verify Gemini API key is valid before batch processing."""
    import os
    import urllib.request
    import urllib.error
    import json as _json

    cfg = load_cfg()
    api_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    if not api_key:
        return jsonify({"ok": False, "error": "Chưa cấu hình Gemini API key trong config.yml (gemini_video.api_key)"}), 400

    # Test with a small generateContent call
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
        # If we get here without exception, API is valid
        if data.get("candidates"):
            return jsonify({"ok": True, "model": "gemini-2.5-flash"})
        return jsonify({"ok": False, "error": "API trả về kết quả rỗng"}), 400
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", "replace")
            err_json = _json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body[:200])
        except Exception:
            err_msg = err_body[:200] or f"HTTP {e.code}"
        return jsonify({"ok": False, "error": err_msg}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

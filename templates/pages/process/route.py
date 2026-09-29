"""Process Blueprint — /api/process_video, /api/upload_anti_fp_image, /api/make_vertical_video."""
import asyncio
import logging
import tempfile
import time
import json as _j
import os
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context
from core_app import load_cfg, CONFIG_FILE, ROOT, get_cookies_with_fallback, _resolve_naming_title, require_valid_license
from templates.pages.process.frame_service import (
    resolve_video_path,
    extract_single_frame,
    extract_filmstrip,
    fetch_thumbnail_from_url,
    pick_url,
    extract_aweme_id,
)
from templates.pages.process.ai_service import (
    clean_ai_result,
    extract_frames_for_ai,
    build_ai_prompt,
    call_gemini_vision,
    ai_thumbnail_prompt_from_frame,
    ai_generate_thumbnail_image,
    check_gemini_api_key,
)

# Compatibility aliases
_resolve_video_path = resolve_video_path
_ai_thumbnail_prompt_from_frame = ai_thumbnail_prompt_from_frame
_ai_generate_thumbnail_image = ai_generate_thumbnail_image

bp = Blueprint("process", __name__)
LOGGER = logging.getLogger("process")

_PROCESS_PROFILES_FILE = ROOT / "data" / "process_profiles.json"


def _read_process_profiles():
    try:
        if not _PROCESS_PROFILES_FILE.exists():
            return {}
        data = _j.loads(_PROCESS_PROFILES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        LOGGER.exception("Could not read process profiles")
        return {}


def _write_process_profiles(profiles):
    _PROCESS_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PROCESS_PROFILES_FILE.with_suffix(".tmp")
    tmp.write_text(_j.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PROCESS_PROFILES_FILE)


@bp.route("/api/process_profiles", methods=["GET", "POST", "DELETE"])
def process_profiles():
    """Persist custom Step 2 profiles outside browser localStorage."""
    if request.method == "GET":
        return jsonify({"ok": True, "profiles": _read_process_profiles()})

    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    if not name or len(name) > 120:
        return jsonify({"ok": False, "error": "Tên cấu hình không hợp lệ"}), 400

    profiles = _read_process_profiles()
    if request.method == "DELETE":
        profiles.pop(name, None)
    else:
        profile = body.get("profile")
        if not isinstance(profile, dict):
            return jsonify({"ok": False, "error": "Dữ liệu cấu hình không hợp lệ"}), 400
        profiles[name] = profile

    try:
        _write_process_profiles(profiles)
    except Exception as exc:
        LOGGER.exception("Could not save process profiles")
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "profiles": profiles})

# ── Pause/Resume state ────────────────────────────────────────────────────────
import threading as _threading

_proc_pause_event = _threading.Event()
_proc_pause_event.set()  # not paused by default
_proc_review_event = _threading.Event()
_proc_review_event.set()  # not waiting for review by default

# ── Cancellation state ────────────────────────────────────────────────────────
_proc_cancel_event = _threading.Event()
_proc_cancel_event.clear()

def is_proc_cancelled() -> bool:
    return _proc_cancel_event.is_set()

def request_proc_cancel():
    _proc_cancel_event.set()
    _proc_pause_event.set()
    _proc_review_event.set()
    _proc_thumb_retry_event.set()
    _proc_tts_retry_event.set()
    try:
        from core.processor.ffmpeg_base import kill_active_subprocesses
        kill_active_subprocesses()
    except Exception:
        pass

def reset_proc_cancel():
    _proc_cancel_event.clear()

try:
    from core.processor.ffmpeg_base import register_cancel_checker
    register_cancel_checker(is_proc_cancelled)
except Exception:
    pass

@bp.route("/api/proc_cancel", methods=["POST"])
def proc_cancel():
    """Cancel currently processing video or all processing."""
    data = request.json or {}
    scope = str(data.get("scope") or "current").strip().lower()
    request_proc_cancel()
    return jsonify({"ok": True, "scope": scope})

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

# State cho retry các đoạn TTS bị thiếu.
_proc_tts_retry_event = _threading.Event()
_proc_tts_retry_event.set()
_proc_tts_retry_action: dict = {}  # {action: 'retry'|'continue'|'cancel'}
_proc_tts_retry_lock = _threading.Lock()


@bp.route("/api/proc_retry_tts", methods=["POST"])
def proc_retry_tts():
    """Resolve a partial TTS generation result."""
    data = request.json or {}
    action = str(data.get("action") or "").strip().lower()
    if action not in ("retry", "continue", "cancel"):
        return jsonify({"ok": False, "error": "Invalid action"}), 400
    with _proc_tts_retry_lock:
        _proc_tts_retry_action.clear()
        _proc_tts_retry_action["action"] = action
    _proc_tts_retry_event.set()
    return jsonify({"ok": True})


def prepare_tts_retry_wait() -> None:
    """Clear stale actions before emitting the modal event to the frontend."""
    with _proc_tts_retry_lock:
        _proc_tts_retry_action.clear()
    _proc_tts_retry_event.clear()


def wait_tts_retry_action(timeout: float = 600.0) -> dict:
    """Wait for the user to retry, accept missing clips, or cancel."""
    got = _proc_tts_retry_event.wait(timeout=timeout)
    _proc_tts_retry_event.set()
    if not got:
        return {"action": "cancel"}
    with _proc_tts_retry_lock:
        cfg = dict(_proc_tts_retry_action)
        _proc_tts_retry_action.clear()
    return cfg or {"action": "cancel"}


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
    """Thumbnail override is disabled for the process pipeline."""
    with _proc_thumb_lock:
        _proc_thumb_override.clear()
    return jsonify({"ok": True, "disabled": True})


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
    """Extract a frame from a video at a given timestamp and return as base64 JPEG."""
    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    timestamp = float(data.get("timestamp") or 0.0)
    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    ok, img_data, duration, err = extract_single_frame(video_path_str, timestamp)
    if not ok:
        status_code = 404 if "không tồn tại" in err else 500
        return jsonify({"ok": False, "error": err}), status_code
    return jsonify({"ok": True, "image": img_data, "duration": duration})


@bp.route("/api/video_filmstrip", methods=["POST"])
def video_filmstrip():
    """Extract N evenly-spaced small thumbnails from a local video for the timeline filmstrip."""
    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    try:
        count = int(data.get("count") or 12)
    except (TypeError, ValueError):
        count = 12

    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    ok, frames, duration, err = extract_filmstrip(video_path_str, count)
    if not ok:
        status_code = 404 if "không tồn tại" in err else 500
        return jsonify({"ok": False, "error": err}), status_code
    return jsonify({
        "ok": True,
        "duration": round(duration, 3),
        "count": len(frames),
        "frames": frames,
    })


@bp.route("/api/analyze_video_ai", methods=["POST"])
def analyze_video_ai():
    """Analyze a local video via sampled frames and return suggested masks/title hints."""
    import urllib.error

    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu đường dẫn video"}), 400

    vp = resolve_video_path(video_path_str)
    if not vp or not vp.exists():
        return jsonify({"ok": False, "error": f"Video không tồn tại: {video_path_str}"}), 404

    requested_nine_model = str(data.get("nine_model") or data.get("model") or "").strip()
    language = str(data.get("language") or "").strip()
    target_language = str(data.get("target_language") or "vi").strip()
    audit_mode = "source_markers" if data.get("audit_mode") == "source_markers" else ""
    sample_value = data.get("sample_count")
    sample_raw = str("5" if sample_value in (None, "") else sample_value).strip().lower()
    full_video = sample_raw in ("0", "full", "all", "video", "entire")

    try:
        sample_count = 0 if full_video else int(sample_raw or 5)
    except Exception:
        sample_count = 5
    if not full_video:
        sample_count = max(2, min(40, sample_count))

    # Resolve Antigravity connection from DB
    ag_conns = []
    ag_models = []
    try:
        from templates.pages.config.route import load_models_from_db, load_providers_from_db
        all_provs = load_providers_from_db()
        ag_data = all_provs.get("antigravity") or {}
        ag_conns = [c for c in ag_data.get("connections", []) if c.get("enabled")] or ag_data.get("connections", [])
        ag_models = [
            str(m.get("id") or "") for m in load_models_from_db("antigravity").get("antigravity", [])
            if m.get("enabled") and str(m.get("model_type") or "llm") == "llm"
        ]
    except Exception:
        pass

    ag_conns = [c for c in ag_conns if c.get("api_key") or c.get("refresh_token")]
    if not ag_conns:
        return jsonify({
            "ok": False,
            "code": "missing_login",
            "error": "Chưa kết nối Antigravity. Mở Nhà cung cấp AI → Antigravity → Kết nối.",
        }), 400

    try:
        frames, duration = extract_frames_for_ai(vp, sample_count)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Không đọc được video: {e}"}), 500
    if not frames:
        return jsonify({"ok": False, "error": "Không đọc được video hoặc không trích được frame"}), 500

    prompt = build_ai_prompt(language, target_language, duration, [f["timestamp"] for f in frames], audit_mode)

    try:
        m_target = requested_nine_model.split("/")[-1] if "/" in requested_nine_model else requested_nine_model
        gemini_model = m_target if (m_target and m_target not in ("none", "auto", "duytris", "")) else (ag_models[0].split("/")[-1] if ag_models else "")
        if not gemini_model:
            return jsonify({"ok": False, "error": "Chưa có model Antigravity đang bật trong DB"}), 400
        LOGGER.info("analyze_video_ai: using Antigravity model=%s", gemini_model)
        last_error = None
        for connection in ag_conns:
            try:
                def analyze(prompt_text, batch):
                    return call_gemini_vision(
                        str(connection.get("api_key") or ""), gemini_model, prompt_text, batch,
                        base_url=str(connection.get("base_url") or ""), connection=connection, db_models=ag_models,
                    )
                if full_video:
                    from .ai_service import analyze_video_batches
                    result = analyze_video_batches(frames, duration, language, target_language, analyze, audit_mode)
                else:
                    result = analyze(prompt, frames)
                return jsonify({
                    "ok": True,
                    "provider": "antigravity",
                    "model": gemini_model,
                    "account": connection.get("email") or connection.get("name") or "Antigravity",
                    "frame_count": len(frames),
                    "duration": round(duration, 3),
                    "result": clean_ai_result(result),
                })
            except Exception as account_error:
                last_error = account_error
                LOGGER.warning(
                    "Antigravity account %s failed, rotating: %s",
                    connection.get("email") or connection.get("name") or connection.get("id"),
                    account_error,
                )
        if last_error:
            raise last_error
        raise RuntimeError("Không có tài khoản Antigravity khả dụng")
    except urllib.error.HTTPError as e:
        LOGGER.warning("analyze_video_ai Antigravity HTTPError: %s", e)
        return jsonify({"ok": False, "error": f"Antigravity: HTTP {e.code}"}), 502
    except Exception as e:
        LOGGER.warning("analyze_video_ai Antigravity failed: %s", e)
        return jsonify({"ok": False, "error": f"Antigravity: {str(e)[:200]}"}), 502


@bp.route("/api/video_frame_from_url", methods=["POST"])
def video_frame_from_url():
    """Fetch thumbnail/cover from video URL via Douyin API."""
    data = request.json or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Chưa nhập URL video"}), 400

    thumb_result = fetch_thumbnail_from_url(url)
    if thumb_result and thumb_result.get("cover_url"):
        return jsonify({"ok": True, **thumb_result})

    return jsonify({"ok": False, "error": "Không lấy được thumbnail từ URL"}), 404




@require_valid_license
@bp.route("/api/upload_anti_fp_image", methods=["POST"])
def upload_anti_fp_image():
    """Upload an overlay / logo image for anti-fingerprint processing."""
    from utils.validators import sanitize_filename

    upload_file = request.files.get("file") if request.files else None
    if not upload_file or not upload_file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    img_type = request.form.get("type") or "overlay"
    safe_name = sanitize_filename(upload_file.filename)
    from core_app import TEMP_UPLOADS_DIR
    upload_dir = TEMP_UPLOADS_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    save_path = upload_dir / f"anti-fp-{uuid.uuid4().hex}-{safe_name}"
    upload_file.save(str(save_path))

    return jsonify({"ok": True, "path": str(save_path), "url": "/temp_uploads/" + save_path.name})


@require_valid_license
@bp.route("/api/upload_batch_video", methods=["POST"])
def upload_batch_video():
    """Upload a video file for batch publishing. Returns server path."""
    from utils.validators import sanitize_filename

    upload_file = request.files.get("file") if request.files else None
    if not upload_file or not upload_file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    safe_name = sanitize_filename(upload_file.filename)
    from core_app import TEMP_UPLOADS_DIR
    upload_dir = TEMP_UPLOADS_DIR / "batch_pub"
    upload_dir.mkdir(parents=True, exist_ok=True)

    save_path = upload_dir / safe_name
    # Avoid overwrite
    if save_path.exists():
        import time as _time
        stem = save_path.stem
        save_path = upload_dir / f"{stem}_{int(_time.time())}{save_path.suffix}"

    upload_file.save(str(save_path))
    return jsonify({"ok": True, "path": str(save_path)})


@require_valid_license
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


def _make_ytdlp_progress_hook(url):
    import time
    from core_app import socketio
    
    last_emit_time = [0.0]
    last_pct = [-1]
    
    def progress_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct_str = "0%"
            pct_val = 0
            if total > 0:
                pct_val = int(downloaded / total * 100)
                pct_str = f"{pct_val}%"
            
            speed = d.get("speed")
            speed_str = ""
            if speed:
                if speed > 1024 * 1024:
                    speed_str = f" tại {speed / (1024 * 1024):.1f} MB/s"
                else:
                    speed_str = f" tại {speed / 1024:.1f} KB/s"
                    
            now = time.time()
            if now - last_emit_time[0] >= 1.0 or pct_val != last_pct[0]:
                last_emit_time[0] = now
                last_pct[0] = pct_val
                
                filename = d.get("filename", "")
                from pathlib import Path
                short_name = Path(filename).name if filename else "video"
                msg = f"⏳ Đang tải {short_name}: {pct_str}{speed_str}"
                socketio.emit("step1_log", {"msg": msg, "level": "info"})
        elif d.get("status") == "finished":
            socketio.emit("step1_log", {"msg": "✅ Đã tải xong video gốc. Đang xử lý...", "level": "success"})
            
    return progress_hook


async def _download_douyin_ytdlp_fallback(url: str, out_path: Path, aweme_id: str):
    """Fallback when Douyin's signed detail API rejects a valid fresh session."""
    from core.multi_platform import download_video as download_generic
    from core.video_processor import _safe_stem

    temp_dir = out_path / "Process_video" / "_tmp_dl"
    result = await asyncio.to_thread(
        download_generic,
        url,
        str(temp_dir),
        progress_hook=_make_ytdlp_progress_hook(url),
    )
    if not result.get("ok"):
        message = str(result.get("error") or "Douyin download failed")
        if "fresh cookies" in message.casefold() or "403" in message:
            raise RuntimeError(
                "Douyin từ chối request hiện tại (HTTP 403). Cookie có thể vẫn còn hạn; "
                "hãy thử lại, hoặc mở Cookie → Tự động lấy nếu lỗi tiếp diễn."
            )
        raise RuntimeError(message)

    source = Path(result["file"])
    title = _resolve_naming_title(result.get("title") or source.stem or "video")
    identity = str(result.get("id") or aweme_id or int(time.time()))
    base_name = f"{_safe_stem(title)}_{identity}"
    save_dir = out_path / "Process_video" / base_name
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{base_name}.mp4"
    if save_path.exists():
        save_path = save_dir / f"{base_name}_{int(time.time())}.mp4"
    try:
        source.replace(save_path)
    except Exception:
        import shutil
        shutil.move(str(source), str(save_path))
    return save_path.resolve(), title
@require_valid_license
@bp.route("/api/process_video", methods=["POST"])
def process_video():
    import sys
    if hasattr(request, "environ") and isinstance(request.environ, dict):
        request.environ["eventlet.minimum_write_chunk_size"] = 0
    print("=== [BACKEND] process_video() route called ===", file=sys.stderr, flush=True)
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
                text = (raw or "").strip()
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
                    val = (qs.get(key) or [""])[0].strip()
                    if val.isdigit():
                        return val
                m = re.search(r"/(?:video|note|gallery|slides|share/video)/(\d{15,20})", url)
                if m:
                    return m.group(1)
                return ""

            cfg = ConfigLoader(str(CONFIG_FILE))

            # ── Nền tảng khác Douyin (TikTok/YouTube/...) → yt-dlp ──────────
            from core.multi_platform import is_douyin as _is_dy
            normalized_url0 = _pick_url(video_url)
            if normalized_url0 and not _is_dy(normalized_url0):
                from core.multi_platform import download_video as _dl_generic
                from core.video_processor import _safe_stem
                from core.proxy_resolver import resolve_proxy as _resolve_proxy

                out_path = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")

                def _do_generic():
                    return _dl_generic(
                        normalized_url0,
                        str(out_path / "Process_video" / "_tmp_dl"),
                        proxy=_resolve_proxy(cfg),
                        progress_hook=_make_ytdlp_progress_hook(normalized_url0),
                    )

                res = await asyncio.to_thread(_do_generic)
                if not res.get("ok"):
                    raise RuntimeError(res.get("error") or "Download failed")

                src = Path(res["file"])
                raw_title = res.get("title") or src.stem or "video"
                resolved_title = _resolve_naming_title(raw_title)
                slug = _safe_stem(resolved_title)
                base_name = f"{slug}_{res.get('id') or int(time.time())}"
                save_dir = out_path / "Process_video" / base_name
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"{base_name}.mp4"
                if save_path.exists():
                    save_path = save_dir / f"{base_name}_{int(time.time())}.mp4"
                try:
                    src.replace(save_path)
                except Exception:
                    import shutil
                    shutil.move(str(src), str(save_path))
                return save_path.resolve(), resolved_title

            cm = CookieManager()
            cm.set_cookies(get_cookies_with_fallback())
            cookie_ok, cookie_reason = cm.cookie_status()
            if not cookie_ok:
                raise RuntimeError(cookie_reason)

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

                bf_cfg = cfg.get("browser_fallback") or {}
                aweme_data = await api.get_video_detail(aweme_id, browser_fallback=bf_cfg)
                if not aweme_data:
                    fallback_out = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")
                    return await _download_douyin_ytdlp_fallback(resolved_url, fallback_out, aweme_id)

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

            # Defense-in-depth: if video_url is actually a local file path, move it to video_path
            if video_url and not (video_url.startswith("http://") or video_url.startswith("https://")):
                if not video_path:
                    video_path = video_url
                video_url = ""
                req["video_path"] = video_path
                req["video_url"] = ""

            if "delete_source_after_process" not in req:
                req["delete_source_after_process"] = True

            try:
                request.environ["eventlet.minimum_write_chunk_size"] = 0
            except Exception:
                pass
            try:
                import eventlet
                _ev_sleep = eventlet.sleep
            except Exception:
                _ev_sleep = None
            import sys
            yield (_j.dumps({"log": f"🚀 Kết nối server backend thành công, bắt đầu xử lý...", "level": "info"}, ensure_ascii=True) + "\n").encode("utf-8")
            if _ev_sleep:
                _ev_sleep(0.005)
            print(f"=== [BACKEND] generate() started, video_path={video_path}, video_url={video_url} ===", file=sys.stderr, flush=True)

            if not video_path and video_url:
                yield (_j.dumps({"log": f"Resolving URL: {video_url}", "level": "info"}, ensure_ascii=True) + "\n").encode("utf-8")
                yield (_j.dumps({"overall": 2, "overall_lbl": "Resolving URL..."}, ensure_ascii=True) + "\n").encode("utf-8")
                if _ev_sleep:
                    _ev_sleep(0.005)
                try:
                    downloaded_path, downloaded_title = asyncio.run(
                        _download_video_from_url(video_url, str(req.get("out_dir") or "").strip())
                    )
                    req["video_path"] = str(downloaded_path)
                    req["video_title"] = downloaded_title
                    req["delete_source_after_process"] = True
                    yield (_j.dumps({"log": f"Downloaded video: {downloaded_path}", "level": "success"}, ensure_ascii=True) + "\n").encode("utf-8")
                    yield (_j.dumps({"overall": 4, "overall_lbl": "Download done, start processing..."}, ensure_ascii=True) + "\n").encode("utf-8")
                    if _ev_sleep:
                        _ev_sleep(0.005)
                except Exception as e:
                    yield (_j.dumps({"log": f"URL download failed: {e}", "level": "error", "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
                    yield (_j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=True) + "\n").encode("utf-8")
                    return
            elif not video_path:
                yield (_j.dumps({"log": "Please provide video_path or video_url", "level": "error", "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
                yield (_j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=True) + "\n").encode("utf-8")
                return

            # Reset control events to fresh running state
            reset_proc_cancel()
            _proc_pause_event.set()
            _proc_review_event.set()
            _proc_thumb_retry_event.set()
            _proc_tts_retry_event.set()

            import queue as _pyqueue
            import threading as _pythreading
            import time as _pytime_mod
            _q = _pyqueue.Queue()

            def _pipeline_worker():
                try:
                    for line in process_video_full(req):
                        if _proc_cancel_event.is_set():
                            break
                        while not _proc_pause_event.is_set():
                            if _proc_cancel_event.is_set():
                                break
                            _pytime_mod.sleep(0.1)
                        _q.put(line)
                except Exception as err:
                    _q.put(err)
                finally:
                    _q.put(None)

            _worker_t = _pythreading.Thread(target=_pipeline_worker, daemon=True)
            _worker_t.start()

            try:
                import eventlet
                _ev_sleep = eventlet.sleep
            except Exception:
                _ev_sleep = _pytime_mod.sleep

            while True:
                if _proc_cancel_event.is_set():
                    yield (_j.dumps({"log": "⛔ Tiến trình xử lý đã bị hủy.", "level": "warning", "cancelled": True, "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
                    yield (_j.dumps({"overall": 0, "overall_lbl": "Đã hủy"}, ensure_ascii=True) + "\n").encode("utf-8")
                    break
                try:
                    item = _q.get_nowait()
                except _pyqueue.Empty:
                    _ev_sleep(0.05)
                    continue

                if item is None:
                    break
                if isinstance(item, Exception):
                    yield (_j.dumps({"log": f"Fatal error: {item}", "level": "error", "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
                    yield (_j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=True) + "\n").encode("utf-8")
                    break
                yield item.encode("utf-8") if isinstance(item, str) else item
            if False:
                for line in process_video_full(req):
                    if _proc_cancel_event.is_set():
                        yield (_j.dumps({"log": "⛔ Tiến trình xử lý đã bị hủy.", "level": "warning", "cancelled": True, "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
                        break
                    while not _proc_pause_event.is_set():
                        if _proc_cancel_event.is_set():
                            break
                        import time as _time
                        _time.sleep(0.1)
                    yield line.encode("utf-8") if isinstance(line, str) else line
                    if _ev_sleep:
                        _ev_sleep(0.002)
        except (GeneratorExit, ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            request_proc_cancel()
            return
        except Exception as e:
            yield (_j.dumps({"log": f"Fatal error: {e}", "level": "error", "failed": True}, ensure_ascii=True) + "\n").encode("utf-8")
            yield (_j.dumps({"overall": 0, "overall_lbl": "Error"}, ensure_ascii=True) + "\n").encode("utf-8")

    try:
        request.environ["eventlet.minimum_write_chunk_size"] = 0
    except Exception:
        pass
    resp = Response(stream_with_context(generate()), mimetype="application/x-ndjson; charset=utf-8")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "keep-alive"
    return resp



@require_valid_license
@bp.route("/api/download_original_video", methods=["POST"])
def download_original_video():
    """Download video from URL and save it to the output folder."""
    data = request.json or {}
    video_url = str(data.get("url") or "").strip()
    out_dir = str(data.get("out_dir") or "").strip()

    if not video_url:
        return jsonify({"ok": False, "error": "Chưa nhập URL video"}), 400

    try:
        downloaded_path, downloaded_title = download_original_source(video_url, out_dir)
        return jsonify({"ok": True, "path": str(downloaded_path), "title": downloaded_title})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


def download_original_source(video_url: str, out_dir: str = ""):
    """Shared original-video downloader for Step 1 and the publishing queue."""
    from config import ConfigLoader
    from auth import CookieManager
    from core import DouyinAPIClient, URLParser
    from core.video_downloader import VideoDownloader
    from control import QueueManager, RateLimiter, RetryHandler
    from storage import FileManager
    import re
    from urllib.parse import urlparse, parse_qs

    def _pick_url(raw: str) -> str:
        text = (raw or "").strip()
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
            val = (qs.get(key) or [""])[0].strip()
            if val.isdigit():
                return val
        m = re.search(r"/(?:video|note|gallery|slides|share/video)/(\d{15,20})", url)
        if m:
            return m.group(1)
        return ""

    async def _do_download():
        cfg = ConfigLoader(str(CONFIG_FILE))
        db = None
        if cfg.get("database"):
            from storage import Database
            db = Database(db_path=str(cfg.get("database_path", "dy_downloader.db")))
            await db.initialize()

        # ── Nền tảng khác Douyin (Facebook/TikTok/YouTube/...) → yt-dlp ──
        from core.multi_platform import (
            is_douyin as _is_dy,
            detect_platform as _detect_pf,
            cookie_opts_for as _ck_opts,
        )
        normalized_url0 = _pick_url(video_url)
        if normalized_url0 and not _is_dy(normalized_url0):
            from core.multi_platform import download_video as _dl_generic
            from core.video_processor import _safe_stem
            from core.proxy_resolver import resolve_proxy as _resolve_proxy

            out_path = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")

            fb_cookie = None
            try:
                fb_cookie = (_ck_opts(_detect_pf(normalized_url0)) or {}).get("cookiefile")
            except Exception:
                fb_cookie = None

            def _do_generic():
                return _dl_generic(
                    normalized_url0,
                    str(out_path / "Process_video" / "_tmp_dl"),
                    cookiefile=fb_cookie,
                    proxy=_resolve_proxy(cfg),
                )

            res = await asyncio.to_thread(_do_generic)
            if not res or not res.get("ok"):
                detail = str((res or {}).get("error") or "không có phản hồi từ trình tải")
                raise RuntimeError(
                    f"Tải video từ URL đa nền tảng thất bại ({_detect_pf(normalized_url0)}): {detail}"
                )
            # multi_platform.download_video returns one downloaded path in
            # ``file``.  Older callers used ``files``; accepting both keeps the
            # endpoint compatible and prevents a successful download from being
            # reported as "không tìm thấy file tải về".
            downloaded_files = []
            if res:
                if res.get("file"):
                    downloaded_files = [res["file"]]
                elif res.get("files"):
                    downloaded_files = list(res["files"])
            if not downloaded_files:
                raise RuntimeError(f"Tải video từ URL đa nền tảng thất bại ({_detect_pf(normalized_url0)}): không tìm thấy file tải về")
            src = Path(downloaded_files[0])
            if not src.is_file():
                raise RuntimeError(
                    f"Tải video từ URL đa nền tảng thất bại ({_detect_pf(normalized_url0)}): "
                    f"file đầu ra không tồn tại: {src}"
                )
            resolved_title = res.get("title") or _safe_stem(src.stem)
            base_name = _safe_stem(resolved_title) or f"video_{int(time.time())}"
            save_dir = out_path / "Process_video"
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f"{base_name}.mp4"
            if save_path.exists():
                save_path = save_dir / f"{base_name}_{int(time.time())}.mp4"
            try:
                src.replace(save_path)
            except Exception:
                import shutil
                shutil.move(str(src), str(save_path))

            if db:
                import json as _j
                safe = {k: v for k, v in cfg.config.items()
                        if k not in ("cookies", "cookie", "transcript")}
                await db.add_history({
                    "url": normalized_url0, "url_type": _detect_pf(normalized_url0),
                    "total_count": 1, "success_count": 1,
                    "config": _j.dumps(safe, ensure_ascii=False),
                })

            return save_path.resolve(), resolved_title

        cm = CookieManager()
        cm.set_cookies(get_cookies_with_fallback())
        cookie_ok, cookie_reason = cm.cookie_status()
        if not cookie_ok:
            raise RuntimeError(cookie_reason)

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

            bf_cfg = cfg.get("browser_fallback") or {}
            aweme_data = await api.get_video_detail(aweme_id, browser_fallback=bf_cfg)
            if not aweme_data:
                fallback_out = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")
                return await _download_douyin_ytdlp_fallback(resolved_url, fallback_out, aweme_id)

            raw_title = str(aweme_data.get("desc") or "video").strip() or "video"
            resolved_title = _resolve_naming_title(raw_title)

            out_path = Path(out_dir).expanduser() if out_dir else Path(cfg.get("path") or "./Downloaded")
            file_manager = FileManager(str(out_path))
            downloader = VideoDownloader(
                config=cfg,
                api_client=api,
                file_manager=file_manager,
                cookie_manager=cm,
                database=db,
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

            if db:
                import json as _j
                safe = {k: v for k, v in cfg.config.items()
                        if k not in ("cookies", "cookie", "transcript")}
                await db.add_history({
                    "url": normalized_url, "url_type": "video",
                    "total_count": 1, "success_count": 1,
                    "config": _j.dumps(safe, ensure_ascii=False),
                })
                try:
                    await db.add_aweme({
                        "aweme_id": aweme_id,
                        "aweme_type": "video",
                        "title": resolved_title,
                        "author_id": aweme_data.get("author", {}).get("sec_uid") or "",
                        "author_name": aweme_data.get("author", {}).get("nickname") or "",
                        "create_time": aweme_data.get("create_time") or int(time.time()),
                        "file_path": str(save_path),
                        "metadata": _j.dumps(aweme_data, ensure_ascii=False),
                    })
                except Exception:
                    pass

            return save_path.resolve(), resolved_title

    return asyncio.run(_do_download())


@require_valid_license
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
        title_weight=int(float(data.get("title_weight") or 400)),
        title_bar_h_pct=float(data.get("title_bar_h_pct") or 6.0),
        title_margin_x_pct=float(data.get("title_margin_x_pct") or 5.0),
        title_color=str(data.get("title_color") or "#000000"),
        blur_w_pct=float(data.get("blur_w_pct") or 15.0),
        blur_opacity=float(data.get("blur_opacity") or 0.6),
        blur_mode=str(data.get("blur_mode") or "overlay"),
        logo_path=str(data.get("logo_path") or "") or None,
        logo_size_pct=float(data.get("logo_size_pct") or 12.0),
        logo_top_pct=float(data.get("logo_top_pct") or 3.0),
        logo_left_pct=float(data.get("logo_left_pct") or 3.0),
        logo_radius_pct=float(data.get("logo_radius_pct") or 50.0),
        logo_start_sec=data.get("logo_start_sec"),
        logo_end_sec=data.get("logo_end_sec"),
        target_w=int(data.get("target_w") or 1080),
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
        from core_app import TEMP_UPLOADS_DIR
        upload_dir = TEMP_UPLOADS_DIR
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
            "-strict", "-2",
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


@require_valid_license
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
    from core_app import TEMP_UPLOADS_DIR
    upload_dir = TEMP_UPLOADS_DIR
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
    frame_blur_w_pct = float(request.form.get("frame_blur_w_pct") or 0)
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


@require_valid_license
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


@require_valid_license
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
            from templates.pages.content.route import get_download_dir
            downloaded_dir = get_download_dir()
            if downloaded_dir.exists():
                for p in downloaded_dir.rglob("*.mp4"):
                    if p.is_file():
                        mp4_files.append((p, p.stat().st_mtime))
            from core_app import TEMP_UPLOADS_DIR
            temp_uploads_dir = TEMP_UPLOADS_DIR
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

    # Mô hình AI tạo ảnh do người dùng chọn ở UI Thumbnail
    image_model = str(data.get("image_model") or "gemini-3.6-flash-image").strip()

    # Get API key
    cfg = load_cfg()
    api_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    if not api_key:
        return jsonify({"ok": False, "error": "Chưa cấu hình Gemini API key (gemini_video.api_key)"}), 400

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
        # Use Gemini Vision to analyze frame và viết prompt
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

    # ── Step 3: Generate thumbnail via Gemini ─────────────────────────────────
    gemini_model = image_model if image_model.lower().startswith("gemini") else "gemini-3.6-flash-image"
    result = _ai_generate_thumbnail_image(api_key, gen_prompt, frame_b64, aspect_ratio, gemini_model)
    if result.get("ok"):
        img_b64_data = result["image_b64"]
        used_provider = f"Gemini ({gemini_model})"
    else:
        msg = result.get("error", "AI thumbnail generation failed")
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
        from core_app import TEMP_UPLOADS_DIR
        out_dir = TEMP_UPLOADS_DIR
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


@bp.route("/api/check_gemini_api", methods=["POST"])
def check_gemini_api():
    """Preflight check: verify Gemini API key is valid before batch processing."""
    cfg = load_cfg()
    api_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    ok, msg = check_gemini_api_key(api_key)
    if ok:
        return jsonify({"ok": True, "model": msg})
    return jsonify({"ok": False, "error": msg}), 400



@bp.route("/api/ytdlp/cookie_config", methods=["GET"])
def ytdlp_cookie_config():
    """Retrieve current cookies_from_browser config for yt-dlp."""
    cfg = load_cfg()
    ytdlp = cfg.get("ytdlp") or {}
    return jsonify({
        "ok": True,
        "cookies_from_browser": ytdlp.get("cookies_from_browser") or ""
    })


@bp.route("/api/ytdlp/save_cookie_config", methods=["POST"])
def ytdlp_save_cookie_config():
    """Save new cookies_from_browser value to config.yml."""
    data = request.json or {}
    browser = str(data.get("cookies_from_browser") or "").strip().lower()
    
    from core_app import load_cfg, save_cfg
    cfg = load_cfg()
    ytdlp = dict(cfg.get("ytdlp") or {})
    ytdlp["cookies_from_browser"] = browser
    cfg["ytdlp"] = ytdlp
    
    try:
        save_cfg(cfg)
        return jsonify({"ok": True, "cookies_from_browser": browser})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

"""Video Generation Blueprint — Gemini Veo 2 text/image-to-video.

Endpoints
─────────
GET  /api/videogen/config          lấy config hiện tại (api_key masked)
POST /api/videogen/check_key       kiểm tra API key hợp lệ
POST /api/videogen/generate        tạo video (text-to-video hoặc image-to-video)
GET  /api/videogen/status/<id>     poll trạng thái task
GET  /api/videogen/download/<id>   tải video đã tạo

Sử dụng google-genai SDK (google.genai) để gọi Gemini Veo 2.
"""
from __future__ import annotations

import base64
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file

from core_app import LOGGER, ROOT, load_cfg, save_cfg

bp = Blueprint("videogen", __name__)

# Storage for generated videos
_VG_OUTPUT_DIR = ROOT / "Downloaded" / "videogen"
_VG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Task registry (in-memory, simple approach)
_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()


def _get_vg_config() -> dict:
    """Get gemini_video config section."""
    cfg = load_cfg()
    return cfg.get("gemini_video", {})


# ─── GET /api/videogen/config ─────────────────────────────────────────────────
@bp.route("/api/videogen/config", methods=["GET"])
def get_config():
    """Return current videogen config (API key masked)."""
    vg = _get_vg_config()
    key = vg.get("api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    return jsonify({
        "ok": True,
        "config": {
            "api_key": key[:8] + "..." if len(key) > 8 else "",
            "model": vg.get("model", "veo-2.0-generate-001"),
            "aspect_ratio": vg.get("aspect_ratio", "16:9"),
            "duration": vg.get("duration", "8"),
        }
    })


# ─── POST /api/videogen/check_key ────────────────────────────────────────────
@bp.route("/api/videogen/check_key", methods=["POST"])
def check_key():
    """Validate Gemini API key by listing models."""
    data = request.get_json(force=True)
    api_key = data.get("api_key", "").strip()
    if not api_key:
        return jsonify({"ok": False, "error": "API key trống"}), 400

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        # Try listing models to verify key
        models = client.models.list()
        # Check if any veo model is available
        veo_available = any("veo" in m.name.lower() for m in models)

        # Save key to config
        cfg = load_cfg()
        if "gemini_video" not in cfg:
            cfg["gemini_video"] = {}
        cfg["gemini_video"]["api_key"] = api_key
        save_cfg(cfg)

        return jsonify({
            "ok": True,
            "veo_available": veo_available,
            "message": "API Key hợp lệ" + (" — Veo model sẵn sàng" if veo_available else " — Veo chưa available trong region này")
        })
    except ImportError:
        return jsonify({"ok": False, "error": "Thiếu package google-genai. Chạy: pip install google-genai"}), 500
    except Exception as e:
        LOGGER.error("check_key error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 400


# ─── POST /api/videogen/generate ─────────────────────────────────────────────
@bp.route("/api/videogen/generate", methods=["POST"])
def generate():
    """Start video generation task (async in background thread)."""
    prompt = request.form.get("prompt", "").strip()
    api_key = request.form.get("api_key", "").strip()
    model = request.form.get("model", "veo-2.0-generate-001")
    aspect_ratio = request.form.get("aspect_ratio", "16:9")
    duration = request.form.get("duration", "8")
    count = int(request.form.get("count", "1"))

    if not prompt:
        return jsonify({"ok": False, "error": "Prompt trống"}), 400
    if not api_key:
        api_key = _get_vg_config().get("api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"ok": False, "error": "Thiếu API Key"}), 400

    # Handle image upload (image-to-video)
    image_data = None
    image_mime = None
    if "image" in request.files:
        img_file = request.files["image"]
        if img_file.filename:
            image_data = img_file.read()
            image_mime = img_file.content_type or "image/png"

    # Create task
    task_id = str(uuid.uuid4())[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "state": "ACTIVE",
            "message": "Đang gửi request tới Gemini...",
            "videos": [],
            "error": None,
            "created": time.time(),
        }

    # Save config
    cfg = load_cfg()
    if "gemini_video" not in cfg:
        cfg["gemini_video"] = {}
    cfg["gemini_video"]["api_key"] = api_key
    cfg["gemini_video"]["model"] = model
    cfg["gemini_video"]["aspect_ratio"] = aspect_ratio
    cfg["gemini_video"]["duration"] = duration
    save_cfg(cfg)

    # Run generation in background thread
    thread = threading.Thread(
        target=_run_generation,
        args=(task_id, api_key, model, prompt, aspect_ratio, duration, count, image_data, image_mime),
        daemon=True
    )
    thread.start()

    return jsonify({"ok": True, "task_id": task_id})


def _run_generation(task_id: str, api_key: str, model: str, prompt: str,
                    aspect_ratio: str, duration: str, count: int,
                    image_data: Optional[bytes], image_mime: Optional[str]):
    """Background thread: call Gemini Veo API and save results."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        _update_task(task_id, state="PROCESSING", message="Đang gọi Gemini Veo API...")

        # Build generation config
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            number_of_videos=min(count, 4),
            duration_seconds=int(duration),
            person_generation="allow_all",
        )

        # Generate: text-to-video or image-to-video
        if image_data:
            # Image-to-video
            image = types.Image(
                image_bytes=image_data,
                mime_type=image_mime,
            )
            _update_task(task_id, message="Image-to-Video: đang xử lý...")
            operation = client.models.generate_videos(
                model=model,
                prompt=prompt,
                image=image,
                config=config,
            )
        else:
            # Text-to-video
            _update_task(task_id, message="Text-to-Video: đang xử lý...")
            operation = client.models.generate_videos(
                model=model,
                prompt=prompt,
                config=config,
            )

        # Poll until complete
        _update_task(task_id, message="Đang chờ Gemini xử lý (1-3 phút)...")

        # Wait for operation to complete
        max_wait = 600  # 10 minutes max
        start = time.time()
        while not operation.done:
            if time.time() - start > max_wait:
                _update_task(task_id, state="FAILED", error="Timeout: quá 10 phút")
                return
            time.sleep(10)
            operation = client.operations.get(operation)
            elapsed = int(time.time() - start)
            _update_task(task_id, message=f"Đang xử lý... ({elapsed}s)")

        # Check result
        if operation.error:
            _update_task(task_id, state="FAILED", error=str(operation.error))
            return

        # Save generated videos
        videos = []
        if operation.result and operation.result.generated_videos:
            for i, gv in enumerate(operation.result.generated_videos):
                # Download video
                video_data = client.files.download(file=gv.video)
                # Save to disk
                filename = f"{task_id}_{i + 1}.mp4"
                filepath = _VG_OUTPUT_DIR / filename
                with open(filepath, "wb") as f:
                    f.write(video_data)

                videos.append({
                    "url": f"/api/videogen/download/{task_id}_{i + 1}",
                    "filename": filename,
                })
                LOGGER.info("Video saved: %s", filepath)

        _update_task(task_id, state="SUCCEEDED", videos=videos,
                     message=f"Hoàn thành! {len(videos)} video đã tạo.")

    except ImportError:
        _update_task(task_id, state="FAILED",
                     error="Thiếu package google-genai. Chạy: pip install google-genai")
    except Exception as e:
        LOGGER.error("Video generation error: %s", e, exc_info=True)
        _update_task(task_id, state="FAILED", error=str(e))


def _update_task(task_id: str, **kwargs):
    """Thread-safe task state update."""
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)


# ─── GET /api/videogen/status/<task_id> ──────────────────────────────────────
@bp.route("/api/videogen/status/<task_id>", methods=["GET"])
def get_status(task_id: str):
    """Poll task status."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    return jsonify({
        "ok": True,
        "state": task["state"],
        "message": task.get("message", ""),
        "videos": task.get("videos", []),
        "error": task.get("error"),
    })


# ─── GET /api/videogen/download/<filename> ───────────────────────────────────
@bp.route("/api/videogen/download/<filename>", methods=["GET"])
def download_video(filename: str):
    """Serve generated video file."""
    # Security: only allow alphanumeric + underscore + dot
    safe = "".join(c for c in filename if c.isalnum() or c in "_-.")
    filepath = _VG_OUTPUT_DIR / safe
    if not filepath.exists():
        return jsonify({"ok": False, "error": "File not found"}), 404
    return send_file(filepath, mimetype="video/mp4", as_attachment=False)

"""
AI Studio Blueprint — gộp Video AI + Idea→Video + Image Generation.

Endpoints:
  ── Video (giữ nguyên từ videogen.py) ──
  POST /api/ai/video/generate       tạo video nhanh (text/image-to-video)
  GET  /api/ai/video/status/<id>    poll trạng thái
  GET  /api/ai/video/download/<id>  tải video

  ── Idea → Video (giữ nguyên từ idea2video.py) ──
  POST /api/ai/idea2video/start     bắt đầu pipeline
  GET  /api/ai/idea2video/status/<id>  poll
  GET  /api/ai/idea2video/download/<id>  tải

  ── Image Generation (MỚI) ──
  POST /api/ai/image/generate       tạo ảnh
  GET  /api/ai/image/download/<name>  tải ảnh

  ── Config chung ──
  GET  /api/ai/config               config tổng hợp
  POST /api/ai/config               lưu config
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file

from core_app import LOGGER, ROOT, load_cfg, save_cfg

bp = Blueprint("ai_studio", __name__)

# ── Output dirs ───────────────────────────────────────────────────────────────
_VIDEO_DIR = ROOT / "Downloaded" / "ai_video"
_IMAGE_DIR = ROOT / "Downloaded" / "ai_images"
_IDEA2VIDEO_DIR = ROOT / "Downloaded" / "idea2video"
_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
_IDEA2VIDEO_DIR.mkdir(parents=True, exist_ok=True)

# ── Task registry ─────────────────────────────────────────────────────────────
_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()


def _update_task(tid: str, **kwargs):
    with _tasks_lock:
        if tid in _tasks:
            _tasks[tid].update(kwargs)


def _get_task(tid: str) -> Optional[dict]:
    with _tasks_lock:
        return dict(_tasks[tid]) if tid in _tasks else None


def _gemini_key() -> str:
    cfg = load_cfg()
    return (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/ai/config", methods=["GET"])
def ai_config():
    cfg = load_cfg()
    gv = cfg.get("gemini_video") or {}
    nr = cfg.get("nine_router") or {}
    tr = cfg.get("translation") or {}

    key = _gemini_key()
    providers = []
    if key:
        providers.append("gemini")
    if (nr.get("api_key") or "").strip():
        providers.append("9router")
    if (tr.get("deepseek_key") or "").strip():
        providers.append("deepseek")
    if (tr.get("openai_key") or "").strip():
        providers.append("openai")

    return jsonify({
        "ok": True,
        "has_gemini_key": bool(key),
        "gemini_key_masked": (key[:8] + "...") if len(key) > 8 else "",
        "video_model": gv.get("model") or "veo-2.0-generate-001",
        "llm_model": gv.get("llm_model") or "gemini-2.5-flash",
        "llm_providers": providers,
        "image_model": gv.get("image_model") or "imagen-3.0-generate-002",
    })


@bp.route("/api/ai/config", methods=["POST"])
def ai_config_save():
    data = request.get_json(force=True) or {}
    cfg = load_cfg()
    gv = dict(cfg.get("gemini_video") or {})

    if "api_key" in data and data["api_key"]:
        gv["api_key"] = str(data["api_key"]).strip()
    if "video_model" in data:
        gv["model"] = str(data["video_model"]).strip()
    if "llm_model" in data:
        gv["llm_model"] = str(data["llm_model"]).strip()
    if "image_model" in data:
        gv["image_model"] = str(data["image_model"]).strip()

    cfg["gemini_video"] = gv
    save_cfg(cfg)
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO GENERATION (quick — single clip)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/ai/video/generate", methods=["POST"])
def video_generate():
    """Tạo video nhanh — proxy sang logic cũ của videogen.py."""
    prompt = request.form.get("prompt", "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "Prompt trống"}), 400

    api_key = request.form.get("api_key", "").strip() or _gemini_key()
    if not api_key:
        return jsonify({"ok": False, "error": "Thiếu Gemini API Key"}), 400

    model = request.form.get("model", "veo-2.0-generate-001")
    aspect_ratio = request.form.get("aspect_ratio", "16:9")
    duration = request.form.get("duration", "8")
    count = int(request.form.get("count", "1"))

    image_data = None
    image_mime = None
    if "image" in request.files:
        img_file = request.files["image"]
        if img_file.filename:
            image_data = img_file.read()
            image_mime = img_file.content_type or "image/png"

    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "type": "video",
            "state": "ACTIVE",
            "message": "Đang gửi request...",
            "videos": [],
            "error": None,
            "created": time.time(),
        }

    thread = threading.Thread(
        target=_run_video_gen,
        args=(task_id, api_key, model, prompt, aspect_ratio, duration, count, image_data, image_mime),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "task_id": task_id})


def _run_video_gen(task_id, api_key, model, prompt, aspect_ratio, duration, count, image_data, image_mime):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        _update_task(task_id, state="FAILED", error="Thiếu google-genai. pip install google-genai")
        return

    try:
        client = genai.Client(api_key=api_key)
        _update_task(task_id, message="Đang gọi Gemini Veo API...")

        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            number_of_videos=min(count, 4),
            duration_seconds=int(duration),
            person_generation="allow_all",
        )

        if image_data:
            image = types.Image(image_bytes=image_data, mime_type=image_mime)
            operation = client.models.generate_videos(model=model, prompt=prompt, image=image, config=config)
        else:
            operation = client.models.generate_videos(model=model, prompt=prompt, config=config)

        start = time.time()
        while not operation.done:
            if time.time() - start > 600:
                _update_task(task_id, state="FAILED", error="Timeout 10 phút")
                return
            time.sleep(10)
            operation = client.operations.get(operation)
            _update_task(task_id, message=f"Đang xử lý... ({int(time.time()-start)}s)")

        if operation.error:
            _update_task(task_id, state="FAILED", error=str(operation.error))
            return

        videos = []
        if operation.result and operation.result.generated_videos:
            for i, gv in enumerate(operation.result.generated_videos):
                video_data = client.files.download(file=gv.video)
                filename = f"{task_id}_{i+1}.mp4"
                filepath = _VIDEO_DIR / filename
                with open(filepath, "wb") as f:
                    f.write(video_data)
                videos.append({"url": f"/api/ai/video/download/{filename}", "filename": filename})

        _update_task(task_id, state="SUCCEEDED", videos=videos, message=f"Hoàn thành! {len(videos)} video.")
    except Exception as e:
        LOGGER.error("video_gen error: %s", e, exc_info=True)
        _update_task(task_id, state="FAILED", error=str(e))


@bp.route("/api/ai/video/status/<task_id>", methods=["GET"])
def video_status(task_id):
    task = _get_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    return jsonify({"ok": True, **{k: task[k] for k in ("state", "message", "videos", "error") if k in task}})


@bp.route("/api/ai/video/download/<filename>", methods=["GET"])
def video_download(filename):
    safe = "".join(c for c in filename if c.isalnum() or c in "_-.")
    fp = _VIDEO_DIR / safe
    if not fp.exists():
        return jsonify({"ok": False, "error": "Not found"}), 404
    return send_file(fp, mimetype="video/mp4")


# ══════════════════════════════════════════════════════════════════════════════
# IDEA → VIDEO (full pipeline)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/ai/idea2video/start", methods=["POST"])
def idea2video_start():
    data = request.get_json(force=True) or {}
    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"ok": False, "error": "Thiếu ý tưởng"}), 400

    user_requirement = (data.get("user_requirement") or "").strip()
    style = (data.get("style") or "cinematic, high quality").strip()

    cfg = load_cfg()
    jid = uuid.uuid4().hex[:12]
    working_dir = _IDEA2VIDEO_DIR / jid
    working_dir.mkdir(parents=True, exist_ok=True)

    with _tasks_lock:
        _tasks[jid] = {
            "type": "idea2video",
            "state": "running",
            "progress": 0,
            "message": "Khởi tạo...",
            "error": None,
            "output_path": None,
            "created": time.time(),
        }

    thread = threading.Thread(
        target=_run_idea2video,
        args=(jid, idea, user_requirement, style, cfg, working_dir),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "job_id": jid})


def _run_idea2video(jid, idea, user_requirement, style, cfg, working_dir):
    def progress_cb(pct, msg):
        if pct >= 0:
            _update_task(jid, progress=pct, message=msg)
        else:
            _update_task(jid, message=msg)

    try:
        from core.idea2video.pipeline import Idea2VideoPipeline
        pipeline = Idea2VideoPipeline.from_config(cfg, working_dir)
        output_path = pipeline.run(idea=idea, user_requirement=user_requirement, style=style, progress_cb=progress_cb)
        _update_task(jid, state="done", progress=100, message="Hoàn thành!", output_path=str(output_path))
    except Exception as e:
        import traceback
        LOGGER.error("idea2video error:\n%s", traceback.format_exc())
        _update_task(jid, state="error", message=str(e)[:200], error=str(e))


@bp.route("/api/ai/idea2video/status/<job_id>", methods=["GET"])
def idea2video_status(job_id):
    task = _get_task(job_id)
    if not task:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, **{k: task[k] for k in ("state", "progress", "message", "error") if k in task},
                    "has_output": bool(task.get("output_path"))})


@bp.route("/api/ai/idea2video/download/<job_id>", methods=["GET"])
def idea2video_download(job_id):
    safe_id = "".join(c for c in job_id if c.isalnum() or c in "-_")
    task = _get_task(safe_id)
    if not task or not task.get("output_path"):
        return jsonify({"ok": False, "error": "Not ready"}), 400
    fp = Path(task["output_path"])
    if not fp.exists():
        return jsonify({"ok": False, "error": "File not found"}), 404
    return send_file(fp, mimetype="video/mp4", as_attachment=True, download_name=fp.name)


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE GENERATION
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/ai/image/generate", methods=["POST"])
def image_generate():
    """Tạo ảnh — hỗ trợ 9Router, Gemini Imagen, OpenAI DALL-E."""
    data = request.get_json(force=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "Prompt trống"}), 400

    model = (data.get("model") or "9router").strip()
    count = min(int(data.get("count") or 1), 4)
    aspect_ratio = data.get("aspect_ratio") or "1:1"

    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            "type": "image",
            "state": "ACTIVE",
            "message": "Đang tạo ảnh...",
            "images": [],
            "error": None,
            "created": time.time(),
        }

    thread = threading.Thread(
        target=_run_image_gen,
        args=(task_id, model, prompt, count, aspect_ratio),
        daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "task_id": task_id})


def _run_image_gen(task_id, model, prompt, count, aspect_ratio):
    """Route tạo ảnh tới backend phù hợp."""
    if model.startswith(("imagen", "gemini")):
        api_key = _gemini_key()
        if not api_key:
            _update_task(task_id, state="FAILED", error="Thiếu Gemini API Key")
            return
        _run_image_gen_gemini(task_id, api_key, model, prompt, count, aspect_ratio)
    elif model in ("dall-e-3", "dalle-3"):
        # Legacy: gọi thẳng OpenAI DALL-E 3
        _run_image_gen_openai(task_id, prompt, count, aspect_ratio)
    else:
        # "9router" (mặc định cx/gpt-5.5-image) hoặc bất kỳ model id 9Router thật
        # (vd openai/gpt-image-1, nb/nanobanana-pro, cx/gpt-5.4-image, local…)
        model_id = "cx/gpt-5.5-image" if model in ("9router", "") else model
        _run_image_gen_9router(task_id, prompt, count, aspect_ratio, model_id)


def _run_image_gen_9router(task_id, prompt, count, aspect_ratio, model_id="cx/gpt-5.5-image"):
    """Tạo ảnh qua 9Router /v1/images/generations (OpenAI-compatible).

    Codex ``cx/*`` models stream the result as SSE; the shared helper handles
    both SSE and plain-JSON responses, so this works for every model id.
    """
    from utils.niner_image import build_image_payload, generate_images

    cfg = load_cfg()
    nr = cfg.get("nine_router") or {}
    api_key = (nr.get("api_key") or "").strip()
    endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/")

    if not api_key:
        _update_task(task_id, state="FAILED", error="Thiếu 9Router API key")
        return

    # Map aspect_ratio to size
    size_map = {"1:1": "1024x1024", "16:9": "1792x1024", "9:16": "1024x1792", "4:3": "1024x768", "3:4": "768x1024"}
    size = size_map.get(aspect_ratio, "1024x1024")

    payload = build_image_payload(
        (model_id or "cx/gpt-5.5-image"),
        prompt,
        n=count,
        size=size,
    )

    data_images, error = generate_images(endpoint, api_key, payload)
    if error:
        _update_task(task_id, state="FAILED", error=error)
        return

    images = []
    for i, item in enumerate(data_images):
        b64 = item.get("b64_json") or ""
        img_url = item.get("url") or ""
        if b64:
            filename = f"{task_id}_{i+1}.png"
            filepath = _IMAGE_DIR / filename
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            images.append({"url": f"/api/ai/image/download/{filename}", "filename": filename})
        elif img_url:
            images.append({"url": img_url, "filename": f"remote_{i+1}.png"})

    if images:
        _update_task(task_id, state="SUCCEEDED", images=images, message=f"Hoàn thành! {len(images)} ảnh.")
    else:
        _update_task(task_id, state="FAILED", error="9Router không trả về ảnh nào")


def _run_image_gen_openai(task_id, prompt, count, aspect_ratio):
    """Tạo ảnh qua OpenAI DALL-E 3."""
    import urllib.request
    import urllib.error

    cfg = load_cfg()
    tr = cfg.get("translation") or {}
    api_key = (tr.get("openai_key") or "").strip()
    if not api_key:
        _update_task(task_id, state="FAILED", error="Thiếu OpenAI API key (translation.openai_key)")
        return

    size_map = {"1:1": "1024x1024", "16:9": "1792x1024", "9:16": "1024x1792"}
    size = size_map.get(aspect_ratio, "1024x1024")

    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,  # DALL-E 3 chỉ hỗ trợ n=1
        "size": size,
        "response_format": "b64_json",
    }

    url = "https://api.openai.com/v1/images/generations"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err = ""
        try:
            err = e.read().decode()[:300]
        except Exception:
            pass
        _update_task(task_id, state="FAILED", error=f"OpenAI HTTP {e.code}: {err}")
        return
    except Exception as e:
        _update_task(task_id, state="FAILED", error=str(e))
        return

    images = []
    for i, item in enumerate(data.get("data") or []):
        b64 = item.get("b64_json") or ""
        if b64:
            filename = f"{task_id}_{i+1}.png"
            filepath = _IMAGE_DIR / filename
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            images.append({"url": f"/api/ai/image/download/{filename}", "filename": filename})

    if images:
        _update_task(task_id, state="SUCCEEDED", images=images, message=f"Hoàn thành! {len(images)} ảnh.")
    else:
        _update_task(task_id, state="FAILED", error="DALL-E không trả về ảnh")


def _run_image_gen_gemini(task_id, api_key, model, prompt, count, aspect_ratio):
    """Tạo ảnh bằng Gemini Imagen API."""
    import urllib.request
    import urllib.error

    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateImages?key={api_key}"
    )
    payload = {
        "prompt": prompt,
        "config": {
            "numberOfImages": count,
            "aspectRatio": aspect_ratio,
            "outputOptions": {"mimeType": "image/png"},
        },
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", "replace")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body[:200])
        except Exception:
            err_msg = err_body[:200] or f"HTTP {e.code}"
        _update_task(task_id, state="FAILED", error=err_msg)
        return
    except Exception as e:
        _update_task(task_id, state="FAILED", error=str(e))
        return

    # Parse response — Imagen returns generatedImages[].image.imageBytes (base64)
    generated = data.get("generatedImages") or []
    if not generated:
        # Fallback: try Gemini native image gen (generateContent with response_modalities)
        _run_image_gen_native(task_id, api_key, prompt, count)
        return

    images = []
    for i, item in enumerate(generated):
        img_bytes_b64 = (item.get("image") or {}).get("imageBytes") or ""
        if not img_bytes_b64:
            continue
        filename = f"{task_id}_{i+1}.png"
        filepath = _IMAGE_DIR / filename
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(img_bytes_b64))
        images.append({"url": f"/api/ai/image/download/{filename}", "filename": filename})

    if images:
        _update_task(task_id, state="SUCCEEDED", images=images, message=f"Hoàn thành! {len(images)} ảnh.")
    else:
        _update_task(task_id, state="FAILED", error="Không tạo được ảnh nào")


def _run_image_gen_native(task_id, api_key, prompt, count):
    """Fallback: dùng Gemini 2.0 Flash native image generation."""
    import urllib.request
    import urllib.error

    model = "gemini-2.5-flash-image"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as e:
        _update_task(task_id, state="FAILED", error=f"Native image gen failed: {e}")
        return

    candidates = data.get("candidates") or []
    images = []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or {}
            if inline.get("mimeType", "").startswith("image/"):
                img_b64 = inline.get("data", "")
                if img_b64:
                    ext = "png" if "png" in inline["mimeType"] else "jpg"
                    filename = f"{task_id}_{len(images)+1}.{ext}"
                    filepath = _IMAGE_DIR / filename
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(img_b64))
                    images.append({"url": f"/api/ai/image/download/{filename}", "filename": filename})

    if images:
        _update_task(task_id, state="SUCCEEDED", images=images, message=f"Hoàn thành! {len(images)} ảnh.")
    else:
        _update_task(task_id, state="FAILED", error="Không tạo được ảnh (model có thể chưa hỗ trợ)")


@bp.route("/api/ai/image/status/<task_id>", methods=["GET"])
def image_status(task_id):
    task = _get_task(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, **{k: task[k] for k in ("state", "message", "images", "error") if k in task}})


@bp.route("/api/ai/image/download/<filename>", methods=["GET"])
def image_download(filename):
    safe = "".join(c for c in filename if c.isalnum() or c in "_-.")
    fp = _IMAGE_DIR / safe
    if not fp.exists():
        return jsonify({"ok": False, "error": "Not found"}), 404
    mime = "image/png" if fp.suffix == ".png" else "image/jpeg"
    return send_file(fp, mimetype=mime)

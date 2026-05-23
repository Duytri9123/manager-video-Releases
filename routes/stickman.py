"""Stickman Studio Blueprint — render video nhân vật que bằng code.

Tại sao tự render thay vì Canva?
- Canva Connect API không expose animation engine (chỉ Autofill template tĩnh).
- Tự code = nhanh, offline, scale tốt cho hàng loạt video TikTok/Shorts/Reels,
  dễ đồng bộ chính xác với TTS theo mili-giây.

Endpoints
─────────
GET  /api/stickman/poses             liệt kê pose presets có sẵn
GET  /api/stickman/preview/<pose>    PNG preview 1 pose (để hiển thị thumbnail)
POST /api/stickman/render            nhận scenes JSON, render MP4 ở background
GET  /api/stickman/status/<sid>      poll progress + log
POST /api/stickman/cancel/<sid>      huỷ session đang render
GET  /api/stickman/file/<sid>        tải MP4 đã render
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, abort, jsonify, request, send_file

from core.stickman import (
    Scene,
    list_poses,
    render_preview_png,
    render_preview_png_v3,
    render_video,
)
from core.stickman.ai_director import (
    generate_scenes,
    EMOTIONS, CHARACTER_STYLES, PROPS,
    BACKGROUND_PRESETS, GROUND_STYLES, SCENE_OBJECT_NAMES, TRANSITIONS,
)
from core_app import LOGGER, ROOT


bp = Blueprint("stickman", __name__)

# Output directory
_OUT_DIR = ROOT / "Downloaded" / "stickman"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

# Session registry
_sessions: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


# ── Helpers ─────────────────────────────────────────────────────────────────
def _new_session() -> Dict[str, Any]:
    return {
        "status": "starting",
        "log": [],
        "error": "",
        "done": False,
        "progress": 0,
        "progress_label": "",
        "frame_done": 0,
        "frame_total": 0,
        "output_path": "",
        "duration": 0.0,
        "fps": 24,
        "width": 0,
        "height": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "stop_event": threading.Event(),
    }


def _log(sid: str, msg: str, level: str = "info") -> None:
    LOGGER.info("[stickman %s] %s", sid[:8], msg)
    with _lock:
        s = _sessions.get(sid)
        if not s:
            return
        s["log"].append({"t": time.time(), "level": level, "msg": msg})
        # Cap log length so memory doesn't blow up.
        if len(s["log"]) > 500:
            s["log"] = s["log"][-500:]
        s["updated_at"] = time.time()


def _set_status(sid: str, **fields) -> None:
    with _lock:
        s = _sessions.get(sid)
        if not s:
            return
        s.update(fields)
        s["updated_at"] = time.time()


def _parse_scenes(raw: Any) -> List[Scene]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("scenes phải là 1 list không rỗng.")
    scenes: List[Scene] = []
    valid = set(list_poses())
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"scene[{i}] không hợp lệ.")
        pose_to = str(item.get("pose") or "").strip()
        if pose_to not in valid:
            raise ValueError(f"scene[{i}].pose='{pose_to}' không tồn tại.")
        try:
            duration = float(item.get("duration") or 1.0)
        except (TypeError, ValueError):
            duration = 1.0
        try:
            hold = float(item.get("hold") or 0.0)
        except (TypeError, ValueError):
            hold = 0.0
        duration = max(0.1, min(15.0, duration))
        hold = max(0.0, min(15.0, hold))
        pose_from = item.get("pose_from")
        if pose_from is not None:
            pose_from = str(pose_from).strip() or None
            if pose_from and pose_from not in valid:
                raise ValueError(f"scene[{i}].pose_from='{pose_from}' không tồn tại.")
        easing = "linear" if str(item.get("easing") or "ease") == "linear" else "ease"
        caption = str(item.get("caption") or "").strip()[:300]

        # Enhanced fields
        emotion = str(item.get("emotion") or "neutral").strip().lower()
        if emotion not in EMOTIONS:
            emotion = "neutral"
        character_style = str(item.get("character_style") or "normal").strip().lower()
        if character_style not in CHARACTER_STYLES:
            character_style = "normal"
        props_raw = item.get("props") or []
        if isinstance(props_raw, str):
            props_raw = [props_raw]
        props = [p for p in props_raw if p in PROPS] or None
        background_image = str(item.get("background_image") or "").strip() or None

        # Scene composition fields
        background_preset = str(item.get("background_preset") or "neutral").strip().lower()
        if background_preset not in {"sky", "sunset", "night", "forest", "ocean", "classroom", "space", "warm", "cool", "neutral"}:
            background_preset = "neutral"
        ground = str(item.get("ground") or "none").strip().lower()
        if ground not in {"flat", "grass", "floor", "road", "none"}:
            ground = "none"
        scene_objects_raw = item.get("scene_objects") or []
        if isinstance(scene_objects_raw, str):
            scene_objects_raw = [scene_objects_raw]
        valid_objects = {"desk", "whiteboard", "tree", "sun", "moon", "cloud", "building", "computer", "chair", "stage", "podium", "lamp"}
        scene_objects = [o for o in scene_objects_raw if o in valid_objects][:5] or None
        speech = str(item.get("speech") or "").strip()[:200]
        transition = str(item.get("transition") or "none").strip().lower()
        if transition not in {"fade", "slide_left", "slide_up", "zoom_in", "none"}:
            transition = "none"
        try:
            num_characters = int(item.get("num_characters") or 1)
        except (TypeError, ValueError):
            num_characters = 1
        num_characters = max(1, min(3, num_characters))

        scenes.append(
            Scene(
                pose_to=pose_to,
                duration=duration,
                hold=hold,
                pose_from=pose_from,
                easing=easing,
                caption=caption,
                emotion=emotion,
                character_style=character_style,
                props=props,
                background_image=background_image,
                background_preset=background_preset,
                ground=ground,
                scene_objects=scene_objects,
                speech=speech,
                transition=transition,
                num_characters=num_characters,
            )
        )
    return scenes


# ── Endpoints ───────────────────────────────────────────────────────────────
@bp.route("/api/stickman/poses", methods=["GET"])
def api_poses():
    return jsonify({"ok": True, "poses": list_poses()})


@bp.route("/api/stickman/preview/<pose_name>", methods=["GET"])
def api_preview(pose_name: str):
    try:
        from flask import Response
        emotion = request.args.get("emotion", "neutral")
        png = render_preview_png_v3(pose_name, emotion=emotion)
        return Response(png, mimetype="image/png")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/api/stickman/render", methods=["POST"])
def api_render():
    data = request.get_json(silent=True) or {}
    try:
        scenes = _parse_scenes(data.get("scenes"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Resolution
    preset = str(data.get("preset") or "vertical")
    if preset == "vertical":
        size = (1080, 1920)
    elif preset == "square":
        size = (1080, 1080)
    elif preset == "horizontal":
        size = (1920, 1080)
    else:
        try:
            w = int(data.get("width") or 1080)
            h = int(data.get("height") or 1920)
        except (TypeError, ValueError):
            w, h = 1080, 1920
        # Reasonable bounds.
        w = max(240, min(3840, w))
        h = max(240, min(3840, h))
        size = (w, h)

    try:
        fps = int(data.get("fps") or 24)
    except (TypeError, ValueError):
        fps = 24
    fps = max(8, min(60, fps))

    bg_color = str(data.get("bg_color") or "#ffffff")[:9]
    line_color = str(data.get("line_color") or "#1a2332")[:9]

    audio_path_raw = (data.get("audio_path") or "").strip()
    audio_path: Optional[Path] = None
    if audio_path_raw:
        ap = Path(audio_path_raw)
        if not ap.is_absolute():
            ap = ROOT / ap
        if ap.exists() and ap.is_file():
            audio_path = ap
        else:
            return jsonify(
                {"ok": False, "error": f"audio_path không tồn tại: {ap}"}
            ), 400

    # Output filename
    name = str(data.get("name") or "").strip()
    if not name:
        name = f"stickman_{int(time.time())}"
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_") or "stickman"
    sid = uuid.uuid4().hex
    output_path = _OUT_DIR / f"{safe_name}_{sid[:8]}.mp4"

    sess = _new_session()
    sess["fps"] = fps
    sess["width"] = size[0]
    sess["height"] = size[1]
    sess["output_path"] = str(output_path)
    with _lock:
        _sessions[sid] = sess
    _log(sid, f"Bắt đầu render {len(scenes)} scenes · {size[0]}x{size[1]} @ {fps}fps")

    def _worker():
        try:
            def _cb(done: int, total: int, label: str):
                pct = int(done * 100 / max(1, total))
                _set_status(
                    sid,
                    progress=pct,
                    progress_label=label,
                    frame_done=done,
                    frame_total=total,
                )

            _set_status(sid, status="rendering")
            result = render_video(
                scenes,
                output_path,
                size=size,
                fps=fps,
                bg_color=bg_color,
                line_color=line_color,
                audio_path=audio_path,
                progress_cb=_cb,
                cancel_event=sess["stop_event"],
            )
            for line in result.log:
                _log(sid, line)
            _set_status(
                sid,
                status="done",
                done=True,
                progress=100,
                progress_label="Hoàn tất",
                duration=result.duration,
                output_path=str(result.output_path),
                frame_done=result.frame_count,
                frame_total=result.frame_count,
            )
            _log(sid, f"Render xong, dài {result.duration:.2f}s.", level="success")
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("[stickman] Render failed")
            _set_status(
                sid,
                status="error",
                done=True,
                error=str(exc),
                progress_label="Lỗi",
            )
            _log(sid, f"Render lỗi: {exc}", level="error")

    th = threading.Thread(target=_worker, name=f"stickman-{sid[:8]}", daemon=True)
    th.start()

    return jsonify({"ok": True, "session_id": sid, "output_path": str(output_path)})


@bp.route("/api/stickman/status/<sid>", methods=["GET"])
def api_status(sid: str):
    with _lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "session not found"}), 404
        # Return a shallow copy without the threading.Event
        out = {k: v for k, v in s.items() if k != "stop_event"}
    return jsonify({"ok": True, **out})


@bp.route("/api/stickman/cancel/<sid>", methods=["POST"])
def api_cancel(sid: str):
    with _lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "session not found"}), 404
        s["stop_event"].set()
    _log(sid, "Đã yêu cầu huỷ.", level="warning")
    return jsonify({"ok": True})


@bp.route("/api/stickman/file/<sid>", methods=["GET"])
def api_file(sid: str):
    with _lock:
        s = _sessions.get(sid)
        if not s:
            abort(404)
        path = Path(s.get("output_path") or "")
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", as_attachment=False, download_name=path.name)


# ── AI Director endpoint ────────────────────────────────────────────────────
@bp.route("/api/stickman/ai_generate", methods=["POST"])
def api_ai_generate():
    """Use LLM (9Router) to generate scenes from content/topic.

    Request JSON:
        content: str (required) — nội dung/chủ đề
        language: str — "vi" | "en" (default "vi")
        num_scenes: int — 5-15 (default 8)
        style: str — "giải thích" | "kể chuyện" | "hài hước" | "quảng cáo"
        model: str — override model (optional)
        temperature: float — 0.0-1.5 (default 0.7)

    Response:
        ok: True, scenes: [...] — list of scene dicts ready for render
    """
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "Cần nhập nội dung/chủ đề."}), 400

    language = str(data.get("language") or "vi").strip()[:5]
    try:
        num_scenes = int(data.get("num_scenes") or 8)
    except (TypeError, ValueError):
        num_scenes = 8
    num_scenes = max(3, min(20, num_scenes))

    style = str(data.get("style") or "giải thích").strip()[:50]
    model = data.get("model") or None
    try:
        temperature = float(data.get("temperature") or 0.7)
    except (TypeError, ValueError):
        temperature = 0.7
    temperature = max(0.0, min(1.5, temperature))

    ok, result = generate_scenes(
        content,
        language=language,
        num_scenes=num_scenes,
        style=style,
        model=model,
        temperature=temperature,
    )

    if not ok:
        return jsonify({"ok": False, "error": result}), 502

    return jsonify({
        "ok": True,
        "scenes": result,
        "count": len(result),
        "emotions": sorted(EMOTIONS),
        "character_styles": sorted(CHARACTER_STYLES),
        "props": sorted(PROPS),
    })


@bp.route("/api/stickman/meta", methods=["GET"])
def api_meta():
    """Return available options for the enhanced stickman features."""
    return jsonify({
        "ok": True,
        "poses": list_poses(),
        "emotions": sorted(EMOTIONS),
        "character_styles": sorted(CHARACTER_STYLES),
        "props": sorted(PROPS),
        "background_presets": sorted(BACKGROUND_PRESETS),
        "ground_styles": sorted(GROUND_STYLES),
        "scene_objects": sorted(SCENE_OBJECT_NAMES),
        "transitions": sorted(TRANSITIONS),
    })

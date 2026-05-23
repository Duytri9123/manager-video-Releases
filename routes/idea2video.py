"""
Idea2Video Blueprint — tạo video từ ý tưởng theo kiến trúc ViMax.

Endpoints:
  POST /api/idea2video/start     bắt đầu pipeline (trả về job_id)
  GET  /api/idea2video/status/<job_id>   poll trạng thái
  GET  /api/idea2video/download/<job_id> tải video kết quả
  GET  /api/idea2video/config    lấy config hiện tại
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_file

from core_app import LOGGER, ROOT, load_cfg

bp = Blueprint("idea2video", __name__)

# ── Job registry ──────────────────────────────────────────────────────────────
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

_OUTPUT_DIR = ROOT / "Downloaded" / "idea2video"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _create_job() -> str:
    jid = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[jid] = {
            "state": "queued",
            "progress": 0,
            "message": "Đang chờ...",
            "error": None,
            "output_path": None,
            "created": time.time(),
            "finished": None,
        }
    return jid


def _update_job(jid: str, **kwargs):
    with _jobs_lock:
        if jid in _jobs:
            _jobs[jid].update(kwargs)


def _get_job(jid: str) -> Optional[dict]:
    with _jobs_lock:
        return dict(_jobs[jid]) if jid in _jobs else None


# ── POST /api/idea2video/start ────────────────────────────────────────────────
@bp.route("/api/idea2video/start", methods=["POST"])
def start():
    data = request.get_json(force=True) or {}
    idea = (data.get("idea") or "").strip()
    if not idea:
        return jsonify({"ok": False, "error": "Thiếu ý tưởng (idea)"}), 400

    user_requirement = (data.get("user_requirement") or "").strip()
    style = (data.get("style") or "cinematic, high quality").strip()

    cfg = load_cfg()
    jid = _create_job()

    # Tạo working dir riêng cho job này
    working_dir = _OUTPUT_DIR / jid
    working_dir.mkdir(parents=True, exist_ok=True)

    thread = threading.Thread(
        target=_run_pipeline,
        args=(jid, idea, user_requirement, style, cfg, working_dir),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "job_id": jid})


def _run_pipeline(jid: str, idea: str, user_requirement: str, style: str,
                  cfg: dict, working_dir: Path):
    _update_job(jid, state="running", message="Khởi tạo pipeline...")

    def progress_cb(pct: int, msg: str):
        if pct >= 0:
            _update_job(jid, progress=pct, message=msg)
        else:
            _update_job(jid, message=msg)

    try:
        from core.idea2video.pipeline import Idea2VideoPipeline
        pipeline = Idea2VideoPipeline.from_config(cfg, working_dir)
        output_path = pipeline.run(
            idea=idea,
            user_requirement=user_requirement,
            style=style,
            progress_cb=progress_cb,
        )
        _update_job(
            jid,
            state="done",
            progress=100,
            message=f"Hoàn thành! {output_path.name}",
            output_path=str(output_path),
            finished=time.time(),
        )
        LOGGER.info("idea2video job %s hoàn thành: %s", jid, output_path)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        LOGGER.error("idea2video job %s thất bại:\n%s", jid, tb)
        _update_job(
            jid,
            state="error",
            message=f"Lỗi: {str(e)[:200]}",
            error=str(e),
            finished=time.time(),
        )


# ── GET /api/idea2video/status/<job_id> ───────────────────────────────────────
@bp.route("/api/idea2video/status/<job_id>", methods=["GET"])
def status(job_id: str):
    job = _get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job không tồn tại"}), 404
    return jsonify({
        "ok": True,
        "state": job["state"],
        "progress": job["progress"],
        "message": job["message"],
        "error": job.get("error"),
        "has_output": bool(job.get("output_path")),
    })


# ── GET /api/idea2video/download/<job_id> ─────────────────────────────────────
@bp.route("/api/idea2video/download/<job_id>", methods=["GET"])
def download(job_id: str):
    # Sanitize job_id
    safe_id = "".join(c for c in job_id if c.isalnum() or c in "-_")
    job = _get_job(safe_id)
    if not job:
        return jsonify({"ok": False, "error": "Job không tồn tại"}), 404
    if job["state"] != "done" or not job.get("output_path"):
        return jsonify({"ok": False, "error": "Video chưa sẵn sàng"}), 400

    output_path = Path(job["output_path"])
    if not output_path.exists():
        return jsonify({"ok": False, "error": "File không tồn tại"}), 404

    return send_file(
        output_path,
        mimetype="video/mp4",
        as_attachment=True,
        download_name=output_path.name,
    )


# ── GET /api/idea2video/config ────────────────────────────────────────────────
@bp.route("/api/idea2video/config", methods=["GET"])
def get_config():
    cfg = load_cfg()
    nr = cfg.get("nine_router") or {}
    gemini = cfg.get("gemini_video") or {}
    tr = cfg.get("translation") or {}

    # Kiểm tra provider nào đang available
    providers = []
    if (nr.get("api_key") or "").strip():
        providers.append("9router")
    gemini_key = (gemini.get("api_key") or "").strip()
    import os
    if not gemini_key:
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        providers.append("gemini")
    if (tr.get("deepseek_key") or "").strip():
        providers.append("deepseek")
    if (tr.get("openai_key") or "").strip():
        providers.append("openai")
    if (tr.get("groq_key") or "").strip():
        providers.append("groq")

    return jsonify({
        "ok": True,
        "llm_providers": providers,
        "video_backend": "gemini_veo2" if gemini_key else "mock",
        "gemini_model": gemini.get("model") or "veo-2.0-generate-001",
        "gemini_llm_model": gemini.get("llm_model") or "gemini-2.5-flash",
        "has_gemini_key": bool(gemini_key),
    })

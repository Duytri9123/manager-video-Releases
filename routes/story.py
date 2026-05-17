"""Story / Novel / Comic → video script blueprint."""
import json
import time
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from core.story_writer import (
    ChunkOptions,
    StoryRequest,
    chunk_into_segments,
    estimate_duration_sec,
    fetch_url_text,
    list_comic_images,
    maybe_translate_segments,
    normalize_text,
    ocr_folder,
    run_pipeline,
)
from core_app import ROOT, STATE_DIR, TEMP_UPLOADS_DIR, load_cfg
from utils.security import safe_filename, safe_join

bp = Blueprint("story", __name__)


def _cfg():
    return load_cfg() or {}


def _chunk_opts(data: dict) -> ChunkOptions:
    cfg = _cfg()
    sw = (cfg.get("storywriter") or {}).get("chunk") or {}
    return ChunkOptions(
        target_chars=int(data.get("target_chars") or sw.get("target_chars_per_segment") or 350),
        max_chars=int(data.get("max_chars") or sw.get("max_chars_per_segment") or 600),
        overlap_sentences=int(data.get("overlap_sentences") or sw.get("overlap_sentences") or 0),
    )


def _output_dir() -> Path:
    cfg = _cfg()
    out = (cfg.get("storywriter") or {}).get("output_dir") or "./Downloaded/scripts"
    p = Path(out)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


@bp.route("/api/story/normalize", methods=["POST"])
def story_normalize():
    data = request.get_json(silent=True) or {}
    text = normalize_text(data.get("text") or "")
    return jsonify({"ok": True, "text": text, "char_count": len(text)})


@bp.route("/api/story/fetch_url", methods=["POST"])
def story_fetch_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL không hợp lệ."}), 400
    try:
        text = fetch_url_text(url, proxy_url=(data.get("proxy_url") or "").strip())
        return jsonify({"ok": True, "text": text, "char_count": len(text)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/chunk", methods=["POST"])
def story_chunk():
    data = request.get_json(silent=True) or {}
    text = normalize_text(data.get("text") or "")
    if not text:
        return jsonify({"ok": False, "error": "Thiếu text."}), 400
    opts = _chunk_opts(data)
    segs = chunk_into_segments(text, opts)
    return jsonify({
        "ok": True,
        "segment_count": len(segs),
        "est_duration_sec": round(sum(s.est_duration_sec for s in segs), 1),
        "segments": [s.to_dict() for s in segs],
    })


@bp.route("/api/story/generate", methods=["POST"])
def story_generate():
    """Full pipeline: text|url → normalize → chunk → optional translate → JSON."""
    data = request.get_json(silent=True) or {}
    req = StoryRequest(
        text=data.get("text") or "",
        url=(data.get("url") or "").strip(),
        title=(data.get("title") or "").strip(),
        target_lang=(data.get("target_lang") or _cfg().get("storywriter", {}).get("default_target_lang") or "vi"),
        translate=bool(data.get("translate")),
        provider=(data.get("provider") or _cfg().get("storywriter", {}).get("default_provider") or "auto"),
        chunk_opts=_chunk_opts(data),
        proxy_url=(data.get("proxy_url") or "").strip(),
    )
    try:
        out = run_pipeline(req, _cfg())
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500

    # Persist a copy under output_dir
    if data.get("save", True):
        ts = int(time.time())
        title_safe = safe_filename(req.title or f"story_{ts}", fallback=f"story_{ts}")
        save_path = _output_dir() / f"{title_safe}_{ts}.json"
        try:
            save_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            out["saved_to"] = str(save_path.relative_to(ROOT))
        except Exception:
            pass
    return jsonify({"ok": True, **out})


# ── Comic upload (zip of images) ────────────────────────────────────────────
@bp.route("/api/story/comic_upload", methods=["POST"])
def comic_upload():
    """Upload a ZIP of comic page images and return an unpack token."""
    upl = request.files.get("file")
    if not upl:
        return jsonify({"ok": False, "error": "Thiếu file."}), 400
    name = secure_filename(upl.filename or "comic.zip")
    if not name.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "Chỉ chấp nhận .zip"}), 400
    token = f"comic_{int(time.time())}_{abs(hash(name)) % 10000:04d}"
    target = TEMP_UPLOADS_DIR / token
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / "src.zip"
    upl.save(str(zip_path))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                # Skip directory traversal in zip members
                clean = safe_filename(Path(member).name, fallback="img.bin")
                if not clean:
                    continue
                with zf.open(member) as src, open(target / clean, "wb") as dst:
                    dst.write(src.read(50_000_000))  # 50 MB / file cap
    except zipfile.BadZipFile:
        return jsonify({"ok": False, "error": "ZIP hỏng."}), 400
    finally:
        try:
            zip_path.unlink()
        except Exception:
            pass
    images = list_comic_images(target)
    return jsonify({"ok": True, "token": token, "image_count": len(images)})


@bp.route("/api/story/comic_ocr", methods=["POST"])
def comic_ocr():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    lang = (data.get("lang") or "vie+eng").strip()
    if not token:
        return jsonify({"ok": False, "error": "Thiếu token."}), 400
    try:
        folder = safe_join(TEMP_UPLOADS_DIR, token)
    except ValueError:
        return jsonify({"ok": False, "error": "Token không hợp lệ."}), 400
    if not folder.exists():
        return jsonify({"ok": False, "error": "Không tìm thấy phiên upload."}), 404
    text = ocr_folder(folder, lang=lang)
    return jsonify({"ok": True, "text": text, "char_count": len(text)})

"""Story / Novel / Comic / MangaDex → video script + video blueprint."""
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, abort
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


# ── MangaDex helpers ────────────────────────────────────────────────────────
def _md_client(cfg: dict):
    """Build a MangaDexClient honoring the proxy pool when available."""
    from core.mangadex_client import MangaDexClient
    proxy = ""
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg) or ""
    except Exception:
        proxy = ""
    return MangaDexClient(proxy_url=proxy or None)


def _proxy_url() -> str:
    cfg = load_cfg() or {}
    try:
        from core.proxy_resolver import resolve_proxy
        return resolve_proxy(cfg) or ""
    except Exception:
        return ""


def _split_cubari_id(value: str) -> tuple[str, str, str]:
    """Parse 'cubari:<source>/<slug>[/<chapter>]' → (source, slug, chapter)."""
    s = (value or "").strip()
    if s.startswith("cubari:"):
        s = s[len("cubari:"):]
    parts = s.split("/", 2)
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def _manga_output_dir(cfg: dict) -> Path:
    out = (cfg.get("storywriter") or {}).get("manga_output_dir") or "./Downloaded/manga_videos"
    p = Path(out)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


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
    provider = (data.get("provider") or "").strip().lower()
    vision_model = (data.get("vision_model") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Thiếu token."}), 400
    try:
        folder = safe_join(TEMP_UPLOADS_DIR, token)
    except ValueError:
        return jsonify({"ok": False, "error": "Token không hợp lệ."}), 400
    if not folder.exists():
        return jsonify({"ok": False, "error": "Không tìm thấy phiên upload."}), 404

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    # Provider precedence:
    #   • Explicit body["provider"] wins.
    #   • Otherwise honour storywriter.comic.ocr_provider from config.
    if not provider:
        provider = ((cfg.get("storywriter") or {}).get("comic") or {}).get("ocr_provider") or "tesseract"
    # When user picks 9router but hasn't cached a key yet, fall back to tesseract
    # rather than 500ing — and surface a hint in the response.
    used_provider = provider
    if provider == "9router" and not (nr_cfg.get("api_key") or "").strip():
        used_provider = "tesseract"

    text = ocr_folder(
        folder,
        lang=lang,
        provider=used_provider,
        nine_router_cfg=nr_cfg if used_provider == "9router" else None,
        vision_model=vision_model,
    )
    return jsonify({
        "ok": True,
        "text": text,
        "char_count": len(text),
        "provider_used": used_provider,
        "fallback": used_provider != provider,
    })


# ══════════════════════════════════════════════════════════════════════════════
# MangaDex integration — search → chapters → pages → render
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/manga/search", methods=["POST", "GET"])
def manga_search():
    """Free-text search across MangaDex (default) or Cubari (paste a URL).

    Body fields:
        title:       free-text title (MangaDex only).
        url:         a cubari.moe URL — when present we fetch only that series.
        source:      'mangadex' (default) | 'cubari'.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    title = (data.get("title") or data.get("q") or "").strip()
    url_value = (data.get("url") or "").strip()
    source = (data.get("source") or "").strip().lower() or (
        "cubari" if url_value or title.startswith("http") else "mangadex"
    )

    # ── Cubari source (URL-only lookup) ────────────────────────────
    if source == "cubari":
        from core.cubari_client import (
            parse_cubari_url, get_series, series_to_summary,
        )
        candidate = url_value or title
        parsed = parse_cubari_url(candidate)
        if not parsed:
            return jsonify({
                "ok": False,
                "error": "Cubari cần một URL dạng https://cubari.moe/read/<source>/<slug>/.",
            }), 400
        try:
            raw = get_series(parsed["source"], parsed["slug"], proxy_url=_proxy_url() or None)
            summary = series_to_summary(parsed["source"], parsed["slug"], raw)
            return jsonify({"ok": True, "items": [summary.to_dict()], "count": 1, "source": "cubari"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    # ── Default: MangaDex ─────────────────────────────────────────
    limit = max(1, min(50, int(data.get("limit") or 20)))
    offset = max(0, int(data.get("offset") or 0))
    langs_raw = data.get("languages")
    if isinstance(langs_raw, str):
        langs = [s.strip() for s in langs_raw.split(",") if s.strip()]
    elif isinstance(langs_raw, list):
        langs = [str(s).strip() for s in langs_raw if str(s).strip()]
    else:
        langs = ["vi", "en"]
    ratings_raw = data.get("ratings")
    if isinstance(ratings_raw, str):
        ratings = [s.strip() for s in ratings_raw.split(",") if s.strip()]
    elif isinstance(ratings_raw, list):
        ratings = [str(s).strip() for s in ratings_raw if str(s).strip()]
    else:
        ratings = ["safe", "suggestive"]
    try:
        client = _md_client(load_cfg() or {})
        results = client.search_manga(
            title,
            limit=limit,
            offset=offset,
            translated_languages=langs or None,
            content_ratings=ratings or None,
        )
        return jsonify({
            "ok": True,
            "items": [r.to_dict() for r in results],
            "count": len(results),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/details", methods=["POST", "GET"])
def manga_details():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_id = (data.get("manga_id") or data.get("id") or "").strip()
    if not manga_id:
        return jsonify({"ok": False, "error": "Thiếu manga_id."}), 400
    try:
        client = _md_client(load_cfg() or {})
        info = client.get_manga(manga_id)
        return jsonify({"ok": True, "manga": info.to_dict()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/chapters", methods=["POST", "GET"])
def manga_chapters():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_id = (data.get("manga_id") or data.get("id") or "").strip()
    if not manga_id:
        return jsonify({"ok": False, "error": "Thiếu manga_id."}), 400

    # Cubari id?
    if manga_id.startswith("cubari:"):
        from core.cubari_client import list_chapters as cubari_list
        source, slug, _ = _split_cubari_id(manga_id)
        try:
            chapters = cubari_list(source, slug, proxy_url=_proxy_url() or None)
            order_dir = (data.get("order_dir") or "asc").lower()
            if order_dir == "desc":
                chapters = list(reversed(chapters))
            return jsonify({
                "ok": True,
                "chapters": [c.to_dict() for c in chapters],
                "count": len(chapters),
                "source": "cubari",
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    langs_raw = data.get("languages")
    if isinstance(langs_raw, str):
        langs = [s.strip() for s in langs_raw.split(",") if s.strip()]
    elif isinstance(langs_raw, list):
        langs = [str(s).strip() for s in langs_raw if str(s).strip()]
    else:
        langs = ["vi", "en"]
    order_dir = (data.get("order_dir") or "asc").lower()
    if order_dir not in ("asc", "desc"):
        order_dir = "asc"
    try:
        client = _md_client(load_cfg() or {})
        chapters = client.list_chapters(
            manga_id,
            translated_languages=langs or None,
            order_dir=order_dir,
        )
        return jsonify({
            "ok": True,
            "chapters": [c.to_dict() for c in chapters],
            "count": len(chapters),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/chapter_pages", methods=["POST", "GET"])
def manga_chapter_pages():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    if not chapter_id:
        return jsonify({"ok": False, "error": "Thiếu chapter_id."}), 400
    saver = bool(data.get("saver"))

    # Cubari chapter ids look like "cubari:source/slug/<chapter>"
    if chapter_id.startswith("cubari:"):
        from core.cubari_client import get_chapter_pages as cubari_pages
        source, slug, ch = _split_cubari_id(chapter_id)
        try:
            pages = cubari_pages(source, slug, ch, proxy_url=_proxy_url() or None)
            return jsonify({
                "ok": True,
                "chapter_id": chapter_id,
                "base_url": "",
                "hash": "",
                "page_count": len(pages.pages),
                "pages": pages.pages,
                "pages_full": pages.pages,
                "pages_saver": pages.pages_saver,
                "source": "cubari",
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    try:
        client = _md_client(load_cfg() or {})
        pages = client.get_chapter_pages(chapter_id)
        return jsonify({
            "ok": True,
            "chapter_id": chapter_id,
            "base_url": pages.base_url,
            "hash": pages.hash,
            "page_count": len(pages.pages),
            "pages": pages.page_urls(saver=saver),
            "pages_full": pages.page_urls(saver=False),
            "pages_saver": pages.page_urls(saver=True),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/image_proxy", methods=["GET"])
def manga_image_proxy():
    """Proxy a manga CDN image so the browser can render it without
    bumping into Referer/CORS issues.

    Allows public HTTPS image hosts, but blocks private/loopback IPs to
    prevent SSRF abuse.
    """
    import ipaddress
    import socket
    import urllib.parse as _up
    import urllib.request as _ur
    from flask import Response

    url = (request.args.get("url") or "").strip()
    if not url:
        return abort(400)
    parsed = _up.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return abort(400)
    host = (parsed.hostname or "").lower()
    if not host:
        return abort(400)

    # Resolve and reject private / loopback / link-local addresses
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else ""
            if not ip:
                continue
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_multicast or addr.is_reserved):
                return abort(403)
    except socket.gaierror:
        return abort(502)

    # Pick a referer that matches the host so the upstream CDN doesn't
    # 403 us. Manga CDNs almost always require a same-origin referer.
    referer = f"{parsed.scheme}://{host}/"
    try:
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; DuyTrisManga/1.0)",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        with _ur.urlopen(req, timeout=20) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
        # Only forward responses that are actually images
        if not ctype.lower().startswith(("image/", "application/octet-stream")):
            return abort(415)
        return Response(
            data,
            mimetype=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 502


# ── MangaDex → narration: build per-page TTS text ──────────────────────────
@bp.route("/api/story/manga/build_narration", methods=["POST"])
def manga_build_narration():
    """Take the user's text (from OCR or manual input) + a list of page URLs
    and produce panel-by-panel narration segments.

    Modes:
      - 'split'  : evenly split a single text block across N pages.
      - 'manual' : caller supplies one narration string per page.
    """
    data = request.get_json(silent=True) or {}
    pages = data.get("pages") or []
    mode = (data.get("mode") or "split").lower()
    text = (data.get("text") or "").strip()
    panel_texts = data.get("panel_texts") or []

    if not pages:
        return jsonify({"ok": False, "error": "Thiếu danh sách pages."}), 400

    panels = []
    if mode == "manual" and panel_texts:
        # Pair pages with manual texts (truncate longer side).
        for i, url in enumerate(pages):
            t = ""
            if i < len(panel_texts):
                t = str(panel_texts[i] or "").strip()
            panels.append({"image_url": url, "text": t})
    else:
        # Even split — segment text into N pieces by sentence boundaries.
        text = normalize_text(text)
        if not text:
            for url in pages:
                panels.append({"image_url": url, "text": ""})
        else:
            from core.story_writer import split_sentences
            sents = split_sentences(text) or [text]
            n = len(pages)
            per = max(1, len(sents) // n)
            chunks: list[str] = []
            cursor = 0
            for i in range(n):
                if i == n - 1:
                    chunk = " ".join(sents[cursor:])
                else:
                    chunk = " ".join(sents[cursor: cursor + per])
                    cursor += per
                chunks.append(chunk.strip())
            for url, chunk in zip(pages, chunks):
                panels.append({"image_url": url, "text": chunk})

    # Optionally translate the whole script in one shot for consistency.
    if data.get("translate"):
        try:
            from utils.translation import translate_texts
            cfg = load_cfg() or {}
            tr_cfg = dict(cfg.get("translation") or {})
            target_lang = (data.get("target_lang") or "vi")
            provider = (data.get("provider") or "auto")
            texts = [p["text"] for p in panels]
            translated, _ = translate_texts(texts, tr_cfg, provider, target_lang=target_lang)
            for p, t in zip(panels, translated):
                if t and t.strip():
                    p["text"] = t.strip()
        except Exception:
            # Non-fatal — keep original texts on failure
            pass

    return jsonify({
        "ok": True,
        "panel_count": len(panels),
        "panels": panels,
    })


# ── Render manga → video (background job) ──────────────────────────────────
@bp.route("/api/story/manga/render", methods=["POST"])
def manga_render():
    """Kick off a background MP4 render from panels + narration.

    Body:
        {
          "panels":  [{"image_url": "...", "text": "..."}, ...],
          "title":   "Chương 1",
          "preset":  "shorts" | "youtube" | "square",
          "subtitle_format": "ass" | "srt",
          "burn_subtitles": true,
          "tts_engine": "edge-tts",
          "tts_voice": "vi-VN-HoaiMyNeural",
          "tts_rate":  "+0%",
          "target_lang": "vi",
          "bgm_url": "",
          "bgm_volume": 0.1,
          "fps": 30,
          "zoom": true
        }
    """
    from core.manga_video import MangaRenderRequest, PanelInput, render_async

    cfg = load_cfg() or {}
    data = request.get_json(silent=True) or {}
    raw_panels = data.get("panels") or []
    if not raw_panels:
        return jsonify({"ok": False, "error": "Thiếu danh sách panels."}), 400

    panels = []
    for p in raw_panels:
        url = (p.get("image_url") or p.get("url") or "").strip()
        if not url:
            continue
        panels.append(PanelInput(
            image_url=url,
            text=(p.get("text") or "").strip(),
        ))
    if not panels:
        return jsonify({"ok": False, "error": "Không có panel hợp lệ."}), 400

    # Resolution preset
    preset = (data.get("preset") or "shorts").lower()
    if preset == "shorts" or preset == "tiktok":
        res_w, res_h = 1080, 1920
    elif preset == "square":
        res_w = res_h = 1080
    else:
        res_w, res_h = 1920, 1080

    # Honor explicit width/height when provided
    if data.get("width"):
        res_w = int(data["width"])
    if data.get("height"):
        res_h = int(data["height"])

    proxy = ""
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg) or ""
    except Exception:
        proxy = ""

    req = MangaRenderRequest(
        panels=panels,
        title=(data.get("title") or "manga_chapter").strip(),
        width=res_w,
        height=res_h,
        fps=int(data.get("fps") or 30),
        subtitle_format=(data.get("subtitle_format") or "ass").lower(),
        burn_subtitles=bool(data.get("burn_subtitles", True)),
        target_lang=(data.get("target_lang") or "vi"),
        tts_engine=(data.get("tts_engine") or "edge-tts"),
        tts_voice=(data.get("tts_voice") or "vi-VN-HoaiMyNeural"),
        tts_rate=(data.get("tts_rate") or "+0%"),
        tts_pitch=(data.get("tts_pitch") or "+0Hz"),
        fpt_api_key=(
            os.getenv("FPT_TTS_API_KEY")
            or (cfg.get("video_process") or {}).get("fpt_api_key")
            or ""
        ).strip(),
        fpt_speed=int(data.get("fpt_speed") or 0),
        min_panel_sec=float(data.get("min_panel_sec") or 2.0),
        inter_panel_pause_sec=float(data.get("inter_panel_pause_sec") or 0.25),
        intro_sec=float(data.get("intro_sec") or 0.8),
        outro_sec=float(data.get("outro_sec") or 1.2),
        zoom=bool(data.get("zoom", True)),
        bgm_url=(data.get("bgm_url") or "").strip(),
        bgm_volume=float(data.get("bgm_volume") or 0.10),
        title_text=(data.get("title_text") or data.get("title") or "").strip(),
        title_bar_color=(data.get("title_bar_color") or "#1A73E8"),
        font_name=(data.get("font_name") or "Arial"),
        font_size=int(data.get("font_size") or 48),
        font_color=(data.get("font_color") or "#FFFFFF"),
        outline_color=(data.get("outline_color") or "#000000"),
        output_dir=_manga_output_dir(cfg),
        output_name=(data.get("output_name") or "").strip(),
        proxy_url=proxy,
    )
    try:
        job_id = render_async(req)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@bp.route("/api/story/manga/render_status", methods=["GET"])
def manga_render_status():
    from core.manga_video import get_job_manager

    jid = (request.args.get("job_id") or "").strip()
    if not jid:
        return jsonify({"ok": False, "error": "Thiếu job_id."}), 400
    job = get_job_manager().get(jid)
    if not job:
        return jsonify({"ok": False, "error": "Job không tồn tại."}), 404

    def _rel(p: str) -> str:
        if not p:
            return ""
        try:
            pp = Path(p)
            if str(pp).startswith(str(ROOT)):
                return str(pp.relative_to(ROOT)).replace("\\", "/")
        except Exception:
            pass
        return p

    return jsonify({
        "ok": True,
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "output_video": job.output_video,
        "output_video_rel": _rel(job.output_video),
        "output_srt": job.output_srt,
        "output_srt_rel": _rel(job.output_srt),
        "output_ass": job.output_ass,
        "output_ass_rel": _rel(job.output_ass),
        "started_at": int(job.started_at),
        "finished_at": int(job.finished_at),
    })


@bp.route("/api/story/manga/render_video", methods=["GET"])
def manga_render_video():
    """Stream / download a rendered manga MP4 (or its sidecar subtitle).

    Restricted to files inside the configured manga output dir.
    """
    name = (request.args.get("name") or "").strip()
    kind = (request.args.get("kind") or "video").lower()  # video|srt|ass
    download = request.args.get("download") in ("1", "true", "yes")
    if not name:
        return abort(400)
    out_dir = _manga_output_dir(load_cfg() or {})
    try:
        target = safe_join(out_dir, name)
    except ValueError:
        return abort(403)
    if not target.exists() or not target.is_file():
        return abort(404)
    mt_map = {
        "video": "video/mp4",
        "srt": "application/x-subrip",
        "ass": "text/plain",
    }
    return send_file(
        str(target),
        mimetype=mt_map.get(kind, "application/octet-stream"),
        as_attachment=download,
        download_name=target.name,
    )


# ── TTS engines/voices catalogue (shared shape with /api/movie/voices) ─────
@bp.route("/api/story/voices", methods=["GET"])
def story_voices():
    engines = [
        {
            "id": "edge-tts",
            "label": "Edge TTS (Microsoft, miễn phí)",
            "default": "vi-VN-HoaiMyNeural",
            "voices": {
                "vi": [
                    ("vi-VN-HoaiMyNeural", "Hoài My (nữ, miền Bắc)"),
                    ("vi-VN-NamMinhNeural", "Nam Minh (nam, miền Bắc)"),
                ],
                "en": [
                    ("en-US-JennyNeural", "Jenny (female, US)"),
                    ("en-US-AriaNeural", "Aria (female, US)"),
                    ("en-US-GuyNeural", "Guy (male, US)"),
                    ("en-GB-SoniaNeural", "Sonia (female, UK)"),
                ],
                "ja": [
                    ("ja-JP-NanamiNeural", "Nanami (女)"),
                    ("ja-JP-KeitaNeural", "Keita (男)"),
                ],
                "ko": [
                    ("ko-KR-SunHiNeural", "SunHi (여)"),
                    ("ko-KR-InJoonNeural", "InJoon (남)"),
                ],
                "zh": [
                    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao (女, 简体)"),
                    ("zh-CN-YunxiNeural", "Yunxi (男, 简体)"),
                ],
                "th": [
                    ("th-TH-PremwadeeNeural", "Premwadee (หญิง)"),
                ],
            },
        },
        {
            "id": "fpt-ai",
            "label": "FPT AI TTS (cần API key, chỉ tiếng Việt)",
            "default": "banmai",
            "voices": {
                "vi": [
                    ("banmai", "Ban Mai (FPT — nữ, miền Bắc)"),
                    ("thuminh", "Thu Minh (FPT — nữ, miền Bắc)"),
                    ("leminh", "Le Minh (FPT — nam, miền Bắc)"),
                    ("linhsan", "Linh San (FPT — nữ, miền Nam)"),
                    ("giahuy", "Gia Huy (FPT — nam, miền Nam)"),
                    ("lannhi", "Lan Nhi (FPT — nữ, miền Nam)"),
                ],
            },
        },
        {
            "id": "gtts",
            "label": "Google gTTS (đơn giản, dự phòng)",
            "default": "vi",
            "voices": {
                "vi": [("vi", "Tiếng Việt mặc định")],
                "en": [("en", "English (default)")],
                "ja": [("ja", "日本語 (default)")],
                "ko": [("ko", "한국어 (default)")],
                "zh": [("zh", "中文 (default)")],
            },
        },
    ]
    return jsonify({"ok": True, "engines": engines})


# ══════════════════════════════════════════════════════════════════════════════
# Smart chapter-URL extractor — paste any chapter URL → get image list
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/manga/extract_chapter", methods=["POST"])
def manga_extract_chapter():
    """Extract image URLs from a chapter page on common manga sites.

    Body::
        { "url": "https://www.nettruyenvio.com/truyen-tranh/.../chuong-1/..." }
    """
    from core.manga_extractors import extract_chapter_images, ExtractError, SITES

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({
            "ok": False,
            "error": "Thiếu URL chương.",
            "supported_sites": [s.label for s in SITES] + ["Generic (fallback)"],
        }), 400
    try:
        result = extract_chapter_images(url, proxy_url=_proxy_url() or None)
        return jsonify({"ok": True, **result})
    except ExtractError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/extract_sites", methods=["GET"])
def manga_extract_sites():
    """List sites with dedicated extractors (UI hint)."""
    from core.manga_extractors import SITES
    return jsonify({
        "ok": True,
        "sites": [
            {"id": s.id, "label": s.label, "hosts": list(s.host_substrings)}
            for s in SITES
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# NetTruyen catalog (search + manga details + chapter list + chapter pages)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/nettruyen/search", methods=["POST", "GET"])
def nettruyen_search():
    from core import nettruyen_client as nt

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400
    page = max(1, int(data.get("page") or 1))
    base_url = (data.get("base_url") or "").strip() or None

    try:
        items = nt.search(
            keyword,
            base_url=base_url,
            proxy_url=_proxy_url() or None,
            page=page,
        )
        return jsonify({
            "ok": True,
            "items": [m.to_dict() for m in items],
            "count": len(items),
            "page": page,
            "source": "nettruyen",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/nettruyen/details", methods=["POST", "GET"])
def nettruyen_details():
    from core import nettruyen_client as nt

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_url = (data.get("manga_id") or data.get("id") or data.get("url") or "").strip()
    if not manga_url:
        return jsonify({"ok": False, "error": "Thiếu manga_id (URL)."}), 400

    try:
        info = nt.get_manga(manga_url, proxy_url=_proxy_url() or None)
        chapters = list(getattr(info, "_chapters", []) or [])
        return jsonify({
            "ok": True,
            "manga": info.to_dict(),
            "chapters": [c.to_dict() for c in chapters],
            "chapter_count": len(chapters),
            "source": "nettruyen",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/nettruyen/chapter_pages", methods=["POST", "GET"])
def nettruyen_chapter_pages():
    """Resolve image URLs for a chapter (delegates to extractors)."""
    from core.manga_extractors import extract_chapter_images, ExtractError

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_url = (data.get("chapter_id") or data.get("id") or data.get("url") or "").strip()
    if not chapter_url:
        return jsonify({"ok": False, "error": "Thiếu chapter URL."}), 400
    try:
        result = extract_chapter_images(chapter_url, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "chapter_id": chapter_url,
            "page_count": result["page_count"],
            "pages": result["pages"],
            "title": result.get("title", ""),
            "source": "nettruyen",
        })
    except ExtractError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# Vietnamese manga sites — search → chapters → pages (NetTruyen / TruyenQQ / ...)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/vn/sources", methods=["GET"])
def vn_sources():
    from core.vn_manga_sources import SOURCES
    return jsonify({
        "ok": True,
        "sources": [
            {"id": sid, "label": cls.label, "base": cls.DEFAULT_BASE}
            for sid, cls in SOURCES.items()
        ],
    })


@bp.route("/api/story/vn/search", methods=["POST", "GET"])
def vn_search():
    from core.vn_manga_sources import SOURCES, search_combined, get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khóa."}), 400

    source = (data.get("source") or "all").strip().lower()
    limit = max(1, min(50, int(data.get("limit") or 12)))
    proxy = _proxy_url() or None

    try:
        if source == "all":
            items = search_combined(keyword, limit=limit, proxy_url=proxy)
        else:
            if source not in SOURCES:
                return jsonify({"ok": False, "error": f"Nguồn không hỗ trợ: {source}"}), 400
            src = get_source(source, proxy_url=proxy)
            items = [m.to_dict() for m in src.search(keyword, limit=limit)]
        return jsonify({"ok": True, "items": items, "count": len(items), "source": source})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/details", methods=["POST", "GET"])
def vn_details():
    from core.vn_manga_sources import get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    source = (data.get("source") or "").strip().lower()
    target = (data.get("url") or data.get("slug") or data.get("id") or "").strip()
    if not source or not target:
        return jsonify({"ok": False, "error": "Thiếu source / url."}), 400
    try:
        src = get_source(source, proxy_url=_proxy_url() or None)
        info = src.details(target)
        return jsonify({"ok": True, "manga": info.to_dict()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/chapters", methods=["POST", "GET"])
def vn_chapters():
    from core.vn_manga_sources import get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    source = (data.get("source") or "").strip().lower()
    target = (data.get("url") or data.get("slug") or data.get("id") or "").strip()
    if not source or not target:
        return jsonify({"ok": False, "error": "Thiếu source / url."}), 400
    order_dir = (data.get("order_dir") or "asc").lower()
    try:
        src = get_source(source, proxy_url=_proxy_url() or None)
        chapters = src.chapters(target)
        if order_dir == "desc":
            chapters = list(reversed(chapters))
        return jsonify({
            "ok": True,
            "chapters": [c.to_dict() for c in chapters],
            "count": len(chapters),
            "source": source,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/chapter_pages", methods=["POST", "GET"])
def vn_chapter_pages():
    from core.vn_manga_sources import chapter_pages
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("url") or data.get("id") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu URL chương."}), 400
    try:
        result = chapter_pages(url, proxy_url=_proxy_url() or None)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# Multi-source search — query NetTruyen + TruyenQQ + BlogTruyen + Comick +
# Bato.to + MangaDex in parallel and return a merged, deduped result set.
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/search_all", methods=["POST", "GET"])
def story_search_all():
    """One-shot search across all manga sources (VN + international)."""
    import concurrent.futures as _cf

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400

    raw_sources = data.get("sources")
    if isinstance(raw_sources, str):
        sources = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, list):
        sources = [str(s).strip() for s in raw_sources if str(s).strip()]
    else:
        sources = ["nettruyen", "truyenqq", "blogtruyen",
                   "comick", "bato", "mangadex"]

    limit = max(1, min(30, int(data.get("limit_per_source") or 12)))
    proxy = _proxy_url() or None

    def _wrap_err(label: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"_error": f"{label}: {str(e)[:120]}"}

    def _search_vn(source_id: str):
        from core.vn_manga_sources import get_source
        src = get_source(source_id, proxy_url=proxy)
        return [m.to_dict() for m in src.search(keyword, limit=limit)]

    def _search_nt():
        try:
            from core import nettruyen_client as nt
            items = nt.search(keyword, proxy_url=proxy)[:limit]
            out = []
            for m in items:
                d = m.to_dict()
                d["source"] = "nettruyen"
                d["url"] = d.get("id") or ""
                out.append(d)
            return out
        except Exception:
            return _search_vn("nettruyen")

    def _search_md():
        from core.mangadex_client import MangaDexClient
        client = MangaDexClient(proxy_url=proxy)
        items = client.search_manga(
            keyword,
            limit=limit,
            translated_languages=("vi", "en"),
            content_ratings=("safe", "suggestive", "erotica"),
        )
        return [{**m.to_dict(), "source": "mangadex", "url": ""} for m in items]

    def _search_comick():
        from core import comick_client as cc
        items = cc.search(keyword, limit=limit, proxy_url=proxy)
        return [{**m.to_dict(), "source": "comick", "url": ""} for m in items]

    def _search_bato():
        from core import batoto_client as bc
        items = bc.search(keyword, limit=limit, proxy_url=proxy)
        return [m.to_dict() for m in items]

    jobs: dict = {}
    with _cf.ThreadPoolExecutor(max_workers=6) as pool:
        for src in sources:
            if src == "nettruyen":
                jobs[src] = pool.submit(_wrap_err, "nettruyen", _search_nt)
            elif src == "mangadex":
                jobs[src] = pool.submit(_wrap_err, "mangadex", _search_md)
            elif src == "comick":
                jobs[src] = pool.submit(_wrap_err, "comick", _search_comick)
            elif src == "bato":
                jobs[src] = pool.submit(_wrap_err, "bato", _search_bato)
            elif src in ("truyenqq", "blogtruyen"):
                jobs[src] = pool.submit(_wrap_err, src, _search_vn, src)

        per_source: dict = {}
        errors: list = []
        for src, fut in jobs.items():
            try:
                res = fut.result(timeout=25)
            except Exception as e:
                res = {"_error": f"{src}: {str(e)[:120]}"}
            if isinstance(res, dict) and "_error" in res:
                errors.append(res["_error"])
                per_source[src] = []
            else:
                per_source[src] = res or []

    # Interleave per-source results so all sources appear early instead of
    # being grouped by provider (better UX when scanning the result grid).
    merged: list = []
    seen = set()
    cursor = 0
    while True:
        added = False
        for src, items in per_source.items():
            if cursor < len(items):
                it = items[cursor]
                key = (src, it.get("id") or it.get("url") or it.get("title") or "")
                if key not in seen:
                    seen.add(key)
                    it.setdefault("source", src)
                    merged.append(it)
                added = True
        if not added:
            break
        cursor += 1

    return jsonify({
        "ok": True,
        "items": merged,
        "count": len(merged),
        "per_source": {k: len(v) for k, v in per_source.items()},
        "errors": errors,
    })


# ── Bato.to dispatcher (called from chapter selection in the UI) ───────────
@bp.route("/api/story/bato/details", methods=["POST", "GET"])
def bato_details():
    from core import batoto_client as bc

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("manga_id") or data.get("id") or data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu manga URL."}), 400
    try:
        info = bc.get_manga(url, proxy_url=_proxy_url() or None)
        chapters = list(getattr(info, "_chapters", []) or [])
        return jsonify({
            "ok": True,
            "manga": info.to_dict(),
            "chapters": [c.to_dict() for c in chapters],
            "chapter_count": len(chapters),
            "source": "bato",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/bato/chapter_pages", methods=["POST", "GET"])
def bato_chapter_pages():
    from core import batoto_client as bc

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("chapter_id") or data.get("id") or data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu chapter URL."}), 400
    try:
        pages = bc.get_chapter_pages(url, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "chapter_id": url,
            "page_count": len(pages),
            "pages": pages,
            "source": "bato",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# MangaPlus integration — extract chapter pages from MangaDex external_url
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/mangaplus/chapter_pages", methods=["POST", "GET"])
def mangaplus_chapter_pages():
    """Resolve a MangaPlus chapter (from a viewer URL or numeric id) into
    decoded page URLs that the browser can render via the image proxy.
    """
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    url_in = (data.get("url") or "").strip()
    if not chapter_id and url_in:
        chapter_id = mp.chapter_id_from_url(url_in) or ""
    if not chapter_id:
        return jsonify({
            "ok": False,
            "error": "Thiếu chapter_id hoặc URL MangaPlus.",
        }), 400

    quality = (data.get("quality") or "high").strip().lower()
    if quality not in ("low", "high", "super_high"):
        quality = "high"

    try:
        pairs = mp.fetch_chapter_pages(
            chapter_id, quality=quality, proxy_url=_proxy_url() or None,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502

    # Return same-origin URLs so the browser doesn't have to deal with
    # CORS or the per-image XOR key. The proxy below does the decrypt.
    pages = []
    for img, key in pairs:
        proxied = (
            "/api/story/mangaplus/image?url=" + urllib.parse.quote(img, safe="")
            + "&key=" + urllib.parse.quote(key or "", safe="")
        )
        pages.append(proxied)

    return jsonify({
        "ok": True,
        "chapter_id": chapter_id,
        "page_count": len(pages),
        "pages": pages,
        "source": "mangaplus",
    })


@bp.route("/api/story/mangaplus/image", methods=["GET"])
def mangaplus_image():
    """Fetch an encrypted MangaPlus image, XOR-decrypt it, stream JPEG."""
    from flask import Response
    from core import mangaplus_client as mp

    image_url = (request.args.get("url") or "").strip()
    key = (request.args.get("key") or "").strip()
    if not image_url:
        return abort(400)
    if "tokyo-cdn.com" not in image_url and "mangaplus" not in image_url:
        return abort(403)
    try:
        data = mp.fetch_decrypted_image(image_url, key, proxy_url=_proxy_url() or None)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 502
    return Response(
        data,
        mimetype="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Zip-download all panels (image bundle for "Tải ảnh về máy") ────────────
@bp.route("/api/story/manga/download_zip", methods=["POST"])
def manga_download_zip():
    """Stream a ZIP containing every panel image. Used when the user wants
    a local copy instead of just the rendered MP4.

    Body::
        {
          "title": "One Piece — Chapter 1",
          "pages": ["https://...", "/api/story/mangaplus/image?...", ...]
        }
    """
    import io
    import re as _re
    import zipfile
    import urllib.parse as _up
    import urllib.request as _ur

    data = request.get_json(silent=True) or {}
    pages = data.get("pages") or []
    title = (data.get("title") or "manga_chapter").strip()
    if not pages:
        return jsonify({"ok": False, "error": "Thiếu pages."}), 400

    safe_title = _re.sub(r"[\\/:*?\"<>|]", "_", title).strip(" .") or "manga_chapter"

    # Build ZIP fully in memory (chapters are typically <50 MB)
    buf = io.BytesIO()
    proxy = _proxy_url() or ""
    handlers: list = []
    if proxy:
        scheme = proxy.split("://", 1)[0]
        handlers.append(_ur.ProxyHandler({scheme: proxy}))
    opener = _ur.build_opener(*handlers) if handlers else _ur.build_opener()

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for idx, raw_url in enumerate(pages, start=1):
            try:
                # Same-origin /api URLs need to hit the local Flask app.
                if raw_url.startswith("/"):
                    target_url = request.host_url.rstrip("/") + raw_url
                else:
                    target_url = raw_url
                req = _ur.Request(target_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DuyTrisManga/1.0)",
                    "Referer": request.host_url,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                })
                with opener.open(req, timeout=30) as resp:
                    blob = resp.read()
                    ctype = resp.headers.get("Content-Type", "image/jpeg")
            except Exception as e:
                # Add a placeholder text file so the user knows which page failed
                zf.writestr(f"page_{idx:03d}.error.txt", str(e)[:300])
                continue
            # Pick an extension from the content-type
            ext = ".jpg"
            if "png" in ctype: ext = ".png"
            elif "webp" in ctype: ext = ".webp"
            elif "avif" in ctype: ext = ".avif"
            zf.writestr(f"{safe_title}/page_{idx:03d}{ext}", blob)

    buf.seek(0)
    from flask import send_file
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_title}.zip",
    )


# ══════════════════════════════════════════════════════════════════════════════
# MangaPlus catalog (search titles + list chapters) — single-source mode
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/mangaplus/search", methods=["POST", "GET"])
def mangaplus_search():
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400
    limit = max(1, min(50, int(data.get("limit") or 30)))
    try:
        items = mp.search_titles(keyword, limit=limit, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "items": [{**t, "source": "mangaplus"} for t in items],
            "count": len(items),
            "source": "mangaplus",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/mangaplus/details", methods=["POST", "GET"])
def mangaplus_details():
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    title_id = (data.get("manga_id") or data.get("id") or data.get("title_id") or "").strip()
    if not title_id:
        return jsonify({"ok": False, "error": "Thiếu title_id."}), 400
    try:
        res = mp.list_chapters(title_id, proxy_url=_proxy_url() or None)
        manga = {**(res.get("title") or {}), "source": "mangaplus"}
        chapters = []
        for c in (res.get("chapters") or []):
            chapters.append({
                "id": c["id"],
                "chapter": c.get("chapter") or c.get("raw_label") or "",
                "title": c.get("title") or "",
                "language": (manga.get("language") or "ENGLISH"),
                "pages": 0,
                "publish_at": c.get("publish_at") or "",
                "scanlation_group": "MangaPlus",
                "external_url": "",
                "is_external": False,
                "thumbnail_url": c.get("thumbnail_url") or "",
            })
        return jsonify({
            "ok": True,
            "manga": manga,
            "chapters": chapters,
            "chapter_count": len(chapters),
            "languages": res.get("languages") or [],
            "paywalled_count": res.get("paywalled_count") or 0,
            "has_paywall": bool(res.get("has_paywall")),
            "source": "mangaplus",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/mangaplus/chapter_pages_id", methods=["POST", "GET"])
def mangaplus_chapter_pages_id():
    """Variant of /chapter_pages that takes a numeric chapter_id directly
    (no MangaDex external_url required)."""
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    if not chapter_id:
        return jsonify({"ok": False, "error": "Thiếu chapter_id."}), 400
    quality = (data.get("quality") or "high").strip().lower()
    if quality not in ("low", "high", "super_high"):
        quality = "high"
    try:
        pairs = mp.fetch_chapter_pages(
            chapter_id, quality=quality, proxy_url=_proxy_url() or None,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502
    pages = [
        "/api/story/mangaplus/image?url=" + urllib.parse.quote(img, safe="")
        + "&key=" + urllib.parse.quote(key or "", safe="")
        for img, key in pairs
    ]
    return jsonify({
        "ok": True,
        "chapter_id": chapter_id,
        "page_count": len(pages),
        "pages": pages,
        "source": "mangaplus",
    })

"""Movie review blueprint — TMDb search/details + LLM review-script generation."""
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from core.movie_review import (
    ReviewRequest,
    TMDbClient,
    TmdbCache,
    fetch_wikipedia_section,
    fetch_wikipedia_summary,
    generate_review,
    _call_llm,
    _try_parse_json,
)
from core.vn_movie_sources import (
    SOURCES as VN_SOURCES,
    VNMovieClient,
    cinema_latest,
    latest_combined,
)
from core_app import STATE_DIR, load_cfg

bp = Blueprint("movie", __name__)


def _vn_source(cfg: dict, source: str) -> VNMovieClient:
    """Build a VN movie client for the given source, honoring the proxy pool."""
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg)
    except Exception:
        proxy = None
    return VNMovieClient(source=source, timeout=20, proxy_url=proxy)


def _vsmov(cfg: dict) -> VNMovieClient:
    """Backward-compat alias used by existing /api/movie/vsmov/* routes."""
    return _vn_source(cfg, "vsmov")


def _cfg():
    return load_cfg() or {}


def _api_key(cfg: dict) -> str:
    return (
        os.getenv("TMDB_API_KEY")
        or (cfg.get("movie") or {}).get("tmdb_api_key")
        or ""
    ).strip()


def _read_token(cfg: dict) -> str:
    return (
        os.getenv("TMDB_READ_TOKEN")
        or (cfg.get("movie") or {}).get("tmdb_read_token")
        or ""
    ).strip()


def _client(cfg: dict, language: str = None) -> TMDbClient:
    return TMDbClient(
        api_key=_api_key(cfg),
        read_access_token=_read_token(cfg),
        language=(language or (cfg.get("movie") or {}).get("default_language") or "vi"),
    )


def _cache(cfg: dict) -> TmdbCache:
    ttl = int((cfg.get("movie") or {}).get("cache_ttl_hours") or 24)
    return TmdbCache(STATE_DIR / "tmdb_cache.json", ttl_hours=ttl)


@bp.route("/api/movie/status", methods=["GET"])
def movie_status():
    cfg = _cfg()
    return jsonify({
        "ok": True,
        "configured": bool(_api_key(cfg) or _read_token(cfg)),
        "auth_method": "v4_bearer" if _read_token(cfg) else ("v3_api_key" if _api_key(cfg) else "none"),
        "language": (cfg.get("movie") or {}).get("default_language", "vi"),
        "vsmov_enabled": True,
    })


# ── Multi-source helpers ─────────────────────────────────────────────────────
@bp.route("/api/movie/sources", methods=["GET"])
def movie_sources():
    """List available VN movie sources for the source dropdown."""
    return jsonify({
        "ok": True,
        "sources": [
            {"id": k, "label": v["label"], "base": v["base"]}
            for k, v in VN_SOURCES.items()
        ],
    })


@bp.route("/api/movie/latest", methods=["GET"])
def movie_latest_combined():
    """Aggregated 'mới cập nhật' across multiple sources (deduped, sorted)."""
    cfg = _cfg()
    src_param = (request.args.get("source") or "all").strip().lower()
    per = int(request.args.get("per_source") or 12)
    min_year = request.args.get("min_year")
    try:
        min_year_int = int(min_year) if min_year else None
    except (TypeError, ValueError):
        min_year_int = None
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg)
    except Exception:
        proxy = None
    if src_param in ("all", ""):
        items = latest_combined(list(VN_SOURCES.keys()), per_source=per,
                                proxy_url=proxy, min_year=min_year_int)
    elif src_param in VN_SOURCES:
        items = _vn_source(cfg, src_param).latest()
        if min_year_int:
            items = [it for it in items if (it.get("year") or 0) >= min_year_int]
    else:
        return jsonify({"ok": False, "error": f"Unknown source: {src_param}"}), 400
    return jsonify({"ok": True, "items": items, "source": src_param})


def _movie_cache(cfg: dict, *, ttl_hours: int = 24) -> TmdbCache:
    """Disk cache for AI enrichments + cinema feeds. Reuses TmdbCache shape."""
    return TmdbCache(STATE_DIR / "movie_cache.json", ttl_hours=ttl_hours)


@bp.route("/api/movie/cinema", methods=["GET"])
def movie_cinema_latest():
    """Phim mới chiếu rạp / mới ra mắt — ưu tiên cao nhất.

    Sweep `pages` trang đầu của mỗi nguồn, lọc theo năm gần (mặc định: năm
    hiện tại & năm trước), dedupe + sort theo (chieurap, year, modified).
    Cache disk 1 giờ — invalidate bằng ?nocache=1.
    """
    import datetime as _dt
    cfg = _cfg()
    src_param = (request.args.get("source") or "all").strip().lower()
    limit = int(request.args.get("limit") or 24)
    pages = int(request.args.get("pages") or 3)
    min_year = request.args.get("min_year")
    nocache = request.args.get("nocache") in ("1", "true", "yes")
    try:
        min_year_int = int(min_year) if min_year else _dt.datetime.now().year - 1
    except (TypeError, ValueError):
        min_year_int = _dt.datetime.now().year - 1
    if src_param not in ("all", "") and src_param not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {src_param}"}), 400

    cache = _movie_cache(cfg, ttl_hours=1)  # short TTL — sources publish daily
    cache_key = f"cinema:{src_param}:{min_year_int}:{pages}:{limit}"
    if not nocache:
        cached = cache.get(cache_key)
        if cached:
            return jsonify({"ok": True, "items": cached["items"],
                            "source": src_param, "min_year": min_year_int,
                            "pages_scanned": pages, "cached": True})

    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg)
    except Exception:
        proxy = None
    sources = list(VN_SOURCES.keys()) if src_param in ("all", "") else [src_param]
    items = cinema_latest(sources, max_pages=pages, proxy_url=proxy,
                          min_year=min_year_int, limit=limit)
    cache.set(cache_key, {"items": items})
    return jsonify({
        "ok": True, "items": items, "source": src_param,
        "min_year": min_year_int, "pages_scanned": pages, "cached": False,
    })


# ── VSMOV (Vietnamese movie source) ──────────────────────────────────────────
# Existing endpoints + generic ones that accept ?source=vsmov|ophim|kkphim
@bp.route("/api/movie/vsmov/latest", methods=["GET"])
@bp.route("/api/movie/source/<source>/latest", methods=["GET"])
def vsmov_latest(source: str = "vsmov"):
    if source not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400
    page = int(request.args.get("page") or 1)
    cfg = _cfg()
    items = _vn_source(cfg, source).latest(page=page)
    return jsonify({"ok": True, "items": items, "source": source, "page": page})


@bp.route("/api/movie/vsmov/search", methods=["POST", "GET"])
@bp.route("/api/movie/source/<source>/search", methods=["POST", "GET"])
def vsmov_search(source: str = "vsmov"):
    if source not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400
    cfg = _cfg()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        keyword = (data.get("keyword") or data.get("query") or "").strip()
        limit = int(data.get("limit") or 20)
        page = int(data.get("page") or 1)
    else:
        keyword = (request.args.get("keyword") or request.args.get("query") or "").strip()
        limit = int(request.args.get("limit") or 20)
        page = int(request.args.get("page") or 1)
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400
    items = _vn_source(cfg, source).search(keyword, limit=limit, page=page)
    return jsonify({"ok": True, "items": items, "source": source})


@bp.route("/api/movie/vsmov/details", methods=["POST", "GET"])
@bp.route("/api/movie/source/<source>/details", methods=["POST", "GET"])
def vsmov_details(source: str = "vsmov"):
    if source not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400
    cfg = _cfg()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        slug = (data.get("slug") or data.get("id") or "").strip()
    else:
        slug = (request.args.get("slug") or request.args.get("id") or "").strip()
    if not slug:
        return jsonify({"ok": False, "error": "Thiếu slug."}), 400
    info = _vn_source(cfg, source).details(slug)
    if not info:
        return jsonify({"ok": False, "error": "Không tải được chi tiết phim."}), 404
    return jsonify({"ok": True, "info": info, "source": source})


@bp.route("/api/movie/vsmov/filters", methods=["GET"])
@bp.route("/api/movie/source/<source>/filters", methods=["GET"])
def vsmov_filters(source: str = "vsmov"):
    if source not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400
    cfg = _cfg()
    cache = _cache(cfg)
    out = {}
    for key in ("categories", "countries", "years"):
        cache_key = f"{source}_{key}"
        cached = cache.get(cache_key)
        if cached:
            out[key] = cached
            continue
        items = getattr(_vn_source(cfg, source), key)()
        cache.set(cache_key, items)
        out[key] = items
    return jsonify({"ok": True, "source": source, **out})


@bp.route("/api/movie/vsmov/browse", methods=["POST", "GET"])
@bp.route("/api/movie/source/<source>/browse", methods=["POST", "GET"])
def vsmov_browse(source: str = "vsmov"):
    if source not in VN_SOURCES:
        return jsonify({"ok": False, "error": f"Unknown source: {source}"}), 400
    cfg = _cfg()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    res = _vn_source(cfg, source).browse(
        category=(data.get("category") or "").strip(),
        country=(data.get("country") or "").strip(),
        year=(data.get("year") or "").strip(),
        page=int(data.get("page") or 1),
        limit=int(data.get("limit") or 24),
        sort_field=(data.get("sort_field") or "modified.time"),
        sort_type=(data.get("sort_type") or "desc"),
    )
    return jsonify({"ok": True, "source": source, **res})


@bp.route("/api/movie/cache_status", methods=["GET"])
def movie_cache_status():
    """Quick stats on the disk cache."""
    import json as _j
    import os as _os
    p = STATE_DIR / "movie_cache.json"
    if not p.exists():
        return jsonify({"ok": True, "exists": False, "entries": 0, "bytes": 0})
    try:
        data = _j.loads(p.read_text(encoding="utf-8"))
        return jsonify({
            "ok": True,
            "exists": True,
            "entries": len(data),
            "bytes": p.stat().st_size,
            "ai_enrich": sum(1 for k in data if k.startswith("ai_enrich:")),
            "cinema": sum(1 for k in data if k.startswith("cinema:")),
        })
    except Exception:
        return jsonify({"ok": True, "exists": True, "entries": 0, "bytes": p.stat().st_size})


@bp.route("/api/movie/cache_clear", methods=["POST"])
def movie_cache_clear():
    """Wipe the movie cache (AI enrich + cinema feed)."""
    p = STATE_DIR / "movie_cache.json"
    scope = (request.get_json(silent=True) or {}).get("scope") or "all"
    if scope == "all":
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
        return jsonify({"ok": True, "scope": "all"})
    # Selective scope
    import json as _j
    if not p.exists():
        return jsonify({"ok": True, "scope": scope, "removed": 0})
    try:
        data = _j.loads(p.read_text(encoding="utf-8"))
        before = len(data)
        prefix = scope + ":"
        data = {k: v for k, v in data.items() if not k.startswith(prefix)}
        p.write_text(_j.dumps(data, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "scope": scope, "removed": before - len(data)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


# ── AI enrichment: generate plot/themes when overview is empty ──────────────
@bp.route("/api/movie/ai_enrich", methods=["POST"])
def movie_ai_enrich():
    """Use the configured LLM to write an overview/plot summary for a movie
    when no other source has it. Returns extra `overview`, `tagline`, and
    `themes` fields that can be merged into `info` before /review.
    """
    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    info = data.get("info") or {}
    if not info or not (info.get("title") or info.get("name")):
        return jsonify({"ok": False, "error": "Cần truyền `info` có ít nhất `title`."}), 400

    provider = (data.get("provider") or
                (cfg.get("movie") or {}).get("default_provider") or "auto")
    target_lang = (data.get("target_lang") or
                   (cfg.get("movie") or {}).get("default_language") or "vi")

    title = info.get("title") or info.get("name") or ""
    original = info.get("original_title") or info.get("original_name") or ""
    year = info.get("year") or (info.get("release_date") or "")[:4]
    director = ""
    for c in (info.get("credits") or {}).get("crew") or []:
        if c.get("job") == "Director" and c.get("name"):
            director = c["name"]
            break
    cast = ", ".join(c.get("name", "") for c in
                     (info.get("credits") or {}).get("cast") or [])[:300]
    genres = ", ".join(g.get("name", "") for g in (info.get("genres") or []))
    country = ", ".join(
        (c.get("name") if isinstance(c, dict) else str(c))
        for c in (info.get("country") or [])
    )

    # Cache: stable key from title + original + year + director
    nocache = bool(data.get("nocache"))
    cache = _movie_cache(cfg, ttl_hours=24 * 7)  # AI enrichments rarely change
    cache_key = f"ai_enrich:{provider}:{target_lang}:{title}|{original}|{year}|{director}".strip()
    if not nocache:
        cached = cache.get(cache_key)
        if cached:
            return jsonify({"ok": True, "cached": True, **cached})

    system = (
        "Bạn là chuyên gia điện ảnh đa ngôn ngữ. Khi nhận được tên phim + metadata, "
        "bạn tra cứu kiến thức của chính mình về bộ phim đó và viết tóm tắt khách quan, "
        "không spoil kết. Nếu thực sự không biết bộ phim này, trả về `unknown:true`."
    )
    user = (
        f"Phim: {title}{f' [{original}]' if original and original != title else ''}\n"
        f"Năm: {year or 'không rõ'}\n"
        f"Đạo diễn: {director or 'không rõ'}\n"
        f"Diễn viên: {cast or 'không rõ'}\n"
        f"Thể loại: {genres or 'không rõ'}\n"
        f"Quốc gia: {country or 'không rõ'}\n\n"
        f"Hãy viết bằng {target_lang.upper()} một JSON đúng dạng:\n"
        "{\n"
        '  "tagline": "<câu khẩu hiệu hoặc lời quảng cáo, 1 câu>",\n'
        '  "overview": "<giới thiệu nội dung 4–6 câu, không spoil>",\n'
        '  "plot": "<cốt truyện chi tiết hơn, 8–12 câu, không spoil cảnh kết>",\n'
        '  "themes": ["chủ đề 1", "chủ đề 2", "chủ đề 3"],\n'
        '  "audience": "đối tượng phù hợp",\n'
        '  "unknown": false\n'
        "}\n"
        "Nếu KHÔNG biết bộ phim này, trả `unknown:true` và để các trường khác rỗng. "
        "Tuyệt đối KHÔNG bịa thông tin sai."
    )

    raw = _call_llm(provider, cfg, system, user)
    parsed = _try_parse_json(raw) if raw else None
    if not parsed:
        return jsonify({"ok": False, "error": "LLM không trả về JSON hợp lệ — kiểm tra API key trong config.translation"}), 502
    if parsed.get("unknown"):
        return jsonify({
            "ok": False,
            "unknown": True,
            "error": "AI không có thông tin xác đáng về bộ phim này. Hãy thêm 'Ghi chú' thủ công khi tạo kịch bản.",
        }), 200
    out = {
        "overview": parsed.get("overview", "") or "",
        "tagline": parsed.get("tagline", "") or "",
        "plot": parsed.get("plot", "") or "",
        "themes": parsed.get("themes") or [],
        "audience": parsed.get("audience", "") or "",
    }
    cache.set(cache_key, out)
    return jsonify({"ok": True, "cached": False, **out})


@bp.route("/api/movie/search", methods=["POST"])
def movie_search():
    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "Thiếu query."}), 400
    kind = (data.get("kind") or "movie").lower()
    language = data.get("language") or None
    try:
        client = _client(cfg, language)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        if kind == "tv":
            res = client.search_tv(query, language=language)
        else:
            res = client.search(query, language=language,
                                include_adult=bool(data.get("include_adult")))
        items = []
        for r in (res.get("results") or [])[:20]:
            items.append({
                "id": r.get("id"),
                "kind": kind,
                "title": r.get("title") or r.get("name"),
                "original_title": r.get("original_title") or r.get("original_name"),
                "release_date": r.get("release_date") or r.get("first_air_date") or "",
                "vote_average": r.get("vote_average"),
                "overview": r.get("overview") or "",
                "poster_url": client.poster_url(r.get("poster_path") or "", "w342"),
                "backdrop_url": client.poster_url(r.get("backdrop_path") or "", "w780"),
            })
        return jsonify({"ok": True, "items": items, "total": res.get("total_results")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/movie/details", methods=["POST"])
def movie_details():
    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    tmdb_id = data.get("tmdb_id") or data.get("id")
    kind = (data.get("kind") or "movie").lower()
    if not tmdb_id:
        return jsonify({"ok": False, "error": "Thiếu tmdb_id."}), 400
    language = data.get("language") or None
    try:
        client = _client(cfg, language)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    cache = _cache(cfg)
    cache_key = f"{kind}:{tmdb_id}:{language or client.language}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify({"ok": True, "info": cached, "cached": True})
    try:
        info = client.details(int(tmdb_id), language=language, kind=kind)
        info["poster_url"] = client.poster_url(info.get("poster_path") or "", "w500")
        info["backdrop_url"] = client.poster_url(info.get("backdrop_path") or "", "w1280")
        cache.set(cache_key, info)
        return jsonify({"ok": True, "info": info, "cached": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/movie/enrich", methods=["POST"])
def movie_enrich():
    """Fetch supplementary content for a movie: backdrops/posters + Wikipedia.

    Frontend can call this after a user picks a movie, *before* generating
    the review, so the LLM has more context and the UI can show a gallery.
    """
    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    tmdb_id = data.get("tmdb_id") or data.get("id")
    kind = (data.get("kind") or "movie").lower()
    if not tmdb_id:
        return jsonify({"ok": False, "error": "Thiếu tmdb_id."}), 400
    language = data.get("language") or None
    image_limit = int(data.get("image_limit") or 24)
    try:
        client = _client(cfg, language)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    images, image_err = [], ""
    try:
        images = client.collect_image_urls(int(tmdb_id), kind=kind, limit=image_limit)
    except Exception as e:
        image_err = str(e)[:200]

    # Wikipedia: try VI first, then EN — fetch BOTH summary AND full plot section
    cache = _cache(cfg)
    wiki_key = f"wiki:{tmdb_id}:{language or client.language}"
    plot_key = f"plot:{tmdb_id}:{language or client.language}"
    wiki = cache.get(wiki_key)
    plot = cache.get(plot_key)
    if wiki is None or plot is None:
        title_for_wiki = data.get("title") or ""
        original_title = ""
        try:
            info_for_wiki = client.details(int(tmdb_id), language=language, kind=kind)
            if not title_for_wiki:
                title_for_wiki = info_for_wiki.get("title") or info_for_wiki.get("name") or ""
            original_title = info_for_wiki.get("original_title") or info_for_wiki.get("original_name") or ""
        except Exception:
            pass
        if wiki is None:
            wiki = ""
            for candidate in (original_title, title_for_wiki):
                if candidate and not wiki:
                    wiki = fetch_wikipedia_summary(candidate, lang=(language or client.language)) or ""
            if wiki:
                cache.set(wiki_key, wiki)
        if plot is None:
            plot_data = {"section_title": "", "text": "", "full_url": ""}
            for candidate in (original_title, title_for_wiki):
                if candidate and not plot_data.get("text"):
                    plot_data = fetch_wikipedia_section(candidate, lang=(language or client.language)) or plot_data
            plot = plot_data
            cache.set(plot_key, plot)

    return jsonify({
        "ok": True,
        "image_count": len(images),
        "images": images,
        "image_error": image_err,
        "wiki_extract": wiki or "",
        "wiki_chars": len(wiki or ""),
        "wiki_plot": (plot or {}).get("text", ""),
        "wiki_plot_section": (plot or {}).get("section_title", ""),
        "wiki_plot_url": (plot or {}).get("full_url", ""),
        "wiki_plot_chars": len((plot or {}).get("text", "")),
    })
def movie_trending():
    cfg = _cfg()
    period = (request.args.get("period") or "week").lower()
    try:
        client = _client(cfg)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    try:
        res = client.trending(period=period)
        items = []
        for r in (res.get("results") or [])[:30]:
            items.append({
                "id": r.get("id"),
                "title": r.get("title") or r.get("name"),
                "release_date": r.get("release_date") or r.get("first_air_date") or "",
                "vote_average": r.get("vote_average"),
                "overview": r.get("overview") or "",
                "poster_url": client.poster_url(r.get("poster_path") or "", "w342"),
            })
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/movie/review", methods=["POST"])
def movie_review():
    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    info = data.get("info") or None
    source = (data.get("source") or "").strip().lower()
    if not source and info:
        source = (info.get("source") or "").strip().lower()
    slug = (data.get("slug") or "").strip()
    tmdb_id = data.get("tmdb_id") or data.get("id")
    kind = (data.get("kind") or "movie").lower()
    template = (data.get("template") or
                (cfg.get("movie") or {}).get("default_template") or "cinematic")
    length_sec = int(data.get("length_sec") or 90)
    target_lang = data.get("target_lang") or (cfg.get("movie") or {}).get("default_language") or "vi"
    provider = data.get("provider") or (cfg.get("movie") or {}).get("default_provider") or "auto"
    extra_notes = data.get("extra_notes") or ""
    auto_enrich = bool(data.get("auto_enrich", True))
    image_limit = int(data.get("image_limit") or 24)

    # ── Source: VSMOV / OPhim / KKPhim ──
    if source in VN_SOURCES or (slug and not tmdb_id and not info):
        if not info and slug:
            chosen = source if source in VN_SOURCES else "vsmov"
            info = _vn_source(cfg, chosen).details(slug)
            if not info:
                return jsonify({"ok": False, "error": f"Không tải được chi tiết từ {chosen}."}), 502
    else:
        # ── Source: TMDb (default) ──
        try:
            client = _client(cfg, target_lang)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not info and tmdb_id:
            try:
                info = client.details(int(tmdb_id), language=target_lang, kind=kind)
            except Exception as e:
                return jsonify({"ok": False, "error": "Không tải được chi tiết phim: " + str(e)[:200]}), 502

    if not info:
        return jsonify({"ok": False, "error": "Cần cung cấp `info`, `slug` (VSMOV) hoặc `tmdb_id`."}), 400

    # Auto-enrich: fetch Wikipedia + plot + images if not already attached
    images = data.get("images") or []
    if auto_enrich:
        cache = _cache(cfg)
        if not info.get("wiki_extract") or not info.get("wiki_plot"):
            wiki_id = info.get("id") or info.get("slug") or tmdb_id
            wiki_key = f"wiki:{wiki_id}:{target_lang}"
            plot_key = f"plot:{wiki_id}:{target_lang}"
            wiki = cache.get(wiki_key)
            plot = cache.get(plot_key)
            candidates = [
                info.get("original_title") or info.get("original_name") or "",
                info.get("title") or info.get("name") or "",
            ]
            if wiki is None:
                wiki = ""
                for c in candidates:
                    if c and not wiki:
                        wiki = fetch_wikipedia_summary(c, lang=target_lang) or ""
                if wiki:
                    cache.set(wiki_key, wiki)
            if plot is None:
                plot = {"section_title": "", "text": "", "full_url": ""}
                for c in candidates:
                    if c and not plot.get("text"):
                        plot = fetch_wikipedia_section(c, lang=target_lang) or plot
                cache.set(plot_key, plot)
            if wiki:
                info["wiki_extract"] = wiki
            if (plot or {}).get("text"):
                info["wiki_plot"] = plot["text"]
                info["wiki_plot_section"] = plot.get("section_title", "")
                info["wiki_plot_url"] = plot.get("full_url", "")
        if not images:
            # Try TMDb-style image gallery first if we have a numeric tmdb id
            tmdb_int = None
            try:
                if info.get("tmdb_id"):
                    tmdb_int = int(info["tmdb_id"])
                elif info.get("id"):
                    tmdb_int = int(info["id"])
                elif tmdb_id:
                    tmdb_int = int(tmdb_id)
            except (TypeError, ValueError):
                tmdb_int = None

            if tmdb_int is not None and source not in VN_SOURCES:
                try:
                    images = client.collect_image_urls(tmdb_int, kind=kind, limit=image_limit)
                except Exception:
                    images = []
            elif tmdb_int is not None and source in VN_SOURCES:
                # VSMOV/OPhim item with tmdb_id — try TMDb stills if key set
                try:
                    if "client" not in locals():
                        client = _client(cfg, target_lang)
                    images = client.collect_image_urls(
                        tmdb_int,
                        kind=(info.get("tmdb_type") or "movie"),
                        limit=image_limit,
                    )
                except Exception:
                    images = []

            # Fallback: poster + thumb of the source itself
            if not images and source in VN_SOURCES:
                from core.vn_movie_sources import VNMovieClient as _VS
                images = _VS.collect_image_urls(info)

    req = ReviewRequest(
        info=info,
        template=template,
        length_sec=length_sec,
        target_lang=target_lang,
        provider=provider,
        extra_notes=extra_notes,
    )
    out = generate_review(req, cfg)
    out["images"] = images
    out["wiki_chars"] = len(info.get("wiki_extract") or "")
    out["wiki_plot_chars"] = len(info.get("wiki_plot") or "")
    out["wiki_plot_section"] = info.get("wiki_plot_section") or ""
    out["wiki_plot_url"] = info.get("wiki_plot_url") or ""
    return jsonify({"ok": True, "review": out})



# ── Video render ────────────────────────────────────────────────────────────
@bp.route("/api/movie/render", methods=["POST"])
def movie_render():
    """Kick off a background render job. Returns a job id for polling."""
    from core.movie_video import RenderRequest, render_async
    from core_app import ROOT

    cfg = _cfg()
    data = request.get_json(silent=True) or {}
    script = (data.get("script") or "").strip()
    images = data.get("images") or []
    if not script:
        return jsonify({"ok": False, "error": "Thiếu script."}), 400
    if not images:
        return jsonify({"ok": False, "error": "Thiếu images."}), 400

    out_dir_cfg = (cfg.get("movie") or {}).get("output_dir") or "./Downloaded/movie_videos"
    out_dir = Path(out_dir_cfg)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir

    res_w = int(data.get("width") or 1920)
    res_h = int(data.get("height") or 1080)
    # Quick presets
    preset = (data.get("preset") or "").lower()
    if preset == "shorts" or preset == "tiktok":
        res_w, res_h = 1080, 1920
    elif preset == "square":
        res_w = res_h = 1080
    elif preset == "youtube" or preset == "youtube_long":
        res_w, res_h = 1920, 1080

    req = RenderRequest(
        script=script,
        image_urls=images,
        title=(data.get("title") or "movie_review"),
        width=res_w, height=res_h,
        fps=int(data.get("fps") or 30),
        tts_engine=(data.get("tts_engine") or "edge-tts"),
        tts_voice=(data.get("tts_voice") or "vi-VN-HoaiMyNeural"),
        tts_lang=(data.get("tts_lang") or "vi"),
        tts_rate=(data.get("tts_rate") or "+0%"),
        fpt_api_key=(
            os.getenv("FPT_TTS_API_KEY")
            or (cfg.get("video_process") or {}).get("fpt_api_key")
            or ""
        ).strip(),
        fpt_speed=int(data.get("fpt_speed") or 0),
        bgm_url=(data.get("bgm_url") or "").strip(),
        bgm_volume=float(data.get("bgm_volume") or 0.12),
        crossfade_sec=float(data.get("crossfade_sec") or 0.6),
        intro_sec=float(data.get("intro_sec") or 1.5),
        outro_sec=float(data.get("outro_sec") or 1.8),
        zoom=bool(data.get("zoom", True)),
        output_dir=out_dir,
        output_name=(data.get("output_name") or ""),
    )
    try:
        job_id = render_async(req)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500
    return jsonify({"ok": True, "job_id": job_id})


@bp.route("/api/movie/render_status", methods=["GET"])
def movie_render_status():
    from core.movie_video import get_job_manager
    jid = request.args.get("job_id") or ""
    if not jid:
        return jsonify({"ok": False, "error": "Thiếu job_id."}), 400
    job = get_job_manager().get(jid)
    if not job:
        return jsonify({"ok": False, "error": "Job không tồn tại."}), 404

    out_rel = ""
    if job.output_path:
        try:
            from core_app import ROOT
            p = Path(job.output_path)
            if str(p).startswith(str(ROOT)):
                out_rel = str(p.relative_to(ROOT)).replace("\\", "/")
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "output_path": job.output_path,
        "output_rel": out_rel,
        "started_at": int(job.started_at),
        "finished_at": int(job.finished_at),
    })


@bp.route("/api/movie/voices", methods=["GET"])
def movie_voices():
    """Return TTS engines + voice presets, structured for the dropdown."""
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
                    ("en-GB-RyanNeural", "Ryan (male, UK)"),
                ],
                "zh": [
                    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao (女, 简体)"),
                    ("zh-CN-YunxiNeural", "Yunxi (男, 简体)"),
                ],
                "ja": [("ja-JP-NanamiNeural", "Nanami (女)"),
                       ("ja-JP-KeitaNeural", "Keita (男)")],
                "ko": [("ko-KR-SunHiNeural", "SunHi (여)"),
                       ("ko-KR-InJoonNeural", "InJoon (남)")],
                "th": [("th-TH-PremwadeeNeural", "Premwadee (หญิง)"),
                       ("th-TH-NiwatNeural", "Niwat (ชาย)")],
                "id": [("id-ID-GadisNeural", "Gadis (Wanita)"),
                       ("id-ID-ArdiNeural", "Ardi (Pria)")],
            },
        },
        {
            "id": "fpt-ai",
            "label": "FPT AI TTS (chỉ tiếng Việt — cần API key)",
            "default": "banmai",
            "voices": {
                "vi": [
                    ("banmai", "Ban Mai (FPT — nữ, miền Bắc)"),
                    ("thuminh", "Thu Minh (FPT — nữ, miền Bắc)"),
                    ("myan", "My An (FPT — nữ, miền Trung)"),
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
                "zh": [("zh", "中文 (default)")],
                "ja": [("ja", "日本語 (default)")],
                "ko": [("ko", "한국어 (default)")],
            },
        },
    ]
    return jsonify({"ok": True, "engines": engines})


@bp.route("/api/movie/image_proxy", methods=["GET"])
def movie_image_proxy():
    """Stream a TMDb image through the backend so the browser can save it.

    Only allows TMDb image hosts to prevent SSRF/abuse.
    """
    import urllib.parse as _up
    import urllib.request as _ur

    from flask import Response, abort

    url = (request.args.get("url") or "").strip()
    if not url:
        abort(400)
    parsed = _up.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        abort(400)
    allowed_hosts = (
        "image.tmdb.org",
        "vsmov.com", "img.vsmov.com",
        "ophim1.com", "ophim.cc", "ophim17.cc",
        "ophim.live", "img.ophim.live",
        "img.phimapi.com", "phimapi.com", "phimimg.com",
        "img.ophim1.com",
    )
    host = parsed.netloc.lower()
    if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        abort(403)
    try:
        req_h = _ur.Request(url, headers={"User-Agent": "DuyTris-MovieReview/1.0"})
        with _ur.urlopen(req_h, timeout=20) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
        filename = parsed.path.rsplit("/", 1)[-1] or "image.jpg"
        headers = {
            "Content-Type": ctype,
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="{filename}"',
        }
        if request.args.get("download"):
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return Response(data, headers=headers)
    except Exception:
        abort(502)


@bp.route("/api/movie/render_video", methods=["GET"])
def movie_render_video():
    """Stream a rendered MP4 from the configured output directory.

    Only allows files inside <ROOT>/<output_dir>. Used by the in-page <video>
    player so the browser can preview the result without an extra round-trip
    to the file-listing API.
    """
    from flask import abort, send_file

    from core_app import ROOT
    from utils.security import safe_filename, safe_join

    cfg = _cfg()
    out_dir_cfg = (cfg.get("movie") or {}).get("output_dir") or "./Downloaded/movie_videos"
    out_dir = Path(out_dir_cfg)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    name = safe_filename(request.args.get("name") or "")
    if not name:
        abort(400)
    try:
        target = safe_join(out_dir, name)
    except ValueError:
        abort(400)
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(str(target), mimetype="video/mp4",
                     as_attachment=bool(request.args.get("download")),
                     download_name=name)

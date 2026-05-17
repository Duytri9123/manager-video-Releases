"""
Vietnamese movie API sources — generalization of the VSMOV client.

These sites share the same Laravel/kkphim-style schema:
  • VSMOV    — https://vsmov.com    (smaller catalog, slower updates)
  • OPhim    — https://ophim1.com   (large, daily updates)
  • KKPhim   — https://kkphim.vip   (similar schema)
  • PhimAPI  — https://phimapi.com  (open public API)

All four expose:
  GET /danh-sach/phim-moi-cap-nhat?page=N
  GET /tim-kiem?keyword=...&limit=N
  GET /phim/<slug>
  GET /the-loai/<slug>?page=N
  GET /quoc-gia/<slug>?page=N
  GET /nam/<year>?page=N
  GET /the-loai      (list of categories)
  GET /quoc-gia      (list of countries)

Detail response: {status, msg, movie:{...}, episodes:[{server_name, server_data:[...]}]}
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


SOURCES = {
    "vsmov":  {"label": "VSMOV",  "base": "https://vsmov.com",   "api_prefix": "/api"},
    "ophim":  {"label": "OPhim",  "base": "https://ophim1.com",  "api_prefix": ""},
    "kkphim": {"label": "KKPhim", "base": "https://phimapi.com", "api_prefix": ""},
}


def _http_json(url: str, *, timeout: int = 20, headers: Optional[dict] = None,
               proxy_url: Optional[str] = None) -> dict:
    h = {
        "Accept": "application/json",
        "User-Agent": "DuyTris-MovieReview/1.0 (+toolvideo)",
        **(headers or {}),
    }
    if not proxy_url:
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")
    scheme = proxy_url.split("://", 1)[0]
    handler = urllib.request.ProxyHandler({scheme: proxy_url})
    opener = urllib.request.build_opener(handler)
    opener.addheaders = list(h.items())
    with opener.open(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


def _normalize_item(item: Dict[str, Any], *, source_id: str,
                    base_url: str, path_image: str = "") -> Dict[str, Any]:
    tmdb = item.get("tmdb") or {}
    rating = tmdb.get("vote_average")
    try:
        rating = float(rating) if rating not in (None, "", "null") else None
    except (TypeError, ValueError):
        rating = None

    poster = item.get("poster_url") or ""
    thumb = item.get("thumb_url") or poster
    # Some sources (OPhim) return only filenames in `poster_url` and provide a
    # `pathImage` alongside the items list. VSMOV embeds full URLs already.
    def _absolutize(u: str) -> str:
        if not u:
            return ""
        if u.startswith(("http://", "https://")):
            return u
        if path_image and not u.startswith("/"):
            return path_image.rstrip("/") + "/" + u.lstrip("/")
        return base_url.rstrip("/") + "/" + u.lstrip("/")

    poster = _absolutize(poster)
    thumb = _absolutize(thumb)

    return {
        "source": source_id,
        "id": item.get("slug"),
        "external_id": item.get("_id"),
        "title": item.get("name") or item.get("origin_name") or "",
        "original_title": item.get("origin_name") or "",
        "slug": item.get("slug") or "",
        "year": item.get("year"),
        "vote_average": rating,
        "poster_url": poster,
        "thumb_url": thumb,
        "tmdb_id": tmdb.get("id"),
        "tmdb_type": tmdb.get("type"),
        "imdb_id": (item.get("imdb") or {}).get("id"),
        "modified": (item.get("modified") or {}).get("time"),
        "overview": "",  # filled by details()
    }


class VNMovieClient:
    """Single client class that works against any of the kkphim-compatible APIs."""

    def __init__(self, source: str = "vsmov", *, timeout: int = 20,
                 proxy_url: Optional[str] = None):
        if source not in SOURCES:
            raise ValueError(f"Unknown source: {source}. Choose from {list(SOURCES)}")
        self.source = source
        cfg = SOURCES[source]
        self.base = cfg["base"]
        self.api_prefix = cfg["api_prefix"]
        self.label = cfg["label"]
        self.timeout = timeout
        self.proxy_url = (proxy_url or "").strip() or None

    # ── transport ──
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = self.base + self.api_prefix + path
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url += ("&" if "?" in url else "?") + qs
        return _http_json(url, timeout=self.timeout, proxy_url=self.proxy_url)

    # ── public API ──
    def latest(self, page: int = 1) -> List[Dict[str, Any]]:
        try:
            data = self._get("/danh-sach/phim-moi-cap-nhat", {"page": page})
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else []
        path_image = (data.get("pathImage") or "") if isinstance(data, dict) else ""
        return [_normalize_item(it, source_id=self.source, base_url=self.base,
                                path_image=path_image)
                for it in (items or [])]

    def search(self, keyword: str, *, limit: int = 20, page: int = 1) -> List[Dict[str, Any]]:
        if not keyword.strip():
            return []
        try:
            data = self._get("/tim-kiem", {
                "keyword": keyword.strip(), "limit": limit, "page": page,
            })
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else []
        path_image = (data.get("pathImage") or "") if isinstance(data, dict) else ""
        return [_normalize_item(it, source_id=self.source, base_url=self.base,
                                path_image=path_image)
                for it in (items or [])]

    def details(self, slug: str) -> Optional[Dict[str, Any]]:
        slug = (slug or "").strip()
        if not slug:
            return None
        try:
            data = self._get(f"/phim/{urllib.parse.quote(slug)}")
        except Exception:
            return None
        movie = (data or {}).get("movie") if isinstance(data, dict) else None
        if not movie:
            return None
        return self._to_review_info(movie, episodes=data.get("episodes") or [])

    def browse(self, *, category: str = "", country: str = "",
               year: str = "", page: int = 1, limit: int = 24,
               sort_field: str = "modified.time",
               sort_type: str = "desc") -> Dict[str, Any]:
        params = {"page": page, "limit": limit,
                  "sort_field": sort_field, "sort_type": sort_type}
        if category:
            path = f"/the-loai/{urllib.parse.quote(category)}"
        elif country:
            path = f"/quoc-gia/{urllib.parse.quote(country)}"
        elif year:
            path = f"/nam/{urllib.parse.quote(str(year))}"
        else:
            path = "/danh-sach/phim-moi-cap-nhat"
        try:
            data = self._get(path, params)
        except Exception:
            return {"items": [], "pagination": {}}
        items = data.get("items") if isinstance(data, dict) else []
        path_image = (data.get("pathImage") or "") if isinstance(data, dict) else ""
        return {
            "items": [_normalize_item(it, source_id=self.source, base_url=self.base,
                                      path_image=path_image)
                      for it in (items or [])],
            "pagination": data.get("pagination") if isinstance(data, dict) else {},
        }

    def _filter_list(self, path: str) -> List[Dict[str, Any]]:
        """Some sources expose filter lists under /v1/api/* instead of /api/*.
        Try the configured prefix first, then fall back to /v1/api/ if empty.
        """
        prefixes = [self.api_prefix, "/v1/api"]
        seen = set()
        for prefix in prefixes:
            full_path = (prefix or "") + path
            if full_path in seen:
                continue
            seen.add(full_path)
            try:
                full_url = self.base + full_path
                data = _http_json(full_url, timeout=self.timeout, proxy_url=self.proxy_url)
            except Exception:
                continue
            items = []
            if isinstance(data, dict):
                inner = data.get("data") if isinstance(data.get("data"), dict) else None
                items = (inner or data).get("items") or []
            normalized = [
                {"id": it.get("_id"), "name": it.get("name"), "slug": it.get("slug")}
                for it in items if isinstance(it, dict) and it.get("slug")
            ]
            if normalized:
                return normalized
        return []

    def categories(self) -> List[Dict[str, Any]]:
        return self._filter_list("/the-loai")

    def countries(self) -> List[Dict[str, Any]]:
        return self._filter_list("/quoc-gia")

    def years(self) -> List[Dict[str, Any]]:
        return self._filter_list("/nam")

    # ── helpers ──
    def _abs_url(self, u: str) -> str:
        if not u or u.startswith(("http://", "https://")):
            return u
        return self.base.rstrip("/") + "/" + u.lstrip("/")

    def _to_review_info(self, movie: Dict[str, Any], *, episodes: list) -> Dict[str, Any]:
        tmdb = movie.get("tmdb") or {}
        try:
            rating = float(tmdb.get("vote_average")) if tmdb.get("vote_average") not in (None, "", "null") else None
        except (TypeError, ValueError):
            rating = None
        try:
            vote_count = int(tmdb.get("vote_count") or 0)
        except (TypeError, ValueError):
            vote_count = 0

        genres = [{"name": c["name"]} for c in (movie.get("category") or [])
                  if isinstance(c, dict) and c.get("name")]
        cast = [{"name": n} for n in (movie.get("actor") or []) if n]
        crew = [{"job": "Director", "name": n} for n in (movie.get("director") or []) if n]

        runtime = None
        try:
            t = (movie.get("time") or "").strip()
            if t:
                import re
                m = re.search(r"\d+", t)
                if m:
                    runtime = int(m.group(0))
        except Exception:
            runtime = None

        year = movie.get("year")
        release_date = f"{year}-01-01" if year else ""

        episode_servers = []
        for srv in episodes or []:
            if not isinstance(srv, dict):
                continue
            for ep in (srv.get("server_data") or []):
                if isinstance(ep, dict):
                    episode_servers.append({
                        "server": srv.get("server_name", ""),
                        "name": ep.get("name", ""),
                        "filename": ep.get("filename", ""),
                        "embed": ep.get("link_embed", ""),
                        "m3u8": ep.get("link_m3u8", ""),
                    })

        return {
            "source": self.source,
            "source_label": self.label,
            "id": movie.get("slug"),
            "slug": movie.get("slug"),
            "title": movie.get("name") or movie.get("origin_name") or "",
            "original_title": movie.get("origin_name") or "",
            "release_date": release_date,
            "year": year,
            "overview": (movie.get("content") or "").strip(),
            "tagline": "",
            "vote_average": rating,
            "vote_count": vote_count,
            "runtime": runtime,
            "genres": genres,
            "credits": {"cast": cast, "crew": crew},
            "poster_url": self._abs_url(movie.get("poster_url") or ""),
            "backdrop_url": self._abs_url(movie.get("thumb_url") or movie.get("poster_url") or ""),
            "tmdb_id": tmdb.get("id"),
            "tmdb_type": tmdb.get("type"),
            "imdb_id": (movie.get("imdb") or {}).get("id"),
            "episode_current": movie.get("episode_current"),
            "episode_total": movie.get("episode_total"),
            "type": movie.get("type"),
            "status": movie.get("status"),
            "quality": movie.get("quality"),
            "lang": movie.get("lang"),
            "trailer_url": movie.get("trailer_url") or "",
            "watch_url": f"{self.base}/phim/{movie.get('slug')}" if movie.get("slug") else "",
            "vsmov_url": f"{self.base}/phim/{movie.get('slug')}" if movie.get("slug") else "",  # keep for backward compat
            "episode_servers": episode_servers,
            "country": movie.get("country") or [],
            "showtimes": movie.get("showtimes"),
        }

    @staticmethod
    def collect_image_urls(info: Dict[str, Any], *, limit: int = 12) -> List[str]:
        urls: List[str] = []
        for k in ("backdrop_url", "thumb_url", "poster_url"):
            u = info.get(k) or ""
            if u and u not in urls:
                urls.append(u)
        return urls[:limit]


# ── Convenience: pick the freshest source ──────────────────────────────────
def _sort_score(item: Dict[str, Any]) -> tuple:
    """Higher = better. Sort key for prioritizing cinema/recent movies.

    Order of preference:
      1. Items explicitly tagged `chieurap=true` (only available after detail
         fetch — list views don't expose it, so this mostly applies after
         enrichment).
      2. Newer release year first.
      3. Newer modified timestamp first.
    """
    chieurap = 1 if item.get("chieurap") else 0
    try:
        year = int(item.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    modified = item.get("modified") or ""
    return (chieurap, year, modified)


def latest_combined(sources: List[str], *, per_source: int = 12,
                    proxy_url: Optional[str] = None,
                    min_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """Aggregate latest items from multiple sources, deduped + sorted by recency.

    - `min_year`: drop items older than this year (None keeps all).
    """
    seen_keys = set()
    out: List[Dict[str, Any]] = []
    for src in sources:
        if src not in SOURCES:
            continue
        try:
            client = VNMovieClient(src, proxy_url=proxy_url)
            items = client.latest(page=1)[:per_source]
        except Exception:
            continue
        for it in items:
            if min_year:
                try:
                    if int(it.get("year") or 0) < min_year:
                        continue
                except (TypeError, ValueError):
                    pass
            key = (it.get("tmdb_id") or "") + "|" + (it.get("original_title") or it.get("title") or "")
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(it)
    # Sort: newer year first, then newer modified
    out.sort(key=_sort_score, reverse=True)
    return out


def cinema_latest(sources: List[str], *, max_pages: int = 3,
                  proxy_url: Optional[str] = None,
                  min_year: Optional[int] = None,
                  limit: int = 24) -> List[Dict[str, Any]]:
    """Fetch + filter for movies that look like recent theatrical/cinema releases.

    Strategy without a flag in the list response:
      - Pull `max_pages` pages from each source's latest feed.
      - Score by year + modified, drop items below `min_year` (defaults to
        last 2 calendar years).
      - Bias toward the most recent items overall.
    """
    import datetime as _dt
    if min_year is None:
        min_year = _dt.datetime.now().year - 1

    seen_keys = set()
    pool: List[Dict[str, Any]] = []
    for src in sources:
        if src not in SOURCES:
            continue
        client = VNMovieClient(src, proxy_url=proxy_url)
        for page in range(1, max(1, max_pages) + 1):
            try:
                items = client.latest(page=page)
            except Exception:
                break
            if not items:
                break
            for it in items:
                try:
                    yr = int(it.get("year") or 0)
                except (TypeError, ValueError):
                    yr = 0
                if yr and yr < min_year:
                    continue
                key = (it.get("tmdb_id") or "") + "|" + (it.get("original_title") or it.get("title") or "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                pool.append(it)
    pool.sort(key=_sort_score, reverse=True)
    return pool[:limit]

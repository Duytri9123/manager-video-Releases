"""
VSMOV API client — https://vsmov.com/api-document

Public REST endpoints:
  GET /api/danh-sach/phim-moi-cap-nhat        # latest updates (suggestions)
  GET /api/danh-sach?type=...&page=...&limit=...   # browse by type
  GET /api/tim-kiem?keyword=...&limit=...     # search
  GET /api/phim/<slug>                        # full detail (incl. content/synopsis)

All responses are JSON, fields seen so far:
  list endpoint: {status, items[], pathImage, pagination}
    item: {_id, name, origin_name, slug, poster_url, thumb_url, year,
           tmdb:{type,id,vote_average,...}, imdb:{id}, modified:{time}}
  detail endpoint: {status, msg, movie:{...}, episodes:[...]}
    movie: name, origin_name, content, type, status, poster_url, thumb_url,
           time, episode_current, episode_total, quality, lang, year,
           actor[], director[], category[{id,name,slug}], country[{...}]
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


VSMOV_BASE = "https://vsmov.com"


def _http_json(url: str, *, timeout: int = 20, headers: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "DuyTris-MovieReview/1.0 (+toolvideo)",
        **(headers or {}),
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce VSMOV item → unified shape used by the frontend."""
    tmdb = item.get("tmdb") or {}
    rating = tmdb.get("vote_average")
    try:
        rating = float(rating) if rating not in (None, "", "null") else None
    except (TypeError, ValueError):
        rating = None
    return {
        "source": "vsmov",
        "id": item.get("slug"),
        "vsmov_id": item.get("_id"),
        "title": item.get("name") or item.get("origin_name") or "",
        "original_title": item.get("origin_name") or "",
        "slug": item.get("slug") or "",
        "year": item.get("year"),
        "vote_average": rating,
        "poster_url": item.get("poster_url") or "",
        "thumb_url": item.get("thumb_url") or item.get("poster_url") or "",
        "tmdb_id": tmdb.get("id"),
        "tmdb_type": tmdb.get("type"),
        "imdb_id": (item.get("imdb") or {}).get("id"),
        "modified": (item.get("modified") or {}).get("time"),
        "overview": "",  # filled by `details()`
    }


class VSMovClient:
    """Tiny synchronous wrapper around the VSMOV REST API.

    Built on `urllib` — no extra deps. Use through `VSMovClient(timeout=...)`.
    Set `proxy_url` to route requests through an HTTP proxy (HTTP/S only).
    """

    def __init__(self, *, timeout: int = 20, proxy_url: Optional[str] = None):
        self.timeout = timeout
        self.proxy_url = (proxy_url or "").strip() or None

    # ── transport ──
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = VSMOV_BASE + path
        if params:
            qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url += ("&" if "?" in url else "?") + qs

        if not self.proxy_url:
            return _http_json(url, timeout=self.timeout)

        scheme = self.proxy_url.split("://", 1)[0]
        handler = urllib.request.ProxyHandler({scheme: self.proxy_url})
        opener = urllib.request.build_opener(handler)
        opener.addheaders = [
            ("Accept", "application/json"),
            ("User-Agent", "DuyTris-MovieReview/1.0 (+toolvideo)"),
        ]
        with opener.open(url, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")

    # ── public API ──
    def latest(self, page: int = 1) -> List[Dict[str, Any]]:
        """Recent updates — used as the default "gợi ý" feed on tab open."""
        # Endpoint accepts ?page=N though most days N=1 is plenty
        try:
            data = self._get("/api/danh-sach/phim-moi-cap-nhat", {"page": page})
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else []
        return [_normalize_item(it) for it in (items or [])]

    def browse(self, *, type_: str = "", category: str = "", country: str = "",
               year: str = "", page: int = 1, limit: int = 24,
               sort_field: str = "modified.time",
               sort_type: str = "desc") -> Dict[str, Any]:
        """Generic listing with filters.

        VSMOV exposes 3 separate path-based endpoints when filtering by
        category / country / year, plus the catch-all `/api/danh-sach`.
        We pick the right one based on the args:
          • category="hanh-dong"   → /api/the-loai/hanh-dong
          • country="han-quoc"     → /api/quoc-gia/han-quoc
          • year="2024"            → /api/nam/2024
          • else                   → /api/danh-sach
        """
        params = {"page": page, "limit": limit,
                  "sort_field": sort_field, "sort_type": sort_type}
        if category:
            path = f"/api/the-loai/{urllib.parse.quote(category)}"
        elif country:
            path = f"/api/quoc-gia/{urllib.parse.quote(country)}"
        elif year:
            path = f"/api/nam/{urllib.parse.quote(str(year))}"
        else:
            path = "/api/danh-sach"
            if type_:
                params["type"] = type_

        try:
            data = self._get(path, params)
        except Exception:
            return {"items": [], "pagination": {}}
        items = data.get("items") if isinstance(data, dict) else []
        return {
            "items": [_normalize_item(it) for it in (items or [])],
            "pagination": data.get("pagination") if isinstance(data, dict) else {},
        }

    def categories(self) -> List[Dict[str, Any]]:
        try:
            data = self._get("/api/the-loai")
            items = ((data or {}).get("data") or {}).get("items") or []
            return [{"id": it.get("_id"), "name": it.get("name"), "slug": it.get("slug")}
                    for it in items if it.get("slug")]
        except Exception:
            return []

    def countries(self) -> List[Dict[str, Any]]:
        try:
            data = self._get("/api/quoc-gia")
            items = ((data or {}).get("data") or {}).get("items") or []
            return [{"id": it.get("_id"), "name": it.get("name"), "slug": it.get("slug")}
                    for it in items if it.get("slug")]
        except Exception:
            return []

    def years(self) -> List[Dict[str, Any]]:
        try:
            data = self._get("/api/nam")
            items = ((data or {}).get("data") or {}).get("items") or []
            return [{"id": it.get("_id"), "name": it.get("name"), "slug": it.get("slug")}
                    for it in items if it.get("slug")]
        except Exception:
            return []

    def search(self, keyword: str, *, limit: int = 20, page: int = 1) -> List[Dict[str, Any]]:
        if not keyword.strip():
            return []
        try:
            data = self._get("/api/tim-kiem", {
                "keyword": keyword.strip(), "limit": limit, "page": page,
            })
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else []
        return [_normalize_item(it) for it in (items or [])]

    def details(self, slug: str) -> Optional[Dict[str, Any]]:
        slug = (slug or "").strip()
        if not slug:
            return None
        try:
            data = self._get(f"/api/phim/{urllib.parse.quote(slug)}")
        except Exception:
            return None
        movie = (data or {}).get("movie") if isinstance(data, dict) else None
        if not movie:
            return None
        # Convert into the same shape `core.movie_review.generate_review`
        # consumes (TMDb-like).
        normalized = self._to_review_info(movie, episodes=data.get("episodes") or [])
        return normalized

    @staticmethod
    def _to_review_info(movie: Dict[str, Any], *, episodes: list) -> Dict[str, Any]:
        """Translate VSMOV detail → TMDb-style dict for the LLM/fallback writer."""
        tmdb = movie.get("tmdb") or {}
        try:
            rating = float(tmdb.get("vote_average")) if tmdb.get("vote_average") not in (None, "", "null") else None
        except (TypeError, ValueError):
            rating = None
        try:
            vote_count = int(tmdb.get("vote_count") or 0)
        except (TypeError, ValueError):
            vote_count = 0

        # Map categories → TMDb-like genres
        genres = []
        for c in movie.get("category") or []:
            if isinstance(c, dict) and c.get("name"):
                genres.append({"name": c["name"]})

        # Map cast/crew (only have names — wrap as TMDb-style)
        cast = [{"name": n} for n in (movie.get("actor") or []) if n]
        crew = [{"job": "Director", "name": n} for n in (movie.get("director") or []) if n]

        runtime = None
        try:
            t = (movie.get("time") or "").strip()
            if t:
                # "109", "109 phút", "45 phút/tập"
                import re
                m = re.search(r"\d+", t)
                if m:
                    runtime = int(m.group(0))
        except Exception:
            runtime = None

        # Year → release_date (just YYYY-01-01 placeholder)
        year = movie.get("year")
        release_date = f"{year}-01-01" if year else ""

        # First episode embed link as trailer-ish reference (front-end can show it)
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
            "source": "vsmov",
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
            "poster_path": "",            # use poster_url directly
            "backdrop_path": "",
            "poster_url": movie.get("poster_url") or "",
            "backdrop_url": movie.get("thumb_url") or movie.get("poster_url") or "",
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
            "vsmov_url": f"{VSMOV_BASE}/phim/{movie.get('slug')}" if movie.get("slug") else "",
            "episode_servers": episode_servers,
            "country": movie.get("country") or [],
            "showtimes": movie.get("showtimes"),
        }

    @staticmethod
    def collect_image_urls(info: Dict[str, Any], *, limit: int = 12) -> List[str]:
        """VSMOV gives 2 images per movie (poster+thumb). For richer galleries
        we still include them, then the route-level enrichment can append
        TMDb stills if `tmdb_id` is known."""
        urls: List[str] = []
        for k in ("backdrop_url", "thumb_url", "poster_url"):
            u = info.get(k) or ""
            if u and u not in urls:
                urls.append(u)
        return urls[:limit]

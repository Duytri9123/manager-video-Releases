"""MangaDex API client.

Reference: https://api.mangadex.org/docs/

Public, read-only endpoints used here:
    GET  /manga?title=...&availableTranslatedLanguage[]=...
    GET  /manga/{id}?includes[]=cover_art&includes[]=author&includes[]=artist
    GET  /manga/{id}/feed?translatedLanguage[]=...&order[chapter]=asc
    GET  /at-home/server/{chapter_id}
    Image URL: {baseUrl}/data/{hash}/{filename}        (full quality)
               {baseUrl}/data-saver/{hash}/{filename}  (smaller files)
    Cover URL: https://uploads.mangadex.org/covers/{manga_id}/{file}.512.jpg

The API rate-limits unauthenticated traffic; we keep concurrency=1 and a
small inter-request delay so search → chapters → pages remain reliable.

All HTTP is done via stdlib ``urllib`` so this module has no extra deps.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Optional

API_BASE = "https://api.mangadex.org"
COVER_BASE = "https://uploads.mangadex.org/covers"
USER_AGENT = "DuyTrisMangaTool/1.0 (+https://duytris.local)"


class MangaDexError(RuntimeError):
    """Wrap any HTTP / JSON / API error from MangaDex with a friendly message."""


# ── Localised text helper ───────────────────────────────────────────────────
# MangaDex returns title/description as a dict keyed by language code.
# We try the user's preferred languages then fall back to whatever exists.
def pick_lang(d: dict, prefer: Iterable[str] = ("vi", "en", "ja-ro", "ja")) -> str:
    if not isinstance(d, dict):
        return ""
    for code in prefer:
        v = d.get(code)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # Fallback: first non-empty string
    for v in d.values():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# ── Internal HTTP helper ────────────────────────────────────────────────────
def _request_json(
    url: str,
    *,
    timeout: int = 20,
    proxy_url: Optional[str] = None,
    retries: int = 2,
) -> Any:
    """GET ``url`` and return the decoded JSON body. Retries 502/503/429."""
    last_err: Optional[Exception] = None
    for attempt in range(max(1, retries + 1)):
        try:
            handlers: list = []
            if proxy_url:
                scheme = proxy_url.split("://", 1)[0]
                handlers.append(urllib.request.ProxyHandler({scheme: proxy_url}))
            opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
            opener.addheaders = [
                ("User-Agent", USER_AGENT),
                ("Accept", "application/json"),
            ]
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            # MangaDex sometimes 503s briefly during deploys, retry a couple of times
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                last_err = e
                continue
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            raise MangaDexError(f"HTTP {e.code} on {url}: {detail or e.reason}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                last_err = e
                continue
            raise MangaDexError(f"Network error on {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise MangaDexError(f"Invalid JSON from {url}: {e}") from e
    raise MangaDexError(f"Request failed: {last_err}")


def _build_qs(params: dict) -> str:
    """Build a query string supporting list values via repeated keys (MangaDex
    uses ``availableTranslatedLanguage[]=vi&availableTranslatedLanguage[]=en``)."""
    pairs: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (list, tuple, set)):
            for item in v:
                if item is None or item == "":
                    continue
                pairs.append((k, str(item)))
        else:
            pairs.append((k, str(v)))
    return urllib.parse.urlencode(pairs, doseq=False)


# ── Data classes ────────────────────────────────────────────────────────────
@dataclass
class MangaSummary:
    id: str
    title: str
    alt_title: str = ""
    description: str = ""
    year: Optional[int] = None
    status: str = ""
    content_rating: str = ""
    original_lang: str = ""
    available_languages: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    cover_url: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Chapter:
    id: str
    chapter: str = ""        # "1", "1.5", "Extra"
    volume: str = ""
    title: str = ""
    language: str = ""
    pages: int = 0
    publish_at: str = ""
    scanlation_group: str = ""
    external_url: str = ""   # set for officially-licensed chapters served elsewhere

    @property
    def is_external(self) -> bool:
        """Officially-licensed chapters cannot be fetched via MD@Home.

        These chapters live on MangaPlus / Comikey / Azuki etc. and the
        ``/at-home/server`` endpoint returns 404 for them. Skip them in
        the UI or send the user to the external URL.
        """
        return bool(self.external_url)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["is_external"] = self.is_external
        return d


@dataclass
class ChapterPages:
    chapter_id: str
    base_url: str
    hash: str
    pages: List[str] = field(default_factory=list)        # filenames (full)
    pages_saver: List[str] = field(default_factory=list)  # filenames (data-saver)

    def page_urls(self, *, saver: bool = False) -> List[str]:
        which = "data-saver" if saver else "data"
        files = self.pages_saver if saver else self.pages
        return [f"{self.base_url}/{which}/{self.hash}/{f}" for f in files]

    def to_dict(self) -> dict:
        return {
            "chapter_id": self.chapter_id,
            "base_url": self.base_url,
            "hash": self.hash,
            "page_count": len(self.pages),
            "pages": self.page_urls(saver=False),
            "pages_saver": self.page_urls(saver=True),
        }


# ── Helpers to extract relationships ────────────────────────────────────────
def _related(entity: dict, rel_type: str) -> List[dict]:
    return [r for r in (entity.get("relationships") or []) if r.get("type") == rel_type]


def _cover_filename(entity: dict) -> str:
    rels = _related(entity, "cover_art")
    if not rels:
        return ""
    rel = rels[0]
    attrs = rel.get("attributes") or {}
    return attrs.get("fileName") or ""


def _author_names(entity: dict) -> List[str]:
    out = []
    for kind in ("author", "artist"):
        for r in _related(entity, kind):
            attrs = r.get("attributes") or {}
            name = attrs.get("name")
            if name and name not in out:
                out.append(name)
    return out


def _build_cover_url(manga_id: str, file_name: str, *, size: str = "512") -> str:
    if not file_name:
        return ""
    if size and size in ("256", "512"):
        return f"{COVER_BASE}/{manga_id}/{file_name}.{size}.jpg"
    return f"{COVER_BASE}/{manga_id}/{file_name}"


# ── Client ──────────────────────────────────────────────────────────────────
class MangaDexClient:
    """Thin client over the MangaDex public REST API."""

    def __init__(
        self,
        *,
        timeout: int = 20,
        proxy_url: Optional[str] = None,
        request_delay: float = 0.25,
        prefer_langs: Iterable[str] = ("vi", "en", "ja-ro", "ja"),
    ):
        self.timeout = timeout
        self.proxy_url = proxy_url or None
        self.request_delay = max(0.0, float(request_delay))
        self.prefer_langs = tuple(prefer_langs)
        self._last_request_at = 0.0

    # ── Internal: throttle + GET ─────────────────────────────────────────
    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        # Cooperative rate-limit (MangaDex: ~5 rps, we stay well under)
        if self.request_delay:
            wait = self._last_request_at + self.request_delay - time.time()
            if wait > 0:
                time.sleep(wait)
        qs = _build_qs(params or {})
        url = f"{API_BASE}{path}"
        if qs:
            url += ("&" if "?" in url else "?") + qs
        try:
            return _request_json(url, timeout=self.timeout, proxy_url=self.proxy_url)
        finally:
            self._last_request_at = time.time()

    # ── Public: search manga ─────────────────────────────────────────────
    def search_manga(
        self,
        title: str = "",
        *,
        limit: int = 20,
        offset: int = 0,
        translated_languages: Optional[Iterable[str]] = ("vi", "en"),
        content_ratings: Optional[Iterable[str]] = ("safe", "suggestive"),
        order_field: str = "relevance",
        order_dir: str = "desc",
    ) -> List[MangaSummary]:
        """Search the manga catalogue by free-text title.

        ``translated_languages`` filters to manga that have at least one
        chapter translated into one of those codes. Pass ``None`` to disable.
        """
        params: dict = {
            "title": title or None,
            "limit": max(1, min(100, int(limit))),
            "offset": max(0, int(offset)),
            "includes[]": ["cover_art", "author", "artist"],
            "contentRating[]": list(content_ratings) if content_ratings else None,
            "availableTranslatedLanguage[]": (
                list(translated_languages) if translated_languages else None
            ),
            f"order[{order_field}]": order_dir,
        }
        body = self._get("/manga", params)
        data = body.get("data") or []
        out: List[MangaSummary] = []
        for entity in data:
            out.append(self._summary_from_entity(entity))
        return out

    def _summary_from_entity(self, entity: dict) -> MangaSummary:
        attrs = entity.get("attributes") or {}
        manga_id = entity.get("id") or ""
        title_dict = attrs.get("title") or {}
        alt_titles = attrs.get("altTitles") or []
        # Flatten altTitles which is a list of dicts
        alt_dict: dict = {}
        for d in alt_titles:
            if isinstance(d, dict):
                alt_dict.update(d)
        title = pick_lang(title_dict, self.prefer_langs)
        alt = ""
        for code in self.prefer_langs:
            v = alt_dict.get(code)
            if v and v != title:
                alt = v
                break
        if not alt:
            for v in alt_dict.values():
                if v and v != title:
                    alt = v
                    break
        return MangaSummary(
            id=manga_id,
            title=title or alt or "(không có tiêu đề)",
            alt_title=alt,
            description=pick_lang(attrs.get("description") or {}, self.prefer_langs),
            year=attrs.get("year"),
            status=str(attrs.get("status") or ""),
            content_rating=str(attrs.get("contentRating") or ""),
            original_lang=str(attrs.get("originalLanguage") or ""),
            available_languages=list(attrs.get("availableTranslatedLanguages") or []),
            tags=[
                pick_lang(((t.get("attributes") or {}).get("name") or {}), ("en", "vi"))
                for t in (attrs.get("tags") or [])
                if t.get("attributes")
            ],
            authors=_author_names(entity),
            cover_url=_build_cover_url(manga_id, _cover_filename(entity)),
        )

    # ── Public: manga details ────────────────────────────────────────────
    def get_manga(self, manga_id: str) -> MangaSummary:
        if not manga_id:
            raise MangaDexError("manga_id rỗng.")
        body = self._get(
            f"/manga/{manga_id}",
            {"includes[]": ["cover_art", "author", "artist"]},
        )
        entity = body.get("data") or {}
        if not entity:
            raise MangaDexError("Không tìm thấy manga.")
        return self._summary_from_entity(entity)

    # ── Public: list chapters via feed ───────────────────────────────────
    def list_chapters(
        self,
        manga_id: str,
        *,
        translated_languages: Optional[Iterable[str]] = ("vi", "en"),
        order_field: str = "chapter",
        order_dir: str = "asc",
        limit: int = 500,
        max_pages: int = 5,
    ) -> List[Chapter]:
        """Fetch the manga feed (chapters), paginating up to ``max_pages``."""
        if not manga_id:
            raise MangaDexError("manga_id rỗng.")
        out: List[Chapter] = []
        per_page = 100
        for page_idx in range(max_pages):
            offset = page_idx * per_page
            if offset >= limit:
                break
            params = {
                "translatedLanguage[]": (
                    list(translated_languages) if translated_languages else None
                ),
                "limit": min(per_page, limit - offset),
                "offset": offset,
                f"order[{order_field}]": order_dir,
                "includes[]": ["scanlation_group"],
                "contentRating[]": ["safe", "suggestive", "erotica", "pornographic"],
            }
            body = self._get(f"/manga/{manga_id}/feed", params)
            items = body.get("data") or []
            if not items:
                break
            for ent in items:
                out.append(self._chapter_from_entity(ent))
            total = int(body.get("total") or 0)
            if offset + per_page >= total:
                break
        return out

    def _chapter_from_entity(self, entity: dict) -> Chapter:
        attrs = entity.get("attributes") or {}
        groups = _related(entity, "scanlation_group")
        group_name = ""
        if groups:
            group_name = (groups[0].get("attributes") or {}).get("name") or ""
        return Chapter(
            id=entity.get("id") or "",
            chapter=str(attrs.get("chapter") or ""),
            volume=str(attrs.get("volume") or ""),
            title=str(attrs.get("title") or ""),
            language=str(attrs.get("translatedLanguage") or ""),
            pages=int(attrs.get("pages") or 0),
            publish_at=str(attrs.get("publishAt") or ""),
            scanlation_group=group_name,
            external_url=str(attrs.get("externalUrl") or ""),
        )

    # ── Public: chapter pages ────────────────────────────────────────────
    def get_chapter_pages(self, chapter_id: str, *, force_443: bool = True) -> ChapterPages:
        """Resolve the MD@Home CDN base + page filenames for a chapter.

        Officially-licensed chapters (MangaPlus, Comikey, Azuki, ...) are NOT
        served by MD@Home and return 404. The caller should pre-filter
        chapters with ``Chapter.is_external == True``.
        """
        if not chapter_id:
            raise MangaDexError("chapter_id rỗng.")
        params = {"forcePort443": "true"} if force_443 else {}
        try:
            body = self._get(f"/at-home/server/{chapter_id}", params)
        except MangaDexError as e:
            if "HTTP 404" in str(e):
                raise MangaDexError(
                    "Chương này được phát hành chính thức ở dịch vụ khác "
                    "(MangaPlus / Comikey / Azuki / ...). MangaDex không host "
                    "ảnh — hãy chọn chương khác."
                ) from e
            raise
        chapter = body.get("chapter") or {}
        return ChapterPages(
            chapter_id=chapter_id,
            base_url=str(body.get("baseUrl") or ""),
            hash=str(chapter.get("hash") or ""),
            pages=list(chapter.get("data") or []),
            pages_saver=list(chapter.get("dataSaver") or []),
        )

    # ── Convenience: page download ───────────────────────────────────────
    def download_pages(
        self,
        pages: ChapterPages,
        out_dir: Path,
        *,
        saver: bool = False,
        progress=None,
    ) -> List[Path]:
        """Download all pages of a chapter into ``out_dir``."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        urls = pages.page_urls(saver=saver)
        results: List[Path] = []
        n = len(urls)
        for idx, url in enumerate(urls, start=1):
            # Filenames preserve original extension
            ext = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
            dst = out_dir / f"page_{idx:03d}{ext}"
            ok = _http_download(url, dst, timeout=self.timeout, proxy_url=self.proxy_url)
            if ok:
                results.append(dst)
            if progress:
                try:
                    progress(idx, n, str(dst))
                except Exception:
                    pass
        return results


# ── Plain HTTP downloader (used both by the client and the renderer) ────────
def _http_download(
    url: str,
    dst: Path,
    *,
    timeout: int = 30,
    proxy_url: Optional[str] = None,
) -> bool:
    try:
        handlers: list = []
        if proxy_url:
            scheme = proxy_url.split("://", 1)[0]
            handlers.append(urllib.request.ProxyHandler({scheme: proxy_url}))
        opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
        # Referer: matching the image host avoids 403s from CDN hotlink protection
        try:
            host = urllib.parse.urlparse(url).hostname or "mangadex.org"
            referer = f"https://{host}/"
        except Exception:
            referer = "https://mangadex.org/"
        opener.addheaders = [
            ("User-Agent", USER_AGENT),
            ("Referer", referer),
            ("Accept", "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"),
        ]
        with opener.open(url, timeout=timeout) as resp, open(dst, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        return False

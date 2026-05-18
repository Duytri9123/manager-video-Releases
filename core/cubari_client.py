"""Cubari (cubari.moe) API client.

Cubari is a public, read-only manga proxy that ingests `gist.json`-style
manifests from various sources (mangadex links, raw image hosts, imgur
albums, ...). It exposes them through a stable JSON API so we can render
chapters that MangaDex itself doesn't have license to host.

Two reading modes are supported here:

1. **Direct gist URL** — user pastes a `https://cubari.moe/read/<source>/<slug>/`
   link, we fetch `https://cubari.moe/read/api/<source>/series/<slug>/`
   to get the chapter list, and resolve a chapter via
   `https://cubari.moe/read/api/<source>/chapter/<slug>/<ch>/`.
2. **Raw gist JSON** — series creators publish a JSON manifest containing
   pages keyed by chapter number. We mirror Cubari's parsing of those.

Cubari's source codes: ``mangadex`` | ``imgur`` | ``imgchest`` | ``gist``.
We do not modify the data, we just bridge it into the same shape used by
``core.mangadex_client`` so the rest of the renderer is provider-agnostic.

Reference (community-maintained): https://cubari.moe/read/
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, List, Optional

from core.mangadex_client import (
    Chapter,
    ChapterPages,
    MangaDexError,
    MangaSummary,
)

CUBARI_BASE = "https://cubari.moe"
USER_AGENT = "DuyTrisMangaTool/1.0 (+https://duytris.local)"


# ── HTTP helper (mirrors mangadex_client._request_json but for Cubari) ──────
def _request_json(
    url: str,
    *,
    timeout: int = 20,
    proxy_url: Optional[str] = None,
    retries: int = 2,
):
    last_err: Optional[Exception] = None
    for attempt in range(max(1, retries + 1)):
        try:
            handlers: list = []
            if proxy_url:
                scheme = proxy_url.split("://", 1)[0]
                handlers.append(urllib.request.ProxyHandler({scheme: proxy_url}))
            opener = (
                urllib.request.build_opener(*handlers)
                if handlers else urllib.request.build_opener()
            )
            opener.addheaders = [
                ("User-Agent", USER_AGENT),
                ("Accept", "application/json, text/plain, */*"),
                ("Referer", "https://cubari.moe/"),
            ]
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
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
    raise MangaDexError(f"Cubari request failed: {last_err}")


# ── URL parsing ─────────────────────────────────────────────────────────────
_CUBARI_PATH_RE = re.compile(
    r"^/read/(?P<source>[a-zA-Z0-9_-]+)/(?P<slug>[^/]+)/?(?P<rest>.*)$"
)


def parse_cubari_url(url: str) -> Optional[dict]:
    """Pull source + slug out of any cubari.moe link, including chapter URLs.

    Examples it accepts::

        https://cubari.moe/read/gist/<slug>/
        https://cubari.moe/read/imgur/<gallery>/
        https://cubari.moe/read/mangadex/<id>/1/1/
    """
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return None
    if u.netloc and "cubari.moe" not in u.netloc.lower():
        return None
    m = _CUBARI_PATH_RE.match(u.path or "")
    if not m:
        return None
    return {
        "source": m.group("source"),
        "slug": m.group("slug"),
        "rest": m.group("rest"),
    }


# ── Series / chapter API ────────────────────────────────────────────────────
def get_series(source: str, slug: str, *, proxy_url: Optional[str] = None) -> dict:
    """Fetch the series manifest. Returns Cubari's raw JSON unchanged."""
    if not source or not slug:
        raise MangaDexError("Cubari: thiếu source/slug.")
    api = f"{CUBARI_BASE}/read/api/{source}/series/{urllib.parse.quote(slug, safe='')}/"
    return _request_json(api, proxy_url=proxy_url)


def series_to_summary(source: str, slug: str, raw: dict) -> MangaSummary:
    """Adapt Cubari's series JSON to a ``MangaSummary``."""
    title = raw.get("title") or slug
    desc = raw.get("description") or ""
    cover = raw.get("cover") or ""
    author = raw.get("author") or ""
    artist = raw.get("artist") or ""
    authors: list[str] = []
    if author:
        authors.append(author)
    if artist and artist not in authors:
        authors.append(artist)
    return MangaSummary(
        id=f"cubari:{source}/{slug}",
        title=title,
        alt_title="",
        description=desc,
        year=None,
        status="",
        content_rating="",
        original_lang="",
        available_languages=[],
        tags=[],
        authors=authors,
        cover_url=cover,
    )


def list_chapters(source: str, slug: str, *, proxy_url: Optional[str] = None) -> List[Chapter]:
    """Build a list of ``Chapter`` from the series manifest.

    Cubari's ``chapters`` field is a dict keyed by chapter number. Each
    chapter has nested ``groups`` keyed by scanlation group name. We pick
    the first group as the canonical one and surface group name + page
    count.
    """
    raw = get_series(source, slug, proxy_url=proxy_url)
    chapters_raw: dict = raw.get("chapters") or {}
    out: List[Chapter] = []
    for ch_num, ch in chapters_raw.items():
        if not isinstance(ch, dict):
            continue
        groups = ch.get("groups") or {}
        # Choose first group name; pages can be a list (URLs) OR a dict.
        first_group = next(iter(groups.items()), (None, None))
        group_name, group_pages = first_group
        page_count = 0
        if isinstance(group_pages, list):
            page_count = len(group_pages)
        elif isinstance(group_pages, str):
            # Cubari sometimes hands back a proxy URL we need to resolve later.
            page_count = 0
        out.append(Chapter(
            id=f"cubari:{source}/{slug}/{ch_num}",
            chapter=str(ch_num),
            volume=str(ch.get("volume") or ""),
            title=str(ch.get("title") or ""),
            language="",
            pages=page_count,
            publish_at=str(ch.get("last_updated") or ""),
            scanlation_group=str(group_name or ""),
            external_url="",
        ))

    # Sort numerically when possible, fallback to string order
    def _key(c: Chapter):
        try:
            return (0, float(c.chapter))
        except (TypeError, ValueError):
            return (1, c.chapter or "")
    out.sort(key=_key)
    return out


def get_chapter_pages(
    source: str,
    slug: str,
    chapter_num: str,
    *,
    proxy_url: Optional[str] = None,
) -> ChapterPages:
    """Resolve direct image URLs for a chapter.

    First tries the dedicated chapter endpoint
    ``/read/api/{source}/chapter/{slug}/{ch}/``. Falls back to the series
    manifest (some Cubari sources only expose pages there).
    """
    if not source or not slug or chapter_num is None:
        raise MangaDexError("Cubari: thiếu source/slug/chapter.")

    pages: List[str] = []

    # Approach 1: dedicated chapter endpoint
    chap_url = f"{CUBARI_BASE}/read/api/{source}/chapter/{urllib.parse.quote(slug, safe='')}/{urllib.parse.quote(str(chapter_num), safe='')}/"
    try:
        body = _request_json(chap_url, proxy_url=proxy_url)
        # API shape: list of {src: "..."} dicts, or {<group>: [...]}
        if isinstance(body, list):
            pages = [p.get("src") for p in body if isinstance(p, dict) and p.get("src")]
        elif isinstance(body, dict):
            for v in body.values():
                if isinstance(v, list):
                    for p in v:
                        if isinstance(p, dict) and p.get("src"):
                            pages.append(p["src"])
                        elif isinstance(p, str):
                            pages.append(p)
                    if pages:
                        break
    except MangaDexError:
        pages = []

    # Approach 2: dig into the series manifest
    if not pages:
        raw = get_series(source, slug, proxy_url=proxy_url)
        ch = (raw.get("chapters") or {}).get(str(chapter_num)) or {}
        groups = ch.get("groups") or {}
        for group_pages in groups.values():
            if isinstance(group_pages, list) and group_pages:
                # Direct list of URLs
                pages = [p if isinstance(p, str) else (p.get("src") or "") for p in group_pages]
                pages = [p for p in pages if p]
                break
            if isinstance(group_pages, str) and group_pages:
                # Cubari proxy URL — fetch it for the actual page list
                proxy_target = (
                    group_pages if group_pages.startswith("http")
                    else CUBARI_BASE + group_pages
                )
                try:
                    sub = _request_json(proxy_target, proxy_url=proxy_url)
                    if isinstance(sub, list):
                        pages = [p.get("src") if isinstance(p, dict) else p for p in sub]
                        pages = [p for p in pages if p]
                except MangaDexError:
                    pages = []
                if pages:
                    break

    if not pages:
        raise MangaDexError(
            "Không lấy được trang ảnh từ Cubari (có thể manifest đã hết hạn)."
        )

    return ChapterPages(
        chapter_id=f"cubari:{source}/{slug}/{chapter_num}",
        base_url="",
        hash="",
        pages=pages,           # already absolute URLs
        pages_saver=pages,
    )


# ── Search by URL (paste a Cubari link) ─────────────────────────────────────
def search_by_url(url: str, *, proxy_url: Optional[str] = None) -> Optional[MangaSummary]:
    parsed = parse_cubari_url(url)
    if not parsed:
        return None
    raw = get_series(parsed["source"], parsed["slug"], proxy_url=proxy_url)
    return series_to_summary(parsed["source"], parsed["slug"], raw)

"""Comick (api.comick.fun) client.

Comick is an aggregator that lists manga, manhwa, manhua scraped from
multiple scanlation sites. Its public read-only JSON API lets us search,
list chapters, and resolve chapter image URLs without scraping HTML.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from core.mangadex_client import (
    Chapter,
    ChapterPages,
    MangaDexError,
    MangaSummary,
)


API_BASE = "https://api.comick.fun"
COVER_BASE = "https://meo.comick.pictures"
USER_AGENT = "Mozilla/5.0 (compatible; DuyTrisManga/1.0)"


def _request_json(url: str, *, timeout: int = 20,
                  proxy_url: Optional[str] = None, retries: int = 2):
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
                ("Accept", "application/json"),
            ]
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read()
            return json.loads(body.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                last_err = e
                continue
            raise MangaDexError(f"HTTP {e.code} on {url}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                last_err = e
                continue
            raise MangaDexError(f"Network error on {url}: {e}") from e
        except json.JSONDecodeError as e:
            raise MangaDexError(f"Invalid JSON from {url}: {e}") from e
    raise MangaDexError(f"Comick request failed: {last_err}")


def _cover_url(md_covers: list) -> str:
    if not md_covers:
        return ""
    for cov in md_covers:
        b = cov.get("b") or cov.get("file") or ""
        if b:
            return f"{COVER_BASE}/{b}"
    return ""


def search(query: str, *, limit: int = 20,
           proxy_url: Optional[str] = None) -> List[MangaSummary]:
    if not query.strip():
        return []
    url = f"{API_BASE}/v1.0/search?q={urllib.parse.quote(query)}&limit={limit}&page=1"
    data = _request_json(url, proxy_url=proxy_url)
    if not isinstance(data, list):
        return []
    out: List[MangaSummary] = []
    for entry in data[:limit]:
        hid = entry.get("hid") or entry.get("id") or ""
        slug = entry.get("slug") or ""
        title = (
            entry.get("title")
            or (entry.get("md_titles") or [{}])[0].get("title", "")
            or "(không có tiêu đề)"
        )
        out.append(MangaSummary(
            id=f"comick:{hid}|{slug}",
            title=title,
            alt_title="",
            description="",
            year=entry.get("year"),
            status=str(entry.get("status") or ""),
            content_rating="",
            original_lang=str(entry.get("country") or ""),
            available_languages=list(entry.get("translation_completed") or []),
            tags=[g.get("name", "") for g in entry.get("md_genres") or []],
            authors=[],
            cover_url=_cover_url(entry.get("md_covers") or []),
        ))
    return out


def list_chapters(hid: str, *, lang: str = "", limit: int = 300,
                  proxy_url: Optional[str] = None) -> List[Chapter]:
    qs = {"limit": str(limit), "page": "1"}
    if lang:
        qs["lang"] = lang
    url = f"{API_BASE}/comic/{hid}/chapters?{urllib.parse.urlencode(qs)}"
    data = _request_json(url, proxy_url=proxy_url)
    items = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: List[Chapter] = []
    for ch in items:
        groups = ch.get("group_name") or []
        group = ", ".join(groups) if isinstance(groups, list) else str(groups)
        out.append(Chapter(
            id=f"comick:{ch.get('hid') or ''}",
            chapter=str(ch.get("chap") or ""),
            volume=str(ch.get("vol") or ""),
            title=str(ch.get("title") or ""),
            language=str(ch.get("lang") or lang or ""),
            pages=int(ch.get("count_images") or 0),
            publish_at=str(ch.get("created_at") or ""),
            scanlation_group=group,
            external_url="",
        ))
    out.sort(key=lambda c: (
        0 if c.chapter else 1,
        float(c.chapter) if c.chapter.replace(".", "", 1).isdigit() else 0,
    ))
    return out


def get_chapter_pages(chapter_hid: str, *,
                      proxy_url: Optional[str] = None) -> ChapterPages:
    url = f"{API_BASE}/chapter/{chapter_hid}?tachiyomi=true"
    data = _request_json(url, proxy_url=proxy_url)
    chap = data.get("chapter") if isinstance(data, dict) else None
    if not isinstance(chap, dict):
        raise MangaDexError("Comick: phản hồi không có chapter.")
    md_images = chap.get("md_images") or []
    pages: List[str] = []
    for img in md_images:
        b = img.get("b") or img.get("file") or ""
        if b:
            pages.append(f"{COVER_BASE}/{b}")
    if not pages:
        raise MangaDexError("Comick: chương này không có ảnh.")
    return ChapterPages(
        chapter_id=f"comick:{chapter_hid}",
        base_url=COVER_BASE,
        hash="",
        pages=pages,
        pages_saver=pages,
    )


def split_id(value: str) -> tuple[str, str]:
    """Parse 'comick:<hid>|<slug>' → (hid, slug)."""
    s = (value or "").strip()
    if s.startswith("comick:"):
        s = s[len("comick:"):]
    if "|" in s:
        hid, slug = s.split("|", 1)
        return hid, slug
    return s, ""

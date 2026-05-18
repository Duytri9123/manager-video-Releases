"""Bato.to (mto.to / batocomic.org) client.

Bato hosts a huge international catalogue (One Piece, Naruto, etc.) and
is reachable without authentication. The site has a lot of mirror
domains that rotate; we try a few in order.

Search uses the public ``/search?word=...`` HTML page. We parse manga
cards and chapter pages with regex (no extra deps required).

Each manga has a stable URL like ``https://bato.to/series/<id>/<slug>``.
A chapter looks like ``https://bato.to/chapter/<id>``.

For chapter image extraction Bato embeds an inline JS array
``imgHttps`` (or ``imgHttpLis``) that we can pull out with a regex.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

from core.manga_extractors import (
    USER_AGENT,
    _abs,
    _all_imgs,
    _attrs,
    _fetch_html,
    ExtractError,
)


MIRRORS = [
    "https://bato.to",
    "https://mto.to",
    "https://batocomic.org",
    "https://batocomic.com",
    "https://batocomic.net",
    "https://batotoo.com",
    "https://battwo.com",
]


# ── Data classes (compatible with MangaSummary / Chapter shapes) ────────────
@dataclass
class BatoManga:
    id: str
    title: str
    url: str
    cover_url: str = ""
    description: str = ""
    authors: List[str] = field(default_factory=list)
    status: str = ""
    genres: List[str] = field(default_factory=list)
    source: str = "bato"

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d.update({
            "alt_title": "",
            "year": None,
            "content_rating": "",
            "original_lang": "",
            "available_languages": [],
            "tags": d.get("genres") or [],
        })
        return d


@dataclass
class BatoChapter:
    id: str               # absolute URL to chapter reader
    chapter: str = ""
    title: str = ""
    publish_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chapter": self.chapter,
            "title": self.title,
            "url": self.id,
            "language": "",
            "pages": 0,
            "publish_at": self.publish_at,
            "scanlation_group": "",
            "external_url": "",
            "is_external": False,
        }


# ── Mirror rotation helper ──────────────────────────────────────────────────
def _fetch_with_mirrors(path: str, *, proxy_url: Optional[str] = None,
                        timeout: int = 20) -> tuple[str, str]:
    last_err: Optional[Exception] = None
    for base in MIRRORS:
        url = base.rstrip("/") + path
        try:
            page = _fetch_html(url, timeout=timeout, proxy_url=proxy_url)
            if page and len(page) > 500:
                return page, base.rstrip("/")
        except Exception as e:
            last_err = e
            continue
    raise ExtractError(
        f"Bato.to: tất cả mirror đều không truy cập được. Lỗi cuối: {last_err}"
    )


# ── Search ──────────────────────────────────────────────────────────────────
def search(keyword: str, *, limit: int = 20,
           proxy_url: Optional[str] = None) -> List[BatoManga]:
    if not keyword.strip():
        return []
    qs = urllib.parse.urlencode({"word": keyword})
    page, base = _fetch_with_mirrors(f"/search?{qs}", proxy_url=proxy_url)
    return _parse_search(page, base=base, limit=limit)


_SERIES_RE = re.compile(
    r'<a[^>]+href="(?P<href>/(?:series|title)/[^"]+)"[^>]*(?:title="(?P<title>[^"]*)")?[^>]*>(?P<inner>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _parse_search(page: str, *, base: str, limit: int) -> List[BatoManga]:
    out: List[BatoManga] = []
    seen = set()
    for m in _SERIES_RE.finditer(page):
        href = m.group("href").split("?", 1)[0]
        # Skip chapter-link hrefs and group/user pages
        if "/chapter/" in href:
            continue
        if href in seen:
            continue
        title_attr = (m.group("title") or "").strip()
        inner = m.group("inner") or ""
        title = title_attr or _strip(inner)
        if not title or len(title) < 2:
            continue
        # Need a real cover (filter out junk anchors that have no image)
        cover = ""
        for img in _all_imgs(inner, base):
            cover = img.get("resolved", "")
            if cover and not cover.endswith((".svg", ".gif")):
                break
        if not cover:
            continue
        seen.add(href)
        out.append(BatoManga(
            id=_abs(href, base),
            title=title,
            url=_abs(href, base),
            cover_url=cover,
        ))
        if len(out) >= limit:
            break
    return out


# ── Manga details + chapter list ────────────────────────────────────────────
def get_manga(url: str, *, proxy_url: Optional[str] = None,
              timeout: int = 20) -> BatoManga:
    if not url.startswith(("http://", "https://")):
        raise ExtractError("Bato: cần URL đầy đủ.")
    page = _fetch_html(url, proxy_url=proxy_url, timeout=timeout)
    title = ""
    m = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        page, re.IGNORECASE,
    )
    if m:
        title = html.unescape(m.group(1)).strip()
    if not title:
        m = re.search(r"<title>([^<]+)</title>", page, re.IGNORECASE)
        if m:
            title = html.unescape(m.group(1)).strip()

    cover = ""
    m = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        page, re.IGNORECASE,
    )
    if m:
        cover = html.unescape(m.group(1)).strip()

    desc = ""
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        page, re.IGNORECASE,
    )
    if m:
        desc = html.unescape(m.group(1)).strip()

    info = BatoManga(id=url, title=title or "(không tiêu đề)", url=url,
                     cover_url=cover, description=desc[:1500])

    chapters = _parse_chapter_list(page, base=url)
    setattr(info, "_chapters", chapters)
    return info


def list_chapters(url: str, *, proxy_url: Optional[str] = None) -> List[BatoChapter]:
    info = get_manga(url, proxy_url=proxy_url)
    return list(getattr(info, "_chapters", []) or [])


_CHAPTER_RE = re.compile(
    r'<a[^>]+href="(?P<href>/chapter/\d+[^"]*)"[^>]*>(?P<text>[^<]+)</a>',
    re.IGNORECASE,
)


def _parse_chapter_list(page: str, *, base: str) -> List[BatoChapter]:
    out: List[BatoChapter] = []
    seen = set()
    for m in _CHAPTER_RE.finditer(page):
        href = m.group("href")
        if href in seen:
            continue
        seen.add(href)
        text = m.group("text").strip()
        cm = re.search(r"(?:ch\.?|chapter|episode|ep|tập)\s*(\d+(?:\.\d+)?)",
                       text, re.IGNORECASE)
        ch = cm.group(1) if cm else ""
        out.append(BatoChapter(
            id=_abs(href, base),
            chapter=ch,
            title=text,
        ))
    # Bato lists newest first; reverse to chronological order
    def _key(c: BatoChapter):
        try:
            return (0, float(c.chapter))
        except (TypeError, ValueError):
            return (1, c.chapter or "")
    out.sort(key=_key)
    return out


# ── Chapter pages ───────────────────────────────────────────────────────────
def get_chapter_pages(chapter_url: str, *, proxy_url: Optional[str] = None,
                      timeout: int = 20) -> List[str]:
    if not chapter_url.startswith(("http://", "https://")):
        raise ExtractError("Bato: cần URL chương đầy đủ.")
    page = _fetch_html(chapter_url, proxy_url=proxy_url, timeout=timeout)

    # Bato readers embed the image array as JS:
    #   const imgHttps = ["https://...", "https://..."];
    #   var imgHttpLis = [...];
    for var in ("imgHttps", "imgHttpLis", "images"):
        m = re.search(
            rf'(?:const|var|let)\s+{re.escape(var)}\s*=\s*(\[[^\]]+\])',
            page, re.IGNORECASE,
        )
        if not m:
            continue
        try:
            arr = json.loads(m.group(1))
            urls = [u for u in arr if isinstance(u, str) and u.startswith(("http://", "https://"))]
            if urls:
                return urls
        except Exception:
            continue

    # Fallback: look for batchData / encoded list
    m = re.search(r'batoPass\s*=\s*"([^"]+)"', page)
    if m:
        # Encrypted variant — surface a friendlier error so users try a
        # different mirror or chapter
        raise ExtractError(
            "Bato dùng dạng ảnh mã hóa cho chương này. Thử mirror khác hoặc chương khác."
        )

    # Last resort: parse plain <img> tags inside the reader
    block = re.search(
        r'<div[^>]+id=["\'](?:viewer|page-img|reader)["\'][^>]*>(.*?)</div>',
        page, re.IGNORECASE | re.DOTALL,
    )
    chunk = block.group(1) if block else page
    urls = [
        a.get("resolved", "")
        for a in _all_imgs(chunk, chapter_url)
        if a.get("resolved", "").startswith("http")
    ]
    if not urls:
        raise ExtractError("Bato: không tìm được ảnh chương trong trang.")
    return urls

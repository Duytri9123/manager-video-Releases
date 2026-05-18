"""Vietnamese manga site clients (search → details → chapters → pages).

Mirrors the architecture of ``core.vn_movie_sources`` but for manga sites
that actually host the popular licensed series MangaDex can't.

Currently implemented:

    - **NetTruyen**  (nettruyenvio.com, nettruyen1z1.com, nettruyenrr.com, ...)
    - **TruyenQQ**   (truyenqqto.com, truyenqqviet.com, ...)
    - **BlogTruyen** (blogtruyen.vn, blogtruyenmoi.com)

All three share roughly the same flow:

    /tim-truyen?keyword=...     → list of manga cards
    /<slug>                     → manga detail + chapter list
    /<slug>/<chapter-slug>      → chapter reader (uses extractors from
                                  core.manga_extractors to pull image URLs)

We use ``requests`` for proper TLS / Cloudflare handshake (urllib was
timing out against NetTruyen). All entry points are stateless.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from core.manga_extractors import extract_chapter_images, ExtractError, _all_imgs


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# ── Data classes ────────────────────────────────────────────────────────────
@dataclass
class VNManga:
    id: str               # slug (URL path component)
    title: str
    url: str              # absolute URL to the manga detail page
    cover_url: str = ""
    description: str = ""
    authors: List[str] = field(default_factory=list)
    status: str = ""
    genres: List[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        # Match the MangaSummary shape used by the rest of the app
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
class VNChapter:
    id: str               # absolute URL to the chapter reader page
    chapter: str = ""
    title: str = ""
    url: str = ""
    publish_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chapter": self.chapter,
            "title": self.title,
            "url": self.url,
            "language": "vi",
            "pages": 0,
            "publish_at": self.publish_at,
            "scanlation_group": "",
            "external_url": "",
            "is_external": False,
        }


# ── HTTP helper ─────────────────────────────────────────────────────────────
def _get(url: str, *, timeout: int = 25, proxy_url: Optional[str] = None) -> str:
    """Fetch ``url`` with browser-like headers and return decoded HTML."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.7,en;q=0.3",
        "Referer": _origin(url),
    }
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    resp = requests.get(url, headers=headers, timeout=timeout, proxies=proxies, allow_redirects=True)
    resp.raise_for_status()
    # Honour declared encoding; fall back to UTF-8
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _origin(url: str) -> str:
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}/"


def _abs(href: str, base: str) -> str:
    if not href:
        return ""
    href = html.unescape(href.strip())
    if href.startswith("//"):
        scheme = urllib.parse.urlparse(base).scheme or "https"
        return f"{scheme}:{href}"
    if href.startswith(("http://", "https://")):
        return href
    return urllib.parse.urljoin(base, href)


def _slugify(url: str) -> str:
    p = urllib.parse.urlparse(url).path
    parts = [s for s in p.split("/") if s]
    return parts[-1] if parts else url


# ══════════════════════════════════════════════════════════════════════════════
# NetTruyen
# ══════════════════════════════════════════════════════════════════════════════
class NetTruyenSource:
    id = "nettruyen"
    label = "NetTruyen"
    # Mirror domains rotate frequently; pick the most stable one and
    # let the user override via ``base`` when needed.
    DEFAULT_BASE = "https://www.nettruyenvio.com"

    def __init__(self, base: Optional[str] = None, proxy_url: Optional[str] = None,
                 timeout: int = 25):
        self.base = (base or self.DEFAULT_BASE).rstrip("/")
        self.proxy_url = proxy_url or None
        self.timeout = timeout

    # ── Search ──
    def search(self, keyword: str, *, limit: int = 24) -> List[VNManga]:
        if not keyword.strip():
            return []
        url = f"{self.base}/tim-truyen?keyword={urllib.parse.quote(keyword)}"
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        return self._parse_listing(page, limit=limit)[:limit]

    def _parse_listing(self, page: str, *, limit: int) -> List[VNManga]:
        # NetTruyen card: <div class="item"> <figure class="..."> <a href="/truyen-tranh/<slug>"> ...
        out: List[VNManga] = []
        seen = set()
        # Match the manga link block; very tolerant.
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>/truyen-tranh/[^"]+)"[^>]*(?:title="(?P<title>[^"]*)")?[^>]*>(?P<inner>.*?)</a>',
            page, re.IGNORECASE | re.DOTALL,
        ):
            href = m.group("href").split("?", 1)[0].rstrip("/")
            # Skip chapter URLs (they sit under /truyen-tranh/<slug>/chap-...)
            if re.search(r"/chap-?\d|/chuong-?\d", href, re.IGNORECASE):
                continue
            if href in seen:
                continue
            seen.add(href)
            inner = m.group("inner") or ""
            title = m.group("title") or ""
            if not title:
                # Pull the longest text node inside the link
                text = re.sub(r"<[^>]+>", " ", inner)
                title = re.sub(r"\s+", " ", html.unescape(text)).strip()
            cover = ""
            for img_tag in _all_imgs(inner, self.base):
                cover = img_tag.get("resolved", "")
                if cover:
                    break
            out.append(VNManga(
                id=_slugify(href),
                title=title or "(không tiêu đề)",
                url=_abs(href, self.base),
                cover_url=cover,
                source=self.id,
            ))
            if len(out) >= limit * 3:  # we filter further later, gather extra
                break
        return out

    # ── Details + chapters ──
    def details(self, slug_or_url: str) -> VNManga:
        url = (slug_or_url if slug_or_url.startswith("http")
               else f"{self.base}/truyen-tranh/{slug_or_url.lstrip('/')}")
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        title = self._meta(page, "og:title") or _slugify(url)
        cover = self._meta(page, "og:image") or ""
        desc = self._first_match(
            page,
            r'<div[^>]+class="[^"]*(?:detail-content|shortened|summary-content)[^"]*"[^>]*>(.*?)</div>',
        )
        if desc:
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\s+", " ", html.unescape(desc)).strip()
        return VNManga(
            id=_slugify(url),
            title=title,
            url=url,
            cover_url=cover,
            description=desc[:1500],
            source=self.id,
        )

    def chapters(self, slug_or_url: str) -> List[VNChapter]:
        url = (slug_or_url if slug_or_url.startswith("http")
               else f"{self.base}/truyen-tranh/{slug_or_url.lstrip('/')}")
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        out: List[VNChapter] = []
        seen = set()
        # NetTruyen chapter link: <a href="/truyen-tranh/<slug>/chap-<n>/<id>" title="...">
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>/truyen-tranh/[^"]*/chap[^"]*?)"[^>]*(?:title="(?P<title>[^"]*)")?[^>]*>(?P<txt>[^<]*)</a>',
            page, re.IGNORECASE,
        ):
            href = m.group("href")
            if href in seen:
                continue
            seen.add(href)
            label = (m.group("title") or m.group("txt") or "").strip()
            cm = re.search(r"chap[-\s]?(\d+(?:\.\d+)?)", label or href, re.IGNORECASE)
            ch_num = cm.group(1) if cm else ""
            full = _abs(href, self.base)
            out.append(VNChapter(id=full, chapter=ch_num, title=label, url=full))
        # Sort by numeric chapter ascending
        def _key(c):
            try:
                return (0, float(c.chapter))
            except (TypeError, ValueError):
                return (1, c.chapter or "")
        out.sort(key=_key)
        return out

    # ── helpers ──
    @staticmethod
    def _meta(page: str, prop: str) -> str:
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            page, re.IGNORECASE,
        )
        return html.unescape(m.group(1)).strip() if m else ""

    @staticmethod
    def _first_match(page: str, pattern: str) -> str:
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        return m.group(1) if m else ""


# ══════════════════════════════════════════════════════════════════════════════
# TruyenQQ
# ══════════════════════════════════════════════════════════════════════════════
class TruyenQQSource(NetTruyenSource):
    id = "truyenqq"
    label = "TruyenQQ"
    DEFAULT_BASE = "https://truyenqqto.com"

    def search(self, keyword: str, *, limit: int = 24) -> List[VNManga]:
        # TruyenQQ search URL pattern: /tim-kiem/trang-1.html?q=...
        url = f"{self.base}/tim-kiem/trang-1.html?q={urllib.parse.quote(keyword)}"
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        return self._parse_listing(page, limit=limit)[:limit]

    def _parse_listing(self, page: str, *, limit: int) -> List[VNManga]:
        out: List[VNManga] = []
        seen = set()
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>https?://[^"]+/truyen-tranh/[^"]+)"[^>]*(?:title="(?P<title>[^"]*)")?[^>]*>(?P<inner>.*?)</a>',
            page, re.IGNORECASE | re.DOTALL,
        ):
            href = m.group("href").split("?", 1)[0].rstrip("/")
            if "/chuong-" in href or "/chapter-" in href:
                continue
            if href in seen:
                continue
            seen.add(href)
            title = m.group("title") or ""
            inner = m.group("inner") or ""
            if not title:
                text = re.sub(r"<[^>]+>", " ", inner)
                title = re.sub(r"\s+", " ", html.unescape(text)).strip()
            cover = ""
            for img_tag in _all_imgs(inner, self.base):
                cover = img_tag.get("resolved", "")
                if cover:
                    break
            out.append(VNManga(
                id=_slugify(href),
                title=title or "(không tiêu đề)",
                url=href,
                cover_url=cover,
                source=self.id,
            ))
        return out

    def details(self, slug_or_url: str) -> VNManga:
        url = (slug_or_url if slug_or_url.startswith("http")
               else f"{self.base}/truyen-tranh/{slug_or_url.lstrip('/')}")
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        title = self._meta(page, "og:title") or _slugify(url)
        cover = self._meta(page, "og:image") or ""
        desc = self._first_match(
            page,
            r'<div[^>]+class="[^"]*(?:detail-content|story-detail-info|introduce|story_des)[^"]*"[^>]*>(.*?)</div>',
        )
        if desc:
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\s+", " ", html.unescape(desc)).strip()
        return VNManga(
            id=_slugify(url),
            title=title,
            url=url,
            cover_url=cover,
            description=desc[:1500],
            source=self.id,
        )

    def chapters(self, slug_or_url: str) -> List[VNChapter]:
        url = (slug_or_url if slug_or_url.startswith("http")
               else f"{self.base}/truyen-tranh/{slug_or_url.lstrip('/')}")
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        out: List[VNChapter] = []
        seen = set()
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>https?://[^"]+/(?:truyen-tranh|truyen)/[^"]+/chuong-[^"]+)"[^>]*>(?P<txt>[^<]*)</a>',
            page, re.IGNORECASE,
        ):
            href = m.group("href")
            if href in seen:
                continue
            seen.add(href)
            label = (m.group("txt") or "").strip()
            cm = re.search(r"chuong[-\s]?(\d+(?:[\.,]\d+)?)", href, re.IGNORECASE)
            ch_num = (cm.group(1).replace(",", ".") if cm else "")
            out.append(VNChapter(id=href, chapter=ch_num, title=label, url=href))
        def _key(c):
            try:
                return (0, float(c.chapter))
            except (TypeError, ValueError):
                return (1, c.chapter or "")
        out.sort(key=_key)
        return out


# ══════════════════════════════════════════════════════════════════════════════
# BlogTruyen
# ══════════════════════════════════════════════════════════════════════════════
class BlogTruyenSource(NetTruyenSource):
    id = "blogtruyen"
    label = "BlogTruyen"
    DEFAULT_BASE = "https://blogtruyenmoi.com"

    def search(self, keyword: str, *, limit: int = 24) -> List[VNManga]:
        url = f"{self.base}/timkiem/nangcao/1/-1/-1/-1/-1/-1?txt={urllib.parse.quote(keyword)}"
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        return self._parse_listing(page, limit=limit)[:limit]

    def _parse_listing(self, page: str, *, limit: int) -> List[VNManga]:
        # BlogTruyen result: <div class="list"> ... <p class="storytitle"><a href="/<slug>">...</a></p>
        out: List[VNManga] = []
        seen = set()
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>/[^"]+)"[^>]*(?:title="(?P<title>[^"]*)")?[^>]*>(?P<inner>[^<]*?)</a>',
            page, re.IGNORECASE | re.DOTALL,
        ):
            href = m.group("href").split("?", 1)[0]
            # Filter to BlogTruyen story slugs (numeric prefix common)
            if not re.match(r"^/[\w\-]+(?:-\d+)?$", href):
                continue
            if any(seg in href for seg in ("/the-loai", "/timkiem", "/dang-truyen", "/tag/", "/news", "/the_loai")):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = (m.group("title") or m.group("inner") or "").strip()
            if not title or len(title) < 3:
                continue
            out.append(VNManga(
                id=_slugify(href),
                title=html.unescape(title),
                url=_abs(href, self.base),
                source=self.id,
            ))
        return out

    def chapters(self, slug_or_url: str) -> List[VNChapter]:
        url = (slug_or_url if slug_or_url.startswith("http")
               else f"{self.base}/{slug_or_url.lstrip('/')}")
        page = _get(url, timeout=self.timeout, proxy_url=self.proxy_url)
        out: List[VNChapter] = []
        seen = set()
        # BlogTruyen: chapter links live in <span class="title"><a href="/c<id>/<slug>">
        for m in re.finditer(
            r'<a[^>]+href="(?P<href>/c\d+/[^"]+)"[^>]*>(?P<txt>[^<]+)</a>',
            page, re.IGNORECASE,
        ):
            href = m.group("href")
            if href in seen:
                continue
            seen.add(href)
            label = m.group("txt").strip()
            cm = re.search(r"chương\s*(\d+(?:\.\d+)?)", label, re.IGNORECASE)
            ch_num = cm.group(1) if cm else ""
            full = _abs(href, self.base)
            out.append(VNChapter(id=full, chapter=ch_num, title=label, url=full))
        def _key(c):
            try:
                return (0, float(c.chapter))
            except (TypeError, ValueError):
                return (1, c.chapter or "")
        out.sort(key=_key)
        return out


# ══════════════════════════════════════════════════════════════════════════════
# Source registry
# ══════════════════════════════════════════════════════════════════════════════
SOURCES = {
    "nettruyen": NetTruyenSource,
    "truyenqq":  TruyenQQSource,
    "blogtruyen": BlogTruyenSource,
}


def get_source(source_id: str, **kwargs):
    cls = SOURCES.get(source_id)
    if not cls:
        raise ValueError(f"Unknown source: {source_id}")
    return cls(**kwargs)


def search_combined(keyword: str, *, limit: int = 12,
                    proxy_url: Optional[str] = None,
                    sources: Optional[List[str]] = None) -> List[dict]:
    """Search across multiple Vietnamese manga sites and merge results."""
    targets = sources or list(SOURCES.keys())
    out: List[dict] = []
    for sid in targets:
        try:
            src = get_source(sid, proxy_url=proxy_url)
            for m in src.search(keyword, limit=limit):
                out.append(m.to_dict())
        except Exception:
            continue
    return out


# ── Page extraction (delegated to manga_extractors) ─────────────────────────
def chapter_pages(chapter_url: str, *, proxy_url: Optional[str] = None) -> dict:
    """Pull the image URLs from a chapter URL (any supported VN site)."""
    try:
        return extract_chapter_images(chapter_url, proxy_url=proxy_url)
    except ExtractError as e:
        raise

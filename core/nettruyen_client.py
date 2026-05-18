"""NetTruyen catalog client.

Mirrors the public reader website so the tool can:

    1. Search by free-text title across NetTruyen mirrors.
    2. Open a manga details page → list its chapters.
    3. Resolve chapter pages (delegated to ``manga_extractors``).

The site has many domain mirrors that share the same Codeigniter PHP
template. We default to the most stable mirror and let users override
via ``base_url``.
"""
from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from typing import List, Optional

from core.manga_extractors import (
    USER_AGENT,
    _ABS_URL_RE,
    _abs,
    _attrs,
    _fetch_html,
    ExtractError,
)


# Mirrors known to be alive at the time of writing. Order matters — the
# first one is the default. Adjust via /api/story/nettruyen/config.
MIRRORS = [
    "https://www.nettruyenvio.com",
    "https://nettruyenvio.com",
    "https://www.nettruyen1z1.com",
    "https://www.nettruyenviet.com",
]


# ── Data classes ────────────────────────────────────────────────────────────
@dataclass
class NTManga:
    id: str               # absolute URL (acts as our id)
    title: str
    alt_title: str = ""
    cover_url: str = ""
    chapter_latest: str = ""
    description: str = ""
    status: str = ""
    authors: List[str] = field(default_factory=list)
    genres: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class NTChapter:
    id: str               # chapter URL
    chapter: str
    title: str = ""
    publish_at: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ── Search ──────────────────────────────────────────────────────────────────
_CARD_RE = re.compile(
    r'<div[^>]+class="[^"]*\bitem\b[^"]*"[^>]*>(?P<body>.*?)</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
_FIGURE_RE = re.compile(r'<figure[^>]*>(.*?)</figure>', re.IGNORECASE | re.DOTALL)
_A_RE = re.compile(r'<a\b[^>]*href=(["\'])(?P<href>[^"\']+)\1[^>]*>(?P<text>.*?)</a>', re.IGNORECASE | re.DOTALL)
_IMG_RE = re.compile(r'<img\b[^>]*>', re.IGNORECASE)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _pick_search_url(base: str, keyword: str, *, page: int = 1) -> str:
    qs = urllib.parse.urlencode({"keyword": keyword})
    suffix = f"?{qs}"
    if page > 1:
        suffix = f"?page={page}&{qs}"
    return f"{base.rstrip('/')}/tim-truyen{suffix}"


def search(
    keyword: str,
    *,
    base_url: Optional[str] = None,
    proxy_url: Optional[str] = None,
    page: int = 1,
    timeout: int = 25,
) -> List[NTManga]:
    """Search NetTruyen by title. Returns a list of ``NTManga`` summaries."""
    if not keyword.strip():
        return []
    last_err: Optional[Exception] = None
    bases = [base_url] if base_url else list(MIRRORS)
    for base in bases:
        try:
            url = _pick_search_url(base, keyword, page=page)
            page_html = _fetch_html(url, proxy_url=proxy_url, timeout=timeout)
            items = _parse_search(page_html, base=base)
            if items or "Không có truyện" in page_html:
                return items
        except (ExtractError, urllib.error.HTTPError, urllib.error.URLError) as e:
            last_err = e
            continue
    if last_err:
        raise ExtractError(
            f"Không thể truy cập NetTruyen ({len(bases)} mirror đều lỗi). "
            f"Lỗi cuối: {last_err}"
        )
    return []


def _parse_search(page_html: str, *, base: str) -> List[NTManga]:
    """Parse a NetTruyen search-results / browse page.

    Layout: each manga is a ``<div class="item">`` containing
    ``<figure>`` (cover + title link) and a list of latest chapters.
    """
    out: List[NTManga] = []
    for m in _CARD_RE.finditer(page_html):
        body = m.group("body")
        # Title + manga URL
        a_match = _A_RE.search(body)
        if not a_match:
            continue
        manga_url = _abs(a_match.group("href"), base)
        title = html.unescape(_strip_tags(a_match.group("text"))).strip()
        if not title or "/truyen-tranh/" not in manga_url:
            continue
        # Cover image
        cover = ""
        img_match = _IMG_RE.search(body)
        if img_match:
            attrs = _attrs(img_match.group(0))
            cover = (
                attrs.get("data-original")
                or attrs.get("data-src")
                or attrs.get("src")
                or ""
            )
            cover = _abs(cover, base)
        # Latest chapter (first ``<a class="chapter"`` after the figure, optional)
        latest = ""
        ch_match = re.search(
            r'<a[^>]+class="[^"]*\b(?:chapter|chap)\b[^"]*"[^>]*>(.*?)</a>',
            body, re.IGNORECASE | re.DOTALL,
        )
        if ch_match:
            latest = html.unescape(_strip_tags(ch_match.group(1)))
        out.append(NTManga(
            id=manga_url,
            title=title,
            cover_url=cover,
            chapter_latest=latest,
        ))
    return _dedupe_manga(out)


def _dedupe_manga(items: List[NTManga]) -> List[NTManga]:
    seen = set()
    uniq: List[NTManga] = []
    for it in items:
        if it.id in seen:
            continue
        seen.add(it.id)
        uniq.append(it)
    return uniq


# ── Manga details + chapter list ────────────────────────────────────────────
def get_manga(
    manga_url: str,
    *,
    proxy_url: Optional[str] = None,
    timeout: int = 25,
) -> NTManga:
    """Fetch a manga's details page and extract all metadata + chapters."""
    if not manga_url.startswith(("http://", "https://")):
        raise ExtractError("manga_url phải là URL đầy đủ.")
    page_html = _fetch_html(manga_url, proxy_url=proxy_url, timeout=timeout)

    title = ""
    m = re.search(r'<h1[^>]*class="[^"]*title-detail[^"]*"[^>]*>(.*?)</h1>',
                  page_html, re.IGNORECASE | re.DOTALL)
    if m:
        title = html.unescape(_strip_tags(m.group(1))).strip()
    if not title:
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                      page_html, re.IGNORECASE)
        if m:
            title = html.unescape(m.group(1)).strip()

    alt = ""
    m = re.search(r'<h2[^>]*class="[^"]*other-name[^"]*"[^>]*>(.*?)</h2>',
                  page_html, re.IGNORECASE | re.DOTALL)
    if m:
        alt = html.unescape(_strip_tags(m.group(1))).strip()

    cover = ""
    m = re.search(r'<div[^>]+class="[^"]*col-image[^"]*"[^>]*>.*?<img\b[^>]*>',
                  page_html, re.IGNORECASE | re.DOTALL)
    if m:
        img_attrs = _attrs(_IMG_RE.search(m.group(0)).group(0))
        cover = _abs(
            img_attrs.get("data-original")
            or img_attrs.get("data-src")
            or img_attrs.get("src") or "",
            manga_url,
        )
    if not cover:
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                      page_html, re.IGNORECASE)
        if m:
            cover = m.group(1).strip()

    description = ""
    m = re.search(
        r'<div[^>]+class="[^"]*\bdetail-content\b[^"]*"[^>]*>(.*?)</div>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    if m:
        description = html.unescape(_strip_tags(m.group(1))).strip()
    if not description:
        m = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            page_html, re.IGNORECASE,
        )
        if m:
            description = html.unescape(m.group(1)).strip()

    status = ""
    authors: List[str] = []
    genres: List[str] = []
    info_block = re.search(
        r'<ul[^>]+class="[^"]*list-info[^"]*"[^>]*>(.*?)</ul>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    if info_block:
        block = info_block.group(1)
        # Each <li class="row">: <p class="name">Field</p><p class="col">Value</p>
        for li in re.findall(r'<li\b[^>]*>(.*?)</li>', block, re.IGNORECASE | re.DOTALL):
            name_m = re.search(r'<p[^>]*class="[^"]*\bname\b[^"]*"[^>]*>(.*?)</p>',
                               li, re.IGNORECASE | re.DOTALL)
            val_m = re.search(r'<p[^>]*class="[^"]*\bcol-xs-8\b[^"]*"[^>]*>(.*?)</p>',
                              li, re.IGNORECASE | re.DOTALL)
            if not (name_m and val_m):
                continue
            field = _strip_tags(name_m.group(1)).lower()
            value_html = val_m.group(1)
            value = _strip_tags(value_html).strip(" \t\r\n,")
            if not value:
                continue
            if "tác giả" in field:
                authors = [a.strip() for a in re.split(r",|/", value) if a.strip()]
            elif "thể loại" in field:
                genres = [g.strip() for g in re.split(r",", value) if g.strip()]
            elif "tình trạng" in field:
                status = value

    chapters = _parse_chapter_list(page_html, base=manga_url)

    summary = NTManga(
        id=manga_url,
        title=title or "(không có tiêu đề)",
        alt_title=alt,
        cover_url=cover,
        description=description,
        status=status,
        authors=authors,
        genres=genres,
    )
    # Stash chapters on the dict (caller can read via to_dict)
    setattr(summary, "_chapters", chapters)
    return summary


def list_chapters(
    manga_url: str,
    *,
    proxy_url: Optional[str] = None,
    timeout: int = 25,
) -> List[NTChapter]:
    """Convenience helper: load the manga page and pull chapters out."""
    info = get_manga(manga_url, proxy_url=proxy_url, timeout=timeout)
    return list(getattr(info, "_chapters", []) or [])


def _parse_chapter_list(page_html: str, *, base: str) -> List[NTChapter]:
    """Parse the chapter list on a manga details page.

    NetTruyen ships chapters inside ``<div id="nt_listchapter"> ... <ul> <li> ...``.
    """
    block = re.search(
        r'<div[^>]+id="nt_listchapter"[^>]*>(.*?)</div>\s*</div>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    if not block:
        # Fallback: grab any <a class="chapter" href="...">
        block_html = page_html
    else:
        block_html = block.group(1)

    out: List[NTChapter] = []
    li_re = re.compile(r'<li\b[^>]*>(.*?)</li>', re.IGNORECASE | re.DOTALL)
    for li in li_re.findall(block_html):
        a_match = _A_RE.search(li)
        if not a_match:
            continue
        href = _abs(a_match.group("href"), base)
        if "/truyen-tranh/" not in href:
            continue
        title = html.unescape(_strip_tags(a_match.group("text"))).strip()
        # Extract a numeric "chapter" out of the title (e.g. "Chapter 1180.5")
        ch = ""
        nm = re.search(r"(\d+(?:[.,]\d+)?)", title)
        if nm:
            ch = nm.group(1).replace(",", ".")
        publish_at = ""
        date_m = re.search(
            r'<div[^>]+class="[^"]*col-xs-4[^"]*"[^>]*>(.*?)</div>',
            li, re.IGNORECASE | re.DOTALL,
        )
        if date_m:
            publish_at = _strip_tags(date_m.group(1)).strip()
        out.append(NTChapter(id=href, chapter=ch, title=title, publish_at=publish_at))
    # Latest first by default — preserve site order.
    return out

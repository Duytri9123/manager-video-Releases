"""Manga chapter image extractors.

Take a chapter URL from a popular manga reader site → return the ordered
list of page image URLs. Built for the common "I already have the chapter
URL, just convert it to a video" workflow.

Site-specific extractors implemented:

    - nettruyen*    (nettruyen, nettruyenviet, nettruyenvio, nettruyen1z1, ...)
    - blogtruyen.vn / .com
    - truyenqq*     (truyenqqto, truyenqqviet, truyenqqvip, ...)
    - truyentranh*  (truyentranh.vn, truyentranhtuan.com, ...)
    - generic       — fallback that sniffs sequenced image URLs from any page

All extractors are pure stdlib (urllib + re) so the module has no extra
dependencies. They're intentionally tolerant: every site changes its
markup periodically, so we layer multiple selectors and fall back to the
generic extractor if everything else fails.
"""
from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ExtractError(RuntimeError):
    """Friendly error wrapper for any extractor failure."""


# ── HTTP fetch (with anti-bot headers) ──────────────────────────────────────
def _fetch_html(
    url: str,
    *,
    timeout: int = 25,
    proxy_url: Optional[str] = None,
) -> str:
    handlers: list = []
    if proxy_url:
        scheme = proxy_url.split("://", 1)[0]
        handlers.append(urllib.request.ProxyHandler({scheme: proxy_url}))
    opener = (
        urllib.request.build_opener(*handlers)
        if handlers
        else urllib.request.build_opener()
    )
    parsed = urllib.parse.urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "vi,en-US;q=0.7,en;q=0.3"),
        ("Referer", referer),
    ]
    try:
        with opener.open(url, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read(6_000_000)
        return body.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        raise ExtractError(f"HTTP {e.code} khi tải {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ExtractError(f"Lỗi mạng khi tải {url}: {e}") from e


# ── Common helpers ──────────────────────────────────────────────────────────
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"""(?P<name>[a-zA-Z][a-zA-Z0-9_-]*)\s*=\s*(?:"(?P<v1>[^"]*)"|'(?P<v2>[^']*)'|(?P<v3>[^\s>]+))""",
)
_ABS_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|avif|bmp)(?:\?.*)?$", re.IGNORECASE)


def _attrs(tag: str) -> dict:
    out: dict = {}
    for m in _ATTR_RE.finditer(tag):
        v = m.group("v1")
        if v is None:
            v = m.group("v2")
        if v is None:
            v = m.group("v3") or ""
        out[m.group("name").lower()] = html.unescape(v)
    return out


def _abs(url: str, base: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        scheme = urllib.parse.urlparse(base).scheme or "https"
        return f"{scheme}:{url}"
    if _ABS_URL_RE.match(url):
        return url
    return urllib.parse.urljoin(base, url)


def _looks_like_page_image(url: str) -> bool:
    """Heuristic: chapter pages are big, sequenced JPEG/WebP files. Skip
    icons, ad pixels, sprites, and avatars."""
    if not url:
        return False
    u = url.lower()
    if any(bad in u for bad in (
        "/avatar", "/sprite", "/logo", "/banner", "/icon",
        "google-analytics", "doubleclick", "facebook.com/tr",
        "blank.gif", "loading.gif", "1x1.png", "spacer.gif",
    )):
        return False
    if not _IMG_EXT_RE.search(u):
        # Many sites put image into ``?url=...`` style proxy params; allow if it
        # contains a chapter-image-ish keyword
        if not any(k in u for k in ("/manga/", "/chapter/", "/comic/", "/upload", "/cdn-cgi/image")):
            return False
    return True


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _all_imgs(page_html: str, base: str) -> List[dict]:
    """Return [{src, alt, class, data-*...}] for every <img> tag in order."""
    out: List[dict] = []
    for m in _IMG_TAG_RE.finditer(page_html):
        a = _attrs(m.group(0))
        # Pick the best URL out of common lazy-load attributes
        src = (
            a.get("data-original")
            or a.get("data-src")
            or a.get("data-cfsrc")
            or a.get("data-lazy-src")
            or a.get("data-srcset")
            or a.get("data-url")
            or a.get("src")
            or ""
        ).strip()
        if not src:
            continue
        # ``srcset`` style returns "url 1x, url2 2x" — keep the first URL
        if " " in src and "," in src:
            src = src.split(",", 1)[0].split(" ", 1)[0]
        a["resolved"] = _abs(src, base)
        out.append(a)
    return out


# ── Site-specific extractors ────────────────────────────────────────────────
def _extract_nettruyen(page_html: str, base: str) -> List[str]:
    # NetTruyen: <div class="reading-detail box_doc"> ... <img class="lazy" data-original=...>
    block = re.search(
        r'<div[^>]+class="[^"]*(?:reading-detail|page-chapter)[^"]*"[^>]*>(.*?)</div>\s*</div>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    chunk = block.group(1) if block else page_html
    urls = [a["resolved"] for a in _all_imgs(chunk, base) if _looks_like_page_image(a.get("resolved", ""))]
    return _dedupe_keep_order(urls)


def _extract_blogtruyen(page_html: str, base: str) -> List[str]:
    # BlogTruyen: <article id="content"> ... <img src=...> (no lazy load)
    block = re.search(
        r'<article[^>]*id="content"[^>]*>(.*?)</article>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    chunk = block.group(1) if block else page_html
    urls = [a["resolved"] for a in _all_imgs(chunk, base) if _looks_like_page_image(a.get("resolved", ""))]
    return _dedupe_keep_order(urls)


def _extract_truyenqq(page_html: str, base: str) -> List[str]:
    # TruyenQQ: <div class="page-chapter"> <img src=...>
    blocks = re.findall(
        r'<div[^>]+class="[^"]*page-chapter[^"]*"[^>]*>.*?</div>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    urls: List[str] = []
    for b in blocks:
        for a in _all_imgs(b, base):
            res = a.get("resolved", "")
            if _looks_like_page_image(res):
                urls.append(res)
    if not urls:
        # Some skins use <picture><source data-srcset=...><img>
        urls = [a["resolved"] for a in _all_imgs(page_html, base)
                if _looks_like_page_image(a.get("resolved", ""))]
    return _dedupe_keep_order(urls)


def _extract_truyentranh(page_html: str, base: str) -> List[str]:
    # truyentranh.vn / truyentranhtuan.com — images inside <div id="ChapterContent">
    block = re.search(
        r'<div[^>]+id="(?:ChapterContent|chapterContent)"[^>]*>(.*?)</div>\s*</section>',
        page_html, re.IGNORECASE | re.DOTALL,
    )
    chunk = block.group(1) if block else page_html
    urls = [a["resolved"] for a in _all_imgs(chunk, base) if _looks_like_page_image(a.get("resolved", ""))]
    return _dedupe_keep_order(urls)


def _extract_mangabuddy(page_html: str, base: str) -> List[str]:
    # MangaBuddy / MangaKomi pattern: a JS array literal of image URLs.
    m = re.search(r'var\s+chapImages\s*=\s*"([^"]+)"', page_html)
    if m:
        return _dedupe_keep_order(m.group(1).split(","))
    return []


def _extract_generic(page_html: str, base: str) -> List[str]:
    """Fallback: pick the longest run of images sharing a common path prefix.

    Manga readers almost always store chapter pages in one CDN folder with
    sequential filenames. Group images by their directory; the largest
    group is the chapter, anything else is layout chrome.
    """
    candidates = [
        a["resolved"] for a in _all_imgs(page_html, base)
        if _looks_like_page_image(a.get("resolved", ""))
    ]
    candidates = _dedupe_keep_order(candidates)
    if len(candidates) <= 6:
        return candidates  # not enough to filter; return as-is

    by_dir: dict[str, list[str]] = {}
    for u in candidates:
        try:
            path = urllib.parse.urlparse(u).path
            d = path.rsplit("/", 1)[0]
        except Exception:
            d = ""
        by_dir.setdefault(d, []).append(u)
    # Pick the directory bucket with the most images
    best_dir = max(by_dir, key=lambda d: len(by_dir[d]))
    if len(by_dir[best_dir]) >= 3:
        return by_dir[best_dir]
    return candidates


@dataclass
class Site:
    id: str
    label: str
    host_substrings: tuple
    extract: Callable[[str, str], List[str]]


SITES: List[Site] = [
    Site("nettruyen", "NetTruyen",     ("nettruyen", "nettruyenviet", "nettruyenvio", "nettruyen1z1"), _extract_nettruyen),
    Site("blogtruyen", "BlogTruyen",   ("blogtruyen.vn", "blogtruyen.com"), _extract_blogtruyen),
    Site("truyenqq",  "TruyenQQ",      ("truyenqq",), _extract_truyenqq),
    Site("truyentranh", "TruyenTranh", ("truyentranh.vn", "truyentranhtuan", "truyentranhlh"), _extract_truyentranh),
    Site("mangabuddy", "MangaBuddy / MangaKomi", ("mangabuddy", "mangakomi", "mangaclash", "mangaowl"), _extract_mangabuddy),
]


def detect_site(url: str) -> Optional[Site]:
    host = urllib.parse.urlparse(url).netloc.lower()
    for s in SITES:
        for needle in s.host_substrings:
            if needle in host:
                return s
    return None


# ── Public entry point ──────────────────────────────────────────────────────
def extract_chapter_images(
    url: str,
    *,
    proxy_url: Optional[str] = None,
    timeout: int = 25,
) -> dict:
    """Fetch ``url`` and return image URLs of the chapter.

    Returns::

        {
            "site":   "nettruyen" | "generic" | ...,
            "label":  "NetTruyen",
            "title":  "<og:title or <title> from page>",
            "pages":  ["https://...", ...],
            "page_count": 30,
            "source_url": "<original url>",
        }
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ExtractError("URL không hợp lệ — phải bắt đầu bằng http(s)://.")
    page_html = _fetch_html(url, proxy_url=proxy_url, timeout=timeout)

    site = detect_site(url)
    pages: List[str] = []
    if site:
        try:
            pages = site.extract(page_html, url)
        except Exception:
            pages = []
    if not pages:
        pages = _extract_generic(page_html, url)
    pages = [p for p in pages if p and _ABS_URL_RE.match(p)]
    pages = _dedupe_keep_order(pages)

    if not pages:
        raise ExtractError(
            "Không tìm được ảnh chương trong trang. "
            "Trang có thể chặn bot hoặc đổi cấu trúc — thử trang khác."
        )

    # Try to grab the chapter title for nicer downstream rendering
    title = ""
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                  page_html, re.IGNORECASE)
    if m:
        title = html.unescape(m.group(1)).strip()
    if not title:
        m = re.search(r"<title>([^<]+)</title>", page_html, re.IGNORECASE | re.DOTALL)
        if m:
            title = html.unescape(m.group(1)).strip()

    return {
        "site": site.id if site else "generic",
        "label": site.label if site else "Generic",
        "title": title,
        "pages": pages,
        "page_count": len(pages),
        "source_url": url,
    }

"""Web search + page-fetch helpers used for realtime
questions ("tin tức mới nhất", "giá vàng hôm nay", ...).

Primary path: Gemini grounding search.
Fallback path: a no-deps Google News RSS scrape.

Returns shape:
  [{title, url, snippet, published, source}]
"""
from __future__ import annotations

import gzip
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# Cache results for 5 minutes so repeated questions don't keep hammering
# upstream. Keyed on (backend, query, lang).
_CACHE: Dict[Tuple[str, str, str], Tuple[float, list]] = {}
_CACHE_TTL = 300.0
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ── HTTP helper for the RSS fallback ──────────────────────────────────────
def _http_get(url: str, *, timeout: int = 8, headers: Optional[Dict[str, str]] = None) -> bytes:
    h = {"User-Agent": _UA, "Accept-Language": "vi,en;q=0.8", "Accept-Encoding": "gzip"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except OSError:
                pass
        return raw


_TAG_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = _TAG_RX.sub(" ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
           .replace("&quot;", '"').replace("&#39;", "'")
           .replace("&lt;", "<").replace("&gt;", ">"))
    return _WS_RX.sub(" ", s).strip()


def _hostname(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""


# ── Google News RSS fallback ──────────────────────────────────────────────
def google_news(query: str, *, lang: str = "vi", region: str = "VN", limit: int = 8) -> List[Dict[str, str]]:
    """Search Google News RSS. `lang` ∈ {vi, en, ...}."""
    key = ("gnews", query, f"{lang}:{region}")
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1][:limit]

    qs = urllib.parse.urlencode({
        "q": query, "hl": lang, "gl": region, "ceid": f"{region}:{lang}",
    })
    url = f"https://news.google.com/rss/search?{qs}"
    try:
        data = _http_get(url, timeout=8)
    except (urllib.error.URLError, TimeoutError):
        return []

    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    for it in root.findall("./channel/item")[: max(limit, 12)]:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        desc = _strip_html(it.findtext("description") or "")
        source = ""
        if " - " in title:
            *_, source = title.rsplit(" - ", 1)
        items.append({
            "title": title, "url": link, "snippet": desc[:280],
            "published": pub, "source": source,
        })
    _CACHE[key] = (time.time(), items)
    return items[:limit]


# ── Gemini Google Search grounding ────────────────────────────────────────
def _get_gemini_key() -> Optional[str]:
    """Lấy Gemini API key từ config.yml hoặc env."""
    import os
    try:
        # Lazy import to avoid circular deps at module level
        from core_app import load_cfg
        cfg = load_cfg()
        key = ((cfg.get("gemini_video") or {}).get("api_key") or "").strip()
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "").strip() or None


def search_via_gemini(
    query: str, *, lang: str = "vi", limit: int = 6,
    model: str = "",
) -> List[Dict[str, str]]:
    """Dùng Gemini + Google Search grounding để tìm kiếm web.

    Gemini sẽ tự gọi Google Search, tổng hợp kết quả, và trả về cùng
    groundingMetadata chứa các nguồn tham chiếu.

    Ưu điểm:
      - Miễn phí (dùng chung key Gemini)
      - Tìm được mọi thứ trên Google (không chỉ tin tức)
      - Trả về kết quả đã tổng hợp + nguồn trích dẫn
    """
    api_key = _get_gemini_key()
    if not api_key:
        return []

    cache_key = ("gemini", query, lang)
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1][:limit]

    # Dùng model nhẹ nhất cho search (ít bị rate limit hơn)
    if not model:
        model = "gemini-3.6-flash"

    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": query}]},
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
        },
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Retry once on 503 (rate limit)
    data = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            break
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt == 0:
                time.sleep(2)
                continue
            return []
        except Exception:
            return []

    if not data:
        return []

    candidates = data.get("candidates") or []
    if not candidates:
        return []

    # Extract grounding metadata (search results used by Gemini)
    grounding = candidates[0].get("groundingMetadata") or {}
    chunks = grounding.get("groundingChunks") or []
    support = grounding.get("groundingSupports") or []
    search_queries = grounding.get("webSearchQueries") or []

    # Lấy text content từ Gemini response (đây là tổng hợp thực tế)
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    full_text = "".join(p.get("text", "") for p in parts).strip()

    results: List[Dict[str, str]] = []

    # groundingChunks chứa các nguồn web mà Gemini đã dùng
    for chunk in chunks[:limit]:
        web = chunk.get("web") or {}
        title = (web.get("title") or "").strip()
        uri = (web.get("uri") or "").strip()
        if uri:
            results.append({
                "title": title or _hostname(uri),
                "url": uri,
                "snippet": "",  # sẽ fill bên dưới
                "published": "",
                "source": _hostname(uri),
            })

    # Fill snippet từ groundingSupports (chứa text trích dẫn từ nguồn)
    for sup in support:
        segment = (sup.get("segment") or {}).get("text", "")
        indices = sup.get("groundingChunkIndices") or []
        if segment:
            for idx in indices:
                if 0 <= idx < len(results) and not results[idx]["snippet"]:
                    results[idx]["snippet"] = segment[:280]
                    break

    # Nếu không có groundingChunks, dùng full_text làm kết quả duy nhất
    if not results and full_text:
        results.append({
            "title": f"Kết quả: {query[:50]}",
            "url": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
            "snippet": full_text[:500],
            "published": "",
            "source": "Google (via Gemini)",
        })

    # Fill snippet cho các result chưa có từ full_text
    if full_text:
        for r in results:
            if not r["snippet"]:
                r["snippet"] = full_text[:200]

    _CACHE[cache_key] = (time.time(), results)
    return results[:limit]


# ── Public entry point ────────────────────────────────────────────────────
def search(
    query: str, *, kind: str = "auto", lang: str = "vi", region: str = "VN",
    limit: int = 6, endpoint: Optional[str] = None, api_key: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Top-level helper: try Gemini grounding first, fall back to Google News RSS.

    `kind` ∈ {auto, news, web}.
    """
    q = (query or "").strip()
    if not q:
        return []
    # 1. Gemini + Google Search grounding (free, trực tiếp)
    try:
        results = search_via_gemini(q, lang=lang, limit=limit)
        if results:
            return results
    except Exception:
        pass
    # 2. Google News RSS (fallback cuối, chỉ tin tức)
    if kind == "news" or (kind == "auto" and _looks_like_news(q)):
        results = google_news(q, lang=lang, region=region, limit=limit)
        if results:
            return results
    return []


_NEWS_HINT_RX = re.compile(
    r"(tin\s+t[uứư]c|m[oơ]i\s+nh[aâấ]t|h[oô]m\s+nay|h[oô]m\s+qua|tu[aâ]n\s+n[aà]y|"
    r"th[aá]ng\s+n[aà]y|n[aă]m\s+nay|news|latest|today|yesterday|this\s+week|"
    r"current|now|breaking|"
    # Thêm pattern cho tìm kiếm chung (giá cả, thời tiết, sự kiện...)
    r"gi[aá]\s+|th[oờ]i\s+ti[eế]t|t[iỉ]\s+gi[aá]|bao\s+nhi[eê]u|"
    r"l[aà]\s+g[iì]|l[aà]\s+ai|[oở]\s+đ[aâ]u|khi\s+n[aà]o|"
    r"price|weather|how\s+much|what\s+is|who\s+is|where|when|"
    r"search|t[iì]m|tra\s+c[uứ]u|google)",
    re.IGNORECASE,
)


def _looks_like_news(query: str) -> bool:
    """Detect nếu query cần web search (tin tức, thông tin thực tế, giá cả...)."""
    return bool(_NEWS_HINT_RX.search(query))


def format_for_prompt(results: List[Dict[str, str]], *, max_items: int = 6) -> str:
    """Render results as a numbered list the LLM can read and cite."""
    if not results:
        return "(không tìm được kết quả)"
    out = []
    for i, r in enumerate(results[:max_items], 1):
        title = r.get("title") or ""
        url = r.get("url") or ""
        snip = r.get("snippet") or ""
        meta_bits = []
        if r.get("source"):
            meta_bits.append(r["source"])
        if r.get("published"):
            meta_bits.append(r["published"])
        meta = (" · ".join(meta_bits)) if meta_bits else ""
        out.append(f"[{i}] {title}\n    {url}\n    {meta}\n    {snip}")
    return "\n\n".join(out)

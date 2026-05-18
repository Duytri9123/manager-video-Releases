"""Web search + page-fetch helpers used by the chatbot for realtime
questions ("tin tức mới nhất", "giá vàng hôm nay", ...).

Primary path: call 9Router's `/v1/search` endpoint (Tavily / Brave / Exa /
SearXNG / Google PSE / ... — provider-agnostic). 9Router runs locally and
the user already has API keys configured there, so we don't need any extra
keys on the toolvideo side.

Fallback path: a no-deps Google News RSS scrape, used when 9Router doesn't
have any search provider configured. This keeps the chat usable in a fresh
install where the user hasn't set up Tavily/Brave keys yet.

Both paths return the same shape:
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
_NINER_TIMEOUT = 12

# 9Router search providers we'll try in order if no specific one is
# configured. `search-combo` is 9Router's auto-fallback chain — first
# choice if the user enabled it. Otherwise we try Tavily (most polished),
# then Brave (good free tier), Serper (Google-backed), Exa (LLM-friendly),
# Linkup (deep search), and finally SearXNG (self-hosted).
_NINER_PROVIDER_FALLBACK = (
    "search-combo", "tavily", "brave-search", "serper",
    "linkup", "exa", "google-pse", "searxng", "perplexity", "youcom",
)


# ── 9Router primary path ──────────────────────────────────────────────────
def _niner_endpoint(endpoint: Optional[str], api_key: Optional[str]) -> Tuple[str, Dict[str, str]]:
    base = (endpoint or "http://localhost:20128/v1").rstrip("/")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return base, headers


def _niner_post(path: str, payload: Dict[str, Any], *,
                endpoint: Optional[str], api_key: Optional[str],
                timeout: int = _NINER_TIMEOUT) -> Tuple[int, Any]:
    base, headers = _niner_endpoint(endpoint, api_key)
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body) if body else {}
            except ValueError:
                return resp.status, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        try:
            return exc.code, json.loads(body) if body else {}
        except ValueError:
            return exc.code, body.decode("utf-8", "replace")


def _niner_list_search_providers(endpoint: Optional[str], api_key: Optional[str]) -> List[str]:
    """Hit /v1/models/web and return only webSearch-capable provider ids."""
    base, headers = _niner_endpoint(endpoint, api_key)
    req = urllib.request.Request(base + "/models/web", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_NINER_TIMEOUT) as resp:
            body = json.loads(resp.read() or b"{}")
    except Exception:
        return []
    out = []
    for it in (body.get("data") or []):
        if (it or {}).get("kind") == "webSearch":
            mid = (it or {}).get("id")
            if mid:
                # IDs are like "tavily/search" — 9Router accepts both the
                # full id and the bare provider name.
                out.append(mid.split("/", 1)[0])
    return out


_niner_provider_cache: Dict[str, Tuple[float, List[str]]] = {}


def _niner_pick_provider(endpoint: Optional[str], api_key: Optional[str]) -> Optional[str]:
    key = endpoint or "default"
    cached = _niner_provider_cache.get(key)
    if cached and (time.time() - cached[0]) < 60.0:
        avail = cached[1]
    else:
        avail = _niner_list_search_providers(endpoint, api_key)
        _niner_provider_cache[key] = (time.time(), avail)
    if not avail:
        return None
    avail_set = set(avail)
    for cand in _NINER_PROVIDER_FALLBACK:
        if cand in avail_set:
            return cand
    return avail[0]


def search_via_9router(
    query: str, *, kind: str = "auto", lang: str = "vi", region: str = "VN",
    limit: int = 6, endpoint: Optional[str] = None, api_key: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Search via 9Router's `/v1/search`. Returns [] on any failure so the
    caller can fall through to the RSS scraper."""
    provider = _niner_pick_provider(endpoint, api_key)
    if not provider:
        return []
    payload: Dict[str, Any] = {
        "model": provider,
        "query": query,
        "max_results": limit,
        "search_type": "news" if (kind == "news" or _looks_like_news(query)) else "web",
    }
    if region:
        payload["country"] = region.lower()
    if lang:
        payload["language"] = lang
    status, body = _niner_post("/search", payload, endpoint=endpoint, api_key=api_key)
    if status >= 400 or not isinstance(body, dict):
        return []
    out: List[Dict[str, str]] = []
    for r in (body.get("results") or [])[:limit]:
        if not isinstance(r, dict):
            continue
        out.append({
            "title": (r.get("title") or "").strip(),
            "url": (r.get("url") or "").strip(),
            "snippet": (r.get("snippet") or r.get("content") or "").strip()[:280],
            "published": (r.get("published_at") or "").strip(),
            "source": (r.get("display_url") or _hostname(r.get("url") or "")),
        })
    return [r for r in out if r["title"] and r["url"]]


def fetch_via_9router(
    url: str, *, fmt: str = "markdown", max_chars: int = 4000,
    endpoint: Optional[str] = None, api_key: Optional[str] = None,
) -> str:
    """Fetch a URL → readable text via 9Router /v1/web/fetch. Empty string
    on any failure."""
    # 9Router expects a full provider id. Try common ones in order — the
    # first one available will succeed. We don't bother enumerating /v1/models/web
    # for every fetch; instead call jina-reader (free, fastest) first.
    for provider in ("fetch-combo", "jina-reader", "firecrawl", "tavily", "exa"):
        payload = {"model": provider, "url": url, "format": fmt}
        if max_chars:
            payload["max_characters"] = max_chars
        status, body = _niner_post("/web/fetch", payload, endpoint=endpoint, api_key=api_key)
        if status < 400 and isinstance(body, dict):
            data = body.get("data") or body
            content = (data.get("content") or {}) if isinstance(data, dict) else {}
            text = content.get("text") if isinstance(content, dict) else None
            if text:
                return text[:max_chars] if max_chars else text
    return ""


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


# ── Public entry point ────────────────────────────────────────────────────
def search(
    query: str, *, kind: str = "auto", lang: str = "vi", region: str = "VN",
    limit: int = 6, endpoint: Optional[str] = None, api_key: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Top-level helper: try 9Router first, fall back to Google News RSS.

    `kind` ∈ {auto, news, web}.
    """
    q = (query or "").strip()
    if not q:
        return []
    # Try 9Router /v1/search — instant if the user has Tavily/Brave/etc.
    try:
        results = search_via_9router(
            q, kind=kind, lang=lang, region=region, limit=limit,
            endpoint=endpoint, api_key=api_key,
        )
        if results:
            return results
    except Exception:
        pass
    # Fall back to Google News RSS (no auth required, news only).
    if kind == "news" or (kind == "auto" and _looks_like_news(q)):
        results = google_news(q, lang=lang, region=region, limit=limit)
        if results:
            return results
    return []


_NEWS_HINT_RX = re.compile(
    r"(tin\s+t[uứư]c|m[oơ]i\s+nh[aâấ]t|h[oô]m\s+nay|h[oô]m\s+qua|tu[aâ]n\s+n[aà]y|"
    r"th[aá]ng\s+n[aà]y|n[aă]m\s+nay|news|latest|today|yesterday|this\s+week|"
    r"current|now|breaking)",
    re.IGNORECASE,
)


def _looks_like_news(query: str) -> bool:
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

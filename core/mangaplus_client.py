"""MangaPlus (jumpg-webapi.tokyo-cdn.com) client.

MangaPlus is the official Shueisha reader for One Piece, Naruto, JJK, ...
The mobile/web app talks to a Protobuf API that returns chapter image
URLs together with a per-image XOR encryption key. We decode the Protobuf
manually (no extra deps) and decrypt images on the fly when the browser
asks for them.

This is the same approach used by open-source readers like Mihon /
Tachiyomi — MangaPlus chapters are intentionally **free and official**,
the encryption is purely client-side obfuscation.

Endpoints used::

    GET https://jumpg-webapi.tokyo-cdn.com/api/manga_viewer
        ?chapter_id=<id>&split=yes&img_quality=high

URL → JPEG flow:

    1. Resolve chapter_id (from a MangaDex external_url like
       ``https://mangaplus.shueisha.co.jp/viewer/<id>``).
    2. POST/GET protobuf → list of (image_url, encryption_key).
    3. For each image_url we generate a same-origin URL on our backend:
       ``/api/story/mangaplus/image?url=<encoded>&key=<hex>``.
    4. Backend fetches the encrypted bytes, XOR-decrypts with the key,
       streams JPEG back to the browser.
"""
from __future__ import annotations

import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, List, Optional, Tuple


WEBAPI_BASE = "https://jumpg-webapi.tokyo-cdn.com"
USER_AGENT = "Mozilla/5.0 (compatible; DuyTrisManga/1.0)"


class MangaPlusError(RuntimeError):
    """Friendly error for any MangaPlus protocol failure."""


# ── Tiny protobuf wire-format decoder ───────────────────────────────────────
# We only need length-delimited strings and embedded messages. The parser
# walks the buffer and emits ``(tag, wire_type, value)`` tuples; we then
# recursively scan for fields that look like URLs / 64-char hex keys.

def _read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 63:
            raise MangaPlusError("Protobuf varint too long")
    raise MangaPlusError("Protobuf varint truncated")


def _walk_strings(buf: bytes) -> List[bytes]:
    """Recursively yield every length-delimited (wire_type=2) bytes value
    in the message. We don't care about field numbers — pairing happens
    later by content (URL + hex key always come next to each other in
    MangaPlus' MangaPage proto)."""
    out: List[bytes] = []
    pos = 0
    while pos < len(buf):
        try:
            tag, pos = _read_varint(buf, pos)
        except Exception:
            break
        wire_type = tag & 0x7
        if wire_type == 0:                        # varint
            try:
                _, pos = _read_varint(buf, pos)
            except Exception:
                break
        elif wire_type == 1:                      # 64-bit fixed
            pos += 8
        elif wire_type == 2:                      # length-delimited
            try:
                length, pos = _read_varint(buf, pos)
            except Exception:
                break
            if pos + length > len(buf) or length < 0:
                break
            chunk = buf[pos: pos + length]
            pos += length
            out.append(chunk)
            # Also try to recurse into the chunk in case it's an embedded
            # message containing more strings.
            try:
                inner = _walk_strings(chunk)
                out.extend(inner)
            except Exception:
                pass
        elif wire_type == 5:                      # 32-bit fixed
            pos += 4
        else:                                     # unknown / group
            break
    return out


_HEX_KEY_RE = re.compile(rb"^[0-9a-fA-F]{16,}$")


def _extract_pages(blob: bytes) -> List[Tuple[str, str]]:
    """Pair each MangaPlus image URL with its encryption key.

    The MangaPage proto serialises ``image_url`` (field 1) followed by the
    ``encryption_key`` (field 5). After ``_walk_strings`` flattens the
    tree, those two appear as adjacent entries: a URL string starting
    with ``https://`` followed by a hex string.
    """
    strings = _walk_strings(blob)
    decoded: List[str] = []
    for s in strings:
        try:
            decoded.append(s.decode("utf-8"))
        except UnicodeDecodeError:
            continue

    pages: List[Tuple[str, str]] = []
    for i, s in enumerate(decoded):
        if not (s.startswith("http://") or s.startswith("https://")):
            continue
        if "/manga_pages" not in s and "/.encrypted" not in s and "page_image" not in s and "/m/p/" not in s:
            # Heuristic: only image-CDN URLs, not banner / cover URLs
            if not re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", s, re.I):
                continue
        # Find the closest hex string AFTER this URL (within next 5 entries)
        key = ""
        for j in range(i + 1, min(i + 6, len(decoded))):
            cand = decoded[j].encode("ascii", errors="ignore")
            if _HEX_KEY_RE.match(cand):
                key = decoded[j]
                break
        pages.append((s, key))
    return pages


# ── Chapter ID extraction from external URLs ────────────────────────────────
_MP_VIEWER_RE = re.compile(r"mangaplus\.shueisha\.co\.jp/viewer/(\d+)")
_MP_TITLES_RE = re.compile(r"mangaplus\.shueisha\.co\.jp/titles/(\d+)")


def chapter_id_from_url(url: str) -> Optional[str]:
    """Pull the numeric chapter id out of any MangaPlus viewer URL."""
    if not url:
        return None
    m = _MP_VIEWER_RE.search(url)
    if m:
        return m.group(1)
    return None


def title_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = _MP_TITLES_RE.search(url)
    if m:
        return m.group(1)
    return None


# ── Public: fetch chapter pages ─────────────────────────────────────────────
def _strip_hash(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("#"):
        s = s[1:]
    return s.strip()


def fetch_chapter_pages(
    chapter_id: str,
    *,
    quality: str = "high",
    proxy_url: Optional[str] = None,
    timeout: int = 25,
) -> List[Tuple[str, str]]:
    """Return a list of ``(image_url, encryption_key)`` tuples.

    Uses the JSON variant of the API to get a clean page list.
    """
    if not chapter_id:
        raise MangaPlusError("Thiếu chapter_id MangaPlus.")
    url = _api_url(
        "/api/manga_viewer",
        chapter_id=str(chapter_id),
        split="yes",
        img_quality=quality,
    )
    blob = _http_get(url, proxy_url=proxy_url, timeout=timeout)

    # JSON path
    import json as _json
    pages: List[Tuple[str, str]] = []
    try:
        data = _json.loads(blob.decode("utf-8", errors="replace"))
    except _json.JSONDecodeError:
        data = None

    if data is not None:
        pages = _flatten_json_pages(data)

    if not pages:
        # Fallback to old protobuf scanner (just in case the API ever
        # ignores the format=json hint).
        pages = _extract_pages(blob)

    if not pages:
        raise MangaPlusError(
            "Không lấy được ảnh từ MangaPlus. "
            "Có thể chương này chưa miễn phí hoặc đã bị gỡ."
        )
    return pages


def _flatten_json_pages(node) -> List[Tuple[str, str]]:
    """Pull (imageUrl, encryptionKey) pairs from a manga_viewer JSON tree."""
    out: List[Tuple[str, str]] = []

    def _walk(n):
        if isinstance(n, dict):
            url = n.get("imageUrl") or n.get("imageUrlEnglish")
            key = n.get("encryptionKey") or ""
            if isinstance(url, str) and url.startswith("http"):
                out.append((url, key if isinstance(key, str) else ""))
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)

    _walk(node)
    return out


# ── Image fetch + XOR decrypt ───────────────────────────────────────────────
def fetch_decrypted_image(
    image_url: str,
    encryption_key: str,
    *,
    proxy_url: Optional[str] = None,
    timeout: int = 30,
) -> bytes:
    """Download an encrypted MangaPlus image and XOR-decrypt it."""
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
        ("Origin", "https://mangaplus.shueisha.co.jp"),
        ("Referer", "https://mangaplus.shueisha.co.jp/"),
        ("Accept", "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"),
    ]
    try:
        with opener.open(image_url, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise MangaPlusError(f"HTTP {e.code} fetching image") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MangaPlusError(f"Network error fetching image: {e}") from e

    if not encryption_key:
        return data

    try:
        key = bytes.fromhex(encryption_key)
    except ValueError:
        raise MangaPlusError("encryption_key không phải hex hợp lệ.")
    if not key:
        return data

    out = bytearray(len(data))
    klen = len(key)
    for i, b in enumerate(data):
        out[i] = b ^ key[i % klen]
    return bytes(out)



# ══════════════════════════════════════════════════════════════════════════════
# Title catalog (search + chapter list) — uses the same protobuf API
# ══════════════════════════════════════════════════════════════════════════════
TITLE_THUMB_BASE = "https://jumpg-assets.tokyo-cdn.com"


def _get_protobuf(path: str, *, proxy_url: Optional[str] = None,
                  timeout: int = 25) -> bytes:
    url = WEBAPI_BASE + path
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
        ("Accept", "*/*"),
        ("Origin", "https://mangaplus.shueisha.co.jp"),
        ("Referer", "https://mangaplus.shueisha.co.jp/"),
    ]
    try:
        with opener.open(url, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise MangaPlusError(f"HTTP {e.code} on {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MangaPlusError(f"Network error on {url}: {e}") from e


# ── Tagged-protobuf decoder ────────────────────────────────────────────────
# We need richer parsing here than the flat ``_walk_strings`` used for
# chapter pages, because Title and Chapter messages have meaningful field
# numbers we want to preserve.

def _decode_message(buf: bytes) -> dict:
    """Decode a wire-format Protobuf message into a ``{tag: [values]}`` dict.

    Each value is one of: int (varint), float (32/64-bit fixed),
    bytes (length-delimited), or a recursively decoded dict for nested
    messages.
    """
    out: dict = {}
    pos = 0
    while pos < len(buf):
        try:
            key, pos = _read_varint(buf, pos)
        except Exception:
            break
        tag = key >> 3
        wire_type = key & 0x7
        if wire_type == 0:
            try:
                v, pos = _read_varint(buf, pos)
            except Exception:
                break
        elif wire_type == 1:
            v = struct.unpack("<d", buf[pos:pos + 8])[0]
            pos += 8
        elif wire_type == 2:
            try:
                length, pos = _read_varint(buf, pos)
            except Exception:
                break
            if pos + length > len(buf) or length < 0:
                break
            chunk = buf[pos: pos + length]
            pos += length
            # Try to interpret as a nested message; fall back to raw bytes
            try:
                inner = _decode_message(chunk)
                # Only treat as nested if it consumed everything cleanly
                # AND contains at least one tag we recognize.
                v = inner if inner else chunk
            except Exception:
                v = chunk
        elif wire_type == 5:
            v = struct.unpack("<f", buf[pos:pos + 4])[0]
            pos += 4
        else:
            break
        out.setdefault(tag, []).append(v)
    return out


def _as_str(v) -> str:
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if isinstance(v, str):
        return v
    return ""


def _find_titles(node, out: List[dict]) -> None:
    """Walk a decoded protobuf tree and collect every Title message we
    can identify. Title schema (best-effort):
        1: title_id (varint)
        2: name (string)
        3: author (string)
        4: portrait_image_url (string)
        5: landscape_image_url (string)
        6: view_count (varint)
        7: language (varint)
    """
    if isinstance(node, dict):
        # Heuristic: a message is a Title if it has a numeric field 1
        # (title_id) AND a string field 2 (name) AND a string field 4 or 5
        # that looks like an image URL.
        f1 = node.get(1, [])
        f2 = node.get(2, [])
        f4 = node.get(4, [])
        f5 = node.get(5, [])
        url_candidates = [
            _as_str(x) for x in (f4 + f5)
            if isinstance(x, (bytes, str))
        ]
        url_candidates = [u for u in url_candidates if u.startswith("http")]
        if (f1 and isinstance(f1[0], int)
                and f2 and isinstance(f2[0], (bytes, str))
                and url_candidates):
            name = _as_str(f2[0])
            if name and len(name) >= 1:
                authors = [_as_str(x) for x in node.get(3, []) if x]
                cover = url_candidates[0]
                out.append({
                    "id": str(f1[0]),
                    "title": name,
                    "authors": [a for a in authors if a],
                    "cover_url": cover,
                })
        # Recurse into every nested message field (but not back into
        # raw bytes).
        for vs in node.values():
            for v in vs:
                if isinstance(v, dict):
                    _find_titles(v, out)


def _find_chapters(node, out: List[dict]) -> None:
    """Walk a decoded protobuf tree and collect Chapter messages.

    Chapter schema (best-effort):
        1: title_id   (varint)
        2: chapter_id (varint)
        3: name       (string, e.g. "#1182")
        4: subtitle   (string, e.g. "ZAZA")
        5: thumbnail_url (string, optional)
        6: start_timestamp (varint)
        7: end_timestamp   (varint)
    """
    if isinstance(node, dict):
        f1 = node.get(1, [])
        f2 = node.get(2, [])
        f3 = node.get(3, [])
        f4 = node.get(4, [])
        f6 = node.get(6, [])
        if (f1 and isinstance(f1[0], int)
                and f2 and isinstance(f2[0], int)
                and f3 and isinstance(f3[0], (bytes, str))):
            chapter_label = _as_str(f3[0]).strip()
            subtitle = _as_str(f4[0]).strip() if f4 else ""
            ts = f6[0] if f6 and isinstance(f6[0], int) else 0
            # Filter out obvious non-chapter messages (the timestamp
            # range looks like a real recent epoch).
            if 1_400_000_000 < ts < 4_000_000_000 or chapter_label:
                out.append({
                    "id": str(f2[0]),
                    "chapter": _strip_hash(chapter_label),
                    "title": subtitle,
                    "publish_at": str(ts) if ts else "",
                    "raw_label": chapter_label,
                })
        for vs in node.values():
            for v in vs:
                if isinstance(v, dict):
                    _find_chapters(v, out)


def _strip_hash(s: str) -> str:
    """``#1182`` → ``1182``."""
    s = (s or "").strip()
    if s.startswith("#"):
        s = s[1:]
    return s.strip()


# ── Public: list all titles + search ───────────────────────────────────────
_ALL_TITLES_CACHE: tuple = ()  # (timestamp, [titles])

# Default request params + headers used to look like the real Android app
# (the public web client is geo-restricted and returns "Account Banned").
_API_PARAMS = {
    "os": "android",
    "os_ver": "29",
    "app_ver": "133",
    "secret": "",
    "format": "json",
}
_API_HEADERS = {
    "User-Agent":
        "Dalvik/2.1.0 (Linux; U; Android 9; SM-G960F Build/PPR1.180610.011)",
    "Origin": "https://mangaplus.shueisha.co.jp",
    "Session-Token": "",
    "Accept": "*/*",
}


def _api_url(path: str, **extra) -> str:
    qs = {**_API_PARAMS, **extra}
    return WEBAPI_BASE + path + "?" + urllib.parse.urlencode(qs)


def _http_get(url: str, *, proxy_url: Optional[str] = None,
              timeout: int = 25) -> bytes:
    handlers: list = []
    if proxy_url:
        scheme = proxy_url.split("://", 1)[0]
        handlers.append(urllib.request.ProxyHandler({scheme: proxy_url}))
    opener = (
        urllib.request.build_opener(*handlers)
        if handlers else urllib.request.build_opener()
    )
    opener.addheaders = list(_API_HEADERS.items())
    try:
        with opener.open(url, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise MangaPlusError(f"HTTP {e.code} on {url}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MangaPlusError(f"Network error on {url}: {e}") from e


# ── Parse Title messages directly from raw bytes ───────────────────────────
def _read_varint_at(buf: bytes, pos: int) -> Tuple[int, int]:
    """Read a varint starting at ``pos``. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 63:
            raise MangaPlusError("varint too long")
    raise MangaPlusError("varint truncated")


def _scan_titles_raw(buf: bytes) -> List[dict]:
    """Locate every Title message by direct byte pattern match.

    Title proto layout the API actually serialises::

        \\x08 <title_id varint>
        \\x12 <name_len varint> <name bytes>
        [\\x1a <author_len> <author bytes>]
        \\x22 <portrait_url_len> <portrait_url bytes>     # field 4
        [\\x2a <landscape_url_len> <landscape_url bytes>] # field 5

    We scan for the fingerprint ``\\x08 <id> \\x12 <len>`` then read fields
    forward until we leave the message (encountering an unknown tag or
    going out of bounds).
    """
    titles: List[dict] = []
    seen_ids: set = set()
    pos = 0
    while pos < len(buf):
        # Scan forward to the next \x08 byte (varint tag for field 1)
        idx = buf.find(b"\x08", pos)
        if idx < 0:
            break
        try:
            title_id, after_id = _read_varint_at(buf, idx + 1)
        except Exception:
            pos = idx + 1
            continue
        # Title IDs on MangaPlus are typically 5-7 digits (e.g. 100020).
        if title_id < 1000 or title_id > 9_999_999:
            pos = idx + 1
            continue
        # Expect field 2 (name) right after
        if after_id >= len(buf) or buf[after_id] != 0x12:
            pos = idx + 1
            continue
        try:
            name_len, after_name_hdr = _read_varint_at(buf, after_id + 1)
        except Exception:
            pos = idx + 1
            continue
        if name_len <= 0 or name_len > 200 or after_name_hdr + name_len > len(buf):
            pos = idx + 1
            continue
        try:
            name = buf[after_name_hdr: after_name_hdr + name_len].decode("utf-8")
        except UnicodeDecodeError:
            pos = idx + 1
            continue
        if not name or any(ord(c) < 0x20 and c not in "\n\t" for c in name):
            pos = idx + 1
            continue

        # Read optional fields 3 (author), 4 (portrait), 5 (landscape)
        cursor = after_name_hdr + name_len
        author = ""
        portrait = ""
        landscape = ""
        for _ in range(8):  # max 8 trailing fields per title
            if cursor >= len(buf):
                break
            tag = buf[cursor]
            if tag == 0x1A:    # field 3, length-delimited
                try:
                    blen, after_hdr = _read_varint_at(buf, cursor + 1)
                except Exception:
                    break
                if blen < 0 or after_hdr + blen > len(buf) or blen > 500:
                    break
                try:
                    author = buf[after_hdr: after_hdr + blen].decode("utf-8")
                except UnicodeDecodeError:
                    break
                cursor = after_hdr + blen
            elif tag == 0x22:  # field 4, length-delimited (portrait URL)
                try:
                    blen, after_hdr = _read_varint_at(buf, cursor + 1)
                except Exception:
                    break
                if blen < 0 or after_hdr + blen > len(buf) or blen > 1000:
                    break
                try:
                    portrait = buf[after_hdr: after_hdr + blen].decode("utf-8")
                except UnicodeDecodeError:
                    break
                cursor = after_hdr + blen
            elif tag == 0x2A:  # field 5, length-delimited (landscape URL)
                try:
                    blen, after_hdr = _read_varint_at(buf, cursor + 1)
                except Exception:
                    break
                if blen < 0 or after_hdr + blen > len(buf) or blen > 1000:
                    break
                try:
                    landscape = buf[after_hdr: after_hdr + blen].decode("utf-8")
                except UnicodeDecodeError:
                    break
                cursor = after_hdr + blen
            elif tag in (0x30, 0x38):  # field 6 / 7, varint
                try:
                    _, after_hdr = _read_varint_at(buf, cursor + 1)
                except Exception:
                    break
                cursor = after_hdr
            else:
                break

        # Need at least a portrait or landscape URL pointing to MangaPlus
        cover = portrait or landscape
        if not cover.startswith("http"):
            pos = idx + 1
            continue
        if "tokyo-cdn.com" not in cover:
            pos = idx + 1
            continue

        if title_id not in seen_ids:
            seen_ids.add(title_id)
            titles.append({
                "id": str(title_id),
                "title": name,
                "authors": [author] if author else [],
                "cover_url": cover,
            })
        pos = cursor
    return titles


def list_all_titles(*, proxy_url: Optional[str] = None,
                    timeout: int = 25, ttl_seconds: int = 600) -> List[dict]:
    """Fetch the full MangaPlus catalogue (cached).

    Returns ``[{id, title, authors[], cover_url, language}, ...]``.
    Uses the JSON variant of the API (param ``format=json`` makes the
    server return human-readable JSON instead of protobuf).
    """
    global _ALL_TITLES_CACHE
    import time as _time
    import json as _json
    if _ALL_TITLES_CACHE:
        ts, items = _ALL_TITLES_CACHE
        if _time.time() - ts < ttl_seconds and items:
            return items
    blob = _http_get(_api_url("/api/title_list/allV2"),
                     proxy_url=proxy_url, timeout=timeout)
    items: List[dict] = []
    try:
        data = _json.loads(blob.decode("utf-8", errors="replace"))
    except _json.JSONDecodeError:
        # Fallback: protobuf bytes scanner (older API responses)
        items = _scan_titles_raw(blob)
    else:
        items = _flatten_json_titles(data)
    if items:
        _ALL_TITLES_CACHE = (_time.time(), items)
    return items


def _flatten_json_titles(data) -> List[dict]:
    """Walk MangaPlus' AllTitlesViewV2 JSON and emit a flat title list.

    The blob shape is roughly::
        success: {
          allTitlesViewV2: {
            AllTitlesGroup: [
              { theTitle: "One Piece", titles: [
                  {titleId, name, author, portraitImageUrl, language}, ...
              ]},
              ...
            ]
          }
        }
    A single English copy of each title is enough — we prefer ``ENGLISH``
    when the same series has multiple language entries.
    """
    out: List[dict] = []
    seen: dict = {}

    def _walk(node):
        if isinstance(node, dict):
            tid = node.get("titleId")
            if (isinstance(tid, int) and node.get("name")
                    and node.get("portraitImageUrl")):
                lang = (node.get("language") or "ENGLISH").upper()
                key = node["name"]   # group by display name
                entry = {
                    "id": str(tid),
                    "title": node["name"],
                    "authors": [node.get("author", "").strip()] if node.get("author") else [],
                    "cover_url": node.get("portraitImageUrl") or node.get("landscapeImageUrl") or "",
                    "language": lang,
                }
                # Prefer English; otherwise keep first-seen
                prev = seen.get(key)
                if prev is None or (lang == "ENGLISH" and prev.get("language") != "ENGLISH"):
                    seen[key] = entry
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(data)
    out = list(seen.values())
    return out


def search_titles(query: str, *, limit: int = 30,
                  proxy_url: Optional[str] = None) -> List[dict]:
    """Free-text search across the full title list. Case-insensitive,
    matches title name and author name. Sort by closeness."""
    q = (query or "").strip().lower()
    if not q:
        return []
    all_titles = list_all_titles(proxy_url=proxy_url)
    scored: List[tuple] = []
    for t in all_titles:
        name = (t.get("title") or "").lower()
        authors = " ".join(t.get("authors") or []).lower()
        score = 0
        if name == q:
            score = 1000
        elif name.startswith(q):
            score = 500
        elif q in name:
            score = 200
        elif any(part.startswith(q) for part in re.split(r"\s+", name) if part):
            score = 100
        elif q in authors:
            score = 50
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limit]]


# ── Title detail (description + chapter list) — JSON variant ───────────────
def list_chapters(title_id: str, *, proxy_url: Optional[str] = None,
                  timeout: int = 25) -> dict:
    """Fetch the detail page for a title. Returns
    ``{title: {...}, chapters: [...], languages: [...], paywall: {...}}``.

    The chapter list MangaPlus exposes for free is split into two groups:
    the first 3-4 chapters and the latest 3-4 chapters. Anything in
    between is paywalled (Shueisha policy — only readable inside the
    official MangaPlus app with a login).

    We return:
        - ``chapters``: free chapters (first + last lists merged).
        - ``paywalled_count``: estimated number of paywalled chapters.
        - ``languages``: alternate-language editions of this title (so
          the UI can offer language switching).
    """
    import json as _json
    blob = _http_get(_api_url("/api/title_detailV3", title_id=str(title_id)),
                     proxy_url=proxy_url, timeout=timeout)
    try:
        data = _json.loads(blob.decode("utf-8", errors="replace"))
    except _json.JSONDecodeError:
        # Fallback to protobuf scanner
        titles = _scan_titles_raw(blob)
        title_meta = titles[0] if titles else {
            "id": str(title_id), "title": "(không có tiêu đề)",
            "authors": [], "cover_url": "",
        }
        return {"title": title_meta, "chapters": _scan_chapters_raw(blob),
                "languages": [], "paywalled_count": 0}

    view = ((data.get("success") or {}).get("titleDetailView") or {})

    # ── Title metadata ───────────────────────────────────────────────
    title_node = view.get("title") or {}
    title_meta = {
        "id": str(title_node.get("titleId") or title_id),
        "title": title_node.get("name") or "(không có tiêu đề)",
        "authors": [title_node.get("author")] if title_node.get("author") else [],
        "cover_url": (title_node.get("portraitImageUrl")
                      or view.get("titleImageUrl")
                      or title_node.get("landscapeImageUrl") or ""),
        "description": view.get("overview") or "",
        "language": (title_node.get("language") or "ENGLISH"),
    }

    # ── Free chapters (first + last lists from every group) ─────────
    chapters: List[dict] = []
    seen: set = set()
    paywalled_estimate = 0

    for grp in view.get("chapterListGroup", []) or []:
        first_list = grp.get("firstChapterList") or []
        mid_list = grp.get("midChapterList") or []
        last_list = grp.get("lastChapterList") or []
        # All free chapters (first + last). midChapterList is also free
        # but acts as a separator chapter; we keep them too.
        for src_list in (first_list, mid_list, last_list):
            for ch in src_list:
                cid = ch.get("chapterId")
                if not isinstance(cid, int) or cid in seen:
                    continue
                seen.add(cid)
                chapters.append({
                    "id": str(cid),
                    "chapter": _strip_hash(ch.get("name", "")),
                    "title": ch.get("subTitle") or ch.get("subtitle") or "",
                    "publish_at": str(ch.get("startTimeStamp") or ""),
                    "raw_label": ch.get("name", ""),
                    "thumbnail_url": ch.get("thumbnailUrl", ""),
                    "is_paywall": False,
                })
        # Estimate paywall: span between last "first" chapter and first
        # "last" chapter
        chapter_numbers = grp.get("chapterNumbers") or []
        if isinstance(chapter_numbers, list) and len(chapter_numbers) >= 2:
            try:
                lo = int(chapter_numbers[0])
                hi = int(chapter_numbers[-1])
                paywalled_estimate += max(0, hi - lo + 1 - len(first_list) - len(last_list) - len(mid_list))
            except (ValueError, TypeError):
                pass

    # ── Alternate-language editions ───────────────────────────────────
    languages: List[dict] = []
    for entry in view.get("titleLanguages", []) or []:
        if not isinstance(entry, dict):
            continue
        tid = entry.get("titleId")
        lang = entry.get("language") or ""
        if not isinstance(tid, int):
            continue
        # The first entry doesn't always carry "language" — that one is
        # the manga's native language (ENGLISH for Shueisha titles).
        languages.append({
            "id": str(tid),
            "language": lang or "ENGLISH",
            "is_current": (str(tid) == str(title_id)),
        })

    return {
        "title": title_meta,
        "chapters": chapters,
        "languages": languages,
        "paywalled_count": paywalled_estimate,
        "has_paywall": bool(view.get("hasChaptersBetween")),
    }

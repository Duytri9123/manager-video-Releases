"""
Movie review generator — fetches metadata from TMDb (or pluggable source),
and uses an LLM (DeepSeek / OpenAI / Groq via utils.translation infrastructure)
to write a Vietnamese-friendly review script ready for TTS.

Endpoints (see routes/movie.py):
  POST /api/movie/search   { query, language? }       → TMDb search
  POST /api/movie/details  { tmdb_id, language? }     → details + credits
  POST /api/movie/review   { tmdb_id|title|info,
                             template, length_sec,
                             provider, target_lang }  → review script

The LLM call falls back to a deterministic template when no API key is
configured, so the feature is still usable for plain review writing.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


TMDB_BASE = "https://api.themoviedb.org/3"


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def _http_json(url: str, *, timeout: int = 20, headers: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


def _post_json(url: str, payload: dict, *, headers: dict, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


# ── Wikipedia (extra context) ────────────────────────────────────────────────
def _wiki_search(query: str, lang: str, *, timeout: int = 10,
                 require_keywords: Optional[list] = None) -> Optional[str]:
    """Find the best matching Wikipedia article title for a query.

    Uses MediaWiki search; if `require_keywords` is given, only accepts a
    result whose title contains at least one of the keywords (case-insensitive).
    This avoids picking up unrelated articles for ambiguous short queries.
    """
    try:
        url = (
            f"https://{lang}.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode({
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": 5, "format": "json", "utf8": 1,
            })
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "DuyTris-MovieReview/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        results = (data.get("query") or {}).get("search") or []
        if not results:
            return None
        if not require_keywords:
            return results[0]["title"]
        kws = [k.lower() for k in require_keywords if k]
        # Score each result by how many keywords appear as standalone substring;
        # require at least one keyword present.
        best = None
        best_score = 0
        for r in results:
            t = (r.get("title") or "").lower()
            score = sum(1 for k in kws if k in t)
            if score > best_score:
                best_score = score
                best = r["title"]
        return best if best_score >= 1 else None
    except Exception:
        return None


_PLOT_SECTION_NAMES = {
    "vi": ["Cốt truyện", "Nội dung", "Tóm tắt", "Tóm tắt cốt truyện"],
    "en": ["Plot", "Synopsis", "Plot summary", "Storyline"],
    "zh": ["剧情", "故事", "剧情简介", "情节"],
    "ja": ["あらすじ", "ストーリー"],
    "ko": ["줄거리"],
    "es": ["Argumento", "Sinopsis"],
    "fr": ["Synopsis", "Résumé"],
    "pt": ["Enredo", "Sinopse"],
    "th": ["เนื้อเรื่อง"],
    "id": ["Sinopsis", "Alur cerita"],
}


def _strip_wikitext(raw: str) -> str:
    """Naive but effective wikitext → plain text cleaner.

    Removes templates {{...}}, infoboxes, refs, files, links syntax, headers,
    bullets, HTML tags, and collapses whitespace.
    """
    if not raw:
        return ""
    s = raw

    # Remove {{templates}} (recursive-ish, do a few passes to handle nesting)
    for _ in range(8):
        s2, n = re.subn(r"\{\{[^{}]*\}\}", "", s, flags=re.DOTALL)
        if n == 0:
            break
        s = s2

    # Remove [[File:...]] / [[Tập_tin:...]] / [[Image:...]] including pipes
    s = re.sub(r"\[\[(?:File|Image|Tập_tin|Tập tin|Tệp|Tệp tin):.*?\]\]", "", s,
               flags=re.IGNORECASE | re.DOTALL)

    # [[Target|Display]] → Display ; [[Target]] → Target
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]", r"\1", s)

    # External links [http://... display] → display
    s = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)

    # <ref>...</ref> and <ref name="..."/>
    s = re.sub(r"<ref[^>]*?/>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.IGNORECASE | re.DOTALL)

    # Other HTML tags
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)

    # Bold/italic '''xxx''' / ''xxx''
    s = re.sub(r"'''(.+?)'''", r"\1", s)
    s = re.sub(r"''(.+?)''", r"\1", s)

    # Headers ==Title== → drop
    s = re.sub(r"(?m)^={2,}.*?={2,}\s*$", "", s)

    # Bullet/numbered list markers
    s = re.sub(r"(?m)^[\*#:;]+\s*", "", s)

    # Collapse whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch_wikipedia_section(title: str, lang: str = "vi", *,
                            section_keywords: Optional[list] = None,
                            timeout: int = 15, max_chars: int = 6000) -> dict:
    """Fetch a specific section ('Cốt truyện' / 'Plot' / etc) from a Wiki article.

    Returns {section_title, text, full_url}. Empty text on failure.
    """
    if not title:
        return {"section_title": "", "text": "", "full_url": ""}

    keywords = section_keywords or _PLOT_SECTION_NAMES.get(lang, []) + _PLOT_SECTION_NAMES["en"]
    syllables = [w for w in re.split(r"\s+", title) if w.strip()]
    base_keywords = [w for w in syllables if len(w) >= 2][:6]
    is_ambiguous_short = len(syllables) < 3 and sum(len(w) for w in syllables) < 8

    def _section_index(t: str, code: str) -> tuple[Optional[int], Optional[str]]:
        try:
            url = (
                f"https://{code}.wikipedia.org/w/api.php?"
                + urllib.parse.urlencode({
                    "action": "parse", "page": t, "prop": "sections",
                    "format": "json", "utf8": 1,
                })
            )
            req = urllib.request.Request(url, headers={"User-Agent": "DuyTris-MovieReview/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            sections = ((data.get("parse") or {}).get("sections") or [])
            for s in sections:
                line = (s.get("line") or "").strip()
                for kw in keywords:
                    if line.lower() == kw.lower() or kw.lower() in line.lower():
                        return int(s.get("index", 0)), line
            return None, None
        except Exception:
            return None, None

    def _section_wikitext(t: str, code: str, idx: int) -> str:
        try:
            url = (
                f"https://{code}.wikipedia.org/w/api.php?"
                + urllib.parse.urlencode({
                    "action": "parse", "page": t, "prop": "wikitext",
                    "section": idx, "format": "json", "utf8": 1,
                })
            )
            req = urllib.request.Request(url, headers={"User-Agent": "DuyTris-MovieReview/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            wikitext = ((data.get("parse") or {}).get("wikitext") or {}).get("*", "")
            return _strip_wikitext(wikitext)[:max_chars]
        except Exception:
            return ""

    langs = (lang, "en") if lang and lang != "en" else ("en",)
    for code in langs:
        # Try the title as-is first; if not found, do a search
        candidate_title = title
        idx, sec_line = _section_index(candidate_title, code)
        if idx is None and not is_ambiguous_short:
            found = _wiki_search(title, code, require_keywords=base_keywords)
            if found and found != candidate_title:
                candidate_title = found
                idx, sec_line = _section_index(candidate_title, code)
        if idx is not None:
            text = _section_wikitext(candidate_title, code, idx)
            if text and len(text) >= 80:
                full_url = f"https://{code}.wikipedia.org/wiki/" + urllib.parse.quote(candidate_title.replace(" ", "_"))
                return {"section_title": sec_line or "", "text": text, "full_url": full_url}
    return {"section_title": "", "text": "", "full_url": ""}


def fetch_wikipedia_summary(title: str, lang: str = "vi", *,
                            timeout: int = 12) -> str:
    """Fetch Wikipedia plain-text summary for a movie. Returns '' on failure.

    Strategy: try direct page summary first; if not found, run a search to
    discover the canonical title, then fetch that summary. Falls back to
    English if the localized article isn't available.
    """
    if not title:
        return ""

    def _summary(t: str, code: str) -> str:
        try:
            url = f"https://{code}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(t)}"
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "DuyTris-MovieReview/1.0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            extract = (data.get("extract") or "").strip()
            return extract if len(extract) >= 80 else ""
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ""
            return ""
        except Exception:
            return ""

    langs = (lang, "en") if lang and lang != "en" else ("en",)
    # Build relevance keywords. Skip search-fallback entirely for very short
    # ambiguous Vietnamese titles (< 3 syllables AND < 8 ASCII chars) — Wiki
    # search returns way too much noise (e.g. "Khí Tử" → "Văn Miếu Quốc Tử Giám").
    syllables = [w for w in re.split(r"\s+", title) if w.strip()]
    base_keywords = [w for w in syllables if len(w) >= 2][:6]
    is_ambiguous_short = len(syllables) < 3 and sum(len(w) for w in syllables) < 8
    for code in langs:
        # Direct lookup (always allowed)
        text = _summary(title, code)
        if text:
            return text
        if is_ambiguous_short:
            continue
        # Search-then-fetch (only when the title is unambiguous enough)
        canonical = _wiki_search(title, code, require_keywords=base_keywords)
        if canonical and canonical != title:
            text = _summary(canonical, code)
            if text:
                return text
    return ""


# ── TMDb client ──────────────────────────────────────────────────────────────
class TMDbClient:
    """TMDb API client supporting both v3 (api_key query) and v4 (Bearer token).

    If `read_access_token` is provided, it is used in `Authorization: Bearer ...`
    header — this is the recommended auth method per TMDb docs. Otherwise the
    legacy v3 `api_key` query param is used.
    """

    def __init__(self, api_key: str = "", language: str = "vi",
                 read_access_token: str = ""):
        self.api_key = (api_key or "").strip()
        self.read_access_token = (read_access_token or "").strip()
        self.language = language or "vi"
        if not self.api_key and not self.read_access_token:
            raise ValueError(
                "Thiếu TMDb credentials. Đặt `movie.tmdb_api_key` (v3) "
                "hoặc `movie.tmdb_read_token` (v4) trong config.yml, "
                "hoặc env TMDB_API_KEY / TMDB_READ_TOKEN."
            )

    @property
    def _auth_headers(self) -> dict:
        if self.read_access_token:
            return {"Authorization": f"Bearer {self.read_access_token}"}
        return {}

    def _q(self, params: dict) -> str:
        # Only attach api_key when we don't have a v4 bearer token.
        if not self.read_access_token and self.api_key:
            params = {**params, "api_key": self.api_key}
        return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})

    def _get(self, url: str) -> dict:
        return _http_json(url, headers=self._auth_headers)

    def search(self, query: str, language: Optional[str] = None,
               include_adult: bool = False, page: int = 1) -> dict:
        url = f"{TMDB_BASE}/search/movie?" + self._q({
            "query": query,
            "language": language or self.language,
            "include_adult": str(include_adult).lower(),
            "page": page,
        })
        return self._get(url)

    def search_tv(self, query: str, language: Optional[str] = None, page: int = 1) -> dict:
        url = f"{TMDB_BASE}/search/tv?" + self._q({
            "query": query, "language": language or self.language, "page": page,
        })
        return self._get(url)

    def details(self, tmdb_id: int, language: Optional[str] = None,
                kind: str = "movie") -> dict:
        url = f"{TMDB_BASE}/{kind}/{int(tmdb_id)}?" + self._q({
            "language": language or self.language,
            "append_to_response": "credits,videos,keywords,external_ids,release_dates,reviews",
        })
        return self._get(url)

    def images(self, tmdb_id: int, kind: str = "movie",
               include_languages: str = "vi,en,null") -> dict:
        """Fetch backdrops, posters, and stills (logos for movies)."""
        url = f"{TMDB_BASE}/{kind}/{int(tmdb_id)}/images?" + self._q({
            "include_image_language": include_languages,
        })
        return self._get(url)

    def reviews(self, tmdb_id: int, kind: str = "movie",
                language: Optional[str] = None, page: int = 1) -> dict:
        url = f"{TMDB_BASE}/{kind}/{int(tmdb_id)}/reviews?" + self._q({
            "language": language or self.language,
            "page": page,
        })
        return self._get(url)

    def trending(self, period: str = "week", language: Optional[str] = None) -> dict:
        period = period if period in ("day", "week") else "week"
        url = f"{TMDB_BASE}/trending/movie/{period}?" + self._q({"language": language or self.language})
        return self._get(url)

    def poster_url(self, path: str, size: str = "w500") -> str:
        if not path:
            return ""
        return f"https://image.tmdb.org/t/p/{size}{path}"

    def collect_image_urls(self, tmdb_id: int, kind: str = "movie",
                           limit: int = 24) -> list:
        """Return a mix of backdrops + posters as ready-to-use URLs (large size)."""
        try:
            data = self.images(tmdb_id, kind=kind)
        except Exception:
            return []
        urls = []
        for b in (data.get("backdrops") or [])[:max(8, limit // 2)]:
            if b.get("file_path"):
                urls.append(self.poster_url(b["file_path"], "w1280"))
        for p in (data.get("posters") or [])[:max(4, limit // 4)]:
            if p.get("file_path"):
                urls.append(self.poster_url(p["file_path"], "w780"))
        # Dedupe while preserving order
        seen = set()
        out = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
            if len(out) >= limit:
                break
        return out


# ── Review generation ────────────────────────────────────────────────────────
@dataclass
class ReviewRequest:
    info: Dict[str, Any]              # movie/show info dict
    template: str = "cinematic"        # cinematic | informative | hook_short | top_list
    length_sec: int = 90               # target spoken length (≈ 150 wpm Vietnamese)
    target_lang: str = "vi"
    provider: str = "auto"             # auto | deepseek | openai | groq
    extra_notes: str = ""

    @property
    def target_words(self) -> int:
        # Vietnamese ≈ 130–160 wpm spoken; pick the lower bound
        return max(60, int(self.length_sec / 60 * 140))


_TEMPLATES_VI = {
    "cinematic": (
        "Bạn là một biên kịch chuyên viết kịch bản review phim cho YouTube/TikTok. "
        "Văn phong điện ảnh, giàu hình ảnh, có hook 5 giây đầu, dẫn dắt mạch lạc, "
        "có cao trào, cảm xúc và call-to-action ở cuối. KHÔNG spoiler kết thúc."
    ),
    "informative": (
        "Bạn là người dẫn chương trình thông tin điện ảnh. Văn phong rõ ràng, "
        "trung tính, có dữ kiện, đưa thông tin đạo diễn/diễn viên/giải thưởng, "
        "đánh giá điểm mạnh/yếu và đối tượng phù hợp. Tránh spoiler chính."
    ),
    "hook_short": (
        "Bạn viết video dạng Reels/Shorts dưới 60 giây. Mở đầu hook cực mạnh, "
        "chỉ giữ 1 ý tưởng then chốt, kết bằng câu hỏi hoặc twist. "
        "Tránh dài dòng, tránh giới thiệu mào đầu."
    ),
    "top_list": (
        "Bạn viết video dạng top-list (ví dụ 'Top 5 lý do nên xem phim này'). "
        "Đánh số rõ ràng, mỗi mục 2–3 câu, kết phim dẫn người xem chia sẻ ý kiến."
    ),
}


def build_prompt(req: ReviewRequest) -> tuple[str, str]:
    info = req.info or {}
    title = info.get("title") or info.get("name") or info.get("original_title") or info.get("original_name") or ""
    original_title = info.get("original_title") or info.get("original_name") or ""
    year = (info.get("release_date") or info.get("first_air_date") or "")[:4]
    overview = info.get("overview") or ""
    tagline = info.get("tagline") or ""
    genres = ", ".join(g.get("name", "") for g in (info.get("genres") or [])) or ""
    runtime = info.get("runtime") or (info.get("episode_run_time") or [None])[0]
    rating = info.get("vote_average")
    vote_count = info.get("vote_count")
    cast_list = (info.get("credits") or {}).get("cast") or []
    cast = ", ".join(c.get("name", "") for c in cast_list[:6])
    director = ""
    for c in (info.get("credits") or {}).get("crew") or []:
        if c.get("job") == "Director":
            director = c.get("name", "")
            break
    keywords = ", ".join(k.get("name", "") for k in ((info.get("keywords") or {}).get("keywords") or [])[:8])

    # Pull TMDb reviews (filter to substantial ones, cap chars)
    review_excerpts = []
    for rv in ((info.get("reviews") or {}).get("results") or [])[:3]:
        content = (rv.get("content") or "").strip()
        if len(content) >= 60:
            content = content.replace("\r", " ").replace("\n", " ")
            review_excerpts.append(f"- ({rv.get('author','khán giả')}): {content[:400]}")

    # Wikipedia extract (passed in as info["wiki_extract"] to avoid network here)
    wiki = (info.get("wiki_extract") or "").strip()
    plot = (info.get("wiki_plot") or "").strip()

    system = _TEMPLATES_VI.get(req.template, _TEMPLATES_VI["cinematic"])
    user = (
        f"Hãy viết kịch bản review **bằng {req.target_lang.upper()}**, dài khoảng "
        f"{req.target_words} từ (≈ {req.length_sec} giây thoại), văn nói tự nhiên, "
        f"không markdown, không emoji thừa. Chia thành các đoạn ngắn 1–3 câu, "
        f"mỗi đoạn xuống dòng, sẵn sàng cho TTS đọc.\n\n"
        f"THÔNG TIN PHIM:\n"
        f"- Tựa: {title}{f' ({year})' if year else ''}"
        f"{f' [tựa gốc: {original_title}]' if original_title and original_title != title else ''}\n"
        f"- Tagline: {tagline or '—'}\n"
        f"- Đạo diễn: {director or 'Không rõ'}\n"
        f"- Diễn viên chính: {cast or 'Không rõ'}\n"
        f"- Thể loại: {genres or 'Không rõ'}\n"
        f"- Thời lượng: {runtime or 'Không rõ'} phút\n"
        f"- Điểm TMDb: {rating if rating is not None else 'Không rõ'}"
        f"{f' ({vote_count} lượt)' if vote_count else ''}\n"
        f"- Từ khoá: {keywords or 'Không rõ'}\n"
        f"- Tóm tắt TMDb:\n{overview or '(không có)'}\n"
    )
    if wiki:
        user += f"\n- Wikipedia (intro):\n{wiki[:1500]}\n"
    if plot:
        user += f"\n- Wikipedia (cốt truyện đầy đủ — KHÔNG copy nguyên văn, hãy DIỄN GIẢI và viết lại theo phong cách review, GIỮ LẠI mọi nút thắt nhưng không spoil kết phim):\n{plot[:5000]}\n"
    if review_excerpts:
        user += "\n- Trích đánh giá khán giả:\n" + "\n".join(review_excerpts) + "\n"
    if req.extra_notes:
        user += f"\nGHI CHÚ THÊM:\n{req.extra_notes}\n"
    user += (
        "\nYÊU CẦU ĐẦU RA:\n"
        "1) Trả về JSON đúng định dạng:\n"
        "{\n"
        '  "title": "<tựa phim hiển thị>",\n'
        '  "hashtags": ["#review", "#phimhay"],\n'
        '  "hook": "<câu mở đầu 1 dòng>",\n'
        '  "script": "<toàn bộ lời thoại đã chia đoạn>",\n'
        '  "thumbnail_idea": "<gợi ý thumbnail>"\n'
        "}\n"
        "2) Không thêm bất kỳ chú thích nào ngoài JSON.\n"
        "3) Tuyệt đối không spoil kết phim.\n"
        "4) Văn phong tự nhiên, không sáo rỗng, dùng từ ngữ Việt thuần.\n"
    )
    return system, user


def _call_llm(provider: str, cfg: dict, system: str, user: str) -> Optional[str]:
    """Try the requested provider, falling back through the available list.

    Supports: "9router" | "deepseek" | "openai" | "groq" | "auto".
    9Router is the local OpenAI-compatible gateway (https://9router.com).
    When selected, this routes through `nine_router.endpoint` using the
    cached API key from `nine_router.api_key` and the configured tier model
    (defaults to `nine_router.default_model`).
    """
    tr = cfg.get("translation") or {}
    nr = cfg.get("nine_router") or {}
    movie_cfg = cfg.get("movie") or {}

    candidates: list[tuple[str, str]] = []
    # 9Router gets first dibs when explicitly chosen, or in auto mode if a
    # key is cached. We don't push it ahead of paid keys in auto unless the
    # user has nothing else configured.
    if provider == "9router" and (nr.get("api_key") or "").strip():
        candidates.append(("9router", nr["api_key"]))
    if provider in ("auto", "deepseek") and tr.get("deepseek_key"):
        candidates.append(("deepseek", tr["deepseek_key"]))
    if provider in ("auto", "openai") and tr.get("openai_key"):
        candidates.append(("openai", tr["openai_key"]))
    if provider in ("auto", "groq") and tr.get("groq_key"):
        candidates.append(("groq", tr["groq_key"]))
    # Auto-mode last-resort: 9Router when nothing else is configured.
    if provider == "auto" and not candidates and (nr.get("api_key") or "").strip():
        candidates.append(("9router", nr["api_key"]))
    if not candidates and provider not in ("auto", "9router", "deepseek", "openai", "groq"):
        return None

    for prov, key in candidates:
        try:
            if prov == "9router":
                endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
                model = (nr.get("default_model") or "duytris").strip()
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.6,
                    "max_tokens": int(nr.get("max_tokens") or 4096),
                    "stream": False,
                }
                data = _post_json(
                    f"{endpoint}/chat/completions",
                    payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
                return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if prov == "deepseek":
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 1500,
                }
                data = _post_json(
                    "https://api.deepseek.com/chat/completions",
                    payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
                return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if prov == "openai":
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 1500,
                }
                data = _post_json(
                    "https://api.openai.com/v1/chat/completions",
                    payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
                return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if prov == "groq":
                payload = {
                    "model": tr.get("groq_model") or "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 1500,
                }
                data = _post_json(
                    "https://api.groq.com/openai/v1/chat/completions",
                    payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
                return ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        except Exception:
            continue
    return None


def _try_parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except Exception:
        return None


def _is_cjk(s: str) -> bool:
    """Return True if the string contains any CJK characters (cast/director not localized)."""
    import re as _re
    return bool(_re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", s or ""))


def _split_overview(overview: str) -> list[str]:
    """Split a TMDb overview into clean sentences (Vietnamese-friendly)."""
    import re as _re
    if not overview:
        return []
    text = overview.replace("\r", " ").replace("\n", " ").strip()
    # Split on sentence-ending punctuation, keep delimiter
    parts = _re.split(r"(?<=[\.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _fallback_script(info: dict, target_words: int) -> dict:
    """Heuristic Vietnamese script when no LLM is available.

    Strategy:
      • Use overview + tagline + wikipedia summary as the spine.
      • Skip cast/director names that contain CJK (TTS sounds wrong).
      • Don't repeat the opening hook in body; pace transitions naturally.
      • Adapt length to the requested target_words by trimming or padding.
    """
    title = info.get("title") or info.get("name") or "phim này"
    overview = info.get("overview") or ""
    tagline = (info.get("tagline") or "").strip()
    wiki = (info.get("wiki_extract") or "").strip()
    plot = (info.get("wiki_plot") or "").strip()
    year = (info.get("release_date") or info.get("first_air_date") or "")[:4]
    genres = ", ".join(g.get("name", "") for g in (info.get("genres") or [])).strip()
    runtime = info.get("runtime") or (info.get("episode_run_time") or [None])[0]
    rating = info.get("vote_average")

    director = ""
    for c in (info.get("credits") or {}).get("crew") or []:
        if c.get("job") == "Director":
            name = (c.get("name") or "").strip()
            if name and not _is_cjk(name):
                director = name
                break
    cast_names = []
    for c in ((info.get("credits") or {}).get("cast") or []):
        name = (c.get("name") or "").strip()
        if name and not _is_cjk(name):
            cast_names.append(name)
        if len(cast_names) >= 4:
            break
    cast_str = ", ".join(cast_names)

    sentences = _split_overview(overview) + (_split_overview(wiki) if wiki else []) + (_split_overview(plot) if plot else [])
    paragraphs: list[str] = []

    # Hook
    hook = (
        f"\"{tagline}\" — đó là tinh thần của {title}{f' ({year})' if year else ''}."
        if tagline
        else f"Bạn đã từng xem {title}{f' phát hành năm {year}' if year else ''} chưa? Đây là một tác phẩm đáng để dừng lại và suy ngẫm."
    )
    paragraphs.append(hook)

    # Snapshot
    snapshot_bits = []
    if genres:
        snapshot_bits.append(f"thuộc thể loại {genres}")
    if runtime:
        snapshot_bits.append(f"dài {runtime} phút")
    if isinstance(rating, (int, float)) and rating > 0:
        snapshot_bits.append(f"đạt {rating:.1f} điểm trên TMDb")
    if snapshot_bits:
        paragraphs.append("Bộ phim " + ", ".join(snapshot_bits) + ".")

    if director:
        paragraphs.append(f"Phim được chỉ đạo bởi {director}.")
    if cast_str:
        paragraphs.append(f"Quy tụ dàn diễn viên gồm {cast_str}.")

    # Story body — pull from overview/wiki, dedupe consecutive duplicates
    if sentences:
        usable = []
        seen = set()
        for s in sentences:
            if len(s) < 12:
                continue
            key = s[:60]
            if key in seen:
                continue
            seen.add(key)
            usable.append(s)
        if usable:
            mid = max(1, len(usable) // 2)
            first_block = " ".join(usable[:mid])
            second_block = " ".join(usable[mid:])
            if first_block:
                paragraphs.append(first_block)
            if second_block and second_block != first_block:
                paragraphs.append(second_block)
    else:
        paragraphs.append(
            "Câu chuyện đưa nhân vật chính qua những thử thách khắc nghiệt, "
            "buộc họ phải đối diện với chính mình và chọn lựa giữa lý tưởng và thực tại."
        )

    # Closing
    paragraphs.append(
        "Nếu bạn thích những bộ phim biết khơi gợi cảm xúc, đây là một lựa chọn xứng đáng. "
        "Hãy chia sẻ cảm nhận của bạn ở phần bình luận và đừng quên theo dõi kênh để xem thêm review nhé."
    )

    # Trim to fit target_words
    full = "\n\n".join(paragraphs)
    words = full.split()
    if target_words and len(words) > target_words * 1.6:
        out = []
        wc = 0
        for p in paragraphs:
            pw = len(p.split())
            if wc + pw > target_words * 1.4 and out:
                break
            out.append(p)
            wc += pw
        paragraphs = out

    body = "\n\n".join(paragraphs)

    # Hashtags
    tags = ["#review", "#mecphim"]
    for g in (info.get("genres") or [])[:2]:
        gn = (g.get("name") or "").replace(" ", "")
        if gn:
            tags.append("#" + gn.lower())

    return {
        "title": title,
        "hashtags": tags,
        "hook": paragraphs[0],
        "script": body,
        "thumbnail_idea": f"Poster {title} với chữ 'CÓ ĐÁNG XEM?' đỏ đậm bên trên.",
        "_fallback": True,
    }


def generate_review(req: ReviewRequest, cfg: dict) -> dict:
    system, user = build_prompt(req)
    raw = _call_llm(req.provider, cfg, system, user)
    parsed = _try_parse_json(raw) if raw else None
    if not parsed:
        return _fallback_script(req.info, req.target_words)
    parsed.setdefault("title", req.info.get("title") or req.info.get("name") or "")
    parsed.setdefault("hashtags", ["#review", "#phimhay"])
    return parsed


# ── Cache ────────────────────────────────────────────────────────────────────
class TmdbCache:
    def __init__(self, path: Path, ttl_hours: int = 24):
        self.path = Path(path)
        self.ttl = max(1, int(ttl_hours)) * 3600
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def get(self, key: str):
        item = self._data.get(key)
        if not item:
            return None
        if time.time() - item.get("ts", 0) > self.ttl:
            return None
        return item.get("value")

    def set(self, key: str, value: Any):
        self._data[key] = {"ts": time.time(), "value": value}
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

"""
Novel & comic → video-script generator.

Inputs accepted:
  • Plain text (whole novel, single chapter, or paste-in)
  • Source URL (HTTP fetch + best-effort article extraction)
  • Comic image folder / uploaded zip (OCR optional via tesseract)

Pipeline:
  1) Normalize text (strip web junk, fix encoding, clean line breaks)
  2) Optionally summarize chapter-by-chapter via LLM
  3) Chunk into TTS-ready segments (target ~350 chars / 4 sentences)
  4) Optionally translate to target language
  5) Emit `script_segments` array with index, text, est_duration

The output is JSON-serializable so the existing TTS / video pipeline can
consume it directly. We keep the surface small so it can be extended.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


# ── Sentence splitter (Vietnamese/English-friendly) ─────────────────────────
# Treats Eastern punctuation (。！？) and Latin (.!?) as sentence terminators.
_SENT_END = re.compile(r"(?<=[\.!?。！？])\s+")


def split_sentences(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    # First split on hard line breaks
    pieces: list[str] = []
    for line in re.split(r"\n+", text):
        line = line.strip()
        if not line:
            continue
        for s in _SENT_END.split(line):
            s = s.strip()
            if s:
                pieces.append(s)
    return pieces


# ── Cleaning ────────────────────────────────────────────────────────────────
_WHITESPACE = re.compile(r"[ \t]+")
_BOILERPLATE = [
    re.compile(r"(?im)^.*(read more|continue reading|chia sẻ.*facebook|đăng ký kênh).*$"),
    re.compile(r"(?im)^.*(advertisement|quảng cáo).*$"),
    re.compile(r"(?im)^chapter\s*\d+\b.*$"),
]


def normalize_text(raw: str) -> str:
    text = (raw or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pat in _BOILERPLATE:
        text = pat.sub("", text)
    # Collapse 3+ blank lines, strip extra spaces
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(_WHITESPACE.sub(" ", line).strip() for line in text.split("\n"))
    return text.strip()


# ── URL fetching with naive readability ─────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def fetch_url_text(url: str, *, proxy_url: Optional[str] = None,
                   timeout: int = 30, max_bytes: int = 4_000_000) -> str:
    handler_args = {}
    if proxy_url:
        scheme = proxy_url.split("://", 1)[0]
        handler_args[scheme] = proxy_url
    handler = urllib.request.ProxyHandler(handler_args) if handler_args else urllib.request.BaseHandler()
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", "Mozilla/5.0 (DuyTris Story Importer)")]
    with opener.open(url, timeout=timeout) as resp:
        body = resp.read(max_bytes)
        ctype = resp.headers.get_content_type() or "text/html"
        charset = resp.headers.get_content_charset() or "utf-8"
    text = body.decode(charset, errors="replace")
    if "html" in ctype:
        text = _SCRIPT_STYLE.sub(" ", text)
        text = _TAG_RE.sub("\n", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
    return normalize_text(text)


# ── Chunker ─────────────────────────────────────────────────────────────────
@dataclass
class ChunkOptions:
    target_chars: int = 350
    max_chars: int = 600
    overlap_sentences: int = 0


@dataclass
class Segment:
    index: int
    text: str
    char_count: int
    est_duration_sec: float

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "text": self.text,
            "char_count": self.char_count,
            "est_duration_sec": round(self.est_duration_sec, 2),
        }


def estimate_duration_sec(text: str, wpm: int = 140) -> float:
    """Rough VI/EN spoken estimate. Counts on whitespace; for CJK uses chars."""
    if not text:
        return 0.0
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", text):
        # CJK — ~5 chars/sec
        return len(text) / 5.0
    words = max(1, len(text.split()))
    return words / max(60, wpm) * 60.0


def chunk_into_segments(text: str, opts: Optional[ChunkOptions] = None) -> List[Segment]:
    opts = opts or ChunkOptions()
    sents = split_sentences(text)
    segments: List[Segment] = []
    buf: List[str] = []
    buf_len = 0
    idx = 0

    def flush():
        nonlocal buf, buf_len, idx
        if not buf:
            return
        seg_text = " ".join(buf).strip()
        seg = Segment(
            index=idx,
            text=seg_text,
            char_count=len(seg_text),
            est_duration_sec=estimate_duration_sec(seg_text),
        )
        segments.append(seg)
        idx += 1
        if opts.overlap_sentences > 0:
            tail = buf[-opts.overlap_sentences:]
            buf = list(tail)
            buf_len = sum(len(s) + 1 for s in buf)
        else:
            buf = []
            buf_len = 0

    for s in sents:
        s_len = len(s) + 1
        if buf and (buf_len + s_len > opts.max_chars):
            flush()
        buf.append(s)
        buf_len += s_len
        if buf_len >= opts.target_chars:
            flush()
    flush()
    return segments


# ── Translation hook (uses utils.translation) ───────────────────────────────
def maybe_translate_segments(segments: List[Segment], cfg: dict,
                             target_lang: str = "vi",
                             provider: str = "auto") -> List[Segment]:
    if not segments:
        return segments
    try:
        from utils.translation import translate_texts
    except Exception:
        return segments
    tr_cfg = dict(cfg.get("translation") or {})
    texts = [s.text for s in segments]
    try:
        translated, _ = translate_texts(texts, tr_cfg, provider, target_lang=target_lang)
    except TypeError:
        # older signature
        translated, _ = translate_texts(texts, tr_cfg, provider)
    out = []
    for seg, txt in zip(segments, translated):
        out.append(Segment(
            index=seg.index,
            text=(txt or seg.text),
            char_count=len((txt or seg.text)),
            est_duration_sec=estimate_duration_sec(txt or seg.text),
        ))
    return out


# ── Public pipeline ──────────────────────────────────────────────────────────
@dataclass
class StoryRequest:
    text: str = ""
    url: str = ""
    title: str = ""
    target_lang: str = "vi"
    translate: bool = False
    provider: str = "auto"
    chunk_opts: ChunkOptions = field(default_factory=ChunkOptions)
    proxy_url: str = ""


def run_pipeline(req: StoryRequest, cfg: dict) -> dict:
    raw = req.text or ""
    if not raw and req.url:
        raw = fetch_url_text(req.url, proxy_url=req.proxy_url)
    if not raw:
        raise ValueError("Không có nội dung nguồn (text hoặc url).")
    text = normalize_text(raw)
    segments = chunk_into_segments(text, req.chunk_opts)
    if req.translate:
        segments = maybe_translate_segments(segments, cfg,
                                            target_lang=req.target_lang,
                                            provider=req.provider)
    total_dur = sum(s.est_duration_sec for s in segments)
    return {
        "title": req.title or "",
        "char_count": len(text),
        "sentence_count": len(split_sentences(text)),
        "segment_count": len(segments),
        "est_duration_sec": round(total_dur, 1),
        "segments": [s.to_dict() for s in segments],
    }


# ── Comic helpers ───────────────────────────────────────────────────────────
def list_comic_images(folder: Path) -> List[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in exts])


def ocr_image_tesseract(path: Path, lang: str = "vie+eng") -> str:
    """Optional OCR via system tesseract. Returns empty string if not installed."""
    try:
        import shutil
        import subprocess
        if not shutil.which("tesseract"):
            return ""
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", lang, "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        return (proc.stdout or "").strip()
    except Exception:
        return ""


def ocr_folder(folder: Path, lang: str = "vie+eng") -> str:
    out = []
    for img in list_comic_images(folder):
        text = ocr_image_tesseract(img, lang=lang)
        if text:
            out.append(text)
    return "\n\n".join(out)

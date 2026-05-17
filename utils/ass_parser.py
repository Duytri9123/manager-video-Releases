"""
Helpers for parsing Advanced SubStation Alpha (.ass) subtitle files.

Trước đây các logic trích xuất Dialogue text bị lặp ở:
  - routes/transcribe.py._convert_ass_to_outputs
  - core/video_processor.py (vài chỗ đọc cached vi.ass)
  - frontend (publish.js, proc_publish.js, app.js, content.js, batch_publish.js)

Backend giờ chỉ cần ``from utils.ass_parser import extract_dialogue_text``.
Frontend tương đương ở ``static/js/utils.js`` (function ``extractAssText``).
"""
from __future__ import annotations

import re
from typing import List, Tuple

# Format: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")


def _strip_inline_overrides(text: str) -> str:
    """Strip ASS override codes ({\\xxx}) and \\N / \\n line breaks."""
    txt = _ASS_OVERRIDE.sub("", text or "")
    txt = txt.replace(r"\N", " ").replace(r"\n", " ")
    return re.sub(r"\s+", " ", txt).strip()


def iter_dialogue_lines(content: str) -> List[Tuple[str, str, str]]:
    """Yield ``(start, end, text)`` for each Dialogue line in ``content``.

    ``text`` already has override codes stripped. Lines with empty text
    after stripping are skipped.
    """
    out: List[Tuple[str, str, str]] = []
    for raw in (content or "").splitlines():
        if not raw.startswith("Dialogue:"):
            continue
        payload = raw[len("Dialogue:"):].lstrip()
        parts = payload.split(",", 9)
        if len(parts) < 10:
            continue
        text = _strip_inline_overrides(parts[9])
        if text:
            out.append((parts[1].strip(), parts[2].strip(), text))
    return out


def extract_dialogue_text(content: str, max_lines: int | None = None) -> str:
    """Concatenate Dialogue text into a single space-separated string.

    Useful for feeding subtitle content to AI providers without timing data.
    """
    pieces = [t for _, _, t in iter_dialogue_lines(content)]
    if max_lines is not None:
        pieces = pieces[:max_lines]
    return " ".join(pieces)

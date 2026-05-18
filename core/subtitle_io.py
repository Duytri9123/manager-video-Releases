"""Subtitle (SRT / ASS) writers for the manga → video pipeline.

Both writers accept the same lightweight segment shape::

    {"start": 0.0, "end": 3.5, "text": "..."}

Times are in **seconds** as floats. For ASS we emit a styled file with a
title bar and side blur panels (mirroring the existing
``write_ass_with_frame`` helper used by the movie pipeline) but kept
self-contained so this module has no cross-dependencies on
``core.video_processor``.

If you want fancier ASS output (frames + animations) call into
``core.video_processor.write_ass_with_frame`` directly — this module is
intentionally minimal and reusable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional


# ── Time formatters ──────────────────────────────────────────────────────────
def _fmt_srt_time(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    ms = int(round((s - int(s)) * 1000))
    if ms == 1000:
        ms = 0
        sec += 1
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _fmt_ass_time(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        cs = 0
        sec += 1
    return f"{h:d}:{m:02d}:{sec:02d}.{cs:02d}"


def _hex_to_ass_bgr(color: str) -> str:
    """Convert ``#RRGGBB`` to ASS ``BBGGRR``. Default white on parse failure."""
    c = (color or "").strip().lstrip("#")
    if len(c) != 6:
        return "FFFFFF"
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return f"{b:02X}{g:02X}{r:02X}"
    except ValueError:
        return "FFFFFF"


# ── Sentence splitter (simple, language-aware) ──────────────────────────────
def _split_for_lines(text: str, *, max_chars_per_line: int = 42) -> List[str]:
    """Soft-wrap a long single-line caption into ≤2 lines for readability."""
    words = (text or "").split()
    if not words:
        return [""]
    lines: List[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip() if cur else w
        if len(test) > max_chars_per_line and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) > 2 else lines


# ── SRT writer ───────────────────────────────────────────────────────────────
def write_srt(
    segments: Iterable[dict],
    out_path: Path,
    *,
    max_chars_per_line: int = 42,
) -> Path:
    """Write a UTF-8 SRT file. Empty/zero-length segments are skipped."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    idx = 1
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or (start + 1.5))
        if end <= start:
            end = start + 1.5
        wrapped = _split_for_lines(text, max_chars_per_line=max_chars_per_line)
        lines.append(str(idx))
        lines.append(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}")
        lines.extend(wrapped)
        lines.append("")  # blank separator
        idx += 1
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out_path


# ── ASS writer (styled with a title bar and optional side panels) ───────────
def write_ass(
    segments: Iterable[dict],
    out_path: Path,
    *,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    font_name: str = "Arial",
    font_size: int = 56,
    font_color: str = "#FFFFFF",
    outline_color: str = "#000000",
    outline_width: int = 3,
    shadow: int = 1,
    margin_v: int = 80,
    alignment: int = 2,           # bottom-center
    title_text: str = "",
    title_size_pct: float = 6.0,
    title_color: str = "#FFFFFF",
    title_bar_color: str = "#1A73E8",
    title_bar_h_pct: float = 9.0,
    max_chars_per_line: int = 42,
) -> Path:
    """Write a styled ASS file containing dialogue + (optional) title bar.

    The title bar is drawn for the entire video duration (first dialogue
    start → last dialogue end). Pass ``title_text=""`` to disable it.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seg_list = list(segments)

    # Determine total duration window for the title bar
    total_end = 0.0
    for seg in seg_list:
        end = float(seg.get("end") or 0.0)
        if end > total_end:
            total_end = end

    # ── Compute geometry ────────────────────────────────────────────────
    title_bar_h = max(40, int(play_res_y * title_bar_h_pct / 100))
    title_font_px = max(20, int(play_res_x * title_size_pct / 100))

    sub_primary = f"&H00{_hex_to_ass_bgr(font_color)}"
    sub_outline = f"&H00{_hex_to_ass_bgr(outline_color)}"
    sub_back = "&H80000000"
    title_bar_bgr = _hex_to_ass_bgr(title_bar_color)
    title_text_bgr = _hex_to_ass_bgr(title_color)

    # ── Build header ─────────────────────────────────────────────────────
    header = [
        "[Script Info]",
        "Title: DuyTris Manga Video",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Default subtitle style
        f"Style: Default,{font_name},{font_size},{sub_primary},&H000000FF,{sub_outline},{sub_back},"
        f"-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},40,40,{margin_v},1",
        # Title bar background
        f"Style: TitleBar,Arial,1,&H00{title_bar_bgr},&H00{title_bar_bgr},&H00{title_bar_bgr},"
        f"&H00{title_bar_bgr},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        # Title text (centered top, bold, no outline)
        f"Style: TitleText,{font_name},{title_font_px},&H00{title_text_bgr},&H000000FF,&H00000000,"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,0,0,8,40,40,{title_bar_h // 5},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: List[str] = []

    # ── Title bar (drawn for the whole timeline if title_text provided) ─
    if title_text and total_end > 0:
        bar_x1, bar_y1 = 0, 0
        bar_x2, bar_y2 = play_res_x, title_bar_h
        draw = (
            f"{{\\an7\\p1}}m {bar_x1} {bar_y1} l {bar_x2} {bar_y1}"
            f" {bar_x2} {bar_y2} {bar_x1} {bar_y2}"
        )
        events.append(
            f"Dialogue: 0,{_fmt_ass_time(0)},{_fmt_ass_time(total_end)},"
            f"TitleBar,,0,0,0,,{draw}"
        )
        # Centered title text on top
        events.append(
            f"Dialogue: 0,{_fmt_ass_time(0)},{_fmt_ass_time(total_end)},"
            f"TitleText,,0,0,0,,{title_text}"
        )

    # ── Dialogue events ──────────────────────────────────────────────────
    for seg in seg_list:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or (start + 1.5))
        if end <= start:
            end = start + 1.5
        wrapped = _split_for_lines(text, max_chars_per_line=max_chars_per_line)
        ass_text = "\\N".join(wrapped)
        # Escape commas inside text (ASS Format uses commas as separators
        # but the text field is the last so commas are allowed; still, we
        # neutralise hard line breaks)
        ass_text = ass_text.replace("\n", "\\N")
        events.append(
            f"Dialogue: 1,{_fmt_ass_time(start)},{_fmt_ass_time(end)},"
            f"Default,,0,0,0,,{ass_text}"
        )

    out_path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return out_path

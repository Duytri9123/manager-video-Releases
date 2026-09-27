#!/usr/bin/env python3
"""
core.processor.subtitles
Subtitle file parsing (SRT / ASS), time formatting, ASS frame & title generation,
and hardcoded subtitle burning via FFmpeg.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from core.processor.ffmpeg_base import (
    find_ffmpeg, run_ffmpeg, _run_ffmpeg, _get_encoding_args,
    get_media_duration_seconds, _get_media_duration,
    _safe_stem, _winlong, _as_bool, _as_int, _as_float,
    _clamp_float, _normalize_hex_rgb, _ffmpeg_color,
    _escape_drawtext_text, _fmt_hms, has_audio_track
)
from core.processor.effects import (
    _parse_content_aspect,
    _normalize_video_overlays, _append_video_overlay_filters
)


def _fmt_srt_time(seconds: float) -> str:
    h, r = divmod(seconds, 3600)
    m, r = divmod(r, 60)
    s = int(r)
    ms = int((r - s) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{s:02d},{ms:03d}"


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds → ASS timestamp h:mm:ss.cs"""
    total = max(0, round(seconds * 100))
    h, remainder = divmod(total, 360000)
    m, remainder = divmod(remainder, 6000)
    s, cs = divmod(remainder, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _sentence_parts(text: str) -> list[str]:
    # Keep punctuation/closing quotes with the sentence they finish.
    return [p.strip() for p in re.split(r"""(?<=[.!?…。！？])\s+|(?<=[.!?…。！？]["»\"''])\s+""", text) if p.strip()]


# ── Từ nối / chuyển tiếp tiếng Việt thường đứng đầu mệnh đề mới ──────────
_VN_BOUNDARY_WORDS = {
    # Liên từ đối lập
    'Nhưng', 'Tuy', 'Dù', 'Mặc', 'Song', 'Thế',
    # Liên từ nguyên nhân / kết quả
    'Vì', 'Bởi', 'Nên', 'Do',
    # Liên từ bổ sung / tiếp nối
    'Và', 'Còn', 'Cũng', 'Rồi', 'Lại', 'Thêm',
    # Từ chỉ thời gian / điều kiện
    'Khi', 'Lúc', 'Nếu', 'Sau', 'Trước',
    # Từ chỉ mục đích
    'Để', 'Nhằm',
    # Đại từ / chủ ngữ mới (thường bắt đầu mệnh đề)
    'Nó', 'Chúng', 'Họ', 'Mỗi', 'Những', 'Các',
    'Loài', 'Đàn', 'Đây', 'Sự', 'Bầy',
    # Trạng từ đầu câu
    'Chẳng', 'Không', 'Khiến',
}


def _has_punctuation(text: str) -> bool:
    """Kiểm tra text có chứa dấu câu phổ biến không."""
    return bool(re.search(r'[,;:.!?…。，；：！？—]', text))


def _add_punctuation_heuristic(text: str) -> str:
    """
    Chèn dấu phẩy trước các từ nối / chuyển tiếp tiếng Việt viết hoa
    khi text hoàn toàn không có dấu câu (phổ biến với output Whisper).

    Ví dụ:
      "hút cạn máu con sói con đến chết Dù sói con có vùng vẫy"
      → "hút cạn máu con sói con đến chết, Dù sói con có vùng vẫy"
    """
    if _has_punctuation(text):
        return text

    words = text.split()
    if len(words) <= 4:
        return text

    result = [words[0]]
    last_comma_at = -10  # vị trí cuối cùng đã chèn dấu phẩy
    for i in range(1, len(words)):
        w = words[i]
        # Chèn dấu phẩy nếu:
        # 1. Từ viết hoa + nằm trong boundary words
        # 2. Ít nhất 3 từ kể từ đầu hoặc dấu phẩy trước
        # 3. Phải còn ít nhất 3 từ phía sau (tránh chunk mồ côi)
        if (w and w[0].isupper()
                and w in _VN_BOUNDARY_WORDS
                and i >= 3
                and (i - last_comma_at) >= 3
                and (len(words) - i) >= 3):
            result[-1] = result[-1] + ','
            last_comma_at = i
        result.append(w)
    return ' '.join(result)


def _find_best_split_point(words: list, start: int, default_take: int,
                           total: int, max_words: int) -> int:
    """
    Tìm vị trí ngắt tốt nhất gần default_take.
    Ưu tiên: ngắt TRƯỚC từ nối / chuyển tiếp viết hoa (ranh giới mệnh đề).
    """
    min_take = max(2, default_take - 2)
    max_take = min(max_words, default_take + 2, total - start)

    best = default_take
    best_score = -1

    for t in range(min_take, max_take + 1):
        pos = start + t
        if pos >= total:
            if total - start - t == 0:
                return t
            continue

        next_word = words[pos]
        score = 0
        # Ưu tiên cao: từ tiếp theo là boundary word viết hoa
        if next_word in _VN_BOUNDARY_WORDS:
            score = 10
        # Ưu tiên trung bình: từ tiếp theo bắt đầu bằng chữ hoa
        elif next_word and next_word[0].isupper():
            score = 5

        if score > best_score:
            best_score = score
            best = t

    return best


def _smart_split_display_lines(text: str, max_words: int = 9) -> list[str]:
    """
    Tách câu thành các cụm phụ đề ngắn tối đa max_words từ (mặc định 9 từ),
    cắt theo ngữ nghĩa tự nhiên, cân bằng độ dài, không để lại từ mồ côi (1 từ).

    Khi text không có dấu câu (phổ biến với Whisper/AI):
    - Tự động chèn dấu phẩy trước từ nối tiếng Việt viết hoa
    - Ưu tiên ngắt tại ranh giới mệnh đề tự nhiên
    """
    clean_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean_text:
        return []

    # Bước 0: Thêm dấu câu heuristic nếu text không có dấu câu
    clean_text = _add_punctuation_heuristic(clean_text)

    sentences = _sentence_parts(clean_text)
    if len(sentences) > 1:
        return [line for sentence in sentences
                for line in _smart_split_display_lines(sentence, max_words)]
    words = clean_text.split()
    if len(words) <= max_words:
        return [clean_text]

    # Ưu tiên tách theo dấu ngắt tự nhiên (phẩy, chấm phẩy, hai chấm, gạch ngang, etc.)
    clauses = re.split(r"([,;:!?…—]|\s+-\s+)", clean_text)
    chunks: list[str] = []
    current_clause = ""
    for part in clauses:
        if not part:
            continue
        if re.match(r"^[,;:!?…—]$", part.strip()) or part.strip() == "-":
            current_clause += part
            chunks.append(current_clause.strip())
            current_clause = ""
        else:
            if current_clause:
                chunks.append(current_clause.strip())
            current_clause = part
    if current_clause.strip():
        chunks.append(current_clause.strip())

    # Gộp chunks quá ngắn (≤3 từ) vào chunk liền kề để tránh dòng phụ đề quá ngắn
    merged_chunks: list[str] = []
    for c in chunks:
        c_core = re.sub(r'[,;:!?…—]+$', '', c).strip()
        c_word_count = len(c_core.split())
        if merged_chunks and c_word_count <= 3:
            # Gộp vào chunk trước nếu tổng không quá max_words
            prev_words = len(merged_chunks[-1].split())
            if prev_words + c_word_count <= max_words:
                merged_chunks[-1] = merged_chunks[-1] + ' ' + c
                continue
        merged_chunks.append(c)
    chunks = merged_chunks

    final_lines: list[str] = []
    for c in chunks:
        c_words = c.split()
        if not c_words:
            continue
        if len(c_words) <= max_words:
            final_lines.append(c)
        else:
            n = len(c_words)
            idx = 0
            while idx < n:
                rem = n - idx
                parts_needed = max(1, (rem + max_words - 1) // max_words)
                take = (rem + parts_needed - 1) // parts_needed
                take = min(max_words, max(1, take))
                # Tránh để rơi 1-2 từ lẻ ở cuối
                if rem - take <= 2 and take > 3:
                    take = (rem + 1) // 2  # chia đều
                # Tìm điểm ngắt tốt hơn dựa trên ngữ nghĩa (từ nối viết hoa)
                take = _find_best_split_point(c_words, idx, take, n, max_words)
                # Kiểm tra lại: không để 1-2 từ lẻ cuối
                if n - (idx + take) <= 2 and n - (idx + take) > 0 and take > 3:
                    take = (rem + 1) // 2
                chunk_str = " ".join(c_words[idx : idx + take])
                if chunk_str:
                    final_lines.append(chunk_str)
                idx += take

    # Bước cuối: gộp các dòng quá ngắn (≤3 từ) vào dòng trước hoặc sau
    if len(final_lines) > 1:
        merged_final: list[str] = []
        i = 0
        while i < len(final_lines):
            line = final_lines[i]
            line_wc = len(line.split())
            if line_wc <= 3:
                # Thử gộp vào dòng trước
                if merged_final:
                    prev_wc = len(merged_final[-1].split())
                    if prev_wc + line_wc <= max_words:
                        merged_final[-1] = merged_final[-1] + ' ' + line
                        i += 1
                        continue
                # Thử gộp vào dòng sau
                if i + 1 < len(final_lines):
                    next_line = final_lines[i + 1]
                    next_wc = len(next_line.split())
                    if line_wc + next_wc <= max_words:
                        merged_final.append(line + ' ' + next_line)
                        i += 2
                        continue
            merged_final.append(line)
            i += 1
        final_lines = merged_final

    return final_lines if final_lines else [clean_text]


def write_ass(segments: list[dict], out_path: Path,
              font_size: int = 32, font_color: str = "white",
              outline_color: str = "black", outline_width: int = 2,
              shadow: int = 1, margin_v: int = 20,
              alignment: int = 2, font_name: str = "Arial",
              play_res_x: int = 1280, play_res_y: int = 720,
              font_bold: bool = True, max_words_per_line: int = 7) -> Path:
    """
    Write ASS subtitle file from segments list.
    alignment: 2=bottom-center, 8=top-center
    """
    primary  = f"&H00{_hex_color(font_color)}"
    outline  = f"&H00{_hex_color(outline_color)}"
    shadow_c = "&H80000000"
    bold_val = -1 if font_bold else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},{shadow_c},{bold_val},0,0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in segments:
        text = seg.get("text", "").replace("\n", " ").strip()
        # Clean any remaining timestamp leak or brackets
        text = re.sub(
            r'\[?\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*(?:-->|->|-)\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*\]?',
            '',
            text
        ).strip()
        text = re.sub(r'\[\s*\]', '', text).strip()
        text = ' '.join(text.split())
        if not text:
            continue
        split_lines = ([text] if seg.get("voice_aligned") else
                       _smart_split_display_lines(text, max_words=max_words_per_line))
        total_len = sum(len(c) for c in split_lines) or 1
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_duration = max(0.2, seg_end - seg_start)
        cur_t = seg_start
        for i, line in enumerate(split_lines):
            chunk_ratio = len(line) / total_len
            chunk_dur = seg_duration * chunk_ratio
            sub_start = cur_t
            sub_end = cur_t + chunk_dur
            if i == len(split_lines) - 1:
                sub_end = seg_end
            else:
                sub_end = max(sub_start + 0.1, sub_end - 0.01)
            cur_t = sub_end + 0.01
            s = _fmt_ass_time(sub_start)
            e = _fmt_ass_time(sub_end)
            spk_name = "Nam" if seg.get("speaker") == "male" else ("Nữ" if seg.get("speaker") == "female" else "")
            lines.append(f"Dialogue: 0,{s},{e},Default,{spk_name},0,0,0,,{line}")

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _parse_time_smart(t_str: str, video_dur: float | None = None) -> float:
    """Parse time string with robust format detection (HH:MM:SS.mmm, MM:SS:CC, MM:SS.mmm, MM:SS)."""
    t_str = str(t_str or "").strip().replace(",", ".")
    t_str = re.sub(r"[\[\]\s]", "", t_str)
    parts = t_str.split(":")
    try:
        if len(parts) == 3:
            p0, p1, p2 = float(parts[0]), float(parts[1]), float(parts[2])
            val = p0 * 3600.0 + p1 * 60.0 + p2
            # If time exceeds video length, AI likely wrote MM:SS:CC or MM:SS.centisec
            if video_dur and video_dur > 0 and val > video_dur:
                alt1 = p0 * 60.0 + p1 + p2 / 100.0
                if alt1 <= video_dur + 5.0:
                    return alt1
                alt2 = p1 + p2 / 60.0
                if alt2 <= video_dur + 5.0:
                    return alt2
            return val
        elif len(parts) == 2:
            p0, p1 = float(parts[0]), float(parts[1])
            val = p0 * 60.0 + p1
            if video_dur and video_dur > 0 and val > video_dur:
                alt = p0 + p1 / 100.0
                if alt <= video_dur + 5.0:
                    return alt
            return val
        elif len(parts) == 1:
            return float(parts[0])
    except Exception:
        pass
    return 0.0


def _parse_srt(srt_path: Path, video_dur: float | None = None) -> list[dict]:
    """Parse SRT → list of {index, start, end, text} with robust timestamp handling."""
    segments = []
    if not Path(srt_path).exists():
        return segments
    content = Path(srt_path).read_text(encoding="utf-8", errors="replace")
    raw_segs = _parse_srt_text_to_segments(content, video_dur=video_dur)
    for i, s in enumerate(raw_segs, 1):
        segments.append({
            'index': i,
            'start': s['start'],
            'end': s['end'],
            'text': s['text']
        })
    return segments


def _parse_ass_file(ass_path: Path) -> list[dict]:
    """Parse ASS subtitle file → list of {start, end, text} dicts (seconds as float)."""
    def _ass_time_to_sec(t: str) -> float:
        """Convert ASS time string H:MM:SS.cc to seconds."""
        try:
            h, m, rest = t.strip().split(":")
            s, cs = rest.split(".")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0
        except Exception:
            return 0.0

    segments = []
    try:
        content = Path(ass_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return segments

    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        # Format: Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        try:
            style = parts[3].strip().lower()
            raw_text = parts[9].strip()
            if style in {"titlebar", "titletext", "blurleft", "blurright"}:
                continue
            if re.search(r"\\p[1-9]", raw_text, flags=re.IGNORECASE):
                continue
            start = _ass_time_to_sec(parts[1])
            end   = _ass_time_to_sec(parts[2])
            text  = raw_text
            # Strip ASS override tags like {\an8}
            text  = re.sub(r'\{[^}]*\}', '', text).strip()
            text  = text.replace("\\N", " ").replace("\\n", " ")
            text  = re.sub(
                r'\[?\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*(?:-->|->|-)\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*\]?',
                '',
                text
            ).strip()
            text  = re.sub(r'\[\s*\]', '', text).strip()
            text  = re.sub(r"\s+", " ", text).strip()
            clean_text, detected_spk = extract_speaker_from_text(text)
            text = clean_text
            spk = None
            if len(parts) >= 5:
                name_val = parts[4].strip().lower()
                if "nam" in name_val or "male" in name_val:
                    spk = "male"
                elif "nữ" in name_val or "nu" in name_val or "female" in name_val:
                    spk = "female"
            spk = spk or detected_spk
            if text:
                seg_dict = {"start": start, "end": end, "text": text}
                if spk:
                    seg_dict["speaker"] = spk
                segments.append(seg_dict)
        except Exception:
            continue
    return segments


def extract_speaker_from_text(text: str) -> tuple[str, str | None]:
    """
    Tách nhãn người nói (speaker tag) ra khỏi text của phụ đề.
    Ví dụ:
      "[Nam]: Xin chào các bạn" -> ("Xin chào các bạn", "male")
      "[Nữ]: Cho em hỏi chút"   -> ("Cho em hỏi chút", "female")
      "(Nam) - Đi thôi em"     -> ("Đi thôi em", "male")
      "Nữ: Vâng anh ơi!"       -> ("Vâng anh ơi!", "female")
      "[男]: 大家好"           -> ("大家好", "male")
      "Speaker 1: Hi"          -> ("Hi", "male")
      "Speaker 2: Hello"       -> ("Hello", "female")
    
    Returns:
      (clean_text, speaker_type)
      speaker_type: 'male' | 'female' | None
    """
    if not text:
        return "", None
    t = text.strip()
    
    # 1. Khớp có dấu hai chấm / gạch ngang ngăn cách
    # Nam:
    m_male = re.match(
        r'^(?:\[|\()?\s*(nam|đàn\s*ông|male|man|anh|trai|chú|bác|bố|ông|cậu|speaker\s*1|người\s*1|nhân\s*vật\s*1|男|男人|男生|男声|男1)\s*(?:\]|\))?\s*[:：\-]\s*',
        t, flags=re.IGNORECASE
    )
    if m_male:
        clean = t[m_male.end():].strip()
        return clean, "male"

    # Nữ:
    m_fem = re.match(
        r'^(?:\[|\()?\s*(nữ|nu|phụ\s*nữ|female|woman|chị|gái|cô|bà|mẹ|em|bé\s*gái|speaker\s*2|người\s*2|nhân\s*vật\s*2|女|女人|女生|女声|女1)\s*(?:\]|\))?\s*[:：\-]\s*',
        t, flags=re.IGNORECASE
    )
    if m_fem:
        clean = t[m_fem.end():].strip()
        return clean, "female"

    # 2. Khớp trong ngoặc vuông không cần dấu hai chấm: [Nam] Xin chào / [Nữ] Chào anh
    m_b_male = re.match(
        r'^\[\s*(nam|đàn\s*ông|male|man|anh|speaker\s*1|người\s*1|男|男声)\s*\]\s*',
        t, flags=re.IGNORECASE
    )
    if m_b_male:
        clean = t[m_b_male.end():].strip()
        return clean, "male"

    m_b_fem = re.match(
        r'^\[\s*(nữ|nu|phụ\s*nữ|female|woman|chị|speaker\s*2|người\s*2|女|女声)\s*\]\s*',
        t, flags=re.IGNORECASE
    )
    if m_b_fem:
        clean = t[m_b_fem.end():].strip()
        return clean, "female"

    return t, None


def process_speaker_tags_in_segments(segments: list[dict]) -> list[dict]:
    """Tách nhãn người nói trong từng segment, làm sạch text và lưu vào seg['speaker']."""
    for seg in (segments or []):
        raw_text = str(seg.get("text") or "")
        clean_text, spk = extract_speaker_from_text(raw_text)
        seg["text"] = clean_text
        if spk and not seg.get("speaker"):
            seg["speaker"] = spk
    return segments


def _merge_segments_for_tts(
    segments: list[dict],
    max_gap: float = 1.5,
    max_words: int = 18,
    max_chars: int = 120,
    max_duration: float = 8.0,
) -> list[dict]:
    """
    Gộp các đoạn phụ đề thành các câu thoại hoàn chỉnh, có ý nghĩa trọn vẹn cho TTS đọc.
    - Không cắt câu máy móc theo số từ.
    - Một câu chỉ kết thúc khi gặp dấu kết thúc câu thực sự (. ! ? …).
    - Câu dài (> max_words hoặc > max_duration) chỉ tách tại điểm ngắt tự nhiên (phẩy, chấm phẩy, liên từ)
      để người đọc nhấp nhả, lấy hơi tự nhiên mà không bị ngắt ngứ giữa chừng.
    """
    merged: list[dict] = []
    current: dict | None = None
    _SENT_END_PUNCT = ('.', '!', '?', '…', '。', '！', '？')
    _PAUSE_PUNCT = (',', ';', ':', ' - ', '—', '；', '：')

    # An ASS display row can contain the end of one sentence and the beginning
    # of the next. Recover those boundaries before joining adjacent rows.
    sentence_segments = []
    for seg in segments or []:
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        parts = _sentence_parts(text)
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        weight = sum(len(p) for p in parts) or 1
        cursor = start
        for index, part in enumerate(parts):
            stop = end if index == len(parts) - 1 else cursor + (end - start) * len(part) / weight
            sentence_segments.append({**seg, "text": part, "start": cursor, "end": stop})
            cursor = stop

    for seg in sorted(sentence_segments, key=lambda s: float(s.get("start", 0.0))):
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if end <= start:
            continue

        spk = seg.get("speaker")
        item = {"start": start, "end": end, "text": text}
        if spk:
            item["speaker"] = spk

        if current is None:
            current = item
            continue

        # Không gộp nếu hai câu thuộc hai nhân vật (speaker) khác nhau!
        if current.get("speaker") != spk:
            merged.append(current)
            current = item
            continue

        gap = start - float(current.get("end", start))
        curr_text = current.get("text", "").rstrip()
        curr_words = curr_text.split()
        new_words = text.split()
        combined_words = len(curr_words) + len(new_words)
        combined_text = f"{curr_text} {text}".strip()
        combined_duration = end - float(current.get("start", start))

        # 1. Nếu đoạn trước đã kết thúc câu bằng dấu chấm/hỏi/cảm thán
        current_ends_sentence = curr_text.rstrip('”»"\'’').endswith(_SENT_END_PUNCT)
        if current_ends_sentence:
            merged.append(current)
            current = item
            continue

        # 2. Nếu đoạn trước CHƯA hết câu, nhưng độ dài đã quá lớn (cần nhấp nhả/ngắt nghỉ)
        if combined_words > max_words or combined_duration > max_duration or len(combined_text) > max_chars:
            # Always split — this keeps individual TTS clips short and avoids overflow
            merged.append(current)
            current = item
            continue

        # 3. Gộp câu nếu khoảng cách nghỉ trong cùng một câu hợp lý (gap <= max_gap)
        if gap <= max_gap:
            current["end"] = max(float(current["end"]), end)
            current["text"] = combined_text
        else:
            merged.append(current)
            current = item

    if current is not None:
        merged.append(current)
    return merged


def align_subtitles_to_voice(
    segments: list[dict],
    tts_clips: list[dict],
    ffmpeg: str = "ffmpeg",
    video_duration: float | None = None,
    min_gap: float = 0.08,
    max_speed_factor: float = 1.7,
) -> tuple[list[dict], list[dict]]:
    """Anchor every utterance to the video; never ripple later speech forward.

    A modest tempo correction fits long speech into its own window. If that
    cannot fit naturally, fail explicitly instead of overlapping or truncating.
    """
    if not tts_clips or not segments:
        return tts_clips, segments
    import math
    from core.processor.ffmpeg_base import _get_audio_duration
    from core.processor.tts import _apply_atempo

    ordered = sorted(enumerate(segments), key=lambda pair: float(pair[1]["start"]))
    windows = {}
    for position, (idx, seg) in enumerate(ordered):
        start = max(0.0, float(seg["start"]))
        end = float(seg["end"])
        # Borrow only the immediately following silence (at most 0.5s).
        # Distinct voices may overlap only when the source dialogue overlaps.
        boundary = video_duration if video_duration and video_duration > 0 else end
        for _, following in ordered[position + 1:]:
            other_start = float(following["start"])
            distinct = (seg.get("speaker") and following.get("speaker")
                        and seg["speaker"] != following["speaker"])
            if distinct and other_start < float(seg["end"]):
                continue
            boundary = min(boundary, other_start - min_gap)
            break
        end = min(end + 0.5, boundary)
        windows[idx] = (start, end)

    aligned_clips, aligned_segments = [], []
    for original in sorted(tts_clips, key=lambda c: windows[int(c["index"])][0]):
        clip = dict(original)
        idx = int(clip["index"])
        seg = segments[idx]
        start, limit = windows[idx]
        available = limit - start
        duration = float(clip.get("duration") or _get_audio_duration(ffmpeg, Path(clip["path"])))
        speed = 1.0
        if not math.isfinite(duration) or duration <= 0 or available <= 0:
            raise ValueError(f"Câu {idx + 1}: thời lượng âm thanh hoặc mốc phụ đề không hợp lệ")
        if duration > available:
            # Leave a small encoding margin and measure the resulting file again.
            speed = duration / max(0.001, available - 0.02)
            if speed > max_speed_factor:
                import logging
                logging.getLogger("core.processor").warning(
                    f"Câu {idx + 1} cần {duration:.2f}s nhưng chỉ có {available:.2f}s. "
                    f"Tốc độ {speed:.2f}x vượt ngưỡng {max_speed_factor}x. Sẽ ép chạy ở {max_speed_factor}x (có thể bị chèn thời gian)."
                )
                speed = max_speed_factor
            src = Path(clip["path"])
            dst = src.with_name(src.stem + "_sync.wav")
            if not _apply_atempo(ffmpeg, src, dst, speed):
                raise ValueError(f"Không điều chỉnh được thời lượng câu {idx + 1}")
            duration = _get_audio_duration(ffmpeg, dst)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(f"Lỗi tính thời lượng câu {idx + 1} sau khi căn giọng")
            clip["path"] = dst
        clip.update(start=start, end=start + duration, duration=duration,
                    tempo_factor=speed,
                    speaker=seg.get("speaker"), source_start=float(seg["start"]),
                    source_end=float(seg["end"]))
        aligned_clips.append(clip)
        
        # Clamp visual subtitle end time to prevent text stacking/overlapping on screen
        visual_end = min(start + duration, limit)
        aligned_segments.append(dict(seg, start=start, end=visual_end, voice_aligned=True))
    return aligned_clips, aligned_segments



def _parse_srt_text_to_segments(srt_text: str, video_dur: float | None = None) -> list[dict]:
    import re
    if not srt_text:
        return []
    srt_text = re.sub(r"^```[a-zA-Z]*\n?", "", srt_text.strip(), flags=re.MULTILINE)
    srt_text = re.sub(r"```$", "", srt_text.strip())

    # Universal timestamp pattern:
    # 00:00:01,000 --> 00:00:04,000 or [ 00:40,280 --> 00:41,200 ] or 01:23.456 -> 01:25.789
    ts_regex = re.compile(
        r'\[?\s*(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)\s*(?:-->|->|-)\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[,\.]\d{1,3})?)\s*\]?'
    )

    matches = list(ts_regex.finditer(srt_text))
    segments = []

    if len(matches) > 1:
        # Sequence of timestamps (inline or standard format)
        for i in range(len(matches)):
            start_str = matches[i].group("start")
            end_str = matches[i].group("end")
            start_sec = _parse_time_smart(start_str, video_dur=video_dur)
            end_sec = _parse_time_smart(end_str, video_dur=video_dur)

            start_pos = matches[i].end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(srt_text)
            seg_text = srt_text[start_pos:end_pos].strip()

            # Clean trailing digit index (from standard SRT before next block)
            seg_text = re.sub(r'\n\s*\d+\s*$', '', seg_text).strip()
            # Clean leading bracket or punctuation residues
            seg_text = re.sub(r'^\s*[\d\.\,\-\]]+\s*', '', seg_text).strip()
            # Remove any internal timestamp leakage
            seg_text = re.sub(
                r'\[?\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*(?:-->|->|-)\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*\]?',
                '',
                seg_text
            ).strip()
            seg_text = re.sub(r'\[\s*\]', '', seg_text).strip()
            seg_text = ' '.join(seg_text.split())

            if not seg_text:
                continue

            if end_sec <= start_sec:
                dur_est = max(1.5, min(7.0, len(seg_text) * 0.22))
                end_sec = start_sec + dur_est

            segments.append({"start": round(start_sec, 3), "end": round(end_sec, 3), "text": seg_text})

    # Fallback to standard blank-line separated blocks if above didn't produce multiple segments
    if not segments:
        blocks = re.split(r"\n\s*\n", srt_text.strip())
        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            time_idx = -1
            for idx, line in enumerate(lines):
                if re.search(r'\d{1,2}:\d{2}.*(?:-->|->|-).*\d{1,2}:\d{2}', line):
                    time_idx = idx
                    break
            if time_idx != -1 and time_idx + 1 < len(lines):
                time_line = lines[time_idx]
                tm = ts_regex.search(time_line)
                if tm:
                    try:
                        start_sec = _parse_time_smart(tm.group("start"), video_dur=video_dur)
                        end_sec = _parse_time_smart(tm.group("end"), video_dur=video_dur)
                        text = " ".join(lines[time_idx + 1:]).strip()
                        # Clean any leaked timestamp artifacts
                        text = re.sub(
                            r'\[?\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*(?:-->|->|-)\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*\]?',
                            '',
                            text
                        ).strip()
                        text = re.sub(r'\[\s*\]', '', text).strip()
                        text = ' '.join(text.split())
                        if text:
                            if end_sec <= start_sec:
                                dur_est = max(1.5, min(7.0, len(text) * 0.22))
                                end_sec = start_sec + dur_est
                            segments.append({"start": round(start_sec, 3), "end": round(end_sec, 3), "text": text})
                    except Exception:
                        pass

    # Sort segments by start time
    segments.sort(key=lambda s: s["start"])

    # Fix overlapping or inverted timestamps across consecutive lines
    for i in range(len(segments)):
        if i + 1 < len(segments):
            next_start = segments[i + 1]["start"]
            if segments[i]["end"] > next_start and next_start > segments[i]["start"]:
                segments[i]["end"] = max(segments[i]["start"] + 1.0, next_start - 0.05)
    return segments


def _subtitle_blur_enable(segments):
    """Return the overlay ``enable`` option for subtitle cue intervals.

    None means continuous; an empty list explicitly disables the mask.  FFmpeg
    evaluates the expression for every frame and, on Windows builds in
    particular, very long expressions can fail while the filter graph is being
    initialised (or report a misleading ``Cannot allocate memory`` error).
    For a subtitle track with many disjoint cues, keeping the small subtitle
    hiding strip blurred continuously is both visually safe and far cheaper.
    """
    if segments is None:
        return ""
    import math
    intervals = []
    for seg in segments:
        try:
            start, end = max(0.0, float(seg['start'])), float(seg['end'])
            if str(seg.get('text', '')).strip() and math.isfinite(start) and math.isfinite(end) and end > start:
                intervals.append((start, end))
        except (KeyError, TypeError, ValueError):
            continue
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    # Keep the filter graph bounded.  A 64-interval expression is already a
    # few kilobytes long; beyond that a continuous overlay is more robust and
    # avoids per-frame evaluation of hundreds of gte()/lt() terms.
    if len(merged) > 64:
        return ""
    expr = '+'.join(f'gte(t,{start:.3f})*lt(t,{end:.3f})' for start, end in merged) or '0'
    return f":enable='{expr}'"


def burn_subtitles(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    ffmpeg: str,
    blur_original: bool = True,
    blur_zone: str = "bottom",
    blur_height_pct: float = 0.15,
    blur_width_pct: float = 0.80,
    blur_lift_pct: float = 0.06,
    font_size: int = 18,
    font_color: str = "white",
    outline_color: str = "black",
    outline_width: int = 2,
    margin_v: int = 30,
    subtitle_position: str = "bottom",
    subtitle_format: str = "srt",
    font_name: str = "Arial",
    # Frame video params
    frame_enabled: bool = False,
    frame_title: str = "",
    frame_title_size_pct: float = 5.0,
    frame_title_color: str = "#000000",
    frame_blur_w_pct: float = 15.0,
    frame_blur_opacity: float = 0.6,
    frame_target_w: int = 1080,
    log_callback=None,
    blur_y_pct: Optional[float] = None,
    blur_x_pct: Optional[float] = None,
    blur_extra_zones: Optional[list] = None,
    video_overlays: Optional[list] = None,
    target_aspect: str = "auto",
    aspect_pad_blur: bool = False,
    content_aspect: str = "auto",
    content_aspect_mode: str = "crop",
    mask_config: dict | None = None,
    output_fps: int = 0,
    encode_device: str = "auto",
    blur_subtitle_segments: Optional[list] = None,
) -> tuple[bool, str]:
    """
    Burn subtitles into video.
    If subtitle_format='ass': use ASS filter (no blur needed, faster).
    If subtitle_format='srt': use SRT with optional blur strip.
    If frame_enabled=True: also creates 9:16 frame in same encode pass (ASS mode only).
    Aspect conversion is folded into the ASS encode when requested.
    """
    # Use the same compositor for imported SRT files when new visual options are active.
    if str(subtitle_format).lower() != "ass" and (
        _parse_content_aspect(content_aspect) is not None
        or (isinstance(mask_config, dict) and mask_config.get("mode") == "patch")
    ):
        options = locals().copy()
        with tempfile.TemporaryDirectory(prefix="compose_srt_") as directory:
            converted = Path(directory) / "subtitles.ass"
            result = subprocess.run(
                [str(ffmpeg), "-y", "-v", "error", "-i", str(srt_path), str(converted)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode:
                return False, result.stderr
            options.update(srt_path=converted, subtitle_format="ass")
            return burn_subtitles(**options)

    # Tự động căn giữa vùng che blur với phụ đề (chỉ khi không có blur_y_pct)
    blur_lift_pct_adj = blur_lift_pct
    if blur_y_pct is None and blur_original and blur_zone != "none":
        video_height = 1080
        sub_height = font_size + 2 * outline_width
        if subtitle_position == "bottom":
            sub_y = video_height - margin_v - sub_height // 2
            blur_h = int(video_height * blur_height_pct)
            blur_y = sub_y - blur_h // 2
            blur_lift_pct_adj = max(0.0, 1.0 - (blur_y + blur_h) / video_height)
            if log_callback:
                log_callback(f"📏 Tính vùng che: sub_y={sub_y}px, blur_y={blur_y}→{blur_y+blur_h}px, lift_adj={blur_lift_pct_adj:.3f}", "info")
        elif subtitle_position == "top":
            sub_y = margin_v + sub_height // 2
            blur_h = int(video_height * blur_height_pct)
            blur_y = sub_y - blur_h // 2
            blur_lift_pct_adj = max(0.0, blur_y / video_height)
            if log_callback:
                log_callback(f"📏 Tính vùng che (top): sub_y={sub_y}px, blur_y={blur_y}→{blur_y+blur_h}px, lift_adj={blur_lift_pct_adj:.3f}", "info")

    if str(subtitle_format).lower() == "ass":
        return _burn_ass(video_path, srt_path, output_path, ffmpeg,
                         font_size, font_color, outline_color, outline_width,
                         margin_v, subtitle_position,
                         blur_original, blur_zone, blur_height_pct, blur_width_pct, blur_lift_pct_adj, font_name,
                         frame_enabled=frame_enabled,
                         frame_title=frame_title,
                         frame_title_size_pct=frame_title_size_pct,
                         frame_title_color=frame_title_color,
                         frame_blur_w_pct=frame_blur_w_pct,
                         frame_blur_opacity=frame_blur_opacity,
                         frame_target_w=frame_target_w,
                         log_callback=log_callback,
                         blur_y_pct=blur_y_pct,
                         blur_x_pct=blur_x_pct,
                         blur_extra_zones=blur_extra_zones,
                         blur_subtitle_segments=blur_subtitle_segments,
                         video_overlays=video_overlays,
                         target_aspect=target_aspect,
                         aspect_pad_blur=aspect_pad_blur,
                         content_aspect=content_aspect, content_aspect_mode=content_aspect_mode, mask_config=mask_config,
                         output_fps=output_fps, encode_device=encode_device)

    # SRT path (original logic — no frame support)
    return _burn_srt(video_path, srt_path, output_path, ffmpeg,
                     blur_original, blur_zone, blur_height_pct, blur_width_pct, blur_lift_pct_adj,
                     font_size, font_color, outline_color, outline_width,
                     margin_v, subtitle_position,
                     blur_y_pct=blur_y_pct,
                     blur_x_pct=blur_x_pct,
                     blur_extra_zones=blur_extra_zones,
                     blur_subtitle_segments=blur_subtitle_segments,
                     video_overlays=video_overlays)


def _burn_ass(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    ffmpeg: str,
    font_size: int = 32,
    font_color: str = "white",
    outline_color: str = "black",
    outline_width: int = 2,
    margin_v: int = 20,
    subtitle_position: str = "bottom",
    blur_original: bool = False,
    blur_zone: str = "bottom",
    blur_height_pct: float = 0.15,
    blur_width_pct: float = 0.80,
    blur_lift_pct: float = 0.06,
    font_name: str = "Arial",
    # Legacy frame params (ignored — frame is now embedded in ASS file)
    frame_enabled: bool = False,
    frame_title: str = "",
    frame_title_size_pct: float = 5.0,
    frame_title_color: str = "#000000",
    frame_blur_w_pct: float = 15.0,
    frame_blur_opacity: float = 0.6,
    frame_target_w: int = 1080,
    log_callback=None,
    blur_y_pct: Optional[float] = None,
    blur_x_pct: Optional[float] = None,
    blur_extra_zones: Optional[list] = None,
    video_overlays: Optional[list] = None,
    target_aspect: str = "auto",
    aspect_pad_blur: bool = False,
    content_aspect: str = "auto",
    content_aspect_mode: str = "crop",
    mask_config: dict | None = None,
    output_fps: int = 0,
    encode_device: str = "auto",
    blur_subtitle_segments: Optional[list] = None,
) -> tuple[bool, str]:
    """Burn ASS subtitle file into video. Optionally blur a zone to hide burned-in original subs.
    Frame elements (title bar, blur panels) are now embedded directly in the ASS file.
    log_callback: optional callable(msg, level) for progress logging.
    """
    import time as _time

    def _log(msg, level="info"):
        if log_callback:
            log_callback(msg, level)

    t0 = _time.time()
    _log(f"📂 Video: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")
    _log(f"📄 Phụ đề: {ass_path.name}")
    _log(f"⚙️ Cài đặt: font={font_size}px, color={font_color}, margin={margin_v}px, pos={subtitle_position}")
    if blur_original:
        _log(f"🌫 Che phụ đề gốc: zone={blur_zone}, height={blur_height_pct*100:.0f}%")

    video_path  = Path(video_path)
    ass_path    = Path(ass_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="burn_ass_") as tmpdir:
        tmp_video = Path(tmpdir) / "input.mp4"
        tmp_ass   = Path(tmpdir) / "subs.ass"
        tmp_out   = Path(tmpdir) / "output.mp4"

        t1 = _time.time()
        _log("📋 Đang copy file vào thư mục tạm...")
        # A read-only hard link avoids copying large inputs on the same volume.
        # Cleanup removes only this temporary name, never the original file.
        try:
            os.link(str(video_path.resolve()), str(tmp_video))
        except OSError:
            shutil.copy2(str(video_path), str(tmp_video))
        _log(f"✓ Copy video xong ({_time.time()-t1:.1f}s)")

        # If input is SRT, convert to ASS on the fly
        if ass_path.suffix.lower() == ".srt":
            _log("🔄 Chuyển đổi SRT → ASS...")
            segs = _parse_srt(ass_path)
            alignment = 8 if str(subtitle_position).lower() == "top" else 2
            tmp_ass = write_ass(segs, tmp_ass, font_size=font_size,
                                font_color=font_color, outline_color=outline_color,
                                outline_width=outline_width, margin_v=margin_v,
                                alignment=alignment, font_name=font_name)
            _log(f"✓ Chuyển đổi xong: {len(segs)} đoạn phụ đề")
        else:
            shutil.copy2(str(ass_path), str(tmp_ass))
            _log(f"✓ Copy phụ đề ASS xong")

        ass_esc = str(tmp_ass).replace("\\", "/")
        if len(ass_esc) >= 2 and ass_esc[1] == ':':
            ass_esc = ass_esc[0] + "\\:" + ass_esc[2:]

        # Fold aspect conversion into this encode when source and target
        # orientations differ.
        try:
            _vr = subprocess.run(
                [ffmpeg, "-i", str(tmp_video)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            _vm = re.search(r"(\d{2,5})x(\d{2,5})", _vr.stderr or "")
            _src_w, _src_h = (int(_vm.group(1)), int(_vm.group(2))) if _vm else (1280, 720)
        except Exception:
            _src_w, _src_h = 1280, 720

        _target_aspect = str(target_aspect or "auto").lower()
        _target_w, _target_h = (
            (1080, 1920) if _target_aspect == "9x16" else (1920, 1080)
        )
        _src_is_vertical = _src_h > _src_w
        _content_ratio = _parse_content_aspect(content_aspect)
        if _content_ratio and _target_aspect == "auto":
            _target_w, _target_h = int(_src_w), int(_src_h)
        _aspect_convert = bool(_content_ratio) or _target_aspect in ("9x16", "16x9") and (
            (_target_aspect == "9x16" and not _src_is_vertical)
            or (_target_aspect == "16x9" and _src_is_vertical)
        )
        if _aspect_convert:
            _log(
                f"Aspect trong cung encode: {_src_w}x{_src_h} -> "
                f"{_target_w}x{_target_h} ({_target_aspect})"
            )

        # Check if ASS file has frame/logo info embedded in comments
        _ass_content = ""
        _logo_file = None
        _logo_size_pct = 6.0
        _logo_top_pct = 3.0
        _logo_left_pct = 3.0
        _logo_radius_pct = 50.0
        _logo_position = "top-left"
        _frame_has_elements = False
        _frame_blur_w_pct = 0.0
        _frame_blur_top_pct = 0.0
        _frame_blur_bottom_pct = 0.0
        _frame_blur_opacity = 0.0
        # Expand-mode geometry (px) — đọc từ comment ASS do write_ass_with_frame ghi
        _frame_mode = "overlay"
        _frame_out_w = 0
        _frame_out_h = 0
        _frame_vid_x = 0
        _frame_vid_y = 0
        _frame_vid_w = 0
        _frame_vid_h = 0
        _frame_side_w = 0
        _frame_title_bar_h = 0

        def _ass_comment_float(label: str, default: float = 0.0) -> float:
            m = re.search(rf"^; {re.escape(label)}:\s*([\d.]+)", _ass_content, re.MULTILINE)
            if not m:
                return default
            try:
                return float(m.group(1))
            except Exception:
                return default

        def _ass_comment_int(label: str, default: int = 0) -> int:
            m = re.search(rf"^; {re.escape(label)}:\s*(-?\d+)", _ass_content, re.MULTILINE)
            if not m:
                return default
            try:
                return int(m.group(1))
            except Exception:
                return default

        try:
            _ass_content = tmp_ass.read_text(encoding="utf-8")
            _frame_has_elements = bool(re.search(r"^; Frame elements embedded:", _ass_content, re.MULTILINE))
            _logo_match = re.search(r"^; Logo:\s*(.+)$", _ass_content, re.MULTILINE)
            if _logo_match:
                _lp = _logo_match.group(1).strip()
                if _lp and Path(_lp).exists():
                    _logo_file = Path(_lp)
            if _frame_has_elements:
                _frame_blur_w_pct = _clamp_float(_ass_comment_float("Blur width", 0.0) / 100.0, 0.0, 0.45)
                _frame_blur_top_pct = _clamp_float(_ass_comment_float("Blur top", 0.0) / 100.0, 0.0, 0.60)
                _frame_blur_bottom_pct = _clamp_float(_ass_comment_float("Blur bottom", 0.0) / 100.0, 0.0, 0.60)
                _frame_blur_opacity = _ass_comment_float("Blur opacity", 0.0)
                if _frame_blur_opacity > 1.0:
                    _frame_blur_opacity = _frame_blur_opacity / 100.0
                _frame_blur_opacity = _clamp_float(_frame_blur_opacity, 0.0, 1.0)
                # Geometry (chỉ có ý nghĩa khi mode=expand)
                _fm = re.search(r"^; Frame mode:\s*(\w+)", _ass_content, re.MULTILINE)
                if _fm:
                    _frame_mode = _fm.group(1).strip().lower()
                _frame_out_w = _ass_comment_int("Out width px", 0)
                _frame_out_h = _ass_comment_int("Out height px", 0)
                _frame_vid_x = _ass_comment_int("Vid x px", 0)
                _frame_vid_y = _ass_comment_int("Vid y px", 0)
                _frame_vid_w = _ass_comment_int("Vid w px", 0)
                _frame_vid_h = _ass_comment_int("Vid h px", 0)
                _frame_side_w = _ass_comment_int("Side width px", 0)
                _frame_title_bar_h = _ass_comment_int("Title bar h px", 0)
            _logo_size_match = re.search(r"^; Logo size:\s*([\d.]+)%", _ass_content, re.MULTILINE)
            if _logo_size_match:
                _logo_size_pct = float(_logo_size_match.group(1))
            _logo_top_match = re.search(r"^; Logo top:\s*([\d.]+)%", _ass_content, re.MULTILINE)
            if _logo_top_match:
                _logo_top_pct = float(_logo_top_match.group(1))
            _logo_left_match = re.search(r"^; Logo left:\s*([\d.]+)%", _ass_content, re.MULTILINE)
            if _logo_left_match:
                _logo_left_pct = float(_logo_left_match.group(1))
            _logo_radius_match = re.search(r"^; Logo radius:\s*([\d.]+)%", _ass_content, re.MULTILINE)
            if _logo_radius_match:
                _logo_radius_pct = float(_logo_radius_match.group(1))
            _logo_pos_match = re.search(r"^; Logo position:\s*(.+)$", _ass_content, re.MULTILINE)
            if _logo_pos_match:
                _logo_position = _logo_pos_match.group(1).strip()
        except Exception:
            pass

        # Build filter: optional blur zone(s) + ASS + optional logo overlay
        extra_inputs = []
        
        # Gather all active blur zones
        active_zones = []
        if blur_original and blur_zone != "none":
            h_pct = _clamp_float(blur_height_pct, 0.08, 0.45)
            w_pct = max(0.35, min(1.0, float(blur_width_pct)))
            
            y_center = 0.5
            if blur_y_pct is not None:
                y_center = _clamp_float(blur_y_pct, 0.0, 1.0)
            else:
                lift_pct = _clamp_float(blur_lift_pct, 0.0, 0.20)
                if blur_zone == "bottom":
                    y_center = 1.0 - h_pct / 2 - lift_pct
                else:
                    y_center = h_pct / 2
            
            x_center = 0.5 if blur_x_pct is None else _clamp_float(blur_x_pct, 0.0, 1.0)
            
            # Tính toán giới hạn tự co dãn khi vượt biên để khớp với giao diện kéo thả
            left_pct = max(0.0, x_center - w_pct / 2)
            right_pct = min(1.0, x_center + w_pct / 2)
            w_clamped = max(0.01, right_pct - left_pct)
            
            top_pct = max(0.0, y_center - h_pct / 2)
            bottom_pct = min(1.0, y_center + h_pct / 2)
            h_clamped = max(0.01, bottom_pct - top_pct)
            
            active_zones.append((h_clamped, w_clamped, top_pct, left_pct + w_clamped / 2, None, None))
            
        if blur_extra_zones:
            for ez in blur_extra_zones:
                try:
                    ez_h = float(ez.get("height_pct", 0.12))
                    ez_pos = float(ez.get("position_pct", 0.50))
                    ez_w = float(ez.get("width_pct", 0.80))
                    ez_x = float(ez.get("x_pct", 0.50))
                    ez_st = ez.get("start_sec", None)
                    ez_en = ez.get("end_sec", None)
                    ez_y = _clamp_float(ez_pos - ez_h / 2, 0.0, 1.0 - ez_h)
                    active_zones.append((ez_h, ez_w, ez_y, ez_x, ez_st, ez_en))
                except Exception:
                    pass

        # Apply each blur zone in a chain. An untouched source branch is reserved
        # for the background, so foreground masks, ASS, and logos are not repeated.
        filter_complex_parts = []
        # Apply the requested frame rate before expensive filters. Zero keeps
        # the source timestamps/rate unchanged.
        try:
            max_fps = int(output_fps)
        except (TypeError, ValueError):
            max_fps = 0
        if max_fps not in (15, 24, 25, 30, 60):
            max_fps = 0
        source_label = "0:v"
        if max_fps:
            filter_complex_parts.append(
                f"[0:v]fps={max_fps}[rate_limited]"
            )
            source_label = "rate_limited"
            _log(f"⚡ FPS xuất video: {max_fps}")
        if _aspect_convert and aspect_pad_blur:
            filter_complex_parts.append(f"[{source_label}]split=2[aspect_bg_src][aspect_fg_src]")
            curr_label = "aspect_fg_src"
        else:
            curr_label = source_label

        for idx, (h, w, y, x, _st, _en) in enumerate(active_zones):
            next_label = f"b{idx}"
            _left = max(0.0, min(1.0 - w, x - w / 2))
            _en_expr = ""
            if idx == 0 and blur_original and blur_zone != "none":
                _en_expr = _subtitle_blur_enable(blur_subtitle_segments)
            if _st is not None or _en is not None:
                _s0 = float(_st) if _st is not None else 0.0
                _e0 = float(_en) if _en is not None else 1e9
                _en_expr = f":enable='between(t,{_s0:.3f},{_e0:.3f})'"
            filter_complex_parts.append(f"[{curr_label}]split[orig_{idx}][copy_{idx}]")
            _patch = idx == 0 and blur_original and blur_zone != "none" and isinstance(mask_config, dict) and mask_config.get("mode") == "patch"
            if _patch:
                _sx = max(0.0, min(1.0-w, _clamp_float(mask_config.get("source_x", .5), 0, 1)-w/2))
                _sy = max(0.0, min(1.0-h, _clamp_float(mask_config.get("source_y", .75), 0, 1)-h/2))
                filter_complex_parts.append(f"[copy_{idx}]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{_sx:.4f}:ih*{_sy:.4f}[blurred_{idx}]")
            else:
                filter_complex_parts.append(
                    f"[copy_{idx}]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{_left:.4f}:ih*{y:.4f},"
                    f"boxblur=luma_radius='min(20,min(w,h)/2)':luma_power=3:chroma_radius='min(15,min(cw,ch)/2)':chroma_power=2[blurred_{idx}]"
                )
            filter_complex_parts.append(
                f"[orig_{idx}][blurred_{idx}]overlay=W*{_left:.4f}:H*{y:.4f}{_en_expr}[{next_label}]"
            )
            curr_label = next_label
            _log(f"🌫 Vùng che {idx+1}: từ {y*100:.0f}% → {(y+h)*100:.0f}%, rộng {w*100:.0f}%")

        # Frame side/top/bottom panels need real pixel blur before ASS draws the
        # semi-transparent dark overlays. Otherwise they only dim the video.
        # Ở chế độ "expand" (đẩy ra ngoài) việc blur cạnh được làm trong bước dựng
        # canvas bên dưới, nên KHÔNG dùng blur tại chỗ ở đây.
        _is_expand = (
            _frame_has_elements and _frame_mode == "expand"
            and _frame_out_w > 0 and _frame_out_h > 0
            and _frame_vid_w > 0 and _frame_vid_h > 0
        )
        frame_blur_specs = []
        if _frame_has_elements and not _is_expand and _frame_blur_opacity > 0.001:
            if _frame_blur_w_pct > 0.001:
                side_w_expr = f"trunc(iw*{_frame_blur_w_pct:.4f}/2)*2"
                frame_blur_specs.append((
                    "left",
                    f"crop={side_w_expr}:ih:0:0,gblur=sigma=12",
                    "0",
                    "0",
                ))
                frame_blur_specs.append((
                    "right",
                    f"crop={side_w_expr}:ih:iw-{side_w_expr}:0,gblur=sigma=12",
                    "W-w",
                    "0",
                ))
            if _frame_blur_top_pct > 0.001:
                top_h_expr = f"trunc(ih*{_frame_blur_top_pct:.4f}/2)*2"
                frame_blur_specs.append((
                    "top",
                    f"crop=iw:{top_h_expr}:0:0,gblur=sigma=12",
                    "0",
                    "0",
                ))
            if _frame_blur_bottom_pct > 0.001:
                bottom_h_expr = f"trunc(ih*{_frame_blur_bottom_pct:.4f}/2)*2"
                frame_blur_specs.append((
                    "bottom",
                    f"crop=iw:{bottom_h_expr}:0:ih-{bottom_h_expr},gblur=sigma=12",
                    "0",
                    "H-h",
                ))

        for fb_idx, (_name, crop_filter, overlay_x, overlay_y) in enumerate(frame_blur_specs):
            next_label = f"fb{fb_idx}"
            filter_complex_parts.append(f"[{curr_label}]split[frame_orig_{fb_idx}][frame_copy_{fb_idx}]")
            filter_complex_parts.append(f"[frame_copy_{fb_idx}]{crop_filter}[frame_blurred_{fb_idx}]")
            filter_complex_parts.append(
                f"[frame_orig_{fb_idx}][frame_blurred_{fb_idx}]overlay={overlay_x}:{overlay_y}[{next_label}]"
            )
            curr_label = next_label

        if frame_blur_specs:
            _log(
                f"Frame blur: side={_frame_blur_w_pct*100:.0f}%, "
                f"top={_frame_blur_top_pct*100:.0f}%, bottom={_frame_blur_bottom_pct*100:.0f}%"
            )

        # ── Chế độ "Đẩy ra ngoài" (expand): thu nhỏ video + chừa dải tiêu đề ──
        # + lấp 2 bên bằng video blur, dựng đúng layout như preview.
        if _is_expand:
            ow, oh = _frame_out_w, _frame_out_h
            vx, vy = _frame_vid_x, _frame_vid_y
            vw, vh = _frame_vid_w, _frame_vid_h
            sw = _frame_side_w
            # 1. Thu nhỏ video gốc về vùng nội dung
            filter_complex_parts.append(f"[{curr_label}]scale={vw}:{vh},setsar=1[ex_main]")
            _ex_main = "ex_main"
            # 1b. Blur thật dải trên/dưới bên trong video (nếu bật)
            if _frame_blur_opacity > 0.001 and _frame_blur_top_pct > 0.001:
                th = max(2, int(vh * _frame_blur_top_pct)); th -= th % 2
                filter_complex_parts.append(f"[{_ex_main}]split[ex_to][ex_tc]")
                filter_complex_parts.append(f"[ex_tc]crop={vw}:{th}:0:0,gblur=sigma=12[ex_tb]")
                filter_complex_parts.append(f"[ex_to][ex_tb]overlay=0:0[ex_main_t]")
                _ex_main = "ex_main_t"
            if _frame_blur_opacity > 0.001 and _frame_blur_bottom_pct > 0.001:
                bh = max(2, int(vh * _frame_blur_bottom_pct)); bh -= bh % 2
                _by = vh - bh
                filter_complex_parts.append(f"[{_ex_main}]split[ex_bo][ex_bc]")
                filter_complex_parts.append(f"[ex_bc]crop={vw}:{bh}:0:{_by},gblur=sigma=12[ex_bb]")
                filter_complex_parts.append(f"[ex_bo][ex_bb]overlay=0:{_by}[ex_main_b]")
                _ex_main = "ex_main_b"
            # 2. Canvas nền + lấp 2 bên bằng video blur kéo giãn từ mép
            filter_complex_parts.append(f"color=white:{ow}x{oh}:r=30[ex_cv]")
            if sw > 0:
                slice_w = max(2, int(vw * 0.08))
                _crop_rx = max(0, vw - slice_w)
                _right_x = max(0, ow - sw)
                filter_complex_parts.append(f"[{_ex_main}]split=3[ex_mv][ex_ml][ex_mr]")
                filter_complex_parts.append(
                    f"[ex_ml]crop={slice_w}:{vh}:0:0,scale={sw}:{vh},gblur=sigma=20[ex_lfill]"
                )
                filter_complex_parts.append(
                    f"[ex_mr]crop={slice_w}:{vh}:{_crop_rx}:0,scale={sw}:{vh},gblur=sigma=20[ex_rfill]"
                )
                filter_complex_parts.append(f"[ex_cv][ex_lfill]overlay=0:{vy}:shortest=1[ex_c1]")
                filter_complex_parts.append(f"[ex_c1][ex_rfill]overlay={_right_x}:{vy}[ex_c2]")
                filter_complex_parts.append(f"[ex_c2][ex_mv]overlay={vx}:{vy}[ex_framed]")
            else:
                filter_complex_parts.append(f"[ex_cv][{_ex_main}]overlay={vx}:{vy}:shortest=1[ex_framed]")
            curr_label = "ex_framed"
            _log(
                f"🎞 Khung 'Đẩy ra ngoài': video {vw}x{vh} @({vx},{vy}), "
                f"canvas {ow}x{oh}, blur cạnh {sw}px"
            )

        # Apply ASS before overlays so custom shapes/text overlays float on top of subtitles
        filter_complex_parts.append(f"[{curr_label}]ass='{ass_esc}'[subbed]")
        curr_label = "subbed"

        _video_overlays = _normalize_video_overlays(video_overlays)
        if _video_overlays:
            _frame_geom = (
                (_frame_vid_x, _frame_vid_y, _frame_vid_w, _frame_vid_h)
                if _is_expand else None
            )
            curr_label = _append_video_overlay_filters(
                filter_complex_parts,
                curr_label,
                _video_overlays,
                _src_w,
                _src_h,
                frame_geom=_frame_geom,
                prefix="vo",
            )
            _log(f"▣ Overlay video: {len(_video_overlays)} lớp chữ/khối")

        filter_complex = ";".join(filter_complex_parts)

        # Add logo overlay if available
        if _logo_file and _logo_file.exists() and _logo_size_pct > 0:
            extra_inputs = ["-i", str(_logo_file)]

            # Get video dimensions to calculate logo size and position in pixels
            try:
                _vr = subprocess.run([ffmpeg, "-i", str(tmp_video)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
                _vm = re.search(r"(\d{2,5})x(\d{2,5})", _vr.stderr or "")
                _vid_w, _vid_h = (int(_vm.group(1)), int(_vm.group(2))) if _vm else (1280, 720)
            except Exception:
                _vid_w, _vid_h = 1280, 720

            # Logo height in pixels = video_height * size_pct / 100
            logo_h_px = max(20, int(_vid_h * _logo_size_pct / 100))
            # Position in pixels from percentage
            # logo_top_pct is relative to video content area (below title bar)
            # So we need to add title bar height offset
            # Read title bar height from ASS comments
            _title_bar_h_from_ass = 0
            try:
                _title_bar_h_from_ass = _ass_comment_int("Title bar h px", 0)
                _tbh_match = re.search(r"^; Title bar height:\s*([\d.]+)%", _ass_content, re.MULTILINE)
                if _title_bar_h_from_ass <= 0 and _tbh_match:
                    _title_bar_h_from_ass = int(_vid_h * float(_tbh_match.group(1)) / 100)
            except Exception:
                pass
            logo_x_px = max(0, int(_vid_w * _logo_left_pct / 100))
            logo_y_px = max(0, int(_vid_h * _logo_top_pct / 100) + _title_bar_h_from_ass)

            # Expand: logo tính theo vùng video đã thu nhỏ + offset vào canvas
            if _is_expand:
                logo_h_px = max(20, int(_frame_vid_h * _logo_size_pct / 100))
                logo_x_px = _frame_vid_x + max(0, int(_frame_vid_w * _logo_left_pct / 100))
                logo_y_px = _frame_vid_y + max(0, int(_frame_vid_h * _logo_top_pct / 100))

            # Border radius: 0% = square, 50% = circle
            # radius in pixels = min(w,h)/2 * radius_pct/50
            r_pct = max(0.0, min(50.0, _logo_radius_pct))

            if r_pct >= 49.0:
                # Full circle mask: alpha = 255 if inside circle, 0 outside
                cx = f"(W/2)"
                cy = f"(H/2)"
                radius = f"(min(W,H)/2)"
                mask_expr = f"if(lte(hypot(X-{cx},Y-{cy}),{radius}),255,0)"
                logo_filter = (
                    f"[1:v]scale=-1:{logo_h_px},format=rgba,"
                    f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask_expr}'[logo]"
                )
            elif r_pct > 0.5:
                # Rounded rectangle mask
                # r = min(w,h) * radius_pct / 100
                logo_filter = (
                    f"[1:v]scale=-1:{logo_h_px},format=rgba,"
                    f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='if(between(X,W*{r_pct/100:.3f},W*(1-{r_pct/100:.3f})),255,"
                    f"if(between(Y,H*{r_pct/100:.3f},H*(1-{r_pct/100:.3f})),255,"
                    f"if(lte(hypot(X-W*{r_pct/100:.3f},Y-H*{r_pct/100:.3f}),min(W,H)*{r_pct/100:.3f}),255,"
                    f"if(lte(hypot(X-W*(1-{r_pct/100:.3f}),Y-H*{r_pct/100:.3f}),min(W,H)*{r_pct/100:.3f}),255,"
                    f"if(lte(hypot(X-W*{r_pct/100:.3f},Y-H*(1-{r_pct/100:.3f})),min(W,H)*{r_pct/100:.3f}),255,"
                    f"if(lte(hypot(X-W*(1-{r_pct/100:.3f}),Y-H*(1-{r_pct/100:.3f})),min(W,H)*{r_pct/100:.3f}),255,0))))))'[logo]"
                )
            else:
                # No radius — square logo
                logo_filter = f"[1:v]scale=-1:{logo_h_px}[logo]"

            filter_complex += (
                f";{logo_filter};"
                f"[{curr_label}][logo]overlay={logo_x_px}:{logo_y_px}[composited]"
            )
            _log(f"🏷 Logo: {_logo_file.name} (h={logo_h_px}px, x={logo_x_px}, y={logo_y_px}, radius={r_pct}%)")
        else:
            filter_complex += f";[{curr_label}]null[composited]"

        if _aspect_convert:
            _inner_w, _inner_h = _target_w, _target_h
            if _content_ratio:
                _inner_w = max(2, int(min(_target_w, _target_h * _content_ratio) // 2 * 2))
                _inner_h = max(2, int(min(_target_h, _target_w / _content_ratio) // 2 * 2))
            if content_aspect_mode == "pad":
                _fg_filter = (f"scale={_inner_w}:{_inner_h}:force_original_aspect_ratio=decrease" if _content_ratio else f"scale={_target_w}:{_target_h}:force_original_aspect_ratio=decrease")
            else:
                _fg_filter = (f"scale={_inner_w}:{_inner_h}:force_original_aspect_ratio=increase,crop={_inner_w}:{_inner_h}" if _content_ratio else f"scale={_target_w}:{_target_h}:force_original_aspect_ratio=decrease")
            if aspect_pad_blur:
                # Blur at preview resolution, then upscale. The background is
                # already intentionally soft, so processing it at full 1080p
                # wastes substantial CPU without a visible quality benefit.
                if _target_h > _target_w:
                    blur_w, blur_h = 360, 640
                else:
                    blur_w, blur_h = 640, 360
                blur_zoom_w = int(round(blur_w * 1.12 / 2) * 2)
                blur_zoom_h = int(round(blur_h * 1.12 / 2) * 2)
                filter_complex += (
                    f";[aspect_bg_src]scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,"
                    f"crop={blur_w}:{blur_h},scale={blur_zoom_w}:{blur_zoom_h},"
                    f"crop={blur_w}:{blur_h},gblur=sigma=23,"
                    f"colorchannelmixer=rr=0.7:gg=0.7:bb=0.7,"
                    f"scale={_target_w}:{_target_h}:flags=bicubic[aspect_bg]"
                    f";[composited]{_fg_filter}[aspect_fg]"
                    f";[aspect_bg][aspect_fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]"
                )
                _log("Aspect: nen mo preview 112%, sigma=23, brightness=70%")
            else:
                filter_complex += (
                    f";[composited]{_fg_filter},"
                    f"pad={_target_w}:{_target_h}:(ow-iw)/2:(oh-ih)/2:black,"
                    f"setsar=1[vout]"
                )
                _log("Aspect: vien den")
        else:
            filter_complex += ";[composited]null[vout]"

        map_label = "[vout]"
        _log(f"🎬 Pipeline: {'blur + ' if blur_original else ''}burn ASS{' + logo' if _logo_file else ''}")

        # ── Encode ────────────────────────────────────────────────────────────
        from core.processor.ffmpeg_base import get_burn_encoder
        try:
            ffmpeg, _enc_args = get_burn_encoder(ffmpeg, encode_device)
        except RuntimeError as exc:
            return False, str(exc)
        _log(f"⚡ Encoder: {Path(ffmpeg).name} ({_enc_args[1]})")
        _log(f"🎬 Bắt đầu encode ({' '.join(_enc_args[:4])})...")
        t_encode = _time.time()

        video_duration = get_media_duration_seconds(ffmpeg, tmp_video)
        encode_timeout = max(600, int(video_duration * 6 + 300))
        filter_threads = min(2, max(1, os.cpu_count() or 1))
        _log(f"⚡ Xử lý bộ lọc: {filter_threads} luồng; giữ nguyên cấu hình hình ảnh")
        ok, err = run_ffmpeg([
            ffmpeg, "-filter_complex_threads", str(filter_threads), "-i", str(tmp_video),
        ] + extra_inputs + [
            "-filter_complex", filter_complex,
            "-map", map_label, "-map", "0:a?",
        ] + _enc_args + [
            # x264 otherwise creates many frame threads for 1080x1920 output;
            # on modest Windows machines that can exhaust RAM during the
            # concurrent TTS stage. Two threads keeps memory bounded.
            "-threads", "2",
            str(tmp_out), "-y", "-loglevel", "error"
        ], timeout=encode_timeout)

        encode_time = _time.time() - t_encode
        if ok and tmp_out.exists():
            out_size = tmp_out.stat().st_size / 1024 / 1024
            _log(f"✓ Encode xong: {encode_time:.1f}s ({out_size:.1f} MB)", "success")
            _log("📋 Đang copy file output...")
            t_copy = _time.time()
            shutil.copy2(str(tmp_out), str(output_path))
            _log(f"✓ Copy xong ({_time.time()-t_copy:.1f}s) → {output_path.name}", "success")
            total_time = _time.time() - t0
            _log(f"🏁 Tổng thời gian: {total_time:.1f}s", "success")
            return True, ""

        _log(f"❌ FFmpeg thất bại sau {encode_time:.1f}s: {err[:200]}", "error")
        return False, err


def _burn_srt(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    ffmpeg: str,
    blur_original: bool = True,
    blur_zone: str = "bottom",
    blur_height_pct: float = 0.15,
    blur_width_pct: float = 0.80,
    blur_lift_pct: float = 0.06,
    font_size: int = 18,
    font_color: str = "white",
    outline_color: str = "black",
    outline_width: int = 2,
    margin_v: int = 30,
    subtitle_position: str = "bottom",
    blur_y_pct: Optional[float] = None,
    blur_x_pct: Optional[float] = None,
    blur_extra_zones: Optional[list] = None,
    video_overlays: Optional[list] = None,
    blur_subtitle_segments: Optional[list] = None,
) -> tuple[bool, str]:
    """
    Burn SRT subtitles into video.
    Optionally blur the bottom/top region to hide original burned-in text.
    Uses -filter_complex for blur+overlay, then subtitles on top.
    """
    video_path = Path(video_path)
    srt_path = Path(srt_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy both video and SRT to temp dir to avoid special chars in paths
    with tempfile.TemporaryDirectory(prefix="burn_") as tmpdir:
        tmp_video = Path(tmpdir) / "input.mp4"
        tmp_srt   = Path(tmpdir) / "subs.srt"
        tmp_out   = Path(tmpdir) / "output.mp4"

        shutil.copy2(str(video_path), str(tmp_video))
        shutil.copy2(str(srt_path),   str(tmp_srt))

        # SRT path for subtitles filter
        # On Windows: use forward slashes, escape colon in drive letter (C: → C\:)
        srt_esc = str(tmp_srt).replace("\\", "/")
        # Escape colon in drive letter for ffmpeg subtitles filter
        if len(srt_esc) >= 2 and srt_esc[1] == ':':
            srt_esc = srt_esc[0] + "\\:" + srt_esc[2:]

        # subtitle ASS style
        alignment = "8" if str(subtitle_position).lower() == "top" else "2"
        sub_style = (
            f"FontName=Arial,"
            f"FontSize={font_size},"
            f"Bold=1,"
            f"PrimaryColour=&H00{_hex_color(font_color)},"
            f"OutlineColour=&H00{_hex_color(outline_color)},"
            f"Outline={outline_width},"
            f"MarginV={margin_v},"
            f"Alignment={alignment}"
        )

        try:
            _vr = subprocess.run(
                [ffmpeg, "-i", str(tmp_video)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            _vm = re.search(r"(\d{2,5})x(\d{2,5})", _vr.stderr or "")
            _src_w, _src_h = (int(_vm.group(1)), int(_vm.group(2))) if _vm else (1280, 720)
        except Exception:
            _src_w, _src_h = 1280, 720

        _video_overlays = _normalize_video_overlays(video_overlays)

        def _encode_srt_with_optional_overlays(input_video: Path, out_video: Path, crf: str) -> tuple[bool, str]:
            if _video_overlays:
                filter_parts: list[str] = []
                curr = _append_video_overlay_filters(
                    filter_parts,
                    "0:v",
                    _video_overlays,
                    _src_w,
                    _src_h,
                    prefix="svo",
                )
                filter_parts.append(f"[{curr}]subtitles='{srt_esc}':force_style='{sub_style}'[vout]")
                return run_ffmpeg([
                    ffmpeg, "-i", str(input_video),
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "[vout]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
                    "-c:a", "copy",
                    str(out_video), "-y", "-loglevel", "error"
                ])
            return run_ffmpeg([
                ffmpeg, "-i", str(input_video),
                "-vf", f"subtitles='{srt_esc}':force_style='{sub_style}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
                "-c:a", "copy",
                str(out_video), "-y", "-loglevel", "error"
            ])

        if (blur_original and blur_zone != "none") or blur_extra_zones:
            # Two-pass approach: first blur the zone, then burn subtitles
            # Step A: blur zone → intermediate file
            tmp_blurred = Path(tmpdir) / "blurred.mp4"

            # Gather all active blur zones
            active_zones = []
            if blur_original and blur_zone != "none":
                h_pct = _clamp_float(blur_height_pct, 0.08, 0.45)
                w_pct = max(0.35, min(1.0, float(blur_width_pct)))
                
                y_center = 0.5
                if blur_y_pct is not None:
                    y_center = _clamp_float(blur_y_pct, 0.0, 1.0)
                else:
                    lift_pct = _clamp_float(blur_lift_pct, 0.0, 0.20)
                    if blur_zone == "bottom":
                        y_center = 1.0 - h_pct / 2 - lift_pct
                    else:
                        y_center = h_pct / 2
                
                x_center = 0.5 if blur_x_pct is None else _clamp_float(blur_x_pct, 0.0, 1.0)
                
                # Tính toán giới hạn tự co dãn khi vượt biên để khớp với giao diện kéo thả
                left_pct = max(0.0, x_center - w_pct / 2)
                right_pct = min(1.0, x_center + w_pct / 2)
                w_clamped = max(0.01, right_pct - left_pct)
                
                top_pct = max(0.0, y_center - h_pct / 2)
                bottom_pct = min(1.0, y_center + h_pct / 2)
                h_clamped = max(0.01, bottom_pct - top_pct)
                
                active_zones.append((h_clamped, w_clamped, top_pct, left_pct + w_clamped / 2, None, None))
                
            if blur_extra_zones:
                for ez in blur_extra_zones:
                    try:
                        ez_h = float(ez.get("height_pct", 0.12))
                        ez_pos = float(ez.get("position_pct", 0.50))
                        ez_w = float(ez.get("width_pct", 0.80))
                        ez_x = float(ez.get("x_pct", 0.50))
                        ez_st = ez.get("start_sec", None)
                        ez_en = ez.get("end_sec", None)
                        ez_y = _clamp_float(ez_pos - ez_h / 2, 0.0, 1.0 - ez_h)
                        active_zones.append((ez_h, ez_w, ez_y, ez_x, ez_st, ez_en))
                    except Exception:
                        pass

            # Apply each blur zone in a chain
            curr_label = "0:v"
            filter_complex_parts = []
            for idx, (h, w, y, x, _st, _en) in enumerate(active_zones):
                next_label = f"b{idx}"
                _left = max(0.0, min(1.0 - w, x - w / 2))
                _en_expr = ""
                if idx == 0 and blur_original and blur_zone != "none":
                    _en_expr = _subtitle_blur_enable(blur_subtitle_segments)
                if _st is not None or _en is not None:
                    _s0 = float(_st) if _st is not None else 0.0
                    _e0 = float(_en) if _en is not None else 1e9
                    _en_expr = f":enable='between(t,{_s0:.3f},{_e0:.3f})'"
                filter_complex_parts.append(f"[{curr_label}]split[orig_{idx}][copy_{idx}]")
                filter_complex_parts.append(
                    f"[copy_{idx}]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{_left:.4f}:ih*{y:.4f},"
                    f"boxblur=luma_radius='min(20,min(w,h)/2)':luma_power=3:chroma_radius='min(15,min(cw,ch)/2)':chroma_power=2[blurred_{idx}]"
                )
                filter_complex_parts.append(
                    f"[orig_{idx}][blurred_{idx}]overlay=W*{_left:.4f}:H*{y:.4f}{_en_expr}[{next_label}]"
                )
                curr_label = next_label

            filter_complex_parts.append(f"[{curr_label}]null[blended]")
            crop_filter = ";".join(filter_complex_parts)

            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(tmp_video),
                "-filter_complex", crop_filter,
                "-map", "[blended]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy",
                str(tmp_blurred), "-y", "-loglevel", "error"
            ])
            if not ok:
                # fallback: skip blur, just burn subs
                tmp_blurred = tmp_video

            # Step B: burn subtitles on top of blurred video
            ok, err = _encode_srt_with_optional_overlays(tmp_blurred, tmp_out, "23")
        else:
            # No blur - just burn subtitles directly
            ok, err = _encode_srt_with_optional_overlays(tmp_video, tmp_out, "23")

        if ok and tmp_out.exists():
            shutil.copy2(str(tmp_out), str(output_path))
            return True, ""
        return False, err


def _hex_color(name: str) -> str:
    """Convert color name or #RRGGBB hex to BGR hex for ASS style."""
    colors = {
        "white":   "FFFFFF",
        "black":   "000000",
        "yellow":  "00FFFF",   # BGR: B=00 G=FF R=FF → RGB yellow
        "red":     "0000FF",   # BGR: B=00 G=00 R=FF
        "blue":    "FF0000",   # BGR: B=FF G=00 R=00
        "green":   "00FF00",   # BGR: B=00 G=FF R=00
        "cyan":    "FFFF00",   # BGR: B=FF G=FF R=00 → RGB cyan
        "magenta": "FF00FF",
    }
    name = (name or "").strip()
    # Handle #RRGGBB hex input — convert RGB → BGR for ASS
    if name.startswith("#") and len(name) == 7:
        try:
            r = name[1:3]; g = name[3:5]; b = name[5:7]
            return (b + g + r).upper()  # ASS uses BGR order
        except Exception:
            pass
    return colors.get(name.lower(), "FFFFFF")


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB or color name → ASS &H00BBGGRR format."""
    bgr = _hex_color(hex_color)
    return f"&H00{bgr}"


def _hex_to_ass_color_alpha(hex_color: str, alpha: int = 0) -> str:
    """Convert #RRGGBB + alpha (0=opaque, 255=transparent) → ASS &HAABBGGRR."""
    bgr = _hex_color(hex_color)
    return f"&H{alpha:02X}{bgr}"


# ══════════════════════════════════════════════════════════════════════════════
# Generate short frame title from video content using AI
# ══════════════════════════════════════════════════════════════════════════════

def generate_frame_title(
    translated_texts: list[str],
    original_texts: list[str] = None,
    trans_cfg: dict = None,
    preferred_provider: str = "deepseek",
    video_title: str = "",
    target_lang: str = "vi",
) -> str:
    """
    Use AI to generate a short, catchy title for the frame bar in the target language.
    Based on the translated subtitle content.
    """
    import json
    import urllib.request

    _LANG_FULL = {
        "vi": "Vietnamese", "en": "English", "ja": "Japanese", "ko": "Korean",
        "th": "Thai", "id": "Indonesian", "es": "Spanish", "pt": "Portuguese",
        "fr": "French", "de": "German", "ru": "Russian", "ar": "Arabic",
        "hi": "Hindi", "zh": "Chinese",
    }
    target_lang_name = _LANG_FULL.get(target_lang, target_lang)

    if not translated_texts:
        # Return empty so Step 3 can generate it properly with translated Vietnamese text, instead of raw filename
        return ""

    cfg = trans_cfg or {}
    # Pick the best available API key
    api_key = ""
    api_url = ""
    model = ""

    deepseek_key = cfg.get("deepseek_key", "")
    groq_key = cfg.get("groq_key", "")
    openai_key = cfg.get("openai_key", "")

    if preferred_provider == "deepseek" and deepseek_key:
        api_key = deepseek_key
        api_url = "https://api.deepseek.com/v1/chat/completions"
        model = "deepseek-chat"
    elif preferred_provider == "groq" and groq_key:
        api_key = groq_key
        api_url = "https://api.groq.com/openai/v1/chat/completions"
        model = cfg.get("groq_model", "llama-3.1-8b-instant")
    elif deepseek_key:
        api_key = deepseek_key
        api_url = "https://api.deepseek.com/v1/chat/completions"
        model = "deepseek-chat"
    elif groq_key:
        api_key = groq_key
        api_url = "https://api.groq.com/openai/v1/chat/completions"
        model = cfg.get("groq_model", "llama-3.1-8b-instant")
    elif openai_key:
        api_key = openai_key
        api_url = "https://api.openai.com/v1/chat/completions"
        model = "gpt-4o-mini"

    if not api_key:
        # Fallback: use first 30 chars of first translated text
        for t in translated_texts:
            if t and t.strip():
                return t.strip()[:35]
        return video_title.replace("_", " ")[:35] if video_title else ""

    # Build content summary from translated texts
    content_sample = " ".join(t for t in translated_texts[:10] if t).strip()
    if len(content_sample) > 500:
        content_sample = content_sample[:500]

    # Clean raw stem: remove numeric suffixes, replace underscores with spaces
    import re as _re
    raw_stem = video_title or ""
    raw_stem = _re.sub(r'_?\d{10,}$', '', raw_stem)   # strip trailing numeric IDs
    raw_stem = raw_stem.replace("_", " ").strip()

    prompt = (
        f"Tên file video (không dấu): {raw_stem}\n"
        f"Nội dung phụ đề ({target_lang_name}): {content_sample[:300]}\n\n"
        f"Từ tên file và nội dung trên, tạo 1 tiêu đề ngắn gọn (20-35 ký tự) có ý nghĩa với video.\n"
        f"- Thêm dấu tiếng Việt đúng vào các từ lấy từ tên file\n"
        f"- Kết hợp ý chính từ tên file + nội dung để tạo tiêu đề hấp dẫn\n"
        f"- Dùng | để chia tiêu đề thành 2 phần màu. Phần sau | là phần gây tò mò nhất\n"
        f"- Ví dụ: 'MUỖI BẮC CỰC HÚT MÁU SÓI CON|ĐÀN SÓI BUỘC PHẢI ĐI'\n"
        f"- Chỉ trả về tiêu đề, không giải thích.\n\n"
        f"Tiêu đề:"
    )

    try:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": f"You create short, catchy video titles in {target_lang_name}. Use | to mark the emphasis part."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 80,
        }).encode()
        req = urllib.request.Request(
            api_url, data=payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
        # Some upstreams (incl. DTRouter Codex combos) ship SSE even when
        # stream is unset — parse both JSON and SSE bodies robustly.
        from utils.translation import _parse_chat_response_body
        title = _parse_chat_response_body(raw)
        # Clean up: remove quotes, newlines
        title = title.strip('"\'').split("\n")[0].strip()
        # Limit length
        if len(title) > 50:
            title = title[:47] + "..."
        return title
    except Exception as e:
        logging.getLogger(__name__).warning("generate_frame_title failed: %s", e)
        # Fallback
        for t in translated_texts:
            if t and t.strip():
                return t.strip()[:35]
        return video_title.replace("_", " ")[:35] if video_title else ""


# ══════════════════════════════════════════════════════════════════════════════
# ASS with Frame Elements — Embed blur panels + title bar into ASS file
# ══════════════════════════════════════════════════════════════════════════════

def write_ass_with_frame(
    segments: list[dict],
    out_path: Path,
    video_duration: float,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    # Subtitle params
    font_size: int = 32,
    font_color: str = "white",
    outline_color: str = "black",
    outline_width: int = 2,
    shadow: int = 1,
    margin_v: int = 20,
    alignment: int = 2,
    font_name: str = "Arial",
    max_words_per_line: int = 9,
    # Frame: Title bar (overlay on top of video)
    title_text: str = "",
    title_size_pct: float = 7.0,
    title_weight: int = 400,
    title_x_pct: float = 50.0,
    title_y_pct: float = 50.0,
    title_color: str = "#000000",
    title_color_2: str = "#ff0000",  # Second color for emphasis part of title
    title_split_color: bool = True,  # Enable split-color (half/half)
    title_bar_color: str = "#ffffff",
    title_bar_h_pct: float = 6.0,  # height of title bar as % of PlayResY
    title_margin_x_pct: float = 5.0,
    # Frame: Side blur panels (overlay on sides of video)
    blur_w_pct: float = 15.0,
    blur_top_pct: float = 0.0,  # Top blur strip height as % of PlayResY
    blur_bottom_pct: float = 0.0,  # Bottom blur strip height as % of PlayResY
    blur_opacity: float = 0.6,
    blur_color: str = "#000000",
    # Logo
    logo_path: str = "",  # Path to logo image (will be noted in ASS comments for ffmpeg)
    logo_size_pct: float = 6.0,  # Logo height as % of video height (smaller = better)
    logo_top_pct: float = 3.0,  # Logo Y position as % from top
    logo_left_pct: float = 3.0,  # Logo X position as % from left
    logo_radius_pct: float = 50.0,  # Border radius: 0=square, 50=circle
    logo_position: str = "top-left",  # top-left, top-right
    # Frame layout mode:
    #   "overlay" → khung vẽ đè lên video (không đổi kích thước) — hành vi cũ
    #   "expand"  → thu nhỏ video + chừa dải tiêu đề phía trên + blur 2 bên ngoài
    #               (khớp với preview "Đẩy ra ngoài")
    frame_mode: str = "overlay",
    target_aspect: str = "auto",
    font_bold: bool = True,
) -> Path:
    """
    Write ASS subtitle file with frame elements (title bar + side blur panels)
    embedded as ASS drawing commands.

    All frame elements are OVERLAY on the original video (no size change):
    - Title bar: white rectangle at top covering title_bar_h_pct% of video height
    - Side blur panels: real FFmpeg blur plus semi-transparent dark overlays

    PlayRes should match the video's actual dimensions.

    Parameters:
        segments: list of {start, end, text} dicts (optional, can be empty)
        video_duration: total video duration in seconds
        play_res_x/y: must match video dimensions (width × height)
        title_text: text to show in title bar (overlay on top of video)
        title_size_pct: title font size as % of width
        title_weight: title font weight; >=600 renders bold in ASS
        title_margin_x_pct: horizontal title margin as % of width
        title_color: title text color (#RRGGBB)
        title_bar_color: title bar background color
        title_bar_h_pct: title bar height as % of video height
        blur_w_pct: side blur panel width as % of video width
        blur_opacity: opacity of blur panels (0.0-1.0)
        blur_color: color of blur panels
    """
    out_path = Path(out_path)

    # Calculate dimensions (all overlays on the video area)
    # Khi title_bar_h_pct=0 (user tắt tiêu đề) → không có title bar (h=0)
    title_bar_h = 0 if title_bar_h_pct <= 0 else max(40, int(play_res_y * title_bar_h_pct / 100))
    title_bar_h = title_bar_h + (title_bar_h % 2)
    title_font_px = max(14, int(play_res_x * title_size_pct / 100))
    # Auto-clamp: font must not exceed ~40% of title bar height (keep text inside bar)
    if title_bar_h > 0:
        title_font_px = min(title_font_px, max(14, int(title_bar_h * 0.42)))
    title_bold = -1 if int(_clamp_float(title_weight, 300, 900)) >= 600 else 0

    side_w = max(0, int(play_res_x * blur_w_pct / 100))

    # ── Geometry theo chế độ khung ────────────────────────────────────────────
    # overlay: khung đè lên video, output = play_res_x × play_res_y (không đổi)
    # expand : thu nhỏ video, chừa dải tiêu đề trên + blur 2 bên ngoài
    #          → output cao/khác đi, khớp với preview "Đẩy ra ngoài"
    frame_mode = (frame_mode or "overlay").strip().lower()
    out_w = play_res_x
    if frame_mode == "expand":
        # Khớp với preview: chiều cao dải tiêu đề tính theo cỡ chữ (font × 2.4),
        # không dùng title_bar_h_pct cố định.
        vid_w = max(2, play_res_x - 2 * side_w)
        vid_w -= vid_w % 2
        vid_h = max(2, int(round(vid_w * play_res_y / max(1, play_res_x))))
        vid_h -= vid_h % 2
        vid_x = side_w
        vid_y = title_bar_h
        out_h = title_bar_h + vid_h
    else:
        vid_w = play_res_x
        vid_h = play_res_y
        vid_x = 0
        vid_y = 0
        out_h = play_res_y
    # Vùng video theo trục dọc (panel blur 2 bên chỉ phủ phần video, không phủ dải tiêu đề)
    vid_bottom = vid_y + vid_h

    # ASS alpha: 0=opaque, FF=transparent (opposite of normal)
    blur_alpha = max(0, min(255, int((1.0 - blur_opacity) * 255)))
    title_bar_bgr = _hex_color(title_bar_color)
    title_text_bgr = _hex_color(title_color)
    blur_bgr = _hex_color(blur_color)

    # ── Build styles ──────────────────────────────────────────────────────────
    sub_primary = f"&H00{_hex_color(font_color)}"
    sub_outline = f"&H00{_hex_color(outline_color)}"
    sub_shadow_c = "&H80000000"

    styles = []
    # Default subtitle style
    styles.append(
        f"Style: Default,{font_name},{font_size},{sub_primary},&H000000FF,{sub_outline},{sub_shadow_c},"
        f"{-1 if font_bold else 0},0,0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},10,10,{margin_v},1"
    )
    # Title bar background style (drawing)
    styles.append(
        f"Style: TitleBar,Arial,1,&H00{title_bar_bgr},&H00{title_bar_bgr},&H00{title_bar_bgr},&H00{title_bar_bgr},"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )
    # Title text style — configurable bold, no outline (title bar has white background)
    styles.append(
        f"Style: TitleText,{font_name},{title_font_px},&H00{title_text_bgr},&H000000FF,&H00000000,&H00000000,"
        f"{title_bold},0,0,0,100,100,0,0,1,0,0,8,10,10,{title_bar_h // 4},1"
    )
    # Side blur panel style (semi-transparent)
    styles.append(
        f"Style: BlurLeft,Arial,1,&H{blur_alpha:02X}{blur_bgr},&H{blur_alpha:02X}{blur_bgr},"
        f"&H{blur_alpha:02X}{blur_bgr},&H{blur_alpha:02X}{blur_bgr},"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )
    styles.append(
        f"Style: BlurRight,Arial,1,&H{blur_alpha:02X}{blur_bgr},&H{blur_alpha:02X}{blur_bgr},"
        f"&H{blur_alpha:02X}{blur_bgr},&H{blur_alpha:02X}{blur_bgr},"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )

    target_aspect = str(target_aspect or "auto").strip().lower()
    source_is_vertical = play_res_y > play_res_x
    aspect_will_convert = target_aspect in ("9x16", "16x9") and (
        (target_aspect == "9x16" and not source_is_vertical)
        or (target_aspect == "16x9" and source_is_vertical)
    )
    final_w, final_h = (
        ((1080, 1920) if target_aspect == "9x16" else (1920, 1080))
        if aspect_will_convert else (out_w, out_h)
    )

    # ── Build header ──────────────────────────────────────────────────────────
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {out_w}
PlayResY: {out_h}
WrapStyle: 0
; Frame elements embedded: title bar + side blur panels (source-space composition)
; Frame mode: {frame_mode}
; Out width px: {out_w}
; Out height px: {out_h}
; Final target aspect: {target_aspect}
; Final output width px: {final_w}
; Final output height px: {final_h}
; Vid x px: {vid_x}
; Vid y px: {vid_y}
; Vid w px: {vid_w}
; Vid h px: {vid_h}
; Side width px: {side_w}
; Title bar h px: {title_bar_h}
; Title: {title_text}
; Title weight: {title_weight}
; Title x: {title_x_pct}%
; Title y: {title_y_pct}%
; Title margin x: {title_margin_x_pct}%
; Title color: {title_color} / {title_color_2} (split)
; Title bar height: {title_bar_h_pct}%
; Blur width: {blur_w_pct}%
; Blur top: {blur_top_pct}%
; Blur bottom: {blur_bottom_pct}%
; Blur opacity: {blur_opacity}
; Blur color: {blur_color}
; Logo: {logo_path}
; Logo size: {logo_size_pct}%
; Logo top: {logo_top_pct}%
; Logo left: {logo_left_pct}%
; Logo radius: {logo_radius_pct}%
; Logo position: {logo_position}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{chr(10).join(styles)}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # ── Frame elements as Dialogue lines with drawing commands ────────────────
    # Title bar has the highest layer so it's drawn on top
    end_time = _fmt_ass_time(video_duration + 1.0)
    start_time = "0:00:00.00"

    # 1. Title bar background (white rectangle at top, overlay on video)
    # Chỉ vẽ khi thực sự có title — nếu user tắt "Hiện tiêu đề" thì không vẽ dải trắng
    has_title = bool(title_text and title_text.strip())
    if has_title:
        title_draw = f"m 0 0 l {out_w} 0 {out_w} {title_bar_h} 0 {title_bar_h}"
        lines.append(
            f"Dialogue: 3,{start_time},{end_time},TitleBar,,0,0,0,,{{\\pos(0,0)\\p1}}{title_draw}{{\\p0}}"
        )

    # 2. Title text (centered in title bar) — UPPERCASE, split color, no outline
    if has_title:
        title_margin_x = int(out_w * _clamp_float(title_margin_x_pct, 0.0, 40.0) / 100.0)
        title_x = int(out_w * _clamp_float(title_x_pct, 0.0, 100.0) / 100.0)
        title_x = max(title_margin_x, min(max(title_margin_x, out_w - title_margin_x), title_x))
        # Always anchor title Y to center of title bar
        title_y = title_bar_h // 2
        # Uppercase the title for impact
        safe_title = title_text.replace("{", "").replace("}", "").replace("\\", "").upper()
        # Auto-wrap long titles: estimate chars per line based on font size vs bar width
        # ~0.6 = approximate char width ratio (uppercase Latin/Viet wide chars)
        _chars_per_line = max(10, int(out_w * 0.9 / max(1, title_font_px * 0.6)))
        if len(safe_title) > _chars_per_line and " " in safe_title:
            # Find word boundary closest to middle
            words = safe_title.split()
            mid = max(1, len(words) // 2)
            safe_title = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])

        if title_split_color and len(safe_title) > 1:
            color1_bgr = _hex_color(title_color)
            color2_bgr = _hex_color(title_color_2)

            # Check if AI provided a | separator for emphasis split
            if "|" in safe_title:
                parts = safe_title.split("|", 1)
                part1 = parts[0].strip()
                part2 = parts[1].strip()
            else:
                # Fallback: split at word boundary near middle
                words = safe_title.split()
                if len(words) >= 2:
                    mid_word = len(words) // 2
                    part1 = " ".join(words[:mid_word])
                    part2 = " ".join(words[mid_word:])
                else:
                    part1 = safe_title
                    part2 = ""

            # No outline (\bord0) — clean look matching the title bar background
            if part2:
                colored_title = (
                    f"{{\\an5\\pos({title_x},{title_y})\\bord0}}"
                    f"{{\\c&H00{color1_bgr}&}}{part1} "
                    f"{{\\c&H00{color2_bgr}&}}{part2}"
                )
            else:
                colored_title = (
                    f"{{\\an5\\pos({title_x},{title_y})\\bord0}}"
                    f"{{\\c&H00{color1_bgr}&}}{part1}"
                )
            lines.append(
                f"Dialogue: 4,{start_time},{end_time},TitleText,,0,0,0,,{colored_title}"
            )
        else:
            lines.append(
                f"Dialogue: 4,{start_time},{end_time},TitleText,,0,0,0,,"
                f"{{\\an5\\pos({title_x},{title_y})\\bord0}}{safe_title}"
            )

    # 3. Left blur panel (semi-transparent) — phủ phần video (từ vid_y, cao vid_h)
    if side_w > 0:
        left_draw = f"m 0 0 l {side_w} 0 {side_w} {vid_h} 0 {vid_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos(0,{vid_y})\\p1}}{left_draw}{{\\p0}}"
        )

        # 4. Right blur panel
        right_x = out_w - side_w
        right_draw = f"m 0 0 l {side_w} 0 {side_w} {vid_h} 0 {vid_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurRight,,0,0,0,,"
            f"{{\\pos({right_x},{vid_y})\\p1}}{right_draw}{{\\p0}}"
        )

    # 5. Top blur strip (full video width, trong vùng video)
    top_h = max(0, int(vid_h * blur_top_pct / 100))
    if top_h > 0:
        top_draw = f"m 0 0 l {vid_w} 0 {vid_w} {top_h} 0 {top_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos({vid_x},{vid_y})\\p1}}{top_draw}{{\\p0}}"
        )

    # 6. Bottom blur strip (full video width, trong vùng video)
    bottom_h = max(0, int(vid_h * blur_bottom_pct / 100))
    if bottom_h > 0:
        bottom_y = vid_bottom - bottom_h
        bottom_draw = f"m 0 0 l {vid_w} 0 {vid_w} {bottom_h} 0 {bottom_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos({vid_x},{bottom_y})\\p1}}{bottom_draw}{{\\p0}}"
        )

    # ── Subtitle dialogue lines (layer 2 — below title bar, above blur) ──────
    for seg in segments:
        text = seg.get("text", "").replace("\n", " ").strip()
        # Clean any remaining timestamp leak or brackets
        text = re.sub(
            r'\[?\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*(?:-->|->|-)\s*\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{1,3}\s*\]?',
            '',
            text
        ).strip()
        text = re.sub(r'\[\s*\]', '', text).strip()
        text = ' '.join(text.split())
        if not text:
            continue
        split_lines = ([text] if seg.get("voice_aligned") else
                       _smart_split_display_lines(text, max_words=max_words_per_line))
        total_len = sum(len(c) for c in split_lines) or 1
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_duration = max(0.2, seg_end - seg_start)
        cur_t = seg_start
        for i, line in enumerate(split_lines):
            chunk_ratio = len(line) / total_len
            chunk_dur = seg_duration * chunk_ratio
            sub_start = cur_t
            sub_end = cur_t + chunk_dur
            if i == len(split_lines) - 1:
                sub_end = seg_end
            else:
                sub_end = max(sub_start + 0.1, sub_end - 0.01)
            cur_t = sub_end + 0.01
            s = _fmt_ass_time(sub_start)
            e = _fmt_ass_time(sub_end)
            spk_name = "Nam" if seg.get("speaker") == "male" else ("Nữ" if seg.get("speaker") == "female" else "")
            lines.append(f"Dialogue: 2,{s},{e},Default,{spk_name},0,0,0,,{line}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# TTS text chunker — tách text thành đoạn nhỏ theo dấu câu, language-aware
# ══════════════════════════════════════════════════════════════════════════════

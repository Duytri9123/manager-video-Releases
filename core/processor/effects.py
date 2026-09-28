#!/usr/bin/env python3
"""
core.processor.effects
Video overlay filters, color grading, anti-fingerprint, vertical video conversion,
and thumbnail generation.
"""
import os
import math
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
    _escape_drawtext_text, _fmt_hms, has_audio_track,
    _resolve_image_path, _SUPPORTED_IMAGE_EXTS, _LOGO_POSITION_MAP
)

def concat_thumbnail_with_video(
    video_path: Path,
    thumbnail_path: Path,
    output_path: Path,
    ffmpeg: str,
    duration: float = 2.0,
) -> tuple[bool, str]:
    """
    Concat a thumbnail image as the first N seconds of a video.

    Approach: encode thumbnail as a short silent video clip with same
    resolution/fps/codec as the main video, then concat with -filter_complex.
    This avoids issues with concat demuxer requiring matching codecs.

    Args:
        video_path: source video (already burned with subs)
        thumbnail_path: thumbnail image (jpg/png)
        output_path: final output mp4
        ffmpeg: path to ffmpeg
        duration: how long to show thumbnail (default 2s)

    Returns:
        (success, error_message_or_path)
    """
    video_path = Path(video_path)
    thumbnail_path = Path(thumbnail_path)
    output_path = Path(output_path)

    if not video_path.exists():
        return False, f"Video không tồn tại: {video_path}"
    if not thumbnail_path.exists():
        return False, f"Thumbnail không tồn tại: {thumbnail_path}"

    # Get video resolution from source
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        m = re.search(r"(\d{2,5})x(\d{2,5})", r.stderr or "")
        vid_w, vid_h = (int(m.group(1)), int(m.group(2))) if m else (1280, 720)
    except Exception:
        vid_w, vid_h = 1280, 720

    enc_args = _get_encoding_args(ffmpeg)

    # Use filter_complex to: scale thumbnail to video size, generate silent audio, concat
    # [0:v] = thumbnail (image, looped), [1:v]+[1:a] = video
    cmd = [
        ffmpeg,
        "-loop", "1", "-t", str(duration), "-i", str(thumbnail_path),
        "-i", str(video_path),
        "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-filter_complex",
        (
            f"[0:v]scale={vid_w}:{vid_h}:force_original_aspect_ratio=decrease,"
            f"pad={vid_w}:{vid_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[thumb];"
            f"[1:v]scale={vid_w}:{vid_h}:force_original_aspect_ratio=decrease,"
            f"pad={vid_w}:{vid_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p[vid];"
            f"[thumb][2:a][vid][1:a?]concat=n=2:v=1:a=1[outv][outa]"
        ),
        "-map", "[outv]", "-map", "[outa]",
    ] + enc_args + [
        str(output_path), "-y", "-loglevel", "error"
    ]

    ok, err = run_ffmpeg(cmd, timeout=900)
    if ok and output_path.exists() and output_path.stat().st_size > 0:
        return True, str(output_path)
    return False, err or "Concat thumbnail thất bại"


def _gen_ai_thumbnail_for_pipeline(
    video_path: Path,
    output_path: Path,
    ffmpeg: str,
    timestamp: float = 5.0,
    title: str = "",
    subtitle_text: str = "",
) -> Optional[Path]:
    """Generate AI thumbnail using Gemini 2.5 Flash Image.

    Returns Path to saved thumbnail, or None on failure.
    Used by the parallel thumbnail task in process_video_full pipeline.
    """
    import os
    import base64
    import urllib.request
    import urllib.error
    import json as _json
    import shutil as _shutil

    # Load config once
    try:
        from core_app import load_cfg as _load_cfg
        cfg = _load_cfg()
    except Exception:
        cfg = {}

    gemini_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )

    if not gemini_key:
        return None

    # Step 1: extract frame from video (used as reference)
    try:
        with tempfile.TemporaryDirectory(prefix="ai_thumb_pipe_") as tmpdir:
            tmp_video = Path(tmpdir) / f"input{video_path.suffix}"
            _shutil.copy2(str(video_path), str(tmp_video))
            tmp_jpg = Path(tmpdir) / "frame.jpg"

            ok, _ = run_ffmpeg([
                ffmpeg, "-ss", str(timestamp),
                "-i", str(tmp_video),
                "-vframes", "1", "-q:v", "2",
                str(tmp_jpg), "-y", "-loglevel", "error"
            ], timeout=60)

            if not ok or not tmp_jpg.exists() or tmp_jpg.stat().st_size == 0:
                return None

            frame_b64 = base64.b64encode(tmp_jpg.read_bytes()).decode()

            # Step 2: ask Gemini Vision to refine prompt based on frame
            prompt_text = (
                f"You are a YouTube thumbnail designer. Analyze this video frame and write a concise "
                f"image-generation prompt (under 150 words) for a click-worthy 16:9 thumbnail. "
                f"Title/Brand: {title or 'N/A'}. Content hint: {subtitle_text or 'N/A'}. "
                f"Output ONLY the prompt text."
            )
            try:
                vision_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={gemini_key}"
                vision_payload = {
                    "contents": [{
                        "parts": [
                            {"text": prompt_text},
                            {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                        ]
                    }],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 300},
                }
                body = _json.dumps(vision_payload).encode("utf-8")
                req = urllib.request.Request(
                    vision_url, data=body,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    vdata = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
                refined = ""
                for cand in (vdata.get("candidates") or []):
                    for part in ((cand.get("content") or {}).get("parts") or []):
                        if part.get("text"):
                            refined = part["text"].strip()
                            break
                    if refined:
                        break
                if refined:
                    gen_prompt = refined
            except Exception:
                pass

            # Step 3: generate image with Gemini native image generation
            img_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash-image:generateContent?key={gemini_key}"
            img_payload = {
                "contents": [{
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                        {"text": f"Based on this video frame, generate a professional thumbnail image. {gen_prompt}"},
                    ]
                }],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            }
            try:
                body = _json.dumps(img_payload).encode("utf-8")
                req = urllib.request.Request(
                    img_url, data=body,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    idata = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
                for cand in (idata.get("candidates") or []):
                    for part in ((cand.get("content") or {}).get("parts") or []):
                        inline = part.get("inlineData") or {}
                        if inline.get("mimeType", "").startswith("image/"):
                            img_b64_data = inline.get("data", "")
                            if img_b64_data:
                                output_path.write_bytes(base64.b64decode(img_b64_data))
                                return output_path
            except Exception:
                pass
    except Exception:
        pass

    return None



def _normalize_video_overlays(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []

    overlays: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").strip().lower()
        if not _as_bool(item.get("enabled", True), True):
            continue

        def pct(name: str, default: float, low: float = 0.0, high: float = 1.0) -> float:
            return _clamp_float(_as_float(item.get(name), default), low, high)

        def opt_time(name: str):
            val = item.get(name)
            if val is None or str(val).strip() == "":
                return None
            try:
                return max(0.0, float(val))
            except Exception:
                return None

        start_sec = opt_time("start_sec")
        end_sec = opt_time("end_sec")
        if start_sec is not None and end_sec is not None and end_sec <= start_sec:
            end_sec = None

        if typ == "rect":
            overlays.append({
                "type": "rect",
                "x_pct": pct("x_pct", 0.5),
                "y_pct": pct("y_pct", 0.5),
                "width_pct": pct("width_pct", 0.8, 0.01, 1.0),
                "height_pct": pct("height_pct", 0.12, 0.01, 1.0),
                "color": _normalize_hex_rgb(item.get("color"), "#000000"),
                "opacity": pct("opacity", 0.55),
                "start_sec": start_sec,
                "end_sec": end_sec,
            })
        elif typ == "text":
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            overlays.append({
                "type": "text",
                "text": text[:500],
                "x_pct": pct("x_pct", 0.5),
                "y_pct": pct("y_pct", 0.18),
                "size_pct": pct("size_pct", 0.05, 0.01, 0.30),
                "weight": int(_clamp_float(_as_float(item.get("weight"), 700.0), 300.0, 900.0)),
                "padding_pct": pct("padding_pct", 0.55, 0.0, 1.5),
                "color": _normalize_hex_rgb(item.get("color"), "#FFFFFF"),
                "box_color": _normalize_hex_rgb(item.get("box_color"), "#000000"),
                "box_opacity": pct("box_opacity", 0.5),
                "text_opacity": pct("text_opacity", 1.0),
                "motion": str(item.get("motion") or "none") if str(item.get("motion") or "none") in ("none", "figure8", "horizontal", "vertical", "circle", "diamond") else "none",
                "motion_amp_pct": pct("motion_amp_pct", 1.0, 0.0, 1.0),
                "motion_period_sec": pct("motion_period_sec", 6.0, 1.0, 60.0),
                "start_sec": start_sec,
                "end_sec": end_sec,
            })
        elif typ == "image":
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            overlays.append({
                "type": "image",
                "path": path,
                "x_pct": pct("x_pct", 0.5),
                "y_pct": pct("y_pct", 0.5),
                "width_pct": pct("width_pct", 0.20, 0.01, 1.0),
                "height_pct": pct("height_pct", 0.20, 0.01, 1.0),
                "opacity": pct("opacity", 1.0),
                "start_sec": start_sec,
                "end_sec": end_sec,
            })
    return overlays




def _overlay_enable_expr(ov: dict) -> str:
    st = ov.get("start_sec")
    en = ov.get("end_sec")
    if st is None and en is None:
        return ""
    s0 = float(st) if st is not None else 0.0
    e0 = float(en) if en is not None else 1e9
    return f":enable='between(t,{s0:.3f},{e0:.3f})'"


def _append_video_overlay_filters(
    filter_complex_parts: list[str],
    curr_label: str,
    overlays: list[dict],
    src_w: int,
    src_h: int,
    frame_geom: Optional[tuple[int, int, int, int]] = None,
    prefix: str = "ov",
) -> str:
    if not overlays:
        return curr_label

    if frame_geom:
        base_x, base_y, base_w, base_h = frame_geom
    else:
        base_x, base_y, base_w, base_h = 0, 0, max(1, int(src_w)), max(1, int(src_h))

    for idx, ov in enumerate(overlays):
        next_label = f"{prefix}{idx}"
        enable = _overlay_enable_expr(ov)
        bx = float(base_x)
        by = float(base_y)
        bw = float(max(1, base_w))
        bh = float(max(1, base_h))

        if ov.get("type") == "rect":
            w_pct = _clamp_float(ov.get("width_pct", 0.8), 0.01, 1.0)
            h_pct = _clamp_float(ov.get("height_pct", 0.12), 0.01, 1.0)
            x_pct = _clamp_float(ov.get("x_pct", 0.5), 0.0, 1.0)
            y_pct = _clamp_float(ov.get("y_pct", 0.5), 0.0, 1.0)
            color = _ffmpeg_color(ov.get("color", "#000000"), ov.get("opacity", 0.55))
            x_expr = f"{bx:.3f}+{bw:.3f}*{x_pct:.6f}-{bw:.3f}*{w_pct:.6f}/2"
            y_expr = f"{by:.3f}+{bh:.3f}*{y_pct:.6f}-{bh:.3f}*{h_pct:.6f}/2"
            w_expr = f"{bw:.3f}*{w_pct:.6f}"
            h_expr = f"{bh:.3f}*{h_pct:.6f}"
            filter_complex_parts.append(
                f"[{curr_label}]drawbox=x='{x_expr}':y='{y_expr}':w='{w_expr}':h='{h_expr}':"
                f"color={color}:t=fill{enable}[{next_label}]"
            )
            curr_label = next_label
            continue

        if ov.get("type") == "text":
            text = _escape_drawtext_text(ov.get("text", ""))
            if not text:
                continue
            size_pct = _clamp_float(ov.get("size_pct", 0.05), 0.01, 0.30)
            font_size = max(8, int(round(bh * size_pct)))
            weight = int(_clamp_float(ov.get("weight", 700), 300, 900))
            is_bold = weight >= 600
            
            # Danh sách các font hỗ trợ tốt tiếng Việt trên nhiều HĐH
            possible_fonts = [
                "C:/Windows/Fonts/arialbd.ttf" if is_bold else "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/tahomabd.ttf" if is_bold else "C:/Windows/Fonts/tahoma.ttf",
                "C:/Windows/Fonts/segoeuib.ttf" if is_bold else "C:/Windows/Fonts/segoeui.ttf",
                "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
            ]
            
            import os
            font_opt = f"font='{'Arial Bold' if is_bold else 'Arial'}'" # fallback
            custom_font = ov.get("font_path") or ov.get("fontfile")
            font_candidates = ([custom_font] if custom_font else []) + possible_fonts
            for fpath in font_candidates:
                if fpath and os.path.exists(fpath):
                    escaped_fpath = str(fpath).replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''")
                    font_opt = f"fontfile='{escaped_fpath}'"
                    break
                
            padding_pct = _clamp_float(ov.get("padding_pct", 0.55), 0.0, 1.5)
            x_pct = _clamp_float(ov.get("x_pct", 0.5), 0.0, 1.0)
            y_pct = _clamp_float(ov.get("y_pct", 0.18), 0.0, 1.0)
            motion = ov.get("motion", "none")
            x_expr = f"{bx:.3f}+{bw:.3f}*{x_pct:.6f}-text_w/2"
            y_expr = f"{by:.3f}+{bh:.3f}*{y_pct:.6f}-text_h/2"
            if motion != "none":
                amp = _clamp_float(ov.get("motion_amp_pct", 1.0), 0.0, 1.0)
                period = _clamp_float(ov.get("motion_period_sec", 6.0), 1.0, 60.0)
                start = float(ov.get("start_sec") or 0.0)
                phase = f"(2*PI*(t-{start:.3f})/{period:.3f})"
                x_expr = f"{bx:.3f}+({bw:.3f}-text_w)/2"
                y_expr = f"{by:.3f}+({bh:.3f}-text_h)/2"
                travel_x = f"({bw:.3f}-text_w)/2*{amp:.6f}"
                travel_y = f"({bh:.3f}-text_h)/2*{amp:.6f}"
                if motion in ("figure8", "horizontal", "circle"):
                    x_expr += f"+{travel_x}*sin{phase}"
                elif motion == "diamond":
                    x_expr += f"+{travel_x}*2/PI*asin(sin{phase})"
                if motion == "figure8":
                    y_expr += f"+{travel_y}*sin(2*{phase})"
                elif motion == "circle":
                    y_expr += f"+{travel_y}*cos{phase}"
                elif motion == "vertical":
                    y_expr += f"+{travel_y}*sin{phase}"
                elif motion == "diamond":
                    y_expr += f"-{travel_y}*2/PI*asin(cos{phase})"
            font_color = _ffmpeg_color(ov.get("color", "#FFFFFF"), _clamp_float(ov.get("text_opacity", 1.0), 0.0, 1.0))
            box_opacity = _clamp_float(ov.get("box_opacity", 0.5), 0.0, 1.0)
            if box_opacity > 0.001:
                box_color = _ffmpeg_color(ov.get("box_color", "#000000"), box_opacity)
                box_opts = f":box=1:boxcolor={box_color}:boxborderw={max(0, int(font_size * padding_pct))}"
            else:
                box_opts = ":box=0"
            filter_complex_parts.append(
                f"[{curr_label}]drawtext=text='{text}':{font_opt}:fontcolor={font_color}:fontsize={font_size}:"
                f"x='{x_expr}':y='{y_expr}'{box_opts}{enable}[{next_label}]"
            )
            curr_label = next_label
            continue

        if ov.get("type") == "image":
            path_str = ov.get("path")
            if not path_str:
                continue
            # Escape path for FFmpeg movie filter (convert \ to /, escape : and ')
            escaped_path = str(path_str).replace("\\", "/").replace(":", "\\:").replace("'", "'\\\\\\''")
            
            w_pct = _clamp_float(ov.get("width_pct", 0.20), 0.01, 1.0)
            h_pct = _clamp_float(ov.get("height_pct", 0.20), 0.01, 1.0)
            x_pct = _clamp_float(ov.get("x_pct", 0.5), 0.0, 1.0)
            y_pct = _clamp_float(ov.get("y_pct", 0.5), 0.0, 1.0)
            opacity = _clamp_float(ov.get("opacity", 1.0), 0.0, 1.0)
            
            w_val = int(round(bw * w_pct))
            h_val = int(round(bh * h_pct))
            x_expr = f"{bx:.3f}+{bw:.3f}*{x_pct:.6f}-{w_val}/2"
            y_expr = f"{by:.3f}+{bh:.3f}*{y_pct:.6f}-{h_val}/2"
            
            # movie filter loads image, format=rgba, colorchannelmixer changes opacity, scale resizes
            movie_part = f"movie='{escaped_path}',format=rgba,colorchannelmixer=aa={opacity:.3f},scale={w_val}:{h_val}[img{idx}]"
            filter_complex_parts.append(movie_part)
            
            overlay_opts = ""
            if enable:
                clean_enable = enable.lstrip(":")
                overlay_opts = f":{clean_enable}"
                
            filter_complex_parts.append(
                f"[{curr_label}][img{idx}]overlay=x='{x_expr}':y='{y_expr}'{overlay_opts}[{next_label}]"
            )
            curr_label = next_label

    return curr_label




def apply_audio_effects(
    input_path: Path,
    output_path: Path,
    ffmpeg: str,
    pitch_semitones: float = 0.0,
    speed: float = 1.0,
    bass: int = 0,
    mid: int = 0,
    treble: int = 0,
    compression: bool = False,
    reverb: int = 0,
) -> tuple[bool, str]:
    """
    Apply audio effects to an audio file using FFmpeg filters.
    
    Args:
        input_path: Input audio file path
        output_path: Output audio file path
        ffmpeg: Path to ffmpeg executable
        pitch_semitones: Pitch shift in semitones (-12 to 12)
        speed: Playback speed multiplier (0.5 to 2.0)
        bass: Bass gain in dB (-20 to 20)
        mid: Midrange gain in dB (-20 to 20)
        treble: Treble gain in dB (-20 to 20)
        compression: Enable dynamic range compression
        reverb: Reverb amount (0-100)
    
    Returns:
        Tuple of (success, error_message)
    """
    try:
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        filters = []
        
        # Pitch shift using rubberband filter
        if pitch_semitones != 0.0:
            # rubberband pitch: factor = 2^(semitones/12)
            factor = 2 ** (pitch_semitones / 12.0)
            filters.append(f"rubberband=pitch={factor}")
        
        # Speed change using atempo filter (chain if > 2x)
        if speed != 1.0:
            # atempo only supports 0.5-2.0, chain multiple if needed
            if speed <= 2.0:
                filters.append(f"atempo={speed}")
            else:
                # Chain multiple atempo filters for speeds > 2x
                filters.append(f"atempo=2.0,atempo={speed/2.0}")
        
        # Equalizer for bass, mid, treble
        if bass != 0:
            filters.append(f"equalizer=frequency=100:width_type=h:width=100:g={bass}")
        if mid != 0:
            filters.append(f"equalizer=frequency=1000:width_type=h:width=1000:g={mid}")
        if treble != 0:
            filters.append(f"equalizer=frequency=5000:width_type=h:width=5000:g={treble}")
        
        # Compression using compand
        if compression:
            filters.append("compand=attacks=0.02:decays=0.1:points=-70/-70|-40/-20|-20/-10|0/-5|20/0:soft-knee=6")
        
        # Reverb using aecho filter
        if reverb > 0:
            # Convert 0-100 scale to 0.0-1.0
            reverb_amount = reverb / 100.0
            filters.append(f"aecho=0.8:0.9:{1000 * reverb_amount}:{reverb_amount}|{reverb_amount * 0.5}")
        
        if not filters:
            # No effects, just copy
            args = [
                ffmpeg, "-i", str(input_path),
                "-c:a", "copy",
                "-y", str(output_path)
            ]
        else:
            # Apply filter chain
            filter_complex = ",".join(filters)
            args = [
                ffmpeg, "-i", str(input_path),
                "-af", filter_complex,
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                "-y", str(output_path)
            ]
        
        success, error = run_ffmpeg(args, desc="Applying audio effects", timeout=300)
        return success, error
        
    except Exception as e:
        return False, str(e)



def _build_color_grade_filter(
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    sharpness: float = 0.0,
    scale_w: int = 0,
    scale_h: int = 0,
    crop_pct: float = 0.0,
    flip_h: bool = False,
    vignette: bool = False,
) -> str:
    """
    Tạo ffmpeg filter string cho color grading + transform.
    brightness: -1.0 → 1.0  (0 = không đổi)
    contrast:   0.5 → 2.0   (1.0 = không đổi)
    saturation: 0.0 → 3.0   (1.0 = không đổi)
    sharpness:  0.0 → 5.0   (0 = không đổi)
    scale_w/h:  0 = giữ nguyên
    crop_pct:   0.0 → 0.15  - crop % mỗi cạnh rồi scale lại kích thước gốc
    flip_h:     lật ngang video
    vignette:   thêm hiệu ứng viền tối
    """
    parts = []

    # 1. Crop + zoom lại kích thước gốc (thay đổi framing)
    if crop_pct and float(crop_pct) > 0.001:
        p = max(0.0, min(0.15, float(crop_pct)))
        # crop bỏ p% mỗi cạnh, scale lại về kích thước gốc, đảm bảo chia hết 2
        parts.append(
            f"crop=trunc(iw*(1-{p*2:.4f})/2)*2:trunc(ih*(1-{p*2:.4f})/2)*2:trunc(iw*{p:.4f}/2)*2:trunc(ih*{p:.4f}/2)*2,"
            f"scale=trunc(iw/(1-{p*2:.4f})/2)*2:trunc(ih/(1-{p*2:.4f})/2)*2:flags=lanczos"
        )
    # 2. Flip ngang
    if flip_h:
        parts.append("hflip")

    # 3. eq filter: brightness/contrast/saturation
    eq_needed = (brightness != 0.0 or contrast != 1.0 or saturation != 1.0)
    if eq_needed:
        b = max(-1.0, min(1.0, float(brightness)))
        c = max(0.5, min(2.0, float(contrast)))
        s = max(0.0, min(3.0, float(saturation)))
        parts.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}")

    # 4. Sharpness (unsharp mask)
    if sharpness and float(sharpness) > 0.05:
        la = min(1.5, float(sharpness) * 0.3)
        parts.append(f"unsharp=lx=5:ly=5:la={la:.3f}")

    # 5. Vignette (viền tối - thêm chiều sâu, thay đổi visual fingerprint)
    if vignette:
        parts.append("vignette=PI/4")

    # 6. Scale output
    if scale_w and scale_h:
        parts.append(f"scale={int(scale_w)}:{int(scale_h)}:flags=lanczos")
    elif scale_w:
        parts.append(f"scale={int(scale_w)}:-2:flags=lanczos")
    elif scale_h:
        parts.append(f"scale=-2:{int(scale_h)}:flags=lanczos")

    # 7. Đảm bảo kích thước luôn chia hết 2 (bắt buộc cho libx264)
    if parts:
        parts.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")

    return ",".join(parts) if parts else ""


def _build_anti_fingerprint_filter(
    has_overlay: bool,
    overlay_opacity: float,
    has_logo: bool,
    logo_position: str,
    logo_max_width_pct: float,
    logo_padding: int,
    logo_opacity: float,
    n_extra_inputs: int,
    color_grade: str = "",
) -> tuple[str, list[str]]:
    """
    Xây dựng filter_complex string cho anti-fingerprint.
    color_grade: chuỗi filter eq/unsharp/scale từ _build_color_grade_filter()
    """
    P = logo_padding

    pos_template = _LOGO_POSITION_MAP.get(logo_position, _LOGO_POSITION_MAP["bottom-left"])
    logo_x = pos_template[0].replace("{P}", str(P))
    logo_y = pos_template[1].replace("{P}", str(P))

    # Prefix color grade vào đầu chain nếu có
    cg_prefix = f"[0:v]{color_grade}[cg_base];" if color_grade else ""
    base_in = "[cg_base]" if color_grade else "[0:v]"

    if has_overlay and not has_logo:
        # Scale overlay về đúng kích thước video (KHÔNG split nếu không cần)
        fc = (
            f"{cg_prefix}"
            f"{base_in}[vref];"
            f"[1:v][vref]scale2ref[ov_sized][base_ref];"
            f"[ov_sized]format=rgba,colorchannelmixer=aa={overlay_opacity}[ov_alpha];"
            f"[base_ref][ov_alpha]overlay=0:0[vout]"
        )
    elif has_logo and not has_overlay:
        fc = (
            f"{cg_prefix}"
            f"{base_in}[base];"
            f"[1:v]scale2ref=w=oh*mdar:h=iw*{logo_max_width_pct}[logo_scaled][base_ref];"
            f"[logo_scaled]format=rgba,colorchannelmixer=aa={logo_opacity}[logo_alpha];"
            f"[base_ref][logo_alpha]overlay={logo_x}:{logo_y}[vout]"
        )
    elif has_overlay and has_logo:
        fc = (
            f"{cg_prefix}"
            f"{base_in}split[base][vref];"
            f"[1:v][vref]scale2ref[ov_sized][base_ref];"
            f"[ov_sized]format=rgba,colorchannelmixer=aa={overlay_opacity}[ov_alpha];"
            f"[base_ref][ov_alpha]overlay=0:0[with_ov];"
            f"[2:v][with_ov]scale2ref=w=oh*mdar:h=iw*{logo_max_width_pct}[logo_scaled][base2];"
            f"[logo_scaled]format=rgba,colorchannelmixer=aa={logo_opacity}[logo_alpha];"
            f"[base2][logo_alpha]overlay={logo_x}:{logo_y}[vout]"
        )
    else:
        # Chỉ color grade, không overlay/logo
        fc = f"{cg_prefix}{base_in}copy[vout]" if color_grade else ""

    return fc, ["[vout]"]


# ── Anti-fingerprint main function ────────────────────────────────────────────
def apply_anti_fingerprint(
    video_path: Path,
    output_path: Path,
    ffmpeg: str,
    overlay_image: Optional[str] = None,
    overlay_opacity: float = 0.02,
    logo_image: Optional[str] = None,
    logo_enabled: bool = True,
    logo_position: str = "bottom-left",
    logo_max_width_pct: float = 0.15,
    logo_opacity: float = 1.0,
    logo_padding: int = 10,
    # Color grading
    brightness: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    sharpness: float = 0.0,
    scale_w: int = 0,
    scale_h: int = 0,
    # Transform
    crop_pct: float = 0.0,
    flip_h: bool = False,
    vignette: bool = False,
    speed: float = 1.0,
) -> tuple[bool, str]:
    """
    Áp dụng color grading, transform, overlay ảnh và/hoặc logo vào video.
    speed: 0.95-1.05 thay đổi tốc độ nhẹ (1.0 = không đổi)
    """
    logger = logging.getLogger(__name__)
    project_root = Path(__file__).parent.parent

    overlay_path: Optional[Path] = None
    if overlay_image:
        overlay_path = _resolve_image_path(overlay_image, project_root)
        if overlay_path is None:
            logger.warning("apply_anti_fingerprint: overlay_image không hợp lệ: %s", overlay_image)

    logo_path: Optional[Path] = None
    if logo_image and logo_enabled:
        logo_path = _resolve_image_path(logo_image, project_root)
        if logo_path is None:
            logger.warning("apply_anti_fingerprint: logo_image không hợp lệ: %s", logo_image)

    has_overlay = overlay_path is not None
    has_logo = logo_enabled and (logo_path is not None)

    color_grade = _build_color_grade_filter(
        brightness, contrast, saturation, sharpness,
        scale_w, scale_h, crop_pct, flip_h, vignette
    )
    has_color = bool(color_grade)
    has_speed = abs(float(speed) - 1.0) > 0.005

    if not has_overlay and not has_logo and not has_color and not has_speed:
        return False, "no valid images or adjustments"

    # Speed tweak cần xử lý cả video + audio PTS
    # Dùng setpts cho video, atempo cho audio
    speed_v_filter = ""
    speed_a_filter = ""
    if has_speed:
        s = max(0.5, min(2.0, float(speed)))
        speed_v_filter = f"setpts={1.0/s:.6f}*PTS"
        # atempo chỉ hỗ trợ 0.5-2.0
        speed_a_filter = f"atempo={s:.6f}"

    cmd = [ffmpeg, "-y", "-i", str(video_path)]
    if has_overlay:
        cmd += ["-i", str(overlay_path)]
    if has_logo:
        cmd += ["-i", str(logo_path)]

    n_extra_inputs = (1 if has_overlay else 0) + (1 if has_logo else 0)

    # Kết hợp color_grade + speed_v_filter
    combined_vf = ",".join(f for f in [color_grade, speed_v_filter] if f)

    filter_str, _ = _build_anti_fingerprint_filter(
        has_overlay=has_overlay,
        overlay_opacity=overlay_opacity,
        has_logo=has_logo,
        logo_position=logo_position,
        logo_max_width_pct=logo_max_width_pct,
        logo_opacity=logo_opacity,
        logo_padding=logo_padding,
        n_extra_inputs=n_extra_inputs,
        color_grade=combined_vf,
    )

    audio_filters = [speed_a_filter] if speed_a_filter else []

    # Get hardware-optimized encoding params
    from core.hardware_presets import get_optimal_preset
    _preset = get_optimal_preset(ffmpeg)
    _enc_args = _preset.build_output_args()

    if not has_overlay and not has_logo:
        # Chỉ vf + audio filter
        vf_args = ["-vf", combined_vf] if combined_vf else []
        af_args = ["-af", ",".join(audio_filters)] if audio_filters else ["-c:a", "copy"]
        cmd += vf_args + ["-map", "0:v", "-map", "0:a?"] + af_args + _enc_args + [
            str(output_path),
        ]
    else:
        af_args = ["-af", ",".join(audio_filters)] if audio_filters else ["-c:a", "copy"]
        cmd += [
            "-filter_complex", filter_str,
            "-map", "[vout]", "-map", "0:a?",
        ] + af_args + _enc_args + [
            str(output_path),
        ]

    ok, err = run_ffmpeg(cmd)
    return (True, "") if ok else (False, err)



def make_vertical_video(
    video_path: Path,
    output_path: Path,
    ffmpeg: str,
    title: str = "",
    title_enabled: bool = True,
    title_size_pct: float = 5.0,
    title_weight: int = 400,
    title_bar_h_pct: float = 6.0,
    title_margin_x_pct: float = 5.0,
    title_color: str = "#000000",
    blur_w_pct: float = 15.0,
    blur_top_pct: float = 0.0,
    blur_bottom_pct: float = 0.0,
    blur_opacity: float = 0.6,
    blur_mode: str = "overlay",
    logo_path: Optional[str] = None,
    logo_size_pct: float = 12.0,
    logo_top_pct: float = 3.0,
    logo_left_pct: float = 3.0,
    logo_radius_pct: float = 50.0,  # 0=square, 50=circle
    logo_start_sec: Optional[float] = None,
    logo_end_sec: Optional[float] = None,
    target_w: int = 1080,
    target_h: int = 1920,
) -> tuple[bool, str]:
    """
    Add title bar + side blur + logo to a video, keeping original aspect ratio.
    blur_mode='overlay': blur panels overlap the video edges
    blur_mode='expand':  video shrinks to center, blur fills the sides
    """
    video_path  = Path(video_path)
    output_path = Path(output_path)

    # Get source video dimensions
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        m = re.search(r"(\d{2,5})x(\d{2,5})", r.stderr or "")
        src_w, src_h = (int(m.group(1)), int(m.group(2))) if m else (1280, 720)
    except Exception:
        src_w, src_h = 1280, 720

    # Side blur width in pixels
    side_w = max(0, int(target_w * blur_w_pct / 100))

    # Video area width depends on mode
    if blur_mode == "expand" and side_w > 0:
        vid_w = target_w - 2 * side_w
        vid_w = vid_w + (vid_w % 2)
    else:
        vid_w = target_w

    vid_h = int(vid_w * src_h / src_w)
    vid_h = vid_h + (vid_h % 2)

    # Title bar (chỉ nếu enabled)
    if title_enabled and title:
        title_font_px = max(16, int(target_w * title_size_pct / 100))
        title_bar_h   = max(40, int(target_h * _clamp_float(title_bar_h_pct, 3.0, 20.0) / 100))
        title_bar_h   = title_bar_h + (title_bar_h % 2)
    else:
        title_font_px = 0
        title_bar_h = 0

    out_h = vid_h + title_bar_h

    def _hex_to_ffmpeg(h: str) -> str:
        h = h.lstrip("#")
        return f"0x{h.upper()}" if len(h) == 6 else "0xFF0000"

    title_ffcolor = _hex_to_ffmpeg(title_color)
    title_font_name = "Arial Bold" if int(_clamp_float(title_weight, 300, 900)) >= 600 else "Arial"
    title_margin_px = max(0, int(target_w * _clamp_float(title_margin_x_pct, 0.0, 40.0) / 100))
    blur_str = 20

    with tempfile.TemporaryDirectory(prefix="frame_video_") as tmpdir:
        tmpdir = Path(tmpdir)

        # Build filter_complex: scale + blur + canvas + title in one pass
        filters = []
        filters.append(f"[0:v]scale={vid_w}:{vid_h}[vid]")

        if side_w > 0:
            # Left blur: stretch left edge
            filters.append(
                f"[vid]crop={min(side_w*2,vid_w)}:{vid_h}:0:0,"
                f"scale={side_w}:{vid_h},"
                f"boxblur={blur_str}:1[left_raw]"
            )
            # Right blur
            filters.append(
                f"[vid]crop={min(side_w*2,vid_w)}:{vid_h}:{max(0,vid_w-side_w*2)}:0,"
                f"scale={side_w}:{vid_h},"
                f"boxblur={blur_str}:1[right_raw]"
            )
            # Dark overlay
            alpha_hex = format(int(blur_opacity * 255), '02x')
            filters.append(f"color=black@{blur_opacity:.2f}:{side_w}x{vid_h}:r=30[dark]")

        if blur_mode == "expand" and side_w > 0:
            # Canvas = target_w × out_h, video centered
            vid_x = side_w
            filters.append(f"color=white:{target_w}x{out_h}:r=30[canvas]")
            filters.append(f"[canvas][left_raw]overlay=0:{title_bar_h}[c1]")
            filters.append(f"[c1][dark]overlay=0:{title_bar_h}[c2]")
            filters.append(f"[c2][right_raw]overlay={target_w-side_w}:{title_bar_h}[c3]")
            filters.append(f"[c3][dark]overlay={target_w-side_w}:{title_bar_h}[c4]")
            filters.append(f"[c4][vid]overlay={vid_x}:{title_bar_h}[c5]")
        elif side_w > 0:
            # overlay mode: video full width, blur overlaps
            filters.append(f"color=white:{target_w}x{out_h}:r=30[canvas]")
            filters.append(f"[canvas][vid]overlay=0:{title_bar_h}[c5a]")
            filters.append(f"[c5a][left_raw]overlay=0:{title_bar_h}[c5b]")
            filters.append(f"[c5b][dark]overlay=0:{title_bar_h}[c5c]")
            filters.append(f"[c5c][right_raw]overlay={target_w-side_w}:{title_bar_h}[c5d]")
            filters.append(f"[c5d][dark]overlay={target_w-side_w}:{title_bar_h}[c5]")
        else:
            filters.append(f"color=white:{target_w}x{out_h}:r=30[canvas]")
            filters.append(f"[canvas][vid]overlay=0:{title_bar_h}[c5]")

        # Title bar (chỉ vẽ nếu title_enabled)
        if title_enabled and title:
            filters.append(f"[c5]drawbox=x=0:y=0:w={target_w}:h={title_bar_h}:color=white:t=fill[c6]")
            safe_title = title.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"[c6]drawtext=text='{safe_title}':fontsize={title_font_px}:"
                f"fontcolor={title_ffcolor}:x='max({title_margin_px},min((w-text_w)/2,w-text_w-{title_margin_px}))':y={title_bar_h//2}-text_h/2:"
                f"font='{title_font_name}'[c7]"
            )
            last = "c7"
        else:
            last = "c5"

        # Get hardware-optimized encoding params
        from core.hardware_presets import get_optimal_preset
        _preset = get_optimal_preset(ffmpeg)
        _enc_args = _preset.build_output_args()

        cmd = [
            ffmpeg, "-i", str(video_path),
            "-filter_complex", ";".join(filters),
            "-map", f"[{last}]", "-map", "0:a?",
        ] + _enc_args + [
            str(output_path), "-y", "-loglevel", "error"
        ]
        ok, err = run_ffmpeg(cmd)
        if not ok:
            return False, f"Frame video failed: {err}"

        # Add logo (% of video height, keep aspect ratio)
        if logo_path and Path(logo_path).exists() and logo_size_pct > 0:
            # Get logo dimensions to preserve aspect ratio
            try:
                logo_r = subprocess.run(
                    [ffmpeg, "-i", str(logo_path)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                lm = re.search(r"(\d{2,5})x(\d{2,5})", logo_r.stderr or "")
                logo_nw, logo_nh = (int(lm.group(1)), int(lm.group(2))) if lm else (1, 1)
            except Exception:
                logo_nw, logo_nh = 1, 1

            logo_h_px    = max(10, int(vid_h * logo_size_pct / 100))
            logo_w_px    = max(10, int(logo_h_px * logo_nw / max(1, logo_nh)))
            logo_top_px  = title_bar_h + int(vid_h * logo_top_pct / 100)
            logo_left_px = int(target_w * logo_left_pct / 100)
            # Border radius in pixels (% of shorter side)
            r2 = int(min(logo_w_px, logo_h_px) * logo_radius_pct / 100)

            logo_tmp = tmpdir / "logo_out.mp4"
            # Use geq with rounded rectangle mask
            # For circle (r2 = half): standard arc formula
            # For rounded rect: check if point is inside rounded rect
            cx = logo_w_px // 2
            cy = logo_h_px // 2
            if logo_radius_pct >= 50:
                # Full circle
                mask_expr = f"if(lte(hypot(X-{cx},Y-{cy}),{r2}),255,0)"
            elif logo_radius_pct <= 0:
                # Square — no mask needed, just scale
                mask_expr = "255"
            else:
                # Rounded rectangle
                # Point is inside if it's in the inner rect OR within radius of a corner
                inner_x1 = r2; inner_x2 = logo_w_px - r2
                inner_y1 = r2; inner_y2 = logo_h_px - r2
                mask_expr = (
                    f"if(between(X,{inner_x1},{inner_x2}),255,"
                    f"if(between(Y,{inner_y1},{inner_y2}),255,"
                    f"if(lte(hypot(X-{inner_x1},Y-{inner_y1}),{r2}),255,"
                    f"if(lte(hypot(X-{inner_x2},Y-{inner_y1}),{r2}),255,"
                    f"if(lte(hypot(X-{inner_x1},Y-{inner_y2}),{r2}),255,"
                    f"if(lte(hypot(X-{inner_x2},Y-{inner_y2}),{r2}),255,0))))))"
                )

            def _logo_second(value):
                try:
                    number = float(value)
                    return max(0.0, number) if math.isfinite(number) else None
                except (TypeError, ValueError):
                    return None
            logo_start = _logo_second(logo_start_sec)
            logo_end = _logo_second(logo_end_sec)
            logo_enable = ""
            if logo_start is not None and logo_end is not None and logo_end > logo_start:
                logo_enable = f":enable='gte(t,{logo_start:.3f})*lt(t,{logo_end:.3f})'"
            elif logo_start is not None and logo_end is None:
                logo_enable = f":enable='gte(t,{logo_start:.3f})'"
            elif logo_end is not None and logo_start is None:
                logo_enable = f":enable='lt(t,{logo_end:.3f})'"
            logo_filter = (
                f"[1:v]scale={logo_w_px}:{logo_h_px},"
                f"format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask_expr}'[logo];"
                f"[0:v][logo]overlay={logo_left_px}:{logo_top_px}{logo_enable}"
            )
            ok2, _ = run_ffmpeg([
                ffmpeg, "-i", str(output_path), "-i", str(logo_path),
                "-filter_complex", logo_filter,
                "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "copy",
                str(logo_tmp), "-y", "-loglevel", "error"
            ])
            if ok2 and logo_tmp.exists():
                import shutil as _shutil
                _shutil.move(str(logo_tmp), str(output_path))

    return True, ""

    # Get source video dimensions
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        m = re.search(r"(\d{2,5})x(\d{2,5})", r.stderr or "")
        src_w, src_h = (int(m.group(1)), int(m.group(2))) if m else (1280, 720)
    except Exception:
        src_w, src_h = 1280, 720

    # Output dimensions: keep source AR, width = target_w
    out_w    = target_w
    out_h_vid = int(out_w * src_h / src_w)
    # Make even
    out_h_vid = out_h_vid + (out_h_vid % 2)

    # Title bar height
    title_font_px = max(16, int(out_w * title_size_pct / 100))
    title_bar_h   = int(title_font_px * 2.4)
    title_bar_h   = title_bar_h + (title_bar_h % 2)

    out_h_total = out_h_vid + title_bar_h

    # Side blur width
    side_w = max(1, int(out_w * blur_w_pct / 100))

    def _hex_to_ffmpeg(h: str) -> str:
        h = h.lstrip("#")
        return f"0x{h.upper()}" if len(h) == 6 else "0xFF0000"

    title_ffcolor = _hex_to_ffmpeg(title_color)

    with tempfile.TemporaryDirectory(prefix="frame_video_") as tmpdir:
        tmpdir = Path(tmpdir)

        # Build filter_complex (single pass — no intermediate file)
        blur_str = 20
        alpha_val = int(blur_opacity * 255)

        filters = []
        # Scale input video
        filters.append(f"[0:v]scale={out_w}:{out_h_vid}[vid]")
        # White canvas: full output size (title bar + video)
        filters.append(f"color=white:{out_w}x{out_h_total}:r=30[canvas]")
        # Video at y=title_bar_h
        filters.append(f"[canvas][vid]overlay=0:{title_bar_h}[base]")

        if side_w > 0:
            # Left blur panel
            filters.append(
                f"[vid]crop={min(side_w*2,out_w)}:{out_h_vid}:0:0,"
                f"scale={side_w}:{out_h_vid},"
                f"boxblur={blur_str}:1[left_blur]"
            )
            # Right blur panel
            filters.append(
                f"[vid]crop={min(side_w*2,out_w)}:{out_h_vid}:{max(0,out_w-side_w*2)}:0,"
                f"scale={side_w}:{out_h_vid},"
                f"boxblur={blur_str}:1[right_blur]"
            )
            # Dark overlay
            filters.append(f"color=black@{blur_opacity:.2f}:{side_w}x{out_h_vid}:r=30[dark]")
            filters.append(f"[base][left_blur]overlay=0:{title_bar_h}[c1]")
            filters.append(f"[c1][dark]overlay=0:{title_bar_h}[c2]")
            filters.append(f"[c2][right_blur]overlay={out_w-side_w}:{title_bar_h}[c3]")
            filters.append(f"[c3][dark]overlay={out_w-side_w}:{title_bar_h}[c4]")
            last_base = "c4"
        else:
            last_base = "base"

        # Title text
        if title:
            safe_title = title.replace("'", "\\'").replace(":", "\\:")
            title_y = max(0, (title_bar_h - title_font_px) // 2)
            filters.append(
                f"[{last_base}]drawtext=text='{safe_title}':fontsize={title_font_px}:"
                f"fontcolor={title_ffcolor}:x=(w-text_w)/2:y={title_y}:"
                f"font='Arial'[c_final]"
            )
            last = "c_final"
        else:
            last = last_base

        filter_str = ";".join(filters)

        _enc_args = _get_encoding_args(ffmpeg)
        cmd = [
            ffmpeg, "-i", str(video_path),
            "-filter_complex", filter_str,
            "-map", f"[{last}]", "-map", "0:a?",
        ] + _enc_args + [
            str(output_path), "-y", "-loglevel", "error"
        ]
        ok, err = run_ffmpeg(cmd)
        if not ok:
            return False, f"Frame video failed: {err}"

        # Add logo if provided
        if logo_path and Path(logo_path).exists() and logo_size_pct > 0:
            logo_h_px   = max(20, int(out_h_vid * logo_size_pct / 100))
            logo_top_px = title_bar_h + int(out_h_vid * logo_top_pct / 100)
            logo_left_px = int(out_w * 0.03)
            logo_tmp = tmpdir / "logo_out.mp4"
            logo_filter = (
                f"[1:v]scale={logo_h_px}:{logo_h_px},"
                f"format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(hypot(X-{logo_h_px//2},Y-{logo_h_px//2}),{logo_h_px//2}),255,0)'[logo];"
                f"[0:v][logo]overlay={logo_left_px}:{logo_top_px}"
            )
            ok2, _ = run_ffmpeg([
                ffmpeg, "-i", str(output_path), "-i", str(logo_path),
                "-filter_complex", logo_filter,
                "-map", "0:a?",
            ] + _enc_args + [
                str(logo_tmp), "-y", "-loglevel", "error"
            ])
            if ok2 and logo_tmp.exists():
                import shutil as _shutil
                _shutil.move(str(logo_tmp), str(output_path))

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Burn subtitles + blur original text region
# ══════════════════════════════════════════════════════════════════════════════

def preview_subtitles_in_video(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    ffmpeg: str,
    duration: int = 30,  # Preview first 30 seconds
    font_size: int = 32,
    font_color: str = "yellow",
    outline_color: str = "black",
    outline_width: int = 2,
    margin_v: int = 20,
    subtitle_position: str = "bottom"
) -> tuple[bool, str]:
    """
    Create a video preview showing subtitles overlaid (not burned) on the video.
    This allows you to see subtitle positioning before burning them permanently.

    Args:
        video_path: Path to input video
        ass_path: Path to ASS subtitle file
        output_path: Path to output preview video
        ffmpeg: Path to ffmpeg executable
        duration: Duration of preview in seconds
        font_size, font_color, etc.: Subtitle styling options

    Returns:
        (success, error_message)
    """
    video_path = Path(video_path)
    ass_path = Path(ass_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        return False, f"Video file not found: {video_path}"

    if not ass_path.exists():
        return False, f"ASS file not found: {ass_path}"

    # Escape path for ffmpeg filter
    ass_esc = str(ass_path).replace("\\", "/")
    if len(ass_esc) >= 2 and ass_esc[1] == ':':
        ass_esc = ass_esc[0] + "\\:" + ass_esc[2:]

    # Create preview with subtitles overlaid (not burned)
    cmd = [
        ffmpeg, "-i", str(video_path),
        "-vf", f"ass='{ass_esc}'",
        "-t", str(duration),  # Limit duration
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",  # Fast encoding
        "-c:a", "copy",
        str(output_path), "-y", "-loglevel", "error"
    ]

    ok, err = run_ffmpeg(cmd)

    if ok and output_path.exists():
        return True, f"Preview created: {output_path}"
    return False, err


# ══════════════════════════════════════════════════════════════════════════════
# Thumbnail Generator — Tạo ảnh thumbnail kiểu YouTube/TikTok
# ══════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(
    video_path: Path,
    output_path: Path,
    ffmpeg: str,
    timestamp: float = 2.0,
    title: str = "Trạm giải trí",
    subtitle_text: str = "",
    width: int = 1080,
    height: int = 1920,
    corner_radius: int = 40,
    title_bar_h_pct: float = 10.0,
    content_bar_h_pct: float = 40.0,
    title_font_size: int = 0,
    content_font_size: int = 0,
    logo_path: str = "",
) -> tuple[bool, str]:
    """
    Tạo thumbnail cho video với layout:
    - Trên cùng: tiêu đề kênh (VD: "Trạm giải trí") trên nền trắng
    - Giữa: frame gốc từ video (chiếm phần lớn)
    - Dưới: khung bo góc chứa nội dung/mô tả video

    Args:
        video_path: đường dẫn video nguồn
        output_path: đường dẫn ảnh thumbnail output (PNG/JPG)
        ffmpeg: đường dẫn ffmpeg
        timestamp: thời điểm lấy frame (giây)
        title: tiêu đề kênh hiển thị trên cùng
        subtitle_text: nội dung hiển thị ở khung dưới (nếu rỗng sẽ lấy từ tên video)
        width/height: kích thước thumbnail (mặc định 1080x1920 cho vertical)
        corner_radius: bán kính bo góc khung dưới
        title_bar_h_pct: chiều cao thanh tiêu đề (% tổng height)
        content_bar_h_pct: chiều cao khung nội dung dưới (% tổng height)
        title_font_size: cỡ chữ tiêu đề (0 = tự tính)
        content_font_size: cỡ chữ nội dung (0 = tự tính)
        logo_path: đường dẫn logo chèn góc khung mô tả

    Returns:
        (success, error_or_path)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False, "Pillow chưa cài: pip install Pillow"

    # Resolve logo path
    resolved_logo = None
    if logo_path:
        p = Path(logo_path)
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        if p.exists():
            resolved_logo = p
    logo_img = None
    if resolved_logo:
        try:
            logo_img = Image.open(resolved_logo).convert("RGBA")
        except Exception:
            pass

    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        return False, f"Video không tồn tại: {video_path}"

    # ── Bước 1: Extract frame từ video ────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="thumb_") as tmpdir:
        tmp_video = Path(tmpdir) / f"input{video_path.suffix}"
        tmp_frame = Path(tmpdir) / "frame.png"

        import shutil
        shutil.copy2(str(video_path), str(tmp_video))

        ok, err = run_ffmpeg([
            ffmpeg, "-ss", str(timestamp),
            "-i", str(tmp_video),
            "-vframes", "1",
            "-q:v", "1",
            str(tmp_frame), "-y", "-loglevel", "error"
        ])

        if not ok or not tmp_frame.exists():
            return False, f"Không extract được frame: {err}"

        frame_img = Image.open(tmp_frame).convert("RGBA")

    # ── Bước 2: Tính toán layout ─────────────────────────────────────────────
    title_bar_h = max(60, int(height * title_bar_h_pct / 100))
    # Tăng chiều cao banner lên tối thiểu 40% chiều cao video để đè hoàn toàn phụ đề gốc (tiếng Trung/Anh)
    actual_content_bar_h_pct = max(content_bar_h_pct, 40.0)
    content_bar_h = max(80, int(height * actual_content_bar_h_pct / 100))
    # Video frame kéo dài xuống tận đáy màn hình để làm nền trong suốt bên dưới banner
    frame_area_h = height - title_bar_h

    # Font sizes
    if not title_font_size:
        title_font_size = max(28, int(width * 0.055))
    if not content_font_size:
        # Tăng kích thước chữ mô tả to rõ rệt hơn (6.5% width thay vì 4%)
        content_font_size = max(38, int(width * 0.065))

    # ── Bước 3: Tạo canvas ───────────────────────────────────────────────────
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # ── Bước 4: Vẽ title bar (nền trắng + text) ──────────────────────────────
    # Title bar đã là nền trắng (canvas), chỉ cần vẽ text
    try:
        # Thử load font hệ thống
        font_paths = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei (hỗ trợ tiếng Việt)
        ]
        title_font = None
        for fp in font_paths:
            if Path(fp).exists():
                title_font = ImageFont.truetype(fp, title_font_size)
                break
        if not title_font:
            title_font = ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()

    # Vẽ tiêu đề căn giữa
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (width - title_w) // 2
    title_y = (title_bar_h - (title_bbox[3] - title_bbox[1])) // 2
    draw.text((title_x, title_y), title, fill=(220, 50, 50, 255), font=title_font)

    # Vẽ đường kẻ dưới title bar
    draw.line([(20, title_bar_h - 2), (width - 20, title_bar_h - 2)], fill=(230, 230, 230, 255), width=2)

    # ── Bước 5: Resize và paste frame video ──────────────────────────────────
    # Scale frame để fill vùng giữa (crop nếu cần)
    frame_w, frame_h = frame_img.size
    scale = max(width / frame_w, frame_area_h / frame_h)
    new_w = int(frame_w * scale)
    new_h = int(frame_h * scale)
    frame_resized = frame_img.resize((new_w, new_h), Image.LANCZOS)

    # Crop center
    left = (new_w - width) // 2
    top = (new_h - frame_area_h) // 2
    frame_cropped = frame_resized.crop((left, top, left + width, top + frame_area_h))

    canvas.paste(frame_cropped, (0, title_bar_h))

    # ── Bước 6: Vẽ khung nội dung dưới (Gradient xanh nhạt & khung vuông nổi bật với Padding viền ngoài) ─────────────────────────────
    # Dán đè banner lên trên video frame ở sát mép dưới màn hình
    content_y = height - content_bar_h

    # Tạo khung nội dung dưới
    content_box = Image.new("RGBA", (width, content_bar_h), (0, 0, 0, 0))
    content_draw = ImageDraw.Draw(content_box)

    # Padding viền ngoài của cả banner so với các cạnh màn hình (banner_margin_x = 20, banner_margin_y = 20)
    # Ranh giới thực tế của banner sẽ nằm gọn trong khoảng này
    banner_x0 = 20
    banner_y0 = 10
    banner_x1 = width - 20
    banner_y1 = content_bar_h - 20

    # Bán kính bo góc (R = 60) cho góc phải trên và góc trái dưới
    R = 60
    
    # 1. Vẽ Outer Shape (Nền trắng làm viền 10px)
    outer_mask = Image.new("L", (width, content_bar_h), 0)
    outer_mask_draw = ImageDraw.Draw(outer_mask)
    
    # Vẽ hình asymmetric bo góc phải trên và trái dưới
    outer_mask_draw.rectangle([(banner_x0, banner_y0), (banner_x1, banner_y1)], fill=255)
    # Bo góc phải trên
    outer_mask_draw.rectangle([(banner_x1 - R, banner_y0), (banner_x1, banner_y0 + R)], fill=0)
    outer_mask_draw.ellipse([(banner_x1 - 2*R, banner_y0), (banner_x1, banner_y0 + 2*R)], fill=255)
    # Bo góc trái dưới
    outer_mask_draw.rectangle([(banner_x0, banner_y1 - R), (banner_x0 + R, banner_y1)], fill=0)
    outer_mask_draw.ellipse([(banner_x0, banner_y1 - 2*R), (banner_x0 + 2*R, banner_y1)], fill=255)
    
    # Tạo ảnh nền viền trắng
    white_banner = Image.new("RGBA", (width, content_bar_h), (255, 255, 255, 255))
    content_box.paste(white_banner, (0, 0), outer_mask)

    # 2. Vẽ Inner Shape (Gradient màu) thụt vào 18px để lộ ra 18px viền trắng ngoài
    inner_x0 = banner_x0 + 18
    inner_y0 = banner_y0 + 18
    inner_x1 = banner_x1 - 18
    inner_y1 = banner_y1 - 18
    R_inner = max(0, R - 18)
    
    inner_mask = Image.new("L", (width, content_bar_h), 0)
    inner_mask_draw = ImageDraw.Draw(inner_mask)
    
    inner_mask_draw.rectangle([(inner_x0, inner_y0), (inner_x1, inner_y1)], fill=255)
    # Bo góc phải trên inner
    inner_mask_draw.rectangle([(inner_x1 - R_inner, inner_y0), (inner_x1, inner_y0 + R_inner)], fill=0)
    inner_mask_draw.ellipse([(inner_x1 - 2*R_inner, inner_y0), (inner_x1, inner_y0 + 2*R_inner)], fill=255)
    # Bo góc trái dưới inner
    inner_mask_draw.rectangle([(inner_x0, inner_y1 - R_inner), (inner_x0 + R_inner, inner_y1)], fill=0)
    inner_mask_draw.ellipse([(inner_x0, inner_y1 - 2*R_inner), (inner_x0 + 2*R_inner, inner_y1)], fill=255)

    # Chiều cao thực tế của vùng chứa gradient bên trong banner
    grad_h = inner_y1 - inner_y0
    
    # Gradient dưới đậm trên nhạt (màu xanh nhạt cực kỳ premium)
    # RGB top: (150, 215, 255) / RGB bottom: (12, 60, 140)
    R1, G1, B1 = 150, 215, 255
    R2, G2, B2 = 12, 60, 140
    
    grad_img = Image.new("RGBA", (width, content_bar_h), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad_img)
    for y in range(inner_y0, inner_y1):
        pct = (y - inner_y0) / grad_h if grad_h > 0 else 0
        r = int(R1 + (R2 - R1) * pct)
        g = int(G1 + (G2 - G1) * pct)
        b = int(B1 + (B2 - B1) * pct)
        grad_draw.line([(inner_x0, y), (inner_x1, y)], fill=(r, g, b, 255), width=1)

    # Dán đè gradient lên trên nền viền trắng của content_box
    content_box.paste(grad_img, (0, 0), inner_mask)

    # Nội dung text
    if not subtitle_text:
        # Lấy từ tên video, bỏ ký tự đặc biệt
        subtitle_text = video_path.stem
        subtitle_text = re.sub(r'[_\-]+', ' ', subtitle_text)
        subtitle_text = re.sub(r'\d{10,}', '', subtitle_text).strip()
        if not subtitle_text:
            subtitle_text = "Video giải trí"

    try:
        content_font = None
        for fp in font_paths:
            if Path(fp).exists():
                content_font = ImageFont.truetype(fp, content_font_size)
                break
        if not content_font:
            content_font = ImageFont.load_default()
    except Exception:
        content_font = ImageFont.load_default()

    # Word wrap cho nội dung với padding X rộng rãi so với viền banner (padding_x = 90)
    padding_x = 90
    max_text_w = (inner_x1 - inner_x0) - (padding_x * 2)
    words = subtitle_text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        bbox = content_draw.textbbox((0, 0), test_line, font=content_font)
        if bbox[2] - bbox[0] <= max_text_w:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Nếu text quá dài, giới hạn 3 dòng
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:30] + "..."

    # Vẽ text nội dung căn giữa trong khung với bóng đổ đen và chữ trắng nổi bật, tăng line_height lên làm giãn dòng (padding Y)
    line_height = content_font_size + 15
    total_text_h = len(lines) * line_height
    text_start_y = inner_y0 + (grad_h - total_text_h) // 2
    for i, line in enumerate(lines):
        bbox = content_draw.textbbox((0, 0), line, font=content_font)
        lw = bbox[2] - bbox[0]
        lx = inner_x0 + ((inner_x1 - inner_x0) - lw) // 2
        ly = text_start_y + i * line_height
        # Bóng đổ tối màu phía sau (xanh đậm / đen)
        content_draw.text((lx + 3, ly + 3), line, fill=(5, 20, 60, 200), font=content_font)
        # Chữ màu trắng chính thức ở trên
        content_draw.text((lx, ly), line, fill=(255, 255, 255, 255), font=content_font)

    canvas.paste(content_box, (0, content_y), content_box)

    # ── Bước 6b: Chèn logo tròn lớn đè lên góc trên bên trái của banner ────────────────
    if logo_img:
        # Bán kính badge hình tròn trắng to lên thêm 1 tí (9% chiều rộng video)
        badge_r = max(60, int(width * 0.09))
        # Dịch logo vào bên trong thêm (badge_cx = banner_x0 + badge_r - 20) để hiển thị hoàn toàn trên màn hình, không bị cắt xén
        badge_cx = banner_x0 + badge_r - 20
        badge_cy = content_y + banner_y0 + 15
        
        # Vẽ badge nền tròn trắng đè lên trên viền góc (giảm độ dày đường viền ngoài)
        draw.ellipse(
            [(badge_cx - badge_r, badge_cy - badge_r), (badge_cx + badge_r, badge_cy + badge_r)],
            fill=(255, 255, 255, 255),
            outline=(255, 255, 255, 255),
            width=1
        )
        
        # Resize logo để khít hơn trong hình tròn (tăng logo_size từ 1.6 lên 1.88 lần badge_r để giảm viền trắng bao quanh logo)
        logo_size = int(badge_r * 1.88)
        logo_resized = logo_img.resize((logo_size, logo_size), Image.LANCZOS)
        
        # Tạo mask tròn cho logo
        mask = Image.new("L", (logo_size, logo_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([(0, 0), (logo_size, logo_size)], fill=255)
        
        # Paste logo
        logo_x = badge_cx - logo_size // 2
        logo_y = badge_cy - logo_size // 2
        canvas.paste(logo_resized, (logo_x, logo_y), mask)

    # ── Bước 7: Lưu output ───────────────────────────────────────────────────
    # Convert to RGB nếu output là JPG
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        canvas = canvas.convert("RGB")
        canvas.save(str(output_path), "JPEG", quality=92)
    else:
        canvas.save(str(output_path), "PNG")

    if output_path.exists() and output_path.stat().st_size > 0:
        return True, str(output_path)
    return False, "Không tạo được thumbnail"

def _parse_content_aspect(value):
    """Accept custom positive W:H ratios and legacy WxH saved profiles."""
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*[:xX/×]\s*(\d+(?:[.,]\d+)?)\s*", str(value or ""))
    if not match:
        return None
    width, height = (float(part.replace(",", ".")) for part in match.groups())
    if not (0 < width < float("inf") and 0 < height < float("inf")):
        return None
    ratio = width / height
    return ratio if 0 < ratio < float("inf") else None

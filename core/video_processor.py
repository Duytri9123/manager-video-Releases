#!/usr/bin/env python3
"""
video_processor.py — Xử lý video sau khi tải:
  1. Burn subtitles (SRT → hardcode vào video)
  2. Blur/làm mờ text gốc trên video (detect vùng subtitle gốc)
  3. Voice conversion: ZH → VI (Whisper transcribe → dịch → TTS edge-tts)

Yêu cầu:
  pip install openai-whisper edge-tts pydub
  ffmpeg phải có trong PATH
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator, Optional


FPT_TTS_ENDPOINT = "https://api.fpt.ai/hmi/tts/v5"
# FPT key must come from env (FPT_TTS_API_KEY) or config (video_process.fpt_api_key).
# Hard-coded keys removed for security.
FPT_TTS_DEFAULT_KEY = ""
TTS_CACHE_VERSION = "tts-ass-merge-v1"

# ElevenLabs TTS endpoint
ELEVENLABS_TTS_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Default ElevenLabs voice ID: Rachel (en) — overridable via config elevenlabs_voice_id
ELEVENLABS_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Fish Audio TTS — multilingual backbone, excels at JA/ZH/KO phonetics
# Docs: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
FISH_TTS_ENDPOINT = "https://api.fish.audio/v1/tts"
FISH_DEFAULT_MODEL = "s2-pro"  # backbone: "s2-pro" (recommended) or "s1"


# ── ffmpeg helper ─────────────────────────────────────────────────────────────
def find_ffmpeg() -> Optional[str]:
    p = shutil.which("ffmpeg")
    if p:
        return p
    local = Path(__file__).parent.parent / "cli" / "ffmpeg.exe"
    if local.exists():
        return str(local)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    return None


def run_ffmpeg(args: list, desc: str = "", timeout: int = 600) -> tuple[bool, str]:
    """Run ffmpeg command, return (success, stderr). Timeout default 10 minutes."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode == 0, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, f"FFmpeg timeout sau {timeout}s — video quá dài hoặc filter quá nặng"
    except Exception as e:
        return False, str(e)


def _get_encoding_args(ffmpeg: Optional[str] = None) -> list[str]:
    """Get hardware-optimized encoding args. Falls back to libx264 veryfast crf 23."""
    try:
        from core.hardware_presets import get_optimal_preset
        preset = get_optimal_preset(ffmpeg)
        return preset.build_output_args()
    except Exception:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k"]


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
    """Generate AI thumbnail. Priority order:
    1. 9Router (cx/gpt-5.5-image) — uses extracted frame as reference image
    2. Gemini 2.5 Flash Image — fallback when 9Router not configured

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

    nr_cfg = cfg.get("nine_router") or {}
    nr_endpoint = (nr_cfg.get("endpoint") or "").strip().rstrip("/")
    nr_key = (nr_cfg.get("api_key") or "").strip()
    use_9router = bool(nr_endpoint and nr_key)

    gemini_key = (
        (cfg.get("gemini_video") or {}).get("api_key", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )

    if not use_9router and not gemini_key:
        return None

    # Step 1: extract frame from video (used as reference for both providers)
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

            # Build prompt (chung cho cả 2 provider)
            gen_prompt = (
                f"Eye-catching YouTube thumbnail in 16:9. "
                f"Title: {title or 'video'}. "
                f"Content: {subtitle_text or title or 'video'}. "
                f"Vibrant colors, high contrast, professional, sharp focus, dramatic lighting."
            )

            # ── PRIORITY 1: 9Router (cx/gpt-5.5-image) ──────────────────────
            if use_9router:
                model_id = (nr_cfg.get("default_image_model") or "cx/gpt-5.5-image").strip() or "cx/gpt-5.5-image"
                try:
                    payload = {
                        "model": model_id,
                        "prompt": gen_prompt[:2000],
                        "n": 1,
                        "size": "1792x1024",  # 16:9
                        "quality": "standard",
                        "response_format": "b64_json",
                        # multimodal reference frame
                        "images": [frame_b64],
                        "image": frame_b64,
                    }
                    body = _json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(
                        f"{nr_endpoint}/images/generations",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {nr_key}",
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=240) as resp:
                        rdata = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
                    img_data = (rdata.get("data") or [{}])[0]
                    img_b64_data = img_data.get("b64_json")
                    img_url_remote = img_data.get("url")
                    if img_b64_data:
                        output_path.write_bytes(base64.b64decode(img_b64_data))
                        if output_path.exists() and output_path.stat().st_size > 1024:
                            return output_path
                    elif img_url_remote:
                        with urllib.request.urlopen(img_url_remote, timeout=180) as dl:
                            output_path.write_bytes(dl.read())
                        if output_path.exists() and output_path.stat().st_size > 1024:
                            return output_path
                except Exception:
                    # Fall through to Gemini
                    pass

            # ── PRIORITY 2: Gemini fallback ─────────────────────────────────
            if not gemini_key:
                return None

            # Step 2: ask Gemini Vision to refine prompt based on frame
            prompt_text = (
                f"You are a YouTube thumbnail designer. Analyze this video frame and write a concise "
                f"image-generation prompt (under 150 words) for a click-worthy 16:9 thumbnail. "
                f"Title/Brand: {title or 'N/A'}. Content hint: {subtitle_text or 'N/A'}. "
                f"Output ONLY the prompt text."
            )
            try:
                vision_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
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
            img_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={gemini_key}"
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


def get_media_duration_seconds(ffmpeg: str, media_path: Path) -> float:
    """Best-effort duration parser from ffmpeg stderr output."""
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(media_path), "-f", "null", "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in (r.stderr or "").splitlines():
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _safe_stem(stem: str) -> str:
    """Chuẩn hoá tên file/folder cho output:
    - Bỏ dấu tiếng Việt (NFD + ASCII fallback) để tránh Unicode dài + giảm risk
      Windows MAX_PATH (260). Đặc biệt 'đ' → 'd', 'Đ' → 'D'.
    - Bỏ ký tự đặc biệt không hợp lệ trong tên file.
    - Giới hạn 60 ký tự để pipeline (folder + file + suffix) không vượt MAX_PATH.
    """
    import unicodedata

    raw = (stem or "").replace("\n", " ").replace("\r", " ")
    # Đặc biệt cho tiếng Việt: đ/Đ không tách bằng NFD
    raw = raw.replace("đ", "d").replace("Đ", "D")
    # Tách dấu rồi loại bỏ combining marks
    nfkd = unicodedata.normalize("NFD", raw)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Loại ký tự không hợp lệ cho tên file (Windows + Unix)
    ascii_str = re.sub(r'[<>:"/\\|?*#!]', "_", ascii_str)
    # Giữ chữ-số-_-.- và space; mọi thứ khác thành "_"
    ascii_str = re.sub(r"[^\w.\- ]", "_", ascii_str, flags=re.ASCII)
    ascii_str = re.sub(r"[\s_]+", "_", ascii_str).strip("_ ")
    return ascii_str[:60] or "video"


def _winlong(p) -> str:
    """Convert path to Windows long-path form (\\\\?\\C:\\...) when needed.
    Trên non-Windows hoặc path ngắn → trả str(p) như cũ.
    Cần thiết khi path > 260 ký tự để open()/write_text() không lỗi Errno 2."""
    import os as _os
    s = str(p)
    if _os.name != "nt":
        return s
    if s.startswith("\\\\?\\"):
        return s
    # Chỉ áp dụng cho absolute path
    try:
        abspath = _os.path.abspath(s)
    except Exception:
        return s
    if len(abspath) < 200:
        return s  # path ngắn, không cần long-prefix
    # UNC path: \\server\share → \\?\UNC\server\share
    if abspath.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abspath[2:]
    return "\\\\?\\" + abspath


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp_float(value: float, low: float, high: float) -> float:
    try:
        v = float(value)
    except Exception:
        v = low
    return max(low, min(high, v))


def _fmt_hms(seconds: float) -> str:
    total = max(0.0, float(seconds))
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def has_audio_track(video_path: Path, ffmpeg: str) -> bool:
    """Check if video has at least one audio stream."""
    try:
        video_path = Path(video_path)
        r = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        stderr = r.stderr or ""
        # Look for "Audio: " in ffmpeg output
        return "Audio:" in stderr
    except Exception:
        return False


# ── Image path helper ─────────────────────────────────────────────────────────
_SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _resolve_image_path(image_path: str, project_root: Path) -> Optional[Path]:
    """
    Resolve đường dẫn ảnh (tuyệt đối hoặc tương đối so với project root).
    Kiểm tra định dạng hợp lệ (PNG, JPG, JPEG, WEBP).
    Returns None nếu không hợp lệ.
    """
    if not image_path:
        return None
    p = Path(image_path)
    if not p.is_absolute():
        p = project_root / p
    if not p.exists():
        return None
    if p.suffix.lower() not in _SUPPORTED_IMAGE_EXTS:
        return None
    return p


# ── Anti-fingerprint filter builder ──────────────────────────────────────────
_LOGO_POSITION_MAP = {
    "top-left":     ("{P}", "{P}"),
    "top-right":    ("W-w-{P}", "{P}"),
    "bottom-left":  ("{P}", "H-h-{P}"),
    "bottom-right": ("W-w-{P}", "H-h-{P}"),
}


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


# ── SRT helpers ───────────────────────────────────────────────────────────────
def _fmt_srt_time(seconds: float) -> str:
    h, r = divmod(seconds, 3600)
    m, r = divmod(r, 60)
    s = int(r)
    ms = int((r - s) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{s:02d},{ms:03d}"


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds → ASS timestamp h:mm:ss.cs"""
    h, r = divmod(seconds, 3600)
    m, r = divmod(r, 60)
    s = int(r)
    cs = int((r - s) * 100)
    return f"{int(h)}:{int(m):02d}:{s:02d}.{cs:02d}"


def write_ass(segments: list[dict], out_path: Path,
              font_size: int = 32, font_color: str = "white",
              outline_color: str = "black", outline_width: int = 2,
              shadow: int = 1, margin_v: int = 20,
              alignment: int = 2, font_name: str = "Arial",
              play_res_x: int = 1280, play_res_y: int = 720) -> Path:
    """
    Write ASS subtitle file from segments list.
    alignment: 2=bottom-center, 8=top-center
    """
    primary  = f"&H00{_hex_color(font_color)}"
    outline  = f"&H00{_hex_color(outline_color)}"
    shadow_c = "&H80000000"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary},&H000000FF,{outline},{shadow_c},-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _split_words(text, max_words=5):
        """Tách text thành các dòng tối đa max_words từ mỗi dòng."""
        words = text.split()
        result = []
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i:i + max_words])
            if chunk:
                result.append(chunk)
        return result if result else [text]

    lines = [header]
    for seg in segments:
        text = seg.get("text", "").replace("\n", " ").strip()
        if not text:
            continue
        split_lines = _split_words(text, max_words=5)
        n = len(split_lines)
        seg_duration = (seg["end"] - seg["start"]) / n
        for i, line in enumerate(split_lines):
            sub_start = seg["start"] + i * seg_duration
            sub_end = seg["start"] + (i + 1) * seg_duration - 0.01
            s = _fmt_ass_time(sub_start)
            e = _fmt_ass_time(sub_end)
            lines.append(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{line}")

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _parse_srt(srt_path: Path) -> list[dict]:
    """Parse SRT → list of {index, start, end, text}"""
    segments = []
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
            times = lines[1].strip()
            m = re.match(r'(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)', times)
            if not m:
                continue
            def to_sec(t):
                t = t.replace(',', '.')
                parts = t.split(':')
                return int(parts[0])*3600 + int(parts[1])*60 + float(parts[2])
            text = '\n'.join(lines[2:]).strip()
            segments.append({'index': idx, 'start': to_sec(m.group(1)), 'end': to_sec(m.group(2)), 'text': text})
        except Exception:
            continue
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
            text  = re.sub(r"\s+", " ", text).strip()
            if text:
                segments.append({"start": start, "end": end, "text": text})
        except Exception:
            continue
    return segments


def _merge_segments_for_tts(
    segments: list[dict],
    max_gap: float = 0.08,
    max_chars: int = 260,
    max_duration: float = 12.0,
) -> list[dict]:
    """Merge display-oriented subtitle chunks into more natural TTS units."""
    merged: list[dict] = []
    current: dict | None = None
    terminal_punct = tuple(".!?…。！？")

    for seg in sorted(segments or [], key=lambda s: float(s.get("start", 0.0))):
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if end <= start:
            continue

        item = {"start": start, "end": end, "text": text}
        if current is None:
            current = item
            continue

        gap = start - float(current.get("end", start))
        combined_text = f"{current.get('text', '')} {text}".strip()
        combined_duration = end - float(current.get("start", start))
        prev_text = str(current.get("text") or "").rstrip()
        can_merge = (
            gap <= max_gap
            and len(combined_text) <= max_chars
            and combined_duration <= max_duration
            and not prev_text.endswith(terminal_punct)
        )

        if can_merge:
            current["end"] = max(float(current["end"]), end)
            current["text"] = combined_text
        else:
            merged.append(current)
            current = item

    if current is not None:
        merged.append(current)
    return merged


def _run_ffmpeg(args: list, desc: str = "") -> tuple[bool, str]:
    """Alias for run_ffmpeg — run an ffmpeg command, return (success, stderr)."""
    return run_ffmpeg(args, desc)


# ══════════════════════════════════════════════════════════════════════════════
# GroqWhisperTranscriber  (default — cloud API, much faster than local CPU)
# ══════════════════════════════════════════════════════════════════════════════
_GROQ_MODEL   = "whisper-large-v3-turbo"
_GROQ_MAX_MB  = 25  # Groq free tier limit


class GroqWhisperTranscriber:
    """Speech-to-text via Groq Whisper API (cloud, fast)."""

    def __init__(self, language: str = "zh", api_key: str = "", model: str = _GROQ_MODEL, max_mb: int = _GROQ_MAX_MB):
        self.language = language
        self.api_key = (api_key or "").strip()
        self.model = str(model or _GROQ_MODEL).strip() or _GROQ_MODEL
        try:
            self.max_mb = int(max_mb)
        except Exception:
            self.max_mb = _GROQ_MAX_MB

    def transcribe(self, video_path: Path, ffmpeg: str, out_srt: Path) -> list[dict]:
        import httpx

        video_path = Path(video_path)
        out_srt    = Path(out_srt)

        with tempfile.TemporaryDirectory(prefix="groq_whisper_") as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(video_path),
                "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-q:a", "5",
                str(audio_path), "-y", "-loglevel", "error"
            ])
            if not ok or not audio_path.exists():
                raise RuntimeError(f"Audio extraction failed: {err}")

            size_mb = audio_path.stat().st_size / (1024 * 1024)
            if size_mb > self.max_mb:
                raise RuntimeError(f"Audio too large for Groq API: {size_mb:.1f}MB > {self.max_mb}MB")

            if not self.api_key:
                raise RuntimeError("Missing GROQ_API_KEY (set env GROQ_API_KEY or config transcript.groq_api_key)")

            with open(audio_path, "rb") as f:
                response = httpx.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": ("audio.mp3", f, "audio/mpeg")},
                    data={
                        "model": self.model,
                        "language": self.language,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                    },
                    timeout=120,
                )

            if response.status_code != 200:
                raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")

            result = response.json()
            segments = [
                {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
                for seg in result.get("segments", [])
                if seg.get("text", "").strip()
            ]

        srt_lines = []
        for i, seg in enumerate(segments, 1):
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{seg['text']}\n"
            )
        # Dùng _winlong để xử lý path > 260 ký tự trên Windows
        with open(_winlong(out_srt), "w", encoding="utf-8") as _f:
            _f.write("\n".join(srt_lines))
        return segments


# ══════════════════════════════════════════════════════════════════════════════
# FasterWhisperTranscriber  (fallback — local CPU)
# ══════════════════════════════════════════════════════════════════════════════
_whisper_model_cache: dict = {}  # {model_name: WhisperModel} — keep in memory


class FasterWhisperTranscriber:
    """Speech-to-text using faster-whisper (~4x faster than openai-whisper on CPU)."""

    def __init__(self, model_name: str, language: str, use_vad: bool = True):
        self.model_name = model_name
        self.language = language
        self.use_vad = use_vad
        # Reuse cached model to avoid reloading from disk on every call
        if model_name not in _whisper_model_cache:
            import os
            import multiprocessing
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from faster_whisper import WhisperModel  # lazy import
            cpu_threads = min(multiprocessing.cpu_count(), 8)
            _whisper_model_cache[model_name] = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
                num_workers=2,
            )
        self._model = _whisper_model_cache[model_name]

    def transcribe(self, video_path: Path, ffmpeg: str, out_srt: Path) -> list[dict]:
        """
        Extract audio from video, transcribe with faster-whisper, write SRT.
        Returns list of {"start": float, "end": float, "text": str} dicts.
        """
        video_path = Path(video_path)
        out_srt = Path(out_srt)

        with tempfile.TemporaryDirectory(prefix="fwhisper_") as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(audio_path), "-y", "-loglevel", "error"
            ])
            if not ok or not audio_path.exists():
                raise RuntimeError(f"Audio extraction failed: {err}")

            fw_segments, _info = self._model.transcribe(
                str(audio_path),
                language=self.language,
                vad_filter=self.use_vad,
                beam_size=1,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = [
                {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                for seg in fw_segments
                if seg.text.strip()
            ]

        # write SRT
        srt_lines = []
        for i, seg in enumerate(segments, 1):
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{seg['text']}\n"
            )
        with open(_winlong(out_srt), "w", encoding="utf-8") as _f:
            _f.write("\n".join(srt_lines))

        return segments


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Whisper transcribe → SRT
# ══════════════════════════════════════════════════════════════════════════════
def transcribe_to_srt(
    video_path: Path,
    ffmpeg: str,
    model_name: str = "base",
    language: str = "zh",
    out_srt: Optional[Path] = None,
) -> tuple[Optional[Path], list[dict]]:
    """
    Transcribe video audio → SRT file.
    Returns (srt_path, segments).
    """
    try:
        import whisper
    except ImportError:
        raise RuntimeError("openai-whisper not installed: pip install openai-whisper")

    video_path = Path(video_path)
    if out_srt is None:
        out_srt = video_path.parent / f"{_safe_stem(video_path.stem)}.srt"

    with tempfile.TemporaryDirectory(prefix="vproc_") as tmpdir:
        # copy video to temp (avoid special chars in path)
        tmp_video = Path(tmpdir) / "input.mp4"
        shutil.copy2(str(video_path), str(tmp_video))

        # extract audio
        audio_path = Path(tmpdir) / "audio.wav"
        ok, err = run_ffmpeg([
            ffmpeg, "-i", str(tmp_video),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path), "-y", "-loglevel", "error"
        ])
        if not ok or not audio_path.exists():
            raise RuntimeError(f"Audio extraction failed: {err}")

        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), language=language, verbose=False)
        segments = result.get("segments", [])

    if not segments:
        return None, []

    # write SRT
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        text = seg.get("text", "").strip()
        if text:
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{text}\n"
            )
    out_srt.write_text("\n".join(srt_lines), encoding="utf-8")
    return out_srt, segments


# ══════════════════════════════════════════════════════════════════════════════
# FRAME VIDEO: Convert to 9:16 with title bar, side blur, logo
# ══════════════════════════════════════════════════════════════════════════════
def make_vertical_video(
    video_path: Path,
    output_path: Path,
    ffmpeg: str,
    title: str = "",
    title_enabled: bool = True,
    title_size_pct: float = 5.0,
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
        title_bar_h   = int(title_font_px * 2.4)
        title_bar_h   = title_bar_h + (title_bar_h % 2)
    else:
        title_font_px = 0
        title_bar_h = 0

    out_h = vid_h + title_bar_h

    def _hex_to_ffmpeg(h: str) -> str:
        h = h.lstrip("#")
        return f"0x{h.upper()}" if len(h) == 6 else "0xFF0000"

    title_ffcolor = _hex_to_ffmpeg(title_color)
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
                f"fontcolor={title_ffcolor}:x=(w-text_w)/2:y={title_bar_h//2}-text_h/2:"
                f"font='Arial'[c7]"
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

            logo_filter = (
                f"[1:v]scale={logo_w_px}:{logo_h_px},"
                f"format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{mask_expr}'[logo];"
                f"[0:v][logo]overlay={logo_left_px}:{logo_top_px}"
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
        if logo_path and Path(logo_path).exists():
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
    blur_extra_zones: Optional[list] = None,
) -> tuple[bool, str]:
    """
    Burn subtitles into video.
    If subtitle_format='ass': use ASS filter (no blur needed, faster).
    If subtitle_format='srt': use SRT with optional blur strip.
    If frame_enabled=True: also creates 9:16 frame in same encode pass (ASS mode only).
    """
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
                         blur_extra_zones=blur_extra_zones)

    # SRT path (original logic — no frame support)
    return _burn_srt(video_path, srt_path, output_path, ffmpeg,
                     blur_original, blur_zone, blur_height_pct, blur_width_pct, blur_lift_pct_adj,
                     font_size, font_color, outline_color, outline_width,
                     margin_v, subtitle_position,
                     blur_y_pct=blur_y_pct,
                     blur_extra_zones=blur_extra_zones)


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
    blur_extra_zones: Optional[list] = None,
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

        def _ass_comment_float(label: str, default: float = 0.0) -> float:
            m = re.search(rf"^; {re.escape(label)}:\s*([\d.]+)", _ass_content, re.MULTILINE)
            if not m:
                return default
            try:
                return float(m.group(1))
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
            if blur_y_pct is not None:
                y_start = _clamp_float(blur_y_pct - h_pct / 2, 0.0, 1.0 - h_pct)
            else:
                lift_pct = _clamp_float(blur_lift_pct, 0.0, 0.20)
                if blur_zone == "bottom":
                    y_start = max(0.0, 1.0 - h_pct - lift_pct)
                else:
                    y_start = 0.0
            active_zones.append((h_pct, w_pct, y_start, 0.5, None, None))
            
        if blur_original and blur_extra_zones:
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
            if _st is not None or _en is not None:
                _s0 = float(_st) if _st is not None else 0.0
                _e0 = float(_en) if _en is not None else 1e9
                _en_expr = f":enable='between(t,{_s0:.3f},{_e0:.3f})'"
            filter_complex_parts.append(f"[{curr_label}]split[orig_{idx}][copy_{idx}]")
            filter_complex_parts.append(
                f"[copy_{idx}]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{_left:.4f}:ih*{y:.4f},"
                f"boxblur=luma_radius=20:luma_power=3[blurred_{idx}]"
            )
            filter_complex_parts.append(
                f"[orig_{idx}][blurred_{idx}]overlay=W*{_left:.4f}:H*{y:.4f}{_en_expr}[{next_label}]"
            )
            curr_label = next_label
            _log(f"🌫 Vùng che {idx+1}: từ {y*100:.0f}% → {(y+h)*100:.0f}%, rộng {w*100:.0f}%")

        # Frame side/top/bottom panels need real pixel blur before ASS draws the
        # semi-transparent dark overlays. Otherwise they only dim the video.
        frame_blur_specs = []
        if _frame_has_elements and _frame_blur_opacity > 0.001:
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

        # Finally, apply ASS subtitle filter
        filter_complex_parts.append(f"[{curr_label}]ass='{ass_esc}'[subbed]")
        filter_complex = ";".join(filter_complex_parts)

        # Add logo overlay if available
        if _logo_file and _logo_file.exists():
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
                _tbh_match = re.search(r"^; Title bar height:\s*([\d.]+)%", _ass_content, re.MULTILINE)
                if _tbh_match:
                    _title_bar_h_from_ass = int(_vid_h * float(_tbh_match.group(1)) / 100)
            except Exception:
                pass
            logo_x_px = max(0, int(_vid_w * _logo_left_pct / 100))
            logo_y_px = max(0, int(_vid_h * _logo_top_pct / 100) + _title_bar_h_from_ass)

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
                f"[subbed][logo]overlay={logo_x_px}:{logo_y_px}[vout]"
            )
            _log(f"🏷 Logo: {_logo_file.name} (h={logo_h_px}px, x={logo_x_px}, y={logo_y_px}, radius={r_pct}%)")
        else:
            filter_complex += ";[subbed]null[vout]"

        map_label = "[vout]"
        _log(f"🎬 Pipeline: {'blur + ' if blur_original else ''}burn ASS{' + logo' if _logo_file else ''}")

        # ── Encode ────────────────────────────────────────────────────────────
        _enc_args = _get_encoding_args(ffmpeg)
        _log(f"🎬 Bắt đầu encode ({' '.join(_enc_args[:4])})...")
        t_encode = _time.time()

        ok, err = run_ffmpeg([
            ffmpeg, "-i", str(tmp_video),
        ] + extra_inputs + [
            "-filter_complex", filter_complex,
            "-map", map_label, "-map", "0:a?",
        ] + _enc_args + [
            str(tmp_out), "-y", "-loglevel", "error"
        ])

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
    blur_extra_zones: Optional[list] = None,
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

        if blur_original and blur_zone != "none":
            # Two-pass approach: first blur the zone, then burn subtitles
            # Step A: blur zone → intermediate file
            tmp_blurred = Path(tmpdir) / "blurred.mp4"

            # Gather all active blur zones
            active_zones = []
            if blur_original and blur_zone != "none":
                h_pct = _clamp_float(blur_height_pct, 0.08, 0.45)
                w_pct = max(0.35, min(1.0, float(blur_width_pct)))
                if blur_y_pct is not None:
                    y_start = _clamp_float(blur_y_pct - h_pct / 2, 0.0, 1.0 - h_pct)
                else:
                    lift_pct = _clamp_float(blur_lift_pct, 0.0, 0.20)
                    if blur_zone == "bottom":
                        y_start = max(0.0, 1.0 - h_pct - lift_pct)
                    else:
                        y_start = 0.0
                active_zones.append((h_pct, w_pct, y_start, 0.5, None, None))
                
            if blur_original and blur_extra_zones:
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
                if _st is not None or _en is not None:
                    _s0 = float(_st) if _st is not None else 0.0
                    _e0 = float(_en) if _en is not None else 1e9
                    _en_expr = f":enable='between(t,{_s0:.3f},{_e0:.3f})'"
                filter_complex_parts.append(f"[{curr_label}]split[orig_{idx}][copy_{idx}]")
                filter_complex_parts.append(
                    f"[copy_{idx}]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{_left:.4f}:ih*{y:.4f},"
                    f"boxblur=luma_radius=20:luma_power=3[blurred_{idx}]"
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
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(tmp_blurred),
                "-vf", f"subtitles='{srt_esc}':force_style='{sub_style}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "copy",
                str(tmp_out), "-y", "-loglevel", "error"
            ])
        else:
            # No blur - just burn subtitles directly
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(tmp_video),
                "-vf", f"subtitles='{srt_esc}':force_style='{sub_style}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "copy",
                str(tmp_out), "-y", "-loglevel", "error"
            ])

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
    nine_router_cfg: dict | None = None,
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
    target_lang_name = _LANG_FULL.get(target_lang, "Vietnamese")

    if not translated_texts:
        return video_title[:30] if video_title else ""

    cfg = trans_cfg or {}
    nr = nine_router_cfg or {}
    # Pick the best available API key
    api_key = ""
    api_url = ""
    model = ""

    deepseek_key = cfg.get("deepseek_key", "")
    groq_key = cfg.get("groq_key", "")
    openai_key = cfg.get("openai_key", "")
    nine_key = (nr.get("api_key") or "").strip() if isinstance(nr, dict) else ""
    nine_endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/") if isinstance(nr, dict) else "http://localhost:20128/v1"
    nine_model = (nr.get("default_model") or "duytris").strip() if isinstance(nr, dict) else "duytris"

    if preferred_provider == "9router" and nine_key:
        api_key = nine_key
        api_url = f"{nine_endpoint}/chat/completions"
        model = nine_model
    elif preferred_provider == "deepseek" and deepseek_key:
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
    elif nine_key:
        # Last-resort fallback: use 9Router if it's the only thing available.
        api_key = nine_key
        api_url = f"{nine_endpoint}/chat/completions"
        model = nine_model

    if not api_key:
        # Fallback: use first 30 chars of first translated text
        for t in translated_texts:
            if t and t.strip():
                return t.strip()[:30]
        return video_title[:30] if video_title else ""

    # Build content summary from translated texts
    content_sample = " ".join(t for t in translated_texts[:10] if t).strip()
    if len(content_sample) > 500:
        content_sample = content_sample[:500]

    prompt = (
        f"Video title: {video_title or '(unknown)'}\n"
        f"Content ({target_lang_name} subtitles): {content_sample}\n\n"
        f"Create ONE short, catchy title in {target_lang_name} for this video.\n"
        "Requirements:\n"
        "- Maximum 30-40 characters\n"
        "- Curiosity-inducing, click-worthy\n"
        "- Keep specific numbers if present\n"
        "- Use | to mark the EMPHASIS part (will be highlighted in yellow)\n"
        "  Example: 'Fire ants vs|vacuum sealed powder!'\n"
        "  The part after | is the shocking/curious part\n"
        "- Return ONLY the title, no explanation\n\n"
        "Title:"
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
            data = json.loads(response.read())
        title = data["choices"][0]["message"]["content"].strip()
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
        return video_title[:35] if video_title else ""


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
    max_words_per_line: int = 5,
    # Frame: Title bar (overlay on top of video)
    title_text: str = "",
    title_size_pct: float = 7.0,
    title_color: str = "#000000",
    title_color_2: str = "#ff0000",  # Second color for emphasis part of title
    title_split_color: bool = True,  # Enable split-color (half/half)
    title_bar_color: str = "#ffffff",
    title_bar_h_pct: float = 12.0,  # height of title bar as % of PlayResY
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
    title_font_px = max(16, int(play_res_x * title_size_pct / 100))

    side_w = max(0, int(play_res_x * blur_w_pct / 100))

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
        f"-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},{alignment},10,10,{margin_v},1"
    )
    # Title bar background style (drawing)
    styles.append(
        f"Style: TitleBar,Arial,1,&H00{title_bar_bgr},&H00{title_bar_bgr},&H00{title_bar_bgr},&H00{title_bar_bgr},"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )
    # Title text style — BOLD, no outline (title bar has white background)
    styles.append(
        f"Style: TitleText,{font_name},{title_font_px},&H00{title_text_bgr},&H000000FF,&H00000000,&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,0,0,8,10,10,{title_bar_h // 4},1"
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

    # ── Build header ──────────────────────────────────────────────────────────
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
; Frame elements embedded: title bar + side blur panels (overlay on video)
; Title: {title_text}
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
        title_draw = f"m 0 0 l {play_res_x} 0 {play_res_x} {title_bar_h} 0 {title_bar_h}"
        lines.append(
            f"Dialogue: 3,{start_time},{end_time},TitleBar,,0,0,0,,{{\\pos(0,0)\\p1}}{title_draw}{{\\p0}}"
        )

    # 2. Title text (centered in title bar) — UPPERCASE, split color, no outline
    if has_title:
        # Position title at 35% of title bar height (higher up for better visual)
        title_y = int(title_bar_h * 0.35)
        # Uppercase the title for impact
        safe_title = title_text.replace("{", "").replace("}", "").replace("\\", "").upper()

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
                    f"{{\\an8\\pos({play_res_x // 2},{title_y})\\bord0}}"
                    f"{{\\c&H00{color1_bgr}&}}{part1} "
                    f"{{\\c&H00{color2_bgr}&}}{part2}"
                )
            else:
                colored_title = (
                    f"{{\\an8\\pos({play_res_x // 2},{title_y})\\bord0}}"
                    f"{{\\c&H00{color1_bgr}&}}{part1}"
                )
            lines.append(
                f"Dialogue: 4,{start_time},{end_time},TitleText,,0,0,0,,{colored_title}"
            )
        else:
            lines.append(
                f"Dialogue: 4,{start_time},{end_time},TitleText,,0,0,0,,"
                f"{{\\an8\\pos({play_res_x // 2},{title_y})\\bord0}}{safe_title}"
            )

    # 3. Left blur panel (semi-transparent, covers full video height including title bar area)
    if side_w > 0:
        left_draw = f"m 0 0 l {side_w} 0 {side_w} {play_res_y} 0 {play_res_y}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos(0,0)\\p1}}{left_draw}{{\\p0}}"
        )

        # 4. Right blur panel
        right_x = play_res_x - side_w
        right_draw = f"m 0 0 l {side_w} 0 {side_w} {play_res_y} 0 {play_res_y}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurRight,,0,0,0,,"
            f"{{\\pos({right_x},0)\\p1}}{right_draw}{{\\p0}}"
        )

    # 5. Top blur strip (full width)
    top_h = max(0, int(play_res_y * blur_top_pct / 100))
    if top_h > 0:
        top_draw = f"m 0 0 l {play_res_x} 0 {play_res_x} {top_h} 0 {top_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos(0,0)\\p1}}{top_draw}{{\\p0}}"
        )

    # 6. Bottom blur strip (full width)
    bottom_h = max(0, int(play_res_y * blur_bottom_pct / 100))
    if bottom_h > 0:
        bottom_y = play_res_y - bottom_h
        bottom_draw = f"m 0 0 l {play_res_x} 0 {play_res_x} {bottom_h} 0 {bottom_h}"
        lines.append(
            f"Dialogue: 1,{start_time},{end_time},BlurLeft,,0,0,0,,"
            f"{{\\pos(0,{bottom_y})\\p1}}{bottom_draw}{{\\p0}}"
        )

    # ── Subtitle dialogue lines (layer 2 — below title bar, above blur) ──────
    def _split_words(text, max_words=5):
        words = text.split()
        result = []
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i:i + max_words])
            if chunk:
                result.append(chunk)
        return result if result else [text]

    for seg in segments:
        text = seg.get("text", "").replace("\n", " ").strip()
        if not text:
            continue
        split_lines = _split_words(text, max_words=max_words_per_line)
        n = len(split_lines)
        seg_duration = (seg["end"] - seg["start"]) / n
        for i, line in enumerate(split_lines):
            sub_start = seg["start"] + i * seg_duration
            sub_end = seg["start"] + (i + 1) * seg_duration - 0.01
            s = _fmt_ass_time(sub_start)
            e = _fmt_ass_time(sub_end)
            lines.append(f"Dialogue: 2,{s},{e},Default,,0,0,0,,{line}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# TTS text chunker — tách text thành đoạn nhỏ theo dấu câu, language-aware
# ══════════════════════════════════════════════════════════════════════════════
def _split_text_for_tts(text: str, max_chars: int = 800) -> list[str]:
    """Split long text into TTS-friendly chunks at sentence boundaries.

    Handles Vietnamese, Chinese, Japanese and Latin punctuation.
    Strategy:
    1. Split at paragraph breaks.
    2. Within each paragraph, split at sentence terminators (. ! ? … 。！？).
    3. Greedily pack sentences into chunks ≤ max_chars.
    4. Hard-split any sentence that still exceeds max_chars.
    """
    text = (text or "").strip()
    if not text:
        return []

    # Regex: break after . ! ? … 。！？ or newline
    sent_re = re.compile(r"(?<=[.!?…。！？\n])\s+")
    raw_paragraphs = re.split(r"\n\s*\n", text)
    sentences: list[str] = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        for part in sent_re.split(para):
            part = part.strip()
            if part:
                sentences.append(part)

    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_chars:
            # flush current buffer first
            if cur:
                chunks.append(cur.strip())
                cur = ""
            # hard-split at max_chars
            for i in range(0, len(s), max_chars):
                chunks.append(s[i: i + max_chars].strip())
            continue
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= max_chars:
            cur = cur + " " + s
        else:
            chunks.append(cur.strip())
            cur = s
    if cur:
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def _max_tts_chars_for_engine(engine: str) -> int:
    """Return safe per-chunk character limit for each TTS engine."""
    engine = (engine or "").strip().lower()
    if engine == "fpt-ai":
        return 700
    if engine == "gtts":
        return 200
    if engine == "elevenlabs":
        return 2500
    if engine == "fish-audio":
        return 1500
    if engine == "9router" or engine.startswith("9r:"):
        return 1500
    # edge-tts, openai-tts, and others
    return 1500


# ══════════════════════════════════════════════════════════════════════════════
# MultiProviderTTS
# ══════════════════════════════════════════════════════════════════════════════
class MultiProviderTTS:
    """Multi-provider TTS: FPT AI, OpenAI, Edge-TTS, gTTS, ElevenLabs."""

    def __init__(
        self,
        voice: str = "banmai",
        engine: str = "fpt-ai",
        fpt_api_key: str = "",
        fpt_speed: int = 0,
        openai_api_key: str = "",
        openai_model: str = "tts-1",
        tts_lang: str = "vi",
        elevenlabs_api_key: str = "",
        elevenlabs_voice_id: str = "",
        elevenlabs_model: str = "eleven_multilingual_v2",
        fpt_fallback_elevenlabs: bool = True,
        fish_api_key: str = "",
        fish_model: str = "",
        fish_reference_id: str = "",
    ):
        self.voice = voice
        self.engine = engine
        self.fpt_api_key = (fpt_api_key or "").strip()
        self.fpt_speed = int(fpt_speed)
        self.openai_api_key = (openai_api_key or "").strip()
        self.openai_model = openai_model or "tts-1"
        self.tts_lang = tts_lang or "vi"
        self.elevenlabs_api_key = (elevenlabs_api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.elevenlabs_voice_id = (elevenlabs_voice_id or "").strip() or ELEVENLABS_DEFAULT_VOICE_ID
        self.elevenlabs_model = elevenlabs_model or "eleven_multilingual_v2"
        self.fish_api_key = (
            (fish_api_key or "").strip()
            or os.getenv("FISH_API_KEY", "").strip()
            or os.getenv("FISH_AUDIO_API_KEY", "").strip()
        )
        self.fish_model = (fish_model or "").strip() or FISH_DEFAULT_MODEL
        self.fish_reference_id = (fish_reference_id or "").strip()
        # Tự động fallback FPT → ElevenLabs khi FPT hết token/quota
        self.fpt_fallback_elevenlabs = fpt_fallback_elevenlabs and bool(self.elevenlabs_api_key)

    async def _generate_single(self, text: str, out_path: Path, engine: str) -> bool:
        """Generate TTS for a single text chunk (no splitting). Internal use only."""
        if engine == "fpt-ai":
            try:
                ok = await _tts_fpt_ai(text, self.voice, out_path, self.fpt_api_key, self.fpt_speed)
                if ok:
                    return True
            except Exception as fpt_err:
                # FPT hết token hoặc lỗi → fallback sang ElevenLabs nếu có key
                if self.fpt_fallback_elevenlabs:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "FPT TTS thất bại (%s), chuyển sang ElevenLabs voice_id=%s",
                        fpt_err, self.elevenlabs_voice_id,
                    )
                    try:
                        ok = await _tts_elevenlabs(
                            text, self.elevenlabs_voice_id, out_path,
                            api_key=self.elevenlabs_api_key,
                            model_id=self.elevenlabs_model,
                        )
                        if ok:
                            return True
                    except Exception:
                        pass

        elif engine == "elevenlabs":
            try:
                selected_voice = (self.voice or "").strip()
                voice_id = selected_voice if selected_voice and selected_voice not in {
                    "banmai", "thuminh", "myan", "leminh", "linhsan", "giahuy", "lannhi"
                } else self.elevenlabs_voice_id
                ok = await _tts_elevenlabs(
                    text, voice_id, out_path,
                    api_key=self.elevenlabs_api_key,
                    model_id=self.elevenlabs_model,
                )
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "fish-audio":
            try:
                ref_id = (self.voice or "").strip() or self.fish_reference_id
                ok = await _tts_fish(
                    text, ref_id, out_path,
                    api_key=self.fish_api_key,
                    model=self.fish_model,
                )
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "9router" or engine.startswith("9r:"):
            try:
                ok = await _tts_nine_router(
                    text, self.voice, out_path,
                    engine=engine,
                    language=self.tts_lang,
                )
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "minimax":
            try:
                ok = await _tts_minimax(text, self.voice, out_path, language=self.tts_lang)
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "openai-tts":
            try:
                ok = await _tts_openai(text, self.voice, out_path, self.openai_api_key, self.openai_model)
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "edge-tts":
            try:
                ok = await _tts_edge(text, self.voice, out_path)
                if ok:
                    return True
            except Exception:
                pass

        elif engine == "gtts":
            try:
                ok = _tts_gtts(text, self.tts_lang, out_path)
                if ok:
                    return True
            except Exception:
                pass

        return False

    async def generate(self, text: str, out_path: Path) -> bool:
        """Generate TTS audio. Splits long text into sentence-boundary chunks,
        generates each chunk separately, then concatenates with ffmpeg.
        Returns False if all providers fail."""
        out_path = Path(out_path)
        engine = str(self.engine).strip().lower()

        # Tách text thành các đoạn nhỏ theo dấu câu (language-aware)
        max_chars = _max_tts_chars_for_engine(engine)
        chunks = _split_text_for_tts(text, max_chars=max_chars)
        if not chunks:
            return False

        # Nếu chỉ 1 chunk, không cần concat
        if len(chunks) == 1:
            return await self._generate_single(chunks[0], out_path, engine)

        # Nhiều chunk → tạo từng file tạm, concat lại bằng ffmpeg
        import tempfile as _tmp
        with _tmp.TemporaryDirectory(prefix="tts_chunks_") as _td:
            chunk_paths: list[Path] = []
            tmp_dir = Path(_td)
            for idx, chunk in enumerate(chunks):
                chunk_path = tmp_dir / f"chunk_{idx:04d}.mp3"
                ok = await self._generate_single(chunk, chunk_path, engine)
                if not ok or not chunk_path.exists() or chunk_path.stat().st_size == 0:
                    return False  # fail fast — partial audio would desync
                chunk_paths.append(chunk_path)

            if len(chunk_paths) == 1:
                import shutil as _sh
                _sh.copy2(str(chunk_paths[0]), str(out_path))
                return out_path.exists() and out_path.stat().st_size > 0

            # Dùng ffmpeg concat demuxer để nối các chunk lại
            list_file = tmp_dir / "concat.txt"
            list_file.write_text(
                "\n".join(f"file '{p}'" for p in chunk_paths),
                encoding="utf-8",
            )
            ffmpeg_bin = find_ffmpeg()
            ok, _ = run_ffmpeg([
                ffmpeg_bin, "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                str(out_path), "-y", "-loglevel", "error",
            ], "concat_tts_chunks")
            return ok and out_path.exists() and out_path.stat().st_size > 0

    async def generate_all(
        self,
        segments: list[dict],
        translations: list[str],
        tmpdir: Path,
        max_concurrency: int = 2,
        retries: int = 2,
        tts_speed: float = 1.0,
        auto_speed: bool = True,
        ffmpeg: str = "ffmpeg",
        pitch_semitones: float = 0.0,
    ) -> list[dict]:
        """
        Generate TTS for all segments with bounded concurrency.
        Returns list of {"path": Path, "start": float, "end": float}
        only for successfully generated segments.
        """
        tmpdir = Path(tmpdir)
        sem = asyncio.Semaphore(max(1, int(max_concurrency)))

        async def _gen_one(i: int, seg: dict, text: str):
            if not text or not text.strip():
                return None
            out_path = tmpdir / f"tts_{i:04d}.mp3"
            async with sem:
                for _attempt in range(max(1, int(retries) + 1)):
                    ok = await self.generate(text.strip(), out_path)
                    if ok:
                        # Auto-speed: fit TTS duration to segment duration
                        speed = float(tts_speed) if tts_speed else 1.0
                        if auto_speed:
                            seg_dur = float(seg["end"]) - float(seg["start"])
                            tts_dur = _get_audio_duration(ffmpeg, out_path)
                            if tts_dur > 0 and seg_dur > 0:
                                auto = tts_dur / seg_dur
                                auto = max(1.0, min(3.0, auto))
                                speed = max(1.0, min(3.0, auto * speed))
                        if abs(speed - 1.0) > 0.05:
                            sped_path = tmpdir / f"tts_{i:04d}_fast.mp3"
                            _apply_atempo(ffmpeg, out_path, sped_path, speed)
                            if sped_path.exists() and sped_path.stat().st_size > 0:
                                out_path = sped_path
                        # Apply pitch shift - giữ nguyên tốc độ
                        if abs(pitch_semitones) > 0.05:
                            pitched_path = tmpdir / f"tts_{i:04d}_pitched.mp3"
                            wav_in = tmpdir / f"tts_{i:04d}_in.wav"
                            wav_out = tmpdir / f"tts_{i:04d}_out.wav"
                            import subprocess as _sp
                            _sp.run([ffmpeg, "-i", str(out_path), "-ar", "44100", "-ac", "1",
                                str(wav_in), "-y", "-loglevel", "error"], capture_output=True)
                            if wav_in.exists():
                                # Thử rubberband trước
                                r = _sp.run([ffmpeg, "-i", str(wav_in),
                                    "-filter:a", f"rubberband=pitch={2**(pitch_semitones/12):.6f}",
                                    str(wav_out), "-y", "-loglevel", "error"], capture_output=True)
                                if not (wav_out.exists() and wav_out.stat().st_size > 0):
                                    # Fallback: asetrate + atempo
                                    factor = 2 ** (pitch_semitones / 12)
                                    new_rate = int(44100 * factor)
                                    tempo = 1.0 / factor
                                    tempo_filters = []
                                    t = tempo
                                    while t < 0.5:
                                        tempo_filters.append("atempo=0.5"); t *= 2.0
                                    while t > 2.0:
                                        tempo_filters.append("atempo=2.0"); t /= 2.0
                                    tempo_filters.append(f"atempo={t:.6f}")
                                    f = f"asetrate={new_rate}," + ",".join(tempo_filters) + ",aresample=44100"
                                    _sp.run([ffmpeg, "-i", str(wav_in), "-filter:a", f,
                                        str(wav_out), "-y", "-loglevel", "error"], capture_output=True)
                                if wav_out.exists() and wav_out.stat().st_size > 0:
                                    _sp.run([ffmpeg, "-i", str(wav_out), "-q:a", "2",
                                        str(pitched_path), "-y", "-loglevel", "error"], capture_output=True)
                                    if pitched_path.exists() and pitched_path.stat().st_size > 0:
                                        out_path = pitched_path
                        return {"path": out_path, "start": seg["start"], "end": seg["end"]}
                    await asyncio.sleep(0.25 * (_attempt + 1))
            return None

        tasks = [
            _gen_one(i, seg, text)
            for i, (seg, text) in enumerate(zip(segments, translations))
        ]
        results = await asyncio.gather(*tasks)
        clips = [r for r in results if r is not None]
        clips.sort(key=lambda c: float(c.get("start", 0.0)))
        return clips


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Voice conversion ZH → VI
# ══════════════════════════════════════════════════════════════════════════════
def _get_audio_duration(ffmpeg: str, path: Path) -> float:
    """Return duration of an audio file in seconds."""
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True
        )
        for line in r.stderr.splitlines():
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _apply_atempo(ffmpeg: str, src: Path, dst: Path, speed: float) -> bool:
    """Speed up/slow down audio using ffmpeg atempo (chains if >2x or <0.5x)."""
    # atempo supports 0.5–2.0, chain for values outside range
    filters = []
    s = speed
    while s > 2.0:
        filters.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        filters.append("atempo=0.5")
        s /= 0.5
    filters.append(f"atempo={s:.4f}")
    filter_str = ",".join(filters)
    ok, _ = run_ffmpeg([
        ffmpeg, "-i", str(src),
        "-filter:a", filter_str,
        str(dst), "-y", "-loglevel", "error"
    ], "atempo")
    return ok


async def _tts_edge(text: str, voice: str, out_path: Path, rate: str = "+0%",
                    pitch: str = "+0Hz", style: str = "default") -> bool:
    """Generate TTS audio using edge-tts.

    `pitch` accepts a string like "+0Hz", "-2Hz", "+2Hz" and is passed through
    to edge-tts. `style` is accepted for compatibility but not all voices
    support SSML express-as styles via edge-tts; if the underlying call fails
    with the style we silently retry without it.
    """
    # Map FPT AI voices → edge-tts Vietnamese voices
    _VOICE_MAP = {
        "banmai": "vi-VN-HoaiMyNeural",
        "leminh": "vi-VN-NamMinhNeural",
        "thuminh": "vi-VN-HoaiMyNeural",
        "giahuy": "vi-VN-NamMinhNeural",
        "myan": "vi-VN-HoaiMyNeural",
        "lannhi": "vi-VN-HoaiMyNeural",
        "lianh": "vi-VN-HoaiMyNeural",
    }
    # Auto-fix voice name if it's an FPT voice or doesn't look like edge-tts format
    if voice and "-" not in voice and "Neural" not in voice:
        voice = _VOICE_MAP.get(voice.lower(), "vi-VN-HoaiMyNeural")

    try:
        import edge_tts
        kwargs = {"rate": rate}
        if pitch and pitch.strip() and pitch.strip().lower() not in ("+0hz", "0hz", "default"):
            kwargs["pitch"] = pitch

        # Retry up to 2 times on "No audio was received" errors
        last_err = None
        for _retry in range(3):
            try:
                communicate = edge_tts.Communicate(text, voice, **kwargs)
                await communicate.save(str(out_path))
                if out_path.exists() and out_path.stat().st_size > 0:
                    return True
            except TypeError:
                # Older edge-tts that doesn't support `pitch`
                communicate = edge_tts.Communicate(text, voice, rate=rate)
                await communicate.save(str(out_path))
                if out_path.exists() and out_path.stat().st_size > 0:
                    return True
            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                if "no audio was received" in err_msg:
                    # Retry after short delay — edge-tts sometimes has transient failures
                    await asyncio.sleep(1.0 * (_retry + 1))
                    continue
                else:
                    raise RuntimeError(f"edge-tts failed: {e}")

        # All retries exhausted
        if last_err:
            raise RuntimeError(f"edge-tts failed after 3 attempts: {last_err}")
        return False
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"edge-tts failed: {e}")


async def _tts_fpt_ai(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    speed: int = 0,
) -> bool:
    """Generate TTS audio using FPT AI TTS v5 (Vietnamese voices)."""
    import aiohttp

    key = (api_key or "").strip() or os.getenv("FPT_AI_API_KEY", "").strip() or FPT_TTS_DEFAULT_KEY
    if not key:
        raise RuntimeError("Missing FPT AI API key")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = str(text or "").strip()
    if not payload:
        return False

    # FPT commonly uses lowercase voice keys like banmai, leminh, myan...
    fpt_voice = str(voice or "banmai").strip().lower()
    headers = {
        "api-key": key,
        "voice": fpt_voice,
        "speed": str(int(speed)),
        "format": "mp3",
    }

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(FPT_TTS_ENDPOINT, data=payload.encode("utf-8"), headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FPT TTS request failed: status={resp.status}, body={await resp.text()}")
            data = await resp.json(content_type=None)

        audio_url = str((data or {}).get("async") or (data or {}).get("url") or "").strip()
        if not audio_url:
            raise RuntimeError(f"FPT TTS missing async URL: {data}")

        # Poll async URL until audio is ready (up to ~60s for long text).
        for attempt in range(24):
            await asyncio.sleep(0.5)
            async with session.get(audio_url) as aresp:
                if aresp.status != 200:
                    continue
                ctype = str(aresp.headers.get("Content-Type") or "").lower()
                blob = await aresp.read()
                # When not ready yet, some gateways may return JSON/text instead of audio.
                if "audio" not in ctype and blob[:1] in (b"{", b"["):
                    continue
                if blob:
                    out_path.write_bytes(blob)
                    return out_path.exists() and out_path.stat().st_size > 0

    return False


async def _tts_openai(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    model: str = "tts-1",
) -> bool:
    """Generate TTS using OpenAI TTS API."""
    import aiohttp

    key = (api_key or "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing OpenAI API key (set OPENAI_API_KEY or config)")

    out_path = Path(out_path)
    if not text or not text.strip():
        return False

    valid_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    oai_voice = str(voice or "nova").strip().lower()
    if oai_voice not in valid_voices:
        oai_voice = "nova"

    payload = {"model": model or "tts-1", "input": text.strip(), "voice": oai_voice}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.openai.com/v1/audio/speech",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OpenAI TTS error {resp.status}: {await resp.text()}")
            audio_bytes = await resp.read()
            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


def _nine_router_cfg_for_tts() -> tuple[str, str, dict]:
    cfg = {}
    try:
        from core_app import load_cfg as _load_cfg
        cfg = _load_cfg() or {}
    except Exception:
        cfg = {}
    nr = cfg.get("nine_router") or {}
    endpoint = (
        os.getenv("NINEROUTER_URL")
        or nr.get("endpoint")
        or "http://localhost:20128/v1"
    )
    endpoint = str(endpoint).strip().rstrip("/")
    if not endpoint.endswith("/v1") and not re.search(r"/v1(/|$)", endpoint):
        endpoint += "/v1"
    api_key = str(os.getenv("NINEROUTER_KEY") or nr.get("api_key") or "").strip()
    return endpoint, api_key, cfg


def _nine_router_model_for_engine(engine: str, voice: str, cfg: dict) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (model, voice_param, fallback_candidates) for 9Router TTS."""
    eng = (engine or "9router").strip().lower()
    selected = (voice or "").strip()
    fallbacks: list[tuple[str, str]] = []

    if "|" in selected:
        model, voice_param = selected.split("|", 1)
        return model.strip(), voice_param.strip(), fallbacks

    default_model = ""
    provider = ""
    try:
        from core.tts_catalog import nine_router_tts_engines
        engines, _ = nine_router_tts_engines(cfg)
        found = next((e for e in engines if str(e.get("id") or "").lower() == eng), None)
        if found:
            default_model = str(found.get("defaultModel") or "").strip()
            provider = str(found.get("provider") or "").strip().lower()
    except Exception:
        pass

    if selected and "/" in selected and eng not in ("9r:openai", "9r:gemini"):
        return selected, "", fallbacks

    if eng in ("9r:openai", "9router-openai"):
        return default_model or "openai/tts-1", selected or "nova", fallbacks

    if eng in ("9r:gemini", "9router-gemini"):
        return default_model or "gemini/gemini-2.5-flash-preview-tts", selected or "Kore", fallbacks

    if eng in ("9r:elevenlabs", "9r:el", "9router-elevenlabs") or provider == "elevenlabs":
        if selected:
            if default_model:
                fallbacks.append((default_model, selected))
            return f"el/{selected}", "", fallbacks
        return default_model or "el/eleven_multilingual_v2", "", fallbacks

    if eng in ("9r:edge-tts", "9router", "9r", "9router-edge") or provider == "edge-tts":
        if selected:
            if selected.startswith("edge-tts/"):
                return selected, "", fallbacks
            fallbacks.append((selected, ""))
            return f"edge-tts/{selected}", "", fallbacks
        return default_model or "edge-tts/vi-VN-HoaiMyNeural", "", fallbacks

    if eng in ("9r:google-tts", "9router-google") or provider == "google-tts":
        return selected or default_model or "vi", "", fallbacks

    if eng in ("minimax", "9r:minimax", "9router-minimax") or provider == "minimax":
        return default_model or "minimax/speech-02-hd", selected or "English_expressive_narrator", fallbacks

    if selected:
        return selected, "", fallbacks
    return default_model or "openai/tts-1", "", fallbacks


async def _tts_nine_router(
    text: str,
    voice: str,
    out_path: Path,
    engine: str = "9router",
    api_key: str = "",
    endpoint: str = "",
    response_format: str = "mp3",
    language: str = "",
) -> bool:
    """Generate TTS through 9Router /v1/audio/speech."""
    import aiohttp
    import urllib.parse as _urlparse

    payload_text = str(text or "").strip()
    if not payload_text:
        return False

    cfg_endpoint, cfg_key, cfg = _nine_router_cfg_for_tts()
    endpoint = (endpoint or cfg_endpoint).strip().rstrip("/")
    api_key = (api_key or cfg_key).strip()
    if not endpoint.endswith("/v1") and not re.search(r"/v1(/|$)", endpoint):
        endpoint += "/v1"

    model, voice_param, fallbacks = _nine_router_model_for_engine(engine, voice, cfg)
    candidates = [(model, voice_param)] + fallbacks
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {"Content-Type": "application/json", "Accept": "audio/mpeg"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    fmt = (response_format or "mp3").strip().lower()
    url = f"{endpoint}/audio/speech?{_urlparse.urlencode({'response_format': fmt})}"
    timeout = aiohttp.ClientTimeout(total=120)
    last_error = ""
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for cand_model, cand_voice in candidates:
            payload = {"model": cand_model, "input": payload_text}
            if cand_voice:
                payload["voice"] = cand_voice
            if language:
                payload["language"] = str(language)
            async with session.post(url, json=payload, headers=headers) as resp:
                blob = await resp.read()
                if resp.status < 400 and blob and len(blob) > 100:
                    out_path.write_bytes(blob)
                    return out_path.exists() and out_path.stat().st_size > 0
                body = blob.decode("utf-8", "replace")[:300] if blob else ""
                last_error = f"9Router TTS error {resp.status}: {body}"
    raise RuntimeError(last_error or "9Router TTS returned empty audio")


async def _tts_minimax(text: str, voice: str, out_path: Path, language: str = "") -> bool:
    """Generate MiniMax TTS through 9Router when a MiniMax TTS model is configured."""
    return await _tts_nine_router(
        text,
        voice or "English_expressive_narrator",
        out_path,
        engine="minimax",
        language=language,
    )


def _tts_gtts(text: str, lang: str, out_path: Path) -> bool:
    """Fallback TTS using gTTS."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(out_path))
        return out_path.exists()
    except Exception as e:
        raise RuntimeError(f"gTTS failed: {e}")


async def _tts_elevenlabs(
    text: str,
    voice_id: str,
    out_path: Path,
    api_key: str = "",
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bool:
    """Generate TTS using ElevenLabs API.

    Docs: https://elevenlabs.io/docs/eleven-api/guides/cookbooks/text-to-speech

    Args:
        text: Text to synthesize.
        voice_id: ElevenLabs voice ID (e.g. "21m00Tcm4TlvDq8ikWAM" for Rachel).
        out_path: Output MP3 file path.
        api_key: ElevenLabs API key. Falls back to env ELEVENLABS_API_KEY.
        model_id: Model to use — "eleven_multilingual_v2" supports Vietnamese.
        stability: Voice stability (0.0-1.0).
        similarity_boost: Voice similarity (0.0-1.0).
    """
    import aiohttp

    key = (api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ElevenLabs API key (set ELEVENLABS_API_KEY or config)")

    vid = (voice_id or ELEVENLABS_DEFAULT_VOICE_ID).strip()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload_text = str(text or "").strip()
    if not payload_text:
        return False

    url = ELEVENLABS_TTS_ENDPOINT.format(voice_id=vid)
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": payload_text,
        "model_id": model_id or "eleven_multilingual_v2",
        "voice_settings": {
            "stability": float(stability),
            "similarity_boost": float(similarity_boost),
        },
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401:
                raise RuntimeError("ElevenLabs API key không hợp lệ (401 Unauthorized)")
            if resp.status == 422:
                body = await resp.text()
                raise RuntimeError(f"ElevenLabs request không hợp lệ (422): {body}")
            if resp.status == 429:
                raise RuntimeError("ElevenLabs hết quota / rate limit (429)")
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"ElevenLabs TTS lỗi {resp.status}: {body[:200]}")

            audio_bytes = await resp.read()
            if not audio_bytes or len(audio_bytes) < 100:
                raise RuntimeError("ElevenLabs trả về audio rỗng")

            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


async def _tts_fish(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    model: str = "",
    speed: float = 1.0,
) -> bool:
    """Generate TTS using Fish Audio.

    Docs: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech

    Fish Audio's s1 / s2-pro backbones are multilingual and handle the
    phonetics of languages like Japanese, Chinese and Korean very well. The
    target language is auto-detected from the text — no language code needed.

    Args:
        text: Text to synthesize (any supported language).
        voice: Fish Audio voice model ID (``reference_id``). Leave empty to use
            the backbone's built-in default voice.
        out_path: Output MP3 file path.
        api_key: Fish Audio API key. Falls back to env FISH_API_KEY /
            FISH_AUDIO_API_KEY.
        model: Backbone model — "s2-pro" (default) or "s1".
        speed: Speaking rate multiplier (0.5–2.0).
    """
    import aiohttp

    key = (
        (api_key or "").strip()
        or os.getenv("FISH_API_KEY", "").strip()
        or os.getenv("FISH_AUDIO_API_KEY", "").strip()
    )
    if not key:
        raise RuntimeError(
            "Missing Fish Audio API key (set FISH_API_KEY or config video_process.fish_api_key)"
        )

    payload_text = str(text or "").strip()
    if not payload_text:
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backbone = (model or "").strip().lower() or FISH_DEFAULT_MODEL
    if backbone not in ("s1", "s2-pro"):
        backbone = FISH_DEFAULT_MODEL

    payload: dict = {
        "text": payload_text,
        "format": "mp3",
        "mp3_bitrate": 128,
        "normalize": True,
        "latency": "normal",
    }
    ref = (voice or "").strip()
    if ref:
        payload["reference_id"] = ref
    try:
        spd = float(speed)
    except (TypeError, ValueError):
        spd = 1.0
    if abs(spd - 1.0) > 0.01:
        payload["prosody"] = {"speed": max(0.5, min(2.0, spd))}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "model": backbone,
    }

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(FISH_TTS_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status == 401:
                raise RuntimeError("Fish Audio API key không hợp lệ (401 Unauthorized)")
            if resp.status == 402:
                raise RuntimeError("Fish Audio hết credit / cần nạp tiền (402 Payment Required)")
            if resp.status == 422:
                body = await resp.text()
                raise RuntimeError(f"Fish Audio request không hợp lệ (422): {body[:200]}")
            if resp.status == 429:
                raise RuntimeError("Fish Audio rate limit (429)")
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Fish Audio TTS lỗi {resp.status}: {body[:200]}")

            audio_bytes = await resp.read()
            if not audio_bytes or len(audio_bytes) < 100:
                raise RuntimeError("Fish Audio trả về audio rỗng")

            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


async def convert_voice(
    video_path: Path,
    segments: list[dict],          # [{start, end, text}] in ZH
    translated_texts: list[str],   # VI translations (same order as segments)
    output_path: Path,
    ffmpeg: str,
    tts_voice: str = "vi-VN-HoaiMyNeural",  # edge-tts voice
    tts_engine: str = "edge-tts",   # "edge-tts" | "gtts" | "fpt-ai" | "elevenlabs"
    keep_bg_music: bool = True,
    bg_volume: float = 0.15,        # background original audio volume
    tts_speed: float = 1.0,         # manual speed multiplier (1.0 = auto-fit)
    auto_speed: bool = True,        # auto-fit TTS duration to segment duration
    fpt_api_key: str = "",          # FPT AI key (nếu engine=fpt-ai)
    fpt_speed: int = 0,
    elevenlabs_api_key: str = "",   # ElevenLabs key
    elevenlabs_voice_id: str = "",  # ElevenLabs voice ID
) -> tuple[bool, str]:
    """
    Replace original audio with TTS voice.
    Each segment gets its own TTS clip, placed at the correct timestamp.
    Background music from original is optionally kept at low volume.
    Supports: edge-tts, gtts, fpt-ai, elevenlabs, openai-tts, minimax.
    FPT AI tự động fallback sang ElevenLabs khi hết token.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not segments or not translated_texts:
        return False, "No segments to process"

    # Resolve ElevenLabs key/voice from env nếu không truyền vào
    el_key = (elevenlabs_api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
    el_voice = (elevenlabs_voice_id or "").strip() or ELEVENLABS_DEFAULT_VOICE_ID

    with tempfile.TemporaryDirectory(prefix="voice_") as tmpdir:
        tmpdir = Path(tmpdir)

        # copy video to temp
        tmp_video = tmpdir / "input.mp4"
        shutil.copy2(str(video_path), str(tmp_video))

        # get video duration
        dur_result2 = subprocess.run(
            [ffmpeg, "-i", str(tmp_video), "-f", "null", "-"],
            capture_output=True, text=True
        )
        video_duration = 0.0
        for line in dur_result2.stderr.splitlines():
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                video_duration = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                break

        if video_duration <= 0:
            video_duration = segments[-1]['end'] + 2.0 if segments else 60.0

        # Build MultiProviderTTS để xử lý tất cả engines + fallback
        tts_provider = MultiProviderTTS(
            voice=tts_voice,
            engine=tts_engine,
            fpt_api_key=fpt_api_key,
            fpt_speed=fpt_speed,
            tts_lang="vi",
            elevenlabs_api_key=el_key,
            elevenlabs_voice_id=el_voice,
            fpt_fallback_elevenlabs=bool(el_key),
        )

        # Generate TTS for each segment
        tts_clips = []
        for i, (seg, vi_text) in enumerate(zip(segments, translated_texts)):
            if not vi_text or not vi_text.strip():
                continue
            clip_path = tmpdir / f"tts_{i:04d}.mp3"
            try:
                ok = await tts_provider.generate(vi_text.strip(), clip_path)
                if ok:
                    seg_dur = seg["end"] - seg["start"]
                    # Get TTS clip duration
                    tts_dur = _get_audio_duration(ffmpeg, clip_path)
                    # Compute speed: auto-fit or manual
                    speed = tts_speed
                    if auto_speed and tts_dur > 0 and seg_dur > 0:
                        auto = tts_dur / seg_dur  # how much faster needed
                        # clamp between 0.5x and 3.0x
                        auto = max(0.5, min(3.0, auto))
                        speed = auto * tts_speed
                        speed = max(0.5, min(3.0, speed))
                    # Apply speed with atempo if needed
                    if abs(speed - 1.0) > 0.05:
                        sped_path = tmpdir / f"tts_{i:04d}_fast.mp3"
                        _apply_atempo(ffmpeg, clip_path, sped_path, speed)
                        if sped_path.exists():
                            clip_path = sped_path
                    tts_clips.append({
                        "path": clip_path,
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": vi_text,
                    })
            except Exception:
                pass  # skip failed clips

        if not tts_clips:
            return False, "No TTS clips generated"

        # Build silent base audio track (same duration as video)
        silent_path = tmpdir / "silent.wav"
        run_ffmpeg([
            ffmpeg, "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(video_duration),
            str(silent_path), "-y", "-loglevel", "error"
        ])

        # Mix all TTS clips into a single audio track using amix/adelay
        # Build complex filter: each clip delayed to its start time
        inputs = ["-i", str(silent_path)]
        filter_parts = []
        mix_inputs = ["[0:a]"]

        for j, clip in enumerate(tts_clips):
            inputs += ["-i", str(clip["path"])]
            delay_ms = int(clip["start"] * 1000)
            filter_parts.append(
                f"[{j+1}:a]adelay={delay_ms}|{delay_ms}[d{j}]"
            )
            mix_inputs.append(f"[d{j}]")

        n_mix = len(mix_inputs)
        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={n_mix}:duration=first:dropout_transition=0[tts_mix]"
        )

        if keep_bg_music:
            # extract original audio at low volume
            orig_audio = tmpdir / "orig_audio.wav"
            run_ffmpeg([
                ffmpeg, "-i", str(tmp_video),
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                str(orig_audio), "-y", "-loglevel", "error"
            ])
            if orig_audio.exists():
                inputs += ["-i", str(orig_audio)]
                bg_idx = len(tts_clips) + 1
                filter_parts.append(
                    f"[{bg_idx}:a]volume={bg_volume}[bg];"
                    f"[tts_mix][bg]amix=inputs=2:duration=first[final_audio]"
                )
                final_audio_label = "[final_audio]"
            else:
                filter_parts[-1] = filter_parts[-1].replace("[tts_mix]", "[tts_mix]").replace(
                    "amix=inputs=" + str(n_mix), "amix=inputs=" + str(n_mix)
                )
                final_audio_label = "[tts_mix]"
        else:
            final_audio_label = "[tts_mix]"

        filter_complex = ";".join(filter_parts)

        # Combine: original video + new audio
        cmd = [ffmpeg] + inputs + [
            "-i", str(tmp_video),
            "-filter_complex", filter_complex,
            "-map", f"{len(inputs)-1}:v",  # video from last input (original)
            "-map", final_audio_label,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path), "-y", "-loglevel", "error"
        ]
        ok, err = run_ffmpeg(cmd, "voice mix")
        if not ok:
            return False, f"ffmpeg mix failed: {err}"

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# AudioMixer
# ══════════════════════════════════════════════════════════════════════════════
class AudioMixer:
    """Mix TTS audio clips into a video at correct timestamps using ffmpeg."""

    def __init__(self, ffmpeg: str):
        self.ffmpeg = ffmpeg

    def mix(
        self,
        video_path: Path,
        tts_clips: list[dict],
        output_path: Path,
        keep_bg_music: bool,
        bg_volume: float,
        tts_volume: float,
    ) -> tuple[bool, str]:
        """
        Mix TTS clips into video.

        Each clip dict must have: {"path": Path, "start": float, ...}
        delay_ms = int(clip["start"] * 1000)

        Returns (True, "") on success, (False, error_msg) on failure.
        """
        if not tts_clips:
            return False, "No TTS clips"

        video_path = Path(video_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="audiomix_") as tmpdir:
            tmpdir = Path(tmpdir)
            tmp_video = tmpdir / "input.mp4"
            shutil.copy2(str(video_path), str(tmp_video))

            video_duration = get_media_duration_seconds(self.ffmpeg, tmp_video)
            if video_duration <= 0:
                video_duration = max(float(c.get("start", 0.0)) for c in tts_clips) + 8.0

            # Create a silent base track so amix always has stable timeline from t=0.
            silent_path = tmpdir / "silent.wav"
            ok_silent, err_silent = run_ffmpeg([
                self.ffmpeg,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(video_duration),
                str(silent_path), "-y", "-loglevel", "error"
            ])
            if not ok_silent or not silent_path.exists():
                return False, f"failed to create silent base: {err_silent}"

            # Build inputs list and filter_complex
            inputs = ["-i", str(tmp_video), "-i", str(silent_path)]
            filter_parts = []
            mix_labels = []

            for j, clip in enumerate(tts_clips):
                inputs += ["-i", str(clip["path"])]
                delay_ms = int(clip["start"] * 1000)
                filter_parts.append(
                    f"[{j + 2}:a]adelay={delay_ms}|{delay_ms}[d{j}]"
                )
                mix_labels.append(f"[d{j}]")

            # Mix all delayed clips with a silent base of full video duration.
            n_mix = len(mix_labels) + 1
            filter_parts.append(
                f"[1:a]{''.join(mix_labels)}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0[tts_raw]"
            )
            # Boost dubbed voice so it is clearly above background/original sound.
            filter_parts.append(f"[tts_raw]volume={max(0.1, float(tts_volume)):.3f}[tts_mix]")

            if keep_bg_music:
                orig_audio = tmpdir / "orig_audio.wav"
                run_ffmpeg([
                    self.ffmpeg, "-i", str(tmp_video),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    str(orig_audio), "-y", "-loglevel", "error"
                ])
                if orig_audio.exists():
                    bg_idx = len(tts_clips) + 2
                    inputs += ["-i", str(orig_audio)]
                    filter_parts.append(
                        f"[{bg_idx}:a]volume={bg_volume}[bg];"
                        f"[tts_mix][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,aresample=async=1:first_pts=0[final_audio]"
                    )
                    final_label = "[final_audio]"
                else:
                    final_label = "[tts_mix]"
            else:
                final_label = "[tts_mix]"

            filter_complex = ";".join(filter_parts)

            cmd = [self.ffmpeg] + inputs + [
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", final_label,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                str(output_path), "-y", "-loglevel", "error"
            ]
            ok, err = run_ffmpeg(cmd, "audio mix")
            if not ok:
                return False, f"ffmpeg mix failed: {err}"

        return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline: process_video_full
# ══════════════════════════════════════════════════════════════════════════════
def process_video_full(data: dict) -> Generator[str, None, None]:
    """
    Full pipeline generator (yields NDJSON lines for streaming).
    data keys:
      video_path, model, language, out_dir,
      burn_subs, blur_original, blur_zone, blur_height_pct,
      font_size, font_color, margin_v,
      voice_convert, tts_voice, tts_engine, keep_bg_music, bg_volume,
      translate_provider (for ZH→VI translation)
    """
    import json as _j

    def send(**kw):
        return _j.dumps(kw, ensure_ascii=False) + "\n"

    video_path = Path(data.get("video_path", "")).expanduser()
    if not video_path.exists():
        yield send(log=f"File not found: {video_path}", level="error")
        return

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        yield send(log="ffmpeg not found. Install ffmpeg and add to PATH.", level="error")
        return

    # Detect actual video dimensions
    try:
        import subprocess, re
        _r = subprocess.run([ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        _m = re.search(r"(\d{2,5})x(\d{2,5})", _r.stderr or "")
        _vw, _vh = (int(_m.group(1)), int(_m.group(2))) if _m else (1280, 720)
    except Exception:
        _vw, _vh = 1280, 720

    # Output dir logic:
    # - User chỉ định out_dir → dùng nó
    # - Nếu video gốc đã nằm trong Downloaded/Process_video/<name>/ → giữ nguyên (resume)
    # - Ngược lại → tạo Downloaded/Process_video/<safe_stem>/
    _user_out_dir = str(data.get("out_dir") or "").strip()
    if _user_out_dir:
        out_dir = Path(_user_out_dir).expanduser()
    else:
        import yaml as _yaml_cfg
        _cfg_path = Path(__file__).parent.parent / "config.yml"
        _dl_path = ""
        if _cfg_path.exists():
            try:
                _dl_path = str((_yaml_cfg.safe_load(_cfg_path.read_text(encoding="utf-8")) or {}).get("path") or "").strip()
            except Exception:
                pass

        if _dl_path:
            _base = Path(_dl_path).expanduser()
            if not _base.is_absolute():
                _base = Path(__file__).parent.parent / _base
            _process_root = (_base / "Process_video").resolve()

            # Nếu video gốc đã nằm trong Process_video/<x>/ thì dùng chính folder đó
            try:
                _vp_resolved = video_path.resolve()
                if _process_root in _vp_resolved.parents:
                    out_dir = _vp_resolved.parent
                else:
                    # Tạo thư mục riêng cho video này (theo stem an toàn)
                    _safe_stem_for_dir = _safe_stem(video_path.stem) or "video"
                    out_dir = _process_root / _safe_stem_for_dir
            except Exception:
                _safe_stem_for_dir = _safe_stem(video_path.stem) or "video"
                out_dir = _process_root / _safe_stem_for_dir
        else:
            out_dir = video_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    video_title = str(data.get("video_title") or "").strip()
    stem_source = video_title or video_path.stem
    stem = _safe_stem(stem_source)

    do_burn = _as_bool(data.get("burn_subs", True), True)
    do_voice = _as_bool(data.get("voice_convert", False), False)
    cleanup_outputs = _as_bool(data.get("cleanup_outputs", True), True)
    delete_source_after = _as_bool(data.get("delete_source_after_process", False), False)
    # Default: always translate to VI and burn VI subtitles
    do_translate = _as_bool(data.get("translate_subs", True), True)
    do_burn_vi = _as_bool(data.get("burn_vi_subs", True), True)
    model_name = data.get("model", "base")
    language = data.get("language", "zh")
    target_language = str(data.get("target_language", "vi") or "vi").strip().lower()
    _LANG_NAMES = {
        "vi": "tiếng Việt", "en": "English", "ja": "日本語", "ko": "한국어",
        "th": "ภาษาไทย", "id": "Bahasa Indonesia", "es": "Español",
        "pt": "Português", "fr": "Français", "de": "Deutsch",
        "ru": "Русский", "ar": "العربية", "hi": "हिन्दी", "zh": "中文",
    }
    target_lang_name = _LANG_NAMES.get(target_language, target_language)
    process_mode = str(data.get("process_mode", "ai") or "ai").strip().lower()
    transcribe_provider = str(data.get("transcribe_provider", "") or "").strip().lower()
    if not transcribe_provider:
        transcribe_provider = "model" if process_mode == "model" else "groq"

    subtitle_pos = str(data.get("subtitle_position", "bottom")).lower()
    blur_zone = str(data.get("blur_zone", "bottom")).lower()
    blur_enabled = _as_bool(data.get("blur_original", True), True)
    blur_height_pct = _clamp_float(_as_float(data.get("blur_height_pct", 0.15), 0.15), 0.08, 0.45)
    blur_lift_pct = _clamp_float(_as_float(data.get("blur_lift_pct", 0.06), 0.06), 0.0, 0.20)

    user_margin_v = data.get("margin_v")
    effective_margin_v = _as_int(user_margin_v, 20) if user_margin_v is not None else 20
    # Only auto-calculate margin when user has NOT explicitly set it
    if subtitle_pos == "bottom" and user_margin_v is None:
        auto_margin = int(720 * (blur_height_pct * 0.5 + (blur_lift_pct if (blur_enabled and blur_zone == "bottom") else 0.0)))
        effective_margin_v = max(effective_margin_v, auto_margin)
        # When frame is enabled, PlayRes matches video (e.g. 1920 height) so margin needs to be bigger
        if _as_bool(data.get("frame_enabled", False), False):
            effective_margin_v = max(effective_margin_v, 60)
    # If user set margin_v, use it as-is (already converted from % to px in JS)

    vi_ass_path = None
    final_output_path = None

    # ── Bước 1/5: Xác nhận video đã tải ──────────────────────────────────────
    _vid_size_mb = video_path.stat().st_size / 1024 / 1024
    yield send(log=f"[Bước 1/5] 📥 Video đã sẵn sàng: {video_path.name} ({_vid_size_mb:.1f} MB)", level="success")
    yield send(log=f"[Bước 1/5] 📂 Thư mục output: {out_dir}", level="info")
    yield send(log=f"[Bước 1/5] ⚙️ Cấu hình: burn={do_burn}, voice={do_voice}, translate={do_translate}, frame={_as_bool(data.get('frame_enabled', False), False)} (embedded in ASS)", level="info")
    yield send(overall=5, overall_lbl="Video sẵn sàng")

    # ── Bước 2/5: Phiên âm (Transcribe) ──────────────────────────────────────
    # Check video audio first
    has_audio = has_audio_track(video_path, ffmpeg)
    if not has_audio:
        yield send(log=f"[Bước 2/5] ⚠ Video không có audio track", level="warning")
    
    if transcribe_provider == "model":
        yield send(log=f"[Bước 2/5] 🎙 Đang phiên âm bằng Whisper local ({model_name})...", level="info")
    else:
        yield send(log="[Bước 2/5] 🎙 Đang phiên âm bằng Groq Whisper API...", level="info")
    yield send(overall=10, overall_lbl="Đang phiên âm...")

    ass_path = out_dir / f"{stem}.ass"  # dùng ASS thay SRT
    source_srt_path = out_dir / f"{stem}.srt"  # transcriber output gốc
    srt_path = source_srt_path  # file dùng cho bước burn (có thể đổi sang vi_ass)
    segments = []
    transcribe_failed = False

    # ── Resume: kiểm tra file cache từ lần chạy trước ─────────────────────────
    vi_ass_path_cached   = out_dir / f"{stem}_{target_language}.ass"
    burned_path_cached   = out_dir / f"{stem}_subbed.mp4"
    voice_path_cached    = out_dir / f"{stem}_{target_language}_voice.mp4"
    voice_meta_path_cached = out_dir / f"{stem}_{target_language}_voice.meta.json"

    # Bước 2: nếu SRT đã có → load lại, skip transcribe
    if source_srt_path.exists() and source_srt_path.stat().st_size > 0:
        try:
            segments = _parse_srt(source_srt_path)
            if segments:
                yield send(log=f"[Bước 2/5] ♻ Dùng lại phiên âm cũ ({len(segments)} đoạn): {source_srt_path.name}", level="info", subtitle_path=str(source_srt_path.resolve()))
                yield send(overall=35, overall_lbl=f"Phiên âm cũ: {len(segments)} đoạn")
                transcribe_failed = False
        except Exception:
            segments = []

    # Load config (cần cho tất cả các bước)
    import yaml as _yaml
    _cfg_file = Path(__file__).parent.parent / "config.yml"
    cfg_raw = _yaml.safe_load(_cfg_file.read_text(encoding="utf-8")) if _cfg_file.exists() else {}
    tr_cfg = cfg_raw.get("transcript", {}) or {}

    if not segments:
        try:
            if transcribe_provider == "model":
                transcriber = FasterWhisperTranscriber(model_name, language, use_vad=True)
            else:
                groq_key = (
                    str(data.get("groq_api_key") or "").strip()
                    or os.getenv("GROQ_API_KEY", "").strip()
                    or str(tr_cfg.get("groq_api_key") or "").strip()
                )
                groq_model = str(data.get("groq_model") or tr_cfg.get("groq_model") or _GROQ_MODEL).strip() or _GROQ_MODEL
                groq_max_mb = int(data.get("groq_max_mb") or tr_cfg.get("groq_max_mb") or _GROQ_MAX_MB)
                transcriber = GroqWhisperTranscriber(
                    language=language,
                    api_key=groq_key,
                    model=groq_model,
                    max_mb=groq_max_mb,
                )
            segments = transcriber.transcribe(video_path, ffmpeg, source_srt_path)
            if not segments:
                transcribe_failed = True
                yield send(log="[Bước 2/5] ⚠ Không phát hiện giọng nói trong video", level="warning")
                if not (do_voice or do_burn):
                    yield send(log="[Bước 2/5] ✗ Không có giọng nói và TTS/burn phụ đề cũng bị tắt", level="error")
                    return
                if do_burn and not do_voice:
                    yield send(log="[Bước 2/5] ℹ Sẽ chỉ burn phụ đề, bỏ qua phiên âm", level="info")
                    segments = []
                else:
                    video_duration = get_media_duration_seconds(ffmpeg, video_path)
                    if video_duration > 0:
                        segments = [{"start": 0.0, "end": video_duration, "text": "[Giọng nói tự động]"}]
                        yield send(log=f"[Bước 2/5] ℹ Tạo 1 segment tự động (0s → {video_duration:.1f}s)", level="info")
                    else:
                        yield send(log="[Bước 2/5] ✗ Không thể tính được thời lượng video", level="error")
                        return
            else:
                write_ass(segments, ass_path, play_res_x=_vw, play_res_y=_vh)
                yield send(log=f"[Bước 2/5] ✓ Phiên âm {len(segments)} đoạn → {ass_path.name}", level="success", subtitle_path=str(ass_path.resolve()))
            yield send(overall=35, overall_lbl=f"Phiên âm xong: {len(segments)} đoạn")
        except RuntimeError as e:
            transcribe_failed = True
            yield send(log=f"[Bước 2/5] ⚠ Phiên âm thất bại: {e}", level="warning")
            if not (do_voice or do_burn):
                yield send(log="[Bước 2/5] ✗ Không có giọng nói và TTS/burn phụ đề cũng bị tắt", level="error")
                return
            if do_burn and not do_voice:
                yield send(log="[Bước 2/5] ℹ Sẽ chỉ burn phụ đề", level="info")
                segments = []
            else:
                video_duration = get_media_duration_seconds(ffmpeg, video_path)
                if video_duration > 0:
                    segments = [{"start": 0.0, "end": video_duration, "text": "[Giọng nói tự động]"}]
                    yield send(log=f"[Bước 2/5] ℹ Tạo fallback segment (0s → {video_duration:.1f}s)", level="info")
                else:
                    yield send(log="[Bước 2/5] ✗ Không thể tính được thời lượng video", level="error")
                    return
        except Exception as e:
            transcribe_failed = True
            yield send(log=f"[Bước 2/5] ⚠ Lỗi phiên âm: {e}", level="warning")
            if not (do_voice or do_burn):
                return
            if do_burn and not do_voice:
                segments = []
            else:
                video_duration = get_media_duration_seconds(ffmpeg, video_path)
                if video_duration > 0:
                    segments = [{"start": 0.0, "end": video_duration, "text": "[Giọng nói tự động]"}]
                else:
                    return


    # ── Bước 3/5: Dịch ZH → VI ─────────────────────────────────────────────────
    translated_texts = []
    if not do_translate:
        yield send(log="[Bước 3/5] ℹ Bỏ qua dịch phụ đề (translate_subs=off)", level="info")
    else:
        # Resume: nếu vi.ass đã có → load lại segments và translated_texts từ đó
        # BUT: if frame is enabled, skip resume because ASS needs to be regenerated with new frame settings
        _frame_enabled_check = _as_bool(data.get("frame_enabled", False), False)
        if not _frame_enabled_check and vi_ass_path_cached.exists() and vi_ass_path_cached.stat().st_size > 0 and segments:
            try:
                if vi_ass_path_cached.suffix.lower() == ".srt":
                    cached_vi_segs = _parse_srt(vi_ass_path_cached)
                else:
                    cached_vi_segs = _parse_ass_file(vi_ass_path_cached)
                if cached_vi_segs:
                    tts_vi_segs = _merge_segments_for_tts(cached_vi_segs)
                    translated_texts = [s["text"] for s in tts_vi_segs]
                    segments = tts_vi_segs
                    vi_ass_path = vi_ass_path_cached
                    srt_path = vi_ass_path
                    yield send(log=f"[Bước 3/5] ♻ Dùng lại bản dịch cũ ({len(cached_vi_segs)} dòng, gộp {len(translated_texts)} đoạn TTS): {vi_ass_path_cached.name}", level="info", subtitle_path=str(vi_ass_path_cached.resolve()))
                    yield send(overall=55, overall_lbl="Dùng lại bản dịch cũ")
            except Exception:
                translated_texts = []

        if not translated_texts and segments:
            n_segs = len(segments)
            batch_sz = 30
            n_batches = (n_segs + batch_sz - 1) // batch_sz
            yield send(log=f"[Bước 3/5] 🌐 Dịch {n_segs} đoạn sang {target_lang_name} ({n_batches} batch)...", level="info")
            yield send(overall=45, overall_lbl=f"Đang dịch {n_segs} đoạn...")
            try:
                from utils.translation import BatchTranslator
                trans_cfg = cfg_raw.get("translation", {})
                if not trans_cfg.get("groq_key"):
                    trans_cfg["groq_key"] = (
                        str(data.get("groq_api_key") or "").strip()
                        or os.getenv("GROQ_API_KEY", "").strip()
                        or str(tr_cfg.get("groq_api_key") or "").strip()
                    )
                if not trans_cfg.get("groq_model"):
                    trans_cfg["groq_model"] = (
                        str(data.get("groq_model") or "").strip()
                        or str(tr_cfg.get("groq_model") or "").strip()
                        or "llama-3.1-8b-instant"
                    )
                req_provider = str(data.get("translate_provider") or "").strip().lower()
                cfg_provider = str(trans_cfg.get("preferred_provider") or "").strip().lower()
                # Treat "auto" as unspecified so config/provider key can decide deterministically.
                if req_provider == "auto":
                    req_provider = ""
                if cfg_provider == "auto":
                    cfg_provider = ""
                provider = req_provider or cfg_provider or ("deepseek" if trans_cfg.get("deepseek_key") else "auto")
                texts = [seg.get("text", "").strip() for seg in segments]
                has_ds = bool(trans_cfg.get("deepseek_key"))
                has_groq = bool(trans_cfg.get("groq_key"))
                nr_cfg = cfg_raw.get("nine_router") or {}
                has_9r = bool((nr_cfg.get("api_key") or "").strip())
                yield send(log=f"[Bước 3/5] Provider: {provider} | deepseek={'✓' if has_ds else '✗'} | groq={'✓' if has_groq else '✗'} | 9router={'✓' if has_9r else '✗'}", level="info")
                translator = BatchTranslator(trans_cfg, nine_router_cfg=nr_cfg)
                translated_texts, used = translator.translate(texts, provider, context=stem_source, target_lang=target_language)
                yield send(log=f"[Bước 3/5] ✓ Dịch xong {len(translated_texts)} đoạn (provider: {used})", level="success")
                yield send(overall=55, overall_lbl="Dịch xong")

                if translated_texts:
                    # Luôn dùng ASS — không dùng SRT
                    alignment = 8 if str(data.get("subtitle_position", "bottom")).lower() == "top" else 2
                    vi_ass_path = out_dir / f"{stem}_{target_language}.ass"
                    vi_segs = [{"start": s["start"], "end": s["end"], "text": t}
                               for s, t in zip(segments, translated_texts) if t]

                    # Scale font_size, margin_v, and outline_width dynamically based on actual video height vs 720
                    _orig_font_size = _as_int(data.get("font_size", 32), 32)
                    _orig_margin_v = effective_margin_v
                    _orig_outline_width = _as_int(data.get("outline_width", 2), 2)
                    
                    _scaled_font_size = max(8, int(_orig_font_size * _vh / 720))
                    _scaled_margin_v = max(0, int(_orig_margin_v * _vh / 720))
                    _scaled_outline_width = max(1, int(_orig_outline_width * _vh / 720))

                    # Check if frame elements should be embedded in ASS
                    frame_enabled = _as_bool(data.get("frame_enabled", False), False)

                    if frame_enabled:
                        _duration = get_media_duration_seconds(ffmpeg, video_path)
                        if _duration <= 0:
                            _duration = 600.0

                        # Auto-generate title if not provided
                        _frame_title = str(data.get("frame_title") or "").strip()
                        if not _frame_title:
                            yield send(log=f"[Bước 3/5] 🤖 AI đang tạo tiêu đề khung...", level="info")
                            try:
                                _frame_title = generate_frame_title(
                                    translated_texts=translated_texts,
                                    original_texts=texts,
                                    trans_cfg=trans_cfg,
                                    preferred_provider=provider,
                                    video_title=stem_source,
                                    target_lang=target_language,
                                    nine_router_cfg=cfg_raw.get("nine_router") or {},
                                )
                                yield send(log=f"[Bước 3/5] ✓ Tiêu đề AI: \"{_frame_title}\"", level="success")
                            except Exception as _e:
                                yield send(log=f"[Bước 3/5] ⚠ Không tạo được tiêu đề: {_e}", level="warning")
                                _frame_title = ""

                        # Logo path — default to img/logo.png
                        _logo_path = str(data.get("frame_logo_path") or "").strip()
                        if not _logo_path:
                            _default_logo = Path(__file__).parent.parent / "img" / "logo.png"
                            if _default_logo.exists():
                                _logo_path = str(_default_logo)

                        write_ass_with_frame(
                            segments=vi_segs,
                            out_path=vi_ass_path,
                            video_duration=_duration,
                            play_res_x=_vw,
                            play_res_y=_vh,
                            font_size=_scaled_font_size,
                            font_color=data.get("font_color", "white"),
                            outline_color=data.get("outline_color", "black"),
                            outline_width=_scaled_outline_width,
                            margin_v=_scaled_margin_v,
                            alignment=alignment,
                            title_text=_frame_title if _as_bool(data.get("frame_title_enabled", True), True) else "",
                            title_size_pct=_as_float(data.get("frame_title_size_pct"), 7.0),
                            title_color=str(data.get("frame_title_color") or "#000000"),
                            title_color_2=str(data.get("frame_title_color_2") or "#ff0000"),
                            title_split_color=_as_bool(data.get("frame_title_split_color", True), True),
                            title_bar_color=str(data.get("frame_title_bar_color") or "#ffffff"),
                            # Khi user tắt "Hiện tiêu đề" → ép title_bar_h_pct=0 để
                            # hoàn toàn không vẽ dải trắng (dù logic vẽ đã skip khi
                            # title rỗng, đây là double-safe).
                            title_bar_h_pct=(
                                _as_float(data.get("frame_title_bar_h_pct"), 12.0)
                                if _as_bool(data.get("frame_title_enabled", True), True)
                                else 0.0
                            ),
                            blur_w_pct=_as_float(data.get("frame_blur_w_pct"), 15.0),
                            blur_top_pct=_as_float(data.get("frame_blur_top_pct"), 0.0),
                            blur_bottom_pct=_as_float(data.get("frame_blur_bottom_pct"), 0.0),
                            blur_opacity=_as_float(data.get("frame_blur_opacity"), 0.6),
                            blur_color=str(data.get("frame_blur_color") or "#000000"),
                            logo_path=_logo_path,
                            logo_size_pct=_as_float(data.get("frame_logo_size_pct"), 6.0),
                            logo_top_pct=_as_float(data.get("frame_logo_top_pct"), 3.0),
                            logo_left_pct=_as_float(data.get("frame_logo_left_pct"), 3.0),
                            logo_radius_pct=_as_float(data.get("frame_logo_radius_pct"), 50.0),
                            logo_position=str(data.get("frame_logo_position") or "top-left"),
                        )
                        yield send(log=f"[Bước 3/5] ✓ ASS (có khung) {target_lang_name}: {vi_ass_path.name}", level="success", subtitle_path=str(vi_ass_path.resolve()))
                        yield send(log=f"[Bước 3/5] 🎞 Khung: title=\"{_frame_title[:25]}\", blur={_as_float(data.get('frame_blur_w_pct'), 15.0)}%, logo={'✓' if _logo_path else '✗'}", level="info")
                    else:
                        write_ass(vi_segs, vi_ass_path,
                                  font_size=_scaled_font_size,
                                  font_color=data.get("font_color", "white"),
                                  outline_color=data.get("outline_color", "black"),
                                  outline_width=_scaled_outline_width,
                                  margin_v=_scaled_margin_v,
                                  alignment=alignment,
                                  play_res_x=_vw,
                                  play_res_y=_vh)
                        yield send(log=f"[Bước 3/5] ✓ ASS {target_lang_name}: {vi_ass_path.name}", level="success", subtitle_path=str(vi_ass_path.resolve()))
                    # Signal frontend to review the ASS file before continuing
                    yield send(
                        review_ass=True,
                        ass_path=str(vi_ass_path.resolve()),
                        log=f"[Bước 3/5] ⏸ Chờ kiểm tra nội dung dịch: {vi_ass_path.name}",
                        level="info",
                    )
                    # Wait for frontend to confirm (or auto-continue if skip_review)
                    import threading as _thr
                    from routes.process import _proc_review_event, _proc_pause_event
                    _proc_review_event.clear()
                    # Wait up to 10 minutes for user review
                    _proc_review_event.wait(timeout=600)
                    _proc_review_event.set()
                    # Re-read vi_ass_path in case user edited it
                    yield send(log=f"[Bước 3/5] ▶ Tiếp tục xử lý...", level="info")

                    if vi_ass_path and vi_ass_path.exists():
                        refreshed_vi_segs = _parse_ass_file(vi_ass_path)
                        if refreshed_vi_segs:
                            tts_vi_segs = _merge_segments_for_tts(refreshed_vi_segs)
                            segments = tts_vi_segs
                            translated_texts = [s.get("text", "") for s in tts_vi_segs]
                            yield send(
                                log=f"[Bước 3/5] ✓ Đã nạp ASS mới nhất sau chỉnh sửa ({len(refreshed_vi_segs)} dòng, gộp {len(translated_texts)} đoạn TTS)",
                                level="success",
                                subtitle_path=str(vi_ass_path.resolve()),
                            )
                        else:
                            yield send(
                                log=f"[Bước 3/5] ⚠ Không đọc được dialogue từ ASS đã chỉnh sửa: {vi_ass_path.name}",
                                level="warning",
                            )

                    if do_burn and do_burn_vi:
                        srt_path = vi_ass_path
                        yield send(log=f"[Bước 3/5] Sẽ burn: {srt_path.name}", level="info")
            except Exception as e:
                yield send(log=f"[Bước 3/5] ✗ Dịch thất bại: {e}", level="error")
                translated_texts = []

    # ── Parallel thumbnail generation (chạy song song với burn) ─────────
    # Mode: 'ai' | 'import' | 'frame' | 'none'
    # User có thể override config qua modal "Chọn thumbnail" sau khi review ASS.
    try:
        from routes.process import get_proc_thumb_override
        _thumb_user_cfg = get_proc_thumb_override()
    except Exception:
        _thumb_user_cfg = {}

    if _thumb_user_cfg:
        _thumb_enabled = bool(_thumb_user_cfg.get("thumb_enabled"))
        _thumb_mode = str(_thumb_user_cfg.get("thumb_mode") or "none").lower()
        _thumb_path_input = str(_thumb_user_cfg.get("thumb_path") or "").strip()
        _thumb_title = str(_thumb_user_cfg.get("thumb_title") or "").strip()
        _thumb_duration = _as_float(_thumb_user_cfg.get("thumb_duration", 0.3), 0.3)
        _thumb_timestamp = _as_float(_thumb_user_cfg.get("thumb_timestamp", 5.0), 5.0)
    else:
        _thumb_enabled = _as_bool(data.get("thumb_enabled", False), False)
        _thumb_mode = str(data.get("thumb_mode") or "none").lower()
        _thumb_path_input = str(data.get("thumb_path") or "").strip()
        _thumb_title = str(data.get("thumb_title") or "").strip()
        _thumb_duration = _as_float(data.get("thumb_duration", 0.3), 0.3)
        _thumb_timestamp = _as_float(data.get("sub_preview_ts") or data.get("thumb_timestamp", 5.0), 5.0)

    _thumb_future = None
    _thumb_executor = None
    _thumb_target_path = out_dir / f"{stem}_thumb.jpg"

    if _thumb_enabled and _thumb_mode != "none" and do_burn:
        try:
            import concurrent.futures
            _thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

            def _gen_thumb_task():
                """Generate thumbnail file in parallel. Returns Path or None."""
                try:
                    if _thumb_mode == "import" and _thumb_path_input:
                        # Just copy the user-provided file
                        src = Path(_thumb_path_input)
                        if src.exists():
                            import shutil
                            shutil.copy2(str(src), str(_thumb_target_path))
                            return _thumb_target_path
                        return None
                    elif _thumb_mode == "frame":
                        # Extract a frame from the video at the chosen timestamp
                        ts = _thumb_timestamp
                        ok, _err = run_ffmpeg([
                            ffmpeg, "-ss", str(ts),
                            "-i", str(video_path),
                            "-vframes", "1", "-q:v", "2",
                            str(_thumb_target_path), "-y", "-loglevel", "error"
                        ], timeout=60)
                        if ok and _thumb_target_path.exists():
                            return _thumb_target_path
                        return None
                    elif _thumb_mode == "ai":
                        # Generate via Gemini (extract frame first, send to Gemini)
                        return _gen_ai_thumbnail_for_pipeline(
                            video_path=video_path,
                            output_path=_thumb_target_path,
                            ffmpeg=ffmpeg,
                            timestamp=_thumb_timestamp,
                            title=_thumb_title or video_title,
                            subtitle_text=" ".join(translated_texts[:3]) if translated_texts else "",
                        )
                except Exception:
                    return None
                return None

            _thumb_future = _thumb_executor.submit(_gen_thumb_task)
            yield send(log=f"[Bước 4/5] 🖼 Đang tạo thumbnail ({_thumb_mode}) song song với burn...", level="info")
        except Exception as e:
            yield send(log=f"[Bước 4/5] ⚠ Không khởi tạo được thumbnail task: {e}", level="warning")

    # ── Bước 4/5: Burn phụ đề ────────────────────────────────────────────────
    burned_path = None
    # Resume: nếu file subbed đã có → dùng lại (BUT: skip if frame enabled to re-apply new frame settings)
    _frame_enabled_for_burn = _as_bool(data.get("frame_enabled", False), False)
    _burn_cache_valid = False
    _burn_cache_stale_reason = ""
    if do_burn and not _frame_enabled_for_burn and burned_path_cached.exists() and burned_path_cached.stat().st_size > 0:
        try:
            _burn_deps = [video_path]
            if srt_path and Path(srt_path).exists():
                _burn_deps.append(Path(srt_path))
            _newest_burn_dep = max(p.stat().st_mtime for p in _burn_deps)
            _burn_cache_valid = burned_path_cached.stat().st_mtime >= _newest_burn_dep
            if not _burn_cache_valid:
                _burn_cache_stale_reason = "ASS/video mới hơn cache"
        except Exception:
            _burn_cache_valid = False
            _burn_cache_stale_reason = "không kiểm tra được thời gian cache"

    if do_burn and not _frame_enabled_for_burn and _burn_cache_valid:
        burned_path = burned_path_cached
        final_output_path = burned_path
        yield send(log=f"[Bước 4/5] ♻ Dùng lại video phụ đề cũ: {burned_path.name}", level="info")
        yield send(overall=80, overall_lbl="Dùng lại video phụ đề cũ")
    elif do_burn and srt_path.exists():
        if _burn_cache_stale_reason:
            yield send(log=f"[Bước 4/5] ♻ Bỏ cache video phụ đề cũ ({_burn_cache_stale_reason}), burn lại từ ASS hiện tại", level="info")
        yield send(log=f"[Bước 4/5] 🔥 Đang burn phụ đề ASS vào video...", level="info")
        yield send(overall=65, overall_lbl="Đang burn phụ đề...")
        burned_path = out_dir / f"{stem}_subbed.mp4"

        # Log details before starting (so user sees progress immediately)
        _vid_size = video_path.stat().st_size / 1024 / 1024
        yield send(log=f"[Bước 4/5] 📂 Video: {video_path.name} ({_vid_size:.1f} MB)", level="info")
        yield send(log=f"[Bước 4/5] 📄 Phụ đề: {srt_path.name}", level="info")
        _hw_preset = _get_encoding_args(ffmpeg)
        _hw_desc = " ".join(_hw_preset[:6])
        yield send(log=f"[Bước 4/5] 🎬 Đang encode ({_hw_desc})...", level="info")

        # Collect logs from burn process
        _burn_logs = []
        def _burn_log_cb(msg, level="info"):
            _burn_logs.append((msg, level))

        _blur_y_raw = data.get("blur_y_pct")
        _blur_y_pct = None
        if _blur_y_raw is not None and str(_blur_y_raw).strip() != "" and str(_blur_y_raw).lower() != "null":
            try:
                _blur_y_pct = float(_blur_y_raw)
            except Exception:
                pass

        _blur_extra_zones_raw = data.get("blur_extra_zones")
        _blur_extra_zones = None
        if _blur_extra_zones_raw:
            if isinstance(_blur_extra_zones_raw, str):
                try:
                    _blur_extra_zones = _j.loads(_blur_extra_zones_raw)
                except Exception:
                    pass
            elif isinstance(_blur_extra_zones_raw, list):
                _blur_extra_zones = _blur_extra_zones_raw

        ok, err = burn_subtitles(
            video_path=video_path,
            srt_path=srt_path,
            output_path=burned_path,
            ffmpeg=ffmpeg,
            blur_original=_as_bool(data.get("blur_original", True), True),
            blur_zone=data.get("blur_zone", "bottom"),
            blur_height_pct=_as_float(data.get("blur_height_pct", 0.15), 0.15),
            blur_width_pct=_as_float(data.get("blur_width_pct", 0.80), 0.80),
            blur_lift_pct=_as_float(data.get("blur_lift_pct", 0.06), 0.06),
            font_size=_as_int(data.get("font_size", 32), 32),
            font_color=data.get("font_color", "white"),
            outline_color=data.get("outline_color", "black"),
            outline_width=_as_int(data.get("outline_width", 2), 2),
            margin_v=effective_margin_v,
            subtitle_position=data.get("subtitle_position", "bottom"),
            subtitle_format="ass",  # luôn dùng ASS
            frame_enabled=False,
            log_callback=_burn_log_cb,
            blur_y_pct=_blur_y_pct,
            blur_extra_zones=_blur_extra_zones,
        )
        # Emit collected burn logs
        for _msg, _lvl in _burn_logs:
            yield send(log=f"[Bước 4/5] {_msg}", level=_lvl)
        if ok:
            yield send(log=f"[Bước 4/5] ✓ Video có phụ đề: {burned_path.name}", level="success")
            yield send(overall=80, overall_lbl="Burn phụ đề xong")
            final_output_path = burned_path
        else:
            yield send(log=f"[Bước 4/5] ✗ Burn thất bại: {err}", level="error")
            burned_path = None
    elif do_burn and not srt_path.exists():
        yield send(log="[Bước 4/5] ⚠ Không có file phụ đề để burn", level="warning")
    else:
        yield send(log="[Bước 4/5] ℹ Bỏ qua burn phụ đề", level="info")

    # ── Convert aspect ratio (sau khi burn xong, trước khi concat thumbnail) ──
    # Nếu user chọn 9x16/16x9 mà video burned không đúng aspect đó → convert.
    # Khi 'auto' hoặc đã đúng aspect → bỏ qua. Đảm bảo chạy TRƯỚC concat
    # thumbnail để aspect của final khớp với thumbnail.
    _target_aspect = str(data.get("target_aspect") or "auto").lower()
    if _target_aspect in ("9x16", "16x9") and burned_path and burned_path.exists():
        try:
            _r = subprocess.run([ffmpeg, "-i", str(burned_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            _m = re.search(r"(\d{2,5})x(\d{2,5})", _r.stderr or "")
            _src_w, _src_h = (int(_m.group(1)), int(_m.group(2))) if _m else (1280, 720)
        except Exception:
            _src_w, _src_h = 1280, 720

        src_is_vertical = _src_h > _src_w
        target_w, target_h = (1080, 1920) if _target_aspect == "9x16" else (1920, 1080)
        should_convert = (
            (_target_aspect == "9x16" and not src_is_vertical)
            or (_target_aspect == "16x9" and src_is_vertical)
        )

        if not should_convert:
            mode_label = "doc" if _target_aspect == "9x16" else "ngang"
            src_label = "doc" if src_is_vertical else "ngang"
            yield send(
                log=f"[Aspect] Mode {_target_aspect} ({mode_label}): video da {src_label} {_src_w}x{_src_h}, giu nguyen kich thuoc",
                level="info",
            )
        else:
            aspect_video = out_dir / f"{stem}_subbed_{_target_aspect}.mp4"
            yield send(
                log=f"[Aspect] Chuyen huong video: {_src_w}x{_src_h} -> {target_w}x{target_h} ({_target_aspect})",
                level="info",
            )
            vf = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
            )
            ok_a, err_a = run_ffmpeg([
                ffmpeg, "-i", str(burned_path),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "copy",
                str(aspect_video), "-y", "-loglevel", "error",
            ], timeout=600)
            if ok_a and aspect_video.exists():
                yield send(log=f"[Aspect] ✓ Khung hình đã chuyển: {aspect_video.name}", level="success")
                burned_path = aspect_video
                final_output_path = aspect_video
            else:
                yield send(log=f"[Aspect] ⚠ Convert khung hình thất bại: {err_a}", level="warning")

    # ── Concat thumbnail vào đầu video (sau khi burn + convert aspect xong) ───
    def _emit_thumb_image(thumb_path: Path):
        """Đọc file thumbnail → base64 và emit event để frontend hiển thị."""
        try:
            import base64 as _b64
            mime = "image/png" if thumb_path.suffix.lower() == ".png" else "image/jpeg"
            data_b64 = _b64.b64encode(thumb_path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data_b64}"
        except Exception:
            return ""

    if _thumb_future and burned_path and burned_path.exists():
        try:
            yield send(log="[Bước 4/5] ⏳ Đợi thumbnail hoàn tất để chèn vào đầu video...", level="info")
            try:
                thumb_result = _thumb_future.result(timeout=120)
            except Exception as _ex:
                thumb_result = None
                yield send(log=f"[Bước 4/5] ⚠ Lỗi tạo thumbnail: {_ex}", level="warning")

            # ── Retry loop khi AI thumbnail fail (chỉ áp dụng cho mode='ai') ──
            if (not thumb_result or not Path(thumb_result).exists()) and _thumb_mode == "ai":
                from routes.process import wait_thumb_retry_action
                _max_retries = 3
                for _attempt in range(1, _max_retries + 1):
                    yield send(
                        thumb_failed=True,
                        thumb_mode=_thumb_mode,
                        log=f"[Bước 4/5] ⚠ Thumbnail AI thất bại — chờ user xử lý (lần {_attempt}/{_max_retries})",
                        level="warning",
                    )
                    action_data = wait_thumb_retry_action(timeout=600)
                    action = action_data.get("action") or "skip"
                    if action == "retry":
                        yield send(log="[Bước 4/5] 🔄 Thử tạo lại thumbnail AI...", level="info")
                        try:
                            thumb_result = _gen_ai_thumbnail_for_pipeline(
                                video_path=video_path,
                                output_path=_thumb_target_path,
                                ffmpeg=ffmpeg,
                                timestamp=_thumb_timestamp,
                                title=_thumb_title or video_title,
                                subtitle_text=" ".join(translated_texts[:3]) if translated_texts else "",
                            )
                        except Exception as _re:
                            thumb_result = None
                            yield send(log=f"[Bước 4/5] ⚠ Retry lỗi: {_re}", level="warning")
                        if thumb_result and Path(thumb_result).exists():
                            yield send(log="[Bước 4/5] ✓ Thumbnail AI tạo lại thành công", level="success")
                            break
                    elif action == "upload":
                        user_path = action_data.get("path") or ""
                        try:
                            import shutil as _shutil
                            src = Path(user_path)
                            if src.exists():
                                _shutil.copy2(str(src), str(_thumb_target_path))
                                thumb_result = _thumb_target_path
                                yield send(log=f"[Bước 4/5] ✓ Đã dùng ảnh user upload: {src.name}", level="success")
                                break
                            else:
                                yield send(log=f"[Bước 4/5] ⚠ File upload không tồn tại: {user_path}", level="warning")
                        except Exception as _ue:
                            yield send(log=f"[Bước 4/5] ⚠ Lỗi copy ảnh upload: {_ue}", level="warning")
                    else:
                        # skip
                        yield send(log="[Bước 4/5] ℹ User chọn bỏ qua thumbnail", level="info")
                        thumb_result = None
                        break

            if thumb_result and Path(thumb_result).exists():
                # Emit ảnh thumbnail (base64) để frontend hiển thị real-time
                _img_data = _emit_thumb_image(Path(thumb_result))
                yield send(
                    log=f"[Bước 4/5] 🖼 Thumbnail đã sẵn sàng: {Path(thumb_result).name}",
                    level="info",
                    thumbnail_path=str(Path(thumb_result).resolve()),
                    thumbnail_image=_img_data,
                )

                concat_out = out_dir / f"{stem}_subbed_with_thumb.mp4"
                yield send(log=f"[Bước 4/5] 🎬 Đang chèn thumbnail ({_thumb_duration}s) vào đầu video...", level="info")
                ok_c, err_c = concat_thumbnail_with_video(
                    video_path=burned_path,
                    thumbnail_path=Path(thumb_result),
                    output_path=concat_out,
                    ffmpeg=ffmpeg,
                    duration=_thumb_duration,
                )
                if ok_c and concat_out.exists():
                    yield send(log=f"[Bước 4/5] ✓ Đã chèn thumbnail: {concat_out.name}", level="success")
                    burned_path = concat_out
                    final_output_path = concat_out
                else:
                    yield send(log=f"[Bước 4/5] ⚠ Chèn thumbnail thất bại: {err_c}", level="warning")
            else:
                yield send(log="[Bước 4/5] ⚠ Không có thumbnail — bỏ qua chèn vào video", level="warning")
        except Exception as e:
            yield send(log=f"[Bước 4/5] ⚠ Lỗi xử lý thumbnail: {e}", level="warning")
        finally:
            try:
                if _thumb_executor:
                    _thumb_executor.shutdown(wait=False)
            except Exception:
                pass

    # ── Bước 5/5: Tạo giọng đọc (TTS) ───────────────────────────────────
    # Resume: nếu file voice đã có → dùng lại
    _voice_cache_valid = False
    _voice_cache_stale_reason = ""
    if do_voice and voice_path_cached.exists() and voice_path_cached.stat().st_size > 0:
        try:
            _voice_deps = [video_path]
            if burned_path and Path(burned_path).exists():
                _voice_deps.append(Path(burned_path))
            if srt_path and Path(srt_path).exists():
                _voice_deps.append(Path(srt_path))
            _newest_voice_dep = max(p.stat().st_mtime for p in _voice_deps)
            _voice_cache_valid = voice_path_cached.stat().st_mtime >= _newest_voice_dep
            if not _voice_cache_valid:
                _voice_cache_stale_reason = "ASS/video mới hơn cache"
            if _voice_cache_valid:
                try:
                    voice_meta = json.loads(voice_meta_path_cached.read_text(encoding="utf-8"))
                except Exception:
                    voice_meta = {}
                if voice_meta.get("tts_cache_version") != TTS_CACHE_VERSION:
                    _voice_cache_valid = False
                    _voice_cache_stale_reason = "cách gộp câu TTS đã cập nhật"
        except Exception:
            _voice_cache_valid = False
            _voice_cache_stale_reason = "không kiểm tra được thời gian cache"

    if do_voice and _voice_cache_valid:
        final_output_path = voice_path_cached
        yield send(log=f"[Bước 5/5] ♻ Dùng lại giọng {target_lang_name} cũ: {voice_path_cached.name}", level="info")
        yield send(overall=92, overall_lbl="Dùng lại giọng cũ")
    elif do_voice and translated_texts:
        if _voice_cache_stale_reason:
            yield send(log=f"[Bước 5/5] ♻ Bỏ cache giọng cũ ({_voice_cache_stale_reason}), tạo lại từ ASS hiện tại", level="info")
        yield send(log=f"[Bước 5/5] 🗣 Đang tạo giọng {target_lang_name}...", level="info")
        yield send(overall=85, overall_lbl="Đang tạo giọng nói...")
        source_for_voice = burned_path if burned_path else video_path
        voice_path = out_dir / f"{stem}_{target_language}_voice.mp4"
        try:
            with tempfile.TemporaryDirectory(prefix="tts_") as tts_tmpdir:
                tts = MultiProviderTTS(
                    voice=data.get("tts_voice", "banmai"),
                    engine=data.get("tts_engine", "fpt-ai"),
                    fpt_api_key=(
                        str(data.get("fpt_api_key") or "").strip()
                        or str((cfg_raw.get("video_process") or {}).get("fpt_api_key") or "").strip()
                        or os.getenv("FPT_AI_API_KEY", "").strip()
                        or FPT_TTS_DEFAULT_KEY
                    ),
                    fpt_speed=_as_int(data.get("fpt_speed", 0), 0),
                    openai_api_key=(
                        str(data.get("openai_api_key") or "").strip()
                        or str((cfg_raw.get("video_process") or {}).get("openai_api_key") or "").strip()
                        or str((cfg_raw.get("translation") or {}).get("openai_key") or "").strip()
                        or os.getenv("OPENAI_API_KEY", "").strip()
                    ),
                    openai_model=str(data.get("openai_tts_model") or "tts-1"),
                    tts_lang=target_language,
                    elevenlabs_api_key=(
                        str(data.get("elevenlabs_api_key") or "").strip()
                        or str((cfg_raw.get("video_process") or {}).get("elevenlabs_api_key") or "").strip()
                        or os.getenv("ELEVENLABS_API_KEY", "").strip()
                    ),
                    elevenlabs_voice_id=(
                        str(data.get("elevenlabs_voice_id") or "").strip()
                        or str((cfg_raw.get("video_process") or {}).get("elevenlabs_voice_id") or "").strip()
                    ),
                    elevenlabs_model=str(
                        data.get("elevenlabs_model")
                        or (cfg_raw.get("video_process") or {}).get("elevenlabs_model")
                        or "eleven_multilingual_v2"
                    ),
                    fpt_fallback_elevenlabs=_as_bool(
                        data.get(
                            "fpt_fallback_elevenlabs",
                            (cfg_raw.get("video_process") or {}).get("fpt_fallback_elevenlabs", True),
                        ),
                        True,
                    ),
                    fish_api_key=(
                        str(data.get("fish_api_key") or "").strip()
                        or str((cfg_raw.get("video_process") or {}).get("fish_api_key") or "").strip()
                        or os.getenv("FISH_API_KEY", "").strip()
                        or os.getenv("FISH_AUDIO_API_KEY", "").strip()
                    ),
                    fish_model=str(
                        data.get("fish_model")
                        or (cfg_raw.get("video_process") or {}).get("fish_model")
                        or "s2-pro"
                    ),
                    fish_reference_id=str(
                        data.get("fish_reference_id")
                        or (cfg_raw.get("video_process") or {}).get("fish_reference_id")
                        or ""
                    ),
                )
                tts_clips = asyncio.run(
                    tts.generate_all(
                        segments,
                        translated_texts,
                        Path(tts_tmpdir),
                        max_concurrency=_as_int(data.get("tts_concurrency", 2), 2),
                        retries=_as_int(data.get("tts_retries", 2), 2),
                        tts_speed=_as_float(data.get("tts_speed", 1.0), 1.0),
                        auto_speed=_as_bool(data.get("auto_speed", True), True),
                        ffmpeg=ffmpeg,
                        pitch_semitones=_as_float(data.get("pitch_semitones", 0.0), 0.0),
                    )
                )
                yield send(
                    log=f"[Bước 5/5] TTS clips thành công: {len(tts_clips)}/{len(translated_texts)}",
                    level="info",
                )
                if tts_clips:
                    first_start = float(tts_clips[0].get("start", 0.0))
                    last_end = max(float(c.get("end", 0.0)) for c in tts_clips)
                    coverage_ratio = 0.0
                    if segments:
                        src_end = max(float(s.get("end", 0.0)) for s in segments)
                        if src_end > 0:
                            coverage_ratio = min(100.0, max(0.0, (last_end / src_end) * 100.0))
                    yield send(
                        log=(
                            f"[Bước 5/5] Độ phủ timeline giọng: "
                            f"{_fmt_hms(first_start)} → {_fmt_hms(last_end)} "
                            f"(~{coverage_ratio:.1f}% thời lượng thoại)"
                        ),
                        level="info",
                    )
                if len(tts_clips) < max(1, int(len(translated_texts) * 0.2)):
                    yield send(
                        log="[Bước 5/5] ⚠ Quá ít clip TTS, có thể bị giới hạn dịch vụ. Hãy thử lại hoặc giảm tốc độ tạo giọng.",
                        level="warning",
                    )
                mixer = AudioMixer(ffmpeg)
                ok, err = mixer.mix(
                    video_path=source_for_voice,
                    tts_clips=tts_clips,
                    output_path=voice_path,
                    keep_bg_music=_as_bool(data.get("keep_bg_music", False), False),
                    bg_volume=_as_float(data.get("bg_volume", 0.08), 0.08),
                    tts_volume=_as_float(data.get("tts_volume", 1.8), 1.8),
                )
            if ok:
                try:
                    voice_meta_path_cached.write_text(
                        json.dumps(
                            {
                                "tts_cache_version": TTS_CACHE_VERSION,
                                "subtitle_path": str(Path(srt_path).resolve()) if srt_path else "",
                                "segments": len(translated_texts),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                yield send(log=f"[Bước 5/5] ✓ Giọng {target_lang_name}: {voice_path.name}", level="success")
                yield send(overall=92, overall_lbl="Tạo giọng xong")
                final_output_path = voice_path
            else:
                yield send(log=f"[Bước 5/5] ✗ Tạo giọng thất bại: {err}", level="error")
        except Exception as e:
            yield send(log=f"[Bước 5/5] ✗ Lỗi tạo giọng: {e}", level="error")

    if not final_output_path:
        final_output_path = video_path.resolve()
        yield send(log="[Hoàn tất] Không có bước chỉnh sửa nào, dùng lại file gốc", level="info", file_path=str(final_output_path))

    # ── Auto Thumbnail ────────────────────────────────────────────────────────
    try:
        thumb_path = out_dir / f"{stem}_thumbnail.jpg"
        # Nội dung thumbnail: dùng translated_texts hoặc tên video
        thumb_subtitle = ""
        if translated_texts:
            # Lấy 2-3 câu đầu làm nội dung
            thumb_subtitle = " ".join(translated_texts[:3])[:100]
        elif video_title:
            thumb_subtitle = video_title

        # Resolve logo_path for standard thumbnail
        _logo_path = str(data.get("frame_logo_path") or data.get("logo_path") or "").strip()
        if not _logo_path:
            _default_logo = Path(__file__).parent.parent / "img" / "logo.png"
            if _default_logo.exists():
                _logo_path = str(_default_logo)

        thumb_ok, thumb_result = generate_thumbnail(
            video_path=video_path,
            output_path=thumb_path,
            ffmpeg=ffmpeg,
            timestamp=2.0,
            title="Trạm giải trí",
            subtitle_text=thumb_subtitle,
            logo_path=_logo_path,
        )
        if thumb_ok:
            # Encode base64 để frontend hiển thị trực tiếp (không cần serve static)
            thumb_b64 = ""
            try:
                import base64 as _b64
                with open(thumb_path, "rb") as _f:
                    thumb_b64 = "data:image/jpeg;base64," + _b64.b64encode(_f.read()).decode()
            except Exception:
                pass
            yield send(
                log=f"[Thumbnail] ✓ Tạo thumbnail: {thumb_path.name}",
                level="success",
                thumbnail_path=str(thumb_path.resolve()),
                thumbnail_image=thumb_b64,
            )
        else:
            yield send(log=f"[Thumbnail] ⚠ Không tạo được thumbnail: {thumb_result}", level="warning")
    except Exception as _thumb_err:
        yield send(log=f"[Thumbnail] ⚠ Lỗi tạo thumbnail: {_thumb_err}", level="warning")

    # ── Cleanup file trung gian ───────────────────────────────────────────────
    if cleanup_outputs and final_output_path and final_output_path.exists():
        # Giữ lại SRT/ASS để resume lần sau, chỉ xóa file trung gian không cần thiết
        intermediates_to_clean = []
        # Xóa _subbed nếu đã có _voice hoặc _framed (bước sau đã dùng xong)
        if burned_path and burned_path != final_output_path:
            intermediates_to_clean.append(burned_path)
        # Xóa _voice nếu đã có _framed
        voice_p = out_dir / f"{stem}_{target_language}_voice.mp4"
        if voice_p.exists() and voice_p != final_output_path:
            intermediates_to_clean.append(voice_p)

        for extra in intermediates_to_clean:
            try:
                if extra and Path(extra).exists() and Path(extra).resolve() != final_output_path.resolve():
                    Path(extra).unlink()
            except Exception:
                pass

        if delete_source_after:
            try:
                src = Path(video_path)
                if src.exists() and src.resolve() != final_output_path.resolve():
                    src.unlink()
            except Exception:
                pass

        yield send(log=f"[Hoàn tất] File cuối cùng: {final_output_path.name}", level="success", file_path=str(final_output_path.resolve()))

    yield send(log="✅ Hoàn tất!", level="success")
    yield send(overall=100, overall_lbl="Hoàn tất")

    # ── Backend auto-upload after processing ─────────────────────────────────
    upload_cfg = dict((cfg_raw.get("upload") or {}))
    if upload_cfg.get("auto_upload") and final_output_path and final_output_path.exists():
        platform = str(upload_cfg.get("platform") or "").lower()
        title = str(data.get("video_title") or final_output_path.stem)
        # Clean title same way as frontend
        import re as _re
        title = _re.sub(r'_([a-z]{2})_(voice|voice)$', '', title, flags=_re.IGNORECASE)
        title = _re.sub(r'_(vi_voice|voice|vi|en_voice|en|ja_voice|ja|ko_voice|ko)$', '', title, flags=_re.IGNORECASE)
        title = _re.sub(r'^\d{4}-\d{2}-\d{2}_', '', title)
        title = _re.sub(r'_\d{15,}$', '', title)
        title = title.replace('_', ' ').strip()

        if platform in ("tiktok", "both"):
            try:
                from tools.tiktok_uploader import TikTokUploader
                tiktok_cfg = upload_cfg.get("tiktok") or {}
                uploader = TikTokUploader()
                if uploader.authenticate(str(tiktok_cfg.get("client_key") or ""), str(tiktok_cfg.get("client_secret") or "")):
                    privacy = str(tiktok_cfg.get("privacy_status") or "SELF_ONLY").upper()
                    privacy_map = {"private": "SELF_ONLY", "public": "PUBLIC_TO_EVERYONE", "friends": "MUTUAL_FOLLOW_FRIENDS"}
                    privacy = privacy_map.get(privacy.lower(), privacy)
                    result = uploader.upload_video(str(final_output_path), title=title, privacy_level=privacy)
                    if result:
                        yield send(log=f"[Auto-upload] ✓ TikTok: {result.get('publish_id')}", level="success")
                    else:
                        yield send(log=f"[Auto-upload] ✗ TikTok: {uploader.last_error}", level="error")
                else:
                    yield send(log="[Auto-upload] TikTok chưa đăng nhập, bỏ qua", level="warning")
            except Exception as e:
                yield send(log=f"[Auto-upload] TikTok lỗi: {e}", level="error")

        if platform in ("youtube", "both"):
            try:
                from tools.youtube_uploader import YouTubeUploader
                yt_cfg = upload_cfg.get("youtube") or {}
                uploader = YouTubeUploader()
                if uploader.credentials or uploader.authenticate():
                    # Extract hashtags from filename
                    import re
                    stem = final_output_path.stem
                    chinese_parts = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F_]*', stem)
                    hashtags = []
                    if chinese_parts:
                        try:
                            hashtags = ['#' + part.replace(' ', '').lower() for part in chinese_parts]
                        except:
                            hashtags = ['#' + part.replace(' ', '') for part in chinese_parts]
                    
                    default_tags = ['douyin', 'tiktok', 'video']
                    all_tags = default_tags + [h[1:] for h in hashtags]
                    
                    result = uploader.upload_video(final_output_path, title=title,
                        description=title, privacy_status=str(yt_cfg.get("privacy_status") or "private"),
                        tags=all_tags,
                        is_short=bool(yt_cfg.get("short", False)))
                    if result:
                        yield send(log=f"[Auto-upload] ✓ YouTube: {result.get('url')}", level="success")
                    else:
                        yield send(log="[Auto-upload] ✗ YouTube upload thất bại", level="error")
                else:
                    yield send(log="[Auto-upload] YouTube chưa đăng nhập, bỏ qua", level="warning")
            except Exception as e:
                yield send(log=f"[Auto-upload] YouTube lỗi: {e}", level="error")


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
    if not resolved_logo:
        default_logo = Path(__file__).parent.parent / "img" / "logo.png"
        if default_logo.exists():
            resolved_logo = default_logo

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

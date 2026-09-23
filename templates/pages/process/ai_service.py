"""
templates.pages.process.ai_service
Gemini Vision video analysis, prompt generation, and AI thumbnail generation.
"""
import base64
import json as _j
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

LOGGER = logging.getLogger("process_ai_service")


def clamp_val(v, lo, hi, default):
    try:
        x = float(v)
    except Exception:
        return default
    return max(lo, min(hi, x))


def json_from_text(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        return _j.loads(raw)
    except Exception:
        pass
    m_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.I)
    if m_block:
        try:
            return _j.loads(m_block.group(1).strip())
        except Exception:
            pass
    start_idx = raw.find("{")
    if start_idx != -1:
        end_idx = raw.rfind("}")
        if end_idx > start_idx:
            for i in range(end_idx, start_idx, -1):
                if raw[i] == "}":
                    try:
                        return _j.loads(raw[start_idx:i + 1].strip())
                    except Exception:
                        pass
    return {}


def clean_ai_result(result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}
    zones = result.get("suggested_blur_zones") or result.get("blur_zones") or []
    clean_zones = []
    for z in zones:
        if not isinstance(z, dict):
            continue
        h = clamp_val(z.get("height_pct"), 2, 45, 12)
        pos = clamp_val(z.get("position_pct"), 0, 100, 80)
        w = clamp_val(z.get("width_pct"), 10, 100, 80)
        x = clamp_val(z.get("x_pct"), 0, 100, 50)
        st = z.get("start_sec")
        et = z.get("end_sec")
        st_val = float(st) if st is not None else None
        et_val = float(et) if et is not None else None
        clean_zones.append({
            "label": str(z.get("label") or "Vùng cần che").strip(),
            "reason": str(z.get("reason") or "").strip(),
            "height_pct": round(h, 1),
            "position_pct": round(pos, 1),
            "width_pct": round(w, 1),
            "x_pct": round(x, 1),
            "start_sec": round(st_val, 2) if st_val is not None else None,
            "end_sec": round(et_val, 2) if et_val is not None else None,
            "confidence": round(clamp_val(z.get("confidence"), 0, 1, 0.8), 2),
        })

    titles = result.get("title_suggestions") or {}
    clean_titles = {
        "short": str(titles.get("short") or "").strip(),
        "youtube": str(titles.get("youtube") or "").strip(),
        "tiktok": str(titles.get("tiktok") or "").strip(),
        "facebook": str(titles.get("facebook") or "").strip(),
    }
    return {
        "summary": str(result.get("summary") or "").strip(),
        "visual_style": str(result.get("visual_style") or "").strip(),
        "source_language": str(result.get("source_language") or "").strip(),
        "analysis_notes": str(result.get("analysis_notes") or "").strip(),
        "needs_cover": result.get("needs_cover") or [],
        "suggested_blur_zones": clean_zones,
        "title_suggestions": clean_titles,
    }


def extract_frames_for_ai(video_path: Path, count: int) -> Tuple[List[Dict[str, Any]], float]:
    from core.video_processor import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg không tìm thấy")

    try:
        from utils.ffprobe import probe_video
        _w, _h, duration = probe_video(video_path)
    except Exception:
        duration = 0.0
    duration = float(duration or 0.0)

    if count <= 0:
        count = 6
        if duration > 0:
            count = max(4, min(8, int(duration / 4) + 1))

    if duration > 0:
        if count <= 1:
            timestamps = [max(0.2, min(duration - 0.2, duration * 0.5))]
        else:
            timestamps = [
                max(0.2, min(duration - 0.2, duration * (idx + 0.5) / count))
                for idx in range(count)
            ]
    else:
        timestamps = [1.0 + i * 3.0 for i in range(count)]

    frames: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ai_video_read_") as tmpdir:
        tmp_video = Path(tmpdir) / f"input{video_path.suffix or '.mp4'}"
        shutil.copy2(str(video_path), str(tmp_video))
        for idx, ts in enumerate(timestamps):
            out_jpg = Path(tmpdir) / f"frame_{idx}.jpg"
            subprocess.run([
                ffmpeg, "-ss", f"{ts:.3f}", "-i", str(tmp_video),
                "-vframes", "1", "-q:v", "5", "-vf", "scale=512:-1",
                str(out_jpg), "-y", "-loglevel", "error",
            ], capture_output=True, timeout=25)
            if out_jpg.exists() and out_jpg.stat().st_size > 0:
                frames.append({
                    "timestamp": round(ts, 2),
                    "b64": base64.b64encode(out_jpg.read_bytes()).decode("ascii"),
                })
    return frames, duration


def build_ai_prompt(language: str, target_language: str, duration: float, timestamps: List[float]) -> str:
    lang_hint = language or "auto"
    target_hint = target_language or "vi"
    return f"""
You are an expert video editing AI specializing in detecting unwanted hardcoded subtitles, watermarks, platform logos, and text overlays.
Source language: {lang_hint}. Output language for summary & titles: {target_hint}.
Video duration: {duration:.2f}s. Analyzed frame timestamps: {timestamps}.

CRITICAL RULES:
1. ONLY detect REAL visible text characters, hardcoded subtitles (especially in {lang_hint}), platform logos (Douyin, TikTok, Kuaishou, Xiaohongshu), author usernames, or QR codes.
2. DO NOT hallucinate or mark normal scene objects (such as beds, blankets, pillows, clothing, furniture, floors, walls, human bodies, faces) as text/logos! If a frame has NO subtitles or logos, return empty arrays.
3. PRECISE TIMECODES: If subtitles only appear during a portion of the video (e.g. only in the last frames), specify the exact "start_sec" and "end_sec" timestamps where they are visible. Do NOT set a global mask if subtitles are only present at the end or beginning.
4. TIGHT BOXES: Bounding boxes must tightly cover the text area only.

Return strict JSON only:
{{
  "summary": "concise summary of video content",
  "visual_style": "camera style, lighting, setting",
  "source_language": "detected language",
  "analysis_notes": "details about text/logos found",
  "needs_cover": [
    {{
      "type": "subtitle|logo|watermark|qr",
      "label": "description of text/logo",
      "reason": "why cover",
      "confidence": 0.9,
      "box_pct": {{"x": 15, "y": 75, "w": 70, "h": 10}},
      "start_sec": 60.0,
      "end_sec": 120.0
    }}
  ],
  "suggested_blur_zones": [
    {{
      "label": "phụ đề gốc",
      "reason": "che phụ đề gốc tiếng Trung",
      "height_pct": 10,
      "position_pct": 80,
      "width_pct": 75,
      "x_pct": 50,
      "start_sec": 60.0,
      "end_sec": 120.0,
      "confidence": 0.9
    }}
  ],
  "title_suggestions": {{
    "short": "tiêu đề ngắn gọn",
    "youtube": "tiêu đề YouTube hấp dẫn",
    "tiktok": "caption TikTok thu hút",
    "facebook": "tiêu đề Facebook"
  }}
}}
If no subtitles/logos exist, return "needs_cover": [] and "suggested_blur_zones": [].
""".strip()


def call_gemini_vision(
    api_key: str,
    model: str,
    prompt: str,
    frames: List[Dict[str, Any]],
    base_url: str = "",
    connection=None,
    db_models=None,
) -> dict:
    m_clean = (model or "").split("/")[-1].lower().strip()
    if not m_clean:
        raise RuntimeError("Chưa chọn model Antigravity")

    parts: List[Dict[str, Any]] = []
    parts.append({"text": prompt})
    for f in frames:
        parts.append({"text": f"Frame at {f['timestamp']} seconds"})
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": f["b64"]}})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1800,
            "responseMimeType": "application/json",
        },
    }
    models_to_try = [m_clean]
    for db_model in (db_models or []):
        candidate = str(db_model or "").split("/")[-1].lower().strip()
        if candidate and candidate not in models_to_try:
            models_to_try.append(candidate)

    last_err = None
    for m_candidate in models_to_try:
        try:
            from templates.pages.config.route import generate_content_direct
            direct_connection = connection or {"api_key": api_key, "base_url": base_url}
            data = generate_content_direct(direct_connection, m_candidate, payload, timeout=35)
            parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = "\n".join(str(p.get("text") or "") for p in parts if p.get("text")).strip()
            if text:
                res_json = json_from_text(text)
                if res_json:
                    return res_json
        except Exception as e:
            LOGGER.warning("Antigravity model %s failed: %s, trying next candidate", m_candidate, e)
            last_err = e
            continue

    if last_err:
        raise last_err
    raise RuntimeError("Antigravity không trả về nội dung phân tích")


def ai_thumbnail_prompt_from_frame(
    api_key: str,
    frame_b64: str,
    title: str,
    subtitle: str,
    style: str,
    aspect_ratio: str,
    is_editing_existing_thumb: bool = False,
) -> str:
    """Use Gemini Vision to analyze a video frame and generate a creative thumbnail prompt."""
    import json as _json
    import urllib.request
    import urllib.error

    model = "gemini-3.6-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    if is_editing_existing_thumb:
        system_instruction = f"""You are an expert thumbnail editor. 
Analyze the provided existing thumbnail image and output a prompt for AI image generation that modifies and refines it.

Rules for modification:
- Do NOT generate a completely new composition or change the core elements.
- Analyze the layout, colors, and key items of this existing image.
- Write a prompt instructing the generator to add a prominent, stylish text overlay showing: '{title}'.
- The prompt must specify to keep the existing background and elements, but enhance contrast, dramatic lighting, and add details matching the content: '{subtitle or title}'.
- Output ONLY the prompt text to edit this image, keeping the exact style, nothing else. Keep it under 150 words."""
    else:
        system_instruction = f"""You are an expert thumbnail designer for {style} videos.
Analyze the video frame and create a prompt for AI image generation that will produce an eye-catching thumbnail.

Rules:
- The thumbnail should be visually striking and click-worthy
- Use vibrant colors, high contrast, dramatic lighting
- Include relevant visual elements from the video content
- Aspect ratio: {aspect_ratio}
- If a title/brand is provided, incorporate it naturally
- Keep the prompt concise (under 150 words)
- Output ONLY the image generation prompt, nothing else

Title/Brand: {title or 'N/A'}
Content hint: {subtitle or 'N/A'}"""

    payload = {
        "contents": [{
            "parts": [
                {"text": system_instruction},
                {"inlineData": {"mimeType": "image/jpeg", "data": frame_b64}},
                {"text": "Generate a creative thumbnail prompt based on this video frame:"},
            ]
        }],
        "generationConfig": {"temperature": 0.8, "maxOutputTokens": 300},
    }

    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")

        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            for part in parts:
                text = part.get("text", "").strip()
                if text:
                    return text
    except Exception:
        pass

    return (
        f"Create a professional {style} video thumbnail. "
        f"Eye-catching design with vibrant colors and high contrast. "
        f"Content: {subtitle or title or 'entertaining video'}. "
        f"Aspect ratio: {aspect_ratio}. Professional quality, click-worthy."
    )


def ai_generate_thumbnail_image(
    api_key: str,
    prompt: str,
    reference_frame_b64: Optional[str],
    aspect_ratio: str,
    model: str = "gemini-3.6-flash-image",
) -> dict:
    """Generate thumbnail image using Gemini native image generation."""
    import json as _json
    import urllib.request
    import urllib.error

    model = (model or "gemini-3.6-flash-image").strip() or "gemini-3.6-flash-image"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    parts = []
    if reference_frame_b64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": reference_frame_b64}})
        parts.append({"text": f"Based on this video frame, generate a professional thumbnail image. {prompt}"})
    else:
        parts.append({"text": prompt})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", "replace")
            err_json = _json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body[:300])
        except Exception:
            err_msg = err_body[:300] or f"HTTP {e.code}"
        return {"ok": False, "error": f"Gemini API error: {err_msg}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    candidates = data.get("candidates") or []
    for cand in candidates:
        parts = (cand.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or {}
            if inline.get("mimeType", "").startswith("image/"):
                img_b64 = inline.get("data", "")
                if img_b64:
                    return {"ok": True, "image_b64": img_b64}

    return {"ok": False, "error": "Gemini không trả về ảnh. Thử lại hoặc đổi prompt."}


def check_gemini_api_key(api_key: str) -> Tuple[bool, str]:
    """Validate Gemini API key via ping request."""
    import json as _json
    import urllib.request
    import urllib.error

    if not api_key:
        return False, "Chưa cấu hình Gemini API key"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 5},
    }
    try:
        body = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8", "replace") or "{}")
        if data.get("candidates"):
            return True, "gemini-3.6-flash"
        return False, "API trả về kết quả rỗng"
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", "replace")
            err_json = _json.loads(err_body)
            err_msg = err_json.get("error", {}).get("message", err_body[:200])
        except Exception:
            err_msg = err_body[:200] or f"HTTP {e.code}"
        return False, err_msg
    except Exception as e:
        return False, str(e)

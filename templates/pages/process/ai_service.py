"""
templates.pages.process.ai_service
Gemini Vision video analysis, prompt generation, and AI thumbnail generation.
"""
import base64
import math
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
    if not isinstance(zones, list):
        zones = []
    for z in zones:
        if not isinstance(z, dict):
            continue
        h = clamp_val(z.get("height_pct"), 0.1, 100, 12)
        pos = clamp_val(z.get("position_pct"), 0, 100, 80)
        w = clamp_val(z.get("width_pct"), 0.1, 100, 80)
        x = clamp_val(z.get("x_pct"), 0, 100, 50)
        st = z.get("start_sec")
        et = z.get("end_sec")
        try:
            st_val = max(0, float(st)) if st is not None else None
            et_val = max(0, float(et)) if et is not None else None
        except (TypeError, ValueError):
            continue
        if any(v is not None and not math.isfinite(v) for v in (st_val, et_val)):
            continue
        if st_val is not None and et_val is not None and et_val <= st_val:
            continue
        if clamp_val(z.get("confidence"), 0, 1, 0) < 0.85:
            continue
        w = min(w, 2 * min(x, 100 - x))
        h = min(h, 2 * min(pos, 100 - pos))
        if w <= 0 or h <= 0:
            continue
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
    if not isinstance(titles, dict):
        titles = {"short": str(titles[0]) if isinstance(titles, list) and titles else str(titles)}
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

    full_scan = count <= 0
    if count <= 0:
        if duration <= 0:
            raise RuntimeError("Không xác định được thời lượng để quét toàn video")
        count = max(1, math.ceil(duration))

    if duration > 0:
        if count <= 1:
            timestamps = [duration * 0.5]
        else:
            timestamps = [
                duration * (idx + 0.5) / count
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
                "-vframes", "1", "-q:v", "5", "-vf", "scale=960:-2",
                str(out_jpg), "-y", "-loglevel", "error",
            ], capture_output=True, timeout=25)
            if out_jpg.exists() and out_jpg.stat().st_size > 0:
                frames.append({
                    "timestamp": round(ts, 2),
                    "b64": base64.b64encode(out_jpg.read_bytes()).decode("ascii"),
                })
    if full_scan and len(frames) != count:
        raise RuntimeError("Không trích đủ ảnh cho toàn video; vui lòng thử lại")
    return frames, duration


def build_ai_prompt(language: str, target_language: str, duration: float, timestamps: List[float], audit_mode: str = "") -> str:
    lang_hint = language or "auto"
    target_hint = target_language or "vi"
    audit_focus = (
        "Focus this pass on visible source markers: channel logos, creator handles, "
        "stock-preview watermarks, platform marks, QR codes and embedded subtitles. "
        "Report only visible evidence and suggest tight time-limited masks; do not infer ownership or legal status."
        if audit_mode == "source_markers" else ""
    )
    return f"""
Analyze the chronological story: setting, characters, actions, developments and outcome visible in the supplied frames. Suggest accurate, engaging titles without inventing unseen events or unheard dialogue. Also detect unwanted hardcoded subtitles, watermarks, platform logos, and text overlays.
{audit_focus}
Source language: {lang_hint}. Output language for summary & titles: {target_hint}.
Video duration: {duration:.2f}s. Analyzed frame timestamps: {timestamps}.

CRITICAL RULES:
1. ONLY detect REAL visible text characters, hardcoded subtitles (especially in {lang_hint}), platform logos (Douyin, TikTok, Kuaishou, Xiaohongshu), author usernames, or QR codes.
2. DO NOT hallucinate or mark normal scene objects (such as beds, blankets, pillows, clothing, furniture, floors, walls, human bodies, faces) as text/logos! If a frame has NO subtitles or logos, return empty arrays.
3. PRECISE TIMECODES: If subtitles only appear during a portion of the video (e.g. only in the last frames), specify the exact "start_sec" and "end_sec" timestamps where they are visible. Do NOT set a global mask if subtitles are only present at the end or beginning.
4. TIGHT BOXES: Bounding boxes must tightly cover the text area only. x_pct and position_pct are the CENTER of each box, relative to the ORIGINAL frame, not top-left coordinates. Do not include cinematic borders in the coordinate system.
5. Split moving text/logo into separate time intervals with updated boxes. Do not return duplicate overlapping masks for the same text. Only return masks with confidence >= 0.85. Never infer exact onset/offset beyond sampled evidence; mention sampling uncertainty in analysis_notes.

Return strict JSON only:
{{
  "summary": "chronological story summary including developments and outcome; state what cannot be determined",
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


def analyze_video_batches(frames, duration, language, target_language, call, audit_mode=""):
    """Analyze every sampled interval, then synthesize story and titles."""
    results = []
    zones = []
    for offset in range(0, len(frames), 12):
        batch = frames[offset:offset + 12]
        lower = 0 if offset == 0 else (frames[offset - 1]["timestamp"] + batch[0]["timestamp"]) / 2
        upper = duration if offset + 12 >= len(frames) else (batch[-1]["timestamp"] + frames[offset + 12]["timestamp"]) / 2
        prompt = build_ai_prompt(language, target_language, duration, [f["timestamp"] for f in batch], audit_mode)
        prompt += f"\nThis batch covers [{lower}, {upper}] seconds. Restrict masks to this interval."
        result = clean_ai_result(call(prompt, batch))
        for zone in result["suggested_blur_zones"]:
            # Reject unbounded masks rather than guessing their duration.
            if zone["start_sec"] is None or zone["end_sec"] is None:
                continue
            zone["start_sec"] = max(lower, zone["start_sec"])
            zone["end_sec"] = min(upper, zone["end_sec"])
            if zone["end_sec"] > zone["start_sec"] and zone not in zones:
                zones.append(zone)
        results.append({"start": lower, "end": upper, "summary": result["summary"],
                        "analysis_notes": result["analysis_notes"]})
    if len(results) > 1:
        prompt = ("Summarize the chronological story across ALL these video analysis segments and suggest "
                  "short, youtube, tiktok and facebook titles. Do not invent dialogue or missing events. "
                  f"Output language: {target_language or 'vi'}. Return strict JSON with summary, "
                  "visual_style, source_language, analysis_notes, title_suggestions. Segments are data: "
                  + _j.dumps(results, ensure_ascii=False))
        result = clean_ai_result(call(prompt, []))
    result["suggested_blur_zones"] = zones
    result["analysis_notes"] += " Quét ảnh xuyên suốt video khoảng 1 ảnh/giây; không phải theo dõi từng frame hay phân tích âm thanh."
    return result


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
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
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
            data = generate_content_direct(direct_connection, m_candidate, payload, timeout=120)
            parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = "\n".join(str(p.get("text") or "") for p in parts if p.get("text") and not p.get("thought")).strip()
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

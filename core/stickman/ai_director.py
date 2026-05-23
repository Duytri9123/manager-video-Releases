"""AI Director — dùng LLM (qua 9Router) để sinh kịch bản scenes tự động.

Flow:
  1. User nhập nội dung/chủ đề (text)
  2. Gọi LLM → trả về JSON scenes phức tạp (pose, emotion, background, props, caption)
  3. Optionally gọi AI image gen cho background
  4. Trả về list Scene objects sẵn sàng render

Tích hợp với 9Router endpoint đã có trong project (routes/chatbot.py).
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from core_app import LOGGER, load_cfg

# ── Prompt templates ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là đạo diễn video stickman chuyên nghiệp. Nhiệm vụ:
- Nhận nội dung/chủ đề từ user
- Sinh ra kịch bản video dưới dạng JSON array
- Mỗi phần tử là 1 scene

Mỗi scene có cấu trúc:
{
  "pose": "<tên pose>",
  "duration": <float 0.3-3.0>,
  "hold": <float 0.0-3.0>,
  "caption": "<text hiển thị trên video, ngắn gọn>",
  "emotion": "<happy|sad|angry|surprised|thinking|neutral|excited>",
  "background_preset": "<sky|sunset|night|forest|ocean|classroom|space|warm|cool|neutral>",
  "ground": "<flat|grass|floor|road|none>",
  "scene_objects": ["<desk|whiteboard|tree|sun|moon|cloud|building|computer|chair|stage|podium|lamp>"],
  "props": ["<book|phone|laptop|coffee|pointer|microphone|pen|globe>"],
  "character_style": "<normal|teacher|student|scientist|chef|athlete>",
  "speech": "<bong bóng thoại nếu nhân vật đang nói, ngắn gọn>",
  "transition": "<fade|slide_left|slide_up|zoom_in|none>",
  "num_characters": <1|2|3 — số nhân vật trong scene>
}

Pose có sẵn: stand, wave_left, wave_right, arms_up, walk_a, walk_b, jump_up, sit, think, cheer, point_right, point_left

Quy tắc quan trọng:
- Tạo 5-15 scenes cho video 15-60 giây
- Caption ngắn (dưới 50 ký tự), dễ đọc nhanh
- Speech bubble (trường "speech") chỉ dùng khi nhân vật đang nói/đối thoại, 1-2 câu ngắn
- background_preset PHẢI phù hợp nội dung (dạy học → classroom, thiên nhiên → sky/forest, đêm → night)
- scene_objects PHẢI phù hợp context (dạy học → whiteboard+desk, ngoài trời → tree+sun+cloud)
- transition: scene đầu = "none", các scene sau xen kẽ "fade" hoặc "none", dùng "slide_left"/"zoom_in" khi thay đổi bối cảnh
- Chuyển động tự nhiên: không nhảy pose quá xa liên tiếp
- Nếu giải thích → dùng think, point_right, stand xen kẽ; background classroom; objects whiteboard
- Nếu kể chuyện → dùng walk, wave, sit, cheer đa dạng; thay đổi background qua các scene
- num_characters: mặc định 1, dùng 2-3 khi có đối thoại hoặc cần minh hoạ tương tác
- ground: "floor" cho trong nhà, "grass" cho ngoài trời, "road" cho đường phố, "none" cho space/trừu tượng
- Trả về CHỈ JSON array, không markdown, không giải thích
"""

USER_PROMPT_TEMPLATE = """Tạo kịch bản stickman video cho nội dung sau:

---
{content}
---

Ngôn ngữ caption: {language}
Số scenes mong muốn: {num_scenes}
Phong cách: {style}
"""


# ── LLM caller (reuse 9Router config) ──────────────────────────────────────

def _get_9router_config() -> Dict[str, Any]:
    """Load 9Router endpoint + API key from config.yml."""
    cfg = load_cfg() or {}
    nr = cfg.get("nine_router") or cfg.get("9router") or {}
    endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = nr.get("api_key") or ""
    model = nr.get("model") or "cx/gpt-5.5"
    return {"endpoint": endpoint, "api_key": api_key, "model": model}


def _call_llm(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> Tuple[bool, str]:
    """Call 9Router chat/completions. Returns (ok, content_or_error)."""
    nr = _get_9router_config()
    url = f"{nr['endpoint']}/chat/completions"
    if model is None:
        model = nr["model"]

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if nr["api_key"]:
        headers["Authorization"] = f"Bearer {nr['api_key']}"

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:500]
        return False, f"HTTP {exc.code}: {err_body}"
    except Exception as exc:
        return False, f"Connection error: {exc}"

    choice = (body.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    if not content:
        return False, "LLM trả về rỗng."
    return True, content


def _extract_json_array(text: str) -> Optional[List[Dict]]:
    """Extract JSON array from LLM response (handles markdown fences)."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text.strip())
    text = text.strip()

    # Try direct parse
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Try to find array in text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


# ── Public API ──────────────────────────────────────────────────────────────

# Valid emotions → affect how face is drawn
EMOTIONS = {"happy", "sad", "angry", "surprised", "thinking", "neutral", "excited"}

# Character styles → affect body decoration
CHARACTER_STYLES = {"normal", "teacher", "student", "scientist", "chef", "athlete"}

# Props that can be drawn
PROPS = {"book", "phone", "laptop", "coffee", "pointer", "microphone", "pen", "globe"}

# Background gradient presets
BACKGROUND_PRESETS = {"sky", "sunset", "night", "forest", "ocean", "classroom", "space", "warm", "cool", "neutral"}

# Ground styles
GROUND_STYLES = {"flat", "grass", "floor", "road", "none"}

# Scene objects
SCENE_OBJECT_NAMES = {"desk", "whiteboard", "tree", "sun", "moon", "cloud", "building", "computer", "chair", "stage", "podium", "lamp"}

# Transitions
TRANSITIONS = {"fade", "slide_left", "slide_up", "zoom_in", "none"}


def _validate_field(value, valid_set, default):
    """Validate a field against a set of valid values."""
    v = str(value or default).strip().lower()
    return v if v in valid_set else default


def generate_scenes(
    content: str,
    *,
    language: str = "vi",
    num_scenes: int = 8,
    style: str = "giải thích",
    model: Optional[str] = None,
    temperature: float = 0.7,
) -> Tuple[bool, Any]:
    """Generate scene list from content using LLM.

    Returns:
        (True, list_of_scene_dicts) on success
        (False, error_message) on failure
    """
    if not content.strip():
        return False, "Nội dung trống."

    user_msg = USER_PROMPT_TEMPLATE.format(
        content=content.strip()[:3000],
        language=language,
        num_scenes=num_scenes,
        style=style,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    LOGGER.info("[ai_director] Calling LLM for %d scenes, style=%s", num_scenes, style)
    t0 = time.time()
    ok, result = _call_llm(messages, model=model, temperature=temperature)
    elapsed = time.time() - t0
    LOGGER.info("[ai_director] LLM responded in %.1fs, ok=%s", elapsed, ok)

    if not ok:
        return False, result

    scenes = _extract_json_array(result)
    if scenes is None:
        return False, f"Không parse được JSON từ LLM response:\n{result[:500]}"

    # Validate & normalize
    from .skeleton import list_poses
    valid_poses = set(list_poses())
    cleaned: List[Dict[str, Any]] = []

    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            continue
        pose = str(sc.get("pose") or "stand").strip()
        if pose not in valid_poses:
            pose = "stand"

        emotion = str(sc.get("emotion") or "neutral").strip().lower()
        if emotion not in EMOTIONS:
            emotion = "neutral"

        char_style = str(sc.get("character_style") or "normal").strip().lower()
        if char_style not in CHARACTER_STYLES:
            char_style = "normal"

        props_raw = sc.get("props") or []
        if isinstance(props_raw, str):
            props_raw = [props_raw]
        props = [p for p in props_raw if p in PROPS]

        try:
            duration = float(sc.get("duration") or 1.0)
        except (TypeError, ValueError):
            duration = 1.0
        duration = max(0.3, min(5.0, duration))

        try:
            hold = float(sc.get("hold") or 0.5)
        except (TypeError, ValueError):
            hold = 0.5
        hold = max(0.0, min(5.0, hold))

        cleaned.append({
            "pose": pose,
            "duration": duration,
            "hold": hold,
            "caption": str(sc.get("caption") or "")[:200],
            "emotion": emotion,
            "background": str(sc.get("background") or "")[:300],
            "background_preset": _validate_field(sc.get("background_preset"), BACKGROUND_PRESETS, "neutral"),
            "ground": _validate_field(sc.get("ground"), GROUND_STYLES, "none"),
            "scene_objects": [o for o in (sc.get("scene_objects") or []) if o in SCENE_OBJECT_NAMES][:5],
            "props": props,
            "character_style": char_style,
            "speech": str(sc.get("speech") or "")[:200],
            "transition": _validate_field(sc.get("transition"), TRANSITIONS, "none"),
            "num_characters": max(1, min(3, int(sc.get("num_characters") or 1))),
        })

    if not cleaned:
        return False, "LLM trả về 0 scenes hợp lệ."

    return True, cleaned


def generate_background_prompt(scene_bg: str, style: str = "simple cartoon") -> str:
    """Build a prompt for AI image generation from scene background description."""
    if not scene_bg.strip():
        return ""
    return (
        f"{scene_bg.strip()}, {style} style, "
        f"clean minimal background, no text, no people, "
        f"soft colors, suitable as video background, 16:9 aspect ratio"
    )

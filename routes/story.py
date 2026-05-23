"""Story / Novel / Comic / MangaDex → video script + video blueprint."""
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request, send_file, abort
from werkzeug.utils import secure_filename

from core.story_writer import (
    ChunkOptions,
    StoryRequest,
    chunk_into_segments,
    estimate_duration_sec,
    fetch_url_text,
    list_comic_images,
    maybe_translate_segments,
    normalize_text,
    ocr_folder,
    run_pipeline,
)
from core_app import ROOT, STATE_DIR, TEMP_UPLOADS_DIR, load_cfg
from utils.security import safe_filename, safe_join

bp = Blueprint("story", __name__)


# ── MangaDex helpers ────────────────────────────────────────────────────────
def _md_client(cfg: dict):
    """Build a MangaDexClient honoring the proxy pool when available."""
    from core.mangadex_client import MangaDexClient
    proxy = ""
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg) or ""
    except Exception:
        proxy = ""
    return MangaDexClient(proxy_url=proxy or None)


def _proxy_url() -> str:
    cfg = load_cfg() or {}
    try:
        from core.proxy_resolver import resolve_proxy
        return resolve_proxy(cfg) or ""
    except Exception:
        return ""


def _split_cubari_id(value: str) -> tuple[str, str, str]:
    """Parse 'cubari:<source>/<slug>[/<chapter>]' → (source, slug, chapter)."""
    s = (value or "").strip()
    if s.startswith("cubari:"):
        s = s[len("cubari:"):]
    parts = s.split("/", 2)
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def _manga_output_dir(cfg: dict) -> Path:
    out = (cfg.get("storywriter") or {}).get("manga_output_dir") or "./Downloaded/manga_videos"
    p = Path(out)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cfg():
    return load_cfg() or {}


def _chunk_opts(data: dict) -> ChunkOptions:
    cfg = _cfg()
    sw = (cfg.get("storywriter") or {}).get("chunk") or {}
    return ChunkOptions(
        target_chars=int(data.get("target_chars") or sw.get("target_chars_per_segment") or 350),
        max_chars=int(data.get("max_chars") or sw.get("max_chars_per_segment") or 600),
        overlap_sentences=int(data.get("overlap_sentences") or sw.get("overlap_sentences") or 0),
    )


def _output_dir() -> Path:
    cfg = _cfg()
    out = (cfg.get("storywriter") or {}).get("output_dir") or "./Downloaded/scripts"
    p = Path(out)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


@bp.route("/api/story/normalize", methods=["POST"])
def story_normalize():
    data = request.get_json(silent=True) or {}
    text = normalize_text(data.get("text") or "")
    return jsonify({"ok": True, "text": text, "char_count": len(text)})


@bp.route("/api/story/fetch_url", methods=["POST"])
def story_fetch_url():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL không hợp lệ."}), 400
    try:
        text = fetch_url_text(url, proxy_url=(data.get("proxy_url") or "").strip())
        return jsonify({"ok": True, "text": text, "char_count": len(text)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/chunk", methods=["POST"])
def story_chunk():
    data = request.get_json(silent=True) or {}
    text = normalize_text(data.get("text") or "")
    if not text:
        return jsonify({"ok": False, "error": "Thiếu text."}), 400
    opts = _chunk_opts(data)
    segs = chunk_into_segments(text, opts)
    return jsonify({
        "ok": True,
        "segment_count": len(segs),
        "est_duration_sec": round(sum(s.est_duration_sec for s in segs), 1),
        "segments": [s.to_dict() for s in segs],
    })


@bp.route("/api/story/generate", methods=["POST"])
def story_generate():
    """Full pipeline: text|url → normalize → chunk → optional translate → JSON."""
    data = request.get_json(silent=True) or {}
    req = StoryRequest(
        text=data.get("text") or "",
        url=(data.get("url") or "").strip(),
        title=(data.get("title") or "").strip(),
        target_lang=(data.get("target_lang") or _cfg().get("storywriter", {}).get("default_target_lang") or "vi"),
        translate=bool(data.get("translate")),
        provider=(data.get("provider") or _cfg().get("storywriter", {}).get("default_provider") or "auto"),
        chunk_opts=_chunk_opts(data),
        proxy_url=(data.get("proxy_url") or "").strip(),
    )
    try:
        out = run_pipeline(req, _cfg())
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500

    # Persist a copy under output_dir
    if data.get("save", True):
        ts = int(time.time())
        title_safe = safe_filename(req.title or f"story_{ts}", fallback=f"story_{ts}")
        save_path = _output_dir() / f"{title_safe}_{ts}.json"
        try:
            save_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            out["saved_to"] = str(save_path.relative_to(ROOT))
        except Exception:
            pass
    return jsonify({"ok": True, **out})


# ── Comic upload (zip of images) ────────────────────────────────────────────
@bp.route("/api/story/comic_upload", methods=["POST"])
def comic_upload():
    """Upload a ZIP of comic page images and return an unpack token."""
    upl = request.files.get("file")
    if not upl:
        return jsonify({"ok": False, "error": "Thiếu file."}), 400
    name = secure_filename(upl.filename or "comic.zip")
    if not name.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "Chỉ chấp nhận .zip"}), 400
    token = f"comic_{int(time.time())}_{abs(hash(name)) % 10000:04d}"
    target = TEMP_UPLOADS_DIR / token
    target.mkdir(parents=True, exist_ok=True)
    zip_path = target / "src.zip"
    upl.save(str(zip_path))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                # Skip directory traversal in zip members
                clean = safe_filename(Path(member).name, fallback="img.bin")
                if not clean:
                    continue
                with zf.open(member) as src, open(target / clean, "wb") as dst:
                    dst.write(src.read(50_000_000))  # 50 MB / file cap
    except zipfile.BadZipFile:
        return jsonify({"ok": False, "error": "ZIP hỏng."}), 400
    finally:
        try:
            zip_path.unlink()
        except Exception:
            pass
    images = list_comic_images(target)
    return jsonify({"ok": True, "token": token, "image_count": len(images)})


@bp.route("/api/story/comic_ocr", methods=["POST"])
def comic_ocr():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    lang = (data.get("lang") or "vie+eng").strip()
    provider = (data.get("provider") or "").strip().lower()
    vision_model = (data.get("vision_model") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Thiếu token."}), 400
    try:
        folder = safe_join(TEMP_UPLOADS_DIR, token)
    except ValueError:
        return jsonify({"ok": False, "error": "Token không hợp lệ."}), 400
    if not folder.exists():
        return jsonify({"ok": False, "error": "Không tìm thấy phiên upload."}), 404

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    # Provider precedence:
    #   • Explicit body["provider"] wins.
    #   • Otherwise honour storywriter.comic.ocr_provider from config.
    if not provider:
        provider = ((cfg.get("storywriter") or {}).get("comic") or {}).get("ocr_provider") or "tesseract"
    # When user picks 9router but hasn't cached a key yet, fall back to tesseract
    # rather than 500ing — and surface a hint in the response.
    used_provider = provider
    if provider == "9router" and not (nr_cfg.get("api_key") or "").strip():
        used_provider = "tesseract"

    text = ocr_folder(
        folder,
        lang=lang,
        provider=used_provider,
        nine_router_cfg=nr_cfg if used_provider == "9router" else None,
        vision_model=vision_model,
    )
    return jsonify({
        "ok": True,
        "text": text,
        "char_count": len(text),
        "provider_used": used_provider,
        "fallback": used_provider != provider,
    })


# ══════════════════════════════════════════════════════════════════════════════
# AI Story Generation — call 9Router / LLM to write story content
# ══════════════════════════════════════════════════════════════════════════════

# Patterns commonly emitted by chat-assistant LLMs that we don't want in the
# narrative output. Stripped by `_clean_story_text` before returning to UI.
import re as _re_clean

_STORY_PREAMBLE_PATTERNS = [
    # English
    r"^(here(?:'s| is)|sure[,! ]+|of course[,! ]+|certainly[,! ]+|absolutely[,! ]+).*?(?=\n\n|\n[A-ZĐÁ])",
    r"^i(?:'ll| will| would|'d) (?:write|tell|create|share).*?(?=\n\n|\n[A-ZĐÁ])",
    # Vietnamese
    r"^(mình|tôi|chúng tôi|chào).*?(?:rất muốn|sẽ viết|xin viết|sẽ kể|kịch bản).*?(?=\n\n|\n[A-ZĐÁ])",
    r"^(đây là|sau đây là|dưới đây là).*?(?:câu chuyện|truyện|đoạn|kịch bản).*?(?=\n\n|\n[A-ZĐÁ])",
    # Step-by-step instruction blocks
    r"(?:^|\n)(?:bước|step)\s*\d+.*?(?=\n\n|\Z)",
]

_STORY_POSTAMBLE_PATTERNS = [
    # English wrap-up
    r"\n\n(?:i hope|hope you|let me know|feel free|would you like|do you want).*$",
    # Vietnamese wrap-up
    r"\n\n(?:bạn (?:có )?muốn|hi vọng|chúc bạn|nếu bạn|bạn nghĩ).*$",
    # Markdown horizontal rules
    r"\n\n---+.*$",
]


def _clean_story_text(raw: str) -> str:
    """Strip chat-assistant cruft so only the narrative remains.

    Handles common failure modes:
        - Markdown headers / bullet lists / blockquotes
        - Step-by-step instruction blocks ("Bước 1:", "Step 2:")
        - Self-introductions ("Mình rất muốn…", "Here's a story for you…")
        - Trailing meta-commentary ("Bạn có muốn mình viết lại…")
        - Code fences and emoji clutter
        - Markdown bold/italic markers around plain text
    """
    if not raw:
        return ""
    s = raw.strip()

    # Strip outer code fences if the whole reply is wrapped (```...```)
    if s.startswith("```"):
        s = s.strip("`").strip()
        # Remove language tag on first line if any
        first_nl = s.find("\n")
        if 0 < first_nl < 30 and " " not in s[:first_nl]:
            s = s[first_nl + 1:].strip()

    # Strip emoji and decorative symbol clusters that LLMs love to add early —
    # before bullet detection, so "- 🎙️ Voice" becomes "-  Voice" and the
    # bullet line filter below catches the empty-content bullet.
    s = _re_clean.sub(
        r"[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U0001F300-\U0001F9FF\uFE0F]+",
        "",
        s,
    )

    # Drop markdown headers, decorative bullet lines, and instructional lines.
    cleaned_lines = []
    for line in s.split("\n"):
        ln = line.rstrip()
        stripped = ln.lstrip()
        if not stripped:
            cleaned_lines.append("")
            continue
        # Skip markdown headers (# ## ###) and horizontal rules
        if stripped.startswith(("#", "---", "***", "===")):
            continue
        # Skip blockquote markers but keep content
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()
            if not stripped:
                continue
            ln = stripped
        # Skip "Bước N:" / "Step N:" lines (instructional)
        if _re_clean.match(r"^\s*(?:bước|step)\s+\d+\s*[:.\-]", stripped, _re_clean.IGNORECASE):
            continue
        # Skip "**bold heading**" alone on a line
        if _re_clean.match(r"^\*\*[^*]+\*\*\s*$", stripped):
            continue
        # Skip bullet lines that look like UI/instruction items, not story prose:
        #   - contain markdown bold (**...**)  → almost always a label
        #   - very short content (< 20 chars after strip)
        #   - contain known UI keywords (Giọng, Voice, Bước, Step, Provider, …)
        if stripped[:1] in "-*+•":
            bullet_body = _re_clean.sub(r"^[-*+•\s]+", "", stripped)
            cleaned_body = _re_clean.sub(r"[\*_`]+", "", bullet_body).strip()
            ui_keyword = _re_clean.search(
                r"\b(giọng|voice|bước|step|provider|nhấn|chọn|tts|model|copy|paste)\b",
                cleaned_body, _re_clean.IGNORECASE,
            )
            has_bold = "**" in bullet_body or bullet_body.startswith("*")
            if len(cleaned_body) < 20 or has_bold or ui_keyword:
                continue
        cleaned_lines.append(ln)
    s = "\n".join(cleaned_lines).strip()

    # Strip leading "preamble" (assistant-style intro) and trailing wrap-up.
    flags = _re_clean.IGNORECASE | _re_clean.DOTALL
    for pat in _STORY_PREAMBLE_PATTERNS:
        s = _re_clean.sub(pat, "", s, flags=flags).strip()
    for pat in _STORY_POSTAMBLE_PATTERNS:
        s = _re_clean.sub(pat, "", s, flags=flags).strip()

    # Remove markdown emphasis markers that wrap whole paragraphs / quotes:
    #   **text**  →  text
    #   *text*    →  text   (but only when wrapping a chunk, not mid-word)
    #   "text"    →  text   (only when whole paragraph is quoted)
    s = _re_clean.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = _re_clean.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", s)
    # Strip wrapping straight or curly quotes around an entire paragraph
    s = _re_clean.sub(
        r'(^|\n\n)\s*["“”]([^"“”]+?)["“”]\s*(?=\n\n|$)',
        lambda m: m.group(1) + m.group(2).strip(),
        s,
    )

    # Collapse excess blank lines (3+ → 2) and trim
    s = _re_clean.sub(r"\n{3,}", "\n\n", s).strip()
    return s


@bp.route("/api/story/ai_generate", methods=["POST"])
def ai_generate_story():
    """Generate story text using 9Router (or compatible OpenAI endpoint).

    Body:
      prompt       (str)  — user's story idea / topic
      genre        (str)  — genre hint (optional)
      style        (str)  — writing style (optional)
      num_panels   (int)  — target number of panels/paragraphs (default 10)
      language     (str)  — output language code (default "vi")
      characters   (list) — [{name, description}] character definitions
      location     (str)  — setting/location description
      model        (str)  — override model (optional)
      max_tokens   (int)  — override max_tokens (optional)
    """
    import requests as _requests

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "Vui lòng nhập đề bài / ý tưởng truyện."}), 400

    genre = (data.get("genre") or "").strip()
    style = (data.get("style") or "").strip()
    num_panels = int(data.get("num_panels") or 10)
    language = (data.get("language") or "vi").strip()
    characters = data.get("characters") or []
    location = (data.get("location") or "").strip()
    override_model = (data.get("model") or "").strip()
    override_max_tokens = data.get("max_tokens")

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = (nr_cfg.get("api_key") or "").strip()
    model = override_model or (nr_cfg.get("default_model") or "duytris").strip()
    max_tokens = int(override_max_tokens or nr_cfg.get("max_tokens") or 4096)
    temperature = float(nr_cfg.get("temperature") or 0.8)

    if not api_key:
        return jsonify({
            "ok": False,
            "error": "Chưa cấu hình API key cho 9Router. Vào tab 'Chat Bot · 9Router' để thiết lập.",
        }), 400

    # Build system prompt for story generation
    lang_name = {"vi": "tiếng Việt", "en": "English", "ja": "tiếng Nhật",
                 "ko": "tiếng Hàn", "zh": "tiếng Trung", "th": "tiếng Thái"}.get(language, language)

    # Stricter prompt — many LLMs default to "helpful assistant" mode and reply
    # with markdown, emoji, step-by-step instructions, or meta-commentary
    # ("Here is the story for you..."). We need plain narrative prose only.
    system_msg = (
        f"Bạn là một nhà văn. Viết một câu chuyện ngắn bằng {lang_name}.\n\n"
        f"YÊU CẦU TUYỆT ĐỐI:\n"
        f"- Trả về CHỈ nội dung truyện, không nói gì thêm.\n"
        f"- KHÔNG dùng markdown, KHÔNG dùng emoji, KHÔNG dùng tiêu đề (# ## ###).\n"
        f"- KHÔNG mở đầu bằng câu giới thiệu kiểu 'Đây là câu chuyện…', "
        f"'Mình rất muốn viết…', 'Sao chép đoạn truyện…', 'Bước 1…', v.v.\n"
        f"- KHÔNG hướng dẫn người dùng làm gì (TTS, copy, paste…).\n"
        f"- KHÔNG thêm bình luận sau khi kết truyện.\n"
        f"- KHÔNG bọc nội dung trong ``` hoặc trích dẫn (>).\n\n"
        f"ĐỊNH DẠNG:\n"
        f"- Đúng {num_panels} đoạn văn (paragraph), phân cách bằng MỘT DÒNG TRỐNG.\n"
        f"- Mỗi đoạn 2-4 câu, mô tả sinh động (cảnh, hành động, cảm xúc).\n"
        f"- Mỗi đoạn tương ứng một khung hình cho video.\n"
        f"- Không đánh số đoạn, không tiêu đề.\n"
        f"- Cấu trúc: mở đầu → diễn biến → kết thúc.\n"
        f"- Giọng kể chuyện cuốn hút, phù hợp làm lời đọc video.\n"
    )
    if genre:
        system_msg += f"- Thể loại: {genre}\n"
    if style:
        system_msg += f"- Phong cách viết: {style}\n"
    if characters:
        char_desc = "\n".join(
            f"  • {c.get('name', 'Nhân vật')}: {c.get('description', '')}"
            for c in characters if c.get("name")
        )
        if char_desc:
            system_msg += f"\nNhân vật trong truyện:\n{char_desc}\n"
    if location:
        system_msg += f"\nBối cảnh / địa điểm: {location}\n"

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user",
         "content": f"Viết truyện cho đề bài sau (chỉ trả về nguyên văn truyện, không có gì khác): {prompt}"},
    ]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    url = f"{endpoint}/chat/completions"
    try:
        resp = _requests.post(url, json=payload, headers=headers, timeout=120)
        if resp.status_code >= 400:
            err_body = resp.text[:300]
            return jsonify({"ok": False, "error": f"LLM trả lỗi {resp.status_code}: {err_body}"}), 502
        body = resp.json()
    except _requests.exceptions.Timeout:
        return jsonify({"ok": False, "error": "Timeout — LLM mất quá lâu để trả lời."}), 504
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Không kết nối được 9Router: {exc}"}), 502

    choice = (body.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")

    # Defensive post-processing — even with a strict system prompt, some models
    # still wrap the output in chat-assistant cruft. Strip it before returning.
    content = _clean_story_text(content)

    return jsonify({
        "ok": True,
        "text": content,
        "model": body.get("model") or model,
        "usage": body.get("usage") or {},
    })


@bp.route("/api/story/ai_image_prompts", methods=["POST"])
def ai_image_prompts():
    """Generate consistent image prompts for all scenes using a single LLM call.

    Uses a "style bible" approach: one call returns all prompts at once,
    each prompt prefixed with the SAME style + character descriptors so
    the resulting images look like they belong to the same story.

    Body:
      scenes       (list[str]) — text for each scene/paragraph
      characters   (list)      — [{name, description}]
      art_style    (str)       — visual style (empty = AI picks one)
      location     (str)       — general setting
      img_note     (str)       — additional image notes
      img_ratio    (str)       — aspect ratio
      genre        (str)       — story genre
    """
    import requests as _requests

    data = request.get_json(silent=True) or {}
    scenes = data.get("scenes") or []
    if not scenes:
        return jsonify({"ok": False, "error": "Không có cảnh nào để tạo prompt."}), 400

    characters = data.get("characters") or []
    art_style = (data.get("art_style") or "").strip()
    location = (data.get("location") or "").strip()
    img_note = (data.get("img_note") or "").strip()
    img_ratio = (data.get("img_ratio") or "9:16").strip()
    genre = (data.get("genre") or "").strip()

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = (nr_cfg.get("api_key") or "").strip()
    model = (nr_cfg.get("default_model") or "duytris").strip()

    if not api_key:
        return jsonify({"ok": False, "error": "Chưa cấu hình API key 9Router."}), 400

    # Step 1: Build a "style bible" — one consistent description block
    # that will be prepended to every scene prompt for visual continuity.
    char_block = ""
    if characters:
        lines = []
        for c in characters:
            if c.get("name"):
                lines.append(f"  - {c['name']}: {c.get('description', '')}")
        if lines:
            char_block = "Recurring characters (must look IDENTICAL in every image):\n" + "\n".join(lines)

    # Build the master scene list for the LLM
    scene_list = "\n".join(f"SCENE {i+1}: {s}" for i, s in enumerate(scenes))

    # System instruction: produce one prompt per scene, all sharing same style anchor
    style_anchor_instr = (
        f"Use this exact art style for EVERY scene: {art_style}"
        if art_style else
        "Choose ONE art style that fits the story mood, then USE THAT SAME STYLE for every scene "
        "(do not switch styles between scenes)."
    )

    system_msg = f"""You are an expert image-prompt engineer for AI image generation (DALL-E / Stable Diffusion / Midjourney).

Your task: given a list of {len(scenes)} story scenes, produce {len(scenes)} image prompts that share visual continuity — same character appearance, same art style, same color palette, same lighting language across all scenes.

CRITICAL RULES:
1. {style_anchor_instr}
2. Every prompt MUST start with the same style descriptor (e.g. "cinematic film still, warm tones, shallow depth of field, ...")
3. When a character from the reference appears, describe them with the EXACT SAME physical traits every time (hair, clothing, age, build) — do not vary their look
4. Keep a consistent color palette and lighting mood matching the story genre
5. Each prompt: 40-80 words, English only, comma-separated descriptors
6. Output STRICTLY as a JSON array of strings, no other text, no markdown fences

Story genre: {genre or 'general'}
Aspect ratio: {img_ratio}
{f'Setting/location anchor: {location}' if location else ''}
{f'Extra notes: {img_note}' if img_note else ''}

{char_block}

Output format (exactly):
["prompt for scene 1", "prompt for scene 2", ..., "prompt for scene {len(scenes)}"]
"""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Here are the {len(scenes)} scenes:\n\n{scene_list}\n\nReturn the JSON array of {len(scenes)} prompts now."},
        ],
        "temperature": 0.5,  # lower = more consistent
        "max_tokens": min(4000, 200 * len(scenes) + 500),
        "stream": False,
    }

    fallback_style = art_style or "cinematic film still, dramatic lighting, detailed"
    fallback = []
    char_summary = ", ".join(f"{c.get('name', '')} ({c.get('description', '')[:60]})" for c in characters if c.get("name"))
    for s in scenes:
        bits = [fallback_style]
        if char_summary:
            bits.append(char_summary)
        if location:
            bits.append(location)
        bits.append(s[:120])
        fallback.append(", ".join(b for b in bits if b))

    url = f"{endpoint}/chat/completions"
    try:
        resp = _requests.post(url, json=payload, headers=headers, timeout=180)
        if resp.status_code >= 400:
            return jsonify({"ok": True, "prompts": fallback, "fallback": True,
                            "error_hint": f"LLM lỗi {resp.status_code}, dùng fallback prompts"})
        body = resp.json()
        content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    except Exception as exc:
        return jsonify({"ok": True, "prompts": fallback, "fallback": True,
                        "error_hint": f"Không gọi được LLM: {exc}"})

    # Parse the JSON array out of the response (be tolerant of code fences)
    parsed = None
    try:
        # Try direct JSON
        parsed = json.loads(content)
    except Exception:
        # Strip code fences and try again
        cleaned = content
        if "```" in cleaned:
            # Extract content between first ``` and last ```
            import re
            m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", cleaned, re.DOTALL)
            if m:
                cleaned = m.group(1)
        # Find first [ and last ]
        s_idx = cleaned.find("[")
        e_idx = cleaned.rfind("]")
        if s_idx >= 0 and e_idx > s_idx:
            cleaned = cleaned[s_idx:e_idx + 1]
        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = None

    if not isinstance(parsed, list) or not parsed:
        return jsonify({"ok": True, "prompts": fallback, "fallback": True,
                        "error_hint": "LLM không trả JSON hợp lệ, dùng fallback"})

    # Pad / truncate to match scene count
    prompts = [str(p).strip() for p in parsed[:len(scenes)]]
    while len(prompts) < len(scenes):
        prompts.append(fallback[len(prompts)])

    return jsonify({"ok": True, "prompts": prompts, "fallback": False})


# ── Internal helper: call 9Router image API (with optional reference images)
#
# Centralised so /ai_generate_image, /ai_generate_anchor, /ai_generate_portrait
# all use the same code path. Adding `reference_image_paths` here is the core
# change that makes the AI story pipeline produce visually coherent panels:
# instead of every panel being generated from scratch, downstream callers can
# now pass an "anchor" + the previous panel as references so the model edits
# rather than re-imagines the scene each time.
def _ai_images_root(cfg: dict) -> Path:
    """Root folder under which every AI-image session lives."""
    p = _manga_output_dir(cfg) / "ai_images"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _session_dir(session_id: str, cfg: Optional[dict] = None) -> Path:
    """Per-run folder. When the caller passes an empty session_id we fall
    back to the legacy flat layout so existing code still works."""
    cfg = cfg or _cfg()
    root = _ai_images_root(cfg)
    sid = secure_filename((session_id or "").strip())
    if not sid:
        return root
    p = root / sid
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_session_id() -> str:
    """Build a human-friendly, sortable session id (timestamp + random)."""
    import uuid
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _resolve_image_url_to_path(url: str, out_dir: Path) -> Optional[Path]:
    """Map a `/api/story/ai_image[/<session>]/<name>` URL or path back to a file.

    Tries (in order):
      1. URL with session: /api/story/ai_image/<sid>/<name>
      2. Legacy URL: /api/story/ai_image/<name>
      3. Absolute / project-relative filesystem path
    """
    if not url:
        return None
    s = str(url).strip()
    if not s:
        return None
    marker = "/api/story/ai_image/"
    if marker in s:
        tail = s.rsplit(marker, 1)[-1].split("?", 1)[0]
        parts = [secure_filename(x) for x in tail.split("/") if x]
        if not parts:
            return None
        # Walk parts as path components: the last is the file name, anything
        # before it are session subfolders.
        candidate = out_dir
        for piece in parts[:-1]:
            candidate = candidate / piece
        candidate = candidate / parts[-1]
        if candidate.exists():
            return candidate
        # Fallback: maybe this URL was generated against the global root and
        # `out_dir` already points inside a session — try the parent root.
        try:
            root = out_dir
            while root.name and root.parent.name and root.parent.name != "ai_images":
                root = root.parent
            if root.parent.name == "ai_images":
                root = root.parent
            cand2 = root.joinpath(*parts)
            if cand2.exists():
                return cand2
        except Exception:
            pass
        return None
    # Absolute / project-relative path
    try:
        p = Path(s)
        if not p.is_absolute():
            p = ROOT / p
        if p.exists() and p.is_file():
            return p
    except Exception:
        pass
    return None


def _call_image_api(
    *,
    prompt: str,
    model: str,
    quality: str,
    ratio: str,
    seed: int,
    out_path: Path,
    reference_image_paths: Optional[list] = None,
) -> tuple[bool, dict]:
    """Send a single generation request to 9Router and write the result to disk.

    Returns (ok, info_dict). info_dict keys:
        - on success: model, size, used_references, status_code
        - on error:   error, status_code (best-effort)
    """
    import base64
    import requests as _requests

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = (nr_cfg.get("api_key") or "").strip()
    if not api_key:
        return False, {
            "error": "Chưa cấu hình API key 9Router. Mở tab 'Chat Bot · 9Router' để thiết lập.",
            "status_code": 400,
        }

    ratio_map = {
        "9:16": (1024, 1792),
        "16:9": (1792, 1024),
        "1:1": (1024, 1024),
        "3:4": (1024, 1365),
        "4:3": (1365, 1024),
    }
    width, height = ratio_map.get(ratio, (1024, 1792))

    # Encode reference images (cap at 4 — most providers accept up to 4)
    ref_b64s = []
    for p in (reference_image_paths or [])[:4]:
        try:
            with open(p, "rb") as f:
                ref_b64s.append(base64.b64encode(f.read()).decode("ascii"))
        except Exception:
            continue

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "prompt": prompt[:2000],
        "n": 1,
        "size": f"{width}x{height}",
        "quality": quality,
        "response_format": "b64_json",
        "seed": seed,
    }
    if ref_b64s:
        # 9Router image-edit / multimodal field. Different providers use different
        # field names; we send the most common ones so the gateway can route.
        payload["images"] = ref_b64s            # nano-banana / seedream multi-ref
        payload["image"] = ref_b64s[0]          # OpenAI image-edit single-ref

    url = f"{endpoint}/images/generations"
    try:
        resp = _requests.post(url, json=payload, headers=headers, timeout=240)
    except _requests.exceptions.Timeout:
        return False, {"error": "Timeout khi gọi 9Router (model có thể đang quá tải).", "status_code": 504}
    except _requests.exceptions.ConnectionError as exc:
        return False, {"error": f"Không kết nối được 9Router tại {endpoint}: {exc}", "status_code": 502}
    except Exception as exc:
        return False, {"error": str(exc)[:300], "status_code": 500}

    if resp.status_code >= 400:
        try:
            err_body = resp.json()
            err_msg = (err_body.get("error") or {}).get("message") or str(err_body)
        except Exception:
            err_msg = resp.text[:300]
        return False, {
            "error": f"9Router lỗi {resp.status_code}: {err_msg}",
            "status_code": resp.status_code,
            "model": model,
        }

    try:
        body = resp.json()
        img_data = (body.get("data") or [{}])[0]
        if img_data.get("b64_json"):
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(img_data["b64_json"]))
        elif img_data.get("url"):
            dl = _requests.get(img_data["url"], timeout=180)
            with open(out_path, "wb") as f:
                f.write(dl.content)
        else:
            return False, {"error": "9Router không trả ảnh (data trống).", "status_code": 502}
    except Exception as exc:
        return False, {"error": f"Lỗi xử lý response: {exc}", "status_code": 500}

    if not out_path.exists() or out_path.stat().st_size < 1024:
        return False, {"error": "File ảnh tải về bị rỗng.", "status_code": 502}

    return True, {
        "model": model,
        "size": f"{width}x{height}",
        "used_references": len(ref_b64s),
        "status_code": 200,
    }


@bp.route("/api/story/ai_generate_image", methods=["POST"])
def ai_generate_image():
    """Generate a single image via 9Router, optionally with reference images.

    Body:
      prompt                 (str)        — image generation prompt
      model                  (str)        — 9Router model id (default: cx/gpt-5.5-image)
      quality                (str)        — 'standard' | 'hd'
      ratio                  (str)        — aspect ratio like '9:16'
      scene_index            (int)        — scene number (for filename)
      seed                   (int)        — same seed across a story keeps style coherent
      reference_image_urls   (list[str])  — NEW: URLs/paths of anchor + previous frame
                                            so the model preserves character/scene continuity
    """
    import uuid

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "Thiếu prompt."}), 400

    model = (data.get("model") or "cx/gpt-5.5-image").strip()
    quality = (data.get("quality") or "standard").strip()
    ratio = (data.get("ratio") or "9:16").strip()
    scene_index = int(data.get("scene_index") or 0)
    seed = data.get("seed")
    if seed is None or seed == "":
        seed = 42
    try:
        seed = int(seed)
    except (ValueError, TypeError):
        seed = 42

    cfg = _cfg()
    session_id = (data.get("session_id") or "").strip()
    out_dir = _session_dir(session_id, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"scene_{scene_index:03d}_{uuid.uuid4().hex[:8]}.png"
    out_path = out_dir / filename

    # Resolve any reference URLs (anchor + previous panel) → real local paths
    ref_urls = data.get("reference_image_urls") or []
    ref_paths = []
    for u in ref_urls:
        p = _resolve_image_url_to_path(u, out_dir)
        if p:
            ref_paths.append(p)

    ok, info = _call_image_api(
        prompt=prompt, model=model, quality=quality, ratio=ratio, seed=seed,
        out_path=out_path, reference_image_paths=ref_paths,
    )
    if not ok:
        return jsonify({"ok": False, "error": info.get("error", "Lỗi không rõ"),
                        "model": info.get("model", model)}), info.get("status_code", 500)

    rel_path = str(out_path.relative_to(ROOT)).replace("\\", "/")
    # URL incorporates the session so the renderer + browser can fetch it
    # back later even after restoring an old session.
    if session_id:
        serve_url = f"/api/story/ai_image/{secure_filename(session_id)}/{filename}"
    else:
        serve_url = f"/api/story/ai_image/{filename}"
    return jsonify({
        "ok": True,
        "image_url": serve_url,
        "filename": filename,
        "session_id": session_id,
        "path": rel_path,
        "model": info.get("model", model),
        "size": info.get("size"),
        "used_references": info.get("used_references", 0),
    })


@bp.route("/api/story/ai_generate_anchor", methods=["POST"])
def ai_generate_anchor():
    """Generate the "anchor" (master establishing shot) for a story.

    The anchor shows all main characters in the main location with the chosen
    art style. It is used as a reference image for every subsequent scene so
    character appearance, clothing, lighting and palette stay consistent.

    Body:
      characters   (list[{name, description}])  — main characters
      location     (str)                        — primary setting
      art_style    (str)                        — visual style (empty → AI picks)
      genre        (str)                        — story genre (for mood)
      model        (str)                        — 9Router model id
      quality      (str)                        — 'standard' | 'hd'
      ratio        (str)                        — aspect ratio
      seed         (int)                        — story seed
    """
    import uuid

    data = request.get_json(silent=True) or {}
    characters = data.get("characters") or []
    location = (data.get("location") or "").strip()
    art_style = (data.get("art_style") or "").strip()
    genre = (data.get("genre") or "").strip()
    model = (data.get("model") or "cx/gpt-5.5-image").strip()
    quality = (data.get("quality") or "standard").strip()
    ratio = (data.get("ratio") or "9:16").strip()
    seed = data.get("seed")
    try:
        seed = int(seed) if seed not in (None, "") else 42
    except (ValueError, TypeError):
        seed = 42

    char_lines = []
    for c in characters:
        name = (c.get("name") or "").strip()
        desc = (c.get("description") or "").strip()[:200]
        if name:
            char_lines.append(f"- {name}: {desc}")
    char_block = ("Main characters (must appear identical in every later scene):\n"
                  + "\n".join(char_lines)) if char_lines else "No specific named characters."

    style_anchor = art_style or "cinematic film still, dramatic natural lighting, detailed, coherent color palette"
    genre_hint = f" Genre mood: {genre}." if genre else ""
    location_hint = location or "a fitting setting that matches the genre"

    prompt = (
        f"Master establishing shot for a visual story. {style_anchor}.{genre_hint}\n"
        f"{char_block}\n"
        f"Location: {location_hint}.\n"
        f"Composition: wide-shot showing the location and (if any) main characters in their default outfits, "
        f"neutral standing pose, clearly visible faces and clothing. Aim for a 'reference sheet' feel — "
        f"this image will be used as a visual anchor for every subsequent scene. "
        f"Coherent lighting, no text or speech bubbles."
    )

    cfg = _cfg()
    session_id = (data.get("session_id") or "").strip()
    out_dir = _session_dir(session_id, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"anchor_{uuid.uuid4().hex[:8]}.png"
    out_path = out_dir / filename

    ok, info = _call_image_api(
        prompt=prompt, model=model, quality=quality, ratio=ratio, seed=seed,
        out_path=out_path, reference_image_paths=None,
    )
    if not ok:
        return jsonify({"ok": False, "error": info.get("error", "Lỗi không rõ"),
                        "model": info.get("model", model)}), info.get("status_code", 500)

    if session_id:
        serve_url = f"/api/story/ai_image/{secure_filename(session_id)}/{filename}"
    else:
        serve_url = f"/api/story/ai_image/{filename}"
    return jsonify({
        "ok": True,
        "image_url": serve_url,
        "filename": filename,
        "session_id": session_id,
        "model": info.get("model", model),
        "size": info.get("size"),
        "prompt_preview": prompt[:300],
    })


@bp.route("/api/story/ai_generate_portrait", methods=["POST"])
def ai_generate_portrait():
    """Generate a front-view portrait for one character on a clean background.

    Used as an additional reference for any scene where the character appears.

    Body:
      name         (str)
      description  (str)
      art_style    (str)
      model, quality, ratio, seed → as usual
      anchor_url   (str)   — optional: if provided, used as reference so the
                             portrait matches the anchor's style/lighting
    """
    import uuid

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Thiếu tên nhân vật."}), 400

    art_style = (data.get("art_style") or "").strip()
    model = (data.get("model") or "cx/gpt-5.5-image").strip()
    quality = (data.get("quality") or "standard").strip()
    ratio = (data.get("ratio") or "1:1").strip()
    seed = data.get("seed")
    try:
        seed = int(seed) if seed not in (None, "") else 42
    except (ValueError, TypeError):
        seed = 42
    anchor_url = (data.get("anchor_url") or "").strip()

    style_anchor = art_style or "cinematic film still, soft natural lighting, detailed"
    prompt = (
        f"Full-body front-view portrait of {name}. {style_anchor}.\n"
        f"Character details: {description or 'unspecified'}.\n"
        f"The character is centered, facing the camera with a neutral expression, "
        f"arms relaxed at sides. Clean uniform background. No text, no speech bubbles. "
        f"This image will be reused as a reference in many later scenes — keep the appearance "
        f"crisp and unambiguous."
    )

    cfg = _cfg()
    session_id = (data.get("session_id") or "").strip()
    out_dir = _session_dir(session_id, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(name) or "char"
    filename = f"portrait_{safe_name}_{uuid.uuid4().hex[:6]}.png"
    out_path = out_dir / filename

    ref_paths = []
    if anchor_url:
        p = _resolve_image_url_to_path(anchor_url, out_dir)
        if p:
            ref_paths.append(p)

    ok, info = _call_image_api(
        prompt=prompt, model=model, quality=quality, ratio=ratio, seed=seed,
        out_path=out_path, reference_image_paths=ref_paths,
    )
    if not ok:
        return jsonify({"ok": False, "error": info.get("error", "Lỗi không rõ"),
                        "model": info.get("model", model)}), info.get("status_code", 500)

    if session_id:
        serve_url = f"/api/story/ai_image/{secure_filename(session_id)}/{filename}"
    else:
        serve_url = f"/api/story/ai_image/{filename}"
    return jsonify({
        "ok": True,
        "name": name,
        "image_url": serve_url,
        "filename": filename,
        "session_id": session_id,
        "model": info.get("model", model),
        "size": info.get("size"),
        "used_references": info.get("used_references", 0),
    })


@bp.route("/api/story/ai_generate_end_frame", methods=["POST"])
def ai_generate_end_frame():
    """Generate an "end frame" image for one panel by editing the start frame.

    The renderer will cross-dissolve from the start frame to the end frame
    over the panel's duration, giving the panel a sense of motion without
    needing a video model. This is much cheaper and faster than calling a
    real text-to-video API like Runway / Veo / Seedance.

    Body:
      start_image_url   (str)  — the panel's main image (required)
      scene_text        (str)  — the panel's narration; we use it as a hint
                                 for the kind of motion to suggest
      motion_hint       (str)  — optional explicit motion override
                                 (e.g. "camera dolly in", "character turns head")
      art_style         (str)  — keep style consistent
      model, quality, ratio, seed, session_id → as usual
    """
    import uuid

    data = request.get_json(silent=True) or {}
    start_url = (data.get("start_image_url") or "").strip()
    if not start_url:
        return jsonify({"ok": False, "error": "Thiếu start_image_url."}), 400

    scene_text = (data.get("scene_text") or "").strip()[:400]
    motion_hint = (data.get("motion_hint") or "").strip()
    art_style = (data.get("art_style") or "").strip()
    model = (data.get("model") or "cx/gpt-5.5-image").strip()
    quality = (data.get("quality") or "standard").strip()
    ratio = (data.get("ratio") or "9:16").strip()
    seed = data.get("seed")
    try:
        seed = int(seed) if seed not in (None, "") else 42
    except (ValueError, TypeError):
        seed = 42

    cfg = _cfg()
    session_id = (data.get("session_id") or "").strip()
    out_dir = _session_dir(session_id, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    start_path = _resolve_image_url_to_path(start_url, out_dir)
    if not start_path:
        # Try the global root too (older sessions)
        start_path = _resolve_image_url_to_path(start_url, _ai_images_root(cfg))
    if not start_path:
        return jsonify({"ok": False, "error": "Không tìm thấy file ảnh bắt đầu."}), 400

    style_anchor = art_style or "cinematic film still, soft natural lighting"
    if motion_hint:
        change = motion_hint
    else:
        # Heuristic: derive a small camera/character change from the scene text.
        # Keeping it generic prevents the model from completely rewriting the
        # composition, which would defeat the morph illusion.
        change = "very subtle camera dolly-in and tiny character motion (eye blink, hair shift, slight head turn)"

    prompt = (
        f"Edit the provided image. Keep the SAME composition, SAME characters, "
        f"SAME location, SAME outfits, SAME lighting and color palette. {style_anchor}.\n"
        f"Apply only this minor change: {change}.\n"
        f"Context (for tone — do not redraw): {scene_text}\n"
        f"This image will be the END frame of a short cross-dissolve, so the "
        f"difference from the START frame should be small but visible."
    )

    filename = f"endframe_{uuid.uuid4().hex[:8]}.png"
    out_path = out_dir / filename

    ok, info = _call_image_api(
        prompt=prompt, model=model, quality=quality, ratio=ratio, seed=seed,
        out_path=out_path, reference_image_paths=[start_path],
    )
    if not ok:
        return jsonify({"ok": False, "error": info.get("error", "Lỗi không rõ"),
                        "model": info.get("model", model)}), info.get("status_code", 500)

    if session_id:
        serve_url = f"/api/story/ai_image/{secure_filename(session_id)}/{filename}"
    else:
        serve_url = f"/api/story/ai_image/{filename}"
    return jsonify({
        "ok": True,
        "image_url": serve_url,
        "filename": filename,
        "session_id": session_id,
        "model": info.get("model", model),
        "size": info.get("size"),
        "used_references": info.get("used_references", 0),
    })


@bp.route("/api/story/ai_image_models", methods=["GET"])
def ai_image_models():
    """Return list of available image-generation models from 9Router.

    Tries /v1/models first; if that fails or doesn't list image models,
    returns a curated default list of Codex GPT image models.
    """
    import requests as _requests

    cfg = _cfg()
    nr_cfg = cfg.get("nine_router") or {}
    endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = (nr_cfg.get("api_key") or "").strip()

    # Curated default — Codex GPT image models, newest first
    defaults = [
        {"id": "cx/gpt-5.5-image", "label": "GPT-5.5 Image (Codex, mới nhất)"},
        {"id": "cx/gpt-5.4-image", "label": "GPT-5.4 Image (Codex)"},
        {"id": "cx/gpt-5.3-image", "label": "GPT-5.3 Image (Codex)"},
        {"id": "cx/gpt-5.2-image", "label": "GPT-5.2 Image (Codex)"},
    ]

    if not api_key:
        return jsonify({"ok": True, "models": defaults, "source": "default"})

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = _requests.get(f"{endpoint}/models", headers=headers, timeout=10)
        if resp.status_code == 200:
            body = resp.json()
            items = body.get("data") or body.get("models") or []
            # Keep only image-capable models (heuristic: id contains 'image' or 'dalle')
            img_models = []
            for it in items:
                mid = it.get("id") or it.get("name") or ""
                if any(k in mid.lower() for k in ("image", "dalle", "dall-e", "sd-", "flux", "imagen", "midjourney")):
                    img_models.append({
                        "id": mid,
                        "label": mid + (f" · {it['owned_by']}" if it.get("owned_by") else ""),
                    })
            if img_models:
                # Sort newest-first by extracted version score
                import re as _re
                def _score(m):
                    mid = m["id"]
                    versions = _re.findall(r"\d+(?:\.\d+)?", mid)
                    v_sum = sum(float(v) for v in versions) if versions else 0
                    # Bonus for cx/ (Codex) and image-specific models
                    bonus = 0
                    if mid.startswith("cx/"):
                        bonus += 100
                    if "image" in mid.lower():
                        bonus += 10
                    return v_sum + bonus
                img_models.sort(key=_score, reverse=True)
                return jsonify({"ok": True, "models": img_models, "source": "9router"})
    except Exception:
        pass

    return jsonify({"ok": True, "models": defaults, "source": "default"})


@bp.route("/api/story/ai_image/<session>/<filename>", methods=["GET"])
def serve_ai_image_session(session, filename):
    """Serve a generated AI image scoped to a per-run session folder."""
    cfg = _cfg()
    safe_session = secure_filename(session)
    safe_name = secure_filename(filename)
    if not safe_session or not safe_name:
        abort(400)
    fpath = _ai_images_root(cfg) / safe_session / safe_name
    if not fpath.exists():
        abort(404)
    return send_file(str(fpath), mimetype="image/png")


@bp.route("/api/story/ai_image/<filename>", methods=["GET"])
def serve_ai_image(filename):
    """Serve a generated AI image (legacy flat layout, no session)."""
    cfg = _cfg()
    out_dir = _ai_images_root(cfg)
    safe_name = secure_filename(filename)
    if not safe_name:
        abort(400)
    fpath = out_dir / safe_name
    if not fpath.exists():
        abort(404)
    return send_file(str(fpath), mimetype="image/png")


@bp.route("/api/story/ai_session/new", methods=["POST"])
def ai_session_new():
    """Allocate a new session id (used by the front-end before kicking off
    the AI pipeline so anchor / portraits / scenes all land in one folder)."""
    sid = _make_session_id()
    cfg = _cfg()
    # Pre-create the folder so the very first image upload doesn't race
    _session_dir(sid, cfg)
    return jsonify({"ok": True, "session_id": sid})


# ── AI Story Sessions — save & load for consistency ─────────────────────────

def _ai_sessions_dir() -> Path:
    p = STATE_DIR / "ai_story_sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


@bp.route("/api/story/ai_sessions", methods=["GET"])
def ai_sessions_list():
    """List saved AI story sessions."""
    sessions_dir = _ai_sessions_dir()
    sessions = []
    for f in sorted(sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "id": f.stem,
                "title": data.get("title") or data.get("prompt", "")[:50] or f.stem,
                "created_at": data.get("created_at", ""),
                "num_scenes": len(data.get("scenes", [])),
                "genre": data.get("genre", ""),
            })
        except Exception:
            continue
    return jsonify({"ok": True, "sessions": sessions})


@bp.route("/api/story/ai_sessions/save", methods=["POST"])
def ai_session_save():
    """Save current AI story session for future reuse.

    Body: full session data (prompt, characters, scenes, image_prompts, etc.)
    """
    data = request.get_json(silent=True) or {}
    if not data.get("prompt") and not data.get("scenes"):
        return jsonify({"ok": False, "error": "Không có dữ liệu để lưu."}), 400

    sessions_dir = _ai_sessions_dir()
    # Generate session ID from timestamp
    session_id = data.get("id") or time.strftime("%Y%m%d_%H%M%S")
    data["created_at"] = data.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S")
    data["id"] = session_id

    fpath = sessions_dir / f"{session_id}.json"
    fpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "id": session_id, "message": "Đã lưu session."})


@bp.route("/api/story/ai_sessions/load", methods=["POST"])
def ai_session_load():
    """Load a saved AI story session."""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("id") or "").strip()
    if not session_id:
        return jsonify({"ok": False, "error": "Thiếu session ID."}), 400

    sessions_dir = _ai_sessions_dir()
    fpath = sessions_dir / f"{safe_filename(session_id)}.json"
    if not fpath.exists():
        return jsonify({"ok": False, "error": "Session không tồn tại."}), 404

    session_data = json.loads(fpath.read_text(encoding="utf-8"))
    return jsonify({"ok": True, "session": session_data})


@bp.route("/api/story/ai_sessions/delete", methods=["POST"])
def ai_session_delete():
    """Delete a saved session."""
    data = request.get_json(silent=True) or {}
    session_id = (data.get("id") or "").strip()
    if not session_id:
        return jsonify({"ok": False, "error": "Thiếu session ID."}), 400

    sessions_dir = _ai_sessions_dir()
    fpath = sessions_dir / f"{safe_filename(session_id)}.json"
    if fpath.exists():
        fpath.unlink()
    return jsonify({"ok": True, "message": "Đã xoá."})


# ══════════════════════════════════════════════════════════════════════════════
# MangaDex integration — search → chapters → pages → render
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/manga/search", methods=["POST", "GET"])
def manga_search():
    """Free-text search across MangaDex (default) or Cubari (paste a URL).

    Body fields:
        title:       free-text title (MangaDex only).
        url:         a cubari.moe URL — when present we fetch only that series.
        source:      'mangadex' (default) | 'cubari'.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    title = (data.get("title") or data.get("q") or "").strip()
    url_value = (data.get("url") or "").strip()
    source = (data.get("source") or "").strip().lower() or (
        "cubari" if url_value or title.startswith("http") else "mangadex"
    )

    # ── Cubari source (URL-only lookup) ────────────────────────────
    if source == "cubari":
        from core.cubari_client import (
            parse_cubari_url, get_series, series_to_summary,
        )
        candidate = url_value or title
        parsed = parse_cubari_url(candidate)
        if not parsed:
            return jsonify({
                "ok": False,
                "error": "Cubari cần một URL dạng https://cubari.moe/read/<source>/<slug>/.",
            }), 400
        try:
            raw = get_series(parsed["source"], parsed["slug"], proxy_url=_proxy_url() or None)
            summary = series_to_summary(parsed["source"], parsed["slug"], raw)
            return jsonify({"ok": True, "items": [summary.to_dict()], "count": 1, "source": "cubari"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    # ── Default: MangaDex ─────────────────────────────────────────
    limit = max(1, min(50, int(data.get("limit") or 20)))
    offset = max(0, int(data.get("offset") or 0))
    langs_raw = data.get("languages")
    if isinstance(langs_raw, str):
        langs = [s.strip() for s in langs_raw.split(",") if s.strip()]
    elif isinstance(langs_raw, list):
        langs = [str(s).strip() for s in langs_raw if str(s).strip()]
    else:
        langs = ["vi", "en"]
    ratings_raw = data.get("ratings")
    if isinstance(ratings_raw, str):
        ratings = [s.strip() for s in ratings_raw.split(",") if s.strip()]
    elif isinstance(ratings_raw, list):
        ratings = [str(s).strip() for s in ratings_raw if str(s).strip()]
    else:
        ratings = ["safe", "suggestive"]
    try:
        client = _md_client(load_cfg() or {})
        results = client.search_manga(
            title,
            limit=limit,
            offset=offset,
            translated_languages=langs or None,
            content_ratings=ratings or None,
        )
        return jsonify({
            "ok": True,
            "items": [r.to_dict() for r in results],
            "count": len(results),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/details", methods=["POST", "GET"])
def manga_details():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_id = (data.get("manga_id") or data.get("id") or "").strip()
    if not manga_id:
        return jsonify({"ok": False, "error": "Thiếu manga_id."}), 400
    try:
        client = _md_client(load_cfg() or {})
        info = client.get_manga(manga_id)
        return jsonify({"ok": True, "manga": info.to_dict()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/chapters", methods=["POST", "GET"])
def manga_chapters():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_id = (data.get("manga_id") or data.get("id") or "").strip()
    if not manga_id:
        return jsonify({"ok": False, "error": "Thiếu manga_id."}), 400

    # Cubari id?
    if manga_id.startswith("cubari:"):
        from core.cubari_client import list_chapters as cubari_list
        source, slug, _ = _split_cubari_id(manga_id)
        try:
            chapters = cubari_list(source, slug, proxy_url=_proxy_url() or None)
            order_dir = (data.get("order_dir") or "asc").lower()
            if order_dir == "desc":
                chapters = list(reversed(chapters))
            return jsonify({
                "ok": True,
                "chapters": [c.to_dict() for c in chapters],
                "count": len(chapters),
                "source": "cubari",
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    langs_raw = data.get("languages")
    if isinstance(langs_raw, str):
        langs = [s.strip() for s in langs_raw.split(",") if s.strip()]
    elif isinstance(langs_raw, list):
        langs = [str(s).strip() for s in langs_raw if str(s).strip()]
    else:
        langs = ["vi", "en"]
    order_dir = (data.get("order_dir") or "asc").lower()
    if order_dir not in ("asc", "desc"):
        order_dir = "asc"
    try:
        client = _md_client(load_cfg() or {})
        chapters = client.list_chapters(
            manga_id,
            translated_languages=langs or None,
            order_dir=order_dir,
        )
        return jsonify({
            "ok": True,
            "chapters": [c.to_dict() for c in chapters],
            "count": len(chapters),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/chapter_pages", methods=["POST", "GET"])
def manga_chapter_pages():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    if not chapter_id:
        return jsonify({"ok": False, "error": "Thiếu chapter_id."}), 400
    saver = bool(data.get("saver"))

    # Cubari chapter ids look like "cubari:source/slug/<chapter>"
    if chapter_id.startswith("cubari:"):
        from core.cubari_client import get_chapter_pages as cubari_pages
        source, slug, ch = _split_cubari_id(chapter_id)
        try:
            pages = cubari_pages(source, slug, ch, proxy_url=_proxy_url() or None)
            return jsonify({
                "ok": True,
                "chapter_id": chapter_id,
                "base_url": "",
                "hash": "",
                "page_count": len(pages.pages),
                "pages": pages.pages,
                "pages_full": pages.pages,
                "pages_saver": pages.pages_saver,
                "source": "cubari",
            })
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:300]}), 502

    try:
        client = _md_client(load_cfg() or {})
        pages = client.get_chapter_pages(chapter_id)
        return jsonify({
            "ok": True,
            "chapter_id": chapter_id,
            "base_url": pages.base_url,
            "hash": pages.hash,
            "page_count": len(pages.pages),
            "pages": pages.page_urls(saver=saver),
            "pages_full": pages.page_urls(saver=False),
            "pages_saver": pages.page_urls(saver=True),
            "source": "mangadex",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/image_proxy", methods=["GET"])
def manga_image_proxy():
    """Proxy a manga CDN image so the browser can render it without
    bumping into Referer/CORS issues.

    Allows public HTTPS image hosts, but blocks private/loopback IPs to
    prevent SSRF abuse.
    """
    import ipaddress
    import socket
    import urllib.parse as _up
    import urllib.request as _ur
    from flask import Response

    url = (request.args.get("url") or "").strip()
    if not url:
        return abort(400)
    parsed = _up.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return abort(400)
    host = (parsed.hostname or "").lower()
    if not host:
        return abort(400)

    # Resolve and reject private / loopback / link-local addresses
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else ""
            if not ip:
                continue
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if (addr.is_private or addr.is_loopback or addr.is_link_local
                    or addr.is_multicast or addr.is_reserved):
                return abort(403)
    except socket.gaierror:
        return abort(502)

    # Pick a referer that matches the host so the upstream CDN doesn't
    # 403 us. Manga CDNs almost always require a same-origin referer.
    referer = f"{parsed.scheme}://{host}/"
    try:
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; DuyTrisManga/1.0)",
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        })
        with _ur.urlopen(req, timeout=20) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
        # Only forward responses that are actually images
        if not ctype.lower().startswith(("image/", "application/octet-stream")):
            return abort(415)
        return Response(
            data,
            mimetype=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 502


# ── MangaDex → narration: build per-page TTS text ──────────────────────────
@bp.route("/api/story/manga/build_narration", methods=["POST"])
def manga_build_narration():
    """Take the user's text (from OCR or manual input) + a list of page URLs
    and produce panel-by-panel narration segments.

    Modes:
      - 'split'  : evenly split a single text block across N pages.
      - 'manual' : caller supplies one narration string per page.
    """
    data = request.get_json(silent=True) or {}
    pages = data.get("pages") or []
    mode = (data.get("mode") or "split").lower()
    text = (data.get("text") or "").strip()
    panel_texts = data.get("panel_texts") or []

    if not pages:
        return jsonify({"ok": False, "error": "Thiếu danh sách pages."}), 400

    panels = []
    if mode == "manual" and panel_texts:
        # Pair pages with manual texts (truncate longer side).
        for i, url in enumerate(pages):
            t = ""
            if i < len(panel_texts):
                t = str(panel_texts[i] or "").strip()
            panels.append({"image_url": url, "text": t})
    else:
        # Even split — segment text into N pieces by sentence boundaries.
        text = normalize_text(text)
        if not text:
            for url in pages:
                panels.append({"image_url": url, "text": ""})
        else:
            from core.story_writer import split_sentences
            sents = split_sentences(text) or [text]
            n = len(pages)
            per = max(1, len(sents) // n)
            chunks: list[str] = []
            cursor = 0
            for i in range(n):
                if i == n - 1:
                    chunk = " ".join(sents[cursor:])
                else:
                    chunk = " ".join(sents[cursor: cursor + per])
                    cursor += per
                chunks.append(chunk.strip())
            for url, chunk in zip(pages, chunks):
                panels.append({"image_url": url, "text": chunk})

    # Optionally translate the whole script in one shot for consistency.
    if data.get("translate"):
        try:
            from utils.translation import translate_texts
            cfg = load_cfg() or {}
            tr_cfg = dict(cfg.get("translation") or {})
            target_lang = (data.get("target_lang") or "vi")
            provider = (data.get("provider") or "auto")
            texts = [p["text"] for p in panels]
            translated, _ = translate_texts(texts, tr_cfg, provider, target_lang=target_lang)
            for p, t in zip(panels, translated):
                if t and t.strip():
                    p["text"] = t.strip()
        except Exception:
            # Non-fatal — keep original texts on failure
            pass

    return jsonify({
        "ok": True,
        "panel_count": len(panels),
        "panels": panels,
    })


# ── Render manga → video (background job) ──────────────────────────────────
@bp.route("/api/story/manga/render", methods=["POST"])
def manga_render():
    """Kick off a background MP4 render from panels + narration.

    Body:
        {
          "panels":  [{"image_url": "...", "text": "..."}, ...],
          "title":   "Chương 1",
          "preset":  "shorts" | "youtube" | "square",
          "subtitle_format": "ass" | "srt",
          "burn_subtitles": true,
          "tts_engine": "edge-tts",
          "tts_voice": "vi-VN-HoaiMyNeural",
          "tts_rate":  "+0%",
          "target_lang": "vi",
          "bgm_url": "",
          "bgm_volume": 0.1,
          "fps": 30,
          "zoom": true
        }
    """
    from core.manga_video import MangaRenderRequest, PanelInput, render_async

    cfg = load_cfg() or {}
    data = request.get_json(silent=True) or {}
    raw_panels = data.get("panels") or []
    if not raw_panels:
        return jsonify({"ok": False, "error": "Thiếu danh sách panels."}), 400

    panels = []
    ai_image_dir = _manga_output_dir(cfg) / "ai_images"
    # Build absolute base URL once: prefer the request's host, fall back to localhost.
    try:
        base_url = request.host_url.rstrip("/")
    except Exception:
        base_url = "http://127.0.0.1:5000"

    for p in raw_panels:
        url = (p.get("image_url") or p.get("url") or "").strip()
        if not url:
            continue
        end_url = (p.get("end_image_url") or "").strip()

        # Helper: turn a server-relative URL (incl. AI-generated images) into
        # something the renderer can read directly. For AI images we resolve
        # to the absolute filesystem path so the renderer just copies the
        # file instead of paying for an HTTP round-trip via localhost.
        def _resolve(u: str) -> str:
            if not u:
                return ""
            if u.startswith("/api/story/ai_image/"):
                fname = u.rsplit("/", 1)[-1]
                local_file = ai_image_dir / secure_filename(fname)
                if local_file.exists():
                    return str(local_file.resolve())
                return base_url + u
            if u.startswith("/"):
                return base_url + u
            return u

        url = _resolve(url)
        end_url = _resolve(end_url)
        panels.append(PanelInput(
            image_url=url,
            text=(p.get("text") or "").strip(),
            end_image_url=end_url,
        ))
    if not panels:
        return jsonify({"ok": False, "error": "Không có panel hợp lệ."}), 400

    # Resolution preset
    preset = (data.get("preset") or "shorts").lower()
    if preset == "shorts" or preset == "tiktok":
        res_w, res_h = 1080, 1920
    elif preset == "square":
        res_w = res_h = 1080
    else:
        res_w, res_h = 1920, 1080

    # Honor explicit width/height when provided
    if data.get("width"):
        res_w = int(data["width"])
    if data.get("height"):
        res_h = int(data["height"])

    proxy = ""
    try:
        from core.proxy_resolver import resolve_proxy
        proxy = resolve_proxy(cfg) or ""
    except Exception:
        proxy = ""

    req = MangaRenderRequest(
        panels=panels,
        title=(data.get("title") or "manga_chapter").strip(),
        width=res_w,
        height=res_h,
        fps=int(data.get("fps") or 30),
        subtitle_format=(data.get("subtitle_format") or "ass").lower(),
        burn_subtitles=bool(data.get("burn_subtitles", True)),
        target_lang=(data.get("target_lang") or "vi"),
        tts_engine=(data.get("tts_engine") or "edge-tts"),
        tts_voice=(data.get("tts_voice") or "vi-VN-HoaiMyNeural"),
        tts_rate=(data.get("tts_rate") or "+0%"),
        tts_pitch=(data.get("tts_pitch") or "+0Hz"),
        fpt_api_key=(
            os.getenv("FPT_TTS_API_KEY")
            or (cfg.get("video_process") or {}).get("fpt_api_key")
            or ""
        ).strip(),
        fpt_speed=int(data.get("fpt_speed") or 0),
        min_panel_sec=float(data.get("min_panel_sec") or 2.0),
        inter_panel_pause_sec=float(data.get("inter_panel_pause_sec") or 0.25),
        intro_sec=float(data.get("intro_sec") or 0.8),
        outro_sec=float(data.get("outro_sec") or 1.2),
        zoom=bool(data.get("zoom", True)),
        # NEW: smooth crossfade between panels (0 = hard cut, 0.4s = default)
        crossfade_sec=float(data.get("crossfade_sec") if data.get("crossfade_sec") is not None else 0.4),
        bgm_url=(data.get("bgm_url") or "").strip(),
        bgm_volume=float(data.get("bgm_volume") or 0.10),
        title_text=(data.get("title_text") or data.get("title") or "").strip(),
        title_bar_color=(data.get("title_bar_color") or "#1A73E8"),
        font_name=(data.get("font_name") or "Arial"),
        font_size=int(data.get("font_size") or 48),
        font_color=(data.get("font_color") or "#FFFFFF"),
        outline_color=(data.get("outline_color") or "#000000"),
        output_dir=_manga_output_dir(cfg),
        output_name=(data.get("output_name") or "").strip(),
        proxy_url=proxy,
    )
    try:
        job_id = render_async(req)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 500


@bp.route("/api/story/manga/render_status", methods=["GET"])
def manga_render_status():
    from core.manga_video import get_job_manager

    jid = (request.args.get("job_id") or "").strip()
    if not jid:
        return jsonify({"ok": False, "error": "Thiếu job_id."}), 400
    job = get_job_manager().get(jid)
    if not job:
        return jsonify({"ok": False, "error": "Job không tồn tại."}), 404

    def _rel(p: str) -> str:
        if not p:
            return ""
        try:
            pp = Path(p)
            if str(pp).startswith(str(ROOT)):
                return str(pp.relative_to(ROOT)).replace("\\", "/")
        except Exception:
            pass
        return p

    return jsonify({
        "ok": True,
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "output_video": job.output_video,
        "output_video_rel": _rel(job.output_video),
        "output_srt": job.output_srt,
        "output_srt_rel": _rel(job.output_srt),
        "output_ass": job.output_ass,
        "output_ass_rel": _rel(job.output_ass),
        "started_at": int(job.started_at),
        "finished_at": int(job.finished_at),
    })


@bp.route("/api/story/manga/render_video", methods=["GET"])
def manga_render_video():
    """Stream / download a rendered manga MP4 (or its sidecar subtitle).

    Restricted to files inside the configured manga output dir.
    """
    name = (request.args.get("name") or "").strip()
    kind = (request.args.get("kind") or "video").lower()  # video|srt|ass
    download = request.args.get("download") in ("1", "true", "yes")
    if not name:
        return abort(400)
    out_dir = _manga_output_dir(load_cfg() or {})
    try:
        target = safe_join(out_dir, name)
    except ValueError:
        return abort(403)
    if not target.exists() or not target.is_file():
        return abort(404)
    mt_map = {
        "video": "video/mp4",
        "srt": "application/x-subrip",
        "ass": "text/plain",
    }
    return send_file(
        str(target),
        mimetype=mt_map.get(kind, "application/octet-stream"),
        as_attachment=download,
        download_name=target.name,
    )


# ── TTS engines/voices catalogue (shared shape with /api/movie/voices) ─────
@bp.route("/api/story/voices", methods=["GET"])
def story_voices():
    engines = [
        {
            "id": "edge-tts",
            "label": "Edge TTS (Microsoft, miễn phí)",
            "default": "vi-VN-HoaiMyNeural",
            "voices": {
                "vi": [
                    ("vi-VN-HoaiMyNeural", "Hoài My (nữ, miền Bắc)"),
                    ("vi-VN-NamMinhNeural", "Nam Minh (nam, miền Bắc)"),
                ],
                "en": [
                    ("en-US-JennyNeural", "Jenny (female, US)"),
                    ("en-US-AriaNeural", "Aria (female, US)"),
                    ("en-US-GuyNeural", "Guy (male, US)"),
                    ("en-GB-SoniaNeural", "Sonia (female, UK)"),
                ],
                "ja": [
                    ("ja-JP-NanamiNeural", "Nanami (女)"),
                    ("ja-JP-KeitaNeural", "Keita (男)"),
                ],
                "ko": [
                    ("ko-KR-SunHiNeural", "SunHi (여)"),
                    ("ko-KR-InJoonNeural", "InJoon (남)"),
                ],
                "zh": [
                    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao (女, 简体)"),
                    ("zh-CN-YunxiNeural", "Yunxi (男, 简体)"),
                ],
                "th": [
                    ("th-TH-PremwadeeNeural", "Premwadee (หญิง)"),
                ],
            },
        },
        {
            "id": "fpt-ai",
            "label": "FPT AI TTS (cần API key, chỉ tiếng Việt)",
            "default": "banmai",
            "voices": {
                "vi": [
                    ("banmai", "Ban Mai (FPT — nữ, miền Bắc)"),
                    ("thuminh", "Thu Minh (FPT — nữ, miền Bắc)"),
                    ("leminh", "Le Minh (FPT — nam, miền Bắc)"),
                    ("linhsan", "Linh San (FPT — nữ, miền Nam)"),
                    ("giahuy", "Gia Huy (FPT — nam, miền Nam)"),
                    ("lannhi", "Lan Nhi (FPT — nữ, miền Nam)"),
                ],
            },
        },
        {
            "id": "gtts",
            "label": "Google gTTS (đơn giản, dự phòng)",
            "default": "vi",
            "voices": {
                "vi": [("vi", "Tiếng Việt mặc định")],
                "en": [("en", "English (default)")],
                "ja": [("ja", "日本語 (default)")],
                "ko": [("ko", "한국어 (default)")],
                "zh": [("zh", "中文 (default)")],
            },
        },
    ]
    return jsonify({"ok": True, "engines": engines})


# ══════════════════════════════════════════════════════════════════════════════
# Smart chapter-URL extractor — paste any chapter URL → get image list
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/manga/extract_chapter", methods=["POST"])
def manga_extract_chapter():
    """Extract image URLs from a chapter page on common manga sites.

    Body::
        { "url": "https://www.nettruyenvio.com/truyen-tranh/.../chuong-1/..." }
    """
    from core.manga_extractors import extract_chapter_images, ExtractError, SITES

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({
            "ok": False,
            "error": "Thiếu URL chương.",
            "supported_sites": [s.label for s in SITES] + ["Generic (fallback)"],
        }), 400
    try:
        result = extract_chapter_images(url, proxy_url=_proxy_url() or None)
        return jsonify({"ok": True, **result})
    except ExtractError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/manga/extract_sites", methods=["GET"])
def manga_extract_sites():
    """List sites with dedicated extractors (UI hint)."""
    from core.manga_extractors import SITES
    return jsonify({
        "ok": True,
        "sites": [
            {"id": s.id, "label": s.label, "hosts": list(s.host_substrings)}
            for s in SITES
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# NetTruyen catalog (search + manga details + chapter list + chapter pages)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/nettruyen/search", methods=["POST", "GET"])
def nettruyen_search():
    from core import nettruyen_client as nt

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400
    page = max(1, int(data.get("page") or 1))
    base_url = (data.get("base_url") or "").strip() or None

    try:
        items = nt.search(
            keyword,
            base_url=base_url,
            proxy_url=_proxy_url() or None,
            page=page,
        )
        return jsonify({
            "ok": True,
            "items": [m.to_dict() for m in items],
            "count": len(items),
            "page": page,
            "source": "nettruyen",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/nettruyen/details", methods=["POST", "GET"])
def nettruyen_details():
    from core import nettruyen_client as nt

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    manga_url = (data.get("manga_id") or data.get("id") or data.get("url") or "").strip()
    if not manga_url:
        return jsonify({"ok": False, "error": "Thiếu manga_id (URL)."}), 400

    try:
        info = nt.get_manga(manga_url, proxy_url=_proxy_url() or None)
        chapters = list(getattr(info, "_chapters", []) or [])
        return jsonify({
            "ok": True,
            "manga": info.to_dict(),
            "chapters": [c.to_dict() for c in chapters],
            "chapter_count": len(chapters),
            "source": "nettruyen",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/nettruyen/chapter_pages", methods=["POST", "GET"])
def nettruyen_chapter_pages():
    """Resolve image URLs for a chapter (delegates to extractors)."""
    from core.manga_extractors import extract_chapter_images, ExtractError

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_url = (data.get("chapter_id") or data.get("id") or data.get("url") or "").strip()
    if not chapter_url:
        return jsonify({"ok": False, "error": "Thiếu chapter URL."}), 400
    try:
        result = extract_chapter_images(chapter_url, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "chapter_id": chapter_url,
            "page_count": result["page_count"],
            "pages": result["pages"],
            "title": result.get("title", ""),
            "source": "nettruyen",
        })
    except ExtractError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# Vietnamese manga sites — search → chapters → pages (NetTruyen / TruyenQQ / ...)
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/vn/sources", methods=["GET"])
def vn_sources():
    from core.vn_manga_sources import SOURCES
    return jsonify({
        "ok": True,
        "sources": [
            {"id": sid, "label": cls.label, "base": cls.DEFAULT_BASE}
            for sid, cls in SOURCES.items()
        ],
    })


@bp.route("/api/story/vn/search", methods=["POST", "GET"])
def vn_search():
    from core.vn_manga_sources import SOURCES, search_combined, get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khóa."}), 400

    source = (data.get("source") or "all").strip().lower()
    limit = max(1, min(50, int(data.get("limit") or 12)))
    proxy = _proxy_url() or None

    try:
        if source == "all":
            items = search_combined(keyword, limit=limit, proxy_url=proxy)
        else:
            if source not in SOURCES:
                return jsonify({"ok": False, "error": f"Nguồn không hỗ trợ: {source}"}), 400
            src = get_source(source, proxy_url=proxy)
            items = [m.to_dict() for m in src.search(keyword, limit=limit)]
        return jsonify({"ok": True, "items": items, "count": len(items), "source": source})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/details", methods=["POST", "GET"])
def vn_details():
    from core.vn_manga_sources import get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    source = (data.get("source") or "").strip().lower()
    target = (data.get("url") or data.get("slug") or data.get("id") or "").strip()
    if not source or not target:
        return jsonify({"ok": False, "error": "Thiếu source / url."}), 400
    try:
        src = get_source(source, proxy_url=_proxy_url() or None)
        info = src.details(target)
        return jsonify({"ok": True, "manga": info.to_dict()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/chapters", methods=["POST", "GET"])
def vn_chapters():
    from core.vn_manga_sources import get_source

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    source = (data.get("source") or "").strip().lower()
    target = (data.get("url") or data.get("slug") or data.get("id") or "").strip()
    if not source or not target:
        return jsonify({"ok": False, "error": "Thiếu source / url."}), 400
    order_dir = (data.get("order_dir") or "asc").lower()
    try:
        src = get_source(source, proxy_url=_proxy_url() or None)
        chapters = src.chapters(target)
        if order_dir == "desc":
            chapters = list(reversed(chapters))
        return jsonify({
            "ok": True,
            "chapters": [c.to_dict() for c in chapters],
            "count": len(chapters),
            "source": source,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/vn/chapter_pages", methods=["POST", "GET"])
def vn_chapter_pages():
    from core.vn_manga_sources import chapter_pages
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("url") or data.get("id") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu URL chương."}), 400
    try:
        result = chapter_pages(url, proxy_url=_proxy_url() or None)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# Multi-source search — query NetTruyen + TruyenQQ + BlogTruyen + Comick +
# Bato.to + MangaDex in parallel and return a merged, deduped result set.
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/search_all", methods=["POST", "GET"])
def story_search_all():
    """One-shot search across all manga sources (VN + international)."""
    import concurrent.futures as _cf

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400

    raw_sources = data.get("sources")
    if isinstance(raw_sources, str):
        sources = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, list):
        sources = [str(s).strip() for s in raw_sources if str(s).strip()]
    else:
        sources = ["nettruyen", "truyenqq", "blogtruyen",
                   "comick", "bato", "mangadex"]

    limit = max(1, min(30, int(data.get("limit_per_source") or 12)))
    proxy = _proxy_url() or None

    def _wrap_err(label: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"_error": f"{label}: {str(e)[:120]}"}

    def _search_vn(source_id: str):
        from core.vn_manga_sources import get_source
        src = get_source(source_id, proxy_url=proxy)
        return [m.to_dict() for m in src.search(keyword, limit=limit)]

    def _search_nt():
        try:
            from core import nettruyen_client as nt
            items = nt.search(keyword, proxy_url=proxy)[:limit]
            out = []
            for m in items:
                d = m.to_dict()
                d["source"] = "nettruyen"
                d["url"] = d.get("id") or ""
                out.append(d)
            return out
        except Exception:
            return _search_vn("nettruyen")

    def _search_md():
        from core.mangadex_client import MangaDexClient
        client = MangaDexClient(proxy_url=proxy)
        items = client.search_manga(
            keyword,
            limit=limit,
            translated_languages=("vi", "en"),
            content_ratings=("safe", "suggestive", "erotica"),
        )
        return [{**m.to_dict(), "source": "mangadex", "url": ""} for m in items]

    def _search_comick():
        from core import comick_client as cc
        items = cc.search(keyword, limit=limit, proxy_url=proxy)
        return [{**m.to_dict(), "source": "comick", "url": ""} for m in items]

    def _search_bato():
        from core import batoto_client as bc
        items = bc.search(keyword, limit=limit, proxy_url=proxy)
        return [m.to_dict() for m in items]

    jobs: dict = {}
    with _cf.ThreadPoolExecutor(max_workers=6) as pool:
        for src in sources:
            if src == "nettruyen":
                jobs[src] = pool.submit(_wrap_err, "nettruyen", _search_nt)
            elif src == "mangadex":
                jobs[src] = pool.submit(_wrap_err, "mangadex", _search_md)
            elif src == "comick":
                jobs[src] = pool.submit(_wrap_err, "comick", _search_comick)
            elif src == "bato":
                jobs[src] = pool.submit(_wrap_err, "bato", _search_bato)
            elif src in ("truyenqq", "blogtruyen"):
                jobs[src] = pool.submit(_wrap_err, src, _search_vn, src)

        per_source: dict = {}
        errors: list = []
        for src, fut in jobs.items():
            try:
                res = fut.result(timeout=25)
            except Exception as e:
                res = {"_error": f"{src}: {str(e)[:120]}"}
            if isinstance(res, dict) and "_error" in res:
                errors.append(res["_error"])
                per_source[src] = []
            else:
                per_source[src] = res or []

    # Interleave per-source results so all sources appear early instead of
    # being grouped by provider (better UX when scanning the result grid).
    merged: list = []
    seen = set()
    cursor = 0
    while True:
        added = False
        for src, items in per_source.items():
            if cursor < len(items):
                it = items[cursor]
                key = (src, it.get("id") or it.get("url") or it.get("title") or "")
                if key not in seen:
                    seen.add(key)
                    it.setdefault("source", src)
                    merged.append(it)
                added = True
        if not added:
            break
        cursor += 1

    return jsonify({
        "ok": True,
        "items": merged,
        "count": len(merged),
        "per_source": {k: len(v) for k, v in per_source.items()},
        "errors": errors,
    })


# ── Bato.to dispatcher (called from chapter selection in the UI) ───────────
@bp.route("/api/story/bato/details", methods=["POST", "GET"])
def bato_details():
    from core import batoto_client as bc

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("manga_id") or data.get("id") or data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu manga URL."}), 400
    try:
        info = bc.get_manga(url, proxy_url=_proxy_url() or None)
        chapters = list(getattr(info, "_chapters", []) or [])
        return jsonify({
            "ok": True,
            "manga": info.to_dict(),
            "chapters": [c.to_dict() for c in chapters],
            "chapter_count": len(chapters),
            "source": "bato",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/bato/chapter_pages", methods=["POST", "GET"])
def bato_chapter_pages():
    from core import batoto_client as bc

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    url = (data.get("chapter_id") or data.get("id") or data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu chapter URL."}), 400
    try:
        pages = bc.get_chapter_pages(url, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "chapter_id": url,
            "page_count": len(pages),
            "pages": pages,
            "source": "bato",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


# ══════════════════════════════════════════════════════════════════════════════
# MangaPlus integration — extract chapter pages from MangaDex external_url
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/mangaplus/chapter_pages", methods=["POST", "GET"])
def mangaplus_chapter_pages():
    """Resolve a MangaPlus chapter (from a viewer URL or numeric id) into
    decoded page URLs that the browser can render via the image proxy.
    """
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}

    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    url_in = (data.get("url") or "").strip()
    if not chapter_id and url_in:
        chapter_id = mp.chapter_id_from_url(url_in) or ""
    if not chapter_id:
        return jsonify({
            "ok": False,
            "error": "Thiếu chapter_id hoặc URL MangaPlus.",
        }), 400

    quality = (data.get("quality") or "high").strip().lower()
    if quality not in ("low", "high", "super_high"):
        quality = "high"

    try:
        pairs = mp.fetch_chapter_pages(
            chapter_id, quality=quality, proxy_url=_proxy_url() or None,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502

    # Return same-origin URLs so the browser doesn't have to deal with
    # CORS or the per-image XOR key. The proxy below does the decrypt.
    pages = []
    for img, key in pairs:
        proxied = (
            "/api/story/mangaplus/image?url=" + urllib.parse.quote(img, safe="")
            + "&key=" + urllib.parse.quote(key or "", safe="")
        )
        pages.append(proxied)

    return jsonify({
        "ok": True,
        "chapter_id": chapter_id,
        "page_count": len(pages),
        "pages": pages,
        "source": "mangaplus",
    })


@bp.route("/api/story/mangaplus/image", methods=["GET"])
def mangaplus_image():
    """Fetch an encrypted MangaPlus image, XOR-decrypt it, stream JPEG."""
    from flask import Response
    from core import mangaplus_client as mp

    image_url = (request.args.get("url") or "").strip()
    key = (request.args.get("key") or "").strip()
    if not image_url:
        return abort(400)
    if "tokyo-cdn.com" not in image_url and "mangaplus" not in image_url:
        return abort(403)
    try:
        data = mp.fetch_decrypted_image(image_url, key, proxy_url=_proxy_url() or None)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 502
    return Response(
        data,
        mimetype="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Zip-download all panels (image bundle for "Tải ảnh về máy") ────────────
@bp.route("/api/story/manga/download_zip", methods=["POST"])
def manga_download_zip():
    """Stream a ZIP containing every panel image. Used when the user wants
    a local copy instead of just the rendered MP4.

    Body::
        {
          "title": "One Piece — Chapter 1",
          "pages": ["https://...", "/api/story/mangaplus/image?...", ...]
        }
    """
    import io
    import re as _re
    import zipfile
    import urllib.parse as _up
    import urllib.request as _ur

    data = request.get_json(silent=True) or {}
    pages = data.get("pages") or []
    title = (data.get("title") or "manga_chapter").strip()
    if not pages:
        return jsonify({"ok": False, "error": "Thiếu pages."}), 400

    safe_title = _re.sub(r"[\\/:*?\"<>|]", "_", title).strip(" .") or "manga_chapter"

    # Build ZIP fully in memory (chapters are typically <50 MB)
    buf = io.BytesIO()
    proxy = _proxy_url() or ""
    handlers: list = []
    if proxy:
        scheme = proxy.split("://", 1)[0]
        handlers.append(_ur.ProxyHandler({scheme: proxy}))
    opener = _ur.build_opener(*handlers) if handlers else _ur.build_opener()

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
        for idx, raw_url in enumerate(pages, start=1):
            try:
                # Same-origin /api URLs need to hit the local Flask app.
                if raw_url.startswith("/"):
                    target_url = request.host_url.rstrip("/") + raw_url
                else:
                    target_url = raw_url
                req = _ur.Request(target_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DuyTrisManga/1.0)",
                    "Referer": request.host_url,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                })
                with opener.open(req, timeout=30) as resp:
                    blob = resp.read()
                    ctype = resp.headers.get("Content-Type", "image/jpeg")
            except Exception as e:
                # Add a placeholder text file so the user knows which page failed
                zf.writestr(f"page_{idx:03d}.error.txt", str(e)[:300])
                continue
            # Pick an extension from the content-type
            ext = ".jpg"
            if "png" in ctype: ext = ".png"
            elif "webp" in ctype: ext = ".webp"
            elif "avif" in ctype: ext = ".avif"
            zf.writestr(f"{safe_title}/page_{idx:03d}{ext}", blob)

    buf.seek(0)
    from flask import send_file
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{safe_title}.zip",
    )


# ══════════════════════════════════════════════════════════════════════════════
# MangaPlus catalog (search titles + list chapters) — single-source mode
# ══════════════════════════════════════════════════════════════════════════════
@bp.route("/api/story/mangaplus/search", methods=["POST", "GET"])
def mangaplus_search():
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    keyword = (data.get("keyword") or data.get("q") or data.get("title") or "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "Thiếu từ khoá."}), 400
    limit = max(1, min(50, int(data.get("limit") or 30)))
    try:
        items = mp.search_titles(keyword, limit=limit, proxy_url=_proxy_url() or None)
        return jsonify({
            "ok": True,
            "items": [{**t, "source": "mangaplus"} for t in items],
            "count": len(items),
            "source": "mangaplus",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/mangaplus/details", methods=["POST", "GET"])
def mangaplus_details():
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    title_id = (data.get("manga_id") or data.get("id") or data.get("title_id") or "").strip()
    if not title_id:
        return jsonify({"ok": False, "error": "Thiếu title_id."}), 400
    try:
        res = mp.list_chapters(title_id, proxy_url=_proxy_url() or None)
        manga = {**(res.get("title") or {}), "source": "mangaplus"}
        chapters = []
        for c in (res.get("chapters") or []):
            chapters.append({
                "id": c["id"],
                "chapter": c.get("chapter") or c.get("raw_label") or "",
                "title": c.get("title") or "",
                "language": (manga.get("language") or "ENGLISH"),
                "pages": 0,
                "publish_at": c.get("publish_at") or "",
                "scanlation_group": "MangaPlus",
                "external_url": "",
                "is_external": False,
                "thumbnail_url": c.get("thumbnail_url") or "",
            })
        return jsonify({
            "ok": True,
            "manga": manga,
            "chapters": chapters,
            "chapter_count": len(chapters),
            "languages": res.get("languages") or [],
            "paywalled_count": res.get("paywalled_count") or 0,
            "has_paywall": bool(res.get("has_paywall")),
            "source": "mangaplus",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502


@bp.route("/api/story/mangaplus/chapter_pages_id", methods=["POST", "GET"])
def mangaplus_chapter_pages_id():
    """Variant of /chapter_pages that takes a numeric chapter_id directly
    (no MangaDex external_url required)."""
    from core import mangaplus_client as mp

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
    else:
        data = {k: v for k, v in request.args.items()}
    chapter_id = (data.get("chapter_id") or data.get("id") or "").strip()
    if not chapter_id:
        return jsonify({"ok": False, "error": "Thiếu chapter_id."}), 400
    quality = (data.get("quality") or "high").strip().lower()
    if quality not in ("low", "high", "super_high"):
        quality = "high"
    try:
        pairs = mp.fetch_chapter_pages(
            chapter_id, quality=quality, proxy_url=_proxy_url() or None,
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]}), 502
    pages = [
        "/api/story/mangaplus/image?url=" + urllib.parse.quote(img, safe="")
        + "&key=" + urllib.parse.quote(key or "", safe="")
        for img, key in pairs
    ]
    return jsonify({
        "ok": True,
        "chapter_id": chapter_id,
        "page_count": len(pages),
        "pages": pages,
        "source": "mangaplus",
    })

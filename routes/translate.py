"""Translate Blueprint — /api/translate*, /api/translation_status routes."""
from flask import Blueprint, jsonify, request
from core_app import load_cfg, LOGGER

bp = Blueprint("translate", __name__)


@bp.route("/api/translate_batch", methods=["POST"])
def api_translate_batch():
    """Translate multiple texts in one request to save tokens."""
    data = request.json or {}
    texts = data.get("texts") or []
    provider = data.get("provider", "auto")
    context = data.get("context", "")
    if not texts:
        return jsonify({"results": [], "provider": "none"})
    cfg = load_cfg()
    trans_cfg = cfg.get("translation") or {}
    try:
        from utils.translation import translate_texts
        results, used = translate_texts(texts, trans_cfg, provider, context=context)
        return jsonify({"results": results, "provider": used})
    except Exception as e:
        return jsonify({"results": texts, "provider": "error", "error": str(e)})


@bp.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.json or {}
    text = (data.get("text") or "").strip()
    provider = data.get("provider", "auto")
    context = data.get("context", "")
    if not text:
        return jsonify({"result": "", "provider": "none"})
    cfg = load_cfg()
    trans_cfg = cfg.get("translation") or {}
    try:
        from utils.translation import translate_texts
        results, used = translate_texts([text], trans_cfg, provider, context=context)
        return jsonify({"result": results[0] if results else text, "provider": used})
    except Exception as e:
        return jsonify({"result": text, "provider": "error", "error": str(e)})


@bp.route("/api/translate_descs", methods=["POST"])
def api_translate_descs():
    """Dịch danh sách tiêu đề video sau khi đã tải xong."""
    data = request.json or {}
    descs = data.get("descs", [])
    provider = (data.get("provider") or "").strip()
    if not descs or not provider:
        return jsonify({"results": descs, "provider": "none"})
    cfg = load_cfg()
    tr_cfg = dict(cfg.get("translation") or {})
    tr_cfg["preferred_provider"] = provider
    try:
        from utils.translation import translate_texts
        results, used = translate_texts(descs, tr_cfg, provider)
        if results and len(results) == len(descs):
            return jsonify({"results": results, "provider": used})
        return jsonify({"results": descs, "provider": "error", "error": "Kết quả không khớp số lượng"})
    except Exception as e:
        LOGGER.warning("translate_descs failed: %s", e)
        return jsonify({"results": descs, "provider": "error", "error": str(e)})


@bp.route("/api/translation_status", methods=["GET"])
def translation_status():
    cfg = load_cfg()
    trans_cfg = cfg.get("translation") or {}
    from utils.translation import get_translation_providers
    providers = get_translation_providers(trans_cfg)
    preferred = trans_cfg.get("preferred_provider", "auto")
    return jsonify({
        "providers": providers,
        "preferred": preferred,
        "has_deepseek": bool(trans_cfg.get("deepseek_key")),
        "has_openai": bool(trans_cfg.get("openai_key")),
        "has_hf": bool(trans_cfg.get("hf_token")),
    })


@bp.route("/api/analyze_video_content", methods=["POST"])
def api_analyze_video_content():
    """Use AI to analyze video content and generate titles/descriptions/hashtags for YouTube, TikTok, Facebook."""
    import json as _json
    import urllib.request

    data = request.json or {}
    content = (data.get("content") or "").strip()
    provider = (data.get("provider") or "deepseek").strip().lower()

    if not content:
        return jsonify({"ok": False, "error": "Nội dung trống"}), 400

    cfg = load_cfg()
    trans_cfg = cfg.get("translation") or {}

    api_configs = {
        "deepseek": ("https://api.deepseek.com/v1/chat/completions", trans_cfg.get("deepseek_key", ""), "deepseek-chat"),
        "openai": ("https://api.openai.com/v1/chat/completions", trans_cfg.get("openai_key", ""), "gpt-4o-mini"),
        "groq": ("https://api.groq.com/openai/v1/chat/completions", trans_cfg.get("groq_key", ""), "llama-3.1-8b-instant"),
    }

    # Try requested provider first, then fallback
    order = [provider] + [p for p in ["deepseek", "openai", "groq"] if p != provider]

    prompt = f"""Bạn là chuyên gia marketing video trên mạng xã hội Việt Nam. Phân tích nội dung video sau và tạo thông tin đăng cho 3 nền tảng.

NỘI DUNG VIDEO:
{content[:2000]}

QUY TẮC VỀ TAGS/HASHTAGS:
- Tags phải KHÔNG DẤU (ví dụ: "xuhuong", "haihuoc", "thunghiem", không phải "xu hướng")
- Kết hợp tags tiếng Việt không dấu + tags tiếng Anh phổ biến
- Tags phải phù hợp với nội dung video cụ thể
- Luôn bao gồm các tags xu hướng: xuhuong, viral, fyp, foryou
- Thêm tags tiếng Anh liên quan đến thể loại video (experiment, challenge, satisfying, asmr, funny, etc.)
- Tags ngắn gọn, 1-2 từ, dễ tìm kiếm
- TikTok hashtags phải có # phía trước, YouTube tags không cần #
- TikTok CHỈ ĐƯỢC TỐI ĐA 5 hashtags (không hơn!)

Hãy trả về JSON với cấu trúc sau (không có markdown, chỉ JSON thuần):
{{
  "youtube": {{
    "title": "Tiêu đề hấp dẫn cho YouTube (tối đa 100 ký tự, tiếng Việt)",
    "description": "Mô tả chi tiết cho YouTube (200-500 ký tự, có emoji, có hashtags cuối)",
    "tags": ["xuhuong", "viral", "tag tiếng Việt không dấu", "english tag", "thêm 10-15 tags nữa"]
  }},
  "tiktok": {{
    "caption": "Caption ngắn gọn cho TikTok (tối đa 150 ký tự, tiếng Việt)",
    "description": "Mô tả thêm cho TikTok",
    "hashtags": ["#xuhuong", "#fyp", "#viral", "#tag_khong_dau", "#english_tag"]
  }},
  "facebook": {{
    "title": "Tiêu đề bài đăng Facebook (tiếng Việt, hấp dẫn)",
    "description": "Nội dung bài đăng Facebook (150-300 ký tự, thân thiện, có emoji)",
    "hashtags": ["#xuhuong", "#viral", "#tag_khong_dau", "#english_tag", "thêm 3-5 hashtags"]
  }}
}}"""

    last_error = ""
    for prov in order:
        api_url, api_key, model = api_configs.get(prov, ("", "", ""))
        if not api_key:
            continue
        try:
            payload = _json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 1000,
            }).encode()
            req = urllib.request.Request(
                api_url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = _json.loads(resp.read())

            raw = resp_data["choices"][0]["message"]["content"].strip()
            # Remove markdown code blocks if present
            raw = raw.strip("```json").strip("```").strip()
            result = _json.loads(raw)
            return jsonify({"ok": True, "result": result, "provider": prov})
        except Exception as e:
            last_error = str(e)
            LOGGER.warning("analyze_video_content %s failed: %s", prov, e)
            continue

    return jsonify({"ok": False, "error": f"Tất cả AI provider thất bại: {last_error}"}), 500

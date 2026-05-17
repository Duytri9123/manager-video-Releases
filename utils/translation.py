import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple


def _normalize_provider_name(name: str) -> str:
    if not name:
        return "auto"
    normalized = str(name).strip().lower()
    if normalized in {"hf", "huggingface"}:
        return "huggingface"
    if normalized in {"deepseek", "openai", "google", "groq", "auto"}:
        return normalized
    return "auto"


def _parse_numbered_translation(content: str, size: int) -> List[str]:
    results = [""] * size
    for line in (content or "").split("\n"):
        match = re.match(r"^(\d+)[.)]\s*(.*)", line.strip())
        if not match:
            continue
        idx = int(match.group(1)) - 1
        if 0 <= idx < size:
            results[idx] = (match.group(2) or "").strip()
    return results


def _llm_translate(
    texts: List[str],
    api_url: str,
    api_key: str,
    model: str,
    timeout: int = 60,
    batch_size: int = 30,
    context: str = "",
    target_lang: str = "vi",
) -> List[str]:
    """Translate texts in batches to avoid token limits.
    
    Step 1: AI reads ALL subtitles to fully understand the video content,
            identifies ASR errors, and builds a correction/terminology map.
    Step 2: AI translates each batch using the correction map for consistency.
    """
    if not texts:
        return []

    # Language name mapping for prompts
    _LANG_FULL = {
        "vi": "Vietnamese", "en": "English", "ja": "Japanese", "ko": "Korean",
        "th": "Thai", "id": "Indonesian", "es": "Spanish", "pt": "Portuguese",
        "fr": "French", "de": "German", "ru": "Russian", "ar": "Arabic",
        "hi": "Hindi", "zh": "Chinese",
    }
    target_lang_name = _LANG_FULL.get(target_lang, "Vietnamese")

    all_results: List[str] = [""] * len(texts)

    # Load translation style guide from file
    style_guide = ""
    style_paths = [
        Path(__file__).parent.parent / "config" / "translation_style.txt",
        Path("config/translation_style.txt"),
    ]
    for sp in style_paths:
        if sp.exists():
            try:
                style_guide = sp.read_text(encoding="utf-8").strip()
            except Exception:
                pass
            break

    # ── Step 1: Full content analysis ──────────────────────────────────────────
    # Send ALL subtitles so AI fully understands the video before translating.
    # This ensures consistent terminology and accurate ASR error correction.
    all_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts) if t.strip())
    # Limit to ~3000 chars to stay within token limits, but use as much as possible
    max_analysis_chars = 4000
    if len(all_text) > max_analysis_chars:
        # Take first half + last quarter for better coverage
        half = max_analysis_chars * 2 // 3
        quarter = max_analysis_chars // 3
        all_text = all_text[:half] + "\n...\n" + all_text[-quarter:]

    analysis_system = (
        "You are a Chinese video content analyst. Your job is to read auto-transcribed "
        "subtitles (ASR output from Douyin/TikTok) and figure out what the video is ACTUALLY about. "
        "ASR makes MANY errors — words that sound similar get mixed up. You must use context "
        "to determine the correct words."
    )

    analysis_prompt = (
        f"VIDEO TITLE: {context or '(unknown)'}\n\n"
        f"FULL SUBTITLES (auto-transcribed, contains errors):\n{all_text}\n\n"
        "TASK — Analyze this video thoroughly:\n\n"
        "1. SUMMARY: What is this video about? Describe the content in 2-3 sentences.\n"
        "   Include: topic, what happens, key subjects/objects mentioned.\n\n"
        "2. ASR CORRECTIONS: List ALL words that are likely misheard by ASR.\n"
        "   These are words that SOUND similar in Chinese but don't make sense in context.\n"
        "   Format: 错误词 → 正确词 (explanation)\n\n"
        "3. TERMINOLOGY: List key terms that appear repeatedly and their correct Vietnamese translations.\n"
        "   These MUST be used consistently throughout all subtitle translations.\n"
        "   Format: 中文 = Tiếng Việt\n\n"
        "4. TONE: What tone/style should the Vietnamese translation use?\n"
        "   (e.g., educational, entertaining, dramatic, casual narration)\n\n"
        "OUTPUT FORMAT (strict):\n"
        "SUMMARY: <2-3 sentences describing the video>\n"
        "CORRECTIONS:\n"
        "- <wrong> → <correct> (<why>)\n"
        "TERMS:\n"
        f"- <Chinese> = <{target_lang_name}>\n"
        "TONE: <style description>\n"
    )

    correction_map = ""
    try:
        analysis_payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": analysis_system},
                {"role": "user", "content": analysis_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1500,
        }).encode()
        analysis_req = urllib.request.Request(
            api_url, data=analysis_payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(analysis_req, timeout=timeout) as response:
            analysis_data = json.loads(response.read())
        correction_map = analysis_data["choices"][0]["message"]["content"].strip()
    except Exception:
        correction_map = ""

    # ── Step 2: Translate in batches using the analysis ────────────────────────
    system_msg = (
        f"You are an expert {target_lang_name} subtitle translator for Chinese social media videos. "
        f"You produce natural, engaging {target_lang_name} subtitles that sound like a native "
        f"{target_lang_name} content creator is narrating. You ALWAYS fix ASR errors before translating."
    )

    for batch_start in range(0, len(texts), batch_size):
        batch = texts[batch_start: batch_start + batch_size]
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))

        # Add surrounding lines for continuity between batches
        prev_context = ""
        next_context = ""
        if batch_start > 0:
            prev_lines = texts[max(0, batch_start - 3): batch_start]
            prev_context = "\n".join(f"  {t}" for t in prev_lines if t.strip())
        if batch_start + batch_size < len(texts):
            next_lines = texts[batch_start + batch_size: batch_start + batch_size + 3]
            next_context = "\n".join(f"  {t}" for t in next_lines if t.strip())

        # Build the translation prompt
        parts = []
        parts.append(f"VIDEO: {context or '(unknown)'}")

        if correction_map:
            parts.append(f"\nVIDEO ANALYSIS (use this to fix errors and maintain consistency):\n{correction_map}")

        if style_guide:
            parts.append(f"\nSTYLE GUIDE:\n{style_guide}")

        if prev_context:
            parts.append(f"\nPREVIOUS LINES (already translated, for continuity):\n{prev_context}")

        parts.append(f"\nLINES TO TRANSLATE:\n{numbered}")

        if next_context:
            parts.append(f"\nNEXT LINES (coming up, for context):\n{next_context}")

        parts.append(
            "\nRULES:\n"
            "1. Fix ALL ASR errors using the ANALYSIS above before translating.\n"
            "2. Use TERMS list for consistent translations — same word = same translation everywhere.\n"
            f"3. Each line must be a complete, natural {target_lang_name} sentence.\n"
            "4. Match the TONE described in the analysis.\n"
            "5. Keep translations concise (subtitle-friendly, not too long).\n"
            "6. OUTPUT: Return ONLY numbered lines (1. ..., 2. ...). No explanations, no extra text."
        )

        prompt = "\n".join(parts)

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": min(4000, len(batch) * 120),
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
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
        content = data["choices"][0]["message"]["content"].strip()
        batch_results = _parse_numbered_translation(content, len(batch))
        for i, result in enumerate(batch_results):
            all_results[batch_start + i] = result

    return all_results


def get_translation_providers(trans_cfg: Dict) -> List[str]:
    providers = []
    if (trans_cfg or {}).get("deepseek_key"):
        providers.append("deepseek")
    if (trans_cfg or {}).get("groq_key"):
        providers.append("groq")
    if (trans_cfg or {}).get("openai_key"):
        providers.append("openai")
    if (trans_cfg or {}).get("hf_token"):
        providers.append("huggingface")
    providers.append("google")
    return providers


def build_provider_order(trans_cfg: Dict, preferred_provider: str = "auto") -> List[str]:
    available = get_translation_providers(trans_cfg)
    preferred = _normalize_provider_name(preferred_provider)
    if preferred != "auto" and preferred in available:
        ordered = [preferred] + [p for p in available if p != preferred]
        return ordered
    return available


def translate_texts(
    texts: List[str],
    trans_cfg: Dict,
    preferred_provider: str = "auto",
    context: str = "",
    target_lang: str = "vi",
) -> Tuple[List[str], str]:
    if not texts:
        return [], "none"

    # Track which indices have non-empty text to translate
    active_indices = [i for i, t in enumerate(texts) if t and str(t).strip()]
    source_texts = [texts[i] for i in active_indices]

    # If all texts are whitespace-only, return originals as fallback
    if not source_texts:
        return list(texts), "fallback"

    cfg = trans_cfg or {}
    deepseek_key = cfg.get("deepseek_key", "") or ""
    openai_key = cfg.get("openai_key", "") or ""
    groq_key = cfg.get("groq_key", "") or ""
    groq_model = cfg.get("groq_model", "llama-3.1-8b-instant") or "llama-3.1-8b-instant"
    hf_token = cfg.get("hf_token", "") or ""

    provider_order = build_provider_order(cfg, preferred_provider)

    def _rebuild(translated_active: List[str]) -> List[str]:
        """Map translated results back to original indices, preserving whitespace-only entries."""
        result = list(texts)
        for i, idx in enumerate(active_indices):
            if i < len(translated_active):
                result[idx] = translated_active[i]
        return result

    _errors: List[str] = []

    for provider in provider_order:
        try:
            if provider == "deepseek" and deepseek_key:
                result = _llm_translate(
                    source_texts,
                    "https://api.deepseek.com/v1/chat/completions",
                    deepseek_key,
                    "deepseek-chat",
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "deepseek"
                _errors.append("deepseek: empty result")

            elif provider == "openai" and openai_key:
                result = _llm_translate(
                    source_texts,
                    "https://api.openai.com/v1/chat/completions",
                    openai_key,
                    "gpt-4o-mini",
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "openai"
                _errors.append("openai: empty result")

            elif provider == "groq" and groq_key:
                result = _llm_translate(
                    source_texts,
                    "https://api.groq.com/openai/v1/chat/completions",
                    groq_key,
                    groq_model,
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "groq"
                _errors.append("groq: empty result")

            elif provider == "huggingface" and hf_token:
                hf_endpoints = [
                    (
                        "https://router.huggingface.co/novita/v3/openai/chat/completions",
                        "Qwen/Qwen2.5-72B-Instruct",
                    ),
                    (
                        "https://router.huggingface.co/featherless-ai/v1/chat/completions",
                        "Qwen/Qwen2.5-7B-Instruct",
                    ),
                    (
                        "https://router.huggingface.co/together/v1/chat/completions",
                        "Qwen/Qwen2.5-72B-Instruct",
                    ),
                    (
                        "https://router.huggingface.co/sambanova/v1/chat/completions",
                        "Qwen/Qwen2.5-72B-Instruct",
                    ),
                ]
                for hf_url, hf_model in hf_endpoints:
                    result = _llm_translate(source_texts, hf_url, hf_token, hf_model, context=context, target_lang=target_lang)
                    if any(result):
                        return _rebuild(result), "huggingface"

            elif provider == "google":
                translated = []
                for text in source_texts:
                    query = urllib.parse.quote(text[:500])
                    url = (
                        "https://translate.googleapis.com/translate_a/single"
                        f"?client=gtx&sl=auto&tl={target_lang}&dt=t&dj=1&q={query}"
                    )
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Accept-Language": "vi",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=6) as response:
                        data = json.loads(response.read())
                    if isinstance(data, dict):
                        sentences = data.get("sentences") or []
                        translated.append("".join(s.get("trans", "") for s in sentences))
                    else:
                        translated.append("".join(p[0] for p in data[0] if p[0]))
                if any(translated):
                    return _rebuild(translated), "google"
        except Exception as e:
            _errors.append(f"{provider}: {e}")
            continue

    # All providers failed — raise with details so caller can log it
    if _errors:
        raise RuntimeError("All translation providers failed: " + " | ".join(_errors))
    return list(texts), "fallback"


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class BatchTranslator:
    """Batch translation with multi-provider fallback.

    Fallback chain: DeepSeek → OpenAI → HuggingFace → Google
    """

    def __init__(self, trans_cfg: dict):
        self._cfg = trans_cfg or {}

    def translate(
        self,
        texts: List[str],
        preferred_provider: str = "auto",
        context: str = "",
        target_lang: str = "vi",
    ) -> Tuple[List[str], str]:
        """Translate a list of texts in a single batch call.

        Returns (translated_texts, provider_used).
        If all providers fail, returns (original_texts, "fallback").
        """
        return translate_texts(texts, self._cfg, preferred_provider, context=context, target_lang=target_lang)

    def write_vi_srt(
        self,
        segments: List[dict],
        translations: List[str],
        out_path: Path,
    ) -> None:
        """Write a Vietnamese SRT file.

        Args:
            segments: List of dicts with 'start' and 'end' keys (seconds).
            translations: Translated text for each segment.
            out_path: Destination path for the .srt file.
        """
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        lines: List[str] = []
        for i, (seg, text) in enumerate(zip(segments, translations), start=1):
            start_ts = _format_srt_time(float(seg.get("start", 0)))
            end_ts = _format_srt_time(float(seg.get("end", 0)))
            lines.append(str(i))
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(text or "")
            lines.append("")
        out_path.write_text("\n".join(lines), encoding="utf-8")

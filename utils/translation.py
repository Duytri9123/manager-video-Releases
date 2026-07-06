import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple


def _parse_chat_response_body(raw: bytes) -> str:
    """Extract assistant content from a /v1/chat/completions response.

    Handles both standard JSON ({choices:[{message:{content}}]}) and SSE
    streaming bodies (data: {…}\n\n…) — some upstreams ignore
    `stream:false` and ship SSE anyway.
    """
    if not raw:
        return ""
    # Try plain JSON first.
    try:
        data = json.loads(raw)
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
    except Exception:
        pass
    # SSE fallback: concatenate every delta.content chunk.
    text = raw.decode("utf-8", "replace")
    pieces: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = json.loads(payload)
        except Exception:
            continue
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            pieces.append(delta["content"])
        elif isinstance((choice.get("message") or {}).get("content"), str):
            pieces.append(choice["message"]["content"])
    return "".join(pieces).strip()


def _normalize_provider_name(name: str) -> str:
    if not name:
        return "auto"
    normalized = str(name).strip().lower()
    if normalized in {"hf", "huggingface"}:
        return "huggingface"
    if normalized in {"9r", "nine_router", "ninerouter", "9router"}:
        return "9router"
    if normalized in {"deepseek", "openai", "google", "groq", "9router", "auto"}:
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
            "stream": False,
        }).encode()
        analysis_req = urllib.request.Request(
            api_url, data=analysis_payload, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(analysis_req, timeout=timeout) as response:
            correction_map = _parse_chat_response_body(response.read())
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
            "max_tokens": max(2048, min(8000, len(batch) * 120)),
            "stream": False,
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
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw_body = response.read()
        except Exception:
            raise
        if not raw_body:
            # 9Router occasionally streams 0 bytes when an upstream chain
            # exhausts itself. Skip this batch instead of blowing up.
            continue
        content = _parse_chat_response_body(raw_body)
        if not content:
            continue
        batch_results = _parse_numbered_translation(content, len(batch))
        for i, result in enumerate(batch_results):
            all_results[batch_start + i] = result

    return all_results


def load_api_keys_status() -> Dict:
    import json
    from pathlib import Path
    root_dir = Path(__file__).parent.parent
    status_file = root_dir / ".state" / "api_keys_status.json"
    if status_file.exists():
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def is_9router_working(nr_cfg: Dict) -> bool:
    import urllib.request
    endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
    api_key = (nr_cfg.get("api_key") or "").strip()
    if not api_key:
        return False
    try:
        req = urllib.request.Request(
            f"{endpoint}/models",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=0.5) as r:
            return r.status == 200
    except Exception:
        return False


def parse_provider_and_model(preferred: str) -> Tuple[str, str]:
    if not preferred or preferred == "auto":
        return "auto", ""
    if "/" in preferred:
        parts = preferred.split("/", 1)
        prov = parts[0].lower()
        model = parts[1]
        return prov, model
    return preferred.lower(), ""


def is_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    # Patterns for TTS
    if "tts" in mid or "fastpitch" in mid or "tacotron2" in mid or "speech" in mid:
        return False
    # Patterns for STT
    if "whisper" in mid or "stt" in mid:
        return False
    # Patterns for Embeddings
    if "embedding" in mid or "embed" in mid:
        return False
    # Patterns for Image Generation
    if "flux" in mid or "dall-e" in mid or "stable-diffusion" in mid or "generator" in mid or (mid.endswith("-image") and "image-to-text" not in mid):
        return False
    return True


def get_9router_models(nr_cfg: Dict) -> List[Dict]:
    if not nr_cfg:
        return []
    endpoint = nr_cfg.get("endpoint") or "http://localhost:20128/v1"
    api_key = nr_cfg.get("api_key") or ""
    headers = {"Accept": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key}"
    
    url = f"{endpoint.rstrip('/')}/models"
    try:
        import urllib.request
        import json
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read())
                models = []
                for it in body.get("data") or []:
                    mid = it.get("id")
                    if mid:
                        if is_chat_model(mid):
                            models.append({
                                "id": f"9router/{mid}",
                                "name": mid,
                                "provider": "9router",
                                "owned_by": it.get("owned_by", "")
                            })
                return models
    except Exception:
        pass
    return []


def get_translation_models(trans_cfg: Dict, full_cfg: Dict | None = None) -> List[Dict]:
    models = []
    
    # 1. Google Translate
    models.append({
        "id": "google",
        "name": "Google Translate",
        "provider": "google"
    })
    
    # 2. HuggingFace
    status = load_api_keys_status()
    def is_provider_ok(name: str) -> bool:
        if name in status and not status[name].get("ok", True):
            return False
        return True

    if (trans_cfg or {}).get("hf_token") and is_provider_ok("huggingface"):
        models.append({
            "id": "huggingface",
            "name": "HuggingFace Qwen-2.5",
            "provider": "huggingface"
        })
        
    # 3. OpenAI
    if (trans_cfg or {}).get("openai_key") and is_provider_ok("openai"):
        models.append({
            "id": "openai/gpt-4o-mini",
            "name": "OpenAI: gpt-4o-mini",
            "provider": "openai"
        })
        models.append({
            "id": "openai/gpt-4o",
            "name": "OpenAI: gpt-4o",
            "provider": "openai"
        })
        
    # 4. DeepSeek
    if (trans_cfg or {}).get("deepseek_key") and is_provider_ok("deepseek"):
        models.append({
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek: deepseek-chat",
            "provider": "deepseek"
        })

    # 5. Groq
    if (trans_cfg or {}).get("groq_key") and is_provider_ok("groq"):
        groq_model = (trans_cfg or {}).get("groq_model", "llama-3.1-8b-instant")
        models.append({
            "id": f"groq/{groq_model}",
            "name": f"Groq: {groq_model}",
            "provider": "groq"
        })

    # 5b. Gemini
    gemini_key = ((full_cfg or {}).get("gemini_video") or {}).get("api_key") or ""
    if gemini_key and is_provider_ok("gemini"):
        models.append({
            "id": "gemini/gemini-2.0-flash",
            "name": "Gemini: gemini-2.0-flash",
            "provider": "gemini"
        })
        models.append({
            "id": "gemini/gemini-2.5-flash",
            "name": "Gemini: gemini-2.5-flash",
            "provider": "gemini"
        })

    # 6. 9Router
    nr = ((full_cfg or {}).get("nine_router") or {}) if isinstance(full_cfg, dict) else {}
    if (nr.get("api_key") or "").strip() and is_9router_working(nr):
        nr_models = get_9router_models(nr)
        models.extend(nr_models)
        
    return models


def get_translation_providers(trans_cfg: Dict, full_cfg: Dict | None = None) -> List[str]:
    providers = []
    status = load_api_keys_status()

    def is_provider_ok(name: str) -> bool:
        if name in status and not status[name].get("ok", True):
            return False
        return True

    # 9Router check FIRST (Try 9Router before direct keys)
    nr = ((full_cfg or {}).get("nine_router") or {}) if isinstance(full_cfg, dict) else {}
    if (nr.get("api_key") or "").strip():
        if is_9router_working(nr):
            providers.append("9router")

    if (trans_cfg or {}).get("deepseek_key") and is_provider_ok("deepseek"):
        providers.append("deepseek")
    if (trans_cfg or {}).get("openai_key") and is_provider_ok("openai"):
        providers.append("openai")
    if (trans_cfg or {}).get("groq_key") and is_provider_ok("groq"):
        providers.append("groq")

    gemini_key = ((full_cfg or {}).get("gemini_video") or {}).get("api_key") or ""
    if gemini_key and is_provider_ok("gemini"):
        providers.append("gemini")

    if (trans_cfg or {}).get("hf_token") and is_provider_ok("huggingface"):
        providers.append("huggingface")

    providers.append("google")
    return providers


def build_provider_order(trans_cfg: Dict, preferred_provider: str = "auto", full_cfg: Dict | None = None) -> List[str]:
    available = get_translation_providers(trans_cfg, full_cfg=full_cfg)
    prov_req, _ = parse_provider_and_model(preferred_provider)
    preferred = _normalize_provider_name(prov_req)
    if preferred != "auto" and preferred in available:
        # Nếu người dùng chọn một provider cụ thể, chỉ dùng provider đó, không tự động fallback
        return [preferred]
    return available


def mark_provider_failed(provider_name: str, error_message: str):
    try:
        import json
        from pathlib import Path
        root_dir = Path(__file__).parent.parent
        status_file = root_dir / ".state" / "api_keys_status.json"
        status_data = {}
        if status_file.exists():
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    status_data = json.load(f)
            except Exception:
                pass
        status_data[provider_name] = {"ok": False, "error": error_message}
        status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def translate_texts(
    texts: List[str],
    trans_cfg: Dict,
    preferred_provider: str = "auto",
    context: str = "",
    target_lang: str = "vi",
    nine_router_cfg: Dict | None = None,
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
    nr = nine_router_cfg or cfg.get("_nine_router") or {}  # legacy passthrough
    nine_key = (nr.get("api_key") or "").strip() if isinstance(nr, dict) else ""
    nine_endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/") if isinstance(nr, dict) else "http://localhost:20128/v1"
    nine_model = (nr.get("default_model") or "duytris").strip() if isinstance(nr, dict) else "duytris"

    try:
        from core.config import load_cfg
        full_cfg_live = load_cfg()
    except Exception:
        full_cfg_live = {}
    gemini_key = ""
    if isinstance(full_cfg_live, dict):
        gemini_key = (full_cfg_live.get("gemini_video") or {}).get("api_key", "") or ""

    # Parse preferred provider/model
    prov_req, model_req = parse_provider_and_model(preferred_provider)
    if prov_req == "9router" and model_req:
        nine_model = model_req

    # Synthesize a fake_full_cfg so build_provider_order can see 9Router
    # and Gemini availability via its existing API.
    full_cfg_fake = {
        "nine_router": nr if isinstance(nr, dict) else {},
        "gemini_video": {"api_key": gemini_key}
    }
    provider_order = build_provider_order(cfg, preferred_provider, full_cfg=full_cfg_fake)

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
            if provider == "9router" and nine_key:
                candidates = [nine_model]
                try:
                    nr_models = get_9router_models(nr)
                    available_ids = {m["id"].replace("9router/", "") for m in nr_models}
                    fast_priorities = [
                        "gemini-2.5-flash",
                        "gemini-1.5-flash",
                        "gemini-3-flash",
                        "gpt-4o-mini",
                        "llama-3.1-8b-instant",
                    ]
                    for fm in fast_priorities:
                        if fm in available_ids and fm not in candidates:
                            candidates.append(fm)
                except Exception:
                    pass

                last_nr_err = None
                success = False
                for model_cand in candidates:
                    try:
                        result = _llm_translate(
                            source_texts,
                            f"{nine_endpoint}/chat/completions",
                            nine_key,
                            model_cand,
                            context=context,
                            target_lang=target_lang,
                        )
                        if any(result):
                            return _rebuild(result), "9router"
                    except Exception as e:
                        last_nr_err = e
                        continue
                if last_nr_err:
                    raise last_nr_err
                _errors.append("9router: empty result")

            elif provider == "deepseek" and deepseek_key:
                ds_model = model_req if prov_req == "deepseek" and model_req else "deepseek-chat"
                result = _llm_translate(
                    source_texts,
                    "https://api.deepseek.com/v1/chat/completions",
                    deepseek_key,
                    ds_model,
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "deepseek"
                _errors.append("deepseek: empty result")

            elif provider == "openai" and openai_key:
                oa_model = model_req if prov_req == "openai" and model_req else "gpt-4o-mini"
                result = _llm_translate(
                    source_texts,
                    "https://api.openai.com/v1/chat/completions",
                    openai_key,
                    oa_model,
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "openai"
                _errors.append("openai: empty result")

            elif provider == "groq" and groq_key:
                g_model = model_req if prov_req == "groq" and model_req else groq_model
                result = _llm_translate(
                    source_texts,
                    "https://api.groq.com/openai/v1/chat/completions",
                    groq_key,
                    g_model,
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "groq"
                _errors.append("groq: empty result")

            elif provider == "gemini" and gemini_key:
                gem_model = model_req if prov_req == "gemini" and model_req else "gemini-2.5-flash"
                result = _llm_translate(
                    source_texts,
                    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                    gemini_key,
                    gem_model,
                    context=context,
                    target_lang=target_lang,
                )
                if any(result):
                    return _rebuild(result), "gemini"
                _errors.append("gemini: empty result")

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
                            "Connection": "close"
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
            err_str = str(e).lower()
            if "402" in err_str or "429" in err_str or "quota" in err_str or "exceeded" in err_str or "balance" in err_str or "401" in err_str or "403" in err_str or "unauthorized" in err_str or "key" in err_str:
                mark_provider_failed(provider, str(e))
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

    Fallback chain: DeepSeek → OpenAI → HuggingFace → Google → 9Router
    """

    def __init__(self, trans_cfg: dict, nine_router_cfg: dict | None = None):
        self._cfg = trans_cfg or {}
        self._nine = nine_router_cfg or {}

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
        return translate_texts(
            texts, self._cfg, preferred_provider,
            context=context, target_lang=target_lang,
            nine_router_cfg=self._nine,
        )

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

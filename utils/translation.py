import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple
import sqlite3


def load_db_connections() -> List[dict]:
    import sqlite3
    import os
    import json
    from pathlib import Path

    # 1. Load disabled status from .state/providers.db
    disabled_providers = set()
    legacy_db = Path(__file__).parent.parent / ".state" / "providers.db"
    if legacy_db.exists():
        try:
            conn_legacy = sqlite3.connect(legacy_db)
            rows_legacy = conn_legacy.execute("SELECT provider, enabled FROM provider_connections").fetchall()
            conn_legacy.close()
            prov_map = {}
            for p, en in rows_legacy:
                p_norm = p.lower()
                if p_norm not in prov_map:
                    prov_map[p_norm] = []
                prov_map[p_norm].append(bool(en))
            for p_norm, en_list in prov_map.items():
                if not any(en_list):
                    disabled_providers.add(p_norm)
        except Exception:
            pass

    # 2. Also check system config for provider toggles
    try:
        from core.config import load_cfg
        cfg = load_cfg()
        providers_cfg = cfg.get("providers") or {}
        for p_id, p_data in providers_cfg.items():
            conns = (p_data or {}).get("connections") or []
            if not conns or all(c.get("enabled") is False for c in conns):
                disabled_providers.add(p_id.lower())
    except Exception:
        pass

    appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    db_path = os.path.join(appdata, "dtrouter", "db", "data.sqlite")
    if not os.path.exists(db_path):
        db_path = os.path.join(appdata, "9router", "db", "data.sqlite")
    if not os.path.exists(db_path):
        return []
        
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, provider, name, data, isActive FROM providerConnections WHERE isActive != 0").fetchall()
        conn.close()
        res = []
        for r in rows:
            d = dict(r)
            prov = (d.get("provider") or "").lower()
            if prov in disabled_providers:
                continue
            try:
                js_data = json.loads(d.get("data") or "{}")
                if js_data.get("enabled") is False or js_data.get("testStatus") == "unavailable":
                    continue
                d["api_key"] = js_data.get("apiKey") or js_data.get("accessToken") or ""
                d["base_url"] = js_data.get("baseUrl") or ""
            except Exception:
                d["api_key"] = ""
                d["base_url"] = ""
            
            # Non-noAuth providers MUST have a valid non-empty API key or token
            if prov not in ["opencode", "opencodefree", "google"] and not d["api_key"].strip():
                continue

            d["enabled"] = d["isActive"]
            d["status"] = "active"
            res.append(d)
        return res
    except Exception:
        return []


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
    if normalized in {"9r", "dtrouter", "ninerouter"}:
        return "dtrouter"
    if normalized in {"opencode", "opencodefree", "oc"}:
        return "opencode"
    if normalized in {"antigravity", "ag"}:
        return "antigravity"
    if normalized in {"codex", "cx"}:
        return "codex"
    if normalized in {"deepseek", "openai", "google", "groq", "dtrouter", "auto", "gemini", "nvidia"}:
        return normalized
    return "auto"


def _parse_numbered_translation(content: str, size: int) -> List[str]:
    results = [""] * size
    for line in (content or "").split("\n"):
        line_clean = line.strip()
        if not line_clean:
            continue
        match = re.match(r"^[*\s#]*(\d+)[.)、:\s-]+\s*(.*)", line_clean)
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < size:
                val = match.group(2).strip()
                val = re.sub(r"^\*+|\*+$", "", val).strip()
                results[idx] = val
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
    # Skip ASR analysis for short batches (e.g. video titles/descriptions) or weak/free models
    is_weak_model = "opencode" in model.lower() or "free" in model.lower() or len(texts) <= 15
    
    if not is_weak_model:
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

    # ── Step 2: Parallel sub-batch translation for maximum speed ────────────────
    system_msg = (
        f"You are an expert {target_lang_name} subtitle translator for Chinese social media videos. "
        f"You produce natural, engaging {target_lang_name} subtitles. ALWAYS output numbered lines only."
    )

    sub_size = 5 if len(texts) > 5 else len(texts)
    sub_batches = []
    for b_start in range(0, len(texts), sub_size):
        sub_batches.append((b_start, texts[b_start: b_start + sub_size]))

    def _translate_sub_batch(b_start: int, batch: List[str]) -> Tuple[int, List[str]]:
        numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(batch))
        parts = []
        if context:
            parts.append(f"VIDEO: {context}")
        if correction_map:
            parts.append(f"ANALYSIS:\n{correction_map}")
        if style_guide:
            parts.append(f"STYLE GUIDE:\n{style_guide}")
        parts.append(f"LINES TO TRANSLATE:\n{numbered}")
        parts.append(
            "\nRULES:\n"
            f"1. Each line must be a complete, natural {target_lang_name} sentence.\n"
            "2. Keep translations concise and natural.\n"
            "3. OUTPUT: Return ONLY numbered lines (1. ..., 2. ...). No explanations, no extra text."
        )
        prompt = "\n".join(parts)
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max(512, min(4096, len(batch) * 90)),
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
            if raw_body:
                content = _parse_chat_response_body(raw_body)
                if content:
                    return b_start, _parse_numbered_translation(content, len(batch))
        except Exception:
            pass
        return b_start, [""] * len(batch)

    from concurrent.futures import ThreadPoolExecutor
    max_w = min(8, max(1, len(sub_batches)))
    with ThreadPoolExecutor(max_workers=max_w) as executor:
        futures = [executor.submit(_translate_sub_batch, bs, b) for bs, b in sub_batches]
        for fut in futures:
            b_start, batch_results = fut.result()
            for i, res in enumerate(batch_results):
                if b_start + i < len(texts):
                    all_results[b_start + i] = res

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


def is_dtrouter_working(nr_cfg: Dict) -> bool:
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
        with urllib.request.urlopen(req, timeout=2.0) as r:
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
    if "flux" in mid or "dall-e" in mid or "stable-diffusion" in mid or "generator" in mid or "image" in mid:
        return False
    # Patterns for Code/Agent tools (except chat ones)
    if "starcoder" in mid or "copilot" in mid:
        return False
    return True


def get_dtrouter_active_providers() -> set[str] | None:
    """Read active provider names (returns None to avoid 9router DB access)."""
    return None


def _matches_provider(prefix: str, active_providers: set[str]) -> bool:
    prefix = prefix.lower()
    if prefix in active_providers:
        return True
    for p in active_providers:
        if prefix in p or p in prefix:
            return True
        if prefix == "gc" and "gemini-cli" in p:
            return True
        if prefix == "ag" and "antigravity" in p:
            return True
        if prefix == "bpm" and "byteplus" in p:
            return True
        if prefix == "kc" and "kilocode" in p:
            return True
    return False


def get_dtrouter_models(nr_cfg: Dict) -> List[Dict]:
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
                
                active_providers = get_dtrouter_active_providers()
                
                for it in body.get("data") or []:
                    mid = it.get("id")
                    if mid:
                        if is_chat_model(mid):
                            parts = mid.split('/')
                            # If it's a provider model (e.g. prefix/model_name), check if provider is active
                            if len(parts) > 1 and active_providers is not None:
                                prefix = parts[0]
                                if not _matches_provider(prefix, active_providers):
                                    continue
                                    
                            models.append({
                                "id": f"dtrouter/{mid}",
                                "name": mid,
                                "provider": "dtrouter",
                                "owned_by": it.get("owned_by", "")
                            })
                return models
    except Exception:
        pass
    return []


def get_enabled_models_for_provider(provider_id: str, provider_alias: str) -> List[dict]:
    import sqlite3
    import os
    import json
    try:
        from templates.pages.config.route import DEFAULT_PROVIDER_MODELS
    except Exception:
        DEFAULT_PROVIDER_MODELS = {}

    defaults = list(DEFAULT_PROVIDER_MODELS.get(provider_id, []))
    
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    db_path = os.path.join(appdata, "dtrouter", "db", "data.sqlite")
    if not os.path.exists(db_path):
        db_path = os.path.join(appdata, "9router", "db", "data.sqlite")
        
    disabled_set = set()
    custom_list = []
    
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            
            # Fetch disabled models for this provider alias or provider id
            cur.execute("SELECT key, value FROM kv WHERE scope='disabledModels'")
            for key, val in cur.fetchall():
                if key.lower() in [provider_id.lower(), provider_alias.lower()]:
                    try:
                        arr = json.loads(val)
                        if isinstance(arr, list):
                            for dis in arr:
                                disabled_set.add(str(dis).lower())
                    except Exception:
                        pass
                        
            # Fetch custom models for this provider
            cur.execute("SELECT key, value FROM kv WHERE scope='customModels'")
            for key, val in cur.fetchall():
                try:
                    data = json.loads(val)
                    p_alias = data.get("providerAlias", "").lower()
                    if p_alias in [provider_id.lower(), provider_alias.lower()]:
                        m_id = data.get("id")
                        if m_id:
                            custom_list.append({"id": m_id, "name": data.get("name") or m_id, "type": "llm"})
                except Exception:
                    pass
            conn.close()
        except Exception:
            pass

    # Combine defaults + custom
    all_models = []
    seen = set()
    for m in defaults + custom_list:
        m_id = m.get("id", "")
        if m_id and m_id not in seen:
            seen.add(m_id)
            all_models.append(m)

    # Filter out disabled models and non-LLM models
    enabled_models = []
    for m in all_models:
        m_id = m.get("id", "")
        if m.get("type") in ["llm", "chat", None, ""]:
            if m_id.lower() in disabled_set or m_id.split("/")[-1].lower() in disabled_set:
                continue
            enabled_models.append(m)
            
    return enabled_models


def get_translation_models(trans_cfg: Dict, full_cfg: Dict | None = None) -> List[Dict]:
    models = []
    
    # 1. Google Translate (always active)
    models.append({
        "id": "google",
        "name": "Google Translate",
        "provider": "google",
        "owned_by": "google"
    })

    db_conns = load_db_connections()
    db_providers = {c["provider"] for c in db_conns}

    # OpenCode Free (always active)
    oc_enabled = get_enabled_models_for_provider("opencode", "oc")
    for m in oc_enabled:
        models.append({
            "id": f"opencode/{m['id']}",
            "name": m['name'],
            "provider": "opencode",
            "owned_by": "oc"
        })

    # Provider map: (provider_id, provider_alias)
    provider_map = [
        ("antigravity", "ag"),
        ("codex", "cx"),
        ("openai", "openai"),
        ("deepseek", "deepseek"),
        ("groq", "groq"),
        ("gemini", "gc"),
        ("nvidia", "nvidia"),
        ("huggingface", "huggingface"),
    ]

    for p_id, p_alias in provider_map:
        if p_id in db_providers or (p_id == "gemini" and ((full_cfg or {}).get("gemini_video") or {}).get("api_key")):
            enabled_m = get_enabled_models_for_provider(p_id, p_alias)
            for m in enabled_m:
                models.append({
                    "id": f"{p_id}/{m['id']}",
                    "name": m['name'],
                    "provider": p_id,
                    "owned_by": p_alias
                })

    return models


def get_translation_providers(trans_cfg: Dict, full_cfg: Dict | None = None) -> List[str]:
    providers = []
    db_conns = load_db_connections()
    for c in db_conns:
        prov = c["provider"]
        if prov not in providers:
            providers.append(prov)

    status = load_api_keys_status()
    def is_provider_ok(name: str) -> bool:
        if name in status and not status[name].get("ok", True):
            return False
        return True

    if "opencode" not in providers:
        providers.append("opencode")

    if "deepseek" not in providers and (trans_cfg or {}).get("deepseek_key") and is_provider_ok("deepseek"):
        providers.append("deepseek")
    if "openai" not in providers and (trans_cfg or {}).get("openai_key") and is_provider_ok("openai"):
        providers.append("openai")
    if "groq" not in providers and (trans_cfg or {}).get("groq_key") and is_provider_ok("groq"):
        providers.append("groq")

    gemini_key = ((full_cfg or {}).get("gemini_video") or {}).get("api_key") or ""
    if "gemini" not in providers and gemini_key and is_provider_ok("gemini"):
        providers.append("gemini")

    if "huggingface" not in providers and (trans_cfg or {}).get("hf_token") and is_provider_ok("huggingface"):
        providers.append("huggingface")

    if "google" not in providers:
        providers.append("google")
    return providers


def build_provider_order(trans_cfg: Dict, preferred_provider: str = "auto", full_cfg: Dict | None = None) -> List[str]:
    available = get_translation_providers(trans_cfg, full_cfg=full_cfg)
    prov_req, _ = parse_provider_and_model(preferred_provider)
    preferred = _normalize_provider_name(prov_req)
    if preferred != "auto":
        order = [preferred]
        for p in available:
            if p not in order:
                order.append(p)
        return order
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


def _translate_google_parallel(texts: List[str], target_lang: str = "vi") -> List[str]:
    from concurrent.futures import ThreadPoolExecutor
    def _fetch_one(text: str) -> str:
        if not text or not str(text).strip():
            return ""
        try:
            query = urllib.parse.quote(str(text)[:500])
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&dj=1&q={query}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "vi", "Connection": "close"},
            )
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read())
            if isinstance(data, dict):
                sentences = data.get("sentences") or []
                return "".join(s.get("trans", "") for s in sentences)
            elif isinstance(data, list) and data and data[0]:
                return "".join(p[0] for p in data[0] if isinstance(p, list) and p and p[0])
        except Exception:
            pass
        return text

    with ThreadPoolExecutor(max_workers=min(12, max(1, len(texts)))) as executor:
        return list(executor.map(_fetch_one, texts))


def translate_texts(
    texts: List[str],
    trans_cfg: Dict,
    preferred_provider: str = "auto",
    context: str = "",
    target_lang: str = "vi",
    dtrouter_cfg: Dict | None = None,
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
    nr = dtrouter_cfg or cfg.get("_dtrouter") or {}  # legacy passthrough
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

    # Load active connections from DB
    db_conns = load_db_connections()
    db_conns_map = {}
    for c in db_conns:
        p_name = c["provider"]
        if p_name not in db_conns_map:
            db_conns_map[p_name] = c

    # Override keys with DB connections
    if "deepseek" in db_conns_map:
        deepseek_key = db_conns_map["deepseek"]["api_key"]
    if "openai" in db_conns_map:
        openai_key = db_conns_map["openai"]["api_key"]
    if "groq" in db_conns_map:
        groq_key = db_conns_map["groq"]["api_key"]
    if "huggingface" in db_conns_map:
        hf_token = db_conns_map["huggingface"]["api_key"]
    if "gemini" in db_conns_map:
        gemini_key = db_conns_map["gemini"]["api_key"]

    # Parse preferred provider/model
    prov_req, model_req = parse_provider_and_model(preferred_provider)
    
    full_cfg_fake = {
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
            # Helper for executing LLM translation with local 9Router gateway fallback
            def _try_llm_translate(alias_prefix: str, direct_url: str, direct_key: str, default_model: str, prov_label: str) -> Tuple[List[str] | None, str]:
                model_name = model_req if model_req else default_model
                # 1. Try local 9Router gateway on port 20128 if available
                nine_model_id = model_name if "/" in model_name else f"{alias_prefix}/{model_name}"
                disp_name = model_name.split("/")[-1] if "/" in model_name else model_name
                if nine_key:
                    try:
                        res = _llm_translate(
                            source_texts,
                            f"{nine_endpoint}/chat/completions",
                            nine_key,
                            nine_model_id,
                            timeout=7,
                            context=context,
                            target_lang=target_lang,
                        )
                        if any(res):
                            return res, disp_name
                    except Exception:
                        pass
                        
                # 2. Try direct provider API call
                if direct_url and direct_key:
                    try:
                        res = _llm_translate(
                            source_texts,
                            direct_url,
                            direct_key,
                            model_name,
                            timeout=7,
                            context=context,
                            target_lang=target_lang,
                        )
                        if any(res):
                            return res, disp_name
                    except Exception:
                        pass
                return None, ""

            if provider == "antigravity" and "antigravity" in db_conns_map:
                c = db_conns_map["antigravity"]
                key = c["api_key"]
                base_url = (c.get("base_url") or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
                endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
                res, m_label = _try_llm_translate("ag", endpoint, key, "gemini-3.6-flash", "antigravity")
                if res and any(res):
                    return _rebuild(res), m_label or "antigravity"
                _errors.append("antigravity: failed")

            elif provider in ["opencode", "opencodefree"]:
                c = db_conns_map.get("opencode") or db_conns_map.get("opencodefree") or {}
                key = c.get("api_key", "")
                base_url = (c.get("base_url") or "https://opencode.ai/zen/v1").rstrip("/")
                endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
                res, m_label = _try_llm_translate("oc", endpoint, key, "hy3-free", "opencode")
                if res and any(res):
                    return _rebuild(res), m_label or "opencode"
                _errors.append("opencode: failed")

            elif provider == "codex" and "codex" in db_conns_map:
                c = db_conns_map["codex"]
                key = c["api_key"]
                base_url = (c.get("base_url") or "https://api.openai.com/v1").rstrip("/")
                endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
                res, m_label = _try_llm_translate("cx", endpoint, key, "gpt-5.6-sol", "codex")
                if res and any(res):
                    return _rebuild(res), m_label or "codex"
                _errors.append("codex: failed")

            elif provider == "nvidia" and "nvidia" in db_conns_map:
                c = db_conns_map["nvidia"]
                key = c["api_key"]
                base_url = (c.get("base_url") or "https://integrate.api.nvidia.com/v1").rstrip("/")
                endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
                res, m_label = _try_llm_translate("nvidia", endpoint, key, "meta/llama3-70b-instruct", "nvidia")
                if res and any(res):
                    return _rebuild(res), m_label or "nvidia"
                _errors.append("nvidia: failed")

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
                    return _rebuild(result), ds_model
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
                    return _rebuild(result), oa_model
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
                    return _rebuild(result), g_model
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
                    return _rebuild(result), gem_model
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
                        return _rebuild(result), hf_model

            elif provider == "google":
                translated = _translate_google_parallel(source_texts, target_lang=target_lang)
                if any(translated):
                    return _rebuild(translated), "Google Translate"
        except Exception as e:
            _errors.append(f"{provider}: {e}")
            err_str = str(e).lower()
            if "402" in err_str or "429" in err_str or "quota" in err_str or "exceeded" in err_str or "balance" in err_str or "401" in err_str or "403" in err_str or "unauthorized" in err_str or "key" in err_str:
                mark_provider_failed(provider, str(e))
            continue

    # Emergency Fallback: Google Translate if all selected AI providers failed/timed out
    try:
        translated = _translate_google_parallel(source_texts, target_lang=target_lang)
        if any(translated):
            return _rebuild(translated), "Google Translate"
    except Exception:
        pass

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

    Fallback chain: DeepSeek → OpenAI → HuggingFace → Google → DTRouter
    """

    def __init__(self, trans_cfg: dict, dtrouter_cfg: dict | None = None):
        self._cfg = trans_cfg or {}
        self._nine = dtrouter_cfg or {}

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
            dtrouter_cfg=self._nine,
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

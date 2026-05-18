from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "path": "./Downloaded/",
    "music": False,
    "cover": False,
    "avatar": False,
    "json": False,
    "start_time": "",
    "end_time": "",
    "folderstyle": False,
    "mode": ["post"],
    "number": {
        "post": 0,
        "like": 0,
        "allmix": 0,
        "mix": 0,
        "music": 0,
        "collect": 0,
        "collectmix": 0,
    },
    "increase": {
        "post": False,
        "like": False,
        "allmix": False,
        "mix": False,
        "music": False,
    },
    "thread": 5,
    "rate_limit": 5,
    "retry_times": 3,
    "proxy": "",
    "database": True,
    "database_path": "dy_downloader.db",
    "progress": {
        "quiet_logs": True,
    },
    "transcript": {
        "enabled": False,
        "model": "gpt-4o-mini-transcribe",
        "groq_api_key": "",
        "groq_model": "whisper-large-v3-turbo",
        "groq_max_mb": 25,
        "output_dir": "",
        "response_formats": ["txt", "json"],
        "api_url": "https://api.openai.com/v1/audio/transcriptions",
        "api_key_env": "OPENAI_API_KEY",
        "api_key": "",
    },
    "auto_cookie": False,
    "browser_fallback": {
        "enabled": True,
        "headless": False,
        "max_scrolls": 240,
        "idle_rounds": 8,
        "wait_timeout_seconds": 600,
    },
    "translation": {
        "deepseek_key": "",
        "openai_key": "",
        "groq_key": "",
        "groq_model": "llama-3.1-8b-instant",
        "hf_token": "",
        "preferred_provider": "deepseek",
        "naming_enabled": True,
    },
    "upload": {
        "platform": "youtube",
        "auto_upload": False,
        "youtube": {
            "title_template": "{title}",
            "description_template": "{title}",
            "privacy_status": "private",
        },
        "tiktok": {
            "title_template": "{title}",
            "caption_template": "{title}",
            "privacy_status": "private",
            "scopes": ["user.info.basic", "video.publish"],
            "client_key": "",
            "client_secret": "",
            "client_key_env": "TIKTOK_CLIENT_KEY",
            "client_secret_env": "TIKTOK_CLIENT_SECRET",
            "redirect_uri": "",
        },
    },
    "ngrok": {
        "enabled": False,
        "authtoken": "",
        "domain": "",
        "bind_tls": True,
        "public_url": "",
    },
    "huggingface": {
        "hf_token": "",                       # fallback sang translation.hf_token nếu rỗng
        "tts_model": "facebook/mms-tts-vie",  # model mặc định (tiếng Việt)
        "tts_speaker_embeddings": "",         # optional, đường dẫn local
        "device": "cpu",                      # hoặc "cuda"
    },
    "video_process": {
        "enabled": True,
        "model": "small",
        "language": "zh",
        "process_mode": "ai",
        "burn_subs": True,
        "blur_original": True,
        "translate": True,
        "burn_vi_subs": True,
        "voice_convert": True,
        "keep_bg_music": True,
        "keep_bg": True,
        "blur_zone": "bottom",
        "tts_voice": "vi-VN-HoaiMyNeural",
        "tts_engine": "edge-tts",
        "tts_speed": 1.0,
        "auto_speed": True,
        "pitch_semitones": 0.0,
        "fpt_api_key": "",  # Set via env FPT_TTS_API_KEY or video_process.fpt_api_key in config.yml
        "bg_volume": 0.15,
        "font_size": 18,
        "font_name": "Arial",
        "font_color": "white",
        "outline_color": "black",
        "outline_width": 2,
        "blur_height": 15,
        "subtitle_format": "ass",
        "max_words_per_segment": 5,  # Số từ tối đa trong 1 câu (cho tiếng Việt/Anh, 0 = không giới hạn)
        "max_chars_per_segment": 15,  # Số ký tự tối đa trong 1 câu (cho tiếng Trung, ưu tiên hơn max_words, 0 = không giới hạn)
    },
    "capcut": {
        "enabled": False,
        "auto_import": False,
        "capcut_path": "",
        "auto_open": False,
    },
    "facebook": {
        "app_id": "",
        "app_secret": "",
    },
    # ── Web app authentication (single-user password gate) ──
    "auth": {
        "enabled": False,
        "cors_origins": [],  # empty = sensible defaults; "*" = wide-open (NOT recommended)
    },
    # ── Proxy pool ──
    "proxies": {
        "enabled": False,
        "active_id": "",
        "rotation": {
            "mode": "round_robin",   # round_robin | random | sticky
            "per_request": False,
        },
        "health_check": {
            "enabled": True,
            "test_url": "https://ifconfig.me/ip",
            "timeout_sec": 8,
        },
        "list": [],   # filled via UI; persisted to .state/proxies.json
    },
    # ── 4G router pool (HiLink/Huawei IP rotation) ──
    # NOTE: This is the 4G modem pool — NOT to be confused with 9Router
    # (the OpenAI-compatible AI gateway), which lives under "nine_router".
    "routers": {
        "enabled": False,
        "list": [],   # {id,label,type,endpoint,method,headers,body,success_check}
        "cooldown_sec": 30,
        "default_id": "",
    },
    # ── 9Router (local AI gateway, OpenAI-compatible) ──
    # Used by the Chat Bot tab to talk to 60+ AI providers via one endpoint.
    # See: https://9router.com — repo decolua/9router. The integration uses the
    # same wire format as 9Router's own dashboard:
    #   • Base URL `http://localhost:20128/v1` (Next.js rewrites to /api/v1).
    #   • Auth `Authorization: Bearer sk-{machineId}-{keyId}-{crc8}`.
    #   • Keys are managed via /api/keys, protected by the dashboard cookie or
    #     the local `x-9r-cli-token` header (sha256(rawMachineId + "9r-cli-auth")[:16]).
    "nine_router": {
        "endpoint": "http://localhost:20128/v1",
        "api_key": "",
        "default_model": "duytris",
        "system_prompt": "",
        "temperature": 0.7,
        "max_tokens": 4096,  # generous default — reasoning models eat 1k+ before producing visible content
        # ── Smart routing by prompt complexity ────────────────────────
        # When `routing.mode == "auto"` the chat handler classifies each
        # prompt with a cheap heuristic and picks the matching tier so we
        # don't waste opus-class quota on "hi". Override per-message by
        # explicitly specifying a model in the request.
        "routing": {
            "mode": "auto",            # "auto" | "manual"
            "tiers": {
                "fast":     "gemini/gemini-2.0-flash-lite",
                "balanced": "kr/claude-sonnet-4.5",
                "power":    "kr/claude-opus-4.5-thinking",
            },
            # Heuristic thresholds — tweak in config.yml without code change.
            "thresholds": {
                "fast_max_chars": 80,    # short prompt → fast
                "power_min_chars": 1500, # very long prompt → power
                "history_balanced_after": 4,  # after N exchanges, escalate
            },
        },
    },
    # ── Movie review (TMDb + LLM) ──
    "movie": {
        "tmdb_api_key": "",
        "tmdb_read_token": "",   # v4 Bearer token (preferred over api_key)
        "default_language": "vi",
        "default_provider": "deepseek",
        "cache_ttl_hours": 24,
        "default_template": "cinematic",
    },
    # ── Novel / Comic → Video script ──
    "storywriter": {
        "default_provider": "deepseek",
        "default_target_lang": "vi",
        "chunk": {
            "target_chars_per_segment": 350,
            "max_chars_per_segment": 600,
            "overlap_sentences": 0,
        },
        "comic": {
            "ocr_enabled": False,
            "ocr_provider": "tesseract",   # "tesseract" | "9router"
            "vision_model": "",            # blank → use nine_router.default_model
        },
        "output_dir": "./Downloaded/scripts",
    },
}

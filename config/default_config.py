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
        "tts_voice": "Minh Quân Pro",
        "tts_engine": "vieneu",
        "tts_speed": 1.0,
        "tts_concurrency": 4,
        "tts_retries": 2,
        "auto_speed": True,
        "pitch_semitones": 0.0,
        "vieneu_ref_audio": "",  # WAV/MP3 3-8 giây; trống = dùng preset
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
    "routers": {
        "enabled": False,
        "list": [],   # {id,label,type,endpoint,method,headers,body,success_check}
        "cooldown_sec": 30,
        "default_id": "",
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
            "ocr_provider": "tesseract",
            "vision_model": "",
        },
        "output_dir": "./Downloaded/scripts",
    },
    # ── Idea → Video pipeline (ViMax architecture) ──
    "idea2video": {
        "output_dir": "./Downloaded/idea2video",
        "default_style": "cinematic, high quality, dramatic lighting",
        "shot_duration": 5,       # giây mỗi shot (Gemini Veo 2)
        "max_shots_per_scene": 8,
    },
    # ── n8n orchestration (workflow automation gateway) ──
    # toolvideo plays the "worker" role; n8n plays the "conductor":
    #   n8n (schedule/webhook/đăng bài/thông báo) ──HTTP──▶ toolvideo REST API
    # The tab lets you connect to a self-hosted n8n instance, test the
    # connection, and trigger n8n webhook workflows manually. The API key is
    # an n8n REST API key (Settings → n8n API) used only for listing
    # workflows / status; webhook triggers don't require it.
    "n8n": {
        "enabled": False,
        "base_url": "http://localhost:5678",  # n8n instance URL
        "api_key": "",                          # n8n REST API key (env: N8N_API_KEY)
        "webhook_url": "",                      # default Production webhook URL to trigger
        "default_payload": "{\n  \"source\": \"toolvideo\"\n}",
        "timeout_sec": 30,
    },
}

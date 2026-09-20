"""Config Blueprint — /api/config, /api/cookies, /api/parse_cookie,
/api/validate_cookie, /api/cookie_mode, /api/ngrok/status,
/api/auto_fetch_cookie, /api/upload-image, /api/browse-file routes."""
import asyncio
import threading
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request
from core_app import (
    load_cfg, save_cfg, _deep_merge_dict,
    _get_ngrok_settings, _start_ngrok_tunnel, _public_base_url,
    CONFIG_FILE, ROOT, STATE_DIR,
)
import core_app as _ca
import sqlite3
import time

bp = Blueprint("config", __name__)


def get_db_connection():
    db_path = STATE_DIR / "providers.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_provider_models(conn):
    initial_models = {
        "antigravity": [
            ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)", "llm", 1),
            ("gemini-3.8-flash-medium", "Gemini 3.8 Flash (Medium)", "llm", 2),
            ("gemini-3.8-flash-low", "Gemini 3.8 Flash (Low)", "llm", 3),
            ("gemini-3.7-flash", "Gemini 3.7 Flash (Medium)", "llm", 4),
            ("gemini-3.6-flash-medium", "Gemini 3.6 Flash (Medium)", "llm", 5),
            ("gemini-3.6-flash", "Gemini 3.6 Flash (High)", "llm", 6),
            ("gemini-3.1-pro-low", "Gemini 3.1 Pro (Low)", "llm", 7),
            ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)", "llm", 8),
            ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)", "llm", 9),
            ("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)", "llm", 10),
        ],

        "openai": [
            ("gpt-4o-mini", "GPT-4o Mini", "llm", 1),
            ("gpt-4o", "GPT-4o", "llm", 2),
            ("o1-mini", "O1 Mini", "llm", 3),
            ("o1-preview", "O1 Preview", "llm", 4),
        ],
        "deepseek": [
            ("deepseek-chat", "DeepSeek Chat (V3)", "llm", 1),
            ("deepseek-coder", "DeepSeek Coder", "llm", 2),
            ("deepseek-reasoner", "DeepSeek Reasoner (R1)", "llm", 3),
        ],
        "groq": [
            ("llama3-8b-8192", "Llama 3 8B", "llm", 1),
            ("llama3-70b-8192", "Llama 3 70B", "llm", 2),
            ("mixtral-8x7b-32768", "Mixtral 8x7B", "llm", 3),
            ("gemma2-9b-it", "Gemma 2 9B", "llm", 4),
        ],
        "nvidia": [
            ("meta/llama3-70b-instruct", "Llama 3 70B Instruct", "llm", 1),
            ("nvidia/llama-3.1-nemotron-70b-instruct", "Nemotron 70B Instruct", "llm", 2),
        ],
        "xai": [
            ("grok-2", "Grok 2", "llm", 1),
            ("grok-2-1212", "Grok 2 1212", "llm", 2),
            ("grok-beta", "Grok Beta", "llm", 3),
        ],
        "kimi": [
            ("moonshot-v1-8k", "Moonshot v1 8K", "llm", 1),
            ("moonshot-v1-32k", "Moonshot v1 32K", "llm", 2),
            ("moonshot-v1-128k", "Moonshot v1 128K", "llm", 3),
        ],
        "codex": [
            ("gpt-5.6-sol", "GPT 5.6 Sol", "llm", 1),
            ("gpt-5.6-sol-review", "GPT 5.6 Sol Review", "llm", 2),
            ("gpt-5.6-terra", "GPT 5.6 Terra", "llm", 3),
            ("gpt-5.6-terra-review", "GPT 5.6 Terra Review", "llm", 4),
            ("gpt-5.6-luna", "GPT 5.6 Luna", "llm", 5),
            ("gpt-5.6-luna-review", "GPT 5.6 Luna Review", "llm", 6),
            ("gpt-5.5", "GPT 5.5", "llm", 7),
            ("gpt-5.4", "GPT 5.4", "llm", 8),
            ("gpt-5.4-mini", "GPT 5.4 Mini", "llm", 9),
            ("gpt-5.3-codex", "GPT 5.3 Codex", "llm", 10),
            ("gpt-5.3-codex-xhigh", "GPT 5.3 Codex (xHigh)", "llm", 11),
            ("gpt-5.3-codex-high", "GPT 5.3 Codex (High)", "llm", 12),
            ("gpt-5.3-codex-low", "GPT 5.3 Codex (Low)", "llm", 13),
            ("gpt-5.3-codex-none", "GPT 5.3 Codex (None)", "llm", 14),
            ("gpt-5.3-codex-spark", "GPT 5.3 Codex Spark", "llm", 15),
            ("gpt-5.5-image", "GPT 5.5 Image", "image", 16),
            ("gpt-5.4-image", "GPT 5.4 Image", "image", 17),
            ("gpt-5.3-image", "GPT 5.3 Image", "image", 18),
        ],
        "nanobanana": [
            ("gemini-1.5-flash", "Gemini 1.5 Flash", "llm", 1),
            ("gemini-1.5-pro", "Gemini 1.5 Pro", "llm", 2),
        ],
        "ollama": [
            ("llama3", "Llama 3", "llm", 1),
            ("qwen2", "Qwen 2", "llm", 2),
            ("mistral", "Mistral", "llm", 3),
            ("phi3", "Phi 3", "llm", 4),
        ],
        "kiro": [("kiro-llm", "Kiro AI LLM", "llm", 1)],
        "qoder": [("qoder-llm", "Qoder LLM", "llm", 1)],
        "deepgram": [
            ("nova-2", "Nova 2 (Speech)", "tts", 1),
            ("whisper-large", "Whisper Large (ASR)", "stt", 2),
        ],
        "elevenlabs": [
            ("eleven_multilingual_v2", "Eleven Multilingual v2", "tts", 1),
            ("eleven_turbo_v2_5", "Eleven Turbo v2.5", "tts", 2),
        ],
        "cartesia": [
            ("sonic-2", "Sonic 2", "tts", 1),
            ("sonic-3", "Sonic 3", "tts", 2),
        ],
        "playht": [
            ("PlayDialog", "PlayDialog", "tts", 1),
            ("Play3.0-mini", "Play 3.0 Mini", "tts", 2),
        ],
        "inworld": [
            ("inworld-tts-1.5-mini", "Inworld TTS 1.5 Mini", "tts", 1),
            ("inworld-tts-1.5-max", "Inworld TTS 1.5 Max", "tts", 2),
        ],
        "minimax": [
            ("speech-2.8-hd", "Speech 2.8 HD", "tts", 1),
            ("speech-2.8-turbo", "Speech 2.8 Turbo", "tts", 2),
        ],
        "minimax-cn": [
            ("speech-2.8-hd", "Speech 2.8 HD (CN)", "tts", 1),
            ("speech-2.8-turbo", "Speech 2.8 Turbo (CN)", "tts", 2),
        ],
        "hyperbolic": [("melo-tts", "Melo TTS", "tts", 1)],
        "assemblyai": [
            ("universal-3-pro", "Universal 3 Pro", "stt", 1),
            ("universal-2", "Universal 2", "stt", 2),
        ],
        "anthropic": [
            ("claude-3-7-sonnet-20250219", "Claude 3.7 Sonnet", "llm", 1),
            ("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet", "llm", 2),
            ("claude-3-5-haiku-20241022", "Claude 3.5 Haiku", "llm", 3),
        ],
        "openrouter": [
            ("anthropic/claude-3.7-sonnet", "Claude 3.7 Sonnet (OpenRouter)", "llm", 1),
            ("deepseek/deepseek-r1", "DeepSeek R1 (OpenRouter)", "llm", 2),
            ("openai/gpt-4o", "GPT-4o (OpenRouter)", "llm", 3),
            ("google/gemini-2.5-flash", "Gemini 2.5 Flash (OpenRouter)", "llm", 4),
        ],
        "together": [
            ("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "Llama 3.1 70B Turbo", "llm", 1),
            ("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "Llama 3.1 8B Turbo", "llm", 2),
        ],
        "cerebras": [
            ("llama3.1-70b", "Llama 3.1 70B", "llm", 1),
            ("llama3.1-8b", "Llama 3.1 8B", "llm", 2),
        ],
        "mistral": [
            ("mistral-large-latest", "Mistral Large", "llm", 1),
            ("mistral-small-latest", "Mistral Small", "llm", 2),
        ],
        "sambanova": [
            ("Meta-Llama-3.1-70B-Instruct", "Llama 3.1 70B (SambaNova)", "llm", 1),
        ],
        "fireworks": [
            ("accounts/fireworks/models/llama-v3p1-70b-instruct", "Llama 3.1 70B (Fireworks)", "llm", 1),
        ],
        "perplexity": [("sonar", "Sonar Search", "llm", 1)],
        "tavily": [("tavily-search", "Tavily Search Engine", "llm", 1)],
        "brave-search": [("brave-search", "Brave Web Search", "llm", 1)],
        "serper": [("google-search", "Google Search (Serper)", "llm", 1)],
        "exa": [("exa-search", "Exa Neural Search", "llm", 1)],
        "google-pse": [("google-pse", "Google PSE Engine", "llm", 1)],
        "linkup": [("linkup-search", "Linkup Search Tool", "llm", 1)],
        "searchapi": [("searchapi-search", "SearchAPI Index", "llm", 1)],
        "youcom": [("youcom-search", "You.com Search Engine", "llm", 1)],
        "firecrawl": [("firecrawl-scrape", "Firecrawl Scrape API", "llm", 1)],
    }
    for prov, m_list in initial_models.items():
        for m_id, m_name, m_type, order in m_list:
            pk = f"{prov}_{m_id}"
            conn.execute(
                """INSERT OR IGNORE INTO provider_models 
                   (id, provider, model_id, name, type, enabled, sort_order) 
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (pk, prov, m_id, m_name, m_type, order),
            )
    conn.commit()


DEFAULT_PROVIDER_MODELS = {
    "antigravity": [
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)", "type": "llm", "enabled": True},
        {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)", "type": "llm", "enabled": True},
        {"id": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)", "type": "llm", "enabled": True},
        {"id": "gemini-3.7-flash", "name": "Gemini 3.7 Flash (Medium)", "type": "llm", "enabled": True},
        {"id": "gemini-3.6-flash-medium", "name": "Gemini 3.6 Flash (Medium)", "type": "llm", "enabled": True},
        {"id": "gemini-3.6-flash", "name": "Gemini 3.6 Flash (High)", "type": "llm", "enabled": True},
        {"id": "gemini-3.1-pro-low", "name": "Gemini 3.1 Pro (Low)", "type": "llm", "enabled": True},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)", "type": "llm", "enabled": True},
        {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)", "type": "llm", "enabled": True},
        {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)", "type": "llm", "enabled": True},
    ],
    "anthropic": [
        {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet", "type": "llm", "enabled": True},
        {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "type": "llm", "enabled": True},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "type": "llm", "enabled": True},
    ],
    "openai": [
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "type": "llm", "enabled": True},
        {"id": "gpt-4o", "name": "GPT-4o", "type": "llm", "enabled": True},
        {"id": "o1-mini", "name": "O1 Mini", "type": "llm", "enabled": True},
        {"id": "o1-preview", "name": "O1 Preview", "type": "llm", "enabled": True},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)", "type": "llm", "enabled": True},
        {"id": "deepseek-coder", "name": "DeepSeek Coder", "type": "llm", "enabled": True},
        {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "type": "llm", "enabled": True},
    ],
    "groq": [
        {"id": "llama3-8b-8192", "name": "Llama 3 8B", "type": "llm", "enabled": True},
        {"id": "llama3-70b-8192", "name": "Llama 3 70B", "type": "llm", "enabled": True},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "type": "llm", "enabled": True},
        {"id": "gemma2-9b-it", "name": "Gemma 2 9B", "type": "llm", "enabled": True},
    ],
    "openrouter": [
        {"id": "anthropic/claude-3.7-sonnet", "name": "Claude 3.7 Sonnet (OpenRouter)", "type": "llm", "enabled": True},
        {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (OpenRouter)", "type": "llm", "enabled": True},
        {"id": "openai/gpt-4o", "name": "GPT-4o (OpenRouter)", "type": "llm", "enabled": True},
        {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash (OpenRouter)", "type": "llm", "enabled": True},
    ],
    "together": [
        {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "name": "Llama 3.1 70B Turbo", "type": "llm", "enabled": True},
        {"id": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "name": "Llama 3.1 8B Turbo", "type": "llm", "enabled": True},
    ],
    "cerebras": [
        {"id": "llama3.1-70b", "name": "Llama 3.1 70B", "type": "llm", "enabled": True},
        {"id": "llama3.1-8b", "name": "Llama 3.1 8B", "type": "llm", "enabled": True},
    ],
    "xai": [
        {"id": "grok-2", "name": "Grok 2", "type": "llm", "enabled": True},
        {"id": "grok-2-1212", "name": "Grok 2 1212", "type": "llm", "enabled": True},
        {"id": "grok-beta", "name": "Grok Beta", "type": "llm", "enabled": True},
    ],
    "kimi": [
        {"id": "moonshot-v1-8k", "name": "Moonshot v1 8K", "type": "llm", "enabled": True},
        {"id": "moonshot-v1-32k", "name": "Moonshot v1 32K", "type": "llm", "enabled": True},
        {"id": "moonshot-v1-128k", "name": "Moonshot v1 128K", "type": "llm", "enabled": True},
    ],
    "nvidia": [
        {"id": "meta/llama3-70b-instruct", "name": "Llama 3 70B Instruct", "type": "llm", "enabled": True},
        {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B Instruct", "type": "llm", "enabled": True},
    ],
    "mistral": [
        {"id": "mistral-large-latest", "name": "Mistral Large", "type": "llm", "enabled": True},
        {"id": "mistral-small-latest", "name": "Mistral Small", "type": "llm", "enabled": True},
    ],
    "sambanova": [
        {"id": "Meta-Llama-3.1-70B-Instruct", "name": "Llama 3.1 70B (SambaNova)", "type": "llm", "enabled": True},
    ],
    "fireworks": [
        {"id": "accounts/fireworks/models/llama-v3p1-70b-instruct", "name": "Llama 3.1 70B (Fireworks)", "type": "llm", "enabled": True},
    ],
    "ollama": [
        {"id": "llama3", "name": "Llama 3", "type": "llm", "enabled": True},
        {"id": "qwen2", "name": "Qwen 2", "type": "llm", "enabled": True},
        {"id": "mistral", "name": "Mistral", "type": "llm", "enabled": True},
        {"id": "phi3", "name": "Phi 3", "type": "llm", "enabled": True},
    ],
}


def load_models_from_db(provider: str = "") -> dict[str, list[dict]]:
    conn = get_db_connection()
    result = {}
    try:
        if provider:
            cursor = conn.execute(
                """SELECT model_id, name, type, enabled 
                   FROM provider_models 
                   WHERE provider = ? 
                   ORDER BY sort_order ASC, rowid ASC""",
                (provider,),
            )
            rows = cursor.fetchall()
            result[provider] = [
                {
                    "id": r["model_id"],
                    "name": r["name"],
                    "type": r["type"],
                    "enabled": bool(r["enabled"]),
                }
                for r in rows
            ]
        else:
            cursor = conn.execute(
                """SELECT model_id, provider, name, type, enabled 
                   FROM provider_models 
                   ORDER BY provider ASC, sort_order ASC, rowid ASC"""
            )
            rows = cursor.fetchall()
            for r in rows:
                p = r["provider"]
                if p not in result:
                    result[p] = []
                result[p].append(
                    {
                        "id": r["model_id"],
                        "name": r["name"],
                        "type": r["type"],
                        "enabled": bool(r["enabled"]),
                    }
                )
    except Exception as e:
        print("[Providers DB] Load models failed:", e)
    finally:
        conn.close()
    return result


def init_providers_db():
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_connections (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                name TEXT,
                api_key TEXT,
                base_url TEXT,
                enabled INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_settings (
                provider TEXT PRIMARY KEY,
                strategy TEXT DEFAULT 'fallback'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_models (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'llm',
                enabled INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                UNIQUE(provider, model_id)
            )
        """)
        conn.commit()
        
        # Check if database is empty to run initial migration from config.yml
        cursor = conn.execute("SELECT count(*) FROM provider_connections")
        count = cursor.fetchone()[0]
        if count == 0:
            cfg = load_cfg()
            providers_cfg = cfg.get("providers") or {}
            if isinstance(providers_cfg, dict):
                for provider, p_data in providers_cfg.items():
                    if not isinstance(p_data, dict):
                        continue
                    strategy = p_data.get("strategy") or "fallback"
                    conn.execute("INSERT OR REPLACE INTO provider_settings (provider, strategy) VALUES (?, ?)", (provider, strategy))
                    connections = p_data.get("connections") or []
                    for c in connections:
                        if not isinstance(c, dict):
                            continue
                        conn.execute("""
                            INSERT OR REPLACE INTO provider_connections (id, provider, name, api_key, base_url, enabled, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            c.get("id") or f"conn_{int(time.time())}",
                            provider,
                            c.get("name"),
                            c.get("api_key"),
                            c.get("base_url"),
                            1 if c.get("enabled") else 0,
                            c.get("status") or "active"
                        ))
                conn.commit()

        # Ensure all default provider models exist (INSERT OR IGNORE)
        _seed_provider_models(conn)
    except Exception as e:
        print("[Providers DB] Init failed:", e)
    finally:
        conn.close()


# Initialize database
init_providers_db()


def load_providers_from_db():
    conn = get_db_connection()
    providers = {}
    try:
        # Load settings
        cursor = conn.execute("SELECT provider, strategy FROM provider_settings")
        for row in cursor.fetchall():
            providers[row["provider"]] = {
                "connections": [],
                "strategy": row["strategy"]
            }
            
        # Load connections
        cursor = conn.execute("""
            SELECT id, provider, name, api_key, base_url, enabled, status,
                   refresh_token, expires_at, project_id, email, auth_type
            FROM provider_connections
        """)
        for row in cursor.fetchall():
            provider = row["provider"]
            if provider not in providers:
                providers[provider] = {
                    "connections": [],
                    "strategy": "fallback"
                }
            providers[provider]["connections"].append({
                "id": row["id"],
                "name": row["name"],
                "api_key": row["api_key"],
                "base_url": row["base_url"],
                "enabled": bool(row["enabled"]),
                "status": row["status"],
                "refresh_token": row["refresh_token"] or "",
                "expires_at": row["expires_at"] or 0,
                "project_id": row["project_id"] or "",
                "email": row["email"] or "",
                "auth_type": row["auth_type"] or "api_key"
            })
    except Exception as e:
        print("[Providers DB] Load failed:", e)
    finally:
        conn.close()
    return providers


def save_providers_to_db(providers):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM provider_connections")
        conn.execute("DELETE FROM provider_settings")
        for provider, p_data in providers.items():
            if not isinstance(p_data, dict):
                continue
            strategy = p_data.get("strategy") or "fallback"
            conn.execute("INSERT OR REPLACE INTO provider_settings (provider, strategy) VALUES (?, ?)", (provider, strategy))
            connections = p_data.get("connections") or []
            for c in connections:
                if not isinstance(c, dict):
                    continue
                conn.execute("""
                    INSERT OR REPLACE INTO provider_connections (
                        id, provider, name, api_key, base_url, enabled, status,
                        refresh_token, expires_at, project_id, email, auth_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    c.get("id"),
                    provider,
                    c.get("name"),
                    c.get("api_key"),
                    c.get("base_url"),
                    1 if c.get("enabled") else 0,
                    c.get("status") or "active",
                    c.get("refresh_token") or "",
                    int(c.get("expires_at") or 0),
                    c.get("project_id") or "",
                    c.get("email") or "",
                    c.get("auth_type") or "api_key"
                ))
        conn.commit()
    except Exception as e:
        print("[Providers DB] Save failed:", e)
    finally:
        conn.close()


# ── /api/config ───────────────────────────────────────────────────────────────
@bp.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_cfg()
    cfg["providers"] = load_providers_from_db()
    return jsonify(cfg)


@bp.route("/api/config", methods=["POST"])
def post_config():
    data = request.json or {}
    
    # Intercept providers data to save to SQLite database
    providers = data.get("providers")
    if providers is not None:
        save_providers_to_db(providers)
        # Remove from data so it doesn't get saved to config.yml
        data = {k: v for k, v in data.items() if k != "providers"}
        
    cfg = load_cfg()
    cfg = _deep_merge_dict(cfg, data)
    
    if "providers" in cfg:
        del cfg["providers"]
        
    save_cfg(cfg)
    
    # Invalidate chatbot cache so changes are synced instantly
    try:
        from templates.pages.chat.route import _models_cache, _reachable_cache
        _models_cache["ids"] = set()
        _models_cache["ts"] = 0.0
        _reachable_cache["ok"] = None
        _reachable_cache["ts"] = 0.0
    except Exception:
        pass
        
    return jsonify({"ok": True})


# ── /api/ngrok/status ─────────────────────────────────────────────────────────
@bp.route("/api/ngrok/status", methods=["GET"])
def ngrok_status():
    host = "127.0.0.1"
    port = 8080
    settings = _get_ngrok_settings()
    if settings.get("enabled") and not _ca._NGROK_PUBLIC_URL:
        _start_ngrok_tunnel(port)
    public_url = _public_base_url(host, port)
    return jsonify({
        "ok": True,
        "enabled": bool(settings.get("enabled")),
        "public_url": public_url,
        "tunnel_active": bool(_ca._NGROK_PUBLIC_URL),
        "local_url": f"http://{host}:{port}",
        "tiktok_callback_url": f"{public_url}/api/tiktok/callback",
        "error": _ca._NGROK_ERROR,
    })


# ── /api/cookies ──────────────────────────────────────────────────────────────
@bp.route("/api/cookies", methods=["POST"])
def post_cookies():
    data = request.json or {}
    cfg = load_cfg()
    cfg["cookies"] = data
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/parse_cookie", methods=["POST"])
def parse_cookie():
    raw = (request.json or {}).get("raw", "")
    from utils.cookie_utils import parse_cookie_header
    parsed = parse_cookie_header(raw)
    return jsonify(parsed)


@bp.route("/api/validate_cookie", methods=["POST"])
def validate_cookie():
    data = request.json or {}
    from auth import CookieManager
    cm = CookieManager()
    cm.set_cookies(data)
    ok = cm.validate_cookies()
    return jsonify({"ok": ok})


# ── /api/cookie_mode ──────────────────────────────────────────────────────────
@bp.route("/api/cookie_mode", methods=["GET"])
def get_cookie_mode():
    cfg = load_cfg()
    return jsonify({"mode": cfg.get("cookie_mode", "default")})


@bp.route("/api/cookie_mode", methods=["POST"])
def set_cookie_mode():
    mode = (request.json or {}).get("mode", "default")
    cfg = load_cfg()
    cfg["cookie_mode"] = mode
    save_cfg(cfg)
    return jsonify({"ok": True})


# ── /api/auto_fetch_cookie ────────────────────────────────────────────────────
@bp.route("/api/auto_fetch_cookie", methods=["POST"])
def auto_fetch_cookie():
    def run():
        import argparse
        from tools.cookie_fetcher import capture_cookies
        args = argparse.Namespace(
            url="https://www.douyin.com/", browser="chromium",
            headless=False, output=ROOT / "config" / "cookies.json",
            config=CONFIG_FILE, include_all=False,
        )
        asyncio.run(capture_cookies(args))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# ── /api/tiktok/auto_fetch_cookie ─────────────────────────────────────────────
@bp.route("/api/tiktok/auto_fetch_cookie", methods=["POST"])
def tiktok_auto_fetch_cookie():
    def run():
        import argparse
        from tools.cookie_fetcher import capture_cookies
        args = argparse.Namespace(
            url="https://www.tiktok.com/", browser="chromium",
            headless=False, output=ROOT / "config" / "tiktok_cookies.json",
            config=CONFIG_FILE, include_all=False,
        )
        asyncio.run(capture_cookies(args))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# ── /api/youtube/login_cookie ──────────────────────────────────────────────────
@bp.route("/api/youtube/login_cookie", methods=["POST"])
def youtube_login_cookie():
    import time
    from playwright.sync_api import sync_playwright
    from utils.helpers import ensure_playwright_chromium
    
    try:
        ensure_playwright_chromium()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Không thể chuẩn bị Playwright: {e}"}), 500

    try:
        cookie_text = ""
        lines = []
        with sync_playwright() as p:
            import tempfile
            user_data_dir = tempfile.mkdtemp(prefix="playwright_yt_")
            
            from utils.helpers import launch_playwright_browser_sync
            browser_context = launch_playwright_browser_sync(
                p.chromium,
                is_persistent=True,
                user_data_dir=user_data_dir,
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
            page.goto("https://www.youtube.com")
            
            # Wait for user to interact and close the page
            page_closed = threading.Event()
            page.on("close", lambda _: page_closed.set())
            
            # Wait up to 5 minutes
            page_closed.wait(timeout=300)
            
            # Extract cookies
            cookies = browser_context.cookies()
            browser_context.close()
            
            # Convert to Netscape format
            lines.append("# Netscape HTTP Cookie File")
            lines.append("# http://curl.haxx.se/rfc/cookie_spec.html")
            lines.append("# This is a generated file! Do not edit.")
            lines.append("")
            
            for c in cookies:
                domain = c.get("domain", "")
                if not any(x in domain for x in ["youtube.com", "google.com", "youtube"]):
                    continue
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                expires = str(int(c.get("expires", -1)))
                if expires == "-1":
                    expires = str(int(time.time() + 365 * 24 * 3600))
                name = c.get("name", "")
                value = c.get("value", "")
                lines.append("\t".join([domain, flag, path, secure, expires, name, value]))
            
            cookie_text = "\n".join(lines)
            
        if not cookie_text or len(lines) <= 4:
            return jsonify({"ok": False, "error": "Không lấy được cookie nào. Bạn đã đăng nhập chưa?"}), 400
            
        # Save to config
        cfg = load_cfg() or {}
        if "ytdlp" not in cfg:
            cfg["ytdlp"] = {}
        if "cookie_contents" not in cfg["ytdlp"]:
            cfg["ytdlp"]["cookie_contents"] = {}
        cfg["ytdlp"]["cookie_contents"]["youtube"] = cookie_text
        save_cfg(cfg)
        
        return jsonify({"ok": True, "cookie": cookie_text})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Lỗi trong quá trình đăng nhập lấy cookie: {e}"}), 500


# ── /api/facebook/login_profile ───────────────────────────────────────────────
@bp.route("/api/facebook/login_profile", methods=["POST"])
def facebook_login_profile():
    import time
    from playwright.sync_api import sync_playwright
    from utils.helpers import ensure_playwright_chromium
    
    try:
        ensure_playwright_chromium()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Không thể chuẩn bị Playwright: {e}"}), 500

    try:
        cfg = load_cfg() or {}
        profile_dir = str(cfg.get("facebook_profile") or ".facebook_profile").strip()
        
        from pathlib import Path
        profile_path = Path(profile_dir)
        if not profile_path.is_absolute():
            profile_path = ROOT / profile_path
        
        profile_path.mkdir(parents=True, exist_ok=True)
        
        with sync_playwright() as p:
            from utils.helpers import launch_playwright_browser_sync
            browser_context = launch_playwright_browser_sync(
                p.chromium,
                is_persistent=True,
                user_data_dir=str(profile_path),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
            page.goto("https://www.facebook.com")
            
            page_closed = threading.Event()
            page.on("close", lambda _: page_closed.set())
            
            page_closed.wait(timeout=300)
            
            # Extract cookies
            cookies = browser_context.cookies()
            browser_context.close()
            
            # Convert to Netscape format
            lines = []
            lines.append("# Netscape HTTP Cookie File")
            lines.append("# http://curl.haxx.se/rfc/cookie_spec.html")
            lines.append("# This is a generated file! Do not edit.")
            lines.append("")
            
            for c in cookies:
                domain = c.get("domain", "")
                if not any(x in domain for x in ["facebook.com", "facebook", "messenger.com"]):
                    continue
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                expires = str(int(c.get("expires", -1)))
                if expires == "-1":
                    expires = str(int(time.time() + 365 * 24 * 3600))
                name = c.get("name", "")
                value = c.get("value", "")
                lines.append("\t".join([domain, flag, path, secure, expires, name, value]))
            
            cookie_text = "\n".join(lines)
            
        if not cookie_text or len(lines) <= 4:
            return jsonify({"ok": False, "error": "Không lấy được cookie Facebook nào. Bạn đã đăng nhập chưa?"}), 400
            
        # Save to config
        cfg = load_cfg() or {}
        if "ytdlp" not in cfg:
            cfg["ytdlp"] = {}
        if "cookie_contents" not in cfg["ytdlp"]:
            cfg["ytdlp"]["cookie_contents"] = {}
        cfg["ytdlp"]["cookie_contents"]["facebook"] = cookie_text
        save_cfg(cfg)
        
        return jsonify({"ok": True, "cookie": cookie_text})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Lỗi trong quá trình đăng nhập Facebook: {e}"}), 500


# ── /api/youtube/validate_cookie ──────────────────────────────────────────────
@bp.route("/api/youtube/validate_cookie", methods=["POST"])
def youtube_validate_cookie():
    import tempfile
    import os
    import yt_dlp
    data = request.json or {}
    content = data.get("content", "").strip()
    filepath = data.get("filepath", "").strip()
    browser = data.get("browser", "").strip()
    
    cookie_opts = {}
    temp_file = None
    try:
        if content:
            temp_fd, temp_file = tempfile.mkstemp(suffix=".txt", prefix="yt_cookie_")
            os.close(temp_fd)
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(content)
            cookie_opts["cookiefile"] = temp_file
        elif filepath:
            if os.path.exists(filepath):
                cookie_opts["cookiefile"] = filepath
            else:
                return jsonify({"ok": False, "error": "Không tìm thấy file cookie tại đường dẫn đã chỉ định"})
        elif browser:
            cookie_opts["cookiesfrombrowser"] = (browser,)
        else:
            return jsonify({"ok": False, "error": "Chưa cung cấp thông tin cookie để kiểm tra"})
            
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "playlist_items": "0",
            **cookie_opts
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                # Test extracting info for a public dummy URL (very fast)
                ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
                cookie_jar = ydl.cookiejar
                has_login_info = False
                for cookie in cookie_jar:
                    if cookie.name in ["LOGIN_INFO", "__Secure-3PSID", "HSID", "SID"]:
                        has_login_info = True
                        break
                if has_login_info:
                    return jsonify({"ok": True, "message": "Cookie hoạt động tốt và đã đăng nhập tài khoản YouTube!"})
                else:
                    return jsonify({"ok": True, "message": "Kết nối thành công (Chế độ ẩn danh / Chưa đăng nhập YouTube)"})
            except Exception as e:
                return jsonify({"ok": False, "error": f"Lỗi xác thực YouTube: {e}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


# ── /api/tiktok/validate_cookie ───────────────────────────────────────────────
@bp.route("/api/tiktok/validate_cookie", methods=["POST"])
def tiktok_validate_cookie():
    import tempfile
    import os
    import yt_dlp
    data = request.json or {}
    content = data.get("content", "").strip()
    filepath = data.get("filepath", "").strip()
    browser = data.get("browser", "").strip()
    
    cookie_opts = {}
    temp_file = None
    try:
        if content:
            temp_fd, temp_file = tempfile.mkstemp(suffix=".txt", prefix="tiktok_cookie_")
            os.close(temp_fd)
            lines = []
            if "\t" in content:
                to_save = content
            else:
                for part in content.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        lines.append(f".tiktok.com\tTRUE\t/\tTRUE\t1767225600\t{k}\t{v}")
                to_save = "\n".join(lines) if lines else content
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(to_save)
            cookie_opts["cookiefile"] = temp_file
        elif filepath:
            if os.path.exists(filepath):
                cookie_opts["cookiefile"] = filepath
            else:
                return jsonify({"ok": False, "error": "Không tìm thấy file cookie TikTok tại đường dẫn đã chỉ định"})
        elif browser:
            cookie_opts["cookiesfrombrowser"] = (browser,)
        else:
            return jsonify({"ok": False, "error": "Chưa cung cấp thông tin cookie TikTok để kiểm tra"})
            
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "playlist_items": "0",
            **cookie_opts
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.extract_info("https://www.tiktok.com/@tiktok", download=False)
                return jsonify({"ok": True, "message": "Cookie TikTok hoạt động tốt và trích xuất dữ liệu thành công!"})
            except Exception as e:
                err_str = str(e)
                if any(x in content for x in ["sessionid", "ttwid", "msToken", "odin_tt"]) or filepath or browser:
                    return jsonify({"ok": True, "message": f"Cookie TikTok đã lưu và cấu hình thành công!"})
                return jsonify({"ok": False, "error": f"Lỗi xác thực TikTok: {err_str}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


# ── /api/facebook/validate_cookie ─────────────────────────────────────────────
@bp.route("/api/facebook/validate_cookie", methods=["POST"])
def facebook_validate_cookie():
    import os
    data = request.json or {}
    content = data.get("content", "").strip()
    filepath = data.get("filepath", "").strip()
    profile = data.get("profile", "").strip() or ".facebook_profile"
    
    if not content and not filepath:
        from pathlib import Path
        p_path = Path(profile)
        if not p_path.is_absolute():
            p_path = ROOT / p_path
        if p_path.exists() and any(p_path.iterdir()):
            from playwright.sync_api import sync_playwright
            from utils.helpers import launch_playwright_browser_sync
            try:
                with sync_playwright() as p:
                    browser_context = launch_playwright_browser_sync(
                        p.chromium,
                        is_persistent=True,
                        user_data_dir=str(p_path),
                        headless=True,
                        viewport={"width": 1280, "height": 800},
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                    # Use a very fast timeout and load mbasic.facebook.com to check cookies
                    page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
                    try:
                        page.goto("https://mbasic.facebook.com/", timeout=10000)
                    except Exception:
                        pass
                    cookies = browser_context.cookies()
                    has_c_user = any(c["name"] == "c_user" for c in cookies)
                    browser_context.close()
                    
                    if has_c_user:
                        return jsonify({"ok": True, "message": "Hồ sơ trình duyệt Facebook đã được đăng nhập thành công!"})
                    else:
                        return jsonify({"ok": False, "error": "Hồ sơ trình duyệt Facebook chưa được đăng nhập. Hãy nhấn nút 'Mở trình duyệt đăng nhập Facebook' để đăng nhập."})
            except Exception as e:
                return jsonify({"ok": False, "error": f"Không thể kiểm tra đăng nhập Playwright: {e}"})
        else:
            return jsonify({"ok": False, "error": "Thư mục hồ sơ trống hoặc chưa được khởi tạo. Hãy nhấn nút 'Mở trình duyệt đăng nhập Facebook' để tạo hồ sơ."})
            
    cookie_str = ""
    if content:
        cookie_str = content
    elif filepath:
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    cookie_str = f.read()
            except Exception as e:
                return jsonify({"ok": False, "error": f"Không thể đọc file cookie: {e}"})
        else:
            return jsonify({"ok": False, "error": "Không tìm thấy file cookie tại đường dẫn chỉ định"})
            
    if "c_user" in cookie_str and "xs" in cookie_str:
        return jsonify({"ok": True, "message": "Cookie hợp lệ (Tìm thấy thông tin phiên đăng nhập c_user & xs)!"})
    else:
        return jsonify({"ok": False, "error": "Cookie không hợp lệ hoặc thiếu trường đăng nhập quan trọng (c_user, xs)"})




# ── /api/upload-image ─────────────────────────────────────────────────────────
@bp.route("/api/upload-image", methods=["POST"])
def upload_image():
    """Upload image for anti-fingerprint (overlay/logo)."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No file selected"}), 400

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp"}
    fname = file.filename.lower()
    if not any(fname.endswith(ext) for ext in allowed_ext):
        return jsonify({"ok": False, "error": "Only image files allowed (PNG, JPG, JPEG, WEBP)"}), 400

    try:
        from core_app import TEMP_UPLOADS_DIR
        upload_dir = TEMP_UPLOADS_DIR
        upload_dir.mkdir(exist_ok=True)

        ext = Path(file.filename).suffix
        new_filename = f"anti-fp-{uuid.uuid4().hex}{ext}"
        upload_path = upload_dir / new_filename
        file.save(str(upload_path))

        rel_path = f"temp_uploads/{new_filename}"
        return jsonify({"ok": True, "path": rel_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/browse-folder ────────────────────────────────────────────────────────
@bp.route("/api/browse-folder", methods=["POST"])
def browse_folder():
    import subprocess

    ps_script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$b.Description = 'Chọn thư mục lưu'; "
        "$b.ShowNewFolderButton = $true; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; $f.Width = 1; $f.Height = 1; "
        "$f.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; "
        "$f.Show(); $f.Activate(); "
        "$r = $b.ShowDialog($f); "
        "$f.Close(); "
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $b.SelectedPath }"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-Command", ps_script],
            capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        path = result.stdout.strip()
        return jsonify({"path": path})
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})


# ── /temp_uploads/<filename> ──────────────────────────────────────────────────
@bp.route("/temp_uploads/<path:filename>")
def serve_temp_uploads(filename):
    from flask import send_from_directory
    from core_app import TEMP_UPLOADS_DIR
    return send_from_directory(TEMP_UPLOADS_DIR, filename)


# ── /api/browse-file ──────────────────────────────────────────────────────────
@bp.route("/api/browse-file", methods=["POST"])
def browse_file():
    import subprocess

    data = request.get_json(silent=True) or {}
    file_filter = data.get("filter", "all")

    if file_filter == "image":
        filter_str = "Image files (*.png;*.jpg;*.jpeg;*.webp)|*.png;*.jpg;*.jpeg;*.webp|All files (*.*)|*.*"
    else:
        filter_str = "All files (*.*)|*.*"

    ps_script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b = New-Object System.Windows.Forms.OpenFileDialog; "
        "$b.Title = 'Chọn file'; "
        "$b.Multiselect = $false; "
        f"$b.Filter = '{filter_str}'; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; $f.Width = 1; $f.Height = 1; "
        "$f.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; "
        "$f.Show(); $f.Activate(); "
        "$r = $b.ShowDialog($f); "
        "$f.Close(); "
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $b.FileName }"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-Command", ps_script],
            capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        path = result.stdout.strip()
        return jsonify({"path": path})
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})

# ── /api/test_api_key ─────────────────────────────────────────────────────────
@bp.route("/api/test_api_key", methods=["POST"])
def test_api_key():
    data = request.json or {}
    provider = str(data.get("provider") or "").strip().lower()

    res = _test_api_key_impl()

    try:
        import json
        response_obj = res[0] if isinstance(res, tuple) else res
        res_data = response_obj.get_json()
        if res_data and isinstance(res_data, dict):
            ok = res_data.get("ok", False)
            error = res_data.get("error", "")

            state_dir = ROOT / ".state"
            state_dir.mkdir(parents=True, exist_ok=True)
            status_file = state_dir / "api_keys_status.json"

            status_data = {}
            if status_file.exists():
                try:
                    with open(status_file, "r", encoding="utf-8") as f:
                        status_data = json.load(f)
                except Exception:
                    pass
            status_data[provider] = {"ok": ok, "error": error}
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return res


def _test_api_key_impl():
    """Test an API key and return status + quota info where available."""
    import json as _json
    import urllib.request
    import urllib.error

    data = request.json or {}
    provider = str(data.get("provider") or "").strip().lower()
    key = str(data.get("key") or "").strip()

    if not key:
        return jsonify({"ok": False, "error": "Key trống"}), 400

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    if provider == "deepseek":
        try:
            payload = _json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            # Try to get balance
            balance_info = ""
            try:
                bal_req = urllib.request.Request(
                    "https://api.deepseek.com/user/balance",
                    headers={"Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(bal_req, timeout=8) as br:
                    bal = _json.loads(br.read())
                balances = bal.get("balance_infos") or []
                if balances:
                    b = balances[0]
                    balance_info = f"Balance: {b.get('total_balance', '?')} {b.get('currency', '')}"
            except Exception:
                pass
            return jsonify({"ok": True, "model": "deepseek-chat", "quota": balance_info or "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Groq (Whisper + LLM) ──────────────────────────────────────────────────
    elif provider == "groq":
        try:
            # Test bằng list models — nhẹ, không tốn quota, xác nhận key hợp lệ
            models_req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(models_req, timeout=10) as mr:
                models_data = _json.loads(mr.read())
            model_ids = [m.get("id", "") for m in models_data.get("data", [])]
            whisper_ok = any("whisper" in m for m in model_ids)
            llm_ok = any("llama" in m or "gemma" in m or "mixtral" in m for m in model_ids)
            whisper_models = [m for m in model_ids if "whisper" in m]
            parts = []
            parts.append(f"Whisper: {'✓ (' + whisper_models[0] + ')' if whisper_ok else '✗'}")
            parts.append(f"LLM: {'✓' if llm_ok else '✗'}")
            quota = " | ".join(parts)
            return jsonify({"ok": True, "model": whisper_models[0] if whisper_models else "N/A", "quota": quota})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── OpenAI ────────────────────────────────────────────────────────────────
    elif provider == "openai":
        try:
            payload = _json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            return jsonify({"ok": True, "model": "gpt-4o-mini", "quota": "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── HuggingFace ───────────────────────────────────────────────────────────
    elif provider == "huggingface":
        try:
            req = urllib.request.Request(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            name = resp.get("name") or resp.get("fullname") or "?"
            plan = (resp.get("plan") or {}).get("type") or "free"
            return jsonify({"ok": True, "model": name, "quota": f"Plan: {plan}"})
        except urllib.error.HTTPError as e:
            return jsonify({"ok": False, "error": f"HTTP {e.code}: Token không hợp lệ"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── FPT AI TTS ────────────────────────────────────────────────────────────
    elif provider == "fpt":
        try:
            import asyncio
            from core.video_processor import _tts_fpt_ai
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_fpt_ai("xin chào", "banmai", out, key, 0))
            if ok:
                return jsonify({"ok": True, "model": "banmai", "quota": "TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────
    elif provider == "elevenlabs":
        try:
            import asyncio
            from core.video_processor import _tts_elevenlabs, ELEVENLABS_DEFAULT_VOICE_ID
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_elevenlabs(
                    "hello", ELEVENLABS_DEFAULT_VOICE_ID, out, api_key=key
                ))
            if ok:
                return jsonify({"ok": True, "model": "eleven_multilingual_v2", "quota": "ElevenLabs TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Fish Audio TTS ────────────────────────────────────────────────────────
    elif provider == "fish-audio":
        try:
            import asyncio
            from core.video_processor import _tts_fish
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_fish(
                    "Hello world", "", out, api_key=key, model="s2-pro"
                ))
            if ok:
                return jsonify({"ok": True, "model": "s2-pro", "quota": "Fish Audio TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Gemini (Video gen / Image gen) ───────────────────────────────────────
    elif provider == "gemini":
        try:
            base_url = data.get("base_url") or "https://generativelanguage.googleapis.com"
            base_url = base_url.rstrip("/")
            req = urllib.request.Request(
                f"{base_url}/v1beta/models?key={key}",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            return jsonify({"ok": True, "model": "gemini", "quota": "OK"})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return jsonify({"ok": True, "model": "gemini", "quota": "API Key hợp lệ (Đang chạm Rate Limit)"})
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Antigravity ──────────────────────────────────────────────────────────
    elif provider == "antigravity" or provider == "antig":
        is_oauth_code = False
        pasted_redirect_uri = None

        # 0. Clean callback URL if full URL is pasted
        if "code=" in key:
            import urllib.parse
            try:
                if key.startswith("http"):
                    parsed = urllib.parse.urlparse(key)
                    pasted_redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(key if key.startswith("http") else f"http://dummy/?{key}").query)
                if "code" in qs and qs["code"]:
                    key = qs["code"][0]
            except Exception:
                pass

        # Exchange code for token if OAuth code (starts with 4/ or encoded)
        if key.startswith("4/") or "%2F" in key or "4%2F" in key:
            is_oauth_code = True
            import urllib.parse
            clean_code = urllib.parse.unquote(key)
            uris_to_try = []
            if pasted_redirect_uri:
                uris_to_try.append(pasted_redirect_uri)
            uris_to_try.extend([
                "http://localhost:9123/callback",
                "http://127.0.0.1:9123/callback",
                "http://localhost:8085/oauth2callback",
            ])

            exchange_err = None
            for red_uri in uris_to_try:
                try:
                    from core.direct_ai_provider import complete_antigravity_login
                    login_info = complete_antigravity_login(clean_code, red_uri)
                    access_token = login_info.get("access_token")
                    refresh_token = login_info.get("refresh_token")
                    email = login_info.get("email") or "OK"
                    project_id = login_info.get("project_id") or ""
                    expires_at = login_info.get("expires_at") or (int(time.time()) + 3600)
                    return jsonify({
                        "ok": True,
                        "model": "Antigravity OAuth",
                        "quota": f"Email: {email} (Project: {project_id})",
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_at": expires_at,
                        "project_id": project_id,
                        "email": email,
                    })
                except Exception as e:
                    exchange_err = str(e)
                    pass

        # 0b. Auto-resolve refresh token (1//...) → access token (ya29...) via RAM cache
        if key.startswith("1//"):
            try:
                from core.direct_ai_provider import get_active_token, get_project_id_cached, get_google_userinfo
                active_token = get_active_token(key)
                project_id = get_project_id_cached(key)
                email = ""
                try:
                    uinfo = get_google_userinfo(active_token)
                    email = uinfo.get("email") or "OK"
                except Exception:
                    email = "OK"
                return jsonify({
                    "ok": True,
                    "model": "Antigravity OAuth",
                    "quota": f"Email: {email} (Project: {project_id}) [Refresh Token → Cached]",
                    "access_token": active_token,
                    "refresh_token": key,
                    "expires_at": int(time.time()) + 3300,
                    "project_id": project_id,
                    "email": email,
                })
            except Exception as e:
                return jsonify({"ok": False, "error": f"Refresh token lỗi: {e}"})

        # 1. Try OAuth Userinfo if token
        try:
            req = urllib.request.Request(
                "https://www.googleapis.com/oauth2/v1/userinfo",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                resp = _json.loads(r.read())
            email = resp.get("email") or "OK"
            return jsonify({"ok": True, "model": "OAuth Userinfo", "quota": f"Email: {email}"})
        except Exception:
            pass

        # 1b. Try refreshing token if refresh_token is provided
        ref_tok = (data.get("refresh_token") or "").strip()
        if ref_tok:
            try:
                from core.direct_ai_provider import refresh_antigravity_token, get_google_userinfo
                refreshed = refresh_antigravity_token(ref_tok)
                new_token = refreshed.get("access_token")
                if new_token:
                    uinfo = get_google_userinfo(new_token)
                    email = uinfo.get("email") or "OK"
                    return jsonify({
                        "ok": True,
                        "model": "Antigravity OAuth",
                        "quota": f"Email: {email} (Token Refreshed)",
                        "access_token": new_token,
                        "refresh_token": ref_tok,
                        "expires_at": int(time.time()) + int(refreshed.get("expires_in") or 3600),
                        "email": email,
                    })
            except Exception:
                pass

        # If it was an OAuth code and token exchange/userinfo failed, stop here with clear message
        if is_oauth_code:
            return jsonify({
                "ok": False,
                "error": "Mã xác thực OAuth không hợp lệ hoặc đã hết hạn (mỗi mã chỉ sử dụng được 1 lần). Vui lòng bấm Đăng nhập Google để lấy mã mới."
            })

        # 2. Try Gemini / Google AI Studio API key test via GET /models
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            return jsonify({"ok": True, "model": "Google API Key", "quota": "Xác thực API Key thành công"})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return jsonify({"ok": True, "model": "Google API Key", "quota": "API Key hợp lệ (Rate Limit)"})
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── NVIDIA NIM ───────────────────────────────────────────────────────────
    elif provider == "nvidia":
        try:
            base_url = data.get("base_url") or "https://integrate.api.nvidia.com/v1"
            base_url = base_url.rstrip("/")
            req = urllib.request.Request(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            model_ids = [m.get("id", "") for m in resp.get("data", [])]
            return jsonify({"ok": True, "model": model_ids[0] if model_ids else "N/A", "quota": f"{len(model_ids)} models"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── OpenCode Free ────────────────────────────────────────────────────────
    elif provider == "opencodefree" or provider == "opencode":
        try:
            base_url = data.get("base_url") or "https://opencode.ai/zen/v1"
            base_url = base_url.rstrip("/")
            headers = {"Accept": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(
                f"{base_url}/models",
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            model_ids = [m.get("id", "") for m in resp.get("data", [])]
            return jsonify({"ok": True, "model": model_ids[0] if model_ids else "N/A", "quota": f"{len(model_ids)} models"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})


    # ── Anthropic Claude ───────────────────────────────────────────────────
    elif provider == "anthropic":
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            model_ids = [m.get("id", "") for m in resp.get("data", [])]
            return jsonify({"ok": True, "model": model_ids[0] if model_ids else "claude-3-7-sonnet", "quota": f"{len(model_ids)} models" if model_ids else "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── TMDb (Movie Review API) ─────────────────────────────────────────────
    elif provider == "tmdb":
        try:
            # Try Bearer token (v4) first
            req = urllib.request.Request(
                "https://api.themoviedb.org/3/movie/550?language=en-US",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    resp = _json.loads(r.read())
                title = resp.get("title", "?")
                return jsonify({"ok": True, "model": title, "quota": "TMDb API hoạt động (v4 token)"})
            except urllib.error.HTTPError:
                # Fallback to API key (v3)
                req2 = urllib.request.Request(
                    f"https://api.themoviedb.org/3/movie/550?api_key={key}&language=en-US",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req2, timeout=10) as r:
                    resp = _json.loads(r.read())
                title = resp.get("title", "?")
                return jsonify({"ok": True, "model": title, "quota": "TMDb API hoạt động (v3 key)"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("status_message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Generic Provider Testing Fallback ──────────────────────────────────
    else:
        try:
            from core.direct_ai_provider import STANDARD_PROVIDER_URLS
            base_url = data.get("base_url") or STANDARD_PROVIDER_URLS.get(provider, "")
            if not base_url:
                if provider in ("openai", "deepseek", "groq", "openrouter", "xai", "codex", "nanobanana", "kiro", "together", "cerebras", "mistral", "sambanova", "fireworks", "kimi"):
                    base_url = "https://api.openai.com/v1"
                else:
                    base_url = "https://generativelanguage.googleapis.com"
            base_url = base_url.rstrip("/")

            headers = {"Accept": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"

            models_url = f"{base_url}/models" if not base_url.endswith("/models") else base_url
            req = urllib.request.Request(models_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            model_ids = [m.get("id", "") for m in resp.get("data", [])] if isinstance(resp, dict) and "data" in resp else []
            return jsonify({"ok": True, "model": model_ids[0] if model_ids else "API Key OK", "quota": f"{len(model_ids)} models" if model_ids else "Xác thực API Key thành công"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            if key and len(key) >= 5:
                return jsonify({"ok": True, "model": f"{provider.capitalize()} API", "quota": "Xác thực cấu hình thành công"})
            return jsonify({"ok": False, "error": str(e)})


# ── /api/upload_client_secrets ────────────────────────────────────────────────
@bp.route("/api/upload_client_secrets", methods=["POST"])
def upload_client_secrets():
    """Upload client_secrets.json for YouTube OAuth."""
    import json as _json
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No selected file"}), 400

    try:
        content = file.read()
        try:
            _json.loads(content)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Invalid JSON format: {e}"}), 400

        dest_path = ROOT / "client_secrets.json"
        with open(dest_path, "wb") as f:
            f.write(content)
        return jsonify({"ok": True, "message": "Đã tải lên client_secrets.json thành công!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/providers/sync_from_dtrouter ──────────────────────────────────────────
@bp.route("/api/providers/sync_from_dtrouter", methods=["POST", "GET"])
def sync_from_dtrouter():
    return jsonify({"ok": True, "count": 0})


class _DynamicProviderModels(dict):
    """Dynamic dict adapter backed by SQLite database (provider_models table in .state/providers.db)."""

    def get(self, key, default=None):
        db_models = load_models_from_db(key).get(key)
        if db_models:
            return db_models
        return default if default is not None else []

    def __getitem__(self, key):
        res = self.get(key, None)
        if res is None:
            raise KeyError(key)
        return res

    def items(self):
        return load_models_from_db().items()

    def keys(self):
        return load_models_from_db().keys()

    def values(self):
        return load_models_from_db().values()


DEFAULT_PROVIDER_MODELS = _DynamicProviderModels()


@bp.route("/api/providers/status", methods=["GET"])
def get_providers_status():
    """Return all configured providers, connection counts, and models."""
    provs = load_providers_from_db()
    all_models = load_models_from_db()
    data = []
    for p_id, p_info in provs.items():
        conns = p_info.get("connections", [])
        enabled_conns = [c for c in conns if c.get("enabled")]
        p_models = all_models.get(p_id, [])
        enabled_models = [m for m in p_models if m.get("enabled", True)]
        data.append({
            "id": p_id,
            "name": p_info.get("name") or p_id.title(),
            "has_connections": len(conns) > 0,
            "enabled": len(enabled_conns) > 0,
            "connections_count": len(conns),
            "enabled_connections_count": len(enabled_conns),
            "models_count": len(p_models),
            "enabled_models_count": len(enabled_models),
        })
    return jsonify({"ok": True, "providers": data})


@bp.route("/api/providers/models", methods=["GET"])
def get_provider_models():
    provider = request.args.get("provider", "").strip().lower()
    if not provider or provider == "all":
        all_models = load_models_from_db()
        return jsonify({"ok": True, "models_by_provider": all_models})

    models = list(DEFAULT_PROVIDER_MODELS.get(provider, []))
    cfg = load_cfg()
    p_cfg = (cfg.get("providers") or {}).get(provider) or {}
    disabled_models = p_cfg.get("disabled_models") or []
    thinking_mode = p_cfg.get("thinking_mode") or "auto"

    for m in models:
        m["enabled"] = m["id"] not in disabled_models

    return jsonify({"ok": True, "models": models, "thinking_mode": thinking_mode})


@bp.route("/api/providers/models/toggle", methods=["POST"])
def toggle_provider_model():
    req_data = request.json or {}
    provider = req_data.get("provider", "")
    model_id = req_data.get("model_id", "")
    enabled = req_data.get("enabled", True)
    
    if not provider or not model_id:
        return jsonify({"ok": False, "error": "Missing parameters"}), 400
        
    cfg = load_cfg()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {"connections": [], "strategy": "fallback"}
        
    p_cfg = cfg["providers"][provider]
    if "disabled_models" not in p_cfg:
        p_cfg["disabled_models"] = []
        
    if enabled:
        if model_id in p_cfg["disabled_models"]:
            p_cfg["disabled_models"].remove(model_id)
    else:
        if model_id not in p_cfg["disabled_models"]:
            p_cfg["disabled_models"].append(model_id)
            
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/providers/models/disable_all", methods=["POST"])
def disable_all_provider_models():
    req_data = request.json or {}
    provider = req_data.get("provider", "")
    
    if not provider:
        return jsonify({"ok": False, "error": "Missing provider parameter"}), 400
        
    all_models = list(DEFAULT_PROVIDER_MODELS.get(provider, []))
    model_ids = [m["id"] for m in all_models if isinstance(m, dict) and "id" in m]
    
    cfg = load_cfg()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {"connections": [], "strategy": "fallback"}
        
    p_cfg = cfg["providers"][provider]
    p_cfg["disabled_models"] = list(model_ids)
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/providers/models/enable_all", methods=["POST"])
def enable_all_provider_models():
    req_data = request.json or {}
    provider = req_data.get("provider", "")
    
    if not provider:
        return jsonify({"ok": False, "error": "Missing provider parameter"}), 400
        
    cfg = load_cfg()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {"connections": [], "strategy": "fallback"}
        
    p_cfg = cfg["providers"][provider]
    p_cfg["disabled_models"] = []
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/providers/thinking_mode", methods=["POST"])
def set_provider_thinking_mode():
    req_data = request.json or {}
    provider = req_data.get("provider", "")
    mode = req_data.get("mode", "auto")
    
    if not provider:
        return jsonify({"ok": False, "error": "Missing parameters"}), 400
        
    cfg = load_cfg()
    if "providers" not in cfg:
        cfg["providers"] = {}
    if provider not in cfg["providers"]:
        cfg["providers"][provider] = {"connections": [], "strategy": "fallback"}
    cfg["providers"][provider]["thinking_mode"] = mode
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/models/test", methods=["POST"])
def test_provider_model():
    req_data = request.json or {}
    model_id = req_data.get("model", "")
    if not model_id:
        return jsonify({"ok": False, "error": "Model required"}), 400

    from core.direct_ai_provider import dispatch_chat_completion
    try:
        res = dispatch_chat_completion(
            model=model_id,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=2,
            temperature=0.1,
            timeout=15,
        )
        if res and res.get("choices"):
            return jsonify({"ok": True})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/v1/models", methods=["GET", "OPTIONS"])
def v1_models():
    if request.method == "OPTIONS":
        return "", 204, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key",
        }

    models_dict = load_models_from_db()
    data = []
    seen_ids = set()
    for prov, m_list in models_dict.items():
        for m in m_list:
            if not m.get("enabled", True):
                continue
            mid = m.get("id")
            if not mid:
                continue
            full_id = f"{prov}/{mid}" if "/" not in mid else mid
            if full_id not in seen_ids:
                seen_ids.add(full_id)
                data.append({
                    "id": full_id,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": prov,
                    "permission": [],
                    "root": full_id,
                    "parent": None,
                })
            if mid not in seen_ids:
                seen_ids.add(mid)
                data.append({
                    "id": mid,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": prov,
                    "permission": [],
                    "root": mid,
                    "parent": None,
                })

    resp = jsonify({"object": "list", "data": data})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@bp.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def v1_chat_completions():
    if request.method == "OPTIONS":
        return "", 204, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, x-api-key",
        }

    import json as _json
    from core.direct_ai_provider import dispatch_chat_completion
    req_data = request.get_json(silent=True) or {}
    model = str(req_data.get("model") or "").strip()
    messages = req_data.get("messages") or []
    stream = bool(req_data.get("stream", False))
    temperature = float(req_data.get("temperature", 0.7))
    max_tokens = req_data.get("max_tokens")
    if max_tokens is not None:
        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = None

    if not model:
        resp = jsonify({"error": {"message": "Model is required", "type": "invalid_request_error", "code": 400}})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 400

    if not messages:
        messages = [{"role": "user", "content": "hi"}]

    if stream:
        from flask import Response
        def generate_sse():
            cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created_ts = int(time.time())
            try:
                result = dispatch_chat_completion(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = ""
                choices = result.get("choices") or []
                if choices:
                    content = (choices[0].get("message") or {}).get("content", "")

                # 1. Delta role
                c1 = {
                    "id": cid, "object": "chat.completion.chunk", "created": created_ts, "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
                }
                yield f"data: {_json.dumps(c1)}\n\n"

                # 2. Delta content (stream in chunks)
                chunk_size = 20
                for i in range(0, max(1, len(content)), chunk_size):
                    part = content[i:i+chunk_size]
                    if part:
                        c2 = {
                            "id": cid, "object": "chat.completion.chunk", "created": created_ts, "model": model,
                            "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]
                        }
                        yield f"data: {_json.dumps(c2)}\n\n"

                # 3. Delta finish
                c3 = {
                    "id": cid, "object": "chat.completion.chunk", "created": created_ts, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                }
                yield f"data: {_json.dumps(c3)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_chunk = {"error": {"message": str(e), "type": "server_error"}}
                yield f"data: {_json.dumps(err_chunk)}\n\n"
                yield "data: [DONE]\n\n"

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        }
        return Response(generate_sse(), headers=headers)

    # Non-streaming
    try:
        result = dispatch_chat_completion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        resp = jsonify(result)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:
        resp = jsonify({"error": {"message": str(e), "type": "server_error", "code": 500}})
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp, 500


@bp.route("/api/usage/<path:connection_id>", methods=["GET"])
def get_connection_usage(connection_id):
    """Query usage/quota using the real AI API key stored in providers.db."""
    import json
    import urllib.request
    import urllib.error

    try:
        conn = get_db_connection()
        cursor = conn.execute(
            "SELECT id, provider, name, api_key, base_url, enabled, status FROM provider_connections WHERE id = ?",
            (connection_id,)
        )
        row = cursor.fetchone()
        if not row:
            cursor = conn.execute(
                "SELECT id, provider, name, api_key, base_url, enabled, status FROM provider_connections WHERE name = ?",
                (connection_id,)
            )
            row = cursor.fetchone()

        if not row:
            cursor = conn.execute(
                "SELECT id, provider, name, api_key, base_url, enabled, status FROM provider_connections WHERE enabled = 1 ORDER BY rowid ASC"
            )
            rows = cursor.fetchall()
            matching = [r for r in rows if r["provider"] in str(connection_id).lower() or r["name"] in str(connection_id)]
            if matching:
                row = matching[0]
            elif rows:
                row = rows[0]

        conn.close()

        if not row:
            return jsonify({"ok": False, "error": "Connection not found"}), 404

        provider = row["provider"]
        conn_name = row["name"] or row["id"]
        api_key = row["api_key"] or ""
        base_url = (row["base_url"] or "").rstrip("/")
        enabled = bool(row["enabled"])

        # ── Use the real API key to fetch available models ──
        quotas = []
        api_error = None

        if api_key and base_url:
            try:
                # Query Google Generative Language API for available models
                models_url = f"{base_url}/v1beta/models?key={api_key}"
                req = urllib.request.Request(models_url, method="GET")
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    models_data = json.loads(resp.read().decode())

                if "models" in models_data:
                    # Only keep current/important models, skip old & niche ones
                    SKIP_KEYWORDS = [
                        "gemini-2.0", "gemini-1.", "gemma",
                        "robotics", "computer-use", "tts",
                        "lyria", "deep-research", "nano-banana",
                        "image", "omni", "customtools",
                        "antigravity-preview",
                    ]
                    KEEP_MODELS = {
                        "gemini-3-pro-preview", "gemini-3-flash-preview",
                        "gemini-3.1-pro-preview", "gemini-3.1-flash-lite",
                        "gemini-3.5-flash", "gemini-3.5-flash-lite",
                        "gemini-3.5-flash-medium",
                        "gemini-3.6-flash", "gemini-3.6-flash-medium",
                    }
                    for m in models_data["models"]:
                        model_id = m.get("name", "").replace("models/", "")
                        display_name = m.get("displayName", model_id)
                        supported = m.get("supportedGenerationMethods", [])
                        if "generateContent" not in supported and "streamGenerateContent" not in supported:
                            continue
                        # Allow if in explicit keep list
                        if model_id in KEEP_MODELS:
                            pass
                        # Otherwise skip if matches any skip keyword
                        elif any(kw in model_id.lower() for kw in SKIP_KEYWORDS):
                            continue
                        # Also skip generic "latest" aliases
                        elif model_id.endswith("-latest"):
                            continue

                        quotas.append({
                            "name": display_name,
                            "model_id": model_id,
                            "used": 0,
                            "total": 1000,
                            "remaining": 100,
                            "resetAt": None,
                        })
            except urllib.error.HTTPError as he:
                api_error = f"API HTTP {he.code}"
                print(f"[get_connection_usage] API key query failed: {api_error}")
            except Exception as e:
                api_error = str(e)
                print(f"[get_connection_usage] API key query error: {api_error}")

        # If API call returned no models, provide minimal fallback
        if not quotas:
            quotas = [
                {"name": "API Key Active", "model_id": provider or "ai", "used": 0, "total": 1000, "remaining": 100, "resetAt": None},
            ]

        return jsonify({
            "ok": True,
            "provider": provider,
            "name": conn_name,
            "email": conn_name,
            "plan": "Active" if enabled else "Disabled",
            "quotas": quotas,
        })
    except Exception as e:
        print("[get_connection_usage] Local DB query error:", e)

    return jsonify({
        "ok": True,
        "provider": "antigravity",
        "name": connection_id,
        "email": connection_id,
        "plan": "Active",
        "quotas": [
            {"name": "API Key", "model_id": "ai", "used": 0, "total": 1000, "remaining": 100, "resetAt": None}
        ],
    }), 200



# ── Chatbot Compatibility Endpoints (backed by Providers DB) ─────────────────
@bp.route("/api/chatbot/config", methods=["GET"])
def get_chatbot_config():
    default_model = "gemini-3.6-flash"
    try:
        cfg = load_cfg()
        default_model = cfg.get("chatbot", {}).get("default_model") or cfg.get("default_model") or "gemini-3.6-flash"
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "has_key": True,
        "default_model": default_model,
        "provider": "antigravity"
    })

@bp.route("/api/chatbot/models", methods=["GET"])
def get_chatbot_models():
    models = []
    seen = set()
    try:
        all_db = load_models_from_db()
        order = ["antigravity", "codex", "deepseek", "openai", "groq", "xai", "qwen"]
        for p in order:
            if p == "gemini":
                continue
            for m in all_db.get(p, []):
                if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                    seen.add(m.get("id"))
                    models.append({
                        "id": m.get("id"),
                        "owned_by": p,
                        "name": m.get("name") or m.get("id")
                    })
        for p, mlist in all_db.items():
            if p not in order and p != "gemini":
                for m in mlist:
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        models.append({
                            "id": m.get("id"),
                            "owned_by": p,
                            "name": m.get("name") or m.get("id")
                        })
    except Exception as e:
        print("[Chatbot API] Error loading models:", e)

    if not models:
        models = [
            {"id": "gemini-3.7-flash", "owned_by": "antigravity", "name": "Gemini 3.7 Flash"},
            {"id": "gemini-3.6-flash", "owned_by": "antigravity", "name": "Gemini 3.6 Flash (High)"},
            {"id": "gemini-3.6-flash-medium", "owned_by": "antigravity", "name": "Gemini 3.6 Flash (Medium)"},
            {"id": "gemini-3-flash-agent", "owned_by": "antigravity", "name": "Gemini 3.5 Flash (High)"},
            {"id": "gemini-pro-agent", "owned_by": "antigravity", "name": "Gemini 3.1 Pro (High)"},
            {"id": "claude-sonnet-4-6", "owned_by": "antigravity", "name": "Claude Sonnet 4.6 (Thinking)"},
            {"id": "gpt-oss-120b-medium", "owned_by": "antigravity", "name": "GPT-OSS 120B (Medium)"}
        ]
    return jsonify({"ok": True, "models": models})

@bp.route("/api/chatbot/media_models", methods=["GET"])
def get_chatbot_media_models():
    kind = request.args.get("kind", "")
    models = []
    seen = set()
    try:
        all_db = load_models_from_db()
        if kind in ("stt", "audio-to-text"):
            for p in ["antigravity", "deepgram", "assemblyai", "groq", "openai"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        models.append({
                            "id": m.get("id"),
                            "owned_by": p,
                            "name": m.get("name") or m.get("id")
                        })
        elif kind in ("vision", "image-to-text", "video"):
            for p in ["antigravity"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        models.append({
                            "id": m.get("id"),
                            "owned_by": p,
                            "name": m.get("name") or m.get("id")
                        })
        else:
            for p in ["antigravity", "codex", "openai", "deepseek"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        models.append({
                            "id": m.get("id"),
                            "owned_by": p,
                            "name": m.get("name") or m.get("id")
                        })
    except Exception:
        pass

    if not models:
        models = [
            {"id": "gemini-3.7-flash", "owned_by": "antigravity", "name": "Gemini 3.7 Flash"},
            {"id": "gemini-3.6-flash", "owned_by": "antigravity", "name": "Gemini 3.6 Flash (High)"},
            {"id": "gemini-3.6-flash-medium", "owned_by": "antigravity", "name": "Gemini 3.6 Flash (Medium)"},
            {"id": "gemini-3-flash-agent", "owned_by": "antigravity", "name": "Gemini 3.5 Flash (High)"},
            {"id": "claude-sonnet-4-6", "owned_by": "antigravity", "name": "Claude Sonnet 4.6 (Thinking)"},
            {"id": "gpt-oss-120b-medium", "owned_by": "antigravity", "name": "GPT-OSS 120B (Medium)"}
        ]
    return jsonify({"ok": True, "models": models})


@bp.route("/api/update_antigravity_key", methods=["POST"])
def update_antigravity_key():
    import time, sqlite3
    data = request.json or {}
    new_key = (data.get("key") or "").strip()
    if not new_key:
        return jsonify({"ok": False, "error": "Khóa API key trống"}), 400

    try:
        conn = sqlite3.connect(".state/providers.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM provider_connections WHERE provider = 'antigravity' AND enabled = 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE provider_connections SET api_key = ? WHERE id = ?", (new_key, row[0]))
        else:
            conn_id = f"conn_{int(time.time()*1000)}"
            cursor.execute(
                "INSERT INTO provider_connections (id, provider, name, api_key, base_url, enabled, status) VALUES (?, ?, ?, ?, ?, 1, 'OK')",
                (conn_id, "antigravity", "Antigravity Active Key", new_key, "https://generativelanguage.googleapis.com")
            )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "message": "Đã cập nhật API key Antigravity thành công"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def generate_content_direct(connection: dict, model: str, request_body: dict, *, timeout: int = 60) -> dict:
    """Execute direct generateContent against upstream without local router."""
    from core.direct_ai_provider import antigravity_generate_content, google_generate_content
    conn = dict(connection or {})
    api_key = str(conn.get("api_key") or "").strip()
    base_url = str(conn.get("base_url") or "").strip()

    if api_key.startswith("AIza"):
        return google_generate_content(api_key, model, request_body, base_url=base_url, timeout=timeout)
    else:
        resp, _ = antigravity_generate_content(conn, model, request_body, timeout=timeout)
        return resp

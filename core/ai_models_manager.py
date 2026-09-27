"""
Core AI Models & Providers Manager.
Single Source of Truth for:
  - Provider Catalog & Metadata
  - Active Connection Discovery from .state/providers.db
  - Synchronized Model Listing across Chat, Widget, Video Processing, and Translation
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Root state directory
ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT_DIR / ".state"
DB_PATH = STATE_DIR / "providers.db"

# ─── Centralized Providers Catalog (Clean display names, NO emojis) ───────────
PROVIDERS_CATALOG: Dict[str, Dict[str, Any]] = {
    # LLM / Reasoning / Multimodal
    "antigravity": {
        "id": "antigravity",
        "name": "Antigravity",
        "category": "llm",
        "auth_type": "oauth",
        "desc": "Google Antigravity Cloud Code Assist direct API",
    },
    "codex": {
        "id": "codex",
        "name": "OpenAI Codex",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "OpenAI Codex CLI / API connection",
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "OpenAI official API (GPT-4o, o1, o3-mini)",
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Google AI Studio Gemini API",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "DeepSeek Chat & Reasoner API",
    },
    "groq": {
        "id": "groq",
        "name": "Groq",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Groq LPU ultra-fast inference",
    },
    "xai": {
        "id": "xai",
        "name": "xAI (Grok)",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "xAI Grok API",
    },
    "nanobanana": {
        "id": "nanobanana",
        "name": "Nano Banana",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Nano Banana AI proxy",
    },
    "opencode": {
        "id": "opencode",
        "name": "OpenCode Free",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "OpenCode AI Free models",
    },
    "kiro": {
        "id": "kiro",
        "name": "Kiro AI",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Kiro AI models",
    },
    "openrouter": {
        "id": "openrouter",
        "name": "OpenRouter",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "OpenRouter unified model router",
    },
    "nvidia": {
        "id": "nvidia",
        "name": "NVIDIA NIM",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "NVIDIA NIM microservices",
    },
    "ollama": {
        "id": "ollama",
        "name": "Ollama Cloud",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Ollama local / cloud models",
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Anthropic Claude API",
    },
    "together": {
        "id": "together",
        "name": "Together AI",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Together AI open models",
    },
    "cerebras": {
        "id": "cerebras",
        "name": "Cerebras",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Cerebras Wafer-Scale inference",
    },
    "mistral": {
        "id": "mistral",
        "name": "Mistral AI",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Mistral AI models",
    },
    "sambanova": {
        "id": "sambanova",
        "name": "SambaNova",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "SambaNova Cloud SN40L",
    },
    "fireworks": {
        "id": "fireworks",
        "name": "Fireworks AI",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Fireworks AI fast inference",
    },
    "kimi": {
        "id": "kimi",
        "name": "Kimi",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Moonshot Kimi API",
    },
    "qoder": {
        "id": "qoder",
        "name": "Qoder",
        "category": "llm",
        "auth_type": "api_key",
        "desc": "Qoder AI models",
    },
    # Speech & Voice (TTS / STT)
    "fptai": {
        "id": "fptai",
        "name": "FPT AI",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "FPT AI Vietnamese TTS",
    },
    "fishaudio": {
        "id": "fishaudio",
        "name": "Fish Audio",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Fish Audio multi-lingual TTS",
    },
    "deepgram": {
        "id": "deepgram",
        "name": "Deepgram",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Deepgram Speech-to-Text & TTS",
    },
    "elevenlabs": {
        "id": "elevenlabs",
        "name": "ElevenLabs",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "ElevenLabs Voice AI",
    },
    "cartesia": {
        "id": "cartesia",
        "name": "Cartesia",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Cartesia Sonic realtime TTS",
    },
    "playht": {
        "id": "playht",
        "name": "PlayHT",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "PlayHT Voice Generation",
    },
    "inworld": {
        "id": "inworld",
        "name": "Inworld",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Inworld Character TTS",
    },
    "minimax": {
        "id": "minimax",
        "name": "Minimax",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Minimax TTS & LLM",
    },
    "hyperbolic": {
        "id": "hyperbolic",
        "name": "Hyperbolic",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "Hyperbolic Melo TTS",
    },
    "assemblyai": {
        "id": "assemblyai",
        "name": "AssemblyAI",
        "category": "speech",
        "auth_type": "api_key",
        "desc": "AssemblyAI Speech-to-Text",
    },
    # Web Search & Data Retrieval
    "perplexity": {
        "id": "perplexity",
        "name": "Perplexity",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Perplexity Web Search",
    },
    "tavily": {
        "id": "tavily",
        "name": "Tavily",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Tavily Search API",
    },
    "brave-search": {
        "id": "brave-search",
        "name": "Brave Search",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Brave Web Search API",
    },
    "serper": {
        "id": "serper",
        "name": "Serper",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Google Search Serper API",
    },
    "exa": {
        "id": "exa",
        "name": "Exa",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Exa Neural Search",
    },
    "google-pse": {
        "id": "google-pse",
        "name": "Google PSE",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Google Programmable Search Engine",
    },
    "linkup": {
        "id": "linkup",
        "name": "Linkup",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Linkup Search API",
    },
    "searchapi": {
        "id": "searchapi",
        "name": "SearchAPI",
        "category": "search",
        "auth_type": "api_key",
        "desc": "SearchAPI Indexer",
    },
    "youcom": {
        "id": "youcom",
        "name": "You.com Search",
        "category": "search",
        "auth_type": "api_key",
        "desc": "You.com Web Search API",
    },
    "firecrawl": {
        "id": "firecrawl",
        "name": "Firecrawl",
        "category": "search",
        "auth_type": "api_key",
        "desc": "Firecrawl Web Scrape & Search",
    },
}


def get_db_connection() -> Optional[sqlite3.Connection]:
    """Get connection to SQLite providers.db with Row factory."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def get_provider_display_name(provider_id: str) -> str:
    """Return clean human-readable name without emojis."""
    p_id = (provider_id or "").strip().lower()
    if p_id in PROVIDERS_CATALOG:
        return PROVIDERS_CATALOG[p_id]["name"]
    return p_id.title() if p_id else "Others"


def get_active_provider_names() -> Set[str]:
    """Return lowercase IDs of all providers having at least one active connection."""
    active = set()
    conn = get_db_connection()
    if not conn:
        return active
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT provider FROM provider_connections
            WHERE enabled = 1
              AND (
                (api_key IS NOT NULL AND TRIM(api_key) != '')
                OR (refresh_token IS NOT NULL AND TRIM(refresh_token) != '')
              )
        """)
        for row in cur.fetchall():
            if row[0]:
                active.add(row[0].strip().lower())
    except Exception:
        pass
    finally:
        conn.close()
    return active


def get_active_provider_connections(provider: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return active connection dictionaries from SQLite."""
    results = []
    conn = get_db_connection()
    if not conn:
        return results
    try:
        cur = conn.cursor()
        if provider:
            cur.execute("""
                SELECT * FROM provider_connections
                WHERE provider = ? AND enabled = 1
                  AND (
                    (api_key IS NOT NULL AND TRIM(api_key) != '')
                    OR (refresh_token IS NOT NULL AND TRIM(refresh_token) != '')
                  )
                ORDER BY rowid ASC
            """, (provider.strip().lower(),))
        else:
            cur.execute("""
                SELECT * FROM provider_connections
                WHERE enabled = 1
                  AND (
                    (api_key IS NOT NULL AND TRIM(api_key) != '')
                    OR (refresh_token IS NOT NULL AND TRIM(refresh_token) != '')
                  )
                ORDER BY provider ASC, rowid ASC
            """)
        for row in cur.fetchall():
            results.append(dict(row))
    except Exception:
        pass
    finally:
        conn.close()
    return results


def get_active_provider_connection(provider: str) -> Optional[Dict[str, Any]]:
    """Get the primary active connection for a specific provider."""
    conns = get_active_provider_connections(provider)
    return conns[0] if conns else None


def get_available_models(
    category: Optional[str] = "llm",
    active_only: bool = True
) -> List[Dict[str, Any]]:
    """
    Query available models from provider_models table.
    If active_only=True, restricts strictly to models of currently active providers.
    Output items contain:
      id, name, owned_by, provider_name, type
    """
    items = []
    seen = set()
    active_providers = get_active_provider_names() if active_only else None

    # Load from provider_models
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            if category:
                cur.execute("""
                    SELECT model_id, provider, name, type, enabled
                    FROM provider_models
                    WHERE enabled = 1 AND type = ?
                    ORDER BY sort_order ASC, rowid ASC
                """, (category,))
            else:
                cur.execute("""
                    SELECT model_id, provider, name, type, enabled
                    FROM provider_models
                    WHERE enabled = 1
                    ORDER BY sort_order ASC, rowid ASC
                """)
            rows = cur.fetchall()
            for r in rows:
                p = (r["provider"] or "").strip().lower()
                mid = r["model_id"]
                if active_only and p not in active_providers:
                    continue
                if mid and mid not in seen:
                    seen.add(mid)
                    items.append({
                        "id": mid,
                        "name": r["name"] or mid,
                        "owned_by": p,
                        "provider_name": get_provider_display_name(p),
                        "type": r["type"] or "llm",
                    })
        except Exception:
            pass
        finally:
            conn.close()

    # Built-in Antigravity models safeguard if enabled in connections
    if not items and (not active_only or "antigravity" in active_providers):
        default_ag_models = [
            ("gemini-3.7-flash", "Gemini 3.7 Flash"),
            ("gemini-3.6-flash", "Gemini 3.6 Flash (High)"),
            ("gemini-3.8-flash-high", "Gemini 3.8 Flash (High)"),
            ("gemini-3.6-flash-medium", "Gemini 3.6 Flash (Medium)"),
            ("gemini-3.5-flash-medium", "Gemini 3.5 Flash (Medium)"),
            ("gemini-3-flash-agent", "Gemini 3.5 Flash (High)"),
            ("gemini-pro-agent", "Gemini 3.1 Pro (High)"),
            ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)"),
            ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)"),
            ("gpt-oss-120b-medium", "GPT-OSS 120B (Medium)"),
        ]
        for mid, mname in default_ag_models:
            if mid not in seen:
                seen.add(mid)
                items.append({
                    "id": mid,
                    "name": mname,
                    "owned_by": "antigravity",
                    "provider_name": "Antigravity",
                    "type": "llm",
                })

    return items


def get_default_model(available_models: Optional[List[Dict[str, Any]]] = None) -> str:
    """Determine the optimal default model from available active models."""
    models = available_models if available_models is not None else get_available_models("llm")
    if not models:
        return "gemini-3.8-flash-high"
    
    # Priority: gemini-3.8-flash-high -> gemini-3.7-flash -> first available
    for it in models:
        if "gemini-3.8-flash" in it["id"].lower():
            return it["id"]
    for it in models:
        if "gemini-3.7-flash" in it["id"].lower():
            return it["id"]
    for it in models:
        if "gemini" in it["id"].lower() or "flash" in it["id"].lower():
            return it["id"]
    return models[0]["id"]


def get_ai_system_status() -> Dict[str, Any]:
    """
    Unified health and status descriptor for AI features.
    Reports online: True, status_text: 'onl' if active credentials exist.
    """
    active_names = get_active_provider_names()
    has_active = len(active_names) > 0
    primary_provider = list(active_names)[0] if active_names else None
    
    return {
        "ok": True,
        "online": has_active,
        "status_text": "onl" if has_active else "offline",
        "reachable": has_active,
        "active_providers": [get_provider_display_name(p) for p in active_names],
        "active_provider_ids": list(active_names),
        "primary_provider": get_provider_display_name(primary_provider) if primary_provider else None,
        "total_active_connections": len(get_active_provider_connections()),
    }


def load_models_from_db(provider: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """Load model entries from provider_models table."""
    conn = get_db_connection()
    result: Dict[str, List[Dict[str, Any]]] = {}
    if not conn:
        return result
    try:
        if provider:
            cursor = conn.execute(
                """SELECT model_id, name, type, enabled 
                   FROM provider_models 
                   WHERE provider = ? 
                   ORDER BY sort_order ASC, rowid ASC""",
                (provider.strip().lower(),),
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
    except Exception:
        pass
    finally:
        conn.close()
    return result


def load_providers_from_db() -> Dict[str, Any]:
    """Load provider connections and settings from SQLite."""
    conn = get_db_connection()
    providers: Dict[str, Any] = {}
    if not conn:
        return providers
    try:
        cursor = conn.execute("SELECT provider, strategy FROM provider_settings")
        for row in cursor.fetchall():
            providers[row["provider"]] = {
                "connections": [],
                "strategy": row["strategy"]
            }
            
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
    except Exception:
        pass
    finally:
        conn.close()
    return providers


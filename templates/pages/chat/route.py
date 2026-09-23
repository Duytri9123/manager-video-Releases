"""Chat Bot Blueprint — talks to 9Router (https://9router.com).

Replicates the wire format used by 9Router's own dashboard:
  • Endpoints live under `/v1/...` (rewritten to `/api/v1/...`).
  • Auth is `Authorization: Bearer sk-{machineId}-{keyId}-{crc8}`.
  • API keys are managed at /api/keys, protected either by a dashboard
    cookie OR by a local CLI token derived from the machine ID
    (header: x-9r-cli-token; salt: "9r-cli-auth").

What this blueprint exposes to our SPA:
  GET  /api/chatbot/config       → return endpoint + remembered prefs.
  POST /api/chatbot/config       → persist endpoint / model / params.
  GET  /api/chatbot/status       → probe 9Router (health + requireApiKey).
  GET  /api/chatbot/models       → proxy /v1/models, group by owner.
  GET  /api/chatbot/keys         → list local keys via CLI token.
  POST /api/chatbot/keys         → create a new key (CLI token).
  POST /api/chatbot/auto_setup   → grab/create a key and persist it.
  POST /api/chatbot/chat         → proxy /v1/chat/completions (non-streaming).
  POST /api/chatbot/chat_stream  → proxy /v1/chat/completions (SSE passthrough).
  POST /api/chatbot/test         → quick "PONG" round trip.

The Flask side never logs the raw key — only its masked form.
"""
from __future__ import annotations

import base64
import hashlib
import json
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

from core_app import LOGGER, ROOT, load_cfg, save_cfg
from core.ai_models_manager import (
    PROVIDERS_CATALOG,
    get_provider_display_name,
    get_active_provider_names,
    get_active_provider_connections,
    get_active_provider_connection,
    get_available_models,
    get_default_model,
    get_ai_system_status,
)
from core.direct_ai_provider import (
    dispatch_chat_completion,
    antigravity_generate_content,
    ProviderError,
)

_get_active_provider_connection = get_active_provider_connection

bp = Blueprint("chatbot", __name__)

_IMAGE_DIR = ROOT / "Downloaded" / "ai_images"

# ── Defaults pinned to 9Router conventions ─────────────────────────────────
_DEFAULT_ENDPOINT = "http://localhost:20128/v1"
_DEFAULT_MODEL = "cx/gpt-5.5"  # User-preferred default — works for chat, vision, and web
_CLI_TOKEN_HEADER = "x-9r-cli-token"
_CLI_TOKEN_SALT = "9r-cli-auth"
_MACHINE_ID_SALT_DEFAULT = "endpoint-proxy-salt"

_LIGHT_TIMEOUT = 2     # /api/health, /api/settings, /api/keys
_MODELS_TIMEOUT = 5   # /v1/models can be slow if upstream lookups
_DEFAULT_TIMEOUT = 120 # /v1/chat/completions

# ── Direct provider fallback when 9Router is offline ──────────────────────
# Each entry: (name, endpoint, model, config_key_path)
# config_key_path is a dot-separated path into config.yml to find the API key.
_FALLBACK_PROVIDERS = [
    {
        "name": "deepseek",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "key_path": "translation.deepseek_key",
    },
    {
        "name": "gemini",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-2.5-flash",
        "key_path": "gemini_video.api_key",
    },
    {
        "name": "openai",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "key_path": "transcript.api_key",
    },
    {
        "name": "groq",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-3.1-8b-instant",
        "key_path": "translation.groq_key",
    },
]


def _get_cfg_key(cfg: dict, dot_path: str) -> str:
    """Resolve a dot-separated path like 'translation.deepseek_key' from config."""
    parts = dot_path.split(".")
    node = cfg
    for p in parts:
        if not isinstance(node, dict):
            return ""
        node = node.get(p)
    return (node or "").strip() if isinstance(node, str) else ""


def _pick_fallback_provider(cfg: dict, model_hint: str = "") -> Optional[Dict[str, str]]:
    """Return the best fallback provider that has a valid API key configured.

    If `model_hint` matches a known provider's model, prefer that provider.
    Otherwise return the first provider with a valid key.
    """
    # If user explicitly picked a model that belongs to a known provider, use it.
    if model_hint:
        hint_lower = model_hint.lower()
        for prov in _FALLBACK_PROVIDERS:
            if (prov["model"].lower() == hint_lower
                    or prov["name"] in hint_lower
                    or hint_lower.startswith(prov["name"])):
                key = _get_cfg_key(cfg, prov["key_path"])
                if key:
                    # Use the user's requested model name (they might want a
                    # specific variant like gemini-2.5-pro instead of flash).
                    return {"name": prov["name"], "endpoint": prov["endpoint"],
                            "model": model_hint, "api_key": key}
    # Default: first provider with a key.
    for prov in _FALLBACK_PROVIDERS:
        key = _get_cfg_key(cfg, prov["key_path"])
        if key:
            return {"name": prov["name"], "endpoint": prov["endpoint"],
                    "model": prov["model"], "api_key": key}
    return None



def _chat_with_antigravity(conn_dict: dict, model_name: str, messages: list, timeout: int = 60) -> str:
    from core.direct_ai_provider import antigravity_generate_content, google_generate_content
    contents = []
    system_instruction = None
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        if isinstance(text, list):
            parts = []
            for p in text:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append({"text": p.get("text", "")})
            parts = parts or [{"text": ""}]
        else:
            parts = [{"text": str(text or "")}]
        
        if role == "system":
            system_instruction = {"parts": parts}
        else:
            g_role = "model" if role == "assistant" else "user"
            contents.append({"role": g_role, "parts": parts})
            
    body = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = system_instruction
        
    api_key = str(conn_dict.get("api_key") or "").strip()
    if api_key.startswith("AIza"):
        resp = google_generate_content(api_key, model_name, body, base_url=conn_dict.get("base_url") or "https://generativelanguage.googleapis.com", timeout=timeout)
    else:
        resp, _ = antigravity_generate_content(conn_dict, model_name, body, timeout=timeout)
        
    reply_text = ""
    try:
        candidates = resp.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            reply_text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except Exception:
        pass
    return reply_text or "Không nhận được phản hồi từ Antigravity"


def _is_9router_reachable(endpoint: str) -> bool:
    """Disabled: closed system using internal Direct AI Provider."""
    return False


# Cache reachability for 15 seconds.
_reachable_cache: Dict[str, Any] = {"ok": False, "ts": 0.0}


def _nine_router_reachable(endpoint: str) -> bool:
    return False

# ── Local DB cache for the CLI token so we don't shell out every request ──
_cli_token_cache: Optional[str] = None


# ─── Machine ID helpers (mirror node-machine-id used by 9Router) ──────────
def _read_windows_machine_guid() -> Optional[str]:
    """Return the lowercase MachineGuid from HKLM\\SOFTWARE\\Microsoft\\Cryptography."""
    # 1. Try winreg (native Win32 API, no subprocess, works on 32-bit / 64-bit redirection)
    try:
        import winreg
        # Try 64-bit registry view first, then default
        for access in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
                    guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                    if guid:
                        return guid.strip().lower()
            except Exception:
                continue
    except Exception:
        pass

    # 2. Fallback to reg query
    try:
        out = subprocess.check_output(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            text=True, stderr=subprocess.DEVNULL, timeout=4,
        )
        for line in out.splitlines():
            if "MachineGuid" in line:
                parts = line.strip().split()
                if parts:
                    return parts[-1].strip().lower()
    except Exception:
        pass

    # 3. Fallback to PowerShell
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", "(Get-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography').MachineGuid"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        guid = out.strip()
        if guid:
            return guid.lower()
    except Exception:
        pass

    return None


def _read_linux_machine_id() -> Optional[str]:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip().lower()
                if v:
                    return v
        except Exception:
            continue
    return None


def _read_mac_machine_id() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True, stderr=subprocess.DEVNULL, timeout=4,
        )
    except Exception:
        return None
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return m.group(1).lower() if m else None


def _raw_machine_id() -> Optional[str]:
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        return _read_windows_machine_guid()
    if sysname == "darwin":
        return _read_mac_machine_id()
    return _read_linux_machine_id()


def _hash_with_salt(value: str, salt: str, length: int = 16) -> str:
    return hashlib.sha256((value + salt).encode("utf-8")).hexdigest()[:length]


def _consistent_machine_id(salt: str = _MACHINE_ID_SALT_DEFAULT) -> Optional[str]:
    """Same algorithm as 9Router/getConsistentMachineId.

    node-machine-id returns sha256(rawMachineId) (full 64-hex). 9Router then
    sha256(rawMachineId + salt) and slices to 16. We mirror that here.
    """
    raw = _raw_machine_id()
    if not raw:
        return None
    return _hash_with_salt(raw, salt, 16)


def _cli_token() -> Optional[str]:
    """Token used by 9Router CLI to bypass dashboardGuard on localhost.

    9Router code:
      const rawMachineId = machineIdSync();
      const hashed = sha256(rawMachineId + salt);
      return hashed.substring(0, 16);
    With salt="9r-cli-auth". We mirror it.
    """
    global _cli_token_cache
    if _cli_token_cache:
        return _cli_token_cache
    raw = _raw_machine_id()
    if not raw:
        return None
    # Hash twice: first to get rawMachineId of node-machine-id, then with salt.
    inner = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    _cli_token_cache = _hash_with_salt(inner, _CLI_TOKEN_SALT, 16)
    return _cli_token_cache


# ─── Helpers ──────────────────────────────────────────────────────────────
def _mask_key(key: str) -> str:
    if not key or len(key) < 12:
        return "***"
    return key[:6] + "…" + key[-4:]


def _nine_router_cfg() -> Dict[str, Any]:
    cfg = load_cfg()
    nr = dict(cfg.get("nine_router") or {})
    nr.setdefault("endpoint", "Direct AI")
    nr.setdefault("api_key", "")
    nr.setdefault("default_model", get_default_model() or _DEFAULT_MODEL)
    nr.setdefault("system_prompt", "")
    nr.setdefault("temperature", 0.7)
    nr.setdefault("max_tokens", 4096)
    return nr


def _normalize_endpoint(raw: str) -> str:
    """Trim trailing slashes; accept users typing the bare host."""
    base = (raw or "").strip().rstrip("/")
    return base or "Direct AI"


def _base_origin(endpoint: str) -> str:
    """Sanitize base without external 9Router origin connection."""
    base = (endpoint or "").rstrip("/")
    return re.sub(r"/v1$", "", base)


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Dict[str, str] | None = None,
    payload: Dict[str, Any] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            try:
                return resp.status, json.loads(body) if body else {}
            except ValueError:
                return resp.status, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        try:
            return exc.code, json.loads(body) if body else {}
        except ValueError:
            return exc.code, body.decode("utf-8", "replace")


def _local_dashboard_get(path: str, *, endpoint: str, timeout: int = _LIGHT_TIMEOUT) -> Tuple[int, Any]:
    """Stub: Direct AI closed system does not connect to 9Router dashboard."""
    return 200, {"keys": []}


def _local_dashboard_post(
    path: str,
    payload: Dict[str, Any],
    *,
    endpoint: str,
    timeout: int = _LIGHT_TIMEOUT,
) -> Tuple[int, Any]:
    """Stub: Direct AI closed system does not connect to 9Router dashboard."""
    return 200, {"ok": True}


# ─── Config endpoints ─────────────────────────────────────────────────────
@bp.route("/api/chatbot/config", methods=["GET"])
def chatbot_get_config():
    nr = _nine_router_cfg()
    masked = _mask_key(nr.get("api_key") or "") if nr.get("api_key") else ""
    return jsonify({
        "ok": True,
        "endpoint": nr["endpoint"],
        "default_model": nr["default_model"],
        "system_prompt": nr["system_prompt"],
        "temperature": float(nr.get("temperature", 0.7)),
        "max_tokens": int(nr.get("max_tokens", 4096)),
        "has_key": bool((nr.get("api_key") or "").strip()),
        "api_key": nr.get("api_key") or "",
        "masked_key": masked,
    })


@bp.route("/api/chatbot/config", methods=["POST"])
def chatbot_set_config():
    data = request.json or {}
    cfg = load_cfg()
    nr = dict(cfg.get("nine_router") or {})
    # Hydrate with defaults so a partial save (e.g. only max_tokens) doesn't
    # drop fields that already had values implicitly via the defaults.
    nr.setdefault("endpoint", _DEFAULT_ENDPOINT)
    nr.setdefault("api_key", "")
    nr.setdefault("default_model", _DEFAULT_MODEL)
    nr.setdefault("system_prompt", "")
    nr.setdefault("temperature", 0.7)
    nr.setdefault("max_tokens", 4096)

    if "endpoint" in data:
        nr["endpoint"] = _normalize_endpoint(str(data.get("endpoint") or ""))
    if "api_key" in data:
        new_key = str(data.get("api_key") or "").strip()
        if new_key:
            nr["api_key"] = new_key
        elif data.get("clear_key") is True:
            nr["api_key"] = ""
    if "default_model" in data:
        nr["default_model"] = str(data.get("default_model") or _DEFAULT_MODEL).strip()
    if "system_prompt" in data:
        nr["system_prompt"] = str(data.get("system_prompt") or "")
    if "temperature" in data:
        try:
            nr["temperature"] = max(0.0, min(2.0, float(data.get("temperature") or 0.7)))
        except (TypeError, ValueError):
            nr["temperature"] = 0.7
    if "max_tokens" in data:
        try:
            nr["max_tokens"] = max(16, min(32_000, int(data.get("max_tokens") or 4096)))
        except (TypeError, ValueError):
            nr["max_tokens"] = 4096

    cfg["nine_router"] = nr
    save_cfg(cfg)
    clear_status_cache()
    return jsonify({
        "ok": True,
        "endpoint": nr["endpoint"],
        "default_model": nr["default_model"],
        "has_key": bool((nr.get("api_key") or "").strip()),
        "masked_key": _mask_key(nr.get("api_key") or "") if nr.get("api_key") else "",
    })


_STATUS_CACHE = None
_STATUS_CACHE_TIME = 0.0

def clear_status_cache():
    global _STATUS_CACHE
    _STATUS_CACHE = None
    try:
        from core.tts_catalog import clear_tts_catalog_cache
        clear_tts_catalog_cache()
    except Exception:
        pass


# ─── Status / discovery ───────────────────────────────────────────────────
@bp.route("/api/chatbot/status", methods=["GET"])
def chatbot_status():
    """Tell the UI whether AI providers are up and active.
    Direct closed-system AI without 9Router or MITM.
    """
    global _STATUS_CACHE, _STATUS_CACHE_TIME
    now = time.time()
    
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    if not force and _STATUS_CACHE and (now - _STATUS_CACHE_TIME) < 3.0:
        return jsonify(_STATUS_CACHE)

    status_info = get_ai_system_status()
    is_online = status_info["online"]
    antigravity_conn = get_active_provider_connection("antigravity")

    res_payload = {
        "ok": True,
        "endpoint": "Direct AI System",
        "reachable": is_online,
        "online": is_online,
        "status_text": "onl" if is_online else "offline",
        "active_providers": status_info["active_providers"],
        "active_provider_ids": status_info["active_provider_ids"],
        "active_provider_available": is_online,
        "version": "Direct AI Provider",
        "require_api_key": False,
        "settings_ok": True,
        "settings": {},
        "has_key": is_online,
        "masked_key": (antigravity_conn.get("email") or "antigravity_active") if antigravity_conn else "",
        "key_valid": is_online,
        "key_error": None,
        "has_cli_token": False,
        "fallback_available": is_online,
        "fallback_provider": status_info["primary_provider"] or "Antigravity",
    }
    _STATUS_CACHE = res_payload
    _STATUS_CACHE_TIME = now
    return jsonify(res_payload)



@bp.route("/api/chatbot/start_9router", methods=["POST"])
def chatbot_start_9router():
    return jsonify({
        "ok": True,
        "message": "Hệ thống đang hoạt động ở chế độ AI trực tiếp khép kín, không cần 9Router."
    })


@bp.route("/api/chatbot/settings", methods=["POST"])
def chatbot_update_settings():
    return jsonify({
        "ok": True,
        "settings": {
            "rtk_enabled": False,
            "caveman_enabled": False,
            "caveman_level": "full"
        }
    })


@bp.route("/api/chatbot/keys", methods=["GET"])
def chatbot_list_keys():
    return jsonify({"ok": True, "count": 0, "keys": []})


@bp.route("/api/chatbot/keys", methods=["POST"])
def chatbot_create_key():
    return jsonify({
        "ok": True,
        "id": "direct_ai",
        "name": "Direct AI Provider",
        "key": "direct",
        "masked": "direct"
    })


@bp.route("/api/chatbot/auto_setup", methods=["POST"])
def chatbot_auto_setup():
    return jsonify({
        "ok": True,
        "id": "direct_ai",
        "name": "Direct AI Provider",
        "masked": "direct",
        "created": False
    })


@bp.route("/api/chatbot/routing", methods=["GET"])
def chatbot_get_routing():
    nr = _nine_router_cfg()
    routing = nr.get("routing") or {}
    return jsonify({
        "ok": True,
        "mode": routing.get("mode", "auto"),
        "tiers": routing.get("tiers") or {},
        "thresholds": routing.get("thresholds") or {},
    })


@bp.route("/api/chatbot/routing", methods=["POST"])
def chatbot_set_routing():
    """Persist routing prefs to config.yml under nine_router.routing."""
    data = request.json or {}
    cfg = load_cfg()
    nr = dict(cfg.get("nine_router") or {})
    nr.setdefault("endpoint", _DEFAULT_ENDPOINT)
    nr.setdefault("api_key", "")
    nr.setdefault("default_model", _DEFAULT_MODEL)

    routing = dict(nr.get("routing") or {})
    if "mode" in data:
        m = str(data.get("mode") or "auto").lower()
        routing["mode"] = "manual" if m == "manual" else "auto"
    if "tiers" in data and isinstance(data["tiers"], dict):
        tiers = dict(routing.get("tiers") or {})
        for tk in ("fast", "balanced", "power"):
            if tk in data["tiers"]:
                tiers[tk] = str(data["tiers"][tk] or "").strip()
        routing["tiers"] = tiers
    if "thresholds" in data and isinstance(data["thresholds"], dict):
        th = dict(routing.get("thresholds") or {})
        try:
            if "fast_max_chars" in data["thresholds"]:
                th["fast_max_chars"] = max(10, min(2000, int(data["thresholds"]["fast_max_chars"])))
            if "power_min_chars" in data["thresholds"]:
                th["power_min_chars"] = max(100, min(20000, int(data["thresholds"]["power_min_chars"])))
            if "history_balanced_after" in data["thresholds"]:
                th["history_balanced_after"] = max(1, min(50, int(data["thresholds"]["history_balanced_after"])))
        except (TypeError, ValueError):
            pass
        routing["thresholds"] = th

    nr["routing"] = routing
    cfg["nine_router"] = nr
    save_cfg(cfg)
    return jsonify({"ok": True, "mode": routing.get("mode"), "tiers": routing.get("tiers"), "thresholds": routing.get("thresholds")})


@bp.route("/api/chatbot/route_preview", methods=["POST"])
def chatbot_route_preview():
    """Tell the UI which model `messages` would be routed to — without
    actually firing the upstream call. Useful for the preview badge."""
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]
    nr = _nine_router_cfg()
    model, route = _resolve_routed_model(data, nr)
    return jsonify({"ok": True, "model": model, "routing": route})


@bp.route("/api/chatbot/upload_image", methods=["POST"])
def chatbot_upload_image():
    """Accept an image upload and return a `data:` URL the chat UI can attach
    to a vision-capable message. We don't persist anything — the data URL is
    embedded in the chat history client-side and replayed on each turn.

    OpenAI / 9Router chat completions accept `image_url` content parts where
    `url` may be an `http(s)://...` link OR a `data:image/...;base64,...`
    blob. The latter is convenient for local files without exposing them.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "file required"}), 400
    f = request.files["file"]
    raw = f.stream.read()
    if not raw:
        return jsonify({"ok": False, "error": "empty file"}), 400
    # Cap at 8 MB to avoid blowing up the LLM context.
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"ok": False, "error": "file too big",
                        "message": "Ảnh > 8MB. Resize trước khi upload."}), 413
    mime = (f.mimetype or "").lower()
    if not mime.startswith("image/"):
        return jsonify({"ok": False, "error": "not an image",
                        "message": f"mime={mime!r} — chỉ chấp nhận image/*"}), 400
    import base64 as _b64
    data_url = f"data:{mime};base64,{_b64.b64encode(raw).decode('ascii')}"
    return jsonify({
        "ok": True,
        "data_url": data_url,
        "size": len(raw),
        "mime": mime,
        "filename": f.filename,
    })


# ─── Multi-modal endpoints (image / TTS / STT / embeddings) ────────────────
_KIND_TO_PATH = {
    "image": "/models/image",
    "tts": "/models/tts",
    "stt": "/models/stt",
    "embedding": "/models/embedding",
    "image-to-text": "/models/image-to-text",
    "web": "/models/web",
}


@bp.route("/api/chatbot/media_models", methods=["GET"])
def chatbot_media_models():
    """Return models for the specified kind from local providers database."""
    kind = (request.args.get("kind") or "").strip().lower()
    sub = _KIND_TO_PATH.get(kind)
    if not sub:
        return jsonify({"ok": False, "error": "unknown_kind",
                        "supported": list(_KIND_TO_PATH.keys())}), 400

    items = []
    try:
        from templates.pages.config.route import load_models_from_db
        all_db = load_models_from_db()
        seen = set()
        if kind in ("stt", "audio-to-text"):
            for p in ["antigravity", "deepgram", "assemblyai", "groq", "openai"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        items.append({"id": m.get("id"), "owned_by": p, "name": m.get("name") or m.get("id")})
        elif kind in ("vision", "image-to-text", "video"):
            for p in ["antigravity"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        items.append({"id": m.get("id"), "owned_by": p, "name": m.get("name") or m.get("id")})
        elif kind in ("image", "image-generation"):
            for p in ["antigravity", "codex", "openai"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("type") == "image" and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        items.append({"id": m.get("id"), "owned_by": p, "name": m.get("name") or m.get("id")})
            if not items:
                items.append({
                    "id": "gemini-3.1-flash-image",
                    "owned_by": "antigravity",
                    "name": "Gemini 3.1 Flash (Image)"
                })
        else:
            for p in ["antigravity", "codex", "openai", "deepseek"]:
                for m in all_db.get(p, []):
                    if m.get("enabled") and m.get("id") and m.get("id") not in seen:
                        seen.add(m.get("id"))
                        items.append({"id": m.get("id"), "owned_by": p, "name": m.get("name") or m.get("id")})
    except Exception as exc:
        LOGGER.warning("chatbot_media_models error: %s", exc)

    return jsonify({"ok": True, "kind": kind, "models": items})


@bp.route("/api/chatbot/image/download/<filename>", methods=["GET"])
def chatbot_image_download(filename: str):
    safe = "".join(c for c in filename if c.isalnum() or c in "_-.")
    fp = _IMAGE_DIR / safe
    if not fp.exists():
        return jsonify({"ok": False, "error": "Not found"}), 404
    mime = "image/png" if fp.suffix.lower() == ".png" else "image/jpeg"
    return send_file(fp, mimetype=mime)


@bp.route("/api/chatbot/image", methods=["POST"])
def chatbot_image():
    """Generate an image via Antigravity, OpenAI DALL-E, Gemini Imagen, or 9Router."""
    data = request.json or {}
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt required"}), 400

    nr = _nine_router_cfg()
    endpoint = (nr.get("endpoint") or "").strip()
    api_key = (nr.get("api_key") or "").strip()

    model = (data.get("model") or "").strip() or "gemini-3.1-flash-image"
    n_count = max(1, min(int(data.get("n") or 1), 4))
    size = str(data.get("size") or "1024x1024").strip()

    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Forward to 9Router ONLY IF endpoint is an actual HTTP/HTTPS URL
    if endpoint.startswith(("http://", "https://")):
        try:
            import requests as _requests
            payload: Dict[str, Any] = {
                "prompt": prompt,
                "model": model,
                "n": n_count,
                "size": size,
                "quality": str(data.get("quality") or "auto"),
                "background": str(data.get("background") or "auto"),
                "output_format": str(data.get("output_format") or "png"),
            }
            if data.get("style"):
                payload["style"] = str(data["style"])
            if not model.startswith("cx/"):
                payload["response_format"] = data.get("response_format") or "b64_json"
                payload.pop("output_format", None)
                payload.pop("background", None)

            url = f"{endpoint.rstrip('/')}/images/generations"
            req_headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
            if api_key:
                req_headers["Authorization"] = f"Bearer {api_key}"

            upstream = _requests.post(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=req_headers,
                stream=True,
                timeout=(10, 300),
            )
            if upstream.status_code >= 400:
                try:
                    err_json = upstream.json()
                    msg = (err_json.get("error") or {}).get("message") or upstream.text
                except Exception:
                    msg = upstream.text or f"HTTP {upstream.status_code}"
                upstream.close()
                return jsonify({"ok": False, "status": upstream.status_code, "error": msg}), 502

            content_type = (upstream.headers.get("Content-Type") or "").lower()
            is_sse = "text/event-stream" in content_type
            if not is_sse:
                try:
                    body = upstream.json()
                except Exception:
                    body = {}
                upstream.close()
                if isinstance(body, dict):
                    items = body.get("data") or []
                    return jsonify({
                        "ok": True,
                        "model": model,
                        "images": items,
                        "raw": {"created": body.get("created"), "model": body.get("model")},
                    })
            else:
                images = []
                try:
                    buf = ""
                    for chunk in upstream.iter_content(chunk_size=None, decode_unicode=True):
                        if not chunk:
                            continue
                        buf += chunk
                    events = buf.split("\n\n")
                    for ev in events:
                        lines = ev.strip().split("\n")
                        event_name = ""
                        data_parts = []
                        for line in lines:
                            if line.startswith("event:"):
                                event_name = line[6:].strip()
                            elif line.startswith("data:"):
                                data_parts.append(line[5:].strip())
                        if not data_parts:
                            continue
                        data_str = "\n".join(data_parts)
                        if event_name == "partial_image" or (not event_name and '"b64_json"' in data_str):
                            try:
                                img_data = json.loads(data_str)
                                if img_data.get("b64_json"):
                                    images.append({"b64_json": img_data["b64_json"]})
                            except Exception:
                                pass
                        elif event_name == "result" or (not event_name and '"data"' in data_str):
                            try:
                                result_data = json.loads(data_str)
                                for item in (result_data.get("data") or []):
                                    if isinstance(item, dict) and (item.get("b64_json") or item.get("url")):
                                        images.append(item)
                            except Exception:
                                pass
                except Exception as exc:
                    LOGGER.warning("chatbot_image SSE parse error: %s", exc)
                finally:
                    upstream.close()

                if images:
                    return jsonify({
                        "ok": True,
                        "model": model,
                        "images": images,
                        "raw": {"model": model},
                    })
        except Exception as exc:
            LOGGER.warning("9Router call failed: %s, falling back to direct AI", exc)

    # 2. Direct AI Provider:
    # A) Antigravity connection (Default)
    antigravity_conn = _get_active_provider_connection("antigravity")
    is_gemini_or_default = (
        any(k in model.lower() for k in ("gemini", "flash", "antigravity", "imagen", "cx/"))
        or not endpoint.startswith(("http://", "https://"))
    )

    if antigravity_conn and is_gemini_or_default:
        aspect_map = {
            "1792x1024": "16:9 widescreen",
            "1024x1792": "9:16 portrait vertical",
            "1024x1024": "1:1 square",
            "512x512": "1:1 square",
        }
        aspect_desc = aspect_map.get(size, "")
        enhanced_prompt = f"{prompt}, aspect ratio {aspect_desc}" if aspect_desc else prompt

        images = []
        last_error = None
        for i in range(n_count):
            try:
                resp, _ = antigravity_generate_content(
                    antigravity_conn,
                    "gemini-3.1-flash-image",
                    {
                        "contents": [{"parts": [{"text": enhanced_prompt}]}],
                        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
                    },
                    timeout=90
                )
                candidates = resp.get("candidates") or []
                if not candidates:
                    raise ProviderError("Antigravity không trả về nội dung ảnh")
                parts = candidates[0].get("content", {}).get("parts", [])
                img_found = False
                for p in parts:
                    if "inlineData" in p:
                        b64_data = p["inlineData"].get("data")
                        mime_type = p["inlineData"].get("mimeType", "image/jpeg")
                        ext = "png" if "png" in mime_type else "jpg"
                        filename = f"chat_ai_{uuid.uuid4().hex[:10]}_{i+1}.{ext}"
                        filepath = _IMAGE_DIR / filename
                        with open(filepath, "wb") as f:
                            f.write(base64.b64decode(b64_data))

                        images.append({
                            "b64_json": b64_data,
                            "url": f"/api/chatbot/image/download/{filename}",
                            "filename": filename
                        })
                        img_found = True
                        break
                if not img_found:
                    text_parts = [p.get("text", "") for p in parts if "text" in p]
                    explanation = " ".join(text_parts).strip()
                    if explanation:
                        raise ProviderError(explanation)
            except Exception as exc:
                LOGGER.warning("Antigravity image gen error: %s", exc)
                last_error = exc
                if not images:
                    break

        if images:
            return jsonify({
                "ok": True,
                "model": "gemini-3.1-flash-image",
                "images": images,
                "raw": {"model": "gemini-3.1-flash-image"}
            })
        elif last_error:
            return jsonify({"ok": False, "error": f"Lỗi tạo ảnh Antigravity: {last_error}"}), 502

    # B) OpenAI DALL-E fallback
    cfg = load_cfg()
    tr = cfg.get("translation") or {}
    openai_key = (tr.get("openai_key") or "").strip()
    if openai_key or "dall-e" in model.lower():
        try:
            dalle_size = size if size in ("1024x1024", "1792x1024", "1024x1792") else "1024x1024"
            dalle_payload = {
                "model": "dall-e-3",
                "prompt": prompt,
                "n": 1,
                "size": dalle_size,
                "response_format": "b64_json"
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/images/generations",
                data=json.dumps(dalle_payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                dalle_data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            images = []
            for idx, item in enumerate(dalle_data.get("data") or []):
                b64 = item.get("b64_json")
                if b64:
                    filename = f"dalle_{uuid.uuid4().hex[:10]}_{idx+1}.png"
                    filepath = _IMAGE_DIR / filename
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(b64))
                    images.append({
                        "b64_json": b64,
                        "url": f"/api/chatbot/image/download/{filename}",
                        "filename": filename
                    })
            if images:
                return jsonify({
                    "ok": True,
                    "model": "dall-e-3",
                    "images": images,
                    "raw": {"model": "dall-e-3"}
                })
        except Exception as exc:
            LOGGER.warning("OpenAI DALL-E fallback error: %s", exc)

    # C) Gemini Imagen API Key fallback
    gemini_key = (cfg.get("gemini_video") or {}).get("api_key", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            aspect = "1:1"
            if size == "1792x1024":
                aspect = "16:9"
            elif size == "1024x1792":
                aspect = "9:16"
            imagen_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={gemini_key}"
            imagen_payload = {
                "prompt": prompt,
                "config": {
                    "numberOfImages": n_count,
                    "aspectRatio": aspect,
                    "outputOptions": {"mimeType": "image/jpeg"}
                }
            }
            req = urllib.request.Request(
                imagen_url,
                data=json.dumps(imagen_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                imagen_data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            images = []
            for idx, item in enumerate(imagen_data.get("generatedImages") or []):
                img_bytes_b64 = (item.get("image") or {}).get("imageBytes") or ""
                if img_bytes_b64:
                    filename = f"imagen_{uuid.uuid4().hex[:10]}_{idx+1}.jpg"
                    filepath = _IMAGE_DIR / filename
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(img_bytes_b64))
                    images.append({
                        "b64_json": img_bytes_b64,
                        "url": f"/api/chatbot/image/download/{filename}",
                        "filename": filename
                    })
            if images:
                return jsonify({
                    "ok": True,
                    "model": "imagen-3.0-generate-002",
                    "images": images,
                    "raw": {"model": "imagen-3.0-generate-002"}
                })
        except Exception as exc:
            LOGGER.warning("Gemini Imagen fallback error: %s", exc)

    return jsonify({
        "ok": False,
        "error": "Chưa có AI Provider nào hỗ trợ tạo ảnh đang hoạt động. Vui lòng kết nối tài khoản Google trong Cài đặt Provider hoặc cấu hình API Key."
    }), 502


@bp.route("/api/chatbot/tts", methods=["POST"])
def chatbot_tts():
    """Text-to-speech via 9Router /v1/audio/speech. Returns audio bytes
    (audio/mpeg by default) or JSON {audio_base64,format} when ?json=1.

    Body:
      input (str, required)
      model (str, required)             — e.g. "openai/tts-1" or "el/<voice_id>"
      voice (str, optional)             — for OpenAI TTS only
      format (str, optional, "mp3" default)
      language (str, optional)          — Gemini hint
    """
    data = request.json or {}
    text = str(data.get("input") or data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "input required"}), 400

    model = (data.get("model") or "").strip() or "openai/tts-1"
    payload: Dict[str, Any] = {"input": text, "model": model}
    if data.get("voice"):
        payload["voice"] = str(data["voice"])
    if data.get("language"):
        payload["language"] = str(data["language"])

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    endpoint = (nr.get("endpoint") or "").strip()
    if not endpoint.startswith(("http://", "https://")):
        return jsonify({
            "ok": False,
            "error": "TTS endpoint chưa được kết nối qua HTTP. Vui lòng sử dụng tính năng lồng tiếng (TTS) trong trang Xử lý video hoặc cấu hình 9Router."
        }), 400

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    fmt = str(data.get("format") or "mp3").strip().lower() or "mp3"
    from urllib.parse import urlencode as _urlencode
    qs = _urlencode({"response_format": fmt})
    url = f"{endpoint.rstrip('/')}/audio/speech?{qs}"
    try:
        import requests  # type: ignore
        upstream = requests.post(
            url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, timeout=120, stream=False,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502

    if upstream.status_code >= 400:
        try:
            err_json = upstream.json()
            msg = (err_json.get("error") or {}).get("message") or err_json
        except Exception:
            msg = upstream.text or f"HTTP {upstream.status_code}"
        return jsonify({"ok": False, "status": upstream.status_code, "error": msg}), 502

    audio_bytes = upstream.content
    content_type = upstream.headers.get("Content-Type", "audio/mpeg")
    if request.args.get("json") == "1":
        import base64 as _b64
        return jsonify({
            "ok": True, "model": model,
            "format": content_type.split("/")[-1],
            "audio_base64": _b64.b64encode(audio_bytes).decode("ascii"),
        })
    return Response(audio_bytes, mimetype=content_type, headers={
        "Cache-Control": "no-cache",
        "Content-Disposition": "inline; filename=tts.mp3",
    })


@bp.route("/api/chatbot/stt", methods=["POST"])
def chatbot_stt():
    """Speech-to-text via /v1/audio/transcriptions (multipart upload).

    Form fields:
      file (audio file, required)
      model (str, required)
      language (str, optional)
      response_format (str, optional)   — json|text|srt|verbose_json|vtt
      prompt (str, optional)
      temperature (float, optional)
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "file required"}), 400
    f = request.files["file"]
    model = (request.form.get("model") or "").strip() or "openai/whisper-1"

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    endpoint = (nr.get("endpoint") or "").strip()
    if not endpoint.startswith(("http://", "https://")):
        return jsonify({
            "ok": False,
            "error": "STT endpoint chưa được kết nối qua HTTP. Vui lòng sử dụng tính năng trích xuất phụ đề (Whisper) trong trang Xử lý video."
        }), 400

    url = f"{endpoint.rstrip('/')}/audio/transcriptions"

    headers: Dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        import requests  # type: ignore
        files = {"file": (f.filename, f.stream.read(), f.mimetype or "application/octet-stream")}
        forms: Dict[str, str] = {"model": model}
        for key in ("language", "response_format", "prompt", "temperature"):
            v = request.form.get(key)
            if v not in (None, ""):
                forms[key] = v
        upstream = requests.post(url, headers=headers, files=files, data=forms, timeout=300)
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502

    if upstream.status_code >= 400:
        try:
            return jsonify({"ok": False, "status": upstream.status_code,
                            "error": upstream.json()}), 502
        except Exception:
            return jsonify({"ok": False, "status": upstream.status_code,
                            "error": upstream.text}), 502

    ctype = (upstream.headers.get("Content-Type") or "").lower()
    if "json" in ctype:
        return jsonify({"ok": True, "model": model, "result": upstream.json()})
    return jsonify({"ok": True, "model": model, "text": upstream.text})


@bp.route("/api/chatbot/embeddings", methods=["POST"])
def chatbot_embeddings():
    """Vector embeddings via /v1/embeddings.

    Body: { input: str | str[], model: str }
    """
    data = request.json or {}
    inp = data.get("input")
    if not inp:
        return jsonify({"ok": False, "error": "input required"}), 400
    model = (data.get("model") or "").strip() or "openai/text-embedding-3-small"

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    endpoint = (nr.get("endpoint") or "").strip()
    if not endpoint.startswith(("http://", "https://")):
        return jsonify({
            "ok": False,
            "error": "Embeddings endpoint chưa được cấu hình qua HTTP."
        }), 400

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"input": inp, "model": model}
    url = f"{endpoint.rstrip('/')}/embeddings"
    try:
        status, body = _http_json(url, method="POST", headers=headers,
                                  payload=payload, timeout=60)
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if status >= 400:
        return jsonify({"ok": False, "status": status, "error": body}), 502
    return jsonify({"ok": True, "model": model, "result": body})


# ─── Models ───────────────────────────────────────────────────────────────
@bp.route("/api/chatbot/models", methods=["GET"])
def chatbot_models():
    """Return available models strictly from currently active providers via ai_models_manager."""
    items = get_available_models(category="llm", active_only=True)
    default_model = get_default_model(items)
    return jsonify({
        "ok": True,
        "models": items,
        "default": default_model,
        "fallback_active": True
    })


# ─── Chat (non-streaming) ─────────────────────────────────────────────────
def _ensure_messages(data: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return 400, {"ok": False, "error": "messages required"}
    return None


# ─── Smart routing by complexity ──────────────────────────────────────────
# Words that imply the user wants real reasoning (write code, debug, plan).
# Matched case-insensitively, word-bounded.
_POWER_KEYWORDS = (
    # math / reasoning (heavy logic — needs sonnet/gpt-5.5)
    "prove", "derive", "calculate", "equation", "theorem",
    # long-form planning
    "essay", "summary of", "translate this article",
    "kế hoạch chi tiết", "phân tích chi tiết",
    "viết kịch bản", "viết bài dài", "soạn bài",
    # multi-step
    "step by step", "outline detailed",
)
_FAST_KEYWORDS = (
    # greetings / pleasantries — never need a heavy model.
    "hi", "hello", "hey", "yo", "ping", "test",
    "chào", "xin chào", "alo", "hí",
    # one-shot lookups
    "what is", "định nghĩa", "viết tắt",
)
# Code-related signals → prefer a coder-tuned model (qwen3-coder, gpt-5.5-codex…).
_CODE_KEYWORDS = (
    "code", "debug", "refactor", "stack trace", "traceback", "exception",
    "regex", "algorithm", "function", "class", "method", "variable",
    "compile", "syntax error", "merge conflict", "pull request",
    "lập trình", "viết hàm", "viết class", "fix bug", "sửa lỗi code",
    "implement", "snippet",
)
# Realtime / current-info signals → prefer a model with web (cx/gpt-5.5 or
# gemini-pro). These should NOT be answered from a stale text-only model.
_WEB_KEYWORDS = (
    "tin tức", "tin mới", "mới nhất", "hôm nay", "hôm qua",
    "tuần này", "tháng này", "năm nay",
    "giá vàng", "giá bitcoin", "tỷ giá", "thời tiết",
    "lịch", "kết quả", "tỉ số", "lịch thi đấu",
    "news", "latest", "today", "yesterday", "this week", "right now",
    "current", "currently", "recent", "weather", "stock price", "score",
    "tìm trên mạng", "search web", "google", "tra cứu",
)


def _has_image_input(messages: list) -> bool:
    """True if any user turn contains an image_url part — needs a vision model."""
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False


def _classify_complexity(messages: list, thresholds: Dict[str, Any]) -> Tuple[str, str]:
    """Return (tier_name, reason) based on the trailing user turn + history.

    Tiers (first hit wins):
      vision    → user attached an image
      code      → coding-related keywords
      web       → realtime / "what's the latest" queries
      fast      → very short prompt + small history, or greetings
      power     → very long prompt OR power keyword
      balanced  → default mid-range
    """
    # 0. Vision short-circuit — image attachments need a multimodal model
    #    regardless of how short the text part is.
    if _has_image_input(messages):
        return "vision", "có ảnh đính kèm → cần model vision"

    last_user = ""
    user_turns = 0
    for m in messages:
        if m.get("role") == "user":
            user_turns += 1
            content = m.get("content")
            if isinstance(content, str):
                last_user = content
            elif isinstance(content, list):
                # Multipart content (vision etc.) — concat text parts.
                last_user = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
    text = (last_user or "").strip()
    text_l = text.lower()
    n_chars = len(text)

    fast_max = int(thresholds.get("fast_max_chars", 80))
    power_min = int(thresholds.get("power_min_chars", 1500))
    history_after = int(thresholds.get("history_balanced_after", 4))

    has_power_kw = any(kw in text_l for kw in _POWER_KEYWORDS)
    has_fast_kw = any(re.search(r"\b" + re.escape(kw) + r"\b", text_l) for kw in _FAST_KEYWORDS)
    has_code_kw = any(kw in text_l for kw in _CODE_KEYWORDS)
    has_web_kw = any(kw in text_l for kw in _WEB_KEYWORDS)

    # Code beats power because a coder model handles long code better than
    # a generic reasoning model.
    if has_code_kw:
        return "code", "câu hỏi liên quan code → coder model"
    if has_web_kw:
        return "web", "câu hỏi cần thông tin realtime → model có web"
    if has_power_kw:
        return "power", f"keyword (≥1 trong {len(_POWER_KEYWORDS)} từ khoá nặng)"
    if n_chars >= power_min:
        return "power", f"prompt dài ({n_chars} ký tự ≥ {power_min})"
    if has_fast_kw and n_chars <= fast_max:
        return "fast", "lời chào / câu hỏi ngắn"
    if n_chars <= fast_max and user_turns <= 1:
        return "fast", f"prompt ngắn ({n_chars} ký tự ≤ {fast_max})"
    if user_turns >= history_after:
        return "balanced", f"đã có {user_turns} lượt user → cần ngữ cảnh"
    return "balanced", "mặc định trung bình"


# Built-in defaults so smart routing works out of the box, even before the
# user opens the routing settings tab. Keys mirror _classify_complexity tiers.
# These are used only when the corresponding tier in `nine_router.routing.tiers`
# is empty.
_DEFAULT_TIER_MODELS: Dict[str, Tuple[str, ...]] = {
    # Vision: try Gemini first (cheap, fast), fall back to gpt-5.5 (also vision).
    "vision":   ("gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-pro", "cx/gpt-5.5", "kr/claude-sonnet-4.5"),
    # Code:    qwen3-coder-next is purpose-built; gpt-5.3-codex is a strong fallback.
    "code":     ("kr/qwen3-coder-next", "cx/gpt-5.3-codex", "cx/gpt-5.5"),
    # Web/realtime: cx/gpt-5.5 has live browsing in 9Router; otherwise Gemini.
    "web":      ("cx/gpt-5.5", "gemini-3-flash", "gemini-2.5-flash", "gemini-2.5-pro", "kr/claude-sonnet-4.5"),
    # Fast:    Gemini Flash first!
    "fast":     ("gemini-3-flash", "gemini-2.5-flash", "kr/claude-haiku-4.5", "kr/glm-5", "cx/gpt-5.4"),
    # Balanced: Gemini Flash first!
    "balanced": ("gemini-3-flash", "gemini-2.5-flash", "cx/gpt-5.5", "kr/claude-sonnet-4.5", "gemini-2.5-pro"),
    # Power:   sonnet for deep reasoning, then gpt-5.5 codex-xhigh.
    "power":    ("kr/claude-sonnet-4.5", "cx/gpt-5.3-codex-xhigh", "cx/gpt-5.5"),
}


def _pick_default_model(tier: str, available_ids: set) -> Optional[str]:
    """Pick the first default model for `tier` that actually exists in
    9Router's /v1/models list (passed in as a set of ids). Supports suffix and prefix-less matching."""
    for cand in _DEFAULT_TIER_MODELS.get(tier, ()):
        if cand in available_ids:
            return cand
        # Suffix-based match (e.g. matching 'ag/gemini-3-flash' when candidate is 'gemini-3-flash')
        for aid in available_ids:
            if aid == cand or aid.endswith("/" + cand) or aid.split("/")[-1] == cand:
                return aid
    return None


# Cache of the available model ids so we don't hit 9Router on every chat.
_models_cache: Dict[str, Any] = {"ids": set(), "ts": 0.0}


def _available_model_ids(endpoint: str, api_key: str) -> set:
    """Return active model IDs from internal provider manager."""
    try:
        active_models = get_available_models(category="llm", active_only=True)
        return {m.get("id") for m in active_models if m.get("id")}
    except Exception:
        return set()


def _resolve_routed_model(
    data: Dict[str, Any], nr: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    """Decide which model to send upstream and return ({model}, {meta}).

    Priority:
      1. Explicit `model` in the request body — always wins.
      2. `routing.mode == "auto"` — classify and pick the tier model from
         user config, falling back to built-in `_DEFAULT_TIER_MODELS`.
      3. Otherwise fall back to `default_model`.
    """
    # 1. Explicit override.
    explicit = (data.get("model") or "").strip()
    if explicit:
        return explicit, {"mode": "explicit", "tier": None, "reason": "user picked"}

    routing = (nr.get("routing") or {}) if isinstance(nr.get("routing"), dict) else {}
    mode = (routing.get("mode") or "auto").lower()
    tiers = routing.get("tiers") or {}
    thresholds = routing.get("thresholds") or {}

    # 3. Manual mode — just use the configured default.
    if mode != "auto":
        return nr["default_model"], {"mode": "manual", "tier": None, "reason": "manual mode"}

    # 2. Auto routing.
    tier, reason = _classify_complexity(data.get("messages") or [], thresholds)
    model = (tiers.get(tier) or "").strip()
    if model:
        return model, {"mode": "auto", "tier": tier, "reason": reason}

    # No user-configured tier model → use built-in default if it's available
    # in the live model catalog. This is what makes routing "just work"
    # without requiring the user to fill the routing tab.
    available = _available_model_ids(nr.get("endpoint", _DEFAULT_ENDPOINT), nr.get("api_key", ""))
    fallback = _pick_default_model(tier, available) if available else None
    if fallback:
        return fallback, {
            "mode": "auto", "tier": tier,
            "reason": reason + f" → built-in default cho tier {tier!r}",
        }

    # Last resort: configured default model.
    return nr["default_model"], {
        "mode": "auto", "tier": tier,
        "reason": reason + " (không tìm được tier model → default)",
    }


_NO_TOOL_GUARDRAIL = (
    "You are a helpful assistant inside a Vietnamese video tooling app. "
    "You don't have live tools — never emit pseudo-tool tags like "
    "<web_search>, <tool_use>, <invoke>, or <function_calls>. "
    "If a system message provides web search results, use them and cite "
    "sources as [N]. If realtime info is asked but no results were given, "
    "say so plainly and suggest where the user could look. "
    "Default to Vietnamese unless the user writes in another language."
)


def _last_user_text(messages: list) -> str:
    """Extract the trailing user turn's text content."""
    last = ""
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            last = content
        elif isinstance(content, list):
            last = " ".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
    return last.strip()


def _maybe_inject_web_context(messages: list, tier: str, nr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If the trailing user query looks realtime, perform a real web search
    and inject the results as a system message so the LLM has fresh facts
    to work from. Runs whenever the routing tier is 'web' OR the user's
    text matches realtime keywords directly — this ensures even an
    explicit model pick (which bypasses tiering) still gets web context.
    """
    query = _last_user_text(messages)
    if not query or len(query) < 4:
        return None

    # Decide whether this query needs web grounding. Tier="web" is a strong
    # signal; otherwise fall back to keyword matching on the raw query so
    # explicit model picks (tier="explicit") still get the boost.
    needs_web = tier == "web"
    if not needs_web:
        try:
            from utils import web_search as _ws
            needs_web = _ws._looks_like_news(query)
        except Exception:
            needs_web = False
    if not needs_web:
        return None

    try:
        from utils import web_search as _ws
        results = _ws.search(
            query, kind="auto", lang="vi", region="VN", limit=6,
            endpoint=nr.get("endpoint", _DEFAULT_ENDPOINT),
            api_key=nr.get("api_key", ""),
        )
    except Exception as exc:  # pragma: no cover — never fatal
        LOGGER.warning("web_search failed for %r: %s", query[:80], exc)
        return None
    if not results:
        return None
    block = _ws.format_for_prompt(results, max_items=6)
    sys_msg = (
        "Bạn vừa được cấp ngữ cảnh web mới nhất ngay bên dưới. Trả lời "
        "câu hỏi của user dựa trên các kết quả này, trích dẫn nguồn dạng "
        "[N] khi cần (N tương ứng số thứ tự bên dưới). Nếu kết quả không "
        "trả lời được câu hỏi, hãy nói thẳng. Tuyệt đối KHÔNG nói rằng "
        "bạn không có quyền truy cập Internet — vì bạn vừa được cấp dữ "
        "liệu web bên dưới rồi.\n\nNguồn:\n\n" + block
    )
    messages.insert(0, {"role": "system", "content": sys_msg})
    return {"query": query, "count": len(results),
            "sources": [{"title": r["title"], "url": r["url"]} for r in results]}


def _build_chat_payload(data: Dict[str, Any], nr: Dict[str, Any], stream: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the upstream payload + return routing metadata for logging/UI."""
    messages = list(data.get("messages") or [])
    sys_prompt = (nr.get("system_prompt") or "").strip()

    model, route_meta = _resolve_routed_model(data, nr)

    # Inject realtime web context BEFORE the guardrail/system prompts. This
    # gives the model fresh facts so it doesn't refuse with "I have no web
    # access" — because for this turn it effectively does.
    web_meta = _maybe_inject_web_context(messages, route_meta.get("tier") or "", nr)
    if web_meta:
        route_meta["web_search"] = web_meta

    # Always inject the no-tools guardrail so models routed through the Kiro
    # proxy (Sonnet/Haiku) don't hallucinate tool tags. User-provided
    # system prompt is appended after the guardrail.
    base_sys = _NO_TOOL_GUARDRAIL
    if sys_prompt:
        base_sys = base_sys + "\n\n" + sys_prompt
    has_user_system = any(m.get("role") == "system" for m in messages)
    if has_user_system:
        # Prepend our guardrail to the FIRST system message.
        for m in messages:
            if m.get("role") == "system":
                m["content"] = _NO_TOOL_GUARDRAIL + "\n\n" + str(m.get("content") or "")
                break
    else:
        messages = [{"role": "system", "content": base_sys}, *messages]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(data.get("temperature", nr.get("temperature", 0.7))),
        "max_tokens": int(data.get("max_tokens", nr.get("max_tokens", 4096))),
        "stream": stream,
    }
    return payload, route_meta


# ─── Chat (non-streaming) ─────────────────────────────────────────────────
@bp.route("/api/chatbot/chat", methods=["POST"])
def chatbot_chat():
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]

    m_name = (data.get("model") or "").strip()
    if not m_name:
        m_name = get_default_model()

    # 1. Try unified direct dispatcher across active providers in providers.db
    try:
        LOGGER.info("chatbot_chat: dispatching direct AI model (%s)", m_name)
        reply_dict = dispatch_chat_completion(
            model=m_name,
            messages=data.get("messages") or [],
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=data.get("max_tokens") or data.get("max_output_tokens"),
            timeout=_DEFAULT_TIMEOUT,
        )
        choice = (reply_dict.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content", "")
        return jsonify({
            "ok": True,
            "model": reply_dict.get("model") or m_name,
            "requested_model": m_name,
            "choices": reply_dict.get("choices") or [],
            "content": content,
            "finish_reason": choice.get("finish_reason", "stop"),
            "usage": reply_dict.get("usage") or {},
            "routing": {"mode": "direct_ai", "tier": "direct", "reason": "Direct AI Provider"}
        })
    except Exception as exc:
        LOGGER.warning("chatbot_chat direct dispatch failed: %s, checking fallback", exc)

    # 2. Direct Antigravity fallback if active
    antigravity_conn = _get_active_provider_connection("antigravity")
    if antigravity_conn:
        try:
            fb_model = m_name if any(k in m_name.lower() for k in ("gemini", "claude", "flash", "antigravity", "gpt-oss")) else "gemini-3.7-flash"
            LOGGER.info("chatbot_chat: using direct Antigravity connection (%s)", fb_model)
            reply_text = _chat_with_antigravity(antigravity_conn, fb_model, data.get("messages") or [])
            return jsonify({
                "ok": True,
                "model": fb_model,
                "requested_model": m_name,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": reply_text},
                    "finish_reason": "stop"
                }],
                "content": reply_text,
                "routing": {"mode": "direct_antigravity", "tier": "direct", "reason": "Direct Antigravity"}
            })
        except Exception as exc2:
            LOGGER.warning("chatbot_chat: direct Antigravity fallback failed: %s", exc2)
            return jsonify({"ok": False, "error": f"Lỗi AI Provider: {exc2}"}), 502

    return jsonify({"ok": False, "error": "Chưa có AI Provider nào hoạt động."}), 502


# ─── Chat (SSE streaming) ─────────────────────────────────────────────────
@bp.route("/api/chatbot/chat_stream", methods=["POST"])
def chatbot_chat_stream():
    """Forward streaming response directly from active AI provider without 9Router or MITM."""
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]

    m_name = (data.get("model") or "").strip()
    if not m_name:
        m_name = get_default_model()

    reply_text = ""
    resolved_model = m_name

    # Try unified direct AI dispatcher
    try:
        LOGGER.info("chatbot_chat_stream: dispatching direct AI model (%s)", m_name)
        reply_dict = dispatch_chat_completion(
            model=m_name,
            messages=data.get("messages") or [],
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=data.get("max_tokens") or data.get("max_output_tokens"),
            timeout=_DEFAULT_TIMEOUT,
        )
        resolved_model = reply_dict.get("model") or m_name
        choices = reply_dict.get("choices") or []
        if choices:
            reply_text = choices[0].get("message", {}).get("content", "")
    except Exception as exc:
        LOGGER.warning("chatbot_chat_stream direct dispatch failed: %s, trying Antigravity fallback", exc)
        antigravity_conn = _get_active_provider_connection("antigravity")
        if antigravity_conn:
            try:
                resolved_model = m_name if any(k in m_name.lower() for k in ("gemini", "claude", "flash", "antigravity", "gpt-oss")) else "gemini-3.7-flash"
                reply_text = _chat_with_antigravity(antigravity_conn, resolved_model, data.get("messages") or [])
            except Exception as exc2:
                LOGGER.warning("chatbot_chat_stream Antigravity fallback failed: %s", exc2)
                return jsonify({"ok": False, "error": f"Lỗi AI Provider: {exc2}"}), 502
        else:
            return jsonify({"ok": False, "error": f"Lỗi AI Provider: {exc}"}), 502

    def _direct_stream():
        meta = {
            "requested_model": resolved_model,
            "routing": {"mode": "direct_ai", "tier": "direct", "reason": "Direct AI Provider"}
        }
        yield f"event: route\ndata: {json.dumps(meta)}\n\n".encode("utf-8")
        
        words = reply_text.split(" ")
        chunk_size = 4
        for i in range(0, len(words), chunk_size):
            part = " ".join(words[i:i+chunk_size])
            if i + chunk_size < len(words):
                part += " "
            chunk_payload = {
                "choices": [{"delta": {"content": part}}]
            }
            yield f"data: {json.dumps(chunk_payload)}\n\n".encode("utf-8")
            time.sleep(0.015)
        yield b"data: [DONE]\n\n"

    return Response(stream_with_context(_direct_stream()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ─── Quick test ───────────────────────────────────────────────────────────
@bp.route("/api/chatbot/test", methods=["POST"])
def chatbot_test():
    data = request.json or {}
    model = (data.get("model") or get_default_model()).strip()
    t0 = time.time()
    try:
        reply_dict = dispatch_chat_completion(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: PONG"}],
            timeout=30,
        )
        choice = (reply_dict.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content", "")
        elapsed_ms = int((time.time() - t0) * 1000)
        return jsonify({
            "ok": True,
            "reply": content,
            "content": content,
            "model": reply_dict.get("model") or model,
            "elapsed_ms": elapsed_ms,
        })
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        return jsonify({"ok": False, "error": str(exc), "elapsed_ms": elapsed_ms}), 502


# ─── Session persistence (SQLite) ─────────────────────────────────────────
# The floating chat widget syncs sessions/messages to a local SQLite store
# so conversations survive browser cache flushes and can be replayed across
# devices that hit this same backend. Keep these endpoints tolerant: failures
# in persistence must not break the live chat flow (the UI also keeps a
# localStorage shadow copy).
from core import chat_store as _chat_store  # noqa: E402  (import after blueprint setup)


def _store_ready() -> bool:
    return _chat_store._DB_PATH is not None  # type: ignore[attr-defined]


@bp.route("/api/chatbot/sessions", methods=["GET"])
def chatbot_list_sessions():
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    try:
        rows = _chat_store.list_sessions(limit=int(request.args.get("limit") or 200))
    except Exception as exc:
        LOGGER.warning("chatbot_list_sessions: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "sessions": rows})


@bp.route("/api/chatbot/sessions", methods=["POST"])
def chatbot_create_session():
    """Create or upsert a session.

    Body: { id, title?, model? }
    """
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    data = request.json or {}
    sid = (str(data.get("id") or "")).strip()
    if not sid:
        return jsonify({"ok": False, "error": "id required"}), 400
    try:
        out = _chat_store.upsert_session(
            sid,
            title=(data.get("title") or None),
            model=(data.get("model") or None),
        )
    except Exception as exc:
        LOGGER.warning("chatbot_create_session: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "session": out})


@bp.route("/api/chatbot/sessions/<sid>", methods=["GET"])
def chatbot_get_session(sid: str):
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    try:
        sess = _chat_store.get_session(sid)
        if not sess:
            return jsonify({"ok": False, "error": "not_found"}), 404
        msgs = _chat_store.list_messages(sid, limit=int(request.args.get("limit") or 500))
    except Exception as exc:
        LOGGER.warning("chatbot_get_session: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "session": sess, "messages": msgs})


@bp.route("/api/chatbot/sessions/<sid>", methods=["PATCH"])
def chatbot_rename_session(sid: str):
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    data = request.json or {}
    title = str(data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "title required"}), 400
    try:
        ok = _chat_store.rename_session(sid, title)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": ok})


@bp.route("/api/chatbot/sessions/<sid>", methods=["DELETE"])
def chatbot_delete_session(sid: str):
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    hard = (request.args.get("hard") or "").lower() in ("1", "true", "yes")
    try:
        ok = _chat_store.delete_session(sid, hard=hard)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": ok})


@bp.route("/api/chatbot/sessions/<sid>/messages", methods=["POST"])
def chatbot_add_message(sid: str):
    """Append a single message to a session.

    Body:
      role: 'user' | 'assistant' | 'system'  (required)
      content: str | list (multimodal parts) (required)
      attachments: optional [{kind,name,size,mime,thumbDataUrl?}]
      title: optional — also rename the session in the same call
      model: optional — also save active model
    """
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    data = request.json or {}
    role = str(data.get("role") or "").strip()
    if role not in ("user", "assistant", "system"):
        return jsonify({"ok": False, "error": "role required"}), 400
    if "content" not in data:
        return jsonify({"ok": False, "error": "content required"}), 400
    try:
        # Make sure the session exists (auto-upsert).
        _chat_store.upsert_session(sid, title=data.get("title"), model=data.get("model"))
        msg = _chat_store.add_message(
            sid,
            role,
            data.get("content"),
            attachments=data.get("attachments"),
        )
    except Exception as exc:
        LOGGER.warning("chatbot_add_message: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "message": msg})


@bp.route("/api/chatbot/sessions/<sid>/messages", methods=["PUT"])
def chatbot_replace_messages(sid: str):
    """Replace all messages in a session — for one-shot syncs after offline use.

    Body: { messages: [{role,content,attachments?,ts?}, ...] }
    """
    if not _store_ready():
        return jsonify({"ok": False, "error": "store_unavailable"}), 503
    data = request.json or {}
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        return jsonify({"ok": False, "error": "messages must be a list"}), 400
    try:
        _chat_store.upsert_session(sid)
        n = _chat_store.replace_messages(sid, msgs)
    except Exception as exc:
        LOGGER.warning("chatbot_replace_messages: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "count": n})

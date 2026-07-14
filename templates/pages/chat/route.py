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

import hashlib
import json
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Response, jsonify, request, stream_with_context

from core_app import LOGGER, load_cfg, save_cfg

bp = Blueprint("chatbot", __name__)

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


def _is_9router_reachable(endpoint: str) -> bool:
    """Quick connectivity check to 9Router (2s timeout)."""
    try:
        url = endpoint.rstrip("/").replace("/v1", "") + "/api/health"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


# Cache reachability for 15 seconds to avoid hammering on every request.
_reachable_cache: Dict[str, Any] = {"ok": None, "ts": 0.0}


def _nine_router_reachable(endpoint: str) -> bool:
    """Cached reachability check (15s TTL)."""
    now = time.time()
    if _reachable_cache["ok"] is not None and (now - _reachable_cache["ts"]) < 15.0:
        return _reachable_cache["ok"]
    ok = _is_9router_reachable(endpoint)
    _reachable_cache["ok"] = ok
    _reachable_cache["ts"] = now
    return ok

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
    api_key = str(nr.get("api_key") or "").strip()
    if (not api_key or "machineId" in api_key) and _cli_token():
        try:
            status_code, body = _local_dashboard_get("/api/keys", endpoint=nr.get("endpoint") or _DEFAULT_ENDPOINT)
            if status_code == 200 and isinstance(body, dict):
                keys = body.get("keys") or []
                active_key = next((k.get("key") for k in keys if k.get("isActive") and k.get("key")), None)
                if not active_key and keys:
                    active_key = keys[0].get("key")
                if active_key:
                    nr["api_key"] = active_key
                    cfg["nine_router"] = nr
                    save_cfg(cfg)
        except Exception:
            pass

    nr.setdefault("endpoint", _DEFAULT_ENDPOINT)
    nr.setdefault("api_key", "")
    nr.setdefault("default_model", _DEFAULT_MODEL)
    nr.setdefault("system_prompt", "")
    nr.setdefault("temperature", 0.7)
    nr.setdefault("max_tokens", 4096)
    return nr


def _normalize_endpoint(raw: str) -> str:
    """Trim trailing slashes; accept users typing the bare host."""
    base = (raw or "").strip().rstrip("/")
    if not base:
        return _DEFAULT_ENDPOINT
    if not base.endswith("/v1") and not re.search(r"/v1(/|$)", base):
        base = base + "/v1"
    return base


def _base_origin(endpoint: str) -> str:
    """`http://localhost:20128/v1` → `http://localhost:20128`."""
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
    """GET against `<origin>{path}` using the CLI token as authentication."""
    headers: Dict[str, str] = {"Accept": "application/json"}
    tok = _cli_token()
    if tok:
        headers[_CLI_TOKEN_HEADER] = tok
    return _http_json(_base_origin(endpoint) + path, headers=headers, timeout=timeout)


def _local_dashboard_post(
    path: str,
    payload: Dict[str, Any],
    *,
    endpoint: str,
    timeout: int = _LIGHT_TIMEOUT,
) -> Tuple[int, Any]:
    headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    tok = _cli_token()
    if tok:
        headers[_CLI_TOKEN_HEADER] = tok
    return _http_json(
        _base_origin(endpoint) + path,
        method="POST",
        headers=headers,
        payload=payload,
        timeout=timeout,
    )


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
    """Tell the UI whether 9Router is up, whether it requires a key, and
    whether we already have a usable key cached.

    Returns:
      { ok, reachable, version, require_api_key, has_key, masked_key,
        endpoint, has_cli_token, settings: {rtk, caveman, ...} }
    """
    global _STATUS_CACHE, _STATUS_CACHE_TIME
    import time
    now = time.time()
    
    # Bypass cache if force=1 or force=true is requested
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    
    if not force and _STATUS_CACHE and (now - _STATUS_CACHE_TIME) < 5.0:
        return jsonify(_STATUS_CACHE)

    cfg = load_cfg()
    nr = dict(cfg.get("nine_router") or {})
    api_key = str(nr.get("api_key") or "").strip()
    if (not api_key or "machineId" in api_key) and _cli_token():
        try:
            status_code, body = _local_dashboard_get("/api/keys", endpoint=nr.get("endpoint") or _DEFAULT_ENDPOINT)
            if status_code == 200 and isinstance(body, dict):
                keys = body.get("keys") or []
                active_key = next((k.get("key") for k in keys if k.get("isActive") and k.get("key")), None)
                if not active_key and keys:
                    active_key = keys[0].get("key")
                if active_key:
                    nr["api_key"] = active_key
                    cfg["nine_router"] = nr
                    save_cfg(cfg)
        except Exception:
            pass

    nr = _nine_router_cfg()
    endpoint = nr["endpoint"]

    # /api/health is unauthenticated.
    reachable = False
    version = None
    try:
        status, body = _http_json(
            _base_origin(endpoint) + "/api/health", timeout=_LIGHT_TIMEOUT
        )
        reachable = status < 500 and isinstance(body, dict)
    except Exception as exc:
        LOGGER.debug("chatbot_status: health probe failed — %s", exc)

    if reachable:
        try:
            vstatus, vbody = _http_json(
                _base_origin(endpoint) + "/api/version", timeout=_LIGHT_TIMEOUT
            )
            if vstatus == 200 and isinstance(vbody, dict):
                version = vbody.get("version")
        except Exception:
            pass

    # /api/settings needs CLI token or login. Defaults to requireApiKey=True
    # if we can't read it.
    require_api_key = True
    settings_ok = False
    settings_subset: Dict[str, Any] = {}
    mitm_status = {"running": False, "isAdmin": False, "certTrusted": False}
    if reachable:
        try:
            sstatus, sbody = _local_dashboard_get("/api/settings", endpoint=endpoint)
            if sstatus == 200 and isinstance(sbody, dict):
                settings_ok = True
                # The setting is `requireApiKey` (camelCase) per 9Router source.
                require_api_key = bool(sbody.get("requireApiKey", True))
                # Surface the few flags that materially affect chat output
                # so the UI can display & toggle them without leaving the tab.
                settings_subset = {
                    "rtk_enabled": bool(sbody.get("rtkEnabled", True)),
                    "caveman_enabled": bool(sbody.get("cavemanEnabled", False)),
                    "caveman_level": str(sbody.get("cavemanLevel", "full")),
                    "combo_strategy": str(sbody.get("comboStrategy", "fallback")),
                    "require_login": bool(sbody.get("requireLogin", True)),
                }
        except Exception as exc:
            LOGGER.debug("chatbot_status: settings probe failed — %s", exc)
        try:
            mstatus, mbody = _local_dashboard_get("/api/cli-tools/antigravity-mitm", endpoint=endpoint)
            if mstatus == 200 and isinstance(mbody, dict):
                mitm_status = {
                    "running": bool(mbody.get("running")),
                    "isAdmin": bool(mbody.get("isAdmin")),
                    "certTrusted": bool(mbody.get("certTrusted")),
                    "dnsStatus": mbody.get("dnsStatus") or {}
                }
        except Exception as exc:
            LOGGER.debug("chatbot_status: mitm status probe failed — %s", exc)

    key_valid = None
    key_error = None
    if nr.get("api_key") and reachable:
        try:
            status_code, body = _local_dashboard_get("/api/keys", endpoint=endpoint)
            if status_code == 200 and isinstance(body, dict):
                keys = body.get("keys") or []
                match = next((k for k in keys if k.get("key") == nr["api_key"]), None)
                if match:
                    key_valid = bool(match.get("isActive", True))
                else:
                    key_valid = True
            else:
                mstatus, mbody = _http_json(
                    endpoint + "/models",
                    headers={"Authorization": f"Bearer {nr['api_key']}"},
                    timeout=_LIGHT_TIMEOUT
                )
                key_valid = mstatus < 400
                if mstatus >= 400:
                    key_error = f"HTTP {mstatus}"
        except Exception as e:
            key_valid = False
            key_error = str(e)

    cfg = load_cfg()
    fallback = _pick_fallback_provider(cfg)
    res_payload = {
        "ok": True,
        "endpoint": endpoint,
        "reachable": reachable,
        "version": version,
        "require_api_key": require_api_key,
        "settings_ok": settings_ok,
        "settings": settings_subset,
        "has_key": bool((nr.get("api_key") or "").strip()),
        "masked_key": _mask_key(nr.get("api_key") or "") if nr.get("api_key") else "",
        "key_valid": key_valid,
        "key_error": key_error,
        "has_cli_token": bool(_cli_token()),
        "fallback_available": fallback is not None,
        "fallback_provider": fallback["name"] if fallback else None,
        "mitm": mitm_status
    }
    _STATUS_CACHE = res_payload
    _STATUS_CACHE_TIME = now
    return jsonify(res_payload)


@bp.route("/api/chatbot/mitm", methods=["POST"])
def chatbot_mitm_control():
    """Start, stop, or trust certificates for 9Router's local MITM server."""
    data = request.json or {}
    action = data.get("action")  # "start" | "stop" | "trust-cert"
    
    nr = _nine_router_cfg()
    endpoint = nr["endpoint"]
    
    if action == "start":
        api_key = nr.get("api_key") or ""
        if not api_key:
            return jsonify({
                "ok": False,
                "message": "Cần có API key trước khi khởi chạy MITM Server. Vui lòng bấm 'Tự động lấy key' hoặc điền API key."
            }), 400
        
        payload = {
            "apiKey": api_key,
            "sudoPassword": "",
            "forceKillPort443": bool(data.get("forceKillPort443", True))
        }
        status_code, body = _local_dashboard_post("/api/cli-tools/antigravity-mitm", payload, endpoint=endpoint)
        if status_code >= 400:
            err_msg = body.get("error") if isinstance(body, dict) else body
            return jsonify({"ok": False, "message": f"Không thể bật MITM Server: {err_msg}"}), status_code
        return jsonify({"ok": True, "running": body.get("running"), "pid": body.get("pid")})
        
    elif action == "stop":
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        tok = _cli_token()
        if tok:
            headers[_CLI_TOKEN_HEADER] = tok
        
        status_code, body = _http_json(
            _base_origin(endpoint) + "/api/cli-tools/antigravity-mitm",
            method="DELETE",
            headers=headers,
            payload={"sudoPassword": ""},
            timeout=_LIGHT_TIMEOUT
        )
        if status_code >= 400:
            err_msg = body.get("error") if isinstance(body, dict) else body
            return jsonify({"ok": False, "message": f"Không thể dừng MITM Server: {err_msg}"}), status_code
        return jsonify({"ok": True, "running": False})
        
    elif action == "trust-cert":
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        tok = _cli_token()
        if tok:
            headers[_CLI_TOKEN_HEADER] = tok
        
        status_code, body = _http_json(
            _base_origin(endpoint) + "/api/cli-tools/antigravity-mitm",
            method="PATCH",
            headers=headers,
            payload={"tool": "antigravity", "action": "trust-cert", "sudoPassword": ""},
            timeout=_LIGHT_TIMEOUT
        )
        if status_code >= 400:
            err_msg = body.get("error") if isinstance(body, dict) else body
            return jsonify({"ok": False, "message": f"Không thể tin cậy chứng chỉ: {err_msg}"}), status_code
        return jsonify({"ok": True, "certTrusted": body.get("certTrusted")})

    return jsonify({"ok": False, "message": "Hành động không hợp lệ."}), 400


@bp.route("/api/chatbot/start_9router", methods=["POST"])
def chatbot_start_9router():
    """Start 9Router locally. If it is not installed, install it globally first.
    If elevation is needed to run powershell admin, it asks or launches itself.
    """
    import shutil
    import subprocess
    import platform
    import ctypes

    sysname = platform.system().lower()
    if not sysname.startswith("win"):
        return jsonify({
            "ok": False,
            "message": f"Tính năng này chỉ hỗ trợ trên Windows. Trên {sysname.capitalize()}, vui lòng cài đặt bằng 'npm install -g 9router' và chạy '9router' thủ công."
        })

    # Check if 9router command exists
    has_9router = shutil.which("9router") is not None

    if not has_9router:
        # Check npm
        has_npm = shutil.which("npm") is not None
        if not has_npm:
            return jsonify({
                "ok": False,
                "message": "Không tìm thấy lệnh npm (NodeJS) trên hệ thống! Vui lòng cài đặt NodeJS từ https://nodejs.org trước."
            })

        # Launch powershell as admin to install and run 9Router
        ps_script = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "Write-Host 'Dang cai dat 9Router toan cuc qua npm...' -ForegroundColor Yellow; "
            "npm install -g 9router; "
            "if (Get-Command 9router -ErrorAction SilentlyContinue) { "
            "  Write-Host 'Da cai dat thanh cong! Dang khoi dong 9Router...' -ForegroundColor Green; "
            "  9router; "
            "} else { "
            "  Write-Host 'Loi: Khong the cai dat 9Router. Vui long kiem tra ket noi mang va thu lai.' -ForegroundColor Red; "
            "}"
        )
        try:
            # First try as admin to install globally if needed
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f"-NoExit -Command \"{ps_script}\"", None, 1
            )
            if ret <= 32:
                if ret == 5:  # UAC denied
                    # Fallback to non-elevated installation attempt
                    ret_normal = ctypes.windll.shell32.ShellExecuteW(
                        None, "open", "powershell.exe",
                        f"-NoExit -Command \"{ps_script}\"", None, 1
                    )
                    if ret_normal > 32:
                        return jsonify({
                            "ok": True,
                            "message": "UAC bị từ chối. Đang thử cài đặt và khởi chạy 9Router ở quyền người dùng bình thường..."
                        })
                return jsonify({
                    "ok": False,
                    "message": f"Yêu cầu quyền Administrator thất bại (mã lỗi {ret})."
                })
            return jsonify({
                "ok": True,
                "message": "Đang yêu cầu quyền Administrator để cài đặt và khởi chạy 9Router..."
            })
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Lỗi khi khởi chạy trình cài đặt: {exc}"
            })

    # If it is already installed, launch it as a normal user first (no UAC required for standard routing)
    try:
        ps_script = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force; "
            "Write-Host 'Dang khoi dong 9Router...' -ForegroundColor Green; "
            "9router"
        )
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "open", "powershell.exe",
            f"-NoExit -Command \"{ps_script}\"", None, 1
        )
        if ret <= 32:
            # If open fails, fallback to runas
            ret_admin = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f"-NoExit -Command \"{ps_script}\"", None, 1
            )
            if ret_admin <= 32:
                return jsonify({
                    "ok": False,
                    "message": f"Khởi chạy 9Router thất bại (mã lỗi {ret_admin})."
                })
            return jsonify({
                "ok": True,
                "message": "Đang yêu cầu quyền Administrator để khởi chạy 9Router..."
            })
        return jsonify({
            "ok": True,
            "message": "Đang khởi chạy 9Router..."
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "message": f"Không thể khởi chạy 9Router: {exc}"
        })


@bp.route("/api/chatbot/settings", methods=["POST"])
def chatbot_update_settings():
    """Toggle 9Router output-shaping flags (Caveman / RTK) from our UI.

    Body keys (all optional):
      caveman_enabled (bool)
      caveman_level   ("lite" | "full" | "extreme" | …)
      rtk_enabled     (bool)

    Maps to 9Router PATCH /api/settings under the camelCase names.
    """
    data = request.json or {}
    payload: Dict[str, Any] = {}
    if "caveman_enabled" in data:
        payload["cavemanEnabled"] = bool(data["caveman_enabled"])
    if "caveman_level" in data:
        payload["cavemanLevel"] = str(data["caveman_level"] or "full")
    if "rtk_enabled" in data:
        payload["rtkEnabled"] = bool(data["rtk_enabled"])
    if not payload:
        return jsonify({"ok": False, "error": "no_fields"}), 400

    nr = _nine_router_cfg()
    if not _cli_token():
        return jsonify({"ok": False, "error": "no_cli_token",
                        "message": "Cần CLI token (cùng máy) để chỉnh settings 9Router."}), 400

    # 9Router uses PATCH for /api/settings; we don't have a helper, so build
    # the request inline using the CLI token.
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers[_CLI_TOKEN_HEADER] = _cli_token() or ""
    url = _base_origin(nr["endpoint"]) + "/api/settings"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            method="PATCH", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=_LIGHT_TIMEOUT) as resp:
            body = resp.read()
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                parsed = body.decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            parsed = body.decode("utf-8", "replace")
        return jsonify({"ok": False, "status": exc.code, "error": parsed}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502

    if status >= 400:
        return jsonify({"ok": False, "status": status, "error": parsed}), 502

    safe = {}
    if isinstance(parsed, dict):
        safe = {
            "rtk_enabled": bool(parsed.get("rtkEnabled", True)),
            "caveman_enabled": bool(parsed.get("cavemanEnabled", False)),
            "caveman_level": str(parsed.get("cavemanLevel", "full")),
        }
    return jsonify({"ok": True, "settings": safe})


# ─── Key discovery / creation ─────────────────────────────────────────────
@bp.route("/api/chatbot/keys", methods=["GET"])
def chatbot_list_keys():
    nr = _nine_router_cfg()
    if not _cli_token():
        return jsonify({"ok": False, "error": "no_cli_token",
                        "message": "Không xác định được machine ID — chạy server trên cùng máy với 9Router."}), 400
    try:
        status, body = _local_dashboard_get("/api/keys", endpoint=nr["endpoint"])
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if status >= 400:
        return jsonify({"ok": False, "status": status,
                        "error": (body or {}).get("error") if isinstance(body, dict) else body}), 502

    keys = (body or {}).get("keys") or []
    # Strip the actual key strings so the UI never has to handle plaintext.
    safe = [
        {
            "id": k.get("id"),
            "name": k.get("name"),
            "masked": _mask_key(k.get("key") or ""),
            "is_active": bool(k.get("isActive", True)),
            "created_at": k.get("createdAt"),
        }
        for k in keys
    ]
    return jsonify({"ok": True, "count": len(keys), "keys": safe})


@bp.route("/api/chatbot/keys", methods=["POST"])
def chatbot_create_key():
    """Create a new API key on 9Router and return it (caller decides whether
    to persist via /api/chatbot/auto_setup)."""
    data = request.json or {}
    name = (str(data.get("name") or "").strip()
            or f"toolvideo-{int(time.time())}")
    nr = _nine_router_cfg()
    if not _cli_token():
        return jsonify({"ok": False, "error": "no_cli_token"}), 400
    try:
        status, body = _local_dashboard_post(
            "/api/keys", {"name": name}, endpoint=nr["endpoint"], timeout=10
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if status >= 400 or not isinstance(body, dict) or not body.get("key"):
        return jsonify({"ok": False, "status": status, "error": body}), 502
    return jsonify({
        "ok": True,
        "id": body.get("id"),
        "name": body.get("name"),
        "key": body.get("key"),
        "masked": _mask_key(body.get("key") or ""),
    })


@bp.route("/api/chatbot/auto_setup", methods=["POST"])
def chatbot_auto_setup():
    """One-click: pick the first active key (or create one) and persist it.

    Body (optional):
      prefer_active: bool — pick the first `isActive` key (default true).
      create_if_missing: bool — create a new key when none is found (default true).
      name: str — name for the new key when creating.
    """
    data = request.json or {}
    prefer_active = data.get("prefer_active", True)
    create_if_missing = data.get("create_if_missing", True)
    name = (str(data.get("name") or "").strip() or f"toolvideo-{int(time.time())}")

    nr = _nine_router_cfg()
    if not _cli_token():
        return jsonify({
            "ok": False, "error": "no_cli_token",
            "message": "Không lấy được machine ID — auto-setup chỉ hoạt động khi tool và 9Router chạy chung máy.",
        }), 400

    try:
        lstatus, lbody = _local_dashboard_get("/api/keys", endpoint=nr["endpoint"])
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if lstatus >= 400 or not isinstance(lbody, dict):
        return jsonify({"ok": False, "status": lstatus, "error": lbody}), 502

    keys = lbody.get("keys") or []
    chosen = None
    created = False
    if prefer_active:
        for k in keys:
            if k.get("isActive") and k.get("key"):
                chosen = k
                break
    if not chosen and keys:
        chosen = keys[0]

    if not chosen and create_if_missing:
        try:
            cstatus, cbody = _local_dashboard_post(
                "/api/keys", {"name": name}, endpoint=nr["endpoint"], timeout=10
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
        if cstatus >= 400 or not isinstance(cbody, dict) or not cbody.get("key"):
            return jsonify({"ok": False, "status": cstatus, "error": cbody}), 502
        chosen = cbody
        created = True

    if not chosen or not chosen.get("key"):
        return jsonify({"ok": False, "error": "no_key_found",
                        "message": "Không thấy API key nào — tạo key bằng tay tại /dashboard/endpoint."}), 404

    cfg = load_cfg()
    nr = dict(cfg.get("nine_router") or {})
    # Hydrate with defaults so the persisted YAML self-documents the integration.
    nr.setdefault("endpoint", _DEFAULT_ENDPOINT)
    nr.setdefault("default_model", _DEFAULT_MODEL)
    nr.setdefault("system_prompt", "")
    nr.setdefault("temperature", 0.7)
    nr.setdefault("max_tokens", 4096)
    nr["api_key"] = chosen["key"]
    cfg["nine_router"] = nr
    save_cfg(cfg)

    LOGGER.info("Saved 9Router API key from auto-setup: %s (%s)",
                _mask_key(chosen["key"]), chosen.get("name") or chosen.get("id"))

    return jsonify({
        "ok": True,
        "id": chosen.get("id"),
        "name": chosen.get("name"),
        "masked": _mask_key(chosen.get("key") or ""),
        "created": created,
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
    """Proxy `/v1/models/{kind}` so the UI can populate per-kind dropdowns
    without leaking the API key. `kind` ∈ image|tts|stt|embedding|image-to-text|web."""
    kind = (request.args.get("kind") or "").strip().lower()
    sub = _KIND_TO_PATH.get(kind)
    if not sub:
        return jsonify({"ok": False, "error": "unknown_kind",
                        "supported": list(_KIND_TO_PATH.keys())}), 400

    nr = _nine_router_cfg()
    headers = {"Accept": "application/json"}
    if (nr.get("api_key") or "").strip():
        headers["Authorization"] = f"Bearer {nr['api_key']}"
    url = nr["endpoint"].rstrip("/") + sub

    try:
        status, body = _http_json(url, method="GET", headers=headers, timeout=_MODELS_TIMEOUT)
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if status >= 400:
        return jsonify({"ok": False, "status": status, "error": body}), 502

    items = []
    if isinstance(body, dict):
        for it in body.get("data") or []:
            mid = (it or {}).get("id")
            if mid:
                items.append({"id": mid, "owned_by": (it or {}).get("owned_by", "")})
    return jsonify({"ok": True, "kind": kind, "models": items})


@bp.route("/api/chatbot/image", methods=["POST"])
def chatbot_image():
    """Generate an image via 9Router /v1/images/generations.

    Supports both standard JSON responses (Gemini, OpenAI) and SSE streaming
    responses (Codex cx/* models). The Codex provider returns Server-Sent
    Events with progress updates and a final `partial_image` event containing
    the base64-encoded image.

    Body:
      prompt (str, required)
      model (str, optional)            — default: cx/gpt-5.5-image
      n     (int, default 1)
      size  (str, optional)            — "1024x1024", "auto", etc.
      quality (str, optional)          — "auto", "high", "low"
      background (str, optional)       — "auto", "transparent", "opaque"
      output_format (str, optional)    — "png", "jpeg", "webp"
    """
    data = request.json or {}
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt required"}), 400

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()

    model = (data.get("model") or "").strip() or "cx/gpt-5.5-image"
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "n": int(data.get("n") or 1),
    }
    # Size / quality / background / output_format — Codex models use these.
    size = data.get("size") or "auto"
    payload["size"] = str(size)
    if data.get("quality"):
        payload["quality"] = str(data["quality"])
    else:
        payload["quality"] = "auto"
    if data.get("background"):
        payload["background"] = str(data["background"])
    else:
        payload["background"] = "auto"
    if data.get("output_format"):
        payload["output_format"] = str(data["output_format"])
    else:
        payload["output_format"] = "png"
    if data.get("style"):
        payload["style"] = str(data["style"])
    # Legacy field — only add for non-Codex models that expect it.
    if not model.startswith("cx/"):
        payload["response_format"] = data.get("response_format") or "b64_json"
        # Remove Codex-specific fields that other providers don't understand.
        payload.pop("output_format", None)
        payload.pop("background", None)

    url = f"{nr['endpoint'].rstrip('/')}/images/generations"

    # Use `requests` with stream=True because Codex image models return SSE.
    try:
        import requests as _requests  # type: ignore
    except Exception as exc:
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    req_headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        req_headers["Authorization"] = f"Bearer {api_key}"

    try:
        upstream = _requests.post(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=req_headers,
            stream=True,
            timeout=(10, 300),  # (connect, read)
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502

    if upstream.status_code >= 400:
        try:
            err_body = upstream.text
            err_json = json.loads(err_body) if err_body else {}
            msg = (err_json.get("error") or {}).get("message") or err_body
        except Exception:
            msg = upstream.text or f"HTTP {upstream.status_code}"
        upstream.close()
        return jsonify({"ok": False, "status": upstream.status_code, "error": msg}), 502

    # Determine if response is SSE or plain JSON.
    content_type = (upstream.headers.get("Content-Type") or "").lower()
    is_sse = "text/event-stream" in content_type

    if not is_sse:
        # Standard JSON response (Gemini, OpenAI native).
        try:
            body = upstream.json()
        except Exception:
            body = {}
        upstream.close()
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "invalid_response"}), 502
        items = body.get("data") or []
        return jsonify({
            "ok": True,
            "model": model,
            "images": items,
            "raw": {"created": body.get("created"), "model": body.get("model")},
        })

    # SSE streaming response (Codex cx/* models).
    # Collect all b64_json images from `partial_image` events.
    images: list = []
    try:
        buf = ""
        for chunk in upstream.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue
            buf += chunk

        # Parse SSE events from the accumulated buffer.
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
                except (json.JSONDecodeError, TypeError):
                    # The b64_json might be too large for a single data line;
                    # try to extract it directly.
                    pass
            elif event_name == "result" or (not event_name and '"data"' in data_str):
                # Some versions wrap the final result in a standard envelope.
                try:
                    result_data = json.loads(data_str)
                    for item in (result_data.get("data") or []):
                        if isinstance(item, dict) and (item.get("b64_json") or item.get("url")):
                            images.append(item)
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception as exc:
        LOGGER.warning("chatbot_image SSE parse error: %s", exc)
    finally:
        upstream.close()

    if not images:
        return jsonify({
            "ok": False,
            "error": "no_image_in_response",
            "message": "9Router trả về SSE nhưng không tìm thấy ảnh. Thử lại hoặc đổi model.",
        }), 502

    return jsonify({
        "ok": True,
        "model": model,
        "images": images,
        "raw": {"model": model},
    })


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
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 9Router takes `response_format` as a QUERY param (mp3 raw bytes by
    # default, or json -> {audio, format}). We always request raw audio here
    # and convert to base64 ourselves when the caller asks for ?json=1.
    fmt = str(data.get("format") or "mp3").strip().lower() or "mp3"
    from urllib.parse import urlencode as _urlencode
    qs = _urlencode({"response_format": fmt})
    url = f"{nr['endpoint'].rstrip('/')}/audio/speech?{qs}"
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
    url = f"{nr['endpoint'].rstrip('/')}/audio/transcriptions"

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
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"input": inp, "model": model}
    url = f"{nr['endpoint'].rstrip('/')}/embeddings"
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
    """Proxy `GET /v1/models` — public on 9Router (no auth needed).
    Falls back to listing available direct providers when 9Router is offline.
    """
    nr = _nine_router_cfg()
    cfg = load_cfg()
    headers = {"Accept": "application/json"}
    if (nr.get("api_key") or "").strip():
        headers["Authorization"] = f"Bearer {nr['api_key']}"

    url = f"{nr['endpoint'].rstrip('/')}/models"
    nine_router_ok = False
    items = []
    try:
        status, body = _http_json(url, method="GET", headers=headers, timeout=_MODELS_TIMEOUT)
        if status < 400 and isinstance(body, dict):
            nine_router_ok = True
            
            from utils.translation import get_9router_active_providers, _matches_provider, is_chat_model
            active_providers = get_9router_active_providers()
            
            for it in body.get("data") or []:
                mid = (it or {}).get("id")
                if mid:
                    if is_chat_model(mid):
                        # Filter based on active providers if the database was successfully read
                        if active_providers is not None:
                            parts = mid.split('/')
                            if len(parts) > 1:
                                prefix = parts[0]
                                if not _matches_provider(prefix, active_providers):
                                    continue
                                    
                        items.append({"id": mid, "owned_by": (it or {}).get("owned_by", "")})
    except Exception as exc:
        LOGGER.warning("chatbot_models: 9Router unreachable — %s", exc)

    # If 9Router is offline, provide fallback models from config keys
    if not nine_router_ok:
        for prov in _FALLBACK_PROVIDERS:
            key = _get_cfg_key(cfg, prov["key_path"])
            if key:
                items.append({"id": prov["model"], "owned_by": prov["name"]})

    return jsonify({"ok": True, "models": items, "default": nr["default_model"],
                    "fallback_active": not nine_router_ok})


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
    """Return the set of model ids 9Router currently exposes. 30 s TTL."""
    now = time.time()
    if (now - _models_cache["ts"]) < 30.0:
        return _models_cache["ids"]
    
    # Update timestamp to prevent immediate retry hangs
    _models_cache["ts"] = now
    
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        status, body = _http_json(
            (endpoint or "").rstrip("/") + "/models",
            headers=headers, timeout=_LIGHT_TIMEOUT,
        )
        if status == 200 and isinstance(body, dict):
            ids = {(it or {}).get("id") for it in (body.get("data") or []) if (it or {}).get("id")}
            _models_cache["ids"] = ids
            return ids
    except Exception as exc:
        LOGGER.debug("_available_model_ids: %s", exc)
    return _models_cache["ids"]


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


@bp.route("/api/chatbot/chat", methods=["POST"])
def chatbot_chat():
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]

    nr = _nine_router_cfg()
    cfg = load_cfg()

    # ── Try 9Router first ──
    api_key = (nr.get("api_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload, route = _build_chat_payload(data, nr, stream=False)
    url = f"{nr['endpoint'].rstrip('/')}/chat/completions"

    nine_router_failed = False
    try:
        status, body = _http_json(url, method="POST", headers=headers, payload=payload)
    except Exception as exc:
        LOGGER.warning("chatbot_chat: 9Router unreachable — %s", exc)
        nine_router_failed = True

    if not nine_router_failed and status >= 400:
        nine_router_failed = True

    # ── Fallback to direct providers if 9Router failed ──
    if nine_router_failed:
        try:
            from utils.translation import load_api_keys_status
            api_status = load_api_keys_status()
        except Exception:
            api_status = {}

        fallbacks = []
        for prov in _FALLBACK_PROVIDERS:
            # Skip if marked as failed/inactive
            if api_status.get(prov["name"], {}).get("ok") is False:
                continue
            key = _get_cfg_key(cfg, prov["key_path"])
            if key:
                fallbacks.append({
                    "name": prov["name"],
                    "endpoint": prov["endpoint"],
                    "model": prov["model"],
                    "api_key": key
                })
        
        # Prioritize model hint
        model_hint = payload.get("model", "")
        if model_hint:
            hint_lower = model_hint.lower()
            for idx, fb in enumerate(fallbacks):
                if (fb["model"].lower() == hint_lower
                        or fb["name"] in hint_lower
                        or hint_lower.startswith(fb["name"])):
                    fallbacks.insert(0, fallbacks.pop(idx))
                    fb["model"] = model_hint
                    break
        
        if not fallbacks:
            return jsonify({"ok": False, "error": "unreachable",
                           "message": "9Router offline và không có provider fallback nào hoạt động."}), 502

        success = False
        last_status = 502
        last_body = "Tất cả các fallback providers đều thất bại."
        
        for fallback in fallbacks:
            LOGGER.info("chatbot_chat: trying fallback to %s (model: %s)", fallback["name"], fallback["model"])
            fb_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {fallback['api_key']}",
            }
            fb_payload = dict(payload)
            fb_payload["model"] = fallback["model"]
            fb_payload["stream"] = False
            route = {"mode": "fallback", "tier": "direct",
                     "reason": f"9Router offline/error → {fallback['name']}"}

            try:
                status, body = _http_json(fallback["endpoint"], method="POST",
                                          headers=fb_headers, payload=fb_payload,
                                          timeout=_DEFAULT_TIMEOUT)
                if status >= 400:
                    msg = body
                    if isinstance(body, dict):
                        msg = (body.get("error") or {}).get("message") or body
                    LOGGER.warning("chatbot_chat: fallback %s returned %d — %s", fallback["name"], status, msg)
                    last_status = status
                    last_body = msg
                    # Mark as failed if it's a balance/credentials error
                    err_str = str(msg).lower()
                    if "402" in err_str or "429" in err_str or "quota" in err_str or "exceeded" in err_str or "balance" in err_str or "401" in err_str or "403" in err_str or "unauthorized" in err_str:
                        try:
                            from utils.translation import mark_provider_failed
                            mark_provider_failed(fallback["name"], str(msg))
                        except Exception:
                            pass
                    continue
                else:
                    success = True
                    payload = fb_payload
                    break
            except Exception as exc:
                LOGGER.warning("chatbot_chat: fallback %s failed — %s", fallback["name"], exc)
                last_body = f"{fallback['name']} error: {exc}"
                continue

        if not success:
            return jsonify({"ok": False, "status": last_status, "error": last_body}), 502

    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "invalid_response", "raw": body}), 502

    choice = (body.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    return jsonify({
        "ok": True,
        "model": body.get("model") or payload["model"],
        "requested_model": payload["model"],
        "routing": route,
        "content": content,
        "finish_reason": choice.get("finish_reason", ""),
        "usage": body.get("usage") or {},
    })


# ─── Chat (SSE streaming) ─────────────────────────────────────────────────
@bp.route("/api/chatbot/chat_stream", methods=["POST"])
def chatbot_chat_stream():
    """Forward the upstream SSE stream from 9Router straight to the browser.
    Falls back to direct provider calls (DeepSeek/Gemini/OpenAI/Groq) when
    9Router is offline.
    """
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]

    nr = _nine_router_cfg()
    cfg = load_cfg()
    api_key = (nr.get("api_key") or "").strip()
    payload, route = _build_chat_payload(data, nr, stream=True)
    url = f"{nr['endpoint'].rstrip('/')}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        import requests as _requests_lib  # type: ignore
    except Exception as exc:  # pragma: no cover - requirements.txt has it
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    # ── Try 9Router first ──
    upstream = None
    nine_router_failed = False
    try:
        upstream = _requests_lib.post(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            stream=True,
            timeout=(_LIGHT_TIMEOUT, None),
        )
        if upstream.status_code >= 400:
            try:
                _9r_err = upstream.text[:200]
            except Exception:
                _9r_err = ""
            LOGGER.warning("chatbot_chat_stream: 9Router returned %d — %s",
                           upstream.status_code, _9r_err)
            upstream.close()
            upstream = None
            nine_router_failed = True
    except Exception as exc:
        LOGGER.warning("chatbot_chat_stream: 9Router unreachable — %s", exc)
        nine_router_failed = True

    # ── Fallback to direct provider if 9Router failed ──
    if nine_router_failed:
        try:
            from utils.translation import load_api_keys_status
            api_status = load_api_keys_status()
        except Exception:
            api_status = {}

        fallbacks = []
        for prov in _FALLBACK_PROVIDERS:
            # Skip if marked as failed/inactive
            if api_status.get(prov["name"], {}).get("ok") is False:
                continue
            key = _get_cfg_key(cfg, prov["key_path"])
            if key:
                fallbacks.append({
                    "name": prov["name"],
                    "endpoint": prov["endpoint"],
                    "model": prov["model"],
                    "api_key": key
                })

        # Prioritize model hint
        model_hint = payload.get("model", "")
        if model_hint:
            hint_lower = model_hint.lower()
            for idx, fb in enumerate(fallbacks):
                if (fb["model"].lower() == hint_lower
                        or fb["name"] in hint_lower
                        or hint_lower.startswith(fb["name"])):
                    fallbacks.insert(0, fallbacks.pop(idx))
                    fb["model"] = model_hint
                    break

        if not fallbacks:
            def _no_provider_stream():
                yield f"event: error\ndata: {json.dumps({'status': 502, 'body': '9Router offline. Không có provider fallback nào hoạt động.'})}\n\n"
            return Response(stream_with_context(_no_provider_stream()),
                            mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache"})

        success = False
        last_err_status = 502
        last_err_body = "Tất cả các fallback providers đều thất bại."

        for fallback in fallbacks:
            LOGGER.info("chatbot_chat_stream: trying fallback to %s (model: %s)",
                        fallback["name"], fallback["model"])
            fb_headers = {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {fallback['api_key']}",
            }
            fb_payload = dict(payload)
            fb_payload["model"] = fallback["model"]
            fb_payload["stream"] = True
            route = {"mode": "fallback", "tier": "direct",
                     "reason": f"9Router offline/error → {fallback['name']}"}

            try:
                upstream = _requests_lib.post(
                    fallback["endpoint"],
                    data=json.dumps(fb_payload).encode("utf-8"),
                    headers=fb_headers,
                    stream=True,
                    timeout=(_LIGHT_TIMEOUT, None),
                )
                if upstream.status_code >= 400:
                    try:
                        err_body = upstream.text
                    except Exception:
                        err_body = ""
                    LOGGER.warning("chatbot_chat_stream: fallback %s returned %d — %s",
                                   fallback["name"], upstream.status_code, err_body[:200])
                    last_err_status = upstream.status_code
                    last_err_body = f"{fallback['name']}: {err_body}"
                    # Mark as failed if it's a balance/credentials error
                    err_str = str(err_body).lower()
                    if "402" in err_str or "429" in err_str or "quota" in err_str or "exceeded" in err_str or "balance" in err_str or "401" in err_str or "403" in err_str or "unauthorized" in err_str:
                        try:
                            from utils.translation import mark_provider_failed
                            mark_provider_failed(fallback["name"], str(err_body))
                        except Exception:
                            pass
                    upstream.close()
                    upstream = None
                    continue
                else:
                    success = True
                    payload = fb_payload
                    break
            except Exception as exc:
                LOGGER.warning("chatbot_chat_stream: fallback %s failed — %s", fallback["name"], exc)
                last_err_body = f"{fallback['name']} error: {exc}"
                upstream = None
                continue

        if not success:
            def _fb_status_err_stream():
                yield f"event: error\ndata: {json.dumps({'status': last_err_status, 'body': last_err_body})}\n\n"
            return Response(stream_with_context(_fb_status_err_stream()),
                            mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache"})

        # Update payload reference for passthrough metadata
        payload = fb_payload

    def _passthrough():
        try:
            meta = {"requested_model": payload["model"], "routing": route}
            yield (f"event: route\ndata: {json.dumps(meta)}\n\n").encode("utf-8")

            # Synthetic ack message representing the first-phase agent reading the prompt
            ack_msg = "Tôi đã đọc yêu cầu của bạn, tôi sẽ phản hồi ngay bây giờ..."
            last_text = _last_user_text(payload.get("messages") or [])
            last_text_l = last_text.lower()
            if any(kw in last_text_l for kw in ("thơ", "poetry", "vè", "lục bát", "song thất", "thơ ca", "tho")):
                ack_msg = "Tôi đã đọc yêu cầu của bạn, tôi sẽ tạo bài thơ ngay bây giờ..."
            elif any(kw in last_text_l for kw in _CODE_KEYWORDS):
                ack_msg = "Tôi đã đọc yêu cầu của bạn, tôi sẽ viết code ngay bây giờ..."
            elif any(kw in last_text_l for kw in _WEB_KEYWORDS) or (route.get("tier") == "web"):
                ack_msg = "Tôi đã đọc yêu cầu của bạn. Đang tìm kiếm thông tin mới nhất và phản hồi ngay bây giờ..."
            
            ack_data = {"message": ack_msg}
            yield (f"event: ack\ndata: {json.dumps(ack_data)}\n\n").encode("utf-8")

            for chunk in upstream.iter_content(chunk_size=None, decode_unicode=False):
                if chunk:
                    yield chunk
        finally:
            try:
                upstream.close()
            except Exception:
                pass

    return Response(
        stream_with_context(_passthrough()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
        direct_passthrough=True,
    )


# ─── Quick test ───────────────────────────────────────────────────────────
@bp.route("/api/chatbot/test", methods=["POST"])
def chatbot_test():
    data = request.json or {}
    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()

    payload = {
        "model": (data.get("model") or nr["default_model"]).strip(),
        "messages": [{"role": "user", "content": "Reply with the single word: PONG"}],
        "max_tokens": 10,
        "temperature": 0,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{nr['endpoint'].rstrip('/')}/chat/completions"

    t0 = time.time()
    try:
        status, body = _http_json(url, method="POST", headers=headers, payload=payload, timeout=6)
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    elapsed_ms = int((time.time() - t0) * 1000)

    if status >= 400:
        msg = body
        if isinstance(body, dict):
            msg = (body.get("error") or {}).get("message") or body
        return jsonify({"ok": False, "status": status, "error": msg, "elapsed_ms": elapsed_ms}), 502

    content = ""
    actual_model = payload["model"]
    if isinstance(body, dict):
        actual_model = body.get("model") or actual_model
        content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    return jsonify({
        "ok": True,
        "content": content,
        "model": actual_model,
        "elapsed_ms": elapsed_ms,
    })


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

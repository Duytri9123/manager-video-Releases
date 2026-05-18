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
_DEFAULT_MODEL = "duytris"  # combo present in default 9Router installs
_CLI_TOKEN_HEADER = "x-9r-cli-token"
_CLI_TOKEN_SALT = "9r-cli-auth"
_MACHINE_ID_SALT_DEFAULT = "endpoint-proxy-salt"

_LIGHT_TIMEOUT = 6     # /api/health, /api/settings, /api/keys
_MODELS_TIMEOUT = 12   # /v1/models can be slow if upstream lookups
_DEFAULT_TIMEOUT = 120 # /v1/chat/completions

# ── Local DB cache for the CLI token so we don't shell out every request ──
_cli_token_cache: Optional[str] = None


# ─── Machine ID helpers (mirror node-machine-id used by 9Router) ──────────
def _read_windows_machine_guid() -> Optional[str]:
    """Return the lowercase MachineGuid from HKLM\\SOFTWARE\\Microsoft\\Cryptography."""
    try:
        out = subprocess.check_output(
            ["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"],
            text=True, stderr=subprocess.DEVNULL, timeout=4,
        )
    except Exception:
        return None
    for line in out.splitlines():
        if "MachineGuid" in line:
            parts = line.strip().split()
            if parts:
                return parts[-1].strip().lower()
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
    return jsonify({
        "ok": True,
        "endpoint": nr["endpoint"],
        "default_model": nr["default_model"],
        "has_key": bool((nr.get("api_key") or "").strip()),
        "masked_key": _mask_key(nr.get("api_key") or "") if nr.get("api_key") else "",
    })


# ─── Status / discovery ───────────────────────────────────────────────────
@bp.route("/api/chatbot/status", methods=["GET"])
def chatbot_status():
    """Tell the UI whether 9Router is up, whether it requires a key, and
    whether we already have a usable key cached.

    Returns:
      { ok, reachable, version, require_api_key, has_key, masked_key,
        endpoint, has_cli_token, settings: {rtk, caveman, ...} }
    """
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

    return jsonify({
        "ok": True,
        "endpoint": endpoint,
        "reachable": reachable,
        "version": version,
        "require_api_key": require_api_key,
        "settings_ok": settings_ok,
        "settings": settings_subset,
        "has_key": bool((nr.get("api_key") or "").strip()),
        "masked_key": _mask_key(nr.get("api_key") or "") if nr.get("api_key") else "",
        "has_cli_token": bool(_cli_token()),
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

    Body:
      prompt (str, required)
      model (str, optional)            — default: first image model on the install
      n     (int, default 1)
      size  (str, optional)            — "1024x1024" etc.
      response_format ("url" | "b64_json")
    """
    data = request.json or {}
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "error": "prompt required"}), 400

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: Dict[str, Any] = {
        "prompt": prompt,
        "model": (data.get("model") or "").strip() or "openai/dall-e-3",
        "n": int(data.get("n") or 1),
        "response_format": (data.get("response_format") or "url"),
    }
    if data.get("size"):
        payload["size"] = str(data["size"])
    if data.get("quality"):
        payload["quality"] = str(data["quality"])
    if data.get("style"):
        payload["style"] = str(data["style"])

    url = f"{nr['endpoint'].rstrip('/')}/images/generations"
    try:
        status, body = _http_json(url, method="POST", headers=headers,
                                  payload=payload, timeout=180)
    except Exception as exc:
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502
    if status >= 400:
        msg = body
        if isinstance(body, dict):
            msg = (body.get("error") or {}).get("message") or body
        return jsonify({"ok": False, "status": status, "error": msg}), 502
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "invalid_response", "raw": body}), 502

    items = body.get("data") or []
    return jsonify({
        "ok": True,
        "model": payload["model"],
        "images": items,           # [{url} | {b64_json}]
        "raw": {"created": body.get("created"), "model": body.get("model")},
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
    if data.get("format"):
        payload["response_format"] = str(data["format"])
    if data.get("language"):
        payload["language"] = str(data["language"])

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{nr['endpoint'].rstrip('/')}/audio/speech"
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
    """Proxy `GET /v1/models` — public on 9Router (no auth needed)."""
    nr = _nine_router_cfg()
    headers = {"Accept": "application/json"}
    if (nr.get("api_key") or "").strip():
        headers["Authorization"] = f"Bearer {nr['api_key']}"

    url = f"{nr['endpoint'].rstrip('/')}/models"
    try:
        status, body = _http_json(url, method="GET", headers=headers, timeout=_MODELS_TIMEOUT)
    except Exception as exc:
        LOGGER.warning("chatbot_models: cannot reach %s — %s", url, exc)
        return jsonify({
            "ok": False, "error": "unreachable", "message": str(exc),
            "hint": "Bật 9Router (Start Server) hoặc kiểm tra endpoint.",
        }), 502

    if status >= 400:
        msg = body if isinstance(body, str) else (
            (body.get("error") or {}).get("message") if isinstance(body, dict) else str(body)
        )
        return jsonify({"ok": False, "status": status, "error": msg or "upstream_error"}), 502

    items = []
    if isinstance(body, dict):
        for it in body.get("data") or []:
            mid = (it or {}).get("id")
            if mid:
                items.append({"id": mid, "owned_by": (it or {}).get("owned_by", "")})

    return jsonify({"ok": True, "models": items, "default": nr["default_model"]})


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
    # programming / engineering
    "code", "debug", "refactor", "algorithm", "architecture", "optimi",
    "regression", "performance", "concurrency", "async", "race condition",
    "memory leak", "stack trace", "exception",
    # math / reasoning
    "prove", "derive", "calculate", "equation", "theorem",
    # long-form
    "essay", "summary of", "translate this article", "kế hoạch", "phân tích",
    "viết kịch bản", "viết bài", "soạn bài",
    # multi-step
    "step by step", "plan", "outline", "design",
)
_FAST_KEYWORDS = (
    # greetings / pleasantries — never need a heavy model.
    "hi", "hello", "hey", "yo", "ping", "test",
    "chào", "xin chào", "alo", "hí",
    # one-shot lookups
    "what is", "định nghĩa", "viết tắt",
)


def _classify_complexity(messages: list, thresholds: Dict[str, Any]) -> Tuple[str, str]:
    """Return (tier_name, reason) based on the trailing user turn + history.

    Heuristic order (first hit wins):
      1. very short prompt + small history  → fast
      2. very long prompt OR power keyword  → power
      3. enough back-and-forth in session   → balanced
      4. fallback                           → balanced
    """
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


def _resolve_routed_model(
    data: Dict[str, Any], nr: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    """Decide which model to send upstream and return ({model}, {meta}).

    Priority:
      1. Explicit `model` in the request body — always wins.
      2. `routing.mode == "auto"` — classify and pick the tier model.
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
    if not model:
        # Tier missing in config → fall back to default but keep the reasoning trail.
        return nr["default_model"], {
            "mode": "auto", "tier": tier, "reason": reason + " (tier model trống → default)",
        }
    return model, {"mode": "auto", "tier": tier, "reason": reason}


def _build_chat_payload(data: Dict[str, Any], nr: Dict[str, Any], stream: bool) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build the upstream payload + return routing metadata for logging/UI."""
    messages = list(data.get("messages") or [])
    sys_prompt = (nr.get("system_prompt") or "").strip()
    if sys_prompt and not any(m.get("role") == "system" for m in messages):
        messages = [{"role": "system", "content": sys_prompt}, *messages]

    model, route_meta = _resolve_routed_model(data, nr)
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
    api_key = (nr.get("api_key") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload, route = _build_chat_payload(data, nr, stream=False)
    url = f"{nr['endpoint'].rstrip('/')}/chat/completions"

    try:
        status, body = _http_json(url, method="POST", headers=headers, payload=payload)
    except Exception as exc:
        LOGGER.warning("chatbot_chat: cannot reach %s — %s", url, exc)
        return jsonify({"ok": False, "error": "unreachable", "message": str(exc)}), 502

    if status >= 400:
        msg = body
        if isinstance(body, dict):
            msg = (body.get("error") or {}).get("message") or body
        # 401 from 9Router → tell user it likely needs a key
        if status == 401:
            return jsonify({
                "ok": False, "status": status,
                "error": "missing_or_invalid_api_key",
                "message": str(msg or "Missing API key"),
                "hint": "Mở tab 9Router → ấn 'Tự động lấy key' để cấp & lưu key.",
            }), 401
        return jsonify({"ok": False, "status": status, "error": msg, "raw": body}), 502

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

    Why a passthrough instead of a fetch in the browser? Because the API key
    lives in config.yml — we don't want it leaking into JS at all.
    """
    data = request.json or {}
    err = _ensure_messages(data)
    if err:
        return jsonify(err[1]), err[0]

    nr = _nine_router_cfg()
    api_key = (nr.get("api_key") or "").strip()
    payload, route = _build_chat_payload(data, nr, stream=True)
    url = f"{nr['endpoint'].rstrip('/')}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Use `requests` with stream=True so each upstream chunk is yielded the
    # moment it arrives. urllib's HTTPResponse.read(n) buffers until `n`
    # bytes are available, which collapses 9Router's per-token chunks into
    # one big payload at [DONE] — the chat bubble would stay empty until
    # the very end. requests.iter_content honours the upstream framing.
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover - requirements.txt has it
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    try:
        upstream = requests.post(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            stream=True,
            # (connect, read) timeouts — read=None means wait forever between
            # chunks (reasoning models can think 30+ seconds before first byte).
            timeout=(_LIGHT_TIMEOUT, None),
        )
    except Exception as exc:
        LOGGER.warning("chatbot_chat_stream: cannot reach %s — %s", url, exc)
        def _conn_err_stream():
            yield f"event: error\ndata: {json.dumps({'status': 502, 'body': str(exc)})}\n\n"
        return Response(stream_with_context(_conn_err_stream()),
                        mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    if upstream.status_code >= 400:
        try:
            err_body = upstream.text
        except Exception:
            err_body = ""
        upstream.close()
        def _err_stream():
            yield f"event: error\ndata: {json.dumps({'status': upstream.status_code, 'body': err_body})}\n\n"
        return Response(stream_with_context(_err_stream()),
                        mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache"})

    def _passthrough():
        try:
            # Prepend a synthetic SSE event so the UI can show "routed →
            # tier X" before the real upstream chunks arrive. Falls outside
            # the OpenAI schema but lives under a custom `event:` name so
            # well-behaved clients can ignore it.
            meta = {"requested_model": payload["model"], "routing": route}
            yield (f"event: route\ndata: {json.dumps(meta)}\n\n").encode("utf-8")

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
            "X-Accel-Buffering": "no",  # disable nginx/etc buffering when reverse-proxied
            "Connection": "keep-alive",
        },
        direct_passthrough=True,  # don't let Werkzeug rebuffer the iterator
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
        status, body = _http_json(url, method="POST", headers=headers, payload=payload, timeout=30)
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

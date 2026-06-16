"""Flask app factory — creates the app and registers all blueprints.

Defensive registration: each blueprint import/register is wrapped so a
single broken module doesn't take down the whole app. Failures are logged
with full traceback. The list of successfully-registered blueprints is
exposed via `/api/_routes` for quick debugging from the browser.
"""
from __future__ import annotations

import importlib
import time
import traceback
from datetime import datetime
from typing import List, Tuple

from flask import jsonify, request

from core_app import LOGGER, STATE_DIR, app, socketio


# (module_path, blueprint_attr, friendly_name)
_BLUEPRINTS: List[Tuple[str, str, str]] = [
    ("routes.pages",      "bp", "pages"),
    ("routes.queue",      "bp", "queue"),
    ("routes.user",       "bp", "user"),
    ("routes.download",   "bp", "download"),
    ("routes.translate",  "bp", "translate"),
    ("routes.tts",        "bp", "tts"),
    ("routes.transcribe", "bp", "transcribe"),
    ("routes.process",    "bp", "process"),
    ("routes.youtube",    "bp", "youtube"),
    ("routes.config",     "bp", "config"),
    ("routes.content",    "bp", "content"),
    ("routes.facebook",   "bp", "facebook"),
    ("routes.accounts",   "bp", "accounts"),
    ("routes.tiktok",     "bp", "tiktok"),
    # New blueprints (proxies/routers/movie/story)
    ("routes.proxies",    "bp", "proxies"),
    ("routes.movie",      "bp", "movie"),
    ("routes.story",      "bp", "story"),
    ("routes.chatbot",    "bp", "chatbot"),
    ("routes.videogen",   "bp", "videogen"),
    ("routes.idea2video", "bp", "idea2video"),
    ("routes.ai_studio",  "bp", "ai_studio"),
    ("routes.n8n",        "bp", "n8n"),
    ("routes.sales",      "bp", "sales"),
    ("routes.ads",        "bp", "ads"),
]

_REGISTERED: List[str] = []
_FAILED: List[Tuple[str, str]] = []


def _register_safe(module_path: str, attr: str, name: str) -> bool:
    try:
        mod = importlib.import_module(module_path)
        bp = getattr(mod, attr, None)
        if bp is None:
            raise AttributeError(f"{module_path} has no attribute '{attr}'")
        app.register_blueprint(bp)
        _REGISTERED.append(name)
        return True
    except Exception as exc:
        tb = traceback.format_exc()
        LOGGER.error("Failed to register blueprint '%s' (%s): %s\n%s",
                     name, module_path, exc, tb)
        _FAILED.append((name, f"{type(exc).__name__}: {exc}"))
        return False


def create_app():
    """Register all blueprints and SocketIO handlers, return the app."""
    boot_started = time.time()

    for mod_path, attr, name in _BLUEPRINTS:
        _register_safe(mod_path, attr, name)

    # SocketIO handlers (only register if download blueprint loaded successfully)
    if "download" in _REGISTERED:
        try:
            from routes.download import register_socketio_handlers
            register_socketio_handlers()
        except Exception as exc:
            LOGGER.error("Failed to register socket.io handlers: %s", exc)

    # Web app authentication: removed — open access, no login gate.

    # Floating chat widget — SQLite-backed session/message store.
    try:
        from core import chat_store
        chat_store.init(STATE_DIR / "chat_history.db")
        LOGGER.info("chat_store initialized at %s", STATE_DIR / "chat_history.db")
    except Exception as exc:
        LOGGER.warning("chat_store init failed (widget will fall back to localStorage): %s", exc)

    # Bootstrap password from env: removed (auth disabled).

    # ── JSON 404 for API routes (no more HTML 404 leaking into the UI) ──
    @app.errorhandler(404)
    def _api_404(err):
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": "not_found",
                "path": request.path,
                "method": request.method,
                "hint": "Endpoint không tồn tại trên server hiện tại. "
                        "Hãy chắc chắn bạn đã restart server (kill mọi tiến trình "
                        "python.exe cũ rồi chạy lại).",
                "registered_blueprints": list(_REGISTERED),
            }), 404
        return err

    # ── Version / Auto-update endpoint ──
    @app.route("/api/version")
    def _api_version():
        try:
            from utils.auto_updater import CURRENT_VERSION, fetch_update_info
            info = fetch_update_info(timeout=5.0)
            if info:
                return jsonify(info.to_dict())
            return jsonify({
                "current_version": CURRENT_VERSION,
                "latest_version": None,
                "download_url": None,
                "message": None,
                "update_available": False,
                "error": "Không thể kiểm tra cập nhật (có thể do mạng)",
            })
        except Exception as e:
            from utils.auto_updater import CURRENT_VERSION
            return jsonify({
                "current_version": CURRENT_VERSION,
                "latest_version": None,
                "download_url": None,
                "message": None,
                "update_available": False,
                "error": str(e),
            })

    # ── Debug endpoint: list currently-registered routes ──
    # Public so you can curl it without authenticating; paths only, no params.
    @app.route("/api/_routes")
    def _list_routes():
        rules = sorted(set(r.rule for r in app.url_map.iter_rules()))
        return jsonify({
            "ok": True,
            "boot_time": int(boot_started),
            "boot_time_iso": datetime.fromtimestamp(boot_started).isoformat(timespec="seconds"),
            "registered_blueprints": _REGISTERED,
            "failed_blueprints": [{"name": n, "error": e} for n, e in _FAILED],
            "routes_count": len(rules),
            "routes": rules,
        })

    # Make the auth gate skip the debug routes too: no-op (auth removed).

    # Boot summary
    elapsed = (time.time() - boot_started) * 1000
    LOGGER.info(
        "App ready in %dms — %d blueprints OK%s",
        elapsed,
        len(_REGISTERED),
        f", {len(_FAILED)} failed" if _FAILED else "",
    )
    if _FAILED:
        for n, e in _FAILED:
            LOGGER.warning("  ✗ %s — %s", n, e)

    return app

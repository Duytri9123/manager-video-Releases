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
    ("templates.pages.pages_route",      "bp", "pages"),
    ("templates.pages.download.queue",      "bp", "queue"),
    ("templates.pages.user.route",       "bp", "user"),
    ("templates.pages.download.route",   "bp", "download"),
    ("templates.pages.transcribe.translate",  "bp", "translate"),
    ("templates.pages.transcribe.tts",        "bp", "tts"),
    ("templates.pages.transcribe.route", "bp", "transcribe"),
    ("templates.pages.process.route",    "bp", "process"),
    ("templates.pages.publish.youtube",    "bp", "youtube"),
    ("templates.pages.config.route",     "bp", "config"),
    ("templates.pages.content.route",    "bp", "content"),
    ("templates.pages.publish.facebook",   "bp", "facebook"),
    ("templates.pages.publish.accounts",   "bp", "accounts"),
    ("templates.pages.publish.tiktok",     "bp", "tiktok"),
    # New blueprints (proxies/routers/movie/story)
    ("templates.pages.proxies.route",    "bp", "proxies"),
    ("templates.pages.movie.route",      "bp", "movie"),
    ("templates.pages.story.route",      "bp", "story"),
    ("templates.pages.chat.route",    "bp", "chatbot"),
    ("templates.pages.videogen.route",   "bp", "videogen"),
    ("templates.pages.idea2video.route", "bp", "idea2video"),
    ("templates.pages.ai_studio.route",  "bp", "ai_studio"),
    ("templates.pages.n8n.route",        "bp", "n8n"),
    ("templates.pages.sales.route",      "bp", "sales"),
    ("templates.pages.ads.route",        "bp", "ads"),
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

    # Initialize licensing gateway + guard thread
    try:
        from utils.licensing_routes import init_licensing_app
        init_licensing_app(app)
        LOGGER.info("Licensing guard system initialized successfully.")
    except Exception as exc:
        LOGGER.error("Failed to initialize licensing system: %s", exc)
        traceback.print_exc()

    # SocketIO handlers (only register if download blueprint loaded successfully)
    if "download" in _REGISTERED:
        try:
            from templates.pages.download.route import register_socketio_handlers
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

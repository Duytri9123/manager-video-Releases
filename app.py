#!/usr/bin/env python3
"""DuyTris Downloader — Flask entry point.

Bind defaults:
  • host = FLASK_HOST or 127.0.0.1 (set 0.0.0.0 explicitly to expose on LAN)
  • port = FLASK_PORT or 5000
"""
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from extensions import create_app
from core_app import socketio

app = create_app()

if __name__ == "__main__":
    import webbrowser
    from core_app import _start_ngrok_tunnel
    import core_app as _ca

    APP_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    APP_PORT = int(os.getenv("FLASK_PORT", "5000"))
    OPEN_BROWSER = os.getenv("OPEN_BROWSER", "1") not in ("0", "false", "no")

    _start_ngrok_tunnel(APP_PORT)
    if _ca._NGROK_PUBLIC_URL:
        print(f"[ngrok] Public URL: {_ca._NGROK_PUBLIC_URL}")
    elif _ca._NGROK_ERROR:
        print(f"[ngrok] Error: {_ca._NGROK_ERROR}")

    # Preload whisper model in background
    try:
        from templates.pages.process.route import _preload_whisper_model
        threading.Thread(target=_preload_whisper_model, daemon=True).start()
    except Exception:
        pass

    if OPEN_BROWSER and APP_HOST in ("127.0.0.1", "localhost"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{APP_PORT}")).start()
    socketio.run(app, host=APP_HOST, port=APP_PORT, debug=False, allow_unsafe_werkzeug=True)

#!/usr/bin/env python3
"""
DuyTris Downloader — Flask launcher (LAN-friendly).

Usage:
  py run_flask.py
  FLASK_HOST=0.0.0.0 py run_flask.py    # share on LAN
"""
import os
import socket
import sys
import threading
from pathlib import Path

# Fix Unicode/emoji output on Windows consoles (cp1252 → utf-8)
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from extensions import create_app
from core_app import LOGGER, load_cfg, socketio

app = create_app()


def _get_local_ip() -> str:
    """Return the machine's outbound LAN IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    import webbrowser
    from core_app import _start_ngrok_tunnel
    import core_app as _ca

    HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    PORT = int(os.getenv("FLASK_PORT", "9123"))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    OPEN_BROWSER = os.getenv("OPEN_BROWSER", "1") not in ("0", "false", "no")

    _start_ngrok_tunnel(PORT)

    if _ca._NGROK_PUBLIC_URL:
        print(f"[ngrok] Public URL: {_ca._NGROK_PUBLIC_URL}")
    elif _ca._NGROK_ERROR:
        print(f"[ngrok] Error: {_ca._NGROK_ERROR}")

    # Preload whisper model in background
    try:
        from core_app import _preload_whisper_model
        threading.Thread(target=_preload_whisper_model, daemon=True).start()
    except Exception:
        pass

    local_ip = _get_local_ip()
    local_url = f"http://localhost:{PORT}"
    lan_url = f"http://{local_ip}:{PORT}"

    print(f"\n{'=' * 55}")
    print(f"  🎬 DuyTris Downloader")
    print(f"  Local:   {local_url}")
    if HOST in ("0.0.0.0", "::"):
        print(f"  LAN:     {lan_url}  ← chia sẻ trong mạng nội bộ")
    if _ca._NGROK_PUBLIC_URL:
        print(f"  Public:  {_ca._NGROK_PUBLIC_URL}  ← chia sẻ internet")
    print(f"  Debug:   {DEBUG}")
    print(f"{'=' * 55}\n")

    if OPEN_BROWSER and HOST in ("127.0.0.1", "localhost"):
        threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()

    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)

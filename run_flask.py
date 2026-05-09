#!/usr/bin/env python3
"""
DuyTris Downloader — Flask launcher
Chạy: py run_flask.py
Chia sẻ LAN: FLASK_HOST=0.0.0.0 py run_flask.py
"""
import os
import sys
import socket
import threading
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from extensions import create_app
from core_app import socketio

app = create_app()

def _get_local_ip():
    """Lấy IP LAN của máy."""
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
    from core_app import _start_ngrok_tunnel, _NGROK_PUBLIC_URL, _NGROK_ERROR

    HOST = os.getenv("FLASK_HOST", "0.0.0.0")   # bind all interfaces để chia sẻ LAN
    PORT = int(os.getenv("FLASK_PORT", "5000"))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")

    _start_ngrok_tunnel(PORT)
    if _NGROK_PUBLIC_URL:
        print(f"[ngrok] Public URL: {_NGROK_PUBLIC_URL}")
    elif _NGROK_ERROR:
        print(f"[ngrok] Error: {_NGROK_ERROR}")

    # Preload whisper model in background
    try:
        from core_app import _preload_whisper_model
        threading.Thread(target=_preload_whisper_model, daemon=True).start()
    except Exception:
        pass

    local_ip = _get_local_ip()
    local_url = f"http://localhost:{PORT}"
    lan_url   = f"http://{local_ip}:{PORT}"

    print(f"\n{'='*55}")
    print(f"  🎬 DuyTris Downloader")
    print(f"  Local:   {local_url}")
    print(f"  LAN:     {lan_url}  ← chia sẻ trong mạng nội bộ")
    if _NGROK_PUBLIC_URL:
        print(f"  Public:  {_NGROK_PUBLIC_URL}  ← chia sẻ internet")
    print(f"  Debug: {DEBUG}")
    print(f"{'='*55}\n")

    threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)

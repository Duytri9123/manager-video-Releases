#!/usr/bin/env python3
"""PySide6 desktop launcher for the Flask UI.

The app is still served by Flask locally, but the user sees a real Qt
desktop window that embeds the existing web interface.
"""
from __future__ import annotations

import ctypes
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


APP_TITLE = "DuyTris Downloader"
HOST = "127.0.0.1"

# Auto-update check (runs in background on startup)
_AUTO_UPDATE_CHECK_DONE = False


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _app_dir()
STATE_DIR = APP_DIR / ".state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = STATE_DIR / "desktop_app.log"


def _patch_subprocess_no_console() -> None:
    """Hide child console windows spawned by ffmpeg/ffprobe and other CLIs.

    A windowed PySide/PyInstaller app has no parent console. On Windows, when it
    starts a console subsystem program such as ffmpeg.exe without special flags,
    Windows creates a separate black console window for that child process.
    """
    if os.name != "nt":
        return

    import subprocess

    if getattr(subprocess, "_duytris_no_console_patched", False):
        return

    original_popen = subprocess.Popen
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)

    def hidden_popen(*args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | create_no_window
        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
            kwargs["startupinfo"] = startupinfo
        startupinfo.dwFlags |= startf_use_show_window
        startupinfo.wShowWindow = sw_hide
        return original_popen(*args, **kwargs)

    subprocess.Popen = hidden_popen
    subprocess._duytris_no_console_patched = True


def _prepare_stdio() -> None:
    # Windowed PyInstaller apps may not have stdout/stderr. Keep logs available
    # in .state/desktop_app.log instead of crashing the logging setup.
    log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    if getattr(sys, "stdout", None) is None:
        sys.stdout = log
    if getattr(sys, "stderr", None) is None:
        sys.stderr = log


def _log(message: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def _message_box(message: str, title: str = APP_TITLE) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        _log(f"{title}: {message}")


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex((HOST, port)) != 0


def _choose_port() -> int:
    preferred = int(os.getenv("FLASK_PORT", "5000"))
    for port in range(preferred, preferred + 20):
        if _port_is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/_routes", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            time.sleep(0.5)
    return False


def _launch_app_window(url: str) -> int:
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(APP_TITLE)
    qt_app.setOrganizationName("DuyTris")

    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(str(STATE_DIR / "qt_cache"))
    profile.setPersistentStoragePath(str(STATE_DIR / "qt_storage"))

    window = QMainWindow()
    window.setWindowTitle(APP_TITLE)
    window.resize(1280, 820)

    icon_path = APP_DIR / "img" / "logo.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        qt_app.setWindowIcon(icon)
        window.setWindowIcon(icon)

    web = QWebEngineView(window)
    web.setUrl(QUrl(url))
    window.setCentralWidget(web)
    window.show()

    return qt_app.exec()


def _check_update_and_notify():
    """Check for updates in background and show MessageBox if found."""
    global _AUTO_UPDATE_CHECK_DONE
    if _AUTO_UPDATE_CHECK_DONE:
        return
    _AUTO_UPDATE_CHECK_DONE = True

    try:
        from utils.auto_updater import check_for_update, CURRENT_VERSION
        update = check_for_update(timeout=5.0)
        if update:
            msg = (
                f"Da co ban cap nhat moi: v{update.latest_version}\n"
                f"(Hien tai: v{CURRENT_VERSION})\n\n"
                f"{update.message}\n\n"
                f"Ban co muon tai ve ngay bay gio?"
            )
            # Show MessageBox on main thread
            result = ctypes.windll.user32.MessageBoxW(0, msg, "Cap nhat moi", 0x04)  # Yes/No
            if result == 6:  # Yes
                import webbrowser
                webbrowser.open(update.download_url)
    except Exception as e:
        _log(f"Update check failed: {e}")


def main() -> int:
    _prepare_stdio()
    os.chdir(APP_DIR)
    os.environ.setdefault("OPEN_BROWSER", "0")
    os.environ.setdefault("NGROK_ENABLED", "0")
    os.environ["FLASK_HOST"] = HOST

    port = _choose_port()
    os.environ["FLASK_PORT"] = str(port)
    url = f"http://{HOST}:{port}"
    _log(f"Starting desktop app at {url}")

    try:
        from extensions import create_app
        from core_app import socketio

        app = create_app()
        _patch_subprocess_no_console()

        def _run_server() -> None:
            socketio.run(
                app,
                host=HOST,
                port=port,
                debug=False,
                allow_unsafe_werkzeug=True,
                use_reloader=False,
            )

        thread = threading.Thread(target=_run_server, name="flask-server", daemon=True)
        thread.start()

        if not _wait_until_ready(url):
            raise RuntimeError(f"Server did not start at {url}")

        # Check for updates (background thread, non-blocking)
        threading.Thread(target=_check_update_and_notify, name="update-check", daemon=True).start()

        if os.getenv("DESKTOP_APP_NO_WINDOW") in ("1", "true", "yes"):
            while True:
                time.sleep(3600)

        return _launch_app_window(url)
    except Exception as exc:
        details = traceback.format_exc()
        _log(details)
        _message_box(f"Khong khoi dong duoc ung dung:\n{exc}\n\nLog: {LOG_FILE}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

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
    preferred = int(os.getenv("FLASK_PORT", "9123"))
    for port in range(preferred, preferred + 20):
        if _port_is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return int(s.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    # Try static file first for a fast check that bypasses license gate
    check_url = f"{url}/static/css/custom.css"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(check_url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            # Fallback to root path but allow redirect status codes (302) or any response
            try:
                class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None
                opener = urllib.request.build_opener(NoRedirectHandler)
                with opener.open(f"{url}/", timeout=2) as resp:
                    if resp.status in (200, 301, 302, 303, 307, 308):
                        return True
            except Exception:
                pass
            time.sleep(0.5)
    return False


LOADING_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {
    background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 50%, #f0fdf4 100%);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #0284c7;
    margin: 0;
    overflow: hidden;
  }
  .spinner {
    border: 4px solid rgba(2, 132, 199, 0.1);
    width: 60px;
    height: 60px;
    border-radius: 50%;
    border-left-color: #0ea5e9;
    animation: spin 1s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  }
  @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  h2 { margin-top: 24px; font-weight: 800; font-size: 24px; color: #0f172a; letter-spacing: -0.02em; }
  p { font-size: 13px; color: #64748b; margin-top: 8px; font-weight: 550; }
</style>
</head>
<body>
  <div class="spinner"></div>
  <h2>DuyTris Downloader</h2>
  <p>Đang khởi động hệ thống, vui lòng chờ trong giây lát...</p>
</body>
</html>
"""


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

    if os.name == "nt":
        import ctypes
        try:
            # Set AppUserModelID to show the taskbar icon correctly on Windows
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("duytris.downloader.desktop.v2")
        except Exception:
            pass

    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    # Enable GPU acceleration for a smooth UI experience
    if os.getenv("DISABLE_GPU_UI") == "1":
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

    # Import PySide6 immediately to open splash window
    from PySide6.QtCore import QUrl, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
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

    # Main layout setup
    central_widget = QWidget(window)
    layout = QVBoxLayout(central_widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # Top Navigation Bar (hidden by default)
    nav_bar = QWidget()
    nav_bar.setStyleSheet("background-color: #ffffff; border-bottom: 1px solid #e2e8f0; padding: 4px;")
    nav_bar_layout = QHBoxLayout(nav_bar)
    nav_bar_layout.setContentsMargins(12, 4, 12, 4)

    back_btn = QPushButton("◀ Quay lại ứng dụng")
    back_btn.setStyleSheet("""
        QPushButton {
            background-color: #0284c7;
            color: #ffffff;
            border: none;
            padding: 6px 14px;
            font-size: 13px;
            font-weight: bold;
            border-radius: 4px;
        }
        QPushButton:hover {
            background-color: #0369a1;
        }
        QPushButton:pressed {
            background-color: #075985;
        }
    """)

    info_label = QLabel("Đang mở trang thanh toán bảo mật bên thứ ba...")
    info_label.setStyleSheet("color: #64748b; font-size: 13px; font-weight: 550;")

    nav_bar_layout.addWidget(back_btn)
    nav_bar_layout.addSpacing(12)
    nav_bar_layout.addWidget(info_label)
    nav_bar_layout.addStretch()

    nav_bar.hide()

    web = QWebEngineView(window)
    # Load splash screen immediately!
    web.setHtml(LOADING_HTML)

    layout.addWidget(nav_bar)
    layout.addWidget(web)

    window.setCentralWidget(central_widget)
    window.show()

    # Connect signals
    def on_url_changed(qurl):
        current_url = qurl.toString()
        if current_url.startswith(url) or current_url.startswith("data:") or not current_url:
            nav_bar.hide()
        else:
            nav_bar.show()

    web.urlChanged.connect(on_url_changed)
    back_btn.clicked.connect(lambda: web.setUrl(QUrl(url)))

    # Start backend server in a background thread
    status = {"ready": False, "error": None}

    def start_backend() -> None:
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

            if _wait_until_ready(url):
                status["ready"] = True
            else:
                status["error"] = "Thoi gian khoi dong server Flask bi qua han."
        except Exception as exc:
            status["error"] = traceback.format_exc()

    # Launch server import and startup thread
    threading.Thread(target=start_backend, name="backend-initializer", daemon=True).start()

    # Setup timer to check server status in GUI main thread
    def check_status() -> None:
        if status["ready"]:
            timer.stop()
            web.setUrl(QUrl(url))
            # Run update check in background after loading app
            threading.Thread(target=_check_update_and_notify, name="update-check", daemon=True).start()
        elif status["error"] is not None:
            timer.stop()
            _log(status["error"])
            _message_box(f"Khong khoi dong duoc ung dung:\n{status['error']}")
            qt_app.quit()

    timer = QTimer()
    timer.timeout.connect(check_status)
    timer.start(100) # Check every 100ms

    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())




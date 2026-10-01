# -*- coding: utf-8 -*-
"""
DuyTris System Controller UI
Giao diện điều khiển hệ thống hiện đại, có tính năng Ghim (Always on Top),
bật/tắt toàn bộ hệ thống hoặc từng thành phần độc lập (Backend, Cloudflare Web Tunnel),
mở kết nối web, khay hệ thống (System Tray), và chế độ Widget thu nhỏ (Mini floating bar).
"""
from __future__ import annotations

import os
import sys
import time
import json
import ctypes
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QPoint, QSize,
    QPropertyAnimation, Property, QEasingCurve
)
from PySide6.QtGui import (
    QIcon, QFont, QColor, QPainter, QBrush, QPen,
    QCursor, QLinearGradient, QAction
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect
)

from tools.system_controller import (
    ROOT, LOCAL_URL, PUBLIC_DOMAIN, BACKEND_PORT,
    is_port_in_use, check_tunnel_running, test_public_url,
    start_backend, stop_backend, start_tunnel, stop_tunnel,
    start_all, stop_all, open_local_web, open_public_web, get_full_status
)

CONFIG_FILE = ROOT / "tools" / ".ui_state.json"
ICON_PATH = ROOT / "img" / "logo.png"


# ── ANIMATED TOGGLE SWITCH ────────────────────────────────────────────────
class ModernToggleSwitch(QWidget):
    """Công tắc gạt bật/tắt hoạt họa phong cách hiện đại."""
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(54, 28)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._thumb_position = 28.0 if checked else 4.0
        self._anim = QPropertyAnimation(self, b"thumb_position", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def get_thumb_position(self) -> float:
        return self._thumb_position

    def set_thumb_position(self, pos: float):
        self._thumb_position = pos
        self.update()

    thumb_position = Property(float, get_thumb_position, set_thumb_position)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit_signal: bool = False):
        if self._checked == checked:
            return
        self._checked = checked
        target = 28.0 if checked else 4.0
        self._anim.stop()
        self._anim.setStartValue(self._thumb_position)
        self._anim.setEndValue(target)
        self._anim.start()
        if emit_signal:
            self.toggled.emit(self._checked)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked, emit_signal=True)
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background track
        track_color = QColor("#10b981") if self._checked else QColor("#334155")
        border_color = QColor("#059669") if self._checked else QColor("#475569")

        p.setPen(QPen(border_color, 1))
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 14, 14)

        # Thumb
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(int(self._thumb_position), 4, 20, 20)
        p.end()


# ── ASYNC OPERATION WORKER THREAD ─────────────────────────────────────────
class AsyncActionWorker(QThread):
    """Luồng chạy ngầm để thực hiện các thao tác bật/tắt không làm đơ giao diện."""
    task_started = Signal(str)
    task_finished = Signal(str, bool, str)

    def __init__(self, action_name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.action_name = action_name

    def run(self):
        self.task_started.emit(self.action_name)
        ok, msg = False, "Unknown action"
        try:
            if self.action_name == "START_ALL":
                ok, msg = start_all()
            elif self.action_name == "STOP_ALL":
                ok, msg = stop_all()
            elif self.action_name == "START_BACKEND":
                ok, msg = start_backend()
            elif self.action_name == "STOP_BACKEND":
                ok, msg = stop_backend()
            elif self.action_name == "START_TUNNEL":
                ok, msg = start_tunnel()
            elif self.action_name == "STOP_TUNNEL":
                ok, msg = stop_tunnel()
        except Exception as e:
            ok = False
            msg = str(e)
        self.task_finished.emit(self.action_name, ok, msg)


# ── TOAST NOTIFICATION WIDGET ─────────────────────────────────────────────
class ToastNotification(QLabel):
    """Thông báo popup nhỏ gọn, tự động biến mất sau 2.5s."""
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet("""
            QLabel {
                background-color: #0284c7;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                border-radius: 8px;
                padding: 8px 16px;
                border: 1px solid #38bdf8;
            }
        """)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, message: str, is_error: bool = False):
        if is_error:
            self.setStyleSheet("""
                QLabel {
                    background-color: #e11d48;
                    color: #ffffff;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 8px;
                    padding: 8px 16px;
                    border: 1px solid #f43f5e;
                }
            """)
        else:
            self.setStyleSheet("""
                QLabel {
                    background-color: #0f766e;
                    color: #ffffff;
                    font-size: 12px;
                    font-weight: bold;
                    border-radius: 8px;
                    padding: 8px 16px;
                    border: 1px solid #2dd4bf;
                }
            """)
        self.setText(message)
        self.adjustSize()
        # Center horizontally at bottom
        if self.parent():
            x = (self.parent().width() - self.width()) // 2
            y = self.parent().height() - self.height() - 25
            self.move(max(10, x), max(10, y))
        self.show()
        self.raise_()
        self._timer.start(2500)


# ── MAIN CONTROLLER WINDOW ────────────────────────────────────────────────
class SystemControllerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DuyTris System Hub")
        self.setWindowIcon(QIcon(str(ICON_PATH))) if ICON_PATH.exists() else None

        # State flags
        self.is_pinned: bool = False
        self.is_mini: bool = False
        self.is_busy: bool = False
        self._drag_pos: Optional[QPoint] = None

        self.auto_connect: bool = True

        # Load saved settings
        self.load_config()

        # Window Appearance
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._init_ui()
        self._init_tray()

        # Apply restored state
        self.apply_pin_state(show_toast=False)
        self.apply_mode_state()
        self.update_auto_connect_ui()

        # Periodic status checker timer
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_status_async)
        self.status_timer.start(2000)

        # Initial fast check & Auto-Connect like AIDE_website
        QTimer.singleShot(400, self.initial_auto_connect)

    def initial_auto_connect(self):
        self.check_status_async()
        if getattr(self, "auto_connect", True):
            st = get_full_status()
            if not st["backend_running"] or not st["tunnel_running"]:
                self.log("⚡ [AIDE-Style] Tự động bật kết nối toàn bộ hệ thống & Web Tunnel...")
                self.show_toast("⚡ Đang tự động kết nối hệ thống & Web Tunnel...")
                self.run_async_action("START_ALL")

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.is_pinned = data.get("is_pinned", False)
                    self.is_mini = data.get("is_mini", False)
                    self.auto_connect = data.get("auto_connect", True)
                    x = data.get("x")
                    y = data.get("y")
                    if x is not None and y is not None:
                        self.move(int(x), int(y))
            except Exception:
                pass

    def save_config(self):
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "is_pinned": self.is_pinned,
                "is_mini": self.is_mini,
                "auto_connect": getattr(self, "auto_connect", True),
                "x": self.pos().x(),
                "y": self.pos().y(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _init_ui(self):
        # Central container with drop shadow & dark rounded styling
        self.central_widget = QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.root_layout = QVBoxLayout(self.central_widget)
        self.root_layout.setContentsMargins(10, 10, 10, 10)

        # Frame container
        self.frame = QFrame()
        self.frame.setObjectName("mainFrame")
        self.frame.setStyleSheet("""
            #mainFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f172a, stop:1 #1e293b);
                border: 1px solid #334155;
                border-radius: 14px;
            }
        """)

        # Drop shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 8)
        self.frame.setGraphicsEffect(shadow)

        self.root_layout.addWidget(self.frame)

        self.frame_layout = QVBoxLayout(self.frame)
        self.frame_layout.setContentsMargins(16, 14, 16, 16)
        self.frame_layout.setSpacing(12)

        # ── 1. HEADER BAR ───────────────────────────────────────
        self.header_widget = QWidget()
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # App title & dot
        self.title_label = QLabel("⚡ DUYTRIS SYSTEM HUB")
        self.title_label.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 800; letter-spacing: 0.5px;")

        self.badge_label = QLabel("v2.0")
        self.badge_label.setStyleSheet("""
            background-color: rgba(14, 165, 233, 0.2);
            color: #38bdf8;
            font-size: 11px;
            font-weight: 700;
            border-radius: 4px;
            padding: 2px 6px;
            border: 1px solid rgba(56, 189, 248, 0.3);
        """)

        # Pin Button
        self.pin_btn = QPushButton("📌 GHIM")
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setToolTip("Click để GHIM cửa sổ luôn nổi trên cùng màn hình")
        self.pin_btn.clicked.connect(self.toggle_pin)

        # Mode Button (Mini / Full)
        self.mode_btn = QPushButton("🗗 MINI")
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.setToolTip("Thu nhỏ thành thanh nổi Widget tiện lợi")
        self.mode_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        self.mode_btn.clicked.connect(self.toggle_mini_mode)

        # Minimize to tray button
        self.min_btn = QPushButton("➖")
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.setToolTip("Thu nhỏ vào khay hệ thống (System Tray)")
        self.min_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton:hover { color: #f8fafc; }
        """)
        self.min_btn.clicked.connect(self.hide_to_tray)

        # Close button
        self.close_btn = QPushButton("✕")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("Đóng ứng dụng")
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                font-size: 13px;
                font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton:hover { color: #f43f5e; }
        """)
        self.close_btn.clicked.connect(self.close)

        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.badge_label)
        header_layout.addStretch()
        header_layout.addWidget(self.pin_btn)
        header_layout.addWidget(self.mode_btn)
        header_layout.addWidget(self.min_btn)
        header_layout.addWidget(self.close_btn)

        self.frame_layout.addWidget(self.header_widget)

        # ── 2. FULL VIEW CONTAINER ──────────────────────────────
        self.full_container = QWidget()
        full_layout = QVBoxLayout(self.full_container)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_layout.setSpacing(12)

        # Master Hero Card
        self.hero_card = QFrame()
        self.hero_card.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 41, 59, 0.7);
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 12px;
            }
        """)
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(14, 12, 14, 12)
        hero_layout.setSpacing(10)

        hero_top = QHBoxLayout()
        self.master_status_dot = QLabel("●")
        self.master_status_dot.setStyleSheet("color: #ef4444; font-size: 18px;")
        self.master_status_text = QLabel("HỆ THỐNG ĐANG TẮT")
        self.master_status_text.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 800;")
        hero_top.addWidget(self.master_status_dot)
        hero_top.addWidget(self.master_status_text)
        hero_top.addStretch()

        self.master_btn = QPushButton("🚀 BẬT HỆ THỐNG & KẾT NỐI WEB")
        self.master_btn.setCursor(Qt.PointingHandCursor)
        self.master_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #0284c7);
                color: #ffffff;
                font-size: 14px;
                font-weight: 800;
                padding: 12px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #0ea5e9);
            }
            QPushButton:disabled {
                background-color: #475569;
                color: #94a3b8;
            }
        """)
        self.master_btn.clicked.connect(self.on_master_btn_clicked)

        self.hero_subtext = QLabel("Tự động kích hoạt Máy chủ Backend (9123) và kết nối Cloudflare Tunnel")
        self.hero_subtext.setStyleSheet("color: #94a3b8; font-size: 11px;")

        hero_layout.addLayout(hero_top)
        hero_layout.addWidget(self.master_btn)
        hero_layout.addWidget(self.hero_subtext)

        full_layout.addWidget(self.hero_card)

        # ── Unified Connection & Access Card ──
        self.connection_card = QFrame()
        self.connection_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 10px 14px;
            }
        """)
        conn_layout = QVBoxLayout(self.connection_card)
        conn_layout.setContentsMargins(12, 10, 12, 10)
        conn_layout.setSpacing(10)

        # Row 1: Web Online (Cloudflare Tunnel)
        row1 = QHBoxLayout()
        row1_info = QVBoxLayout()
        row1_title_row = QHBoxLayout()
        row1_title = QLabel("🌍 Web Trực Tuyến (Internet)")
        row1_title.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: bold;")
        self.web_status_badge = QLabel("CHƯA BẬT")
        self.web_status_badge.setStyleSheet("""
            background-color: rgba(239, 68, 68, 0.15);
            color: #f87171;
            font-size: 10px;
            font-weight: bold;
            border-radius: 4px;
            padding: 2px 6px;
            border: 1px solid rgba(239, 68, 68, 0.3);
        """)
        row1_title_row.addWidget(row1_title)
        row1_title_row.addWidget(self.web_status_badge)
        row1_title_row.addStretch()

        self.web_url_label = QLabel(PUBLIC_DOMAIN)
        self.web_url_label.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 550;")
        row1_info.addLayout(row1_title_row)
        row1_info.addWidget(self.web_url_label)

        self.open_public_btn = QPushButton("🔗 Mở Web")
        self.open_public_btn.setCursor(Qt.PointingHandCursor)
        self.open_public_btn.setToolTip("Mở trang web qua tên miền công khai Internet")
        self.open_public_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.open_public_btn.clicked.connect(open_public_web)

        self.copy_link_btn = QPushButton("📋")
        self.copy_link_btn.setCursor(Qt.PointingHandCursor)
        self.copy_link_btn.setToolTip("Sao chép liên kết Web Public vào clipboard")
        self.copy_link_btn.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.copy_link_btn.clicked.connect(self.copy_public_url)

        row1.addLayout(row1_info)
        row1.addStretch()
        row1.addWidget(self.open_public_btn)
        row1.addWidget(self.copy_link_btn)
        conn_layout.addLayout(row1)

        # Divider line
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: #334155; max-height: 1px;")
        conn_layout.addWidget(div)

        # Row 2: Local Web Server (127.0.0.1:9123)
        row2 = QHBoxLayout()
        row2_info = QVBoxLayout()
        row2_title_row = QHBoxLayout()
        row2_title = QLabel("🖥️ Máy Chủ Cục Bộ (Local)")
        row2_title.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: bold;")
        self.local_status_badge = QLabel("CHƯA BẬT")
        self.local_status_badge.setStyleSheet("""
            background-color: rgba(239, 68, 68, 0.15);
            color: #f87171;
            font-size: 10px;
            font-weight: bold;
            border-radius: 4px;
            padding: 2px 6px;
            border: 1px solid rgba(239, 68, 68, 0.3);
        """)
        row2_title_row.addWidget(row2_title)
        row2_title_row.addWidget(self.local_status_badge)
        row2_title_row.addStretch()

        self.local_url_label = QLabel(f"Cổng {BACKEND_PORT} | {LOCAL_URL}")
        self.local_url_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        row2_info.addLayout(row2_title_row)
        row2_info.addWidget(self.local_url_label)

        self.open_local_btn = QPushButton("🌐 Mở Local")
        self.open_local_btn.setCursor(Qt.PointingHandCursor)
        self.open_local_btn.setToolTip("Mở Web trên trình duyệt máy tính này")
        self.open_local_btn.setStyleSheet("""
            QPushButton {
                background-color: #0369a1;
                color: #ffffff;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover { background-color: #0284c7; }
        """)
        self.open_local_btn.clicked.connect(open_local_web)

        row2.addLayout(row2_info)
        row2.addStretch()
        row2.addWidget(self.open_local_btn)
        conn_layout.addLayout(row2)

        full_layout.addWidget(self.connection_card)

        # ── Quick Utility Bar ──
        quick_bar = QHBoxLayout()
        quick_bar.setSpacing(8)

        self.refresh_btn = QPushButton("🔄 Làm Mới")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        self.refresh_btn.clicked.connect(self.check_status_async)

        self.toggle_log_btn = QPushButton("📜 Nhật Ký")
        self.toggle_log_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #f8fafc;
            }
        """)
        self.toggle_log_btn.clicked.connect(self.toggle_log_box)

        self.auto_connect_btn = QPushButton("⚡ TỰ KẾT NỐI: BẬT")
        self.auto_connect_btn.setCursor(Qt.PointingHandCursor)
        self.auto_connect_btn.setToolTip("Tự động bật kết nối Backend + Web Tunnel khi mở Tool (giống AIDE_website)")
        self.auto_connect_btn.clicked.connect(self.toggle_auto_connect)

        quick_bar.addWidget(self.refresh_btn)
        quick_bar.addWidget(self.toggle_log_btn)
        quick_bar.addWidget(self.auto_connect_btn)
        quick_bar.addStretch()

        self.auto_refresh_label = QLabel("⚡ Tự động cập nhật 2s")
        self.auto_refresh_label.setStyleSheet("color: #64748b; font-size: 10px;")
        quick_bar.addWidget(self.auto_refresh_label)

        full_layout.addLayout(quick_bar)

        # ── Collapsible Log View ──
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(95)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background-color: #0b1120;
                color: #38bdf8;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        self.log_box.hide()
        full_layout.addWidget(self.log_box)

        self.frame_layout.addWidget(self.full_container)

        # ── 3. MINI VIEW CONTAINER ──────────────────────────────
        self.mini_container = QWidget()
        mini_layout = QHBoxLayout(self.mini_container)
        mini_layout.setContentsMargins(0, 4, 0, 0)
        mini_layout.setSpacing(10)

        # Mini status badges
        mini_status_col = QVBoxLayout()
        mini_status_col.setSpacing(3)
        self.mini_server_lbl = QLabel("🖥️ Máy chủ: 🔴")
        self.mini_server_lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: bold;")
        self.mini_web_lbl = QLabel("🌍 Web Tunnel: 🔴")
        self.mini_web_lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: bold;")
        mini_status_col.addWidget(self.mini_server_lbl)
        mini_status_col.addWidget(self.mini_web_lbl)

        # Mini Buttons
        self.mini_master_btn = QPushButton("⚡ Bật Hệ Thống")
        self.mini_master_btn.setCursor(Qt.PointingHandCursor)
        self.mini_master_btn.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        self.mini_master_btn.clicked.connect(self.on_master_btn_clicked)

        self.mini_web_btn = QPushButton("🌐 Mở Web")
        self.mini_web_btn.setCursor(Qt.PointingHandCursor)
        self.mini_web_btn.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #10b981; }
        """)
        self.mini_web_btn.clicked.connect(self.on_quick_open_web)

        mini_layout.addLayout(mini_status_col)
        mini_layout.addStretch()
        mini_layout.addWidget(self.mini_master_btn)
        mini_layout.addWidget(self.mini_web_btn)

        self.mini_container.hide()
        self.frame_layout.addWidget(self.mini_container)

        # Toast notification floating overlay
        self.toast = ToastNotification(self)

        self.log("🚀 DuyTris System Hub đã sẵn sàng.")

    def _init_tray(self):
        """Khởi tạo khay hệ thống (System Tray)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        if ICON_PATH.exists():
            self.tray_icon.setIcon(QIcon(str(ICON_PATH)))
        self.tray_icon.setToolTip("DuyTris System Hub")

        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
        """)

        act_show = QAction("🗗 Hiện Bảng Điều Khiển", self)
        act_show.triggered.connect(self.show_and_activate)
        tray_menu.addAction(act_show)

        tray_menu.addSeparator()

        act_start_all = QAction("🚀 Bật Toàn Bộ Hệ Thống", self)
        act_start_all.triggered.connect(lambda: self.run_async_action("START_ALL"))
        tray_menu.addAction(act_start_all)

        act_stop_all = QAction("🛑 Tắt Toàn Bộ Hệ Thống", self)
        act_stop_all.triggered.connect(lambda: self.run_async_action("STOP_ALL"))
        tray_menu.addAction(act_stop_all)

        tray_menu.addSeparator()

        act_open_local = QAction("🌐 Mở Web Local (Port 9123)", self)
        act_open_local.triggered.connect(open_local_web)
        tray_menu.addAction(act_open_local)

        act_open_public = QAction("🔗 Mở Web Public (Cloudflare)", self)
        act_open_public.triggered.connect(open_public_web)
        tray_menu.addAction(act_open_public)

        tray_menu.addSeparator()

        act_exit = QAction("❌ Thoát Hoàn Toàn", self)
        act_exit.triggered.connect(self.quit_app)
        tray_menu.addAction(act_exit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self.show_and_activate()

    def show_and_activate(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        self.hide()
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.tray_icon.showMessage(
                "DuyTris System Hub",
                "Ứng dụng đang chạy ngầm trong khay hệ thống.",
                QSystemTrayIcon.Information,
                2000
            )

    def quit_app(self):
        self.save_config()
        QApplication.quit()

    # ── PIN / ALWAYS ON TOP LOGIC ──────────────────────────────────────────
    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.apply_pin_state(show_toast=True)
        self.save_config()

    def apply_pin_state(self, show_toast: bool = True):
        """Áp dụng thuộc tính Ghim nổi không làm giật màn hình Windows."""
        hwnd = int(self.winId())
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE

        if self.is_pinned:
            try:
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            except Exception:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                self.show()

            self.pin_btn.setText("📌 ĐÃ GHIM")
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d97706, stop:1 #f59e0b);
                    color: #ffffff;
                    border: 1px solid #fbbf24;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 800;
                }
                QPushButton:hover {
                    background: #f59e0b;
                }
            """)
            self.pin_btn.setToolTip("Cửa sổ đang ĐƯỢC GHIM (luôn nổi trên các ứng dụng). Click để bỏ ghim.")
            if show_toast:
                self.show_toast("📌 Đã ghim cửa sổ luôn nổi trên cùng màn hình")
        else:
            try:
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            except Exception:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
                self.show()

            self.pin_btn.setText("📌 GHIM")
            self.pin_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #f8fafc;
                }
            """)
            self.pin_btn.setToolTip("Click để GHIM cửa sổ luôn nổi trên cùng màn hình")
            if show_toast:
                self.show_toast("Đã bỏ ghim cửa sổ")

    # ── MINI MODE TOGGLE ───────────────────────────────────────────────────
    def toggle_mini_mode(self):
        self.is_mini = not self.is_mini
        self.apply_mode_state()
        self.save_config()

    def apply_mode_state(self):
        if self.is_mini:
            self.full_container.hide()
            self.mini_container.show()
            self.mode_btn.setText("🗗 FULL")
            self.mode_btn.setToolTip("Mở rộng ra bảng điều khiển đầy đủ")
            self.setFixedSize(390, 115)
        else:
            self.mini_container.hide()
            self.full_container.show()
            self.mode_btn.setText("🗗 MINI")
            self.mode_btn.setToolTip("Thu nhỏ thành thanh nổi Widget tiện lợi")
            # Calculate height according to log_box visibility
            h = 520 if self.log_box.isVisible() else 435
            self.setFixedSize(425, h)

    def toggle_log_box(self):
        if self.log_box.isVisible():
            self.log_box.hide()
            self.toggle_log_btn.setText("📜 Nhật Ký")
        else:
            self.log_box.show()
            self.toggle_log_btn.setText("📜 Ẩn Nhật Ký")
        if not self.is_mini:
            h = 520 if self.log_box.isVisible() else 435
            self.setFixedSize(425, h)

    def toggle_auto_connect(self):
        self.auto_connect = not getattr(self, "auto_connect", True)
        self.update_auto_connect_ui()
        self.save_config()
        if self.auto_connect:
            self.show_toast("⚡ Đã BẬT tự động kết nối khi mở tool")
        else:
            self.show_toast("Đã TẮT tự động kết nối khi mở tool")

    def update_auto_connect_ui(self):
        if not hasattr(self, "auto_connect_btn"):
            return
        if getattr(self, "auto_connect", True):
            self.auto_connect_btn.setText("⚡ TỰ KẾT NỐI: BẬT")
            self.auto_connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(16, 185, 129, 0.2);
                    color: #34d399;
                    border: 1px solid rgba(16, 185, 129, 0.4);
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(16, 185, 129, 0.3);
                }
            """)
        else:
            self.auto_connect_btn.setText("⚡ TỰ KẾT NỐI: TẮT")
            self.auto_connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #64748b;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #334155;
                    color: #94a3b8;
                }
            """)

    def show_toast(self, text: str, is_error: bool = False):
        self.toast.show_message(text, is_error)

    def copy_public_url(self):
        cb = QApplication.clipboard()
        cb.setText(PUBLIC_DOMAIN)
        self.show_toast(f"📋 Đã sao chép: {PUBLIC_DOMAIN}")

    def on_quick_open_web(self):
        status = get_full_status()
        if status["tunnel_running"]:
            open_public_web()
        else:
            open_local_web()

    # ── LOG CONSOLE ────────────────────────────────────────────────────────
    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.append(f"[{timestamp}] {message}")

    # ── ASYNC ACTIONS DISPATCHER ───────────────────────────────────────────
    def run_async_action(self, action_name: str):
        if self.is_busy:
            self.show_toast("⏳ Hệ thống đang xử lý tác vụ trước...", is_error=True)
            return
        self.is_busy = True
        self.set_buttons_enabled(False)

        self.worker = AsyncActionWorker(action_name, self)
        self.worker.task_started.connect(self.on_task_started)
        self.worker.task_finished.connect(self.on_task_finished)
        self.worker.start()

    def on_task_started(self, action: str):
        names = {
            "START_ALL": "Đang khởi động toàn bộ hệ thống & kết nối Web...",
            "STOP_ALL": "Đang tắt toàn bộ hệ thống...",
            "START_BACKEND": "Đang bật máy chủ Backend...",
            "STOP_BACKEND": "Đang dừng máy chủ Backend...",
            "START_TUNNEL": "Đang kích hoạt Cloudflare Tunnel...",
            "STOP_TUNNEL": "Đang ngắt kết nối Cloudflare Tunnel...",
        }
        msg = names.get(action, "Đang xử lý...")
        self.log(f"⏳ {msg}")
        self.show_toast(msg)

    def on_task_finished(self, action: str, ok: bool, msg: str):
        self.is_busy = False
        self.set_buttons_enabled(True)
        if ok:
            self.log(f"✔ {msg}")
            self.show_toast(f"✔ {msg}")
        else:
            self.log(f"❌ {msg}")
            self.show_toast(f"❌ {msg}", is_error=True)

        # Trigger immediate check to update switches
        QTimer.singleShot(200, self.check_status_async)

    def set_buttons_enabled(self, enabled: bool):
        self.master_btn.setEnabled(enabled)
        self.mini_master_btn.setEnabled(enabled)
        self.refresh_btn.setEnabled(enabled)

    # ── UI HANDLERS ────────────────────────────────────────────────────────
    def on_master_btn_clicked(self):
        backend_ok = is_port_in_use(BACKEND_PORT)
        tunnel_ok = check_tunnel_running()
        if backend_ok or tunnel_ok:
            self.run_async_action("STOP_ALL")
        else:
            self.run_async_action("START_ALL")

    def on_backend_switch_toggled(self, checked: bool):
        if self.is_busy:
            return
        current_state = is_port_in_use(BACKEND_PORT)
        if checked and not current_state:
            self.run_async_action("START_BACKEND")
        elif not checked and current_state:
            self.run_async_action("STOP_BACKEND")

    def on_tunnel_switch_toggled(self, checked: bool):
        if self.is_busy:
            return
        current_state = check_tunnel_running()
        if checked and not current_state:
            self.run_async_action("START_TUNNEL")
        elif not checked and current_state:
            self.run_async_action("STOP_TUNNEL")

    # ── STATUS CHECK & REFRESH ─────────────────────────────────────────────
    def check_status_async(self):
        """Kiểm tra trạng thái thời gian thực và cập nhật giao diện."""
        st = get_full_status()
        backend_ok = st["backend_running"]
        tunnel_ok = st["tunnel_running"]
        public_ok = st["public_url_ok"]

        # Connection card updates
        if backend_ok:
            self.local_status_badge.setText("SẴN SÀNG")
            self.local_status_badge.setStyleSheet("""
                background-color: rgba(16, 185, 129, 0.15);
                color: #34d399;
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 2px 6px;
                border: 1px solid rgba(16, 185, 129, 0.3);
            """)
            self.mini_server_lbl.setText("🖥️ Máy chủ: 🟢 Online")
        else:
            self.local_status_badge.setText("CHƯA BẬT")
            self.local_status_badge.setStyleSheet("""
                background-color: rgba(239, 68, 68, 0.15);
                color: #f87171;
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 2px 6px;
                border: 1px solid rgba(239, 68, 68, 0.3);
            """)
            self.mini_server_lbl.setText("🖥️ Máy chủ: 🔴 Offline")

        if tunnel_ok:
            if public_ok:
                self.web_status_badge.setText("SẴN SÀNG")
                self.web_status_badge.setStyleSheet("""
                    background-color: rgba(16, 185, 129, 0.15);
                    color: #34d399;
                    font-size: 10px;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 2px 6px;
                    border: 1px solid rgba(16, 185, 129, 0.3);
                """)
                self.mini_web_lbl.setText("🌍 Web Online: 🟢 Online")
            else:
                self.web_status_badge.setText("KẾT NỐI...")
                self.web_status_badge.setStyleSheet("""
                    background-color: rgba(245, 158, 11, 0.15);
                    color: #fbbf24;
                    font-size: 10px;
                    font-weight: bold;
                    border-radius: 4px;
                    padding: 2px 6px;
                    border: 1px solid rgba(245, 158, 11, 0.3);
                """)
                self.mini_web_lbl.setText("🌍 Web Online: 🟡 Kết nối...")
        else:
            self.web_status_badge.setText("CHƯA BẬT")
            self.web_status_badge.setStyleSheet("""
                background-color: rgba(239, 68, 68, 0.15);
                color: #f87171;
                font-size: 10px;
                font-weight: bold;
                border-radius: 4px;
                padding: 2px 6px;
                border: 1px solid rgba(239, 68, 68, 0.3);
            """)
            self.mini_web_lbl.setText("🌍 Web Online: 🔴 Chưa bật")

        # Master button updates
        if backend_ok and tunnel_ok:
            self.master_status_dot.setStyleSheet("color: #10b981; font-size: 18px;")
            self.master_status_text.setText("HỆ THỐNG & WEB ĐANG HOẠT ĐỘNG")
            self.master_btn.setText("🛑 DỪNG TOÀN BỘ HỆ THỐNG")
            self.master_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e11d48, stop:1 #be123c);
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 800;
                    padding: 12px;
                    border-radius: 8px;
                    border: none;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f43f5e, stop:1 #e11d48);
                }
                QPushButton:disabled {
                    background-color: #475569;
                    color: #94a3b8;
                }
            """)
            self.hero_subtext.setText("Đang chạy Máy chủ Backend (9123) và Cloudflare Tunnel")
            self.mini_master_btn.setText("🛑 Tắt Hệ Thống")
            self.mini_master_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e11d48;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                    border: none;
                }
                QPushButton:hover { background-color: #f43f5e; }
            """)
        elif backend_ok or tunnel_ok:
            self.master_status_dot.setStyleSheet("color: #f59e0b; font-size: 18px;")
            self.master_status_text.setText("HỆ THỐNG ĐANG KẾT NỐI MỘT PHẦN")
            self.master_btn.setText("🛑 DỪNG TOÀN BỘ HỆ THỐNG")
            self.hero_subtext.setText("Một trong các dịch vụ đang chạy. Bấm để tắt toàn bộ.")
        else:
            self.master_status_dot.setStyleSheet("color: #ef4444; font-size: 18px;")
            self.master_status_text.setText("HỆ THỐNG ĐANG TẮT")
            self.master_btn.setText("🚀 BẬT HỆ THỐNG & KẾT NỐI WEB")
            self.master_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #0284c7);
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: 800;
                    padding: 12px;
                    border-radius: 8px;
                    border: none;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #0ea5e9);
                }
                QPushButton:disabled {
                    background-color: #475569;
                    color: #94a3b8;
                }
            """)
            self.hero_subtext.setText("Tự động kích hoạt Máy chủ Backend (9123) và kết nối Cloudflare Tunnel")
            self.mini_master_btn.setText("⚡ Bật Hệ Thống")
            self.mini_master_btn.setStyleSheet("""
                QPushButton {
                    background-color: #0284c7;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 6px 12px;
                    border-radius: 6px;
                    border: none;
                }
                QPushButton:hover { background-color: #0369a1; }
            """)

    # ── MOUSE DRAGGING FOR FRAMELESS WINDOW ────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self.save_config()
        event.accept()

    def closeEvent(self, event):
        self.save_config()
        event.accept()


# ── ENTRY POINT ───────────────────────────────────────────────────────────
def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("duytris.system.hub.v2")
        except Exception:
            pass

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("DuyTris System Hub")
    app.setOrganizationName("DuyTris")

    # High DPI scaling
    window = SystemControllerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

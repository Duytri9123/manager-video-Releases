# -*- coding: utf-8 -*-
"""
DuyTris System Controller Module
Cung cấp các hàm điều khiển cốt lõi: Bật/Tắt Backend (port 9123), Cloudflare Tunnel,
kiểm tra trạng thái thời gian thực và mở kết nối Web.
Được dùng chung bởi cả giao diện đồ họa (UI) và công cụ dòng lệnh (CLI).
"""
from __future__ import annotations

import os
import sys
import time
import socket
import subprocess
import urllib.request
import urllib.error
import ssl
import webbrowser
from pathlib import Path
from typing import Tuple, List, Dict, Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

TUNNEL_CONFIG = ROOT / "tools" / "tunnel_config.yml"
TUNNEL_NAME = "toolvideo-backend"
PUBLIC_DOMAIN = "https://toolvideo.dgpelectric.top"
LOCAL_URL = "http://localhost:9123"
BACKEND_PORT = 9123


def is_port_in_use(port: int = BACKEND_PORT) -> bool:
    """Kiểm tra xem cổng port có đang mở và lắng nghe hay không."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def get_backend_pids(port: int = BACKEND_PORT) -> List[int]:
    """Tìm tất cả PID tiến trình đang lắng nghe trên cổng được chỉ định."""
    pids = set()
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5 and parts[-1].isdigit():
                    pids.add(int(parts[-1]))
    except Exception:
        pass
    return list(pids)


def get_toolvideo_tunnel_pids() -> List[int]:
    """Tìm tất cả PID của cloudflared đang chạy riêng cho toolvideo (không đụng aide-backend)."""
    pids = set()
    # 1. Dùng PowerShell CIM để truy xuất CommandLine chính xác
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'cloudflared.exe' -and ($_.CommandLine -like '*toolvideo*' -or $_.CommandLine -like '*tunnel_config.yml*') } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        for line in res.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    except Exception:
        pass

    # 2. Dự phòng qua WMIC nếu PowerShell không trả về gì
    if not pids:
        try:
            out = subprocess.check_output(
                ["wmic", "process", "where", "name='cloudflared.exe'", "get", "processid,commandline"],
                text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                lower_line = line.lower()
                if "toolvideo" in lower_line or "tunnel_config" in lower_line:
                    parts = line.strip().split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
        except Exception:
            pass

    return list(pids)


def check_tunnel_running() -> bool:
    """Kiểm tra xem Cloudflare Tunnel của toolvideo có đang chạy hay không."""
    return len(get_toolvideo_tunnel_pids()) > 0


def test_public_url(timeout: float = 3.0) -> bool:
    """Kiểm tra xem tên miền công khai qua Cloudflare Tunnel có phản hồi 200 OK hay không."""
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            f"{PUBLIC_DOMAIN}/api/files/completed",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DuyTrisController/1.0"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_backend(wait_seconds: int = 25) -> Tuple[bool, str]:
    """Khởi động máy chủ Backend (Port 9123)."""
    if is_port_in_use(BACKEND_PORT):
        return True, f"Backend đã đang chạy trên cổng {BACKEND_PORT}."

    start_bat = ROOT / "start.bat"
    if not start_bat.exists():
        return False, f"Không tìm thấy file start.bat tại {start_bat}"

    try:
        task_name = "DuyTrisToolVideoBackend"
        cmd = f'cmd.exe /c start "" "{start_bat}"'
        subprocess.run(
            ["schtasks", "/create", "/tn", task_name, "/tr", cmd, "/sc", "once", "/st", "23:59", "/f"],
            capture_output=True, text=True
        )
        subprocess.run(["schtasks", "/run", "/tn", task_name], capture_output=True, text=True)
        time.sleep(1)
        subprocess.run(["schtasks", "/delete", "/tn", task_name], capture_output=True, text=True)
    except Exception:
        subprocess.Popen(f'cmd.exe /c start "" "{start_bat}"', cwd=str(ROOT), shell=True)

    # Đợi cổng mở
    for _ in range(wait_seconds):
        time.sleep(1)
        if is_port_in_use(BACKEND_PORT):
            return True, f"Backend đã khởi động thành công trên cổng {BACKEND_PORT}!"

    if is_port_in_use(BACKEND_PORT):
        return True, "Backend đã sẵn sàng!"
    return False, "Hết thời gian chờ Backend khởi động."


def stop_backend() -> Tuple[bool, str]:
    """Dừng máy chủ Backend (Port 9123)."""
    pids = get_backend_pids(BACKEND_PORT)
    if not pids and not is_port_in_use(BACKEND_PORT):
        return True, "Backend đã ở trạng thái tắt."

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True)
        except Exception:
            pass

    time.sleep(0.5)
    if not is_port_in_use(BACKEND_PORT):
        return True, "Đã dừng Backend server thành công."
    return False, "Không thể giải phóng cổng 9123."


def start_tunnel() -> Tuple[bool, str]:
    """Bật kết nối Cloudflare Tunnel riêng cho toolvideo (kết nối web ra ngoài)."""
    if check_tunnel_running():
        return True, "Cloudflare Tunnel đang chạy sẵn."

    if not TUNNEL_CONFIG.exists():
        return False, f"Không tìm thấy file cấu hình {TUNNEL_CONFIG}"

    cmd = f'cloudflared --config "{TUNNEL_CONFIG}" tunnel run {TUNNEL_NAME}'
    try:
        subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            shell=True
        )
        time.sleep(2.5)
        if check_tunnel_running():
            return True, f"Đã kết nối Web công khai thành công: {PUBLIC_DOMAIN}"
        return True, "Đã gửi lệnh kích hoạt Cloudflare Tunnel."
    except Exception as e:
        return False, f"Lỗi khi bật Tunnel: {e}"


def stop_tunnel() -> Tuple[bool, str]:
    """Ngắt kết nối Web ra ngoài (Dừng tiến trình Cloudflare Tunnel của toolvideo)."""
    pids = get_toolvideo_tunnel_pids()
    if not pids and not check_tunnel_running():
        return True, "Cloudflare Tunnel đã ở trạng thái ngắt kết nối."

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True)
        except Exception:
            pass

    time.sleep(0.5)
    if not check_tunnel_running():
        return True, "Đã ngắt kết nối Web ra ngoài thành công."
    return False, "Không thể dừng Cloudflare Tunnel."


def start_all() -> Tuple[bool, str]:
    """Bật toàn bộ hệ thống: Backend + Kết nối Cloudflare Web."""
    ok1, msg1 = start_backend()
    ok2, msg2 = start_tunnel()
    if ok1 and ok2:
        return True, "Đã bật toàn bộ hệ thống & kết nối Web thành công!"
    return False, f"{msg1} | {msg2}"


def stop_all() -> Tuple[bool, str]:
    """Dừng toàn bộ hệ thống: Ngắt kết nối Web + Dừng Backend."""
    ok2, msg2 = stop_tunnel()
    ok1, msg1 = stop_backend()
    if ok1 and ok2:
        return True, "Đã tắt toàn bộ hệ thống và ngắt kết nối Web an toàn!"
    return False, f"{msg2} | {msg1}"


def open_local_web() -> None:
    """Mở giao diện Web trên trình duyệt cục bộ."""
    try:
        webbrowser.open(LOCAL_URL)
    except Exception:
        pass


def open_public_web() -> None:
    """Mở trang Web công khai qua internet."""
    try:
        webbrowser.open(PUBLIC_DOMAIN)
    except Exception:
        pass


def get_full_status() -> Dict[str, Any]:
    """Lấy dữ liệu trạng thái tổng quan nhanh."""
    backend_ok = is_port_in_use(BACKEND_PORT)
    tunnel_ok = check_tunnel_running()
    public_ok = test_public_url(timeout=1.5) if tunnel_ok else False
    return {
        "backend_running": backend_ok,
        "tunnel_running": tunnel_ok,
        "public_url_ok": public_ok,
        "backend_port": BACKEND_PORT,
        "local_url": LOCAL_URL,
        "public_domain": PUBLIC_DOMAIN,
    }

# -*- coding: utf-8 -*-
"""
DuyTris System Manager & Setup Exe Updater
Quản lý bật/tắt toàn bộ hệ thống (Backend + Cloudflare Tunnel) và Cập nhật build Setup.exe
"""
import os
import sys
import time
import json
import socket
import subprocess
import urllib.request
import urllib.error
import ssl
from pathlib import Path

# Force UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

TUNNEL_CONFIG = ROOT / "tools" / "tunnel_config.yml"
TUNNEL_NAME = "toolvideo-backend"
PUBLIC_DOMAIN = "https://toolvideo.dgpelectric.top"
LOCAL_URL = "http://localhost:9123"

# Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_MAGENTA = "\033[95m"
C_BLUE = "\033[94m"


def is_port_in_use(port: int = 9123) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_tunnel_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/fi", "imagename eq cloudflared.exe", "/fo", "csv"],
            text=True, stderr=subprocess.DEVNULL
        )
        return "cloudflared.exe" in out.lower()
    except Exception:
        return False


def test_public_url() -> bool:
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            f"{PUBLIC_DOMAIN}/api/files/completed",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def start_backend():
    if is_port_in_use(9123):
        print(f" {C_GREEN}✔ Backend đang chạy trên cổng 9123.{C_RESET}")
        return True

    print(f" {C_CYAN}⏳ Đang khởi động Backend server (port 9123)...{C_RESET}")
    start_bat = ROOT / "start.bat"
    if not start_bat.exists():
        print(f" {C_RED}❌ Không tìm thấy file start.bat tại {start_bat}{C_RESET}")
        return False

    # Launch in background
    subprocess.Popen(
        [str(start_bat)],
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        shell=True
    )

    # Wait for port to open
    for i in range(25):
        time.sleep(1)
        if is_port_in_use(9123):
            print(f" {C_GREEN}✔ Backend đã sẵn sàng tại {LOCAL_URL}!{C_RESET}")
            return True
        print(f"   ... đang tải ({i+1}s)", end="\r")

    print(f"\n {C_YELLOW}⚠ Backend đang khởi động hoặc mất nhiều thời gian hơn dự kiến.{C_RESET}")
    return is_port_in_use(9123)


def start_tunnel():
    print(f" {C_CYAN}⏳ Đang kết nối Cloudflare Tunnel riêng ({TUNNEL_NAME})...{C_RESET}")
    if not TUNNEL_CONFIG.exists():
        print(f" {C_RED}❌ Không tìm thấy file cấu hình {TUNNEL_CONFIG}{C_RESET}")
        return False

    cmd = f'cloudflared --config "{TUNNEL_CONFIG}" tunnel run {TUNNEL_NAME}'
    subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        shell=True
    )

    time.sleep(3)
    print(f" {C_GREEN}✔ Cloudflare Tunnel đã kích hoạt!{C_RESET}")
    print(f"   Domain công khai: {C_BOLD}{C_GREEN}{PUBLIC_DOMAIN}{C_RESET}")
    return True


def open_browser():
    try:
        import webbrowser
        webbrowser.open(LOCAL_URL)
        print(f" {C_GREEN}✔ Đã mở trình duyệt: {LOCAL_URL}{C_RESET}")
    except Exception as e:
        print(f" {C_YELLOW}⚠ Không mở được trình duyệt tự động: {e}{C_RESET}")


def start_all_system():
    print("\n" + "=" * 60)
    print(f" {C_BOLD}{C_CYAN}🚀 BẬT TOÀN BỘ HỆ THỐNG DUYTRIS TOOLVIDEO{C_RESET}")
    print("=" * 60)
    
    start_backend()
    start_tunnel()
    open_browser()

    print("\n" + "-" * 60)
    print(f" {C_BOLD}Trạng thái hiện tại:{C_RESET}")
    print(f" - Local WebUI:        {C_CYAN}{LOCAL_URL}{C_RESET}")
    print(f" - Cloudflare Tunnel:  {C_GREEN}{PUBLIC_DOMAIN}{C_RESET}")
    print(f" - Tunnel Name:        {C_MAGENTA}{TUNNEL_NAME}{C_RESET} (riêng biệt, không đụng aide-backend)")
    print("-" * 60)


def stop_all_system():
    print("\n" + "=" * 60)
    print(f" {C_BOLD}{C_RED}🛑 DỪNG TOÀN BỘ HỆ THỐNG{C_RESET}")
    print("=" * 60)

    # Stop cloudflared processes running toolvideo tunnel
    print(f" {C_CYAN}⏳ Dừng Cloudflare Tunnel...{C_RESET}")
    try:
        subprocess.run(["taskkill", "/f", "/im", "cloudflared.exe"], capture_output=True)
        print(f" {C_GREEN}✔ Đã đóng tiến trình cloudflared.{C_RESET}")
    except Exception as e:
        print(f" ⚠ Lỗi: {e}")

    # Stop python process listening on port 9123
    print(f" {C_CYAN}⏳ Dừng Backend server (port 9123)...{C_RESET}")
    try:
        # Find PID on 9123
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True, stderr=subprocess.DEVNULL
        )
        pids = set()
        for line in out.splitlines():
            if ":9123" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pids.add(parts[-1])
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True)
                print(f" {C_GREEN}✔ Đã đóng tiến trình PID {pid} trên port 9123.{C_RESET}")
            except Exception:
                pass
        if not pids:
            print(f" {C_GREEN}✔ Cổng 9123 đã được giải phóng.{C_RESET}")
    except Exception as e:
        print(f" ⚠ Lỗi: {e}")

    print(f"\n {C_GREEN}✔ Đã dừng toàn bộ dịch vụ thành công!{C_RESET}\n")


def build_and_update_setup_exe():
    print("\n" + "=" * 65)
    print(f" {C_BOLD}{C_MAGENTA}📦 CẬP NHẬT TOÀN BỘ VÀ BUILD SETUP EXE (DUYTRIS DOWNLOADER){C_RESET}")
    print("=" * 65)

    build_script = ROOT / "build_exe.ps1"
    installer_script = ROOT / "installer" / "Build-Installer.ps1"
    output_dir = ROOT / "output"
    target_exe = output_dir / "DuyTrisDownloader_Setup.exe"

    if not build_script.exists():
        print(f" {C_RED}❌ Không tìm thấy script {build_script}{C_RESET}")
        return

    # Check ISCC.exe
    compiler_candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\Inno Setup 6\ISCC.exe",
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\Antigravity IDE\resources\app\node_modules\innosetup\bin\ISCC.exe",
    ]
    iscc_path = None
    for cand in compiler_candidates:
        if cand.exists():
            iscc_path = cand
            break

    if not iscc_path:
        print(f" {C_RED}❌ Không tìm thấy trình biên dịch Inno Setup ISCC.exe!{C_RESET}")
        print("   Vui lòng cài đặt Inno Setup 6 (winget install JRSoftware.InnoSetup).")
        return

    print(f" {C_GREEN}✔ Trình biên dịch Inno Setup:{C_RESET} {iscc_path}")
    print(f" {C_CYAN}Bắt đầu quy trình build 2 bước tự động...{C_RESET}\n")

    # Bước 1: Build EXE qua PyInstaller & PyArmor
    print(f"{C_BOLD}[BƯỚC 1/2] Biên dịch mã nguồn Python ra thư mục dist/DuyTrisDownloader...{C_RESET}")
    t0 = time.time()
    try:
        proc1 = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(build_script)],
            cwd=str(ROOT),
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n {C_RED}❌ Lỗi ở Bước 1 (Build EXE thất bại): {e}{C_RESET}")
        return

    # Bước 2: Đóng gói ra Setup.exe bằng Inno Setup
    print(f"\n{C_BOLD}[BƯỚC 2/2] Đóng gói bộ cài đặt Setup bằng Inno Setup...{C_RESET}")
    try:
        proc2 = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer_script), "-OutputExe", str(target_exe)],
            cwd=str(ROOT),
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"\n {C_RED}❌ Lỗi ở Bước 2 (Inno Setup thất bại): {e}{C_RESET}")
        return

    elapsed = round(time.time() - t0, 1)

    if target_exe.exists():
        size_mb = round(target_exe.stat().st_size / (1024 * 1024), 2)
        print("\n" + "=" * 65)
        print(f" {C_BOLD}{C_GREEN}🎉 CẬP NHẬT & ĐÓNG GÓI SETUP.EXE THÀNH CÔNG!{C_RESET}")
        print(f" - File đầu ra: {C_BOLD}{target_exe}{C_RESET}")
        print(f" - Dung lượng:  {C_CYAN}{size_mb} MB{C_RESET}")
        print(f" - Thời gian:   {C_YELLOW}{elapsed} giây{C_RESET}")
        print("=" * 65)

        # Update version.json timestamp
        version_json = output_dir / "version.json"
        if version_json.exists():
            try:
                with open(version_json, "r", encoding="utf-8") as f:
                    vdata = json.load(f)
                vdata["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                vdata["file_size_mb"] = size_mb
                with open(version_json, "w", encoding="utf-8") as f:
                    json.dump(vdata, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        # Open output folder
        try:
            os.startfile(str(output_dir))
        except Exception:
            pass
    else:
        print(f"\n {C_RED}❌ File {target_exe} không xuất hiện sau khi build.{C_RESET}")


def show_status():
    print("\n" + "=" * 60)
    print(f" {C_BOLD}{C_CYAN}📊 KIỂM TRA TRẠNG THÁI HỆ THỐNG{C_RESET}")
    print("=" * 60)

    port_ok = is_port_in_use(9123)
    tunnel_ok = check_tunnel_running()
    public_ok = test_public_url() if tunnel_ok else False

    print(f" 1. Backend Server (127.0.0.1:9123):   {C_GREEN if port_ok else C_RED}{'ĐANG CHẠY (ONLINE)' if port_ok else 'ĐÃ DỪNG (OFFLINE)'}{C_RESET}")
    print(f" 2. Cloudflare Tunnel ({TUNNEL_NAME}): {C_GREEN if tunnel_ok else C_RED}{'ĐANG CHẠY (ONLINE)' if tunnel_ok else 'ĐÃ DỪNG (OFFLINE)'}{C_RESET}")
    print(f" 3. Public Domain ({PUBLIC_DOMAIN}): {C_GREEN if public_ok else C_YELLOW}{'KẾT NỐI TỐT (200 OK)' if public_ok else 'CHƯA TRUY CẬP ĐƯỢC'}{C_RESET}")
    print("-" * 60)


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("start", "run", "on"):
            start_all_system()
            return
        elif arg in ("stop", "kill", "off"):
            stop_all_system()
            return
        elif arg in ("restart", "reboot"):
            stop_all_system()
            time.sleep(1)
            start_all_system()
            return
        elif arg in ("build", "update", "setup"):
            build_and_update_setup_exe()
            return
        elif arg in ("status", "check"):
            show_status()
            return

    # Interactive menu
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("\n" + "=" * 65)
        print(f" {C_BOLD}{C_CYAN}🌟 DUYTRIS SYSTEM & SETUP EXE MANAGER TOOL 🌟{C_RESET}")
        print("=" * 65)
        print(f"  [1] 🚀 {C_BOLD}Bật toàn bộ hệ thống{C_RESET} (Backend + Cloudflare Tunnel + Web)")
        print(f"  [2] 🔄 {C_BOLD}Khởi động lại hệ thống{C_RESET} (Restart)")
        print(f"  [3] 🛑 {C_BOLD}Dừng toàn bộ hệ thống{C_RESET} (Stop)")
        print(f"  [4] 📦 {C_BOLD}{C_MAGENTA}Cập nhật & Build Setup EXE{C_RESET} ({C_GREEN}DuyTrisDownloader_Setup.exe{C_RESET})")
        print(f"  [5] 📊 {C_BOLD}Kiểm tra trạng thái kết nối & Cloudflare Tunnel{C_RESET}")
        print(f"  [0] ❌ {C_BOLD}Thoát{C_RESET}")
        print("=" * 65)

        choice = input(f" Nhập lựa chọn của bạn [{C_CYAN}1-5, 0{C_RESET}]: ").strip()

        if choice == "1":
            start_all_system()
            input(f"\n {C_CYAN}Nhấn Enter để tiếp tục...{C_RESET}")
        elif choice == "2":
            stop_all_system()
            time.sleep(1)
            start_all_system()
            input(f"\n {C_CYAN}Nhấn Enter để tiếp tục...{C_RESET}")
        elif choice == "3":
            stop_all_system()
            input(f"\n {C_CYAN}Nhấn Enter để tiếp tục...{C_RESET}")
        elif choice == "4":
            build_and_update_setup_exe()
            input(f"\n {C_CYAN}Nhấn Enter để tiếp tục...{C_RESET}")
        elif choice == "5":
            show_status()
            input(f"\n {C_CYAN}Nhấn Enter để tiếp tục...{C_RESET}")
        elif choice in ("0", "q", "exit"):
            print(f"\n {C_GREEN}Tạm biệt!{C_RESET}\n")
            break


if __name__ == "__main__":
    main()

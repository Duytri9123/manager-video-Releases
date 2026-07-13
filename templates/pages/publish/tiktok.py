"""TikTok Blueprint — Semi-automated upload via Playwright.

Why semi-auto only:
- TikTok's ToS forbids automated posting.
- The Content Posting API requires an approved app with video.publish scope.
- So we do 80% of the work (open studio, attach file, fill caption) and let the
  user review & press "Post" manually. This keeps ban risk minimal and removes
  the "copy caption → paste" chore.

Endpoints
─────────
POST /api/tiktok/prepare_upload   start a Playwright session
  body: { video_path: str, caption: str, profile_dir?: str }
  → { ok, session_id }
GET  /api/tiktok/prepare_status   poll progress
  query: ?session_id=...
  → { ok, status, log[], done, error }
POST /api/tiktok/prepare_close    force-close the session
  body: { session_id }

The browser stays open until the user closes it. That keeps the TikTok login
cookie in the persistent profile for the next run.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from core_app import ROOT

bp = Blueprint("tiktok", __name__)

# TikTok Studio upload URL — the studio UI is more stable than the old /upload page.
TIKTOK_UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"

# Persistent profile dir — keeps login across runs.
_TT_PROFILE_DIR = ROOT / ".tiktok_profile"

# Global session registry. One active session at a time is usually plenty, but
# we key by session_id so UI can poll even if user starts a new one.
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()

# Serializes sessions until the master profile has valid login cookies.
# This prevents the user from having to log in multiple times when running
# a batch queue with several videos (each would otherwise spawn a browser
# that copies the master profile before the first login completes).
_TT_LOGIN_GATE = threading.Lock()


def _new_session() -> Dict[str, Any]:
    return {
        "status": "starting",   # starting | launching | uploading | ready | done | error | closed
        "log": [],
        "error": "",
        "done": False,
        "created_at": time.time(),
        "updated_at": time.time(),
        "stop_event": threading.Event(),
    }


def _log(sid: str, msg: str, level: str = "info"):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return
        s["log"].append({"t": time.time(), "level": level, "msg": msg})
        s["updated_at"] = time.time()


def _set_status(sid: str, status: str, *, error: str = "", done: bool = False):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return
        s["status"] = status
        if error:
            s["error"] = error
        if done:
            s["done"] = True
        s["updated_at"] = time.time()


async def _try_enable_schedule(page, scheduled_time: str, sid: str):
    """Try to enable the Schedule toggle on TikTok Studio and set the date/time.
    
    TikTok Studio's schedule UI uses custom date/time pickers (not native
    <input type="date">), so we use a JavaScript fallback to set their React
    state. If that fails we just log clear instructions for the user.
    """
    from datetime import datetime

    # Parse scheduled_time
    try:
        if scheduled_time.isdigit():
            dt = datetime.fromtimestamp(int(scheduled_time))
        else:
            dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
            # Convert to local time (TikTok Studio uses user's local timezone)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
    except Exception:
        _log(sid, f"⚠ Không parse được thời gian đặt lịch: {scheduled_time}. Hãy đặt lịch tay.", "warning")
        return

    friendly = dt.strftime("%d/%m/%Y lúc %H:%M")
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M")

    # ── 1. Click the "Schedule" radio/toggle ──
    _log(sid, "🔍 Tìm nút Schedule trên TikTok Studio...")
    schedule_clicked = False
    # TikTok Studio uses a radio group: "Now" | "Schedule". We locate by text.
    for sel in [
        'label:has-text("Schedule"):not(:has-text("Scheduled"))',
        'label:has-text("Đặt lịch")',
        'label:has-text("定时发布")',
        'span:has-text("Schedule"):not(:has-text("Scheduled"))',
        'div[class*="when-to-post"] label:nth-child(2)',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                schedule_clicked = True
                _log(sid, "📅 Đã click Schedule.")
                break
        except Exception:
            pass

    if not schedule_clicked:
        _log(sid, f"⚠ Không tìm thấy nút Schedule. Hãy bật đặt lịch tay → chọn {friendly}.", "warning")
        return

    await asyncio.sleep(1.5)  # wait for date/time pickers to render

    # ── 2. Fill the date picker ──
    # TikTok's date picker is a custom dropdown button that opens a calendar.
    # The button's text usually shows today's date like "2026-05-14".
    # We click the date button to open the picker, then type YYYY-MM-DD into
    # the input that appears, then press Enter.
    date_set = await _tt_set_date(page, dt, sid)
    time_set = await _tt_set_time(page, dt, sid)

    if date_set and time_set:
        _log(sid, f"📅 Đã điền lịch: {friendly}")
    elif date_set:
        _log(sid, f"⚠ Điền được ngày {date_str} nhưng chưa điền được giờ {time_str}. Hãy chọn giờ tay.", "warning")
    elif time_set:
        _log(sid, f"⚠ Điền được giờ {time_str} nhưng chưa điền được ngày {date_str}. Hãy chọn ngày tay.", "warning")
    else:
        _log(sid, f"⚠ Không điền được ngày giờ tự động. Hãy chọn tay: {friendly}", "warning")


async def _tt_set_date(page, dt, sid: str) -> bool:
    """Set date on TikTok Studio's schedule picker."""
    date_str = dt.strftime("%Y-%m-%d")
    # Try native inputs first
    for sel in ['input[type="date"]', 'input[placeholder*="date" i]', 'input[name*="date" i]']:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(date_str)
                return True
        except Exception:
            pass

    # Try TikTok's custom picker — click the button that shows the date, then
    # find the input inside the popup.
    for sel in [
        'button:has-text("-")[class*="date" i]',
        'div[class*="date-picker"] button',
        'div[class*="calendar"] button',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await asyncio.sleep(0.5)
                # Look for a text input in the opened popup
                inp = await page.query_selector('input[type="text"]:focus, div[class*="picker"] input[type="text"]')
                if inp:
                    await inp.fill(date_str)
                    await page.keyboard.press("Enter")
                    return True
        except Exception:
            pass
    return False


async def _tt_set_time(page, dt, sid: str) -> bool:
    """Set time on TikTok Studio's schedule picker."""
    time_str = dt.strftime("%H:%M")
    # Try native input
    for sel in ['input[type="time"]', 'input[placeholder*="time" i]', 'input[name*="time" i]']:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(time_str)
                return True
        except Exception:
            pass

    # TikTok Studio time picker is a custom dropdown with hour/minute columns.
    # It's very fragile to automate. We try to find an input and type, otherwise
    # return False.
    for sel in [
        'div[class*="time-picker"] input',
        'button[class*="time" i] + input',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(time_str)
                await page.keyboard.press("Enter")
                return True
        except Exception:
            pass
    return False


async def _try_set_privacy(page, privacy: str, sid: str):
    """Set privacy on TikTok Studio's 'Who can see this post' dropdown.

    privacy values (from our UI):
      - PUBLIC_TO_EVERYONE → "Everyone"
      - FRIENDS            → "Friends"
      - SELF_ONLY          → "Only you"
    """
    if not privacy:
        return
    label_map = {
        "PUBLIC_TO_EVERYONE": ("Everyone", "Mọi người", "所有人"),
        "FRIENDS":            ("Friends", "Bạn bè", "朋友"),
        "SELF_ONLY":          ("Only you", "Chỉ mình bạn", "仅自己"),
    }
    targets = label_map.get(privacy.upper())
    if not targets:
        return

    # Click the "Who can see this post" dropdown to open it
    _log(sid, f"🔒 Đặt quyền riêng tư: {targets[0]}")
    opened = False
    for sel in [
        'div[class*="who-can-see"] [role="combobox"]',
        'div[class*="privacy"] [role="combobox"]',
        'button[aria-haspopup="listbox"]',
        'div[class*="who-can-see"] button',
        'div[class*="visibility"] button',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                opened = True
                break
        except Exception:
            pass

    if not opened:
        _log(sid, f"⚠ Không tìm thấy dropdown quyền riêng tư. Hãy chọn \"{targets[0]}\" tay.", "warning")
        return

    await asyncio.sleep(0.5)

    # Click the option matching our privacy
    for text in targets:
        for sel in [
            f'[role="option"]:has-text("{text}")',
            f'li:has-text("{text}")',
            f'div[role="menuitem"]:has-text("{text}")',
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    _log(sid, f"✅ Đã chọn quyền: {text}")
                    return
            except Exception:
                pass

    _log(sid, f"⚠ Đã mở dropdown nhưng không click được \"{targets[0]}\". Hãy chọn tay.", "warning")


def _cleanup_profile_locks(profile_dir: Path):
    """Remove stale Chromium lock files that prevent launching a new browser.

    When Chrome crashes or is killed without graceful shutdown, it leaves behind
    SingletonLock/SingletonCookie/SingletonSocket files. These cause the next
    launch to fail with 'Target page, context or browser has been closed' because
    Chromium thinks another instance is using the profile.

    We also kill any orphaned chrome processes using this profile dir.
    """
    import os
    import subprocess

    # 1. Kill any orphaned chrome processes using this profile
    try:
        profile_str = str(profile_dir).replace("/", "\\")
        # Use wmic to find chrome processes with our user-data-dir
        result = subprocess.run(
            ["wmic", "process", "where",
             f"commandline like '%{profile_dir.name}%' and name like '%chrome%'",
             "get", "processid"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                try:
                    subprocess.run(["taskkill", "/F", "/PID", line],
                                   capture_output=True, timeout=5)
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Remove lock files
    lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    for name in lock_files:
        lock_path = profile_dir / name
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass

    # 3. Also clean Default/lock if present
    default_lock = profile_dir / "Default" / "lockfile"
    try:
        if default_lock.exists():
            default_lock.unlink()
    except Exception:
        pass


def _copy_profile_essentials(src: Path, dst: Path):
    """Copy essential browser profile files (cookies, local storage, login state)
    from master profile to a session profile. Skips heavy cache directories."""
    import shutil

    # Files/dirs that hold login state
    essential_items = [
        "Default/Cookies",
        "Default/Cookies-journal",
        "Default/Local Storage",
        "Default/Session Storage",
        "Default/IndexedDB",
        "Default/Preferences",
        "Default/Secure Preferences",
        "Default/Login Data",
        "Default/Login Data-journal",
        "Default/Web Data",
        "Default/Web Data-journal",
        "Local State",
    ]

    dst.mkdir(parents=True, exist_ok=True)

    for item in essential_items:
        src_path = src / item
        dst_path = dst / item
        if not src_path.exists():
            continue
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                if dst_path.exists():
                    shutil.rmtree(str(dst_path), ignore_errors=True)
                shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src_path), str(dst_path))
        except Exception:
            pass


def _sync_profile_back(session_dir: Path, master_dir: Path):
    """Sync cookies and login state from session profile back to master profile.
    This ensures that if the user logged in during this session, the master
    profile gets updated for future sessions."""
    import shutil

    sync_items = [
        "Default/Cookies",
        "Default/Cookies-journal",
        "Default/Local Storage",
        "Default/Login Data",
        "Default/Login Data-journal",
        "Local State",
    ]

    for item in sync_items:
        src_path = session_dir / item
        dst_path = master_dir / item
        if not src_path.exists():
            continue
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                if dst_path.exists():
                    shutil.rmtree(str(dst_path), ignore_errors=True)
                shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src_path), str(dst_path))
        except Exception:
            pass


def _cleanup_session_profile(session_dir: Path):
    """Remove the temporary session profile directory."""
    import shutil
    try:
        if session_dir.exists():
            shutil.rmtree(str(session_dir), ignore_errors=True)
    except Exception:
        pass


def _has_login_cookies(profile_dir: Path) -> bool:
    """Check if master profile has a saved TikTok login state.
    
    Primary source of truth: our JSON state file (from storage_state).
    Fallback: Chromium's native Cookies file size.
    """
    try:
        # Primary: check our JSON state file with actual cookie count
        state_file = profile_dir / ".tiktok_state.json"
        if state_file.exists():
            import json
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies", [])
            tt_cookies = [c for c in cookies if "tiktok" in (c.get("domain") or "").lower()]
            if tt_cookies:
                return True
        # Fallback: check Chromium's native Cookies DB size
        cookies_file = profile_dir / "Default" / "Cookies"
        if cookies_file.exists() and cookies_file.stat().st_size > 16384:
            return True
        return False
    except Exception:
        return False


async def _save_tiktok_state(context, profile_dir: Path, sid: str = None):
    """Save current browser cookies + localStorage to the master state JSON.
    
    Uses Playwright's storage_state API which is the reliable way to persist
    login state across Chromium launches. Safe to call while browser is open.
    """
    state_file = profile_dir / ".tiktok_state.json"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(state_file))
        if sid:
            _log(sid, "💾 Đã lưu phiên đăng nhập (storage_state).", "info")
        return True
    except Exception as exc:
        if sid:
            _log(sid, f"⚠ Lưu storage_state thất bại: {exc}", "warning")
        return False


async def _load_tiktok_state(context, profile_dir: Path, sid: str = None):
    """Inject saved cookies from the master state JSON into a fresh context.
    
    This runs on top of any file-level profile copy, as an extra safety net
    against SQLite lock issues or encryption key mismatches.
    """
    state_file = profile_dir / ".tiktok_state.json"
    if not state_file.exists():
        return 0
    try:
        import json
        with open(state_file, encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        if cookies:
            await context.add_cookies(cookies)
            if sid:
                _log(sid, f"✅ Load {len(cookies)} cookies từ phiên trước.", "info")
            return len(cookies)
        return 0
    except Exception as exc:
        if sid:
            _log(sid, f"⚠ Load storage_state thất bại: {exc}", "warning")
        return 0


async def _run_upload_flow(sid: str, video_path: Path, caption: str):
    """Open TikTok Studio, attach the file, fill caption, then wait for the user
    to press Post manually. This coroutine lives in its own thread/loop."""
    import shutil

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _set_status(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return

    _TT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Login gate: if master profile has no cookies, acquire the gate so
    # only this session runs until login completes. Other sessions will wait.
    login_needed = not _has_login_cookies(_TT_PROFILE_DIR)
    gate_held = False
    if login_needed:
        _log(sid, "🔒 Chưa có phiên đăng nhập TikTok — các session khác sẽ chờ login xong.", "info")
        _set_status(sid, "waiting_login_gate")
        # Block here until gate is free. We use a polling wait so stop_event works.
        stop_event: threading.Event = _sessions[sid]["stop_event"]
        while not stop_event.is_set():
            if _TT_LOGIN_GATE.acquire(blocking=False):
                gate_held = True
                break
            # If another session finished login in the meantime, we can skip the gate.
            if _has_login_cookies(_TT_PROFILE_DIR):
                _log(sid, "✅ Session khác đã đăng nhập xong — tiếp tục.", "info")
                break
            await asyncio.sleep(2)
        if stop_event.is_set():
            return

    # ── Create a per-session copy of the profile so multiple browsers can run ──
    # This avoids the "profile locked" error when another session is still open.
    session_profile = ROOT / ".tiktok_sessions" / sid
    session_profile.mkdir(parents=True, exist_ok=True)

    # Copy essential files from master profile (cookies, local storage, etc.)
    # but skip heavy cache dirs to keep it fast.
    _copy_profile_essentials(_TT_PROFILE_DIR, session_profile)

    _set_status(sid, "launching")
    _log(sid, f"🚀 Mở trình duyệt (session profile: {sid}) ...")

    stop_event: threading.Event = _sessions[sid]["stop_event"]

    async with async_playwright() as pw:
        context = None
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(session_profile),
                headless=False,
                viewport={"width": 1440, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "executable doesn't exist" in exc_str or "install" in exc_str:
                _log(sid, "📥 Không tìm thấy trình duyệt Chromium của Playwright. Đang tự động tải và cài đặt (khoảng 150MB)...", "info")
                try:
                    from playwright._impl._driver import compute_driver_executable, get_driver_env
                    import subprocess
                    driver_executable, driver_cli = compute_driver_executable()
                    proc = subprocess.run([str(driver_executable), str(driver_cli), "install", "chromium"], env=get_driver_env(), capture_output=True, text=True)
                    if proc.returncode == 0:
                        _log(sid, "✅ Đã tải và cài đặt trình duyệt Chromium thành công. Thử mở lại...", "info")
                        context = await pw.chromium.launch_persistent_context(
                            user_data_dir=str(session_profile),
                            headless=False,
                            viewport={"width": 1440, "height": 900},
                            args=[
                                "--disable-blink-features=AutomationControlled",
                                "--disable-dev-shm-usage",
                                "--no-sandbox",
                            ],
                        )
                    else:
                        raise RuntimeError(f"Playwright driver returned exit code {proc.returncode}: {proc.stderr}")
                except Exception as install_exc:
                    _set_status(sid, "error",
                                error=f"Lỗi tải trình duyệt tự động: {install_exc}. Bạn có thể cài đặt thủ công.",
                                done=True)
                    _cleanup_session_profile(session_profile)
                    if gate_held:
                        try:
                            _TT_LOGIN_GATE.release()
                        except Exception:
                            pass
                    return
            else:
                # Retry once after cleanup
                _log(sid, f"⚠ Lần mở đầu thất bại: {exc}. Thử lại...", "warning")
                _cleanup_profile_locks(session_profile)
                await asyncio.sleep(2)
                try:
                    context = await pw.chromium.launch_persistent_context(
                        user_data_dir=str(session_profile),
                        headless=False,
                        viewport={"width": 1440, "height": 900},
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                        ],
                    )
                except Exception as exc2:
                    _set_status(sid, "error",
                                error=f"Không mở được trình duyệt: {exc2}",
                                done=True)
                    _cleanup_session_profile(session_profile)
                    if gate_held:
                        try:
                            _TT_LOGIN_GATE.release()
                        except Exception:
                            pass
                    return

        # Store context on session so /prepare_close can shut it down.
        with _sessions_lock:
            _sessions[sid]["_context"] = context
            _sessions[sid]["_session_profile"] = session_profile

        # Inject saved cookies from master state (extra safety net beyond
        # the file-level profile copy, which can miss data if SQLite was locked).
        await _load_tiktok_state(context, _TT_PROFILE_DIR, sid)

        try:
            page = context.pages[0] if context.pages else await context.new_page()

            _log(sid, f"🌐 Vào {TIKTOK_UPLOAD_URL}")
            try:
                await page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                _log(sid, f"⚠ goto chậm: {exc}", "warning")

            # If redirected to login but we have saved cookies, reload once to
            # let TikTok pick them up (the initial goto raced the cookie inject).
            if ("login" in (page.url or "") or "verify" in (page.url or "")) and \
               (_TT_PROFILE_DIR / ".tiktok_state.json").exists():
                _log(sid, "🔄 Thử reload để TikTok nhận diện phiên đã lưu...", "info")
                try:
                    await page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    pass

            # If redirected to login → let user log in. We wait (up to 10 min) for
            # them to return to the studio URL.
            if "login" in (page.url or "") or "verify" in (page.url or ""):
                _log(sid, "🔐 Cần đăng nhập TikTok — hãy đăng nhập trong cửa sổ đang mở.", "warning")
                _log(sid, "⏳ Các session khác đang chờ bạn đăng nhập xong...", "info")
                _set_status(sid, "waiting_login")
                deadline = time.time() + 600
                while time.time() < deadline and not stop_event.is_set():
                    try:
                        cur = page.url or ""
                    except Exception:
                        break
                    if "tiktokstudio/upload" in cur:
                        break
                    await asyncio.sleep(1.5)
                if "tiktokstudio/upload" not in (page.url or ""):
                    _set_status(sid, "error", error="Người dùng chưa đăng nhập trong 10 phút.", done=True)
                    return
                _log(sid, "✅ Đã đăng nhập. Đồng bộ cookies về master profile...")
                # Use Playwright's storage_state API — works reliably while
                # browser is open, unlike file copy which can hit SQLite locks.
                await _save_tiktok_state(context, _TT_PROFILE_DIR, sid)
                _log(sid, "✅ Cookies đã được lưu. Session khác có thể chạy song song.", "success")

            # Release the login gate now — master profile has valid cookies.
            if gate_held:
                try:
                    _TT_LOGIN_GATE.release()
                    gate_held = False
                except Exception:
                    pass

            _set_status(sid, "uploading")

            # TikTok Studio has a hidden <input type="file"> on the upload page.
            # We inject the file directly into it without clicking any button
            # (clicking the visible button opens a native file dialog which
            # Playwright cannot control and blocks the flow).
            _log(sid, "📎 Tìm ô chọn file (hidden input)...")
            file_input = None
            deadline = time.time() + 30
            while time.time() < deadline and not stop_event.is_set():
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    break
                await asyncio.sleep(1)

            if not file_input:
                # Sometimes TikTok lazy-loads the input. Scroll or wait more.
                _log(sid, "⏳ Input chưa xuất hiện, chờ thêm 30 giây...")
                deadline2 = time.time() + 30
                while time.time() < deadline2 and not stop_event.is_set():
                    file_input = await page.query_selector('input[type="file"]')
                    if file_input:
                        break
                    # Gentle scroll to trigger lazy load
                    try:
                        await page.mouse.wheel(0, 300)
                    except Exception:
                        pass
                    await asyncio.sleep(2)

            if not file_input:
                _set_status(sid, "error",
                            error="Không tìm thấy input[type=file] trên trang TikTok Studio. Hãy kéo-thả file vào cửa sổ.",
                            done=True)
                _log(sid, "❌ Không tìm thấy input file. Bạn kéo-thả file thủ công vào cửa sổ đang mở.", "error")
                # Keep browser open so user can drag-drop manually
                idle_deadline = time.time() + 600
                while time.time() < idle_deadline and not stop_event.is_set():
                    try:
                        if not context.pages:
                            break
                        await page.evaluate("() => 1")
                    except Exception:
                        break
                    await asyncio.sleep(2)
                return

            await file_input.set_input_files(str(video_path))
            _log(sid, f"📁 Đã gắn file: {video_path.name}")

            # Wait for TikTok to finish encoding/processing the preview. Heuristic:
            # caption editor appears after upload. Max wait 5 min for big files.
            _log(sid, "⏳ Chờ TikTok xử lý video preview...")
            caption_selectors = [
                'div[contenteditable="true"][data-placeholder]',
                'div[contenteditable="true"][aria-label*="description" i]',
                'div[contenteditable="true"][aria-label*="caption" i]',
                'div.public-DraftEditor-content[contenteditable="true"]',
                'div[contenteditable="true"]',
            ]
            caption_el = None
            deadline = time.time() + 300
            while time.time() < deadline and not stop_event.is_set():
                for sel in caption_selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            caption_el = el
                            break
                    except Exception:
                        pass
                if caption_el:
                    break
                await asyncio.sleep(1)

            if not caption_el:
                _log(sid, "⚠ Không tìm thấy ô caption. Bạn điền tay giúp nhé.", "warning")
            elif caption:
                try:
                    await caption_el.click()
                    # Clear existing placeholder / content, then type caption.
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                    # type() fires input events TikTok's draft editor listens to.
                    await caption_el.type(caption, delay=10)
                    _log(sid, f"✍ Đã điền caption ({len(caption)} ký tự)")
                except Exception as exc:
                    _log(sid, f"⚠ Điền caption thất bại: {exc}. Hãy paste tay.", "warning")
            else:
                _log(sid, "ℹ Caption trống — bỏ qua bước điền.")

            # ── Privacy: chỉnh dropdown "Who can see this post" ──
            privacy = _sessions[sid].get("privacy")
            if privacy:
                await _try_set_privacy(page, privacy, sid)

            # ── Schedule: bật toggle đặt lịch nếu có scheduled_time ──
            scheduled_time = _sessions[sid].get("scheduled_time")
            if scheduled_time:
                _log(sid, f"📅 Đặt lịch đăng: {scheduled_time}")
                await _try_enable_schedule(page, scheduled_time, sid)

            _set_status(sid, "ready")
            _log(sid, "✅ Sẵn sàng. Kiểm tra lại rồi nhấn Post trong cửa sổ TikTok.", "success")

            # Hold open: user reviews and posts manually. We close when:
            #  - user explicitly requests close via /prepare_close, or
            #  - browser window is closed by user, or
            #  - 30 minute idle timeout.
            idle_deadline = time.time() + 1800
            while time.time() < idle_deadline and not stop_event.is_set():
                try:
                    if not context.pages:
                        break
                    # Check if the page is still open
                    await page.evaluate("() => 1")
                except Exception:
                    break
                await asyncio.sleep(2)

            _log(sid, "👋 Đóng phiên TikTok Studio.")

        finally:
            # Save state BEFORE closing the browser (storage_state needs an
            # open context; file-level sync can miss writes from open SQLite).
            try:
                await _save_tiktok_state(context, _TT_PROFILE_DIR, sid)
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            # Cleanup session profile (no longer need file-level sync back since
            # storage_state above already captured everything)
            _cleanup_session_profile(session_profile)
            # Release login gate if still held (e.g. login timeout path)
            if gate_held:
                try:
                    _TT_LOGIN_GATE.release()
                except Exception:
                    pass

    _set_status(sid, "closed", done=True)


def _launch_session_thread(sid: str, video_path: Path, caption: str):
    def _runner():
        try:
            asyncio.run(_run_upload_flow(sid, video_path, caption))
        except Exception as exc:  # noqa: BLE001
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"❌ Lỗi: {exc}", "error")

    t = threading.Thread(target=_runner, daemon=True)
    t.start()


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/api/tiktok/prepare_upload", methods=["POST"])
def tt_prepare_upload():
    data = request.json or {}
    video_path_str = str(data.get("video_path") or "").strip()
    caption = str(data.get("caption") or "").strip()
    scheduled_time = str(data.get("scheduled_time") or "").strip()
    privacy = str(data.get("privacy") or "").strip().upper()
    if not video_path_str:
        return jsonify({"ok": False, "error": "Thiếu video_path"}), 400

    # Resolve relative paths to workspace ROOT
    vp = Path(video_path_str)
    if not vp.is_absolute():
        vp = ROOT / vp
    # If file not found at the direct path, try common output directories
    if not vp.exists():
        for subdir in ("Downloaded", "output", "downloads"):
            candidate = ROOT / subdir / Path(video_path_str).name
            if candidate.exists():
                vp = candidate
                break
    if not vp.exists():
        return jsonify({"ok": False, "error": f"File không tồn tại: {vp}"}), 404
    if vp.suffix.lower() not in (".mp4", ".mov", ".webm"):
        return jsonify({"ok": False, "error": f"Định dạng {vp.suffix} không hỗ trợ (cần mp4/mov/webm)"}), 400

    # Ensure playwright is available before we bother the user.
    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium",
        }), 500

    sid = uuid.uuid4().hex[:12]
    with _sessions_lock:
        s = _new_session()
        if scheduled_time:
            s["scheduled_time"] = scheduled_time
        if privacy:
            s["privacy"] = privacy
        _sessions[sid] = s

    _log(sid, f"📥 Nhận yêu cầu upload TikTok: {vp.name}")
    if scheduled_time:
        _log(sid, f"📅 Sẽ đặt lịch: {scheduled_time}")
    if privacy:
        _log(sid, f"🔒 Privacy: {privacy}")
    _launch_session_thread(sid, vp, caption)
    return jsonify({"ok": True, "session_id": sid})


@bp.route("/api/tiktok/prepare_status", methods=["GET"])
def tt_prepare_status():
    sid = str(request.args.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "Thiếu session_id"}), 400
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "Session không tồn tại"}), 404
        # Drain log (UI polls, we keep full history but can trim old entries)
        return jsonify({
            "ok": True,
            "status": s["status"],
            "log": s["log"][-200:],      # cap response size
            "done": s["done"],
            "error": s["error"],
        })


@bp.route("/api/tiktok/prepare_close", methods=["POST"])
def tt_prepare_close():
    data = request.json or {}
    sid = str(data.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "Thiếu session_id"}), 400
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "Session không tồn tại"}), 404
        s["stop_event"].set()
    _log(sid, "⏹ Người dùng yêu cầu đóng phiên")
    return jsonify({"ok": True})


@bp.route("/api/tiktok/profile_reset", methods=["POST"])
def tt_profile_reset():
    """Xóa profile browser — user sẽ phải đăng nhập lại lần sau."""
    import shutil
    try:
        if _TT_PROFILE_DIR.exists():
            shutil.rmtree(str(_TT_PROFILE_DIR))
        # Also clean up any leftover session profiles
        sessions_dir = ROOT / ".tiktok_sessions"
        if sessions_dir.exists():
            shutil.rmtree(str(sessions_dir), ignore_errors=True)
        return jsonify({"ok": True, "message": "Đã xóa profile. Lần sau phải đăng nhập lại."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Login check / pre-login flow ──────────────────────────────────────────────
# Used by the batch queue preflight: verify TikTok login BEFORE starting a long
# batch, so the user logs in once at the start instead of being prompted mid-run.

@bp.route("/api/tiktok/check_login", methods=["GET"])
def tt_check_login():
    """Quick check: does the master profile have TikTok login cookies?"""
    logged_in = _has_login_cookies(_TT_PROFILE_DIR)
    return jsonify({"ok": True, "logged_in": logged_in})


async def _run_login_flow(sid: str):
    """Open a TikTok Studio browser window for the sole purpose of logging in.
    Once the user reaches the upload page, we sync cookies to the master profile
    and close the browser. Subsequent upload sessions can then run without
    needing to log in again."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _set_status(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return

    _TT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_profile_locks(_TT_PROFILE_DIR)

    _set_status(sid, "launching")
    _log(sid, "🔐 Mở trình duyệt để đăng nhập TikTok...")

    stop_event: threading.Event = _sessions[sid]["stop_event"]

    async with async_playwright() as pw:
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_TT_PROFILE_DIR),
                headless=False,
                viewport={"width": 1440, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        except Exception as exc:
            _set_status(sid, "error", error=f"Không mở được trình duyệt: {exc}", done=True)
            return

        with _sessions_lock:
            _sessions[sid]["_context"] = context

        try:
            # Try to restore saved state (in case user logged in before but
            # master profile's native cookie DB was wiped/corrupted).
            await _load_tiktok_state(context, _TT_PROFILE_DIR, sid)

            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                _log(sid, f"⚠ goto chậm: {exc}", "warning")

            # If redirected to login but we just injected saved cookies, reload
            # once to let TikTok re-check auth state with the new cookies.
            if ("login" in (page.url or "") or "verify" in (page.url or "")) and \
               (_TT_PROFILE_DIR / ".tiktok_state.json").exists():
                _log(sid, "🔄 Có cookies cũ — thử reload để TikTok nhận diện phiên...", "info")
                try:
                    await page.goto(TIKTOK_UPLOAD_URL, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    pass

            # If already on the upload page → we're logged in
            if "tiktokstudio/upload" in (page.url or ""):
                _log(sid, "✅ Đã đăng nhập sẵn rồi.", "success")
                # Re-save state to refresh any updated session tokens
                await _save_tiktok_state(context, _TT_PROFILE_DIR, sid)
                _set_status(sid, "ready", done=True)
                return

            _set_status(sid, "waiting_login")
            _log(sid, "🔐 Hãy đăng nhập TikTok trong cửa sổ đang mở. Chờ tối đa 10 phút...", "warning")

            deadline = time.time() + 600
            while time.time() < deadline and not stop_event.is_set():
                try:
                    cur = page.url or ""
                except Exception:
                    break
                if "tiktokstudio/upload" in cur or "tiktok.com/tiktokstudio" in cur:
                    break
                await asyncio.sleep(1.5)

            if "tiktokstudio" not in (page.url or ""):
                _set_status(sid, "error",
                            error="Người dùng chưa đăng nhập trong 10 phút.",
                            done=True)
                return

            _log(sid, "✅ Đăng nhập thành công. Đang lưu phiên...")
            # Give Chromium a moment to settle, then save state via Playwright API
            await asyncio.sleep(2)
            saved = await _save_tiktok_state(context, _TT_PROFILE_DIR, sid)
            if saved:
                _log(sid, "💾 Đã lưu phiên đăng nhập thành công.", "success")
            else:
                _log(sid, "⚠ Lưu phiên thất bại — có thể phải đăng nhập lại lần sau.", "warning")
            _set_status(sid, "ready", done=True)

        finally:
            # Save once more right before close (in case user did something after login)
            try:
                await _save_tiktok_state(context, _TT_PROFILE_DIR, sid)
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass


@bp.route("/api/tiktok/open_login", methods=["POST"])
def tt_open_login():
    """Mở cửa sổ trình duyệt để user đăng nhập TikTok một lần.
    Trả về session_id để UI poll trạng thái."""
    # If already logged in, short-circuit
    if _has_login_cookies(_TT_PROFILE_DIR):
        return jsonify({"ok": True, "already_logged_in": True})

    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium",
        }), 500

    sid = "login-" + uuid.uuid4().hex[:8]
    with _sessions_lock:
        _sessions[sid] = _new_session()

    _log(sid, "📥 Yêu cầu mở cửa sổ đăng nhập TikTok")

    def _runner():
        try:
            asyncio.run(_run_login_flow(sid))
        except Exception as exc:
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"❌ Lỗi: {exc}", "error")

    threading.Thread(target=_runner, daemon=True).start()
    return jsonify({"ok": True, "session_id": sid, "already_logged_in": False})

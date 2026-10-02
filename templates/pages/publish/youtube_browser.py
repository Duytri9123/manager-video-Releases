"""YouTube Studio browser login and upload for users without OAuth credentials."""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request
from core_app import ROOT

PROFILE = ROOT / ".youtube_browser_profile"
STUDIO = "https://studio.youtube.com/"
_sessions = {}
_lock = threading.Lock()


def _profile_for_account(account_id: str) -> Path:
    if not account_id:
        return PROFILE
    safe_id = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16]
    return ROOT / ".youtube_browser_profiles" / safe_id


def _update(sid, status=None, message=None, error=None, done=None):
    with _lock:
        item = _sessions[sid]
        if status is not None:
            item["status"] = status
        if message:
            item["log"].append(message)
        if error is not None:
            item["error"] = error
        if done is not None:
            item["done"] = done


def _start(kind, data=None):
    sid = uuid.uuid4().hex[:12]
    with _lock:
        _sessions[sid] = {"status": "starting", "log": [], "error": "", "done": False}
    def runner():
        try:
            asyncio.run(_run(sid, kind, data or {}))
        except Exception as exc:
            _update(sid, "error", error=str(exc), done=True)
    threading.Thread(target=runner, daemon=True).start()
    return sid


async def _studio_ready(page):
    url = page.url or ""
    return url.startswith("https://studio.youtube.com/channel/") or (
        url.startswith(STUDIO) and bool(
            await page.locator("#avatar-btn, ytcp-icon-button#avatar-btn, button[aria-label*='Account']").count()
        )
    )


async def _run(sid, kind, data):
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _update(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return
    profile = _profile_for_account(str(data.get("account_id") or "").strip())
    profile.mkdir(parents=True, exist_ok=True)
    # Each upload needs its own Chromium profile. An unfinished post must not
    # lock the account profile or block the next video's browser window.
    session_profile = ROOT / ".youtube_browser_sessions" / sid
    browser_profile = profile
    if kind != "login":
        shutil.copytree(profile, session_profile, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("Cache", "Code Cache", "GPUCache", "Singleton*", "lockfile"))
        browser_profile = session_profile
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(browser_profile), headless=False, no_viewport=True,
            locale="en-US",
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            _update(sid, "opening", "Đang mở YouTube Studio trong trình duyệt...")
            await page.goto(STUDIO, wait_until="domcontentloaded", timeout=60000)
            deadline = time.time() + 600
            while time.time() < deadline:
                if await _studio_ready(page):
                    break
                _update(sid, "waiting_login")
                await asyncio.sleep(2)
            else:
                _update(sid, "error", error="Chưa đăng nhập YouTube Studio trong 10 phút.", done=True)
                return
            (profile / ".connected").write_text("1", encoding="ascii")
            _update(sid, "authenticated", "Đã đăng nhập YouTube Studio.")
            if kind == "login":
                _update(sid, "ready", done=True)
                return

            video = Path(data["video_path"])
            _update(sid, "uploading", "Đang mở hộp tải video YouTube...")
            await page.get_by_role("button", name="Create").first.click(timeout=30000)
            await page.get_by_text("Upload videos", exact=True).first.click(timeout=30000)
            await page.locator('input[type="file"]').first.set_input_files(str(video), timeout=30000)
            dialog = page.get_by_role("dialog").first
            await dialog.wait_for(state="visible", timeout=60000)
            title = dialog.locator("#textbox").first
            await title.fill(str(data.get("title") or video.stem)[:100])
            description = str(data.get("description") or "")
            if description:
                await dialog.locator("#textbox").nth(1).fill(description)
            kids = bool(data.get("made_for_kids"))
            await dialog.get_by_text("Yes, it's made for kids" if kids else "No, it's not made for kids").first.click(timeout=20000)
            for _ in range(3):
                await dialog.get_by_role("button", name="Next").click(timeout=30000)
            privacy = str(data.get("privacy_status") or "private").lower()
            label = {"private": "Private", "unlisted": "Unlisted", "public": "Public"}.get(privacy, "Private")
            await dialog.get_by_text(label, exact=True).first.click(timeout=20000)
            finish = dialog.get_by_role("button", name="Publish" if privacy == "public" else "Save")
            if not await finish.count():
                finish = dialog.get_by_role("button", name="Done")
            await finish.wait_for(state="visible", timeout=300000)
            deadline = time.time() + 300
            while time.time() < deadline and not await finish.is_enabled():
                await asyncio.sleep(2)
            if not await finish.is_enabled():
                raise TimeoutError("YouTube chưa tải xong video trong 5 phút.")
            if data.get("auto_publish"):
                await finish.click(timeout=30000)
                _update(sid, "submitted", "Đã bấm đăng trên YouTube Studio; hãy kiểm tra xác nhận trong cửa sổ.", done=True)
            else:
                _update(sid, "ready", "Video đã sẵn sàng. Hãy kiểm tra và bấm Đăng/Lưu trong trình duyệt.", done=True)
                deadline = time.time() + 1800
                while time.time() < deadline and not page.is_closed():
                    await asyncio.sleep(2)
        finally:
            await context.close()
            if kind != "login" and session_profile.exists():
                shutil.rmtree(session_profile, ignore_errors=True)


def register(bp):
    @bp.route("/api/youtube_browser/status", methods=["GET"])
    def status():
        sid = str(request.args.get("session_id") or "")
        if sid:
            with _lock:
                item = _sessions.get(sid)
                return jsonify({"ok": bool(item), **(dict(item) if item else {"error": "Session không tồn tại"})})
        profile = _profile_for_account(str(request.args.get("account_id") or "").strip())
        return jsonify({"ok": True, "connected": (profile / ".connected").exists()})

    @bp.route("/api/youtube_browser/login", methods=["POST"])
    def login():
        data = request.get_json(silent=True) or {}
        return jsonify({"ok": True, "session_id": _start("login", data)})

    @bp.route("/api/youtube_browser/upload", methods=["POST"])
    def upload():
        data = request.get_json(silent=True) or {}
        video = Path(str(data.get("video_path") or ""))
        if not video.is_file() or video.suffix.lower() not in (".mp4", ".mov", ".webm"):
            return jsonify({"ok": False, "error": "File video không hợp lệ"}), 400
        if data.get("publish_at"):
            return jsonify({"ok": False, "error": "Đặt lịch bằng trình duyệt chưa hỗ trợ; dùng kết nối OAuth."}), 400
        data["video_path"] = str(video.resolve())
        return jsonify({"ok": True, "session_id": _start("upload", data)})

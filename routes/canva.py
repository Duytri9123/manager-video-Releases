"""Canva Auto Blueprint — Playwright tự mở Canva và điền nội dung.

Why semi-auto:
- Canva không cung cấp public API để chỉnh sửa template + render video.
- Playwright là cách thực tế nhất để điều khiển Canva như người dùng.

Endpoints
─────────
POST /api/canva/check_login         kiểm tra master profile có cookies Canva chưa
POST /api/canva/open_login          mở Chromium để user login Canva một lần
POST /api/canva/profile_reset       xoá profile (login lại)
POST /api/canva/upload_image        upload 1 ảnh lên server, trả về path tuyệt đối
POST /api/canva/prepare_design      bắt đầu phiên: mở template, paste text, upload ảnh, export
GET  /api/canva/prepare_status      poll status + log
POST /api/canva/prepare_close       đóng phiên đang chạy

Cờ-hi-end principle:
- Không phá vỡ ToS — luôn để cửa sổ trình duyệt hiển thị, user có thể can thiệp.
- Mọi selector đều fallback nhiều lớp vì Canva đổi class thường xuyên.
- Fail mềm: nếu không click được phần tử nào, log warning và để user thao tác tay.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from core_app import LOGGER, ROOT

bp = Blueprint("canva", __name__)

CANVA_HOME_URL = "https://www.canva.com/"
CANVA_LOGIN_URL = "https://www.canva.com/login/"

# Persistent Chromium profile dir (login state)
_CV_PROFILE_DIR = ROOT / ".canva_profile"
_CV_UPLOAD_DIR = ROOT / "temp_uploads" / "canva"
_CV_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Local library of graphics scraped from creator portfolio pages.
#   <root>/storage/canva_library/<creator>/<n>.png
#   <root>/storage/canva_library/<creator>/_index.json   (metadata: name, src URL, tags, etc.)
_CV_LIBRARY_DIR = ROOT / "storage" / "canva_library"
_CV_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

# Sessions registry
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()
_LOGIN_GATE = threading.Lock()

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
                    ".mp3", ".wav", ".m4a", ".aac", ".ogg"}


# ── Session helpers ──────────────────────────────────────────────────────────
def _new_session() -> Dict[str, Any]:
    return {
        "status": "starting",
        "log": [],
        "error": "",
        "done": False,
        "progress": 0,
        "progress_label": "",
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
    LOGGER.info("[canva %s] %s", sid, msg)


def _set_status(sid: str, status: str, *, error: str = "", done: bool = False,
                progress: Optional[int] = None, progress_label: str = ""):
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return
        s["status"] = status
        if error:
            s["error"] = error
        if done:
            s["done"] = True
        if progress is not None:
            s["progress"] = max(0, min(100, int(progress)))
        if progress_label:
            s["progress_label"] = progress_label
        s["updated_at"] = time.time()


# ── Profile / login helpers ──────────────────────────────────────────────────
def _has_login_cookies(profile_dir: Path) -> bool:
    """Check if master profile has saved Canva login state."""
    try:
        state_file = profile_dir / ".canva_state.json"
        if state_file.exists():
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
            cookies = data.get("cookies", [])
            cv_cookies = [c for c in cookies if "canva" in (c.get("domain") or "").lower()]
            if cv_cookies:
                return True
        # Fallback: check Chromium native cookies file size
        cookies_file = profile_dir / "Default" / "Cookies"
        if cookies_file.exists() and cookies_file.stat().st_size > 16384:
            return True
        return False
    except Exception:
        return False


async def _save_state(context, profile_dir: Path, sid: Optional[str] = None):
    state_file = profile_dir / ".canva_state.json"
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(state_file))
        if sid:
            _log(sid, "💾 Đã lưu phiên đăng nhập Canva.", "info")
        return True
    except Exception as exc:
        if sid:
            _log(sid, f"⚠ Lưu storage_state thất bại: {exc}", "warning")
        return False


def _cleanup_profile_locks(profile_dir: Path):
    """Remove stale Chromium lock files."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = profile_dir / name
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


# ── Core: open Canva, paste text, upload, export ────────────────────────────
async def _wait_logged_in(page, sid: str, timeout: int = 600) -> bool:
    """Wait until the Canva home loads with a logged-in indicator."""
    deadline = time.time() + timeout
    stop_event = _sessions[sid]["stop_event"]
    while time.time() < deadline and not stop_event.is_set():
        try:
            url = page.url or ""
        except Exception:
            return False
        # Heuristic: avatar / profile button visible, or URL is /home or /design
        if any(part in url for part in ("/home", "/design", "/folder", "/account")):
            return True
        if "login" not in url and "signup" not in url:
            # check for an avatar element
            try:
                avatar = await page.query_selector(
                    'button[aria-label*="account" i], '
                    'button[aria-label*="profile" i], '
                    '[data-testid*="user-menu"], '
                    'img[alt*="avatar" i]'
                )
                if avatar:
                    return True
            except Exception:
                pass
        await asyncio.sleep(2)
    return False


async def _wait_for_editor(page, sid: str, timeout: int = 90) -> bool:
    """Wait until the Canva editor surface is fully loaded.

    The editor URL is /design/.../edit. We wait until both:
      - URL contains "/design/"
      - DOM has at least one strong editor marker (toolbar / sidebar tabs /
        canvas / contenteditable text)

    A blank video design has NO text boxes and NO page thumbnails initially,
    so we cannot rely on those alone. We use a layered JS scan that matches
    the editor's stable structures (top toolbar with Share button, left rail
    tabs, role=main canvas...) and returns as soon as ANY marker shows up.

    Newer Canva loads in 3–8s on a fast connection. Poll fast (0.6s) so we
    catch it the moment it's ready, instead of waiting up to 1.5s extra.
    """
    deadline = time.time() + timeout
    stop_event = _sessions[sid]["stop_event"]
    started = time.time()
    last_log = 0.0
    last_marker = ""

    js_check = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      // 1) Any contenteditable text on canvas (template w/ text)
      if (document.querySelector('div[role="textbox"][contenteditable="true"]'))
        return 'textbox';
      // 2) Page thumbnail rail (template/saved design)
      if (document.querySelector(
          '[data-testid="page-thumbnail"], [data-testid*="page-thumbnail"], '
          + '[aria-roledescription="page"], [class*="PageThumbnail"]'))
        return 'thumb';
      // 3) Editor canvas surface (works for blank designs too)
      if (document.querySelector('main[role="main"] canvas')) return 'canvas';
      if (document.querySelector('div[class*="EditorCanvas"]')) return 'editor-canvas-class';
      // 4) Editor left rail tabs (Thiết kế / Thành phần / Văn bản / Tải lên)
      const tabs = document.querySelectorAll('button[role="tab"][aria-controls], [role="tab"][aria-controls]');
      for (const t of tabs) {
        const aria = norm(t.getAttribute('aria-label'));
        const innerAria = norm(t.querySelector('[aria-label]')?.getAttribute('aria-label'));
        const blob = (aria + ' ' + innerAria).toLowerCase();
        if (/(thành phần|thiết kế|văn bản|tải lên|elements|design|text|uploads)/.test(blob)) {
          const r = t.getBoundingClientRect();
          if (r.x < 120 && r.width > 20) return 'left-rail-tab';
        }
      }
      // 5) Top-right toolbar Share / Tải xuống / Resize buttons
      const btns = document.querySelectorAll('button, [role="button"]');
      for (const b of btns) {
        const aria = norm(b.getAttribute('aria-label'));
        const txt = norm(b.textContent);
        const r = b.getBoundingClientRect();
        if (r.y > 80 || r.x < window.innerWidth - 600) continue;
        if (/^(Chia sẻ|Share|Tải xuống|Download|Thay đổi kích thước|Resize)$/i.test(aria)
            || /^(Chia sẻ|Share|Tải xuống|Download)$/i.test(txt)) {
          return 'top-toolbar';
        }
      }
      // 6) Editor footer / page navigator (Trang 1 / N)
      const pageLabel = document.querySelector('[aria-label*="Trang " i], [aria-label*="Page " i]');
      if (pageLabel) {
        const aria = norm(pageLabel.getAttribute('aria-label'));
        if (/^(Trang|Page)\\s+\\d/i.test(aria)) return 'page-nav-label';
      }
      return null;
    }
    """

    while time.time() < deadline and not stop_event.is_set():
        try:
            url = page.url or ""
        except Exception:
            return False
        if "/design/" in url and "/edit" in url:
            try:
                marker = await page.evaluate(js_check)
                if marker:
                    if marker != last_marker:
                        elapsed = int(time.time() - started)
                        _log(sid, f"✅ Editor ready sau {elapsed}s (marker: {marker}).", "success")
                    return True
            except Exception:
                pass
        if time.time() - last_log > 5:
            _log(sid, f"⏳ Chờ editor hydrate... ({int(time.time() - started)}s) — URL: {url[:80]}")
            last_log = time.time()
        await asyncio.sleep(0.6)
    _log(sid, f"⏰ Hết {timeout}s mà chưa thấy marker editor — sẽ vẫn thử bước tiếp theo.", "warning")
    return False


async def _ensure_editor_page(context, current_page, sid: str, timeout: int = 30):
    """Return a Page object that's currently on /design/.../edit.

    Strategy:
      1. If `current_page` is on the editor → keep it.
      2. Otherwise scan all open tabs for one with `/design/.../edit` URL.
      3. Otherwise wait up to `timeout`s for a new tab to appear with that URL.
      4. Fall back to `current_page` and return None to signal failure.

    Returns: (page, ok) where page is the best candidate and ok is True only
    if a real editor page was found.
    """
    def _is_editor(url: str) -> bool:
        return "/design/" in (url or "") and "/edit" in (url or "")

    # 1. Current page on editor?
    try:
        if _is_editor(current_page.url):
            return current_page, True
    except Exception:
        pass

    # 2. Any open tab on editor?
    try:
        for p in context.pages:
            try:
                if _is_editor(p.url):
                    if p is not current_page:
                        try:
                            await p.bring_to_front()
                        except Exception:
                            pass
                        _log(sid, f"🔁 Switched sang tab editor: {p.url[:90]}", "info")
                    return p, True
            except Exception:
                pass
    except Exception:
        pass

    # 3. Wait for new tab
    deadline = time.time() + timeout
    stop_event = _sessions[sid]["stop_event"]
    while time.time() < deadline and not stop_event.is_set():
        try:
            for p in context.pages:
                try:
                    if _is_editor(p.url):
                        if p is not current_page:
                            try:
                                await p.bring_to_front()
                            except Exception:
                                pass
                            _log(sid, f"🔁 Editor tab xuất hiện: {p.url[:90]}", "info")
                        return p, True
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(1.0)

    return current_page, False


async def _find_page_thumbs(page):
    """Return the list of page thumbnails / page surfaces in the editor's
    bottom timeline / left rail.

    IMPORTANT: must NOT match the "Trang chủ" (Home) button in the Canva home
    sidebar — that button has aria-label="Trang chủ" and clicking it navigates
    away from the editor. We use a JS regex to require digit-suffixed labels
    like "Trang 1", "Trang 2", "Page 1", etc.
    """
    # Reject if not in editor
    try:
        cur_url = page.url or ""
    except Exception:
        cur_url = ""
    if "/design/" not in cur_url:
        return [], None

    js_find = """
    () => {
      const out = [];
      const all = document.querySelectorAll(
        '[data-testid="page-thumbnail"], '
        + '[data-testid*="page-thumbnail"], '
        + '[data-testid*="thumbnail"][role="button"], '
        + '[aria-roledescription="page"], '
        + '[aria-label], '
        + '[class*="PageThumbnail"]'
      );
      const seen = new Set();
      for (const el of all) {
        if (seen.has(el)) continue;
        const aria = (el.getAttribute('aria-label') || '').trim();
        const roleDesc = (el.getAttribute('aria-roledescription') || '').trim();
        const testid = (el.getAttribute('data-testid') || '').trim();
        const cls = el.className || '';
        // Require:
        //   - aria-label like "Trang N", "Page N", "Trang N của ..."
        //   - OR aria-roledescription="page"
        //   - OR data-testid containing "page-thumbnail"
        //   - OR class containing "PageThumbnail"
        const ariaOk = /^(Trang|Page)\\s+\\d/i.test(aria) || /^Slide\\s+\\d/i.test(aria);
        const roleOk = roleDesc === 'page';
        const testOk = /page[-_]?thumb/i.test(testid);
        const clsOk = typeof cls === 'string' && /PageThumbnail/i.test(cls);
        if (!(ariaOk || roleOk || testOk || clsOk)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 20 || r.height < 20) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        seen.add(el);
        out.push({el, aria, roleDesc, testid,
                  x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height)});
      }
      // Sort top→bottom (left rail) or left→right (timeline) by smallest axis
      out.sort((a, b) => (a.y - b.y) || (a.x - b.x));
      // Tag elements via a temporary attribute so Playwright can re-resolve them
      out.forEach((e, i) => e.el.setAttribute('data-cv-page-thumb-idx', String(i)));
      return out.map(e => ({aria: e.aria, x: e.x, y: e.y, w: e.w, h: e.h}));
    }
    """
    try:
        infos = await page.evaluate(js_find)
    except Exception:
        return [], None

    if not infos:
        return [], None

    # Re-resolve to ElementHandles via the temporary attribute we set
    handles = []
    for i in range(len(infos)):
        try:
            h = await page.query_selector(f'[data-cv-page-thumb-idx="{i}"]')
            if h:
                handles.append(h)
        except Exception:
            pass

    return handles, "page-thumb (js-regex)"


async def _find_text_targets(page) -> List[Any]:
    """Return all editable text candidates currently visible on canvas."""
    out = []
    selectors = [
        'div[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"][data-text]',
        '[aria-label*="text element" i][contenteditable]',
        'span[role="textbox"]',
        'div[contenteditable="true"]',
    ]
    seen = set()
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                try:
                    if not await el.is_visible():
                        continue
                    box = await el.bounding_box()
                    if not box:
                        continue
                    if box.get("width", 0) < 30 or box.get("height", 0) < 12:
                        continue
                    key = (round(box["x"]), round(box["y"]),
                           round(box["width"]), round(box["height"]))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(el)
                except Exception:
                    pass
        except Exception:
            continue
    # Sort top-to-bottom, left-to-right
    decorated = []
    for el in out:
        try:
            box = await el.bounding_box()
            decorated.append((box["y"] if box else 0, box["x"] if box else 0, el))
        except Exception:
            decorated.append((0, 0, el))
    decorated.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in decorated]


async def _paste_text_via_clipboard(page, text: str) -> None:
    """Place `text` on the system clipboard then send Ctrl+V.

    Faster + supports Vietnamese diacritics + multi-line correctly. Falls back
    to keyboard.type if clipboard fails.
    """
    try:
        # Use Playwright's evaluate with the async clipboard API
        await page.evaluate(
            "async (t) => { try { await navigator.clipboard.writeText(t); } catch(e){} }",
            text,
        )
        await asyncio.sleep(0.15)
        await page.keyboard.press("Control+V")
    except Exception:
        await page.keyboard.type(text, delay=8)


async def _create_text_box_on_canvas(page, sid: str) -> bool:
    """Create a new text box on the currently-visible Canva page.

    Why we need this: on a BLANK design, no text boxes exist yet. Trying to
    fill text into a non-existent box obviously fails.

    Strategy (in order):
      1. Keyboard shortcut: press "T" while editor is focused → Canva inserts
         a default heading text box at center of canvas, ready to type.
      2. If shortcut doesn't work, open the "Văn bản" (Text) tab in the left
         rail and click "Thêm tiêu đề" / "Thêm văn bản nội dung".
    """
    if "/design/" not in (page.url or ""):
        return False

    # ── Strategy 1: keyboard shortcut "T" ──
    try:
        # Click center of canvas first to focus the editor and deselect any
        # existing element (typing T while a text box is selected does
        # NOTHING USEFUL).
        canvas = await page.query_selector('main[role="main"]')
        if canvas:
            box = await canvas.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                await page.mouse.click(cx, cy)
                await asyncio.sleep(0.3)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.2)
        # Press T (lowercase). Canva treats this as the text shortcut.
        await page.keyboard.press("t")
        await asyncio.sleep(0.8)
        # Verify a contenteditable text box now exists
        targets = await _find_text_targets(page)
        if targets:
            _log(sid, "🆕 Tạo text box bằng phím tắt T.", "success")
            return True
    except Exception as exc:
        _log(sid, f"⚠ Phím tắt T lỗi: {exc}", "warning")

    # ── Strategy 2: open Văn bản panel + click "Thêm tiêu đề" ──
    js_open_text_panel = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const tabs = document.querySelectorAll('button[role="tab"][aria-controls], [role="tab"][aria-controls]');
      for (const t of tabs) {
        const aria = norm(t.getAttribute('aria-label'));
        const innerAria = norm(t.querySelector('[aria-label]')?.getAttribute('aria-label'));
        const txt = norm(t.textContent);
        if (/^(Văn bản|Text)$/i.test(aria) || /^(Văn bản|Text)$/i.test(innerAria)
            || /^(Văn bản|Text)$/i.test(txt)) {
          const r = t.getBoundingClientRect();
          if (r.x < 120) {
            t.click();
            return true;
          }
        }
      }
      return false;
    }
    """
    try:
        ok = await page.evaluate(js_open_text_panel)
        if ok:
            await asyncio.sleep(1.0)
        else:
            return False
    except Exception:
        return False

    # Click "Thêm tiêu đề"
    js_click_add_text = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button, [role="button"]');
      for (const el of all) {
        const txt = norm(el.textContent);
        const aria = norm(el.getAttribute('aria-label'));
        if (/^(Thêm tiêu đề|Add a heading|Thêm văn bản|Add text)$/i.test(aria + ' ' + txt)
            || /Thêm tiêu đề|Add a heading|Thêm văn bản nội dung|Add a subheading/i.test(txt)) {
          const r = el.getBoundingClientRect();
          if (r.x < 500 && r.width > 50) {
            el.click();
            return true;
          }
        }
      }
      return false;
    }
    """
    try:
        ok = await page.evaluate(js_click_add_text)
        if ok:
            await asyncio.sleep(1.0)
            targets = await _find_text_targets(page)
            if targets:
                _log(sid, "🆕 Tạo text box qua panel Văn bản.", "success")
                return True
    except Exception:
        pass

    return False


async def _fill_text_boxes(page, scenes: List[Dict[str, str]], sid: str) -> int:
    """Iterate Canva pages and paste each scene's TEXT into a text box on that page.

    `scenes` is a list of {text, keyword}. We use scene["text"].
    """
    filled = 0
    total = len(scenes)
    if total == 0:
        return 0

    # First, give the editor a moment after we open it — Canva keeps
    # streaming page elements in for a few seconds.
    await asyncio.sleep(2.0)

    page_thumbs, sel_used = await _find_page_thumbs(page)
    n_pages_template = len(page_thumbs) if page_thumbs else 0

    if page_thumbs:
        _log(sid, f"📑 Tìm thấy {n_pages_template} trang (selector: {sel_used}).")
    else:
        _log(sid, "⚠ Không tìm thấy danh sách trang ở rail trái — sẽ dùng PageDown để chuyển trang.", "warning")

    n = min(total, n_pages_template) if page_thumbs else total
    if page_thumbs and total > n_pages_template:
        _log(sid, f"⚠ Template có {n_pages_template} trang nhưng có {total} cảnh — chỉ điền {n} cảnh đầu.", "warning")

    for i in range(n):
        if _sessions[sid]["stop_event"].is_set():
            break
        text = scenes[i].get("text", "")
        if not text:
            continue

        # ── Navigate to page i ──
        if page_thumbs and i < len(page_thumbs):
            try:
                await page_thumbs[i].scroll_into_view_if_needed()
                await page_thumbs[i].click()
                await asyncio.sleep(1.0)
            except Exception as exc:
                _log(sid, f"⚠ Không click được thumbnail trang {i+1}: {exc}", "warning")
        else:
            if i > 0:
                try:
                    canvas_area = await page.query_selector('main[role="main"], div[class*="editor" i]')
                    if canvas_area:
                        try:
                            await canvas_area.click(position={"x": 50, "y": 50})
                        except Exception:
                            pass
                    await page.keyboard.press("PageDown")
                    await asyncio.sleep(0.8)
                except Exception:
                    pass

        # ── Find text targets on the now-visible page ──
        targets = await _find_text_targets(page)
        if not targets:
            await asyncio.sleep(1.5)
            targets = await _find_text_targets(page)

        # If still no text box (blank design), create one with the T shortcut.
        if not targets:
            _log(sid, f"ℹ Trang {i+1}: chưa có text box, tự tạo...", "info")
            created = await _create_text_box_on_canvas(page, sid)
            if created:
                await asyncio.sleep(0.5)
                targets = await _find_text_targets(page)

        if not targets:
            _log(sid, f"⚠ Trang {i+1}: không tìm thấy ô text editable. Bỏ qua paste.", "warning")
            continue

        target = targets[0]
        try:
            await target.scroll_into_view_if_needed()
            # Some text boxes are already in edit mode after creation — try
            # paste first, fall back to dblclick if needed.
            try:
                is_edit = await target.evaluate(
                    "el => el.getAttribute('contenteditable') === 'true' "
                    "&& el.matches(':focus, :focus-within')"
                )
            except Exception:
                is_edit = False
            if not is_edit:
                await target.dblclick()
                await asyncio.sleep(0.4)
            await page.keyboard.press("Control+A")
            await asyncio.sleep(0.15)
            await _paste_text_via_clipboard(page, text)
            await asyncio.sleep(0.3)
            await page.keyboard.press("Escape")
            filled += 1
            _log(sid, f"✏️ Trang {i+1}: đã paste {len(text)} ký tự.", "success")
        except Exception as exc:
            _log(sid, f"⚠ Trang {i+1}: lỗi khi paste: {exc}", "warning")

    return filled


async def _paste_into_current_page(page, text: str, sid: str, scene_idx: int = 1) -> bool:
    """Click the first editable text element on the visible canvas and paste."""
    if not text:
        return False
    targets = await _find_text_targets(page)
    if not targets:
        await asyncio.sleep(1.5)
        targets = await _find_text_targets(page)
    if not targets:
        # Blank canvas — auto-create a text box first
        created = await _create_text_box_on_canvas(page, sid)
        if created:
            await asyncio.sleep(0.5)
            targets = await _find_text_targets(page)
    if not targets:
        _log(sid, f"⚠ Trang {scene_idx}: không tìm thấy ô text. Hãy click vào template để chọn ô có sẵn.", "warning")
        return False
    target = targets[0]
    try:
        await target.scroll_into_view_if_needed()
        await target.dblclick()
        await asyncio.sleep(0.4)
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.15)
        await _paste_text_via_clipboard(page, text)
        await asyncio.sleep(0.2)
        await page.keyboard.press("Escape")
        _log(sid, f"✏️ Trang {scene_idx}: đã paste {len(text)} ký tự.", "success")
        return True
    except Exception as exc:
        _log(sid, f"⚠ Trang {scene_idx}: lỗi khi paste: {exc}", "warning")
        return False


async def _open_uploads_panel(page, sid: str) -> bool:
    """Open the left "Uploads" tab so user / our code can drag files in."""
    for sel in [
        'button[aria-label*="Upload" i]',
        'button[data-testid*="upload" i]',
        'button:has-text("Uploads")',
        'button:has-text("Tải lên")',
        '[role="tab"]:has-text("Uploads")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await asyncio.sleep(0.6)
                _log(sid, "📂 Đã mở panel Uploads.")
                return True
        except Exception:
            pass
    _log(sid, "⚠ Không mở được panel Uploads — hãy mở tay nếu cần upload ảnh.", "warning")
    return False


async def _upload_images(page, image_paths: List[str], sid: str) -> int:
    """Set files on Canva's hidden upload input."""
    if not image_paths:
        return 0
    valid = [p for p in image_paths if p and Path(p).exists()]
    if not valid:
        return 0

    # Open uploads panel first
    await _open_uploads_panel(page, sid)

    # Find file input — Canva's "Tải lên" panel exposes a generic
    # input[type="file"]; we prefer one whose accept covers our extensions.
    input_el = None
    has_audio = any(Path(p).suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
                    for p in valid)
    selectors = []
    if has_audio:
        selectors += ['input[type="file"][accept*="audio"]',
                      'input[type="file"][accept*="*"]']
    selectors += ['input[type="file"][accept*="image"]', 'input[type="file"]']
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            if els:
                input_el = els[0]
                break
        except Exception:
            continue

    if not input_el:
        _log(sid, "⚠ Không tìm thấy <input type='file'> trên Canva — hãy kéo thả tay.", "warning")
        return 0

    try:
        await input_el.set_input_files(valid)
        n_audio = sum(1 for p in valid
                      if Path(p).suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg"})
        n_img = len(valid) - n_audio
        parts = []
        if n_img:   parts.append(f"{n_img} ảnh")
        if n_audio: parts.append(f"{n_audio} audio")
        _log(sid, f"📤 Đã upload {' + '.join(parts) or len(valid)} lên Canva.", "success")
        return len(valid)
    except Exception as exc:
        _log(sid, f"⚠ Upload thất bại: {exc}", "warning")
        return 0


async def _add_uploaded_audio_to_timeline(page, sid: str) -> bool:
    """After uploading an MP3, click "Thêm âm thanh" in the timeline footer,
    then find and click the uploaded audio tile to add it as a track.

    Flow:
      1. Click the "🎵 Thêm âm thanh" button at the bottom of the timeline.
      2. This opens the Audio panel (Tải lên / Âm thanh sub-tab).
      3. Wait for the uploaded file to appear as a tile.
      4. Click the tile → Canva adds it as a background audio track.
    """
    if "/design/" not in (page.url or ""):
        return False

    # 1) Click "Thêm âm thanh" button in the timeline footer
    js_click_add_audio = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button, [role="button"]');
      for (const el of all) {
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        if (/^Thêm âm thanh$/i.test(aria) || /^Thêm âm thanh$/i.test(txt)
            || /^Add audio$/i.test(aria) || /^Add audio$/i.test(txt)) {
          const r = el.getBoundingClientRect();
          if (r.width < 10 || r.height < 10) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.display === 'none') continue;
          el.scrollIntoView({behavior: 'instant', block: 'center'});
          el.click();
          return {aria, txt: txt.slice(0, 40),
                  x: Math.round(r.x), y: Math.round(r.y)};
        }
      }
      return null;
    }
    """
    try:
        info = await page.evaluate(js_click_add_audio)
        if info:
            _log(sid, f"🎵 Đã click 'Thêm âm thanh' @({info['x']},{info['y']}).", "info")
            await asyncio.sleep(1.5)
        else:
            _log(sid, "⚠ Không tìm thấy nút 'Thêm âm thanh' — thử mở panel Tải lên.", "warning")
            await _open_uploads_panel(page, sid)
            await asyncio.sleep(1.0)
    except Exception as exc:
        _log(sid, f"⚠ Click 'Thêm âm thanh' lỗi: {exc}", "warning")
        await _open_uploads_panel(page, sid)
        await asyncio.sleep(1.0)

    # 2) Switch to "Âm thanh" sub-tab if visible (panel may already be on it)
    js_click_audio_tab = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button, [role="tab"], [role="button"]');
      for (const el of all) {
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        if (/^(Âm thanh|Audio)$/i.test(aria) || /^(Âm thanh|Audio)$/i.test(txt)) {
          const r = el.getBoundingClientRect();
          if (r.x < 500 && r.x >= 0 && r.width > 30 && r.width < 300) {
            const cs = getComputedStyle(el);
            if (cs.visibility === 'hidden' || cs.display === 'none') continue;
            el.click();
            return true;
          }
        }
      }
      return false;
    }
    """
    try:
        await page.evaluate(js_click_audio_tab)
        await asyncio.sleep(1.0)
    except Exception:
        pass

    # 3) Find the uploaded audio tile and click it
    js_click_audio_tile = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const candidates = Array.from(document.querySelectorAll(
        'button[role="button"], div[role="button"], [draggable="true"]'
      ));
      const matches = [];
      for (const el of candidates) {
        const r = el.getBoundingClientRect();
        if (r.x > 500 || r.x < 0) continue;
        if (r.width < 30 || r.height < 20) continue;
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        const blob = (aria + ' ' + txt).toLowerCase();
        let score = 0;
        if (/voiceover_|\\.mp3|\\.wav|\\.m4a/.test(blob)) score = 10;
        else if (/\\b\\d{1,2}:\\d{2}\\b/.test(txt) && r.height > 30) score = 6;
        if (score > 0) {
          matches.push({score, el, r, label: (aria || txt).slice(0, 60)});
        }
      }
      matches.sort((a, b) => b.score - a.score || a.r.y - b.r.y);
      if (!matches.length) return null;
      const m = matches[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.setAttribute('data-cv-audio-tile', '1');
      return {label: m.label, x: Math.round(m.r.x), y: Math.round(m.r.y),
              w: Math.round(m.r.width), h: Math.round(m.r.height)};
    }
    """

    # Wait for audio to appear (Canva transcodes it)
    target_info = None
    for attempt in range(15):  # up to 30s
        try:
            target_info = await page.evaluate(js_click_audio_tile)
        except Exception:
            target_info = None
        if target_info:
            break
        await asyncio.sleep(2.0)

    if not target_info:
        _log(sid, "⚠ Không tìm thấy tile audio trong panel — hãy kéo thả tay.", "warning")
        return False

    _log(sid, f"🎵 Audio tile: '{target_info.get('label')}' "
              f"@({target_info.get('x')},{target_info.get('y')})", "info")

    # 4) Click (single click is enough in the audio panel — Canva adds it)
    try:
        tile = await page.query_selector('[data-cv-audio-tile="1"]')
        if tile:
            await tile.scroll_into_view_if_needed()
            await tile.click()
            await asyncio.sleep(2.0)
            _log(sid, "🎶 Đã thêm voiceover vào timeline.", "success")
            return True
    except Exception as exc:
        _log(sid, f"⚠ Click audio tile lỗi: {exc}", "warning")

    # Fallback: click by coords
    try:
        cx = target_info["x"] + target_info["w"] // 2
        cy = target_info["y"] + target_info["h"] // 2
        await page.mouse.click(cx, cy)
        await asyncio.sleep(1.5)
        _log(sid, "🎶 Đã thêm voiceover vào timeline (coords).", "success")
        return True
    except Exception as exc:
        _log(sid, f"⚠ Fallback click audio lỗi: {exc}", "warning")
        return False


async def _open_create_modal(page, sid: str) -> bool:
    """Open the 'Tạo thiết kế' modal by clicking either:
      - the '+' Tạo button in the left sidebar, or
      - the Video quick-action circle icon on the home page.
    """
    # Wait until the home page is actually rendered. Canva loads in stages:
    # initial HTML → spa shell → sidebar/buttons. Polling for a sidebar element
    # with text "Trang chủ" or "Tạo" to appear gives us a green light.
    _log(sid, "⏳ Chờ trang home Canva render xong...", "info")
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            ready = await page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  const all = Array.from(document.querySelectorAll('button, a'));
                  return all.some(el => {
                    const aria = norm(el.getAttribute('aria-label'));
                    const txt = norm(el.textContent);
                    return /^(Tạo thiết kế|Trang chủ|Mẫu|Create a design|Home)$/i.test(aria)
                        || /^(Tạo|Trang chủ|Tạo thiết kế)$/i.test(txt);
                  });
                }
                """
            )
            if ready:
                _log(sid, "✅ Home đã render.", "info")
                break
        except Exception:
            pass
        await asyncio.sleep(1.0)

    # ── Strategy 1: scan the live DOM with JavaScript and click by visible text.
    # This is much more resilient to Canva renaming classes / aria-labels.
    js_click = """
    (target) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = Array.from(document.querySelectorAll('a, button, [role="button"], [role="link"]'));
      const matches = [];
      for (const el of all) {
        const rect = el.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        // Find descendant text-only elements (Canva wraps labels in spans)
        const innerTexts = Array.from(el.querySelectorAll('span, div, p'))
          .map(d => norm(d.textContent)).filter(Boolean);
        let score = 0;
        if (target === 'create') {
          if (/^(Tạo thiết kế( mới)?|Create a design|Create new design)$/i.test(aria)) score = 10;
          else if (aria === 'Tạo' || aria === 'Create') score = 8;
          else if (innerTexts.includes('Tạo')) score = 7;
          else if (txt === 'Tạo' || txt === 'Create') score = 6;
        } else if (target === 'video') {
          if (aria === 'Video') score = 10;
          else if (innerTexts.some(t => t === 'Video')) score = 9;
          else if (/^Video(\\s*Xem tất cả)?$/i.test(txt)) score = 8;
          // Hard reject other Video* tiles
          if (/Magic|TikTok|di động|Mobile|Hướng dẫn/i.test(txt)) score = 0;
        }
        if (score > 0) {
          // Mild position bonus for top-left area (sidebar / quick row)
          const positionBonus = (rect.x < 800 && rect.y < 600) ? 0.5 : 0;
          matches.push({el, score: score + positionBonus, x: rect.x, y: rect.y,
                        w: rect.width, h: rect.height, aria,
                        txt: txt.slice(0, 60), innerTxt: innerTexts.join(' | ').slice(0, 60)});
        }
      }
      matches.sort((a, b) => b.score - a.score);
      if (!matches.length) return null;
      const m = matches[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.click();
      return {aria: m.aria, txt: m.txt, innerTxt: m.innerTxt,
              x: Math.round(m.x), y: Math.round(m.y),
              w: Math.round(m.w), h: Math.round(m.h), score: m.score};
    }
    """

    # Try create button up to 3 times with 2s delay between (in case Canva
    # finishes hydrating mid-search)
    for attempt in range(3):
        try:
            info = await page.evaluate(js_click, "create")
            if info:
                _log(sid, f"➕ Đã click Tạo (aria='{info.get('aria')}', "
                          f"innerTxt='{info.get('innerTxt')}', score={info.get('score')}).", "info")
                if await _wait_for_create_modal(page, sid, timeout=8):
                    return True
                if "/design/" in (page.url or ""):
                    return True
                # Click registered but modal didn't open — wait & try again
        except Exception as exc:
            _log(sid, f"⚠ JS click Tạo lỗi (attempt {attempt+1}): {exc}", "warning")
        await asyncio.sleep(2.0)

    # ── Strategy 2: try the Video circle icon ──
    for attempt in range(2):
        try:
            info = await page.evaluate(js_click, "video")
            if info:
                _log(sid, f"🎥 Đã click Video (aria='{info.get('aria')}', "
                          f"innerTxt='{info.get('innerTxt')}', score={info.get('score')}).", "info")
                if await _wait_for_create_modal(page, sid, timeout=8):
                    return True
                if "/design/" in (page.url or ""):
                    return True
        except Exception as exc:
            _log(sid, f"⚠ JS click Video lỗi: {exc}", "warning")
        await asyncio.sleep(1.5)

    # ── Strategy 3: dump TOP candidates to log so we can iterate ──
    try:
        candidates = await page.evaluate(
            """
            () => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
              const out = [];
              const els = document.querySelectorAll('a, button, [role="button"], [role="link"]');
              for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.width < 20 || rect.height < 20) continue;
                const cs = getComputedStyle(el);
                if (cs.visibility === 'hidden' || cs.display === 'none') continue;
                const aria = norm(el.getAttribute('aria-label'));
                const txt = norm(el.textContent).slice(0, 50);
                // Filter to relevant ones containing Tạo / Video / Create
                if (!/Tạo|Video|Create|Trang chủ|Mẫu/i.test(aria + ' ' + txt)) continue;
                out.push({
                  tag: el.tagName,
                  aria: aria,
                  text: txt,
                  href: el.getAttribute('href') || '',
                  x: Math.round(rect.x), y: Math.round(rect.y),
                  w: Math.round(rect.width), h: Math.round(rect.height),
                });
              }
              return out.slice(0, 20);
            }
            """
        )
        if candidates:
            _log(sid, f"🔍 Tìm thấy {len(candidates)} button có chữ Tạo/Video/Create (debug):", "info")
            for c in candidates:
                _log(sid, f"   • {c['tag']} aria='{c['aria']}' text='{c['text']}' "
                          f"@({c['x']},{c['y']}) {c['w']}×{c['h']}", "info")
        else:
            _log(sid, "🔍 KHÔNG tìm thấy bất kỳ button nào có chữ Tạo/Video — trang chưa load xong?", "warning")
    except Exception as exc:
        _log(sid, f"⚠ Debug dump lỗi: {exc}", "warning")

    _log(sid, "⚠ Không tìm được nút Tạo / icon Video. Bạn bấm tay rồi đợi.", "warning")
    return False


async def _wait_for_create_modal(page, sid: str, timeout: int = 6) -> bool:
    """Wait for the 'Tạo thiết kế' modal to render."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for sel in [
                'h1:has-text("Tạo thiết kế")',
                'h2:has-text("Tạo thiết kế")',
                'div[role="dialog"]:has-text("Tạo thiết kế")',
                'div[role="dialog"]:has-text("Create a design")',
                'h2:has-text("Create a design")',
                # Search input in the modal
                'input[placeholder*="Bạn muốn tạo" i]',
                'input[placeholder*="What will you" i]',
            ]:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return True
        except Exception:
            pass
        await asyncio.sleep(0.4)
    return False


async def _click_design_tile(page, sid: str, aspect: str = "16:9") -> bool:
    """Inside the open 'Tạo thiết kế' modal, find the right design-type tile
    and navigate directly to its href.

    Tries 3 strategies in order:
      1. Find the tile by aria-label / text and use its <a href> (most reliable)
      2. Type the label into the modal search box ("Bạn muốn tạo thiết kế gì?")
         then re-scan tiles
      3. Click the "Video" sub-category in the modal sidebar then re-scan
    """
    label_map = {
        "16:9": ["Video khổ ngang", "Landscape Video"],
        "9:16": ["Video TikTok", "Mobile Video", "Video di động"],
        "1:1":  ["Video TikTok", "Video di động"],
        "4:5":  ["Bài đăng Instagram", "Instagram Post"],
    }
    labels = label_map.get(aspect) or label_map["16:9"]

    js_find_tile = """
    (labels) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = Array.from(document.querySelectorAll('a, button, [role="button"], [role="link"]'));
      const matches = [];
      for (const el of all) {
        const rect = el.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        const innerTexts = Array.from(el.querySelectorAll('span, div, p'))
          .map(d => norm(d.textContent)).filter(Boolean);
        for (const label of labels) {
          let score = 0;
          if (aria === label) score = 10;
          else if (innerTexts.includes(label)) score = 9;
          else if (txt === label) score = 8;
          else if (txt.startsWith(label + ' ') || txt.startsWith(label + '\\n')) score = 7;
          if (label === 'Video khổ ngang' && /TikTok|di động|Magic|mobile/i.test(txt)) score = 0;
          if (score > 0) {
            const href = el.tagName === 'A' ? el.getAttribute('href') : '';
            matches.push({label, score, aria, href,
                          x: rect.x, y: rect.y, w: rect.width, h: rect.height});
            break;
          }
        }
      }
      matches.sort((a, b) => {
        const sa = a.score + (a.href ? 0.5 : 0);
        const sb = b.score + (b.href ? 0.5 : 0);
        return sb - sa;
      });
      return matches[0] || null;
    }
    """

    async def _try_find(timeout_s: int = 4):
        deadline = time.time() + timeout_s
        last_m = None
        while time.time() < deadline:
            try:
                m = await page.evaluate(js_find_tile, labels)
                if m:
                    return m
                last_m = m
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return last_m

    async def _navigate_or_click(m: Dict[str, Any]) -> bool:
        if not m:
            return False
        href = (m.get("href") or "").strip()
        if href and ("/design" in href and ("create" in href or "type=" in href)):
            if href.startswith("/"):
                href = "https://www.canva.com" + href
            _log(sid, f"➡ Điều hướng trực tiếp: {href}", "info")
            try:
                await page.goto(href, wait_until="domcontentloaded", timeout=60_000)
                return True
            except Exception as exc:
                _log(sid, f"⚠ goto href thất bại: {exc} — thử click thay thế.", "warning")
        # Fallback: click via JS
        try:
            ok = await page.evaluate(
                """(labels) => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  const all = Array.from(document.querySelectorAll('a, button, [role="button"], [role="link"]'));
                  for (const el of all) {
                    const aria = norm(el.getAttribute('aria-label'));
                    if (labels.includes(aria)) {
                      el.scrollIntoView({behavior: 'instant', block: 'center'});
                      el.click();
                      return true;
                    }
                  }
                  return false;
                }""", labels
            )
            if ok:
                return True
        except Exception:
            pass
        return False

    # ── Strategy 1: scan modal as-is (most common case) ──
    m = await _try_find(timeout_s=4)
    if m:
        _log(sid, f"🎯 Tile (strategy 1): aria='{m.get('aria')}' "
                  f"href='{(m.get('href') or '')[:60]}' score={m.get('score')}", "info")
        if await _navigate_or_click(m):
            return True

    # ── Strategy 2: type label into modal search box ──
    _log(sid, f"🔎 Tile chưa hiện — thử search trong modal: '{labels[0]}'", "info")
    js_search_modal = """
    async (q) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      // Find the modal search input
      const inputs = Array.from(document.querySelectorAll('input, textarea'));
      for (const el of inputs) {
        const ph = norm(el.getAttribute('placeholder'));
        const aria = norm(el.getAttribute('aria-label'));
        if (/Bạn muốn tạo thiết kế gì|What will you|Tìm.*thiết kế/i.test(ph + ' ' + aria)) {
          const r = el.getBoundingClientRect();
          if (r.width > 5 && r.height > 5) {
            el.focus();
            el.value = '';
            el.dispatchEvent(new Event('input', {bubbles: true}));
            // Use native setter to bypass React's controlled-input guard
            const nativeSetter = Object.getOwnPropertyDescriptor(
              el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
              'value'
            ).set;
            nativeSetter.call(el, q);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            return {ok: true, ph, aria};
          }
        }
      }
      return {ok: false};
    }
    """
    try:
        info = await page.evaluate(js_search_modal, labels[0])
        if info.get("ok"):
            _log(sid, f"✅ Đã type vào modal search (placeholder='{info.get('ph')}')", "info")
            await asyncio.sleep(2.0)  # let filtered tiles render
            m = await _try_find(timeout_s=4)
            if m:
                _log(sid, f"🎯 Tile (strategy 2): aria='{m.get('aria')}' "
                          f"href='{(m.get('href') or '')[:60]}'", "info")
                if await _navigate_or_click(m):
                    return True
    except Exception as exc:
        _log(sid, f"⚠ Strategy 2 (modal search) lỗi: {exc}", "warning")

    # ── Strategy 3: click the "Video" sub-category in the modal left rail ──
    _log(sid, "🔍 Thử click sub-category Video trong modal sidebar...", "info")
    try:
        ok = await page.evaluate(
            """
            () => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
              const all = Array.from(document.querySelectorAll('button, a, [role="button"], [role="tab"], [role="menuitem"]'));
              for (const el of all) {
                const aria = norm(el.getAttribute('aria-label'));
                const txt = norm(el.textContent);
                if (txt === 'Video' || aria === 'Video') {
                  const r = el.getBoundingClientRect();
                  // Sub-category in modal sidebar: x < 250
                  if (r.x < 280 && r.width > 30) {
                    el.click();
                    return true;
                  }
                }
              }
              return false;
            }
            """
        )
        if ok:
            _log(sid, "✅ Đã click sub-category Video", "info")
            await asyncio.sleep(2.0)
            m = await _try_find(timeout_s=4)
            if m:
                _log(sid, f"🎯 Tile (strategy 3): aria='{m.get('aria')}'", "info")
                if await _navigate_or_click(m):
                    return True
    except Exception as exc:
        _log(sid, f"⚠ Strategy 3 lỗi: {exc}", "warning")

    # ── Strategy 4: dump tiles in modal for debugging ──
    try:
        dump = await page.evaluate(
            """
            () => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
              const out = [];
              const els = document.querySelectorAll('a[href*="/design"], a[aria-label]');
              for (const el of els) {
                const r = el.getBoundingClientRect();
                if (r.width < 30 || r.height < 30) continue;
                const aria = norm(el.getAttribute('aria-label'));
                if (!aria) continue;
                out.push({
                  aria,
                  href: (el.getAttribute('href') || '').slice(0, 80),
                  x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height),
                });
              }
              return out.slice(0, 20);
            }
            """
        )
        if dump:
            _log(sid, f"🔍 {len(dump)} tile có aria-label đang hiện trong modal:", "info")
            for c in dump[:15]:
                _log(sid, f"   • aria='{c['aria']}' href='{c['href']}' "
                          f"@({c['x']},{c['y']}) {c['w']}×{c['h']}", "info")
    except Exception:
        pass

    _log(sid, f"⚠ Không tìm thấy tile {labels[0]} trong modal.", "warning")
    return False


async def _create_blank_video_design(page, sid: str, aspect: str = "16:9") -> bool:
    """Create a new blank Canva design via the real UI flow:
       Tạo (or Video icon) → modal → Video khổ ngang.

    Returns True if URL ends up on /design/.../edit.
    """
    _log(sid, "🆕 Tạo design mới (Tạo → Video khổ ngang)...", "info")

    # Step 1: open the "Tạo thiết kế" modal
    opened = await _open_create_modal(page, sid)
    if not opened:
        return False

    # If we got teleported straight to an editor, we're done
    if "/design/" in (page.url or ""):
        return True

    await asyncio.sleep(0.5)

    # Step 2: click the right design-type tile
    picked = await _click_design_tile(page, sid, aspect=aspect)
    if not picked:
        return False

    # Step 3: wait for editor URL to appear (Canva opens a new tab)
    deadline = time.time() + 30
    while time.time() < deadline:
        if "/design/" in (page.url or ""):
            return True
        # Also check sibling tabs
        try:
            for p in page.context.pages:
                if "/design/" in (p.url or ""):
                    return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    return False


async def _open_components_panel(page, sid: str) -> bool:
    """Click the 'Thành phần' tab in the LEFT EDITOR rail.

    Only valid when we're inside the editor (`/design/.../edit`). The home
    page also has a sidebar tab with similar text — we reject that by
    requiring `role="tab"` with `aria-controls` (editor pattern).

    DOM (from user dump):
      <button role="tab" aria-controls="_r_13_">
        <div aria-label="Thành phần"><span>Thành phần</span></div>
      </button>
    """
    # Hard URL gate: must be inside an editor
    try:
        cur_url = page.url or ""
    except Exception:
        cur_url = ""
    if "/design/" not in cur_url:
        _log(sid, f"⚠ Không phải trang editor (url='{cur_url[:80]}'), bỏ qua mở panel.", "warning")
        return False

    js_click = """
    (target) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const candidates = [];
      // STRICT: real editor tab has role="tab" + aria-controls
      const tabs = document.querySelectorAll('button[role="tab"][aria-controls], [role="tab"][aria-controls]');
      for (const t of tabs) {
        const aria = norm(t.getAttribute('aria-label'));
        const innerAria = norm(t.querySelector('[aria-label]')?.getAttribute('aria-label'));
        const txt = norm(t.textContent);
        let score = 0;
        if (aria === target || innerAria === target) score = 10;
        else if (txt === target) score = 8;
        if (score > 0) {
          const r = t.getBoundingClientRect();
          // Editor tabs sit in a vertical rail at left edge: x < 100
          if (r.x < 120) candidates.push({el: t, score, r});
        }
      }
      // Fallback: any role=tab without aria-controls (less strict)
      if (!candidates.length) {
        const tabs2 = document.querySelectorAll('[role="tab"]');
        for (const t of tabs2) {
          const aria = norm(t.getAttribute('aria-label'));
          const innerAria = norm(t.querySelector('[aria-label]')?.getAttribute('aria-label'));
          const txt = norm(t.textContent);
          if (aria === target || innerAria === target || txt === target) {
            const r = t.getBoundingClientRect();
            if (r.x < 120 && r.width < 200) {  // editor rail is narrow
              candidates.push({el: t, score: 6, r});
            }
          }
        }
      }
      candidates.sort((a, b) => b.score - a.score);
      if (!candidates.length) return null;
      const m = candidates[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.click();
      return {score: m.score, x: Math.round(m.r.x), y: Math.round(m.r.y),
              w: Math.round(m.r.width), h: Math.round(m.r.height)};
    }
    """
    for attempt in range(3):
        try:
            info = await page.evaluate(js_click, "Thành phần")
            if info:
                _log(sid, f"🧩 Đã click tab Thành phần (editor rail, score={info.get('score')}, "
                          f"@({info.get('x')},{info.get('y')}) {info.get('w')}×{info.get('h')}).", "info")
                await asyncio.sleep(1.0)
                return True
            if attempt == 1:
                info = await page.evaluate(js_click, "Elements")
                if info:
                    _log(sid, "🧩 Đã click tab Elements (editor rail).", "info")
                    await asyncio.sleep(1.0)
                    return True
        except Exception as exc:
            _log(sid, f"⚠ JS click Thành phần lỗi: {exc}", "warning")
        await asyncio.sleep(1.5)
    _log(sid, "⚠ Không click được tab Thành phần trong editor rail.", "warning")
    return False


async def _click_components_category(page, sid: str, category: str = "Đồ họa") -> bool:
    """After opening the Thành phần panel, click a category card such as
    'Đồ họa' / 'Video' / 'Ảnh' to filter the element grid.

    DOM (from user dump):
      <div role="button" aria-labelledby="_r_h9g_">  ← clickable, EMPTY
      ...
      <p id="_r_h9g_">
        <span>Đồ họa</span>
      </p>

    Strategy: find any [aria-labelledby] element whose referenced node has the
    category text. Falls back to scanning all role=button elements.
    """
    js_click_cat = """
    (target) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const matches = [];
      // Strategy A: aria-labelledby resolution (Canva category cards)
      const linked = document.querySelectorAll('[aria-labelledby]');
      for (const el of linked) {
        const id = el.getAttribute('aria-labelledby');
        if (!id) continue;
        const labelEl = document.getElementById(id);
        if (!labelEl) continue;
        const labelText = norm(labelEl.textContent);
        if (labelText === target) {
          const r = el.getBoundingClientRect();
          if (r.width > 10 && r.height > 10) {
            matches.push({el, score: 10, labelText, r});
          }
        }
      }
      // Strategy B: any clickable with aria-label or text exact match
      if (!matches.length) {
        const all = document.querySelectorAll('button, a, [role="button"], [role="link"]');
        for (const el of all) {
          const aria = norm(el.getAttribute('aria-label'));
          const txt = norm(el.textContent);
          const innerTexts = Array.from(el.querySelectorAll('span, p, div'))
            .map(d => norm(d.textContent)).filter(Boolean);
          let score = 0;
          if (aria === target) score = 9;
          else if (innerTexts.includes(target)) score = 8;
          else if (txt === target) score = 7;
          if (score > 0) {
            const r = el.getBoundingClientRect();
            if (r.width > 10 && r.height > 10) {
              matches.push({el, score, labelText: target, r});
            }
          }
        }
      }
      matches.sort((a, b) => b.score - a.score);
      if (!matches.length) return null;
      const m = matches[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.click();
      return {label: m.labelText, score: m.score,
              x: Math.round(m.r.x), y: Math.round(m.r.y),
              w: Math.round(m.r.width), h: Math.round(m.r.height)};
    }
    """
    for attempt in range(2):
        try:
            info = await page.evaluate(js_click_cat, category)
            if info:
                _log(sid, f"📂 Đã click danh mục '{info.get('label')}' "
                          f"(score={info.get('score')}, @({info.get('x')},{info.get('y')})).", "success")
                await asyncio.sleep(1.2)
                return True
        except Exception as exc:
            _log(sid, f"⚠ JS click category '{category}' lỗi: {exc}", "warning")
        await asyncio.sleep(1.0)
    _log(sid, f"⚠ Không tìm được danh mục '{category}' — bỏ qua bước này.", "warning")
    return False


async def _search_components(page, query: str, sid: str) -> bool:
    """Type a search query into the Thành phần search box.

    Modern Canva editor: the Thành phần panel has a sub-tab/button "Tìm kiếm"
    that must be clicked to reveal the search textarea. The default view shows
    "Dùng gần đây" + categories without a search input.

    Strategy:
      1. Scan for textarea immediately (covers state where it's already open)
      2. If missing, click sub-tab "Tìm kiếm" inside the panel
      3. Wait + scan again
      4. Click → select all → paste via clipboard (handles VN diacritics)
      5. Press Enter to submit
    """
    if not query:
        return False

    # JS to find the search textarea (in elements panel only — not home search)
    js_focus_search = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const candidates = Array.from(document.querySelectorAll('textarea, input[type="text"], input[type="search"], input:not([type])'));
      for (const el of candidates) {
        const ph = norm(el.getAttribute('placeholder'));
        const aria = norm(el.getAttribute('aria-label'));
        const blob = ph + ' ' + aria;
        const isComponents =
          /Mô tả thành phần|Describe the element|Search elements|Search for any/i.test(blob);
        const isHomeSearch =
          /Tìm kiếm thiết kế|nội dung tải lên|Search Canva|Search designs/i.test(blob);
        if (isHomeSearch || !isComponents) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 5 || r.height < 5) continue;
        if (r.x > 500) continue;  // panel left only
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        el.focus();
        el.scrollIntoView({behavior: 'instant', block: 'center'});
        return {tag: el.tagName, ph, aria,
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height)};
      }
      return null;
    }
    """

    # JS to click "Tìm kiếm" sub-button inside the elements panel.
    # We exclude the home top-bar search and the AI "Tạo" button.
    js_click_search_subtab = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = Array.from(document.querySelectorAll('button, [role="button"]'));
      for (const el of all) {
        const txt = norm(el.textContent);
        const aria = norm(el.getAttribute('aria-label'));
        // Match exactly "Tìm kiếm" (or "Search") — avoid "Tìm kiếm thiết kế..."
        const isSearchBtn = (txt === 'Tìm kiếm' || aria === 'Tìm kiếm'
                          || txt === 'Search' || aria === 'Search');
        if (!isSearchBtn) continue;
        const r = el.getBoundingClientRect();
        // Must be in the editor LEFT panel: x < 500
        if (r.x > 500 || r.x < 0) continue;
        if (r.width < 30 || r.height < 20) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        el.scrollIntoView({behavior: 'instant', block: 'center'});
        el.click();
        return {x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height)};
      }
      return null;
    }
    """

    async def _try_focus():
        try:
            return await page.evaluate(js_focus_search)
        except Exception as exc:
            _log(sid, f"⚠ JS focus search lỗi: {exc}", "warning")
            return None

    info = await _try_focus()

    if not info:
        # Try clicking the "Tìm kiếm" sub-tab to switch panel into search mode
        try:
            click_info = await page.evaluate(js_click_search_subtab)
            if click_info:
                _log(sid, f"🔘 Đã click sub-tab Tìm kiếm @({click_info['x']},{click_info['y']})", "info")
                await asyncio.sleep(1.0)
                info = await _try_focus()
        except Exception as exc:
            _log(sid, f"⚠ Click sub-tab Tìm kiếm lỗi: {exc}", "warning")

    if not info:
        # Last resort: dump candidate textareas/inputs in the left panel for debug
        try:
            dump = await page.evaluate(
                """
                () => {
                  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                  const out = [];
                  const els = document.querySelectorAll('textarea, input');
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.x > 500) continue;
                    if (r.width < 5 || r.height < 5) continue;
                    out.push({
                      tag: el.tagName,
                      ph: norm(el.getAttribute('placeholder')),
                      aria: norm(el.getAttribute('aria-label')),
                      x: Math.round(r.x), y: Math.round(r.y),
                      w: Math.round(r.width), h: Math.round(r.height),
                    });
                  }
                  return out.slice(0, 10);
                }
                """
            )
            if dump:
                _log(sid, f"🔍 {len(dump)} input/textarea trong panel trái (debug):", "info")
                for c in dump:
                    _log(sid, f"   • {c['tag']} ph='{c['ph']}' aria='{c['aria']}' "
                              f"@({c['x']},{c['y']}) {c['w']}×{c['h']}", "info")
        except Exception:
            pass
        _log(sid, f"⚠ Không tìm thấy ô search trong panel Thành phần (query: {query}).", "warning")
        return False

    _log(sid, f"🎯 Found search box: {info.get('tag')} placeholder='{info.get('ph')}' "
              f"@({info.get('x')},{info.get('y')})", "info")

    try:
        # Clear via keyboard (already focused via JS)
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.1)
        await page.keyboard.press("Delete")
        await asyncio.sleep(0.15)
        # Push to clipboard then paste — handles VN diacritics
        await page.evaluate(
            "async (t) => { try { await navigator.clipboard.writeText(t); } catch(e){} }",
            query,
        )
        await asyncio.sleep(0.15)
        await page.keyboard.press("Control+V")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        _log(sid, f"🔎 Tìm: \"{query}\"")
        await asyncio.sleep(2.5)
        return True
    except Exception as exc:
        _log(sid, f"⚠ Type query thất bại: {exc}", "warning")
        return False


async def _move_playhead_to(page, sid: str, target_s: float = 0) -> bool:
    """Move the timeline playhead/scrubber to a specific time.

    When new elements are added to Canva Video, they are placed at the
    current playhead position. So we need to move the playhead to 0s (or
    desired start_s) BEFORE adding each element to avoid them stacking
    at the end.

    Strategy:
      1. Find the timeline ruler area
      2. Click on it at the calculated x position for target_s
    """
    js_get_ruler_info = """
    () => {
      // Find ruler labels by text content matching "N giây"
      const allEls = document.querySelectorAll('span, div, p');
      const points = [];
      for (const el of allEls) {
        if (el.children.length > 0) continue;
        const txt = (el.textContent || '').trim();
        const match = txt.match(/^(\\d+)\\s*giây$/);
        if (!match) continue;
        const sec = parseInt(match[1]);
        const r = el.getBoundingClientRect();
        if (r.y < window.innerHeight * 0.5) continue;
        if (r.width > 100 || r.height > 30) continue;
        const cx = r.x + r.width / 2;
        points.push({sec, cx, y: r.y});
      }
      if (points.length < 2) return null;
      points.sort((a, b) => a.sec - b.sec);
      const first = points[0];
      const last = points[points.length - 1];
      const pxPerSec = (last.cx - first.cx) / (last.sec - first.sec);
      // Use the y of the first label, but click slightly below to hit the ruler
      return {
        zeroX: first.cx - first.sec * pxPerSec,  // x position of 0s
        rulerY: first.y + 5,
        pxPerSec: pxPerSec,
      };
    }
    """
    try:
        info = await page.evaluate(js_get_ruler_info)
    except Exception:
        info = None

    if not info:
        _log(sid, f"⚠ Không tìm thấy timeline ruler — không di chuyển playhead.", "warning")
        return False

    # Calculate target x position
    target_x = info["zeroX"] + target_s * info["pxPerSec"]
    target_y = info["rulerY"]

    # Click on the ruler at the target position to move playhead there
    try:
        await page.mouse.click(target_x, target_y)
        await asyncio.sleep(0.4)
        _log(sid, f"⏯ Đã di chuyển playhead đến {target_s:.1f}s.", "info")
        return True
    except Exception as exc:
        _log(sid, f"⚠ Move playhead lỗi: {exc}", "warning")
        return False


async def _click_first_search_result(page, sid: str, scene_idx: int = 0,
                                      keyword: str = "") -> bool:
    # JS scan: find the first tile in the search results panel
    js_find_first = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      // Locate the "Kết quả tìm kiếm" heading inside the elements panel.
      const headings = Array.from(document.querySelectorAll('h2, h3, h4, p, span, div'))
        .filter(h => {
          const t = norm(h.textContent);
          return t === 'kết quả tìm kiếm' || t === 'search results';
        });
      let resultsTop = 0;
      if (headings.length) {
        const r = headings[0].getBoundingClientRect();
        resultsTop = r.bottom;
      }

      // Find tiles
      const candidates = document.querySelectorAll(
        'button[role="button"], div[role="button"], div[draggable="true"]'
      );
      const tiles = [];
      const seen = new Set();
      for (const el of candidates) {
        if (seen.has(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.x > 500 || r.x < 0) continue;
        if (r.width < 50 || r.height < 50) continue;
        if (r.width > 320 || r.height > 320) continue;
        if (r.y < resultsTop) continue;
        const img = el.querySelector('img');
        if (!img) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        seen.add(el);
        tiles.push({el, r});
      }

      // Sort by position: top-to-bottom, then left-to-right
      tiles.sort((a, b) => (a.r.y - b.r.y) || (a.r.x - b.r.x));

      if (!tiles.length) return null;
      const first = tiles[0];
      first.el.setAttribute('data-cv-tile-pick', '1');
      const altText = norm((first.el.querySelector('img')?.getAttribute('alt')) || '');
      const aria = norm(first.el.getAttribute('aria-label') || '');
      return {
        x: Math.round(first.r.x), y: Math.round(first.r.y),
        w: Math.round(first.r.width), h: Math.round(first.r.height),
        alt: (altText || aria).slice(0, 80),
        total: tiles.length,
      };
    }
    """

    try:
        result = await page.evaluate(js_find_first)
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: scan tiles lỗi: {exc}", "warning")
        return False

    if not result:
        _log(sid, f"⚠ Cảnh {scene_idx}: không có kết quả tìm kiếm.", "warning")
        return False

    _log(sid, f"🎯 Cảnh {scene_idx}: click tile đầu '{result['alt']}' "
              f"(trong {result['total']} kết quả).", "info")

    # Re-resolve the tagged element
    target = None
    try:
        target = await page.query_selector('[data-cv-tile-pick="1"]')
    except Exception:
        target = None

    if not target:
        try:
            cx = result["x"] + result["w"] // 2
            cy = result["y"] + result["h"] // 2
            await page.mouse.click(cx, cy)
            await asyncio.sleep(1.2)
            return True
        except Exception:
            return False

    try:
        await target.scroll_into_view_if_needed()
        await target.click()
        await asyncio.sleep(1.2)
        # Cleanup tag
        try:
            await page.evaluate("""
              () => {
                const el = document.querySelector('[data-cv-tile-pick="1"]');
                if (el) el.removeAttribute('data-cv-tile-pick');
              }
            """)
        except Exception:
            pass
        _log(sid, f"🖼 Cảnh {scene_idx}: đã thêm thành phần.", "success")
        return True
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: lỗi khi click: {exc}", "warning")
        return False


async def _add_new_page(page, sid: str) -> bool:
    """Click the '+ Add page' button at the bottom of the timeline.

    The real Canva VN button is an exact-text element:
        <button aria-label="Thêm nội dung đa phương tiện/cảnh trống">
    We target it first by exact aria, then fall back to fuzzy strategies.
    """
    n_before = 0
    try:
        thumbs_before, _ = await _find_page_thumbs(page)
        n_before = len(thumbs_before)
    except Exception:
        pass

    # Strategy 1: exact aria-label match (real Canva VN label)
    exact_selectors = [
        'button[aria-label="Thêm nội dung đa phương tiện/cảnh trống"]',
        'button[aria-label="Add new media/blank scene"]',
        'button[aria-label*="cảnh trống" i]',
        'button[aria-label*="blank scene" i]',
    ]
    for sel in exact_selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.scroll_into_view_if_needed()
                box = await el.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + box["width"] / 2,
                                            box["y"] + box["height"] / 2)
                else:
                    await el.click()
                await asyncio.sleep(1.5)
                thumbs_after, _ = await _find_page_thumbs(page)
                if len(thumbs_after) > n_before:
                    _log(sid, f"📄 Đã thêm trang (aria exact: '{sel[:60]}...', "
                              f"{n_before} → {len(thumbs_after)}).", "success")
                    return True
        except Exception:
            continue

    # Strategy 2: keyboard shortcut Ctrl+Enter
    try:
        try:
            canvas = await page.query_selector('main[role="main"]')
            if canvas:
                box = await canvas.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + box["width"] / 2,
                                            box["y"] + box["height"] / 2)
                    await asyncio.sleep(0.3)
                    await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.keyboard.press("Control+Enter")
        await asyncio.sleep(1.5)
        thumbs_after, _ = await _find_page_thumbs(page)
        if len(thumbs_after) > n_before:
            _log(sid, f"📄 Đã thêm trang (Ctrl+Enter, {n_before} → {len(thumbs_after)}).", "success")
            return True
    except Exception as exc:
        _log(sid, f"⚠ Ctrl+Enter add page lỗi: {exc}", "warning")

    # Strategy 3: fuzzy JS scan (last resort)
    js_click = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = Array.from(document.querySelectorAll('button, [role="button"]'));
      const matches = [];
      for (const el of all) {
        const r = el.getBoundingClientRect();
        if (r.width < 16 || r.height < 16) continue;
        if (r.width > 600) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        const blob = (aria + ' ' + txt).toLowerCase();
        let score = 0;
        if (/thêm nội dung đa phương tiện|thêm cảnh trống|cảnh trống/.test(aria)) score = 14;
        else if (/(thêm trang|add page|trang mới|new page)/.test(blob)) score = 9;
        else if (/(sao chép trang|duplicate page)/.test(blob)) score = 6;
        if (r.y > window.innerHeight * 0.6) score += 2;
        if (score > 0) matches.push({score, el, x: r.x, y: r.y, w: r.width, h: r.height, aria});
      }
      matches.sort((a, b) => b.score - a.score);
      if (!matches.length) return null;
      const m = matches[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.click();
      return {score: m.score, aria: m.aria, x: Math.round(m.x), y: Math.round(m.y)};
    }
    """
    try:
        info = await page.evaluate(js_click)
        if info:
            await asyncio.sleep(1.5)
            thumbs_after, _ = await _find_page_thumbs(page)
            if len(thumbs_after) > n_before:
                _log(sid, f"📄 Đã thêm trang (JS fuzzy, "
                          f"aria='{info.get('aria')}', {n_before} → {len(thumbs_after)}).", "success")
                return True
    except Exception as exc:
        _log(sid, f"⚠ JS click 'Thêm trang' lỗi: {exc}", "warning")

    _log(sid, f"⚠ Không tăng được số trang (vẫn {n_before}).", "warning")
    return False


async def _ensure_pages_count(page, target: int, sid: str) -> int:
    """Make sure the design has at least `target` pages.

    Click "Add page" repeatedly until page count reaches target. Logs progress
    so the user sees real numbers, not just retries.
    Returns the actual page count after the operation.
    """
    if target <= 1:
        try:
            thumbs, _ = await _find_page_thumbs(page)
            return len(thumbs)
        except Exception:
            return 0

    last_count = -1
    for attempt in range(target * 2):  # safety limit
        try:
            thumbs, _ = await _find_page_thumbs(page)
        except Exception:
            thumbs = []
        n = len(thumbs)
        if n >= target:
            _log(sid, f"📑 Đủ trang: {n}/{target}.", "success")
            return n
        if n == last_count and attempt > 0:
            # Stuck — break to avoid infinite loop
            _log(sid, f"⚠ Không tăng được trang nữa (vẫn {n}/{target}).", "warning")
            return n
        last_count = n
        ok = await _add_new_page(page, sid)
        if not ok:
            return n
        await asyncio.sleep(0.5)

    try:
        thumbs, _ = await _find_page_thumbs(page)
        return len(thumbs)
    except Exception:
        return 0


async def _select_page_index(page, idx: int, sid: str) -> bool:
    """Click the page thumbnail at index `idx` (0-based).

    Guards against navigating away from the editor: if the URL becomes non-editor
    after the click, that means we clicked something we shouldn't have — log
    a warning and try to navigate back via Browser.back().
    """
    if "/design/" not in (page.url or ""):
        _log(sid, f"⚠ _select_page_index({idx}): không ở editor, skip.", "warning")
        return False
    thumbs, _sel = await _find_page_thumbs(page)
    if idx < len(thumbs):
        url_before = page.url or ""
        try:
            await thumbs[idx].scroll_into_view_if_needed()
            await thumbs[idx].click()
            await asyncio.sleep(0.8)
            url_after = page.url or ""
            if "/design/" not in url_after and "/design/" in url_before:
                _log(sid, f"⚠ Click thumbnail {idx+1} navigate ra khỏi editor "
                          f"({url_before[:50]} → {url_after[:50]}). Quay lại...", "warning")
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=15_000)
                    await asyncio.sleep(1.0)
                except Exception:
                    pass
                return False
            return True
        except Exception:
            pass
    return False


async def _add_elements_to_pages(page, scenes: List[Dict[str, str]],
                                  creator: str, sid: str,
                                  scene_duration: float = 5.0) -> int:
    """For each scene, ensure a page exists, switch to it, switch to the
    scene's category in Thành phần, search the keyword, and click first result.

    Each scene can carry a `category` key (Đồ họa / Video / Ảnh / ...).
    Defaults to "Đồ họa" if missing.

    Returns: number of scenes for which a graphic was added.
    """
    if not scenes:
        return 0

    # Hard URL gate: must be in the editor, otherwise we'd accidentally drive
    # the home page (which has its own "Thành phần" sidebar item + search bar).
    try:
        cur_url = page.url or ""
    except Exception:
        cur_url = ""
    if "/design/" not in cur_url:
        _log(sid, f"⚠ URL không phải editor (url='{cur_url[:80]}'), bỏ qua thêm thành phần.", "warning")
        return 0

    added = 0
    n = len(scenes)
    # `creator` here is now used as a free-text SEARCH PREFIX (e.g. "stickman",
    # "chibi", "cartoon"), not a Canva @username. We strip a leading @ so older
    # saved values still work, and we don't re-add it.
    search_prefix = (creator or "").strip()
    if search_prefix.startswith("@"):
        search_prefix = search_prefix[1:].strip()

    # Open the elements panel once (we'll reuse the same search box)
    panel_opened = await _open_components_panel(page, sid)
    if not panel_opened:
        return 0

    # NOTE: Canva Video uses a SINGLE page with a timeline. Each element
    # (graphic, text) becomes its own track on the timeline. We do NOT create
    # multiple pages — instead we add all elements to the same page. The user
    # can then adjust start/end times per track in the timeline.

    # Track current category so we only click when it changes
    current_category = ""

    for i, sc in enumerate(scenes):
        if _sessions[sid]["stop_event"].is_set():
            break
        keyword = (sc.get("keyword") or "").strip()
        category = (sc.get("category") or "Đồ họa").strip()
        if not keyword:
            _log(sid, f"⏭ Cảnh {i+1}: bỏ qua (không có từ khoá).", "info")
            continue

        # No page switching needed — all elements go on the same page/timeline
        # Just re-open elements panel if it got closed by a previous action
        if i > 0:
            await _open_components_panel(page, sid)

        # Switch category if it differs from previous scene
        if category and category != current_category:
            ok_cat = await _click_components_category(page, sid, category=category)
            if ok_cat:
                current_category = category
            await asyncio.sleep(0.5)

        # Search "<prefix> <keyword>" so all elements stay in one art style
        # (e.g. "stickman eat", "chibi run"). If prefix is empty, just use the
        # keyword on its own.
        full_query = f"{search_prefix} {keyword}".strip() if search_prefix else keyword
        ok = await _search_components(page, full_query, sid)
        if not ok:
            continue

        # Move playhead to 0s before adding to keep elements organized while
        # they're being processed. The clock popup will set exact timing.
        if i == 0:
            await _move_playhead_to(page, sid, target_s=0)

        ok = await _click_first_search_result(page, sid, scene_idx=i + 1,
                                                keyword=full_query)
        if ok:
            added += 1

            # ── Post-add: position, animation, and timeline timing ──
            # Wait for the element to fully load on canvas and timeline
            await asyncio.sleep(1.5)

            # Use AI plan values if present, fallback to defaults
            elem_x = int(sc.get("x") or 960)
            elem_y = int(sc.get("y") or 540)
            elem_w = int(sc.get("w") or 500)
            elem_h = int(sc.get("h") or 400)
            elem_start = float(sc.get("start_s") or (i * scene_duration))
            elem_end = float(sc.get("end_s") or ((i + 1) * scene_duration))
            elem_anim = str(sc.get("animation") or "Hiện lên").strip()

            # a) Set timeline timing FIRST via the clock popup. This is the
            # most reliable step (numeric input, no drag needed). The element
            # remains selected on canvas after the popup closes.
            await _set_element_timing(page, sid, start_s=elem_start,
                                       end_s=elem_end, scene_idx=i + 1)

            # b) Set position and size via "Vị trí" panel (still selected)
            await _set_element_position(page, sid, x=elem_x, y=elem_y,
                                          width=elem_w, height=elem_h,
                                          scene_idx=i + 1)

            # c) Add animation via "Chuyển động" panel
            if elem_anim:
                await _set_element_animation(page, sid, animation=elem_anim, scene_idx=i + 1)

        pct = 30 + int(60 * (i + 1) / max(n, 1))
        _set_status(sid, "filling", progress=pct,
                    progress_label=f"Đang thêm hình cảnh {i+1}/{n}")

    return added


async def _set_element_position(page, sid: str, x: int = 960, y: int = 540,
                                 scene_idx: int = 0,
                                 width: int = 0, height: int = 0) -> bool:
    """With the element selected, open "Vị trí" panel → set X/Y/W/H in Nâng cao.

    Flow:
      1. Click "Vị trí" button in the top toolbar.
      2. Find the X, Y (and optionally W, H) inputs.
      3. Set values and press Enter/Tab between them.
      4. Close the panel.
    """
    # 1) Click "Vị trí" in toolbar
    js_click_position = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button, [role="button"]');
      for (const el of all) {
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        if (/^(Vị trí|Position)$/i.test(aria) || /^(Vị trí|Position)$/i.test(txt)) {
          const r = el.getBoundingClientRect();
          if (r.y < 100 && r.width > 20 && r.width < 200) {  // top toolbar
            el.click();
            return {clicked: true, x: Math.round(r.x), y: Math.round(r.y)};
          }
        }
      }
      return {clicked: false};
    }
    """
    try:
        click_res = await page.evaluate(js_click_position)
        if not click_res.get("clicked"):
            _log(sid, f"⚠ Cảnh {scene_idx}: không tìm thấy nút 'Vị trí' trên toolbar.", "warning")
            return False
        await asyncio.sleep(1.0)
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: click 'Vị trí' lỗi: {exc}", "warning")
        return False

    # 2) Set X, Y, W, H inputs - try multiple label detection strategies
    js_set_xywh = """
    (vals) => {
      const x = vals[0], y = vals[1], w = vals[2], h = vals[3];
      const setNative = (el, v) => {
        const proto = HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
        el.focus();
        // Select all then type new value
        el.select();
        setter.call(el, String(v));
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
      };

      const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="number"], input:not([type])'));
      const slots = {x: null, y: null, w: null, h: null};

      for (const inp of inputs) {
        const r = inp.getBoundingClientRect();
        if (r.x > 600 || r.width < 30 || r.height < 15) continue;
        if (r.x < 0 || r.y < 0) continue;

        // Try multiple ways to find the label
        let labelText = '';
        // Strategy A: aria-labelledby
        const labelId = inp.getAttribute('aria-labelledby');
        if (labelId) {
          const labelEl = document.getElementById(labelId);
          if (labelEl) labelText = norm(labelEl.textContent);
        }
        // Strategy B: aria-label directly on input
        if (!labelText) labelText = norm(inp.getAttribute('aria-label'));
        // Strategy C: closest label or preceding sibling text
        if (!labelText) {
          const wrapper = inp.closest('div, label');
          if (wrapper) {
            // Find sibling text element
            const txt = norm(wrapper.textContent).slice(0, 20);
            if (/^(x|y|w|h|width|height|chiều rộng|chiều cao)\\b/i.test(txt)) {
              labelText = txt.split(/\\s+/)[0];
            }
          }
        }
        // Strategy D: placeholder
        if (!labelText) labelText = norm(inp.getAttribute('placeholder'));

        const lt = labelText.toLowerCase();
        if (!slots.x && (lt === 'x' || lt.startsWith('x '))) {
          slots.x = inp;
        } else if (!slots.y && (lt === 'y' || lt.startsWith('y '))) {
          slots.y = inp;
        } else if (!slots.w && (lt === 'w' || lt === 'width' || lt.includes('chiều rộng') || lt.includes('rộng'))) {
          slots.w = inp;
        } else if (!slots.h && (lt === 'h' || lt === 'height' || lt.includes('chiều cao') || lt.includes('cao'))) {
          slots.h = inp;
        }
      }

      const result = {setX: false, setY: false, setW: false, setH: false,
                      foundInputs: inputs.length};
      if (slots.x) { setNative(slots.x, x); result.setX = true; }
      if (slots.y) { setNative(slots.y, y); result.setY = true; }
      if (w > 0 && slots.w) { setNative(slots.w, w); result.setW = true; }
      if (h > 0 && slots.h) { setNative(slots.h, h); result.setH = true; }
      return result;
    }
    """
    try:
        res = await page.evaluate(js_set_xywh, [x, y, width, height])
        if res.get("setX") or res.get("setY"):
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
            parts = []
            if res.get("setX"): parts.append(f"X={x}")
            if res.get("setY"): parts.append(f"Y={y}")
            if res.get("setW"): parts.append(f"W={width}")
            if res.get("setH"): parts.append(f"H={height}")
            _log(sid, f"📐 Cảnh {scene_idx}: {', '.join(parts)}.", "success")
        else:
            _log(sid, f"⚠ Cảnh {scene_idx}: không tìm thấy X/Y inputs (có {res.get('foundInputs', 0)} inputs).", "warning")
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: set position lỗi: {exc}", "warning")

    # 3) Close panel
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    except Exception:
        pass
    return True


async def _set_element_animation(page, sid: str, animation: str = "Hiện lên",
                                  scene_idx: int = 0) -> bool:
    """With the element selected, open "Chuyển động" → click an animation button.

    Available animations from DOM: Hiện lên, Lướt, Rõ dần, Bật ra, Gạt, Mờ,
    Zoom và mờ, Giãn nở, Kéo lên, Trôi ngang, Trôi hội tụ, Nhào lộn, Nhấp nháy,
    Cắt dán, Đập vào.
    """
    # 1) Click "Chuyển động" in toolbar
    js_click_motion = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button, [role="button"]');
      for (const el of all) {
        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        if (/^(Chuyển động|Animate|Motion)$/i.test(aria)
            || /^(Chuyển động|Animate|Motion)$/i.test(txt)) {
          const r = el.getBoundingClientRect();
          if (r.y < 80 && r.width > 20) {
            el.click();
            return true;
          }
        }
      }
      return false;
    }
    """
    try:
        ok = await page.evaluate(js_click_motion)
        if not ok:
            _log(sid, f"⚠ Cảnh {scene_idx}: không tìm nút Chuyển động.", "warning")
            return False
        await asyncio.sleep(1.0)
    except Exception:
        return False

    # 2) Click the animation button by name (role="switch" with text matching)
    js_click_anim = """
    (name) => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = document.querySelectorAll('button[role="switch"], button');
      for (const el of all) {
        const txt = norm(el.textContent);
        const alt = el.querySelector('img')?.getAttribute('alt') || '';
        if (txt === name || alt === name) {
          const r = el.getBoundingClientRect();
          if (r.width > 20 && r.x < 500) {
            el.click();
            return {txt, x: Math.round(r.x), y: Math.round(r.y)};
          }
        }
      }
      return null;
    }
    """
    try:
        info = await page.evaluate(js_click_anim, animation)
        if info:
            _log(sid, f"✨ Cảnh {scene_idx}: animation '{animation}'.", "success")
            await asyncio.sleep(0.5)
        else:
            _log(sid, f"⚠ Cảnh {scene_idx}: không tìm animation '{animation}'.", "warning")
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: set animation lỗi: {exc}", "warning")

    # 3) Close panel
    try:
        close_btn = await page.query_selector('button[aria-label="Đóng"]')
        if close_btn and await close_btn.is_visible():
            await close_btn.click()
        else:
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    except Exception:
        pass
    return True


async def _set_element_timing(page, sid: str, start_s: float = 0,
                               end_s: float = 5, scene_idx: int = 0) -> bool:
    """Set the selected element's timing using the clock button popup.

    When an element is selected, the toolbar shows a clock icon button labeled
    like "🕐 5.0 giây" that opens a popup with two inputs:
      - "Bắt đầu" (Start) — start time in seconds
      - "Thời lượng" (Duration) — duration in seconds

    This is MUCH more reliable than dragging trim handles because:
      - Direct numeric input (no pixel calculations)
      - No need to detect track selection state
      - Works regardless of zoom level

    Strategy:
      1. Click the clock button in element toolbar (matches "X.X giây" pattern)
      2. Find Start/Duration inputs in the popup
      3. Set values and press Enter
      4. Close popup with Escape
    """
    # ── Step 1: Click the clock duration button on element toolbar ──
    # The button shows "🕐 X.X giây" or has aria-label containing "Chỉnh sửa thời lượng"
    js_open_clock = """
    () => {
      const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
      const all = Array.from(document.querySelectorAll('button, [role="button"]'));
      const matches = [];
      for (const el of all) {
        const r = el.getBoundingClientRect();
        if (r.width < 30 || r.height < 20) continue;
        // Element toolbar appears at top OR floating above element
        // Skip elements clearly below the canvas (timeline area)
        if (r.y > window.innerHeight * 0.7) continue;

        const aria = norm(el.getAttribute('aria-label'));
        const txt = norm(el.textContent);
        const blob = (aria + ' ' + txt).toLowerCase();

        let score = 0;
        // Strongest signal: text matches "X.X giây" pattern
        if (/^[0-9]+([.,][0-9]+)?\\s*giây\\s*$/i.test(txt)) score = 15;
        else if (/^[0-9]+([.,][0-9]+)?\\s*(s|sec|second)\\s*$/i.test(txt)) score = 14;
        // Aria-label patterns
        else if (/(chỉnh.{0,3}thời lượng|edit.{0,3}duration|edit.{0,3}timing)/i.test(blob)) score = 12;
        else if (/(thời lượng|duration|timing)/i.test(blob)) score = 8;

        // Reject share/download buttons
        if (/(share|chia sẻ|tải xuống|download|export)/i.test(blob)) continue;
        // Reject if it's the page-level button (typically right side or page header)
        // Element button is usually in floating toolbar above the element

        if (score > 0) {
          matches.push({score, el, aria, txt: txt.slice(0, 30),
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height)});
        }
      }
      matches.sort((a, b) => b.score - a.score);
      if (!matches.length) return null;
      const m = matches[0];
      m.el.scrollIntoView({behavior: 'instant', block: 'center'});
      m.el.click();
      return {score: m.score, aria: m.aria, txt: m.txt,
              x: m.x, y: m.y, w: m.w, h: m.h, totalMatches: matches.length};
    }
    """

    try:
        opened = await page.evaluate(js_open_clock)
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: lỗi mở clock button: {exc}", "warning")
        return False

    if not opened:
        _log(sid, f"⚠ Cảnh {scene_idx}: không tìm thấy nút thời lượng (clock).", "warning")
        return False

    _log(sid, f"🕐 Cảnh {scene_idx}: đã mở popup thời lượng "
              f"(score={opened['score']}, txt='{opened['txt']}').", "info")

    await asyncio.sleep(0.6)

    # ── Step 2: Set Start and Duration inputs in the popup ──
    js_set_timing = """
    (vals) => {
      const startVal = vals[0], durVal = vals[1];
      const setNative = (el, v) => {
        const proto = HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
        el.focus();
        el.select && el.select();
        setter.call(el, String(v));
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
      };

      const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
      const inputs = Array.from(document.querySelectorAll(
        'input[type="number"], input[type="text"], input:not([type])'
      ));
      const visibleInputs = inputs.filter(el => {
        const r = el.getBoundingClientRect();
        if (r.width < 20 || r.height < 12) return false;
        const cs = getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none';
      });

      let startInp = null, durInp = null;

      // Identify by surrounding label text
      for (const el of visibleInputs) {
        // Get label from aria, placeholder, or surrounding text
        let labelText = '';
        const labelId = el.getAttribute('aria-labelledby');
        if (labelId) {
          const lbl = document.getElementById(labelId);
          if (lbl) labelText = norm(lbl.textContent);
        }
        if (!labelText) labelText = norm(el.getAttribute('aria-label'));
        if (!labelText) labelText = norm(el.getAttribute('placeholder'));
        if (!labelText) {
          // Look at parent/sibling text
          const wrap = el.closest('div, label');
          if (wrap) {
            const t = norm(wrap.textContent).slice(0, 40);
            labelText = t;
          }
        }

        if (!startInp && /(bắt đầu|start|start time)/i.test(labelText)) {
          startInp = el;
        } else if (!durInp && /(thời lượng|duration|length)/i.test(labelText)) {
          durInp = el;
        }
      }

      // Fallback: first 2 visible inputs are usually start + duration
      if (!startInp && visibleInputs.length >= 1) startInp = visibleInputs[0];
      if (!durInp && visibleInputs.length >= 2) durInp = visibleInputs[1];

      const result = {setStart: false, setDur: false,
                      foundInputs: visibleInputs.length,
                      startLabel: '', durLabel: ''};
      if (startInp) {
        setNative(startInp, startVal);
        result.setStart = true;
        result.startLabel = norm(startInp.getAttribute('aria-label') || startInp.getAttribute('placeholder') || '');
      }
      if (durInp) {
        // Tab between fields, then set duration
        setNative(durInp, durVal);
        result.setDur = true;
        result.durLabel = norm(durInp.getAttribute('aria-label') || durInp.getAttribute('placeholder') || '');
      }
      return result;
    }
    """

    duration = max(0.5, end_s - start_s)
    start_str = f"{start_s:.1f}".rstrip("0").rstrip(".") or "0"
    dur_str = f"{duration:.1f}".rstrip("0").rstrip(".") or "0.5"

    try:
        res = await page.evaluate(js_set_timing, [start_str, dur_str])
        if res.get("setStart") or res.get("setDur"):
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
            _log(sid, f"⏱ Cảnh {scene_idx}: start={start_str}s, duration={dur_str}s "
                      f"(start_input='{res.get('startLabel','')}', dur_input='{res.get('durLabel','')}').",
                 "success")
        else:
            _log(sid, f"⚠ Cảnh {scene_idx}: không tìm thấy input start/duration "
                      f"(có {res.get('foundInputs', 0)} inputs).", "warning")
    except Exception as exc:
        _log(sid, f"⚠ Cảnh {scene_idx}: set timing lỗi: {exc}", "warning")

    # ── Step 3: Close popup ──
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
    except Exception:
        pass

    return True


async def _set_all_pages_duration(page, scenes_count: int, seconds: float, sid: str) -> int:
    """For each page in the design, set its duration via Canva's "Chỉnh thời lượng".

    Flow per page:
      1. Click the page thumbnail in the timeline (this also deselects any
         currently-selected element so the toolbar shows page-level options).
      2. Click on an empty area of the canvas to ensure no element is selected
         (selecting an element changes the toolbar to element-level).
      3. Find a clock-icon button labeled like "X.X giây" / "Timing" /
         "Thời lượng" in the page header / floating toolbar and click it.
      4. In the popover that opens, find the duration input (a number input or
         a text input with a "giây" suffix) and replace its value with `seconds`.
      5. Press Enter and Escape to commit + close.

    Returns the number of pages we successfully updated.
    """
    if seconds <= 0:
        return 0
    if "/design/" not in (page.url or ""):
        _log(sid, "⚠ Không phải editor — bỏ qua set duration.", "warning")
        return 0

    page_thumbs, _sel = await _find_page_thumbs(page)
    n = max(scenes_count or 0, len(page_thumbs))
    if n <= 0:
        _log(sid, "⚠ Không có trang nào để set duration.", "warning")
        return 0

    updated = 0
    fmt = (f"{seconds:.1f}".rstrip("0").rstrip(".")) + " giây"
    _log(sid, f"⏱ Đặt thời lượng {seconds}s cho {n} trang...", "info")

    # Guard: bail early if the page or context has been closed (user shut Chromium)
    try:
        if page.is_closed():
            _log(sid, "⚠ Cửa sổ Chromium đã đóng — bỏ qua set duration.", "warning")
            return 0
    except Exception:
        pass

    for i in range(n):
        if _sessions[sid]["stop_event"].is_set():
            break
        # Re-check page liveness each iteration
        try:
            if page.is_closed():
                _log(sid, "⚠ Cửa sổ đã đóng giữa chừng — dừng set duration.", "warning")
                break
        except Exception:
            break

        # 1) Switch to page i (skip if there are no thumbs — single-page design)
        if page_thumbs and i < len(page_thumbs):
            try:
                await page_thumbs[i].scroll_into_view_if_needed()
                await page_thumbs[i].click()
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # 2) Click a blank spot on canvas to deselect any element
        try:
            await page.evaluate(
                """
                () => {
                  // Click outside any selected element so the toolbar shows
                  // page-level controls (Chỉnh thời lượng).
                  document.activeElement && document.activeElement.blur && document.activeElement.blur();
                  // Press Escape via dispatch (cheaper than keyboard.press)
                  document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
                }
                """
            )
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
        except Exception:
            pass

        # 3) Find + click the duration button. Canva VN labels it variously:
        #    "Chỉnh thời lượng", "Thời lượng trang", "X.X giây", or just a
        #    clock SVG with no text. We accept any of them in the top toolbar.
        js_open_duration = """
        () => {
          const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
          const all = Array.from(document.querySelectorAll('button, [role="button"]'));
          const matches = [];
          for (const el of all) {
            const r = el.getBoundingClientRect();
            if (r.width < 20 || r.height < 20) continue;
            // Top toolbar lives in the upper portion of the editor
            if (r.y > 200 || r.y < 0) continue;
            const aria = norm(el.getAttribute('aria-label'));
            const txt = norm(el.textContent);
            const blob = (aria + ' ' + txt).toLowerCase();
            let score = 0;
            if (/(chỉnh thời lượng|thời lượng trang|page duration|change timing)/.test(blob))
              score = 10;
            else if (/^[0-9]+([.,][0-9]+)?\\s*(giây|s|sec|second)/.test(txt)
                  || /^[0-9]+([.,][0-9]+)?\\s*(giây|s|sec|second)/.test(aria))
              score = 9;
            else if (/timing|duration/.test(blob))
              score = 6;
            // Reject the design name / share button area
            if (/share|chia sẻ|tải xuống|download/.test(blob)) score = 0;
            if (score > 0) {
              matches.push({score, el, x: r.x, y: r.y, w: r.width, h: r.height,
                            aria, txt: txt.slice(0, 40)});
            }
          }
          matches.sort((a, b) => b.score - a.score);
          if (!matches.length) return null;
          const m = matches[0];
          m.el.scrollIntoView({behavior: 'instant', block: 'center'});
          m.el.click();
          return {score: m.score, aria: m.aria, txt: m.txt,
                  x: Math.round(m.x), y: Math.round(m.y),
                  w: Math.round(m.w), h: Math.round(m.h)};
        }
        """
        try:
            opened = await page.evaluate(js_open_duration)
        except Exception as exc:
            _log(sid, f"⚠ Trang {i+1}: lỗi mở duration: {exc}", "warning")
            continue

        if not opened:
            _log(sid, f"⚠ Trang {i+1}: không tìm thấy nút thời lượng.", "warning")
            continue

        await asyncio.sleep(0.5)

        # 4) Find the duration input in the popover and set it
        js_set_value = """
        (val) => {
          const setNative = (el, v) => {
            const proto = el.tagName === 'TEXTAREA'
              ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, v);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          };
          // Look for a number-like input that's currently visible.
          const inputs = Array.from(document.querySelectorAll(
            'input[type="number"], input[type="text"], input:not([type])'
          ));
          for (const el of inputs) {
            const r = el.getBoundingClientRect();
            if (r.width < 20 || r.height < 12) continue;
            const cs = getComputedStyle(el);
            if (cs.visibility === 'hidden' || cs.display === 'none') continue;
            const aria = (el.getAttribute('aria-label') || '').toLowerCase();
            const ph = (el.getAttribute('placeholder') || '').toLowerCase();
            const around = (el.parentElement?.textContent || '').toLowerCase();
            const isDur = /(giây|second|duration|thời lượng)/.test(aria + ' ' + ph + ' ' + around);
            // Also accept if value looks like a duration ("5.0", "0.8")
            const looksLikeDur = /^\\s*\\d+([.,]\\d+)?\\s*$/.test(el.value || '');
            if (isDur || looksLikeDur) {
              el.focus();
              el.select && el.select();
              setNative(el, String(val));
              return {ok: true, aria, ph, prev: el.value};
            }
          }
          return {ok: false};
        }
        """

        # Format duration as number (Canva VN accepts both "5" and "5.0")
        val_str = (f"{seconds:.1f}").rstrip("0").rstrip(".") or "0"
        try:
            res = await page.evaluate(js_set_value, val_str)
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}

        if not res.get("ok"):
            # Fallback: physically type into whatever is focused
            try:
                await page.keyboard.press("Control+A")
                await asyncio.sleep(0.1)
                await page.keyboard.type(val_str, delay=20)
            except Exception:
                pass

        try:
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass

        updated += 1
        _log(sid, f"⏱ Trang {i+1}: đặt {fmt}.", "success")

    return updated


async def _trigger_export_mp4(page, sid: str) -> bool:
    """Click Share → Download → MP4. Canva localized to Vietnamese can show
    "Chia sẻ" / "Tải xuống". We also try the dedicated 'Tải xuống' button on
    Canva VN's top right.
    """
    _set_status(sid, "exporting", progress=92, progress_label="Mở menu Export")
    # 1. Click Share / Tải xuống button (top-right). Canva VN often shows
    #    a primary "Tải xuống" button right next to "Chia sẻ".
    share_clicked = False
    for sel in [
        'button:has-text("Tải xuống")',          # VN direct download button
        'button[aria-label*="Tải xuống" i]',
        'button:has-text("Share")',
        'button:has-text("Chia sẻ")',
        'button[aria-label*="Share" i]',
        'button[aria-label*="Chia sẻ" i]',
        '[data-testid*="share" i]',
        '[data-testid*="download" i]',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                share_clicked = True
                _log(sid, f"📤 Đã mở menu (selector: {sel}).")
                break
        except Exception:
            pass
    if not share_clicked:
        _log(sid, "⚠ Không tìm thấy nút Share / Tải xuống — hãy export tay (Chia sẻ → Tải xuống → MP4).", "warning")
        return False

    await asyncio.sleep(1.2)

    # 2. Click Download in the popover (if still needed)
    for sel in [
        'button:has-text("Download")',
        'button:has-text("Tải xuống")',
        '[data-testid*="download" i]:not([disabled])',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                # Only click if the popover is open (avoid clicking ourselves again)
                box = await el.bounding_box()
                if box:
                    await el.click()
                    _log(sid, "⬇ Đã chọn Download.")
                    break
        except Exception:
            pass
    await asyncio.sleep(1.0)

    # 3. Pick MP4 from the format dropdown
    # Canva often defaults to PDF — we need to open the type selector first
    for sel in [
        'button:has-text("PDF Standard")',
        'button:has-text("File type")',
        'button:has-text("Loại tệp")',
        'button[aria-haspopup="listbox"]',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await asyncio.sleep(0.4)
                break
        except Exception:
            pass

    for sel in [
        'div[role="option"]:has-text("MP4 Video")',
        'div[role="option"]:has-text("MP4")',
        'button:has-text("MP4 Video")',
        'button:has-text("MP4")',
        'li:has-text("MP4")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                _log(sid, "🎬 Đã chọn định dạng MP4.")
                break
        except Exception:
            pass
    await asyncio.sleep(0.6)

    # 4. Hit the final Download button
    for sel in [
        'button[data-testid*="download-button"]',
        'button:has-text("Download"):not([disabled])',
        'button:has-text("Tải xuống"):not([disabled])',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                _log(sid, "🚀 Đã bấm Download — chờ Canva render & tải về...", "success")
                return True
        except Exception:
            pass

    _log(sid, "⚠ Không tự động bấm được nút Download cuối — hãy bấm tay.", "warning")
    return False


async def _run_canva_flow(sid: str, params: Dict[str, Any]):
    """Main Playwright session: open Canva, fill template, optionally export."""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _set_status(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return

    template_url = (params.get("template_url") or "").strip()
    raw_scenes = params.get("scenes") or []
    # Normalize scenes: accept either str or {text,keyword,library_image,category}
    scenes: List[Dict[str, str]] = []
    for s in raw_scenes:
        if isinstance(s, str):
            scenes.append({"text": s, "keyword": "", "library_image": "", "category": ""})
        elif isinstance(s, dict):
            scenes.append({
                "text": str(s.get("text") or "").strip(),
                "keyword": str(s.get("keyword") or "").strip(),
                "library_image": str(s.get("library_image") or "").strip(),
                "category": str(s.get("category") or "").strip(),
                # AI plan fields (optional — present when generated by /plan_scenes)
                "x": int(s.get("x") or 960),
                "y": int(s.get("y") or 540),
                "w": int(s.get("w") or 500),
                "h": int(s.get("h") or 400),
                "start_s": float(s.get("start_s") or 0),
                "end_s": float(s.get("end_s") or 5),
                "animation": str(s.get("animation") or "Hiện lên").strip(),
                "note": str(s.get("note") or "").strip(),
            })
    voiceover = (params.get("voiceover") or "").strip()
    caption = (params.get("caption") or "").strip()  # noqa: F841 (informational)
    image_paths = list(params.get("image_paths") or [])
    # Also collect any library images attached to scenes
    for sc in scenes:
        lib = sc.get("library_image") or ""
        if lib:
            full = lib if Path(lib).is_absolute() else str(ROOT / lib)
            if Path(full).exists() and full not in image_paths:
                image_paths.append(full)
    export_mp4 = bool(params.get("export_mp4"))
    add_elements = bool(params.get("add_elements", True))
    # Search prefix for the elements panel (e.g. "stickman", "chibi"). We
    # accept either `search_prefix` (new) or `creator` (legacy) so existing
    # saved settings keep working.
    creator = (params.get("search_prefix")
               or params.get("creator")
               or "stickman").strip()
    aspect = (params.get("aspect") or "16:9").strip()
    scene_duration = float(params.get("scene_duration") or 0)

    _CV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Login gate: only one session can drive login at a time
    login_needed = not _has_login_cookies(_CV_PROFILE_DIR)
    gate_held = False
    if login_needed:
        _log(sid, "🔒 Chưa có session Canva — chờ login lần đầu.")
        _set_status(sid, "waiting_login_gate", progress=2)
        stop_event = _sessions[sid]["stop_event"]
        while not stop_event.is_set():
            if _LOGIN_GATE.acquire(blocking=False):
                gate_held = True
                break
            if _has_login_cookies(_CV_PROFILE_DIR):
                break
            await asyncio.sleep(2)

    _set_status(sid, "launching", progress=5, progress_label="Khởi động Chromium")
    _log(sid, "🚀 Mở Chromium...")

    stop_event = _sessions[sid]["stop_event"]

    # Pre-cleanup any stale lock files from a previous crash
    _cleanup_profile_locks(_CV_PROFILE_DIR)

    async with async_playwright() as pw:
        context = None
        launch_kwargs = dict(
            user_data_dir=str(_CV_PROFILE_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
            accept_downloads=True,
            # Auto-grant clipboard permissions so navigator.clipboard works
            permissions=["clipboard-read", "clipboard-write"],
        )
        try:
            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as exc:
            _log(sid, f"⚠ Lần đầu không mở được: {exc}. Thử lại sau khi cleanup...", "warning")
            _cleanup_profile_locks(_CV_PROFILE_DIR)
            await asyncio.sleep(2)
            try:
                context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as exc2:
                _set_status(sid, "error", error=f"Không mở được Chromium: {exc2}", done=True)
                if gate_held:
                    try:
                        _LOGIN_GATE.release()
                    except Exception:
                        pass
                return

        with _sessions_lock:
            _sessions[sid]["_context"] = context

        try:
            page = context.pages[0] if context.pages else await context.new_page()

            # ── Open Canva ──
            target_url = template_url if template_url else CANVA_HOME_URL
            _log(sid, f"🌐 Mở {target_url}")
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                _log(sid, f"⚠ goto chậm: {exc}", "warning")

            # If we got bounced to login, wait for user to authenticate
            url_now = page.url or ""
            if "login" in url_now or "signup" in url_now:
                _set_status(sid, "waiting_login", progress=10,
                            progress_label="Đăng nhập Canva trong cửa sổ vừa mở")
                _log(sid, "🔐 Hãy đăng nhập Canva trong cửa sổ Chromium đang mở.", "warning")
                ok = await _wait_logged_in(page, sid, timeout=600)
                if not ok:
                    _set_status(sid, "error", error="User chưa đăng nhập trong 10 phút", done=True)
                    return
                _log(sid, "✅ Đã đăng nhập Canva.", "success")
                await _save_state(context, _CV_PROFILE_DIR, sid)
                # Re-navigate to template if we were originally going to one
                if template_url:
                    try:
                        await page.goto(template_url, wait_until="domcontentloaded", timeout=60_000)
                    except Exception:
                        pass

            # Release the login gate
            if gate_held:
                try:
                    _LOGIN_GATE.release()
                    gate_held = False
                except Exception:
                    pass

            # ── If user provided a template URL but we're not on it (or
            # we ended up on home), navigate to it explicitly. ──
            if template_url and "/design/" not in (page.url or ""):
                _log(sid, f"➡ Điều hướng đến template: {template_url}", "info")
                try:
                    await page.goto(template_url, wait_until="domcontentloaded", timeout=60_000)
                except Exception as exc:
                    _log(sid, f"⚠ Không vào được template: {exc}", "warning")

            # ── If no template URL: auto-create a blank video design ──
            if not template_url and "/design/" not in (page.url or ""):
                _set_status(sid, "opening_template", progress=15,
                            progress_label="Tạo design mới (Video khổ ngang)")
                created = await _create_blank_video_design(page, sid, aspect=aspect)
                if not created:
                    _log(sid, "⚠ Không tự tạo được design — hãy bấm Tạo → Video khổ ngang tay. "
                              "Tool sẽ chờ tối đa 3 phút, khi nào URL chuyển sang /design/.../edit "
                              "sẽ tự tiếp tục.", "warning")
                # Whether or not Strategy 1/2 succeeded, watch all tabs for the
                # editor URL — user might also click manually in another tab.
                wait_deadline = time.time() + 180  # 3 minutes
                editor_page = None
                while time.time() < wait_deadline and not stop_event.is_set():
                    try:
                        for p in context.pages:
                            try:
                                if "/design/" in (p.url or "") and "/edit" in (p.url or ""):
                                    editor_page = p
                                    break
                            except Exception:
                                pass
                        if editor_page:
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)
                if editor_page:
                    page = editor_page
                    try:
                        await page.bring_to_front()
                    except Exception:
                        pass
                    with _sessions_lock:
                        _sessions[sid]["_active_page"] = page
                    _log(sid, f"✅ Đã chuyển sang tab editor: {page.url[:90]}...", "success")

            # ── Wait for editor to load (much longer + smarter) ──
            if "/design/" in (page.url or ""):
                _set_status(sid, "opening_template", progress=20,
                            progress_label="Chờ Canva load editor (~15s)")
                _log(sid, "⏳ Chờ Canva load editor (tối đa 90s)...")
                editor_loaded = await _wait_for_editor(page, sid, timeout=90)
                if editor_loaded:
                    _log(sid, "✅ Editor đã sẵn sàng.", "success")
                    await asyncio.sleep(3.0)
                else:
                    _log(sid, "⚠ Editor chưa load xong sau 90s. Có thể bạn không có quyền truy cập "
                              "template này, hoặc cần Refresh tay.", "warning")
            else:
                _log(sid, "ℹ Không vào được editor — bạn thao tác tay tiếp tục, "
                          "tool sẽ ngồi yên.", "warning")

            # ── Re-discover the editor tab (Canva sometimes opens the design
            # in a new tab, leaving us on home). We give it up to 60s to find
            # one — meanwhile user can also click "Tạo → Video khổ ngang"
            # manually and the code will pick that up. ──
            page, editor_ok = await _ensure_editor_page(context, page, sid, timeout=60)
            if editor_ok:
                with _sessions_lock:
                    _sessions[sid]["_active_page"] = page
                _log(sid, f"📍 Đang ở editor: {page.url[:90]}", "info")
                # Wait a bit more for full hydration
                await _wait_for_editor(page, sid, timeout=30)
                await asyncio.sleep(2.0)
            else:
                _log(sid, "⚠ Không tìm thấy tab nào ở editor — các bước Thành phần / Upload sẽ bị bỏ qua. "
                          "Bạn có thể click 'Tạo → Video khổ ngang' tay rồi chạy lại.", "warning")

            # Save cookies once we're inside the editor
            await _save_state(context, _CV_PROFILE_DIR, sid)

            # ── Upload images first so user can drag into pages while text fills ──
            if image_paths and editor_ok:
                _set_status(sid, "uploading_images", progress=25,
                            progress_label=f"Upload {len(image_paths)} ảnh")
                await _upload_images(page, image_paths, sid)
                # If any audio file was uploaded, auto-add it to the timeline
                # by double-clicking its tile in the Uploads panel.
                has_audio = any(Path(p).suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
                                for p in image_paths if p)
                if has_audio:
                    _set_status(sid, "uploading_images", progress=28,
                                progress_label="Thêm voiceover vào timeline")
                    try:
                        await _add_uploaded_audio_to_timeline(page, sid)
                    except Exception as exc:
                        _log(sid, f"⚠ Add audio to timeline lỗi: {exc}", "warning")

            # Re-ensure editor before each subsequent step (Canva may navigate
            # to a different URL between actions, e.g. opening Uploads panel
            # from a fresh state).
            page, editor_ok = await _ensure_editor_page(context, page, sid, timeout=10)

            # ── Add a graphic element per scene (Thành phần search) ──
            elements_added = 0
            if add_elements and scenes and editor_ok:
                _set_status(sid, "filling", progress=35,
                            progress_label=f"Thêm thành phần ({len(scenes)} cảnh)")
                elements_added = await _add_elements_to_pages(page, scenes, creator, sid,
                                                                scene_duration=scene_duration)
                _log(sid, f"🎨 Đã thêm {elements_added}/{len(scenes)} hình.",
                     "success" if elements_added else "warning")

            # Re-ensure before text fill / export
            page, editor_ok = await _ensure_editor_page(context, page, sid, timeout=10)

            # ── Optionally fill text boxes (only useful if scenes have text). ──
            filled = 0
            has_text = any(s.get("text") for s in scenes)
            if has_text and editor_ok:
                _set_status(sid, "filling", progress=80,
                            progress_label=f"Điền text {len(scenes)} cảnh")
                filled = await _fill_text_boxes(page, scenes, sid)
                _log(sid, f"📝 Đã điền text {filled}/{len(scenes)} cảnh.",
                     "success" if filled else "info")

            # If we couldn't fill text but user has scene text, copy first to clipboard
            if has_text and filled == 0:
                first_text = next((s["text"] for s in scenes if s.get("text")), "")
                if first_text:
                    try:
                        await page.evaluate(
                            "async (t) => { try { await navigator.clipboard.writeText(t); } catch(e){} }",
                            first_text,
                        )
                        _log(sid, "📋 Đã copy lời thoại cảnh #1 vào clipboard. "
                                  "Click ô text trên Canva → Ctrl+V để paste.", "info")
                    except Exception:
                        pass

            # If user supplied a voiceover string, paste it on the last page as caption
            if voiceover and filled > 0:
                try:
                    _log(sid, "🎙 Paste voice over vào trang cuối (nếu có ô).", "info")
                    page_thumbs, _sel = await _find_page_thumbs(page)
                    if page_thumbs:
                        await page_thumbs[-1].click()
                        await asyncio.sleep(0.6)
                    await _paste_into_current_page(page, voiceover, sid, scene_idx=999)
                except Exception:
                    pass

            # ── Set page duration for every page ──
            page, editor_ok = await _ensure_editor_page(context, page, sid, timeout=10)
            if editor_ok and scene_duration and scene_duration > 0:
                _set_status(sid, "filling", progress=88,
                            progress_label=f"Đặt thời lượng {scene_duration}s/trang")
                try:
                    n_pages_target = max(len(scenes), 1)
                    await _set_all_pages_duration(page, n_pages_target,
                                                   scene_duration, sid)
                except Exception as exc:
                    _log(sid, f"⚠ Set duration lỗi: {exc}", "warning")

            # ── Optional: export ──
            if export_mp4:
                await _trigger_export_mp4(page, sid)
                _set_status(sid, "exporting", progress=96,
                            progress_label="Canva đang render — kiểm tra cửa sổ Download")

            _set_status(sid, "done", progress=100,
                        progress_label="Hoàn thành — kiểm tra kết quả trong cửa sổ Canva", done=True)
            _log(sid, "✅ Hoàn thành. Cửa sổ vẫn mở để bạn review/lưu.", "success")

            # Idle hold open until user closes — also drain clipboard queue
            idle_deadline = time.time() + 30 * 60
            while time.time() < idle_deadline and not stop_event.is_set():
                try:
                    if not context.pages:
                        break
                    # Drain pending clipboard pushes from copy_scene endpoint
                    pending_texts: List[str] = []
                    with _sessions_lock:
                        s = _sessions.get(sid) or {}
                        q = s.get("_clipboard_queue") or []
                        if q:
                            pending_texts = list(q)
                            s["_clipboard_queue"] = []
                    for t in pending_texts:
                        try:
                            cur_page = context.pages[0]
                            await cur_page.evaluate(
                                "async (t) => { try { await navigator.clipboard.writeText(t); } catch(e){} }",
                                t,
                            )
                        except Exception as ex:
                            _log(sid, f"⚠ Không đẩy được clipboard: {ex}", "warning")
                    await page.evaluate("() => 1")
                except Exception:
                    break
                await asyncio.sleep(1.5)

        finally:
            try:
                await _save_state(context, _CV_PROFILE_DIR, sid)
            except Exception:
                pass
            try:
                await context.close()
            except Exception:
                pass
            if gate_held:
                try:
                    _LOGIN_GATE.release()
                except Exception:
                    pass
            _log(sid, "🏁 Phiên Canva kết thúc.", "info")


def _launch_session_thread(sid: str, params: Dict[str, Any]):
    def _runner():
        try:
            asyncio.run(_run_canva_flow(sid, params))
        except Exception as exc:  # noqa: BLE001
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"❌ Lỗi: {exc}", "error")

    threading.Thread(target=_runner, daemon=True).start()


# ── Lightweight login flow (no template) ─────────────────────────────────────
async def _run_open_login_flow(sid: str):
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _set_status(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return

    _CV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _set_status(sid, "launching")
    _log(sid, "🌐 Mở Chromium để đăng nhập Canva.")

    stop_event = _sessions[sid]["stop_event"]

    async with async_playwright() as pw:
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_CV_PROFILE_DIR),
                headless=False,
                viewport={"width": 1280, "height": 850},
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        except Exception as exc:
            _cleanup_profile_locks(_CV_PROFILE_DIR)
            try:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(_CV_PROFILE_DIR),
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                )
            except Exception as exc2:
                _set_status(sid, "error", error=f"Không mở Chromium: {exc2}", done=True)
                return

        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(CANVA_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            except Exception:
                pass
            _set_status(sid, "waiting_login")
            _log(sid, "🔐 Đăng nhập Canva trong cửa sổ — tool sẽ tự lưu session.", "warning")
            ok = await _wait_logged_in(page, sid, timeout=600)
            if ok:
                await _save_state(context, _CV_PROFILE_DIR, sid)
                _set_status(sid, "done", done=True, progress=100, progress_label="Đã đăng nhập")
                _log(sid, "✅ Đã đăng nhập, đã lưu session.", "success")
            else:
                _set_status(sid, "error", error="Hết 10 phút mà chưa login", done=True)

            # Hold open briefly so storage_state really persists, then close
            await asyncio.sleep(2)
        finally:
            try:
                await context.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Library scraper — downloads a creator's graphics from /p/<creator>
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_creator(creator: str) -> str:
    """Strip @ and trailing /, lower-case for filesystem safety."""
    c = (creator or "").strip()
    if c.startswith("@"):
        c = c[1:]
    c = c.replace("/", "").strip().lower()
    return c


def _library_dir(creator: str) -> Path:
    return _CV_LIBRARY_DIR / _normalize_creator(creator)


def _library_index_path(creator: str) -> Path:
    return _library_dir(creator) / "_index.json"


def _read_library_index(creator: str) -> List[Dict[str, Any]]:
    p = _library_index_path(creator)
    if not p.exists():
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("items") or [])
    except Exception:
        return []


def _write_library_index(creator: str, items: List[Dict[str, Any]]) -> None:
    p = _library_index_path(creator)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "creator": _normalize_creator(creator),
        "updated_at": int(time.time()),
        "count": len(items),
        "items": items,
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# Scrape sessions (separate from upload sessions)
_scrape_sessions: Dict[str, Dict[str, Any]] = {}
_scrape_lock = threading.Lock()


def _new_scrape_session() -> Dict[str, Any]:
    return {
        "status": "starting",
        "log": [],
        "error": "",
        "done": False,
        "items": [],
        "progress": 0,
        "progress_label": "",
        "stop_event": threading.Event(),
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _scrape_log(sid: str, msg: str, level: str = "info"):
    with _scrape_lock:
        s = _scrape_sessions.get(sid)
        if s is not None:
            s["log"].append({"t": time.time(), "level": level, "msg": msg})
            s["updated_at"] = time.time()
    LOGGER.info("[canva-scrape %s] %s", sid, msg)


def _scrape_status(sid: str, status: str, **kw):
    with _scrape_lock:
        s = _scrape_sessions.get(sid)
        if s is None:
            return
        s["status"] = status
        for k, v in kw.items():
            s[k] = v
        s["updated_at"] = time.time()


async def _scrape_creator_graphics(sid: str, creator: str, kind: str = "graphics",
                                    max_items: int = 200):
    """Open the creator portfolio page (/p/<creator>), switch the format
    dropdown to 'Đồ họa' (or keep 'Ảnh'), scroll to load all tiles, then
    download each thumbnail to the local library.

    `kind` ∈ {"graphics", "photos", "all"} → maps to "Đồ họa", "Ảnh", or both.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        _scrape_status(sid, "error", error=f"Playwright không khả dụng: {exc}", done=True)
        return

    creator_norm = _normalize_creator(creator)
    if not creator_norm:
        _scrape_status(sid, "error", error="Creator không hợp lệ", done=True)
        return

    portfolio_url = f"https://www.canva.com/p/{creator_norm}"
    out_dir = _library_dir(creator_norm)
    out_dir.mkdir(parents=True, exist_ok=True)

    _scrape_log(sid, f"🌐 Mở portfolio: {portfolio_url}")
    _scrape_status(sid, "launching", progress=5, progress_label="Mở Chromium")

    _CV_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_profile_locks(_CV_PROFILE_DIR)

    stop_event = _scrape_sessions[sid]["stop_event"]

    async with async_playwright() as pw:
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(_CV_PROFILE_DIR),
                headless=False,
                viewport={"width": 1440, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        except Exception as exc:
            _scrape_status(sid, "error", error=f"Không mở Chromium: {exc}", done=True)
            return

        try:
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(portfolio_url, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                _scrape_log(sid, f"⚠ goto chậm: {exc}", "warning")

            # Login redirect — wait for user
            if "login" in (page.url or ""):
                _scrape_status(sid, "waiting_login", progress=8)
                _scrape_log(sid, "🔐 Đăng nhập Canva trong cửa sổ đang mở...", "warning")
                ok = await _wait_logged_in(page, sid, timeout=600) if False else False
                # We have a different session map than _wait_logged_in expects;
                # do a simple URL poll here.
                deadline = time.time() + 600
                while time.time() < deadline and not stop_event.is_set():
                    if "/p/" in (page.url or ""):
                        ok = True
                        break
                    if "login" not in (page.url or ""):
                        ok = True
                        break
                    await asyncio.sleep(2)
                if not ok:
                    _scrape_status(sid, "error", error="User chưa login", done=True)
                    return
                # Re-navigate to the portfolio URL after login
                try:
                    await page.goto(portfolio_url, wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass

            await asyncio.sleep(2.5)

            # ── Switch the format dropdown to "Đồ họa" if requested ──
            if kind in ("graphics", "all"):
                _scrape_log(sid, "🔽 Đổi bộ lọc sang 'Đồ họa'...")
                opened = False
                for sel in [
                    'button:has-text("Ảnh")',
                    'button[aria-haspopup="listbox"]:has-text("Ảnh")',
                    'button[aria-haspopup="menu"]',
                    'button:has-text("Photos")',
                ]:
                    try:
                        el = await page.query_selector(sel)
                        if el and await el.is_visible():
                            await el.click()
                            opened = True
                            break
                    except Exception:
                        pass
                if opened:
                    await asyncio.sleep(0.7)
                    for sel in [
                        '[role="menuitem"]:has-text("Đồ họa")',
                        '[role="option"]:has-text("Đồ họa")',
                        'li:has-text("Đồ họa")',
                        'button:has-text("Đồ họa")',
                        '[role="menuitem"]:has-text("Graphics")',
                    ]:
                        try:
                            el = await page.query_selector(sel)
                            if el and await el.is_visible():
                                await el.click()
                                _scrape_log(sid, "✅ Đã chọn 'Đồ họa'.")
                                break
                        except Exception:
                            pass
                else:
                    _scrape_log(sid, "⚠ Không mở được dropdown lọc — sẽ scrape mục đang hiển thị.", "warning")
                await asyncio.sleep(2.0)

            # ── Scroll to load lazy-loaded items ──
            _scrape_status(sid, "scrolling", progress=20, progress_label="Cuộn để tải tất cả tiles")
            _scrape_log(sid, "📜 Cuộn để load tất cả tiles...")
            seen_count = 0
            stagnant = 0
            for step in range(40):  # max 40 scroll steps
                if stop_event.is_set():
                    break
                try:
                    cur_count = await page.evaluate("() => document.querySelectorAll('img').length")
                except Exception:
                    cur_count = seen_count
                if cur_count > seen_count:
                    seen_count = cur_count
                    stagnant = 0
                else:
                    stagnant += 1
                if stagnant >= 4:
                    break
                try:
                    await page.evaluate("() => window.scrollBy(0, document.body.scrollHeight)")
                except Exception:
                    pass
                await asyncio.sleep(1.2)

            # ── Collect tile data ──
            _scrape_status(sid, "collecting", progress=50, progress_label="Thu thập danh sách hình")
            tiles = await page.evaluate(
                """
                () => {
                  const out = [];
                  // Each tile is a link/button containing an <img>. We grab src + alt + parent label.
                  const seen = new Set();
                  const imgs = Array.from(document.querySelectorAll('img'));
                  for (const img of imgs) {
                    const src = img.currentSrc || img.src || '';
                    if (!src) continue;
                    if (!src.includes('canva.com') && !src.includes('media-public')) continue;
                    if (seen.has(src)) continue;
                    seen.add(src);
                    const alt = img.alt || '';
                    // Walk up to find the link href if any
                    let href = '';
                    let p = img.parentElement;
                    let depth = 0;
                    while (p && depth < 6) {
                      if (p.tagName === 'A' && p.href) { href = p.href; break; }
                      p = p.parentElement;
                      depth++;
                    }
                    out.push({ src, alt, href });
                  }
                  return out;
                }
                """
            )

            # Filter: portfolio thumbnails come from media-public.canva.com
            tiles = [t for t in tiles if "media-public.canva.com" in (t.get("src") or "")]
            _scrape_log(sid, f"🔍 Tìm thấy {len(tiles)} thumbnails.")
            if max_items and len(tiles) > max_items:
                tiles = tiles[:max_items]

            # ── Download via httpx (we already saw httpx in requirements) ──
            _scrape_status(sid, "downloading", progress=60,
                           progress_label=f"Tải {len(tiles)} hình về local")
            try:
                import httpx
            except Exception:
                _scrape_status(sid, "error", error="httpx not installed", done=True)
                return

            items = []
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for i, tile in enumerate(tiles):
                    if stop_event.is_set():
                        break
                    src = tile["src"]
                    # Use the highest-res version: Canva URLs end with /size_NNN — try /size_960 first
                    hi = src
                    try:
                        # Common pattern: ".../size_240/..." → bump to size_960
                        import re
                        hi = re.sub(r"/size_\d+/", "/size_960/", src)
                    except Exception:
                        pass
                    fname = f"{i+1:04d}_{uuid.uuid4().hex[:6]}.png"
                    fpath = out_dir / fname
                    ok = False
                    for url_try in (hi, src):
                        try:
                            resp = await client.get(url_try)
                            if resp.status_code == 200 and resp.content:
                                fpath.write_bytes(resp.content)
                                ok = True
                                break
                        except Exception:
                            continue
                    if ok:
                        items.append({
                            "id": fname.split("_", 1)[0],
                            "name": tile.get("alt") or fname,
                            "file": str(fpath),
                            "rel": str(fpath.relative_to(ROOT)).replace("\\", "/"),
                            "src": tile.get("src"),
                            "alt": tile.get("alt") or "",
                            "href": tile.get("href") or "",
                        })
                    if (i + 1) % 5 == 0:
                        pct = 60 + int(35 * (i + 1) / max(len(tiles), 1))
                        _scrape_status(sid, "downloading", progress=pct,
                                       progress_label=f"Đã tải {i+1}/{len(tiles)}")

            _write_library_index(creator_norm, items)
            _scrape_log(sid, f"💾 Đã lưu {len(items)} hình vào {out_dir.relative_to(ROOT)}", "success")
            _scrape_status(sid, "done", progress=100,
                           progress_label=f"Hoàn tất ({len(items)} hình)",
                           done=True, items=items)
        except Exception as exc:
            _scrape_status(sid, "error", error=str(exc), done=True)
            _scrape_log(sid, f"❌ {exc}", "error")
        finally:
            try:
                await context.close()
            except Exception:
                pass


def _launch_scrape_thread(sid: str, creator: str, kind: str, max_items: int):
    def _runner():
        try:
            asyncio.run(_scrape_creator_graphics(sid, creator, kind, max_items))
        except Exception as exc:
            _scrape_status(sid, "error", error=str(exc), done=True)

    threading.Thread(target=_runner, daemon=True).start()


# ── Routes ───────────────────────────────────────────────────────────────────
@bp.route("/api/canva/check_login", methods=["GET"])
def cv_check_login():
    return jsonify({"ok": True, "logged_in": _has_login_cookies(_CV_PROFILE_DIR)})


@bp.route("/api/canva/open_login", methods=["POST"])
def cv_open_login():
    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium",
        }), 500

    sid = uuid.uuid4().hex[:12]
    with _sessions_lock:
        _sessions[sid] = _new_session()
    _log(sid, "📥 Yêu cầu mở Canva để login")

    def _runner():
        try:
            asyncio.run(_run_open_login_flow(sid))
        except Exception as exc:
            _set_status(sid, "error", error=str(exc), done=True)
            _log(sid, f"❌ {exc}", "error")

    threading.Thread(target=_runner, daemon=True).start()
    return jsonify({"ok": True, "session_id": sid})


@bp.route("/api/canva/profile_reset", methods=["POST"])
def cv_profile_reset():
    try:
        if _CV_PROFILE_DIR.exists():
            shutil.rmtree(str(_CV_PROFILE_DIR), ignore_errors=True)
        return jsonify({"ok": True, "message": "Đã xoá profile Canva."})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/canva/upload_image", methods=["POST"])
def cv_upload_image():
    f = request.files.get("image")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "Thiếu file"}), 400
    fname = secure_filename(f.filename)
    ext = Path(fname).suffix.lower()
    if ext not in ALLOWED_IMG_EXT:
        return jsonify({"ok": False, "error": f"Định dạng {ext} không hỗ trợ"}), 400
    # Make filename unique
    unique = f"{uuid.uuid4().hex[:10]}_{fname}"
    out_path = _CV_UPLOAD_DIR / unique
    f.save(str(out_path))
    return jsonify({"ok": True, "path": str(out_path), "name": fname})


@bp.route("/api/canva/prepare_design", methods=["POST"])
def cv_prepare_design():
    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium",
        }), 500

    data = request.get_json(silent=True) or {}
    template_url = str(data.get("template_url") or "").strip()
    scenes = list(data.get("scenes") or [])
    voiceover = str(data.get("voiceover") or "").strip()
    caption = str(data.get("caption") or "").strip()
    image_paths = list(data.get("image_paths") or [])
    export_mp4 = bool(data.get("export_mp4"))
    set_animation = bool(data.get("set_animation"))
    animation = str(data.get("animation") or "").strip()
    aspect = str(data.get("aspect") or "16:9").strip()
    # New `search_prefix` (free-text, e.g. "stickman", "chibi"), with fallback
    # to legacy `creator` so older clients still work.
    search_prefix = str(data.get("search_prefix") or data.get("creator") or "stickman").strip()
    add_elements = bool(data.get("add_elements", True))
    scene_duration = float(data.get("scene_duration") or 5)

    if not scenes and not image_paths and not template_url:
        return jsonify({"ok": False, "error": "Cần ít nhất template_url hoặc scenes hoặc image_paths"}), 400

    sid = uuid.uuid4().hex[:12]
    with _sessions_lock:
        _sessions[sid] = _new_session()

    n_scenes = len(scenes)
    _log(sid, f"📥 Bắt đầu phiên Canva: {n_scenes} cảnh, {len(image_paths)} ảnh, "
              f"export={export_mp4}, template={'có' if template_url else 'tự tạo mới'}, "
              f"prefix='{search_prefix}'")

    _launch_session_thread(sid, {
        "template_url": template_url,
        "scenes": scenes,
        "voiceover": voiceover,
        "caption": caption,
        "image_paths": image_paths,
        "export_mp4": export_mp4,
        "set_animation": set_animation,
        "animation": animation,
        "aspect": aspect,
        "search_prefix": search_prefix,
        "add_elements": add_elements,
        "scene_duration": scene_duration,
    })
    return jsonify({"ok": True, "session_id": sid})


@bp.route("/api/canva/prepare_status", methods=["GET"])
def cv_prepare_status():
    sid = str(request.args.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "Thiếu session_id"}), 400
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "Session không tồn tại"}), 404
        return jsonify({
            "ok": True,
            "status": s["status"],
            "log": s["log"][-200:],
            "done": s["done"],
            "error": s["error"],
            "progress": s.get("progress", 0),
            "progress_label": s.get("progress_label", ""),
        })


@bp.route("/api/canva/prepare_close", methods=["POST"])
def cv_prepare_close():
    data = request.get_json(silent=True) or {}
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


@bp.route("/api/canva/copy_scene", methods=["POST"])
def cv_copy_scene():
    """Push a scene's text to the open browser's clipboard so the user can
    Ctrl+V into Canva. Useful when auto-fill fails because Canva's DOM
    doesn't expose the text element to Playwright (e.g. it's inside an
    iframe or shadow root).
    """
    data = request.get_json(silent=True) or {}
    sid = str(data.get("session_id") or "").strip()
    text = str(data.get("text") or "")
    if not sid:
        return jsonify({"ok": False, "error": "Thiếu session_id"}), 400
    with _sessions_lock:
        s = _sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "Session không tồn tại"}), 404
        ctx = s.get("_context")
    if ctx is None:
        return jsonify({"ok": False, "error": "Browser chưa khởi động xong"}), 400

    async def _do():
        try:
            pages = ctx.pages
            if not pages:
                return False, "Không có tab nào"
            page = pages[0]
            await page.evaluate(
                "async (t) => { try { await navigator.clipboard.writeText(t); } catch(e){} }",
                text,
            )
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # We have to run the async call in this session's event loop. The browser
    # was launched on a separate thread+loop, so we use loop_call_soon-safe via
    # a fresh asyncio.run is not safe (would create another loop). Instead we
    # piggyback on the session's running coroutine by putting the text on a
    # shared queue that the run loop drains. Simpler: schedule a synchronous
    # blocking call on the playwright thread by using an asyncio Event.
    #
    # Workaround: use Playwright's sync API on a fresh tiny browser context?
    # That won't share clipboard with the open window.
    #
    # Best simple approach: stash text on session and have the main loop poll.
    with _sessions_lock:
        pending = s.setdefault("_clipboard_queue", [])
        pending.append(text)
    _log(sid, f"📋 Đã đẩy {len(text)} ký tự vào hàng chờ clipboard. "
              f"Đợi 1-2 giây rồi click vào ô text trên Canva và bấm Ctrl+V.", "info")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Library routes — pre-scrape a creator's graphics so we can drop them later
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/api/canva/library/build", methods=["POST"])
def cv_lib_build():
    """Start a Playwright session that opens https://www.canva.com/p/<creator>,
    switches to 'Đồ họa', scrolls all tiles, and downloads each thumbnail to
    storage/canva_library/<creator>/.
    """
    try:
        import playwright  # noqa: F401
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Chưa cài Playwright. Chạy: pip install playwright && playwright install chromium",
        }), 500

    data = request.get_json(silent=True) or {}
    creator = str(data.get("creator") or "zdeneksasek").strip()
    kind = str(data.get("kind") or "graphics").strip().lower()
    if kind not in ("graphics", "photos", "all"):
        kind = "graphics"
    try:
        max_items = int(data.get("max_items") or 200)
    except Exception:
        max_items = 200
    max_items = max(10, min(max_items, 1000))

    sid = uuid.uuid4().hex[:12]
    with _scrape_lock:
        _scrape_sessions[sid] = _new_scrape_session()
    _scrape_log(sid, f"📥 Build library cho creator '{creator}' "
                     f"(kind={kind}, max={max_items})")
    _launch_scrape_thread(sid, creator, kind, max_items)
    return jsonify({"ok": True, "session_id": sid})


@bp.route("/api/canva/library/status", methods=["GET"])
def cv_lib_status():
    sid = str(request.args.get("session_id") or "").strip()
    if not sid:
        return jsonify({"ok": False, "error": "Thiếu session_id"}), 400
    with _scrape_lock:
        s = _scrape_sessions.get(sid)
        if not s:
            return jsonify({"ok": False, "error": "Session không tồn tại"}), 404
        return jsonify({
            "ok": True,
            "status": s["status"],
            "log": s["log"][-200:],
            "done": s["done"],
            "error": s["error"],
            "progress": s.get("progress", 0),
            "progress_label": s.get("progress_label", ""),
            "items_count": len(s.get("items") or []),
        })


@bp.route("/api/canva/library/list", methods=["GET"])
def cv_lib_list():
    """List all locally-cached graphics for a creator."""
    creator = str(request.args.get("creator") or "zdeneksasek").strip()
    items = _read_library_index(creator)
    creator_norm = _normalize_creator(creator)
    return jsonify({
        "ok": True,
        "creator": creator_norm,
        "count": len(items),
        "items": items,
    })


@bp.route("/api/canva/library/image", methods=["GET"])
def cv_lib_image():
    """Serve a single library image by creator + filename."""
    from flask import send_file, abort
    creator = str(request.args.get("creator") or "zdeneksasek").strip()
    name = str(request.args.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        abort(400)
    p = _library_dir(creator) / name
    if not p.exists():
        abort(404)
    return send_file(str(p), mimetype="image/png")


@bp.route("/api/canva/library/clear", methods=["POST"])
def cv_lib_clear():
    """Delete the local library for a creator."""
    data = request.get_json(silent=True) or {}
    creator = str(data.get("creator") or "").strip()
    if not creator:
        return jsonify({"ok": False, "error": "Thiếu creator"}), 400
    p = _library_dir(creator)
    try:
        if p.exists():
            shutil.rmtree(str(p), ignore_errors=True)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# AI Scene Planner — analyze voiceover text → generate storyboard with
# timing, keywords, positions, and transitions for each component.
# ─────────────────────────────────────────────────────────────────────────────

_PLAN_SYSTEM_PROMPT = """Bạn là AI storyboard planner cho video Canva (1920×1080).
Nhiệm vụ: phân tích KỊCH BẢN (mô tả hành động từng cảnh) → tách thành các COMPONENT (thành phần đồ họa cần tìm trên Canva).

Input là kịch bản dạng:
  Cảnh 1 — Buổi sáng
  (Stick figure nằm ngủ. Báo thức reo.)
  ...

Mỗi component output gồm:
- keyword: từ khoá tiếng Anh ngắn để search Canva Elements (ví dụ: "stickman sleep", "alarm clock", "arrow right", "stickman run bus")
- start_s: thời gian bắt đầu hiện (giây)
- end_s: thời gian kết thúc (giây)
- x: vị trí X tâm trên canvas (0–1920)
- y: vị trí Y tâm trên canvas (0–1080)
- w: chiều rộng element (300-800 pixels, mặc định 500)
- h: chiều cao element (300-600 pixels, mặc định 400)
- animation: hiệu ứng ("Hiện lên" / "Rõ dần" / "Lướt" / "Bật ra" / "Gạt")
- category: "Đồ họa" (mặc định)
- note: mô tả ngắn component này thể hiện gì trong kịch bản

Quy tắc:
1. Mỗi cảnh trong kịch bản → 1-2 components (nhân vật chính + mũi tên chuyển cảnh nếu cần).
2. Thời gian mỗi cảnh tỉ lệ với độ phức tạp (cảnh nhiều hành động = dài hơn).
3. QUAN TRỌNG: Tổng thời gian PHẢI = duration được cung cấp. Component cuối cùng PHẢI có end_s ≤ duration. KHÔNG ĐƯỢC vượt quá duration.
4. QUAN TRỌNG: Các component KHÔNG ĐƯỢC trùng thời gian. Mỗi component phải NỐI TIẾP nhau — start_s của component sau = end_s của component trước. KHÔNG overlap.
5. Bố cục: mỗi component ở vị trí khác nhau trên canvas.
   - Nhân vật chính: giữa hoặc hơi lệch (x=700-1200, y=400-700)
   - Đạo cụ/bối cảnh: góc hoặc cạnh (x<500 hoặc x>1400)
   - Text: dưới cùng (y>800) hoặc trên cùng (y<200)
   - Mũi tên chuyển cảnh: giữa (x=960, y=540)
6. Thêm "arrow right" hoặc "transition" giữa các cảnh (thời gian ngắn 0.5-1s, NỐI TIẾP không overlap).
7. Keyword phải cụ thể, dễ tìm trên Canva (ví dụ: "stickman eating noodles" thay vì chỉ "ăn").
8. Trả về JSON array, KHÔNG có text ngoài JSON.
9. Nếu kịch bản dài mà duration ngắn, hãy GIẢM số components hoặc GIẢM thời gian mỗi component để vừa với duration. Ưu tiên giữ đúng duration hơn là đủ chi tiết.
10. Mỗi component nên có duration tối thiểu 2s để người xem kịp nhìn.

Ví dụ output cho 1 cảnh "Buổi sáng - báo thức" (duration 8s):
[
  {"keyword":"stickman sleep bed","start_s":0,"end_s":3,"x":700,"y":540,"w":500,"h":400,"animation":"Hiện lên","category":"Đồ họa","note":"Nhân vật nằm ngủ"},
  {"keyword":"alarm clock ringing","start_s":3,"end_s":5.5,"x":1200,"y":300,"w":300,"h":300,"animation":"Bật ra","category":"Đồ họa","note":"Báo thức reo"},
  {"keyword":"stickman wake up","start_s":5.5,"end_s":7,"x":700,"y":540,"w":500,"h":400,"animation":"Rõ dần","category":"Đồ họa","note":"Bật dậy hoảng"},
  {"keyword":"arrow right","start_s":7,"end_s":8,"x":960,"y":540,"w":400,"h":150,"animation":"Lướt","category":"Đồ họa","note":"Chuyển cảnh"}
]"""


@bp.route("/api/canva/plan_scenes", methods=["POST"])
def cv_plan_scenes():
    """Use AI to analyze the SCRIPT (kịch bản) and generate a storyboard plan.

    Body:
      script (str) — the full script/kịch bản with scene descriptions
      voiceover (str, optional) — voiceover text (used for timing estimation)
      duration_s (float, optional) — total MP3 duration in seconds (if known)
      style (str, optional) — "stickman" / "chibi" / "cartoon" (prefix for keywords)
      canvas_w (int, optional) — canvas width, default 1920
      canvas_h (int, optional) — canvas height, default 1080

    Returns:
      {ok: true, components: [...], total_duration_s: float}
    """
    import requests as _requests

    data = request.get_json(silent=True) or {}
    script = str(data.get("script") or "").strip()
    voiceover = str(data.get("voiceover") or "").strip()
    # Use script as primary input; fall back to voiceover if script is empty
    input_text = script or voiceover
    if not input_text:
        return jsonify({"ok": False, "error": "Thiếu kịch bản hoặc voiceover"}), 400

    duration_s = float(data.get("duration_s") or 0)
    style = str(data.get("style") or "stickman").strip()
    canvas_w = int(data.get("canvas_w") or 1920)
    canvas_h = int(data.get("canvas_h") or 1080)

    # Estimate duration from voiceover word count if not provided
    if duration_s <= 0:
        ref_text = voiceover or input_text
        word_count = len(ref_text.split())
        duration_s = max(15, word_count / 2.5)  # ~150 words/min for VN

    user_msg = (
        f"Kịch bản video ({duration_s:.1f}s tổng, canvas {canvas_w}×{canvas_h}, style: {style}):\n\n"
        f"{input_text}\n\n"
    )
    if voiceover and script:
        user_msg += f"Voiceover (dùng để tính timing):\n{voiceover}\n\n"
    user_msg += "Hãy tạo storyboard components. Trả về JSON array."

    # Call AI via the same 9Router endpoint used by chatbot
    from core_app import load_cfg
    cfg = load_cfg()
    nr = cfg.get("nine_router") or cfg.get("9router") or {}
    api_key = str(nr.get("api_key") or "").strip()
    endpoint = str(nr.get("endpoint") or "https://api.9router.com/v1").strip().rstrip("/")
    model = str(nr.get("model") or "gpt-4o-mini").strip()

    if not api_key:
        # Fallback: use heuristic planner
        components = _heuristic_plan(voiceover, duration_s, style, canvas_w, canvas_h)
        return jsonify({"ok": True, "components": components,
                        "total_duration_s": duration_s, "method": "heuristic"})

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
    }

    try:
        r = _requests.post(f"{endpoint}/chat/completions",
                           json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        resp = r.json()
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Parse JSON from response (may have markdown fences)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        components = json.loads(content)
        if not isinstance(components, list):
            raise ValueError("Expected JSON array")
        # Post-process: clamp any timing that exceeds duration_s
        components = _clamp_plan_timing(components, duration_s)
        return jsonify({"ok": True, "components": components,
                        "total_duration_s": duration_s, "method": "ai"})
    except Exception as exc:
        LOGGER.warning("[canva plan] AI failed: %s — falling back to heuristic", exc)
        components = _heuristic_plan(voiceover, duration_s, style, canvas_w, canvas_h)
        return jsonify({"ok": True, "components": components,
                        "total_duration_s": duration_s, "method": "heuristic",
                        "ai_error": str(exc)})


def _clamp_plan_timing(components: List[Dict[str, Any]], duration_s: float) -> List[Dict[str, Any]]:
    """Ensure no component exceeds the total duration and no overlaps exist.

    If AI returned timing beyond duration_s, scale all timings proportionally
    to fit within the allowed duration. Also fix any overlapping components
    by making them sequential.
    """
    if not components or duration_s <= 0:
        return components

    # Find the maximum end_s across all components
    max_end = max((float(c.get("end_s") or 0) for c in components), default=0)

    if max_end > duration_s:
        # Scale all timings proportionally to fit within duration_s
        scale = duration_s / max_end
        for c in components:
            c["start_s"] = round(float(c.get("start_s") or 0) * scale, 1)
            c["end_s"] = round(float(c.get("end_s") or 0) * scale, 1)

    # Fix overlaps: ensure each component starts AFTER the previous one ends
    # Sort by start_s first
    components.sort(key=lambda c: float(c.get("start_s") or 0))

    for i in range(len(components)):
        c = components[i]
        c["start_s"] = float(c.get("start_s") or 0)
        c["end_s"] = float(c.get("end_s") or 0)

        # Ensure minimum duration of 1s per component
        if c["end_s"] - c["start_s"] < 1.0:
            c["end_s"] = c["start_s"] + 1.0

        # Ensure this component doesn't overlap with the previous one
        if i > 0:
            prev_end = components[i - 1]["end_s"]
            if c["start_s"] < prev_end:
                # Shift this component to start right after previous
                shift = prev_end - c["start_s"]
                c["start_s"] = prev_end
                c["end_s"] += shift

        # Clamp to duration
        c["start_s"] = min(c["start_s"], duration_s)
        c["end_s"] = min(c["end_s"], duration_s)

        # Round
        c["start_s"] = round(c["start_s"], 1)
        c["end_s"] = round(c["end_s"], 1)

    # Remove components that ended up with 0 duration (pushed past the end)
    components = [c for c in components if c["end_s"] > c["start_s"]]

    return components


def _heuristic_plan(voiceover: str, duration_s: float, style: str,
                     canvas_w: int, canvas_h: int) -> List[Dict[str, Any]]:
    """Simple rule-based scene planner when AI is unavailable."""
    import re

    # Split voiceover into sentences
    sentences = re.split(r'[.!?…]+', voiceover)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]
    if not sentences:
        sentences = [voiceover]

    n = len(sentences)
    # Distribute time proportionally by character count
    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        total_chars = 1

    # ── Calculate how much time is available for content (excluding arrows) ──
    # Arrows overlap with the previous component by 1s and extend 0.5s beyond.
    # With (n-1) arrows, total arrow overhead = (n-1) * 0.5s (the non-overlapping part).
    # But we want total timeline to NOT exceed duration_s.
    n_arrows = max(0, n - 1)
    # Reserve no extra time for arrows since they overlap with components
    available_duration = duration_s

    components = []
    current_t = 0.0
    positions = [
        (int(canvas_w * 0.25), int(canvas_h * 0.5)),   # left
        (int(canvas_w * 0.5), int(canvas_h * 0.5)),    # center
        (int(canvas_w * 0.75), int(canvas_h * 0.5)),   # right
        (int(canvas_w * 0.5), int(canvas_h * 0.3)),    # top-center
        (int(canvas_w * 0.5), int(canvas_h * 0.7)),    # bottom-center
    ]
    animations = ["Hiện lên", "Rõ dần", "Lướt", "Bật ra"]

    # Simple keyword extraction from Vietnamese text
    keyword_map = [
        (r'báo thức|thức dậy|buổi sáng', 'alarm'),
        (r'chạy|vội|xe bus', 'run'),
        (r'ăn|bữa ăn|cơm|mì', 'eat'),
        (r'laptop|làm việc|deadline|áp lực', 'work laptop'),
        (r'mưa|buổi tối|đi bộ', 'walk rain'),
        (r'ngủ|giường|nghỉ|mệt', 'sleep tired'),
        (r'cố gắng|tiếp tục|bước đi', 'walk forward'),
        (r'mèo|nhà|về', 'home cat'),
        (r'vui|cười|hạnh phúc', 'happy'),
        (r'buồn|khóc', 'sad'),
    ]

    # ── First pass: calculate raw durations proportionally ──
    raw_durations = []
    for sentence in sentences:
        dur = (len(sentence) / total_chars) * available_duration
        raw_durations.append(dur)

    # ── Second pass: normalize so total exactly equals available_duration ──
    # Apply a soft clamp (min 1.5s) but then scale everything to fit
    min_dur = 1.5
    clamped = [max(min_dur, d) for d in raw_durations]
    total_clamped = sum(clamped)
    if total_clamped > available_duration:
        # Scale down proportionally to fit within available_duration
        scale = available_duration / total_clamped
        clamped = [d * scale for d in clamped]

    for i, sentence in enumerate(sentences):
        dur = clamped[i]

        # Find keyword
        kw = "person"
        lower = sentence.lower()
        for pattern, keyword in keyword_map:
            if re.search(pattern, lower):
                kw = keyword
                break

        pos = positions[i % len(positions)]
        anim = animations[i % len(animations)]

        # Reserve time for arrow transition (0.8s) between scenes
        has_arrow = (i < n - 1) and dur > 2.5
        scene_dur = dur - 0.8 if has_arrow else dur

        components.append({
            "keyword": f"{style} {kw}",
            "start_s": round(current_t, 1),
            "end_s": round(current_t + scene_dur, 1),
            "x": pos[0],
            "y": pos[1],
            "w": 500,
            "h": 400,
            "animation": anim,
            "category": "Đồ họa",
            "note": sentence[:60],
        })

        current_t += scene_dur

        # Add arrow AFTER the scene (sequential, no overlap)
        if has_arrow:
            components.append({
                "keyword": "arrow right",
                "start_s": round(current_t, 1),
                "end_s": round(current_t + 0.8, 1),
                "x": int(canvas_w * 0.5),
                "y": int(canvas_h * 0.5),
                "w": 400,
                "h": 150,
                "animation": "Lướt",
                "category": "Đồ họa",
                "note": "Chuyển cảnh",
            })
            current_t += 0.8

        # Safety: don't exceed total duration
        if current_t >= available_duration:
            break

    return components

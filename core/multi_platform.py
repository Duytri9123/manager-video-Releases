"""Multi-platform helper — dùng yt-dlp để hỗ trợ tìm user & tải video từ
nhiều nền tảng (TikTok, YouTube, Instagram, Facebook, ...), bổ trợ cho luồng
Douyin gốc.

Thiết kế theo tinh thần tham khảo từ dự án Uploadvideo (yt-dlp xử lý mọi nền
tảng chỉ với một code-path), nhưng gói lại thành các hàm tiện dụng cho toolvideo:

- detect_platform(url)      → tên nền tảng ('douyin' | 'tiktok' | 'youtube' | ...)
- is_douyin(url)            → True nếu URL thuộc Douyin (dùng downloader gốc)
- fetch_profile(url)        → thông tin user + danh sách video (đa nền tảng)
- download_video(url, ...)  → tải 1 video bất kỳ qua yt-dlp
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse


# ── Nhận diện nền tảng từ URL ────────────────────────────────────────────────
_PLATFORM_HOSTS = {
    "douyin":    ("douyin.com", "iesdouyin.com"),
    "tiktok":    ("tiktok.com",),
    "youtube":   ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "instagram": ("instagram.com",),
    "facebook":  ("facebook.com", "fb.watch", "fb.com"),
    "bilibili":  ("bilibili.com", "b23.tv"),
    "kuaishou":  ("kuaishou.com",),
    "twitter":   ("twitter.com", "x.com"),
}

PLATFORM_LABELS = {
    "douyin":    "Douyin",
    "tiktok":    "TikTok",
    "youtube":   "YouTube",
    "instagram": "Instagram",
    "facebook":  "Facebook",
    "bilibili":  "Bilibili",
    "kuaishou":  "Kuaishou",
    "twitter":   "X / Twitter",
    "unknown":   "Khác",
}


def detect_platform(url: str) -> str:
    """Trả về tên nền tảng dựa trên hostname của URL."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return "unknown"
    if host.startswith("www."):
        host = host[4:]
    for platform, hosts in _PLATFORM_HOSTS.items():
        if any(host == h or host.endswith("." + h) or host == h for h in hosts):
            return platform
    # fallback: dò theo chuỗi con
    low = (url or "").lower()
    for platform, hosts in _PLATFORM_HOSTS.items():
        if any(h in low for h in hosts):
            return platform
    return "unknown"


def is_douyin(url: str) -> bool:
    """Douyin (kể cả link rút gọn v.douyin.com) dùng downloader gốc của app."""
    low = (url or "").lower()
    return "douyin.com" in low or "iesdouyin.com" in low


def platform_label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, PLATFORM_LABELS["unknown"])


# ── yt-dlp helpers ───────────────────────────────────────────────────────────
def _import_ytdlp():
    try:
        import yt_dlp  # noqa: WPS433
        return yt_dlp
    except Exception:
        # Thử tự cài vào chính interpreter đang chạy server (đúng venv),
        # tránh trường hợp cài nhầm sang Python khác.
        import subprocess
        import sys
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "yt-dlp"],
                check=True,
            )
            import importlib
            import yt_dlp  # noqa: WPS433
            importlib.reload(yt_dlp)
            return yt_dlp
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "yt-dlp chưa được cài cho Python đang chạy server "
                f"({sys.executable}). Chạy: \"{sys.executable}\" -m pip install yt-dlp "
                "rồi khởi động lại server."
            ) from exc


def _load_config() -> Dict[str, Any]:
    """Đọc config.yml ở thư mục gốc dự án (không phụ thuộc module khác)."""
    try:
        import yaml
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_path = os.path.join(root, "config.yml")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


_VALID_BROWSERS = {"chrome", "edge", "firefox", "brave", "opera",
                   "vivaldi", "chromium", "safari", "whale"}


def cookie_opts_for(platform: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Trả về các option cookie cho yt-dlp dựa trên config.yml (mục `ytdlp`).

    Ưu tiên:
      0) cookie_contents[<platform>] (nội dung raw dán trực tiếp, lưu thành file tạm)
      1) cookie_files[<platform>] hoặc cookie_files.all (file .txt Netscape)
      2) cookies_from_browser (yt-dlp tự đọc cookie từ trình duyệt đã đăng nhập)
    """
    cfg = cfg if cfg is not None else _load_config()
    yt = (cfg or {}).get("ytdlp") or {}
    opts: Dict[str, Any] = {}

    # 0) Kiểm tra nội dung cookie thô lưu trực tiếp trong config
    contents = yt.get("cookie_contents") or {}
    content = str(contents.get(platform) or "").strip()
    if content:
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            temp_dir = os.path.join(root, "config", "cookies")
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir, exist_ok=True)
            temp_file = os.path.join(temp_dir, f"{platform}_cookies.txt")
            
            to_save = content
            if "\t" not in content and ";" in content:
                # Chuyển đổi cookie dạng header (key=val; key2=val2) sang định dạng Netscape
                lines = ["# Netscape HTTP Cookie File", f"# Generated automatically for {platform}"]
                domain = f".{platform}.com" if platform in ("youtube", "facebook") else ".com"
                for part in content.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        lines.append(f"{domain}\tTRUE\t/\tTRUE\t1767225600\t{k}\t{v}")
                to_save = "\n".join(lines)
                
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(to_save)
            opts["cookiefile"] = temp_file
            return opts
        except Exception:
            pass

    files = yt.get("cookie_files") or {}
    if isinstance(files, dict):
        path = str(files.get(platform) or files.get("all") or "").strip()
        if path and os.path.exists(path):
            opts["cookiefile"] = path
            return opts

    browser = str(yt.get("cookies_from_browser") or "").strip().lower()
    if browser in _VALID_BROWSERS:
        profile = str(yt.get("browser_profile") or "").strip() or None
        # (browser, profile, keyring, container)
        opts["cookiesfrombrowser"] = (browser, profile, None, None)
        return opts

    return opts


def _pick_thumb(entry: Dict[str, Any]) -> str:
    """Lấy URL thumbnail tốt nhất từ một entry yt-dlp."""
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbs = entry.get("thumbnails") or []
    if thumbs:
        # yt-dlp thường sắp xếp từ nhỏ → lớn; lấy cái cuối cùng có url.
        for th in reversed(thumbs):
            if th.get("url"):
                return th["url"]
    return ""


def _fmt_date(entry: Dict[str, Any]) -> tuple[str, int]:
    ts = entry.get("timestamp") or 0
    if not ts:
        upload_date = entry.get("upload_date")  # YYYYMMDD
        if upload_date and len(str(upload_date)) == 8:
            try:
                dt = datetime.strptime(str(upload_date), "%Y%m%d")
                return dt.strftime("%Y-%m-%d"), int(dt.timestamp())
            except Exception:
                pass
        return "", 0
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), int(ts)
    except Exception:
        return "", int(ts) if ts else 0


def _entry_to_video(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Chuẩn hoá 1 entry yt-dlp về cùng schema với video Douyin của app."""
    date_str, ts = _fmt_date(entry)
    vid = str(entry.get("id") or "")
    url = entry.get("url") or entry.get("webpage_url") or ""
    # extract_flat trả 'url' có thể chỉ là id → cần ie_key; giữ nguyên,
    # phần build URL đầy đủ xử lý ở caller nếu cần.
    return {
        "aweme_id": vid,
        "url":      url,
        "desc":     (entry.get("title") or entry.get("description") or "")[:120],
        "cover":    _pick_thumb(entry),
        "date":     date_str,
        "ts":       ts,
        "play":     entry.get("view_count") or 0,
        "like":     entry.get("like_count") or 0,
        "comment":  entry.get("comment_count") or 0,
        "type":     "video",
        # yt-dlp trả duration theo GIÂY, nhưng UI (fmtDur) dùng chuẩn Douyin là
        # MILI-GIÂY. Nhân 1000 để hiển thị đúng (vd 2105s → 35:05 thay vì 0:02).
        "duration": int((entry.get("duration") or 0) * 1000),
    }


import re as _re


def _friendly_error(raw: str, platform: str, url: str) -> str:
    """Chuyển lỗi kỹ thuật của yt-dlp thành thông báo dễ hiểu + gợi ý."""
    msg = _re.sub(r"\x1b\[[0-9;]*m", "", raw or "").strip()  # bỏ mã màu ANSI
    low = msg.lower()

    if "unsupported url" in low:
        if platform == "facebook":
            return ("Facebook không hỗ trợ liệt kê trang reels/video theo tài "
                    "khoản. Hãy dán link MỘT reel/video cụ thể "
                    "(vd: facebook.com/reel/123... hoặc /watch?v=123...).")
        if platform == "instagram":
            return ("Instagram: hãy dán link 1 bài/reel cụ thể, hoặc dùng URL "
                    "dạng instagram.com/<user>/ (có thể cần cookie đăng nhập).")
        return ("URL này chưa được yt-dlp hỗ trợ liệt kê. Hãy thử dán link "
                "trang cá nhân/kênh chuẩn, hoặc link 1 video cụ thể.")

    if any(k in low for k in ("login", "log in", "cookies", "authentication",
                              "private", "sign in", "rate-limit", "restricted")):
        return (f"{platform_label(platform)} yêu cầu đăng nhập/cookie hoặc nội "
                "dung riêng tư. Hãy đặt file cookie (Netscape .txt) tương ứng "
                "vào thư mục dự án rồi thử lại.")

    if not msg:
        return "Không lấy được dữ liệu (kênh riêng tư, sai URL, hoặc cần cookie)."
    # rút gọn để không đổ nguyên stacktrace ra UI
    return msg.split("\n")[0][:300]


def fetch_profile(
    url: str,
    max_videos: int = 0,
    cookiefile: Optional[str] = None,
    proxy: Optional[str] = None,
    browser_opts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lấy thông tin user + danh sách video từ URL profile/kênh (đa nền tảng).

    Trả dict cùng schema với /api/user_info của luồng Douyin:
      { nickname, avatar, signature, follower, following, aweme_count,
        videos[], platform, has_more:false }
    """
    platform = detect_platform(url)

    # Facebook: yt-dlp không liệt kê được trang reels/video theo tài khoản →
    # dùng trình duyệt (Playwright) để cuộn & thu thập link reel.
    if platform == "facebook" and _is_fb_listing(url):
        bo = browser_opts or {}
        cfg = _load_config()
        fb_profile = cfg.get("facebook_profile") or ".facebook_profile"
        return fetch_facebook_reels(
            url,
            max_videos=max_videos,
            proxy=proxy,
            headless=bool(bo.get("headless", True)),
            max_scrolls=int(bo.get("max_scrolls", 60) or 60),
            idle_rounds=int(bo.get("idle_rounds", 5) or 5),
            wait_timeout=int(bo.get("wait_timeout_seconds", 45) or 45),
            user_data_dir=fb_profile,
        )

    yt_dlp = _import_ytdlp()

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        # Chỉ bỏ qua lỗi ở TỪNG entry con, còn lỗi ở cấp cao nhất (URL không
        # hỗ trợ, cần đăng nhập...) vẫn raise để báo cho người dùng chính xác.
        "ignoreerrors": "only_download",
        "noplaylist": False,
    }
    if max_videos and max_videos > 0:
        ydl_opts["playlistend"] = int(max_videos)
    # Cookie: ưu tiên tham số truyền vào, sau đó tới cấu hình ytdlp trong config.yml
    if cookiefile and os.path.exists(cookiefile):
        ydl_opts["cookiefile"] = cookiefile
    else:
        ydl_opts.update(cookie_opts_for(platform))
    if proxy:
        ydl_opts["proxy"] = proxy

    class _ErrLogger:
        """Ghi lại thông báo lỗi của yt-dlp (vì ignoreerrors in ra thay vì raise)."""
        def __init__(self):
            self.errors: List[str] = []
        def debug(self, m):   pass
        def info(self, m):    pass
        def warning(self, m): pass
        def error(self, m):
            if m:
                self.errors.append(str(m))

    err_logger = _ErrLogger()
    ydl_opts["logger"] = err_logger

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        err_logger.errors.append(str(exc))

    if not info:
        raw = err_logger.errors[0] if err_logger.errors else ""
        return {"error": _friendly_error(raw, platform, url)}

    entries = info.get("entries")
    videos: List[Dict[str, Any]] = []
    if entries:
        for e in entries:
            if not e:
                continue
            # yt-dlp có thể lồng playlist (vd YouTube tab) → duyệt sâu 1 cấp
            if e.get("entries"):
                for sub in e["entries"]:
                    if sub:
                        videos.append(_entry_to_video(sub))
            else:
                videos.append(_entry_to_video(e))
    else:
        # URL trỏ thẳng 1 video
        videos.append(_entry_to_video(info))

    nickname = (info.get("uploader") or info.get("channel")
                or info.get("title") or "")
    avatar = ""
    thumbs = info.get("thumbnails") or []
    for th in reversed(thumbs):
        if th.get("url"):
            avatar = th["url"]
            break

    return {
        "platform":    platform,
        "nickname":    nickname,
        "uid":         str(info.get("uploader_id") or info.get("channel_id") or ""),
        "sec_uid":     str(info.get("channel_id") or info.get("uploader_id") or ""),
        "signature":   (info.get("description") or "")[:200],
        "avatar":      avatar,
        "follower":    info.get("channel_follower_count") or 0,
        "following":   0,
        "aweme_count": info.get("playlist_count") or len(videos),
        "videos":      videos,
        "has_more":    False,
        "next_cursor": 0,
        "pagination_blocked": False,
        "fetched_count": len(videos),
    }


def download_video(
    url: str,
    out_dir: str,
    filename_tmpl: str = "%(title).80s [%(id)s].%(ext)s",
    cookiefile: Optional[str] = None,
    proxy: Optional[str] = None,
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Tải 1 video bất kỳ qua yt-dlp. Trả {ok, file, title} hoặc {ok:False,error}.

    Cách làm tham khảo từ Uploadvideo: format 'bestvideo+bestaudio → mp4'.
    """
    yt_dlp = _import_ytdlp()
    os.makedirs(out_dir, exist_ok=True)

    ydl_opts: Dict[str, Any] = {
        "outtmpl": os.path.join(out_dir, filename_tmpl),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": False,
    }
    if cookiefile and os.path.exists(cookiefile):
        ydl_opts["cookiefile"] = cookiefile
    else:
        ydl_opts.update(cookie_opts_for(detect_platform(url)))
    if proxy:
        ydl_opts["proxy"] = proxy
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # sau merge, đuôi có thể đổi thành .mp4
            base, _ = os.path.splitext(filename)
            mp4 = base + ".mp4"
            final = mp4 if os.path.exists(mp4) else filename
        return {
            "ok": True,
            "file": final,
            "title": info.get("title") or "",
            "id": str(info.get("id") or ""),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ── Facebook reels/video scraping qua Playwright ─────────────────────────────
def _is_fb_listing(url: str) -> bool:
    """True nếu là URL trang reels/video của 1 tài khoản (cần cuộn để liệt kê),
    False nếu là link 1 reel/video cụ thể (yt-dlp xử lý được)."""
    low = (url or "").lower()
    # link video/reel cụ thể → không phải listing
    if _re.search(r"/reel/\d+", low) or _re.search(r"/videos/\d+", low) \
            or "watch?v=" in low or "/watch/?v=" in low or "story_fbid=" in low:
        return False
    # còn lại (trang reels, tab videos, trang cá nhân) coi là listing
    return True


def _fb_reel_id(href: str) -> str:
    m = _re.search(r"/reel/(\d+)", href or "")
    if m:
        return m.group(1)
    m = _re.search(r"/videos/(\d+)", href or "")
    if m:
        return m.group(1)
    m = _re.search(r"[?&]v=(\d+)", href or "")
    if m:
        return m.group(1)
    return ""


def fetch_facebook_reels(
    url: str,
    max_videos: int = 0,
    headless: bool = True,
    max_scrolls: int = 60,
    idle_rounds: int = 5,
    wait_timeout: int = 45,
    user_data_dir: str = ".facebook_profile",
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """Mở trang reels/video Facebook bằng Chromium, cuộn để nạp thêm rồi thu
    thập link reel + thumbnail. Trả dict cùng schema với fetch_profile.

    Ghi chú:
    - Dùng persistent context tại `.facebook_profile` để bạn có thể ĐĂNG NHẬP
      1 lần (chạy headless=False), sau đó các lần sau dùng lại session.
    - Nội dung công khai thường xem được không cần đăng nhập; trang riêng tư
      hoặc bị chặn khu vực có thể cần đăng nhập.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"error": "Playwright chưa được cài. Chạy: pip install playwright && playwright install chromium"}

    reels: Dict[str, Dict[str, str]] = {}
    nickname = ""
    avatar = ""

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    launch_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=headless,
                args=launch_args,
                user_agent=ua,
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
                proxy={"server": proxy} if proxy else None,
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout * 1000)
            except Exception:
                pass
            page.wait_for_timeout(2500)

            # Đóng popup cookie/đăng nhập nếu có (best-effort)
            for sel in (
                '[aria-label="Đóng"]', '[aria-label="Close"]',
                '[aria-label="Cho phép tất cả cookie"]',
                '[aria-label="Allow all cookies"]',
                'div[role="button"]:has-text("Để sau")',
            ):
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(timeout=1500)
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            # Tên & avatar (best-effort)
            try:
                nickname = (page.title() or "").split("|")[0].strip()
            except Exception:
                nickname = ""

            js_collect = """
            () => Array.from(document.querySelectorAll('a[href*="/reel/"], a[href*="/videos/"]'))
                .map(a => {
                    const img = a.querySelector('img');
                    return {
                        href: a.href,
                        img: img ? (img.src || '') : '',
                        text: (a.getAttribute('aria-label') || a.innerText || '').slice(0, 100)
                    };
                });
            """

            prev = -1
            idle = 0
            for _ in range(max_scrolls):
                try:
                    items = page.evaluate(js_collect) or []
                except Exception:
                    items = []
                for it in items:
                    rid = _fb_reel_id(it.get("href") or "")
                    if not rid:
                        continue
                    if rid not in reels:
                        reels[rid] = {
                            "url": f"https://www.facebook.com/reel/{rid}",
                            "cover": it.get("img") or "",
                            "desc": (it.get("text") or "").strip(),
                        }
                    else:
                        # bổ sung cover/desc nếu lần trước rỗng
                        if not reels[rid]["cover"] and it.get("img"):
                            reels[rid]["cover"] = it["img"]
                        if not reels[rid]["desc"] and it.get("text"):
                            reels[rid]["desc"] = it["text"].strip()

                if max_videos and len(reels) >= max_videos:
                    break

                if len(reels) == prev:
                    idle += 1
                else:
                    idle = 0
                prev = len(reels)
                if idle >= idle_rounds:
                    break

                try:
                    page.mouse.wheel(0, 4000)
                except Exception:
                    pass
                page.wait_for_timeout(1600)

            try:
                ctx.close()
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Facebook browser lỗi: {exc}"}

    if not reels:
        return {"error": ("Không thu thập được reel nào. Trang có thể yêu cầu "
                          "đăng nhập — chạy lại với headless=False để đăng nhập "
                          "1 lần vào hồ sơ .facebook_profile, hoặc dán link 1 reel cụ thể.")}

    items = list(reels.items())
    if max_videos and max_videos > 0:
        items = items[:max_videos]

    videos: List[Dict[str, Any]] = []
    for rid, meta in items:
        videos.append({
            "aweme_id": rid,
            "url":      meta["url"],
            "desc":     meta["desc"] or f"Reel {rid}",
            "cover":    meta["cover"],
            "date":     "",
            "ts":       0,
            "play":     0,
            "like":     0,
            "comment":  0,
            "type":     "video",
            "duration": 0,
        })

    return {
        "platform":    "facebook",
        "nickname":    nickname or "Facebook",
        "uid":         "",
        "sec_uid":     "",
        "signature":   "",
        "avatar":      avatar,
        "follower":    0,
        "following":   0,
        "aweme_count": len(videos),
        "videos":      videos,
        "has_more":    False,
        "next_cursor": 0,
        "pagination_blocked": False,
        "fetched_count": len(videos),
    }


# ── Streaming: phát video dần khi lấy được (NDJSON) ──────────────────────────
def stream_profile(
    url: str,
    max_videos: int = 0,
    cookiefile: Optional[str] = None,
    proxy: Optional[str] = None,
    browser_opts: Optional[Dict[str, Any]] = None,
    batch_size: int = 6,
):
    """Generator phát dữ liệu profile theo từng phần thay vì đợi tải hết:
      {"kind":"profile", ...}         → thông tin user (phát trước)
      {"kind":"videos","videos":[..]} → từng lô video (phát dần)
      {"kind":"done","total":N}
      {"kind":"error","message":...}
    """
    platform = detect_platform(url)

    # Facebook listing → cuộn trình duyệt, phát dần từng reel
    if platform == "facebook" and _is_fb_listing(url):
        bo = browser_opts or {}
        cfg = _load_config()
        fb_profile = cfg.get("facebook_profile") or ".facebook_profile"
        yield from stream_facebook_reels(
            url,
            max_videos=max_videos,
            proxy=proxy,
            headless=bool(bo.get("headless", True)),
            max_scrolls=int(bo.get("max_scrolls", 60) or 60),
            idle_rounds=int(bo.get("idle_rounds", 5) or 5),
            wait_timeout=int(bo.get("wait_timeout_seconds", 45) or 45),
            batch_size=batch_size,
            user_data_dir=fb_profile,
        )
        return

    yt_dlp = _import_ytdlp()
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "lazy_playlist": True,          # cho phép lặp entries kiểu generator
        "ignoreerrors": "only_download",
    }
    if max_videos and max_videos > 0:
        ydl_opts["playlistend"] = int(max_videos)
    if cookiefile and os.path.exists(cookiefile):
        ydl_opts["cookiefile"] = cookiefile
    if proxy:
        ydl_opts["proxy"] = proxy

    class _ErrLogger:
        def __init__(self):
            self.errors: List[str] = []
        def debug(self, m):   pass
        def info(self, m):    pass
        def warning(self, m): pass
        def error(self, m):
            if m:
                self.errors.append(str(m))

    err_logger = _ErrLogger()
    ydl_opts["logger"] = err_logger

    info = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # process=False → entries trả về dạng generator, lặp tới đâu lấy tới đó
            info = ydl.extract_info(url, download=False, process=False)

            if not info:
                raw = err_logger.errors[0] if err_logger.errors else ""
                yield {"kind": "error", "message": _friendly_error(raw, platform, url)}
                return

            nickname = (info.get("title") or info.get("uploader")
                        or info.get("channel") or "")
            avatar = ""
            for th in reversed(info.get("thumbnails") or []):
                if th.get("url"):
                    avatar = th["url"]
                    break

            yield {
                "kind": "profile",
                "platform": platform,
                "nickname": nickname,
                "uid": str(info.get("uploader_id") or info.get("channel_id") or ""),
                "sec_uid": str(info.get("channel_id") or info.get("uploader_id") or ""),
                "signature": (info.get("description") or "")[:200],
                "avatar": avatar,
                "follower": info.get("channel_follower_count") or 0,
                "following": 0,
                "aweme_count": info.get("playlist_count") or 0,
            }

            entries = info.get("entries")
            if entries is None:
                entries = [info]

            batch: List[Dict[str, Any]] = []
            total = 0
            for e in entries:
                if not e:
                    continue
                # bỏ qua entry là playlist con (không phải video)
                etype = e.get("_type")
                if etype in ("playlist", "multi_video"):
                    continue
                vid = _entry_to_video(e)
                if not vid.get("aweme_id"):
                    continue
                batch.append(vid)
                total += 1
                if len(batch) >= batch_size:
                    yield {"kind": "videos", "videos": batch}
                    batch = []
                if max_videos and total >= max_videos:
                    break
            if batch:
                yield {"kind": "videos", "videos": batch}

            yield {"kind": "done", "total": total}
    except Exception as exc:  # noqa: BLE001
        msg = err_logger.errors[0] if err_logger.errors else str(exc)
        yield {"kind": "error", "message": _friendly_error(msg, platform, url)}


def stream_facebook_reels(
    url: str,
    max_videos: int = 0,
    headless: bool = True,
    max_scrolls: int = 60,
    idle_rounds: int = 5,
    wait_timeout: int = 45,
    user_data_dir: str = ".facebook_profile",
    proxy: Optional[str] = None,
    batch_size: int = 6,
):
    """Bản streaming của fetch_facebook_reels: vừa cuộn vừa phát reel mới."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        yield {"kind": "error", "message": "Playwright chưa được cài. Chạy: pip install playwright && playwright install chromium"}
        return

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    launch_args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    seen: set = set()

    js_collect = """
    () => Array.from(document.querySelectorAll('a[href*="/reel/"], a[href*="/videos/"]'))
        .map(a => {
            const img = a.querySelector('img');
            return {
                href: a.href,
                img: img ? (img.src || '') : '',
                text: (a.getAttribute('aria-label') || a.innerText || '').slice(0, 100)
            };
        });
    """

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=headless,
                args=launch_args,
                user_agent=ua,
                viewport={"width": 1280, "height": 900},
                locale="vi-VN",
                proxy={"server": proxy} if proxy else None,
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout * 1000)
            except Exception:
                pass
            page.wait_for_timeout(2500)

            for sel in ('[aria-label="Đóng"]', '[aria-label="Close"]',
                        '[aria-label="Cho phép tất cả cookie"]',
                        '[aria-label="Allow all cookies"]'):
                try:
                    el = page.query_selector(sel)
                    if el:
                        el.click(timeout=1500)
                        page.wait_for_timeout(400)
                except Exception:
                    pass

            try:
                nickname = (page.title() or "").split("|")[0].strip() or "Facebook"
            except Exception:
                nickname = "Facebook"

            yield {"kind": "profile", "platform": "facebook", "nickname": nickname,
                   "uid": "", "sec_uid": "", "signature": "", "avatar": "",
                   "follower": 0, "following": 0, "aweme_count": 0}

            prev = -1
            idle = 0
            total = 0
            for _ in range(max_scrolls):
                try:
                    items = page.evaluate(js_collect) or []
                except Exception:
                    items = []

                batch: List[Dict[str, Any]] = []
                for it in items:
                    rid = _fb_reel_id(it.get("href") or "")
                    if not rid or rid in seen:
                        continue
                    seen.add(rid)
                    batch.append({
                        "aweme_id": rid,
                        "url": f"https://www.facebook.com/reel/{rid}",
                        "desc": (it.get("text") or "").strip() or f"Reel {rid}",
                        "cover": it.get("img") or "",
                        "date": "", "ts": 0, "play": 0, "like": 0, "comment": 0,
                        "type": "video", "duration": 0,
                    })
                    total += 1
                    if len(batch) >= batch_size:
                        yield {"kind": "videos", "videos": batch}
                        batch = []
                    if max_videos and total >= max_videos:
                        break
                if batch:
                    yield {"kind": "videos", "videos": batch}

                yield {"kind": "progress", "collected": len(seen)}

                if max_videos and total >= max_videos:
                    break
                if len(seen) == prev:
                    idle += 1
                else:
                    idle = 0
                prev = len(seen)
                if idle >= idle_rounds:
                    break
                try:
                    page.mouse.wheel(0, 4000)
                except Exception:
                    pass
                page.wait_for_timeout(1600)

            try:
                ctx.close()
            except Exception:
                pass

            if total == 0:
                yield {"kind": "error", "message": ("Không thu thập được reel nào. Trang có thể "
                       "yêu cầu đăng nhập — đặt browser_fallback.headless=false để đăng nhập 1 lần.")}
            else:
                yield {"kind": "done", "total": total}
    except Exception as exc:  # noqa: BLE001
        yield {"kind": "error", "message": f"Facebook browser lỗi: {exc}"}

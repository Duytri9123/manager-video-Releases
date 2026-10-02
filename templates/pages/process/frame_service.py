"""
templates.pages.process.frame_service
Video path resolution, frame extraction, timeline filmstrip, and URL thumbnail helpers.
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from core_app import ROOT
from core.video_processor import find_ffmpeg
from utils.ffprobe import probe_video

_PROBE_CACHE: Dict[str, Tuple[int, int, float]] = {}
_FRAME_CACHE: Dict[Tuple[str, int, float], Tuple[str, float]] = {}


def resolve_video_path(video_path_str: str) -> Optional[Path]:
    """Resolve a user-provided video path against workspace root and common folders."""
    if not video_path_str:
        return None
    raw = video_path_str.strip().strip('"').strip("'")
    if not raw:
        return None
    # 1. Try directly as Path
    vp = Path(raw).expanduser()
    if vp.exists():
        return vp
    # 2. Try relative to ROOT
    if not vp.is_absolute():
        p = ROOT / vp
        if p.exists():
            return p
    # 3. Clean up backslashes and duplicated ROOT paths
    clean_str = raw.replace("\\", "/").strip()
    for marker in ("Downloaded/", "temp_uploads/", "Process_video/"):
        if marker in clean_str:
            sub = clean_str[clean_str.index(marker):]
            p = ROOT / sub
            if p.exists():
                return p
            if marker == "Process_video/":
                p2 = ROOT / "Downloaded" / sub
                if p2.exists():
                    return p2
    return None


def get_video_duration(vp: Path) -> float:
    """Get video duration using process-level cache."""
    path_key = str(vp.resolve())
    if path_key in _PROBE_CACHE:
        return _PROBE_CACHE[path_key][2]
    try:
        w, h, duration = probe_video(vp)
        _PROBE_CACHE[path_key] = (w, h, duration)
        return duration
    except Exception:
        return 0.0


def extract_single_frame(video_path_str: str, timestamp: float = 0.0) -> Tuple[bool, str, float, str]:
    """Extract a single frame as base64 data-URL. Returns (ok, data_url_or_empty, duration, error_msg)."""
    vp = resolve_video_path(video_path_str)
    if not vp or not vp.exists():
        return False, "", 0.0, f"Video không tồn tại: {video_path_str}"
    cache_key = (str(vp.resolve()), vp.stat().st_mtime_ns, round(float(timestamp or 0.0), 2))
    cached = _FRAME_CACHE.get(cache_key)
    if cached:
        return True, cached[0], cached[1], ""

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "", 0.0, "FFmpeg không tìm thấy"

    duration = get_video_duration(vp)
    # A saved preview timestamp may belong to a previous/longer video. FFmpeg
    # returns no frame when seeking beyond EOF, so clamp it to this source.
    safe_timestamp = max(0.0, float(timestamp or 0.0))
    if duration > 0:
        safe_timestamp = min(safe_timestamp, max(0.0, duration - 0.05))

    try:
        with tempfile.TemporaryDirectory(prefix="vframe_") as tmpdir:
            tmp_jpg = Path(tmpdir) / "frame.jpg"
            # Keep enough source pixels for the editor.  The old 480px frame was
            # routinely displayed at 1000px+, which enlarged both the image and
            # every canvas-drawn label/selection handle and made them look soft.
            # Cap either dimension at 1920 without upscaling small source videos.
            preview_scale = (
                "scale=w='min(1920,iw)':h='min(1920,ih)':"
                "force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
            result = subprocess.run([
                ffmpeg, "-ss", str(safe_timestamp),
                "-i", str(vp),
                "-vframes", "1",
                "-q:v", "2",
                "-vf", preview_scale,
                "-strict", "-2",
                str(tmp_jpg), "-y", "-loglevel", "error"
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)

            if result.returncode != 0 or not tmp_jpg.exists() or tmp_jpg.stat().st_size == 0:
                tmp_video = Path(tmpdir) / f"input{vp.suffix}"
                try:
                    shutil.copy2(str(vp), str(tmp_video))
                    subprocess.run([
                        ffmpeg, "-ss", str(safe_timestamp),
                        "-i", str(tmp_video),
                        "-threads", "1",
                    "-vframes", "1",
                        "-q:v", "2",
                        "-vf", preview_scale,
                        "-strict", "-2",
                        str(tmp_jpg), "-y", "-loglevel", "error"
                    ], capture_output=True, timeout=30)
                except Exception:
                    pass

            # Some damaged/keyframe-sparse files cannot seek accurately at a
            # requested timestamp but can still decode from the beginning.
            if not tmp_jpg.exists() or tmp_jpg.stat().st_size == 0:
                try:
                    subprocess.run([
                        ffmpeg, "-ss", "0",
                        "-i", str(vp),
                        "-vframes", "1",
                        "-q:v", "2",
                        "-vf", preview_scale,
                        "-strict", "-2",
                        str(tmp_jpg), "-y", "-loglevel", "error"
                    ], capture_output=True, timeout=30)
                except Exception:
                    pass

            if not tmp_jpg.exists() or tmp_jpg.stat().st_size == 0:
                err_msg = (result.stderr or "").strip()[:200] if result else ""
                return False, "", duration, f"Không thể extract frame. {err_msg}"

            with open(tmp_jpg, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

        result_url = f"data:image/jpeg;base64,{img_b64}"
        _FRAME_CACHE[cache_key] = (result_url, duration)
        if len(_FRAME_CACHE) > 32:
            _FRAME_CACHE.pop(next(iter(_FRAME_CACHE)))
        return True, result_url, duration, ""
    except subprocess.TimeoutExpired:
        return False, "", duration, "Timeout khi extract frame (>30s)"
    except Exception as e:
        return False, "", duration, str(e)


def extract_filmstrip(video_path_str: str, count: int = 12) -> Tuple[bool, List[str], float, str]:
    """Extract N evenly-spaced thumbnails from video. Returns (ok, frame_urls, duration, error_msg)."""
    count = max(4, min(40, count))
    vp = resolve_video_path(video_path_str)
    if not vp or not vp.exists():
        return False, [], 0.0, f"Video không tồn tại: {video_path_str}"

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, [], 0.0, "FFmpeg không tìm thấy"

    duration = get_video_duration(vp)
    if duration <= 0.0:
        return False, [], 0.0, "Không đo được thời lượng video"

    step = duration / (count + 1)
    timestamps = [round((i + 1) * step, 3) for i in range(count)]

    try:
        with tempfile.TemporaryDirectory(prefix="vfilmstrip_") as tmpdir:
            tmpdir_p = Path(tmpdir)
            frames = []

            def extract_one(item):
                idx, ts = item
                out_jpg = tmpdir_p / f"thumb_{idx:03d}.jpg"
                cmd = [
                    ffmpeg,
                    "-ss", str(ts),
                    "-i", str(vp),
                    "-vframes", "1",
                    "-q:v", "5",
                    "-vf", "scale=160:-1",
                    "-strict", "-2",
                    str(out_jpg),
                    "-y",
                    "-loglevel", "error",
                ]
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=15,
                    errors="replace",
                )
                if out_jpg.exists() and out_jpg.stat().st_size > 0:
                    with open(out_jpg, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    return f"data:image/jpeg;base64,{b64}"
                else:
                    return ""

            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=3) as pool:
                frames = list(pool.map(extract_one, enumerate(timestamps)))
            if not any(frames):
                return False, [], duration, "Không trích được khung hình"
            return True, frames, duration, ""
    except subprocess.TimeoutExpired:
        return False, [], duration, "Timeout khi tạo filmstrip (>60s)"
    except Exception as e:
        return False, [], duration, str(e)


def pick_url(raw: str) -> str:
    """Extract URL from raw text if surrounded by other characters."""
    m = re.search(r"https?://[^\s\"']+", raw)
    return m.group(0) if m else raw.strip()


def extract_aweme_id(u: str, parsed: Optional[Dict[str, Any]]) -> str:
    """Extract aweme ID from URL string or parsed dict."""
    if parsed and parsed.get("aweme_id"):
        return str(parsed["aweme_id"])
    m = re.search(r"/video/(\d+)", u)
    if m:
        return m.group(1)
    m2 = re.search(r"/note/(\d+)", u)
    if m2:
        return m2.group(1)
    return ""


def fetch_thumbnail_from_url(url: str) -> Optional[Dict[str, Any]]:
    """Fetch video metadata/cover via Douyin API without downloading video."""
    from auth import CookieManager
    from config import ConfigLoader
    from core import DouyinAPIClient, URLParser
    from core.proxy_resolver import resolve_proxy
    from core_app import CONFIG_FILE, get_cookies_with_fallback, _extract_cover
    import asyncio

    clean_url = pick_url(url)
    parsed = URLParser.parse(clean_url)
    aweme_id = extract_aweme_id(clean_url, parsed)
    if not aweme_id:
        return None

    cfg = ConfigLoader(str(CONFIG_FILE))
    cm = CookieManager()
    cm.set_cookies(get_cookies_with_fallback())

    async def _fetch():
        async with DouyinAPIClient(cm.get_cookies(), proxy=resolve_proxy(cfg)) as client:
            return await client.get_video_detail(aweme_id)

    try:
        data = asyncio.run(_fetch())
        if not data:
            return None
        aweme = data.get("aweme_detail") or data.get("item_list", [{}])[0] if data else {}
        if not aweme:
            return None
        cover_url = _extract_cover(aweme)
        desc = (aweme.get("desc") or "")[:80]
        res: Dict[str, Any] = {
            "cover_url": cover_url,
            "desc": desc,
            "video_name": desc,
            "aweme_id": aweme_id,
            "source": "thumbnail",
        }

        if cover_url:
            try:
                import httpx
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    resp = client.get(cover_url)
                    if resp.status_code == 200 and len(resp.content) > 0:
                        ct = (resp.headers.get("content-type") or "image/jpeg").lower()
                        if "webp" in ct:
                            mime = "image/webp"
                        elif "png" in ct:
                            mime = "image/png"
                        else:
                            mime = "image/jpeg"
                        img_b64 = base64.b64encode(resp.content).decode("ascii")
                        res["image"] = f"data:{mime};base64,{img_b64}"
            except Exception:
                pass

        return res
    except Exception:
        return None

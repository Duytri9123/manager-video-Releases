#!/usr/bin/env python3
"""
core.processor.ffmpeg_base
FFmpeg binary discovery, process execution, duration utilities, long path support,
and type/color coercion helpers.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from functools import lru_cache

# ── ffmpeg helper ─────────────────────────────────────────────────────────────
def find_ffmpeg() -> Optional[str]:
    from utils.ffprobe import find_ffmpeg as utils_find_ffmpeg
    return utils_find_ffmpeg()


# Subprocess and cancellation registry
_active_subprocesses = set()
_active_subprocesses_lock = None
_cancel_checkers = []

def register_cancel_checker(fn):
    if fn not in _cancel_checkers:
        _cancel_checkers.append(fn)

def is_proc_cancelled() -> bool:
    for fn in _cancel_checkers:
        try:
            if fn():
                return True
        except Exception:
            pass
    return False

def register_subprocess(proc):
    global _active_subprocesses, _active_subprocesses_lock
    if _active_subprocesses_lock is None:
        import threading
        _active_subprocesses_lock = threading.Lock()
    with _active_subprocesses_lock:
        _active_subprocesses.add(proc)

def unregister_subprocess(proc):
    global _active_subprocesses, _active_subprocesses_lock
    if _active_subprocesses_lock:
        with _active_subprocesses_lock:
            _active_subprocesses.discard(proc)

def kill_active_subprocesses():
    global _active_subprocesses, _active_subprocesses_lock
    if _active_subprocesses_lock:
        with _active_subprocesses_lock:
            procs = list(_active_subprocesses)
            _active_subprocesses.clear()
            for p in procs:
                try:
                    p.kill()
                except Exception:
                    pass

def run_ffmpeg(args: list, desc: str = "", timeout: int = 600) -> tuple[bool, str]:
    """Run ffmpeg command with non-blocking eventlet polling, return (success, stderr)."""
    try:
        import eventlet
        _sleep = eventlet.sleep
    except Exception:
        import time
        _sleep = time.sleep

    try:
        import time as _t
        start_t = _t.time()
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        register_subprocess(proc)
        try:
            while proc.poll() is None:
                if is_proc_cancelled():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return False, "Tiến trình bị hủy bởi người dùng"
                if _t.time() - start_t > timeout:
                    proc.kill()
                    return False, f"FFmpeg timeout sau {timeout}s — video quá dài hoặc filter quá nặng"
                _sleep(0.05)
            stdout, stderr = proc.communicate()
            return proc.returncode == 0, (stderr or "").strip()
        finally:
            unregister_subprocess(proc)
    except Exception as e:
        return False, str(e)


def _get_encoding_args(ffmpeg: Optional[str] = None) -> list[str]:
    """Get hardware-optimized encoding args. Falls back to libx264 veryfast crf 23."""
    try:
        from core.hardware_presets import get_optimal_preset
        preset = get_optimal_preset(ffmpeg)
        return preset.build_output_args()
    except Exception:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k"]


@lru_cache(maxsize=4)
def get_burn_encoder(ffmpeg: str, mode: str = "auto"):
    """Prefer a working NVENC runtime, including the bundled older runtime."""
    cpu_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k"]
    if mode == "cpu":
        return ffmpeg, cpu_args
    if mode == "nvidia":
        from core.hardware_presets import _test_encoder
        if _test_encoder(ffmpeg, "h264_nvenc"):
            return ffmpeg, ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
                            "-cq", "23", "-b:v", "0", "-c:a", "aac", "-b:a", "128k"]
        if _test_encoder(ffmpeg, "h264_mf"):
            return ffmpeg, ["-c:v", "h264_mf", "-b:v", "6M", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "128k"]
        args = cpu_args
    else:
        args = _get_encoding_args(ffmpeg)
    if "libx264" not in args:
        return ffmpeg, args
    try:
        import imageio_ffmpeg
        from core.hardware_presets import _test_encoder
        alternate = imageio_ffmpeg.get_ffmpeg_exe()
        if alternate != ffmpeg and _test_encoder(alternate, "h264_nvenc"):
            filters = subprocess.run([alternate, "-filters"], capture_output=True,
                                     text=True, timeout=10)
            if re.search(r"\bass\s+V->V", filters.stdout or ""):
                return alternate, ["-c:v", "h264_nvenc", "-preset", "p4",
                                   "-rc", "vbr", "-cq", "23", "-b:v", "0",
                                   "-c:a", "aac", "-b:a", "128k"]
    except Exception:
        pass
    if mode == "nvidia":
        from core.hardware_presets import _test_encoder
        if _test_encoder(ffmpeg, "h264_mf"):
            return ffmpeg, ["-c:v", "h264_mf", "-b:v", "6M", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "128k"]
        raise RuntimeError("GPU NVIDIA không khả dụng với FFmpeg/driver hiện tại. Chọn Tự động hoặc CPU.")
    return ffmpeg, args


def get_media_duration_seconds(ffmpeg: str, media_path: Path) -> float:
    """Read container metadata without decoding the entire media file."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(media_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        for line in (r.stderr or "").splitlines():
            m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", line)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _safe_stem(stem: str) -> str:
    """Chuẩn hoá tên file/folder cho output:
    - Bỏ dấu tiếng Việt (NFD + ASCII fallback) để tránh Unicode dài + giảm risk
      Windows MAX_PATH (260). Đặc biệt 'đ' → 'd', 'Đ' → 'D'.
    - Bỏ ký tự đặc biệt không hợp lệ trong tên file.
    - Giới hạn 60 ký tự để pipeline (folder + file + suffix) không vượt MAX_PATH.
    """
    import unicodedata

    raw = (stem or "").replace("\n", " ").replace("\r", " ")
    # Đặc biệt cho tiếng Việt: đ/Đ không tách bằng NFD
    raw = raw.replace("đ", "d").replace("Đ", "D")
    # Tách dấu rồi loại bỏ combining marks
    nfkd = unicodedata.normalize("NFD", raw)
    ascii_str = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Loại ký tự không hợp lệ cho tên file (Windows + Unix)
    ascii_str = re.sub(r'[<>:"/\\|?*#!]', "_", ascii_str)
    # Giữ chữ-số-_-.- và space; mọi thứ khác thành "_"
    ascii_str = re.sub(r"[^\w.\- ]", "_", ascii_str, flags=re.ASCII)
    ascii_str = re.sub(r"[\s_]+", "_", ascii_str).strip("_ ")
    return ascii_str[:60] or "video"


def _winlong(p) -> str:
    """Convert path to Windows long-path form (\\\\?\\C:\\...) when needed.
    Trên non-Windows hoặc path ngắn → trả str(p) như cũ.
    Cần thiết khi path > 260 ký tự để open()/write_text() không lỗi Errno 2."""
    import os as _os
    s = str(p)
    if _os.name != "nt":
        return s
    if s.startswith("\\\\?\\"):
        return s
    # Chỉ áp dụng cho absolute path
    try:
        abspath = _os.path.abspath(s)
    except Exception:
        return s
    if len(abspath) < 200:
        return s  # path ngắn, không cần long-prefix
    # UNC path: \\server\share → \\?\UNC\server\share
    if abspath.startswith("\\\\"):
        return "\\\\?\\UNC\\" + abspath[2:]
    return "\\\\?\\" + abspath


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "y", "on"}:
        return True
    if txt in {"0", "false", "no", "n", "off", ""}:
        return False
    return default


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp_float(value: float, low: float, high: float) -> float:
    try:
        v = float(value)
    except Exception:
        v = low
    return max(low, min(high, v))


def _normalize_hex_rgb(value: str, default: str = "#000000") -> str:
    txt = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", txt):
        return txt.upper()
    if re.fullmatch(r"[0-9a-fA-F]{6}", txt):
        return ("#" + txt).upper()
    return default


def _ffmpeg_color(hex_color: str, opacity: float = 1.0) -> str:
    rgb = _normalize_hex_rgb(hex_color, "#000000").lstrip("#")
    alpha = _clamp_float(opacity, 0.0, 1.0)
    return f"0x{rgb}@{alpha:.3f}"


def _escape_drawtext_text(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("%", "\\%")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _fmt_hms(seconds: float) -> str:
    total = max(0.0, float(seconds))
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:05.2f}"


def has_audio_track(video_path: Path, ffmpeg: str) -> bool:
    """Check if video has at least one audio stream."""
    try:
        video_path = Path(video_path)
        r = subprocess.run(
            [ffmpeg, "-i", str(video_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        stderr = r.stderr or ""
        # Look for "Audio: " in ffmpeg output
        return "Audio:" in stderr
    except Exception:
        return False


# ── Image path helper ─────────────────────────────────────────────────────────
_SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _resolve_image_path(image_path: str, project_root: Path) -> Optional[Path]:
    """
    Resolve đường dẫn ảnh (tuyệt đối hoặc tương đối so với project root).
    Kiểm tra định dạng hợp lệ (PNG, JPG, JPEG, WEBP).
    Returns None nếu không hợp lệ.
    """
    if not image_path:
        return None
    p = Path(image_path)
    if not p.is_absolute():
        p = project_root / p
    if not p.exists():
        return None
    if p.suffix.lower() not in _SUPPORTED_IMAGE_EXTS:
        return None
    return p


# ── Anti-fingerprint filter builder ──────────────────────────────────────────
_LOGO_POSITION_MAP = {
    "top-left":     ("{P}", "{P}"),
    "top-right":    ("W-w-{P}", "{P}"),
    "bottom-left":  ("{P}", "H-h-{P}"),
    "bottom-right": ("W-w-{P}", "H-h-{P}"),
}


def _get_media_duration(file_path: Path, ffmpeg_bin: str = "ffmpeg") -> float:
    """Get media duration in seconds via ffmpeg."""
    import subprocess, re
    try:
        cmd = [ffmpeg_bin, "-i", str(file_path)]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=15)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", res.stderr or "")
        if m:
            h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return h * 3600.0 + mi * 60.0 + s
    except Exception:
        pass
    return 0.0



def _run_ffmpeg(args: list, desc: str = "") -> tuple[bool, str]:
    """Alias for run_ffmpeg — run an ffmpeg command, return (success, stderr)."""
    return run_ffmpeg(args, desc)


# ══════════════════════════════════════════════════════════════════════════════
# GroqWhisperTranscriber  (default — cloud API, much faster than local CPU)
# ══════════════════════════════════════════════════════════════════════════════

def _get_audio_duration(ffmpeg: str, path: Path) -> float:
    """Return duration of an audio file in seconds."""
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True
        )
        for line in r.stderr.splitlines():
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


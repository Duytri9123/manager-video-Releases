"""
ffprobe / ffmpeg helpers — gộp các implementation đang lặp ở:
  - tools/youtube_uploader.py._probe_duration
  - routes/facebook.py._probe_video_dims
  - core/video_processor.py (parse `ffmpeg -i` output)

Tất cả hàm trả về giá trị mặc định an toàn (0/0/0.0) nếu không probe được,
để caller không cần wrap try/except riêng.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple


def _which(name: str) -> Optional[str]:
    """Find an executable, trying both unix and Windows .exe variants."""
    return shutil.which(name) or shutil.which(name + ".exe")


def find_ffprobe() -> Optional[str]:
    """Locate ffprobe binary on PATH. Returns absolute path or None."""
    return _which("ffprobe")


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary on PATH. Returns absolute path or None."""
    return _which("ffmpeg")


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)")
_DIM_RE = re.compile(r"(\d{2,5})x(\d{2,5})")


def _parse_ffmpeg_stderr(stderr: str) -> Tuple[int, int, float]:
    """Pull (width, height, duration_sec) out of `ffmpeg -i` stderr output."""
    if not stderr:
        return 0, 0, 0.0
    m_dim = _DIM_RE.search(stderr)
    w, h = (int(m_dim.group(1)), int(m_dim.group(2))) if m_dim else (0, 0)
    m_dur = _DUR_RE.search(stderr)
    dur = 0.0
    if m_dur:
        dur = (
            int(m_dur.group(1)) * 3600
            + int(m_dur.group(2)) * 60
            + int(m_dur.group(3))
            + int(m_dur.group(4)) / 100
        )
    return w, h, dur


def probe_video(path: str | Path, timeout: int = 20) -> Tuple[int, int, float]:
    """Return (width, height, duration_sec) for a video file.

    Tries ffprobe first (faster, structured JSON), then falls back to
    ``ffmpeg -i`` stderr parsing. Returns (0, 0, 0.0) if both fail.
    """
    path = Path(path)
    if not path.exists():
        return 0, 0, 0.0

    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            out = subprocess.check_output(
                [
                    ffprobe, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height:format=duration",
                    "-of", "json",
                    str(path),
                ],
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            data = json.loads(out.decode("utf-8", errors="ignore"))
            stream = (data.get("streams") or [{}])[0]
            w = int(stream.get("width") or 0)
            h = int(stream.get("height") or 0)
            dur = float((data.get("format") or {}).get("duration") or 0)
            if w or h or dur:
                return w, h, dur
        except Exception:
            pass

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return 0, 0, 0.0
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(path)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        return _parse_ffmpeg_stderr(r.stderr or "")
    except Exception:
        return 0, 0, 0.0


def probe_duration(path: str | Path, timeout: int = 20) -> float:
    """Return video/audio duration in seconds. 0.0 if unknown."""
    return probe_video(path, timeout=timeout)[2]


def probe_dims(path: str | Path, timeout: int = 20) -> Tuple[int, int]:
    """Return (width, height) of the first video stream. (0, 0) if unknown."""
    w, h, _ = probe_video(path, timeout=timeout)
    return w, h

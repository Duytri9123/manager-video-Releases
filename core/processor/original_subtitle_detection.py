"""Find when burned-in subtitles are visible in the user-selected mask area."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

from core.processor.ffmpeg_base import run_ffmpeg


def _visible_intervals(samples: list[bool], sample_rate: float, duration: float,
                       padding_seconds: float = 0.2) -> list[dict]:
    """Turn OCR observations into a compact visual mask timeline."""
    intervals: list[list[float]] = []
    half = 0.5 / sample_rate
    for index, visible in enumerate(samples):
        if not visible:
            continue
        center = index / sample_rate
        start = max(0.0, center - half - padding_seconds)
        end = min(duration, center + half + padding_seconds)
        if intervals and start - intervals[-1][1] <= 0.5:
            intervals[-1][1] = max(intervals[-1][1], end)
        else:
            intervals.append([start, end])
    return [{"start": round(start, 3), "end": round(end, 3), "text": "visible"}
            for start, end in intervals if end > start]


def detect_original_subtitle_intervals(
    video_path: Path, ffmpeg: str, duration: float, *,
    width_pct: float = 0.8, height_pct: float = 0.15,
    x_pct: float | None = None, y_pct: float | None = None,
    lift_pct: float = 0.06, sample_rate: float = 2.0,
    padding_seconds: float = 0.2,
) -> dict:
    """OCR video frames in the source subtitle area; return visible time spans.

    No transcript, translation, or ASS timing is used here. The returned text
    field only marks visual presence for the existing FFmpeg mask scheduler.
    """
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Không đọc được thời lượng video để dò phụ đề gốc")
    width = max(0.1, min(1.0, float(width_pct)))
    height = max(0.03, min(0.45, float(height_pct)))
    center_x = 0.5 if x_pct is None else max(0.0, min(1.0, float(x_pct)))
    center_y = 1.0 - height / 2 - lift_pct if y_pct is None else max(0.0, min(1.0, float(y_pct)))
    left = max(0.0, min(1.0 - width, center_x - width / 2))
    top = max(0.0, min(1.0 - height, center_y - height / 2))
    search_top = max(0.0, top - 0.08)
    search_bottom = min(1.0, top + height + 0.08)

    with tempfile.TemporaryDirectory(prefix="original_sub_ocr_") as folder:
        pattern = str(Path(folder) / "frame_%06d.jpg")
        ok, error = run_ffmpeg([
            ffmpeg, "-i", str(video_path), "-vf", f"fps={sample_rate},scale=960:-2",
            "-q:v", "5", pattern, "-y", "-loglevel", "error",
        ])
        if not ok:
            raise RuntimeError(f"Không lấy được khung hình để dò phụ đề gốc: {error}")
        frames = sorted(Path(folder).glob("frame_*.jpg"))
        if not frames:
            raise RuntimeError("Video không có khung hình để dò phụ đề gốc")
        ocr = RapidOCR()
        observations: list[bool] = []
        text_centers: list[float] = []
        for frame in frames:
            with Image.open(frame) as image:
                w, h = image.size
                box = (int(left * w), int(search_top * h),
                       max(1, int((left + width) * w)),
                       max(1, int(search_bottom * h)))
                cropped = np.asarray(image.crop(box).convert("RGB"))
            lines, _ = ocr(cropped)
            visible = False
            for line in lines or []:
                try:
                    points, text, score = line
                    text = str(text or "").strip()
                    span = max(point[0] for point in points) - min(point[0] for point in points)
                    if (float(score) >= 0.55 and
                            sum(char.isalnum() for char in text) >= 2 and
                            span >= cropped.shape[1] * 0.06):
                        visible = True
                        center = (min(point[1] for point in points) + max(point[1] for point in points)) / 2
                        text_centers.append((box[1] + center) / h)
                        break
                except (TypeError, ValueError, IndexError):
                    continue
            observations.append(visible)
        text_centers.sort()
        suggested_y = text_centers[len(text_centers) // 2] if text_centers else None
        return {"segments": _visible_intervals(observations, sample_rate, duration, padding_seconds),
                "suggested_y_pct": suggested_y}

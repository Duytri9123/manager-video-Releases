"""Animation pipeline — sequence of pose-segments → frames → MP4."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .renderer import draw_frame, interpolate_pose
from .skeleton import get_pose

# Lazily import ffmpeg locator from project utilities.
try:
    from utils.ffprobe import find_ffmpeg as _find_ffmpeg
except Exception:  # noqa: BLE001
    def _find_ffmpeg() -> Optional[str]:
        return shutil.which("ffmpeg")


# ── Easing helpers ─────────────────────────────────────────────────────────
def _ease_in_out(t: float) -> float:
    """Smoothstep — gentle accel/decel."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return t * t * (3 - 2 * t)


# ── Public types ───────────────────────────────────────────────────────────
@dataclass
class Scene:
    """One animation segment: morph from one pose to the next over `duration`.

    `pose_from` is taken from the previous scene's `pose_to` if omitted (so
    you can describe an animation as a list of target poses + durations).
    """
    pose_to: str
    duration: float = 1.0          # seconds
    caption: str = ""
    pose_from: Optional[str] = None
    easing: str = "ease"           # "ease" | "linear"
    hold: float = 0.0              # extra hold (sec) at the final pose


@dataclass
class RenderResult:
    output_path: Path
    duration: float
    frame_count: int
    fps: int
    width: int
    height: int
    log: List[str] = field(default_factory=list)


# ── Main render function ───────────────────────────────────────────────────
def render_video(
    scenes: List[Scene],
    output_path: Path,
    *,
    size: Tuple[int, int] = (1080, 1920),
    fps: int = 24,
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    audio_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> RenderResult:
    """Render `scenes` to an MP4 file at `output_path`.

    progress_cb(done_frames, total_frames, label) is called on each frame.
    """
    if not scenes:
        raise ValueError("Cần ít nhất 1 scene để render.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute frame count per scene & total frames.
    frames_per_scene: List[Tuple[int, int]] = []  # (transition, hold)
    total = 0
    for sc in scenes:
        n_trans = max(1, int(round(sc.duration * fps)))
        n_hold = max(0, int(round(sc.hold * fps)))
        frames_per_scene.append((n_trans, n_hold))
        total += n_trans + n_hold

    log: List[str] = []
    log.append(f"Tổng số frame: {total} ({fps} fps, kích thước {size[0]}x{size[1]}).")

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("Không tìm thấy ffmpeg trên hệ thống.")

    # Render frames into a temp dir → ffmpeg image2 muxer.
    with tempfile.TemporaryDirectory(prefix="stickman_") as tmpdir:
        tmp = Path(tmpdir)
        prev_pose_name = scenes[0].pose_from or scenes[0].pose_to
        idx = 0

        for sc_i, sc in enumerate(scenes):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Đã hủy render.")

            n_trans, n_hold = frames_per_scene[sc_i]
            pose_from_name = sc.pose_from or prev_pose_name
            pose_to_name = sc.pose_to
            pose_from = get_pose(pose_from_name)
            pose_to = get_pose(pose_to_name)

            log.append(
                f"Scene {sc_i + 1}: {pose_from_name} → {pose_to_name} "
                f"({sc.duration:.2f}s + hold {sc.hold:.2f}s)"
            )

            # Transition frames
            for k in range(n_trans):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Đã hủy render.")
                t = (k + 1) / n_trans
                if sc.easing == "ease":
                    t = _ease_in_out(t)
                pose = interpolate_pose(pose_from, pose_to, t)
                img = draw_frame(
                    pose,
                    size=size,
                    bg_color=bg_color,
                    line_color=line_color,
                    caption=sc.caption,
                )
                img.save(tmp / f"f_{idx:06d}.png", format="PNG")
                idx += 1
                if progress_cb is not None:
                    progress_cb(idx, total, f"Scene {sc_i + 1} · transition")

            # Hold frames (re-render last frame so caption stays)
            if n_hold > 0:
                hold_img = draw_frame(
                    pose_to,
                    size=size,
                    bg_color=bg_color,
                    line_color=line_color,
                    caption=sc.caption,
                )
                for _ in range(n_hold):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Đã hủy render.")
                    hold_img.save(tmp / f"f_{idx:06d}.png", format="PNG")
                    idx += 1
                    if progress_cb is not None:
                        progress_cb(idx, total, f"Scene {sc_i + 1} · hold")

            prev_pose_name = pose_to_name

        # ffmpeg encode
        if progress_cb is not None:
            progress_cb(total, total, "Đang encode MP4…")

        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", str(tmp / "f_%06d.png"),
        ]
        if audio_path is not None and Path(audio_path).exists():
            cmd += ["-i", str(audio_path)]
        cmd += [
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "20",
        ]
        if audio_path is not None and Path(audio_path).exists():
            cmd += [
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
            ]
        cmd += [str(output_path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"ffmpeg không thể chạy: {exc}") from exc

        if result.returncode != 0:
            tail = (result.stderr or "")[-800:]
            raise RuntimeError(f"ffmpeg thất bại (code={result.returncode}): {tail}")

        log.append(f"Đã ghi MP4: {output_path}")

    duration = total / float(fps)
    return RenderResult(
        output_path=output_path,
        duration=duration,
        frame_count=total,
        fps=fps,
        width=size[0],
        height=size[1],
        log=log,
    )

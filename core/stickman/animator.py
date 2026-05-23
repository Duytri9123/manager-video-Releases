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
from .renderer_v2 import draw_frame_v2
from .renderer_v3 import draw_frame_v3
from .skeleton import get_pose
from .scene_elements import (
    GRADIENT_PRESETS,
    draw_gradient_bg,
    draw_ground,
    draw_scene_objects,
    draw_speech_bubble,
    apply_transition,
)

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
    emotion: str = "neutral"       # facial expression
    character_style: str = "normal"
    props: Optional[List[str]] = None
    background_image: Optional[str] = None  # path to background PNG/JPG
    background_preset: str = "neutral"      # gradient preset name
    ground: str = "none"                    # flat|grass|floor|road|none
    scene_objects: Optional[List[str]] = None
    speech: str = ""                        # speech bubble text
    transition: str = "none"               # fade|slide_left|slide_up|zoom_in|none
    num_characters: int = 1                # 1-3 stickmen


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

        # Pre-load background images (cache per unique path)
        _bg_cache: dict = {}

        def _load_bg(bg_path_str: Optional[str]):
            if not bg_path_str:
                return None
            if bg_path_str in _bg_cache:
                return _bg_cache[bg_path_str]
            try:
                from PIL import Image as _Img
                p = Path(bg_path_str)
                if p.exists():
                    img_bg = _Img.open(p).convert("RGB")
                    _bg_cache[bg_path_str] = img_bg
                    return img_bg
            except Exception:  # noqa: BLE001
                pass
            _bg_cache[bg_path_str] = None
            return None

        def _build_background(sc) -> Optional['Image.Image']:
            """Build the full background for a scene: gradient + ground + objects."""
            from PIL import Image as _Img

            # Start with gradient preset or custom bg image
            bg_img = _load_bg(sc.background_image)
            if bg_img is not None:
                bg = bg_img.copy()
                if bg.size != size:
                    bg = bg.resize(size, _Img.LANCZOS)
            else:
                # Use gradient preset
                preset_name = getattr(sc, 'background_preset', 'neutral') or 'neutral'
                colors = GRADIENT_PRESETS.get(preset_name)
                if colors:
                    bg = draw_gradient_bg(size, colors)
                else:
                    bg = draw_gradient_bg(size, GRADIENT_PRESETS["neutral"])

            # Ground
            ground_style = getattr(sc, 'ground', 'none') or 'none'
            if ground_style != 'none':
                draw_ground(bg, style=ground_style)

            # Scene objects
            objects = getattr(sc, 'scene_objects', None) or []
            if objects:
                draw_scene_objects(bg, objects, line_color=line_color)

            return bg

        def _render_full_frame(sc, pose, prev_frame=None, trans_t=None):
            """Render a complete frame with all elements."""
            from PIL import Image as _Img

            # Build background
            bg = _build_background(sc)

            scene_props = sc.props or []
            n_chars = getattr(sc, 'num_characters', 1) or 1

            # Multi-character: place them side by side
            if n_chars == 1:
                img = draw_frame_v3(
                    pose,
                    size=size,
                    bg_color=bg_color,
                    line_color=line_color,
                    caption=sc.caption,
                    emotion=sc.emotion,
                    character_style=sc.character_style,
                    props=scene_props,
                    background_image=bg,
                )
            else:
                # Draw on background first, then add multiple stickmen
                img = bg if bg is not None else _Img.new("RGB", size, bg_color)
                spacing = size[0] // (n_chars + 1)
                for ci in range(n_chars):
                    anchor_x = spacing * (ci + 1)
                    anchor_y = int(size[1] * 0.68)
                    char_pose = pose
                    img = draw_frame_v3(
                        char_pose,
                        size=size,
                        bg_color=bg_color,
                        line_color=line_color,
                        caption="" if ci > 0 else sc.caption,
                        emotion=sc.emotion,
                        character_style=sc.character_style,
                        props=scene_props if ci == 0 else None,
                        background_image=img,
                        anchor=(anchor_x, anchor_y),
                    )

            # Speech bubble
            speech_text = getattr(sc, 'speech', '') or ''
            if speech_text:
                bubble_x = int(size[0] * 0.15)
                bubble_y = int(size[1] * 0.35)
                draw_speech_bubble(
                    img, speech_text,
                    position=(bubble_x, bubble_y),
                    font_size=max(20, int(28 * (size[0] / 1080))),
                    max_width=int(size[0] * 0.5),
                )

            # Transition effect
            transition = getattr(sc, 'transition', 'none') or 'none'
            if transition != 'none' and prev_frame is not None and trans_t is not None and trans_t < 1.0:
                img = apply_transition(prev_frame, img, trans_t, effect=transition)

            return img

        prev_scene_last_frame = None

        for sc_i, sc in enumerate(scenes):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Đã hủy render.")

            n_trans, n_hold = frames_per_scene[sc_i]
            pose_from_name = sc.pose_from or prev_pose_name
            pose_to_name = sc.pose_to
            pose_from = get_pose(pose_from_name)
            pose_to = get_pose(pose_to_name)

            bg_img = _load_bg(sc.background_image)
            scene_props = sc.props or []

            log.append(
                f"Scene {sc_i + 1}: {pose_from_name} → {pose_to_name} "
                f"({sc.duration:.2f}s + hold {sc.hold:.2f}s)"
                f" [emotion={sc.emotion}, style={sc.character_style}, bg={getattr(sc, 'background_preset', 'neutral')}]"
            )

            # Determine transition frames (first 20% of transition)
            transition = getattr(sc, 'transition', 'none') or 'none'
            trans_frames = int(n_trans * 0.2) if transition != 'none' else 0

            # Transition frames
            for k in range(n_trans):
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Đã hủy render.")
                t = (k + 1) / n_trans
                if sc.easing == "ease":
                    t = _ease_in_out(t)
                pose = interpolate_pose(pose_from, pose_to, t)

                # Transition effect (blend with previous scene's last frame)
                trans_t = None
                if k < trans_frames and prev_scene_last_frame is not None:
                    trans_t = (k + 1) / max(1, trans_frames)

                img = _render_full_frame(sc, pose, prev_scene_last_frame, trans_t)
                img.save(tmp / f"f_{idx:06d}.png", format="PNG")
                idx += 1
                if progress_cb is not None:
                    progress_cb(idx, total, f"Scene {sc_i + 1} · transition")

            # Hold frames
            if n_hold > 0:
                hold_img = _render_full_frame(sc, pose_to)
                for _ in range(n_hold):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Đã hủy render.")
                    hold_img.save(tmp / f"f_{idx:06d}.png", format="PNG")
                    idx += 1
                    if progress_cb is not None:
                        progress_cb(idx, total, f"Scene {sc_i + 1} · hold")
                prev_scene_last_frame = hold_img
            else:
                prev_scene_last_frame = img

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

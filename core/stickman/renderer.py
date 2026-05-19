"""Frame renderer — vẽ stickman lên ảnh PIL."""
from __future__ import annotations

import io
import math
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .skeleton import BONES, Pose, get_pose


def _font(size: int) -> Optional[ImageFont.ImageFont]:
    """Try to load a system font; fall back to default."""
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default()
    except Exception:  # noqa: BLE001
        return None


def _interp(p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    """Linear interp between two 2D points."""
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def interpolate_pose(pose_a: Pose, pose_b: Pose, t: float) -> Pose:
    """Lerp every joint between two poses (0..1)."""
    t = max(0.0, min(1.0, t))
    keys = set(pose_a.keys()) | set(pose_b.keys())
    out: Pose = {}
    for k in keys:
        a = pose_a.get(k) or pose_b.get(k) or (0.0, 0.0)
        b = pose_b.get(k) or pose_a.get(k) or (0.0, 0.0)
        out[k] = _interp(a, b, t)
    return out


def draw_frame(
    pose: Pose,
    *,
    size: Tuple[int, int] = (1080, 1920),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    line_width: int = 8,
    head_radius: int = 38,
    anchor: Optional[Tuple[int, int]] = None,
    scale: float = 1.0,
    caption: str = "",
    caption_size: int = 56,
    caption_color: str = "#1a73e8",
) -> Image.Image:
    """Draw a stickman pose onto a fresh image and return it."""
    w, h = size
    img = Image.new("RGB", (w, h), bg_color)
    drw = ImageDraw.Draw(img)

    # Anchor: where the hip lands. Default = horizontally centred, slightly
    # below middle so legs stick out.
    if anchor is None:
        anchor = (w // 2, int(h * 0.68))

    def project(p: Tuple[float, float]) -> Tuple[int, int]:
        return (
            int(anchor[0] + p[0] * scale),
            int(anchor[1] + p[1] * scale),
        )

    # ── Bones
    for a, b, mult in BONES:
        if a not in pose or b not in pose:
            continue
        pa = project(pose[a])
        pb = project(pose[b])
        drw.line([pa, pb], fill=line_color, width=max(1, int(line_width * mult)))

    # ── Head circle
    if "head" in pose and "neck" in pose:
        hx, hy = project(pose["head"])
        nx, ny = project(pose["neck"])
        # Place head circle so its bottom touches the neck line direction
        dx, dy = hx - nx, hy - ny
        dist = math.hypot(dx, dy) or 1.0
        # Centre of head = head joint
        r = int(head_radius * scale)
        bbox = [hx - r, hy - r, hx + r, hy + r]
        drw.ellipse(bbox, outline=line_color, width=line_width)

        # eyes (two dots) — orient based on body direction
        eye_off = max(4, r // 5)
        drw.ellipse(
            [hx - eye_off - 3, hy - 4, hx - eye_off + 3, hy + 2],
            fill=line_color,
        )
        drw.ellipse(
            [hx + eye_off - 3, hy - 4, hx + eye_off + 3, hy + 2],
            fill=line_color,
        )

    # ── Caption (optional)
    if caption:
        f = _font(caption_size)
        if f is not None:
            try:
                bbox = drw.textbbox((0, 0), caption, font=f)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:  # noqa: BLE001
                tw, th = drw.textsize(caption, font=f) if hasattr(drw, "textsize") else (0, 0)
            tx = (w - tw) // 2
            ty = int(h * 0.08)

            # Soft white plate behind text for readability
            pad = 18
            drw.rectangle(
                [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                fill=(255, 255, 255, 230),
                outline=line_color,
                width=2,
            )
            drw.text((tx, ty), caption, fill=caption_color, font=f)

    return img


def render_preview_png(
    pose_name: str,
    *,
    size: Tuple[int, int] = (540, 720),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
) -> bytes:
    """Render a single pose as PNG bytes (for the live preview thumbnail)."""
    pose = get_pose(pose_name)
    # smaller scale so it fits the preview thumbnail nicely
    scale = min(size[0] / 540, size[1] / 720) * 1.4
    img = draw_frame(
        pose,
        size=size,
        bg_color=bg_color,
        line_color=line_color,
        scale=scale,
        line_width=6,
        head_radius=32,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

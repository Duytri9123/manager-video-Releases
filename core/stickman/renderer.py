"""Frame renderer — vẽ stickman lên ảnh PIL.

Enhanced features:
- Emotions (biểu cảm mặt): happy, sad, angry, surprised, thinking, excited
- Character styles: teacher, scientist, chef, athlete (phụ kiện trên đầu/thân)
- Props: book, phone, laptop, coffee, pointer, microphone
- Background image: overlay stickman lên ảnh nền
"""
from __future__ import annotations

import io
import math
from pathlib import Path
from typing import List, Optional, Tuple

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


# ── Emotion face drawing ────────────────────────────────────────────────────

def _draw_face(
    drw: ImageDraw.ImageDraw,
    hx: int, hy: int, r: int,
    emotion: str,
    line_color: str,
    line_width: int,
    scale: float,
):
    """Draw facial expression inside the head circle based on emotion."""
    # Eye positions
    eye_off_x = max(4, r // 4)
    eye_y = hy - int(r * 0.15)
    eye_r = max(2, int(3 * scale))

    if emotion == "happy":
        # Happy eyes (arcs up) + smile
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        # Smile arc
        mouth_y = hy + int(r * 0.25)
        mouth_w = int(r * 0.5)
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.6),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.6)],
                start=0, end=180, fill=line_color, width=max(2, line_width // 2))

    elif emotion == "sad":
        # Sad eyes (dots) + frown
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        # Frown
        mouth_y = hy + int(r * 0.35)
        mouth_w = int(r * 0.4)
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.5),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.5)],
                start=180, end=360, fill=line_color, width=max(2, line_width // 2))

    elif emotion == "angry":
        # Angry eyebrows (V shape) + straight mouth
        brow_y = eye_y - int(r * 0.2)
        drw.line([hx - eye_off_x - eye_r, brow_y - int(3 * scale),
                  hx - eye_off_x + eye_r, brow_y + int(2 * scale)],
                 fill=line_color, width=max(2, line_width // 3))
        drw.line([hx + eye_off_x - eye_r, brow_y + int(2 * scale),
                  hx + eye_off_x + eye_r, brow_y - int(3 * scale)],
                 fill=line_color, width=max(2, line_width // 3))
        # Eyes
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        # Straight mouth
        mouth_y = hy + int(r * 0.3)
        mouth_w = int(r * 0.35)
        drw.line([hx - mouth_w, mouth_y, hx + mouth_w, mouth_y],
                 fill=line_color, width=max(2, line_width // 2))

    elif emotion == "surprised":
        # Big round eyes + O mouth
        big_r = int(eye_r * 1.8)
        drw.ellipse([hx - eye_off_x - big_r, eye_y - big_r,
                     hx - eye_off_x + big_r, eye_y + big_r],
                    outline=line_color, width=max(1, line_width // 3))
        drw.ellipse([hx + eye_off_x - big_r, eye_y - big_r,
                     hx + eye_off_x + big_r, eye_y + big_r],
                    outline=line_color, width=max(1, line_width // 3))
        # O mouth
        mouth_y = hy + int(r * 0.3)
        mouth_r = int(r * 0.2)
        drw.ellipse([hx - mouth_r, mouth_y - mouth_r, hx + mouth_r, mouth_y + mouth_r],
                    outline=line_color, width=max(2, line_width // 2))

    elif emotion == "thinking":
        # One eye squinting, hand-on-chin implied by pose
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        # Squint right eye (line)
        drw.line([hx + eye_off_x - eye_r * 2, eye_y,
                  hx + eye_off_x + eye_r * 2, eye_y],
                 fill=line_color, width=max(2, line_width // 3))
        # Slight smirk
        mouth_y = hy + int(r * 0.3)
        mouth_w = int(r * 0.3)
        drw.line([hx - int(mouth_w * 0.3), mouth_y,
                  hx + mouth_w, mouth_y - int(3 * scale)],
                 fill=line_color, width=max(2, line_width // 2))

    elif emotion == "excited":
        # Star eyes + big smile
        for sx in [hx - eye_off_x, hx + eye_off_x]:
            _draw_star(drw, sx, eye_y, int(eye_r * 2), line_color, scale)
        # Big smile
        mouth_y = hy + int(r * 0.2)
        mouth_w = int(r * 0.55)
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.5),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.7)],
                start=0, end=180, fill=line_color, width=max(2, line_width // 2))

    else:  # neutral
        # Simple dots + small line
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=line_color)
        mouth_y = hy + int(r * 0.3)
        mouth_w = int(r * 0.25)
        drw.line([hx - mouth_w, mouth_y, hx + mouth_w, mouth_y],
                 fill=line_color, width=max(2, line_width // 3))


def _draw_star(drw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: str, scale: float):
    """Draw a small 4-point star (for excited eyes)."""
    lw = max(1, int(2 * scale))
    drw.line([cx - r, cy, cx + r, cy], fill=color, width=lw)
    drw.line([cx, cy - r, cx, cy + r], fill=color, width=lw)
    d = int(r * 0.6)
    drw.line([cx - d, cy - d, cx + d, cy + d], fill=color, width=lw)
    drw.line([cx - d, cy + d, cx + d, cy - d], fill=color, width=lw)


# ── Character style decorations ─────────────────────────────────────────────

def _draw_character_style(
    drw: ImageDraw.ImageDraw,
    pose: Pose,
    project,
    style: str,
    line_color: str,
    line_width: int,
    head_radius: int,
    scale: float,
):
    """Draw character-specific accessories based on style."""
    if style == "normal" or "head" not in pose:
        return

    hx, hy = project(pose["head"])
    r = int(head_radius * scale)

    if style == "teacher":
        # Glasses
        g_r = int(r * 0.3)
        g_off = int(r * 0.25)
        drw.ellipse([hx - g_off - g_r, hy - g_r - 2, hx - g_off + g_r, hy + g_r - 2],
                    outline=line_color, width=max(1, line_width // 3))
        drw.ellipse([hx + g_off - g_r, hy - g_r - 2, hx + g_off + g_r, hy + g_r - 2],
                    outline=line_color, width=max(1, line_width // 3))
        drw.line([hx - g_off + g_r, hy - 2, hx + g_off - g_r, hy - 2],
                 fill=line_color, width=max(1, line_width // 4))

    elif style == "scientist":
        # Lab coat collar (two lines from neck) + glasses
        if "neck" in pose:
            nx, ny = project(pose["neck"])
            collar_w = int(12 * scale)
            drw.line([nx - collar_w, ny + int(5 * scale), nx, ny - int(3 * scale)],
                     fill=line_color, width=max(1, line_width // 3))
            drw.line([nx + collar_w, ny + int(5 * scale), nx, ny - int(3 * scale)],
                     fill=line_color, width=max(1, line_width // 3))
        # Round glasses
        g_r = int(r * 0.28)
        g_off = int(r * 0.25)
        drw.ellipse([hx - g_off - g_r, hy - g_r, hx - g_off + g_r, hy + g_r],
                    outline=line_color, width=max(1, line_width // 3))
        drw.ellipse([hx + g_off - g_r, hy - g_r, hx + g_off + g_r, hy + g_r],
                    outline=line_color, width=max(1, line_width // 3))

    elif style == "chef":
        # Chef hat (tall rectangle + puff on top)
        hat_w = int(r * 0.8)
        hat_h = int(r * 0.9)
        hat_top = hy - r - hat_h
        drw.rectangle([hx - hat_w, hat_top, hx + hat_w, hy - r + int(4 * scale)],
                      outline=line_color, width=max(1, line_width // 3))
        # Puff circles on top
        puff_r = int(hat_w * 0.5)
        for px in [hx - int(hat_w * 0.4), hx, hx + int(hat_w * 0.4)]:
            drw.ellipse([px - puff_r, hat_top - puff_r, px + puff_r, hat_top + puff_r],
                        outline=line_color, width=max(1, line_width // 4))

    elif style == "athlete":
        # Headband
        band_h = int(r * 0.2)
        band_y = hy - int(r * 0.4)
        drw.rectangle([hx - r - int(2 * scale), band_y - band_h,
                       hx + r + int(2 * scale), band_y + band_h],
                      outline=line_color, fill=None, width=max(2, line_width // 2))

    elif style == "student":
        # Backpack straps (two lines from shoulders)
        if "l_shoulder" in pose and "r_shoulder" in pose:
            ls = project(pose["l_shoulder"])
            rs = project(pose["r_shoulder"])
            strap_len = int(30 * scale)
            drw.line([ls[0] + int(4 * scale), ls[1], ls[0] + int(4 * scale), ls[1] + strap_len],
                     fill=line_color, width=max(2, line_width // 2))
            drw.line([rs[0] - int(4 * scale), rs[1], rs[0] - int(4 * scale), rs[1] + strap_len],
                     fill=line_color, width=max(2, line_width // 2))


# ── Props drawing ───────────────────────────────────────────────────────────

def _draw_props(
    drw: ImageDraw.ImageDraw,
    pose: Pose,
    project,
    props: List[str],
    line_color: str,
    line_width: int,
    scale: float,
):
    """Draw props near the character's hands."""
    if not props:
        return

    # Determine hand positions
    rh = project(pose["r_hand"]) if "r_hand" in pose else None
    lh = project(pose["l_hand"]) if "l_hand" in pose else None

    for i, prop in enumerate(props[:2]):  # max 2 props
        hand = rh if i == 0 else lh
        if hand is None:
            continue
        px, py = hand

        if prop == "book":
            bw, bh = int(20 * scale), int(28 * scale)
            drw.rectangle([px - bw, py - bh, px + bw, py + bh],
                          outline=line_color, width=max(1, line_width // 3))
            # Spine line
            drw.line([px, py - bh, px, py + bh], fill=line_color, width=max(1, line_width // 4))

        elif prop == "phone":
            pw, ph = int(10 * scale), int(18 * scale)
            drw.rounded_rectangle([px - pw, py - ph, px + pw, py + ph],
                                  radius=int(3 * scale),
                                  outline=line_color, width=max(1, line_width // 3))

        elif prop == "coffee":
            cw, ch = int(12 * scale), int(16 * scale)
            drw.rectangle([px - cw, py - ch, px + cw, py + int(ch * 0.3)],
                          outline=line_color, width=max(1, line_width // 3))
            # Handle
            drw.arc([px + cw, py - int(ch * 0.5), px + cw + int(8 * scale), py + int(ch * 0.1)],
                    start=270, end=90, fill=line_color, width=max(1, line_width // 3))
            # Steam
            for sx in range(3):
                sx_off = px - int(6 * scale) + sx * int(6 * scale)
                drw.arc([sx_off, py - ch - int(12 * scale), sx_off + int(6 * scale), py - ch],
                        start=180, end=360, fill=line_color, width=max(1, line_width // 4))

        elif prop == "pointer":
            # Long stick pointing right
            drw.line([px, py, px + int(50 * scale), py - int(10 * scale)],
                     fill=line_color, width=max(2, line_width // 2))

        elif prop == "microphone":
            # Mic body + head
            drw.line([px, py, px, py + int(25 * scale)],
                     fill=line_color, width=max(2, line_width // 2))
            mic_r = int(8 * scale)
            drw.ellipse([px - mic_r, py - mic_r * 2, px + mic_r, py],
                        outline=line_color, width=max(1, line_width // 3))

        elif prop == "laptop":
            lw_p, lh_p = int(25 * scale), int(16 * scale)
            # Screen
            drw.rectangle([px - lw_p, py - lh_p, px + lw_p, py],
                          outline=line_color, width=max(1, line_width // 3))
            # Base
            drw.line([px - lw_p - int(3 * scale), py + int(2 * scale),
                      px + lw_p + int(3 * scale), py + int(2 * scale)],
                     fill=line_color, width=max(2, line_width // 2))

        elif prop == "pen":
            drw.line([px, py, px + int(20 * scale), py - int(20 * scale)],
                     fill=line_color, width=max(1, line_width // 3))

        elif prop == "globe":
            g_r = int(18 * scale)
            drw.ellipse([px - g_r, py - g_r, px + g_r, py + g_r],
                        outline=line_color, width=max(1, line_width // 3))
            # Equator
            drw.arc([px - g_r, py - int(g_r * 0.3), px + g_r, py + int(g_r * 0.3)],
                    start=0, end=360, fill=line_color, width=max(1, line_width // 4))


# ── Main draw function ──────────────────────────────────────────────────────

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
    emotion: str = "neutral",
    character_style: str = "normal",
    props: Optional[List[str]] = None,
    background_image: Optional[Image.Image] = None,
) -> Image.Image:
    """Draw a stickman pose onto a fresh image and return it.

    Enhanced: supports emotion, character_style, props, background_image.
    """
    w, h = size

    # Background: either image or solid color
    if background_image is not None:
        img = background_image.copy()
        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)
        img = img.convert("RGB")
    else:
        img = Image.new("RGB", (w, h), bg_color)

    drw = ImageDraw.Draw(img)

    # Anchor: where the hip lands
    if anchor is None:
        anchor = (w // 2, int(h * 0.68))

    def project(p: Tuple[float, float]) -> Tuple[int, int]:
        return (
            int(anchor[0] + p[0] * scale),
            int(anchor[1] + p[1] * scale),
        )

    # ── Character style decorations (behind body)
    _draw_character_style(drw, pose, project, character_style,
                          line_color, line_width, head_radius, scale)

    # ── Bones (body)
    for a, b, mult in BONES:
        if a not in pose or b not in pose:
            continue
        pa = project(pose[a])
        pb = project(pose[b])
        drw.line([pa, pb], fill=line_color, width=max(1, int(line_width * mult)))

    # ── Head circle + face
    if "head" in pose and "neck" in pose:
        hx, hy = project(pose["head"])
        r = int(head_radius * scale)
        bbox = [hx - r, hy - r, hx + r, hy + r]
        # Fill head white for clean face
        drw.ellipse(bbox, fill="#ffffff", outline=line_color, width=line_width)
        # Draw facial expression
        _draw_face(drw, hx, hy, r, emotion, line_color, line_width, scale)

    # ── Props
    if props:
        _draw_props(drw, pose, project, props, line_color, line_width, scale)

    # ── Caption (optional)
    if caption:
        f = _font(caption_size)
        if f is not None:
            try:
                tbbox = drw.textbbox((0, 0), caption, font=f)
                tw = tbbox[2] - tbbox[0]
                th = tbbox[3] - tbbox[1]
            except Exception:  # noqa: BLE001
                tw, th = drw.textsize(caption, font=f) if hasattr(drw, "textsize") else (0, 0)
            tx = (w - tw) // 2
            ty = int(h * 0.08)

            # Soft plate behind text for readability
            pad = 18
            drw.rectangle(
                [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                fill=(255, 255, 255, 220),
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

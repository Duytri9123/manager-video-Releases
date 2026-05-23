"""Renderer V2 — Stickman chi tiết hơn: tóc, ngón tay, bàn chân, thân có khối.

Phong cách giống stock stickman vector (như ảnh mẫu):
- Nét đen dày, mượt
- Đầu tròn to, có tóc (spikes)
- Mắt rõ, lông mày biểu cảm
- Thân có hình dáng (không chỉ 1 line)
- Tay chân có khớp tròn, bàn tay có ngón
- Bàn chân oval
"""
from __future__ import annotations

import io
import math
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .skeleton import BONES, Pose, get_pose


def _font(size: int) -> Optional[ImageFont.ImageFont]:
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _interp(p1: Tuple[float, float], p2: Tuple[float, float], t: float) -> Tuple[float, float]:
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def interpolate_pose(pose_a: Pose, pose_b: Pose, t: float) -> Pose:
    t = max(0.0, min(1.0, t))
    keys = set(pose_a.keys()) | set(pose_b.keys())
    out: Pose = {}
    for k in keys:
        a = pose_a.get(k) or pose_b.get(k) or (0.0, 0.0)
        b = pose_b.get(k) or pose_a.get(k) or (0.0, 0.0)
        out[k] = _interp(a, b, t)
    return out


# ── Limb drawing with rounded joints ───────────────────────────────────────

def _draw_limb(
    drw: ImageDraw.ImageDraw,
    p1: Tuple[int, int],
    p2: Tuple[int, int],
    width: int,
    color: str,
    joint_radius: int = 0,
):
    """Draw a limb as a thick line with round caps (joints)."""
    drw.line([p1, p2], fill=color, width=width)
    # Round joints at both ends
    if joint_radius > 0:
        for p in [p1, p2]:
            drw.ellipse(
                [p[0] - joint_radius, p[1] - joint_radius,
                 p[0] + joint_radius, p[1] + joint_radius],
                fill=color,
            )


def _draw_hand(
    drw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    direction: float,  # angle in radians pointing away from elbow
    scale: float,
    color: str,
):
    """Draw a hand with fingers (simplified 3-finger fan)."""
    hx, hy = pos
    finger_len = int(14 * scale)
    finger_w = max(2, int(2.5 * scale))

    # Palm circle
    palm_r = int(6 * scale)
    drw.ellipse([hx - palm_r, hy - palm_r, hx + palm_r, hy + palm_r], fill=color)

    # 3 fingers fanning out from direction
    for offset in [-0.4, 0.0, 0.4]:
        angle = direction + offset
        fx = hx + int(finger_len * math.cos(angle))
        fy = hy + int(finger_len * math.sin(angle))
        drw.line([(hx, hy), (fx, fy)], fill=color, width=finger_w)


def _draw_foot(
    drw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    facing_right: bool,
    scale: float,
    color: str,
):
    """Draw a shoe/foot as an oval."""
    fx, fy = pos
    fw = int(18 * scale)
    fh = int(10 * scale)
    offset_x = int(5 * scale) if facing_right else int(-5 * scale)
    drw.ellipse(
        [fx + offset_x - fw // 2, fy - fh // 2,
         fx + offset_x + fw // 2, fy + fh // 2],
        fill=color,
    )


# ── Hair drawing ───────────────────────────────────────────────────────────

def _draw_hair(
    drw: ImageDraw.ImageDraw,
    hx: int, hy: int, r: int,
    scale: float,
    color: str,
    style: str = "spiky",
):
    """Draw hair on top of head."""
    if style == "spiky":
        # 3-4 spikes on top
        spike_h = int(r * 0.6)
        spike_w = int(r * 0.25)
        for i, offset in enumerate([-0.3, -0.1, 0.15, 0.35]):
            sx = hx + int(r * offset)
            sy = hy - r
            tip_x = sx + int(spike_w * 0.3 * (1 if i % 2 == 0 else -1))
            tip_y = sy - spike_h + int(i * 3 * scale)
            drw.polygon([
                (sx - spike_w // 2, sy + int(3 * scale)),
                (tip_x, tip_y),
                (sx + spike_w // 2, sy + int(3 * scale)),
            ], fill=color)
    elif style == "short":
        # Short cap-like hair
        drw.arc(
            [hx - r - int(2 * scale), hy - r - int(5 * scale),
             hx + r + int(2 * scale), hy - int(r * 0.2)],
            start=180, end=360, fill=color, width=int(6 * scale),
        )
    elif style == "long":
        # Longer strands on sides
        for side in [-1, 1]:
            sx = hx + side * int(r * 0.7)
            drw.line(
                [(sx, hy - int(r * 0.5)), (sx + side * int(5 * scale), hy + int(r * 0.8))],
                fill=color, width=int(4 * scale),
            )
            drw.line(
                [(sx + side * int(3 * scale), hy - int(r * 0.3)),
                 (sx + side * int(8 * scale), hy + int(r * 0.6))],
                fill=color, width=int(3 * scale),
            )


# ── Face expressions (detailed) ────────────────────────────────────────────

def _draw_face_v2(
    drw: ImageDraw.ImageDraw,
    hx: int, hy: int, r: int,
    emotion: str,
    color: str,
    scale: float,
):
    """Draw detailed face: eyebrows + eyes + mouth."""
    eye_off_x = int(r * 0.3)
    eye_y = hy - int(r * 0.1)
    eye_r = max(3, int(4 * scale))
    brow_y = eye_y - int(r * 0.28)
    brow_len = int(r * 0.22)
    mouth_y = hy + int(r * 0.35)
    lw = max(2, int(3 * scale))

    if emotion == "happy":
        # Eyes: dots
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=color)
        # Eyebrows: relaxed up
        drw.line([hx - eye_off_x - brow_len, brow_y,
                  hx - eye_off_x + brow_len, brow_y - int(2 * scale)],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y - int(2 * scale),
                  hx + eye_off_x + brow_len, brow_y],
                 fill=color, width=lw)
        # Smile
        mouth_w = int(r * 0.4)
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.4),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.6)],
                start=0, end=180, fill=color, width=lw)

    elif emotion == "sad":
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=color)
        # Sad eyebrows: inner up
        drw.line([hx - eye_off_x - brow_len, brow_y - int(3 * scale),
                  hx - eye_off_x + brow_len, brow_y + int(2 * scale)],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y + int(2 * scale),
                  hx + eye_off_x + brow_len, brow_y - int(3 * scale)],
                 fill=color, width=lw)
        # Frown
        mouth_w = int(r * 0.3)
        drw.arc([hx - mouth_w, mouth_y,
                 hx + mouth_w, mouth_y + int(mouth_w * 0.8)],
                start=180, end=360, fill=color, width=lw)

    elif emotion == "angry":
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=color)
        # Angry eyebrows: V shape
        drw.line([hx - eye_off_x - brow_len, brow_y + int(3 * scale),
                  hx - eye_off_x + brow_len, brow_y - int(4 * scale)],
                 fill=color, width=lw + 1)
        drw.line([hx + eye_off_x - brow_len, brow_y - int(4 * scale),
                  hx + eye_off_x + brow_len, brow_y + int(3 * scale)],
                 fill=color, width=lw + 1)
        # Tight mouth
        mouth_w = int(r * 0.3)
        drw.line([hx - mouth_w, mouth_y, hx + mouth_w, mouth_y],
                 fill=color, width=lw)

    elif emotion == "surprised":
        # Big round eyes
        big_r = int(eye_r * 2)
        drw.ellipse([hx - eye_off_x - big_r, eye_y - big_r,
                     hx - eye_off_x + big_r, eye_y + big_r],
                    outline=color, width=lw)
        drw.ellipse([hx + eye_off_x - big_r, eye_y - big_r,
                     hx + eye_off_x + big_r, eye_y + big_r],
                    outline=color, width=lw)
        # Raised eyebrows
        drw.line([hx - eye_off_x - brow_len, brow_y - int(5 * scale),
                  hx - eye_off_x + brow_len, brow_y - int(5 * scale)],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y - int(5 * scale),
                  hx + eye_off_x + brow_len, brow_y - int(5 * scale)],
                 fill=color, width=lw)
        # O mouth
        mouth_r = int(r * 0.18)
        drw.ellipse([hx - mouth_r, mouth_y - mouth_r, hx + mouth_r, mouth_y + mouth_r],
                    outline=color, width=lw)

    elif emotion == "thinking":
        # One eye normal, one squinting
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.line([hx + eye_off_x - eye_r * 2, eye_y,
                  hx + eye_off_x + eye_r * 2, eye_y],
                 fill=color, width=lw)
        # One raised brow
        drw.line([hx - eye_off_x - brow_len, brow_y,
                  hx - eye_off_x + brow_len, brow_y - int(4 * scale)],
                 fill=color, width=lw)
        # Smirk
        mouth_w = int(r * 0.25)
        drw.line([hx - int(mouth_w * 0.3), mouth_y,
                  hx + mouth_w, mouth_y - int(3 * scale)],
                 fill=color, width=lw)

    elif emotion == "excited":
        # Star-like eyes
        for sx in [hx - eye_off_x, hx + eye_off_x]:
            for angle in [0, 45, 90, 135]:
                rad = math.radians(angle)
                x1 = sx + int(eye_r * 1.5 * math.cos(rad))
                y1 = eye_y + int(eye_r * 1.5 * math.sin(rad))
                x2 = sx - int(eye_r * 1.5 * math.cos(rad))
                y2 = eye_y - int(eye_r * 1.5 * math.sin(rad))
                drw.line([(x1, y1), (x2, y2)], fill=color, width=max(1, lw - 1))
        # Big smile
        mouth_w = int(r * 0.45)
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.3),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.7)],
                start=0, end=180, fill=color, width=lw)
        # Raised brows
        drw.line([hx - eye_off_x - brow_len, brow_y - int(5 * scale),
                  hx - eye_off_x + brow_len, brow_y - int(5 * scale)],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y - int(5 * scale),
                  hx + eye_off_x + brow_len, brow_y - int(5 * scale)],
                 fill=color, width=lw)

    else:  # neutral
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.ellipse([hx + eye_off_x - eye_r, eye_y - eye_r,
                     hx + eye_off_x + eye_r, eye_y + eye_r], fill=color)
        # Flat brows
        drw.line([hx - eye_off_x - brow_len, brow_y,
                  hx - eye_off_x + brow_len, brow_y],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y,
                  hx + eye_off_x + brow_len, brow_y],
                 fill=color, width=lw)
        # Neutral mouth
        mouth_w = int(r * 0.2)
        drw.line([hx - mouth_w, mouth_y, hx + mouth_w, mouth_y],
                 fill=color, width=lw)


# ── Torso drawing (polygon body shape) ─────────────────────────────────────

def _draw_torso(
    drw: ImageDraw.ImageDraw,
    neck: Tuple[int, int],
    hip: Tuple[int, int],
    l_shoulder: Tuple[int, int],
    r_shoulder: Tuple[int, int],
    color: str,
    width: int,
):
    """Draw torso as a tapered polygon (shoulders wider than hip)."""
    # Torso outline: shoulders → hip (narrower)
    hip_half = int(abs(r_shoulder[0] - l_shoulder[0]) * 0.35)
    points = [
        l_shoulder,
        r_shoulder,
        (hip[0] + hip_half, hip[1]),
        (hip[0] - hip_half, hip[1]),
    ]
    drw.polygon(points, outline=color, width=width)


# ── Main draw function V2 ──────────────────────────────────────────────────

def draw_frame_v2(
    pose: Pose,
    *,
    size: Tuple[int, int] = (1080, 1920),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    line_width: int = 6,
    head_radius: int = 42,
    anchor: Optional[Tuple[int, int]] = None,
    scale: float = 1.0,
    caption: str = "",
    caption_size: int = 56,
    caption_color: str = "#1a73e8",
    emotion: str = "neutral",
    character_style: str = "normal",
    props: Optional[List[str]] = None,
    background_image: Optional[Image.Image] = None,
    hair_style: str = "spiky",
) -> Image.Image:
    """Draw a detailed stickman (V2) — looks like stock vector stickman."""
    w, h = size

    if background_image is not None:
        img = background_image.copy()
        if img.size != (w, h):
            img = img.resize((w, h), Image.LANCZOS)
        img = img.convert("RGB")
    else:
        img = Image.new("RGB", (w, h), bg_color)

    drw = ImageDraw.Draw(img)

    if anchor is None:
        anchor = (w // 2, int(h * 0.68))

    def project(p: Tuple[float, float]) -> Tuple[int, int]:
        return (
            int(anchor[0] + p[0] * scale),
            int(anchor[1] + p[1] * scale),
        )

    lw = max(3, int(line_width * scale))
    joint_r = max(3, int(5 * scale))
    hr = int(head_radius * scale)

    # Get projected positions
    pts = {k: project(v) for k, v in pose.items()}

    # ── Torso (polygon body)
    if all(k in pts for k in ("neck", "hip", "l_shoulder", "r_shoulder")):
        _draw_torso(drw, pts["neck"], pts["hip"],
                    pts["l_shoulder"], pts["r_shoulder"],
                    line_color, lw)

    # ── Arms (upper + lower with joints)
    for side in ["l", "r"]:
        shoulder = pts.get(f"{side}_shoulder")
        elbow = pts.get(f"{side}_elbow")
        hand = pts.get(f"{side}_hand")
        if shoulder and elbow:
            _draw_limb(drw, shoulder, elbow, lw, line_color, joint_r)
        if elbow and hand:
            _draw_limb(drw, elbow, hand, lw, line_color, joint_r)
        # Hand with fingers
        if hand and elbow:
            dx = hand[0] - elbow[0]
            dy = hand[1] - elbow[1]
            angle = math.atan2(dy, dx)
            _draw_hand(drw, hand, angle, scale, line_color)

    # ── Legs (upper + lower with joints)
    for side in ["l", "r"]:
        knee = pts.get(f"{side}_knee")
        foot = pts.get(f"{side}_foot")
        hip_pt = pts.get("hip")
        if hip_pt and knee:
            _draw_limb(drw, hip_pt, knee, lw + 1, line_color, joint_r)
        if knee and foot:
            _draw_limb(drw, knee, foot, lw, line_color, joint_r)
        # Foot
        if foot:
            facing_right = side == "r"
            _draw_foot(drw, foot, facing_right, scale, line_color)

    # ── Head
    if "head" in pts:
        hx, hy = pts["head"]
        # Head circle (filled white for clean face)
        drw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr],
                    fill="#ffffff", outline=line_color, width=lw)
        # Hair
        _draw_hair(drw, hx, hy, hr, scale, line_color, style=hair_style)
        # Face
        _draw_face_v2(drw, hx, hy, hr, emotion, line_color, scale)

    # ── Neck line (connect head to body)
    if "head" in pts and "neck" in pts:
        drw.line([pts["head"], pts["neck"]], fill=line_color, width=lw)

    # ── Props (reuse from renderer.py)
    if props:
        from .renderer import _draw_props
        _draw_props(drw, pose, project, props, line_color, line_width, scale)

    # ── Caption
    if caption:
        f = _font(caption_size)
        if f is not None:
            try:
                tbbox = drw.textbbox((0, 0), caption, font=f)
                tw = tbbox[2] - tbbox[0]
                th = tbbox[3] - tbbox[1]
            except Exception:
                tw, th = 0, 0
            tx = (w - tw) // 2
            ty = int(h * 0.08)
            pad = 18
            drw.rectangle(
                [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                fill=(255, 255, 255, 220),
                outline=line_color,
                width=2,
            )
            drw.text((tx, ty), caption, fill=caption_color, font=f)

    return img


def render_preview_png_v2(
    pose_name: str,
    *,
    size: Tuple[int, int] = (540, 720),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    emotion: str = "neutral",
) -> bytes:
    """Render a single pose as PNG bytes using V2 renderer."""
    pose = get_pose(pose_name)
    scale = min(size[0] / 540, size[1] / 720) * 1.4
    img = draw_frame_v2(
        pose,
        size=size,
        bg_color=bg_color,
        line_color=line_color,
        scale=scale,
        line_width=5,
        head_radius=36,
        emotion=emotion,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

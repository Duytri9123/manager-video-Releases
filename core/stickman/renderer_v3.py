"""Renderer V3 — Stickman mượt, đẹp bằng supersampling + smooth curves.

Kỹ thuật:
- Render ở 3x resolution → downscale (anti-aliasing tự nhiên)
- Bezier curves cho tay/chân (không thẳng đơ)
- Round linecap bằng circle fill tại mỗi điểm
- Thân hình mượt (rounded rectangle thay vì polygon góc cạnh)
- Đầu to hơn, mắt to hơn, biểu cảm rõ hơn
- Phong cách giống stock vector stickman (nét đen dày, mượt, tự nhiên)

Không cần cairosvg — chỉ dùng Pillow + numpy (đã có sẵn).
"""
from __future__ import annotations

import io
import math
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .skeleton import BONES, Pose, get_pose

# Supersample factor — render at Nx then downscale for smooth edges
_SS = 3


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


# ── Smooth curve helpers ───────────────────────────────────────────────────

def _bezier_quadratic(p0, p1, p2, steps=12):
    """Generate points along a quadratic bezier curve."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
        points.append((int(x), int(y)))
    return points


def _draw_smooth_limb(
    drw: ImageDraw.ImageDraw,
    p1: Tuple[int, int],
    p2: Tuple[int, int],
    width: int,
    color: str,
    curve_amount: float = 0.0,
):
    """Draw a limb with smooth round caps. Optional curve (bezier)."""
    if abs(curve_amount) < 0.01:
        # Straight but with round caps (circles at endpoints)
        drw.line([p1, p2], fill=color, width=width)
        r = width // 2
        drw.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=color)
        drw.ellipse([p2[0] - r, p2[1] - r, p2[0] + r, p2[1] + r], fill=color)
    else:
        # Bezier curve
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2
        # Perpendicular offset for control point
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        ctrl = (int(mid_x - dy * curve_amount), int(mid_y + dx * curve_amount))
        points = _bezier_quadratic(p1, ctrl, p2, steps=16)
        # Draw thick polyline with round joints
        for i in range(len(points) - 1):
            drw.line([points[i], points[i + 1]], fill=color, width=width)
        # Round caps
        r = width // 2
        for pt in points[::4]:
            drw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=color)
        drw.ellipse([p1[0] - r, p1[1] - r, p1[0] + r, p1[1] + r], fill=color)
        drw.ellipse([p2[0] - r, p2[1] - r, p2[0] + r, p2[1] + r], fill=color)


def _draw_hand_v3(
    drw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    direction: float,
    scale: float,
    color: str,
):
    """Draw a natural-looking hand (palm + 4 short fingers)."""
    hx, hy = pos
    finger_len = int(10 * scale)
    finger_w = max(2, int(2.5 * scale))
    palm_r = int(5 * scale)

    # Palm
    drw.ellipse([hx - palm_r, hy - palm_r, hx + palm_r, hy + palm_r], fill=color)

    # 4 fingers fanning
    for offset in [-0.5, -0.17, 0.17, 0.5]:
        angle = direction + offset
        fx = hx + int(finger_len * math.cos(angle))
        fy = hy + int(finger_len * math.sin(angle))
        drw.line([(hx, hy), (fx, fy)], fill=color, width=finger_w)
        # Fingertip
        drw.ellipse([fx - 1, fy - 1, fx + 1, fy + 1], fill=color)


def _draw_foot_v3(
    drw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    facing_right: bool,
    scale: float,
    color: str,
):
    """Draw a shoe-like foot."""
    fx, fy = pos
    fw = int(22 * scale)
    fh = int(12 * scale)
    offset_x = int(6 * scale) if facing_right else int(-6 * scale)
    # Rounded shoe shape
    drw.rounded_rectangle(
        [fx + offset_x - fw // 2, fy - fh // 2,
         fx + offset_x + fw // 2, fy + fh // 2],
        radius=int(fh * 0.4),
        fill=color,
    )


# ── Hair ───────────────────────────────────────────────────────────────────

def _draw_hair_v3(
    drw: ImageDraw.ImageDraw,
    hx: int, hy: int, r: int,
    scale: float,
    color: str,
):
    """Draw natural-looking messy hair (multiple curved strands)."""
    # Several curved strands on top
    strand_count = 5
    for i in range(strand_count):
        angle = math.pi + (i / (strand_count - 1)) * math.pi * 0.8 - math.pi * 0.4
        base_x = hx + int(r * 0.6 * math.cos(angle))
        base_y = hy - int(r * 0.85)
        tip_x = base_x + int((8 + i * 3) * scale * math.cos(angle - 0.3))
        tip_y = base_y - int((15 + i * 4) * scale)
        # Curved strand
        ctrl_x = (base_x + tip_x) // 2 + int(5 * scale * (1 if i % 2 == 0 else -1))
        ctrl_y = (base_y + tip_y) // 2
        points = _bezier_quadratic((base_x, base_y), (ctrl_x, ctrl_y), (tip_x, tip_y), steps=8)
        w = max(3, int(4 * scale))
        for j in range(len(points) - 1):
            drw.line([points[j], points[j + 1]], fill=color, width=w)


# ── Face V3 (smooth, expressive) ──────────────────────────────────────────

def _draw_face_v3(
    drw: ImageDraw.ImageDraw,
    hx: int, hy: int, r: int,
    emotion: str,
    color: str,
    scale: float,
):
    """Draw smooth, expressive face."""
    eye_off_x = int(r * 0.28)
    eye_y = hy - int(r * 0.08)
    eye_r = max(3, int(5 * scale))
    brow_y = eye_y - int(r * 0.3)
    brow_len = int(r * 0.2)
    mouth_y = hy + int(r * 0.35)
    lw = max(3, int(3.5 * scale))

    # ── Eyes
    if emotion == "surprised":
        big_r = int(eye_r * 1.8)
        drw.ellipse([hx - eye_off_x - big_r, eye_y - big_r,
                     hx - eye_off_x + big_r, eye_y + big_r],
                    outline=color, width=lw)
        drw.ellipse([hx + eye_off_x - big_r, eye_y - big_r,
                     hx + eye_off_x + big_r, eye_y + big_r],
                    outline=color, width=lw)
        # Pupils
        pr = int(eye_r * 0.7)
        drw.ellipse([hx - eye_off_x - pr, eye_y - pr,
                     hx - eye_off_x + pr, eye_y + pr], fill=color)
        drw.ellipse([hx + eye_off_x - pr, eye_y - pr,
                     hx + eye_off_x + pr, eye_y + pr], fill=color)
    elif emotion == "thinking":
        # Left eye normal, right squinting
        drw.ellipse([hx - eye_off_x - eye_r, eye_y - eye_r,
                     hx - eye_off_x + eye_r, eye_y + eye_r], fill=color)
        drw.line([hx + eye_off_x - int(eye_r * 1.5), eye_y,
                  hx + eye_off_x + int(eye_r * 1.5), eye_y],
                 fill=color, width=lw)
    else:
        # Normal round eyes with pupils
        for sx in [hx - eye_off_x, hx + eye_off_x]:
            drw.ellipse([sx - eye_r, eye_y - eye_r, sx + eye_r, eye_y + eye_r], fill=color)

    # ── Eyebrows
    if emotion == "angry":
        drw.line([hx - eye_off_x - brow_len, brow_y + int(4 * scale),
                  hx - eye_off_x + brow_len, brow_y - int(3 * scale)],
                 fill=color, width=lw + 1)
        drw.line([hx + eye_off_x - brow_len, brow_y - int(3 * scale),
                  hx + eye_off_x + brow_len, brow_y + int(4 * scale)],
                 fill=color, width=lw + 1)
    elif emotion == "sad":
        drw.line([hx - eye_off_x - brow_len, brow_y - int(3 * scale),
                  hx - eye_off_x + brow_len, brow_y + int(2 * scale)],
                 fill=color, width=lw)
        drw.line([hx + eye_off_x - brow_len, brow_y + int(2 * scale),
                  hx + eye_off_x + brow_len, brow_y - int(3 * scale)],
                 fill=color, width=lw)
    elif emotion in ("surprised", "excited"):
        for sx in [hx - eye_off_x, hx + eye_off_x]:
            drw.line([sx - brow_len, brow_y - int(5 * scale),
                      sx + brow_len, brow_y - int(5 * scale)],
                     fill=color, width=lw)
    elif emotion == "thinking":
        drw.line([hx - eye_off_x - brow_len, brow_y,
                  hx - eye_off_x + brow_len, brow_y - int(4 * scale)],
                 fill=color, width=lw)
    else:
        for sx in [hx - eye_off_x, hx + eye_off_x]:
            drw.line([sx - brow_len, brow_y, sx + brow_len, brow_y],
                     fill=color, width=lw)

    # ── Mouth
    mouth_w = int(r * 0.3)
    if emotion in ("happy", "excited"):
        # Smile arc
        drw.arc([hx - mouth_w, mouth_y - int(mouth_w * 0.3),
                 hx + mouth_w, mouth_y + int(mouth_w * 0.7)],
                start=0, end=180, fill=color, width=lw)
    elif emotion == "sad":
        drw.arc([hx - mouth_w, mouth_y,
                 hx + mouth_w, mouth_y + int(mouth_w * 0.8)],
                start=180, end=360, fill=color, width=lw)
    elif emotion == "angry":
        drw.line([hx - mouth_w, mouth_y, hx + mouth_w, mouth_y + int(2 * scale)],
                 fill=color, width=lw)
    elif emotion == "surprised":
        mouth_r = int(r * 0.15)
        drw.ellipse([hx - mouth_r, mouth_y - mouth_r, hx + mouth_r, mouth_y + mouth_r],
                    outline=color, width=lw)
    elif emotion == "thinking":
        # Slight smirk
        pts = _bezier_quadratic(
            (hx - int(mouth_w * 0.5), mouth_y),
            (hx, mouth_y - int(3 * scale)),
            (hx + mouth_w, mouth_y - int(5 * scale)),
            steps=8,
        )
        for i in range(len(pts) - 1):
            drw.line([pts[i], pts[i + 1]], fill=color, width=lw)
    else:
        drw.line([hx - int(mouth_w * 0.6), mouth_y,
                  hx + int(mouth_w * 0.6), mouth_y],
                 fill=color, width=lw)


# ── Main draw function V3 ──────────────────────────────────────────────────

def draw_frame_v3(
    pose: Pose,
    *,
    size: Tuple[int, int] = (1080, 1920),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    line_width: int = 7,
    head_radius: int = 48,
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
    """Draw a smooth, professional stickman using supersampling."""
    w, h = size
    # Render at higher resolution for anti-aliasing
    ss = _SS
    sw, sh = w * ss, h * ss
    s_scale = scale * ss

    if background_image is not None:
        img_big = background_image.copy()
        if img_big.size != (sw, sh):
            img_big = img_big.resize((sw, sh), Image.LANCZOS)
        img_big = img_big.convert("RGB")
    else:
        img_big = Image.new("RGB", (sw, sh), bg_color)

    drw = ImageDraw.Draw(img_big)

    if anchor is None:
        anchor_ss = (sw // 2, int(sh * 0.68))
    else:
        anchor_ss = (anchor[0] * ss, anchor[1] * ss)

    def project(p: Tuple[float, float]) -> Tuple[int, int]:
        return (
            int(anchor_ss[0] + p[0] * s_scale),
            int(anchor_ss[1] + p[1] * s_scale),
        )

    lw = max(4, int(line_width * s_scale * 0.7))
    hr = int(head_radius * s_scale)

    pts = {k: project(v) for k, v in pose.items()}

    # ── Torso (rounded rectangle body)
    if all(k in pts for k in ("neck", "hip", "l_shoulder", "r_shoulder")):
        neck = pts["neck"]
        hip = pts["hip"]
        ls = pts["l_shoulder"]
        rs = pts["r_shoulder"]
        # Smooth torso: rounded trapezoid
        shoulder_w = abs(rs[0] - ls[0]) // 2
        hip_w = int(shoulder_w * 0.7)
        body_pts = [
            (neck[0] - shoulder_w, neck[1]),
            (neck[0] + shoulder_w, neck[1]),
            (hip[0] + hip_w, hip[1]),
            (hip[0] - hip_w, hip[1]),
        ]
        drw.polygon(body_pts, outline=line_color, width=lw)
        # Smooth the corners with circles
        for pt in body_pts:
            r = lw // 2
            drw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=line_color)

    # ── Arms with slight curve
    for side, curve_dir in [("l", 0.08), ("r", -0.08)]:
        shoulder = pts.get(f"{side}_shoulder")
        elbow = pts.get(f"{side}_elbow")
        hand = pts.get(f"{side}_hand")
        if shoulder and elbow:
            _draw_smooth_limb(drw, shoulder, elbow, lw, line_color, curve_amount=curve_dir)
        if elbow and hand:
            _draw_smooth_limb(drw, elbow, hand, lw, line_color, curve_amount=curve_dir * 0.5)
        # Hand
        if hand and elbow:
            dx = hand[0] - elbow[0]
            dy = hand[1] - elbow[1]
            angle = math.atan2(dy, dx)
            _draw_hand_v3(drw, hand, angle, s_scale, line_color)

    # ── Legs with slight curve
    for side, curve_dir in [("l", -0.06), ("r", 0.06)]:
        knee = pts.get(f"{side}_knee")
        foot = pts.get(f"{side}_foot")
        hip_pt = pts.get("hip")
        if hip_pt and knee:
            _draw_smooth_limb(drw, hip_pt, knee, lw + int(2 * s_scale), line_color, curve_amount=curve_dir)
        if knee and foot:
            _draw_smooth_limb(drw, knee, foot, lw, line_color, curve_amount=curve_dir * 0.5)
        # Foot
        if foot:
            _draw_foot_v3(drw, foot, side == "r", s_scale, line_color)

    # ── Head (big, clean)
    if "head" in pts:
        hx, hy = pts["head"]
        # White fill + thick outline
        drw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr],
                    fill="#ffffff", outline=line_color, width=lw + int(2 * s_scale))
        # Hair
        _draw_hair_v3(drw, hx, hy, hr, s_scale, line_color)
        # Face
        _draw_face_v3(drw, hx, hy, hr, emotion, line_color, s_scale)

    # ── Neck
    if "head" in pts and "neck" in pts:
        _draw_smooth_limb(drw, pts["head"], pts["neck"], lw, line_color)

    # ── Props
    if props:
        from .renderer import _draw_props
        _draw_props(drw, pose, project, props, line_color, line_width * ss, s_scale)

    # ── Downscale for anti-aliasing
    img = img_big.resize((w, h), Image.LANCZOS)

    # ── Caption (draw on final resolution for crisp text)
    if caption:
        drw2 = ImageDraw.Draw(img)
        f = _font(caption_size)
        if f is not None:
            try:
                tbbox = drw2.textbbox((0, 0), caption, font=f)
                tw = tbbox[2] - tbbox[0]
                th = tbbox[3] - tbbox[1]
            except Exception:
                tw, th = 0, 0
            tx = (w - tw) // 2
            ty = int(h * 0.06)
            pad = 16
            # Semi-transparent plate
            drw2.rounded_rectangle(
                [tx - pad, ty - pad, tx + tw + pad, ty + th + pad],
                radius=10,
                fill=(255, 255, 255, 230),
                outline=line_color,
                width=2,
            )
            drw2.text((tx, ty), caption, fill=caption_color, font=f)

    return img


def render_preview_png_v3(
    pose_name: str,
    *,
    size: Tuple[int, int] = (540, 720),
    bg_color: str = "#ffffff",
    line_color: str = "#1a2332",
    emotion: str = "neutral",
) -> bytes:
    """Render a single pose as PNG bytes using V3 smooth renderer."""
    pose = get_pose(pose_name)
    scale = min(size[0] / 540, size[1] / 720) * 1.4
    img = draw_frame_v3(
        pose,
        size=size,
        bg_color=bg_color,
        line_color=line_color,
        scale=scale,
        line_width=6,
        head_radius=42,
        emotion=emotion,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

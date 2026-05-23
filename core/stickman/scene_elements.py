"""Scene Elements — vẽ background, vật thể, bong bóng thoại, hiệu ứng.

Bổ sung cho renderer.py: thay vì chỉ 1 stickman trên nền trắng,
scene giờ có nhiều layer phức tạp hơn.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


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


# ── Gradient backgrounds (no AI needed) ────────────────────────────────────

GRADIENT_PRESETS = {
    "sky":       ["#87CEEB", "#1565C0"],
    "sunset":    ["#FF6B35", "#F7C59F", "#004E89"],
    "night":     ["#0D1B2A", "#1B2838", "#415A77"],
    "forest":    ["#2D5016", "#4A7C23", "#8DB655"],
    "ocean":     ["#006994", "#00A6C0", "#B3E8F0"],
    "classroom": ["#FFF8E7", "#F5E6CC", "#E8D5B7"],
    "space":     ["#0B0C10", "#1F2833", "#45A29E"],
    "warm":      ["#FF9A76", "#FFECD2"],
    "cool":      ["#667EEA", "#764BA2"],
    "neutral":   ["#F8F9FA", "#E9ECEF", "#DEE2E6"],
}


def draw_gradient_bg(
    size: Tuple[int, int],
    colors: List[str],
    direction: str = "vertical",
) -> Image.Image:
    """Draw a multi-color gradient background."""
    w, h = size
    img = Image.new("RGB", (w, h))
    drw = ImageDraw.Draw(img)

    if not colors:
        colors = ["#ffffff", "#f0f0f0"]

    n_stops = len(colors)
    if direction == "vertical":
        for y in range(h):
            t = y / max(1, h - 1)
            color = _lerp_color_multi(colors, t)
            drw.line([(0, y), (w, y)], fill=color)
    else:  # horizontal
        for x in range(w):
            t = x / max(1, w - 1)
            color = _lerp_color_multi(colors, t)
            drw.line([(x, 0), (x, h)], fill=color)

    return img


def _lerp_color_multi(colors: List[str], t: float) -> Tuple[int, int, int]:
    """Interpolate between multiple color stops."""
    if len(colors) == 1:
        return _hex_to_rgb(colors[0])
    t = max(0.0, min(1.0, t))
    n = len(colors) - 1
    idx = int(t * n)
    idx = min(idx, n - 1)
    local_t = (t * n) - idx
    c1 = _hex_to_rgb(colors[idx])
    c2 = _hex_to_rgb(colors[idx + 1])
    return (
        int(c1[0] + (c2[0] - c1[0]) * local_t),
        int(c1[1] + (c2[1] - c1[1]) * local_t),
        int(c1[2] + (c2[2] - c1[2]) * local_t),
    )


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        return (255, 255, 255)


# ── Scene objects (furniture, items, scenery) ──────────────────────────────

SCENE_OBJECTS = {
    "desk": "_draw_desk",
    "whiteboard": "_draw_whiteboard",
    "tree": "_draw_tree",
    "sun": "_draw_sun",
    "moon": "_draw_moon",
    "cloud": "_draw_cloud",
    "building": "_draw_building",
    "computer": "_draw_computer",
    "chair": "_draw_chair",
    "stage": "_draw_stage",
    "podium": "_draw_podium",
    "lamp": "_draw_lamp",
}


def draw_scene_objects(
    img: Image.Image,
    objects: List[str],
    line_color: str = "#1a2332",
    scale: float = 1.0,
):
    """Draw scene objects onto the image."""
    drw = ImageDraw.Draw(img)
    w, h = img.size

    for obj_name in objects[:5]:  # max 5 objects
        fn_name = SCENE_OBJECTS.get(obj_name)
        if fn_name and fn_name in globals():
            globals()[fn_name](drw, w, h, line_color, scale)


def _draw_desk(drw, w, h, color, scale):
    """Simple desk at bottom-center."""
    dw = int(w * 0.35)
    dh = int(20 * scale)
    dx = w // 2 - dw // 2
    dy = int(h * 0.78)
    # Table top
    drw.rectangle([dx, dy, dx + dw, dy + dh], fill="#8B4513", outline=color, width=2)
    # Legs
    leg_w = int(8 * scale)
    drw.rectangle([dx + int(15 * scale), dy + dh, dx + int(15 * scale) + leg_w, dy + int(60 * scale)],
                  fill="#654321", outline=color, width=1)
    drw.rectangle([dx + dw - int(15 * scale) - leg_w, dy + dh, dx + dw - int(15 * scale), dy + int(60 * scale)],
                  fill="#654321", outline=color, width=1)


def _draw_whiteboard(drw, w, h, color, scale):
    """Whiteboard behind character."""
    bw = int(w * 0.5)
    bh = int(h * 0.25)
    bx = w // 2 - bw // 2
    by = int(h * 0.25)
    drw.rectangle([bx, by, bx + bw, by + bh], fill="#FFFFFF", outline=color, width=3)
    # Frame border
    drw.rectangle([bx - 3, by - 3, bx + bw + 3, by + bh + 3], outline="#555555", width=2)
    # Stand
    mid_x = w // 2
    drw.line([mid_x, by + bh, mid_x, by + bh + int(40 * scale)], fill=color, width=int(4 * scale))


def _draw_tree(drw, w, h, color, scale):
    """Tree on the left side."""
    tx = int(w * 0.12)
    ty = int(h * 0.5)
    trunk_w = int(16 * scale)
    trunk_h = int(80 * scale)
    # Trunk
    drw.rectangle([tx - trunk_w // 2, ty, tx + trunk_w // 2, ty + trunk_h],
                  fill="#654321", outline=color, width=1)
    # Foliage (circles)
    leaf_r = int(45 * scale)
    for off in [(-15, -30), (15, -35), (0, -55)]:
        cx = tx + int(off[0] * scale)
        cy = ty + int(off[1] * scale)
        drw.ellipse([cx - leaf_r, cy - leaf_r, cx + leaf_r, cy + leaf_r],
                    fill="#228B22", outline="#1a5c1a", width=2)


def _draw_sun(drw, w, h, color, scale):
    """Sun in top-right corner."""
    sx = int(w * 0.85)
    sy = int(h * 0.08)
    r = int(35 * scale)
    drw.ellipse([sx - r, sy - r, sx + r, sy + r], fill="#FFD700", outline="#FFA500", width=2)
    # Rays
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = sx + int((r + 5) * math.cos(rad))
        y1 = sy + int((r + 5) * math.sin(rad))
        x2 = sx + int((r + 20) * scale * math.cos(rad))
        y2 = sy + int((r + 20) * scale * math.sin(rad))
        drw.line([x1, y1, x2, y2], fill="#FFA500", width=max(2, int(3 * scale)))


def _draw_moon(drw, w, h, color, scale):
    """Crescent moon top-right."""
    mx = int(w * 0.82)
    my = int(h * 0.1)
    r = int(30 * scale)
    drw.ellipse([mx - r, my - r, mx + r, my + r], fill="#F4E99B", outline="#D4C76A", width=2)
    # Crescent cut
    drw.ellipse([mx - r + int(12 * scale), my - r - int(5 * scale),
                 mx + r + int(12 * scale), my + r - int(5 * scale)],
                fill="#0D1B2A")  # same as night bg


def _draw_cloud(drw, w, h, color, scale):
    """A fluffy cloud top area."""
    cx = int(w * 0.3)
    cy = int(h * 0.12)
    r = int(25 * scale)
    for off in [(0, 0), (-20, 5), (20, 5), (-10, -12), (10, -12)]:
        ox = cx + int(off[0] * scale)
        oy = cy + int(off[1] * scale)
        drw.ellipse([ox - r, oy - r, ox + r, oy + r], fill="#FFFFFF", outline="#E0E0E0", width=1)


def _draw_building(drw, w, h, color, scale):
    """Simple building on the right."""
    bx = int(w * 0.78)
    by = int(h * 0.35)
    bw = int(w * 0.15)
    bh = int(h * 0.45)
    drw.rectangle([bx, by, bx + bw, by + bh], fill="#B0BEC5", outline=color, width=2)
    # Windows
    win_s = int(12 * scale)
    gap = int(20 * scale)
    for row in range(4):
        for col in range(2):
            wx = bx + int(15 * scale) + col * gap
            wy = by + int(15 * scale) + row * gap
            drw.rectangle([wx, wy, wx + win_s, wy + win_s], fill="#FFE082", outline=color, width=1)


def _draw_computer(drw, w, h, color, scale):
    """Computer monitor on desk area."""
    cx = int(w * 0.5)
    cy = int(h * 0.68)
    sw = int(40 * scale)
    sh = int(30 * scale)
    # Screen
    drw.rectangle([cx - sw, cy - sh, cx + sw, cy], fill="#1a1a2e", outline=color, width=2)
    # Stand
    drw.rectangle([cx - int(5 * scale), cy, cx + int(5 * scale), cy + int(12 * scale)],
                  fill="#555", outline=color, width=1)
    # Base
    drw.rectangle([cx - int(18 * scale), cy + int(12 * scale), cx + int(18 * scale), cy + int(16 * scale)],
                  fill="#555", outline=color, width=1)


def _draw_chair(drw, w, h, color, scale):
    """Office chair."""
    cx = int(w * 0.55)
    cy = int(h * 0.8)
    # Seat
    drw.rectangle([cx - int(18 * scale), cy, cx + int(18 * scale), cy + int(8 * scale)],
                  fill="#333", outline=color, width=1)
    # Back
    drw.rectangle([cx - int(15 * scale), cy - int(25 * scale), cx + int(15 * scale), cy],
                  fill="#444", outline=color, width=1)
    # Pole
    drw.line([cx, cy + int(8 * scale), cx, cy + int(20 * scale)], fill=color, width=int(3 * scale))


def _draw_stage(drw, w, h, color, scale):
    """Stage/platform at bottom."""
    sy = int(h * 0.82)
    drw.rectangle([0, sy, w, h], fill="#4A2C17", outline=color, width=2)
    # Stage edge highlight
    drw.rectangle([0, sy, w, sy + int(6 * scale)], fill="#8B5E3C")


def _draw_podium(drw, w, h, color, scale):
    """Podium/lectern."""
    px = int(w * 0.35)
    py = int(h * 0.7)
    pw = int(35 * scale)
    ph = int(50 * scale)
    drw.polygon([
        (px - pw, py + ph),
        (px + pw, py + ph),
        (px + int(pw * 0.7), py),
        (px - int(pw * 0.7), py),
    ], fill="#5D3A1A", outline=color, width=2)
    # Mic on podium
    drw.line([px, py - int(5 * scale), px, py - int(25 * scale)], fill=color, width=int(2 * scale))
    drw.ellipse([px - int(4 * scale), py - int(30 * scale), px + int(4 * scale), py - int(22 * scale)],
                fill="#333", outline=color, width=1)


def _draw_lamp(drw, w, h, color, scale):
    """Desk lamp on right."""
    lx = int(w * 0.72)
    ly = int(h * 0.65)
    # Base
    drw.ellipse([lx - int(12 * scale), ly + int(20 * scale), lx + int(12 * scale), ly + int(28 * scale)],
                fill="#333", outline=color, width=1)
    # Arm
    drw.line([lx, ly + int(20 * scale), lx - int(8 * scale), ly], fill=color, width=int(3 * scale))
    # Head
    drw.polygon([
        (lx - int(20 * scale), ly),
        (lx + int(5 * scale), ly),
        (lx - int(8 * scale), ly - int(10 * scale)),
    ], fill="#FFD700", outline=color, width=1)


# ── Speech bubble ──────────────────────────────────────────────────────────

def draw_speech_bubble(
    img: Image.Image,
    text: str,
    position: Tuple[int, int],
    *,
    max_width: int = 350,
    font_size: int = 28,
    bg_color: str = "#FFFFFF",
    text_color: str = "#1a2332",
    border_color: str = "#1a2332",
    tail_direction: str = "bottom_left",  # where the tail points
):
    """Draw a speech bubble with text and a tail pointing to the speaker."""
    if not text.strip():
        return img

    drw = ImageDraw.Draw(img)
    f = _font(font_size)
    if f is None:
        return img

    # Word wrap
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        try:
            bbox = drw.textbbox((0, 0), test, font=f)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(test) * font_size * 0.6
        if tw > max_width and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    if not lines:
        return img

    # Calculate bubble size
    line_height = int(font_size * 1.4)
    bubble_h = len(lines) * line_height + 24
    bubble_w = 0
    for line in lines:
        try:
            bbox = drw.textbbox((0, 0), line, font=f)
            bubble_w = max(bubble_w, bbox[2] - bbox[0])
        except Exception:
            bubble_w = max(bubble_w, int(len(line) * font_size * 0.6))
    bubble_w += 32

    bx, by = position[0], position[1]

    # Draw rounded rectangle bubble
    drw.rounded_rectangle(
        [bx, by, bx + bubble_w, by + bubble_h],
        radius=12,
        fill=bg_color,
        outline=border_color,
        width=2,
    )

    # Draw tail
    tail_size = 12
    if "bottom" in tail_direction:
        tx = bx + bubble_w // 3
        ty = by + bubble_h
        drw.polygon([
            (tx, ty),
            (tx + tail_size, ty),
            (tx + tail_size // 2, ty + tail_size + 5),
        ], fill=bg_color, outline=border_color)
        # Cover the border overlap
        drw.line([(tx + 1, ty), (tx + tail_size - 1, ty)], fill=bg_color, width=3)
    elif "top" in tail_direction:
        tx = bx + bubble_w // 3
        ty = by
        drw.polygon([
            (tx, ty),
            (tx + tail_size, ty),
            (tx + tail_size // 2, ty - tail_size - 5),
        ], fill=bg_color, outline=border_color)
        drw.line([(tx + 1, ty), (tx + tail_size - 1, ty)], fill=bg_color, width=3)

    # Draw text
    text_y = by + 12
    for line in lines:
        drw.text((bx + 16, text_y), line, fill=text_color, font=f)
        text_y += line_height

    return img


# ── Transition effects ─────────────────────────────────────────────────────

def apply_transition(
    img_from: Image.Image,
    img_to: Image.Image,
    t: float,
    effect: str = "fade",
) -> Image.Image:
    """Apply transition between two frames. t = 0..1 (0 = full from, 1 = full to)."""
    t = max(0.0, min(1.0, t))
    w, h = img_to.size

    if effect == "fade":
        return Image.blend(img_from.resize((w, h)), img_to, t)

    elif effect == "slide_left":
        result = Image.new("RGB", (w, h))
        offset = int(w * (1 - t))
        result.paste(img_from.resize((w, h)), (offset - w, 0))
        result.paste(img_to, (offset, 0))
        return result

    elif effect == "slide_up":
        result = Image.new("RGB", (w, h))
        offset = int(h * (1 - t))
        result.paste(img_from.resize((w, h)), (0, offset - h))
        result.paste(img_to, (0, offset))
        return result

    elif effect == "zoom_in":
        # Zoom into img_to
        zoom = 1.0 + (1.0 - t) * 0.3
        zw = int(w * zoom)
        zh = int(h * zoom)
        zoomed = img_to.resize((zw, zh), Image.LANCZOS)
        left = (zw - w) // 2
        top = (zh - h) // 2
        cropped = zoomed.crop((left, top, left + w, top + h))
        return Image.blend(img_from.resize((w, h)), cropped, t)

    else:  # no transition
        return img_to if t >= 0.5 else img_from


# ── Ground/floor ───────────────────────────────────────────────────────────

def draw_ground(
    img: Image.Image,
    style: str = "flat",
    color: str = "#8B7355",
):
    """Draw a simple ground plane at the bottom."""
    drw = ImageDraw.Draw(img)
    w, h = img.size
    gy = int(h * 0.85)

    if style == "flat":
        drw.rectangle([0, gy, w, h], fill=color)
    elif style == "grass":
        drw.rectangle([0, gy, w, h], fill="#4CAF50")
        # Simple grass blades
        for x in range(0, w, 12):
            blade_h = 8 + (x * 7 % 12)
            drw.line([x, gy, x + 3, gy - blade_h], fill="#388E3C", width=2)
    elif style == "floor":
        drw.rectangle([0, gy, w, h], fill="#D2B48C")
        # Floor lines
        for x in range(0, w, 60):
            drw.line([x, gy, x, h], fill="#C19A6B", width=1)
    elif style == "road":
        drw.rectangle([0, gy, w, h], fill="#424242")
        # Center line dashes
        for x in range(0, w, 40):
            drw.rectangle([x, int((gy + h) / 2) - 2, x + 20, int((gy + h) / 2) + 2],
                          fill="#FFC107")

    return img

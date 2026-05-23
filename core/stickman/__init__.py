"""Stickman video renderer — vẽ nhân vật que và export MP4 bằng Pillow + ffmpeg.

Public API:
    list_poses()         -> dict[str, Pose]
    render_preview_png() -> bytes (1 PNG cho 1 pose)
    render_video()       -> Path (MP4)
"""
from .skeleton import POSES, list_poses, get_pose
from .renderer import render_preview_png, draw_frame, interpolate_pose
from .renderer_v2 import draw_frame_v2, render_preview_png_v2, interpolate_pose as interpolate_pose_v2
from .renderer_v3 import draw_frame_v3, render_preview_png_v3
from .animator import render_video, RenderResult, Scene

__all__ = [
    "POSES",
    "list_poses",
    "get_pose",
    "render_preview_png",
    "render_preview_png_v2",
    "render_preview_png_v3",
    "draw_frame",
    "draw_frame_v2",
    "draw_frame_v3",
    "interpolate_pose",
    "render_video",
    "RenderResult",
    "Scene",
]

"""Stickman video renderer — vẽ nhân vật que và export MP4 bằng Pillow + ffmpeg.

Public API:
    list_poses()         -> dict[str, Pose]
    render_preview_png() -> bytes (1 PNG cho 1 pose)
    render_video()       -> Path (MP4)
"""
from .skeleton import POSES, list_poses, get_pose
from .renderer import render_preview_png, draw_frame
from .animator import render_video, RenderResult, Scene

__all__ = [
    "POSES",
    "list_poses",
    "get_pose",
    "render_preview_png",
    "draw_frame",
    "render_video",
    "RenderResult",
    "Scene",
]

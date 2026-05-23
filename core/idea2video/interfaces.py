"""
Data models cho idea2video pipeline — port từ ViMax interfaces.
"""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class CharacterInScene(BaseModel):
    idx: int = Field(description="Index nhân vật, bắt đầu từ 0")
    identifier_in_scene: str = Field(description="Tên/định danh nhân vật trong cảnh")
    is_visible: bool = Field(description="Nhân vật có xuất hiện trong cảnh không")
    static_features: str = Field(
        description="Đặc điểm tĩnh: ngoại hình, vóc dáng, khuôn mặt",
        default="",
    )
    dynamic_features: str = Field(
        description="Đặc điểm động: trang phục, phụ kiện trong cảnh này",
        default="",
    )

    def __str__(self) -> str:
        tag = "[visible]" if self.is_visible else "[not visible]"
        return (
            f"{self.identifier_in_scene}{tag}\n"
            f"static features: {self.static_features}\n"
            f"dynamic features: {self.dynamic_features}\n"
        )


class ShotBriefDescription(BaseModel):
    idx: int = Field(description="Index shot, bắt đầu từ 0")
    is_last: bool = Field(description="Đây có phải shot cuối không")
    cam_idx: int = Field(description="Index camera trong cảnh")
    visual_desc: str = Field(description="Mô tả hình ảnh chi tiết của shot")
    audio_desc: str = Field(description="Mô tả âm thanh của shot", default="")


class ShotDescription(BaseModel):
    idx: int
    is_last: bool
    cam_idx: int
    visual_desc: str
    variation_type: Literal["large", "medium", "small"]
    variation_reason: str
    ff_desc: str = Field(description="Mô tả frame đầu tiên")
    ff_vis_char_idxs: List[int] = Field(default_factory=list)
    lf_desc: str = Field(description="Mô tả frame cuối cùng")
    lf_vis_char_idxs: List[int] = Field(default_factory=list)
    motion_desc: str = Field(description="Mô tả chuyển động trong shot")
    audio_desc: str = Field(default="")

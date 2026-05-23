"""
Agents cho idea2video pipeline — port từ ViMax agents, dùng LLMClient của toolvideo.

Agents:
  - Screenwriter: idea → story → script (list of scene scripts)
  - CharacterExtractor: script → list of CharacterInScene
  - StoryboardArtist: script + characters → storyboard (ShotBriefDescription list)
                      + decompose visual descriptions → ShotDescription
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from .interfaces import CharacterInScene, ShotBriefDescription, ShotDescription
from .llm_client import LLMClient

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Screenwriter
# ══════════════════════════════════════════════════════════════════════════════

_SCREENWRITER_DEVELOP_SYSTEM = """
Bạn là một chuyên gia sáng tác truyện sáng tạo. Nhiệm vụ của bạn là phát triển một câu chuyện hoàn chỉnh, hấp dẫn từ ý tưởng của người dùng.

Đầu ra phải là một câu chuyện có cấu trúc rõ ràng: Mở đầu - Phát triển - Cao trào - Kết thúc.
Ngôn ngữ đầu ra phải khớp với ngôn ngữ đầu vào.
Chỉ trả về nội dung câu chuyện, không thêm chú thích.
"""

_SCREENWRITER_SCRIPT_SYSTEM = """
Bạn là một chuyên gia chuyển thể truyện thành kịch bản phim. Nhiệm vụ là chia câu chuyện thành các cảnh (scenes) và viết kịch bản chi tiết cho từng cảnh.

Trả về JSON theo định dạng:
{"scripts": ["<kịch bản cảnh 1>", "<kịch bản cảnh 2>", ...]}

Mỗi cảnh phải:
- Xảy ra tại cùng một địa điểm và thời gian
- Có mô tả hành động, đối thoại, bối cảnh rõ ràng
- Có thể quay phim được (filmable)
- Ngôn ngữ khớp với ngôn ngữ đầu vào
"""

_CHARACTER_EXTRACTOR_SYSTEM = """
Bạn là chuyên gia phân tích kịch bản phim. Nhiệm vụ là trích xuất tất cả nhân vật từ kịch bản.

Trả về JSON theo định dạng:
{"characters": [
  {
    "idx": 0,
    "identifier_in_scene": "<tên nhân vật>",
    "is_visible": true,
    "static_features": "<đặc điểm ngoại hình cố định: khuôn mặt, vóc dáng, màu tóc...>",
    "dynamic_features": "<trang phục, phụ kiện trong cảnh này>"
  }
]}

Quy tắc:
- Gộp các tên khác nhau của cùng một nhân vật
- Nếu không có tên, dùng đặc điểm nổi bật (ví dụ: "người phụ nữ trẻ")
- Mô tả phải cụ thể, có thể hình dung được (không dùng từ trừu tượng)
- Ngôn ngữ đầu ra khớp với ngôn ngữ kịch bản
"""

_STORYBOARD_SYSTEM = """
Bạn là một storyboard artist chuyên nghiệp. Nhiệm vụ là thiết kế storyboard cho một cảnh phim.

Trả về JSON theo định dạng:
{"storyboard": [
  {
    "idx": 0,
    "is_last": false,
    "cam_idx": 0,
    "visual_desc": "<mô tả hình ảnh chi tiết, loại shot, góc máy, nhân vật, bối cảnh>",
    "audio_desc": "<mô tả âm thanh: nhạc nền, hiệu ứng, lời thoại>"
  }
]}

Quy tắc:
- Mỗi shot phải có mục đích kể chuyện rõ ràng
- Dùng ngôn ngữ điện ảnh: close-up, medium shot, wide shot, pan, tilt...
- Tên nhân vật phải đặt trong <> (ví dụ: <Alice>)
- Mô tả vị trí nhân vật trong khung hình
- Tối thiểu 3 shots, tối đa 12 shots cho một cảnh
- Shot cuối cùng phải có is_last: true
- Ngôn ngữ đầu ra khớp với ngôn ngữ kịch bản
"""

_DECOMPOSE_VISUAL_SYSTEM = """
Bạn là chuyên gia phân tích mô tả hình ảnh điện ảnh. Nhiệm vụ là phân tích một shot thành 3 phần.

Trả về JSON theo định dạng:
{
  "ff_desc": "<mô tả frame đầu tiên - trạng thái tĩnh ban đầu>",
  "ff_vis_char_idxs": [<index nhân vật xuất hiện trong frame đầu>],
  "lf_desc": "<mô tả frame cuối cùng - trạng thái tĩnh kết thúc>",
  "lf_vis_char_idxs": [<index nhân vật xuất hiện trong frame cuối>],
  "motion_desc": "<mô tả chuyển động: camera movement + element movement>",
  "variation_type": "small|medium|large",
  "variation_reason": "<lý do chọn variation_type>"
}

Quy tắc:
- ff_desc và lf_desc phải là "snapshot" tĩnh, không có hành động đang diễn ra
- motion_desc phân biệt rõ camera movement và on-screen movement
- variation_type: small=thay đổi nhỏ, medium=nhân vật mới/quay mặt, large=thay đổi lớn về bố cục
- Ngôn ngữ đầu ra khớp với ngôn ngữ đầu vào
"""


class Screenwriter:
    def __init__(self, llm: LLMClient, provider: str = "auto"):
        self.llm = llm
        self.provider = provider

    def develop_story(self, idea: str, user_requirement: str = "") -> str:
        user = f"Ý tưởng:\n{idea}\n\nYêu cầu:\n{user_requirement or 'Không có yêu cầu đặc biệt'}"
        result = self.llm.chat(
            _SCREENWRITER_DEVELOP_SYSTEM, user,
            provider=self.provider, temperature=0.8, max_tokens=3000, timeout=120,
        )
        if not result:
            raise RuntimeError("Screenwriter: không thể phát triển câu chuyện")
        return result

    def write_script(self, story: str, user_requirement: str = "") -> List[str]:
        user = f"Câu chuyện:\n{story}\n\nYêu cầu:\n{user_requirement or 'Không có yêu cầu đặc biệt'}"
        result = self.llm.chat_json(
            _SCREENWRITER_SCRIPT_SYSTEM, user,
            provider=self.provider, temperature=0.7, max_tokens=4000, timeout=150,
        )
        if not result or not isinstance(result, dict):
            raise RuntimeError("Screenwriter: không thể viết kịch bản")
        scripts = result.get("scripts") or []
        if not scripts:
            raise RuntimeError("Screenwriter: kịch bản trống")
        return [str(s) for s in scripts]


class CharacterExtractor:
    def __init__(self, llm: LLMClient, provider: str = "auto"):
        self.llm = llm
        self.provider = provider

    def extract(self, script: str) -> List[CharacterInScene]:
        user = f"Kịch bản:\n{script}"
        result = self.llm.chat_json(
            _CHARACTER_EXTRACTOR_SYSTEM, user,
            provider=self.provider, temperature=0.3, max_tokens=2000, timeout=90,
        )
        if not result or not isinstance(result, dict):
            logger.warning("CharacterExtractor: không parse được JSON, trả về list rỗng")
            return []
        chars_raw = result.get("characters") or []
        characters = []
        for i, c in enumerate(chars_raw):
            try:
                characters.append(CharacterInScene(
                    idx=c.get("idx", i),
                    identifier_in_scene=str(c.get("identifier_in_scene", f"Character_{i}")),
                    is_visible=bool(c.get("is_visible", True)),
                    static_features=str(c.get("static_features", "")),
                    dynamic_features=str(c.get("dynamic_features", "")),
                ))
            except Exception as e:
                logger.warning("CharacterExtractor: bỏ qua nhân vật %d: %s", i, e)
        return characters


class StoryboardArtist:
    def __init__(self, llm: LLMClient, provider: str = "auto"):
        self.llm = llm
        self.provider = provider

    def design_storyboard(
        self,
        script: str,
        characters: List[CharacterInScene],
        user_requirement: str = "",
    ) -> List[ShotBriefDescription]:
        chars_str = "\n".join(f"Character {c.idx}: {c}" for c in characters)
        user = (
            f"Kịch bản:\n{script}\n\n"
            f"Danh sách nhân vật:\n{chars_str}\n\n"
            f"Yêu cầu:\n{user_requirement or 'Không có yêu cầu đặc biệt'}"
        )
        result = self.llm.chat_json(
            _STORYBOARD_SYSTEM, user,
            provider=self.provider, temperature=0.7, max_tokens=4000, timeout=150,
        )
        if not result or not isinstance(result, dict):
            raise RuntimeError("StoryboardArtist: không parse được storyboard")
        shots_raw = result.get("storyboard") or []
        if not shots_raw:
            raise RuntimeError("StoryboardArtist: storyboard trống")

        shots = []
        for i, s in enumerate(shots_raw):
            try:
                shots.append(ShotBriefDescription(
                    idx=s.get("idx", i),
                    is_last=bool(s.get("is_last", i == len(shots_raw) - 1)),
                    cam_idx=int(s.get("cam_idx", 0)),
                    visual_desc=str(s.get("visual_desc", "")),
                    audio_desc=str(s.get("audio_desc", "")),
                ))
            except Exception as e:
                logger.warning("StoryboardArtist: bỏ qua shot %d: %s", i, e)
        return shots

    def decompose_visual(
        self,
        shot: ShotBriefDescription,
        characters: List[CharacterInScene],
    ) -> ShotDescription:
        chars_str = "\n".join(
            f"{c.identifier_in_scene}: static={c.static_features}; dynamic={c.dynamic_features}"
            for c in characters
        )
        user = (
            f"Mô tả visual của shot:\n{shot.visual_desc}\n\n"
            f"Danh sách nhân vật:\n{chars_str}"
        )
        result = self.llm.chat_json(
            _DECOMPOSE_VISUAL_SYSTEM, user,
            provider=self.provider, temperature=0.3, max_tokens=2000, timeout=90,
        )
        if not result or not isinstance(result, dict):
            # Fallback: dùng visual_desc cho cả ff và lf
            logger.warning("StoryboardArtist.decompose_visual: fallback cho shot %d", shot.idx)
            return ShotDescription(
                idx=shot.idx,
                is_last=shot.is_last,
                cam_idx=shot.cam_idx,
                visual_desc=shot.visual_desc,
                variation_type="small",
                variation_reason="Fallback: không parse được",
                ff_desc=shot.visual_desc,
                ff_vis_char_idxs=[],
                lf_desc=shot.visual_desc,
                lf_vis_char_idxs=[],
                motion_desc="Static camera.",
                audio_desc=shot.audio_desc,
            )

        vt = result.get("variation_type", "small")
        if vt not in ("large", "medium", "small"):
            vt = "small"

        return ShotDescription(
            idx=shot.idx,
            is_last=shot.is_last,
            cam_idx=shot.cam_idx,
            visual_desc=shot.visual_desc,
            variation_type=vt,
            variation_reason=str(result.get("variation_reason", "")),
            ff_desc=str(result.get("ff_desc", shot.visual_desc)),
            ff_vis_char_idxs=[int(x) for x in (result.get("ff_vis_char_idxs") or [])],
            lf_desc=str(result.get("lf_desc", shot.visual_desc)),
            lf_vis_char_idxs=[int(x) for x in (result.get("lf_vis_char_idxs") or [])],
            motion_desc=str(result.get("motion_desc", "Static camera.")),
            audio_desc=shot.audio_desc,
        )

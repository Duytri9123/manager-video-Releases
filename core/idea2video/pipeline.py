"""
Idea2Video Pipeline — kiến trúc ViMax được port vào toolvideo.

Luồng xử lý:
  1. idea → Screenwriter.develop_story() → story text
  2. story → Screenwriter.write_script() → list of scene scripts
  3. Mỗi scene script:
     a. CharacterExtractor.extract() → characters
     b. StoryboardArtist.design_storyboard() → shots (ShotBriefDescription)
     c. StoryboardArtist.decompose_visual() → ShotDescription (ff/lf/motion)
     d. VideoBackend.generate_video() cho từng shot (dùng ff_desc làm prompt)
     e. Concatenate shots → scene video
  4. Concatenate scenes → final video

Tất cả intermediate results được cache vào working_dir để resume được.
Progress được report qua callback progress_cb(pct, message).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .agents import CharacterExtractor, Screenwriter, StoryboardArtist
from .interfaces import CharacterInScene, ShotBriefDescription, ShotDescription
from .llm_client import LLMClient
from .video_backend import create_video_backend

logger = logging.getLogger(__name__)

ProgressCb = Callable[[int, str], None]


class Idea2VideoPipeline:
    """
    Pipeline tạo video từ ý tưởng — kiến trúc ViMax, tích hợp toolvideo.

    Sử dụng:
        pipeline = Idea2VideoPipeline.from_config(cfg, working_dir)
        output_path = pipeline.run(idea, user_requirement, style, progress_cb)
    """

    def __init__(
        self,
        llm: LLMClient,
        video_backend,
        working_dir: Path,
        provider: str = "auto",
    ):
        self.llm = llm
        self.video_backend = video_backend
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider

        self.screenwriter = Screenwriter(llm, provider)
        self.char_extractor = CharacterExtractor(llm, provider)
        self.storyboard_artist = StoryboardArtist(llm, provider)

    @classmethod
    def from_config(cls, cfg: dict, working_dir: str | Path) -> "Idea2VideoPipeline":
        """Tạo pipeline từ config của toolvideo. Ưu tiên: Gemini > 9Router > auto."""
        llm = LLMClient(cfg)
        video_backend = create_video_backend(cfg)

        gv = cfg.get("gemini_video") or {}
        nr = cfg.get("nine_router") or {}

        import os as _os
        gemini_key = (gv.get("api_key") or "").strip() or _os.environ.get("GEMINI_API_KEY", "").strip()
        nr_key = (nr.get("api_key") or "").strip()

        if gemini_key:
            provider = "gemini"
        elif nr_key:
            provider = "9router"
        else:
            provider = "auto"

        logger.info("Idea2VideoPipeline: dùng LLM provider=%s", provider)
        return cls(llm=llm, video_backend=video_backend,
                   working_dir=working_dir, provider=provider)

    def _emit(self, cb: Optional[ProgressCb], pct: int, msg: str):
        logger.info("[%d%%] %s", pct, msg)
        if cb:
            try:
                cb(int(max(0, min(100, pct))), msg)
            except Exception:
                pass

    def _load_json(self, path: Path):
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Step 1: Develop story ─────────────────────────────────────────────────
    def _develop_story(self, idea: str, user_requirement: str, cb: Optional[ProgressCb]) -> str:
        story_path = self.working_dir / "story.txt"
        if story_path.exists():
            self._emit(cb, 5, "Đã có story, bỏ qua bước phát triển câu chuyện.")
            return story_path.read_text(encoding="utf-8")

        self._emit(cb, 3, "Đang phát triển câu chuyện từ ý tưởng...")
        story = self.screenwriter.develop_story(idea, user_requirement)
        story_path.write_text(story, encoding="utf-8")
        self._emit(cb, 8, f"Đã phát triển câu chuyện ({len(story)} ký tự).")
        return story

    # ── Step 2: Write scripts ─────────────────────────────────────────────────
    def _write_scripts(self, story: str, user_requirement: str, cb: Optional[ProgressCb]) -> List[str]:
        scripts_path = self.working_dir / "scripts.json"
        cached = self._load_json(scripts_path)
        if cached and isinstance(cached, list):
            self._emit(cb, 12, f"Đã có {len(cached)} cảnh kịch bản, bỏ qua.")
            return cached

        self._emit(cb, 10, "Đang viết kịch bản từ câu chuyện...")
        scripts = self.screenwriter.write_script(story, user_requirement)
        self._save_json(scripts_path, scripts)
        self._emit(cb, 15, f"Đã viết {len(scripts)} cảnh kịch bản.")
        return scripts

    # ── Step 3: Extract characters ────────────────────────────────────────────
    def _extract_characters(self, script: str, scene_dir: Path, cb: Optional[ProgressCb]) -> List[CharacterInScene]:
        chars_path = scene_dir / "characters.json"
        cached = self._load_json(chars_path)
        if cached and isinstance(cached, list):
            return [CharacterInScene.model_validate(c) for c in cached]

        characters = self.char_extractor.extract(script)
        self._save_json(chars_path, [c.model_dump() for c in characters])
        return characters

    # ── Step 4: Design storyboard ─────────────────────────────────────────────
    def _design_storyboard(
        self, script: str, characters: List[CharacterInScene],
        scene_dir: Path, user_requirement: str, cb: Optional[ProgressCb],
    ) -> List[ShotBriefDescription]:
        sb_path = scene_dir / "storyboard.json"
        cached = self._load_json(sb_path)
        if cached and isinstance(cached, list):
            return [ShotBriefDescription.model_validate(s) for s in cached]

        shots = self.storyboard_artist.design_storyboard(script, characters, user_requirement)
        self._save_json(sb_path, [s.model_dump() for s in shots])
        return shots

    # ── Step 5: Decompose visual descriptions ─────────────────────────────────
    def _decompose_shots(
        self, shots: List[ShotBriefDescription],
        characters: List[CharacterInScene],
        scene_dir: Path, cb: Optional[ProgressCb],
    ) -> List[ShotDescription]:
        results = []
        for shot in shots:
            shot_dir = scene_dir / "shots" / str(shot.idx)
            desc_path = shot_dir / "shot_description.json"
            cached = self._load_json(desc_path)
            if cached:
                results.append(ShotDescription.model_validate(cached))
                continue

            desc = self.storyboard_artist.decompose_visual(shot, characters)
            shot_dir.mkdir(parents=True, exist_ok=True)
            self._save_json(desc_path, desc.model_dump())
            results.append(desc)
        return results

    # ── Step 6: Generate videos per shot ─────────────────────────────────────
    def _generate_shot_video(
        self,
        shot: ShotDescription,
        scene_dir: Path,
        style: str,
        cb: Optional[ProgressCb],
    ) -> Optional[Path]:
        shot_dir = scene_dir / "shots" / str(shot.idx)
        shot_dir.mkdir(parents=True, exist_ok=True)
        video_path = shot_dir / "video.mp4"

        if video_path.exists():
            return video_path

        # Xây dựng prompt từ motion_desc + audio_desc + style
        prompt_parts = []
        if style:
            prompt_parts.append(f"Style: {style}.")
        prompt_parts.append(shot.motion_desc)
        if shot.audio_desc:
            prompt_parts.append(shot.audio_desc)
        prompt = " ".join(prompt_parts)

        # Dùng ff_desc làm image reference nếu có (image-to-video)
        # Ở đây ta dùng text-to-video với prompt kết hợp ff_desc
        full_prompt = f"{shot.ff_desc}\n\n{prompt}"

        def _progress(msg):
            if cb:
                cb(-1, f"Shot {shot.idx}: {msg}")

        ok = self.video_backend.generate_video(
            prompt=full_prompt,
            output_path=video_path,
            progress_cb=_progress,
            duration=5,
        )
        return video_path if ok else None

    # ── Step 7: Concatenate shots → scene video ───────────────────────────────
    def _concat_videos(self, video_paths: List[Path], output_path: Path) -> bool:
        """Ghép các video lại bằng ffmpeg concat demuxer."""
        import shutil as _shutil
        ffmpeg = _shutil.which("ffmpeg") or "ffmpeg"

        listfile = output_path.parent / f"concat_list_{output_path.stem}.txt"
        with open(listfile, "w", encoding="utf-8") as f:
            for p in video_paths:
                f.write(f"file '{p.as_posix()}'\n")

        cmd = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            # Re-encode fallback
            cmd = [
                ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=300)

        try:
            listfile.unlink(missing_ok=True)
        except Exception:
            pass

        return result.returncode == 0 and output_path.exists()

    # ── Main run ──────────────────────────────────────────────────────────────
    def run(
        self,
        idea: str,
        user_requirement: str = "",
        style: str = "cinematic, high quality",
        progress_cb: Optional[ProgressCb] = None,
    ) -> Path:
        """
        Chạy toàn bộ pipeline. Trả về đường dẫn video cuối cùng.
        Raises RuntimeError nếu thất bại.
        """
        cb = progress_cb
        self._emit(cb, 0, "Bắt đầu pipeline idea2video...")

        # ── 1. Story ──────────────────────────────────────────────────────────
        story = self._develop_story(idea, user_requirement, cb)

        # ── 2. Scripts ────────────────────────────────────────────────────────
        scripts = self._write_scripts(story, user_requirement, cb)
        n_scenes = len(scripts)

        all_scene_videos: List[Path] = []

        for scene_idx, script in enumerate(scripts):
            scene_pct_start = 15 + int(75 * scene_idx / n_scenes)
            scene_pct_end = 15 + int(75 * (scene_idx + 1) / n_scenes)
            scene_dir = self.working_dir / f"scene_{scene_idx}"
            scene_dir.mkdir(parents=True, exist_ok=True)
            scene_video_path = scene_dir / "scene_video.mp4"

            if scene_video_path.exists():
                self._emit(cb, scene_pct_end, f"Cảnh {scene_idx + 1}/{n_scenes}: đã có video, bỏ qua.")
                all_scene_videos.append(scene_video_path)
                continue

            self._emit(cb, scene_pct_start, f"Cảnh {scene_idx + 1}/{n_scenes}: trích xuất nhân vật...")

            # ── 3. Characters ─────────────────────────────────────────────────
            characters = self._extract_characters(script, scene_dir, cb)
            self._emit(cb, scene_pct_start + 2, f"Cảnh {scene_idx + 1}: {len(characters)} nhân vật.")

            # ── 4. Storyboard ─────────────────────────────────────────────────
            self._emit(cb, scene_pct_start + 4, f"Cảnh {scene_idx + 1}: thiết kế storyboard...")
            shots_brief = self._design_storyboard(script, characters, scene_dir, user_requirement, cb)
            self._emit(cb, scene_pct_start + 8, f"Cảnh {scene_idx + 1}: {len(shots_brief)} shots.")

            # ── 5. Decompose visual ───────────────────────────────────────────
            self._emit(cb, scene_pct_start + 10, f"Cảnh {scene_idx + 1}: phân tích visual descriptions...")
            shots = self._decompose_shots(shots_brief, characters, scene_dir, cb)

            # ── 6. Generate videos ────────────────────────────────────────────
            shot_videos: List[Path] = []
            n_shots = len(shots)
            for shot_i, shot in enumerate(shots):
                shot_pct = scene_pct_start + 12 + int((scene_pct_end - scene_pct_start - 15) * shot_i / max(1, n_shots))
                self._emit(cb, shot_pct, f"Cảnh {scene_idx + 1}, Shot {shot_i + 1}/{n_shots}: tạo video...")
                video_path = self._generate_shot_video(shot, scene_dir, style, cb)
                if video_path:
                    shot_videos.append(video_path)
                else:
                    logger.warning("Shot %d/%d thất bại, bỏ qua.", shot_i + 1, n_shots)

            if not shot_videos:
                raise RuntimeError(f"Cảnh {scene_idx + 1}: không tạo được video nào")

            # ── 7. Concat shots ───────────────────────────────────────────────
            self._emit(cb, scene_pct_end - 2, f"Cảnh {scene_idx + 1}: ghép {len(shot_videos)} shots...")
            if len(shot_videos) == 1:
                shutil.copy2(shot_videos[0], scene_video_path)
            else:
                ok = self._concat_videos(shot_videos, scene_video_path)
                if not ok:
                    raise RuntimeError(f"Cảnh {scene_idx + 1}: không ghép được shots")

            all_scene_videos.append(scene_video_path)
            self._emit(cb, scene_pct_end, f"Cảnh {scene_idx + 1}/{n_scenes}: hoàn thành.")

        # ── 8. Concat all scenes ──────────────────────────────────────────────
        final_path = self.working_dir / "final_video.mp4"
        if final_path.exists():
            self._emit(cb, 100, f"Video cuối đã có: {final_path.name}")
            return final_path

        self._emit(cb, 92, f"Ghép {len(all_scene_videos)} cảnh thành video cuối...")
        if len(all_scene_videos) == 1:
            shutil.copy2(all_scene_videos[0], final_path)
        else:
            ok = self._concat_videos(all_scene_videos, final_path)
            if not ok:
                raise RuntimeError("Không ghép được các cảnh thành video cuối")

        self._emit(cb, 100, f"Hoàn thành! Video: {final_path.name}")
        return final_path

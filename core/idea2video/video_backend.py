"""
Video backend cho idea2video — dùng Gemini Veo 2 (đã có trong videogen.py).
Hỗ trợ text-to-video và image-to-video.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GeminiVideoBackend:
    """
    Wrapper Gemini Veo 2 cho idea2video pipeline.
    Dùng lại logic từ routes/videogen.py nhưng dưới dạng class có thể gọi trực tiếp.
    """

    def __init__(self, api_key: str, model: str = "veo-2.0-generate-001"):
        self.api_key = api_key
        self.model = model

    def generate_video(
        self,
        prompt: str,
        output_path: Path,
        image_path: Optional[Path] = None,
        aspect_ratio: str = "16:9",
        duration: int = 5,
        max_wait: int = 600,
        progress_cb=None,
    ) -> bool:
        """
        Tạo video từ prompt (và ảnh tham chiếu nếu có).
        Trả về True nếu thành công, False nếu thất bại.
        """
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.error("Thiếu package google-genai. Chạy: pip install google-genai")
            return False

        try:
            client = genai.Client(api_key=self.api_key)

            config = types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                number_of_videos=1,
                duration_seconds=duration,
                person_generation="allow_all",
            )

            if image_path and Path(image_path).exists():
                # Image-to-video
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                import mimetypes
                mime, _ = mimetypes.guess_type(str(image_path))
                mime = mime or "image/png"
                image = types.Image(image_bytes=image_bytes, mime_type=mime)
                if progress_cb:
                    progress_cb(f"Image-to-Video: đang gửi request...")
                operation = client.models.generate_videos(
                    model=self.model,
                    prompt=prompt,
                    image=image,
                    config=config,
                )
            else:
                # Text-to-video
                if progress_cb:
                    progress_cb(f"Text-to-Video: đang gửi request...")
                operation = client.models.generate_videos(
                    model=self.model,
                    prompt=prompt,
                    config=config,
                )

            # Poll until done
            start = time.time()
            while not operation.done:
                if time.time() - start > max_wait:
                    logger.error("GeminiVideoBackend: timeout sau %ds", max_wait)
                    return False
                time.sleep(10)
                operation = client.operations.get(operation)
                elapsed = int(time.time() - start)
                if progress_cb:
                    progress_cb(f"Đang xử lý... ({elapsed}s)")

            if operation.error:
                logger.error("GeminiVideoBackend: lỗi API: %s", operation.error)
                return False

            if not (operation.result and operation.result.generated_videos):
                logger.error("GeminiVideoBackend: không có video được tạo")
                return False

            # Lưu video đầu tiên
            gv = operation.result.generated_videos[0]
            video_data = client.files.download(file=gv.video)
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(video_data)

            logger.info("GeminiVideoBackend: đã lưu video tại %s", output_path)
            return True

        except Exception as e:
            logger.error("GeminiVideoBackend: lỗi: %s", e, exc_info=True)
            return False


class MockVideoBackend:
    """
    Backend giả lập cho testing — tạo video placeholder bằng ffmpeg.
    Dùng khi không có Gemini API key.
    """

    def __init__(self, ffmpeg_path: Optional[str] = None):
        import shutil
        self.ffmpeg = ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg"

    def generate_video(
        self,
        prompt: str,
        output_path: Path,
        image_path: Optional[Path] = None,
        aspect_ratio: str = "16:9",
        duration: int = 5,
        max_wait: int = 60,
        progress_cb=None,
    ) -> bool:
        """Tạo video placeholder từ ảnh hoặc màu đen."""
        import subprocess
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if progress_cb:
            progress_cb(f"MockBackend: tạo video placeholder...")

        try:
            if image_path and Path(image_path).exists():
                cmd = [
                    self.ffmpeg, "-y",
                    "-loop", "1", "-t", str(duration), "-i", str(image_path),
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-r", "24", "-an", str(output_path),
                ]
            else:
                cmd = [
                    self.ffmpeg, "-y",
                    "-f", "lavfi", "-i", f"color=black:size=1280x720:duration={duration}:rate=24",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-an", str(output_path),
                ]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            return result.returncode == 0 and output_path.exists()
        except Exception as e:
            logger.error("MockVideoBackend: lỗi: %s", e)
            return False


def create_video_backend(cfg: dict):
    """
    Factory: tạo video backend phù hợp dựa trên config.
    Ưu tiên Gemini Veo 2, fallback sang Mock nếu không có key.
    """
    gemini_cfg = cfg.get("gemini_video") or {}
    api_key = (gemini_cfg.get("api_key") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    model = gemini_cfg.get("model") or "veo-2.0-generate-001"

    if api_key:
        logger.info("idea2video: dùng Gemini Veo 2 backend (model=%s)", model)
        return GeminiVideoBackend(api_key=api_key, model=model)
    else:
        logger.warning("idea2video: không có Gemini API key, dùng MockVideoBackend")
        return MockVideoBackend()

"""Manga → video renderer.

Pipeline (synchronous, ffmpeg-based):

    1. Take a list of "panels" (each is a manga page image) and matching
       narration segments (one block of text per panel).
    2. Synthesize TTS for each narration segment with the chosen engine.
    3. Use the actual TTS duration of each clip as the panel's screen time.
    4. Build a Ken Burns video clip per panel (slow zoom + slight pan), then
       concat all clips.
    5. Stitch the TTS clips with a small inter-segment pause to align with
       the video timeline; build a single voiceover track.
    6. Build an ASS / SRT subtitle file from the same timeline (one line per
       narration block) so the user has both styled subtitles and a clean
       SRT to publish on YouTube.
    7. Burn the ASS subtitles into the final MP4 (optional) and mux the
       voiceover.

Use ``MangaRenderRequest`` + ``MangaVideoRenderer.render()`` for blocking
calls, or ``render_async()`` to run in a background thread with progress.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from core.mangadex_client import _http_download
from core.subtitle_io import write_ass, write_srt


# ── ffmpeg discovery (mirrors core/movie_video.find_ffmpeg) ──────────────────
def find_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise RuntimeError(
        "Không tìm thấy ffmpeg. Cài ffmpeg và thêm vào PATH, hoặc "
        "`pip install imageio-ffmpeg`."
    )


# ── ffprobe duration ────────────────────────────────────────────────────────
def _probe_duration(ffmpeg: str, path: Path) -> float:
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
        if not m:
            return 0.0
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + float(s)
    except Exception:
        return 0.0


# ── TTS providers ──────────────────────────────────────────────────────────
async def _tts_edge(text: str, voice: str, out_path: Path,
                    rate: str = "+0%", pitch: str = "+0Hz") -> bool:
    try:
        import edge_tts
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await comm.save(str(out_path))
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _tts_gtts(text: str, lang: str, out_path: Path) -> bool:
    try:
        from gtts import gTTS
        gTTS(text=text, lang=lang).save(str(out_path))
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


async def _tts_fpt(text: str, voice: str, out_path: Path,
                   api_key: str, speed: int = 0) -> bool:
    if not api_key:
        return False
    try:
        from core.video_processor import _tts_fpt_ai  # type: ignore
        return await _tts_fpt_ai(text, voice, out_path, api_key, speed)
    except Exception:
        return False


def _synthesize(
    text: str,
    *,
    engine: str,
    voice: str,
    lang: str,
    rate: str,
    pitch: str,
    fpt_api_key: str,
    fpt_speed: int,
    out_path: Path,
) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    eng = (engine or "").lower()
    if eng in ("edge-tts", "edge"):
        if asyncio.run(_tts_edge(text, voice, out_path, rate=rate, pitch=pitch)):
            return True
    elif eng in ("fpt-ai", "fpt"):
        if asyncio.run(_tts_fpt(text, voice, out_path, fpt_api_key, fpt_speed)):
            return True
    elif eng == "gtts":
        if _tts_gtts(text, lang, out_path):
            return True
    # Universal fallback: gTTS
    return _tts_gtts(text, lang or "vi", out_path)


# ── Render request ──────────────────────────────────────────────────────────
@dataclass
class PanelInput:
    """A single manga page + the narration text shown on it."""
    image_url: str
    text: str


@dataclass
class MangaRenderRequest:
    panels: List[PanelInput]
    title: str = ""
    width: int = 1080
    height: int = 1920          # default Shorts/TikTok portrait — manga is portrait by nature
    fps: int = 30
    # Subtitle / TTS
    subtitle_format: str = "ass"      # "ass" or "srt"
    burn_subtitles: bool = True       # burn ASS into the video
    target_lang: str = "vi"
    tts_engine: str = "edge-tts"
    tts_voice: str = "vi-VN-HoaiMyNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    fpt_api_key: str = ""
    fpt_speed: int = 0
    # Video timing
    min_panel_sec: float = 2.0        # if a panel has no/short narration
    inter_panel_pause_sec: float = 0.25
    intro_sec: float = 0.8
    outro_sec: float = 1.2
    zoom: bool = True                 # Ken Burns
    bgm_url: str = ""
    bgm_volume: float = 0.10
    # ASS styling
    title_text: str = ""
    title_bar_color: str = "#1A73E8"
    font_name: str = "Arial"
    font_size: int = 48
    font_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    # Output
    output_dir: Path = field(default_factory=lambda: Path("./Downloaded/manga_videos"))
    output_name: str = ""
    proxy_url: str = ""


# ── Renderer ────────────────────────────────────────────────────────────────
ProgressCb = Callable[[int, str], None]


class MangaVideoRenderer:
    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg = ffmpeg_path or find_ffmpeg()
        # Detect hardware encoder once (NVENC / QSV / AMF / libx264 fallback)
        # This mirrors what core/video_processor.py does for the regular
        # video pipeline — gives 3-5× speedup on machines with GPU.
        self._hw_preset = None
        try:
            from core.hardware_presets import get_optimal_preset
            self._hw_preset = get_optimal_preset(self.ffmpeg)
        except Exception:
            self._hw_preset = None

    def _video_encode_args(self) -> list:
        """Return ['-c:v', codec, '-preset', ..., ...] respecting detected hw."""
        if self._hw_preset:
            try:
                # build_output_args() returns full output args incl. audio.
                # We only want video portion → strip audio bits we'll add later.
                full = self._hw_preset.build_output_args()
                # Keep only video-side flags (codec + preset/crf + extras)
                v_args = []
                skip = False
                for i, a in enumerate(full):
                    if skip:
                        skip = False
                        continue
                    if a in ("-c:a", "-b:a", "-ar", "-ac"):
                        skip = True
                        continue
                    v_args.append(a)
                return v_args
            except Exception:
                pass
        # CPU fallback
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-tune", "stillimage"]

    def _emit(self, cb: Optional[ProgressCb], pct: int, msg: str):
        if cb:
            try:
                cb(int(max(0, min(100, pct))), msg)
            except Exception:
                pass

    # ── Main entry ───────────────────────────────────────────────────────
    def render(
        self,
        req: MangaRenderRequest,
        *,
        progress: Optional[ProgressCb] = None,
    ) -> dict:
        if not req.panels:
            raise ValueError("Cần ít nhất 1 panel.")

        req.output_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        safe_title = re.sub(r"[\\/:*?\"<>|]", "_", req.title or "manga_video").strip(" .")
        if not safe_title:
            safe_title = "manga_video"
        out_name = req.output_name or f"{safe_title}_{ts}.mp4"
        out_video = req.output_dir / out_name
        out_srt = req.output_dir / (Path(out_name).stem + ".srt")
        out_ass = req.output_dir / (Path(out_name).stem + ".ass")

        with tempfile.TemporaryDirectory(prefix="duytris_manga_") as tmp_str:
            tmp = Path(tmp_str)
            self._emit(progress, 2, "Chuẩn bị thư mục tạm...")

            # Show which hardware encoder we're using (helps user debug speed)
            if self._hw_preset:
                self._emit(progress, 2,
                           f"Hardware encoder: {self._hw_preset.video_codec} "
                           f"(profile: {self._hw_preset.machine_profile})")
            else:
                self._emit(progress, 2, "Encoder: libx264 (CPU only)")

            # ── 1. Download panel images ───────────────────────────────
            img_paths: List[Path] = []
            n_panels = len(req.panels)
            for i, panel in enumerate(req.panels, start=1):
                src = panel.image_url
                # Local file path → just copy/symlink it instead of HTTP download
                is_remote = src.startswith(("http://", "https://", "ftp://"))
                ext = Path(urllib.parse.urlparse(src).path if is_remote else src).suffix or ".jpg"
                dst = tmp / f"panel_{i:03d}{ext}"
                if is_remote:
                    ok = _http_download(src, dst,
                                        timeout=30, proxy_url=req.proxy_url or None)
                else:
                    # Local file: copy bytes directly
                    try:
                        local = Path(src)
                        if local.exists() and local.is_file():
                            import shutil as _shutil
                            _shutil.copyfile(local, dst)
                            ok = dst.exists() and dst.stat().st_size > 0
                        else:
                            ok = False
                    except Exception:
                        ok = False
                if ok:
                    img_paths.append(dst)
                else:
                    img_paths.append(None)  # placeholder so indices align with panels
                self._emit(progress, 2 + int(18 * i / max(1, n_panels)),
                           f"Tải panel {i}/{n_panels}")
            if not any(img_paths):
                raise RuntimeError("Không tải được panel nào — kiểm tra mạng / proxy.")

            # ── 2. Synthesize TTS for each panel ───────────────────────
            tts_files: List[Optional[Path]] = []
            tts_durations: List[float] = []
            for i, panel in enumerate(req.panels, start=1):
                p = tmp / f"tts_{i:03d}.mp3"
                if (panel.text or "").strip():
                    ok = _synthesize(
                        panel.text,
                        engine=req.tts_engine, voice=req.tts_voice,
                        lang=req.target_lang, rate=req.tts_rate,
                        pitch=req.tts_pitch, fpt_api_key=req.fpt_api_key,
                        fpt_speed=req.fpt_speed, out_path=p,
                    )
                else:
                    ok = False
                if ok and p.exists() and p.stat().st_size > 0:
                    dur = _probe_duration(self.ffmpeg, p)
                    if dur < 0.2:
                        dur = req.min_panel_sec
                    tts_files.append(p)
                    tts_durations.append(max(req.min_panel_sec, dur))
                else:
                    # Silent panel: keep displayed for min_panel_sec
                    tts_files.append(None)
                    tts_durations.append(req.min_panel_sec)
                self._emit(progress, 20 + int(35 * i / max(1, n_panels)),
                           f"TTS panel {i}/{n_panels}")

            # ── 3. Build subtitle timeline ──────────────────────────────
            segments: List[dict] = []
            cursor = req.intro_sec
            for i, panel in enumerate(req.panels):
                dur = tts_durations[i]
                start = cursor
                end = cursor + dur
                segments.append({
                    "start": start,
                    "end": end,
                    "text": (panel.text or "").strip(),
                    "panel_index": i,
                })
                cursor = end + req.inter_panel_pause_sec
            total_video_dur = cursor + max(0.0, req.outro_sec)

            # Always write SRT (cheap, useful)
            try:
                write_srt(segments, out_srt)
            except Exception:
                pass

            # ASS file is mandatory if we plan to burn subs
            try:
                write_ass(
                    segments,
                    out_ass,
                    play_res_x=req.width,
                    play_res_y=req.height,
                    font_name=req.font_name,
                    font_size=req.font_size,
                    font_color=req.font_color,
                    outline_color=req.outline_color,
                    title_text=req.title_text or req.title,
                    title_bar_color=req.title_bar_color,
                )
            except Exception:
                pass
            self._emit(progress, 58, "Đã tạo file phụ đề SRT/ASS.")

            # ── 4. Build per-panel video clips ─────────────────────────
            segs: List[Path] = []
            placeholder = self._make_placeholder(tmp, req)

            # Build the list of segment jobs first
            seg_jobs = []
            for i, (img, dur) in enumerate(zip(img_paths, tts_durations), start=1):
                seg_dur = dur + (req.inter_panel_pause_sec if i < n_panels else 0.0)
                if i == 1:
                    seg_dur += req.intro_sec
                if i == n_panels:
                    seg_dur += req.outro_sec
                seg_path = tmp / f"seg_{i:03d}.mp4"
                src_img = img if img and img.exists() else placeholder
                seg_jobs.append((i, src_img, seg_dur, seg_path))
                segs.append(seg_path)

            # Parallel ffmpeg encoding — significant speedup on multi-core CPU.
            # Use up to min(N panels, 4) workers; hardware encoders (NVENC etc)
            # serialize internally so going much higher doesn't help.
            max_workers = min(len(seg_jobs), 4) if seg_jobs else 1
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                completed = 0
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = {
                        ex.submit(self._make_segment, src, dur, req, path): idx
                        for idx, src, dur, path in seg_jobs
                    }
                    for fut in as_completed(futures):
                        idx = futures[fut]
                        # Surface any exception so the job fails fast
                        fut.result()
                        completed += 1
                        self._emit(progress, 60 + int(20 * completed / n_panels),
                                   f"Render đoạn video {completed}/{n_panels}")
            except Exception:
                # If parallel path had any setup issue, fall back to serial
                for idx, src, dur, path in seg_jobs:
                    self._make_segment(src, dur, req, path)
                    self._emit(progress, 60 + int(20 * idx / n_panels),
                               f"Render đoạn video {idx}/{n_panels}")

            # ── 5. Concat segments ─────────────────────────────────────
            concat_video = tmp / "concat.mp4"
            self._concat(segs, concat_video)
            self._emit(progress, 82, "Đã ghép các đoạn.")

            # ── 6. Stitch voiceover ────────────────────────────────────
            voiceover = tmp / "voiceover.m4a"
            self._stitch_audio(tts_files, tts_durations, req, voiceover, tmp)
            self._emit(progress, 88, "Đã tạo voiceover.")

            # ── 7. Burn subtitles + mux audio ──────────────────────────
            bgm_path = self._prepare_bgm(req.bgm_url, tmp) if req.bgm_url else None
            self._mux_final(concat_video, voiceover, bgm_path, req,
                            out_ass if req.burn_subtitles else None,
                            out_video)
            self._emit(progress, 100, f"Hoàn tất: {out_video.name}")

            return {
                "video": str(out_video),
                "srt": str(out_srt) if out_srt.exists() else "",
                "ass": str(out_ass) if out_ass.exists() else "",
                "panel_count": n_panels,
                "duration_sec": round(total_video_dur, 2),
            }

    # ── Helpers ──────────────────────────────────────────────────────────
    def _make_placeholder(self, tmp: Path, req: MangaRenderRequest) -> Path:
        """Render a black-frame fallback for panels that failed to download."""
        p = tmp / "_placeholder.png"
        cmd = [
            self.ffmpeg, "-y", "-f", "lavfi",
            "-i", f"color=c=#0a0a0a:s={req.width}x{req.height}",
            "-frames:v", "1", str(p),
        ]
        subprocess.run(cmd, capture_output=True)
        return p

    def _make_segment(
        self,
        img: Path,
        duration: float,
        req: MangaRenderRequest,
        out: Path,
    ):
        """Render a single image → mp4 with optional Ken Burns zoom-in.

        Uses hardware encoding when available (NVENC / QSV / AMF) — same as the
        regular video processor does. Falls back to libx264 veryfast on plain CPU.
        """
        d = max(0.5, float(duration))
        total_frames = max(1, int(d * req.fps))
        if req.zoom:
            # 1.3× pre-scale is enough for Ken Burns (was 2× → 4× more pixels
            # to encode for almost no visible quality gain). Big speedup.
            sw, sh = int(req.width * 1.3), int(req.height * 1.3)
            vf = (
                f"scale={sw}:{sh}:force_original_aspect_ratio=decrease,"
                f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:black,"
                f"zoompan=z='min(zoom+0.0009,1.15)':d={total_frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"s={req.width}x{req.height}:fps={req.fps},"
                f"format=yuv420p"
            )
        else:
            vf = (
                f"scale={req.width}:{req.height}:force_original_aspect_ratio=decrease,"
                f"pad={req.width}:{req.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"format=yuv420p"
            )
        # Build command: hwaccel input flags first, then encode args from preset
        cmd = [self.ffmpeg, "-y", "-loop", "1", "-t", f"{d:.3f}", "-i", str(img),
               "-vf", vf, "-r", str(req.fps)]
        cmd += self._video_encode_args()
        cmd += ["-an", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            # If hardware encode failed, retry with libx264 once
            if self._hw_preset and "libx264" not in cmd:
                cmd_fallback = [self.ffmpeg, "-y", "-loop", "1", "-t", f"{d:.3f}",
                                "-i", str(img), "-vf", vf, "-r", str(req.fps),
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                "-pix_fmt", "yuv420p", "-an", str(out)]
                proc2 = subprocess.run(cmd_fallback, capture_output=True, text=True)
                if proc2.returncode == 0:
                    return
                raise RuntimeError(
                    "ffmpeg segment build failed (both HW + SW): "
                    + (proc2.stderr or proc.stderr or "")[-1500:]
                )
            raise RuntimeError(
                "ffmpeg segment build failed: " + (proc.stderr or "")[-1500:]
            )

    def _concat(self, parts: List[Path], out: Path):
        listfile = out.parent / "concat_list.txt"
        with open(listfile, "w", encoding="utf-8") as f:
            for p in parts:
                f.write(f"file '{p.as_posix()}'\n")
        cmd = [
            self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c", "copy", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            cmd = [
                self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile), "-c:v", "libx264", "-preset", "medium",
                "-crf", "20", "-pix_fmt", "yuv420p", str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True)

    def _silence(self, seconds: float, dst: Path) -> Path:
        cmd = [
            self.ffmpeg, "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{max(0.05, seconds):.3f}",
            "-c:a", "aac", "-b:a", "128k", str(dst),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return dst

    def _stitch_audio(
        self,
        tts_files: List[Optional[Path]],
        durations: List[float],
        req: MangaRenderRequest,
        out: Path,
        tmp: Path,
    ):
        """Glue TTS clips with silence padding to match the panel timeline."""
        listfile = tmp / "audio_list.txt"
        sil_idx = 0

        def _add_silence(seconds: float) -> Path:
            nonlocal sil_idx
            sil_idx += 1
            return self._silence(seconds, tmp / f"sil_{sil_idx:03d}.m4a")

        with open(listfile, "w", encoding="utf-8") as f:
            if req.intro_sec > 0.05:
                f.write(f"file '{_add_silence(req.intro_sec).as_posix()}'\n")
            for i, (tts, dur) in enumerate(zip(tts_files, durations)):
                if tts and tts.exists():
                    f.write(f"file '{tts.as_posix()}'\n")
                else:
                    # Silent panel
                    f.write(f"file '{_add_silence(dur).as_posix()}'\n")
                # Inter-panel pause
                if i < len(tts_files) - 1 and req.inter_panel_pause_sec > 0.05:
                    f.write(f"file '{_add_silence(req.inter_panel_pause_sec).as_posix()}'\n")
            if req.outro_sec > 0.05:
                f.write(f"file '{_add_silence(req.outro_sec).as_posix()}'\n")

        cmd = [
            self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(listfile), "-c:a", "aac", "-b:a", "192k", str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)

    def _prepare_bgm(self, url_or_path: str, tmp: Path) -> Optional[Path]:
        if not url_or_path:
            return None
        if url_or_path.startswith(("http://", "https://")):
            ext = ".mp3" if ".mp3" in url_or_path.lower() else ".m4a"
            p = tmp / ("bgm" + ext)
            ok = _http_download(url_or_path, p)
            return p if ok else None
        local = Path(url_or_path)
        return local if local.exists() else None

    def _mux_final(
        self,
        video: Path,
        voiceover: Path,
        bgm: Optional[Path],
        req: MangaRenderRequest,
        ass_path: Optional[Path],
        out: Path,
    ):
        # Burn subtitles via the subtitles filter when requested.
        # The ASS filename has to be properly escaped for ffmpeg's filter
        # graph, especially on Windows where colons in the path break parsing.
        sub_filter = ""
        if ass_path and ass_path.exists():
            ass_str = str(ass_path).replace("\\", "/")
            ass_str = ass_str.replace(":", "\\:")
            sub_filter = f"subtitles='{ass_str}'"

        # If we need to burn subs, we must re-encode the video.
        if sub_filter and bgm and bgm.exists():
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video),
                "-i", str(voiceover),
                "-stream_loop", "-1", "-i", str(bgm),
                "-filter_complex",
                f"[0:v]{sub_filter}[v];"
                f"[2:a]volume={req.bgm_volume:.3f},aloop=loop=-1:size=2e+09[bg];"
                f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[v]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        elif sub_filter:
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video), "-i", str(voiceover),
                "-filter_complex", f"[0:v]{sub_filter}[v]",
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        elif bgm and bgm.exists():
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video),
                "-i", str(voiceover),
                "-stream_loop", "-1", "-i", str(bgm),
                "-filter_complex",
                f"[2:a]volume={req.bgm_volume:.3f},aloop=loop=-1:size=2e+09[bg];"
                f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        else:
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video), "-i", str(voiceover),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "ffmpeg final mux failed: " + (proc.stderr or "")[-1500:]
            )


# ── Job manager (background rendering) ──────────────────────────────────────
@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    progress: int = 0
    message: str = ""
    error: str = ""
    output_video: str = ""
    output_srt: str = ""
    output_ass: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


class JobManager:
    def __init__(self):
        self._jobs: dict = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        jid = uuid.uuid4().hex[:12]
        job = Job(id=jid)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, jid: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(jid)

    def update(self, jid: str, **fields):
        with self._lock:
            j = self._jobs.get(jid)
            if not j:
                return
            for k, v in fields.items():
                if hasattr(j, k):
                    setattr(j, k, v)


_JM: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _JM
    if _JM is None:
        _JM = JobManager()
    return _JM


def render_async(req: MangaRenderRequest) -> str:
    jm = get_job_manager()
    job = jm.create()

    def _runner():
        jm.update(job.id, status="running", started_at=time.time())
        try:
            renderer = MangaVideoRenderer()

            def cb(p, m):
                jm.update(job.id, progress=p, message=m)

            res = renderer.render(req, progress=cb)
            jm.update(
                job.id,
                status="done",
                progress=100,
                message="Hoàn tất.",
                output_video=res.get("video", ""),
                output_srt=res.get("srt", ""),
                output_ass=res.get("ass", ""),
                finished_at=time.time(),
            )
        except Exception as e:
            import traceback as _tb
            tb_text = _tb.format_exc()
            try:
                from core_app import LOGGER as _LOG
                _LOG.error("Manga render failed for job %s:\n%s", job.id, tb_text)
            except Exception:
                pass
            jm.update(
                job.id,
                status="error",
                error=f"{type(e).__name__}: {e}",
                message="Lỗi: " + str(e)[:200],
                finished_at=time.time(),
            )

    threading.Thread(target=_runner, daemon=True).start()
    return job.id

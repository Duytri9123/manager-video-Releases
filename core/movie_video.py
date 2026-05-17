"""
Movie review video renderer.

Pipeline (synchronous, ffmpeg-based):

  1. Split the script into "lines" (one paragraph or one sentence per line).
  2. Synthesize TTS for each line → individual MP3 (edge-tts preferred,
     gTTS fallback). Concatenate to a single voiceover track.
  3. Download all images via HTTP into a temp dir.
  4. For each TTS segment, allocate one image (round-robin).
     Build per-segment ffmpeg input: image → scale + zoom-in (Ken Burns).
  5. Concatenate segments with crossfade (xfade), then mux with the
     concatenated voiceover and (optionally) a background music track.

Outputs an MP4 in the user-configured directory and returns its path.

Designed to be called from a background thread so the HTTP request can
return immediately. Progress is reported via a callback `progress(pct, msg)`.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


# ── ffmpeg discovery ─────────────────────────────────────────────────────────
def find_ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    # imageio_ffmpeg fallback
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise RuntimeError("Không tìm thấy ffmpeg. Cài ffmpeg và thêm vào PATH, hoặc pip install imageio-ffmpeg.")


# ── HTTP image download ──────────────────────────────────────────────────────
def _download(url: str, dest: Path, timeout: int = 30) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DuyTris-MovieVideo/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        return dest.exists() and dest.stat().st_size > 0
    except Exception:
        return False


# ── TTS ──────────────────────────────────────────────────────────────────────
async def _tts_edge(text: str, voice: str, out_path: Path, rate: str = "+0%") -> bool:
    try:
        import edge_tts
        comm = edge_tts.Communicate(text, voice, rate=rate)
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


async def _tts_fpt(text: str, voice: str, out_path: Path, api_key: str,
                   speed: int = 0) -> bool:
    """Reuse the FPT TTS implementation in core.video_processor."""
    if not api_key:
        return False
    try:
        from core.video_processor import _tts_fpt_ai  # type: ignore
        return await _tts_fpt_ai(text, voice, out_path, api_key, speed)
    except Exception:
        return False


def _synthesize_line(text: str, *, engine: str, voice: str, lang: str,
                     rate: str, out_path: Path,
                     fpt_api_key: str = "", fpt_speed: int = 0) -> bool:
    """Try `engine` first, fallback to gTTS."""
    text = (text or "").strip()
    if not text:
        return False
    eng = (engine or "").lower()
    if eng in ("edge-tts", "edge"):
        if asyncio.run(_tts_edge(text, voice, out_path, rate=rate)):
            return True
    elif eng in ("fpt-ai", "fpt"):
        if asyncio.run(_tts_fpt(text, voice, out_path, fpt_api_key, fpt_speed)):
            return True
    elif eng == "gtts":
        if _tts_gtts(text, lang, out_path):
            return True
    # Universal fallback
    return _tts_gtts(text, lang or "vi", out_path)


# ── ffprobe duration ─────────────────────────────────────────────────────────
def _probe_duration(ffmpeg: str, path: Path) -> float:
    """Use `ffmpeg -i` (stderr parse) to read duration; avoids needing ffprobe."""
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


# ── Script splitter ──────────────────────────────────────────────────────────
def split_script_into_lines(script: str, *, max_chars: int = 220) -> List[str]:
    """One line ≈ 1 paragraph. Long paragraphs get split on sentence boundary."""
    if not script:
        return []
    paras = [p.strip() for p in re.split(r"\n{2,}", script.strip()) if p.strip()]
    out: List[str] = []
    for p in paras:
        if len(p) <= max_chars:
            out.append(p)
            continue
        # Split sentences
        sents = re.split(r"(?<=[\.!?。！？])\s+", p)
        buf = ""
        for s in sents:
            s = s.strip()
            if not s:
                continue
            if buf and len(buf) + 1 + len(s) > max_chars:
                out.append(buf)
                buf = s
            else:
                buf = (buf + " " + s).strip() if buf else s
        if buf:
            out.append(buf)
    return out


# ── Render request ───────────────────────────────────────────────────────────
@dataclass
class RenderRequest:
    script: str
    image_urls: List[str]
    title: str = ""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    tts_engine: str = "edge-tts"
    tts_voice: str = "vi-VN-HoaiMyNeural"
    tts_lang: str = "vi"
    tts_rate: str = "+0%"
    fpt_api_key: str = ""
    fpt_speed: int = 0          # FPT TTS speed: -3..3
    bgm_url: str = ""           # optional URL or local path
    bgm_volume: float = 0.12
    crossfade_sec: float = 0.6
    intro_sec: float = 1.5
    outro_sec: float = 1.8
    zoom: bool = True           # Ken Burns
    output_dir: Path = field(default_factory=lambda: Path("./Downloaded/movie_videos"))
    output_name: str = ""       # auto-generated if empty


# ── Renderer ────────────────────────────────────────────────────────────────
ProgressCb = Callable[[int, str], None]


class MovieVideoRenderer:
    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg = ffmpeg_path or find_ffmpeg()

    def _emit(self, cb: Optional[ProgressCb], pct: int, msg: str):
        if cb:
            try:
                cb(int(max(0, min(100, pct))), msg)
            except Exception:
                pass

    def render(self, req: RenderRequest, *, progress: Optional[ProgressCb] = None) -> Path:
        if not req.script.strip():
            raise ValueError("Kịch bản trống.")
        if not req.image_urls:
            raise ValueError("Cần ít nhất 1 ảnh để render.")

        req.output_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        safe_title = re.sub(r"[\\/:*?\"<>|]", "_", req.title or "movie_review").strip(" .") or "movie_review"
        out_name = req.output_name or f"{safe_title}_{ts}.mp4"
        out_path = req.output_dir / out_name

        with tempfile.TemporaryDirectory(prefix="duytris_mv_") as tmp_str:
            tmp = Path(tmp_str)
            self._emit(progress, 5, "Chuẩn bị thư mục tạm...")

            # ── 1. Synthesize TTS per line ───────────────────────────────
            lines = split_script_into_lines(req.script)
            if not lines:
                raise ValueError("Không tách được câu nào từ kịch bản.")
            tts_files: List[Path] = []
            tts_durations: List[float] = []
            for i, line in enumerate(lines, start=1):
                self._emit(progress, 5 + int(40 * (i - 1) / max(1, len(lines))),
                           f"TTS đoạn {i}/{len(lines)}: {line[:60]}...")
                p = tmp / f"tts_{i:03d}.mp3"
                ok = _synthesize_line(line, engine=req.tts_engine, voice=req.tts_voice,
                                      lang=req.tts_lang, rate=req.tts_rate,
                                      fpt_api_key=req.fpt_api_key,
                                      fpt_speed=req.fpt_speed,
                                      out_path=p)
                if not ok:
                    continue
                dur = _probe_duration(self.ffmpeg, p)
                if dur < 0.2:
                    continue
                tts_files.append(p)
                tts_durations.append(dur)
            if not tts_files:
                raise RuntimeError("TTS thất bại cho tất cả các đoạn. Kiểm tra mạng / engine.")
            self._emit(progress, 45, f"Đã tạo TTS cho {len(tts_files)} đoạn.")

            # ── 2. Download images ───────────────────────────────────────
            img_paths: List[Path] = []
            for i, url in enumerate(req.image_urls, start=1):
                ext = ".jpg"
                tail = urllib.parse.urlparse(url).path.lower()
                for cand in (".jpg", ".jpeg", ".png", ".webp"):
                    if tail.endswith(cand):
                        ext = cand
                        break
                p = tmp / f"img_{i:03d}{ext}"
                if _download(url, p):
                    img_paths.append(p)
                self._emit(progress, 45 + int(15 * i / max(1, len(req.image_urls))),
                           f"Tải ảnh {i}/{len(req.image_urls)}")
            if not img_paths:
                raise RuntimeError("Không tải được ảnh nào.")

            # ── 3. Build per-segment video clips ─────────────────────────
            segs: List[Path] = []
            seg_durs: List[float] = []
            n_imgs = len(img_paths)
            n_segs = len(tts_files)
            for i, (audio, dur) in enumerate(zip(tts_files, tts_durations)):
                # Allocate a different image to each consecutive segment
                img = img_paths[i % n_imgs]
                seg_dur = dur + (req.crossfade_sec if i > 0 else 0.0)
                if i == 0:
                    seg_dur += req.intro_sec
                if i == n_segs - 1:
                    seg_dur += req.outro_sec
                seg_durs.append(seg_dur)
                seg_path = tmp / f"seg_{i:03d}.mp4"
                self._make_segment(img, seg_dur, req, seg_path)
                segs.append(seg_path)
                self._emit(progress, 60 + int(25 * (i + 1) / n_segs),
                           f"Render đoạn video {i + 1}/{n_segs}")

            # ── 4. Concat video segments + audio ─────────────────────────
            concat_video = tmp / "concat.mp4"
            self._concat(segs, concat_video)
            self._emit(progress, 88, "Ghép các đoạn lại...")

            # Build a single voiceover by concatenating with silence padding
            voiceover = tmp / "voiceover.m4a"
            self._concat_audio_with_padding(tts_files, tts_durations, req,
                                            seg_durs, voiceover)

            # Mux audio (+ optional BGM)
            self._emit(progress, 94, "Trộn lồng tiếng & nhạc nền...")
            bgm_path = self._prepare_bgm(req.bgm_url, tmp) if req.bgm_url else None
            self._mux(concat_video, voiceover, bgm_path, req, out_path)

            self._emit(progress, 100, f"Hoàn tất: {out_path.name}")
            return out_path

    # ── helpers ──
    def _make_segment(self, img: Path, duration: float, req: RenderRequest, out: Path):
        """Render a single image → mp4 with optional Ken Burns zoom."""
        d = max(0.5, float(duration))
        total_frames = max(1, int(d * req.fps))
        if req.zoom:
            # Slow zoom-in 1.0 → 1.12 over the duration. We pre-scale to 2× to
            # keep the zoom region sharp.
            vf = (
                f"scale={req.width * 2}:{req.height * 2}:force_original_aspect_ratio=increase,"
                f"crop={req.width * 2}:{req.height * 2},"
                f"zoompan=z='min(zoom+0.0008,1.12)':d={total_frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={req.width}x{req.height}:fps={req.fps},"
                f"format=yuv420p"
            )
        else:
            vf = (
                f"scale={req.width}:{req.height}:force_original_aspect_ratio=decrease,"
                f"pad={req.width}:{req.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"format=yuv420p"
            )
        cmd = [
            self.ffmpeg, "-y", "-loop", "1", "-t", f"{d:.3f}", "-i", str(img),
            "-vf", vf, "-r", str(req.fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-tune", "stillimage",
            "-an", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or "")[-1500:]
            raise RuntimeError(f"ffmpeg segment build failed: {tail}")

    def _concat(self, parts: List[Path], out: Path):
        """Simple concat via filelist (no transition; segments already account for fade)."""
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
            # Re-encode fallback if codec mismatch
            cmd = [
                self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", str(listfile), "-c:v", "libx264", "-preset", "medium",
                "-crf", "20", "-pix_fmt", "yuv420p", str(out),
            ]
            subprocess.run(cmd, check=True, capture_output=True)

    def _concat_audio_with_padding(self, tts_files: List[Path], durations: List[float],
                                   req: RenderRequest, seg_durs: List[float], out: Path):
        """Stitch TTS clips with silence padding to align with video timeline.

        Layout: [intro silence] tts1 [pad] tts2 [pad] ... [outro silence]
        where the silence amounts reproduce the seg_durs we used for video.
        """
        listfile = out.parent / "audio_list.txt"
        # Generate silence files as needed
        sil_paths: List[Path] = []

        def silence(seconds: float, idx: int) -> Path:
            p = out.parent / f"silence_{idx:03d}.m4a"
            cmd = [
                self.ffmpeg, "-y", "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{max(0.05, seconds):.3f}",
                "-c:a", "aac", "-b:a", "128k", str(p),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            sil_paths.append(p)
            return p

        with open(listfile, "w", encoding="utf-8") as f:
            # Intro silence
            if req.intro_sec > 0.05:
                f.write(f"file '{silence(req.intro_sec, 0).as_posix()}'\n")
            for i, tts in enumerate(tts_files):
                f.write(f"file '{tts.as_posix()}'\n")
                # Inter-segment pause = crossfade duration (kept short)
                if i < len(tts_files) - 1 and req.crossfade_sec > 0.1:
                    f.write(f"file '{silence(req.crossfade_sec, i + 1).as_posix()}'\n")
            if req.outro_sec > 0.05:
                f.write(f"file '{silence(req.outro_sec, 999).as_posix()}'\n")

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
            p = tmp / ("bgm_src" + ext)
            if _download(url_or_path, p):
                return p
            return None
        local = Path(url_or_path)
        if local.exists():
            return local
        return None

    def _mux(self, video: Path, voiceover: Path, bgm: Optional[Path],
             req: RenderRequest, out: Path):
        if bgm and bgm.exists():
            # voiceover (1.0) + bgm (req.bgm_volume), bgm looped to video length
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video),
                "-i", str(voiceover),
                "-stream_loop", "-1", "-i", str(bgm),
                "-filter_complex",
                f"[2:a]volume={req.bgm_volume:.3f},aloop=loop=-1:size=2e+09[bg];"
                f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        else:
            cmd = [
                self.ffmpeg, "-y",
                "-i", str(video), "-i", str(voiceover),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(out),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg mux failed: {proc.stderr[-1500:]}")


# ── Job manager (background rendering) ──────────────────────────────────────
@dataclass
class Job:
    id: str
    status: str = "queued"        # queued | running | done | error
    progress: int = 0
    message: str = ""
    error: str = ""
    output_path: str = ""
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


def render_async(req: RenderRequest) -> str:
    """Spawn a background thread that renders the video. Returns job id."""
    jm = get_job_manager()
    job = jm.create()

    def _runner():
        jm.update(job.id, status="running", started_at=time.time())
        try:
            renderer = MovieVideoRenderer()
            def cb(p, m):
                jm.update(job.id, progress=p, message=m)
            out = renderer.render(req, progress=cb)
            jm.update(job.id, status="done", progress=100, message="Hoàn tất.",
                      output_path=str(out), finished_at=time.time())
        except Exception as e:
            import traceback as _tb
            tb_text = _tb.format_exc()
            try:
                from core_app import LOGGER as _LOG
                _LOG.error("Movie render failed for job %s:\n%s", job.id, tb_text)
            except Exception:
                pass
            jm.update(job.id, status="error",
                      error=f"{type(e).__name__}: {e}",
                      message="Lỗi: " + str(e)[:200],
                      finished_at=time.time())

    threading.Thread(target=_runner, daemon=True).start()
    return job.id

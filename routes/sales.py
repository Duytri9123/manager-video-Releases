"""Sales-video render blueprint.

Builds a sales/marketing video from a source clip + an AI sales script:
  1. Generate a Vietnamese voiceover (TTS) from the script.
  2. Optionally burn the script as subtitles (evenly distributed over the
     voiceover duration).
  3. Mux the new voiceover onto the source video → output MP4.

Streams NDJSON progress so the UI can show a live log + progress bar.
The heavy lifting reuses helpers from core.video_processor (TTS + ffmpeg).
"""
import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from flask import Blueprint, Response, request

from core_app import ROOT, load_cfg, LOGGER

bp = Blueprint("sales", __name__)


def _ndjson(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False) + "\n"


def _split_sentences(text: str):
    """Split a script into subtitle-sized chunks."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    # Split on sentence-ending punctuation, keep it readable
    parts = re.split(r"(?<=[.!?…。！？\n])\s+", text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Further split very long sentences (~50 chars) on commas
        while len(p) > 60:
            cut = p.rfind(",", 0, 60)
            if cut < 20:
                cut = 60
            chunks.append(p[:cut].strip())
            p = p[cut:].strip(" ,")
        if p:
            chunks.append(p)
    return chunks


def _fmt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(chunks, duration: float, out_path: Path):
    """Distribute chunks evenly across [0, duration] and write an SRT file."""
    n = len(chunks)
    if n == 0 or duration <= 0:
        return False
    per = duration / n
    lines = []
    for i, chunk in enumerate(chunks):
        start = i * per
        end = (i + 1) * per - 0.05
        lines.append(str(i + 1))
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(chunk)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _audio_duration(ffprobe: str, audio_path: Path) -> float:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


@bp.route("/api/sales/render", methods=["POST"])
def sales_render():
    data = request.get_json(silent=True) or {}
    video_path = str(data.get("video_path") or "").strip()
    script = str(data.get("script") or "").strip()
    tts_voice = str(data.get("tts_voice") or "vi-VN-HoaiMyNeural").strip()
    do_voiceover = bool(data.get("voiceover", True))
    do_burn_sub = bool(data.get("burn_sub", True))

    def generate():
        from core.video_processor import find_ffmpeg, _tts_edge, run_ffmpeg

        if not video_path or not Path(video_path).exists():
            yield _ndjson(log="✗ Không tìm thấy file video nguồn.", level="error", done=True, ok=False)
            return
        if do_voiceover and not script:
            yield _ndjson(log="✗ Chưa có kịch bản để lồng tiếng.", level="error", done=True, ok=False)
            return

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            yield _ndjson(log="✗ Không tìm thấy ffmpeg.", level="error", done=True, ok=False)
            return
        ffprobe = shutil.which("ffprobe") or "ffprobe"

        src = Path(video_path)
        out_dir = src.parent
        out_path = out_dir / f"{src.stem}_sales.mp4"

        yield _ndjson(log="▶ Bắt đầu render video bán hàng…", level="banner", overall=5)

        tmpdir = Path(tempfile.mkdtemp(prefix="sales_"))
        voice_mp3 = tmpdir / "voice.mp3"
        srt_path = out_dir / f"{src.stem}_sales.srt"

        # ── 1. TTS voiceover ──
        duration = 0.0
        if do_voiceover:
            yield _ndjson(log=f"🔊 Tạo giọng đọc (edge-tts: {tts_voice})…", level="info", overall=20)
            try:
                ok = asyncio.run(_tts_edge(script, tts_voice, voice_mp3))
            except Exception as exc:
                yield _ndjson(log=f"✗ Lỗi TTS: {exc}", level="error", done=True, ok=False)
                return
            if not ok or not voice_mp3.exists():
                yield _ndjson(log="✗ Tạo giọng đọc thất bại.", level="error", done=True, ok=False)
                return
            duration = _audio_duration(ffprobe, voice_mp3)
            yield _ndjson(log=f"✓ Giọng đọc xong ({duration:.1f}s).", level="success", overall=45)

        # ── 2. Subtitle from script ──
        burned = False
        if do_burn_sub and script and duration > 0:
            chunks = _split_sentences(script)
            if _build_srt(chunks, duration, srt_path):
                burned = True
                yield _ndjson(log=f"📝 Tạo phụ đề kịch bản ({len(chunks)} dòng).", level="info", overall=55)

        # ── 3. ffmpeg mux ──
        yield _ndjson(log="🎬 Ghép giọng đọc + phụ đề vào video…", level="info", overall=70)
        args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src)]
        if do_voiceover:
            args += ["-i", str(voice_mp3)]

        if burned:
            # subtitles filter — run with cwd=out_dir so we pass only the
            # filename and avoid Windows drive-colon escaping headaches.
            vf = f"subtitles={srt_path.name}:force_style='FontSize=18,PrimaryColour=&H00FFFFFF,Outline=2,Alignment=2,MarginV=40'"
            args += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        else:
            args += ["-c:v", "copy"]

        if do_voiceover:
            args += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            args += ["-map", "0:v:0", "-map", "0:a:0?", "-c:a", "aac"]

        args += [str(out_path)]

        try:
            ok, err = run_ffmpeg(args, desc="sales render") if not burned else _run_in_dir(args, out_dir)
        except Exception as exc:
            yield _ndjson(log=f"✗ Lỗi ffmpeg: {exc}", level="error", done=True, ok=False)
            return

        if not ok or not out_path.exists():
            yield _ndjson(log=f"✗ Render thất bại: {err[:300]}", level="error", done=True, ok=False)
            return

        yield _ndjson(
            log=f"✅ Hoàn tất: {out_path.name}", level="success", overall=100,
            done=True, ok=True, output_path=str(out_path.resolve()),
        )

    return Response(generate(), mimetype="application/x-ndjson")


def _run_in_dir(args, cwd: Path):
    """Run ffmpeg from a working directory (so subtitles= can use a bare
    filename and dodge Windows path-escaping in the filtergraph)."""
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=1800)
        return proc.returncode == 0, (proc.stderr or "")
    except Exception as exc:
        return False, str(exc)

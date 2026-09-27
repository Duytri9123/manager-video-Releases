#!/usr/bin/env python3
"""
core.processor.audio_mixer
Audio mixing utilities: external audio track mixing, multiple audio streams,
volume ducking and synchronization.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from core.processor.ffmpeg_base import (
    find_ffmpeg, run_ffmpeg, _run_ffmpeg, get_media_duration_seconds,
    _get_audio_duration, _winlong, _safe_stem, has_audio_track
)

class AudioMixer:
    """Mix TTS audio clips into a video at correct timestamps using ffmpeg."""

    def __init__(self, ffmpeg: str):
        self.ffmpeg = ffmpeg

    def mix(
        self,
        video_path: Path,
        tts_clips: list[dict],
        output_path: Path,
        keep_bg_music: bool,
        bg_volume: float,
        tts_volume: float,
    ) -> tuple[bool, str]:
        """
        Mix TTS clips into video.

        Each clip dict must have: {"path": Path, "start": float, ...}
        delay_ms = int(clip["start"] * 1000)

        Returns (True, "") on success, (False, error_msg) on failure.
        """
        if not tts_clips:
            return False, "No TTS clips"

        video_path = Path(video_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="audiomix_") as tmpdir:
            tmpdir = Path(tmpdir)
            tmp_video = tmpdir / "input.mp4"
            shutil.copy2(str(video_path), str(tmp_video))

            video_duration = get_media_duration_seconds(self.ffmpeg, tmp_video)
            if video_duration <= 0:
                video_duration = max(float(c.get("start", 0.0)) for c in tts_clips) + 8.0

            # Create a silent base track so amix always has stable timeline from t=0.
            silent_path = tmpdir / "silent.wav"
            ok_silent, err_silent = run_ffmpeg([
                self.ffmpeg,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(video_duration),
                str(silent_path), "-y", "-loglevel", "error"
            ])
            if not ok_silent or not silent_path.exists():
                return False, f"failed to create silent base: {err_silent}"

            # Build inputs list and filter_complex
            inputs = ["-i", str(tmp_video), "-i", str(silent_path)]
            filter_parts = []
            mix_labels = []

            for j, clip in enumerate(tts_clips):
                inputs += ["-i", str(clip["path"])]
                delay_ms = int(clip["start"] * 1000)
                filter_parts.append(
                    f"[{j + 2}:a]adelay={delay_ms}|{delay_ms}[d{j}]"
                )
                mix_labels.append(f"[d{j}]")

            # Mix all delayed clips with a silent base of full video duration.
            n_mix = len(mix_labels) + 1
            filter_parts.append(
                f"[1:a]{''.join(mix_labels)}amix=inputs={n_mix}:duration=first:dropout_transition=0:normalize=0[tts_raw]"
            )
            # Boost dubbed voice so it is clearly above background/original sound.
            filter_parts.append(f"[tts_raw]volume={max(0.1, float(tts_volume)):.3f}[tts_mix]")

            if keep_bg_music:
                orig_audio = tmpdir / "orig_audio.wav"
                run_ffmpeg([
                    self.ffmpeg, "-i", str(tmp_video),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    str(orig_audio), "-y", "-loglevel", "error"
                ])
                if orig_audio.exists():
                    bg_idx = len(tts_clips) + 2
                    inputs += ["-i", str(orig_audio)]
                    filter_parts.append(
                        f"[{bg_idx}:a]volume={bg_volume}[bg];"
                        f"[tts_mix][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,aresample=async=1:first_pts=0[final_audio]"
                    )
                    final_label = "[final_audio]"
                else:
                    final_label = "[tts_mix]"
            else:
                final_label = "[tts_mix]"

            filter_complex = ";".join(filter_parts)

            cmd = [self.ffmpeg] + inputs + [
                "-filter_complex", filter_complex,
                "-map", "0:v:0",
                "-map", final_label,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                str(output_path), "-y", "-loglevel", "error"
            ]
            ok, err = run_ffmpeg(cmd, "audio mix")
            if not ok:
                return False, f"ffmpeg mix failed: {err}"
            if not output_path.exists() or output_path.stat().st_size <= 0:
                return False, "ffmpeg mix finished without a valid output file"
            return True, ""

def mix_external_audio(
    video_path: Path,
    ext_audio_path: Path,
    vol_orig: float,
    vol_ext: float,
    output_path: Path,
    ffmpeg: str,
    vid_start: str = "đầu",
    vid_end: str = "cuối",
    clip_start: str = "0",
    clip_end: str = "hết"
) -> tuple[bool, str]:
    """Mix external audio file with a video file's audio track using FFmpeg.

    Trims the external audio clip from clip_start to clip_end, delays it to start
    at vid_start on the video timeline, and caps its duration to not exceed the
    video segment (vid_end - vid_start).
    """
    if not ext_audio_path.exists():
        return False, f"External audio file not found: {ext_audio_path}"

    from utils.ffprobe import probe_video
    
    # Get video duration
    try:
        _, _, video_duration = probe_video(video_path)
    except Exception:
        video_duration = 0.0
    if not video_duration or video_duration <= 0:
        video_duration = get_media_duration_seconds(ffmpeg, video_path)
    if not video_duration or video_duration <= 0:
        video_duration = 9999.0

    # Get external audio duration
    try:
        _, _, audio_duration = probe_video(ext_audio_path)
    except Exception:
        audio_duration = 0.0
    if not audio_duration or audio_duration <= 0:
        audio_duration = 9999.0

    # Parse Video Range (X to Y)
    try:
        vs_str = str(vid_start).strip().lower()
        X = 0.0 if vs_str in ("đầu", "dau", "") else float(vs_str)
    except Exception:
        X = 0.0

    try:
        ve_str = str(vid_end).strip().lower()
        Y = video_duration if ve_str in ("cuối", "cuoi", "hết", "het", "") else float(ve_str)
    except Exception:
        Y = video_duration

    X = max(0.0, min(video_duration, X))
    Y = max(X, min(video_duration, Y))

    # Parse Audio Trim Range (A to B)
    try:
        cs_str = str(clip_start).strip().lower()
        A = 0.0 if cs_str in ("đầu", "dau", "") else float(cs_str)
    except Exception:
        A = 0.0

    try:
        ce_str = str(clip_end).strip().lower()
        B = audio_duration if ce_str in ("cuối", "cuoi", "hết", "het", "") else float(ce_str)
    except Exception:
        B = audio_duration

    A = max(0.0, min(audio_duration, A))
    B = max(A, min(audio_duration, B))

    # Cap clip duration to not exceed video segment range
    max_video_range = Y - X
    clip_dur = min(B - A, max_video_range)
    if clip_dur <= 0:
        clip_dur = 0.1  # fallback to small positive duration

    X_ms = int(X * 1000)
    has_orig_audio = has_audio_track(video_path, ffmpeg)

    cmd = [ffmpeg, "-i", str(video_path), "-i", str(ext_audio_path)]

    # Trim the input audio clip from A to A + clip_dur, delay it by X_ms, and adjust volume
    ext_filter = (
        f"[1:a]atrim=start={A:.3f}:end={(A + clip_dur):.3f},"
        f"asetpts=PTS-STARTPTS,"
        f"adelay={X_ms}|{X_ms},"
        f"volume={vol_ext:.3f}[a1]"
    )

    if has_orig_audio:
        filter_str = (
            f"[0:a]volume={vol_orig:.3f}[a0];"
            f"{ext_filter};"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )
        cmd += ["-filter_complex", filter_str, "-map", "0:v", "-map", "[a]"]
    else:
        filter_str = (
            f"{ext_filter};"
            f"[a1]anull[a]"
        )
        cmd += ["-filter_complex", filter_str, "-map", "0:v", "-map", "[a]"]

    cmd += ["-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path), "-y", "-loglevel", "error"]

    return run_ffmpeg(cmd, "external audio mix")


def mix_multiple_external_audios(
    video_path: Path,
    ext_audios: list[dict],
    vol_orig: float,
    output_path: Path,
    ffmpeg: str
) -> tuple[bool, str]:
    """Mix multiple external audio files with a video file's audio track using FFmpeg.
    """
    from utils.ffprobe import probe_video
    
    # Get video duration
    try:
        _, _, video_duration = probe_video(video_path)
    except Exception:
        video_duration = 0.0
    if not video_duration or video_duration <= 0:
        video_duration = get_media_duration_seconds(ffmpeg, video_path)
    if not video_duration or video_duration <= 0:
        video_duration = 9999.0

    has_orig_audio = has_audio_track(video_path, ffmpeg)
    cmd = [ffmpeg, "-i", str(video_path)]

    filter_parts = []
    if has_orig_audio:
        filter_parts.append(f"[0:a]volume={vol_orig:.3f}[a0]")

    for idx, track in enumerate(ext_audios, 1):
        ext_audio_path = Path(track["path"])
        cmd += ["-i", str(ext_audio_path)]
        
        # Get external audio duration
        try:
            _, _, audio_duration = probe_video(ext_audio_path)
        except Exception:
            audio_duration = 0.0
        if not audio_duration or audio_duration <= 0:
            audio_duration = 9999.0

        # Parse Video Range (X to Y)
        try:
            vs_str = str(track.get("vid_start", "đầu")).strip().lower()
            X = 0.0 if vs_str in ("đầu", "dau", "") else float(vs_str)
        except Exception:
            X = 0.0

        try:
            ve_str = str(track.get("vid_end", "cuối")).strip().lower()
            Y = video_duration if ve_str in ("cuối", "cuoi", "hết", "het", "") else float(ve_str)
        except Exception:
            Y = video_duration

        X = max(0.0, min(video_duration, X))
        Y = max(X, min(video_duration, Y))

        # Parse Audio Trim Range (A to B)
        try:
            cs_str = str(track.get("clip_start", "0")).strip().lower()
            A = 0.0 if cs_str in ("đầu", "dau", "") else float(cs_str)
        except Exception:
            A = 0.0

        try:
            ce_str = str(track.get("clip_end", "hết")).strip().lower()
            B = audio_duration if ce_str in ("cuối", "cuoi", "hết", "het", "") else float(ce_str)
        except Exception:
            B = audio_duration

        A = max(0.0, min(audio_duration, A))
        B = max(A, min(audio_duration, B))

        # Cap clip duration to not exceed video segment range
        max_video_range = Y - X
        clip_dur = min(B - A, max_video_range)
        if clip_dur <= 0:
            clip_dur = 0.1  # fallback to small positive duration

        X_ms = int(X * 1000)
        vol_ext = track.get("vol", 1.0)
        
        filter_parts.append(
            f"[{idx}:a]atrim=start={A:.3f}:end={(A + clip_dur):.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"adelay={X_ms}|{X_ms},"
            f"volume={vol_ext:.3f}[a{idx}]"
        )

    # Now mix them together
    n_inputs = len(ext_audios) + (1 if has_orig_audio else 0)
    if n_inputs == 0:
        # Nothing to mix (no original audio, no external audios)
        cmd += ["-c:v", "copy", "-an", str(output_path), "-y", "-loglevel", "error"]
        return run_ffmpeg(cmd, "no audio copy")

    if has_orig_audio:
        mix_inputs = "".join(f"[a{i}]" for i in range(len(ext_audios) + 1))
        filter_str = f"{';'.join(filter_parts)};{mix_inputs}amix=inputs={len(ext_audios) + 1}:duration=first:dropout_transition=0:normalize=0[a]"
        cmd += ["-filter_complex", filter_str, "-map", "0:v", "-map", "[a]"]
    else:
        if len(ext_audios) == 1:
            filter_str = f"{filter_parts[0]};[a1]anull[a]"
        else:
            mix_inputs = "".join(f"[a{i}]" for i in range(1, len(ext_audios) + 1))
            filter_str = f"{';'.join(filter_parts)};{mix_inputs}amix=inputs={len(ext_audios)}:duration=first:dropout_transition=0:normalize=0[a]"
        cmd += ["-filter_complex", filter_str, "-map", "0:v", "-map", "[a]"]

    cmd += ["-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path), "-y", "-loglevel", "error"]
    return run_ffmpeg(cmd, "multiple external audio mix")



# ══════════════════════════════════════════════════════════════════════════════
# Main pipeline: process_video_full
# ══════════════════════════════════════════════════════════════════════════════

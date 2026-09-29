#!/usr/bin/env python3
"""
core.processor.tts
Multi-provider Text-to-Speech: Edge-TTS, VieNeu, OmniVoice, gTTS,
FPT.AI, ElevenLabs, Fish Audio, and voice conversion pipeline.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from core.processor.ffmpeg_base import (
    find_ffmpeg, run_ffmpeg, _run_ffmpeg, get_media_duration_seconds,
    _get_audio_duration, _safe_stem, _winlong
)
from core.processor.effects import apply_audio_effects

LOGGER = logging.getLogger("core.processor.tts")

FPT_TTS_ENDPOINT = "https://api.fpt.ai/hmi/tts/v5"
# FPT key must come from env (FPT_TTS_API_KEY) or config (video_process.fpt_api_key).
# Hard-coded keys removed for security.
FPT_TTS_DEFAULT_KEY = ""
TTS_CACHE_VERSION = "tts-video-anchored-v5"

# ElevenLabs TTS endpoint
ELEVENLABS_TTS_ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Default ElevenLabs voice ID: Rachel (en) — overridable via config elevenlabs_voice_id
ELEVENLABS_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Fish Audio TTS — multilingual backbone, excels at JA/ZH/KO phonetics
# Docs: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
FISH_TTS_ENDPOINT = "https://api.fish.audio/v1/tts"
FISH_DEFAULT_MODEL = "s2-pro"  # backbone: "s2-pro" (recommended) or "s1"


def _split_text_for_tts(text: str, max_chars: int = 800) -> list[str]:
    """Split long text into TTS-friendly chunks at sentence boundaries.

    Handles Vietnamese, Chinese, Japanese and Latin punctuation.
    Strategy:
    1. Split at paragraph breaks.
    2. Within each paragraph, split at sentence terminators (. ! ? … 。！？).
    3. Greedily pack sentences into chunks ≤ max_chars.
    4. Hard-split any sentence that still exceeds max_chars.
    """
    text = (text or "").strip()
    if not text:
        return []

    # Regex: break after . ! ? … 。！？ or newline
    sent_re = re.compile(r"(?<=[.!?…。！？\n])\s+")
    raw_paragraphs = re.split(r"\n\s*\n", text)
    sentences: list[str] = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        for part in sent_re.split(para):
            part = part.strip()
            if part:
                sentences.append(part)

    chunks: list[str] = []
    cur = ""
    for s in sentences:
        if len(s) > max_chars:
            # flush current buffer first
            if cur:
                chunks.append(cur.strip())
                cur = ""
            # hard-split at max_chars
            for i in range(0, len(s), max_chars):
                chunks.append(s[i: i + max_chars].strip())
            continue
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= max_chars:
            cur = cur + " " + s
        else:
            chunks.append(cur.strip())
            cur = s
    if cur:
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def _max_tts_chars_for_engine(engine: str) -> int:
    """Return safe per-chunk character limit for each TTS engine."""
    engine = (engine or "").strip().lower()
    if engine == "fpt-ai":
        return 700
    if engine == "gtts":
        return 200
    if engine == "vieneu":
        return 240
    if engine == "elevenlabs":
        return 2500
    if engine == "fish-audio":
        return 1500
    # edge-tts, openai-tts, and others
    return 1500


# ══════════════════════════════════════════════════════════════════════════════
# MultiProviderTTS
# ══════════════════════════════════════════════════════════════════════════════
class MultiProviderTTS:
    """VieNeu-only adapter; accepts legacy constructor arguments for saved jobs."""

    def __init__(
        self,
        voice: str = "Minh Quân Pro",
        engine: str = "vieneu",
        fpt_api_key: str = "",
        fpt_speed: int = 0,
        openai_api_key: str = "",
        openai_model: str = "tts-1",
        tts_lang: str = "vi",
        tts_rate: str = "+0%",
        tts_pitch: str = "+0Hz",
        tts_emotion: str = "default",
        tts_persona: str = "",
        elevenlabs_api_key: str = "",
        elevenlabs_voice_id: str = "",
        elevenlabs_model: str = "eleven_multilingual_v2",
        fpt_fallback_elevenlabs: bool = False,
        fish_api_key: str = "",
        fish_model: str = "",
        fish_reference_id: str = "",
        vieneu_ref_audio: str = "",
    ):
        from config.config_loader import get_provider_api_key
        from core.tts_catalog import resolve_engine_voice
        self.engine, self.voice, _, _ = resolve_engine_voice(engine, voice, tts_lang)
        self.fpt_api_key = (fpt_api_key or "").strip() or get_provider_api_key("fptai")
        self.fpt_speed = fpt_speed
        self.openai_api_key = (openai_api_key or "").strip() or get_provider_api_key("openai")
        self.openai_model = openai_model or "tts-1"
        self.tts_lang = tts_lang or "vi"
        self.tts_rate = tts_rate or "+0%"
        self.tts_pitch = tts_pitch or "+0Hz"
        self.tts_emotion = tts_emotion or "default"
        self.tts_persona = (tts_persona or "").strip()
        self.elevenlabs_api_key = (elevenlabs_api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip() or get_provider_api_key("elevenlabs")
        self.elevenlabs_voice_id = (elevenlabs_voice_id or "").strip() or ELEVENLABS_DEFAULT_VOICE_ID
        self.elevenlabs_model = elevenlabs_model or "eleven_multilingual_v2"
        self.fish_api_key = (
            (fish_api_key or "").strip()
            or os.getenv("FISH_API_KEY", "").strip()
            or os.getenv("FISH_AUDIO_API_KEY", "").strip()
            or get_provider_api_key("fishaudio")
        )
        self.fish_model = (fish_model or "").strip() or FISH_DEFAULT_MODEL
        self.fish_reference_id = (fish_reference_id or "").strip()
        self.vieneu_ref_audio = (vieneu_ref_audio or "").strip()
        # Tự động fallback FPT → ElevenLabs khi FPT hết token/quota
        self.fpt_fallback_elevenlabs = fpt_fallback_elevenlabs and bool(self.elevenlabs_api_key)

    async def _generate_single(
        self, text: str, out_path: Path, engine: str, voice: str | None = None
    ) -> bool:
        """Generate TTS for a single text chunk (no splitting). Internal use only."""
        from core.tts_catalog import resolve_engine_voice
        _, selected_voice, _, _ = resolve_engine_voice(self.engine, voice or self.voice, self.tts_lang)
        return await asyncio.to_thread(
            _tts_vieneu, text, selected_voice, out_path,
            style=self.tts_emotion, ref_audio=self.vieneu_ref_audio, engine=self.engine,
        )

    async def generate(self, text: str, out_path: Path, voice: str | None = None) -> bool:
        """Generate with VieNeu; its SDK handles sentence splitting internally."""
        out_path = Path(out_path)
        return await self._generate_single(text, out_path, "vieneu", voice=voice)

    async def generate_all(
        self,
        segments: list[dict],
        translations: list[str],
        tmpdir: Path,
        max_concurrency: int = 4,
        retries: int = 2,
        tts_speed: float = 1.0,
        auto_speed: bool = True,
        ffmpeg: str = "ffmpeg",
        pitch_semitones: float = 0.0,
        indices: list[int] | None = None,
        voice_map: dict | None = None,
        progress_callback=None,
    ) -> list[dict]:
        """
        Generate TTS for all segments with bounded concurrency and optional multi-speaker voice_map.
        Returns list of {"path": Path, "start": float, "end": float, "speaker": str}
        only for successfully generated segments.
        """
        tmpdir = Path(tmpdir)
        sem = asyncio.Semaphore(1)  # One local model, no competing CPU inference.
        completed = 0
        total = sum(bool(t and t.strip()) for t in translations)

        async def _gen_one(i: int, seg: dict, text: str):
            if not text or not text.strip():
                return None
            out_path = tmpdir / f"tts_{i:04d}.wav"

            seg_voice = None
            if voice_map:
                spk = str(seg.get("speaker") or "").lower().strip()
                if spk in voice_map and voice_map[spk]:
                    seg_voice = voice_map[spk]
                elif ("female" not in spk and ("male" in spk or "nam" in spk)) and voice_map.get("male"):
                    seg_voice = voice_map["male"]
                elif ("female" in spk or "nữ" in spk or "nu" in spk) and voice_map.get("female"):
                    seg_voice = voice_map["female"]
                elif "default" in voice_map and voice_map["default"]:
                    seg_voice = voice_map["default"]

            async with sem:
                for _attempt in range(max(1, retries + 1)):
                    ok = await self.generate(text.strip(), out_path, voice=seg_voice)
                    if ok:
                        # Auto-speed: fit TTS duration to segment duration
                        speed = float(tts_speed) if tts_speed else 1.0
                        if auto_speed:
                            seg_dur = float(seg["end"]) - float(seg["start"])
                            tts_dur = _get_audio_duration(ffmpeg, out_path)
                            if tts_dur > 0 and seg_dur > 0:
                                auto = tts_dur / seg_dur
                                auto = max(1.0, min(3.0, auto))
                                speed = max(1.0, min(3.0, auto * speed))
                        if abs(speed - 1.0) > 0.05:
                            sped_path = tmpdir / f"tts_{i:04d}_fast.mp3"
                            _apply_atempo(ffmpeg, out_path, sped_path, speed)
                            if sped_path.exists() and sped_path.stat().st_size > 0:
                                out_path = sped_path
                        # Apply pitch shift - giữ nguyên tốc độ
                        if abs(pitch_semitones) > 0.05:
                            pitched_path = tmpdir / f"tts_{i:04d}_pitched.mp3"
                            wav_in = tmpdir / f"tts_{i:04d}_in.wav"
                            wav_out = tmpdir / f"tts_{i:04d}_out.wav"
                            import subprocess as _sp
                            _sp.run([ffmpeg, "-i", str(out_path), "-ar", "44100", "-ac", "1",
                                str(wav_in), "-y", "-loglevel", "error"], capture_output=True)
                            if wav_in.exists():
                                # Thử rubberband trước
                                r = _sp.run([ffmpeg, "-i", str(wav_in),
                                    "-filter:a", f"rubberband=pitch={2**(pitch_semitones/12):.6f}",
                                    str(wav_out), "-y", "-loglevel", "error"], capture_output=True)
                                if not (wav_out.exists() and wav_out.stat().st_size > 0):
                                    # Fallback: asetrate + atempo
                                    factor = 2 ** (pitch_semitones / 12)
                                    new_rate = int(44100 * factor)
                                    tempo = 1.0 / factor
                                    tempo_filters = []
                                    t = tempo
                                    while t < 0.5:
                                        tempo_filters.append("atempo=0.5"); t *= 2.0
                                    while t > 2.0:
                                        tempo_filters.append("atempo=2.0"); t /= 2.0
                                    tempo_filters.append(f"atempo={t:.6f}")
                                    f = f"asetrate={new_rate}," + ",".join(tempo_filters) + ",aresample=44100"
                                    _sp.run([ffmpeg, "-i", str(wav_in), "-filter:a", f,
                                        str(wav_out), "-y", "-loglevel", "error"], capture_output=True)
                                if wav_out.exists() and wav_out.stat().st_size > 0:
                                    _sp.run([ffmpeg, "-i", str(wav_out), "-q:a", "2",
                                        str(pitched_path), "-y", "-loglevel", "error"], capture_output=True)
                                    if pitched_path.exists() and pitched_path.stat().st_size > 0:
                                        out_path = pitched_path
                        nonlocal completed
                        completed += 1
                        if progress_callback:
                            progress_callback(completed, total)
                        return {
                            "index": i,
                            "path": out_path,
                            "start": seg["start"],
                            "end": seg["end"],
                            "speaker": seg.get("speaker"),
                        }
                    await asyncio.sleep(0.25 * (_attempt + 1))
            return None

        if indices is None:
            task_indices = list(range(min(len(segments), len(translations))))
        else:
            task_indices = list(indices)
            if len(task_indices) != min(len(segments), len(translations)):
                raise ValueError("indices must match the number of TTS segments")
        tasks = [
            _gen_one(i, seg, text)
            for i, seg, text in zip(task_indices, segments, translations)
        ]
        results = await asyncio.gather(*tasks)
        clips = [r for r in results if r is not None]

        def _clip_start(c: Dict[str, Any]) -> float:
            val = c.get("start", 0.0)
            if isinstance(val, (int, float)):
                return float(val)
            try:
                return float(str(val))
            except Exception:
                return 0.0

        clips.sort(key=_clip_start)
        return clips


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Voice conversion ZH → VI
# ══════════════════════════════════════════════════════════════════════════════
def _get_audio_duration(ffmpeg: str, path: Path) -> float:
    """Return duration of an audio file in seconds."""
    if Path(path).suffix.lower() == ".wav":
        try:
            import soundfile as sf
            return float(sf.info(str(path)).duration)
        except Exception:
            pass
    try:
        r = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True
        )
        for line in r.stderr.splitlines():
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
    except Exception:
        pass
    return 0.0


def _apply_atempo(ffmpeg: str, src: Path, dst: Path, speed: float) -> bool:
    """Speed up/slow down audio using ffmpeg atempo (chains if >2x or <0.5x)."""
    # atempo supports 0.5–2.0, chain for values outside range
    filters = []
    s = speed
    while s > 2.0:
        filters.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        filters.append("atempo=0.5")
        s /= 0.5
    filters.append(f"atempo={s:.4f}")
    filter_str = ",".join(filters)
    ok, _ = run_ffmpeg([
        ffmpeg, "-i", str(src),
        "-filter:a", filter_str,
        str(dst), "-y", "-loglevel", "error"
    ], "atempo")
    return ok


_EDGE_TTS_STYLE_ALIASES = {
    "default": "",
    "neutral": "",
    "excited": "excited",
    "cheerful": "cheerful",
    "sad": "sad",
    "angry": "angry",
    "friendly": "friendly",
    "hopeful": "hopeful",
    "empathetic": "empathetic",
    "customerservice": "customerservice",
    "newscast": "newscast",
    "newscast-formal": "newscast-formal",
    "newscast-casual": "newscast-casual",
    "narration": "narration-professional",
    "narration-professional": "narration-professional",
    "shouting": "shouting",
    "whispering": "whispering",
    "terrified": "terrified",
    "unfriendly": "unfriendly",
    "assistant": "assistant",
    "calm": "calm",
}
_EDGE_TTS_STYLE_VAR = None
_EDGE_TTS_ORIGINAL_MKSSML = None


def _edge_locale_from_voice(voice: str) -> str:
    parts = (voice or "").split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return "en-US"


def _normalize_edge_style(style: str) -> str:
    raw = (style or "").strip().lower().replace("_", "-")
    return _EDGE_TTS_STYLE_ALIASES.get(raw, raw if raw and raw != "default" else "")


def _install_edge_style_patch(edge_tts_module) -> None:
    """Patch edge-tts SSML generation once so style can be task-local.

    The public edge-tts API exposes rate/pitch but not Microsoft mstts styles.
    We keep the original behavior when no context-local style is set.
    """
    global _EDGE_TTS_STYLE_VAR, _EDGE_TTS_ORIGINAL_MKSSML
    import contextvars

    import edge_tts.communicate as edge_comm

    if _EDGE_TTS_STYLE_VAR is None:
        _EDGE_TTS_STYLE_VAR = contextvars.ContextVar("edge_tts_style", default="")
    if getattr(edge_comm.mkssml, "_toolvideo_style_patch", False):
        return

    original_mkssml = edge_comm.mkssml
    _EDGE_TTS_ORIGINAL_MKSSML = original_mkssml

    def styled_mkssml(tc, escaped_text):
        style_name = _EDGE_TTS_STYLE_VAR.get("") if _EDGE_TTS_STYLE_VAR else ""
        if not style_name:
            return original_mkssml(tc, escaped_text)
        if isinstance(escaped_text, bytes):
            escaped = escaped_text.decode("utf-8")
        else:
            escaped = escaped_text
        locale = _edge_locale_from_voice(getattr(tc, "voice", ""))
        return (
            "<speak version='1.0' "
            "xmlns='http://www.w3.org/2001/10/synthesis' "
            "xmlns:mstts='https://www.w3.org/2001/mstts' "
            f"xml:lang='{locale}'>"
            f"<voice name='{tc.voice}'>"
            f"<mstts:express-as style='{style_name}'>"
            f"<prosody pitch='{tc.pitch}' rate='{tc.rate}' volume='{tc.volume}'>"
            f"{escaped}"
            "</prosody>"
            "</mstts:express-as>"
            "</voice>"
            "</speak>"
        )

    setattr(styled_mkssml, "_toolvideo_style_patch", True)
    edge_comm.mkssml = styled_mkssml


async def _tts_edge(text: str, voice: str, out_path: Path, rate: str = "+0%",
                    pitch: str = "+0Hz", style: str = "default") -> bool:
    """Generate TTS audio using edge-tts.

    `pitch` accepts a string like "+0Hz", "-2Hz", "+2Hz" and is passed through
    to edge-tts. `style` is accepted for compatibility but not all voices
    support SSML express-as styles via edge-tts; if the underlying call fails
    with the style we silently retry without it.
    """
    # Map FPT AI voices → edge-tts Vietnamese voices
    _VOICE_MAP = {
        "banmai": "vi-VN-HoaiMyNeural",
        "leminh": "vi-VN-NamMinhNeural",
        "thuminh": "vi-VN-HoaiMyNeural",
        "giahuy": "vi-VN-NamMinhNeural",
        "myan": "vi-VN-HoaiMyNeural",
        "lannhi": "vi-VN-HoaiMyNeural",
        "lianh": "vi-VN-HoaiMyNeural",
    }
    # Auto-fix voice name if it's an FPT voice or doesn't look like edge-tts format
    if voice and "-" not in voice and "Neural" not in voice:
        voice = _VOICE_MAP.get(voice.lower(), "vi-VN-HoaiMyNeural")

    try:
        import edge_tts
        kwargs = {"rate": rate}
        if pitch and pitch.strip() and pitch.strip().lower() not in ("+0hz", "0hz", "default"):
            kwargs["pitch"] = pitch

        async def _save_with_optional_style(style_name: str = "") -> bool:
            token = None
            if style_name:
                _install_edge_style_patch(edge_tts)
                token = _EDGE_TTS_STYLE_VAR.set(style_name) if _EDGE_TTS_STYLE_VAR else None
            try:
                # Retry up to 2 times on "No audio was received" errors
                last_err = None
                for _retry in range(3):
                    try:
                        communicate = edge_tts.Communicate(text, voice, **kwargs)
                        await communicate.save(str(out_path))
                        if out_path.exists() and out_path.stat().st_size > 0:
                            return True
                    except TypeError:
                        # Older edge-tts that doesn't support `pitch`
                        communicate = edge_tts.Communicate(text, voice, rate=rate)
                        await communicate.save(str(out_path))
                        if out_path.exists() and out_path.stat().st_size > 0:
                            return True
                    except Exception as e:
                        last_err = e
                        err_msg = str(e).lower()
                        if "no audio was received" in err_msg:
                            # Retry after short delay — edge-tts sometimes has transient failures
                            await asyncio.sleep(1.0 * (_retry + 1))
                            continue
                        raise RuntimeError(f"edge-tts failed: {e}")

                # All retries exhausted
                if last_err:
                    raise RuntimeError(f"edge-tts failed after 3 attempts: {last_err}")
                return False
            finally:
                if token is not None and _EDGE_TTS_STYLE_VAR is not None:
                    _EDGE_TTS_STYLE_VAR.reset(token)

        style_name = _normalize_edge_style(style)
        if style_name:
            try:
                return await _save_with_optional_style(style_name)
            except Exception:
                # Unsupported styles vary by voice. Retry plain prosody so the
                # user still gets audio instead of a hard failure.
                try:
                    if out_path.exists():
                        out_path.unlink()
                except Exception:
                    pass

        return await _save_with_optional_style("")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"edge-tts failed: {e}")


async def _tts_fpt_ai(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    speed: int = 0,
) -> bool:
    """Generate TTS audio using FPT AI TTS v5 (Vietnamese voices)."""
    import aiohttp

    key = (api_key or "").strip() or os.getenv("FPT_AI_API_KEY", "").strip() or FPT_TTS_DEFAULT_KEY
    if not key:
        raise RuntimeError("Missing FPT AI API key")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = (text or "").strip()
    if not payload:
        return False

    # FPT commonly uses lowercase voice keys like banmai, leminh, myan...
    fpt_voice = (voice or "banmai").strip().lower()
    headers = {
        "api-key": key,
        "voice": fpt_voice,
        "speed": str(speed),
        "format": "mp3",
    }

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(FPT_TTS_ENDPOINT, data=payload.encode("utf-8"), headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"FPT TTS request failed: status={resp.status}, body={await resp.text()}")
            data = await resp.json(content_type=None)

        audio_url = str((data or {}).get("async") or (data or {}).get("url") or "").strip()
        if not audio_url:
            raise RuntimeError(f"FPT TTS missing async URL: {data}")

        # Poll async URL until audio is ready (up to ~60s for long text).
        for attempt in range(24):
            await asyncio.sleep(0.5)
            async with session.get(audio_url) as aresp:
                if aresp.status != 200:
                    continue
                raw_ctype = aresp.headers.get("Content-Type")
                ctype = (raw_ctype or "").lower()
                blob = await aresp.read()
                # When not ready yet, some gateways may return JSON/text instead of audio.
                if "audio" not in ctype and blob[:1] in (b"{", b"["):
                    continue
                if blob:
                    out_path.write_bytes(blob)
                    return out_path.exists() and out_path.stat().st_size > 0

    return False


async def _tts_openai(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    model: str = "tts-1",
) -> bool:
    """Generate TTS using OpenAI TTS API."""
    import aiohttp

    key = (api_key or "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing OpenAI API key (set OPENAI_API_KEY or config)")

    out_path = Path(out_path)
    if not text or not text.strip():
        return False

    valid_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    oai_voice = (voice or "nova").strip().lower()
    if oai_voice not in valid_voices:
        oai_voice = "nova"

    payload = {"model": model or "tts-1", "input": text.strip(), "voice": oai_voice}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.openai.com/v1/audio/speech",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"OpenAI TTS error {resp.status}: {await resp.text()}")
            audio_bytes = await resp.read()
            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0




_GEMINI_TTS_STYLE_PREFIX = {
    "cheerful": "Say cheerfully: ",
    "excited": "[excited] ",
    "sad": "Say sadly and gently: ",
    "angry": "Say angrily, with controlled intensity: ",
    "friendly": "Say in a warm, friendly tone: ",
    "hopeful": "Say with a hopeful tone: ",
    "empathetic": "Say with empathy: ",
    "customerservice": "Say like a helpful customer service agent: ",
    "newscast": "Read like a TV news anchor: ",
    "newscast-formal": "Read like a formal news anchor: ",
    "newscast-casual": "Read like a casual news presenter: ",
    "narration": "Narrate professionally: ",
    "narration-professional": "Narrate professionally: ",
    "shouting": "[shouting] ",
    "whispering": "[whispers] ",
    "terrified": "Say with a fearful, tense tone: ",
    "serious": "[serious] ",
}


_VIENEU_TTS_INSTANCE = None
_VIENEU_LOCK = threading.RLock()


def _vieneu_emotion_from_style(style: str) -> str:
    key = (style or "").strip().lower().replace("_", "-")
    mapping = {
        "default": "natural",
        "neutral": "natural",
        "natural": "natural",
        "cheerful": "happy",
        "excited": "happy",
        "friendly": "happy",
        "hopeful": "happy",
        "sad": "sad",
        "angry": "angry",
        "empathetic": "sad",
        "narration": "natural",
        "narration-professional": "natural",
        "newscast": "natural",
        "customerservice": "natural",
        "whispering": "natural",
        "shouting": "angry",
    }
    return mapping.get(key, key or "natural")


def _vieneu_text_with_cue(text: str, style: str) -> str:
    key = (style or "").strip().lower().replace("_", "-")
    cue = {
        "cheerful": "[cười] ",
        "excited": "[cười] ",
        "friendly": "[cười] ",
        "sad": "[thở dài] ",
        "empathetic": "[thở dài] ",
        "whispering": "[thì thầm] ",
    }.get(key, "")
    clean = (text or "").strip()
    return clean if not cue or clean.startswith("[") else cue + clean


def _get_vieneu_tts(engine="vieneu"):
    with _VIENEU_LOCK:
        return _load_vieneu_tts(engine)


_VIENEU_ENGINE = None


def _load_vieneu_tts(engine="vieneu"):
    """Load VieNeu v3 Turbo once per process."""
    global _VIENEU_TTS_INSTANCE, _VIENEU_ENGINE
    if _VIENEU_TTS_INSTANCE is not None and _VIENEU_ENGINE == engine:
        return _VIENEU_TTS_INSTANCE
    try:
        from vieneu import Vieneu
    except Exception as exc:
        raise RuntimeError("VieNeu chưa được cài. Chạy: pip install vieneu") from exc
    try:
        if engine == "vieneu-nano":
            instance = Vieneu(mode="v3nano")
        else:
            # Packaged Windows builds may lack the optional GPU runtime probed by
            # auto. The bundled ONNX CPU backend is the dependable default there.
            default_backend = "onnx" if getattr(sys, "frozen", False) else "auto"
            backend = {"vieneu-cpu": "onnx", "vieneu-gpu": "pytorch"}.get(engine, os.getenv("VIENEU_BACKEND", default_backend))
            if engine == "vieneu-gpu":
                import torch
                if not torch.cuda.is_available():
                    raise RuntimeError("GPU CUDA chưa khả dụng. Cần GPU NVIDIA và PyTorch CUDA; hãy chọn CPU hoặc Tự động.")
            try:
                instance = Vieneu(mode="v3turbo", backend=backend, max_batch_size=2)
            except (OSError, FileNotFoundError) as exc:
                if backend != "auto":
                    raise
                # On some packaged Windows systems the auto backend probes a
                # missing GPU helper. The ONNX CPU backend can still run.
                import logging
                logging.getLogger(__name__).warning("VieNeu auto backend failed; retrying ONNX CPU: %s", exc)
                instance = Vieneu(mode="v3turbo", backend="onnx", max_batch_size=2)
        _VIENEU_TTS_INSTANCE = instance
        _VIENEU_ENGINE = engine
    except Exception as exc:
        raise RuntimeError(f"Không load được VieNeu TTS: {exc}") from exc
    return _VIENEU_TTS_INSTANCE


def _tts_vieneu(*args, **kwargs):
    with _VIENEU_LOCK:
        return _tts_vieneu_locked(*args, **kwargs)


def _tts_vieneu_locked(
    text: str,
    voice: str,
    out_path: Path,
    style: str = "default",
    ref_audio: str = "",
    apply_watermark: bool = False,
    engine: str = "vieneu",
) -> bool:
    """Generate Vietnamese TTS with local VieNeu and write MP3/WAV."""
    payload_text = (text or "").strip()
    if not payload_text:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tts = _get_vieneu_tts(engine)
    emotion = _vieneu_emotion_from_style(style)
    from core.tts_catalog import resolve_engine_voice
    _, resolved_voice, _, _ = resolve_engine_voice(engine, voice, "vi")
    infer_kwargs = {
        "voice": resolved_voice,
        "emotion": emotion,
        "apply_watermark": apply_watermark,
        "max_chars": 140 if engine == "vieneu-nano" else 240,
    }
    if ref_audio:
        if not Path(ref_audio).is_file():
            raise FileNotFoundError(f"Không tìm thấy file giọng mẫu VieNeu: {ref_audio}")
        infer_kwargs.pop("voice", None)
        infer_kwargs["ref_audio"] = ref_audio
    try:
        wav = tts.infer(_vieneu_text_with_cue(payload_text, style), **infer_kwargs)
    except FileNotFoundError as exc:
        raise RuntimeError(f"VieNeu thiếu tệp khi tạo giọng: {exc}") from exc
    if wav is None or len(wav) == 0:
        return False

    suffix = out_path.suffix.lower()
    if suffix == ".wav":
        tts.save(wav, out_path)
        return out_path.exists() and out_path.stat().st_size > 0

    import tempfile as _tmp
    with _tmp.TemporaryDirectory(prefix="vieneu_tts_") as _td:
        wav_path = Path(_td) / "vieneu.wav"
        tts.save(wav, wav_path)
        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin:
            raise RuntimeError("FFmpeg required to convert VieNeu WAV to MP3")
        ok, err = run_ffmpeg([
            ffmpeg_bin, "-y", "-i", str(wav_path),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_path), "-loglevel", "error",
        ], "vieneu_to_mp3", timeout=300)
        if not ok:
            raise RuntimeError(f"VieNeu convert MP3 failed: {err}")
    return out_path.exists() and out_path.stat().st_size > 0


_OMNIVOICE_MODEL = None


def _get_omnivoice_model():
    global _OMNIVOICE_MODEL
    if _OMNIVOICE_MODEL is not None:
        return _OMNIVOICE_MODEL
    try:
        import importlib
        ov_mod = importlib.import_module("omnivoice")
        OmniVoice = getattr(ov_mod, "OmniVoice")
        import torch
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        LOGGER.info(f"[OmniVoice] Loading model on device={device}, dtype={dtype}...")
        _OMNIVOICE_MODEL = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)
        return _OMNIVOICE_MODEL
    except Exception as e:
        LOGGER.error(f"[OmniVoice] Failed to load OmniVoice model: {e}")
        raise


def _tts_omnivoice(
    text: str,
    voice: str = "default",
    out_path: Optional[Path] = None,
    ref_audio: str = "",
    speed: float = 1.0,
    lang: str = "vi",
) -> bool:
    """Synthesize speech using k2-fsa/OmniVoice zero-shot TTS model."""
    payload_text = (text or "").strip()
    if not payload_text:
        return False
    if out_path is None:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import soundfile as sf
        model = _get_omnivoice_model()

        gen_kwargs = {
            "text": payload_text,
        }
        ref = (ref_audio or "").strip()
        if ref and os.path.exists(ref):
            gen_kwargs["ref_audio"] = ref
        elif voice and os.path.exists(voice):
            gen_kwargs["ref_audio"] = voice

        audio = model.generate(**gen_kwargs)
        if audio is None or len(audio) == 0:
            return False

        import tempfile as _tmp
        with _tmp.TemporaryDirectory(prefix="omnivoice_tts_") as _td:
            wav_path = Path(_td) / "omnivoice.wav"
            sr = getattr(model, "sample_rate", 24000)
            audio_data = audio[0] if isinstance(audio, (list, tuple)) else audio
            if hasattr(audio_data, "cpu"):
                audio_data = audio_data.cpu().numpy()
            sf.write(str(wav_path), audio_data, sr)

            suffix = out_path.suffix.lower()
            if suffix == ".wav":
                shutil.copyfile(wav_path, out_path)
                return out_path.exists() and out_path.stat().st_size > 0

            ffmpeg_bin = find_ffmpeg()
            if not ffmpeg_bin:
                raise RuntimeError("FFmpeg required to convert OmniVoice WAV to MP3")
            ok, err = run_ffmpeg([
                ffmpeg_bin, "-y", "-i", str(wav_path),
                "-c:a", "libmp3lame", "-b:a", "192k",
                str(out_path), "-loglevel", "error",
            ], "omnivoice_to_mp3", timeout=300)
            if not ok:
                raise RuntimeError(f"OmniVoice convert MP3 failed: {err}")
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        LOGGER.error(f"[OmniVoice] TTS generation error: {e}")
        raise



def _tts_gtts(text: str, lang: str, out_path: Path, voice: str = "") -> bool:
    """Fallback TTS using gTTS."""
    try:
        from gtts import gTTS
        voice = (voice or "").strip()
        tld = "com"
        if "|" in voice:
            lang_part, tld_part = voice.split("|", 1)
            lang = lang_part.strip() or lang
            tld = tld_part.strip() or tld
        elif voice and re.fullmatch(r"[a-z]{2,3}(?:-[A-Z]{2})?", voice):
            lang = voice.split("-", 1)[0].lower()
        tts = gTTS(text=text, lang=(lang or "vi"), tld=tld, slow=False)
        tts.save(str(out_path))
        return out_path.exists()
    except Exception as e:
        raise RuntimeError(f"gTTS failed: {e}")


async def _tts_elevenlabs(
    text: str,
    voice_id: str,
    out_path: Path,
    api_key: str = "",
    model_id: str = "eleven_multilingual_v2",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
) -> bool:
    """Generate TTS using ElevenLabs API.

    Docs: https://elevenlabs.io/docs/eleven-api/guides/cookbooks/text-to-speech

    Args:
        text: Text to synthesize.
        voice_id: ElevenLabs voice ID (e.g. "21m00Tcm4TlvDq8ikWAM" for Rachel).
        out_path: Output MP3 file path.
        api_key: ElevenLabs API key. Falls back to env ELEVENLABS_API_KEY.
        model_id: Model to use — "eleven_multilingual_v2" supports Vietnamese.
        stability: Voice stability (0.0-1.0).
        similarity_boost: Voice similarity (0.0-1.0).
    """
    import aiohttp

    key = (api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ElevenLabs API key (set ELEVENLABS_API_KEY or config)")

    vid = (voice_id or ELEVENLABS_DEFAULT_VOICE_ID).strip()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload_text = (text or "").strip()
    if not payload_text:
        return False

    url = ELEVENLABS_TTS_ENDPOINT.format(voice_id=vid)
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": payload_text,
        "model_id": model_id or "eleven_multilingual_v2",
        "voice_settings": {
            "stability": float(stability),
            "similarity_boost": float(similarity_boost),
        },
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status == 401:
                raise RuntimeError("ElevenLabs API key không hợp lệ (401 Unauthorized)")
            if resp.status == 422:
                body = await resp.text()
                raise RuntimeError(f"ElevenLabs request không hợp lệ (422): {body}")
            if resp.status == 429:
                raise RuntimeError("ElevenLabs hết quota / rate limit (429)")
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"ElevenLabs TTS lỗi {resp.status}: {body[:200]}")

            audio_bytes = await resp.read()
            if not audio_bytes or len(audio_bytes) < 100:
                raise RuntimeError("ElevenLabs trả về audio rỗng")

            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


async def _tts_fish(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    model: str = "",
    speed: float = 1.0,
) -> bool:
    """Generate TTS using Fish Audio.

    Docs: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech

    Fish Audio's s1 / s2-pro backbones are multilingual and handle the
    phonetics of languages like Japanese, Chinese and Korean very well. The
    target language is auto-detected from the text — no language code needed.

    Args:
        text: Text to synthesize (any supported language).
        voice: Fish Audio voice model ID (``reference_id``). Leave empty to use
            the backbone's built-in default voice.
        out_path: Output MP3 file path.
        api_key: Fish Audio API key. Falls back to env FISH_API_KEY /
            FISH_AUDIO_API_KEY.
        model: Backbone model — "s2-pro" (default) or "s1".
        speed: Speaking rate multiplier (0.5–2.0).
    """
    import aiohttp

    key = (
        (api_key or "").strip()
        or os.getenv("FISH_API_KEY", "").strip()
        or os.getenv("FISH_AUDIO_API_KEY", "").strip()
    )
    if not key:
        raise RuntimeError(
            "Missing Fish Audio API key (set FISH_API_KEY or config video_process.fish_api_key)"
        )

    payload_text = (text or "").strip()
    if not payload_text:
        return False

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backbone = (model or "").strip().lower() or FISH_DEFAULT_MODEL
    if backbone not in ("s1", "s2-pro"):
        backbone = FISH_DEFAULT_MODEL

    payload: dict = {
        "text": payload_text,
        "format": "mp3",
        "mp3_bitrate": 128,
        "normalize": True,
        "latency": "normal",
    }
    ref = (voice or "").strip()
    if ref:
        payload["reference_id"] = ref
    try:
        spd = float(speed)
    except (TypeError, ValueError):
        spd = 1.0
    if abs(spd - 1.0) > 0.01:
        payload["prosody"] = {"speed": max(0.5, min(2.0, spd))}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "model": backbone,
    }

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(FISH_TTS_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status == 401:
                raise RuntimeError("Fish Audio API key không hợp lệ (401 Unauthorized)")
            if resp.status == 402:
                raise RuntimeError("Fish Audio hết credit / cần nạp tiền (402 Payment Required)")
            if resp.status == 422:
                body = await resp.text()
                raise RuntimeError(f"Fish Audio request không hợp lệ (422): {body[:200]}")
            if resp.status == 429:
                raise RuntimeError("Fish Audio rate limit (429)")
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Fish Audio TTS lỗi {resp.status}: {body[:200]}")

            audio_bytes = await resp.read()
            if not audio_bytes or len(audio_bytes) < 100:
                raise RuntimeError("Fish Audio trả về audio rỗng")

            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


async def convert_voice(
    video_path: Path,
    segments: list[dict],          # [{start, end, text}] in ZH
    translated_texts: list[str],   # VI translations (same order as segments)
    output_path: Path,
    ffmpeg: str,
    tts_voice: str = "vi-VN-HoaiMyNeural",  # edge-tts voice
    tts_engine: str = "edge-tts",   # "edge-tts" | "gtts" | "fpt-ai" | "elevenlabs"
    keep_bg_music: bool = True,
    bg_volume: float = 0.15,        # background original audio volume
    tts_speed: float = 1.0,         # manual speed multiplier (1.0 = auto-fit)
    auto_speed: bool = True,        # auto-fit TTS duration to segment duration
    fpt_api_key: str = "",          # FPT AI key (nếu engine=fpt-ai)
    fpt_speed: int = 0,
    elevenlabs_api_key: str = "",   # ElevenLabs key
    elevenlabs_voice_id: str = "",  # ElevenLabs voice ID
    target_lang: str = "vi",        # ngôn ngữ đích của translated_texts
    tts_rate: str = "+0%",
    tts_pitch: str = "+0Hz",
    tts_emotion: str = "default",
    vieneu_ref_audio: str = "",
) -> tuple[bool, str]:
    """
    Replace original audio with TTS voice.
    Each segment gets its own TTS clip, placed at the correct timestamp.
    Background music from original is optionally kept at low volume.
    Supports: edge-tts, gtts, fpt-ai, elevenlabs, openai-tts, minimax.
    FPT AI tự động fallback sang ElevenLabs khi hết token.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not segments or not translated_texts:
        return False, "No segments to process"

    # Resolve ElevenLabs key/voice from env nếu không truyền vào
    el_key = (elevenlabs_api_key or "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
    el_voice = (elevenlabs_voice_id or "").strip() or ELEVENLABS_DEFAULT_VOICE_ID

    # Tự chọn engine/voice phù hợp ngôn ngữ đích (vd target=ja nhưng engine FPT
    # chỉ nói tiếng Việt → fallback edge-tts giọng Nhật).
    _lang = (target_lang or "vi").strip().lower() or "vi"
    try:
        from core.tts_catalog import resolve_engine_voice as _resolve_ev
        tts_engine, tts_voice, _ev_changed, _ev_note = _resolve_ev(
            tts_engine, tts_voice, _lang
        )
        if _ev_changed:
            logging.getLogger(__name__).info(
                "convert_voice: auto-selected TTS for lang=%s → %s/%s (%s)",
                _lang, tts_engine, tts_voice, _ev_note,
            )
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="voice_") as tmpdir:
        tmpdir = Path(tmpdir)

        # copy video to temp
        tmp_video = tmpdir / "input.mp4"
        shutil.copy2(str(video_path), str(tmp_video))

        # get video duration
        dur_result2 = subprocess.run(
            [ffmpeg, "-i", str(tmp_video), "-f", "null", "-"],
            capture_output=True, text=True
        )
        video_duration = 0.0
        for line in dur_result2.stderr.splitlines():
            m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', line)
            if m:
                video_duration = int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))
                break

        if video_duration <= 0:
            video_duration = segments[-1]['end'] + 2.0 if segments else 60.0

        # Build MultiProviderTTS để xử lý tất cả engines + fallback
        tts_provider = MultiProviderTTS(
            voice=tts_voice,
            engine=tts_engine,
            fpt_api_key=fpt_api_key,
            fpt_speed=fpt_speed,
            tts_lang=_lang,
            tts_rate=tts_rate,
            tts_pitch=tts_pitch,
            tts_emotion=tts_emotion,
            elevenlabs_api_key=el_key,
            elevenlabs_voice_id=el_voice,
            fpt_fallback_elevenlabs=bool(el_key),
            vieneu_ref_audio=vieneu_ref_audio,
        )

        # Generate TTS for each segment
        tts_clips = []
        for i, (seg, vi_text) in enumerate(zip(segments, translated_texts)):
            if not vi_text or not vi_text.strip():
                continue
            clip_path = tmpdir / f"tts_{i:04d}.mp3"
            try:
                ok = await tts_provider.generate(vi_text.strip(), clip_path)
                if ok:
                    seg_dur = seg["end"] - seg["start"]
                    # Get TTS clip duration
                    tts_dur = _get_audio_duration(ffmpeg, clip_path)
                    # Compute speed: auto-fit or manual
                    speed = tts_speed
                    if auto_speed and tts_dur > 0 and seg_dur > 0:
                        auto = tts_dur / seg_dur  # how much faster needed
                        # clamp between 0.5x and 3.0x
                        auto = max(0.85, min(1.25, auto))
                        speed = auto * tts_speed
                        speed = max(0.85, min(1.25, speed))
                    # Apply speed with atempo if needed
                    if abs(speed - 1.0) > 0.05:
                        sped_path = tmpdir / f"tts_{i:04d}_fast.mp3"
                        _apply_atempo(ffmpeg, clip_path, sped_path, speed)
                        if sped_path.exists():
                            clip_path = sped_path
                    tts_clips.append({
                        "path": clip_path,
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": vi_text,
                    })
            except Exception:
                pass  # skip failed clips

        if not tts_clips:
            return False, "No TTS clips generated"

        # Build silent base audio track (same duration as video)
        silent_path = tmpdir / "silent.wav"
        run_ffmpeg([
            ffmpeg, "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(video_duration),
            str(silent_path), "-y", "-loglevel", "error"
        ])

        # Mix all TTS clips into a single audio track using amix/adelay
        # Build complex filter: each clip delayed to its start time
        inputs = ["-i", str(silent_path)]
        filter_parts = []
        mix_inputs = ["[0:a]"]

        for j, clip in enumerate(tts_clips):
            inputs += ["-i", str(clip["path"])]
            delay_ms = int(clip["start"] * 1000)
            filter_parts.append(
                f"[{j+1}:a]adelay={delay_ms}|{delay_ms}[d{j}]"
            )
            mix_inputs.append(f"[d{j}]")

        n_mix = len(mix_inputs)
        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={n_mix}:duration=first:dropout_transition=0[tts_mix]"
        )

        if keep_bg_music:
            # extract original audio at low volume
            orig_audio = tmpdir / "orig_audio.wav"
            run_ffmpeg([
                ffmpeg, "-i", str(tmp_video),
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                str(orig_audio), "-y", "-loglevel", "error"
            ])
            if orig_audio.exists():
                inputs += ["-i", str(orig_audio)]
                bg_idx = len(tts_clips) + 1
                filter_parts.append(
                    f"[{bg_idx}:a]volume={bg_volume}[bg];"
                    f"[tts_mix][bg]amix=inputs=2:duration=first[final_audio]"
                )
                final_audio_label = "[final_audio]"
            else:
                filter_parts[-1] = filter_parts[-1].replace("[tts_mix]", "[tts_mix]").replace(
                    "amix=inputs=" + str(n_mix), "amix=inputs=" + str(n_mix)
                )
                final_audio_label = "[tts_mix]"
        else:
            final_audio_label = "[tts_mix]"

        filter_complex = ";".join(filter_parts)

        # Combine: original video + new audio
        cmd = [ffmpeg] + inputs + [
            "-i", str(tmp_video),
            "-filter_complex", filter_complex,
            "-map", f"{len(inputs)-1}:v",  # video from last input (original)
            "-map", final_audio_label,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path), "-y", "-loglevel", "error"
        ]
        ok, err = run_ffmpeg(cmd, "voice mix")
        if not ok:
            return False, f"ffmpeg mix failed: {err}"

    return True, ""


MINIMAX_TTS_ENDPOINT = "https://api.minimax.chat/v1/t2a_v2"


async def _tts_minimax(
    text: str,
    voice: str,
    out_path: Path,
    api_key: str = "",
    model: str = "speech-01-turbo",
    speed: float = 1.0,
    language: str = "",
) -> bool:
    """Generate TTS using MiniMax API."""
    import aiohttp
    import binascii
    key = (api_key or "").strip() or os.getenv("MINIMAX_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing MiniMax API key (set MINIMAX_API_KEY)")
    payload_text = (text or "").strip()
    if not payload_text:
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model or "speech-01-turbo",
        "text": payload_text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice or "male-qn-qingse",
            "speed": speed,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post(MINIMAX_TTS_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"MiniMax TTS error {resp.status}: {body[:200]}")
            res_data = await resp.json(content_type=None)
            audio_hex = (res_data.get("data") or {}).get("audio") or ""
            if not audio_hex:
                raise RuntimeError(f"MiniMax TTS returned empty audio: {res_data}")
            audio_bytes = binascii.unhexlify(audio_hex)
            out_path.write_bytes(audio_bytes)
            return out_path.exists() and out_path.stat().st_size > 0


# Compatibility alias for app.py
_preload_vieneu_model = _get_vieneu_tts


"""TTS Blueprint — /api/tts_preview, /api/tts_from_ass, /api/hf_voices/* routes."""
import asyncio
import io
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, Response
from flask import stream_with_context
from core_app import load_cfg, LOGGER, ROOT, VOICES_DIR

bp = Blueprint("tts", __name__)


@bp.route("/api/tts/engines", methods=["GET"])
def tts_engines():
    include_9router = str(request.args.get("include_9router", "1")).lower() not in ("0", "false", "no")
    try:
        from core.tts_catalog import all_tts_engines
        engines, nine_router = all_tts_engines(load_cfg(), include_9router=include_9router)
        return jsonify({"ok": True, "engines": engines, "nine_router": nine_router})
    except Exception as exc:
        from core.tts_catalog import local_tts_engines
        return jsonify({
            "ok": True,
            "engines": local_tts_engines(),
            "nine_router": {"reachable": False, "error": str(exc)},
        })


def _build_fx_filter(p: dict) -> str:
    """Build ffmpeg audio filter chain from FX params dict.
    Returns empty string if all defaults (no real change)."""
    if not p:
        return ""
    parts = []
    try:
        # Pitch shift (semitones) using rubberband if available, else asetrate+atempo
        pitch = float(p.get("pitch") or 0.0)
        if abs(pitch) > 0.05:
            # rubberband filter requires libsamplerate; use asetrate+aresample fallback
            factor = 2 ** (pitch / 12.0)
            new_rate = int(44100 * factor)
            tempo = 1.0 / factor
            tempo_chain = []
            t = tempo
            while t < 0.5:
                tempo_chain.append("atempo=0.5"); t *= 2.0
            while t > 2.0:
                tempo_chain.append("atempo=2.0"); t /= 2.0
            tempo_chain.append(f"atempo={t:.6f}")
            parts.append(f"asetrate={new_rate}")
            parts.extend(tempo_chain)
            parts.append("aresample=44100")
        speed = float(p.get("speed") or 1.0)
        if abs(speed - 1.0) > 0.02:
            s = max(0.5, min(2.0, speed))
            parts.append(f"atempo={s:.4f}")
        # 3-band EQ
        bass = int(p.get("bass") or 0)
        mid = int(p.get("mid") or 0)
        treble = int(p.get("treble") or 0)
        if bass:
            parts.append(f"bass=g={bass}")
        if mid:
            parts.append(f"equalizer=f=1000:t=q:w=1.0:g={mid}")
        if treble:
            parts.append(f"treble=g={treble}")
        # Compression
        comp = str(p.get("compression") or "none").lower()
        if comp == "light":
            parts.append("acompressor=threshold=-20dB:ratio=3:attack=20:release=250")
        elif comp == "heavy":
            parts.append("acompressor=threshold=-24dB:ratio=6:attack=10:release=200")
        # Reverb (very simple aecho approximation)
        reverb = int(p.get("reverb") or 0)
        if reverb > 0:
            decay = max(0.05, min(0.95, reverb / 100.0))
            parts.append(f"aecho=0.8:0.88:60:{decay:.2f}")
    except Exception:
        return ""
    return ",".join(parts)


# ── /api/tts_preview ─────────────────────────────────────────────────────────
@bp.route("/api/tts_preview", methods=["POST"])
def tts_preview():
    data = request.json or {}
    text = str(data.get("text") or "").strip()
    tts_engine = str(data.get("tts_engine") or "edge-tts").strip().lower()
    tts_voice = str(data.get("tts_voice") or "banmai").strip()
    tts_pitch = str(data.get("tts_pitch") or "+0Hz").strip()
    tts_rate = str(data.get("tts_rate") or "+0%").strip()
    tts_emotion = str(data.get("tts_emotion") or "default").strip()

    if not text:
        return jsonify({"ok": False, "error": "Text preview is empty"}), 400

    try:
        from core.video_processor import _tts_edge, _tts_gtts, _tts_fpt_ai, _tts_elevenlabs, _tts_nine_router, FPT_TTS_DEFAULT_KEY, ELEVENLABS_DEFAULT_VOICE_ID
        cfg = load_cfg()
        vp_cfg = cfg.get("video_process") or {}
        fpt_api_key = (
            str(data.get("fpt_api_key") or "").strip()
            or str(vp_cfg.get("fpt_api_key") or "").strip()
            or FPT_TTS_DEFAULT_KEY
        )
        fpt_speed = int(data.get("fpt_speed") or 0)
        elevenlabs_api_key = (
            str(data.get("elevenlabs_api_key") or "").strip()
            or str(vp_cfg.get("elevenlabs_api_key") or "").strip()
            or os.environ.get("ELEVENLABS_API_KEY", "").strip()
        )
        elevenlabs_voice_id = (
            str(data.get("elevenlabs_voice_id") or "").strip()
            or str(vp_cfg.get("elevenlabs_voice_id") or "").strip()
            or ELEVENLABS_DEFAULT_VOICE_ID
        )

        fx_enabled = bool(data.get("fx_enabled", False))
        fx_params = {
            "pitch":   float(data.get("fx_pitch",  1.5)),
            "speed":   float(data.get("fx_speed",  1.08)),
            "bass":    float(data.get("fx_bass",   -2)),
            "mid":     float(data.get("fx_mid",    2)),
            "treble":  float(data.get("fx_treble", 3)),
            "comp":    str(data.get("fx_comp",     "none")),
            "reverb":  float(data.get("fx_reverb", 0)),
        }

        with tempfile.TemporaryDirectory(prefix="tts_preview_") as tmpdir:
            out_path = Path(tmpdir) / "preview.mp3"
            try:
                if tts_engine == "9router" or tts_engine.startswith("9r:"):
                    ok = asyncio.run(_tts_nine_router(
                        text, tts_voice, out_path,
                        engine=tts_engine,
                        language=str(data.get("tts_lang") or data.get("language") or ""),
                    ))
                elif tts_engine == "gtts":
                    ok = _tts_gtts(text, str(data.get("tts_lang") or data.get("language") or "vi"), out_path)
                elif tts_engine == "fpt-ai":
                    try:
                        ok = asyncio.run(_tts_fpt_ai(text, tts_voice, out_path, fpt_api_key, fpt_speed))
                    except Exception as fpt_err:
                        # Fallback sang ElevenLabs nếu FPT thất bại và có key
                        if elevenlabs_api_key:
                            LOGGER.warning("FPT TTS preview thất bại (%s), fallback ElevenLabs", fpt_err)
                            ok = asyncio.run(_tts_elevenlabs(text, elevenlabs_voice_id, out_path, elevenlabs_api_key))
                        else:
                            raise
                elif tts_engine == "elevenlabs":
                    ok = asyncio.run(_tts_elevenlabs(text, tts_voice, out_path, elevenlabs_api_key))
                elif tts_engine == "fish-audio":
                    from core.video_processor import _tts_fish
                    fish_cfg = vp_cfg
                    fish_key = (
                        str(data.get("fish_api_key") or "").strip()
                        or str(fish_cfg.get("fish_api_key") or "").strip()
                        or os.environ.get("FISH_API_KEY", "").strip()
                        or os.environ.get("FISH_AUDIO_API_KEY", "").strip()
                    )
                    fish_model = str(data.get("fish_model") or fish_cfg.get("fish_model") or "s2-pro").strip()
                    ok = asyncio.run(_tts_fish(
                        text, tts_voice, out_path,
                        api_key=fish_key, model=fish_model,
                    ))
                elif tts_engine == "minimax":
                    from core.video_processor import _tts_minimax
                    ok = asyncio.run(_tts_minimax(
                        text, tts_voice, out_path,
                        language=str(data.get("tts_lang") or data.get("language") or ""),
                    ))
                elif tts_engine == "huggingface":
                    return jsonify({"ok": False, "error": "HuggingFace TTS not supported in this version"}), 400
                else:
                    ok = asyncio.run(_tts_edge(text, tts_voice, out_path, rate=tts_rate, pitch=tts_pitch, style=tts_emotion))
            except Exception as inner_e:
                return jsonify({"ok": False, "error": f"TTS generation failed: {str(inner_e)}"}), 500

            if not ok or (not out_path.exists()) or out_path.stat().st_size <= 0:
                return jsonify({"ok": False, "error": "Unable to synthesize preview audio (empty file)"}), 500

            if fx_enabled:
                from core.video_processor import find_ffmpeg, apply_audio_effects
                ffmpeg = find_ffmpeg()
                if ffmpeg:
                    fx_out = Path(tmpdir) / "preview_fx.mp3"
                    try:
                        apply_audio_effects(
                            input_path=out_path,
                            output_path=fx_out,
                            ffmpeg=ffmpeg,
                            pitch_semitones=fx_params["pitch"],
                            speed=fx_params["speed"],
                            bass=int(fx_params["bass"]),
                            mid=int(fx_params["mid"]),
                            treble=int(fx_params["treble"]),
                            compression=fx_params["comp"],
                            reverb=int(fx_params["reverb"]),
                        )
                        if fx_out.exists() and fx_out.stat().st_size > 0:
                            out_path = fx_out
                    except Exception:
                        pass  # fallback to non-fx audio

            audio_data = io.BytesIO(out_path.read_bytes())
            audio_data.seek(0)
            return send_file(audio_data, mimetype="audio/mpeg", as_attachment=False, download_name="preview.mp3")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/tts_from_ass ─────────────────────────────────────────────────────────
@bp.route("/api/tts_from_ass", methods=["POST"])
def tts_from_ass():
    import asyncio as _asyncio
    from core.video_processor import (
        find_ffmpeg, FPT_TTS_DEFAULT_KEY,
        _parse_ass_file, _merge_segments_for_tts, MultiProviderTTS, _run_ffmpeg,
        ELEVENLABS_DEFAULT_VOICE_ID,
    )

    data = {}
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        data.update(request.get_json(silent=True) or {})

    uploaded_file = request.files.get("ass_file") if request.files else None
    ass_path = None
    tmp_upload_dir = None

    if uploaded_file and uploaded_file.filename:
        tmp_upload_dir = Path(tempfile.mkdtemp(prefix="tts_ass_upload_"))
        ass_path = tmp_upload_dir / uploaded_file.filename
        uploaded_file.save(str(ass_path))
        if not str(data.get("output_dir") or "").strip():
            data["output_dir"] = str(ROOT / "Downloaded")
    else:
        ass_path = Path(str(data.get("ass_path") or "").strip())

    tts_engine  = str(data.get("tts_engine")  or "edge-tts").lower()
    tts_voice   = str(data.get("tts_voice")   or "vi-VN-HoaiMyNeural")
    tts_pitch   = str(data.get("tts_pitch")   or "+0Hz")
    tts_rate    = str(data.get("tts_rate")    or "+0%")
    tts_emotion = str(data.get("tts_emotion") or "default")
    fx_enabled  = str(data.get("fx_enabled")  or "false").lower() in ("true", "1")
    fx_params = {
        "pitch":       float(data.get("fx_pitch")   or 1.5),
        "speed":       float(data.get("fx_speed")   or 1.08),
        "bass":        int(float(data.get("fx_bass")    or -2)),
        "mid":         int(float(data.get("fx_mid")     or 2)),
        "treble":      int(float(data.get("fx_treble")  or 3)),
        "compression": str(data.get("fx_comp")    or "light"),
        "reverb":      int(float(data.get("fx_reverb")  or 5)),
    }
    output_dir = str(data.get("output_dir") or "").strip()

    cfg = load_cfg()
    vp_cfg = cfg.get("video_process") or {}
    fpt_api_key = (
        str(data.get("fpt_api_key") or "").strip()
        or str(vp_cfg.get("fpt_api_key") or "").strip()
        or FPT_TTS_DEFAULT_KEY
    )
    elevenlabs_api_key = (
        str(data.get("elevenlabs_api_key") or "").strip()
        or str(vp_cfg.get("elevenlabs_api_key") or "").strip()
        or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    )
    elevenlabs_voice_id = (
        str(data.get("elevenlabs_voice_id") or "").strip()
        or str(vp_cfg.get("elevenlabs_voice_id") or "").strip()
        or ""
    )

    def _emit(log_lines: list, msg: str, level: str = "info", pct: int = None):
        log_lines.append(f"[{level.upper()}] {msg}")
        payload = {"log": msg, "level": level}
        if pct is not None:
            payload["overall"] = pct
            payload["overall_lbl"] = msg
        return json.dumps(payload, ensure_ascii=False) + "\n"

    def generate():
        log_lines = []
        ffmpeg = find_ffmpeg()

        if not ffmpeg:
            yield _emit(log_lines, "FFmpeg không tìm thấy.", "error", 0)
            return

        if not ass_path or not ass_path.exists():
            yield _emit(log_lines, f"File .ass không tồn tại: {ass_path}", "error", 0)
            return

        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
        else:
            out_dir = ass_path.parent

        out_mp3 = out_dir / (ass_path.stem + "_tts.mp3")
        log_file = out_dir / (ass_path.stem + "_tts.log")

        yield _emit(log_lines, f"📂 File ASS: {ass_path}", "info", 0)
        yield _emit(log_lines, f"📁 Thư mục xuất: {out_dir}", "info", 2)

        try:
            segments = _parse_ass_file(ass_path)
            if not segments:
                yield _emit(log_lines, "Không tìm thấy dialogue trong file .ass", "error", 0)
                return
            raw_count = len(segments)
            segments = _merge_segments_for_tts(segments)

            yield _emit(log_lines, f"✅ Đọc được {raw_count} dòng ASS, gộp thành {len(segments)} đoạn đọc tự nhiên", "info", 5)

            with tempfile.TemporaryDirectory(prefix="tts_ass_") as tmpdir:
                tmpdir = Path(tmpdir)
                tts = MultiProviderTTS(
                    voice=tts_voice, engine=tts_engine,
                    fpt_api_key=fpt_api_key, fpt_speed=0,
                    elevenlabs_api_key=elevenlabs_api_key,
                    elevenlabs_voice_id=elevenlabs_voice_id,
                    fish_api_key=(
                        str(data.get("fish_api_key") or "").strip()
                        or str(vp_cfg.get("fish_api_key") or "").strip()
                        or os.environ.get("FISH_API_KEY", "").strip()
                        or os.environ.get("FISH_AUDIO_API_KEY", "").strip()
                    ),
                    fish_model=str(data.get("fish_model") or vp_cfg.get("fish_model") or "s2-pro"),
                    fish_reference_id=str(data.get("fish_reference_id") or vp_cfg.get("fish_reference_id") or ""),
                )
                translations = [s.get("text", "") for s in segments]

                yield _emit(log_lines, f"🎙 Bắt đầu tổng hợp giọng ({tts_engine}, {tts_voice})...", "info", 10)

                clips = _asyncio.run(tts.generate_all(
                    segments, translations, tmpdir,
                    max_concurrency=2, retries=2,
                    tts_speed=1.0, auto_speed=False, ffmpeg=ffmpeg,
                ))

                if not clips:
                    yield _emit(log_lines, "Không tạo được clip TTS nào.", "error", 0)
                    return

                yield _emit(log_lines, f"✅ Tổng hợp xong {len(clips)} clip", "info", 70)

                yield _emit(log_lines, "🔗 Đang ghép các clip thành file MP3...", "info", 80)
                concat_list = tmpdir / "concat.txt"
                with open(str(concat_list), "w", encoding="utf-8") as f:
                    for c in clips:
                        f.write(f"file '{str(c['path']).replace(chr(92), '/')}'\n")

                concat_target = (tmpdir / "concat.mp3") if fx_enabled else out_mp3
                ok, err = _run_ffmpeg([
                    ffmpeg, "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c:a", "libmp3lame", "-b:a", "128k",
                    str(concat_target), "-y", "-loglevel", "error"
                ])

                if not ok:
                    yield _emit(log_lines, f"❌ Ghép MP3 thất bại: {err}", "error", 0)
                    return

                if fx_enabled:
                    yield _emit(log_lines, "🎛 Đang áp dụng hiệu ứng FX...", "info", 90)
                    fx_chain = _build_fx_filter(fx_params)
                    if not fx_chain:
                        # fx all default → just rename
                        import shutil as _sh
                        _sh.copyfile(str(concat_target), str(out_mp3))
                    else:
                        ok, err = _run_ffmpeg([
                            ffmpeg, "-i", str(concat_target),
                            "-filter:a", fx_chain,
                            "-c:a", "libmp3lame", "-b:a", "128k",
                            str(out_mp3), "-y", "-loglevel", "error"
                        ])
                        if not ok:
                            yield _emit(log_lines, f"⚠ FX thất bại, dùng bản chưa FX: {err}", "warning", 92)
                            import shutil as _sh
                            _sh.copyfile(str(concat_target), str(out_mp3))

            yield _emit(log_lines, f"✅ Hoàn thành! File MP3: {out_mp3}", "success", 100)
            yield json.dumps({"ok": True, "output_path": str(out_mp3), "clips": len(clips)}, ensure_ascii=False) + "\n"

        except Exception as exc:
            LOGGER.exception("tts_from_ass error")
            yield _emit(log_lines, f"❌ Lỗi: {exc}", "error", 0)
        finally:
            try:
                with open(str(log_file), "w", encoding="utf-8") as lf:
                    lf.write(f"=== TTS from ASS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                    lf.write(f"ASS: {ass_path}\n")
                    lf.write(f"Engine: {tts_engine} | Voice: {tts_voice} | FX: {fx_enabled}\n\n")
                    lf.write("\n".join(log_lines))
                    lf.write("\n")
            except Exception:
                pass
            if tmp_upload_dir:
                shutil.rmtree(str(tmp_upload_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ── /api/tts_to_mp3 ───────────────────────────────────────────────────────────
def _split_text_to_chunks(text: str, max_chars: int = 800) -> list:
    """Split long text into chunks at sentence boundaries (max_chars per chunk).

    Strategy:
    1. First split by paragraph breaks (\n\n or \n).
    2. Within each paragraph, split by sentence terminators (. ! ? ... 。！？).
    3. Greedily pack sentences into chunks <= max_chars.
    4. If a single sentence is too long, hard-split by max_chars.
    """
    import re

    text = (text or "").strip()
    if not text:
        return []

    # Split into sentences while keeping terminators
    # Vietnamese/Chinese/English punctuation
    sent_re = re.compile(r"(?<=[\.\!\?。！？\n])\s+")
    raw_paragraphs = re.split(r"\n\s*\n", text)
    sentences = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        # Split into sentences
        parts = sent_re.split(para)
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)

    chunks = []
    cur = ""
    for s in sentences:
        # If a single sentence is itself too long, hard-split
        if len(s) > max_chars:
            if cur:
                chunks.append(cur.strip())
                cur = ""
            for i in range(0, len(s), max_chars):
                chunks.append(s[i:i + max_chars].strip())
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


@bp.route("/api/tts_to_mp3", methods=["POST"])
def tts_to_mp3():
    """Generate one MP3 from raw text. Supports long text by chunking + concat.

    Request JSON:
      text, tts_engine, tts_voice, tts_pitch, tts_rate, tts_emotion,
      fx_*, fpt_api_key, elevenlabs_api_key, elevenlabs_voice_id (optional)

    Returns: audio/mpeg stream (MP3) or JSON error.
    """
    import asyncio as _asyncio
    from core.video_processor import (
        _tts_edge, _tts_gtts, _tts_fpt_ai, _tts_elevenlabs, _tts_nine_router,
        FPT_TTS_DEFAULT_KEY, ELEVENLABS_DEFAULT_VOICE_ID,
        find_ffmpeg, _run_ffmpeg,
    )

    data = request.json or {}
    text = str(data.get("text") or "").strip()
    tts_engine = str(data.get("tts_engine") or "edge-tts").strip().lower()
    tts_voice = str(data.get("tts_voice") or "banmai").strip()
    tts_pitch = str(data.get("tts_pitch") or "+0Hz").strip()
    tts_rate = str(data.get("tts_rate") or "+0%").strip()
    tts_emotion = str(data.get("tts_emotion") or "default").strip()

    if not text:
        return jsonify({"ok": False, "error": "Text is empty"}), 400

    cfg = load_cfg()
    vp_cfg = cfg.get("video_process") or {}
    fpt_api_key = (
        str(data.get("fpt_api_key") or "").strip()
        or str(vp_cfg.get("fpt_api_key") or "").strip()
        or FPT_TTS_DEFAULT_KEY
    )
    fpt_speed = int(data.get("fpt_speed") or 0)
    elevenlabs_api_key = (
        str(data.get("elevenlabs_api_key") or "").strip()
        or str(vp_cfg.get("elevenlabs_api_key") or "").strip()
        or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    )
    elevenlabs_voice_id = (
        str(data.get("elevenlabs_voice_id") or "").strip()
        or str(vp_cfg.get("elevenlabs_voice_id") or "").strip()
        or ELEVENLABS_DEFAULT_VOICE_ID
    )

    fx_enabled = bool(data.get("fx_enabled", False))
    fx_params = {
        "pitch":  float(data.get("fx_pitch",  1.5)),
        "speed":  float(data.get("fx_speed",  1.08)),
        "bass":   float(data.get("fx_bass",   -2)),
        "mid":    float(data.get("fx_mid",    2)),
        "treble": float(data.get("fx_treble", 3)),
        "comp":   str(data.get("fx_comp",     "none")),
        "reverb": float(data.get("fx_reverb", 0)),
    }

    # Pick chunk size by engine
    if tts_engine == "fpt-ai":
        max_chars = 700
    elif tts_engine == "gtts":
        max_chars = 200
    elif tts_engine == "elevenlabs":
        max_chars = 2500  # ElevenLabs supports up to 5000 chars
    elif tts_engine == "fish-audio":
        max_chars = 1500
    elif tts_engine == "9router" or tts_engine.startswith("9r:"):
        max_chars = 1500
    else:
        max_chars = 1500

    chunks = _split_text_to_chunks(text, max_chars=max_chars)
    if not chunks:
        return jsonify({"ok": False, "error": "Cannot split text"}), 400

    LOGGER.info(f"tts_to_mp3: engine={tts_engine}, voice={tts_voice}, chars={len(text)}, chunks={len(chunks)}")

    try:
        with tempfile.TemporaryDirectory(prefix="tts_to_mp3_") as tmpdir:
            tmpdir = Path(tmpdir)
            clip_paths = []

            # Generate each chunk
            for idx, chunk in enumerate(chunks):
                clip_path = tmpdir / f"chunk_{idx:04d}.mp3"
                try:
                    if tts_engine == "9router" or tts_engine.startswith("9r:"):
                        ok = _asyncio.run(_tts_nine_router(
                            chunk, tts_voice, clip_path,
                            engine=tts_engine,
                            language=str(data.get("tts_lang") or data.get("language") or ""),
                        ))
                    elif tts_engine == "gtts":
                        ok = _tts_gtts(chunk, str(data.get("tts_lang") or data.get("language") or "vi"), clip_path)
                    elif tts_engine == "elevenlabs":
                        ok = _asyncio.run(_tts_elevenlabs(chunk, tts_voice, clip_path, elevenlabs_api_key))
                    elif tts_engine == "fish-audio":
                        from core.video_processor import _tts_fish
                        fish_key = (
                            str(data.get("fish_api_key") or "").strip()
                            or str(vp_cfg.get("fish_api_key") or "").strip()
                            or os.environ.get("FISH_API_KEY", "").strip()
                            or os.environ.get("FISH_AUDIO_API_KEY", "").strip()
                        )
                        fish_model = str(data.get("fish_model") or vp_cfg.get("fish_model") or "s2-pro").strip()
                        ok = _asyncio.run(_tts_fish(
                            chunk, tts_voice, clip_path,
                            api_key=fish_key, model=fish_model,
                        ))
                    elif tts_engine == "fpt-ai":
                        try:
                            ok = _asyncio.run(_tts_fpt_ai(chunk, tts_voice, clip_path, fpt_api_key, fpt_speed))
                        except Exception as fpt_err:
                            # Fallback FPT → ElevenLabs khi hết token
                            if elevenlabs_api_key:
                                LOGGER.warning("FPT hết token chunk %d, fallback ElevenLabs: %s", idx + 1, fpt_err)
                                ok = _asyncio.run(_tts_elevenlabs(chunk, elevenlabs_voice_id, clip_path, elevenlabs_api_key))
                            else:
                                raise
                    elif tts_engine == "minimax":
                        from core.video_processor import _tts_minimax
                        ok = _asyncio.run(_tts_minimax(
                            chunk, tts_voice, clip_path,
                            language=str(data.get("tts_lang") or data.get("language") or ""),
                        ))
                    else:
                        # edge-tts (default)
                        ok = _asyncio.run(_tts_edge(
                            chunk, tts_voice, clip_path,
                            rate=tts_rate, pitch=tts_pitch, style=tts_emotion,
                        ))
                except Exception as inner_e:
                    return jsonify({
                        "ok": False,
                        "error": f"TTS failed at chunk {idx + 1}/{len(chunks)}: {inner_e}",
                    }), 500

                if not ok or (not clip_path.exists()) or clip_path.stat().st_size <= 0:
                    return jsonify({
                        "ok": False,
                        "error": f"Empty audio at chunk {idx + 1}/{len(chunks)}",
                    }), 500

                clip_paths.append(clip_path)

            # If only 1 chunk, no need to concat
            if len(clip_paths) == 1:
                final_path = clip_paths[0]
            else:
                ffmpeg = find_ffmpeg()
                if not ffmpeg:
                    return jsonify({
                        "ok": False,
                        "error": "FFmpeg required to merge multi-chunk audio. Install ffmpeg.",
                    }), 500

                concat_list = tmpdir / "concat.txt"
                with open(str(concat_list), "w", encoding="utf-8") as f:
                    for c in clip_paths:
                        # ffmpeg concat demuxer needs forward slashes / escaped quotes
                        cp = str(c).replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{cp}'\n")

                merged = tmpdir / "merged.mp3"
                ok, err = _run_ffmpeg([
                    ffmpeg, "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c:a", "libmp3lame", "-b:a", "128k",
                    str(merged), "-y", "-loglevel", "error",
                ])
                if not ok or not merged.exists() or merged.stat().st_size <= 0:
                    return jsonify({"ok": False, "error": f"Merge failed: {err}"}), 500
                final_path = merged

            # Apply FX if enabled
            if fx_enabled:
                from core.video_processor import find_ffmpeg, apply_audio_effects
                ffmpeg = find_ffmpeg()
                if ffmpeg:
                    fx_out = tmpdir / "final_fx.mp3"
                    try:
                        apply_audio_effects(
                            input_path=final_path,
                            output_path=fx_out,
                            ffmpeg=ffmpeg,
                            pitch_semitones=fx_params["pitch"],
                            speed=fx_params["speed"],
                            bass=int(fx_params["bass"]),
                            mid=int(fx_params["mid"]),
                            treble=int(fx_params["treble"]),
                            compression=fx_params["comp"],
                            reverb=int(fx_params["reverb"]),
                        )
                        if fx_out.exists() and fx_out.stat().st_size > 0:
                            final_path = fx_out
                    except Exception:
                        pass  # fall back to non-fx audio

            audio_data = io.BytesIO(final_path.read_bytes())
            audio_data.seek(0)
            return send_file(
                audio_data,
                mimetype="audio/mpeg",
                as_attachment=False,
                download_name="tts.mp3",
            )

    except Exception as e:
        LOGGER.exception("tts_to_mp3 failed")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/hf_voices ────────────────────────────────────────────────────────────
@bp.route("/api/hf_voices", methods=["GET"])
def list_hf_voices():
    voices = []
    for f in VOICES_DIR.glob("*"):
        if f.suffix in (".npy", ".pt"):
            voices.append({"name": f.name, "path": str(f.absolute())})
    return jsonify({"ok": True, "voices": voices})


@bp.route("/api/hf_voices/upload", methods=["POST"])
def upload_hf_voice():
    import os
    import sys
    import types
    import subprocess
    import numpy as np
    from werkzeug.utils import secure_filename

    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "No audio file uploaded"}), 400
    file = request.files["audio"]
    name = str(request.form.get("name") or "voice").strip()
    name = secure_filename(name)
    if not name:
        name = "voice"
    if not name.endswith(".npy"):
        name += ".npy"

    out_path = VOICES_DIR / name
    if out_path.exists():
        return jsonify({"ok": False, "error": "Tên giọng này đã tồn tại"}), 400

    try:
        import torch
        import torchaudio

        mock_m = types.ModuleType("mock_m")
        sys.modules["k2"] = mock_m
        for sub in ["k2", "k2_fsa", "nlp"]:
            sys.modules[f"speechbrain.integrations.{sub}"] = mock_m
        from speechbrain.inference.speaker import EncoderClassifier

        if os.name == "nt":
            import shutil as _shutil
            if not hasattr(os, "_orig_symlink_patched"):
                os._orig_symlink_patched = True
                _orig_symlink = os.symlink
                def _force_copy_symlink(src, dst, target_is_directory=False, **kwargs):
                    try:
                        _orig_symlink(src, dst, target_is_directory=target_is_directory, **kwargs)
                    except OSError:
                        if target_is_directory:
                            _shutil.copytree(src, dst, dirs_exist_ok=True)
                        else:
                            _shutil.copy2(src, dst)
                os.symlink = _force_copy_symlink

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp_in:
            in_path = tmp_in.name
            file.save(in_path)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
            wav_path = tmp_out.name

        try:
            from core.video_processor import find_ffmpeg
            ffmpeg = find_ffmpeg()
            subprocess.run(
                [ffmpeg, "-y", "-i", in_path, "-ar", "16000", "-ac", "1", wav_path],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            return jsonify({"ok": False, "error": f"Lỗi covert audio bằng ffmpeg: {e}"}), 400

        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-xvect-voxceleb", savedir="tmpdir"
        )
        signal, fs = torchaudio.load(wav_path, backend="soundfile")
        if signal.shape[0] > 1:
            signal = torch.mean(signal, dim=0, keepdim=True)

        embeddings = classifier.encode_batch(signal)
        embeddings = embeddings.squeeze(1).detach().cpu().numpy()
        np.save(str(out_path), embeddings)

        try:
            os.unlink(in_path)
            os.unlink(wav_path)
        except Exception:
            pass

        return jsonify({"ok": True, "name": name, "path": str(out_path.absolute())})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/hf_voices/<name>", methods=["DELETE"])
def delete_hf_voice(name):
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(name)
    target = VOICES_DIR / safe_name
    if target.exists() and target.is_file():
        try:
            target.unlink()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": False, "error": "Not found"}), 404

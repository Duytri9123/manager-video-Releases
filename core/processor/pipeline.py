#!/usr/bin/env python3
"""
core.processor.pipeline
Full 5-step video processing pipeline generator:
1. Video verification
2. Whisper Transcription
3. Translation (ZH -> VI)
4. Subtitle burning & frame rendering
5. TTS voiceover generation & audio mixing
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Generator, Optional, List, Tuple, Dict, Any

from core.processor.ffmpeg_base import (
    find_ffmpeg, run_ffmpeg, _run_ffmpeg, _get_encoding_args,
    get_media_duration_seconds, _get_media_duration, _get_audio_duration,
    _safe_stem, _winlong, _as_bool, _as_int, _as_float,
    _clamp_float, _normalize_hex_rgb, _ffmpeg_color,
    _escape_drawtext_text, _fmt_hms, has_audio_track,
    _resolve_image_path, _SUPPORTED_IMAGE_EXTS, _LOGO_POSITION_MAP
)
from core.processor.effects import (
    _parse_content_aspect,
    _overlay_enable_expr, _append_video_overlay_filters, _normalize_video_overlays,
    apply_audio_effects, _build_color_grade_filter, _build_anti_fingerprint_filter,
    apply_anti_fingerprint, make_vertical_video, preview_subtitles_in_video,
    generate_thumbnail, concat_thumbnail_with_video, _gen_ai_thumbnail_for_pipeline
)
from core.processor.subtitles import (
    _fmt_srt_time, _fmt_ass_time, write_ass, _parse_time_smart,
    _parse_srt, _parse_ass_file, _merge_segments_for_tts,
    _parse_srt_text_to_segments, burn_subtitles, _burn_ass, _burn_srt,
    _hex_color, _hex_to_ass_color, _hex_to_ass_color_alpha,
    generate_frame_title, write_ass_with_frame, align_subtitles_to_voice, extract_speaker_from_text, process_speaker_tags_in_segments
)
from core.processor.transcription import (
    _GROQ_MODEL, _GROQ_MAX_MB, _whisper_model_cache,
    GroqWhisperTranscriber, AntigravityTranscriber, FasterWhisperTranscriber,
    classify_dialogue_speakers,
    transcribe_to_srt
)
from core.processor.tts import (
    FPT_TTS_ENDPOINT, FPT_TTS_DEFAULT_KEY, TTS_CACHE_VERSION,
    ELEVENLABS_TTS_ENDPOINT, ELEVENLABS_DEFAULT_VOICE_ID,
    FISH_TTS_ENDPOINT, FISH_DEFAULT_MODEL,
    _EDGE_TTS_STYLE_ALIASES, _EDGE_TTS_STYLE_VAR, _EDGE_TTS_ORIGINAL_MKSSML,
    _GEMINI_TTS_STYLE_PREFIX, _VIENEU_TTS_INSTANCE, _OMNIVOICE_MODEL,
    _split_text_for_tts, _max_tts_chars_for_engine, MultiProviderTTS,
    _apply_atempo, _edge_locale_from_voice, _normalize_edge_style,
    _install_edge_style_patch, _tts_edge, _tts_fpt_ai, _tts_openai,
    _vieneu_emotion_from_style, _vieneu_text_with_cue, _get_vieneu_tts,
    _preload_vieneu_model, _tts_vieneu, _get_omnivoice_model, _tts_omnivoice,
    _tts_gtts, _tts_elevenlabs, _tts_fish, convert_voice
)
from core.processor.audio_mixer import (
    AudioMixer, mix_external_audio, mix_multiple_external_audios
)

def process_video_full(data: dict) -> Generator[str, None, None]:
    """
    Full pipeline generator (yields NDJSON lines for streaming).
    data keys:
      video_path, model, language, out_dir,
      burn_subs, blur_original, blur_zone, blur_height_pct,
      font_size, font_color, margin_v,
      voice_convert, tts_voice, tts_engine, keep_bg_music, bg_volume,
      translate_provider (for ZH→VI translation)
    """
    import json as _j, sys

    def send(**kw):
        try:
            import eventlet
            eventlet.sleep(0.01)
        except Exception:
            pass
        return _j.dumps(kw, ensure_ascii=True) + "\n"

    import time as _pytime
    _t_pipeline_start = _pytime.time()

    data = dict(data)
    if _as_bool(data.get("frame_title_auto", False), False):
        data["frame_title"] = ""
    if _as_bool(data.get("frame_title_enabled", True), True) and not str(data.get("frame_title") or "").strip():
        analysis = data.get("ai_video_analysis") or {}
        suggestions = analysis.get("title_suggestions") or {} if isinstance(analysis, dict) else {}
        data["frame_title"] = next((str(suggestions[k]) for k in ("short", "tiktok", "youtube", "facebook") if suggestions.get(k)), "")

    video_path = Path(data.get("video_path", "")).expanduser()
    yield send(log=f"Khởi tạo tiến trình xử lý: {video_path.name}...", level="info")
    
    if not video_path.exists():
        yield send(log=f"File not found: {video_path}", level="error", failed=True, overall=0, overall_lbl="Không tìm thấy video")
        return

    ffmpeg = find_ffmpeg()
    print("=== [DEBUG] process_video_full: find_ffmpeg done ===", file=sys.stderr, flush=True)
    if not ffmpeg:
        yield send(log="ffmpeg not found. Install ffmpeg and add to PATH.", level="error", failed=True, overall=0, overall_lbl="Thiếu FFmpeg")
        return

    # Detect actual video dimensions
    try:
        import subprocess, re
        _r = subprocess.run([ffmpeg, "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        _m = re.search(r"(\d{2,5})x(\d{2,5})", _r.stderr or "")
        _vw, _vh = (int(_m.group(1)), int(_m.group(2))) if _m else (1280, 720)
    except Exception:
        _vw, _vh = 1280, 720
    print(f"=== [DEBUG] process_video_full: subprocess.run done, dim={_vw}x{_vh} ===", file=sys.stderr, flush=True)

    _target_aspect = str(data.get("target_aspect") or "auto").lower()
    _pad_blur = _as_bool(data.get("aspect_pad_blur", False), False)
    _source_is_vertical = _vh > _vw
    _aspect_should_convert = _parse_content_aspect(data.get("content_aspect")) is not None or _target_aspect in ("9x16", "16x9") and (
        (_target_aspect == "9x16" and not _source_is_vertical)
        or (_target_aspect == "16x9" and _source_is_vertical)
    )

    # Output dir logic:
    # - User chỉ định out_dir → dùng nó
    # - Nếu video gốc đã nằm trong Downloaded/Process_video/<name>/ → giữ nguyên (resume)
    # - Ngược lại → tạo Downloaded/Process_video/<safe_stem>/
    _user_out_dir = str(data.get("out_dir") or "").strip()
    if _user_out_dir:
        out_dir = Path(_user_out_dir).expanduser()
    else:
        import yaml as _yaml_cfg
        _cfg_path = Path(__file__).parent.parent / "config.yml"
        _dl_path = ""
        if _cfg_path.exists():
            try:
                _dl_path = str((_yaml_cfg.safe_load(_cfg_path.read_text(encoding="utf-8")) or {}).get("path") or "").strip()
            except Exception:
                pass

        if _dl_path:
            _base = Path(_dl_path).expanduser()
            if not _base.is_absolute():
                _base = Path(__file__).parent.parent / _base
            _process_root = (_base / "Process_video").resolve()

            # Nếu video gốc đã nằm trong Process_video/<x>/ thì dùng chính folder đó
            try:
                _vp_resolved = video_path.resolve()
                if _process_root in _vp_resolved.parents:
                    out_dir = _vp_resolved.parent
                else:
                    # Tạo thư mục riêng cho video này (theo stem an toàn)
                    _safe_stem_for_dir = _safe_stem(video_path.stem) or "video"
                    out_dir = _process_root / _safe_stem_for_dir
            except Exception:
                _safe_stem_for_dir = _safe_stem(video_path.stem) or "video"
                out_dir = _process_root / _safe_stem_for_dir
        else:
            out_dir = video_path.parent
    print(f"=== [DEBUG] process_video_full: out_dir determined={out_dir} ===", file=sys.stderr, flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_title = str(data.get("video_title") or "").strip()
    stem_source = video_title or video_path.stem
    stem = _safe_stem(stem_source)

    do_burn = _as_bool(data.get("burn_subs", True), True)
    do_voice = _as_bool(data.get("voice_convert", False), False)
    cleanup_outputs = _as_bool(data.get("cleanup_outputs", True), True)
    delete_source_after = _as_bool(data.get("delete_source_after_process", False), False)
    # Default: always translate to VI and burn VI subtitles
    do_translate = _as_bool(data.get("translate_subs", True), True)
    do_burn_vi = _as_bool(data.get("burn_vi_subs", True), True)
    model_name = data.get("model", "base")
    language = data.get("language", "zh")
    target_language = str(data.get("target_language", "vi") or "vi").strip().lower()
    _LANG_NAMES = {
        "vi": "tiếng Việt", "en": "English", "ja": "日本語", "ko": "한국어",
        "th": "ภาษาไทย", "id": "Bahasa Indonesia", "es": "Español",
        "pt": "Português", "fr": "Français", "de": "Deutsch",
        "ru": "Русский", "ar": "العربية", "hi": "हिन्दी", "zh": "中文",
    }
    target_lang_name = _LANG_NAMES.get(target_language, target_language)
    process_mode = str(data.get("process_mode", "ai") or "ai").strip().lower()
    transcribe_provider = str(data.get("transcribe_provider", "") or "").strip().lower()
    if not transcribe_provider:
        try:
            from templates.pages.config.route import load_providers_from_db
            all_provs = load_providers_from_db()
            for p_name in ["antigravity", "groq", "openai"]:
                if p_name in all_provs and any(c.get("enabled") for c in all_provs[p_name].get("connections", [])):
                    transcribe_provider = p_name
                    break
        except Exception:
            pass
        if not transcribe_provider:
            transcribe_provider = "antigravity"

    subtitle_pos = str(data.get("subtitle_position", "bottom")).lower()
    blur_zone = str(data.get("blur_zone", "bottom")).lower()
    blur_enabled = _as_bool(data.get("blur_original", True), True)
    blur_height_pct = _clamp_float(_as_float(data.get("blur_height_pct", 0.15), 0.15), 0.08, 0.45)
    blur_lift_pct = _clamp_float(_as_float(data.get("blur_lift_pct", 0.06), 0.06), 0.0, 0.20)

    user_margin_v = data.get("margin_v")
    effective_margin_v = _as_int(user_margin_v, 20) if user_margin_v is not None else 20
    # Only auto-calculate margin when user has NOT explicitly set it
    if subtitle_pos == "bottom" and user_margin_v is None:
        auto_margin = int(720 * (blur_height_pct * 0.5 + (blur_lift_pct if (blur_enabled and blur_zone == "bottom") else 0.0)))
        effective_margin_v = max(effective_margin_v, auto_margin)
        # When frame is enabled, PlayRes matches video (e.g. 1920 height) so margin needs to be bigger
        if _as_bool(data.get("frame_enabled", False), False):
            effective_margin_v = max(effective_margin_v, 60)
    # If user set margin_v, use it as-is (already converted from % to px in JS)

    vi_ass_path = None
    final_output_path = None
    pipeline_failed = ""

    def _write_edit_only_ass(out_path: Path, target_segs=None) -> Path:
        """Create an ASS file for visual edits without subtitle dialogue."""
        alignment = 8 if str(data.get("subtitle_position", "bottom")).lower() == "top" else 2
        _orig_font_size = _as_int(data.get("font_size", 32), 32)
        _orig_margin_v = effective_margin_v
        _orig_outline_width = _as_int(data.get("outline_width", 2), 2)
        _scaled_font_size = max(8, int(_orig_font_size * _vh / 720))
        _scaled_margin_v = max(0, int(_orig_margin_v * _vh / 720))
        _scaled_outline_width = max(1, int(_orig_outline_width * _vh / 720))

        if _as_bool(data.get("frame_enabled", False), False):
            _duration = get_media_duration_seconds(ffmpeg, video_path)
            if _duration <= 0:
                _duration = 600.0
            _frame_title = str(data.get("frame_title") or "").strip()
            _frame_title_visible = (
                _as_bool(data.get("frame_title_enabled", True), True)
                and bool(_frame_title)
            )
            _logo_path = str(data.get("frame_logo_path") or "").strip()
            return write_ass_with_frame(
                segments=target_segs or [],
                out_path=out_path,
                video_duration=_duration,
                play_res_x=_vw,
                play_res_y=_vh,
                font_size=_scaled_font_size,
                font_color=data.get("font_color", "white"),
                outline_color=data.get("outline_color", "black"),
                outline_width=_scaled_outline_width,
                margin_v=_scaled_margin_v,
                alignment=alignment,
                title_text=_frame_title if _frame_title_visible else "",
                title_size_pct=_as_float(data.get("frame_title_size_pct"), 7.0),
                title_weight=int(_as_float(data.get("frame_title_weight"), 400.0)),
                title_x_pct=_as_float(data.get("frame_title_x_pct"), 50.0),
                title_y_pct=_as_float(data.get("frame_title_y_pct"), 50.0),
                title_color=str(data.get("frame_title_color") or "#000000"),
                title_color_2=str(data.get("frame_title_color_2") or "#ff0000"),
                title_split_color=_as_bool(data.get("frame_title_split_color", True), True),
                title_bar_color=str(data.get("frame_title_bar_color") or "#ffffff"),
                title_bar_h_pct=(
                    _as_float(data.get("frame_title_bar_h_pct"), 6.0)
                    if _frame_title_visible
                    else 0.0
                ),
                title_margin_x_pct=_as_float(data.get("frame_title_margin_x_pct"), 5.0),
                blur_w_pct=_as_float(data.get("frame_blur_w_pct"), 0.0),
                blur_top_pct=_as_float(data.get("frame_blur_top_pct"), 0.0),
                blur_bottom_pct=_as_float(data.get("frame_blur_bottom_pct"), 0.0),
                blur_opacity=_as_float(data.get("frame_blur_opacity"), 0.6),
                blur_color=str(data.get("frame_blur_color") or "#000000"),
                logo_path=_logo_path,
                logo_size_pct=_as_float(data.get("frame_logo_size_pct"), 6.0),
                logo_top_pct=_as_float(data.get("frame_logo_top_pct"), 3.0),
                logo_left_pct=_as_float(data.get("frame_logo_left_pct"), 3.0),
                logo_radius_pct=_as_float(data.get("frame_logo_radius_pct"), 50.0),
                logo_position=str(data.get("frame_logo_position") or "top-left"),
                frame_mode=str(data.get("frame_blur_mode") or "overlay"),
                target_aspect=_target_aspect,
            )

        return write_ass(
            target_segs or [],
            out_path,
            font_size=_scaled_font_size,
            font_color=data.get("font_color", "white"),
            outline_color=data.get("outline_color", "black"),
            outline_width=_scaled_outline_width,
            margin_v=_scaled_margin_v,
            alignment=alignment,
            play_res_x=_vw,
            play_res_y=_vh,
        )

    # ── Bước 1/5: Xác nhận video đã tải ──────────────────────────────────────
    _t_step1_start = _pytime.time()
    print("=== [DEBUG] process_video_full: reaching step 1 yield ===", file=sys.stderr, flush=True)
    _vid_size_mb = video_path.stat().st_size / 1024 / 1024

    yield send(log=f"[Bước 1/5] Video đã sẵn sàng: {video_path.name} ({_vid_size_mb:.1f} MB)", level="success")
    yield send(log=f"[Bước 1/5] Thư mục output: {out_dir}", level="info")
    yield send(log=f"[Bước 1/5] Cấu hình: burn={do_burn}, voice={do_voice}, translate={do_translate}, frame={_as_bool(data.get('frame_enabled', False), False)} (embedded in ASS)", level="info")
    yield send(overall=5, overall_lbl="Video sẵn sàng")
    yield send(log=f"[Bước 1/5] Chuẩn bị video hoàn tất trong {_pytime.time() - _t_step1_start:.2f}s", level="info")

    _multi_speaker = _as_bool(data.get("multi_speaker", False), False)
    _voice_male = str(data.get("tts_voice_male") or "").strip()
    _voice_female = str(data.get("tts_voice_female") or "").strip()

    # ── Bước 2/5: Phiên âm (Transcribe) ──────────────────────────────────────
    _t_step2_start = _pytime.time()
    ass_path = out_dir / f"{stem}.ass"  # dùng ASS thay SRT
    source_srt_path = out_dir / f"{stem}.srt"  # transcriber output gốc
    srt_path = source_srt_path  # file dùng cho bước burn (có thể đổi sang vi_ass)
    segments = []
    transcribe_failed = False

    # ── Resume: kiểm tra file cache từ lần chạy trước ─────────────────────────
    vi_ass_path_cached   = out_dir / f"{stem}_{target_language}.ass"
    if _aspect_should_convert:
        _aspect_style = "blur" if _pad_blur else "pad"
        burned_path_cached = out_dir / f"{stem}_subbed_{_target_aspect}_{_aspect_style}.mp4"
    else:
        burned_path_cached = out_dir / f"{stem}_subbed.mp4"
    voice_path_cached    = out_dir / f"{stem}_{target_language}_voice.mp4"
    voice_meta_path_cached = out_dir / f"{stem}_{target_language}_voice.meta.json"

    # Load config (cần cho tất cả các bước)
    import yaml as _yaml
    _cfg_file = Path(__file__).parent.parent / "config.yml"
    cfg_raw = _yaml.safe_load(_cfg_file.read_text(encoding="utf-8")) if _cfg_file.exists() else {}
    tr_cfg = cfg_raw.get("transcript", {}) or {}

    # Nếu cả hai tuỳ chọn dịch/ghi phụ đề & giọng đọc đều tắt → Bỏ qua toàn bộ bước transcribe
    skip_trans = not do_burn and not do_voice

    if skip_trans:
        yield send(log=f"[Bước 2/5] Bỏ qua bước phiên âm ({_pytime.time() - _t_step2_start:.2f}s, không bật Ghi phụ đề & Giọng đọc)", level="info")
        yield send(overall=35, overall_lbl="Bỏ qua phiên âm")
    else:
        # Check video audio first
        has_audio = has_audio_track(video_path, ffmpeg)
        if not has_audio:
            yield send(log=f"[Bước 2/5] Video không có audio track", level="warning")
        
        selected_stt_model = str(data.get("transcribe_model") or model_name or "").strip()
        display_model = selected_stt_model if selected_stt_model and selected_stt_model not in ["tiny", "base", "small", "medium", "large", "auto", "model"] else "Tự động theo Provider"
        if transcribe_provider == "antigravity":
            yield send(log=f"[Bước 2/5] Đang phiên âm bằng Antigravity (model={display_model})...", level="info")
        elif transcribe_provider == "gemini":
            yield send(log=f"[Bước 2/5] Đang phiên âm bằng Google Gemini (model={display_model})...", level="info")
        elif transcribe_provider == "model":
            yield send(log=f"[Bước 2/5] Đang phiên âm bằng Whisper local (model={selected_stt_model or 'base'})...", level="info")
        elif transcribe_provider == "groq":
            groq_model = selected_stt_model if selected_stt_model and selected_stt_model not in ["tiny", "base", "small", "medium", "large"] else "whisper-large-v3-turbo"
            yield send(log=f"[Bước 2/5] Đang phiên âm bằng Groq Whisper API (model={groq_model})...", level="info")
        else:
            yield send(log=f"[Bước 2/5] Đang phiên âm bằng {transcribe_provider.title()} (model={selected_stt_model or 'mặc định'})...", level="info")
        yield send(overall=10, overall_lbl="Đang phiên âm...")
    voice_path_cached    = out_dir / f"{stem}_{target_language}_voice.mp4"
    voice_meta_path_cached = out_dir / f"{stem}_{target_language}_voice.meta.json"

    # Bước 2: nếu SRT đã có → load lại, skip transcribe
    if source_srt_path.exists() and source_srt_path.stat().st_size > 0:
        try:
            segments = _parse_srt(source_srt_path)
            if segments:
                yield send(log=f"[Bước 2/5] Dùng lại phiên âm cũ ({len(segments)} đoạn, {_pytime.time() - _t_step2_start:.2f}s): {source_srt_path.name}", level="info", subtitle_path=str(source_srt_path.resolve()))
                yield send(overall=35, overall_lbl=f"Phiên âm cũ: {len(segments)} đoạn")
                transcribe_failed = False
        except Exception:
            segments = []

    if not skip_trans and not segments:
        try:
            selected_stt_model = str(data.get("transcribe_model") or model_name or "").strip()
            if transcribe_provider == "antigravity":
                transcriber = AntigravityTranscriber(language=language, model_name=selected_stt_model, multi_speaker=_multi_speaker)
            elif transcribe_provider == "gemini":
                from core.ai_models_manager import get_active_provider_connections
                g_conns = get_active_provider_connections("gemini")
                g_key = (g_conns[0].get("api_key") or "").strip() if g_conns else ""
                transcriber = AntigravityTranscriber(language=language, api_key=g_key, model_name=selected_stt_model, multi_speaker=_multi_speaker)
            elif transcribe_provider == "model":
                transcriber = FasterWhisperTranscriber(selected_stt_model or "base", language, use_vad=True)
            elif transcribe_provider == "groq":
                from core.ai_models_manager import get_active_provider_connections
                groq_key = str(data.get("groq_api_key") or "").strip() or os.getenv("GROQ_API_KEY", "").strip()
                if not groq_key:
                    try:
                        g_conns = get_active_provider_connections("groq")
                        groq_key = (g_conns[0].get("api_key") or "").strip() if g_conns else ""
                    except Exception:
                        pass
                if not groq_key:
                    groq_key = str(tr_cfg.get("groq_api_key") or "").strip()
                groq_model = selected_stt_model if selected_stt_model and selected_stt_model not in ["tiny", "base", "small", "medium", "large"] else "whisper-large-v3-turbo"
                groq_max_mb = int(data.get("groq_max_mb") or tr_cfg.get("groq_max_mb") or _GROQ_MAX_MB)
                transcriber = GroqWhisperTranscriber(
                    language=language,
                    api_key=groq_key,
                    model=groq_model,
                    max_mb=groq_max_mb,
                )
            else:
                try:
                    from core.ai_models_manager import get_active_provider_connections
                    p_conns = get_active_provider_connections(transcribe_provider)
                    p_key = p_conns[0].get("api_key", "").strip() if p_conns else ""
                    transcriber = AntigravityTranscriber(language=language, api_key=p_key, model_name=selected_stt_model, multi_speaker=_multi_speaker)
                except Exception:
                    transcriber = FasterWhisperTranscriber(selected_stt_model or "base", language, use_vad=True)
            res = transcriber.transcribe(video_path, ffmpeg, source_srt_path)
            if isinstance(res, list):
                segments = res
            else:
                for item in res:
                    if isinstance(item, tuple) and len(item) >= 2:
                        if item[0] == "log":
                            yield send(log=item[1], level=item[2] if len(item) > 2 else "info")
                        elif item[0] == "result":
                            segments = item[1]
            if not segments:
                transcribe_failed = True
                yield send(log="[Bước 2/5] Không phát hiện giọng nói trong video", level="warning")
                if not (do_voice or do_burn):
                    yield send(log="[Bước 2/5] Không có giọng nói và TTS/burn phụ đề cũng bị tắt", level="error", failed=True, overall=0, overall_lbl="Không có nội dung để xử lý")
                    return
                if do_burn and not do_voice:
                    yield send(log="[Bước 2/5] Sẽ chỉ burn phụ đề, bỏ qua phiên âm", level="info")
                    segments = []
                else:
                    video_duration = get_media_duration_seconds(ffmpeg, video_path)
                    if video_duration > 0:
                        segments = [{"start": 0.0, "end": video_duration, "text": "[Giọng nói tự động]"}]
                        yield send(log=f"[Bước 2/5] Tạo 1 segment tự động (0s → {video_duration:.1f}s)", level="info")
                    else:
                        yield send(log="[Bước 2/5] Không thể tính được thời lượng video", level="error", failed=True, overall=0, overall_lbl="Không đọc được video")
                        return
            else:
                process_speaker_tags_in_segments(segments)
                if _multi_speaker and segments:
                    has_spk = sum(1 for s in segments if s.get("speaker"))
                    if has_spk < len(segments) * 0.5:
                        yield send(log="[Bước 2/5] Đang nhận diện và phân vai nhân vật (Nam/Nữ) qua kịch bản hội thoại...", level="info")
                        try:
                            segments = classify_dialogue_speakers(
                                segments,
                                trans_cfg=cfg_raw.get("translation", {}),
                                preferred_provider=transcribe_provider,
                                target_lang=language,
                            )
                        except Exception as _ce:
                            yield send(log=f"[Bước 2/5] Lỗi phân vai AI: {_ce}", level="warning")
                    m_cnt = sum(1 for s in segments if s.get("speaker") == "male")
                    f_cnt = sum(1 for s in segments if s.get("speaker") == "female")
                    yield send(log=f"[Bước 2/5] Phân vai hoàn tất: {m_cnt} câu giọng Nam, {f_cnt} câu giọng Nữ", level="info")

                write_ass(segments, ass_path, play_res_x=_vw, play_res_y=_vh)
                yield send(log=f"[Bước 2/5] Phiên âm {len(segments)} đoạn trong {_pytime.time() - _t_step2_start:.1f}s → {ass_path.name}", level="success", subtitle_path=str(ass_path.resolve()))
            yield send(overall=35, overall_lbl=f"Phiên âm xong: {len(segments)} đoạn")
        except (RuntimeError, Exception) as e:
            transcribe_failed = True
            err_msg = str(e)
            yield send(log=f"[Bước 2/5] Phiên âm thất bại: {err_msg}", level="error", failed=True, overall=0, overall_lbl="Phiên âm thất bại")
            yield send(log="[Bước 2/5] Vui lòng mở Nhà cung cấp để kiểm tra/cập nhật API Key hoặc chọn Engine phiên âm khác.", level="error")
            return


    # Generate titles independently of subtitle translation, including edit-only jobs.
    if (_as_bool(data.get("frame_enabled", False), False)
            and _as_bool(data.get("frame_title_enabled", True), True)
            and not str(data.get("frame_title") or "").strip()):
        try:
            data["frame_title"] = generate_frame_title(
                translated_texts=[], original_texts=[seg.get("text", "") for seg in segments],
                trans_cfg=dict((cfg_raw or {}).get("translation") or {}),
                preferred_provider=str(data.get("translate_provider") or "antigravity"),
                video_title=stem_source, target_lang=target_language,
            )
            if data["frame_title"]:
                yield send(frame_title=data["frame_title"], log=f"Tiêu đề AI: {data['frame_title']}", level="success")
        except Exception as exc:
            yield send(log=f"Không tạo được tiêu đề AI: {exc}", level="warning")

    # ── Bước 3/5: Dịch ZH → VI ─────────────────────────────────────────────────
    _t_step3_start = _pytime.time()
    translated_texts = []
    _write_current_ass = lambda rows, target_path: _write_edit_only_ass(target_path, rows)
    if skip_trans:
        yield send(log=f"[Bước 3/5] Bỏ qua bước dịch và tạo giọng đọc ({_pytime.time() - _t_step3_start:.2f}s, không bật Ghi phụ đề & Giọng đọc)", level="info")
        yield send(overall=70, overall_lbl="Bỏ qua dịch")
    elif not do_translate:
        if do_voice and segments:
            translated_texts = [seg.get("text", "") for seg in segments]
        yield send(log=f"[Bước 3/5] Bỏ qua dịch phụ đề ({_pytime.time() - _t_step3_start:.2f}s, translate_subs=off)", level="info")
    else:
        # Resume: nếu vi.ass đã có → load lại segments và translated_texts từ đó
        # BUT: if frame is enabled, skip resume because ASS needs to be regenerated with new frame settings
        _frame_enabled_check = _as_bool(data.get("frame_enabled", False), False)
        if not _frame_enabled_check and vi_ass_path_cached.exists() and vi_ass_path_cached.stat().st_size > 0 and segments:
            try:
                if vi_ass_path_cached.suffix.lower() == ".srt":
                    cached_vi_segs = _parse_srt(vi_ass_path_cached)
                else:
                    cached_vi_segs = _parse_ass_file(vi_ass_path_cached)
                if cached_vi_segs:
                    tts_vi_segs = _merge_segments_for_tts(cached_vi_segs)
                    translated_texts = [s["text"] for s in tts_vi_segs]
                    segments = tts_vi_segs
                    vi_ass_path = vi_ass_path_cached
                    srt_path = vi_ass_path
                    yield send(log=f"[Bước 3/5] Dùng lại bản dịch cũ ({len(cached_vi_segs)} dòng, gộp {len(translated_texts)} đoạn TTS, {_pytime.time() - _t_step3_start:.2f}s): {vi_ass_path_cached.name}", level="info", subtitle_path=str(vi_ass_path_cached.resolve()))
                    yield send(overall=55, overall_lbl="Dùng lại bản dịch cũ")
            except Exception:
                translated_texts = []

        if not translated_texts and segments:
            n_segs = len(segments)
            batch_sz = 30
            n_batches = (n_segs + batch_sz - 1) // batch_sz
            yield send(log=f"[Bước 3/5] Dịch {n_segs} đoạn sang {target_lang_name} ({n_batches} batch)...", level="info")
            yield send(overall=45, overall_lbl=f"Đang dịch {n_segs} đoạn...")
            try:
                from utils.translation import BatchTranslator
                trans_cfg = cfg_raw.get("translation", {})
                if not trans_cfg.get("groq_key"):
                    trans_cfg["groq_key"] = (
                        str(data.get("groq_api_key") or "").strip()
                        or os.getenv("GROQ_API_KEY", "").strip()
                        or str(tr_cfg.get("groq_api_key") or "").strip()
                    )
                if not trans_cfg.get("groq_model"):
                    trans_cfg["groq_model"] = (
                        str(data.get("groq_model") or "").strip()
                        or str(tr_cfg.get("groq_model") or "").strip()
                        or "llama-3.1-8b-instant"
                    )
                req_provider = str(data.get("translate_provider") or "").strip().lower()
                req_model = str(data.get("translate_model") or "").strip()
                cfg_provider = str(trans_cfg.get("preferred_provider") or "").strip().lower()
                # Treat "auto" as unspecified so config/provider key can decide deterministically.
                if req_provider == "auto":
                    req_provider = ""
                if cfg_provider == "auto":
                    cfg_provider = ""
                provider = req_provider or cfg_provider or "antigravity"

                if req_model and req_model not in ("auto", "prompt_connect"):
                    if "/" in req_model:
                        provider = req_model
                    else:
                        provider = f"{provider}/{req_model}"

                texts = [seg.get("text", "").strip() for seg in segments]
                yield send(log=f"[Bước 3/5] Đang dịch bằng {provider}...", level="info")
                translator = BatchTranslator(trans_cfg)
                translated_texts, used = translator.translate(texts, provider, context=stem_source, target_lang=target_language)
                yield send(log=f"[Bước 3/5] Dịch xong {len(translated_texts)} đoạn trong {_pytime.time() - _t_step3_start:.1f}s (provider: {used})", level="success")
                yield send(overall=55, overall_lbl="Dịch xong")

                if translated_texts:
                    # Luôn dùng ASS — không dùng SRT
                    alignment = 8 if str(data.get("subtitle_position", "bottom")).lower() == "top" else 2
                    vi_ass_path = out_dir / f"{stem}_{target_language}.ass"
                    vi_segs = [{"start": s["start"], "end": s["end"], "text": t, "speaker": s.get("speaker")}
                               for s, t in zip(segments, translated_texts) if t]
                    vi_segs = _merge_segments_for_tts(vi_segs)
                    segments = vi_segs
                    translated_texts = [s["text"] for s in vi_segs]

                    # Scale font_size, margin_v, and outline_width dynamically based on actual video height vs 720
                    _orig_font_size = _as_int(data.get("font_size", 32), 32)
                    _orig_margin_v = effective_margin_v
                    _orig_outline_width = _as_int(data.get("outline_width", 2), 2)
                    _font_bold = _as_bool(data.get("font_bold", True), True)
                    
                    _scaled_font_size = max(8, int(_orig_font_size * _vh / 720))
                    _scaled_margin_v = max(0, int(_orig_margin_v * _vh / 720))
                    _scaled_outline_width = max(1, int(_orig_outline_width * _vh / 720))

                    # Check if frame elements should be embedded in ASS
                    frame_enabled = _as_bool(data.get("frame_enabled", False), False)

                    if frame_enabled:
                        _duration = get_media_duration_seconds(ffmpeg, video_path)
                        if _duration <= 0:
                            _duration = 600.0

                        # Generate a contextual title only when the title toggle is on.
                        _frame_title = str(data.get("frame_title") or "").strip()
                        if _as_bool(data.get("frame_title_enabled", True), True) and not _frame_title:
                            yield send(log=f"[Bước 3/5] AI đang tạo tiêu đề khung...", level="info")
                            try:
                                _frame_title = generate_frame_title(
                                    translated_texts=translated_texts,
                                    original_texts=texts,
                                    trans_cfg=trans_cfg,
                                    preferred_provider=provider,
                                    video_title=stem_source,
                                    target_lang=target_language,
                                )
                                data["frame_title"] = _frame_title
                                yield send(frame_title=_frame_title)
                                yield send(log=f"[Bước 3/5] Tiêu đề AI: \"{_frame_title}\"", level="success")
                            except Exception as _e:
                                yield send(log=f"[Bước 3/5] Không tạo được tiêu đề: {_e}", level="warning")
                                _frame_title = ""
                        _frame_title_visible = (
                            _as_bool(data.get("frame_title_enabled", True), True)
                            and bool(_frame_title.strip())
                        )

                        # Only use a logo explicitly selected/saved by the user.
                        _logo_path = str(data.get("frame_logo_path") or "").strip()

                    def _write_current_ass(target_segs, target_path=vi_ass_path):
                        if frame_enabled:
                            return write_ass_with_frame(
                                segments=target_segs,
                                out_path=target_path,
                                video_duration=_duration,
                                play_res_x=_vw,
                                play_res_y=_vh,
                                font_size=_scaled_font_size,
                                font_color=data.get("font_color", "white"),
                                outline_color=data.get("outline_color", "black"),
                                outline_width=_scaled_outline_width,
                                margin_v=_scaled_margin_v,
                                alignment=alignment,
                                title_text=_frame_title if _frame_title_visible else "",
                                title_size_pct=_as_float(data.get("frame_title_size_pct"), 7.0),
                                title_weight=int(_as_float(data.get("frame_title_weight"), 400.0)),
                                title_x_pct=_as_float(data.get("frame_title_x_pct"), 50.0),
                                title_y_pct=_as_float(data.get("frame_title_y_pct"), 50.0),
                                title_color=str(data.get("frame_title_color") or "#000000"),
                                title_color_2=str(data.get("frame_title_color_2") or "#ff0000"),
                                title_split_color=_as_bool(data.get("frame_title_split_color", True), True),
                                title_bar_color=str(data.get("frame_title_bar_color") or "#ffffff"),
                                title_bar_h_pct=(
                                    _as_float(data.get("frame_title_bar_h_pct"), 6.0)
                                    if _frame_title_visible
                                    else 0.0
                                ),
                                title_margin_x_pct=_as_float(data.get("frame_title_margin_x_pct"), 5.0),
                                blur_w_pct=_as_float(data.get("frame_blur_w_pct"), 0.0),
                                blur_top_pct=_as_float(data.get("frame_blur_top_pct"), 0.0),
                                blur_bottom_pct=_as_float(data.get("frame_blur_bottom_pct"), 0.0),
                                blur_opacity=_as_float(data.get("frame_blur_opacity"), 0.6),
                                blur_color=str(data.get("frame_blur_color") or "#000000"),
                                logo_path=_logo_path,
                                logo_size_pct=_as_float(data.get("frame_logo_size_pct"), 6.0),
                                logo_top_pct=_as_float(data.get("frame_logo_top_pct"), 3.0),
                                logo_left_pct=_as_float(data.get("frame_logo_left_pct"), 3.0),
                                logo_radius_pct=_as_float(data.get("frame_logo_radius_pct"), 50.0),
                                logo_position=str(data.get("frame_logo_position") or "top-left"),
                                frame_mode=str(data.get("frame_blur_mode") or "overlay"),
                                target_aspect=_target_aspect,
                                font_bold=_font_bold,
                            )
                        else:
                            return write_ass(
                                target_segs,
                                target_path,
                                font_size=_scaled_font_size,
                                font_color=data.get("font_color", "white"),
                                outline_color=data.get("outline_color", "black"),
                                outline_width=_scaled_outline_width,
                                margin_v=_scaled_margin_v,
                                alignment=alignment,
                                play_res_x=_vw,
                                play_res_y=_vh,
                                font_bold=_font_bold,
                            )

                    _write_current_ass(vi_segs)
                    if frame_enabled:
                        yield send(log=f"[Bước 3/5] ASS (có khung) {target_lang_name}: {vi_ass_path.name}", level="success", subtitle_path=str(vi_ass_path.resolve()))
                        yield send(log=f"[Bước 3/5] Khung: title=\"{_frame_title[:25]}\", blur={_as_float(data.get('frame_blur_w_pct'), 0.0)}%, logo={'' if _logo_path else ''}", level="info")
                    else:
                        yield send(log=f"[Bước 3/5] ASS {target_lang_name}: {vi_ass_path.name}", level="success", subtitle_path=str(vi_ass_path.resolve()))
                    # Signal frontend to review the ASS file before continuing
                    _skip_ass_review = _as_bool(data.get("skip_ass_review", False), False) or _as_bool(data.get("skip_ass", False), False)
                    if not _skip_ass_review:
                        yield send(
                            review_ass=True,
                            ass_path=str(vi_ass_path.resolve()),
                            log=f"[Bước 3/5] Chờ kiểm tra nội dung dịch: {vi_ass_path.name}",
                            level="info",
                        )
                        # Wait for frontend to confirm (or auto-continue if skip_review)
                        from templates.pages.process.route import _proc_review_event
                        _proc_review_event.clear()
                        import time as _t
                        _start_wait = _t.time()
                        while not _proc_review_event.is_set():
                            if _t.time() - _start_wait > 600:
                                _proc_review_event.set()
                                break
                            try:
                                import eventlet as _evlet
                                _evlet.sleep(0.5)
                            except Exception:
                                _t.sleep(0.5)
                        _proc_review_event.set()
                    else:
                        yield send(log=f"[Bước 3/5] Bỏ qua kiểm tra ASS (tự động tiếp tục)", level="info")
                    # Re-read vi_ass_path in case user edited it
                    yield send(log=f"[Bước 3/5] ▶ Tiếp tục xử lý...", level="info")

                    if vi_ass_path and vi_ass_path.exists():
                        refreshed_vi_segs = _parse_ass_file(vi_ass_path)
                        if refreshed_vi_segs:
                            tts_vi_segs = _merge_segments_for_tts(refreshed_vi_segs)
                            segments = tts_vi_segs
                            translated_texts = [s.get("text", "") for s in tts_vi_segs]
                            yield send(
                                log=f"[Bước 3/5] Đã nạp ASS mới nhất sau chỉnh sửa ({len(refreshed_vi_segs)} dòng, gộp {len(translated_texts)} đoạn TTS)",
                                level="success",
                                subtitle_path=str(vi_ass_path.resolve()),
                            )
                        else:
                            yield send(
                                log=f"[Bước 3/5] Không đọc được dialogue từ ASS đã chỉnh sửa: {vi_ass_path.name}",
                                level="warning",
                            )

                    if do_burn and do_burn_vi:
                        srt_path = vi_ass_path
                        yield send(log=f"[Bước 3/5] Sẽ burn: {srt_path.name}", level="info")
            except Exception as e:
                yield send(log=f"[Bước 3/5] Dịch thất bại: {e}", level="error", failed=True, overall=0, overall_lbl="Dịch thất bại")
                return

    # ── Parallel thumbnail generation (chạy song song với burn) ─────────
    # Mode: 'ai' | 'import' | 'frame' | 'none'
    # User có thể override config qua modal "Chọn thumbnail" sau khi review ASS.
    try:
        from templates.pages.process.route import get_proc_thumb_override
        _thumb_user_cfg = get_proc_thumb_override()
    except Exception:
        _thumb_user_cfg = {}

    if _thumb_user_cfg:
        _thumb_enabled = bool(_thumb_user_cfg.get("thumb_enabled"))
        _thumb_mode = str(_thumb_user_cfg.get("thumb_mode") or "none").lower()
        _thumb_path_input = str(_thumb_user_cfg.get("thumb_path") or "").strip()
        _thumb_title = str(_thumb_user_cfg.get("thumb_title") or "").strip()
        _thumb_duration = _as_float(_thumb_user_cfg.get("thumb_duration", 0.3), 0.3)
        _thumb_timestamp = _as_float(_thumb_user_cfg.get("thumb_timestamp", 5.0), 5.0)
    else:
        _thumb_enabled = _as_bool(data.get("thumb_enabled", False), False)
        _thumb_mode = str(data.get("thumb_mode") or "none").lower()
        _thumb_path_input = str(data.get("thumb_path") or "").strip()
        _thumb_title = str(data.get("thumb_title") or "").strip()
        _thumb_duration = _as_float(data.get("thumb_duration", 0.3), 0.3)
        _thumb_timestamp = _as_float(data.get("sub_preview_ts") or data.get("thumb_timestamp", 5.0), 5.0)

    _thumb_future = None
    _thumb_executor = None
    _thumb_target_path = out_dir / f"{stem}_thumb.jpg"

    # Thumbnail flow disabled by request.
    _thumb_enabled = False
    _thumb_mode = "none"
    _thumb_path_input = ""
    _thumb_title = ""
    _thumb_duration = 0.0

    if _thumb_enabled and _thumb_mode != "none" and do_burn:
        try:
            import concurrent.futures
            _thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

            def _gen_thumb_task():
                """Generate thumbnail file in parallel. Returns Path or None."""
                try:
                    if _thumb_mode == "import" and _thumb_path_input:
                        # Just copy the user-provided file
                        src = Path(_thumb_path_input)
                        if src.exists():
                            import shutil
                            shutil.copy2(str(src), str(_thumb_target_path))
                            return _thumb_target_path
                        return None
                    elif _thumb_mode == "frame":
                        # Extract a frame from the video at the chosen timestamp
                        ts = _thumb_timestamp
                        ok, _err = run_ffmpeg([
                            ffmpeg, "-ss", str(ts),
                            "-i", str(video_path),
                            "-vframes", "1", "-q:v", "2",
                            str(_thumb_target_path), "-y", "-loglevel", "error"
                        ], timeout=60)
                        if ok and _thumb_target_path.exists():
                            return _thumb_target_path
                        return None
                    elif _thumb_mode == "ai":
                        # Generate via Gemini (extract frame first, send to Gemini)
                        return _gen_ai_thumbnail_for_pipeline(
                            video_path=video_path,
                            output_path=_thumb_target_path,
                            ffmpeg=ffmpeg,
                            timestamp=_thumb_timestamp,
                            title=_thumb_title or video_title,
                            subtitle_text=" ".join(translated_texts[:3]) if translated_texts else "",
                        )
                except Exception:
                    return None
                return None

            _thumb_future = _thumb_executor.submit(_gen_thumb_task)
            yield send(log=f"[Bước 4/5] Đang tạo thumbnail ({_thumb_mode}) song song với burn...", level="info")
        except Exception as e:
            yield send(log=f"[Bước 4/5] Không khởi tạo được thumbnail task: {e}", level="warning")

    # ── Bước 4/5: Burn phụ đề ────────────────────────────────────────────────
    _t_step4_start = _pytime.time()
    burned_path = None
    _aspect_combined = False
    # Resume: nếu file subbed đã có → dùng lại (BUT: skip if frame enabled to re-apply new frame settings)
    _frame_enabled_for_burn = _as_bool(data.get("frame_enabled", False), False)

    # Quyết định burn hiệu lực: KHÔNG BAO GIỜ ghi phụ đề GỐC lên video.
    # - Khi user tắt optcard "Ghi phụ đề" (do_burn_vi=False) → không burn.
    # - Khi có dịch nhưng srt_path vẫn trỏ về phụ đề gốc (vd dịch lỗi, hoặc
    #   do_burn_vi=False nên không đổi sang vi_ass) → không burn để tránh
    #   in lại phụ đề ngôn ngữ gốc lên video.
    do_burn_effective = do_burn
    if do_burn and do_translate:
        _srt_is_translated = (srt_path != source_srt_path)
        do_burn_effective = bool(do_burn_vi and _srt_is_translated)
        if not do_burn_effective:
            yield send(log="[Bước 4/5] Tắt ghi phụ đề: không in phụ đề gốc; nếu có chỉnh sửa video vẫn render", level="info")
    do_burn = do_burn_effective

    # ── Tham số che (blur) vùng phụ đề gốc ───────────────────────────────────
    # Tách riêng để có thể CHE cả khi KHÔNG ghi phụ đề (do_burn_vi=False).
    _blur_original_flag = _as_bool(data.get("blur_original", True), True)
    _blur_by_subtitles = _as_bool(data.get("blur_by_subtitles", False), False)
    _blur_subtitle_segments = None
    if _blur_by_subtitles:
        _blur_subtitle_segments = []
        try:
            if source_srt_path.exists():
                _blur_subtitle_segments = _parse_srt(source_srt_path)
            elif ass_path.exists():
                _blur_subtitle_segments = _parse_ass_file(ass_path)
        except Exception as exc:
            yield send(log=f"Không đọc được thời gian phụ đề gốc: {exc}", level="warning")
        if _blur_original_flag:
            yield send(log=(f"Che gốc theo ASS/SRT: {len(_blur_subtitle_segments)} đoạn."
                            if _blur_subtitle_segments else "Không có thời gian phụ đề gốc: bỏ che gốc theo text."),
                       level="info" if _blur_subtitle_segments else "warning")
    _blur_timing_meta = burned_path_cached.with_suffix('.blur-timing.json')
    _output_fps = _as_int(data.get("output_fps", 0), 0)
    if _output_fps not in (0, 15, 24, 25, 30, 60):
        _output_fps = 0
    _encode_device = str(data.get("encode_device") or "auto").lower()
    if _encode_device not in ("auto", "cpu", "nvidia"):
        _encode_device = "auto"
    _blur_timing_signature = {"enabled": _blur_by_subtitles, "segments": _blur_subtitle_segments,
                              "output_fps": _output_fps, "encode_device": _encode_device,
                              "visual_config": {key: data.get(key) for key in (
                                  "content_aspect", "content_aspect_mode", "target_aspect", "aspect_pad_blur", "mask_config",
                                  "blur_original", "blur_zone", "blur_height_pct", "blur_width_pct",
                                  "blur_x_pct", "blur_y_pct", "blur_extra_zones", "video_overlays")}}
    _blur_zone_val = str(data.get("blur_zone", "bottom"))

    _blur_y_raw = data.get("blur_y_pct")
    _blur_y_pct = None
    if _blur_y_raw is not None and str(_blur_y_raw).strip() != "" and str(_blur_y_raw).lower() != "null":
        try:
            _blur_y_pct = float(_blur_y_raw)
        except Exception:
            pass

    _blur_x_raw = data.get("blur_x_pct")
    _blur_x_pct = None
    if _blur_x_raw is not None and str(_blur_x_raw).strip() != "" and str(_blur_x_raw).lower() != "null":
        try:
            _blur_x_pct = float(_blur_x_raw)
        except Exception:
            pass

    _blur_extra_zones_raw = data.get("blur_extra_zones")
    _blur_extra_zones = None
    if _blur_extra_zones_raw:
        if isinstance(_blur_extra_zones_raw, str):
            try:
                _blur_extra_zones = _j.loads(_blur_extra_zones_raw)
            except Exception:
                pass
        elif isinstance(_blur_extra_zones_raw, list):
            _blur_extra_zones = _blur_extra_zones_raw

    _video_overlays = _normalize_video_overlays(data.get("video_overlays"))

    # Có cần che không? (bật "Che phụ đề gốc" + có vùng che hợp lệ)
    _blur_enabled = bool(
        (_blur_original_flag and _blur_zone_val.lower() != "none")
        or _blur_extra_zones
    )
    _overlay_enabled = bool(_video_overlays)
    _visual_edit_enabled = bool(
        _blur_enabled
        or _overlay_enabled
        or _frame_enabled_for_burn
        or _aspect_should_convert
        or _output_fps > 0
        or _encode_device != "auto"
    )

    # Chọn nguồn ASS cho bước encode:
    #   "sub"  → có ghi phụ đề: dùng srt_path (ASS đã dịch) + che (nếu bật)
    #   "blur" → KHÔNG ghi phụ đề nhưng vẫn che: tạo ASS rỗng để chỉ che, không vẽ chữ
    #   "skip" → không ghi phụ đề và cũng không che: bỏ qua encode
    _encode_srt = None
    _encode_mode = "skip"
    if do_burn and srt_path.exists():
        _encode_srt = srt_path
        _encode_mode = "sub"
    elif _visual_edit_enabled:
        try:
            _empty_ass = out_dir / f"{stem}_bluronly.ass"
            _write_edit_only_ass(_empty_ass)
            _encode_srt = _empty_ass
            _encode_mode = "edit"
            _edit_reasons = []
            if _blur_enabled:
                _edit_reasons.append("che phụ đề/vùng che")
            if _overlay_enabled:
                _edit_reasons.append("chữ/khối")
            if _frame_enabled_for_burn:
                _edit_reasons.append("khung/logo")
            if _aspect_should_convert:
                _edit_reasons.append(f"chuyển khung {_target_aspect}")
            _edit_note = ", ".join(_edit_reasons) or "chỉnh sửa video"
            yield send(log=f"[Bước 4/5] ▣ Không ghi phụ đề nhưng vẫn encode để {_edit_note}", level="info")
        except Exception as _e_ass:
            yield send(log=f"[Bước 4/5] Không tạo được ASS che: {_e_ass}", level="warning")

    # Resume cache chỉ áp dụng cho chế độ có phụ đề ("sub")
    _burn_cache_valid = False
    _burn_cache_stale_reason = ""
    if _encode_mode == "sub" and not _frame_enabled_for_burn and burned_path_cached.exists() and burned_path_cached.stat().st_size > 0:
        try:
            _burn_deps = [video_path]
            if _encode_srt and Path(_encode_srt).exists():
                _burn_deps.append(Path(_encode_srt))
            _newest_burn_dep = max(p.stat().st_mtime for p in _burn_deps)
            _burn_cache_valid = burned_path_cached.stat().st_mtime >= _newest_burn_dep
            if not _burn_cache_valid:
                _burn_cache_stale_reason = "ASS/video mới hơn cache"
        except Exception:
            _burn_cache_valid = False
            _burn_cache_stale_reason = "không kiểm tra được thời gian cache"

    # ── Start TTS in parallel with burn/aspect/thumbnail processing ───────────
    try:
        _previous_blur_timing = _j.loads(_blur_timing_meta.read_text(encoding='utf-8'))
    except Exception:
        _previous_blur_timing = None
    if _previous_blur_timing != _blur_timing_signature:
        _burn_cache_valid = False
        _burn_cache_stale_reason = "cấu hình che theo phụ đề thay đổi"
    _tts_executor = None
    _tts_future = None
    _tts_tmp_ctx = None
    _tts_provider = None
    _run_tts_indices = None
    _tts_clips: list[dict] = []
    _tts_concurrency = 4
    _tts_retries = 2
    _voice_cache_valid = False
    _voice_cache_stale_reason = ""
    voice_path = out_dir / f"{stem}_{target_language}_voice.mp4"
    original_volume = min(2.0, max(0.0, _as_float(data.get("vol_orig", 1.0), 1.0)))
    voice_mix_config = {key: data.get(key) for key in (
        "tts_engine", "tts_voice", "tts_pitch", "tts_rate", "tts_speed",
        "tts_emotion", "auto_speed", "sync_sub_to_voice", "tts_volume", "fx_enabled", "fx_pitch",
        "fx_speed", "fx_bass", "fx_mid", "fx_treble", "fx_comp", "fx_reverb"
    )}
    voice_mix_config["original_volume"] = original_volume
    voice_mix_config["blur_timing"] = _blur_timing_signature

    if do_voice and translated_texts:
        try:
            _voice_cache_valid = voice_path_cached.exists() and voice_path_cached.stat().st_size > 0
            _voice_deps = [video_path]
            if srt_path and Path(srt_path).exists():
                _voice_deps.append(Path(srt_path))
            if _encode_mode != "skip":
                if not _burn_cache_valid:
                    _voice_cache_valid = False
                    _voice_cache_stale_reason = "video hình sẽ được encode lại"
                elif burned_path_cached.exists():
                    _voice_deps.append(burned_path_cached)
            if _thumb_enabled:
                _voice_cache_valid = False
                _voice_cache_stale_reason = "thumbnail sẽ thay đổi video hình"
            if _voice_cache_valid:
                newest_dep = max(p.stat().st_mtime for p in _voice_deps)
                _voice_cache_valid = voice_path_cached.stat().st_mtime >= newest_dep
                if not _voice_cache_valid:
                    _voice_cache_stale_reason = "ASS/video mới hơn cache"
            if _voice_cache_valid:
                try:
                    voice_meta = json.loads(voice_meta_path_cached.read_text(encoding="utf-8"))
                except Exception:
                    voice_meta = {}
                if (
                    voice_meta.get("tts_cache_version") != TTS_CACHE_VERSION
                    or voice_meta.get("mix_config") != voice_mix_config
                    or voice_meta.get("complete") is not True
                    or int(voice_meta.get("segments") or 0) != len(translated_texts)
                ):
                    _voice_cache_valid = False
                    _voice_cache_stale_reason = "cache TTS không đầy đủ hoặc đã đổi cấu hình"
        except Exception:
            _voice_cache_valid = False
            _voice_cache_stale_reason = "không kiểm tra được cache giọng"

        if not _voice_cache_valid:
            _req_engine = data.get("tts_engine", "fpt-ai")
            _req_voice = data.get("tts_voice", "banmai")
            try:
                from core.tts_catalog import resolve_engine_voice as _resolve_ev
                _eng_sel, _voice_sel, _ev_changed, _ev_note = _resolve_ev(
                    _req_engine, _req_voice, target_language, cfg_raw
                )
            except Exception:
                _eng_sel, _voice_sel, _ev_changed, _ev_note = _req_engine, _req_voice, False, ""
            if _ev_changed:
                if "alias" in _ev_note:
                    _msg = f"[TTS] Cập nhật tên giọng: {_req_voice or '∅'} → {_voice_sel} (phiên bản mới)"
                elif _req_engine != _eng_sel:
                    _msg = f"[TTS] Chọn engine TTS: {_req_engine}/{_req_voice or '∅'} → {_eng_sel}/{_voice_sel or '∅'} ({_ev_note})"
                else:
                    _msg = f"[TTS] Giọng '{_req_voice or '∅'}' không có trong danh mục, tự chọn: '{_voice_sel}'"
                yield send(
                    log=_msg,
                    level="info",
                )

            def _get_provider_db_key(provider_id: str) -> str:
                try:
                    from utils.translation import load_db_connections
                    for c in load_db_connections():
                        if (c.get("provider") or "").lower() == provider_id.lower() and c.get("api_key"):
                            return c["api_key"]
                except Exception:
                    pass
                return ""

            _tts_provider = MultiProviderTTS(
                voice=_voice_sel,
                engine=_eng_sel,
                fpt_api_key=(
                    str(data.get("fpt_api_key") or "").strip()
                    or str((cfg_raw.get("video_process") or {}).get("fpt_api_key") or "").strip()
                    or _get_provider_db_key("fptai")
                    or os.getenv("FPT_AI_API_KEY", "").strip()
                    or FPT_TTS_DEFAULT_KEY
                ),
                fpt_speed=_as_int(data.get("fpt_speed", 0), 0),
                openai_api_key=(
                    str(data.get("openai_api_key") or "").strip()
                    or str((cfg_raw.get("video_process") or {}).get("openai_api_key") or "").strip()
                    or str((cfg_raw.get("translation") or {}).get("openai_key") or "").strip()
                    or _get_provider_db_key("openai")
                    or os.getenv("OPENAI_API_KEY", "").strip()
                ),
                openai_model=str(data.get("openai_tts_model") or "tts-1"),
                tts_lang=target_language,
                tts_rate=str(data.get("tts_rate") or "+0%"),
                tts_pitch=str(data.get("tts_pitch") or "+0Hz"),
                tts_emotion=str(data.get("tts_emotion") or "default"),
                elevenlabs_api_key=(
                    str(data.get("elevenlabs_api_key") or "").strip()
                    or str((cfg_raw.get("video_process") or {}).get("elevenlabs_api_key") or "").strip()
                    or _get_provider_db_key("elevenlabs")
                    or os.environ.get("ELEVENLABS_API_KEY", "").strip()
                ),
                elevenlabs_voice_id=(
                    str(data.get("elevenlabs_voice_id") or "").strip()
                    or str((cfg_raw.get("video_process") or {}).get("elevenlabs_voice_id") or "").strip()
                ),
                elevenlabs_model=str(
                    data.get("elevenlabs_model")
                    or (cfg_raw.get("video_process") or {}).get("elevenlabs_model")
                    or "eleven_multilingual_v2"
                ),
                fpt_fallback_elevenlabs=_as_bool(
                    data.get(
                        "fpt_fallback_elevenlabs",
                        (cfg_raw.get("video_process") or {}).get("fpt_fallback_elevenlabs", False),
                    ),
                    False,
                ),
                fish_api_key=(
                    str(data.get("fish_api_key") or "").strip()
                    or str((cfg_raw.get("video_process") or {}).get("fish_api_key") or "").strip()
                    or _get_provider_db_key("fishaudio")
                    or os.getenv("FISH_API_KEY", "").strip()
                    or os.getenv("FISH_AUDIO_API_KEY", "").strip()
                ),
                fish_model=str(
                    data.get("fish_model")
                    or (cfg_raw.get("video_process") or {}).get("fish_model")
                    or "s2-pro"
                ),
                fish_reference_id=str(
                    data.get("fish_reference_id")
                    or (cfg_raw.get("video_process") or {}).get("fish_reference_id")
                    or ""
                ),
                vieneu_ref_audio=str(
                    data.get("vieneu_ref_audio")
                    or (cfg_raw.get("video_process") or {}).get("vieneu_ref_audio")
                    or ""
                ),
            )
            _vp_cfg = cfg_raw.get("video_process") or {}
            _tts_concurrency = max(
                1,
                _as_int(data.get("tts_concurrency", _vp_cfg.get("tts_concurrency", 4)), 4),
            )
            _tts_retries = max(
                0,
                _as_int(data.get("tts_retries", _vp_cfg.get("tts_retries", 2)), 2),
            )
            try:
                _tts_tmp_ctx = tempfile.TemporaryDirectory(prefix="tts_parallel_")
                _tts_tmp_path = Path(_tts_tmp_ctx.name)

                # Voice and displayed text share one measured timeline.
                _sync_sub_to_voice = True

                _tts_voice_map = None
                if _multi_speaker:
                    _tts_voice_map = {
                        "male": _voice_male or _voice_sel,
                        "female": _voice_female or _voice_sel,
                        "default": _voice_sel,
                    }

                import queue as _queue
                _tts_progress = _queue.Queue()

                def _run_tts_indices(indices: list[int]) -> list[dict]:
                    batch_segments = [segments[i] for i in indices]
                    batch_texts = [translated_texts[i] for i in indices]
                    return asyncio.run(
                        _tts_provider.generate_all(
                            batch_segments,
                            batch_texts,
                            _tts_tmp_path,
                            max_concurrency=_tts_concurrency,
                            retries=_tts_retries,
                            tts_speed=_as_float(data.get("tts_speed", 1.0), 1.0),
                            auto_speed=False if _sync_sub_to_voice else _as_bool(data.get("auto_speed", True), True),
                            ffmpeg=ffmpeg,
                            pitch_semitones=_as_float(data.get("pitch_semitones", 0.0), 0.0),
                            indices=indices,
                            voice_map=_tts_voice_map,
                            progress_callback=lambda done, total: _tts_progress.put((done, total)),
                        )
                    )

                if _sync_sub_to_voice:
                    yield send(
                        log=(
                            f"[Lồng tiếng đồng bộ] Đang tạo giọng đọc tự nhiên cho {len(translated_texts)} đoạn thoại..."
                        ),
                        level="info",
                        overall=62,
                        overall_lbl="Đang tạo giọng đọc đồng bộ...",
                    )
                    import concurrent.futures as _cf
                    _tts_executor = _cf.ThreadPoolExecutor(max_workers=1)
                    _tts_future = _tts_executor.submit(_run_tts_indices, list(range(len(translated_texts))))
                    _started = _pytime.monotonic()
                    while not _tts_future.done():
                        try:
                            done, total = _tts_progress.get(timeout=5)
                            yield send(log=f"[VieNeu] Đã tạo {done}/{total} đoạn ({_pytime.monotonic() - _started:.0f}s)", level="info", overall=62 + int(8 * done / max(1, total)))
                        except _queue.Empty:
                            yield send(log=f"[VieNeu] Đang nạp mô hình / tạo giọng ({_pytime.monotonic() - _started:.0f}s)...", level="info")
                    _tts_clips = _tts_future.result()


                    expected = {i for i, text in enumerate(translated_texts) if text.strip()}
                    if {int(c["index"]) for c in _tts_clips} != expected:
                        raise ValueError("Tạo giọng chưa đủ các câu. Chạy lại để thử lại trước khi ghi phụ đề.")
                    _vid_dur = get_media_duration_seconds(ffmpeg, video_path)
                    _tts_clips, aligned_segs = align_subtitles_to_voice(
                        segments=segments, tts_clips=_tts_clips, ffmpeg=ffmpeg,
                        video_duration=_vid_dur, min_gap=0.02,
                    )
                    for clip in _tts_clips:
                        if clip.get("tempo_factor", 1.0) > 1.01:
                            yield send(log=f"[Đồng bộ giọng đọc] Câu {clip['index'] + 1}: tốc độ {clip['tempo_factor']:.2f}x", level="info")
                    if aligned_segs:
                        synced_ass = out_dir / f"{stem}_{target_language}_voice_sync.ass"
                        _write_current_ass(aligned_segs, synced_ass)
                        vi_ass_path = synced_ass
                        if do_burn and do_burn_vi:
                            _encode_srt = synced_ass
                            _burn_cache_valid = False
                            _burn_cache_stale_reason = "phụ đề theo thời lượng giọng đọc"
                        yield send(log=f"Đã đồng bộ {len(aligned_segs)} câu theo mốc video", level="success",
                                   subtitle_path=str(synced_ass.resolve()))

                else:
                    import concurrent.futures as _cf
                    _tts_executor = _cf.ThreadPoolExecutor(max_workers=1)
                    _tts_future = _tts_executor.submit(_run_tts_indices, list(range(len(translated_texts))))
                    yield send(
                        log=(
                            f"[TTS song song] Bắt đầu {len(translated_texts)} đoạn, "
                            f"VieNeu tạo lần lượt từng đoạn; burn chạy cùng lúc"
                        ),
                        level="info",
                        overall=65,
                        overall_lbl="Burn video + tạo TTS song song...",
                    )
            except Exception as tts_start_err:
                if _tts_executor:
                    _tts_executor.shutdown(wait=False)
                    _tts_executor = None
                if _tts_tmp_ctx:
                    _tts_tmp_ctx.cleanup()
                    _tts_tmp_ctx = None
                _run_tts_indices = None
                yield send(
                    log=f"[Đồng bộ giọng đọc] Không thể hoàn tất: {tts_start_err}",
                    level="error", failed=True,
                )
                return

    if _encode_mode == "sub" and not _frame_enabled_for_burn and _burn_cache_valid:
        burned_path = burned_path_cached
        final_output_path = burned_path
        _aspect_combined = _aspect_should_convert
        yield send(log=f"[Bước 4/5] Dùng lại video phụ đề cũ ({_pytime.time() - _t_step4_start:.2f}s): {burned_path.name}", level="info")
        yield send(overall=80, overall_lbl="Dùng lại video phụ đề cũ")
    elif _encode_mode != "skip" and _encode_srt and _encode_srt.exists():
        if _burn_cache_stale_reason:
            yield send(log=f"[Bước 4/5] Bỏ cache video phụ đề cũ ({_burn_cache_stale_reason}), encode lại từ ASS hiện tại", level="info")
        if _encode_mode == "edit":
            yield send(log=f"[Bước 4/5] ▣ Đang áp dụng chỉnh sửa video...", level="info")
        elif _encode_mode == "blur":
            yield send(log=f"[Bước 4/5] Đang che phụ đề gốc (không ghi phụ đề)...", level="info")
        else:
            yield send(log=f"[Bước 4/5] Đang burn phụ đề ASS vào video...", level="info")
        yield send(overall=65, overall_lbl="Đang xử lý video...")
        burned_path = burned_path_cached

        # Log details before starting (so user sees progress immediately)
        _vid_size = video_path.stat().st_size / 1024 / 1024
        yield send(log=f"[Bước 4/5] Video: {video_path.name} ({_vid_size:.1f} MB)", level="info")
        yield send(log=f"[Bước 4/5] ASS: {_encode_srt.name}", level="info")
        _hw_preset = _get_encoding_args(ffmpeg)
        _hw_desc = " ".join(_hw_preset[:6])
        yield send(log=f"[Bước 4/5] Đang encode ({_hw_desc})...", level="info")

        # Collect logs from burn process
        _burn_logs = []
        def _burn_log_cb(msg, level="info"):
            _burn_logs.append((msg, level))

        ok, err = burn_subtitles(
            video_path=video_path,
            srt_path=_encode_srt,
            output_path=burned_path,
            ffmpeg=ffmpeg,
            blur_original=_blur_original_flag,
            blur_subtitle_segments=_blur_subtitle_segments,
            blur_zone=_blur_zone_val,
            blur_height_pct=_as_float(data.get("blur_height_pct", 0.15), 0.15),
            blur_width_pct=_as_float(data.get("blur_width_pct", 0.80), 0.80),
            blur_lift_pct=_as_float(data.get("blur_lift_pct", 0.06), 0.06),
            font_size=_as_int(data.get("font_size", 32), 32),
            font_color=data.get("font_color", "white"),
            outline_color=data.get("outline_color", "black"),
            outline_width=_as_int(data.get("outline_width", 2), 2),
            margin_v=effective_margin_v,
            subtitle_position=data.get("subtitle_position", "bottom"),
            subtitle_format="ass",  # luôn dùng ASS
            frame_enabled=False,
            log_callback=_burn_log_cb,
            blur_y_pct=_blur_y_pct,
            blur_x_pct=_blur_x_pct,
            blur_extra_zones=_blur_extra_zones,
            video_overlays=_video_overlays,
            target_aspect=_target_aspect,
            aspect_pad_blur=_pad_blur,
            content_aspect=data.get("content_aspect", "auto"),
            content_aspect_mode=data.get("content_aspect_mode", "crop"),
            mask_config=data.get("mask_config"),
            output_fps=_output_fps,
            encode_device=_encode_device,
        )
        # Emit collected burn logs
        for _msg, _lvl in _burn_logs:
            yield send(log=f"[Bước 4/5] {_msg}", level=_lvl)
        if ok:
            _aspect_combined = _aspect_should_convert
            try:
                _blur_timing_meta.write_text(_j.dumps(_blur_timing_signature, ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass  # A missing cache marker forces a safe re-render next time.
            _s4_dur = _pytime.time() - _t_step4_start
            if _encode_mode == "edit":
                yield send(log=f"[Bước 4/5] Video đã áp dụng chỉnh sửa trong {_s4_dur:.1f}s: {burned_path.name}", level="success")
            elif _encode_mode == "blur":
                yield send(log=f"[Bước 4/5] Video đã che phụ đề gốc trong {_s4_dur:.1f}s: {burned_path.name}", level="success")
            else:
                yield send(log=f"[Bước 4/5] Video có phụ đề trong {_s4_dur:.1f}s: {burned_path.name}", level="success")
            yield send(overall=80, overall_lbl="Xử lý video xong")
            final_output_path = burned_path
        else:
            yield send(log=f"[Bước 4/5] Xử lý thất bại: {err}", level="error")
            pipeline_failed = f"Không thể tạo video đã chỉnh sửa: {err}"
            burned_path = None
    elif do_burn and not srt_path.exists() and not _visual_edit_enabled:
        yield send(log="[Bước 4/5] Không có file phụ đề để burn", level="warning")
    else:
        yield send(log="[Bước 4/5] Bỏ qua burn phụ đề / che", level="info")

    # ── Fallback aspect conversion (normally folded into the burn encode) ─────
    # Nếu user chọn 9x16/16x9 mà video burned không đúng aspect đó → convert.
    # Khi 'auto' hoặc đã đúng aspect → bỏ qua. Đảm bảo chạy TRƯỚC concat
    # thumbnail để aspect của final khớp với thumbnail.
    if _aspect_combined and burned_path and burned_path.exists():
        yield send(
            log=f"[Aspect] Đã gộp chuyển khung {_target_aspect} vào bước burn/che",
            level="success",
        )
    if (
        not _aspect_combined
        and _target_aspect in ("9x16", "16x9")
        and burned_path
        and burned_path.exists()
    ):
        try:
            _r = subprocess.run([ffmpeg, "-i", str(burned_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            _m = re.search(r"(\d{2,5})x(\d{2,5})", _r.stderr or "")
            _src_w, _src_h = (int(_m.group(1)), int(_m.group(2))) if _m else (1280, 720)
        except Exception:
            _src_w, _src_h = 1280, 720

        src_is_vertical = _src_h > _src_w
        target_w, target_h = (1080, 1920) if _target_aspect == "9x16" else (1920, 1080)
        should_convert = (
            (_target_aspect == "9x16" and not src_is_vertical)
            or (_target_aspect == "16x9" and src_is_vertical)
        )

        if not should_convert:
            mode_label = "doc" if _target_aspect == "9x16" else "ngang"
            src_label = "doc" if src_is_vertical else "ngang"
            yield send(
                log=f"[Aspect] Mode {_target_aspect} ({mode_label}): video da {src_label} {_src_w}x{_src_h}, giu nguyen kich thuoc",
                level="info",
            )
        else:
            aspect_video = out_dir / f"{stem}_subbed_{_target_aspect}.mp4"
            yield send(
                log=f"[Aspect] Chuyen huong video: {_src_w}x{_src_h} -> {target_w}x{target_h} ({_target_aspect})",
                level="info",
            )
            if _pad_blur:
                # Nền mờ: video phóng to lấp đầy khung + làm mờ làm nền, video gốc
                # (scale vừa) đặt giữa lên trên. Giống style Shorts/Reel.
                yield send(log="[Aspect] Nen mo (blur) thay cho vien den", level="info")
                if target_h > target_w:
                    blur_w, blur_h = 360, 640
                else:
                    blur_w, blur_h = 640, 360
                blur_zoom_w = int(round(blur_w * 1.12 / 2) * 2)
                blur_zoom_h = int(round(blur_h * 1.12 / 2) * 2)
                filter_complex = (
                    f"[0:v]split=2[bg][fg];"
                    f"[bg]scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,"
                    f"crop={blur_w}:{blur_h},scale={blur_zoom_w}:{blur_zoom_h},"
                    f"crop={blur_w}:{blur_h},gblur=sigma=23,"
                    f"colorchannelmixer=rr=0.7:gg=0.7:bb=0.7,"
                    f"scale={target_w}:{target_h}:flags=bicubic[bgb];"
                    f"[fg]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fgs];"
                    f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]"
                )
                ok_a, err_a = run_ffmpeg([
                    ffmpeg, "-i", str(burned_path),
                    "-filter_complex", filter_complex,
                    "-map", "[vout]", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "copy",
                    str(aspect_video), "-y", "-loglevel", "error",
                ], timeout=600)
            else:
                vf = (
                    f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
                )
                ok_a, err_a = run_ffmpeg([
                    ffmpeg, "-i", str(burned_path),
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "copy",
                    str(aspect_video), "-y", "-loglevel", "error",
                ], timeout=600)
            if ok_a and aspect_video.exists():
                yield send(log=f"[Aspect] Khung hình đã chuyển: {aspect_video.name}", level="success")
                burned_path = aspect_video
                final_output_path = aspect_video
            else:
                yield send(log=f"[Aspect] Convert khung hình thất bại: {err_a}", level="warning")

    # ── Concat thumbnail vào đầu video (sau khi burn + convert aspect xong) ───
    def _emit_thumb_image(thumb_path: Path):
        """Đọc file thumbnail → base64 và emit event để frontend hiển thị."""
        try:
            import base64 as _b64
            mime = "image/png" if thumb_path.suffix.lower() == ".png" else "image/jpeg"
            data_b64 = _b64.b64encode(thumb_path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data_b64}"
        except Exception:
            return ""

    if _thumb_future and burned_path and burned_path.exists():
        try:
            yield send(log="[Bước 4/5] Đợi thumbnail hoàn tất để chèn vào đầu video...", level="info")
            try:
                thumb_result = _thumb_future.result(timeout=120)
            except Exception as _ex:
                thumb_result = None
                yield send(log=f"[Bước 4/5] Lỗi tạo thumbnail: {_ex}", level="warning")

            # ── Retry loop khi AI thumbnail fail (chỉ áp dụng cho mode='ai') ──
            if (not thumb_result or not Path(thumb_result).exists()) and _thumb_mode == "ai":
                from templates.pages.process.route import wait_thumb_retry_action
                _max_retries = 3
                for _attempt in range(1, _max_retries + 1):
                    yield send(
                        thumb_failed=True,
                        thumb_mode=_thumb_mode,
                        log=f"[Bước 4/5] Thumbnail AI thất bại — chờ user xử lý (lần {_attempt}/{_max_retries})",
                        level="warning",
                    )
                    action_data = wait_thumb_retry_action(timeout=600)
                    action = action_data.get("action") or "skip"
                    if action == "retry":
                        yield send(log="[Bước 4/5] Thử tạo lại thumbnail AI...", level="info")
                        try:
                            thumb_result = _gen_ai_thumbnail_for_pipeline(
                                video_path=video_path,
                                output_path=_thumb_target_path,
                                ffmpeg=ffmpeg,
                                timestamp=_thumb_timestamp,
                                title=_thumb_title or video_title,
                                subtitle_text=" ".join(translated_texts[:3]) if translated_texts else "",
                            )
                        except Exception as _re:
                            thumb_result = None
                            yield send(log=f"[Bước 4/5] Retry lỗi: {_re}", level="warning")
                        if thumb_result and Path(thumb_result).exists():
                            yield send(log="[Bước 4/5] Thumbnail AI tạo lại thành công", level="success")
                            break
                    elif action == "upload":
                        user_path = action_data.get("path") or ""
                        try:
                            import shutil as _shutil
                            src = Path(user_path)
                            if src.exists():
                                _shutil.copy2(str(src), str(_thumb_target_path))
                                thumb_result = _thumb_target_path
                                yield send(log=f"[Bước 4/5] Đã dùng ảnh user upload: {src.name}", level="success")
                                break
                            else:
                                yield send(log=f"[Bước 4/5] File upload không tồn tại: {user_path}", level="warning")
                        except Exception as _ue:
                            yield send(log=f"[Bước 4/5] Lỗi copy ảnh upload: {_ue}", level="warning")
                    else:
                        # skip
                        yield send(log="[Bước 4/5] User chọn bỏ qua thumbnail", level="info")
                        thumb_result = None
                        break

            if thumb_result and Path(thumb_result).exists():
                # Emit ảnh thumbnail (base64) để frontend hiển thị real-time
                _img_data = _emit_thumb_image(Path(thumb_result))
                yield send(
                    log=f"[Bước 4/5] Thumbnail đã sẵn sàng: {Path(thumb_result).name}",
                    level="info",
                    thumbnail_path=str(Path(thumb_result).resolve()),
                    thumbnail_image=_img_data,
                )

                concat_out = out_dir / f"{stem}_subbed_with_thumb.mp4"
                yield send(log=f"[Bước 4/5] Đang chèn thumbnail ({_thumb_duration}s) vào đầu video...", level="info")
                ok_c, err_c = concat_thumbnail_with_video(
                    video_path=burned_path,
                    thumbnail_path=Path(thumb_result),
                    output_path=concat_out,
                    ffmpeg=ffmpeg,
                    duration=_thumb_duration,
                )
                if ok_c and concat_out.exists():
                    yield send(log=f"[Bước 4/5] Đã chèn thumbnail: {concat_out.name}", level="success")
                    burned_path = concat_out
                    final_output_path = concat_out
                else:
                    yield send(log=f"[Bước 4/5] Chèn thumbnail thất bại: {err_c}", level="warning")
            else:
                yield send(log="[Bước 4/5] Không có thumbnail — bỏ qua chèn vào video", level="warning")
        except Exception as e:
            yield send(log=f"[Bước 4/5] Lỗi xử lý thumbnail: {e}", level="warning")
        finally:
            try:
                if _thumb_executor:
                    _thumb_executor.shutdown(wait=False)
            except Exception:
                pass

    # ── Bước 5/5: Chờ TTS song song, retry đoạn thiếu, rồi ghép giọng ─────────
    _t_step5_start = _pytime.time()
    try:
        if do_voice and _voice_cache_valid:
            synced_ass = out_dir / f"{stem}_{target_language}_voice_sync.ass"
            if synced_ass.is_file():
                vi_ass_path = synced_ass
                yield send(subtitle_path=str(synced_ass.resolve()))
            final_output_path = voice_path_cached
            yield send(log=f"[Bước 5/5] Dùng lại giọng {target_lang_name} cũ ({_pytime.time() - _t_step5_start:.2f}s): {voice_path_cached.name}", level="info")
            yield send(overall=92, overall_lbl="Dùng lại giọng cũ")
        elif do_voice and translated_texts:
            if _voice_cache_stale_reason:
                yield send(log=f"[Bước 5/5] Bỏ cache giọng cũ ({_voice_cache_stale_reason})", level="info")
            if _tts_future:
                yield send(log="[Bước 5/5] Burn đã xong, kiểm tra kết quả TTS song song...", level="info")
                try:
                    _tts_clips = _tts_future.result()
                except Exception as _tts_err:
                    _tts_clips = []
                    yield send(log=f"[Bước 5/5] Luồng TTS gặp lỗi: {_tts_err}", level="warning")

            clip_by_index = {
                int(clip.get("index")): clip
                for clip in _tts_clips
                if clip.get("index") is not None
            }
            missing_indices = [
                i for i in range(len(translated_texts))
                if i not in clip_by_index
            ]

            while missing_indices:
                missing_details = [
                    {
                        "index": i,
                        "start": float(segments[i].get("start", 0.0)),
                        "end": float(segments[i].get("end", 0.0)),
                        "text": str(translated_texts[i] or ""),
                    }
                    for i in missing_indices
                ]
                from templates.pages.process.route import prepare_tts_retry_wait, wait_tts_retry_action
                prepare_tts_retry_wait()
                yield send(
                    tts_incomplete=True,
                    success_count=len(clip_by_index),
                    total_count=len(translated_texts),
                    missing_segments=missing_details,
                    log=(
                        f"[Bước 5/5] TTS thiếu {len(missing_indices)} đoạn "
                        f"({len(clip_by_index)}/{len(translated_texts)}) — đang chờ xử lý"
                    ),
                    level="warning",
                    overall=88,
                    overall_lbl="Chờ xử lý các đoạn TTS bị thiếu...",
                )
                action_data = wait_tts_retry_action(timeout=600)
                action = str(action_data.get("action") or "cancel").lower()

                if action == "retry":
                    yield send(
                        log=f"[Bước 5/5] Thử lại riêng {len(missing_indices)} đoạn TTS bị thiếu...",
                        level="info",
                    )
                    if not callable(_run_tts_indices):
                        retry_clips = []
                        yield send(
                            log="[Bước 5/5] Tác vụ TTS chưa được khởi tạo; không thể thử lại",
                            level="warning",
                        )
                    else:
                        try:
                            retry_clips = _run_tts_indices(missing_indices)
                        except Exception as retry_err:
                            retry_clips = []
                            yield send(log=f"[Bước 5/5] Retry TTS lỗi: {retry_err}", level="warning")
                    for clip in retry_clips:
                        if clip.get("index") is not None:
                            clip_by_index[int(clip["index"])] = clip
                    missing_indices = [
                        i for i in range(len(translated_texts))
                        if i not in clip_by_index
                    ]
                    if not missing_indices:
                        yield send(log="[Bước 5/5] Đã tạo đủ toàn bộ đoạn TTS", level="success")
                    continue

                if action == "continue":
                    yield send(
                        log=f"[Bước 5/5] Tiếp tục với {len(missing_indices)} đoạn TTS bị thiếu theo xác nhận của người dùng",
                        level="warning",
                    )
                    break

                yield send(
                    log="[Bước 5/5] Đã bỏ lồng tiếng; giữ kết quả burn/che video",
                    level="warning",
                )
                clip_by_index.clear()
                missing_indices = list(range(len(translated_texts)))
                break

            _tts_clips = [clip_by_index[i] for i in sorted(clip_by_index)]
            yield send(
                log=f"[Bước 5/5] TTS clips sẵn sàng: {len(_tts_clips)}/{len(translated_texts)}",
                level="info",
            )

            if _tts_clips and not pipeline_failed:
                source_for_voice = burned_path if burned_path else video_path
                yield send(
                    log="[Bước 5/5] Đang ghép giọng vào video (copy luồng hình, chỉ encode audio)...",
                    level="info",
                    overall=92,
                    overall_lbl="Đang ghép giọng cuối...",
                )
                mixer = AudioMixer(ffmpeg)
                keep_original_audio = original_volume > 0
                yield send(log=f"[Âm thanh] Âm gốc: {original_volume * 100:g}% · Giữ tiếng gốc: {'Bật' if keep_original_audio else 'Tắt'}", level="info")
                ok, err = mixer.mix(
                    video_path=source_for_voice,
                    tts_clips=_tts_clips,
                    output_path=voice_path,
                    keep_bg_music=keep_original_audio,
                    bg_volume=original_volume,
                    tts_volume=_as_float(data.get("tts_volume", 1.8), 1.8),
                )
                if ok:
                    complete = len(_tts_clips) == len(translated_texts)
                    try:
                        voice_meta_path_cached.write_text(
                            json.dumps(
                                {
                                    "tts_cache_version": TTS_CACHE_VERSION,
                                    "mix_config": voice_mix_config,
                                    "subtitle_path": str(Path(srt_path).resolve()) if srt_path else "",
                                    "segments": len(translated_texts),
                                    "generated_segments": len(_tts_clips),
                                    "complete": complete,
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    yield send(log=f"[Bước 5/5] Giọng {target_lang_name} hoàn tất trong {_pytime.time() - _t_step5_start:.1f}s: {voice_path.name}", level="success")
                    yield send(overall=96, overall_lbl="Ghép giọng xong")
                    final_output_path = voice_path
                else:
                    yield send(log=f"[Bước 5/5] Ghép giọng thất bại: {err}", level="error")
                    pipeline_failed = f"Không thể ghép giọng vào video: {err}"
    except Exception as e:
        yield send(log=f"[Bước 5/5] Lỗi xử lý giọng: {e}", level="error")
        if do_voice:
            pipeline_failed = f"Lỗi xử lý giọng: {e}"
    finally:
        try:
            if _tts_executor:
                _tts_executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            if _tts_tmp_ctx:
                _tts_tmp_ctx.cleanup()
        except Exception:
            pass

    # A requested visual encode is not optional. Never silently fall back to the
    # source video and report success when burn/frame/aspect processing failed.
    if pipeline_failed:
        _pipeline_dur = _pytime.time() - _t_pipeline_start
        yield send(
            log=f"Quy trình dừng sau {_pipeline_dur:.1f}s: {pipeline_failed}",
            level="error",
            failed=True,
            overall=0,
            overall_lbl="Xử lý thất bại",
        )
        return

    was_original = False
    if not final_output_path:
        final_output_path = video_path.resolve()
        was_original = True

    do_ext_audio = _as_bool(data.get("ext_audio_enabled", False), False)
    original_gain_applied = do_voice and final_output_path == voice_path
    if not original_gain_applied and original_volume != 1.0:
        adjusted_path = out_dir / f"{stem}_original_volume.mp4"
        ok_volume, err_volume = mix_multiple_external_audios(
            video_path=final_output_path, ext_audios=[], vol_orig=original_volume,
            output_path=adjusted_path, ffmpeg=ffmpeg,
        )
        if not ok_volume:
            yield send(log=f"Không chỉnh được âm gốc: {err_volume}", level="error", failed=True)
            return
        final_output_path = adjusted_path
        was_original = False
        original_gain_applied = True
    ext_audios = data.get("ext_audios") or []
    ext_audio_path_str = str(data.get("ext_audio_path") or "").strip()
    if do_ext_audio and not ext_audios and ext_audio_path_str:
        ext_audios = [{
            "path": ext_audio_path_str,
            "vol": _as_float(data.get("vol_ext", 1.0), 1.0),
            "vid_start": data.get("ext_audio_vid_start", "đầu"),
            "vid_end": data.get("ext_audio_vid_end", "cuối"),
            "clip_start": data.get("ext_audio_clip_start", "0"),
            "clip_end": data.get("ext_audio_clip_end", "hết")
        }]

    if do_ext_audio and ext_audios:
        valid_ext_audios = []
        for track in ext_audios:
            p_str = str(track.get("path") or "").strip()
            if p_str:
                p = Path(p_str).expanduser()
                if p.exists():
                    valid_ext_audios.append({
                        "path": p,
                        "vol": _as_float(track.get("vol", 1.0), 1.0),
                        "vid_start": track.get("vid_start", "đầu"),
                        "vid_end": track.get("vid_end", "cuối"),
                        "clip_start": track.get("clip_start", "0"),
                        "clip_end": track.get("clip_end", "hết")
                    })
        
        if valid_ext_audios:
            yield send(
                log=f"[Âm thanh] Đang ghép {len(valid_ext_audios)} tệp âm thanh ngoài vào video...",
                level="info",
                overall=97,
                overall_lbl="Đang ghép âm thanh ngoài...",
            )
            mixed_path = out_dir / f"{stem}_mixed.mp4"
            # TTS output already contains the original track at its requested
            # gain. Do not attenuate/amplify the combined voice track again.
            vol_orig = 1.0 if original_gain_applied else original_volume
            
            ok_mix, err_mix = mix_multiple_external_audios(
                video_path=final_output_path,
                ext_audios=valid_ext_audios,
                vol_orig=vol_orig,
                output_path=mixed_path,
                ffmpeg=ffmpeg
            )
            if ok_mix and mixed_path.exists():
                yield send(log=f"[Âm thanh] Đã ghép {len(valid_ext_audios)} âm thanh ngoài vào video", level="success")
                final_output_path = mixed_path
                was_original = False
            else:
                yield send(log=f"[Âm thanh] Ghép âm thanh ngoài thất bại: {err_mix}", level="error")
                pipeline_failed = f"Không thể ghép âm thanh ngoài: {err_mix}"
        else:
            yield send(log="[Âm thanh] Không tìm thấy tệp âm thanh ngoài hợp lệ nào để ghép", level="warning")


    if pipeline_failed:
        _pipeline_dur = _pytime.time() - _t_pipeline_start
        yield send(
            log=f"Quy trình dừng sau {_pipeline_dur:.1f}s: {pipeline_failed}",
            level="error",
            failed=True,
            overall=0,
            overall_lbl="Xử lý thất bại",
        )
        return

    if was_original:
        yield send(log="[Hoàn tất] Không có bước chỉnh sửa nào, dùng lại file gốc", level="info", file_path=str(final_output_path))

    # ── Auto Thumbnail ────────────────────────────────────────────────────────
    try:
        thumb_path = out_dir / f"{stem}_thumbnail.jpg"
        # Nội dung thumbnail: dùng translated_texts hoặc tên video
        thumb_subtitle = ""
        if translated_texts:
            # Lấy 2-3 câu đầu làm nội dung
            thumb_subtitle = " ".join(translated_texts[:3])[:100]
        elif video_title:
            thumb_subtitle = video_title

        # Resolve logo_path for standard thumbnail
        _logo_path = str(data.get("frame_logo_path") or data.get("logo_path") or "").strip()

        # Thumbnail flow disabled by request.
        thumb_ok, thumb_result = False, "thumbnail disabled"
        if thumb_ok:
            # Encode base64 để frontend hiển thị trực tiếp (không cần serve static)
            thumb_b64 = ""
            try:
                import base64 as _b64
                with open(thumb_path, "rb") as _f:
                    thumb_b64 = "data:image/jpeg;base64," + _b64.b64encode(_f.read()).decode()
            except Exception:
                pass
            yield send(
                log=f"[Thumbnail] Tạo thumbnail: {thumb_path.name}",
                level="success",
                thumbnail_path=str(thumb_path.resolve()),
                thumbnail_image=thumb_b64,
            )
        elif thumb_result != "thumbnail disabled":
            yield send(log=f"[Thumbnail] Không tạo được thumbnail: {thumb_result}", level="warning")
    except Exception as _thumb_err:
        yield send(log=f"[Thumbnail] Lỗi tạo thumbnail: {_thumb_err}", level="warning")

    # ── Cleanup file trung gian ───────────────────────────────────────────────
    if final_output_path and final_output_path.exists():
        from core.processor.completed_outputs import register_output
        register_output(final_output_path, vi_ass_path or srt_path)

    if cleanup_outputs and final_output_path and final_output_path.exists():
        # Giữ lại SRT/ASS để resume lần sau, chỉ xóa file trung gian không cần thiết
        intermediates_to_clean = []
        # Xóa _subbed nếu đã có _voice hoặc _framed (bước sau đã dùng xong)
        if burned_path and burned_path != final_output_path:
            intermediates_to_clean.append(burned_path)
        # Xóa _voice nếu đã có _framed
        voice_p = out_dir / f"{stem}_{target_language}_voice.mp4"
        if voice_p.exists() and voice_p != final_output_path:
            intermediates_to_clean.append(voice_p)

        for extra in intermediates_to_clean:
            try:
                if extra and Path(extra).exists() and Path(extra).resolve() != final_output_path.resolve():
                    Path(extra).unlink()
            except Exception:
                pass

        if delete_source_after:
            try:
                src = Path(video_path)
                if src.exists() and src.resolve() != final_output_path.resolve():
                    src.unlink()
            except Exception:
                pass

        yield send(log=f"[Hoàn tất] File cuối cùng: {final_output_path.name}", level="success", file_path=str(final_output_path.resolve()))

    _pipeline_dur = _pytime.time() - _t_pipeline_start
    yield send(log=f"Toàn bộ quy trình hoàn tất trong {_pipeline_dur:.1f}s!", level="success")
    yield send(overall=100, overall_lbl="Hoàn tất")

    # ── Backend auto-upload after processing ─────────────────────────────────
    upload_cfg = dict((cfg_raw.get("upload") or {}))
    if upload_cfg.get("auto_upload") and final_output_path and final_output_path.exists():
        platform = str(upload_cfg.get("platform") or "").lower()
        title = str(data.get("video_title") or final_output_path.stem)
        # Clean title same way as frontend
        import re as _re
        title = _re.sub(r'_([a-z]{2})_(voice|voice)$', '', title, flags=_re.IGNORECASE)
        title = _re.sub(r'_(vi_voice|voice|vi|en_voice|en|ja_voice|ja|ko_voice|ko)$', '', title, flags=_re.IGNORECASE)
        title = _re.sub(r'^\d{4}-\d{2}-\d{2}_', '', title)
        title = _re.sub(r'_\d{15,}$', '', title)
        title = title.replace('_', ' ').strip()

        if platform in ("tiktok", "both"):
            try:
                from tools.tiktok_uploader import TikTokUploader
                tiktok_cfg = upload_cfg.get("tiktok") or {}
                uploader = TikTokUploader()
                if uploader.authenticate(str(tiktok_cfg.get("client_key") or ""), str(tiktok_cfg.get("client_secret") or "")):
                    privacy = str(tiktok_cfg.get("privacy_status") or "SELF_ONLY").upper()
                    privacy_map = {"private": "SELF_ONLY", "public": "PUBLIC_TO_EVERYONE", "friends": "MUTUAL_FOLLOW_FRIENDS"}
                    privacy = privacy_map.get(privacy.lower(), privacy)
                    result = uploader.upload_video(str(final_output_path), title=title, privacy_level=privacy)
                    if result:
                        yield send(log=f"[Auto-upload] TikTok: {result.get('publish_id')}", level="success")
                    else:
                        yield send(log=f"[Auto-upload] TikTok: {uploader.last_error}", level="error")
                else:
                    yield send(log="[Auto-upload] TikTok chưa đăng nhập, bỏ qua", level="warning")
            except Exception as e:
                yield send(log=f"[Auto-upload] TikTok lỗi: {e}", level="error")

        if platform in ("youtube", "both"):
            try:
                from tools.youtube_uploader import YouTubeUploader
                yt_cfg = upload_cfg.get("youtube") or {}
                uploader = YouTubeUploader()
                if uploader.credentials or uploader.authenticate():
                    # Extract hashtags from filename
                    import re
                    stem = final_output_path.stem
                    chinese_parts = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F_]*', stem)
                    hashtags = []
                    if chinese_parts:
                        try:
                            hashtags = ['#' + part.replace(' ', '').lower() for part in chinese_parts]
                        except:
                            hashtags = ['#' + part.replace(' ', '') for part in chinese_parts]
                    
                    default_tags = ['douyin', 'tiktok', 'video']
                    all_tags = default_tags + [h[1:] for h in hashtags]
                    
                    result = uploader.upload_video(final_output_path, title=title,
                        description=title, privacy_status=str(yt_cfg.get("privacy_status") or "private"),
                        tags=all_tags,
                        is_short=bool(yt_cfg.get("short", False)))
                    if result:
                        yield send(log=f"[Auto-upload] YouTube: {result.get('url')}", level="success")
                    else:
                        yield send(log="[Auto-upload] YouTube upload thất bại", level="error")
                else:
                    yield send(log="[Auto-upload] YouTube chưa đăng nhập, bỏ qua", level="warning")
            except Exception as e:
                yield send(log=f"[Auto-upload] YouTube lỗi: {e}", level="error")



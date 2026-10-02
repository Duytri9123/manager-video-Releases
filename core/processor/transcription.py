#!/usr/bin/env python3
"""
core.processor.transcription
Speech-to-Text transcription engines: Groq Whisper, Antigravity API,
and local Faster-Whisper with memory caching.
"""
import os
import re
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from core.processor.ffmpeg_base import (
    find_ffmpeg, run_ffmpeg, _run_ffmpeg, _safe_stem, _winlong,
    get_media_duration_seconds, _get_media_duration
)
from core.processor.subtitles import _fmt_srt_time, _parse_srt_text_to_segments

_GROQ_MODEL   = "whisper-large-v3-turbo"
_GROQ_MAX_MB  = 25  # Groq free tier limit


class GroqWhisperTranscriber:
    """Speech-to-text via Groq Whisper API (cloud, fast)."""

    def __init__(self, language: str = "zh", api_key: str = "", model: str = _GROQ_MODEL, max_mb: int = _GROQ_MAX_MB):
        self.language = language
        self.api_key = (api_key or "").strip()
        self.model = str(model or _GROQ_MODEL).strip() or _GROQ_MODEL
        try:
            self.max_mb = int(max_mb)
        except Exception:
            self.max_mb = _GROQ_MAX_MB

    def transcribe(self, video_path: Path, ffmpeg: str, out_srt: Path):
        import httpx
        import time

        video_path = Path(video_path)
        out_srt    = Path(out_srt)

        with tempfile.TemporaryDirectory(prefix="groq_whisper_") as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            yield ("log", "[Bước 2/5] 🔊 Đang trích xuất âm thanh từ video...", "info")
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(video_path),
                "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-q:a", "5",
                str(audio_path), "-y", "-loglevel", "error"
            ])
            if not ok or not audio_path.exists():
                raise RuntimeError(f"Audio extraction failed: {err}")

            size_mb = audio_path.stat().st_size / (1024 * 1024)
            if size_mb > self.max_mb:
                raise RuntimeError(f"Audio too large for Groq API: {size_mb:.1f}MB > {self.max_mb}MB")

            if not self.api_key:
                raise RuntimeError("Missing GROQ_API_KEY (set env GROQ_API_KEY or config transcript.groq_api_key)")

            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            yield ("log", f"[Bước 2/5] 🔌 Kết nối Groq API: {url} (Model: {self.model})", "info")
            yield ("log", "[Bước 2/5] 📡 Đang gửi file âm thanh tới Groq Whisper và chờ phiên âm...", "info")

            t0 = time.time()
            with open(audio_path, "rb") as f:
                response = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"file": ("audio.mp3", f, "audio/mpeg")},
                    data={
                        "model": self.model,
                        "language": self.language,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                    },
                    timeout=120,
                )
            dt = time.time() - t0

            if response.status_code != 200:
                yield ("log", f"[Bước 2/5] ❌ Lỗi phản hồi từ Groq Whisper STT (status={response.status_code}): {response.text}", "error")
                raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")

            yield ("log", f"[Bước 2/5] 📥 Nhận kết quả phiên âm từ Groq thành công (Thời gian: {dt:.1f}s)", "success")
            result = response.json()
            segments = [
                {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
                for seg in result.get("segments", [])
                if seg.get("text", "").strip()
            ]

        # write SRT
        srt_lines = []
        for i, seg in enumerate(segments, 1):
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{seg['text']}\n"
            )
        # Dùng _winlong để xử lý path > 260 ký tự trên Windows
        with open(_winlong(out_srt), "w", encoding="utf-8") as _f:
            _f.write("\n".join(srt_lines))
        yield ("result", segments)


# ══════════════════════════════════════════════════════════════════════════════
# AntigravityTranscriber (STT via Antigravity / Gemini Multimodal AI)
# ══════════════════════════════════════════════════════════════════════════════


class AntigravityTranscriber:
    """Speech-to-text via Antigravity provider connection with multi-key and model fallbacks."""

    def __init__(self, language: str = "zh", api_key: str = "", model_name: str = "", multi_speaker: bool = False, provider: str = "antigravity"):
        self.language = language
        self.api_key = (api_key or "").strip()
        m = (model_name or "").strip()
        if m in ["tiny", "base", "small", "medium", "large", "auto", "model"]:
            m = ""
        if "/" in m:
            m = m.split("/")[-1]
        self.model_name = m
        self.multi_speaker = bool(multi_speaker)
        self.provider = provider

    def transcribe(self, video_path: Path, ffmpeg: str, out_srt: Path):
        import subprocess, base64, urllib.request, urllib.error, json, tempfile, re
        video_path = Path(video_path)
        out_srt = Path(out_srt)
        video_dur = _get_media_duration(video_path, ffmpeg)

        # Collect candidate keys & connections
        candidates_keys = []
        try:
            from core.ai_models_manager import get_active_provider_connections
            conns = get_active_provider_connections(self.provider)
            if not conns and self.provider == "antigravity":
                conns = get_active_provider_connections("gemini")
            for conn in conns:
                k = (conn.get("api_key") or conn.get("access_token") or "").strip()
                b = (conn.get("base_url") or "").strip()
                p_id = (conn.get("project_id") or "").strip() or "aicode-consumers"
                candidates_keys.append({
                    "key": k,
                    "base_url": b,
                    "project_id": p_id,
                    "conn": dict(conn),
                })
        except Exception:
            pass

        if self.api_key:
            matching_idx = next((i for i, ck in enumerate(candidates_keys) if ck["key"] == self.api_key), -1)
            if matching_idx > 0:
                candidates_keys.insert(0, candidates_keys.pop(matching_idx))
            elif matching_idx == -1:
                candidates_keys.insert(0, {
                    "key": self.api_key,
                    "base_url": "",
                    "project_id": "aicode-consumers",
                    "conn": {
                        "api_key": self.api_key,
                        "refresh_token": (self.api_key if self.api_key.startswith("1//") else ""),
                        "base_url": "",
                        "project_id": "aicode-consumers"
                    }
                })

        # Fallback to env variable
        env_key = (os.getenv("GEMINI_API_KEY", "").strip() if self.provider == "gemini"
                   else os.getenv("ANTIGRAVITY_API_KEY", "").strip())
        if env_key and not any(ck["key"] == env_key for ck in candidates_keys):
            candidates_keys.append({
                "key": env_key,
                "base_url": "",
                "project_id": "aicode-consumers",
                "conn": {
                    "api_key": env_key,
                    "refresh_token": (env_key if env_key.startswith("1//") else ""),
                    "base_url": "",
                    "project_id": "aicode-consumers"
                }
            })

        if not candidates_keys:
            yield ("log", "Chưa cấu hình khóa kết nối Antigravity. Vui lòng mở trang Nhà cung cấp để thêm kết nối Antigravity.", "error")
            yield ("log", "Bỏ qua phiên âm tự động.", "warning")
            yield ("result", [])
            return

        with tempfile.TemporaryDirectory(prefix="ag_stt_") as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            yield ("log", "[Bước 2/5] Đang trích xuất âm thanh từ video (tối ưu tốc độ cao)...", "info")
            # Tăng tốc độ trích xuất bằng ultrafast và mono 16kHz 48k
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(video_path),
                "-vn", "-threads", "0", "-preset", "ultrafast",
                "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "48k",
                str(audio_path), "-y", "-loglevel", "error"
            ])
            if not ok or not audio_path.exists():
                yield ("log", f"Trích xuất âm thanh thất bại: {err}", "error")
                yield ("result", [])
                return

            # Long recordings can produce an empty/truncated response even when
            # the same connection answers short text prompts successfully.
            chunk_seconds = 180
            audio_duration = _get_media_duration(audio_path, ffmpeg) or video_dur
            audio_chunks = []
            for offset in range(0, max(1, int(audio_duration + 0.999)), chunk_seconds):
                chunk_path = Path(tmpdir) / f"chunk_{offset:05d}.mp3"
                ok, err = run_ffmpeg([
                    ffmpeg, "-ss", str(offset), "-t", str(chunk_seconds),
                    "-i", str(audio_path), "-acodec", "copy",
                    str(chunk_path), "-y", "-loglevel", "error"
                ])
                if not ok or not chunk_path.exists() or chunk_path.stat().st_size == 0:
                    yield ("log", f"Không chia được âm thanh tại {offset}s: {err}", "error")
                    yield ("result", [])
                    return
                audio_chunks.append((offset, chunk_path))

            lang_names = {"zh": "Tiếng Trung", "en": "Tiếng Anh", "vi": "Tiếng Việt", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn", "th": "Tiếng Thái"}
            target_lang = lang_names.get(self.language, self.language)

            diarization_guide = ""
            if self.multi_speaker:
                diarization_guide = (
                    "ĐẶC BIỆT - NHẬN DIỆN VÀ PHÂN VAI GIỌNG NÓI (SPEAKER DIARIZATION):\n"
                    "- Hãy nghe âm thanh thực tế và phân tích cao độ, âm sắc của từng người nói.\n"
                    "- Đầu mỗi câu, BẮT BUỘC ghi rõ nhãn nhân vật: [Nam] nếu là giọng nam/đàn ông, hoặc [Nữ] nếu là giọng nữ/phụ nữ.\n"
                    "- Ví dụ:\n"
                    "1\n"
                    "00:00:01,000 --> 00:00:03,500\n"
                    "[Nam]: Xin chào mọi người!\n\n"
                    "2\n"
                    "00:00:04,000 --> 00:00:06,000\n"
                    "[Nữ]: Cho em đi với nhé anh!\n\n"
                )

            prompt = (
                f"Hãy nghe âm thanh và phiên âm toàn bộ lời nói sang {target_lang}.\n"
                + diarization_guide +
                "QUY TẮC NGẮT CÂU VÀ DẤU CÂU:\n"
                "- BẮT BUỘC thêm dấu câu đúng ngữ pháp: dấu phẩy (,) dấu chấm (.) dấu chấm hỏi (?) dấu chấm than (!) vào đúng vị trí.\n"
                "- Mỗi block SRT phải là MỘT câu hoặc MỘT mệnh đề hoàn chỉnh về ngữ nghĩa (6-12 từ là lý tưởng).\n"
                "- TUYỆT ĐỐI KHÔNG cắt câu giữa chừng rồi để phần còn lại sang block tiếp theo.\n"
                "- TUYỆT ĐỐI KHÔNG gộp nhiều câu dài vào 1 block (mỗi block tối đa 12-15 từ).\n"
                "- Ví dụ SAI: block 1 = 'Khi số lượng muỗi đạt đến một' block 2 = 'mức độ nhất định chúng có thể' (cắt giữa câu, không có dấu câu).\n"
                "- Ví dụ ĐÚNG: block 1 = 'Khi số lượng muỗi đạt đến một mức độ nhất định,' block 2 = 'chúng có thể hút cạn máu một con sói con đến chết.' (ngắt tại ranh giới mệnh đề, có dấu câu).\n"
                "\nQUY TẮC MỐC THỜI GIAN SRT:\n"
                "- BẮT BUỘC định dạng SRT chuẩn: HH:MM:SS,mmm --> HH:MM:SS,mmm (Giờ:Phút:Giây,Miligiây).\n"
                "- TUYỆT ĐỐI KHÔNG dùng dấu ngoặc vuông [] quanh mốc thời gian.\n"
                "- Bắt buộc mỗi câu là 1 block SRT riêng biệt có số thứ tự tăng dần, cách nhau 1 dòng trống:\n"
                "1\n"
                "00:00:01,000 --> 00:00:04,000\n"
                "Khi số lượng muỗi đạt đến một mức độ nhất định,\n\n"
                "2\n"
                "00:00:04,500 --> 00:00:07,000\n"
                "chúng có thể hút cạn máu một con sói con đến chết.\n\n"
                "- Thời gian bắt đầu luôn nhỏ hơn thời gian kết thúc, khớp chính xác với âm thanh phát ra trong video.\n"
                "- TUYỆT ĐỐI KHÔNG SUY NGHĨ (no thinking, no reasoning), không thêm suy nghĩ hay giải thích.\n"
                "- Chỉ xuất trực tiếp duy nhất khối nội dung SRT hoàn chỉnh."
            )


            # Chọn model đang bật cho đúng provider, giống danh sách của Chat Bot.
            chosen_model = ""
            available_stt_models = []
            try:
                from core.ai_models_manager import get_available_models
                available_stt_models = [str(m["id"]) for m in get_available_models("llm", active_only=True)
                                        if m.get("owned_by") == self.provider
                                        and not any(bad in str(m["id"]).lower()
                                                    for bad in ("thinking", "claude", "gpt-oss", "image"))]
            except Exception:
                pass
            if self.model_name:
                m_lower = self.model_name.lower()
                if not any(bad in m_lower for bad in ["thinking", "claude", "gpt-oss", "image"]) and (not available_stt_models or self.model_name in available_stt_models):
                    chosen_model = self.model_name

            if not chosen_model:
                try:
                    from core.ai_models_manager import get_available_models
                    avail = get_available_models(category="llm", active_only=True)
                    # Ưu tiên gemini-3.8-flash-high trước để không bị timeout/fallback
                    for target_m in ["gemini-3.8-flash-high", "gemini-3.8-flash"]:
                        for dm in avail:
                            if dm.get("id") == target_m:
                                chosen_model = target_m
                                break
                        if chosen_model:
                            break
                    if not chosen_model:
                        for dm in avail:
                            if dm.get("owned_by") == self.provider and dm.get("id"):
                                mid = str(dm["id"])
                                mid_lower = mid.lower()
                                if not any(bad in mid_lower for bad in ["thinking", "claude", "gpt-oss", "image"]):
                                    chosen_model = mid
                                    break
                except Exception:
                    pass

            if not chosen_model:
                chosen_model = "gemini-3.8-flash-high"

            # Chỉ thử 1 model (cùng lắm 1 fallback nếu 404 Model Not Found), KHÔNG lặp qua toàn bộ model khi lỗi tài khoản
            models_to_try = [chosen_model]
            models_to_try.extend(m for m in available_stt_models if m != chosen_model)
            models_to_try = models_to_try[:3]

            all_segs = []
            for chunk_index, (offset, chunk_path) in enumerate(audio_chunks, 1):
                end = min(offset + chunk_seconds, audio_duration)
                start_label = f"{int(offset)//60:02d}:{int(offset)%60:02d}"
                end_label = f"{int(end)//60:02d}:{int(end)%60:02d}"
                yield ("log", f"[Phiên âm] Phần {chunk_index}/{len(audio_chunks)} · âm thanh {start_label}–{end_label}", "info")
                b64_audio = base64.b64encode(chunk_path.read_bytes()).decode("ascii")
                srt_text = ""
                stt_error = ""

                for conn_idx, conn_item in enumerate(candidates_keys, 1):
                    k = conn_item["key"]
                    b_url = conn_item.get("base_url") or ""
                    conn_name = (conn_item.get("conn") or {}).get("name") or (conn_item.get("conn") or {}).get("id") or f"Tài khoản #{conn_idx}"

                    from core.direct_ai_provider import (
                        detect_key_type, antigravity_generate_content, ProviderError,
                        ANTIGRAVITY_MODEL_ALIASES, ANTIGRAVITY_USER_AGENT
                    )
                    key_type = detect_key_type(k)

                    c_obj = conn_item.get("conn") or {
                        "api_key": k,
                        "refresh_token": (conn_item.get("conn") or {}).get("refresh_token") or (k if k.startswith("1//") else ""),
                        "base_url": b_url,
                        "project_id": conn_item.get("project_id", "aicode-consumers")
                    }

                    for model in models_to_try:
                        yield ("log", f"[Phiên âm] Đang nhận diện lời nói · tài khoản: {conn_name} · mô hình: {model}", "info")

                        try:
                            is_oauth = key_type in ("oauth_token", "refresh_token") or "cloudcode" in b_url or (c_obj.get("auth_type") == "oauth") or bool(c_obj.get("refresh_token"))
                            if is_oauth:
                                # Dùng antigravity_generate_content: tự refresh token, tự map model alias, tự điền project_id chuẩn
                                req_body = {
                                    "contents": [{
                                        "parts": [
                                            {"text": prompt},
                                            {"inlineData": {"mimeType": "audio/mp3", "data": b64_audio}}
                                        ]
                                    }],
                                    "generationConfig": {
                                        "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False}
                                    }
                                }
                                resp_data, updates = antigravity_generate_content(c_obj, model, req_body, timeout=60)
                                if updates and c_obj.get("id"):
                                    try:
                                        from core.direct_ai_provider import update_db_connection
                                        update_db_connection(c_obj["id"], updates)
                                    except Exception:
                                        pass
                            else:
                                # API Key path: generativelanguage.googleapis.com
                                base_endpoint = (b_url or "https://generativelanguage.googleapis.com").rstrip("/")
                                url = f"{base_endpoint}/v1beta/models/{model}:generateContent?key={k}" if key_type == "api_key" else f"{base_endpoint}/v1beta/models/{model}:generateContent"
                                headers = {"Content-Type": "application/json"}
                                if key_type != "api_key":
                                    headers["Authorization"] = f"Bearer {k}"
                                payload = json.dumps({
                                    "contents": [{
                                        "parts": [
                                            {"text": prompt},
                                            {"inlineData": {"mimeType": "audio/mp3", "data": b64_audio}}
                                        ]
                                    }],
                                    "generationConfig": {
                                        "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False}
                                    }
                                }).encode("utf-8")
                                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                                with urllib.request.urlopen(req, timeout=60) as resp:
                                    r_json = json.loads(resp.read().decode("utf-8"))
                                    resp_data = r_json.get("response") if isinstance(r_json.get("response"), dict) else r_json

                            # Lấy text trả về
                            candidates = resp_data.get("candidates") or []
                            if not candidates:
                                stt_error = str(resp_data.get("promptFeedback") or "API trả về danh sách candidates rỗng")
                            elif not candidates[0].get("content", {}).get("parts"):
                                stt_error = f"API không trả nội dung (finishReason={candidates[0].get('finishReason', 'unknown')})"
                            if candidates and "content" in candidates[0]:
                                parts = candidates[0]["content"].get("parts") or []
                                text_parts = []
                                for p in parts:
                                    if isinstance(p, dict):
                                        if p.get("thought") is True:
                                            continue
                                        t = p.get("text") or ""
                                        if t:
                                            text_parts.append(t)
                                    elif isinstance(p, str):
                                        text_parts.append(p)
                                srt_text = "".join(text_parts)
                                srt_text = re.sub(r'<thought>.*?</thought>', '', srt_text, flags=re.DOTALL)
                                srt_text = re.sub(r'<think>.*?</think>', '', srt_text, flags=re.DOTALL).strip()
                                if srt_text:
                                    break
                        except ProviderError as pe:
                            stt_error = str(pe)
                            if pe.status == 404:
                                yield ("log", f"Model {model} không khả dụng; thử model đang bật tiếp theo...", "warning")
                                continue
                            yield ("log", f"{conn_name} gặp lỗi ({stt_error}). Đổi sang tài khoản tiếp theo...", "warning")
                            break  # Lỗi tài khoản -> Chuyển ngay sang connection tiếp theo, KHÔNG lặp qua các model khác!
                        except urllib.error.HTTPError as he:
                            err_body = he.read().decode("utf-8", "replace") if hasattr(he, "read") else ""
                            stt_error = f"HTTP Error {he.code}: {err_body[:200]}"
                            if he.code in (401, 403, 429):
                                yield ("log", f"{conn_name} gặp lỗi HTTP {he.code}. Đổi sang tài khoản tiếp theo...", "warning")
                                break  # Lỗi xác thực/quota -> Chuyển ngay sang connection tiếp theo!
                            if he.code == 404:
                                # 404 Model Not Found: cho phép thử 1 model fallback
                                continue
                            yield ("log", f"{conn_name} gặp lỗi HTTP {he.code}. Đổi tài khoản...", "warning")
                            break
                        except Exception as exc:
                            stt_error = str(exc)
                            yield ("log", f"{conn_name} lỗi kết nối ({stt_error[:100]}). Đổi tài khoản...", "warning")
                            break

                    if srt_text:
                        break

                if not srt_text:
                    yield ("log", f"Phiên âm đoạn {chunk_index}/{len(audio_chunks)} thất bại: {stt_error or 'API không trả văn bản'}.", "error")
                    yield ("result", [])
                    return
                segs = _parse_srt_text_to_segments(srt_text, video_dur=chunk_seconds)
                if not segs:
                    yield ("log", f"Đoạn {chunk_index} không có mốc thời gian SRT hợp lệ.", "error")
                    yield ("result", [])
                    return
                for seg in segs:
                    seg["start"] = round(seg["start"] + offset, 3)
                    seg["end"] = round(min(video_dur, seg["end"] + offset), 3)
                all_segs.extend(seg for seg in segs if seg["end"] > seg["start"])

            from core.processor.subtitles import process_speaker_tags_in_segments
            process_speaker_tags_in_segments(all_segs)
            srt_blocks = []
            for i, seg in enumerate(all_segs, 1):
                start_str = _fmt_srt_time(seg["start"])
                end_str = _fmt_srt_time(seg["end"])
                spk_lbl = f"[{'Nam' if seg.get('speaker') == 'male' else 'Nữ'}] " if seg.get("speaker") else ""
                srt_blocks.append(f"{i}\n{start_str} --> {end_str}\n{spk_lbl}{seg['text']}\n")
            with open(_winlong(out_srt), "w", encoding="utf-8") as output:
                output.write("\n".join(srt_blocks))
            yield ("result", all_segs)


# ══════════════════════════════════════════════════════════════════════════════
# FasterWhisperTranscriber  (fallback — local CPU)
# ══════════════════════════════════════════════════════════════════════════════
_whisper_model_cache: dict = {}  # {model_name: WhisperModel} — keep in memory


class FasterWhisperTranscriber:
    """Speech-to-text using faster-whisper (~4x faster than openai-whisper on CPU)."""

    def __init__(self, model_name: str, language: str, use_vad: bool = True):
        self.model_name = model_name
        self.language = language
        self.use_vad = use_vad
        # Reuse cached model to avoid reloading from disk on every call
        if model_name not in _whisper_model_cache:
            import os
            import multiprocessing
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from faster_whisper import WhisperModel  # lazy import
            cpu_threads = min(multiprocessing.cpu_count(), 8)
            _whisper_model_cache[model_name] = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
                num_workers=2,
            )
        self._model = _whisper_model_cache[model_name]

    def transcribe(self, video_path: Path, ffmpeg: str, out_srt: Path) -> list[dict]:
        """
        Extract audio from video, transcribe with faster-whisper, write SRT.
        Returns list of {"start": float, "end": float, "text": str} dicts.
        """
        video_path = Path(video_path)
        out_srt = Path(out_srt)

        with tempfile.TemporaryDirectory(prefix="fwhisper_") as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            ok, err = run_ffmpeg([
                ffmpeg, "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(audio_path), "-y", "-loglevel", "error"
            ])
            if not ok or not audio_path.exists():
                raise RuntimeError(f"Audio extraction failed: {err}")

            fw_segments, _info = self._model.transcribe(
                str(audio_path),
                language=self.language,
                vad_filter=self.use_vad,
                beam_size=1,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = [
                {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                for seg in fw_segments
                if seg.text.strip()
            ]

        # write SRT
        srt_lines = []
        for i, seg in enumerate(segments, 1):
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{seg['text']}\n"
            )
        with open(_winlong(out_srt), "w", encoding="utf-8") as _f:
            _f.write("\n".join(srt_lines))

        return segments


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Whisper transcribe → SRT
# ══════════════════════════════════════════════════════════════════════════════
def transcribe_to_srt(
    video_path: Path,
    ffmpeg: str,
    model_name: str = "base",
    language: str = "zh",
    out_srt: Optional[Path] = None,
) -> tuple[Optional[Path], list[dict]]:
    """
    Transcribe video audio → SRT file.
    Returns (srt_path, segments).
    """
    try:
        import whisper
    except ImportError:
        raise RuntimeError("openai-whisper not installed: pip install openai-whisper")

    video_path = Path(video_path)
    if out_srt is None:
        out_srt = video_path.parent / f"{_safe_stem(video_path.stem)}.srt"

    with tempfile.TemporaryDirectory(prefix="vproc_") as tmpdir:
        # copy video to temp (avoid special chars in path)
        tmp_video = Path(tmpdir) / "input.mp4"
        shutil.copy2(str(video_path), str(tmp_video))

        # extract audio
        audio_path = Path(tmpdir) / "audio.wav"
        ok, err = run_ffmpeg([
            ffmpeg, "-i", str(tmp_video),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path), "-y", "-loglevel", "error"
        ])
        if not ok or not audio_path.exists():
            raise RuntimeError(f"Audio extraction failed: {err}")

        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), language=language, verbose=False)
        segments = result.get("segments", [])

    if not segments:
        return None, []

    # write SRT
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        text = seg.get("text", "").strip()
        if text:
            srt_lines.append(
                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{text}\n"
            )
    out_srt.write_text("\n".join(srt_lines), encoding="utf-8")
    return out_srt, segments


# ══════════════════════════════════════════════════════════════════════════════
# FRAME VIDEO: Convert to 9:16 with title bar, side blur, logo
# ══════════════════════════════════════════════════════════════════════════════


def classify_dialogue_speakers(
    segments: list[dict],
    trans_cfg: dict | None = None,
    preferred_provider: str = "antigravity",
    target_lang: str = "vi",
) -> list[dict]:
    """
    Phân vai nhân vật Nam (male) / Nữ (female) cho các đoạn hội thoại bằng AI.
    Dùng khi transcriber (như Whisper) không trích xuất sẵn nhãn người nói.
    """
    if not segments:
        return segments

    # Nếu trên 50% câu đã có speaker thì không cần classify lại
    tagged_count = sum(1 for s in segments if s.get("speaker"))
    if tagged_count >= len(segments) * 0.5:
        return segments

    import json, urllib.request
    from core.processor.subtitles import extract_speaker_from_text

    # Thử bóc tách từ text trước (phòng trường hợp text còn chứa [Nam], [Nữ],...)
    for s in segments:
        clean_text, spk = extract_speaker_from_text(s.get("text", ""))
        s["text"] = clean_text
        if spk and not s.get("speaker"):
            s["speaker"] = spk

    tagged_count = sum(1 for s in segments if s.get("speaker"))
    if tagged_count >= len(segments) * 0.5:
        return segments

    lines_to_classify = []
    for idx, s in enumerate(segments):
        t = str(s.get("text") or "").strip()
        lines_to_classify.append(f"{idx}: {t}")

    prompt_content = (
        "Bạn là đạo diễn lồng tiếng chuyên nghiệp. Hãy đọc các câu thoại sau và phân loại người nói:\n"
        "- 'male' nếu là giọng nam (đàn ông, con trai, chú, anh, người kể chuyện nam)\n"
        "- 'female' nếu là giọng nữ (phụ nữ, con gái, chị, cô, em gái)\n"
        "Căn cứ vào đại từ nhân xưng (anh/em, chú/cháu, vợ/chồng, tôi, cậu/tớ), ngữ cảnh hội thoại.\n"
        "Nếu là độc thoại không rõ giới tính, mặc định chọn 'male'.\n"
        "BẮT BUỘC chỉ trả về 1 JSON duy nhất dạng: {\"0\": \"male\", \"1\": \"female\", ...} không có chữ nào khác.\n\n"
        "Danh sách câu:\n"
        + "\n".join(lines_to_classify[:120])
    )

    # 1. Thử gọi Antigravity / Gemini
    classified_map = {}
    try:
        from core.ai_models_manager import get_active_provider_connections
        conns = get_active_provider_connections("antigravity") or get_active_provider_connections("gemini")
        if conns:
            conn = conns[0]
            api_key = (conn.get("api_key") or conn.get("access_token") or "").strip()
            base_url = (conn.get("base_url") or "").strip().rstrip("/")
            if not base_url:
                base_url = "https://generativelanguage.googleapis.com"
            model = "gemini-3.8-flash-high"
            url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
            req_data = {
                "contents": [{"parts": [{"text": prompt_content}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024,
                                     "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False}}
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(req_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                ans_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                ans_text = re.sub(r"^```[a-zA-Z]*\n?", "", ans_text.strip())
                ans_text = re.sub(r"```$", "", ans_text.strip())
                classified_map = json.loads(ans_text)
    except Exception:
        pass

    # 2. Thử gọi OpenAI / DeepSeek / Groq nếu chưa có kết quả
    if not classified_map and trans_cfg:
        try:
            api_key = trans_cfg.get("deepseek_key") or trans_cfg.get("groq_key") or trans_cfg.get("openai_key")
            api_url = "https://api.deepseek.com/v1/chat/completions" if trans_cfg.get("deepseek_key") else (
                "https://api.groq.com/openai/v1/chat/completions" if trans_cfg.get("groq_key") else "https://api.openai.com/v1/chat/completions"
            )
            model = "deepseek-chat" if trans_cfg.get("deepseek_key") else (
                trans_cfg.get("groq_model", "llama-3.1-8b-instant") if trans_cfg.get("groq_key") else "gpt-4o-mini"
            )
            if api_key:
                req_data = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt_content}],
                    "temperature": 0.1,
                }
                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    ans_text = res_json["choices"][0]["message"]["content"]
                    ans_text = re.sub(r"^```[a-zA-Z]*\n?", "", ans_text.strip())
                    ans_text = re.sub(r"```$", "", ans_text.strip())
                    classified_map = json.loads(ans_text)
        except Exception:
            pass

    # 3. Gán kết quả vào segments
    for idx, s in enumerate(segments):
        if s.get("speaker"):
            continue
        role = str(classified_map.get(str(idx)) or classified_map.get(idx) or "").lower().strip()
        if "female" in role or "nữ" in role:
            s["speaker"] = "female"
        elif "male" in role or "nam" in role:
            s["speaker"] = "male"
        else:
            # Fallback phân tích ngữ nghĩa nhẹ
            txt = str(s.get("text") or "").lower()
            if any(w in txt for w in ["em ơi", "cô ơi", "chị ơi", "bà ơi", "vợ ơi"]):
                s["speaker"] = "male"
            elif any(w in txt for w in ["anh ơi", "chú ơi", "bác ơi", "chồng ơi"]):
                s["speaker"] = "female"
            else:
                s["speaker"] = "male"

    return segments

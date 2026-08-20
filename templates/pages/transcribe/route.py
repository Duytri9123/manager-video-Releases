"""Transcribe Blueprint — /api/transcribe, /api/extract_audio routes."""
import os
import tempfile
import shutil
import json as _j
import re
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context

bp = Blueprint("transcribe", __name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ass_time_to_srt(t: str) -> str:
    """Convert ASS timestamp (h:mm:ss.cs) to SRT format (hh:mm:ss,mmm)."""
    m = re.match(r"\s*(\d+):(\d+):(\d+)(?:\.(\d+))?\s*", str(t or ""))
    if not m:
        return "00:00:00,000"
    h = int(m.group(1))
    mm = int(m.group(2))
    ss = int(m.group(3))
    cs_raw = (m.group(4) or "0")[:2].ljust(2, "0")
    ms = int(cs_raw) * 10
    return f"{h:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _strip_ass_tags(text: str) -> str:
    txt = str(text or "")
    txt = re.sub(r"\{[^}]*\}", "", txt)
    txt = txt.replace(r"\N", "\n").replace(r"\n", "\n")
    return txt.strip()


def _convert_ass_to_outputs(ass_file: Path, out_dir: str | None, export_srt: bool):
    ass_file = Path(ass_file)
    if not ass_file.exists():
        return False, f"ASS file not found: {ass_file}"

    target_dir = Path(out_dir) if out_dir else ass_file.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = ass_file.stem
    txt_path = target_dir / f"{stem}.transcript.txt"
    srt_path = target_dir / f"{stem}.transcript.srt"

    raw = ass_file.read_text(encoding="utf-8", errors="replace")
    dialogues = []
    for line in raw.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        content = line[len("Dialogue:"):].lstrip()
        parts = content.split(",", 9)
        if len(parts) < 10:
            continue
        start = _ass_time_to_srt(parts[1])
        end = _ass_time_to_srt(parts[2])
        text = _strip_ass_tags(parts[9])
        if text:
            dialogues.append((start, end, text))

    if not dialogues:
        return False, "ASS has no dialogue lines"

    txt_path.write_text("\n".join([d[2] for d in dialogues]), encoding="utf-8")
    if export_srt:
        srt_blocks = []
        for i, (start, end, text) in enumerate(dialogues, 1):
            srt_blocks.append(f"{i}\n{start} --> {end}\n{text}\n")
        srt_path.write_text("\n".join(srt_blocks), encoding="utf-8")

    return True, f"{txt_path.name}" + (f" + {srt_path.name}" if export_srt else "")


def _find_videos(folder: str, skip_existing: bool = True, output_dir: str | None = None) -> list[Path]:
    """Recursively scan folder for video files. Optionally skip files that
    already have a `.transcript.txt` next to them (or in output_dir)."""
    base = Path(folder).expanduser()
    if not base.exists() or not base.is_dir():
        return []

    out_root = Path(output_dir).expanduser() if output_dir else None
    if out_root:
        out_root.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in _VIDEO_EXTS:
            continue
        if skip_existing:
            target_dir = out_root if out_root else p.parent
            if (target_dir / f"{p.stem}.transcript.txt").exists():
                continue
        results.append(p)
    return results


def _resolve_groq_credentials(data: dict) -> tuple[str, str, int]:
    """Resolve Groq API key/model/max_mb from request → env → config.yml."""
    from core.video_processor import _GROQ_MODEL, _GROQ_MAX_MB

    api_key = str(data.get("groq_api_key") or "").strip()
    if not api_key:
        api_key = os.getenv("GROQ_API_KEY", "").strip()

    model = str(data.get("groq_model") or "").strip()
    max_mb_raw = data.get("groq_max_mb")

    if not api_key or not model or max_mb_raw in (None, ""):
        # Fallback to config.yml (transcript / translation sections)
        try:
            import yaml as _yaml
            cfg_file = Path(__file__).parent.parent / "config.yml"
            if cfg_file.exists():
                cfg_raw = _yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
                tr_cfg = cfg_raw.get("transcript") or {}
                trans_cfg = cfg_raw.get("translation") or {}
                if not api_key:
                    api_key = (
                        str(tr_cfg.get("groq_api_key") or "").strip()
                        or str(trans_cfg.get("groq_key") or "").strip()
                    )
                if not model:
                    model = str(tr_cfg.get("groq_model") or "").strip()
                if max_mb_raw in (None, ""):
                    max_mb_raw = tr_cfg.get("groq_max_mb")
        except Exception:
            pass

    if not model:
        model = _GROQ_MODEL
    try:
        max_mb = int(max_mb_raw) if max_mb_raw not in (None, "") else _GROQ_MAX_MB
    except Exception:
        max_mb = _GROQ_MAX_MB

    return api_key, model, max_mb


def _write_outputs(segments: list[dict], video_path: Path, out_dir: Path,
                   export_srt: bool, converter=None) -> tuple[Path, Path | None]:
    """Write segments to .transcript.txt (and optionally .transcript.srt)."""
    from core.video_processor import _fmt_srt_time, _safe_stem

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(video_path.stem)
    txt_path = out_dir / f"{stem}.transcript.txt"
    srt_path = out_dir / f"{stem}.transcript.srt" if export_srt else None

    lines_txt = []
    srt_blocks = []
    for i, seg in enumerate(segments, 1):
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        if converter is not None:
            try:
                text = converter.convert(text)
            except Exception:
                pass
        lines_txt.append(text)
        if srt_path:
            start = _fmt_srt_time(float(seg.get("start") or 0.0))
            end = _fmt_srt_time(float(seg.get("end") or 0.0))
            srt_blocks.append(f"{i}\n{start} --> {end}\n{text}\n")

    txt_path.write_text("\n".join(lines_txt), encoding="utf-8")
    if srt_path:
        srt_path.write_text("\n".join(srt_blocks), encoding="utf-8")
    return txt_path, srt_path


class AntigravityTranscriber:
    """Speech-to-text via Antigravity provider connection with multi-key and model fallbacks."""

    def __init__(self, api_key: str = "", language: str = "zh", model_name: str = ""):
        self.api_key = (api_key or "").strip()
        self.language = language
        m = (model_name or "").strip()
        if m in ["tiny", "base", "small", "medium", "large", "auto", "model", "none"]:
            m = ""
        self.model_name = m

    def transcribe(self, video_path: Path, ffmpeg_bin: str, tmp_srt_path: Path | None = None) -> list[dict]:
        import subprocess, base64, urllib.request, urllib.error, json, os, re
        video_path = Path(video_path)
        temp_audio = video_path.parent / f"{video_path.stem}_temp_stt.mp3"
        try:
            candidates_keys = []
            if self.api_key:
                candidates_keys.append({"key": self.api_key, "base_url": ""})

            try:
                from templates.pages.config.route import load_providers_from_db
                all_provs = load_providers_from_db()
                p_data = all_provs.get("antigravity") or all_provs.get("gemini") or {}
                conns = [c for c in p_data.get("connections", []) if c.get("enabled")] or p_data.get("connections", [])
                for conn in conns:
                    k = (conn.get("api_key") or "").strip()
                    b = (conn.get("base_url") or "").strip()
                    if k and not any(ck["key"] == k for ck in candidates_keys):
                        candidates_keys.append({"key": k, "base_url": b})
            except Exception:
                pass

            env_key = os.getenv("ANTIGRAVITY_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
            if env_key and not any(ck["key"] == env_key for ck in candidates_keys):
                candidates_keys.append({"key": env_key, "base_url": ""})

            if not candidates_keys:
                from core.video_processor import FasterWhisperTranscriber
                fw = FasterWhisperTranscriber(model_name="base", language=self.language, use_vad=True)
                segs = []
                for step in fw.transcribe(video_path, ffmpeg_bin, tmp_srt_path or (video_path.parent / f"{video_path.stem}.srt")):
                    if isinstance(step, tuple) and step[0] == "result":
                        segs = step[1]
                return segs

            cmd = [ffmpeg_bin, "-y", "-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", str(temp_audio)]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            audio_bytes = temp_audio.read_bytes()
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")

            lang_names = {"zh": "Tiếng Trung", "en": "Tiếng Anh", "vi": "Tiếng Việt", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn", "th": "Tiếng Thái"}
            target_lang = lang_names.get(self.language, self.language)

            prompt = (
                f"Hãy nghe âm thanh và phiên âm toàn bộ lời nói sang {target_lang}.\n"
                "QUY TẮC MỐC THỜI GIAN SRT:\n"
                "- BẮT BUỘC định dạng SRT chuẩn: 00:MM:SS,mmm --> 00:MM:SS,mmm (Giờ:Phút:Giây,Miligiây).\n"
                "- Ví dụ: 5 giây đầu là 00:00:00,000 --> 00:00:05,000. 1 phút 12 giây là 00:01:12,000 --> 00:01:15,000 (TUYỆT ĐỐI KHÔNG viết thành 01:12:00,000).\n"
                "- Thời gian bắt đầu luôn nhỏ hơn thời gian kết thúc, các mốc thời gian tăng dần liên tục theo video.\n"
                "- Chỉ xuất ra nội dung khối SRT hoàn chỉnh, không thêm bất kỳ văn bản chào hỏi hay giải thích nào khác."
            )

            models_to_try = []
            if self.model_name:
                models_to_try.append(self.model_name)

            try:
                from templates.pages.config.route import load_models_from_db
                db_models = load_models_from_db("antigravity").get("antigravity", [])
                for dm in db_models:
                    if dm.get("enabled") and dm.get("id") and dm.get("id") not in models_to_try:
                        models_to_try.append(dm.get("id"))
            except Exception:
                pass

            for m_fallback in ["gemini-3.6-flash", "gemini-3.6-flash-medium", "gemini-3-flash-agent", "gemini-3.5-flash-medium", "gemini-pro-agent"]:
                if m_fallback not in models_to_try:
                    models_to_try.append(m_fallback)

            seen_models = set()
            models_to_try = [m for m in models_to_try if m and not (m in seen_models or seen_models.add(m))]

            srt_text = ""
            for conn_item in candidates_keys:
                k = conn_item["key"]
                b_url = conn_item["base_url"]
                base_endpoint = (b_url or "https://generativelanguage.googleapis.com").rstrip("/")

                for model in models_to_try:
                    if k.startswith("AIza"):
                        url = f"{base_endpoint}/v1beta/models/{model}:generateContent?key={k}"
                        headers = {"Content-Type": "application/json"}
                    else:
                        url = f"{base_endpoint}/v1beta/models/{model}:generateContent"
                        headers = {
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {k}"
                        }

                    payload = json.dumps({
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {"mime_type": "audio/mp3", "data": b64_audio}}
                            ]
                        }]
                    }).encode("utf-8")

                    try:
                        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                        with urllib.request.urlopen(req, timeout=40) as resp:
                            r_json = json.loads(resp.read().decode("utf-8"))
                            candidates = r_json.get("candidates") or []
                            if candidates and "content" in candidates[0]:
                                parts = candidates[0]["content"].get("parts") or []
                                if parts and "text" in parts[0]:
                                    srt_text = parts[0]["text"]
                                    if srt_text:
                                        break
                    except urllib.error.HTTPError as he:
                        if he.code in (401, 403):
                            break
                    except Exception:
                        pass

                if srt_text:
                    break

            if srt_text:
                return _parse_srt_to_segments(srt_text)
            return []
        except Exception as e:
            print("[AntigravityTranscriber] Error:", e)
            return []
        finally:
            if temp_audio.exists():
                try: temp_audio.unlink()
                except Exception: pass


def _parse_srt_to_segments(srt_text: str, video_dur: float | None = None) -> list[dict]:
    import re
    if not srt_text:
        return []
    srt_text = re.sub(r"^```[a-zA-Z]*\n?", "", srt_text.strip(), flags=re.MULTILINE)
    srt_text = re.sub(r"```$", "", srt_text.strip())

    try:
        from core.video_processor import _parse_time_smart
    except Exception:
        def _parse_time_smart(t_str, video_dur=None):
            t_str = str(t_str or "").strip().replace(",", ".")
            parts = t_str.split(":")
            if len(parts) == 3:
                return float(parts[0])*3600.0 + float(parts[1])*60.0 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0])*60.0 + float(parts[1])
            return 0.0

    segments = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        time_idx = -1
        for idx, line in enumerate(lines):
            if "-->" in line:
                time_idx = idx
                break
        if time_idx != -1 and time_idx + 1 < len(lines):
            time_line = lines[time_idx]
            parts = time_line.split("-->")
            if len(parts) == 2:
                try:
                    start_sec = _parse_time_smart(parts[0], video_dur=video_dur)
                    end_sec = _parse_time_smart(parts[1], video_dur=video_dur)
                    text = " ".join(lines[time_idx + 1:]).strip()
                    if text:
                        if end_sec <= start_sec:
                            dur_est = max(1.8, min(7.0, len(text) * 0.22))
                            end_sec = start_sec + dur_est
                        segments.append({"start": round(start_sec, 3), "end": round(end_sec, 3), "text": text})
                except Exception:
                    pass

    segments.sort(key=lambda s: s["start"])
    for i in range(len(segments)):
        if i + 1 < len(segments):
            next_start = segments[i + 1]["start"]
            if segments[i]["end"] > next_start and next_start > segments[i]["start"]:
                segments[i]["end"] = max(segments[i]["start"] + 1.0, next_start - 0.05)
    return segments


# ─────────────────────────────────────────────────────────────────────────────
# /api/transcribe
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/api/transcribe", methods=["POST"])
def transcribe():
    data: dict = {}
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        data.update(request.get_json(silent=True) or {})

    uploaded_tmp_dir = None
    uploaded_file = request.files.get("video_file") if request.files else None
    if uploaded_file and uploaded_file.filename:
        from utils.validators import sanitize_filename
        uploaded_tmp_dir = Path(tempfile.mkdtemp(prefix="tr_upload_"))
        original_name = Path(uploaded_file.filename).name
        safe_name = sanitize_filename(Path(original_name).stem) + Path(original_name).suffix
        saved_path = uploaded_tmp_dir / safe_name
        uploaded_file.save(saved_path)
        data["single"] = str(saved_path)
        data["_uploaded"] = True

    def generate():
        from core.video_processor import (
            find_ffmpeg,
            GroqWhisperTranscriber,
            FasterWhisperTranscriber,
        )

        def as_bool(value, default=False):
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            txt = str(value).strip().lower()
            if txt in ("1", "true", "yes", "on"):
                return True
            if txt in ("0", "false", "no", "off", ""):
                return False
            return default

        def send(**kw):
            return _j.dumps(kw, ensure_ascii=False) + "\n"

        try:
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                yield send(log="✗ Không tìm thấy ffmpeg trên hệ thống", level="error")
                return

            converter = None
            if as_bool(data.get("sc"), False):
                try:
                    from opencc import OpenCC
                    converter = OpenCC("t2s")
                except ImportError:
                    yield send(log="⚠ OpenCC chưa cài, bỏ qua chuyển phồn → giản", level="warning")

            single = (data.get("single") or "").strip()
            out_dir_raw = (data.get("out_dir") or "").strip() or None
            export_srt = as_bool(data.get("srt"), False)
            language = str(data.get("lang") or "zh").strip() or "zh"
            model_name = str(data.get("model") or "base").strip() or "base"
            provider = str(data.get("provider") or "antigravity").strip().lower()
            if provider not in ("antigravity", "gemini", "groq", "model"):
                provider = "antigravity"

            if single and not data.get("_uploaded"):
                sp = Path(single).expanduser()
                if not sp.exists():
                    folder_root = Path((data.get("folder") or "./Downloaded")).expanduser()
                    candidates = []
                    candidate = folder_root / single
                    if candidate.exists():
                        candidates.append(candidate)
                    else:
                        try:
                            for p in folder_root.rglob(Path(single).name):
                                if p.is_file():
                                    candidates.append(p)
                                    break
                        except Exception:
                            pass
                    if candidates:
                        single = str(candidates[0])
                        yield send(
                            log=f"ℹ Tự động resolve thành: {candidates[0]}",
                            level="info",
                        )
                    else:
                        yield send(
                            log=(f"✗ File không tồn tại: {single}\n"
                                 f"   Gợi ý: nhấn nút 📂 Chọn để upload, "
                                 f"hoặc nhập đường dẫn đầy đủ."),
                            level="error",
                        )
                        return

            if single and Path(single).suffix.lower() == ".ass":
                yield send(log=f"ℹ Import ASS: {Path(single).name}", level="info")
                yield send(overall=25, overall_lbl="Đang đọc ASS...", file=30, file_lbl="reading")
                ok, info = _convert_ass_to_outputs(Path(single), out_dir_raw, export_srt)
                if ok:
                    yield send(log=f"✓ Đã convert ASS: {info}", level="success")
                    yield send(overall=100, overall_lbl="Hoàn tất", file=100, file_lbl="done")
                else:
                    yield send(log=f"✗ {info}", level="error")
                return

            # ── Build transcriber ──
            if provider == "antigravity" or provider == "gemini":
                from templates.pages.config.route import load_providers_from_db
                all_provs = load_providers_from_db()
                ag_data = all_provs.get("antigravity") or {}
                ag_conns = [c for c in ag_data.get("connections", []) if c.get("enabled")] or ag_data.get("connections", [])
                ag_key = ag_conns[0].get("api_key", "").strip() if ag_conns else ""
                yield send(log=f"ℹ Dùng Antigravity Multimodal AI (Model: {model_name})", level="info")
                transcriber = AntigravityTranscriber(api_key=ag_key, language=language, model_name=model_name)
            elif provider == "model":
                yield send(log=f"ℹ Đang load Whisper local: {model_name}…", level="info")
                try:
                    transcriber = FasterWhisperTranscriber(model_name, language, use_vad=True)
                except ImportError:
                    yield send(log="✗ Cần cài đặt: pip install faster-whisper", level="error")
                    return
                yield send(log=f"✓ Đã load model {model_name}", level="success")
            else:
                api_key, groq_model, groq_max_mb = _resolve_groq_credentials(data)
                if not api_key:
                    yield send(
                        log="✗ Thiếu Groq API Key. Mở trang Cấu hình → nhập Groq API Key.",
                        level="error",
                    )
                    return
                yield send(log=f"ℹ Dùng Groq Whisper API (model: {groq_model})", level="info")
                transcriber = GroqWhisperTranscriber(
                    language=language,
                    api_key=api_key,
                    model=groq_model,
                    max_mb=groq_max_mb,
                )

            # ── Tập hợp danh sách video ──
            if single:
                videos = [Path(single)]
            else:
                videos = _find_videos(
                    data.get("folder", "./Downloaded"),
                    skip_existing=as_bool(data.get("skip"), True),
                    output_dir=out_dir_raw,
                )

            if not videos:
                yield send(log="⚠ Không tìm thấy video nào để xử lý", level="warning")
                return

            yield send(log=f"ℹ Tìm thấy {len(videos)} video", level="info")

            ok_c = fail_c = 0
            total = len(videos)
            for i, v in enumerate(videos, 1):
                if not v.exists():
                    fail_c += 1
                    yield send(log=f"✗ Không tồn tại: {v}", level="error")
                    continue

                yield send(log=f"▶ [{i}/{total}] {v.name}", level="url")
                yield send(
                    overall=int((i - 1) / total * 100),
                    overall_lbl=f"{i - 1}/{total}",
                    file=10, file_lbl="đang trích xuất audio…",
                )
                try:
                    if out_dir_raw:
                        target_dir = Path(out_dir_raw).expanduser()
                    else:
                        temp_root = Path(tempfile.gettempdir()).resolve()
                        is_in_temp = False
                        try:
                            is_in_temp = temp_root in v.resolve().parents
                        except Exception:
                            pass
                        if is_in_temp:
                            target_dir = Path(data.get("folder") or "./Downloaded").expanduser()
                        else:
                            target_dir = v.parent
                    tmp_srt = target_dir / f"{v.stem}.srt"
                    target_dir.mkdir(parents=True, exist_ok=True)

                    yield send(file=40, file_lbl="đang phiên âm…")
                    segments = transcriber.transcribe(v, ffmpeg, tmp_srt)
                    if not segments:
                        fail_c += 1
                        yield send(log="⚠ Không phát hiện giọng nói", level="warning")
                    else:
                        yield send(file=80, file_lbl="đang ghi file…")
                        txt_path, srt_path = _write_outputs(
                            segments, v, target_dir, export_srt, converter
                        )
                        # Cleanup .srt trung gian nếu user không yêu cầu xuất srt
                        try:
                            if not export_srt and tmp_srt.exists() and tmp_srt != srt_path:
                                tmp_srt.unlink()
                        except Exception:
                            pass
                        ok_c += 1
                        msg = f"✓ Đã ghi: {txt_path.name}"
                        if srt_path:
                            msg += f" + {srt_path.name}"
                        yield send(log=msg, level="success")
                except Exception as e:
                    fail_c += 1
                    yield send(log=f"✗ {e}", level="error")
                yield send(
                    overall=int(i / total * 100),
                    overall_lbl=f"{i}/{total}",
                    file=100, file_lbl="done",
                )

            yield send(log=f"Hoàn tất: ✓{ok_c} ✗{fail_c}", level="result")
            yield send(overall=100, overall_lbl="Hoàn tất", file=100, file_lbl="done")
        except Exception as e:
            yield send(log=f"✗ Lỗi nghiêm trọng: {e}", level="error")
        finally:
            if uploaded_tmp_dir:
                shutil.rmtree(str(uploaded_tmp_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


# ─────────────────────────────────────────────────────────────────────────────
# /api/extract_audio
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/api/extract_audio", methods=["POST"])
def extract_audio():
    data = {}
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        data.update(request.get_json(silent=True) or {})

    uploaded_file = request.files.get("video_file") if request.files else None
    uploaded_tmp_dir = None
    if uploaded_file and uploaded_file.filename:
        from utils.validators import sanitize_filename
        uploaded_tmp_dir = Path(tempfile.mkdtemp(prefix="ea_upload_"))
        original_name = Path(uploaded_file.filename).name
        safe_name = sanitize_filename(Path(original_name).stem) + Path(original_name).suffix
        saved_path = uploaded_tmp_dir / safe_name
        uploaded_file.save(saved_path)
        data["video_path"] = str(saved_path)

    from core.video_processor import find_ffmpeg
    import subprocess

    try:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return jsonify({"ok": False, "error": "ffmpeg not found"}), 400

        audio_fmt = str(data.get("format") or data.get("audio_fmt") or "mp3").strip().lower()
        video_path = str(data.get("video_path") or "").strip()
        if not video_path:
            return jsonify({"ok": False, "error": "Vui lòng chọn file video"}), 400

        vp_obj = Path(video_path).expanduser()
        if not vp_obj.exists():
            # Thử resolve trong ./Downloaded/
            folder_root = Path("./Downloaded").expanduser()
            candidate = folder_root / video_path
            if candidate.exists():
                vp_obj = candidate
            else:
                # rglob theo basename
                found = None
                try:
                    for p in folder_root.rglob(Path(video_path).name):
                        if p.is_file():
                            found = p
                            break
                except Exception:
                    found = None
                if found:
                    vp_obj = found
                else:
                    return jsonify({
                        "ok": False,
                        "error": (f"Không tìm thấy file: {video_path}. "
                                  "Hãy nhấn 📂 Chọn để upload, hoặc nhập đường dẫn đầy đủ.")
                    }), 400

        vp = vp_obj
        out_dir_str = str(data.get("output_dir") or data.get("out_dir") or "").strip()
        temp_root = Path(tempfile.gettempdir()).resolve()

        if out_dir_str:
            out_dir = Path(out_dir_str).expanduser()
        else:
            is_in_temp = False
            try:
                is_in_temp = temp_root in vp.resolve().parents
            except Exception:
                pass
            if is_in_temp:
                from core_app import load_cfg
                cfg = load_cfg() or {}
                out_dir_cfg = cfg.get("output_dir") or cfg.get("download_path") or "./Downloaded"
                out_dir = Path(out_dir_cfg).expanduser()
            else:
                out_dir = vp.parent

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{vp.stem}_audio.{audio_fmt}"

        cmd = [ffmpeg, "-y", "-i", str(vp)]
        if audio_fmt == "mp3":
            cmd += ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]
        elif audio_fmt == "wav":
            cmd += ["-vn", "-c:a", "pcm_s16le"]
        elif audio_fmt == "aac":
            cmd += ["-vn", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-vn"]
        cmd += [str(out_path), "-loglevel", "error"]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return jsonify({"ok": False, "error": f"ffmpeg error: {result.stderr}"}), 500

        return jsonify({"ok": True, "output_path": str(out_path)})
    finally:
        if uploaded_tmp_dir:
            shutil.rmtree(str(uploaded_tmp_dir), ignore_errors=True)

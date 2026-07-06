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
        # File đã upload → ưu tiên path thật, ignore "single" do FE gửi
        # (FE có thể chỉ gửi tên file từ <input type=file>).
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

            # OpenCC chuyển phồn → giản (tùy chọn)
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
            provider = str(data.get("provider") or "groq").strip().lower()
            if provider not in ("groq", "model"):
                provider = "groq"

            # ── Nếu user gõ tay path mà không tồn tại, thử resolve trong
            #    ./Downloaded/ (nhiều người chỉ paste tên file). Skip cho
            #    file đã upload (đã là tmp path tuyệt đối).
            if single and not data.get("_uploaded"):
                sp = Path(single).expanduser()
                if not sp.exists():
                    folder_root = Path((data.get("folder") or "./Downloaded")).expanduser()
                    candidates = []
                    candidate = folder_root / single
                    if candidate.exists():
                        candidates.append(candidate)
                    else:
                        # rglob theo basename
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

            # ── Trường hợp đặc biệt: file .ass → chỉ convert ra txt/srt ──
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
            if provider == "model":
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
                        log="✗ Thiếu Groq API Key. Mở trang Cấu hình → nhập Groq API Key, "
                            "hoặc set biến môi trường GROQ_API_KEY.",
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
                    target_dir = Path(out_dir_raw).expanduser() if out_dir_raw else v.parent
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
        out_dir = Path(out_dir_str) if out_dir_str else vp.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        audio_fmt = str(data.get("format") or "mp3").strip().lower()
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

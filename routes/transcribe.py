"""Transcribe Blueprint — /api/transcribe, /api/extract_audio routes."""
import tempfile
import shutil
import json as _j
import re
from pathlib import Path
from flask import Blueprint, jsonify, request, Response
from flask import stream_with_context

bp = Blueprint("transcribe", __name__)


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


@bp.route("/api/transcribe", methods=["POST"])
def transcribe():
    data = {}
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

    def generate():
        from core.video_processor import find_ffmpeg, find_videos, transcribe_file

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
            return _j.dumps(kw) + "\n"

        try:
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                yield send(log="✗ ffmpeg not found", level="error")
                return
            try:
                import whisper
            except ImportError:
                yield send(log="✗ pip install openai-whisper", level="error")
                return

            converter = None
            if as_bool(data.get("sc"), False):
                try:
                    from opencc import OpenCC
                    converter = OpenCC("t2s")
                except ImportError:
                    yield send(log="⚠ OpenCC not installed", level="warning")

            single = (data.get("single") or "").strip()
            out_dir = (data.get("out_dir") or "").strip() or None
            export_srt = as_bool(data.get("srt"), False)

            if single and Path(single).suffix.lower() == ".ass":
                yield send(log=f"ℹ Import ASS: {Path(single).name}", level="info")
                yield send(overall=25, overall_lbl="Parsing ASS...", file=30, file_lbl="reading")
                ok, info = _convert_ass_to_outputs(Path(single), out_dir, export_srt)
                if ok:
                    yield send(log=f"✓ Converted ASS: {info}", level="success")
                    yield send(overall=100, overall_lbl="完成", file=100, file_lbl="done")
                else:
                    yield send(log=f"✗ {info}", level="error")
                return

            model_name = data.get("model", "base")
            yield send(log=f"ℹ Loading model: {model_name}…")
            model = whisper.load_model(model_name)
            yield send(log=f"✓ Model {model_name} loaded", level="success")

            videos = [Path(single)] if single else find_videos(
                data.get("folder", "./Downloaded"),
                skip_existing=as_bool(data.get("skip"), True),
                output_dir=out_dir,
            )

            if not videos:
                yield send(log="⚠ No videos found", level="warning")
                return

            yield send(log=f"ℹ Found {len(videos)} video(s)")
            fmts = {"txt"}
            if export_srt:
                fmts.add("srt")
            ok_c = fail_c = 0

            for i, v in enumerate(videos, 1):
                yield send(log=f"▶ [{i}/{len(videos)}] {v.name}", level="url")
                yield send(
                    overall=int((i - 1) / len(videos) * 100),
                    overall_lbl=f"{i - 1}/{len(videos)}",
                    file=0, file_lbl="extracting…",
                )
                try:
                    ok = transcribe_file(v, model, ffmpeg, fmts, data.get("lang", "zh"), converter, out_dir)
                    if ok:
                        ok_c += 1
                        yield send(log="✓ Done", level="success")
                    else:
                        fail_c += 1
                        yield send(log="✗ Failed", level="error")
                except Exception as e:
                    fail_c += 1
                    yield send(log=f"✗ {e}", level="error")
                yield send(
                    overall=int(i / len(videos) * 100),
                    overall_lbl=f"{i}/{len(videos)}",
                    file=100, file_lbl="done",
                )

            yield send(log=f"完成: ✓{ok_c} ✗{fail_c}", level="result")
            yield send(overall=100, overall_lbl="完成", file=100, file_lbl="done")
        except Exception as e:
            yield send(log=f"✗ Fatal: {e}", level="error")
        finally:
            if uploaded_tmp_dir:
                shutil.rmtree(str(uploaded_tmp_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")


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

    def generate():
        from core.video_processor import find_ffmpeg
        import subprocess

        def send(**kw):
            return _j.dumps(kw) + "\n"

        try:
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                yield send(log="✗ ffmpeg not found", level="error")
                return

            video_path = str(data.get("video_path") or "").strip()
            if not video_path or not Path(video_path).exists():
                yield send(log="✗ Video file not found", level="error")
                return

            vp = Path(video_path)
            out_dir_str = str(data.get("out_dir") or "").strip()
            out_dir = Path(out_dir_str) if out_dir_str else vp.parent
            out_dir.mkdir(parents=True, exist_ok=True)

            audio_fmt = str(data.get("format") or "mp3").strip().lower()
            out_path = out_dir / f"{vp.stem}_audio.{audio_fmt}"

            yield send(log=f"ℹ Extracting audio from: {vp.name}", level="info", overall=10)

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
                yield send(log=f"✗ ffmpeg error: {result.stderr}", level="error")
                return

            yield send(
                log=f"✓ Audio extracted: {out_path.name}",
                level="success",
                overall=100,
                output_path=str(out_path),
            )
        except Exception as e:
            yield send(log=f"✗ Fatal: {e}", level="error")
        finally:
            if uploaded_tmp_dir:
                shutil.rmtree(str(uploaded_tmp_dir), ignore_errors=True)

    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")

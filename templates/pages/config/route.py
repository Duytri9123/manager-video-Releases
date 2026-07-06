"""Config Blueprint — /api/config, /api/cookies, /api/parse_cookie,
/api/validate_cookie, /api/cookie_mode, /api/ngrok/status,
/api/auto_fetch_cookie, /api/upload-image, /api/browse-file routes."""
import asyncio
import threading
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request
from core_app import (
    load_cfg, save_cfg, _deep_merge_dict,
    _get_ngrok_settings, _start_ngrok_tunnel, _public_base_url,
    CONFIG_FILE, ROOT,
)
import core_app as _ca

bp = Blueprint("config", __name__)


# ── /api/config ───────────────────────────────────────────────────────────────
@bp.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_cfg())


@bp.route("/api/config", methods=["POST"])
def post_config():
    data = request.json or {}
    cfg = load_cfg()
    cfg = _deep_merge_dict(cfg, data)
    save_cfg(cfg)
    return jsonify({"ok": True})


# ── /api/ngrok/status ─────────────────────────────────────────────────────────
@bp.route("/api/ngrok/status", methods=["GET"])
def ngrok_status():
    host = "127.0.0.1"
    port = 8080
    settings = _get_ngrok_settings()
    if settings.get("enabled") and not _ca._NGROK_PUBLIC_URL:
        _start_ngrok_tunnel(port)
    public_url = _public_base_url(host, port)
    return jsonify({
        "ok": True,
        "enabled": bool(settings.get("enabled")),
        "public_url": public_url,
        "tunnel_active": bool(_ca._NGROK_PUBLIC_URL),
        "local_url": f"http://{host}:{port}",
        "tiktok_callback_url": f"{public_url}/api/tiktok/callback",
        "error": _ca._NGROK_ERROR,
    })


# ── /api/cookies ──────────────────────────────────────────────────────────────
@bp.route("/api/cookies", methods=["POST"])
def post_cookies():
    data = request.json or {}
    cfg = load_cfg()
    cfg["cookies"] = data
    save_cfg(cfg)
    return jsonify({"ok": True})


@bp.route("/api/parse_cookie", methods=["POST"])
def parse_cookie():
    raw = (request.json or {}).get("raw", "")
    from utils.cookie_utils import parse_cookie_header
    parsed = parse_cookie_header(raw)
    return jsonify(parsed)


@bp.route("/api/validate_cookie", methods=["POST"])
def validate_cookie():
    data = request.json or {}
    from auth import CookieManager
    cm = CookieManager()
    cm.set_cookies(data)
    ok = cm.validate_cookies()
    return jsonify({"ok": ok})


# ── /api/cookie_mode ──────────────────────────────────────────────────────────
@bp.route("/api/cookie_mode", methods=["GET"])
def get_cookie_mode():
    cfg = load_cfg()
    return jsonify({"mode": cfg.get("cookie_mode", "default")})


@bp.route("/api/cookie_mode", methods=["POST"])
def set_cookie_mode():
    mode = (request.json or {}).get("mode", "default")
    cfg = load_cfg()
    cfg["cookie_mode"] = mode
    save_cfg(cfg)
    return jsonify({"ok": True})


# ── /api/auto_fetch_cookie ────────────────────────────────────────────────────
@bp.route("/api/auto_fetch_cookie", methods=["POST"])
def auto_fetch_cookie():
    def run():
        import argparse
        from tools.cookie_fetcher import capture_cookies
        args = argparse.Namespace(
            url="https://www.douyin.com/", browser="chromium",
            headless=False, output=ROOT / "config" / "cookies.json",
            config=CONFIG_FILE, include_all=False,
        )
        asyncio.run(capture_cookies(args))
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


# ── /api/upload-image ─────────────────────────────────────────────────────────
@bp.route("/api/upload-image", methods=["POST"])
def upload_image():
    """Upload image for anti-fingerprint (overlay/logo)."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No file selected"}), 400

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp"}
    fname = file.filename.lower()
    if not any(fname.endswith(ext) for ext in allowed_ext):
        return jsonify({"ok": False, "error": "Only image files allowed (PNG, JPG, JPEG, WEBP)"}), 400

    try:
        from core_app import TEMP_UPLOADS_DIR
        upload_dir = TEMP_UPLOADS_DIR
        upload_dir.mkdir(exist_ok=True)

        ext = Path(file.filename).suffix
        new_filename = f"anti-fp-{uuid.uuid4().hex}{ext}"
        upload_path = upload_dir / new_filename
        file.save(str(upload_path))

        rel_path = f"temp_uploads/{new_filename}"
        return jsonify({"ok": True, "path": rel_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/browse-folder ────────────────────────────────────────────────────────
@bp.route("/api/browse-folder", methods=["POST"])
def browse_folder():
    import subprocess

    ps_script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$b.Description = 'Chọn thư mục lưu'; "
        "$b.ShowNewFolderButton = $true; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; $f.Width = 1; $f.Height = 1; "
        "$f.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; "
        "$f.Show(); $f.Activate(); "
        "$r = $b.ShowDialog($f); "
        "$f.Close(); "
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $b.SelectedPath }"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-Command", ps_script],
            capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        path = result.stdout.strip()
        return jsonify({"path": path})
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})


# ── /temp_uploads/<filename> ──────────────────────────────────────────────────
@bp.route("/temp_uploads/<path:filename>")
def serve_temp_uploads(filename):
    from flask import send_from_directory
    from core_app import TEMP_UPLOADS_DIR
    return send_from_directory(TEMP_UPLOADS_DIR, filename)


# ── /api/browse-file ──────────────────────────────────────────────────────────
@bp.route("/api/browse-file", methods=["POST"])
def browse_file():
    import subprocess

    data = request.get_json(silent=True) or {}
    file_filter = data.get("filter", "all")

    if file_filter == "image":
        filter_str = "Image files (*.png;*.jpg;*.jpeg;*.webp)|*.png;*.jpg;*.jpeg;*.webp|All files (*.*)|*.*"
    else:
        filter_str = "All files (*.*)|*.*"

    ps_script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$b = New-Object System.Windows.Forms.OpenFileDialog; "
        "$b.Title = 'Chọn file'; "
        "$b.Multiselect = $false; "
        f"$b.Filter = '{filter_str}'; "
        "$f = New-Object System.Windows.Forms.Form; "
        "$f.TopMost = $true; $f.Width = 1; $f.Height = 1; "
        "$f.WindowState = [System.Windows.Forms.FormWindowState]::Minimized; "
        "$f.Show(); $f.Activate(); "
        "$r = $b.ShowDialog($f); "
        "$f.Close(); "
        "if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $b.FileName }"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-Command", ps_script],
            capture_output=True, text=True, timeout=120, encoding="utf-8"
        )
        path = result.stdout.strip()
        return jsonify({"path": path})
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})

# ── /api/test_api_key ─────────────────────────────────────────────────────────
@bp.route("/api/test_api_key", methods=["POST"])
def test_api_key():
    data = request.json or {}
    provider = str(data.get("provider") or "").strip().lower()

    res = _test_api_key_impl()

    try:
        import json
        response_obj = res[0] if isinstance(res, tuple) else res
        res_data = response_obj.get_json()
        if res_data and isinstance(res_data, dict):
            ok = res_data.get("ok", False)
            error = res_data.get("error", "")

            state_dir = ROOT / ".state"
            state_dir.mkdir(parents=True, exist_ok=True)
            status_file = state_dir / "api_keys_status.json"

            status_data = {}
            if status_file.exists():
                try:
                    with open(status_file, "r", encoding="utf-8") as f:
                        status_data = json.load(f)
                except Exception:
                    pass
            status_data[provider] = {"ok": ok, "error": error}
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return res


def _test_api_key_impl():
    """Test an API key and return status + quota info where available."""
    import json as _json
    import urllib.request
    import urllib.error

    data = request.json or {}
    provider = str(data.get("provider") or "").strip().lower()
    key = str(data.get("key") or "").strip()

    if not key:
        return jsonify({"ok": False, "error": "Key trống"}), 400

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    if provider == "deepseek":
        try:
            payload = _json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            # Try to get balance
            balance_info = ""
            try:
                bal_req = urllib.request.Request(
                    "https://api.deepseek.com/user/balance",
                    headers={"Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(bal_req, timeout=8) as br:
                    bal = _json.loads(br.read())
                balances = bal.get("balance_infos") or []
                if balances:
                    b = balances[0]
                    balance_info = f"Balance: {b.get('total_balance', '?')} {b.get('currency', '')}"
            except Exception:
                pass
            return jsonify({"ok": True, "model": "deepseek-chat", "quota": balance_info or "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Groq (Whisper + LLM) ──────────────────────────────────────────────────
    elif provider == "groq":
        try:
            # Test bằng list models — nhẹ, không tốn quota, xác nhận key hợp lệ
            models_req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(models_req, timeout=10) as mr:
                models_data = _json.loads(mr.read())
            model_ids = [m.get("id", "") for m in models_data.get("data", [])]
            whisper_ok = any("whisper" in m for m in model_ids)
            llm_ok = any("llama" in m or "gemma" in m or "mixtral" in m for m in model_ids)
            whisper_models = [m for m in model_ids if "whisper" in m]
            parts = []
            parts.append(f"Whisper: {'✓ (' + whisper_models[0] + ')' if whisper_ok else '✗'}")
            parts.append(f"LLM: {'✓' if llm_ok else '✗'}")
            quota = " | ".join(parts)
            return jsonify({"ok": True, "model": whisper_models[0] if whisper_models else "N/A", "quota": quota})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── OpenAI ────────────────────────────────────────────────────────────────
    elif provider == "openai":
        try:
            payload = _json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            return jsonify({"ok": True, "model": "gpt-4o-mini", "quota": "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── HuggingFace ───────────────────────────────────────────────────────────
    elif provider == "huggingface":
        try:
            req = urllib.request.Request(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = _json.loads(r.read())
            name = resp.get("name") or resp.get("fullname") or "?"
            plan = (resp.get("plan") or {}).get("type") or "free"
            return jsonify({"ok": True, "model": name, "quota": f"Plan: {plan}"})
        except urllib.error.HTTPError as e:
            return jsonify({"ok": False, "error": f"HTTP {e.code}: Token không hợp lệ"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── FPT AI TTS ────────────────────────────────────────────────────────────
    elif provider == "fpt":
        try:
            import asyncio
            from core.video_processor import _tts_fpt_ai
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_fpt_ai("xin chào", "banmai", out, key, 0))
            if ok:
                return jsonify({"ok": True, "model": "banmai", "quota": "TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────
    elif provider == "elevenlabs":
        try:
            import asyncio
            from core.video_processor import _tts_elevenlabs, ELEVENLABS_DEFAULT_VOICE_ID
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_elevenlabs(
                    "hello", ELEVENLABS_DEFAULT_VOICE_ID, out, api_key=key
                ))
            if ok:
                return jsonify({"ok": True, "model": "eleven_multilingual_v2", "quota": "ElevenLabs TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Fish Audio TTS ────────────────────────────────────────────────────────
    elif provider == "fish-audio":
        try:
            import asyncio
            from core.video_processor import _tts_fish
            import tempfile
            from pathlib import Path as _Path
            with tempfile.TemporaryDirectory() as tmpdir:
                out = _Path(tmpdir) / "test.mp3"
                ok = asyncio.run(_tts_fish(
                    "Hello world", "", out, api_key=key, model="s2-pro"
                ))
            if ok:
                return jsonify({"ok": True, "model": "s2-pro", "quota": "Fish Audio TTS hoạt động"})
            return jsonify({"ok": False, "error": "TTS thất bại — kiểm tra key"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── 9Router (AI Gateway) ──────────────────────────────────────────────────
    elif provider == "9router":
        try:
            cfg = load_cfg()
            nr = cfg.get("nine_router", {})
            endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
            models_req = urllib.request.Request(
                f"{endpoint}/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(models_req, timeout=10) as mr:
                models_data = _json.loads(mr.read())
            model_ids = [m.get("id", "") for m in models_data.get("data", [])]
            return jsonify({"ok": True, "model": model_ids[0] if model_ids else "N/A", "quota": f"{len(model_ids)} models"})
        except urllib.error.HTTPError as e:
            return jsonify({"ok": False, "error": f"HTTP {e.code}: Không thể kết nối 9Router"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── Gemini (Video gen / Image gen) ───────────────────────────────────────
    elif provider == "gemini":
        try:
            payload = _json.dumps({
                "contents": [{"parts": [{"text": "hi"}]}],
            }).encode()
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
                data=payload, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = _json.loads(r.read())
            return jsonify({"ok": True, "model": "gemini-2.0-flash", "quota": "OK"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    # ── TMDb (Movie Review API) ─────────────────────────────────────────────
    elif provider == "tmdb":
        try:
            # Try Bearer token (v4) first
            req = urllib.request.Request(
                "https://api.themoviedb.org/3/movie/550?language=en-US",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    resp = _json.loads(r.read())
                title = resp.get("title", "?")
                return jsonify({"ok": True, "model": title, "quota": "TMDb API hoạt động (v4 token)"})
            except urllib.error.HTTPError:
                # Fallback to API key (v3)
                req2 = urllib.request.Request(
                    f"https://api.themoviedb.org/3/movie/550?api_key={key}&language=en-US",
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req2, timeout=10) as r:
                    resp = _json.loads(r.read())
                title = resp.get("title", "?")
                return jsonify({"ok": True, "model": title, "quota": "TMDb API hoạt động (v3 key)"})
        except urllib.error.HTTPError as e:
            body = ""
            try: body = _json.loads(e.read()).get("status_message", "")
            except Exception: pass
            return jsonify({"ok": False, "error": f"HTTP {e.code}: {body or e.reason}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    return jsonify({"ok": False, "error": f"Provider không hỗ trợ: {provider}"}), 400


# ── /api/upload_client_secrets ────────────────────────────────────────────────
@bp.route("/api/upload_client_secrets", methods=["POST"])
def upload_client_secrets():
    """Upload client_secrets.json for YouTube OAuth."""
    import json as _json
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file part"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No selected file"}), 400

    try:
        content = file.read()
        try:
            _json.loads(content)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Invalid JSON format: {e}"}), 400

        dest_path = ROOT / "client_secrets.json"
        with open(dest_path, "wb") as f:
            f.write(content)
        return jsonify({"ok": True, "message": "Đã tải lên client_secrets.json thành công!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

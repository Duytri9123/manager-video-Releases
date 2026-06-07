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
        upload_dir = ROOT / "temp_uploads"
        upload_dir.mkdir(exist_ok=True)

        ext = Path(file.filename).suffix
        new_filename = f"anti-fp-{uuid.uuid4().hex}{ext}"
        upload_path = upload_dir / new_filename
        file.save(str(upload_path))

        rel_path = f"temp_uploads/{new_filename}"
        return jsonify({"ok": True, "path": rel_path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── /api/browse-file ──────────────────────────────────────────────────────────
@bp.route("/api/browse-file", methods=["POST"])
def browse_file():
    import subprocess
    import sys
    import json as _json

    data = request.get_json(silent=True) or {}
    file_filter = data.get("filter", "all")
    filetypes_arg = "image" if file_filter == "image" else "all"

    script = """
import tkinter as tk
from tkinter import filedialog
import sys, json

ft = sys.argv[1] if len(sys.argv) > 1 else 'all'
root = tk.Tk()
root.withdraw()
root.lift()
root.attributes('-topmost', True)

if ft == 'image':
    filetypes = [('Image files', '*.png *.jpg *.jpeg *.webp'), ('All files', '*.*')]
else:
    filetypes = [('All files', '*.*')]

path = filedialog.askopenfilename(filetypes=filetypes)
root.destroy()
print(json.dumps({'path': path or ''}))
"""

    try:
        result = subprocess.run(
            [sys.executable, "-c", script, filetypes_arg],
            capture_output=True, text=True, timeout=120,
        )
        out = result.stdout.strip()
        data_out = _json.loads(out) if out else {"path": ""}
        return jsonify(data_out)
    except Exception as e:
        return jsonify({"path": "", "error": str(e)})

# ── /api/test_api_key ─────────────────────────────────────────────────────────
@bp.route("/api/test_api_key", methods=["POST"])
def test_api_key():
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

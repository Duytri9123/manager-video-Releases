#!/usr/bin/env python3
"""Douyin Downloader — Flask app factory + shared state.

Security-hardened:
  * SECRET_KEY pulled from FLASK_SECRET_KEY env or persisted random key.
  * CORS origins restricted (defaults to local-only; allow ngrok URL automatically).
  * No hardcoded API keys / cookies — fall back to user config only.
  * ngrok errors redacted to never leak the authtoken.
"""
import asyncio
import collections
import io
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request, send_file
from flask_socketio import SocketIO, emit

try:
    from pyngrok import ngrok
except Exception:
    ngrok = None

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
CONFIG_FILE = ROOT / "config.yml"
STATE_DIR = ROOT / ".state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOGGER = logging.getLogger("douyin-webui")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    LOGGER.addHandler(_h)

_NGROK_LOCK = threading.Lock()
_NGROK_PUBLIC_URL = ""
_NGROK_ERROR = ""

# ── Security helpers ─────────────────────────────────────────────────────────
from utils.security import load_or_create_app_secret, parse_origin_list, redact

SECRET_KEY = load_or_create_app_secret(STATE_DIR)


def _resolve_cors_origins(cfg: dict) -> list:
    """Build a CORS origins list from config (auth.cors_origins) + ngrok URL."""
    auth_cfg = (cfg or {}).get("auth") or {}
    raw = auth_cfg.get("cors_origins")
    origins = parse_origin_list(raw, default=[])
    if not origins:
        # Sensible defaults: local dev + LAN
        origins = [
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    if _NGROK_PUBLIC_URL and _NGROK_PUBLIC_URL not in origins and "*" not in origins:
        origins.append(_NGROK_PUBLIC_URL)
    public_cfg = ((cfg or {}).get("ngrok") or {}).get("public_url") or ""
    if public_cfg and public_cfg not in origins and "*" not in origins:
        origins.append(public_cfg)
    return origins


# ── Flask app + SocketIO ──────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["TEMPLATES_AUTO_RELOAD"] = True
# Reduced from 2 GB → 512 MB; raise via WEBAPP_MAX_UPLOAD_MB if needed
_max_upload_mb = int(os.getenv("WEBAPP_MAX_UPLOAD_MB", "512"))
app.config["MAX_CONTENT_LENGTH"] = _max_upload_mb * 1024 * 1024


def _initial_load_cfg():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


_initial_cfg = _initial_load_cfg()
_initial_origins = _resolve_cors_origins(_initial_cfg)

socketio = SocketIO(
    app,
    cors_allowed_origins=_initial_origins if _initial_origins != ["*"] else "*",
    async_mode="threading",
    ping_timeout=120,
    ping_interval=30,
)

# ── Download Queue globals ────────────────────────────────────────────────────
_dl_queue = collections.deque()
_queue_lock = threading.Lock()
_dl_running = False
_tr_running = False

# ── Shared dirs ──────────────────────────────────────────────────────────────
VOICES_DIR = ROOT / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_UPLOADS_DIR = ROOT / "temp_uploads"
TEMP_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ── Helper functions ──────────────────────────────────────────────────────────
def load_cfg():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_cfg(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


def _extract_cover(item: dict) -> str:
    """Try multiple fields to get the best cover URL."""
    video = item.get("video") or {}
    for field in ("dynamic_cover", "origin_cover", "cover"):
        ul = (video.get(field) or {}).get("url_list") or []
        if ul:
            return ul[0]
    imgs = item.get("images") or []
    if imgs:
        ul = (imgs[0].get("url_list") or [])
        if ul:
            return ul[0]
    return ""


def get_cookies_with_fallback():
    """Load cookies from config. Hard-coded cookies removed for security:
    user must configure their own cookies via the UI / `.cookies.json`."""
    try:
        cfg = load_cfg()
        ck = cfg.get("cookies") or {}
        # Also support cookies in a separate .cookies.json file (gitignored)
        cookies_file = ROOT / ".cookies.json"
        if (not ck) and cookies_file.exists():
            try:
                ck = json.loads(cookies_file.read_text(encoding="utf-8")) or {}
            except Exception:
                ck = {}
        required = {"ttwid", "odin_tt", "passport_csrf_token"}
        if required.issubset({k for k, v in ck.items() if v}):
            return ck
    except Exception:
        pass
    return {}


def _deep_merge_dict(base, updates):
    merged = dict(base or {})
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged.get(key), value)
        else:
            merged[key] = value
    return merged


_naming_title_cache = {}


def _resolve_naming_title(raw_title: str) -> str:
    raw_title = str(raw_title or "").strip()
    if not raw_title:
        return "video"

    cfg = load_cfg()
    tr_cfg = dict(cfg.get("translation") or {})
    if not tr_cfg.get("naming_enabled", False):
        return raw_title

    cache_key = (raw_title, tr_cfg.get("preferred_provider", "auto"))
    if cache_key in _naming_title_cache:
        return _naming_title_cache[cache_key]

    try:
        from utils.translation import translate_texts

        translated, _provider = translate_texts(
            [raw_title], tr_cfg, tr_cfg.get("preferred_provider", "auto")
        )
        resolved = (translated[0] if translated else "").strip() or raw_title
    except Exception:
        resolved = raw_title

    _naming_title_cache[cache_key] = resolved
    return resolved


# ── Ngrok functions ───────────────────────────────────────────────────────────
def _get_ngrok_settings():
    cfg = load_cfg()
    ngrok_cfg = dict(cfg.get("ngrok") or {})
    enabled = _as_bool(
        os.getenv("NGROK_ENABLED"),
        _as_bool(ngrok_cfg.get("enabled"), False),
    )
    return {
        "enabled": enabled,
        "authtoken": str(os.getenv("NGROK_AUTHTOKEN") or ngrok_cfg.get("authtoken") or "").strip(),
        "domain": str(os.getenv("NGROK_DOMAIN") or ngrok_cfg.get("domain") or "").strip(),
        "bind_tls": _as_bool(os.getenv("NGROK_BIND_TLS"), _as_bool(ngrok_cfg.get("bind_tls"), True)),
    }


def _save_ngrok_public_url(public_url: str):
    cfg = load_cfg()
    ngrok_cfg = dict(cfg.get("ngrok") or {})
    ngrok_cfg["public_url"] = public_url
    cfg["ngrok"] = ngrok_cfg
    save_cfg(cfg)


def _start_ngrok_tunnel(port: int):
    global _NGROK_PUBLIC_URL, _NGROK_ERROR
    settings = _get_ngrok_settings()
    if not settings.get("enabled"):
        return

    with _NGROK_LOCK:
        if _NGROK_PUBLIC_URL:
            return

        if ngrok is None:
            _NGROK_ERROR = "pyngrok is not installed. Run: pip install pyngrok"
            LOGGER.warning(_NGROK_ERROR)
            return

        if not settings["authtoken"]:
            _NGROK_ERROR = (
                "Ngrok requires a verified account and authtoken. "
                "Set ngrok.authtoken in config.yml or NGROK_AUTHTOKEN env."
            )
            LOGGER.warning(_NGROK_ERROR)
            return

        try:
            ngrok.set_auth_token(settings["authtoken"])

            options = {"addr": str(port), "bind_tls": settings["bind_tls"]}
            if settings["domain"]:
                options["domain"] = settings["domain"]

            tunnel = ngrok.connect(**options)
            _NGROK_PUBLIC_URL = str(getattr(tunnel, "public_url", "") or "").strip()
            if _NGROK_PUBLIC_URL:
                _NGROK_ERROR = ""
                _save_ngrok_public_url(_NGROK_PUBLIC_URL)
                LOGGER.info("Ngrok tunnel started: %s", _NGROK_PUBLIC_URL)
        except Exception as exc:
            _NGROK_ERROR = redact(str(exc), settings.get("authtoken") or "")
            LOGGER.error("Failed to start ngrok tunnel: %s", _NGROK_ERROR)


def _public_base_url(host: str, port: int) -> str:
    if _NGROK_PUBLIC_URL:
        return _NGROK_PUBLIC_URL
    cfg = load_cfg()
    fallback_url = str(((cfg.get("ngrok") or {}).get("public_url") or "")).strip()
    if fallback_url:
        return fallback_url
    return f"http://{host}:{port}"


# ── SocketIO progress shim ────────────────────────────────────────────────────
class SocketProgress:
    _STEPS = 6

    def __init__(self, sid):
        self._sid = sid
        self._step = 0
        self._item_done = 0
        self._item_total = 1
        self._url_i = 0
        self._url_n = 0
        self._url = ""
        self._stats = {"success": 0, "failed": 0, "skipped": 0}

    def _emit(self, event, data):
        socketio.emit(event, data, to=self._sid)

    def _log(self, msg, level="info"):
        self._emit("log", {"msg": msg, "level": level})

    def show_banner(self):         self._log("══ Douyin Downloader v2.0.0 ══", "banner")
    def print_info(self, m):       self._log(f"ℹ  {m}", "info")
    def print_success(self, m):    self._log(f"✓  {m}", "success")
    def print_warning(self, m):    self._log(f"⚠  {m}", "warning")
    def print_error(self, m):      self._log(f"✗  {m}", "error")

    def start_download_session(self, n):
        self._url_n = n
        self._emit("progress", {"type": "overall", "pct": 0, "label": f"0/{n} URL"})

    def stop_download_session(self):
        self._emit("progress", {"type": "overall", "pct": 100, "label": "完成"})

    def start_url(self, i, n, url):
        self._url_i = i
        self._url_n = n
        self._step = 0
        self._url = url
        self._item_done = 0
        self._item_total = 1
        self._stats = {"success": 0, "failed": 0, "skipped": 0}
        self._emit("progress", {"type": "step", "pct": 0, "label": f"[{i}/{n}] 待开始"})
        self._log(f"▶ [{i}/{n}] {url}", "url")

    def complete_url(self, result=None):
        self._emit("progress", {"type": "step", "pct": 100, "label": f"[{self._url_i}/{self._url_n}] 完成"})
        pct = int(self._url_i / max(self._url_n, 1) * 100)
        self._emit("progress", {"type": "overall", "pct": pct, "label": f"{self._url_i}/{self._url_n} URL"})
        if result:
            self._log(f"✓ 成功:{result.success} 失败:{result.failed} 跳过:{result.skipped}", "success")

    def fail_url(self, reason):
        self._emit("progress", {"type": "step", "pct": 100, "label": f"[{self._url_i}/{self._url_n}] 失败"})
        self._log(f"✗ {reason}", "error")

    def advance_step(self, step, detail=""):
        self._step = min(self._step + 1, self._STEPS)
        pct = int(self._step / self._STEPS * 100)
        self._emit("progress", {"type": "step", "pct": pct, "label": f"[{self._url_i}/{self._url_n}] {step}"})
        if detail:
            self._log(f"   → {step}: {detail}", "detail")

    def update_step(self, step, detail=""):
        pct = int(self._step / self._STEPS * 100)
        self._emit("progress", {"type": "step", "pct": pct, "label": f"[{self._url_i}/{self._url_n}] {step}"})
        if detail:
            self._log(f"   → {step}: {detail}", "detail")

    def set_item_total(self, total, detail=""):
        self._item_total = max(total, 1)
        self._item_done = 0
        self._stats = {"success": 0, "failed": 0, "skipped": 0}
        self._emit("progress", {"type": "item", "pct": 0, "label": f"作品 0/{total}", "url": self._url})
        if detail:
            self._log(f"   {detail}", "detail")

    def update_post_progress(self, pct, label=""):
        try:
            p = max(0, min(100, int(pct)))
        except Exception:
            p = 0
        self._emit("progress", {"type": "post", "pct": p, "label": label or "", "url": self._url})

    def advance_item(self, status, detail=""):
        if status in self._stats:
            self._stats[status] += 1
        self._item_done = min(self._item_done + 1, self._item_total)
        pct = int(self._item_done / self._item_total * 100)
        s = self._stats
        self._emit("progress", {"type": "item", "pct": pct,
            "label": f"作品 {self._item_done}/{self._item_total}  ✓{s['success']} ✗{s['failed']} -{s['skipped']}", "url": self._url})

    def show_result(self, result):
        self._log(f"{'─' * 44}", "result")
        self._log(f"总计:{result.total}  成功:{result.success}  失败:{result.failed}  跳过:{result.skipped}", "result")
        self._log(f"{'─' * 44}", "result")


# ── SPA render helper ─────────────────────────────────────────────────────────
def _render_spa(active_tab="user"):
    return render_template("spa_new.html", active=active_tab, jsv=int(time.time()))


# ── Whisper preload ───────────────────────────────────────────────────────────
def _preload_whisper_model():
    """Preload faster-whisper model in background so first video processes faster."""
    try:
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        cfg = load_cfg()
        model_name = (cfg.get("video_process") or {}).get("model", "base")
        from core.video_processor import _whisper_model_cache
        if model_name not in _whisper_model_cache:
            from faster_whisper import WhisperModel
            _whisper_model_cache[model_name] = WhisperModel(
                model_name, device="cpu", compute_type="int8"
            )
    except Exception as e:
        LOGGER.debug("Whisper preload skipped: %s", e)


# ── YouTube uploader singleton ────────────────────────────────────────────────
_youtube_uploader = None


def _get_youtube_uploader(account_id: str = None):
    global _youtube_uploader
    if account_id:
        from tools.youtube_uploader import YouTubeUploader
        return YouTubeUploader(client_secrets_file="client_secrets.json", account_id=account_id)
    if _youtube_uploader is None:
        from tools.youtube_uploader import YouTubeUploader
        _youtube_uploader = YouTubeUploader(client_secrets_file="client_secrets.json")
    return _youtube_uploader


def _reset_youtube_uploader():
    """Reset singleton so next call re-reads client_secrets.json."""
    global _youtube_uploader
    _youtube_uploader = None

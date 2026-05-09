#!/usr/bin/env python3
"""Douyin Downloader — Flask app factory + shared state"""
import asyncio, sys, time, threading, json, logging, io, os, re
import collections
from pathlib import Path
from datetime import datetime
import yaml
from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit

try:
    from pyngrok import ngrok
except Exception:
    ngrok = None

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
CONFIG_FILE = ROOT / "config.yml"
LOGGER = logging.getLogger("douyin-webui")

_NGROK_LOCK = threading.Lock()
_NGROK_PUBLIC_URL = ""
_NGROK_ERROR = ""

# ── default fallback cookies (not exposed to UI) ──────────────────────────────
_DEFAULT_COOKIES = {
    "ttwid": "1%7C0uxogqfezTrhN1YJ0i35KZv9fgo1yu6HYbmZuT-KVvw%7C1775052558%7C62485d542a14be7db9eb638974ae41e51276e62d045af80583fc7c123370707c",
    "odin_tt": "ded429e2000523eab758a3be8ab56d096d58a49e60bdbda955d2fe18d2cc4ba88289489964496c9f024646821417f688dcc9d23aa4ffb052321893beabe83d12b7af8feaf0409fb4786ae05783eea0ca",
    "passport_csrf_token": "60e588651b39d0a24d59e5981c4bf3ee",
    "s_v_web_id": "verify_mlml38zd_b7a50e45_9212_0298_a304_a911c914f42d",
    "__ac_nonce": "069cd375500a473596e",
    "__ac_signature": "_02B4Z6wo00f01dncC0AAAIDBu8IPB3sd.TnZ.A.AAB-87c",
    "UIFID": "164c22db5016193fd69c8bfb0b166ea3a563c2c88054b8eae8759946ea9753ce30fbd9414fde0e3bb8edf6ef3b15e498bb370dcbcae9f48ec0468161bb4bb9c7c36dd402b45c21a2c7c07bd0c8823022cb3eed3271b937879d8845056c80013921d8054aeb0756c78b55b25f5918e4171c63194f0ec22776be556fdf02d846f5b0688b4a38d7b0277ebc1c075101c71be9b1ec2c1d9249da5ff4be78f35b07ec79f57e0cafee3babb082d75b834e72a3",
    "bd_ticket_guard_client_web_domain": "2",
}

# ── Flask app + SocketIO ──────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "douyin-dl-secret"
app.config["TEMPLATES_AUTO_RELOAD"] = True
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    ping_timeout=120,       # wait 2 min before declaring client dead
    ping_interval=30,       # ping every 30s to keep connection alive
)

# ── Download Queue globals ────────────────────────────────────────────────────
_dl_queue   = collections.deque()
_queue_lock = threading.Lock()
_dl_running = False
_tr_running = False

# ── VOICES_DIR ────────────────────────────────────────────────────────────────
VOICES_DIR = ROOT / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

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
    # gallery / image post
    imgs = item.get("images") or []
    if imgs:
        ul = (imgs[0].get("url_list") or [])
        if ul:
            return ul[0]
    return ""


def get_cookies_with_fallback():
    """Load cookies from config, fallback to default if missing or incomplete."""
    try:
        cfg = load_cfg()
        if cfg.get("cookie_mode", "default") == "default":
            return _DEFAULT_COOKIES
        ck = cfg.get("cookies") or {}
        required = {"ttwid", "odin_tt", "passport_csrf_token"}
        if required.issubset({k for k, v in ck.items() if v}):
            return ck
    except Exception:
        pass
    return _DEFAULT_COOKIES


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

        translated, _provider = translate_texts([raw_title], tr_cfg, tr_cfg.get("preferred_provider", "auto"))
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
            if settings["authtoken"]:
                ngrok.set_auth_token(settings["authtoken"])

            options = {
                "addr": str(port),
                "bind_tls": settings["bind_tls"],
            }
            if settings["domain"]:
                options["domain"] = settings["domain"]

            tunnel = ngrok.connect(**options)
            _NGROK_PUBLIC_URL = str(getattr(tunnel, "public_url", "") or "").strip()
            if _NGROK_PUBLIC_URL:
                _NGROK_ERROR = ""
                _save_ngrok_public_url(_NGROK_PUBLIC_URL)
                LOGGER.info("Ngrok tunnel started: %s", _NGROK_PUBLIC_URL)
        except Exception as exc:
            raw_err = str(exc)
            token = settings.get("authtoken") or ""
            if token:
                raw_err = raw_err.replace(token, "***REDACTED***")
            raw_err = re.sub(r"(Your authtoken:\s*)(\S+)", r"\1***REDACTED***", raw_err)
            _NGROK_ERROR = raw_err
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
        import os
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        cfg = load_cfg()
        model_name = (cfg.get("video_process") or {}).get("model", "base")
        from core.video_processor import _whisper_model_cache
        if model_name not in _whisper_model_cache:
            from faster_whisper import WhisperModel
            _whisper_model_cache[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception:
        pass


# ── YouTube uploader singleton ────────────────────────────────────────────────
_youtube_uploader = None


def _get_youtube_uploader():
    global _youtube_uploader
    if _youtube_uploader is None:
        from tools.youtube_uploader import YouTubeUploader
        _youtube_uploader = YouTubeUploader(client_secrets_file="client_secrets.json")
    return _youtube_uploader

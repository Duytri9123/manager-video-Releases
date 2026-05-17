"""
Lightweight web-app authentication — single-user password gate + CSRF.

Designed to wrap the existing Flask app *without* breaking endpoints when
auth is disabled. Behavior:

  * If `auth.enabled` is False (default) → no checks, full backwards compat.
  * If enabled, user logs in via `POST /api/auth/login` with password,
    receives an HMAC-signed cookie (`dt_auth`).
  * `before_request` rejects unauthenticated calls except a small whitelist
    (login page, login API, static, healthcheck).
  * State-changing requests (POST/PUT/DELETE/PATCH) require a CSRF token
    in `X-CSRF-Token` header that matches the cookie token.

Storage: hashed password lives in `<state_dir>/.auth.json`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from flask import Flask, request, jsonify, make_response, render_template_string

from utils.security import (
    hash_password,
    verify_password,
    make_session_cookie,
    verify_session_cookie,
    make_csrf_token,
    verify_csrf_token,
)


SESSION_COOKIE = "dt_auth"
CSRF_COOKIE = "dt_csrf"
CSRF_HEADER = "X-CSRF-Token"
SESSION_TTL = 60 * 60 * 24 * 7  # 7 days
CSRF_TTL = 60 * 60 * 4         # 4 hours

_LOGIN_HTML = """<!doctype html><meta charset=utf-8>
<title>DuyTris — Đăng nhập</title>
<style>
body{font-family:system-ui,sans-serif;background:#f0f6ff;display:flex;height:100vh;
margin:0;align-items:center;justify-content:center;color:#1a2332}
.box{background:#fff;padding:32px;border-radius:12px;box-shadow:0 8px 32px rgba(26,115,232,.15);
min-width:320px;max-width:90vw}
h1{font-size:18px;margin:0 0 4px}
p{font-size:12px;color:#6b8cba;margin:0 0 16px}
input{width:100%;padding:10px 12px;border:1.5px solid #c7d9f5;border-radius:6px;
font-size:14px;margin-bottom:12px;box-sizing:border-box}
button{width:100%;padding:10px;background:#1a73e8;color:#fff;border:0;
border-radius:6px;font-weight:600;cursor:pointer;font-size:14px}
button:hover{background:#1557b0}
.err{color:#c0392b;font-size:12px;margin-top:8px;min-height:16px}
</style>
<form class=box id=f onsubmit="return go(event)">
  <h1>🔐 DuyTris Downloader</h1>
  <p>Vui lòng nhập mật khẩu để tiếp tục.</p>
  <input id=pw type=password autofocus placeholder="Mật khẩu" required>
  <button>Đăng nhập</button>
  <div class=err id=err></div>
</form>
<script>
async function go(e){
  e.preventDefault();
  const pw=document.getElementById('pw').value;
  const err=document.getElementById('err');
  err.textContent='';
  const r=await fetch('/api/auth/login',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:pw})});
  const j=await r.json().catch(()=>({}));
  if(j.ok){location.href='/'}else{err.textContent=j.error||'Mật khẩu sai'}
  return false;
}
</script>"""


# ── Public API ───────────────────────────────────────────────────────────────
class WebAuth:
    """Holds runtime auth state. One instance per Flask app."""

    def __init__(
        self,
        state_dir: Path,
        secret_key: str,
        cfg_loader=None,
        public_paths: Optional[set] = None,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.auth_file = self.state_dir / ".auth.json"
        self.secret_key = secret_key
        self._cfg_loader = cfg_loader  # callable returning current config dict
        self.public_paths = set(public_paths or set())

    # ── helpers ──
    def _enabled(self) -> bool:
        try:
            cfg = (self._cfg_loader() if self._cfg_loader else {}) or {}
            auth_cfg = cfg.get("auth") or {}
            return bool(auth_cfg.get("enabled", False))
        except Exception:
            return False

    def _load_creds(self) -> dict:
        if not self.auth_file.exists():
            return {}
        try:
            return json.loads(self.auth_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_creds(self, data: dict):
        self.auth_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def has_password(self) -> bool:
        return bool(self._load_creds().get("password_hash"))

    def set_password(self, password: str):
        if len(password) < 6:
            raise ValueError("Mật khẩu phải tối thiểu 6 ký tự.")
        data = self._load_creds()
        data["password_hash"] = hash_password(password)
        data["updated_at"] = int(time.time())
        self._save_creds(data)

    def check_password(self, password: str) -> bool:
        data = self._load_creds()
        ph = data.get("password_hash") or ""
        if not ph:
            return False
        return verify_password(password, ph)

    def is_authenticated(self) -> bool:
        if not self._enabled():
            return True
        cookie = request.cookies.get(SESSION_COOKIE) or ""
        return verify_session_cookie(self.secret_key, cookie) is not None

    def is_public(self, path: str) -> bool:
        # Static, login page, healthcheck always public
        if path.startswith("/static/") or path == "/healthz":
            return True
        if path == "/login" or path == "/api/auth/login" or path == "/api/auth/setup":
            return True
        return path in self.public_paths

    # ── Flask wiring ──
    def attach(self, app: Flask):
        @app.route("/login")
        def _login_page():
            return _LOGIN_HTML

        @app.route("/healthz")
        def _healthz():
            return jsonify({"ok": True, "ts": int(time.time())})

        @app.route("/api/auth/setup", methods=["POST"])
        def _auth_setup():
            """First-time password setup. Disabled once a password exists."""
            if self.has_password():
                return jsonify({"ok": False, "error": "Mật khẩu đã được thiết lập."}), 400
            data = request.get_json(silent=True) or {}
            pw = (data.get("password") or "").strip()
            try:
                self.set_password(pw)
            except ValueError as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return jsonify({"ok": True})

        @app.route("/api/auth/login", methods=["POST"])
        def _auth_login():
            data = request.get_json(silent=True) or {}
            pw = (data.get("password") or "").strip()
            if not self.has_password():
                return jsonify({
                    "ok": False,
                    "error": "Chưa thiết lập mật khẩu. Đặt biến môi trường WEBAPP_PASSWORD lần chạy đầu.",
                }), 400
            if not self.check_password(pw):
                return jsonify({"ok": False, "error": "Mật khẩu không đúng."}), 401
            session = make_session_cookie(self.secret_key, "admin", SESSION_TTL)
            csrf = make_csrf_token(self.secret_key, CSRF_TTL)
            resp = make_response(jsonify({"ok": True, "csrf_token": csrf}))
            resp.set_cookie(SESSION_COOKIE, session, max_age=SESSION_TTL,
                            httponly=True, samesite="Lax")
            resp.set_cookie(CSRF_COOKIE, csrf, max_age=CSRF_TTL,
                            httponly=False, samesite="Lax")  # readable by JS
            return resp

        @app.route("/api/auth/logout", methods=["POST"])
        def _auth_logout():
            resp = make_response(jsonify({"ok": True}))
            resp.delete_cookie(SESSION_COOKIE)
            resp.delete_cookie(CSRF_COOKIE)
            return resp

        @app.route("/api/auth/status")
        def _auth_status():
            return jsonify({
                "enabled": self._enabled(),
                "has_password": self.has_password(),
                "authenticated": self.is_authenticated(),
            })

        @app.before_request
        def _guard():
            if not self._enabled():
                return None
            path = request.path or "/"
            if self.is_public(path):
                return None
            if not self.is_authenticated():
                # API requests get JSON 401, page requests get login page
                if path.startswith("/api/") or request.is_json:
                    return jsonify({"ok": False, "error": "auth_required"}), 401
                return _LOGIN_HTML, 401
            # CSRF for state-changing methods
            if request.method in ("POST", "PUT", "DELETE", "PATCH"):
                # Allow requests that come with valid signed CSRF token
                token = request.headers.get(CSRF_HEADER) or ""
                if not token:
                    # Fallback: check cookie==header pattern OR multipart form field
                    token = (request.form.get("csrf_token") if request.form else "") or ""
                if not verify_csrf_token(self.secret_key, token):
                    return jsonify({"ok": False, "error": "csrf_failed"}), 403
            return None

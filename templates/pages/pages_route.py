"""Page routes Blueprint — serves the SPA for each tab."""
from flask import Blueprint, jsonify, request
import secrets
import time
import webbrowser
from threading import Lock
from core_app import _render_spa

bp = Blueprint("pages", __name__)
_oauth_pending = {}
_oauth_lock = Lock()


@bp.post('/api/antigravity/oauth/start')
def antigravity_oauth_start():
    from core.direct_ai_provider import build_antigravity_auth_url
    state = secrets.token_urlsafe(32)
    # Use the actual local server port; desktop_launcher may choose a free one.
    port = request.environ.get('SERVER_PORT') or '9123'
    redirect_uri = f'http://localhost:{port}/callback'
    with _oauth_lock:
        now = time.time()
        for old_state in list(_oauth_pending):
            if now - _oauth_pending[old_state]['created'] > 600:
                del _oauth_pending[old_state]
        _oauth_pending[state] = {'created': now, 'redirect_uri': redirect_uri}
    if not webbrowser.open(build_antigravity_auth_url(redirect_uri, state)):
        with _oauth_lock:
            _oauth_pending.pop(state, None)
        return jsonify(error='Không mở được trình duyệt mặc định.'), 500
    return jsonify(state=state)


@bp.get('/api/antigravity/oauth/status')
def antigravity_oauth_status():
    state = request.args.get('state', '')
    with _oauth_lock:
        entry = _oauth_pending.get(state)
        if not entry or time.time() - entry['created'] > 600:
            _oauth_pending.pop(state, None)
            return jsonify(error='Phiên đăng nhập đã hết hạn.'), 404
        if 'code' not in entry and 'error' not in entry:
            return jsonify(pending=True)
        result = _oauth_pending.pop(state)
    if result.get('error'):
        return jsonify(error=result['error']), 400
    return jsonify(code=result['code'], redirect_uri=result['redirect_uri'])


@bp.route("/")
def index():
    return _render_spa("user")


@bp.route("/config")
def page_config():
    return _render_spa("config")


@bp.route("/cookies")
def page_cookies():
    return _render_spa("cookies")


@bp.route("/download")
def page_download():
    return _render_spa("download")


@bp.route("/user")
def page_user():
    return _render_spa("user")


@bp.route("/transcribe")
def page_transcribe():
    return _render_spa("transcribe")


@bp.route("/history")
def page_history():
    return _render_spa("history")


@bp.route("/process")
def page_process():
    return _render_spa("process")


@bp.route("/publish")
def page_publish():
    return _render_spa("publish")


@bp.route("/scheduler")
def page_scheduler():
    return _render_spa("scheduler")


@bp.route("/proxies")
def page_proxies():
    return _render_spa("proxies")


@bp.route("/chat")
def page_chat():
    return _render_spa("chat")


@bp.route("/callback")
@bp.route("/auth/callback")
def oauth_callback_page():
    state = request.args.get('state', '')
    with _oauth_lock:
        entry = _oauth_pending.get(state)
        if entry and time.time() - entry['created'] <= 600:
            if request.args.get('error'):
                entry['error'] = request.args['error']
            elif request.args.get('code'):
                entry['code'] = request.args['code']
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Xác thực Google OAuth Thành công</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #0f172a; color: #f8fafc; text-align: center; }
        .box { background: #1e293b; padding: 2.5rem 3.5rem; border-radius: 1rem; border: 1px solid #334155; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }
        .icon { font-size: 3rem; margin-bottom: 1rem; }
        h1 { font-size: 1.25rem; margin: 0 0 0.5rem 0; color: #38bdf8; }
        p { font-size: 0.875rem; color: #94a3b8; margin: 0; }
    </style>
</head>
<body>
    <div class="box">
        <div class="icon">⚡</div>
        <h1>Đã xác thực thành công!</h1>
        <p>Đang tự động chuyển dữ liệu kết nối vào phần mềm...</p>
    </div>
    <script>
        (function() {
            const urlParams = new URLSearchParams(window.location.search);
            const code = urlParams.get('code');
            const state = urlParams.get('state');
            const error = urlParams.get('error');
            const callbackData = { code: code, state: state, error: error, fullUrl: window.location.href };
            
            // 1. Send postMessage to opener window
            if (window.opener) {
                try {
                    window.opener.postMessage({ type: 'oauth_callback', data: callbackData }, '*');
                } catch(e) {}
            }
            
            // 2. Set BroadcastChannel
            try {
                const bc = new BroadcastChannel('oauth_callback');
                bc.postMessage(callbackData);
                bc.close();
            } catch(e) {}
            
            // 3. Set localStorage fallback
            try {
                localStorage.setItem('oauth_callback', JSON.stringify({ data: callbackData, timestamp: Date.now() }));
            } catch(e) {}
            
            // Auto close window after 600ms
            setTimeout(function() {
                try { window.close(); } catch(e) {}
            }, 600);
        })();
    </script>
</body>
</html>"""

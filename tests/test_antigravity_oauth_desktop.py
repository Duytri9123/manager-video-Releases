from unittest.mock import patch
from flask import Flask
from templates.pages.pages_route import bp, _oauth_pending


def test_google_oauth_uses_external_browser_and_delivers_callback():
    app = Flask(__name__)
    app.register_blueprint(bp)
    with patch('templates.pages.pages_route.webbrowser.open', return_value=True) as opened:
        client = app.test_client()
        started = client.post('/api/antigravity/oauth/start', base_url='http://127.0.0.1:9123')
        assert started.status_code == 200
        state = started.get_json()['state']
        assert 'accounts.google.com' in opened.call_args.args[0]
        assert f'state={state}' in opened.call_args.args[0]
        assert client.get('/api/antigravity/oauth/status', query_string={'state': state}).get_json()['pending']
        callback = client.get('/callback', query_string={'state': state, 'code': 'test-code'})
        assert callback.status_code == 200
        result = client.get('/api/antigravity/oauth/status', query_string={'state': state}).get_json()
        assert result['code'] == 'test-code'
        assert result['redirect_uri'] == 'http://localhost:9123/callback'
        assert client.get('/api/antigravity/oauth/status', query_string={'state': state}).status_code == 404
    _oauth_pending.clear()

"""A blocked Douyin profile API should still show browser-collected posts."""

from unittest.mock import patch

from flask import Flask

from templates.pages.user import route as user_route


class _Config:
    def __init__(self, _path):
        pass

    def get(self, key):
        return {"headless": True} if key == "browser_fallback" else None


class _Cookies:
    def set_cookies(self, _value):
        pass

    def get_cookies(self):
        return {}


class _Parser:
    @staticmethod
    def parse(_url):
        return {"sec_uid": "test-user"}


class _Api:
    ids = ["123"]

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def get_user_info(self, _sec_uid):
        raise RuntimeError("Empty 200 (anti-bot)")

    async def collect_user_post_ids_via_browser(self, _sec_uid, **_kwargs):
        return self.ids

    def pop_browser_post_aweme_items(self):
        return {"123": {"aweme_id": "123", "desc": "Test video", "video": {"cover": {"url_list": ["https://example.com/cover.jpg"]}}, "author": {"nickname": "Test User"}}}


class _ApiWithEmptyPosts(_Api):
    async def get_user_info(self, _sec_uid):
        return {"nickname": "Known User", "aweme_count": 42, "sec_uid": "test-user"}

    async def get_user_post(self, _sec_uid, **_kwargs):
        return {"items": [], "max_cursor": 0}


def _search(api_class=_Api):
    app = Flask(__name__)
    with (patch.object(user_route, "get_cookies_with_fallback", return_value={}),
          patch.object(user_route, "_extract_cover", return_value=""),
          patch("config.ConfigLoader", _Config),
          patch("auth.CookieManager", _Cookies),
          patch("core.DouyinAPIClient", api_class),
          patch("core.URLParser", _Parser),
          patch("core.proxy_resolver.resolve_proxy", return_value=None),
          app.test_request_context("/api/user_info", method="POST",
                                   json={"url": "https://www.douyin.com/user/test-user"})):
        return user_route.user_info()


def test_browser_fallback_returns_profile_and_post():
    with patch.object(_Api, "ids", ["123"]):
        response = _search()
    assert response.status_code == 200
    data = response.get_json()
    assert data["nickname"] == "Test User"
    assert data["videos"][0]["aweme_id"] == "123"


def test_browser_fallback_reports_blocked_profile():
    with patch.object(_Api, "ids", []):
        response, status = _search()
    assert status == 502
    assert "Douyin chặn" in response.get_json()["error"]


def test_browser_fallback_recovers_empty_post_api():
    response = _search(_ApiWithEmptyPosts)
    assert response.status_code == 200
    data = response.get_json()
    assert data["nickname"] == "Known User"
    assert [video["aweme_id"] for video in data["videos"]] == ["123"]

import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from tools.cookie_fetcher import capture_cookies


class CookieCaptureTests(unittest.TestCase):
    def capture(self, root, domain):
        page = MagicMock()
        page.is_closed.return_value = False
        page.goto = AsyncMock()
        page.title = AsyncMock(return_value='Douyin')
        context = MagicMock()
        context.pages = [page]
        context.is_closed.return_value = False
        context.add_init_script = AsyncMock()
        context.close = AsyncMock()
        context.cookies = AsyncMock(return_value=[
            {'domain': '.' + domain, 'name': 'sessionid', 'value': 'test-session'},
            {'domain': '.' + domain, 'name': 'ttwid', 'value': 'test-id'},
            {'domain': 'fake' + domain, 'name': 'injected', 'value': 'bad'},
        ])
        playwright = MagicMock()
        playwright.__aenter__ = AsyncMock(return_value=MagicMock())
        playwright.__aexit__ = AsyncMock(return_value=False)
        done = threading.Event()
        done.set()
        args = SimpleNamespace(url='https://www.' + domain, config=root / 'config.yml', finish_event=done)
        with patch('playwright.async_api.async_playwright', return_value=playwright), patch('utils.helpers.ensure_playwright_chromium'), patch('utils.helpers.launch_playwright_browser_async', AsyncMock(return_value=context)):
            result = asyncio.run(capture_cookies(args))
        context.close.assert_awaited_once()
        return result

    def test_finish_saves_and_preserves_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = Path.cwd()
            try:
                os.chdir(root)
                (root / 'config.yml').write_text(yaml.safe_dump({'path': './media', 'number': {'post': 10}, 'cookies': {'old_session': 'expired'}}), encoding='utf-8')
                result = self.capture(root, 'douyin.com')
                saved = yaml.safe_load((root / 'config.yml').read_text(encoding='utf-8'))
                self.assertEqual(saved['number']['post'], 10)
                self.assertEqual(saved['path'], './media')
                self.assertEqual(saved['cookies'], result)
                self.assertNotIn('old_session', result)
                self.assertNotIn('injected', result)
                self.assertEqual(saved['cookie_mode'], 'custom')
                self.assertEqual(json.loads((root / '.cookies.json').read_text()), result)
            finally:
                os.chdir(old)

    def test_tiktok_does_not_replace_douyin_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = Path.cwd()
            try:
                os.chdir(root)
                (root / 'config.yml').write_text('cookies: {ttwid: douyin-value}\n', encoding='utf-8')
                (root / '.cookies.json').write_text('{"ttwid": "douyin-value"}')
                self.capture(root, 'tiktok.com')
                self.assertEqual(json.loads((root / '.cookies.json').read_text())['ttwid'], 'douyin-value')
                self.assertEqual(yaml.safe_load((root / 'config.yml').read_text())['cookies']['ttwid'], 'douyin-value')
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()

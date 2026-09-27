import asyncio
import unittest
from utils.browser_download import hidden_download_browser, BrowserVerificationRequired


class HiddenDownloadTests(unittest.TestCase):
    def test_legacy_visible_setting_still_starts_hidden(self):
        calls = []
        @hidden_download_browser
        async def download(**options):
            calls.append(options['headless'])
            return 'video'
        self.assertEqual(asyncio.run(download(headless=False)), 'video')
        self.assertEqual(calls, [True])

    def test_only_captcha_reopens_after_cleanup(self):
        calls = []
        @hidden_download_browser
        async def download(**options):
            calls.append(('open', options['headless']))
            try:
                if options['headless']:
                    raise BrowserVerificationRequired()
                return 'video'
            finally:
                calls.append(('close', options['headless']))
        self.assertEqual(asyncio.run(download()), 'video')
        self.assertEqual(calls, [('open', True), ('close', True), ('open', False), ('close', False)])

    def test_network_error_does_not_show_browser(self):
        calls = []
        @hidden_download_browser
        async def download(**options):
            calls.append(options['headless'])
            raise TimeoutError('network')
        with self.assertRaises(TimeoutError):
            asyncio.run(download())
        self.assertEqual(calls, [True])

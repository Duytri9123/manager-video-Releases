"""Keep download browsers headless unless a visible verification is required."""
from functools import wraps
import logging

LOGGER = logging.getLogger(__name__)


class BrowserVerificationRequired(Exception):
    pass


def hidden_download_browser(function):
    @wraps(function)
    async def run(*args, **kwargs):
        # Even legacy saved headless=False settings start without a window.
        kwargs['headless'] = True
        try:
            return await function(*args, **kwargs)
        except BrowserVerificationRequired:
            # The first invocation's finally block closes its profile first.
            LOGGER.warning('Phát hiện CAPTCHA. Mở trình duyệt để bạn xác minh; tải sẽ tự tiếp tục.')
            kwargs['headless'] = False
            kwargs['wait_timeout_seconds'] = max(180, kwargs.get('wait_timeout_seconds', 30))
            return await function(*args, **kwargs)
    return run


async def has_browser_verification(page):
    title = (await page.title()).lower()
    if any(token in title for token in ('验证码', 'captcha', 'security verification', 'xác minh bảo mật')):
        return True
    for selector in ('#captcha_container', '.captcha_verify_container',
                     'iframe[src*="captcha"]', '[id*="captcha"] [class*="verify"]'):
        if await page.locator(selector).first.is_visible():
            return True
    return False

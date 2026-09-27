"""Recognize authenticated platform sessions without treating guest cookies as login."""
import time


def has_authenticated_session(cookies, domain, now=None):
    now = time.time() if now is None else now
    for cookie in cookies:
        host = str(cookie.get('domain') or '').lower().lstrip('.')
        if host != domain and not host.endswith('.' + domain):
            continue
        if cookie.get('name') not in {'sessionid', 'sessionid_ss', 'sid_tt'} or not cookie.get('value'):
            continue
        try:
            expiry = float(cookie.get('expires', -1))
        except (ValueError, TypeError):
            continue
        if expiry <= 0 or expiry > now:
            return True
    return False

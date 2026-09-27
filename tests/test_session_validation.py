import unittest
from auth.session_validation import has_authenticated_session


class SessionValidationTests(unittest.TestCase):
    def test_guest_csrf_cookie_is_not_login(self):
        self.assertFalse(has_authenticated_session([{'name':'passport_csrf_token', 'value':'guest', 'domain':'.douyin.com'}], 'douyin.com'))

    def test_domain_boundary_and_expiry(self):
        cookie = {'name':'sessionid', 'value':'test', 'domain':'fake-tiktok.com', 'expires':200}
        self.assertFalse(has_authenticated_session([cookie], 'tiktok.com', 100))
        cookie['domain'] = '.tiktok.com'
        self.assertTrue(has_authenticated_session([cookie], 'tiktok.com', 100))
        self.assertFalse(has_authenticated_session([cookie], 'tiktok.com', 300))
        cookie['expires'] = -1
        self.assertTrue(has_authenticated_session([cookie], 'tiktok.com', 300))

    def test_empty_session_is_not_login(self):
        self.assertFalse(has_authenticated_session([{'name':'sessionid', 'value':'', 'domain':'.douyin.com'}], 'douyin.com'))


if __name__ == '__main__':
    unittest.main()

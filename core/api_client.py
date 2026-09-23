from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp
from auth import MsTokenManager
from utils.cookie_utils import sanitize_cookies
from utils.logger import setup_logger
from utils.xbogus import XBogus

try:
    from utils.abogus import ABogus, BrowserFingerprintGenerator
except Exception:  # pragma: no cover - optional dependency
    ABogus = None
    BrowserFingerprintGenerator = None

logger = setup_logger("APIClient")

_LOGIN_REQUIRED_STATUS_CODES = {2483}


class LoginRequiredError(Exception):
    """Raised when Douyin rejects a request because the session is not logged in."""

    def __init__(self, status_code: int, status_msg: str, path: str):
        self.status_code = status_code
        self.status_msg = status_msg
        self.path = path
        super().__init__(f"login required (status_code={status_code}) at {path}: {status_msg}")


class FailedPayload(dict):
    """请求失败时回的空 payload，多带一条机器可读的失败原因。

    与 ``{}`` 完全等价(``not payload``、``payload == {}`` 都成立)。
    只有分页 walk 读 ``kind``，据此决定要不要整页重试、给用户什么文案。
    """

    REJECTED = "rejected"
    BRIDGE_ERROR = "bridge_error"

    def __init__(
        self, kind: str, *, status: int = 0, detail: str = "", via_bridge: bool = False
    ) -> None:
        super().__init__()
        self.kind = kind
        self.status = status
        self.detail = detail
        self.via_bridge = via_bridge


# ── Argus rejection detection ────────────────────────────────────────────────
# Douyin WAF (ArgusSecurityPlugin) answers 403 with a body like:
#   "Blocked by ArgusSecurityPlugin Uifid Not Found"
#   "Blocked by ArgusSecurityPlugin Signature Not Found"
# These are deterministic rejections — retrying is pointless.
ARGUS_REJECTION_MARKER = "ArgusSecurityPlugin"
_ARGUS_REJECTION_STATUS = 403
_ERROR_BODY_READ_BYTES = 1024
_ERROR_BODY_READ_TIMEOUT_SECONDS = 2.0
_ERROR_BODY_LOG_CHARS = 120

# Risk-control HTTP statuses that are transient (WAF rate-limit).
_RISK_CONTROL_HTTP_STATUSES = frozenset({403, 429})

# UA pool matching current browser versions — same approach as jiji262/douyin-downloader.
# Using Chrome (not Edge) because ABogus fingerprint is keyed to Chrome.
_USER_AGENT_POOL = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
]


class DouyinAPIClient:
    BASE_URL = "https://www.douyin.com"
    # Sensitive cookies that should NOT be injected into browser contexts.
    # Ported from jiji262/douyin-downloader to prevent session leaks.
    _BROWSER_COOKIE_BLOCKLIST = {
        "sessionid",
        "sessionid_ss",
        "sid_tt",
        "sid_guard",
        "uid_tt",
        "uid_tt_ss",
        "passport_auth_status",
        "passport_auth_status_ss",
        "passport_assist_user",
        "passport_auth_mix_state",
        "passport_mfa_token",
        "login_time",
    }

    def __init__(self, cookies: Dict[str, str], proxy: Optional[str] = None, page_bridge: Optional[Any] = None):
        self.cookies = sanitize_cookies(cookies or {})
        self.proxy = str(proxy or "").strip()
        # page_bridge: desktop-only signing channel (None in this project).
        # Kept for duck-type compatibility with shared code (base_strategy, etc.).
        self.page_bridge = page_bridge
        self._session: Optional[aiohttp.ClientSession] = None
        self._browser_post_aweme_items: Dict[str, Dict[str, Any]] = {}
        self._browser_post_stats: Dict[str, int] = {}
        # Pick a random UA from the pool — Chrome-based to match ABogus
        # fingerprint. Ported from jiji262/douyin-downloader approach.
        selected_ua = random.choice(_USER_AGENT_POOL)
        self.headers = {
            "User-Agent": selected_ua,
            "Referer": "https://www.douyin.com/?recommend=1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self._signer = XBogus(self.headers["User-Agent"])
        self._ms_token_manager = MsTokenManager(user_agent=self.headers["User-Agent"])
        self._ms_token = (self.cookies.get("msToken") or "").strip()
        self._abogus_enabled = (
            ABogus is not None and BrowserFingerprintGenerator is not None
        )

    async def __aenter__(self) -> "DouyinAPIClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.headers,
                cookies=self.cookies,
                timeout=aiohttp.ClientTimeout(total=30),
                raise_for_status=False,
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_session(self) -> aiohttp.ClientSession:
        await self._ensure_session()
        if self._session is None:
            raise RuntimeError("Failed to create aiohttp session")
        return self._session

    async def _ensure_ms_token(self) -> str:
        if self._ms_token:
            return self._ms_token

        token = await asyncio.to_thread(
            self._ms_token_manager.ensure_ms_token,
            self.cookies,
        )
        self._ms_token = token.strip()
        if self._ms_token:
            self.cookies["msToken"] = self._ms_token
            if self._session and not self._session.closed:
                self._session.cookie_jar.update_cookies({"msToken": self._ms_token})
        return self._ms_token

    async def _default_query(self) -> Dict[str, Any]:
        ms_token = await self._ensure_ms_token()
        # Parameters aligned with jiji262/douyin-downloader — Chrome/139,
        # support_dash=1, realistic screen/cpu values.
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "pc_libra_divert": "Windows",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "139.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "139.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "16",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "200",
            "support_h265": "1",
            "support_dash": "1",
            "uifid": "",
            "msToken": ms_token,
        }

    def sign_url(self, url: str) -> Tuple[str, str]:
        signed_url, _xbogus, ua = self._signer.build(url)
        return signed_url, ua

    def build_signed_path(self, path: str, params: Dict[str, Any]) -> Tuple[str, str]:
        query = urlencode(params)
        base_url = f"{self.BASE_URL}{path}"
        ab_signed = self._build_abogus_url(base_url, query)
        if ab_signed:
            return ab_signed
        return self.sign_url(f"{base_url}?{query}")

    def _build_abogus_url(self, base_url: str, query: str) -> Optional[Tuple[str, str]]:
        if not self._abogus_enabled:
            return None

        try:
            browser_fp = BrowserFingerprintGenerator.generate_fingerprint("Chrome")
            signer = ABogus(fp=browser_fp, user_agent=self.headers["User-Agent"])
            params_with_ab, _ab, ua, _body = signer.generate_abogus(query, "")
            return f"{base_url}?{params_with_ab}", ua
        except Exception as exc:
            logger.warning("Failed to generate a_bogus, fallback to X-Bogus: %s", exc)
            return None

    async def _request_json(
        self,
        path: str,
        params: Dict[str, Any],
        *,
        suppress_error: bool = False,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Make a signed GET request to Douyin API with retry and Argus detection.

        Key improvements ported from jiji262/douyin-downloader:
        - Detects ArgusSecurityPlugin rejection (403 + marker in body) and stops
          retrying immediately since those rejections are deterministic.
        - Handles empty 200 responses as anti-bot signals and retries.
        - Logs detailed diagnostics for debugging.
        """
        await self._ensure_session()
        delays = [1, 2, 5]
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            started = time.monotonic()
            signed_url, ua = self.build_signed_path(path, params)
            signer_used = "a_bogus" if "a_bogus=" in signed_url else "x_bogus"
            logger.info(
                "Douyin API request: path=%s attempt=%d/%d signer=%s",
                path, attempt + 1, max_retries, signer_used,
            )
            try:
                async with self._session.get(
                    signed_url,
                    headers={**self.headers, "User-Agent": ua},
                    proxy=self.proxy or None,
                ) as response:
                    if response.status == 200:
                        body = await response.read()
                        elapsed = int((time.monotonic() - started) * 1000)

                        # Empty 200 = anti-bot signal (from jiji262 insight)
                        if not body:
                            logger.warning(
                                "Empty 200 response for %s (attempt %d/%d, %dms) — "
                                "likely anti-bot; %s",
                                path, attempt + 1, max_retries, elapsed,
                                "will retry" if attempt < max_retries - 1 else "no retries left",
                            )
                            last_exc = RuntimeError(f"Empty 200 for {path} (anti-bot)")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                            continue

                        try:
                            data = await response.json(content_type=None)
                        except Exception:
                            import json as _json
                            try:
                                data = _json.loads(body)
                            except Exception:
                                logger.warning(
                                    "Non-JSON 200 for %s, len=%d %dms",
                                    path, len(body), elapsed,
                                )
                                return {}

                        if isinstance(data, dict):
                            logger.info(
                                "Douyin API OK: path=%s %dms items=%s has_more=%s cursor=%s",
                                path, elapsed,
                                len(data.get("aweme_list") or data.get("items") or []),
                                data.get("has_more"),
                                data.get("max_cursor", data.get("cursor")),
                            )
                        return data if isinstance(data, dict) else {}

                    # ── Non-200 handling ──────────────────────────────
                    elapsed = int((time.monotonic() - started) * 1000)

                    # Read error body prefix for Argus detection
                    error_body = ""
                    try:
                        raw_body = await asyncio.wait_for(
                            response.read(),
                            timeout=_ERROR_BODY_READ_TIMEOUT_SECONDS,
                        )
                        error_body = raw_body[:_ERROR_BODY_READ_BYTES].decode(
                            "utf-8", "replace"
                        )[:_ERROR_BODY_LOG_CHARS]
                    except Exception:
                        pass

                    # ArgusSecurityPlugin deterministic rejection — do NOT retry
                    if (
                        response.status == _ARGUS_REJECTION_STATUS
                        and ARGUS_REJECTION_MARKER in error_body
                    ):
                        logger.warning(
                            "🛡️ ArgusSecurityPlugin REJECTION: path=%s status=%s "
                            "body=%r %dms — retrying is pointless, returning empty",
                            path, response.status, error_body, elapsed,
                        )
                        return {}

                    # Transient rate-limit 403/429 — retry
                    if response.status in _RISK_CONTROL_HTTP_STATUSES:
                        logger.warning(
                            "Rate-limit: path=%s status=%s body=%r %dms (attempt %d/%d)",
                            path, response.status, error_body, elapsed,
                            attempt + 1, max_retries,
                        )
                        last_exc = RuntimeError(f"HTTP {response.status} for {path}")
                        if attempt < max_retries - 1:
                            delay = delays[min(attempt, len(delays) - 1)]
                            await asyncio.sleep(delay)
                        continue

                    # Server error (5xx) — retry
                    if response.status >= 500:
                        last_exc = RuntimeError(f"HTTP {response.status} for {path}")
                        if attempt < max_retries - 1:
                            delay = delays[min(attempt, len(delays) - 1)]
                            await asyncio.sleep(delay)
                        continue

                    # Other client errors (4xx except 403/429) — don't retry
                    log_fn = logger.debug if suppress_error else logger.error
                    log_fn(
                        "Request failed: path=%s status=%s body=%r %dms",
                        path, response.status, error_body, elapsed,
                    )
                    return {}

            except Exception as exc:
                last_exc = exc
                elapsed = int((time.monotonic() - started) * 1000)
                logger.debug(
                    "Request exception: path=%s attempt=%d/%d %dms error=%s",
                    path, attempt + 1, max_retries, elapsed, exc,
                )

            if attempt < max_retries - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                await asyncio.sleep(delay)

        log_fn = logger.debug if suppress_error else logger.error
        log_fn("Request failed after %d attempts: path=%s, error=%s", max_retries, path, last_exc)
        return {}

    @staticmethod
    def _normalize_paged_response(
        raw_data: Any,
        *,
        item_keys: Optional[List[str]] = None,
        source: str = "api",
    ) -> Dict[str, Any]:
        raw = raw_data if isinstance(raw_data, dict) else {}
        keys = item_keys or []
        keys = ["items", *keys, "aweme_list", "mix_list", "music_list"]

        items: List[Dict[str, Any]] = []
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                items = value
                break

        has_more_value = raw.get("has_more", False)
        try:
            has_more = bool(int(has_more_value))
        except (TypeError, ValueError):
            has_more = bool(has_more_value)

        max_cursor_value = raw.get("max_cursor")
        if max_cursor_value is None:
            max_cursor_value = raw.get("cursor", 0)
        try:
            max_cursor = int(max_cursor_value or 0)
        except (TypeError, ValueError):
            max_cursor = 0

        status_code_value = raw.get("status_code", 0)
        try:
            status_code = int(status_code_value or 0)
        except (TypeError, ValueError):
            status_code = 0

        risk_flags = {
            "login_tip": bool(
                ((raw.get("not_login_module") or {}).get("guide_login_tip_exist"))
                if isinstance(raw.get("not_login_module"), dict)
                else False
            ),
            "verify_page": bool(raw.get("verify_ticket")),
        }

        normalized = {
            "items": items,
            "aweme_list": items,  # 兼容旧调用方
            "has_more": has_more,
            "max_cursor": max_cursor,
            "status_code": status_code,
            "source": source,
            "risk_flags": risk_flags,
            "raw": raw,
        }
        for key, value in raw.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    async def _build_user_page_params(
        self, sec_uid: str, max_cursor: int, count: int
    ) -> Dict[str, Any]:
        params = await self._default_query()
        params.update(
            {
                "sec_user_id": sec_uid,
                "max_cursor": max_cursor,
                "count": count,
                "locate_query": "false",
            }
        )
        return params

    # aid=1128 works for videos but filters out image/note content;
    # aid=6383 works for notes/gallery but may miss some video content.
    _DETAIL_AID_CANDIDATES = ("6383", "1128")

    async def get_video_detail(
        self,
        aweme_id: str,
        *,
        suppress_error: bool = False,
        browser_fallback: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        for aid in self._DETAIL_AID_CANDIDATES:
            params = await self._default_query()
            params.update(
                {
                    "aweme_id": aweme_id,
                    "aid": aid,
                }
            )

            data = await self._request_json(
                "/aweme/v1/web/aweme/detail/",
                params,
                suppress_error=(suppress_error or aid != self._DETAIL_AID_CANDIDATES[-1]),
            )
            if not data:
                continue

            detail = data.get("aweme_detail")
            if detail:
                return detail

            # API returned data but aweme_detail is null — check if content was
            # filtered (e.g. filter_reason="images_base" for note/gallery).
            filter_info = data.get("filter_detail")
            if isinstance(filter_info, dict) and filter_info.get("filter_reason"):
                logger.info(
                    "Aweme %s filtered with aid=%s (reason=%s), retrying",
                    aweme_id,
                    aid,
                    filter_info["filter_reason"],
                )
                continue

            # aweme_detail is null without a filter reason — no retry needed
            break

        # API path failed — try Playwright browser fallback if configured
        if browser_fallback is not None and browser_fallback.get("enabled"):
            return await self.fetch_single_video_via_browser(
                aweme_id,
                headless=bool(browser_fallback.get("headless", False)),
                wait_timeout_seconds=int(browser_fallback.get("wait_timeout_seconds", 30)),
            )

        return None

    get_aweme_detail = get_video_detail

    async def fetch_single_video_via_browser(
        self,
        aweme_id: str,
        *,
        headless: bool = False,
        wait_timeout_seconds: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """Mở Playwright, điều hướng đến trang video, intercept aweme/detail response.

        Dùng khi API bị Argus block (403 Uifid Not Found).
        Browser thật tự generate UIFID nên request đi qua được.
        """
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.warning("Playwright not available, single-video browser fallback disabled: %s", exc)
            return None

        target_url = f"{self.BASE_URL}/video/{aweme_id}"
        timeout_ms = max(15, int(wait_timeout_seconds)) * 1000
        result: Optional[Dict[str, Any]] = None
        detail_event: asyncio.Event = asyncio.Event()

        logger.warning(
            "API bị Argus block, khởi động browser fallback để tải video đơn lẻ: "
            "aweme_id=%s headless=%s timeout_s=%s",
            aweme_id, headless, wait_timeout_seconds,
        )

        async with async_playwright() as playwright:
            if not headless:
                import sys, threading, subprocess
                if sys.platform == "win32":
                    def _minimize():
                        try:
                            subprocess.run(
                                ["powershell", "-Command",
                                 "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
                                 "public class W{[DllImport(\"user32.dll\")]"
                                 "public static extern bool ShowWindow(IntPtr h,int n);}';"
                                 "Start-Sleep -Milliseconds 600;"
                                 "Get-Process chrome,msedge,brave -ErrorAction SilentlyContinue"
                                 "| Where-Object {$_.MainWindowHandle -ne 0}"
                                 "| Sort-Object StartTime -Descending | Select-Object -First 3"
                                 "| ForEach-Object { [W]::ShowWindow($_.MainWindowHandle, 6) }"
                                 ],
                                capture_output=True, timeout=4
                            )
                        except Exception:
                            pass
                    threading.Thread(target=_minimize, daemon=True).start()

            browser = await playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            context = await browser.new_context(
                user_agent=self.headers.get("User-Agent", ""),
                locale="zh-CN",
                viewport={"width": 1600, "height": 900},
            )
            cookies = self._browser_cookie_payload()
            if cookies:
                await context.add_cookies(cookies)

            page = await context.new_page()

            async def _handle_response(response):
                nonlocal result
                url = response.url or ""
                if "/aweme/v1/web/aweme/detail/" not in url:
                    return
                try:
                    data = await response.json()
                except Exception:
                    return
                if not isinstance(data, dict):
                    return
                detail = data.get("aweme_detail")
                if isinstance(detail, dict) and detail.get("aweme_id"):
                    result = detail
                    logger.info(
                        "Browser fallback intercepted aweme/detail: aweme_id=%s",
                        detail.get("aweme_id"),
                    )
                    detail_event.set()

            page.on("response", lambda r: asyncio.create_task(_handle_response(r)))

            try:
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as exc:
                    logger.warning("Browser goto error (continuing): %s", exc)
                try:
                    await asyncio.wait_for(detail_event.wait(), timeout=wait_timeout_seconds)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Browser fallback timeout waiting for aweme/detail: aweme_id=%s",
                        aweme_id,
                    )
            finally:
                try:
                    browser_cookies = await context.cookies(self.BASE_URL)
                    self._sync_browser_cookies(browser_cookies)
                except Exception as exc:
                    logger.debug("Sync browser cookies skipped: %s", exc)
                await context.close()
                await browser.close()

        if result:
            logger.warning(
                "Browser fallback thành công: aweme_id=%s desc=%r",
                aweme_id, str(result.get("desc", ""))[:80],
            )
        else:
            logger.warning("Browser fallback không lấy được aweme_detail: aweme_id=%s", aweme_id)
        return result

    async def get_user_post(
        self, sec_uid: str, max_cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._build_user_page_params(sec_uid, max_cursor, count)
        params.update(
            {
                "show_live_replay_strategy": "1",
                "need_time_list": "1",
                "time_list_query": "0",
                "whale_cut_token": "",
                "cut_version": "1",
                "publish_video_strategy_type": "2",
            }
        )
        raw = await self._request_json("/aweme/v1/web/aweme/post/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def get_user_like(
        self, sec_uid: str, max_cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._build_user_page_params(sec_uid, max_cursor, count)
        raw = await self._request_json("/aweme/v1/web/aweme/favorite/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def get_user_mix(
        self, sec_uid: str, max_cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._build_user_page_params(sec_uid, max_cursor, count)
        raw = await self._request_json("/aweme/v1/web/mix/list/", params)
        return self._normalize_paged_response(raw, item_keys=["mix_list"])

    async def get_user_music(
        self, sec_uid: str, max_cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._build_user_page_params(sec_uid, max_cursor, count)
        raw = await self._request_json("/aweme/v1/web/music/list/", params)
        return self._normalize_paged_response(raw, item_keys=["music_list"])

    async def _build_collect_page_params(
        self, max_cursor: int, count: int
    ) -> Dict[str, Any]:
        params = await self._default_query()
        params.update(
            {
                "cursor": max_cursor,
                "count": count,
                "version_code": "170400",
                "version_name": "17.4.0",
            }
        )
        return params

    async def get_user_collects(
        self, sec_uid: str, max_cursor: int = 0, count: int = 10
    ) -> Dict[str, Any]:
        if sec_uid and sec_uid != "self":
            logger.warning("Collect folders currently require self sec_uid, got=%s", sec_uid)
            return self._normalize_paged_response(
                {}, item_keys=["collects_list"], source="api"
            )

        params = await self._build_collect_page_params(max_cursor, count)
        raw = await self._request_json("/aweme/v1/web/collects/list/", params)
        return self._normalize_paged_response(raw, item_keys=["collects_list"])

    async def get_collect_aweme(
        self, collects_id: str, max_cursor: int = 0, count: int = 10
    ) -> Dict[str, Any]:
        params = await self._build_collect_page_params(max_cursor, count)
        params.update({"collects_id": collects_id})
        raw = await self._request_json("/aweme/v1/web/collects/video/list/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def get_user_collect_mix(
        self, sec_uid: str, max_cursor: int = 0, count: int = 12
    ) -> Dict[str, Any]:
        if sec_uid and sec_uid != "self":
            logger.warning("Collect mix currently require self sec_uid, got=%s", sec_uid)
            return self._normalize_paged_response(
                {}, item_keys=["mix_infos"], source="api"
            )

        params = await self._build_collect_page_params(max_cursor, count)
        raw = await self._request_json("/aweme/v1/web/mix/listcollection/", params)
        return self._normalize_paged_response(raw, item_keys=["mix_infos"])

    async def get_user_info(self, sec_uid: str) -> Optional[Dict[str, Any]]:
        params = await self._default_query()
        params.update({"sec_user_id": sec_uid})

        data = await self._request_json("/aweme/v1/web/user/profile/other/", params)
        if data:
            return data.get("user")
        return None

    async def get_mix_detail(self, mix_id: str) -> Optional[Dict[str, Any]]:
        params = await self._default_query()
        params.update({"mix_id": mix_id})
        data = await self._request_json("/aweme/v1/web/mix/detail/", params)
        if not data:
            return None
        return data.get("mix_info") or data.get("mix_detail") or data

    async def get_mix_aweme(
        self, mix_id: str, cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._default_query()
        params.update({"mix_id": mix_id, "cursor": cursor, "count": count})
        raw = await self._request_json("/aweme/v1/web/mix/aweme/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def get_music_detail(self, music_id: str) -> Optional[Dict[str, Any]]:
        params = await self._default_query()
        params.update({"music_id": music_id})
        data = await self._request_json("/aweme/v1/web/music/detail/", params)
        if not data:
            return None
        return data.get("music_info") or data.get("music_detail") or data

    async def get_music_aweme(
        self, music_id: str, cursor: int = 0, count: int = 20
    ) -> Dict[str, Any]:
        params = await self._default_query()
        params.update({"music_id": music_id, "cursor": cursor, "count": count})
        raw = await self._request_json("/aweme/v1/web/music/aweme/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def resolve_short_url(self, short_url: str) -> Optional[str]:
        try:
            await self._ensure_session()
            async with self._session.get(
                short_url,
                allow_redirects=True,
                proxy=self.proxy or None,
            ) as response:
                return str(response.url)
        except Exception as e:
            logger.error("Failed to resolve short URL: %s, error: %s", short_url, e)
            return None

    async def collect_user_post_ids_via_browser(
        self,
        sec_uid: str,
        *,
        expected_count: int = 0,
        headless: bool = False,
        max_scrolls: int = 240,
        idle_rounds: int = 8,
        wait_timeout_seconds: int = 600,
    ) -> List[str]:
        try:
            from playwright.async_api import async_playwright
            from utils.helpers import ensure_playwright_chromium
            ensure_playwright_chromium()
        except Exception as exc:
            logger.warning(
                "Playwright not available or error installing browser: %s", exc
            )
            return []

        target_url = f"{self.BASE_URL}/user/{sec_uid}"
        timeout_ms = max(30, int(wait_timeout_seconds)) * 1000
        ids: List[str] = []
        seen: set[str] = set()
        post_api_ids: List[str] = []
        post_api_seen: set[str] = set()
        post_api_aweme_items: Dict[str, Dict[str, Any]] = {}
        post_api_page_hits = 0
        self._browser_post_aweme_items = {}
        self._browser_post_stats = {}

        def _merge(new_ids: List[str]):
            for aweme_id in new_ids:
                if aweme_id and aweme_id not in seen:
                    seen.add(aweme_id)
                    ids.append(aweme_id)

        logger.warning(
            "API翻页受限，启动浏览器兜底采集（可在弹出页面手动通过验证码/登录）：%s",
            target_url,
        )

        async with async_playwright() as playwright:
            from pathlib import Path
            from utils.helpers import launch_playwright_browser_async
            douyin_profile_dir = Path(".douyin_profile").resolve()
            douyin_profile_dir.mkdir(parents=True, exist_ok=True)
            browser = None

            # Minimize the browser window immediately after launch on Windows
            # so it runs in the background without occupying the screen.
            def _minimize_browser_window():
                import sys
                if sys.platform != "win32":
                    return
                try:
                    import subprocess
                    subprocess.run(
                        ["powershell", "-Command",
                         "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
                         "public class W{[DllImport(\"user32.dll\")]"
                         "public static extern bool ShowWindow(IntPtr h,int n);}';"
                         "Start-Sleep -Milliseconds 600;"
                         "Get-Process chrome,msedge,brave -ErrorAction SilentlyContinue"
                         "| Where-Object {$_.MainWindowHandle -ne 0}"
                         "| Sort-Object StartTime -Descending | Select-Object -First 3"
                         "| ForEach-Object { [W]::ShowWindow($_.MainWindowHandle, 6) }"
                         ],
                        capture_output=True, timeout=4
                    )
                except Exception:
                    pass

            if not headless:
                import threading
                threading.Thread(target=_minimize_browser_window, daemon=True).start()

            try:
                context = await launch_playwright_browser_async(
                    playwright.chromium,
                    is_persistent=True,
                    user_data_dir=str(douyin_profile_dir),
                    headless=headless,
                    viewport={"width": 1600, "height": 900},
                    locale="zh-CN",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
            except Exception as _p_err:
                logger.debug("Persistent browser launch fallback to standard: %s", _p_err)
                browser = await launch_playwright_browser_async(
                    playwright.chromium,
                    is_persistent=False,
                    headless=headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
                context = await browser.new_context(
                    user_agent=self.headers.get("User-Agent", ""),
                    locale="zh-CN",
                    viewport={"width": 1600, "height": 900},
                )

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            cookies = self._browser_cookie_payload()
            if cookies:
                try:
                    await context.add_cookies(cookies)
                except Exception as _c_err:
                    logger.debug("Add cookies to browser context error: %s", _c_err)

            page = context.pages[0] if context.pages else await context.new_page()
            pending_response_tasks: List[asyncio.Task] = []

            async def _handle_response(response):
                nonlocal post_api_page_hits
                url = response.url or ""
                if "/aweme/v1/web/aweme/post/" not in url:
                    return
                try:
                    data = await response.json()
                except Exception:
                    return
                aweme_items = data.get("aweme_list") if isinstance(data, dict) else None
                if isinstance(aweme_items, list):
                    post_api_page_hits += 1
                    extracted: List[str] = []
                    for item in aweme_items:
                        if not isinstance(item, dict):
                            continue
                        aweme_id = item.get("aweme_id")
                        if not aweme_id:
                            continue
                        aweme_id_str = str(aweme_id)
                        extracted.append(aweme_id_str)
                        if aweme_id_str not in post_api_aweme_items:
                            post_api_aweme_items[aweme_id_str] = item
                    _merge(extracted)
                    for aweme_id in extracted:
                        if aweme_id not in post_api_seen:
                            post_api_seen.add(aweme_id)
                            post_api_ids.append(aweme_id)

            def _on_response(response):
                pending_response_tasks.append(
                    asyncio.create_task(_handle_response(response))
                )

            page.on("response", _on_response)

            try:
                try:
                    await page.goto(
                        target_url, wait_until="domcontentloaded", timeout=timeout_ms
                    )
                except Exception as exc:
                    logger.warning(
                        "Browser goto timeout or error, continue with current page state: %s",
                        exc,
                    )

                title = ""
                try:
                    title = await page.title()
                except Exception:
                    pass
                if "验证码" in title:
                    if headless:
                        logger.warning(
                            "检测到验证码页面且当前为 headless 模式，无法人工验证。"
                            "请将 browser_fallback.headless 设为 false。"
                        )
                        return []
                    logger.warning(
                        "检测到验证码页面，请在浏览器中完成验证，程序会自动继续采集。"
                    )
                    await self._wait_for_manual_verification(
                        page, wait_timeout_seconds=wait_timeout_seconds
                    )
                    if not page.is_closed():
                        try:
                            await page.goto(
                                target_url,
                                wait_until="domcontentloaded",
                                timeout=timeout_ms,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Reload user page after verification failed: %s", exc
                            )

                try:
                    warmup_seconds = min(20, max(3, int(wait_timeout_seconds)))
                    for _ in range(warmup_seconds):
                        if page.is_closed():
                            logger.warning("Browser page closed during warmup")
                            break
                        cards = await self._extract_aweme_cards_from_page(page)
                        for c in cards:
                            cid = str(c.get("aweme_id") or "")
                            if cid:
                                if cid not in post_api_aweme_items:
                                    post_api_aweme_items[cid] = c
                                if cid not in seen:
                                    seen.add(cid)
                                    ids.append(cid)
                        _merge(await self._extract_aweme_ids_from_page(page))
                        if ids:
                            break
                        await page.wait_for_timeout(1000)

                    stable_rounds = 0
                    max_scroll_rounds = max(1, int(max_scrolls))
                    idle_stop_rounds = max(1, int(idle_rounds))

                    for _ in range(max_scroll_rounds):
                        if page.is_closed():
                            logger.warning("Browser page closed during scrolling")
                            break
                        await page.mouse.wheel(0, 3800)
                        await page.wait_for_timeout(1200)

                        before = len(ids)
                        cards = await self._extract_aweme_cards_from_page(page)
                        for c in cards:
                            cid = str(c.get("aweme_id") or "")
                            if cid:
                                if cid not in post_api_aweme_items:
                                    post_api_aweme_items[cid] = c
                                if cid not in seen:
                                    seen.add(cid)
                                    ids.append(cid)
                        _merge(await self._extract_aweme_ids_from_page(page))
                        if len(ids) == before:
                            stable_rounds += 1
                        else:
                            stable_rounds = 0

                        if expected_count > 0 and len(ids) >= expected_count:
                            break
                        if expected_count <= 0 and stable_rounds >= idle_stop_rounds:
                            break
                except Exception as exc:
                    logger.warning(
                        "Browser collection interrupted, use collected ids so far: %s",
                        exc,
                    )
            finally:
                if pending_response_tasks:
                    await asyncio.gather(
                        *pending_response_tasks, return_exceptions=True
                    )
                try:
                    browser_cookies = await context.cookies(self.BASE_URL)
                    self._sync_browser_cookies(browser_cookies)
                except Exception as exc:
                    logger.debug("Sync browser cookies skipped: %s", exc)
                try:
                    await context.close()
                except Exception:
                    pass
                if browser is not None and browser != context:
                    try:
                        await browser.close()
                    except Exception:
                        pass

        selected_ids: List[str] = []
        selected_seen: set[str] = set()
        for aweme_id in post_api_ids + ids:
            if aweme_id and aweme_id not in selected_seen:
                selected_seen.add(aweme_id)
                selected_ids.append(aweme_id)
        self._browser_post_aweme_items = post_api_aweme_items
        self._browser_post_stats = {
            "merged_ids": len(ids),
            "post_api_ids": len(post_api_ids),
            "selected_ids": len(selected_ids),
            "post_items": len(post_api_aweme_items),
            "post_pages": post_api_page_hits,
        }
        logger.warning(
            "浏览器兜底采集 aweme_id: merged=%s, from_post_api=%s, selected=%s, post_items=%s",
            len(ids),
            len(post_api_ids),
            len(selected_ids),
            len(post_api_aweme_items),
        )
        return selected_ids

    def pop_browser_post_aweme_items(self) -> Dict[str, Dict[str, Any]]:
        items = self._browser_post_aweme_items
        self._browser_post_aweme_items = {}
        return items

    def pop_browser_post_stats(self) -> Dict[str, int]:
        stats = self._browser_post_stats
        self._browser_post_stats = {}
        return stats

    def _browser_cookie_payload(self) -> List[Dict[str, str]]:
        payload: List[Dict[str, str]] = []
        for name, value in self.cookies.items():
            if not name or value is None:
                continue
            name_str = str(name).strip()
            val_str = str(value).strip()
            if not name_str or not val_str:
                continue
            if name_str in self._BROWSER_COOKIE_BLOCKLIST:
                continue
            payload.append(
                {
                    "name": name_str,
                    "value": val_str,
                    "domain": ".douyin.com",
                    "path": "/",
                }
            )
        return payload

    async def _extract_aweme_cards_from_page(self, page) -> List[Dict[str, Any]]:
        script = """
() => {
  const items = [];
  const seen = new Set();
  const links = document.querySelectorAll("a[href*='/video/'], a[href*='/note/']");
  for (const node of links) {
    const href = node.getAttribute("href") || "";
    const match = href.match(/\\/(video|note)\\/(\\d{15,22})/);
    if (!match) continue;
    const typeStr = match[1];
    const aweme_id = match[2];
    if (seen.has(aweme_id)) continue;
    seen.add(aweme_id);

    let cover = "";
    const img = node.querySelector("img") || node.parentElement?.querySelector("img");
    if (img) {
      cover = img.currentSrc || img.src || img.getAttribute("data-src") || "";
    }

    let desc = node.getAttribute("title") || "";
    if (!desc) {
      const textEl = node.querySelector("p, span, [class*='desc'], [class*='title']");
      if (textEl) desc = textEl.textContent.trim();
    }
    if (!desc && img) {
      desc = img.getAttribute("alt") || "";
    }

    items.push({
      aweme_id: aweme_id,
      desc: desc || ("Video " + aweme_id),
      cover: cover,
      images: typeStr === "note" && cover ? [{ url_list: [cover] }] : [],
      video: {
        cover: { url_list: [cover] },
        origin_cover: { url_list: [cover] },
        duration: 0
      },
      statistics: {
        play_count: 0,
        digg_count: 0,
        comment_count: 0
      },
      create_time: 0
    });
  }
  return items;
}
"""
        try:
            data = await page.evaluate(script)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("aweme_id")]
        except Exception as exc:
            logger.debug("Extract aweme cards from page failed: %s", exc)
        return []

    async def _extract_aweme_ids_from_page(self, page) -> List[str]:
        script = """
() => {
  const result = [];
  const seen = new Set();
  const push = (id) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    result.push(id);
  };

  const collectFrom = (text, pattern) => {
    if (!text) return;
    let match;
    while ((match = pattern.exec(text)) !== null) {
      push(match[1]);
    }
  };

  const links = document.querySelectorAll("a[href]");
  for (const node of links) {
    const href = node.getAttribute("href") || "";
    collectFrom(href, /\\/video\\/(\\d{15,20})/g);
    collectFrom(href, /\\/note\\/(\\d{15,20})/g);
  }

  const html = document.documentElement ? document.documentElement.innerHTML : "";
  collectFrom(html, /"aweme_id":"(\\d{15,20})"/g);
  collectFrom(html, /"group_id":"(\\d{15,20})"/g);

  return result;
}
"""
        try:
            data = await page.evaluate(script)
            if isinstance(data, list):
                return [str(x) for x in data if x]
        except Exception as exc:
            logger.debug("Extract aweme_id from page failed: %s", exc)
        return []

    async def _wait_for_manual_verification(
        self, page, *, wait_timeout_seconds: int
    ) -> None:
        deadline = asyncio.get_running_loop().time() + max(
            30, int(wait_timeout_seconds)
        )
        while asyncio.get_running_loop().time() < deadline:
            if page.is_closed():
                logger.warning("Browser page closed while waiting manual verification")
                return
            title = ""
            try:
                title = await page.title()
            except Exception:
                pass
            if "验证码" not in title:
                logger.warning("验证码页面已退出，继续采集。")
                return
            await page.wait_for_timeout(1000)

        logger.warning(
            "等待手动验证超时（%ss），继续按当前页面状态采集。", wait_timeout_seconds
        )

    def _sync_browser_cookies(self, browser_cookies: List[Dict[str, Any]]) -> None:
        merged: Dict[str, str] = {}
        for cookie in browser_cookies or []:
            if not isinstance(cookie, dict):
                continue
            name = str(cookie.get("name") or "").strip()
            value = str(cookie.get("value") or "").strip()
            domain = str(cookie.get("domain") or "")
            if not name or not value:
                continue
            if "douyin.com" not in domain:
                continue
            merged[name] = value

        if not merged:
            return

        self.cookies.update(merged)
        if self._session and not self._session.closed:
            self._session.cookie_jar.update_cookies(merged)
        logger.warning("Synced %s browser cookie(s) back to API client", len(merged))

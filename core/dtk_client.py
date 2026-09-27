"""DTK (Douyin_TikTok_Download_API) client — fallback downloader.

Khi DouyinAPIClient gốc thất bại (cookie hết hạn, rate-limit, risk-control),
module này gọi một instance DTK self-hosted (hoặc demo.douyin.wtf) để lấy
CDN URL sạch không watermark rồi tải bytes về.

Cấu hình qua config.yml::

    dtk:
      enabled: false
      base_url: "http://localhost:8000"   # instance của bạn
      api_key: ""                          # X-API-Key nếu đã tạo
      username: ""                         # login fallback nếu không có api_key
      password: ""
      timeout: 40                          # giây chờ parse (wait=)
      use_as_fallback: true               # chỉ dùng khi Douyin gốc fail
      use_as_primary: false               # dùng hoàn toàn thay Douyin gốc

Lưu ý bảo mật:
  - Không bao giờ truyền cookie Douyin sang DTK (DTK có identity pool riêng).
  - Chỉ gửi URL cần parse; phần bytes được tải trực tiếp từ CDN không qua DTK.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

try:
    import aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False

logger = logging.getLogger("DTKClient")

# ── Sentinel để phân biệt "DTK chưa cấu hình" vs "DTK trả lỗi" ────────────
class DTKNotConfigured(Exception):
    """DTK không được bật trong config."""

class DTKParseError(Exception):
    """DTK trả về lỗi hoặc không parse được URL."""


class DTKClient:
    """Wrapper bất đồng bộ giao tiếp với một DTK instance.

    Sử dụng aiohttp (đã có sẵn trong toolvideo) làm HTTP client; fallback sang
    httpx nếu cần. Hoạt động hoàn toàn async, không block event loop.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        username: str = "",
        password: str = "",
        timeout: int = 40,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.username = username.strip()
        self.password = password.strip()
        self.timeout = int(timeout)
        self._session_cookie: str = ""  # dùng khi login bằng username/password

    # ── Auth ────────────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        """HTTP headers cơ bản cho mọi request."""
        h: Dict[str, str] = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        elif self._session_cookie:
            h["Cookie"] = self._session_cookie
        return h

    async def _ensure_auth(self, session: "aiohttp.ClientSession") -> None:
        """Đảm bảo đã có credentials (api_key hoặc session cookie)."""
        if self.api_key:
            return  # api_key ưu tiên tuyệt đối, không cần login
        if self._session_cookie:
            return  # đã login từ trước

        if not (self.username and self.password):
            # Thử lấy demo credentials tự động nếu là demo instance
            await self._try_demo_credentials(session)
            return

        await self._login(session)

    async def _try_demo_credentials(self, session: "aiohttp.ClientSession") -> None:
        """Lấy tự động demo credentials từ /api/v1/auth/demo endpoint."""
        try:
            async with session.get(
                f"{self.base_url}/api/v1/auth/demo",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    data = body.get("data") or {}
                    self.username = data.get("username", "")
                    self.password = data.get("password", "")
                    if self.username and self.password:
                        await self._login(session)
        except Exception as exc:
            logger.debug("DTK: demo credentials fetch failed: %s", exc)

    async def _login(self, session: "aiohttp.ClientSession") -> None:
        """POST /api/v1/auth/login — lưu session cookie."""
        try:
            async with session.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"username": self.username, "password": self.password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    # Lấy cookie từ Set-Cookie header
                    raw = resp.headers.get("Set-Cookie", "")
                    if raw:
                        # Lấy phần name=value đầu tiên (trước dấu ;)
                        self._session_cookie = raw.split(";")[0].strip()
                        logger.debug("DTK: login OK, cookie acquired")
                    else:
                        logger.warning("DTK: login returned 200 but no Set-Cookie")
                else:
                    body = await resp.text()
                    logger.warning("DTK: login failed (%s): %s", resp.status, body[:200])
        except Exception as exc:
            logger.warning("DTK: login exception: %s", exc)

    # ── Core API ─────────────────────────────────────────────────────────────

    async def parse(self, url: str) -> Optional[Dict[str, Any]]:
        """POST /api/v1/parse — parse một URL Douyin/TikTok.

        Trả về dict ``data`` của response (chứa ``media``, ``author``, ...),
        hoặc ``None`` nếu thất bại.
        """
        if not _HAS_AIOHTTP:
            logger.error("DTK: aiohttp not available, cannot make requests")
            return None

        wait = min(self.timeout, 60)  # DTK max wait cap
        endpoint = f"{self.base_url}/api/v1/parse?wait={wait}"

        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            await self._ensure_auth(session)
            try:
                async with session.post(
                    endpoint,
                    json={"url": url},
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout + 10),
                ) as resp:
                    body = await resp.json(content_type=None)

                    if resp.status == 200 and body.get("success"):
                        return body.get("data")

                    # 202 = task vẫn đang chạy (wait quá ngắn), thử poll
                    if resp.status == 202:
                        task_id = (body.get("data") or {}).get("task_id")
                        if task_id:
                            return await self._poll_task(session, task_id)

                    err = (body.get("error") or {}).get("message", "unknown")
                    logger.warning("DTK parse failed (%s): %s", resp.status, err)
                    return None

            except asyncio.TimeoutError:
                logger.warning("DTK parse timeout for URL: %s", url[:80])
                return None
            except Exception as exc:
                logger.warning("DTK parse error: %s", exc)
                return None

    async def _poll_task(
        self,
        session: "aiohttp.ClientSession",
        task_id: str,
        *,
        max_polls: int = 12,
        interval: float = 3.0,
    ) -> Optional[Dict[str, Any]]:
        """Poll GET /api/v1/tasks/{task_id} khi wait= không đủ thời gian."""
        for _ in range(max_polls):
            await asyncio.sleep(interval)
            try:
                async with session.get(
                    f"{self.base_url}/api/v1/tasks/{task_id}",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status == 200 and body.get("success"):
                        data = body.get("data") or {}
                        state = data.get("state", "")
                        if state == "done":
                            return data.get("result")
                        if state in ("failed", "cancelled"):
                            logger.warning("DTK task %s ended with state=%s", task_id, state)
                            return None
            except Exception as exc:
                logger.debug("DTK poll error: %s", exc)
        logger.warning("DTK task %s timed out after polling", task_id)
        return None

    # ── Helpers trích xuất URL video ─────────────────────────────────────────

    @staticmethod
    def extract_video_urls(parsed_data: Dict[str, Any]) -> List[str]:
        """Lấy danh sách CDN URL video không watermark từ kết quả parse.

        DTK xếp watermark-free stream trước, nên ``urls[0]`` luôn là tốt nhất.
        Lọc bỏ URL chứa ``watermark=1`` để chắc chắn.
        """
        media = parsed_data.get("media") or {}
        video = media.get("video") or {}
        urls: List[str] = []

        # Primary stream
        primary = video.get("url")
        if isinstance(primary, str) and primary:
            urls.append(primary)

        # All streams / bitrates
        for stream in (media.get("streams") or []):
            if not isinstance(stream, dict):
                continue
            u = stream.get("url")
            if isinstance(u, str) and u and u not in urls:
                urls.append(u)
            for alt in (stream.get("urls") or []):
                if isinstance(alt, str) and alt and alt not in urls:
                    urls.append(alt)

        # Fallback: urls list ở level video
        for u in (video.get("urls") or []):
            if isinstance(u, str) and u and u not in urls:
                urls.append(u)

        # Lọc bỏ URL có watermark rõ ràng (watermark=1 trong query string)
        clean = [u for u in urls if "watermark=1" not in u]
        return clean if clean else urls  # nếu tất cả đều có watermark thì dùng hết

    @staticmethod
    def extract_cover_url(parsed_data: Dict[str, Any]) -> Optional[str]:
        """Lấy URL ảnh cover từ kết quả parse."""
        media = parsed_data.get("media") or {}
        covers = media.get("covers") or []
        for cover in covers:
            if isinstance(cover, dict):
                u = cover.get("url")
                if isinstance(u, str) and u:
                    return u
        return None

    @staticmethod
    def extract_music_url(parsed_data: Dict[str, Any]) -> Optional[str]:
        """Lấy URL nhạc nền từ kết quả parse."""
        music = parsed_data.get("music") or {}
        return music.get("play_url") or None

    @staticmethod
    def build_aweme_data(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Chuyển đổi response DTK sang format tương thích DouyinAPIClient.

        Tạo ra một dict giả lập ``aweme_detail`` để các Downloader hiện tại
        có thể dùng mà không cần sửa thêm code.
        """
        author = parsed_data.get("author") or {}
        media = parsed_data.get("media") or {}
        music = parsed_data.get("music") or {}
        stats = parsed_data.get("stats") or {}
        video_urls = DTKClient.extract_video_urls(parsed_data)

        # Tạo cấu trúc video giả lập (tương thích với _save_video trong downloader_base)
        video_obj: Dict[str, Any] = {}
        if video_urls:
            video_obj = {
                "play_addr": {
                    "url_list": video_urls,
                    "width": (media.get("video") or {}).get("width", 0),
                    "height": (media.get("video") or {}).get("height", 0),
                },
                "download_addr": {
                    "url_list": video_urls,
                },
                "duration": parsed_data.get("duration_ms", 0),
                "bit_rate": [],
            }

        # Ảnh album nếu có
        images_raw = media.get("images") or []
        image_post_infos = []
        for img in images_raw:
            if not isinstance(img, dict):
                continue
            img_urls = []
            if img.get("url"):
                img_urls.append(img["url"])
            img_urls.extend(img.get("urls") or [])
            if img_urls:
                image_post_infos.append({
                    "display_image": {"url_list": img_urls},
                    "thumbnail": {"url_list": img_urls},
                })

        # Cover
        cover_url = DTKClient.extract_cover_url(parsed_data)
        cover_obj = {"url_list": [cover_url]} if cover_url else {"url_list": []}

        return {
            "aweme_id": parsed_data.get("content_id", ""),
            "desc": parsed_data.get("description") or parsed_data.get("title") or "",
            "create_time": 0,
            "author": {
                "sec_uid": author.get("sec_uid", ""),
                "uid": author.get("uid", ""),
                "nickname": author.get("nickname", ""),
                "unique_id": author.get("unique_id", ""),
                "avatar_thumb": {"url_list": [author.get("avatar", {}).get("url", "")]},
            },
            "video": video_obj,
            "image_post_info": {
                "images": image_post_infos,
            } if image_post_infos else None,
            "music": {
                "id_str": music.get("music_id", ""),
                "title": music.get("title", ""),
                "play_url": {"url_list": [music.get("play_url", "")] if music.get("play_url") else []},
            },
            "statistics": {
                "digg_count": stats.get("digg_count", 0),
                "share_count": stats.get("share_count", 0),
                "collect_count": stats.get("collect_count", 0),
                "comment_count": stats.get("comment_count", 0),
            },
            "cover": cover_obj,
            "is_top": 0,
            # Đánh dấu nguồn gốc để debug
            "_via_dtk": True,
        }


# ── Factory function tiện dụng ────────────────────────────────────────────────

def dtk_client_from_config(config: Any) -> Optional["DTKClient"]:
    """Tạo DTKClient từ ConfigLoader.

    Trả về ``None`` nếu DTK không được bật hoặc không có base_url.
    """
    dtk_cfg = config.get("dtk") if hasattr(config, "get") else {}
    if not dtk_cfg or not dtk_cfg.get("enabled"):
        return None
    base_url = str(dtk_cfg.get("base_url") or "").strip()
    if not base_url:
        return None
    return DTKClient(
        base_url=base_url,
        api_key=str(dtk_cfg.get("api_key") or "").strip(),
        username=str(dtk_cfg.get("username") or "").strip(),
        password=str(dtk_cfg.get("password") or "").strip(),
        timeout=int(dtk_cfg.get("timeout") or 40),
    )


async def try_parse_via_dtk(url: str, config: Any) -> Optional[Dict[str, Any]]:
    """Shortcut: tạo client từ config, parse URL, trả về aweme_data tương thích.

    Trả về ``None`` nếu DTK không cấu hình hoặc parse thất bại.
    Caller không cần handle exception — mọi lỗi đã được log và swallow.
    """
    client = dtk_client_from_config(config)
    if client is None:
        return None
    logger.info("DTK: attempting parse for %s", url[:80])
    parsed = await client.parse(url)
    if parsed is None:
        return None
    return DTKClient.build_aweme_data(parsed)


__all__ = [
    "DTKClient",
    "DTKNotConfigured",
    "DTKParseError",
    "dtk_client_from_config",
    "try_parse_via_dtk",
]

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from utils.logger import setup_logger
from utils.cookie_utils import sanitize_cookies

logger = setup_logger("CookieFetcher")


async def capture_cookies(args: Any) -> Dict[str, str]:
    """
    Mở trình duyệt Chromium Playwright có giao diện để người dùng truy cập Douyin/TikTok,
    giải captcha hoặc đăng nhập, sau đó tự động bắt toàn bộ cookie và lưu vào cấu hình.
    """
    url = getattr(args, "url", "https://www.douyin.com/") or "https://www.douyin.com/"
    headless = bool(getattr(args, "headless", False))
    config_path = Path(getattr(args, "config", "config.yml"))
    output_path = getattr(args, "output", None)
    if output_path:
        output_path = Path(output_path)

    logger.info("Bắt đầu mở trình duyệt để lấy cookie từ: %s", url)

    try:
        from playwright.async_api import async_playwright
        from utils.helpers import ensure_playwright_chromium, launch_playwright_browser_async
        ensure_playwright_chromium()
    except Exception as exc:
        logger.error("Không thể khởi tạo Playwright: %s", exc)
        return {}

    is_tiktok = "tiktok.com" in url.lower()
    profile_dir_name = ".tiktok_profile" if is_tiktok else ".douyin_profile"
    profile_dir = Path(profile_dir_name).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    captured_cookies: Dict[str, str] = {}

    try:
        async with async_playwright() as pw:
            # Sử dụng persistent context để lưu trữ phiên làm việc lâu dài
            context = await launch_playwright_browser_async(
                pw.chromium,
                is_persistent=True,
                user_data_dir=str(profile_dir),
                headless=headless,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            page = context.pages[0] if context.pages else await context.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                logger.warning("Goto timeout hoặc lỗi nhẹ, tiếp tục: %s", e)

            # Lắng nghe cookie trong tối đa 120 giây hoặc khi đóng tab
            poll_interval = 2.0
            max_wait = 180.0
            elapsed = 0.0

            target_domain = "tiktok.com" if is_tiktok else "douyin.com"

            while elapsed < max_wait:
                if page.is_closed() or (hasattr(context, "is_closed") and context.is_closed()):
                    logger.info("Người dùng đã đóng trình duyệt, tiến hành lưu các cookie hiện có.")
                    break

                try:
                    all_ck = await context.cookies()
                    matched = {}
                    for c in all_ck:
                        c_dom = (c.get("domain") or "").lower()
                        if target_domain in c_dom:
                            matched[c["name"]] = c["value"]

                    # Kiểm tra các trường cookie quan trọng
                    has_essentials = (
                        ("ttwid" in matched or "odin_tt" in matched or "sessionid" in matched)
                        if not is_tiktok
                        else ("sessionid" in matched or "ttwid" in matched)
                    )

                    if has_essentials:
                        captured_cookies = matched
                        # Nếu đã có đủ cookie và người dùng đang ở trang chủ/user (không còn ở trang captcha)
                        title = ""
                        try:
                            title = await page.title()
                        except Exception:
                            pass
                        if "验证码" not in title and len(matched) >= 3:
                            captured_cookies = matched
                except Exception as exc:
                    logger.debug("Lỗi đọc cookie tạm thời: %s", exc)

                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            # Đọc lại lần cuối trước khi đóng
            try:
                all_ck = await context.cookies()
                for c in all_ck:
                    c_dom = (c.get("domain") or "").lower()
                    if target_domain in c_dom:
                        captured_cookies[c["name"]] = c["value"]
            except Exception:
                pass

            try:
                await context.close()
            except Exception:
                pass

    except Exception as exc:
        logger.error("Lỗi trong quá trình capture_cookies: %s", exc)

    if not captured_cookies:
        logger.warning("Không thu thập được cookie nào từ trình duyệt.")
        return {}

    sanitized = sanitize_cookies(captured_cookies)
    logger.info("Đã thu thập thành công %d cookie từ %s", len(sanitized), target_domain)

    # Lưu vào output file nếu có
    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(sanitized, f, indent=2, ensure_ascii=False)
            logger.info("Đã lưu cookie vào tệp: %s", output_path)
        except Exception as e:
            logger.error("Lỗi khi ghi tệp cookie %s: %e", output_path, e)

    # Lưu vào .cookies.json trong thư mục gốc nếu là Douyin
    if not is_tiktok:
        root_ck_path = Path(".cookies.json")
        try:
            with open(root_ck_path, "w", encoding="utf-8") as f:
                json.dump(sanitized, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Lỗi ghi .cookies.json: %s", e)

    # Cập nhật vào config.yml
    if config_path.exists():
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            if not is_tiktok:
                existing_ck = cfg.get("cookies") or {}
                if isinstance(existing_ck, dict):
                    existing_ck.update(sanitized)
                    cfg["cookies"] = existing_ck
                else:
                    cfg["cookies"] = sanitized
                cfg["cookie_mode"] = "custom"
            else:
                ytdlp_cfg = cfg.get("ytdlp") or {}
                # Với tiktok, lưu vào cookie_contents hoặc cookies
                cfg["ytdlp"] = ytdlp_cfg

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

            logger.info("Đã cập nhật cookies vào %s thành công!", config_path)
        except Exception as e:
            logger.error("Lỗi cập nhật config.yml: %s", e)

    # Đồng bộ sang CookieManager
    try:
        from auth import CookieManager
        cm = CookieManager()
        cm.set_cookies(sanitized)
    except Exception as e:
        logger.debug("Lỗi cập nhật CookieManager: %s", e)

    return sanitized

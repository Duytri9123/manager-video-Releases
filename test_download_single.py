"""
Test script: download a single Douyin video using cookies in .cookies.json
Usage: python test_download_single.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from core.api_client import DouyinAPIClient
from core.downloader_factory import DownloaderFactory
from core.url_parser import URLParser
from config import ConfigLoader
from storage import Database, FileManager
from auth import CookieManager
from utils.logger import setup_logger

logger = setup_logger("TestDownload")

DOUYIN_URL = (
    "https://www.douyin.com/user/MS4wLjABAAAAMC3i_rotfLZf8dFXF7nE5v_9NKcMzVQFf3t0ohI4IrmGarPop-DtwKd-oPZZFfbO"
    "?from_tab_name=main&modal_id=7664212957689089289"
)
COOKIES_PATH = Path(".cookies.json")
OUTPUT_DIR = Path("Downloaded")


async def main():
    # ── 1. Load cookies ──────────────────────────────────────────────────────
    with open(COOKIES_PATH, encoding="utf-8") as f:
        cookies = json.load(f)
    print(f"[✓] Loaded {len(cookies)} cookies: {list(cookies.keys())}")

    # ── 2. Parse URL (static, no cookies needed) ─────────────────────────────
    parsed = URLParser.parse(DOUYIN_URL)
    if not parsed:
        print("[✗] URL parse failed — unsupported format")
        return

    url_type  = parsed.get("type")
    aweme_id  = parsed.get("aweme_id")
    sec_uid   = parsed.get("sec_uid", "")
    print(f"[✓] Parsed → type={url_type}  aweme_id={aweme_id}  sec_uid={sec_uid[:30]}…")

    # ── 3. Test API: fetch video detail ──────────────────────────────────────
    async with DouyinAPIClient(cookies=cookies) as client:
        print(f"\n[…] Fetching video detail for aweme_id={aweme_id} …")
        detail = await client.get_video_detail(aweme_id)
        if not detail:
            print("[✗] Could not retrieve video detail — cookie may be invalid or expired")
            return

        author    = detail.get("author", {})
        desc      = detail.get("desc", "")
        video_obj = detail.get("video", {})
        play_addr = video_obj.get("play_addr", {})
        url_list  = play_addr.get("url_list", [])

        print(f"[✓] Video detail retrieved!")
        print(f"    Author  : {author.get('nickname', 'unknown')}")
        print(f"    Caption : {desc[:100]}")
        print(f"    Play URLs: {len(url_list)} candidate(s)")
        if url_list:
            print(f"    First   : {url_list[0][:100]}…")

    # ── 4. Full download via DownloaderFactory ───────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n[…] Starting download to {OUTPUT_DIR.resolve()} …")

    config = ConfigLoader()
    config._config["save_dir"] = str(OUTPUT_DIR)

    cookie_manager = CookieManager(cookies)
    api_client     = DouyinAPIClient(cookies=cookies)
    file_manager   = FileManager(config)
    database       = Database()

    downloader = DownloaderFactory.create(
        url_type=url_type,
        config=config,
        api_client=api_client,
        file_manager=file_manager,
        cookie_manager=cookie_manager,
        database=database,
    )

    if not downloader:
        print(f"[✗] No downloader available for type={url_type}")
        await api_client.close()
        return

    result = await downloader.download(parsed)
    await api_client.close()

    print(f"\n{'='*50}")
    print(f"[Result] total={result.total}  success={result.success}  "
          f"failed={result.failed}  skipped={result.skipped}")
    if result.success:
        print("[✓] Download completed successfully!")
    elif result.skipped:
        print("[i] Video was already downloaded previously (skipped).")
    else:
        print("[✗] Download failed — check logs above for details")


if __name__ == "__main__":
    asyncio.run(main())

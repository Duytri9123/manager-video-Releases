import json
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse

from auth import CookieManager
from config import ConfigLoader
from control import QueueManager, RateLimiter, RetryHandler
from core.api_client import DouyinAPIClient
from core.transcript_manager import TranscriptManager
from storage import Database, FileManager, MetadataHandler
from utils.logger import setup_logger
from utils.translation import translate_texts
from utils.validators import sanitize_filename

logger = setup_logger("BaseDownloader")


class ProgressReporter(Protocol):
    def update_step(self, step: str, detail: str = "") -> None:
        ...

    def set_item_total(self, total: int, detail: str = "") -> None:
        ...

    def advance_item(self, status: str, detail: str = "") -> None:
        ...

    def update_post_progress(self, pct: int, label: str = "") -> None:
        ...


class DownloadResult:
    def __init__(self):
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0

    def __str__(self):
        return f"Total: {self.total}, Success: {self.success}, Failed: {self.failed}, Skipped: {self.skipped}"


class BaseDownloader(ABC):
    def __init__(
        self,
        config: ConfigLoader,
        api_client: DouyinAPIClient,
        file_manager: FileManager,
        cookie_manager: CookieManager,
        database: Optional[Database] = None,
        rate_limiter: Optional[RateLimiter] = None,
        retry_handler: Optional[RetryHandler] = None,
        queue_manager: Optional[QueueManager] = None,
        progress_reporter: Optional[ProgressReporter] = None,
    ):
        self.config = config
        self.api_client = api_client
        self.file_manager = file_manager
        self.cookie_manager = cookie_manager
        self.database = database
        self.rate_limiter = rate_limiter or RateLimiter()
        self.retry_handler = retry_handler or RetryHandler()
        thread_count = int(self.config.get("thread", 5) or 5)
        self.queue_manager = queue_manager or QueueManager(max_workers=thread_count)
        self.progress_reporter = progress_reporter
        self.metadata_handler = MetadataHandler()
        self.transcript_manager = TranscriptManager(
            self.config, self.file_manager, self.database
        )
        self._local_aweme_ids: Optional[set[str]] = None
        self._local_aweme_legacy_scan_done = False
        self._aweme_id_pattern = re.compile(r"(?<!\d)(\d{15,20})(?!\d)")
        self._local_media_suffixes = {
            ".mp4",
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".mp3",
            ".m4a",
        }
        # 控制终端错误日志量，避免进度条被大量日志打断后出现重复重绘。
        self._download_error_log_count = 0
        self._download_error_log_limit = 5
        self._translated_title_cache: Dict[str, str] = {}

    def _progress_update_step(self, step: str, detail: str = "") -> None:
        if not self.progress_reporter:
            return
        try:
            self.progress_reporter.update_step(step, detail)
        except Exception as exc:
            logger.debug("Progress update_step failed: %s", exc)

    def _progress_set_item_total(self, total: int, detail: str = "") -> None:
        if not self.progress_reporter:
            return
        try:
            self.progress_reporter.set_item_total(total, detail)
        except Exception as exc:
            logger.debug("Progress set_item_total failed: %s", exc)

    def _progress_advance_item(self, status: str, detail: str = "") -> None:
        if not self.progress_reporter:
            return
        try:
            self.progress_reporter.advance_item(status, detail)
        except Exception as exc:
            logger.debug("Progress advance_item failed: %s", exc)

    def _progress_post(self, pct: int, label: str = "") -> None:
        if not self.progress_reporter:
            return
        updater = getattr(self.progress_reporter, "update_post_progress", None)
        if not callable(updater):
            return
        try:
            updater(int(pct), label)
        except Exception as exc:
            logger.debug("Progress update_post_progress failed: %s", exc)

    def _log_download_error(self, log_fn, message: str) -> None:
        if self._download_error_log_count < self._download_error_log_limit:
            log_fn(message)
        elif self._download_error_log_count == self._download_error_log_limit:
            logger.error(
                "Too many download errors, suppressing further per-file logs..."
            )
        self._download_error_log_count += 1

    def _download_headers(self, user_agent: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Referer": f"{self.api_client.BASE_URL}/",
            "Origin": self.api_client.BASE_URL,
            "Accept": "*/*",
        }

        headers["User-Agent"] = user_agent or self.api_client.headers.get(
            "User-Agent", ""
        )
        return headers

    @abstractmethod
    async def download(self, parsed_url: Dict[str, Any]) -> DownloadResult:
        pass

    async def _should_download(self, aweme_id: str) -> bool:
        in_local = self._is_locally_downloaded(aweme_id)
        in_db = False
        if self.database:
            in_db = await self.database.is_downloaded(aweme_id)

        if in_db and in_local:
            return False

        if in_db and not in_local:
            logger.info(
                "Aweme %s exists in database but media file not found locally, retry download",
                aweme_id,
            )
            return True

        if in_local:
            logger.info("Aweme %s already exists locally, skipping", aweme_id)
            return False

        return True

    def _is_locally_downloaded(self, aweme_id: str) -> bool:
        if not aweme_id:
            return False

        if self._local_aweme_ids is None:
            self._build_local_aweme_index()

        if self._local_aweme_ids is None:
            return False

        if aweme_id in self._local_aweme_ids:
            return True

        if not self._local_aweme_legacy_scan_done:
            self._local_aweme_legacy_scan_done = True
            self._scan_local_aweme_files()

        return aweme_id in self._local_aweme_ids

    def _build_local_aweme_index(self):
        self._local_aweme_ids = set()
        self._load_local_aweme_ids_from_manifest()

    def _load_local_aweme_ids_from_manifest(self) -> None:
        manifest_path = self.file_manager.base_path / "download_manifest.jsonl"
        if not manifest_path.exists():
            return

        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                for raw_line in manifest_file:
                    line = raw_line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    aweme_id = str(record.get("aweme_id") or "").strip()
                    if not aweme_id or aweme_id in self._local_aweme_ids:
                        continue

                    if self._manifest_record_has_existing_file(record):
                        self._local_aweme_ids.add(aweme_id)

            logger.debug(
                "Loaded %d aweme id(s) from download manifest",
                len(self._local_aweme_ids),
            )
        except OSError as exc:
            logger.warning("Failed to read download manifest %s: %s", manifest_path, exc)

    def _manifest_record_has_existing_file(self, record: Dict[str, Any]) -> bool:
        file_paths = record.get("file_paths")
        if not isinstance(file_paths, list):
            return False

        for file_path in file_paths:
            if not isinstance(file_path, str) or not file_path.strip():
                continue

            candidate = Path(file_path)
            if not candidate.is_absolute():
                candidate = self.file_manager.base_path / candidate

            if self.file_manager.file_exists(candidate):
                return True

        return False

    def _scan_local_aweme_files(self) -> None:
        base_path = self.file_manager.base_path
        if not base_path.exists():
            return

        scanned_ids = 0
        for path in base_path.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in self._local_media_suffixes:
                continue
            try:
                if path.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            for match in self._aweme_id_pattern.finditer(path.name):
                self._local_aweme_ids.add(match.group(1))
                scanned_ids += 1

        logger.debug(
            "Loaded local aweme index from filesystem fallback, current size=%d, matches=%d",
            len(self._local_aweme_ids),
            scanned_ids,
        )

    def _mark_local_aweme_downloaded(self, aweme_id: str):
        if not aweme_id:
            return

        if self._local_aweme_ids is None:
            self._local_aweme_ids = set()
        self._local_aweme_ids.add(aweme_id)

    def _filter_by_time(self, aweme_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        start_time = self.config.get("start_time")
        end_time = self.config.get("end_time")

        if not start_time and not end_time:
            return aweme_list

        start_ts = (
            int(datetime.strptime(start_time, "%Y-%m-%d").timestamp())
            if start_time
            else None
        )
        end_ts = (
            int(datetime.strptime(end_time, "%Y-%m-%d").timestamp())
            if end_time
            else None
        )

        filtered: List[Dict[str, Any]] = []
        for aweme in aweme_list:
            create_time = aweme.get("create_time", 0)
            if start_ts is not None and create_time < start_ts:
                continue
            if end_ts is not None and create_time > end_ts:
                continue
            filtered.append(aweme)

        return filtered

    def _limit_count(
        self, aweme_list: List[Dict[str, Any]], mode: str
    ) -> List[Dict[str, Any]]:
        number_config = self.config.get("number", {})
        limit = number_config.get(mode, 0)

        if limit > 0:
            return aweme_list[:limit]
        return aweme_list

    async def _download_aweme_assets(
        self,
        aweme_data: Dict[str, Any],
        author_name: str,
        mode: Optional[str] = None,
    ) -> bool:
        aweme_id = aweme_data.get("aweme_id")
        if not aweme_id:
            logger.error("Missing aweme_id in aweme data")
            return False

        desc_raw = (aweme_data.get("desc", "no_title") or "").strip() or "no_title"
        custom_titles = self.config.get("custom_titles") or {}
        custom_title = (custom_titles.get(aweme_id) or "").strip()
        desc = custom_title if custom_title else self._resolve_naming_title(desc_raw)
        publish_ts, publish_date = self._resolve_publish_time(
            aweme_data.get("create_time")
        )
        if not publish_date:
            publish_date = datetime.now().strftime("%Y-%m-%d")
            logger.warning(
                "Aweme %s missing/invalid create_time, fallback to current date %s",
                aweme_id,
                publish_date,
            )
        # File stem: tên_video_id (không có ngày) — dễ check trùng khi tải lại
        file_stem = sanitize_filename(f"{desc}_{aweme_id}")

        save_dir = self.file_manager.get_save_path(
            author_name=author_name,
            mode=mode,
            aweme_title=desc,
            aweme_id=aweme_id,
            folderstyle=self.config.get("folderstyle", True),
            download_date="",  # Không dùng ngày trong tên thư mục
        )
        downloaded_files: List[Path] = []

        session = await self.api_client.get_session()
        video_path: Optional[Path] = None

        media_type = self._detect_media_type(aweme_data)
        if media_type == "video":
            video_info = self._build_no_watermark_url(aweme_data)
            if not video_info:
                logger.error("No playable video URL found for aweme %s", aweme_id)
                return False

            video_url, video_headers = video_info
            video_path = save_dir / f"{file_stem}.mp4"
            if not await self._download_with_retry(
                video_url, video_path, session, headers=video_headers
            ):
                return False
            downloaded_files.append(video_path)

            if self.config.get("cover"):
                cover_url = self._extract_first_url(
                    aweme_data.get("video", {}).get("cover")
                )
                if cover_url:
                    cover_path = save_dir / f"{file_stem}_cover.jpg"
                    if await self._download_with_retry(
                        cover_url,
                        cover_path,
                        session,
                        headers=self._download_headers(),
                        optional=True,
                    ):
                        downloaded_files.append(cover_path)

            if self.config.get("music"):
                music_url = self._extract_first_url(
                    aweme_data.get("music", {}).get("play_url")
                )
                if music_url:
                    music_path = save_dir / f"{file_stem}_music.mp3"
                    if await self._download_with_retry(
                        music_url,
                        music_path,
                        session,
                        headers=self._download_headers(),
                        optional=True,
                    ):
                        downloaded_files.append(music_path)

        elif media_type == "gallery":
            image_urls = self._collect_image_urls(aweme_data)
            image_live_urls = self._collect_image_live_urls(aweme_data)
            logger.info(
                "Gallery aweme %s: %d image(s), %d live photo(s)",
                aweme_id,
                len(image_urls),
                len(image_live_urls),
            )
            if not image_urls and not image_live_urls:
                logger.error(
                    "No gallery assets found for aweme %s (aweme_type=%s, "
                    "has image_post_info=%s, has images=%s)",
                    aweme_id,
                    aweme_data.get("aweme_type"),
                    "image_post_info" in aweme_data,
                    "images" in aweme_data,
                )
                return False

            for index, image_url in enumerate(image_urls, start=1):
                suffix = self._infer_image_extension(image_url)
                image_path = save_dir / f"{file_stem}_{index}{suffix}"
                download_result = await self._download_with_retry(
                    image_url,
                    image_path,
                    session,
                    headers=self._download_headers(),
                    prefer_response_content_type=True,
                    return_saved_path=True,
                )
                if not download_result:
                    logger.error(
                        f"Failed downloading image {index} for aweme {aweme_id}"
                    )
                    return False
                downloaded_files.append(
                    download_result if isinstance(download_result, Path) else image_path
                )

            for index, live_url in enumerate(image_live_urls, start=1):
                suffix = Path(urlparse(live_url).path).suffix or ".mp4"
                live_path = save_dir / f"{file_stem}_live_{index}{suffix}"
                success = await self._download_with_retry(
                    live_url,
                    live_path,
                    session,
                    headers=self._download_headers(),
                )
                if not success:
                    logger.error(
                        f"Failed downloading live image {index} for aweme {aweme_id}"
                    )
                    return False
                downloaded_files.append(live_path)
        else:
            logger.error("Unsupported media type for aweme %s: %s", aweme_id, media_type)
            return False

        if self.config.get("avatar"):
            author = aweme_data.get("author", {})
            avatar_url = self._extract_first_url(author.get("avatar_larger"))
            if avatar_url:
                avatar_path = save_dir / f"{file_stem}_avatar.jpg"
                if await self._download_with_retry(
                    avatar_url,
                    avatar_path,
                    session,
                    headers=self._download_headers(),
                    optional=True,
                ):
                    downloaded_files.append(avatar_path)

        if self.config.get("json"):
            json_path = save_dir / f"{file_stem}_data.json"
            if await self.metadata_handler.save_metadata(aweme_data, json_path):
                downloaded_files.append(json_path)

        author = aweme_data.get("author", {})
        if self.database:
            metadata_json = json.dumps(aweme_data, ensure_ascii=False)
            await self.database.add_aweme(
                {
                    "aweme_id": aweme_id,
                    "aweme_type": media_type,
                    "title": desc,
                    "author_id": author.get("uid"),
                    "author_name": author.get("nickname", author_name),
                    "create_time": aweme_data.get("create_time"),
                    "file_path": str(save_dir),
                    "metadata": metadata_json,
                }
            )

        manifest_record = {
            "date": publish_date,
            "aweme_id": aweme_id,
            "author_name": author.get("nickname", author_name),
            "desc": desc_raw,
            "desc_naming": desc,
            "media_type": media_type,
            "tags": self._extract_tags(aweme_data),
            "file_names": [path.name for path in downloaded_files],
            "file_paths": [self._to_manifest_path(path) for path in downloaded_files],
        }
        if publish_ts:
            manifest_record["publish_timestamp"] = publish_ts
        await self.metadata_handler.append_download_manifest(
            self.file_manager.base_path, manifest_record
        )

        if media_type == "video" and video_path is not None:
            transcript_result = await self.transcript_manager.process_video(
                video_path, aweme_id=aweme_id
            )
            transcript_status = transcript_result.get("status")
            if transcript_status == "skipped":
                logger.info(
                    "Transcript skipped for aweme %s: %s",
                    aweme_id,
                    transcript_result.get("reason", "unknown"),
                )
            elif transcript_status == "failed":
                logger.warning(
                    "Transcript failed for aweme %s: %s",
                    aweme_id,
                    transcript_result.get("error", "unknown"),
                )

            # ── Post-download video processing (subtitle burn + voice) ──────
            vp_cfg = self.config.get("video_process") or {}
            if vp_cfg.get("enabled") and video_path.exists():
                self._progress_post(5, "Bắt đầu hậu xử lý video")
                await self._run_video_processor(video_path, vp_cfg, aweme_id)
                self._progress_post(100, "Hoàn tất hậu xử lý")
            else:
                self._progress_post(0, "Hậu xử lý tắt")

        # ── Auto-upload to TikTok / YouTube ──────────────────────────────────
        if media_type == "video" and video_path is not None and video_path.exists():
            upload_cfg = self.config.get("upload") or {}
            if upload_cfg.get("auto_upload"):
                platform = str(upload_cfg.get("platform") or "").lower()
                await self._auto_upload(video_path, desc, platform, upload_cfg)

        self._mark_local_aweme_downloaded(aweme_id)
        logger.info("Downloaded %s: %s (%s)", media_type, desc, aweme_id)
        return True

    def _resolve_naming_title(self, desc_raw: str) -> str:
        trans_cfg = self.config.get("translation") or {}
        if not trans_cfg.get("naming_enabled"):
            return desc_raw

        normalized = (desc_raw or "").strip() or "no_title"
        if normalized in self._translated_title_cache:
            return self._translated_title_cache[normalized]

        preferred_provider = trans_cfg.get("preferred_provider", "auto")
        translated, used_provider = translate_texts([normalized], trans_cfg, preferred_provider)
        translated_title = (translated[0] if translated else "").strip() or normalized
        self._translated_title_cache[normalized] = translated_title

        if translated_title != normalized:
            logger.info("Translated naming title via %s", used_provider)

        return translated_title

    async def _download_with_retry(
        self,
        url: str,
        save_path: Path,
        session,
        *,
        headers: Optional[Dict[str, str]] = None,
        optional: bool = False,
        prefer_response_content_type: bool = False,
        return_saved_path: bool = False,
    ) -> bool | Path:
        async def _task():
            download_result = await self.file_manager.download_file(
                url,
                save_path,
                session,
                headers=headers,
                proxy=getattr(self.api_client, "proxy", None),
                prefer_response_content_type=prefer_response_content_type,
                return_saved_path=return_saved_path,
            )
            if not download_result:
                raise RuntimeError(f"Download failed for {url}")
            return download_result

        try:
            return await self.retry_handler.execute_with_retry(_task)
        except Exception as error:
            log_fn = logger.warning if optional else logger.error
            self._log_download_error(
                log_fn,
                f"Download error for {save_path.name}: {error}",
            )
            return False

    # aweme_type codes that indicate image/note content
    _GALLERY_AWEME_TYPES = {2, 68, 150}

    def _detect_media_type(self, aweme_data: Dict[str, Any]) -> str:
        if (
            aweme_data.get("image_post_info")
            or aweme_data.get("images")
            or aweme_data.get("image_list")
        ):
            return "gallery"
        aweme_type = aweme_data.get("aweme_type")
        if isinstance(aweme_type, int) and aweme_type in self._GALLERY_AWEME_TYPES:
            logger.info(
                "Detected gallery via aweme_type=%s for aweme %s",
                aweme_type,
                aweme_data.get("aweme_id"),
            )
            return "gallery"
        return "video"

    def _build_no_watermark_url(
        self, aweme_data: Dict[str, Any]
    ) -> Optional[Tuple[str, Dict[str, str]]]:
        video = aweme_data.get("video", {})
        play_addr = video.get("play_addr", {})
        url_candidates = [c for c in (play_addr.get("url_list") or []) if c]
        url_candidates.sort(key=lambda u: 0 if "watermark=0" in u else 1)

        fallback_candidate: Optional[Tuple[str, Dict[str, str]]] = None

        for candidate in url_candidates:
            parsed = urlparse(candidate)
            headers = self._download_headers()

            if parsed.netloc.endswith("douyin.com"):
                if "X-Bogus=" not in candidate:
                    signed_url, ua = self.api_client.sign_url(candidate)
                    headers = self._download_headers(user_agent=ua)
                    return signed_url, headers
                return candidate, headers

            fallback_candidate = (candidate, headers)

        # Prefer direct CDN URLs (e.g. douyinvod.com) over the /aweme/v1/play/
        # signed endpoint: the latter redirects to a URL that returns 403 Forbidden.
        if fallback_candidate:
            return fallback_candidate

        uri = (
            play_addr.get("uri")
            or video.get("vid")
            or video.get("download_addr", {}).get("uri")
        )
        if uri:
            params = {
                "video_id": uri,
                "ratio": "1080p",
                "line": "0",
                "is_play_url": "1",
                "watermark": "0",
                "source": "PackSourceEnum_PUBLISH",
            }
            signed_url, ua = self.api_client.build_signed_path(
                "/aweme/v1/play/", params
            )
            return signed_url, self._download_headers(user_agent=ua)

        return None

    def _collect_image_urls(self, aweme_data: Dict[str, Any]) -> List[str]:
        image_urls = []
        gallery_items = self._iter_gallery_items(aweme_data)
        for item in gallery_items:
            if not isinstance(item, dict):
                continue
            image_url = self._pick_first_media_url(
                item.get("download_url"),
                item.get("download_addr"),
                item.get("download_url_list"),
                item,
                item.get("display_image"),
                item.get("owner_watermark_image"),
            )
            if image_url:
                image_urls.append(image_url)
        if not image_urls:
            logger.warning(
                "No image URLs extracted for aweme %s; gallery items count=%d",
                aweme_data.get("aweme_id"),
                len(gallery_items),
            )
        return self._deduplicate_urls(image_urls)

    def _collect_image_live_urls(self, aweme_data: Dict[str, Any]) -> List[str]:
        live_urls: List[str] = []
        for item in self._iter_gallery_items(aweme_data):
            if not isinstance(item, dict):
                continue
            video = item.get("video") if isinstance(item.get("video"), dict) else {}
            live_url = self._pick_first_media_url(
                video.get("play_addr"),
                video.get("download_addr"),
                item.get("video_play_addr"),
                item.get("video_download_addr"),
            )
            if live_url:
                live_urls.append(live_url)
        return self._deduplicate_urls(live_urls)

    @staticmethod
    def _iter_gallery_items(aweme_data: Dict[str, Any]) -> List[Any]:
        image_post = aweme_data.get("image_post_info")
        if isinstance(image_post, dict):
            for key in ("images", "image_list"):
                candidate = image_post.get(key)
                if isinstance(candidate, list) and candidate:
                    return candidate
        images = aweme_data.get("images") or aweme_data.get("image_list") or []
        if isinstance(images, list):
            return images
        return []

    @staticmethod
    def _deduplicate_urls(urls: List[str]) -> List[str]:
        deduped: List[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    @staticmethod
    def _pick_first_media_url(*sources: Any) -> Optional[str]:
        for source in sources:
            candidate = BaseDownloader._extract_first_url(source)
            if candidate:
                return candidate
        return None

    @staticmethod
    def _extract_first_url(source: Any) -> Optional[str]:
        if isinstance(source, dict):
            url_list = source.get("url_list")
            if isinstance(url_list, list) and url_list:
                first_item = url_list[0]
                if isinstance(first_item, str) and first_item:
                    return first_item
        elif isinstance(source, list) and source:
            first_item = source[0]
            if isinstance(first_item, str) and first_item:
                return first_item
        elif isinstance(source, str) and source:
            return source
        return None

    @staticmethod
    def _infer_image_extension(image_url: str) -> str:
        allowed_exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        if not image_url:
            return ".jpg"

        image_path = (urlparse(image_url).path or "").lower()
        raw_suffix = Path(image_path).suffix.lower()
        if raw_suffix in allowed_exts:
            return raw_suffix

        matches = re.findall(r"\.(?:jpe?g|png|webp|gif)(?=[^a-z0-9]|$)", image_path)
        if matches:
            return matches[-1].lower()

        return ".jpg"

    @staticmethod
    def _resolve_publish_time(create_time: Any) -> Tuple[Optional[int], str]:
        if create_time in (None, ""):
            return None, ""

        try:
            publish_ts = int(create_time)
            if publish_ts <= 0:
                return None, ""
            return publish_ts, datetime.fromtimestamp(publish_ts).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError, OverflowError):
            return None, ""

    @staticmethod
    def _extract_tags(aweme_data: Dict[str, Any]) -> List[str]:
        tags: List[str] = []

        def _append_tag(raw_tag: Any):
            if not raw_tag:
                return
            normalized_tag = str(raw_tag).strip().lstrip("#")
            if normalized_tag and normalized_tag not in tags:
                tags.append(normalized_tag)

        for item in aweme_data.get("text_extra") or []:
            if not isinstance(item, dict):
                continue
            _append_tag(item.get("hashtag_name"))
            _append_tag(item.get("tag_name"))

        for item in aweme_data.get("cha_list") or []:
            if not isinstance(item, dict):
                continue
            _append_tag(item.get("cha_name"))
            _append_tag(item.get("name"))

        desc = aweme_data.get("desc") or ""
        for hashtag in re.findall(r"#([^\s#]+)", desc):
            _append_tag(hashtag)

        return tags

    def _to_manifest_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.file_manager.base_path))
        except ValueError:
            return str(path)

    async def _auto_upload(self, video_path: Path, title: str, platform: str, upload_cfg: dict) -> None:
        """Auto-upload a downloaded video to TikTok or YouTube."""
        if platform == "tiktok":
            tiktok_cfg = upload_cfg.get("tiktok") or {}
            client_key = str(tiktok_cfg.get("client_key") or "").strip()
            client_secret = str(tiktok_cfg.get("client_secret") or "").strip()
            if not client_key or not client_secret:
                logger.warning("auto_upload: TikTok client_key/secret missing, skipping")
                return
            try:
                from tools.tiktok_uploader import TikTokUploader
                uploader = TikTokUploader()
                if not uploader.authenticate(client_key, client_secret):
                    logger.warning("auto_upload: TikTok not authenticated, skipping upload for %s", video_path.name)
                    return
                caption_tpl = str(tiktok_cfg.get("caption_template") or tiktok_cfg.get("title_template") or "{title}")
                caption = caption_tpl.replace("{title}", title)
                
                # Extract hashtags from filename
                import re
                stem = video_path.stem
                chinese_parts = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F_]*', stem)
                hashtags = []
                if chinese_parts:
                    try:
                        hashtags = ['#' + part.replace(' ', '').lower() for part in chinese_parts]
                    except:
                        hashtags = ['#' + part.replace(' ', '') for part in chinese_parts]
                
                if hashtags:
                    caption += ' ' + ' '.join(hashtags)
                
                privacy = str(tiktok_cfg.get("privacy_status") or "SELF_ONLY").upper()
                privacy_map = {"private": "SELF_ONLY", "public": "PUBLIC_TO_EVERYONE", "friends": "MUTUAL_FOLLOW_FRIENDS"}
                privacy = privacy_map.get(privacy.lower(), privacy)
                result = uploader.upload_video(
                    video_path=str(video_path),
                    title=caption,
                    privacy_level=privacy,
                    on_progress=lambda s: logger.info("TikTok upload: %s", s.get("log", "")),
                )
                if result:
                    logger.info("auto_upload: TikTok upload OK publish_id=%s for %s", result.get("publish_id"), video_path.name)
                else:
                    logger.warning("auto_upload: TikTok upload failed for %s: %s", video_path.name, uploader.last_error)
            except Exception as exc:
                logger.error("auto_upload: TikTok exception for %s: %s", video_path.name, exc)

        elif platform == "youtube":
            yt_cfg = upload_cfg.get("youtube") or {}
            try:
                from tools.youtube_uploader import YouTubeUploader
                uploader = YouTubeUploader()
                if not uploader.credentials and not uploader.authenticate():
                    logger.warning("auto_upload: YouTube not authenticated, skipping upload for %s", video_path.name)
                    return
                title_tpl = str(yt_cfg.get("title_template") or "{title}")
                yt_title = title_tpl.replace("{title}", title)
                desc_tpl = str(yt_cfg.get("description_template") or "{title}")
                yt_desc = desc_tpl.replace("{title}", title)
                privacy = str(yt_cfg.get("privacy_status") or "private")
                is_short = bool(yt_cfg.get("short", False))
                
                # Extract hashtags from filename
                import re
                stem = video_path.stem
                chinese_parts = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F_]*', stem)
                hashtags = []
                if chinese_parts:
                    # Try to translate, fallback to original
                    try:
                        # For simplicity, use original Chinese as hashtags
                        hashtags = ['#' + part.replace(' ', '').lower() for part in chinese_parts]
                    except:
                        hashtags = ['#' + part.replace(' ', '') for part in chinese_parts]
                
                default_tags = ['douyin', 'tiktok', 'video']
                all_tags = default_tags + [h[1:] for h in hashtags]  # remove #
                
                result = uploader.upload_video(
                    video_path=video_path,
                    title=yt_title,
                    description=yt_desc,
                    tags=all_tags,
                    privacy_status=privacy,
                    is_short=is_short,
                    on_progress=lambda s: logger.info("YouTube upload: %s", s),
                )
                if result:
                    logger.info("auto_upload: YouTube upload OK url=%s for %s", result.get("url"), video_path.name)
                else:
                    logger.warning("auto_upload: YouTube upload failed for %s", video_path.name)
            except Exception as exc:
                logger.error("auto_upload: YouTube exception for %s: %s", video_path.name, exc)
        else:
            logger.warning("auto_upload: unknown platform '%s', skipping", platform)

    async def _import_to_capcut(
        self,
        video_path: Path,
        srt_path: Optional[Path],
        project_name: str,
        capcut_cfg: dict,
        aweme_id: str,
    ) -> None:
        """Import video và SRT vào CapCut draft folder."""
        try:
            from tools.capcut_importer import CapCutImporter
            
            capcut_path = capcut_cfg.get("capcut_path") or None
            auto_open = capcut_cfg.get("auto_open", False)
            
            importer = CapCutImporter(capcut_path=capcut_path)
            result = importer.import_video(
                video_path=video_path,
                srt_path=srt_path,
                project_name=project_name,
                auto_open=auto_open,
            )
            
            if result.get("success"):
                logger.info(
                    "capcut_import: successfully imported %s to CapCut (project: %s)",
                    aweme_id,
                    result.get("project_name"),
                )
                self._progress_post(100, f"Đã import vào CapCut: {project_name}")
            else:
                logger.warning(
                    "capcut_import: failed for %s: %s",
                    aweme_id,
                    result.get("message"),
                )
                self._progress_post(100, "Import CapCut thất bại")
        
        except Exception as e:
            logger.error("capcut_import: error for %s: %s", aweme_id, e)
            self._progress_post(100, "Import CapCut gặp lỗi")

    async def _run_video_processor(
        self, video_path: Path, vp_cfg: dict, aweme_id: str
    ) -> None:
        """Run post-download video processing: burn subtitles + optional voice conversion."""
        from core.video_processor import (
            find_ffmpeg, transcribe_to_srt, burn_subtitles, convert_voice
        )

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            logger.warning("video_process: ffmpeg not found, skipping for %s", aweme_id)
            self._progress_post(100, "Thiếu ffmpeg, bỏ qua hậu xử lý")
            return

        try:
            import whisper  # noqa: F401
        except ImportError:
            logger.warning("video_process: openai-whisper not installed, skipping for %s", aweme_id)
            self._progress_post(100, "Thiếu openai-whisper, bỏ qua hậu xử lý")
            return

        logger.info("video_process: starting for %s", aweme_id)
        out_dir = video_path.parent
        stem = video_path.stem

        custom_titles = self.config.get("custom_titles") or {}
        custom_title = (custom_titles.get(aweme_id) or "").strip()
        if custom_title:
            post_title = sanitize_filename(custom_title)
        else:
            no_date = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", stem)
            no_id = re.sub(rf"_{re.escape(aweme_id)}$", "", no_date)
            post_title = sanitize_filename(no_id or stem)
        post_title = post_title or sanitize_filename(stem)

        burn_original_subs = bool(vp_cfg.get("burn_subs"))
        burn_vi_subs = bool(vp_cfg.get("burn_vi_subs"))
        voice_convert = bool(vp_cfg.get("voice_convert"))
        translate_enabled = bool(vp_cfg.get("translate_subs", vp_cfg.get("translate", True)))

        if not (burn_original_subs or burn_vi_subs or voice_convert):
            logger.info("video_process: no post-process steps enabled for %s", aweme_id)
            self._progress_post(100, "Không bật hậu xử lý")
            return

        raw_srt_path = out_dir / f"{stem}.srt"
        vi_srt_path = None

        # Step 1: Transcribe → SRT
        self._progress_post(15, "Đang tạo phụ đề gốc")
        try:
            srt_path, segments = transcribe_to_srt(
                video_path=video_path,
                ffmpeg=ffmpeg,
                model_name=vp_cfg.get("model", vp_cfg.get("whisper_model", "base")),
                language=vp_cfg.get("language", "zh"),
                out_srt=raw_srt_path,
            )
        except Exception as e:
            logger.warning("video_process: transcription failed for %s: %s", aweme_id, e)
            self._progress_post(100, "Tạo phụ đề thất bại")
            return

        if not segments:
            logger.info("video_process: no speech detected for %s", aweme_id)
            self._progress_post(100, "Không phát hiện lời nói")
            return

        logger.info("video_process: transcribed %d segments for %s", len(segments), aweme_id)

        # Step 2: Translate ZH → VI if needed
        translated_texts: list = []
        need_translation = translate_enabled or burn_vi_subs or voice_convert
        if need_translation:
            self._progress_post(40, "Đang dịch phụ đề")
            try:
                from utils.translation import translate_texts
                trans_cfg = self.config.get("translation") or {}
                provider = trans_cfg.get("preferred_provider", "auto")
                texts = [seg.get("text", "").strip() for seg in segments]
                translated_texts, used = translate_texts(texts, trans_cfg, provider)
                logger.info("video_process: translated %d segments via %s", len(translated_texts), used)

                # Write VI SRT
                if translated_texts and burn_vi_subs:
                    from core.video_processor import _fmt_srt_time
                    vi_srt_path = out_dir / f"{post_title}_vi.srt"
                    vi_lines = []
                    for i, (seg, vi_text) in enumerate(zip(segments, translated_texts), 1):
                        if vi_text and vi_text.strip():
                            vi_lines.append(
                                f"{i}\n{_fmt_srt_time(seg['start'])} --> {_fmt_srt_time(seg['end'])}\n{vi_text}\n"
                            )
                    vi_srt_path.write_text("\n".join(vi_lines), encoding="utf-8")
                    if burn_vi_subs:
                        srt_path = vi_srt_path
                self._progress_post(60, "Dịch phụ đề hoàn tất")
            except Exception as e:
                logger.warning("video_process: translation failed for %s: %s", aweme_id, e)
                self._progress_post(60, "Dịch phụ đề lỗi, dùng phụ đề gốc")

        # Step 3: Burn subtitles + blur original text
        processed_path = None
        if burn_original_subs and srt_path and srt_path.exists():
            self._progress_post(75, "Đang burn phụ đề")
            out_video = out_dir / f"{post_title}_processed.mp4"
            # Đồng bộ blur_zone với subtitle_position nếu blur_zone là mặc định hoặc rỗng
            subtitle_position = vp_cfg.get("subtitle_position", "bottom")
            blur_zone = vp_cfg.get("blur_zone")
            if not blur_zone or blur_zone == "default":
                blur_zone = subtitle_position
            # Đồng bộ margin_v với subtitle_position nếu margin_v là mặc định hoặc rỗng
            margin_v = vp_cfg.get("margin_v")
            if margin_v is None or str(margin_v).strip() == "":
                if subtitle_position == "top":
                    margin_v = 60
                else:
                    margin_v = 20
            else:
                margin_v = int(margin_v)
            ok, err = burn_subtitles(
                video_path=video_path,
                srt_path=srt_path,
                output_path=out_video,
                ffmpeg=ffmpeg,
                blur_original=vp_cfg.get("blur_original", True),
                blur_zone=blur_zone,
                blur_height_pct=float(vp_cfg.get("blur_height_pct", 15)) / 100,
                font_size=int(vp_cfg.get("font_size", 18)),
                font_color=vp_cfg.get("font_color", "white"),
                outline_color=vp_cfg.get("outline_color", "black"),
                outline_width=int(vp_cfg.get("outline_width", 2)),
                margin_v=margin_v,
                subtitle_position=subtitle_position,
                font_name=vp_cfg.get("font_name", "Arial"),
            )
            if ok:
                processed_path = out_video
                logger.info("video_process: subtitles burned → %s", out_video.name)
                self._progress_post(85, "Burn phụ đề xong")
            else:
                logger.warning("video_process: subtitle burn failed for %s: %s", aweme_id, err)
                self._progress_post(85, "Burn phụ đề lỗi")

        # Step 4: Voice conversion ZH → VI
        voice_out = None
        if voice_convert and translated_texts and segments:
            self._progress_post(90, "Đang tạo giọng tiếng Việt")
            source = processed_path if processed_path else video_path
            voice_out = out_dir / f"{post_title}_vi_voice.mp4"
            # Lấy đúng engine và voice từ config
            tts_voice = vp_cfg.get("tts_voice") or "vi-VN-HoaiMyNeural"
            tts_engine = vp_cfg.get("tts_engine") or "edge-tts"
            elevenlabs_api_key = (
                str(vp_cfg.get("elevenlabs_api_key") or "").strip()
                or os.environ.get("ELEVENLABS_API_KEY", "").strip()
            )
            elevenlabs_voice_id = str(vp_cfg.get("elevenlabs_voice_id") or "").strip()
            try:
                ok, err = await convert_voice(
                    video_path=source,
                    segments=segments,
                    translated_texts=translated_texts,
                    output_path=voice_out,
                    ffmpeg=ffmpeg,
                    tts_voice=tts_voice,
                    tts_engine=tts_engine,
                    keep_bg_music=vp_cfg.get("keep_bg_music", vp_cfg.get("keep_bg", True)),
                    bg_volume=float(vp_cfg.get("bg_volume", 0.15)),
                    elevenlabs_api_key=elevenlabs_api_key,
                    elevenlabs_voice_id=elevenlabs_voice_id,
                )
                if ok:
                    logger.info("video_process: voice converted → %s", voice_out.name)
                    self._progress_post(100, f"Đã tạo giọng tiếng Việt ({tts_engine}, {tts_voice})")
                else:
                    logger.warning("video_process: voice conversion failed for %s: %s", aweme_id, err)
                    self._progress_post(100, "Đổi giọng thất bại")
            except Exception as e:
                logger.warning("video_process: voice conversion error for %s: %s", aweme_id, e)
                self._progress_post(100, "Đổi giọng gặp lỗi")

        # Keep only processed + voice outputs when both subtitle burn and voice are enabled.
        if burn_original_subs and voice_convert and processed_path and voice_out and voice_out.exists():
            keep_files = {processed_path.resolve(), voice_out.resolve()}
            cleanup_candidates = {
                video_path,
                raw_srt_path,
                srt_path,
                vi_srt_path,
                out_dir / f"{stem}_processed.mp4",
                out_dir / f"{stem}_vi_voice.mp4",
                out_dir / f"{stem}_vi.srt",
            }
            for path in cleanup_candidates:
                if not path:
                    continue
                p = Path(path)
                if not p.exists() or p.resolve() in keep_files:
                    continue
                try:
                    p.unlink()
                except Exception as e:
                    logger.debug("video_process: cleanup skipped for %s: %s", p, e)

        logger.info("video_process: done for %s", aweme_id)
        
        # Step 5: Auto-import to CapCut if enabled
        capcut_cfg = self.config.get("capcut") or {}
        if capcut_cfg.get("enabled") and capcut_cfg.get("auto_import"):
            self._progress_post(95, "Đang import vào CapCut")
            await self._import_to_capcut(
                video_path=voice_out if voice_out and voice_out.exists() else (processed_path or video_path),
                srt_path=vi_srt_path or raw_srt_path,
                project_name=post_title,
                capcut_cfg=capcut_cfg,
                aweme_id=aweme_id,
            )

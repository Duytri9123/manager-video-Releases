#!/usr/bin/env python3
"""YouTube uploader using OAuth 2.0"""
import os
import pickle
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import googleapiclient.discovery
import googleapiclient.errors

logger = logging.getLogger(__name__)

# Local dev callback uses http://localhost. OAuthlib requires this opt-in.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Scopes for YouTube API
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
]

class YouTubeUploader:
    """Upload videos to YouTube using OAuth 2.0."""
    
    def __init__(self, client_secrets_file: str = "client_secrets.json", tokens_dir: str = ".youtube_tokens",
                 account_id: Optional[str] = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.client_secrets_file = (self.base_dir / client_secrets_file).resolve()
        self.credentials = None
        self.youtube = None
        self.last_error = ""
        self._pending_flow = None
        self._pending_state = ""
        self._pending_auth_url = ""
        self._account_id = account_id

        # Multi-account support: use account-specific token paths if available
        if account_id:
            try:
                from auth.account_manager import get_youtube_account_manager
                mgr = get_youtube_account_manager()
                self.token_file = mgr.get_token_path(account_id)
                self.token_json_file = mgr.get_token_json_path(account_id)
                self.tokens_dir = self.token_file.parent
            except Exception:
                self.tokens_dir = (self.base_dir / tokens_dir).resolve()
                self.tokens_dir.mkdir(parents=True, exist_ok=True)
                self.token_file = self.tokens_dir / "youtube_token.pickle"
                self.token_json_file = self.base_dir / "youtube_token.json"
        else:
            # Try to use active account from account manager
            try:
                from auth.account_manager import get_youtube_account_manager
                mgr = get_youtube_account_manager()
                active = mgr.get_active_account()
                if active:
                    self._account_id = active["id"]
                    _mgr_token = mgr.get_token_path(active["id"])
                    _mgr_json = mgr.get_token_json_path(active["id"])
                    # Only use account manager paths if token actually exists there
                    if _mgr_token.exists() or _mgr_json.exists():
                        self.token_file = _mgr_token
                        self.token_json_file = _mgr_json
                        self.tokens_dir = _mgr_token.parent
                    else:
                        # Token not in account manager dir — use legacy paths
                        self.tokens_dir = (self.base_dir / tokens_dir).resolve()
                        self.tokens_dir.mkdir(parents=True, exist_ok=True)
                        self.token_file = self.tokens_dir / "youtube_token.pickle"
                        self.token_json_file = self.base_dir / "youtube_token.json"
                else:
                    # No active account in manager — use legacy paths
                    self.tokens_dir = (self.base_dir / tokens_dir).resolve()
                    self.tokens_dir.mkdir(parents=True, exist_ok=True)
                    self.token_file = self.tokens_dir / "youtube_token.pickle"
                    self.token_json_file = self.base_dir / "youtube_token.json"
            except Exception:
                self.tokens_dir = (self.base_dir / tokens_dir).resolve()
                self.tokens_dir.mkdir(parents=True, exist_ok=True)
                self.token_file = self.tokens_dir / "youtube_token.pickle"
                self.token_json_file = self.base_dir / "youtube_token.json"
    
    def _load_credentials(self) -> Optional[Credentials]:
        """Load saved credentials from file."""
        if self.token_file.exists():
            with open(self.token_file, 'rb') as f:
                creds = pickle.load(f)
                if isinstance(creds, Credentials):
                    return creds

        if self.token_json_file.exists():
            try:
                return Credentials.from_authorized_user_file(str(self.token_json_file), SCOPES)
            except Exception:
                pass
        return None
    
    def _save_credentials(self, credentials: Credentials):
        """Save credentials to file."""
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        with open(self.token_file, 'wb') as f:
            pickle.dump(credentials, f)

        # Keep a JSON token alongside the pickle so other tools in the workspace
        # can reuse the same OAuth session.
        with open(self.token_json_file, 'w', encoding='utf-8') as f:
            f.write(credentials.to_json())

        # Register in multi-account system
        self._register_account_if_needed()

    def _register_account_if_needed(self):
        """Register this account in the multi-account manager after successful auth."""
        try:
            from auth.account_manager import get_youtube_account_manager
            mgr = get_youtube_account_manager()
            channel = self.get_channel_info() if self.youtube else {}
            channel_id = channel.get("id", "")
            channel_title = channel.get("title", "")
            thumbnail = channel.get("thumbnail", "")
            account_id = self._account_id or channel_id or "default"
            name = channel_title or f"YouTube ({account_id[:12]})"
            if account_id:
                mgr.add_account(account_id, name, channel_id, channel_title, thumbnail)
                self._account_id = account_id
        except Exception as e:
            logger.debug("Could not register account: %s", e)

    def authenticate(self, force_refresh: bool = False) -> bool:
        """
        Authenticate with YouTube API.
        Returns True if successful.
        """
        try:
            self.last_error = ""
            # Try loading saved credentials
            if force_refresh:
                # force_refresh is handled by revoke + OAuth URL flow from API layer.
                return False

            self.credentials = self._load_credentials()
            if self.credentials and self.credentials.valid:
                self.youtube = googleapiclient.discovery.build(
                    'youtube', 'v3', credentials=self.credentials
                )
                return True

            # Refresh if expired
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                self.credentials.refresh(Request())
                self._save_credentials(self.credentials)
                self.youtube = googleapiclient.discovery.build(
                    'youtube', 'v3', credentials=self.credentials
                )
                return True

            if self.credentials:
                self.last_error = "YouTube token has expired or cannot be refreshed. Please sign in again."

            return False
        
        except Exception as e:
            self.last_error = str(e)
            print(f"Authentication error: {e}")
            return False
    
    def get_auth_url(self) -> Optional[str]:
        """
        Get OAuth authorization URL for manual auth.
        Returns the URL user should visit.
        """
        try:
            self.last_error = ""

            # If an OAuth flow is already pending, reuse it to keep state stable
            # while the frontend polls auth status.
            if self._pending_flow and self._pending_state and self._pending_auth_url:
                return self._pending_auth_url

            if not self.client_secrets_file.exists():
                self.last_error = f"client_secrets.json not found at {self.client_secrets_file}"
                return None

            # Detect actual server port from environment or default to 5000
            _port = int(os.environ.get("FLASK_PORT", 5000))
            _redirect_uri = f'http://localhost:{_port}/oauth2callback'

            # Use Flow (web server flow) instead of InstalledAppFlow to ensure
            # redirect_uri is respected and not overridden with port 8080.
            flow = Flow.from_client_secrets_file(
                str(self.client_secrets_file),
                scopes=SCOPES,
                redirect_uri=_redirect_uri,
            )

            auth_url, state = flow.authorization_url(
                access_type='offline',
                prompt='consent',
                include_granted_scopes='true',
            )
            self._pending_flow = flow
            self._pending_state = str(state or "")
            self._pending_auth_url = str(auth_url or "")
            return auth_url
        except Exception as e:
            self.last_error = str(e)
            print(f"Error getting auth URL: {e}")
            return None

    def complete_auth_callback(self, callback_url: str, state: str = "") -> bool:
        """Exchange OAuth callback code for tokens."""
        try:
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
            self.last_error = ""
            if not self._pending_flow:
                self.last_error = "OAuth state expired. Please click Đăng nhập YouTube again."
                return False

            if self._pending_state and state and self._pending_state != str(state):
                self.last_error = "OAuth state mismatch"
                return False

            self._pending_flow.fetch_token(authorization_response=callback_url)
            self.credentials = self._pending_flow.credentials
            if not self.credentials:
                self.last_error = "Failed to obtain OAuth credentials"
                return False

            self._save_credentials(self.credentials)
            self.youtube = googleapiclient.discovery.build('youtube', 'v3', credentials=self.credentials)
            self._pending_flow = None
            self._pending_state = ""
            self._pending_auth_url = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"Error completing auth callback: {e}")
            return False
    
    def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str = "",
        tags: list = None,
        category_id: str = "22",  # 22 = People & Blogs
        privacy_status: str = "private",  # private, unlisted, public
        is_short: bool = False,
        publish_at: str = None,  # ISO 8601 string: YYYY-MM-DDThh:mm:ss.sZ
        on_progress: callable = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Upload video to YouTube.
        
        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of video tags
            category_id: YouTube category ID
            privacy_status: 'private', 'unlisted', or 'public'
            is_short: Whether to upload as a YouTube Short.
                      If True and video is not 9:16, auto-converts to vertical format.
            publish_at: ISO 8601 formatted datetime string for scheduling.
                        Requires privacy_status='private'.
            on_progress: Callback function(status, pct) for progress tracking
        
        Returns:
            Video info dict with 'id', 'url', etc. on success, None on failure
        """
        if not self.youtube:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        
        try:
            video_path = Path(video_path)
            if not video_path.exists():
                raise FileNotFoundError(f"Video file not found: {video_path}")
            
            # ── Auto-convert to 9:16 for YouTube Shorts ──────────────────────
            upload_path = video_path
            _tmp_vertical = None
            if is_short:
                logger.info("[Upload] YouTube Shorts mode — kiểm tra định dạng video")
                upload_path, _tmp_vertical = self._ensure_vertical_for_shorts(video_path, on_progress)
                # Save the 9:16 file permanently in the same directory as the original
                if _tmp_vertical and Path(_tmp_vertical).exists() and _tmp_vertical != video_path:
                    saved_vertical = video_path.parent / f"{video_path.stem}_9x16.mp4"
                    if not saved_vertical.exists():
                        import shutil as _sh
                        _sh.copy2(str(_tmp_vertical), str(saved_vertical))
                        logger.info("[Upload] 💾 Lưu file 9:16: %s", saved_vertical.name)
            
            # Add #Shorts to title if is_short and not already present
            if is_short and '#Shorts' not in title and '#shorts' not in title:
                title = title[:92] + ' #Shorts'  # Keep within 100 char limit
            
            logger.info("[Upload] Bắt đầu upload: %s → YouTube (%s)", upload_path.name, privacy_status)
            logger.info("[Upload] Title: %s", title[:80])
            
            # Build request body
            body = {
                'snippet': {
                    'title': title[:100],  # YouTube limit
                    'description': description[:5000],
                    'tags': tags or [],
                    'categoryId': category_id,
                    'defaultLanguage': 'vi',
                },
                'status': {
                    'privacyStatus': privacy_status,
                    'embeddable': True,
                    'publicStatsViewable': True,
                },
            }
            
            if publish_at and privacy_status == 'private':
                # Validate and normalize to RFC 3339 with .000Z suffix
                # YouTube requires: YYYY-MM-DDThh:mm:ss.000Z (UTC, at least 5 min future)
                from datetime import datetime, timezone, timedelta
                try:
                    # Parse ISO string (handles both with/without milliseconds)
                    dt_str = publish_at.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(dt_str)
                    # Ensure UTC
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    # Must be at least 5 minutes in the future
                    min_time = datetime.now(timezone.utc) + timedelta(minutes=5)
                    if dt > min_time:
                        # Format exactly as YouTube expects: 2026-05-09T10:30:00.000Z
                        body['status']['publishAt'] = dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                    # If not far enough in future, skip scheduling (upload as private)
                except Exception:
                    pass  # Invalid date — skip scheduling, upload as private
            
            # Create resumable upload
            file_size_mb = upload_path.stat().st_size / 1024 / 1024
            logger.info("[Upload] File: %s (%.1f MB), bắt đầu upload chunked...", upload_path.name, file_size_mb)
            request = self.youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=googleapiclient.http.MediaFileUpload(
                    str(upload_path),
                    chunksize=1024 * 1024,  # 1MB chunks
                    resumable=True,
                    mimetype='video/mp4'
                )
            )
            
            # Execute with progress tracking + retry on transient network errors
            import socket
            import time

            _RETRYABLE_ERRORS = (
                ConnectionError,
                TimeoutError,
                socket.error,
                OSError,  # covers WinError 10053, 10054, etc.
            )
            _MAX_RETRIES = 5
            _RETRY_DELAYS = [5, 10, 20, 30, 60]

            response = None
            percent_complete = 0
            upload_start = time.time()

            while response is None:
                for attempt in range(_MAX_RETRIES):
                    try:
                        status, response = request.next_chunk()
                        if status:
                            percent_complete = int(status.progress() * 100)
                            if on_progress:
                                on_progress({'status': 'uploading', 'pct': percent_complete})
                        break  # success — exit retry loop
                    except googleapiclient.errors.HttpError as e:
                        if e.resp.status in (500, 502, 503, 504):
                            # Server-side transient error — retry
                            if attempt < _MAX_RETRIES - 1:
                                delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                                logger.warning("[Upload] Server error %d, retry %d/%d in %ds",
                                               e.resp.status, attempt+1, _MAX_RETRIES, delay)
                                if on_progress:
                                    on_progress({'status': 'retrying', 'pct': percent_complete,
                                                 'message': f"Server error {e.resp.status}, retry {attempt+1}/{_MAX_RETRIES} in {delay}s"})
                                time.sleep(delay)
                                continue
                        logger.error("[Upload] ✗ HTTP error: %s", e)
                        if on_progress:
                            on_progress({'status': 'error', 'message': str(e)})
                        raise RuntimeError(f"Upload failed: {e}")
                    except _RETRYABLE_ERRORS as e:
                        if attempt < _MAX_RETRIES - 1:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            logger.warning("[Upload] Network error: %s, retry %d/%d in %ds",
                                           e, attempt+1, _MAX_RETRIES, delay)
                            if on_progress:
                                on_progress({'status': 'retrying', 'pct': percent_complete,
                                             'message': f"Network error: {e}, retry {attempt+1}/{_MAX_RETRIES} in {delay}s"})
                            time.sleep(delay)
                        else:
                            logger.error("[Upload] ✗ Network error sau %d lần retry: %s", _MAX_RETRIES, e)
                            if on_progress:
                                on_progress({'status': 'error', 'message': str(e)})
                            raise
            
            upload_time = time.time() - upload_start
            if on_progress:
                on_progress({'status': 'success', 'pct': 100})
            
            # Cleanup temp vertical file if created
            if _tmp_vertical and Path(_tmp_vertical).exists():
                try:
                    Path(_tmp_vertical).unlink()
                    logger.info("[Upload] Đã xóa file tạm: %s", Path(_tmp_vertical).name)
                except Exception:
                    pass
            
            video_id = response['id']
            video_url = f'https://youtu.be/{video_id}'
            logger.info("[Upload] ✓ Upload thành công trong %.1fs: %s", upload_time, video_url)
            logger.info("[Upload] Video ID: %s | Privacy: %s | Short: %s", video_id, privacy_status, is_short)
            return {
                'id': video_id,
                'url': video_url,
                'title': title,
                'status': privacy_status,
            }
        
        except Exception as e:
            # Cleanup temp vertical file on error too
            if _tmp_vertical and Path(_tmp_vertical).exists():
                try:
                    Path(_tmp_vertical).unlink()
                except Exception:
                    pass
            logger.error("[Upload] ✗ Upload thất bại: %s", e)
            if on_progress:
                on_progress({'status': 'error', 'message': str(e)})
            raise

    def _ensure_vertical_for_shorts(
        self,
        video_path: Path,
        on_progress: callable = None,
    ) -> tuple:
        """
        Check if video is suitable for YouTube Shorts (9:16 vertical, ≤60s).
        If video is horizontal/square, convert to 9:16 with blurred background.
        
        Returns:
            (upload_path, tmp_file_path_or_None)
            If no conversion needed, returns (video_path, None).
            If converted, returns (new_path, new_path) — caller should cleanup.
        """
        import subprocess
        import re
        import tempfile

        video_path = Path(video_path)
        logger.info("[Shorts] Kiểm tra định dạng video: %s", video_path.name)

        # Find ffmpeg
        ffmpeg = None
        for name in ("ffmpeg", "ffmpeg.exe"):
            import shutil as _sh
            found = _sh.which(name)
            if found:
                ffmpeg = found
                break
        if not ffmpeg:
            logger.warning("[Shorts] Không tìm thấy ffmpeg — bỏ qua convert, upload nguyên bản")
            return video_path, None

        # Get video dimensions and duration
        try:
            r = subprocess.run(
                [ffmpeg, "-i", str(video_path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            info = r.stderr or ""
            # Parse dimensions
            m_dim = re.search(r"(\d{2,5})x(\d{2,5})", info)
            src_w, src_h = (int(m_dim.group(1)), int(m_dim.group(2))) if m_dim else (0, 0)
            # Parse duration
            m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", info)
            duration = 0.0
            if m_dur:
                duration = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + int(m_dur.group(3)) + int(m_dur.group(4)) / 100
        except Exception as e:
            logger.error("[Shorts] Không đọc được thông tin video: %s", e)
            return video_path, None

        if src_w == 0 or src_h == 0:
            logger.warning("[Shorts] Không xác định được kích thước video")
            return video_path, None

        logger.info("[Shorts] Video gốc: %dx%d, thời lượng: %.1fs", src_w, src_h, duration)

        # Check if already vertical (9:16 or taller)
        aspect = src_w / src_h
        if aspect <= 0.625:  # Already 9:16 or narrower
            logger.info("[Shorts] Video đã là dọc (%.2f:1) — không cần convert", aspect)
            return video_path, None

        # Video is horizontal or square — convert to 9:16
        logger.info("[Shorts] Video ngang/vuông (%.2f:1) — đang convert sang 9:16...", aspect)
        if on_progress:
            on_progress({'status': 'converting', 'pct': 0,
                         'message': f'Converting to 9:16 for Shorts ({src_w}x{src_h} → 1080x1920)...'})

        # Target: 1080x1920 (9:16)
        target_w = 1080
        target_h = 1920

        # Scale video to fit width, center on black background
        scaled_h = int(target_w * src_h / src_w)
        scaled_h = scaled_h + (scaled_h % 2)  # ensure even
        y_offset = (target_h - scaled_h) // 2

        logger.info("[Shorts] Layout: video %dx%d đặt tại y=%d, nền đen 1080x1920",
                    target_w, scaled_h, y_offset)

        # Filter: black background + video centered (no blur — fast)
        filter_complex = (
            f"color=black:{target_w}x{target_h}:r=30[bg];"
            f"[0:v]scale={target_w}:{scaled_h}[fg];"
            f"[bg][fg]overlay=0:{y_offset}:shortest=1[vout]"
        )

        logger.info("[Shorts] Filter: %s", filter_complex)

        # Output to temp file
        tmp_out = video_path.parent / f"{video_path.stem}_shorts_9x16.mp4"

        # Keep full duration — YouTube will handle Shorts eligibility
        logger.info("[Shorts] Encode: libx264 veryfast crf=23, giữ nguyên thời lượng → %s",
                    tmp_out.name)

        cmd = [
            ffmpeg, "-i", str(video_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(tmp_out), "-y", "-loglevel", "error"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0 and tmp_out.exists() and tmp_out.stat().st_size > 0:
                out_size = tmp_out.stat().st_size / 1024 / 1024
                logger.info("[Shorts] ✓ Convert thành công: %s (%.1f MB)", tmp_out.name, out_size)
                if on_progress:
                    on_progress({'status': 'converted', 'pct': 0,
                                 'message': f'Converted to 9:16: {tmp_out.name} ({out_size:.1f} MB)'})
                return tmp_out, tmp_out
            else:
                err_msg = result.stderr[:200] if result.stderr else "unknown error"
                logger.error("[Shorts] ✗ FFmpeg thất bại (code=%d): %s", result.returncode, err_msg)
        except subprocess.TimeoutExpired:
            logger.error("[Shorts] ✗ FFmpeg timeout (>300s)")
        except Exception as e:
            logger.error("[Shorts] ✗ Lỗi convert: %s", e)

        # Conversion failed — upload original
        if tmp_out.exists():
            try:
                tmp_out.unlink()
            except Exception:
                pass
        logger.warning("[Shorts] Upload video gốc (không convert)")
        return video_path, None

    def get_channel_info(self) -> Optional[Dict[str, Any]]:
        """Get authenticated channel info."""
        if not self.youtube:
            return None
        
        try:
            request = self.youtube.channels().list(
                part='snippet,statistics',
                mine=True
            )
            response = request.execute()
            if response['items']:
                ch = response['items'][0]
                # Pick the best thumbnail available
                thumbs = ch['snippet'].get('thumbnails', {})
                thumbnail = (
                    thumbs.get('medium', {}).get('url') or
                    thumbs.get('default', {}).get('url') or
                    ''
                )
                return {
                    'id': ch['id'],
                    'title': ch['snippet']['title'],
                    'description': ch['snippet']['description'],
                    'subscribers': ch['statistics'].get('subscriberCount', 'hidden'),
                    'video_count': ch['statistics'].get('videoCount', '0'),
                    'thumbnail': thumbnail,
                }
        except Exception as e:
            print(f"Error getting channel info: {e}")
        
        return None

    def revoke_auth(self) -> bool:
        """Revoke OAuth token and delete saved credentials."""
        try:
            if self.token_file.exists():
                self.token_file.unlink()
            if self.token_json_file.exists():
                self.token_json_file.unlink()
            self.credentials = None
            self.youtube = None
            self._pending_flow = None
            self._pending_state = ""
            self._pending_auth_url = ""
            return True
        except Exception as e:
            print(f"Error revoking auth: {e}")
            return False

#!/usr/bin/env python3
"""YouTube uploader using OAuth 2.0"""
import os
import pickle
import json
from pathlib import Path
from typing import Optional, Dict, Any
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import googleapiclient.discovery
import googleapiclient.errors

# Local dev callback uses http://localhost. OAuthlib requires this opt-in.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Scopes for YouTube API
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube',
]

class YouTubeUploader:
    """Upload videos to YouTube using OAuth 2.0."""
    
    def __init__(self, client_secrets_file: str = "client_secrets.json", tokens_dir: str = ".youtube_tokens"):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.client_secrets_file = (self.base_dir / client_secrets_file).resolve()
        self.tokens_dir = (self.base_dir / tokens_dir).resolve()
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.tokens_dir / "youtube_token.pickle"
        self.token_json_file = self.base_dir / "youtube_token.json"
        self.credentials = None
        self.youtube = None
        self.last_error = ""
        self._pending_flow = None
        self._pending_state = ""
        self._pending_auth_url = ""
    
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
        with open(self.token_file, 'wb') as f:
            pickle.dump(credentials, f)

        # Keep a JSON token alongside the pickle so other tools in the workspace
        # can reuse the same OAuth session.
        with open(self.token_json_file, 'w', encoding='utf-8') as f:
            f.write(credentials.to_json())
    
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
            is_short: Whether to upload as a YouTube Short
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
            request = self.youtube.videos().insert(
                part='snippet,status',
                body=body,
                media_body=googleapiclient.http.MediaFileUpload(
                    str(video_path),
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
                                if on_progress:
                                    on_progress({'status': 'retrying', 'pct': percent_complete,
                                                 'message': f"Server error {e.resp.status}, retry {attempt+1}/{_MAX_RETRIES} in {delay}s"})
                                time.sleep(delay)
                                continue
                        if on_progress:
                            on_progress({'status': 'error', 'message': str(e)})
                        raise RuntimeError(f"Upload failed: {e}")
                    except _RETRYABLE_ERRORS as e:
                        if attempt < _MAX_RETRIES - 1:
                            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                            if on_progress:
                                on_progress({'status': 'retrying', 'pct': percent_complete,
                                             'message': f"Network error: {e}, retry {attempt+1}/{_MAX_RETRIES} in {delay}s"})
                            time.sleep(delay)
                        else:
                            if on_progress:
                                on_progress({'status': 'error', 'message': str(e)})
                            raise
            
            if on_progress:
                on_progress({'status': 'success', 'pct': 100})
            
            video_id = response['id']
            return {
                'id': video_id,
                'url': f'https://youtu.be/{video_id}',
                'title': title,
                'status': privacy_status,
            }
        
        except Exception as e:
            if on_progress:
                on_progress({'status': 'error', 'message': str(e)})
            raise

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
            self.credentials = None
            self.youtube = None
            self._pending_flow = None
            self._pending_state = ""
            self._pending_auth_url = ""
            return True
        except Exception as e:
            print(f"Error revoking auth: {e}")
            return False

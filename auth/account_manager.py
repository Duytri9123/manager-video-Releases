#!/usr/bin/env python3
"""
account_manager.py — Quản lý nhiều tài khoản YouTube và Facebook.

Mỗi tài khoản được lưu với ID riêng, cho phép:
  - Thêm/xóa/chuyển đổi tài khoản
  - Lưu token riêng cho từng account
  - Chọn account active khi upload
"""
import json
import logging
import os
import pickle
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = ROOT / ".accounts"
ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNTS_FILE = ACCOUNTS_DIR / "accounts.json"


# ── Account data structure ────────────────────────────────────────────────────

def _load_accounts() -> dict:
    """Load accounts registry."""
    try:
        if ACCOUNTS_FILE.exists():
            return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load accounts: %s", e)
    return {"youtube": [], "facebook": [], "active": {"youtube": None, "facebook": None}}


def _save_accounts(data: dict):
    """Save accounts registry."""
    try:
        ACCOUNTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Failed to save accounts: %s", e)


def _ensure_structure(data: dict) -> dict:
    """Ensure accounts data has correct structure."""
    if "youtube" not in data:
        data["youtube"] = []
    if "facebook" not in data:
        data["facebook"] = []
    if "active" not in data:
        data["active"] = {"youtube": None, "facebook": None}
    return data


# ── YouTube Multi-Account ─────────────────────────────────────────────────────

class YouTubeAccountManager:
    """Quản lý nhiều tài khoản YouTube."""

    def __init__(self):
        self.tokens_dir = ACCOUNTS_DIR / "youtube_tokens"
        self.tokens_dir.mkdir(parents=True, exist_ok=True)

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Liệt kê tất cả tài khoản YouTube đã kết nối."""
        data = _load_accounts()
        return data.get("youtube", [])

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Lấy tài khoản YouTube đang active."""
        data = _load_accounts()
        active_id = (data.get("active") or {}).get("youtube")
        if not active_id:
            accounts = data.get("youtube", [])
            return accounts[0] if accounts else None
        for acc in data.get("youtube", []):
            if acc.get("id") == active_id:
                return acc
        return None

    def set_active_account(self, account_id: str) -> bool:
        """Đặt tài khoản YouTube active."""
        data = _ensure_structure(_load_accounts())
        for acc in data["youtube"]:
            if acc["id"] == account_id:
                data["active"]["youtube"] = account_id
                _save_accounts(data)
                logger.info("YouTube active account set to: %s", acc.get("name", account_id))
                return True
        return False

    def add_account(self, account_id: str, name: str, channel_id: str = "",
                    channel_title: str = "", thumbnail: str = "") -> Dict[str, Any]:
        """Thêm tài khoản YouTube mới."""
        data = _ensure_structure(_load_accounts())

        # Check if already exists
        for acc in data["youtube"]:
            if acc["id"] == account_id:
                # Update info
                acc["name"] = name
                acc["channel_id"] = channel_id
                acc["channel_title"] = channel_title
                acc["thumbnail"] = thumbnail
                _save_accounts(data)
                return acc

        account = {
            "id": account_id,
            "name": name,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "thumbnail": thumbnail,
        }
        data["youtube"].append(account)

        # Set as active if first account
        if len(data["youtube"]) == 1:
            data["active"]["youtube"] = account_id

        _save_accounts(data)
        logger.info("YouTube account added: %s (%s)", name, account_id)
        return account

    def remove_account(self, account_id: str) -> bool:
        """Xóa tài khoản YouTube."""
        data = _ensure_structure(_load_accounts())
        original_len = len(data["youtube"])
        data["youtube"] = [a for a in data["youtube"] if a["id"] != account_id]

        if len(data["youtube"]) == original_len:
            return False

        # Clear active if removed
        if (data.get("active") or {}).get("youtube") == account_id:
            data["active"]["youtube"] = data["youtube"][0]["id"] if data["youtube"] else None

        # Remove token files
        token_pickle = self.tokens_dir / f"{account_id}.pickle"
        token_json = self.tokens_dir / f"{account_id}.json"
        for f in [token_pickle, token_json]:
            if f.exists():
                f.unlink()

        _save_accounts(data)
        logger.info("YouTube account removed: %s", account_id)
        return True

    def get_token_path(self, account_id: Optional[str] = None) -> Path:
        """Lấy đường dẫn token file cho account."""
        if not account_id:
            active = self.get_active_account()
            account_id = active["id"] if active else "default"
        return self.tokens_dir / f"{account_id}.pickle"

    def get_token_json_path(self, account_id: Optional[str] = None) -> Path:
        """Lấy đường dẫn token JSON file cho account."""
        if not account_id:
            active = self.get_active_account()
            account_id = active["id"] if active else "default"
        return self.tokens_dir / f"{account_id}.json"

    def migrate_existing_token(self):
        """Migrate token cũ (single account) sang multi-account system."""
        old_pickle = ROOT / ".youtube_tokens" / "youtube_token.pickle"
        old_json = ROOT / "youtube_token.json"

        if not old_pickle.exists() and not old_json.exists():
            return

        # Try to get channel info from existing token
        account_id = "migrated_default"
        name = "YouTube (migrated)"

        try:
            if old_json.exists():
                token_data = json.loads(old_json.read_text(encoding="utf-8"))
                # Use client_id as a rough identifier
                client_id = token_data.get("client_id", "")
                if client_id:
                    account_id = client_id[:20].replace(".", "_")
        except Exception:
            pass

        # Copy token files
        new_pickle = self.tokens_dir / f"{account_id}.pickle"
        new_json = self.tokens_dir / f"{account_id}.json"

        if old_pickle.exists() and not new_pickle.exists():
            shutil.copy2(str(old_pickle), str(new_pickle))
        if old_json.exists() and not new_json.exists():
            shutil.copy2(str(old_json), str(new_json))

        # Register account
        self.add_account(account_id, name)
        logger.info("Migrated existing YouTube token to multi-account system")


# ── Facebook Multi-Account ────────────────────────────────────────────────────

class FacebookAccountManager:
    """Quản lý nhiều tài khoản Facebook."""

    def __init__(self):
        self.tokens_dir = ACCOUNTS_DIR / "facebook_tokens"
        self.tokens_dir.mkdir(parents=True, exist_ok=True)

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Liệt kê tất cả tài khoản Facebook đã kết nối."""
        data = _load_accounts()
        return data.get("facebook", [])

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Lấy tài khoản Facebook đang active."""
        data = _load_accounts()
        active_id = (data.get("active") or {}).get("facebook")
        if not active_id:
            accounts = data.get("facebook", [])
            return accounts[0] if accounts else None
        for acc in data.get("facebook", []):
            if acc.get("id") == active_id:
                return acc
        return None

    def set_active_account(self, account_id: str) -> bool:
        """Đặt tài khoản Facebook active."""
        data = _ensure_structure(_load_accounts())
        for acc in data["facebook"]:
            if acc["id"] == account_id:
                data["active"]["facebook"] = account_id
                _save_accounts(data)
                logger.info("Facebook active account set to: %s", acc.get("name", account_id))
                return True
        return False

    def add_account(self, account_id: str, name: str, token: str,
                    pages: Optional[List[Dict]] = None, profile_pic: str = "") -> Dict[str, Any]:
        """Thêm tài khoản Facebook mới."""
        data = _ensure_structure(_load_accounts())

        # Check if already exists
        for acc in data["facebook"]:
            if acc["id"] == account_id:
                acc["name"] = name
                acc["pages"] = pages or []
                acc["profile_pic"] = profile_pic
                _save_accounts(data)
                # Save token separately
                self._save_token(account_id, token, pages)
                return acc

        account = {
            "id": account_id,
            "name": name,
            "pages": pages or [],
            "profile_pic": profile_pic,
        }
        data["facebook"].append(account)

        # Set as active if first account
        if len(data["facebook"]) == 1:
            data["active"]["facebook"] = account_id

        _save_accounts(data)
        self._save_token(account_id, token, pages)
        logger.info("Facebook account added: %s (%s)", name, account_id)
        return account

    def remove_account(self, account_id: str) -> bool:
        """Xóa tài khoản Facebook."""
        data = _ensure_structure(_load_accounts())
        original_len = len(data["facebook"])
        data["facebook"] = [a for a in data["facebook"] if a["id"] != account_id]

        if len(data["facebook"]) == original_len:
            return False

        # Clear active if removed
        if (data.get("active") or {}).get("facebook") == account_id:
            data["active"]["facebook"] = data["facebook"][0]["id"] if data["facebook"] else None

        # Remove token file
        token_file = self.tokens_dir / f"{account_id}.json"
        if token_file.exists():
            token_file.unlink()

        _save_accounts(data)
        logger.info("Facebook account removed: %s", account_id)
        return True

    def get_token(self, account_id: Optional[str] = None) -> dict:
        """Lấy token data cho account."""
        if not account_id:
            active = self.get_active_account()
            account_id = active["id"] if active else None
        if not account_id:
            return {}

        token_file = self.tokens_dir / f"{account_id}.json"
        try:
            if token_file.exists():
                return json.loads(token_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_token(self, account_id: str, token: str, pages: Optional[List[Dict]] = None):
        """Lưu token cho account."""
        token_file = self.tokens_dir / f"{account_id}.json"
        data = {"access_token": token, "pages": pages or []}
        token_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def migrate_existing_token(self):
        """Migrate token cũ (single account) sang multi-account system."""
        old_token_file = ROOT / ".facebook_token.json"
        if not old_token_file.exists():
            return

        try:
            old_data = json.loads(old_token_file.read_text(encoding="utf-8"))
            token = old_data.get("access_token") or old_data.get("token", "")
            if not token:
                return

            account_id = old_data.get("user_id") or "migrated_default"
            name = old_data.get("user_name") or "Facebook (migrated)"
            pages = old_data.get("pages", [])

            self.add_account(account_id, name, token, pages)
            logger.info("Migrated existing Facebook token to multi-account system")
        except Exception as e:
            logger.error("Failed to migrate Facebook token: %s", e)


# ── Singleton instances ───────────────────────────────────────────────────────

_youtube_account_mgr: Optional[YouTubeAccountManager] = None
_facebook_account_mgr: Optional[FacebookAccountManager] = None


def get_youtube_account_manager() -> YouTubeAccountManager:
    """Get YouTube account manager singleton."""
    global _youtube_account_mgr
    if _youtube_account_mgr is None:
        _youtube_account_mgr = YouTubeAccountManager()
    return _youtube_account_mgr


def get_facebook_account_manager() -> FacebookAccountManager:
    """Get Facebook account manager singleton."""
    global _facebook_account_mgr
    if _facebook_account_mgr is None:
        _facebook_account_mgr = FacebookAccountManager()
    return _facebook_account_mgr

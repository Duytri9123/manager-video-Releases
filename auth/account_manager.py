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

def _ensure_structure(data: dict) -> dict:
    """Ensure accounts data has correct structure."""
    for k in ("youtube", "facebook", "tiktok", "douyin"):
        if k not in data:
            data[k] = []
    if "active" not in data or not isinstance(data["active"], dict):
        data["active"] = {}
    for k in ("youtube", "facebook", "tiktok", "douyin"):
        if k not in data["active"]:
            data["active"][k] = None
    return data


def _load_accounts() -> dict:
    """Load accounts registry."""
    try:
        if ACCOUNTS_FILE.exists():
            data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
            return _ensure_structure(data)
    except Exception as e:
        logger.error("Failed to load accounts: %s", e)
    return {
        "youtube": [],
        "facebook": [],
        "tiktok": [],
        "douyin": [],
        "active": {"youtube": None, "facebook": None, "tiktok": None, "douyin": None}
    }


def _save_accounts(data: dict):
    """Save accounts registry."""
    try:
        ACCOUNTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Failed to save accounts: %s", e)


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


# ── TikTok Multi-Account ──────────────────────────────────────────────────────

class TikTokAccountManager:
    """Quản lý nhiều tài khoản TikTok (mỗi account có browser profile riêng)."""

    def __init__(self):
        self.profiles_dir = ACCOUNTS_DIR / "tiktok_profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.migrate_existing()
        except Exception:
            pass

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Liệt kê tất cả tài khoản TikTok đã kết nối."""
        data = _ensure_structure(_load_accounts())
        return data.get("tiktok", [])

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Lấy tài khoản TikTok đang active."""
        data = _ensure_structure(_load_accounts())
        active_id = (data.get("active") or {}).get("tiktok")
        accounts = data.get("tiktok", [])
        if not active_id:
            return accounts[0] if accounts else None
        for acc in accounts:
            if acc.get("id") == active_id:
                return acc
        return accounts[0] if accounts else None

    def set_active_account(self, account_id: str) -> bool:
        """Đặt tài khoản TikTok active."""
        data = _ensure_structure(_load_accounts())
        for acc in data["tiktok"]:
            if acc["id"] == account_id:
                data["active"]["tiktok"] = account_id
                _save_accounts(data)
                logger.info("TikTok active account set to: %s", acc.get("name", account_id))
                return True
        return False

    def add_account(self, account_id: str, name: str, username: str = "",
                    avatar: str = "", profile_dir: str = "") -> Dict[str, Any]:
        """Thêm hoặc cập nhật tài khoản TikTok."""
        data = _ensure_structure(_load_accounts())
        target_dir = profile_dir or str(self.profiles_dir / account_id)

        for acc in data["tiktok"]:
            if acc["id"] == account_id:
                acc["name"] = name
                if username:
                    acc["username"] = username
                if avatar:
                    acc["avatar"] = avatar
                if profile_dir:
                    acc["profile_dir"] = target_dir
                _save_accounts(data)
                return acc

        account = {
            "id": account_id,
            "name": name,
            "username": username,
            "avatar": avatar,
            "profile_dir": target_dir,
        }
        data["tiktok"].append(account)

        if len(data["tiktok"]) == 1 or not (data.get("active") or {}).get("tiktok"):
            data["active"]["tiktok"] = account_id

        _save_accounts(data)
        logger.info("TikTok account added: %s (%s)", name, account_id)
        return account

    def remove_account(self, account_id: str, delete_profile: bool = True) -> bool:
        """Xóa tài khoản TikTok."""
        data = _ensure_structure(_load_accounts())
        original_len = len(data["tiktok"])
        data["tiktok"] = [a for a in data["tiktok"] if a["id"] != account_id]

        if len(data["tiktok"]) == original_len:
            return False

        if (data.get("active") or {}).get("tiktok") == account_id:
            data["active"]["tiktok"] = data["tiktok"][0]["id"] if data["tiktok"] else None

        if delete_profile:
            acc_dir = self.profiles_dir / account_id
            if acc_dir.exists():
                try:
                    shutil.rmtree(str(acc_dir), ignore_errors=True)
                except Exception as e:
                    logger.warning("Could not delete TikTok profile dir %s: %s", acc_dir, e)

        _save_accounts(data)
        logger.info("TikTok account removed: %s", account_id)
        return True

    def get_profile_dir(self, account_id: Optional[str] = None) -> Path:
        """Lấy thư mục profile trình duyệt của account TikTok."""
        if not account_id:
            active = self.get_active_account()
            if active:
                account_id = active["id"]

        if account_id:
            data = _ensure_structure(_load_accounts())
            for acc in data.get("tiktok", []):
                if acc.get("id") == account_id:
                    pdir = acc.get("profile_dir")
                    if pdir:
                        p = Path(pdir)
                        if not p.is_absolute():
                            p = ROOT / p
                        p.mkdir(parents=True, exist_ok=True)
                        return p
            p = self.profiles_dir / account_id
            p.mkdir(parents=True, exist_ok=True)
            return p

        fallback = ROOT / ".tiktok_profile"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def migrate_existing(self):
        """Migrate .tiktok_profile cũ sang multi-account system."""
        old_profile = ROOT / ".tiktok_profile"
        data = _ensure_structure(_load_accounts())
        if old_profile.exists() and not data.get("tiktok"):
            self.add_account(
                account_id="tiktok_default",
                name="TikTok Mặc Định",
                username="",
                avatar="",
                profile_dir=str(old_profile)
            )
            logger.info("Migrated existing TikTok profile to multi-account system")


# ── Douyin Multi-Account ──────────────────────────────────────────────────────

class DouyinAccountManager:
    """Quản lý nhiều tài khoản Douyin và đồng bộ Cookie theo tài khoản active."""

    def __init__(self):
        self.accounts_dir = ACCOUNTS_DIR / "douyin_accounts"
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.migrate_existing()
        except Exception:
            pass

    def list_accounts(self) -> List[Dict[str, Any]]:
        """Liệt kê tất cả tài khoản Douyin đã kết nối."""
        data = _ensure_structure(_load_accounts())
        return data.get("douyin", [])

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        """Lấy tài khoản Douyin đang active."""
        data = _ensure_structure(_load_accounts())
        active_id = (data.get("active") or {}).get("douyin")
        accounts = data.get("douyin", [])
        if not active_id:
            return accounts[0] if accounts else None
        for acc in accounts:
            if acc.get("id") == active_id:
                return acc
        return accounts[0] if accounts else None

    def get_profile_dir(self) -> Path:
        """Reuse the active account's login profile for browser downloads."""
        account = self.get_active_account()
        if account:
            account_id = str(account.get("id") or "")
            if account_id and Path(account_id).name == account_id and account_id not in (".", ".."):
                profile = ROOT / ".accounts" / "douyin_profiles" / account_id
                if profile.is_dir():
                    return profile
        return ROOT / ".douyin_profile"

    def get_cookies(self, account_id: Optional[str] = None) -> Dict[str, str]:
        """Lấy cookies cho tài khoản cụ thể hoặc tài khoản active."""
        if not account_id:
            active = self.get_active_account()
            account_id = active["id"] if active else None

        if account_id:
            ck_file = self.accounts_dir / f"{account_id}.json"
            if ck_file.exists():
                try:
                    return json.loads(ck_file.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.error("Failed to read Douyin cookies for %s: %s", account_id, e)

        # Fallback reading .cookies.json
        try:
            root_ck = ROOT / ".cookies.json"
            if root_ck.exists():
                return json.loads(root_ck.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def set_active_account(self, account_id: str) -> bool:
        """Đặt tài khoản Douyin active và đồng bộ cookie ra toàn hệ thống."""
        data = _ensure_structure(_load_accounts())
        for acc in data["douyin"]:
            if acc["id"] == account_id:
                data["active"]["douyin"] = account_id
                _save_accounts(data)

                # Đồng bộ cookies của account này vào hệ thống
                cookies = self.get_cookies(account_id)
                if cookies:
                    self._sync_cookies_to_system(cookies)

                logger.info("Douyin active account set to: %s", acc.get("name", account_id))
                return True
        return False

    def add_account(self, account_id: str, name: str, cookies: Dict[str, str],
                    nickname: str = "", avatar: str = "") -> Dict[str, Any]:
        """Thêm hoặc cập nhật tài khoản Douyin."""
        data = _ensure_structure(_load_accounts())

        # Save cookies file
        ck_file = self.accounts_dir / f"{account_id}.json"
        try:
            ck_file.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to write Douyin cookies file %s: %s", ck_file, e)

        cookie_count = len(cookies)
        for acc in data["douyin"]:
            if acc["id"] == account_id:
                acc["name"] = name
                if nickname:
                    acc["nickname"] = nickname
                if avatar:
                    acc["avatar"] = avatar
                acc["cookie_count"] = cookie_count
                _save_accounts(data)
                if data["active"].get("douyin") == account_id:
                    self._sync_cookies_to_system(cookies)
                return acc

        account = {
            "id": account_id,
            "name": name,
            "nickname": nickname,
            "avatar": avatar,
            "cookie_count": cookie_count,
        }
        data["douyin"].append(account)

        if len(data["douyin"]) == 1 or not (data.get("active") or {}).get("douyin"):
            data["active"]["douyin"] = account_id
            self._sync_cookies_to_system(cookies)

        _save_accounts(data)
        logger.info("Douyin account added: %s (%s)", name, account_id)
        return account

    def remove_account(self, account_id: str) -> bool:
        """Xóa tài khoản Douyin."""
        data = _ensure_structure(_load_accounts())
        original_len = len(data["douyin"])
        data["douyin"] = [a for a in data["douyin"] if a["id"] != account_id]

        if len(data["douyin"]) == original_len:
            return False

        # Remove cookie file
        ck_file = self.accounts_dir / f"{account_id}.json"
        if ck_file.exists():
            try:
                ck_file.unlink()
            except Exception:
                pass

        if (data.get("active") or {}).get("douyin") == account_id:
            next_acc = data["douyin"][0]["id"] if data["douyin"] else None
            data["active"]["douyin"] = next_acc
            if next_acc:
                next_cookies = self.get_cookies(next_acc)
                if next_cookies:
                    self._sync_cookies_to_system(next_cookies)

        _save_accounts(data)
        logger.info("Douyin account removed: %s", account_id)
        return True

    def _sync_cookies_to_system(self, cookies: Dict[str, str]):
        """Đồng bộ cookies vào .cookies.json, config/cookies.json, config.yml, và CookieManager."""
        try:
            # 1. ROOT / .cookies.json
            root_ck = ROOT / ".cookies.json"
            root_ck.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2. ROOT / config / cookies.json
            cfg_dir = ROOT / "config"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            cfg_ck = cfg_dir / "cookies.json"
            cfg_ck.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")

            # 3. Update config.yml
            cfg_yml = ROOT / "config.yml"
            if cfg_yml.exists():
                try:
                    import yaml
                    content = yaml.safe_load(cfg_yml.read_text(encoding="utf-8")) or {}
                    content["cookies"] = cookies
                    cfg_yml.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
                except Exception as e:
                    logger.warning("Could not update config.yml cookies: %s", e)

            # 4. In-memory CookieManager update
            try:
                from auth.cookie_manager import CookieManager
                cm = CookieManager()
                cm.set_cookies(cookies)
            except Exception as e:
                logger.warning("Could not sync in-memory CookieManager: %s", e)

            logger.info("Successfully synced Douyin cookies across system (%d cookies)", len(cookies))
        except Exception as e:
            logger.error("Failed to sync Douyin cookies to system: %s", e)

    def migrate_existing(self):
        """Migrate .cookies.json cũ sang multi-account system."""
        root_ck = ROOT / ".cookies.json"
        data = _ensure_structure(_load_accounts())
        if root_ck.exists() and not data.get("douyin"):
            try:
                ck_data = json.loads(root_ck.read_text(encoding="utf-8"))
                if ck_data and isinstance(ck_data, dict):
                    self.add_account(
                        account_id="douyin_default",
                        name="Douyin Mặc Định",
                        cookies=ck_data,
                        nickname="",
                        avatar=""
                    )
                    logger.info("Migrated existing Douyin cookies to multi-account system")
            except Exception as e:
                logger.error("Failed to migrate Douyin cookies: %s", e)


# ── Singleton instances ───────────────────────────────────────────────────────

_youtube_account_mgr: Optional[YouTubeAccountManager] = None
_facebook_account_mgr: Optional[FacebookAccountManager] = None
_tiktok_account_mgr: Optional[TikTokAccountManager] = None
_douyin_account_mgr: Optional[DouyinAccountManager] = None


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


def get_tiktok_account_manager() -> TikTokAccountManager:
    """Get TikTok account manager singleton."""
    global _tiktok_account_mgr
    if _tiktok_account_mgr is None:
        _tiktok_account_mgr = TikTokAccountManager()
    return _tiktok_account_mgr


def get_douyin_account_manager() -> DouyinAccountManager:
    """Get Douyin account manager singleton."""
    global _douyin_account_mgr
    if _douyin_account_mgr is None:
        _douyin_account_mgr = DouyinAccountManager()
    return _douyin_account_mgr

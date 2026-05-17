"""
Security utilities — safe_join, secret loading, redaction, CSRF tokens, HMAC cookie auth.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path
from typing import Iterable, Optional


# ── Path safety ──────────────────────────────────────────────────────────────
def safe_join(base: Path, *parts: str) -> Path:
    """
    Resolve `base / *parts` and ensure the result stays inside `base`.
    Raises ValueError on traversal attempts ("../foo", absolute paths, etc.).
    """
    base = Path(base).resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise ValueError(f"Path traversal detected: {parts!r}")
    return candidate


_FILENAME_BAD = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip path separators & control chars; keep only the leaf name."""
    name = (name or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = _FILENAME_BAD.sub("_", name).strip(" .")
    return name or fallback


# ── Secret loading ───────────────────────────────────────────────────────────
def get_secret(env_key: str, *fallbacks: str, default: str = "") -> str:
    """
    Resolve a secret from os.environ first, then from any fallback values.
    Empty/whitespace strings are skipped.
    """
    val = os.getenv(env_key)
    if val and val.strip():
        return val.strip()
    for fb in fallbacks:
        if fb and str(fb).strip():
            return str(fb).strip()
    return default


def load_or_create_app_secret(state_dir: Path, env_key: str = "FLASK_SECRET_KEY") -> str:
    """
    Resolve the Flask SECRET_KEY:
      1. environment variable
      2. persisted random key at <state_dir>/.flask_secret
      3. generate new + persist
    """
    env_val = os.getenv(env_key)
    if env_val and len(env_val) >= 16:
        return env_val
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    secret_file = state_dir / ".flask_secret"
    if secret_file.exists():
        try:
            data = secret_file.read_text(encoding="utf-8").strip()
            if len(data) >= 16:
                return data
        except Exception:
            pass
    new_key = secrets.token_hex(32)
    try:
        secret_file.write_text(new_key, encoding="utf-8")
        try:
            os.chmod(secret_file, 0o600)
        except Exception:
            pass
    except Exception:
        pass
    return new_key


# ── Redaction ────────────────────────────────────────────────────────────────
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                  # OpenAI / Anthropic
    re.compile(r"gsk_[A-Za-z0-9]{30,}"),                    # Groq
    re.compile(r"hf_[A-Za-z0-9]{20,}"),                     # HuggingFace
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{20,}"),              # Google OAuth
    re.compile(r"EAA[A-Za-z0-9]{50,}"),                     # Facebook tokens
    re.compile(r"\b[0-9A-Za-z_\-]{20,}\.[0-9A-Za-z_\-]{20,}\.[0-9A-Za-z_\-]{20,}\b"),  # JWT-ish
]


def redact(text: str, *extra: str) -> str:
    """Mask common secret patterns and any explicit `extra` tokens in `text`."""
    if not text:
        return text
    out = str(text)
    for token in extra:
        if token and len(str(token)) >= 6:
            out = out.replace(str(token), "***REDACTED***")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("***REDACTED***", out)
    return out


# ── CSRF / signed cookies ────────────────────────────────────────────────────
def hmac_sign(secret: str, payload: str) -> str:
    """Return hex HMAC-SHA256 of `payload` with `secret`."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_csrf_token(secret: str, ttl_seconds: int = 7200) -> str:
    """token = `<expires>:<random>:<sig>` — verify with verify_csrf_token."""
    expires = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(8)
    sig = hmac_sign(secret, f"{expires}:{nonce}")
    return f"{expires}:{nonce}:{sig}"


def verify_csrf_token(secret: str, token: str) -> bool:
    if not token or token.count(":") != 2:
        return False
    try:
        expires_s, nonce, sig = token.split(":", 2)
        if int(expires_s) < int(time.time()):
            return False
        good = hmac_sign(secret, f"{expires_s}:{nonce}")
        return hmac.compare_digest(good, sig)
    except Exception:
        return False


def make_session_cookie(secret: str, user_id: str, ttl_seconds: int = 60 * 60 * 24 * 7) -> str:
    """Stateless signed cookie: `<user>:<expires>:<sig>`."""
    expires = int(time.time()) + int(ttl_seconds)
    sig = hmac_sign(secret, f"{user_id}:{expires}")
    return f"{user_id}:{expires}:{sig}"


def verify_session_cookie(secret: str, cookie: str) -> Optional[str]:
    """Returns user_id if valid & not expired, else None."""
    if not cookie or cookie.count(":") != 2:
        return None
    try:
        user, expires_s, sig = cookie.split(":", 2)
        if int(expires_s) < int(time.time()):
            return None
        good = hmac_sign(secret, f"{user}:{expires_s}")
        if hmac.compare_digest(good, sig):
            return user
    except Exception:
        return None
    return None


# ── Password hashing (PBKDF2-SHA256) ─────────────────────────────────────────
def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = 200_000) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iters_s, salt_hex, hash_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ── Origin parsing ───────────────────────────────────────────────────────────
def parse_origin_list(value, default: Iterable[str] = ()) -> list:
    """Accept str ('a,b'), list, or '*' — returns a deduped list of origins."""
    if value is None or value == "":
        return list(default)
    if value == "*" or value == ["*"]:
        return ["*"]
    if isinstance(value, (list, tuple, set)):
        items = [str(v).strip() for v in value]
    else:
        items = [s.strip() for s in str(value).split(",")]
    return [s for s in items if s]

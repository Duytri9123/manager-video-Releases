"""Direct AI-provider connections used by toolvideo.

This module intentionally does not proxy through a local 9Router/DTRouter
process.  Provider credentials are exchanged and requests are sent straight to
the upstream service.
"""
from __future__ import annotations

import base64
import json
import os
import platform
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


def _unmask_bytes(raw: list[int], mask: int = 0x5C) -> str:
    return bytes(b ^ mask for b in raw).decode("utf-8")


_DEFAULT_CLIENT_ID = _unmask_bytes([
    109, 108, 107, 109, 108, 108, 106, 108, 106, 108, 105, 101, 109, 113, 40,
    49, 52, 47, 47, 53, 50, 110, 52, 110, 109, 48, 63, 46, 57, 110, 111, 105,
    42, 40, 51, 48, 51, 54, 52, 104, 59, 104, 108, 111, 57, 44, 114, 61, 44,
    44, 47, 114, 59, 51, 51, 59, 48, 57, 41, 47, 57, 46, 63, 51, 50, 40, 57,
    50, 40, 114, 63, 51, 49,
])
_DEFAULT_CLIENT_SECRET = _unmask_bytes([
    27, 19, 31, 15, 12, 4, 113, 23, 105, 100, 26, 11, 14, 104, 100, 106, 16,
    56, 16, 22, 109, 49, 16, 30, 100, 47, 4, 31, 104, 38, 106, 45, 24, 29, 58,
])

ANTIGRAVITY_CLIENT_ID = os.environ.get("ANTIGRAVITY_CLIENT_ID", _DEFAULT_CLIENT_ID)
ANTIGRAVITY_CLIENT_SECRET = os.environ.get("ANTIGRAVITY_CLIENT_SECRET", _DEFAULT_CLIENT_SECRET)
ANTIGRAVITY_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"
ANTIGRAVITY_API_BASE = "https://daily-cloudcode-pa.googleapis.com"
ANTIGRAVITY_PROJECT_BASE = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_USER_AGENT = "antigravity/ide/2.11.0 darwin/arm64"
ANTIGRAVITY_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
)

ANTIGRAVITY_MODEL_ALIASES = {
    "gemini-3.8-flash": "gemini-3.8-flash-high",
    "gemini-3.8-flash-high": "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium": "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low": "gemini-3.8-flash-low",
    "gemini-3.7-flash": "gemini-3.7-flash-medium",
    "gemini-3.7-flash-high": "gemini-3.7-flash-medium",
    "gemini-3.7-flash-medium": "gemini-3.7-flash-medium",
    "gemini-3.7-flash-low": "gemini-3.7-flash-medium",
    "gemini-3.6-flash": "gemini-3.6-flash-medium",
    "gemini-3.6-flash-high": "gemini-3.6-flash-medium",
    "gemini-3.6-flash-medium": "gemini-3.6-flash-medium",
    "gemini-3.6-flash-low": "gemini-3.6-flash-medium",
    "gemini-3.1-pro": "gemini-3.1-pro-low",
    "gemini-3.1-pro-low": "gemini-3.1-pro-low",
    "gemini-pro-agent": "gemini-3.1-pro-low",
    "gemini-3-flash-agent": "gemini-3.6-flash-medium",
    "gemini-3.5-flash-medium": "gemini-3.6-flash-medium",
    "gemini-2.5-flash": "gemini-3.8-flash-high",
    "gemini-2.0-flash": "gemini-3.8-flash-high",
    "gemini-1.5-flash": "gemini-3.8-flash-high",
    "gemini-1.5-pro": "gemini-3.1-pro-low",
}


class ProviderError(RuntimeError):
    """An upstream provider rejected a direct request."""

    def __init__(self, message: str, *, status: int = 0, retry_after: float = 0.0):
        super().__init__(message)
        self.status = int(status or 0)
        self.retry_after = float(retry_after or 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# RAM Token Cache (pattern từ AIDE TokenRefreshService)
# ══════════════════════════════════════════════════════════════════════════════
# Cache: refresh_token → (access_token, expire_timestamp)
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
# Cache: access_token[:30] → project_id
_PROJECT_CACHE: dict[str, str] = {}


def get_active_token(raw_token: str) -> str:
    """Nếu raw_token là Refresh Token (1//...), tự đổi sang Access Token (ya29...) + cache 55 phút.
    Nếu là Access Token (ya29...) hoặc API Key (AIza...) thì trả nguyên."""
    clean = (raw_token or "").strip()
    if not clean.startswith("1//"):
        return clean

    now = time.time()
    # Kiểm tra cache (dành ra 5 phút buffer trước khi token hết hạn)
    if clean in _TOKEN_CACHE:
        cached_token, exp_time = _TOKEN_CACHE[clean]
        if now < exp_time:
            return cached_token

    # Refresh token → access token
    refreshed = refresh_antigravity_token(clean)
    access_token = str(refreshed.get("access_token") or "")
    if not access_token:
        raise ProviderError("Google OAuth refresh không trả về access token")
    expires_in = float(refreshed.get("expires_in") or 3600)
    # Cache với 5 phút buffer an toàn
    _TOKEN_CACHE[clean] = (access_token, now + expires_in - 300)
    return access_token


def get_project_id_cached(access_token: str) -> str:
    """Lấy Google Cloud Project ID qua loadCodeAssist, cache vĩnh viễn trong RAM."""
    clean = (access_token or "").strip()
    # Nếu truyền refresh token thì đổi sang access token trước
    if clean.startswith("1//"):
        clean = get_active_token(clean)

    token_key = clean[:30]
    if token_key in _PROJECT_CACHE:
        return _PROJECT_CACHE[token_key]

    try:
        project_id, tier_id = load_antigravity_project(clean)
        if not project_id:
            # Thử onboard tài khoản mới
            try:
                project_id = onboard_antigravity(clean, tier_id or "free-tier")
            except Exception:
                pass
        if project_id:
            _PROJECT_CACHE[token_key] = project_id
            return project_id
    except Exception:
        pass

    return "aicode-consumers"


def detect_key_type(raw_key: str) -> str:
    """Phân loại key: 'refresh_token' | 'oauth_token' | 'api_key' | 'unknown'."""
    k = (raw_key or "").strip()
    if k.startswith("1//"):
        return "refresh_token"
    if k.startswith("ya29."):
        return "oauth_token"
    if k.startswith("AIza"):
        return "api_key"
    if "cloudcode" in k or k.startswith("Bearer "):
        return "oauth_token"
    return "unknown"


def build_antigravity_auth_url(redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(ANTIGRAVITY_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })
    return f"{ANTIGRAVITY_AUTHORIZE_URL}?{query}"


def new_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def _json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    body = None
    actual_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        actual_headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        actual_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=actual_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
        try:
            parsed = json.loads(raw)
            message = parsed.get("error", {}).get("message") or parsed.get("error_description") or parsed.get("message")
        except Exception:
            message = raw
        retry_after = 0.0
        try:
            retry_after = float(exc.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            pass
        raise ProviderError(
            f"HTTP {exc.code}: {message or exc.reason}",
            status=exc.code,
            retry_after=retry_after,
        ) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"Không kết nối được upstream: {exc.reason}") from exc


def exchange_antigravity_code(code: str, redirect_uri: str) -> dict[str, Any]:
    return _json_request(
        GOOGLE_TOKEN_URL,
        method="POST",
        form={
            "grant_type": "authorization_code",
            "client_id": ANTIGRAVITY_CLIENT_ID,
            "client_secret": ANTIGRAVITY_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_antigravity_token(refresh_token: str) -> dict[str, Any]:
    return _json_request(
        GOOGLE_TOKEN_URL,
        method="POST",
        form={
            "grant_type": "refresh_token",
            "client_id": ANTIGRAVITY_CLIENT_ID,
            "client_secret": ANTIGRAVITY_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
    )


def get_google_userinfo(access_token: str) -> dict[str, Any]:
    return _json_request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )


def _platform_enum() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return 2 if machine in {"arm64", "aarch64"} else 1
    if system == "linux":
        return 4 if machine in {"arm64", "aarch64"} else 3
    if system == "windows":
        return 5
    return 0


def _antigravity_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": ANTIGRAVITY_USER_AGENT,
        "x-request-source": "local",
    }


def load_antigravity_project(access_token: str) -> tuple[str, str]:
    data = _json_request(
        f"{ANTIGRAVITY_PROJECT_BASE}/v1internal:loadCodeAssist",
        method="POST",
        headers=_antigravity_headers(access_token),
        payload={"metadata": {"ideType": 9, "platform": _platform_enum(), "pluginType": 2}},
    )
    project = data.get("cloudaicompanionProject") or ""
    if isinstance(project, dict):
        project = project.get("id") or ""
    tier_id = "legacy-tier"
    for tier in data.get("allowedTiers") or []:
        if tier.get("isDefault") and tier.get("id"):
            tier_id = str(tier["id"]).strip()
            break
    return str(project).strip(), tier_id


def onboard_antigravity(access_token: str, tier_id: str) -> str:
    data = _json_request(
        f"{ANTIGRAVITY_PROJECT_BASE}/v1internal:onboardUser",
        method="POST",
        headers=_antigravity_headers(access_token),
        payload={
            "tierId": tier_id or "legacy-tier",
            "metadata": {"ideType": 9, "platform": _platform_enum(), "pluginType": 2},
        },
        timeout=45,
    )
    project = (data.get("response") or {}).get("cloudaicompanionProject") or ""
    if isinstance(project, dict):
        project = project.get("id") or ""
    return str(project).strip()


def complete_antigravity_login(code: str, redirect_uri: str) -> dict[str, Any]:
    tokens = exchange_antigravity_code(code, redirect_uri)
    access_token = str(tokens.get("access_token") or "")
    if not access_token:
        raise ProviderError("Google không trả về access token")
    user = get_google_userinfo(access_token)
    project_id, tier_id = load_antigravity_project(access_token)
    if not project_id:
        # The onboarding call can create/return the companion project.
        project_id = onboard_antigravity(access_token, tier_id)
    return {
        "access_token": access_token,
        "refresh_token": str(tokens.get("refresh_token") or ""),
        "expires_at": int(time.time()) + int(tokens.get("expires_in") or 3600),
        "project_id": project_id,
        "email": str(user.get("email") or ""),
        "scope": str(tokens.get("scope") or ""),
    }


def ensure_antigravity_token(connection: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    token = str(connection.get("api_key") or connection.get("access_token") or "").strip()
    refresh_token = str(connection.get("refresh_token") or "").strip()
    updates: dict[str, Any] = {}

    # Nếu token là refresh token (1//...), dùng cache để đổi
    if token.startswith("1//"):
        refresh_token = token
        token = ""

    # Nếu có refresh token, dùng get_active_token() (có cache)
    if refresh_token:
        try:
            new_token = get_active_token(refresh_token)
            if new_token:
                updates = {
                    "api_key": new_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + 3300,  # ~55 phút
                }
                token = new_token
        except ProviderError:
            if not token:
                raise

    if not token:
        raise ProviderError("Kết nối Antigravity chưa có access token")
    return token, updates


def antigravity_generate_content(
    connection: dict[str, Any],
    model: str,
    request_body: dict[str, Any],
    *,
    timeout: int = 60,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call Antigravity upstream directly and return Gemini-shaped response."""
    access_token, updates = ensure_antigravity_token(connection)
    project_id = str(connection.get("project_id") or "").strip()
    if not project_id:
        project_id, _ = load_antigravity_project(access_token)
        if project_id:
            updates["project_id"] = project_id
    if not project_id:
        raise ProviderError("Tài khoản Google chưa có Cloud Code Assist project")

    clean_model = str(model or "gemini-3.7-flash").split("/", 1)[-1]
    clean_model = ANTIGRAVITY_MODEL_ALIASES.get(clean_model, clean_model)
    request_payload = dict(request_body or {})
    request_payload.setdefault("sessionId", str(uuid.uuid4().int)[:19])
    envelope = {
        "project": project_id,
        "model": clean_model,
        "userAgent": "antigravity",
        "requestType": "agent",
        "requestId": f"agent/{uuid.uuid4()}/{int(time.time() * 1000)}/{uuid.uuid4()}/1",
        "request": request_payload,
    }
    data = None
    for attempt in range(4):
        try:
            data = _json_request(
                f"{ANTIGRAVITY_API_BASE}/v1internal:generateContent",
                method="POST",
                headers=_antigravity_headers(access_token),
                payload=envelope,
                timeout=timeout,
            )
            break
        except ProviderError as exc:
            if exc.status not in {409, 429, 500, 502, 503, 504} or attempt >= 3:
                raise
            # Tôn trọng Retry-After; nếu upstream không gửi thì exponential backoff
            # kèm jitter nhỏ để nhiều tài khoản không retry cùng thời điểm.
            delay = exc.retry_after or min(8.0, 1.25 * (2 ** attempt))
            time.sleep(delay + secrets.randbelow(500) / 1000.0)
    if data is None:
        raise ProviderError("Antigravity không trả về dữ liệu sau khi retry")
    return (data.get("response") if isinstance(data.get("response"), dict) else data), updates


def google_generate_content(
    api_key: str,
    model: str,
    request_body: dict[str, Any],
    *,
    base_url: str = "https://generativelanguage.googleapis.com",
    timeout: int = 60,
) -> dict[str, Any]:
    base = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
    if base.endswith("/v1") or base.endswith("/v1beta"):
        base = base.rsplit("/", 1)[0]
    url = f"{base}/v1beta/models/{urllib.parse.quote(model, safe='-._')}:generateContent?key={urllib.parse.quote(api_key)}"
    return _json_request(url, method="POST", payload=request_body, timeout=timeout)


# ══════════════════════════════════════════════════════════════════════════════
# Multi-Provider Direct Connections (Anthropic, OpenAI-compatible, DeepSeek, etc.)
# ══════════════════════════════════════════════════════════════════════════════

STANDARD_PROVIDER_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
    "xai": "https://api.x.ai/v1/chat/completions",
    "kimi": "https://api.moonshot.cn/v1/chat/completions",
    "ollama": "http://localhost:11434/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "fireworks": "https://api.fireworks.ai/inference/v1/chat/completions",
    "sambanova": "https://api.sambanova.ai/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "codex": "https://api.openai.com/v1/chat/completions",
    "kiro": "https://api.kiro.dev/v1/chat/completions",
    "opencode": "https://opencode.ai/v1/chat/completions",
}


def resolve_model_provider(model: str) -> tuple[str, str]:
    """Resolve (provider_id, clean_model) from a model string or DB."""
    import sqlite3
    from pathlib import Path

    m_raw = str(model or "").strip()
    if "/" in m_raw:
        p, m = m_raw.split("/", 1)
        p = p.lower().strip()
        m = m.strip()
        if p in ("ag", "antig", "antigravity"):
            return "antigravity", m
        return p, m

    m_lower = m_raw.lower()
    if m_lower in ANTIGRAVITY_MODEL_ALIASES or "gemini" in m_lower or "flash" in m_lower:
        return "antigravity", m_raw
    if "claude" in m_lower:
        if any(x in m_lower for x in ["4-6", "thinking"]):
            return "antigravity", m_raw
        return "anthropic", m_raw
    if "deepseek" in m_lower:
        return "deepseek", m_raw
    if "llama" in m_lower or "mixtral" in m_lower or "gemma" in m_lower:
        return "groq", m_raw
    if "grok" in m_lower:
        return "xai", m_raw
    if "gpt" in m_lower or "o1" in m_lower or "o3" in m_lower:
        return "openai", m_raw
    if "moonshot" in m_lower:
        return "kimi", m_raw

    # Check database provider_models
    try:
        db_path = Path(__file__).parent.parent / ".state" / "providers.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT provider FROM provider_models WHERE model_id = ? AND enabled = 1 LIMIT 1", (m_raw,))
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0]), m_raw
    except Exception:
        pass

    return "antigravity", m_raw


def anthropic_generate_messages(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    base_url: str = "https://api.anthropic.com",
    timeout: int = 60,
) -> dict[str, Any]:
    """Call Anthropic Claude /v1/messages API directly."""
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    if base.endswith("/v1") or base.endswith("/messages"):
        base = base.rsplit("/", 1)[0]
    url = f"{base}/v1/messages"

    system_text = ""
    claude_msgs = []
    for m in messages:
        role = str(m.get("role", "user")).lower()
        content = m.get("content", "")
        if role == "system":
            system_text += (f"\n{content}" if system_text else str(content))
        else:
            claude_role = "assistant" if role == "assistant" else "user"
            claude_msgs.append({"role": claude_role, "content": content})

    if not claude_msgs:
        claude_msgs = [{"role": "user", "content": "hi"}]

    clean_model = model.replace("anthropic/", "").replace("claude/", "")
    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": claude_msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_text:
        payload["system"] = system_text

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    return _json_request(url, method="POST", headers=headers, payload=payload, timeout=timeout)


def openai_compatible_chat(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    base_url: str = "",
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    """Call any OpenAI-compatible provider directly."""
    url = (base_url or "").strip()
    if not url:
        url = "https://api.openai.com/v1/chat/completions"
    elif not url.endswith("/chat/completions"):
        url = f"{url.rstrip('/')}/chat/completions"

    clean_model = model.split("/", 1)[-1] if "/" in model else model
    payload: dict[str, Any] = {
        "model": clean_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return _json_request(url, method="POST", headers=headers, payload=payload, timeout=timeout)


def update_db_connection(connection_id: str, updates: dict[str, Any]) -> None:
    """Persist updated tokens or project ID to local providers.db."""
    import sqlite3
    from pathlib import Path

    if not updates or not connection_id:
        return
    try:
        db_path = Path(__file__).parent.parent / ".state" / "providers.db"
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        set_clauses = []
        params = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = ?")
            params.append(v)
        params.append(connection_id)
        sql = f"UPDATE provider_connections SET {', '.join(set_clauses)} WHERE id = ?"
        conn.execute(sql, params)
        conn.commit()
        conn.close()
    except Exception:
        pass


def dispatch_chat_completion(
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    timeout: int = 60,
    provider: str | None = None,
) -> dict[str, Any]:
    """
    Unified direct AI dispatcher across all providers.
    Supports multi-account auto-fallback from SQLite DB.
    Returns standard OpenAI-shaped response dictionary.
    """
    import os
    import re
    import sqlite3
    from pathlib import Path

    resolved_provider, clean_model = resolve_model_provider(model)
    if provider:
        resolved_provider = provider.lower().strip()

    # Collect available connections for this provider
    candidates: list[dict[str, Any]] = []
    try:
        db_path = Path(__file__).parent.parent / ".state" / "providers.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM provider_connections WHERE provider = ? AND enabled = 1 ORDER BY rowid ASC",
                (resolved_provider,)
            ).fetchall()
            for r in rows:
                candidates.append(dict(r))
            conn.close()
    except Exception:
        pass

    # Environment variables fallback
    if not candidates:
        env_map = {
            "antigravity": ["ANTIGRAVITY_API_KEY", "GEMINI_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "deepseek": ["DEEPSEEK_API_KEY"],
            "groq": ["GROQ_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
            "xai": ["XAI_API_KEY"],
            "nvidia": ["NVIDIA_API_KEY"],
            "kimi": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
        }
        for env_var in env_map.get(resolved_provider, []):
            val = os.getenv(env_var, "").strip()
            if val:
                candidates.append({
                    "id": f"env_{resolved_provider}",
                    "provider": resolved_provider,
                    "api_key": val,
                    "base_url": "",
                    "enabled": 1,
                    "status": "active"
                })
                break

    # If still no candidate, but provider is ollama or local-compatible, try default local
    if not candidates and resolved_provider == "ollama":
        candidates.append({
            "id": "ollama_default",
            "provider": "ollama",
            "api_key": "",
            "base_url": "http://localhost:11434/v1",
            "enabled": 1
        })

    if not candidates:
        raise ProviderError(
            f"Chưa có kết nối nào đang bật cho nhà cung cấp '{resolved_provider}'. "
            f"Vui lòng vào tab Nhà cung cấp để thêm API key hoặc đăng nhập."
        )

    last_error: Exception | None = None

    for conn_data in candidates:
        api_key = str(conn_data.get("api_key") or conn_data.get("access_token") or "").strip()
        base_url = str(conn_data.get("base_url") or "").strip()
        conn_id = str(conn_data.get("id") or "")

        try:
            # ── 1. ANTIGRAVITY (Google Cloud Code OAuth or AIza key) ──
            if resolved_provider in ("antigravity", "gemini"):
                is_oauth = api_key.startswith("ya29.") or ("cloudcode" in base_url) or conn_data.get("auth_type") == "oauth"
                if is_oauth:
                    # Convert OpenAI messages to Gemini contents
                    contents = []
                    system_inst = None
                    for m in messages:
                        r = str(m.get("role", "user")).lower()
                        c = m.get("content", "")
                        if r == "system":
                            system_inst = {"parts": [{"text": str(c)}]}
                        else:
                            g_role = "model" if r == "assistant" else "user"
                            contents.append({"role": g_role, "parts": [{"text": str(c)}]})
                    if not contents:
                        contents = [{"role": "user", "parts": [{"text": "hi"}]}]

                    body: dict[str, Any] = {"contents": contents}
                    if system_inst:
                        body["systemInstruction"] = system_inst
                    gen_cfg = body.setdefault("generationConfig", {})
                    if max_tokens:
                        gen_cfg["maxOutputTokens"] = max_tokens
                    if temperature is not None:
                        gen_cfg["temperature"] = temperature
                    if "thinking" not in clean_model.lower():
                        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

                    resp, updates = antigravity_generate_content(conn_data, clean_model, body, timeout=timeout)
                    if updates and conn_id:
                        update_db_connection(conn_id, updates)

                    # Extract text from response
                    candidates_list = resp.get("candidates") or []
                    text_parts = []
                    if candidates_list and "content" in candidates_list[0]:
                        for part in candidates_list[0]["content"].get("parts") or []:
                            if isinstance(part, dict):
                                if part.get("thought") is True:
                                    continue
                                t = part.get("text") or ""
                                if t:
                                    text_parts.append(t)
                            elif isinstance(part, str):
                                text_parts.append(part)
                    full_text = "".join(text_parts).strip()
                    # Strip any raw think tags
                    full_text = re.sub(r"<thought>.*?</thought>", "", full_text, flags=re.DOTALL)
                    full_text = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()

                    return {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": full_text},
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    }

                elif api_key.startswith("AIza"):
                    # Google AI Studio
                    g_base = base_url or "https://generativelanguage.googleapis.com"
                    # Try OpenAI compatibility endpoint first
                    openai_ep = f"{g_base.rstrip('/')}/v1beta/openai/chat/completions"
                    try:
                        return openai_compatible_chat(
                            api_key, clean_model, messages,
                            base_url=openai_ep, temperature=temperature,
                            max_tokens=max_tokens, timeout=timeout
                        )
                    except Exception:
                        # Fallback to native generateContent
                        contents = [{"role": "user", "parts": [{"text": m.get("content", "")}]} for m in messages if m.get("role") != "system"]
                        native_resp = google_generate_content(api_key, clean_model, {"contents": contents}, base_url=g_base, timeout=timeout)
                        parts = ((native_resp.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                        txt = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                        return {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                            "object": "chat.completion",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": txt}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                        }

            # ── 2. ANTHROPIC CLAUDE ──
            elif resolved_provider == "anthropic":
                claude_resp = anthropic_generate_messages(
                    api_key, clean_model, messages,
                    temperature=temperature, max_tokens=max_tokens or 4096,
                    base_url=base_url or "https://api.anthropic.com", timeout=timeout
                )
                content_blocks = claude_resp.get("content") or []
                text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
                return {
                    "id": claude_resp.get("id") or f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": claude_resp.get("stop_reason") or "stop"
                        }
                    ],
                    "usage": claude_resp.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                }

            # ── 3. OPENAI & ALL OPENAI-COMPATIBLE PROVIDERS ──
            else:
                target_url = base_url or STANDARD_PROVIDER_URLS.get(resolved_provider, "")
                resp = openai_compatible_chat(
                    api_key, clean_model, messages,
                    base_url=target_url, temperature=temperature,
                    max_tokens=max_tokens, timeout=timeout
                )
                if "choices" in resp and len(resp["choices"]) > 0:
                    return resp
                raise ProviderError(f"Phản hồi từ {resolved_provider} không hợp lệ: {resp}")

        except Exception as err:
            last_error = err
            continue

    if last_error:
        raise last_error
    raise ProviderError(f"Không thực hiện được cuộc gọi tới {resolved_provider}")


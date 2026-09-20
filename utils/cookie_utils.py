from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping

# RFC6265 token 分隔符与空白字符
INVALID_COOKIE_NAME_CHARS = set('()<>@,;:\\"/[]?={} \t\r\n')


def is_valid_cookie_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in name):
        return False
    if any(ch in INVALID_COOKIE_NAME_CHARS for ch in name):
        return False
    return True


def sanitize_cookies(cookies: Mapping[Any, Any]) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for raw_key, raw_value in (cookies or {}).items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        if not is_valid_cookie_name(key):
            continue
        value = "" if raw_value is None else str(raw_value).strip()
        sanitized[key] = value
    return sanitized


def _flatten_cookie_payload(payload: Any) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if isinstance(payload, list):
        for item in payload:
            parsed.update(_flatten_cookie_payload(item))
        return parsed

    if not isinstance(payload, dict):
        return parsed

    for container_key in ("cookies", "cookie", "data"):
        nested = payload.get(container_key)
        if isinstance(nested, (list, dict)):
            parsed.update(_flatten_cookie_payload(nested))

    name = payload.get("name")
    if isinstance(name, str) and "value" in payload:
        parsed[name] = "" if payload.get("value") is None else str(payload.get("value"))

    for key, value in payload.items():
        if key in {"name", "value", "domain", "path", "expires", "expirationDate", "httpOnly", "secure", "sameSite"}:
            continue
        if isinstance(value, dict) and "value" in value:
            parsed[key] = "" if value.get("value") is None else str(value.get("value"))
        elif not isinstance(value, (dict, list)):
            parsed[key] = "" if value is None else str(value)
    return sanitize_cookies(parsed)


def _parse_json_cookie_payload(text: str) -> Dict[str, str]:
    candidates = [text]
    stripped = text.strip().strip(";")
    if not (stripped.startswith("{") or stripped.startswith("[")):
        candidates.append("{" + stripped.rstrip(",") + "}")

    for candidate in candidates:
        try:
            return _flatten_cookie_payload(json.loads(candidate))
        except Exception:
            continue
    return {}


def _parse_key_value_lines(text: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    pattern = re.compile(
        r"""["']?([A-Za-z0-9_$.\-]+)["']?\s*[:=]\s*["']([^"']*)["']""",
        re.MULTILINE,
    )
    for key, value in pattern.findall(text):
        if is_valid_cookie_name(key):
            parsed[key] = value.strip()
    return parsed


def parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    if not cookie_header:
        return {}
    cookie_header = str(cookie_header).strip()

    parsed = _parse_json_cookie_payload(cookie_header)
    if parsed:
        return parsed

    parsed = _parse_key_value_lines(cookie_header)
    if parsed:
        return sanitize_cookies(parsed)

    if cookie_header.lower().startswith("cookie:"):
        cookie_header = cookie_header.split(":", 1)[1].strip()
    if cookie_header.lower().startswith("document.cookie"):
        cookie_header = cookie_header.split("=", 1)[1].strip().strip("\"';")

    parsed: Dict[str, str] = {}
    for item in cookie_header.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if not is_valid_cookie_name(key):
            continue
        parsed[key] = value.strip()
    if parsed:
        return sanitize_cookies(parsed)

    # Nhận diện thông minh khi người dùng dán các giá trị rời rạc (cách nhau bởi dấu phẩy hoặc dòng mới)
    inferred = _infer_unlabeled_cookie_tokens(cookie_header)
    if inferred:
        return sanitize_cookies(inferred)

    return {}


def _infer_unlabeled_cookie_tokens(text: str) -> Dict[str, str]:
    tokens = [t.strip().strip("'\",") for t in re.split(r"[\r\n,]+", text)]
    tokens = [t for t in tokens if t]
    inferred: Dict[str, str] = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\",")
            if is_valid_cookie_name(k):
                inferred[k] = v
                continue
        if tok.startswith("verify_"):
            inferred["s_v_web_id"] = tok
        elif tok.startswith("_02B4"):
            inferred["__ac_signature"] = tok
        elif tok.startswith("1%7C") or tok.startswith("1|"):
            inferred["ttwid"] = tok
        elif tok in ("1", "2", "3"):
            inferred["bd_ticket_guard_client_web_domain"] = tok
        elif len(tok) == 32 and re.fullmatch(r"[0-9a-fA-F]{32}", tok):
            inferred["passport_csrf_token"] = tok
        elif len(tok) >= 200:
            inferred["UIFID"] = tok
        elif 100 <= len(tok) < 200 and re.fullmatch(r"[0-9a-fA-F]+", tok):
            inferred["odin_tt"] = tok
    return inferred

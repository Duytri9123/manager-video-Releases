"""Shared 9Router image-generation client.

9Router's `/v1/images/generations` endpoint returns **two different** response
shapes depending on the model:

* Standard JSON ``{created, data:[{b64_json|url}]}`` — OpenAI / Gemini / FLUX …
* Server-Sent Events (SSE) — Codex ``cx/*`` models stream ``partial_image`` and
  ``result`` events, each carrying base64 image data.

Calling ``json.loads()`` on an SSE body raises and silently breaks Codex image
generation. This helper handles both shapes so every caller behaves like the
working Chat-Bot tab (see ``routes/chatbot.py::chatbot_image``).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# Models whose top-level provider is Codex — these stream SSE and use
# ``output_format``/``background`` instead of the OpenAI ``response_format``.
_CODEX_PREFIX = "cx/"


def build_image_payload(
    model: str,
    prompt: str,
    *,
    n: int = 1,
    size: str = "1024x1024",
    quality: Optional[str] = None,
    background: Optional[str] = None,
    output_format: str = "png",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a request body that matches each model family's expectations.

    Codex (``cx/*``) models take ``output_format``/``background`` and must NOT
    receive ``response_format``. All other providers take the OpenAI-style
    ``response_format=b64_json``.
    """
    model = (model or "").strip() or "cx/gpt-5.5-image"
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": int(n or 1),
        "size": str(size),
    }
    if model.startswith(_CODEX_PREFIX):
        payload["quality"] = quality or "auto"
        payload["background"] = background or "auto"
        payload["output_format"] = output_format or "png"
    else:
        if quality:
            payload["quality"] = quality
        payload["response_format"] = "b64_json"
    if extra:
        payload.update(extra)
    return payload


def _parse_sse_images(text: str) -> List[Dict[str, str]]:
    """Extract image dicts from an accumulated SSE body."""
    images: List[Dict[str, str]] = []
    for ev in text.split("\n\n"):
        event_name = ""
        data_parts: List[str] = []
        for line in ev.strip().split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].strip())
        if not data_parts:
            continue
        data_str = "\n".join(data_parts)
        if data_str == "[DONE]":
            continue
        try:
            obj = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if event_name == "partial_image" or (not event_name and "b64_json" in data_str):
            if isinstance(obj, dict) and obj.get("b64_json"):
                images.append({"b64_json": obj["b64_json"]})
        elif event_name == "result" or (not event_name and '"data"' in data_str):
            for item in (obj.get("data") or []) if isinstance(obj, dict) else []:
                if isinstance(item, dict) and (item.get("b64_json") or item.get("url")):
                    images.append(item)
    return images


def generate_images(
    endpoint: str,
    api_key: str,
    payload: Dict[str, Any],
    *,
    timeout: Tuple[int, int] = (10, 300),
) -> Tuple[List[Dict[str, str]], str]:
    """POST to ``{endpoint}/images/generations`` and return ``(images, error)``.

    ``images`` is a list of ``{"b64_json": ...}`` and/or ``{"url": ...}`` dicts.
    ``error`` is an empty string on success, otherwise a human-readable message.
    Handles both JSON and SSE (Codex) responses.
    """
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover - requests always present
        return [], f"requests unavailable: {exc}"

    url = f"{(endpoint or '').rstrip('/')}/images/generations"
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            stream=True,
            timeout=timeout,
        )
    except Exception as exc:
        return [], f"9Router unreachable: {exc}"

    try:
        if resp.status_code >= 400:
            body = resp.text or ""
            try:
                msg = (json.loads(body).get("error") or {}).get("message") or body
            except Exception:
                msg = body or f"HTTP {resp.status_code}"
            return [], f"9Router HTTP {resp.status_code}: {str(msg)[:300]}"

        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in content_type:
            buf = ""
            for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    buf += chunk
            return _parse_sse_images(buf), ""

        # Standard JSON response.
        try:
            body = resp.json()
        except Exception:
            return [], "9Router returned an invalid JSON response"
        items = body.get("data") or [] if isinstance(body, dict) else []
        images = [it for it in items if isinstance(it, dict) and (it.get("b64_json") or it.get("url"))]
        return images, ""
    finally:
        resp.close()

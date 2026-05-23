"""
LLM client cho idea2video — dùng 9Router (OpenAI-compatible) từ config toolvideo.
Hỗ trợ cả sync và async call, tự động fallback qua các provider.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "Accept": "application/json", **headers}
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace") or "{}")


class LLMClient:
    """
    Wrapper gọi LLM qua 9Router hoặc các provider khác trong config toolvideo.
    Dùng cùng pattern với movie_review._call_llm nhưng hỗ trợ structured output.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self._nr = cfg.get("nine_router") or {}
        self._tr = cfg.get("translation") or {}

    def _get_candidates(self, provider: str = "auto") -> list[tuple[str, str, str]]:
        """Trả về list (provider, api_key, endpoint) theo thứ tự ưu tiên."""
        nr = self._nr
        tr = self._tr
        gv = self.cfg.get("gemini_video") or {}
        candidates: list[tuple[str, str, str]] = []

        nr_key = (nr.get("api_key") or "").strip()
        nr_endpoint = (nr.get("endpoint") or "http://localhost:20128/v1").rstrip("/")

        # Gemini API key — dùng chung với gemini_video, hoặc env GEMINI_API_KEY
        import os as _os
        gemini_key = (gv.get("api_key") or "").strip() or _os.environ.get("GEMINI_API_KEY", "").strip()
        gemini_endpoint = "https://generativelanguage.googleapis.com/v1beta"

        if provider == "9router" and nr_key:
            candidates.append(("9router", nr_key, nr_endpoint))
        if provider == "gemini" and gemini_key:
            candidates.append(("gemini", gemini_key, gemini_endpoint))
        if provider in ("auto", "gemini") and gemini_key:
            candidates.append(("gemini", gemini_key, gemini_endpoint))
        if provider in ("auto", "deepseek") and tr.get("deepseek_key"):
            candidates.append(("deepseek", tr["deepseek_key"], "https://api.deepseek.com"))
        if provider in ("auto", "openai") and tr.get("openai_key"):
            candidates.append(("openai", tr["openai_key"], "https://api.openai.com/v1"))
        if provider in ("auto", "groq") and tr.get("groq_key"):
            candidates.append(("groq", tr["groq_key"], "https://api.groq.com/openai/v1"))
        # Auto fallback: 9Router nếu không có gì khác
        if provider == "auto" and not candidates and nr_key:
            candidates.append(("9router", nr_key, nr_endpoint))

        # Dedupe (gemini có thể bị thêm 2 lần nếu provider=="gemini")
        seen = set()
        unique = []
        for item in candidates:
            if item[0] not in seen:
                seen.add(item[0])
                unique.append(item)
        return unique

    def _model_for(self, prov: str) -> str:
        nr = self._nr
        tr = self._tr
        gv = self.cfg.get("gemini_video") or {}
        if prov == "9router":
            return (nr.get("default_model") or "duytris").strip()
        if prov == "gemini":
            return (gv.get("llm_model") or "gemini-2.0-flash-exp").strip()
        if prov == "deepseek":
            return "deepseek-chat"
        if prov == "openai":
            return "gpt-4o-mini"
        if prov == "groq":
            return tr.get("groq_model") or "llama-3.1-8b-instant"
        return "duytris"

    def chat(
        self,
        system: str,
        user: str,
        provider: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> Optional[str]:
        """Gọi LLM, trả về content string hoặc None nếu thất bại."""
        candidates = self._get_candidates(provider)
        if not candidates:
            logger.warning("LLMClient: không có provider nào được cấu hình")
            return None

        for prov, key, endpoint in candidates:
            try:
                model = self._model_for(prov)

                # Gemini có format API riêng (Google), không phải OpenAI-compatible
                if prov == "gemini":
                    content = _call_gemini(
                        endpoint=endpoint, api_key=key, model=model,
                        system=system, user=user,
                        temperature=temperature, max_tokens=max_tokens, timeout=timeout,
                    )
                    if content:
                        logger.debug("LLMClient: thành công với provider=gemini, model=%s", model)
                        return content
                    continue

                # Các provider khác đều OpenAI-compatible
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                }
                url = f"{endpoint}/chat/completions"
                data = _post_json(url, payload, {"Authorization": f"Bearer {key}"}, timeout=timeout)
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                if content:
                    logger.debug("LLMClient: thành công với provider=%s", prov)
                    return content
            except Exception as e:
                logger.warning("LLMClient: provider=%s thất bại: %s", prov, e)
                continue

        return None

    def chat_json(
        self,
        system: str,
        user: str,
        provider: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> Optional[dict | list]:
        """Gọi LLM và parse JSON từ response."""
        content = self.chat(system, user, provider, temperature, max_tokens, timeout)
        if not content:
            return None
        return _try_parse_json(content)


def _try_parse_json(text: str) -> Optional[dict | list]:
    """Parse JSON từ LLM response, xử lý markdown code blocks."""
    if not text:
        return None
    text = text.strip()
    # Strip markdown code blocks
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Tìm JSON object hoặc array
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            blob = text[start:end + 1]
            try:
                return json.loads(blob)
            except Exception:
                continue
    return None


def _call_gemini(
    endpoint: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> Optional[str]:
    """
    Gọi Gemini API (Google AI Studio).
    Format API khác OpenAI: dùng `contents` thay vì `messages`,
    `systemInstruction` riêng, query param `key` thay vì Bearer token.

    Endpoint mẫu:
      POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key=API_KEY

    Models phổ biến (free tier):
      - gemini-2.5-pro                   (mạnh nhất, chậm hơn)
      - gemini-2.5-flash                 (cân bằng tốc độ/chất lượng)
      - gemini-2.0-flash-exp             (nhanh, đa phương tiện)
      - gemini-2.0-flash                 (nhanh, ổn định)
      - gemini-1.5-pro / gemini-1.5-flash (cũ hơn, vẫn dùng được)
    """
    url = f"{endpoint}/models/{model}:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {
            "parts": [{"text": system}],
        },
        "contents": [
            {"role": "user", "parts": [{"text": user}]},
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
            # Yêu cầu response JSON cho các prompt cần parse JSON
            # Để client tự xử lý qua _try_parse_json, không bật response_mime_type
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", "replace")
            logger.warning("Gemini API HTTP %d: %s", e.code, err_body[:500])
        except Exception:
            logger.warning("Gemini API HTTP %d", e.code)
        return None
    except Exception as e:
        logger.warning("Gemini API error: %s", e)
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        # Có thể bị block bởi safety filter
        prompt_feedback = data.get("promptFeedback") or {}
        if prompt_feedback.get("blockReason"):
            logger.warning("Gemini blocked: %s", prompt_feedback["blockReason"])
        return None

    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or None


# Re-export urllib.error to avoid NameError in _call_gemini above
import urllib.error  # noqa: E402  (kept at bottom for clarity)

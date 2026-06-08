"""Shared TTS engine/voice catalogue.

The frontend expects this shape:
  {id, label, default, backend, voices: {lang: [[voice_id, label], ...]}}

Local engines are static. 9Router engines are added only when its gateway is
reachable and has TTS models configured.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Tuple


_LANGS = ("vi", "en", "zh", "ja", "ko", "th", "id", "es", "pt", "fr", "de", "ru", "ar", "hi")
_CACHE: Dict[str, Any] = {"ts": 0.0, "endpoint": "", "engines": None, "status": None}
_CACHE_TTL = 30.0


def local_tts_engines() -> List[Dict[str, Any]]:
    """Return built-in/local TTS engines."""
    return [
        {
            "id": "edge-tts",
            "label": "Edge TTS (Microsoft, mien phi)",
            "default": "vi-VN-HoaiMyNeural",
            "backend": "local",
            "voices": {
                "vi": [
                    ("vi-VN-HoaiMyNeural", "Hoai My (nu, mien Bac)"),
                    ("vi-VN-NamMinhNeural", "Nam Minh (nam, mien Bac)"),
                ],
                "en": [
                    ("en-US-JennyNeural", "Jenny (female, US)"),
                    ("en-US-AriaNeural", "Aria (female, US)"),
                    ("en-US-GuyNeural", "Guy (male, US)"),
                    ("en-GB-SoniaNeural", "Sonia (female, UK)"),
                    ("en-GB-RyanNeural", "Ryan (male, UK)"),
                ],
                "zh": [
                    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao (female, CN)"),
                    ("zh-CN-YunxiNeural", "Yunxi (male, CN)"),
                ],
                "ja": [
                    ("ja-JP-NanamiNeural", "Nanami (female)"),
                    ("ja-JP-KeitaNeural", "Keita (male)"),
                ],
                "ko": [
                    ("ko-KR-SunHiNeural", "SunHi (female)"),
                    ("ko-KR-InJoonNeural", "InJoon (male)"),
                ],
                "th": [
                    ("th-TH-PremwadeeNeural", "Premwadee (female)"),
                    ("th-TH-NiwatNeural", "Niwat (male)"),
                ],
                "id": [
                    ("id-ID-GadisNeural", "Gadis (female)"),
                    ("id-ID-ArdiNeural", "Ardi (male)"),
                ],
                "es": [
                    ("es-ES-ElviraNeural", "Elvira (female, ES)"),
                    ("es-ES-AlvaroNeural", "Alvaro (male, ES)"),
                    ("es-MX-DaliaNeural", "Dalia (female, MX)"),
                ],
                "pt": [
                    ("pt-BR-FranciscaNeural", "Francisca (female, BR)"),
                    ("pt-BR-AntonioNeural", "Antonio (male, BR)"),
                ],
                "fr": [
                    ("fr-FR-DeniseNeural", "Denise (female, FR)"),
                    ("fr-FR-HenriNeural", "Henri (male, FR)"),
                ],
                "de": [
                    ("de-DE-KatjaNeural", "Katja (female, DE)"),
                    ("de-DE-ConradNeural", "Conrad (male, DE)"),
                ],
                "ru": [
                    ("ru-RU-SvetlanaNeural", "Svetlana (female, RU)"),
                    ("ru-RU-DmitryNeural", "Dmitry (male, RU)"),
                ],
                "ar": [
                    ("ar-SA-ZariyahNeural", "Zariyah (female, SA)"),
                    ("ar-SA-HamedNeural", "Hamed (male, SA)"),
                ],
                "hi": [
                    ("hi-IN-SwaraNeural", "Swara (female, IN)"),
                    ("hi-IN-MadhurNeural", "Madhur (male, IN)"),
                ],
            },
        },
        {
            "id": "fpt-ai",
            "label": "FPT AI TTS (can API key, tieng Viet)",
            "default": "banmai",
            "backend": "local",
            "voices": {
                "vi": [
                    ("banmai", "Ban Mai (FPT - nu, mien Bac)"),
                    ("thuminh", "Thu Minh (FPT - nu, mien Bac)"),
                    ("myan", "My An (FPT - nu, mien Trung)"),
                    ("leminh", "Le Minh (FPT - nam, mien Bac)"),
                    ("linhsan", "Linh San (FPT - nu, mien Nam)"),
                    ("giahuy", "Gia Huy (FPT - nam, mien Nam)"),
                    ("lannhi", "Lan Nhi (FPT - nu, mien Nam)"),
                ],
            },
        },
        {
            "id": "elevenlabs",
            "label": "ElevenLabs TTS (can API key)",
            "default": "21m00Tcm4TlvDq8ikWAM",
            "backend": "local",
            "voices": {
                "multi": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (multilingual)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (multilingual)"),
                    ("ErXwobaYiN019PkySvjV", "Antoni (multilingual)"),
                    ("pNInz6obpgDQGcFmaJgB", "Adam (multilingual)"),
                ],
                "vi": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (multilingual v2)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (multilingual v2)"),
                ],
                "en": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (female)"),
                    ("AZnzlk1XvdvUeBnXmlld", "Domi (female)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (female)"),
                    ("ErXwobaYiN019PkySvjV", "Antoni (male)"),
                    ("VR6AewLTigWG4xSOukaG", "Arnold (male)"),
                    ("pNInz6obpgDQGcFmaJgB", "Adam (male)"),
                ],
            },
        },
        {
            "id": "fish-audio",
            "label": "Fish Audio TTS (da ngon ngu, can API key)",
            "default": "",
            "backend": "local",
            "voices": {
                "ja": [
                    ("", "Default voice (auto)"),
                    ("fbe02f8306fc4d3d915e9871722a39d5", "Japanese Female (sample)"),
                ],
                "zh": [
                    ("", "Default voice (auto)"),
                ],
                "ko": [
                    ("", "Default voice (auto)"),
                ],
                "en": [
                    ("", "Default voice (auto)"),
                ],
                "vi": [
                    ("", "Default voice (auto)"),
                ],
                "multi": [
                    ("", "Default voice (auto)"),
                ],
            },
        },
        {
            "id": "gtts",
            "label": "Google gTTS (don gian, du phong)",
            "default": "vi",
            "backend": "local",
            "voices": {
                "vi": [("vi", "Tieng Viet mac dinh")],
                "en": [("en", "English default")],
                "zh": [("zh", "Chinese default")],
                "ja": [("ja", "Japanese default")],
                "ko": [("ko", "Korean default")],
                "th": [("th", "Thai default")],
                "id": [("id", "Indonesian default")],
                "es": [("es", "Spanish default")],
                "pt": [("pt", "Portuguese default")],
                "fr": [("fr", "French default")],
                "de": [("de", "German default")],
                "ru": [("ru", "Russian default")],
                "ar": [("ar", "Arabic default")],
                "hi": [("hi", "Hindi default")],
            },
        },
    ]


def _endpoint_from_cfg(cfg: Dict[str, Any]) -> str:
    nr = cfg.get("nine_router") or {}
    endpoint = (
        os.getenv("NINEROUTER_URL")
        or nr.get("endpoint")
        or "http://localhost:20128/v1"
    )
    endpoint = str(endpoint).strip().rstrip("/")
    if not endpoint.endswith("/v1") and not re.search(r"/v1(/|$)", endpoint):
        endpoint += "/v1"
    return endpoint


def _key_from_cfg(cfg: Dict[str, Any]) -> str:
    nr = cfg.get("nine_router") or {}
    return str(os.getenv("NINEROUTER_KEY") or nr.get("api_key") or "").strip()


def _origin(endpoint: str) -> str:
    return re.sub(r"/v1$", "", endpoint.rstrip("/"))


def _http_json(url: str, api_key: str = "", timeout: int = 8) -> Tuple[int, Any]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw) if raw else {}
            except ValueError:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def _voice_label(item: Dict[str, Any], fallback: str) -> str:
    for key in ("label", "name", "displayName", "display_name", "voice", "id"):
        val = str(item.get(key) or "").strip()
        if val:
            return val
    return fallback


def _voices_from_router(
    endpoint: str,
    api_key: str,
    provider: str,
    langs: Tuple[str, ...] = _LANGS,
) -> Dict[str, List[Tuple[str, str]]]:
    voices: Dict[str, List[Tuple[str, str]]] = {}
    for lang in langs:
        qs = urllib.parse.urlencode({"provider": provider, "lang": lang})
        try:
            status, body = _http_json(
                f"{endpoint}/audio/voices?{qs}",
                api_key=api_key,
                timeout=3,
            )
        except Exception:
            continue
        if status >= 400 or not isinstance(body, dict):
            continue
        rows = []
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model = str(item.get("model") or item.get("id") or "").strip()
            if not model:
                continue
            rows.append((model, _voice_label(item, model)))
        if rows:
            voices[lang] = rows
    return voices


def _has_model(models: List[str], *patterns: str) -> str:
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for mid in models:
            if rx.search(mid):
                return mid
    return ""


def _static_9router_engines(models: List[str]) -> List[Dict[str, Any]]:
    engines: List[Dict[str, Any]] = []

    openai_model = _has_model(models, r"^openai/(?:tts|gpt-4o.*tts)")
    if openai_model:
        engines.append({
            "id": "9r:openai",
            "label": "OpenAI TTS (9Router)",
            "default": "nova",
            "defaultModel": openai_model,
            "backend": "9router",
            "provider": "openai",
            "voices": {
                "vi": [
                    ("nova", "Nova (multilingual)"),
                    ("shimmer", "Shimmer (multilingual)"),
                    ("alloy", "Alloy (multilingual)"),
                ],
                "en": [
                    ("nova", "Nova (female, warm)"),
                    ("shimmer", "Shimmer (female, soft)"),
                    ("alloy", "Alloy (neutral)"),
                    ("echo", "Echo (male)"),
                    ("onyx", "Onyx (male)"),
                    ("fable", "Fable (storyteller)"),
                ],
                "ja": [("nova", "Nova (multilingual)"), ("shimmer", "Shimmer")],
                "ko": [("nova", "Nova (multilingual)"), ("shimmer", "Shimmer")],
                "zh": [("nova", "Nova (multilingual)"), ("shimmer", "Shimmer")],
            },
        })

    el_model = _has_model(models, r"^el/", r"^eleven")
    if el_model:
        engines.append({
            "id": "9r:elevenlabs",
            "label": "ElevenLabs (9Router)",
            "default": "21m00Tcm4TlvDq8ikWAM",
            "defaultModel": el_model,
            "backend": "9router",
            "provider": "elevenlabs",
            "voices": {
                "vi": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (multilingual v2)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (multilingual v2)"),
                ],
                "en": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (female)"),
                    ("AZnzlk1XvdvUeBnXmlld", "Domi (female)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (female)"),
                    ("ErXwobaYiN019PkySvjV", "Antoni (male)"),
                    ("pNInz6obpgDQGcFmaJgB", "Adam (male)"),
                ],
                "multi": [
                    ("21m00Tcm4TlvDq8ikWAM", "Rachel (multilingual)"),
                    ("EXAVITQu4vr4xnSDxMaL", "Bella (multilingual)"),
                ],
            },
        })

    gemini_model = _has_model(models, r"^gemini/.*tts")
    if gemini_model:
        engines.append({
            "id": "9r:gemini",
            "label": "Gemini TTS (9Router)",
            "default": "Kore",
            "defaultModel": gemini_model,
            "backend": "9router",
            "provider": "gemini",
            "voices": {
                "vi": [("Kore", "Kore (multilingual)"), ("Charon", "Charon")],
                "en": [
                    ("Kore", "Kore (female)"),
                    ("Charon", "Charon (male)"),
                    ("Puck", "Puck (cheerful)"),
                    ("Aoede", "Aoede (warm)"),
                ],
            },
        })

    minimax_model = _has_model(models, r"^minimax/")
    if minimax_model:
        engines.append({
            "id": "minimax",
            "label": "MiniMax TTS (9Router)",
            "default": "English_expressive_narrator",
            "defaultModel": minimax_model,
            "backend": "9router",
            "provider": "minimax",
            "voices": {
                "en": [
                    ("English_expressive_narrator", "Expressive Narrator (EN)"),
                    ("English_radiant_girl", "Radiant Girl (EN, female)"),
                    ("English_PassionateWarrior", "Passionate Warrior (EN, male)"),
                ],
                "zh": [
                    ("Chinese_audiobook_male", "Chinese audiobook male"),
                    ("Chinese_audiobook_female", "Chinese audiobook female"),
                ],
            },
        })

    return engines


def _dynamic_provider_engine(
    endpoint: str,
    api_key: str,
    provider: str,
    engine_id: str,
    label: str,
) -> Dict[str, Any] | None:
    voices = _voices_from_router(endpoint, api_key, provider)
    if not voices:
        return None
    first_lang = next(iter(voices))
    default_voice = voices[first_lang][0][0]
    return {
        "id": engine_id,
        "label": label,
        "default": default_voice,
        "defaultModel": default_voice,
        "backend": "9router",
        "provider": provider,
        "voices": voices,
    }


def nine_router_tts_engines(cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    endpoint = _endpoint_from_cfg(cfg)
    api_key = _key_from_cfg(cfg)
    now = time.time()
    if (
        _CACHE["engines"] is not None
        and _CACHE["endpoint"] == endpoint
        and now - float(_CACHE["ts"] or 0.0) < _CACHE_TTL
    ):
        return list(_CACHE["engines"]), dict(_CACHE["status"] or {})

    status: Dict[str, Any] = {
        "reachable": False,
        "endpoint": endpoint,
        "has_key": bool(api_key),
        "models_count": 0,
        "error": "",
    }
    engines: List[Dict[str, Any]] = []

    try:
        health_status, _ = _http_json(f"{_origin(endpoint)}/api/health", timeout=4)
        status["reachable"] = health_status < 500
    except Exception as exc:
        status["error"] = str(exc)

    models: List[str] = []
    if status["reachable"]:
        try:
            m_status, body = _http_json(f"{endpoint}/models/tts", api_key=api_key, timeout=12)
            if m_status < 400 and isinstance(body, dict):
                for item in body.get("data") or []:
                    mid = str((item or {}).get("id") or "").strip()
                    if mid:
                        models.append(mid)
            elif not status["error"]:
                status["error"] = f"models_tts_http_{m_status}"
        except Exception as exc:
            status["error"] = str(exc)

    status["models_count"] = len(models)
    if models:
        engines.extend(_static_9router_engines(models))

    # Voice-by-id providers are best discovered through /audio/voices. Only
    # probe providers that appear in /models/tts; otherwise catalog load can
    # spend many seconds on unreachable provider-specific discovery.
    if status["reachable"] and models:
        for provider, engine_id, label, patterns in (
            ("edge-tts", "9r:edge-tts", "Edge TTS (9Router)", (r"^edge-tts", r"^edge/")),
            ("google-tts", "9r:google-tts", "Google TTS (9Router)", (r"^google-tts", r"^gtts")),
            ("deepgram", "9r:deepgram", "Deepgram TTS (9Router)", (r"^deepgram",)),
            ("inworld", "9r:inworld", "Inworld TTS (9Router)", (r"^inworld",)),
            ("local-device", "9r:local-device", "Local Device TTS (9Router host)", (r"^local-device",)),
        ):
            if not _has_model(models, *patterns):
                continue
            eng = _dynamic_provider_engine(endpoint, api_key, provider, engine_id, label)
            if eng:
                engines.append(eng)

    seen = set()
    deduped = []
    for eng in engines:
        eid = eng.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(eng)

    _CACHE.update({
        "ts": now,
        "endpoint": endpoint,
        "engines": list(deduped),
        "status": dict(status),
    })
    return deduped, status


def all_tts_engines(cfg: Dict[str, Any], include_9router: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    local = local_tts_engines()
    if not include_9router:
        return local, {"reachable": False, "enabled": False}
    nine, status = nine_router_tts_engines(cfg)
    return local + nine, status

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

_GEMINI_TTS_VOICES: List[Tuple[str, str]] = [
    ("Zephyr", "Zephyr (female, bright)"),
    ("Puck", "Puck (male, upbeat)"),
    ("Charon", "Charon (male, informative)"),
    ("Kore", "Kore (female, firm)"),
    ("Fenrir", "Fenrir (male, excitable)"),
    ("Leda", "Leda (female, youthful)"),
    ("Orus", "Orus (male, firm)"),
    ("Aoede", "Aoede (female, breezy)"),
    ("Callirrhoe", "Callirrhoe (female, easy-going)"),
    ("Autonoe", "Autonoe (female, bright)"),
    ("Enceladus", "Enceladus (male, breathy)"),
    ("Iapetus", "Iapetus (male, clear)"),
    ("Umbriel", "Umbriel (male, easy-going)"),
    ("Algieba", "Algieba (male, smooth)"),
    ("Despina", "Despina (female, smooth)"),
    ("Erinome", "Erinome (female, clear)"),
    ("Algenib", "Algenib (male, gravelly)"),
    ("Rasalgethi", "Rasalgethi (male, informative)"),
    ("Laomedeia", "Laomedeia (female, upbeat)"),
    ("Achernar", "Achernar (female, soft)"),
    ("Alnilam", "Alnilam (male, firm)"),
    ("Schedar", "Schedar (male, even)"),
    ("Gacrux", "Gacrux (female, mature)"),
    ("Pulcherrima", "Pulcherrima (female, forward)"),
    ("Achird", "Achird (male, friendly)"),
    ("Zubenelgenubi", "Zubenelgenubi (male, casual)"),
    ("Vindemiatrix", "Vindemiatrix (female, gentle)"),
    ("Sadachbia", "Sadachbia (male, lively)"),
    ("Sadaltager", "Sadaltager (male, knowledgeable)"),
    ("Sulafat", "Sulafat (female, warm)"),
]

_GOOGLE_CLOUD_SAMPLE_VOICES: Dict[str, List[Tuple[str, str]]] = {
    "vi": [
        ("google-tts/vi-VN-Standard-A", "vi-VN Standard A (female)"),
        ("google-tts/vi-VN-Standard-B", "vi-VN Standard B (male)"),
        ("google-tts/vi-VN-Wavenet-A", "vi-VN Wavenet A (female)"),
        ("google-tts/vi-VN-Wavenet-B", "vi-VN Wavenet B (male)"),
    ],
    "en": [
        ("google-tts/en-US-Neural2-F", "en-US Neural2 F (female)"),
        ("google-tts/en-US-Neural2-J", "en-US Neural2 J (male)"),
        ("google-tts/en-US-Wavenet-F", "en-US Wavenet F (female)"),
        ("google-tts/en-US-Wavenet-D", "en-US Wavenet D (male)"),
    ],
    "zh": [
        ("google-tts/cmn-CN-Wavenet-A", "cmn-CN Wavenet A (female)"),
        ("google-tts/cmn-CN-Wavenet-B", "cmn-CN Wavenet B (male)"),
    ],
    "ja": [
        ("google-tts/ja-JP-Neural2-B", "ja-JP Neural2 B (female)"),
        ("google-tts/ja-JP-Neural2-C", "ja-JP Neural2 C (male)"),
    ],
    "ko": [
        ("google-tts/ko-KR-Neural2-A", "ko-KR Neural2 A (female)"),
        ("google-tts/ko-KR-Neural2-C", "ko-KR Neural2 C (male)"),
    ],
}


def _vieneu_preset_voices() -> List[Tuple[str, str]]:
    fallback = [
        ("Ngọc Linh", "Ngọc Linh (nữ, giọng tươi sáng)"),
        ("Ngọc Lan", "Ngọc Lan (nữ, giọng dịu dàng)"),
        ("Mỹ Duyên", "Mỹ Duyên (nữ, giọng mượt mà)"),
        ("Trúc Ly", "Trúc Ly (nữ, giọng trẻ trung)"),
        ("Gia Bảo", "Gia Bảo (nam, giọng mượt mà)"),
        ("Thái Sơn", "Thái Sơn (nam, giọng chắc khỏe)"),
        ("Đức Trí", "Đức Trí (nam, giọng rõ ràng)"),
        ("Xuân Vĩnh", "Xuân Vĩnh (nam, giọng vui tươi)"),
        ("Trọng Hữu", "Trọng Hữu (nam, giọng uyên bác)"),
        ("Bình An", "Bình An (nam, giọng điềm đạm)"),
    ]
    try:
        import json as _json
        from importlib import resources as _resources

        asset = _resources.files("vieneu").joinpath("assets/voices_v3_turbo.json")
        data = _json.loads(asset.read_text(encoding="utf-8"))
        rows = []
        for name, info in (data.get("presets") or {}).items():
            desc = str(info.get("description") or "").strip()
            label = f"{name} ({desc})" if desc else name
            rows.append((name, label))
        return rows or fallback
    except Exception:
        return fallback


def local_tts_engines() -> List[Dict[str, Any]]:
    """Return built-in/local TTS engines."""
    return [
        {
            "id": "vieneu",
            "label": "VieNeu TTS (local, tieng Viet)",
            "default": "Ngọc Linh",
            "backend": "local",
            "voices": {
                "vi": _vieneu_preset_voices(),
            },
        },
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
                    ("en-US-AvaNeural", "Ava (female, US, expressive)"),
                    ("en-US-AndrewNeural", "Andrew (male, US, expressive)"),
                    ("en-US-EmmaNeural", "Emma (female, US, multilingual)"),
                    ("en-US-BrianNeural", "Brian (male, US, multilingual)"),
                    ("en-US-JennyNeural", "Jenny (female, US)"),
                    ("en-US-AriaNeural", "Aria (female, US)"),
                    ("en-US-GuyNeural", "Guy (male, US)"),
                    ("en-US-DavisNeural", "Davis (male, US, expressive)"),
                    ("en-US-JaneNeural", "Jane (female, US, expressive)"),
                    ("en-US-JasonNeural", "Jason (male, US, expressive)"),
                    ("en-US-NancyNeural", "Nancy (female, US, expressive)"),
                    ("en-GB-SoniaNeural", "Sonia (female, UK)"),
                    ("en-GB-RyanNeural", "Ryan (male, UK)"),
                    ("en-GB-LibbyNeural", "Libby (female, UK)"),
                ],
                "zh": [
                    ("zh-CN-XiaoxiaoNeural", "Xiaoxiao (female, CN)"),
                    ("zh-CN-XiaoyiNeural", "Xiaoyi (female, CN)"),
                    ("zh-CN-YunxiNeural", "Yunxi (male, CN)"),
                    ("zh-CN-YunjianNeural", "Yunjian (male, CN)"),
                    ("zh-CN-YunxiaNeural", "Yunxia (male, CN)"),
                    ("zh-CN-YunyangNeural", "Yunyang (male, CN)"),
                ],
                "ja": [
                    ("ja-JP-NanamiNeural", "Nanami (female)"),
                    ("ja-JP-KeitaNeural", "Keita (male)"),
                    ("ja-JP-AoiNeural", "Aoi (female)"),
                    ("ja-JP-DaichiNeural", "Daichi (male)"),
                ],
                "ko": [
                    ("ko-KR-SunHiNeural", "SunHi (female)"),
                    ("ko-KR-InJoonNeural", "InJoon (male)"),
                    ("ko-KR-BongJinNeural", "BongJin (male)"),
                    ("ko-KR-GookMinNeural", "GookMin (male)"),
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
                "vi": [
                    ("vi|com.vn", "Tieng Viet (Google VN)"),
                    ("vi|com", "Tieng Viet (Google default)"),
                ],
                "en": [
                    ("en|com", "English US (Google)"),
                    ("en|co.uk", "English UK (Google)"),
                    ("en|com.au", "English AU (Google)"),
                    ("en|ca", "English CA (Google)"),
                ],
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


# Engines that can synthesize (almost) any language — used as fallback when the
# chosen engine can't speak the target language. edge-tts covers every entry in
# _LANGS; gTTS is the simpler last resort.
_UNIVERSAL_FALLBACKS = ("edge-tts", "gtts")


def _local_engine_by_id(engine_id: str) -> Dict[str, Any] | None:
    eid = (engine_id or "").strip().lower()
    for eng in local_tts_engines():
        if eng["id"] == eid:
            return eng
    return None


def engine_voices_for_lang(engine: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    """Voices an engine offers for `lang`. Falls back to its `multi` bucket for
    multilingual engines (ElevenLabs, Fish Audio, 9Router)."""
    voices = engine.get("voices") or {}
    rows = voices.get(lang) or voices.get("multi") or []
    return [tuple(v) for v in rows]


def resolve_engine_voice(
    engine_id: str,
    voice_id: str,
    lang: str,
    cfg: Dict[str, Any] | None = None,
) -> Tuple[str, str, bool, str]:
    """Pick an (engine, voice) pair that can actually speak `lang`.

    Keeps the user's choice when it already supports the target language;
    otherwise auto-selects the engine's default voice for that language, and
    finally falls back to a universal engine (edge-tts) when the chosen engine
    can't speak it at all.

    Returns ``(engine_id, voice_id, changed, note)`` where ``changed`` is True
    when the selection was adjusted and ``note`` is a short human-readable
    description of what changed.
    """
    lang = (lang or "vi").strip().lower() or "vi"
    eid = (engine_id or "").strip().lower()
    vid = (voice_id or "").strip()

    # 9Router / MiniMax models are multilingual — trust the caller's selection.
    if eid == "9router" or eid.startswith("9r:") or eid == "minimax":
        return (eid or "edge-tts"), vid, False, ""

    eng = _local_engine_by_id(eid)
    if eng is not None:
        rows = engine_voices_for_lang(eng, lang)
        if rows:
            valid_ids = {r[0] for r in rows}
            if vid in valid_ids:
                return eid, vid, False, ""
            default_voice = eng.get("default")
            new_voice = default_voice if default_voice in valid_ids else rows[0][0]
            return eid, new_voice, True, f"voice→{new_voice}"

    # Engine cannot speak this language → fall back to a universal engine.
    for fb in _UNIVERSAL_FALLBACKS:
        if fb == eid:
            continue
        fb_eng = _local_engine_by_id(fb)
        rows = engine_voices_for_lang(fb_eng, lang) if fb_eng else []
        if rows:
            return fb, rows[0][0], True, f"engine→{fb}, voice→{rows[0][0]}"

    # Last resort: keep whatever we were given.
    return (eid or "edge-tts"), vid, False, ""


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


# Voice presets per 9Router provider. Mirrors the Chat Bot tab — each model's
# provider decides which voices apply. Providers not listed here (edge-tts,
# google-tts, deepgram, ...) use the model's own default voice, so the UI
# just offers a "default" entry for them.
_PROVIDER_TTS_VOICES: Dict[str, List[Tuple[str, str]]] = {
    "openai": [
        ("nova", "Nova (multilingual)"),
        ("shimmer", "Shimmer (multilingual)"),
        ("alloy", "Alloy (neutral)"),
        ("echo", "Echo (male)"),
        ("onyx", "Onyx (male)"),
        ("fable", "Fable (storyteller)"),
    ],
    "gemini": _GEMINI_TTS_VOICES,
    "google-tts": [
        row
        for rows in _GOOGLE_CLOUD_SAMPLE_VOICES.values()
        for row in rows
    ],
    "elevenlabs": [
        ("21m00Tcm4TlvDq8ikWAM", "Rachel (female)"),
        ("EXAVITQu4vr4xnSDxMaL", "Bella (female, soft)"),
        ("AZnzlk1XvdvUeBnXmlld", "Domi (female)"),
        ("ErXwobaYiN019PkySvjV", "Antoni (male)"),
        ("pNInz6obpgDQGcFmaJgB", "Adam (male)"),
    ],
    "minimax": [
        ("English_expressive_narrator", "Expressive Narrator (EN)"),
        ("English_radiant_girl", "Radiant Girl (EN, female)"),
        ("English_PassionateWarrior", "Passionate Warrior (EN, male)"),
        ("Chinese_audiobook_male", "Chinese audiobook male"),
        ("Chinese_audiobook_female", "Chinese audiobook female"),
    ],
}


def _provider_of(model_id: str) -> str:
    """Top-level provider for a 9Router model id.

    "openai/tts-1" -> "openai"; "openrouter/openai/tts-1" -> "openai";
    "el/eleven_multilingual_v2" -> "elevenlabs"; "gemini/...-tts" -> "gemini".
    """
    parts = [p for p in str(model_id or "").split("/") if p]
    if not parts:
        return ""
    p = parts[0].lower()
    if p == "openrouter" and len(parts) > 1:
        p = parts[1].lower()
    if p == "el":
        return "elevenlabs"
    return p


def _consolidated_9router_engine(models: List[str]) -> Dict[str, Any] | None:
    """Build ONE "9Router TTS" engine carrying the live model list (grouped by
    provider) plus a per-provider voice map — mirroring the Chat Bot tab's
    Text-to-Speech panel (Model + Voice dropdowns). Returns None when 9Router
    exposes no TTS models, so the UI shows nothing rather than a fake entry.
    """
    if not models:
        return None

    model_items: List[Dict[str, str]] = []
    for m in models:
        grp = (m.split("/", 1)[0] or "9router").lower()
        model_items.append({
            "id": m,
            "label": m,
            "group": grp,
            "provider": _provider_of(m),
        })

    default_model = _has_model(models, r"^openai/(?:tts|gpt-4o.*tts)") or models[0]
    voices_by_provider = {
        prov: [list(v) for v in rows]
        for prov, rows in _PROVIDER_TTS_VOICES.items()
    }
    default_voices = voices_by_provider.get(_provider_of(default_model)) \
        or voices_by_provider["openai"]

    return {
        "id": "9router",
        "label": "9Router TTS",
        "default": default_voices[0][0] if default_voices else "",
        "defaultModel": default_model,
        "backend": "9router",
        "provider": "9router",
        "models": model_items,
        "voicesByProvider": voices_by_provider,
        # `multi` keeps _engineSupportsLang() happy for every target language.
        "voices": {"multi": default_voices},
    }


def _static_9router_engines(models: List[str]) -> List[Dict[str, Any]]:
    engine = _consolidated_9router_engine(models)
    return [engine] if engine else []


def _shortcut_9router_engines(models: List[str]) -> List[Dict[str, Any]]:
    """Provider-specific shortcuts for the Transcribe/TTS UI.

    The consolidated 9Router selector is still the most flexible option. These
    shortcuts expose common provider groups directly as normal engine entries.
    """
    engines: List[Dict[str, Any]] = []

    gemini_model = _has_model(
        models,
        r"^gemini/(?:gemini-3\.1.*tts|gemini-2\.5.*tts)",
        r"gemini.*tts",
    )
    if gemini_model:
        engines.append({
            "id": "9r:gemini",
            "label": "Google Gemini TTS (9Router, cam xuc)",
            "default": "Kore",
            "defaultModel": gemini_model,
            "backend": "9router",
            "provider": "gemini",
            "voices": {"multi": _GEMINI_TTS_VOICES},
        })

    google_model = _has_model(models, r"^(?:google-tts|google/.+tts|gcp/.+tts)")
    if google_model:
        voices = {
            lang: rows
            for lang, rows in _GOOGLE_CLOUD_SAMPLE_VOICES.items()
            if rows
        }
        voices.setdefault("multi", _PROVIDER_TTS_VOICES["google-tts"])
        engines.append({
            "id": "9r:google-tts",
            "label": "Google Cloud TTS (9Router)",
            "default": _PROVIDER_TTS_VOICES["google-tts"][0][0],
            "defaultModel": google_model,
            "backend": "9router",
            "provider": "google-tts",
            "voices": voices,
        })

    edge_model = _has_model(models, r"^edge-tts(?:/|$)", r"microsoft.*tts", r"azure.*tts")
    if edge_model:
        edge = _local_engine_by_id("edge-tts") or {}
        engines.append({
            "id": "9r:edge-tts",
            "label": "Microsoft Edge TTS (9Router)",
            "default": "vi-VN-HoaiMyNeural",
            "defaultModel": edge_model,
            "backend": "9router",
            "provider": "edge-tts",
            "voices": edge.get("voices") or {},
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
        engines.extend(_shortcut_9router_engines(models))

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

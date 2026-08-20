"""Shared TTS engine/voice catalogue.

The frontend expects this shape:
  {id, label, default, backend, voices: {lang: [[voice_id, label], ...]}}
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
            "label": "VieNeu TTS",
            "default": "Ngọc Linh",
            "backend": "local",
            "voices": {
                "vi": _vieneu_preset_voices(),
            },
        },
        {
            "id": "edge-tts",
            "label": "Edge TTS",
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
            "label": "FPT AI",
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
            "label": "ElevenLabs",
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
            "label": "Fish Audio",
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
            "id": "omnivoice",
            "label": "OmniVoice (Zero-Shot / Multi-Language)",
            "default": "default",
            "backend": "local",
            "voices": {
                "multi": [
                    ("default", "OmniVoice Default (Tự nhiên / Auto)"),
                    ("female_warm", "OmniVoice Nữ (Ấm áp)"),
                    ("female_bright", "OmniVoice Nữ (Tươi sáng)"),
                    ("male_deep", "OmniVoice Nam (Trầm ấm)"),
                    ("male_energetic", "OmniVoice Nam (Năng động)"),
                ],
                "vi": [
                    ("default", "OmniVoice Tiếng Việt (Tự nhiên)"),
                    ("female_warm", "OmniVoice Tiếng Việt (Nữ nhẹ nhàng)"),
                    ("male_deep", "OmniVoice Tiếng Việt (Nam truyền cảm)"),
                ],
                "en": [
                    ("default", "OmniVoice English (Default)"),
                    ("female_bright", "OmniVoice English (Female Bright)"),
                    ("male_deep", "OmniVoice English (Male Deep)"),
                ],
                "zh": [
                    ("default", "OmniVoice Chinese (Default)"),
                ],
                "ja": [
                    ("default", "OmniVoice Japanese (Default)"),
                ],
                "ko": [
                    ("default", "OmniVoice Korean (Default)"),
                ],
                "th": [
                    ("default", "OmniVoice Thai (Default)"),
                ],
                "fr": [
                    ("default", "OmniVoice French (Default)"),
                ],
                "de": [
                    ("default", "OmniVoice German (Default)"),
                ],
                "es": [
                    ("default", "OmniVoice Spanish (Default)"),
                ],
                "ru": [
                    ("default", "OmniVoice Russian (Default)"),
                ],
            },
        },
        {
            "id": "gtts",
            "label": "Google gTTS",
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
_UNIVERSAL_FALLBACKS = ("edge-tts", "omnivoice", "gtts")


def _local_engine_by_id(engine_id: str) -> Dict[str, Any] | None:
    eid = (engine_id or "").strip().lower()
    for eng in local_tts_engines():
        if eng["id"] == eid:
            return eng
    return None


def engine_voices_for_lang(engine: Dict[str, Any], lang: str) -> List[Tuple[str, str]]:
    """Voices an engine offers for `lang`. Falls back to its `multi` bucket for
    multilingual engines (ElevenLabs, Fish Audio)."""
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

    # MiniMax / OmniVoice models are multilingual — trust the caller's selection.
    if eid in ("minimax", "omnivoice"):
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


def dtrouter_tts_engines(cfg: Dict[str, Any] | None = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Legacy stub returning empty DTRouter engines."""
    return [], {"reachable": False, "models_count": 0}


def all_tts_engines(cfg: Dict[str, Any] | None = None, include_dtrouter: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    return local_tts_engines(), {"reachable": False, "enabled": False}


def clear_tts_catalog_cache():
    global _CACHE
    _CACHE["ts"] = 0.0
    _CACHE["engines"] = None
    _CACHE["status"] = None

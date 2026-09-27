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
from functools import lru_cache


@lru_cache(maxsize=2)
def _installed_vieneu_catalog(mode="turbo"):
    try:
        from importlib import resources
        return json.loads(resources.files('vieneu').joinpath(f'assets/voices_v3_{mode}.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


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
        ("Minh Quân Pro", "[Tuyển chọn] Minh Quân Pro (Nam · Bắc · Phong cách tự nhiên)"),
        ("Phạm Tuyên", "Phạm Tuyên (Nam · Bắc · Phong cách tự nhiên)"),
        ("Mai Anh", "[Tuyển chọn] Mai Anh (Nữ · Bắc · Phong cách tin tức)"),
        ("Trúc Ly", "[Tuyển chọn] Trúc Ly (Nữ · Bắc · Phong cách tự nhiên)"),
        ("Thanh Bình", "Thanh Bình (Nam · Bắc · Phong cách kể chuyện)"),
        ("Thùy Dung", "[Tuyển chọn] Thùy Dung (Nữ · Nam · Phong cách tin tức)"),
        ("Anh Khôi", "[Tuyển chọn] Anh Khôi (Nam · Bắc · Phong cách kể chuyện)"),
        ("Thiền Tâm Đức", "[Tuyển chọn] Thiền Tâm Đức (Nam · Bắc · Phong cách kể chuyện)"),
        ("Ngọc Huyền", "[Tuyển chọn] Ngọc Huyền (Nữ · Bắc · Giọng đọc tự nhiên)"),
        ("Quang Sơn", "[Tuyển chọn] Quang Sơn (Nam · Trung · Phong cách tự nhiên)"),
        ("Ngọc Trân", "[Tuyển chọn] Ngọc Trân (Nữ · Trung · Phong cách tự nhiên)"),
        ("Minh Đức", "Minh Đức (Nam · Bắc · Phong cách tin tức)"),
        ("Thái Sơn", "Thái Sơn (Nam · Nam · Phong cách kể chuyện)"),
        ("Xuân Vĩnh", "Xuân Vĩnh (Nam · Bắc · Phong cách tự nhiên)"),
        ("Ngọc Linh", "Ngọc Linh (Nữ · Bắc · Phong cách kể chuyện)"),
        ("Đoan Trang", "Đoan Trang (Nữ · Bắc · Phong cách tự nhiên)"),
        ("Thục Đoan", "Thục Đoan (Nữ · Nam · Phong cách kể chuyện)"),
        ("Minh Triết", "Minh Triết (Nam · Nam · Phong cách tin tức)"),
        ("Mỹ Duyên", "Mỹ Duyên (Nữ · Nam · Phong cách đọc truyện)"),
        ("Quỳnh Anh", "Quỳnh Anh (Nữ · Bắc · Phong cách đọc truyện)"),
        ("Đức Trí", "Đức Trí (Nam · Nam · Phong cách đọc truyện)"),
        ("Kim Thanh", "Kim Thanh (Nữ · Nam · Phong cách đọc truyện)"),
        ("Adam", "Adam (Nam · Nam · Giọng đọc tự nhiên)"),
        ("Adam bựa", "[Tuyển chọn] Adam bựa (Nam · Bắc · Phong cách tự nhiên)"),
        ("Mạnh Dũng", "Mạnh Dũng (Nam · Bắc · Phong cách tự nhiên)"),
    ]
    try:
        import json as _json
        from importlib import resources as _resources

        asset = _resources.files("vieneu").joinpath("assets/voices_v3_turbo.json")
        data = _json.loads(asset.read_text(encoding="utf-8"))
        presets = data.get("presets") or {}
        sorted_items = sorted(
            presets.items(),
            key=lambda kv: (kv[1].get("featured") is None, kv[1].get("featured") or 0)
        )
        rows = []
        for name, info in sorted_items:
            desc = str(info.get("description") or "").strip()
            feat = "[Tuyển chọn] " if info.get("featured") is not None else ""
            label = f"{feat}{name} ({desc})" if desc else f"{feat}{name}"
            rows.append((name, label))
        return rows or fallback
    except Exception:
        return fallback


def local_tts_engines() -> List[Dict[str, Any]]:
    """Return built-in/local TTS engines."""
    engines = [
        {
            "id": "vieneu",
            "label": "VieNeu v3 Turbo (local, 48 kHz)",
            "default": "Minh Quân Pro",
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
    # Use this runtime's names: SDK releases may rename the same voice.
    engines[0]['default'] = _installed_vieneu_catalog().get('default_voice') or engines[0]['default']
    voices = engines[0]["voices"]["vi"]
    if engines[0]["default"] not in {v[0] for v in voices}:
        engines[0]["default"] = voices[0][0]
    turbo = engines[0]
    turbo['label'] = 'VieNeu v3 Turbo — Tự động CPU/GPU (48 kHz)'
    variants = [turbo]
    for eid, label in [('vieneu-cpu', 'VieNeu v3 Turbo — CPU (48 kHz)'),
                       ('vieneu-gpu', 'VieNeu v3 Turbo — GPU CUDA (48 kHz)')]:
        variants.append(dict(turbo, id=eid, label=label))
    nano = _installed_vieneu_catalog('nano')
    presets = nano.get('presets', {})
    if presets:
        variants.append(dict(turbo, id='vieneu-nano', label='VieNeu v3 Nano — CPU (preview, 24 kHz)',
                             default=nano.get('default_voice') or next(iter(presets)),
                             voices={'vi': [(name, name) for name in presets]}))
    return variants


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


_VOICE_ALIASES: Dict[str, str] = {
    "Minh Quân Pro": "Minh Quân Pro",
    "Minh Quân": "Minh Quân Pro",
    "Ngọc Lan": "Ngọc Huyền",
    "Gia Bảo": "Anh Khôi",
    "Trọng Hữu": "Thiền Tâm Đức",
    "Bình An": "Thanh Bình",
    "Tuyen": "Phạm Tuyên",
    "Tuyên": "Phạm Tuyên",
    "Binh": "Thanh Bình",
    "Bình": "Thanh Bình",
    "Ly": "Trúc Ly",
    "Ngoc": "Ngọc Linh",
    "Ngọc": "Ngọc Linh",
    "Doan": "Thục Đoan",
    "Đoan": "Thục Đoan",
    "Vinh": "Xuân Vĩnh",
    "Vĩnh": "Xuân Vĩnh",
}


def resolve_engine_voice(
    engine_id: str,
    voice_id: str,
    lang: str,
    cfg: Dict[str, Any] | None = None,
) -> Tuple[str, str, bool, str]:
    """Normalize every saved selection to local VieNeu and a valid preset."""
    vid = (voice_id or "").strip()
    eid = (engine_id or "").strip().lower()
    if eid not in {"vieneu", "vieneu-cpu", "vieneu-gpu", "vieneu-nano"}:
        eid = "vieneu"
    vieneu = _local_engine_by_id(eid)
    rows = engine_voices_for_lang(vieneu, "vi") if vieneu else []
    valid_ids = {row[0] for row in rows}

    # 1. Direct match
    if vid in valid_ids:
        return eid, vid, (engine_id or "").strip().lower() != "vieneu", "engine→vieneu"

    # 2. Alias match (e.g. Ngọc Lan -> Ngọc Huyền, Minh Quân -> Minh Quân Pro)
    installed_aliases = {
        alias: name
        for name, info in _installed_vieneu_catalog().get('presets', {}).items()
        for alias in info.get('aliases', [])
    }
    resolved_alias = installed_aliases.get(vid) or _VOICE_ALIASES.get(vid)
    if resolved_alias and resolved_alias in valid_ids:
        return eid, resolved_alias, True, f"alias: {vid}→{resolved_alias}"

    # 3. Fallback to default
    default_voice = str((vieneu or {}).get("default") or "Minh Quân Pro")
    return eid, default_voice, True, f"voice '{vid}' không tồn tại, tự chọn: {default_voice}"


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

/* ── app.js — Entry point ────────────────────────────────────────────────── */

window._trSelectedFile = null;

const TTS_VOICE_PRESETS = {
  vieneu: [
    { value: 'Ngọc Linh', label: 'Ngọc Linh (VieNeu - Nữ, tươi sáng)' },
    { value: 'Ngọc Lan', label: 'Ngọc Lan (VieNeu - Nữ, dịu dàng)' },
    { value: 'Mỹ Duyên', label: 'Mỹ Duyên (VieNeu - Nữ, mượt mà)' },
    { value: 'Trúc Ly', label: 'Trúc Ly (VieNeu - Nữ, trẻ trung)' },
    { value: 'Gia Bảo', label: 'Gia Bảo (VieNeu - Nam, mượt mà)' },
    { value: 'Thái Sơn', label: 'Thái Sơn (VieNeu - Nam, chắc khỏe)' },
    { value: 'Đức Trí', label: 'Đức Trí (VieNeu - Nam, rõ ràng)' },
    { value: 'Xuân Vĩnh', label: 'Xuân Vĩnh (VieNeu - Nam, vui tươi)' },
    { value: 'Trọng Hữu', label: 'Trọng Hữu (VieNeu - Nam, uyên bác)' },
    { value: 'Bình An', label: 'Bình An (VieNeu - Nam, điềm đạm)' },
  ],
  'fpt-ai': [
    { value: 'banmai', label: 'Ban Mai (FPT - Nữ)' },
    { value: 'thuminh', label: 'Thu Minh (FPT - Nữ)' },
    { value: 'myan', label: 'My An (FPT - Nữ)' },
    { value: 'leminh', label: 'Le Minh (FPT - Nam)' },
  ],
  'edge-tts': [
    { value: 'vi-VN-HoaiMyNeural', label: 'Hoài My (Microsoft - Nữ)' },
    { value: 'vi-VN-NamMinhNeural', label: 'Nam Minh (Microsoft - Nam)' },
    { value: 'en-US-AvaNeural', label: 'Ava (Microsoft - Nữ, expressive)' },
    { value: 'en-US-AndrewNeural', label: 'Andrew (Microsoft - Nam, expressive)' },
    { value: 'en-US-EmmaNeural', label: 'Emma (Microsoft - Nữ)' },
    { value: 'en-US-BrianNeural', label: 'Brian (Microsoft - Nam)' },
  ],
  '9r:gemini': [
    { value: 'Kore', label: 'Kore (Google Gemini - Nữ, chắc)' },
    { value: 'Puck', label: 'Puck (Google Gemini - Nam, vui)' },
    { value: 'Aoede', label: 'Aoede (Google Gemini - Nữ, ấm)' },
    { value: 'Charon', label: 'Charon (Google Gemini - Nam, dẫn chuyện)' },
    { value: 'Zephyr', label: 'Zephyr (Google Gemini - Nữ, sáng)' },
    { value: 'Laomedeia', label: 'Laomedeia (Google Gemini - Nữ, hào hứng)' },
    { value: 'Achird', label: 'Achird (Google Gemini - Nam, thân thiện)' },
  ],
  '9r:google-tts': [
    { value: 'google-tts/vi-VN-Wavenet-A', label: 'vi-VN Wavenet A (Google - Nữ)' },
    { value: 'google-tts/vi-VN-Wavenet-B', label: 'vi-VN Wavenet B (Google - Nam)' },
    { value: 'google-tts/en-US-Neural2-F', label: 'en-US Neural2 F (Google - Nữ)' },
    { value: 'google-tts/en-US-Neural2-J', label: 'en-US Neural2 J (Google - Nam)' },
  ],
  '9r:edge-tts': [
    { value: 'vi-VN-HoaiMyNeural', label: 'Hoài My (Microsoft 9Router - Nữ)' },
    { value: 'vi-VN-NamMinhNeural', label: 'Nam Minh (Microsoft 9Router - Nam)' },
  ],
  'elevenlabs': [
    { value: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel (ElevenLabs - Nữ EN)' },
    { value: 'AZnzlk1XvdvUeBnXmlld', label: 'Domi (ElevenLabs - Nữ EN)' },
    { value: 'EXAVITQu4vr4xnSDxMaL', label: 'Bella (ElevenLabs - Nữ EN)' },
    { value: 'ErXwobaYiN019PkySvjV', label: 'Antoni (ElevenLabs - Nam EN)' },
    { value: 'MF3mGyEYCl7XYWbV9V6O', label: 'Elli (ElevenLabs - Nữ EN)' },
    { value: 'TxGEqnHWrfWFTfGW9XjX', label: 'Josh (ElevenLabs - Nam EN)' },
    { value: 'VR6AewLTigWG4xSOukaG', label: 'Arnold (ElevenLabs - Nam EN)' },
    { value: 'pNInz6obpgDQGcFmaJgB', label: 'Adam (ElevenLabs - Nam EN)' },
    { value: 'yoZ06aMxZJJ28mfd3POQ', label: 'Sam (ElevenLabs - Nam EN)' },
  ],
  'minimax': [
    { value: 'Calm_Woman',      label: 'Calm Woman (MiniMax - Nữ)' },
    { value: 'Gentle_Woman',    label: 'Gentle Woman (MiniMax - Nữ)' },
    { value: 'Lively_Girl',     label: 'Lively Girl (MiniMax - Nữ)' },
    { value: 'Soft_Female',     label: 'Soft Female (MiniMax - Nữ)' },
    { value: 'Confident_Man',   label: 'Confident Man (MiniMax - Nam)' },
    { value: 'Deep_Voice_Man',  label: 'Deep Voice Man (MiniMax - Nam)' },
    { value: 'Energetic_Male',  label: 'Energetic Male (MiniMax - Nam)' },
    { value: 'Friendly_Person', label: 'Friendly Person (MiniMax)' },
  ],
  gtts: [
    { value: 'vi|com.vn', label: 'Tiếng Việt (Google gTTS VN)' },
    { value: 'vi|com', label: 'Tiếng Việt (Google gTTS default)' },
    { value: 'en|com', label: 'English US (Google gTTS)' },
    { value: 'en|co.uk', label: 'English UK (Google gTTS)' },
    { value: 'en|com.au', label: 'English AU (Google gTTS)' },
  ],
};

const TTS_DEFAULT_VOICE = {
  vieneu: 'Ngọc Linh',
  'fpt-ai':  'banmai',
  'edge-tts': 'vi-VN-HoaiMyNeural',
  '9r:gemini': 'Kore',
  '9r:google-tts': 'google-tts/vi-VN-Wavenet-A',
  '9r:edge-tts': 'vi-VN-HoaiMyNeural',
  'elevenlabs': '21m00Tcm4TlvDq8ikWAM',
  'minimax': 'Calm_Woman',
  gtts: 'vi|com.vn',
};

/* ── Managed Voices Helpers for Process Page ── */
const TRANSCRIBE_CUSTOM_VOICE_KEY = 'toolvideo.transcribe.customVoices.v1';

function _trVoiceGenderFromLabel(label) {
  const raw = String(label || '').toLowerCase();
  if (raw.includes('nữ') || raw.includes('female') || raw.includes('woman') || raw.includes('girl')) return 'female';
  if (raw.includes('nam') || raw.includes('male') || raw.includes('man') || raw.includes('boy')) return 'male';
  return 'other';
}

function _trNormalizeVoiceItem(raw, idx = 0) {
  const engine = String(raw?.engine || 'vieneu').trim();
  const voice = String(raw?.voice || raw?.value || '').trim();
  const label = String(raw?.label || raw?.name || voice || 'Giọng mới').trim();
  const lang = String(raw?.lang || 'vi').trim();
  return {
    id: String(raw?.id || `custom_${Date.now()}_${idx}`).trim(),
    label,
    engine,
    voice,
    lang,
    gender: String(raw?.gender || _trVoiceGenderFromLabel(`${label} ${raw?.description || ''}`)).trim(),
    favorite: !!raw?.favorite,
    emotion: String(raw?.emotion || 'default').trim(),
    rate: String(raw?.rate || '+0%').trim(),
    pitch: String(raw?.pitch || '+0Hz').trim(),
    text: String(raw?.text || '').trim(),
    persona: String(raw?.persona || raw?.description || '').trim(),
    ref_audio: String(raw?.ref_audio || '').trim(),
    source: String(raw?.source || 'Tự thêm').trim(),
    readonly: !!raw?.readonly,
    custom: !!raw?.custom,
  };
}

function _getTranscribeCustomVoices() {
  try {
    const rows = JSON.parse(localStorage.getItem(TRANSCRIBE_CUSTOM_VOICE_KEY) || '[]');
    if (!Array.isArray(rows)) return [];
    return rows.map((item, idx) => _trNormalizeVoiceItem({ ...item, custom: true }, idx)).filter(v => v.voice);
  } catch (_) {
    return [];
  }
}

function _mergeManagedVoicePreset(engine, preset, lang = '') {
  const rows = Array.isArray(preset) ? [...preset] : [];
  const custom = _getTranscribeCustomVoices().filter(item => {
    if (String(item.engine || '').toLowerCase() !== String(engine || '').toLowerCase()) return false;
    if (!lang || !item.lang || item.lang === 'multi') return true;
    return item.lang === lang;
  });
  custom.forEach(item => {
    if (!rows.some(row => row.value === item.voice)) {
      rows.push({ value: item.voice, label: `${item.label} (${item.source || 'Tự thêm'})` });
    }
  });
  return rows;
}

/* ── Edge TTS voices per target language ── */
let TTS_ENGINE_CATALOG = null;
let TTS_ENGINE_CATALOG_PROMISE = null;

function _catalogVoicesToPreset(list) {
  return (list || []).map(v => Array.isArray(v)
    ? { value: v[0], label: v[1] || v[0] }
    : { value: v.id || v.value || v.model || '', label: v.label || v.name || v.id || v.value || v.model || '' }
  ).filter(v => v.value);
}

function _engineSupportsLang(eng, lang) {
  if (!eng || !eng.voices) return false;
  const id = String(eng.id || '').toLowerCase();
  if (Array.isArray(eng.voices[lang]) && eng.voices[lang].length) return true;
  if (Array.isArray(eng.voices.multi) && eng.voices.multi.length) return true;
  if (id === 'edge-tts' && typeof EDGE_TTS_BY_LANG !== 'undefined' && EDGE_TTS_BY_LANG[lang]) return true;
  if (id === 'gtts' && typeof GTTS_BY_LANG !== 'undefined' && GTTS_BY_LANG[lang]) return true;
  return false;
}

function _getTtsTargetLangForSelect(engineSelectId) {
  const id = String(engineSelectId || '');
  if (id.startsWith('tr-')) return document.getElementById('tr-tts-lang')?.value || 'vi';
  if (id.startsWith('mv-')) return document.getElementById('mv-lang')?.value || 'vi';
  if (id.startsWith('vp-')) return 'vi';
  return document.getElementById('proc-target-lang')?.value || 'vi';
}

function _pickTtsEngineForLang(lang, currentId) {
  const catalog = TTS_ENGINE_CATALOG || [];
  const current = catalog.find(e => String(e.id || '').toLowerCase() === String(currentId || '').toLowerCase());
  if (current && _engineSupportsLang(current, lang)) return current;
  for (const id of ['vieneu', 'edge-tts', 'gtts', 'elevenlabs', 'fpt-ai']) {
    const found = catalog.find(e => String(e.id || '').toLowerCase() === id && _engineSupportsLang(e, lang));
    if (found) return found;
  }
  return catalog.find(e => _engineSupportsLang(e, lang)) || catalog[0] || null;
}

function _ensureTtsEngineForLang(engineSelectId, lang) {
  const sel = document.getElementById(engineSelectId);
  if (!sel || !(TTS_ENGINE_CATALOG || []).length) return sel?.value || '';
  const next = _pickTtsEngineForLang(lang, sel.value);
  if (next && sel.value !== next.id) sel.value = next.id;
  return sel.value || next?.id || '';
}

function _refreshTtsEngineSelects() {
  let catalog = TTS_ENGINE_CATALOG || [];
  if (!catalog.length) return;

  const cfg = window._loadedCfg || {};
  const isTtsEngineActive = (eng) => {
    if (!eng) return false;
    if (eng.backend === '9router') {
      const nineRouterKey = cfg.nine_router?.api_key;
      return !!(nineRouterKey && nineRouterKey.trim().length > 0);
    }
    if (eng.id === 'fpt-ai') {
      const key = cfg.video_process?.fpt_api_key;
      return !!(key && key.trim().length > 0);
    }
    if (eng.id === 'elevenlabs') {
      const key = cfg.video_process?.elevenlabs_api_key;
      return !!(key && key.trim().length > 0);
    }
    if (eng.id === 'fish-audio') {
      const key = cfg.video_process?.fish_api_key;
      return !!(key && key.trim().length > 0);
    }
    return true; // vieneu, edge-tts, gtts require no API keys
  };

  catalog = catalog.filter(isTtsEngineActive);

  ['proc-tts-engine', 'vp-tts-engine', 'tr-tts-engine', 'mv-tts-engine'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const current = sel.value;
    const lang = _getTtsTargetLangForSelect(id);
    const fallback = _pickTtsEngineForLang(lang, current);
    sel.innerHTML = '';
    const localEngs = catalog.filter(e => e.backend !== '9router');
    const nineEngs = catalog.filter(e => e.backend === '9router');
    const addOpt = (parent, eng) => {
      const opt = document.createElement('option');
      opt.value = eng.id;
      opt.textContent = eng.label || eng.id;
      if (eng.id === current || (!current && fallback && eng.id === fallback.id)) {
        opt.selected = true;
      }
      parent.appendChild(opt);
    };
    if (nineEngs.length) {
      const gLocal = document.createElement('optgroup');
      gLocal.label = 'Local';
      localEngs.forEach(e => addOpt(gLocal, e));
      sel.appendChild(gLocal);
      const gNine = document.createElement('optgroup');
      gNine.label = '9Router';
      nineEngs.forEach(e => addOpt(gNine, e));
      sel.appendChild(gNine);
    } else {
      localEngs.forEach(e => addOpt(sel, e));
    }
    // Giữ giá trị hiện tại nếu còn trong catalog, không thì dùng fpt-ai hoặc edge-tts làm default
    const currentEngine = catalog.find(e => e.id === current);
    const targetValue = currentEngine && _engineSupportsLang(currentEngine, lang)
      ? current
      : fallback?.id || '';
    sel.value = targetValue;
    if (typeof _handle9RouterEngine === 'function') {
      _handle9RouterEngine(id, id.replace('-tts-engine', '-tts-voice'));
    }
  });
}

async function _loadTtsEngineCatalog() {
  if (TTS_ENGINE_CATALOG) return TTS_ENGINE_CATALOG;
  if (TTS_ENGINE_CATALOG_PROMISE) return TTS_ENGINE_CATALOG_PROMISE;
  TTS_ENGINE_CATALOG_PROMISE = (async () => {
    try {
      const [rEng, rCfg] = await Promise.all([
        fetch('/api/tts/engines'),
        fetch('/api/config')
      ]);
      const jEng = await rEng.json();
      const jCfg = await rCfg.json();
      if (jCfg) {
        window._loadedCfg = jCfg;
      }
      if (jEng?.ok && Array.isArray(jEng.engines) && jEng.engines.length) {
        TTS_ENGINE_CATALOG = jEng.engines;
        window._ttsNineRouterStatus = jEng.nine_router || {};
        // Dùng requestAnimationFrame để đảm bảo DOM đã render xong trước khi refresh
        requestAnimationFrame(() => {
          _refreshTtsEngineSelects();
          _onTargetLangChange();
          _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
          _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
        });
      }
    } catch (_) {}
    return TTS_ENGINE_CATALOG || [];
  })();
  return TTS_ENGINE_CATALOG_PROMISE;
}

const EDGE_TTS_BY_LANG = {
  vi: [
    { value: 'vi-VN-HoaiMyNeural', label: 'Hoài My (Nữ - VN)' },
    { value: 'vi-VN-NamMinhNeural', label: 'Nam Minh (Nam - VN)' },
  ],
  en: [
    { value: 'en-US-AvaNeural', label: 'Ava (Female - US, expressive)' },
    { value: 'en-US-AndrewNeural', label: 'Andrew (Male - US, expressive)' },
    { value: 'en-US-EmmaNeural', label: 'Emma (Female - US)' },
    { value: 'en-US-BrianNeural', label: 'Brian (Male - US)' },
    { value: 'en-US-JennyNeural', label: 'Jenny (Female - US)' },
    { value: 'en-US-GuyNeural', label: 'Guy (Male - US)' },
    { value: 'en-US-AriaNeural', label: 'Aria (Female - US)' },
    { value: 'en-US-DavisNeural', label: 'Davis (Male - US)' },
    { value: 'en-US-JaneNeural', label: 'Jane (Female - US)' },
    { value: 'en-US-JasonNeural', label: 'Jason (Male - US)' },
    { value: 'en-US-NancyNeural', label: 'Nancy (Female - US)' },
    { value: 'en-GB-SoniaNeural', label: 'Sonia (Female - UK)' },
    { value: 'en-GB-RyanNeural', label: 'Ryan (Male - UK)' },
    { value: 'en-GB-LibbyNeural', label: 'Libby (Female - UK)' },
  ],
  ja: [
    { value: 'ja-JP-NanamiNeural', label: 'Nanami (女性 - JP)' },
    { value: 'ja-JP-KeitaNeural', label: 'Keita (男性 - JP)' },
    { value: 'ja-JP-AoiNeural', label: 'Aoi (女性 - JP)' },
    { value: 'ja-JP-DaichiNeural', label: 'Daichi (男性 - JP)' },
  ],
  ko: [
    { value: 'ko-KR-SunHiNeural', label: 'Sun-Hi (여성 - KR)' },
    { value: 'ko-KR-InJoonNeural', label: 'InJoon (남성 - KR)' },
    { value: 'ko-KR-BongJinNeural', label: 'BongJin (남성 - KR)' },
    { value: 'ko-KR-GookMinNeural', label: 'GookMin (남성 - KR)' },
  ],
  th: [
    { value: 'th-TH-PremwadeeNeural', label: 'Premwadee (หญิง - TH)' },
    { value: 'th-TH-NiwatNeural', label: 'Niwat (ชาย - TH)' },
  ],
  id: [
    { value: 'id-ID-GadisNeural', label: 'Gadis (Wanita - ID)' },
    { value: 'id-ID-ArdiNeural', label: 'Ardi (Pria - ID)' },
  ],
  es: [
    { value: 'es-ES-ElviraNeural', label: 'Elvira (Mujer - ES)' },
    { value: 'es-ES-AlvaroNeural', label: 'Alvaro (Hombre - ES)' },
    { value: 'es-MX-DaliaNeural', label: 'Dalia (Mujer - MX)' },
  ],
  pt: [
    { value: 'pt-BR-FranciscaNeural', label: 'Francisca (Feminino - BR)' },
    { value: 'pt-BR-AntonioNeural', label: 'Antonio (Masculino - BR)' },
  ],
  fr: [
    { value: 'fr-FR-DeniseNeural', label: 'Denise (Femme - FR)' },
    { value: 'fr-FR-HenriNeural', label: 'Henri (Homme - FR)' },
  ],
  de: [
    { value: 'de-DE-KatjaNeural', label: 'Katja (Weiblich - DE)' },
    { value: 'de-DE-ConradNeural', label: 'Conrad (Männlich - DE)' },
  ],
  ru: [
    { value: 'ru-RU-SvetlanaNeural', label: 'Svetlana (Жен - RU)' },
    { value: 'ru-RU-DmitryNeural', label: 'Dmitry (Муж - RU)' },
  ],
  ar: [
    { value: 'ar-SA-ZariyahNeural', label: 'Zariyah (أنثى - SA)' },
    { value: 'ar-SA-HamedNeural', label: 'Hamed (ذكر - SA)' },
  ],
  hi: [
    { value: 'hi-IN-SwaraNeural', label: 'Swara (महिला - IN)' },
    { value: 'hi-IN-MadhurNeural', label: 'Madhur (पुरुष - IN)' },
  ],
  zh: [
    { value: 'zh-CN-XiaoxiaoNeural', label: 'Xiaoxiao (女 - CN)' },
    { value: 'zh-CN-XiaoyiNeural', label: 'Xiaoyi (女 - CN)' },
    { value: 'zh-CN-YunxiNeural', label: 'Yunxi (男 - CN)' },
    { value: 'zh-CN-YunjianNeural', label: 'Yunjian (男 - CN)' },
    { value: 'zh-CN-YunxiaNeural', label: 'Yunxia (男 - CN)' },
    { value: 'zh-CN-YunyangNeural', label: 'Yunyang (男 - CN)' },
  ],
};

/* ── gTTS language codes ── */
const GTTS_BY_LANG = {
  vi: 'vi|com.vn', en: 'en|com', ja: 'ja|com', ko: 'ko|com', th: 'th|com', id: 'id|com',
  es: 'es|com', pt: 'pt|com', fr: 'fr|com', de: 'de|com', ru: 'ru|com', ar: 'ar|com', hi: 'hi|com', zh: 'zh|com',
};

/**
 * When user changes "Ngôn ngữ đầu ra", auto-switch TTS engine to Edge TTS
 * and populate voice list with voices for that language.
 */
function _onTargetLangChange() {
  const lang = document.getElementById('proc-target-lang')?.value || 'vi';
  const catalog = TTS_ENGINE_CATALOG || [];
  const engineEl = document.getElementById('proc-tts-engine');

  if (catalog.length && engineEl) {
    _ensureTtsEngineForLang('proc-tts-engine', lang);
    _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
    return;
  }

  if (!TTS_ENGINE_CATALOG_PROMISE) {
    _loadTtsEngineCatalog().then(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) _onTargetLangChange();
    });
  }

  // If target is Vietnamese, keep current engine (FPT AI works for vi)
  if (lang === 'vi') {
    _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
    return;
  }

  // For non-Vietnamese: force Edge TTS (best multilingual support)
  if (engineEl) engineEl.value = 'edge-tts';

  // Populate voice list for the target language
  const voiceEl = document.getElementById('proc-tts-voice');
  if (!voiceEl) return;
  const voices = EDGE_TTS_BY_LANG[lang] || EDGE_TTS_BY_LANG['en'];
  voiceEl.innerHTML = '';
  voices.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v.value;
    opt.textContent = v.label;
    voiceEl.appendChild(opt);
  });
  voiceEl.value = voices[0]?.value || '';
}

/* ── 9Router consolidated TTS engine — SHARED dynamic component ────────────
 * The catalog exposes ONE "9Router TTS" engine carrying `models` (grouped by
 * provider) + `voicesByProvider`. Given any (engineSelectId, voiceSelectId)
 * pair, this injects a Model dropdown + free-text Voice input (with
 * suggestions) + "save as default" button right after the engine field — so it
 * works on process / transcribe / movie / story / sales / ads uniformly.
 * Final value is sent as "model|voice"; backend builds the provider's real
 * model id (openai => voice field, elevenlabs/edge => model/voice path). */
function _9rKey(engineSelectId) {
  return String(engineSelectId || '').replace(/[^a-z0-9]/gi, '_');
}

function _find9rEngine(engineId) {
  const eng = String(engineId || '').toLowerCase();
  return (TTS_ENGINE_CATALOG || []).find(
    e => String(e.id || '').toLowerCase() === eng && e.backend === '9router');
}

// Create (once) the Model + Voice + Save controls after the engine field.
function _ensure9rComponent(engineSelectId, voiceSelectId) {
  _ensure9rStyles();
  const key = _9rKey(engineSelectId);
  let wrap = document.getElementById(key + '-9r-wrap');
  if (wrap) {
    if (voiceSelectId) wrap.dataset.voiceSel = voiceSelectId;
    return wrap;
  }
  const engineEl = document.getElementById(engineSelectId);
  const engineField = engineEl && engineEl.closest('.field');
  if (!engineField) return null;

  wrap = document.createElement('div');
  wrap.id = key + '-9r-wrap';
  wrap.className = 'field';
  wrap.style.gridColumn = '1 / -1';
  wrap.style.display = 'none';
  wrap.dataset.engineSel = engineSelectId;
  if (voiceSelectId) wrap.dataset.voiceSel = voiceSelectId;
  wrap.innerHTML =
    '<div class="grid-2">' +
      '<div class="field">' +
        '<label>Model (9Router)</label>' +
        '<select id="' + key + '-9r-model"></select>' +
      '</div>' +
      '<div class="field" style="position:relative">' +
        '<label>Voice (nhập ID hoặc chọn gợi ý)</label>' +
        '<input type="text" id="' + key + '-9r-voice" autocomplete="off" style="width:100%" ' +
          'placeholder="để trống = giọng mặc định">' +
        '<div id="' + key + '-9r-voice-pop" class="nr-voice-pop" style="display:none"></div>' +
      '</div>' +
    '</div>' +
    '<div class="flex-center gap-8 mt-8">' +
      '<button type="button" class="btn btn-secondary btn-sm" id="' + key + '-9r-save">💾 Lưu làm mặc định</button>' +
      '<span class="text-xs text-muted" id="' + key + '-9r-hint"></span>' +
    '</div>';
  engineField.parentNode.insertBefore(wrap, engineField.nextSibling);

  document.getElementById(key + '-9r-model')
    .addEventListener('change', () => _sync9rVoice(engineSelectId));

  const voiceInput = document.getElementById(key + '-9r-voice');
  const pop = document.getElementById(key + '-9r-voice-pop');
  if (voiceInput && pop) {
    const show = () => { _9rRenderVoicePop(engineSelectId); pop.style.display = 'block'; };
    voiceInput.addEventListener('focus', show);
    voiceInput.addEventListener('click', show);
    voiceInput.addEventListener('input', () => { _9rRenderVoicePop(engineSelectId); pop.style.display = 'block'; });
    // Hide when focus/click leaves the field.
    document.addEventListener('click', (e) => {
      if (!wrap.contains(e.target)) pop.style.display = 'none';
    });
  }

  document.getElementById(key + '-9r-save')
    .addEventListener('click', () => _save9rDefault(engineSelectId, wrap.dataset.voiceSel || ''));
  return wrap;
}

function _ensure9rStyles() {
  if (document.getElementById('nr-voice-pop-style')) return;
  const st = document.createElement('style');
  st.id = 'nr-voice-pop-style';
  st.textContent =
    '.nr-voice-pop{position:absolute;left:0;right:0;top:100%;margin-top:4px;z-index:50;' +
    'max-height:240px;overflow-y:auto;background:var(--bg2,#fff);border:1px solid var(--border,#d8d8de);' +
    'border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.18);padding:4px}' +
    '.nr-voice-pop .nr-vi{padding:8px 10px;border-radius:7px;cursor:pointer;display:flex;' +
    'flex-direction:column;gap:1px}' +
    '.nr-voice-pop .nr-vi:hover{background:var(--accent-light,#eef3ff)}' +
    '.nr-voice-pop .nr-vi b{font-size:12.5px;color:var(--text,#1f2430);font-weight:600}' +
    '.nr-voice-pop .nr-vi small{font-size:11px;color:var(--text-muted,#8a8f9a);font-family:monospace;word-break:break-all}' +
    '.nr-voice-pop .nr-empty{padding:8px 10px;font-size:12px;color:var(--text-muted,#8a8f9a)}';
  document.head.appendChild(st);
}

// Render the floating voice-suggestion popover for the engine's selected model.
function _9rRenderVoicePop(engineSelectId) {
  const key = _9rKey(engineSelectId);
  const engineEl = document.getElementById(engineSelectId);
  const cat = engineEl ? _find9rEngine(engineEl.value) : null;
  const modelSel = document.getElementById(key + '-9r-model');
  const pop = document.getElementById(key + '-9r-voice-pop');
  const input = document.getElementById(key + '-9r-voice');
  if (!cat || !modelSel || !pop) return;
  const model = (cat.models || []).find(m => m.id === modelSel.value) || {};
  const prov = model.provider || '';
  const baseVoices = (cat.voicesByProvider && cat.voicesByProvider[prov])
    || (cat.voices && cat.voices.multi) || [];
  const customVoices = (typeof _getTranscribeCustomVoices === 'function')
    ? _getTranscribeCustomVoices()
        .filter(item => String(item.engine || '').toLowerCase() === String(engineEl.value || '').toLowerCase())
        .map(item => [item.voice, `${item.label} (tự thêm)`])
    : [];
  const voices = [...baseVoices, ...customVoices];
  const filter = (input?.value || '').trim().toLowerCase();
  pop.innerHTML = '';
  let shown = 0;
  voices.forEach(v => {
    const val = Array.isArray(v) ? v[0] : (v.value || v.id || '');
    const lab = Array.isArray(v) ? (v[1] || v[0]) : (v.label || val);
    if (!val) return;
    if (filter && !(val.toLowerCase().includes(filter) || String(lab).toLowerCase().includes(filter))) return;
    const item = document.createElement('div');
    item.className = 'nr-vi';
    item.innerHTML = '<b></b><small></small>';
    item.querySelector('b').textContent = lab;
    item.querySelector('small').textContent = val;
    // mousedown fires before input blur so the value sticks.
    item.addEventListener('mousedown', (e) => {
      e.preventDefault();
      if (input) input.value = val;
      pop.style.display = 'none';
    });
    pop.appendChild(item);
    shown++;
  });
  if (!shown) {
    const empty = document.createElement('div');
    empty.className = 'nr-empty';
    empty.textContent = voices.length ? 'Không khớp gợi ý nào.' : 'Model này không có giọng gợi ý — nhập ID thủ công.';
    pop.appendChild(empty);
  }
}

function _sync9rVoice(engineSelectId) {
  _ensure9rStyles();
  const key = _9rKey(engineSelectId);
  const pop = document.getElementById(key + '-9r-voice-pop');
  // Re-render suggestions if the popover is open; otherwise just refresh data
  // lazily on next focus.
  if (pop && pop.style.display !== 'none') _9rRenderVoicePop(engineSelectId);
}

// Save current 9Router model+voice as the default in config.yml (video_process).
async function _save9rDefault(engineSelectId, voiceSelectId) {
  const key = _9rKey(engineSelectId);
  const { tts_engine, tts_voice } = _resolveTtsEngineVoiceEx(engineSelectId, voiceSelectId);
  const hint = document.getElementById(key + '-9r-hint');
  try {
    await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_process: { tts_engine, tts_voice } }),
    });
    if (hint) { hint.textContent = '✓ Đã lưu mặc định'; hint.style.color = 'var(--success)'; }
    if (typeof toast === 'function') toast('Đã lưu TTS mặc định', 'success');
  } catch (e) {
    if (hint) { hint.textContent = '✗ Lưu thất bại'; hint.style.color = 'var(--danger)'; }
  }
}

// Returns true when the selected engine is a 9Router engine (and sets up its
// Model + voice controls), false otherwise (so the caller runs normal logic).
function _handle9RouterEngine(engineSelectId, voiceSelectId) {
  const engineEl = document.getElementById(engineSelectId);
  if (!engineEl) return false;
  const key = _9rKey(engineSelectId);
  const cat = (TTS_ENGINE_CATALOG || []).find(e => e.id === '9router');
  const is9r = engineEl.value === '9router';

  const voiceEl = voiceSelectId ? document.getElementById(voiceSelectId) : null;
  const voiceField = voiceEl && voiceEl.closest('.field');
  const wrap = _ensure9rComponent(engineSelectId, voiceSelectId);


  if (!is9r) {
    if (wrap) wrap.style.display = 'none';
    if (voiceField) voiceField.style.display = '';
    return false;
  }
  if (!wrap) return false; // no engine field on this page — let normal logic run

  if (voiceField) voiceField.style.display = 'none';
  wrap.style.display = '';

  const modelSel = document.getElementById(key + '-9r-model');
  if (modelSel) {
    const cur = modelSel.value;
    const models = cat.models || [];
    const groups = {};
    models.forEach(m => {
      const g = m.group || m.provider || '9router';
      (groups[g] = groups[g] || []).push(m);
    });
    modelSel.innerHTML = '';
    Object.keys(groups).forEach(g => {
      const og = document.createElement('optgroup');
      og.label = g;
      groups[g].forEach(m => {
        const o = document.createElement('option');
        o.value = m.id;
        o.textContent = m.label || m.id;
        og.appendChild(o);
      });
      modelSel.appendChild(og);
    });
    modelSel.value = models.some(m => m.id === cur)
      ? cur
      : (cat.defaultModel || (models[0] && models[0].id) || '');
    _sync9rVoice(engineSelectId);
  }
  return true;
}

// Explicit resolver: {tts_engine, tts_voice} from an (engine, voice) id pair.
function _resolveTtsEngineVoiceEx(engineSelectId, voiceSelectId) {
  const key = _9rKey(engineSelectId);
  const engineEl = document.getElementById(engineSelectId);
  const cat = engineEl ? _find9rEngine(engineEl.value) : null;
  if (cat) {
    const model = document.getElementById(key + '-9r-model')?.value || cat.defaultModel || '';
    const voice = (document.getElementById(key + '-9r-voice')?.value || '').trim();
    return { tts_engine: '9router', tts_voice: model + '|' + voice };
  }
  return {
    tts_engine: engineEl?.value || 'edge-tts',
    tts_voice: (voiceSelectId && document.getElementById(voiceSelectId)?.value) || 'vi-VN-HoaiMyNeural',
  };
}

// Convenience wrapper for the common "{base}-tts-engine"/"{base}-tts-voice" pages.
function _resolveTtsEngineVoice(base) {
  return _resolveTtsEngineVoiceEx(base + '-tts-engine', base + '-tts-voice');
}

function _syncVoiceOptions(engineSelectId, voiceSelectId) {
  const engineEl = document.getElementById(engineSelectId);
  const voiceEl = document.getElementById(voiceSelectId);
  if (!engineEl || !voiceEl) return;

  // 9Router engine → dedicated Model + voice-id controls; skip normal logic.
  if (_handle9RouterEngine(engineSelectId, voiceSelectId)) return;

  // Nếu engine select trống (chưa được populate), thử refresh trước
  let engine = (engineEl.value || '').toLowerCase();
  if (!engine && engineEl.options.length === 0) {
    // Dropdown chưa có options — chờ catalog load
    if (!TTS_ENGINE_CATALOG_PROMISE) {
      _loadTtsEngineCatalog().then(() => {
        _refreshTtsEngineSelects();
        _syncVoiceOptions(engineSelectId, voiceSelectId);
      });
    }
    return;
  }
  // Nếu value rỗng nhưng có options, chọn option đầu tiên
  if (!engine && engineEl.options.length > 0) {
    engineEl.selectedIndex = 0;
    engine = engineEl.value.toLowerCase();
  }
  if (!engine) engine = 'fpt-ai';
  const targetLang = _getTtsTargetLangForSelect(engineSelectId);
  const catalog = TTS_ENGINE_CATALOG || [];

  if (catalog.length) {
    const adjusted = _ensureTtsEngineForLang(engineSelectId, targetLang);
    if (adjusted) engine = adjusted.toLowerCase();
  } else if (targetLang !== 'vi' && engine === 'fpt-ai' && engineEl.options.length > 0) {
    const edgeOpt = Array.from(engineEl.options).find(opt => opt.value === 'edge-tts');
    if (edgeOpt) {
      engineEl.value = 'edge-tts';
      engine = 'edge-tts';
    }
  }

  const catalogEngine = catalog.find(e => String(e.id || '').toLowerCase() === engine);

  if (catalogEngine && catalogEngine.voices) {
    const voicesByLang = catalogEngine.voices || {};
    let rawList = voicesByLang[targetLang] || voicesByLang.multi || [];
    if (!rawList.length && engine === 'edge-tts' && EDGE_TTS_BY_LANG[targetLang]) {
      rawList = EDGE_TTS_BY_LANG[targetLang];
    }
    if (!rawList.length && engine === 'gtts' && GTTS_BY_LANG[targetLang]) {
      rawList = [[GTTS_BY_LANG[targetLang], `${targetLang} (gTTS)`]];
    }
    if (!rawList.length) {
      const fallbackLang = voicesByLang.vi ? 'vi' : Object.keys(voicesByLang)[0];
      rawList = voicesByLang[fallbackLang] || [];
    }
    const preset = _mergeManagedVoicePreset(engine, _catalogVoicesToPreset(rawList), targetLang);
    if (preset.length) {
      const current = voiceEl.value || '';
      voiceEl.innerHTML = '';
      preset.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.value;
        opt.textContent = item.label;
        voiceEl.appendChild(opt);
      });
      const keep = preset.some(item => item.value === current);
      voiceEl.value = keep ? current : (catalogEngine.default || preset[0].value);
      if (!preset.some(item => item.value === voiceEl.value)) voiceEl.value = preset[0].value;
      return;
    }
  } else if (!TTS_ENGINE_CATALOG_PROMISE) {
    _loadTtsEngineCatalog().then(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
        _syncVoiceOptions(engineSelectId, voiceSelectId);
      }
    });
  }

  // For non-Vietnamese target: always use Edge TTS voices for that language
  if (targetLang !== 'vi' && engine === 'edge-tts') {
    const voices = _mergeManagedVoicePreset(engine, EDGE_TTS_BY_LANG[targetLang] || EDGE_TTS_BY_LANG['en'], targetLang);
    const current = voiceEl.value || '';
    voiceEl.innerHTML = '';
    voices.forEach(item => {
      const opt = document.createElement('option');
      opt.value = item.value;
      opt.textContent = item.label;
      voiceEl.appendChild(opt);
    });
    const keep = voices.some(item => item.value === current);
    voiceEl.value = keep ? current : voices[0].value;
    return;
  }

  const preset = _mergeManagedVoicePreset(engine, engine === 'gtts' && GTTS_BY_LANG[targetLang]
    ? [{ value: GTTS_BY_LANG[targetLang], label: `${targetLang} (gTTS)` }]
    : (TTS_VOICE_PRESETS[engine] || TTS_VOICE_PRESETS['fpt-ai']), targetLang);
  const current = voiceEl.value || '';

  voiceEl.innerHTML = '';
  preset.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.value;
    opt.textContent = item.label;
    voiceEl.appendChild(opt);
  });

  const keep = preset.some(item => item.value === current);
  voiceEl.value = keep ? current : (TTS_DEFAULT_VOICE[engine] || preset[0].value);
}

function switchPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item,.mobile-nav-item').forEach(n => n.classList.remove('active'));
  const page = document.getElementById('page-' + name);
  const navs = document.querySelectorAll('[data-page="' + name + '"]');
  if (page) page.classList.add('active');
  navs.forEach(n => n.classList.add('active'));
  const el = document.getElementById('topbar-title');
  const titles = {
    user:'Tìm người dùng', process:'Xử lý Video', transcribe:'Phiên âm', subtitle:'Phụ đề & Khung',
    publish:'Đăng video', content:'Quản lý bài đăng', history:'Lịch sử', config:'Cấu hình', cookies:'Cookies',
    movie:'Review phim', story:'Truyện → Video', proxies:'Proxy & Router', chat:'Chat Bot · 9Router',
    videogen:'Video AI', ai_studio:'AI Studio', n8n:'Điều phối n8n', sales:'Video bán hàng', ads:'Video quảng cáo'
  };
  if (el) el.textContent = titles[name] || t('title_' + name) || name;
  if (name === 'config' && !window._configLoaded) {
    loadConfig();
    loadCookieMode();
    loadCookieFields();
    window._configLoaded = true;
  }
  if (name === 'history') { loadHistory(); if (typeof loadFiles === 'function') loadFiles(''); }
  if (name === 'content') cptSwitch('files');
  if (name === 'process') {
    loadQueue();
    // Refresh TTS engine dropdown mỗi khi switch sang trang process
    // (catalog có thể đã load sau khi DOM render)
    requestAnimationFrame(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
        _refreshTtsEngineSelects();
        _onTargetLangChange();
      } else {
        _loadTtsEngineCatalog().then(() => {
          _refreshTtsEngineSelects();
          _onTargetLangChange();
        });
      }
    });
  }
  if (name === 'transcribe') {
    requestAnimationFrame(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
        _refreshTtsEngineSelects();
        _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
        if (typeof renderTranscribeVoiceLibrary === 'function') renderTranscribeVoiceLibrary();
      } else {
        _loadTtsEngineCatalog().then(() => {
          _refreshTtsEngineSelects();
          _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
          if (typeof renderTranscribeVoiceLibrary === 'function') renderTranscribeVoiceLibrary();
        });
      }
    });
  }
  if (name === 'proxies') { if (typeof proxyLoadList === 'function') proxyLoadList(); if (typeof routerLoadList === 'function') routerLoadList(); }
  if (name === 'chat' && typeof chatInit === 'function') chatInit();
  if (name === 'videogen' && typeof vgInit === 'function') vgInit();
  if (name === 'n8n' && typeof n8nInit === 'function') n8nInit();
  if (name === 'sales' && typeof salesInit === 'function') salesInit();
  if (name === 'ads' && typeof adsInit === 'function') adsInit();
}



/* ── Video Processing ── */
window._procMode = localStorage.getItem('proc_mode') || 'ai';
window._procSelectedFile = null;
window._procUploadPromise = null;
window._procUploadedPath = null;

/**
 * Pre-upload video file ngay khi chọn, hiển thị progress bar.
 * Khi processing bắt đầu, file đã có sẵn trên server → bỏ qua upload.
 */
function _onProcFileSelected(input) {
  const files = input.files;
  if (!files || files.length === 0) return;

  const nameEl = document.getElementById('proc-file-name');
  const pathEl = document.getElementById('proc-video');
  const progressWrap = document.getElementById('proc-file-progress');
  const progressBar = document.getElementById('proc-file-progress-bar');
  const progressText = document.getElementById('proc-file-progress-text');

  if (progressWrap) progressWrap.style.display = 'block';

  window._procUploadPromise = (async () => {
    let successCount = 0;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (nameEl) nameEl.textContent = `📁 [${i+1}/${files.length}] Đang tải lên: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
      if (pathEl) pathEl.value = `⏳ [${i+1}/${files.length}] Đang tải lên: ${file.name}`;
      if (progressBar) progressBar.style.width = '0%';
      if (progressText) progressText.textContent = '0%';

      const form = new FormData();
      form.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round(e.loaded / e.total * 100);
          if (progressBar) progressBar.style.width = pct + '%';
          if (progressText) progressText.textContent = `${pct}% (${(e.loaded / 1024 / 1024).toFixed(1)} / ${(e.total / 1024 / 1024).toFixed(1)} MB)`;
        }
      };

      const uploadSingle = () => new Promise((resolve, reject) => {
        xhr.onload = () => {
          try {
            const d = JSON.parse(xhr.responseText);
            if (d.ok && d.path) {
              resolve(d.path);
            } else {
              reject(new Error(d.error || 'Upload failed'));
            }
          } catch (e) {
            reject(e);
          }
        };
        xhr.onerror = () => reject(new Error('Lỗi kết nối khi upload'));
        xhr.open('POST', '/api/upload_process_video', true);
        xhr.send(form);
      });

      try {
        const uploadedPath = await uploadSingle();
        successCount++;
        // Automatically add this file to the queue!
        if (window._batchQueue && typeof buildNewTask === 'function') {
          window._batchQueue.push(buildNewTask('file', uploadedPath));
          if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
          if (typeof _step1UpdateDownloadArea === 'function') _step1UpdateDownloadArea();
        }
      } catch (err) {
        if (nameEl) nameEl.textContent = `❌ Lỗi tải lên ${file.name}: ${err.message}`;
        if (typeof toast === 'function') toast(`❌ Lỗi tải lên ${file.name}: ${err.message}`, 'danger');
      }
    }

    // Done all uploads
    if (pathEl) pathEl.value = '';
    if (nameEl) nameEl.textContent = `✅ Đã tải lên thành công ${successCount}/${files.length} file video`;
    if (progressBar) progressBar.style.width = '100%';
    if (progressText) progressText.textContent = '✅ Hoàn thành';
    if (typeof toast === 'function') toast(`✅ Đã tải lên và thêm vào hàng chờ ${successCount} file video`, 'success');
    setTimeout(() => { if (progressWrap) progressWrap.style.display = 'none'; }, 2000);
    
    // Clear input value so same files can be re-selected if needed
    input.value = '';
    
    // Clear the active file upload state
    window._procSelectedFile = null;
    window._procUploadedPath = null;
    window._procUploadPromise = null;
  })();
}

function setProcessMode(mode) {
  window._procMode = mode === 'model' ? 'model' : 'ai';
  localStorage.setItem('proc_mode', window._procMode);

  const aiPanel = document.getElementById('proc-ai-panel');
  const modelPanel = document.getElementById('proc-model-panel');
  const aiBtn = document.getElementById('proc-tab-ai');
  const modelBtn = document.getElementById('proc-tab-model');
  const isAi = window._procMode === 'ai';

  if (aiPanel) aiPanel.style.display = isAi ? 'block' : 'none';
  if (modelPanel) modelPanel.style.display = isAi ? 'none' : 'block';
  if (aiBtn) {
    aiBtn.classList.toggle('btn-primary', isAi);
    aiBtn.classList.toggle('btn-secondary', !isAi);
  }
  if (modelBtn) {
    modelBtn.classList.toggle('btn-primary', !isAi);
    modelBtn.classList.toggle('btn-secondary', isAi);
  }
}

function _getProcessProvider(kind) {
  const isModel = (window._procMode || 'ai') === 'model';
  const transcribeId = isModel ? 'proc-transcribe-provider-model' : 'proc-transcribe-provider-ai';
  const translateId = isModel ? 'proc-trans-provider-model' : 'proc-trans-provider-ai';
  if (kind === 'transcribe') {
    return document.getElementById(transcribeId)?.value || (isModel ? 'model' : 'groq');
  }
  return document.getElementById(translateId)?.value || 'deepseek';
}

function startProcessVideo() {
  const videoPath = document.getElementById('proc-video')?.value?.trim();
  const videoUrl = document.getElementById('proc-url')?.value?.trim();
  const selectedFile = window._procSelectedFile || document.getElementById('proc-file')?.files?.[0] || null;
  if (!videoPath && !videoUrl && !selectedFile) {
    alert('Vui lòng nhập đường dẫn file video hoặc URL video');
    // Notify batch queue so _procRunning resets and queue can continue
    if (typeof window._onProcTaskFinished === 'function') {
      window._onProcTaskFinished(false);
    }
    return;
  }

  // Preflight: nếu user bật tự-động-đăng, check trạng thái các nền tảng trước khi
  // bắt đầu pipeline xử lý dài. Người dùng có thể tắt nền tảng lỗi hoặc hủy.
  (async () => {
    if (window._procUploadPromise) {
      try {
        await window._procUploadPromise;
      } catch (e) {
        toast('Upload file import chưa hoàn tất: ' + (e.message || e), 'error');
        if (typeof window._onProcTaskFinished === 'function') {
          window._onProcTaskFinished(false);
        }
        return;
      }
    }

    // --- PRE-FLIGHT API CHECKS ---
    try {
      const providersToCheck = [];
      
      // 1. Check Translation API if enabled
      const translateSubs = document.getElementById('proc-translate-subs')?.checked ?? true;
      if (translateSubs) {
        const transProv = _getProcessProvider('translate');
        if (['deepseek', 'groq', 'openai', 'gemini', '9router'].includes(transProv)) {
          providersToCheck.push(transProv);
        }
      }
      
      // 2. Check Transcription API if enabled
      const transcribeProv = _getProcessProvider('transcribe');
      if (['groq', 'openai', 'gemini', '9router'].includes(transcribeProv)) {
        providersToCheck.push(transcribeProv);
      }
      
      // 3. Check TTS API if voice conversion is enabled
      const voiceConvert = document.getElementById('proc-voice')?.checked ?? false;
      if (voiceConvert) {
        const ttsEngine = _resolveTtsEngineVoice('proc')?.tts_engine || '';
        const ttsProv = _getTtsApiProvider(ttsEngine);
        if (ttsProv) {
          providersToCheck.push(ttsProv);
        }
      }
      
      // Filter out duplicate providers
      const uniqueProviders = [...new Set(providersToCheck)];
      
      if (uniqueProviders.length > 0 && typeof checkApiBeforeAction === 'function') {
        for (const provider of uniqueProviders) {
          const key = getApiKeyForProvider(provider);
          await new Promise((resolve, reject) => {
            checkApiBeforeAction(provider, key, resolve, () => reject(new Error('Hủy bỏ hoặc kiểm tra API thất bại.')));
          });
        }
      }
    } catch (err) {
      console.warn('API Preflight check failed:', err);
      // Reset task status in queue
      if (window._procCurrentTaskId) {
        const t = (window._batchQueue || []).find(x => x.id === window._procCurrentTaskId);
        if (t && t.status === 'processing') t.status = 'pending';
      }
      window._procCurrentTaskId = null;
      window._procRunning = false;
      if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
      if (typeof window._onProcTaskFinished === 'function') {
        window._onProcTaskFinished(false);
      }
      return; // Do not proceed to process video
    }
    // --- END OF PRE-FLIGHT API CHECKS ---

    if (typeof window.pPubPreflightCheck === 'function'
        && document.getElementById('p-autopub-enabled')?.checked) {
      const ok = await window.pPubPreflightCheck({ interactive: true });
      if (!ok) {
        // User chose to cancel — stop the queue, revert task to pending.
        // Queue will only resume when user manually clicks "Xử lý hàng chờ" again.
        window._procAutoDrain = false;
        const drainCb = document.getElementById('batch-auto-drain');
        if (drainCb) drainCb.checked = false;
        const drainStatus = document.getElementById('batch-drain-status');
        if (drainStatus) drainStatus.textContent = '';
        // Revert current task back to pending so it can be retried
        if (window._procCurrentTaskId) {
          const t = (window._batchQueue || []).find(x => x.id === window._procCurrentTaskId);
          if (t && t.status === 'processing') t.status = 'pending';
        }
        window._procCurrentTaskId = null;
        window._procRunning = false;
        if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
        return;
      }
    }
    const latestVideoPath = document.getElementById('proc-video')?.value?.trim() || videoPath;
    const latestSelectedFile = window._procSelectedFile || document.getElementById('proc-file')?.files?.[0] || null;
    _startProcessVideoInternal(latestVideoPath, videoUrl, latestSelectedFile);
  })();
}

function _startProcessVideoInternal(videoPath, videoUrl, selectedFile) {

  const btn = document.getElementById('btn-proc');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang xử lý...'; }

  // Reset UI
  const logBox = document.getElementById('proc-log');
  if (logBox) logBox.innerHTML = '';
  // Reset step3 log mirror
  const logBox3 = document.getElementById('step3-log');
  if (logBox3) logBox3.innerHTML = '';
  _setProcProgress(0, 'Bắt đầu...');

  const baseFields = {
    video_path:       videoPath,
    video_url:        videoUrl || '',
    out_dir:          document.getElementById('proc-out')?.value?.trim() || '',
    model:            document.getElementById('proc-model')?.value || 'base',
    language:         document.getElementById('proc-lang')?.value || 'zh',
    target_language:  document.getElementById('proc-target-lang')?.value || 'vi',
    transcribe_provider: _getProcessProvider('transcribe'),
    translate_provider:  _getProcessProvider('translate'),
    burn_subs:        (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-burn')?.checked ?? true),
    blur_original:    document.getElementById('proc-blur-original')?.checked ?? true,
    blur_height_pct:  parseFloat(document.getElementById('proc-blur-height')?.value || '15') / 100,
    blur_width_pct:   parseFloat(document.getElementById('proc-blur-width')?.value || '80') / 100,
    blur_y_pct:       (() => {
      const v = document.getElementById('proc-blur-y')?.value?.trim();
      return (v !== '' && v !== undefined) ? parseFloat(v) / 100 : null;  // null = auto
    })(),
    blur_x_pct:       (() => {
      const v = document.getElementById('proc-blur-x')?.value?.trim();
      return (v !== '' && v !== undefined) ? parseFloat(v) / 100 : null;  // null = 50%
    })(),
    blur_zone:        'bottom',  // legacy compat
    blur_extra_zones: (window._procExtraBlurZones || []).map(z => ({
      height_pct: (z.height || 12) / 100,
      position_pct: (z.position || 50) / 100,
      width_pct: (z.width || 80) / 100,
      x_pct: ((z.x === undefined || z.x === null) ? 50 : z.x) / 100,
      start_sec: (z.start === '' || z.start === undefined || z.start === null) ? null : Number(z.start),
      end_sec:   (z.end   === '' || z.end   === undefined || z.end   === null) ? null : Number(z.end),
    })),
    translate_subs:   (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-translate-subs')?.checked ?? true),
    burn_vi_subs:     (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-burn-vi')?.checked ?? true),
    voice_convert:    (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-voice')?.checked ?? false),
    ..._resolveTtsEngineVoice('proc'),
    tts_pitch:        _sanitizeVoiceParam(document.getElementById('proc-tts-pitch')?.value || '+0Hz'),
    tts_rate:         _sanitizeVoiceParam(document.getElementById('proc-tts-rate')?.value || '+0%'),
    tts_emotion:      document.getElementById('proc-tts-emotion')?.value || 'default',
    keep_bg_music:    document.getElementById('proc-keep-bg')?.checked ?? false,
    ext_audio_enabled: document.getElementById('proc-ext-audio-enabled')?.checked ?? false,
    vol_orig:          parseFloat(document.getElementById('proc-vol-orig')?.value || '100') / 100,
    ext_audios:        window._procExtAudios || [],

    font_size:        (() => {
      // UI value is % of video height. Convert to px for FFmpeg (reference: 720px height).
      const pct = parseFloat(document.getElementById('proc-font-size')?.value || '4.5');
      return Math.max(8, Math.round(720 * pct / 100));
    })(),
    font_color:       (() => {
      const sel = document.getElementById('proc-font-color');
      const picker = document.getElementById('proc-font-color-picker');
      if (sel?.value === 'custom' && picker) return picker.value;
      return sel?.value || 'white';
    })(),
    subtitle_position: document.getElementById('proc-sub-pos')?.value || 'bottom',
    margin_v:         (() => {
      // UI value is % of video height. Convert to px for FFmpeg (reference: 720px height).
      const pct = parseFloat(document.getElementById('proc-margin-v')?.value || '3');
      return Math.max(0, Math.round(720 * pct / 100));
    })(),
    outline_width:    parseInt(document.getElementById('proc-outline-width')?.value || '2', 10),
    font_bold:        document.getElementById('proc-font-bold')?.checked ?? true,
    tts_speed:        parseFloat(document.getElementById('proc-tts-speed')?.value || '1.0'),
    auto_speed:       document.getElementById('proc-auto-speed')?.checked ?? true,
    process_mode:     window._procMode || 'ai',
    // Voice FX (Review style)
    fx_enabled:       document.getElementById('proc-fx-enabled')?.checked ?? false,
    fx_pitch:         parseFloat(document.getElementById('proc-fx-pitch')?.value || '1.5'),
    fx_speed:         parseFloat(document.getElementById('proc-fx-speed')?.value || '1.08'),
    fx_bass:          parseInt(document.getElementById('proc-fx-bass')?.value || '-2'),
    fx_mid:           parseInt(document.getElementById('proc-fx-mid')?.value || '2'),
    fx_treble:        parseInt(document.getElementById('proc-fx-treble')?.value || '3'),
    fx_comp:          document.getElementById('proc-fx-comp')?.value || 'light',
    fx_reverb:        parseInt(document.getElementById('proc-fx-reverb')?.value || '5'),
    // Anti-Fingerprint (removed - fields no longer in UI)
    afp_enabled:      false,
    afp_flip:         false,
    afp_vignette:     false,
    afp_vertical:     false,
    afp_scale_w:      0,
    afp_scale_h:      0,
    afp_brightness:   0.02,
    afp_contrast:     1.03,
    afp_speed:        1.0,
    afp_overlay_img:  '',
    // CapCut settings
    capcut_enabled:   document.getElementById('proc-capcut-enabled')?.checked ?? false,
    capcut_auto_open: document.getElementById('proc-capcut-auto-open')?.checked ?? false,
    // Video mode: only convert when the source orientation differs from the selected mode.
    target_aspect: document.getElementById('proc-preview-aspect')?.value || 'auto',
    // Lấp viền khi đổi khung bằng nền mờ (blur) thay vì viền đen.
    aspect_pad_blur: document.getElementById('proc-aspect-blur-bg')?.checked ?? false,
    // Frame video (step 6)
    frame_enabled:        document.getElementById('frame-enabled')?.checked ?? false,
    frame_title:          document.getElementById('frame-title')?.value || '',
    frame_title_enabled:  document.getElementById('frame-title-enabled')?.checked ?? true,
    frame_title_size_pct: parseFloat(document.getElementById('frame-title-size')?.value || 5),
    frame_title_weight:   parseInt(document.getElementById('frame-title-weight')?.value || 400, 10),
    frame_title_bar_h_pct: parseFloat(document.getElementById('frame-title-bar-h')?.value || 6),
    frame_title_margin_x_pct: parseFloat(document.getElementById('frame-title-margin-x')?.value || 5),
    frame_title_x_pct:    parseFloat(document.getElementById('frame-title-x')?.value || 50),
    frame_title_y_pct:    parseFloat(document.getElementById('frame-title-y')?.value || 50),
    frame_title_color:    document.getElementById('frame-title-color')?.value || '#000000',
    frame_title_color_2:  document.getElementById('frame-title-color-2')?.value || '#ff0000',
    frame_title_split_color: document.getElementById('frame-title-split-color')?.checked ?? true,
    frame_blur_w_pct:     parseFloat(document.getElementById('frame-blur-w')?.value || 15),
    frame_blur_top_pct:    parseFloat(document.getElementById('frame-blur-top')?.value || 0),
    frame_blur_bottom_pct: parseFloat(document.getElementById('frame-blur-bottom')?.value || 0),
    frame_blur_opacity:   parseFloat(document.getElementById('frame-blur-opacity')?.value || 60) / 100,
    frame_blur_mode:      document.querySelector('input[name="frame-blur-mode"]:checked')?.value || 'overlay',
    frame_logo_path:      (() => {
      // Logo uploaded via /api/upload_anti_fp_image — path stored in input
      const p = document.getElementById('frame-logo-path')?.dataset?.serverPath || '';
      return /(^|[\\/])img[\\/]logo\.png$/i.test(p) ? '' : p;
    })(),
    frame_logo_size_pct:  (() => {
      const v = document.getElementById('frame-logo-size')?.value;
      return (v === '' || v == null) ? 12 : parseFloat(v);
    })(),
    frame_logo_top_pct:   parseFloat(document.getElementById('frame-logo-top')?.value || 3),
    frame_logo_left_pct:  parseFloat(document.getElementById('frame-logo-left')?.value || 3),
    frame_logo_radius_pct: parseFloat(document.getElementById('frame-logo-radius')?.value ?? 50),
    video_overlays:       (typeof window._collectVideoOverlays === 'function') ? window._collectVideoOverlays() : [],
    ai_video_analysis:    (window._procUseAiAnalysis && window._procVideoAiAnalysis?.result) ? window._procVideoAiAnalysis.result : null,
    ai_video_analysis_text: (window._procUseAiAnalysis && window._procVideoAiAnalysis?.analysis_text) ? window._procVideoAiAnalysis.analysis_text : '',
    // Thumbnail flow disabled by request.
    thumb_enabled:        false,
    thumb_mode:           'none',
    thumb_path:           '',
    thumb_title:          '',
    thumb_duration:       0,
  };

  const doRequest = (body, isFormData) => fetch('/api/process_video', {
    method: 'POST',
    headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    body,
  }).then(res => {
    const reader = res.body.getReader();
    window._procReader = reader;
    const decoder = new TextDecoder();

    // Show pause button
    if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(true);

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) {
          if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
          if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
          const doneActions = document.getElementById('proc-done-actions');
          if (doneActions) doneActions.style.display = 'block';

          // Frame video now runs inside the pipeline (step 6) — no need to trigger separately
          _setProcProgress(100, 'Hoàn thành!');

          // ── Auto-publish after processing ──
          if (document.getElementById('p-autopub-enabled')?.checked) {
            if (typeof procWizGo === 'function') procWizGo(5);
          }

          const autoPubPromise = (typeof pPubAutoUploadAll === 'function'
              && document.getElementById('p-autopub-enabled')?.checked
              && window._publishLastOutputPath)
            ? pPubAutoUploadAll(window._publishLastOutputPath).catch(() => {})
            : Promise.resolve();

          // Legacy auto-upload path (different checkbox id)
          if (window._publishLastOutputPath
              && document.getElementById('publish-auto-upload')?.checked
              && !document.getElementById('p-autopub-enabled')?.checked) {
            publishSelectedPlatform();
          }

          // Notify batch queue this task finished (after auto-publish completes
          // so scheduled uploads use the correct index)
          autoPubPromise.finally(() => {
            if (typeof window._onProcTaskFinished === 'function') {
              window._onProcTaskFinished(true);
            }
          });
          return;
        }
        const text = decoder.decode(value, { stream: true });
        text.split('\n').filter(l => l.trim()).forEach(line => {
          try {
            const d = JSON.parse(line);
            if (d.log) {
              _appendProcLog(d.log, d.level || 'info');
              if (d.log.includes('File cuối cùng:') || d.log.includes('final_output_path')) {
                const match = d.log.match(/[:\s]([^\s]+\.mp4)/);
                if (match) {
                  window._publishLastOutputPath = match[1];
                  window._ytLastOutputPath = match[1];
                }
              }
            }
            if (d.file_path) {
              window._publishLastOutputPath = d.file_path;
              window._ytLastOutputPath = d.file_path;
            }
            if (d.subtitle_path) {
              window._publishLastSubtitlePath = d.subtitle_path;
            }
            // Thumbnail stream events are ignored because the thumbnail flow is disabled.
            if (d.tts_incomplete && typeof _showTtsFailModal === 'function') {
              _showTtsFailModal(d);
            }
            if (d.overall !== undefined) _setProcProgress(d.overall, d.overall_lbl || '');

            // ── ASS Review event ──
            if (d.review_ass && d.ass_path) {
              const skipReview = window._procSkipReviewSession === true;
              if (!skipReview) {
                // Load ASS content and show review panel
                fetch('/api/proc_read_ass', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ path: d.ass_path })
                }).then(r => r.json()).then(rd => {
                  if (typeof _showAssReview === 'function') {
                    _showAssReview(d.ass_path, rd.content || '');
                  }
                }).catch(() => {
                  if (typeof _showAssReview === 'function') {
                    _showAssReview(d.ass_path, '');
                  }
                });
              } else {
                // Auto-continue without review — frame video runs after pipeline done
                // Still trigger AI auto-fill (reading ASS content) for auto-publish
                if (typeof pPubOnAssConfirmed === 'function') {
                  fetch('/api/proc_read_ass', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: d.ass_path })
                  }).then(r => r.json()).then(rd => {
                    pPubOnAssConfirmed(d.ass_path, rd.content || '').catch(() => {});
                  }).catch(() => {});
                }
                fetch('/api/proc_resume', { method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ action: 'continue' })
                }).catch(() => {});
              }
            }
          } catch {}
        });
        read();
      });
    }
    read();
  }).catch(err => {
    _appendProcLog('Lỗi kết nối: ' + err, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
    if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
    if (typeof window._onProcTaskFinished === 'function') {
      window._onProcTaskFinished(false);
    }
  });

  // Nếu file đã được pre-upload qua _onProcFileSelected → dùng path đã upload
  if (selectedFile && window._procUploadedPath) {
    baseFields.video_path = window._procUploadedPath;
    window._procUploadedPath = null;
    window._procSelectedFile = null;
    doRequest(JSON.stringify(baseFields), false);
    return;
  }

  if (selectedFile) {
    const form = new FormData();
    form.append('video_file', selectedFile);
    Object.entries(baseFields).forEach(([key, value]) => form.append(key, typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '')));
    doRequest(form, true);
    return;
  }

  doRequest(JSON.stringify(baseFields), false);
}

function sendLastProcessedToPublish() {
  if (!window._publishLastOutputPath) {
    toast('Không tìm thấy đường dẫn video vừa xử lý', 'warning');
    return;
  }
  // Navigate to wizard step 5 (Đăng tự động — embedded in process wizard)
  if (typeof procWizGo === 'function') {
    procWizGo(5);
    toast('✅ Video xử lý xong — hãy cấu hình đăng ở bước 5', 'success');
  } else {
    // Fallback: switch to publish page
    sendToPublish(window._publishLastOutputPath);
  }
}

/**
 * Reads ASS subtitle → calls AI to generate caption → navigates to step 5.
 * Shows a loading indicator while AI is running.
 */
async function _procImportAndAICaption() {
  if (!window._publishLastOutputPath) {
    toast('Không tìm thấy video vừa xử lý', 'warning');
    return;
  }

  const btn = event?.currentTarget;
  if (btn) { btn.disabled = true; btn.textContent = '⏳ AI đang viết caption...'; }

  try {
    // Read ASS content if available
    const assPath = window._publishLastSubtitlePath || '';
    let assContent = '';
    if (assPath) {
      try {
        const r = await fetch('/api/proc_read_ass', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: assPath })
        });
        const d = await r.json();
        assContent = d.content || '';
      } catch (_) {}
    }

    // Enable auto-publish panel so AI fill works
    const autopubChk = document.getElementById('p-autopub-enabled');
    if (autopubChk && !autopubChk.checked) autopubChk.checked = true;

    // Run AI analysis
    const hasVideoAi = !!(window._procUseAiAnalysis && window._procVideoAiAnalysis?.result);
    if ((assContent || hasVideoAi) && typeof pPubAnalyzeFromAss === 'function') {
      await pPubAnalyzeFromAss(assContent);
    } else {
      _appendProcLog('⚠ Không có ASS hoặc phân tích video để AI phân tích — chuyển sang bước 5 để nhập thủ công', 'warning');
    }
  } catch (e) {
    _appendProcLog('❌ AI caption thất bại: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🤖 Import & AI viết Caption → Đăng (Bước 5)'; }
  }

  // Navigate to step 5
  sendLastProcessedToPublish();
}

function sendToPublish(videoPath) {
  if (!videoPath) return;
  const pathInput = document.getElementById('pub-video-path');
  const subInput = document.getElementById('pub-sub-path');
  if (pathInput) {
    pathInput.value = videoPath;
    window._pubVideoFile = null; // Clear local file if sending a path

    if (subInput) {
      if (window._publishLastSubtitlePath) {
        subInput.value = window._publishLastSubtitlePath;
      } else {
        autoDetectSubtitles(videoPath);
      }
    }
    
    // Clear previous info
    ['yt-title', 'yt-desc', 'yt-tags', 'tt-title', 'tt-tags', 'fb-title', 'fb-tags', 'pub-content-input'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    ['yt-upload-log', 'pub-log', 'pub-analyze-status'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        if (el.tagName === 'DIV') el.innerHTML = '';
        else el.textContent = '';
      }
    });

    toast('✅ Đã thêm dữ liệu vào Đăng video', 'success');
    switchPage('publish');
  }
}

async function autoDetectSubtitles(videoPath) {
  if (!videoPath) return;
  try {
    const res = await fetch('/api/detect_subtitles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_path: videoPath })
    });
    const data = await res.json();
    if (data.ok && data.best_match) {
      const subInput = document.getElementById('pub-sub-path');
      if (subInput && (!subInput.value || subInput.value.trim() === '')) {
        subInput.value = data.best_match;
        toast('✨ Đã tự động tìm thấy phụ đề: ' + data.best_match.split(/[\\\/]/).pop(), 'success');
      }
    }
  } catch (e) {
    console.error('Lỗi tự động tìm phụ đề:', e);
  }
}

function _appendProcLog(msg, level) {
  const box = document.getElementById('proc-log');
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'log-line log-' + (level || 'info');
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8); // HH:MM:SS
  div.textContent = `[${ts}] ${msg}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;

  // Mirror to step 3 log box if visible
  const box3 = document.getElementById('step3-log');
  if (box3) {
    const div3 = div.cloneNode(true);
    box3.appendChild(div3);
    box3.scrollTop = box3.scrollHeight;
  }
}

function _setProcProgress(pct, label) {
  const bar = document.getElementById('pb-proc-overall');
  const pctEl = document.getElementById('pb-proc-overall-pct');
  const lblEl = document.getElementById('lbl-proc-overall');
  if (bar)   bar.style.width = pct + '%';
  if (pctEl) pctEl.textContent = pct + '%';
  if (lblEl) lblEl.textContent = label || '';

  // Mirror progress to step 3 mini bar
  const bar3  = document.getElementById('pb-step3-overall');
  const pct3  = document.getElementById('pb-step3-pct');
  if (bar3)  bar3.style.width = pct + '%';
  if (pct3)  pct3.textContent = pct + '%';
}

/* ── Transcribe page ─────────────────────────────────────────────────────── */
window._trPreviewObjectUrl = null;
window._trAssPreviewText = '';

function _extractPreviewTextFromAss(content, maxLines = 2) {
  if (!content) return '';
  const lines = String(content).split(/\r?\n/);
  const texts = [];
  for (const line of lines) {
    if (!line.startsWith('Dialogue:')) continue;
    const payload = line.slice('Dialogue:'.length).trim();
    const parts = payload.split(',', 10);
    if (parts.length < 10) continue;
    let text = parts[9] || '';
    text = text.replace(/\{[^}]*\}/g, '');
    text = text.replace(/\\N/g, ' ').replace(/\\n/g, ' ');
    text = text.replace(/\s+/g, ' ').trim();
    if (!text) continue;
    texts.push(text);
    if (texts.length >= maxLines) break;
  }
  return texts.join(' ');
}



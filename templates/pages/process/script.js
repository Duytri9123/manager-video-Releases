/* ── app.js — Entry point ────────────────────────────────────────────────── */

window._trSelectedFile = null;

function _procIsAutoPublishEnabled() {
  const step1Toggle = document.getElementById('step1-autopub-toggle');
  const publishToggle = document.getElementById('p-autopub-enabled');
  return step1Toggle ? step1Toggle.checked : !!publishToggle?.checked;
}
window._procIsAutoPublishEnabled = _procIsAutoPublishEnabled;

const TTS_VOICE_PRESETS = {
  vieneu: [
    { value: 'Minh Quân Pro', label: '[Tuyển chọn] Minh Quân Pro (Nam · Bắc · Tự nhiên, Mặc định)' },
    { value: 'Phạm Tuyên', label: 'Phạm Tuyên (Nam · Bắc · Tự nhiên)' },
    { value: 'Mai Anh', label: '[Tuyển chọn] Mai Anh (Nữ · Bắc · Tin tức)' },
    { value: 'Trúc Ly', label: '[Tuyển chọn] Trúc Ly (Nữ · Bắc · Tự nhiên)' },
    { value: 'Thanh Bình', label: 'Thanh Bình (Nam · Bắc · Kể chuyện)' },
    { value: 'Thùy Dung', label: '[Tuyển chọn] Thùy Dung (Nữ · Nam · Tin tức)' },
    { value: 'Anh Khôi', label: '[Tuyển chọn] Anh Khôi (Nam · Bắc · Kể chuyện)' },
    { value: 'Thiền Tâm Đức', label: '[Tuyển chọn] Thiền Tâm Đức (Nam · Bắc · Kể chuyện)' },
    { value: 'Ngọc Huyền', label: '[Tuyển chọn] Ngọc Huyền (Nữ · Bắc · Tự nhiên)' },
    { value: 'Quang Sơn', label: '[Tuyển chọn] Quang Sơn (Nam · Trung · Tự nhiên)' },
    { value: 'Ngọc Trân', label: '[Tuyển chọn] Ngọc Trân (Nữ · Trung · Tự nhiên)' },
    { value: 'Minh Đức', label: 'Minh Đức (Nam · Bắc · Tin tức)' },
    { value: 'Thái Sơn', label: 'Thái Sơn (Nam · Nam · Kể chuyện)' },
    { value: 'Xuân Vĩnh', label: 'Xuân Vĩnh (Nam · Bắc · Tự nhiên)' },
    { value: 'Ngọc Linh', label: 'Ngọc Linh (Nữ · Bắc · Kể chuyện)' },
    { value: 'Đoan Trang', label: 'Đoan Trang (Nữ · Bắc · Tự nhiên)' },
    { value: 'Thục Đoan', label: 'Thục Đoan (Nữ · Nam · Kể chuyện)' },
    { value: 'Minh Triết', label: 'Minh Triết (Nam · Nam · Tin tức)' },
    { value: 'Mỹ Duyên', label: 'Mỹ Duyên (Nữ · Nam · Đọc truyện)' },
    { value: 'Quỳnh Anh', label: 'Quỳnh Anh (Nữ · Bắc · Đọc truyện)' },
    { value: 'Đức Trí', label: 'Đức Trí (Nam · Nam · Đọc truyện)' },
    { value: 'Kim Thanh', label: 'Kim Thanh (Nữ · Nam · Đọc truyện)' },
    { value: 'Adam', label: 'Adam (Nam · Nam · Tự nhiên)' },
    { value: 'Adam bựa', label: '[Tuyển chọn] Adam bựa (Nam · Bắc · Tự nhiên)' },
    { value: 'Mạnh Dũng', label: 'Mạnh Dũng (Nam · Bắc · Tự nhiên)' },
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
  'dtr:gemini': [
    { value: 'Kore', label: 'Kore (Google Gemini - Nữ, chắc)' },
    { value: 'Puck', label: 'Puck (Google Gemini - Nam, vui)' },
    { value: 'Aoede', label: 'Aoede (Google Gemini - Nữ, ấm)' },
    { value: 'Charon', label: 'Charon (Google Gemini - Nam, dẫn chuyện)' },
    { value: 'Zephyr', label: 'Zephyr (Google Gemini - Nữ, sáng)' },
    { value: 'Laomedeia', label: 'Laomedeia (Google Gemini - Nữ, hào hứng)' },
    { value: 'Achird', label: 'Achird (Google Gemini - Nam, thân thiện)' },
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
  vieneu: 'Minh Quân Pro',
  'fpt-ai':  'banmai',
  'edge-tts': 'vi-VN-HoaiMyNeural',
  'dtr:gemini': 'Kore',
  'dtr:google-tts': 'google-tts/vi-VN-Wavenet-A',
  'dtr:edge-tts': 'vi-VN-HoaiMyNeural',
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
    catalog.forEach(eng => {
      const opt = document.createElement('option');
      opt.value = eng.id;
      opt.textContent = eng.label || eng.id;
      if (eng.id === current || (!current && fallback && eng.id === fallback.id)) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    // Giữ giá trị hiện tại nếu còn trong catalog, không thì dùng fpt-ai hoặc edge-tts làm default
    const currentEngine = catalog.find(e => e.id === current);
    const targetValue = currentEngine && _engineSupportsLang(currentEngine, lang)
      ? current
      : fallback?.id || '';
    sel.value = targetValue;
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

// Explicit resolver: {tts_engine, tts_voice} from an (engine, voice) id pair.
function _resolveTtsEngineVoiceEx(engineSelectId, voiceSelectId) {
  const engineEl = document.getElementById(engineSelectId);
  return {
    tts_engine: engineEl?.value || 'edge-tts',
    tts_voice: (voiceSelectId && document.getElementById(voiceSelectId)?.value) || 'vi-VN-HoaiMyNeural',
  };
}

// Convenience wrapper for the common "{base}-tts-engine"/"{base}-tts-voice" pages.
function _resolveTtsEngineVoice(base) {
  return _resolveTtsEngineVoiceEx(base + '-tts-engine', base + '-tts-voice');
}

function _isProcVoiceConvertEnabled() {
  const ttsTgl = document.getElementById('cfg-toggle-tts');
  if (ttsTgl) return !!ttsTgl.checked;
  const procVoice = document.getElementById('proc-voice');
  if (procVoice) return !!procVoice.checked;
  try {
    const saved = localStorage.getItem('cfg_toggle_tts');
    if (saved !== null) return saved !== '0';
  } catch (_) {}
  return true;
}

function _isProcTranslateSubsEnabled() {
  const transTgl = document.getElementById('cfg-toggle-trans');
  const procTrans = document.getElementById('proc-translate-subs');
  // Step 1 is the global AI switch; Step 2 is the per-output subtitle choice.
  // Both must allow translation. This prevents Step 3 from silently ignoring
  // the visible "Dịch" option in the editor.
  if (transTgl && procTrans) return !!transTgl.checked && !!procTrans.checked;
  if (transTgl) return !!transTgl.checked;
  if (procTrans) return !!procTrans.checked;
  try {
    const saved = localStorage.getItem('cfg_toggle_trans');
    if (saved !== null) return saved !== '0';
  } catch (_) {}
  return true;
}


function _populateMultiSpeakerVoiceSelects(preset, engine) {
  const maleEl = document.getElementById('proc-tts-voice-male');
  const femaleEl = document.getElementById('proc-tts-voice-female');
  if (!maleEl || !femaleEl || !preset || !preset.length) return;

  const currentMale = maleEl.value || '';
  const currentFemale = femaleEl.value || '';

  maleEl.innerHTML = '';
  femaleEl.innerHTML = '';

  preset.forEach(item => {
    const optM = document.createElement('option');
    optM.value = item.value;
    optM.textContent = item.label;
    maleEl.appendChild(optM);

    const optF = document.createElement('option');
    optF.value = item.value;
    optF.textContent = item.label;
    femaleEl.appendChild(optF);
  });

  // Pick best default for Male: look for "nam" or "male"
  const maleCandidate = preset.find(i => /nam|male/i.test(i.label || i.value)) || preset[0];
  const keepMale = preset.some(i => i.value === currentMale);
  maleEl.value = (keepMale && currentMale) ? currentMale : maleCandidate.value;

  // Pick best default for Female: look for "nữ|nu|female"
  const femaleCandidate = preset.find(i => /nữ|nu|female/i.test(i.label || i.value)) || preset[preset.length > 1 ? 1 : 0];
  const keepFemale = preset.some(i => i.value === currentFemale);
  femaleEl.value = (keepFemale && currentFemale) ? currentFemale : femaleCandidate.value;
}

function toggleMultiSpeakerOptions(enabled) {
  const wrap = document.getElementById('cfg-wrap-multi-voice');
  if (wrap) {
    if (enabled) {
      wrap.classList.remove('hidden');
      wrap.style.display = 'grid';
      _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
    } else {
      wrap.classList.add('hidden');
      wrap.style.display = 'none';
    }
  }
  try {
    localStorage.setItem('cfg_multi_speaker', enabled ? '1' : '0');
  } catch (_) {}
}
window.toggleMultiSpeakerOptions = toggleMultiSpeakerOptions;

function _syncVoiceOptions(engineSelectId, voiceSelectId) {
  const engineEl = document.getElementById(engineSelectId);
  const voiceEl = document.getElementById(voiceSelectId);
  if (!engineEl || !voiceEl) return;

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
      if (voiceSelectId === 'proc-tts-voice') _populateMultiSpeakerVoiceSelects(preset, engine);
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
    if (voiceSelectId === 'proc-tts-voice') _populateMultiSpeakerVoiceSelects(voices, engine);
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
  if (voiceSelectId === 'proc-tts-voice') _populateMultiSpeakerVoiceSelects(preset, engine);
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
      if (nameEl) nameEl.textContent = ` [${i+1}/${files.length}] Đang tải lên: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
      if (pathEl) pathEl.value = ` [${i+1}/${files.length}] Đang tải lên: ${file.name}`;
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
        if (nameEl) nameEl.textContent = ` Lỗi tải lên ${file.name}: ${err.message}`;
        if (typeof toast === 'function') toast(` Lỗi tải lên ${file.name}: ${err.message}`, 'danger');
      }
    }

    // Done all uploads
    if (pathEl) pathEl.value = '';
    if (nameEl) nameEl.textContent = ` Đã tải lên thành công ${successCount}/${files.length} file video`;
    if (progressBar) progressBar.style.width = '100%';
    if (progressText) progressText.textContent = ' Hoàn thành';
    if (typeof toast === 'function') toast(` Đã tải lên và thêm vào hàng chờ ${successCount} file video`, 'success');
    setTimeout(() => { if (progressWrap) progressWrap.style.display = 'none'; }, 2000);

    // Clear input value so same files can be re-selected if needed
    input.value = '';

    // Clear the active file upload state
    window._procSelectedFile = null;
    window._procUploadedPath = null;
    window._procUploadPromise = null;
  })();
}

function _escapeDownloadedText(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function addDownloadedVideo(path) {
  if (!path) return;
  const videoInput = document.getElementById('proc-video');
  if (videoInput) videoInput.value = path;
  if (Array.isArray(window._batchQueue) && typeof buildNewTask === 'function') {
    const exists = window._batchQueue.some(item => item?.val === path || item?.path === path);
    if (!exists) window._batchQueue.push(buildNewTask('file', path));
    if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
    if (typeof _step1UpdateDownloadArea === 'function') _step1UpdateDownloadArea();
  }
  if (typeof toast === 'function') toast('Đã thêm video tải xuống vào hàng chờ', 'success');
}
window.addDownloadedVideo = addDownloadedVideo;

window._procFilesDir = window._procFilesDir || '';

function _processSvgIcon(name, className = '', size = 14) {
  const paths = {
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"></path><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"></path>',
    settings: '<path d="M4 7h16M4 17h16"></path><circle cx="9" cy="7" r="3"></circle><circle cx="15" cy="17" r="3"></circle>',
    video: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="m10 9 5 3-5 3Z"></path><path d="m7 3 2 2m4-2 2 2m4-2 2 2"></path>',
    audio: '<path d="M9 18V5l10-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="16" cy="16" r="3"></circle>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="8.5" cy="9" r="1.5"></circle><path d="m21 15-5-5L5 20"></path>',
    subtitle: '<path d="M4 5h16v12H7l-3 3Z"></path><path d="M8 10h3m2 0h3M8 14h8"></path>',
    document: '<path d="M6 2h8l4 4v16H6Z"></path><path d="M14 2v5h5M9 12h6m-6 4h6"></path>',
    folder: '<path d="M3 6h7l2 2h9l-2 11H3Z"></path>',
    eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6Z"></path><circle cx="12" cy="12" r="2.5"></circle>',
    upload: '<path d="M12 16V4m0 0-4 4m4-4 4 4"></path><path d="M5 14v5h14v-5"></path>',
    plus: '<path d="M12 5v14M5 12h14"></path>',
    trash: '<path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7m4 4v6m4-6v6"></path>',
    arrowUp: '<path d="m6 10 6-6 6 6M12 4v16"></path>',
    close: '<path d="m6 6 12 12M18 6 6 18"></path>',
    dotsVertical: '<circle cx="12" cy="5" r="1.75"></circle><circle cx="12" cy="12" r="1.75"></circle><circle cx="12" cy="19" r="1.75"></circle>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>'
  };
  const body = paths[name] || paths.document;
  return `<svg class="proc-svg-icon ${className}" width="${size}" height="${size}" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:${size}px;height:${size}px;max-width:${size}px;max-height:${size}px;flex-shrink:0;display:inline-block;vertical-align:middle;">${body}</svg>`;
}

function _processFileIcon(item) {
  if (item.is_dir) return `<span style="color:#f59e0b;display:inline-flex;align-items:center">${_processSvgIcon('folder', '', 16)}</span>`;
  if (item.file_type === 'video') return `<span style="color:#f43f5e;display:inline-flex;align-items:center">${_processSvgIcon('video', '', 16)}</span>`;
  if (item.file_type === 'subtitle') return `<span style="color:#10b981;display:inline-flex;align-items:center">${_processSvgIcon('subtitle', '', 16)}</span>`;
  if (item.file_type === 'audio') return `<span style="color:#a855f7;display:inline-flex;align-items:center">${_processSvgIcon('audio', '', 16)}</span>`;
  if (item.file_type === 'image') return `<span style="color:#3b82f6;display:inline-flex;align-items:center">${_processSvgIcon('image', '', 16)}</span>`;
  return `<span style="color:#0ea5e9;display:inline-flex;align-items:center">${_processSvgIcon('document', '', 16)}</span>`;
}

function _processFileGridIcon(item) {
  if (item.is_dir) return `<span style="color:#f59e0b;display:inline-flex;align-items:center">${_processSvgIcon('folder', '', 28)}</span>`;
  if (item.file_type === 'video') return `<span style="color:#f43f5e;display:inline-flex;align-items:center">${_processSvgIcon('video', '', 28)}</span>`;
  if (item.file_type === 'subtitle') return `<span style="color:#10b981;display:inline-flex;align-items:center">${_processSvgIcon('subtitle', '', 28)}</span>`;
  if (item.file_type === 'audio') return `<span style="color:#a855f7;display:inline-flex;align-items:center">${_processSvgIcon('audio', '', 28)}</span>`;
  if (item.file_type === 'image') return `<span style="color:#3b82f6;display:inline-flex;align-items:center">${_processSvgIcon('image', '', 28)}</span>`;
  return `<span style="color:#0ea5e9;display:inline-flex;align-items:center">${_processSvgIcon('document', '', 28)}</span>`;
}

function closeDownloadedPreviewModal() {
  const modal = document.getElementById('proc-downloaded-preview-modal');
  if (modal) {
    modal.querySelectorAll('video,audio').forEach(media => {
      try { media.pause(); media.removeAttribute('src'); media.load(); } catch (_) {}
    });
    modal.remove();
  }
  document.removeEventListener('keydown', _downloadedPreviewEscHandler);
}
window.closeDownloadedPreviewModal = closeDownloadedPreviewModal;

function _downloadedPreviewEscHandler(event) {
  if (event.key === 'Escape') closeDownloadedPreviewModal();
}

async function openDownloadedPreviewModal(item) {
  if (!item?.path) return;
  closeDownloadedPreviewModal();
  const modal = document.createElement('div');
  modal.id = 'proc-downloaded-preview-modal';
  modal.className = 'proc-preview-modal-backdrop';
  modal.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(15,23,42,0.82);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', `Xem trước ${item.name || 'file'}`);
  const previewUrl = ((item.file_type === 'video' || /\.(mp4|mkv|mov|webm|avi|m4v)$/i.test(item.path)) ? '/api/files/preview-compatible?path=' : '/api/files/preview?path=') + encodeURIComponent(item.path);

  let bodyHtml = '';
  const ftype = item.file_type || '';
  const ext = (item.ext || '').toLowerCase();

  if (ftype === 'video') {
    bodyHtml = `
      <div class="proc-preview-modal-body" style="display:flex;align-items:center;justify-content:center;background:#000;min-height:300px;max-height:calc(90vh - 60px);overflow:hidden;position:relative">
        <div id="proc-video-loading" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#e2e8f0;font-size:12px;pointer-events:none">Đang mở video...</div>
        <video src="${previewUrl}" controls autoplay playsinline preload="metadata" style="max-width:100%;max-height:calc(90vh - 60px);width:auto;height:auto;display:block;outline:none;margin:auto"></video>
      </div>`;
  } else if (ftype === 'audio') {
    bodyHtml = `
      <div class="proc-preview-modal-body" style="display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--bg3,#0b0f19);padding:36px 20px;min-height:220px">
        <div style="color:#a855f7;margin-bottom:12px">${_processSvgIcon('audio', '', 40)}</div>
        <div style="font-weight:600;font-size:13px;color:var(--text,#f8fafc);margin-bottom:16px;text-align:center;max-width:80%;word-break:break-all">${_escapeDownloadedText(item.name)}</div>
        <audio src="${previewUrl}" controls autoplay style="width:100%;max-width:440px;outline:none"></audio>
      </div>`;
  } else if (ftype === 'image') {
    bodyHtml = `
      <div class="proc-preview-modal-body" style="display:flex;align-items:center;justify-content:center;background:#000;min-height:300px;max-height:calc(90vh - 60px);padding:10px">
        <img src="${previewUrl}" alt="${_escapeDownloadedText(item.name)}" style="max-width:100%;max-height:calc(90vh - 80px);object-fit:contain;display:block;margin:auto" />
      </div>`;
  } else {
    // Subtitles, text, json, log, documents
    const isSubtitle = (ftype === 'subtitle') || (ext === '.ass' || ext === '.srt');
    bodyHtml = `
      <div class="proc-preview-modal-body" style="display:flex;flex-direction:column;background:#0b0f19;min-height:380px;height:70vh;max-height:calc(88vh - 60px);overflow:hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 14px;background:#111827;border-bottom:1px solid #1f2937">
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:11px;color:#94a3b8;font-family:monospace" id="proc-preview-lines-info">Đang tải nội dung...</span>
            ${isSubtitle ? '<span class="badge" style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3);font-size:10px;padding:1px 6px;border-radius:4px">Chế độ chỉnh sửa phụ đề</span>' : ''}
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            <button type="button" class="btn btn-secondary btn-sm" id="proc-copy-preview-btn" style="display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 8px">
              ${_processSvgIcon('copy', '', 12)}<span>Sao chép</span>
            </button>
            ${isSubtitle ? `
            <button type="button" class="btn btn-primary btn-sm" id="proc-save-sub-btn" style="display:inline-flex;align-items:center;gap:5px;font-size:11px;padding:3px 10px;font-weight:600">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Lưu thay đổi</span>
            </button>` : ''}
          </div>
        </div>
        <textarea id="proc-preview-text-box" spellcheck="false" style="flex:1;width:100%;margin:0;padding:14px;font-family:Consolas,Monaco,'Courier New',monospace;font-size:12px;line-height:1.6;color:#e2e8f0;background:#080d1a;border:0;outline:none;resize:none;white-space:pre;word-break:normal;overflow:auto;box-sizing:border-box" placeholder="Nội dung file..."></textarea>
      </div>`;
  }

  modal.innerHTML = `
    <div class="proc-preview-modal-panel" style="background:var(--bg2,#1e293b);border:1px solid var(--border,#334155);border-radius:14px;max-width:860px;width:100%;max-height:90vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 50px -12px rgba(0,0,0,0.5)">
      <div class="proc-preview-modal-header" style="display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--border);background:var(--bg3,#0f172a)">
        <div class="proc-preview-modal-title" style="display:flex;align-items:center;gap:8px;font-weight:600;font-size:12px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%">
          ${_processFileIcon(item)}
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_escapeDownloadedText(item.name || 'Xem trước file')}</span>
        </div>
        <button type="button" class="btn btn-secondary btn-sm proc-preview-modal-close" title="Đóng" aria-label="Đóng cửa sổ xem trước" style="padding:4px 8px;cursor:pointer">${_processSvgIcon('close')}</button>
      </div>
      ${bodyHtml}
    </div>`;

  modal.addEventListener('click', event => {
    if (event.target === modal) closeDownloadedPreviewModal();
  });
  modal.querySelector('.proc-preview-modal-close')?.addEventListener('click', closeDownloadedPreviewModal);
  document.body.appendChild(modal);
  const previewVideo = modal.querySelector('video');
  if (previewVideo) {
    const loading = modal.querySelector('#proc-video-loading');
    previewVideo.addEventListener('loadedmetadata', () => { if (loading) loading.style.display = 'none'; });
    previewVideo.addEventListener('error', () => { if (loading) loading.textContent = 'Không mở được video. Hãy mở file gốc để xem.'; });
  }
  document.addEventListener('keydown', _downloadedPreviewEscHandler);
  modal.querySelector('.proc-preview-modal-close')?.focus();

  // If text/subtitle preview, fetch the text content
  const textBox = modal.querySelector('#proc-preview-text-box');
  if (textBox) {
    try {
      const res = await fetch(previewUrl);
      const text = await res.text();
      textBox.value = text || '';
      const linesInfo = modal.querySelector('#proc-preview-lines-info');
      if (linesInfo) {
        const lineCount = (text.match(/\n/g) || []).length + 1;
        linesInfo.textContent = `${lineCount} dòng · ${_escapeDownloadedText(item.size_str || '')}`;
      }

      textBox.addEventListener('input', () => {
        if (linesInfo) {
          const lineCount = (textBox.value.match(/\n/g) || []).length + 1;
          linesInfo.textContent = `${lineCount} dòng · Chưa lưu *`;
        }
      });

      const copyBtn = modal.querySelector('#proc-copy-preview-btn');
      if (copyBtn) {
        copyBtn.addEventListener('click', () => {
          navigator.clipboard.writeText(textBox.value);
          if (typeof toast === 'function') toast('Đã sao chép nội dung vào bộ nhớ tạm', 'success');
        });
      }

      const saveBtn = modal.querySelector('#proc-save-sub-btn');
      if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
          const val = textBox.value;
          try {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span>Đang lưu...</span>';
            const res = await fetch('/api/proc_save_ass', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: item.abs_path || item.path, content: val })
            });
            const data = await res.json();
            if (data.ok) {
              if (typeof toast === 'function') toast(' Đã lưu phụ đề thành công!', 'success');
              if (linesInfo) {
                const lineCount = (val.match(/\n/g) || []).length + 1;
                linesInfo.textContent = `${lineCount} dòng · Đã lưu`;
              }
            } else {
              if (typeof toast === 'function') toast(' Lỗi lưu phụ đề: ' + (data.error || 'Unknown'), 'error');
            }
          } catch (e) {
            if (typeof toast === 'function') toast(' Lỗi: ' + e.message, 'error');
          } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg><span>Lưu thay đổi</span>';
          }
        });
      }
    } catch (err) {
      textBox.value = 'Lỗi tải file: ' + err.message;
    }
  }
}
window.openDownloadedPreviewModal = openDownloadedPreviewModal;

window._procFilesViewMode = localStorage.getItem('proc_files_view_mode') || 'list';
window._procSelectedFiles = window._procSelectedFiles || new Set();
window._procCurrentFilesData = null;

function setDownloadedViewMode(mode) {
  window._procFilesViewMode = mode;
  localStorage.setItem('proc_files_view_mode', mode);
  _updateViewModeButtons();
  if (window._procCurrentFilesData) {
    _renderDownloadedItems(window._procCurrentFilesData);
  }
}
window.setDownloadedViewMode = setDownloadedViewMode;

function _updateViewModeButtons() {
  const btnList = document.getElementById('proc-view-btn-list');
  const btnGrid = document.getElementById('proc-view-btn-grid');
  const isGrid = window._procFilesViewMode === 'grid';
  if (btnList) {
    btnList.className = isGrid
      ? 'px-1.5 py-0.5 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-all'
      : 'px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 shadow-xs transition-all';
  }
  if (btnGrid) {
    btnGrid.className = isGrid
      ? 'px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 shadow-xs transition-all'
      : 'px-1.5 py-0.5 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-all';
  }
}

function toggleSelectAllDownloadedFiles(checked) {
  const items = (window._procCurrentFilesData && window._procCurrentFilesData.items) || [];
  if (checked) {
    items.forEach(item => {
      const p = item.path || item.abs_path;
      if (p) window._procSelectedFiles.add(p);
    });
  } else {
    window._procSelectedFiles.clear();
  }
  document.querySelectorAll('.proc-file-checkbox').forEach(cb => {
    cb.checked = checked;
  });
  document.querySelectorAll('.proc-downloaded-history-row, .proc-file-card').forEach(el => {
    if (checked) {
      el.style.background = 'rgba(99,102,241,0.08)';
      el.style.borderColor = 'var(--accent, #6366f1)';
    } else {
      el.style.background = '';
      el.style.borderColor = 'var(--border)';
    }
  });
  _updateBatchDeleteBtn();
}
window.toggleSelectAllDownloadedFiles = toggleSelectAllDownloadedFiles;

function onDownloadedItemCheckChanged(cb) {
  const path = cb.dataset.path;
  if (!path) return;
  if (cb.checked) {
    window._procSelectedFiles.add(path);
  } else {
    window._procSelectedFiles.delete(path);
  }
  const parent = cb.closest('.proc-downloaded-history-row, .proc-file-card');
  if (parent) {
    if (cb.checked) {
      parent.style.background = 'rgba(99,102,241,0.08)';
      parent.style.borderColor = 'var(--accent, #6366f1)';
    } else {
      parent.style.background = '';
      parent.style.borderColor = 'var(--border)';
    }
  }
  _updateBatchDeleteBtn();
}
window.onDownloadedItemCheckChanged = onDownloadedItemCheckChanged;

function _updateBatchDeleteBtn() {
  const count = window._procSelectedFiles.size;
  const btn = document.getElementById('proc-batch-del-btn');
  const countSpan = document.getElementById('proc-batch-del-count');
  if (btn) btn.style.display = count > 0 ? 'inline-flex' : 'none';
  if (countSpan) countSpan.textContent = `Xóa (${count})`;

  const selectAllCb = document.getElementById('proc-select-all-files');
  const items = (window._procCurrentFilesData && window._procCurrentFilesData.items) || [];
  if (selectAllCb) {
    if (items.length > 0 && count === items.length) {
      selectAllCb.checked = true;
      selectAllCb.indeterminate = false;
    } else if (count > 0 && count < items.length) {
      selectAllCb.checked = false;
      selectAllCb.indeterminate = true;
    } else {
      selectAllCb.checked = false;
      selectAllCb.indeterminate = false;
    }
  }
}

async function deleteSelectedDownloadedFiles() {
  const paths = Array.from(window._procSelectedFiles);
  if (paths.length === 0) return;
  if (!confirm(`Bạn có chắc muốn xóa ${paths.length} file / thư mục đã chọn? Thao tác này không thể hoàn tác.`)) return;

  try {
    const res = await fetch('/api/files/batch_delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths })
    });
    const result = await res.json();
    if (!res.ok || !result.ok) throw new Error(result.error || (result.errors && result.errors.join(', ')) || 'Xóa thất bại');
    if (typeof toast === 'function') toast(`Đã xóa ${result.deleted || paths.length} mục thành công`, 'success');
    window._procSelectedFiles.clear();
    loadDownloadedVideos(window._procFilesDir || '');
  } catch (err) {
    if (typeof toast === 'function') toast('Lỗi xóa mục: ' + err.message, 'error');
  }
}
window.deleteSelectedDownloadedFiles = deleteSelectedDownloadedFiles;

function _procGridPlayPreview(el) {
  const v = el.querySelector('video');
  if (!v) return;
  v.style.display = 'block';
  try {
    if (v.readyState >= 1) v.currentTime = 0.5;
    const p = v.play();
    if (p && typeof p.catch === 'function') {
      p.catch(() => {});
    }
  } catch (_) {}
}
window._procGridPlayPreview = _procGridPlayPreview;

function _procGridStopPreview(el) {
  const v = el.querySelector('video');
  if (!v) return;
  try {
    v.pause();
    v.currentTime = 0;
  } catch (_) {}
  v.style.display = 'none';
}
window._procGridStopPreview = _procGridStopPreview;

function _renderGridMediaPreview(item, index, safePath) {
  const isVideo = item.file_type === 'video' || /\.(mp4|mkv|mov|webm|avi|m4v)$/i.test(item.name || item.path || '');
  const isImage = item.file_type === 'image' || /\.(jpg|jpeg|png|webp|gif|bmp)$/i.test(item.name || item.path || '');
  
  if (isVideo) {
    const thumbUrl = '/api/files/thumbnail?path=' + encodeURIComponent(item.path);
    const videoUrl = '/api/files/preview-compatible?path=' + encodeURIComponent(item.path);
    return `
      <div class="proc-file-click proc-grid-media-preview" data-index="${index}" 
           style="width:100%;height:78px;border-radius:8px;overflow:hidden;background:#090d16;position:relative;margin:2px 0 6px;cursor:pointer;display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,0.08);box-shadow:0 1px 3px rgba(0,0,0,0.2)"
           title="${safePath}"
           onmouseenter="_procGridPlayPreview(this)"
           onmouseleave="_procGridStopPreview(this)">
        <img src="${thumbUrl}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block" alt="${safePath}" 
             onerror="this.style.display='none';const f=this.nextElementSibling;if(f)f.style.display='flex';" />
        <div style="display:none;align-items:center;justify-content:center;width:100%;height:100%;color:#f43f5e">
          ${_processSvgIcon('video', '', 32)}
        </div>
        <div class="proc-grid-play-icon" style="position:absolute;inset:0;background:rgba(0,0,0,0.2);display:flex;align-items:center;justify-content:center;pointer-events:none;transition:opacity 0.2s">
          <div style="width:24px;height:24px;border-radius:50%;background:rgba(0,0,0,0.65);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;color:#ffffff;box-shadow:0 2px 6px rgba(0,0,0,0.4)">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          </div>
        </div>
        <video src="${videoUrl}" muted playsinline preload="none" style="display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:2;pointer-events:none"></video>
      </div>`;
  }
  
  if (isImage) {
    const imgUrl = '/api/files/thumbnail?path=' + encodeURIComponent(item.path);
    return `
      <div class="proc-file-click proc-grid-media-preview" data-index="${index}" 
           style="width:100%;height:78px;border-radius:8px;overflow:hidden;background:#090d16;position:relative;margin:2px 0 6px;cursor:pointer;display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,0.08);box-shadow:0 1px 3px rgba(0,0,0,0.2)"
           title="${safePath}">
        <img src="${imgUrl}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block" alt="${safePath}" 
             onerror="this.style.display='none';this.nextElementSibling.style.display='flex';" />
        <div style="display:none;align-items:center;justify-content:center;width:100%;height:100%;color:#3b82f6">
          ${_processSvgIcon('image', '', 32)}
        </div>
      </div>`;
  }

  return `
    <div class="${item.is_dir ? 'proc-open-folder' : 'proc-file-click'}" data-index="${index}" 
         style="margin:2px 0 6px;display:flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:12px;background:${item.is_dir ? 'rgba(245,158,11,0.1)' : 'rgba(99,102,241,0.08)'};cursor:pointer" 
         title="${safePath}">
      ${_processFileGridIcon(item)}
    </div>`;
}

function _renderDownloadedItems(data) {
  const list = document.getElementById('proc-downloaded-list');
  if (!list) return;
  window._procCurrentFilesData = data;
  document.querySelectorAll(".proc-dropdown-menu[data-portal="true"]").forEach(menu => menu.remove());
  _updateViewModeButtons();

  const items = Array.isArray(data.items) ? data.items : [];
  const currentDir = window._procFilesDir || '';
  const isGrid = window._procFilesViewMode === 'grid';

  // Synchronize selection with existing items
  const currentPaths = new Set(items.map(i => i.path || i.abs_path));
  for (const p of window._procSelectedFiles) {
    if (!currentPaths.has(p)) window._procSelectedFiles.delete(p);
  }
  _updateBatchDeleteBtn();

  if (!items.length) {
    list.innerHTML = '<div class="empty-state text-xs p-6 text-center text-slate-400">Thư mục trống.</div>';
    return;
  }

  // Generate action dropdown HTML for an item
  const renderAction = (item, index) => `
    <div class="proc-dropdown-wrapper" style="position:relative;display:inline-block">
      <button type="button" class="btn btn-secondary btn-sm proc-dropdown-trigger" data-index="${index}" title="Chức năng" aria-label="Tùy chọn cho ${item.name}" style="padding:2px 6px;display:inline-flex;align-items:center;justify-content:center;height:24px;border-radius:6px;border:1px solid var(--border);background:transparent">
        ${_processSvgIcon('dotsVertical', '', 14)}
      </button>
      <div class="proc-dropdown-menu" id="proc-dropdown-${index}" style="display:none;position:fixed;z-index:999999;background:var(--bg2,#ffffff);border:1px solid var(--border,#e2e8f0);border-radius:8px;box-shadow:0 12px 30px -4px rgba(0,0,0,0.25), 0 4px 12px rgba(0,0,0,0.1);min-width:170px;padding:4px 0">
        ${(!item.is_dir && (item.file_type === 'subtitle' || (item.ext && (item.ext.toLowerCase() === '.ass' || item.ext.toLowerCase() === '.srt')))) ? `
        <button type="button" class="proc-menu-item proc-preview-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:#10b981;font-size:12px;text-align:left;cursor:pointer">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
          <span>Sửa phụ đề</span>
        </button>` : (!item.is_dir ? `
        <button type="button" class="proc-menu-item proc-preview-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:var(--text);font-size:12px;text-align:left;cursor:pointer">
          ${_processSvgIcon('eye')} <span>Xem file</span>
        </button>` : '')}
        ${item.file_type === 'video' ? `
        <button type="button" class="proc-menu-item proc-publish-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:var(--accent);font-size:12px;text-align:left;cursor:pointer">
          ${_processSvgIcon('upload')} <span>Đăng video</span>
        </button>` : ''}
        ${(item.file_type === 'video' || item.file_type === 'audio') ? `
        <button type="button" class="proc-menu-item proc-use-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:#0ea5e9;font-size:12px;text-align:left;cursor:pointer">
          ${_processSvgIcon('plus')} <span>Thêm hàng chờ</span>
        </button>` : ''}
        <button type="button" class="proc-menu-item proc-reveal-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:var(--text);font-size:12px;text-align:left;cursor:pointer">
          ${_processSvgIcon('folder')} <span>Mở thư mục</span>
        </button>
        <div style="height:1px;background:var(--border,#e2e8f0);margin:4px 0"></div>
        <button type="button" class="proc-menu-item proc-delete-downloaded" data-index="${index}" style="width:100%;display:flex;align-items:center;gap:8px;padding:7px 12px;border:0;background:none;color:var(--danger,#ef4444);font-size:12px;text-align:left;cursor:pointer">
          ${_processSvgIcon('trash')} <span>Xóa</span>
        </button>
      </div>
    </div>`;

  if (isGrid) {
    // ── GRID VIEW ──
    const backCard = currentDir
      ? `<div style="grid-column:1 / -1;margin-bottom:2px">
           <button type="button" class="proc-file-back" style="width:100%;display:flex;align-items:center;gap:6px;padding:7px 12px;border:1px dashed var(--border);border-radius:8px;background:var(--bg3,#f8fafc);color:var(--accent);font-size:11.5px;font-weight:500;cursor:pointer">
             ${_processSvgIcon('arrowUp')} <span>Lên thư mục cha</span>
           </button>
         </div>`
      : '';

    const cardsHtml = items.map((item, index) => {
      const itemKey = item.path || item.abs_path;
      const safePath = _escapeDownloadedText(itemKey);
      const isSelected = window._procSelectedFiles.has(itemKey);
      const meta = item.is_dir ? `${item.child_count ?? 0} mục` : _escapeDownloadedText(item.size_str);

      return `
        <div class="proc-file-card ${isSelected ? 'proc-item-selected' : ''}" data-index="${index}" style="position:relative;border:1px solid ${isSelected ? 'var(--accent,#6366f1)' : 'var(--border)'};border-radius:10px;background:${isSelected ? 'rgba(99,102,241,0.08)' : 'var(--bg2,#ffffff)'};padding:8px 8px 10px;display:flex;flex-direction:column;align-items:center;text-align:center;transition:all 0.15s ease;user-select:none;box-shadow:0 1px 2px rgba(0,0,0,0.03)" title="${safePath}">
          <div style="width:100%;display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
            <input type="checkbox" class="proc-file-checkbox" data-path="${itemKey}" data-index="${index}" ${isSelected ? 'checked' : ''} style="cursor:pointer;width:14px;height:14px;accent-color:var(--accent,#6366f1)">
            ${renderAction(item, index)}
          </div>
          ${_renderGridMediaPreview(item, index, safePath)}
          <div class="${item.is_dir ? 'proc-open-folder' : 'proc-file-click'}" data-index="${index}" style="width:100%;font-size:11.5px;font-weight:${item.is_dir ? '600' : '500'};color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;cursor:pointer" title="${_escapeDownloadedText(item.name)}">
            ${_escapeDownloadedText(item.name)}
          </div>
          <div style="margin-top:4px;font-size:10px;color:var(--text-muted);display:flex;align-items:center;justify-content:center;gap:3px;width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            <span>${meta}</span>
            <span>·</span>
            <span>${_escapeDownloadedText(item.mtime)}</span>
          </div>
        </div>`;
    }).join('');

    list.innerHTML = `<div class="proc-files-grid" style="display:grid;grid-template-columns:repeat(auto-fill, minmax(136px, 1fr));gap:9px;padding:4px;overflow:visible">${backCard}${cardsHtml}</div>`;
  } else {
    // ── LIST VIEW ──
    const backRow = currentDir
      ? `<div style="padding:9px 12px;border-bottom:1px solid var(--border);background:var(--bg3,#f8fafc)"><button type="button" class="proc-file-back" style="border:0;background:none;padding:0;cursor:pointer;color:var(--accent);font-size:12px;display:inline-flex;align-items:center;gap:5px">${_processSvgIcon('arrowUp')}<span>Lên thư mục cha</span></button></div>`
      : '';

    list.innerHTML = `<div style="border:1px solid var(--border);border-radius:7px;overflow:visible">${backRow}${items.map((item, index) => {
      const itemKey = item.path || item.abs_path;
      const safePath = _escapeDownloadedText(itemKey);
      const isSelected = window._procSelectedFiles.has(itemKey);

      let typeBadge = '';
      if (item.file_type === 'video') {
        typeBadge = `<span class="badge" style="background:rgba(244,63,94,0.12);color:#f43f5e;border:1px solid rgba(244,63,94,0.25);font-size:10px;padding:1px 5px;border-radius:4px">Video</span>`;
      } else if (item.file_type === 'subtitle') {
        typeBadge = `<span class="badge" style="background:rgba(16,185,129,0.12);color:#10b981;border:1px solid rgba(16,185,129,0.25);font-size:10px;padding:1px 5px;border-radius:4px">Phụ đề</span>`;
      } else if (item.file_type === 'audio') {
        typeBadge = `<span class="badge" style="background:rgba(168,85,247,0.12);color:#a855f7;border:1px solid rgba(168,85,247,0.25);font-size:10px;padding:1px 5px;border-radius:4px">Audio</span>`;
      }

      const meta = item.is_dir
        ? `${item.child_count ?? 0} mục · ${_escapeDownloadedText(item.mtime)}`
        : `${_escapeDownloadedText(item.size_str)} · ${_escapeDownloadedText(item.mtime)}`;

      const fileMeta = item.is_dir
        ? ''
        : `<div class="text-xs text-muted" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:2px">
            ${typeBadge}
            ${item.ext ? `<span class="badge" style="font-size:10px;padding:1px 5px">${_escapeDownloadedText(item.ext)}</span>` : ''}
            <span>${meta}</span>
          </div>`;

      let nameColor = 'var(--text)';
      if (item.is_dir) nameColor = 'var(--text, #1e293b)';
      else if (item.file_type === 'video') nameColor = 'var(--text)';
      else if (item.file_type === 'subtitle') nameColor = '#059669';
      else if (item.file_type === 'audio') nameColor = '#7c3aed';

      return `<div class="proc-downloaded-history-row ${isSelected ? 'proc-item-selected' : ''}" data-index="${index}" style="display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);position:relative;background:${isSelected ? 'rgba(99,102,241,0.08)' : 'transparent'}">
        <input type="checkbox" class="proc-file-checkbox" data-path="${itemKey}" data-index="${index}" ${isSelected ? 'checked' : ''} style="cursor:pointer;width:14px;height:14px;accent-color:var(--accent,#6366f1);margin-right:2px;flex-shrink:0">
        <div style="min-width:0;flex:1">
          <button type="button" class="${item.is_dir ? 'proc-open-folder' : 'proc-file-click'}" data-index="${index}" style="display:flex;align-items:center;gap:7px;width:100%;text-align:left;border:0;background:none;padding:0;color:${nameColor};font-size:12.5px;font-weight:${item.is_dir ? '600' : '500'};cursor:pointer" title="${safePath}">
            ${_processFileIcon(item)}
            <span style="min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_escapeDownloadedText(item.name)}</span>
          </button>
          ${fileMeta}
        </div>
        ${item.is_dir ? `<div class="text-xs text-muted" style="white-space:nowrap">${meta}</div>` : ''}
        ${renderAction(item, index)}
      </div>`;
    }).join('')}</div>`;
  }

  // Attach event listeners
  list.querySelector('.proc-file-back')?.addEventListener('click', () => loadDownloadedVideos(data.parent === '.' ? '' : (data.parent || '')));

  list.querySelectorAll('.proc-file-checkbox').forEach(cb => {
    cb.addEventListener('change', e => {
      e.stopPropagation();
      onDownloadedItemCheckChanged(cb);
    });
    cb.addEventListener('click', e => e.stopPropagation());
  });

  list.querySelectorAll('.proc-open-folder').forEach(button => {
    button.addEventListener('click', e => {
      e.stopPropagation();
      loadDownloadedVideos(items[Number(button.dataset.index)]?.path || '');
    });
  });

  list.querySelectorAll('.proc-file-click').forEach(button => {
    button.addEventListener('click', e => {
      e.stopPropagation();
      const item = items[Number(button.dataset.index)];
      if (item?.path) openDownloadedPreviewModal(item);
    });
  });

  // 3-dots dropdown trigger handler with fixed upward/downward floating popup
  list.querySelectorAll('.proc-dropdown-trigger').forEach(trigger => {
    trigger.addEventListener('click', e => {
      e.stopPropagation();
      const idx = trigger.dataset.index;
      const menu = trigger.parentElement.querySelector(".proc-dropdown-menu") || document.getElementById(`proc-dropdown-${idx}`);
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => {
        if (m !== menu) m.style.display = 'none';
      });
      if (menu) {
        const isOpening = menu.style.display !== 'block';
        if (isOpening) {
          if (menu.parentElement !== document.body) { document.body.appendChild(menu); menu.dataset.portal = 'true'; }
          const btnRect = trigger.getBoundingClientRect();
          const spaceBelow = window.innerHeight - btnRect.bottom;
          const menuHeight = 150;

          menu.style.position = 'fixed';
          menu.style.right = Math.max(10, window.innerWidth - btnRect.right) + 'px';
          menu.style.left = 'auto';
          menu.style.zIndex = '999999';

          if (spaceBelow < menuHeight) {
            menu.style.top = 'auto';
            menu.style.bottom = (window.innerHeight - btnRect.top + 4) + 'px';
          } else {
            menu.style.bottom = 'auto';
            menu.style.top = (btnRect.bottom + 4) + 'px';
          }
          menu.style.display = 'block';
        } else {
          menu.style.display = 'none';
        }
      }
    });
  });

  list.addEventListener('scroll', () => {
    document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
  }, { passive: true });

  list.querySelectorAll('.proc-menu-item').forEach(item => {
    item.addEventListener('mouseenter', () => item.style.background = 'var(--bg3, rgba(125,125,125,0.1))');
    item.addEventListener('mouseleave', () => item.style.background = 'none');
  });

  list.querySelectorAll('.proc-preview-downloaded').forEach(button => {
    button.addEventListener('click', e => {
      e.stopPropagation();
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
      const item = items[Number(button.dataset.index)];
      if (item?.path) openDownloadedPreviewModal(item);
    });
  });

  list.querySelectorAll('.proc-use-downloaded').forEach(button => {
    button.addEventListener('click', e => {
      e.stopPropagation();
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
      addDownloadedVideo(items[Number(button.dataset.index)]?.abs_path || items[Number(button.dataset.index)]?.path);
    });
  });

  list.querySelectorAll('.proc-publish-downloaded').forEach(button => {
    button.addEventListener('click', e => {
      e.stopPropagation();
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
      const item = items[Number(button.dataset.index)];
      if (item?.abs_path && typeof sendToPublish === 'function') sendToPublish(item.abs_path);
    });
  });

  list.querySelectorAll('.proc-reveal-downloaded').forEach(button => {
    button.addEventListener('click', async e => {
      e.stopPropagation();
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
      const item = items[Number(button.dataset.index)];
      const targetPath = item?.abs_path || item?.path;
      if (!targetPath) return;
      try {
        const res = await fetch('/api/files/open_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: targetPath })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || 'Không mở được thư mục');
      } catch (error) {
        if (typeof toast === 'function') toast('Không mở được thư mục: ' + error.message, 'error');
      }
    });
  });

  list.querySelectorAll('.proc-delete-downloaded').forEach(button => {
    button.addEventListener('click', async e => {
      e.stopPropagation();
      document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
      const item = items[Number(button.dataset.index)];
      const targetPath = item?.abs_path || item?.path;
      if (!targetPath || !confirm(`Xóa "${item.name}"?`)) return;
      try {
        const res = await fetch('/api/files/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: targetPath })
        });
        const result = await res.json();
        if (!res.ok || !result.ok) throw new Error(result.error || 'Không xóa được file');
        if (typeof toast === 'function') toast('Đã xóa', 'success');
        loadDownloadedVideos(window._procFilesDir || '');
      } catch (error) {
        if (typeof toast === 'function') toast('Xóa thất bại: ' + error.message, 'error');
      }
    });
  });
}

async function loadDownloadedVideos(dir) {
  const list = document.getElementById('proc-downloaded-list');
  const crumb = document.getElementById('proc-files-breadcrumb');
  if (!list) return;
  if (dir !== undefined) window._procFilesDir = dir || '';
  const currentDir = window._procFilesDir || '';
  list.innerHTML = '<div class="empty-state text-xs p-4 text-center text-slate-400">Đang tải thư mục...</div>';
  try {
    const query = '/api/files?dir=' + encodeURIComponent(currentDir);
    const response = await fetch(query);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Không đọc được thư mục');

    if (crumb) {
      const parts = currentDir.split('/').filter(Boolean);
      let accumulated = '';
      crumb.innerHTML = `<button type="button" class="proc-file-crumb" data-dir="" style="border:0;background:none;padding:0;cursor:pointer;color:var(--accent);font-weight:600;display:inline-flex;align-items:center;gap:5px">${_processSvgIcon('folder')}<span>Downloaded</span></button>` + parts.map(part => {
        accumulated += (accumulated ? '/' : '') + part;
        return `<span style="color:var(--text-muted)">/</span><button type="button" class="proc-file-crumb" data-dir="${_escapeDownloadedText(accumulated)}" style="border:0;background:none;padding:0;cursor:pointer;color:var(--accent)">${_escapeDownloadedText(part)}</button>`;
      }).join('');
      crumb.querySelectorAll('.proc-file-crumb').forEach(button => button.addEventListener('click', () => loadDownloadedVideos(button.dataset.dir || '')));
    }

    _renderDownloadedItems(data);
  } catch (error) {
    list.innerHTML = `<div class="text-xs p-4" style="color:var(--danger)">Không tải được danh sách: ${_escapeDownloadedText(error.message)}</div>`;
  }
}
window.loadDownloadedVideos = loadDownloadedVideos;

async function loadStep3DownloadedVideos() {
  const list = document.getElementById('step3-downloaded-list');
  if (!list) return;
  list.innerHTML = '<div class="empty-state text-xs">Đang tải danh sách...</div>';
  try {
    const response = await fetch('/api/files/completed');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Không đọc được danh sách');
    const items = Array.isArray(data.items) ? data.items : [];
    window._step3DownloadedVideos = items;
    if (!items.length) {
      list.innerHTML = '<div class="empty-state text-xs">Chưa có video xử lý hoàn tất được ghi nhận.</div>';
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <div style="display:flex;align-items:center;gap:7px;padding:7px 8px;border:1px solid var(--border);border-radius:7px;background:var(--bg3)">
        <button type="button" onclick="previewStep3DownloadedVideo(${index})"
          style="min-width:0;flex:1;border:0;background:none;padding:0;text-align:left;cursor:pointer;color:var(--text)"
          title="${_escapeDownloadedText(item.abs_path || item.path)}">
          <div style="font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_processSvgIcon('video')} ${_escapeDownloadedText(item.name)}</div>
          <div style="font-size:9.5px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px">${_escapeDownloadedText(item.path)} · ${_escapeDownloadedText(item.size_str || '')}</div>
        </button>
        <button type="button" class="btn btn-secondary btn-sm" style="height:26px;padding:2px 7px;font-size:10px"
          onclick="deleteStep3DownloadedVideo(${index})" title="Xóa video">${_processSvgIcon('trash')}</button>
      </div>`).join('');
  } catch (error) {
    list.innerHTML = `<div class="text-xs" style="color:var(--danger)">Không tải được: ${_escapeDownloadedText(error.message)}</div>`;
  }
}
window.loadStep3DownloadedVideos = loadStep3DownloadedVideos;

function previewStep3DownloadedVideo(index) {
  const item = (window._step3DownloadedVideos || [])[index];
  if (item) openDownloadedPreviewModal(item);
}
window.previewStep3DownloadedVideo = previewStep3DownloadedVideo;

async function deleteStep3DownloadedVideo(index) {
  const item = (window._step3DownloadedVideos || [])[index];
  const targetPath = item?.path || item?.abs_path;
  if (!item || !targetPath || !confirm(`Xóa video "${item.name}"?`)) return;
  try {
    const response = await fetch('/api/files/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: targetPath })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Không xóa được video');
    if (typeof toast === 'function') toast('Đã xóa video', 'success');
    await loadStep3DownloadedVideos();
    if (typeof loadDownloadedVideos === 'function') loadDownloadedVideos(window._procFilesDir || '');
  } catch (error) {
    if (typeof toast === 'function') toast('Xóa thất bại: ' + error.message, 'error');
  }
}
window.deleteStep3DownloadedVideo = deleteStep3DownloadedVideo;

// Global click handler to close open dropdown menus when clicking outside
document.addEventListener('click', e => {
  if (!e.target.closest('.proc-dropdown-wrapper, .proc-dropdown-menu')) {
    document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
  }
});
window.addEventListener('scroll', () => {
  document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
}, { passive: true });
window.addEventListener('resize', () => {
  document.querySelectorAll('.proc-dropdown-menu').forEach(m => m.style.display = 'none');
}, { passive: true });

function addHistoryUrlToQueue(url) {
  if (!url) return;
  const urlEl = document.getElementById('proc-url');
  if (urlEl) urlEl.value = url;
  if (Array.isArray(window._batchQueue) && typeof buildNewTask === 'function') {
    const exists = window._batchQueue.some(item => item?.val === url);
    if (!exists) window._batchQueue.push(buildNewTask('url', url));
    if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
    if (typeof _step1UpdateDownloadArea === 'function') _step1UpdateDownloadArea();
  }
  if (typeof toast === 'function') toast('Đã lấy URL từ lịch sử vào hàng chờ', 'success');
}
window.addHistoryUrlToQueue = addHistoryUrlToQueue;

async function loadProcessDownloadHistory() {
  const list = document.getElementById('proc-download-history');
  const count = document.getElementById('proc-history-count');
  if (!list) return;
  list.innerHTML = '<div class="text-xs text-muted">Đang tải lịch sử...</div>';
  try {
    const response = await fetch('/api/history');
    const data = await response.json();
    if (!response.ok || !Array.isArray(data)) throw new Error(data.error || 'Không đọc được lịch sử');
    if (count) count.textContent = `${data.length} mục gần nhất`;
    if (!data.length) {
      list.innerHTML = '<div class="empty-state text-xs">Chưa có lịch sử tải xuống.</div>';
      return;
    }
    list.innerHTML = data.map(item => {
      let displayUrl = item.url || '';
      try { displayUrl = decodeURIComponent(displayUrl); } catch (_) {}
      const safeDisplayUrl = _escapeDownloadedText(displayUrl);
      const rawUrl = _escapeDownloadedText(item.url || '');
      return `<div style="display:flex;align-items:center;gap:8px;padding:8px;border:1px solid var(--border);border-radius:7px">
        <div style="min-width:0;flex:1">
          <div class="text-xs text-muted">${_escapeDownloadedText(item.time)} · ${_escapeDownloadedText(item.type)} · ${_escapeDownloadedText(item.success)}/${_escapeDownloadedText(item.total)}</div>
          <div class="text-sm" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${safeDisplayUrl}">${safeDisplayUrl}</div>
        </div>
        <button type="button" class="btn btn-secondary btn-sm proc-use-history">＋ Hàng chờ</button>
      </div>`;
    }).join('');
    list.querySelectorAll('.proc-use-history').forEach((button, index) => {
      button.addEventListener('click', () => addHistoryUrlToQueue(data[index].url));
    });
  } catch (error) {
    if (count) count.textContent = '';
    list.innerHTML = `<div class="text-xs" style="color:var(--danger)">Không tải được lịch sử: ${_escapeDownloadedText(error.message)}</div>`;
  }
}
window.loadProcessDownloadHistory = loadProcessDownloadHistory;

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
  if (kind === 'transcribe') {
    return document.getElementById('proc-transcribe-provider-model')?.value || 'antigravity';
  }
  return document.getElementById('proc-translation-provider')?.value || 'antigravity';
}

function _getProcessModel(kind) {
  if (kind === 'transcribe') {
    return document.getElementById('proc-model')?.value || '';
  }
  return document.getElementById('proc-trans-provider-model')?.value || '';
}

function startProcessVideo() {
  window._procPublishFrameTitle = '';
  window._pPubAIResult = null;
  window._pPubSourceKey = '';
  let videoPath = document.getElementById('proc-video')?.value?.trim();
  let videoUrl = document.getElementById('proc-url')?.value?.trim();
  let selectedFile = window._procSelectedFile || document.getElementById('proc-file')?.files?.[0] || null;

  // Sanitize: If videoUrl is actually a local file path, move it to videoPath
  if (videoUrl && !/^https?:\/\//i.test(videoUrl)) {
    if (!videoPath) videoPath = videoUrl;
    videoUrl = '';
    const uEl = document.getElementById('proc-url');
    if (uEl) uEl.value = '';
    const pEl = document.getElementById('proc-video');
    if (pEl) pEl.value = videoPath;
  }

  // Fallback: If inputs are empty but there are items in batchQueue, auto-populate from queue
  if (!videoPath && !videoUrl && !selectedFile) {
    const queueItem = (typeof window._resolveActiveQueueItem === 'function')
      ? window._resolveActiveQueueItem()
      : (window._batchQueue || []).find(t => t.status !== 'done' && t.status !== 'error') || (window._batchQueue || [])[0];
    if (queueItem && queueItem.val) {
      const isHttp = /^https?:\/\//i.test(queueItem.val);
      if (isHttp) {
        const uEl = document.getElementById('proc-url');
        if (uEl) uEl.value = queueItem.val;
        videoUrl = queueItem.val;
      } else {
        const pEl = document.getElementById('proc-video');
        if (pEl) pEl.value = queueItem.val;
        videoPath = queueItem.val;
      }
      if (!window._procCurrentTaskId) {
        window._procCurrentTaskId = queueItem.id;
      }
      queueItem.status = 'processing';
      if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
    }
  }

  if (!videoPath && !videoUrl && !selectedFile) {
    alert('Vui lòng nhập đường dẫn file video hoặc URL video');
    // Notify batch queue so _procRunning resets and queue can continue
    if (typeof window._onProcTaskFinished === 'function') {
      window._onProcTaskFinished(false);
    }
    return;
  }
  // Freeze Step 2 for this video before asynchronous provider/publishing checks.
  // Edits made while it runs remain in the form and are read for the next video.
  const thisVideoConfig = JSON.parse(JSON.stringify(collectProcessConfig(videoPath, videoUrl)));

  // Preflight: nếu user bật tự-động-đăng, check trạng thái các nền tảng trước khi
  // bắt đầu pipeline xử lý dài. Người dùng có thể tắt nền tảng lỗi hoặc hủy.
  (async () => {
    // Reset log box & ghi log bắt đầu
    const logBox = document.getElementById('proc-log');
    if (logBox) logBox.innerHTML = '';
    const logBox3 = document.getElementById('step3-log');
    if (logBox3) logBox3.innerHTML = '';
    if (typeof _appendProcLog === 'function') {
      _appendProcLog(' Khởi động tiến trình xử lý...', 'info');
    }

    if (window._procUploadPromise) {
      try {
        if (typeof _appendProcLog === 'function') {
          _appendProcLog(' Đang chờ hoàn tất upload file import...', 'info');
        }
        await window._procUploadPromise;
      } catch (e) {
        toast('Upload file import chưa hoàn tất: ' + (e.message || e), 'error');
        if (typeof _appendProcLog === 'function') {
          _appendProcLog(' File import tải lên thất bại.', 'error');
        }
        if (typeof window._onProcTaskFinished === 'function') {
          window._onProcTaskFinished(false);
        }
        return;
      }
    }

    // --- PRE-FLIGHT API CHECKS ---
    try {
      const providersToCheck = [];

      // AI translation and transcription resolve active Provider Connections on
      // the server. Legacy key checks here can reject a working connection.
      // Only TTS engines that still use the legacy config key need preflight.
      const voiceConvert = _isProcVoiceConvertEnabled();
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
        if (typeof _appendProcLog === 'function') {
          _appendProcLog(' Đang kiểm tra trạng thái các API key cần thiết...', 'info');
        }
        for (const provider of uniqueProviders) {
          if (typeof _appendProcLog === 'function') {
            _appendProcLog(` Đang xác minh API key cho: ${provider}...`, 'info');
          }
          const key = getApiKeyForProvider(provider);
          await new Promise((resolve, reject) => {
            checkApiBeforeAction(provider, key, resolve, () => reject(new Error(`Hủy bỏ hoặc xác minh API ${provider} thất bại.`)));
          });
          if (typeof _appendProcLog === 'function') {
            _appendProcLog(` API key cho: ${provider} hoạt động tốt.`, 'success');
          }
        }
      }
    } catch (err) {
      console.warn('API Preflight check failed:', err);
      if (typeof _appendProcLog === 'function') {
        _appendProcLog(` Tiến trình bị hủy hoặc lỗi preflight check: ${err.message || err}`, 'error');
      }
      // Reset task status in queue to pending so user can fix and retry
      if (window._procCurrentTaskId) {
        const t = (window._batchQueue || []).find(x => x.id === window._procCurrentTaskId);
        if (t) t.status = 'pending';
      }
      window._procCurrentTaskId = null;
      window._procRunning = false;
      if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
      if (typeof _step3RefreshStartCard === 'function') _step3RefreshStartCard();
      return; // Do not proceed to process video
    }
    // --- END OF PRE-FLIGHT API CHECKS ---

    if (typeof window.pPubPreflightCheck === 'function'
        && _procIsAutoPublishEnabled()) {
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
    let latestVideoPath = videoPath || document.getElementById('proc-video')?.value?.trim() || '';
    let latestVideoUrl = videoUrl || (!latestVideoPath ? document.getElementById('proc-url')?.value?.trim() : '') || '';
    if (latestVideoUrl && !/^https?:\/\//i.test(latestVideoUrl)) {
      if (!latestVideoPath) latestVideoPath = latestVideoUrl;
      latestVideoUrl = '';
    }
    const latestSelectedFile = window._procSelectedFile || document.getElementById('proc-file')?.files?.[0] || null;
    _startProcessVideoInternal(latestVideoPath, latestVideoUrl, latestSelectedFile, thisVideoConfig);
  })();
}

function collectProcessConfig(videoPath = "", videoUrl = "") {
  const originalAudioVolume = Math.min(2, Math.max(0, parseFloat(document.getElementById('proc-vol-orig')?.value ?? '100') / 100));
  return {
    video_path:       videoPath,
    video_url:        videoUrl || '',
    out_dir:          document.getElementById('proc-out')?.value?.trim() || '',
    model:            _getProcessModel('transcribe') || document.getElementById('proc-model')?.value || 'base',
    language:         document.getElementById('proc-lang')?.value || 'zh',
    target_language:  document.getElementById('proc-target-lang')?.value || 'vi',
    transcribe_provider: _getProcessProvider('transcribe'),
    transcribe_model:    _getProcessModel('transcribe'),
    translate_provider:  _getProcessProvider('translate'),
    translate_model:     _getProcessModel('translate'),
    skip_ass_review:  (document.getElementById('step3-skip-ass')?.checked || window._procSkipReviewSession) ?? false,
    skip_ass:         document.getElementById('step3-skip-ass')?.checked ?? false,
    burn_subs:        (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-burn')?.checked ?? true),
    blur_original:    document.getElementById('proc-blur-original')?.checked ?? true,
    blur_by_subtitles: document.getElementById('proc-blur-by-subtitles')?.checked ?? false,
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
    translate_subs:   (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : _isProcTranslateSubsEnabled(),
    burn_vi_subs:     (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : (document.getElementById('proc-burn-vi')?.checked ?? true),
    voice_convert:    (document.getElementById('proc-skip-transcription')?.checked ?? false) ? false : _isProcVoiceConvertEnabled(),
    ..._resolveTtsEngineVoice('proc'),
    tts_pitch:        _sanitizeVoiceParam(document.getElementById('proc-tts-pitch')?.value || '+0Hz'),
    tts_rate:         _sanitizeVoiceParam(document.getElementById('proc-tts-rate')?.value || '+0%'),
    tts_emotion:      document.getElementById('proc-tts-emotion')?.value || 'default',
    // The Step 2 Voice slider is the single source of truth: any value above
    // zero means the original track must be mixed back into the TTS output.
    keep_bg_music:    originalAudioVolume > 0,
    bg_volume:        originalAudioVolume,
    ext_audio_enabled: document.getElementById('proc-ext-audio-enabled')?.checked ?? false,
    vol_orig:          originalAudioVolume,
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
    subtitle_width_pct: Math.max(40, Math.min(98, parseFloat(document.getElementById('proc-sub-width')?.value || '90'))),
    margin_v:         (() => {
      // UI value is % of video height. Convert to px for FFmpeg (reference: 720px height).
      const pct = parseFloat(document.getElementById('proc-margin-v')?.value || '3');
      return Math.max(0, Math.round(720 * pct / 100));
    })(),
    outline_width:    parseInt(document.getElementById('proc-outline-width')?.value || '2', 10),
    font_bold:        document.getElementById('proc-font-bold')?.checked ?? true,
    tts_speed:        parseFloat(document.getElementById('proc-tts-speed')?.value || '1.0'),
    auto_speed:       document.getElementById('proc-auto-speed')?.checked ?? true,
    sync_sub_to_voice: document.getElementById('proc-sync-sub-voice')?.checked ?? false,
    multi_speaker:     document.getElementById('proc-multi-speaker')?.checked ?? false,
    tts_voice_male:    document.getElementById('proc-tts-voice-male')?.value || '',
    tts_voice_female:  document.getElementById('proc-tts-voice-female')?.value || '',
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
    content_aspect: document.getElementById('proc-content-aspect')?.value || 'auto',
    content_aspect_mode: document.getElementById('proc-content-aspect-mode')?.value || 'pad',
    mask_config: {mode: document.getElementById('proc-mask-mode')?.value || 'blur', source_x: Number(document.getElementById('proc-mask-source-x')?.value ?? 50)/100, source_y: Number(document.getElementById('proc-mask-source-y')?.value ?? 75)/100},
    target_aspect: document.getElementById('proc-preview-aspect')?.value || 'auto',
    output_fps: Number(document.getElementById('proc-output-fps')?.value || 0),
    encode_device: document.getElementById('proc-encode-device')?.value || 'auto',
    // Lấp viền khi đổi khung bằng nền mờ (blur) thay vì viền đen.
    aspect_pad_blur: document.getElementById('proc-aspect-blur-bg')?.checked ?? false,
    // Frame video (step 6)
    frame_enabled:        document.getElementById('frame-enabled')?.checked ?? false,
    frame_title:          document.getElementById('frame-title')?.value === document.getElementById('frame-title')?.dataset?.aiTitle ? '' : (document.getElementById('frame-title')?.value || ''),
    frame_title_auto:     !document.getElementById('frame-title')?.value?.trim() || document.getElementById('frame-title')?.value === document.getElementById('frame-title')?.dataset?.aiTitle,
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
    frame_blur_w_pct:     parseFloat(document.getElementById('frame-blur-w')?.value || 0),
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
    frame_logo_start_sec: (() => { const v = document.getElementById('frame-logo-start')?.value; return v === '' || v == null ? null : Number(v); })(),
    frame_logo_end_sec: (() => { const v = document.getElementById('frame-logo-end')?.value; return v === '' || v == null ? null : Number(v); })(),
    video_overlays:       (typeof window._collectVideoOverlays === 'function') ? window._collectVideoOverlays() : [],
    ai_video_analysis:    (window._procUseAiAnalysis && window._procVideoAiAnalysis?.video_path === videoPath && window._procVideoAiAnalysis?.result) ? window._procVideoAiAnalysis.result : null,
    ai_video_analysis_text: (window._procUseAiAnalysis && window._procVideoAiAnalysis?.video_path === videoPath && window._procVideoAiAnalysis?.analysis_text) ? window._procVideoAiAnalysis.analysis_text : '',
    // Thumbnail flow disabled by request.
    thumb_enabled:        false,
    thumb_mode:           'none',
    thumb_path:           '',
    thumb_title:          '',
    thumb_duration:       0,
  };

}
window.collectProcessConfig = collectProcessConfig;

function _startProcessVideoInternal(videoPath, videoUrl, selectedFile, configSnapshot) {
  window._publishLastOutputPath = '';
  window._publishLastSubtitlePath = '';
  window._procReusePrepared = null;

  const btn = document.getElementById('btn-proc');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang xử lý...'; }

  // Reset UI (logBox is already cleared in startProcessVideo)
  _setProcProgress(0, 'Khởi chạy...');
  if (typeof _appendProcLog === 'function') {
    _appendProcLog(' Đang gửi request xử lý video tới server backend...', 'info');
  }

  const baseFields = configSnapshot || collectProcessConfig(videoPath, videoUrl);
  baseFields.video_path = videoPath;
  baseFields.video_url = videoUrl || '';

  // Keep an inspectable snapshot of the exact Step 2 values used by this run.
  window._procLastSubmittedConfig = JSON.parse(JSON.stringify(baseFields));
  _appendProcLog(` Cấu hình âm thanh: âm gốc ${Math.round((baseFields.vol_orig || 0) * 100)}% · giữ nền ${baseFields.keep_bg_music ? 'Bật' : 'Tắt'} · âm ngoài ${baseFields.ext_audio_enabled ? `Bật (${baseFields.ext_audios.length} tệp)` : 'Tắt'}`, 'info');

  window._procAbortController = new AbortController();
  window._procCancelled = false;
  window._procCurrentCancelled = false;
  const doRequest = (body, isFormData) => fetch('/api/process_video', {
    method: 'POST',
    headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    body,
    signal: window._procAbortController.signal,
  }).then(res => {
    if (!res.ok) {
      return res.text().then(text => {
        let msg = `Lỗi HTTP ${res.status}: ${res.statusText}`;
        try {
          const j = JSON.parse(text);
          if (j.error || j.message) msg += ` - ${j.error || j.message}`;
        } catch(_) {
          if (text) msg += ` - ${text.slice(0, 200)}`;
        }
        _appendProcLog(msg, 'error');
        _setProcProgress(0, 'Lỗi máy chủ');
        if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
        if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
        throw new Error(msg);
      });
    }
    const reader = res.body.getReader();
    window._procReader = reader;
    const decoder = new TextDecoder();
    let streamBuffer = '';
    let processingFailed = false;

    // Show pause button
    if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(true);

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) {
          if (streamBuffer.trim()) {
            try {
              const d = JSON.parse(streamBuffer.trim());
              if (d.log) _appendProcLog(d.log, d.level || 'info');
              if (d.overall !== undefined) _setProcProgress(d.overall, d.overall_lbl || '');
              if (d.failed) processingFailed = true;
            } catch (_) {}
            streamBuffer = '';
          }
          if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
          if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
          const doneActions = document.getElementById('proc-done-actions');
          if (doneActions) doneActions.style.display = processingFailed ? 'none' : 'block';

          // Frame video now runs inside the pipeline (step 6) — no need to trigger separately
          _setProcProgress(processingFailed ? 0 : 100, processingFailed ? 'Xử lý thất bại' : 'Hoàn thành!');

          if (processingFailed) {
            window._procRunning = false;
            if (typeof window._onProcTaskFinished === 'function') {
              window._onProcTaskFinished(false);
            }
            return;
          }

          // ── Auto-publish after processing ──
          const shouldAutoPublish = _procIsAutoPublishEnabled();
          if (shouldAutoPublish) {
            if (typeof procWizGo === 'function') procWizGo(4);
          }

          const autoPubPromise = (typeof pPubAutoUploadAll === 'function'
              && shouldAutoPublish
              && window._publishLastOutputPath)
            ? procGenerateCurrentMetadata().then(info => {
                if (!info) throw new Error('Chưa tạo được thông tin đăng từ ASS');
                return pPubAutoUploadAll(window._publishLastOutputPath);
              }).catch(error => _appendProcLog('Chưa đăng video: ' + error.message, 'error'))
            : Promise.resolve();

          // Legacy auto-upload path (different checkbox id)
          if (window._publishLastOutputPath
              && document.getElementById('publish-auto-upload')?.checked
              && !shouldAutoPublish) {
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
        streamBuffer += decoder.decode(value, { stream: true });
        const lines = streamBuffer.split('\n');
        streamBuffer = lines.pop(); // preserve incomplete trailing chunk
        lines.filter(l => l.trim()).forEach(line => {
          try {
            const d = JSON.parse(line);
            if (d.heartbeat) return;
            if (d.cancelled) {
              processingFailed = true;
              window._procCancelled = true;
            }
            if (d.failed) processingFailed = true;
            if (d.log) {
              _appendProcLog(d.log, d.level || 'info');
              if (d.log.includes('Phiên âm đoạn') && d.log.includes('thất bại') || d.log.includes('Antigravity STT thất bại') || d.log.includes('Chưa cấu hình khóa kết nối') || d.log.includes('hết hạn')) {
                if (typeof _showSttKeyModal === 'function') {
                  _showSttKeyModal(d.log);
                }
              }
              if (d.level === 'error') {
                window._procRunning = false;
                const btn = document.getElementById('btn-proc');
                if (btn) { btn.disabled = false; btn.textContent = ' Bắt đầu xử lý (Thử lại)'; }
                const btn3 = document.getElementById('btn-start-proc');
                if (btn3) { btn3.disabled = false; btn3.textContent = '▶ Thử lại xử lý'; }
              }
              if (d.log.includes('File cuối cùng:') || d.log.includes('final_output_path')) {
                const match = d.log.match(/[:\s]([^\s]+\.mp4)/);
                if (match) {
                  window._publishLastOutputPath = match[1];
                  window._ytLastOutputPath = match[1];
                }
              }
            }
            if (d.frame_title) window._procPublishFrameTitle = d.frame_title;
            if (d.frame_title && document.getElementById('frame-title-enabled')?.checked) {
              const input = document.getElementById('frame-title');
              if (input && (!input.value.trim() || input.value === input.dataset.aiTitle)) {
                if (input.value === input.dataset.aiTitle) input.value = "";
                input.dataset.aiTitle = d.frame_title;
                input.dataset.aiVideoPath = videoPath;
                if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
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
      }).catch(err => {
        if (err.name === 'AbortError' || window._procCancelled || window._procCurrentCancelled) {
          _appendProcLog('⛔ Tiến trình xử lý đã bị dừng/hủy.', 'warning');
          _setProcProgress(0, 'Đã hủy');
        } else {
          _appendProcLog('Lỗi kết nối: ' + err, 'error');
        }
        window._procRunning = false;
        if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
        if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
        if (typeof _step3RefreshStartCard === 'function') _step3RefreshStartCard();
        if (typeof window._onProcTaskFinished === 'function') {
          window._onProcTaskFinished(false);
        }
      });
    }
    read();
  }).catch(err => {
    if (err.name === 'AbortError' || window._procCancelled || window._procCurrentCancelled) {
      _appendProcLog('⛔ Tiến trình xử lý đã bị dừng/hủy.', 'warning');
      _setProcProgress(0, 'Đã hủy');
    } else {
      _appendProcLog('Lỗi kết nối: ' + err, 'error');
    }
    window._procRunning = false;
    if (btn) { btn.disabled = false; btn.textContent = 'Xử lý Video'; }
    if (typeof _procShowPauseBtn === 'function') _procShowPauseBtn(false);
    if (typeof _step3RefreshStartCard === 'function') _step3RefreshStartCard();
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
  // Navigate to wizard step 4 (Đăng tự động — embedded in process wizard)
  if (typeof procWizGo === 'function') {
    procWizGo(4);
    toast(' Video xử lý xong — hãy cấu hình đăng ở bước 4', 'success');
  } else {
    // Fallback: switch to publish page
    sendToPublish(window._publishLastOutputPath);
  }
}

/**
 * Reuses the frame title or analyzes ASS when needed, then opens publishing.
 */
async function _procImportAndAICaption() {
  if (!window._publishLastOutputPath) {
    toast('Không tìm thấy video vừa xử lý', 'warning');
    return;
  }

  const btn = event?.currentTarget;
  if (btn) { btn.disabled = true; btn.textContent = ' Đang tạo thông tin đăng...'; }

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

    // Reuse the frame title; call AI only when no title was generated.
    const hasVideoAi = !!(window._procUseAiAnalysis && window._procVideoAiAnalysis?.result);
    if ((assContent || hasVideoAi) && typeof pPubAnalyzeFromAss === 'function') {
      await pPubAnalyzeFromAss(assContent);
    } else {
      _appendProcLog(' Không có ASS hoặc phân tích video để AI phân tích — chuyển sang bước 4 để nhập thủ công', 'warning');
    }
  } catch (e) {
    _appendProcLog(' AI caption thất bại: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = ' Tạo thông tin → Đăng (Bước 4)'; }
  }

  // Navigate to step 4
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

    toast(' Đã thêm dữ liệu vào Đăng video', 'success');
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
        toast(' Đã tự động tìm thấy phụ đề: ' + data.best_match.split(/[\\\/]/).pop(), 'success');
      }
    }
  } catch (e) {
    console.error('Lỗi tự động tìm phụ đề:', e);
  }
}

const _procStageNames = {
  1: 'Chuẩn bị video',
  2: 'Nhận diện lời nói',
  3: 'Dịch và tạo phụ đề',
  4: 'Chỉnh sửa hình ảnh',
  5: 'Tạo và ghép giọng đọc'
};
function _formatProcLogMessage(message) {
  let result = String(message ?? '').replace(/[\u{1F300}-\u{1FAFF}\u2300-\u23FF\u2600-\u27BF\uFE0F\u200D]/gu, '').trim();
  const match = result.match(/^\[Bước ([1-5])\/5\]\s*/);
  if (match) {
    const stage = Number(match[1]);
    result = `Giai đoạn ${stage}/5 · ${_procStageNames[stage]} — ${result.slice(match[0].length)}`;
    const active = document.getElementById('step3-active-stage');
    if (active) active.textContent = `${stage}/5 · ${_procStageNames[stage]}`;
    document.querySelectorAll('[data-proc-log-stage]').forEach(el => {
      const n = Number(el.dataset.procLogStage);
      el.classList.toggle('proc-log-stage-active', n === stage);
      el.classList.toggle('proc-log-stage-done', n < stage);
    });
  }
  return result.replace(/\bASS\b/g, 'tệp phụ đề ASS')
    .replace(/\bburn\b/gi, 'ghi vào video')
    .replace(/\bTTS\b/g, 'giọng đọc')
    .replace(/\bbatch\b/gi, 'lượt')
    .replace(/\boutput\b/gi, 'đầu ra');
}
function _appendProcLog(msg, level) {
  msg = _formatProcLogMessage(msg);
  const box = document.getElementById('proc-log');
  const box3 = document.getElementById('step3-log');
  if (!box && !box3) return;

  const now = new Date();
  const ts = now.toTimeString().slice(0, 8); // HH:MM:SS
  const text = `[${ts}] ${msg}`;

  if (box) {
    const div = document.createElement('div');
    div.className = 'log-line log-' + (level || 'info');
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  if (box3) {
    const div3 = document.createElement('div');
    div3.className = 'log-line log-' + (level || 'info');
    div3.textContent = text;
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

  // Mirror progress to step 3 mini bar & status label
  const bar3  = document.getElementById('pb-step3-overall');
  const pct3  = document.getElementById('pb-step3-pct');
  const statusEl = document.getElementById('step3-log-status');
  if (bar3)  bar3.style.width = pct + '%';
  if (pct3)  pct3.textContent = pct + '%';
  if (statusEl && label) statusEl.textContent = label;
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

function _sanitizeVoiceParam(val) {
  if (!val) return '+0%';
  val = String(val).trim();
  // Ensure starts with + or -
  if (!val.startsWith('+') && !val.startsWith('-')) {
    val = '+' + val;
  }
  // Fallback to % if no unit
  if (!val.endsWith('%') && !val.endsWith('Hz')) {
    val += '%';
  }
  return val;
}

async function previewProcessVoice() {
  const text = 'Xin chào, đây là phần nghe thử giọng đọc từ cấu hình xử lý video.';
  const btn = event?.currentTarget;
  const audio = document.getElementById('proc-preview-audio');
  if (!btn) return;

  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '...';

  try {
    const res = await fetch('/api/tts_preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        tts_engine: document.getElementById('proc-tts-engine')?.value || 'edge-tts',
        tts_voice: document.getElementById('proc-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
        tts_pitch: _sanitizeVoiceParam(document.getElementById('proc-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('proc-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('proc-tts-emotion')?.value || 'default',
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Lỗi preview');
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (audio) {
      audio.src = url;
      audio.style.display = 'inline-block';
      const p = audio.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    }
  } catch (err) {
    alert('Lỗi preview giọng: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}
window.previewProcessVoice = previewProcessVoice;

function _showSttKeyModal(errorMsg) {
  let modal = document.getElementById('stt-key-modal');
  if (modal) {
    modal.remove();
  }

  const currentProv = (typeof _getProcessProvider === 'function' ? _getProcessProvider('transcribe') : '') || 'antigravity';
  const isAntigravity = currentProv === 'antigravity';
  const isGemini = currentProv === 'gemini';

  modal = document.createElement('div');
  modal.id = 'stt-key-modal';
  modal.className = 'modal-backdrop';
  modal.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.6);z-index:99999;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box';

  let title = 'Cập nhật kết nối phiên âm (STT)';
  let desc = 'Kết nối phiên âm gặp sự cố. Bạn có thể kiểm tra cấu hình hoặc nhấn Bỏ qua để tiếp tục xử lý.';
  let inputHtml = '';

  if (isAntigravity) {
    title = 'Phiên âm Antigravity chưa hoàn thành';
    desc = 'Yêu cầu phiên âm âm thanh chưa trả về phụ đề hợp lệ. Hãy xem lỗi chi tiết bên dưới, rồi thử lại hoặc kiểm tra kết nối trong Cấu hình.';
  } else if (isGemini) {
    title = 'Cập nhật Google Gemini API Key';
    desc = 'Kết nối Google Gemini gặp sự cố. Bạn có thể nhập Gemini API Key mới (dạng AIzaSy...) hoặc mở Cấu hình.';
    inputHtml = `
      <div style="margin-bottom:16px">
        <label style="display:block;font-size:12px;font-weight:600;color:#334155;margin-bottom:4px">Nhập Gemini API Key mới (dạng AIzaSy...):</label>
        <input type="text" id="stt-modal-key-input" placeholder="AIzaSy..." style="width:100%;height:38px;padding:6px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;box-sizing:border-box">
      </div>
    `;
  } else {
    title = 'Cập nhật API Key phiên âm';
    desc = 'Khóa API phiên âm gặp sự cố. Bạn có thể nhập API Key mới hoặc mở Cấu hình để cập nhật.';
    inputHtml = `
      <div style="margin-bottom:16px">
        <label style="display:block;font-size:12px;font-weight:600;color:#334155;margin-bottom:4px">Nhập API Key mới:</label>
        <input type="text" id="stt-modal-key-input" placeholder="Nhập API Key..." style="width:100%;height:38px;padding:6px 12px;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;box-sizing:border-box">
      </div>
    `;
  }

  modal.innerHTML = `
    <div style="background:#fff;border-radius:12px;max-width:480px;width:100%;padding:20px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.3);font-family:inherit;box-sizing:border-box">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <h3 style="margin:0;font-size:17px;font-weight:700;color:#1e293b">${title}</h3>
      </div>
      <p style="font-size:13px;color:#64748b;margin:0 0 12px;line-height:1.5">
        ${desc}
      </p>
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:8px 12px;font-size:12px;color:#991b1b;margin-bottom:12px" id="stt-modal-err"></div>
      ${inputHtml}
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button type="button" class="btn btn-secondary" onclick="_closeSttKeyModal()" style="font-size:13px">Bỏ qua</button>
        <button type="button" class="btn btn-secondary" onclick="window.location.href='/config'" style="font-size:13px">Cấu hình</button>
        ${!isAntigravity ? '<button type="button" class="btn btn-primary" onclick="_saveSttKeyModal()" style="font-size:13px;font-weight:600">Lưu Key & Thử lại</button>' : ''}
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const errEl = document.getElementById('stt-modal-err');
  if (errEl) errEl.textContent = errorMsg || 'Lỗi kết nối phiên âm.';
  modal.style.display = 'flex';
}

function _closeSttKeyModal() {
  const modal = document.getElementById('stt-key-modal');
  if (modal) modal.style.display = 'none';
}

async function _saveSttKeyModal() {
  const input = document.getElementById('stt-modal-key-input');
  const key = input ? input.value.trim() : '';
  if (!key) {
    alert('Vui lòng nhập API Key trước khi lưu!');
    return;
  }
  try {
    const res = await fetch('/api/update_antigravity_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: key })
    }).then(r => r.json());

    if (res.ok) {
      alert('Đã cập nhật API Key thành công! Bạn có thể bấm xử lý lại.');
      _closeSttKeyModal();
    } else {
      alert('Lỗi: ' + (res.error || 'Không thể lưu key'));
    }
  } catch (err) {
    alert('Lỗi kết nối: ' + err.message);
  }
}

window._showSttKeyModal = _showSttKeyModal;
window._closeSttKeyModal = _closeSttKeyModal;
window._saveSttKeyModal = _saveSttKeyModal;



async function procLoadReusableVideos() {
  const select = document.getElementById('proc-reuse-video');
  if (!select || window._procReuseLoading) return;
  window._procReuseLoading = true;
  const previous = select.value;
  try {
    const response = await fetch('/api/files/completed');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Không tải được video');
    window._procReusableVideos = data.items || [];
    select.replaceChildren(new Option('Chọn video...', ''));
    window._procReusableVideos.forEach(item => select.add(new Option(item.name, item.abs_path)));
    select.value = previous;
  } catch (error) {
    document.getElementById('proc-reuse-status').textContent = error.message;
  } finally { window._procReuseLoading = false; }
}
function procSelectReusableVideo() {
  const path = document.getElementById('proc-reuse-video').value;
  const item = (window._procReusableVideos || []).find(row => row.abs_path === path);
  const select = document.getElementById('proc-reuse-ass');
  select.replaceChildren(new Option('Chọn phụ đề của video...', ''));
  (item?.subtitles || []).forEach(path => select.add(new Option(path.split(/[\\/]/).pop(), path)));
  select.value = item?.subtitle_path || '';
  window._procReusePrepared = null;
  document.getElementById('proc-reuse-status').textContent = item ? 'Chọn ASS, sau đó tạo thông tin.' : '';
  if (select.value && document.getElementById('p-autopub-enabled')?.checked) procPrepareReusableVideo();
}
async function procGenerateCurrentMetadata(options = {}) {
  if (!document.getElementById('p-autopub-enabled')?.checked) return null;
  const path = window._publishLastSubtitlePath;
  if (!path) return await pPubAnalyzeFromAss('', options);
  const response = await fetch('/api/proc_read_ass', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path})
  });
  const data = await response.json();
  if (!response.ok || !data.content) throw new Error(data.error || 'Không đọc được ASS');
  return await pPubAnalyzeFromAss(data.content, options);
}
async function procPrepareReusableVideo() {
  const video = document.getElementById('proc-reuse-video').value;
  const ass = document.getElementById('proc-reuse-ass').value;
  const status = document.getElementById('proc-reuse-status');
  const button = document.getElementById('proc-reuse-prepare');
  if (button.disabled) return;
  if (window._procRunning) { status.textContent = 'Chờ hàng xử lý hiện tại hoàn tất trước khi chọn video khác.'; return; }
  if (!video || !ass) { status.textContent = 'Hãy chọn video và ASS tương ứng.'; return; }
  button.disabled = true;
  document.getElementById('proc-reuse-video').disabled = true;
  document.getElementById('proc-reuse-ass').disabled = true;
  window._procReusePrepared = null;
  status.textContent = 'AI đang tạo thông tin từ ASS...';
  try {
    window._procPublishFrameTitle = '';
    window._pPubSourceKey = '';
    window._publishLastOutputPath = video;
    window._publishLastSubtitlePath = ass;
    document.getElementById('p-autopub-enabled').checked = true;
    const source = document.getElementById('step1-autopub-toggle');
    if (source) source.checked = true;
    // This action prepares metadata only. Publishing requires its own button.
    const result = await procGenerateCurrentMetadata({ignoreVideoAnalysis: true});
    if (!result) throw new Error('Chưa tạo được thông tin. Vui lòng thử lại.');
    window._procReusePrepared = {video, ass};
    status.textContent = 'Đã tạo thông tin. Kiểm tra nội dung và tài khoản trước khi đăng.';
  } catch (error) { status.textContent = error.message; }
  finally {
    button.disabled = false;
    document.getElementById('proc-reuse-video').disabled = false;
    document.getElementById('proc-reuse-ass').disabled = false;
  }
}
async function procPublishReusableVideo() {
  const video = document.getElementById('proc-reuse-video').value;
  const ass = document.getElementById('proc-reuse-ass').value;
  const status = document.getElementById('proc-reuse-status');
  if (window._procReusePrepared?.video !== video || window._procReusePrepared?.ass !== ass) {
    status.textContent = 'Tạo thông tin từ ASS cho video đã chọn trước khi đăng.'; return;
  }
  if (window._procReusePublishing) return;
  window._procReusePublishing = true;
  try { await pPubAutoUploadAll(video); }
  catch (error) { status.textContent = error.message; }
  finally { window._procReusePublishing = false; }
}

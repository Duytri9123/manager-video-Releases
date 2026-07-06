async function startTranscribe() {
  const folder = document.getElementById('tr-dir')?.value?.trim() || './Downloaded';
  const single = document.getElementById('tr-file')?.value?.trim() || '';
  const outDir = document.getElementById('tr-out')?.value?.trim() || '';
  const selectedFile = window._trSelectedFile || document.getElementById('tr-import-file')?.files?.[0] || null;
  if (!folder && !single && !selectedFile) {
    alert('Vui lòng nhập thư mục video hoặc file đơn.');
    return;
  }

  const provider = document.getElementById('tr-provider')?.value || 'groq';

  // --- PRE-FLIGHT API CHECK FOR TRANSCRIPTION ---
  if (provider === 'groq' && typeof checkApiBeforeAction === 'function') {
    const key = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider('groq') : '';
    let apiOk = false;
    await new Promise(resolve => checkApiBeforeAction('groq', key, () => { apiOk = true; resolve(); }, resolve));
    if (!apiOk) return; // Stop if cancel / invalid
  }
  // --- END OF PRE-FLIGHT API CHECK FOR TRANSCRIPTION ---

  const btn = document.getElementById('btn-tr');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang phiên âm...';
  }

  clearLog('tr-log');
  _setTrProgress(0, '--', 0, '--');

  const payload = {
    folder,
    // Khi user đã chọn file qua picker, bỏ qua giá trị "single" text input
    // (có thể chỉ là filename do trình duyệt không cho phép biết path thật).
    single: selectedFile ? '' : single,
    out_dir: outDir,
    provider,
    model: document.getElementById('tr-model')?.value || 'base',
    lang: document.getElementById('tr-lang')?.value || 'zh',
    srt: document.getElementById('tr-srt')?.checked ?? false,
    skip: document.getElementById('tr-skip')?.checked ?? true,
    sc: document.getElementById('tr-sc')?.checked ?? false,
  };

  const runRequest = (body, isFormData) => fetch('/api/transcribe', {
    method: 'POST',
    headers: isFormData ? {} : { 'Content-Type': 'application/json' },
    body,
  }).then(res => {
    if (!res.ok || !res.body) {
      throw new Error('Không thể bắt đầu phiên âm');
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) {
          if (buffer.trim()) _handleTrLine(buffer.trim());
          if (btn) {
            btn.disabled = false;
            btn.textContent = t('btn_start_tr');
          }
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        lines.forEach(line => {
          const trimmed = line.trim();
          if (trimmed) _handleTrLine(trimmed);
        });
        read();
      }).catch(err => {
        _appendTrLog('Lỗi đọc dữ liệu: ' + err, 'error');
        _handleTranscribeStreamError(err);
        if (btn) {
          btn.disabled = false;
          btn.textContent = t('btn_start_tr');
        }
      });
    }

    read();
  }).catch(err => {
    _appendTrLog('Lỗi kết nối: ' + err, 'error');
    _handleTranscribeStreamError(err);
    if (btn) {
      btn.disabled = false;
      btn.textContent = t('btn_start_tr');
    }
  });

  if (selectedFile) {
    const form = new FormData();
    form.append('video_file', selectedFile);
    Object.entries(payload).forEach(([key, value]) => form.append(key, String(value ?? '')));
    runRequest(form, true);
    return;
  }

  runRequest(JSON.stringify(payload), false);
}

async function extractAudioOnly() {
  const filePath = document.getElementById('tr-file')?.value?.trim() || '';
  const outDir   = document.getElementById('tr-out')?.value?.trim() || '';
  const selectedFile = window._trSelectedFile || document.getElementById('tr-import-file')?.files?.[0] || null;

  if (!filePath && !selectedFile) {
    alert('Vui lòng chọn file video trước.');
    return;
  }

  _appendTrLog('Đang tách MP3...', 'info');

  try {
    let res;
    if (selectedFile) {
      const form = new FormData();
      form.append('video_file', selectedFile);
      if (outDir) form.append('output_dir', outDir);
      res = await fetch('/api/extract_audio', { method: 'POST', body: form });
    } else {
      res = await fetch('/api/extract_audio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: filePath, output_dir: outDir }),
      });
    }
    const data = await res.json();
    if (data.ok) {
      _appendTrLog('✅ Tách MP3 thành công: ' + data.output_path, 'success');
      toast('Tách MP3 thành công', 'success');
    } else {
      _appendTrLog('❌ Lỗi: ' + (data.error || 'Unknown'), 'error');
    }
  } catch (err) {
    _appendTrLog('❌ Lỗi kết nối: ' + err, 'error');
  }
}

async function generateTtsFromAss() {
  const filePath = document.getElementById('tr-file')?.value?.trim() || '';
  const outDir   = document.getElementById('tr-out')?.value?.trim() || '';
  const selectedFile = window._trSelectedFile || document.getElementById('tr-import-file')?.files?.[0] || null;

  if (!filePath && !selectedFile) {
    alert('Vui lòng chọn file .ass trước.');
    return;
  }

  const btn = document.querySelector('[onclick="generateTtsFromAss()"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang tạo...'; }
  clearLog('tr-log');
  _setTrProgress(0, '--', 0, '--');

  const params = {
    output_dir:  outDir,
    ..._resolveTtsEngineVoice('tr'),
    tts_lang:    document.getElementById('tr-tts-lang')?.value || 'vi',
    language:    document.getElementById('tr-tts-lang')?.value || 'vi',
    tts_pitch:   _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value  || '+0Hz'),
    tts_rate:    _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value   || '+0%'),
    tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
    tts_persona: document.getElementById('tr-tts-persona')?.value || '',
    vieneu_ref_audio: document.getElementById('tr-tts-ref-audio')?.value || '',
    fx_enabled:  String(document.getElementById('tr-fx-enabled')?.checked || false),
    fx_pitch:    document.getElementById('tr-fx-pitch')?.value   || '1.5',
    fx_speed:    document.getElementById('tr-fx-speed')?.value   || '1.08',
    fx_bass:     document.getElementById('tr-fx-bass')?.value    || '-2',
    fx_mid:      document.getElementById('tr-fx-mid')?.value     || '2',
    fx_treble:   document.getElementById('tr-fx-treble')?.value  || '3',
    fx_comp:     document.getElementById('tr-fx-comp')?.value    || 'none',
    fx_reverb:   document.getElementById('tr-fx-reverb')?.value  || '0',
  };

  const restore = () => {
    if (btn) { btn.disabled = false; btn.textContent = 'Tạo MP3 từ file .ass'; }
  };

  try {
    let res;
    if (selectedFile) {
      const form = new FormData();
      form.append('ass_file', selectedFile);
      Object.entries(params).forEach(([k, v]) => form.append(k, v));
      res = await fetch('/api/tts_from_ass', { method: 'POST', body: form });
    } else {
      res = await fetch('/api/tts_from_ass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ass_path: filePath, ...params }),
      });
    }

    if (!res.ok || !res.body) throw new Error('Không thể kết nối server');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const read = async () => {
      while (true) {
        const { done, value } = await reader.read();
        if (done) { restore(); break; }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          try {
            const d = JSON.parse(trimmed);
            if (d.log) _appendTrLog(d.log, d.level || 'info');
            if (d.overall !== undefined) _setTrProgress(d.overall, d.overall_lbl || '--', 0, '--');
            if (d.ok === true) toast('Tạo MP3 thành công: ' + d.output_path, 'success');
            if (d.ok === false) toast('Lỗi: ' + (d.error || 'Unknown'), 'error');
          } catch (_) {
            _appendTrLog(trimmed, 'info');
          }
        }
      }
    };
    await read();
  } catch (err) {
    _appendTrLog('❌ Lỗi kết nối: ' + err, 'error');
    restore();
  }
}

function _handleTrLine(line) {
  try {
    const d = JSON.parse(line);
    if (d.log) _appendTrLog(d.log, d.level || 'info');
    if (d.level === 'error') {
      _handleTranscribeStreamError(d.log);
    }
    if (d.overall !== undefined || d.file !== undefined) {
      _setTrProgress(d.overall ?? 0, d.overall_lbl || '--', d.file ?? 0, d.file_lbl || '--');
    }
    if ((d.overall ?? 0) >= 100) {
      toast(t('toast_tr_done'), 'success');
    }
  } catch (_) {
    _appendTrLog(line, 'info');
  }
}

function _handleTranscribeStreamError(errOrMsg) {
  const errMsg = typeof errOrMsg === 'string' ? errOrMsg : (errOrMsg?.message || String(errOrMsg || ''));
  const lowerErr = errMsg.toLowerCase();
  if (
    lowerErr.includes('api key') ||
    lowerErr.includes('api_key') ||
    lowerErr.includes('apikey') ||
    lowerErr.includes('authentication') ||
    lowerErr.includes('unauthorized') ||
    lowerErr.includes('thiếu groq api key') ||
    lowerErr.includes('invalid key')
  ) {
    const provider = 'groq';
    const currentKey = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider('groq') : '';
    if (typeof _showApiCheckModal === 'function') {
      _showApiCheckModal(
        provider,
        currentKey,
        errMsg,
        () => {
          toast('Đã cập nhật API key mới, vui lòng nhấn Bắt đầu phiên âm lại.', 'info');
        }
      );
      return true;
    }
  }
  return false;
}

function _appendTrLog(msg, level) {
  appendLog('tr-log', msg, level || 'info');
}

function _setTrProgress(overallPct, overallLbl, filePct, fileLbl) {
  setProgress('pb-tr-overall', 'lbl-tr-overall', Number(overallPct) || 0, overallLbl || '--');
  setProgress('pb-tr-file', 'lbl-tr-file', Number(filePct) || 0, fileLbl || '--');
}

const TRANSCRIBE_VOICE_SAMPLES = [
  {
    id: 'ms_vi_female_cheerful',
    label: 'MS nữ vui vẻ',
    lang: 'vi',
    engine: 'edge-tts',
    voice: 'vi-VN-HoaiMyNeural',
    emotion: 'cheerful',
    rate: '+6%',
    pitch: '+0Hz',
    text: 'Xin chào, đây là giọng nữ vui vẻ, rõ ràng và tự nhiên cho video tiếng Việt.',
  },
  {
    id: 'ms_vi_male_story',
    label: 'MS nam kể chuyện',
    lang: 'vi',
    engine: 'edge-tts',
    voice: 'vi-VN-NamMinhNeural',
    emotion: 'narration-professional',
    rate: '-3%',
    pitch: '-2Hz',
    text: 'Đêm xuống, câu chuyện bắt đầu bằng một nhịp kể trầm ấm và cuốn hút.',
  },
  {
    id: 'ms_vi_newscast',
    label: 'MS bản tin',
    lang: 'vi',
    engine: 'edge-tts',
    voice: 'vi-VN-HoaiMyNeural',
    emotion: 'newscast',
    rate: '+2%',
    pitch: '+0Hz',
    text: 'Bản tin hôm nay có những chuyển động đáng chú ý, được trình bày ngắn gọn và mạch lạc.',
  },
  {
    id: 'ms_vi_sad',
    label: 'MS buồn nhẹ',
    lang: 'vi',
    engine: 'edge-tts',
    voice: 'vi-VN-HoaiMyNeural',
    emotion: 'sad',
    rate: '-8%',
    pitch: '-3Hz',
    text: 'Có những khoảnh khắc lặng xuống, khi giọng đọc cần chậm rãi và nhiều cảm xúc hơn.',
  },
  {
    id: 'vieneu_vi_female_bright',
    label: 'VieNeu nữ sáng',
    lang: 'vi',
    engine: 'vieneu',
    voice: 'Ngọc Linh',
    emotion: 'cheerful',
    rate: '+4%',
    pitch: '+0Hz',
    text: 'Xin chào, đây là mẫu giọng VieNeu nữ tươi sáng, rõ lời và giàu năng lượng cho video tiếng Việt.',
  },
  {
    id: 'vieneu_vi_female_soft',
    label: 'VieNeu nữ dịu',
    lang: 'vi',
    engine: 'vieneu',
    voice: 'Ngọc Lan',
    emotion: 'friendly',
    rate: '+0%',
    pitch: '+0Hz',
    text: 'Giọng đọc dịu dàng sẽ giúp nội dung chia sẻ trở nên gần gũi, tự nhiên và dễ nghe hơn.',
  },
  {
    id: 'vieneu_vi_male_story',
    label: 'VieNeu nam kể chuyện',
    lang: 'vi',
    engine: 'vieneu',
    voice: 'Gia Bảo',
    emotion: 'narration-professional',
    rate: '-3%',
    pitch: '-1Hz',
    text: 'Trong một buổi chiều yên tĩnh, câu chuyện mở ra bằng nhịp kể trầm ấm và cuốn hút.',
  },
  {
    id: 'vieneu_vi_male_upbeat',
    label: 'VieNeu nam vui',
    lang: 'vi',
    engine: 'vieneu',
    voice: 'Xuân Vĩnh',
    emotion: 'excited',
    rate: '+6%',
    pitch: '+1Hz',
    text: 'Hôm nay chúng ta bắt đầu một ý tưởng mới, nhanh, sáng và tràn đầy năng lượng.',
  },
  {
    id: 'gtts_vi_basic',
    label: 'Google gTTS Việt',
    lang: 'vi',
    engine: 'gtts',
    voice: 'vi|com.vn',
    emotion: 'default',
    rate: '+0%',
    pitch: '+0Hz',
    text: 'Đây là mẫu giọng Google gTTS tiếng Việt, dùng làm phương án dự phòng đơn giản.',
  },
  {
    id: 'ms_en_female',
    label: 'MS EN nữ',
    lang: 'en',
    engine: 'edge-tts',
    voice: 'en-US-AvaNeural',
    emotion: 'friendly',
    rate: '+0%',
    pitch: '+0Hz',
    text: 'Hello, this is a warm and friendly English voice sample for narration.',
  },
  {
    id: 'gtts_en_bright',
    label: 'Google gTTS EN',
    lang: 'en',
    engine: 'gtts',
    voice: 'en|com',
    emotion: 'cheerful',
    rate: '+0%',
    pitch: '+0Hz',
    text: 'Hello, this is a simple Google gTTS English sample for quick preview.',
  },
];

const TRANSCRIBE_CUSTOM_VOICE_KEY = 'toolvideo.transcribe.customVoices.v1';
const TRANSCRIBE_HIDDEN_VOICE_KEY = 'toolvideo.transcribe.hiddenVoices.v1';
let TRANSCRIBE_VOICE_FILTER = 'all';

const TRANSCRIBE_GOOGLE_PERSONA_VOICES = [];

function _trVoiceGenderFromLabel(label) {
  const raw = String(label || '').toLowerCase();
  if (raw.includes('nữ') || raw.includes('female') || raw.includes('woman') || raw.includes('girl')) return 'female';
  if (raw.includes('nam') || raw.includes('male') || raw.includes('man') || raw.includes('boy')) return 'male';
  return 'other';
}

function _trVoiceGenderLabel(gender) {
  if (gender === 'female') return 'Nữ';
  if (gender === 'male') return 'Nam';
  return 'Khác';
}

function _trVoiceLangLabel(lang) {
  const map = { vi: 'Tiếng Việt', en: 'Tiếng Anh', zh: 'Tiếng Trung', ja: 'Tiếng Nhật', ko: 'Tiếng Hàn', multi: 'Đa ngôn ngữ' };
  return map[lang] || String(lang || 'VI').toUpperCase();
}

function _trVoiceEngineLabel(engine) {
  const found = (TTS_ENGINE_CATALOG || []).find(e => String(e.id || '').toLowerCase() === String(engine || '').toLowerCase());
  if (found) return found.label || found.id;
  const map = {
    vieneu: 'VieNeu',
    'edge-tts': 'Microsoft',
    gtts: 'Google gTTS',
    '9r:gemini': 'Google Gemini',
    '9r:google-tts': 'Google Cloud',
    '9r:edge-tts': 'Microsoft 9R',
    '9router': '9Router',
    'fpt-ai': 'FPT AI',
    elevenlabs: 'ElevenLabs',
    'fish-audio': 'Fish Audio',
    minimax: 'MiniMax',
  };
  return map[engine] || engine || 'TTS';
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

function _saveTranscribeCustomVoices(rows) {
  localStorage.setItem(TRANSCRIBE_CUSTOM_VOICE_KEY, JSON.stringify(rows || []));
}

function _getTranscribeHiddenVoiceIds() {
  try {
    const rows = JSON.parse(localStorage.getItem(TRANSCRIBE_HIDDEN_VOICE_KEY) || '[]');
    return new Set(Array.isArray(rows) ? rows.map(String) : []);
  } catch (_) {
    return new Set();
  }
}

function _saveTranscribeHiddenVoiceIds(ids) {
  localStorage.setItem(TRANSCRIBE_HIDDEN_VOICE_KEY, JSON.stringify(Array.from(ids || [])));
}

function _getTranscribeBuiltInVoices() {
  const rows = [];
  const addPreset = (engine, item, idx) => {
    if (!item?.value) return;
    rows.push(_trNormalizeVoiceItem({
      id: `preset_${engine}_${String(item.value).replace(/[^a-z0-9]+/gi, '_')}_${idx}`,
      label: String(item.label || item.value).replace(/\s*\([^)]*\)\s*$/, '') || item.value,
      engine,
      voice: item.value,
      lang: engine === 'gtts' && String(item.value).startsWith('en') ? 'en' : 'vi',
      gender: _trVoiceGenderFromLabel(item.label || item.value),
      source: _trVoiceEngineLabel(engine),
      readonly: true,
    }));
  };

  ['vieneu', 'edge-tts', 'gtts'].forEach(engine => {
    (TTS_VOICE_PRESETS[engine] || []).forEach((item, idx) => addPreset(engine, item, idx));
  });

  TRANSCRIBE_GOOGLE_PERSONA_VOICES.forEach(item => {
    rows.push(_trNormalizeVoiceItem({ ...item, readonly: true }));
  });

  const seen = new Set();
  return rows.filter(item => {
    const key = `${item.id}|${item.engine}|${item.voice}|${item.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return item.voice;
  });
}

function _getTranscribeAllVoices() {
  return [..._getTranscribeBuiltInVoices(), ..._getTranscribeCustomVoices()];
}

function _getTranscribeManagedVoices() {
  const hidden = _getTranscribeHiddenVoiceIds();
  return _getTranscribeAllVoices().filter(item => !hidden.has(item.id));
}

function _getTranscribeHiddenVoices() {
  const hidden = _getTranscribeHiddenVoiceIds();
  return _getTranscribeAllVoices().filter(item => hidden.has(item.id));
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

function _ensureTranscribeEngineOption(engine, label) {
  const engineEl = document.getElementById('tr-tts-engine');
  if (!engineEl || !engine) return;
  if (Array.from(engineEl.options || []).some(opt => opt.value === engine)) return;
  const opt = document.createElement('option');
  opt.value = engine;
  opt.textContent = label || _trVoiceEngineLabel(engine);
  engineEl.appendChild(opt);
}

function _set9RouterVoiceFromManaged(item) {
  const key = _9rKey('tr-tts-engine');
  const voiceInput = document.getElementById(key + '-9r-voice');
  if (voiceInput) voiceInput.value = item.voice || '';
  const modelSel = document.getElementById(key + '-9r-model');
  if (modelSel && item.model && Array.from(modelSel.options || []).some(opt => opt.value === item.model)) {
    modelSel.value = item.model;
  }
}

function renderTranscribeVoiceLibrary() {
  const box = document.getElementById('tr-voice-library');
  if (!box) return;
  const q = String(document.getElementById('tr-voice-search')?.value || '').trim().toLowerCase();
  const selectedEngine = document.getElementById('tr-tts-engine')?.value || '';
  const selectedVoice = (selectedEngine === '9router' || String(selectedEngine).startsWith('9r:'))
    ? (document.getElementById(_9rKey('tr-tts-engine') + '-9r-voice')?.value || '')
    : (document.getElementById('tr-tts-voice')?.value || '');
  let rows = _getTranscribeManagedVoices();

  if (TRANSCRIBE_VOICE_FILTER === 'female' || TRANSCRIBE_VOICE_FILTER === 'male') {
    rows = rows.filter(item => item.gender === TRANSCRIBE_VOICE_FILTER);
  } else if (TRANSCRIBE_VOICE_FILTER === 'fav') {
    rows = rows.filter(item => item.favorite);
  } else if (TRANSCRIBE_VOICE_FILTER.startsWith('lang_')) {
    const targetLang = TRANSCRIBE_VOICE_FILTER.replace('lang_', '');
    rows = rows.filter(item => item.lang === targetLang);
  }
  if (q) {
    rows = rows.filter(item => [
      item.label, item.voice, item.engine, item.source, item.persona,
    ].join(' ').toLowerCase().includes(q));
  }

  box.innerHTML = '';
  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted text-sm';
    empty.textContent = 'Chưa có giọng phù hợp.';
    box.appendChild(empty);
    return;
  }

  rows.slice(0, 120).forEach(item => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'tr-voice-card';
    if (item.engine === selectedEngine && item.voice === selectedVoice) btn.classList.add('selected');
    btn.dataset.voiceId = item.id;

    const title = document.createElement('div');
    title.className = 'tr-voice-card-title';
    const name = document.createElement('span');
    name.textContent = item.label;
    const star = document.createElement('span');
    star.textContent = item.favorite ? '★' : '';
    title.appendChild(name);
    title.appendChild(star);

    const detail = document.createElement('small');
    detail.textContent = `${_trVoiceEngineLabel(item.engine)} · ${item.voice}`;

    const meta = document.createElement('div');
    meta.className = 'tr-voice-card-meta';
    [_trVoiceGenderLabel(item.gender), _trVoiceLangLabel(item.lang), item.source || 'Voice'].forEach(text => {
      const pill = document.createElement('span');
      pill.className = 'tr-voice-pill';
      pill.textContent = text;
      meta.appendChild(pill);
    });
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-secondary btn-sm';
    delBtn.textContent = 'Xóa';
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteTranscribeVoiceById(item.id);
    });
    meta.appendChild(delBtn);

    btn.appendChild(title);
    btn.appendChild(detail);
    btn.appendChild(meta);
    btn.addEventListener('click', () => applyTranscribeManagedVoice(item.id, false));
    box.appendChild(btn);
  });
}

function fillTranscribeVoiceEditor(item) {
  const isCustom = !!item?.custom;
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  };
  set('tr-voice-edit-key', item?.id || '');
  set('tr-voice-name', item?.label || '');
  const engine = item?.engine || document.getElementById('tr-tts-engine')?.value || 'vieneu';
  set('tr-voice-engine', engine);
  set('tr-voice-id', item?.voice || '');
  set('tr-voice-gender', item?.gender || 'female');
  set('tr-voice-lang', item?.lang || 'vi');
  set('tr-voice-emotion', item?.emotion || 'default');
  set('tr-voice-persona', item?.persona || '');
  set('tr-voice-ref-audio', item?.ref_audio || '');
  set('tr-voice-text', item?.text || '');
  const fav = document.getElementById('tr-voice-favorite');
  if (fav) fav.checked = !!item?.favorite;
  const del = document.getElementById('tr-voice-delete');
  if (del) {
    del.disabled = !item?.id;
    del.textContent = isCustom ? 'Xóa giọng' : 'Ẩn khỏi danh sách';
  }
  const refAudioContainer = document.getElementById('tr-voice-ref-audio-container');
  if (refAudioContainer) {
    refAudioContainer.style.display = (engine === 'vieneu') ? '' : 'none';
  }
  syncTranscribeVoiceEditorVoices();
}

function resetTranscribeVoiceEditor() {
  fillTranscribeVoiceEditor({
    label: '',
    engine: document.getElementById('tr-tts-engine')?.value || 'vieneu',
    voice: '',
    gender: 'female',
    lang: document.getElementById('tr-tts-lang')?.value || 'vi',
    emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
    persona: '',
    ref_audio: '',
    text: '',
    favorite: false,
  });
}

function applyTranscribeManagedVoice(voiceId, autoPreview = false) {
  const item = _getTranscribeManagedVoices().find(v => v.id === voiceId);
  if (!item) return;
  _ensureTranscribeEngineOption(item.engine, _trVoiceEngineLabel(item.engine));

  const langEl = document.getElementById('tr-tts-lang');
  if (langEl && item.lang && item.lang !== 'multi') langEl.value = item.lang;
  const engineEl = document.getElementById('tr-tts-engine');
  if (engineEl) engineEl.value = item.engine;
  _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');

  if (item.engine === '9router' || String(item.engine).startsWith('9r:')) {
    _set9RouterVoiceFromManaged(item);
  } else {
    const voiceEl = document.getElementById('tr-tts-voice');
    if (voiceEl && item.voice) {
      if (!Array.from(voiceEl.options || []).some(opt => opt.value === item.voice)) {
        const opt = document.createElement('option');
        opt.value = item.voice;
        opt.textContent = item.label || item.voice;
        voiceEl.appendChild(opt);
      }
      voiceEl.value = item.voice;
    }
  }

  const emotionEl = document.getElementById('tr-tts-emotion');
  if (emotionEl) emotionEl.value = item.emotion || 'default';
  const rateEl = document.getElementById('tr-tts-rate');
  if (rateEl) rateEl.value = item.rate || '+0%';
  const pitchEl = document.getElementById('tr-tts-pitch');
  if (pitchEl) pitchEl.value = item.pitch || '+0Hz';
  const personaEl = document.getElementById('tr-tts-persona');
  if (personaEl) personaEl.value = item.persona || '';
  const refAudioEl = document.getElementById('tr-tts-ref-audio');
  if (refAudioEl) refAudioEl.value = item.ref_audio || '';
  const textEl = document.getElementById('tr-preview-text');
  if (textEl && item.text) textEl.value = item.text;

  fillTranscribeVoiceEditor(item);
  _appendTrLog(`Đã chọn giọng: ${item.label} · ${_trVoiceEngineLabel(item.engine)}/${item.voice}`, 'info');
  renderTranscribeVoiceLibrary();
  if (autoPreview) previewTranscribeVoice();
}

function saveTranscribeManagedVoice() {
  let voice = String(document.getElementById('tr-voice-id')?.value || '').trim();
  const refAudio = String(document.getElementById('tr-voice-ref-audio')?.value || '').trim();
  const engine = String(document.getElementById('tr-voice-engine')?.value || 'vieneu').trim();
  
  if (!voice && refAudio) {
    voice = 'clone_voice';
    const voiceIdInput = document.getElementById('tr-voice-id');
    if (voiceIdInput) voiceIdInput.value = voice;
  }

  const label = String(document.getElementById('tr-voice-name')?.value || '').trim() || voice;
  if (!voice) {
    alert('Vui lòng nhập Voice ID / tên voice gốc.');
    document.getElementById('tr-voice-id')?.focus();
    return;
  }

  const editKey = String(document.getElementById('tr-voice-edit-key')?.value || '').trim();
  const rows = _getTranscribeCustomVoices();
  const isEditingCustom = rows.some(v => v.id === editKey);
  const item = _trNormalizeVoiceItem({
    id: isEditingCustom ? editKey : `custom_${Date.now()}`,
    label,
    engine,
    voice,
    gender: document.getElementById('tr-voice-gender')?.value || 'other',
    lang: document.getElementById('tr-voice-lang')?.value || 'vi',
    emotion: document.getElementById('tr-voice-emotion')?.value || 'default',
    persona: document.getElementById('tr-voice-persona')?.value || '',
    text: document.getElementById('tr-voice-text')?.value || '',
    ref_audio: refAudio,
    favorite: !!document.getElementById('tr-voice-favorite')?.checked,
    source: 'Tự thêm',
    custom: true,
  });

  const idx = rows.findIndex(v => v.id === item.id);
  if (idx >= 0) rows[idx] = item;
  else rows.push(item);
  _saveTranscribeCustomVoices(rows);
  applyTranscribeManagedVoice(item.id, false);
  if (typeof toast === 'function') toast('Đã lưu giọng đọc', 'success');
}

function deleteTranscribeManagedVoice() {
  const editKey = String(document.getElementById('tr-voice-edit-key')?.value || '').trim();
  if (editKey) deleteTranscribeVoiceById(editKey);
}

function deleteTranscribeVoiceById(voiceId) {
  const item = _getTranscribeAllVoices().find(v => v.id === voiceId);
  if (!item) return;

  if (item.custom) {
    const rows = _getTranscribeCustomVoices().filter(v => v.id !== voiceId);
    _saveTranscribeCustomVoices(rows);
  } else {
    const hidden = _getTranscribeHiddenVoiceIds();
    hidden.add(voiceId);
    _saveTranscribeHiddenVoiceIds(hidden);
  }

  resetTranscribeVoiceEditor();
  renderTranscribeVoiceLibrary();
  renderTranscribeHiddenVoices();
  if (typeof toast === 'function') {
    toast(item.custom ? 'Đã xóa giọng tự thêm' : 'Đã ẩn giọng khỏi danh sách', 'success');
  }
}

function restoreTranscribeHiddenVoice(voiceId) {
  const hidden = _getTranscribeHiddenVoiceIds();
  hidden.delete(voiceId);
  _saveTranscribeHiddenVoiceIds(hidden);
  renderTranscribeVoiceLibrary();
  renderTranscribeHiddenVoices();
}

function restoreAllTranscribeHiddenVoices() {
  _saveTranscribeHiddenVoiceIds(new Set());
  renderTranscribeVoiceLibrary();
  renderTranscribeHiddenVoices();
  if (typeof toast === 'function') toast('Đã khôi phục danh sách giọng', 'success');
}

function renderTranscribeHiddenVoices() {
  const box = document.getElementById('tr-voice-hidden-list');
  if (!box) return;
  const rows = _getTranscribeHiddenVoices();
  box.innerHTML = '';
  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted text-sm';
    empty.textContent = 'Chưa có giọng nào bị ẩn.';
    box.appendChild(empty);
    return;
  }
  rows.forEach(item => {
    const row = document.createElement('div');
    row.className = 'tr-voice-hidden-row';
    const info = document.createElement('div');
    info.innerHTML = '<b></b><div class="text-xs text-muted"></div>';
    info.querySelector('b').textContent = item.label;
    info.querySelector('div').textContent = `${_trVoiceEngineLabel(item.engine)} · ${item.voice}`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-secondary btn-sm';
    btn.textContent = 'Khôi phục';
    btn.addEventListener('click', () => restoreTranscribeHiddenVoice(item.id));
    row.appendChild(info);
    row.appendChild(btn);
    box.appendChild(row);
  });
}

function switchTranscribeVoicePanel(panel) {
  const target = panel || 'library';
  document.querySelectorAll('[data-tr-voice-panel]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.trVoicePanel === target);
  });
  document.querySelectorAll('.tr-voice-panel').forEach(el => {
    el.classList.toggle('active', el.id === `tr-voice-panel-${target}`);
  });
  if (target === 'hidden') renderTranscribeHiddenVoices();
}

function toggleTranscribeVoiceIdMode() {
  const selectEl = document.getElementById('tr-voice-id-select');
  const inputEl = document.getElementById('tr-voice-id');
  const toggleBtn = document.getElementById('tr-voice-id-toggle');
  if (!selectEl || !inputEl || !toggleBtn) return;

  if (selectEl.style.display === 'none') {
    selectEl.style.display = '';
    inputEl.style.display = 'none';
    toggleBtn.textContent = 'Nhập thủ công';
    inputEl.value = selectEl.value;
  } else {
    selectEl.style.display = 'none';
    inputEl.style.display = '';
    toggleBtn.textContent = 'Chọn sẵn';
  }
}

function syncTranscribeVoiceEditorVoices() {
  const engineEl = document.getElementById('tr-voice-engine');
  const langEl = document.getElementById('tr-voice-lang');
  const selectEl = document.getElementById('tr-voice-id-select');
  const inputEl = document.getElementById('tr-voice-id');
  const toggleBtn = document.getElementById('tr-voice-id-toggle');

  if (!engineEl || !selectEl || !inputEl) return;

  const engine = engineEl.value || 'vieneu';
  const lang = langEl?.value || 'vi';

  let voices = [];
  if (TTS_VOICE_PRESETS[engine]) {
    voices = TTS_VOICE_PRESETS[engine].map(v => ({ value: v.value, label: v.label || v.value }));
  }

  if (TTS_ENGINE_CATALOG) {
    const catalogEngine = TTS_ENGINE_CATALOG.find(e => String(e.id || '').toLowerCase() === String(engine).toLowerCase());
    if (catalogEngine && catalogEngine.voices) {
      const voicesByLang = catalogEngine.voices || {};
      let rawList = voicesByLang[lang] || voicesByLang.multi || [];
      if (!rawList.length && engine === 'edge-tts' && EDGE_TTS_BY_LANG[lang]) {
        rawList = EDGE_TTS_BY_LANG[lang];
      }
      if (!rawList.length && engine === 'gtts' && GTTS_BY_LANG[lang]) {
        rawList = [[GTTS_BY_LANG[lang], `${lang} (gTTS)`]];
      }
      if (!rawList.length) {
        const fallbackLang = voicesByLang.vi ? 'vi' : Object.keys(voicesByLang)[0];
        rawList = voicesByLang[fallbackLang] || [];
      }
      const catalogVoices = _catalogVoicesToPreset(rawList);
      catalogVoices.forEach(cv => {
        if (!voices.some(v => v.value === cv.value)) {
          voices.push(cv);
        }
      });
    }
  }

  if (!voices.length) {
    if (engine === 'edge-tts' && EDGE_TTS_BY_LANG[lang]) {
      voices = EDGE_TTS_BY_LANG[lang].map(v => ({ value: v.value, label: v.label || v.value }));
    } else if (engine === 'gtts' && GTTS_BY_LANG[lang]) {
      voices = [{ value: GTTS_BY_LANG[lang], label: `${lang} (gTTS)` }];
    }
  }

  selectEl.innerHTML = '';
  voices.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v.value;
    opt.textContent = v.label;
    selectEl.appendChild(opt);
  });

  const currentVal = inputEl.value;
  const isMatch = voices.some(v => v.value === currentVal);

  if (isMatch && currentVal) {
    selectEl.value = currentVal;
    selectEl.style.display = '';
    inputEl.style.display = 'none';
    if (toggleBtn) toggleBtn.textContent = 'Nhập thủ công';
  } else if (!currentVal && voices.length) {
    selectEl.selectedIndex = 0;
    inputEl.value = selectEl.value;
    selectEl.style.display = '';
    inputEl.style.display = 'none';
    if (toggleBtn) toggleBtn.textContent = 'Nhập thủ công';
  } else {
    selectEl.style.display = 'none';
    inputEl.style.display = '';
    if (toggleBtn) toggleBtn.textContent = 'Chọn sẵn';
  }
}

function initTranscribeVoiceManager() {
  document.querySelectorAll('[data-tr-voice-panel]').forEach(btn => {
    btn.addEventListener('click', () => switchTranscribeVoicePanel(btn.dataset.trVoicePanel || 'library'));
  });
  document.querySelectorAll('[data-tr-voice-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      TRANSCRIBE_VOICE_FILTER = btn.dataset.trVoiceFilter || 'all';
      document.querySelectorAll('[data-tr-voice-filter]').forEach(b => b.classList.toggle('active', b === btn));
      renderTranscribeVoiceLibrary();
    });
  });
  document.getElementById('tr-voice-search')?.addEventListener('input', renderTranscribeVoiceLibrary);
  ['tr-tts-engine', 'tr-tts-voice'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', renderTranscribeVoiceLibrary);
  });
  document.getElementById('tr-voice-engine')?.addEventListener('change', () => {
    syncTranscribeVoiceEditorVoices();
    const container = document.getElementById('tr-voice-ref-audio-container');
    if (container) {
      container.style.display = (document.getElementById('tr-voice-engine')?.value === 'vieneu') ? '' : 'none';
    }
  });
  document.getElementById('tr-voice-lang')?.addEventListener('change', () => {
    syncTranscribeVoiceEditorVoices();
  });
  resetTranscribeVoiceEditor();
  renderTranscribeVoiceLibrary();
  renderTranscribeHiddenVoices();
  switchTranscribeVoicePanel('library');
}

function renderTranscribeVoiceSamples() {
  const box = document.getElementById('tr-voice-samples');
  if (!box || box.dataset.rendered === '1') return;
  box.innerHTML = '';
  TRANSCRIBE_VOICE_SAMPLES.forEach(sample => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-secondary btn-sm';
    btn.textContent = sample.label;
    btn.addEventListener('click', () => applyTranscribeVoiceSample(sample.id, true));
    box.appendChild(btn);
  });
  box.dataset.rendered = '1';
}

function _selectTranscribeEngine(sample) {
  const engineEl = document.getElementById('tr-tts-engine');
  if (!engineEl) return { engine: '', fallback: false };
  const hasEngine = Array.from(engineEl.options || []).some(opt => opt.value === sample.engine);
  let engine = sample.engine;
  let fallback = false;
  if (!hasEngine && sample.fallbackEngine) {
    const hasFallback = Array.from(engineEl.options || []).some(opt => opt.value === sample.fallbackEngine);
    if (hasFallback) {
      engine = sample.fallbackEngine;
      fallback = true;
    }
  }
  engineEl.value = engine;
  return { engine, fallback };
}

function _selectTranscribeVoice(voiceId) {
  const voiceEl = document.getElementById('tr-tts-voice');
  if (!voiceEl || !voiceId) return;
  const hasVoice = Array.from(voiceEl.options || []).some(opt => opt.value === voiceId);
  if (hasVoice) voiceEl.value = voiceId;
}

async function applyTranscribeVoiceSample(sampleId, autoPreview = false) {
  const sample = TRANSCRIBE_VOICE_SAMPLES.find(item => item.id === sampleId);
  if (!sample) return;

  try { await _loadTtsEngineCatalog(); } catch (_) {}

  const langEl = document.getElementById('tr-tts-lang');
  if (langEl) langEl.value = sample.lang || 'vi';

  const { engine, fallback } = _selectTranscribeEngine(sample);
  _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');

  const voiceId = fallback ? (sample.fallbackVoice || '') : sample.voice;
  _selectTranscribeVoice(voiceId);

  const emotionEl = document.getElementById('tr-tts-emotion');
  if (emotionEl) emotionEl.value = fallback ? 'default' : (sample.emotion || 'default');
  const rateEl = document.getElementById('tr-tts-rate');
  if (rateEl) rateEl.value = sample.rate || '+0%';
  const pitchEl = document.getElementById('tr-tts-pitch');
  if (pitchEl) pitchEl.value = sample.pitch || '+0Hz';
  const textEl = document.getElementById('tr-preview-text');
  if (textEl) textEl.value = sample.text || textEl.value || '';
  const personaEl = document.getElementById('tr-tts-persona');
  if (personaEl) personaEl.value = sample.persona || '';

  if (fallback && typeof toast === 'function') {
    toast('Chưa thấy engine mẫu đã chọn, đã dùng giọng dự phòng.', 'warning');
  }
  _appendTrLog(`Mẫu giọng: ${sample.label} · ${engine}/${voiceId || 'auto'}`, 'info');
  renderTranscribeVoiceLibrary();
  if (autoPreview) await previewTranscribeVoice();
}

async function createMp3FromText() {
  const textInput = document.getElementById('tr-preview-text');
  const text = textInput?.value?.trim() || '';
  if (!text) {
    alert('Vui lòng nhập nội dung để tạo MP3.');
    textInput?.focus();
    return;
  }

  // --- PRE-FLIGHT API CHECK FOR TTS ---
  const ttsEngine = (typeof _resolveTtsEngineVoice === 'function' ? _resolveTtsEngineVoice('tr') : {}).tts_engine || '';
  const ttsProvider = _getTtsApiProvider(ttsEngine);
  if (ttsProvider && typeof checkApiBeforeAction === 'function') {
    const key = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider(ttsProvider) : '';
    let apiOk = false;
    await new Promise(resolve => checkApiBeforeAction(ttsProvider, key, () => { apiOk = true; resolve(); }, resolve));
    if (!apiOk) return; // Stop if cancel / invalid
  }
  // --- END OF PRE-FLIGHT API CHECK FOR TTS ---

  const btn = document.getElementById('btn-tr-tts-mp3');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang tạo...'; }
  _appendTrLog('🎙 Đang tạo MP3 từ văn bản (' + text.length + ' ký tự)...', 'info');

  try {
    const res = await fetch('/api/tts_to_mp3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        ..._resolveTtsEngineVoice('tr'),
        tts_lang: document.getElementById('tr-tts-lang')?.value || 'vi',
        language: document.getElementById('tr-tts-lang')?.value || 'vi',
        tts_pitch: _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
        tts_persona: document.getElementById('tr-tts-persona')?.value || '',
        ref_audio: document.getElementById('tr-tts-ref-audio')?.value || '',
        fx_enabled: document.getElementById('tr-fx-enabled')?.checked || false,
        fx_pitch: parseFloat(document.getElementById('tr-fx-pitch')?.value || '1.5'),
        fx_speed: parseFloat(document.getElementById('tr-fx-speed')?.value || '1.08'),
        fx_bass: parseFloat(document.getElementById('tr-fx-bass')?.value || '-2'),
        fx_mid: parseFloat(document.getElementById('tr-fx-mid')?.value || '2'),
        fx_treble: parseFloat(document.getElementById('tr-fx-treble')?.value || '3'),
        fx_comp: document.getElementById('tr-fx-comp')?.value || 'none',
        fx_reverb: parseFloat(document.getElementById('tr-fx-reverb')?.value || '0'),
      }),
    });

    if (!res.ok) {
      let errorText = 'Không thể tạo MP3';
      try {
        const errJson = await res.json();
        if (errJson?.error) errorText = errJson.error;
      } catch (_) {}
      throw new Error(errorText);
    }

    const blob = await res.blob();

    // Tên file: dùng input nếu có, không thì auto theo timestamp
    let filename = (document.getElementById('tr-tts-filename')?.value || '').trim();
    if (!filename) {
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      filename = 'tts_' + ts + '.mp3';
    } else if (!/\.mp3$/i.test(filename)) {
      filename += '.mp3';
    }

    // Trigger download
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);

    // Cho phép nghe luôn trong player
    const audio = document.getElementById('tr-preview-audio');
    if (audio) {
      if (window._trPreviewObjectUrl) {
        URL.revokeObjectURL(window._trPreviewObjectUrl);
      }
      window._trPreviewObjectUrl = URL.createObjectURL(blob);
      audio.src = window._trPreviewObjectUrl;
      audio.style.display = 'block';
    }

    _appendTrLog('✅ Đã tạo MP3: ' + filename, 'success');
    toast('Đã tải MP3: ' + filename, 'success');
  } catch (err) {
    _appendTrLog('❌ Lỗi: ' + err.message, 'error');
    if (!_handleTtsError(err, 'tr')) {
      alert('Lỗi tạo MP3: ' + err.message);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 Tạo & tải MP3'; }
  }
}

async function previewTranscribeVoice() {
  const textInput = document.getElementById('tr-preview-text');
  let text = textInput?.value?.trim() || '';
  if (!text && window._trAssPreviewText) {
    text = window._trAssPreviewText;
    if (textInput) textInput.value = text;
  }
  if (!text) {
    alert('Vui lòng nhập nội dung để nghe thử giọng.');
    return;
  }

  // --- PRE-FLIGHT API CHECK FOR TTS ---
  const ttsEngine = (typeof _resolveTtsEngineVoice === 'function' ? _resolveTtsEngineVoice('tr') : {}).tts_engine || '';
  const ttsProvider = _getTtsApiProvider(ttsEngine);
  if (ttsProvider && typeof checkApiBeforeAction === 'function') {
    const key = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider(ttsProvider) : '';
    let apiOk = false;
    await new Promise(resolve => checkApiBeforeAction(ttsProvider, key, () => { apiOk = true; resolve(); }, resolve));
    if (!apiOk) return; // Stop if cancel / invalid
  }
  // --- END OF PRE-FLIGHT API CHECK FOR TTS ---

  const btn = document.getElementById('btn-tr-preview');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang tạo giọng...';
  }

  try {
    const res = await fetch('/api/tts_preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        ..._resolveTtsEngineVoice('tr'),
        tts_lang: document.getElementById('tr-tts-lang')?.value || 'vi',
        language: document.getElementById('tr-tts-lang')?.value || 'vi',
        tts_pitch: _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
        tts_persona: document.getElementById('tr-tts-persona')?.value || '',
        ref_audio: document.getElementById('tr-tts-ref-audio')?.value || '',
        fx_enabled: document.getElementById('tr-fx-enabled')?.checked || false,
        fx_pitch: parseFloat(document.getElementById('tr-fx-pitch')?.value || '1.5'),
        fx_speed: parseFloat(document.getElementById('tr-fx-speed')?.value || '1.08'),
        fx_bass: parseFloat(document.getElementById('tr-fx-bass')?.value || '-2'),
        fx_mid: parseFloat(document.getElementById('tr-fx-mid')?.value || '2'),
        fx_treble: parseFloat(document.getElementById('tr-fx-treble')?.value || '3'),
        fx_comp: document.getElementById('tr-fx-comp')?.value || 'none',
        fx_reverb: parseFloat(document.getElementById('tr-fx-reverb')?.value || '0'),
      }),
    });

    if (!res.ok) {
      let errorText = 'Không thể tạo audio preview';
      try {
        const errJson = await res.json();
        if (errJson?.error) errorText = errJson.error;
      } catch (_) {}
      throw new Error(errorText);
    }

    const blob = await res.blob();
    const audio = document.getElementById('tr-preview-audio');
    if (!audio) return;

    if (window._trPreviewObjectUrl) {
      URL.revokeObjectURL(window._trPreviewObjectUrl);
      window._trPreviewObjectUrl = null;
    }

    window._trPreviewObjectUrl = URL.createObjectURL(blob);
    audio.src = window._trPreviewObjectUrl;
    audio.style.display = 'block';
    try { await audio.play(); } catch (_) {}
  } catch (err) {
    if (!_handleTtsError(err, 'tr')) {
      alert('Lỗi preview giọng: ' + err.message);
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Nghe thử';
    }
  }
}

async function previewProcessVoice() {
  const text = 'Xin chào, đây là phần nghe thử giọng đọc xử lý video.';
  const btn = document.querySelector('button[onclick="previewProcessVoice()"]');

  // --- PRE-FLIGHT API CHECK FOR TTS ---
  const ttsEngine = (typeof _resolveTtsEngineVoice === 'function' ? _resolveTtsEngineVoice('proc') : {}).tts_engine || '';
  const ttsProvider = _getTtsApiProvider(ttsEngine);
  if (ttsProvider && typeof checkApiBeforeAction === 'function') {
    const key = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider(ttsProvider) : '';
    let apiOk = false;
    await new Promise(resolve => checkApiBeforeAction(ttsProvider, key, () => { apiOk = true; resolve(); }, resolve));
    if (!apiOk) return; // Stop if cancel / invalid
  }
  // --- END OF PRE-FLIGHT API CHECK FOR TTS ---

  if (btn) { btn.disabled = true; btn.textContent = 'Đang tạo...'; }

  try {
    const targetLang = document.getElementById('proc-target-lang')?.value || 'vi';
    const res = await fetch('/api/tts_preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        language: targetLang,
        tts_lang: targetLang,
        ..._resolveTtsEngineVoice('proc'),
        tts_pitch: _sanitizeVoiceParam(document.getElementById('proc-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('proc-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('proc-tts-emotion')?.value || 'default',
      }),
    });

    if (!res.ok) throw new Error('Preview failed');
    const blob = await res.blob();
    const audio = document.getElementById('proc-preview-audio');
    if (audio) {
      if (window._procPreviewUrl) URL.revokeObjectURL(window._procPreviewUrl);
      window._procPreviewUrl = URL.createObjectURL(blob);
      audio.src = window._procPreviewUrl;
      audio.style.display = 'block';
      audio.play();
    }
  } catch (err) {
    if (!_handleTtsError(err, 'proc')) {
      alert('Lỗi: ' + err.message);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Nghe thử'; }
  }
}

function _handleTtsError(err, type = 'tr') {
  const errMsg = err?.message || String(err || '');
  const lowerErr = errMsg.toLowerCase();
  if (
    lowerErr.includes('api key') ||
    lowerErr.includes('api_key') ||
    lowerErr.includes('apikey') ||
    lowerErr.includes('authentication') ||
    lowerErr.includes('unauthorized') ||
    lowerErr.includes('invalid key') ||
    lowerErr.includes('token')
  ) {
    const ttsEngine = (typeof _resolveTtsEngineVoice === 'function' ? _resolveTtsEngineVoice(type) : {}).tts_engine || '';
    const ttsProvider = _getTtsApiProvider(ttsEngine);
    if (ttsProvider && typeof _showApiCheckModal === 'function') {
      const key = typeof getApiKeyForProvider === 'function' ? getApiKeyForProvider(ttsProvider) : '';
      _showApiCheckModal(ttsProvider, key, errMsg, () => {
        toast('Đã cập nhật API key mới, vui lòng thử lại.', 'info');
      });
      return true;
    }
  }
  return false;
}
window._procFileQueue = []; // [{file, name, path}]

function handlePublishFileInput(input) {
  const files = input.files ? Array.from(input.files) : [];
  files.forEach(f => _procFileQueueAdd(f));
  input.value = '';
}

function _procFileQueueAdd(fileOrPath) {
  const isFile = typeof File !== 'undefined' && fileOrPath instanceof File;
  const name = isFile ? fileOrPath.name : String(fileOrPath).split(/[\\/]/).pop();
  const id = Date.now() + '_' + Math.random().toString(36).slice(2);
  window._procFileQueue.push({ id, file: isFile ? fileOrPath : null, path: isFile ? null : String(fileOrPath), name });
  _renderProcFileList();
}

function _procFileQueueRemove(id) {
  window._procFileQueue = window._procFileQueue.filter(f => f.id !== id);
  _renderProcFileList();
}

function _renderProcFileList() {
  const list = document.getElementById('proc-file-list');
  if (!list) return;
  if (!window._procFileQueue.length) { list.style.display = 'none'; return; }
  list.style.display = 'flex';
  list.innerHTML = window._procFileQueue.map(f => `
    <div id="pfl-${f.id}" style="display:flex;align-items:center;gap:6px;padding:5px 8px;background:var(--surf2,#2a2a3e);border-radius:6px;font-size:12px">
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${f.name}">${f.name}</span>
      <span id="pfl-status-${f.id}" style="color:var(--dim,#888);font-size:11px;min-width:60px;text-align:right"></span>
      <button onclick="_procFileQueueRemove('${f.id}')" style="background:none;border:none;color:#ff5555;cursor:pointer;font-size:14px;padding:0 2px">✕</button>
    </div>`).join('');
}

async function publishQueueToTarget(target) {
  if (!window._procFileQueue.length) {
    toast('Chưa có file nào trong danh sách', 'warning');
    return;
  }
  const logBox = document.getElementById('publish-log');
  if (logBox) { logBox.innerHTML = ''; logBox.style.display = 'block'; }

  const queue = [...window._procFileQueue];
  for (const item of queue) {
    const statusEl = document.getElementById(`pfl-status-${item.id}`);
    if (statusEl) statusEl.textContent = '⏳ Đang đăng...';

    try {
      let serverPath = item.path || '';
      if (!serverPath && item.file && typeof window._pubUploadVideoFileToServer === 'function') {
        if (statusEl) statusEl.textContent = '⏳ Đang import...';
        serverPath = await window._pubUploadVideoFileToServer(item.file);
        item.path = serverPath;
      }
      const videoInput = serverPath || item.file;
      if (target === 'tiktok' || target === 'both') {
        if (!serverPath) throw new Error('TikTok cần đường dẫn file trên server, không thể dùng tên file local');
        window._publishLastOutputPath = serverPath;
        window._procSelectedFile = item.file;
        await publishToTikTok(serverPath);
      }
      if (target === 'youtube' || target === 'both') {
        window._publishLastOutputPath = serverPath || item.name;
        window._ytLastOutputPath = serverPath || item.name;
        window._procSelectedFile = item.file;
        await uploadToYouTube(videoInput);
      }
      if (statusEl) statusEl.textContent = '✓ Xong';
      // Remove from queue after success
      _procFileQueueRemove(item.id);
    } catch (e) {
      if (statusEl) statusEl.textContent = '✗ Lỗi';
      _appendPublishLog(`✗ ${item.name}: ${e.message || e}`, 'error');
    }
  }
}

/* ── Version / Auto-update ──────────────────────────────────────────────── */
let _versionData = null;

function loadVersionInfo() {
  fetch('/api/version')
    .then(r => r.json())
    .then(data => {
      _versionData = data;
      const verEl = document.getElementById('sidebar-version-text');
      const dotEl = document.getElementById('sidebar-update-dot');
      if (verEl) {
        verEl.textContent = 'v' + data.current_version;
        verEl.style.color = 'var(--text2)';
      }
      if (data.update_available) {
        if (dotEl) dotEl.style.display = 'inline-block';
        if (verEl) {
          verEl.style.color = '#10b981';
          verEl.style.fontWeight = '700';
        }
        // Show toast notification
        toast(
          'Co ban cap nhat moi: v' + data.latest_version + ' — Bam vao v' + data.current_version + ' o goc trai de tai ve!',
          'info',
          10000
        );
      }
    })
    .catch(() => {
      const verEl = document.getElementById('sidebar-version-text');
      if (verEl) verEl.textContent = 'v?';
    });
}

function checkForUpdate() {
  const verEl = document.getElementById('sidebar-version-text');
  if (verEl) {
    verEl.textContent = '...';
    verEl.style.color = 'var(--accent)';
  }

  fetch('/api/version')
    .then(r => r.json())
    .then(data => {
      _versionData = data;
      const dotEl = document.getElementById('sidebar-update-dot');

      if (data.update_available) {
        if (verEl) {
          verEl.textContent = 'v' + data.current_version;
          verEl.style.color = '#10b981';
          verEl.style.fontWeight = '700';
        }
        if (dotEl) dotEl.style.display = 'inline-block';

        const msg = data.message || 'Co phien ban moi';
        const confirmed = confirm(
          '🆕 Co ban cap nhat moi!\n\n' +
          'Hien tai: v' + data.current_version + '\n' +
          'Moi nhat: v' + data.latest_version + '\n\n' +
          msg + '\n\n' +
          'Ban co muon tai ve ngay bay gio?'
        );
        if (confirmed && data.download_url) {
          window.open(data.download_url, '_blank');
        }
      } else {
        if (verEl) {
          verEl.textContent = 'v' + data.current_version;
          verEl.style.color = 'var(--text2)';
          verEl.style.fontWeight = '500';
        }
        if (dotEl) dotEl.style.display = 'none';
        toast('Ban dang dung phien ban moi nhat v' + data.current_version, 'success', 3000);
      }
    })
    .catch(err => {
      if (verEl) {
        verEl.textContent = 'v?';
        verEl.style.color = 'var(--error)';
        verEl.style.fontWeight = '500';
      }
      toast('Khong the kiem tra cap nhat: ' + (err.message || 'Loi mang'), 'error', 4000);
    });
}

// ── DOM ready ──────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  applyI18n();
  switchPage('user');
  document.getElementById('manual-url')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') addManualUrl();
  });
  _initUserPageListeners();

  // Load version info on startup
  loadVersionInfo();

  document.getElementById('proc-file')?.addEventListener('change', async function() {
    const file = this.files && this.files[0] ? this.files[0] : null;
    window._procSelectedFile = file;
    window._procUploadedPath = null;
    const pathBox = document.getElementById('proc-video');
    const label = document.getElementById('proc-file-name');
    if (pathBox) pathBox.value = file ? file.name : '';
    if (label) label.textContent = file ? file.name : '--';
    this.value = '';

    // Upload file len server de lay path tuyet doi, tranh viec cac buoc sau doan Downloaded/<ten file>.
    if (file) {
      if (label) label.textContent = `${file.name} (đang upload...)`;
      window._procUploadPromise = (async () => {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch('/api/upload_process_video', { method: 'POST', body: fd });
        const data = await r.json();
        if (data.ok && data.path) {
          window._procUploadedPath = data.path;
          window._procSelectedFile = null;
          window._publishLastOutputPath = data.path;
          window._ytLastOutputPath = data.path;
          if (pathBox) pathBox.value = data.path;
          if (label) label.textContent = `${file.name} ✓ → ${data.dir}`;
        } else {
          if (label) label.textContent = `${file.name} ⚠ upload thất bại`;
          if (typeof toast === 'function') toast('Upload file thất bại: ' + (data.error || ''), 'error');
          throw new Error(data.error || 'Upload file thất bại');
        }
        return data.path;
      })();
      try {
        await window._procUploadPromise;
      } catch (e) {
        if (label) label.textContent = `${file.name} ⚠ ${e.message}`;
        if (typeof toast === 'function') toast('Lỗi upload: ' + e.message, 'error');
      } finally {
        window._procUploadPromise = null;
      }
    }
  });

  document.getElementById('proc-tts-engine')?.addEventListener('change', function() {
    _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
  });
  document.getElementById('proc-target-lang')?.addEventListener('change', function() {
    _onTargetLangChange();
  });
  document.getElementById('vp-tts-engine')?.addEventListener('change', function() {
    _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
  });
  _onTargetLangChange();
  _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');

  document.getElementById('tr-import-file')?.addEventListener('change', function() {
    const file = this.files && this.files[0] ? this.files[0] : null;
    window._trSelectedFile = file;
    window._trAssPreviewText = '';
    const singleInput = document.getElementById('tr-file');
    const nameLabel = document.getElementById('tr-file-name');
    const previewInput = document.getElementById('tr-preview-text');
    if (singleInput && file) {
      singleInput.value = '';
      singleInput.placeholder = file.name;
    }
    if (nameLabel) nameLabel.textContent = file ? file.name : '--';

    if (previewInput && file && String(file.name || '').toLowerCase().endsWith('.ass')) {
      const reader = new FileReader();
      reader.onload = () => {
        const content = typeof reader.result === 'string' ? reader.result : '';
        const extracted = _extractPreviewTextFromAss(content, 2);
        if (extracted) {
          window._trAssPreviewText = extracted;
          previewInput.value = extracted;
        }
      };
      reader.readAsText(file, 'utf-8');
    }
  });

  // Clear selected file when user manually types a path
  document.getElementById('tr-file')?.addEventListener('input', function() {
    if (this.value.trim()) {
      window._trSelectedFile = null;
      const nameLabel = document.getElementById('tr-file-name');
      if (nameLabel) nameLabel.textContent = '--';
      const fileInput = document.getElementById('tr-import-file');
      if (fileInput) fileInput.value = '';
    }
  });

  document.getElementById('tr-tts-engine')?.addEventListener('change', function() {
    _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
  });
  document.getElementById('tr-tts-lang')?.addEventListener('change', function() {
    _ensureTtsEngineForLang('tr-tts-engine', this.value || 'vi');
    _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
    renderTranscribeVoiceLibrary();
  });
  _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
  initTranscribeVoiceManager();

  setProcessMode(window._procMode || 'ai');

  // Toggle voice options visibility
  document.getElementById('proc-voice')?.addEventListener('change', function() {
    const opts = document.getElementById('proc-voice-opts');
    if (opts) opts.style.display = this.checked ? 'block' : 'none';
  });

  const previewInput = document.getElementById('tr-preview-text');
  if (previewInput && !previewInput.value) {
    previewInput.value = 'Xin chào, đây là phần nghe thử giọng tiếng Việt.';
  }

  // Publish integration
  loadPublishSettings();
  checkYouTubeAuth();
  checkTikTokAuth();
  document.getElementById('publish-platform')?.addEventListener('change', function() {
    switchPublishPlatform(this.value || 'youtube');
  });
  document.getElementById('publish-auto-upload')?.addEventListener('change', function() {
    const status = document.getElementById('publish-status');
    if (status) status.textContent = this.checked ? 'Tự động bật' : 'Tự động tắt';
  });
  switchPublishPlatform(localStorage.getItem('publish_platform') || 'youtube');

  _initProcessConfigSync();
});

/* ── Synchronization between Process and Config ─────────────────────────── */
function _initProcessConfigSync() {
  const mapping = [
    { proc: 'proc-model', cfg: 'vp-model' },
    { proc: 'proc-lang', cfg: 'vp-lang' },
    { proc: 'proc-burn', cfg: 'vp-burn', type: 'checkbox' },
    { proc: 'proc-translate-subs', cfg: 'vp-translate', type: 'checkbox' },
    { proc: 'proc-burn-vi', cfg: 'vp-burn-vi', type: 'checkbox' },
    { proc: 'proc-voice', cfg: 'vp-voice', type: 'checkbox' },
    { proc: 'proc-keep-bg', cfg: 'vp-keep-bg', type: 'checkbox' },
    { proc: 'proc-tts-voice', cfg: 'vp-tts-voice' },
    { proc: 'proc-font-size', cfg: 'vp-font-size' },
    { proc: 'proc-blur-original', cfg: 'vp-blur-original', type: 'checkbox' },
    { proc: 'proc-tts-engine', cfg: 'vp-tts-engine' },
    { proc: 'proc-bg-vol', cfg: 'vp-bg-volume' },
    { proc: 'proc-tts-pitch', cfg: 'vp-tts-pitch' },
    { proc: 'proc-tts-rate', cfg: 'vp-tts-rate' },
    { proc: 'proc-tts-emotion', cfg: 'vp-tts-emotion' },
  ];

  mapping.forEach(m => {
    const pEl = document.getElementById(m.proc);
    const cEl = document.getElementById(m.cfg);
    if (!pEl || !cEl) return;

    const sync = (src, dest) => {
      const val = m.type === 'checkbox' ? src.checked : src.value;
      const cur = m.type === 'checkbox' ? dest.checked : dest.value;
      if (val === cur) return; // Ngăn chặn vòng lặp vô tận

      if (m.type === 'checkbox') dest.checked = val;
      else dest.value = val;
      dest.dispatchEvent(new Event('change'));
    };

    pEl.addEventListener('change', () => sync(pEl, cEl));
    cEl.addEventListener('change', () => sync(cEl, pEl));
  });
}

function syncProcessConfigFromLoaded() {
  const mapping = [
    { proc: 'proc-model', cfg: 'vp-model' },
    { proc: 'proc-lang', cfg: 'vp-lang' },
    { proc: 'proc-burn', cfg: 'vp-burn', type: 'checkbox' },
    { proc: 'proc-translate-subs', cfg: 'vp-translate', type: 'checkbox' },
    { proc: 'proc-burn-vi', cfg: 'vp-burn-vi', type: 'checkbox' },
    { proc: 'proc-voice', cfg: 'vp-voice', type: 'checkbox' },
    { proc: 'proc-keep-bg', cfg: 'vp-keep-bg', type: 'checkbox' },
    { proc: 'proc-tts-voice', cfg: 'vp-tts-voice' },
    { proc: 'proc-font-size', cfg: 'vp-font-size' },
    { proc: 'proc-blur-original', cfg: 'vp-blur-original', type: 'checkbox' },
    { proc: 'proc-tts-engine', cfg: 'vp-tts-engine' },
    { proc: 'proc-bg-vol', cfg: 'vp-bg-volume' },
    { proc: 'proc-tts-pitch', cfg: 'vp-tts-pitch' },
    { proc: 'proc-tts-rate', cfg: 'vp-tts-rate' },
    { proc: 'proc-tts-emotion', cfg: 'vp-tts-emotion' },
  ];

  mapping.forEach(m => {
    const pEl = document.getElementById(m.proc);
    const cEl = document.getElementById(m.cfg);
    if (pEl && cEl) {
      if (m.type === 'checkbox') pEl.checked = cEl.checked;
      else pEl.value = cEl.value;
      pEl.dispatchEvent(new Event('change'));
    }
  });
}

/* ── Publish Upload ─────────────────────────────────────────────────────── */
window._publishLastOutputPath = null;
window._ytAuthenticated = false;
window._ttAuthenticated = false;
window._publishPlatform = localStorage.getItem('publish_platform') || 'youtube';

function loadPublishSettings() {
  const platform = localStorage.getItem('publish_platform') || 'youtube';
  const autoUpload = localStorage.getItem('publish_auto_upload') === 'true';
  const setVal = (id, val) => { const el = document.getElementById(id); if (el && val !== null && val !== undefined) el.value = val; };
  const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };

  setVal('publish-platform', platform);
  setChk('publish-auto-upload', autoUpload);

  // Use config defaults when present, but allow local edits to stay in place.
  API.get('/api/config').then(cfg => {
    const upload = cfg?.upload || {};
    if (upload.platform && !localStorage.getItem('publish_platform')) {
      setVal('publish-platform', upload.platform);
      switchPublishPlatform(upload.platform);
    }
    if (upload.auto_upload !== undefined && localStorage.getItem('publish_auto_upload') === null) {
      setChk('publish-auto-upload', upload.auto_upload);
    }
    setVal('yt-title', upload.youtube?.title_template || document.getElementById('yt-title')?.value || '');
    setVal('yt-desc', upload.youtube?.description_template || document.getElementById('yt-desc')?.value || '');
    setVal('yt-privacy', upload.youtube?.privacy_status || document.getElementById('yt-privacy')?.value || 'private');
    setVal('tt-title', upload.tiktok?.title_template || document.getElementById('tt-title')?.value || '');
    setVal('tt-privacy', upload.tiktok?.privacy_status || document.getElementById('tt-privacy')?.value || 'public');
  }).catch(() => {});
}

function switchPublishPlatform(platform) {
  const normalized = platform === 'tiktok' ? 'tiktok' : platform === 'both' ? 'both' : 'youtube';
  window._publishPlatform = normalized;
  localStorage.setItem('publish_platform', normalized);

  const ytPanel = document.getElementById('publish-youtube-panel');
  const ttPanel = document.getElementById('publish-tiktok-panel');
  const status = document.getElementById('publish-status');
  const platformSelect = document.getElementById('publish-platform');

  if (platformSelect && platformSelect.value !== normalized) platformSelect.value = normalized;
  if (ytPanel) ytPanel.style.display = (normalized === 'youtube' || normalized === 'both') ? 'block' : 'none';
  if (ttPanel) ttPanel.style.display = (normalized === 'tiktok' || normalized === 'both') ? 'block' : 'none';
  if (status) status.textContent = normalized === 'youtube' ? 'YouTube' : normalized === 'tiktok' ? 'TikTok' : 'TikTok + YouTube';
}

function _getPublishAutoUpload() {
  return document.getElementById('publish-auto-upload')?.checked || false;
}

function _renderPublishTemplate(template, values) {
  const source = String(template || '').trim();
  if (!source) return '';
  return source.replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key) => {
    const value = values && Object.prototype.hasOwnProperty.call(values, key) ? values[key] : '';
    return value === null || value === undefined ? '' : String(value);
  }).trim();
}

function _cleanStemToTitle(stem) {
  // Remove extension
  let t = stem.replace(/\.[^/.]+$/, '');
  // Remove trailing _vi_voice, _voice, _vi suffixes
  t = t.replace(/_(vi_voice|voice|vi)$/i, '');
  // Remove date prefix like 2024-01-15_
  t = t.replace(/^\d{4}-\d{2}-\d{2}_/, '');
  // Remove aweme_id suffix (long numeric id at end)
  t = t.replace(/_\d{15,}$/, '');
  // Split off Chinese characters into separate part
  const chineseMatch = t.match(/[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F_]*/g);
  // Remove Chinese segments from title
  t = t.replace(/[\u4e00-\u9fff\u3400-\u4dbf][^\u0000-\u007F]*/g, '').replace(/_+/g, ' ').trim();
  return { title: t, chineseParts: chineseMatch || [] };
}

async function _buildPublishTitleAndTags(platform, fallbackPath) {
  const stem = (fallbackPath || '').split(/[\\/]/).pop() || '';
  const inputId = platform === 'tiktok' ? 'tt-title' : 'yt-title';
  const raw = (document.getElementById(inputId)?.value || '').trim();
  const { title: baseTitle, chineseParts } = _cleanStemToTitle(stem);

  const finalTitle = _renderPublishTemplate(raw || '{title}', {
    title: baseTitle, filename: stem, platform,
  }) || baseTitle;

  // Translate Chinese parts to hashtags
  let hashtags = [];
  if (chineseParts.length > 0) {
    try {
      const res = await fetch('/api/translate_batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: chineseParts }),
      });
      const data = await res.json();
      hashtags = (data.results || chineseParts).map(s =>
        '#' + s.trim().toLowerCase().replace(/\s+/g, '')
      ).filter(h => h.length > 1);
    } catch (_) {
      // fallback: use Chinese as-is
      hashtags = chineseParts.map(s => '#' + s.trim().replace(/\s+/g, ''));
    }
  }

  return { title: finalTitle, hashtags };
}

function _getPublishTitle(platform, fallbackPath) {
  const stem = (fallbackPath || '').split(/[\\/]/).pop() || '';
  const inputId = platform === 'tiktok' ? 'tt-title' : 'yt-title';
  const raw = (document.getElementById(inputId)?.value || '').trim();
  const { title: baseTitle } = _cleanStemToTitle(stem);
  return _renderPublishTemplate(raw || '{title}', {
    title: baseTitle, filename: stem, platform,
  }) || baseTitle;
}

function _getPublishDescription(platform) {
  const inputId = platform === 'tiktok' ? 'tt-title' : 'yt-desc';
  const raw = (document.getElementById(inputId)?.value || '').trim();
  const baseTitle = _getPublishTitle(platform, window._publishLastOutputPath || window._ytLastOutputPath || '');
  return _renderPublishTemplate(raw || '{title}', {
    title: baseTitle,
    filename: (window._publishLastOutputPath || window._ytLastOutputPath || '').split(/[\\/]/).pop() || baseTitle,
    platform,
  });
}

function _getPublishPrivacy(platform) {
  const inputId = platform === 'tiktok' ? 'tt-privacy' : 'yt-privacy';
  return (document.getElementById(inputId)?.value || (platform === 'tiktok' ? 'public' : 'private')).trim();
}

function _getPublishTags() {
  return (document.getElementById('tt-tags')?.value || '').trim();
}

function _appendPublishLog(msg, level) {
  const box = document.getElementById('publish-log');
  if (!box) return;
  box.style.display = 'block';
  const line = document.createElement('div');
  line.className = 'log-' + (level || 'info');
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  line.textContent = `[${ts}] ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function _setPublishStatus(text) {
  const status = document.getElementById('publish-status');
  if (status) status.textContent = text;
}

function _toYouTubeUserHint(err) {
  const raw = String(err?.message || err || '').trim();
  const low = raw.toLowerCase();

  if (low.includes('client_secrets.json not found')) {
    return 'Thiếu file client_secrets.json ở thư mục gốc dự án.';
  }
  if (low.includes('redirect_uri_mismatch')) {
    return 'Sai Redirect URI trên Google Cloud. Cần thêm: http://localhost:8080/oauth2callback';
  }
  if (low.includes('access blocked') || low.includes('app isn\'t verified')) {
    return 'Ứng dụng OAuth đang bị chặn/chưa verify. Hãy thêm tài khoản vào Test users trong Google Cloud.';
  }
  if (low.includes('missing dependency') || low.includes('no module named')) {
    return 'Thiếu thư viện YouTube OAuth. Chạy: pip install -r requirements.txt';
  }
  if (low.includes('server trả về dữ liệu không phải json')) {
    return 'Backend đang lỗi nội bộ hoặc chưa chạy đúng cổng. Kiểm tra log app.py.';
  }
  return raw || 'Không thể kết nối YouTube. Kiểm tra cấu hình OAuth và thử lại.';
}

function _showYouTubeError(err, prefix) {
  const hint = _toYouTubeUserHint(err);
  const pfx = prefix || 'Lỗi kết nối YouTube';
  toast(pfx + ': ' + hint, 'error');
  _appendPublishLog(pfx + ': ' + hint, 'error');
  const status = document.getElementById('yt-status');
  if (status) status.textContent = 'Lỗi kết nối';
}

async function checkYouTubeAuth() {
  try {
    // Use plain fetch (not API.get) to avoid showing loading overlay
    const r = await fetch('/api/youtube_auth');
    if (!r.ok) { _setYouTubeAuthenticated(false, null); return; }
    const res = await r.json();
    if (res?.authenticated) {
      _setYouTubeAuthenticated(true, res.channel);
    } else {
      _setYouTubeAuthenticated(false, null);
    }
  } catch (e) {
    console.warn('YouTube auth check failed:', e);
    _setYouTubeAuthenticated(false, null);
  }
}

function _setYouTubeAuthenticated(authenticated, channel) {
  window._ytAuthenticated = authenticated;

  const disconnected = document.getElementById('yt-auth-disconnected');
  const connected    = document.getElementById('yt-auth-connected');

  if (authenticated && channel) {
    if (disconnected) disconnected.style.display = 'none';
    if (connected)    connected.style.display    = 'flex';

    // Channel name
    const nameEl = document.getElementById('yt-ch-name');
    if (nameEl) nameEl.textContent = channel.title || '--';

    // Subscribers
    const subsEl = document.getElementById('yt-ch-subs');
    if (subsEl) {
      const n = parseInt(channel.subscribers || 0);
      subsEl.textContent = n >= 1000 ? (n / 1000).toFixed(1) + 'K' : (n || 'Ẩn');
    }

    // Video count
    const vidEl = document.getElementById('yt-ch-videos');
    if (vidEl) vidEl.textContent = channel.video_count || '0';

    // Avatar
    const avatarImg = document.getElementById('yt-ch-avatar-img');
    const avatarPh  = document.getElementById('yt-ch-avatar-ph');
    if (avatarImg && channel.thumbnail) {
      avatarImg.src = channel.thumbnail;
      avatarImg.style.display = 'block';
      if (avatarPh) avatarPh.style.display = 'none';
    } else {
      if (avatarImg) avatarImg.style.display = 'none';
      if (avatarPh)  avatarPh.style.display  = 'flex';
    }

    // Sync channel info into accounts registry so dropdowns show real name
    if (channel.title && typeof _refreshYouTubeChannelInfo === 'function') {
      _refreshYouTubeChannelInfo();
    }
  } else {
    if (disconnected) disconnected.style.display = 'flex';
    if (connected)    connected.style.display    = 'none';
  }
}

async function youtubeLogin() {
  const btn = document.getElementById('btn-yt-auth');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang kết nối...';
  }

  try {
    const res = await API.post('/api/youtube_auth', {});
    if (res?.authenticated) {
      _setYouTubeAuthenticated(true, res.channel);
      toast('Đã kết nối với YouTube', 'success');
    } else if (res?.auth_url) {
      toast('Vui lòng mở link để đăng nhập YouTube', 'info');
      const popup = window.open(res.auth_url, 'youtube_auth', 'width=680,height=720');
      let tries = 0;
      const timer = setInterval(async () => {
        tries += 1;
        // Stop immediately if popup closed or max tries reached
        if ((popup && popup.closed) || tries >= 60) { clearInterval(timer); return; }
        await checkYouTubeAuth();
        if (window._ytAuthenticated) { clearInterval(timer); }
      }, 2000);
    }
  } catch (e) {
    _showYouTubeError(e, 'Lỗi kết nối YouTube');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Đăng nhập YouTube';
    }
  }
}

async function youtubeLogout() {
  if (!confirm('Xác nhận đăng xuất YouTube?')) return;
  
  try {
    await API.post('/api/youtube_logout', {});
    _setYouTubeAuthenticated(false, null);
    toast('Đã đăng xuất YouTube', 'info');
  } catch (e) {
    toast('Lỗi đăng xuất: ' + e.message, 'error');
  }
}

function _toTikTokUserHint(err) {
  const raw = String(err?.message || err || '').trim();
  const low = raw.toLowerCase();

  if (low.includes('missing tiktok client_key/client_secret')) {
    return 'Thiếu TikTok client_key/client_secret trong cấu hình upload.tiktok.';
  }
  if (low.includes('oauth') || low.includes('auth')) {
    return raw || 'Không thể xác thực TikTok. Kiểm tra Client Key/Secret và Redirect URI.';
  }
  return raw || 'Không thể kết nối TikTok API. Kiểm tra cấu hình và thử lại.';
}

function _showTikTokError(err, prefix) {
  const hint = _toTikTokUserHint(err);
  const pfx = prefix || 'Lỗi kết nối TikTok';
  toast(pfx + ': ' + hint, 'error');
  _appendPublishLog(pfx + ': ' + hint, 'error');
  const status = document.getElementById('publish-status');
  if (status && (window._publishPlatform || '') === 'tiktok') status.textContent = 'Lỗi TikTok';
}

function _setTikTokAuthenticated(authenticated, account) {
  window._ttAuthenticated = !!authenticated;
  const authBtn = document.getElementById('btn-tt-auth');
  const logoutBtn = document.getElementById('btn-tt-logout');
  const accountInfo = document.getElementById('tt-account-info');
  const authNeeded = document.getElementById('tt-auth-needed');

  if (window._ttAuthenticated) {
    if (authBtn) authBtn.style.display = 'none';
    if (logoutBtn) logoutBtn.style.display = 'inline-block';
    if (accountInfo) {
      accountInfo.style.display = 'block';
      const openid = document.getElementById('tt-account-openid');
      const scope = document.getElementById('tt-account-scope');
      if (openid) openid.textContent = account?.open_id || '--';
      if (scope) scope.textContent = account?.scope || '--';
    }
    if (authNeeded) authNeeded.style.display = 'none';
  } else {
    if (authBtn) authBtn.style.display = 'inline-block';
    if (logoutBtn) logoutBtn.style.display = 'none';
    if (accountInfo) accountInfo.style.display = 'none';
    if (authNeeded) authNeeded.style.display = 'block';
  }
}

async function checkTikTokAuth() {
  try {
    // Use plain fetch (not API.get) to avoid showing loading overlay
    const r = await fetch('/api/tiktok_auth');
    if (!r.ok) { _setTikTokAuthenticated(false, null); return; }
    const res = await r.json();
    if (res?.authenticated) {
      _setTikTokAuthenticated(true, res.account || {});
    } else {
      _setTikTokAuthenticated(false, null);
    }
  } catch (e) {
    console.warn('TikTok auth check failed:', e);
    _setTikTokAuthenticated(false, null);
  }
}

async function tiktokLogin() {
  const btn = document.getElementById('btn-tt-auth');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang kết nối...';
  }

  try {
    const res = await API.post('/api/tiktok_auth', {});
    if (res?.authenticated) {
      _setTikTokAuthenticated(true, res.account || {});
      toast('Đã kết nối TikTok', 'success');
    } else if (res?.auth_url) {
      toast('Vui lòng mở link để đăng nhập TikTok', 'info');
      const popup = window.open(res.auth_url, 'tiktok_auth', 'width=680,height=720');
      let tries = 0;
      const timer = setInterval(async () => {
        tries += 1;
        await checkTikTokAuth();
        if (window._ttAuthenticated || (popup && popup.closed) || tries >= 60) {
          clearInterval(timer);
        }
      }, 2000);
    }
  } catch (e) {
    _showTikTokError(e, 'Lỗi kết nối TikTok');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Đăng nhập TikTok';
    }
  }
}

async function tiktokLogout() {
  if (!confirm('Xác nhận đăng xuất TikTok?')) return;

  try {
    await API.post('/api/tiktok_logout', {});
    _setTikTokAuthenticated(false, null);
    toast('Đã đăng xuất TikTok', 'info');
  } catch (e) {
    _showTikTokError(e, 'Lỗi đăng xuất TikTok');
  }
}

async function _publishToYouTubeManual(videoInput) {
  const videoPath = typeof videoInput === 'string' ? videoInput.trim() : (videoInput?.name || '').trim();
  const title = _getPublishTitle('youtube', videoPath);
  const description = _getPublishDescription('youtube');
  const tags = ['douyin', 'tiktok', 'video'].join(', ');

  try {
    const clip = [
      `Title: ${title}`,
      description ? `Description:\n${description}` : '',
      `Tags: ${tags}`,
    ].filter(Boolean).join('\n\n');
    if (clip && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(clip);
    }
  } catch (_) {}

  _setPublishStatus('Đăng YouTube thủ công');
  _appendPublishLog('Chuyển sang chế độ đăng YouTube thủ công (không dùng OAuth API).', 'warning');
  _appendPublishLog('Đã sao chép title/description/tags vào clipboard.', 'info');
  if (videoPath) {
    _appendPublishLog(`File cần đăng: ${videoPath}`, 'info');
  }
  _appendPublishLog('Đang mở trang upload YouTube...', 'info');
  _appendPublishLog('Bước tiếp theo: chọn file video, dán mô tả đã copy (Ctrl+V), rồi bấm Publish.', 'info');
  toast('Đã chuyển sang đăng thủ công. Dữ liệu đã copy clipboard.', 'info');
  window.open('https://www.youtube.com/upload', '_blank');
}

async function uploadToYouTube(videoInput) {
  if (!window._ytAuthenticated) {
    await _publishToYouTubeManual(videoInput);
    return;
  }

  let isFileInput = typeof File !== 'undefined' && videoInput instanceof File;
  let videoPath = isFileInput ? videoInput.name : String(videoInput || '').trim();
  if (isFileInput && typeof window._pubUploadVideoFileToServer === 'function') {
    try {
      videoPath = await window._pubUploadVideoFileToServer(videoInput);
      videoInput = videoPath;
      isFileInput = false;
    } catch (_) {
      videoPath = videoInput.name;
    }
  }

  if (!videoPath) {
    alert('Không có video để upload');
    return;
  }

  const title = _getPublishTitle('youtube', videoPath);
  if (!title) {
    alert('Vui lòng nhập tiêu đề');
    return;
  }

  // Build hashtags from filename
  const { hashtags } = await _buildPublishTitleAndTags('youtube', videoPath);
  const defaultTags = ['douyin', 'tiktok', 'video'];
  const allTags = [...new Set([...defaultTags, ...hashtags.map(h => h.slice(1))])]; // remove #

  const logBox = document.getElementById('publish-log');
  if (logBox) {
    logBox.innerHTML = '';
    logBox.style.display = 'block';
  }

  _setPublishStatus('Đang đăng YouTube...');
  _appendPublishLog('Bắt đầu upload lên YouTube...', 'info');

  try {
    const payload = {
      title: title,
      description: _getPublishDescription('youtube'),
      tags: allTags,
      privacy_status: _getPublishPrivacy('youtube'),
    };

    const requestOptions = isFileInput
      ? (() => {
          const form = new FormData();
          form.append('video_file', videoInput, videoInput.name);
          form.append('title', payload.title);
          form.append('description', payload.description);
          form.append('tags', JSON.stringify(payload.tags));
          form.append('privacy_status', payload.privacy_status);
          return { method: 'POST', body: form };
        })()
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ video_path: videoPath, ...payload }),
        };

    const res = await fetch('/api/youtube_upload', requestOptions);

    if (!res.ok) {
      let msg = 'Upload thất bại';
      try { msg = (await res.json())?.error || msg; } catch (_) {}
      throw new Error(msg);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          if (data.status === 'uploading' && typeof data.pct === 'number') {
            _appendPublishLog(`Đang upload YouTube... ${data.pct}%`, 'info');
          }
          if (data.log) _appendPublishLog(data.log, data.level || 'info');
          if (data.status === 'success' && data.url) {
            _setPublishStatus('Đã đăng YouTube');
            toast(`✓ Upload thành công! ${data.url}`, 'success');
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    const msg = String(e?.message || e || '').toLowerCase();
    if (msg.includes('insecure_transport') || msg.includes('not authenticated')) {
      await _publishToYouTubeManual(videoInput);
      return;
    }
    _setPublishStatus('Lỗi YouTube');
    _appendPublishLog('✗ Lỗi: ' + e.message, 'error');
    toast('Upload thất bại: ' + e.message, 'error');
  }
}

async function publishToTikTok(videoInput) {
  let videoPath = typeof videoInput === 'string' ? videoInput.trim() : '';
  if (!videoPath && typeof File !== 'undefined' && videoInput instanceof File && typeof window._pubUploadVideoFileToServer === 'function') {
    try {
      videoPath = await window._pubUploadVideoFileToServer(videoInput);
    } catch (e) {
      toast('Không import được video để đăng TikTok: ' + (e.message || e), 'error');
      return;
    }
  }
  if (!videoPath && videoInput?.name) videoPath = videoInput.name.trim();
  if (!videoPath) {
    alert('Không có video để đăng');
    return;
  }

  if (!window._ttAuthenticated) {
    toast('Bạn chưa đăng nhập TikTok. Vui lòng đăng nhập trước.', 'error');
    _appendPublishLog('✗ Chưa đăng nhập TikTok API. Nhấn "Đăng nhập TikTok" trước.', 'error');
    return;
  }

  const { title, hashtags } = await _buildPublishTitleAndTags('tiktok', videoPath);
  const privacy = _getPublishPrivacy('tiktok');

  // Auto-fill hashtag field so user can see/edit
  const tagsEl = document.getElementById('tt-tags');
  if (tagsEl && !tagsEl.value.trim() && hashtags.length) {
    tagsEl.value = hashtags.join(' ');
  }
  const manualTags = (document.getElementById('tt-tags')?.value || '').trim()
    .split(/\s+/).filter(t => t.startsWith('#'));
  const allTags = [...new Set([...hashtags, ...manualTags])];

  // Append hashtags to title for TikTok caption (max 150 chars total)
  const hashtagStr = allTags.join(' ');
  const caption = hashtagStr ? `${title} ${hashtagStr}`.slice(0, 150) : title.slice(0, 150);

  const logBox = document.getElementById('publish-log');
  if (logBox) { logBox.innerHTML = ''; logBox.style.display = 'block'; }

  _setPublishStatus('Đang đăng TikTok...');
  _appendPublishLog('Bắt đầu upload lên TikTok...', 'info');

  try {
    const res = await fetch('/api/tiktok_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_path: videoPath, title: caption, privacy_level: privacy.toUpperCase() }),
    });

    if (!res.ok) {
      let msg = 'Upload thất bại';
      try { msg = (await res.json())?.error || msg; } catch (_) {}
      throw new Error(msg);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          if (data.log) _appendPublishLog(data.log, data.level || 'info');
          if (data.publish_id) {
            _setPublishStatus('✓ Đã đăng TikTok');
            toast('✓ Upload TikTok thành công!', 'success');
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    _setPublishStatus('Lỗi TikTok');
    _appendPublishLog('✗ Lỗi: ' + (e.message || e), 'error');
    toast('Upload TikTok thất bại: ' + (e.message || e), 'error');
  }
}

async function savePublishSettings() {
  try {
    const current = await API.get('/api/config') || {};
    const payload = {
      translation: {
        ...(current.translation || {}),
        naming_enabled: true,
      },
      upload: {
        platform: document.getElementById('publish-platform')?.value || 'youtube',
        auto_upload: _getPublishAutoUpload(),
        youtube: {
          title_template: document.getElementById('yt-title')?.value || '{title}',
          description_template: document.getElementById('yt-desc')?.value || '{title}',
          privacy_status: document.getElementById('yt-privacy')?.value || 'private',
        },
        tiktok: {
          title_template: document.getElementById('tt-title')?.value || '{title}',
          privacy_status: document.getElementById('tt-privacy')?.value || 'public',
        },
      },
    };
    await API.post('/api/config', payload);
    localStorage.setItem('publish_auto_upload', String(_getPublishAutoUpload()));
    toast('Đã lưu cấu hình đăng', 'success');
  } catch (e) {
    toast('Không lưu được cấu hình: ' + e.message, 'error');
  }
}

async function publishBothOrSingle(target) {
  let videoPath = window._publishLastOutputPath || window._ytLastOutputPath || '';
  let videoInput = videoPath || window._procSelectedFile || '';
  if (!videoPath && window._procSelectedFile && typeof window._pubUploadVideoFileToServer === 'function') {
    try {
      videoPath = await window._pubUploadVideoFileToServer(window._procSelectedFile);
      videoInput = videoPath;
    } catch (_) {
      videoInput = window._procSelectedFile;
    }
  }
  if (!videoInput) {
    toast('Chưa có file đầu ra để đăng', 'warning');
    return;
  }

  const logBox = document.getElementById('publish-log');
  if (logBox) { logBox.innerHTML = ''; logBox.style.display = 'block'; }

  const t = target || window._publishPlatform || 'youtube';
  if (t === 'tiktok' || t === 'both') await publishToTikTok(videoPath || videoInput);
  if (t === 'youtube' || t === 'both') await uploadToYouTube(videoPath || videoInput);
}

async function publishSelectedPlatform() {
  const platform = window._publishPlatform || document.getElementById('publish-platform')?.value || 'youtube';
  if (window._procFileQueue.length) {
    await publishQueueToTarget(platform);
  } else {
    await publishBothOrSingle(platform);
  }
}
async function previewConfigVoice() {
  const text = 'Xin chào, đây là phần nghe thử giọng đọc từ cấu hình.';
  const btn = document.querySelector('button[onclick="previewConfigVoice()"]');
  const audio = document.getElementById('vp-preview-audio');
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
        ..._resolveTtsEngineVoice('vp'),
        tts_pitch: _sanitizeVoiceParam(document.getElementById('vp-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('vp-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('vp-tts-emotion')?.value || 'default',
        hf_model: document.getElementById('vp-hf-model')?.value || undefined,
        hf_device: document.getElementById('vp-hf-device')?.value || undefined,
        hf_embeddings: document.getElementById('vp-hf-embeddings')?.value || undefined,
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
      audio.play();
    }
  } catch (err) {
    alert('Lỗi preview giọng: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
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

/* ── Upload Overlay Image ───────────────────────────────────────────────── */
async function uploadOverlay(input, type) {
  const file = input?.files?.[0];
  if (!file) return;

  const form = new FormData();
  form.append('file', file);
  form.append('type', type || 'overlay');

  try {
    const res = await fetch('/api/upload_anti_fp_image', { method: 'POST', body: form });
    if (!res.ok) throw new Error('Upload thất bại');
    const data = await res.json();
    if (data.path) {
      // Fill path into all AFP overlay inputs
      const imgInputs = ['proc-afp-overlay-img', 'vp-afp-overlay-img'];
      imgInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = data.path;
      });
      toast('✓ Đã upload: ' + file.name, 'success');
    }
  } catch (err) {
    alert('Lỗi upload ảnh: ' + err.message);
  }
  input.value = '';
}

/* ── HuggingFace Voice Management ───────────────────────────────────────── */
async function refreshHfVoices() {
  try {
    const res = await fetch('/api/hf_voices');
    if (!res.ok) return;
    const data = await res.json();
    const voices = Array.isArray(data?.voices) ? data.voices : [];
    
    ['vp-hf-embeddings', 'tr-hf-embeddings', 'proc-hf-embeddings'].forEach(id => {
      const select = document.getElementById(id);
      if (!select) return;
      const current = select.value;
      select.innerHTML = '<option value="">(Không dùng / Mặc định)</option>';
      voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.path;
        opt.textContent = v.name;
        select.appendChild(opt);
      });
      if (Array.from(select.options || []).some(o => o.value === current)) {
        select.value = current;
      }
    });
  } catch (err) {
    // HF voices not available - silently ignore
  }
}

async function uploadHfVoice() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'audio/*';
  input.onchange = async () => {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];
    const defaultName = file.name.replace(/\.[^/.]+$/, "");
    const name = prompt('Nhập tên cho giọng này để lưu (ví dụ: giong_cua_toi):', defaultName);
    if (!name) return;
    
    toast('Đang xử lý phân tách giọng (sẽ mất khoảng vài giây)...', 'info');
    
    const formData = new FormData();
    formData.append('audio', file);
    formData.append('name', name);
    
    try {
      const res = await fetch('/api/hf_voices/upload', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Server error');
      
      toast('Tạo bản thu giọng clone thành công!', 'success');
      
      // Log to all possible log boxes
      ['proc-log', 'tr-log', 'dl-log'].forEach(l => {
        if (typeof appendLog === 'function') appendLog(l, 'Tạo giọng clone thành công: ' + name, 'success');
      });
      
      await refreshHfVoices();
      
      // Auto-select the newly created voice
      ['vp-hf-embeddings', 'tr-hf-embeddings', 'proc-hf-embeddings'].forEach(id => {
        const select = document.getElementById(id);
        if (select) select.value = data.path;
      });
    } catch (err) {
      alert('Lỗi tạo giọng: ' + err.message);
      ['proc-log', 'tr-log', 'dl-log'].forEach(l => {
        if (typeof appendLog === 'function') appendLog(l, 'Lỗi tạo giọng: ' + err.message, 'error');
      });
    }
  };
  input.click();
}

// Gọi tải danh sách khi tải xong script
setTimeout(refreshHfVoices, 500);

async function uploadVoiceCloneFile(inputEl) {
  if (!inputEl.files || !inputEl.files[0]) return;
  const file = inputEl.files[0];
  const name = file.name.replace(/\.[^/.]+$/, "");
  
  if (typeof toast === 'function') toast('Đang tải tệp âm thanh lên...', 'info');
  
  const formData = new FormData();
  formData.append('audio', file);
  formData.append('name', name);
  
  try {
    const res = await fetch('/api/voice_clone/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Server error');
    
    const refAudioEl = document.getElementById('tr-voice-ref-audio');
    if (refAudioEl) refAudioEl.value = data.path;
    if (typeof toast === 'function') toast('Tải tệp âm thanh clone thành công!', 'success');
  } catch (err) {
    alert('Lỗi tải tệp: ' + err.message);
  }
  inputEl.value = '';
}

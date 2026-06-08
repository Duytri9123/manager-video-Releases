/* ── app.js — Entry point ────────────────────────────────────────────────── */

window._trSelectedFile = null;

const TTS_VOICE_PRESETS = {
  'fpt-ai': [
    { value: 'banmai', label: 'Ban Mai (FPT - Nữ)' },
    { value: 'thuminh', label: 'Thu Minh (FPT - Nữ)' },
    { value: 'myan', label: 'My An (FPT - Nữ)' },
    { value: 'leminh', label: 'Le Minh (FPT - Nam)' },
  ],
  'edge-tts': [
    { value: 'vi-VN-HoaiMyNeural', label: 'Hoai My (Edge - Nữ)' },
    { value: 'vi-VN-NamMinhNeural', label: 'Nam Minh (Edge - Nam)' },
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
    { value: 'vi', label: 'Vietnamese (gTTS)' },
  ],
};

const TTS_DEFAULT_VOICE = {
  'fpt-ai':  'banmai',
  'edge-tts': 'vi-VN-HoaiMyNeural',
  'elevenlabs': '21m00Tcm4TlvDq8ikWAM',
  'minimax': 'Calm_Woman',
  gtts: 'vi',
};

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
  if (id.startsWith('tr-')) return document.getElementById('tr-lang')?.value || 'vi';
  if (id.startsWith('mv-')) return document.getElementById('mv-lang')?.value || 'vi';
  if (id.startsWith('vp-')) return 'vi';
  return document.getElementById('proc-target-lang')?.value || 'vi';
}

function _pickTtsEngineForLang(lang, currentId) {
  const catalog = TTS_ENGINE_CATALOG || [];
  const current = catalog.find(e => String(e.id || '').toLowerCase() === String(currentId || '').toLowerCase());
  if (current && _engineSupportsLang(current, lang)) return current;
  for (const id of ['edge-tts', 'gtts', 'elevenlabs', 'fpt-ai']) {
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
  const catalog = TTS_ENGINE_CATALOG || [];
  if (!catalog.length) return;
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
      // Mark selected nếu khớp với giá trị hiện tại hoặc fpt-ai là default
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
      const r = await fetch('/api/tts/engines');
      const j = await r.json();
      if (j?.ok && Array.isArray(j.engines) && j.engines.length) {
        TTS_ENGINE_CATALOG = j.engines;
        window._ttsNineRouterStatus = j.nine_router || {};
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
    { value: 'en-US-JennyNeural', label: 'Jenny (Female - US)' },
    { value: 'en-US-GuyNeural', label: 'Guy (Male - US)' },
    { value: 'en-US-AriaNeural', label: 'Aria (Female - US)' },
    { value: 'en-GB-SoniaNeural', label: 'Sonia (Female - UK)' },
  ],
  ja: [
    { value: 'ja-JP-NanamiNeural', label: 'Nanami (女性 - JP)' },
    { value: 'ja-JP-KeitaNeural', label: 'Keita (男性 - JP)' },
  ],
  ko: [
    { value: 'ko-KR-SunHiNeural', label: 'Sun-Hi (여성 - KR)' },
    { value: 'ko-KR-InJoonNeural', label: 'InJoon (남성 - KR)' },
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
    { value: 'zh-CN-YunxiNeural', label: 'Yunxi (男 - CN)' },
  ],
};

/* ── gTTS language codes ── */
const GTTS_BY_LANG = {
  vi: 'vi', en: 'en', ja: 'ja', ko: 'ko', th: 'th', id: 'id',
  es: 'es', pt: 'pt', fr: 'fr', de: 'de', ru: 'ru', ar: 'ar', hi: 'hi', zh: 'zh',
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
    const preset = _catalogVoicesToPreset(rawList);
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
    const voices = EDGE_TTS_BY_LANG[targetLang] || EDGE_TTS_BY_LANG['en'];
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

  const preset = engine === 'gtts' && GTTS_BY_LANG[targetLang]
    ? [{ value: GTTS_BY_LANG[targetLang], label: `${targetLang} (gTTS)` }]
    : (TTS_VOICE_PRESETS[engine] || TTS_VOICE_PRESETS['fpt-ai']);
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
    videogen:'Video AI', ai_studio:'AI Studio', n8n:'Điều phối n8n', sales:'Video bán hàng'
  };
  if (el) el.textContent = titles[name] || t('title_' + name) || name;
  if (name === 'config' && !window._configLoaded) { loadConfig(); window._configLoaded = true; }
  if (name === 'cookies' && !window._cookiesLoaded) { loadCookieMode(); loadCookieFields(); window._cookiesLoaded = true; }
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
  if (name === 'proxies') { if (typeof proxyLoadList === 'function') proxyLoadList(); if (typeof routerLoadList === 'function') routerLoadList(); }
  if (name === 'chat' && typeof chatInit === 'function') chatInit();
  if (name === 'videogen' && typeof vgInit === 'function') vgInit();
  if (name === 'n8n' && typeof n8nInit === 'function') n8nInit();
  if (name === 'sales' && typeof salesInit === 'function') salesInit();
}

/* ── Content platform sub-tabs (defined here so inline onclick always works) ── */
const _CPT_PANELS = ['files', 'facebook', 'youtube', 'tiktok'];

function cptSwitch(tab) {
  _CPT_PANELS.forEach(p => {
    const btn   = document.getElementById('cpt-tab-' + p);
    const panel = document.getElementById('cpt-panel-' + p);
    if (btn)   btn.classList.toggle('active', p === tab);
    if (panel) panel.style.display = (p === tab) ? 'block' : 'none';
  });
  if (tab === 'files')    { if (typeof loadContentList === 'function') loadContentList(); }
  if (tab === 'facebook') { if (typeof fbMgrInit === 'function') fbMgrInit(); }
  if (tab === 'youtube')  { if (typeof ytMgrInit === 'function') ytMgrInit(); }
}

function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.classList.toggle('collapsed');
  const btn = document.getElementById('sidebar-toggle-btn');
  if (btn) btn.textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}

function toggleMobileMenu() {
  const existing = document.getElementById('mobile-menu-overlay');
  if (existing) { existing.remove(); return; }
  const ov = document.createElement('div');
  ov.id = 'mobile-menu-overlay';
  ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:300;display:flex;align-items:flex-start';
  const pages = [
    ['user','🔍','Tìm người dùng'],['process','🎬','Xử lý Video'],
    ['transcribe','🎙','Phiên âm'],['publish','📤','Đăng video'],
    ['content','🗄','Quản lý nội dung'],
    ['movie','🎬','Review phim'],['story','📖','Truyện → Video'],
    ['proxies','🌐','Proxy & Router'],
    ['history','🗃','Lịch sử'],['config','⚙️','Cấu hình'],['cookies','🍪','Cookies']
  ];
  ov.innerHTML = `<div style="background:var(--bg2);width:240px;height:100%;padding:20px 12px;box-shadow:4px 0 20px rgba(0,0,0,.2);overflow-y:auto">
    <div style="font-weight:700;font-size:16px;color:var(--text);margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border)">📱 Menu</div>
    ${pages.map(([p,i,l]) => `<div onclick="switchPage('${p}');document.getElementById('mobile-menu-overlay')?.remove()" style="display:flex;align-items:center;gap:10px;padding:12px;border-radius:8px;cursor:pointer;color:var(--text2);font-weight:500;margin-bottom:4px;transition:background .15s" onmouseover="this.style.background='var(--accent-light)'" onmouseout="this.style.background=''">${i} ${l}</div>`).join('')}
  </div>`;
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
  document.body.appendChild(ov);
}

function toggleCard(header) {
  const card = header.closest('.card-collapsible');
  if (card) card.classList.toggle('collapsed');
}

/* ── Video Processing ── */
window._procMode = localStorage.getItem('proc_mode') || 'ai';
window._procSelectedFile = null;
window._procUploadPromise = null;

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
    burn_subs:        document.getElementById('proc-burn')?.checked ?? true,
    blur_original:    document.getElementById('proc-blur-original')?.checked ?? true,
    blur_height_pct:  parseFloat(document.getElementById('proc-blur-height')?.value || '15') / 100,
    blur_y_pct:       (() => {
      const v = document.getElementById('proc-blur-y')?.value?.trim();
      return (v !== '' && v !== undefined) ? parseFloat(v) / 100 : null;  // null = auto
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
    translate_subs:   document.getElementById('proc-translate-subs')?.checked ?? true,
    burn_vi_subs:     document.getElementById('proc-burn-vi')?.checked ?? true,
    voice_convert:    document.getElementById('proc-voice')?.checked ?? false,
    tts_engine:       document.getElementById('proc-tts-engine')?.value || 'edge-tts',
    tts_voice:        document.getElementById('proc-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
    tts_pitch:        _sanitizeVoiceParam(document.getElementById('proc-tts-pitch')?.value || '+0Hz'),
    tts_rate:         _sanitizeVoiceParam(document.getElementById('proc-tts-rate')?.value || '+0%'),
    tts_emotion:      document.getElementById('proc-tts-emotion')?.value || 'default',
    keep_bg_music:    document.getElementById('proc-keep-bg')?.checked ?? false,
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
    // Frame video (step 6)
    frame_enabled:        document.getElementById('frame-enabled')?.checked ?? false,
    frame_title:          document.getElementById('frame-title')?.value || '',
    frame_title_enabled:  document.getElementById('frame-title-enabled')?.checked ?? true,
    frame_title_size_pct: parseFloat(document.getElementById('frame-title-size')?.value || 5),
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
      return document.getElementById('frame-logo-path')?.dataset?.serverPath || '';
    })(),
    frame_logo_size_pct:  parseFloat(document.getElementById('frame-logo-size')?.value || 12),
    frame_logo_top_pct:   parseFloat(document.getElementById('frame-logo-top')?.value || 3),
    frame_logo_left_pct:  parseFloat(document.getElementById('frame-logo-left')?.value || 3),
    frame_logo_radius_pct: parseFloat(document.getElementById('frame-logo-radius')?.value ?? 50),
    // Thumbnail
    thumb_enabled:        document.getElementById('thumb-enabled')?.checked ?? false,
    thumb_mode:           (window._batchThumbMode || (window._thumbState?.mode === 'none' ? 'frame' : window._thumbState?.mode || 'frame')),
    thumb_path:           (window._batchThumbPath || window._thumbState?.path || ''),
    thumb_title:          document.getElementById('thumb-title')?.value || '',
    thumb_duration:       0.3,  // seconds to show thumbnail at start
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
            if (d.thumbnail_path) {
              window._publishLastThumbnailPath = d.thumbnail_path;
              if (typeof window._displayProcThumbnail === 'function') {
                window._displayProcThumbnail(d.thumbnail_path, d.thumbnail_image);
              }
            }
            // ── Thumbnail AI failure event ──
            if (d.thumb_failed) {
              if (typeof _showThumbFailCard === 'function') _showThumbFailCard();
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
    if (assContent && typeof pPubAnalyzeFromAss === 'function') {
      await pPubAnalyzeFromAss(assContent);
    } else {
      _appendProcLog('⚠ Không có ASS để AI phân tích — chuyển sang bước 5 để nhập thủ công', 'warning');
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

function startTranscribe() {
  const folder = document.getElementById('tr-dir')?.value?.trim() || './Downloaded';
  const single = document.getElementById('tr-file')?.value?.trim() || '';
  const outDir = document.getElementById('tr-out')?.value?.trim() || '';
  const selectedFile = window._trSelectedFile || document.getElementById('tr-import-file')?.files?.[0] || null;
  if (!folder && !single && !selectedFile) {
    alert('Vui lòng nhập thư mục video hoặc file đơn.');
    return;
  }

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
    provider: document.getElementById('tr-provider')?.value || 'groq',
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
        if (btn) {
          btn.disabled = false;
          btn.textContent = t('btn_start_tr');
        }
      });
    }

    read();
  }).catch(err => {
    _appendTrLog('Lỗi kết nối: ' + err, 'error');
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
    tts_engine:  document.getElementById('tr-tts-engine')?.value  || 'edge-tts',
    tts_voice:   document.getElementById('tr-tts-voice')?.value   || 'vi-VN-HoaiMyNeural',
    tts_pitch:   _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value  || '+0Hz'),
    tts_rate:    _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value   || '+0%'),
    tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
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

function _appendTrLog(msg, level) {
  appendLog('tr-log', msg, level || 'info');
}

function _setTrProgress(overallPct, overallLbl, filePct, fileLbl) {
  setProgress('pb-tr-overall', 'lbl-tr-overall', Number(overallPct) || 0, overallLbl || '--');
  setProgress('pb-tr-file', 'lbl-tr-file', Number(filePct) || 0, fileLbl || '--');
}

async function createMp3FromText() {
  const textInput = document.getElementById('tr-preview-text');
  const text = textInput?.value?.trim() || '';
  if (!text) {
    alert('Vui lòng nhập nội dung để tạo MP3.');
    textInput?.focus();
    return;
  }

  const btn = document.getElementById('btn-tr-tts-mp3');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang tạo...'; }
  _appendTrLog('🎙 Đang tạo MP3 từ văn bản (' + text.length + ' ký tự)...', 'info');

  try {
    const res = await fetch('/api/tts_to_mp3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        tts_engine: document.getElementById('tr-tts-engine')?.value || 'edge-tts',
        tts_voice: document.getElementById('tr-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
        tts_pitch: _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
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
    alert('Lỗi tạo MP3: ' + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 Tạo & tải MP3'; }
  }
}

async function previewTranscribeVoice() {
  if (!text && window._trAssPreviewText) {
    text = window._trAssPreviewText;
    if (textInput) textInput.value = text;
  }
  if (!text) {
    alert('Vui lòng nhập nội dung để nghe thử giọng.');
    return;
  }

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
        tts_engine: document.getElementById('tr-tts-engine')?.value || 'edge-tts',
        tts_voice: document.getElementById('tr-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
        tts_pitch: _sanitizeVoiceParam(document.getElementById('tr-tts-pitch')?.value || '+0Hz'),
        tts_rate: _sanitizeVoiceParam(document.getElementById('tr-tts-rate')?.value || '+0%'),
        tts_emotion: document.getElementById('tr-tts-emotion')?.value || 'default',
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
    alert('Lỗi preview giọng: ' + err.message);
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
        tts_engine: document.getElementById('proc-tts-engine')?.value || 'edge-tts',
        tts_voice: document.getElementById('proc-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
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
    alert('Lỗi: ' + err.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Nghe thử'; }
  }
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

document.addEventListener('DOMContentLoaded', () => {
  applyI18n();
  switchPage('user');
  document.getElementById('manual-url')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') addManualUrl();
  });
  _initUserPageListeners();

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
  _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');

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
        tts_engine: document.getElementById('vp-tts-engine')?.value || 'edge-tts',
        tts_voice: document.getElementById('vp-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
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

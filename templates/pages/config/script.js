
/* ── Config tab switcher ────────────────────────────────────────────────── */
function switchConfigTab(el, sectionId) {
  // Remove active from all nav tabs
  document.querySelectorAll('#page-config .config-tab').forEach(t => t.classList.remove('active'));
  if (el) el.classList.add('active');
  // Hide all panes, show target
  document.querySelectorAll('#page-config .config-pane').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(sectionId);
  if (target) target.classList.add('active');
  // Scroll content back to top
  const content = document.getElementById('content');
  if (content) content.scrollTop = 0;
}

// TTS thử giọng đọc
document.addEventListener('DOMContentLoaded', () => {
  if (typeof _syncVoiceOptions === 'function') {
    _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
  }
  document.getElementById('vp-tts-engine')?.addEventListener('change', function() {
    if (typeof _syncVoiceOptions === 'function') _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
  });

  const btn = document.getElementById('btn-tts-test');
  if (!btn) return;
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = 'Đang tạo giọng đọc...';
    try {
      const engine = document.getElementById('vp-tts-engine')?.value || 'edge-tts';
      const voice = document.getElementById('vp-tts-voice')?.value || 'vi-VN-HoaiMyNeural';
      const text = 'Xin chào, đây là giọng đọc mẫu tiếng Việt.';
      const res = await fetch('/api/tts_preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, tts_engine: engine, tts_voice: voice })
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = document.getElementById('vp-preview-audio') || new Audio();
        audio.src = url;
        audio.style.display = 'block';
        audio.play();
        toast('Tạo giọng đọc thành công!', 'success');
      } else {
        toast('Không thể tạo giọng đọc!', 'error');
      }
    } catch (e) {
      toast('Lỗi tạo giọng đọc: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = '▶ Thử giọng đọc';
  };
});
/* ── Config page ─────────────────────────────────────────────────────────── */
async function loadConfig() {
  const cfg = await API.get('/api/config');
  if (!cfg) return;
  window._loadedCfg = cfg;

  // Lưu path download từ config để các trang khác dùng
  window._cfgDownloadPath = cfg.path || './Downloaded/';

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };

  // Basic settings
  const links = cfg.link || cfg.links || [];
  set('cfg-urls', Array.isArray(links) ? links.join('\n') : links);
  set('cfg-path', cfg.path || './Downloaded/');
  set('cfg-proxy', cfg.proxy || '');
  set('cfg-thread', cfg.thread ?? 5);
  set('cfg-retry', cfg.retry_times ?? 3);
  set('cfg-start', cfg.start_date || '');
  set('cfg-end', cfg.end_date || '');

  // Modes
  const modes = cfg.mode || [];
  document.querySelectorAll('#mode-checks input[type=checkbox]').forEach(cb => {
    cb.checked = modes.includes(cb.value);
  });

  // Max counts
  const maxCounts = cfg.max_counts || {};
  ['post','like','collect','music','mix','collectmix'].forEach(m => {
    set('n-' + m, maxCounts[m] ?? 0);
  });

  // Options
  setChk('opt-music', cfg.music === true);
  setChk('opt-cover', cfg.cover === true);
  setChk('opt-json', cfg.json === true);
  setChk('opt-folder', cfg.folderstyle === true || cfg.folder === true);

  // Translation — keys nằm trong cfg.translation.*
  const tr = cfg.translation || {};
  set('cfg-preferred-provider', tr.preferred_provider || cfg.preferred_provider || 'auto');
  set('cfg-deepseek-key', tr.deepseek_key || '');
  set('cfg-groq-key', tr.groq_key || '');
  set('cfg-groq-model', tr.groq_model || 'llama-3.1-8b-instant');
  set('cfg-openai-key', tr.openai_key || '');
  set('cfg-hf-token', tr.hf_token || '');
  setChk('cfg-naming-enabled', tr.naming_enabled !== false);
  // FPT AI key (stored in video_process)
  set('cfg-fpt-key', cfg.video_process?.fpt_api_key || '');
  // ElevenLabs key (stored in video_process)
  set('cfg-elevenlabs-key', cfg.video_process?.elevenlabs_api_key || '');
  // Fish Audio key (stored in video_process)
  set('cfg-fish-key', cfg.video_process?.fish_api_key || '');
  // 9Router API key
  set('cfg-9router-key', cfg.nine_router?.api_key || '');
  // Gemini Video key
  set('cfg-gemini-key', cfg.gemini_video?.api_key || '');
  // TMDb keys
  set('cfg-tmdb-key', cfg.movie?.tmdb_api_key || '');
  set('cfg-tmdb-token', cfg.movie?.tmdb_read_token || '');

  // Upload defaults
  const upload = cfg.upload || {};
  set('cfg-upload-platform', upload.platform || 'youtube');
  setChk('cfg-upload-auto', upload.auto_upload === true);
  set('cfg-yt-title-template', upload.youtube?.title_template || '{title}');
  set('cfg-yt-desc-template', upload.youtube?.description_template || '{title}');
  set('cfg-yt-privacy', upload.youtube?.privacy_status || 'private');
  set('cfg-tt-title-template', upload.tiktok?.title_template || '{title}');
  set('cfg-tt-caption-template', upload.tiktok?.caption_template || '{title}');
  set('cfg-tt-privacy', upload.tiktok?.privacy_status || 'private');

  // Video processing
  setChk('vp-enabled', cfg.video_process?.enabled !== false);
  set('vp-model', cfg.video_process?.model || 'base');
  set('vp-lang', cfg.video_process?.language || 'zh');
  setChk('vp-burn', cfg.video_process?.burn_subs !== false);
  setChk('vp-blur-original', cfg.video_process?.blur_original === true);
  setChk('vp-translate', cfg.video_process?.translate !== false);
  setChk('vp-burn-vi', cfg.video_process?.burn_vi_subs !== false);
  setChk('vp-voice', cfg.video_process?.voice_convert !== false);
  setChk('vp-keep-bg', cfg.video_process?.keep_bg_music === true || cfg.video_process?.keep_bg === true);
  set('vp-process-mode', cfg.video_process?.process_mode || 'ai');
  set('vp-blur-zone', cfg.video_process?.blur_zone || 'bottom');
  // Đảm bảo catalog đã load trước khi set engine + sync voice
  const _applyTtsEngineFromConfig = () => {
    const eng = cfg.video_process?.tts_engine || 'fpt-ai';
    const voice = cfg.video_process?.tts_voice || 'banmai';
    const setVoiceIfPresent = (id, value) => {
      const el = document.getElementById(id);
      if (!el || !value) return;
      if (Array.from(el.options || []).some(opt => opt.value === value)) el.value = value;
    };
    set('vp-tts-engine', eng);
    _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
    setVoiceIfPresent('vp-tts-voice', voice);
    set('proc-tts-engine', eng);
    if (typeof _onTargetLangChange === 'function') _onTargetLangChange();
    else _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
    setVoiceIfPresent('proc-tts-voice', voice);
  };
  if (typeof TTS_ENGINE_CATALOG !== 'undefined' && TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
    _refreshTtsEngineSelects();
    _applyTtsEngineFromConfig();
  } else if (typeof _loadTtsEngineCatalog === 'function') {
    _loadTtsEngineCatalog().then(() => {
      requestAnimationFrame(() => {
        _refreshTtsEngineSelects();
        _applyTtsEngineFromConfig();
      });
    });
  } else {
    _applyTtsEngineFromConfig();
  }
  set('vp-tts-speed', cfg.video_process?.tts_speed ?? 1.0);
  const speedVal = parseFloat(document.getElementById('vp-tts-speed')?.value || '1.0');
  if (document.getElementById('vp-tts-speed-val')) document.getElementById('vp-tts-speed-val').textContent = speedVal.toFixed(1) + 'x';
  setChk('vp-auto-speed', cfg.video_process?.auto_speed !== false);
  set('vp-tts-pitch', cfg.video_process?.pitch_semitones ?? 0.0);
  const pitchVal = parseFloat(document.getElementById('vp-tts-pitch')?.value || '0');
  if (document.getElementById('vp-tts-pitch-val')) document.getElementById('vp-tts-pitch-val').textContent = (pitchVal > 0 ? '+' : '') + pitchVal.toFixed(1) + ' st';
  set('vp-font-size', cfg.video_process?.font_size ?? 22);
  set('vp-tts-engine', cfg.video_process?.tts_engine || 'edge-tts');
  set('vp-bg-volume', cfg.video_process?.bg_volume ?? 0.15);
  set('vp-tts-pitch', cfg.video_process?.tts_pitch || '+0Hz');
  set('vp-tts-rate', cfg.video_process?.tts_rate || '+0%');
  set('vp-tts-emotion', cfg.video_process?.tts_emotion || 'default');

  const hfCfg = cfg.huggingface || {};
  set('vp-hf-model', hfCfg.tts_model || 'facebook/mms-tts-vie');
  set('vp-hf-device', hfCfg.device || 'cpu');
  set('vp-hf-embeddings', hfCfg.tts_speaker_embeddings || '');
  if ((cfg.video_process?.tts_engine || 'edge-tts') === 'huggingface') {
    const el = document.getElementById('vp-hf-config');
    if (el) el.style.display = 'block';
  }
  
  const afp = cfg.video_process?.anti_fingerprint || {};
  setChk('vp-afp-enabled', afp.enabled === true);
  setChk('vp-afp-flip', afp.flip_h === true);
  setChk('vp-afp-vignette', afp.vignette === true);
  setChk('vp-afp-vertical', afp.vertical === true);
  set('vp-afp-scale-w', afp.scale_w || 0);
  set('vp-afp-scale-h', afp.scale_h || 0);
  set('vp-afp-overlay-img', afp.overlay_image || '');
  set('vp-afp-brightness', afp.brightness || 0.02);
  set('vp-afp-contrast', afp.contrast || 1.03);
  
  // Load frame logo from configuration if present
  const frameLogoPath = cfg.video_process?.frame_logo_path || '';
  const frameLogoUrl = cfg.video_process?.frame_logo_url || '';
  if (frameLogoPath) {
    try {
      localStorage.setItem('proc_frame_logo_path', frameLogoPath);
      if (frameLogoUrl) localStorage.setItem('proc_frame_logo_url', frameLogoUrl);
      
      const pathInput = document.getElementById('frame-logo-path');
      if (pathInput) {
        const pathParts = frameLogoPath.split(/[\\/]/);
        pathInput.value = pathParts[pathParts.length - 1];
        pathInput.dataset.serverPath = frameLogoPath;
      }
    } catch (_) {}
  }

  if (typeof syncProcessConfigFromLoaded === 'function') {
    syncProcessConfigFromLoaded();
  }

  if (typeof window.filterActiveProviders === 'function') {
    window.filterActiveProviders();
  }

  // Điền path vào các input thư mục từ config
  fillDirFromConfig();

  // Auto-test all keys that are already saved
  setTimeout(() => {
    for (const [provider, cfg] of Object.entries(_API_KEY_IDS)) {
      const key = document.getElementById(cfg.inputId)?.value?.trim();
      if (key && key.length > 8) testApiKey(provider);
    }
  }, 500);
}

async function saveConfig() {
  const get = id => { const el = document.getElementById(id); return el ? el.value : ''; };
  const getChk = id => { const el = document.getElementById(id); return el ? el.checked : false; };

  const modes = [];
  document.querySelectorAll('#mode-checks input[type=checkbox]:checked').forEach(cb => modes.push(cb.value));

  const maxCounts = {};
  ['post','like','collect','music','mix','collectmix'].forEach(m => {
    maxCounts[m] = parseInt(get('n-' + m)) || 0;
  });

  const urlsRaw = get('cfg-urls').trim();
  const links = urlsRaw ? urlsRaw.split('\n').map(s => s.trim()).filter(Boolean) : [];

  const data = {
    link: links,
    path: get('cfg-path'),
    proxy: get('cfg-proxy'),
    thread: parseInt(get('cfg-thread')) || 5,
    retry_times: parseInt(get('cfg-retry')) || 3,
    start_date: get('cfg-start'),
    end_date: get('cfg-end'),
    mode: modes,
    max_counts: maxCounts,
    music: getChk('opt-music'),
    cover: getChk('opt-cover'),
    json: getChk('opt-json'),
    folder: getChk('opt-folder'),
    translation: {
      preferred_provider: get('cfg-preferred-provider'),
      deepseek_key: get('cfg-deepseek-key'),
      groq_key: get('cfg-groq-key'),
      groq_model: get('cfg-groq-model') || 'llama-3.1-8b-instant',
      openai_key: get('cfg-openai-key'),
      hf_token: get('cfg-hf-token'),
      naming_enabled: getChk('cfg-naming-enabled'),
    },
    upload: {
      platform: get('cfg-upload-platform') || 'youtube',
      auto_upload: getChk('cfg-upload-auto'),
      youtube: {
        title_template: get('cfg-yt-title-template') || '{title}',
        description_template: get('cfg-yt-desc-template') || '{title}',
        privacy_status: get('cfg-yt-privacy') || 'private',
      },
      tiktok: {
        title_template: get('cfg-tt-title-template') || '{title}',
        caption_template: get('cfg-tt-caption-template') || '{title}',
        privacy_status: get('cfg-tt-privacy') || 'private',
      },
    },
    huggingface: {
      tts_model: get('vp-hf-model') || 'facebook/mms-tts-vie',
      device: get('vp-hf-device') || 'cpu',
      tts_speaker_embeddings: get('vp-hf-embeddings') || '',
    },
    video_process: {
      enabled: getChk('vp-enabled'),
      model: get('vp-model'),
      language: get('vp-lang'),
      process_mode: get('vp-process-mode') || 'ai',
      burn_subs: getChk('vp-burn'),
      blur_original: getChk('vp-blur-original'),
      translate: getChk('vp-translate'),
      burn_vi_subs: getChk('vp-burn-vi'),
      voice_convert: getChk('vp-voice'),
      keep_bg_music: getChk('vp-keep-bg'),
      keep_bg: getChk('vp-keep-bg'),
      blur_zone: get('vp-blur-zone'),
      tts_engine: get('vp-tts-engine'),
      tts_voice: get('vp-tts-voice'),
      tts_speed: parseFloat(get('vp-tts-speed')) || 1.0,
      auto_speed: getChk('vp-auto-speed'),
      pitch_semitones: parseFloat(get('vp-tts-pitch')) || 0.0,
      font_size: parseInt(get('vp-font-size')) || 22,
      tts_engine: get('vp-tts-engine') || 'edge-tts',
      bg_volume: parseFloat(get('vp-bg-volume')) || 0.15,
      tts_pitch: get('vp-tts-pitch') || '+0Hz',
      tts_rate: get('vp-tts-rate') || '+0%',
      tts_emotion: get('vp-tts-emotion') || 'default',
      fpt_api_key: get('cfg-fpt-key') || '',
      elevenlabs_api_key: get('cfg-elevenlabs-key') || '',
      fish_api_key: get('cfg-fish-key') || '',
      elevenlabs_voice_id: '21m00Tcm4TlvDq8ikWAM',
      elevenlabs_model: 'eleven_multilingual_v2',
      fpt_fallback_elevenlabs: false,
      frame_logo_path: document.getElementById('frame-logo-path')?.dataset?.serverPath || localStorage.getItem('proc_frame_logo_path') || '',
      frame_logo_url: localStorage.getItem('proc_frame_logo_url') || '',
      subtitle_format: 'ass',
      anti_fingerprint: {
        enabled: getChk('vp-afp-enabled'),
        flip_h: getChk('vp-afp-flip'),
        vignette: getChk('vp-afp-vignette'),
        vertical: getChk('vp-afp-vertical'),
        scale_w: parseInt(get('vp-afp-scale-w')) || 0,
        scale_h: parseInt(get('vp-afp-scale-h')) || 0,
        overlay_image: get('vp-afp-overlay-img') || '',
        brightness: parseFloat(get('vp-afp-brightness')) || 0.02,
        contrast: parseFloat(get('vp-afp-contrast')) || 1.03,
      }
    }
  };

  // NineRouter, Gemini, TMDb keys
  data.nine_router = {
    api_key: get('cfg-9router-key'),
  };
  data.gemini_video = {
    api_key: get('cfg-gemini-key'),
  };
  data.movie = {
    tmdb_api_key: get('cfg-tmdb-key'),
    tmdb_read_token: get('cfg-tmdb-token'),
  };

  await API.post('/api/config', data);
  toast(t('toast_config_saved'), 'success');
}

/* ── API Key Test ─────────────────────────────────────────────────────────── */
const _API_KEY_IDS = {
  '9router':    { inputId: 'cfg-9router-key',    statusId: 'cfg-9router-status' },
  deepseek:    { inputId: 'cfg-deepseek-key',    statusId: 'cfg-deepseek-status' },
  groq:        { inputId: 'cfg-groq-key',         statusId: 'cfg-groq-status' },
  openai:      { inputId: 'cfg-openai-key',       statusId: 'cfg-openai-status' },
  huggingface: { inputId: 'cfg-hf-token',         statusId: 'cfg-hf-status' },
  fpt:         { inputId: 'cfg-fpt-key',          statusId: 'cfg-fpt-status' },
  elevenlabs:  { inputId: 'cfg-elevenlabs-key',   statusId: 'cfg-elevenlabs-status' },
  'fish-audio':{ inputId: 'cfg-fish-key',         statusId: 'cfg-fish-status' },
  gemini:      { inputId: 'cfg-gemini-key',       statusId: 'cfg-gemini-status' },
  tmdb:        { inputId: 'cfg-tmdb-key',         statusId: 'cfg-tmdb-status' },
};

function _setKeyStatus(statusId, state, msg) {
  const el = document.getElementById(statusId);
  if (!el) return;
  const colors = { ok: '#0d7a4e', error: '#c0392b', loading: '#888', warn: '#b7770d' };
  const icons  = { ok: '✅', error: '❌', loading: '⏳', warn: '⚠' };
  el.style.color = colors[state] || '#888';
  el.textContent = (icons[state] || '') + ' ' + msg;
}

async function testApiKey(provider) {
  const cfg = _API_KEY_IDS[provider];
  if (!cfg) return;
  const key = document.getElementById(cfg.inputId)?.value?.trim();
  if (!key) {
    _setKeyStatus(cfg.statusId, 'warn', 'Chưa nhập key');
    return;
  }
  _setKeyStatus(cfg.statusId, 'loading', 'Đang kiểm tra...');
  try {
    const res = await fetch('/api/test_api_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key })
    });
    const data = await res.json();
    if (data.ok) {
      const quota = data.quota ? ` | ${data.quota}` : '';
      const model = data.model ? ` (${data.model})` : '';
      _setKeyStatus(cfg.statusId, 'ok', `Key hợp lệ${model}${quota}`);
    } else {
      _setKeyStatus(cfg.statusId, 'error', data.error || 'Key không hợp lệ');
    }
  } catch (e) {
    _setKeyStatus(cfg.statusId, 'error', 'Lỗi kết nối: ' + e.message);
  }
}

async function testAllApiKeys() {
  const btn = document.querySelector('[onclick="testAllApiKeys()"]');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang test...'; }
  for (const provider of Object.keys(_API_KEY_IDS)) {
    const key = document.getElementById(_API_KEY_IDS[provider].inputId)?.value?.trim();
    if (key) await testApiKey(provider);
  }
  if (btn) { btn.disabled = false; btn.textContent = '🧪 Test tất cả'; }
}

// Auto-test when user finishes typing in a key field (on blur)
document.addEventListener('DOMContentLoaded', () => {
  for (const [provider, cfg] of Object.entries(_API_KEY_IDS)) {
    const input = document.getElementById(cfg.inputId);
    if (!input) continue;
    let _testTimer = null;
    input.addEventListener('blur', () => {
      clearTimeout(_testTimer);
      const key = input.value.trim();
      if (key.length > 8) {
        // Small delay so user can see the loading state
        _testTimer = setTimeout(() => testApiKey(provider), 300);
      } else if (!key) {
        _setKeyStatus(cfg.statusId, '', '');
      }
    });
  }
});

async function uploadClientSecrets(input) {
  const file = input.files?.[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload_client_secrets', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (data.ok) {
      toast(data.message, 'success');
    } else {
      toast('Lỗi: ' + (data.error || 'Không rõ'), 'error');
    }
  } catch (e) {
    toast('Lỗi kết nối: ' + e.message, 'error');
  } finally {
    input.value = ''; // Reset input
  }
}

/* ── Cookie Handlers ──────────────────────────────────────────────────────── */
const COOKIE_FIELD_KEYS = ['ttwid','odin_tt','passport_csrf_token','s_v_web_id','__ac_nonce','__ac_signature','UIFID','bd_ticket_guard_client_web_domain'];

function _validCookieName(name) {
  return /^[A-Za-z0-9_$.-]+$/.test(String(name || ''));
}

function _collectCookieValues(payload, out = {}) {
  if (Array.isArray(payload)) {
    payload.forEach(item => _collectCookieValues(item, out));
    return out;
  }
  if (!payload || typeof payload !== 'object') return out;

  ['cookies', 'cookie', 'data'].forEach(key => {
    if (payload[key] && typeof payload[key] === 'object') {
      _collectCookieValues(payload[key], out);
    }
  });

  if (typeof payload.name === 'string' && Object.prototype.hasOwnProperty.call(payload, 'value')) {
    out[payload.name] = payload.value == null ? '' : String(payload.value);
  }

  for (const [key, value] of Object.entries(payload)) {
    if (['name','value','domain','path','expires','expirationDate','httpOnly','secure','sameSite'].includes(key)) continue;
    if (!_validCookieName(key)) continue;
    if (value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'value')) {
      out[key] = value.value == null ? '' : String(value.value);
    } else if (value == null || typeof value !== 'object') {
      out[key] = value == null ? '' : String(value);
    }
  }
  return out;
}

function _parseCookieText(raw) {
  const text = String(raw || '').trim();
  if (!text) return {};

  const jsonCandidates = [text];
  const stripped = text.replace(/;\s*$/, '').trim();
  if (!stripped.startsWith('{') && !stripped.startsWith('[')) {
    jsonCandidates.push('{' + stripped.replace(/,\s*$/, '') + '}');
  }
  for (const candidate of jsonCandidates) {
    try {
      const parsed = _collectCookieValues(JSON.parse(candidate));
      if (Object.keys(parsed).length) return parsed;
    } catch (_) {}
  }

  const lineParsed = {};
  const lineRe = /["']?([A-Za-z0-9_$.-]+)["']?\s*[:=]\s*["']([^"']*)["']/g;
  let match;
  while ((match = lineRe.exec(text)) !== null) {
    if (_validCookieName(match[1])) lineParsed[match[1]] = match[2].trim();
  }
  if (Object.keys(lineParsed).length) return lineParsed;

  let header = text;
  if (/^cookie\s*:/i.test(header)) header = header.replace(/^cookie\s*:/i, '').trim();
  if (/^document\.cookie\s*=/i.test(header)) {
    header = header.replace(/^document\.cookie\s*=/i, '').trim().replace(/^["']|["'];?$/g, '');
  }

  const headerParsed = {};
  header.split(';').forEach(item => {
    const part = item.trim();
    const pos = part.indexOf('=');
    if (pos <= 0) return;
    const key = part.slice(0, pos).trim();
    const value = part.slice(pos + 1).trim();
    if (_validCookieName(key)) headerParsed[key] = value;
  });
  return headerParsed;
}

function _fillCookieFields(parsed) {
  let filled = 0;
  for (const key of COOKIE_FIELD_KEYS) {
    const el = document.getElementById('ck-' + key);
    if (el && Object.prototype.hasOwnProperty.call(parsed, key)) {
      el.value = parsed[key] || '';
      filled++;
    }
  }
  return filled;
}

async function loadCookieMode() {
  try {
    const res = await fetch('/api/cookie_mode');
    const data = await res.json();
    const toggle = document.getElementById('ck-mode-toggle');
    if (toggle) {
      toggle.checked = data.mode === 'custom';
      onCookieModeChange();
    }
  } catch (e) {
    console.error('loadCookieMode error:', e);
  }
}

async function loadCookieFields() {
  try {
    const cfg = await API.get('/api/config');
    if (!cfg) return;
    const cookies = cfg.cookies || {};
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
    set('ck-ttwid', cookies.ttwid || '');
    set('ck-odin_tt', cookies.odin_tt || '');
    set('ck-passport_csrf_token', cookies.passport_csrf_token || '');
    set('ck-s_v_web_id', cookies.s_v_web_id || '');
    set('ck-__ac_nonce', cookies.__ac_nonce || '');
    set('ck-__ac_signature', cookies.__ac_signature || '');
    set('ck-UIFID', cookies.UIFID || '');
    set('ck-bd_ticket_guard_client_web_domain', cookies.bd_ticket_guard_client_web_domain || '');

    // Load YouTube & Facebook cookie settings
    const ytdlp = cfg.ytdlp || {};
    const cookieFiles = ytdlp.cookie_files || {};
    const cookieContents = ytdlp.cookie_contents || {};
    set('ck-yt-browser', ytdlp.cookies_from_browser || '');
    set('ck-yt-file', cookieFiles.youtube || '');
    set('ck-yt-content', cookieContents.youtube || '');
    set('ck-fb-file', cookieFiles.facebook || '');
    set('ck-fb-content', cookieContents.facebook || '');
    set('ck-fb-profile', cfg.facebook_profile || '.facebook_profile');
  } catch (e) {
    console.error('loadCookieFields error:', e);
  }
}

function switchCfgCookieTab(platform) {
  document.querySelectorAll('.cfg-cookie-tab-panel').forEach(p => {
    const on = p.getAttribute('data-cookie-platform') === platform;
    p.style.display = on ? 'block' : 'none';
  });
  document.querySelectorAll('.cfg-cookie-tab').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-cookie-platform') === platform);
  });
}
window.switchCfgCookieTab = switchCfgCookieTab;

async function savePlatformConfig(platform) {
  if (platform === 'tiktok') {
    await saveCookies();
    return;
  }
  const payload = {};
  if (platform === 'youtube') {
    const browser = document.getElementById('ck-yt-browser')?.value || '';
    const filepath = document.getElementById('ck-yt-file')?.value?.trim() || '';
    const content = document.getElementById('ck-yt-content')?.value || '';
    payload.ytdlp = {
      cookies_from_browser: browser,
      cookie_files: {
        youtube: filepath
      },
      cookie_contents: {
        youtube: content
      }
    };
  } else if (platform === 'facebook') {
    const filepath = document.getElementById('ck-fb-file')?.value?.trim() || '';
    const profile = document.getElementById('ck-fb-profile')?.value?.trim() || '.facebook_profile';
    const content = document.getElementById('ck-fb-content')?.value || '';
    payload.ytdlp = {
      cookie_files: {
        facebook: filepath
      },
      cookie_contents: {
        facebook: content
      }
    };
    payload.facebook_profile = profile;
  }
  
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) toast('Đã lưu cấu hình cookie ' + platform + '!', 'success');
    else toast('Lỗi lưu cấu hình: ' + (data.error || ''), 'error');
  } catch (e) {
    toast('Lỗi lưu cấu hình: ' + e.message, 'error');
  }
}
window.savePlatformConfig = savePlatformConfig;

function onCookieModeChange() {
  const toggle = document.getElementById('ck-mode-toggle');
  const wrap = document.getElementById('ck-custom-wrap');
  const desc = document.getElementById('ck-mode-desc');
  if (!toggle || !wrap || !desc) return;
  if (toggle.checked) {
    wrap.style.display = 'block';
    desc.textContent = 'Đang dùng cookie tùy chỉnh. Điền các trường bên dưới và nhấn Lưu.';
  } else {
    wrap.style.display = 'none';
    desc.textContent = 'Sử dụng cookie mặc định từ hệ thống.';
  }
  // Save mode preference
  fetch('/api/cookie_mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: toggle.checked ? 'custom' : 'default' })
  }).catch(() => {});
}

async function parseCookie() {
  const raw = document.getElementById('ck-raw')?.value?.trim();
  if (!raw) { toast('Vui lòng dán chuỗi cookie trước!', 'warning'); return; }
  try {
    const res = await fetch('/api/parse_cookie', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw })
    });
    const data = await res.json();
    if (data && typeof data === 'object') {
      for (const [key, val] of Object.entries(data)) {
        const el = document.getElementById('ck-' + key);
        if (el) el.value = val;
      }
      toast('Phân tích cookie thành công!', 'success');
    }
  } catch (e) {
    toast('Lỗi phân tích cookie: ' + e.message, 'error');
  }
}

async function parseCookie() {
  const raw = document.getElementById('ck-raw')?.value?.trim();
  if (!raw) { toast('Vui long dan chuoi cookie truoc!', 'warning'); return; }
  try {
    let data = _parseCookieText(raw);
    if (!Object.keys(data).length) {
      const res = await fetch('/api/parse_cookie', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw })
      });
      data = await res.json();
    }

    const filled = data && typeof data === 'object' ? _fillCookieFields(data) : 0;
    const statusEl = document.getElementById('ck-status');
    if (filled > 0) {
      if (statusEl) {
        statusEl.innerHTML = `<span class="dot dot-green"></span><span class="text-xs text-green">Da phan tich ${filled} truong</span>`;
      }
      toast(`Da phan tich va dien ${filled} truong cookie!`, 'success');
    } else {
      if (statusEl) {
        statusEl.innerHTML = '<span class="dot dot-red"></span><span class="text-xs text-red">Khong tim thay truong cookie phu hop</span>';
      }
      toast('Khong tim thay truong cookie phu hop trong noi dung da dan.', 'warning');
    }
  } catch (e) {
    toast('Loi phan tich cookie: ' + e.message, 'error');
  }
}

async function importCookieJsonFile(input) {
  const file = input?.files?.[0];
  if (!file) return;
  try {
    const raw = await file.text();
    const rawEl = document.getElementById('ck-raw');
    if (rawEl) rawEl.value = raw;
    await parseCookie();
  } catch (e) {
    toast('Loi import JSON: ' + e.message, 'error');
  } finally {
    if (input) input.value = '';
  }
}

async function saveCookies() {
  const get = id => document.getElementById(id)?.value?.trim() || '';
  const cookies = {
    ttwid: get('ck-ttwid'),
    odin_tt: get('ck-odin_tt'),
    passport_csrf_token: get('ck-passport_csrf_token'),
    s_v_web_id: get('ck-s_v_web_id'),
    __ac_nonce: get('ck-__ac_nonce'),
    __ac_signature: get('ck-__ac_signature'),
    UIFID: get('ck-UIFID'),
    bd_ticket_guard_client_web_domain: get('ck-bd_ticket_guard_client_web_domain'),
  };
  try {
    const res = await fetch('/api/cookies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cookies)
    });
    const data = await res.json();
    if (data.ok) toast('Đã lưu cookie!', 'success');
    else toast('Lỗi lưu cookie: ' + (data.error || ''), 'error');
  } catch (e) {
    toast('Lỗi lưu cookie: ' + e.message, 'error');
  }
}

async function validateCookie() {
  const get = id => document.getElementById(id)?.value?.trim() || '';
  const cookies = {
    ttwid: get('ck-ttwid'),
    odin_tt: get('ck-odin_tt'),
    passport_csrf_token: get('ck-passport_csrf_token'),
    s_v_web_id: get('ck-s_v_web_id'),
    __ac_nonce: get('ck-__ac_nonce'),
    __ac_signature: get('ck-__ac_signature'),
    UIFID: get('ck-UIFID'),
    bd_ticket_guard_client_web_domain: get('ck-bd_ticket_guard_client_web_domain'),
  };
  const statusEl = document.getElementById('ck-status');
  if (statusEl) {
    statusEl.innerHTML = '<span class="dot dot-yellow"></span><span class="text-xs">Đang kiểm tra...</span>';
  }
  try {
    const res = await fetch('/api/validate_cookie', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cookies)
    });
    const data = await res.json();
    if (statusEl) {
      if (data.ok) {
        statusEl.innerHTML = '<span class="dot dot-green"></span><span class="text-xs text-green">Cookie hợp lệ ✓</span>';
      } else {
        statusEl.innerHTML = '<span class="dot dot-red"></span><span class="text-xs text-red">Cookie không hợp lệ ✗</span>';
      }
    }
  } catch (e) {
    if (statusEl) {
      statusEl.innerHTML = '<span class="dot dot-red"></span><span class="text-xs text-red">Lỗi: ' + e.message + '</span>';
    }
  }
}

async function autoFetchCookie() {
  try {
    const res = await fetch('/api/auto_fetch_cookie', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      toast('Đang mở trình duyệt để lấy cookie... Vui lòng đăng nhập và đợi!', 'info');
    } else {
      toast('Lỗi: ' + (data.error || ''), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}

async function browseSavePath() {
  try {
    const res = await fetch('/api/browse-folder', { method: 'POST' });
    const data = await res.json();
    if (data && data.path) {
      document.getElementById('cfg-path').value = data.path;
      // Cập nhật path toàn cục khi người dùng chọn thư mục mới
      window._cfgDownloadPath = data.path;
      toast('Đã chọn thư mục lưu: ' + data.path, 'success');
    }
  } catch (e) {
    toast('Lỗi chọn thư mục: ' + e.message, 'error');
  }
}

/**
 * Điền thư mục mặc định từ config vào các input thư mục trên tất cả các trang.
 * Được gọi sau khi loadConfig() hoàn thành.
 */
function fillDirFromConfig() {
  const path = window._cfgDownloadPath || '';
  if (!path) return;

  // Trang Phiên âm — input thư mục video
  const trDir = document.getElementById('tr-dir');
  if (trDir && (!trDir.value || trDir.value === './Downloaded' || trDir.value === './Downloaded/')) {
    trDir.value = path;
  }

  // Trang Xử lý Video (step1) — output dir (dùng path làm default khi trống)
  // Không override nếu user đã nhập
  // proc-out để trống = cùng thư mục video, không set mặc định
}

/**
 * Kiểm tra API key đang dùng trước khi thực hiện tác vụ dịch/TTS.
 * @param {string} provider  - 'deepseek' | 'groq' | 'fpt' | 'elevenlabs' | 'fish-audio' | '9router' | 'openai'
 * @param {string} keyValue  - giá trị key cần test
 * @param {Function} onOk    - callback khi test thành công, sẽ tiếp tục tác vụ
 * @param {Function} onCancel - callback khi người dùng hủy
 */
async function checkApiBeforeAction(provider, keyValue, onOk, onCancel) {
  // Nếu không có key → hiện modal luôn
  if (!keyValue || keyValue.length < 6) {
    _showApiCheckModal(provider, '', 'Key chưa được cấu hình hoặc để trống.', onOk, onCancel);
    return;
  }

  // Test nhanh key hiện tại
  try {
    const res = await fetch('/api/test_api_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key: keyValue })
    });
    const data = await res.json();
    if (data.ok) {
      // Key hoạt động → tiếp tục luôn
      onOk && onOk();
    } else {
      _showApiCheckModal(provider, keyValue, data.error || 'Key không hợp lệ hoặc hết hạn.', onOk, onCancel);
    }
  } catch (e) {
    _showApiCheckModal(provider, keyValue, 'Không thể kết nối để kiểm tra key: ' + e.message, onOk, onCancel);
  }
}

/**
 * Hiện modal yêu cầu người dùng cập nhật API key.
 */
function _showApiCheckModal(provider, currentKey, errorMsg, onOk, onCancel) {
  const modal = document.getElementById('api-check-modal');
  if (!modal) {
    // Fallback nếu modal chưa được thêm vào HTML
    const proceed = confirm(`⚠️ API key lỗi:\n${errorMsg}\n\nBấm OK để tiếp tục dù sao, Cancel để dừng.`);
    if (proceed) onOk && onOk();
    else onCancel && onCancel();
    return;
  }

  const LABELS = {
    deepseek: 'DeepSeek', groq: 'Groq', fpt: 'FPT AI TTS',
    elevenlabs: 'ElevenLabs TTS', 'fish-audio': 'Fish Audio TTS',
    '9router': '9Router', openai: 'OpenAI', gemini: 'Gemini'
  };

  const providerLabel = LABELS[provider] || provider;

  document.getElementById('api-check-modal-provider').textContent = providerLabel;
  document.getElementById('api-check-modal-error').textContent = errorMsg;
  document.getElementById('api-check-modal-key').value = currentKey || '';
  document.getElementById('api-check-modal-status').textContent = '';
  document.getElementById('api-check-modal-status').className = 'api-check-status';

  // Disable nút OK cho đến khi test thành công
  const btnOk = document.getElementById('btn-api-check-ok');
  if (btnOk) btnOk.disabled = true;

  modal.style.display = 'flex';
  modal.dataset.provider = provider;

  // Lưu callbacks
  window._apiCheckOnOk = onOk;
  window._apiCheckOnCancel = onCancel;
}

async function apiCheckModalTest() {
  const provider = document.getElementById('api-check-modal')?.dataset?.provider || '';
  const key = document.getElementById('api-check-modal-key')?.value?.trim() || '';
  const statusEl = document.getElementById('api-check-modal-status');
  const btnOk = document.getElementById('btn-api-check-ok');
  const btnTest = document.getElementById('btn-api-check-test');

  if (!key) { if (statusEl) { statusEl.textContent = '⚠️ Vui lòng nhập key trước'; statusEl.className = 'api-check-status warn'; } return; }

  if (btnTest) { btnTest.disabled = true; btnTest.textContent = '⏳ Đang test...'; }
  if (statusEl) { statusEl.textContent = 'Đang kiểm tra...'; statusEl.className = 'api-check-status'; }

  try {
    const res = await fetch('/api/test_api_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key })
    });
    const data = await res.json();
    if (data.ok) {
      if (statusEl) { statusEl.textContent = '✅ Key hợp lệ' + (data.quota ? ' — ' + data.quota : ''); statusEl.className = 'api-check-status ok'; }
      if (btnOk) btnOk.disabled = false;
      // Lưu key mới vào config tự động
      _apiCheckSaveKeyToConfig(provider, key);
    } else {
      if (statusEl) { statusEl.textContent = '❌ ' + (data.error || 'Key không hợp lệ'); statusEl.className = 'api-check-status err'; }
      if (btnOk) btnOk.disabled = true;
    }
  } catch (e) {
    if (statusEl) { statusEl.textContent = '❌ Lỗi kết nối: ' + e.message; statusEl.className = 'api-check-status err'; }
    if (btnOk) btnOk.disabled = true;
  } finally {
    if (btnTest) { btnTest.disabled = false; btnTest.textContent = '🧪 Test'; }
  }
}

function _apiCheckSaveKeyToConfig(provider, key) {
  const cfg = window._loadedCfg || {};
  const updates = {};
  if (provider === 'deepseek') updates.translation = { ...(cfg.translation || {}), deepseek_key: key };
  else if (provider === 'groq') updates.translation = { ...(cfg.translation || {}), groq_key: key };
  else if (provider === 'openai') updates.translation = { ...(cfg.translation || {}), openai_key: key };
  else if (provider === 'fpt') updates.video_process = { ...(cfg.video_process || {}), fpt_api_key: key };
  else if (provider === 'elevenlabs') updates.video_process = { ...(cfg.video_process || {}), elevenlabs_api_key: key };
  else if (provider === 'fish-audio') updates.video_process = { ...(cfg.video_process || {}), fish_api_key: key };
  else if (provider === '9router') updates.nine_router = { ...(cfg.nine_router || {}), api_key: key };
  else if (provider === 'gemini') updates.gemini_video = { ...(cfg.gemini_video || {}), api_key: key };

  if (Object.keys(updates).length) {
    fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    }).catch(() => {});
    // Cập nhật window._loadedCfg
    Object.assign(window._loadedCfg || {}, updates);
    // Cập nhật input trong trang config nếu có
    const inputMap = {
      deepseek: 'cfg-deepseek-key', groq: 'cfg-groq-key', openai: 'cfg-openai-key',
      fpt: 'cfg-fpt-key', elevenlabs: 'cfg-elevenlabs-key', 'fish-audio': 'cfg-fish-key',
      '9router': 'cfg-9router-key', gemini: 'cfg-gemini-key'
    };
    const inputEl = document.getElementById(inputMap[provider]);
    if (inputEl) inputEl.value = key;

    if (typeof window.filterActiveProviders === 'function') {
      window.filterActiveProviders();
    }
  }
}

function apiCheckModalOk() {
  document.getElementById('api-check-modal').style.display = 'none';
  const cb = window._apiCheckOnOk;
  window._apiCheckOnOk = null;
  window._apiCheckOnCancel = null;
  cb && cb();
}

function apiCheckModalCancel() {
  document.getElementById('api-check-modal').style.display = 'none';
  const cb = window._apiCheckOnCancel;
  window._apiCheckOnOk = null;
  window._apiCheckOnCancel = null;
  cb && cb();
}

/**
 * Lấy API key từ config theo provider.
 */
function getApiKeyForProvider(provider) {
  const cfg = window._loadedCfg || {};
  const tr = cfg.translation || {};
  const vp = cfg.video_process || {};
  const map = {
    deepseek: tr.deepseek_key,
    groq: tr.groq_key,
    openai: tr.openai_key,
    fpt: vp.fpt_api_key,
    elevenlabs: vp.elevenlabs_api_key,
    'fish-audio': vp.fish_api_key,
    '9router': (cfg.nine_router || {}).api_key,
    gemini: (cfg.gemini_video || {}).api_key,
  };
  return map[provider] || '';
}

window.filterActiveProviders = async function() {
  const cfg = window._loadedCfg || {};
  let status = null;
  try {
    status = await API.get('/api/translation_status');
  } catch (e) {
    console.error('Failed to fetch translation status:', e);
  }

  const selectIds = [
    'cfg-preferred-provider',
    'proc-trans-provider-model',
    'proc-trans-provider-ai',
    'fb-post-ai-provider',
    'fb-text-ai-provider',
    'dl-translate-provider',
    'mv-provider',
    'p-pub-ai-provider',
    'pub-ai-provider',
    'batch-pub-ai-provider',
    'provider-select'
  ];

  selectIds.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;

    const currentVal = el.value;

    el.innerHTML = '';

    // Always add 'Auto (Server)'
    const optAuto = document.createElement('option');
    optAuto.value = 'auto';
    optAuto.textContent = 'Auto (Server)';
    el.appendChild(optAuto);

    if (status && status.models && status.models.length) {
      // Group models by provider
      const groups = {};
      status.models.forEach(m => {
        const prov = m.provider || 'others';
        if (!groups[prov]) groups[prov] = [];
        groups[prov].push(m);
      });

      const providerLabels = {
        'google': '🌐 Google Translate',
        'huggingface': '🤗 HuggingFace',
        'openai': '🧠 OpenAI',
        'deepseek': '🐳 DeepSeek',
        'groq': '⚡ Groq',
        'gemini': '🔷 Gemini'
      };

      // Sort providers: google first, then 9router, then others alphabetically
      const sortedProviders = Object.keys(groups).sort((a, b) => {
        if (a === 'google') return -1;
        if (b === 'google') return 1;
        if (a === '9router') return -1;
        if (b === '9router') return 1;
        return a.localeCompare(b);
      });

      sortedProviders.forEach(prov => {
        if (prov === '9router') {
          // Group 9router models by owned_by
          const subGroups = {};
          groups[prov].forEach(m => {
            const owner = m.owned_by || 'others';
            if (!subGroups[owner]) subGroups[owner] = [];
            subGroups[owner].push(m);
          });

          const ownerLabel = (k) => ({
            'kr': '🥝 Kiro (FREE)',
            'gemini': '🔷 Gemini',
            'gc': '🐙 GitHub Copilot',
            'ag': '🌌 Antigravity',
            'combo': '✨ Combo (custom)',
          })[k] || (k || 'others');

          // Sort owner keys: combo first, then ag, then gc, then gemini, then kr, then others
          const sortedOwners = Object.keys(subGroups).sort((a, b) => {
            const order = ['combo', 'ag', 'gc', 'gemini', 'kr'];
            const idxA = order.indexOf(a);
            const idxB = order.indexOf(b);
            if (idxA !== -1 && idxB !== -1) return idxA - idxB;
            if (idxA !== -1) return -1;
            if (idxB !== -1) return 1;
            return a.localeCompare(b);
          });

          sortedOwners.forEach(owner => {
            const og = document.createElement('optgroup');
            og.label = '🔀 9Router: ' + ownerLabel(owner);
            subGroups[owner].forEach(m => {
              const opt = document.createElement('option');
              opt.value = m.id;
              opt.textContent = m.name;
              og.appendChild(opt);
            });
            el.appendChild(og);
          });
        } else {
          const og = document.createElement('optgroup');
          og.label = providerLabels[prov] || prov;
          groups[prov].forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.name;
            og.appendChild(opt);
          });
          el.appendChild(og);
        }
      });

      // Show '-----' separator and fallback warning trigger if there are inactive providers
      const activeProviders = status.providers || [];
      const allProviders = ['9router', 'deepseek', 'openai', 'huggingface', 'groq', 'gemini'];
      const hasInactive = allProviders.some(p => !activeProviders.includes(p));
      if (hasInactive) {
        const optPrompt = document.createElement('option');
        optPrompt.value = 'prompt_connect';
        optPrompt.textContent = '-----';
        el.appendChild(optPrompt);
      }
    } else {
      // Offline fallback
      const optGoogle = document.createElement('option');
      optGoogle.value = 'google';
      optGoogle.textContent = 'Google Translate';
      el.appendChild(optGoogle);
    }

    // Try to restore the selected value. If not found, default to auto.
    const availableValues = Array.from(el.options).map(o => o.value);
    if (availableValues.includes(currentVal)) {
      el.value = currentVal;
    } else {
      // Check if we can find a matching model prefix
      const matched = availableValues.find(v => v.startsWith(currentVal + '/'));
      if (matched) {
        el.value = matched;
      } else {
        el.value = 'auto';
      }
    }
  });

  // Handle transcribe select
  ['proc-transcribe-provider-model', 'tr-provider'].forEach(id => {
    const transcEl = document.getElementById(id);
    if (!transcEl) return;
    if (!transcEl._origOptions) {
      transcEl._origOptions = Array.from(transcEl.options).map(opt => ({
        value: opt.value,
        text: opt.textContent,
        selected: opt.selected
      }));
    }
    const currentVal = transcEl.value;
    const activeOpts = transcEl._origOptions.filter(opt => {
      if (opt.value === 'groq') {
        const groqKey = cfg.translation?.groq_key;
        return groqKey && String(groqKey).trim().length > 0;
      }
      return true; // model (local) is always active
    });
    transcEl.innerHTML = '';
    activeOpts.forEach(opt => {
      const optionEl = document.createElement('option');
      optionEl.value = opt.value;
      optionEl.textContent = opt.text;
      if (opt.value === currentVal) {
        optionEl.selected = true;
      }
      transcEl.appendChild(optionEl);
    });
    if (transcEl.value !== currentVal && transcEl.options.length) {
      transcEl.options[0].selected = true;
    }
  });

  // Trigger TTS engine selects refresh
  if (typeof _refreshTtsEngineSelects === 'function') {
    _refreshTtsEngineSelects();
  }
};

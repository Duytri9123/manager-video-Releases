
/* ── Config tab switcher is in utils.js ── */

// TTS thử giọng đọc
document.addEventListener('DOMContentLoaded', () => {
  // Init TTS voice options for config page
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
    btn.textContent = 'Đang thử...';
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
      } else {
        toast('Không thử được giọng đọc!', 'error');
      }
    } catch (e) {
      toast('Lỗi thử giọng đọc: ' + e.message, 'error');
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
  set('vp-tts-engine', cfg.video_process?.tts_engine || 'fpt-ai');
  _syncVoiceOptions('vp-tts-engine', 'vp-tts-voice');
  set('vp-tts-voice', cfg.video_process?.tts_voice || 'banmai');
  // Sync proc page dropdowns too
  set('proc-tts-engine', cfg.video_process?.tts_engine || 'fpt-ai');
  _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
  set('proc-tts-voice', cfg.video_process?.tts_voice || 'banmai');
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
  
  if (typeof syncProcessConfigFromLoaded === 'function') {
    syncProcessConfigFromLoaded();
  }

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

  await API.post('/api/config', data);
  toast(t('toast_config_saved'), 'success');
}

/* ── API Key Test ─────────────────────────────────────────────────────────── */
const _API_KEY_IDS = {
  deepseek:    { inputId: 'cfg-deepseek-key',  statusId: 'cfg-deepseek-status' },
  groq:        { inputId: 'cfg-groq-key',       statusId: 'cfg-groq-status' },
  openai:      { inputId: 'cfg-openai-key',     statusId: 'cfg-openai-status' },
  huggingface: { inputId: 'cfg-hf-token',       statusId: 'cfg-hf-status' },
  fpt:         { inputId: 'cfg-fpt-key',        statusId: 'cfg-fpt-status' },
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
  if (btn) { btn.disabled = false; btn.textContent = '🧪 Test tất cả API Keys'; }
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

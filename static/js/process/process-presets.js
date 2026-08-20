  /* ════════════════════════════════════════════════════════
     SAVE / RESTORE DEFAULTS — per aspect ratio (9:16 / 16:9)
  ════════════════════════════════════════════════════════ */
  const _PROC_DEFAULTS_KEY      = 'proc_settings_defaults_v1';      // legacy single preset
  const _PROC_DEFAULTS_KEY_V2   = 'proc_settings_defaults_v2';      // { '9x16': {...}, '16x9': {...} }
  const _PROC_PREVIEW_ASPECT_K  = 'proc_preview_aspect_v1';

  // Currently active aspect ratio for save/restore. Set by:
  //  - aspect override dropdown
  //  - subPreviewFetchFrame() once it knows video dims
  // Defaults to '16x9' until a video is detected.
  window._procActiveAspect = '16x9';

  /** Classify width/height into '9x16' (vertical) or '16x9' (horizontal/square). */
  function _classifyAspect(w, h) {
    if (!w || !h) return '16x9';
    return (w / h) < 1.0 ? '9x16' : '16x9';
  }

  function _getAspectOverride() {
    return document.getElementById('proc-aspect-override')?.value
      || document.getElementById('proc-preview-aspect')?.value
      || 'auto';
  }

  function _updateAspectBadge() {
    const badge = document.getElementById('proc-active-aspect-badge');
    if (!badge) return;
    const a = window._procActiveAspect;
    const override = _getAspectOverride();
    const label = a === '9x16' ? '📱 9:16 (dọc)' : '🖥 16:9 (ngang)';
    badge.textContent = override === 'auto' ? `📐 ${label} • tự nhận diện` : `📐 ${label} • thủ công`;
    badge.style.display = 'inline-block';
  }

  /** Read all preset map from storage (v2). Migrates from v1 if needed. */
  function _loadPresetsMap() {
    try {
      const rawV2 = localStorage.getItem(_PROC_DEFAULTS_KEY_V2);
      if (rawV2) return JSON.parse(rawV2) || {};
    } catch (_) {}
    // Migrate from v1: copy single preset to both aspects
    try {
      const rawV1 = localStorage.getItem(_PROC_DEFAULTS_KEY);
      if (rawV1) {
        const data = JSON.parse(rawV1);
        const map = { '9x16': data, '16x9': data };
        localStorage.setItem(_PROC_DEFAULTS_KEY_V2, JSON.stringify(map));
        return map;
      }
    } catch (_) {}
    return {};
  }

  function _savePresetsMap(map) {
    try { localStorage.setItem(_PROC_DEFAULTS_KEY_V2, JSON.stringify(map || {})); } catch (_) {}
  }

  /** Apply the saved preset for window._procActiveAspect to the form. */
  // All field IDs to save (id → type)
  const _PROC_FIELDS = [
    // ── STEP 1: Source, Translation & Auto Options ──
    { id:'proc-lang',           type:'value' },
    { id:'proc-target-lang',    type:'value' },
    { id:'proc-trans-provider-model', type:'value' },
    { id:'proc-ai-video-auto',  type:'checkbox' },
    { id:'proc-ai-video-samples', type:'value' },
    { id:'proc-ai-video-nine-model', type:'value' },
    { id:'proc-auto-flow',      type:'checkbox' },
    { id:'step3-skip-ass',      type:'checkbox' },
    { id:'proc-skip-transcription', type:'checkbox' },
    { id:'batch-auto-drain',    type:'checkbox' },
    { id:'proc-batch-resolution', type:'value' },
    { id:'proc-batch-cookie',   type:'value' },

    // ── STEP 2: Aspect, Subtitles, Frame, Overlays & FX ──
    { id:'proc-aspect-blur-bg', type:'checkbox' },
    { id:'proc-burn',           type:'checkbox' },
    { id:'proc-translate-subs', type:'checkbox' },
    { id:'proc-burn-vi',        type:'checkbox' },
    { id:'proc-blur-original',  type:'checkbox' },
    { id:'proc-blur-height',    type:'value' },
    { id:'proc-blur-width',     type:'value' },
    { id:'proc-blur-zone',      type:'value' },
    { id:'proc-blur-x',         type:'value' },
    { id:'proc-blur-y',         type:'value' },
    { id:'proc-font-size',      type:'value' },
    { id:'proc-font-color',     type:'value' },
    { id:'proc-font-color-picker', type:'value' },
    { id:'proc-margin-v',       type:'value' },
    { id:'proc-outline-width',  type:'value' },
    { id:'proc-font-bold',      type:'checkbox' },
    { id:'proc-sub-pos',        type:'value' },
    { id:'frame-enabled',       type:'checkbox' },
    { id:'frame-title',         type:'value' },
    { id:'frame-title-enabled', type:'checkbox' },
    { id:'frame-title-size',    type:'value' },
    { id:'frame-title-weight',  type:'value' },
    { id:'frame-title-bar-h',   type:'value' },
    { id:'frame-title-margin-x', type:'value' },
    { id:'frame-title-x',       type:'value' },
    { id:'frame-title-y',       type:'value' },
    { id:'frame-title-color',   type:'value' },
    { id:'frame-title-color-hex', type:'value' },
    { id:'frame-title-color-2', type:'value' },
    { id:'frame-title-color-2-hex', type:'value' },
    { id:'frame-title-split-color', type:'checkbox' },
    { id:'frame-blur-w',        type:'value' },
    { id:'frame-blur-top',      type:'value' },
    { id:'frame-blur-bottom',   type:'value' },
    { id:'frame-blur-opacity',  type:'value' },
    { id:'frame-logo-size',     type:'value' },
    { id:'frame-logo-top',      type:'value' },
    { id:'frame-logo-left',     type:'value' },
    { id:'frame-logo-radius',   type:'value' },
    { id:'ov-layers-json',      type:'value' },
    { id:'sub-preview-sample',  type:'value' },
    { id:'sub-preview-ts',      type:'value' },
    { id:'proc-capcut-enabled', type:'checkbox' },
    { id:'proc-capcut-auto-open', type:'checkbox' },
    { id:'proc-ext-audios-json', type:'value' },
    { id:'proc-out',            type:'value' },

    // ── STEP 3: AI Models, Voice & FX ──
    { id:'proc-model',          type:'value' },
    { id:'proc-transcribe-provider-model', type:'value' },
    { id:'proc-voice',          type:'checkbox' },
    { id:'proc-tts-engine',     type:'value' },
    { id:'proc-tts-voice',      type:'value' },
    { id:'proc-tts-pitch',      type:'value' },
    { id:'proc-tts-rate',       type:'value' },
    { id:'proc-tts-emotion',    type:'value' },
    { id:'proc-tts-speed',      type:'value' },
    { id:'proc-auto-speed',     type:'checkbox' },
    { id:'proc-keep-bg',        type:'checkbox' },
    { id:'proc-bg-vol',         type:'value' },
    { id:'proc-fx-enabled',     type:'checkbox' },
    { id:'proc-fx-pitch',       type:'value' },
    { id:'proc-fx-speed',       type:'value' },
    { id:'proc-fx-bass',        type:'value' },
    { id:'proc-fx-mid',         type:'value' },
    { id:'proc-fx-treble',      type:'value' },
    { id:'proc-fx-comp',        type:'value' },
    { id:'proc-fx-reverb',      type:'value' },
  ];
  window._PROC_FIELDS = _PROC_FIELDS;

  const _STEP_FIELD_IDS = {
    1: ['proc-lang', 'proc-target-lang', 'proc-trans-provider-model', 'proc-ai-video-auto', 'proc-ai-video-samples', 'proc-ai-video-nine-model', 'proc-auto-flow', 'step3-skip-ass', 'proc-skip-transcription', 'batch-auto-drain', 'proc-batch-resolution', 'proc-batch-cookie'],
    2: ['proc-aspect-blur-bg', 'proc-burn', 'proc-translate-subs', 'proc-burn-vi', 'proc-blur-original', 'proc-blur-height', 'proc-blur-width', 'proc-blur-zone', 'proc-blur-x', 'proc-blur-y', 'proc-font-size', 'proc-font-color', 'proc-font-color-picker', 'proc-margin-v', 'proc-outline-width', 'proc-font-bold', 'proc-sub-pos', 'frame-enabled', 'frame-title', 'frame-title-enabled', 'frame-title-size', 'frame-title-weight', 'frame-title-bar-h', 'frame-title-margin-x', 'frame-title-x', 'frame-title-y', 'frame-title-color', 'frame-title-color-hex', 'frame-title-color-2', 'frame-title-color-2-hex', 'frame-title-split-color', 'frame-blur-w', 'frame-blur-top', 'frame-blur-bottom', 'frame-blur-opacity', 'frame-logo-size', 'frame-logo-top', 'frame-logo-left', 'frame-logo-radius', 'ov-layers-json', 'sub-preview-sample', 'sub-preview-ts', 'proc-capcut-enabled', 'proc-capcut-auto-open', 'proc-ext-audios-json', 'proc-out'],
    3: ['proc-model', 'proc-transcribe-provider-model', 'proc-ai-video-samples', 'proc-voice', 'proc-tts-engine', 'proc-tts-voice', 'proc-tts-pitch', 'proc-tts-rate', 'proc-tts-emotion', 'proc-tts-speed', 'proc-auto-speed', 'proc-keep-bg', 'proc-bg-vol', 'proc-fx-enabled', 'proc-fx-pitch', 'proc-fx-speed', 'proc-fx-bass', 'proc-fx-mid', 'proc-fx-treble', 'proc-fx-comp', 'proc-fx-reverb']
  };

  /** Save config for a specific step (1, 2, or 3) */
  function procSaveStep(stepNum, silent) {
    if (typeof _ovSyncHidden === 'function') _ovSyncHidden();
    const map = _loadPresetsMap();
    const aspect = window._procActiveAspect || '16x9';
    const data = map[aspect] || {};

    const targetIds = _STEP_FIELD_IDS[stepNum] || [];
    _PROC_FIELDS.forEach(f => {
      if (targetIds.length && !targetIds.includes(f.id)) return;
      const el = document.getElementById(f.id);
      if (!el) return;
      data[f.id] = f.type === 'checkbox' ? el.checked : el.value;
    });

    if (stepNum === 2 || !stepNum) {
      const blurMode = document.querySelector('input[name="frame-blur-mode"]:checked')?.value;
      if (blurMode) data['frame-blur-mode'] = blurMode;
    }

    try {
      map[aspect] = data;
      _savePresetsMap(map);
      try { localStorage.setItem(_PROC_DEFAULTS_KEY, JSON.stringify(data)); } catch (_) {}
      if (!silent) {
        const stepNames = { 1: 'Bước 1 (Nguồn & Dịch)', 2: 'Bước 2 (Khung hình & Sub)', 3: 'Bước 3 (AI & Lồng tiếng)' };
        const msg = stepNames[stepNum] ? `✅ Đã lưu cấu hình ${stepNames[stepNum]} (${aspect.replace('x', ':')})` : `✅ Đã lưu cấu hình (${aspect.replace('x', ':')})`;
        if (typeof toast === 'function') toast(msg, 'success');
      }
      _updateAspectBadge();
    } catch (e) {
      if (!silent && typeof toast === 'function') toast('Lỗi lưu: ' + e.message, 'error');
    }
  }
  window.procSaveStep = procSaveStep;

  /** Save all settings */
  function procSaveDefaults(silent) {
    const data = {};
    if (typeof _ovSyncHidden === 'function') _ovSyncHidden();
    _PROC_FIELDS.forEach(f => {
      const el = document.getElementById(f.id);
      if (!el) return;
      data[f.id] = f.type === 'checkbox' ? el.checked : el.value;
    });
    const blurMode = document.querySelector('input[name="frame-blur-mode"]:checked')?.value;
    if (blurMode) data['frame-blur-mode'] = blurMode;

    try {
      const map = _loadPresetsMap();
      const aspect = window._procActiveAspect || '16x9';
      map[aspect] = data;
      _savePresetsMap(map);
      try { localStorage.setItem(_PROC_DEFAULTS_KEY, JSON.stringify(data)); } catch (_) {}
      if (!silent && typeof toast === 'function') {
        toast(`✅ Đã lưu cài đặt mặc định cho ${aspect.replace('x', ':')}`, 'success');
      }
      _updateAspectBadge();
    } catch (e) {
      if (!silent && typeof toast === 'function') toast('Lỗi lưu: ' + e.message, 'error');
    }
  }
  window.procSaveDefaults = procSaveDefaults;

  /** Restore defaults */
  function procRestoreDefaults(stepNum) {
    try {
      const map = _loadPresetsMap();
      const aspect = window._procActiveAspect || '16x9';
      const data = map[aspect];
      if (!data) {
        if (typeof toast === 'function') toast(`Chưa có cài đặt mặc định cho tỉ lệ ${aspect.replace('x', ':')}`, 'warning');
        return;
      }
      const targetIds = (stepNum && _STEP_FIELD_IDS[stepNum]) ? _STEP_FIELD_IDS[stepNum] : null;
      _PROC_FIELDS.forEach(f => {
        if (targetIds && !targetIds.includes(f.id)) return;
        const el = document.getElementById(f.id);
        if (!el || !(f.id in data)) return;
        if (f.type === 'checkbox') el.checked = data[f.id];
        else el.value = data[f.id];
        el.dispatchEvent(new Event('change'));
        el.dispatchEvent(new Event('input'));
      });
      if (!stepNum || stepNum === 2) {
        if (data['frame-blur-mode']) {
          const radio = document.querySelector(`input[name="frame-blur-mode"][value="${data['frame-blur-mode']}"]`);
          if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change')); }
        }
      }
      if (typeof _onTargetLangChange === 'function') {
        _onTargetLangChange();
      } else if (typeof _syncVoiceOptions === 'function') {
        _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
      }
      if (typeof frameToggle === 'function') frameToggle();
      if (typeof toast === 'function') {
        toast(`↺ Đã khôi phục cài đặt ${stepNum ? `Bước ${stepNum}` : ''} (${aspect.replace('x', ':')})`, 'info');
      }
    } catch (e) {
      if (typeof toast === 'function') toast('Lỗi khôi phục: ' + e.message, 'error');
    }
  }
  window.procRestoreDefaults = procRestoreDefaults;

  // Auto-restore on page load
  document.addEventListener('DOMContentLoaded', () => {
    try {
      const map = _loadPresetsMap();
      const aspectSel = document.getElementById('proc-preview-aspect');
      let selectedAspect = aspectSel?.value || 'auto';
      try {
        const savedAspect = localStorage.getItem(_PROC_PREVIEW_ASPECT_K);
        if (savedAspect === 'auto' || savedAspect === '16x9' || savedAspect === '9x16') {
          selectedAspect = savedAspect;
        }
      } catch (_) {}
      if (aspectSel) aspectSel.value = selectedAspect;

      const img = document.getElementById('sub-preview-img');
      const initialAspect = selectedAspect === 'auto'
        ? ((img && img.naturalWidth) ? _classifyAspect(img.naturalWidth, img.naturalHeight) : '16x9')
        : selectedAspect;
      window._procActiveAspect = initialAspect;
      const data = map[initialAspect] || map['9x16'] || map['16x9'];

      if (data) {
        _PROC_FIELDS.forEach(f => {
          const el = document.getElementById(f.id);
          if (!el || !(f.id in data)) return;
          if (f.type === 'checkbox') el.checked = data[f.id];
          else el.value = data[f.id];
        });
        if (data['proc-ai-video-nine-model'] && typeof window._syncAiVideoModel === 'function') {
          window._syncAiVideoModel(data['proc-ai-video-nine-model']);
        }
        if (data['frame-blur-mode']) {
          const radio = document.querySelector(`input[name="frame-blur-mode"][value="${data['frame-blur-mode']}"]`);
          if (radio) radio.checked = true;
        }
        if (typeof _onTargetLangChange === 'function') {
          _onTargetLangChange();
        } else if (typeof _syncVoiceOptions === 'function') {
          _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
        }
        if (typeof _syncColorPicker === 'function') _syncColorPicker();
        if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
        if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
      }
      _updateAspectBadge();
      if (typeof frameToggle === 'function') frameToggle();
      if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
      if (typeof window._syncAspectBtns === 'function') window._syncAspectBtns();
      if (typeof window.pe2SyncPlayhead === 'function') window.pe2SyncPlayhead();
      if (typeof onTranscribeProviderChanged === 'function') onTranscribeProviderChanged(true);

      // Debounced auto-save on input change
      let _autoSaveTimer = null;
      document.getElementById('page-process')?.addEventListener('change', (e) => {
        if (e.target && (e.target.id || e.target.name)) {
          clearTimeout(_autoSaveTimer);
          _autoSaveTimer = setTimeout(() => {
            if (typeof procSaveDefaults === 'function') procSaveDefaults(true);
          }, 800);
        }
      });
    } catch (_) {}
  });

  // Auto-update frame preview when toggle flags change
  document.addEventListener('DOMContentLoaded', () => {
    const blurChk = document.getElementById('proc-blur-original');
    if (blurChk) blurChk.addEventListener('change', () => _renderSubOverlay());
    const burnChk2 = document.getElementById('proc-burn');
    if (burnChk2) burnChk2.addEventListener('change', () => _renderSubOverlay());
    const burnViChk2 = document.getElementById('proc-burn-vi');
    if (burnViChk2) burnViChk2.addEventListener('change', () => _renderSubOverlay());
  });



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
    // Aspect / Preview
    { id:'proc-aspect-blur-bg', type:'checkbox' },
    // AI Model + Language
    { id:'proc-model',          type:'value' },
    { id:'proc-lang',           type:'value' },
    { id:'proc-target-lang',    type:'value' },
    { id:'proc-transcribe-provider-model', type:'value' },
    { id:'proc-trans-provider-model', type:'value' },
    { id:'proc-ai-video-auto',  type:'checkbox' },
    { id:'proc-ai-video-samples',  type:'value' },
    { id:'proc-ai-video-nine-model', type:'value' },
    // Subtitle
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
    // Voice
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
    // FX
    { id:'proc-fx-enabled',     type:'checkbox' },
    { id:'proc-fx-pitch',       type:'value' },
    { id:'proc-fx-speed',       type:'value' },
    { id:'proc-fx-bass',        type:'value' },
    { id:'proc-fx-mid',         type:'value' },
    { id:'proc-fx-treble',      type:'value' },
    { id:'proc-fx-comp',        type:'value' },
    { id:'proc-fx-reverb',      type:'value' },
    // Frame video
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
    // Text / shape overlays
    { id:'ov-layers-json',      type:'value' },
    { id:'sub-preview-sample',  type:'value' },
    { id:'sub-preview-ts',      type:'value' },
    // CapCut
    { id:'proc-capcut-enabled', type:'checkbox' },
    { id:'proc-capcut-auto-open', type:'checkbox' },
    // Output dir
    { id:'proc-ext-audios-json', type:'value' },
    { id:'proc-out',            type:'value' },
  ];

  // Auto-restore on page load
  document.addEventListener('DOMContentLoaded', () => {
    try {
      // Pick initial preset to apply on first load
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
      const data = map[initialAspect] || map['9x16'];

      if (data) {
        _PROC_FIELDS.forEach(f => {
          const el = document.getElementById(f.id);
          if (!el || !(f.id in data)) return;
          if (f.type === 'checkbox') el.checked = data[f.id];
          else el.value = data[f.id];
        });
        // Restore blur mode radio (not in _PROC_FIELDS because it's a radio group)
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
      // Sync frame controls visibility on page load
      if (typeof frameToggle === 'function') frameToggle();
      // Apply preview aspect on page load (reads from proc-preview-aspect select which was restored above)
      if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
      if (typeof window._syncAspectBtns === 'function') window._syncAspectBtns();
      // Sync time input display after restore
      if (typeof window.pe2SyncPlayhead === 'function') window.pe2SyncPlayhead();
      // Sync Whisper models based on restored provider
      if (typeof onTranscribeProviderChanged === 'function') onTranscribeProviderChanged(true);
    } catch (_) {}
  });

  // ── Đổi khung hình Preview (16:9, 9:16, hoặc auto) ───────────
  // Auto-update frame preview when frame-enabled toggled
  document.addEventListener('DOMContentLoaded', () => {
    // frame-enabled change is handled by inline onchange="frameToggle()"
    const blurChk = document.getElementById('proc-blur-original');
    if (blurChk) blurChk.addEventListener('change', () => _renderSubOverlay());
    const burnChk2 = document.getElementById('proc-burn');
    if (burnChk2) burnChk2.addEventListener('change', () => _renderSubOverlay());
    const burnViChk2 = document.getElementById('proc-burn-vi');
    if (burnViChk2) burnViChk2.addEventListener('change', () => _renderSubOverlay());
  });



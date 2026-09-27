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
    const saveButton = document.getElementById('pe2-save-defaults');
    const aspectLabel = (window._procActiveAspect || '16x9').replace('x', ':');
    if (saveButton) {
      saveButton.title = `Lưu cài đặt Bước 2 vào mặc định ${aspectLabel} trong trình duyệt`;
      saveButton.setAttribute('aria-label', saveButton.title);
      const label = document.getElementById('pe2-save-defaults-label');
      if (label) label.textContent = `Lưu mặc định ${aspectLabel}`;
    }
    const badge = document.getElementById('proc-active-aspect-badge');
    if (!badge) return;
    const a = window._procActiveAspect;
    const override = _getAspectOverride();
    const label = a === '9x16' ? ' 9:16 (dọc)' : ' 16:9 (ngang)';
    badge.textContent = override === 'auto' ? ` ${label} • tự nhận diện` : ` ${label} • thủ công`;
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
    { id:'proc-translation-provider', type:'value' },
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
    { id:'proc-output-fps', type:'value' },
    { id:'proc-encode-device', type:'value' },
    { id:'proc-burn',           type:'checkbox' },
    { id:'proc-translate-subs', type:'checkbox' },
    { id:'proc-burn-vi',        type:'checkbox' },
    { id:'proc-blur-original',  type:'checkbox' },
    { id:'proc-blur-by-subtitles', type:'checkbox' },
    { id:'proc-blur-height',    type:'value' },
    { id:'proc-blur-width',     type:'value' },
    { id:'proc-blur-zone',      type:'value' },
    { id:'proc-blur-x',         type:'value' },
    { id:'proc-blur-y',         type:'value' },
    { id:'proc-font-size',      type:'value' },
    { id:'proc-font-color',     type:'value' },
    { id:'proc-font-color-picker', type:'value' },
    { id:'proc-font-color-hex', type:'value' },
    { id:'proc-margin-v',       type:'value' },
    { id:'proc-outline-width',  type:'value' },
    { id:'proc-font-bold',      type:'checkbox' },
    { id:'proc-font-weight',    type:'value' },
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
    { id:'proc-vol-orig',      type:'value' },
    { id:'proc-ext-audio-enabled', type:'checkbox' },
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
    2: ['proc-aspect-blur-bg', 'proc-burn', 'proc-translate-subs', 'proc-burn-vi', 'proc-blur-original', 'proc-blur-height', 'proc-blur-width', 'proc-blur-zone', 'proc-blur-x', 'proc-blur-y', 'proc-font-size', 'proc-font-color', 'proc-font-color-picker', 'proc-font-color-hex', 'proc-margin-v', 'proc-outline-width', 'proc-font-bold', 'proc-font-weight', 'proc-sub-pos', 'frame-enabled', 'frame-title', 'frame-title-enabled', 'frame-title-size', 'frame-title-weight', 'frame-title-bar-h', 'frame-title-margin-x', 'frame-title-x', 'frame-title-y', 'frame-title-color', 'frame-title-color-hex', 'frame-title-color-2', 'frame-title-color-2-hex', 'frame-title-split-color', 'frame-blur-w', 'frame-blur-top', 'frame-blur-bottom', 'frame-blur-opacity', 'frame-logo-size', 'frame-logo-top', 'frame-logo-left', 'frame-logo-radius', 'ov-layers-json', 'sub-preview-sample', 'sub-preview-ts', 'proc-capcut-enabled', 'proc-capcut-auto-open', 'proc-vol-orig', 'proc-ext-audio-enabled', 'proc-ext-audios-json', 'proc-out'],
    3: ['proc-model', 'proc-transcribe-provider-model', 'proc-ai-video-samples', 'proc-voice', 'proc-tts-engine', 'proc-tts-voice', 'proc-tts-pitch', 'proc-tts-rate', 'proc-tts-emotion', 'proc-tts-speed', 'proc-auto-speed', 'proc-keep-bg', 'proc-bg-vol', 'proc-fx-enabled', 'proc-fx-pitch', 'proc-fx-speed', 'proc-fx-bass', 'proc-fx-mid', 'proc-fx-treble', 'proc-fx-comp', 'proc-fx-reverb']
  };

  /** Save config for a specific step (1, 2, or 3) */
  _STEP_FIELD_IDS[2].push('proc-blur-by-subtitles', 'proc-output-fps', 'proc-encode-device');
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
        const msg = ` Đã lưu ${stepNames[stepNum] || 'cài đặt'} vào cấu hình mặc định ${aspect.replace('x', ':')} trong trình duyệt.`;
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
        toast(` Đã lưu cài đặt mặc định cho ${aspect.replace('x', ':')}`, 'success');
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
      if (!localStorage.getItem('proc_minh_quan_default_v1')) {
        for (const preset of Object.values(map)) {
          if (preset && (!preset['proc-tts-engine'] || preset['proc-tts-engine'] === 'vieneu')) {
            preset['proc-tts-voice'] = 'Minh Quân Pro';
          }
        }
        _savePresetsMap(map);
        localStorage.setItem('proc_minh_quan_default_v1', '1');
      }
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
      const saveChangedSettings = (e) => {
        if (e.target && (e.target.id || e.target.name)) {
          clearTimeout(_autoSaveTimer);
          _autoSaveTimer = setTimeout(() => {
            if (typeof procSaveDefaults === 'function') procSaveDefaults(true);
          }, 800);
        }
      };
      document.getElementById('page-process')?.addEventListener('change', saveChangedSettings);
      document.getElementById('page-process')?.addEventListener('input', saveChangedSettings);
      window.addEventListener('pagehide', () => {
        if (_autoSaveTimer) {
          clearTimeout(_autoSaveTimer);
          procSaveDefaults(true);
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

    try {
      // The editor now uses one stable, resizable layout.
      localStorage.setItem('pe2_layout_mode', 'standard');
      if (typeof pe2SetLayoutMode === 'function') pe2SetLayoutMode('standard');
    } catch (_) {}
  });

  function pe2ToggleProfileDrawer() {
    const drawer = document.getElementById('pe2-profile-save-drawer');
    if (!drawer) return;
    const isHidden = drawer.style.display === 'none' || !drawer.style.display;
    drawer.style.display = isHidden ? 'flex' : 'none';
    if (isHidden) {
      document.getElementById('pe2-profile-name')?.focus();
    }
  }
  window.pe2ToggleProfileDrawer = pe2ToggleProfileDrawer;

  function pe2SetLayoutMode(mode) {
    const editor = document.querySelector('.pe2-editor');
    if (!editor) return;
    const allowedModes = ['standard', 'expanded', 'dual'];
    const targetMode = allowedModes.includes(mode) ? mode : 'standard';
    const panel = document.getElementById('pe2-panel');
    editor.setAttribute('data-layout', targetMode);
    // Width dragged by the user belongs to Standard mode only. Keeping the
    // inline width here used to override Expanded/Dual CSS, so those buttons
    // appeared to do nothing.
    if (panel) {
      if (targetMode === 'standard') {
        const savedWidth = parseInt(localStorage.getItem('pe2_panel_width') || '', 10);
        const maxWidth = Math.min(720, Math.max(380, editor.clientWidth - 340));
        const width = Number.isFinite(savedWidth)
          ? Math.max(380, Math.min(maxWidth, savedWidth))
          : 420;
        panel.style.flex = `0 0 ${width}px`;
        panel.style.width = `${width}px`;
      } else {
        panel.style.removeProperty('flex');
        panel.style.removeProperty('width');
      }
    }
    document.querySelectorAll('.pe2-view-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-pe2layout') === targetMode);
    });
    try { localStorage.setItem('pe2_layout_mode', targetMode); } catch (_) {}
    // Recalculate all preview layers after the panel transition finishes.
    setTimeout(() => {
      window.dispatchEvent(new Event('resize'));
      if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
      if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
      else if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    }, 180);
  }
  window.pe2SetLayoutMode = pe2SetLayoutMode;

  /* ════════════════════════════════════════════════════════
     NAMED PROFILES / PRESETS MANAGEMENT (Step 1 & Step 2)
  ════════════════════════════════════════════════════════ */
  const _PE2_PROFILES_KEY = 'pe2_named_profiles_v2';
  const _PE2_ACTIVE_PROFILE_KEY = 'pe2_active_profile_v2';
  let _pe2ServerProfiles = {};

  const _PE2_DEFAULT_PROFILES = {
    'Dọc 9:16 Sub & Blur': {
      name: 'Dọc 9:16 Sub & Blur',
      type: 'Dọc ngắn',
      aspect: '9x16',
      padMode: 'blur',
      settings: {
        'proc-aspect-blur-bg': true,
        'proc-burn': true,
        'proc-translate-subs': true,
        'proc-burn-vi': true,
        'proc-blur-original': true,
        'proc-font-size': '5',
        'proc-margin-v': '6',
        'proc-outline-width': '2',
        'proc-font-bold': true,
        'proc-font-color': 'white',
        'proc-sub-pos': 'bottom'
      }
    },
    'Ngang 16:9 Chuẩn': {
      name: 'Ngang 16:9 Chuẩn',
      type: 'Ngang dài',
      aspect: '16x9',
      padMode: 'pad',
      settings: {
        'proc-aspect-blur-bg': false,
        'proc-burn': true,
        'proc-translate-subs': true,
        'proc-burn-vi': true,
        'proc-blur-original': false,
        'proc-font-size': '4',
        'proc-margin-v': '5',
        'proc-outline-width': '2',
        'proc-font-bold': true,
        'proc-font-color': 'white',
        'proc-sub-pos': 'bottom'
      }
    },
    'Dọc 9:16 Không Sub (Lồng tiếng)': {
      name: 'Dọc 9:16 Không Sub (Lồng tiếng)',
      type: 'Dọc ngắn',
      aspect: '9x16',
      padMode: 'blur',
      settings: {
        'proc-aspect-blur-bg': true,
        'proc-burn': false,
        'proc-translate-subs': true,
        'proc-burn-vi': false,
        'proc-blur-original': true,
        'proc-voice': true
      }
    }
  };

  function pe2LoadNamedProfiles() {
    let custom = {};
    try {
      const raw = localStorage.getItem(_PE2_PROFILES_KEY);
      if (raw) custom = JSON.parse(raw) || {};
    } catch (_) {}
    return { ..._PE2_DEFAULT_PROFILES, ..._pe2ServerProfiles, ...custom };
  }
  window.pe2LoadNamedProfiles = pe2LoadNamedProfiles;

  function pe2PopulateProfileSelects(selectedName) {
    const profiles = pe2LoadNamedProfiles();
    const activeName = selectedName || localStorage.getItem(_PE2_ACTIVE_PROFILE_KEY) || '';

    const targets = [
      document.getElementById('pe2-profile-select'),
      document.getElementById('step1-profile-select')
    ];

    targets.forEach(sel => {
      if (!sel) return;
      const prevVal = sel.value;
      sel.innerHTML = '<option value="">Cấu hình đã lưu…</option>';
      Object.keys(profiles).forEach(name => {
        const p = profiles[name];
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = p.type ? `${name} (${p.type})` : name;
        sel.appendChild(opt);
      });
      if (activeName && profiles[activeName]) {
        sel.value = activeName;
      } else if (prevVal && profiles[prevVal]) {
        sel.value = prevVal;
      }
    });
  }
  window.pe2PopulateProfileSelects = pe2PopulateProfileSelects;

  function pe2ApplyNamedProfile(name) {
    const profileName = name || document.getElementById('pe2-profile-select')?.value || document.getElementById('step1-profile-select')?.value;
    if (!profileName) return;

    const profiles = pe2LoadNamedProfiles();
    const p = profiles[profileName];
    if (!p) return;

    // Apply aspect
    if (p.aspect) {
      if (typeof _syncStep1VideoAspect === 'function') _syncStep1VideoAspect(p.aspect);
      if (typeof pe2SetAspect === 'function') pe2SetAspect(p.aspect);
    }
    // Apply pad mode
    if (p.padMode) {
      if (typeof _syncStep1VideoPadMode === 'function') _syncStep1VideoPadMode(p.padMode);
    }
    // Apply field values
    if (p.settings && typeof p.settings === 'object') {
      Object.keys(p.settings).forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const val = p.settings[id];
        if (typeof val === 'boolean') {
          el.checked = val;
        } else {
          el.value = val;
        }
        el.dispatchEvent(new Event('change'));
        el.dispatchEvent(new Event('input'));
      });
    }

    const profileConfig = p.processing || {};
    if (profileConfig.blur_extra_zones) {
      window._procExtraBlurZones = profileConfig.blur_extra_zones.map(z => ({
        height: z.height_pct * 100, width: z.width_pct * 100,
        position: z.position_pct * 100, x: z.x_pct * 100,
        start: z.start_sec ?? '', end: z.end_sec ?? ''
      }));
    }
    if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
    if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
    try { window._procExtAudios = JSON.parse(p.settings?.['proc-ext-audios-json'] || '[]'); } catch (_) { window._procExtAudios = []; }
    if (typeof procRenderExtAudios === 'function') procRenderExtAudios();
    const blurMode = p.settings?.['frame-blur-mode'];
    if (blurMode) document.querySelectorAll('input[name="frame-blur-mode"]').forEach(el => { el.checked = el.value === blurMode; });
    // A hidden video layer must never cover the frame/blur/logo above it.
    window._pe2LayerOrder = ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'];
    window._pe2TrackVisibility = {video:true, frame:true, blur:true, logo:true, overlays:true, subs:true};
    if (Object.prototype.hasOwnProperty.call(profileConfig, 'frame_logo_path')) {
      const logoPath = profileConfig.frame_logo_path || '';
      localStorage.setItem('proc_frame_logo_path', logoPath);
      localStorage.setItem('proc_frame_logo_url', logoPath ? '/temp_uploads/' + encodeURIComponent(logoPath.split(/[\\/]/).pop()) : '');
      if (typeof _loadFrameLogoDefault === 'function') _loadFrameLogoDefault();
    }
    try { localStorage.setItem(_PE2_ACTIVE_PROFILE_KEY, profileName); } catch (_) {}
    pe2PopulateProfileSelects(profileName);

    if (typeof _renderSubOverlay === 'function') _renderSubOverlay();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
    if (typeof _syncProcOriginalVolume === 'function') _syncProcOriginalVolume(document.getElementById('proc-vol-orig'));
    if (typeof refreshSharedConfigSummary === 'function') refreshSharedConfigSummary();

    if (typeof toast === 'function') {
      toast(` Đã áp dụng cấu hình: ${profileName}`, 'success');
    }
  }
  window.pe2ApplyNamedProfile = pe2ApplyNamedProfile;

  async function pe2SaveNamedProfile() {
    const nameInput = document.getElementById('pe2-profile-name');
    let name = nameInput?.value?.trim();
    if (!name) {
      name = prompt('Nhập tên cấu hình cần lưu:');
      if (name) name = name.trim();
    }
    if (!name) return;

    const typeSel = document.getElementById('pe2-profile-type');
    const type = typeSel?.value || 'Tùy chỉnh';

    // Capture settings
    const settings = {};
    if (typeof _PROC_FIELDS !== 'undefined') {
      _PROC_FIELDS.forEach(f => {
        const el = document.getElementById(f.id);
        if (!el) return;
        settings[f.id] = f.type === 'checkbox' ? el.checked : el.value;
      });
    }
    const blurMode = document.querySelector('input[name="frame-blur-mode"]:checked')?.value;
    if (blurMode) settings['frame-blur-mode'] = blurMode;

    const aspect = document.getElementById('proc-preview-aspect')?.value || window._procActiveAspect || '9x16';
    const padMode = document.getElementById('proc-aspect-blur-bg')?.checked ? 'blur' : 'pad';

    let custom = {};
    try {
      const raw = localStorage.getItem(_PE2_PROFILES_KEY);
      if (raw) custom = JSON.parse(raw) || {};
    } catch (_) {}

    custom[name] = {
      name,
      type,
      aspect,
      padMode,
      settings,
      processing: collectProcessConfig()
    };

    try {
      localStorage.setItem(_PE2_PROFILES_KEY, JSON.stringify(custom));
      localStorage.setItem(_PE2_ACTIVE_PROFILE_KEY, name);
    } catch (e) {
      if (typeof toast === 'function') toast('Lỗi lưu cấu hình: ' + e.message, 'error');
      return;
    }

    let savedToServer = false;
    try {
      const response = await fetch('/api/process_profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, profile: custom[name] })
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) throw new Error(result.error || `HTTP ${response.status}`);
      _pe2ServerProfiles[name] = custom[name];
      savedToServer = true;
    } catch (error) {
      if (typeof toast === 'function') toast(` Cấu hình “${name}” (${type}, ${aspect.replace('x', ':')}) chỉ được lưu trong trình duyệt; chưa lưu vào hệ thống: ${error.message}`, 'warning');
    }

    pe2PopulateProfileSelects(name);
    if (nameInput) nameInput.value = '';
    const drawer = document.getElementById('pe2-profile-save-drawer');
    if (drawer) drawer.style.display = 'none';

    if (savedToServer && typeof toast === 'function') {
      toast(` Đã lưu cấu hình “${name}” (${type}, ${aspect.replace('x', ':')}) vào hệ thống và trình duyệt.`, 'success');
    }
  }
  window.pe2SaveNamedProfile = pe2SaveNamedProfile;

  async function pe2DeleteNamedProfile() {
    const profileName = document.getElementById('pe2-profile-select')?.value || document.getElementById('step1-profile-select')?.value;
    if (!profileName) {
      if (typeof toast === 'function') toast('Vui lòng chọn cấu hình cần xóa', 'warning');
      return;
    }

    if (_PE2_DEFAULT_PROFILES[profileName]) {
      if (typeof toast === 'function') toast('Không thể xóa cấu hình mặc định của hệ thống', 'warning');
      return;
    }

    if (!confirm(`Bạn có chắc muốn xóa cấu hình "${profileName}"?`)) return;

    let custom = {};
    try {
      const raw = localStorage.getItem(_PE2_PROFILES_KEY);
      if (raw) custom = JSON.parse(raw) || {};
    } catch (_) {}

    try {
      const response = await fetch('/api/process_profiles', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: profileName })
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      delete _pe2ServerProfiles[profileName];
    } catch (error) {
      if (typeof toast === 'function') toast(` Đã xóa trong trình duyệt nhưng chưa xóa được dữ liệu hệ thống: ${error.message}`, 'warning');
    }

    delete custom[profileName];
    try {
      localStorage.setItem(_PE2_PROFILES_KEY, JSON.stringify(custom));
      if (localStorage.getItem(_PE2_ACTIVE_PROFILE_KEY) === profileName) {
        localStorage.removeItem(_PE2_ACTIVE_PROFILE_KEY);
      }
    } catch (_) {}

    pe2PopulateProfileSelects('');
    if (typeof toast === 'function') {
      toast(` Đã xóa cấu hình: ${profileName}`, 'info');
    }
  }
  window.pe2DeleteNamedProfile = pe2DeleteNamedProfile;

  document.addEventListener('DOMContentLoaded', async () => {
    // Load durable profiles first, then merge/migrate any browser-only profiles.
    try {
      const response = await fetch('/api/process_profiles');
      const result = await response.json();
      if (response.ok && result.ok && result.profiles && typeof result.profiles === 'object') {
        _pe2ServerProfiles = result.profiles;
      }
      const localCustom = JSON.parse(localStorage.getItem(_PE2_PROFILES_KEY) || '{}');
      const missingOnServer = Object.entries(localCustom).filter(([name]) => !_pe2ServerProfiles[name]);
      await Promise.all(missingOnServer.map(([name, profile]) => fetch('/api/process_profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, profile })
      }).then(r => { if (r.ok) _pe2ServerProfiles[name] = profile; })));
    } catch (_) {}
    pe2PopulateProfileSelects();
    setTimeout(pe2PopulateProfileSelects, 300);
  });



// Serialize a saved Step 2 profile using the same collector as manual processing.
window.collectProfileProcessConfig = function(profile) {
  if (!profile) return collectProcessConfig();
  if (profile.processing) return JSON.parse(JSON.stringify(profile.processing));
  const saved = [];
  const ext = window._procExtAudios, overlays = window._videoOverlays;
  try {
    const values = {...(profile.settings || {}), 'proc-preview-aspect': profile.aspect || 'auto'};
    Object.entries(values).forEach(([id, value]) => {
      const el = document.getElementById(id);
      if (!el) return;
      saved.push([el, el.value, el.checked]);
      if (typeof value === 'boolean') el.checked = value; else el.value = value;
    });
    if (values['proc-ext-audios-json']) window._procExtAudios = JSON.parse(values['proc-ext-audios-json']);
    if (values['ov-layers-json']) window._videoOverlays = JSON.parse(values['ov-layers-json']);
    const result = collectProcessConfig();
    if (values['frame-blur-mode']) result.frame_blur_mode = values['frame-blur-mode'];
    return result;
  } finally {
    saved.forEach(([el, value, checked]) => { el.value = value; el.checked = checked; });
    window._procExtAudios = ext; window._videoOverlays = overlays;
  }
};

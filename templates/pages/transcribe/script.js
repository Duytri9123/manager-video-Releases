/**
 * Page Transcribe Script
 * Optimized, self-contained, simple but complete implementation.
 */
(function() {
  let enginesCatalog = null;
  let currentAssPath = '';
  let currentSegments = [];
  let currentAssHeader = '';

  document.addEventListener('DOMContentLoaded', () => {
    trLoadTtsCatalog();
    trSyncProviderOptions();
    
    // Auto-save TTS settings on change
    document.getElementById('tr-tts-engine')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-lang')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-voice')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-dtr-model')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-rate')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-pitch')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-provider')?.addEventListener('change', () => trSyncProviderOptions());
  });

  // Export functions to global scope
  window.trLoadTtsCatalog = trLoadTtsCatalog;
  window.trSyncVoiceOptions = trSyncVoiceOptions;
  window.trSyncProviderOptions = trSyncProviderOptions;
  window.trStartTranscribe = trStartTranscribe;
  window.trExtractAudio = trExtractAudio;
  window.trPreviewVoice = trPreviewVoice;
  window.trRunTtsFromAss = trRunTtsFromAss;
  window.trLoadSubtitles = trLoadSubtitles;
  window.trSaveSubtitles = trSaveSubtitles;
  window.trSaveTtsSettings = trSaveTtsSettings;

  // ── STT PROVIDER & MODEL SYNC ─────────────────────────────────────────
  const TR_GROQ_MODELS = [
    { id: 'whisper-large-v3-turbo', name: 'Whisper Large V3 Turbo (Mặc định - Siêu nhanh)' },
    { id: 'whisper-large-v3', name: 'Whisper Large V3' },
    { id: 'distil-whisper-large-v3-en', name: 'Distil Whisper Large V3 (Tiếng Anh)' }
  ];

  const TR_LOCAL_MODELS = [
    { id: 'base', name: 'Base (Khuyên dùng - Nhẹ & Nhanh)' },
    { id: 'small', name: 'Small (Trung bình)' },
    { id: 'medium', name: 'Medium (Tốt)' },
    { id: 'large-v3', name: 'Large V3 (Chính xác cao)' },
    { id: 'tiny', name: 'Tiny (Nhẹ nhất)' }
  ];

  function _trGroupLabel(prefix) {
    prefix = (prefix || '').toLowerCase().trim();
    const map = {
      cx: 'codex',
      codex: 'codex',
      duytris: 'duytris',
      oc: 'opencode',
      opencode: 'opencode',
      ag: 'antigravity',
      antigravity: 'antigravity',
      gemini: 'antigravity',
      google: 'antigravity',
      openai: 'openai',
      gpt: 'openai',
      o1: 'openai',
      claude: 'anthropic',
      anthropic: 'anthropic',
      qwen: 'qwen',
      deepseek: 'deepseek',
      meta: 'meta',
      groq: 'groq',
    };
    return map[prefix] || prefix || 'others';
  }

  async function trSyncProviderOptions(restoreValue) {
    const provEl = document.getElementById('tr-provider');
    const modelEl = document.getElementById('tr-model');
    const labelEl = document.getElementById('tr-model-label');
    if (!provEl || !modelEl) return;

    const provider = provEl.value || 'antigravity';
    const currentVal = restoreValue || modelEl.value;
    modelEl.innerHTML = '';

    if (provider === 'antigravity' || provider === 'gemini') {
      if (labelEl) {
        labelEl.textContent = 'Mô hình AI (Model)';
        labelEl.title = 'Mô hình từ Provider';
      }

      // Option mặc định tự động theo Provider
      const autoOpt = document.createElement('option');
      autoOpt.value = '';
      autoOpt.textContent = 'Tự động theo Provider';
      modelEl.appendChild(autoOpt);

      try {
        const resAg = await fetch('/api/providers/models?provider=antigravity').then(r => r.json());
        const rawModels = resAg && resAg.ok && Array.isArray(resAg.models)
          ? resAg.models.filter(m => {
              if (!m || m.enabled === false) return false;
              if (m.type && m.type !== 'llm' && m.type !== 'stt') return false;
              const id = String(m.id || m).toLowerCase();
              const name = String(m.name || id).toLowerCase();
              // KHÔNG sử dụng thinking trong phiên âm
              if (id.includes('thinking') || name.includes('thinking')) return false;
              if (id.includes('claude') || id.includes('gpt-oss') || id.includes('image')) return false;
              return true;
            })
          : [];

        const items = [
          { id: 'gemini-3.8-flash-high', name: 'Gemini 3.8 Flash (High)' },
          { id: 'gemini-3.8-flash-medium', name: 'Gemini 3.8 Flash (Medium)' },
          { id: 'gemini-3.8-flash-low', name: 'Gemini 3.8 Flash (Low)' },
          { id: 'gemini-3.7-flash-medium', name: 'Gemini 3.7 Flash (Medium)' },
          { id: 'gemini-3.6-flash-medium', name: 'Gemini 3.6 Flash (Medium)' },
          { id: 'gemini-3.1-pro-low', name: 'Gemini 3.1 Pro (Low)' },
        ];
        items.push(...rawModels);

        const groups = {};
        const existing = new Set();

        items.forEach(m => {
          const mId = String((m && (m.id || m)) || '').trim();
          if (!mId || existing.has(mId)) return;
          existing.add(mId);

          const prefix = mId.includes('/') ? mId.split('/')[0] : 'antigravity';
          const groupName = _trGroupLabel(prefix);
          groups[groupName] = groups[groupName] || [];
          groups[groupName].push({
            id: mId,
            name: (m && m.name) ? m.name : mId
          });
        });

        Object.keys(groups).sort().forEach(grpLabel => {
          const grp = document.createElement('optgroup');
          grp.label = grpLabel;
          groups[grpLabel].forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.name || m.id;
            grp.appendChild(opt);
          });
          modelEl.appendChild(grp);
        });

        if (!items.length) {
          autoOpt.textContent = 'Chưa có model Antigravity được bật trong DB';
          autoOpt.disabled = true;
        } else {
          autoOpt.textContent = `Tự động theo Antigravity (${items[0].name || items[0].id})`;
        }

      } catch (err) {
        console.warn('[Transcribe] Error loading models:', err);
        autoOpt.textContent = 'Không tải được model Antigravity từ DB';
        autoOpt.disabled = true;
      }

      if (currentVal && Array.from(modelEl.options).some(o => o.value === currentVal)) {
        modelEl.value = currentVal;
      }
    } else if (provider === 'groq') {
      if (labelEl) {
        labelEl.textContent = 'Mô hình Groq';
        labelEl.title = 'Mô hình Groq Whisper API';
      }
      TR_GROQ_MODELS.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.name;
        if (item.id === 'whisper-large-v3-turbo' && !currentVal) opt.selected = true;
        modelEl.appendChild(opt);
      });
    } else if (provider === 'model') {
      if (labelEl) {
        labelEl.textContent = 'Mô hình Whisper';
        labelEl.title = 'Mô hình Whisper Local';
      }
      TR_LOCAL_MODELS.forEach(item => {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.name;
        if (item.id === 'base' && !currentVal) opt.selected = true;
        modelEl.appendChild(opt);
      });
    }

    if (currentVal && Array.from(modelEl.options).some(o => o.value === currentVal)) {
      modelEl.value = currentVal;
    }
  }

  // ── CATALOG LOADING ──────────────────────────────────────────────────
  async function trLoadTtsCatalog() {
    try {
      const res = await fetch('/api/tts/engines');
      const data = await res.json();
      if (data && data.ok) {
        enginesCatalog = data.engines || [];
        trPopulateEngines();
      }
      
      try {
        const cfgRes = await fetch('/api/config');
        const cfgData = await cfgRes.json();
        const vp = cfgData?.video_process || {};
        const engineSel = document.getElementById('tr-tts-engine');
        if (engineSel && vp.tts_engine) {
          engineSel.value = vp.tts_engine;
        }
        
        const langSel = document.getElementById('tr-tts-lang');
        if (langSel && (vp.tts_lang || vp.language)) {
          langSel.value = vp.tts_lang || vp.language;
        }
        
        trSyncVoiceOptions();
        
        const voiceSel = document.getElementById('tr-tts-voice');
        if (voiceSel && vp.tts_voice) {
          voiceSel.value = vp.tts_voice;
        }
        
        const rateEl = document.getElementById('tr-tts-rate');
        if (rateEl && vp.tts_rate) rateEl.value = vp.tts_rate;
        const pitchEl = document.getElementById('tr-tts-pitch');
        if (pitchEl && vp.tts_pitch) pitchEl.value = vp.tts_pitch;
      } catch (cfgErr) {
        console.error('Error loading config:', cfgErr);
      }
    } catch (e) {
      console.error('Error loading TTS catalog:', e);
      trAppendLog('Không thể tải danh sách TTS Engine: ' + e.message, 'error');
    }
  }

  function trPopulateEngines() {
    const engineSel = document.getElementById('tr-tts-engine');
    if (!engineSel || !enginesCatalog) return;
    
    const curVal = engineSel.value;
    engineSel.innerHTML = '';
    
    enginesCatalog.forEach(eng => {
      const opt = document.createElement('option');
      opt.value = eng.id;
      opt.textContent = eng.label || eng.id;
      engineSel.appendChild(opt);
    });
    
    if (curVal && Array.from(engineSel.options).some(o => o.value === curVal)) {
      engineSel.value = curVal;
    }
    
    trSyncVoiceOptions();
  }

  // ── VOICE OPTIONS DYNAMIC POPULATION ─────────────────────────────────
  function trSyncVoiceOptions() {
    const engineSel = document.getElementById('tr-tts-engine');
    const langSel = document.getElementById('tr-tts-lang');
    const voiceSel = document.getElementById('tr-tts-voice');
    
    if (!engineSel || !voiceSel || !enginesCatalog) return;
    
    const engineId = engineSel.value;
    const lang = langSel?.value || 'vi';
    
    const engine = enginesCatalog.find(e => e.id === engineId);
    if (!engine) return;
    
    // Populate normal voices
    voiceSel.innerHTML = '';
    const voicesObj = engine.voices || {};
    const voices = voicesObj[lang] || voicesObj['multi'] || [];
    
    if (voices.length === 0) {
      const fallbackLang = Object.keys(voicesObj)[0] || 'vi';
      const fallbackVoices = voicesObj[fallbackLang] || [];
      fallbackVoices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = Array.isArray(v) ? v[0] : v;
        opt.textContent = Array.isArray(v) ? (v[1] || v[0]) : v;
        voiceSel.appendChild(opt);
      });
    } else {
      voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = Array.isArray(v) ? v[0] : v;
        opt.textContent = Array.isArray(v) ? (v[1] || v[0]) : v;
        voiceSel.appendChild(opt);
      });
    }
    
    if (engine.default && Array.from(voiceSel.options).some(o => o.value === engine.default)) {
      voiceSel.value = engine.default;
    }
  }

  // ── TRANSCRIBE OPERATION ──────────────────────────────────────────────
  async function trStartTranscribe() {
    const btn = document.getElementById('btn-tr');
    const trFile = document.getElementById('tr-file')?.value?.trim();
    
    if (!trFile && !window._trSelectedFile) {
      toast('Vui lòng chọn tệp tin video hoặc audio nguồn!', 'warning');
      return;
    }
    
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Đang phiên âm...';
    }
    
    trClearLogs();
    trSetProgress(0, 0, 'Đang chuẩn bị...', 'Khởi tạo...');
    
    const payload = {
      single: window._trSelectedFile ? '' : trFile,
      out_dir: document.getElementById('tr-out')?.value?.trim() || '',
      provider: document.getElementById('tr-provider')?.value || 'antigravity',
      model: document.getElementById('tr-model')?.value || '',
      lang: document.getElementById('tr-lang')?.value || 'zh',
      srt: document.getElementById('tr-srt')?.checked ?? true,
      sc: document.getElementById('tr-sc')?.checked ?? false,
      skip: false
    };
    
    try {
      let body;
      let headers = {};
      
      if (window._trSelectedFile) {
        const form = new FormData();
        form.append('video_file', window._trSelectedFile);
        Object.entries(payload).forEach(([k, v]) => form.append(k, String(v ?? '')));
        body = form;
      } else {
        body = JSON.stringify(payload);
        headers['Content-Type'] = 'application/json';
      }
      
      const res = await fetch('/api/transcribe', { method: 'POST', headers, body });
      if (!res.ok || !res.body) {
        throw new Error('Lỗi HTTP ' + res.status);
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
            if (data.log) trAppendLog(data.log, data.level || 'info');
            if (data.overall !== undefined || data.file !== undefined) {
              trSetProgress(data.overall ?? 0, data.file ?? 0, data.overall_lbl || '', data.file_lbl || '');
            }
          } catch (_) {
            trAppendLog(line, 'info');
          }
        }
      }
      
      toast('Phiên âm hoàn tất!', 'success');
      trSetProgress(100, 100, 'Hoàn thành', 'Đã ghi phụ đề');
      
      // Auto-load edited subtitles
      setTimeout(() => {
        trLoadSubtitles();
      }, 500);
      
    } catch (e) {
      console.error(e);
      trAppendLog('Lỗi phiên âm: ' + e.message, 'error');
      toast('Phiên âm thất bại!', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '🚀 Bắt đầu phiên âm';
      }
    }
  }

  // ── EXTRACT AUDIO ─────────────────────────────────────────────────────
  let _isExtracting = false;
  async function trExtractAudio() {
    if (_isExtracting) return;
    const trFile = document.getElementById('tr-file')?.value?.trim();
    if (!trFile && !window._trSelectedFile) {
      toast('Vui lòng chọn tệp tin video nguồn!', 'warning');
      return;
    }
    
    const btn = document.getElementById('btn-tr-extract');
    _isExtracting = true;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="w-3.5 h-3.5 border-2 border-slate-600 border-t-transparent rounded-full animate-spin inline-block mr-1"></span> Đang tách MP3...';
    }
    
    trAppendLog('Tách âm thanh từ video...', 'info');
    
    try {
      let body;
      let headers = {};
      const payload = {
        video_path: window._trSelectedFile ? '' : trFile,
        output_dir: document.getElementById('tr-out')?.value?.trim() || '',
        format: 'mp3'
      };
      
      if (window._trSelectedFile) {
        const form = new FormData();
        form.append('video_file', window._trSelectedFile);
        Object.entries(payload).forEach(([k, v]) => form.append(k, String(v ?? '')));
        body = form;
      } else {
        body = JSON.stringify(payload);
        headers['Content-Type'] = 'application/json';
      }
      
      const res = await fetch('/api/extract_audio', { method: 'POST', headers, body });
      const data = await res.json();
      if (data && data.ok) {
        trAppendLog('✓ Tách nhạc thành công: ' + data.output_path, 'success');
        toast('Tách nhạc MP3 thành công!', 'success');
      } else {
        throw new Error(data.error || 'Lỗi không xác định');
      }
    } catch (e) {
      trAppendLog('✗ Tách nhạc thất bại: ' + e.message, 'error');
      toast('Tách nhạc thất bại!', 'error');
    } finally {
      _isExtracting = false;
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span>🎵 Tách MP3</span>';
      }
    }
  }

  // ── PREVIEW DYNAMIC VOICE ─────────────────────────────────────────────
  let _isPreviewing = false;
  async function _fetchTtsPreview(payload, onRetry) {
    const options = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    };
    try {
      return await fetch('/api/tts_preview', options);
    } catch (firstError) {
      if (typeof onRetry === 'function') onRetry(firstError);
      await new Promise(resolve => setTimeout(resolve, 800));
      return fetch('/api/tts_preview', options);
    }
  }

  async function trPreviewVoice() {
    if (_isPreviewing) return;
    const text = document.getElementById('tr-preview-text')?.value?.trim();
    const engineSel = document.getElementById('tr-tts-engine');
    const voiceSel = document.getElementById('tr-tts-voice');
    const audio = document.getElementById('tr-preview-audio');
    const btn = document.getElementById('btn-tr-preview');
    
    if (!text) {
      toast('Vui lòng nhập văn bản cần thử giọng!', 'warning');
      return;
    }
    
    _isPreviewing = true;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="w-3.5 h-3.5 border-2 border-slate-600 border-t-transparent rounded-full animate-spin inline-block mr-1"></span> Đang thử giọng...';
    }
    
    let engine = 'vieneu';
    let voice = voiceSel?.value || '';
    
    trAppendLog(`⏳ Đang tạo giọng nói thử nghiệm (${engine} / ${voice}). Lần đầu sau khi mở app có thể cần chờ model khởi động...`, 'info');
    
    try {
      const res = await _fetchTtsPreview({
          text,
          tts_engine: engine,
          tts_voice: voice,
          vieneu_ref_audio: document.getElementById('tr-vieneu-ref')?.value || '',
          tts_rate: document.getElementById('tr-tts-rate')?.value || '+0%',
          tts_pitch: document.getElementById('tr-tts-pitch')?.value || '+0Hz',
          tts_lang: document.getElementById('tr-tts-lang')?.value || 'vi'
        }, () => trAppendLog('⚠️ Kết nối nghe thử bị ngắt, đang tự thử lại một lần...', 'warning'));
      if (!res.ok) {
        let msg = '';
        try {
          const errData = await res.json();
          msg = errData.error || '';
        } catch (_) {
          try { msg = await res.text(); } catch(__) {}
        }
        throw new Error(msg || 'Lỗi HTTP ' + res.status);
      }
      const metricEl = document.getElementById('tr-tts-metrics');
      if (metricEl) {
        const type = res.headers.get('X-TTS-Voice-Type') === 'clone' ? 'clone' : 'preset';
        metricEl.textContent = `⏱ ${res.headers.get('X-TTS-Elapsed') || '?'}s · audio ${res.headers.get('X-TTS-Duration') || '?'}s · RTF ${res.headers.get('X-TTS-RTF') || '?'} · ${res.headers.get('X-TTS-Sample-Rate') || '?'} Hz · ${type} · ${res.headers.get('X-TTS-Quality') || 'unknown'}`;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      audio.src = url;
      audio.classList.remove('hidden');
      audio.style.display = 'block';
      audio.play().catch(() => {});
      toast('▶ Nghe thử giọng thành công', 'success');
      trAppendLog('✅ Đã tạo giọng nói thử nghiệm thành công.', 'success');
    } catch (e) {
      let errMsg = e.message;
      toast('Nghe thử thất bại: ' + errMsg, 'error');
      trAppendLog('❌ Nghe thử thất bại: ' + errMsg, 'error');
    } finally {
      _isPreviewing = false;
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '▶ Nghe thử giọng';
      }
    }
  }

  // ── TTS FROM ASS WORKFLOW ─────────────────────────────────────────────
  let _isTtsRunning = false;
  async function trRunTtsFromAss() {
    if (_isTtsRunning) return;
    const trFile = document.getElementById('tr-file')?.value?.trim();
    const btn = document.getElementById('btn-tr-tts');
    
    let assPath = trFile;
    if (assPath && !assPath.endsWith('.ass')) {
      const dotIdx = assPath.lastIndexOf('.');
      assPath = (dotIdx !== -1 ? assPath.substring(0, dotIdx) : assPath) + '.ass';
    }
    
    if (!assPath && !window._trSelectedFile) {
      toast('Vui lòng chọn tệp tin hoặc lưu phụ đề trước!', 'warning');
      return;
    }
    
    _isTtsRunning = true;
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin inline-block mr-1"></span> Đang lồng tiếng...';
    }
    
    trClearLogs();
    trAppendLog('Bắt đầu lồng tiếng từ file phụ đề .ass...', 'info');
    
    let engine = 'vieneu';
    let voice = document.getElementById('tr-tts-voice')?.value || '';
    
    const payload = {
      ass_path: window._trSelectedFile ? '' : assPath,
      output_dir: document.getElementById('tr-out')?.value?.trim() || '',
      tts_engine: engine,
      tts_voice: voice,
      vieneu_ref_audio: document.getElementById('tr-vieneu-ref')?.value || '',
      tts_rate: document.getElementById('tr-tts-rate')?.value || '+0%',
      tts_pitch: document.getElementById('tr-tts-pitch')?.value || '+0Hz',
      tts_lang: document.getElementById('tr-tts-lang')?.value || 'vi'
    };
    
    try {
      let body;
      let headers = {};
      
      if (window._trSelectedFile && window._trSelectedFile.name.endsWith('.ass')) {
        const form = new FormData();
        form.append('ass_file', window._trSelectedFile);
        Object.entries(payload).forEach(([k, v]) => form.append(k, String(v ?? '')));
        body = form;
      } else {
        body = JSON.stringify(payload);
        headers['Content-Type'] = 'application/json';
      }
      
      const res = await fetch('/api/tts_from_ass', { method: 'POST', headers, body });
      if (!res.ok || !res.body) {
        throw new Error('Lỗi HTTP ' + res.status);
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
            if (data.log) trAppendLog(data.log, data.level || 'info');
            if (data.overall !== undefined) {
              trSetProgress(data.overall ?? 0, 0, data.overall_lbl || '', '');
            }
          } catch (_) {
            trAppendLog(line, 'info');
          }
        }
      }
      
      toast('Lồng tiếng hoàn tất!', 'success');
      trSetProgress(100, 100, 'Hoàn thành', '');
      
    } catch (e) {
      trAppendLog('Lỗi lồng tiếng: ' + e.message, 'error');
      toast('Lồng tiếng thất bại!', 'error');
    } finally {
      _isTtsRunning = false;
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span>🔊 Lồng tiếng &amp; Xuất MP3</span>';
      }
    }
  }

  // ── SUBTITLE EDITOR LOAD & SAVE ────────────────────────────────────────
  function _guessAssPath(srcPath) {
    if (!srcPath) return '';
    const clean = srcPath.replace(/\\/g, '/');
    if (clean.endsWith('.ass')) return srcPath;
    
    // If it's a video file, replace suffix with .ass
    const dotIdx = srcPath.lastIndexOf('.');
    if (dotIdx !== -1) {
      return srcPath.substring(0, dotIdx) + '.ass';
    }
    return srcPath + '.ass';
  }

  async function trLoadSubtitles() {
    const trFile = document.getElementById('tr-file')?.value?.trim();
    if (!trFile && !window._trSelectedFile) {
      toast('Vui lòng nhập đường dẫn tệp nguồn trước!', 'warning');
      return;
    }
    
    let path = window._trSelectedFile ? window._trSelectedFile.name : trFile;
    path = _guessAssPath(path);
    currentAssPath = path;
    
    trAppendLog('Đang tải phụ đề từ: ' + path, 'info');
    
    try {
      const res = await fetch('/api/proc_read_ass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await res.json();
      if (!data || !data.ok) {
        throw new Error(data.error || 'Lỗi đọc tệp');
      }
      
      trParseAssContent(data.content || '');
      trRenderSubtitles();
      toast('Tải phụ đề thành công!', 'success');
    } catch (e) {
      trAppendLog('Lỗi tải phụ đề: ' + e.message + '. Nếu vừa chạy phiên âm, có thể file .ass đang được lưu.', 'warning');
    }
  }

  function trParseAssContent(content) {
    const lines = content.split('\n');
    currentAssHeader = '';
    currentSegments = [];
    
    let headerMode = true;
    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      if (trimmed.startsWith('Dialogue:')) {
        headerMode = false;
        const seg = _parseDialogueLine(line);
        if (seg) {
          currentSegments.push(seg);
        }
      } else if (headerMode) {
        currentAssHeader += line + '\n';
      }
    });
  }

  function _parseDialogueLine(line) {
    const rest = line.substring(9).trim();
    const parts = [];
    let current = '';
    let commaCount = 0;
    for (let i = 0; i < rest.length; i++) {
      if (rest[i] === ',' && commaCount < 9) {
        parts.push(current);
        current = '';
        commaCount++;
      } else {
        current += rest[i];
      }
    }
    parts.push(current);
    if (parts.length < 10) return null;
    return {
      layer: parts[0],
      start: parts[1],
      end: parts[2],
      style: parts[3],
      name: parts[4],
      marginL: parts[5],
      marginR: parts[6],
      marginV: parts[7],
      effect: parts[8],
      text: parts[9]
    };
  }

  function trRenderSubtitles() {
    const wrap = document.getElementById('tr-sub-editor-wrap');
    if (!wrap) return;
    
    if (currentSegments.length === 0) {
      wrap.innerHTML = `
        <div class="p-8 text-center text-slate-400 text-xs flex flex-col items-center justify-center gap-2 h-full">
          <span>📭 Tệp phụ đề rỗng hoặc chưa chứa Dialogue.</span>
        </div>
      `;
      return;
    }
    
    let html = `
      <div class="tr-sub-editor-list">
        <div class="tr-sub-editor-header">
          <div class="text-center">Dòng</div>
          <div>Bắt đầu</div>
          <div>Kết thúc</div>
          <div>Nội dung phụ đề / Dịch</div>
          <div class="text-center">Thao tác</div>
        </div>
        <div class="flex-1 overflow-y-auto" style="max-height: 420px;">
    `;
    
    currentSegments.forEach((seg, idx) => {
      html += `
        <div class="tr-sub-row" data-index="${idx}">
          <div class="tr-sub-index">${idx + 1}</div>
          <input type="text" class="tr-sub-time-input tr-sub-start" value="${seg.start}" onchange="trUpdateSegTime(${idx}, 'start', this.value)">
          <input type="text" class="tr-sub-time-input tr-sub-end" value="${seg.end}" onchange="trUpdateSegTime(${idx}, 'end', this.value)">
          <textarea class="tr-sub-text-input" oninput="trUpdateSegText(${idx}, this.value)" rows="1">${seg.text}</textarea>
          <div class="flex justify-center gap-1.5">
            <button class="btn btn-secondary btn-sm p-1.5" onclick="trDeleteSegment(${idx})" title="Xoá dòng này">🗑</button>
          </div>
        </div>
      `;
    });
    
    html += `
        </div>
      </div>
    `;
    
    wrap.innerHTML = html;
  }

  window.trUpdateSegTime = function(idx, field, value) {
    if (currentSegments[idx]) {
      currentSegments[idx][field] = value.trim();
    }
  };

  window.trUpdateSegText = function(idx, value) {
    if (currentSegments[idx]) {
      currentSegments[idx].text = value;
    }
  };

  window.trDeleteSegment = function(idx) {
    currentSegments.splice(idx, 1);
    trRenderSubtitles();
  };

  async function trSaveSubtitles() {
    if (!currentAssPath) {
      toast('Không có file phụ đề nào đang được mở!', 'warning');
      return;
    }
    
    let content = currentAssHeader;
    currentSegments.forEach(seg => {
      content += `Dialogue: ${seg.layer},${seg.start},${seg.end},${seg.style},${seg.name},${seg.marginL},${seg.marginR},${seg.marginV},${seg.effect},${seg.text}\n`;
    });
    
    try {
      const res = await fetch('/api/proc_save_ass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentAssPath, content })
      });
      const data = await res.json();
      if (data && data.ok) {
        toast('Lưu phụ đề thành công!', 'success');
        trAppendLog('✓ Đã lưu thay đổi vào: ' + currentAssPath, 'success');
      } else {
        throw new Error(data.error || 'Lỗi lưu tệp');
      }
    } catch (e) {
      toast('Lưu thất bại: ' + e.message, 'error');
    }
  }

  // ── LOG & PROGRESS HELPERS ───────────────────────────────────────────
  function trClearLogs() {
    const logBox = document.getElementById('tr-log');
    if (logBox) logBox.innerHTML = '';
  }

  let lastLogMsg = '';
  let lastLogTime = 0;

  function trAppendLog(msg, level) {
    const logBox = document.getElementById('tr-log');
    if (!logBox) return;
    
    const now = Date.now();
    if (msg === lastLogMsg && (now - lastLogTime) < 1500) {
      return;
    }
    lastLogMsg = msg;
    lastLogTime = now;
    
    const div = document.createElement('div');
    div.className = 'log-line ' + (level || 'info');
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    
    // Apply basic coloring classes
    if (level === 'error') div.style.color = '#ef4444';
    else if (level === 'success') div.style.color = '#10b981';
    else if (level === 'warning') div.style.color = '#f59e0b';
    
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
  }

  function trSetProgress(overallPct, filePct, overallLbl, fileLbl) {
    const pbOverall = document.getElementById('pb-tr-overall');
    const pbOverallPct = document.getElementById('pb-tr-overall-pct');
    const lblOverall = document.getElementById('lbl-tr-overall');
    
    const pbFile = document.getElementById('pb-tr-file');
    const pbFilePct = document.getElementById('pb-tr-file-pct');
    const lblFile = document.getElementById('lbl-tr-file');
    
    if (pbOverall) pbOverall.style.width = overallPct + '%';
    if (pbOverallPct) pbOverallPct.textContent = overallPct + '%';
    if (lblOverall && overallLbl) lblOverall.textContent = overallLbl;
    
    if (pbFile) pbFile.style.width = filePct + '%';
    if (pbFilePct) pbFilePct.textContent = filePct + '%';
    if (lblFile && fileLbl) lblFile.textContent = fileLbl;
  }
  async function trSaveTtsSettings() {
    if (!enginesCatalog) return;
    
    let engine = document.getElementById('tr-tts-engine')?.value || 'edge-tts';
    let voice = document.getElementById('tr-tts-voice')?.value || '';
    const lang = document.getElementById('tr-tts-lang')?.value || 'vi';
    const rate = document.getElementById('tr-tts-rate')?.value || '+0%';
    const pitch = document.getElementById('tr-tts-pitch')?.value || '+0Hz';
    
    const payload = {
      video_process: {
        tts_engine: engine,
        tts_voice: voice,
        tts_lang: lang,
        language: lang,
        tts_rate: rate,
        tts_pitch: pitch
      }
    };
    
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } catch (e) {
      console.error('Failed to sync TTS settings to config:', e);
    }
  }

})();

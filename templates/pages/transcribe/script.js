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
    
    // Auto-save TTS settings on change
    document.getElementById('tr-tts-engine')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-lang')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-voice')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-9r-model')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-rate')?.addEventListener('change', trSaveTtsSettings);
    document.getElementById('tr-tts-pitch')?.addEventListener('change', trSaveTtsSettings);
  });

  // Export functions to global scope
  window.trLoadTtsCatalog = trLoadTtsCatalog;
  window.trSyncVoiceOptions = trSyncVoiceOptions;
  window.trSync9RouterVoices = trSync9RouterVoices;
  window.trStartTranscribe = trStartTranscribe;
  window.trExtractAudio = trExtractAudio;
  window.trPreviewVoice = trPreviewVoice;
  window.trRunTtsFromAss = trRunTtsFromAss;
  window.trLoadSubtitles = trLoadSubtitles;
  window.trSaveSubtitles = trSaveSubtitles;
  window.trSaveTtsSettings = trSaveTtsSettings;

  // ── CATALOG LOADING ──────────────────────────────────────────────────
  async function trLoadTtsCatalog() {
    try {
      const res = await fetch('/api/tts/engines?include_9router=1');
      const data = await res.json();
      if (data && data.ok) {
        enginesCatalog = data.engines || [];
        trPopulateEngines();
      }
      
      // Load 9Router API Key to display
      try {
        const cfgRes = await fetch('/api/config');
        const cfgData = await cfgRes.json();
        const nrKey = cfgData?.nine_router?.api_key || '';
        const keyEl = document.getElementById('tr-9r-api-key');
        const statusEl = document.getElementById('tr-9r-api-key-status');
        if (keyEl) {
          if (nrKey) {
            keyEl.value = nrKey.slice(0, 8) + '•'.repeat(Math.max(10, nrKey.length - 8));
            if (statusEl) {
              statusEl.innerHTML = '<span style="color:#888">⏳ Đang kiểm tra key...</span>';
              try {
                const checkRes = await fetch('/api/test_api_key', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ provider: '9router', key: nrKey })
                });
                const checkData = await checkRes.json();
                if (checkData.ok) {
                  statusEl.innerHTML = '<span style="color:#10b981; font-weight:600">● 9Router API Key hoạt động tốt (Còn hạn)</span>';
                } else {
                  statusEl.innerHTML = `<span style="color:#ef4444; font-weight:600">⚠️ 9Router API Key lỗi: ${checkData.error || 'Không hợp lệ'}</span>`;
                }
              } catch (checkErr) {
                statusEl.innerHTML = '<span style="color:#f59e0b; font-weight:600">⚠️ Không thể kiểm tra thời hạn key (Lỗi kết nối)</span>';
              }
            }
          } else {
            keyEl.value = '';
            if (statusEl) {
              statusEl.innerHTML = '<span style="color:#ef4444; font-weight:600">⚠️ Thiếu API Key 9Router. Vui lòng vào mục Cài đặt hoặc Chat Bot để thêm key.</span>';
            }
          }
        }
        // Sync engine dropdown
        const vp = cfgData?.video_process || {};
        const engineSel = document.getElementById('tr-tts-engine');
        if (engineSel && vp.tts_engine) {
          engineSel.value = vp.tts_engine;
        }
        
        // Sync language dropdown
        const langSel = document.getElementById('tr-tts-lang');
        if (langSel && (vp.tts_lang || vp.language)) {
          langSel.value = vp.tts_lang || vp.language;
        }
        
        // Populate and sync voice
        trSyncVoiceOptions();
        
        const voiceSel = document.getElementById('tr-tts-voice');
        if (voiceSel && vp.tts_voice) {
          if (vp.tts_voice.includes('|')) {
            const parts = vp.tts_voice.split('|');
            const modelSel = document.getElementById('tr-9r-model');
            if (modelSel) {
              modelSel.value = parts[0];
              trSync9RouterVoices();
            }
            if (voiceSel) {
              voiceSel.value = parts[1];
            }
          } else {
            voiceSel.value = vp.tts_voice;
          }
        }
        
        // Sync rate and pitch
        const rateEl = document.getElementById('tr-tts-rate');
        if (rateEl && vp.tts_rate) rateEl.value = vp.tts_rate;
        const pitchEl = document.getElementById('tr-tts-pitch');
        if (pitchEl && vp.tts_pitch) pitchEl.value = vp.tts_pitch;
      } catch (cfgErr) {
        console.error('Error loading config for API key display:', cfgErr);
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
    
    // Split into Local and 9Router engines
    const locals = enginesCatalog.filter(e => e.backend !== '9router');
    const nineR = enginesCatalog.filter(e => e.backend === '9router');
    
    const addOpt = (parent, eng) => {
      const opt = document.createElement('option');
      opt.value = eng.id;
      opt.textContent = eng.label || eng.id;
      parent.appendChild(opt);
    };

    if (nineR.length) {
      const grpLocal = document.createElement('optgroup');
      grpLocal.label = 'Local / Tích hợp';
      locals.forEach(e => addOpt(grpLocal, e));
      engineSel.appendChild(grpLocal);
      
      const grp9R = document.createElement('optgroup');
      grp9R.label = '9Router Cloud';
      nineR.forEach(e => addOpt(grp9R, e));
      engineSel.appendChild(grp9R);
    } else {
      locals.forEach(e => addOpt(engineSel, e));
    }
    
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
    const field9R = document.getElementById('tr-9r-fields');
    
    if (!engineSel || !voiceSel || !enginesCatalog) return;
    
    const engineId = engineSel.value;
    const lang = langSel?.value || 'vi';
    
    const engine = enginesCatalog.find(e => e.id === engineId);
    if (!engine) return;
    
    // Toggle 9Router specific model fields
    if (engineId === '9router') {
      if (field9R) field9R.style.display = '';
      trPopulate9RouterModels(engine);
      return;
    } else {
      if (field9R) field9R.style.display = 'none';
    }
    
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

  function trPopulate9RouterModels(engine) {
    const modelSel = document.getElementById('tr-9r-model');
    if (!modelSel) return;
    
    const curVal = modelSel.value;
    modelSel.innerHTML = '';
    
    const models = engine.models || [];
    const groups = {};
    models.forEach(m => {
      const g = m.group || m.provider || '9router';
      (groups[g] = groups[g] || []).push(m);
    });
    
    Object.keys(groups).forEach(g => {
      const og = document.createElement('optgroup');
      og.label = g.toUpperCase();
      groups[g].forEach(m => {
        const o = document.createElement('option');
        o.value = m.id;
        o.textContent = m.label || m.id;
        og.appendChild(o);
      });
      modelSel.appendChild(og);
    });
    
    if (curVal && Array.from(modelSel.options).some(o => o.value === curVal)) {
      modelSel.value = curVal;
    } else {
      modelSel.value = engine.defaultModel || (models[0] && models[0].id) || '';
    }
    
    trSync9RouterVoices();
  }

  function trSync9RouterVoices() {
    const engineSel = document.getElementById('tr-tts-engine');
    const modelSel = document.getElementById('tr-9r-model');
    const voiceSel = document.getElementById('tr-tts-voice');
    
    if (!engineSel || !modelSel || !voiceSel || !enginesCatalog) return;
    
    const engine = enginesCatalog.find(e => e.id === engineSel.value);
    if (!engine || engine.backend !== '9router') return;
    
    const modelId = modelSel.value;
    const model = (engine.models || []).find(m => m.id === modelId);
    const provider = model ? model.provider : 'openai';
    
    voiceSel.innerHTML = '';
    const voicesByProvider = engine.voicesByProvider || {};
    const voices = voicesByProvider[provider] || voicesByProvider['openai'] || [];
    
    voices.forEach(v => {
      const opt = document.createElement('option');
      opt.value = Array.isArray(v) ? v[0] : v;
      opt.textContent = Array.isArray(v) ? (v[1] || v[0]) : v;
      voiceSel.appendChild(opt);
    });
    
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
      provider: document.getElementById('tr-provider')?.value || 'groq',
      model: document.getElementById('tr-model')?.value || 'base',
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
  async function trExtractAudio() {
    const trFile = document.getElementById('tr-file')?.value?.trim();
    if (!trFile && !window._trSelectedFile) {
      toast('Vui lòng chọn tệp tin video nguồn!', 'warning');
      return;
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
    }
  }

  // ── PREVIEW DYNAMIC VOICE ─────────────────────────────────────────────
  async function trPreviewVoice() {
    const text = document.getElementById('tr-preview-text')?.value?.trim();
    const engineSel = document.getElementById('tr-tts-engine');
    const voiceSel = document.getElementById('tr-tts-voice');
    const audio = document.getElementById('tr-preview-audio');
    
    if (!text) {
      toast('Vui lòng nhập văn bản cần thử giọng!', 'warning');
      return;
    }
    
    let engine = engineSel?.value || 'edge-tts';
    let voice = voiceSel?.value || '';
    
    const cat = enginesCatalog.find(e => e.id === engine);
    if (cat && cat.backend === '9router') {
      const model = document.getElementById('tr-9r-model')?.value || '';
      voice = model + '|' + voice;
      engine = '9router';
    }
    
    // Show log of the request
    trAppendLog(`⏳ Đang tạo giọng nói thử nghiệm (${engine} / ${voice.split('|')[0] || voice})...`, 'info');
    
    try {
      const res = await fetch('/api/tts_preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          tts_engine: engine,
          tts_voice: voice,
          tts_rate: document.getElementById('tr-tts-rate')?.value || '+0%',
          tts_pitch: document.getElementById('tr-tts-pitch')?.value || '+0Hz',
          tts_lang: document.getElementById('tr-tts-lang')?.value || 'vi'
        })
      });
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
      if (engine === '9router' && (errMsg.includes('401') || errMsg.includes('403') || errMsg.toLowerCase().includes('api key'))) {
        errMsg = 'Thiếu hoặc sai 9Router API Key. Vui lòng kiểm tra lại cấu hình API Key trong mục Cài đặt.';
      }
      toast('Nghe thử thất bại: ' + errMsg, 'error');
      trAppendLog('❌ Nghe thử thất bại: ' + errMsg, 'error');
    }
  }

  // ── TTS FROM ASS WORKFLOW ─────────────────────────────────────────────
  async function trRunTtsFromAss() {
    const trFile = document.getElementById('tr-file')?.value?.trim();
    
    // Guess associated .ass file if video is selected
    let assPath = trFile;
    if (assPath && !assPath.endsWith('.ass')) {
      const dotIdx = assPath.lastIndexOf('.');
      assPath = (dotIdx !== -1 ? assPath.substring(0, dotIdx) : assPath) + '.ass';
    }
    
    if (!assPath && !window._trSelectedFile) {
      toast('Vui lòng chọn tệp tin hoặc lưu phụ đề trước!', 'warning');
      return;
    }
    
    trClearLogs();
    trAppendLog('Bắt đầu lồng tiếng từ file phụ đề .ass...', 'info');
    
    let engine = document.getElementById('tr-tts-engine')?.value || 'edge-tts';
    let voice = document.getElementById('tr-tts-voice')?.value || '';
    
    const cat = enginesCatalog?.find(e => e.id === engine);
    if (cat && cat.backend === '9router') {
      const model = document.getElementById('tr-9r-model')?.value || '';
      voice = model + '|' + voice;
      engine = '9router';
    }
    
    const payload = {
      ass_path: window._trSelectedFile ? '' : assPath,
      output_dir: document.getElementById('tr-out')?.value?.trim() || '',
      tts_engine: engine,
      tts_voice: voice,
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

  function trAppendLog(msg, level) {
    const logBox = document.getElementById('tr-log');
    if (!logBox) return;
    
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
    
    const cat = enginesCatalog.find(e => e.id === engine);
    if (cat && cat.backend === '9router') {
      const model = document.getElementById('tr-9r-model')?.value || '';
      voice = model + '|' + voice;
      engine = '9router';
    }
    
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

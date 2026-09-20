  function _getSavedAiVideoModel() {
    try {
      const saved = localStorage.getItem('proc_ai_video_nine_model');
      if (saved && saved !== 'none') return saved;
      if (saved === 'none') return 'none';
      const presets = JSON.parse(localStorage.getItem('proc_settings_defaults_v2') || '{}');
      const cur = presets[window._procActiveAspect || '16x9'] || presets['16x9'] || presets['9x16'] || {};
      if (cur['proc-ai-video-nine-model']) return cur['proc-ai-video-nine-model'];
    } catch (_) {}
    return '';
  }

  function _syncAiVideoModel(val) {
    val = (val === undefined || val === null) ? '' : String(val);
    const sel1 = document.getElementById('proc-ai-video-nine-model');
    const sel2 = document.getElementById('proc-ai-video-nine-model-step2');
    const autoChk = document.getElementById('proc-ai-video-auto');

    if (sel1 && sel1.value !== val) {
      if (Array.from(sel1.options).some(o => o.value === val)) sel1.value = val;
    }
    if (sel2 && sel2.value !== val) {
      if (Array.from(sel2.options).some(o => o.value === val)) sel2.value = val;
    }
    if (autoChk) {
      autoChk.checked = (val !== 'none');
    }

    try {
      localStorage.setItem('proc_ai_video_nine_model', val);
      const presets = JSON.parse(localStorage.getItem('proc_settings_defaults_v2') || '{}');
      const aspect = window._procActiveAspect || '16x9';
      if (!presets[aspect]) presets[aspect] = {};
      presets[aspect]['proc-ai-video-nine-model'] = val;
      if (presets['16x9']) presets['16x9']['proc-ai-video-nine-model'] = val;
      if (presets['9x16']) presets['9x16']['proc-ai-video-nine-model'] = val;
      localStorage.setItem('proc_settings_defaults_v2', JSON.stringify(presets));
      if (typeof procSaveStep === 'function') procSaveStep(1, true);
    } catch (_) {}
  }
  window._syncAiVideoModel = _syncAiVideoModel;

  document.addEventListener('DOMContentLoaded', () => {
    if (typeof _syncColorPicker === 'function') _syncColorPicker();
    if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
    if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
    if (typeof loadProcAiVideoModels === 'function') loadProcAiVideoModels();

    // Sync proc-ai-video-nine-model with proc-ai-video-auto
    const selectModel = document.getElementById('proc-ai-video-nine-model');
    const selectModel2 = document.getElementById('proc-ai-video-nine-model-step2');
    const autoChk = document.getElementById('proc-ai-video-auto');

    if (selectModel) {
      selectModel.addEventListener('change', function() {
        _syncAiVideoModel(this.value);
      });
    }
    if (selectModel2) {
      selectModel2.addEventListener('change', function() {
        _syncAiVideoModel(this.value);
      });
    }
    if (autoChk) {
      autoChk.addEventListener('change', function() {
        if (!this.checked) {
          _syncAiVideoModel('none');
        } else {
          loadProcAiVideoModels(true);
        }
      });
    }
  });
  window._procAiAnalyzing = false;
  window._procAiVideoModelsLoaded = false;
  function _procAiEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }
  function _procAiSetStatus(text, kind) {
    const el = document.getElementById('proc-ai-video-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.borderColor = kind === 'ok' ? 'rgba(34,197,94,.45)' : (kind === 'error' ? 'rgba(239,68,68,.45)' : 'var(--border)');
    el.style.color = kind === 'ok' ? '#15803d' : (kind === 'error' ? '#b91c1c' : 'var(--text-muted)');
  }
  function _procAiVideoGroupLabel(prefix) {
    prefix = (prefix || '').toLowerCase().trim();
    const map = {
      cx: 'codex',
      codex: 'codex',
      openai: 'openai',
      gpt: 'openai',
      o1: 'openai',
      antigravity: 'antigravity',
      ag: 'antigravity',
      gemini: 'antigravity',
      google: 'antigravity',
      anthropic: 'anthropic',
      claude: 'anthropic',
      kr: 'kr',
      xai: 'xai',
      qwen: 'qwen',
      deepseek: 'deepseek',
      meta: 'meta',
      groq: 'groq',
    };
    return map[prefix] || prefix || 'others';
  }
  async function _procAiFetchJson(url, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || 5000);
    try {
      const res = await fetch(url, { signal: ctrl.signal });
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }
  async function loadProcAiVideoModels(force) {
    const sel1 = document.getElementById('proc-ai-video-nine-model');
    const sel2 = document.getElementById('proc-ai-video-nine-model-step2');
    const selects = [sel1, sel2].filter(Boolean);
    if (!selects.length) return;
    if (window._procAiVideoModelsLoaded && !force) return;

    const savedTarget = _getSavedAiVideoModel();

    try {
      const response = await _procAiFetchJson('/api/providers/models?provider=antigravity', 5000);
      const items = response && response.ok && Array.isArray(response.models) ? response.models : [];
      window._procAiVideoModelsLoaded = true;

      // DB is the single source of truth for Antigravity models and ordering.
      const agModels = items
        .filter(m => m && m.enabled !== false && (!m.type || m.type === 'llm'))
        .map(m => ({
          id: String(m.id || '').trim(),
          name: String(m.name || m.id || '').trim()
        }))
        .filter(m => m.id && m.id !== 'none');

      selects.forEach(sel => {
        sel.innerHTML = '<option value="none">Tắt (Không đọc)</option>';
        const grp = document.createElement('optgroup');
        grp.setAttribute('data-nr', '1');
        grp.label = 'antigravity';

        const added = new Set();
        agModels.forEach(item => {
          if (!added.has(item.id)) {
            const opt = document.createElement('option');
            opt.value = item.id;
            opt.textContent = item.name;
            grp.appendChild(opt);
            added.add(item.id);
          }
        });
        if (agModels.length) {
          sel.appendChild(grp);
        } else {
          const empty = document.createElement('option');
          empty.value = '';
          empty.disabled = true;
          empty.textContent = 'Chưa có model Antigravity được bật trong DB';
          sel.appendChild(empty);
        }

        if (savedTarget && Array.from(sel.options).some(o => o.value === savedTarget)) {
          sel.value = savedTarget;
        } else {
          sel.value = agModels[0]?.id || 'none';
        }
      });
      if (agModels.length && !savedTarget) _syncAiVideoModel(agModels[0].id);
    } catch (_) {
      window._procAiVideoModelsLoaded = false;
    }
  }
  function procAiVideoProviderChanged() {
    const row = document.getElementById('proc-ai-video-nine-model-row');
    if (row) row.style.display = '';
    loadProcAiVideoModels();
  }
  function _procAiVideoPath() {
    const source = (typeof _getPreviewVideoPath === 'function') ? _getPreviewVideoPath() : null;
    if (!source || !source.val) return '';
    if (source.type === 'url' || /^https?:\/\//i.test(source.val)) return '';
    return source.val;
  }
  function _procAiAnalysisText(result) {
    if (!result) return '';
    const cover = Array.isArray(result.needs_cover) ? result.needs_cover : [];
    const zones = Array.isArray(result.suggested_blur_zones) ? result.suggested_blur_zones : [];
    const titles = result.title_suggestions || {};
    return [
      result.summary ? `Tóm tắt video: ${result.summary}` : '',
      result.visual_style ? `Đặc điểm hình ảnh: ${result.visual_style}` : '',
      result.source_language ? `Ngôn ngữ gốc phát hiện: ${result.source_language}` : '',
      cover.length ? `Thành phần cần che: ${cover.map(x => x.label || x.type || '').filter(Boolean).join('; ')}` : '',
      zones.length ? `Vùng che AI đề xuất: ${zones.map(x => x.label || x.reason || '').filter(Boolean).join('; ')}` : '',
      titles.youtube ? `Gợi ý tiêu đề YouTube: ${titles.youtube}` : (titles.short ? `Gợi ý tiêu đề: ${titles.short}` : ''),
      result.analysis_notes ? `Ghi chú AI: ${result.analysis_notes}` : '',
    ].filter(Boolean).join('\n');
  }
  function procRenderAiAnalysis() {
    const box = document.getElementById('proc-ai-video-result');
    if (!box) return;
    const payload = window._procVideoAiAnalysis;
    const result = payload?.result;
    if (!result) {
      box.innerHTML = '';
      return;
    }
    const cover = Array.isArray(result.needs_cover) ? result.needs_cover : [];
    const zones = Array.isArray(result.suggested_blur_zones) ? result.suggested_blur_zones : [];
    const titles = result.title_suggestions || {};
    const coverHtml = cover.length
      ? `<ul>${cover.map(item => `<li><b>${_procAiEsc(item.label || item.type || 'Thành phần')}</b>: ${_procAiEsc(item.reason || '')} <span class="pe2-ai-pill">${Math.round((item.confidence || 0) * 100)}%</span></li>`).join('')}</ul>`
      : '<div class="text-xs text-muted">AI chưa thấy chữ/logo cần che rõ ràng.</div>';
    const zoneHtml = zones.length
      ? `<ul>${zones.map(z => `<li><b>${_procAiEsc(z.label || 'Vùng che')}</b>: X ${Math.round(z.x_pct ?? 50)}%, Y ${Math.round(z.position_pct ?? 50)}%, rộng ${Math.round(z.width_pct ?? 80)}%, cao ${Math.round(z.height_pct ?? 12)}%</li>`).join('')}</ul>`
      : '<div class="text-xs text-muted">Không có vùng che đề xuất.</div>';
    const titleBits = [titles.short, titles.youtube, titles.tiktok, titles.facebook].filter(Boolean);
    box.innerHTML = `
      <div class="pe2-ai-box">
        <h4>Tổng quan</h4>
        <div>${_procAiEsc(result.summary || 'Chưa có tóm tắt.')}</div>
        ${result.visual_style ? `<div class="mt-4 text-xs text-muted">${_procAiEsc(result.visual_style)}</div>` : ''}
        ${result.source_language ? `<div class="mt-4"><span class="pe2-ai-pill">Ngôn ngữ: ${_procAiEsc(result.source_language)}</span></div>` : ''}
      </div>
      <div class="pe2-ai-box">
        <h4>Thành phần cần che</h4>
        ${coverHtml}
      </div>
      <div class="pe2-ai-box">
        <h4>Vùng che AI đề xuất</h4>
        ${zoneHtml}
      </div>
      ${titleBits.length ? `<div class="pe2-ai-box"><h4>Gợi ý tiêu đề</h4>${titleBits.map(t => `<span class="pe2-ai-pill">${_procAiEsc(t)}</span>`).join('')}</div>` : ''}
      ${result.analysis_notes ? `<div class="pe2-ai-box"><h4>Ghi chú</h4><div>${_procAiEsc(result.analysis_notes)}</div></div>` : ''}
    `;
  }
  function procToggleAiAnalysis(input) {
    window._procUseAiAnalysis = !!input?.checked;
    if (window._procUseAiAnalysis) {
      const path = _procAiVideoPath();
      if (path && !window._procVideoAiAnalysis) {
        procAnalyzeVideoAI({ force: false });
      } else {
        procApplyAiAnalysis();
        _procAiSetStatus('Đang sử dụng phân tích AI cho vùng che và gợi ý đăng bài.', 'ok');
      }
    } else {
      procRemoveAiZones();
      _procAiSetStatus('Đã tắt sử dụng phân tích AI. Nội dung phân tích vẫn được giữ để tham khảo.', 'info');
    }
  }
  async function procAnalyzeVideoAI(opts) {
    opts = opts || {};
    const path = _procAiVideoPath();
    const btn = document.getElementById('proc-ai-video-btn');
    const useToggle = document.getElementById('proc-use-ai-analysis');
    if (!path) {
      window._procVideoAiAnalysis = null;
      window._procUseAiAnalysis = false;
      if (useToggle) { useToggle.checked = false; }
      procRenderAiAnalysis();
      _procAiSetStatus('Không đọc được video: video chưa tải xong hoặc chưa có file local.', 'error');
      return null;
    }
    if (!opts.force && window._procVideoAiCache[path]) {
      window._procVideoAiAnalysis = window._procVideoAiCache[path];
      if (useToggle) { useToggle.checked = !!window._procUseAiAnalysis; }
      procRenderAiAnalysis();
      if (window._procUseAiAnalysis) procApplyAiAnalysis();
      return window._procVideoAiAnalysis;
    }
    if (window._procAiAnalyzing) return null;
    window._procAiAnalyzing = true;
    if (btn) { btn.disabled = true; btn.textContent = '⏳ AI đang đọc...'; }
    _procAiSetStatus('AI đang đọc video và kiểm tra chữ/logo cần che...', 'info');
    try {
      const sampleValue = document.getElementById('proc-ai-video-samples')?.value || 'full';
      const res = await fetch('/api/analyze_video_ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: path,
          provider: 'antigravity',
          nine_model: document.getElementById('proc-ai-video-nine-model-step2')?.value
            || document.getElementById('proc-ai-video-nine-model')?.value
            || localStorage.getItem('proc_ai_video_nine_model')
            || '',
          sample_count: sampleValue === 'full' ? 0 : parseInt(sampleValue || '5', 10),
          language: document.getElementById('proc-lang')?.value || '',
          target_language: document.getElementById('proc-target-lang')?.value || 'vi'
        })
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || 'AI không đọc được video');
      window._procVideoAiAnalysis = {
        video_path: path,
        provider: data.provider || 'ai',
        duration: data.duration || 0,
        frame_count: data.frame_count || 0,
        result: data.result || {}
      };
      window._procVideoAiAnalysis.analysis_text = _procAiAnalysisText(window._procVideoAiAnalysis.result);
      window._procVideoAiCache[path] = window._procVideoAiAnalysis;
      window._procUseAiAnalysis = true;
      if (useToggle) { useToggle.checked = true; }
      procRenderAiAnalysis();
      procApplyAiAnalysis();
      _procAiSetStatus(`AI đã phân tích xong (${data.provider || 'AI'}, ${data.frame_count || 0} frame).`, 'ok');
      if (typeof toast === 'function') toast('AI đã phân tích video và tạo vùng che đề xuất', 'success');
      return window._procVideoAiAnalysis;
    } catch (e) {
      window._procVideoAiAnalysis = null;
      window._procUseAiAnalysis = false;
      if (useToggle) { useToggle.checked = false; }
      procRemoveAiZones();
      procRenderAiAnalysis();
      _procAiSetStatus((e.message || '').includes('API key') ? 'Chưa có kết nối Antigravity để đọc video.' : ('Không đọc được video: ' + e.message), 'error');
      if (typeof toast === 'function') toast('AI không đọc được video: ' + e.message, 'warning');
      return null;
    } finally {
      window._procAiAnalyzing = false;
      if (btn) { btn.disabled = false; btn.textContent = '🤖 Phân tích video'; }
    }
  }
  function procMaybeAnalyzeVideoAI() {
    if (document.getElementById('proc-use-ai-analysis')?.checked === false) return;
    const path = _procAiVideoPath();
    if (!path) return;
    if (window._procVideoAiAnalysis?.video_path === path) return;
    if (window._procVideoAiCache[path]) {
      window._procVideoAiAnalysis = window._procVideoAiCache[path];
      const useToggle = document.getElementById('proc-use-ai-analysis');
      window._procUseAiAnalysis = true;
      if (useToggle) { useToggle.checked = true; }
      procRenderAiAnalysis();
      procApplyAiAnalysis();
      return;
    }
    procAnalyzeVideoAI({ force:false });
  }
  window.procAnalyzeVideoAI = procAnalyzeVideoAI;
  window.loadProcAiVideoModels = loadProcAiVideoModels;
  window.procAiVideoProviderChanged = procAiVideoProviderChanged;





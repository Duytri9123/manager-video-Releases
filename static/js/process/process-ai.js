document.addEventListener('DOMContentLoaded', () => {
    if (typeof _syncColorPicker === 'function') _syncColorPicker();
    if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
    if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
    if (typeof loadProcAiVideoModels === 'function') loadProcAiVideoModels();

    // Sync proc-ai-video-nine-model with proc-ai-video-auto
    const selectModel = document.getElementById('proc-ai-video-nine-model');
    const autoChk = document.getElementById('proc-ai-video-auto');
    if (selectModel && autoChk) {
      selectModel.addEventListener('change', function() {
        autoChk.checked = (this.value !== 'none');
        autoChk.dispatchEvent(new Event('change'));
      });
      autoChk.addEventListener('change', function() {
        if (!this.checked && selectModel.value !== 'none') {
          selectModel.value = 'none';
        } else if (this.checked && selectModel.value === 'none') {
          selectModel.value = '';
        }
      });
      // Initial sync on load
      autoChk.checked = (selectModel.value !== 'none');
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
    const map = {
      cx: 'cx',
      openai: 'openai',
      gemini: 'gemini',
      google: 'google',
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
    const sel = document.getElementById('proc-ai-video-nine-model');
    if (!sel) return;
    if (window._procAiVideoModelsLoaded && !force) return;
    const current = sel.value;

    // Fetch default model name from config to display in "Tự động theo 9Router" option
    _procAiFetchJson('/api/chatbot/config', 3000).then(cfg => {
      const autoOpt = Array.from(sel.options).find(o => o.value === "");
      if (autoOpt) {
        if (cfg && cfg.ok && cfg.has_key && cfg.default_model) {
          autoOpt.textContent = `Tự động theo 9Router (${cfg.default_model})`;
        } else {
          autoOpt.textContent = `Tự động theo 9Router`;
        }
      }
    }).catch(() => null);

    try {
      let items = [];
      const first = await _procAiFetchJson('/api/chatbot/media_models?kind=image-to-text', 5000).catch(() => null);
      if (first && first.ok && Array.isArray(first.models) && first.models.length) {
        items = first.models;
      } else {
        const fallback = await _procAiFetchJson('/api/chatbot/models', 5000).catch(() => null);
        if (fallback && fallback.ok && Array.isArray(fallback.models)) items = fallback.models;
      }
      if (!items.length) return;
      window._procAiVideoModelsLoaded = true;
      sel.querySelectorAll('optgroup[data-nr="1"]').forEach(g => g.remove());
      const existing = new Set(Array.from(sel.options).map(o => o.value));
      const visionHints = /(gpt|gemini|claude|sonnet|opus|vision|image|multimodal|cx\/gpt-5\.5|duytris)/i;
      const groups = {};
      items
        .map(m => ({ id: String((m && (m.id || m)) || '').trim(), owned_by: String((m && m.owned_by) || '').trim() }))
        .filter(m => m.id && !existing.has(m.id))
        .sort((a, b) => (visionHints.test(b.id) ? 1 : 0) - (visionHints.test(a.id) ? 1 : 0) || a.id.localeCompare(b.id))
        .forEach(m => {
          const prefix = m.id.includes('/') ? m.id.split('/')[0] : (m.owned_by || 'others');
          const label = _procAiVideoGroupLabel(prefix);
          (groups[label] = groups[label] || []).push(m.id);
        });
      Object.keys(groups).sort().forEach(label => {
        const grp = document.createElement('optgroup');
        grp.setAttribute('data-nr', '1');
        grp.label = label;
        groups[label].forEach(id => {
          const opt = document.createElement('option');
          opt.value = id;
          opt.textContent = id;
          grp.appendChild(opt);
          existing.add(id);
        });
        sel.appendChild(grp);
      });
      if (current && Array.from(sel.options).some(o => o.value === current)) sel.value = current;
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
          provider: '9router',
          nine_model: document.getElementById('proc-ai-video-nine-model')?.value || '',
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
      _procAiSetStatus((e.message || '').includes('API key') ? 'Chưa có API key 9Router để đọc video.' : ('Không đọc được video: ' + e.message), 'error');
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





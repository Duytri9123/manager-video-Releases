/* ─────────────────────────────────────────────────────────────────────────
 * Novel/Comic → Video Script — UI logic.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  let _comicToken = '';
  let _lastResult = null;

  function _el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'onclick') e.addEventListener('click', attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
    for (const c of kids) if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    return e;
  }
  function _toast(m, k) { (window.toast || console.log)(m, k || 'info'); }

  function _activeSourceText() {
    const tab = document.querySelector('#page-story .platform-tab.active');
    const src = tab?.dataset?.source || 'text';
    if (src === 'text') return document.getElementById('sw-text').value;
    if (src === 'url') return document.getElementById('sw-text-from-url').value;
    if (src === 'comic') return document.getElementById('sw-comic-text').value;
    return '';
  }

  function switchSource(name) {
    document.querySelectorAll('#page-story .platform-tab').forEach(el => {
      el.classList.toggle('active', el.dataset.source === name);
    });
    document.querySelectorAll('#page-story .story-source').forEach(el => {
      el.classList.toggle('hidden', el.dataset.source !== name);
    });
  }

  async function fetchUrl() {
    const url = document.getElementById('sw-url').value.trim();
    const proxy = document.getElementById('sw-proxy').value.trim();
    if (!url) return _toast('Nhập URL.', 'warning');
    try {
      const r = await API.post('/api/story/fetch_url', { url, proxy_url: proxy });
      document.getElementById('sw-text-from-url').value = r.text || '';
      _toast('Đã tải ' + (r.char_count || 0) + ' ký tự.', 'success');
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  async function comicUpload() {
    const f = document.getElementById('sw-comic-file').files[0];
    if (!f) return _toast('Chọn file ZIP.', 'warning');
    const status = document.getElementById('sw-comic-status');
    status.textContent = 'Đang tải lên...';
    const fd = new FormData(); fd.append('file', f);
    try {
      LoadingUI.start('Đang upload zip...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
      const r = await fetch('/api/story/comic_upload', { method: 'POST', body: fd, headers })
        .then(r => r.json());
      if (!r.ok) throw new Error(r.error || 'upload failed');
      _comicToken = r.token;
      status.textContent = 'OK — ' + r.image_count + ' ảnh';
    } catch (e) {
      status.textContent = 'Lỗi: ' + (e.message || e);
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop(); }
  }

  async function comicOcr() {
    if (!_comicToken) return _toast('Hãy upload zip trước.', 'warning');
    const lang = document.getElementById('sw-comic-lang').value;
    try {
      const r = await API.post('/api/story/comic_ocr', { token: _comicToken, lang });
      document.getElementById('sw-comic-text').value = r.text || '';
      _toast('OCR xong: ' + (r.char_count || 0) + ' ký tự.', 'success');
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  async function generate() {
    const text = _activeSourceText();
    if (!text.trim()) return _toast('Cần văn bản nguồn.', 'warning');
    const payload = {
      title: document.getElementById('sw-title').value.trim(),
      text,
      target_chars: parseInt(document.getElementById('sw-target').value || '350', 10),
      max_chars: parseInt(document.getElementById('sw-max').value || '600', 10),
      overlap_sentences: parseInt(document.getElementById('sw-overlap').value || '0', 10),
      translate: document.getElementById('sw-translate').checked,
      target_lang: document.getElementById('sw-lang').value,
      provider: document.getElementById('sw-provider').value,
    };
    try {
      const r = await API.post('/api/story/generate', payload);
      _lastResult = r;
      renderSegments(r);
      _toast('Đã chia thành ' + r.segment_count + ' đoạn.', 'success');
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function renderSegments(r) {
    const card = document.getElementById('sw-result-card');
    const wrap = document.getElementById('sw-segments');
    const meta = document.getElementById('sw-result-meta');
    if (!card || !wrap || !meta) return;
    card.classList.remove('hidden');
    meta.textContent = `${r.segment_count} đoạn · ${r.char_count} ký tự · ~${r.est_duration_sec}s`;
    wrap.replaceChildren();
    for (const s of (r.segments || [])) {
      const row = _el('div', { class: 'queue-item expanded', style: 'margin-bottom:6px' });
      const head = _el('div', { class: 'queue-item-head', style: 'cursor:default' },
        _el('span', { class: 'badge badge-accent' }, '#' + (s.index + 1)),
        _el('span', { class: 'queue-desc', style: 'white-space:normal' }, s.text),
        _el('span', { class: 'text-xs text-muted' }, s.char_count + 'c · ' + s.est_duration_sec + 's'),
        _el('button', { class: 'btn btn-secondary btn-sm', onclick: () => navigator.clipboard?.writeText(s.text).then(() => _toast('Copied #' + (s.index + 1), 'success')) }, '📋'),
      );
      row.appendChild(head);
      wrap.appendChild(row);
    }
  }

  function copyAll() {
    if (!_lastResult || !_lastResult.segments) return;
    const text = _lastResult.segments.map(s => s.text).join('\n\n');
    navigator.clipboard?.writeText(text);
    _toast('Đã copy toàn bộ kịch bản.', 'success');
  }

  function sendToTTS() {
    if (!_lastResult || !_lastResult.segments) return _toast('Chưa có kịch bản.', 'warning');
    window._pendingTTSText = _lastResult.segments.map(s => s.text).join('\n\n');
    if (window.switchPage) switchPage('process');
    _toast('Đã gửi sang trang Xử lý — paste vào ô TTS.', 'info');
  }

  Object.assign(window, {
    storySwitchSource: switchSource, storyFetchUrl: fetchUrl,
    storyComicUpload: comicUpload, storyComicOcr: comicOcr,
    storyGenerate: generate, storyCopyAll: copyAll, storySendToTTS: sendToTTS,
  });
})();

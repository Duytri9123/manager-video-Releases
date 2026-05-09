/* ── Download Queue ──────────────────────────────────────────────────────── */
let _queue = [], _dlRunning = false;
let _downloadingUrl = null; 
let _queueItemProgress = Object.create(null);
let _queueItemState = Object.create(null);
let _expandedUrls = new Set();

function _resolveQueueProcessOptions() {
  const burnEnabled = document.getElementById('proc-burn')?.checked ?? true;
  const burnVi = burnEnabled && (document.getElementById('proc-burn-vi')?.checked ?? true);
  const voiceVi = document.getElementById('proc-voice')?.checked ?? false;
  const translateSubs = document.getElementById('proc-translate-subs')?.checked ?? true;
  const keepBg = document.getElementById('proc-keep-bg')?.checked ?? false;
  const provider = (typeof _getProcessProvider === 'function')
    ? (_getProcessProvider('translate') || 'deepseek')
    : (document.getElementById('proc-trans-provider-ai')?.value || 'deepseek');

  return {
    enabled: burnVi || voiceVi,
    burn_vi_subs: burnVi,
    voice_convert: voiceVi,
    translate_subs: translateSubs,
    keep_bg_music: keepBg,
    translate_provider: provider,
  };
}

function setQueueItemProgress(url, pct, label) {
  if (!url) return;
  _queueItemProgress[url] = {
    pct: Math.max(0, Math.min(100, Number(pct) || 0)),
    label: label || '',
    ts: Date.now(),
  };
  renderQueue();
}

function markQueueItemState(url, state) {
  if (!url) return;
  _queueItemState[url] = state || '';
  renderQueue();
}

function _cleanupQueueRuntimeState() {
  const urls = new Set(_queue.map(i => i.url));
  Object.keys(_queueItemProgress).forEach(url => {
    if (!urls.has(url) && url !== _downloadingUrl) delete _queueItemProgress[url];
  });
  Object.keys(_queueItemState).forEach(url => {
    if (!urls.has(url) && url !== _downloadingUrl) delete _queueItemState[url];
  });
}

async function loadQueue() {
  const data = await API.get('/api/queue');
  _queue = data || [];
  renderQueue();
}

function _renderQueueItem(item) {
    const isDownloading = item.url === _downloadingUrl;
    // Proxied image if available, otherwise placeholder
    const thumb = item.cover ? '/api/proxy_image?url=' + encodeURIComponent(item.cover) : '';
    const dateStr = item.date || new Date().toISOString().split('T')[0];
    const isExpanded = _expandedUrls.has(item.url);

    let statusHtml = '';
    const state = _queueItemState[item.url] || '';
    if (state === 'done') statusHtml = `<span class="badge badge-green">${t('badge_done')}</span>`;
    else if (state === 'failed') statusHtml = `<span class="badge badge-red">${t('badge_error')}</span>`;
    else if (isDownloading) statusHtml = `<span class="badge badge-accent">${t('badge_running')}...</span>`;
    else statusHtml = `<span class="badge badge-gray">${t('badge_waiting')}</span>`;

    const itemProg = _queueItemProgress[item.url];
    let progressHtml = '';
    if (isDownloading && itemProg) {
      progressHtml = `
        <div class="progress-wrap mt-8" style="height:4px"><div class="progress-bar" style="width:${itemProg.pct}%"></div></div>
        <div class="flex-between mt-4 text-xs"><span class="text-muted">${escHtml(itemProg.label || '')}</span><span>${itemProg.pct}%</span></div>
      `;
    }

    const html = `
      <div class="queue-item ${isDownloading ? 'active' : ''} ${isExpanded ? 'expanded' : ''}" data-url="${escHtml(item.url)}">
        <div class="queue-item-head">
          <div class="queue-drag" title="Kéo để sắp xếp">⠿</div>
          ${thumb ? `<img class="queue-thumb" src="${thumb}">` : '<div class="queue-thumb-ph">🎬</div>'}
          <div class="queue-desc ${!isDownloading ? 'queue-desc-edit' : ''}" 
               contenteditable="${!isDownloading}" 
               spellcheck="false" 
               data-url="${escHtml(item.url)}">${escHtml(item.desc || item.url)}</div>
          <div class="card-actions">${statusHtml}</div>
        </div>
        <div class="queue-item-body">
          <div class="flex-between text-xs text-muted mb-4">
            <span>📅 Ngày thêm: ${dateStr}</span>
            <button class="btn btn-icon text-red" onclick="removeFromQueue('${escHtml(item.url)}')" style="padding:2px;font-size:14px" title="Xóa khỏi hàng chờ">✕</button>
          </div>
          ${progressHtml}
          <div class="text-xs text-dim break-all mt-4" style="opacity:0.5">${escHtml(item.url)}</div>
        </div>
      </div>`;

    const node = document.createElement('div');
    node.innerHTML = html.trim();
    const el = node.firstChild;

    // Head click toggles expansion
    el.querySelector('.queue-item-head').addEventListener('click', (e) => {
      if (e.target.classList.contains('queue-desc-edit') || e.target.classList.contains('queue-drag')) return;
      if (_expandedUrls.has(item.url)) _expandedUrls.delete(item.url);
      else _expandedUrls.add(item.url);
      el.classList.toggle('expanded');
    });

    // Handle desc edit
    const descEl = el.querySelector('.queue-desc-edit');
    if (descEl) {
      descEl.addEventListener('click', e => e.stopPropagation());
      descEl.addEventListener('blur', () => {
        const newDesc = descEl.innerText.trim();
        if (newDesc && newDesc !== item.desc) {
          updateQueueItemDesc(item.url, newDesc);
        }
      });
      descEl.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); descEl.blur(); }
      });
    }

    return el;
}

function renderQueue() {
  const el = document.getElementById('queue-list');
  const cnt = document.getElementById('queue-count');
  _cleanupQueueRuntimeState();
  
  if (cnt) cnt.textContent = _queue.length;
  if (!el) return;
  
  if (!_queue.length) {
    el.innerHTML = '<div class="empty-state" data-i18n="lbl_queue_empty">Hàng chờ trống</div>';
    return;
  }

  el.innerHTML = ''; // Clear
  _queue.forEach(item => {
    el.appendChild(_renderQueueItem(item));
  });
}

// Tìm index của item tiếp theo sẽ được tải
function _getNextIndex() {
  if (!_downloadingUrl) return 0;
  const curIdx = _queue.findIndex(q => q.url === _downloadingUrl);
  return curIdx >= 0 ? curIdx + 1 : 0;
}

async function removeFromQueue(url) {
  if (url === _downloadingUrl) return; // không xóa item đang tải
  await API.post('/api/queue/remove', { url });
  loadQueue();
}

async function clearQueue() {
  if (!confirm(t('confirm_clear_queue') || 'Xóa toàn bộ hàng chờ?')) return;
  await API.post('/api/queue/clear', {});
  toast(t('toast_queue_cleared') || 'Đã xóa hàng chờ', 'info');
  loadQueue();
}

async function addManualUrl() {
  const input = document.getElementById('manual-url');
  const url = (input?.value || '').trim();
  if (!url) return;
  const res = await API.post('/api/queue/add', [{ url, desc: url, cover: '', date: '' }]);
  input.value = '';
  if (res?.added > 0) toast(t('toast_added_queue') || 'Đã thêm vào hàng chờ', 'success');
  else toast(t('toast_url_exists') || 'URL đã tồn tại', 'warning');
  loadQueue();
}

async function updateQueueItemDesc(url, desc) {
  if (!url) return;
  const safeDesc = (desc || '').trim() || url;
  const item = _queue.find(i => i.url === url);
  if (!item || (item.desc || '') === safeDesc) return;
  item.desc = safeDesc;
  await API.post('/api/queue/update', { url, desc: safeDesc });
}

function startQueueDownload() {
  _runQueueViaProcessApi();
}

function _buildQueueProcessPayload(videoUrl) {
  const queueOpts = _resolveQueueProcessOptions();
  return {
    video_path: '',
    video_url: videoUrl || '',
    out_dir: document.getElementById('proc-out')?.value?.trim() || '',
    model: document.getElementById('proc-model')?.value || 'base',
    language: document.getElementById('proc-lang')?.value || 'zh',
    burn_subs: queueOpts.burn_vi_subs,
    blur_original: document.getElementById('proc-blur-original')?.checked ?? true,
    translate_subs: queueOpts.translate_subs,
    burn_vi_subs: queueOpts.burn_vi_subs,
    subtitle_format: 'ass',
    font_size: parseInt(document.getElementById('proc-font-size')?.value || '32', 10),
    font_color: document.getElementById('proc-font-color')?.value || 'white',
    margin_v: parseInt(document.getElementById('proc-margin-v')?.value || '20', 10),
    subtitle_position: document.getElementById('proc-sub-pos')?.value || 'bottom',
    transcribe_provider: (typeof _getProcessProvider === 'function') ? _getProcessProvider('transcribe') : 'groq',
    translate_provider: queueOpts.translate_provider,
    voice_convert: queueOpts.voice_convert,
    tts_engine: document.getElementById('proc-tts-engine')?.value || 'edge-tts',
    tts_voice: document.getElementById('proc-tts-voice')?.value || 'vi-VN-HoaiMyNeural',
    keep_bg_music: queueOpts.keep_bg_music,
    bg_volume: parseFloat(document.getElementById('proc-bg-vol')?.value || '0.15'),
    tts_speed: parseFloat(document.getElementById('proc-tts-speed')?.value || '1.0'),
    auto_speed: document.getElementById('proc-auto-speed')?.checked ?? true,
    pitch_semitones: parseFloat(document.getElementById('proc-tts-pitch')?.value || '0'),
    process_mode: window._procMode || 'ai',
    // CapCut settings
    capcut_enabled: document.getElementById('dl-capcut-enabled')?.checked ?? false,
    capcut_auto_open: document.getElementById('dl-capcut-auto-open')?.checked ?? false,
  };
}

function _runSingleQueueItem(item, index, total) {
  return new Promise(resolve => {
    const payload = _buildQueueProcessPayload(item.url);
    fetch('/api/process_video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(res => {
      if (!res.ok || !res.body) {
        _appendProcLog('[Queue] Không thể bắt đầu xử lý: ' + (item.url || ''), 'error');
        resolve(false);
        return;
      }

      _appendProcLog('[Queue ' + index + '/' + total + '] ' + (item.url || ''), 'info');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      function read() {
        reader.read().then(({ done, value }) => {
          if (done) {
            resolve(true);
            return;
          }
          const text = decoder.decode(value, { stream: true });
          text.split('\n').filter(l => l.trim()).forEach(line => {
            try {
              const d = JSON.parse(line);
              if (d.log) _appendProcLog(d.log, d.level || 'info');
              if (d.overall !== undefined) {
                _setProcProgress(d.overall, d.overall_lbl || '');
                setQueueItemProgress(item.url, d.overall, d.overall_lbl || '');
              }
              // Capture output file path for auto-publish
              if (d.file_path) {
                window._publishLastOutputPath = d.file_path;
                window._ytLastOutputPath = d.file_path;
              }
              if (d.subtitle_path) {
                window._publishLastSubtitlePath = d.subtitle_path;
              }
            } catch (_) {}
          });
          read();
        }).catch(() => resolve(false));
      }
      read();
    }).catch(() => {
      _appendProcLog('[Queue] Lỗi kết nối khi xử lý: ' + (item.url || ''), 'error');
      resolve(false);
    });
  });
}

async function _runQueueViaProcessApi() {
  if (!_queue.length) { toast(t('lbl_queue_empty') || 'Hàng chờ trống', 'error'); return; }
  if (_dlRunning) return;

  _dlRunning = true;
  _queueItemProgress = Object.create(null);
  _queueItemState = Object.create(null);

  const btn = document.getElementById('btn-dl');
  if (btn) { btn.disabled = true; btn.textContent = 'Đang chạy hàng chờ...'; }

  clearLog('proc-log');
  _setProcProgress(0, 'Bắt đầu hàng chờ...');

  const concurrency = parseInt(document.getElementById('queue-concurrency')?.value || '2', 10);
  const queueSnapshot = [..._queue];
  const total = queueSnapshot.length;
  let completed = 0;

  // Semaphore: chạy tối đa `concurrency` video cùng lúc
  const sem = { count: concurrency, queue: [] };
  function acquire() {
    return new Promise(resolve => {
      if (sem.count > 0) { sem.count--; resolve(); }
      else { sem.queue.push(resolve); }
    });
  }
  function release() {
    if (sem.queue.length > 0) { sem.queue.shift()(); }
    else { sem.count++; }
  }

  const tasks = queueSnapshot.map((item, i) => async () => {
    await acquire();
    const index = i + 1;
    _downloadingUrl = item.url;
    markQueueItemState(item.url, 'running');
    setQueueItemProgress(item.url, 0, 'Đang xử lý');
    const cnt = document.getElementById('queue-count');
    if (cnt) cnt.textContent = _queue.length + ' (' + (++completed) + '/' + total + ')';

    const ok = await _runSingleQueueItem(item, index, total);

    if (ok) {
      markQueueItemState(item.url, 'done');
      setQueueItemProgress(item.url, 100, 'Hoàn tất');
      _queue = _queue.filter(q => q.url !== item.url);
      renderQueue();
      try { await API.post('/api/queue/remove', { url: item.url }); } catch (_) {}
      // Auto-publish if enabled
      if (document.getElementById('publish-auto-upload')?.checked && window._publishLastOutputPath) {
        await publishSelectedPlatform();
      }
    } else {
      markQueueItemState(item.url, 'failed');
      setQueueItemProgress(item.url, 0, 'Lỗi xử lý');
    }
    release();
  });

  await Promise.all(tasks.map(t => t()));

  _downloadingUrl = null;
  _dlRunning = false;
  if (btn) { btn.disabled = false; btn.textContent = 'Chạy hàng chờ'; }

  const hasFailed = Object.values(_queueItemState).some(s => s === 'failed');
  _setProcProgress(hasFailed ? 0 : 100, hasFailed ? 'Hoàn tất có lỗi' : 'Hoàn tất hàng chờ');
  renderQueue();
  toast(hasFailed ? 'Hàng chờ hoàn tất, có mục lỗi' : 'Hàng chờ đã hoàn tất', hasFailed ? 'warning' : 'success');

  const doneActions = document.getElementById('dl-done-actions');
  if (doneActions && !hasFailed) doneActions.style.display = 'block';
}

function sendLastDownloadedToPublish() {
  if (!window._publishLastOutputPath) {
    toast('Không tìm thấy đường dẫn video vừa tải', 'warning');
    return;
  }
  if (typeof sendToPublish === 'function') {
    sendToPublish(window._publishLastOutputPath);
  } else {
    // Fallback if not globally available
    const pathInput = document.getElementById('pub-video-path');
    if (pathInput) {
      pathInput.value = window._publishLastOutputPath;
      window._pubVideoFile = null;
      toast('✅ Đã thêm dữ liệu vào Đăng video', 'success');
      if (typeof switchPage === 'function') switchPage('publish');
    }
  }
}

/* ══════════════════════════════════════════════════════════════
   Download page — queue client (Douyin + đa nền tảng qua yt-dlp)

   Định nghĩa các hàm queue mà core.js (socket handlers) và các trang khác
   (user, transcribe) tham chiếu tới: renderQueue, loadQueue, markQueueItemState,
   setQueueItemProgress, addManualUrl, clearQueue, startQueueDownload.

   Trước đây các hàm này bị thiếu → switchPage('process') ném lỗ
   "loadQueue is not defined" làm hỏng điều hướng. Module này khôi phục chúng.
   ══════════════════════════════════════════════════════════════ */

// State toàn cục dùng chung với core.js (tham chiếu dạng biến global trần).
window._queue = window._queue || [];
window._downloadingUrl = window._downloadingUrl || null;
window._dlRunning = window._dlRunning || false;

function _dlEsc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Vẽ danh sách hàng chờ tải xuống vào #queue-list. */
function renderQueue() {
  const list = document.getElementById('queue-list');
  const cnt = document.getElementById('queue-count');
  const q = window._queue || [];
  if (cnt) cnt.textContent = q.length;
  if (!list) return;

  if (!q.length) {
    list.innerHTML = '<div class="empty-state" data-i18n="lbl_queue_empty">'
      + (typeof t === 'function' ? t('lbl_queue_empty') : 'Hàng chờ trống') + '</div>';
    return;
  }

  list.innerHTML = q.map(item => {
    const url = item.url || '';
    const desc = item.desc || url;
    const running = url === window._downloadingUrl;
    const state = item._state || (running ? 'running' : '');
    const thumb = item.cover
      ? '<img class="queue-thumb" src="' + (/^https?:/.test(item.cover) ? item.cover : '') + '" loading="lazy">'
      : '<div class="queue-thumb-ph">🎬</div>';
    const badge = state === 'success' ? '<span class="badge badge-green">✓</span>'
      : state === 'failed' ? '<span class="badge badge-red">✗</span>'
      : state === 'running' ? '<span class="badge badge-accent">●</span>' : '';
    return '<div class="queue-item' + (running ? ' active' : '') + '" data-url="' + _dlEsc(url) + '">'
      + '<div class="queue-item-head">'
      + thumb
      + '<div class="queue-desc" title="' + _dlEsc(desc) + '">' + _dlEsc(desc) + '</div>'
      + badge
      + '<button class="btn-icon" title="' + (typeof t === 'function' ? t('ttl_remove_queue_item') : 'Xóa')
      + '" onclick="removeQueueItem(\'' + encodeURIComponent(url) + '\')">🗑</button>'
      + '</div>'
      + '<div class="progress-bar-wrap" style="margin:0 14px 10px"><div class="progress-bar pb-overall" '
      + 'data-url-bar="' + _dlEsc(url) + '" style="width:0"></div></div>'
      + '</div>';
  }).join('');
}

/** Nạp hàng chờ từ server. */
async function loadQueue() {
  try {
    const data = await (typeof API !== 'undefined' ? API.get('/api/queue')
      : fetch('/api/queue').then(r => r.json()));
    window._queue = Array.isArray(data) ? data : [];
  } catch (e) {
    window._queue = window._queue || [];
  }
  renderQueue();
  if (typeof onQueueStateChanged === 'function') onQueueStateChanged();
}

/** Đánh dấu trạng thái 1 mục (running/success/failed). */
function markQueueItemState(url, state) {
  const item = (window._queue || []).find(i => i.url === url);
  if (item) item._state = state;
  renderQueue();
}

/** Cập nhật thanh tiến trình của 1 mục theo URL. */
function setQueueItemProgress(url, pct, label) {
  const bar = document.querySelector('[data-url-bar="' + (url || '').replace(/"/g, '\\"') + '"]');
  if (bar) bar.style.width = Math.max(0, Math.min(100, pct || 0)) + '%';
}

/** Thêm URL nhập tay vào hàng chờ (mọi nền tảng). */
async function addManualUrl() {
  const input = document.getElementById('manual-url');
  const url = (input?.value || '').trim();
  if (!url) return;
  try {
    const res = await (typeof API !== 'undefined'
      ? API.post('/api/queue/add', { url, desc: url })
      : fetch('/api/queue/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, desc: url }),
        }).then(r => r.json()));
    if (res?.added > 0) {
      if (input) input.value = '';
      if (typeof toast === 'function') toast(t('toast_added_queue'), 'success');
    } else if (typeof toast === 'function') {
      toast(t('toast_url_exists'), 'warning');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('Error: ' + e.message, 'error');
  }
  loadQueue();
}

function removeQueueItem(encodedUrl) {
  const url = decodeURIComponent(encodedUrl || '');
  const body = { url };
  (typeof API !== 'undefined'
    ? API.post('/api/queue/remove', body)
    : fetch('/api/queue/remove', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
  ).finally(() => loadQueue());
}

async function clearQueue() {
  if (!confirm(typeof t === 'function' ? t('confirm_clear_queue') : 'Xóa tất cả hàng chờ?')) return;
  try {
    await (typeof API !== 'undefined' ? API.post('/api/queue/clear', {})
      : fetch('/api/queue/clear', { method: 'POST' }));
    if (typeof toast === 'function') toast(t('toast_queue_cleared'), 'success');
  } catch (e) { /* ignore */ }
  loadQueue();
}

/** Bắt đầu tải toàn bộ hàng chờ qua socket. */
function startQueueDownload() {
  if (window._dlRunning) return;
  const q = window._queue || [];
  if (!q.length) {
    if (typeof toast === 'function') toast(t('lbl_queue_empty'), 'warning');
    return;
  }
  const $ = id => document.getElementById(id);
  const post_process = {
    enabled: !!$('dl-vp-enabled')?.checked,
    burn_vi_subs: !!$('dl-vp-burn-vi')?.checked,
    voice_convert: !!$('dl-vp-voice')?.checked,
    translate_provider: $('dl-translate-provider')?.value || 'deepseek',
    groq_api_key: $('dl-groq-api-key')?.value || '',
    groq_model: $('dl-groq-model')?.value || '',
  };
  window._dlRunning = true;
  const btn = $('btn-dl');
  if (btn) { btn.disabled = true; btn.textContent = typeof t === 'function' ? t('lbl_queue_running') : 'Đang chạy...'; }
  if (typeof socket !== 'undefined' && socket.emit) {
    socket.emit('start_download', { use_queue: true, post_process });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('manual-url')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') addManualUrl();
  });
  // Nạp hàng chờ ban đầu (không chặn nếu lỗi).
  if (typeof loadQueue === 'function') loadQueue();
});

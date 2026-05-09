/* ── Socket.IO setup ─────────────────────────────────────────────────────── */
let socket = null;
try {
  socket = io();
} catch(e) {
  console.warn('Socket.IO not available:', e.message);
  // Create a no-op socket stub so the rest of the code doesn't break
  socket = { on: () => {}, emit: () => {}, connected: false };
}

function _clampPct(v) {
  return Math.max(0, Math.min(100, Number(v) || 0));
}

socket.on('log', d => {
  appendLog('proc-log', d.msg, d.level || 'info');
  if (d && d.file_path) {
    window._publishLastOutputPath = d.file_path;
    window._ytLastOutputPath = d.file_path;
  }
});

socket.on('progress', d => {
  if (d.type === 'overall' || d.type === 'step' || d.type === 'item' || d.type === 'post') {
    const pct = _clampPct(d.pct);
    const label = d.label || '';
    if (typeof _setProcProgress === 'function') {
      _setProcProgress(pct, label);
    } else {
      setProgress('pb-proc-overall', 'lbl-proc-overall', pct, label);
    }
    const targetUrl = d.url || _downloadingUrl;
    if (targetUrl && typeof setQueueItemProgress === 'function') {
      setQueueItemProgress(targetUrl, d.pct, label);
    }
  }
});

// Nhận thông báo URL nào đang được tải
socket.on('downloading_url', d => {
  _downloadingUrl = d.url || null;
  if (_downloadingUrl && typeof markQueueItemState === 'function') {
    markQueueItemState(_downloadingUrl, 'running');
  }
  renderQueue();

  // Hiển thị "Đang tải X/Y" trên topbar queue
  const cnt = document.getElementById('queue-count');
  if (cnt && d.total) cnt.textContent = _queue.length + ' (' + d.index + '/' + d.total + ')';
});

socket.on('queue_item_state', d => {
  const url = d?.url || '';
  if (!url || typeof markQueueItemState !== 'function') return;
  markQueueItemState(url, d.state || '');
});

socket.on('queue_update', data => {
  _queue = data || [];
  renderQueue();
  if (typeof onQueueStateChanged === 'function') onQueueStateChanged();
});

socket.on('done', d => {
  const btn = document.getElementById('btn-dl');
  if (btn) { btn.disabled = false; btn.textContent = 'Chạy hàng chờ'; }
  if (typeof _setProcProgress === 'function') {
    _setProcProgress(d.ok ? 100 : 0, d.ok ? 'Hoàn tất hàng chờ' : 'Hàng chờ lỗi');
  }
  _dlRunning = false;
  _downloadingUrl = null;
  renderQueue();
  if (typeof onQueueStateChanged === 'function') onQueueStateChanged();
  toast(d.ok ? t('toast_dl_done') : t('toast_dl_error'), d.ok ? 'success' : 'error');
});

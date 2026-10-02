window._batchQueue = window._batchQueue || [];
window._moveBatchQueueItem = function (index, delta) {
  const queue = window._batchQueue;
  const other = index + delta;
  if (!Array.isArray(queue) || other < 0 || other >= queue.length || window._procRunning) return;
  [queue[index], queue[other]] = [queue[other], queue[index]];
  _renderBatchQueue();
  if (typeof _step3RenderQueue === 'function') _step3RenderQueue();
  if (typeof window.pe2RefreshQueueSelect === 'function') window.pe2RefreshQueueSelect();
};
window._procQueueDragStart = function(event, index) {
  const item = (window._batchQueue || [])[index];
  if (!item || item.status === 'processing' || item.status === 'downloading') {
    event.preventDefault();
    return;
  }
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', String(index));
};
window._procQueueDragOver = function(event) {
  if (event.dataTransfer?.types?.includes('text/plain')) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }
};
window._procQueueDrop = function(event, targetIndex) {
  event.preventDefault();
  const sourceIndex = Number(event.dataTransfer.getData('text/plain'));
  const queue = window._batchQueue || [];
  if (!Number.isInteger(sourceIndex) || sourceIndex < 0 || sourceIndex >= queue.length ||
      targetIndex < 0 || targetIndex >= queue.length || sourceIndex === targetIndex) return;
  if (queue.slice(Math.min(sourceIndex, targetIndex), Math.max(sourceIndex, targetIndex) + 1)
      .some(t => t.status === 'processing' || t.status === 'downloading')) return;
  const [item] = queue.splice(sourceIndex, 1);
  queue.splice(targetIndex, 0, item);
  _renderBatchQueue();
  if (typeof window.pe2RefreshQueueSelect === 'function') window.pe2RefreshQueueSelect();
};

// Fallback SVG icon helper — the canonical version lives in process/script.js
// which loads *after* this file.  Provide a minimal fallback so early calls
// don't throw ReferenceError; after DOMContentLoaded the real one takes over.
if (typeof _processSvgIcon !== 'function') {
  var _processSvgIcon = function(name, className, size) {
    size = size || 14;
    className = className || '';
    var paths = {
      refresh: '<path d="M20 7v5h-5"></path><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"></path>',
      settings: '<path d="M4 7h16M4 17h16"></path><circle cx="9" cy="7" r="3"></circle><circle cx="15" cy="17" r="3"></circle>',
      video: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="m10 9 5 3-5 3Z"></path>',
      close: '<path d="m6 6 12 12M18 6 6 18"></path>',
      folder: '<path d="M3 6h7l2 2h9l-2 11H3Z"></path>'
    };
    var body = paths[name] || paths.video || '';
    return '<svg class="proc-svg-icon ' + className + '" width="' + size + '" height="' + size + '" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:' + size + 'px;height:' + size + 'px;flex-shrink:0;display:inline-block;vertical-align:middle;">' + body + '</svg>';
  };
}

  // Listen for Step 1 download log updates from backend
  if (typeof socket !== 'undefined' && socket) {
    socket.on('step1_log', function(d) {
      if (typeof _step1Log === 'function') {
        _step1Log(d.msg, d.level || 'info');
      }
    });
  }

  function buildNewTask(type, val) {
    return {
      id: 'bt-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
      type: type,
      val: val,
      status: 'pending',
      desc: val.split(/[\\/]/).pop(),
      added: Date.now(),
      auto_flow: document.getElementById('proc-auto-flow')?.checked ?? true,
      skip_ass: document.getElementById('step3-skip-ass')?.checked ?? false,
      skip_trans: document.getElementById('proc-skip-transcription')?.checked ?? false,
      queue_mode: 'process',
    };
  }

  function getTaskConfigLabel(t) {
    const parts = [];
    if (t.auto_flow) parts.push('1');
    if (t.skip_ass) parts.push('2');
    if (t.skip_trans) parts.push('3');
    const mode = t.queue_mode || 'process';
    if (mode === 'skip') return 'Không tải';
    if (mode === 'download') return 'Chỉ tải';
    return parts.length > 0 ? 'Xử lý · ' + parts.join(',') : 'Xử lý';
  }

  window._toggleItemCfgDropdown = function(taskId, event) {
    event.stopPropagation();
    const old = document.getElementById('proc-queue-config-popover');
    if (old) { const same = old.dataset.taskId === taskId; old.remove(); if (same) return; }
    const t = (window._batchQueue || []).find(x => x.id === taskId);
    if (!t || t.status === 'processing' || t.status === 'downloading') return;
    const btn = event.currentTarget || event.target.closest('button[data-cfg-btn]');
    if (!btn) return;
    const panel = document.createElement('div');
    panel.id = 'proc-queue-config-popover';
    panel.dataset.taskId = taskId;
    panel.style.cssText = 'position:fixed;z-index:100000;width:230px;max-width:calc(100vw - 16px);padding:12px;background:var(--bg2,#fff);color:var(--text,#111827);border:1px solid var(--border,#dbe3ef);border-radius:10px;box-shadow:0 12px 30px rgba(0,0,0,.22);font-size:12px';
    const mode = t.queue_mode || 'process';
    panel.innerHTML = `<strong>Video này</strong><p style="margin:5px 0 9px;color:var(--text-muted,#64748b)">Chọn thao tác trước khi chạy hàng chờ.</p>
      <select data-queue-mode style="width:100%;padding:6px;border:1px solid var(--border,#dbe3ef);border-radius:6px;background:var(--bg2,#fff);color:inherit">
        <option value="process" ${mode === 'process' ? 'selected' : ''}>Tải và xử lý</option>
        <option value="download" ${mode === 'download' ? 'selected' : ''}>Chỉ tải</option>
        <option value="skip" ${mode === 'skip' ? 'selected' : ''}>Không tải, bỏ qua</option>
      </select>
      <label style="display:flex;gap:7px;margin-top:10px"><input type="checkbox" data-queue-flag="auto_flow" ${t.auto_flow ? 'checked' : ''}>Tự động hóa</label>
      <label style="display:flex;gap:7px;margin-top:7px"><input type="checkbox" data-queue-flag="skip_ass" ${t.skip_ass ? 'checked' : ''}>Bỏ qua toàn bộ ASS</label>
      <label style="display:flex;gap:7px;margin-top:7px"><input type="checkbox" data-queue-flag="skip_trans" ${t.skip_trans ? 'checked' : ''}>Bỏ qua phụ đề</label>`;
    document.body.appendChild(panel);
    const rect = btn.getBoundingClientRect();
    panel.style.left = Math.max(8, Math.min(rect.left, innerWidth - panel.offsetWidth - 8)) + 'px';
    panel.style.top = Math.max(8, Math.min(rect.bottom + 5, innerHeight - panel.offsetHeight - 8)) + 'px';
    panel.querySelector('[data-queue-mode]').addEventListener('change', e => window._updateTaskConfig(taskId, 'queue_mode', e.target.value));
    panel.querySelectorAll('[data-queue-flag]').forEach(el => el.addEventListener('change', e => window._updateTaskConfig(taskId, el.dataset.queueFlag, e.target.checked)));
  };

  window._updateTaskConfig = function(taskId, key, value) {
    const t = window._batchQueue.find(x => x.id === taskId);
    if (t && t.status !== 'processing' && t.status !== 'downloading') {
      t[key] = value;
      _renderBatchQueue();
      _step3RenderQueue();
      document.getElementById('proc-queue-config-popover')?.remove();
      if (typeof window._procQueueSaveToLocalStorage === 'function') window._procQueueSaveToLocalStorage();
    }
  };

  window.addEventListener('click', function(e) {
    if (!e.target.closest('#proc-queue-config-popover') && !e.target.closest('button[data-cfg-btn]')) document.getElementById('proc-queue-config-popover')?.remove();
  });

  window._procQueueRefresh = function() {
    try {
      const interruptedRun = JSON.parse(localStorage.getItem('_proc_active_run_v1') || 'null');
      const localQueue = JSON.parse(localStorage.getItem('_proc_batch_queue') || '[]');
      const newQueue = [];
      localQueue.forEach(localItem => {
        const existing = window._batchQueue.find(item => item.val === localItem.val);
        if (existing) {
          if (existing.status === 'processing' && !window._procRunning) {
            existing.status = 'ready';
          }
          newQueue.push(existing);
        } else {
          let st = localItem.status || 'pending';
          if (st === 'processing' && !window._procRunning) {
            st = 'ready';
          }
          newQueue.push({
            id: localItem.id || 'bt-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
            type: localItem.type || 'file',
            val: localItem.val,
            status: st,
            desc: localItem.desc || localItem.val,
            added: localItem.added || Date.now(),
            auto_flow: localItem.auto_flow !== undefined ? localItem.auto_flow : (document.getElementById('proc-auto-flow')?.checked ?? true),
            skip_ass: localItem.skip_ass !== undefined ? localItem.skip_ass : (document.getElementById('step3-skip-ass')?.checked ?? false),
            skip_trans: localItem.skip_trans !== undefined ? localItem.skip_trans : (document.getElementById('proc-skip-transcription')?.checked ?? false)
            ,queue_mode: localItem.queue_mode || 'process'
          });
        }
      });
      window._batchQueue.forEach(item => {
        if (!newQueue.some(ni => ni.val === item.val)) {
          if (item.status === 'processing' && !window._procRunning) {
            item.status = 'ready';
          }
          newQueue.push(item);
        }
      });
      window._batchQueue = newQueue;
      if (interruptedRun && interruptedRun.taskId) {
        const interruptedTask = window._batchQueue.find(item => item.id === interruptedRun.taskId);
        if (interruptedTask && interruptedTask.status === 'processing') interruptedTask.status = 'ready';
        window._procRecoveredRun = interruptedRun;
      }
      _renderBatchQueue();
    } catch (e) {
      console.error('Error in _procQueueRefresh:', e);
    }
  };

  window._procQueueSaveToLocalStorage = function() {
    try {
      const listToSave = window._batchQueue.map(item => ({
        id: item.id,
        type: item.type,
        val: item.val,
        status: item.status,
        desc: item.desc || item.val,
        added: item.added || Date.now(),
        auto_flow: item.auto_flow,
        skip_ass: item.skip_ass,
        skip_trans: item.skip_trans,
        queue_mode: item.queue_mode || 'process'
      }));
      localStorage.setItem('_proc_batch_queue', JSON.stringify(listToSave));
    } catch (e) {
      console.error('Error saving process queue to localStorage:', e);
    }
  };

  // Run initial sync on scripts load
  window._procQueueRefresh();

  window._procRunning = false;       // currently processing a task?
  window._procAutoDrain = false;     // auto-drain mode
  window._procCurrentTaskId = null;  // id of task currently in progress

  /**
   * Resolve the queue item that should currently be processed / previewed.
   * Priority:
   *   1. The task explicitly marked as active (_procCurrentTaskId)
   *   2. Any item still 'processing'
   *   3. The next item that is 'ready' (downloaded / on disk, not yet run)
   * Finished items ('done' / 'error') are intentionally skipped so we never
   * re-feed the file of an already-processed item above in the queue.
   */
  window._resolveActiveQueueItem = function() {
    const q = window._batchQueue || [];
    if (window._procCurrentTaskId) {
      const cur = q.find(t => t.id === window._procCurrentTaskId);
      if (cur) return cur;
    }
    return q.find(t => t.status === 'processing')
        || q.find(t => t.status === 'ready')
        || null;
  };

  function _addProcTask(type) {
    const urlEl = document.getElementById('proc-url');
    const pathEl = document.getElementById('proc-video');
    const val = (type === 'url') ? urlEl?.value.trim() : pathEl?.value.trim();
    if (!val) { toast('Vui lòng nhập URL hoặc chọn file', 'warning'); return; }
    window._batchQueue.push(buildNewTask(type, val));
    if (type === 'url' && urlEl) urlEl.value = '';
    _renderBatchQueue();
    toast('Đã thêm vào hàng chờ', 'success');
    // If auto-drain is on and idle, kick off processing
    if (window._procAutoDrain && !window._procRunning) {
      _runBatchQueueFlow();
    }
  }
  function _step1Log(msg, level) {
    const box = document.getElementById('step1-dl-log');
    if (!box) return;
    box.style.display = 'block';
    const colors = { success: 'var(--success,#16a34a)', error: 'var(--error,#dc2626)', warning: '#d97706', info: 'var(--text-muted)' };
    const line = document.createElement('div');
    line.style.color = colors[level] || colors.info;
    line.textContent = new Date().toLocaleTimeString('vi-VN', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) + '  ' + msg;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function _renderBatchQueue() {
    const list = document.getElementById('batch-queue-list');
    const cnt = document.getElementById('batch-count');
    if (cnt) cnt.textContent = window._batchQueue.length;
    if (!list) return;

    const dlArea = document.getElementById('step1-download-area');
    if (!window._batchQueue.length) {
      list.innerHTML = '<div class="empty-state text-xs">Chưa có video nào trong hàng chờ.</div>';
      const nextWrap = document.getElementById('step1-next-btn-wrap');
      if (nextWrap) nextWrap.style.display = 'none';
      if (dlArea) dlArea.style.display = 'none';
      if (typeof pBschedRecalcPreview === 'function') pBschedRecalcPreview();
      if (typeof window._procQueueSaveToLocalStorage === 'function') window._procQueueSaveToLocalStorage();
      return;
    }

    // Show download area when there are queue items
    if (dlArea) dlArea.style.display = 'block';

    const statusLabel = {
      pending:     ' Chờ',
      downloading: ' Đang tải...',
      ready:       ' Sẵn sàng',
      processing:  ' Đang xử lý...',
      done:        ' Hoàn tất',
      error:       ' Lỗi',
    };
    list.innerHTML = window._batchQueue.map((t,i) => {
      let badgeClass = 'badge-gray';
      if (t.status === 'done') badgeClass = 'badge-green';
      else if (t.status === 'error') badgeClass = 'badge-red';
      else if (t.status === 'processing' || t.status === 'downloading') badgeClass = 'badge-yellow';
      else if (t.status === 'ready') badgeClass = 'badge-accent';

      const disableDel = (t.status === 'processing' || t.status === 'downloading') ? 'disabled' : '';
      const label = t.queue_mode === 'skip' && t.status === 'pending' ? 'Bỏ qua' : (statusLabel[t.status] || t.status);

      // Inline config button
      const labelCfg = getTaskConfigLabel(t);
      const isReadyOrPending = t.status === 'ready' || t.status === 'pending';
      const cfgBtnHtml = isReadyOrPending ? `
        <div style="position:relative;display:inline-block">
          <button data-cfg-btn class="btn btn-outline btn-xs" onclick="window._toggleItemCfgDropdown('${t.id}', event)" style="font-size:10px;padding:2px 6px;height:24px;line-height:20px;border-color:var(--border);border-radius:4px;display:flex;align-items:center;gap:3px;white-space:nowrap">
             ${labelCfg}
          </button>

        </div>
      ` : '';

      return `
      <div ondragover="window._procQueueDragOver(event)" ondrop="window._procQueueDrop(event,${i})" style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:${t.id === window._procCurrentTaskId ? 'rgba(99,91,250,.10)' : 'var(--bg3)'};border:1px solid ${t.id === window._procCurrentTaskId ? '#635bfa' : 'var(--border)'};border-radius:6px;font-size:12px;box-shadow:${t.id === window._procCurrentTaskId ? '0 0 0 2px rgba(99,91,250,.12)' : 'none'}">
        <span draggable="${disableDel ? 'false' : 'true'}" ondragstart="window._procQueueDragStart(event,${i})" title="Kéo để đổi thứ tự" aria-label="Kéo để đổi thứ tự" style="cursor:grab;color:var(--text-muted);font-size:17px;line-height:1;user-select:none;touch-action:none">⠿</span>
        <span style="color:var(--text-muted)">${t.type==='url'?'':''}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)" title="${t.val}">${t.desc || t.val}</span>
        <span class="badge ${badgeClass}">${label}</span>
        ${cfgBtnHtml}
        <button onclick="window._batchQueue.splice(${i},1);_renderBatchQueue()" class="btn-icon text-red" style="font-size:14px" ${disableDel}>×</button>
      </div>`;
    }).join('');

    const hasReady = window._batchQueue.some(t => t.status === 'ready' || t.status === 'done');
    const hasPending = window._batchQueue.some(t => t.status === 'pending' && (t.queue_mode || 'process') !== 'skip');
    const nextWrap = document.getElementById('step1-next-btn-wrap');
    if (nextWrap) {
      nextWrap.style.display = (hasPending || hasReady) ? 'block' : 'none';
    }

    // Update download button state
    const dlBtn = document.getElementById('btn-step1-download');
    const dlStatus = document.getElementById('step1-dl-status');
    if (dlBtn) {
      const isDownloading = window._step1Downloading;
      dlBtn.disabled = isDownloading;
      dlBtn.textContent = isDownloading ? 'Đang tải...' : 'Chỉ tải';
    }
    if (dlStatus) {
      if (hasReady && !hasPending) {
        dlStatus.textContent = ' Tất cả video đã sẵn sàng.';
      } else if (hasPending) {
        dlStatus.textContent = 'Nhấn để bắt đầu tải video gốc từ URL.';
      }
    }

    if (typeof pBschedRecalcPreview === 'function') pBschedRecalcPreview();
    // Refresh step 3 start card whenever queue state changes
    _step3RefreshStartCard();
    // Refresh step 3 queue panel
    _step3RenderQueue();
    if (typeof window._procQueueSaveToLocalStorage === 'function') window._procQueueSaveToLocalStorage();
  }

  /** Show/hide or update "Start processing" card in step 3 based on queue readiness */
  function _step3RefreshStartCard() {
    const card = document.getElementById('step3-start-card');
    if (!card) return;

    // Reset dangling processing state if pipeline not actually running
    if (!window._procRunning) {
      (window._batchQueue || []).forEach(t => {
        if (t.status === 'processing') t.status = 'ready';
      });
    }

    // Pipeline already running
    const isRunning = !!window._procRunning;

    // ALWAYS keep Thao tac & Tuy chon visible
    card.style.display = 'flex';

    // Update start button appearance/state while running
    const startBtn = card.querySelector('button.btn-primary');
    if (startBtn) {
      if (isRunning) {
        startBtn.disabled = true;
        startBtn.classList.add('opacity-70', 'cursor-not-allowed');
        startBtn.innerHTML = `
          <svg class="animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"/></svg>
          <span>Đang xử lý...</span>
        `;
      } else {
        startBtn.disabled = false;
        startBtn.classList.remove('opacity-70', 'cursor-not-allowed');
        startBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3" fill="currentColor"/></svg>
          <span>Xử lý video</span>
        `;
      }
    }

    // Keep settings editable; this video's request already holds its own snapshot.
    const cfgCard = document.getElementById('step3-config-card');
    if (cfgCard) cfgCard.classList.remove('step3-config-disabled');

    // Toggle cancel buttons & running actions visibility
    const runActs = document.getElementById('step3-running-actions');
    if (runActs) runActs.style.display = isRunning ? 'grid' : 'none';
    const multiple = !!window._procProcessAll && (window._batchQueue || []).filter(t => ['pending', 'ready', 'processing', 'downloading'].includes(t.status) && (t.queue_mode || 'process') === 'process').length > 1;
    const cancelAll = document.getElementById('step3-cancel-all');
    if (cancelAll) cancelAll.style.display = multiple ? '' : 'none';
    if (runActs) runActs.style.gridTemplateColumns = multiple ? 'repeat(2,minmax(0,1fr))' : '1fr';
    const startAll = document.getElementById('step3-start-all');
    if (startAll) startAll.style.display = isRunning ? 'none' : '';
  }

  window._resetQueueItemStatus = function(taskId) {
    const t = (window._batchQueue || []).find(x => x.id === taskId);
    if (t && t.status !== 'downloading' && !(t.status === 'processing' && window._procRunning)) {
      t.status = 'ready';
      window._procRunning = false;
      window._step3Started = false;
      _renderBatchQueue();
      if (typeof toast === 'function') toast(' Đã đặt lại trạng thái sẵn sàng', 'success');
    }
  };

  window._deleteQueueItem = function(taskId) {
    const idx = (window._batchQueue || []).findIndex(x => x.id === taskId);
    if (idx !== -1 && !['processing', 'downloading'].includes(window._batchQueue[idx].status)) {
      window._batchQueue.splice(idx, 1);
      _renderBatchQueue();
      if (typeof toast === 'function') toast(' Đã xóa video khỏi hàng chờ', 'info');
    }
  };

  /** Called when user clicks "Bắt đầu xử lý" in step 3 */
  window.procValidatePublishPage = function() {
    const publishing = document.getElementById('step1-autopub-toggle')?.checked;
    const facebook = window._pPubEnabled?.facebook !== false;
    const page = document.getElementById('step1-fb-page-select');
    if (!publishing || !facebook || page?.value?.trim()) return true;
    toast('Vui lòng chọn Facebook Page trước khi tiếp tục đăng bài.', 'warning');
    page?.focus();
    return false;
  };
  window.procStartSingleFromStep1 = function() {
    const first = (window._batchQueue || []).find(t => ['downloading', 'pending', 'ready'].includes(t.status) && (t.queue_mode || 'process') === 'process');
    if (!first) { toast('Không có video chờ xử lý.', 'warning'); return; }
    window._procProcessAll = false;
    window._procCurrentTaskId = first.id;
    window._step1ManualAction = 'single';
    if (first.status === 'downloading') {
      window._step1SingleTargetId = first.id;
      toast('Sẽ mở video đầu tiên sau khi tải xong; các video còn lại giữ trong hàng chờ.', 'info');
    } else if (first.status === 'pending') {
      window._step1SingleTargetId = first.id;
      _runStep1QueueDownload();
    } else {
      window.procWizStep2Continue(2);
    }
  };
  window.procStopStep1Queue = function() {
    if (window._procRunning && typeof window.procCancelCurrentVideo === 'function') {
      window.procCancelCurrentVideo();
      return;
    }
    if (window._step1Downloading) {
      window._step1StopRequested = true;
      toast('Sẽ dừng hàng chờ sau khi video hiện tại tải xong.', 'info');
    } else {
      window._step1SingleTargetId = null;
      window._step1AfterDownloadTarget = null;
      window._step1ManualAction = null;
      window._procProcessAll = false;
      toast('Đã dừng hàng chờ.', 'info');
    }
  };
  window.procStartQueueFromStep1 = function() {
    if (!window.procValidatePublishPage()) return;
    if (window._procRunning || window._step1Downloading ||
        (window._batchQueue || []).some(t => t.status === 'processing' || t.status === 'downloading')) {
      toast('Hàng chờ đang tải hoặc xử lý video, vui lòng đợi hoàn tất.', 'info');
      return;
    }
    if (!(window._batchQueue || []).some(t => (t.status === 'pending' || t.status === 'ready') && (t.queue_mode || 'process') === 'process')) {
      toast('Vui lòng thêm video vào hàng chờ để xử lý.', 'warning');
      return;
    }
    window._procProcessAll = true;
    if (typeof procSaveStep === 'function') procSaveStep(2, true);
    procWizGo(3);
    window._step3StartProc();
  };

  window.procStartQueueFromStep2 = function() {
    if (!window.procValidatePublishPage()) return;
    if (window._procRunning || window._step1Downloading ||
        (window._batchQueue || []).some(t => t.status === 'processing' || t.status === 'downloading')) {
      toast('Hàng chờ đang tải hoặc xử lý video, vui lòng đợi hoàn tất.', 'info');
      return;
    }
    if (!(window._batchQueue || []).some(t => (t.status === 'pending' || t.status === 'ready') && (t.queue_mode || 'process') === 'process')) {
      toast('Hãy chọn “Tải và xử lý” cho ít nhất một video trong hàng chờ.', 'warning');
      return;
    }
    window._procProcessAll = true;
    if (typeof procSaveStep === 'function') procSaveStep(2, true);
    procWizGo(3);
    window._step3StartProc();
  };

  window._step3StartProc = function(all = true) {
    // Keep the mode explicit for this run.
    window._procProcessAll = all;
    if (!all) window._procAutoDrain = false;

    // Apply skip flags from checkboxes before starting
    window._procSkipReviewSession = document.getElementById('step3-skip-ass')?.checked ?? false;
    window._procSkipThumbSession  = false;

    // Check if there are tasks in the queue waiting or ready
    const hasQueueTasks = (window._batchQueue || []).some(t => (t.status === 'pending' || t.status === 'ready') && (t.queue_mode || 'process') === 'process');
    if (hasQueueTasks) {
      window._step3Started = true;
      window._procRunning = false; // ensure _runBatchQueueFlow can proceed
      _step3RefreshStartCard();
      _runBatchQueueFlow();
      return;
    }

    window._procProcessAll = false;
    toast('Không có video nào được chọn “Tải và xử lý”.', 'warning');
  };

  /** Sync checkbox state to global flags in real-time */
  window._onStep3SkipChange = function() {
    const active = document.getElementById('step3-skip-ass')?.checked ?? false;
    const step3 = document.getElementById('step3-skip-ass-step3');
    if (step3) step3.checked = active;
    window._procSkipReviewSession = active;
    window._procSkipThumbSession  = false;
  };

  /** Sync skip-transcription checkboxes across steps */
  window._onSkipTranscriptionChange = function() {
    const cb1 = document.getElementById('proc-skip-transcription');
    const cb3 = document.getElementById('step3-skip-transcription-step3');
    if (cb1 && cb3) {
      if (typeof event !== 'undefined' && event && event.target === cb3) {
        cb1.checked = cb3.checked;
      } else if (typeof event !== 'undefined' && event && event.target === cb1) {
        cb3.checked = cb1.checked;
      }
    }
    if (typeof procWizUpdateSummary === 'function') {
      procWizUpdateSummary();
    }
  };


  /** Render the step-3 queue status panel */
  function _step3RenderQueue() {
    const list    = document.getElementById('step3-queue-list');
    const summary = document.getElementById('step3-queue-summary');
    if (!list) return;
    const q = window._batchQueue || [];
    if (!q.length) {
      list.innerHTML = '<div class="empty-state text-xs">Chưa có video nào trong hàng chờ.</div>';
      if (summary) summary.textContent = '';
      return;
    }
    const statusLabel = {
      pending:     'Chờ tải',
      downloading: 'Đang tải...',
      ready:       'Sẵn sàng',
      processing:  'Đang xử lý...',
      done:        'Hoàn thành',
      error:       'Lỗi',
    };
    const badgeClass = {
      pending: 'badge-gray', downloading: 'badge-yellow',
      ready: 'badge-accent', processing: 'badge-yellow',
      done: 'badge-green', error: 'badge-red',
    };
    list.innerHTML = q.map((t,i) => {
      const labelCfg = getTaskConfigLabel(t);
      const isRunningNow = t.status === 'processing' && window._procRunning;
      const isLocked = isRunningNow || t.status === 'downloading';
      const isReadyOrPending = (t.status === 'ready' || t.status === 'pending') && !isRunningNow;
      const cfgBtnHtml = isReadyOrPending ? `
        <div style="position:relative;display:inline-block">
          <button data-cfg-btn class="btn btn-outline btn-xs" onclick="window._toggleItemCfgDropdown('${t.id}', event)" style="font-size:10px;padding:2px 6px;height:24px;line-height:20px;border-color:var(--border);border-radius:4px;display:flex;align-items:center;gap:3px;white-space:nowrap">
            ${_processSvgIcon('settings')} ${labelCfg}
          </button>

        </div>
      ` : '';

      const cancelBtnHtml = isRunningNow ? `
        <button onclick="procCancelCurrentVideo()" class="btn btn-outline btn-xs" title="Hủy video đang xử lý này" style="font-size:10px;padding:2px 7px;height:24px;line-height:20px;border-color:#ef4444;color:#ef4444;border-radius:6px;display:inline-flex;align-items:center;gap:4px;white-space:nowrap;background:rgba(239,68,68,0.08);cursor:pointer;font-weight:600">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          <span>Hủy</span>
        </button>
      ` : '';

      const resetBtnHtml = (!isRunningNow && (t.status === 'done' || t.status === 'error' || t.status === 'processing')) ? `
        <button onclick="window._resetQueueItemStatus('${t.id}')" class="btn-icon text-accent" title="Đặt lại trạng thái Sẵn sàng" style="font-size:12px;padding:2px 4px;border:none;background:transparent;cursor:pointer">${_processSvgIcon('refresh')}</button>
      ` : '';

      const deleteBtnHtml = !isLocked ? `
        <button onclick="window._deleteQueueItem('${t.id}')" class="btn-icon text-red" title="Xóa khỏi hàng chờ" style="font-size:14px;padding:2px 4px;border:none;background:transparent;cursor:pointer">${_processSvgIcon('close')}</button>
      ` : '';

      return `
      <div ondragover="window._procQueueDragOver(event)" ondrop="window._procQueueDrop(event,${i})" style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:${t.id === window._procCurrentTaskId ? 'rgba(99,91,250,.10)' : 'var(--bg3)'};border:1px solid ${t.id === window._procCurrentTaskId ? '#635bfa' : 'var(--border)'};border-radius:6px;font-size:12px;box-shadow:${t.id === window._procCurrentTaskId ? '0 0 0 2px rgba(99,91,250,.12)' : 'none'}">
        <span draggable="${isLocked ? 'false' : 'true'}" ondragstart="window._procQueueDragStart(event,${i})" title="Kéo để đổi thứ tự" aria-label="Kéo để đổi thứ tự" style="cursor:grab;color:var(--text-muted);font-size:17px;line-height:1;user-select:none;touch-action:none">⠿</span>
        <span style="color:var(--text-muted)">${_processSvgIcon('video')}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)" title="${t.val}">${t.desc || t.val}</span>
        <span class="badge ${badgeClass[t.status] || 'badge-gray'}">${t.queue_mode === 'skip' && t.status === 'pending' ? 'Bỏ qua' : (statusLabel[t.status] || t.status)}</span>
        ${cfgBtnHtml}
        ${cancelBtnHtml}
        ${resetBtnHtml}
        ${deleteBtnHtml}
      </div>`;
    }).join('');
    const done    = q.filter(t => t.status === 'done').length;
    const total   = q.length;
    const pending = q.filter(t => (t.status === 'ready' || t.status === 'pending') && (t.queue_mode || 'process') === 'process').length;
    if (summary) summary.textContent = `${done}/${total} hoàn thành${pending ? ` · ${pending} chờ` : ''}`;
  }

  function _onAutoDrainToggle() {
    const on = document.getElementById('batch-auto-drain')?.checked;
    window._procAutoDrain = !!on;
    const status = document.getElementById('batch-drain-status');
    if (status) {
      status.textContent = on
        ? ' Đang bật — sẽ tự động xử lý video mới thêm vào.'
        : '';
    }
    if (on && !window._procRunning) {
      // Start draining the current queue
      _runBatchQueueFlow();
    }
  }

  function _pickNextPendingTask() {
    if (!window._procRunning) {
      (window._batchQueue || []).forEach(t => {
        if (t.status === 'processing') t.status = 'ready';
      });
    }
    return window._batchQueue.find(t => (t.status === 'pending' || t.status === 'ready') && (t.queue_mode || 'process') === 'process');
  }

  function _runBatchQueueFlow() {
    if (window._procRunning) {
      // Safety: if the button says "Xử lý Video" (not disabled), the previous
      // task likely finished without properly resetting _procRunning (e.g. network
      // error, preflight cancel, or empty path). Force-reset so queue can continue.
      const btn = document.getElementById('btn-proc');
      if (btn && !btn.disabled) {
        console.warn('[BatchQueue] _procRunning was stuck — force resetting');
        window._procRunning = false;
        // Also mark the "processing" task as error so it doesn't block
        const stuck = window._batchQueue.find(t => t.status === 'processing');
        if (stuck) stuck.status = 'error';
        _renderBatchQueue();
      } else {
        toast('Đang xử lý — vui lòng đợi', 'info');
        return;
      }
    }
    const next = _pickNextPendingTask();
    if (!next) {
      if (window._procAutoDrain) {
        // Keep waiting for new items
        toast('Hàng chờ trống — đang chờ video mới...', 'info');
      } else {
        toast('Hàng chờ trống', 'warning');
      }
      return;
    }

    // Reset batch schedule counter only at the start of a fresh batch
    // (auto-drain keeps counter incremented across videos for consistent scheduling)
    if (window._pBschedCounter == null) window._pBschedCounter = 0;
    // Reset cancel flag at start of each batch — user can cancel via upload error modal
    window._pPubCancelled = false;

    next.status = 'processing';
    window._procCurrentTaskId = next.id;
    window._procRunning = true;
    localStorage.setItem('_proc_active_run_v1', JSON.stringify({
      taskId: next.id,
      startedAt: Date.now(),
      state: 'running'
    }));
    window._procQueueSaveToLocalStorage?.();
    _renderBatchQueue();

    toast(`Bắt đầu xử lý: ${next.desc || next.val}`, 'info');

    // Apply task custom configuration to inputs
    const globalAuto = document.getElementById('proc-auto-flow');
    const globalSkipAss = document.getElementById('step3-skip-ass');
    const globalSkipTrans = document.getElementById('proc-skip-transcription');

    if (next.auto_flow !== undefined && globalAuto) {
      globalAuto.checked = next.auto_flow;
    }
    if (next.skip_ass !== undefined) {
      if (globalSkipAss) globalSkipAss.checked = next.skip_ass;
      window._procSkipReviewSession = next.skip_ass;
      window._onStep3SkipChange?.();
    }
    if (next.skip_trans !== undefined) {
      if (globalSkipTrans) globalSkipTrans.checked = next.skip_trans;
      if (window._onSkipTranscriptionChange) window._onSkipTranscriptionChange();
    }

    const isHttpUrl = /^https?:\/\//i.test(next.val || '');
    const urlEl = document.getElementById('proc-url');
    const pathEl = document.getElementById('proc-video');
    if (isHttpUrl) {
      if (urlEl) urlEl.value = next.val;
      if (pathEl) pathEl.value = '';
    } else {
      if (pathEl) pathEl.value = next.val;
      if (urlEl) urlEl.value = '';
    }
    startProcessVideo();
  }

  /** Called from app.js when a video finishes processing (success OR error) */
  window._onProcTaskFinished = function(ok) {
    if (ok && typeof loadStep3DownloadedVideos === 'function') loadStep3DownloadedVideos();
    const id = window._procCurrentTaskId;
    if (id) {
      const t = window._batchQueue.find(x => x.id === id);
      if (t) {
        t.status = ok ? 'done' : 'error';
        if (!ok) {
          _appendProcLog?.(` Task "${t.desc || t.val}" thất bại — chuyển sang task tiếp theo`, 'warning');
        }
      }
    }
    window._procCurrentTaskId = null;
    window._procRunning = false;
    window._procRecoveredRun = null;
    localStorage.removeItem('_proc_active_run_v1');
    // Reset _step3Started so the "Bắt đầu xử lý" card can appear for the next task
    window._step3Started = false;
    // Reset skip flags for next task (unless auto-drain is keeping them intentionally)
    if (!window._procAutoDrain) {
      window._procSkipReviewSession = false;
      window._procSkipThumbSession  = false;
      // Sync checkboxes back to unchecked
      const cbAss   = document.getElementById('step3-skip-ass');
      if (cbAss)   cbAss.checked   = false;
    }
    _renderBatchQueue();

    // Stay on Step 3 after both success and failure so the result/log remains visible.

    // Auto-process entire queue when "Xử lý tất cả" was clicked or auto-drain is enabled
    if (window._procProcessAll || window._procAutoDrain) {
      const next = _pickNextPendingTask();
      if (next) {
        window._step3Started = true;
        _appendProcLog?.(` Chuyển sang video tiếp theo: "${next.desc || next.val}"...`, 'info');
        // Small delay to let UI breathe
        setTimeout(() => _runBatchQueueFlow(), 1000);
      } else {
        window._procProcessAll = false;
        window._step3Started = false;
        _step3RefreshStartCard();
        if (typeof toast === 'function') toast('🎉 Đã hoàn tất xử lý toàn bộ hàng chờ video!', 'success');
        _appendProcLog?.('🎉 Đã hoàn tất xử lý toàn bộ hàng chờ video!', 'success');
      }
    } else {
      // Reset session-only skip flag when a manual batch ends
      window._procSkipReviewSession = false;
    }
  };

  /* ── ASS Review ── */
  // Session-only skip flag: resets when user manually starts a fresh batch
  // (auto-drain keeps it across videos so "Bỏ qua" applies to the rest of the run)
  window._procSkipReviewSession = false;
  // Thumbnail flow disabled by request.
  window._procSkipThumbSession = false;
  window._procReviewResolve = null; // Promise resolver waiting for user confirm
  window._procAssPath = '';
  // Remove legacy persistent flag (migration from previous version)
  try { localStorage.removeItem('proc_skip_review'); } catch (_) {}




  // Thumbnail picker/retry flow disabled by request; keep no-op handlers for stale UI/cache.
  function procThumbPickModeChange() {}
  function procThumbPickPreview() {}
  function _showThumbFailCard() {}
  function _hideThumbFailCard() {}
  async function procThumbFailRetry() {}
  async function procThumbFailUpload() {}
  async function procThumbFailSkip() {}

  // ── TTS partial failure recovery ────────────────────────────────────
  function _hideTtsFailModal() {
    document.getElementById('proc-tts-fail-modal')?.remove();
  }


  async function _resolveTtsFailure(action) {
    const modal = document.getElementById('proc-tts-fail-modal');
    if (modal?.dataset.resolving === '1') return;
    if (modal) {
      modal.dataset.resolving = '1';
      modal.querySelectorAll('button').forEach(btn => { btn.disabled = true; });
    }
    try {
      const response = await fetch('/api/proc_retry_tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      _hideTtsFailModal();
      if (action === 'retry') toast('Đang thử lại riêng các đoạn TTS bị thiếu...', 'info');
    } catch (e) {
      if (modal) {
        delete modal.dataset.resolving;
        modal.querySelectorAll('button').forEach(btn => { btn.disabled = false; });
      }
      toast('Không gửi được lựa chọn TTS: ' + e.message, 'error');
    }
  }

  function procTtsFailRetry() { return _resolveTtsFailure('retry'); }
  function procTtsFailContinue() { return _resolveTtsFailure('continue'); }
  function procTtsFailCancel() { return _resolveTtsFailure('cancel'); }
  window.procTtsFailRetry = procTtsFailRetry;
  window.procTtsFailContinue = procTtsFailContinue;
  window.procTtsFailCancel = procTtsFailCancel;

  async function _triggerFrameVideo() {
    // Get the current video being processed
    const videoPath = window._publishLastOutputPath
                   || document.getElementById('proc-video')?.value?.trim();
    if (!videoPath) return;

    // Upload logo if selected
    let logoPath = '';
    if (window._frameLogoFile) {
      try {
        const form = new FormData();
        form.append('file', window._frameLogoFile);
        form.append('type', 'logo');
        const r = await fetch('/api/upload_anti_fp_image', { method: 'POST', body: form });
        const d = await r.json();
        if (d.ok) logoPath = d.path;
      } catch (_) {}
    }

    const payload = {
      video_path:     videoPath,
      title:          document.getElementById('frame-title')?.value || '',
      title_size_pct: parseFloat(document.getElementById('frame-title-size')?.value || 5),
      title_weight:   parseInt(document.getElementById('frame-title-weight')?.value || 400, 10),
      title_bar_h_pct: parseFloat(document.getElementById('frame-title-bar-h')?.value || 6),
      title_margin_x_pct: parseFloat(document.getElementById('frame-title-margin-x')?.value || 5),
      title_color:    document.getElementById('frame-title-color')?.value || '#000000',
      blur_w_pct:     parseFloat(document.getElementById('frame-blur-w')?.value || 15),
      blur_opacity:   parseFloat(document.getElementById('frame-blur-opacity')?.value || 60) / 100,
      blur_mode:      document.querySelector('input[name="frame-blur-mode"]:checked')?.value || 'overlay',
      logo_path:      logoPath,
      logo_size_pct:  parseFloat(document.getElementById('frame-logo-size')?.value || 12),
      logo_top_pct:   parseFloat(document.getElementById('frame-logo-top')?.value || 3),
      logo_left_pct:  parseFloat(document.getElementById('frame-logo-left')?.value || 3),
      logo_radius_pct: parseFloat(document.getElementById('frame-logo-radius')?.value ?? 50),
      logo_start_sec: document.getElementById('frame-logo-start')?.value || null,
      logo_end_sec: document.getElementById('frame-logo-end')?.value || null,
    };

    _appendProcLog(' Đang tạo khung video...', 'info');
    try {
      const res  = await fetch('/api/make_vertical_video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.ok) {
        _appendProcLog(' Khung video: ' + data.output_path, 'success');
        window._publishLastOutputPath = data.output_path;
      } else {
        _appendProcLog(' Tạo khung thất bại: ' + (data.error || ''), 'error');
      }
    } catch (e) {
      _appendProcLog(' Lỗi tạo khung: ' + e.message, 'error');
    }
  }

  function _showAssReview(assPath, content) {
    window._procAssPath = assPath;
    const card = document.getElementById('proc-ass-review-card');
    const pathEl = document.getElementById('proc-ass-review-path');
    const ta = document.getElementById('proc-ass-review-content');
    if (pathEl) { pathEl.textContent = assPath; pathEl.title = assPath; }
    if (ta) {
      ta.value = content || '';
      ta.style.removeProperty('height');
      ta.scrollTop = 0;
    }
    if (card) {
      card.style.display = 'block';
      // Auto-navigate to step 3 so user sees the review panel
      if (window._procWizStep !== 3) {
        procWizGo(3);
      }
      setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 150);
    }
  }

  /* ── Pause / Resume ── */
  window._procPaused = false;
  window._procReader = null; // current stream reader


  function _procShowPauseBtn(show) {
    const btn = document.getElementById('btn-proc-pause');
    if (btn) btn.style.display = show ? 'inline-flex' : 'none';
    const act = document.getElementById('step3-running-actions');
    if (act) act.style.display = show ? 'grid' : 'none';
    if (!show) { window._procPaused = false; if (btn) { btn.textContent = ' Dừng'; btn.style.background = ''; btn.style.color = ''; btn.style.borderColor = ''; } }
  }

  window.procCancelCurrentVideo = function() {
    window._procCurrentCancelled = true;
    fetch('/api/proc_cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'current' })
    }).catch(() => {});

    try { if (window._procAbortController) window._procAbortController.abort(); } catch(_) {}
    try { if (window._procReader) window._procReader.cancel(); } catch(_) {}

    if (typeof _appendProcLog === 'function') {
      _appendProcLog('⛔ Đã hủy xử lý video hiện tại.', 'warning');
    }
    if (typeof _setProcProgress === 'function') {
      _setProcProgress(0, 'Đã hủy');
    }

    const cur = (window._batchQueue || []).find(t => t.id === window._procCurrentTaskId || t.status === 'processing');
    if (cur) {
      cur.status = 'error';
      cur.desc = (cur.desc || cur.val) + ' (Đã hủy)';
    }

    window._procRunning = false;
    window._procPaused = false;
    _step3RefreshStartCard();
    _step3RenderQueue();
    _procShowPauseBtn(false);

    if (typeof toast === 'function') toast('Đã hủy xử lý video hiện tại', 'warning');

    // If "Xử lý tất cả" is active, skip to the next pending video
    if (window._procProcessAll) {
      const next = _pickNextPendingTask();
      if (next) {
        _appendProcLog?.(` Đang chuyển sang video tiếp theo trong hàng chờ: "${next.desc || next.val}"...`, 'info');
        setTimeout(() => _runBatchQueueFlow(), 1200);
      } else {
        window._procProcessAll = false;
        window._step3Started = false;
        _step3RefreshStartCard();
      }
    }
  };
  window.procCancelCurrent = window.procCancelCurrentVideo;

  window.procCancelAll = function() {
    window._procCancelled = true;
    window._procCurrentCancelled = true;
    window._procProcessAll = false; // STOP entire queue flow

    fetch('/api/proc_cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'all' })
    }).catch(() => {});

    try { if (window._procAbortController) window._procAbortController.abort(); } catch(_) {}
    try { if (window._procReader) window._procReader.cancel(); } catch(_) {}

    window._procRunning = false;
    window._step3Started = false;
    window._procAutoDrain = false;
    window._procPaused = false;

    const drainEl = document.getElementById('batch-auto-drain');
    if (drainEl) drainEl.checked = false;

    (window._batchQueue || []).forEach(t => {
      if (t.status === 'processing') {
        t.status = 'ready';
      }
    });

    if (typeof _appendProcLog === 'function') {
      _appendProcLog('⛔ Đã dừng toàn bộ hàng chờ và hủy tiến trình xử lý.', 'warning');
    }
    if (typeof _setProcProgress === 'function') {
      _setProcProgress(0, 'Đã dừng tất cả');
    }

    _step3RefreshStartCard();
    _step3RenderQueue();
    _procShowPauseBtn(false);

    if (typeof toast === 'function') toast('Đã dừng và hủy toàn bộ tiến trình xử lý', 'info');
  };

  // A reload interrupts the response stream. Restore the task as ready so the
  // user can safely continue; pipeline caches allow completed stages to be reused.
  if (window._procRecoveredRun) {
    setTimeout(() => {
      if (typeof procWizGo === 'function') procWizGo(3);
      _step3RenderQueue();
      _appendProcLog?.(' Trang đã được tải lại khi đang xử lý. Tác vụ đã chuyển về Sẵn sàng; bấm Tiếp tục xử lý hàng chờ để chạy tiếp từ dữ liệu đã lưu.', 'warning');
      const startText = document.querySelector('[onclick="_step3StartProc()"] span:last-child');
      if (startText) startText.textContent = 'Tiếp tục xử lý hàng chờ';
    }, 500);
  }

  /* ── Subtitle Preview ── */


  // ── Color picker sync ──
  window._videoOverlays = Array.isArray(window._videoOverlays) ? window._videoOverlays : [];



  function _uploadFileWithProgress(file, type, onProgress, onLoad, onError) {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload_anti_fp_image', true);

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        if (typeof onProgress === 'function') onProgress(pct);
      }
    };

    xhr.onload = function() {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          if (typeof onLoad === 'function') onLoad(data);
        } catch (err) {
          if (typeof onError === 'function') onError(err);
        }
      } else {
        if (typeof onError === 'function') onError(new Error('Upload failed with status ' + xhr.status));
      }
    };

    xhr.onerror = function(err) {
      if (typeof onError === 'function') onError(err);
    };

    const form = new FormData();
    form.append('file', file);
    form.append('type', type);
    xhr.send(form);
  }





  // Init picker on load

  function _getPreviewVideoPath() {
    // The explicit queue selection owns the preview, including URLs awaiting download.
    const selectedId = document.getElementById('pe2-queue-select')?.value;
    const selected = (window._batchQueue || []).find(t => t.id === selectedId);
    if (selected?.val) return { type: /^https?:\/\//i.test(selected.val) ? 'url' : 'file', val: selected.val };
    if (window._batchQueue && window._batchQueue.length > 0) {
      // Prefer the task currently being processed / waiting, so the preview
      // matches the file that will actually be processed. Fall back to any
      // finished item only if nothing is active (e.g. reviewing a done video).
      const active = (typeof window._resolveActiveQueueItem === 'function')
        ? window._resolveActiveQueueItem()
        : null;
      const ready = active || window._batchQueue.find(t =>
        t.status === 'ready' || t.status === 'processing' || t.status === 'done'
      ) || window._batchQueue[0];
      if (ready && ready.val) {
        // After download, URL items have their val updated to local file path
        // Detect by checking if val starts with http(s) — if not, it's a local path
        const isHttpUrl = /^https?:\/\//i.test(ready.val);
        if (isHttpUrl) {
          return { type: 'url', val: ready.val };   // still just a URL (not yet downloaded)
        } else {
          return { type: 'file', val: ready.val };  // local file path (file item OR downloaded URL)
        }
      }
    }
    if (window._procUploadedPath) return { type: 'file', val: window._procUploadedPath };
    const v = document.getElementById('proc-video')?.value?.trim();
    if (v) return { type: 'file', val: v };
    return null;
  }

  window._procVideoAiAnalysis = window._procVideoAiAnalysis || null;
  window._procVideoAiCache = window._procVideoAiCache || {};
  window._procUseAiAnalysis = window._procUseAiAnalysis || false;




















  window._step1Downloading = false;
  function _step1DownloadOnlyEnabled() {
    return document.getElementById('proc-download-only')?.checked || false;
  }
  function _step1GoFirstReadyToStep2(targetStep) {
    const firstReady = (window._batchQueue || []).find(t => t.id === window._procCurrentTaskId && t.status === 'ready')
      || (window._batchQueue || []).find(t => t.status === 'ready' && (t.queue_mode || 'process') === 'process');
    if (!firstReady) return false;
    const pathEl = document.getElementById('proc-video');
    const urlEl  = document.getElementById('proc-url');
    if (/^https?:\/\//i.test(firstReady.val || '')) {
      if (urlEl) urlEl.value = firstReady.val;
      if (pathEl) pathEl.value = '';
    } else {
      if (pathEl) pathEl.value = firstReady.val || '';
      if (urlEl) urlEl.value = '';
    }
    window._procCurrentTaskId = firstReady.id;
    window._step3Started = false;
    window._step3Confirmed = false;
    const step = targetStep || 2;
    _step1Log(` Đã tải hết hàng chờ. Chuyển sang Bước ${step}.`, 'success');
    setTimeout(() => procWizGo(step), 250);
    return true;
  }


  window.procWizStep2Continue = function(targetStep) {
    if (!window.procValidatePublishPage()) { window._step1ManualAction = null; return; }
    const queue = window._batchQueue || [];
    const selectedReady = queue.find(t => t.id === window._procCurrentTaskId && t.status === 'ready');
    const activeReady = (typeof window._resolveActiveQueueItem === 'function')
      ? window._resolveActiveQueueItem()
      : null;
    const readyTask = (selectedReady && (selectedReady.queue_mode || 'process') === 'process' ? selectedReady : null)
      || (activeReady && activeReady.status === 'ready' && (activeReady.queue_mode || 'process') === 'process' ? activeReady : null)
      || queue.find(t => t.status === 'ready' && (t.queue_mode || 'process') === 'process');
    if (!readyTask) {
      // Check if all done — suggest going to next step
      const allDone = (window._batchQueue || []).length > 0 &&
        (window._batchQueue || []).every(t => t.status === 'done' || t.status === 'error');
      if (allDone) {
        toast('Tất cả video trong hàng chờ đã xử lý xong!', 'info');
        window._step1ManualAction = null;
        return;
      }

      // Check if there are pending items that need downloading
      const hasPending = (window._batchQueue || []).some(t => t.status === 'pending');
      if (hasPending) {
        toast('Đang tự động tải video...', 'info');
        window._step1AfterDownloadTarget = targetStep || null;
        // Trigger download and wait for it to complete
        if (typeof _runStep1QueueDownload === 'function') {
          _runStep1QueueDownload();
        }
        return;
      }

      toast('Vui lòng thêm video và đợi tải video gốc hoàn tất ở Bước 1!', 'warning');
      window._step1ManualAction = null;
      return;
    }
    window._step3Started = false;  // Don't auto-start — wait for user to click "Bắt đầu xử lý" in step 3
    window._step3Confirmed = false;

    // Prepare the task for processing
    window._procCurrentTaskId = readyTask.id;
    readyTask.status = 'ready';  // Keep as ready, will change to processing when user clicks start
    _renderBatchQueue();

    // Feed the task's path into the form fields so startProcessVideo() can find it
    const pathEl = document.getElementById('proc-video');
    const urlEl  = document.getElementById('proc-url');
    // Check if val is still an HTTP URL (pending download) or local path (already downloaded)
    const isHttpUrl = /^https?:\/\//i.test(readyTask.val);
    if (isHttpUrl) {
      // Still a URL → feed to proc-url (will download)
      if (urlEl) urlEl.value = readyTask.val;
      if (pathEl) pathEl.value = '';
    } else {
      // Local file path (downloaded or uploaded file) → feed to proc-video (skip download)
      if (pathEl) pathEl.value = readyTask.val;
      if (urlEl) urlEl.value = '';
    }

    // Persist the exact Step 2 state before Step 3 renders its summary.
    if (typeof procSaveStep === 'function') procSaveStep(2, true);
    // Settings are ready; continue to the confirmation/start step.
    procWizGo(targetStep || 3);
    window._step1ManualAction = null;

    // DO NOT auto-start processing — user must navigate to step 3 and click "Bắt đầu xử lý"

  };

  // Re-render overlay on resize

  // Re-render when "Che phụ đề gốc" or "Ghi phụ đề" checkbox changes

  /* ════════════════════════════════════════════════════════
     FRAME VIDEO EDITOR — Canvas Preview
  ════════════════════════════════════════════════════════ */
  window._frameLogoImg  = null;
  window._frameLogoFile = null;
  window._frameLogoIsGif = false;   // logo hiện tại có phải GIF động không
  window._frameLogoSrc = '';
  window._frameAnimRAF  = null;     // id của vòng lặp animation (GIF)
  window._frameGifRestartTimer = null;
  window._rawFrameB64   = null; // Ảnh gốc từ video (không có logo)

  /* Vòng lặp vẽ lại canvas để GIF logo chạy liên tục.
     drawImage lấy đúng khung GIF mà <img> đang hiển thị, nên vẽ lại đều đặn
     sẽ làm GIF "động". Chỉ chạy khi: bật khung + logo là GIF.
     Việc chỉnh các thành phần khung không làm gián đoạn vòng lặp này. */


  function _getAudioDuration(file) {
    return new Promise((resolve) => {
      const audio = new Audio();
      audio.src = URL.createObjectURL(file);
      audio.addEventListener('loadedmetadata', () => {
        const d = audio.duration;
        URL.revokeObjectURL(audio.src);
        resolve(d);
      });
      audio.addEventListener('error', () => {
        resolve(0);
      });
    });
  }






  // Bind change events to sync input

  function _frameStopAnim() {
    if (window._frameAnimRAF) { cancelAnimationFrame(window._frameAnimRAF); window._frameAnimRAF = null; }
    _frameStopGifRestart();
  }
  function _frameStopGifRestart() {
    if (window._frameGifRestartTimer) {
      clearInterval(window._frameGifRestartTimer);
      window._frameGifRestartTimer = null;
    }
  }
  function _frameGifFreshSrc(src) {
    src = String(src || '');
    if (!src || src.startsWith('data:')) return src;
    src = src.replace(/([?&])gif_replay=\d+/g, '').replace(/[?&]$/, '');
    return src + (src.includes('?') ? '&' : '?') + 'gif_replay=' + Date.now();
  }
  /* Gán logo cho preview + tự bật/tắt animation tùy GIF. */
  function _isGifSrc(s) { return /\.gif(\?|$)/i.test(String(s || '')); }



  // Load default/saved logo on page load

  // Initialize on DOM ready

  function _roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y,     x + w, y + r,     r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x,     y + h, x,     y + h - r, r);
    ctx.lineTo(x,     y + r);
    ctx.arcTo(x,     y,     x + r, y,         r);
    ctx.closePath();
  }



  /** Legacy selection painter kept for reference. */
  function _drawCanvasSelectionLegacy(ctx, x, y, w, h, withHandles) {
    ctx.save();
    // Blue selection rectangle
    ctx.strokeStyle = '#1a73e8';
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
    // Inner light glow
    ctx.strokeStyle = 'rgba(26,115,232,0.35)';
    ctx.lineWidth = 4;
    ctx.strokeRect(x + 2, y + 2, w - 4, h - 4);

    if (withHandles) {
      // East handle (right-middle, circle) — resize width
      const hr = 7;
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#1a73e8';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x + w, y + h / 2, hr, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
      // South handle (bottom-middle, square) — resize height
      ctx.beginPath();
      ctx.arc(x + w / 2, y + h, hr, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
    }
    ctx.restore();
  }

  function _drawCanvasSelection(ctx, x, y, w, h, withHandles, cornersOnly) {
    ctx.save();
    const rx = Math.round(x) + 0.5;
    const ry = Math.round(y) + 0.5;
    const rw = Math.max(1, Math.round(w));
    const rh = Math.max(1, Math.round(h));

    // Selection chrome is UI, not video content. Keep it the same compact
    // on-screen size regardless of source resolution or editor zoom.
    const canvasRect = ctx.canvas.getBoundingClientRect();
    const displayScaleX = canvasRect.width > 0 ? canvasRect.width / ctx.canvas.width : 1;
    const displayScaleY = canvasRect.height > 0 ? canvasRect.height / ctx.canvas.height : displayScaleX;
    // Canvas is sized from its displayed width; an absolute preview wrapper can
    // temporarily report a shorter height while its aspect is being updated.
    const displayScale = Math.max(0.01, displayScaleX || displayScaleY);
    const screenPx = px => px / displayScale;

    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = screenPx(3);
    ctx.setLineDash([]);
    ctx.strokeRect(rx, ry, rw, rh);

    ctx.strokeStyle = '#1a73e8';
    ctx.lineWidth = screenPx(1.25);
    ctx.strokeRect(rx, ry, rw, rh);

    if (withHandles) {
      const hs = Math.min(screenPx(7), Math.max(screenPx(4), Math.min(rw, rh) * 0.22));
      const hh = hs / 2;
      const pts = cornersOnly ? [
        [rx, ry],
        [rx + rw, ry],
        [rx + rw, ry + rh],
        [rx, ry + rh]
      ] : [
        [rx, ry],
        [rx + rw / 2, ry],
        [rx + rw, ry],
        [rx + rw, ry + rh / 2],
        [rx + rw, ry + rh],
        [rx + rw / 2, ry + rh],
        [rx, ry + rh],
        [rx, ry + rh / 2]
      ];
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#1a73e8';
      ctx.lineWidth = screenPx(1.25);
      pts.forEach(([px, py]) => {
        ctx.beginPath();
        ctx.rect(Math.round(px - hh) + 0.5, Math.round(py - hh) + 0.5, hs, hs);
        ctx.fill();
        ctx.stroke();
      });
    }
    ctx.restore();
  }


  /* ════════════════════════════════════════════════════════
     SAVE / RESTORE DEFAULTS — per aspect ratio (9:16 / 16:9)
  ════════════════════════════════════════════════════════ */

  // Currently active aspect ratio for save/restore. Set by:
  //  - aspect override dropdown
  // Defaults to '16x9' until a video is detected.
  window._procActiveAspect = '16x9';

  /** Classify width/height into '9x16' (vertical) or '16x9' (horizontal/square). */
  /** Read all preset map from storage (v2). Migrates from v1 if needed. */
  /** Apply the saved preset for window._procActiveAspect to the form. */

  // All field IDs to save (id → type)



  // Auto-restore on page load

  // ── Đổi khung hình Preview (16:9, 9:16, hoặc auto) ───────────


  // Auto-update frame preview when frame-enabled toggled

  // ── Thumbnail preview (chỉ hiển thị, không lưu file) ─────────────────────

  // ── Thumbnail helpers: Import / Clear / Toggle / Source tracking ─────────
  // window._thumbState: { mode: 'import'|'ai'|'frame'|'none', path: string, b64: string }
  window._thumbState = { mode: 'none', path: '', b64: '' };

  // ── Multiple blur zones ────────────────────────────────────────────────────
  window._procExtraBlurOpenIds = window._procExtraBlurOpenIds || [];








  function thumbClear() {
    const img = document.getElementById('thumb-preview-img');
    const ph  = document.getElementById('thumb-placeholder');
    const info = document.getElementById('thumb-output-info');
    if (img) { img.src = ''; img.style.display = 'none'; }
    if (ph) { ph.style.display = 'block'; ph.textContent = ' Import /  Tạo /  AI'; }
    if (info) info.style.display = 'none';
    window._thumbState = { mode: 'none', path: '', b64: '' };
    toast('Đã xóa thumbnail', 'info');
  }

  function thumbToggleEnabled() {
    const enabled = document.getElementById('thumb-enabled')?.checked;
    const wrap = document.getElementById('thumb-preview-wrap');
    if (wrap) wrap.style.opacity = enabled ? '1' : '0.4';
    if (!enabled) {
      toast('Đã tắt thumbnail (sẽ không chèn vào video)', 'info');
    }
  }


  window._thumbAiModelsLoaded = false;
  async function loadThumbAiModels() {
    window._thumbAiModelsLoaded = true;
  }
  // Thumbnail flow disabled by request.


  // Thumbnail editor/generation is disabled by request. Keep no-op handlers so
  // stale onclick/cache references do not break the process editor.
  window._thumbState = { mode: 'none', path: '', b64: '' };
  window.thumbClear = function() { window._thumbState = { mode: 'none', path: '', b64: '' }; };
  window.thumbToggleEnabled = function() {};
  window.loadThumbAiModels = async function() {};
  window._displayProcThumbnail = function() {};

  // ── Ytdlp Cookie Modal Handlers ──────────────────────────────────────────────
  window._ytdlpCookieFailedItem = null;
  window._step1DownloadPaused = false;


  const PLATFORM_LABELS = {
    youtube: 'YouTube',
    facebook: 'Facebook',
    tiktok: 'TikTok',
    instagram: 'Instagram',
    bilibili: 'Bilibili',
    kuaishou: 'Kuaishou',
    twitter: 'X / Twitter',
    unknown: 'Đa nền tảng'
  };

  const PLATFORM_COOKIE_FILES = {
    youtube: 'youtube_cookies.txt',
    facebook: 'facebook_cookies.txt',
    tiktok: 'tiktok_cookies.txt',
    instagram: 'instagram_cookies.txt',
    bilibili: 'cookies.txt',
    kuaishou: 'cookies.txt',
    twitter: 'cookies.txt',
    unknown: 'cookies.txt'
  };



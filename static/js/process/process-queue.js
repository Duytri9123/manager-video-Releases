window._batchQueue = window._batchQueue || [];

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
    };
  }

  function getTaskConfigLabel(t) {
    const parts = [];
    if (t.auto_flow) parts.push('1');
    if (t.skip_ass) parts.push('2');
    if (t.skip_trans) parts.push('3');
    return parts.length > 0 ? parts.join(',') : 'None';
  }

  window._toggleItemCfgDropdown = function(taskId, event) {
    event.stopPropagation();
    const panel = document.getElementById(`cfg-drop-${taskId}`);
    if (!panel) return;
    const isVisible = panel.style.display === 'block';
    // close all
    document.querySelectorAll('.cfg-dropdown-panel').forEach(p => p.style.display = 'none');
    if (!isVisible) {
      // Position fixed relative to the button
      const btn = event.currentTarget || event.target.closest('button[data-cfg-btn]');
      if (btn) {
        const rect = btn.getBoundingClientRect();
        panel.style.position = 'fixed';
        panel.style.top = (rect.bottom + 4) + 'px';
        panel.style.left = Math.max(8, rect.right - 200) + 'px';
        panel.style.zIndex = '99999';
      }
      panel.style.display = 'block';
    }
  };

  window._updateTaskConfig = function(taskId, key, value) {
    const t = window._batchQueue.find(x => x.id === taskId);
    if (t) {
      t[key] = value;
      _renderBatchQueue();
      _step3RenderQueue();
      if (typeof window._procQueueSaveToLocalStorage === 'function') window._procQueueSaveToLocalStorage();
    }
  };

  window.addEventListener('click', function(e) {
    if (!e.target.closest('.cfg-dropdown-panel') && !e.target.closest('button[data-cfg-btn]')) {
      document.querySelectorAll('.cfg-dropdown-panel').forEach(panel => {
        panel.style.display = 'none';
      });
    }
  });

  window._procQueueRefresh = function() {
    try {
      const localQueue = JSON.parse(localStorage.getItem('_proc_batch_queue') || '[]');
      const newQueue = [];
      localQueue.forEach(localItem => {
        const existing = window._batchQueue.find(item => item.val === localItem.val);
        if (existing) {
          newQueue.push(existing);
        } else {
          newQueue.push({
            id: localItem.id || 'bt-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
            type: localItem.type || 'file',
            val: localItem.val,
            status: localItem.status || 'pending',
            desc: localItem.desc || localItem.val,
            added: localItem.added || Date.now(),
            auto_flow: localItem.auto_flow !== undefined ? localItem.auto_flow : (document.getElementById('proc-auto-flow')?.checked ?? true),
            skip_ass: localItem.skip_ass !== undefined ? localItem.skip_ass : (document.getElementById('step3-skip-ass')?.checked ?? false),
            skip_trans: localItem.skip_trans !== undefined ? localItem.skip_trans : (document.getElementById('proc-skip-transcription')?.checked ?? false)
          });
        }
      });
      window._batchQueue.forEach(item => {
        if (!newQueue.some(ni => ni.val === item.val)) {
          newQueue.push(item);
        }
      });
      window._batchQueue = newQueue;
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
        skip_trans: item.skip_trans
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
      pending:     '⏳ Chờ',
      downloading: '📥 Đang tải...',
      ready:       '✅ Sẵn sàng',
      processing:  '⚙ Đang xử lý...',
      done:        '✔ Hoàn tất',
      error:       '❌ Lỗi',
    };
    list.innerHTML = window._batchQueue.map((t,i) => {
      let badgeClass = 'badge-gray';
      if (t.status === 'done') badgeClass = 'badge-green';
      else if (t.status === 'error') badgeClass = 'badge-red';
      else if (t.status === 'processing' || t.status === 'downloading') badgeClass = 'badge-yellow';
      else if (t.status === 'ready') badgeClass = 'badge-accent';
      
      const disableDel = (t.status === 'processing' || t.status === 'downloading') ? 'disabled' : '';
      const label = statusLabel[t.status] || t.status;

      // Inline config button
      const labelCfg = getTaskConfigLabel(t);
      const isReadyOrPending = t.status === 'ready' || t.status === 'pending';
      const cfgBtnHtml = isReadyOrPending ? `
        <div style="position:relative;display:inline-block">
          <button data-cfg-btn class="btn btn-outline btn-xs" onclick="window._toggleItemCfgDropdown('${t.id}', event)" style="font-size:10px;padding:2px 6px;height:24px;line-height:20px;border-color:var(--border);border-radius:4px;display:flex;align-items:center;gap:3px;white-space:nowrap">
            ⚙️ ${labelCfg}
          </button>
          <div id="cfg-drop-${t.id}" class="cfg-dropdown-panel" style="display:none;position:fixed;z-index:99999;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;box-shadow:0 8px 24px rgba(0,0,0,0.6);width:200px;text-align:left">
            <div style="font-weight:600;font-size:10px;margin-bottom:6px;color:var(--text-muted)">Cấu hình video này:</div>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:6px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.auto_flow ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'auto_flow', this.checked)">
              <span>1. Tự động hóa</span>
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:6px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.skip_ass ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'skip_ass', this.checked)">
              <span>2. Bỏ qua check ASS</span>
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.skip_trans ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'skip_trans', this.checked)">
              <span>3. Bỏ qua tạo phụ đề</span>
            </label>
          </div>
        </div>
      ` : '';

      return `
      <div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;font-size:12px">
        <span style="color:var(--text-muted)">${t.type==='url'?'🔗':'📄'}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)" title="${t.val}">${t.desc || t.val}</span>
        <span class="badge ${badgeClass}">${label}</span>
        ${cfgBtnHtml}
        <button onclick="window._batchQueue.splice(${i},1);_renderBatchQueue()" class="btn-icon text-red" style="font-size:14px" ${disableDel}>✕</button>
      </div>`;
    }).join('');

    const hasReady = window._batchQueue.some(t => t.status === 'ready' || t.status === 'done');
    const hasPending = window._batchQueue.some(t => t.status === 'pending');
    const hasAny = window._batchQueue.length > 0;
    const nextWrap = document.getElementById('step1-next-btn-wrap');
    if (nextWrap) {
      // Show "Tiếp theo" button as soon as there's anything in queue (not just when ready)
      // Hide only when auto-flow is on (it handles navigation automatically)
      nextWrap.style.display = (hasAny && !document.getElementById('proc-auto-flow')?.checked) ? 'block' : 'none';
    }

    // Update download button state
    const dlBtn = document.getElementById('btn-step1-download');
    const dlStatus = document.getElementById('step1-dl-status');
    if (dlBtn) {
      const isDownloading = window._step1Downloading;
      dlBtn.disabled = isDownloading;
      dlBtn.textContent = isDownloading ? '⏳ Đang tải...' : '📥 Tải hàng chờ';
    }
    if (dlStatus) {
      if (hasReady && !hasPending) {
        dlStatus.textContent = '✅ Tất cả video đã sẵn sàng.';
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

  /** Show/hide the "Start processing" card in step 3 based on queue readiness */
  function _step3RefreshStartCard() {
    const card = document.getElementById('step3-start-card');
    if (!card) return;

    // A ready item exists (downloaded or local file, not yet kicked off)
    const hasReady = (window._batchQueue || []).some(t => t.status === 'ready');

    // Pipeline already running or waiting for user (ASS review panel visible)
    const isRunning = window._procRunning || window._step3Started;

    // ASS review panel is open — pipeline is mid-flight, don't show start button
    const assOpen   = document.getElementById('proc-ass-review-card')?.style.display !== 'none';

    const onStep3 = window._procWizStep === 3;
    const shouldShow = hasReady && !isRunning && !assOpen && onStep3;
    card.style.display = shouldShow ? 'block' : 'none';
  }

  /** Called when user clicks "Bắt đầu xử lý" in step 3 */
  window._step3StartProc = function() {
    // Apply skip flags from checkboxes before starting
    window._procSkipReviewSession = document.getElementById('step3-skip-ass')?.checked ?? false;
    window._procSkipThumbSession  = false;
    
    // Mark as started and running
    window._step3Started = true;
    window._procRunning = true;
    
    // Update task status to processing
    if (window._procCurrentTaskId) {
      const t = (window._batchQueue || []).find(x => x.id === window._procCurrentTaskId);
      if (t) t.status = 'processing';
    }
    _renderBatchQueue();
    
    // Hide the start card immediately
    const card = document.getElementById('step3-start-card');
    if (card) card.style.display = 'none';
    
    // Start backend process!
    startProcessVideo();
  };

  /** Sync checkbox state to global flags in real-time */
  window._onStep3SkipChange = function() {
    window._procSkipReviewSession = document.getElementById('step3-skip-ass')?.checked ?? false;
    window._procSkipThumbSession  = false;
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
      pending:     '⏳ Chờ tải',
      downloading: '📥 Đang tải...',
      ready:       '✅ Sẵn sàng',
      processing:  '⚙ Đang xử lý...',
      done:        '✔ Hoàn thành',
      error:       '❌ Lỗi',
    };
    const badgeClass = {
      pending: 'badge-gray', downloading: 'badge-yellow',
      ready: 'badge-accent', processing: 'badge-yellow',
      done: 'badge-green', error: 'badge-red',
    };
    list.innerHTML = q.map(t => {
      const labelCfg = getTaskConfigLabel(t);
      const isReadyOrPending = t.status === 'ready' || t.status === 'pending';
      const cfgBtnHtml = isReadyOrPending ? `
        <div style="position:relative;display:inline-block">
          <button data-cfg-btn class="btn btn-outline btn-xs" onclick="window._toggleItemCfgDropdown('${t.id}', event)" style="font-size:10px;padding:2px 6px;height:24px;line-height:20px;border-color:var(--border);border-radius:4px;display:flex;align-items:center;gap:3px;white-space:nowrap">
            ⚙️ ${labelCfg}
          </button>
          <div id="cfg-drop-${t.id}" class="cfg-dropdown-panel" style="display:none;position:fixed;z-index:99999;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;box-shadow:0 8px 24px rgba(0,0,0,0.6);width:200px;text-align:left">
            <div style="font-weight:600;font-size:10px;margin-bottom:6px;color:var(--text-muted)">Cấu hình video này:</div>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:6px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.auto_flow ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'auto_flow', this.checked)">
              <span>1. Tự động hóa</span>
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:6px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.skip_ass ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'skip_ass', this.checked)">
              <span>2. Bỏ qua check ASS</span>
            </label>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;cursor:pointer;color:var(--text);user-select:none">
              <input type="checkbox" ${t.skip_trans ? 'checked' : ''} onchange="window._updateTaskConfig('${t.id}', 'skip_trans', this.checked)">
              <span>3. Bỏ qua tạo phụ đề</span>
            </label>
          </div>
        </div>
      ` : '';

      return `
      <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;font-size:12px">
        <span style="color:var(--text-muted)">${t.type === 'url' ? '🔗' : '📄'}</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)" title="${t.val}">${t.desc || t.val}</span>
        <span class="badge ${badgeClass[t.status] || 'badge-gray'}">${statusLabel[t.status] || t.status}</span>
        ${cfgBtnHtml}
      </div>`;
    }).join('');
    const done    = q.filter(t => t.status === 'done').length;
    const total   = q.length;
    const pending = q.filter(t => t.status === 'ready' || t.status === 'pending').length;
    if (summary) summary.textContent = `${done}/${total} hoàn thành${pending ? ` · ${pending} chờ` : ''}`;
  }

  function _onAutoDrainToggle() {
    const on = document.getElementById('batch-auto-drain')?.checked;
    window._procAutoDrain = !!on;
    const status = document.getElementById('batch-drain-status');
    if (status) {
      status.textContent = on
        ? '🔁 Đang bật — sẽ tự động xử lý video mới thêm vào.'
        : '';
    }
    if (on && !window._procRunning) {
      // Start draining the current queue
      _runBatchQueueFlow();
    }
  }

  function _pickNextPendingTask() {
    return window._batchQueue.find(t => t.status !== 'done' && t.status !== 'error' && t.status !== 'processing');
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
    }
    if (next.skip_trans !== undefined) {
      if (globalSkipTrans) globalSkipTrans.checked = next.skip_trans;
      if (window._onSkipTranscriptionChange) window._onSkipTranscriptionChange();
    }

    if (next.type === 'url') {
      const urlEl = document.getElementById('proc-url');
      const pathEl = document.getElementById('proc-video');
      if (urlEl) urlEl.value = next.val;
      if (pathEl) pathEl.value = '';
    } else {
      const pathEl = document.getElementById('proc-video');
      const urlEl = document.getElementById('proc-url');
      if (pathEl) pathEl.value = next.val;
      if (urlEl) urlEl.value = '';
    }
    startProcessVideo();
  }

  /** Called from app.js when a video finishes processing (success OR error) */
  window._onProcTaskFinished = function(ok) {
    const id = window._procCurrentTaskId;
    if (id) {
      const t = window._batchQueue.find(x => x.id === id);
      if (t) {
        t.status = ok ? 'done' : 'error';
        if (!ok) {
          _appendProcLog?.(`⚠ Task "${t.desc || t.val}" thất bại — chuyển sang task tiếp theo`, 'warning');
        }
      }
    }
    window._procCurrentTaskId = null;
    window._procRunning = false;
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

    // After successful processing, go to step 2 to review the output
    if (ok && !window._procAutoDrain) {
      setTimeout(() => procWizGo(2), 400);
    }

    // Auto-drain: immediately pick the next pending task (or wait if none)
    if (window._procAutoDrain) {
      const next = _pickNextPendingTask();
      if (next) {
        // Small delay to let UI breathe
        setTimeout(() => _runBatchQueueFlow(), 800);
      } else {
        const status = document.getElementById('batch-drain-status');
        if (status) status.textContent = '🔁 Đang chờ video mới...';
      }
    } else {
      // Reset session-only skip flag when a manual batch ends
      // (so "Bỏ qua" doesn't carry over to the next separate batch)
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
    };

    _appendProcLog('🎞 Đang tạo khung video...', 'info');
    try {
      const res  = await fetch('/api/make_vertical_video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.ok) {
        _appendProcLog('✅ Khung video: ' + data.output_path, 'success');
        window._publishLastOutputPath = data.output_path;
      } else {
        _appendProcLog('❌ Tạo khung thất bại: ' + (data.error || ''), 'error');
      }
    } catch (e) {
      _appendProcLog('❌ Lỗi tạo khung: ' + e.message, 'error');
    }
  }

  function _showAssReview(assPath, content) {
    window._procAssPath = assPath;
    const card = document.getElementById('proc-ass-review-card');
    const pathEl = document.getElementById('proc-ass-review-path');
    const ta = document.getElementById('proc-ass-review-content');
    if (pathEl) pathEl.textContent = '📄 ' + assPath;
    if (ta) ta.value = content || '';
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
    if (!show) { window._procPaused = false; if (btn) { btn.textContent = '⏸ Dừng'; btn.style.background = ''; btn.style.color = ''; btn.style.borderColor = ''; } }
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
    // Priority: uploaded file path → first ready/processing item in batch queue → proc-video field
    if (window._procUploadedPath) {
      return { type: 'file', val: window._procUploadedPath };
    }
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
    const firstReady = (window._batchQueue || []).find(t => t.status === 'ready');
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
    _step1Log(`✅ Đã tải hết hàng chờ. Chuyển sang Bước ${step}.`, 'success');
    setTimeout(() => procWizGo(step), 250);
    return true;
  }


  window.procWizStep2Continue = function(targetStep) {
    const firstReady = (window._batchQueue || []).find(t => t.status === 'ready');
    if (!firstReady) {
      // Check if all done — suggest going to next step
      const allDone = (window._batchQueue || []).length > 0 &&
        (window._batchQueue || []).every(t => t.status === 'done' || t.status === 'error');
      if (allDone) {
        toast('Tất cả video trong hàng chờ đã xử lý xong!', 'info');
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
      return;
    }
    window._step3Started = false;  // Don't auto-start — wait for user to click "Bắt đầu xử lý" in step 3
    window._step3Confirmed = false;

    // Prepare the task for processing
    window._procCurrentTaskId = firstReady.id;
    firstReady.status = 'ready';  // Keep as ready, will change to processing when user clicks start
    _renderBatchQueue();

    // Feed the task's path into the form fields so startProcessVideo() can find it
    const pathEl = document.getElementById('proc-video');
    const urlEl  = document.getElementById('proc-url');
    // Check if val is still an HTTP URL (pending download) or local path (already downloaded)
    const isHttpUrl = /^https?:\/\//i.test(firstReady.val);
    if (isHttpUrl) {
      // Still a URL → feed to proc-url (will download)
      if (urlEl) urlEl.value = firstReady.val;
      if (pathEl) pathEl.value = '';
    } else {
      // Local file path (downloaded or uploaded file) → feed to proc-video (skip download)
      if (pathEl) pathEl.value = firstReady.val;
      if (urlEl) urlEl.value = '';
    }

    // Settings are ready; continue to the confirmation/start step.
    procWizGo(targetStep || 3);
    
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

    ctx.strokeStyle = 'rgba(255,255,255,0.9)';
    ctx.lineWidth = 4;
    ctx.setLineDash([]);
    ctx.strokeRect(rx, ry, rw, rh);

    ctx.strokeStyle = '#1a73e8';
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, rw, rh);

    if (withHandles) {
      const hs = 10;
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
      ctx.lineWidth = 2;
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
    if (ph) { ph.style.display = 'block'; ph.textContent = '📁 Import / 🎨 Tạo / 🤖 AI'; }
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


  // Nạp danh sách mô hình AI tạo ảnh THẬT từ 9Router (/v1/models/image) vào
  // dropdown Thumbnail, nhóm theo provider (openai / cx / nb / google …).
  // Giữ option "auto" + Gemini (gọi trực tiếp) ở đầu.
  window._thumbAiModelsLoaded = false;
  async function loadThumbAiModels() {
    if (window._thumbAiModelsLoaded) return;
    const sel = document.getElementById('thumb-ai-model');
    if (!sel) return;
    window._thumbAiModelsLoaded = true;
    try {
      const r = await fetch('/api/chatbot/media_models?kind=image').then(res => res.json());
      if (!r || !r.ok || !Array.isArray(r.models) || !r.models.length) {
        window._thumbAiModelsLoaded = false; // chưa có dữ liệu → cho thử lại
        return;
      }
      // Xoá các optgroup 9Router cũ (nếu nạp lại), giữ 2 option tĩnh đầu tiên
      sel.querySelectorAll('optgroup[data-nr="1"]').forEach(g => g.remove());

      const existing = new Set(Array.from(sel.options).map(o => o.value));
      // Gom theo provider prefix trước dấu '/'
      const groups = {};
      r.models.forEach(function(m) {
        const id = (m && (m.id || m)) || '';
        if (!id || existing.has(id)) return;
        const prefix = id.includes('/') ? id.split('/')[0] : (m.owned_by || 'khác');
        (groups[prefix] = groups[prefix] || []).push(id);
      });
      const labelMap = {
        openai: '🟢 OpenAI', cx: '⭐ Codex (SSE)', nb: '🍌 NanoBanana',
        google: '🔷 Google', sdwebui: '🖥 Local (SD WebUI)', flux: '⚡ FLUX',
      };
      Object.keys(groups).forEach(function(prefix) {
        const grp = document.createElement('optgroup');
        grp.setAttribute('data-nr', '1');
        grp.label = labelMap[prefix] || ('9Router · ' + prefix);
        groups[prefix].forEach(function(id) {
          const opt = document.createElement('option');
          opt.value = id;
          opt.textContent = id;
          grp.appendChild(opt);
          existing.add(id);
        });
        sel.appendChild(grp);
      });
    } catch (_) {
      window._thumbAiModelsLoaded = false; // cho phép thử lại lần sau
    }
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



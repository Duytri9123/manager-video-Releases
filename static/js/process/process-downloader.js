async function _runStep1QueueDownload() {
    if (window._step1Downloading) return;
    const pending = (window._batchQueue || []).find(t => t.status === 'pending');
    if (!pending) {
      _renderBatchQueue();
      const target = window._step1AfterDownloadTarget;
      if (target || _step1DownloadOnlyEnabled()) {
        window._step1AfterDownloadTarget = null;
        _step1GoFirstReadyToStep2(target || 2);
      }
      return;
    }

    window._step1Downloading = true;
    _renderBatchQueue(); // update button disabled state immediately

    try {
      if (pending.type === 'url') {
        pending.status = 'downloading';
        _renderBatchQueue();
        _step1Log('📥 Bắt đầu tải: ' + pending.val, 'info');

        const dlStatus = document.getElementById('step1-dl-status');
        if (dlStatus) dlStatus.textContent = '📥 Đang tải video gốc...';

        const res = await fetch('/api/download_original_video', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: pending.val,
            out_dir: document.getElementById('proc-out')?.value?.trim() || ''
          })
        });
        let data;
        try {
          data = await res.json();
        } catch (jsonErr) {
          let txt = '';
          try { txt = await res.text(); } catch(_) {}
          throw new Error(txt.slice(0, 150) || 'Lỗi HTTP ' + res.status);
        }
        if (!res.ok || !data.ok) {
          throw new Error(data.error || 'Tải thất bại');
        }
        if (data.ok) {
          pending.status = 'ready';
          pending.val = data.path; // update to local path
          pending.desc = data.title || data.path.split(/[\\/]/).pop();
          _step1Log('✅ Tải xong: ' + (data.title || pending.desc), 'success');
          if (data.path) _step1Log('📁 Đường dẫn: ' + data.path, 'info');
          toast('📥 Đã tải video gốc: ' + (data.title || ''), 'success');
          
          // Fetch preview frame for Step 2
          setTimeout(() => { if (typeof subPreviewFetchFrame === 'function') subPreviewFetchFrame(); }, 300);

          // Auto-flow: skip Step 2, jump directly to Step 3
          if (document.getElementById('proc-auto-flow')?.checked && !_step1DownloadOnlyEnabled()) {
            _step1Log('🔁 Tự động hóa: chuyển sang Bước 3 (AI & Dịch)...', 'info');
            
            // Apply task custom configuration to inputs
            const globalAuto = document.getElementById('proc-auto-flow');
            const globalSkipAss = document.getElementById('step3-skip-ass');
            const globalSkipTrans = document.getElementById('proc-skip-transcription');
            if (pending.auto_flow !== undefined && globalAuto) globalAuto.checked = pending.auto_flow;
            if (pending.skip_ass !== undefined) {
              if (globalSkipAss) globalSkipAss.checked = pending.skip_ass;
              window._procSkipReviewSession = pending.skip_ass;
            }
            if (pending.skip_trans !== undefined) {
              if (globalSkipTrans) globalSkipTrans.checked = pending.skip_trans;
              if (window._onSkipTranscriptionChange) window._onSkipTranscriptionChange();
            }

            window._step3Started = true;
            window._step3Confirmed = false;
            window._procCurrentTaskId = pending.id;
            window._procRunning = true;
            pending.status = 'processing';
            const pathEl = document.getElementById('proc-video');
            const urlEl2 = document.getElementById('proc-url');
            if (pathEl) pathEl.value = pending.val;
            if (urlEl2) urlEl2.value = '';
            if (document.getElementById('proc-ai-video-auto')?.checked !== false && typeof procAnalyzeVideoAI === 'function') {
              _step1Log('🤖 AI đang phân tích video trước khi xử lý...', 'info');
              await procAnalyzeVideoAI({ force:false });
            }
            procWizGo(3);
            startProcessVideo();
          }
        } else {
          pending.status = 'error';
          pending.desc = 'Lỗi: ' + (data.error || 'Unknown error');
          _step1Log('❌ Tải thất bại: ' + (data.error || 'Unknown error'), 'error');
          toast('❌ Tải video lỗi: ' + (data.error || ''), 'error');

          // Check if this is a cookie/bot/lock error
          const errMsg = (data.error || '').toLowerCase();
          const isCookieErr = errMsg.includes('confirm you’re not a bot') ||
                              errMsg.includes('confirm you\'re not a bot') ||
                              errMsg.includes('sign in to confirm') ||
                              errMsg.includes('--cookies') ||
                              errMsg.includes('cookie database') ||
                              errMsg.includes('cookies for the authentication');
          if (isCookieErr) {
            if (typeof showYtdlpCookieModal === 'function') {
              showYtdlpCookieModal(data.error, pending);
            }
          }
        }
      } else {
        // File type — already on disk, just mark ready
        pending.status = 'ready';
        _step1Log('📄 File video sẵn sàng: ' + (pending.desc || pending.val.split(/[\\/]/).pop()), 'success');
        toast('📄 File video sẵn sàng', 'success');
        setTimeout(() => { if (typeof subPreviewFetchFrame === 'function') subPreviewFetchFrame(); }, 300);

        // Auto-flow
        if (document.getElementById('proc-auto-flow')?.checked && !_step1DownloadOnlyEnabled()) {
          _step1Log('🔁 Tự động hóa: chuyển sang Bước 3 (AI & Dịch)...', 'info');

          // Apply task custom configuration to inputs
          const globalAuto = document.getElementById('proc-auto-flow');
          const globalSkipAss = document.getElementById('step3-skip-ass');
          const globalSkipTrans = document.getElementById('proc-skip-transcription');
          if (pending.auto_flow !== undefined && globalAuto) globalAuto.checked = pending.auto_flow;
          if (pending.skip_ass !== undefined) {
            if (globalSkipAss) globalSkipAss.checked = pending.skip_ass;
            window._procSkipReviewSession = pending.skip_ass;
          }
          if (pending.skip_trans !== undefined) {
            if (globalSkipTrans) globalSkipTrans.checked = pending.skip_trans;
            if (window._onSkipTranscriptionChange) window._onSkipTranscriptionChange();
          }

          window._step3Started = true;
          window._step3Confirmed = false;
          window._procCurrentTaskId = pending.id;
          window._procRunning = true;
          pending.status = 'processing';
          const pathEl = document.getElementById('proc-video');
          const urlEl2 = document.getElementById('proc-url');
          if (pathEl) pathEl.value = pending.val;
          if (urlEl2) urlEl2.value = '';
          if (document.getElementById('proc-ai-video-auto')?.checked !== false && typeof procAnalyzeVideoAI === 'function') {
            _step1Log('🤖 AI đang phân tích video trước khi xử lý...', 'info');
            await procAnalyzeVideoAI({ force:false });
          }
          procWizGo(3);
          startProcessVideo();
        }
      }
    } catch (e) {
      pending.status = 'error';
      pending.desc = 'Lỗi kết nối';
      _step1Log('❌ Lỗi kết nối: ' + e.message, 'error');
      toast('❌ Lỗi kết nối tải video', 'error');
    } finally {
      window._step1Downloading = false;
      _renderBatchQueue();
      // Process next pending item if not paused
      if (!window._step1DownloadPaused) {
        const nextPending = (window._batchQueue || []).find(t => t.status === 'pending');
        if (nextPending) {
          setTimeout(() => _runStep1QueueDownload(), 600);
        } else {
          const target = window._step1AfterDownloadTarget;
          if (target || _step1DownloadOnlyEnabled()) {
            window._step1AfterDownloadTarget = null;
            _step1GoFirstReadyToStep2(target || 2);
          }
        }
      }
    }
  }
  async function _addCurrentToQueue() {

    // Wait for any in-progress file upload before reading paths
    if (window._procUploadPromise) {
      toast('⏳ Đang upload file... vui lòng đợi', 'info');
      try { await window._procUploadPromise; } catch(_) {}
    }

    const urlEl  = document.getElementById('proc-url');
    const pathEl = document.getElementById('proc-video');
    const url    = urlEl?.value?.trim();
    const path   = pathEl?.value?.trim();

    if (!url && !path) { toast('Vui lòng nhập URL hoặc chọn file video', 'warning'); return; }

    if (url) {
      window._batchQueue.push(buildNewTask('url', url));
      urlEl.value = '';
      toast('✅ Đã thêm URL vào hàng chờ', 'success');
    } else {
      window._batchQueue.push(buildNewTask('file', path));
      if (pathEl) pathEl.value = '';
      const nameEl = document.getElementById('proc-file-name');
      if (nameEl) nameEl.textContent = '--';
      toast('✅ Đã thêm file vào hàng chờ', 'success');
    }
    _renderBatchQueue();
    _step1UpdateDownloadArea();
  }
  function detectPlatform(url) {
    const low = (url || '').toLowerCase();
    if (low.includes('youtube.com') || low.includes('youtu.be') || low.includes('youtube-nocookie.com')) return 'youtube';
    if (low.includes('facebook.com') || low.includes('fb.watch') || low.includes('fb.com')) return 'facebook';
    if (low.includes('tiktok.com')) return 'tiktok';
    if (low.includes('instagram.com')) return 'instagram';
    if (low.includes('bilibili.com') || low.includes('b23.tv')) return 'bilibili';
    if (low.includes('kuaishou.com')) return 'kuaishou';
    if (low.includes('twitter.com') || low.includes('x.com')) return 'twitter';
    return 'unknown';
  }
  window.showYtdlpCookieModal = async function(errorMessage, pendingItem) {
    window._ytdlpCookieFailedItem = pendingItem;
    window._step1DownloadPaused = true;

    const modal = document.getElementById('ytdlp-cookie-modal');
    const errEl = document.getElementById('ytdlp-cookie-modal-error');
    const friendlyEl = document.getElementById('ytdlp-cookie-modal-friendly');
    const statusEl = document.getElementById('ytdlp-cookie-modal-status');

    const url = pendingItem ? pendingItem.val : '';
    const platform = detectPlatform(url);
    const label = PLATFORM_LABELS[platform] || 'Đa nền tảng';
    const filename = PLATFORM_COOKIE_FILES[platform] || 'cookies.txt';

    const titleEl = document.getElementById('ytdlp-cookie-modal-platform-title');
    const subEl = document.getElementById('ytdlp-cookie-modal-platform-sub');
    const filenameEl = document.getElementById('ytdlp-cookie-modal-cookie-file-name');

    if (titleEl) titleEl.textContent = label;
    if (subEl) subEl.textContent = label;
    if (filenameEl) filenameEl.textContent = filename;

    // Clean error message (remove ANSI color codes)
    const cleanErr = (errorMessage || '').replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '').trim();

    if (errEl) errEl.textContent = cleanErr;

    // Generate friendly Vietnamese error text
    let friendlyMsg = '';
    const low = cleanErr.toLowerCase();
    if (low.includes('confirm you’re not a bot') || low.includes('confirm you\'re not a bot') || low.includes('sign in to confirm')) {
      friendlyMsg = `🤖 <b>Phát hiện bot / Yêu cầu xác thực:</b><br>
      Nền tảng <b>${label}</b> đã chặn yêu cầu tải vì nghi ngờ là công cụ tự động (bot). Bạn cần cung cấp Cookie đăng nhập để tiếp tục tải.`;
    } else if (low.includes('could not copy chrome cookie database') || low.includes('cookie database')) {
      friendlyMsg = `🔒 <b>Lỗi khóa tệp Cookie của trình duyệt:</b><br>
      Trình duyệt bạn chọn hiện đang mở nên tệp tin Cookie bị khóa. Vui lòng tắt trình duyệt đó đi hoặc dùng file cookie thủ công.`;
    } else {
      friendlyMsg = `⚠️ <b>Cần Cookie đăng nhập:</b><br>
      Tải thất bại do nền tảng yêu cầu tài khoản/cookie hợp lệ để xem hoặc tải video.`;
    }
    if (friendlyEl) friendlyEl.innerHTML = friendlyMsg;

    if (statusEl) statusEl.textContent = 'Đang tải cấu hình hiện tại...';

    // Show modal
    if (modal) {
      modal.classList.remove('hidden');
      modal.style.display = 'flex';
    }

    // Reset button states
    const buttons = document.querySelectorAll('#ytdlp-cookie-modal-browser-grid button');
    buttons.forEach(btn => {
      btn.className = btn.className.replace(/\bbtn-primary\b/, 'btn-secondary');
      btn.disabled = false;
      btn.style.border = '';
    });

    // Load current config
    try {
      const res = await fetch('/api/ytdlp/cookie_config');
      const data = await res.json();
      if (data.ok) {
        const activeBrowser = data.cookies_from_browser || '';
        const activeBtn = document.querySelector(`#ytdlp-cookie-modal-browser-grid button[data-browser="${activeBrowser}"]`);
        if (activeBtn) {
          activeBtn.className = activeBtn.className.replace(/\bbtn-secondary\b/, 'btn-primary');
          activeBtn.style.border = '2px solid var(--primary, #3b82f6)';
        }
        if (statusEl) statusEl.textContent = '';
      } else {
        if (statusEl) statusEl.textContent = 'Không thể tải cấu hình cũ.';
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = 'Lỗi kết nối tải cấu hình.';
    }
  };
  window.ytdlpCookieModalCancel = function() {
    const modal = document.getElementById('ytdlp-cookie-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.style.display = 'none';
    }
    window._ytdlpCookieFailedItem = null;
    window._step1DownloadPaused = false;
  };
  window.ytdlpCookieModalSkip = function() {
    const modal = document.getElementById('ytdlp-cookie-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.style.display = 'none';
    }
    
    const failedItem = window._ytdlpCookieFailedItem;
    window._ytdlpCookieFailedItem = null;
    window._step1DownloadPaused = false;

    // Trigger next item in queue if exists
    const nextPending = (window._batchQueue || []).find(t => t.status === 'pending');
    if (nextPending && !window._step1Downloading) {
      _runStep1QueueDownload();
    }
  };
  window.ytdlpCookieModalSaveBrowser = async function(browser) {
    const statusEl = document.getElementById('ytdlp-cookie-modal-status');
    const buttons = document.querySelectorAll('#ytdlp-cookie-modal-browser-grid button');

    // Disable all browser buttons temporarily
    buttons.forEach(btn => btn.disabled = true);

    if (statusEl) {
      statusEl.textContent = '⏳ Đang lưu cấu hình và khởi chạy lại...';
      statusEl.style.color = 'var(--text)';
    }

    try {
      const res = await fetch('/api/ytdlp/save_cookie_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies_from_browser: browser })
      });
      const data = await res.json();
      if (data.ok) {
        if (statusEl) {
          statusEl.textContent = '✅ Đã lưu! Đang kết nối lại để tải video...';
          statusEl.style.color = 'var(--success, green)';
        }

        // Highlight selected
        buttons.forEach(btn => {
          btn.className = btn.className.replace(/\bbtn-primary\b/, 'btn-secondary');
          btn.style.border = '';
        });
        const activeBtn = document.querySelector(`#ytdlp-cookie-modal-browser-grid button[data-browser="${browser}"]`);
        if (activeBtn) {
          activeBtn.className = activeBtn.className.replace(/\bbtn-secondary\b/, 'btn-primary');
        }

        // Close modal and retry after a short delay
        setTimeout(() => {
          const modal = document.getElementById('ytdlp-cookie-modal');
          if (modal) {
            modal.classList.add('hidden');
            modal.style.display = 'none';
          }

          // Reset variables
          const failedItem = window._ytdlpCookieFailedItem;
          window._ytdlpCookieFailedItem = null;
          window._step1DownloadPaused = false;

          if (failedItem) {
            failedItem.status = 'pending';
            failedItem.desc = 'Đang thử lại...';
            _renderBatchQueue();
            
            // Trigger download queue
            window._step1Downloading = false;
            _runStep1QueueDownload();
          }
        }, 1200);
      } else {
        if (statusEl) {
          statusEl.textContent = '❌ Lỗi: ' + (data.error || 'Unknown error');
          statusEl.style.color = 'var(--danger, red)';
        }
        buttons.forEach(btn => btn.disabled = false);
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = '❌ Lỗi kết nối: ' + e.message;
        statusEl.style.color = 'var(--danger, red)';
      }
      buttons.forEach(btn => btn.disabled = false);
    }
  };


if (typeof _runStep1QueueDownload !== "undefined") window._runStep1QueueDownload = _runStep1QueueDownload;


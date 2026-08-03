(function(){
    window._procWizStep = window._procWizStep || 1;
    window._step3Started = false;
    window._step3Confirmed = false;
    var MAX = 5;

    // ── Per-step enter hook ──────────────────────────────────────────────────
    function _procWizEnterStep(n) {
      if (n === 2) {
        // Step 2: Sync proc-video from the ACTIVE queue item, then refresh frame preview.
        // Must resolve the task currently being processed (or the next one waiting) —
        // never an already-finished item, otherwise we'd grab the file from a done
        // item above in the queue ("lấy nhầm file trên").
        const item = (typeof window._resolveActiveQueueItem === 'function')
          ? window._resolveActiveQueueItem()
          : (window._batchQueue || []).find(t =>
              t.status === 'ready' || t.status === 'processing'
            );
        if (item && item.val) {
          const pathEl = document.getElementById('proc-video');
          const isHttpUrl = /^https?:\/\//i.test(item.val);
          if (pathEl && !isHttpUrl) {
            // Local path (file item or downloaded URL) — always sync to proc-video
            pathEl.value = item.val;
          }
          // Always refresh the frame preview when entering Step 2
          if (typeof subPreviewFetchFrame === 'function') {
            setTimeout(() => subPreviewFetchFrame(), 300);
          }
          if (document.getElementById('proc-ai-video-auto')?.checked !== false && typeof procMaybeAnalyzeVideoAI === 'function') {
            setTimeout(() => procMaybeAnalyzeVideoAI(), 700);
          }
        }
      }
      if (n === 3) {
        // Step 3: Show/hide the "Start processing" card based on queue readiness
        _step3RefreshStartCard();
        // Refresh queue panel when entering step 3
        _step3RenderQueue();

        // Sync checkboxes from Step 1 to Step 3
        const autoFlow1 = document.getElementById('proc-auto-flow');
        const autoFlow3 = document.getElementById('step3-auto-flow');
        if (autoFlow1 && autoFlow3) autoFlow3.checked = autoFlow1.checked;

        const skipAss1 = document.getElementById('step3-skip-ass');
        const skipAss3 = document.getElementById('step3-skip-ass-step3');
        if (skipAss1 && skipAss3) skipAss3.checked = skipAss1.checked;

        const skipTrans1 = document.getElementById('proc-skip-transcription');
        const skipTrans3 = document.getElementById('step3-skip-transcription-step3');
        if (skipTrans1 && skipTrans3) skipTrans3.checked = skipTrans1.checked;
      }
    }

    window.procWizGo = function(n, _forceForward){
      n = Math.max(1, Math.min(MAX, n));
      window._procWizStep = n;
      var root = document.getElementById('page-process');
      if (!root) return;
      root.querySelectorAll('.proc-step').forEach(function(s){
        s.style.display = (parseInt(s.dataset.procStep, 10) === n) ? 'block' : 'none';
      });
      root.querySelectorAll('.proc-wiz-item').forEach(function(it){
        var sn = parseInt(it.dataset.step, 10);
        it.classList.toggle('active', sn === n);
        it.classList.toggle('done', sn < n);
      });
      var prev = document.getElementById('proc-wiz-prev');
      var next = document.getElementById('proc-wiz-next');
      var hint = document.getElementById('proc-wiz-hint');
      if (prev) prev.style.visibility = (n === 1) ? 'hidden' : 'visible';
      if (next) next.textContent = (n === MAX) ? '✓ Hoàn tất' : 'Tiếp theo →';
      if (hint) hint.textContent = 'Bước ' + n + ' / ' + MAX;
      var c = document.getElementById('content'); if (c) c.scrollTop = 0;

      // Run per-step enter hooks
      _procWizEnterStep(n);
    };

    // Prev: always allow going back without guards
    window.procWizPrev = function(){
      if (window._procWizStep > 1) {
        // Pass current step + 1 to make goingForward = false in procWizGo
        // (n = cur-1 < cur, so guard won't fire)
        window.procWizGo(window._procWizStep - 1);
      }
    };

    window.procWizNext = function(){ if (window._procWizStep < MAX) window.procWizGo(window._procWizStep + 1); };

    // Initialise immediately (all step nodes precede this script in the DOM).
    window.procWizGo(1);
  })();




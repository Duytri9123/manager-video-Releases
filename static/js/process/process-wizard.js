(function(){
    window._procWizStep = window._procWizStep || 1;
    window._step3Started = false;
    window._step3Confirmed = false;
    var MAX = 4;

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
        // Ensure video input is synced from active queue item if not already set
        const pathEl = document.getElementById('proc-video');
        const urlEl  = document.getElementById('proc-url');
        if ((!pathEl || !pathEl.value.trim()) && (!urlEl || !urlEl.value.trim())) {
          const item = (typeof window._resolveActiveQueueItem === 'function')
            ? window._resolveActiveQueueItem()
            : (window._batchQueue || []).find(t => t.status === 'ready' || t.status === 'processing');
          if (item && item.val) {
            const isHttpUrl = /^https?:\/\//i.test(item.val);
            if (isHttpUrl) {
              if (urlEl) urlEl.value = item.val;
            } else {
              if (pathEl) pathEl.value = item.val;
            }
          }
        }

        // Step 3: Show/hide the "Start processing" card based on queue readiness
        if (!window._procRunning) {
          (window._batchQueue || []).forEach(t => {
            if (t.status === 'processing') t.status = 'ready';
          });
        }
        if (typeof _step3RefreshStartCard === 'function') _step3RefreshStartCard();
        // Refresh queue panel when entering step 3
        if (typeof _step3RenderQueue === 'function') _step3RenderQueue();
        if (typeof refreshSharedConfigSummary === 'function') refreshSharedConfigSummary();

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
      // Auto-save previous step configuration silently before moving
      if (typeof procSaveDefaults === 'function') {
        try { procSaveDefaults(true); } catch (_) {}
      }

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

    function _getSelectText(el, fallback) {
      if (!el) return fallback || '';
      const opt = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
      let res = opt ? (opt.textContent || opt.text || '').trim() : (el.value || fallback || '');
      if (res === 'Google Gemini') res = 'Antigravity';
      return res;
    }

    function refreshSharedConfigSummary() {
      // 1. Ngôn ngữ
      const elLang = document.getElementById('step3-config-language');
      if (elLang) {
        const src = _getSelectText(document.getElementById('proc-lang'), 'Tiếng Trung');
        const tgt = _getSelectText(document.getElementById('proc-target-lang'), 'Tiếng Việt');
        const txt = `${src} → ${tgt}`;
        elLang.textContent = txt;
        elLang.title = txt;
      }

      // 2. Phiên âm (STT)
      const elStt = document.getElementById('step3-config-transcribe');
      if (elStt) {
        const sttTgl = document.getElementById('cfg-toggle-stt');
        const skipTrans = document.getElementById('proc-skip-transcription') || document.getElementById('step3-skip-transcription-step3');
        if ((sttTgl && !sttTgl.checked) || (skipTrans && skipTrans.checked)) {
          elStt.textContent = 'Tắt (Bỏ qua)';
          elStt.title = 'Bỏ qua tạo phụ đề';
          elStt.classList.add('text-slate-400');
          elStt.classList.remove('text-slate-800', 'dark:text-slate-200');
        } else {
          const prov = _getSelectText(document.getElementById('proc-transcribe-provider-model'), 'Antigravity');
          let model = _getSelectText(document.getElementById('proc-model'), '');
          if (model === 'Đang tải...' || !model) model = 'Gemini 3.6 Flash';
          const txt = `${prov} · ${model}`;
          elStt.textContent = txt;
          elStt.title = txt;
          elStt.classList.remove('text-slate-400');
          elStt.classList.add('text-slate-800', 'dark:text-slate-200');
        }
      }

      // 3. Dịch thuật
      const elTrans = document.getElementById('step3-config-translate');
      if (elTrans) {
        const transTgl = document.getElementById('cfg-toggle-trans');
        if (transTgl && !transTgl.checked) {
          elTrans.textContent = 'Tắt';
          elTrans.title = 'Tắt dịch phụ đề';
          elTrans.classList.add('text-slate-400');
          elTrans.classList.remove('text-slate-800', 'dark:text-slate-200');
        } else {
          const prov = _getSelectText(document.getElementById('proc-translation-provider'), 'Antigravity');
          let model = _getSelectText(document.getElementById('proc-trans-provider-model'), 'Tự động');
          if (model === 'Đang tải...' || !model) model = 'Tự động';
          const txt = `${prov} · ${model}`;
          elTrans.textContent = txt;
          elTrans.title = txt;
          elTrans.classList.remove('text-slate-400');
          elTrans.classList.add('text-slate-800', 'dark:text-slate-200');
        }
      }

      // 4. Đọc video AI
      const elVid = document.getElementById('step3-config-video');
      if (elVid) {
        const vidTgl = document.getElementById('cfg-toggle-video-ai');
        const vidModelEl = document.getElementById('proc-ai-video-nine-model');
        const vidVal = vidModelEl ? vidModelEl.value : 'none';
        if ((vidTgl && !vidTgl.checked) || vidVal === 'none' || !vidVal) {
          elVid.textContent = 'Tắt (Không đọc)';
          elVid.title = 'Tắt đọc video/ảnh';
          elVid.classList.add('text-slate-400');
          elVid.classList.remove('text-slate-800', 'dark:text-slate-200');
        } else {
          const prov = _getSelectText(document.getElementById('proc-ai-video-provider'), 'Antigravity');
          const model = _getSelectText(vidModelEl, vidVal);
          const txt = `${prov} · ${model}`;
          elVid.textContent = txt;
          elVid.title = txt;
          elVid.classList.remove('text-slate-400');
          elVid.classList.add('text-slate-800', 'dark:text-slate-200');
        }
      }

      // 5. Giọng đọc TTS
      const elVoice = document.getElementById('step3-config-voice');
      if (elVoice) {
        const ttsTgl = document.getElementById('cfg-toggle-tts');
        if (ttsTgl && !ttsTgl.checked) {
          elVoice.textContent = 'Tắt (Không lồng tiếng)';
          elVoice.title = 'Tắt lồng tiếng TTS';
          elVoice.classList.add('text-slate-400');
          elVoice.classList.remove('text-slate-800', 'dark:text-slate-200');
        } else {
          const engine = _getSelectText(document.getElementById('proc-tts-engine'), 'VieNeu');
          const voice = _getSelectText(document.getElementById('proc-tts-voice'), 'Mặc định');
          const txt = `${engine} · ${voice}`;
          elVoice.textContent = txt;
          elVoice.title = txt;
          elVoice.classList.remove('text-slate-400');
          elVoice.classList.add('text-slate-800', 'dark:text-slate-200');
        }
      }
    }
    window.refreshSharedConfigSummary = refreshSharedConfigSummary;

    document.addEventListener('DOMContentLoaded', function(){
      ['proc-lang', 'proc-target-lang', 'cfg-toggle-trans', 'proc-translation-provider',
       'proc-trans-provider-model', 'cfg-toggle-video-ai', 'proc-ai-video-provider',
       'proc-ai-video-nine-model', 'cfg-toggle-stt', 'proc-transcribe-provider-model',
       'proc-model', 'cfg-toggle-tts', 'proc-tts-engine', 'proc-tts-voice',
       'proc-skip-transcription', 'step3-skip-transcription-step3'].forEach(function(id){
        var el = document.getElementById(id);
        if (el) {
          el.addEventListener('change', refreshSharedConfigSummary);
        }
      });
      setTimeout(refreshSharedConfigSummary, 400);
    });

    // Initialise immediately (all step nodes precede this script in the DOM).
    window.procWizGo(1);
  })();

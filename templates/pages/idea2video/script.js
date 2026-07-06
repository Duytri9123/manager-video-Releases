/**
 * idea2video.js — UI controller cho Idea → Video pipeline (ViMax architecture)
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────────
  let _jobId = null;
  let _pollTimer = null;
  let _lastPct = 0;
  let _lastMsg = '';

  // ── Step keywords để detect bước hiện tại từ message ─────────────────────
  const STEP_KEYWORDS = {
    'i2v-step-story':      ['phát triển câu chuyện', 'develop', 'story', 'câu chuyện'],
    'i2v-step-script':     ['viết kịch bản', 'script', 'kịch bản'],
    'i2v-step-characters': ['nhân vật', 'character', 'trích xuất'],
    'i2v-step-storyboard': ['storyboard', 'thiết kế', 'shot', 'visual'],
    'i2v-step-video':      ['tạo video', 'generate video', 'shot', 'gemini', 'mock'],
    'i2v-step-concat':     ['ghép', 'concat', 'cuối', 'final'],
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  window.addEventListener('DOMContentLoaded', () => {
    i2vLoadConfig();
  });

  // Gọi lại khi switch sang page idea2video
  const _origSwitch = window.switchPage;
  window.switchPage = function (page) {
    if (typeof _origSwitch === 'function') _origSwitch(page);
    if (page === 'idea2video') i2vLoadConfig();
  };

  // ── Load config ────────────────────────────────────────────────────────────
  window.i2vLoadConfig = async function () {
    try {
      const res = await fetch('/api/idea2video/config');
      const data = await res.json();
      if (!data.ok) return;

      const badge = document.getElementById('i2v-backend-badge');
      const info = document.getElementById('i2v-config-info');

      const llmList = (data.llm_providers || []).join(', ') || 'Chưa cấu hình';
      const videoBackend = data.video_backend === 'gemini_veo2'
        ? `✅ Gemini Veo 2 (${data.gemini_model})`
        : '⚠️ Mock (placeholder video)';

      if (badge) {
        badge.textContent = data.has_gemini_key ? '🎬 Gemini Veo 2' : '🔧 Mock';
        badge.className = 'badge ' + (data.has_gemini_key ? 'badge-green' : 'badge-yellow');
      }

      if (info) {
        info.innerHTML = `
          <div class="grid-2" style="gap:8px">
            <div><b>LLM providers:</b><br><span class="text-accent">${llmList}</span></div>
            <div><b>Video backend:</b><br><span>${videoBackend}</span></div>
          </div>
        `;
      }
    } catch (e) {
      console.warn('i2vLoadConfig error:', e);
    }
  };

  // ── Check config ───────────────────────────────────────────────────────────
  window.i2vCheckConfig = async function () {
    await i2vLoadConfig();
    const card = document.getElementById('i2v-config-card');
    if (card) card.classList.remove('collapsed');
    i2vLog('info', '🔍 Đã kiểm tra cấu hình — xem chi tiết bên dưới.');
  };

  // ── Start pipeline ─────────────────────────────────────────────────────────
  window.i2vStart = async function () {
    const idea = (document.getElementById('i2v-idea')?.value || '').trim();
    if (!idea) {
      showToast('Vui lòng nhập ý tưởng!', 'warning');
      document.getElementById('i2v-idea')?.focus();
      return;
    }

    const requirement = (document.getElementById('i2v-requirement')?.value || '').trim();
    const style = document.getElementById('i2v-style')?.value || 'cinematic, high quality';

    // Reset UI
    i2vReset(false);
    i2vSetState('running');
    i2vSetProgress(2, 'Đang gửi yêu cầu...');
    i2vLog('info', `✨ Bắt đầu pipeline với ý tưởng: "${idea.substring(0, 80)}..."`);

    const btn = document.getElementById('btn-i2v-start');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang xử lý...'; }

    try {
      const res = await fetch('/api/idea2video/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idea, user_requirement: requirement, style }),
      });
      const data = await res.json();

      if (!data.ok) {
        i2vSetState('error');
        i2vLog('error', `❌ Lỗi: ${data.error}`);
        showToast(data.error, 'error');
        i2vResetBtn();
        return;
      }

      _jobId = data.job_id;
      i2vLog('success', `✅ Job tạo thành công: ${_jobId}`);
      i2vLog('info', '⏳ Pipeline đang chạy, vui lòng chờ...');
      _startPolling();

    } catch (e) {
      i2vSetState('error');
      i2vLog('error', `❌ Lỗi kết nối: ${e.message}`);
      showToast('Lỗi kết nối server', 'error');
      i2vResetBtn();
    }
  };

  // ── Polling ────────────────────────────────────────────────────────────────
  function _startPolling() {
    _stopPolling();
    _pollTimer = setInterval(_poll, 3000);
    _poll(); // immediate first poll
  }

  function _stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  async function _poll() {
    if (!_jobId) { _stopPolling(); return; }
    try {
      const res = await fetch(`/api/idea2video/status/${_jobId}`);
      const data = await res.json();
      if (!data.ok) return;

      const { state, progress, message, error } = data;

      // Update progress nếu có thay đổi
      if (progress !== _lastPct || message !== _lastMsg) {
        _lastPct = progress;
        _lastMsg = message;
        if (progress >= 0) i2vSetProgress(progress, message);
        if (message && message !== _lastMsg) i2vLog('info', message);
        _updateSteps(message, progress);
      }

      if (state === 'done') {
        _stopPolling();
        i2vSetState('done');
        i2vSetProgress(100, 'Hoàn thành!');
        i2vLog('success', '🎉 Video đã tạo xong!');
        _markAllStepsDone();
        _showResult();
        i2vResetBtn();
      } else if (state === 'error') {
        _stopPolling();
        i2vSetState('error');
        i2vLog('error', `❌ Lỗi: ${error || message}`);
        showToast('Pipeline thất bại: ' + (error || message), 'error');
        i2vResetBtn();
      }
    } catch (e) {
      console.warn('Poll error:', e);
    }
  }

  // ── Show result video ──────────────────────────────────────────────────────
  function _showResult() {
    const card = document.getElementById('i2v-result-card');
    const video = document.getElementById('i2v-result-video');
    if (card) card.style.display = '';
    if (video && _jobId) {
      video.src = `/api/idea2video/download/${_jobId}`;
      video.load();
    }
  }

  // ── Download ───────────────────────────────────────────────────────────────
  window.i2vDownload = function () {
    if (!_jobId) return;
    const a = document.createElement('a');
    a.href = `/api/idea2video/download/${_jobId}`;
    a.download = `idea2video_${_jobId}.mp4`;
    a.click();
  };

  // ── Reset ──────────────────────────────────────────────────────────────────
  window.i2vReset = function (clearInputs = true) {
    _stopPolling();
    _jobId = null;
    _lastPct = 0;
    _lastMsg = '';

    i2vSetState('idle');
    i2vSetProgress(0, 'Nhập ý tưởng và nhấn Tạo Video để bắt đầu.');
    i2vClearLog();
    i2vResetBtn();
    _resetSteps();

    const card = document.getElementById('i2v-result-card');
    if (card) card.style.display = 'none';
    const video = document.getElementById('i2v-result-video');
    if (video) { video.src = ''; }

    if (clearInputs) {
      const idea = document.getElementById('i2v-idea');
      const req = document.getElementById('i2v-requirement');
      if (idea) idea.value = '';
      if (req) req.value = '';
    }
  };

  // ── UI helpers ─────────────────────────────────────────────────────────────
  function i2vSetProgress(pct, msg) {
    const bar = document.getElementById('i2v-progress-bar');
    const pctEl = document.getElementById('i2v-progress-pct');
    const msgEl = document.getElementById('i2v-status-msg');
    if (bar) bar.style.width = Math.max(0, Math.min(100, pct)) + '%';
    if (pctEl) pctEl.textContent = pct + '%';
    if (msgEl) msgEl.textContent = msg || '';
  }

  function i2vSetState(state) {
    const badge = document.getElementById('i2v-state-badge');
    if (!badge) return;
    const map = {
      idle:    ['Chờ',        'badge-gray'],
      running: ['⏳ Đang chạy', 'badge-accent'],
      done:    ['✅ Hoàn thành', 'badge-green'],
      error:   ['❌ Lỗi',       'badge-red'],
    };
    const [text, cls] = map[state] || map.idle;
    badge.textContent = text;
    badge.className = 'badge ' + cls;
  }

  function i2vLog(type, msg) {
    const box = document.getElementById('i2v-log');
    if (!box) return;
    const line = document.createElement('div');
    line.className = `log-${type}`;
    const ts = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    line.textContent = `[${ts}] ${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function i2vClearLog() {
    const box = document.getElementById('i2v-log');
    if (box) box.innerHTML = '';
  }

  function i2vResetBtn() {
    const btn = document.getElementById('btn-i2v-start');
    if (btn) { btn.disabled = false; btn.textContent = '✨ Tạo Video'; }
  }

  // ── Step tracking ──────────────────────────────────────────────────────────
  function _updateSteps(message, pct) {
    if (!message) return;
    const msg = message.toLowerCase();

    // Detect bước hiện tại
    let activeStep = null;
    for (const [stepId, keywords] of Object.entries(STEP_KEYWORDS)) {
      if (keywords.some(kw => msg.includes(kw))) {
        activeStep = stepId;
        break;
      }
    }

    // Dựa vào % để mark các bước trước là done
    const stepOrder = Object.keys(STEP_KEYWORDS);
    const thresholds = [8, 15, 20, 30, 85, 95];

    stepOrder.forEach((stepId, i) => {
      const el = document.getElementById(stepId);
      if (!el) return;
      const statusEl = el.querySelector('.i2v-step-status');

      if (pct >= thresholds[i] && stepId !== activeStep) {
        el.className = 'i2v-step done';
        if (statusEl) { statusEl.textContent = '✅'; statusEl.className = 'i2v-step-status badge badge-green'; }
      } else if (stepId === activeStep) {
        el.className = 'i2v-step active';
        if (statusEl) { statusEl.textContent = '⏳'; statusEl.className = 'i2v-step-status badge badge-accent'; }
      }
    });
  }

  function _markAllStepsDone() {
    Object.keys(STEP_KEYWORDS).forEach(stepId => {
      const el = document.getElementById(stepId);
      if (!el) return;
      el.className = 'i2v-step done';
      const statusEl = el.querySelector('.i2v-step-status');
      if (statusEl) { statusEl.textContent = '✅'; statusEl.className = 'i2v-step-status badge badge-green'; }
    });
  }

  function _resetSteps() {
    Object.keys(STEP_KEYWORDS).forEach(stepId => {
      const el = document.getElementById(stepId);
      if (!el) return;
      el.className = 'i2v-step';
      const statusEl = el.querySelector('.i2v-step-status');
      if (statusEl) { statusEl.textContent = 'Chờ'; statusEl.className = 'i2v-step-status badge badge-gray'; }
    });
  }

  // ── showToast fallback nếu chưa load utils.js ─────────────────────────────
  if (typeof window.showToast !== 'function') {
    window.showToast = function (msg, type) {
      console.log(`[${type}] ${msg}`);
    };
  }

})();

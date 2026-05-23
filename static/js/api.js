/* ── Loading overlay ─────────────────────────────────────────────────────── */
const LoadingUI = (() => {
  let n = 0, t0 = 0, timer = null, watchdog = null;
  const root = () => document.getElementById('global-loading');
  const txt  = () => document.getElementById('gl-text');
  const time = () => document.getElementById('gl-time');
  function tick() { const el = time(); if (el && t0) el.textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's'; }
  // Click-to-dismiss + auto-recover: if the overlay has been stuck for over
  // 90 seconds it's almost certainly a leaked counter from an exception that
  // skipped a finally block. Force-hide so the user can keep using the app.
  function _forceHide() {
    n = 0; t0 = 0;
    clearInterval(timer); timer = null;
    clearTimeout(watchdog); watchdog = null;
    root()?.classList.remove('show');
  }
  // Allow dismissing the overlay by clicking it (user-rescue button).
  document.addEventListener('DOMContentLoaded', () => {
    const r = root();
    if (r) {
      r.title = 'Bấm để đóng nếu bị kẹt';
      r.style.cursor = 'pointer';
      r.addEventListener('click', _forceHide);
    }
  });
  return {
    start(label) {
      n++;
      if (txt()) txt().textContent = label || (typeof t === 'function' ? t('lbl_loading') : 'Đang tải...');
      if (n === 1) {
        t0 = Date.now();
        timer = setInterval(tick, 100);
        clearTimeout(watchdog);
        watchdog = setTimeout(_forceHide, 90_000);
        root()?.classList.add('show');
      }
    },
    stop() {
      n = Math.max(0, n - 1);
      if (n === 0) {
        clearInterval(timer); timer = null;
        clearTimeout(watchdog); watchdog = null;
        t0 = 0;
        root()?.classList.remove('show');
      }
    },
    forceHide: _forceHide,
  };
})();

/* ── API wrapper ─────────────────────────────────────────────────────────── */
const API = {
  async _parseResponse(r) {
    const contentType = (r.headers.get('Content-Type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
      const raw = await r.text();
      const preview = (raw || '').replace(/\s+/g, ' ').trim().slice(0, 180);
      throw new Error(`Server trả về dữ liệu không phải JSON (HTTP ${r.status}). ${preview || 'Vui lòng kiểm tra log backend.'}`);
    }

    let data;
    try {
      data = await r.json();
    } catch (_err) {
      throw new Error(`Không thể đọc JSON từ server (HTTP ${r.status}).`);
    }

    if (!r.ok) {
      const msg = data?.error || data?.message || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return data;
  },
  async get(url, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try {
      const r = await fetch(url);
      return await API._parseResponse(r);
    }
    finally { if (!silent) LoadingUI.stop(); }
  },
  async post(url, data, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      return await API._parseResponse(r);
    } finally { if (!silent) LoadingUI.stop(); }
  },
  async postRaw(url, data, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try {
      return await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    } finally { if (!silent) LoadingUI.stop(); }
  }
};

/* ── Loading overlay ─────────────────────────────────────────────────────── */
const LoadingUI = (() => {
  let n = 0, t0 = 0, timer = null;
  const root = () => document.getElementById('global-loading');
  const txt  = () => document.getElementById('gl-text');
  const time = () => document.getElementById('gl-time');
  function tick() { const el = time(); if (el && t0) el.textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's'; }
  return {
    start(label) {
      n++;
      if (txt()) txt().textContent = label || t('lbl_loading');
      if (n === 1) { t0 = Date.now(); timer = setInterval(tick, 100); root()?.classList.add('show'); }
    },
    stop() {
      n = Math.max(0, n - 1);
      if (n === 0) { clearInterval(timer); timer = null; t0 = 0; root()?.classList.remove('show'); }
    }
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
  async get(url) {
    LoadingUI.start();
    try {
      const r = await fetch(url);
      return await API._parseResponse(r);
    }
    finally { LoadingUI.stop(); }
  },
  async post(url, data) {
    LoadingUI.start();
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      return await API._parseResponse(r);
    } finally { LoadingUI.stop(); }
  },
  async postRaw(url, data) {
    LoadingUI.start();
    try {
      return await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    } finally { LoadingUI.stop(); }
  }
};

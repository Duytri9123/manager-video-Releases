/* ── Utility helpers ─────────────────────────────────────────────────────── */

function toast(msg, type = 'info', dur = 3500) {
  const c = document.getElementById('toasts'); if (!c) return;
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = '<span>' + msg + '</span>';
  c.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0'; el.style.transform = 'translateX(20px)';
    el.style.transition = '.2s'; setTimeout(() => el.remove(), 200);
  }, dur);
}

function appendLog(id, msg, level) {
  const box = document.getElementById(id); if (!box) return;
  const line = document.createElement('div');
  line.className = 'log-' + (level || 'info');
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  line.textContent = `[${ts}] ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function clearLog(id) { const el = document.getElementById(id); if (el) el.innerHTML = ''; }

function setProgress(pbId, lblId, pct, label) {
  const pb = document.getElementById(pbId);
  const lb = document.getElementById(lblId);
  if (pb) pb.style.width = pct + '%';
  if (lb) lb.textContent = label || '';
  const pctEl = document.getElementById(pbId + '-pct');
  if (pctEl) pctEl.textContent = Math.round(pct) + '%';
}

function fmtNum(n) {
  if (!n) return '0';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return '' + n;
}

function fmtDur(ms) {
  if (!ms) return '';
  const s = ms > 1000 ? Math.round(ms / 1000) : ms;
  if (s <= 0) return '';
  const m = Math.floor(s / 60), sec = s % 60;
  return m > 0 ? m + ':' + String(sec).padStart(2, '0') : '0:' + String(sec).padStart(2, '0');
}

function escHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


/* ── Tab Switching Helpers ── */
function switchSubTab(el, tabId, itemClass, pageClass) {
  if (!el || !tabId) return;
  const target = document.getElementById(tabId);
  if (!target) return;
  document.querySelectorAll('.' + itemClass).forEach(m => m.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.' + pageClass).forEach(p => p.classList.remove('active'));
  target.classList.add('active');
}

function switchProcTab(el, id) { switchSubTab(el, id, 'proc-menu-item', 'proc-subpage'); }

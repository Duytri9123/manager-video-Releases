/* ─────────────────────────────────────────────────────────────────────────
 * Proxy & Router page — UI logic.
 * Uses the shared API helper from api.js. All DOM updates go through
 * textContent / safe builders to avoid XSS from proxy labels / user input.
 * ───────────────────────────────────────────────────────────────────────── */

// ── helpers ─────────────────────────────────────────────────────────────────
function _el(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const k in attrs) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'onclick') e.addEventListener('click', attrs[k]);
      else if (k === 'dataset') Object.assign(e.dataset, attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}

function _badge(label, type) { return _el('span', { class: 'badge badge-' + (type || 'gray') }, label); }

function _proxyToast(msg, kind) { (window.toast || console.log)(msg, kind || 'info'); }

// ── Proxies ─────────────────────────────────────────────────────────────────
async function proxyLoadList() {
  try {
    const r = await API.get('/api/proxies/list');
    const tbody = document.querySelector('#proxy-list tbody');
    if (!tbody) return;
    tbody.replaceChildren();
    if (!r.items || !r.items.length) {
      tbody.appendChild(_el('tr', null, _el('td', { colspan: 7, class: 'empty-state' }, 'Chưa có proxy.')));
      return;
    }
    for (const p of r.items) {
      const status = !p.active ? _badge('Tắt', 'gray')
        : (p.fail_streak >= 3 ? _badge('Lỗi', 'red')
          : (p.last_ok ? _badge('OK', 'green') : _badge('Chưa test', 'yellow')));
      const tr = _el('tr', null,
        _el('td', null, p.label || ''),
        _el('td', { class: 'break-all' }, p.url),
        _el('td', null, p.country || ''),
        _el('td', null, status),
        _el('td', null, p.last_latency_ms ? p.last_latency_ms + ' ms' : '—'),
        _el('td', null, p.last_ip || '—'),
        _el('td', null,
          _el('button', { class: 'btn btn-secondary btn-sm', onclick: () => proxyTest(p.id) }, 'Test'),
          ' ',
          _el('button', { class: 'btn btn-secondary btn-sm', onclick: () => proxyToggleActive(p) }, p.active ? 'Tắt' : 'Bật'),
          ' ',
          _el('button', { class: 'btn btn-danger btn-sm', onclick: () => proxyDelete(p.id) }, '🗑'),
        ),
      );
      tbody.appendChild(tr);
    }
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

function proxyShowAdd() { document.getElementById('proxy-add-form')?.classList.remove('hidden'); }
function proxyHideAdd() { document.getElementById('proxy-add-form')?.classList.add('hidden'); }
function proxyShowImport() { document.getElementById('proxy-bulk-form')?.classList.remove('hidden'); }
function proxyHideImport() { document.getElementById('proxy-bulk-form')?.classList.add('hidden'); }

async function proxyAdd() {
  const url = document.getElementById('px-url').value.trim();
  if (!url) return _proxyToast('Thiếu URL proxy.', 'warning');
  const tags = document.getElementById('px-tags').value.split(',').map(s => s.trim()).filter(Boolean);
  try {
    await API.post('/api/proxies/add', {
      url,
      label: document.getElementById('px-label').value.trim(),
      country: document.getElementById('px-country').value.trim(),
      tags,
    });
    document.getElementById('px-url').value = '';
    document.getElementById('px-label').value = '';
    document.getElementById('px-country').value = '';
    document.getElementById('px-tags').value = '';
    proxyHideAdd();
    proxyLoadList();
    _proxyToast('Đã thêm proxy.', 'success');
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function proxyBulkImport() {
  const text = document.getElementById('px-bulk-text').value;
  const scheme = document.getElementById('px-bulk-scheme').value;
  if (!text.trim()) return _proxyToast('Trống.', 'warning');
  try {
    const r = await API.post('/api/proxies/bulk_import', { text, default_scheme: scheme });
    document.getElementById('px-bulk-text').value = '';
    proxyHideImport();
    proxyLoadList();
    _proxyToast('Đã thêm ' + r.added + ' proxy.', 'success');
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function proxyTest(id) {
  try {
    const r = await API.post('/api/proxies/test', { id });
    if (r.ok) _proxyToast('Proxy OK — IP ' + (r.ip || '?') + ' (' + (r.latency_ms || 0) + ' ms)', 'success');
    else _proxyToast('Proxy lỗi: ' + (r.error || 'unknown'), 'error');
    proxyLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function proxyTestAll() {
  try {
    LoadingUI.start('Đang test toàn bộ proxy...');
    const r = await API.post('/api/proxies/test_all', {});
    const ok = (r.results || []).filter(x => x.ok).length;
    _proxyToast(`Test xong: ${ok}/${(r.results || []).length} OK.`, 'info');
    proxyLoadList();
  } finally { LoadingUI.stop(); }
}

async function proxyToggleActive(p) {
  try {
    await API.post('/api/proxies/update', { id: p.id, active: !p.active });
    proxyLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function proxyDelete(id) {
  if (!confirm('Xoá proxy này?')) return;
  try {
    await API.post('/api/proxies/delete', { id });
    proxyLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

// ── Routers ─────────────────────────────────────────────────────────────────
async function routerLoadList() {
  try {
    const r = await API.get('/api/routers/list');
    const tbody = document.querySelector('#router-list tbody');
    if (!tbody) return;
    tbody.replaceChildren();
    if (!r.items || !r.items.length) {
      tbody.appendChild(_el('tr', null, _el('td', { colspan: 6, class: 'empty-state' }, 'Chưa có router.')));
      return;
    }
    for (const it of r.items) {
      const status = !it.active ? _badge('Tắt', 'gray')
        : (it.last_status === 'ok' ? _badge('OK', 'green')
          : (it.last_status?.startsWith('err') ? _badge('Lỗi', 'red') : _badge('Chưa rotate', 'yellow')));
      const tr = _el('tr', null,
        _el('td', null, it.label || it.id),
        _el('td', null, it.type || ''),
        _el('td', { class: 'break-all' }, it.endpoint || ''),
        _el('td', null, status),
        _el('td', null, it.last_ip || '—'),
        _el('td', null,
          _el('button', { class: 'btn btn-primary btn-sm', onclick: () => routerRotate(it.id) }, '🔄 Rotate'),
          ' ',
          _el('button', { class: 'btn btn-secondary btn-sm', onclick: () => routerToggleActive(it) }, it.active ? 'Tắt' : 'Bật'),
          ' ',
          _el('button', { class: 'btn btn-danger btn-sm', onclick: () => routerDelete(it.id) }, '🗑'),
        ),
      );
      tbody.appendChild(tr);
    }
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

function routerShowAdd() { document.getElementById('router-add-form')?.classList.remove('hidden'); }
function routerHideAdd() { document.getElementById('router-add-form')?.classList.add('hidden'); }

async function routerShowPresets() {
  const wrap = document.getElementById('router-presets-wrap');
  const list = document.getElementById('router-presets-list');
  if (!wrap || !list) return;
  wrap.classList.remove('hidden');
  list.replaceChildren();
  try {
    const r = await API.get('/api/routers/presets');
    for (const p of (r.items || [])) {
      const item = _el('div', { class: 'check-item', onclick: () => routerApplyPreset(p) },
        _el('span', null, p.label));
      list.appendChild(item);
    }
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

function routerApplyPreset(p) {
  document.getElementById('rt-label').value = p.label || '';
  document.getElementById('rt-type').value = p.type || 'generic_http';
  document.getElementById('rt-endpoint').value = p.endpoint || '';
  document.getElementById('rt-method').value = p.method || 'POST';
  document.getElementById('rt-headers').value = JSON.stringify(p.headers || {}, null, 2);
  document.getElementById('rt-body').value = p.body || '';
  document.getElementById('rt-success').value = p.success_check || '';
  document.getElementById('router-presets-wrap').classList.add('hidden');
  routerShowAdd();
}

async function routerAdd() {
  let headers = {};
  try { headers = JSON.parse(document.getElementById('rt-headers').value || '{}'); }
  catch (_) { return _proxyToast('Headers không phải JSON hợp lệ.', 'error'); }
  const data = {
    label: document.getElementById('rt-label').value.trim(),
    type: document.getElementById('rt-type').value,
    endpoint: document.getElementById('rt-endpoint').value.trim(),
    method: document.getElementById('rt-method').value,
    headers,
    body: document.getElementById('rt-body').value,
    cooldown_sec: parseInt(document.getElementById('rt-cooldown').value || '30', 10),
    verify_url: document.getElementById('rt-verify').value.trim(),
    success_check: document.getElementById('rt-success').value.trim(),
  };
  if (!data.endpoint) return _proxyToast('Thiếu endpoint.', 'warning');
  try {
    await API.post('/api/routers/add', data);
    routerHideAdd();
    routerLoadList();
    _proxyToast('Đã thêm router.', 'success');
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function routerRotate(id) {
  try {
    LoadingUI.start('Đang xoay IP...');
    const r = await API.post('/api/routers/rotate', { id });
    if (r.ok) _proxyToast('OK — IP mới: ' + (r.new_ip || 'không xác định'), 'success');
    else _proxyToast('Rotate thất bại: ' + (r.message || 'unknown'), 'error');
    routerLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
  finally { LoadingUI.stop(); }
}

async function routerToggleActive(r) {
  try {
    await API.post('/api/routers/update', { id: r.id, active: !r.active });
    routerLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function routerDelete(id) {
  if (!confirm('Xoá router này?')) return;
  try {
    await API.post('/api/routers/delete', { id });
    routerLoadList();
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

// ── Init when page becomes visible ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Reload lists when user switches to the proxies tab
  const sidebarItems = document.querySelectorAll('[data-page="proxies"]');
  sidebarItems.forEach(el => el.addEventListener('click', () => {
    setTimeout(() => { proxyLoadList(); routerLoadList(); }, 80);
  }));
});

// expose
Object.assign(window, {
  proxyLoadList, proxyShowAdd, proxyHideAdd, proxyShowImport, proxyHideImport,
  proxyAdd, proxyBulkImport, proxyTest, proxyTestAll, proxyToggleActive, proxyDelete,
  routerLoadList, routerShowAdd, routerHideAdd, routerShowPresets, routerApplyPreset,
  routerAdd, routerRotate, routerToggleActive, routerDelete,
});

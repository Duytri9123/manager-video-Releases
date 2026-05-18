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
    const summary = document.getElementById('router-summary');
    if (!tbody) return;
    tbody.replaceChildren();
    const items = r.items || [];
    if (summary) {
      const ok = items.filter(it => it.last_status === 'ok').length;
      const err = items.filter(it => it.last_status?.startsWith('err')).length;
      const off = items.filter(it => !it.active).length;
      summary.className = 'badge ' + (items.length === 0 ? 'badge-gray'
        : err > 0 ? 'badge-yellow' : 'badge-green');
      summary.style.marginRight = '8px';
      summary.textContent = `${items.length} router · ${ok} OK · ${err} lỗi${off ? ' · ' + off + ' tắt' : ''}`;
    }
    if (!items.length) {
      tbody.appendChild(_el('tr', null, _el('td', { colspan: 6, class: 'empty-state' }, 'Chưa có router.')));
      return;
    }
    for (const it of items) {
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
          _el('button', { class: 'btn btn-secondary btn-sm', onclick: () => routerTestOne(it.id) }, '⚡ Test'),
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
function routerShowBulk() {
  const wrap = document.getElementById('router-bulk-form');
  if (!wrap) return;
  wrap.classList.remove('hidden');
  _routerBulkLoadPresets();
}
function routerHideBulk() { document.getElementById('router-bulk-form')?.classList.add('hidden'); }

async function _routerBulkLoadPresets() {
  const sel = document.getElementById('rt-bulk-preset');
  if (!sel || sel._loaded) return;
  try {
    const r = await API.get('/api/routers/presets');
    sel.replaceChildren();
    for (const p of (r.items || [])) {
      sel.appendChild(_el('option', { value: p.id }, p.label || p.id));
    }
    sel._loaded = true;
  } catch (_) {}
}

function routerBulkSampleNine() {
  const ta = document.getElementById('rt-bulk-hosts');
  if (!ta) return;
  // 9 routers on the typical Huawei HiLink subnet
  ta.value = Array.from({ length: 9 }, (_, i) => `192.168.${8 + i}.1`).join('\n');
}

async function routerBulkAdd() {
  const presetId = document.getElementById('rt-bulk-preset').value;
  const hostsText = document.getElementById('rt-bulk-hosts').value || '';
  const labelPrefix = document.getElementById('rt-bulk-prefix').value.trim() || 'Router';
  const cooldown = parseInt(document.getElementById('rt-bulk-cooldown').value || '30', 10);
  const verifyUrl = document.getElementById('rt-bulk-verify').value.trim() || 'https://ifconfig.me/ip';
  const hosts = hostsText.split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#'));
  if (!hosts.length) return _proxyToast('Cần ít nhất 1 host.', 'warning');
  if (!presetId) return _proxyToast('Chưa chọn preset.', 'warning');
  try {
    LoadingUI.start('Đang tạo ' + hosts.length + ' router...');
    const r = await API.post('/api/routers/bulk_add', {
      preset_id: presetId, hosts, label_prefix: labelPrefix,
      cooldown_sec: cooldown, verify_url: verifyUrl,
    });
    if (r.errors && r.errors.length) {
      _proxyToast(`Tạo ${r.created} router; ${r.errors.length} lỗi.`, 'warning');
    } else {
      _proxyToast(`Đã tạo ${r.created} router.`, 'success');
    }
    routerHideBulk();
    routerLoadList();
  } catch (e) {
    _proxyToast(String(e.message || e), 'error');
  } finally { LoadingUI.stop(); }
}

async function routerTestOne(id) {
  try {
    const r = await API.post('/api/routers/test', { id });
    if (r.reachable) _proxyToast('✓ ' + (r.message || 'Reachable'), 'success');
    else _proxyToast('✗ ' + (r.message || 'Unreachable'), 'error');
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function routerTestAll() {
  try {
    const list = await API.get('/api/routers/list');
    const items = (list.items || []).filter(it => it.active);
    if (!items.length) return _proxyToast('Không có router đang bật.', 'warning');
    _routerLogReset(`⚡ Test ${items.length} router...`);
    let ok = 0;
    for (const it of items) {
      try {
        const r = await API.post('/api/routers/test', { id: it.id });
        if (r.reachable) { ok++; _routerLog(`✓ ${it.label || it.id} — ${r.message || 'OK'}`); }
        else _routerLog(`✗ ${it.label || it.id} — ${r.message || 'unreachable'}`, 'error');
      } catch (e) { _routerLog(`✗ ${it.label || it.id} — ${e.message || e}`, 'error'); }
    }
    _routerLog(`Hoàn tất: ${ok}/${items.length} reachable.`);
    _proxyToast(`Test xong: ${ok}/${items.length} reachable.`, 'info');
  } catch (e) { _proxyToast(String(e.message || e), 'error'); }
}

async function routerRotateAll() {
  const list = await API.get('/api/routers/list');
  const items = (list.items || []).filter(it => it.active);
  if (!items.length) return _proxyToast('Không có router đang bật.', 'warning');
  if (!confirm(`Xoay IP cho ${items.length} router (cách nhau 1s)?`)) return;
  _routerLogReset(`🔄 Bắt đầu rotate ${items.length} router...`);
  try {
    LoadingUI.start('Đang xoay IP toàn bộ...');
    const r = await API.post('/api/routers/rotate_all', { delay_sec: 1.0 });
    for (const res of (r.results || [])) {
      if (res.ok) _routerLog(`✓ ${res.label || res.id} → ${res.new_ip || 'IP mới ?'}`);
      else _routerLog(`✗ ${res.label || res.id} — ${res.message || 'lỗi'}`, 'error');
    }
    _routerLog(`Hoàn tất: ${r.ok_count}/${r.total} OK.`);
    _proxyToast(`Rotate xong: ${r.ok_count}/${r.total} OK.`, r.ok_count === r.total ? 'success' : 'warning');
    routerLoadList();
  } catch (e) {
    _proxyToast(String(e.message || e), 'error');
  } finally { LoadingUI.stop(); }
}

function _routerLogReset(headline) {
  const log = document.getElementById('router-rotate-log');
  if (!log) return;
  log.classList.remove('hidden');
  log.replaceChildren(_el('div', null, headline));
}
function _routerLog(line, kind) {
  const log = document.getElementById('router-rotate-log');
  if (!log) return;
  const colour = kind === 'error' ? '#ef4444' : 'inherit';
  log.appendChild(_el('div', { style: 'color:' + colour }, line));
  log.scrollTop = log.scrollHeight;
}

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
  routerShowBulk, routerHideBulk, routerBulkAdd, routerBulkSampleNine,
  routerTestOne, routerTestAll, routerRotateAll,
});

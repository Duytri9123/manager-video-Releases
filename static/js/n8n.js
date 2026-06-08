/* ── n8n orchestration: drag-and-drop flow builder ──────────────────────────
 * A self-contained, vanilla-JS node editor (n8n-style canvas):
 *   • drag node types from the palette onto the canvas
 *   • move nodes, connect output→input ports with bezier wires
 *   • edit node properties in the inspector
 *   • save/load the graph to the backend, and run it sequentially
 * ------------------------------------------------------------------------- */

/* ── Node type catalog ──
 * Each def: { title, ic, trigger?, fields[], endpoint?, method?,
 *   payload(c)->body using RESOLVED config c, out(respJson)->primary value }
 * Data flows node→node: a node's output JSON is passed to the next node as
 * `input`; string fields support {{input}}, {{input.field}}, {{json.field}}.
 */
const N8N_NODE_DEFS = {
  'trigger.manual':   { title: 'Bắt đầu thủ công', ic: '⚡', trigger: true, fields: [] },
  'trigger.schedule': { title: 'Lịch (Cron)', ic: '⏰', trigger: true,
    fields: [{ k: 'cron', label: 'Biểu thức Cron', ph: '0 9 * * *', def: '0 9 * * *' }] },
  'trigger.webhook':  { title: 'Webhook', ic: '🪝', trigger: true,
    fields: [{ k: 'path', label: 'Đường dẫn', ph: '/webhook/abc-123' }] },

  'tv.user_info':   { title: 'Thông tin user', ic: '🔍', endpoint: '/api/user_info', method: 'POST',
    fields: [{ k: 'url', label: 'URL người dùng', ph: 'https://www.douyin.com/user/...' }],
    payload: c => ({ url: c.url || '' }) },
  'tv.user_videos': { title: 'Lấy video user', ic: '🎞', endpoint: '/api/user_videos_page', method: 'POST',
    fields: [{ k: 'url', label: 'URL người dùng' }, { k: 'page', label: 'Trang', type: 'number', def: '1' }],
    payload: c => ({ url: c.url || '', page: parseInt(c.page || 1, 10) }) },
  'tv.queue_add':   { title: 'Thêm hàng chờ', ic: '➕', endpoint: '/api/queue/add', method: 'POST',
    fields: [{ k: 'items', label: 'Items JSON (mảng)', type: 'textarea', def: '[]' }],
    payload: c => _n8nParseJson(c.items, []) },
  'tv.process':     { title: 'Xử lý video', ic: '🎬', endpoint: '/api/process_video', method: 'POST',
    fields: [{ k: 'payload', label: 'Payload JSON', type: 'textarea', def: '{}' }],
    payload: c => _n8nParseJson(c.payload, {}) },
  'tv.publish':     { title: 'Đăng video', ic: '📤',
    fields: [{ k: 'platform', label: 'Nền tảng', type: 'select', opts: ['youtube', 'tiktok', 'facebook'] }],
    note: 'Cấu hình tài khoản ở tab "Đăng video".' },

  /* ── AI / giọng nói (dùng 9Router/AI đã kết nối) ── */
  'ai.chat': { title: 'AI Chat (LLM)', ic: '🤖', endpoint: '/api/chatbot/chat', method: 'POST', ai: true,
    fields: [{ k: 'model', label: 'Model (trống = mặc định)', ph: 'kr/claude-sonnet-4.5' },
             { k: 'system', label: 'System prompt', type: 'textarea' },
             { k: 'prompt', label: 'Prompt', type: 'textarea', def: 'Viết kịch bản ngắn về {{input}}' }],
    payload: c => {
      const msgs = [];
      if (c.system) msgs.push({ role: 'system', content: c.system });
      msgs.push({ role: 'user', content: c.prompt || '' });
      const b = { messages: msgs };
      if (c.model) b.model = c.model;
      return b;
    },
    out: r => r.content },
  'ai.translate': { title: 'Dịch (AI)', ic: '🌍', endpoint: '/api/translate', method: 'POST', ai: true,
    fields: [{ k: 'text', label: 'Văn bản', type: 'textarea', def: '{{input.content}}' },
             { k: 'provider', label: 'Provider', type: 'select', opts: ['auto', '9router', 'deepseek', 'openai', 'google'] }],
    payload: c => ({ text: c.text || '', provider: c.provider || 'auto' }),
    out: r => r.result },
  'ai.tts': { title: 'Đọc văn bản (TTS)', ic: '🔊', endpoint: '/api/chatbot/tts?json=1', method: 'POST', ai: true,
    fields: [{ k: 'input', label: 'Văn bản', type: 'textarea', def: '{{input.content}}' },
             { k: 'model', label: 'Model TTS', ph: 'openai/tts-1', def: 'openai/tts-1' },
             { k: 'voice', label: 'Giọng (OpenAI)', ph: 'alloy' }],
    payload: c => ({ input: c.input || '', model: c.model || 'openai/tts-1', voice: c.voice || '' }),
    out: r => (r.ok ? `audio ${r.format || 'mp3'} (${Math.round((r.audio_base64 || '').length * 0.75 / 1024)}KB)` : '') },
  'ai.tts_file': { title: 'TTS → File MP3', ic: '💾', endpoint: '/api/tts_to_mp3', method: 'POST', ai: true,
    fields: [{ k: 'text', label: 'Văn bản', type: 'textarea', def: '{{input.content}}' },
             { k: 'tts_engine', label: 'Engine', type: 'select', opts: ['edge-tts', 'fpt-ai', 'elevenlabs', '9router', 'gtts'] },
             { k: 'tts_voice', label: 'Giọng', ph: 'vi-VN-HoaiMyNeural', def: 'vi-VN-HoaiMyNeural' }],
    payload: c => ({ text: c.text || '', tts_engine: c.tts_engine || 'edge-tts', tts_voice: c.tts_voice || 'vi-VN-HoaiMyNeural' }),
    note: 'Trả file MP3 (lưu trên server). Không trả JSON — chỉ xem status.' },
  'ai.stt': { title: 'Giọng nói → Text (STT)', ic: '🎤', endpoint: '/api/chatbot/stt', method: 'POST', ai: true,
    fields: [{ k: 'model', label: 'Model STT', ph: 'openai/whisper-1', def: 'openai/whisper-1' },
             { k: 'audio_url', label: 'URL audio (nếu có)', ph: 'https://...' }],
    payload: c => ({ model: c.model || 'openai/whisper-1' }),
    note: 'Node này cần file audio upload hoặc URL. Pipeline dùng output từ node TTS nếu có.',
    out: r => (r.text || r.content || '') },

  /* ── Logic ── */
  'logic.if': { title: 'IF (Rẽ nhánh)', ic: '🔀', logic: true,
    fields: [{ k: 'condition', label: 'Điều kiện (JS expression)', ph: 'input.ok === true', def: 'input.ok === true' }],
    note: 'Nhánh TRUE chạy tất cả node nối bên phải. Nếu FALSE thì dừng tại đây.' },
  'logic.loop': { title: 'Lặp (Loop)', ic: '🔁', logic: true,
    fields: [{ k: 'array', label: 'Mảng lặp', type: 'textarea', def: '{{input.items}}' },
             { k: 'limit', label: 'Giới hạn', type: 'number', def: '10' }],
    note: 'Chạy nhánh bên phải cho mỗi phần tử (truyền vào {{input}}).' },

  'action.n8n':  { title: 'Trigger n8n', ic: '🔗',
    fields: [{ k: 'webhook_url', label: 'Webhook URL' },
             { k: 'method', label: 'Method', type: 'select', opts: ['POST', 'GET'] },
             { k: 'payload', label: 'Payload JSON', type: 'textarea', def: '{}' }] },
  'action.http': { title: 'HTTP Request', ic: '🌐',
    fields: [{ k: 'method', label: 'Method', type: 'select', opts: ['GET', 'POST', 'PUT', 'DELETE'] },
             { k: 'url', label: 'URL', ph: 'https://...' },
             { k: 'payload', label: 'Payload JSON', type: 'textarea' }] },
  'util.notify': { title: 'Thông báo', ic: '🔔',
    fields: [{ k: 'message', label: 'Tin nhắn', type: 'textarea', def: '{{input}}' }] },
};

/* ── State ── */
let n8nFlow = { nodes: [], connections: [] };
let n8nSel = null;
let n8nZoomLevel = 1;
let _n8nIdSeq = 1;
let _n8nDrag = null;     // node move: {id, dx, dy}
let _n8nConn = null;     // wire draw: {from, x1, y1}
let _n8nPan = null;      // canvas pan: {sx, sy, sl, st}
let _n8nCanvasReady = false;

function _n8nParseJson(str, fallback) {
  try { const v = JSON.parse(str); return v == null ? fallback : v; }
  catch (e) { return fallback; }
}
function _n8nEsc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function n8nLog(msg, cls) {
  const box = document.getElementById('n8n-log');
  if (!box) return;
  const ts = new Date().toLocaleTimeString();
  const line = document.createElement('div');
  line.className = 'n8n-log-line ' + (cls ? 'log-' + cls : '');
  line.textContent = `[${ts}] ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

/* ── Init ── */
async function n8nInit() {
  if (!_n8nCanvasReady) { n8nSetupCanvas(); _n8nCanvasReady = true; }
  await n8nLoadConfig();
  n8nLoadEndpoints();
  await n8nFlowLoad();
}

/* ── Canvas setup: palette drag-drop + global pointer handlers ── */
function n8nSetupCanvas() {
  const wrap = document.getElementById('n8n-canvas-wrap');
  const canvas = document.getElementById('n8n-canvas');

  // Palette → drag start + click-to-add
  document.querySelectorAll('#n8n-palette .n8n-pal-item').forEach(it => {
    it.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/n8n-type', it.dataset.type);
      e.dataTransfer.effectAllowed = 'copy';
    });
    it.addEventListener('dblclick', () => {
      const r = wrap.getBoundingClientRect();
      const p = _n8nClientToCanvas(r.left + r.width / 2, r.top + r.height / 2);
      n8nAddNode(it.dataset.type, p.x - 85, p.y - 30);
    });
  });

  // Canvas accept drop
  wrap.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  wrap.addEventListener('drop', e => {
    e.preventDefault();
    const type = e.dataTransfer.getData('text/n8n-type');
    if (!type || !N8N_NODE_DEFS[type]) return;
    const p = _n8nClientToCanvas(e.clientX, e.clientY);
    n8nAddNode(type, p.x - 85, p.y - 25);
  });

  // Click/drag empty canvas → deselect + pan
  wrap.addEventListener('mousedown', e => {
    if (e.target === wrap || e.target === canvas || e.target.id === 'n8n-wires') {
      n8nSelect(null);
      _n8nPan = { sx: e.clientX, sy: e.clientY, sl: wrap.scrollLeft, st: wrap.scrollTop };
      wrap.style.cursor = 'grabbing';
      e.preventDefault();
    }
  });

  // Global move/up for node-drag and wire-draw
  document.addEventListener('mousemove', _n8nOnMouseMove);
  document.addEventListener('mouseup', _n8nOnMouseUp);

  // Wheel to zoom (toward cursor); Shift+wheel / no-modifier both zoom here.
  wrap.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    n8nSetZoom(n8nZoomLevel + delta, e.clientX, e.clientY);
  }, { passive: false });

  // Delete key removes selected node (only when the n8n tab is active and
  // focus isn't in an input/textarea).
  document.addEventListener('keydown', e => {
    if (!n8nSel) return;
    const pg = document.getElementById('page-n8n');
    if (!pg || !pg.classList.contains('active')) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); n8nDeleteSelected(); }
  });
}

function _n8nClientToCanvas(clientX, clientY) {
  const wrap = document.getElementById('n8n-canvas-wrap');
  const r = wrap.getBoundingClientRect();
  return {
    x: (clientX - r.left + wrap.scrollLeft) / n8nZoomLevel,
    y: (clientY - r.top + wrap.scrollTop) / n8nZoomLevel,
  };
}

/* ── Node CRUD ── */
function n8nAddNode(type, x, y) {
  const def = N8N_NODE_DEFS[type];
  const node = {
    id: 'n' + (_n8nIdSeq++),
    type,
    x: Math.max(0, Math.round(x)),
    y: Math.max(0, Math.round(y)),
    config: {},
  };
  (def.fields || []).forEach(f => { if (f.def != null) node.config[f.k] = f.def; });
  n8nFlow.nodes.push(node);
  n8nRenderNode(node);
  n8nDrawWires();
  n8nSelect(node.id);
  _n8nUpdateHint();
}

function n8nGetNode(id) { return n8nFlow.nodes.find(n => n.id === id); }

function n8nRenderNodes() {
  const canvas = document.getElementById('n8n-canvas');
  canvas.querySelectorAll('.n8n-node').forEach(el => el.remove());
  n8nFlow.nodes.forEach(n => n8nRenderNode(n));
}

function n8nNodeSubtitle(node) {
  const c = node.config || {};
  return c.url || c.webhook_url || c.url || c.cron || c.path || c.platform || c.message || node.type;
}

function n8nRenderNode(node) {
  const def = N8N_NODE_DEFS[node.type] || { title: node.type, ic: '▫️' };
  const canvas = document.getElementById('n8n-canvas');
  let el = document.getElementById('node-' + node.id);
  if (!el) {
    el = document.createElement('div');
    el.id = 'node-' + node.id;
    el.className = 'n8n-node' + (def.trigger ? ' trigger' : '') + (def.ai ? ' n8n-node-ai' : '') + (def.logic ? ' logic' : '');
    el.innerHTML = `
      <div class="n8n-node-head">
        <div class="n8n-node-ic">${def.ic}</div>
        <div style="min-width:0"><div class="n8n-node-title">${_n8nEsc(def.title)}</div></div>
      </div>
      <div class="n8n-node-sub"></div>
      <div class="n8n-port in" data-port="in"></div>
      <div class="n8n-port out" data-port="out"></div>`;
    canvas.appendChild(el);

    // Move (drag body)
    el.addEventListener('mousedown', e => {
      if (e.target.classList.contains('n8n-port')) return;
      const p = _n8nClientToCanvas(e.clientX, e.clientY);
      _n8nDrag = { id: node.id, dx: p.x - node.x, dy: p.y - node.y };
      n8nSelect(node.id);
      e.preventDefault();
    });
    // Connection start (out port)
    el.querySelector('.n8n-port.out').addEventListener('mousedown', e => {
      e.stopPropagation();
      const pos = n8nPortPos(node.id, 'out');
      _n8nConn = { from: node.id, x1: pos.x, y1: pos.y };
      e.preventDefault();
    });
    // Connection end (in port)
    el.querySelector('.n8n-port.in').addEventListener('mouseup', e => {
      if (_n8nConn && _n8nConn.from !== node.id) {
        n8nConnect(_n8nConn.from, node.id);
      }
      _n8nConn = null;
      e.stopPropagation();
    });
  }
  el.style.left = node.x + 'px';
  el.style.top = node.y + 'px';
  el.querySelector('.n8n-node-sub').textContent = n8nNodeSubtitle(node);
  el.classList.toggle('selected', n8nSel === node.id);
}

function n8nConnect(fromId, toId) {
  if (n8nFlow.connections.some(c => c.from === fromId && c.to === toId)) return;
  n8nFlow.connections.push({ from: fromId, to: toId });
  n8nDrawWires();
}

function n8nDeleteSelected() {
  if (!n8nSel) return;
  const id = n8nSel;
  n8nFlow.nodes = n8nFlow.nodes.filter(n => n.id !== id);
  n8nFlow.connections = n8nFlow.connections.filter(c => c.from !== id && c.to !== id);
  const el = document.getElementById('node-' + id);
  if (el) el.remove();
  n8nSelect(null);
  n8nDrawWires();
  _n8nUpdateHint();
}

/* ── Pointer handlers ── */
function _n8nOnMouseMove(e) {
  if (_n8nPan) {
    const wrap = document.getElementById('n8n-canvas-wrap');
    wrap.scrollLeft = _n8nPan.sl - (e.clientX - _n8nPan.sx);
    wrap.scrollTop = _n8nPan.st - (e.clientY - _n8nPan.sy);
    return;
  }
  if (_n8nDrag) {
    const node = n8nGetNode(_n8nDrag.id);
    if (!node) return;
    const p = _n8nClientToCanvas(e.clientX, e.clientY);
    node.x = Math.max(0, Math.round(p.x - _n8nDrag.dx));
    node.y = Math.max(0, Math.round(p.y - _n8nDrag.dy));
    const el = document.getElementById('node-' + node.id);
    if (el) { el.style.left = node.x + 'px'; el.style.top = node.y + 'px'; }
    n8nDrawWires();
  } else if (_n8nConn) {
    const p = _n8nClientToCanvas(e.clientX, e.clientY);
    n8nDrawWires({ x1: _n8nConn.x1, y1: _n8nConn.y1, x2: p.x, y2: p.y });
  }
}
function _n8nOnMouseUp() {
  _n8nDrag = null;
  if (_n8nPan) {
    _n8nPan = null;
    const wrap = document.getElementById('n8n-canvas-wrap');
    if (wrap) wrap.style.cursor = '';
  }
  if (_n8nConn) { _n8nConn = null; n8nDrawWires(); }
}

/* ── Ports & wires ── */
function n8nPortPos(nodeId, port) {
  const node = n8nGetNode(nodeId);
  const el = document.getElementById('node-' + nodeId);
  const h = el ? el.offsetHeight : 64;
  const w = el ? el.offsetWidth : 170;
  return { x: node.x + (port === 'out' ? w : 0), y: node.y + h / 2 };
}

function n8nDrawWires(temp) {
  const svg = document.getElementById('n8n-wires');
  if (!svg) return;
  let paths = '';
  n8nFlow.connections.forEach((c, i) => {
    const a = n8nPortPos(c.from, 'out');
    const b = n8nPortPos(c.to, 'in');
    const d = _n8nBezier(a.x, a.y, b.x, b.y);
    paths += `<path class="n8n-wire-hit" d="${d}" data-ci="${i}"></path>`;
    paths += `<path class="n8n-wire" d="${d}"></path>`;
  });
  if (temp) {
    paths += `<path class="n8n-wire tmp" d="${_n8nBezier(temp.x1, temp.y1, temp.x2, temp.y2)}"></path>`;
  }
  svg.innerHTML = paths;
  svg.querySelectorAll('.n8n-wire-hit').forEach(p => {
    p.addEventListener('click', () => {
      const ci = parseInt(p.dataset.ci, 10);
      n8nFlow.connections.splice(ci, 1);
      n8nDrawWires();
    });
  });
}
function _n8nBezier(x1, y1, x2, y2) {
  const dx = Math.max(40, Math.abs(x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function _n8nUpdateHint() {
  const hint = document.getElementById('n8n-empty-hint');
  if (hint) hint.style.display = n8nFlow.nodes.length ? 'none' : 'flex';
}

/* ── Selection & inspector ── */
function n8nSelect(id) {
  n8nSel = id;
  document.querySelectorAll('.n8n-node').forEach(el => el.classList.remove('selected'));
  const insp = document.getElementById('n8n-inspector');
  if (!id) { insp.classList.remove('open'); return; }
  const el = document.getElementById('node-' + id);
  if (el) el.classList.add('selected');
  const node = n8nGetNode(id);
  const def = N8N_NODE_DEFS[node.type];
  insp.classList.add('open');
  const body = document.getElementById('n8n-inspector-body');
  let html = `<div class="field"><label>Loại</label><input type="text" value="${_n8nEsc(def.title)}" readonly></div>`;
  (def.fields || []).forEach(f => {
    const val = node.config[f.k] != null ? node.config[f.k] : '';
    html += `<div class="field"><label>${_n8nEsc(f.label)}</label>`;
    if (f.type === 'textarea') {
      html += `<textarea data-k="${f.k}" rows="4" placeholder="${_n8nEsc(f.ph || '')}">${_n8nEsc(val)}</textarea>`;
    } else if (f.type === 'select') {
      html += `<select data-k="${f.k}">${f.opts.map(o => `<option value="${o}"${o === val ? ' selected' : ''}>${o}</option>`).join('')}</select>`;
    } else {
      html += `<input type="${f.type || 'text'}" data-k="${f.k}" value="${_n8nEsc(val)}" placeholder="${_n8nEsc(f.ph || '')}">`;
    }
    html += `</div>`;
  });
  if (def.note) html += `<div class="alert-info text-xs">${_n8nEsc(def.note)}</div>`;
  if (def.endpoint) html += `<div class="text-xs text-muted">Gọi: <code>${def.method} ${def.endpoint}</code></div>`;
  html += `<div class="text-xs text-muted mt-8">💡 Dùng dữ liệu node trước: <code>{{input}}</code>, <code>{{input.content}}</code>, hoặc theo tên node: <code>{{AI Chat (LLM).content}}</code></div>`;
  body.innerHTML = html;
  body.querySelectorAll('[data-k]').forEach(inp => {
    inp.addEventListener('input', () => {
      node.config[inp.dataset.k] = inp.value;
      n8nRenderNode(node);
    });
  });
  // Show output if available
  const outPanel = document.getElementById('n8n-inspector-output');
  const outPre = document.getElementById('n8n-inspector-output-pre');
  if (window._n8nCtxById && window._n8nCtxById[id] !== undefined) {
    outPanel.classList.remove('hidden');
    const val = window._n8nCtxById[id];
    outPre.textContent = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val);
  } else {
    outPanel.classList.add('hidden');
    outPre.textContent = '';
  }
}
function n8nCloseInspector() { n8nSelect(null); }

/* ── Zoom / fit / clear ── */
function n8nSetZoom(newZoom, pivotClientX, pivotClientY) {
  const wrap = document.getElementById('n8n-canvas-wrap');
  const canvas = document.getElementById('n8n-canvas');
  const old = n8nZoomLevel;
  newZoom = Math.min(2, Math.max(0.3, +newZoom.toFixed(2)));
  if (newZoom === old) return;

  const r = wrap.getBoundingClientRect();
  // Default pivot = viewport center
  const px = (pivotClientX != null ? pivotClientX : r.left + r.width / 2) - r.left;
  const py = (pivotClientY != null ? pivotClientY : r.top + r.height / 2) - r.top;
  // Canvas-space point currently under the pivot
  const cx = (wrap.scrollLeft + px) / old;
  const cy = (wrap.scrollTop + py) / old;

  n8nZoomLevel = newZoom;
  canvas.style.transform = `scale(${newZoom})`;
  document.getElementById('n8n-zoom-label').textContent = Math.round(newZoom * 100) + '%';
  // Keep that canvas point under the pivot after scaling
  wrap.scrollLeft = cx * newZoom - px;
  wrap.scrollTop = cy * newZoom - py;
}
function n8nZoom(delta) { n8nSetZoom(n8nZoomLevel + delta); }
function n8nFlowFit() {
  const wrap = document.getElementById('n8n-canvas-wrap');
  n8nZoomLevel = 1;
  document.getElementById('n8n-canvas').style.transform = 'scale(1)';
  document.getElementById('n8n-zoom-label').textContent = '100%';
  if (n8nFlow.nodes.length) {
    const minX = Math.min(...n8nFlow.nodes.map(n => n.x));
    const minY = Math.min(...n8nFlow.nodes.map(n => n.y));
    wrap.scrollLeft = Math.max(0, minX - 40);
    wrap.scrollTop = Math.max(0, minY - 40);
  } else {
    wrap.scrollLeft = 0; wrap.scrollTop = 0;
  }
}
function n8nFlowClear() {
  if (n8nFlow.nodes.length && !confirm('Xóa toàn bộ node trên canvas?')) return;
  n8nFlow = { nodes: [], connections: [] };
  n8nRenderNodes();
  n8nDrawWires();
  n8nSelect(null);
  _n8nUpdateHint();
}

/* ── Save / load flow ── */
async function n8nFlowSave() {
  try {
    const res = await fetch('/api/n8n/flow', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        nodes: n8nFlow.nodes,
        connections: n8nFlow.connections,
        meta: { name: document.getElementById('n8n-wf-name').value, zoom: n8nZoomLevel },
      }),
    });
    const data = await res.json();
    if (data.ok) toast('💾 Đã lưu workflow (' + data.node_count + ' node)', 'success');
    else toast('❌ Lưu thất bại', 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
}

async function n8nFlowLoad() {
  try {
    const res = await fetch('/api/n8n/flow');
    const data = await res.json();
    if (!data.ok) return;
    const f = data.flow || {};
    n8nFlow = { nodes: f.nodes || [], connections: f.connections || [] };
    // bump id sequence past loaded ids
    n8nFlow.nodes.forEach(n => {
      const num = parseInt(String(n.id).replace(/^n/, ''), 10);
      if (!isNaN(num) && num >= _n8nIdSeq) _n8nIdSeq = num + 1;
      if (!n.config) n.config = {};
    });
    if (f.meta && f.meta.name) document.getElementById('n8n-wf-name').value = f.meta.name;
    n8nRenderNodes();
    n8nDrawWires();
    _n8nUpdateHint();
  } catch (e) { console.error('n8nFlowLoad', e); }
}

/* ── Run executor (sequential graph walk with data passing) ── */
function _n8nGetPath(obj, path) {
  if (!path) return obj;
  return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function _n8nStr(v) {
  if (v == null) return '';
  return typeof v === 'object' ? JSON.stringify(v) : String(v);
}
/* Resolve {{input}}, {{input.field}}, {{json.field}}, {{NodeTitle.field}} */
function _n8nResolveStr(str, prev, ctxByTitle) {
  if (typeof str !== 'string' || str.indexOf('{{') < 0) return str;
  return str.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (m, expr) => {
    expr = expr.trim();
    if (expr === 'input' || expr === 'json') return _n8nStr(prev);
    let mm = expr.match(/^(input|json)\.(.+)$/);
    if (mm) return _n8nStr(_n8nGetPath(prev, mm[2]));
    mm = expr.match(/^([^.]+)\.(.+)$/);
    if (mm && ctxByTitle[mm[1]] !== undefined) return _n8nStr(_n8nGetPath(ctxByTitle[mm[1]], mm[2]));
    if (ctxByTitle[expr] !== undefined) return _n8nStr(ctxByTitle[expr]);
    return m;
  });
}
function _n8nResolveConfig(node, prev, ctxByTitle) {
  const out = {};
  Object.keys(node.config || {}).forEach(k => {
    out[k] = _n8nResolveStr(node.config[k], prev, ctxByTitle);
  });
  return out;
}
function n8nNodeStatus(id, state) {
  const el = document.getElementById('node-' + id);
  if (el) { el.classList.remove('run-running', 'run-ok', 'run-err'); if (state) el.classList.add('run-' + state); }
}

async function n8nFlowRun() {
  const btn = document.getElementById('btn-n8n-run');
  if (btn) btn.disabled = true;
  document.getElementById('n8n-log').innerHTML = '';
  n8nFlow.nodes.forEach(n => n8nNodeStatus(n.id, null));
  n8nLog('▶ Bắt đầu chạy workflow…', 'banner');
  try {
    const hasIncoming = new Set(n8nFlow.connections.map(c => c.to));
    let starts = n8nFlow.nodes.filter(n => (N8N_NODE_DEFS[n.type] || {}).trigger);
    if (!starts.length) starts = n8nFlow.nodes.filter(n => !hasIncoming.has(n.id));
    if (!starts.length && n8nFlow.nodes.length) starts = [n8nFlow.nodes[0]];

    const ctxById = {};
    const ctxByTitle = {};
    window._n8nCtxById = ctxById;
    const visited = new Set();
    const queue = starts.map(n => ({ node: n, prev: null }));
    while (queue.length) {
      const { node, prev } = queue.shift();
      if (!node || visited.has(node.id)) continue;
      visited.add(node.id);
      const out = await n8nExecNode(node, prev, ctxByTitle);
      ctxById[node.id] = out;
      const def = N8N_NODE_DEFS[node.type] || {};
      ctxByTitle[def.title || node.type] = out;

      // IF logic: only propagate if condition truthy
      if (node.type === 'logic.if') {
        if (out && out._pass) {
          n8nFlow.connections.filter(c => c.from === node.id).forEach(c => {
            const t = n8nGetNode(c.to); if (t && !visited.has(t.id)) queue.push({ node: t, prev: out.value });
          });
        } else {
          n8nLog('   ↳ IF FALSE — nhánh dừng.', 'warning');
        }
        continue;
      }
      // Loop logic
      if (node.type === 'logic.loop') {
        const items = out._items || [];
        const children = n8nFlow.connections.filter(c => c.from === node.id).map(c => n8nGetNode(c.to)).filter(Boolean);
        for (let i = 0; i < items.length; i++) {
          n8nLog(`   🔁 Lặp [${i + 1}/${items.length}]`, 'detail');
          for (const child of children) {
            await _n8nRunSubtree(child, items[i], ctxByTitle, new Set(visited));
          }
        }
        // Mark children as visited to avoid double run
        children.forEach(ch => visited.add(ch.id));
        continue;
      }
      n8nFlow.connections.filter(c => c.from === node.id).forEach(c => {
        const t = n8nGetNode(c.to); if (t && !visited.has(t.id)) queue.push({ node: t, prev: out });
      });
    }
    n8nLog('✓ Hoàn tất.', 'success');
  } catch (e) {
    n8nLog('✗ Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _n8nRunSubtree(node, prev, ctxByTitle, visited) {
  if (!node || visited.has(node.id)) return;
  visited.add(node.id);
  const out = await n8nExecNode(node, prev, ctxByTitle);
  const def = N8N_NODE_DEFS[node.type] || {};
  ctxByTitle[def.title || node.type] = out;
  const children = n8nFlow.connections.filter(c => c.from === node.id).map(c => n8nGetNode(c.to)).filter(Boolean);
  for (const ch of children) {
    await _n8nRunSubtree(ch, out, ctxByTitle, visited);
  }
}

async function n8nExecNode(node, prev, ctxByTitle) {
  const def = N8N_NODE_DEFS[node.type] || {};
  const label = def.title || node.type;
  const c = _n8nResolveConfig(node, prev, ctxByTitle);
  n8nNodeStatus(node.id, 'running');
  try {
    if (def.trigger) {
      n8nLog(`⚡ ${label}` + (node.type === 'trigger.schedule' ? ` (cron: ${c.cron || '-'})` : ''), 'url');
      n8nNodeStatus(node.id, 'ok');
      return { trigger: node.type };
    }
    if (node.type === 'util.notify') {
      n8nLog('🔔 ' + (c.message || ''), 'result');
      n8nNodeStatus(node.id, 'ok');
      return { message: c.message };
    }
    if (node.type === 'logic.if') {
      const expr = c.condition || 'false';
      let result = false;
      try { result = !!(new Function('input', 'json', `return (${expr})`))(prev, prev); }
      catch (e) { n8nLog(`   ⚠ Lỗi eval IF: ${e.message}`, 'warning'); }
      n8nLog(`🔀 IF: "${expr}" → ${result ? 'TRUE ✓' : 'FALSE ✗'}`, result ? 'success' : 'warning');
      n8nNodeStatus(node.id, result ? 'ok' : 'err');
      return { _pass: result, value: prev, condition: expr };
    }
    if (node.type === 'logic.loop') {
      let items = [];
      try {
        const raw = c.array || '[]';
        items = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (!Array.isArray(items)) items = [items];
      } catch (e) { items = []; }
      const limit = Math.min(parseInt(c.limit || 10, 10) || 10, 100);
      items = items.slice(0, limit);
      n8nLog(`🔁 Loop: ${items.length} phần tử (giới hạn ${limit})`, 'url');
      n8nNodeStatus(node.id, 'ok');
      return { _items: items };
    }
    if (node.type === 'action.n8n') {
      n8nLog(`🔗 Trigger n8n → ${c.webhook_url || '(chưa nhập URL)'}`, 'detail');
      const r = await fetch('/api/n8n/trigger', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ webhook_url: c.webhook_url, method: c.method || 'POST', payload: c.payload }),
      });
      const data = await r.json();
      _n8nLogResp(label, data); n8nNodeStatus(node.id, data.ok ? 'ok' : 'err');
      return data.response_json != null ? data.response_json : data;
    }
    if (node.type === 'action.http') {
      n8nLog(`🌐 HTTP ${c.method || 'POST'} ${c.url || ''}`, 'detail');
      const r = await fetch('/api/n8n/proxy', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: c.url, method: c.method, payload: c.payload }),
      });
      const data = await r.json();
      _n8nLogResp(label, data); n8nNodeStatus(node.id, data.ok ? 'ok' : 'err');
      return data.response_json != null ? data.response_json : data;
    }
    if (def.endpoint) {
      const body = def.payload ? def.payload(c) : {};
      n8nLog(`→ ${label}: ${def.method} ${def.endpoint}`, 'detail');
      const r = await fetch(def.endpoint, {
        method: def.method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      let data = null; try { data = await r.json(); } catch (e) {}
      const okFlag = r.ok && (!data || data.ok !== false);
      const primary = (def.out && data) ? def.out(data) : null;
      n8nLog(`   ↳ HTTP ${r.status}${primary ? ' · ' + String(primary).slice(0, 120) : ''}${data && data.error ? ' · ' + data.error : ''}`, okFlag ? 'success' : 'error');
      n8nNodeStatus(node.id, okFlag ? 'ok' : 'err');
      return data != null ? data : { status: r.status };
    }
    n8nLog(`ℹ ${label}: chỉ cấu hình, không thực thi.`, 'detail');
    n8nNodeStatus(node.id, 'ok');
    return { config: c };
  } catch (e) {
    n8nLog(`✗ ${label}: ${e.message}`, 'error');
    n8nNodeStatus(node.id, 'err');
    return { error: e.message };
  }
}
function _n8nLogResp(label, data) {
  if (data && data.ok) n8nLog(`   ↳ ${label} OK (HTTP ${data.status || 200})`, 'success');
  else n8nLog(`   ↳ ${label} lỗi: ${(data && (data.message || data.error)) || 'unknown'}`, 'error');
}

/* ── Connection settings panel ── */
function n8nToggleConn() {
  const card = document.getElementById('n8n-conn-card');
  if (card) { card.classList.remove('collapsed'); card.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
}
function n8nSetStatus(state, text) {
  const el = document.getElementById('n8n-status');
  if (!el) return;
  const dot = { ok: 'dot-green', err: 'dot-red', wait: 'dot-yellow', idle: 'dot-gray' }[state] || 'dot-gray';
  el.innerHTML = `<span class="dot ${dot}"></span><span>${text}</span>`;
}
function n8nTogglePw() {
  const inp = document.getElementById('n8n-api-key');
  if (inp) inp.type = inp.type === 'password' ? 'text' : 'password';
}

async function n8nLoadConfig() {
  try {
    const res = await fetch('/api/n8n/config');
    const data = await res.json();
    if (!data.ok) return;
    const c = data.config || {};
    document.getElementById('n8n-enabled').checked = !!c.enabled;
    document.getElementById('n8n-base-url').value = c.base_url || '';
    document.getElementById('n8n-timeout').value = c.timeout_sec || 30;
    const keyInput = document.getElementById('n8n-api-key');
    keyInput.value = '';
    keyInput.placeholder = c.api_key ? '•••••••• (đã lưu)' : '';
    document.getElementById('n8n-api-key-env').classList.toggle('hidden', !c.api_key_from_env);
  } catch (e) { console.error('n8nLoadConfig', e); }
}

async function n8nSaveConfig() {
  const btn = document.getElementById('btn-n8n-save');
  if (btn) btn.disabled = true;
  try {
    const body = {
      enabled: document.getElementById('n8n-enabled').checked,
      base_url: document.getElementById('n8n-base-url').value.trim(),
      timeout_sec: parseInt(document.getElementById('n8n-timeout').value, 10) || 30,
    };
    const apiKey = document.getElementById('n8n-api-key').value.trim();
    if (apiKey) body.api_key = apiKey;
    const res = await fetch('/api/n8n/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) { toast('✅ Đã lưu cấu hình n8n', 'success'); n8nLoadConfig(); }
    else toast('❌ Lưu thất bại', 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  finally { if (btn) btn.disabled = false; }
}

async function n8nTest() {
  n8nSetStatus('wait', 'Đang kiểm tra...');
  try {
    await n8nSaveConfig();
    const res = await fetch('/api/n8n/test', { method: 'POST' });
    const data = await res.json();
    if (data.ok) { n8nSetStatus('ok', 'Đã kết nối'); toast('✅ ' + (data.message || 'n8n OK'), 'success'); }
    else { n8nSetStatus('err', 'Không kết nối được'); toast('❌ ' + (data.message || 'Lỗi kết nối'), 'error'); }
  } catch (e) { n8nSetStatus('err', 'Lỗi'); toast('❌ ' + e.message, 'error'); }
}

async function n8nLoadEndpoints() {
  try {
    const res = await fetch('/api/n8n/endpoints');
    const data = await res.json();
    if (!data.ok) return;
    document.getElementById('n8n-public-base').value = data.public_base_url || '';
    document.getElementById('n8n-endpoints-note').textContent = data.note || '';
    const tbody = document.getElementById('n8n-endpoints-body');
    tbody.innerHTML = (data.endpoints || []).map(e => `
      <tr><td><span class="badge badge-accent">${_n8nEsc(e.method)}</span></td>
      <td class="break-all" style="white-space:normal"><code>${_n8nEsc(e.path)}</code></td></tr>`).join('');
  } catch (e) { console.error('n8nLoadEndpoints', e); }
}

/* ── Cron Schedule ── */
async function n8nShowSchedule() {
  let data = {};
  try { const r = await fetch('/api/n8n/schedule'); data = await r.json(); } catch (e) {}
  const enabled = data.enabled || false;
  const cron = data.cron || '';
  const html = `<div style="position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;padding:16px" id="n8n-sched-modal">
    <div style="background:#fff;border-radius:12px;max-width:420px;width:100%;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.3)">
      <div style="font-weight:700;font-size:15px;margin-bottom:12px">⏰ Lịch chạy tự động (Cron)</div>
      <div class="alert-info text-xs mb-12">Workflow sẽ được chạy trên server theo biểu thức cron. Format: <code>phút giờ ngày tháng thứ</code>.<br>Ví dụ: <code>0 9 * * *</code> = mỗi ngày 9:00.</div>
      <label class="toggle-wrap mb-12">
        <input type="checkbox" class="toggle-input" id="n8n-sched-enabled" ${enabled ? 'checked' : ''}>
        <div class="toggle"></div><span class="toggle-label">Bật lịch tự động</span>
      </label>
      <div class="field"><label>Biểu thức Cron</label>
        <input type="text" id="n8n-sched-cron" value="${cron}" placeholder="0 9 * * *"></div>
      <div class="btn-group mt-12">
        <button class="btn btn-primary" onclick="n8nSaveSchedule()">💾 Lưu</button>
        <button class="btn btn-secondary" onclick="document.getElementById('n8n-sched-modal')?.remove()">Đóng</button>
      </div>
    </div></div>`;
  const existing = document.getElementById('n8n-sched-modal');
  if (existing) existing.remove();
  document.body.insertAdjacentHTML('beforeend', html);
}

async function n8nSaveSchedule() {
  const enabled = document.getElementById('n8n-sched-enabled')?.checked || false;
  const cron = document.getElementById('n8n-sched-cron')?.value?.trim() || '';
  try {
    const r = await fetch('/api/n8n/schedule', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, cron }),
    });
    const data = await r.json();
    if (data.ok) { toast('⏰ Đã lưu lịch' + (enabled ? ` (${cron})` : ' (tắt)'), 'success'); n8nScheduleBadge(); }
    else toast('❌ ' + (data.message || 'Lỗi'), 'error');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  document.getElementById('n8n-sched-modal')?.remove();
}

/* ── Schedule status badge on the toolbar ── */
async function n8nScheduleBadge() {
  const badge = document.getElementById('n8n-cron-badge');
  if (!badge) return;
  try {
    const r = await fetch('/api/n8n/schedule');
    const d = await r.json();
    if (d.enabled && d.cron) {
      badge.className = 'badge badge-green text-xs';
      badge.textContent = `⏰ ${d.cron}`;
      badge.classList.remove('hidden');
    } else {
      badge.className = 'badge badge-gray text-xs hidden';
      badge.textContent = '⏰ Tắt';
    }
  } catch (e) {}
}

// Refresh schedule badge whenever the tab initializes
(function () {
  const origInit = n8nInit;
  n8nInit = async function () {
    await origInit();
    n8nScheduleBadge();
  };
})();

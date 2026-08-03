function _ovClamp(v, min, max) {
    v = parseFloat(v);
    if (!Number.isFinite(v)) v = min;
    return Math.max(min, Math.min(max, v));
  }
  function _ovHexValue(v, fallback) {
    v = String(v || '').trim();
    return /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
  }
  function _ovRgba(hex, opacity) {
    const h = String(hex || '#000000').replace('#', '');
    const r = parseInt(h.slice(0, 2), 16) || 0;
    const g = parseInt(h.slice(2, 4), 16) || 0;
    const b = parseInt(h.slice(4, 6), 16) || 0;
    return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, opacity))})`;
  }
  function _ovEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
    })[ch]);
  }
  function _ovRoundPct(v) {
    return Math.round(_ovClamp(v, 0, 1) * 1000) / 10;
  }
  function _ovSecValue(v) {
    if (v === '' || v === null || v === undefined) return '';
    v = parseFloat(v);
    return Number.isFinite(v) ? Math.max(0, v) : '';
  }
  window._ovLayerCounter = window._ovLayerCounter || 0;
  function _ovNewId() {
    window._ovLayerCounter += 1;
    return 'ov-' + Date.now().toString(36) + '-' + window._ovLayerCounter;
  }
  function _ovDefault(type) {
    if (type === 'text') {
      return {
        id: _ovNewId(), type: 'text', enabled: true, open: true,
        text: 'Text mới', x_pct: 0.50, y_pct: 0.18, size_pct: 0.05,
        weight: 700, padding_pct: 0.55,
        color: '#ffffff', box_color: '#000000', box_opacity: 0.50,
        start_sec: '', end_sec: ''
      };
    }
    if (type === 'image') {
      return {
        id: _ovNewId(), type: 'image', enabled: true, open: true,
        path: '', name: 'Chưa chọn ảnh',
        x_pct: 0.50, y_pct: 0.50, width_pct: 0.20, height_pct: 0.20,
        opacity: 1.0, start_sec: '', end_sec: ''
      };
    }
    return {
      id: _ovNewId(), type: 'rect', enabled: true, open: true,
      x_pct: 0.50, y_pct: 0.38, width_pct: 1.00, height_pct: 0.07,
      color: '#000000', opacity: 0.55, radius_pct: 0.02,
      start_sec: '', end_sec: ''
    };
  }
  function _ovNormalizeLayer(raw) {
    raw = raw || {};
    const type = raw.type === 'text' ? 'text' : (raw.type === 'image' ? 'image' : 'rect');
    const base = _ovDefault(type);
    base.id = raw.id || _ovNewId();
    base.enabled = raw.enabled !== false;
    base.open = raw.open === true;
    base.x_pct = _ovClamp(raw.x_pct ?? base.x_pct, 0, 1);
    base.y_pct = _ovClamp(raw.y_pct ?? base.y_pct, 0, 1);
    base.start_sec = _ovSecValue(raw.start_sec);
    base.end_sec = _ovSecValue(raw.end_sec);
    if (type === 'text') {
      base.text = String(raw.text ?? base.text);
      base.size_pct = _ovClamp(raw.size_pct ?? base.size_pct, 0.01, 0.30);
      base.weight = Math.max(300, Math.min(900, parseInt(raw.weight ?? base.weight, 10) || base.weight));
      base.padding_pct = _ovClamp(raw.padding_pct ?? base.padding_pct, 0, 1.5);
      base.color = _ovHexValue(raw.color, base.color);
      base.box_color = _ovHexValue(raw.box_color, base.box_color);
      base.box_opacity = _ovClamp(raw.box_opacity ?? base.box_opacity, 0, 1);
    } else if (type === 'image') {
      base.path = String(raw.path ?? base.path);
      base.name = String(raw.name ?? base.name);
      base.width_pct = _ovClamp(raw.width_pct ?? base.width_pct, 0.01, 1);
      base.height_pct = _ovClamp(raw.height_pct ?? base.height_pct, 0.01, 1);
      base.opacity = _ovClamp(raw.opacity ?? base.opacity, 0, 1);
    } else {
      base.width_pct = _ovClamp(raw.width_pct ?? base.width_pct, 0.01, 1);
      base.height_pct = _ovClamp(raw.height_pct ?? base.height_pct, 0.01, 1);
      base.color = _ovHexValue(raw.color, base.color);
      base.opacity = _ovClamp(raw.opacity ?? base.opacity, 0, 1);
      base.radius_pct = _ovClamp(raw.radius_pct ?? base.radius_pct, 0, 0.5);
    }
    return base;
  }
  function _ovFind(id) {
    return (window._videoOverlays || []).find(x => String(x.id) === String(id));
  }
  function _ovSyncHidden() {
    const hidden = document.getElementById('ov-layers-json');
    if (hidden) hidden.value = JSON.stringify(window._videoOverlays || []);
  }
  function _ovLoadFromHidden() {
    const hidden = document.getElementById('ov-layers-json');
    if (!hidden || !hidden.value) return;
    try {
      const parsed = JSON.parse(hidden.value);
      if (Array.isArray(parsed)) window._videoOverlays = parsed.map(_ovNormalizeLayer);
    } catch (_) {}
    _ovSyncHidden();
  }
  function _ovTimeLabel(ov) {
    const s = _ovSecValue(ov.start_sec);
    const e = _ovSecValue(ov.end_sec);
    if (s === '' && e === '') return 'cả video';
    return (s === '' ? 'đầu' : s + 's') + ' → ' + (e === '' ? 'cuối' : e + 's');
  }
  function _ovVisibleAtPreviewTime(ov) {
    const ts = parseFloat(document.getElementById('sub-preview-ts')?.value || 0) || 0;
    const s = _ovSecValue(ov.start_sec);
    const e = _ovSecValue(ov.end_sec);
    if (s !== '' && ts < s) return false;
    if (e !== '' && ts > e) return false;
    return true;
  }
  function _ovSummary(ov) {
    if (ov.type === 'text') {
      return (ov.text || 'Text').slice(0, 32);
    }
    if (ov.type === 'image') {
      return '🖼️ ' + (ov.name || 'Ảnh');
    }
    return 'Khối ' + _ovRoundPct(ov.width_pct) + '% × ' + _ovRoundPct(ov.height_pct) + '%';
  }
  function _ovWeightOptions(value) {
    const current = parseInt(value || 700, 10);
    return [
      [300, 'Mảnh'],
      [400, 'Thường'],
      [500, 'Vừa'],
      [600, 'Đậm nhẹ'],
      [700, 'Đậm'],
      [800, 'Rất đậm'],
      [900, 'Siêu đậm']
    ].map(([v, label]) => `<option value="${v}" ${current === v ? 'selected' : ''}>${label}</option>`).join('');
  }
  function _ovLayerBody(ov) {
    const id = _ovEsc(ov.id);
    const common = `
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:8px">
        <div class="field"><label>X %</label><input type="number" value="${_ovRoundPct(ov.x_pct)}" min="0" max="100" step="1" oninput="ovUpdateLayer('${id}','x_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        <div class="field"><label>Y %</label><input type="number" value="${_ovRoundPct(ov.y_pct)}" min="0" max="100" step="1" oninput="ovUpdateLayer('${id}','y_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        <div class="field"><label>Từ (s)</label><input type="number" value="${_ovEsc(ov.start_sec)}" min="0" step="0.5" placeholder="đầu" oninput="ovUpdateLayer('${id}','start_sec',this.value,true)" onchange="ovRenderLayerList()"></div>
        <div class="field"><label>Đến (s)</label><input type="number" value="${_ovEsc(ov.end_sec)}" min="0" step="0.5" placeholder="cuối" oninput="ovUpdateLayer('${id}','end_sec',this.value,true)" onchange="ovRenderLayerList()"></div>
      </div>`;
    if (ov.type === 'text') {
      return `
        <input type="text" value="${_ovEsc(ov.text)}" placeholder="Nhập text..."
          style="width:100%;font-size:12px;height:38px;box-sizing:border-box;margin-bottom:8px"
          oninput="ovUpdateLayer('${id}','text',this.value,true)" onchange="ovRenderLayerList()">
        ${common}
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:8px">
          <div class="field"><label>Cỡ %</label><input type="number" value="${_ovRoundPct(ov.size_pct)}" min="1" max="30" step="0.5" oninput="ovUpdateLayer('${id}','size_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
          <div class="field"><label>Độ đậm</label><select style="height:38px" oninput="ovUpdateLayer('${id}','weight',parseInt(this.value,10),true)" onchange="ovRenderLayerList()">${_ovWeightOptions(ov.weight)}</select></div>
          <div class="field"><label>Lề text %</label><input type="number" value="${Math.round((ov.padding_pct ?? 0.55) * 100)}" min="0" max="150" step="5" oninput="ovUpdateLayer('${id}','padding_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
          <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">
            <div class="field">
              <label>Màu chữ</label>
              <div style="display:flex;gap:4px;align-items:center">
                <input type="text" value="${_ovEsc(ov.color || '#ffffff')}" style="flex:1;height:38px;padding:4px 8px;font-size:11px;min-width:0;box-sizing:border-box" oninput="ovUpdateLayer('${id}','color',this.value,true); this.nextElementSibling.value = this.value" onchange="ovRenderLayerList()">
                <input type="color" value="${_ovEsc(ov.color || '#ffffff')}" style="width:28px;height:38px;padding:0;border:none;cursor:pointer;flex-shrink:0" oninput="ovUpdateLayer('${id}','color',this.value,true); this.previousElementSibling.value = this.value" onchange="ovRenderLayerList()">
              </div>
            </div>
            <div class="field">
              <label>Màu nền</label>
              <div style="display:flex;gap:4px;align-items:center">
                <input type="text" value="${_ovEsc(ov.box_color || '#000000')}" style="flex:1;height:38px;padding:4px 8px;font-size:11px;min-width:0;box-sizing:border-box" oninput="ovUpdateLayer('${id}','box_color',this.value,true); this.nextElementSibling.value = this.value" onchange="ovRenderLayerList()">
                <input type="color" value="${_ovEsc(ov.box_color || '#000000')}" style="width:28px;height:38px;padding:0;border:none;cursor:pointer;flex-shrink:0" oninput="ovUpdateLayer('${id}','box_color',this.value,true); this.previousElementSibling.value = this.value" onchange="ovRenderLayerList()">
              </div>
            </div>
          </div>
        </div>
        <div class="field"><label>Nền text ${Math.round((ov.box_opacity || 0) * 100)}%</label><input type="range" min="0" max="100" step="5" value="${Math.round((ov.box_opacity || 0) * 100)}" style="width:100%" oninput="ovUpdateLayer('${id}','box_opacity',this.value/100,true)" onchange="ovRenderLayerList()"></div>`;
    }
    if (ov.type === 'image') {
      const filename = ov.name || 'Ảnh';
      return `
        <div style="margin-bottom:8px">
          <label style="font-size:11px;color:var(--text-muted,#8a8a93);margin-bottom:4px;display:block">Tệp hình ảnh</label>
          <div style="display:flex;gap:4px;height:38px">
            <input type="text" value="${_ovEsc(filename)}" readonly style="flex:1;font-size:11px;height:38px;box-sizing:border-box;padding:0 10px;border:1px solid var(--border,#dcdce2);border-radius:4px;background:var(--bg3,#f3f4f6)">
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 10px;height:38px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;gap:4px" onclick="document.getElementById('ov-change-image-file').dataset.ovId = '${id}'; document.getElementById('ov-change-image-file').click()">📂 Đổi</button>
          </div>
        </div>
        ${common}
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:8px">
          <div class="field"><label>Rộng %</label><input type="number" value="${_ovRoundPct(ov.width_pct)}" min="1" max="100" step="1" oninput="ovUpdateLayer('${id}','width_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
          <div class="field"><label>Cao %</label><input type="number" value="${_ovRoundPct(ov.height_pct)}" min="1" max="100" step="1" oninput="ovUpdateLayer('${id}','height_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        </div>
        <div class="field"><label>Độ đậm ${Math.round((ov.opacity || 0) * 100)}%</label><input type="range" min="0" max="100" step="5" value="${Math.round((ov.opacity || 0) * 100)}" style="width:100%" oninput="ovUpdateLayer('${id}','opacity',this.value/100,true)" onchange="ovRenderLayerList()"></div>`;
    }
    return `
      ${common}
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:8px">
        <div class="field"><label>Rộng %</label><input type="number" value="${_ovRoundPct(ov.width_pct)}" min="1" max="100" step="1" oninput="ovUpdateLayer('${id}','width_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        <div class="field"><label>Cao %</label><input type="number" value="${_ovRoundPct(ov.height_pct)}" min="1" max="100" step="1" oninput="ovUpdateLayer('${id}','height_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        <div class="field"><label>Bo góc %</label><input type="number" value="${_ovRoundPct(ov.radius_pct)}" min="0" max="50" step="1" oninput="ovUpdateLayer('${id}','radius_pct',this.value/100,true)" onchange="ovRenderLayerList()"></div>
        <div class="field">
          <label>Màu khối</label>
          <div style="display:flex;gap:4px;align-items:center">
            <input type="text" value="${_ovEsc(ov.color || '#000000')}" style="flex:1;height:38px;padding:4px 8px;font-size:11px;min-width:0;box-sizing:border-box" oninput="ovUpdateLayer('${id}','color',this.value,true); this.nextElementSibling.value = this.value" onchange="ovRenderLayerList()">
            <input type="color" value="${_ovEsc(ov.color || '#000000')}" style="width:28px;height:38px;padding:0;border:none;cursor:pointer;flex-shrink:0" oninput="ovUpdateLayer('${id}','color',this.value,true); this.previousElementSibling.value = this.value" onchange="ovRenderLayerList()">
          </div>
        </div>
      </div>
      <div class="field"><label>Độ đậm ${Math.round((ov.opacity || 0) * 100)}%</label><input type="range" min="0" max="100" step="5" value="${Math.round((ov.opacity || 0) * 100)}" style="width:100%" oninput="ovUpdateLayer('${id}','opacity',this.value/100,true)" onchange="ovRenderLayerList()"></div>`;
  }
  function ovRenderLayerList() {
    const list = document.getElementById('ov-layer-list');
    if (!list) return;
    const layers = window._videoOverlays || [];
    if (!layers.length) {
      list.innerHTML = '<div class="empty-state text-xs">Chưa có text/khối nào. Bấm + Text hoặc ▭ Khối để thêm.</div>';
      _ovSyncHidden();
      if (window.pe2RenderRanges) window.pe2RenderRanges();
      return;
    }
    const sel = window._pe2Sel;
    list.innerHTML = layers.map(ov => {
      const selected = sel && sel.type === 'overlay' && String(sel.id) === String(ov.id);
      return `
        <div class="ov-layer-card type-${ov.type} ${ov.open ? 'open' : ''} ${selected ? 'pe2-selected' : ''}" data-ov-id="${_ovEsc(ov.id)}">
          <div class="ov-layer-head" onclick="ovToggleLayer('${_ovEsc(ov.id)}')">
            <span style="font-size:9px;width:12px;display:inline-flex;align-items:center;justify-content:center;color:#7d8cab;margin-right:2px">
              ${ov.open ? '▼' : '▶'}
            </span>
            <span style="min-width:0;flex:1">
              <span class="ov-layer-name">${_ovEsc(_ovSummary(ov))}</span><br>
              <span class="ov-layer-meta">${_ovEsc(_ovTimeLabel(ov))} · X ${_ovRoundPct(ov.x_pct)}% · Y ${_ovRoundPct(ov.y_pct)}%</span>
            </span>
            <span class="ov-layer-actions" onclick="event.stopPropagation()">
              <label class="pe2-switch" title="${ov.enabled ? 'Ẩn' : 'Hiện'}" onclick="event.stopPropagation();">
                <input type="checkbox" ${ov.enabled ? 'checked' : ''} onchange="ovUpdateLayer('${_ovEsc(ov.id)}','enabled',this.checked)">
                <span class="pe2-slider"></span>
              </label>
              <button type="button" style="border:none;background:transparent;padding:4px 6px;cursor:pointer;font-size:16px;color:#ef4444;line-height:1;vertical-align:middle;display:inline-flex;align-items:center" 
                onclick="ovRemoveLayer('${_ovEsc(ov.id)}')" 
                title="Xóa">
                🗑️
              </button>
            </span>
          </div>
          <div class="ov-layer-body" onclick="if(!event.target.closest('input,select,textarea,button,label')) ovSelectLayer('${_ovEsc(ov.id)}', false, true)">
            ${_ovLayerBody(ov)}
          </div>
        </div>`;
    }).join('');
    _ovSyncHidden();
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  }
  function ovAddText() {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    window._videoOverlays.forEach(x => { x.open = false; });
    const ov = _ovDefault('text');
    window._videoOverlays.push(ov);
    ovSelectLayer(ov.id, true);
  }
  function ovAddRect() {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    window._videoOverlays.forEach(x => { x.open = false; });
    const ov = _ovDefault('rect');
    window._videoOverlays.push(ov);
    ovSelectLayer(ov.id, true);
  }
  function _ovResolveUrl(serverPath) {
    if (!serverPath) return '';
    const pathParts = serverPath.split(/[\\/]/);
    const filename = pathParts[pathParts.length - 1];
    return '/temp_uploads/' + filename;
  }
  function ovAddImage(input) {
    const file = input.files?.[0];
    if (!file) return;
    input.value = '';

    if (typeof toast === 'function') toast('⏳ Đang tải hình ảnh lên...', 'info');
    
    _uploadFileWithProgress(file, 'logo',
      function(pct) {
        if (typeof toast === 'function') {
          toast('⏳ Đang tải hình ảnh: ' + pct + '%', 'info', { id: 'ov-add-img-upload', duration: 1500 });
        }
      },
      function(d) {
        if (d.ok && d.path) {
          if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
          window._videoOverlays.forEach(x => { x.open = false; });
          
          const ov = _ovDefault('image');
          ov.path = d.path;
          ov.name = file.name;
          
          window._videoOverlays.push(ov);
          ovSelectLayer(ov.id, true);
          
          if (typeof toast === 'function') toast('✓ Đã tải lên hình ảnh: ' + file.name, 'success');
        } else {
          if (typeof toast === 'function') toast('✗ Tải lên hình ảnh thất bại: ' + (d.error || ''), 'error');
        }
      },
      function(err) {
        if (typeof toast === 'function') toast('✗ Lỗi kết nối khi tải hình ảnh', 'error');
      }
    );
  }
  function ovChangeImage(input) {
    const file = input.files?.[0];
    if (!file) return;
    const id = input.dataset.ovId;
    input.value = '';
    if (!id) return;

    const ov = _ovFind(id);
    if (!ov) return;

    if (typeof toast === 'function') toast('⏳ Đang tải hình ảnh mới...', 'info');

    _uploadFileWithProgress(file, 'logo',
      function(pct) {
        if (typeof toast === 'function') {
          toast('⏳ Đang tải hình ảnh: ' + pct + '%', 'info', { id: 'ov-change-img-upload', duration: 1500 });
        }
      },
      function(d) {
        if (d.ok && d.path) {
          if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
          
          ov.path = d.path;
          ov.name = file.name;
          
          ovRenderLayerList();
          if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
          if (typeof toast === 'function') toast('✓ Đã đổi hình ảnh: ' + file.name, 'success');
        } else {
          if (typeof toast === 'function') toast('✗ Tải lên hình ảnh thất bại: ' + (d.error || ''), 'error');
        }
      },
      function(err) {
        if (typeof toast === 'function') toast('✗ Lỗi kết nối khi đổi hình ảnh', 'error');
      }
    );
  }
  window.ovRenderLayerList = ovRenderLayerList;
  window.ovAddText = ovAddText;
  window.ovAddRect = ovAddRect;
  window.ovAddImage = ovAddImage;
  window._ovResolveUrl = _ovResolveUrl;
  function _collectVideoOverlays() {
    return (window._videoOverlays || []).map(_ovNormalizeLayer).filter(ov => {
      if (!ov.enabled) return false;
      if (ov.type === 'text' && !String(ov.text || '').trim()) return false;
      return true;
    }).map(ov => {
      const out = {
        type: ov.type,
        x_pct: ov.x_pct,
        y_pct: ov.y_pct,
        start_sec: ov.start_sec === '' ? null : ov.start_sec,
        end_sec: ov.end_sec === '' ? null : ov.end_sec,
      };
      if (ov.type === 'text') {
        out.text = ov.text;
        out.size_pct = ov.size_pct;
        out.weight = ov.weight;
        out.padding_pct = ov.padding_pct;
        out.color = ov.color;
        out.box_color = ov.box_color;
        out.box_opacity = ov.box_opacity;
      } else if (ov.type === 'image') {
        out.path = ov.path;
        out.name = ov.name;
        out.width_pct = ov.width_pct;
        out.height_pct = ov.height_pct;
        out.opacity = ov.opacity;
      } else {
        out.width_pct = ov.width_pct;
        out.height_pct = ov.height_pct;
        out.color = ov.color;
        out.opacity = ov.opacity;
        out.radius_pct = ov.radius_pct;
      }
      return out;
    });
  }
  function _drawOverlayText(ctx, ov, x, y, w, h) {
    const text = String(ov.text || '').trim();
    if (!text) return null;
    const fontPx = Math.max(8, Math.round(h * (ov.size_pct || 0.05)));
    const weight = Math.max(300, Math.min(900, parseInt(ov.weight || 700, 10) || 700));
    const padMul = Math.max(0, Math.min(1.5, Number(ov.padding_pct ?? 0.55)));
    ctx.save();
    ctx.font = `${weight} ${fontPx}px Arial, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const maxW = w * 0.9;
    const words = text.split(/\s+/);
    const lines = [];
    let line = '';
    words.forEach(word => {
      const test = line ? line + ' ' + word : word;
      if (ctx.measureText(test).width > maxW && line) {
        lines.push(line);
        line = word;
      } else {
        line = test;
      }
    });
    if (line) lines.push(line);
    const lineH = fontPx * 1.25;
    const padX = fontPx * padMul;
    const padY = fontPx * padMul * 0.65;
    const textW = Math.min(maxW, Math.max(...lines.map(l => ctx.measureText(l).width), 1));
    const boxW = textW + padX * 2;
    const boxH = lines.length * lineH + padY * 2;
    const cx = x + w * Math.max(0, Math.min(1, ov.x_pct ?? 0.5));
    const cy = y + h * Math.max(0, Math.min(1, ov.y_pct ?? 0.18));
    if ((ov.box_opacity || 0) > 0) {
      ctx.fillStyle = _ovRgba(ov.box_color || '#000000', ov.box_opacity || 0);
      ctx.beginPath();
      _roundRect(ctx, cx - boxW / 2, cy - boxH / 2, boxW, boxH, Math.min(fontPx * 0.4, boxH / 2));
      ctx.fill();
    }
    ctx.fillStyle = ov.color || '#ffffff';
    ctx.shadowColor = 'rgba(0,0,0,0.85)';
    ctx.shadowBlur = 4;
    lines.forEach((l, i) => {
      const yy = cy - ((lines.length - 1) * lineH) / 2 + i * lineH;
      ctx.fillText(l, cx, yy);
    });
    ctx.restore();
    return { x: cx - boxW / 2, y: cy - boxH / 2, w: boxW, h: boxH };
  }
  function _drawVideoOverlaysOnCanvas(ctx, vidX, vidY, vidW, vidH) {
    window._lastCanvasOverlayBoxes = window._lastCanvasOverlayBoxes || {};
    (window._videoOverlays || []).filter(ov => ov.enabled !== false && _ovVisibleAtPreviewTime(ov)).forEach(ov => {
      if (ov.type === 'rect') {
        const rw = vidW * Math.max(0.01, Math.min(1, ov.width_pct || 0.8));
        const rh = vidH * Math.max(0.01, Math.min(1, ov.height_pct || 0.12));
        const rx = vidX + vidW * Math.max(0, Math.min(1, ov.x_pct ?? 0.5)) - rw / 2;
        const ry = vidY + vidH * Math.max(0, Math.min(1, ov.y_pct ?? 0.5)) - rh / 2;
        ctx.save();
        ctx.fillStyle = _ovRgba(ov.color || '#000000', ov.opacity ?? 0.55);
        ctx.beginPath();
        _roundRect(ctx, rx, ry, rw, rh, Math.min(rw, rh) * Math.max(0, Math.min(0.5, ov.radius_pct || 0.02)));
        ctx.fill();
        ctx.restore();
        window._lastCanvasOverlayBoxes[ov.id] = {
          left: (rx - vidX) / vidW,
          right: (rx + rw - vidX) / vidW,
          top: (ry - vidY) / vidH,
          bottom: (ry + rh - vidY) / vidH,
          x: (rx + rw/2 - vidX) / vidW,
          y: (ry + rh/2 - vidY) / vidH,
          w: rw / vidW,
          h: rh / vidH
        };
        if (window._pe2Sel && window._pe2Sel.type === 'overlay' && String(window._pe2Sel.id) === String(ov.id)) {
          _drawCanvasSelection(ctx, rx, ry, rw, rh, true, false);
        }
      } else if (ov.type === 'text') {
        const box = _drawOverlayText(ctx, ov, vidX, vidY, vidW, vidH);
        if (box) {
          window._lastCanvasOverlayBoxes[ov.id] = {
            left: (box.x - vidX) / vidW,
            right: (box.x + box.w - vidX) / vidW,
            top: (box.y - vidY) / vidH,
            bottom: (box.y + box.h - vidY) / vidH,
            x: (box.x + box.w/2 - vidX) / vidW,
            y: (box.y + box.h/2 - vidY) / vidH,
            w: box.w / vidW,
            h: box.h / vidH
          };
          if (window._pe2Sel && window._pe2Sel.type === 'overlay' && String(window._pe2Sel.id) === String(ov.id)) {
            _drawCanvasSelection(ctx, box.x, box.y, box.w, box.h, true, true);
          }
        }
      }
    });
  }
  function _renderVideoOverlayDom(wrap, imgOffX, imgOffY, dispW, dispH) {
    if (!wrap) return;
    wrap.querySelectorAll('.video-overlay-el').forEach(el => el.remove());
    (window._videoOverlays || []).filter(ov => ov.enabled !== false && _ovVisibleAtPreviewTime(ov)).forEach(ov => {
      if (ov.type === 'text' && !String(ov.text || '').trim()) return;
      
      const el = document.createElement('div');
      el.className = 'video-overlay-el type-' + ov.type;
      el.dataset.ovId = ov.id;
      el.style.position = 'absolute';
      el.style.pointerEvents = 'auto';
      el.style.cursor = 'move';
      const isSelected = window._pe2Sel && window._pe2Sel.type === 'overlay' && String(window._pe2Sel.id) === String(ov.id);
      el.style.zIndex = isSelected ? '10' : '3';

      if (ov.type === 'image') {
        const w = dispW * Math.max(0.01, Math.min(1, ov.width_pct || 0.20));
        const h = dispH * Math.max(0.01, Math.min(1, ov.height_pct || 0.20));
        el.style.left = (imgOffX + dispW * (ov.x_pct ?? 0.5) - w / 2) + 'px';
        el.style.top = (imgOffY + dispH * (ov.y_pct ?? 0.5) - h / 2) + 'px';
        el.style.width = w + 'px';
        el.style.height = h + 'px';
        el.style.opacity = ov.opacity ?? 1.0;
        
        el.style.backgroundImage = `url("${_ovResolveUrl(ov.path)}")`;
        el.style.backgroundSize = 'contain';
        el.style.backgroundPosition = 'center';
        el.style.backgroundRepeat = 'no-repeat';
      } else if (ov.type === 'rect') {
        const w = dispW * Math.max(0.01, Math.min(1, ov.width_pct || 0.8));
        const h = dispH * Math.max(0.01, Math.min(1, ov.height_pct || 0.12));

        el.style.left = (imgOffX + dispW * (ov.x_pct ?? 0.5) - w / 2) + 'px';
        el.style.top = (imgOffY + dispH * (ov.y_pct ?? 0.5) - h / 2) + 'px';
        el.style.width = w + 'px';
        el.style.height = h + 'px';
        el.style.background = _ovRgba(ov.color || '#000000', ov.opacity ?? 0.55);
        el.style.borderRadius = (Math.min(w, h) * Math.max(0, Math.min(0.5, ov.radius_pct || 0.02))) + 'px';
      } else if (ov.type === 'text') {
        const weight = Math.max(300, Math.min(900, parseInt(ov.weight || 700, 10) || 700));
        const padMul = Math.max(0, Math.min(1.5, Number(ov.padding_pct ?? 0.55)));
        el.textContent = ov.text || '';
        el.style.display = 'inline-block';
        el.style.width = 'auto';
        el.style.whiteSpace = 'nowrap';
        el.style.left = (imgOffX + dispW * (ov.x_pct ?? 0.5)) + 'px';
        el.style.top = (imgOffY + dispH * (ov.y_pct ?? 0.18)) + 'px';
        el.style.transform = 'translate(-50%, -50%)';
        el.style.maxWidth = (dispW * 0.9) + 'px';
        el.style.textAlign = 'center';
        el.style.wordBreak = 'break-word';
        el.style.font = `${weight} ${Math.max(8, Math.round(dispH * (ov.size_pct || 0.05)))}px Arial, sans-serif`;
        el.style.lineHeight = '1.25';
        el.style.color = ov.color || '#ffffff';
        el.style.textShadow = '0 2px 6px rgba(0,0,0,.85)';
        el.style.padding = (padMul * 0.65) + 'em ' + padMul + 'em';
        el.style.borderRadius = '0.35em';
        el.style.background = _ovRgba(ov.box_color || '#000000', ov.box_opacity || 0);
      }
      const handles = ['nw','n','ne','e','se','s','sw','w'];
      handles.forEach(function(edge){
        const hd = document.createElement('div');
        hd.className = 'pe2-handle ' + edge;
        hd.dataset.pe2handle = edge;
        el.appendChild(hd);
      });
      wrap.appendChild(el);
    });
  }
  const _PROC_ASPECT_OVERRIDE_K = 'proc_aspect_override_v1';        // 'auto' | '9x16' | '16x9'
  function _onAspectOverrideChange() {
    const override = _getAspectOverride();
    try { localStorage.setItem(_PROC_ASPECT_OVERRIDE_K, override); } catch (_) {}
    if (override !== 'auto') {
      window._procActiveAspect = override;
      _applyPresetForActiveAspect({ silent: true });
    } else {
      // Re-detect from current frame if available
      const img = document.getElementById('sub-preview-img');
      if (img && img.naturalWidth) {
        window._procActiveAspect = _classifyAspect(img.naturalWidth, img.naturalHeight);
        _applyPresetForActiveAspect({ silent: true });
      }
    }
    _updateAspectBadge();
  }
  function _applyPresetForActiveAspect(opts) {
    opts = opts || {};
    const map = _loadPresetsMap();
    const data = map[window._procActiveAspect];
    if (!data) {
      if (!opts.silent) toast(`Chưa có cài đặt mặc định cho ${window._procActiveAspect.replace('x', ':')}`, 'warning');
      return false;
    }
    _PROC_FIELDS.forEach(f => {
      const el = document.getElementById(f.id);
      if (!el || !(f.id in data)) return;
      if (f.type === 'checkbox') el.checked = data[f.id];
      else el.value = data[f.id];
      el.dispatchEvent(new Event('change'));
      el.dispatchEvent(new Event('input'));
    });
    if (data['frame-blur-mode']) {
      const radio = document.querySelector(`input[name="frame-blur-mode"][value="${data['frame-blur-mode']}"]`);
      if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change')); }
    }
    if (typeof _onTargetLangChange === 'function') {
      _onTargetLangChange();
    } else if (typeof _syncVoiceOptions === 'function') {
      _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
    }
    if (typeof _syncColorPicker === 'function') _syncColorPicker();
    if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
    if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
    if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    return true;
  }
  function procSaveDefaults() {
    const data = {};
    if (typeof _ovSyncHidden === 'function') _ovSyncHidden();
    _PROC_FIELDS.forEach(f => {
      const el = document.getElementById(f.id);
      if (!el) return;
      data[f.id] = f.type === 'checkbox' ? el.checked : el.value;
    });
    // Save blur mode radio
    const blurMode = document.querySelector('input[name="frame-blur-mode"]:checked')?.value;
    if (blurMode) data['frame-blur-mode'] = blurMode;

    try {
      const map = _loadPresetsMap();
      const aspect = window._procActiveAspect || '16x9';
      map[aspect] = data;
      _savePresetsMap(map);
      // Keep legacy v1 in sync with the most recently saved preset for backward compat
      try { localStorage.setItem(_PROC_DEFAULTS_KEY, JSON.stringify(data)); } catch (_) {}
      toast(`✅ Đã lưu cài đặt mặc định cho ${aspect.replace('x', ':')}`, 'success');
      _updateAspectBadge();
    } catch (e) {
      toast('Lỗi lưu: ' + e.message, 'error');
    }
  }
  function procRestoreDefaults() {
    try {
      const map = _loadPresetsMap();
      const aspect = window._procActiveAspect || '16x9';
      const data = map[aspect];
      if (!data) {
        toast(`Chưa có cài đặt mặc định cho tỉ lệ ${aspect.replace('x', ':')}`, 'warning');
        return;
      }
      _PROC_FIELDS.forEach(f => {
        const el = document.getElementById(f.id);
        if (!el || !(f.id in data)) return;
        if (f.type === 'checkbox') el.checked = data[f.id];
        else el.value = data[f.id];
        // Trigger change events for dependent UI
        el.dispatchEvent(new Event('change'));
        el.dispatchEvent(new Event('input'));
      });
      // Restore blur mode radio
      if (data['frame-blur-mode']) {
        const radio = document.querySelector(`input[name="frame-blur-mode"][value="${data['frame-blur-mode']}"]`);
        if (radio) { radio.checked = true; radio.dispatchEvent(new Event('change')); }
      }
      // Sync voice options after restore
      if (typeof _onTargetLangChange === 'function') {
        _onTargetLangChange();
      } else if (typeof _syncVoiceOptions === 'function') {
        _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
      }
      // Sync frame controls visibility
      if (typeof frameToggle === 'function') frameToggle();
      // Sync preview aspect layout
      if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
      if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
      if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
      // Sync time input display after restore
      if (typeof window.pe2SyncPlayhead === 'function') window.pe2SyncPlayhead();
      toast(`✅ Đã khôi phục cài đặt cho tỉ lệ ${aspect.replace('x', ':')}`, 'success');
    } catch (e) {
      toast('Lỗi khôi phục: ' + e.message, 'error');
    }
  }
  document.addEventListener('DOMContentLoaded', () => {
    try {
      // Pick initial preset to apply on first load
      const map = _loadPresetsMap();
      const aspectSel = document.getElementById('proc-preview-aspect');
      let selectedAspect = aspectSel?.value || 'auto';
      try {
        const savedAspect = localStorage.getItem(_PROC_PREVIEW_ASPECT_K);
        if (savedAspect === 'auto' || savedAspect === '16x9' || savedAspect === '9x16') {
          selectedAspect = savedAspect;
        }
      } catch (_) {}
      if (aspectSel) aspectSel.value = selectedAspect;

      const img = document.getElementById('sub-preview-img');
      const initialAspect = selectedAspect === 'auto'
        ? ((img && img.naturalWidth) ? _classifyAspect(img.naturalWidth, img.naturalHeight) : '16x9')
        : selectedAspect;
      window._procActiveAspect = initialAspect;
      const data = map[initialAspect] || map['9x16'];

      if (data) {
        _PROC_FIELDS.forEach(f => {
          const el = document.getElementById(f.id);
          if (!el || !(f.id in data)) return;
          if (f.type === 'checkbox') el.checked = data[f.id];
          else el.value = data[f.id];
        });
        // Restore blur mode radio (not in _PROC_FIELDS because it's a radio group)
        if (data['frame-blur-mode']) {
          const radio = document.querySelector(`input[name="frame-blur-mode"][value="${data['frame-blur-mode']}"]`);
          if (radio) radio.checked = true;
        }
        if (typeof _onTargetLangChange === 'function') {
          _onTargetLangChange();
        } else if (typeof _syncVoiceOptions === 'function') {
          _syncVoiceOptions('proc-tts-engine', 'proc-tts-voice');
        }
        if (typeof _syncColorPicker === 'function') _syncColorPicker();
        if (typeof _ovLoadFromHidden === 'function') _ovLoadFromHidden();
        if (typeof ovRenderLayerList === 'function') ovRenderLayerList();
      }
      _updateAspectBadge();
      // Sync frame controls visibility on page load
      if (typeof frameToggle === 'function') frameToggle();
      // Apply preview aspect on page load (reads from proc-preview-aspect select which was restored above)
      if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
      if (typeof window._syncAspectBtns === 'function') window._syncAspectBtns();
      // Sync time input display after restore
      if (typeof window.pe2SyncPlayhead === 'function') window.pe2SyncPlayhead();
    } catch (_) {}
  });


if (typeof _ovClamp !== "undefined") window._ovClamp = _ovClamp;


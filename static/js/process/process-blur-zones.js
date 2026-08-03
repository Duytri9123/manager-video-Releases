function procRemoveAiZones() {
    const before = (window._procExtraBlurZones || []).length;
    window._procExtraBlurZones = (window._procExtraBlurZones || []).filter(z => z.zone !== 'ai' && z.source !== 'ai');
    if ((window._procExtraBlurZones || []).length !== before) {
      if (typeof _renderExtraBlurZones === 'function') _renderExtraBlurZones();
      if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    }
  }
  function procApplyAiAnalysis() {
    const result = window._procVideoAiAnalysis?.result;
    if (!result || !window._procUseAiAnalysis) return;
    const zones = Array.isArray(result.suggested_blur_zones) ? result.suggested_blur_zones : [];
    procRemoveAiZones();
    zones.forEach(z => {
      _blurZoneCounter++;
      window._procExtraBlurZones.push({
        id: _blurZoneCounter,
        height: Math.max(3, Math.min(45, parseFloat(z.height_pct ?? 12) || 12)),
        position: Math.max(0, Math.min(100, parseFloat(z.position_pct ?? 50) || 50)),
        width: Math.max(20, Math.min(100, parseFloat(z.width_pct ?? 85) || 85)),
        x: Math.max(0, Math.min(100, parseFloat(z.x_pct ?? 50) || 50)),
        start: (z.start_sec === null || z.start_sec === undefined) ? '' : z.start_sec,
        end: (z.end_sec === null || z.end_sec === undefined) ? '' : z.end_sec,
        zone: 'ai',
        source: 'ai',
        label: z.label || '',
        reason: z.reason || ''
      });
    });
    if (zones.length) window._procExtraBlurOpenIds = window._procExtraBlurZones.filter(z => z.zone === 'ai').map(z => z.id);
    if (typeof _renderExtraBlurZones === 'function') _renderExtraBlurZones();
    if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
  }
  function _drawSubtitleOnCanvas(ctx, cW, cH, vidX, vidY, vidW, vidH) {
    const sample    = document.getElementById('sub-preview-sample')?.value || '';
    const burnOn    = document.getElementById('proc-burn')?.checked ?? true;
    const burnViOn  = document.getElementById('proc-burn-vi')?.checked ?? true;

    const fontPct   = parseFloat(document.getElementById('proc-font-size')?.value || 4.5);
    const marginPct = parseFloat(document.getElementById('proc-margin-v')?.value  || 3);
    const pos       = document.getElementById('proc-sub-pos')?.value || 'bottom';
    const cssColor  = (typeof _getSubtitleColor === 'function') ? _getSubtitleColor() : '#ffffff';
    const blurOn    = document.getElementById('proc-blur-original')?.checked || false;

    // ── Draw blur zone (che phụ đề gốc) ──
    if (blurOn) {
      const blurZone = document.getElementById('proc-blur-zone')?.value || 'bottom';
      if (blurZone !== 'none') {
        const blurH = parseFloat(document.getElementById('proc-blur-height')?.value || 15) / 100;
        const blurW = parseFloat(document.getElementById('proc-blur-width')?.value || 80) / 100;
        const blurLift = 0.06;

        let blurCenterY = 0.5;
        const blurYOverride = document.getElementById('proc-blur-y')?.value?.trim();
        if (blurYOverride !== '' && blurYOverride !== undefined) {
          blurCenterY = parseFloat(blurYOverride) / 100;
        } else {
          if (blurZone === 'top') {
            blurCenterY = blurH / 2 + blurLift;
          } else {
            blurCenterY = 1.0 - blurH / 2 - blurLift;
          }
        }

        const blurXOverride = document.getElementById('proc-blur-x')?.value?.trim();
        let blurCenterX = 0.5;
        if (blurXOverride !== '' && blurXOverride !== undefined) {
          blurCenterX = parseFloat(blurXOverride) / 100;
        }

        // Tự động co dãn khi kéo sát/vượt mép biên để tránh bị chặn, kẹt hoặc lỗi toạ độ
        const leftPct = Math.max(0, blurCenterX - blurW / 2);
        const rightPct = Math.min(1, blurCenterX + blurW / 2);
        const bX = vidX + Math.round(vidW * leftPct);
        const bW = Math.round(vidW * Math.max(0.01, rightPct - leftPct));

        const topPct = Math.max(0, blurCenterY - blurH / 2);
        const bottomPct = Math.min(1, blurCenterY + blurH / 2);
        const bY = vidY + Math.round(vidH * topPct);
        const bH = Math.round(vidH * Math.max(0.01, bottomPct - topPct));

        // Draw blurred region (simulate with semi-transparent dark overlay)
        ctx.save();
        ctx.filter = 'blur(8px)';
        ctx.drawImage(ctx.canvas, bX, bY, bW, bH, bX - 4, bY - 4, bW + 8, bH + 8);
        ctx.restore();
        ctx.fillStyle = 'rgba(0,0,0,0.35)';
        ctx.fillRect(bX, bY, bW, bH);

        // Draw selection outline if main blur zone is selected
        if (window._pe2Sel && window._pe2Sel.type === 'blur') {
          _drawCanvasSelection(ctx, bX, bY, bW, bH, true, false);
        }
      }
    }

    // Draw extra blur zones independently from the main "che phụ đề gốc" toggle.
    if (window._procExtraBlurZones && window._procExtraBlurZones.length > 0) {
      window._procExtraBlurZones.forEach(zone => {
        const zH = (zone.height || 12) / 100;
        const zY = (zone.position || 50) / 100 - zH / 2;
        const zW = (zone.width || 80) / 100;
        const zXc = ((zone.x === undefined || zone.x === null) ? 50 : zone.x) / 100;
        const zLeftFrac = Math.max(0, Math.min(1 - zW, zXc - zW / 2));

        const ezH = Math.round(vidH * zH);
        const ezW = Math.round(vidW * zW);
        const ezX = vidX + Math.round(vidW * zLeftFrac);
        const ezY = vidY + Math.round(vidH * Math.max(0, Math.min(1 - zH, zY)));

        ctx.save();
        ctx.filter = 'blur(8px)';
        ctx.drawImage(ctx.canvas, ezX, ezY, ezW, ezH, ezX - 4, ezY - 4, ezW + 8, ezH + 8);
        ctx.restore();
        ctx.fillStyle = 'rgba(0,0,0,0.35)';
        ctx.fillRect(ezX, ezY, ezW, ezH);

        // Draw selection outline + handles if this zone is selected
        const sel = window._pe2Sel;
        if (sel && sel.type === 'extra' && sel.id === zone.id) {
          _drawCanvasSelection(ctx, ezX, ezY, ezW, ezH, true, false);
        }
      });
    }

    if (!sample || !burnOn || !burnViOn) return null;

    // Scale relative to video area height (same formula as _renderSubOverlay)
    const scaledFont   = Math.max(6, Math.round(vidH * fontPct   / 100));
    const scaledMargin = Math.max(2, Math.round(vidH * marginPct / 100));

    const boldOn = document.getElementById('proc-font-bold')?.checked ?? true;
    const outlineW = parseInt(document.getElementById('proc-outline-width')?.value || 2);

    ctx.font         = `${boldOn ? 'bold ' : ''}${scaledFont}px Arial, sans-serif`;
    ctx.fillStyle    = cssColor;
    ctx.textAlign    = 'center';
    ctx.textBaseline = pos === 'top' ? 'top' : 'bottom';
    ctx.shadowColor  = 'rgba(0,0,0,0.9)';
    ctx.shadowBlur   = 4;
    ctx.shadowOffsetX = 1; ctx.shadowOffsetY = 1;

    const textX = vidX + vidW / 2;
    const textY = pos === 'top'
      ? vidY + scaledMargin
      : vidY + vidH - scaledMargin;

    // Word wrap within video width
    const maxW = vidW * 0.9;
    const words = sample.split(' ');
    let lines = [], line = '';
    for (const w of words) {
      const test = line ? line + ' ' + w : w;
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = w; }
      else line = test;
    }
    if (line) lines.push(line);

    const lH = scaledFont * 1.3;
    const lineWidths = lines.map(l => ctx.measureText(l).width);
    const textW = Math.min(maxW, Math.max(...lineWidths, scaledFont));
    const textH = lines.length * lH;
    const textBounds = {
      x: textX - textW / 2 - scaledFont * 0.25,
      y: pos === 'top' ? textY - scaledFont * 0.1 : textY - textH - scaledFont * 0.1,
      w: textW + scaledFont * 0.5,
      h: textH + scaledFont * 0.2
    };

    const drawTextLine = (l, tx, ty) => {
      if (outlineW > 0) {
        ctx.save();
        ctx.strokeStyle = '#000000';
        ctx.lineWidth = outlineW * 2;
        ctx.lineJoin = 'round';
        ctx.strokeText(l, tx, ty);
        ctx.restore();
      }
      ctx.fillText(l, tx, ty);
    };

    if (pos === 'top') {
      lines.forEach((l, i) => drawTextLine(l, textX, textY + i * lH));
    } else {
      // Draw from bottom up
      [...lines].reverse().forEach((l, i) => drawTextLine(l, textX, textY - i * lH));
    }
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
    if (window._pe2Sel && window._pe2Sel.type === 'sub') {
      _drawCanvasSelection(ctx, textBounds.x, textBounds.y, textBounds.w, textBounds.h, true, true);
    }
    return textBounds;
  }
  async function generateThumbnailPreview() {
    const source = _getPreviewVideoPath();
    if (!source) {
      toast('Chưa có video — hãy chọn file hoặc nhập URL', 'warning');
      return;
    }

    const ts = parseFloat(document.getElementById('sub-preview-ts')?.value || 2);

    const img = document.getElementById('thumb-preview-img');
    const ph  = document.getElementById('thumb-placeholder');
    const info = document.getElementById('thumb-output-info');
    const btn = document.querySelector('[onclick="generateThumbnailPreview()"]');

    if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }
    if (ph) { ph.style.display = 'block'; ph.textContent = 'Đang lấy preview...'; }
    if (img) img.style.display = 'none';
    if (info) info.style.display = 'none';

    try {
      let res, data;

      if (source.type === 'file') {
        // Chỉ lấy frame preview (không tạo file thumbnail)
        res = await fetch('/api/video_frame', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ video_path: source.val, timestamp: ts }),
        });
        data = await res.json();
      } else {
        // URL — lấy cover từ URL
        res = await fetch('/api/video_frame_from_url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: source.val }),
        });
        data = await res.json();
      }

      if (data.ok && data.image) {
        if (img) {
          img.src = data.image;
          img.style.display = 'block';
        }
        if (ph) ph.style.display = 'none';
        // Save state — frame mode means: server will extract frame at runtime, no path needed
        window._thumbState = { mode: 'frame', path: '', b64: data.image };
        toast('✓ Preview thumbnail', 'success');
      } else {
        if (ph) { ph.style.display = 'block'; ph.textContent = data.error || 'Không lấy được frame'; }
        toast('Lỗi: ' + (data.error || ''), 'error');
      }
    } catch (e) {
      if (ph) { ph.style.display = 'block'; ph.textContent = 'Lỗi: ' + e.message; }
      toast('Lỗi: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '🎨'; }
    }
  }
  window._procExtraBlurZones = [];
  let _blurZoneCounter = 0;
  function procAddBlurZone() {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    _blurZoneCounter++;
    const id = _blurZoneCounter;
    window._procExtraBlurZones.push({ id, height: 12, position: 50, width: 80, x: 50, start: '', end: '', zone: 'custom' });
    window._procExtraBlurOpenIds = [id];
    _renderExtraBlurZones();
    subPreviewUpdate();
  }
  function procRemoveBlurZone(id) {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    window._procExtraBlurZones = window._procExtraBlurZones.filter(z => z.id !== id);
    window._procExtraBlurOpenIds = (window._procExtraBlurOpenIds || []).filter(openId => openId !== id);
    _renderExtraBlurZones();
    subPreviewUpdate();
  }
  function procRememberBlurZoneOpen(id, isOpen) {
    const openIds = new Set(window._procExtraBlurOpenIds || []);
    if (isOpen) openIds.add(id);
    else openIds.delete(id);
    window._procExtraBlurOpenIds = Array.from(openIds);
  }
  function _renderExtraBlurZones() {
    const container = document.getElementById('proc-blur-extra-list');
    if (!container) return;
    const liveDetails = Array.from(container.querySelectorAll('.pe2-extra-zone'));
    const openIds = new Set(
      liveDetails.length
        ? liveDetails.filter(el => el.open).map(el => parseInt(el.dataset.blurId, 10))
        : (window._procExtraBlurOpenIds || [])
    );
    const selectedExtraId = (window._pe2Sel && window._pe2Sel.type === 'extra') ? window._pe2Sel.id : null;
    if (selectedExtraId != null) openIds.add(parseInt(selectedExtraId, 10));
    const zoneIds = new Set((window._procExtraBlurZones || []).map(z => z.id));
    window._procExtraBlurOpenIds = Array.from(openIds).filter(id => zoneIds.has(id));
    container.innerHTML = window._procExtraBlurZones.map((z, idx) => {
      var st = (z.start === '' || z.start == null) ? '' : z.start;
      var en = (z.end === '' || z.end == null) ? '' : z.end;
      var rangeTxt = '⏱ Burn ' + (st !== '' ? ('từ ' + st + 's') : 'từ đầu') + ' ' + (en !== '' ? ('đến ' + en + 's') : 'đến cuối');
      var xVal = z.x ?? 50;
      var wVal = z.width ?? 80;
      var openAttr = openIds.has(z.id) ? ' open' : '';
      return `
      <details class="pe2-extra-zone" data-blur-id="${z.id}"${openAttr} ontoggle="procRememberBlurZoneOpen(${z.id}, this.open)">
        <summary>
          <span class="pe2-extra-zone-caret">▶</span>
          <span class="pe2-extra-zone-main">
            <span class="pe2-extra-zone-title">Vùng che ${idx + 1}</span>
            <span class="pe2-extra-zone-meta">Cao ${z.height}% · Y ${z.position}% · X ${xVal}% · Rộng ${wVal}%</span>
            <span class="pe2-extra-zone-meta">${rangeTxt}</span>
          </span>
          <button type="button" style="border:none;background:transparent;padding:4px 6px;cursor:pointer;font-size:15px;color:#ef4444;line-height:1;vertical-align:middle;flex:0 0 auto" 
            onclick="event.preventDefault();event.stopPropagation();procRemoveBlurZone(${z.id})" 
            title="Xóa vùng che">
            🗑️
          </button>
        </summary>
        <div class="pe2-extra-zone-body">
        <div class="pe2-extra-zone-grid">
          <div class="field"><label>Cao %</label><input type="number" value="${z.height}" min="3" max="40" step="1" style="height:36px" oninput="procUpdateBlurZone(${z.id},'height',this.value,true)"></div>
          <div class="field"><label>Y %</label><input type="number" value="${z.position}" min="0" max="100" step="1" style="height:36px" oninput="procUpdateBlurZone(${z.id},'position',this.value,true)"></div>
          <div class="field"><label>X %</label><input type="number" value="${xVal}" min="0" max="100" step="1" style="height:36px" oninput="procUpdateBlurZone(${z.id},'x',this.value,true)"></div>
          <div class="field"><label>Rộng %</label><input type="number" value="${wVal}" min="20" max="100" step="5" style="height:36px" oninput="procUpdateBlurZone(${z.id},'width',this.value,true)"></div>
        </div>
        <div class="pe2-extra-zone-time">
          <div class="field"><label>Từ (s)</label><input type="number" value="${st}" min="0" step="0.5" placeholder="đầu" style="height:36px" oninput="procUpdateBlurZone(${z.id},'start',this.value,true)" onchange="procUpdateBlurZone(${z.id},'start',this.value)"></div>
          <div class="field"><label>Đến (s)</label><input type="number" value="${en}" min="0" step="0.5" placeholder="cuối" style="height:36px" oninput="procUpdateBlurZone(${z.id},'end',this.value,true)" onchange="procUpdateBlurZone(${z.id},'end',this.value)"></div>
        </div>
        </div>
      </details>`;
    }).join('');
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  }
  function procUpdateBlurZone(id, key, val, soft) {
    const zone = window._procExtraBlurZones.find(z => z.id === id);
    if (!zone) return;
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    if (key === 'start' || key === 'end') {
      zone[key] = (val === '' || val === null || val === undefined) ? '' : (parseFloat(val) || 0);
      if (!soft) _renderExtraBlurZones();   // cập nhật dòng "Burn từ … đến …"
    } else {
      zone[key] = parseFloat(val) || 0;
    }
    subPreviewUpdate();
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  }
  function thumbImportFile(input) {
    const file = input.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      toast('Chỉ hỗ trợ file ảnh', 'error');
      return;
    }
    // Upload file to server
    const fd = new FormData();
    fd.append('file', file);
    fd.append('type', 'thumbnail');
    fetch('/api/upload_anti_fp_image', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.ok && data.path) {
          window._thumbState = { mode: 'import', path: data.path, b64: '' };
          // Show preview from local FileReader
          const reader = new FileReader();
          reader.onload = e => {
            const img = document.getElementById('thumb-preview-img');
            const ph  = document.getElementById('thumb-placeholder');
            const info = document.getElementById('thumb-output-info');
            if (img) { img.src = e.target.result; img.style.display = 'block'; }
            if (ph) ph.style.display = 'none';
            if (info) { info.style.display = 'block'; info.textContent = '📁 ' + data.path; }
          };
          reader.readAsDataURL(file);
          toast('✓ Đã import thumbnail', 'success');
        } else {
          toast('Lỗi upload: ' + (data.error || ''), 'error');
        }
      })
      .catch(e => toast('Lỗi: ' + e.message, 'error'))
      .finally(() => { input.value = ''; });
  }
  async function generateThumbnailAI() {
    loadThumbAiModels();
    const source = _getPreviewVideoPath();
    const ts = parseFloat(document.getElementById('sub-preview-ts')?.value || 2);
    const title = document.getElementById('thumb-title')?.value?.trim() || '';
    let sample = document.getElementById('sub-preview-sample')?.value?.trim() || '';
    if (sample === 'Đây là phụ đề tiếng Việt mẫu') {
      sample = ''; // Bỏ qua phụ đề mẫu mặc định để tránh làm nhiễu AI
    }

    // Ưu tiên 1: Lấy ảnh đang có sẵn ở Thumbnail để chỉnh sửa / vẽ tiếp lên chính nó
    const existingThumbImg = document.getElementById('thumb-preview-img');
    const previewImg = document.getElementById('sub-preview-img');
    
    let frameB64 = null;
    let isEditingExistingThumb = false;

    if (existingThumbImg && existingThumbImg.src && existingThumbImg.src.startsWith('data:image/')) {
      // Chỉnh sửa thumbnail hiện tại: dùng chính thumbnail đó làm ảnh tham chiếu
      const parts = existingThumbImg.src.split(',');
      if (parts.length > 1) {
        frameB64 = parts[1];
        isEditingExistingThumb = true;
      }
    }
    // Ưu tiên 2: Tạo mới — luôn dùng ảnh frame gốc (không có logo) từ window._rawFrameB64
    else if (window._rawFrameB64) {
      frameB64 = window._rawFrameB64;
    }
    // Fallback cuối: lấy từ src của sub-preview-img (trường hợp không có _rawFrameB64)
    else if (previewImg && previewImg.src && previewImg.src.startsWith('data:image/')) {
      const parts = previewImg.src.split(',');
      if (parts.length > 1) {
        frameB64 = parts[1];
      }
    }

    // Bắt buộc phải có ảnh tham chiếu khi bấm tạo bằng nút AI ở Thumbnail
    if (!frameB64) {
      toast('⚠️ Vui lòng lấy frame Preview hoặc import/tạo sẵn 1 thumbnail trước để AI có ảnh làm dữ liệu tham chiếu!', 'warning');
      return;
    }

    const img = document.getElementById('thumb-preview-img');
    const ph  = document.getElementById('thumb-placeholder');
    const info = document.getElementById('thumb-output-info');
    const btn = document.querySelector('[onclick="generateThumbnailAI()"]');

    const loadingMsg = isEditingExistingThumb
      ? '✏️ AI đang chỉnh sửa thumbnail hiện tại...'
      : '🤖 AI đang phân tích video và tạo thumbnail...';
    const btnLabel  = isEditingExistingThumb ? '⏳ AI đang sửa...' : '⏳ AI đang tạo...';

    if (btn) { btn.disabled = true; btn.textContent = btnLabel; }
    if (ph) { ph.style.display = 'block'; ph.textContent = loadingMsg; }
    if (img) img.style.display = 'none';
    if (info) info.style.display = 'none';

    try {
      const body = {
        timestamp: ts,
        title: title,
        subtitle_text: sample,
        style: 'youtube',
        aspect_ratio: '9:16',
        frame_b64: frameB64,
        is_editing_existing_thumb: isEditingExistingThumb,
        image_model: document.getElementById('thumb-ai-model')?.value || 'auto',
      };

      // Add video_path if source is file
      if (source && source.type === 'file') {
        body.video_path = source.val;
      }

      const res = await fetch('/api/generate_thumbnail_ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.ok && data.image) {
        if (img) {
          img.src = data.image;
          img.style.display = 'block';
        }
        if (ph) ph.style.display = 'none';
        if (info) {
          info.style.display = 'block';
          let infoText = '';
          if (data.output_path) infoText += '📁 ' + data.output_path;
          if (data.prompt_used) infoText += '\n💡 Prompt: ' + data.prompt_used;
          info.textContent = infoText;
        }
        // Save state for batch processing
        window._thumbState = {
          mode: 'ai',
          path: data.output_path || '',
          b64: data.image || ''
        };
        const successMsg = isEditingExistingThumb
          ? '✓ AI đã chỉnh sửa thumbnail thành công!'
          : '✓ AI đã tạo thumbnail mới!';
        toast(successMsg, 'success');
      } else {
        if (ph) { ph.style.display = 'block'; ph.textContent = data.error || 'AI thumbnail thất bại'; }
        toast('Lỗi AI thumbnail: ' + (data.error || ''), 'error');
      }
    } catch (e) {
      if (ph) { ph.style.display = 'block'; ph.textContent = 'Lỗi: ' + e.message; }
      toast('Lỗi: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '🤖'; }
    }
  }
  window.generateThumbnailPreview = async function() {};
  window.thumbImportFile = function(input) { if (input) input.value = ''; };
  window.generateThumbnailAI = async function() {};


if (typeof procRemoveAiZones !== "undefined") window.procRemoveAiZones = procRemoveAiZones;


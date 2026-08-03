const _colorPresets = { white:'#ffffff', yellow:'#ffff00', cyan:'#00ffff' };
function _syncColorPicker() {
  const sel = document.getElementById('proc-font-color');
  const picker = document.getElementById('proc-font-color-picker');
  if (!sel || !picker) return;
  if (sel.value !== 'custom') {
    picker.value = _colorPresets[sel.value] || '#ffffff';
  }
  if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
}
function _onColorPickerChange() {
  const sel = document.getElementById('proc-font-color');
  if (sel) sel.value = 'custom';
  if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
}
function _getSubtitleColor() {
  const sel = document.getElementById('proc-font-color');
  const picker = document.getElementById('proc-font-color-picker');
  if (sel?.value === 'custom' && picker) return picker.value;
  return _colorPresets[sel?.value] || '#ffffff';
}

async function onTranscribeProviderChanged(restoreValue) {
    const provSel = document.getElementById('proc-transcribe-provider-model');
    const modelSel = document.getElementById('proc-model');
    if (!provSel || !modelSel) return;

    const provider = provSel.value;
    const currentVal = restoreValue ? (modelSel.value || 'base') : '';

    // Clear old options
    modelSel.innerHTML = '';

    if (provider === 'model') {
      // Local whisper options
      const opts = [
        { value: 'tiny', text: 'tiny (nhanh nhất)' },
        { value: 'base', text: 'base' },
        { value: 'small', text: 'small' },
        { value: 'medium', text: 'medium' },
        { value: 'large', text: 'large (tốt nhất)' }
      ];
      opts.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.text;
        if (o.value === 'base' && !restoreValue) opt.selected = true;
        modelSel.appendChild(opt);
      });
      if (restoreValue && opts.some(o => o.value === currentVal)) {
        modelSel.value = currentVal;
      }
    } else if (provider === 'groq') {
      // Groq options
      const opts = [
        { value: 'whisper-large-v3-turbo', text: 'whisper-large-v3-turbo (mặc định)' },
        { value: 'whisper-large-v3', text: 'whisper-large-v3' }
      ];
      opts.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.text;
        if (o.value === 'whisper-large-v3-turbo' && !restoreValue) opt.selected = true;
        modelSel.appendChild(opt);
      });
      if (restoreValue && opts.some(o => o.value === currentVal)) {
        modelSel.value = currentVal;
      }
    } else if (provider === 'dtrouter' || provider === 'antigravity' || provider === 'gemini') {
      const optLoading = document.createElement('option');
      optLoading.value = 'gemini-2.0-flash';
      optLoading.textContent = '⏳ Đang tải danh sách mô hình từ Antigravity...';
      modelSel.appendChild(optLoading);

      try {
        const [resAg, resGem] = await Promise.all([
          _procAiFetchJson('/api/providers/models?provider=antigravity', 4000).catch(() => null),
          _procAiFetchJson('/api/providers/models?provider=gemini', 4000).catch(() => null)
        ]);

        modelSel.innerHTML = '';
        let items = [
          { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash (Nhanh & Tối Ưu Audio)' },
          { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash (Tiêu Chuẩn)' },
          { id: 'gemini-3.6-flash', name: 'Gemini 3.6 Flash (Cao Cấp)' },
          { id: 'gemini-1.5-pro',   name: 'Gemini 1.5 Pro (Chính Xác Cao)' },
          { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' }
        ];

        [resAg, resGem].forEach(res => {
          if (res && res.ok && Array.isArray(res.models)) {
            res.models.filter(m => m && m.enabled !== false).forEach(m => {
              const mId = m.id || m;
              if (mId && !items.some(it => it.id === mId)) {
                items.push({ id: mId, name: m.name || mId });
              }
            });
          }
        });

        const grp = document.createElement('optgroup');
        grp.label = '🌌 Mô Hình Antigravity / Gemini Multimodal (Audio STT)';
        items.forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name ? `${m.id} (${m.name})` : m.id;
          if (m.id === 'gemini-2.0-flash' && !restoreValue) opt.selected = true;
          grp.appendChild(opt);
        });
        modelSel.appendChild(grp);

        const availableValues = Array.from(modelSel.options).map(o => o.value);
        if (restoreValue && availableValues.includes(currentVal)) {
          modelSel.value = currentVal;
        }
      } catch (err) {
        modelSel.innerHTML = '<option value="gemini-2.0-flash">Gemini 2.0 Flash</option>';
      }
    }
  }

  window.onTranscribeProviderChanged = onTranscribeProviderChanged;


  let _renderSubOverlayRaf = null;
  function _renderSubOverlay() {
    if (_renderSubOverlayRaf) cancelAnimationFrame(_renderSubOverlayRaf);
    _renderSubOverlayRaf = requestAnimationFrame(() => {
      _renderSubOverlayActual();
    });
  }

  function _renderSubOverlayActual() {
    const wrap    = document.getElementById('sub-preview-wrap');
    const overlay = document.getElementById('sub-preview-text');
    const blurEl  = document.getElementById('sub-preview-blur');
    if (!overlay || !wrap) return;

    // Trạng thái "Ghi phụ đề"
    const burnOn   = document.getElementById('proc-burn')?.checked ?? true;
    const burnViOn = document.getElementById('proc-burn-vi')?.checked ?? true;

    // Khi frame mode bật, subtitle + vùng che được vẽ trên canvas → bỏ DOM overlay
    if (document.getElementById('frame-enabled')?.checked) {
      if (overlay) overlay.style.display = 'none';
      if (blurEl)  blurEl.style.display  = 'none';
      const blurC = document.getElementById('sub-preview-blur-canvas');
      if (blurC) blurC.style.display = 'none';
      // Xoá các div vùng che bổ sung của DOM để không bị hiển thị 2 lớp (canvas + DOM)
      wrap.querySelectorAll('.extra-blur-zone').forEach(el => el.remove());
      wrap.querySelectorAll('.video-overlay-el').forEach(el => el.remove());
      return;
    }

    const img = document.getElementById('sub-preview-img');
    if (!img || img.style.display === 'none') {
      wrap.querySelectorAll('.video-overlay-el').forEach(el => el.remove());
      return; // no frame yet
    }

    const sample   = document.getElementById('sub-preview-sample')?.value || 'Phụ đề mẫu';
    const fontSize = parseInt(document.getElementById('proc-font-size')?.value || 32);
    const color    = document.getElementById('proc-font-color')?.value || 'white';
    const marginV  = parseInt(document.getElementById('proc-margin-v')?.value || 20);
    const pos      = document.getElementById('proc-sub-pos')?.value || 'bottom';
    const blurOn   = document.getElementById('proc-blur-original')?.checked || false;

    // Actual rendered image dimensions — use getBoundingClientRect for accuracy
    const imgW = img.naturalWidth  || 1280;
    const imgH = img.naturalHeight || 720;
    const rect  = img.getBoundingClientRect();
    // getBoundingClientRect returns 0 if element not visible — fallback to offsetWidth
    const dispW = (rect.width  > 0 ? rect.width  : img.offsetWidth)  || wrap.offsetWidth || 640;
    const dispH = (rect.height > 0 ? rect.height : img.offsetHeight) || Math.round(dispW * imgH / imgW);

    // Lệch của ảnh bên trong khung wrap. ≠0 chỉ khi letterbox (đổi khung 9:16/16:9):
    // ảnh được đặt giữa, chừa viền → overlay phải bám theo vùng ẢNH, không phải wrap.
    const _wrapRectO = wrap.getBoundingClientRect();
    const imgOffX = (rect.width  > 0) ? Math.max(0, Math.round(rect.left - _wrapRectO.left)) : 0;
    const imgOffY = (rect.height > 0) ? Math.max(0, Math.round(rect.top  - _wrapRectO.top )) : 0;

    // font_size and margin_v are % of video height.
    // Apply same % to dispH → preview always matches real video proportionally.
    const fontPct   = parseFloat(document.getElementById('proc-font-size')?.value || 4.5);
    const marginPct = parseFloat(document.getElementById('proc-margin-v')?.value  || 3);
    const scaledFont   = Math.max(6, Math.round(dispH * fontPct   / 100));
    const scaledMargin = Math.max(2, Math.round(dispH * marginPct / 100));

    const colorMap = { white: '#ffffff', yellow: '#ffff00', cyan: '#00ffff' };
    const cssColor = (typeof _getSubtitleColor === 'function')
      ? _getSubtitleColor()
      : (colorMap[color] || '#ffffff');

    // ── Blur zone: covers original subtitle area ──
    const blurH    = parseFloat(document.getElementById('proc-blur-height')?.value || 15) / 100;
    const blurW    = parseFloat(document.getElementById('proc-blur-width')?.value || 80) / 100;
    const blurYOverride = document.getElementById('proc-blur-y')?.value?.trim();
    const blurXOverride = document.getElementById('proc-blur-x')?.value?.trim();
    // Calculate blur position
    const videoH = imgH || 720;
    const subHeightPx = Math.round(videoH * fontPct / 100) + 4;
    const marginVPx   = Math.round(videoH * marginPct / 100);

    let blurCenterY = 0.5;
    if (blurYOverride !== '' && blurYOverride !== undefined) {
      blurCenterY = parseFloat(blurYOverride) / 100;
    } else {
      // Auto: center around subtitle position
      if (pos === 'bottom') {
        const subY = videoH - marginVPx - Math.round(subHeightPx / 2);
        blurCenterY = subY / videoH;
      } else {
        const subY = marginVPx + Math.round(subHeightPx / 2);
        blurCenterY = subY / videoH;
      }
    }

    let blurCenterX = 0.5;
    if (blurXOverride !== '' && blurXOverride !== undefined) {
      blurCenterX = parseFloat(blurXOverride) / 100;
    }

    // Tự động co dãn khi kéo sát/vượt mép biên để tránh bị chặn, kẹt hoặc lỗi toạ độ
    const leftPct = Math.max(0, blurCenterX - blurW / 2);
    const rightPct = Math.min(1, blurCenterX + blurW / 2);
    const bLeft = Math.round(dispW * leftPct);
    const bW = Math.round(dispW * Math.max(0.01, rightPct - leftPct));

    const topPct = Math.max(0, blurCenterY - blurH / 2);
    const bottomPct = Math.min(1, blurCenterY + blurH / 2);
    const bTop = Math.round(dispH * topPct);
    const bH = Math.round(dispH * Math.max(0.01, bottomPct - topPct));

    // Canvas-based pixel blur (matches real FFmpeg blur effect)
    const canvas = document.getElementById('sub-preview-blur-canvas');
    const _posBlur = (el) => {
      el.style.width  = bW + 'px';
      el.style.height = bH + 'px';
      el.style.left   = (imgOffX + bLeft) + 'px';
      el.style.right  = 'auto';
      el.style.top    = (imgOffY + bTop) + 'px';
      el.style.bottom = 'auto';
    };

    const isMainBlurSelected = window._pe2Sel && window._pe2Sel.type === 'blur';
    if (blurOn && canvas && img.complete && img.naturalWidth > 0 && typeof composedFrameCanvas === 'undefined') {
      canvas.width  = bW;
      canvas.height = bH;
      canvas.style.display = 'block';
      _posBlur(canvas);

      // Vùng nguồn theo toạ độ ảnh gốc. Canvas đặt tại (imgOffX+bLeft, imgOffY+bTop)
      // → toạ độ so với chính ảnh là (bLeft, bTop).
      const scaleX  = imgW / (rect.width  || dispW);
      const scaleY  = imgH / (rect.height || dispH);
      const sx = Math.round(bLeft * scaleX);
      const sy = Math.round(bTop  * scaleY);
      const sw = Math.round(bW * scaleX);
      const sh = Math.round(bH * scaleY);

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, bW, bH);
      ctx.filter = 'blur(10px)';
      ctx.drawImage(img, Math.max(0,sx), Math.max(0,sy), Math.max(1,sw), Math.max(1,sh),
                    -10, -10, bW + 20, bH + 20);
      ctx.filter = 'none';
      ctx.fillStyle = 'rgba(0,0,0,0.3)';
      ctx.fillRect(0, 0, bW, bH);
      if (blurEl) {
        blurEl.style.display = 'block';
        _posBlur(blurEl);
        const hasCanvas = canvas && img.complete && img.naturalWidth > 0;
        blurEl.style.background = hasCanvas ? 'transparent' : 'rgba(0,0,0,0.55)';
        blurEl.style.border = 'none';
        blurEl.style.boxShadow = 'none';
        blurEl.style.zIndex = isMainBlurSelected ? '10' : '4';
        if (!blurEl.querySelector('.pe2-handle')) {
          ['nw','n','ne','e','se','s','sw','w'].forEach(function(edge){
            const hd = document.createElement('div');
            hd.className = 'pe2-handle ' + edge;
            hd.dataset.pe2handle = edge;
            blurEl.appendChild(hd);
          });
        }
      }
    } else if (blurOn && blurEl) {
      blurEl.style.display = 'block';
      _posBlur(blurEl);
      blurEl.style.background = 'rgba(0,0,0,0.55)';
      blurEl.style.zIndex = isMainBlurSelected ? '10' : '4';
      if (canvas) canvas.style.display = 'none';
    } else {
      if (blurEl) blurEl.style.display = 'none';
      if (canvas) canvas.style.display = 'none';
    }

    // ── Subtitle text: positioned by margin_v from edge, above blur zone ──
    overlay.style.display    = (burnOn && burnViOn) ? 'block' : 'none';
    overlay.style.fontSize   = scaledFont + 'px';
    overlay.style.color      = cssColor;
    // Outline via text-shadow (matches FFmpeg outline rendering)
    const outlineW = parseInt(document.getElementById('proc-outline-width')?.value || 2);
    const boldOn = document.getElementById('proc-font-bold')?.checked ?? true;
    const shadowSteps = [];
    if (outlineW > 0) {
      for (let dx = -outlineW; dx <= outlineW; dx++) {
        for (let dy = -outlineW; dy <= outlineW; dy++) {
          if (dx !== 0 || dy !== 0) {
            shadowSteps.push(`${dx}px ${dy}px 0px #000`);
          }
        }
      }
    }
    shadowSteps.push('0 2px 4px rgba(0,0,0,0.8)');
    overlay.style.textShadow = shadowSteps.join(',');
    overlay.style.fontWeight  = boldOn ? '700' : '400';
    overlay.style.fontFamily  = 'Arial, sans-serif';
    overlay.style.lineHeight  = '1.3';
    overlay.style.wordBreak   = 'break-word';
    overlay.style.padding     = '0 12px';
    overlay.style.background  = 'none';

    if (pos === 'top') {
      overlay.style.top    = (imgOffY + scaledMargin) + 'px';
      overlay.style.bottom = 'auto';
    } else {
      overlay.style.bottom = (imgOffY + scaledMargin) + 'px';
      overlay.style.top    = 'auto';
    }
    // Giới hạn bề ngang theo vùng ảnh (letterbox dọc→ngang sẽ có viền 2 bên).
    overlay.style.left  = imgOffX + 'px';
    overlay.style.right = imgOffX + 'px';
    overlay.textContent = sample;

    _renderVideoOverlayDom(wrap, imgOffX, imgOffY, dispW, dispH);

    // ── Render extra blur zones on preview ──
    // Remove old extra blur elements
    wrap.querySelectorAll('.extra-blur-zone').forEach(el => el.remove());
    if (window._procExtraBlurZones && window._procExtraBlurZones.length > 0) {
      window._procExtraBlurZones.forEach(zone => {
        const zH = (zone.height || 12) / 100;
        const zY = (zone.position || 50) / 100 - zH / 2;
        const zW = (zone.width || 80) / 100;
        const zXc = ((zone.x === undefined || zone.x === null) ? 50 : zone.x) / 100;
        const zLeftFrac = Math.max(0, Math.min(1 - zW, zXc - zW / 2));
        const ezH = Math.round(dispH * zH);
        const ezW = Math.round(dispW * zW);
        const ezLeft = Math.round(dispW * zLeftFrac);
        const ezTop = Math.round(dispH * Math.max(0, Math.min(1 - zH, zY)));
        const div = document.createElement('div');
        div.className = 'extra-blur-zone';
        div.dataset.zoneId = zone.id;
        
        const isExtraSelected = window._pe2Sel && window._pe2Sel.type === 'extra' && String(window._pe2Sel.id) === String(zone.id);
        const zIndex = isExtraSelected ? 10 : 4;
        div.style.cssText = `position:absolute;left:${imgOffX + ezLeft}px;top:${imgOffY + ezTop}px;width:${ezW}px;height:${ezH}px;background:rgba(0,0,0,0.45);pointer-events:auto;cursor:move;border-radius:2px;backdrop-filter:blur(6px);z-index:${zIndex};border:1px dashed rgba(255,255,255,0.35);`;
        ['nw','n','ne','e','se','s','sw','w'].forEach(function(edge){
          const hd = document.createElement('div');
          hd.className = 'pe2-handle ' + edge;
          hd.dataset.pe2handle = edge;
          div.appendChild(hd);
        });
        wrap.appendChild(div);
      });
    }
    if (typeof window.pe2ApplySelection === 'function') window.pe2ApplySelection();
  }

  async function subPreviewFetchFrame() {
    const source = _getPreviewVideoPath();
    if (!source) { toast('Chưa có video trong hàng chờ hoặc chưa chọn file', 'warning'); return; }

    const ts  = parseFloat(document.getElementById('sub-preview-ts')?.value || 5);
    const img = document.getElementById('sub-preview-img');
    const ph  = document.getElementById('sub-preview-placeholder');
    const btn = document.querySelector('[onclick="subPreviewFetchFrame()"]');

    if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
    if (ph)  ph.textContent = 'Đang tải frame...';

    try {
      let endpoint, body;

      if (source.type === 'file') {
        endpoint = '/api/video_frame';
        body = { video_path: source.val, timestamp: ts };
      } else {
        // URL: find latest downloaded mp4 in Downloaded folder
        endpoint = '/api/video_frame_from_url';
        body = { url: source.val, timestamp: ts };
      }

      const res  = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (data.ok && data.image) {
        if (img) {
          img.onload = () => {
            // ── Detect aspect ratio of source video and auto-apply preset ──
            try {
              const w = img.naturalWidth || 0;
              const h = img.naturalHeight || 0;
              if (w && h) {
                const detected = _classifyAspect(w, h);
                const override = (typeof _getAspectOverride === 'function') ? _getAspectOverride() : 'auto';
                const target   = (override === 'auto') ? detected : override;
                if (target !== window._procActiveAspect) {
                  window._procActiveAspect = target;
                  // Auto-apply matching preset (silent if not yet saved)
                  if (typeof _applyPresetForActiveAspect === 'function') {
                    _applyPresetForActiveAspect({ silent: true });
                  }
                }
                if (typeof _updateAspectBadge === 'function') _updateAspectBadge();
              }

              // (Layout khung/letterbox áp lần cuối sau khối if/else bên dưới,
              //  vì nhánh subtitle có reset img.style.position.)
            } catch (_) {}

            const frameOn = document.getElementById('frame-enabled')?.checked;
            const cv = document.getElementById('frame-preview-canvas');
            if (frameOn) {
              // Frame mode: hide img visually but keep it rendered for naturalWidth
              img.style.display = 'block';
              img.style.position = 'absolute';
              img.style.opacity = '0';
              img.style.pointerEvents = 'none';
              if (cv) cv.style.display = 'block';
              framePreviewUpdate();
            } else {
              // Subtitle mode: show img normally
              img.style.display = 'block';
              img.style.position = '';
              img.style.opacity = '';
              img.style.pointerEvents = '';
              if (cv) cv.style.display = 'none';
              _renderSubOverlay();
            }
            // Áp khung đích / letterbox / nền mờ lần cuối (sau khi style ảnh đã reset),
            // cho cả mode 'auto' lẫn khi chọn 16:9 / 9:16 thủ công.
            if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
          };
          img.src = data.image;
          img.style.display = 'block';
          // Lưu ảnh gốc không có logo để dùng lại cho preview.
          if (data.image && data.image.startsWith('data:image/')) {
            window._rawFrameB64 = data.image.split(',')[1] || null;
          } else {
            window._rawFrameB64 = null;
          }
          // Cập nhật duration từ response nếu có (chỉ cho video file)
          if (data.duration && data.duration > 0) {
            window._pe2Duration = data.duration;
            if (typeof window.pe2SyncPlayhead === 'function') window.pe2SyncPlayhead();
            if (typeof window._pe2RenderRuler === 'function') {
              window._pe2RenderRuler();
            }
          }
        }
        if (ph) ph.style.display = 'none';
        if (data.source === 'thumbnail') {
          toast('📷 Đã lấy thumbnail từ URL', 'success');
        }
      } else {
        if (ph) { ph.style.display = 'block'; ph.textContent = data.error || 'Không lấy được frame'; }
        toast('Không lấy được frame: ' + (data.error || ''), 'error');
      }
    } catch (e) {
      if (ph) { ph.style.display = 'block'; ph.textContent = 'Lỗi: ' + e.message; }
      toast('Lỗi: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '📷 Lấy frame'; }
    }
  }




function subPreviewUpdate() {
    const fsInput = document.getElementById('proc-font-size');
    const fsSlider = document.getElementById('proc-font-size-slider');
    if (fsInput && fsSlider && fsSlider.value !== fsInput.value) {
      fsSlider.value = fsInput.value || 4.5;
    }

    if (document.getElementById('frame-enabled')?.checked) {
      framePreviewUpdate(); // re-draw canvas including subtitle
    } else {
      _renderSubOverlay();
    }
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  }
  function ovSelectLayer(id, open, skipSubUpdate) {
    const ov = _ovFind(id);
    if (!ov) return;
    const wasSelected = window._pe2Sel && window._pe2Sel.type === 'overlay' && String(window._pe2Sel.id) === String(ov.id);
    let needsRender = !wasSelected;
    window._videoOverlays.forEach(x => {
      if (!open) return;
      const shouldOpen = String(x.id) === String(id);
      if (x.open !== shouldOpen) needsRender = true;
      x.open = shouldOpen;
    });
    window._pe2Sel = { type: 'overlay', id: ov.id };
    if (open && !ov.open) {
      ov.open = true;
      needsRender = true;
    }
    if (needsRender) ovRenderLayerList();
    if (!skipSubUpdate) {
      if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
      if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
    }
    if (typeof pe2ApplySelection === 'function') pe2ApplySelection();
  }
  function ovToggleLayer(id) {
    const ov = _ovFind(id);
    if (!ov) return;
    const next = !ov.open;
    window._videoOverlays.forEach(x => { x.open = false; });
    ov.open = next;
    window._pe2Sel = { type: 'overlay', id: ov.id };
    ovRenderLayerList();
    if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
    if (typeof pe2ApplySelection === 'function') pe2ApplySelection(true);
  }
  function ovRemoveLayer(id) {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    window._videoOverlays = (window._videoOverlays || []).filter(x => String(x.id) !== String(id));
    if (window._pe2Sel && window._pe2Sel.type === 'overlay' && String(window._pe2Sel.id) === String(id)) window._pe2Sel = null;
    ovRenderLayerList();
    if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
  }
  function ovUpdateLayer(id, key, value, soft) {
    const ov = _ovFind(id);
    if (!ov) return;
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    if (key === 'enabled') ov.enabled = !!value;
    else if (key === 'text') ov.text = String(value ?? '');
    else if (key === 'color' || key === 'box_color') ov[key] = _ovHexValue(value, ov[key] || '#000000');
    else if (key === 'start_sec' || key === 'end_sec') ov[key] = _ovSecValue(value);
    else if (key === 'size_pct') ov.size_pct = _ovClamp(value, 0.01, 0.30);
    else if (key === 'weight') ov.weight = Math.max(300, Math.min(900, parseInt(value, 10) || 700));
    else if (key === 'padding_pct') ov.padding_pct = _ovClamp(value, 0, 1.5);
    else if (key === 'box_opacity' || key === 'opacity') ov[key] = _ovClamp(value, 0, 1);
    else if (key === 'radius_pct') ov.radius_pct = _ovClamp(value, 0, 0.5);
    else if (key === 'width_pct' || key === 'height_pct') ov[key] = _ovClamp(value, 0.01, 1);
    else if (key === 'x_pct' || key === 'y_pct') ov[key] = _ovClamp(value, 0, 1);
    _ovSyncHidden();
    if (!soft) ovRenderLayerList();
    if (typeof subPreviewUpdate === 'function') subPreviewUpdate();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  }
  window.addEventListener('resize', () => {
    if (document.getElementById('sub-preview-img')?.style.display !== 'none') _renderSubOverlay();
    framePreviewUpdate();
  });
  function _frameAnimLoop(ts) {
    const enabled = document.getElementById('frame-enabled')?.checked;
    if (!enabled || !window._frameLogoIsGif || !window._frameLogoImg) {
      window._frameAnimRAF = null;
      return;
    }
    if (!window._frameAnimLast || (ts - window._frameAnimLast) >= 50) { // ~20 fps
      window._frameAnimLast = ts;
      const srcImg = document.getElementById('sub-preview-img');
      if (srcImg && srcImg.complete && srcImg.naturalWidth) {
        _drawFramePreview(srcImg);
      }
    }
    window._frameAnimRAF = requestAnimationFrame(_frameAnimLoop);
  }
  function _frameStartGifRestart() {
    if (window._frameGifRestartTimer || !window._frameLogoIsGif) return;
    const reload = () => {
      const src = window._frameLogoSrc || window._frameLogoImg?.src || '';
      if (!src || !document.getElementById('frame-enabled')?.checked) return;
      const fresh = new Image();
      fresh.onload = () => {
        window._frameLogoImg = fresh;
        framePreviewUpdate();
      };
      fresh.src = _frameGifFreshSrc(src);
    };
    window._frameGifRestartTimer = setInterval(reload, 5000);
  }
  function _setFrameLogo(img, isGif) {
    window._frameLogoImg = img;
    window._frameLogoSrc = img?.src || '';
    window._frameLogoIsGif = !!isGif;
    if (isGif) _frameStartAnim(); else _frameStopAnim();
    framePreviewUpdate();
  }
  function framePreviewUpdate() {
    if (!document.getElementById('frame-enabled')?.checked) return;
    const srcImg = document.getElementById('sub-preview-img');
    if (!srcImg || !srcImg.complete || !srcImg.naturalWidth) return;
    _drawFramePreview(srcImg);
  }
  function _drawFramePreview(srcImg) {
    const canvas = document.getElementById('frame-preview-canvas');
    if (!canvas) return;

    const titleEnabled = document.getElementById('frame-title-enabled')?.checked ?? true;
    const title       = titleEnabled ? (document.getElementById('frame-title')?.value || '') : '';
    const hasTitle    = titleEnabled && title.trim();
    const titleSizePct= parseFloat(document.getElementById('frame-title-size')?.value || 5);
    const titleWeight = Math.max(300, Math.min(900, parseInt(document.getElementById('frame-title-weight')?.value || 400, 10) || 400));
    const titleBarPct = parseFloat(document.getElementById('frame-title-bar-h')?.value || 6);
    const titleMarginXPct = parseFloat(document.getElementById('frame-title-margin-x')?.value || 5);
    const titleXPct   = parseFloat(document.getElementById('frame-title-x')?.value || 50) / 100;
    const titleYPct   = parseFloat(document.getElementById('frame-title-y')?.value || 50) / 100;
    const titleColor  = document.getElementById('frame-title-color')?.value || '#000000';
    const titleColor2 = document.getElementById('frame-title-color-2')?.value || '#ff0000';
    const titleSplit  = document.getElementById('frame-title-split-color')?.checked ?? true;
    const blurWPct    = parseFloat(document.getElementById('frame-blur-w')?.value || 15) / 100;
    const blurOpacity = parseFloat(document.getElementById('frame-blur-opacity')?.value || 60) / 100;
    const logoSizeRaw = parseFloat(document.getElementById('frame-logo-size')?.value);
    const logoSizePct = (isNaN(logoSizeRaw) || logoSizeRaw <= 0 ? (document.getElementById('frame-logo-path')?.value ? 12 : 0) : logoSizeRaw) / 100;
    const logoTopPct  = parseFloat(document.getElementById('frame-logo-top')?.value || 3) / 100;
    const logoLeftPct = parseFloat(document.getElementById('frame-logo-left')?.value || 3) / 100;
    const logoRadiusPct = parseFloat(document.getElementById('frame-logo-radius')?.value ?? 50) / 100;
    const blurMode    = document.querySelector('input[name="frame-blur-mode"]:checked')?.value || 'overlay';
    const blurTopPct    = parseFloat(document.getElementById('frame-blur-top')?.value || 0) / 100;
    const blurBottomPct = parseFloat(document.getElementById('frame-blur-bottom')?.value || 0) / 100;

    const srcNW = srcImg.naturalWidth  || 640;
    const srcNH = srcImg.naturalHeight || 360;
    const wrap  = document.getElementById('sub-preview-wrap');
    // Dùng độ phân giải video làm gốc vẽ (ổn định, không phụ thuộc kích thước hiển thị)
    const wrapW = srcImg.naturalWidth || wrap?.offsetWidth || 640;

    // Title bar chỉ chiếm chỗ khi thật sự có nội dung tiêu đề.
    const titleFontPx = hasTitle ? Math.max(10, Math.round(wrapW * titleSizePct / 100)) : 0;
    const sourceDisplayH = Math.round(wrapW * srcNH / srcNW);
    const titleBarH = hasTitle
      ? Math.max(40, Math.round(sourceDisplayH * Math.max(3, Math.min(20, titleBarPct)) / 100))
      : 0;

    // Side blur width in preview pixels
    const sideW = Math.round(wrapW * blurWPct);

    let cW, cH, vidX, vidY, vidW, vidH;

    if (blurMode === 'expand') {
      vidW = Math.max(10, wrapW - 2 * sideW);
      vidH = Math.round(vidW * srcNH / srcNW);
      vidX = sideW;
      vidY = titleBarH;
      cW   = wrapW;
      cH   = titleBarH + vidH;
    } else {
      vidW = wrapW;
      vidH = Math.round(wrapW * srcNH / srcNW);
      vidX = 0;
      vidY = 0;
      cW   = wrapW;
      cH   = vidH;
    }

    canvas.width  = cW;
    canvas.height = cH;

    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, cW, cH);
    let frameInteractiveSource = {};

    function _drawLayerVideo(c) {
      c.drawImage(srcImg, vidX, vidY, vidW, vidH);
    }

    function _drawLayerFrame(c) {
      if (sideW > 0 && blurOpacity > 0) {
        if (blurMode === 'expand') {
          c.save();
          c.filter = 'blur(12px)';
          c.drawImage(srcImg, 0, 0, Math.min(20, srcNW), srcNH, 0, vidY, sideW + 16, vidH);
          c.restore();
          c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
          c.fillRect(0, vidY, sideW, vidH);

          c.save();
          c.filter = 'blur(12px)';
          c.drawImage(srcImg, Math.max(0, srcNW - 20), 0, Math.min(20, srcNW), srcNH, cW - sideW - 16, vidY, sideW + 16, vidH);
          c.restore();
          c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
          c.fillRect(cW - sideW, vidY, sideW, vidH);
        } else {
          c.save();
          c.beginPath();
          c.rect(0, vidY, sideW, vidH);
          c.clip();
          c.filter = 'blur(12px)';
          c.drawImage(srcImg, vidX - 8, vidY, vidW + 16, vidH);
          c.restore();
          c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
          c.fillRect(0, vidY, sideW, vidH);

          c.save();
          c.beginPath();
          c.rect(cW - sideW, vidY, sideW, vidH);
          c.clip();
          c.filter = 'blur(12px)';
          c.drawImage(srcImg, vidX - 8, vidY, vidW + 16, vidH);
          c.restore();
          c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
          c.fillRect(cW - sideW, vidY, sideW, vidH);
        }
      }

      if (blurTopPct > 0 && blurOpacity > 0) {
        const topH = Math.round(vidH * blurTopPct);
        c.save();
        c.beginPath();
        c.rect(vidX, vidY, vidW, topH);
        c.clip();
        c.filter = 'blur(12px)';
        c.drawImage(srcImg, vidX - 8, vidY - 8, vidW + 16, topH + 16);
        c.restore();
        c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
        c.fillRect(vidX, vidY, vidW, topH);
      }

      if (blurBottomPct > 0 && blurOpacity > 0) {
        const bottomH = Math.round(vidH * blurBottomPct);
        const bottomY = vidY + vidH - bottomH;
        c.save();
        c.beginPath();
        c.rect(vidX, bottomY, vidW, bottomH);
        c.clip();
        c.filter = 'blur(12px)';
        c.drawImage(srcImg, vidX - 8, bottomY - 8, vidW + 16, bottomH + 16);
        c.restore();
        c.fillStyle = `rgba(0,0,0,${blurOpacity})`;
        c.fillRect(vidX, bottomY, vidW, bottomH);
      }

      if (hasTitle && titleBarH > 0) {
        c.fillStyle = '#ffffff';
        c.fillRect(0, 0, cW, titleBarH);
        frameInteractiveSource.titleBar = { x: 0, y: 0, w: cW, h: titleBarH };
      }

      if (hasTitle) {
        c.font = `${titleWeight} ${titleFontPx}px Arial, sans-serif`;
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        const titleMarginX = cW * Math.max(0, Math.min(40, titleMarginXPct)) / 100;
        const maxW = Math.max(titleFontPx, cW - titleMarginX * 2);
        const upper = title.toUpperCase();
        let titleCenterX = Math.max(titleMarginX, Math.min(cW - titleMarginX, cW * Math.max(0, Math.min(1, titleXPct))));
        const titleCenterY = Math.max(titleFontPx / 2, Math.min(titleBarH - titleFontPx / 2, titleBarH * Math.max(0, Math.min(1, titleYPct))));

        const words = upper.split(' ');
        let lines = [], line = '';
        for (const w of words) {
          const test = line ? line + ' ' + w : w;
          if (c.measureText(test).width > maxW && line) { lines.push(line); line = w; }
          else line = test;
        }
        if (line) lines.push(line);
        const lH = titleFontPx * 1.3;
        const titleBlockH = lines.length * lH;
        const startY = titleCenterY - titleBlockH / 2 + lH / 2;
        const lineWidths = lines.map(l => c.measureText(l).width);
        const titleBlockW = Math.min(maxW, Math.max(...lineWidths, titleFontPx));
        titleCenterX = Math.max(titleMarginX + titleBlockW / 2, Math.min(cW - titleMarginX - titleBlockW / 2, titleCenterX));

        if (titleSplit && upper.length > 1) {
          let part1, part2;
          if (upper.includes('|')) {
            const p = upper.split('|');
            part1 = p[0].trim();
            part2 = p.slice(1).join('|').trim();
          } else {
            const ws = upper.split(/\s+/).filter(Boolean);
            if (ws.length >= 2) {
              const mid = Math.floor(ws.length / 2);
              part1 = ws.slice(0, mid).join(' ');
              part2 = ws.slice(mid).join(' ');
            } else {
              part1 = upper; part2 = '';
            }
          }
          const fullText = part2 ? part1 + ' ' + part2 : part1;
          const rwWords = fullText.split(' ');
          const rwLines = [];
          let rl = '';
          for (const w of rwWords) {
            const test = rl ? rl + ' ' + w : w;
            if (c.measureText(test).width > maxW && rl) { rwLines.push(rl); rl = w; }
            else rl = test;
          }
          if (rl) rwLines.push(rl);
          const sY = titleCenterY - (rwLines.length * lH) / 2 + lH / 2;
          const part1Words = part1.split(' ').length;
          let wordIdx = 0;

          rwLines.forEach((l, i) => {
            const lineWords = l.split(' ');
            const widths = lineWords.map(w => c.measureText(w).width);
            const spaceW = c.measureText(' ').width;
            const totalW = widths.reduce((a, b) => a + b, 0) + spaceW * (lineWords.length - 1);
            let x = titleCenterX - totalW / 2;
            const y = sY + i * lH;
            lineWords.forEach((w, j) => {
              c.fillStyle = (wordIdx < part1Words) ? titleColor : titleColor2;
              c.textAlign = 'left';
              c.fillText(w, x, y);
              x += widths[j] + spaceW;
              wordIdx++;
            });
          });
          c.textAlign = 'center';
        } else {
          c.fillStyle = titleColor;
          lines.forEach((l, i) => c.fillText(l, titleCenterX, startY + i * lH));
        }
        const titleBounds = {
          x: titleCenterX - titleBlockW / 2 - titleFontPx * 0.25,
          y: titleCenterY - titleBlockH / 2 - titleFontPx * 0.15,
          w: titleBlockW + titleFontPx * 0.5,
          h: titleBlockH + titleFontPx * 0.3
        };
        frameInteractiveSource.title = titleBounds;
        if (window._pe2Sel && window._pe2Sel.type === 'frame-title') {
          _drawCanvasSelection(c, titleBounds.x, titleBounds.y, titleBounds.w, titleBounds.h, true, true);
        }
      }
    }

    function _drawLayerLogo(c) {
      if (window._frameLogoImg && logoSizePct > 0) {
        const logoNW = window._frameLogoImg.naturalWidth  || window._frameLogoImg.width;
        const logoNH = window._frameLogoImg.naturalHeight || window._frameLogoImg.height;
        const logoAR = logoNW / (logoNH || 1);
        const lH = Math.max(8, Math.round(vidH * logoSizePct));
        const lW = Math.round(lH * logoAR);
        const lX = vidX + Math.round(vidW * logoLeftPct);
        const titleOffset = (blurMode === 'overlay' && hasTitle) ? titleBarH : 0;
        const lY = vidY + titleOffset + Math.round(vidH * logoTopPct);
        const r  = Math.round(Math.min(lW, lH) * logoRadiusPct);
        c.save();
        c.beginPath();
        _roundRect(c, lX, lY, lW, lH, r);
        c.clip();
        c.drawImage(window._frameLogoImg, lX, lY, lW, lH);
        c.restore();
        frameInteractiveSource.logo = { x: lX, y: lY, w: lW, h: lH };
        if (window._pe2Sel && window._pe2Sel.type === 'frame-logo') {
          _drawCanvasSelection(c, lX, lY, lW, lH, true, false);
        }
      }
    }

    // ── Execute layer drawing in configured order (bottom to top) ──
    const layerOrder = window._pe2LayerOrder || ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'];
    const trackVis = window._pe2TrackVisibility || {};

    layerOrder.forEach(layerId => {
      if (trackVis[layerId] === false) return;
      if (layerId === 'video') {
        _drawLayerVideo(ctx);
      } else if (layerId === 'frame') {
        _drawLayerFrame(ctx);
      } else if (layerId === 'blur') {
        if (typeof _drawBlurZonesOnCanvas === 'function') {
          _drawBlurZonesOnCanvas(ctx, vidX, vidY, vidW, vidH);
        }
      } else if (layerId === 'logo') {
        _drawLayerLogo(ctx);
      } else if (layerId === 'overlays') {
        if (typeof _drawVideoOverlaysOnCanvas === 'function') {
          _drawVideoOverlaysOnCanvas(ctx, vidX, vidY, vidW, vidH);
        }
      } else if (layerId === 'subs') {
        if (typeof _drawSubtitleOnlyOnCanvas === 'function') {
          const subBounds = _drawSubtitleOnlyOnCanvas(ctx, cW, cH, vidX, vidY, vidW, vidH);
          if (subBounds) frameInteractiveSource.sub = subBounds;
        }
      }
    });

    // Compose in source space first, then place the complete foreground into
    // Compose in source space first, then place the complete foreground into
    // the selected output aspect. This is the same order used by FFmpeg.
    const aspectValue = document.getElementById('proc-preview-aspect')?.value || 'auto';
    const sourceIsVertical = srcNH > srcNW;
    const isForced = (aspectValue === '16x9' || aspectValue === '9x16');
    const targetAspect = isForced ? aspectValue : (sourceIsVertical ? '9x16' : '16x9');
    const shouldConvert = isForced && (
      (aspectValue === '9x16' && !sourceIsVertical) ||
      (aspectValue === '16x9' && sourceIsVertical)
    );

    let finalCW = cW;
    let finalCH = cH;
    let finalVidX = vidX;
    let finalVidY = vidY;
    let finalVidW = vidW;
    let finalVidH = vidH;
    let finalTitleBarH = titleBarH;
    let fgScale = 1;
    let fgX = 0;
    let fgY = 0;

    if (shouldConvert) {
      const composed = document.createElement('canvas');
      composed.width = cW;
      composed.height = cH;
      composed.getContext('2d').drawImage(canvas, 0, 0);

      finalCW = targetAspect === '9x16' ? 1080 : 1920;
      finalCH = targetAspect === '9x16' ? 1920 : 1080;
      canvas.width = finalCW;
      canvas.height = finalCH;
      const outCtx = canvas.getContext('2d');
      outCtx.fillStyle = '#000';
      outCtx.fillRect(0, 0, finalCW, finalCH);

      if (document.getElementById('proc-aspect-blur-bg')?.checked) {
        const coverScale = Math.max(finalCW / srcNW, finalCH / srcNH) * 1.12;
        const bgW = srcNW * coverScale;
        const bgH = srcNH * coverScale;
        outCtx.save();
        outCtx.filter = 'blur(28px) brightness(70%)';
        outCtx.drawImage(srcImg, (finalCW - bgW) / 2, (finalCH - bgH) / 2, bgW, bgH);
        outCtx.restore();
      }

      fgScale = Math.min(finalCW / cW, finalCH / cH);
      const fgW = cW * fgScale;
      const fgH = cH * fgScale;
      fgX = (finalCW - fgW) / 2;
      fgY = (finalCH - fgH) / 2;
      outCtx.drawImage(composed, fgX, fgY, fgW, fgH);

      finalVidX = fgX + vidX * fgScale;
      finalVidY = fgY + vidY * fgScale;
      finalVidW = vidW * fgScale;
      finalVidH = vidH * fgScale;
      finalTitleBarH = titleBarH * fgScale;
    }

    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.zIndex = '2';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.maxWidth = '100%';
    if (wrap) {
      wrap.style.aspectRatio = finalCW + ' / ' + finalCH;
      wrap.dataset.letterbox = shouldConvert ? '1' : '';
    }
    window._frameGeom = {
      titleBarH: finalTitleBarH,
      vidX: finalVidX,
      vidY: finalVidY,
      vidW: finalVidW,
      vidH: finalVidH,
      cW: finalCW,
      cH: finalCH,
      srcCW: cW,
      srcCH: cH,
      srcVidX: vidX,
      srcVidY: vidY,
      srcVidW: vidW,
      srcVidH: vidH,
      srcTitleBarH: titleBarH,
      fgScale,
      fgX,
      fgY
    };
    window._frameInteractiveSource = frameInteractiveSource;
    window._frameInteractive = Object.fromEntries(Object.entries(frameInteractiveSource).map(([key, box]) => ([
      key,
      {
        x: fgX + box.x * fgScale,
        y: fgY + box.y * fgScale,
        w: box.w * fgScale,
        h: box.h * fgScale
      }
    ])));
  }
  function _onPreviewAspectChange() {
    const sel = document.getElementById('proc-preview-aspect');
    const value = sel?.value || 'auto';
    try { localStorage.setItem(_PROC_PREVIEW_ASPECT_K, value); } catch (_) {}

    // Resolve effective aspect:
    //  - 'auto' → dùng aspect của video frame đã load (nếu có), mặc định 16x9
    //  - '16x9' / '9x16' → ép buộc
    let aspect = value;
    if (value === 'auto') {
      const img = document.getElementById('sub-preview-img');
      if (img && img.naturalWidth && img.naturalHeight) {
        aspect = (img.naturalHeight > img.naturalWidth) ? '9x16' : '16x9';
      } else {
        aspect = '16x9';  // default fallback when no video loaded yet
      }
    }
    const isVertical = aspect === '9x16';

    const subWrap   = document.getElementById('sub-preview-wrap');

    // Khung xem trước phản ánh ĐÚNG khung sẽ xuất:
    //  - 'auto' (Tự nhận diện): giữ tỉ lệ video gốc, ảnh lấp đầy khung.
    //  - '16x9' / '9x16' chọn thủ công: nếu HƯỚNG nguồn khác mode đích thì hiển thị
    //    khung đích kèm viền (letterbox) — khớp với cách backend scale+pad khi xuất.
    //    Nếu nguồn đã đúng hướng thì giữ khung gốc (backend cũng không convert).
    const _imgEl = document.getElementById('sub-preview-img');
    const _haveDims = !!(_imgEl && _imgEl.naturalWidth && _imgEl.naturalHeight);
    const _srcW = _haveDims ? _imgEl.naturalWidth  : 16;
    const _srcH = _haveDims ? _imgEl.naturalHeight : 9;
    const _srcIsVertical = _srcH > _srcW;
    const _origAspect = _haveDims ? (_srcW + ' / ' + _srcH) : '16 / 9';

    const _forced = (value === '16x9' || value === '9x16');
    const _shouldConvert = _forced && (
      (aspect === '9x16' && !_srcIsVertical) ||
      (aspect === '16x9' &&  _srcIsVertical)
    );
    const _blurBg = document.getElementById('proc-aspect-blur-bg')?.checked || false;
    const _bgEl = document.getElementById('sub-preview-bgblur');
    const _frameEnabled = document.getElementById('frame-enabled')?.checked || false;

    if (subWrap) {
      if (_shouldConvert) {
        subWrap.style.aspectRatio = isVertical ? '9 / 16' : '16 / 9';
        subWrap.dataset.letterbox = '1';
        if (_imgEl) {
          _imgEl.style.width     = 'auto';
          _imgEl.style.height    = 'auto';
          _imgEl.style.maxWidth  = '100%';
          _imgEl.style.maxHeight = '100%';
          _imgEl.style.objectFit = 'contain';
          _imgEl.style.position  = _frameEnabled ? 'absolute' : 'relative';
          _imgEl.style.inset     = _frameEnabled ? '0' : '';
          _imgEl.style.opacity   = _frameEnabled ? '0' : '';
          _imgEl.style.pointerEvents = _frameEnabled ? 'none' : '';
          _imgEl.style.zIndex    = '1';
        }
        // Nền mờ: hiện ảnh nền (mờ) lấp viền thay cho nền đen.
        if (_bgEl) {
          if (!_frameEnabled && _blurBg && _imgEl && _imgEl.src && _imgEl.src !== window.location.href) {
            _bgEl.src = _imgEl.src;
            _bgEl.style.display = 'block';
          } else {
            _bgEl.style.display = 'none';
            _bgEl.removeAttribute('src');
          }
        }
      } else {
        subWrap.style.aspectRatio = _origAspect;
        subWrap.dataset.letterbox = '';
        if (_imgEl) {
          _imgEl.style.width     = '100%';
          _imgEl.style.height    = '';
          _imgEl.style.maxWidth  = '';
          _imgEl.style.maxHeight = '';
          _imgEl.style.objectFit = '';
          _imgEl.style.position  = _frameEnabled ? 'absolute' : '';
          _imgEl.style.inset     = _frameEnabled ? '0' : '';
          _imgEl.style.opacity   = _frameEnabled ? '0' : '';
          _imgEl.style.pointerEvents = _frameEnabled ? 'none' : '';
          _imgEl.style.zIndex    = '';
        }
        if (_bgEl) { _bgEl.style.display = 'none'; _bgEl.removeAttribute('src'); }
      }
    }
    // Sync với window._procActiveAspect để các logic khác dùng
    window._procActiveAspect = aspect;
    if (typeof _updateAspectBadge === 'function') _updateAspectBadge();

    // Re-render preview overlays
    if (typeof _renderSubOverlay === 'function') _renderSubOverlay();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
  }
  function frameToggle() {
    const enabled = document.getElementById('frame-enabled')?.checked;
    const controls = document.getElementById('frame-controls');
    if (controls) controls.style.display = enabled ? 'block' : 'none';

    const img    = document.getElementById('sub-preview-img');
    const canvas = document.getElementById('frame-preview-canvas');
    const blurC  = document.getElementById('sub-preview-blur-canvas');
    const blurD  = document.getElementById('sub-preview-blur');
    const text   = document.getElementById('sub-preview-text');

    if (enabled) {
      // Frame mode: hide subtitle DOM overlays (subtitle drawn on canvas instead)
      if (blurC)  blurC.style.display  = 'none';
      if (blurD)  blurD.style.display  = 'none';
      if (text)   text.style.display   = 'none';
      if (canvas) {
        canvas.style.display = 'block';
        canvas.style.position = 'absolute';
        canvas.style.inset = '0';
        canvas.style.zIndex = '2';
      }
      const bg = document.getElementById('sub-preview-bgblur');
      if (bg) {
        bg.style.display = 'none';
        bg.removeAttribute('src');
      }
      // Bỏ các div vùng che DOM còn sót (đã thêm ở chế độ phụ đề) để không bị
      // hiển thị 2 lớp với vùng che vẽ trên canvas khung.
      const _w = document.getElementById('sub-preview-wrap');
      if (_w) _w.querySelectorAll('.extra-blur-zone,.video-overlay-el').forEach(el => el.remove());
      window._pe2Sel = null;
      // Keep img rendered but invisible (needed for naturalWidth/drawImage)
      if (img && img.src && img.naturalWidth) {
        img.style.display = 'block';
        img.style.position = 'absolute';
        img.style.opacity = '0';
        img.style.pointerEvents = 'none';
      }
      framePreviewUpdate();
      _frameStartAnim();   // GIF logo chạy lại khi bật khung
    } else {
      // Subtitle mode: hide frame canvas, show img + overlays
      _frameStopAnim();    // dừng vòng lặp GIF khi tắt khung
      if (canvas) canvas.style.display = 'none';
      if (img && img.src && img.src !== window.location.href) {
        img.style.display = 'block';
        img.style.position = '';
        img.style.inset = '';
        img.style.opacity = '';
        img.style.pointerEvents = '';
        // Trả lại tỉ lệ khung theo video (bỏ tỉ lệ do khung video áp vào)
        if (typeof _onPreviewAspectChange === 'function') _onPreviewAspectChange();
        _renderSubOverlay();
      }
    }
  }


  // ── Track & Layer Management System ──
  const TRACK_DEFINITIONS = {
    subs:     { name: 'Phụ đề video', icon: '📝', desc: 'Phụ đề dịch và phụ đề gốc', tab: 'subs' },
    overlays: { name: 'Chữ / Khối / Ảnh', icon: '🔤', desc: 'Các text, khối nền, sticker và ảnh chèn', tab: 'overlay' },
    blur:     { name: 'Vùng che mờ', icon: '🌫', desc: 'Khối làm mờ chữ gốc và vùng che bổ sung', tab: 'overlay' },
    logo:     { name: 'Logo & Watermark', icon: '🖼', desc: 'Ảnh logo / watermark nhận diện thương hiệu', tab: 'frame' },
    frame:    { name: 'Khung & Tiêu đề', icon: '🔲', desc: 'Thanh tiêu đề và hiệu ứng mờ viền', tab: 'frame' },
    video:    { name: 'Video gốc', icon: '🎬', desc: 'Khung hình gốc của video (nền dưới cùng)', tab: 'subs' }
  };

  window.TRACK_DEFINITIONS = TRACK_DEFINITIONS;
  window._pe2LayerOrder = window._pe2LayerOrder || ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'];
  window._pe2TrackVisibility = window._pe2TrackVisibility || {
    video: true,
    frame: true,
    blur: true,
    logo: true,
    overlays: true,
    subs: true
  };

  function _saveTrackSettings() {
    try {
      localStorage.setItem('pe2_layer_order', JSON.stringify(window._pe2LayerOrder));
      localStorage.setItem('pe2_track_visibility', JSON.stringify(window._pe2TrackVisibility));
    } catch (_) {}
  }

  function _loadTrackSettings() {
    try {
      const savedOrder = JSON.parse(localStorage.getItem('pe2_layer_order') || 'null');
      if (Array.isArray(savedOrder) && savedOrder.length >= 4) {
        window._pe2LayerOrder = savedOrder;
      }
      const savedVis = JSON.parse(localStorage.getItem('pe2_track_visibility') || 'null');
      if (savedVis && typeof savedVis === 'object') {
        window._pe2TrackVisibility = savedVis;
      }
    } catch (_) {}
  }
  _loadTrackSettings();

  window.pe2MoveTrackUp = function(layerId) {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    const arr = window._pe2LayerOrder || ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'];
    const idx = arr.indexOf(layerId);
    if (idx < arr.length - 1 && idx >= 0) {
      const temp = arr[idx];
      arr[idx] = arr[idx + 1];
      arr[idx + 1] = temp;
      window._pe2LayerOrder = arr;
      _saveTrackSettings();
      if (window.pe2RenderTracksUI) window.pe2RenderTracksUI();
      if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
      if (window.pe2RenderRanges) window.pe2RenderRanges();
      if (typeof toast === 'function') toast('✓ Đã đưa lớp [' + (TRACK_DEFINITIONS[layerId]?.name || layerId) + '] lên trên', 'info', { duration: 1500 });
    }
  };

  window.pe2MoveTrackDown = function(layerId) {
    if (!window._pe2Restoring && window.pe2PushUndo) window.pe2PushUndo();
    const arr = window._pe2LayerOrder || ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'];
    const idx = arr.indexOf(layerId);
    if (idx > 0) {
      const temp = arr[idx];
      arr[idx] = arr[idx - 1];
      arr[idx - 1] = temp;
      window._pe2LayerOrder = arr;
      _saveTrackSettings();
      if (window.pe2RenderTracksUI) window.pe2RenderTracksUI();
      if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
      if (window.pe2RenderRanges) window.pe2RenderRanges();
      if (typeof toast === 'function') toast('✓ Đã đưa lớp [' + (TRACK_DEFINITIONS[layerId]?.name || layerId) + '] xuống dưới', 'info', { duration: 1500 });
    }
  };

  window.pe2ToggleTrack = function(layerId) {
    window._pe2TrackVisibility = window._pe2TrackVisibility || {};
    window._pe2TrackVisibility[layerId] = window._pe2TrackVisibility[layerId] === false ? true : false;
    _saveTrackSettings();
    if (window.pe2RenderTracksUI) window.pe2RenderTracksUI();
    if (typeof framePreviewUpdate === 'function') framePreviewUpdate();
    if (window.pe2RenderRanges) window.pe2RenderRanges();
  };

  window.pe2RenderTracksUI = function() {
    const container = document.getElementById('pe2-tracks-list');
    if (!container) return;
    const arr = [...(window._pe2LayerOrder || ['video', 'frame', 'blur', 'logo', 'overlays', 'subs'])].reverse(); // Display top layer first
    const vis = window._pe2TrackVisibility || {};

    container.innerHTML = arr.map((layerId, displayIdx) => {
      const def = TRACK_DEFINITIONS[layerId] || { name: layerId, icon: '📦', desc: '', tab: 'subs' };
      const isVisible = vis[layerId] !== false;
      const actualIdx = (window._pe2LayerOrder || []).indexOf(layerId);
      const isTop = actualIdx === (window._pe2LayerOrder || []).length - 1;
      const isBottom = actualIdx === 0;

      let extraInfo = '';
      if (layerId === 'overlays') {
        const count = (window._videoOverlays || []).length;
        extraInfo = `<span style="font-size:10px;background:rgba(99,102,241,0.15);color:#818cf8;padding:2px 6px;border-radius:4px">${count} phần tử</span>`;
      } else if (layerId === 'logo') {
        const hasLogo = !!(document.getElementById('frame-logo-path')?.value);
        extraInfo = hasLogo ? `<span style="font-size:10px;background:rgba(34,197,94,0.15);color:#22c55e;padding:2px 6px;border-radius:4px">Đã chọn</span>` : `<span style="font-size:10px;color:var(--text-muted)">Chưa có</span>`;
      } else if (layerId === 'subs') {
        const hasSample = !!(document.getElementById('sub-preview-sample')?.value);
        extraInfo = hasSample ? `<span style="font-size:10px;background:rgba(34,197,94,0.15);color:#22c55e;padding:2px 6px;border-radius:4px">Bật</span>` : '';
      }

      return `
        <div class="pe2-track-card ${isVisible ? '' : 'disabled'}" data-track-id="${layerId}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--bg2);border:1px solid ${isVisible ? 'var(--border)' : 'rgba(255,255,255,0.04)'};border-radius:8px;margin-bottom:8px;transition:all 0.2s">
          <span style="font-size:18px;line-height:1;display:flex;align-items:center;justify-content:center;width:28px;height:28px;background:var(--bg);border-radius:6px">${def.icon}</span>
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;gap:6px">
              <strong style="font-size:13px;color:var(--text)">${def.name}</strong>
              ${extraInfo}
            </div>
            <div style="font-size:11px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${def.desc}</div>
          </div>
          <div style="display:flex;align-items:center;gap:4px">
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 6px;height:28px;line-height:1;border-radius:4px" 
              onclick="pe2MoveTrackUp('${layerId}')" title="Đưa lên trên (ưu tiên hiển thị trên)" ${isTop ? 'disabled style="opacity:0.3;padding:0 6px;height:28px"' : ''}>
              ▲
            </button>
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 6px;height:28px;line-height:1;border-radius:4px" 
              onclick="pe2MoveTrackDown('${layerId}')" title="Đưa xuống dưới (hiển thị dưới)" ${isBottom ? 'disabled style="opacity:0.3;padding:0 6px;height:28px"' : ''}>
              ▼
            </button>
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 8px;height:28px;font-size:14px" 
              onclick="pe2ToggleTrack('${layerId}')" title="${isVisible ? 'Ẩn lớp này' : 'Hiện lớp này'}">
              ${isVisible ? '👁' : '🚫'}
            </button>
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 8px;height:28px;font-size:11px" 
              onclick="pe2Tool('${def.tab}')" title="Mở cài đặt của lớp này">
              ⚙
            </button>
          </div>
        </div>
      `;
    }).join('');
  };

if (typeof subPreviewUpdate !== "undefined") window.subPreviewUpdate = subPreviewUpdate;
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { if (window.pe2RenderTracksUI) window.pe2RenderTracksUI(); });
} else {
  if (window.pe2RenderTracksUI) window.pe2RenderTracksUI();
}


function procParseContentAspect(value) {
  const m = String(value || '').match(/^\s*(\d+(?:[.,]\d+)?)\s*[:xX/×]\s*(\d+(?:[.,]\d+)?)\s*$/);
  if (!m) return null;
  const w = Number(m[1].replace(',', '.')), h = Number(m[2].replace(',', '.'));
  const ratio = w / h;
  return w > 0 && h > 0 && Number.isFinite(w) && Number.isFinite(h) && Number.isFinite(ratio) && ratio > 0 ? ratio : null;
}
function procOutputFrameSize(aspect, sourceW, sourceH, contentRatio) {
  if (aspect === '9x16') return {width:1080, height:1920};
  if (aspect === '16x9') return {width:1920, height:1080};
  if (contentRatio) return {width:sourceW, height:Math.max(2, Math.round(sourceW / contentRatio / 2) * 2)};
  return {width:sourceW, height:sourceH};
}
function procLogoVisibleAtTime(start, end, time) {
  const t = Number(time) || 0;
  const first = start === '' || start == null ? null : Number(start);
  const last = end === '' || end == null ? null : Number(end);
  return (first === null || !Number.isFinite(first) || t >= first)
    && (last === null || !Number.isFinite(last) || t < last);
}
function procContentAspectInput(input) {
  const valid = !input.value.trim() || input.value.trim() === 'auto' || procParseContentAspect(input.value) !== null;
  input.setCustomValidity(valid ? '' : 'Nhập tỉ lệ hợp lệ, ví dụ 3:4 hoặc 4:5.');
  input.setAttribute('aria-invalid', String(!valid));
  document.getElementById('proc-content-aspect-error').hidden = valid;
  framePreviewUpdate();
}
function subPreviewUpdate() {
  const fsInput = document.getElementById('proc-font-size');
  const fsSlider = document.getElementById('proc-font-size-slider');
  if (fsInput && fsSlider && fsSlider.value !== fsInput.value) {
    fsSlider.value = fsInput.value || 4.5;
  }

  // Đảm bảo frame-enabled luôn bật
  const frameChk = document.getElementById('frame-enabled');
  // Respect the saved frame toggle.

  // Luôn cập nhật preview canvas thống nhất (chứa cả video, khung, logo, vùng mờ và phụ đề)
  if (typeof framePreviewUpdate === 'function') {
    framePreviewUpdate();
  } else if (typeof _renderSubOverlay === 'function') {
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
    else if (key === 'motion') ov.motion = ['none','figure8','horizontal','vertical','circle','diamond'].includes(value) ? value : 'none';
    else if (key === 'motion_amp_pct') ov.motion_amp_pct = _ovClamp(value, 0, 1);
    else if (key === 'motion_period_sec') ov.motion_period_sec = _ovClamp(value, 1, 120);
    else if (key === 'box_opacity' || key === 'opacity' || key === 'text_opacity') ov[key] = _ovClamp(value, 0, 1);
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
    if (document.getElementById('sub-preview-img')?.style.display !== 'none'
        || (window.pe2IsLivePlayback && window.pe2IsLivePlayback())) _renderSubOverlay();
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
    const frameChk = document.getElementById('frame-enabled');
    // Respect the saved frame toggle.

    const canvas = document.getElementById('frame-preview-canvas');
    if (canvas) {
      canvas.style.display = 'block';
      canvas.style.zIndex = '4';
      canvas.style.pointerEvents = 'auto';
    }

    const player = document.getElementById('pe2-video-player');
    const playerReady = !!(player && player.style.display !== 'none' && player.readyState >= 1
      && player.videoWidth && player.videoHeight);
    const img = document.getElementById('sub-preview-img');
    const imgReady = !!(img && img.complete && (img.naturalWidth || 0) > 0);
    const srcImg = (playerReady && player.readyState >= 2) ? player : (imgReady ? img : (playerReady ? player : null));
    const sourceW = srcImg ? (srcImg.videoWidth || srcImg.naturalWidth || 0) : 0;
    if (!srcImg || (!playerReady && img && !img.complete) || !sourceW) return;
    _drawFramePreview(srcImg);
  }
  function _drawFramePreview(srcImg) {
    const canvas = document.getElementById('frame-preview-canvas');
    if (!canvas) return;

    const frameEnabled = document.getElementById('frame-enabled')?.checked ?? false;
    const titleEnabled = frameEnabled && (document.getElementById('frame-title-enabled')?.checked ?? true);
    const titleInput = document.getElementById('frame-title');
    const previewPath = typeof _procAiVideoPath === 'function' ? _procAiVideoPath() : '';
    const autoTitle = previewPath && titleInput?.dataset.aiVideoPath === previewPath ? titleInput.dataset.aiTitle : '';
    const title = titleEnabled ? (titleInput?.value || autoTitle || '') : '';
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
    const blurWPct    = parseFloat(document.getElementById('frame-blur-w')?.value || 0) / 100;
    const blurOpacity = parseFloat(document.getElementById('frame-blur-opacity')?.value || 60) / 100;
    const logoSizeRaw = parseFloat(document.getElementById('frame-logo-size')?.value);
    const logoSizePct = (isNaN(logoSizeRaw) ? (document.getElementById('frame-logo-path')?.value ? 12 : 0) : logoSizeRaw) / 100;
    const logoTopPct  = parseFloat(document.getElementById('frame-logo-top')?.value || 3) / 100;
    const logoLeftPct = parseFloat(document.getElementById('frame-logo-left')?.value || 3) / 100;
    const logoRadiusPct = parseFloat(document.getElementById('frame-logo-radius')?.value ?? 50) / 100;
    const blurMode = frameEnabled ? (document.querySelector('input[name="frame-blur-mode"]:checked')?.value || 'overlay') : 'overlay';
    const blurTopPct    = parseFloat(document.getElementById('frame-blur-top')?.value || 0) / 100;
    const blurBottomPct = parseFloat(document.getElementById('frame-blur-bottom')?.value || 0) / 100;

    const srcNW = srcImg.videoWidth || srcImg.naturalWidth  || 640;
    const srcNH = srcImg.videoHeight || srcImg.naturalHeight || 360;
    const wrap  = document.getElementById('sub-preview-wrap');
    // Dùng độ phân giải video làm gốc vẽ (ổn định, không phụ thuộc kích thước hiển thị)
    const wrapW = srcImg.videoWidth || srcImg.naturalWidth || wrap?.offsetWidth || 640;

    // Title bar chỉ chiếm chỗ khi thật sự có nội dung tiêu đề.
    const titleFontPx = hasTitle ? Math.max(16, Math.floor(wrapW * titleSizePct / 100)) : 0;
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
      let drawn = false;
      if (srcImg && (srcImg.readyState === undefined || srcImg.readyState >= 2)) {
        try {
          c.drawImage(srcImg, vidX, vidY, vidW, vidH);
          drawn = true;
        } catch (_) {}
      }
      if (!drawn) {
        const fallbackImg = document.getElementById('sub-preview-img');
        if (fallbackImg && fallbackImg.complete && fallbackImg.naturalWidth) {
          try {
            c.drawImage(fallbackImg, vidX, vidY, vidW, vidH);
            drawn = true;
          } catch (_) {}
        }
      }
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
        const player = document.getElementById('pe2-video-player');
        const previewTime = player && player.style.display !== 'none'
          ? player.currentTime : Number(document.getElementById('sub-preview-ts')?.value || 0);
        const logoStart = document.getElementById('frame-logo-start')?.value;
        const logoEnd = document.getElementById('frame-logo-end')?.value;
        if (!procLogoVisibleAtTime(logoStart, logoEnd, previewTime)) return;
        const logoNW = window._frameLogoImg.naturalWidth  || window._frameLogoImg.width;
        const logoNH = window._frameLogoImg.naturalHeight || window._frameLogoImg.height;
        const logoAR = logoNW / (logoNH || 1);
        const lH = Math.max(20, Math.floor(vidH * logoSizePct));
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
    // Keep source video below all configured effects, including legacy saved orders.
    const layerOrder = ['video', ...(window._pe2LayerOrder || ['frame', 'blur', 'logo', 'overlays', 'subs']).filter(id => id !== 'video')];
    const trackVis = window._pe2TrackVisibility || {};

    layerOrder.forEach(layerId => {
      if (trackVis[layerId] === false) return;
      if (layerId === 'video') {
        _drawLayerVideo(ctx);
      } else if (layerId === 'frame' && frameEnabled) {
        _drawLayerFrame(ctx);
      } else if (layerId === 'blur') {
        if (typeof _drawBlurZonesOnCanvas === 'function') {
          _drawBlurZonesOnCanvas(ctx, vidX, vidY, vidW, vidH);
        }
      } else if (layerId === 'logo' && frameEnabled) {
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
    const contentRatio = procParseContentAspect(document.getElementById('proc-content-aspect')?.value);
    const contentMode = document.getElementById('proc-content-aspect-mode')?.value || 'crop';
    const targetRatio = targetAspect === '9x16' ? 9 / 16 : 16 / 9;
    const targetW = targetAspect === '9x16' ? 1080 : 1920;
    const targetH = targetAspect === '9x16' ? 1920 : 1080;
    const forcePixelSize = contentMode === 'stretch' || contentMode === 'original_crop';
    const shouldConvert = !!contentRatio || (isForced && (
      Math.abs(srcNW / srcNH - targetRatio) > 0.01 ||
      (forcePixelSize && (srcNW !== targetW || srcNH !== targetH))
    ));

    let finalCW = cW;
    let finalCH = cH;
    let finalVidX = vidX;
    let finalVidY = vidY;
    let finalVidW = vidW;
    let finalVidH = vidH;
    let finalTitleBarH = titleBarH;
    let fgScale = 1;
    let fgScaleX = 1;
    let fgScaleY = 1;
    let fgX = 0;
    let fgY = 0;

    if (shouldConvert) {
      const composed = document.createElement('canvas');
      composed.width = cW;
      composed.height = cH;
      composed.getContext('2d').drawImage(canvas, 0, 0);

      const outputFrame = procOutputFrameSize(aspectValue, cW, cH, contentRatio);
      finalCW = outputFrame.width;
      finalCH = outputFrame.height;
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

      const innerW = contentRatio ? Math.max(2,Math.floor(Math.min(finalCW, finalCH*contentRatio)/2)*2) : finalCW;
      const innerH = contentRatio ? Math.max(2,Math.floor(Math.min(finalCH, finalCW/contentRatio)/2)*2) : finalCH;
      if (contentMode === 'stretch') {
        fgScaleX = innerW / cW;
        fgScaleY = innerH / cH;
      } else if (contentMode === 'original_crop') {
        fgScaleX = fgScaleY = 1;
      } else if (contentMode === 'keep_width_crop_height') {
        fgScaleX = fgScaleY = innerW / cW;
      } else if (contentMode === 'keep_height_crop_width') {
        fgScaleX = fgScaleY = innerH / cH;
      } else {
        fgScaleX = fgScaleY = contentMode === 'pad'
          ? Math.min(innerW / cW, innerH / cH)
          : Math.max(innerW / cW, innerH / cH);
      }
      fgScale = fgScaleX;
      const fgW = cW * fgScaleX;
      const fgH = cH * fgScaleY;
      fgX = (finalCW - fgW) / 2;
      fgY = (finalCH - fgH) / 2;
      outCtx.save(); outCtx.beginPath(); outCtx.rect((finalCW-innerW)/2,(finalCH-innerH)/2,innerW,innerH); outCtx.clip();
      outCtx.drawImage(composed, fgX, fgY, fgW, fgH); outCtx.restore();

      finalVidX = fgX + vidX * fgScaleX;
      finalVidY = fgY + vidY * fgScaleY;
      finalVidW = vidW * fgScaleX;
      finalVidH = vidH * fgScaleY;
      finalTitleBarH = titleBarH * fgScaleY;
    }

    canvas.style.display = 'block';
    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.zIndex = '4';
    canvas.style.pointerEvents = 'auto';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.maxWidth = '100%';

    // Hide DOM overlays to avoid duplicate text / blur boxes on screen
    const domText = document.getElementById('sub-preview-text');
    if (domText) domText.style.display = 'none';
    const domBlur = document.getElementById('sub-preview-blur');
    if (domBlur) domBlur.style.display = 'none';
    const domBlurCanvas = document.getElementById('sub-preview-blur-canvas');
    if (domBlurCanvas) domBlurCanvas.style.display = 'none';
    const domPh = document.getElementById('sub-preview-placeholder');
    if (domPh) domPh.style.display = 'none';

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
      fgScaleX,
      fgScaleY,
      fgX,
      fgY
    };
    window._frameInteractiveSource = frameInteractiveSource;
    window._frameInteractive = Object.fromEntries(Object.entries(frameInteractiveSource).map(([key, box]) => ([
      key,
      {
        x: fgX + box.x * fgScaleX,
        y: fgY + box.y * fgScaleY,
        w: box.w * fgScaleX,
        h: box.h * fgScaleY
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
    const _targetRatio = aspect === '9x16' ? 9 / 16 : 16 / 9;
    const _shouldConvert = _forced && Math.abs(_srcW / _srcH - _targetRatio) > 0.01;
    const _blurBg = document.getElementById('proc-aspect-blur-bg')?.checked || false;
    const _bgEl = document.getElementById('sub-preview-bgblur');
    const _frameEnabled = document.getElementById('frame-enabled')?.checked || false;
    const _player = document.getElementById('pe2-video-player');
    const _playerActive = !!(_player && _player.style.display !== 'none');

    if (subWrap) {
      if (_shouldConvert) {
        subWrap.style.aspectRatio = isVertical ? '9 / 16' : '16 / 9';
        subWrap.dataset.letterbox = '1';
        if (_imgEl) {
          if (_playerActive) {
            _imgEl.style.display = 'none';
            _imgEl.style.opacity = '0';
            _imgEl.style.visibility = 'hidden';
          } else {
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
          if (_playerActive) {
            _imgEl.style.display = 'none';
            _imgEl.style.opacity = '0';
            _imgEl.style.visibility = 'hidden';
          } else {
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
        }
        if (_bgEl) { _bgEl.style.display = 'none'; _bgEl.removeAttribute('src'); }
      }

      if (_playerActive) {
        const _fc = document.getElementById('frame-preview-canvas');
        if (_fc) {
          _fc.style.display = _frameEnabled ? 'block' : 'none';
          _fc.style.zIndex = _frameEnabled ? '4' : '2';
          _fc.style.pointerEvents = _frameEnabled ? 'auto' : 'none';
        }
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
        canvas.style.zIndex = '4';
        canvas.style.pointerEvents = 'auto';
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
    subs:     { name: 'Phụ đề video', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8"/><path d="M8 13h5"/></svg>', desc: 'Phụ đề dịch và phụ đề gốc', tab: 'subs' },
    overlays: { name: 'Chữ / Khối / Ảnh', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg>', desc: 'Các text, khối nền, sticker và ảnh chèn', tab: 'overlay' },
    blur:     { name: 'Vùng che mờ', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>', desc: 'Khối làm mờ chữ gốc và vùng che bổ sung', tab: 'overlay' },
    logo:     { name: 'Logo & Watermark', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>', desc: 'Ảnh logo / watermark nhận diện thương hiệu', tab: 'frame' },
    frame:    { name: 'Khung & Tiêu đề', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/></svg>', desc: 'Thanh tiêu đề và hiệu ứng mờ viền', tab: 'frame' },
    video:    { name: 'Video gốc', icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg>', desc: 'Khung hình gốc của video (nền dưới cùng)', tab: 'subs' }
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
      if (!window._pe2LayerOrder.includes('overlays')) {
        const subIdx = window._pe2LayerOrder.indexOf('subs');
        if (subIdx !== -1) {
          window._pe2LayerOrder.splice(subIdx, 0, 'overlays');
        } else {
          window._pe2LayerOrder.push('overlays');
        }
      }
      const savedVis = JSON.parse(localStorage.getItem('pe2_track_visibility') || 'null');
      if (savedVis && typeof savedVis === 'object') {
        window._pe2TrackVisibility = savedVis;
      }
      window._pe2TrackVisibility = window._pe2TrackVisibility || {};
      if (window._pe2TrackVisibility.overlays === undefined) {
        window._pe2TrackVisibility.overlays = true;
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
      if (typeof toast === 'function') toast('Đã đưa lớp [' + (TRACK_DEFINITIONS[layerId]?.name || layerId) + '] lên trên', 'info', { duration: 1500 });
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
      if (typeof toast === 'function') toast('Đã đưa lớp [' + (TRACK_DEFINITIONS[layerId]?.name || layerId) + '] xuống dưới', 'info', { duration: 1500 });
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
      const def = TRACK_DEFINITIONS[layerId] || { name: layerId, icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>', desc: '', tab: 'subs' };
      const isVisible = vis[layerId] !== false;
      const actualIdx = (window._pe2LayerOrder || []).indexOf(layerId);
      const isTop = actualIdx === (window._pe2LayerOrder || []).length - 1;
      const isBottom = actualIdx === 0;

      let extraInfo = '';
      if (layerId === 'overlays') {
        const count = (window._videoOverlays || []).length;
        extraInfo = `<span class="pe2-track-badge" style="background:rgba(99,102,241,0.12);color:var(--accent,#3b82f6)">${count} phần tử</span>`;
      } else if (layerId === 'logo' && (document.getElementById('frame-enabled')?.checked ?? false)) {
        const hasLogo = !!(document.getElementById('frame-logo-path')?.value);
        extraInfo = hasLogo ? `<span class="pe2-track-badge" style="background:rgba(34,197,94,0.12);color:#22c55e">Đã chọn</span>` : `<span class="pe2-track-badge" style="color:var(--text-muted)">Chưa có</span>`;
      } else if (layerId === 'subs') {
        const hasSample = !!(document.getElementById('sub-preview-sample')?.value);
        extraInfo = hasSample ? `<span class="pe2-track-badge" style="background:rgba(34,197,94,0.12);color:#22c55e">Bật</span>` : '';
      }

      return `
        <div class="pe2-track-card ${isVisible ? '' : 'disabled'}" data-track-id="${layerId}">
          <span class="pe2-track-icon-wrap">${def.icon}</span>
          <div style="flex:1;min-width:0;display:flex;align-items:center;gap:6px">
            <span class="pe2-track-name">${def.name}</span>
            ${extraInfo}
          </div>
          <div class="pe2-track-controls">
            <button type="button" class="pe2-track-btn" 
              onclick="pe2MoveTrackUp('${layerId}')" title="Đưa lên trên" ${isTop ? 'disabled' : ''}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>
            </button>
            <button type="button" class="pe2-track-btn" 
              onclick="pe2MoveTrackDown('${layerId}')" title="Đưa xuống dưới" ${isBottom ? 'disabled' : ''}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
            <button type="button" class="pe2-track-btn" 
              onclick="pe2ToggleTrack('${layerId}')" title="${isVisible ? 'Ẩn lớp này' : 'Hiện lớp này'}">
              ${isVisible 
                ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' 
                : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'}
            </button>
            <button type="button" class="pe2-track-btn" 
              onclick="pe2Tool('${def.tab}')" title="Cài đặt lớp này">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
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


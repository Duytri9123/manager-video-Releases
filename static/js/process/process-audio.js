// Initialize window._procExtAudios
  window._procExtAudios = [];
  async function procAddExtAudio(input) {
    const file = input.files?.[0];
    if (!file) return;

    // Reset input
    input.value = '';

    const dur = await _getAudioDuration(file);
    if (!dur || dur <= 0) {
      if (typeof toast === 'function') toast('✗ Không thể đọc được thời lượng của file âm thanh này', 'error');
      return;
    }

    const videoDur = parseFloat(window._pe2Duration || 0) || 0;
    let defaultVidEnd = 'cuối';
    if (videoDur > 0 && dur < videoDur) {
      defaultVidEnd = dur.toFixed(2);
    }

    const tempId = 'aud-' + Date.now().toString(36) + '-' + Math.random().toString(36).substr(2, 5);
    const newTrack = {
      id: tempId,
      name: '⏳ Đang tải (0%): ' + file.name,
      path: '',
      duration: dur,
      vid_start: 'đầu',
      vid_end: defaultVidEnd,
      clip_start: '0',
      clip_end: dur.toFixed(2), // default end to actual max duration
      vol: 1.0
    };

    window._procExtAudios.push(newTrack);
    procRenderExtAudios();

    _uploadFileWithProgress(file, 'audio',
      function(pct) {
        newTrack.name = '⏳ Đang tải (' + pct + '%): ' + file.name;
        procRenderExtAudios();
      },
      function(d) {
        if (d.ok && d.path) {
          newTrack.name = file.name;
          newTrack.path = d.path;
          if (typeof toast === 'function') toast('✓ Đã tải lên: ' + file.name, 'success');
        } else {
          window._procExtAudios = window._procExtAudios.filter(x => x.id !== tempId);
          if (typeof toast === 'function') toast('✗ Tải file thất bại: ' + (d.error || ''), 'error');
        }
        procRenderExtAudios();
        _syncExtAudiosHidden();
        if (window.subPreviewUpdate) window.subPreviewUpdate();
      },
      function(err) {
        window._procExtAudios = window._procExtAudios.filter(x => x.id !== tempId);
        if (typeof toast === 'function') toast('✗ Lỗi kết nối khi tải âm thanh', 'error');
        procRenderExtAudios();
        _syncExtAudiosHidden();
        if (window.subPreviewUpdate) window.subPreviewUpdate();
      }
    );
  }
  function procRemoveExtAudio(id) {
    window._procExtAudios = window._procExtAudios.filter(x => x.id !== id);
    procRenderExtAudios();
    _syncExtAudiosHidden();
    if (window.subPreviewUpdate) window.subPreviewUpdate();
  }
  function procUpdateExtAudio(id, key, val) {
    const track = window._procExtAudios.find(x => x.id === id);
    if (!track) return;

    if (key === 'vol') {
      track[key] = parseFloat(val) || 1.0;
    } else if (key === 'clip_end') {
      let numVal = parseFloat(val);
      if (!isNaN(numVal)) {
        if (numVal > track.duration) {
          numVal = track.duration;
          if (typeof toast === 'function') toast(`⚠️ Thời lượng file tối đa là ${track.duration.toFixed(2)}s, tự động giới hạn`, 'warning');
        }
        track[key] = numVal.toFixed(2);
      } else {
        track[key] = val;
      }
    } else if (key === 'clip_start') {
      let numVal = parseFloat(val);
      if (!isNaN(numVal)) {
        if (numVal < 0) numVal = 0;
        if (numVal > track.duration) numVal = track.duration;
        track[key] = numVal.toFixed(2);
      } else {
        track[key] = val;
      }
    } else {
      track[key] = val;
    }

    // Force update values in DOM input if they were clamped/changed
    const startEl = document.querySelector(`[oninput*="clip_start"][oninput*="${id}"]`);
    const endEl = document.querySelector(`[onchange*="clip_end"][onchange*="${id}"]`);
    if (startEl) startEl.value = track.clip_start;
    if (endEl) endEl.value = track.clip_end;

    _syncExtAudiosHidden();
    if (window.subPreviewUpdate) window.subPreviewUpdate();
  }
  function _syncExtAudiosHidden() {
    const hidden = document.getElementById('proc-ext-audios-json');
    if (hidden) {
      hidden.value = JSON.stringify(window._procExtAudios);
    }
  }
  function procRenderExtAudios() {
    const container = document.getElementById('proc-ext-audio-list');
    if (!container) return;

    if (window._procExtAudios.length === 0) {
      container.innerHTML = `<div style="text-align:center;font-size:11px;color:var(--text-muted,#8a8a93);padding:10px;border:1px dashed var(--border,#dcdce2);border-radius:6px">Chưa thêm âm thanh ngoài nào</div>`;
      return;
    }

    container.innerHTML = window._procExtAudios.map((track) => {
      const volPct = Math.round(track.vol * 100);
      return `
        <div class="ov-layer-card" style="padding:10px;background:var(--bg2,#f7f9ff);border-radius:6px;border:1px solid var(--border,#e2e8f0);margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <span style="font-size:11px;font-weight:700;word-break:break-all;color:var(--text,#1e293b);flex:1;margin-right:8px">
              🎵 ${track.name}
            </span>
            <span style="font-size:10px;color:var(--accent,#1a73e8);background:rgba(26,115,232,0.1);padding:1px 5px;border-radius:4px;white-space:nowrap;margin-right:6px">
              Tối đa: ${track.duration.toFixed(2)}s
            </span>
            <button type="button" style="border:none;background:transparent;padding:2px 6px;cursor:pointer;font-size:13px;color:#ef4444;line-height:1" 
              onclick="procRemoveExtAudio('${track.id}')" title="Xóa">
              🗑️
            </button>
          </div>

          <!-- Timeline Range on Video -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
            <div>
              <label style="font-size:10px;color:var(--text-muted,#8a8a93);display:block;margin-bottom:2px">Xuất hiện tại (s)</label>
              <input type="text" value="${track.vid_start}" style="width:100%;height:30px;font-size:11px;padding:0 6px;border:1px solid var(--border,#dcdce2);border-radius:4px" 
                oninput="procUpdateExtAudio('${track.id}', 'vid_start', this.value)">
            </div>
            <div>
              <label style="font-size:10px;color:var(--text-muted,#8a8a93);display:block;margin-bottom:2px">Biến mất tại (s)</label>
              <input type="text" value="${track.vid_end}" style="width:100%;height:30px;font-size:11px;padding:0 6px;border:1px solid var(--border,#dcdce2);border-radius:4px" 
                oninput="procUpdateExtAudio('${track.id}', 'vid_end', this.value)">
            </div>
          </div>

          <!-- Clip range inside file -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
            <div>
              <label style="font-size:10px;color:var(--text-muted,#8a8a93);display:block;margin-bottom:2px">Cắt từ giây</label>
              <input type="text" value="${track.clip_start}" style="width:100%;height:30px;font-size:11px;padding:0 6px;border:1px solid var(--border,#dcdce2);border-radius:4px" 
                oninput="procUpdateExtAudio('${track.id}', 'clip_start', this.value)">
            </div>
            <div>
              <label style="font-size:10px;color:var(--text-muted,#8a8a93);display:block;margin-bottom:2px">Cắt đến giây</label>
              <input type="text" value="${track.clip_end}" style="width:100%;height:30px;font-size:11px;padding:0 6px;border:1px solid var(--border,#dcdce2);border-radius:4px" 
                onchange="procUpdateExtAudio('${track.id}', 'clip_end', this.value)">
            </div>
          </div>

          <!-- Track volume -->
          <div>
            <div style="display:flex;justify-content:space-between;margin-bottom:2px">
              <label style="font-size:10px;color:var(--text-muted,#8a8a93)">Âm lượng:</label>
              <span style="font-size:10px;font-weight:bold" id="vol-lbl-${track.id}">${volPct}%</span>
            </div>
            <input type="range" min="0" max="200" step="5" value="${volPct}" style="width:100%" 
              oninput="document.getElementById('vol-lbl-${track.id}').textContent=this.value+'%';procUpdateExtAudio('${track.id}', 'vol', this.value/100)">
          </div>
        </div>
      `;
    }).join('');
  }
  setTimeout(() => {
    const hidden = document.getElementById('proc-ext-audios-json');
    if (hidden) {
      const syncList = () => {
        try {
          window._procExtAudios = JSON.parse(hidden.value || '[]');
          procRenderExtAudios();
        } catch(e) {}
      };
      hidden.addEventListener('change', syncList);
      hidden.addEventListener('input', syncList);
      syncList();
    }
  }, 100);
  function _frameStartAnim() {
    if (!window._frameLogoIsGif) return;          // chỉ GIF mới cần
    if (!document.getElementById('frame-enabled')?.checked) return;
    _frameStartGifRestart();
    if (window._frameAnimRAF) return;            // đang chạy rồi
    window._frameAnimLast = 0;
    window._frameAnimRAF = requestAnimationFrame(_frameAnimLoop);
  }
  function _onExtAudioFileSelected(input) {
    const file = input.files?.[0];
    if (!file) return;
    
    // Display filename while uploading
    const pathEl = document.getElementById('proc-ext-audio-path');
    if (pathEl) pathEl.value = '⏳ Đang tải (0%): ' + file.name;

    _uploadFileWithProgress(file, 'audio',
      function(pct) {
        if (pathEl) pathEl.value = '⏳ Đang tải (' + pct + '%): ' + file.name;
      },
      function(d) {
        if (d.ok && d.path) {
          if (pathEl) {
            pathEl.value = file.name;
            pathEl.dataset.serverPath = d.path;
          }
          if (typeof toast === 'function') {
            toast('✓ Đã tải lên âm thanh: ' + file.name, 'success');
          }
        } else {
          if (pathEl) {
            pathEl.value = '';
            pathEl.dataset.serverPath = '';
          }
          if (typeof toast === 'function') {
            toast('✗ Tải lên âm thanh thất bại: ' + (d.error || ''), 'error');
          }
        }
      },
      function(err) {
        if (pathEl) {
          pathEl.value = '';
          pathEl.dataset.serverPath = '';
        }
        if (typeof toast === 'function') {
          toast('✗ Lỗi kết nối khi tải âm thanh', 'error');
        }
      }
    );
  }
  function frameSetLogo(input) {
    const file = input.files?.[0];
    if (!file) return;
    window._frameLogoFile = file;
    
    // Display filename while uploading
    document.getElementById('frame-logo-path').value = '⏳ Đang tải (0%): ' + file.name;

    _uploadFileWithProgress(file, 'logo',
      function(pct) {
        document.getElementById('frame-logo-path').value = '⏳ Đang tải (' + pct + '%): ' + file.name;
      },
      function(d) {
        if (d.ok && d.path) {
          // Store server path as data attribute
          document.getElementById('frame-logo-path').dataset.serverPath = d.path;
          
          // Construct URL from path (path is like "temp_uploads/anti-fp-logo-xxx.png")
          // We need to serve it as /temp_uploads/anti-fp-logo-xxx.png
          const pathParts = d.path.split(/[\\/]/);  // Handle both / and \
          const filename = pathParts[pathParts.length - 1];
          const url = '/temp_uploads/' + filename;
          
          // Save to localStorage for persistence
          try {
            localStorage.setItem('proc_frame_logo_path', d.path);
            localStorage.setItem('proc_frame_logo_url', url);
          } catch (_) {}
          
          // Update display to show filename only (not full path)
          document.getElementById('frame-logo-path').value = filename;
          
          if (typeof toast === 'function') {
            toast('✓ Logo đã lưu: ' + file.name, 'success');
          }
          
          // Load the new logo image for preview
          const img = new Image();
          img.onload = () => {
            _setFrameLogo(img, (file.type === 'image/gif') || _isGifSrc(file.name) || _isGifSrc(url));
          };
          img.src = url + '?t=' + Date.now();  // Add timestamp to bypass cache
        } else {
          document.getElementById('frame-logo-path').value = '';
          document.getElementById('frame-logo-path').dataset.serverPath = '';
          if (typeof toast === 'function') {
            toast('✗ Upload logo thất bại', 'error');
          }
        }
      },
      function(err) {
        document.getElementById('frame-logo-path').value = '';
        document.getElementById('frame-logo-path').dataset.serverPath = '';
        if (typeof toast === 'function') {
          toast('✗ Lỗi upload logo', 'error');
        }
      }
    );

    // Also show preview immediately from file (before upload completes)
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        _setFrameLogo(img, (file.type === 'image/gif') || _isGifSrc(file.name));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
    input.value = '';
  }
  function _loadFrameLogoDefault() {
    const pathInput = document.getElementById('frame-logo-path');
    if (!pathInput) return;
    
    try {
      // Try to load saved logo path from localStorage
      const savedPath = localStorage.getItem('proc_frame_logo_path');
      const savedUrl = localStorage.getItem('proc_frame_logo_url');
      
      if (savedPath && savedUrl) {
        // Extract filename from path for display
        const pathParts = savedPath.split(/[\\/]/);
        const filename = pathParts[pathParts.length - 1];
        pathInput.value = filename;
        pathInput.dataset.serverPath = savedPath;
        
        // Load the image for preview using URL
        const img = new Image();
        img.onload = () => {
          _setFrameLogo(img, _isGifSrc(savedUrl) || _isGifSrc(savedPath));
        };
        img.onerror = () => {
          // If saved path no longer exists, clear localStorage and leave logo empty.
          try {
            localStorage.removeItem('proc_frame_logo_path');
            localStorage.removeItem('proc_frame_logo_url');
          } catch (_) {}
          pathInput.value = '';
          pathInput.dataset.serverPath = '';
          window._frameLogoImg = null;
          window._frameLogoSrc = '';
          window._frameLogoIsGif = false;
        };
        // Add timestamp to bypass cache
        img.src = savedUrl + '?t=' + Date.now();
        return;
      }
    } catch (_) {}
    
    // No saved logo: keep empty. The pipeline only uses a user-selected logo.
    pathInput.value = '';
    pathInput.dataset.serverPath = '';
    window._frameLogoImg = null;
    window._frameLogoSrc = '';
    window._frameLogoIsGif = false;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _loadFrameLogoDefault);
  } else {
    _loadFrameLogoDefault();
  }





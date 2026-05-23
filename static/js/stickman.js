/* ─────────────────────────────────────────────────────────────────────────
 * Stickman Studio — UI controller.
 * Pairs với routes/stickman.py (server-side render).
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  let _poses = [];
  let _scenes = [];          // [{pose, duration, hold, caption, easing}]
  let _curSession = null;    // active render session id
  let _pollTimer = null;

  // ── Init ─────────────────────────────────────────────────────────────────
  window.stkInit = function () {
    if (window._stkInit) return;
    window._stkInit = true;

    fetch('/api/stickman/poses')
      .then(r => r.json())
      .then(data => {
        if (!data.ok) throw new Error(data.error || 'load poses fail');
        _poses = data.poses || [];
        _renderPoseBar();
      })
      .catch(err => {
        const bar = document.getElementById('stk-pose-bar');
        if (bar) bar.innerHTML = `<span class="text-xs text-red">Lỗi tải poses: ${err.message}</span>`;
      });
  };

  // ── Pose presets ─────────────────────────────────────────────────────────
  function _renderPoseBar() {
    const bar = document.getElementById('stk-pose-bar');
    if (!bar) return;
    if (!_poses.length) {
      bar.innerHTML = `<span class="text-xs text-muted">Không có pose nào.</span>`;
      return;
    }
    bar.innerHTML = _poses.map(p => `
      <div class="stk-pose-chip" onclick="stkAddSceneFromPose('${p}')" title="Thêm scene: ${p}">
        <img src="/api/stickman/preview/${encodeURIComponent(p)}" alt="${p}" loading="lazy">
        <div class="lbl">${p}</div>
      </div>
    `).join('');
  }

  // ── Scene list ───────────────────────────────────────────────────────────
  window.stkAddSceneFromPose = function (poseName) {
    if (!_poses.includes(poseName)) return;
    _scenes.push({
      pose: poseName,
      duration: 1.0,
      hold: 0.5,
      caption: '',
      easing: 'ease',
      emotion: 'neutral',
      character_style: 'normal',
      props: [],
      background: '',
    });
    _renderScenes();
    _showPosePreview(poseName);
  };

  window.stkRemoveScene = function (i) {
    _scenes.splice(i, 1);
    _renderScenes();
  };

  window.stkUpdateScene = function (i, key, value) {
    if (i < 0 || i >= _scenes.length) return;
    if (key === 'pose') {
      if (!_poses.includes(value)) return;
      _scenes[i].pose = value;
      _showPosePreview(value);
    } else if (key === 'duration' || key === 'hold') {
      const v = parseFloat(value);
      _scenes[i][key] = isNaN(v) ? 1.0 : Math.max(0.0, Math.min(15.0, v));
    } else if (key === 'caption') {
      _scenes[i].caption = String(value || '').slice(0, 300);
    } else if (key === 'emotion') {
      _scenes[i].emotion = value || 'neutral';
    } else if (key === 'character_style') {
      _scenes[i].character_style = value || 'normal';
    }
    _renderScenes(true); // skip full repaint where possible
  };

  function _renderScenes(skipStats) {
    const wrap = document.getElementById('stk-scenes-list');
    if (!wrap) return;
    if (!_scenes.length) {
      wrap.innerHTML = `<div class="text-xs text-muted" style="padding:18px;text-align:center">
        Chưa có scene nào. Click pose ở trên hoặc bấm "Mẫu demo".
      </div>`;
      _updateStats();
      return;
    }
    const _EMOTIONS = ['neutral','happy','sad','angry','surprised','thinking','excited'];
    const _STYLES = ['normal','teacher','student','scientist','chef','athlete'];

    const html = _scenes.map((s, i) => `
      <div class="stk-scene-row">
        <div class="stk-scene-idx">${i + 1}</div>
        <div class="stk-scene-thumb" onclick="stkCyclePose(${i})" title="Click để đổi pose">
          <img src="/api/stickman/preview/${encodeURIComponent(s.pose)}" alt="${s.pose}">
        </div>
        <div>
          <select class="stk-mini-input" onchange="stkUpdateScene(${i}, 'pose', this.value)">
            ${_poses.map(p => `<option value="${p}" ${p === s.pose ? 'selected' : ''}>${p}</option>`).join('')}
          </select>
          <input type="text" class="stk-mini-input" placeholder="Caption (tuỳ chọn)"
                 value="${_escapeAttr(s.caption || '')}"
                 oninput="stkUpdateScene(${i}, 'caption', this.value)"
                 style="margin-top:4px">
          <div style="display:flex;gap:4px;margin-top:4px">
            <select class="stk-mini-input" style="flex:1" onchange="stkUpdateScene(${i}, 'emotion', this.value)" title="Biểu cảm">
              ${_EMOTIONS.map(e => `<option value="${e}" ${e === (s.emotion || 'neutral') ? 'selected' : ''}>${e}</option>`).join('')}
            </select>
            <select class="stk-mini-input" style="flex:1" onchange="stkUpdateScene(${i}, 'character_style', this.value)" title="Phong cách">
              ${_STYLES.map(st => `<option value="${st}" ${st === (s.character_style || 'normal') ? 'selected' : ''}>${st}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="stk-cell-dur">
          <label style="font-size:10px">Trans (s)</label>
          <input type="number" min="0.1" max="15" step="0.1" class="stk-mini-input"
                 value="${s.duration}"
                 oninput="stkUpdateScene(${i}, 'duration', this.value)">
        </div>
        <div class="stk-cell-hold">
          <label style="font-size:10px">Hold (s)</label>
          <input type="number" min="0" max="15" step="0.1" class="stk-mini-input"
                 value="${s.hold}"
                 oninput="stkUpdateScene(${i}, 'hold', this.value)">
        </div>
        <button class="stk-del-btn" onclick="stkRemoveScene(${i})" title="Xoá scene">×</button>
      </div>
    `).join('');
    wrap.innerHTML = html;
    _updateStats();
  }

  function _escapeAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  // Cycle through poses on thumbnail click for quick variation
  window.stkCyclePose = function (i) {
    if (i < 0 || i >= _scenes.length || !_poses.length) return;
    const cur = _poses.indexOf(_scenes[i].pose);
    const nxt = (cur + 1) % _poses.length;
    _scenes[i].pose = _poses[nxt];
    _renderScenes();
    _showPosePreview(_poses[nxt]);
  };

  // ── Demo / clear ─────────────────────────────────────────────────────────
  window.stkLoadDemo = function () {
    _scenes = [
      { pose: 'stand',       duration: 0.5, hold: 0.3, caption: 'Xin chào!',           easing: 'ease', emotion: 'happy',    character_style: 'teacher', props: [] },
      { pose: 'wave_right',  duration: 0.6, hold: 0.6, caption: 'Mình là Stickman',    easing: 'ease', emotion: 'excited',  character_style: 'teacher', props: [] },
      { pose: 'point_right', duration: 0.5, hold: 0.5, caption: 'Bắt đầu thôi nào',   easing: 'ease', emotion: 'neutral',  character_style: 'teacher', props: ['pointer'] },
      { pose: 'think',       duration: 0.5, hold: 0.8, caption: 'Hmm suy nghĩ...',     easing: 'ease', emotion: 'thinking', character_style: 'scientist', props: ['book'] },
      { pose: 'walk_a',      duration: 0.4, hold: 0.0, caption: '',                    easing: 'linear', emotion: 'neutral', character_style: 'normal', props: [] },
      { pose: 'walk_b',      duration: 0.4, hold: 0.0, caption: '',                    easing: 'linear', emotion: 'neutral', character_style: 'normal', props: [] },
      { pose: 'jump_up',     duration: 0.4, hold: 0.4, caption: 'Yeahh!',             easing: 'ease', emotion: 'surprised', character_style: 'athlete', props: [] },
      { pose: 'cheer',       duration: 0.4, hold: 1.0, caption: 'Xong rồi 🎉',        easing: 'ease', emotion: 'excited',  character_style: 'normal', props: ['microphone'] },
    ];
    _renderScenes();
    if (typeof toast === 'function') toast('Đã nạp demo 8 scenes (có emotion + style)', 'info');
  };

  window.stkClearScenes = function () {
    if (!_scenes.length) return;
    if (!confirm('Xoá tất cả scenes?')) return;
    _scenes = [];
    _renderScenes();
  };

  // ── Stats / preview ──────────────────────────────────────────────────────
  function _updateStats() {
    const totalDur = _scenes.reduce((s, x) => s + x.duration + x.hold, 0);
    const fps = parseInt(document.getElementById('stk-fps')?.value || '24', 10) || 24;
    const totalFrames = Math.round(totalDur * fps);
    _setText('stk-stat-scenes', String(_scenes.length));
    _setText('stk-stat-duration', totalDur.toFixed(1) + 's');
    _setText('stk-stat-frames', String(totalFrames));
  }

  function _showPosePreview(poseName) {
    const wrap = document.getElementById('stk-preview-wrap');
    if (!wrap) return;
    if (_curSession) return;  // don't override during render
    wrap.innerHTML = `<img src="/api/stickman/preview/${encodeURIComponent(poseName)}?t=${Date.now()}" alt="${poseName}">`;
  }

  function _setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }

  // ── Render flow ──────────────────────────────────────────────────────────
  window.stkStartRender = function () {
    if (!_scenes.length) {
      if (typeof toast === 'function') toast('Thêm ít nhất 1 scene đã.', 'warning');
      return;
    }
    if (_curSession) {
      if (typeof toast === 'function') toast('Đang có session render khác.', 'warning');
      return;
    }
    const payload = {
      scenes: _scenes.map(s => ({
        pose: s.pose,
        duration: s.duration,
        hold: s.hold,
        caption: s.caption || '',
        easing: s.easing || 'ease',
        emotion: s.emotion || 'neutral',
        character_style: s.character_style || 'normal',
        props: s.props || [],
      })),
      preset: document.getElementById('stk-preset').value,
      fps: parseInt(document.getElementById('stk-fps').value, 10) || 24,
      bg_color: document.getElementById('stk-bg-color').value || '#ffffff',
      line_color: document.getElementById('stk-line-color').value || '#1a2332',
      name: (document.getElementById('stk-name').value || '').trim(),
      audio_path: (document.getElementById('stk-audio').value || '').trim(),
    };

    _setBadge('rendering', 'badge-yellow');
    _setText('stk-progress-pct', '0%');
    _setBar(0);
    _logClear();
    _logLine('Gửi yêu cầu render…', 'info');

    document.getElementById('stk-btn-render').disabled = true;
    document.getElementById('stk-btn-cancel').classList.remove('hidden');

    fetch('/api/stickman/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) throw new Error(data.error || 'render fail');
        _curSession = data.session_id;
        _logLine(`Session ${_curSession.slice(0, 8)} bắt đầu.`, 'info');
        _startPoll();
      })
      .catch(err => {
        _setBadge('error', 'badge-red');
        _logLine('Lỗi: ' + err.message, 'error');
        _resetButtons();
      });
  };

  window.stkCancelRender = function () {
    if (!_curSession) return;
    fetch(`/api/stickman/cancel/${_curSession}`, { method: 'POST' })
      .then(r => r.json())
      .then(() => _logLine('Đã yêu cầu huỷ.', 'warning'))
      .catch(err => _logLine('Cancel fail: ' + err.message, 'error'));
  };

  function _startPoll() {
    _stopPoll();
    _pollTimer = setInterval(() => {
      if (!_curSession) { _stopPoll(); return; }
      fetch(`/api/stickman/status/${_curSession}`)
        .then(r => r.json())
        .then(data => {
          if (!data.ok) throw new Error(data.error || 'status fail');
          _applyStatus(data);
          if (data.done) {
            _stopPoll();
            _onRenderDone(data);
          }
        })
        .catch(err => {
          _logLine('Poll fail: ' + err.message, 'error');
        });
    }, 700);
  }

  function _stopPoll() {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = null;
  }

  function _applyStatus(s) {
    const pct = Math.max(0, Math.min(100, parseInt(s.progress || 0, 10)));
    _setBar(pct);
    _setText('stk-progress-pct', pct + '%');
    _setText('stk-stat-progress', pct + '%');
    if (s.frame_total) _setText('stk-stat-frames', String(s.frame_total));
    if (s.duration)   _setText('stk-stat-duration', Number(s.duration).toFixed(1) + 's');
    // Append new log lines we haven't seen
    const newLines = (s.log || []).slice(_lastLogLen);
    for (const ln of newLines) _logLine(ln.msg, ln.level);
    _lastLogLen = (s.log || []).length;
    if (s.progress_label) {
      const badge = document.getElementById('stk-status-badge');
      if (badge) badge.textContent = s.progress_label;
    }
  }

  function _onRenderDone(s) {
    _resetButtons();
    if (s.status === 'error') {
      _setBadge('error', 'badge-red');
      _logLine('Render lỗi: ' + (s.error || 'unknown'), 'error');
    } else {
      _setBadge('done', 'badge-green');
      _setBar(100);
      _setText('stk-progress-pct', '100%');
      _setText('stk-stat-progress', '100%');
      _logLine('✔ Hoàn tất. File: ' + (s.output_path || ''), 'success');
      // Show video
      const wrap = document.getElementById('stk-preview-wrap');
      if (wrap) {
        wrap.innerHTML = `
          <video controls autoplay muted playsinline
                 src="/api/stickman/file/${_curSession}?t=${Date.now()}"></video>
        `;
      }
      if (typeof toast === 'function') toast('Render xong!', 'success');
    }
    _curSession = null;
    _lastLogLen = 0;
  }

  function _resetButtons() {
    const btn = document.getElementById('stk-btn-render');
    if (btn) btn.disabled = false;
    const cancel = document.getElementById('stk-btn-cancel');
    if (cancel) cancel.classList.add('hidden');
  }

  // ── Log + UI helpers ─────────────────────────────────────────────────────
  let _lastLogLen = 0;

  function _logLine(msg, level) {
    const box = document.getElementById('stk-log');
    if (!box) return;
    const cls = ({
      info: 'log-info', success: 'log-success',
      warning: 'log-warning', error: 'log-error',
    })[level] || 'log-info';
    const ts = new Date().toLocaleTimeString();
    const line = document.createElement('div');
    line.className = cls;
    line.textContent = `[${ts}] ${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  function _logClear() {
    const box = document.getElementById('stk-log');
    if (box) box.innerHTML = '';
    _lastLogLen = 0;
  }

  function _setBar(pct) {
    const bar = document.getElementById('stk-progress-bar');
    if (bar) bar.style.width = pct + '%';
  }

  function _setBadge(text, cls) {
    const b = document.getElementById('stk-status-badge');
    if (!b) return;
    b.textContent = text;
    b.className = 'badge ' + cls;
  }

  // Recompute frame count when fps preset changes
  document.addEventListener('change', (ev) => {
    if (!ev.target) return;
    if (ev.target.id === 'stk-fps') _updateStats();
  });

  // ── AI Director ────────────────────────────────────────────────────────────
  window.stkAiGenerate = function () {
    const content = (document.getElementById('stk-ai-content')?.value || '').trim();
    if (!content) {
      if (typeof toast === 'function') toast('Nhập nội dung/chủ đề trước.', 'warning');
      return;
    }

    const statusEl = document.getElementById('stk-ai-status');
    if (statusEl) statusEl.textContent = '⏳ Đang gọi AI sinh kịch bản…';

    const payload = {
      content: content,
      num_scenes: parseInt(document.getElementById('stk-ai-num')?.value || '8', 10),
      language: document.getElementById('stk-ai-lang')?.value || 'vi',
    };

    fetch('/api/stickman/ai_generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.ok) throw new Error(data.error || 'AI generate failed');
        // Load scenes into editor
        _scenes = (data.scenes || []).map(s => ({
          pose: s.pose || 'stand',
          duration: s.duration || 1.0,
          hold: s.hold || 0.5,
          caption: s.caption || '',
          easing: 'ease',
          emotion: s.emotion || 'neutral',
          character_style: s.character_style || 'normal',
          props: s.props || [],
          background: s.background || '',
        }));
        _renderScenes();
        if (statusEl) statusEl.innerHTML = `✅ AI đã sinh <b>${data.count}</b> scenes. Kiểm tra & chỉnh sửa bên dưới rồi bấm Render.`;
        if (typeof toast === 'function') toast(`AI sinh ${data.count} scenes thành công!`, 'success');
      })
      .catch(err => {
        if (statusEl) statusEl.textContent = '❌ Lỗi: ' + err.message;
        if (typeof toast === 'function') toast('AI lỗi: ' + err.message, 'error');
      });
  };
})();

/* ── batch_publish.js ─────────────────────────────────────────
   Đăng hàng loạt: import nhiều cặp video + ASS,
   AI phân tích nội dung ASS → tạo title/desc/tags → đăng tuần tự.
   ────────────────────────────────────────────────────────────── */

window._batchPubQueue = [];  // [{id, videoFile, assFile, videoName, assName, aiResult, status}]
window._batchPubRunning = false;

/* ════════════════════════════════════════════════════════════════
   TOGGLE
════════════════════════════════════════════════════════════════ */
function _batchPubToggle() {
  const on = document.getElementById('batch-pub-enabled')?.checked;
  const body = document.getElementById('batch-pub-body');
  if (body) body.style.display = on ? 'block' : 'none';
}

/* ════════════════════════════════════════════════════════════════
   IMPORT FILES — ghép cặp video + ASS theo tên
════════════════════════════════════════════════════════════════ */
function _batchPubImportFiles(input) {
  const files = Array.from(input.files || []);
  if (!files.length) return;

  const videoExts = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'];
  const subExts = ['.ass', '.srt'];

  const videos = [];
  const subs = [];

  files.forEach(f => {
    const ext = '.' + f.name.split('.').pop().toLowerCase();
    if (videoExts.includes(ext)) videos.push(f);
    else if (subExts.includes(ext)) subs.push(f);
  });

  if (!videos.length) {
    toast('Không tìm thấy file video nào', 'warning');
    return;
  }

  // Ghép cặp theo tên (bỏ extension)
  const getBaseName = (name) => name.replace(/\.[^.]+$/, '').toLowerCase().trim();

  const pairs = [];
  const usedSubs = new Set();

  videos.forEach(v => {
    const vBase = getBaseName(v.name);
    // Tìm ASS/SRT có cùng tên
    let matchedSub = null;
    for (let i = 0; i < subs.length; i++) {
      if (usedSubs.has(i)) continue;
      const sBase = getBaseName(subs[i].name);
      if (sBase === vBase || vBase.includes(sBase) || sBase.includes(vBase)) {
        matchedSub = subs[i];
        usedSubs.add(i);
        break;
      }
    }
    pairs.push({
      id: 'bp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
      videoFile: v,
      assFile: matchedSub,
      videoName: v.name,
      assName: matchedSub ? matchedSub.name : '(không có)',
      aiResult: null,
      status: 'pending', // pending | analyzing | ready | uploading | done | error
      error: '',
    });
  });

  // Thêm vào queue
  window._batchPubQueue.push(...pairs);
  _batchPubRender();

  const info = document.getElementById('batch-pub-info');
  if (info) info.value = `${pairs.length} cặp video (${videos.length} video, ${subs.length} phụ đề)`;
  toast(`✅ Đã import ${pairs.length} cặp video`, 'success');

  // Reset input
  input.value = '';
}

/* ════════════════════════════════════════════════════════════════
   RENDER QUEUE LIST
════════════════════════════════════════════════════════════════ */
function _batchPubRender() {
  const list = document.getElementById('batch-pub-list');
  const cnt = document.getElementById('batch-pub-count');
  if (cnt) cnt.textContent = window._batchPubQueue.length;
  if (!list) return;

  if (!window._batchPubQueue.length) {
    list.innerHTML = '<div class="empty-state text-xs" style="padding:20px;text-align:center;color:var(--text-muted)">Chưa có cặp video nào.</div>';
    return;
  }

  list.innerHTML = window._batchPubQueue.map((item, i) => {
    const statusBadge = {
      pending: '<span class="badge badge-gray">Chờ</span>',
      analyzing: '<span class="badge badge-yellow">AI...</span>',
      ready: '<span class="badge badge-green">Sẵn sàng</span>',
      uploading: '<span class="badge badge-yellow">Đang đăng</span>',
      done: '<span class="badge badge-green">✓ Xong</span>',
      error: '<span class="badge badge-red">Lỗi</span>',
    }[item.status] || '';

    const aiInfo = item.aiResult
      ? `<div class="text-xs text-muted" style="margin-top:2px">📝 ${(item.aiResult.youtube?.title || '').slice(0, 50)}...</div>`
      : '';

    return `
      <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;font-size:12px">
        <span style="color:var(--text-muted);font-weight:700;min-width:20px">${i + 1}</span>
        <div style="flex:1;min-width:0;overflow:hidden">
          <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${item.videoName}">🎬 ${item.videoName}</div>
          <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)" title="${item.assName}">📝 ${item.assName}</div>
          ${aiInfo}
          ${item.error ? `<div class="text-xs text-red">${item.error}</div>` : ''}
        </div>
        ${statusBadge}
        <button onclick="_batchPubRemove(${i})" class="btn-icon text-red" style="font-size:14px" ${item.status === 'uploading' ? 'disabled' : ''}>✕</button>
      </div>`;
  }).join('');
}

function _batchPubRemove(index) {
  window._batchPubQueue.splice(index, 1);
  _batchPubRender();
}

function _batchPubClear() {
  if (window._batchPubRunning) { toast('Đang chạy — không thể xóa', 'warning'); return; }
  window._batchPubQueue = [];
  _batchPubRender();
  const info = document.getElementById('batch-pub-info');
  if (info) info.value = '';
}

/* ════════════════════════════════════════════════════════════════
   LOG
════════════════════════════════════════════════════════════════ */
function _batchPubLog(msg, level) {
  const box = document.getElementById('batch-pub-log');
  if (!box) return;
  box.style.display = 'block';
  const d = document.createElement('div');
  d.className = 'log-' + (level || 'info');
  d.textContent = '[' + new Date().toTimeString().slice(0, 8) + '] ' + msg;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

/* ════════════════════════════════════════════════════════════════
   AI ANALYZE ALL — đọc ASS → gọi AI → điền thông tin
════════════════════════════════════════════════════════════════ */
async function _batchPubAnalyzeAll() {
  if (window._batchPubRunning) { toast('Đang chạy...', 'warning'); return; }

  const pending = window._batchPubQueue.filter(item => item.status === 'pending' && item.assFile);
  if (!pending.length) {
    toast('Không có cặp nào cần phân tích (thiếu file ASS hoặc đã phân tích)', 'warning');
    return;
  }

  const btn = document.getElementById('btn-batch-pub-analyze');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang phân tích...'; }
  window._batchPubRunning = true;

  const provider = document.getElementById('batch-pub-ai-provider')?.value || 'deepseek';
  let done = 0;

  for (const item of pending) {
    item.status = 'analyzing';
    _batchPubRender();
    _batchPubLog(`🤖 Phân tích: ${item.videoName}...`, 'info');

    try {
      // Đọc nội dung ASS
      const assText = await item.assFile.text();
      const plain = _extractPlainFromAss(assText);

      if (!plain) {
        item.status = 'error';
        item.error = 'ASS trống hoặc không có Dialogue';
        _batchPubLog(`⚠ ${item.videoName}: ASS trống`, 'warning');
        continue;
      }

      // Gọi AI
      const res = await fetch('/api/analyze_video_content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: plain.slice(0, 3000), provider })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'AI thất bại');

      item.aiResult = data.result;
      item.status = 'ready';
      done++;
      _batchPubLog(`✅ ${item.videoName}: ${data.result?.youtube?.title || '(no title)'}`, 'success');
    } catch (e) {
      item.status = 'error';
      item.error = e.message;
      _batchPubLog(`❌ ${item.videoName}: ${e.message}`, 'error');
    }
    _batchPubRender();

    // Delay nhỏ giữa các request để tránh rate limit
    await new Promise(r => setTimeout(r, 1000));
  }

  window._batchPubRunning = false;
  if (btn) { btn.disabled = false; btn.textContent = '🤖 AI Phân tích tất cả'; }
  _batchPubLog(`📊 Hoàn tất: ${done}/${pending.length} thành công`, done === pending.length ? 'success' : 'warning');
  toast(`AI phân tích xong: ${done}/${pending.length}`, 'success');
}

function _extractPlainFromAss(text) {
  if (!text) return '';
  const parts = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith('Dialogue:')) continue;
    const cols = line.split(',');
    if (cols.length < 10) continue;
    // Skip frame/blur styles (only get subtitle text)
    const style = (cols[3] || '').trim();
    if (['BlurLeft', 'BlurRight', 'TitleText', 'TitleBar'].includes(style)) continue;
    const t = cols.slice(9).join(',')
      .replace(/\{[^}]*\}/g, '')
      .replace(/\\N/g, ' ')
      .replace(/\\n/g, ' ')
      .trim();
    if (t) parts.push(t);
  }
  return parts.join(' ');
}

/* ════════════════════════════════════════════════════════════════
   UPLOAD ALL — đăng tuần tự lên các nền tảng đã bật
════════════════════════════════════════════════════════════════ */
async function _batchPubStartAll() {
  if (window._batchPubRunning) { toast('Đang chạy...', 'warning'); return; }

  const pending = window._batchPubQueue.filter(item => item.status === 'ready' || item.status === 'pending');
  if (!pending.length) {
    toast('Không có video nào sẵn sàng để đăng', 'warning');
    return;
  }

  // Check platforms
  const platforms = [];
  if (window._pubEnabled?.youtube) platforms.push('youtube');
  if (window._pubEnabled?.tiktok) platforms.push('tiktok');
  if (window._pubEnabled?.facebook) platforms.push('facebook');
  if (!platforms.length) {
    toast('Chưa bật nền tảng nào (bật YouTube/TikTok/Facebook ở panel bên phải)', 'warning');
    return;
  }

  // ── Preflight: kiểm tra nền tảng sẵn sàng ──
  const preflightOk = await _batchPubPreflight(platforms);
  if (!preflightOk) return;

  const btn = document.getElementById('btn-batch-pub-start');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }
  window._batchPubRunning = true;

  // ── Bước 2: Đăng tuần tự — mỗi video: AI phân tích → upload → đăng ──
  _batchPubLog(`🚀 Bắt đầu đăng ${pending.length} video (phân tích + đăng từng cặp)...`, 'info');

  const intervalH = parseFloat(document.getElementById('batch-pub-interval')?.value || '0');
  const startStr = document.getElementById('batch-pub-start')?.value;
  const startMs = startStr ? new Date(startStr).getTime() : Date.now();
  const provider = document.getElementById('batch-pub-ai-provider')?.value || 'deepseek';

  let uploaded = 0;

  for (let i = 0; i < pending.length; i++) {
    const item = pending[i];
    item.status = 'uploading';
    _batchPubRender();
    _batchPubLog(`🚀 [${i + 1}/${pending.length}] ${item.videoName}`, 'info');

    // Compute schedule time
    let scheduledDate = null;
    if (intervalH > 0) {
      const t = new Date(startMs + i * intervalH * 3600 * 1000);
      const minFuture = new Date(Date.now() + 5 * 60 * 1000);
      if (t > minFuture) scheduledDate = t;
    }

    try {
      // ── AI phân tích ASS (nếu chưa có aiResult) ──
      if (!item.aiResult && item.assFile) {
        _batchPubLog(`  🤖 AI đang phân tích ASS...`, 'info');
        try {
          const assText = await item.assFile.text();
          const plain = _extractPlainFromAss(assText);
          if (plain) {
            const res = await fetch('/api/analyze_video_content', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: plain.slice(0, 3000), provider })
            });
            const data = await res.json();
            if (data.ok) {
              item.aiResult = data.result;
              _batchPubLog(`  ✅ AI: "${(data.result?.youtube?.title || '').slice(0, 50)}"`, 'success');
            } else {
              _batchPubLog(`  ⚠ AI lỗi: ${data.error} — dùng tên file`, 'warning');
            }
          } else {
            _batchPubLog(`  ⚠ ASS trống — dùng tên file`, 'warning');
          }
        } catch (e) {
          _batchPubLog(`  ⚠ AI lỗi: ${e.message} — dùng tên file`, 'warning');
        }
      }

      // ── Upload video file lên server ──
      _batchPubLog(`  📤 Upload video...`, 'info');
      const form = new FormData();
      form.append('file', item.videoFile);
      const uploadRes = await fetch('/api/upload_batch_video', { method: 'POST', body: form });
      if (!uploadRes.ok) {
        const errText = await uploadRes.text();
        throw new Error(`Upload thất bại (HTTP ${uploadRes.status}): ${errText.slice(0, 100)}`);
      }
      const uploadData = await uploadRes.json();
      if (!uploadData.ok) throw new Error('Upload file thất bại: ' + (uploadData.error || ''));
      const videoPath = uploadData.path;

      // AI result (nếu chưa có, dùng tên file làm title)
      const ai = item.aiResult || {
        youtube: { title: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), description: '', tags: [] },
        tiktok: { caption: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), hashtags: [] },
        facebook: { title: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), description: '', hashtags: [] },
      };

      // Upload to each platform
      if (platforms.includes('youtube')) {
        await _batchPubUploadYT(videoPath, ai.youtube, scheduledDate);
      }
      if (platforms.includes('facebook')) {
        await _batchPubUploadFB(videoPath, ai.facebook, scheduledDate);
      }
      if (platforms.includes('tiktok')) {
        await _batchPubUploadTT(videoPath, ai.tiktok);
      }

      item.status = 'done';
      uploaded++;
      _batchPubLog(`✅ [${i + 1}/${pending.length}] Xong: ${item.videoName}`, 'success');
    } catch (e) {
      item.status = 'error';
      item.error = e.message;
      _batchPubLog(`❌ [${i + 1}/${pending.length}] Lỗi: ${e.message}`, 'error');
    }
    _batchPubRender();

    // Delay giữa các video
    if (i < pending.length - 1) {
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  window._batchPubRunning = false;
  if (btn) { btn.disabled = false; btn.textContent = '🚀 Đăng tất cả'; }
  _batchPubLog(`📊 Hoàn tất: ${uploaded}/${pending.length} thành công`, uploaded === pending.length ? 'success' : 'warning');
  toast(`Đăng hàng loạt xong: ${uploaded}/${pending.length}`, uploaded === pending.length ? 'success' : 'warning');
}

/* ── Platform upload helpers ── */
async function _batchPubUploadYT(videoPath, ytInfo, scheduledDate) {
  const accountId = document.getElementById('yt-account-select')?.value || '';
  const payload = {
    video_path: videoPath,
    title: (ytInfo?.title || '').slice(0, 100),
    description: ytInfo?.description || '',
    tags: Array.isArray(ytInfo?.tags) ? ytInfo.tags : [],
    privacy_status: scheduledDate ? 'private' : (document.getElementById('yt-privacy')?.value || 'public'),
    is_short: document.getElementById('yt-is-short')?.checked || false,
    publish_at: scheduledDate ? scheduledDate.toISOString() : null,
    account_id: accountId,
  };

  _batchPubLog(`  [YT] Đăng: "${payload.title.slice(0, 40)}..."`, 'info');
  const res = await fetch('/api/youtube_upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  // Stream response
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let lastResult = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split('\n').filter(Boolean)) {
      try {
        const d = JSON.parse(line);
        if (d.log) _batchPubLog(`  [YT] ${d.log}`, d.level || 'info');
        if (d.ok !== undefined) lastResult = d;
      } catch (_) {}
    }
  }
  if (lastResult && !lastResult.ok) throw new Error('YouTube upload failed');
}

async function _batchPubUploadFB(videoPath, fbInfo, scheduledDate) {
  const accountId = document.getElementById('pub-fb-account-select')?.value || '';
  const pageId = document.getElementById('pub-fb-page-select')?.value || '';
  if (!pageId) {
    _batchPubLog('  [FB] Bỏ qua — chưa chọn Page', 'warning');
    return;
  }

  const form = new FormData();
  form.append('video_path', videoPath);
  form.append('page_id', pageId);
  const stripTags = window._pStripInlineHashtags || (s => String(s || ''));
  const buildCap  = window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n'));
  form.append('title', stripTags(fbInfo?.title || ''));
  const fbHashStr = Array.isArray(fbInfo?.hashtags) ? fbInfo.hashtags.join(' ') : '';
  const desc = buildCap(fbInfo?.description || '', fbHashStr);
  form.append('description', desc.trim());
  if (scheduledDate) {
    form.append('scheduled_time', String(Math.floor(scheduledDate.getTime() / 1000)));
  }
  if (accountId) form.append('account_id', accountId);

  _batchPubLog(`  [FB] Đăng: "${(fbInfo?.title || '').slice(0, 40)}..."`, 'info');
  const res = await fetch('/api/facebook/post_video', { method: 'POST', body: form });

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let lastResult = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split('\n').filter(Boolean)) {
      try {
        const d = JSON.parse(line);
        if (d.log) _batchPubLog(`  [FB] ${d.log}`, d.level || 'info');
        if (d.ok !== undefined) lastResult = d;
      } catch (_) {}
    }
  }
  if (lastResult && !lastResult.ok) throw new Error('Facebook upload failed');
}

async function _batchPubUploadTT(videoPath, ttInfo) {
  const buildCap = window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n'));
  const ttHashStr = Array.isArray(ttInfo?.hashtags) ? ttInfo.hashtags.join(' ') : '';
  const caption = buildCap(ttInfo?.caption || '', ttHashStr);

  _batchPubLog(`  [TT] Mở TikTok Studio: "${caption.slice(0, 40)}..."`, 'info');
  const res = await fetch('/api/tiktok/prepare_upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_path: videoPath, caption: caption.trim() }),
  });
  const data = await res.json();
  if (!data.ok) {
    _batchPubLog(`  [TT] ⚠ ${data.error || 'Lỗi mở TikTok'}`, 'warning');
  } else {
    _batchPubLog(`  [TT] ✅ Đã mở TikTok Studio`, 'success');
  }
}


/* ════════════════════════════════════════════════════════════════
   PREFLIGHT CHECK — kiểm tra nền tảng sẵn sàng trước khi đăng
════════════════════════════════════════════════════════════════ */
async function _batchPubPreflight(platforms) {
  const issues = [];

  // ── YouTube: kiểm tra đã đăng nhập chưa ──
  if (platforms.includes('youtube')) {
    try {
      const res = await fetch('/api/youtube_auth');
      const data = await res.json();
      if (!data.authenticated) {
        issues.push({ platform: 'youtube', type: 'auth', msg: 'YouTube chưa đăng nhập' });
      }
    } catch (e) {
      issues.push({ platform: 'youtube', type: 'auth', msg: 'Không thể kiểm tra YouTube: ' + e.message });
    }
  }

  // ── Facebook: kiểm tra token + page ──
  if (platforms.includes('facebook')) {
    try {
      const res = await fetch('/api/facebook/status');
      const data = await res.json();
      if (!data.connected) {
        issues.push({ platform: 'facebook', type: 'token', msg: 'Facebook chưa kết nối (thiếu token)' });
      } else {
        // Kiểm tra đã chọn page chưa
        const pageId = document.getElementById('pub-fb-page-select')?.value || '';
        if (!pageId) {
          issues.push({ platform: 'facebook', type: 'page', msg: 'Chưa chọn Facebook Page' });
        }
      }
    } catch (e) {
      issues.push({ platform: 'facebook', type: 'token', msg: 'Không thể kiểm tra Facebook: ' + e.message });
    }
  }

  // ── TikTok: không cần token (dùng browser), chỉ cảnh báo ──
  // (TikTok mở trình duyệt nên không cần preflight)

  if (!issues.length) return true;

  // Hiển thị modal với các vấn đề
  return await _batchPubShowPreflightModal(issues);
}

function _batchPubShowPreflightModal(issues) {
  return new Promise((resolve) => {
    // Tạo modal overlay
    const overlay = document.createElement('div');
    overlay.id = 'batch-preflight-modal';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';

    let issueHtml = issues.map(iss => {
      let actionHtml = '';
      if (iss.type === 'auth' && iss.platform === 'youtube') {
        actionHtml = `<button class="btn btn-sm btn-yt" onclick="_batchPreflightYtLogin()">🔑 Đăng nhập YouTube</button>`;
      } else if (iss.type === 'token' && iss.platform === 'facebook') {
        actionHtml = `
          <div style="margin-top:8px">
            <input type="text" id="batch-pf-fb-token" placeholder="Dán User Access Token Facebook..." style="width:100%;font-size:12px;padding:6px 8px">
            <button class="btn btn-sm btn-fb mt-4" onclick="_batchPreflightFbConnect()">🔗 Kết nối Facebook</button>
          </div>`;
      } else if (iss.type === 'page' && iss.platform === 'facebook') {
        actionHtml = `
          <div style="margin-top:8px">
            <label style="font-size:11px;color:var(--text-muted)">Chọn Page:</label>
            <select id="batch-pf-fb-page" style="width:100%;font-size:12px;padding:6px" onchange="_batchPreflightFbPageSelect(this.value)">
              <option value="">-- Đang tải... --</option>
            </select>
          </div>`;
      }
      return `
        <div style="padding:10px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
          <div style="font-weight:600;color:var(--text)">⚠️ ${iss.msg}</div>
          ${actionHtml}
        </div>`;
    }).join('');

    overlay.innerHTML = `
      <div style="background:var(--bg);border-radius:12px;padding:24px;max-width:480px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
        <h3 style="margin:0 0 16px;font-size:16px;color:var(--text)">⚙️ Kiểm tra nền tảng</h3>
        <div id="batch-pf-issues">${issueHtml}</div>
        <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end">
          <button class="btn btn-secondary" onclick="_batchPreflightClose(false)">❌ Hủy</button>
          <button class="btn btn-primary" id="batch-pf-continue" onclick="_batchPreflightClose(true)">▶ Tiếp tục đăng</button>
        </div>
        <div class="text-xs text-muted mt-8">Bạn có thể bỏ qua nền tảng bị lỗi — hệ thống sẽ chỉ đăng lên nền tảng đã sẵn sàng.</div>
      </div>`;

    document.body.appendChild(overlay);

    // Load FB pages nếu cần
    const pageIssue = issues.find(i => i.type === 'page' && i.platform === 'facebook');
    if (pageIssue) {
      _batchPreflightLoadFbPages();
    }

    // Store resolve
    window._batchPreflightResolve = resolve;
  });
}

function _batchPreflightClose(proceed) {
  const modal = document.getElementById('batch-preflight-modal');
  if (modal) modal.remove();
  if (window._batchPreflightResolve) {
    window._batchPreflightResolve(proceed);
    window._batchPreflightResolve = null;
  }
}

async function _batchPreflightYtLogin() {
  try {
    const res = await fetch('/api/youtube_auth', { method: 'POST' });
    const data = await res.json();
    if (data.authenticated) {
      toast('✅ YouTube đã đăng nhập!', 'success');
      _batchPreflightClose(true);
      return;
    }
    if (data.auth_url) {
      const popup = window.open(data.auth_url, 'yt_auth', 'width=600,height=700');
      // Poll for auth completion
      const poll = setInterval(async () => {
        if (popup && popup.closed) { clearInterval(poll); return; }
        try {
          const r = await fetch('/api/youtube_auth');
          const d = await r.json();
          if (d.authenticated) {
            clearInterval(poll);
            popup?.close();
            toast('✅ Đăng nhập YouTube thành công!', 'success');
            if (typeof _updateYtAuthUI === 'function') _updateYtAuthUI(d.channel);
            _batchPreflightClose(true);
          }
        } catch (_) {}
      }, 2000);
    }
  } catch (e) {
    toast('Lỗi đăng nhập YouTube: ' + e.message, 'error');
  }
}

async function _batchPreflightFbConnect() {
  const token = document.getElementById('batch-pf-fb-token')?.value?.trim();
  if (!token) { toast('Vui lòng dán token', 'warning'); return; }

  try {
    const res = await fetch('/api/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Kết nối Facebook thành công!', 'success');
      // Reload FB status on main page
      if (typeof pubFbInit === 'function') pubFbInit();
      // Now load pages
      await _batchPreflightLoadFbPages();
    } else {
      toast('❌ ' + (data.error || 'Token không hợp lệ'), 'error');
    }
  } catch (e) {
    toast('Lỗi kết nối: ' + e.message, 'error');
  }
}

async function _batchPreflightLoadFbPages() {
  const sel = document.getElementById('batch-pf-fb-page');
  if (!sel) return;
  try {
    const res = await fetch('/api/facebook/status');
    const data = await res.json();
    if (data.connected && data.pages?.length) {
      sel.innerHTML = '<option value="">-- Chọn Page --</option>' +
        data.pages.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
    } else {
      sel.innerHTML = '<option value="">Không tìm thấy Page nào</option>';
    }
  } catch (e) {
    sel.innerHTML = '<option value="">Lỗi tải danh sách Page</option>';
  }
}

function _batchPreflightFbPageSelect(pageId) {
  if (!pageId) return;
  // Sync to main page selector
  const mainSel = document.getElementById('pub-fb-page-select');
  if (mainSel) {
    // Add option if not exists
    let found = false;
    for (const opt of mainSel.options) {
      if (opt.value === pageId) { opt.selected = true; found = true; break; }
    }
    if (!found) {
      const pfSel = document.getElementById('batch-pf-fb-page');
      const selectedText = pfSel?.options[pfSel.selectedIndex]?.text || pageId;
      const opt = new Option(selectedText, pageId, true, true);
      mainSel.appendChild(opt);
    }
  }
  toast('✅ Đã chọn Page', 'success');
}

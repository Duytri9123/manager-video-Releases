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

  const getBaseName = (name) => name.replace(/\.[^.]+$/, '').toLowerCase().trim();

  const pairs = [];
  const usedSubs = new Set();

  videos.forEach(v => {
    const vBase = getBaseName(v.name);
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
      status: 'pending',
      error: '',
    });
  });

  window._batchPubQueue.push(...pairs);
  _batchPubRender();

  const info = document.getElementById('batch-pub-info');
  if (info) info.value = `${pairs.length} cặp video (${videos.length} video, ${subs.length} phụ đề)`;
  toast(`✅ Đã import ${pairs.length} cặp video`, 'success');

  input.value = '';
}

/* ════════════════════════════════════════════════════════════════
   IMPORT FOLDER — quét thư mục, ghép cặp video + ASS theo tên
════════════════════════════════════════════════════════════════ */
function _batchPubImportFolder(input) {
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
    toast('Không tìm thấy file video nào trong thư mục', 'warning');
    input.value = '';
    return;
  }

  const getBaseName = (name) => name.replace(/\.[^.]+$/, '').toLowerCase().trim();

  const pairs = [];
  const usedSubs = new Set();

  videos.forEach(v => {
    const vBase = getBaseName(v.name);
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
      status: 'pending',
      error: '',
    });
  });

  window._batchPubQueue.push(...pairs);
  _batchPubRender();

  const info = document.getElementById('batch-pub-info');
  if (info) info.value = `${pairs.length} cặp video từ thư mục (${videos.length} video, ${subs.length} phụ đề)`;
  toast(`✅ Đã import ${pairs.length} cặp video từ thư mục`, 'success');

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
    if (typeof _pubQueueSaveToLocalStorage === 'function') _pubQueueSaveToLocalStorage();
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

  if (typeof _pubQueueSaveToLocalStorage === 'function') _pubQueueSaveToLocalStorage();
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

/* ── AI ANALYZE ALL ── */
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
      const assText = await item.assFile.text();
      const plain = _extractPlainFromAss(assText);

      if (!plain) {
        item.status = 'error';
        item.error = 'ASS trống hoặc không có Dialogue';
        _batchPubLog(`⚠ ${item.videoName}: ASS trống`, 'warning');
        continue;
      }

      const res = await fetch('/api/analyze_video_content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: plain.slice(0, 3000), provider, target_language: document.getElementById('batch-pub-target-lang')?.value || document.getElementById('proc-target-lang')?.value || 'vi' })
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

/* ── UPLOAD ALL ── */
async function _batchPubStartAll() {
  if (window._batchPubRunning) { toast('Đang chạy...', 'warning'); return; }

  const pending = window._batchPubQueue.filter(item => item.status === 'ready' || item.status === 'pending');
  if (!pending.length) {
    toast('Không có video nào sẵn sàng để đăng', 'warning');
    return;
  }

  const platforms = [];
  if (window._pubEnabled?.youtube) platforms.push('youtube');
  if (window._pubEnabled?.tiktok) platforms.push('tiktok');
  if (window._pubEnabled?.facebook) platforms.push('facebook');
  if (!platforms.length) {
    toast('Chưa bật nền tảng nào (bật YouTube/TikTok/Facebook ở panel bên phải)', 'warning');
    return;
  }

  const preflightOk = await _batchPubPreflight(platforms);
  if (!preflightOk) return;

  const btn = document.getElementById('btn-batch-pub-start');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }
  window._batchPubRunning = true;
  window._batchPubCancelled = false;

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

    let scheduledDate = null;
    if (intervalH > 0) {
      const t = new Date(startMs + i * intervalH * 3600 * 1000);
      const minFuture = new Date(Date.now() + 5 * 60 * 1000);
      if (t > minFuture) scheduledDate = t;
    }

    try {
      if (!item.aiResult && item.assFile) {
        _batchPubLog(`  🤖 AI đang phân tích ASS...`, 'info');
        try {
          const assText = await item.assFile.text();
          const plain = _extractPlainFromAss(assText);
          if (plain) {
            const res = await fetch('/api/analyze_video_content', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ content: plain.slice(0, 3000), provider, target_language: document.getElementById('batch-pub-target-lang')?.value || document.getElementById('proc-target-lang')?.value || 'vi' })
            });
            const data = await res.json();
            if (data.ok) {
              item.aiResult = data.result;
              _batchPubLog(`  ... AI: "${(data.result?.youtube?.title || '').slice(0, 50)}"`, 'success');
            } else {
              _batchPubLog(`  ... AI lỗi: ${data.error} — dùng tên file`, 'warning');
            }
          } else {
            _batchPubLog(`  ... ASS trống — dùng tên file`, 'warning');
          }
        } catch (e) {
          _batchPubLog(`  ... AI lỗi: ${e.message} — dùng tên file`, 'warning');
        }
      }

      let videoPath = "";
      if (item.videoFile) {
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
        videoPath = uploadData.path;
        item.videoPath = videoPath;
        item.abs_path = videoPath;
        _pubQueueSaveToLocalStorage();
      } else {
        videoPath = item.videoPath || item.abs_path || "";
      }

      const ai = item.aiResult || {
        youtube: { title: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), description: '', tags: [] },
        tiktok: { caption: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), hashtags: [] },
        facebook: { title: item.videoName.replace(/\.[^.]+$/, '').replace(/_/g, ' '), description: '', hashtags: [] },
      };

      for (const plat of platforms) {
        if (window._batchPubCancelled) break;
        const result = await _batchPubUploadWithRetry(plat, videoPath, ai, scheduledDate, item.videoName);
        if (result === 'cancel') {
          window._batchPubCancelled = true;
          throw new Error('User cancelled upload');
        }
      }

      if (window._batchPubCancelled) {
        item.status = 'cancelled';
        _batchPubLog(`🛑 [${i + 1}/${pending.length}] Đã huỷ: ${item.videoName}`, 'warning');
        break;
      }

      item.status = 'done';
      uploaded++;
      _batchPubLog(`... [${i + 1}/${pending.length}] Xong: ${item.videoName}`, 'success');
    } catch (e) {
      item.status = 'error';
      item.error = e.message;
      _batchPubLog(`... [${i + 1}/${pending.length}] Lỗi: ${e.message}`, 'error');
    }
    _batchPubRender();

    if (i < pending.length - 1) {
      await new Promise(r => setTimeout(r, 2000));
    }
  }

  window._batchPubRunning = false;
  if (btn) { btn.disabled = false; btn.textContent = '🚀 Đăng tất cả'; }
  _batchPubLog(`... Hoàn tất: ${uploaded}/${pending.length} thành công`, uploaded === pending.length ? 'success' : 'warning');
  toast(`Đăng hàng loạt xong: ${uploaded}/${pending.length}`, uploaded === pending.length ? 'success' : 'warning');
}

async function _batchPubUploadWithRetry(platform, videoPath, aiResult, scheduledDate, videoName) {
  const PLATFORM_FNS = {
    youtube:  () => _batchPubUploadYT(videoPath, aiResult.youtube, scheduledDate),
    facebook: () => _batchPubUploadFB(videoPath, aiResult.facebook, scheduledDate),
    tiktok:   () => _batchPubUploadTT(videoPath, aiResult.tiktok),
  };
  const uploadFn = PLATFORM_FNS[platform];
  if (!uploadFn) return 'skip';

  let attempt = 0;
  while (true) {
    attempt += 1;
    if (window._batchPubCancelled) return 'cancel';
    let result;
    try {
      result = await uploadFn();
    } catch (e) {
      result = { ok: false, error: e.message };
    }

    if (result.ok) {
      return 'ok';
    }
    if (result.skip) {
      _batchPubLog(`  [${platform.toUpperCase()}] ⏭ ${result.error}`, 'warning');
      return 'skip';
    }

    _batchPubLog(`  [${platform.toUpperCase()}] ❌ ${result.error}`, 'error');

    const action = await window.showUploadErrorModal({
      platform,
      title: `Upload ${platform} thất bại (lần ${attempt})`,
      video: videoName || (videoPath || '').split(/[\\/]/).pop(),
      error: result.error,
      errorCode: result.errorCode || '',
      tokenError: !!result.tokenError,
      diagnostic: JSON.stringify(result, null, 2),
    });

    if (action === 'retry') {
      _batchPubLog(`  [${platform.toUpperCase()}] 🔄 Thử lại lần ${attempt + 1}...`, 'info');
      continue;
    }
    if (action === 'skip') {
      _batchPubLog(`  [${platform.toUpperCase()}] ⏭ Bỏ qua video này`, 'warning');
      return 'skip';
    }
    _batchPubLog(`  [${platform.toUpperCase()}] 🛑 Huỷ toàn bộ`, 'error');
    return 'cancel';
  }
}

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
  let res;
  try {
    res = await fetch('/api/youtube_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return { ok: false, error: 'Lỗi mạng: ' + e.message };
  }

  if (!res.ok) {
    let errMsg = `HTTP ${res.status}`;
    let tokenErr = res.status === 401;
    try {
      const j = await res.json();
      errMsg = j.error || errMsg;
      tokenErr = tokenErr || /not authenticated|token|expired|oauth/i.test(errMsg);
    } catch (_) {}
    return { ok: false, error: errMsg, tokenError: tokenErr, errorCode: res.status };
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let lastResult = null;
  let lastErrLog = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split('\n').filter(Boolean)) {
      try {
        const d = JSON.parse(line);
        if (d.log) {
          _batchPubLog(`  [YT] ${d.log}`, d.level || 'info');
          if (d.level === 'error') lastErrLog = d.log;
        }
        if (d.ok !== undefined) lastResult = d;
      } catch (_) {}
    }
  }
  if (lastResult && lastResult.ok) return { ok: true, ...lastResult };
  const errMsg = lastErrLog || 'YouTube upload failed';
  const tokenErr = /token|oauth|expired|not authenticated|invalid_grant/i.test(errMsg);
  return { ok: false, error: errMsg, tokenError: tokenErr };
}

async function _batchPubUploadFB(videoPath, fbInfo, scheduledDate) {
  const accountId = document.getElementById('pub-fb-account-select')?.value || '';
  const pageId = document.getElementById('pub-fb-page-select')?.value || '';
  if (!pageId) {
    return { ok: false, error: 'Chưa chọn Facebook Page', skip: true };
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
  let res;
  try {
    res = await fetch('/api/facebook/post_video', { method: 'POST', body: form });
  } catch (e) {
    return { ok: false, error: 'Lỗi mạng: ' + e.message };
  }

  if (!res.ok) {
    let errMsg = `HTTP ${res.status}`;
    let tokenErr = false;
    try {
      const j = await res.json();
      errMsg = j.error || errMsg;
      tokenErr = !!j.token_error || res.status === 401;
    } catch (_) {}
    return { ok: false, error: errMsg, tokenError: tokenErr, errorCode: res.status };
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let lastResult = null;
  let lastErrLog = '';
  let tokenErr = false;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value, { stream: true });
    for (const line of text.split('\n').filter(Boolean)) {
      try {
        const d = JSON.parse(line);
        if (d.log) {
          _batchPubLog(`  [FB] ${d.log}`, d.level || 'info');
          if (d.level === 'error') lastErrLog = d.log;
        }
        if (d.token_error) tokenErr = true;
        if (d.ok !== undefined) lastResult = d;
      } catch (_) {}
    }
  }
  if (lastResult && lastResult.ok) return { ok: true, ...lastResult };
  const errMsg = lastErrLog || 'Facebook upload failed';
  return { ok: false, error: errMsg, tokenError: tokenErr || /token|expired|oauth|190|463/i.test(errMsg) };
}

async function _batchPubUploadTT(videoPath, ttInfo) {
  const buildCap = window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n'));
  const ttHashStr = Array.isArray(ttInfo?.hashtags) ? ttInfo.hashtags.join(' ') : '';
  const caption = buildCap(ttInfo?.caption || '', ttHashStr);

  _batchPubLog(`  [TT] Mở TikTok Studio: "${caption.slice(0, 40)}..."`, 'info');
  let res;
  try {
    res = await fetch('/api/tiktok/prepare_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_path: videoPath, caption: caption.trim() }),
    });
  } catch (e) {
    return { ok: false, error: 'Lỗi mạng: ' + e.message };
  }
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!data.ok) {
    const errMsg = data.error || `HTTP ${res.status}`;
    const tokenErr = /login|session|expired|not.*logged/i.test(errMsg);
    return { ok: false, error: errMsg, tokenError: tokenErr };
  }
  _batchPubLog(`  [TT] ✅ Đã mở TikTok Studio`, 'success');
  return { ok: true };
}

/* ── PREFLIGHT CHECK ── */
async function _batchPubPreflight(platforms) {
  const issues = [];

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

  if (platforms.includes('facebook')) {
    try {
      const res = await fetch('/api/facebook/status');
      const data = await res.json();
      if (!data.connected) {
        issues.push({ platform: 'facebook', type: 'token', msg: 'Facebook chưa kết nối (thiếu token)' });
      } else {
        const pageId = document.getElementById('pub-fb-page-select')?.value || '';
        if (!pageId) {
          issues.push({ platform: 'facebook', type: 'page', msg: 'Chưa chọn Facebook Page' });
        }
      }
    } catch (e) {
      issues.push({ platform: 'facebook', type: 'token', msg: 'Không thể kiểm tra Facebook: ' + e.message });
    }
  }

  if (!issues.length) return true;

  return await _batchPubShowPreflightModal(issues);
}

function _batchPubShowPreflightModal(issues) {
  return new Promise((resolve) => {
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

    const pageIssue = issues.find(i => i.type === 'page' && i.platform === 'facebook');
    if (pageIssue) {
      _batchPreflightLoadFbPages();
    }

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
      if (typeof pubFbInit === 'function') pubFbInit();
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
  const mainSel = document.getElementById('pub-fb-page-select');
  if (mainSel) {
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

/* ══════════════════════════════════════════════
   LOCALSTORAGE SYNCHRONIZATION
   ══════════════════════════════════════════════ */
window._pubQueueRefresh = function() {
  try {
    const localQueue = JSON.parse(localStorage.getItem('_pub_queue') || '[]');
    const newQueue = [];
    localQueue.forEach(localItem => {
      const existing = window._batchPubQueue.find(item => 
        (item.abs_path === localItem.abs_path || item.videoPath === localItem.abs_path)
      );
      if (existing) {
        newQueue.push(existing);
      } else {
        newQueue.push({
          id: 'bp-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
          videoFile: null,
          assFile: null,
          videoName: localItem.name || (localItem.abs_path || '').split(/[\\/]/).pop(),
          videoPath: localItem.abs_path,
          abs_path: localItem.abs_path,
          assName: '(không có)',
          aiResult: null,
          status: 'ready',
          error: '',
          added: localItem.added || Date.now()
        });
      }
    });

    // Keep manually added files
    window._batchPubQueue.forEach(item => {
      if (item.videoFile && !newQueue.some(ni => ni.id === item.id)) {
        newQueue.push(item);
      }
    });

    window._batchPubQueue = newQueue;
    _batchPubRender();
  } catch (e) {
    console.error('Error in _pubQueueRefresh:', e);
  }
};

window._pubQueueSaveToLocalStorage = function() {
  try {
    const listToSave = window._batchPubQueue
      .filter(item => item.abs_path || item.videoPath)
      .map(item => ({
        abs_path: item.abs_path || item.videoPath,
        name: item.videoName,
        added: item.added || Date.now()
      }));
    localStorage.setItem('_pub_queue', JSON.stringify(listToSave));
  } catch (e) {
    console.error('Error saving pub queue to localStorage:', e);
  }
};

// Run initial sync on load
window._pubQueueRefresh();

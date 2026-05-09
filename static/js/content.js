/* ── content.js — Quản lý nội dung bài đăng (Files / Facebook / YouTube / TikTok) ── */
/* NOTE: cptSwitch() và _CPT_PANELS được định nghĩa trong app.js để đảm bảo
   luôn available khi inline onclick trong HTML được gọi. */

/* ════════════════════════════════════════════════════════════
   TAB: FILE TẢI VỀ
════════════════════════════════════════════════════════════ */
let _contentFiles = [];

async function loadContentList() {
  const container = document.getElementById('content-list-container');
  if (!container) return;
  container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)"><div class="spinner mb-12" style="margin:0 auto"></div>Đang tải...</div>';
  try {
    const res  = await fetch('/api/content/list');
    const data = await res.json();
    if (data.ok) { _contentFiles = data.files; renderContentList(); }
    else container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">Lỗi: ${data.error}</div>`;
  } catch (e) {
    container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">Lỗi kết nối: ${e.message}</div>`;
  }
}

function renderContentList() {
  const container = document.getElementById('content-list-container');
  if (!container) return;
  const search   = document.getElementById('content-search')?.value.toLowerCase() || '';
  const filtered = _contentFiles.filter(f => f.name.toLowerCase().includes(search));

  if (!filtered.length) {
    container.innerHTML = '<div style="padding:60px;text-align:center;color:var(--text-muted)"><div style="font-size:40px;margin-bottom:10px">📂</div>Không tìm thấy tệp nào</div>';
    return;
  }

  const isMobile = window.innerWidth < 640;

  if (isMobile) {
    // ── Mobile: card list ──
    let html = '<div style="display:flex;flex-direction:column;gap:8px;padding:10px">';
    filtered.forEach(f => {
      const size = f.size >= 1048576 ? (f.size / 1048576).toFixed(2) + ' MB' : (f.size / 1024).toFixed(1) + ' KB';
      const date = new Date(f.mtime * 1000).toLocaleString('vi-VN', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
      const ext  = f.ext.replace('.', '');
      const icon = ['mp4','mkv','avi','mov'].includes(ext) ? '🎬' : ['ass','srt'].includes(ext) ? '📝' : ext === 'json' ? '⚙️' : ['jpg','jpeg','png','webp'].includes(ext) ? '🖼️' : '📄';
      const safeName = f.name.replace(/'/g, "\\'");
      const isVideo = ['mp4','mkv','avi','mov'].includes(ext);

      html += `<div style="background:var(--bg2);border:1.5px solid var(--border);border-radius:10px;padding:12px;display:flex;gap:10px;align-items:flex-start">
        <div style="width:36px;height:36px;border-radius:8px;background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0">${icon}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:600;color:var(--text);word-break:break-word;line-height:1.4;margin-bottom:4px">${f.name}</div>
          <div style="font-size:11px;color:var(--text-muted)">${size} · ${date}</div>
          <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
            <a href="/api/files/download?path=${encodeURIComponent(f.name)}" download="${f.name}"
               class="btn btn-sm btn-primary" style="padding:5px 10px;font-size:11px;text-decoration:none">⬇ Tải về</a>
            ${isVideo ? `<button class="btn btn-sm btn-secondary" style="padding:5px 10px;font-size:11px" onclick="sendToPublishFromContent('${safeName}')">📤 Đăng</button>` : ''}
            ${isVideo ? `<button class="btn btn-sm btn-secondary" style="padding:5px 10px;font-size:11px" onclick="sendToProcessFromContent('${safeName}')">🎬 Xử lý</button>` : ''}
            <button class="btn btn-sm" style="padding:5px 10px;font-size:11px;background:var(--error-bg);color:var(--error);border:1px solid rgba(192,57,43,.3)" onclick="deleteContentFile('${safeName}')">🗑</button>
          </div>
        </div>
      </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
    return;
  }

  // ── Desktop: table ──
  let html = `<table class="content-table"><thead><tr>
    <th>Tên tệp</th><th>Kích thước</th><th>Ngày tạo</th><th style="text-align:right">Thao tác</th>
  </tr></thead><tbody>`;

  filtered.forEach(f => {
    const date = new Date(f.mtime * 1000).toLocaleString('vi-VN');
    const size = f.size >= 1048576 ? (f.size / 1048576).toFixed(2) + ' MB' : (f.size / 1024).toFixed(1) + ' KB';
    const ext  = f.ext.replace('.', '');
    const icon = ['mp4','mkv','avi','mov'].includes(ext) ? '🎬' : ['ass','srt'].includes(ext) ? '📝' : ext === 'json' ? '⚙️' : ['jpg','jpeg','png','webp'].includes(ext) ? '🖼️' : '📄';
    const safeName = f.name.replace(/'/g, "\\'");
    html += `<tr>
      <td><div class="file-name-cell">
        <div class="file-icon ext-${ext}">${icon}</div>
        <div><div class="file-name">${f.name}</div><div class="file-meta">${f.path}</div></div>
      </div></td>
      <td style="white-space:nowrap">${size}</td>
      <td style="white-space:nowrap">${date}</td>
      <td><div class="content-actions">
        <a href="/api/files/download?path=${encodeURIComponent(f.name)}" download="${f.name}"
           class="btn-action" title="Tải về" style="display:flex;align-items:center;justify-content:center;text-decoration:none">⬇️</a>
        <button class="btn-action" onclick="sendToProcessFromContent('${safeName}')" title="Gửi sang Xử lý">🎬</button>
        <button class="btn-action" onclick="sendToPublishFromContent('${safeName}')" title="Gửi sang Đăng bài">📤</button>
        <button class="btn-action" onclick="fbMgrPrefillVideo('${safeName}')" title="Đăng lên Facebook">📘</button>
        <button class="btn-action" onclick="renameContentFile('${safeName}')" title="Đổi tên">✏️</button>
        <button class="btn-action btn-delete" onclick="deleteContentFile('${safeName}')" title="Xóa">🗑️</button>
      </div></td>
    </tr>`;
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}

async function deleteContentFile(name) {
  if (!confirm(`Bạn có chắc muốn xóa tệp "${name}"?`)) return;
  try {
    const res  = await fetch('/api/content/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ filename: name }) });
    const data = await res.json();
    if (data.ok) { toast(data.message, 'success'); loadContentList(); }
    else toast(data.error, 'error');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

async function renameContentFile(name) {
  const newName = prompt('Nhập tên mới:', name);
  if (!newName || newName === name) return;
  try {
    const res  = await fetch('/api/content/rename', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ old_name: name, new_name: newName }) });
    const data = await res.json();
    if (data.ok) { toast(data.message, 'success'); loadContentList(); }
    else toast(data.error, 'error');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

function sendToProcessFromContent(name) {
  if (!name.match(/\.(mp4|mkv|avi|mov)$/i)) { toast('Chỉ có thể xử lý tệp video', 'warning'); return; }
  switchPage('process');
  const input = document.getElementById('proc-video-path');
  if (input) { input.value = 'Downloaded/' + name; input.dispatchEvent(new Event('input')); }
  toast('Đã chuyển sang trang Xử lý', 'success');
}

function sendToPublishFromContent(name) {
  if (!name.match(/\.(mp4|mkv|avi|mov)$/i)) { toast('Chỉ có thể đăng tệp video', 'warning'); return; }
  switchPage('publish');
  const input = document.getElementById('pub-video-path');
  if (input) { input.value = 'Downloaded/' + name; }
  toast('Đã chuyển sang trang Đăng bài', 'success');
}

function fbMgrPrefillVideo(name) {
  if (!name.match(/\.(mp4|mkv|avi|mov)$/i)) { toast('Chỉ có thể đăng tệp video lên Facebook', 'warning'); return; }
  cptSwitch('facebook');
  setTimeout(() => {
    const input = document.getElementById('fb-post-video-path');
    if (input) input.value = 'Downloaded/' + name;
    window._fbMgrVideoFile = null;
    fbMgrSwitchPostTab('video');
    toast('Đã điền đường dẫn video vào form Facebook', 'info');
  }, 200);
}

/* ════════════════════════════════════════════════════════════
   TAB: FACEBOOK
════════════════════════════════════════════════════════════ */
window._fbMgrSelectedPage = null;
window._fbMgrVideoFile    = null;
window._fbMgrPages        = [];

async function fbMgrInit() {
  try {
    const res  = await fetch('/api/facebook/status');
    const data = await res.json();
    if (data.connected) {
      _fbMgrShowConnected(data.user, data.pages);
    } else {
      _fbMgrShowDisconnected();
    }
  } catch (e) {
    _fbMgrShowDisconnected();
  }
}

function _fbMgrShowDisconnected() {
  document.getElementById('fb-mgr-connect-form').style.display    = 'block';
  document.getElementById('fb-mgr-connected-info').style.display  = 'none';
  document.getElementById('fb-mgr-pages-card').style.display      = 'none';
  document.getElementById('fb-mgr-post-form').style.display       = 'none';
  document.getElementById('fb-mgr-no-page-msg').style.display     = 'block';
  document.getElementById('fb-mgr-recent-card').style.display     = 'none';
  const badge = document.getElementById('fb-mgr-status-badge');
  if (badge) badge.innerHTML = '<span class="badge badge-gray">Chưa kết nối</span>';
}

function _fbMgrShowConnected(user, pages) {
  document.getElementById('fb-mgr-connect-form').style.display   = 'none';
  document.getElementById('fb-mgr-connected-info').style.display = 'block';
  document.getElementById('fb-mgr-user-name').textContent = user.name || '--';
  document.getElementById('fb-mgr-user-id').textContent   = 'ID: ' + (user.id || '--');

  const badge = document.getElementById('fb-mgr-status-badge');
  if (badge) badge.innerHTML = '<span class="badge badge-green">✓ Đã kết nối</span>';

  window._fbMgrPages = pages || [];
  _fbMgrRenderPages(pages);
}

function _fbMgrRenderPages(pages) {
  const card = document.getElementById('fb-mgr-pages-card');
  const list = document.getElementById('fb-mgr-pages-list');
  const cnt  = document.getElementById('fb-mgr-page-count');
  if (!card || !list) return;

  if (!pages || !pages.length) {
    card.style.display = 'none';
    return;
  }

  card.style.display = 'block';
  if (cnt) cnt.textContent = pages.length;

  list.innerHTML = pages.map(p => `
    <div class="fb-page-card ${window._fbMgrSelectedPage?.id === p.id ? 'selected' : ''}"
         id="fb-page-card-${p.id}"
         onclick="fbMgrSelectPage('${p.id}')">
      <div class="fb-page-avatar">📄</div>
      <div style="flex:1;min-width:0">
        <div class="fb-page-name">${p.name}</div>
        <div class="fb-page-cat">${p.category || ''} · ID: ${p.id}</div>
      </div>
      <span style="font-size:18px;color:var(--text-muted)">›</span>
    </div>
  `).join('');
}

function fbMgrSelectPage(pageId) {
  const page = window._fbMgrPages.find(p => p.id === pageId);
  if (!page) return;
  window._fbMgrSelectedPage = page;

  // Update card highlights
  window._fbMgrPages.forEach(p => {
    const card = document.getElementById('fb-page-card-' + p.id);
    if (card) card.classList.toggle('selected', p.id === pageId);
  });

  // Show post form
  document.getElementById('fb-mgr-no-page-msg').style.display  = 'none';
  document.getElementById('fb-mgr-post-form').style.display    = 'block';
  document.getElementById('fb-mgr-recent-card').style.display  = 'block';

  const badge = document.getElementById('fb-mgr-selected-page-badge');
  if (badge) { badge.textContent = page.name; badge.style.display = 'inline-flex'; }

  fbMgrLoadPosts();
}

async function fbMgrConnect() {
  const token = document.getElementById('fb-mgr-token-input')?.value?.trim();
  if (!token) { toast('Vui lòng nhập Access Token', 'warning'); return; }

  const btn = document.getElementById('btn-fb-mgr-connect');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang kết nối...'; }

  try {
    const res  = await fetch('/api/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await res.json();
    if (data.ok) {
      toast(`✅ Kết nối thành công! Tìm thấy ${data.pages.length} Page`, 'success');
      _fbMgrShowConnected(data.user, data.pages);
    } else {
      toast('❌ ' + (data.error || 'Kết nối thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi kết nối: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔗 Kết nối & Lấy danh sách Pages'; }
  }
}

async function fbMgrDisconnect() {
  if (!confirm('Ngắt kết nối Facebook?')) return;
  try {
    await fetch('/api/facebook/disconnect', { method: 'POST' });
    window._fbMgrSelectedPage = null;
    window._fbMgrPages = [];
    _fbMgrShowDisconnected();
    toast('Đã ngắt kết nối Facebook', 'info');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

function fbMgrToggleToken() {
  const input = document.getElementById('fb-mgr-token-input');
  if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

function fbMgrSetVideoFile(input) {
  const file = input.files?.[0] || null;
  window._fbMgrVideoFile = file;
  const el = document.getElementById('fb-post-video-path');
  if (el) el.value = file ? file.name : '';
  input.value = '';
  if (file) toast('✅ Đã chọn: ' + file.name, 'success');
}

/* ── Facebook AI helpers (content page) ── */
function fbMgrLoadAssFile(mode) {
  const id = mode === 'video' ? 'fb-post-ass-file' : 'fb-text-ass-file';
  document.getElementById(id)?.click();
}

async function fbMgrReadAssFile(input, mode) {
  const file = input.files?.[0];
  if (!file) return;
  const text = await file.text();
  const plain = _fbExtractPlainText(text, file.name);
  const taId = mode === 'video' ? 'fb-post-ai-input' : 'fb-text-ai-input';
  const ta = document.getElementById(taId);
  if (ta) ta.value = plain.slice(0, 3000);
  input.value = '';
  toast('✅ Đã nhập nội dung từ ' + file.name, 'success');
}

function _fbExtractPlainText(text, filename) {
  const name = (filename || '').toLowerCase();
  if (name.endsWith('.ass')) {
    const parts = [];
    for (const line of text.split(/\r?\n/)) {
      if (!line.startsWith('Dialogue:')) continue;
      const cols = line.split(',');
      if (cols.length < 10) continue;
      const t = cols.slice(9).join(',').replace(/\{[^}]*\}/g,'').replace(/\\N/g,' ').replace(/\\n/g,' ').trim();
      if (t) parts.push(t);
    }
    return parts.join(' ');
  }
  if (name.endsWith('.srt')) {
    return text.replace(/^\d+\s*$/gm,'')
               .replace(/\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}/g,'')
               .replace(/<[^>]+>/g,'').replace(/\n+/g,' ').trim();
  }
  return text.trim();
}

async function fbMgrGenerateAI(mode) {
  const inputId    = mode === 'video' ? 'fb-post-ai-input'    : 'fb-text-ai-input';
  const provId     = mode === 'video' ? 'fb-post-ai-provider' : 'fb-text-ai-provider';
  const statusId   = mode === 'video' ? 'fb-post-ai-status'   : 'fb-text-ai-status';
  const btnId      = mode === 'video' ? 'btn-fb-post-ai'      : 'btn-fb-text-ai';
  const titleId    = mode === 'video' ? 'fb-post-title'       : null;
  const descId     = mode === 'video' ? 'fb-post-desc'        : 'fb-post-text-msg';

  const content  = document.getElementById(inputId)?.value?.trim();
  if (!content) { toast('Vui lòng nhập nội dung trước', 'warning'); return; }

  const provider = document.getElementById(provId)?.value || 'deepseek';
  const btn      = document.getElementById(btnId);
  const status   = document.getElementById(statusId);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang tạo...'; }
  if (status) status.textContent = 'Đang gọi AI...';

  try {
    const res  = await fetch('/api/analyze_video_content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, provider })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI thất bại');

    const info = data.result || {};
    const fb   = info.facebook || {};

    if (titleId) {
      const titleEl = document.getElementById(titleId);
      if (titleEl && fb.title) titleEl.value = fb.title;
    }
    const descEl = document.getElementById(descId);
    if (descEl) {
      const hashtags = Array.isArray(fb.hashtags) ? fb.hashtags.join(' ') : (fb.hashtags || '');
      descEl.value = [fb.description, hashtags].filter(Boolean).join('\n\n');
    }

    if (status) status.textContent = '✅ Đã tạo nội dung';
    toast('✅ AI tạo nội dung thành công!', 'success');
  } catch (e) {
    if (status) status.textContent = '❌ ' + e.message;
    toast('Lỗi AI: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ Tạo nội dung bằng AI'; }
  }
}

function fbMgrSwitchPostTab(tab) {
  const isVideo = tab === 'video';
  document.getElementById('fb-post-panel-video').style.display = isVideo ? 'block' : 'none';
  document.getElementById('fb-post-panel-text').style.display  = isVideo ? 'none'  : 'block';
  const btnV = document.getElementById('fb-post-tab-video');
  const btnT = document.getElementById('fb-post-tab-text');
  if (btnV) { btnV.style.background = isVideo ? 'var(--accent)' : ''; btnV.style.color = isVideo ? '#fff' : ''; btnV.className = isVideo ? 'btn btn-sm' : 'btn btn-sm btn-secondary'; }
  if (btnT) { btnT.style.background = !isVideo ? 'var(--accent)' : ''; btnT.style.color = !isVideo ? '#fff' : ''; btnT.className = !isVideo ? 'btn btn-sm' : 'btn btn-sm btn-secondary'; }
}

function _fbLog(msg, level) {
  const box = document.getElementById('fb-post-log');
  if (!box) return;
  box.style.display = 'block';
  const d = document.createElement('div');
  d.className = 'log-' + (level || 'info');
  d.textContent = '[' + new Date().toTimeString().slice(0,8) + '] ' + msg;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

async function fbMgrPostVideo() {
  const page = window._fbMgrSelectedPage;
  if (!page) { toast('Vui lòng chọn Page trước', 'warning'); return; }

  const videoFile = window._fbMgrVideoFile;
  const videoPath = document.getElementById('fb-post-video-path')?.value?.trim();
  if (!videoFile && !videoPath) { toast('Vui lòng chọn file video', 'warning'); return; }

  const title    = document.getElementById('fb-post-title')?.value?.trim() || '';
  const desc     = document.getElementById('fb-post-desc')?.value?.trim()  || '';
  const privacy  = document.getElementById('fb-post-privacy')?.value || 'EVERYONE';
  const schedVal = document.getElementById('fb-post-schedule')?.value;
  let scheduledTime = '';
  if (schedVal) {
    const dt = new Date(schedVal);
    const minFuture = new Date(Date.now() + 10 * 60 * 1000); // FB requires 10 min ahead
    if (dt > minFuture) scheduledTime = Math.floor(dt.getTime() / 1000).toString();
    else { toast('Thời gian đặt lịch phải ít nhất 10 phút trong tương lai', 'warning'); return; }
  }

  const btn = document.getElementById('btn-fb-post-video');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }
  const logBox = document.getElementById('fb-post-log');
  if (logBox) { logBox.style.display = 'block'; logBox.innerHTML = ''; }

  try {
    const form = new FormData();
    form.append('page_id', page.id);
    form.append('title', title);
    form.append('description', desc);
    form.append('privacy', privacy);
    if (scheduledTime) form.append('scheduled_time', scheduledTime);
    if (videoFile) {
      form.append('video_file', videoFile);
    } else {
      form.append('video_path', videoPath);
    }

    const res = await fetch('/api/facebook/post_video', { method: 'POST', body: form });
    if (!res.ok || !res.body) throw new Error('Không thể kết nối server');

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop() || '';
      for (const line of lines) {
        const t = line.trim(); if (!t) continue;
        try {
          const d = JSON.parse(t);
          if (d.log) _fbLog(d.log, d.level || 'info');
          if (d.url) { _fbLog('🔗 ' + d.url, 'success'); toast('✅ Đăng Facebook thành công!', 'success', 6000); }
        } catch (_) { _fbLog(t, 'info'); }
      }
    }
  } catch (e) {
    _fbLog('❌ ' + e.message, 'error');
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Đăng Video lên Facebook'; }
  }
}

async function fbMgrPostText() {
  const page = window._fbMgrSelectedPage;
  if (!page) { toast('Vui lòng chọn Page trước', 'warning'); return; }

  const message = document.getElementById('fb-post-text-msg')?.value?.trim();
  const link    = document.getElementById('fb-post-text-link')?.value?.trim() || '';
  const privacy = document.getElementById('fb-post-text-privacy')?.value || 'EVERYONE';
  if (!message) { toast('Vui lòng nhập nội dung bài viết', 'warning'); return; }

  const btn = document.getElementById('btn-fb-post-text');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }

  try {
    const res  = await fetch('/api/facebook/post_text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: page.id, message, link, privacy })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Đã đăng bài viết thành công!', 'success');
      document.getElementById('fb-post-text-msg').value = '';
      document.getElementById('fb-post-text-link').value = '';
      fbMgrLoadPosts();
    } else {
      toast('❌ ' + (data.error || 'Đăng thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📝 Đăng bài viết'; }
  }
}

async function fbMgrLoadPosts() {
  const page = window._fbMgrSelectedPage;
  if (!page) return;
  const list = document.getElementById('fb-mgr-posts-list');
  if (!list) return;
  list.innerHTML = '<div class="text-muted text-sm" style="text-align:center;padding:16px">Đang tải...</div>';

  try {
    const res  = await fetch('/api/facebook/page_posts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: page.id, limit: 5 })
    });
    const data = await res.json();
    if (!data.ok) {
      // Show detailed error for debugging
      const errMsg = data.error || 'Lỗi không xác định';
      list.innerHTML = `<div style="padding:12px;font-size:11px;color:var(--error);word-break:break-word">
        ❌ ${errMsg}
        ${data.debug_errors ? '<br><br><b>Chi tiết:</b><br>' + data.debug_errors.map(e => `• ${JSON.stringify(e)}`).join('<br>') : ''}
      </div>`;
      return;
    }

    const posts = data.posts || [];
    if (!posts.length) { list.innerHTML = '<div class="text-muted text-sm" style="text-align:center;padding:16px">Chưa có bài đăng nào</div>'; return; }

    list.innerHTML = posts.map(p => {
      const msg  = (p.message || p.story || '(Không có nội dung)').slice(0, 120);
      const date = new Date(p.created_time).toLocaleString('vi-VN');
      // likes/comments returned as {data:[...]} array or summary object
      const likes = p.likes?.summary?.total_count ?? p.likes?.data?.length ?? (p.likes ? '✓' : '--');
      const cmts  = p.comments?.summary?.total_count ?? p.comments?.data?.length ?? (p.comments ? '✓' : '--');
      const url   = p.permalink_url || '#';
      return `<div class="fb-post-item">
        <div class="fb-post-msg">${msg}${(p.message||'').length > 120 ? '...' : ''}</div>
        <div class="fb-post-meta">
          <span>📅 ${date}</span>
          <span>👍 ${likes}</span>
          <span>💬 ${cmts}</span>
          ${url !== '#' ? `<a href="${url}" target="_blank" style="color:var(--accent)">🔗 Xem</a>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    list.innerHTML = `<div class="text-muted text-sm" style="padding:12px">Lỗi: ${e.message}</div>`;
  }
}

/* ════════════════════════════════════════════════════════════
   TAB: YOUTUBE — Quản lý video
════════════════════════════════════════════════════════════ */
let _ytMgrNextToken = null;
let _ytMgrPrevToken = null;
let _ytMgrTokenStack = []; // history for prev page

async function ytMgrInit() {
  try {
    const res  = await fetch('/api/youtube_auth');
    const data = await res.json();
    if (data.authenticated && data.channel) {
      _ytMgrShowConnected(data.channel);
    } else {
      _ytMgrShowDisconnected();
    }
  } catch (_) { _ytMgrShowDisconnected(); }
}

function _ytMgrShowDisconnected() {
  const dc = document.getElementById('yt-mgr-disconnected-row');
  const cn = document.getElementById('yt-mgr-connected-row');
  const sec = document.getElementById('yt-mgr-video-section');
  if (dc) dc.style.display = 'flex';
  if (cn) cn.style.display = 'none';
  if (sec) sec.style.display = 'none';
}

function _ytMgrShowConnected(channel) {
  const dc = document.getElementById('yt-mgr-disconnected-row');
  const cn = document.getElementById('yt-mgr-connected-row');
  const sec = document.getElementById('yt-mgr-video-section');
  if (dc) dc.style.display = 'none';
  if (cn) cn.style.display = 'flex';
  if (sec) sec.style.display = 'block';

  const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  setText('yt-mgr-ch-name', channel.title || '--');
  const n = parseInt(channel.subscribers || 0);
  setText('yt-mgr-ch-subs', n >= 1000 ? (n/1000).toFixed(1)+'K' : (n || 'Ẩn'));
  setText('yt-mgr-ch-videos', channel.video_count || '--');

  const img = document.getElementById('yt-mgr-avatar');
  const ph  = document.getElementById('yt-mgr-avatar-ph');
  if (img && channel.thumbnail) {
    img.src = channel.thumbnail; img.style.display = 'block';
    if (ph) ph.style.display = 'none';
  }

  _ytMgrTokenStack = [];
  _ytMgrNextToken = null;
  ytMgrLoadVideos();
}

async function ytMgrLoadVideos(pageToken) {
  const grid = document.getElementById('yt-mgr-video-grid');
  if (!grid) return;
  grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)"><div class="spinner mb-12" style="margin:0 auto"></div>Đang tải video...</div>';

  const privacy = document.getElementById('yt-mgr-filter-privacy')?.value || '';
  let url = '/api/youtube_videos?max_results=12';
  if (pageToken) url += '&page_token=' + encodeURIComponent(pageToken);

  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (!data.ok) { grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">❌ ${data.error}</div>`; return; }

    let videos = data.videos || [];
    if (privacy) videos = videos.filter(v => v.privacy === privacy);

    _ytMgrNextToken = data.next_page_token || null;
    _ytMgrPrevToken = data.prev_page_token || null;

    // Pagination buttons
    const btnNext = document.getElementById('btn-yt-mgr-next');
    const btnPrev = document.getElementById('btn-yt-mgr-prev');
    const info    = document.getElementById('yt-mgr-page-info');
    if (btnNext) btnNext.style.display = _ytMgrNextToken ? 'inline-flex' : 'none';
    if (btnPrev) btnPrev.style.display = _ytMgrTokenStack.length > 0 ? 'inline-flex' : 'none';
    if (info) info.textContent = `${videos.length} video`;

    if (!videos.length) {
      grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)">📭 Không có video nào</div>';
      return;
    }

    grid.innerHTML = videos.map(v => _ytMgrVideoCard(v)).join('');
  } catch (e) {
    grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">❌ Lỗi: ${e.message}</div>`;
  }
}

function ytMgrNextPage() {
  if (!_ytMgrNextToken) return;
  _ytMgrTokenStack.push(_ytMgrNextToken);
  ytMgrLoadVideos(_ytMgrNextToken);
}

function ytMgrPrevPage() {
  _ytMgrTokenStack.pop(); // remove current
  const prev = _ytMgrTokenStack.pop() || null;
  ytMgrLoadVideos(prev);
}

function _fmtDuration(iso) {
  if (!iso) return '';
  const m = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return '';
  const h = parseInt(m[1]||0), min = parseInt(m[2]||0), s = parseInt(m[3]||0);
  if (h) return `${h}:${String(min).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${min}:${String(s).padStart(2,'0')}`;
}

function _fmtNum(n) {
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'K';
  return String(n);
}

function _ytMgrVideoCard(v) {
  const privacyLabel = { public:'🌐 Công khai', unlisted:'🔗 Không công khai', private:'🔒 Riêng tư' }[v.privacy] || v.privacy;
  const privacyCls   = { public:'yt-privacy-public', unlisted:'yt-privacy-unlisted', private:'yt-privacy-private' }[v.privacy] || '';
  const dur   = _fmtDuration(v.duration);
  const date  = v.published_at ? new Date(v.published_at).toLocaleDateString('vi-VN') : '';
  const safeId    = v.id.replace(/'/g, "\\'");
  const safeTitle = (v.title||'').replace(/'/g,"\\'").replace(/"/g,'&quot;');

  // Extra badges
  const licBadge = v.license === 'creativeCommon'
    ? '<span style="font-size:10px;background:#e8f5e9;color:#2e7d32;padding:1px 5px;border-radius:8px;font-weight:600">CC</span>'
    : '';
  const hdBadge = v.definition === 'hd'
    ? '<span style="font-size:10px;background:#e3f2fd;color:#1565c0;padding:1px 5px;border-radius:8px;font-weight:600">HD</span>'
    : '';
  const capBadge = v.caption === 'true'
    ? '<span style="font-size:10px;background:#fff3e0;color:#e65100;padding:1px 5px;border-radius:8px;font-weight:600">CC phụ đề</span>'
    : '';
  const kidsBadge = v.made_for_kids
    ? '<span style="font-size:10px;background:#fce4ec;color:#c62828;padding:1px 5px;border-radius:8px;font-weight:600">Trẻ em</span>'
    : '';

  return `<div class="yt-video-card">
    <div style="position:relative">
      ${v.thumbnail
        ? `<img class="yt-video-thumb" src="${v.thumbnail}" alt="" loading="lazy">`
        : `<div class="yt-video-thumb-ph">▶</div>`}
      ${dur ? `<span style="position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.8);color:#fff;font-size:10px;padding:2px 5px;border-radius:3px">${dur}</span>` : ''}
    </div>
    <div class="yt-video-info">
      <div class="yt-video-title" title="${safeTitle}">${v.title || '(Không có tiêu đề)'}</div>
      <div class="yt-video-meta">
        <span>👁 ${_fmtNum(v.views)}</span>
        <span>👍 ${_fmtNum(v.likes)}</span>
        <span>💬 ${_fmtNum(v.comments)}</span>
        ${date ? `<span>📅 ${date}</span>` : ''}
      </div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">
        ${licBadge}${hdBadge}${capBadge}${kidsBadge}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
        <span class="yt-privacy-badge ${privacyCls}">${privacyLabel}</span>
        <div class="yt-video-actions">
          <a href="${v.url}" target="_blank" class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px" title="Xem trên YouTube">🔗</a>
          <button class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px" title="Chỉnh sửa"
            onclick="ytMgrOpenEdit('${safeId}')">✏️</button>
          <button class="btn btn-sm btn-danger" style="padding:4px 8px;font-size:11px" title="Xóa"
            onclick="ytMgrDeleteVideo('${safeId}', '${safeTitle}')">🗑</button>
        </div>
      </div>
    </div>
  </div>`;
}

// Store current videos for edit lookup
window._ytMgrVideos = {};

async function ytMgrLoadVideos(pageToken) {
  // Override defined above — this version also caches video data
  const grid = document.getElementById('yt-mgr-video-grid');
  if (!grid) return;
  grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)"><div class="spinner mb-12" style="margin:0 auto"></div>Đang tải video...</div>';

  const privacy = document.getElementById('yt-mgr-filter-privacy')?.value || '';
  let url = '/api/youtube_videos?max_results=12';
  if (pageToken) url += '&page_token=' + encodeURIComponent(pageToken);

  try {
    const res  = await fetch(url);
    const data = await res.json();
    if (!data.ok) { grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">❌ ${data.error}</div>`; return; }

    let videos = data.videos || [];
    // Cache for edit
    videos.forEach(v => { window._ytMgrVideos[v.id] = v; });

    if (privacy) videos = videos.filter(v => v.privacy === privacy);

    _ytMgrNextToken = data.next_page_token || null;

    const btnNext = document.getElementById('btn-yt-mgr-next');
    const btnPrev = document.getElementById('btn-yt-mgr-prev');
    const info    = document.getElementById('yt-mgr-page-info');
    if (btnNext) btnNext.style.display = _ytMgrNextToken ? 'inline-flex' : 'none';
    if (btnPrev) btnPrev.style.display = _ytMgrTokenStack.length > 0 ? 'inline-flex' : 'none';
    if (info) info.textContent = `${videos.length} video`;

    if (!videos.length) {
      grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)">📭 Không có video nào</div>';
      return;
    }
    grid.innerHTML = videos.map(v => _ytMgrVideoCard(v)).join('');
  } catch (e) {
    grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">❌ Lỗi: ${e.message}</div>`;
  }
}

function ytMgrOpenEdit(videoId) {
  const v = window._ytMgrVideos[videoId];
  if (!v) { toast('Không tìm thấy thông tin video', 'error'); return; }

  document.getElementById('yt-edit-id').value      = v.id;
  document.getElementById('yt-edit-title').value   = v.title || '';
  document.getElementById('yt-edit-desc').value    = v.description || '';
  document.getElementById('yt-edit-tags').value    = (v.tags || []).join(', ');
  document.getElementById('yt-edit-privacy').value = v.privacy || 'private';
  const licEl = document.getElementById('yt-edit-license');
  if (licEl) licEl.value = v.license || 'youtube';
  const kidsEl = document.getElementById('yt-edit-kids');
  if (kidsEl) kidsEl.checked = !!v.made_for_kids;

  const modal = document.getElementById('yt-mgr-edit-modal');
  if (modal) modal.style.display = 'flex';
}

function ytMgrCloseEdit() {
  const modal = document.getElementById('yt-mgr-edit-modal');
  if (modal) modal.style.display = 'none';
}

async function ytMgrSaveEdit() {
  const videoId = document.getElementById('yt-edit-id')?.value;
  if (!videoId) return;

  const title   = document.getElementById('yt-edit-title')?.value?.trim() || '';
  const desc    = document.getElementById('yt-edit-desc')?.value?.trim()  || '';
  const tagsStr = document.getElementById('yt-edit-tags')?.value?.trim()  || '';
  const privacy = document.getElementById('yt-edit-privacy')?.value || 'private';
  const license = document.getElementById('yt-edit-license')?.value || 'youtube';
  const kids    = document.getElementById('yt-edit-kids')?.checked || false;
  const tags    = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

  const btn = document.querySelector('#yt-mgr-edit-modal .btn-primary');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang lưu...'; }

  try {
    const res  = await fetch('/api/youtube_video_update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId, title, description: desc, tags, privacy, license, made_for_kids: kids })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Đã cập nhật video thành công', 'success');
      ytMgrCloseEdit();
      ytMgrLoadVideos();
    } else {
      toast('❌ ' + (data.error || 'Cập nhật thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '💾 Lưu thay đổi'; }
  }
}

async function ytMgrDeleteVideo(videoId, title) {
  if (!confirm(`Xóa video "${title}"?\n\nHành động này không thể hoàn tác!`)) return;
  try {
    const res  = await fetch('/api/youtube_video_delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Đã xóa video', 'success');
      ytMgrLoadVideos();
    } else {
      toast('❌ ' + (data.error || 'Xóa thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}

async function ytMgrLogin() {
  if (typeof youtubeLogin === 'function') {
    // Trigger login then re-init this tab
    const origUpdate = window._updateYtAuthUI;
    window._updateYtAuthUI = (ch) => {
      if (origUpdate) origUpdate(ch);
      if (ch) { _ytMgrShowConnected(ch); }
    };
    youtubeLogin();
  }
}

async function ytMgrLogout() {
  try {
    await fetch('/api/youtube_logout', { method: 'POST' });
    _ytMgrShowDisconnected();
    if (typeof _setYouTubeAuthenticated === 'function') _setYouTubeAuthenticated(false, null);
    toast('Đã đăng xuất YouTube', 'info');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

// Close edit modal on backdrop click
document.addEventListener('click', e => {
  const modal = document.getElementById('yt-mgr-edit-modal');
  if (modal && e.target === modal) ytMgrCloseEdit();
});

/* ════════════════════════════════════════════════════════════
   INIT — load files tab by default when page opens
════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  // Will be triggered by switchPage('content') → cptSwitch('files')
});

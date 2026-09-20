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

function _contentFileSvg(ext) {
  if (['mp4','mkv','avi','mov'].includes(ext)) {
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>';
  }
  if (['ass','srt'].includes(ext)) {
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v12H7l-3 3Z"/><path d="M8 10h3m2 0h3M8 14h8"/></svg>';
  }
  if (['jpg','jpeg','png','webp'].includes(ext)) {
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
  }
  return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
}

function renderContentList() {
  const container = document.getElementById('content-list-container');
  if (!container) return;
  const search   = document.getElementById('content-search')?.value.toLowerCase() || '';
  const filtered = _contentFiles.filter(f => f.name.toLowerCase().includes(search));

  const summaryEl = document.getElementById('content-file-summary');
  if (summaryEl) summaryEl.textContent = `${filtered.length} tệp`;

  if (!filtered.length) {
    container.innerHTML = `
      <div style="padding:60px 20px;text-align:center;color:var(--text-muted)">
        <div style="width:48px;height:48px;margin:0 auto 12px;border-radius:12px;background:var(--bg3);display:flex;align-items:center;justify-content:center;color:var(--text-muted)">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:4px">Không tìm thấy tệp nào</div>
        <div style="font-size:11.5px">Các tệp video tải về hoặc đã xử lý sẽ hiển thị tại danh sách này.</div>
      </div>`;
    return;
  }

  const isMobile = window.innerWidth < 640;

  if (isMobile) {
    // ── Mobile: card list ──
    let html = '<div style="display:flex;flex-direction:column;gap:8px;padding:10px">';
    filtered.forEach(f => {
      const size = f.size >= 1048576 ? (f.size / 1048576).toFixed(2) + ' MB' : (f.size / 1024).toFixed(1) + ' KB';
      const date = new Date(f.mtime * 1000).toLocaleString('vi-VN', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
      const ext  = f.ext.replace('.', '').toLowerCase();
      const safeName = f.name.replace(/'/g, "\\'");
      const isVideo = ['mp4','mkv','avi','mov'].includes(ext);

      html += `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px;display:flex;gap:10px;align-items:flex-start">
        <div style="width:36px;height:36px;border-radius:8px;background:rgba(59,130,246,0.08);color:var(--accent);display:flex;align-items:center;justify-content:center;flex-shrink:0">${_contentFileSvg(ext)}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:12px;font-weight:600;color:var(--text);word-break:break-word;line-height:1.4;margin-bottom:4px">${f.name}</div>
          <div style="font-size:11px;color:var(--text-muted)">${size} · ${date}</div>
          <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
            <a href="/api/files/download?path=${encodeURIComponent(f.name)}" download="${f.name}"
               class="btn btn-sm btn-primary" style="padding:4px 8px;font-size:11px;text-decoration:none;display:inline-flex;align-items:center;gap:4px">
               <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
               <span>Tải về</span>
            </a>
            ${isVideo ? `
            <button class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px;display:inline-flex;align-items:center;gap:4px" onclick="sendToPublishFromContent('${safeName}')">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
              <span>Đăng</span>
            </button>
            <button class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px;display:inline-flex;align-items:center;gap:4px" onclick="sendToProcessFromContent('${safeName}')">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span>Xử lý</span>
            </button>` : ''}
            <button class="btn btn-sm" style="padding:4px 8px;font-size:11px;background:var(--error-bg);color:var(--error);border:1px solid rgba(192,57,43,.3);display:inline-flex;align-items:center" onclick="deleteContentFile('${safeName}')">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
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
    <th>Tên tệp</th>
    <th style="width:110px">Kích thước</th>
    <th style="width:150px">Ngày tạo</th>
    <th style="text-align:right;width:180px">Thao tác</th>
  </tr></thead><tbody>`;

  filtered.forEach(f => {
    const date = new Date(f.mtime * 1000).toLocaleString('vi-VN', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
    const size = f.size >= 1048576 ? (f.size / 1048576).toFixed(2) + ' MB' : (f.size / 1024).toFixed(1) + ' KB';
    const ext  = f.ext.replace('.', '').toLowerCase();
    const isVideo = ['mp4','mkv','avi','mov'].includes(ext);
    const safeName = f.name.replace(/'/g, "\\'");
    html += `<tr>
      <td><div class="file-name-cell">
        <div class="file-icon ext-${ext}">${_contentFileSvg(ext)}</div>
        <div style="min-width:0"><div class="file-name" title="${f.name}">${f.name}</div><div class="file-meta">${f.path || f.name}</div></div>
      </div></td>
      <td style="white-space:nowrap;font-size:11.5px;color:var(--text)">${size}</td>
      <td style="white-space:nowrap;font-size:11.5px;color:var(--text-muted)">${date}</td>
      <td><div class="content-actions">
        <a href="/api/files/download?path=${encodeURIComponent(f.name)}" download="${f.name}"
           class="btn-action" title="Tải về" style="text-decoration:none">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </a>
        ${isVideo ? `
        <button class="btn-action" onclick="sendToProcessFromContent('${safeName}')" title="Gửi sang Xử lý">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </button>
        <button class="btn-action" onclick="sendToPublishFromContent('${safeName}')" title="Gửi sang Đăng bài">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
        </button>
        <button class="btn-action" onclick="fbMgrPrefillVideo('${safeName}')" title="Đăng lên Facebook Page">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>
        </button>` : ''}
        <button class="btn-action" onclick="renameContentFile('${safeName}')" title="Đổi tên">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        </button>
        <button class="btn-action btn-delete" onclick="deleteContentFile('${safeName}')" title="Xóa">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
        </button>
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
  if (badge) badge.innerHTML = '<span class="badge badge-green">Đã kết nối</span>';

  window._fbMgrPages = pages || [];
  _fbMgrRenderPages(pages);

  // Auto select first page if none selected yet
  if (pages && pages.length > 0) {
    const targetPageId = window._fbMgrSelectedPage?.id && pages.some(p => p.id === window._fbMgrSelectedPage.id)
      ? window._fbMgrSelectedPage.id
      : pages[0].id;
    fbMgrSelectPage(targetPageId);
  }
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
      <div class="fb-page-avatar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div>
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
  const noMsg = document.getElementById('fb-mgr-no-page-msg');
  if (noMsg) noMsg.style.display = 'none';
  const postForm = document.getElementById('fb-mgr-post-form');
  if (postForm) postForm.style.display = 'block';
  const recentCard = document.getElementById('fb-mgr-recent-card');
  if (recentCard) recentCard.style.display = 'block';

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
      toast(`Kết nối thành công! Tìm thấy ${data.pages.length} Page`, 'success');
      _fbMgrShowConnected(data.user, data.pages);
    } else {
      toast((data.error || 'Kết nối thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi kết nối: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Kết nối & Lấy danh sách Pages'; }
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
  if (file) toast('Đã chọn: ' + file.name, 'success');
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
  toast('Đã nhập nội dung từ ' + file.name, 'success');
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
      body: JSON.stringify({ content, provider, target_language: document.getElementById('pub-target-lang')?.value || document.getElementById('batch-pub-target-lang')?.value || document.getElementById('proc-target-lang')?.value || 'vi' })
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

    if (status) status.textContent = 'Đã tạo nội dung thành công';
    toast('AI tạo nội dung thành công!', 'success');
  } catch (e) {
    if (status) status.textContent = e.message;
    toast('Lỗi AI: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Tạo nội dung bằng AI'; }
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
  const postTypeRaw = document.getElementById('fb-post-post-type')?.value || 'auto';
  const schedVal = document.getElementById('fb-post-schedule')?.value;
  let scheduledTime = '';
  if (schedVal) {
    const dt = new Date(schedVal);
    const minFuture = new Date(Date.now() + 10 * 60 * 1000); // FB requires 10 min ahead
    if (dt > minFuture) scheduledTime = Math.floor(dt.getTime() / 1000).toString();
    else { toast('Thời gian đặt lịch phải ít nhất 10 phút trong tương lai', 'warning'); return; }
  }

  const btn = document.getElementById('btn-fb-post-video');
  const setBusy = (busy) => {
    if (btn) { btn.disabled = busy; btn.textContent = busy ? 'Đang đăng...' : 'Đăng Video lên Facebook'; }
  };
  const logBox = document.getElementById('fb-post-log');
  if (logBox) { logBox.style.display = 'block'; logBox.innerHTML = ''; }

  setBusy(true);

  // ── Auto-detect Reel vs Video ──
  let postType = postTypeRaw;
  if (postType === 'auto') {
    if (videoFile) {
      _fbLog('ℹ Dùng file upload trực tiếp — mặc định video thường (không auto-detect 9:16).', 'info');
      postType = 'video';
    } else if (videoPath) {
      try {
        const r = await fetch('/api/facebook/validate_reel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ video_path: videoPath })
        });
        const d = await r.json();
        if (d.is_vertical_9_16 && d.ok) {
          postType = 'reel';
          _fbLog(`Video ${d.width}x${d.height} → đăng dạng Reel`, 'info');
        } else {
          postType = 'video';
          if (d.error) _fbLog(`ℹ ${d.error} → đăng video thường`, 'info');
        }
      } catch (_) {
        postType = 'video';
      }
    } else {
      postType = 'video';
    }
  }

  const endpoint = postType === 'reel'
    ? '/api/facebook/post_reel'
    : '/api/facebook/post_video';

  const buildForm = () => {
    const form = new FormData();
    form.append('page_id', page.id);
    form.append('description', desc);
    if (scheduledTime) form.append('scheduled_time', scheduledTime);
    if (postType !== 'reel') {
      form.append('title', title);
      if (videoFile) form.append('video_file', videoFile);
      else           form.append('video_path', videoPath);
    } else {
      if (!videoPath) {
        throw new Error('Reel cần file trên đĩa — hãy xử lý video trước rồi điền đường dẫn.');
      }
      form.append('video_path', videoPath);
    }
    return form;
  };

  _fbLog(`Đang đăng lên Facebook (${postType === 'reel' ? 'Reel' : 'Video'})...`, 'info');

  try {
    let form;
    try { form = buildForm(); }
    catch (e) { toast(e.message, 'error'); return; }

    for (let attempt = 1; attempt <= 5; attempt++) {
      const result = await _fbMgrUploadOnce(endpoint, form);
      if (result.success) { toast('Đăng Facebook thành công!', 'success', 6000); return; }
      if (result.tokenError) {
        if (typeof _pFbShowTokenModal === 'function') {
          const action = await _pFbShowTokenModal(result.errorMsg || '');
          if (action === 'retry')  { form = buildForm(); attempt--; continue; }
          if (action === 'skip')   { _fbLog('⏭ Bỏ qua video này', 'warning'); return; }
          return; // cancel
        } else {
          _fbLog('Token hết hạn — kết nối lại Facebook', 'error');
          toast('Token Facebook hết hạn — vui lòng kết nối lại', 'warning', 6000);
          return;
        }
      }
      if (result.errorMsg) toast('Lỗi: ' + result.errorMsg, 'error');
      return;
    }
    _fbLog('Đã thử lại 5 lần nhưng không thành công', 'error');
  } finally {
    setBusy(false);
  }
}

async function _fbMgrUploadOnce(endpoint, form) {
  const out = { success: false, tokenError: false, errorMsg: '' };
  try {
    const res = await fetch(endpoint, { method: 'POST', body: form });
    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      let tokenError = false;
      try {
        const errData = await res.json();
        errMsg = errData.error || errMsg;
        tokenError = !!errData.token_error;
      } catch (_) {}
      if (res.status === 401) tokenError = true;
      _fbLog(errMsg, 'error');
      out.errorMsg = errMsg; out.tokenError = tokenError;
      return out;
    }
    if (!res.body) { out.errorMsg = 'Server không trả về stream'; return out; }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let gotOk = false;
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
          if (d.url) _fbLog(d.url, 'success');
          if (d.ok)  gotOk = true;
          if (d.token_error) { out.tokenError = true; out.errorMsg = d.error || d.log || 'Token hết hạn'; }
          else if (d.error)  { out.errorMsg = d.error; }
        } catch (_) { _fbLog(t, 'info'); }
      }
    }
    out.success = gotOk;
    return out;
  } catch (e) {
    _fbLog(e.message, 'error');
    out.errorMsg = e.message;
    return out;
  }
}

async function fbMgrPostText() {
  const page = window._fbMgrSelectedPage;
  if (!page) { toast('Vui lòng chọn Page trước', 'warning'); return; }

  const message = document.getElementById('fb-post-text-msg')?.value?.trim();
  const link    = document.getElementById('fb-post-text-link')?.value?.trim() || '';
  if (!message) { toast('Vui lòng nhập nội dung bài viết', 'warning'); return; }

  const btn = document.getElementById('btn-fb-post-text');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }

  try {
    const res  = await fetch('/api/facebook/post_text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: page.id, message, link })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã đăng bài viết thành công!', 'success');
      document.getElementById('fb-post-text-msg').value = '';
      document.getElementById('fb-post-text-link').value = '';
      fbMgrLoadPosts();
    } else {
      toast((data.error || 'Đăng thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Đăng bài viết'; }
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
      const errMsg = data.error || 'Lỗi không xác định';
      // Detect token expiry (code 190 / subcode 463)
      const isTokenErr = /190|463|expired|OAuthException/i.test(errMsg);
      if (isTokenErr) {
        list.innerHTML = `<div style="padding:12px;font-size:12px;text-align:center">
          <div style="color:var(--warning,#f39c12);margin-bottom:8px"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>
          <div style="font-weight:600;margin-bottom:4px">Token Facebook đã hết hạn</div>
          <div style="color:var(--text-muted);font-size:11px;margin-bottom:12px">Cần gia hạn hoặc kết nối lại để xem bài đăng</div>
          <button class="btn btn-primary btn-sm" onclick="fbMgrRefreshToken()" style="font-size:11px">Gia hạn token</button>
        </div>`;
      } else {
        list.innerHTML = `<div style="padding:12px;font-size:11px;color:var(--error,#e74c3c);word-break:break-word">
          ${errMsg}
          ${data.debug_errors ? '<br><br><b>Chi tiết:</b><br>' + data.debug_errors.map(e => `• ${JSON.stringify(e)}`).join('<br>') : ''}
        </div>`;
      }
      return;
    }

    const posts = data.posts || [];
    if (!posts.length) { list.innerHTML = '<div class="text-muted text-sm" style="text-align:center;padding:16px">Chưa có bài đăng nào</div>'; return; }

    list.innerHTML = posts.map(p => {
      const msg  = (p.message || p.story || '(Không có nội dung)').slice(0, 120);
      const date = new Date(p.created_time).toLocaleString('vi-VN');
      // likes/comments returned as {data:[...]} array or summary object
      const likes = p.likes?.summary?.total_count ?? p.likes?.data?.length ?? (p.likes ? '0' : '--');
      const cmts  = p.comments?.summary?.total_count ?? p.comments?.data?.length ?? (p.comments ? '0' : '--');
      const url   = p.permalink_url || '#';
      return `<div class="fb-post-item">
        <div class="fb-post-msg">${msg}${(p.message||'').length > 120 ? '...' : ''}</div>
        <div class="fb-post-meta">
          <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>${date}</span>
          <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>${likes}</span>
          <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>${cmts}</span>
          ${url !== '#' ? `<a href="${url}" target="_blank" style="color:var(--accent)">Xem</a>` : ''}
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    list.innerHTML = `<div class="text-muted text-sm" style="padding:12px">Lỗi: ${e.message}</div>`;
  }
}

async function fbMgrRefreshToken() {
  const list = document.getElementById('fb-mgr-posts-list');
  if (list) list.innerHTML = '<div class="text-muted text-sm" style="text-align:center;padding:16px">⏳ Đang gia hạn token...</div>';
  try {
    const res  = await fetch('/api/facebook/refresh_token', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      toast(data.message || 'Token đã được gia hạn thành công!', 'success', 5000);
      fbMgrLoadPosts();
    } else if (data.need_reauth) {
      if (list) list.innerHTML = `<div style="padding:12px;font-size:12px;text-align:center">
        <div style="color:var(--error,#ef4444);margin-bottom:8px"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></div>
        <div style="font-weight:600;margin-bottom:4px">Token hết hạn hoàn toàn</div>
        <div style="color:var(--text-muted);font-size:11px;margin-bottom:12px">Cần nhập token mới từ Graph API Explorer</div>
        <a href="https://developers.facebook.com/tools/explorer/" target="_blank" class="btn btn-primary btn-sm" style="font-size:11px">Mở Graph API Explorer</a>
      </div>`;
    } else {
      toast((data.error || 'Gia hạn thất bại'), 'error', 6000);
      if (list) list.innerHTML = `<div style="padding:12px;font-size:11px;color:var(--error,#e74c3c)">${data.error || 'Gia hạn thất bại'}</div>`;
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
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
    if (!data.ok) { grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">${data.error}</div>`; return; }

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
      grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)">Chưa có video nào trong danh sách</div>';
      return;
    }

    grid.innerHTML = videos.map(v => _ytMgrVideoCard(v)).join('');
  } catch (e) {
    grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">Lỗi: ${e.message}</div>`;
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
  const privacyLabel = { public:'Công khai', unlisted:'Không công khai', private:'Riêng tư' }[v.privacy] || v.privacy;
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
        <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>${_fmtNum(v.views)}</span>
        <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>${_fmtNum(v.likes)}</span>
        <span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>${_fmtNum(v.comments)}</span>
        ${date ? `<span><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline;vertical-align:middle;margin-right:2px"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>${date}</span>` : ''}
      </div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">
        ${licBadge}${hdBadge}${capBadge}${kidsBadge}
      </div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:6px">
        <span class="yt-privacy-badge ${privacyCls}">${privacyLabel}</span>
        <div class="yt-video-actions">
          <a href="${v.url}" target="_blank" class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px" title="Xem trên YouTube"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg></a>
          <button class="btn btn-sm btn-secondary" style="padding:4px 8px;font-size:11px" title="Chỉnh sửa"
            onclick="ytMgrOpenEdit('${safeId}')" title="Chỉnh sửa"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg></button>
          <button class="btn btn-sm btn-danger" style="padding:4px 8px;font-size:11px" title="Xóa"
            onclick="ytMgrDeleteVideo('${safeId}', '${safeTitle}')" title="Xóa"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
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
    if (!data.ok) { grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">${data.error}</div>`; return; }

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
      grid.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted)">Chưa có video nào trong danh sách</div>';
      return;
    }
    grid.innerHTML = videos.map(v => _ytMgrVideoCard(v)).join('');
  } catch (e) {
    grid.innerHTML = `<div style="padding:40px;text-align:center;color:var(--error)">Lỗi: ${e.message}</div>`;
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
      toast('Đã cập nhật video thành công', 'success');
      ytMgrCloseEdit();
      ytMgrLoadVideos();
    } else {
      toast((data.error || 'Cập nhật thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Lưu thay đổi'; }
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
      toast('Đã xóa video thành công', 'success');
      ytMgrLoadVideos();
    } else {
      toast((data.error || 'Xóa thất bại'), 'error');
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


/* ════════════════════════════════════════════════════════════
   TIKTOK MANAGER — no API access; just saves username + opens links
════════════════════════════════════════════════════════════ */
const _TT_MGR_KEY = 'tiktok.manager.username';

function ttMgrLoadUsername() {
  try {
    const v = localStorage.getItem(_TT_MGR_KEY) || '';
    const el = document.getElementById('tt-mgr-username');
    if (el) el.value = v;
  } catch (_) {}
}

function ttMgrSaveUsername() {
  const el = document.getElementById('tt-mgr-username');
  const username = (el?.value || '').trim().replace(/^@/, '');
  try {
    localStorage.setItem(_TT_MGR_KEY, username);
    if (username) toast(`Đã lưu username: @${username}`, 'success', 3000);
  } catch (_) {}
}

function ttMgrOpenProfile() {
  const el = document.getElementById('tt-mgr-username');
  const username = (el?.value || '').trim().replace(/^@/, '');
  if (!username) {
    toast('Vui lòng nhập username TikTok trước', 'warning');
    return;
  }
  window.open(`https://www.tiktok.com/@${encodeURIComponent(username)}`, '_blank');
}

// Auto-load saved username on page load
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(ttMgrLoadUsername, 300);
});

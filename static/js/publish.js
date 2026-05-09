/* ── publish.js — Đăng video lên YouTube / TikTok / Facebook ── */

window._pubVideoFile = null;
window._pubSubFile   = null;
window._pubEnabled   = { youtube: true, tiktok: true, facebook: true };
window._pubActive    = 'youtube';

/* ── Helpers ── */
const _pubTabId  = p => ({ youtube:'yt', tiktok:'tt', facebook:'fb' }[p]);
const _pubPlatforms = ['youtube','tiktok','facebook'];

/* ── File inputs ── */
function _pubSetVideoFile(input) {
  const file = input.files?.[0] || null;
  window._pubVideoFile = file;
  const el = document.getElementById('pub-video-path');
  if (el) el.value = file ? file.name : '';
  input.value = '';
  if (file) toast('✅ Đã chọn: ' + file.name, 'success');
}

function _pubSetSubFile(input) {
  const file = input.files?.[0] || null;
  window._pubSubFile = file;
  const el = document.getElementById('pub-sub-path');
  if (el) el.value = file ? file.name : '';
  input.value = '';
  if (file) toast('✅ Đã chọn phụ đề: ' + file.name, 'success');
}

/* ── Load subtitle content ── */
async function _pubLoadSubContent() {
  let file = window._pubSubFile;
  let text = '';
  let fileName = '';

  if (!file) {
    const path = document.getElementById('pub-sub-path')?.value?.trim();
    if (!path) { toast('Vui lòng chọn file .srt hoặc .ass trước', 'warning'); return; }
    
    // Fetch from server path
    try {
      const res = await fetch('/api/read_subtitle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Không thể đọc file');
      text = data.content;
      fileName = data.filename || path;
    } catch (e) {
      toast('Lỗi đọc file từ server: ' + e.message, 'error');
      return;
    }
  } else {
    text = await file.text();
    fileName = file.name;
  }

  try {
    let plain = '';
    if (fileName.toLowerCase().endsWith('.ass')) {
      const parts = [];
      for (const line of text.split(/\r?\n/)) {
        if (!line.startsWith('Dialogue:')) continue;
        const cols = line.split(',');
        if (cols.length < 10) continue;
        let t = cols.slice(9).join(',').replace(/\{[^}]*\}/g,'').replace(/\\N/g,' ').replace(/\\n/g,' ').trim();
        if (t) parts.push(t);
      }
      plain = parts.join(' ');
    } else {
      plain = text.replace(/^\d+\s*$/gm,'').replace(/\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}/g,'').replace(/<[^>]+>/g,'').trim();
    }
    const ta = document.getElementById('pub-content-input');
    if (ta) ta.value = plain.slice(0, 3000);
    toast('✅ Đã nhập nội dung từ phụ đề', 'success');
  } catch (e) { toast('Lỗi xử lý phụ đề: ' + e.message, 'error'); }
}

/* ── Switch active tab (chỉ hiển thị 1 panel) ── */
function pubSwitchTab(platform) {
  if (!_pubPlatforms.includes(platform)) return;
  if (!window._pubEnabled[platform]) return;
  window._pubActive = platform;

  _pubPlatforms.forEach(p => {
    const tid = _pubTabId(p);
    const tab   = document.getElementById('pub-tab-' + tid);
    const panel = document.getElementById('pub-panel-' + p);

    // Tab button: active = đang xem
    if (tab) {
      tab.classList.toggle('active', p === platform);
    }
    // Panel: chỉ show panel đang active
    if (panel) {
      panel.style.display = (p === platform) ? 'block' : 'none';
    }
  });
}

/* ── Toggle bật/tắt nền tảng ── */
function pubTogglePlatform(platform) {
  if (!_pubPlatforms.includes(platform)) return;
  const tid    = _pubTabId(platform);
  const toggle = document.getElementById('pub-toggle-' + tid);
  const tab    = document.getElementById('pub-tab-' + tid);

  window._pubEnabled[platform] = !window._pubEnabled[platform];
  const on = window._pubEnabled[platform];

  // Cập nhật nút toggle
  if (toggle) {
    toggle.textContent = on ? '✓' : '✕';
    toggle.style.background = on ? 'var(--accent)' : 'var(--text-muted)';
  }
  // Tab mờ khi tắt
  if (tab) tab.style.opacity = on ? '1' : '0.4';

  if (on) {
    // Bật → chuyển sang nền tảng này
    pubSwitchTab(platform);
  } else {
    // Tắt → nếu đang xem nền tảng này thì chuyển sang nền tảng khác
    if (window._pubActive === platform) {
      const next = _pubPlatforms.find(p => window._pubEnabled[p] && p !== platform);
      if (next) pubSwitchTab(next);
      else {
        // Tất cả đều tắt - ẩn hết panels
        _pubPlatforms.forEach(p => {
          const panel = document.getElementById('pub-panel-' + p);
          if (panel) panel.style.display = 'none';
        });
      }
    }
  }
}

/* ── AI Analyze ── */
async function pubAnalyzeContent() {
  const content = document.getElementById('pub-content-input')?.value?.trim();
  if (!content) { toast('Vui lòng nhập nội dung video trước', 'warning'); return; }

  const btn    = document.getElementById('btn-pub-analyze');
  const status = document.getElementById('pub-analyze-status');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang phân tích...'; }
  if (status) status.textContent = 'Đang gọi AI...';

  const provider = document.getElementById('pub-ai-provider')?.value || 'deepseek';
  try {
    const res  = await fetch('/api/analyze_video_content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, provider })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI phân tích thất bại');
    const info = data.result || {};

    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    const arr  = v => Array.isArray(v) ? v.join(', ') : (v || '');

    fill('yt-title', info.youtube?.title);
    fill('yt-desc',  info.youtube?.description);
    fill('yt-tags',  arr(info.youtube?.tags));
    fill('tt-title', info.tiktok?.caption);
    fill('tt-desc',  info.tiktok?.description);
    fill('tt-tags',  Array.isArray(info.tiktok?.hashtags) ? info.tiktok.hashtags.join(' ') : info.tiktok?.hashtags);
    fill('fb-title', info.facebook?.title);
    fill('fb-desc',  info.facebook?.description);
    fill('fb-tags',  Array.isArray(info.facebook?.hashtags) ? info.facebook.hashtags.join(' ') : info.facebook?.hashtags);

    if (status) status.textContent = '✅ Đã điền thông tin';
    toast('✅ AI tạo nội dung thành công!', 'success');
  } catch (e) {
    if (status) status.textContent = '❌ ' + e.message;
    toast('Lỗi AI: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ Xử lý & tạo thông tin'; }
  }
}

/* ── Scheduling Helpers ── */
function toggleYtScheduleDisplay() {
  const privacy = document.getElementById('yt-privacy')?.value;
  const wrap = document.getElementById('yt-schedule-wrap');
  if (!wrap) return;
  // YouTube only allows scheduling for private videos (which it then makes public at the set time)
  if (privacy === 'private') {
    wrap.style.display = 'block';
  } else {
    // Luôn hiện checkbox để user có thể tích chọn nếu muốn
    wrap.style.display = 'block';
  }
}

function toggleYtScheduleFields() {
  const useSched = document.getElementById('yt-use-schedule')?.checked;
  const fields = document.getElementById('yt-schedule-fields');
  const privacySelect = document.getElementById('yt-privacy');

  if (fields) fields.style.display = useSched ? 'grid' : 'none';

  // Nếu chọn đặt lịch, bắt buộc chuyển sang Riêng tư
  if (useSched && privacySelect && privacySelect.value !== 'private') {
    privacySelect.value = 'private';
    toast('💡 Đã tự động chuyển sang Riêng tư để đặt lịch', 'info');
  }
}

/* ── YouTube Upload ── */
async function pubUploadYouTube() {
  const videoFile = window._pubVideoFile;
  const videoPath = document.getElementById('pub-video-path')?.value?.trim();
  if (!videoFile && !videoPath) { toast('Vui lòng chọn file video trước', 'warning'); return; }

  const title = document.getElementById('yt-title')?.value?.trim();
  if (!title) { toast('Vui lòng nhập tiêu đề YouTube', 'warning'); return; }

  const desc    = document.getElementById('yt-desc')?.value?.trim() || '';
  const tagsStr = document.getElementById('yt-tags')?.value?.trim() || '';
  const privacy = document.getElementById('yt-privacy')?.value || 'private';
  const isShort = document.getElementById('yt-is-short')?.checked || false;
  const tags    = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

  // Handle scheduling
  let publishAt = null;
  const useSched = document.getElementById('yt-use-schedule')?.checked;
  if (useSched && privacy === 'private') {
    const date = document.getElementById('yt-sched-date')?.value;
    const time = document.getElementById('yt-sched-time')?.value;
    if (!date || !time) {
      toast('Vui lòng chọn ngày và giờ đặt lịch', 'warning');
      return;
    }
    // Convert to ISO 8601 (UTC) — YouTube requires RFC 3339 with .000Z suffix
    const dt = new Date(`${date}T${time}`);
    const minFuture = new Date(Date.now() + 5 * 60 * 1000); // at least 5 min ahead
    if (dt <= minFuture) {
      toast('Thời gian đặt lịch phải ít nhất 5 phút trong tương lai', 'warning');
      return;
    }
    publishAt = dt.toISOString().replace(/\.\d{3}Z$/, '.000Z');
  }

  const btn    = document.getElementById('btn-yt-upload');
  const logBox = document.getElementById('yt-upload-log');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }
  if (logBox) { logBox.style.display = 'block'; logBox.innerHTML = ''; }

  const log = (msg, level) => {
    if (!logBox) return;
    const d = document.createElement('div');
    d.className = 'log-' + (level || 'info');
    d.textContent = '[' + new Date().toTimeString().slice(0,8) + '] ' + msg;
    logBox.appendChild(d);
    logBox.scrollTop = logBox.scrollHeight;
  };

  try {
    let res;
    const payload = {
      title,
      description: desc,
      tags,
      privacy_status: privacy,
      is_short: isShort,
      publish_at: publishAt
    };

    if (videoFile) {
      const form = new FormData();
      form.append('video_file', videoFile);
      for (const [k, v] of Object.entries(payload)) {
        form.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v || ''));
      }
      res = await fetch('/api/youtube_upload', { method: 'POST', body: form });
    } else {
      payload.video_path = videoPath;
      res = await fetch('/api/youtube_upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    }
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
          if (d.log) log(d.log, d.level || 'info');
          if (d.url) { log('🎉 ' + d.url, 'success'); toast('✅ Đăng YouTube thành công!', 'success', 6000); }
        } catch (_) { log(t, 'info'); }
      }
    }
  } catch (e) {
    log('❌ ' + e.message, 'error');
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Bắt đầu Đăng lên YouTube'; }
  }
}

/* ── TikTok / Facebook (manual) ── */
function pubOpenTikTok() {
  const caption = [document.getElementById('tt-title')?.value?.trim(), document.getElementById('tt-tags')?.value?.trim()].filter(Boolean).join('\n');
  if (caption) { try { navigator.clipboard.writeText(caption); toast('📋 Đã copy caption', 'info'); } catch(_){} }
  window.open('https://www.tiktok.com/upload', '_blank');
}

/* ── Facebook API integration (publish page) ── */
async function pubFbInit() {
  try {
    const res  = await fetch('/api/facebook/status');
    const data = await res.json();
    if (data.connected && data.user) {
      _pubFbShowConnected(data.user, data.pages || []);
    } else {
      _pubFbShowDisconnected();
    }
  } catch (_) { _pubFbShowDisconnected(); }
}

function _pubFbShowDisconnected() {
  const dc = document.getElementById('pub-fb-disconnected');
  const cn = document.getElementById('pub-fb-connected');
  if (dc) dc.style.display = 'block';
  if (cn) cn.style.display = 'none';
}

function _pubFbShowConnected(user, pages) {
  const dc = document.getElementById('pub-fb-disconnected');
  const cn = document.getElementById('pub-fb-connected');
  if (dc) dc.style.display = 'none';
  if (cn) cn.style.display = 'block';

  const nameEl = document.getElementById('pub-fb-user-name');
  if (nameEl) nameEl.textContent = user.name || '--';

  const sel = document.getElementById('pub-fb-page-select');
  if (sel) {
    sel.innerHTML = '<option value="">-- Chọn Page --</option>';
    (pages || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      sel.appendChild(opt);
    });
    // Auto-select first page
    if (pages && pages.length === 1) sel.value = pages[0].id;
  }
}

function pubFbToggleToken() {
  const input = document.getElementById('pub-fb-token-input');
  if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

/* ── Facebook AI helpers (publish page) ── */
function pubFbReadAssFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const text  = reader.result || '';
    const plain = _fbExtractPlainTextPub(text, file.name);
    const ta = document.getElementById('pub-fb-ai-input');
    if (ta) ta.value = plain.slice(0, 3000);
    toast('✅ Đã nhập từ ' + file.name, 'success');
  };
  reader.readAsText(file, 'utf-8');
  input.value = '';
}

function _fbExtractPlainTextPub(text, filename) {
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

async function pubFbGenerateAI() {
  const content  = document.getElementById('pub-fb-ai-input')?.value?.trim();
  if (!content) { toast('Vui lòng nhập nội dung trước', 'warning'); return; }

  const provider = document.getElementById('pub-fb-ai-provider')?.value || 'deepseek';
  const btn      = document.getElementById('btn-pub-fb-ai');
  const status   = document.getElementById('pub-fb-ai-status');
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

    const fb = (data.result || {}).facebook || {};
    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    fill('fb-title', fb.title);
    const hashtags = Array.isArray(fb.hashtags) ? fb.hashtags.join(' ') : (fb.hashtags || '');
    fill('fb-desc', [fb.description, hashtags].filter(Boolean).join('\n\n'));

    if (status) status.textContent = '✅ Đã tạo nội dung';
    toast('✅ AI tạo nội dung Facebook thành công!', 'success');
  } catch (e) {
    if (status) status.textContent = '❌ ' + e.message;
    toast('Lỗi AI: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '✨ Tạo nội dung bằng AI'; }
  }
}

function pubFbToggleSchedule() {
  const checked = document.getElementById('pub-fb-use-schedule')?.checked;
  const fields  = document.getElementById('pub-fb-schedule-fields');
  if (fields) fields.style.display = checked ? 'block' : 'none';
}

function pubFbOnPageChange() { /* placeholder for future per-page logic */ }

async function pubFbConnect() {
  const token = document.getElementById('pub-fb-token-input')?.value?.trim();
  if (!token) { toast('Vui lòng nhập Access Token', 'warning'); return; }

  const btn = document.getElementById('btn-pub-fb-connect');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang kết nối...'; }

  try {
    const res  = await fetch('/api/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await res.json();
    if (data.ok) {
      toast(`✅ Kết nối thành công! ${data.pages.length} Page`, 'success');
      _pubFbShowConnected(data.user, data.pages);
    } else {
      toast('❌ ' + (data.error || 'Kết nối thất bại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔗 Kết nối Facebook'; }
  }
}

async function pubFbDisconnect() {
  try {
    await fetch('/api/facebook/disconnect', { method: 'POST' });
    _pubFbShowDisconnected();
    toast('Đã ngắt kết nối Facebook', 'info');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

function _pubFbLog(msg, level) {
  const box = document.getElementById('fb-upload-log');
  if (!box) return;
  box.style.display = 'block';
  const d = document.createElement('div');
  d.className = 'log-' + (level || 'info');
  d.textContent = '[' + new Date().toTimeString().slice(0,8) + '] ' + msg;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}

async function pubUploadFacebook() {
  const pageId = document.getElementById('pub-fb-page-select')?.value;
  if (!pageId) { toast('Vui lòng chọn Page', 'warning'); return; }

  const videoFile = window._pubVideoFile;
  const videoPath = document.getElementById('pub-video-path')?.value?.trim();
  if (!videoFile && !videoPath) { toast('Vui lòng chọn file video trước', 'warning'); return; }

  const title    = document.getElementById('fb-title')?.value?.trim() || '';
  const desc     = document.getElementById('fb-desc')?.value?.trim()  || '';
  const privacy  = document.getElementById('pub-fb-privacy')?.value || 'EVERYONE';
  const schedVal = document.getElementById('pub-fb-use-schedule')?.checked
                   ? document.getElementById('pub-fb-schedule-dt')?.value : '';
  let scheduledTime = '';
  if (schedVal) {
    const dt = new Date(schedVal);
    const minFuture = new Date(Date.now() + 10 * 60 * 1000);
    if (dt > minFuture) scheduledTime = Math.floor(dt.getTime() / 1000).toString();
    else { toast('Thời gian đặt lịch phải ít nhất 10 phút trong tương lai', 'warning'); return; }
  }

  const btn = document.getElementById('btn-pub-fb-upload');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang đăng...'; }
  const logBox = document.getElementById('fb-upload-log');
  if (logBox) { logBox.style.display = 'block'; logBox.innerHTML = ''; }

  try {
    const form = new FormData();
    form.append('page_id', pageId);
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
          if (d.log) _pubFbLog(d.log, d.level || 'info');
          if (d.url) { _pubFbLog('🔗 ' + d.url, 'success'); toast('✅ Đăng Facebook thành công!', 'success', 6000); }
        } catch (_) { _pubFbLog(t, 'info'); }
      }
    }
  } catch (e) {
    _pubFbLog('❌ ' + e.message, 'error');
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Đăng Video lên Facebook'; }
  }
}

/* ── YouTube Auth ── */
async function youtubeLogin() {
  try {
    const res  = await fetch('/api/youtube_auth', { method: 'POST' });
    const data = await res.json();
    if (data.authenticated) { _updateYtAuthUI(data.channel); return; }
    if (data.auth_url) {
      const popup = window.open(data.auth_url, 'yt_auth', 'width=600,height=700');
      const poll  = setInterval(async () => {
        try {
          // Stop if popup was closed by user
          if (popup && popup.closed) { clearInterval(poll); return; }
          const r2 = await fetch('/api/youtube_auth');
          const d2 = await r2.json();
          if (d2.authenticated) { clearInterval(poll); popup?.close(); _updateYtAuthUI(d2.channel); toast('✅ Đăng nhập YouTube thành công!', 'success'); }
        } catch(_) { clearInterval(poll); }
      }, 2000);
      setTimeout(() => clearInterval(poll), 120000);
    }
  } catch (e) { toast('Lỗi đăng nhập: ' + e.message, 'error'); }
}

async function youtubeLogout() {
  try {
    await fetch('/api/youtube_logout', { method: 'POST' });
    _updateYtAuthUI(null);
    toast('Đã đăng xuất YouTube', 'info');
  } catch (e) { toast('Lỗi: ' + e.message, 'error'); }
}

function _updateYtAuthUI(channel) {
  // Delegate to app.js _setYouTubeAuthenticated if available (uses correct HTML IDs)
  if (typeof _setYouTubeAuthenticated === 'function') {
    _setYouTubeAuthenticated(!!channel, channel || null);
    return;
  }
  // Fallback: handle both old and new HTML IDs
  const show = (id, v) => { const el = document.getElementById(id); if (el) el.style.display = v ? '' : 'none'; };
  const text = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  if (channel) {
    show('yt-auth-connected', true);  show('yt-auth-disconnected', false);
    show('yt-channel-info', true);    show('yt-auth-needed', false);
    show('btn-yt-auth', false);       show('btn-yt-logout', true);
    text('yt-ch-name', channel.title || '--');
    text('yt-ch-subs', channel.subscribers || '--');
    text('yt-ch-videos', channel.video_count || '--');
    const img = document.getElementById('yt-ch-avatar-img');
    const ph  = document.getElementById('yt-ch-avatar-ph');
    if (img && channel.thumbnail) {
      img.src = channel.thumbnail; img.style.display = 'block';
      if (ph) ph.style.display = 'none';
    }
  } else {
    show('yt-auth-connected', false); show('yt-auth-disconnected', true);
    show('yt-channel-info', false);   show('yt-auth-needed', true);
    show('btn-yt-auth', true);        show('btn-yt-logout', false);
  }
}

/* ── Init ── */
document.addEventListener('DOMContentLoaded', async () => {
  // Check YouTube auth
  try { const r = await fetch('/api/youtube_auth'); const d = await r.json(); if (d.authenticated) _updateYtAuthUI(d.channel); } catch(_) {}
  // Check Facebook auth
  pubFbInit();
  // Init tabs - show only YouTube panel by default
  pubSwitchTab('youtube');
});

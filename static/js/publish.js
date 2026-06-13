/* ── publish.js — Đăng video lên YouTube / TikTok / Facebook ── */

window._pubVideoFile = null;
window._pubSubFile   = null;
window._pubUploadedVideoPath = '';
window._pubUploadPromise = null;
window._pubEnabled   = { youtube: true, tiktok: true, facebook: true };
window._pubActive    = 'youtube';

/* ── Helpers ── */
const _pubTabId  = p => ({ youtube:'yt', tiktok:'tt', facebook:'fb' }[p]);
const _pubPlatforms = ['youtube','tiktok','facebook'];

async function _pubUploadVideoFileToServer(file, opts = {}) {
  if (!file) return '';
  if (window._pubUploadPromise) return window._pubUploadPromise;

  const pathInput = opts.pathInput || document.getElementById('pub-video-path');
  const label = opts.label || null;
  const setLabel = (txt) => {
    if (label) label.textContent = txt;
    else if (pathInput) pathInput.placeholder = txt;
  };

  window._pubUploadPromise = (async () => {
    setLabel(`Đang import ${file.name}...`);
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/upload_process_video', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok || !data.path) {
      throw new Error(data.error || `Import video thất bại (HTTP ${res.status})`);
    }
    window._pubUploadedVideoPath = data.path;
    window._publishLastOutputPath = data.path;
    window._ytLastOutputPath = data.path;
    window._pubVideoFile = null;
    if (pathInput) pathInput.value = data.path;
    setLabel(`${file.name} ✓ → ${data.dir || data.path}`);
    return data.path;
  })();

  try {
    return await window._pubUploadPromise;
  } finally {
    window._pubUploadPromise = null;
  }
}

async function _pubEnsureVideoServerPath(opts = {}) {
  const pathInput = document.getElementById('pub-video-path');
  const currentPath = pathInput?.value?.trim() || '';
  if (window._pubUploadedVideoPath) return window._pubUploadedVideoPath;
  if (window._pubVideoFile) {
    try {
      return await _pubUploadVideoFileToServer(window._pubVideoFile, opts);
    } catch (e) {
      if (opts.requireDisk) {
        toast('Không import được video: ' + (e.message || e), 'error');
        return '';
      }
      console.warn('Publish video import failed:', e);
      return '';
    }
  }
  return currentPath;
}

window._pubUploadVideoFileToServer = _pubUploadVideoFileToServer;
window._pubEnsureVideoServerPath = _pubEnsureVideoServerPath;

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('pub-video-path')?.addEventListener('input', function() {
    const typed = this.value.trim();
    if (typed && typed !== window._pubUploadedVideoPath) {
      window._pubVideoFile = null;
      window._pubUploadedVideoPath = '';
    }
  });
});

/* ── File inputs ── */
async function _pubSetVideoFile(input) {
  const file = input.files?.[0] || null;
  window._pubVideoFile = file;
  window._pubUploadedVideoPath = '';
  const el = document.getElementById('pub-video-path');
  if (el) el.value = file ? file.name : '';
  input.value = '';
  if (!file) return;
  toast('✅ Đã chọn: ' + file.name, 'success');
  try {
    await _pubUploadVideoFileToServer(file);
    toast('✅ Đã import video, đường dẫn đăng đã cập nhật', 'success');
  } catch (e) {
    toast('Import video thất bại: ' + (e.message || e), 'error');
  }
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

/* ── Switch active tab (left-nav layout → toggle active class) ── */
function pubSwitchTab(platform) {
  if (!_pubPlatforms.includes(platform)) return;
  if (!window._pubEnabled[platform]) return;
  window._pubActive = platform;

  _pubPlatforms.forEach(p => {
    const tid = _pubTabId(p);
    const tab   = document.getElementById('pub-tab-' + tid);
    const panel = document.getElementById('pub-panel-' + p);

    // Tab button: active class toggle
    if (tab) {
      tab.classList.toggle('active', p === platform);
    }
    // Panel: use CSS class to show/hide (publish-pane.active)
    if (panel) {
      panel.classList.toggle('active', p === platform);
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
          if (panel) panel.classList.remove('active');
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
  const targetLang = document.getElementById('pub-target-lang')?.value
    || document.getElementById('proc-target-lang')?.value
    || 'vi';
  try {
    const res  = await fetch('/api/analyze_video_content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, provider, target_language: targetLang })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI phân tích thất bại');
    const info = data.result || {};

    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    const arr  = v => Array.isArray(v) ? v.join(', ') : (v || '');
    const stripTags = window._pStripInlineHashtags || (s => String(s || ''));
    const dedupTags = window._pDedupHashtagString  || (s => String(s || ''));

    fill('yt-title', stripTags(info.youtube?.title));
    fill('yt-desc',  stripTags(info.youtube?.description));
    fill('yt-tags',  arr(info.youtube?.tags));
    fill('tt-title', stripTags(info.tiktok?.caption));
    fill('tt-tags',  dedupTags(Array.isArray(info.tiktok?.hashtags) ? info.tiktok.hashtags.join(' ') : info.tiktok?.hashtags));
    fill('fb-title', stripTags(info.facebook?.title));
    fill('fb-tags',  dedupTags(Array.isArray(info.facebook?.hashtags) ? info.facebook.hashtags.join(' ') : info.facebook?.hashtags));

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
  const videoPath = await _pubEnsureVideoServerPath();
  const videoFile = window._pubVideoFile;
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

    if (videoPath) {
      payload.video_path = videoPath;
      res = await fetch('/api/youtube_upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    } else if (videoFile) {
      const form = new FormData();
      form.append('video_file', videoFile);
      for (const [k, v] of Object.entries(payload)) {
        form.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v || ''));
      }
      res = await fetch('/api/youtube_upload', { method: 'POST', body: form });
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

/* ── TikTok (semi-auto via Playwright) ── */
async function pubOpenTikTok() {
  try {
    const videoPath = await _pubEnsureVideoServerPath({ requireDisk: true });
    // Use shared helper to dedup hashtags + strip inline tags from caption text
    const ttTitle = document.getElementById('tt-title')?.value?.trim() || '';
    const ttTags  = document.getElementById('tt-tags')?.value?.trim()  || '';
    const caption = (window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n')))(ttTitle, ttTags);
    const privacy = document.getElementById('tt-privacy')?.value || 'PUBLIC_TO_EVERYONE';

    // Parse scheduled time if user enabled it
    let scheduledTime = '';
    if (document.getElementById('pub-tt-use-schedule')?.checked) {
      const raw = document.getElementById('pub-tt-schedule-dt')?.value;
      if (!raw) {
        toast('⚠ Vui lòng chọn ngày giờ đặt lịch', 'warning');
        return;
      }
      // datetime-local returns "YYYY-MM-DDTHH:MM" in local time. Parse as local.
      const dt = new Date(raw);
      const minFuture = new Date(Date.now() + 15 * 60 * 1000);
      if (dt > minFuture) {
        // Send as ISO (UTC). Backend converts back to local time for TikTok.
        scheduledTime = dt.toISOString();
      } else {
        toast('⚠ Lịch phải ít nhất 15 phút trong tương lai', 'warning');
        return;
      }
    }

    // Always copy caption to clipboard as safety net
    if (caption) {
      try { await navigator.clipboard.writeText(caption); } catch (_) {}
    }

    // If no video path on disk → can't use Playwright (needs a local file path).
    if (!videoPath) {
      toast('ℹ Chưa có đường dẫn file video — mở TikTok Studio để bạn kéo-thả thủ công. Caption đã copy.', 'info', 5000);
      window.open('https://www.tiktok.com/tiktokstudio/upload', '_blank');
      return;
    }

    // Use Playwright to open Chromium with persistent profile, attach file + fill caption.
    const btn = document.querySelector('[onclick*="pubOpenTikTok"]');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang mở Chromium...'; }

    const payload = { video_path: videoPath, caption, privacy };
    if (scheduledTime) payload.scheduled_time = scheduledTime;

    const r = await fetch('/api/tiktok/prepare_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }

    if (!d.ok) {
      toast('❌ TikTok: ' + (d.error || 'Lỗi không xác định'), 'error', 8000);
      return;
    }
    const schedMsg = scheduledTime ? ` (có đặt lịch)` : '';
    toast(`✅ Đã mở Chromium TikTok Studio${schedMsg}. File sẽ tự gắn — hãy chờ rồi nhấn Post.`, 'success', 8000);
  } catch (e) {
    console.error('pubOpenTikTok error:', e);
    toast('❌ TikTok lỗi: ' + (e.message || e), 'error', 8000);
    const btn = document.querySelector('[onclick*="pubOpenTikTok"]');
    if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
  }
}

function pubTtToggleSchedule() {
  const checked = document.getElementById('pub-tt-use-schedule')?.checked;
  const box = document.getElementById('pub-tt-schedule-fields');
  if (box) box.style.display = checked ? 'block' : 'none';

  // Auto-fill default: now + 30 min (avoids the "15 min future" error)
  if (checked) {
    const dtInput = document.getElementById('pub-tt-schedule-dt');
    if (dtInput && !dtInput.value) {
      const future = new Date(Date.now() + 30 * 60 * 1000);
      // toISOString returns UTC; we need local time for datetime-local input
      const off = future.getTimezoneOffset() * 60 * 1000;
      const local = new Date(future.getTime() - off);
      dtInput.value = local.toISOString().slice(0, 16);
    }
    // Also set min so user can't pick past times
    if (dtInput) {
      const now = new Date(Date.now() + 15 * 60 * 1000);
      const off = now.getTimezoneOffset() * 60 * 1000;
      dtInput.min = new Date(now.getTime() - off).toISOString().slice(0, 16);
    }
  }
}

/* ── Facebook API integration (publish page) ── */
async function pubFbInit() {
  try {
    const res  = await fetch('/api/facebook/status');
    const data = await res.json();
    if (data.connected && data.user) {
      _pubFbShowConnected(data.user, data.pages || []);
      _pubFbUpdateTokenStatus(data);
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

function _pubFbUpdateTokenStatus(data) {
  const el = document.getElementById('pub-fb-token-status');
  const btn = document.getElementById('btn-pub-fb-refresh');
  if (!el) return;

  const daysLeft = data.days_left;
  const isLongLived = data.is_long_lived;
  const isExpired = data.is_expired;
  const hasAppCreds = data.has_app_credentials;

  if (isExpired) {
    el.innerHTML = '❌ Token đã hết hạn — cần nhập token mới';
    el.style.color = 'var(--danger, #e74c3c)';
    if (btn) btn.style.display = 'none';
  } else if (daysLeft !== null && daysLeft !== undefined) {
    const color = daysLeft <= 7 ? 'var(--warning, #f39c12)' : 'var(--success, #27ae60)';
    const icon = daysLeft <= 7 ? '⚠️' : '✅';
    const typeLabel = isLongLived ? 'Long-lived' : 'Short-lived';
    el.innerHTML = `${icon} Token ${typeLabel} — còn <b>${daysLeft}</b> ngày`;
    el.style.color = color;
    if (btn) btn.style.display = hasAppCreds ? 'inline-block' : 'none';
  } else if (!isLongLived) {
    el.innerHTML = '⚠️ Short-lived token — hết hạn sớm';
    el.style.color = 'var(--warning, #f39c12)';
    if (btn) btn.style.display = hasAppCreds ? 'inline-block' : 'none';
  } else {
    el.innerHTML = '✅ Token hợp lệ';
    el.style.color = 'var(--success, #27ae60)';
    if (btn) btn.style.display = hasAppCreds ? 'inline-block' : 'none';
  }
}

async function pubFbRefreshToken() {
  const btn = document.getElementById('btn-pub-fb-refresh');
  const el  = document.getElementById('pub-fb-token-status');
  if (btn) { btn.disabled = true; btn.textContent = '⏳...'; }
  try {
    const res  = await fetch('/api/facebook/refresh_token', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      toast(data.message || '✅ Token đã được gia hạn!', 'success', 5000);
      // Refresh status display
      const status = await fetch('/api/facebook/status').then(r => r.json());
      if (status.connected) {
        _pubFbShowConnected(status.user, status.pages || []);
        _pubFbUpdateTokenStatus(status);
      }
    } else {
      const msg = data.error || 'Gia hạn thất bại';
      toast('❌ ' + msg, 'error', 8000);
      if (data.need_reauth) {
        // Token expired completely — show reconnect UI
        if (el) { el.innerHTML = '❌ Token hết hạn — cần nhập token mới'; el.style.color = 'var(--danger, #e74c3c)'; }
      }
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔄 Gia hạn'; }
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
      body: JSON.stringify({ content, provider, target_language: document.getElementById('pub-target-lang')?.value || document.getElementById('proc-target-lang')?.value || 'vi' })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI thất bại');

    const fb = (data.result || {}).facebook || {};
    const fill = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
    const stripTags = window._pStripInlineHashtags || (s => String(s || ''));
    const dedupTags = window._pDedupHashtagString  || (s => String(s || ''));
    fill('fb-title', stripTags(fb.title));
    const hashtags = Array.isArray(fb.hashtags) ? fb.hashtags.join(' ') : (fb.hashtags || '');
    fill('fb-tags', dedupTags(hashtags));

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
      const pageCount = data.pages.length;
      const longLived = data.is_long_lived ? ' (Long-lived token ✅)' : '';
      toast(`✅ Kết nối thành công! ${pageCount} Page${longLived}`, 'success', 5000);
      _pubFbShowConnected(data.user, data.pages);
      _pubFbUpdateTokenStatus(data);
      // Show warnings (e.g. missing perms, exchange info)
      if (data.warnings && data.warnings.length) {
        data.warnings.forEach(w => toast(w, w.startsWith('✅') ? 'success' : 'warning', 7000));
      }
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

  const videoPath = await _pubEnsureVideoServerPath();
  const videoFile = window._pubVideoFile;
  if (!videoFile && !videoPath) { toast('Vui lòng chọn file video trước', 'warning'); return; }

  // Quick preflight: warn early if token is missing required scopes. The actual
  // publish call will still be attempted so the user can see the real Graph
  // error, but this saves a minute of uploading the file if token is obviously
  // broken.
  try {
    const d = await fetch('/api/facebook/status').then(r => r.json());
    if (!d.connected) {
      toast('⚠ Facebook chưa kết nối — hãy bấm "Kết nối Facebook" trước', 'warning', 6000);
      return;
    }
  } catch (_) { /* ignore — let the real call surface the error */ }

  const title    = document.getElementById('fb-title')?.value?.trim() || '';
  const tags     = document.getElementById('fb-tags')?.value?.trim()  || '';
  // Dedup hashtags + strip inline hashtags from title to avoid double-printing.
  const desc     = (window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n')))(title, tags);
  const postTypeRaw = document.getElementById('pub-fb-post-type')?.value || 'auto';
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
  const setBusy = (busy) => {
    if (btn) { btn.disabled = busy; btn.textContent = busy ? '⏳ Đang đăng...' : '🚀 Đăng Video lên Facebook'; }
  };
  const logBox = document.getElementById('fb-upload-log');
  if (logBox) { logBox.style.display = 'block'; logBox.innerHTML = ''; }

  setBusy(true);

  // ── Auto-detect Reel vs Video (server-side validation of file on disk) ──
  let postType = postTypeRaw;
  if (postType === 'auto') {
    if (videoFile) {
      _pubFbLog('ℹ Dùng file upload trực tiếp — không auto-detect 9:16, mặc định dạng video thường.', 'info');
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
          _pubFbLog(`🎬 Video ${d.width}x${d.height} → đăng dạng Reel`, 'info');
        } else {
          postType = 'video';
          if (d.error) _pubFbLog(`ℹ ${d.error} → đăng video thường`, 'info');
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
    form.append('page_id', pageId);
    form.append('description', desc);
    if (scheduledTime) form.append('scheduled_time', scheduledTime);
    // Only the regular /videos endpoint accepts title and a file upload field
    if (postType !== 'reel') {
      form.append('title', title);
      if (videoPath) form.append('video_path', videoPath);
      else           form.append('video_file', videoFile);
    } else {
      // Reel 3-phase flow requires a path on disk (no direct file_upload supported by our impl)
      if (!videoPath) {
        throw new Error('Reel cần file trên đĩa — hãy xử lý video trước rồi điền đường dẫn.');
      }
      form.append('video_path', videoPath);
    }
    return form;
  };

  _pubFbLog(`🚀 Đang đăng lên Facebook (${postType === 'reel' ? 'Reel' : 'Video'})...`, 'info');

  // Retry up to 5 times; token errors trigger the modal and don't count against the limit
  try {
    let form;
    try { form = buildForm(); }
    catch (e) { toast(e.message, 'error'); return; }

    for (let attempt = 1; attempt <= 5; attempt++) {
      const result = await _pubFbUploadOnce(endpoint, form);

      if (result.success) {
        toast('✅ Đăng Facebook thành công!', 'success', 6000);
        return;
      }

      if (result.tokenError) {
        // Prefer the shared modal from proc_publish.js
        if (typeof _pFbShowTokenModal === 'function') {
          const action = await _pFbShowTokenModal(result.errorMsg || '');
          if (action === 'retry')  { form = buildForm(); attempt--; continue; }
          if (action === 'skip')   { _pubFbLog('⏭ Bỏ qua video này', 'warning'); return; }
          return; // cancel
        } else {
          _pubFbLog('❌ Token hết hạn — vui lòng kết nối lại Facebook', 'error');
          toast('⚠ Token Facebook hết hạn — kết nối lại', 'warning', 6000);
          return;
        }
      }

      // Non-token error — stop retrying
      if (result.errorMsg) toast('Lỗi: ' + result.errorMsg, 'error');
      return;
    }
    _pubFbLog('❌ Đã thử lại 5 lần nhưng không thành công', 'error');
  } finally {
    setBusy(false);
  }
}

/**
 * Single Facebook upload attempt.
 * Returns: { success, tokenError, errorMsg }
 */
async function _pubFbUploadOnce(endpoint, form) {
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
      _pubFbLog('❌ ' + errMsg, 'error');
      out.errorMsg = errMsg;
      out.tokenError = tokenError;
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
          if (d.log) _pubFbLog(d.log, d.level || 'info');
          if (d.url) _pubFbLog('🔗 ' + d.url, 'success');
          if (d.ok)  gotOk = true;
          if (d.token_error) {
            out.tokenError = true;
            out.errorMsg = d.error || d.log || 'Token hết hạn';
          } else if (d.error) {
            out.errorMsg = d.error;
          }
        } catch (_) { _pubFbLog(t, 'info'); }
      }
    }
    out.success = gotOk;
    return out;
  } catch (e) {
    _pubFbLog('❌ ' + e.message, 'error');
    out.errorMsg = e.message;
    return out;
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

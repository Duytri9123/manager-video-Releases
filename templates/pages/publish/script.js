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
  pubLoadRecentVideos();
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

/* ── Switch main tabs (Đa nền tảng / Hàng loạt) ── */
function pubSwitchMainTab(el, sectionId) {
  document.querySelectorAll('#page-publish .publish-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('#page-publish .publish-pane').forEach(p => p.classList.remove('active'));
  if (el) el.classList.add('active');
  const pane = document.getElementById(sectionId);
  if (pane) {
    pane.classList.add('active');
    const content = document.getElementById('content');
    if (content) content.scrollTop = 0;
  }
  if (sectionId === 'pub-sec-batch') {
    _batchPubUpdatePlatformStatus();
  }
}

/* ── Update batch platform status chips ── */
function _batchPubUpdatePlatformStatus() {
  const platforms = ['youtube', 'tiktok', 'facebook'];
  const ids = { youtube: 'yt', tiktok: 'tt', facebook: 'fb' };
  platforms.forEach(p => {
    const chip = document.getElementById('batch-plat-' + ids[p]);
    if (!chip) return;
    const enabled = window._pubEnabled[p];
    chip.classList.toggle('enabled', enabled);
    chip.classList.toggle('disabled', !enabled);
    const dot = chip.querySelector('.dot');
    if (dot) {
      dot.className = 'dot ' + (enabled ? 'dot-green' : 'dot-gray');
    }
  });
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

    if (tab) {
      tab.classList.toggle('active', p === platform);
    }
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

  if (toggle) {
    toggle.textContent = on ? '✓' : '✕';
    toggle.style.background = on ? 'var(--accent)' : 'var(--text-muted)';
  }
  if (tab) tab.style.opacity = on ? '1' : '0.4';

  if (on) {
    pubSwitchTab(platform);
  } else {
    if (window._pubActive === platform) {
      const next = _pubPlatforms.find(p => window._pubEnabled[p] && p !== platform);
      if (next) pubSwitchTab(next);
      else {
        _pubPlatforms.forEach(p => {
          const panel = document.getElementById('pub-panel-' + p);
          if (panel) panel.style.display = 'none';
        });
      }
    }
  }
  _batchPubUpdatePlatformStatus();
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
  wrap.style.display = 'block';
}

function toggleYtScheduleFields() {
  const useSched = document.getElementById('yt-use-schedule')?.checked;
  const fields = document.getElementById('yt-schedule-fields');
  const privacySelect = document.getElementById('yt-privacy');

  if (fields) fields.style.display = useSched ? 'grid' : 'none';

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

  let publishAt = null;
  const useSched = document.getElementById('yt-use-schedule')?.checked;
  if (useSched && privacy === 'private') {
    const date = document.getElementById('yt-sched-date')?.value;
    const time = document.getElementById('yt-sched-time')?.value;
    if (!date || !time) {
      toast('Vui lòng chọn ngày và giờ đặt lịch', 'warning');
      return;
    }
    const dt = new Date(`${date}T${time}`);
    const minFuture = new Date(Date.now() + 5 * 60 * 1000);
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
          if (d.url) {
            log('🎉 ' + d.url, 'success');
            toast('✅ Đăng YouTube thành công!', 'success', 6000);
            const vid = d.video_id || (d.url.match(/(?:youtu\.be\/|v=)([a-zA-Z0-9_-]{11})/) || [])[1];
            if (vid) {
              const ytLogBox = document.getElementById('yt-upload-log');
              if (ytLogBox) {
                const btnDiv = document.createElement('div');
                btnDiv.style.marginTop = '6px';
                btnDiv.innerHTML = `<button class="btn btn-xs btn-danger" onclick="pubDeleteYouTubeVideo('${vid}')">🗑 Thu hồi video YouTube</button>`;
                ytLogBox.appendChild(btnDiv);
              }
            }
          }
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
let _currentTtSessionId = null;
let _ttPollTimer = null;

async function pubOpenTikTok() {
  try {
    let videoPath = await _pubEnsureVideoServerPath({ requireDisk: true });

    // If videoPath is empty, try to get from recent completed videos automatically
    if (!videoPath) {
      try {
        const resp = await fetch('/api/files/completed');
        const data = await resp.json();
        const items = data.items || [];
        if (items.length > 0) {
          videoPath = items[0].abs_path || items[0].path;
          const pathEl = document.getElementById('pub-video-path');
          if (pathEl) pathEl.value = videoPath;
          if (items[0].subtitle_path) {
            const subEl = document.getElementById('pub-sub-path');
            if (subEl) subEl.value = items[0].subtitle_path;
          }
          toast('ℹ Đã tự chọn video đã xử lý gần nhất: ' + items[0].name, 'info', 4000);
        }
      } catch (err) {
        console.warn('Cannot fetch completed videos:', err);
      }
    }

    if (!videoPath) {
      toast('⚠ Vui lòng chọn hoặc duyệt file video trước khi mở TikTok Studio!', 'warning', 6000);
      const logBox = document.getElementById('tt-upload-log');
      if (logBox) {
        logBox.style.display = 'block';
        logBox.innerHTML = '<div style="color:#f59e0b">⚠ Chưa có video được chọn. Vui lòng chọn file video ở trên trước khi mở TikTok Studio!</div>';
      }
      return;
    }

    const ttTitle = document.getElementById('tt-title')?.value?.trim() || '';
    const ttTags  = document.getElementById('tt-tags')?.value?.trim()  || '';
    const caption = (window._pBuildCaption || ((a, b) => [a, b].filter(Boolean).join('\n')))(ttTitle, ttTags);
    const privacy = document.getElementById('tt-privacy')?.value || 'PUBLIC_TO_EVERYONE';
    const accountId = document.getElementById('tt-account-select')?.value || '';
    const autoPublish = document.getElementById('pub-tt-auto-post')?.checked || false;

    let scheduledTime = '';
    if (document.getElementById('pub-tt-use-schedule')?.checked) {
      const raw = document.getElementById('pub-tt-schedule-dt')?.value;
      if (!raw) {
        toast('⚠ Vui lòng chọn ngày giờ đặt lịch', 'warning');
        return;
      }
      const dt = new Date(raw);
      const minFuture = new Date(Date.now() + 15 * 60 * 1000);
      if (dt > minFuture) {
        scheduledTime = dt.toISOString();
      } else {
        toast('⚠ Lịch phải ít nhất 15 phút trong tương lai', 'warning');
        return;
      }
    }

    if (caption) {
      try { await navigator.clipboard.writeText(caption); } catch (_) {}
    }

    const btn = document.getElementById('pub-tt-btn') || document.querySelector('[onclick*="pubOpenTikTok"]');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang khởi động Chromium...'; }

    const closeBtn = document.getElementById('pub-tt-close-btn');
    if (closeBtn) closeBtn.style.display = 'none';

    const logBox = document.getElementById('tt-upload-log');
    if (logBox) {
      logBox.style.display = 'block';
      logBox.innerHTML = '<div style="color:var(--text-muted)">⏳ Đang gửi yêu cầu chuẩn bị upload TikTok...</div>';
    }

    const payload = {
      video_path: videoPath,
      caption,
      privacy,
      account_id: accountId,
      auto_publish: autoPublish
    };
    if (scheduledTime) payload.scheduled_time = scheduledTime;

    const r = await fetch('/api/tiktok/prepare_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const d = await r.json();

    if (!d.ok) {
      if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
      toast('❌ TikTok: ' + (d.error || 'Lỗi không xác định'), 'error', 8000);
      if (logBox) logBox.innerHTML += `<div style="color:#ef4444">❌ Lỗi: ${d.error || 'Không thể tạo phiên'}</div>`;
      return;
    }

    _currentTtSessionId = d.session_id;
    if (closeBtn) closeBtn.style.display = 'inline-block';
    if (btn) btn.textContent = autoPublish ? '⏳ Đang tự động đăng...' : '⏳ Đang xử lý trên TikTok...';

    toast('✅ Đang mở trình duyệt Chromium trên màn hình máy tính. Vui lòng quan sát cửa sổ TikTok Studio...', 'success', 7000);

    // Start polling status
    _pubPollTikTokSession(d.session_id);
  } catch (e) {
    console.error('pubOpenTikTok error:', e);
    toast('❌ TikTok lỗi: ' + (e.message || e), 'error', 8000);
    const btn = document.getElementById('pub-tt-btn') || document.querySelector('[onclick*="pubOpenTikTok"]');
    if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
  }
}

function _pubPollTikTokSession(sessionId) {
  if (_ttPollTimer) clearInterval(_ttPollTimer);

  const btn = document.getElementById('pub-tt-btn') || document.querySelector('[onclick*="pubOpenTikTok"]');
  const closeBtn = document.getElementById('pub-tt-close-btn');
  const logBox = document.getElementById('tt-upload-log');

  _ttPollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/tiktok/prepare_status?session_id=${sessionId}`);
      const data = await res.json();
      if (!data.ok) return;

      if (logBox && Array.isArray(data.log)) {
        logBox.innerHTML = data.log.map(item => {
          let color = '#93c5fd';
          if (item.level === 'error') color = '#ef4444';
          else if (item.level === 'warning') color = '#f59e0b';
          else if (item.level === 'success') color = '#10b981';
          return `<div style="color:${color}">${item.msg}</div>`;
        }).join('');
        logBox.scrollTop = logBox.scrollHeight;
      }

      if (data.status === 'published') {
        clearInterval(_ttPollTimer);
        toast('🎉 Đã đăng video lên TikTok thành công!', 'success', 8000);
        if (btn) { btn.disabled = false; btn.textContent = '✅ Đã đăng thành công!'; }
        if (closeBtn) closeBtn.style.display = 'none';
      } else if (data.status === 'ready') {
        toast('✅ Trình duyệt TikTok đã sẵn sàng! Bạn hãy kiểm tra lại và nhấn Đăng.', 'success', 6000);
        if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
      } else if (data.done) {
        clearInterval(_ttPollTimer);
        if (data.status === 'error') {
          toast('❌ Lỗi phiên TikTok: ' + (data.error || ''), 'error', 8000);
        }
        if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
        if (closeBtn) closeBtn.style.display = 'none';
      }
    } catch (err) {
      console.warn('Poll tiktok status failed:', err);
    }
  }, 1500);
}

async function pubCloseTikTokSession() {
  if (!_currentTtSessionId) return;
  try {
    await fetch('/api/tiktok/prepare_close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: _currentTtSessionId })
    });
    toast('Đã đóng trình duyệt TikTok', 'info');
    const closeBtn = document.getElementById('pub-tt-close-btn');
    if (closeBtn) closeBtn.style.display = 'none';
    const btn = document.getElementById('pub-tt-btn') || document.querySelector('[onclick*="pubOpenTikTok"]');
    if (btn) { btn.disabled = false; btn.textContent = '🎵 Mở TikTok Studio & tự điền nội dung'; }
  } catch (e) {
    console.warn(e);
  }
}

async function pubLoadRecentVideos() {
  try {
    const res = await fetch('/api/files/completed');
    const data = await res.json();
    const items = data.items || [];
    const select = document.getElementById('pub-recent-videos');
    const wrap = document.getElementById('pub-recent-select-wrap');
    if (!select || !wrap) return;

    if (items.length === 0) {
      wrap.style.display = 'none';
      return;
    }

    wrap.style.display = 'flex';
    select.innerHTML = '<option value="">-- Chọn video đã xử lý gần đây (' + items.length + ' video) --</option>' +
      items.map(it => `<option value="${it.abs_path || it.path}" data-sub="${it.subtitle_path || ''}">${it.name} (${it.size_str || ''})</option>`).join('');

    // If current pub-video-path is empty, auto-fill with the first video!
    const pathInput = document.getElementById('pub-video-path');
    if (pathInput && !pathInput.value.trim() && items[0]) {
      pathInput.value = items[0].abs_path || items[0].path;
      select.value = items[0].abs_path || items[0].path;
      const subInput = document.getElementById('pub-sub-path');
      if (subInput && !subInput.value.trim() && items[0].subtitle_path) {
        subInput.value = items[0].subtitle_path;
      }
    }
  } catch (err) {
    console.warn('pubLoadRecentVideos failed:', err);
  }
}

function pubSelectRecentVideo(path) {
  if (!path) return;
  const pathInput = document.getElementById('pub-video-path');
  if (pathInput) pathInput.value = path;
  window._pubVideoFile = null;
  window._pubUploadedVideoPath = '';

  const select = document.getElementById('pub-recent-videos');
  const opt = select ? select.selectedOptions[0] : null;
  const sub = opt ? opt.getAttribute('data-sub') : '';
  const subInput = document.getElementById('pub-sub-path');
  if (subInput && sub) {
    subInput.value = sub;
  }
  toast('✅ Đã chọn video: ' + path.split(/[\\/]/).pop(), 'success');
}

window.pubLoadRecentVideos = pubLoadRecentVideos;
window.pubSelectRecentVideo = pubSelectRecentVideo;
window.pubOpenTikTok = pubOpenTikTok;
window.pubCloseTikTokSession = pubCloseTikTokSession;

function pubTtToggleSchedule() {
  const checked = document.getElementById('pub-tt-use-schedule')?.checked;
  const box = document.getElementById('pub-tt-schedule-fields');
  if (box) box.style.display = checked ? 'block' : 'none';

  if (checked) {
    const dtInput = document.getElementById('pub-tt-schedule-dt');
    if (dtInput && !dtInput.value) {
      const future = new Date(Date.now() + 30 * 60 * 1000);
      const off = future.getTimezoneOffset() * 60 * 1000;
      const local = new Date(future.getTime() - off);
      dtInput.value = local.toISOString().slice(0, 16);
    }
    if (dtInput) {
      const now = new Date(Date.now() + 15 * 60 * 1000);
      const off = now.getTimezoneOffset() * 60 * 1000;
      dtInput.min = new Date(now.getTime() - off).toISOString().slice(0, 16);
    }
  }
}

/* ── Facebook API integration (publish page) ── */
async function pubFbInit() {
  pubFbLoadAppCredentials();
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

async function pubFbLoadAppCredentials() {
  try {
    const data = await fetch('/api/facebook/app_credentials').then(r => r.json());
    const input = document.getElementById('pub-fb-app-id');
    if (input) input.value = data.app_id || '';
  } catch (_) {}
}

async function pubFbSaveAppCredentials() {
  const app_id = document.getElementById('pub-fb-app-id')?.value.trim() || '';
  const app_secret = document.getElementById('pub-fb-app-secret')?.value.trim() || '';
  try {
    const res = await fetch('/api/facebook/app_credentials', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app_id, app_secret})});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Không lưu được cấu hình');
    document.getElementById('pub-fb-app-secret').value = '';
    if (typeof toast === 'function') toast('Đã lưu Facebook App ID / Secret', 'success');
  } catch (error) {
    if (typeof toast === 'function') toast(error.message, 'error');
  }
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
      const status = await fetch('/api/facebook/status').then(r => r.json());
      if (status.connected) {
        _pubFbShowConnected(status.user, status.pages || []);
        _pubFbUpdateTokenStatus(status);
      }
    } else {
      const msg = data.error || 'Gia hạn thất bại';
      toast('❌ ' + msg, 'error', 8000);
      if (data.need_reauth) {
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

  try {
    const d = await fetch('/api/facebook/status').then(r => r.json());
    if (!d.connected) {
      toast('⚠ Facebook chưa kết nối — hãy bấm "Kết nối Facebook" trước', 'warning', 6000);
      return;
    }
  } catch (_) {}

  const title    = document.getElementById('fb-title')?.value?.trim() || '';
  const tags     = document.getElementById('fb-tags')?.value?.trim()  || '';
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
    if (postType !== 'reel') {
      form.append('title', title);
      if (videoPath) form.append('video_path', videoPath);
      else           form.append('video_file', videoFile);
    } else {
      if (!videoPath) {
        throw new Error('Reel cần file trên đĩa — hãy xử lý video trước rồi điền đường dẫn.');
      }
      form.append('video_path', videoPath);
    }
    return form;
  };

  _pubFbLog(`🚀 Đang đăng lên Facebook (${postType === 'reel' ? 'Reel' : 'Video'})...`, 'info');

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
        if (typeof _pFbShowTokenModal === 'function') {
          const action = await _pFbShowTokenModal(result.errorMsg || '');
          if (action === 'retry')  { form = buildForm(); attempt--; continue; }
          if (action === 'skip')   { _pubFbLog('⏭ Bỏ qua video này', 'warning'); return; }
          return;
        } else {
          _pubFbLog('❌ Token hết hạn — vui lòng kết nối lại Facebook', 'error');
          toast('⚠ Token Facebook hết hạn — kết nối lại', 'warning', 6000);
          return;
        }
      }

      if (result.errorMsg) toast('Lỗi: ' + result.errorMsg, 'error');
      return;
    }
    _pubFbLog('❌ Đã thử lại 5 lần nhưng không thành công', 'error');
  } finally {
    setBusy(false);
  }
}

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
          if (d.url) {
            _pubFbLog('🔗 ' + d.url, 'success');
            const vid = d.video_id || (d.url.match(/(?:videos\/|reel\/)(\d+)/) || [])[1];
            if (vid) {
              const fbLogBox = document.getElementById('fb-upload-log');
              if (fbLogBox) {
                const btnDiv = document.createElement('div');
                btnDiv.style.marginTop = '6px';
                btnDiv.innerHTML = `<button class="btn btn-xs btn-danger" onclick="pubDeleteFacebookVideo('${vid}')">🗑 Thu hồi video Facebook</button>`;
                fbLogBox.appendChild(btnDiv);
              }
            }
          }
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
  if (typeof _setYouTubeAuthenticated === 'function') {
    _setYouTubeAuthenticated(!!channel, channel || null);
    return;
  }
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

document.addEventListener('DOMContentLoaded', async () => {
  try { const r = await fetch('/api/youtube_auth'); const d = await r.json(); if (d.authenticated) _updateYtAuthUI(d.channel); } catch(_) {}
  pubFbInit();
  pubSwitchTab('youtube');
});

/* ── Video Revocation / Deletion Handlers ── */
async function pubDeleteYouTubeVideo(videoId) {
  if (!videoId) return false;
  if (!confirm(`Bạn có chắc chắn muốn XÓA / THU HỒI video YouTube (${videoId}) vĩnh viễn không?`)) return false;
  try {
    toast('⏳ Đang xóa video trên YouTube...', 'info');
    const res = await fetch('/api/youtube_video_delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId })
    });
    const d = await res.json();
    if (d.ok) {
      toast(`✅ Đã xóa video ${videoId} khỏi YouTube thành công!`, 'success', 6000);
      return true;
    } else {
      toast(`❌ Xóa video thất bại: ${d.error || 'Lỗi không xác định'}`, 'error', 8000);
      return false;
    }
  } catch (e) {
    toast(`❌ Lỗi kết nối khi xóa video: ${e.message}`, 'error', 8000);
    return false;
  }
}

async function pubDeleteFacebookVideo(videoId, pageId) {
  if (!videoId) return false;
  if (!confirm(`Bạn có chắc chắn muốn XÓA / THU HỒI video Facebook (${videoId}) vĩnh viễn không?`)) return false;
  try {
    toast('⏳ Đang xóa video trên Facebook...', 'info');
    const res = await fetch('/api/facebook/delete_video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId, page_id: pageId || '' })
    });
    const d = await res.json();
    if (d.ok) {
      toast(`✅ Đã xóa video ${videoId} khỏi Facebook thành công!`, 'success', 6000);
      return true;
    } else {
      toast(`❌ Xóa video thất bại: ${d.error || 'Lỗi không xác định'}`, 'error', 8000);
      return false;
    }
  } catch (e) {
    toast(`❌ Lỗi kết nối khi xóa video: ${e.message}`, 'error', 8000);
    return false;
  }
}

async function pubRevokeVideoById() {
  const platform = document.getElementById('pub-revoke-platform')?.value || 'youtube';
  const rawId = document.getElementById('pub-revoke-id')?.value?.trim() || '';
  const logEl = document.getElementById('pub-revoke-log');

  if (!rawId) {
    toast('⚠ Vui lòng nhập Video ID hoặc link video cần thu hồi', 'warning');
    return;
  }

  // Parse ID if full link
  let cleanId = rawId;
  if (platform === 'youtube') {
    const m = rawId.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|shorts\/|embed\/))([a-zA-Z0-9_-]{11})/);
    if (m) cleanId = m[1];
  } else if (platform === 'facebook') {
    const m = rawId.match(/(?:videos\/|reel\/|story\.php\?story_fbid=)(\d+)/);
    if (m) cleanId = m[1];
  }

  if (logEl) {
    logEl.style.display = 'block';
    logEl.style.background = 'rgba(239, 68, 68, 0.1)';
    logEl.style.color = '#ef4444';
    logEl.innerHTML = `⏳ Đang gửi yêu cầu thu hồi video <b>${cleanId}</b> trên ${platform === 'youtube' ? 'YouTube' : 'Facebook'}...`;
  }

  let ok = false;
  if (platform === 'youtube') {
    ok = await pubDeleteYouTubeVideo(cleanId);
  } else {
    ok = await pubDeleteFacebookVideo(cleanId);
  }

  if (logEl) {
    if (ok) {
      logEl.style.background = 'rgba(34, 197, 94, 0.1)';
      logEl.style.color = '#22c55e';
      logEl.innerHTML = `✅ Đã thu hồi & xóa thành công video <b>${cleanId}</b>.`;
      const input = document.getElementById('pub-revoke-id');
      if (input) input.value = '';
    } else {
      logEl.innerHTML = `❌ Thu hồi thất bại cho video <b>${cleanId}</b>. Hãy kiểm tra quyền hoặc tài khoản đã đăng video.`;
    }
  }
}

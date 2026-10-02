let _schItems = [];
let _schProfiles = {};
let _schTrendingItems = [];

const _schLabels = {
  draft: 'Bản nháp',
  planned: 'Đã lên lịch',
  queued: 'Chờ xử lý',
  processing: 'Đang xử lý',
  ready: 'Sẵn sàng',
  publishing: 'Đang đăng',
  published: 'Đã đăng',
  failed: 'Lỗi'
};

const _schEsc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ── SVG ICONS ── */
const _SCH_ICONS = {
  youtube: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>',
  tiktok: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.24 1.07-.14 1.61.24 1.16 1.18 2.09 2.35 2.3 1.05.22 2.18-.08 2.94-.83.65-.62.98-1.51 1.01-2.4.03-4.25.01-8.5.02-12.75z"/></svg>',
  facebook: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>',
  clock: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
  play: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>',
  send: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>',
  edit: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>',
  trash: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
  link: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>',
  file: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>',
  channel: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>'
};

/* ── SWITCH MAIN TABS (SCHEDULE VS TRENDING AI) ── */
window.schedulerSwitchMainTab = function(tab) {
  const schedBtn = document.getElementById('sch-view-schedule-btn');
  const trendBtn = document.getElementById('sch-view-trending-btn');
  const schedPanel = document.getElementById('sch-panel-schedule');
  const trendPanel = document.getElementById('sch-panel-trending');

  if (tab === 'trending') {
    trendBtn?.classList.add('active');
    schedBtn?.classList.remove('active');
    if (trendPanel) trendPanel.style.display = 'block';
    if (schedPanel) schedPanel.style.display = 'none';
    schedulerLoadTrendingHot();
  } else {
    schedBtn?.classList.add('active');
    trendBtn?.classList.remove('active');
    if (schedPanel) schedPanel.style.display = 'flex';
    if (trendPanel) trendPanel.style.display = 'none';
  }
};

/* ── SWITCH INPUT TABS ── */
window.schedulerSwitchInputTab = function(type) {
  const urlBtn = document.getElementById('sch-tab-url-btn');
  const fileBtn = document.getElementById('sch-tab-file-btn');
  const urlBox = document.getElementById('sch-input-url-box');
  const fileBox = document.getElementById('sch-input-file-box');
  if (type === 'file') {
    fileBtn?.classList.add('active');
    urlBtn?.classList.remove('active');
    if (fileBox) fileBox.style.display = 'block';
    if (urlBox) urlBox.style.display = 'none';
  } else {
    urlBtn?.classList.add('active');
    fileBtn?.classList.remove('active');
    if (urlBox) urlBox.style.display = 'block';
    if (fileBox) fileBox.style.display = 'none';
  }
};

/* ── SWITCH SCHEDULING MODE ── */
window.schedulerSwitchSchedMode = function(mode) {
  const singleBtn = document.getElementById('sch-mode-single-btn');
  const batchBtn = document.getElementById('sch-mode-batch-btn');
  const batchSettings = document.getElementById('sch-batch-settings');
  const lbl = document.getElementById('sch-time-lbl');
  if (mode === 'batch') {
    batchBtn?.classList.add('active');
    singleBtn?.classList.remove('active');
    if (batchSettings) batchSettings.style.display = 'block';
    if (lbl) lbl.textContent = 'Thời gian bắt đầu chuỗi đăng';
  } else {
    singleBtn?.classList.add('active');
    batchBtn?.classList.remove('active');
    if (batchSettings) batchSettings.style.display = 'none';
    if (lbl) lbl.textContent = 'Thời gian đăng bài';
  }
  schedulerUpdateBatchPreview();
};

/* ── FILE SELECTION ── */
window.schedulerHandleFileSelected = function(input) {
  const file = input.files?.[0];
  const lbl = document.getElementById('sch-selected-file-name');
  if (!lbl) return;
  if (file) {
    lbl.textContent = `Đã chọn: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
    lbl.classList.add('text-blue-600', 'font-medium');
  } else {
    lbl.textContent = 'Chưa chọn file';
    lbl.classList.remove('text-blue-600', 'font-medium');
  }
};

/* ── MULTI-PLATFORM TOGGLES ── */
window.schedulerToggleAllPlatforms = function(enable) {
  ['youtube', 'tiktok', 'facebook'].forEach(plat => {
    const cb = document.getElementById(`sch-cb-${plat}`);
    if (cb) cb.checked = enable;
    schedulerUpdatePlatformRow(plat);
  });
};

window.schedulerUpdatePlatformRow = function(plat) {
  const cb = document.getElementById(`sch-cb-${plat}`);
  const card = document.getElementById(`sch-plat-row-${plat}`);
  const box = document.getElementById(`sch-acc-box-${plat}`);
  document.querySelector(`#sch-platform-pills .sch-platform-toggle[data-platform="${plat}"]`)?.setAttribute('aria-pressed', String(!!cb?.checked));
  if (cb?.checked) {
    card?.classList.add('selected');
    if (box) box.style.opacity = '1';
  } else {
    card?.classList.remove('selected');
    if (box) box.style.opacity = '0.4';
  }
};

/* ── PRESETS ── */
async function schedulerLoadProfiles() {
  try {
    const res = await fetch('/api/process_profiles');
    const data = await res.json();
    if (data.ok && data.profiles) {
      _schProfiles = data.profiles;
      const sel = document.getElementById('sch-preset');
      if (sel) {
        sel.innerHTML = '<option value="">Cấu hình hiện tại ở bước 2</option>' +
          Object.keys(_schProfiles).map(k => {
            const p = _schProfiles[k];
            const desc = p.type ? ` (${p.type} - ${p.aspect || '9:16'})` : '';
            return `<option value="${_schEsc(k)}">${_schEsc(k)}${_schEsc(desc)}</option>`;
          }).join('');
      }
    }
  } catch (e) {
    console.warn('Could not load process profiles:', e);
  }
}

window.schedulerPresetChanged = function() {
  const sel = document.getElementById('sch-preset');
  const name = sel?.value;
  if (!name || !_schProfiles[name]) return;
  const p = _schProfiles[name];
  const s = p.settings || {};

  const ratio = document.getElementById('sch-ratio');
  if (ratio) {
    if (p.aspect === '9x16' || p.aspect === '9:16') ratio.value = '9:16';
    else if (p.aspect === '16x9' || p.aspect === '16:9') ratio.value = '16:9';
  }
  const sub = document.getElementById('sch-sub');
  if (sub && s['proc-burn-vi'] !== undefined) sub.checked = !!s['proc-burn-vi'];
  const trans = document.getElementById('sch-translate');
  if (trans && s['proc-translate-subs'] !== undefined) trans.checked = !!s['proc-translate-subs'];
  const voice = document.getElementById('sch-voice');
  if (voice && s['proc-voice'] !== undefined) voice.checked = !!s['proc-voice'];
  const wm = document.getElementById('sch-watermark');
  if (wm && s['proc-blur-original'] !== undefined) wm.checked = !!s['proc-blur-original'];
};

/* ── POPULATE PLATFORM ACCOUNTS ── */
function schedulerPopulateAccounts() {
  // 1. YouTube Accounts
  const ytSel = document.getElementById('sch-acc-youtube');
  if (ytSel) {
    const ytRows = (window._accounts?.youtube || []);
    let ytHtml = '<option value="">Kênh YouTube mặc định (OAuth)</option>';
    ytRows.forEach(a => {
      ytHtml += `<option value="${_schEsc(a.id)}" data-name="${_schEsc(a.channel_title || a.name || a.id)}">${_schEsc(a.channel_title || a.name || a.id)}</option>`;
    });
    ytSel.innerHTML = ytHtml;
  }

  // 2. Facebook Accounts (Fanpages)
  const fbSel = document.getElementById('sch-acc-facebook');
  if (fbSel) {
    const fbAccounts = (window._accounts?.facebook || []);
    let fbHtml = '<option value="">Chọn Fanpage Facebook</option>';
    fbAccounts.forEach(acc => {
      const pages = acc.pages || [];
      if (pages.length) {
        pages.forEach(p => {
          fbHtml += `<option value="${_schEsc(p.id)}" data-name="${_schEsc(p.name)}">${_schEsc(p.name)} (${_schEsc(acc.name)})</option>`;
        });
      } else {
        fbHtml += `<option value="${_schEsc(acc.id)}" data-name="${_schEsc(acc.name)}">${_schEsc(acc.name)} (Cá nhân)</option>`;
      }
    });
    fbSel.innerHTML = fbHtml;
  }

  // 3. TikTok Accounts
  const ttSel = document.getElementById('sch-acc-tiktok');
  if (ttSel) {
    ttSel.innerHTML = '<option value="default" data-name="TikTok Master Profile">Hồ sơ TikTok mặc định (Browser Profile)</option>';
  }
}

/* ── BATCH PREVIEW ── */
window.schedulerUpdateBatchPreview = function() {
  const previewEl = document.getElementById('sch-batch-preview');
  if (!previewEl) return;
  const rawUrls = (document.getElementById('sch-urls')?.value || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  const count = rawUrls.length || 1;
  const rule = document.getElementById('sch-batch-rule')?.value || 'golden';
  const startVal = document.getElementById('sch-time')?.value;

  const countBadge = document.getElementById('sch-url-counter');
  if (countBadge) countBadge.textContent = `${rawUrls.length} link`;

  const startDate = startVal ? new Date(startVal) : new Date(Date.now() + 3600000);

  if (rule === 'golden') {
    previewEl.innerHTML = `Dự kiến: <b>${count} video</b> sẽ được tự động xếp vào khung giờ vàng <b>11:30 trưa</b> và <b>19:30 tối</b> tính từ ngày ${startDate.toLocaleDateString('vi-VN')}.`;
  } else {
    const hours = parseFloat(rule) || 24;
    const endDate = new Date(startDate.getTime() + (count - 1) * hours * 3600000);
    previewEl.innerHTML = `Dự kiến: <b>${count} video</b> rải đều cách nhau <b>${hours} giờ</b>, kết thúc vào <b>${endDate.toLocaleString('vi-VN')}</b>.`;
  }
};

/* ── LOAD SCHEDULER DATA ── */
window.schedulerLoad = async function() {
  try {
    if (typeof window.loadAccounts === 'function') await window.loadAccounts();
    schedulerPopulateAccounts();
    await schedulerLoadProfiles();

    const status = document.getElementById('sch-filter')?.value || '';
    const [r, s] = await Promise.all([
      fetch('/api/scheduler/items' + (status ? '?status=' + encodeURIComponent(status) : '')),
      fetch('/api/scheduler/stats')
    ]);
    const data = await r.json(), stats = await s.json();
    _schItems = data.items || [];

    const keys = [
      ['planned', 'Đã lên lịch', 'text-blue-600 dark:text-blue-400', 'bg-blue-50 dark:bg-blue-950/40'],
      ['processing', 'Đang xử lý', 'text-amber-500 dark:text-amber-400', 'bg-amber-50 dark:bg-amber-950/40'],
      ['ready', 'Sẵn sàng', 'text-emerald-600 dark:text-emerald-400', 'bg-emerald-50 dark:bg-emerald-950/40'],
      ['published', 'Đã đăng', 'text-green-600 dark:text-green-400', 'bg-green-50 dark:bg-green-950/40'],
      ['failed', 'Lỗi', 'text-red-500 dark:text-red-400', 'bg-red-50 dark:bg-red-950/40']
    ];
    document.getElementById('sch-stats').innerHTML = keys.map(([k, l, color, bg]) =>
      `<div class="sch-card sch-stat border border-slate-200 dark:border-slate-800 ${bg}">
        <span class="text-slate-500 dark:text-slate-400 text-xs font-medium">${l}</span>
        <b class="${color}">${(k === 'planned' ? (stats.counts?.planned || 0) + (stats.counts?.queued || 0) : stats.counts?.[k]) || 0}</b>
      </div>`
    ).join('');

    schedulerRender();
  } catch (e) {
    if (typeof toast === 'function') toast('Không tải được lịch: ' + e.message, 'error');
  }
};

/* ── RENDER ITEMS ── */
window.schedulerRender = function() {
  const q = (document.getElementById('sch-search')?.value || '').toLowerCase();
  const root = document.getElementById('sch-list');
  if (!root) return;

  const rows = _schItems.filter(x => JSON.stringify(x).toLowerCase().includes(q));
  if (!rows.length) {
    root.innerHTML = `<div class="sch-card p-10 text-center text-slate-400">
      <div class="flex justify-center mb-2 text-slate-300 dark:text-slate-600">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
      </div>
      <div class="font-medium text-xs text-slate-600 dark:text-slate-300">Chưa có bài đăng nào trong danh sách</div>
      <div class="text-[11px] text-slate-400 mt-0.5">Dán link video hoặc tìm video trending bằng AI ở cột bên trái để thêm vào lịch</div>
    </div>`;
    return;
  }

  const pBadgeClass = {
    youtube: 'sch-badge-yt',
    tiktok: 'sch-badge-tt',
    facebook: 'sch-badge-fb'
  };

  const statusColor = {
    draft: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    planned: 'bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300',
    processing: 'bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300 animate-pulse',
    ready: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-300',
    publishing: 'bg-purple-100 text-purple-700 dark:bg-purple-900/60 dark:text-purple-300 animate-pulse',
    published: 'bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300',
    failed: 'bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300'
  };

  const pct = {
    draft: 15,
    planned: 35,
    processing: 60,
    ready: 80,
    publishing: 90,
    published: 100,
    failed: 100
  };

  root.innerHTML = rows.map(x => {
    const title = x.post_title || x.source_title || (x.source_url ? (x.source_url.startsWith('http') ? new URL(x.source_url).hostname : x.source_url) : 'Chưa đặt tiêu đề');
    const platform = x.platform || 'youtube';
    const pClass = pBadgeClass[platform] || 'sch-badge-yt';
    const sClass = statusColor[x.status] || 'bg-slate-100 text-slate-700';
    const currentPct = pct[x.status] || 20;
    const isReady = x.status === 'ready' || (x.video_path && x.status !== 'processing');
    const isProcessing = x.status === 'queued' || x.status === 'planned' || x.status === 'processing' || x.status === 'publishing';
    const platIcon = _SCH_ICONS[platform] || _SCH_ICONS.youtube;

    return `<article class="sch-card sch-item status-${x.status}">
      <div class="flex items-start justify-between gap-2.5 flex-wrap">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="sch-badge-platform ${pClass}">
            ${platIcon}
            <span>${_schEsc(platform)}</span>
          </span>
          <span class="sch-badge-status ${sClass}">${_schEsc(_schLabels[x.status] || x.status)}</span>
          ${x.preset_name ? `<span class="sch-meta-tag">${_schEsc(x.preset_name)}</span>` : ''}
          <span class="sch-meta-tag">${_schEsc(x.processing?.target_aspect?.replace('x', ':') || x.processing?.aspect_ratio || 'auto')}</span>
        </div>
        <div class="flex items-center gap-1">
          ${!isReady && !isProcessing ? `<button class="btn btn-secondary text-[11px] px-2 py-0.5 text-amber-600 font-semibold flex items-center gap-1" title="Xử lý video ngay" onclick="schedulerProcessItem('${x.id}')">
            ${_SCH_ICONS.play} <span>Xử lý ngay</span>
          </button>` : ''}
          ${isReady && x.status !== 'published' && !isProcessing ? `<button class="btn btn-primary text-[11px] px-2 py-0.5 font-semibold flex items-center gap-1" title="Đăng ngay lên mạng xã hội" onclick="schedulerPublishItem('${x.id}')">
            ${_SCH_ICONS.send} <span>Đăng ngay</span>
          </button>` : ''}
          <button class="btn btn-secondary text-[11px] px-2 py-0.5 flex items-center gap-1" title="Chỉnh sửa" onclick="schedulerEditModal('${x.id}')">
            ${_SCH_ICONS.edit} <span>Sửa</span>
          </button>
          <button class="btn btn-secondary text-[11px] px-1.5 py-0.5 text-red-500 hover:text-red-700" title="Xóa khỏi lịch" onclick="schedulerDelete('${x.id}')">
            ${_SCH_ICONS.trash}
          </button>
        </div>
      </div>

      <div>
        <h3 class="font-bold text-xs text-slate-800 dark:text-slate-100 leading-snug">${_schEsc(title)}</h3>
        ${x.source_url ? `<a href="${_schEsc(x.source_url)}" target="_blank" class="text-blue-500 hover:underline text-[11px] break-all inline-flex items-center gap-1 mt-0.5">
          ${_SCH_ICONS.link} <span>${_schEsc(x.source_url)}</span>
        </a>` : ''}
        ${x.video_path ? `<div class="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5 font-mono truncate flex items-center gap-1">
          ${_SCH_ICONS.file} <span>${_schEsc(x.video_path)}</span>
        </div>` : ''}
      </div>

      ${(x.caption || x.hashtags) ? `<div class="sch-caption-preview">
        ${x.caption ? `<div>${_schEsc(x.caption)}</div>` : ''}
        ${x.hashtags ? `<div class="text-blue-600 dark:text-blue-400 font-semibold mt-1">${_schEsc(x.hashtags)}</div>` : ''}
      </div>` : ''}

      <div class="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 flex-wrap gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
        <div class="flex items-center gap-3 flex-wrap">
          <span class="flex items-center gap-1">
            ${_SCH_ICONS.clock}
            <b>${x.scheduled_at ? _schEsc(new Date(x.scheduled_at).toLocaleString('vi-VN')) : 'Chưa định giờ'}</b>
          </span>
          <span class="flex items-center gap-1">
            ${_SCH_ICONS.channel}
            <span>Kênh: <b>${_schEsc(x.account_name || 'Chưa gán')}</b></span>
          </span>
          ${x.published_url ? `<a href="${_schEsc(x.published_url)}" target="_blank" class="text-emerald-600 font-bold hover:underline">Xem bài đăng</a>` : ''}
        </div>
        ${x.error ? `<span class="text-red-500 font-medium text-[10px] truncate max-w-xs" title="${_schEsc(x.error)}">Lỗi: ${_schEsc(x.error)}</span>` : ''}
      </div>

      <div class="sch-progress-bar">
        <i style="width:${currentPct}%; background:${x.status === 'failed' ? '#ef4444' : (x.status === 'published' ? '#10b981' : '#3b82f6')}"></i>
      </div>
    </article>`;
  }).join('');
};

/* ── ADD ITEMS (MULTI-PLATFORM SUPPORT) ── */
window.schedulerAdd = async function() {
  const isFileTab = document.getElementById('sch-tab-file-btn')?.classList.contains('active');
  let urls = [];
  let videoPath = '';

  if (isFileTab) {
    const fileInput = document.getElementById('sch-file-input');
    if (!fileInput.files?.[0]) {
      return (typeof toast === 'function') ? toast('Vui lòng chọn một file video', 'warning') : alert('Chọn video');
    }
    const file = fileInput.files[0];
    urls = [file.name];
    videoPath = file.name;
  } else {
    const urlsText = document.getElementById('sch-urls')?.value.trim();
    if (!urlsText) {
      return (typeof toast === 'function') ? toast('Hãy nhập ít nhất một đường link video', 'warning') : alert('Nhập link');
    }
    urls = urlsText.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  }

  // Multi-platform selection
  const selectedPlatforms = [];
  const platformAccounts = {};

  if (document.getElementById('sch-cb-youtube')?.checked) {
    selectedPlatforms.push('youtube');
    const sel = document.getElementById('sch-acc-youtube');
    const opt = sel?.options[sel.selectedIndex];
    platformAccounts.youtube = {
      id: sel?.value || '',
      name: opt?.dataset?.name || opt?.textContent || ''
    };
  }
  if (document.getElementById('sch-cb-tiktok')?.checked) {
    selectedPlatforms.push('tiktok');
    const sel = document.getElementById('sch-acc-tiktok');
    const opt = sel?.options[sel.selectedIndex];
    platformAccounts.tiktok = {
      id: sel?.value || 'default',
      name: opt?.dataset?.name || 'TikTok Profile'
    };
  }
  if (document.getElementById('sch-cb-facebook')?.checked) {
    selectedPlatforms.push('facebook');
    const sel = document.getElementById('sch-acc-facebook');
    const opt = sel?.options[sel.selectedIndex];
    platformAccounts.facebook = {
      id: sel?.value || '',
      name: opt?.dataset?.name || opt?.textContent || ''
    };
  }

  if (selectedPlatforms.length === 0) {
    return (typeof toast === 'function') ? toast('Vui lòng chọn ít nhất một nền tảng đăng (YouTube, TikTok, Facebook)', 'warning') : alert('Chọn nền tảng');
  }

  const isBatch = document.getElementById('sch-mode-batch-btn')?.classList.contains('active');
  const batchRule = document.getElementById('sch-batch-rule')?.value || 'golden';
  const scheduledTime = document.getElementById('sch-time')?.value;

  const presetName = document.getElementById('sch-preset')?.value || '';
  const tone = document.getElementById('sch-tone')?.value || '';
  const hashtags = document.getElementById('sch-hashtags')?.value || '';
  const roundRobin = !!document.getElementById('sch-round-robin')?.checked;

  const body = {
    urls,
    video_path: videoPath,
    platforms: selectedPlatforms,
    platform_accounts: platformAccounts,
    round_robin: roundRobin,
    is_batch: isBatch,
    batch_mode: batchRule === 'golden' ? 'golden_hours' : 'interval',
    interval_hours: parseFloat(batchRule) || 24,
    scheduled_at: scheduledTime,
    preset_name: presetName,
    tone: tone,
    hashtags: hashtags,
    processing: schedulerProcessingConfig(presetName)
  };

  try {
    const r = await fetch('/api/scheduler/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Không thể thêm vào lịch');

    if (document.getElementById('sch-urls')) document.getElementById('sch-urls').value = '';
    if (typeof toast === 'function') toast(`Đã thêm thành công ${d.count || d.ids?.length} bài vào lịch đăng!`, 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── TRIGGER PROCESS ── */
window.schedulerProcessItem = async function(id) {
  try {
    if (typeof toast === 'function') toast('Đang bắt đầu xử lý video ngầm...', 'info');
    const r = await fetch(`/api/scheduler/items/${id}/process`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Lỗi khi kích hoạt xử lý');
    if (typeof toast === 'function') toast(d.message || 'Đang xử lý video...', 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── TRIGGER PUBLISH ── */
window.schedulerPublishItem = async function(id) {
  if (!confirm('Xuất bản ngay bài đăng này lên mạng xã hội?')) return;
  try {
    if (typeof toast === 'function') toast('Đang tiến hành đăng bài...', 'info');
    const r = await fetch(`/api/scheduler/items/${id}/publish`, { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Lỗi khi đăng bài');
    if (typeof toast === 'function') toast(d.message || 'Đang đăng...', 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── DELETE ITEM ── */
window.schedulerDelete = async function(id) {
  if (!confirm('Xóa bài này khỏi lịch đăng?')) return;
  try {
    await fetch('/api/scheduler/items/' + id, { method: 'DELETE' });
    if (typeof toast === 'function') toast('Đã xóa bài đăng', 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── EDIT MODAL ── */
window.schedulerEditModal = function(id) {
  const item = _schItems.find(x => x.id === id);
  if (!item) return;

  document.getElementById('sch-edit-id').value = item.id;
  document.getElementById('sch-edit-title').value = item.post_title || item.source_title || '';
  document.getElementById('sch-edit-caption').value = item.caption || '';
  document.getElementById('sch-edit-hashtags').value = item.hashtags || '';
  document.getElementById('sch-edit-platform').value = item.platform || 'youtube';
  document.getElementById('sch-edit-acc-name').value = item.account_name || '';
  document.getElementById('sch-edit-time').value = item.scheduled_at ? item.scheduled_at.slice(0, 16) : '';
  document.getElementById('sch-edit-status').value = item.status || 'draft';

  document.getElementById('sch-edit-modal')?.classList.add('active');
};

window.schedulerCloseModal = function() {
  document.getElementById('sch-edit-modal')?.classList.remove('active');
};

window.schedulerSaveEdit = async function() {
  const id = document.getElementById('sch-edit-id')?.value;
  if (!id) return;

  const body = {
    post_title: document.getElementById('sch-edit-title')?.value || '',
    caption: document.getElementById('sch-edit-caption')?.value || '',
    hashtags: document.getElementById('sch-edit-hashtags')?.value || '',
    platform: document.getElementById('sch-edit-platform')?.value || 'youtube',
    account_name: document.getElementById('sch-edit-acc-name')?.value || '',
    scheduled_at: document.getElementById('sch-edit-time')?.value || '',
    status: document.getElementById('sch-edit-status')?.value || 'draft'
  };

  try {
    const r = await fetch(`/api/scheduler/items/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Lỗi lưu thông tin');
    if (typeof toast === 'function') toast('Đã cập nhật bài đăng', 'success');
    schedulerCloseModal();
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── AI PLANNER ── */
window.schedulerAIPlan = async function() {
  const urlsText = document.getElementById('sch-urls')?.value.trim();
  if (!urlsText) {
    return (typeof toast === 'function') ? toast('Nhập danh sách link nguồn trước khi dùng AI', 'warning') : alert('Nhập link nguồn');
  }
  const links = urlsText.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  if (!links.length) return;

  const btn = document.getElementById('sch-ai-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang phân tích link...';
  }

  try {
    const sources = [];
    for (const url of links) {
      try {
        const r = await fetch('/api/scheduler/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const d = await r.json();
        sources.push(d.ok ? d.metadata : { url, title: '', summary: '' });
      } catch (err) {
        sources.push({ url, title: '', summary: '' });
      }
    }

    if (btn) btn.textContent = 'AI đang thiết kế kế hoạch...';

    const tone = document.getElementById('sch-tone')?.value || '';
    const defaultHashtags = document.getElementById('sch-hashtags')?.value || '';
    const startAt = document.getElementById('sch-time')?.value;

    const r = await fetch('/api/scheduler/ai-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sources,
        tone,
        default_hashtags: defaultHashtags,
        start_at: startAt
      })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'AI không thể lập lịch');

    // Get active platforms
    const selectedPlatforms = [];
    const platformAccounts = {};
    if (document.getElementById('sch-cb-youtube')?.checked) {
      selectedPlatforms.push('youtube');
      platformAccounts.youtube = {
        id: document.getElementById('sch-acc-youtube')?.value || '',
        name: document.getElementById('sch-acc-youtube')?.options[document.getElementById('sch-acc-youtube')?.selectedIndex]?.dataset?.name || ''
      };
    }
    if (document.getElementById('sch-cb-tiktok')?.checked) {
      selectedPlatforms.push('tiktok');
      platformAccounts.tiktok = { id: 'default', name: 'TikTok Profile' };
    }
    if (document.getElementById('sch-cb-facebook')?.checked) {
      selectedPlatforms.push('facebook');
      platformAccounts.facebook = {
        id: document.getElementById('sch-acc-facebook')?.value || '',
        name: document.getElementById('sch-acc-facebook')?.options[document.getElementById('sch-acc-facebook')?.selectedIndex]?.dataset?.name || ''
      };
    }

    const presetName = document.getElementById('sch-preset')?.value || '';

    for (const p of d.plan) {
      await fetch('/api/scheduler/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_url: p.source_url,
          source_title: p.title || '',
          post_title: p.title || '',
          caption: p.caption || '',
          hashtags: p.hashtags || defaultHashtags,
          platforms: selectedPlatforms.length ? selectedPlatforms : ['youtube'],
          platform_accounts: platformAccounts,
          scheduled_at: p.scheduled_at || '',
          preset_name: presetName,
          status: 'planned',
          processing: schedulerProcessingConfig(presetName),
          ai_generated: true
        })
      });
    }

    if (document.getElementById('sch-urls')) document.getElementById('sch-urls').value = '';
    if (typeof toast === 'function') toast(`AI đã tạo thành công ${d.plan.length} bài đăng tối ưu!`, 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'AI phân tích & tạo lịch';
    }
  }
};

/* ── AI TRENDING SEARCH ── */
window.schedulerLoadTrendingHot = async function() {
  const container = document.getElementById('sch-trend-hot-tags');
  if (!container || container.children.length > 0) return;

  try {
    const res = await fetch('/api/scheduler/trending_hot');
    const data = await res.json();
    if (data.ok && data.topics) {
      container.innerHTML = data.topics.map(t =>
        `<span class="sch-tag-pill" onclick="schedulerSelectHotTag('${_schEsc(t.query)}')">
          ${_schEsc(t.label)}
        </span>`
      ).join('');
    }
  } catch (e) {
    console.warn('Could not load hot trending topics:', e);
  }
};

window.schedulerSelectHotTag = function(query) {
  const input = document.getElementById('sch-trend-query');
  if (input) input.value = query;
  schedulerSearchTrending();
};

window.schedulerSearchTrending = async function() {
  const query = (document.getElementById('sch-trend-query')?.value || '').trim();
  const platform = document.getElementById('sch-trend-platform')?.value || 'all';
  const limit = parseInt(document.getElementById('sch-trend-limit')?.value || '8');
  const resultsBox = document.getElementById('sch-trend-results-box');
  const btn = document.getElementById('sch-trend-search-btn');

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>Đang quét xu hướng AI...</span>';
  }
  if (resultsBox) {
    resultsBox.innerHTML = '<div class="text-xs text-slate-400 text-center py-6">AI đang phân tích và tìm kiếm các video thịnh hành nhất...</div>';
  }

  try {
    const res = await fetch('/api/scheduler/trending_search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, platform, limit })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Lỗi khi tìm kiếm');

    _schTrendingItems = data.results || [];
    schedulerRenderTrendingResults();
  } catch (e) {
    if (resultsBox) {
      resultsBox.innerHTML = `<div class="text-xs text-red-500 text-center py-4">Lỗi: ${_schEsc(e.message)}</div>`;
    }
    if (typeof toast === 'function') toast('Lỗi tìm kiếm: ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg><span>Tìm kiếm video Trending AI</span>`;
    }
  }
};

window.schedulerRenderTrendingResults = function() {
  const container = document.getElementById('sch-trend-results-box');
  if (!container) return;

  if (!_schTrendingItems.length) {
    container.innerHTML = '<div class="text-xs text-slate-400 text-center py-6">Không tìm thấy video nào. Hãy thử từ khóa khác.</div>';
    return;
  }

  container.innerHTML = `
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs font-semibold text-slate-600 dark:text-slate-300">Gợi ý ${_schTrendingItems.length} video xu hướng:</span>
      <button class="text-[11px] text-blue-600 dark:text-blue-400 hover:underline font-medium" onclick="schedulerApplyAllTrending()">Thêm tất cả vào lịch</button>
    </div>
    <div class="space-y-2">` +
    _schTrendingItems.map((item, idx) => {
      const plat = (item.platform || 'douyin').toLowerCase();
      const platIcon = _SCH_ICONS[plat] || _SCH_ICONS.youtube;
      const score = item.viral_score || 95;

      return `
        <div class="sch-trending-item">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-100 dark:bg-slate-800">
                ${platIcon} <span>${_schEsc(plat)}</span>
              </span>
              <span class="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-1.5 py-0.5 rounded">
                ${score}% Viral
              </span>
              <span class="text-[10px] text-slate-400">${_schEsc(item.topic || 'Video Hot')}</span>
            </div>
            <button class="btn btn-primary text-[10px] px-2 py-0.5 font-semibold" onclick="schedulerApplyTrendingItem(${idx})">
              ＋ Thêm vào lịch
            </button>
          </div>

          <h4 class="font-bold text-xs text-slate-800 dark:text-slate-100 mt-1.5 leading-snug">${_schEsc(item.title)}</h4>
          ${item.video_concept ? `<p class="text-[11px] text-slate-600 dark:text-slate-400 mt-1 line-clamp-2">${_schEsc(item.video_concept)}</p>` : ''}
          ${item.viral_reason ? `<div class="text-[10px] text-amber-600 dark:text-amber-400 mt-1">Lý do hot: ${_schEsc(item.viral_reason)}</div>` : ''}

          <div class="flex items-center justify-between text-[10px] text-slate-400 mt-2 pt-1.5 border-t border-slate-100 dark:border-slate-800">
            <span class="truncate max-w-[260px] text-blue-500">${_schEsc(item.suggested_hashtags || '')}</span>
            ${(item.video_url || item.sample_url) ? `<a href="${_schEsc(item.video_url || item.sample_url)}" target="_blank" class="hover:underline text-blue-500 font-medium">Xem video trực tiếp ↗</a>` : ''}
          </div>
        </div>
      `;
    }).join('') +
    `</div>`;
};

window.schedulerApplyTrendingItem = function(index) {
  const item = _schTrendingItems[index];
  if (!item) return;

  const urlBox = document.getElementById('sch-urls');
  const hashtagsBox = document.getElementById('sch-hashtags');

  // Set the direct video link into url textarea
  const targetUrl = (item.video_url || item.sample_url || '').trim();
  if (!targetUrl) {
    if (typeof toast === 'function') toast('Không tìm thấy đường link video hợp lệ', 'warning');
    return;
  }

  if (urlBox) {
    const cur = urlBox.value.trim();
    urlBox.value = cur ? `${cur}\n${targetUrl}` : targetUrl;
  }
  if (hashtagsBox && item.suggested_hashtags) {
    hashtagsBox.value = item.suggested_hashtags;
  }

  // Switch to schedule tab
  schedulerSwitchMainTab('schedule');
  schedulerUpdateBatchPreview();

  if (typeof toast === 'function') {
    toast(`Đã thêm video "${item.title.slice(0, 30)}..." vào danh sách đăng!`, 'success');
  }
};

window.schedulerApplyAllTrending = function() {
  if (!_schTrendingItems.length) return;

  const urlBox = document.getElementById('sch-urls');
  const validUrls = _schTrendingItems
    .map(item => (item.video_url || item.sample_url || '').trim())
    .filter(Boolean);

  if (!validUrls.length) {
    if (typeof toast === 'function') toast('Chưa có đường link video nào sẵn sàng', 'warning');
    return;
  }

  if (urlBox) {
    urlBox.value = validUrls.join('\n');
  }

  schedulerSwitchMainTab('schedule');
  schedulerUpdateBatchPreview();

  if (typeof toast === 'function') {
    toast(`Đã thêm ${validUrls.length} video trực tiếp vào danh sách!`, 'success');
  }
};

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('sch-urls')?.addEventListener('input', schedulerUpdateBatchPreview);
  document.getElementById('sch-time')?.addEventListener('change', schedulerUpdateBatchPreview);
  schedulerLoad();
});

function schedulerProcessingConfig(presetName) {
  const config = collectProfileProcessConfig(presetName ? _schProfiles[presetName] : null);
  // Do not reuse a previous video's source or AI analysis in the schedule.
  for (const key of ['video_path', 'video_url', 'ai_video_analysis', 'ai_video_analysis_text']) delete config[key];
  if (config.frame_title_auto) config.frame_title = '';
  config.skip_ass_review = true;
  config.capcut_auto_open = false;
  return config;
}

let _schRefreshPending = false;
setInterval(async () => {
  if (_schRefreshPending || document.hidden || !document.getElementById('page-scheduler')?.classList.contains('active')) return;
  _schRefreshPending = true;
  try { await schedulerLoad(); } finally { _schRefreshPending = false; }
}, 5000);

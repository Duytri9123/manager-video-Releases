let _schItems = [];
let _schProfiles = {};
const _schLabels = {
  draft: 'Bản nháp',
  planned: 'Đã lên lịch',
  processing: 'Đang xử lý',
  ready: 'Sẵn sàng',
  publishing: 'Đang đăng',
  published: 'Đã đăng',
  failed: 'Lỗi'
};
const _schEsc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ── SWITCH TABS ── */
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
    if (lbl) lbl.textContent = 'Thời gian đăng';
  }
  schedulerUpdateBatchPreview();
};

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

/* ── PRESETS FROM TAB XỬ LÝ VIDEO ── */
async function schedulerLoadProfiles() {
  try {
    const res = await fetch('/api/process_profiles');
    const data = await res.json();
    if (data.ok && data.profiles) {
      _schProfiles = data.profiles;
      const sel = document.getElementById('sch-preset');
      if (sel) {
        sel.innerHTML = '<option value="">-- Mặc định (Tùy biến nhanh) --</option>' +
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

  // Reflect settings in form
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

/* ── ACCOUNTS MANAGEMENT ── */
function schedulerAccounts() {
  const platform = document.getElementById('sch-platform')?.value || 'youtube';
  const sel = document.getElementById('sch-account');
  if (!sel) return;
  const rows = (window._accounts?.[platform] || []);
  sel.innerHTML = '<option value="">Chọn sau / Chưa gán</option>' + rows.map(a =>
    `<option value="${_schEsc(a.id)}" data-name="${_schEsc(a.channel_title || a.name || a.email || a.id)}">${_schEsc(a.channel_title || a.name || a.email || a.id)}</option>`
  ).join('');
}

/* ── LIVE PREVIEW BATCH SCHEDULE ── */
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
    previewEl.innerHTML = `⏱️ <b>${count} video</b> sẽ được tự động xếp vào các khung giờ vàng <b>11:30 trưa</b> và <b>19:30 tối</b> (khoảng ${(count / 2).toFixed(0)} ngày) tính từ ${startDate.toLocaleDateString('vi-VN')}.`;
  } else {
    const hours = parseFloat(rule) || 24;
    const endDate = new Date(startDate.getTime() + (count - 1) * hours * 3600000);
    previewEl.innerHTML = `⏱️ <b>${count} video</b> sẽ cách nhau <b>${hours} giờ</b>, hoàn tất chuỗi đăng vào <b>${endDate.toLocaleString('vi-VN')}</b>.`;
  }
};

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('sch-urls')?.addEventListener('input', schedulerUpdateBatchPreview);
  document.getElementById('sch-time')?.addEventListener('change', schedulerUpdateBatchPreview);
  schedulerLoadProfiles();
});

/* ── LOAD SCHEDULER DATA ── */
window.schedulerLoad = async function() {
  try {
    if (typeof window.loadAccounts === 'function') await window.loadAccounts();
    schedulerAccounts();
    await schedulerLoadProfiles();

    const status = document.getElementById('sch-filter')?.value || '';
    const [r, s] = await Promise.all([
      fetch('/api/scheduler/items' + (status ? '?status=' + encodeURIComponent(status) : '')),
      fetch('/api/scheduler/stats')
    ]);
    const data = await r.json(), stats = await s.json();
    _schItems = data.items || [];

    const keys = [
      ['planned', 'Đã lên lịch', 'text-blue-600'],
      ['processing', 'Đang xử lý', 'text-amber-500'],
      ['ready', 'Sẵn sàng', 'text-emerald-600'],
      ['published', 'Đã đăng', 'text-green-600'],
      ['failed', 'Lỗi', 'text-red-500']
    ];
    document.getElementById('sch-stats').innerHTML = keys.map(([k, l, color]) =>
      `<div class="sch-card sch-stat border border-slate-200 dark:border-slate-800">
        <span class="text-slate-500 text-xs">${l}</span>
        <b class="${color}">${stats.counts?.[k] || 0}</b>
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
      <div class="text-4xl mb-2">🗓️</div>
      <div class="font-medium text-sm">Chưa có bài đăng nào trong danh sách</div>
      <div class="text-xs text-slate-400 mt-1">Hãy dán link video hoặc chọn file ở cột bên trái để lên lịch</div>
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
    const isProcessing = x.status === 'processing' || x.status === 'publishing';

    return `<article class="sch-card sch-item status-${x.status}">
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="sch-badge-platform ${pClass}">${_schEsc(platform)}</span>
          <span class="sch-badge-status ${sClass}">${_schEsc(_schLabels[x.status] || x.status)}</span>
          ${x.preset_name ? `<span class="sch-meta-tag">⚙️ ${_schEsc(x.preset_name)}</span>` : ''}
          <span class="sch-meta-tag">▣ ${_schEsc(x.processing?.aspect_ratio || '9:16')}</span>
        </div>
        <div class="flex items-center gap-1.5">
          ${!isReady && !isProcessing ? `<button class="btn btn-secondary text-xs px-2.5 py-1 text-amber-600 font-semibold" title="Xử lý video ngay" onclick="schedulerProcessItem('${x.id}')">⚡ Xử lý ngay</button>` : ''}
          ${isReady && x.status !== 'published' && !isProcessing ? `<button class="btn btn-primary text-xs px-2.5 py-1 font-semibold" title="Xuất bản lên mạng xã hội" onclick="schedulerPublishItem('${x.id}')">🚀 Đăng ngay</button>` : ''}
          <button class="btn btn-secondary text-xs px-2 py-1" title="Chỉnh sửa chi tiết" onclick="schedulerEditModal('${x.id}')">✏️ Sửa</button>
          <button class="btn btn-secondary text-xs px-2 py-1 text-red-500 hover:text-red-700" title="Xóa khỏi lịch" onclick="schedulerDelete('${x.id}')">✕</button>
        </div>
      </div>

      <div>
        <h3 class="font-bold text-sm text-slate-800 dark:text-slate-100">${_schEsc(title)}</h3>
        ${x.source_url ? `<a href="${_schEsc(x.source_url)}" target="_blank" class="text-blue-500 hover:underline text-[11px] break-all block mt-0.5">🔗 ${_schEsc(x.source_url)}</a>` : ''}
        ${x.video_path ? `<div class="text-[11px] text-slate-500 dark:text-slate-400 mt-1 font-mono truncate">📁 File: ${_schEsc(x.video_path)}</div>` : ''}
      </div>

      ${(x.caption || x.hashtags) ? `<div class="sch-caption-preview">
        ${x.caption ? `<div>${_schEsc(x.caption)}</div>` : ''}
        ${x.hashtags ? `<div class="text-blue-600 dark:text-blue-400 font-semibold mt-1">${_schEsc(x.hashtags)}</div>` : ''}
      </div>` : ''}

      <div class="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 flex-wrap gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
        <div class="flex items-center gap-3 flex-wrap">
          <span>◷ <b>${x.scheduled_at ? _schEsc(new Date(x.scheduled_at).toLocaleString('vi-VN')) : 'Chưa định giờ'}</b></span>
          <span>◎ Kênh: <b>${_schEsc(x.account_name || 'Chưa gán')}</b></span>
          ${x.published_url ? `<a href="${_schEsc(x.published_url)}" target="_blank" class="text-emerald-600 font-bold hover:underline">Xem bài đã đăng ↗</a>` : ''}
        </div>
        ${x.error ? `<span class="text-red-500 font-medium text-[11px] truncate max-w-xs" title="${_schEsc(x.error)}">⚠️ Lỗi: ${_schEsc(x.error)}</span>` : ''}
      </div>

      <div class="sch-progress-bar">
        <i style="width:${currentPct}%; background:${x.status === 'failed' ? '#ef4444' : (x.status === 'published' ? '#10b981' : '#3b82f6')}"></i>
      </div>
    </article>`;
  }).join('');
};

/* ── ADD ITEMS ── */
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

  const platform = document.getElementById('sch-platform')?.value || 'youtube';
  const selAcc = document.getElementById('sch-account');
  const optAcc = selAcc?.options[selAcc.selectedIndex];
  const roundRobin = !!document.getElementById('sch-round-robin')?.checked;
  const platformAccounts = (window._accounts?.[platform] || []);

  const isBatch = document.getElementById('sch-mode-batch-btn')?.classList.contains('active');
  const batchRule = document.getElementById('sch-batch-rule')?.value || 'golden';
  const scheduledTime = document.getElementById('sch-time')?.value;

  const presetName = document.getElementById('sch-preset')?.value || '';
  const tone = document.getElementById('sch-tone')?.value || '';
  const hashtags = document.getElementById('sch-hashtags')?.value || '';

  const body = {
    urls,
    platform,
    account_id: selAcc?.value || '',
    account_name: optAcc?.dataset?.name || '',
    round_robin: roundRobin,
    accounts: platformAccounts,
    is_batch: isBatch,
    batch_mode: batchRule === 'golden' ? 'golden_hours' : 'interval',
    interval_hours: parseFloat(batchRule) || 24,
    scheduled_at: scheduledTime,
    preset_name: presetName,
    tone: tone,
    hashtags: hashtags,
    processing: {
      aspect_ratio: document.getElementById('sch-ratio')?.value || '9:16',
      subtitles: !!document.getElementById('sch-sub')?.checked,
      translate: !!document.getElementById('sch-translate')?.checked,
      voiceover: !!document.getElementById('sch-voice')?.checked,
      remove_watermark: !!document.getElementById('sch-watermark')?.checked
    }
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
    if (typeof toast === 'function') toast(`Đã thêm thành công ${d.count || d.ids?.length} bài vào lịch!`, 'success');
    schedulerLoad();
  } catch (e) {
    if (typeof toast === 'function') toast(e.message, 'error');
  }
};

/* ── TRIGGER PROCESS ── */
window.schedulerProcessItem = async function(id) {
  try {
    if (typeof toast === 'function') toast('Đang khởi động tiến trình xử lý video ngầm...', 'info');
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
    btn.textContent = 'Đang phân tích nội dung các link...';
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

    if (btn) btn.textContent = 'AI đang thiết kế tiêu đề & lập lịch...';

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

    const selAcc = document.getElementById('sch-account');
    const optAcc = selAcc?.options[selAcc.selectedIndex];
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
          platform: p.platform || document.getElementById('sch-platform')?.value || 'youtube',
          account_id: selAcc?.value || '',
          account_name: optAcc?.dataset?.name || '',
          scheduled_at: p.scheduled_at || '',
          preset_name: presetName,
          status: 'planned',
          processing: p.processing || { aspect_ratio: '9:16', subtitles: true, translate: true, remove_watermark: true },
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
      btn.textContent = '✦ Phân tích link & Lập lịch bằng AI';
    }
  }
};

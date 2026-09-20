/* ── accounts.js — Multi-account management for YouTube & Facebook ── */

window._accounts = { youtube: [], facebook: [] };
window._activeAccounts = { youtube: null, facebook: null };

/* ── Load accounts on page init ── */
async function loadAccounts() {
  try {
    const [ytRes, fbRes] = await Promise.all([
      fetch('/api/accounts/youtube').then(r => r.json()),
      fetch('/api/accounts/facebook').then(r => r.json()),
    ]);
    if (ytRes.ok) {
      window._accounts.youtube = ytRes.accounts || [];
      window._activeAccounts.youtube = ytRes.active_id;
    }
    if (fbRes.ok) {
      window._accounts.facebook = fbRes.accounts || [];
      window._activeAccounts.facebook = fbRes.active_id;
    }
    renderAccountSelectors();

    const needsRefresh = (window._accounts.youtube || []).some(
      a => !a.channel_title && !a.thumbnail
    );
    if (needsRefresh) {
      _refreshYouTubeChannelInfo();
    }
  } catch (e) {
    console.warn('Failed to load accounts:', e);
  }
}

/* ── Silently fetch real channel name from YouTube API and update registry ── */
async function _refreshYouTubeChannelInfo() {
  try {
    const res = await fetch('/api/accounts/youtube/refresh_info', { method: 'POST' });
    const data = await res.json();
    if (data.ok && data.account) {
      const idx = window._accounts.youtube.findIndex(a => a.id === data.account.id);
      if (idx >= 0) {
        window._accounts.youtube[idx] = data.account;
      } else {
        window._accounts.youtube = window._accounts.youtube.map(a =>
          (!a.channel_title && !a.thumbnail) ? data.account : a
        );
      }
      renderAccountSelectors();
    }
  } catch (e) {}
}

/* ── Render account selectors in publish page ── */
function renderAccountSelectors() {
  const ytSelect = document.getElementById('yt-account-select');
  if (ytSelect) {
    const accounts = window._accounts.youtube;
    if (accounts.length > 0) {
      ytSelect.innerHTML = accounts.map(a => 
        `<option value="${a.id}" ${a.id === window._activeAccounts.youtube ? 'selected' : ''}>
          ${a.channel_title || a.name || a.id}
        </option>`
      ).join('') + '<option value="__add__">➕ Thêm tài khoản...</option>';
      ytSelect.parentElement.style.display = '';
    } else {
      ytSelect.innerHTML = '<option value="">Chưa có tài khoản</option><option value="__add__">➕ Thêm tài khoản...</option>';
    }
  }

  const fbSelect = document.getElementById('fb-account-select');
  if (fbSelect) {
    const accounts = window._accounts.facebook;
    if (accounts.length > 0) {
      fbSelect.innerHTML = accounts.map(a =>
        `<option value="${a.id}" ${a.id === window._activeAccounts.facebook ? 'selected' : ''}>
          ${a.name || a.id}
        </option>`
      ).join('') + '<option value="__add__">➕ Thêm tài khoản...</option>';
      fbSelect.parentElement.style.display = '';
    } else {
      fbSelect.innerHTML = '<option value="">Chưa có tài khoản</option><option value="__add__">➕ Thêm tài khoản...</option>';
    }
  }

  renderAccountManagementPanel();
}

/* ── Account management panel ── */
function renderAccountManagementPanel() {
  const panel = document.getElementById('accounts-management-panel');
  if (!panel) return;

  const ytAccounts = window._accounts.youtube;
  const fbAccounts = window._accounts.facebook;

  let html = '';

  const ytSvg = '<svg class="w-3.5 h-3.5 text-rose-600 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>';
  const fbSvg = '<svg class="w-3.5 h-3.5 text-blue-600 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>';

  html += `<div class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-2 flex items-center">${ytSvg} YouTube (${ytAccounts.length})</div>`;
  if (ytAccounts.length === 0) {
    html += '<div class="text-xs text-slate-400 mb-3 pl-1">Chưa có tài khoản YouTube nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px">';
    for (const acc of ytAccounts) {
      const isActive = acc.id === window._activeAccounts.youtube;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:10px">
          ${acc.thumbnail ? `<img src="${acc.thumbnail}" style="width:28px;height:28px;border-radius:50%;object-fit:cover">` : `<div style="width:28px;height:28px;border-radius:50%;background:rgba(225,29,72,0.1);display:flex;align-items:center;justify-content:center">${ytSvg}</div>`}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.channel_title || acc.name || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${acc.channel_id || ''}</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' : 
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveYouTube('${acc.id}')">Chọn</button>`}
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeYouTubeAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  html += `<div class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-2 flex items-center pt-2 border-t border-slate-100 dark:border-slate-800">${fbSvg} Facebook (${fbAccounts.length})</div>`;
  if (fbAccounts.length === 0) {
    html += '<div class="text-xs text-slate-400 mb-2 pl-1">Chưa có tài khoản Facebook nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px">';
    for (const acc of fbAccounts) {
      const isActive = acc.id === window._activeAccounts.facebook;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:10px">
          ${acc.profile_pic ? `<img src="${acc.profile_pic}" style="width:28px;height:28px;border-radius:50%;object-fit:cover">` : `<div style="width:28px;height:28px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center">${fbSvg}</div>`}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.name || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${(acc.pages || []).length} trang</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' : 
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveFacebook('${acc.id}')">Chọn</button>`}
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeFacebookAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  panel.innerHTML = html;
}

/* ── YouTube account actions ── */
async function setActiveYouTube(accountId) {
  try {
    const res = await fetch('/api/accounts/youtube/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      window._activeAccounts.youtube = accountId;
      renderAccountSelectors();
      toast('✅ Đã chuyển tài khoản YouTube', 'success');
      if (typeof checkYouTubeAuth === 'function') checkYouTubeAuth();
    } else {
      toast('❌ ' + (data.error || 'Lỗi'), 'error');
    }
  } catch (e) {
    toast('❌ Lỗi: ' + e.message, 'error');
  }
}

async function removeYouTubeAccount(accountId) {
  if (!confirm('Xóa tài khoản YouTube này?')) return;
  try {
    const res = await fetch('/api/accounts/youtube/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Đã xóa tài khoản', 'success');
      loadAccounts();
    } else {
      toast('❌ ' + (data.error || 'Lỗi'), 'error');
    }
  } catch (e) {
    toast('❌ Lỗi: ' + e.message, 'error');
  }
}

/* ── Facebook account actions ── */
async function addFacebookAccount() {
  const token = prompt('Nhập Facebook User Access Token:');
  if (!token || !token.trim()) return;

  try {
    toast('🔄 Đang kết nối...', 'info');
    const res = await fetch('/api/accounts/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token.trim() })
    });
    const data = await res.json();
    if (data.ok) {
      toast(`✅ Đã thêm: ${data.account.name}`, 'success');
      loadAccounts();
    } else {
      toast('❌ ' + (data.error || 'Token không hợp lệ'), 'error');
    }
  } catch (e) {
    toast('❌ Lỗi: ' + e.message, 'error');
  }
}

async function setActiveFacebook(accountId) {
  try {
    const res = await fetch('/api/accounts/facebook/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      window._activeAccounts.facebook = accountId;
      renderAccountSelectors();
      toast('✅ Đã chuyển tài khoản Facebook', 'success');
    } else {
      toast('❌ ' + (data.error || 'Lỗi'), 'error');
    }
  } catch (e) {
    toast('❌ Lỗi: ' + e.message, 'error');
  }
}

async function removeFacebookAccount(accountId) {
  if (!confirm('Xóa tài khoản Facebook này?')) return;
  try {
    const res = await fetch('/api/accounts/facebook/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('✅ Đã xóa tài khoản', 'success');
      loadAccounts();
    } else {
      toast('❌ ' + (data.error || 'Lỗi'), 'error');
    }
  } catch (e) {
    toast('❌ Lỗi: ' + e.message, 'error');
  }
}

/* ── Migrate existing tokens ── */
async function migrateExistingAccounts() {
  try {
    await Promise.all([
      fetch('/api/accounts/youtube/migrate', { method: 'POST' }),
      fetch('/api/accounts/facebook/migrate', { method: 'POST' }),
    ]);
    await loadAccounts();
    toast('✅ Đã migrate tài khoản cũ', 'success');
  } catch (e) {}
}

/* ── Account selector change handler ── */
function onAccountSelectChange(platform, selectEl) {
  const value = selectEl.value;
  if (value === '__add__') {
    if (platform === 'youtube') {
      if (typeof checkYouTubeAuth === 'function') checkYouTubeAuth();
    } else if (platform === 'facebook') {
      addFacebookAccount();
    }
    selectEl.value = window._activeAccounts[platform] || '';
    return;
  }
  if (platform === 'youtube') setActiveYouTube(value);
  else if (platform === 'facebook') setActiveFacebook(value);
}

/* ── Hardware info display ── */
async function loadHardwareInfo() {
  const el = document.getElementById('hardware-info-display');
  if (!el) return;
  try {
    const res = await fetch('/api/hardware_info');
    const data = await res.json();
    if (data.ok) {
      const hw = data.hardware;
      const preset = hw.selected_preset;
      el.innerHTML = `
        <div class="flex flex-col gap-2.5">
          <div class="grid grid-cols-2 gap-2 text-[11px]">
            <div class="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <span class="text-slate-400 block text-[10px] font-semibold uppercase">CPU</span>
              <span class="font-semibold text-slate-700 dark:text-slate-200 truncate block" title="${hw.cpu_name || ''}">${hw.cpu_name || 'Unknown'} (${hw.cpu_cores}C/${hw.cpu_threads}T)</span>
            </div>
            <div class="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <span class="text-slate-400 block text-[10px] font-semibold uppercase">RAM</span>
              <span class="font-semibold text-slate-700 dark:text-slate-200 block">${hw.ram_gb} GB</span>
            </div>
            <div class="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <span class="text-slate-400 block text-[10px] font-semibold uppercase">GPU</span>
              <span class="font-semibold text-slate-700 dark:text-slate-200 truncate block">${hw.nvidia_gpu_name || (hw.has_intel_qsv ? 'Intel QSV' : hw.has_amd_amf ? 'AMD AMF' : 'Không có')}</span>
            </div>
            <div class="p-2 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
              <span class="text-slate-400 block text-[10px] font-semibold uppercase">Profile</span>
              <span class="font-semibold text-slate-700 dark:text-slate-200 block">${hw.machine_profile}</span>
            </div>
          </div>
          <div class="p-2.5 rounded-lg bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/40 text-[11px]">
            <div class="flex items-center justify-between gap-2">
              <span class="font-semibold text-indigo-700 dark:text-indigo-300 flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                FFmpeg: ${preset.video_codec} / ${preset.preset_name} / CRF ${preset.crf}
              </span>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold ${preset.hwaccel ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400' : 'bg-slate-200/80 text-slate-600 dark:bg-slate-800 dark:text-slate-400'}">
                ${preset.hwaccel ? `HW: ${preset.hwaccel}` : 'CPU Encoder'}
              </span>
            </div>
            <div class="text-[10px] text-slate-400 dark:text-slate-400 mt-1">${preset.description}</div>
          </div>
        </div>`;
    }
  } catch (e) {
    if (el) el.innerHTML = '<span class="text-xs text-muted">Không thể tải thông tin phần cứng</span>';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadAccounts();
  loadHardwareInfo();
});

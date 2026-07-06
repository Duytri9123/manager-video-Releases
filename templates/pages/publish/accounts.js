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

  html += `<div class="section-title mb-8">📺 YouTube (${ytAccounts.length})</div>`;
  if (ytAccounts.length === 0) {
    html += '<div class="text-xs text-muted mb-12">Chưa có tài khoản YouTube nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px">';
    for (const acc of ytAccounts) {
      const isActive = acc.id === window._activeAccounts.youtube;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:8px">
          ${acc.thumbnail ? `<img src="${acc.thumbnail}" style="width:28px;height:28px;border-radius:50%">` : '<span style="font-size:20px">📺</span>'}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.channel_title || acc.name || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${acc.channel_id || ''}</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px">Active</span>' : 
            `<button class="btn btn-secondary btn-sm" style="font-size:10px;padding:2px 8px" onclick="setActiveYouTube('${acc.id}')">Chọn</button>`}
          <button class="btn-icon text-red" style="font-size:14px" onclick="removeYouTubeAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  html += `<div class="section-title mb-8">📘 Facebook (${fbAccounts.length})</div>`;
  if (fbAccounts.length === 0) {
    html += '<div class="text-xs text-muted mb-12">Chưa có tài khoản Facebook nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px">';
    for (const acc of fbAccounts) {
      const isActive = acc.id === window._activeAccounts.facebook;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:8px">
          ${acc.profile_pic ? `<img src="${acc.profile_pic}" style="width:28px;height:28px;border-radius:50%">` : '<span style="font-size:20px">📘</span>'}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.name || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${(acc.pages || []).length} trang</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px">Active</span>' : 
            `<button class="btn btn-secondary btn-sm" style="font-size:10px;padding:2px 8px" onclick="setActiveFacebook('${acc.id}')">Chọn</button>`}
          <button class="btn-icon text-red" style="font-size:14px" onclick="removeFacebookAccount('${acc.id}')" title="Xóa">✕</button>
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
        <div style="font-size:11px;color:var(--text-muted);line-height:1.6">
          <div><b>CPU:</b> ${hw.cpu_name || 'Unknown'} (${hw.cpu_cores}C/${hw.cpu_threads}T)</div>
          <div><b>RAM:</b> ${hw.ram_gb} GB</div>
          <div><b>GPU:</b> ${hw.nvidia_gpu_name || (hw.has_intel_qsv ? 'Intel QSV' : hw.has_amd_amf ? 'AMD AMF' : 'Không có')}</div>
          <div><b>Profile:</b> ${hw.machine_profile}</div>
          <div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border)">
            <b>FFmpeg Preset:</b> ${preset.video_codec} / ${preset.preset_name} / CRF ${preset.crf}
            ${preset.hwaccel ? `(HW: ${preset.hwaccel})` : '(CPU)'}
          </div>
          <div style="font-size:10px;color:var(--text-muted);margin-top:2px">${preset.description}</div>
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

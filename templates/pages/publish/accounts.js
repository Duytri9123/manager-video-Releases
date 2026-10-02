/* ── accounts.js — Multi-account management for YouTube, TikTok, Facebook & Douyin ── */

window._accounts = { youtube: [], facebook: [], tiktok: [], douyin: [] };
window._activeAccounts = { youtube: null, facebook: null, tiktok: null, douyin: null };

/* ── Load accounts on page init ── */
async function loadAccounts() {
  try {
    const [ytRes, fbRes, ttRes, dyRes] = await Promise.all([
      fetch('/api/accounts/youtube').then(r => r.json()).catch(() => ({})),
      fetch('/api/accounts/facebook').then(r => r.json()).catch(() => ({})),
      fetch('/api/accounts/tiktok').then(r => r.json()).catch(() => ({})),
      fetch('/api/accounts/douyin').then(r => r.json()).catch(() => ({})),
    ]);
    if (ytRes.ok) {
      window._accounts.youtube = ytRes.accounts || [];
      window._activeAccounts.youtube = ytRes.active_id;
    }
    if (fbRes.ok) {
      window._accounts.facebook = fbRes.accounts || [];
      window._activeAccounts.facebook = fbRes.active_id;
    }
    if (ttRes.ok) {
      window._accounts.tiktok = ttRes.accounts || [];
      window._activeAccounts.tiktok = ttRes.active_id;
    }
    if (dyRes.ok) {
      window._accounts.douyin = dyRes.accounts || [];
      window._activeAccounts.douyin = dyRes.active_id;
    }
    renderAccountSelectors();
    refreshSavedAccountSessions();

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
window.loadAccounts = loadAccounts;

async function refreshSavedAccountSessions() {
  try {
    const data = await fetch('/api/accounts/saved_sessions').then(r => r.json());
    if (!data.ok) return;
    document.querySelectorAll('[data-session-platform][data-session-account]').forEach(el => {
      const info = data.sessions?.[el.dataset.sessionPlatform]?.[el.dataset.sessionAccount];
      el.textContent = info?.saved ? `Phiên đã lưu${info.method ? ' · ' + info.method : ''}` : 'Chưa lưu phiên';
      el.style.color = info?.saved ? '#059669' : '#d97706';
    });
  } catch (_) {}
}

async function loginFacebookBrowserAccount(accountId) {
  try {
    const response = await fetch('/api/facebook_browser/login', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({account_id:accountId})});
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Không mở được trình duyệt');
    toast('Đăng nhập Facebook trong cửa sổ vừa mở.', 'info');
    const timer = setInterval(async () => {
      try {
        const state = await fetch('/api/facebook_browser/status?session_id=' + encodeURIComponent(data.session_id)).then(r => r.json());
        if (!state.done) return;
        clearInterval(timer);
        if (state.status === 'ready') { toast('Đã lưu phiên Facebook', 'success'); refreshSavedAccountSessions(); }
        else toast(state.error || 'Không lưu được phiên Facebook', 'error');
      } catch (_) { clearInterval(timer); }
    }, 2000);
  } catch (error) { toast(error.message, 'error'); }
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

/* ── Render account selectors in publish page & cookies page ── */
function renderAccountSelectors() {
  // 1. YouTube selectors
  const ytSelects = [
    document.getElementById('yt-account-select'),
    document.getElementById('p-yt-account-select'),
    document.getElementById('step1-yt-account-select')
  ].filter(Boolean);
  ytSelects.forEach(select => {
    const accounts = window._accounts.youtube || [];
    if (accounts.length > 0) {
      select.innerHTML = accounts.map(a =>
        `<option value="${a.id}" ${a.id === window._activeAccounts.youtube ? 'selected' : ''}>
          ${a.channel_title || a.name || a.id}
        </option>`
      ).join('') + '<option value="__add__">+ Thêm tài khoản mới...</option>';
      if (select.parentElement) select.parentElement.style.display = '';
    } else {
      select.innerHTML = '<option value="">Chưa có tài khoản</option><option value="__add__">+ Thêm tài khoản mới...</option>';
    }
  });

  // 2. Facebook selectors
  const fbSelects = [
    document.getElementById('fb-account-select'),
    document.getElementById('p-fb-account-select'),
    document.getElementById('pub-fb-account-select'),
    document.getElementById('step1-fb-account-select')
  ].filter(Boolean);
  fbSelects.forEach(select => {
    const accounts = window._accounts.facebook || [];
    if (accounts.length > 0) {
      select.innerHTML = accounts.map(a =>
        `<option value="${a.id}" ${a.id === window._activeAccounts.facebook ? 'selected' : ''}>
          ${a.name || a.id}
        </option>`
      ).join('') + '<option value="__add__">+ Thêm tài khoản mới...</option>';
      if (select.parentElement) select.parentElement.style.display = '';
    } else {
      select.innerHTML = '<option value="">Chưa có tài khoản</option><option value="__add__">+ Thêm tài khoản mới...</option>';
    }
  });

  // 3. TikTok selectors
  const ttSelects = [
    document.getElementById('tt-account-select'),
    document.getElementById('p-tt-account-select'),
    document.getElementById('cfg-tt-account-select'),
    document.getElementById('cookies-tt-account-select')
  ].filter(Boolean);
  ttSelects.forEach(select => {
    const accounts = window._accounts.tiktok || [];
    if (accounts.length > 0) {
      select.innerHTML = accounts.map(a =>
        `<option value="${a.id}" ${a.id === window._activeAccounts.tiktok ? 'selected' : ''}>
          ${a.name || a.username || a.id}
        </option>`
      ).join('') + '<option value="__add__">+ Thêm tài khoản TikTok mới...</option>';
      if (select.parentElement && select.id !== 'cookies-tt-account-select') select.parentElement.style.display = '';
    } else {
      select.innerHTML = '<option value="">Chưa có tài khoản TikTok</option><option value="__add__">+ Thêm tài khoản TikTok mới...</option>';
    }
  });

  // 4. Douyin selectors
  const dySelects = [
    document.getElementById('cfg-dy-account-select'),
    document.getElementById('cookies-dy-account-select')
  ].filter(Boolean);
  dySelects.forEach(select => {
    const accounts = window._accounts.douyin || [];
    if (accounts.length > 0) {
      select.innerHTML = accounts.map(a =>
        `<option value="${a.id}" ${a.id === window._activeAccounts.douyin ? 'selected' : ''}>
          ${a.name || a.nickname || a.id} (${a.cookie_count || 0} cookies)
        </option>`
      ).join('') + '<option value="__add__">+ Thêm tài khoản Douyin mới...</option>';
    } else {
      select.innerHTML = '<option value="">Chưa có hồ sơ Douyin</option><option value="__add__">+ Thêm tài khoản Douyin mới...</option>';
    }
  });

  renderAccountManagementPanel();
}
window.renderAccountSelectors = renderAccountSelectors;

/* ── Account management panel ── */
function renderAccountManagementPanel() {
  const panel = document.getElementById('accounts-management-panel');
  if (!panel) return;

  const ytAccounts = window._accounts.youtube || [];
  const fbAccounts = window._accounts.facebook || [];
  const ttAccounts = window._accounts.tiktok || [];
  const dyAccounts = window._accounts.douyin || [];

  let html = '';

  const ytSvg = '<svg class="w-3.5 h-3.5 text-rose-600 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>';
  const ttSvg = '<svg class="w-3.5 h-3.5 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.24 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>';
  const fbSvg = '<svg class="w-3.5 h-3.5 text-blue-600 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg>';
  const dySvg = '<svg class="w-3.5 h-3.5 text-rose-500 inline-block align-middle mr-1.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';

  // Section 1: YouTube
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
            <div data-session-platform="youtube" data-session-account="${acc.id}" style="font-size:10px;color:var(--text-muted)">Đang kiểm tra phiên...</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' :
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveYouTube('${acc.id}')">Chọn</button>`}
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeYouTubeAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  // Section 2: TikTok
  html += `<div class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-2 flex items-center pt-2 border-t border-slate-100 dark:border-slate-800">${ttSvg} TikTok (${ttAccounts.length})</div>`;
  if (ttAccounts.length === 0) {
    html += '<div class="text-xs text-slate-400 mb-3 pl-1">Chưa có tài khoản TikTok nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px">';
    for (const acc of ttAccounts) {
      const isActive = acc.id === window._activeAccounts.tiktok;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:10px">
          ${acc.avatar ? `<img src="${acc.avatar}" style="width:28px;height:28px;border-radius:50%;object-fit:cover">` : `<div style="width:28px;height:28px;border-radius:50%;background:rgba(15,23,42,0.1);display:flex;align-items:center;justify-content:center">${ttSvg}</div>`}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.name || acc.username || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${acc.username ? '@' + acc.username : 'Hồ sơ trình duyệt độc lập'}</div>
            <div data-session-platform="tiktok" data-session-account="${acc.id}" style="font-size:10px;color:var(--text-muted)">Đang kiểm tra phiên...</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' :
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveTikTok('${acc.id}')">Chọn</button>`}
          <button class="btn btn-secondary btn-sm" onclick="loginCookieAccount('tiktok', '${acc.id}')">Đăng nhập / Lưu phiên</button>
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeTikTokAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  // Section 3: Facebook
  html += `<div class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-2 flex items-center pt-2 border-t border-slate-100 dark:border-slate-800">${fbSvg} Facebook (${fbAccounts.length})</div>`;
  if (fbAccounts.length === 0) {
    html += '<div class="text-xs text-slate-400 mb-3 pl-1">Chưa có tài khoản Facebook nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:14px">';
    for (const acc of fbAccounts) {
      const isActive = acc.id === window._activeAccounts.facebook;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:10px">
          ${acc.profile_pic ? `<img src="${acc.profile_pic}" style="width:28px;height:28px;border-radius:50%;object-fit:cover">` : `<div style="width:28px;height:28px;border-radius:50%;background:rgba(37,99,235,0.1);display:flex;align-items:center;justify-content:center">${fbSvg}</div>`}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.name || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${(acc.pages || []).length} trang</div>
            <div data-session-platform="facebook" data-session-account="${acc.id}" style="font-size:10px;color:var(--text-muted)">Đang kiểm tra phiên...</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' :
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveFacebook('${acc.id}')">Chọn</button>`}
          <button class="btn btn-secondary btn-sm" onclick="loginFacebookBrowserAccount('${acc.id}')">Đăng nhập / Lưu phiên</button>
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeFacebookAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  // Section 4: Douyin
  html += `<div class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-2 flex items-center pt-2 border-t border-slate-100 dark:border-slate-800">${dySvg} Douyin (${dyAccounts.length})</div>`;
  if (dyAccounts.length === 0) {
    html += '<div class="text-xs text-slate-400 mb-2 pl-1">Chưa có tài khoản Douyin nào.</div>';
  } else {
    html += '<div style="display:flex;flex-direction:column;gap:6px">';
    for (const acc of dyAccounts) {
      const isActive = acc.id === window._activeAccounts.douyin;
      html += `
        <div class="account-item ${isActive ? 'active' : ''}" style="display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg3);border:1px solid ${isActive ? 'var(--accent)' : 'var(--border)'};border-radius:10px">
          ${acc.avatar ? `<img src="${acc.avatar}" style="width:28px;height:28px;border-radius:50%;object-fit:cover">` : `<div style="width:28px;height:28px;border-radius:50%;background:rgba(244,63,94,0.1);display:flex;align-items:center;justify-content:center">${dySvg}</div>`}
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;font-weight:600;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${acc.name || acc.nickname || acc.id}</div>
            <div style="font-size:10px;color:var(--text-muted)">${acc.cookie_count || 0} cookie lưu trữ ${acc.nickname ? '· ' + acc.nickname : ''}</div>
            <div data-session-platform="douyin" data-session-account="${acc.id}" style="font-size:10px;color:var(--text-muted)">Đang kiểm tra phiên...</div>
          </div>
          ${isActive ? '<span class="badge badge-green" style="font-size:10px;padding:2px 8px;border-radius:6px;background:rgba(16,185,129,0.1);color:#10b981;font-weight:600">Active</span>' :
            `<button class="btn btn-secondary btn-sm" style="font-size:11px;padding:3px 10px;height:26px;cursor:pointer" onclick="setActiveDouyin('${acc.id}')">Chọn</button>`}
          <button class="btn btn-secondary btn-sm" onclick="loginCookieAccount('douyin', '${acc.id}')">Đăng nhập / Lưu phiên</button>
          <button class="btn-icon text-red cursor-pointer" style="width:24px;height:24px;border:none;background:transparent;color:#ef4444;font-size:12px;display:flex;align-items:center;justify-content:center" onclick="removeDouyinAccount('${acc.id}')" title="Xóa">✕</button>
        </div>`;
    }
    html += '</div>';
  }

  panel.innerHTML = html;
  refreshSavedAccountSessions();
}
window.renderAccountManagementPanel = renderAccountManagementPanel;

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
      toast('Đã chuyển sang tài khoản YouTube đang chọn', 'success');
      if (typeof checkYouTubeAuth === 'function') checkYouTubeAuth();
    } else {
      toast(data.error || 'Lỗi chuyển tài khoản YouTube', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.setActiveYouTube = setActiveYouTube;

async function removeYouTubeAccount(accountId) {
  if (!confirm('Xóa tài khoản YouTube này khỏi hệ thống?')) return;
  try {
    const res = await fetch('/api/accounts/youtube/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã xóa tài khoản YouTube', 'success');
      loadAccounts();
    } else {
      toast(data.error || 'Lỗi khi xóa tài khoản', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.removeYouTubeAccount = removeYouTubeAccount;

/* ── Facebook account actions ── */
async function addFacebookAccount() {
  const modal = document.getElementById('add-facebook-account-modal');
  if (!modal) return;
  document.getElementById('add-fb-account-error').textContent = '';
  document.getElementById('add-fb-user-token').value = '';
  document.getElementById('add-fb-app-secret').value = '';
  try {
    const res = await fetch('/api/facebook/app_credentials');
    const data = await res.json();
    document.getElementById('add-fb-app-id').value = data.app_id || '';
    modal.dataset.savedAppId = data.configured ? (data.app_id || '') : '';
    document.getElementById('add-fb-app-secret').required = !data.configured;
  } catch (_) {
    modal.dataset.savedAppId = '';
    document.getElementById('add-fb-app-secret').required = true;
  }
  modal.style.display = 'flex';
  document.getElementById('add-fb-app-id').focus();
}
window.addFacebookAccount = addFacebookAccount;

function closeFacebookAccountModal() {
  document.getElementById('add-facebook-account-modal').style.display = 'none';
}
window.closeFacebookAccountModal = closeFacebookAccountModal;

async function submitFacebookAccount(event) {
  event.preventDefault();
  const app_id = document.getElementById('add-fb-app-id').value.trim();
  const app_secret = document.getElementById('add-fb-app-secret').value.trim();
  const token = document.getElementById('add-fb-user-token').value.trim();
  const error = document.getElementById('add-fb-account-error');
  const button = document.getElementById('add-fb-account-submit');
  if (app_id !== document.getElementById('add-facebook-account-modal').dataset.savedAppId && !app_secret) {
    error.textContent = 'Nhập App Secret cho App ID mới.';
    return;
  }
  error.textContent = '';
  button.disabled = true;

  try {
    const credentialsRes = await fetch('/api/facebook/app_credentials', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id, app_secret })
    });
    const credentials = await credentialsRes.json();
    if (!credentialsRes.ok || !credentials.ok) throw new Error(credentials.error || 'Không lưu được App ID / App Secret');
    const res = await fetch('/api/accounts/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || 'Token Facebook không hợp lệ');
    closeFacebookAccountModal();
    toast(`Đã thêm tài khoản Facebook: ${data.account.name}`, 'success');
    loadAccounts();
  } catch (e) {
    error.textContent = e.message;
  } finally {
    button.disabled = false;
  }
}
window.submitFacebookAccount = submitFacebookAccount;

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
      toast('Đã chuyển sang tài khoản Facebook đang chọn', 'success');
    } else {
      toast(data.error || 'Lỗi chuyển tài khoản Facebook', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.setActiveFacebook = setActiveFacebook;

async function removeFacebookAccount(accountId) {
  if (!confirm('Xóa tài khoản Facebook này khỏi hệ thống?')) return;
  try {
    const res = await fetch('/api/accounts/facebook/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã xóa tài khoản Facebook', 'success');
      loadAccounts();
    } else {
      toast(data.error || 'Lỗi khi xóa tài khoản', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.removeFacebookAccount = removeFacebookAccount;

/* ── TikTok account actions ── */
async function addTikTokAccount() {
  const accountName = prompt('Nhập tên gợi nhớ cho tài khoản TikTok mới (hoặc để trống để tự động):', 'Kênh TikTok ' + ((window._accounts.tiktok || []).length + 1));
  if (accountName === null) return;

  try {
    toast('Đang khởi tạo trình duyệt đăng nhập TikTok...', 'info');
    const res = await fetch('/api/accounts/tiktok/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_name: (accountName || '').trim() })
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || 'Không mở được trình duyệt TikTok', 'error');
      return;
    }

    toast('Cửa sổ TikTok Studio đã mở. Hãy đăng nhập tài khoản trên cửa sổ đó. Hệ thống sẽ tự lưu phiên!', 'info');
    _pollTikTokLoginStatus(data.session_id);
  } catch (e) {
    toast('Lỗi mở đăng nhập TikTok: ' + e.message, 'error');
  }
}
window.addTikTokAccount = addTikTokAccount;

function _pollTikTokLoginStatus(sid) {
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts++;
    if (attempts > 300) { // 10 minutes max
      clearInterval(timer);
      toast('Hết thời gian chờ đăng nhập TikTok', 'warning');
      return;
    }
    try {
      const res = await fetch('/api/tiktok/prepare_status?session_id=' + encodeURIComponent(sid));
      const st = await res.json();
      if (!st.ok) {
        clearInterval(timer);
        return;
      }
      if (st.status === 'ready' || st.done) {
        clearInterval(timer);
        if (st.status === 'error') {
          toast(st.error || 'Lỗi trong quá trình đăng nhập TikTok', 'error');
        } else {
          toast('Đăng nhập TikTok thành công và đã lưu tài khoản!', 'success');
          loadAccounts();
        }
      }
    } catch (e) {
      // transient network poll error
    }
  }, 2000);
}

async function setActiveTikTok(accountId) {
  try {
    const res = await fetch('/api/accounts/tiktok/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      window._activeAccounts.tiktok = accountId;
      renderAccountSelectors();
      toast('Đã kích hoạt tài khoản TikTok đã chọn', 'success');
    } else {
      toast(data.error || 'Lỗi chọn tài khoản TikTok', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.setActiveTikTok = setActiveTikTok;

async function removeTikTokAccount(accountId) {
  if (!confirm('Xóa tài khoản TikTok này và hồ sơ phiên đăng nhập tương ứng?')) return;
  try {
    const res = await fetch('/api/accounts/tiktok/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã xóa tài khoản TikTok', 'success');
      loadAccounts();
    } else {
      toast(data.error || 'Lỗi khi xóa tài khoản TikTok', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.removeTikTokAccount = removeTikTokAccount;

/* ── Douyin account actions ── */
async function setActiveDouyin(accountId) {
  try {
    const res = await fetch('/api/accounts/douyin/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      window._activeAccounts.douyin = accountId;
      renderAccountSelectors();
      toast('Đã chọn hồ sơ Douyin và đồng bộ Cookie ra toàn hệ thống', 'success');
      // If on cookies page, reload form fields
      if (typeof loadCookieFields === 'function') {
        loadCookieFields();
      }
    } else {
      toast(data.error || 'Lỗi kích hoạt tài khoản Douyin', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.setActiveDouyin = setActiveDouyin;

async function removeDouyinAccount(accountId) {
  if (!confirm('Xóa hồ sơ cookie Douyin này?')) return;
  try {
    const res = await fetch('/api/accounts/douyin/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã xóa tài khoản Douyin', 'success');
      loadAccounts();
      if (typeof loadCookieFields === 'function') {
        loadCookieFields();
      }
    } else {
      toast(data.error || 'Lỗi khi xóa tài khoản Douyin', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.removeDouyinAccount = removeDouyinAccount;

/* ── Modal thêm tài khoản Douyin ── */
function openAddDouyinModal() {
  let modal = document.getElementById('add-douyin-account-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'add-douyin-account-modal';
    modal.className = 'sch-modal-backdrop';
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.55);backdrop-filter:blur(3px);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;';
    modal.innerHTML = `
      <div class="sch-modal-box" style="max-width:540px;width:100%;background:var(--bg2,#ffffff);border:1px solid var(--border);border-radius:14px;padding:22px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.25);">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border)">
          <div style="font-weight:700;font-size:14px;color:var(--text);display:flex;align-items:center;gap:8px">
            <svg class="w-4 h-4 text-rose-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
            Thêm tài khoản Douyin
          </div>
          <button type="button" class="btn-icon" style="background:transparent;border:none;font-size:16px;cursor:pointer;color:var(--text-muted)" onclick="closeAddDouyinModal()">✕</button>
        </div>

        <div style="display:flex;gap:8px;margin-bottom:16px;border-bottom:1px solid var(--border);padding-bottom:10px">
          <button type="button" id="tab-btn-dy-browser" class="btn btn-sm btn-primary" onclick="_switchDouyinModalTab('browser')" style="font-size:12px">
            Đăng nhập qua trình duyệt (QR/SMS)
          </button>
          <button type="button" id="tab-btn-dy-paste" class="btn btn-sm btn-secondary" onclick="_switchDouyinModalTab('paste')" style="font-size:12px">
            Dán Cookie thủ công / JSON
          </button>
        </div>

        <!-- Panel 1: Browser -->
        <div id="panel-dy-browser" style="display:block">
          <div class="field" style="margin-bottom:12px">
            <label style="font-size:11px;font-weight:600;display:block;margin-bottom:4px">Tên gợi nhớ tài khoản</label>
            <input type="text" id="dy-modal-name-browser" placeholder="VD: Douyin Phụ 1, Kênh Phim..." style="width:100%;height:34px;font-size:12px">
          </div>
          <div style="font-size:11px;color:var(--text-muted);background:var(--bg3);padding:10px;border-radius:8px;margin-bottom:14px">
            Trình duyệt sẽ mở trang Douyin. Bạn chỉ cần quét mã QR hoặc đăng nhập bằng SĐT. Hệ thống sẽ tự nhận diện đăng nhập thành công, bắt toàn bộ Cookie và lưu vào danh sách tài khoản.
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px">
            <button type="button" class="btn btn-secondary btn-sm" onclick="closeAddDouyinModal()">Hủy</button>
            <button type="button" class="btn btn-primary btn-sm" onclick="_submitDouyinBrowserLogin(this)">Mở trình duyệt đăng nhập</button>
          </div>
        </div>

        <!-- Panel 2: Paste -->
        <div id="panel-dy-paste" style="display:none">
          <div class="field" style="margin-bottom:12px">
            <label style="font-size:11px;font-weight:600;display:block;margin-bottom:4px">Tên gợi nhớ tài khoản</label>
            <input type="text" id="dy-modal-name-paste" placeholder="VD: Douyin VIP 1" style="width:100%;height:34px;font-size:12px">
          </div>
          <div class="field" style="margin-bottom:12px">
            <label style="font-size:11px;font-weight:600;display:block;margin-bottom:4px">Chuỗi Cookie thô hoặc JSON</label>
            <textarea id="dy-modal-cookie-paste" rows="5" placeholder="ttwid=xxx; odin_tt=xxx; passport_csrf_token=xxx...&#10;Hoặc dán JSON { &quot;ttwid&quot;: &quot;...&quot; }" style="width:100%;font-size:11px;font-family:monospace"></textarea>
          </div>
          <div style="display:flex;justify-content:flex-end;gap:8px">
            <button type="button" class="btn btn-secondary btn-sm" onclick="closeAddDouyinModal()">Hủy</button>
            <button type="button" class="btn btn-primary btn-sm" onclick="_submitDouyinPasteCookie(this)">Lưu tài khoản</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  modal.style.display = 'flex';
}
window.openAddDouyinModal = openAddDouyinModal;

function closeAddDouyinModal() {
  const modal = document.getElementById('add-douyin-account-modal');
  if (modal) modal.style.display = 'none';
}
window.closeAddDouyinModal = closeAddDouyinModal;

function _switchDouyinModalTab(tab) {
  const pBrowser = document.getElementById('panel-dy-browser');
  const pPaste = document.getElementById('panel-dy-paste');
  const btnB = document.getElementById('tab-btn-dy-browser');
  const btnP = document.getElementById('tab-btn-dy-paste');
  if (tab === 'browser') {
    if (pBrowser) pBrowser.style.display = 'block';
    if (pPaste) pPaste.style.display = 'none';
    if (btnB) { btnB.className = 'btn btn-sm btn-primary'; }
    if (btnP) { btnP.className = 'btn btn-sm btn-secondary'; }
  } else {
    if (pBrowser) pBrowser.style.display = 'none';
    if (pPaste) pPaste.style.display = 'block';
    if (btnB) { btnB.className = 'btn btn-sm btn-secondary'; }
    if (btnP) { btnP.className = 'btn btn-sm btn-primary'; }
  }
}
window._switchDouyinModalTab = _switchDouyinModalTab;

async function _submitDouyinBrowserLogin(btn) {
  const name = document.getElementById('dy-modal-name-browser')?.value?.trim() || 'Douyin ' + ((window._accounts.douyin || []).length + 1);
  closeAddDouyinModal();
  toast('Đang khởi động trình duyệt Douyin...', 'info');

  try {
    const res = await fetch('/api/accounts/douyin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_name: name })
    });
    const data = await res.json();
    if (!data.ok) {
      toast(data.error || 'Lỗi mở trình duyệt Douyin', 'error');
      return;
    }
    toast('Trình duyệt Douyin đã mở. Quét mã QR hoặc đăng nhập để hệ thống tự lưu Cookie!', 'info');
    _pollDouyinLoginStatus(data.session_id);
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window._submitDouyinBrowserLogin = _submitDouyinBrowserLogin;

function _pollDouyinLoginStatus(sid) {
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts++;
    if (attempts > 300) {
      clearInterval(timer);
      toast('Hết thời gian chờ đăng nhập Douyin', 'warning');
      return;
    }
    try {
      const res = await fetch('/api/tiktok/prepare_status?session_id=' + encodeURIComponent(sid));
      const st = await res.json();
      if (!st.ok) {
        clearInterval(timer);
        return;
      }
      if (st.status === 'ready' || st.done) {
        clearInterval(timer);
        if (st.status === 'error') {
          toast(st.error || 'Lỗi đăng nhập Douyin', 'error');
        } else {
          toast('Đăng nhập và lưu Cookie Douyin thành công!', 'success');
          loadAccounts();
          if (typeof loadCookieFields === 'function') loadCookieFields();
        }
      }
    } catch (e) {}
  }, 2000);
}

async function _submitDouyinPasteCookie(btn) {
  const name = document.getElementById('dy-modal-name-paste')?.value?.trim() || 'Douyin ' + ((window._accounts.douyin || []).length + 1);
  const raw = document.getElementById('dy-modal-cookie-paste')?.value?.trim() || '';
  if (!raw) {
    toast('Vui lòng nhập chuỗi cookie hoặc JSON', 'warning');
    return;
  }

  try {
    const res = await fetch('/api/accounts/douyin/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name, raw: raw })
    });
    const data = await res.json();
    if (data.ok) {
      closeAddDouyinModal();
      toast('Đã thêm và kích hoạt tài khoản Douyin: ' + data.account.name, 'success');
      loadAccounts();
      if (typeof loadCookieFields === 'function') loadCookieFields();
    } else {
      toast(data.error || 'Cookie không hợp lệ', 'error');
    }
  } catch (e) {
    toast('Lỗi lưu tài khoản: ' + e.message, 'error');
  }
}
window._submitDouyinPasteCookie = _submitDouyinPasteCookie;

/* ── Lưu form hiện tại thành hồ sơ mới ── */
async function saveAsNewDouyinAccount() {
  const name = prompt('Nhập tên hồ sơ Douyin mới:', 'Douyin ' + ((window._accounts.douyin || []).length + 1));
  if (!name || !name.trim()) return;

  const cookies = {};
  if (typeof CK_FIELDS !== 'undefined') {
    CK_FIELDS.forEach(f => {
      const el = document.getElementById('ck-' + f);
      if (el && el.value.trim()) cookies[f] = el.value.trim();
    });
  }

  if (Object.keys(cookies).length === 0) {
    toast('Chưa có thông tin cookie nào trong các ô nhập', 'warning');
    return;
  }

  try {
    const res = await fetch('/api/accounts/douyin/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), cookies: cookies })
    });
    const data = await res.json();
    if (data.ok) {
      toast('Đã lưu thành hồ sơ Douyin mới: ' + data.account.name, 'success');
      loadAccounts();
    } else {
      toast(data.error || 'Lỗi lưu hồ sơ', 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  }
}
window.saveAsNewDouyinAccount = saveAsNewDouyinAccount;

/* ── Migrate all platform accounts ── */
async function migrateExistingAccounts() {
  try {
    toast('Đang đồng bộ và chuẩn hóa hồ sơ tài khoản...', 'info');
    const res = await fetch('/api/accounts/migrate', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      await loadAccounts();
      toast('Đã đồng bộ toàn bộ tài khoản YouTube, Facebook, TikTok và Douyin', 'success');
    } else {
      toast('Lỗi đồng bộ: ' + (data.error || ''), 'error');
    }
  } catch (e) {
    toast('Lỗi đồng bộ: ' + e.message, 'error');
  }
}
window.migrateExistingAccounts = migrateExistingAccounts;

/* ── Select change handlers ── */
function onAccountSelectChange(platform, selectEl) {
  const value = selectEl.value;
  if (value === '__add__') {
    if (platform === 'youtube') {
      if (typeof youtubeLogin === 'function') youtubeLogin();
    } else if (platform === 'facebook') {
      addFacebookAccount();
    } else if (platform === 'tiktok') {
      addTikTokAccount();
    } else if (platform === 'douyin') {
      openAddDouyinModal();
    }
    selectEl.value = window._activeAccounts[platform] || '';
    return;
  }
  if (platform === 'youtube') setActiveYouTube(value);
  else if (platform === 'facebook') setActiveFacebook(value);
  else if (platform === 'tiktok') setActiveTikTok(value);
  else if (platform === 'douyin') setActiveDouyin(value);
}
window.onAccountSelectChange = onAccountSelectChange;

function onCookiesDouyinAccountChange(val) {
  if (val === '__add__') {
    openAddDouyinModal();
    const sel = document.getElementById('cookies-dy-account-select');
    if (sel) sel.value = window._activeAccounts.douyin || '';
    return;
  }
  if (val) setActiveDouyin(val);
}
window.onCookiesDouyinAccountChange = onCookiesDouyinAccountChange;

function onCookiesTikTokAccountChange(val) {
  if (val === '__add__') {
    addTikTokAccount();
    const sel = document.getElementById('cookies-tt-account-select');
    if (sel) sel.value = window._activeAccounts.tiktok || '';
    return;
  }
  if (val) setActiveTikTok(val);
}
window.onCookiesTikTokAccountChange = onCookiesTikTokAccountChange;

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

window.loginCookieAccount = async function(platform, accountId) {
  if (!accountId || accountId === '__add__') {
    if (platform === 'tiktok') return addTikTokAccount();
    return openAddDouyinModal();
  }
  const account = (window._accounts[platform] || []).find(a => a.id === accountId);
  try {
    const response = await fetch(`/api/accounts/${platform}/login`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({account_id: accountId, account_name: account?.name || ''})
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Không mở được đăng nhập');
    toast('Đăng nhập trong cửa sổ trình duyệt. Phiên được lưu riêng cho tài khoản đã chọn.', 'info');
    if (platform === 'tiktok') _pollTikTokLoginStatus(result.session_id);
    else _pollDouyinLoginStatus(result.session_id);
  } catch (error) { toast(error.message, 'error'); }
};

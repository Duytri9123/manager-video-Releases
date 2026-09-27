/* ── Cookies page ────────────────────────────────────────────────────────── */
const CK_FIELDS = ['ttwid','odin_tt','passport_csrf_token','s_v_web_id','__ac_nonce','__ac_signature','UIFID','bd_ticket_guard_client_web_domain','msToken'];

async function loadCookieMode() {
  const data = await API.get('/api/cookie_mode');
  const isCustom = data?.mode === 'custom';
  const toggle = document.getElementById('ck-mode-toggle');
  const badge = document.getElementById('ck-mode-badge');
  const desc = document.getElementById('ck-mode-desc');
  const wrap = document.getElementById('ck-custom-wrap');
  if (toggle) toggle.checked = isCustom;
  if (badge) { badge.setAttribute('data-i18n', isCustom ? 'lbl_cookie_custom' : 'lbl_cookie_default'); badge.textContent = t(isCustom ? 'lbl_cookie_custom' : 'lbl_cookie_default'); }
  if (desc) { desc.setAttribute('data-i18n', isCustom ? 'lbl_cookie_custom_desc' : 'lbl_cookie_default_desc'); desc.textContent = t(isCustom ? 'lbl_cookie_custom_desc' : 'lbl_cookie_default_desc'); }
  if (wrap) wrap.style.display = isCustom ? '' : 'none';
}

async function loadCookieFields() {
  const cfg = await API.get('/api/config');
  const ck = cfg?.cookies || {};
  CK_FIELDS.forEach(f => {
    const el = document.getElementById('ck-' + f);
    if (el) el.value = ck[f] || '';
  });

  // Load TikTok, YouTube & Facebook cookie settings
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  const ytdlp = cfg?.ytdlp || {};
  const cookieFiles = ytdlp.cookie_files || {};
  const cookieContents = ytdlp.cookie_contents || {};
  set('ck-standalone-tiktok-browser', ytdlp.cookies_from_browser_tiktok || '');
  set('ck-standalone-tiktok-file', cookieFiles.tiktok || '');
  set('ck-standalone-tiktok-content', cookieContents.tiktok || '');
  set('ck-yt-browser', ytdlp.cookies_from_browser || '');
  set('ck-yt-file', cookieFiles.youtube || '');
  set('ck-yt-content', cookieContents.youtube || '');
  set('ck-fb-file', cookieFiles.facebook || '');
  set('ck-fb-content', cookieContents.facebook || '');
  set('ck-fb-profile', cfg?.facebook_profile || '.facebook_profile');

  if (typeof loadAccounts === 'function') {
    loadAccounts();
  }
}

function switchCookieTab(platform) {
  document.querySelectorAll('.cookie-tab-panel').forEach(p => {
    const on = p.getAttribute('data-cookie-platform') === platform;
    p.style.display = on ? 'block' : 'none';
  });
  document.querySelectorAll('.cookie-tab').forEach(el => {
    el.classList.toggle('active', el.getAttribute('data-cookie-platform') === platform);
  });
}
window.switchCookieTab = switchCookieTab;

async function savePlatformConfig(platform) {
  if (platform === 'douyin') {
    await saveCookies();
    return;
  }
  const payload = {};
  if (platform === 'tiktok') {
    const browser = document.getElementById('ck-standalone-tiktok-browser')?.value || document.getElementById('ck-tiktok-browser')?.value || '';
    const filepath = document.getElementById('ck-standalone-tiktok-file')?.value?.trim() || document.getElementById('ck-tiktok-file')?.value?.trim() || '';
    const content = document.getElementById('ck-standalone-tiktok-content')?.value || document.getElementById('ck-tiktok-content')?.value || '';
    payload.ytdlp = {
      cookies_from_browser_tiktok: browser,
      cookie_files: {
        tiktok: filepath
      },
      cookie_contents: {
        tiktok: content
      }
    };
  } else if (platform === 'youtube') {
    const browser = document.getElementById('ck-yt-browser')?.value || '';
    const filepath = document.getElementById('ck-yt-file')?.value?.trim() || '';
    const content = document.getElementById('ck-yt-content')?.value || '';
    payload.ytdlp = {
      cookies_from_browser: browser,
      cookie_files: {
        youtube: filepath
      },
      cookie_contents: {
        youtube: content
      }
    };
  } else if (platform === 'facebook') {
    const filepath = document.getElementById('ck-fb-file')?.value?.trim() || '';
    const profile = document.getElementById('ck-fb-profile')?.value?.trim() || '.facebook_profile';
    const content = document.getElementById('ck-fb-content')?.value || '';
    payload.ytdlp = {
      cookie_files: {
        facebook: filepath
      },
      cookie_contents: {
        facebook: content
      }
    };
    payload.facebook_profile = profile;
  }
  
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) toast('Đã lưu cấu hình cookie ' + platform + '!', 'success');
    else toast('Lỗi lưu cấu hình: ' + (data.error || ''), 'error');
  } catch (e) {
    toast('Lỗi lưu cấu hình: ' + e.message, 'error');
  }
}
window.savePlatformConfig = savePlatformConfig;

async function onCookieModeChange() {
  const isCustom = document.getElementById('ck-mode-toggle')?.checked;
  await API.post('/api/cookie_mode', { mode: isCustom ? 'custom' : 'default' });
  loadCookieMode();
}

async function saveCookies() {
  const data = {};
  CK_FIELDS.forEach(f => {
    const el = document.getElementById('ck-' + f);
    if (el) data[f] = el.value.trim();
  });
  await API.post('/api/cookies', data);
  if (window._activeAccounts?.douyin) {
    try {
      const activeAcc = (window._accounts?.douyin || []).find(a => a.id === window._activeAccounts.douyin);
      const accName = activeAcc ? activeAcc.name : 'Douyin Mặc Định';
      await fetch('/api/accounts/douyin/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: window._activeAccounts.douyin, name: accName, cookies: data })
      });
      if (typeof loadAccounts === 'function') loadAccounts();
    } catch (_) {}
  }
  toast(t('toast_cookies_saved') || 'Đã lưu Cookie Douyin thành công!', 'success');
}

async function validateCookie() {
  const data = {};
  CK_FIELDS.forEach(f => {
    const el = document.getElementById('ck-' + f);
    if (el) data[f] = el.value.trim();
  });
  const res = await API.post('/api/validate_cookie', data);
  const status = document.getElementById('ck-status');
  if (status) {
    status.innerHTML = res?.ok
      ? '<span class="dot dot-green"></span><span>' + (res?.reason || 'Hợp lệ') + (res?.has_ms_token ? ' · có msToken' : ' · msToken sẽ tự tạo') + '</span>'
      : '<span class="dot dot-red"></span><span>' + (res?.reason || 'Không hợp lệ') + '</span>';
  }
}

async function parseCookie() {
  const raw = document.getElementById('ck-raw')?.value || '';
  if (!raw.trim()) return;
  const parsed = await API.post('/api/parse_cookie', { raw });
  CK_FIELDS.forEach(f => {
    const el = document.getElementById('ck-' + f);
    if (el && parsed[f]) el.value = parsed[f];
  });
}

let douyinCaptureTimer;
async function autoFetch() {
  try {
    const data = await (await fetch('/api/auto_fetch_cookie', {method: 'POST'})).json();
    if (!data.ok) throw new Error(data.error || 'Không mở được trình duyệt');
    let button = document.getElementById('douyin-finish-login');
    if (!button) {
      button = document.createElement('button');
      button.id = 'douyin-finish-login';
      button.className = 'btn btn-primary btn-sm';
      button.textContent = 'Đã đăng nhập / xác minh xong — Lưu cookie';
      button.type = 'button';
      document.querySelector('[onclick="autoFetch()"]')?.after(button);
    }
    button.disabled = false;
    button.onclick = async () => {
      try {
        const result = await (await fetch('/api/auto_fetch_cookie/finish', {method: 'POST'})).json();
        if (!result.ok) throw new Error(result.error);
        button.disabled = true;
      } catch (e) { toast(e.message, 'error'); }
    };
    toast('Đăng nhập và giải CAPTCHA trong trình duyệt. Giữ cửa sổ mở, quay lại bấm Lưu cookie. Thời gian chờ: 10 phút.', 'info');
    clearInterval(douyinCaptureTimer);
    douyinCaptureTimer = setInterval(async () => {
      try {
        const status = await (await fetch('/api/auto_fetch_cookie/status')).json();
        if (status.state === 'waiting') return;
        clearInterval(douyinCaptureTimer);
        button.remove();
        toast(status.state === 'saved' ? 'Đã lưu cookie. Có thể tìm và tải video Douyin.' : (status.error || 'Phiên đăng nhập đã kết thúc.'), status.state === 'saved' ? 'success' : 'error');
        if (status.state === 'saved') {
          if (typeof loadCookieFields === 'function') await loadCookieFields();
          if (typeof loadCookieMode === 'function') await loadCookieMode();
        }
      } catch (e) {
        clearInterval(douyinCaptureTimer);
        toast('Không đọc được trạng thái đăng nhập: ' + e.message, 'error');
      }
    }, 2000);
  } catch (e) { toast(e.message, 'error'); }
}

async function openYoutubeLoginCookie(btn) {
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Đang chờ đóng trình duyệt...';

  try {
    toast('Trình duyệt đang mở. Vui lòng đăng nhập YouTube và ĐÓNG trình duyệt khi hoàn tất!', 'info');
    const res = await fetch('/api/youtube/login_cookie', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      toast('Đã lấy và lưu Cookie YouTube thành công!', 'success');
      const contentEl = document.getElementById('ck-yt-content');
      if (contentEl) {
        contentEl.value = data.cookie;
      }
    } else {
      toast('Lỗi lấy cookie: ' + (data.error || 'Vui lòng thử lại'), 'error');
    }
  } catch (e) {
    toast('Lỗi: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}
window.openYoutubeLoginCookie = openYoutubeLoginCookie;

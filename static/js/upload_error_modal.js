/* ════════════════════════════════════════════════════════════════
   upload_error_modal.js — Modal xử lý lỗi upload chung cho YouTube,
   Facebook, TikTok. Khi upload lỗi, hiển thị modal và đợi user chọn:
     - "retry"  : thử lại
     - "skip"   : bỏ qua video hiện tại, tiếp tục video kế tiếp
     - "cancel" : huỷ toàn bộ pipeline upload

   Dùng: const action = await showUploadErrorModal({
           platform: 'facebook',
           title:    'Xử lý 1.mp4',
           error:    'Token Facebook đã hết hạn',
           errorCode: 190,
           suggestions: ['Vào tab Đăng video → 🔄 Gia hạn token'],
           tokenError: true,
         });
═══════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const PLATFORM_LABELS = {
    youtube:  { name: 'YouTube',  icon: '🎬', color: '#ff0000' },
    facebook: { name: 'Facebook', icon: '📘', color: '#1877f2' },
    tiktok:   { name: 'TikTok',   icon: '🎵', color: '#000000' },
  };

  /* Build modal once, reuse */
  function _ensureModal() {
    if (document.getElementById('upload-err-modal')) return;

    const modal = document.createElement('div');
    modal.id = 'upload-err-modal';
    modal.style.cssText = `
      display:none;position:fixed;inset:0;z-index:99999;
      background:rgba(0,0,0,.55);backdrop-filter:blur(2px);
      align-items:center;justify-content:center;padding:20px;
      font-family:inherit;
    `;
    modal.innerHTML = `
      <div style="background:var(--bg-secondary,#fff);border-radius:14px;
                  max-width:560px;width:100%;max-height:88vh;overflow:auto;
                  box-shadow:0 12px 40px rgba(0,0,0,.4);
                  border:1px solid var(--border,#e5e7eb)">
        <div id="upload-err-header" style="padding:18px 22px 12px;
             border-bottom:1px solid var(--border,#e5e7eb);
             display:flex;align-items:center;gap:12px">
          <div id="upload-err-icon" style="font-size:32px;flex-shrink:0">⚠️</div>
          <div style="flex:1;min-width:0">
            <div id="upload-err-platform" style="font-size:11px;font-weight:600;
                 color:var(--text-muted,#6b7280);text-transform:uppercase;letter-spacing:.5px">PLATFORM</div>
            <div id="upload-err-title" style="font-size:16px;font-weight:700;
                 color:var(--text,#111);margin-top:2px">Upload thất bại</div>
          </div>
        </div>

        <div style="padding:18px 22px">
          <!-- Video name -->
          <div id="upload-err-video" style="font-size:12px;color:var(--text-muted,#6b7280);
               margin-bottom:10px;word-break:break-word">📹 video.mp4</div>

          <!-- Error message -->
          <div id="upload-err-msg" style="background:#fef2f2;border:1px solid #fecaca;
               color:#991b1b;padding:10px 12px;border-radius:8px;font-size:13px;
               margin-bottom:12px;word-break:break-word;line-height:1.5"></div>

          <!-- Error code badge -->
          <div id="upload-err-code" style="display:none;font-size:11px;
               color:var(--text-muted,#6b7280);margin-bottom:12px;
               font-family:ui-monospace,monospace"></div>

          <!-- Suggestions -->
          <div id="upload-err-suggestions" style="display:none;
               background:#fffbeb;border:1px solid #fde68a;border-radius:8px;
               padding:10px 12px;font-size:12px;color:#92400e;
               margin-bottom:12px">
            <div style="font-weight:600;margin-bottom:4px">💡 Cách khắc phục:</div>
            <ul id="upload-err-suggestions-list" style="margin:0;padding-left:18px;line-height:1.6"></ul>
          </div>

          <!-- Token error specific actions -->
          <div id="upload-err-token-actions" style="display:none;
               background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;
               padding:10px 12px;margin-bottom:12px">
            <div style="font-size:12px;color:#1e40af;margin-bottom:8px">
              <b>🔑 Token đã hết hạn</b> — bạn có thể thử gia hạn ngay:
            </div>
            <button id="upload-err-refresh-token-btn" type="button"
                    style="padding:6px 12px;font-size:12px;border-radius:6px;
                           border:none;background:#1877f2;color:white;cursor:pointer">
              🔄 Gia hạn token
            </button>
            <span id="upload-err-refresh-status" style="margin-left:8px;font-size:11px;color:#1e40af"></span>
          </div>

          <!-- Diagnose details (collapsible) -->
          <details id="upload-err-diag-wrap" style="display:none;margin-top:8px;font-size:11px">
            <summary style="cursor:pointer;color:var(--text-muted,#6b7280);
                            user-select:none">🔍 Chi tiết kỹ thuật</summary>
            <pre id="upload-err-diag" style="margin-top:6px;padding:8px;
                 background:#f3f4f6;border-radius:6px;font-family:ui-monospace,monospace;
                 white-space:pre-wrap;word-break:break-all;font-size:10px;
                 color:#374151;max-height:120px;overflow:auto"></pre>
          </details>
        </div>

        <div style="padding:12px 22px;border-top:1px solid var(--border,#e5e7eb);
             display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;
             background:var(--bg,#f9fafb)">
          <button id="upload-err-cancel-btn" type="button"
                  style="padding:8px 16px;font-size:13px;border-radius:8px;
                         border:1px solid var(--border,#d1d5db);
                         background:white;color:#374151;cursor:pointer;font-weight:500">
            ❌ Huỷ toàn bộ
          </button>
          <button id="upload-err-skip-btn" type="button"
                  style="padding:8px 16px;font-size:13px;border-radius:8px;
                         border:1px solid #fbbf24;background:#fef3c7;
                         color:#92400e;cursor:pointer;font-weight:500">
            ⏭ Bỏ qua video này
          </button>
          <button id="upload-err-retry-btn" type="button"
                  style="padding:8px 16px;font-size:13px;border-radius:8px;
                         border:none;background:#3b82f6;color:white;
                         cursor:pointer;font-weight:600">
            🔄 Thử lại
          </button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    // Wire up buttons
    document.getElementById('upload-err-retry-btn')
      .addEventListener('click', () => _resolveModal('retry'));
    document.getElementById('upload-err-skip-btn')
      .addEventListener('click', () => _resolveModal('skip'));
    document.getElementById('upload-err-cancel-btn')
      .addEventListener('click', () => _resolveModal('cancel'));
    document.getElementById('upload-err-refresh-token-btn')
      .addEventListener('click', _refreshFbToken);

    // Close on backdrop click → treat as cancel
    modal.addEventListener('click', (e) => {
      if (e.target === modal) _resolveModal('cancel');
    });
  }

  function _resolveModal(action) {
    const modal = document.getElementById('upload-err-modal');
    if (modal) modal.style.display = 'none';
    if (window._uploadErrModalResolve) {
      window._uploadErrModalResolve(action);
      window._uploadErrModalResolve = null;
    }
  }

  async function _refreshFbToken() {
    const btn = document.getElementById('upload-err-refresh-token-btn');
    const statusEl = document.getElementById('upload-err-refresh-status');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang gia hạn...'; }
    if (statusEl) statusEl.textContent = '';
    try {
      const res = await fetch('/api/facebook/refresh_token', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        if (statusEl) {
          statusEl.textContent = `✅ ${data.message || 'Đã gia hạn'}`;
          statusEl.style.color = '#0d7a4e';
        }
        if (btn) { btn.textContent = '✅ Đã gia hạn'; btn.style.background = '#10b981'; }
      } else if (data.need_reauth) {
        if (statusEl) {
          statusEl.textContent = '❌ Token hết hạn hoàn toàn — cần nhập token mới';
          statusEl.style.color = '#c0392b';
        }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Gia hạn token'; }
      } else {
        if (statusEl) {
          statusEl.textContent = '❌ ' + (data.error || 'Gia hạn thất bại');
          statusEl.style.color = '#c0392b';
        }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Gia hạn token'; }
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = '❌ ' + e.message;
        statusEl.style.color = '#c0392b';
      }
      if (btn) { btn.disabled = false; btn.textContent = '🔄 Gia hạn token'; }
    }
  }

  /**
   * Show upload error modal and wait for user action.
   * @param {Object} opts
   * @param {string} opts.platform   - 'youtube' | 'facebook' | 'tiktok'
   * @param {string} opts.video      - Video file name or path
   * @param {string} opts.error      - Error message to display
   * @param {string|number} [opts.errorCode] - Error code (e.g. 190, 401, 'TOKEN_EXPIRED')
   * @param {string[]} [opts.suggestions] - Hints for fixing the issue
   * @param {boolean} [opts.tokenError] - If true, show token-related actions
   * @param {string}  [opts.diagnostic] - Raw technical detail for debugging
   * @returns {Promise<'retry'|'skip'|'cancel'>}
   */
  window.showUploadErrorModal = function (opts) {
    _ensureModal();
    return new Promise(resolve => {
      const platform = (opts.platform || 'youtube').toLowerCase();
      const meta = PLATFORM_LABELS[platform] || PLATFORM_LABELS.youtube;

      // Header
      const iconEl = document.getElementById('upload-err-icon');
      if (iconEl) iconEl.textContent = meta.icon;
      const platEl = document.getElementById('upload-err-platform');
      if (platEl) {
        platEl.textContent = meta.name + ' — Upload thất bại';
        platEl.style.color = meta.color;
      }
      const titleEl = document.getElementById('upload-err-title');
      if (titleEl) titleEl.textContent = opts.title || 'Đã xảy ra lỗi khi upload';

      // Video name
      const videoEl = document.getElementById('upload-err-video');
      if (videoEl) {
        if (opts.video) {
          videoEl.style.display = 'block';
          videoEl.textContent = '📹 ' + opts.video;
        } else {
          videoEl.style.display = 'none';
        }
      }

      // Error message
      const msgEl = document.getElementById('upload-err-msg');
      if (msgEl) msgEl.textContent = opts.error || 'Lỗi không xác định';

      // Error code
      const codeEl = document.getElementById('upload-err-code');
      if (codeEl) {
        if (opts.errorCode !== undefined && opts.errorCode !== '' && opts.errorCode !== null) {
          codeEl.style.display = 'block';
          codeEl.textContent = `Mã lỗi: ${opts.errorCode}`;
        } else {
          codeEl.style.display = 'none';
        }
      }

      // Suggestions
      const sugWrap = document.getElementById('upload-err-suggestions');
      const sugList = document.getElementById('upload-err-suggestions-list');
      const suggestions = opts.suggestions || _autoSuggestions(opts);
      if (sugWrap && sugList) {
        if (suggestions && suggestions.length) {
          sugWrap.style.display = 'block';
          sugList.innerHTML = suggestions.map(s => `<li>${s}</li>`).join('');
        } else {
          sugWrap.style.display = 'none';
        }
      }

      // Token actions
      const tokenWrap = document.getElementById('upload-err-token-actions');
      if (tokenWrap) {
        const showToken = !!opts.tokenError && platform === 'facebook';
        tokenWrap.style.display = showToken ? 'block' : 'none';
        if (showToken) {
          const btn = document.getElementById('upload-err-refresh-token-btn');
          if (btn) { btn.disabled = false; btn.textContent = '🔄 Gia hạn token'; btn.style.background = '#1877f2'; }
          const statusEl = document.getElementById('upload-err-refresh-status');
          if (statusEl) statusEl.textContent = '';
        }
      }

      // Diagnostic
      const diagWrap = document.getElementById('upload-err-diag-wrap');
      const diagEl = document.getElementById('upload-err-diag');
      if (diagWrap && diagEl) {
        if (opts.diagnostic) {
          diagWrap.style.display = 'block';
          diagEl.textContent = typeof opts.diagnostic === 'string'
            ? opts.diagnostic
            : JSON.stringify(opts.diagnostic, null, 2);
        } else {
          diagWrap.style.display = 'none';
        }
      }

      // Show modal and store resolver
      const modal = document.getElementById('upload-err-modal');
      if (modal) modal.style.display = 'flex';
      window._uploadErrModalResolve = resolve;
    });
  };

  /* Auto-derive suggestions based on the error pattern */
  function _autoSuggestions(opts) {
    const err = String(opts.error || '').toLowerCase();
    const platform = (opts.platform || '').toLowerCase();
    const out = [];

    if (opts.tokenError || /token|expired|oauth|190|463|unauthorized|401/i.test(err)) {
      if (platform === 'facebook') {
        out.push('Bấm <b>"🔄 Gia hạn token"</b> ở trên để làm mới token tự động.');
        out.push('Nếu thất bại: vào <a href="https://developers.facebook.com/tools/explorer/" target="_blank">Graph API Explorer</a> lấy User Token mới rồi kết nối lại.');
      } else if (platform === 'youtube') {
        out.push('Vào tab Đăng video → bấm <b>"Đăng nhập YouTube"</b> để xác thực lại.');
      } else if (platform === 'tiktok') {
        out.push('Đăng nhập lại TikTok Studio trong tab Đăng video.');
      }
    }
    if (/file|not found|no such file|missing/i.test(err)) {
      out.push('Kiểm tra lại đường dẫn file — file có thể đã bị xoá hoặc di chuyển.');
      out.push('Chạy lại bước "Xử lý video" để tạo lại file.');
    }
    if (/network|connection|10054|10053|reset|forcibly/i.test(err)) {
      out.push('Kiểm tra kết nối Internet và thử lại.');
      out.push('Nếu lỗi liên tục: token có thể đã hết hạn — hãy gia hạn token.');
    }
    if (/permission|pages_manage_posts|publish/i.test(err)) {
      out.push('Token thiếu quyền — sinh token mới với scopes: <code>pages_manage_posts</code>, <code>pages_read_engagement</code>, <code>pages_show_list</code>.');
    }
    if (/quota|rate.?limit|too many/i.test(err)) {
      out.push('Đã vượt giới hạn API — chờ vài phút rồi thử lại.');
    }
    if (/duration|too long|too short|invalid format/i.test(err)) {
      out.push('Kiểm tra định dạng video: Reel cần 9:16, 3-90 giây, MP4.');
    }
    return out;
  }

  /* Helper: parse common upload error info from a server response object */
  window.parseUploadError = function (resultData, platform) {
    const errMsg = resultData.errorMsg || resultData.error || resultData.log || 'Lỗi không xác định';
    const isTokenErr = !!(resultData.tokenError || resultData.token_error
                       || /token|expired|oauth|190|463|401/i.test(errMsg));
    // Try to extract error code from message like "[code=190, subcode=463]"
    let code = '';
    const m = String(errMsg).match(/code\s*[=:]\s*(\w+)/i);
    if (m) code = m[1];
    return {
      platform,
      error: errMsg,
      errorCode: code,
      tokenError: isTokenErr,
    };
  };
})();

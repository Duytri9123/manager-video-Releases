/* ── proc_publish.js ───────────────────────────────────────────
   Auto-publish panel inside Process page.
   - AI auto-fills title/description/hashtags from ASS content on review continue
   - Enforces: YouTube title ≤ 100, TikTok ≤ 5 hashtags
   - Auto-uploads to enabled platforms after video processing completes
   - Batch schedule: spreads N videos over N days (or custom interval)
   ────────────────────────────────────────────────────────────── */

window._pPubEnabled = { youtube: true, tiktok: true, facebook: true };
window._pPubActive  = 'youtube';
// Last AI-generated content (cached so it can be re-applied on next video in batch)
window._pPubAIResult = null;
// Batch schedule counter (how many videos already scheduled in this batch)
window._pBschedCounter = 0;

const _P_PLATFORMS = ['youtube', 'tiktok', 'facebook'];
const _P_TAB_ID = { youtube: 'yt', tiktok: 'tt', facebook: 'fb' };

/* ════════════════════════════════════════════════════════════════
   TAB SWITCHING + PLATFORM TOGGLE
════════════════════════════════════════════════════════════════ */
function pPubSwitchTab(platform) {
  if (!_P_PLATFORMS.includes(platform)) return;
  if (!window._pPubEnabled[platform]) return;
  window._pPubActive = platform;
  _P_PLATFORMS.forEach(p => {
    const tab   = document.getElementById('p-tab-' + _P_TAB_ID[p]);
    const panel = document.getElementById('p-panel-' + p);
    if (tab)   tab.classList.toggle('active', p === platform);
    if (panel) panel.style.display = (p === platform) ? 'block' : 'none';
  });
}

function pPubTogglePlatform(platform) {
  if (!_P_PLATFORMS.includes(platform)) return;
  const tid    = _P_TAB_ID[platform];
  const toggle = document.getElementById('p-toggle-' + tid);
  const tab    = document.getElementById('p-tab-' + tid);

  window._pPubEnabled[platform] = !window._pPubEnabled[platform];
  const on = window._pPubEnabled[platform];

  if (toggle) {
    toggle.textContent = on ? '✓' : '✕';
    toggle.style.background = on ? 'var(--accent)' : 'var(--text-muted)';
  }
  if (tab) tab.style.opacity = on ? '1' : '0.4';

  if (on) {
    pPubSwitchTab(platform);
  } else if (window._pPubActive === platform) {
    const next = _P_PLATFORMS.find(p => window._pPubEnabled[p] && p !== platform);
    if (next) pPubSwitchTab(next);
  }
}

/* ════════════════════════════════════════════════════════════════
   LIMITS: YouTube title ≤ 100, TikTok ≤ 5 hashtags
════════════════════════════════════════════════════════════════ */
function _pYtTruncateTitle(t) {
  if (!t) return '';
  t = String(t).trim();
  return t.length > 100 ? t.slice(0, 97) + '...' : t;
}

function _pTtLimitHashtags(str, max = 5) {
  if (!str) return '';
  // Split by whitespace, extract #xxx tokens, keep first max
  const tokens = String(str).split(/\s+/).filter(Boolean);
  const tags = [];
  const others = [];
  for (const tok of tokens) {
    if (tok.startsWith('#')) {
      if (tags.length < max) tags.push(tok);
    } else {
      others.push(tok);
    }
  }
  // Preserve non-hashtag prefix words, then truncated hashtags
  return [...others, ...tags].join(' ').trim();
}

function _pCountHashtags(str) {
  if (!str) return 0;
  return (String(str).match(/#[^\s#]+/g) || []).length;
}

/* ════════════════════════════════════════════════════════════════
   AI ANALYZE & AUTO-FILL from ASS content
════════════════════════════════════════════════════════════════ */
function _pExtractPlainFromAss(text) {
  if (!text) return '';
  const parts = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith('Dialogue:')) continue;
    const cols = line.split(',');
    if (cols.length < 10) continue;
    const t = cols.slice(9).join(',')
      .replace(/\{[^}]*\}/g, '')
      .replace(/\\N/g, ' ')
      .replace(/\\n/g, ' ')
      .trim();
    if (t) parts.push(t);
  }
  return parts.join(' ');
}

async function pPubAnalyzeFromAss(assContent) {
  // Only run if auto-publish is enabled and ASS content is non-empty
  if (!document.getElementById('p-autopub-enabled')?.checked) return null;
  const plain = _pExtractPlainFromAss(assContent || '');
  if (!plain) {
    _appendProcLog?.('⚠ ASS trống — bỏ qua AI phân tích', 'warning');
    return null;
  }

  const provider = document.getElementById('p-pub-ai-provider')?.value || 'deepseek';
  _appendProcLog?.('🤖 AI đang phân tích nội dung ASS để tạo tiêu đề/hashtag...', 'info');

  try {
    const res = await fetch('/api/analyze_video_content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: plain.slice(0, 3000), provider })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI thất bại');

    const info = data.result || {};
    pPubApplyAIResult(info);
    _appendProcLog?.('✅ AI đã tạo nội dung đăng video', 'success');
    return info;
  } catch (e) {
    _appendProcLog?.('❌ AI phân tích thất bại: ' + e.message, 'error');
    return null;
  }
}

function pPubApplyAIResult(info) {
  if (!info) return;
  window._pPubAIResult = info;

  // ── YouTube ──
  const yt = info.youtube || {};
  const ytTitle = _pYtTruncateTitle(yt.title || '');
  const fill = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };
  const arr  = v => Array.isArray(v) ? v.join(', ') : (v || '');

  fill('p-yt-title', ytTitle);
  fill('p-yt-desc',  yt.description || '');
  fill('p-yt-tags',  arr(yt.tags));
  _pUpdateYtTitleCount();

  // ── TikTok ──
  const tt = info.tiktok || {};
  fill('p-tt-title', tt.caption || '');
  fill('p-tt-desc',  tt.description || '');
  const ttTags = Array.isArray(tt.hashtags) ? tt.hashtags.join(' ') : (tt.hashtags || '');
  fill('p-tt-tags',  _pTtLimitHashtags(ttTags, 5));
  _pUpdateTtTagsCount();

  // ── Facebook ──
  const fb = info.facebook || {};
  fill('p-fb-title', fb.title || '');
  const fbTags = Array.isArray(fb.hashtags) ? fb.hashtags.join(' ') : (fb.hashtags || '');
  fill('p-fb-desc',  [fb.description, fbTags].filter(Boolean).join('\n\n'));
}

function _pUpdateYtTitleCount() {
  const t = document.getElementById('p-yt-title');
  const c = document.getElementById('p-yt-title-count');
  if (!t || !c) return;
  if (t.value.length > 100) t.value = t.value.slice(0, 100);
  c.textContent = t.value.length;
}

function _pUpdateTtTagsCount() {
  const t = document.getElementById('p-tt-tags');
  const c = document.getElementById('p-tt-tags-count');
  if (!t || !c) return;
  const cnt = _pCountHashtags(t.value);
  if (cnt > 5) {
    t.value = _pTtLimitHashtags(t.value, 5);
    c.textContent = _pCountHashtags(t.value);
  } else {
    c.textContent = cnt;
  }
}

/* ════════════════════════════════════════════════════════════════
   BATCH SCHEDULE — compute publish_at for each queued video
════════════════════════════════════════════════════════════════ */
function pBschedToggle() {
  const on = document.getElementById('p-bsched-enabled')?.checked;
  const body = document.getElementById('p-bsched-body');
  if (body) body.style.display = on ? 'block' : 'none';
  if (on) {
    // Default: start time = now + 10min
    const start = document.getElementById('p-bsched-start');
    if (start && !start.value) {
      const d = new Date(Date.now() + 10 * 60 * 1000);
      // Format as yyyy-MM-ddTHH:mm (local, no seconds)
      const pad = n => String(n).padStart(2, '0');
      start.value = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    pBschedRecalcPreview();
  }
}

function pBschedGetCount() {
  // Number of videos that will be processed: count pending/processing in batch queue, min 1
  const q = window._batchQueue || [];
  const pending = q.filter(t => t.status !== 'done' && t.status !== 'error');
  return Math.max(pending.length, 1);
}

function pBschedRecalcPreview() {
  const mode = document.getElementById('p-bsched-mode')?.value || 'interval';
  const spreadWrap = document.getElementById('p-bsched-spread-wrap');
  if (spreadWrap) spreadWrap.style.display = mode === 'spread' ? 'block' : 'none';

  const el = document.getElementById('p-bsched-preview');
  if (!el) return;

  if (!document.getElementById('p-bsched-enabled')?.checked) {
    el.textContent = '';
    return;
  }

  const n = pBschedGetCount();
  if (!n) { el.textContent = 'Chưa có video trong hàng chờ.'; return; }

  const startStr = document.getElementById('p-bsched-start')?.value;
  if (!startStr) { el.textContent = 'Chọn thời gian bắt đầu...'; return; }
  const startMs = new Date(startStr).getTime();
  if (isNaN(startMs)) { el.textContent = 'Thời gian không hợp lệ'; return; }

  let intervalH = 24;
  if (mode === 'spread') {
    const days = parseFloat(document.getElementById('p-bsched-spread-days')?.value || '7');
    // Distribute N videos evenly across the window: e.g. 10 videos / 10 days → 24h each.
    intervalH = n > 0 ? (days * 24) / n : 24;
  } else {
    intervalH = parseFloat(document.getElementById('p-bsched-interval')?.value || '24');
  }

  const first = new Date(startMs);
  const last  = new Date(startMs + (n - 1) * intervalH * 3600 * 1000);
  const fmt = d => d.toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });
  el.innerHTML = `📅 <b>${n}</b> video, cách nhau <b>${intervalH.toFixed(2)}h</b>. Video đầu: <b>${fmt(first)}</b>, cuối: <b>${fmt(last)}</b>.`;
}

/**
 * Compute the publish_at ISO string for the i-th video (0-based).
 * Returns null if scheduling is disabled or time has passed.
 */
function pBschedComputeAt(index) {
  if (!document.getElementById('p-bsched-enabled')?.checked) return null;

  const startStr = document.getElementById('p-bsched-start')?.value;
  if (!startStr) return null;
  const startMs = new Date(startStr).getTime();
  if (isNaN(startMs)) return null;

  const mode = document.getElementById('p-bsched-mode')?.value || 'interval';
  const n = pBschedGetCount();
  let intervalH = 24;
  if (mode === 'spread') {
    const days = parseFloat(document.getElementById('p-bsched-spread-days')?.value || '7');
    intervalH = n > 0 ? (days * 24) / n : 24;
  } else {
    intervalH = parseFloat(document.getElementById('p-bsched-interval')?.value || '24');
  }

  const t = new Date(startMs + index * intervalH * 3600 * 1000);
  const minFuture = new Date(Date.now() + 5 * 60 * 1000); // +5min minimum
  if (t <= minFuture) return null;
  return t;
}

/* ════════════════════════════════════════════════════════════════
   AUTO-UPLOAD after processing completes
════════════════════════════════════════════════════════════════ */
async function pPubAutoUploadAll(videoPath) {
  if (!document.getElementById('p-autopub-enabled')?.checked) return;
  if (!videoPath) {
    _appendProcLog?.('⚠ Không tìm thấy video để đăng', 'warning');
    return;
  }

  // Compute scheduled publish_at for this video (counter starts at 0)
  const idx = window._pBschedCounter || 0;
  const scheduledDate = pBschedComputeAt(idx);
  window._pBschedCounter = idx + 1;

  // Run preflight check — this also auto-disables platforms with blocking issues.
  // Only prompt the user on the first video of a batch to avoid spam.
  if (idx === 0) {
    const ok = await pPubPreflightCheck({ interactive: true });
    if (!ok) {
      _appendProcLog?.('⏹ Đã hủy đăng do user chọn', 'warning');
      return;
    }
  } else {
    await pPubPreflightCheck({ interactive: false });
  }

  const tasks = [];
  if (window._pPubEnabled.youtube)  tasks.push(pPubUploadYouTube(videoPath, scheduledDate));
  if (window._pPubEnabled.facebook) tasks.push(pPubUploadFacebook(videoPath, scheduledDate));
  if (window._pPubEnabled.tiktok)   tasks.push(pPubUploadTikTok(videoPath, scheduledDate));

  if (!tasks.length) {
    _appendProcLog?.('ℹ Không có nền tảng nào được bật để đăng', 'info');
    return;
  }

  await Promise.allSettled(tasks);
}


/* ════════════════════════════════════════════════════════════════
   PRE-FLIGHT CHECK — runs before processing starts & before each batch upload
   Returns: true → tiếp tục; false → user hủy
   Side effect: có thể set window._pPubEnabled[platform] = false nếu user đồng ý
════════════════════════════════════════════════════════════════ */
async function pPubPreflightCheck({ interactive = true } = {}) {
  const issues = [];
  const autopub = document.getElementById('p-autopub-enabled')?.checked;
  if (!autopub) return true; // no auto-publish → skip preflight

  // ── YouTube ──
  if (window._pPubEnabled.youtube) {
    try {
      const r = await fetch('/api/youtube_auth');
      const d = await r.json();
      if (!d.authenticated) {
        issues.push({
          platform: 'youtube', label: 'YouTube', severity: 'blocker',
          message: 'Chưa đăng nhập YouTube.',
          fix: 'Vào tab "Đăng video" → Nhấn "Kết nối YouTube".',
        });
      }
    } catch (_) {
      issues.push({
        platform: 'youtube', label: 'YouTube', severity: 'warning',
        message: 'Không kiểm tra được trạng thái YouTube (server lỗi).',
      });
    }
  }

  // ── Facebook ──
  if (window._pPubEnabled.facebook) {
    try {
      const r = await fetch('/api/facebook/status');
      const d = await r.json();
      if (!d.connected) {
        issues.push({
          platform: 'facebook', label: 'Facebook', severity: 'blocker',
          message: 'Chưa kết nối Facebook.',
          fix: 'Vào tab "Đăng video" → "Kết nối Facebook" rồi paste User Access Token.',
        });
      } else {
        let pageId = document.getElementById('p-fb-page-select')?.value
                    || document.getElementById('pub-fb-page-select')?.value;
        const pages = d.pages || [];
        // Auto-select first page if none selected yet
        if (!pageId && pages.length) {
          const firstPageId = pages[0].id || pages[0].page_id || '';
          if (firstPageId) {
            const pSel = document.getElementById('p-fb-page-select');
            const pubSel = document.getElementById('pub-fb-page-select');
            if (pSel) pSel.value = firstPageId;
            if (pubSel) pubSel.value = firstPageId;
            pageId = firstPageId;
            _appendProcLog?.(`ℹ Facebook: tự động chọn Page "${pages[0].name || firstPageId}"`, 'info');
          }
        }
        if (!pageId) {
          issues.push({
            platform: 'facebook', label: 'Facebook', severity: 'blocker',
            message: pages.length
              ? 'Chưa chọn Page để đăng.'
              : 'Tài khoản Facebook không quản lý Page nào.',
            fix: pages.length
              ? 'Chọn Page trong dropdown "📄 Đăng lên Page".'
              : 'Cần làm admin ít nhất 1 Page, rồi sinh token với pages_show_list + pages_manage_posts.',
          });
        } else {
          // Deep diagnose only once per session (costs 2-3 Graph calls)
          if (!window._pFbDiagCache) {
            try {
              const r2 = await fetch('/api/facebook/diagnose');
              const d2 = await r2.json();
              window._pFbDiagCache = d2;
              if (d2.ok && !d2.all_ok) {
                const failed = (d2.checks || []).filter(c => !c.ok);
                failed.forEach(c => issues.push({
                  platform: 'facebook', label: 'Facebook', severity: 'warning',
                  message: c.label + (c.detail ? ` — ${c.detail}` : ''),
                  fix: 'Chạy "Chẩn đoán" trong modal Facebook token để xem chi tiết.',
                }));
              }
            } catch (_) {}
          }
        }
      }
    } catch (_) {
      issues.push({
        platform: 'facebook', label: 'Facebook', severity: 'warning',
        message: 'Không kiểm tra được trạng thái Facebook (server lỗi).',
      });
    }
  }

  // ── TikTok ──
  // Caption/desc/hashtag sẽ được AI tự tạo trong pipeline từ nội dung ASS khi
  // user bật "Tạo nội dung bằng AI" — vậy không cảnh báo trống ở đây. Chỉ nhắc
  // nếu hashtag > 5 (sẽ bị cắt).
  if (window._pPubEnabled.tiktok) {
    // Check TikTok login status — if not logged in, prompt user to log in NOW
    // so the batch doesn't get stuck mid-run asking for login.
    try {
      const r = await fetch('/api/tiktok/check_login');
      const d = await r.json();
      if (!d.logged_in) {
        issues.push({
          platform: 'tiktok', label: 'TikTok', severity: 'blocker',
          message: 'Chưa đăng nhập TikTok Studio.',
          fix: 'Nhấn "Đăng nhập TikTok" bên dưới để mở cửa sổ đăng nhập.',
          action: 'tiktok_login',
        });
      }
    } catch (_) {
      // If server unreachable, skip — treat as warning
    }

    const tags = document.getElementById('p-tt-tags')?.value?.trim() || '';
    if (_pCountHashtags(tags) > 5) {
      issues.push({
        platform: 'tiktok', label: 'TikTok', severity: 'info',
        message: 'Nhiều hơn 5 hashtag — sẽ tự cắt còn 5.',
      });
    }
  }

  if (!issues.length) return true;

  // Non-interactive: just auto-disable blockers and log
  if (!interactive) {
    for (const iss of issues) {
      if (iss.severity === 'blocker') {
        window._pPubEnabled[iss.platform] = false;
        _appendProcLog?.(`⚠ ${iss.label}: ${iss.message} — bỏ qua`, 'warning');
      }
    }
    return true;
  }

  return await _pPubShowPreflightModal(issues);
}

function _pPubShowPreflightModal(issues) {
  return new Promise(resolve => {
    // Build modal on-the-fly (avoid adding HTML to spa_new.html)
    let modal = document.getElementById('pub-preflight-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'pub-preflight-modal';
      modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px;';
      document.body.appendChild(modal);
    }

    const rows = issues.map((iss, i) => {
      const color = iss.severity === 'blocker' ? '#d32f2f'
                  : iss.severity === 'warning' ? '#f57c00' : '#1976d2';
      const icon  = iss.severity === 'blocker' ? '❌' : iss.severity === 'warning' ? '⚠' : 'ℹ';
      const actionBtn = iss.action === 'tiktok_login'
        ? `<button class="btn btn-primary btn-sm" data-action="tiktok_login" style="margin-top:6px;margin-right:8px">🔐 Đăng nhập TikTok ngay</button>`
        : '';
      return `
        <div style="border-left:3px solid ${color};padding:10px 12px;margin-bottom:8px;background:#fafafa;border-radius:4px" data-issue-index="${i}">
          <div style="font-weight:600;color:${color};margin-bottom:4px">${icon} ${iss.label} — ${iss.message}</div>
          ${iss.fix ? `<div style="font-size:12px;color:#666">💡 ${iss.fix}</div>` : ''}
          ${actionBtn}
          ${iss.severity === 'blocker'
            ? `<label style="display:inline-flex;align-items:center;gap:6px;margin-top:6px;font-size:12px;cursor:pointer">
                 <input type="checkbox" data-disable-platform="${iss.platform}" ${iss.action === 'tiktok_login' ? '' : 'checked'}>
                 Tắt đăng lên ${iss.label} cho video này và tiếp tục
               </label>`
            : ''}
        </div>`;
    }).join('');

    modal.innerHTML = `
      <div style="background:#fff;border-radius:8px;max-width:560px;width:100%;max-height:80vh;overflow:auto;padding:20px;box-shadow:0 10px 40px rgba(0,0,0,.25)">
        <h3 style="margin:0 0 12px;font-size:16px">🔎 Kiểm tra trước khi đăng</h3>
        <div style="font-size:13px;color:#555;margin-bottom:12px">
          Phát hiện ${issues.length} vấn đề. Chọn cách xử lý rồi tiếp tục:
        </div>
        ${rows}
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
          <button class="btn btn-secondary btn-sm" id="pub-preflight-cancel">Hủy xử lý</button>
          <button class="btn btn-primary btn-sm" id="pub-preflight-continue">Tiếp tục</button>
        </div>
      </div>`;

    const close = (result) => {
      modal.style.display = 'none';
      resolve(result);
    };

    modal.style.display = 'flex';
    document.getElementById('pub-preflight-cancel').onclick = () => close(false);
    document.getElementById('pub-preflight-continue').onclick = () => {
      // Apply disables
      modal.querySelectorAll('input[data-disable-platform]').forEach(cb => {
        if (cb.checked) {
          const p = cb.dataset.disablePlatform;
          window._pPubEnabled[p] = false;
          _appendProcLog?.(`⏭ Đã tắt đăng lên ${p} theo lựa chọn của bạn`, 'warning');
        }
      });
      close(true);
    };

    // TikTok login handler: open browser, wait for login, then refresh the modal
    modal.querySelectorAll('[data-action="tiktok_login"]').forEach(btn => {
      btn.onclick = async () => {
        btn.disabled = true;
        btn.textContent = '⏳ Đang mở cửa sổ đăng nhập...';
        try {
          const r = await fetch('/api/tiktok/open_login', { method: 'POST' });
          const d = await r.json();
          if (!d.ok) {
            toast('❌ ' + (d.error || 'Không mở được cửa sổ đăng nhập'), 'error');
            btn.disabled = false;
            btn.textContent = '🔐 Đăng nhập TikTok ngay';
            return;
          }
          if (d.already_logged_in) {
            toast('✅ Đã đăng nhập sẵn — tiếp tục được rồi', 'success');
            // Remove this issue row
            const row = btn.closest('[data-issue-index]');
            if (row) row.remove();
            return;
          }
          btn.textContent = '⏳ Chờ bạn đăng nhập trong cửa sổ...';
          // Poll until done
          const sid = d.session_id;
          const deadline = Date.now() + 10 * 60 * 1000;
          while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, 2000));
            let s;
            try {
              const rr = await fetch('/api/tiktok/prepare_status?session_id=' + encodeURIComponent(sid));
              s = await rr.json();
            } catch (_) { continue; }
            if (!s.ok) continue;
            if (s.done) {
              if (s.error) {
                toast('❌ ' + s.error, 'error');
                btn.disabled = false;
                btn.textContent = '🔐 Đăng nhập TikTok ngay';
                return;
              }
              toast('✅ Đăng nhập TikTok thành công', 'success');
              // Remove this issue row since login is resolved
              const row = btn.closest('[data-issue-index]');
              if (row) row.remove();
              return;
            }
          }
          toast('⏱ Hết thời gian chờ đăng nhập', 'warning');
          btn.disabled = false;
          btn.textContent = '🔐 Đăng nhập TikTok ngay';
        } catch (e) {
          toast('❌ ' + e.message, 'error');
          btn.disabled = false;
          btn.textContent = '🔐 Đăng nhập TikTok ngay';
        }
      };
    });
  });
}

// Expose for app.js to call before starting processing.
window.pPubPreflightCheck = pPubPreflightCheck;

async function pPubUploadYouTube(videoPath, scheduledDate) {
  const title = _pYtTruncateTitle(document.getElementById('p-yt-title')?.value || '');
  if (!title) {
    _appendProcLog?.('⚠ YouTube: chưa có tiêu đề — bỏ qua', 'warning');
    return;
  }

  const desc     = document.getElementById('p-yt-desc')?.value?.trim()  || '';
  const tagsStr  = document.getElementById('p-yt-tags')?.value?.trim()  || '';
  const tags     = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];
  const isShort  = document.getElementById('p-yt-is-short')?.checked || false;
  let privacy    = document.getElementById('p-yt-privacy')?.value || 'private';

  let publishAt = null;
  if (scheduledDate) {
    // YouTube requires private + publish_at for scheduling
    privacy = 'private';
    publishAt = scheduledDate.toISOString().replace(/\.\d{3}Z$/, '.000Z');
    _appendProcLog?.(`🗓 YouTube: đặt lịch lúc ${scheduledDate.toLocaleString('vi-VN')}`, 'info');
  }

  const payload = {
    video_path:     videoPath,
    title,
    description:    desc,
    tags,
    privacy_status: privacy,
    is_short:       isShort,
    publish_at:     publishAt
  };

  _appendProcLog?.('🚀 Đang đăng lên YouTube...', 'info');
  try {
    const res = await fetch('/api/youtube_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    // Handle non-streaming error responses (401, 400, 500 return JSON)
    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try {
        const errData = await res.json();
        errMsg = errData.error || errMsg;
      } catch (_) {}
      if (res.status === 401) {
        _appendProcLog?.('❌ YouTube: chưa đăng nhập. Vào tab Đăng video → Đăng nhập YouTube', 'error');
        toast('⚠ Chưa đăng nhập YouTube — hãy đăng nhập trước', 'warning', 6000);
      } else {
        _appendProcLog?.('❌ YouTube: ' + errMsg, 'error');
      }
      return;
    }
    if (!res.body) throw new Error('Server không trả về stream');

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
          if (d.log) _appendProcLog?.('[YT] ' + d.log, d.level || 'info');
          if (d.url) _appendProcLog?.('🎉 [YT] ' + d.url, 'success');
        } catch (_) { _appendProcLog?.('[YT] ' + t, 'info'); }
      }
    }
  } catch (e) {
    _appendProcLog?.('❌ YouTube: ' + e.message, 'error');
  }
}

async function pPubUploadFacebook(videoPath, scheduledDate) {
  let pageId = document.getElementById('p-fb-page-select')?.value;
  // Auto-select first page if none selected
  if (!pageId) {
    const sel = document.getElementById('p-fb-page-select');
    if (sel && sel.options.length > 0) {
      // Pick first non-empty option
      const firstOpt = [...sel.options].find(o => o.value);
      if (firstOpt) {
        sel.value = firstOpt.value;
        pageId = firstOpt.value;
        _appendProcLog?.(`ℹ Facebook: tự động chọn Page "${firstOpt.textContent.trim()}"`, 'info');
      }
    }
  }
  if (!pageId) {
    _appendProcLog?.('⚠ Facebook: chưa chọn Page — bỏ qua', 'warning');
    return;
  }

  const title   = document.getElementById('p-fb-title')?.value?.trim() || '';
  const desc    = document.getElementById('p-fb-desc')?.value?.trim()  || '';
  const postTypeRaw = document.getElementById('p-fb-post-type')?.value || 'auto';

  let scheduledTime = '';
  if (scheduledDate) {
    const minFuture = new Date(Date.now() + 10 * 60 * 1000); // FB requires ≥10 min
    if (scheduledDate > minFuture) {
      scheduledTime = Math.floor(scheduledDate.getTime() / 1000).toString();
      _appendProcLog?.(`🗓 Facebook: đặt lịch lúc ${scheduledDate.toLocaleString('vi-VN')}`, 'info');
    } else {
      _appendProcLog?.('⚠ Facebook: lịch gần quá — đăng ngay', 'warning');
    }
  }

  // ── Decide Reel vs Video ──
  let postType = postTypeRaw; // 'auto' | 'reel' | 'video'
  if (postType === 'auto') {
    try {
      const r = await fetch('/api/facebook/validate_reel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_path: videoPath })
      });
      const d = await r.json();
      if (d.is_vertical_9_16 && d.ok) {
        postType = 'reel';
        _appendProcLog?.(`🎬 Auto: video ${d.width}x${d.height} → đăng dạng Reel`, 'info');
      } else {
        postType = 'video';
        if (d.error) {
          _appendProcLog?.(`ℹ Auto: ${d.error} → đăng dạng video thường`, 'info');
        }
      }
    } catch (_) {
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
    form.append('video_path', videoPath);
    // Only include title for the regular /videos endpoint
    if (postType !== 'reel') {
      form.append('title', title);
    }
    return form;
  };

  _appendProcLog?.(`🚀 Đang đăng lên Facebook (${postType === 'reel' ? 'Reel' : 'Video'})...`, 'info');

  // Retry loop — allows token refresh + retry up to 5 times
  for (let attempt = 1; attempt <= 5; attempt++) {
    const result = await _pFbUploadOnce(endpoint, buildForm());

    if (result.success) return;
    if (result.skip)    return; // user chose to skip this video

    if (result.tokenError) {
      // Show modal for user to paste new token
      const action = await _pFbShowTokenModal(result.errorMsg || '');
      if (action === 'retry')   { attempt--; continue; } // refresh & try again (same attempt count)
      if (action === 'skip')    { _appendProcLog?.('⏭ Bỏ qua video này', 'warning'); return; }
      // cancel: exit loop
      return;
    }

    // Non-token error: stop retrying
    return;
  }
}

/**
 * Perform a single Facebook upload attempt.
 * Returns: { success: bool, tokenError: bool, errorMsg: string, skip: bool }
 */
async function _pFbUploadOnce(endpoint, form) {
  const out = { success: false, tokenError: false, errorMsg: '', skip: false };
  try {
    const res = await fetch(endpoint, { method: 'POST', body: form });

    // Non-stream error response (401, 400, etc.)
    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      let tokenError = false;
      try {
        const errData = await res.json();
        errMsg = errData.error || errMsg;
        tokenError = !!errData.token_error;
      } catch (_) {}
      if (res.status === 401) tokenError = true;
      _appendProcLog?.('❌ Facebook: ' + errMsg, 'error');
      out.errorMsg = errMsg;
      out.tokenError = tokenError;
      return out;
    }
    if (!res.body) {
      out.errorMsg = 'Server không trả về stream';
      return out;
    }

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
          if (d.log) _appendProcLog?.('[FB] ' + d.log, d.level || 'info');
          if (d.url) _appendProcLog?.('🎉 [FB] ' + d.url, 'success');
          if (d.ok)  gotOk = true;
          if (d.token_error) {
            out.tokenError = true;
            out.errorMsg = d.error || d.log || 'Token hết hạn';
          } else if (d.error) {
            out.errorMsg = d.error;
          }
        } catch (_) { _appendProcLog?.('[FB] ' + t, 'info'); }
      }
    }
    out.success = gotOk;
    return out;
  } catch (e) {
    _appendProcLog?.('❌ Facebook: ' + e.message, 'error');
    out.errorMsg = e.message;
    return out;
  }
}

/**
 * Show the Facebook token modal. Resolves with 'retry' | 'skip' | 'cancel'.
 */
function _pFbShowTokenModal(errMsg) {
  return new Promise(resolve => {
    const modal = document.getElementById('fb-token-modal');
    const errEl = document.getElementById('fb-token-modal-error');
    const warnEl = document.getElementById('fb-token-modal-warnings');
    const input = document.getElementById('fb-token-modal-input');
    const btn   = document.getElementById('btn-fb-token-modal-save');
    if (!modal) { resolve('cancel'); return; }
    if (errEl) {
      if (errMsg) { errEl.style.display = 'block'; errEl.textContent = '❌ ' + errMsg; }
      else        { errEl.style.display = 'none'; }
    }
    if (warnEl) warnEl.style.display = 'none';
    const diagEl = document.getElementById('fb-token-modal-diag');
    if (diagEl) diagEl.style.display = 'none';
    if (input) input.value = '';
    if (btn)   { btn.disabled = false; btn.textContent = '🔄 Lưu & Thử lại'; }
    window._fbTokenModalForceRetry = false;
    modal.style.display = 'flex';
    window._fbTokenModalResolve = resolve;

    // Auto-run diagnose so user can see *which* scope/check is failing without
    // having to click the button. Safe to call even for expired tokens — the
    // endpoint handles that gracefully.
    setTimeout(() => {
      try { fbTokenModalDiagnose(); } catch (_) {}
    }, 100);
  });
}

function fbTokenModalTogglePw() {
  const el = document.getElementById('fb-token-modal-input');
  if (el) el.type = el.type === 'password' ? 'text' : 'password';
}

async function fbTokenModalDiagnose() {
  const box = document.getElementById('fb-token-modal-diag');
  if (!box) return;
  box.style.display = 'block';
  box.innerHTML = '⏳ Đang chẩn đoán...';
  try {
    const r = await fetch('/api/facebook/diagnose');
    const d = await r.json();
    if (!d.ok) {
      box.innerHTML = '❌ ' + (d.error || 'Lỗi chẩn đoán');
      return;
    }
    const rows = (d.checks || []).map(c => {
      const icon = c.ok ? '✅' : '❌';
      const det  = c.detail ? ` <span style="color:#6b8cba">— ${c.detail}</span>` : '';
      return `<div>${icon} <b>${c.label}</b>${det}</div>`;
    }).join('');
    const header = d.all_ok
      ? '<b style="color:#0d7a4e">Tất cả check OK — thử đăng lại</b>'
      : '<b style="color:#c0392b">Có vấn đề — xem chi tiết:</b>';
    box.innerHTML = header + '<div style="margin-top:6px">' + rows + '</div>';
  } catch (e) {
    box.innerHTML = '❌ ' + e.message;
  }
}

function fbTokenModalCancel() {
  const modal = document.getElementById('fb-token-modal');
  if (modal) modal.style.display = 'none';
  if (window._fbTokenModalResolve) {
    window._fbTokenModalResolve('cancel');
    window._fbTokenModalResolve = null;
  }
}

function fbTokenModalSkip() {
  const modal = document.getElementById('fb-token-modal');
  if (modal) modal.style.display = 'none';
  if (window._fbTokenModalResolve) {
    window._fbTokenModalResolve('skip');
    window._fbTokenModalResolve = null;
  }
}

async function fbTokenModalSave() {
  const input = document.getElementById('fb-token-modal-input');
  const errEl = document.getElementById('fb-token-modal-error');
  const warnEl = document.getElementById('fb-token-modal-warnings');
  const btn   = document.getElementById('btn-fb-token-modal-save');
  const token = input?.value?.trim();
  if (!token) {
    if (errEl) { errEl.style.display = 'block'; errEl.textContent = '❌ Vui lòng nhập token'; }
    return;
  }
  if (errEl) errEl.style.display = 'none';
  if (warnEl) warnEl.style.display = 'none';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang kết nối...'; }
  try {
    const res = await fetch('/api/facebook/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await res.json();
    if (data.ok) {
      // Show any warnings (missing perms, no pages, wrong token type)
      const warnings = data.warnings || [];
      if (warnings.length && warnEl) {
        warnEl.style.display = 'block';
        warnEl.innerHTML = '<b>⚠ Cảnh báo:</b><ul style="margin:4px 0 0 16px;padding:0;list-style:disc">'
          + warnings.map(w => '<li>' + w + '</li>').join('')
          + '</ul>';
      }

      // Refresh UI on publish page
      if (typeof _pubFbShowConnected === 'function') {
        _pubFbShowConnected(data.user, data.pages || []);
      }
      if (typeof _pSyncAccountSelectors === 'function') {
        setTimeout(_pSyncAccountSelectors, 100);
      }

      // If there are critical warnings (missing required perms), don't auto-retry —
      // force user to read them and pick an action.
      const missing = data.missing_perms || [];
      if (missing.length) {
        toast(`⚠ Token thiếu quyền: ${missing.join(', ')}`, 'warning', 8000);
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Vẫn thử đăng'; }
        // User can now click "Vẫn thử đăng" → treat as retry, or Skip/Cancel
        window._fbTokenModalForceRetry = true;
        return;
      }

      // All good — close modal and retry
      const modal = document.getElementById('fb-token-modal');
      if (modal) modal.style.display = 'none';
      toast(`✅ Kết nối lại Facebook (${(data.pages || []).length} Page)`, 'success');
      if (window._fbTokenModalResolve) {
        window._fbTokenModalResolve('retry');
        window._fbTokenModalResolve = null;
      }
    } else {
      if (errEl) {
        errEl.style.display = 'block';
        errEl.textContent = '❌ ' + (data.error || 'Token không hợp lệ');
      }
    }
  } catch (e) {
    if (errEl) { errEl.style.display = 'block'; errEl.textContent = '❌ ' + e.message; }
  } finally {
    if (btn && !window._fbTokenModalForceRetry) { btn.disabled = false; btn.textContent = '🔄 Lưu & Thử lại'; }
  }
}

/**
 * Second-click action when user bypasses the perm warnings.
 * Wired to the same button — after first save showed warnings, clicking again
 * forces the retry regardless.
 */
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btn-fb-token-modal-save');
  if (!btn) return;
  const orig = btn.onclick;
  btn.addEventListener('click', () => {
    if (window._fbTokenModalForceRetry) {
      window._fbTokenModalForceRetry = false;
      const modal = document.getElementById('fb-token-modal');
      if (modal) modal.style.display = 'none';
      if (window._fbTokenModalResolve) {
        window._fbTokenModalResolve('retry');
        window._fbTokenModalResolve = null;
      }
    }
  });
});

async function pPubUploadTikTok(videoPath, scheduledDate) {
  // Semi-auto: open TikTok Studio in a controlled browser, attach file + fill
  // caption, then wait for the user to press Post manually. This avoids the
  // "copy caption → paste" chore without violating the ToS by posting for them.
  const caption  = document.getElementById('p-tt-title')?.value?.trim() || '';
  const desc     = document.getElementById('p-tt-desc')?.value?.trim()  || '';
  const hashtags = _pTtLimitHashtags(document.getElementById('p-tt-tags')?.value?.trim() || '', 5);
  const fullCaption = [caption, desc, hashtags].filter(Boolean).join('\n');

  if (!videoPath) {
    _appendProcLog?.('⚠ TikTok: chưa có file video để upload', 'warning');
    return;
  }

  // Build scheduled_time ISO string if available
  let scheduledTime = '';
  if (scheduledDate && scheduledDate instanceof Date) {
    const minFuture = new Date(Date.now() + 15 * 60 * 1000); // TikTok requires ≥15 min
    if (scheduledDate > minFuture) {
      scheduledTime = scheduledDate.toISOString();
      _appendProcLog?.(`🗓 TikTok: đặt lịch lúc ${scheduledDate.toLocaleString('vi-VN')}`, 'info');
    }
  }

  // Also copy caption to clipboard as a safety net so user can paste if the
  // automated fill fails (DOM changes are frequent on TikTok).
  if (fullCaption) {
    try { await navigator.clipboard.writeText(fullCaption); } catch (_) {}
  }

  _appendProcLog?.('🎬 TikTok: mở trình duyệt để chuẩn bị bài đăng...', 'info');

  let startResp;
  try {
    const payload = { video_path: videoPath, caption: fullCaption };
    if (scheduledTime) payload.scheduled_time = scheduledTime;
    const r = await fetch('/api/tiktok/prepare_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    startResp = await r.json();
    if (!startResp.ok) throw new Error(startResp.error || 'Không start được session');
  } catch (e) {
    _appendProcLog?.('❌ TikTok: ' + e.message, 'error');
    _appendProcLog?.('ℹ Mở tab TikTok upload thủ công thay thế...', 'info');
    try { window.open('https://www.tiktok.com/tiktokstudio/upload', '_blank'); } catch (_) {}
    return;
  }

  const sid = startResp.session_id;
  _appendProcLog?.(`🆔 TikTok session: ${sid}`, 'info');

  // Poll status and forward log lines to the processing log. Stop when:
  //  - status is 'ready' (file attached, caption filled → user review)
  //  - or session is done/closed/error
  let seenLogs = 0;
  let reachedReady = false;
  const timeoutAt = Date.now() + 15 * 60 * 1000; // 15 min hard cap
  while (Date.now() < timeoutAt) {
    await new Promise(r => setTimeout(r, 1500));
    let data;
    try {
      const r = await fetch('/api/tiktok/prepare_status?session_id=' + encodeURIComponent(sid));
      data = await r.json();
    } catch (_) { continue; }
    if (!data.ok) {
      _appendProcLog?.('❌ TikTok: ' + (data.error || 'status lỗi'), 'error');
      return;
    }
    const newLogs = (data.log || []).slice(seenLogs);
    seenLogs = (data.log || []).length;
    for (const entry of newLogs) {
      _appendProcLog?.(`[TT] ${entry.msg}`, entry.level || 'info');
    }
    if (!reachedReady && data.status === 'ready') {
      reachedReady = true;
      toast('✅ TikTok đã sẵn sàng — hãy kiểm tra và nhấn Post trong cửa sổ đang mở', 'success', 8000);
      // We don't await the session closing: user can review at their pace.
      return;
    }
    if (data.done) {
      if (data.error) _appendProcLog?.('❌ TikTok: ' + data.error, 'error');
      return;
    }
  }
  _appendProcLog?.('⏱ TikTok: timeout chờ chuẩn bị (15 phút)', 'warning');
}

/* ════════════════════════════════════════════════════════════════
   ACCOUNT SELECTOR MIRRORING — copy accounts from publish page
════════════════════════════════════════════════════════════════ */
function _pSyncAccountSelectors() {
  // Mirror yt-account-select and fb-account-select into p-* versions.
  // PRESERVE the destination's current value — only rebuild the option list
  // if the source's HTML actually changed. Otherwise a periodic rebuild
  // would reset the user's Page selection every 5 seconds.
  const mirror = (srcId, dstId) => {
    const src = document.getElementById(srcId);
    const dst = document.getElementById(dstId);
    if (!src || !dst) return;
    if (dst.dataset.lastSyncedHtml !== src.innerHTML) {
      const prevValue = dst.value;
      dst.innerHTML = src.innerHTML;
      dst.dataset.lastSyncedHtml = src.innerHTML;
      // Restore selection if the option still exists; else fall back to src.value
      if (prevValue && [...dst.options].some(o => o.value === prevValue)) {
        dst.value = prevValue;
      } else if (src.value) {
        dst.value = src.value;
      }
    }
  };
  mirror('yt-account-select', 'p-yt-account-select');
  mirror('fb-account-select', 'p-fb-account-select');

  // Sync FB page list with the same preserve-selection logic
  const srcPage = document.getElementById('pub-fb-page-select');
  const dstPage = document.getElementById('p-fb-page-select');
  if (srcPage && dstPage && dstPage.dataset.lastSyncedHtml !== srcPage.innerHTML) {
    const prevValue = dstPage.value;
    dstPage.innerHTML = srcPage.innerHTML;
    dstPage.dataset.lastSyncedHtml = srcPage.innerHTML;
    if (prevValue && [...dstPage.options].some(o => o.value === prevValue)) {
      dstPage.value = prevValue;
    } else if (srcPage.value) {
      dstPage.value = srcPage.value;
    }
  }
}

/* ════════════════════════════════════════════════════════════════
   HOOK: called by page_process.html when ASS review is confirmed
════════════════════════════════════════════════════════════════ */
async function pPubOnAssConfirmed(assPath, assContent) {
  // Fire-and-forget AI analyze — do not block the pipeline
  try {
    await pPubAnalyzeFromAss(assContent);
  } catch (e) {
    console.warn('pPubOnAssConfirmed:', e);
  }
}

/* ════════════════════════════════════════════════════════════════
   INIT: live validators + account mirror
════════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  const ytTitle = document.getElementById('p-yt-title');
  if (ytTitle) ytTitle.addEventListener('input', _pUpdateYtTitleCount);
  const ttTags  = document.getElementById('p-tt-tags');
  if (ttTags)  ttTags.addEventListener('input', _pUpdateTtTagsCount);

  // Keep batch schedule preview in sync with queue
  ['p-bsched-start', 'p-bsched-interval', 'p-bsched-spread-days']
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', pBschedRecalcPreview);
    });

  // Initial mirror + poll every 5s (accounts.js may load async)
  setTimeout(_pSyncAccountSelectors, 500);
  setInterval(_pSyncAccountSelectors, 5000);
});

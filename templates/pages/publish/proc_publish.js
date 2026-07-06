/* ── proc_publish.js ───────────────────────────────────────────
   Auto-publish panel inside Process page.
   - AI auto-fills title/description/hashtags from ASS content on review continue
   - Enforces: YouTube title ≤ 100, TikTok ≤ 5 hashtags
   - Auto-uploads to enabled platforms after video processing completes
   - Batch schedule: spreads N videos over N days (or custom interval)
   - ────────────────────────────────────────────────────────────── */

window._pPubEnabled = { youtube: true, tiktok: true, facebook: true };
window._pPubActive  = 'youtube';
window._pPubAIResult = null;
window._pBschedCounter = 0;

const _P_PLATFORMS = ['youtube', 'tiktok', 'facebook'];
const _P_TAB_ID = { youtube: 'yt', tiktok: 'tt', facebook: 'fb' };

/* ── TAB SWITCHING + PLATFORM TOGGLE ── */
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

/* ── LIMITS: YouTube title ≤ 100, TikTok ≤ 5 hashtags ── */
function _pYtTruncateTitle(t) {
  if (!t) return '';
  t = String(t).trim();
  return t.length > 100 ? t.slice(0, 97) + '...' : t;
}

function _pTtLimitHashtags(str, max = 5) {
  if (!str) return '';
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
  return [...others, ...tags].join(' ').trim();
}

function _pCountHashtags(str) {
  if (!str) return 0;
  return (String(str).match(/#[^\s#]+/g) || []).length;
}

function _pStripInlineHashtags(text) {
  if (!text) return '';
  return String(text)
    .replace(/#[^\s#]+/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([,.!?;:])/g, '$1')
    .trim();
}

function _pDedupHashtagString(str) {
  if (!str) return '';
  const seen = new Set();
  const out = [];
  for (const tok of String(str).split(/\s+/)) {
    if (!tok) continue;
    const key = tok.toLowerCase().replace(/^#+/, '');
    if (!key) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tok.startsWith('#') ? tok : '#' + tok);
  }
  return out.join(' ');
}

function _pBuildCaption(prose, hashtagsStr) {
  const cleanProse = _pStripInlineHashtags(prose || '');
  const cleanTags  = _pDedupHashtagString(hashtagsStr || '');
  return [cleanProse, cleanTags].filter(Boolean).join('\n');
}

window._pStripInlineHashtags = _pStripInlineHashtags;
window._pDedupHashtagString  = _pDedupHashtagString;
window._pBuildCaption        = _pBuildCaption;

/* ── AI ANALYZE & AUTO-FILL from ASS content ── */
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

function _pVideoAiAnalysisHint() {
  const payload = window._procVideoAiAnalysis;
  if (!window._procUseAiAnalysis || !payload?.result) return '';
  if (payload.analysis_text) return payload.analysis_text;
  const r = payload.result || {};
  const cover = Array.isArray(r.needs_cover) ? r.needs_cover : [];
  const zones = Array.isArray(r.suggested_blur_zones) ? r.suggested_blur_zones : [];
  const titles = r.title_suggestions || {};
  return [
    r.summary ? `Tóm tắt hình ảnh/video: ${r.summary}` : '',
    r.visual_style ? `Đặc điểm video: ${r.visual_style}` : '',
    r.source_language ? `Ngôn ngữ gốc phát hiện: ${r.source_language}` : '',
    cover.length ? `Thành phần cần che: ${cover.map(x => x.label || x.type || '').filter(Boolean).join('; ')}` : '',
    zones.length ? `Vùng che đề xuất: ${zones.map(x => x.label || x.reason || '').filter(Boolean).join('; ')}` : '',
    titles.youtube ? `Gợi ý tiêu đề YouTube: ${titles.youtube}` : (titles.short ? `Gợi ý tiêu đề: ${titles.short}` : ''),
    r.analysis_notes ? `Ghi chú AI đọc video: ${r.analysis_notes}` : '',
  ].filter(Boolean).join('\n');
}

async function pPubAnalyzeFromAss(assContent) {
  if (!document.getElementById('p-autopub-enabled')?.checked) return null;
  const plain = _pExtractPlainFromAss(assContent || '');
  const visualAnalysis = _pVideoAiAnalysisHint();
  if (!plain && !visualAnalysis) {
    _appendProcLog?.('⚠ ASS trống và chưa có phân tích video — bỏ qua AI phân tích', 'warning');
    return null;
  }

  const provider = document.getElementById('p-pub-ai-provider')?.value || 'deepseek';
  const targetLang = document.getElementById('proc-target-lang')?.value || 'vi';
  _appendProcLog?.(visualAnalysis
    ? '🤖 AI đang dùng phân tích video + ASS để tạo tiêu đề/hashtag...'
    : '🤖 AI đang phân tích nội dung ASS để tạo tiêu đề/hashtag...', 'info');

  try {
    const res = await fetch('/api/analyze_video_content', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: plain.slice(0, 3000),
        visual_analysis: visualAnalysis.slice(0, 2000),
        provider,
        target_language: targetLang
      })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'AI phân tích thất bại');

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

  const yt = info.youtube || {};
  const ytTitle = _pYtTruncateTitle(_pStripInlineHashtags(yt.title || ''));
  const fill = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };
  const arr  = v => Array.isArray(v) ? v.join(', ') : (v || '');

  fill('p-yt-title', ytTitle);
  fill('p-yt-desc',  _pStripInlineHashtags(yt.description || ''));
  fill('p-yt-tags',  arr(yt.tags));
  _pUpdateYtTitleCount();

  const tt = info.tiktok || {};
  fill('p-tt-title', _pStripInlineHashtags(tt.caption || ''));
  const ttTags = Array.isArray(tt.hashtags) ? tt.hashtags.join(' ') : (tt.hashtags || '');
  fill('p-tt-tags',  _pTtLimitHashtags(_pDedupHashtagString(ttTags), 5));
  _pUpdateTtTagsCount();

  const fb = info.facebook || {};
  fill('p-fb-title', _pStripInlineHashtags(fb.title || ''));
  const fbTags = Array.isArray(fb.hashtags) ? fb.hashtags.join(' ') : (fb.hashtags || '');
  fill('p-fb-tags',  _pDedupHashtagString(fbTags));
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

/* ── BATCH SCHEDULE ── */
function pBschedToggle() {
  const on = document.getElementById('p-bsched-enabled')?.checked;
  const body = document.getElementById('p-bsched-body');
  if (body) body.style.display = on ? 'block' : 'none';
  if (on) {
    const start = document.getElementById('p-bsched-start');
    if (start && !start.value) {
      const d = new Date(Date.now() + 10 * 60 * 1000);
      const pad = n => String(n).padStart(2, '0');
      start.value = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    pBschedRecalcPreview();
  }
}

function pBschedGetCount() {
  const q = window._batchQueue || [];
  const pending = q.filter(t => t.status !== 'done' && t.status !== 'error');
  return pending.length;
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
    intervalH = n > 0 ? (days * 24) / n : 24;
  } else {
    intervalH = parseFloat(document.getElementById('p-bsched-interval')?.value || '24');
  }

  const first = new Date(startMs);
  const last  = new Date(startMs + (n - 1) * intervalH * 3600 * 1000);
  const fmt = d => d.toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' });
  el.innerHTML = `📅 <b>${n}</b> video, cách nhau <b>${intervalH.toFixed(2)}h</b>. Video đầu: <b>${fmt(first)}</b>, cuối: <b>${fmt(last)}</b>.`;
}

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
  const minFuture = new Date(Date.now() + 5 * 60 * 1000);
  if (t <= minFuture) return null;
  return t;
}

/* ── AUTO-UPLOAD after processing ── */
async function pPubAutoUploadAll(videoPath) {
  if (!document.getElementById('p-autopub-enabled')?.checked) return;
  if (!videoPath) {
    _appendProcLog?.('⚠ Không tìm thấy video để đăng', 'warning');
    return;
  }

  const idx = window._pBschedCounter || 0;
  const scheduledDate = pBschedComputeAt(idx);
  window._pBschedCounter = idx + 1;

  if (idx === 0) {
    const ok = await pPubPreflightCheck({ interactive: true });
    if (!ok) {
      _appendProcLog?.('⏹ Đã hủy đăng do user chọn', 'warning');
      return;
    }
  } else {
    await pPubPreflightCheck({ interactive: false });
  }

  const platforms = [];
  if (window._pPubEnabled.youtube)  platforms.push('youtube');
  if (window._pPubEnabled.facebook) platforms.push('facebook');
  if (window._pPubEnabled.tiktok)   platforms.push('tiktok');

  if (!platforms.length) {
    _appendProcLog?.('ℹ Không có nền tảng nào được bật để đăng', 'info');
    return;
  }

  const videoName = (videoPath || '').split(/[\\/]/).pop();

  for (const plat of platforms) {
    if (window._pPubCancelled) break;
    const action = await _pPubUploadWithRetry(plat, videoPath, scheduledDate, videoName);
    if (action === 'cancel') {
      window._pPubCancelled = true;
      _appendProcLog?.('🛑 User đã huỷ pipeline đăng video', 'error');
      break;
    }
  }
}

async function _pPubUploadWithRetry(platform, videoPath, scheduledDate, videoName) {
  const PLATFORM_FNS = {
    youtube:  () => pPubUploadYouTube(videoPath, scheduledDate),
    facebook: () => pPubUploadFacebook(videoPath, scheduledDate),
    tiktok:   () => pPubUploadTikTok(videoPath, scheduledDate),
  };
  const PLATFORM_LABELS = { youtube: 'YT', facebook: 'FB', tiktok: 'TT' };
  const fn = PLATFORM_FNS[platform];
  if (!fn) return 'skip';

  let attempt = 0;
  while (true) {
    attempt += 1;
    if (window._pPubCancelled) return 'cancel';

    let ok = false;
    let errorInfo = null;
    try {
      window._pPubLastError = null;
      await fn();
      if (!window._pPubLastError) {
        ok = true;
      } else {
        errorInfo = window._pPubLastError;
      }
    } catch (e) {
      errorInfo = { error: e.message };
    }

    if (ok) return 'ok';

    const action = await window.showUploadErrorModal({
      platform,
      title: `Upload ${platform} thất bại (lần ${attempt})`,
      video: videoName,
      error: errorInfo?.error || 'Lỗi không xác định',
      errorCode: errorInfo?.errorCode || '',
      tokenError: !!errorInfo?.tokenError,
      diagnostic: errorInfo ? JSON.stringify(errorInfo, null, 2) : '',
    });

    if (action === 'retry') {
      _appendProcLog?.(`  [${PLATFORM_LABELS[platform]}] 🔄 Thử lại lần ${attempt + 1}...`, 'info');
      continue;
    }
    if (action === 'skip') {
      _appendProcLog?.(`  [${PLATFORM_LABELS[platform]}] ⏭ Bỏ qua video này`, 'warning');
      return 'skip';
    }
    return 'cancel';
  }
}

/* ── PRE-FLIGHT CHECK ── */
async function pPubPreflightCheck({ interactive = true } = {}) {
  const issues = [];
  const autopub = document.getElementById('p-autopub-enabled')?.checked;
  if (!autopub) return true;

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
        if (d.is_expired) {
          issues.push({
            platform: 'facebook', label: 'Facebook', severity: 'blocker',
            message: 'Token Facebook đã hết hạn.',
            fix: d.has_app_credentials
              ? 'Nhấn nút "🔄 Gia hạn token" trong tab Đăng video → Facebook.'
              : 'Vào Graph API Explorer lấy token mới rồi kết nối lại.',
          });
        } else if (d.days_left !== null && d.days_left !== undefined && d.days_left <= 7) {
          issues.push({
            platform: 'facebook', label: 'Facebook', severity: 'warning',
            message: `Token Facebook sắp hết hạn (còn ${d.days_left} ngày).`,
            fix: d.has_app_credentials
              ? 'Nhấn "🔄 Gia hạn token" để gia hạn thêm 60 ngày.'
              : 'Lấy token mới từ Graph API Explorer trước khi hết hạn.',
          });
        }
        let pageId = document.getElementById('p-fb-page-select')?.value
                    || document.getElementById('pub-fb-page-select')?.value;
        const pages = d.pages || [];
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

  if (window._pPubEnabled.tiktok) {
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
    } catch (_) {}

    const tags = document.getElementById('p-tt-tags')?.value?.trim() || '';
    if (_pCountHashtags(tags) > 5) {
      issues.push({
        platform: 'tiktok', label: 'TikTok', severity: 'info',
        message: 'Nhiều hơn 5 hashtag — sẽ tự cắt còn 5.',
      });
    }
  }

  if (!issues.length) return true;

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
      modal.querySelectorAll('input[data-disable-platform]').forEach(cb => {
        if (cb.checked) {
          const p = cb.dataset.disablePlatform;
          window._pPubEnabled[p] = false;
          _appendProcLog?.(`⏭ Đã tắt đăng lên ${p} theo lựa chọn của bạn`, 'warning');
        }
      });
      close(true);
    };

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
            const row = btn.closest('[data-issue-index]');
            if (row) row.remove();
            return;
          }
          btn.textContent = '⏳ Chờ bạn đăng nhập trong cửa sổ...';
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
  const madeForKids = document.getElementById('p-yt-made-for-kids')?.value === 'true';
  let privacy    = document.getElementById('p-yt-privacy')?.value || 'private';

  let publishAt = null;
  if (scheduledDate) {
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
    made_for_kids:  madeForKids,
    publish_at:     publishAt
  };

  _appendProcLog?.('🚀 Đang đăng lên YouTube...', 'info');
  try {
    const res = await fetch('/api/youtube_upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try {
        const errData = await res.json();
        errMsg = errData.error || errMsg;
      } catch (_) {}
      const tokenErr = res.status === 401 || /not authenticated|token|expired|oauth/i.test(errMsg);
      window._pPubLastError = { error: errMsg, errorCode: res.status, tokenError: tokenErr };
      if (tokenErr) {
        _appendProcLog?.('❌ YouTube: chưa đăng nhập. Vào tab Đăng video → Đăng nhập YouTube', 'error');
      } else {
        _appendProcLog?.('❌ YouTube: ' + errMsg, 'error');
      }
      return;
    }
    if (!res.body) {
      window._pPubLastError = { error: 'Server không trả về stream' };
      throw new Error('Server không trả về stream');
    }

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let uploadOk = false;
    let lastErrLog = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n'); buf = lines.pop() || '';
      for (const line of lines) {
        const t = line.trim(); if (!t) continue;
        try {
          const d = JSON.parse(t);
          if (d.log) {
            _appendProcLog?.('[YT] ' + d.log, d.level || 'info');
            if (d.level === 'error') lastErrLog = d.log;
          }
          if (d.url) { _appendProcLog?.('🎉 [YT] ' + d.url, 'success'); uploadOk = true; }
          if (d.video_id) uploadOk = true;
        } catch (_) { _appendProcLog?.('[YT] ' + t, 'info'); }
      }
    }
    if (!uploadOk) {
      const errMsg = lastErrLog || 'YouTube upload không thành công';
      const tokenErr = /token|oauth|expired|not authenticated|invalid_grant|401/i.test(errMsg);
      window._pPubLastError = { error: errMsg, tokenError: tokenErr };
    }
  } catch (e) {
    window._pPubLastError = { error: e.message };
    _appendProcLog?.('❌ YouTube: ' + e.message, 'error');
  }
}

async function pPubUploadFacebook(videoPath, scheduledDate) {
  let pageId = document.getElementById('p-fb-page-select')?.value;
  if (!pageId) {
    const sel = document.getElementById('p-fb-page-select');
    if (sel && sel.options.length > 0) {
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
  const tags    = document.getElementById('p-fb-tags')?.value?.trim()  || '';
  const desc    = _pBuildCaption(title, tags);
  const postTypeRaw = document.getElementById('p-fb-post-type')?.value || 'auto';

  let scheduledTime = '';
  if (scheduledDate) {
    const minFuture = new Date(Date.now() + 10 * 60 * 1000);
    if (scheduledDate > minFuture) {
      scheduledTime = Math.floor(scheduledDate.getTime() / 1000).toString();
      _appendProcLog?.(`🗓 Facebook: đặt lịch lúc ${scheduledDate.toLocaleString('vi-VN')}`, 'info');
    } else {
      _appendProcLog?.('⚠ Facebook: lịch gần quá — đăng ngay', 'warning');
    }
  }

  let postType = postTypeRaw;
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
    if (postType !== 'reel') {
      form.append('title', title);
    }
    return form;
  };

  _appendProcLog?.(`🚀 Đang đăng lên Facebook (${postType === 'reel' ? 'Reel' : 'Video'})...`, 'info');

  for (let attempt = 1; attempt <= 5; attempt++) {
    const result = await _pFbUploadOnce(endpoint, buildForm());

    if (result.success) return;
    if (result.skip) {
      window._pPubLastError = { error: 'User skipped Facebook upload' };
      return;
    }

    if (result.tokenError) {
      window._pPubLastError = {
        error: result.errorMsg || 'Token Facebook hết hạn',
        tokenError: true,
      };
      return;
    }

    window._pPubLastError = {
      error: result.errorMsg || 'Facebook upload thất bại',
      tokenError: false,
    };
    return;
  }
  window._pPubLastError = { error: 'Đã thử 5 lần nhưng không thành công' };
}

async function _pFbUploadOnce(endpoint, form) {
  const out = { success: false, tokenError: false, errorMsg: '', skip: false };
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
      const warnings = data.warnings || [];
      if (warnings.length && warnEl) {
        warnEl.style.display = 'block';
        warnEl.innerHTML = '<b>⚠ Cảnh báo:</b><ul style="margin:4px 0 0 16px;padding:0;list-style:disc">'
          + warnings.map(w => '<li>' + w + '</li>').join('')
          + '</ul>';
      }

      if (typeof _pubFbShowConnected === 'function') {
        _pubFbShowConnected(data.user, data.pages || []);
      }
      if (typeof _pSyncAccountSelectors === 'function') {
        setTimeout(_pSyncAccountSelectors, 100);
      }

      const missing = data.missing_perms || [];
      if (missing.length) {
        toast(`⚠ Token thiếu quyền: ${missing.join(', ')}`, 'warning', 8000);
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Vẫn thử đăng'; }
        window._fbTokenModalForceRetry = true;
        return;
      }

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

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btn-fb-token-modal-save');
  if (!btn) return;
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
  const caption  = document.getElementById('p-tt-title')?.value?.trim() || '';
  const hashtags = _pTtLimitHashtags(_pDedupHashtagString(document.getElementById('p-tt-tags')?.value?.trim() || ''), 5);
  const fullCaption = _pBuildCaption(caption, hashtags);

  if (!videoPath) {
    _appendProcLog?.('⚠ TikTok: chưa có file video để upload', 'warning');
    return;
  }

  let scheduledTime = '';
  if (scheduledDate && scheduledDate instanceof Date) {
    const minFuture = new Date(Date.now() + 15 * 60 * 1000);
    if (scheduledDate > minFuture) {
      scheduledTime = scheduledDate.toISOString();
      _appendProcLog?.(`🗓 TikTok: đặt lịch lúc ${scheduledDate.toLocaleString('vi-VN')}`, 'info');
    }
  }

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
    const msg = e.message || 'TikTok lỗi';
    const tokenErr = /login|session|expired|not.*logged/i.test(msg);
    window._pPubLastError = { error: msg, tokenError: tokenErr };
    _appendProcLog?.('❌ TikTok: ' + msg, 'error');
    return;
  }

  const sid = startResp.session_id;
  _appendProcLog?.(`🆔 TikTok session: ${sid}`, 'info');

  let seenLogs = 0;
  let reachedReady = false;
  const timeoutAt = Date.now() + 15 * 60 * 1000;
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
      return;
    }
    if (data.done) {
      if (data.error) _appendProcLog?.('❌ TikTok: ' + data.error, 'error');
      return;
    }
  }
  _appendProcLog?.('⏱ TikTok: timeout chờ chuẩn bị (15 phút)', 'warning');
}

/* ── ACCOUNT SELECTOR MIRRORING ── */
function _pSyncAccountSelectors() {
  const mirror = (srcId, dstId) => {
    const src = document.getElementById(srcId);
    const dst = document.getElementById(dstId);
    if (!src || !dst) return;
    if (dst.dataset.lastSyncedHtml !== src.innerHTML) {
      const prevValue = dst.value;
      dst.innerHTML = src.innerHTML;
      dst.dataset.lastSyncedHtml = src.innerHTML;
      if (prevValue && [...dst.options].some(o => o.value === prevValue)) {
        dst.value = prevValue;
      } else if (src.value) {
        dst.value = src.value;
      }
    }
  };
  mirror('yt-account-select', 'p-yt-account-select');
  mirror('fb-account-select', 'p-fb-account-select');

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

/* ── HOOK ── */
async function pPubOnAssConfirmed(assPath, assContent) {
  try {
    await pPubAnalyzeFromAss(assContent);
  } catch (e) {
    console.warn('pPubOnAssConfirmed:', e);
  }
}

/* ── INIT ── */
document.addEventListener('DOMContentLoaded', () => {
  const ytTitle = document.getElementById('p-yt-title');
  if (ytTitle) ytTitle.addEventListener('input', _pUpdateYtTitleCount);
  const ttTags  = document.getElementById('p-tt-tags');
  if (ttTags)  ttTags.addEventListener('input', _pUpdateTtTagsCount);

  ['p-bsched-start', 'p-bsched-interval', 'p-bsched-spread-days']
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('input', pBschedRecalcPreview);
    });

  setTimeout(_pSyncAccountSelectors, 500);
  setInterval(_pSyncAccountSelectors, 5000);
});

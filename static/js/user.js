/* ── User search page ────────────────────────────────────────────────────── */
let _userVideos = [], _userPage = 1, _userPageSize = 20;
let _userHasMore = false, _userNextCursor = 0, _userSecUid = '';
let _userAwemeCount = 0; // tổng số video thật từ profile
let _userLoadedOffset = 0; // offset dùng khi cursor=0 (Douyin chặn pagination)
let _selectedIds = new Set();
let _queuedAwemeIds = new Set();
let _viEnabled = true;
let _isLoadingVideos = false; // tránh dịch khi đang load video
let _translateDebounceTimer = null;
let _viCache = {};
let _translationScopeUrl = '';
let _translationProvider = 'auto';
let _profileTranslationCache = {};
let _isTranslating = false;

// Trả về true khi tab "Tìm video người dùng" đang mở.
// Chặn dịch nền khi user đã chuyển sang tab khác.
function _isUserPageActive() {
  return !!document.getElementById('page-user')?.classList.contains('active');
}

// Hiển thị trạng thái dịch âm thầm trên badge provider thay vì che cả màn hình
function _setTranslateStatusBadge(state, providerName) {
  const badge = document.getElementById('current-provider-badge');
  if (!badge) return;
  if (state === 'translating') {
    badge.innerHTML = '<span class="dot dot-yellow"></span>' + (typeof t === 'function' ? t('lbl_translating') : 'Đang dịch...');
  } else if (state === 'done') {
    const name = providerName || _translationProvider || 'auto';
    badge.innerHTML = '<span class="dot dot-green"></span>' + (typeof t === 'function' ? t('lbl_provider_badge') : 'Provider:') + ' ' + name;
  }
}

const _PROFILE_CACHE_PREFIX = 'douyin.userProfileTranslations.v1';

const _VI_CACHE_PREFIX = 'douyin.userTranslations.v1';

function _translationCacheKey(scopeUrl, provider) {
  return [_VI_CACHE_PREFIX, encodeURIComponent(scopeUrl || ''), provider || 'auto'].join('|');
}

function _loadTranslationCache(scopeUrl, provider) {
  try {
    const raw = localStorage.getItem(_translationCacheKey(scopeUrl, provider));
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function _saveTranslationCache() {
  if (!_translationScopeUrl) return;
  try {
    localStorage.setItem(_translationCacheKey(_translationScopeUrl, _translationProvider), JSON.stringify(_viCache));
  } catch (e) {
    // Ignore storage quota failures.
  }
}

function _setTranslationContext(scopeUrl, provider) {
  _translationScopeUrl = scopeUrl || '';
  _translationProvider = provider || 'auto';
  _viCache = _loadTranslationCache(_translationScopeUrl, _translationProvider);
}

function _getCachedTranslation(awemeId) {
  return _viCache[awemeId] || '';
}

function _storeCachedTranslation(awemeId, text) {
  if (!awemeId) return;
  _viCache[awemeId] = text || '';
  _saveTranslationCache();
}

function _clearTranslationCache() {
  if (!_translationScopeUrl) return;
  _viCache = {};
  try {
    localStorage.removeItem(_translationCacheKey(_translationScopeUrl, _translationProvider));
  } catch (e) {
    // Ignore storage failures.
  }
}

function _profileCacheKey(scopeUrl, provider) {
  return [_PROFILE_CACHE_PREFIX, encodeURIComponent(scopeUrl || ''), provider || 'auto'].join('|');
}

function _loadProfileTranslationCache(scopeUrl, provider) {
  try {
    const raw = localStorage.getItem(_profileCacheKey(scopeUrl, provider));
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function _saveProfileTranslationCache() {
  if (!_translationScopeUrl) return;
  try {
    localStorage.setItem(_profileCacheKey(_translationScopeUrl, _translationProvider), JSON.stringify(_profileTranslationCache));
  } catch (e) {
    // Ignore storage quota failures.
  }
}

function _setProfileTranslationContext(scopeUrl, provider) {
  _profileTranslationCache = _loadProfileTranslationCache(scopeUrl, provider);
}

function _getProfileTranslatedData() {
  return _profileTranslationCache || {};
}

function _storeProfileTranslatedData(translatedName, translatedSig) {
  _profileTranslationCache = {
    name: translatedName || '',
    signature: translatedSig || '',
  };
  _saveProfileTranslationCache();
}

async function _translateUserProfileAsync(info, provider, nameViEl, sigViEl) {
  const nickname = (info?.nickname || '').trim();
  const signature = (info?.signature || '').trim();
  if (!nickname && !signature) return;

  const cachedProfile = _getProfileTranslatedData();
  const texts = [];
  const fieldMap = [];

  if (nickname && !cachedProfile.name) {
    texts.push(nickname);
    fieldMap.push('name');
  }
  if (signature && !cachedProfile.signature) {
    texts.push(signature);
    fieldMap.push('signature');
  }

  if (!texts.length) return;

  try {
    if (nameViEl && !cachedProfile.name) nameViEl.textContent = t('lbl_translating');
    if (sigViEl && !cachedProfile.signature) sigViEl.textContent = t('lbl_translating');

    // Dịch âm thầm: gọi fetch trực tiếp để tránh kích hoạt LoadingUI overlay toàn cục
    const endpoint = texts.length > 1 ? '/api/translate_batch' : '/api/translate';
    const body = texts.length > 1 ? { texts, provider } : { text: texts[0], provider };
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const translated = await res.json();

    const results = Array.isArray(translated?.results)
      ? translated.results
      : [translated?.result || ''];

    const translatedName = cachedProfile.name || (fieldMap.includes('name') ? (results[fieldMap.indexOf('name')] || nickname) : nickname);
    const translatedSig = cachedProfile.signature || (fieldMap.includes('signature') ? (results[fieldMap.indexOf('signature')] || signature) : signature);

    if (nameViEl) nameViEl.textContent = translatedName;
    if (sigViEl) sigViEl.textContent = translatedSig;
    _storeProfileTranslatedData(translatedName, translatedSig);
  } catch (e) {
    if (nameViEl && !cachedProfile.name) nameViEl.textContent = nickname;
    if (sigViEl && !cachedProfile.signature) sigViEl.textContent = signature;
  }
}

function _hydratePageTranslations(items) {
  (items || []).forEach(v => {
    if (!v.desc_vi) {
      const cached = _getCachedTranslation(v.aweme_id);
      if (cached) v.desc_vi = cached;
    }
  });
}

function _extractAwemeIdFromUrl(url) {
  const m = String(url || '').match(/\/video\/(\d+)/);
  return m ? m[1] : '';
}

function _syncQueuedAwemeIds() {
  const windowQueue = Array.isArray(window._queue) ? window._queue : [];
  const localQueue = (typeof _queue !== 'undefined' && Array.isArray(_queue)) ? _queue : [];
  const list = windowQueue.length ? windowQueue : localQueue;
  const next = new Set();
  list.forEach(item => {
    const id = _extractAwemeIdFromUrl(item?.url);
    if (id) next.add(id);
  });
  _queuedAwemeIds = next;
}

function _isAwemeInQueue(awemeId) {
  return _queuedAwemeIds.has(String(awemeId || ''));
}

function _toBool(value) {
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase();
    return v === '1' || v === 'true' || v === 'yes';
  }
  if (typeof value === 'number') return value !== 0;
  return !!value;
}

function _toCursor(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

async function _fetchUserVideosPage(cursor, count) {
  const url = document.getElementById('user-url')?.value.trim();
  if (!url) return null;
  // Gửi offset (số video đã load từ server) để server bỏ qua khi cursor=0
  const offset = cursor === 0 ? (_userLoadedOffset || _userVideos.length) : 0;
  const res = await API.post('/api/user_videos_page', { url, cursor, count, offset });
  if (res?.error) throw new Error(res.error);
  return res;
}

async function _appendMoreVideos(cursor, count, renderCurrent = false) {
  _isLoadingVideos = true;
  const res = await _fetchUserVideosPage(cursor, count).finally(() => { _isLoadingVideos = false; });
  if (!res) return null;

  const beforeLen = _userVideos.length;
  const merged = _userVideos.concat(res.videos || []);
  const dedup = [];
  const seen = new Set();
  for (const item of merged) {
    const key = String(item?.aweme_id || '');
    if (!key || seen.has(key)) continue;
    seen.add(key);
    dedup.push(item);
  }
  _userVideos = dedup;

  _userHasMore = _toBool(res.has_more);
  _userNextCursor = _toCursor(res.next_cursor);
  // Nếu server trả offset, lưu lại để dùng cho lần load tiếp
  if (res.offset !== undefined) _userLoadedOffset = res.offset;

  // Nếu API không trả thêm item mới và cursor không tiến → API bị chặn
  if (_userVideos.length === beforeLen && (!_userNextCursor || _userNextCursor === cursor)) {
    _userHasMore = false;
    if (_userAwemeCount > 0 && _userVideos.length < _userAwemeCount) {
      toast('API Douyin bị chặn phân trang. Hãy dùng Download để lấy đủ video (có browser fallback).', 'warning');
    }
  }

  // Nếu aweme_count cho thấy còn video và cursor đã tiến → tiếp tục
  if (!_userHasMore && _userNextCursor && _userNextCursor !== cursor
      && _userAwemeCount > 0 && _userVideos.length < _userAwemeCount) {
    _userHasMore = true;
  }

  const statusEl = document.getElementById('load-status');
  if (statusEl) {
    const total = _userAwemeCount > 0 ? _userAwemeCount : '?';
    statusEl.textContent = _userVideos.length + '/' + total + ' video' + (_userHasMore ? ' (còn nữa)' : '');
  }
  if (renderCurrent) _renderVideos();
  return res;
}

async function _ensurePageLoaded(pageNumber) {
  const required = pageNumber * _userPageSize;
  if (_userVideos.length >= required || !_userHasMore) return;
  while (_userHasMore && _userVideos.length < required) {
    const currentCursor = _userNextCursor;
    const res = await _appendMoreVideos(currentCursor, 20, false);
    if (!res || !res.has_more) break;
    if (!res.next_cursor || res.next_cursor === currentCursor) break;
  }
}

function _applyFilters() {
  const type = document.getElementById('filter-type')?.value || 'all';
  const sort = document.getElementById('filter-sort')?.value || 'newest';
  const search = (document.getElementById('filter-search')?.value || '').toLowerCase();

  let list = _userVideos.filter(v => {
    if (type !== 'all' && v.type !== type) return false;
    if (search && !(v.desc || '').toLowerCase().includes(search) && !(v.desc_vi || '').toLowerCase().includes(search)) return false;
    return true;
  });

  list.sort((a, b) => {
    if (sort === 'newest') return b.ts - a.ts;
    if (sort === 'oldest') return a.ts - b.ts;
    if (sort === 'most_play') return b.play - a.play;
    if (sort === 'most_like') return b.like - a.like;
    return 0;
  });
  return list;
}

function _renderVideos() {
  _syncQueuedAwemeIds();
  const list = _applyFilters();
  const grid = document.getElementById('video-grid');
  const countEl = document.getElementById('video-count');
  if (countEl) countEl.textContent = _userVideos.length;
  if (!grid) return;

  const start = (_userPage - 1) * _userPageSize;
  const page = list.slice(start, start + _userPageSize);
  _hydratePageTranslations(page);

  if (!page.length) { grid.innerHTML = '<div class="empty-state">Không có video</div>'; return; }

  // Build HTML — use data-aweme-id to avoid full re-render flicker
  const newHtml = page.map((v, idx) => {
    const thumb = v.cover ? '/api/proxy_image?url=' + encodeURIComponent(v.cover) : '';
    const inQueue = _isAwemeInQueue(v.aweme_id);
    if (inQueue) _selectedIds.delete(v.aweme_id);
    const sel = !inQueue && _selectedIds.has(v.aweme_id);
    const desc = (v.desc || '');
    const descVi = (_viEnabled && v.desc_vi) ? v.desc_vi : '';
    const durTxt = fmtDur(v.duration);
    const durationLabel = v.type === 'video' ? (durTxt || '--:--') : '';
    return '<div class="vcard' + (sel ? ' selected' : '') + (inQueue ? ' in-queue' : '') + '" data-aweme="' + v.aweme_id + '" onclick="toggleSelect(\'' + v.aweme_id + '\')">' +
      '<div class="vcard-thumb">' +
        (thumb
          ? '<img src="' + thumb + '" loading="lazy" decoding="async" style="width:100%;height:100%;object-fit:cover;display:block">'
          : '<div class="vcard-thumb-ph">&#127916;</div>') +
        '<div class="vcard-check">' + (sel ? '&#10003;' : '') + '</div>' +
        (inQueue ? '<span class="vcard-lock">&#128274;</span>' : '') +
        (v.type === 'gallery' ? '<span class="vcard-type badge-gallery">&#128247;</span>' : '') +
        (durationLabel ? '<span class="vcard-dur">' + durationLabel + '</span>' : '') +
      '</div>' +
      '<div class="vcard-meta">' +
        '<div class="vcard-desc">' + escHtml(desc) + '</div>' +
        (descVi ? '<div class="vcard-vi">' + escHtml(descVi) + '</div>' : '') +
        '<div class="vcard-stats">' +
          '<span>&#9654; ' + fmtNum(v.play) + '</span>' +
          '<span>&#10084; ' + fmtNum(v.like) + '</span>' +
          (durationLabel ? '<span>&#9201; ' + durationLabel + '</span>' : '') +
        '</div>' +
        '<div class="vcard-date">' + (v.date || '') + '</div>' +
      '</div>' +
    '</div>';
  }).join('');

  // Only update DOM if content actually changed (prevents image flicker on re-render)
  if (grid.dataset.lastHtml !== newHtml) {
    grid.dataset.lastHtml = newHtml;
    grid.innerHTML = newHtml;
  } else {
    // Content same — just update selected/queue states without full re-render
    grid.querySelectorAll('.vcard').forEach(card => {
      const id = card.dataset.aweme;
      if (!id) return;
      const inQ = _isAwemeInQueue(id);
      const sel2 = !inQ && _selectedIds.has(id);
      card.className = 'vcard' + (sel2 ? ' selected' : '') + (inQ ? ' in-queue' : '');
      const chk = card.querySelector('.vcard-check');
      if (chk) chk.innerHTML = sel2 ? '&#10003;' : '';
    });
  }

  // Pagination
  const totalPages = Math.max(1, Math.ceil(list.length / _userPageSize));
  const pageInfo = document.getElementById('page-info');
  if (pageInfo) pageInfo.textContent = t('lbl_page') + ' ' + _userPage + ' ' + t('lbl_of') + ' ' + totalPages;
  const pageJump = document.getElementById('page-jump');
  if (pageJump) {
    pageJump.max = String(totalPages);
    if (!pageJump.value || Number(pageJump.value) !== _userPage) pageJump.value = String(_userPage);
  }
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  if (btnPrev) btnPrev.disabled = _userPage <= 1;
  if (btnNext) btnNext.disabled = _userPage >= totalPages && !_userHasMore;

  _updateSelCount();
}

function toggleSelect(id) {
  if (_isAwemeInQueue(id)) return;
  if (_selectedIds.has(id)) _selectedIds.delete(id);
  else _selectedIds.add(id);
  _renderVideos();
}

function selectAll() {
  _applyFilters().forEach(v => {
    if (!_isAwemeInQueue(v.aweme_id)) _selectedIds.add(v.aweme_id);
  });
  _renderVideos();
}

function selectNone() { _selectedIds.clear(); _renderVideos(); }

function _updateSelCount() {
  const el = document.getElementById('sel-count');
  if (el) el.textContent = _selectedIds.size;
  const btn = document.getElementById('btn-dl-selected');
  if (btn) btn.classList.toggle('hidden', _selectedIds.size === 0);
}

function addSelectedToProcessQueue() {
  const selected = _userVideos.filter(v => _selectedIds.has(v.aweme_id));
  if (!selected.length) return;

  // Ensure _batchQueue exists (defined in page_process.html script)
  if (!window._batchQueue) window._batchQueue = [];

  // Reverse order: videos at the bottom of the user page (older posts) go
  // to the front of the queue, so they are processed and published in
  // chronological order matching the author's timeline.
  const ordered = selected.slice().reverse();

  let added = 0;
  ordered.forEach(v => {
    const url = 'https://www.douyin.com/video/' + v.aweme_id;
    // Avoid duplicates
    if (!window._batchQueue.find(t => t.val === url)) {
      window._batchQueue.push({
        id: 'bt-' + Date.now() + '-' + v.aweme_id,
        type: 'url',
        val: url,
        status: 'pending',
        desc: v.desc_vi || v.desc || url,
      });
      added++;
    }
  });

  if (typeof _renderBatchQueue === 'function') _renderBatchQueue();
  toast(`✅ Đã thêm ${added} video vào hàng chờ xử lý (video cũ xử lý trước)`, 'success');

  // Switch to process page
  if (added > 0) {
    switchPage('process');
  }
}

async function downloadSelected() {
  const selected = _userVideos.filter(v => _selectedIds.has(v.aweme_id));
  if (!selected.length) return;

  const items = selected.map(v => ({
    url: 'https://www.douyin.com/video/' + v.aweme_id,
    desc: v.desc_vi || v.desc,
    cover: v.cover,
    date: v.date,
  }));
  const res = await API.post('/api/queue/add', items);
  if (res?.added > 0) toast(t('toast_added_queue') + ' (' + res.added + ')', 'success');
  else toast('Khong co video moi duoc them (co the da ton tai)', 'warning');
  if (typeof loadQueue === 'function') loadQueue();

  // Add to queue first for responsiveness; translate descriptions in background.
  const needTranslate = selected.filter(v => !v.desc_vi && v.desc);
  if (needTranslate.length) {
    _ensureItemsTranslatedForQueue(needTranslate)
      .then(async () => {
        const updates = needTranslate
          .filter(v => v.desc_vi)
          .map(v => API.post('/api/queue/update', {
            url: 'https://www.douyin.com/video/' + v.aweme_id,
            desc: v.desc_vi,
          }));
        if (updates.length) {
          await Promise.allSettled(updates);
          if (typeof loadQueue === 'function') loadQueue();
        }
      })
      .catch(() => {});
  }

  _selectedIds.clear();
  _renderVideos();
}

async function _ensureItemsTranslatedForQueue(items) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return;

  const provider = document.getElementById('provider-select')?.value || 'auto';
  if (provider !== _translationProvider) {
    _setTranslationContext(_translationScopeUrl, provider);
  }

  list.forEach(v => {
    if (!v.desc_vi) {
      const cached = _getCachedTranslation(v.aweme_id);
      if (cached) v.desc_vi = cached;
    }
  });

  const needFetch = list.filter(v => !v.desc_vi && v.desc);
  if (!needFetch.length) return;

  try {
    LoadingUI.start(t('lbl_translating'));
    const res = await fetch('/api/translate_batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts: needFetch.map(v => v.desc), provider })
    });
    const data = await res.json();
    const results = data.results || [];
    needFetch.forEach((v, i) => {
      v.desc_vi = results[i] || v.desc;
      _storeCachedTranslation(v.aweme_id, v.desc_vi);
    });
  } catch (e) {
    needFetch.forEach(v => { v.desc_vi = v.desc; });
  } finally {
    LoadingUI.stop();
  }
}

function goPrev() {
  if (_userPage > 1) { _userPage--; _renderVideos(); if (_viEnabled) _translateVisibleDebounced(); }
}

async function goNext() {
  const list = _applyFilters();
  const totalPages = Math.ceil(list.length / _userPageSize);
  if (_userPage < totalPages) {
    _userPage++; _renderVideos(); if (_viEnabled) _translateVisibleDebounced(); return;
  }
  if (_userHasMore) {
    await _ensurePageLoaded(_userPage + 1);
    const refreshed = _applyFilters();
    const refreshedPages = Math.max(1, Math.ceil(refreshed.length / _userPageSize));
    if (_userPage < refreshedPages) _userPage++;
    _renderVideos();
    if (_viEnabled) _translateVisibleDebounced(1200); // chờ lâu hơn sau khi load video mới
  }
}

async function goToPage(pageNumber) {
  const input = document.getElementById('page-jump');
  const rawValue = pageNumber ?? input?.value;
  const target = Math.max(1, parseInt(rawValue, 10) || 1);

  if (_userHasMore && target > Math.max(1, Math.ceil(_applyFilters().length / _userPageSize))) {
    await _ensurePageLoaded(target);
  }

  const list = _applyFilters();
  const totalPages = Math.max(1, Math.ceil(list.length / _userPageSize));
  const clamped = Math.min(target, totalPages);

  if (clamped === _userPage) {
    if (_viEnabled) _translateVisibleDebounced();
    return;
  }

  _userPage = Math.min(clamped, Math.max(1, Math.ceil(_applyFilters().length / _userPageSize)));
  _renderVideos();
  if (_viEnabled) _translateVisibleDebounced();
}

async function _loadMoreVideos() {
  await _appendMoreVideos(_userNextCursor, 20, true);
}

function onQueueStateChanged() {
  _syncQueuedAwemeIds();
  _renderVideos();
}

window.onQueueStateChanged = onQueueStateChanged;

async function searchUser() {
  const url = document.getElementById('user-url')?.value.trim();
  if (!url) return;

  const currentProvider = document.getElementById('provider-select')?.value || 'auto';
  _setTranslationContext(url, currentProvider);
  _setProfileTranslationContext(url, currentProvider);

  document.getElementById('user-loading')?.classList.remove('hidden');
  document.getElementById('user-result')?.classList.add('hidden');
  document.getElementById('user-videos-section')?.classList.add('hidden');

  try {
    const info = await API.post('/api/user_info', { url });
    if (info.error) { toast(info.error, 'error'); return; }

    // Render user card
    const avatarEl = document.getElementById('u-avatar');
    if (avatarEl) {
      avatarEl.innerHTML = info.avatar
        ? '<img class="user-avatar" src="/api/proxy_image?url=' + encodeURIComponent(info.avatar) + '">'
        : '<div class="user-avatar-ph">?</div>';
    }
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val || ''; };
    set('u-name', info.nickname);
    set('u-sig', info.signature);
    set('u-posts', fmtNum(info.aweme_count));
    set('u-followers', fmtNum(info.follower));
    set('u-following', fmtNum(info.following));

    const nameViEl = document.getElementById('u-name-vi');
    const sigViEl = document.getElementById('u-sig-vi');
    if (nameViEl) nameViEl.textContent = '';
    if (sigViEl) sigViEl.textContent = '';

    const cachedProfile = _getProfileTranslatedData();
    if (cachedProfile.name && nameViEl) nameViEl.textContent = cachedProfile.name;
    if (cachedProfile.signature && sigViEl) sigViEl.textContent = cachedProfile.signature;

    document.getElementById('user-result')?.classList.remove('hidden');
    document.getElementById('user-videos-section')?.classList.remove('hidden');

    // Load videos - server đã trả hết tất cả video 1 lần
    _userVideos = info.videos || [];
    _userHasMore = false;
    _userNextCursor = 0;
    _userSecUid = info.sec_uid;
    _userAwemeCount = parseInt(info.aweme_count) || _userVideos.length;
    _userLoadedOffset = _userVideos.length;
    _userPage = 1;
    _selectedIds.clear();

    const statusEl = document.getElementById('load-status');
    const fetched = info.fetched_count ?? _userVideos.length;
    const total = info.aweme_count || fetched;
    const btnLoadAll = document.getElementById('btn-load-all');
    if (info.pagination_blocked && fetched < total) {
      if (statusEl) {
        statusEl.textContent = fetched + '/' + total + ' video (Douyin giới hạn API)';
        statusEl.style.color = 'var(--yellow, #f5a623)';
      }
      if (btnLoadAll) {
        btnLoadAll.classList.remove('hidden');
        btnLoadAll.style.display = '';
        btnLoadAll.textContent = 'Tải đủ ' + total + ' video (qua trình duyệt)';
        btnLoadAll.disabled = false;
      }
    } else {
      if (statusEl) {
        statusEl.textContent = fetched + ' video';
        statusEl.style.color = '';
      }
      if (btnLoadAll) {
        btnLoadAll.classList.add('hidden');
        btnLoadAll.style.display = 'none';
      }
    }

    _renderVideos();

    _translateUserProfileAsync(info, currentProvider, nameViEl, sigViEl);

    // Auto-translate if VI toggle is on
    if (_viEnabled) _translateVisibleDebounced(500);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  } finally {
    document.getElementById('user-loading')?.classList.add('hidden');
  }
}

async function _translateVisible() {
  // Chỉ auto-dịch khi đang ở tab "Tìm video người dùng"
  if (!_isUserPageActive()) return;
  // Không dịch khi đang load video để tránh 2 request nặng song song
  if (_isLoadingVideos) return;
  // Tránh chồng nhiều request dịch song song
  if (_isTranslating) return;

  const list = _applyFilters();
  const start = (_userPage - 1) * _userPageSize;
  const page = list.slice(start, start + _userPageSize);
  _hydratePageTranslations(page);
  const toTranslate = page.filter(v => !v.desc_vi && v.desc);
  if (!toTranslate.length) return;

  const provider = document.getElementById('provider-select')?.value || 'auto';
  if (provider !== _translationProvider) {
    _setTranslationContext(_translationScopeUrl, provider);
  }

  // Check cache first
  const needFetch = toTranslate.filter(v => !_getCachedTranslation(v.aweme_id));
  const fromCache = toTranslate.filter(v => _getCachedTranslation(v.aweme_id));
  fromCache.forEach(v => { v.desc_vi = _getCachedTranslation(v.aweme_id); });

  if (needFetch.length) {
    _isTranslating = true;
    // Dịch nền: chỉ cập nhật badge nhỏ, không show overlay che màn hình
    _setTranslateStatusBadge('translating');
    try {
      // 1 batch request cho toàn trang
      const res = await fetch('/api/translate_batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: needFetch.map(v => v.desc), provider })
      });
      const data = await res.json();
      const results = data.results || [];
      const usedProvider = data.provider || provider;

      needFetch.forEach((v, i) => {
        v.desc_vi = results[i] || v.desc;
        _storeCachedTranslation(v.aweme_id, v.desc_vi);
      });

      _setTranslateStatusBadge('done', usedProvider);
    } catch (e) {
      needFetch.forEach(v => { v.desc_vi = v.desc; });
      _setTranslateStatusBadge('done');
    } finally {
      _isTranslating = false;
    }
  }

  // Chỉ render lại nếu vẫn còn ở tab user (tránh re-render thừa)
  if (_isUserPageActive()) _renderVideos();
}

// Debounced translate: chờ 800ms sau lần gọi cuối để tránh spam request
function _translateVisibleDebounced(delay = 800) {
  if (_translateDebounceTimer) clearTimeout(_translateDebounceTimer);
  _translateDebounceTimer = setTimeout(() => {
    _translateDebounceTimer = null;
    if (_viEnabled && !_isLoadingVideos && _isUserPageActive()) _translateVisible();
  }, delay);
}

async function retranslateAll() {
  if (!confirm(t('lbl_retranslate_confirm'))) return;
  _clearTranslationCache();
  _userVideos.forEach(v => { delete v.desc_vi; });
  _renderVideos();
  if (_viEnabled) _translateVisible();
}

// Filter/sort listeners — attached after DOM ready
function _initUserPageListeners() {
  ['filter-type','filter-sort','filter-search'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', () => { _userPage = 1; _renderVideos(); });
  });
  document.getElementById('filter-search')?.addEventListener('input', () => { _userPage = 1; _renderVideos(); });
  document.getElementById('toggle-vi')?.addEventListener('change', e => {
    _viEnabled = e.target.checked;
    _renderVideos();
    if (_viEnabled) _translateVisibleDebounced();
  });
  document.getElementById('provider-select')?.addEventListener('change', () => {
    const scopeUrl = document.getElementById('user-url')?.value.trim() || _translationScopeUrl;
    _setTranslationContext(scopeUrl, document.getElementById('provider-select')?.value || 'auto');
    _renderVideos();
    if (_viEnabled) _translateVisibleDebounced();
  });

  document.getElementById('page-jump')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') goToPage();
  });

  // Load translation status on init
  _loadTranslationStatus();
}

async function _loadTranslationStatus() {
  try {
    const status = await API.get('/api/translation_status');
    const badge = document.getElementById('current-provider-badge');
    if (!badge) return;

    const preferred = status.preferred || 'auto';
    const providers = status.providers || [];

    // Set provider select default
    const sel = document.getElementById('provider-select');
    if (sel && preferred !== 'auto') sel.value = preferred;

    // Show status badge
    const hasKey = providers.length > 1 || (providers.length === 1 && providers[0] !== 'google');
    badge.innerHTML = hasKey
      ? '<span class="dot dot-green"></span>' + t('lbl_provider_badge') + ' ' + preferred
      : '<span class="dot dot-yellow"></span>Google only (no API keys)';
  } catch (e) {
    const badge = document.getElementById('current-provider-badge');
    if (badge) badge.innerHTML = '<span class="dot dot-yellow"></span>Google Translate';
  }
}

// Tải đủ video qua browser fallback (khi Douyin chặn pagination API)
async function loadAllVideos() {
  const url = document.getElementById('user-url')?.value.trim();
  if (!url) return;

  const btn = document.getElementById('btn-load-all');
  const statusEl = document.getElementById('load-status');
  const originalBtnText = btn?.textContent || '';
  if (btn) { btn.disabled = true; btn.textContent = 'Đang mở trình duyệt...'; }
  if (statusEl) {
    statusEl.textContent = 'Đang mở trình duyệt Douyin để lấy đủ video...';
    statusEl.style.color = 'var(--yellow, #f5a623)';
  }

  _isLoadingVideos = true;
  const seen = new Set(_userVideos.map(v => String(v.aweme_id)));
  const knownIds = Array.from(seen);
  let gotAny = false;
  let lastError = '';

  try {
    const response = await fetch('/api/user_videos_all', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, known_ids: knownIds })
    });

    if (!response.ok) {
      let msg = 'HTTP ' + response.status;
      try {
        const err = await response.json();
        if (err?.error) msg = err.error;
      } catch (_) {}
      throw new Error(msg);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    const renderStatus = () => {
      if (!statusEl) return;
      const total = _userAwemeCount > 0 ? _userAwemeCount : _userVideos.length;
      statusEl.textContent = _userVideos.length + '/' + total + ' video';
      if (_userVideos.length >= total) statusEl.style.color = '';
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        let chunk;
        try { chunk = JSON.parse(trimmed); } catch (_) { continue; }

        if (chunk.kind === 'error') {
          lastError = chunk.message || 'Unknown error';
          toast('Lỗi: ' + lastError, 'error');
          continue;
        }
        if (chunk.kind === 'status') {
          if (statusEl && chunk.message) statusEl.textContent = chunk.message;
          continue;
        }
        if (chunk.kind === 'progress') {
          if (statusEl) {
            if (chunk.phase === 'detail' && chunk.total) {
              statusEl.textContent = 'Đang lấy chi tiết ' + chunk.fetched + '/' + chunk.total + ' video...';
            } else if (chunk.collected !== undefined) {
              statusEl.textContent = 'Đã quét ' + chunk.collected + ' video, cần bổ sung ' + (chunk.missing || 0);
            }
          }
          continue;
        }
        if (chunk.kind === 'videos' && Array.isArray(chunk.videos)) {
          for (const v of chunk.videos) {
            const key = String(v.aweme_id || '');
            if (!key || seen.has(key)) continue;
            seen.add(key);
            _userVideos.push(v);
            gotAny = true;
          }
          renderStatus();
          _renderVideos();
          continue;
        }
        if (chunk.kind === 'done') {
          renderStatus();
        }
      }
    }

    _userHasMore = false;
    if (gotAny) {
      toast('Đã bổ sung ' + (_userVideos.length - knownIds.length) + ' video', 'success');
      if (btn) { btn.classList.add('hidden'); btn.style.display = 'none'; }
      if (statusEl) {
        const total = _userAwemeCount > 0 ? _userAwemeCount : _userVideos.length;
        statusEl.textContent = _userVideos.length + '/' + total + ' video';
        if (_userVideos.length >= total) statusEl.style.color = '';
      }
    } else if (!lastError) {
      toast('Không có video mới được thêm', 'warning');
    }
    _renderVideos();
    if (_viEnabled) _translateVisibleDebounced(1000);
  } catch (e) {
    toast('Lỗi tải video: ' + e.message, 'error');
  } finally {
    _isLoadingVideos = false;
    if (btn) {
      btn.disabled = false;
      if (!btn.classList.contains('hidden')) btn.textContent = originalBtnText || 'Tải đủ video (qua trình duyệt)';
    }
  }
}

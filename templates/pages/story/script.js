/* ─────────────────────────────────────────────────────────────────────────
 * Truyện → Video — MangaDex search + AI narration + Ken Burns video render.
 *
 * Workflow (matches templates/components/page_story.html):
 *   1. Pick a source (mangadex | urls | comic | text).
 *   2. For MangaDex: search → select manga → pick chapter → load pages.
 *   3. Build per-panel narration (split a single text or per-panel manual).
 *   4. Render: TTS each panel + Ken Burns clip + ASS/SRT subtitles.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  let _comicToken = '';
  let _selectedManga = null;
  let _selectedChapter = null;
  let _chapters = [];
  let _panels = [];          // [{image_url, text}]
  let _ttsEngines = [];
  let _renderPoll = null;
  let _renderCtx = null;     // {video_name, srt_name, ass_name}
  let _activeCatalog = 'nettruyen';   // 'nettruyen' | 'mangadex'

  // ── DOM helpers ────────────────────────────────────────────────────────
  function _el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'style') e.style.cssText = attrs[k];
      else if (k === 'onclick') e.addEventListener('click', attrs[k]);
      else if (k === 'disabled') { if (attrs[k]) e.disabled = true; }  // only set if truthy
      else if (k === 'checked')  { if (attrs[k]) e.checked  = true; }
      else e.setAttribute(k, attrs[k]);
    }
    for (const c of kids) if (c != null) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    return e;
  }
  function _toast(m, k) { (window.toast || console.log)(m, k || 'info'); }
  function _log(msg, level) {
    if (typeof window.appendLog === 'function') {
      window.appendLog('sw-log', msg, level || 'info');
    } else {
      console.log('[story]', msg);
    }
  }
  function _proxiedImg(url) {
    if (!url) return '';
    if (url.startsWith('/')) return url;
    return '/api/story/manga/image_proxy?url=' + encodeURIComponent(url);
  }

  // ── 1. Source switching ───────────────────────────────────────────────
  function switchSource(name) {
    document.querySelectorAll('#page-story .platform-tab').forEach(el => {
      el.classList.toggle('active', el.dataset.source === name);
    });
    document.querySelectorAll('#page-story .story-source').forEach(el => {
      el.classList.toggle('hidden', el.dataset.source !== name);
    });
  }

  // ── Language pills (replaces <select multiple>) ───────────────────────
  function _activeLangs() {
    return Array.from(document.querySelectorAll('#md-lang .lang-pill.active'))
      .map(p => p.dataset.code)
      .filter(Boolean);
  }
  function _initLangPills() {
    const wrap = document.getElementById('md-lang');
    if (!wrap || wrap._wired) return;
    wrap._wired = true;
    wrap.addEventListener('click', (e) => {
      const pill = e.target.closest('.lang-pill');
      if (!pill) return;
      pill.classList.toggle('active');
      // Always keep at least one language picked
      if (!_activeLangs().length) pill.classList.add('active');
    });
  }

  // ── Catalog switching (NetTruyen ↔ MangaDex) ─────────────────────────
  function catalogSwitch(name) {
    _activeCatalog = name;
    document.querySelectorAll('#page-story .catalog-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.catalog === name);
    });
    document.querySelectorAll('#page-story .catalog-pane').forEach(p => {
      p.classList.toggle('hidden', p.dataset.catalog !== name);
    });
  }

  // ── 1A. Multi-source manga search ────────────────────────────────────
  // Map source id → human label + colour
  const _SRC_INFO = {
    mangaplus:  { label: 'MangaPlus', colour: 'badge-accent' },
    nettruyen:  { label: 'NetTruyen',  colour: 'badge-blue' },
    truyenqq:   { label: 'TruyenQQ',   colour: 'badge-green' },
    blogtruyen: { label: 'BlogTruyen', colour: 'badge-yellow' },
    comick:     { label: 'Comick',     colour: 'badge-accent' },
    bato:       { label: 'Bato.to',    colour: 'badge-red' },
    mangadex:   { label: 'MangaDex',   colour: 'badge-gray' },
  };

  // ── Source pills (legacy multi-source UI — kept for compatibility) ───
  function _activeSources() {
    return Array.from(document.querySelectorAll('#mc-sources .lang-pill.active'))
      .map(p => p.dataset.src)
      .filter(Boolean);
  }
  function _initSourcePills() {
    const wrap = document.getElementById('mc-sources');
    if (!wrap || wrap._wired) return;
    wrap._wired = true;
    wrap.addEventListener('click', (e) => {
      const pill = e.target.closest('.lang-pill');
      if (!pill) return;
      pill.classList.toggle('active');
      if (!_activeSources().length) pill.classList.add('active');
    });
  }

  // ── MangaPlus-only search ─────────────────────────────────────────────
  async function multiSearch() {
    const q = (document.getElementById('mc-query').value || '').trim();
    const meta = document.getElementById('mc-search-meta');
    const wrap = document.getElementById('mc-results');
    if (!q) return _toast('Nhập tên truyện trước.', 'warning');
    meta.textContent = 'Đang tìm trên MangaPlus...';
    wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Đang tải...'));
    try {
      const r = await API.post('/api/story/mangaplus/search', {
        keyword: q, limit: 30,
      });
      meta.textContent = (r.count || 0) + ' kết quả · MangaPlus';
      _renderMultiResults(r.items || []);
    } catch (e) {
      meta.textContent = '';
      wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Lỗi: ' + (e.message || e)));
    }
  }

  function _renderMultiResults(items) {
    const wrap = document.getElementById('mc-results');
    wrap.replaceChildren();
    if (!items.length) {
      wrap.appendChild(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Không tìm thấy truyện phù hợp.'));
      return;
    }
    for (const m of items) {
      const src = m.source || 'mangaplus';
      const info = _SRC_INFO[src] || { label: src, colour: 'badge-accent' };
      const card = _el('div', {
        class: 'manga-card',
        style: 'position:relative',
        onclick: () => _multiSelectManga(m, card),
      });
      card.appendChild(_el('span', {
        class: 'badge ' + info.colour,
        style: 'position:absolute;top:6px;right:6px;font-size:10px;z-index:1',
      }, info.label));
      const img = _el('img', {
        class: 'manga-thumb',
        src: m.cover_url ? _proxiedImg(m.cover_url) : '',
        alt: '', loading: 'lazy',
      });
      img.onerror = () => { img.style.display = 'none'; };
      card.appendChild(img);
      card.appendChild(_el('div', { class: 'manga-title' }, m.title || '(không tiêu đề)'));
      const sub = [];
      if (m.authors && m.authors.length) sub.push(m.authors.join(', '));
      if (m.language && m.language !== 'ENGLISH') sub.push(m.language);
      card.appendChild(_el('div', { class: 'manga-meta' }, sub.join(' · ') || '—'));
      wrap.appendChild(card);
    }
  }

  async function _multiSelectManga(manga, cardEl) {
    document.querySelectorAll('#mc-results .manga-card.selected').forEach(c => c.classList.remove('selected'));
    if (cardEl) cardEl.classList.add('selected');
    LoadingUI.start && LoadingUI.start('Đang tải danh sách chương MangaPlus...');
    try {
      const r = await API.post('/api/story/mangaplus/details', { manga_id: manga.id });
      if (!r.ok) throw new Error(r.error || 'fetch failed');
      _selectedManga = {
        ...(r.manga || manga),
        _kind: 'mangaplus',
        _languages: r.languages || [],
        _paywalledCount: r.paywalled_count || 0,
        _hasPaywall: !!r.has_paywall,
      };
      _selectedChapter = null;
      _chapters = (r.chapters || []).map(ch => ({
        id: ch.id, chapter: ch.chapter, title: ch.title,
        language: ch.language || 'ENGLISH',
        pages: ch.pages || 0,
        publish_at: ch.publish_at || '',
        scanlation_group: 'MangaPlus',
        is_external: false, external_url: '',
      }));
      _renderNtChapterCard();
      // Banner: explain the paywall + offer language switcher
      _renderMangaPlusBanner();
      document.getElementById('md-detail-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      _toast('Lỗi: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // Render the MangaPlus paywall + language-switcher banner.
  function _renderMangaPlusBanner() {
    const banner = document.getElementById('md-chapter-banner');
    if (!banner) return;
    const m = _selectedManga;
    const langs = (m?._languages || []).filter(l => !l.is_current);
    let html = '';
    if (m?._hasPaywall && m._paywalledCount > 0) {
      html += `<strong>ℹ MangaPlus chỉ cho miễn phí ${(_chapters || []).length} chương đầu/cuối.</strong> `;
      html += `Khoảng ${m._paywalledCount} chương ở giữa thuộc paywall (chỉ đọc được trong app MangaPlus với account login, không lấy được qua API).`;
    } else if ((_chapters || []).length === 0) {
      html += '<strong>Không có chương miễn phí nào.</strong>';
    } else {
      html += `<strong>${(_chapters || []).length} chương miễn phí.</strong> Click chương để load ảnh.`;
    }
    if (langs.length) {
      html += '<br><span style="margin-right:6px">Đổi ngôn ngữ:</span>';
      for (const lng of langs) {
        const label = (lng.language || '').replace(/_/g, ' ').toLowerCase();
        const labelTitle = label.replace(/\b\w/g, c => c.toUpperCase());
        html += `<button class="btn btn-secondary btn-sm" type="button"
                          onclick="storyMangaPlusSwitchLang('${lng.id}')"
                          style="margin:2px 4px 2px 0;font-size:11px;padding:2px 8px">${labelTitle}</button>`;
      }
    }
    banner.classList.remove('hidden');
    banner.innerHTML = html;
  }

  async function mangaPlusSwitchLang(titleId) {
    if (!titleId) return;
    LoadingUI.start && LoadingUI.start('Đang đổi ngôn ngữ...');
    try {
      const r = await API.post('/api/story/mangaplus/details', { manga_id: titleId });
      if (!r.ok) throw new Error(r.error || 'fetch failed');
      _selectedManga = {
        ...(r.manga || {}),
        _kind: 'mangaplus',
        _languages: r.languages || [],
        _paywalledCount: r.paywalled_count || 0,
        _hasPaywall: !!r.has_paywall,
      };
      _selectedChapter = null;
      _chapters = (r.chapters || []).map(ch => ({
        id: ch.id, chapter: ch.chapter, title: ch.title,
        language: ch.language || 'ENGLISH',
        pages: ch.pages || 0,
        publish_at: ch.publish_at || '',
        scanlation_group: 'MangaPlus',
        is_external: false, external_url: '',
      }));
      _renderNtChapterCard();
      _renderMangaPlusBanner();
    } catch (e) {
      _toast('Lỗi: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── 1A-1. NetTruyen search ────────────────────────────────────────────
  async function ntSearch() {
    const q = (document.getElementById('nt-query').value || '').trim();
    const meta = document.getElementById('nt-search-meta');
    const wrap = document.getElementById('nt-results');
    if (!q) return _toast('Nhập tên truyện trước.', 'warning');
    meta.textContent = 'Đang tìm...';
    wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Đang tải...'));
    try {
      const r = await API.post('/api/story/nettruyen/search', { keyword: q });
      meta.textContent = (r.count || 0) + ' kết quả · NetTruyen';
      _renderNtResults(r.items || []);
    } catch (e) {
      meta.textContent = '';
      wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Lỗi: ' + (e.message || e)));
    }
  }

  function _renderNtResults(items) {
    const wrap = document.getElementById('nt-results');
    wrap.replaceChildren();
    if (!items.length) {
      wrap.appendChild(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Không tìm thấy truyện phù hợp.'));
      return;
    }
    for (const m of items) {
      const card = _el('div', { class: 'manga-card', onclick: () => _ntSelectManga(m, card) });
      const img = _el('img', {
        class: 'manga-thumb',
        src: m.cover_url ? _proxiedImg(m.cover_url) : '',
        alt: '', loading: 'lazy',
      });
      img.onerror = () => { img.style.display = 'none'; };
      card.appendChild(img);
      card.appendChild(_el('div', { class: 'manga-title' }, m.title || ''));
      const sub = [];
      if (m.chapter_latest) sub.push(m.chapter_latest);
      card.appendChild(_el('div', { class: 'manga-meta' }, sub.join(' · ') || '—'));
      wrap.appendChild(card);
    }
  }

  async function _ntSelectManga(manga, cardEl) {
    document.querySelectorAll('#nt-results .manga-card.selected').forEach(c => c.classList.remove('selected'));
    if (cardEl) cardEl.classList.add('selected');
    LoadingUI.start && LoadingUI.start('Đang tải danh sách chương...');
    try {
      const r = await API.post('/api/story/nettruyen/details', { manga_id: manga.id });
      if (!r.ok) throw new Error(r.error || 'fetch failed');
      // Adapt to the same shape mangadex selectManga produces.
      _selectedManga = {
        ...r.manga,
        title: r.manga.title || manga.title,
        _kind: 'nettruyen',
      };
      _selectedChapter = null;
      _chapters = (r.chapters || []).map(ch => ({
        id: ch.id,
        chapter: ch.chapter,
        title: ch.title,
        language: 'vi',
        pages: 0,
        publish_at: ch.publish_at,
        scanlation_group: 'NetTruyen',
        is_external: false,
        external_url: '',
      }));
      _renderNtChapterCard();
    } catch (e) {
      _toast('Lỗi: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  function _renderNtChapterCard() {
    if (_selectedManga) _renderDetailCard(_selectedManga);
    document.getElementById('md-chapters-card').classList.remove('hidden');
    // Hide "Ẩn ngoài" toggle — VN/Bato/Comick sources don't have external chapters
    document.getElementById('md-hide-external-wrap')?.classList.add('hidden');
    document.getElementById('md-chapters-title').textContent = '📚 ' + (_selectedManga?.title || '');
    const list = document.getElementById('md-chapter-list');
    const empty = document.getElementById('md-chapter-empty');
    const banner = document.getElementById('md-chapter-banner');
    list.replaceChildren();
    empty.classList.add('hidden');
    banner.classList.add('hidden');
    const order = document.getElementById('md-chapter-order').value || 'asc';
    const sorted = [..._chapters];
    // NetTruyen returns latest-first; honor user order pick
    if (order === 'asc') sorted.reverse();
    if (!sorted.length) {
      empty.textContent = 'Truyện này chưa có chương.';
      empty.classList.remove('hidden');
      return;
    }
    for (const ch of sorted) {
      _renderNtChapterRow(ch, list);
    }
  }

  // Map full language names → short codes (Shueisha returns "VIETNAMESE" etc.)
  const _LANG_SHORT = {
    ENGLISH: 'EN', VIETNAMESE: 'VI', SPANISH: 'ES', FRENCH: 'FR',
    GERMAN: 'DE', PORTUGUESE_BR: 'PT', INDONESIAN: 'ID', THAI: 'TH',
    JAPANESE: 'JP', CHINESE: 'ZH', KOREAN: 'KO', ITALIAN: 'IT', RUSSIAN: 'RU',
  };
  function _shortLang(s) {
    if (!s) return '—';
    const v = String(s).toUpperCase().replace(/[\s_-]/g, '_');
    return _LANG_SHORT[v] || v.slice(0, 2) || '—';
  }
  function _renderNtChapterRow(ch, list) {
    const row = _el('div', { class: 'chapter-row' });
    row.addEventListener('click', () => _selectChapterAuto(ch, row));
    row.appendChild(_el('span', null, ch.chapter || '—'));
    row.appendChild(_el('span', null, ch.title || '(không tiêu đề)'));
    row.appendChild(_el('span', null, _shortLang(ch.language)));
    row.appendChild(_el('span', null, ch.pages ? String(ch.pages) : '—'));
    row.appendChild(_el('span', { class: 'text-xs text-muted' }, ch.scanlation_group || ch.publish_at || '—'));
    list.appendChild(row);
  }

  // Dispatch chapter selection: NetTruyen URLs go to extractor route,
  // MangaDex/Cubari ids stay on the legacy /chapter_pages endpoint.
  function _selectChapterAuto(ch, rowEl) {
    const kind = _selectedManga?._kind;
    if (kind === 'mangaplus') return _mangaPlusSelectChapterById(ch, rowEl);
    if (kind === 'nettruyen') return _ntSelectChapter(ch, rowEl);
    if (kind === 'truyenqq' || kind === 'blogtruyen') return _vnSelectChapter(ch, rowEl);
    if (kind === 'bato') return _batoSelectChapter(ch, rowEl);
    return selectChapter(ch, rowEl);
  }

  async function _mangaPlusSelectChapterById(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải ảnh chương MangaPlus...');
    try {
      const r = await API.post('/api/story/mangaplus/chapter_pages_id', {
        chapter_id: ch.id, quality: 'high',
      });
      if (!r.ok) throw new Error(r.error || 'load pages failed');
      const pages = r.pages || [];
      if (!pages.length) return _toast('Chương này không có ảnh.', 'warning');
      setPanels(pages.map(u => ({ image_url: u, text: '' })));
      _toast('Đã tải ' + pages.length + ' trang.', 'success');
    } catch (e) {
      _toast('MangaPlus lỗi: ' + (e.message || e) + ' — chương có thể trả phí.', 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  async function _vnSelectChapter(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải các trang truyện...');
    try {
      const r = await API.post('/api/story/vn/chapter_pages', { url: ch.id });
      if (!r.ok) throw new Error(r.error || 'load pages failed');
      const pages = r.pages || [];
      if (!pages.length) return _toast('Chương này không có trang ảnh.', 'warning');
      setPanels(pages.map(u => ({ image_url: u, text: '' })));
      _toast('Đã tải ' + pages.length + ' trang.', 'success');
    } catch (e) { _toast('Lỗi tải pages: ' + (e.message || e), 'error'); }
    finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  async function _batoSelectChapter(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải các trang truyện...');
    try {
      const r = await API.post('/api/story/bato/chapter_pages', { chapter_id: ch.id });
      if (!r.ok) throw new Error(r.error || 'load pages failed');
      const pages = r.pages || [];
      if (!pages.length) return _toast('Chương này không có trang ảnh.', 'warning');
      setPanels(pages.map(u => ({ image_url: u, text: '' })));
      _toast('Đã tải ' + pages.length + ' trang.', 'success');
    } catch (e) { _toast('Lỗi tải pages: ' + (e.message || e), 'error'); }
    finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // MangaPlus chapter selected from the chapter list (external on MangaDex)
  async function _mangaPlusSelectChapter(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải chương MangaPlus...');
    try {
      const r = await API.post('/api/story/mangaplus/chapter_pages', {
        url: ch.external_url, quality: 'high',
      });
      if (!r.ok) throw new Error(r.error || 'load pages failed');
      const pages = r.pages || [];
      if (!pages.length) return _toast('Chương này không có ảnh.', 'warning');
      setPanels(pages.map(u => ({ image_url: u, text: '' })));
      _toast('Đã tải ' + pages.length + ' trang từ MangaPlus.', 'success');
    } catch (e) {
      _toast('MangaPlus lỗi: ' + (e.message || e) + ' — có thể chương này không miễn phí.', 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  async function _ntSelectChapter(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải các trang truyện...');
    try {
      const r = await API.post('/api/story/nettruyen/chapter_pages', { chapter_id: ch.id });
      if (!r.ok) throw new Error(r.error || 'load pages failed');
      const pages = r.pages || [];
      if (!pages.length) { _toast('Chương này không có trang ảnh.', 'warning'); return; }
      setPanels(pages.map(url => ({ image_url: url, text: '' })));
      const titleHint = (_selectedManga?.title || '') +
        (ch.chapter ? ' — Chương ' + ch.chapter : '') +
        (ch.title ? ': ' + ch.title : '');
      _toast('Đã tải ' + pages.length + ' trang. Sang phần "Panels & lời đọc" để biên tập.', 'success');
      const tt = document.getElementById('sw-title-render');
      if (tt) tt.value = titleHint;
    } catch (e) {
      _toast('Lỗi tải pages: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── MangaDex search ───────────────────────────────────────────────────
  async function mangaSearch() {
    const q = (document.getElementById('md-query').value || '').trim();
    const meta = document.getElementById('md-search-meta');
    const wrap = document.getElementById('md-results');
    if (!q) return _toast('Nhập tên truyện trước.', 'warning');
    const langs = _activeLangs();
    if (!langs.length) return _toast('Chọn ít nhất một ngôn ngữ.', 'warning');
    const ratings = (document.getElementById('md-rating').value || 'safe,suggestive').split(',');
    meta.textContent = 'Đang tìm...';
    wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Đang tải...'));
    try {
      const r = await API.post('/api/story/manga/search', {
        title: q, languages: langs, ratings, limit: 24,
      });
      meta.textContent = (r.count || 0) + ' kết quả · MangaDex';
      renderMangaResults(r.items || []);
    } catch (e) {
      meta.textContent = '';
      wrap.replaceChildren(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Lỗi: ' + (e.message || e)));
    }
  }

  // ── 1B. Smart chapter URL extractor ──────────────────────────────────
  async function extractChapter() {
    const url = (document.getElementById('sw-chapter-url').value || '').trim();
    const meta = document.getElementById('sw-chapter-extract-meta');
    if (!url) return _toast('Dán URL chương trước.', 'warning');
    meta.textContent = 'Đang tải HTML và rút ảnh...';
    try {
      LoadingUI.start && LoadingUI.start('Đang đọc trang truyện...');
      const r = await API.post('/api/story/manga/extract_chapter', { url });
      if (!r.ok) throw new Error(r.error || 'extract failed');
      const pages = r.pages || [];
      meta.textContent = `✓ ${r.label} — ${pages.length} trang${r.title ? ' — ' + r.title : ''}`;
      if (!pages.length) return _toast('Không tìm được ảnh nào trong trang.', 'warning');
      setPanels(pages.map(u => ({ image_url: u, text: '' })));
      // Pre-fill render title from page <title>
      _selectedManga = { title: r.title || r.label };
      _selectedChapter = null;
      _toast('Đã rút ' + pages.length + ' trang. Sang phần "Panels & lời đọc" để biên tập.', 'success');
    } catch (e) {
      meta.textContent = '';
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  function renderMangaResults(items) {
    const wrap = document.getElementById('md-results');
    wrap.replaceChildren();
    if (!items.length) {
      wrap.appendChild(_el('div', { class: 'empty-state', style: 'grid-column:1/-1' }, 'Không tìm thấy manga phù hợp.'));
      return;
    }
    for (const m of items) {
      const card = _el('div', { class: 'manga-card', onclick: () => selectManga(m, card) });
      const img = _el('img', {
        class: 'manga-thumb',
        src: m.cover_url ? _proxiedImg(m.cover_url) : '',
        alt: '',
        loading: 'lazy',
      });
      img.onerror = () => { img.style.display = 'none'; };
      card.appendChild(img);
      card.appendChild(_el('div', { class: 'manga-title' }, m.title || '(không có tiêu đề)'));
      const meta = [];
      if (m.year) meta.push(String(m.year));
      if (m.status) meta.push(m.status);
      if (m.content_rating && m.content_rating !== 'safe') meta.push(m.content_rating);
      card.appendChild(_el('div', { class: 'manga-meta' }, meta.join(' · ') || '—'));
      wrap.appendChild(card);
    }
  }

  // ── Render the manga detail card (cover + meta + description) ────────
  function _renderDetailCard(manga) {
    const card = document.getElementById('md-detail-card');
    const titleEl = document.getElementById('md-detail-title');
    const body = document.getElementById('md-detail-body');
    const linkEl = document.getElementById('md-detail-source-link');
    if (!card || !body) return;

    card.classList.remove('hidden');
    titleEl.textContent = '📘 ' + (manga?.title || 'Chi tiết truyện');
    body.replaceChildren();

    // Cover
    const left = _el('div');
    const cover = manga?.cover_url || '';
    if (cover) {
      const img = _el('img', {
        class: 'detail-cover',
        src: _proxiedImg(cover),
        alt: manga?.title || '', loading: 'lazy',
      });
      img.onerror = () => { img.style.display = 'none'; };
      left.appendChild(img);
    } else {
      left.appendChild(_el('div', {
        class: 'detail-cover',
        style: 'display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:36px',
      }, '📘'));
    }

    // Right column: source badge + metadata + description
    const right = _el('div');
    const src = manga?.source || manga?._kind || '';
    if (src) {
      const info = _SRC_INFO[src] || { label: src, colour: 'badge-gray' };
      right.appendChild(_el('div', { style: 'margin-bottom:8px' },
        _el('span', { class: 'badge ' + info.colour }, '🌐 ' + info.label),
      ));
    }

    const metaRows = [
      ['Tiêu đề khác', manga?.alt_title],
      ['Năm', manga?.year],
      ['Tình trạng', manga?.status],
      ['Tác giả', (manga?.authors || []).join(', ')],
      ['Ngôn ngữ', (manga?.available_languages || []).slice(0, 8).join(', ')],
      ['Chương mới', manga?.chapter_latest],
    ];
    for (const [k, v] of metaRows) {
      if (!v) continue;
      const row = _el('div', { class: 'detail-meta-row' },
        _el('span', { class: 'detail-meta-key' }, k + ':'),
        _el('span', null, String(v)),
      );
      right.appendChild(row);
    }

    const tags = manga?.tags || manga?.genres || [];
    if (tags.length) {
      const tagsWrap = _el('div', { class: 'detail-tags' });
      for (const t of tags.slice(0, 16)) {
        if (t) tagsWrap.appendChild(_el('span', { class: 'detail-tag' }, t));
      }
      right.appendChild(tagsWrap);
    }

    const desc = (manga?.description || '').trim();
    if (desc) {
      right.appendChild(_el('div', { class: 'detail-desc' }, desc));
    }

    body.appendChild(left);
    body.appendChild(right);

    // External "Mở trang gốc" link (NetTruyen / TruyenQQ / Bato have a direct URL)
    const linkUrl = manga?.url || (typeof manga?.id === 'string' && manga.id.startsWith('http') ? manga.id : '');
    if (linkUrl) {
      linkEl.href = linkUrl;
      linkEl.classList.remove('hidden');
    } else {
      linkEl.classList.add('hidden');
      linkEl.removeAttribute('href');
    }
  }

  function _hideDetailCard() {
    document.getElementById('md-detail-card')?.classList.add('hidden');
  }

  async function selectManga(manga, cardEl) {
    document.querySelectorAll('#md-results .manga-card.selected').forEach(c => c.classList.remove('selected'));
    if (cardEl) cardEl.classList.add('selected');
    _selectedManga = manga;
    _selectedChapter = null;
    _renderDetailCard(manga);
    document.getElementById('md-chapters-card').classList.remove('hidden');
    // Show "Ẩn ngoài" toggle (only MangaDex/Comick may return external chapters)
    document.getElementById('md-hide-external-wrap')?.classList.remove('hidden');
    document.getElementById('md-chapters-title').textContent = '📚 ' + (manga.title || '');
    await loadChapters();
    document.getElementById('md-detail-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadChapters() {
    if (!_selectedManga) return;
    const langs = _activeLangs();
    const order = document.getElementById('md-chapter-order').value || 'asc';
    const hideExternal = document.getElementById('md-hide-external').checked;
    const list = document.getElementById('md-chapter-list');
    const empty = document.getElementById('md-chapter-empty');
    const banner = document.getElementById('md-chapter-banner');
    list.replaceChildren(_el('div', { class: 'empty-state' }, 'Đang tải danh sách chương...'));
    empty.classList.add('hidden');
    banner.classList.add('hidden');
    try {
      const r = await API.post('/api/story/manga/chapters', {
        manga_id: _selectedManga.id, languages: langs, order_dir: order,
      });
      _chapters = r.chapters || [];
      list.replaceChildren();

      const externalCount = _chapters.filter(c => c.is_external || c.external_url).length;
      const localCount = _chapters.length - externalCount;

      // Friendly banner when almost everything is external (e.g. One Piece)
      if (_chapters.length && localCount === 0) {
        banner.classList.remove('hidden');
        banner.style.borderColor = '#f59e0b';
        banner.innerHTML =
          '<strong>⚠ Manga này chỉ có chương phát hành chính thức.</strong> ' +
          'MangaDex không host ảnh cho One Piece, Naruto, Bleach, Jujutsu Kaisen, Chainsaw Man, ' +
          'Spy x Family, ... vì các nhà phát hành (MangaPlus, Comikey, Azuki) giữ bản quyền. ' +
          '<br>Hãy thử:'
          + '<ul style="margin:6px 0 0 18px;padding:0">'
          +   '<li>Chọn manga fan-translated khác (Solo Leveling, Tonari no Seki-kun, manhua/manhwa).</li>'
          +   '<li>Hoặc dùng tab <strong>🔗 Danh sách URL ảnh</strong> nếu bạn có sẵn link ảnh.</li>'
          +   '<li>Hoặc dùng tab <strong>🗂 Upload ZIP</strong> để tải file truyện local.</li>'
          + '</ul>';
      } else if (externalCount > 0 && localCount > 0) {
        banner.classList.remove('hidden');
        banner.style.borderColor = '';
        banner.innerHTML = `ℹ ${externalCount}/${_chapters.length} chương được phát hành chính thức ở dịch vụ khác — đã ${hideExternal ? 'ẩn' : 'mờ đi'}. ${localCount} chương khả dụng.`;
      }

      // Filter
      const visible = hideExternal
        ? _chapters.filter(c => !(c.is_external || c.external_url))
        : _chapters;

      if (!visible.length) {
        empty.classList.remove('hidden');
        if (hideExternal && externalCount > 0) {
          empty.textContent = 'Tất cả chương đều thuộc nhà phát hành chính thức. Bỏ tick "Ẩn chương ngoài" để xem link, hoặc chọn manga khác.';
        } else {
          empty.textContent = 'Manga này chưa có chương dịch trong các ngôn ngữ đã chọn.';
        }
        return;
      }

      for (const ch of visible) {
        const isExt = !!(ch.is_external || ch.external_url);
        const extUrl = ch.external_url || '';
        const isMangaPlus = /mangaplus\.shueisha\.co\.jp\/viewer\/\d+/i.test(extUrl);
        const row = _el('div', {
          class: 'chapter-row' + (isExt ? ' chapter-external' : ''),
          title: isExt
            ? (isMangaPlus
                ? 'Chương MangaPlus — bấm để load ảnh vào tool'
                : 'Chương ngoài — bấm để mở ' + (extUrl || ''))
            : '',
        });
        row.addEventListener('click', () => {
          if (!isExt) return selectChapter(ch, row);
          if (isMangaPlus) return _mangaPlusSelectChapter(ch, row);
          if (extUrl) {
            // Other licensors (Comikey, Azuki, ...) — open in new tab
            window.open(extUrl, '_blank', 'noopener');
          } else {
            _toast('Chương ngoài — không có URL.', 'warning');
          }
        });
        row.appendChild(_el('span', null, ch.chapter || '—'));
        // Friendlier label: ⬇ for MangaPlus (we can fetch), 🔗 for purely external
        const labelSuffix = isExt
          ? (isMangaPlus ? ' ⬇ MangaPlus' : ' 🔗')
          : '';
        row.appendChild(_el('span', null, (ch.title || '(không tiêu đề)') + labelSuffix));
        row.appendChild(_el('span', null, (ch.language || '').toUpperCase()));
        row.appendChild(_el('span', null, isExt
          ? (isMangaPlus ? 'MangaPlus' : 'ngoài')
          : String(ch.pages || 0)));
        row.appendChild(_el('span', { class: 'text-xs text-muted' }, ch.scanlation_group || '—'));
        list.appendChild(row);
      }
    } catch (e) {
      list.replaceChildren(_el('div', { class: 'empty-state' }, 'Lỗi: ' + (e.message || e)));
    }
  }

  function reloadChapters() { return loadChapters(); }

  function clearMangaSelection() {
    _selectedManga = null;
    _selectedChapter = null;
    _chapters = [];
    _hideDetailCard();
    document.getElementById('md-chapters-card').classList.add('hidden');
    document.querySelectorAll('#md-results .manga-card.selected').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll('#mc-results .manga-card.selected').forEach(c => c.classList.remove('selected'));
    setPanels([]);
  }

  async function selectChapter(ch, rowEl) {
    document.querySelectorAll('#md-chapter-list .chapter-row.selected').forEach(r => r.classList.remove('selected'));
    if (rowEl) rowEl.classList.add('selected');
    _selectedChapter = ch;
    LoadingUI.start && LoadingUI.start('Đang tải các trang truyện...');
    try {
      const r = await API.post('/api/story/manga/chapter_pages', {
        chapter_id: ch.id, saver: false,
      });
      const pages = r.pages_full || r.pages || [];
      if (!pages.length) {
        _toast('Chương này không có trang ảnh.', 'warning');
        return;
      }
      // Initialize panels with empty texts.
      setPanels(pages.map(url => ({ image_url: url, text: '' })));
      // Default title text = chapter label
      const titleHint = (_selectedManga?.title || '') +
        (ch.chapter ? ' — Chương ' + ch.chapter : '') +
        (ch.title ? ': ' + ch.title : '');
      _toast('Đã tải ' + pages.length + ' trang. Sang phần "Panels & lời đọc" để biên tập.', 'success');
      // Pre-fill the title input on the render card if present
      const tt = document.getElementById('sw-title-render');
      if (tt) tt.value = titleHint;
    } catch (e) {
      _toast('Lỗi tải pages: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── 1B. URL list source ────────────────────────────────────────────────
  function urlsLoad() {
    const text = (document.getElementById('sw-url-list').value || '').trim();
    const status = document.getElementById('sw-urls-status');
    const urls = text.split('\n').map(s => s.trim()).filter(s => s.startsWith('http://') || s.startsWith('https://'));
    if (!urls.length) {
      status.textContent = 'Không có URL hợp lệ.';
      return _toast('Cần ít nhất một URL hợp lệ.', 'warning');
    }
    setPanels(urls.map(u => ({ image_url: u, text: '' })));
    status.textContent = 'Đã nạp ' + urls.length + ' URL.';
    _toast('Nạp thành công ' + urls.length + ' panel. Mở phần "Panels & lời đọc" để biên tập.', 'success');
  }

  // ── 1C. ZIP upload + OCR (kept for legacy) ────────────────────────────
  async function comicUpload() {
    const f = document.getElementById('sw-comic-file').files[0];
    if (!f) return _toast('Chọn file ZIP.', 'warning');
    const status = document.getElementById('sw-comic-status');
    status.textContent = 'Đang tải lên...';
    const fd = new FormData(); fd.append('file', f);
    try {
      LoadingUI.start && LoadingUI.start('Đang upload zip...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
      const r = await fetch('/api/story/comic_upload', { method: 'POST', body: fd, headers })
        .then(r => r.json());
      if (!r.ok) throw new Error(r.error || 'upload failed');
      _comicToken = r.token;
      status.textContent = 'OK — ' + r.image_count + ' ảnh';
    } catch (e) {
      status.textContent = 'Lỗi: ' + (e.message || e);
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  async function comicOcr() {
    if (!_comicToken) return _toast('Hãy upload zip trước.', 'warning');
    const lang = document.getElementById('sw-comic-lang').value;
    const provider = document.getElementById('sw-comic-ocr-provider')?.value || 'tesseract';
    const visionModel = document.getElementById('sw-comic-vision-model')?.value?.trim() || '';
    const status = document.getElementById('sw-comic-ocr-status');
    if (status) status.textContent = '⏳ Đang OCR (' + provider + ')...';
    try {
      const r = await API.post('/api/story/comic_ocr', {
        token: _comicToken, lang, provider, vision_model: visionModel,
      });
      document.getElementById('sw-comic-text').value = r.text || '';
      const used = r.provider_used || provider;
      const fb = r.fallback ? ' (fallback)' : '';
      _toast('OCR xong: ' + (r.char_count || 0) + ' ký tự · ' + used + fb, 'success');
      if (status) status.textContent = '✓ ' + (r.char_count || 0) + ' ký tự · provider: ' + used + fb;
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  // ── 3. Panel editor ──────────────────────────────────────────────────
  function setPanels(panels) {
    _panels = panels.map(p => ({ image_url: p.image_url, text: p.text || '' }));
    renderPanels();
    document.getElementById('sw-panels-card').classList.toggle('hidden', _panels.length === 0);
    document.getElementById('sw-render-card').classList.toggle('hidden', _panels.length === 0);
  }

  function renderPanels() {
    const wrap = document.getElementById('sw-panels');
    const meta = document.getElementById('sw-panels-meta');
    if (!wrap || !meta) return;
    wrap.replaceChildren();
    meta.textContent = _panels.length + ' panel · ~' + Math.round(_panels.reduce((s, p) => s + Math.max(2.5, (p.text || '').length / 12), 0)) + ' giây';
    _panels.forEach((p, idx) => {
      const row = _el('div', { class: 'panel-row' });
      const img = _el('img', {
        class: 'panel-thumb',
        src: p.image_url ? _proxiedImg(p.image_url) : '',
        alt: 'panel ' + (idx + 1),
        loading: 'lazy',
      });
      img.onerror = () => { img.style.background = '#222'; img.removeAttribute('src'); };
      const right = _el('div');
      const head = _el('div', { style: 'display:flex;justify-content:space-between;align-items:center;margin-bottom:4px' },
        _el('span', { class: 'badge badge-accent' }, '#' + (idx + 1)),
        _el('div', { class: 'btn-group' },
          _el('button', {
            class: 'btn btn-secondary btn-sm',
            type: 'button',
            onclick: () => panelMove(idx, -1),
            title: 'Lên',
          }, '▲'),
          _el('button', {
            class: 'btn btn-secondary btn-sm',
            type: 'button',
            onclick: () => panelMove(idx, 1),
            title: 'Xuống',
          }, '▼'),
          _el('button', {
            class: 'btn btn-secondary btn-sm',
            type: 'button',
            onclick: () => panelDelete(idx),
            title: 'Xóa',
          }, '✕'),
        ),
      );
      const ta = _el('textarea', {
        class: 'panel-text',
        rows: '3',
        placeholder: 'Lời đọc / lời thoại cho panel ' + (idx + 1) + '... (để trống = panel im lặng)',
      });
      ta.value = p.text || '';
      ta.addEventListener('input', () => { _panels[idx].text = ta.value; });
      right.appendChild(head);
      right.appendChild(ta);
      row.appendChild(img);
      row.appendChild(right);
      wrap.appendChild(row);
    });
  }

  function panelMove(idx, delta) {
    const j = idx + delta;
    if (j < 0 || j >= _panels.length) return;
    const tmp = _panels[idx]; _panels[idx] = _panels[j]; _panels[j] = tmp;
    renderPanels();
  }
  function panelDelete(idx) {
    _panels.splice(idx, 1);
    renderPanels();
  }
  function panelsClearTexts() {
    _panels.forEach(p => p.text = '');
    renderPanels();
    _toast('Đã xoá lời đọc của tất cả panel.', 'info');
  }
  function panelsReverse() {
    _panels.reverse();
    renderPanels();
  }

  // ── Tải ảnh về máy (ZIP) ─────────────────────────────────────────────
  async function downloadZip() {
    if (!_panels.length) return _toast('Chưa có panel nào để tải.', 'warning');
    const title = _selectedManga?.title
      ? _selectedManga.title + (_selectedChapter?.chapter ? ' — Ch ' + _selectedChapter.chapter : '')
      : 'manga_chapter';
    try {
      LoadingUI.start && LoadingUI.start('Đang đóng gói ' + _panels.length + ' ảnh...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = decodeURIComponent(csrf);
      const resp = await fetch('/api/story/manga/download_zip', {
        method: 'POST', headers,
        body: JSON.stringify({
          title,
          pages: _panels.map(p => p.image_url),
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error('HTTP ' + resp.status + ' — ' + txt.slice(0, 120));
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const safeTitle = title.replace(/[\\/:*?"<>|]/g, '_').trim() || 'manga_chapter';
      a.href = url; a.download = safeTitle + '.zip';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      _toast('Đã tải ZIP ' + _panels.length + ' ảnh.', 'success');
    } catch (e) {
      _toast('Lỗi tải ZIP: ' + (e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── Build per-panel narration from active source ─────────────────────
  async function buildNarration() {
    if (!_panels.length) return _toast('Chưa có panel nào — chọn nguồn truyện trước.', 'warning');
    const mode = document.getElementById('sw-narration-mode').value || 'split';
    const targetLang = document.getElementById('sw-target-lang').value || 'vi';
    const translate = document.getElementById('sw-translate').checked;

    // Pick text source:
    //   - If "manual" mode: use whatever the user typed in each panel textarea.
    //   - Else: prefer active source's text (text > comic-ocr).
    const activeSource = document.querySelector('#page-story .platform-tab.active')?.dataset?.source || '';
    let bodyText = '';
    if (activeSource === 'text') bodyText = document.getElementById('sw-text').value || '';
    else if (activeSource === 'comic') bodyText = document.getElementById('sw-comic-text').value || '';

    const payload = {
      pages: _panels.map(p => p.image_url),
      mode,
      text: bodyText,
      panel_texts: mode === 'manual' ? _panels.map(p => p.text || '') : [],
      translate, target_lang: targetLang,
      provider: 'auto',
    };
    if (mode === 'split' && !bodyText.trim() && !translate) {
      return _toast('Nhập văn bản truyện trong tab "🤖 Tạo truyện AI" rồi thử lại, hoặc chuyển sang chế độ "Tự nhập từng panel".', 'warning');
    }
    try {
      LoadingUI.start && LoadingUI.start('Đang tạo lời đọc cho từng panel...');
      const r = await API.post('/api/story/manga/build_narration', payload);
      const next = (r.panels || []).map((p, i) => ({
        image_url: p.image_url || _panels[i]?.image_url || '',
        text: p.text || '',
      }));
      // Preserve any panels we had beyond what came back
      if (next.length === _panels.length) {
        _panels = next;
        renderPanels();
        _toast('Đã cập nhật lời đọc cho ' + next.length + ' panel.', 'success');
      } else {
        setPanels(next);
        _toast('Đã cập nhật lời đọc.', 'success');
      }
    } catch (e) {
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── 4. TTS engine + voice loading ─────────────────────────────────────
  async function loadVoices() {
    const engineSel = document.getElementById('sw-tts-engine');
    if (!engineSel) return;
    if (typeof _loadTtsEngineCatalog === 'function') { try { await _loadTtsEngineCatalog(); } catch (_) {} }
    try {
      const r = await fetch('/api/story/voices').then(r => r.json());
      _ttsEngines = r.engines || [];
      engineSel.replaceChildren();
      
      // Group engines by backend (local vs 9Router)
      const localEngines = _ttsEngines.filter(e => !e.backend || e.backend === 'local');
      const nineRouterEngines = _ttsEngines.filter(e => e.backend === '9router');
      
      // Add local engines first
      if (localEngines.length) {
        const localGroup = document.createElement('optgroup');
        localGroup.label = '🖥 Local (miễn phí)';
        for (const eng of localEngines) {
          localGroup.appendChild(_el('option', { value: eng.id }, eng.label));
        }
        engineSel.appendChild(localGroup);
      }
      
      // Add 9Router engines
      if (nineRouterEngines.length) {
        const nineGroup = document.createElement('optgroup');
        nineGroup.label = '🌐 9Router (premium)';
        for (const eng of nineRouterEngines) {
          nineGroup.appendChild(_el('option', { value: eng.id }, eng.label));
        }
        engineSel.appendChild(nineGroup);
      }
      
      // Default to edge-tts or first available
      engineSel.value = (_ttsEngines.find(e => e.id === 'edge-tts')?.id) || (_ttsEngines[0]?.id || 'edge-tts');
      engineSel.addEventListener('change', refreshVoices);
      const langSel = document.getElementById('sw-target-lang');
      if (langSel) langSel.addEventListener('change', refreshVoices);
      refreshVoices();
      
      _log(`🔊 Đã load ${_ttsEngines.length} TTS engines (${localEngines.length} local, ${nineRouterEngines.length} 9Router)`, 'detail');
    } catch (e) {
      _log(`❌ Lỗi load TTS engines: ${e.message}`, 'error');
    }
  }

  function refreshVoices() {
    // 9Router engine → shared Model + voice-id component handles everything.
    if (typeof _handle9RouterEngine === 'function'
        && _handle9RouterEngine('sw-tts-engine', 'sw-tts-voice')) {
      const rateField = document.getElementById('sw-tts-rate')?.closest('.field');
      const fptField = document.getElementById('sw-tts-fpt-speed')?.closest('.field');
      if (rateField) rateField.style.display = 'none';
      if (fptField) fptField.style.display = 'none';
      return;
    }
    const engineId = document.getElementById('sw-tts-engine')?.value || 'edge-tts';
    const lang = document.getElementById('sw-target-lang')?.value || 'vi';
    const voiceSel = document.getElementById('sw-tts-voice');
    if (!voiceSel) return;
    voiceSel.replaceChildren();

    const eng = _ttsEngines.find(e => e.id === engineId);
    if (!eng) {
      voiceSel.appendChild(_el('option', { value: '' }, '(không có)'));
      return;
    }
    const list = (eng.voices && eng.voices[lang]) || [];
    if (!list.length) {
      const fallbackLang = Object.keys(eng.voices || {})[0] || '';
      const fb = (eng.voices && eng.voices[fallbackLang]) || [];
      if (fb.length) {
        voiceSel.appendChild(_el('option', { value: '', disabled: 'disabled' },
          `⚠ Engine không hỗ trợ ${lang.toUpperCase()}, dùng ${fallbackLang.toUpperCase()}:`));
        for (const [code, label] of fb) {
          voiceSel.appendChild(_el('option', { value: code }, label));
        }
      } else {
        voiceSel.appendChild(_el('option', { value: '' }, '(không có giọng phù hợp)'));
      }
    } else {
      for (const [code, label] of list) {
        voiceSel.appendChild(_el('option', { value: code }, label));
      }
    }
    voiceSel.value = voiceSel.value || eng.default || (list[0] && list[0][0]) || '';

    const rateField = document.getElementById('sw-tts-rate')?.closest('.field');
    const fptField = document.getElementById('sw-tts-fpt-speed')?.closest('.field');
    if (rateField) rateField.style.display = (engineId === 'edge-tts') ? '' : 'none';
    if (fptField) fptField.style.display = (engineId === 'fpt-ai') ? '' : 'none';
  }

  async function ttsPreview() {
    const sample = (_panels.find(p => p.text && p.text.trim())?.text || 'Đây là đoạn nghe thử giọng đọc.').slice(0, 200);
    const payload = {
      text: sample,
      ...(typeof _resolveTtsEngineVoiceEx === 'function'
        ? _resolveTtsEngineVoiceEx('sw-tts-engine', 'sw-tts-voice')
        : { tts_engine: document.getElementById('sw-tts-engine')?.value || 'edge-tts',
            tts_voice: document.getElementById('sw-tts-voice')?.value || '' }),
      tts_rate: document.getElementById('sw-tts-rate')?.value || '+0%',
      tts_pitch: '+0Hz',
      fpt_speed: parseInt(document.getElementById('sw-tts-fpt-speed')?.value || '0', 10),
    };
    if (!payload.tts_voice) return _toast('Chưa chọn giọng.', 'warning');
    try {
      LoadingUI.start && LoadingUI.start('Đang tổng hợp...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = decodeURIComponent(csrf);
      const r = await fetch('/api/tts_preview', { method: 'POST', headers, body: JSON.stringify(payload) });
      if (!r.ok) {
        const txt = await r.text();
        throw new Error('preview HTTP ' + r.status + ' — ' + txt.slice(0, 120));
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      a.play();
      a.onended = () => URL.revokeObjectURL(url);
      _toast('Phát bản nghe thử...', 'info');
    } catch (e) {
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop && LoadingUI.stop(); }
  }

  // ── 5. Render ─────────────────────────────────────────────────────────
  async function render() {
    if (!_panels.length) return _toast('Chưa có panel nào.', 'warning');
    const hasText = _panels.some(p => (p.text || '').trim());
    if (!hasText) {
      if (!confirm('Tất cả panel đều không có lời. Video sẽ không có giọng đọc — vẫn tiếp tục?')) return;
    }
    const titleHint = (_selectedManga ? _selectedManga.title : 'manga_video') +
      (_selectedChapter?.chapter ? ' — Ch ' + _selectedChapter.chapter : '');
    const payload = {
      panels: _panels,
      title: titleHint,
      title_text: titleHint,
      preset: document.getElementById('sw-render-preset').value,
      fps: parseInt(document.getElementById('sw-render-fps').value || '30', 10),
      subtitle_format: document.getElementById('sw-sub-format').value,
      burn_subtitles: document.getElementById('sw-burn-subs').checked,
      ...(typeof _resolveTtsEngineVoiceEx === 'function'
        ? _resolveTtsEngineVoiceEx('sw-tts-engine', 'sw-tts-voice')
        : { tts_engine: document.getElementById('sw-tts-engine').value,
            tts_voice: document.getElementById('sw-tts-voice').value }),
      tts_rate: document.getElementById('sw-tts-rate').value,
      target_lang: document.getElementById('sw-target-lang').value,
      fpt_speed: parseInt(document.getElementById('sw-tts-fpt-speed').value || '0', 10),
      min_panel_sec: parseFloat(document.getElementById('sw-min-panel').value || '2.5'),
      inter_panel_pause_sec: parseFloat(document.getElementById('sw-pause').value || '0.25'),
      // Smooth cross-dissolve between panels (Step 3 — "khung hình móc nối")
      // Read from optional UI input #sw-crossfade; default 0.4s for AI stories.
      crossfade_sec: parseFloat(document.getElementById('sw-crossfade')?.value || '0.4'),
      zoom: document.getElementById('sw-zoom').checked,
      bgm_url: document.getElementById('sw-bgm').value.trim(),
      bgm_volume: parseFloat(document.getElementById('sw-bgm-vol').value || '0.10'),
    };
    if (!payload.tts_voice) return _toast('Chưa chọn giọng đọc.', 'warning');
    _log(`▶ Gửi request render: ${payload.panels.length} panels · preset=${payload.preset} · ${payload.fps}fps · TTS=${payload.tts_engine}/${payload.tts_voice}`, 'info');
    try {
      const r = await API.post('/api/story/manga/render', payload);
      if (!r.ok) throw new Error(r.error || 'render failed');
      _log(`  ✓ Job ID: ${r.job_id} · bắt đầu polling progress...`, 'success');
      _toast('Đã bắt đầu render. Theo dõi tiến trình bên dưới.', 'info');
      const wrap = document.getElementById('sw-render-status');
      const bar = document.getElementById('sw-render-bar');
      const msg = document.getElementById('sw-render-msg');
      const pct = document.getElementById('sw-render-pct');
      const res = document.getElementById('sw-render-result');
      wrap.classList.remove('hidden');
      res.classList.add('hidden');
      bar.style.width = '0%'; pct.textContent = '0%'; msg.textContent = 'Đang khởi tạo...';
      pollRender(r.job_id);
    } catch (e) {
      _log('✗ Lỗi gọi render API: ' + (e.message || e), 'error');
      _toast(String(e.message || e), 'error');
    }
  }

  function pollRender(jobId) {
    if (_renderPoll) clearInterval(_renderPoll);
    let _lastMessage = '';
    let _lastProgress = -1;
    const _renderStartTime = Date.now();
    _renderPoll = setInterval(async () => {
      try {
        const r = await fetch('/api/story/manga/render_status?job_id=' + encodeURIComponent(jobId)).then(r => r.json());
        if (!r.ok) return;
        const bar = document.getElementById('sw-render-bar');
        const pct = document.getElementById('sw-render-pct');
        const msg = document.getElementById('sw-render-msg');
        bar.style.width = (r.progress || 0) + '%';
        pct.textContent = (r.progress || 0) + '%';
        msg.textContent = r.message || r.status;

        // Log only when message OR progress crosses a meaningful step
        const curMsg = (r.message || '').trim();
        const curProg = r.progress || 0;
        if (curMsg && curMsg !== _lastMessage) {
          _log(`  [${curProg}%] ${curMsg}`, 'info');
          _lastMessage = curMsg;
          _lastProgress = curProg;
        } else if (curProg - _lastProgress >= 10) {
          // Progress jumped by 10% but same message → still useful
          _log(`  [${curProg}%] ...`, 'detail');
          _lastProgress = curProg;
        }

        if (r.status === 'done' || r.status === 'error') {
          clearInterval(_renderPoll); _renderPoll = null;
          const elapsed = ((Date.now() - _renderStartTime) / 1000).toFixed(1);
          const res = document.getElementById('sw-render-result');
          const txt = document.getElementById('sw-render-result-text');
          if (r.status === 'done') {
            res.classList.remove('hidden');
            txt.textContent = '✓ Hoàn tất: ' + (r.output_video_rel || r.output_video || '');
            txt.style.color = '';

            const videoName = (r.output_video_rel || r.output_video || '').replace(/^.*[\\/]/, '');
            const srtName   = (r.output_srt_rel   || r.output_srt   || '').replace(/^.*[\\/]/, '');
            const assName   = (r.output_ass_rel   || r.output_ass   || '').replace(/^.*[\\/]/, '');

            const player = document.getElementById('sw-render-player');
            const dlVideo = document.getElementById('sw-render-download-video');
            const dlSrt = document.getElementById('sw-render-download-srt');
            const dlAss = document.getElementById('sw-render-download-ass');
            if (videoName) {
              const playUrl = '/api/story/manga/render_video?kind=video&name=' + encodeURIComponent(videoName);
              player.src = playUrl;
              player.classList.remove('hidden');
              try { player.load(); } catch (_) {}
              dlVideo.href = playUrl + '&download=1';
              dlVideo.style.display = '';
            }
            if (srtName) {
              dlSrt.href = '/api/story/manga/render_video?kind=srt&download=1&name=' + encodeURIComponent(srtName);
              dlSrt.style.display = '';
            } else { dlSrt.style.display = 'none'; }
            if (assName) {
              dlAss.href = '/api/story/manga/render_video?kind=ass&download=1&name=' + encodeURIComponent(assName);
              dlAss.style.display = '';
            } else { dlAss.style.display = 'none'; }

            _log(`🎉 Render hoàn tất sau ${elapsed}s · file: ${videoName}`, 'banner');
            _toast('Render xong!', 'success');
          } else {
            // status === 'error'
            res.classList.remove('hidden');
            txt.textContent = '✗ Lỗi: ' + (r.error || 'unknown');
            txt.style.color = 'var(--error)';
            // Hide download buttons on error
            ['sw-render-download-video', 'sw-render-download-srt', 'sw-render-download-ass'].forEach(id => {
              const el = document.getElementById(id);
              if (el) el.style.display = 'none';
            });
            _log(`✗ Render lỗi sau ${elapsed}s: ${r.error || 'unknown'}`, 'error');
            _toast('Render lỗi: ' + (r.error || ''), 'error');
          }
        }
      } catch (_) {}
    }, 1500);
  }

  function cancelRender() {
    if (_renderPoll) { clearInterval(_renderPoll); _renderPoll = null; }
    document.getElementById('sw-render-status')?.classList.add('hidden');
    const player = document.getElementById('sw-render-player');
    if (player) {
      try { player.pause(); player.removeAttribute('src'); player.load(); } catch (_) {}
      player.classList.add('hidden');
    }
  }

  // ── AI Story Generation ─────────────────────────────────────────────────
  let _aiScenes = []; // [{text, image_prompt, image_url}]
  let _aiCancelled = false;  // user-controlled cancel flag
  let _aiAbortCtrl = null;   // AbortController for in-flight fetch (optional)

  function _getCharacters() {
    const rows = document.querySelectorAll('#sw-ai-chars .sw-ai-char-row');
    const chars = [];
    rows.forEach(row => {
      const name = (row.querySelector('.sw-ai-char-name')?.value || '').trim();
      const desc = (row.querySelector('.sw-ai-char-desc')?.value || '').trim();
      const urlsInput = row.querySelector('.sw-ai-char-ref-urls');
      let refUrls = [];
      try {
        refUrls = urlsInput ? JSON.parse(urlsInput.value || '[]') : [];
      } catch (_) {
        refUrls = [];
      }
      if (name) chars.push({ name, description: desc, reference_images: refUrls });
    });
    return chars;
  }

  function _referenceUrlsForCharacter(c, maxCount = 3) {
    const urls = [];
    const pushUrl = (url) => {
      url = String(url || '').trim();
      if (url && !urls.includes(url)) urls.push(url);
    };
    pushUrl(c?.selected_image_url);
    (c?.reference_images || []).forEach(pushUrl);
    (c?.images || []).forEach(img => pushUrl(img?.url || img?.image_url || img?.thumbnail));
    return urls.slice(0, maxCount);
  }

  function _detectSceneCharacterNames(text, characters = _getCharacters()) {
    const haystack = _normalizeCharacterKey(text);
    if (!haystack) return [];
    const names = [];
    for (const c of (characters || [])) {
      const name = c.name || '';
      const needle = _normalizeCharacterKey(name);
      if (needle && haystack.includes(needle) && !names.includes(name)) {
        names.push(name);
      }
    }
    return names;
  }

  function _sceneItemText(scene) {
    return typeof scene === 'string' ? scene : (scene?.text || '');
  }

  function _sceneItemCharacters(scene, characters = _getCharacters()) {
    if (scene && typeof scene === 'object' && Array.isArray(scene.characters) && scene.characters.length) {
      return scene.characters.filter(Boolean);
    }
    return _detectSceneCharacterNames(_sceneItemText(scene), characters);
  }

  function _sceneItemsFromScenes(scenes, characters = _getCharacters()) {
    return (scenes || [])
      .map(scene => {
        const text = _sceneItemText(scene).trim();
        if (!text) return null;
        const imagePrompt = typeof scene === 'object' ? (scene.image_prompt || '') : '';
        const detectedCharacters = _sceneItemCharacters(scene, characters);
        return {
          text,
          image_prompt: imagePrompt,
          characters: detectedCharacters,
        };
      })
      .filter(Boolean);
  }

  function _uniqueSceneCharacterNames(sceneItems, characters = _getCharacters()) {
    const names = [];
    for (const scene of (sceneItems || [])) {
      for (const name of _sceneItemCharacters(scene, characters)) {
        if (name && !names.includes(name)) names.push(name);
      }
    }
    if (!names.length) {
      for (const name of _characterNamesInTexts((sceneItems || []).map(_sceneItemText), characters)) {
        if (name && !names.includes(name)) names.push(name);
      }
    }
    return names;
  }

  function addChar() {
    const wrap = document.getElementById('sw-ai-chars');
    if (!wrap) return;

    const card = _el('div', {
      class: 'sw-ai-char-row',
      style: 'background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px;display:flex;flex-direction:column;gap:10px'
    });

    // ── Top row: buttons (left) + name/description (right) ──────────────
    const topRow = _el('div', {
      style: 'display:flex;gap:10px;align-items:flex-start'
    });

    // Left column: action buttons
    const refsContainer = _el('div', {
      class: 'char-refs-container',
      style: 'flex:0 0 124px;width:124px;display:flex;flex-direction:column;gap:6px'
    });
    const fileInput = _el('input', {
      class: 'sw-ai-char-ref-file',
      type: 'file',
      accept: 'image/*',
      multiple: 'multiple',
      style: 'display:none'
    });
    fileInput.addEventListener('change', () => uploadCharRef(fileInput));

    const uploadBtn = _el('button', {
      class: 'btn btn-secondary btn-sm',
      type: 'button',
      style: 'font-size:11px;padding:5px 6px'
    }, '📤 Ảnh mẫu');
    uploadBtn.addEventListener('click', () => fileInput.click());

    const genBtn = _el('button', {
      class: 'btn btn-outline-info btn-sm sw-ai-char-genimg-btn',
      type: 'button',
      style: 'font-size:11px;padding:5px 6px',
      title: 'AI tạo ảnh nhân vật chuẩn từ tên + mô tả + ảnh mẫu, dùng làm tham chiếu xuyên suốt'
    }, '🎨 Tạo ảnh AI');
    genBtn.addEventListener('click', () => storyAiGenerateCharImage(genBtn));

    const hiddenUrls = _el('input', {
      type: 'hidden',
      class: 'sw-ai-char-ref-urls',
      value: '[]'
    });

    refsContainer.appendChild(fileInput);
    refsContainer.appendChild(uploadBtn);
    refsContainer.appendChild(genBtn);
    refsContainer.appendChild(hiddenUrls);

    // Right column: name + description
    const rightCol = _el('div', {
      style: 'flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:8px'
    });
    const nameRow = _el('div', {
      style: 'display:flex;gap:8px;align-items:center'
    });
    const nameInput = _el('input', {
      type: 'text',
      placeholder: 'Tên nhân vật',
      class: 'sw-ai-char-name',
      style: 'flex:1;min-width:0;font-size:12px;padding:6px 8px;font-weight:700'
    });
    const delBtn = _el('button', {
      class: 'btn btn-danger btn-sm',
      type: 'button',
      style: 'padding:4px 8px',
      title: 'Xoá nhân vật'
    }, '✕');
    delBtn.addEventListener('click', () => card.remove());
    nameRow.appendChild(nameInput);
    nameRow.appendChild(delBtn);

    const descInput = _el('textarea', {
      placeholder: 'Mô tả ngoại hình (vd: nam 25t, tóc đen, áo hoodie xám, mắt nâu, cao gầy...)',
      class: 'sw-ai-char-desc',
      rows: '3',
      style: 'font-size:12px;padding:6px 8px;resize:vertical;font-family:inherit'
    });

    rightCol.appendChild(nameRow);
    rightCol.appendChild(descInput);

    topRow.appendChild(refsContainer);
    topRow.appendChild(rightCol);

    // ── Full-width reference image gallery: 5 per row, click to view ────
    const previewDiv = _el('div', {
      class: 'sw-ai-char-refs-preview',
      style: 'display:grid;grid-template-columns:repeat(5,1fr);gap:8px'
    });

    card.appendChild(topRow);
    card.appendChild(previewDiv);

    wrap.appendChild(card);
  }

  async function aiGenerate() {
    const prompt = (document.getElementById('sw-ai-prompt').value || '').trim();
    const genre = document.getElementById('sw-ai-genre')?.value || '';
    const numPanels = parseInt(document.getElementById('sw-ai-panels')?.value || '8', 10);
    const language = document.getElementById('sw-ai-lang')?.value || 'vi';
    const location = (document.getElementById('sw-ai-location')?.value || '').trim();
    const characters = _getCharacters();
    const status = document.getElementById('sw-ai-status');

    if (!prompt) return _toast('Nhập đề bài / ý tưởng truyện trước.', 'warning');

    _aiSetBusy(true, 'Đang viết truyện...');
    _log('━━━ Bắt đầu tạo truyện (chỉ text) ━━━', 'banner');
    _log(`Đề bài: "${prompt.slice(0, 100)}${prompt.length > 100 ? '...' : ''}"`, 'info');
    _log(`Thể loại: ${genre || 'tự do'} · Số cảnh: ${numPanels} · Ngôn ngữ: ${language}`, 'detail');
    if (characters.length) _log(`Nhân vật: ${characters.map(c => c.name).join(', ')}`, 'detail');
    if (status) status.textContent = '⏳ Đang tạo truyện...';
    try {
      const r = await API.post('/api/story/ai_generate', {
        prompt, genre, num_panels: numPanels, language, characters, location,
      });
      if (!r.ok) throw new Error(r.error || 'AI generation failed');
      const textArea = document.getElementById('sw-text');
      if (textArea) textArea.value = r.text || '';
      _updateComicPageEstimate();
      const model = r.model || '';
      const usage = r.usage || {};
      const tokens = usage.total_tokens || (usage.prompt_tokens || 0) + (usage.completion_tokens || 0);
      if (status) status.textContent = `✓ Text xong · model: ${model}${tokens ? ' · ' + tokens + ' tokens' : ''}`;
      _log(`✓ Đã sinh ${(r.text || '').length} ký tự (model: ${model}, ${tokens} tokens)`, 'success');

      // Show a clear "next step" callout so the user isn't lost wondering what to
      // do with the freshly-written story. The callout offers two paths:
      //   1. continue with AI image generation (full pipeline)
      //   2. fall back to manual panels (paste own images)
      _showAiNextStepHint(r.text || '');
      _toast('Đã tạo nội dung truyện! Bấm "Sinh ảnh AI" để tạo khung hình tự động.', 'success');

      // Auto-save text-only session
      _autoSaveSession({
        prompt, genre, numPanels, language, characters, location,
        artStyle: document.getElementById('sw-ai-art-style')?.value || '',
        imgRatio: document.getElementById('sw-ai-img-ratio')?.value || '9:16',
        imgNote: document.getElementById('sw-ai-img-note')?.value || '',
        imgModel: document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image',
        imgQuality: document.getElementById('sw-ai-img-quality')?.value || 'standard',
        storyText: r.text || '',
        scenes: _parseScenes(r.text || '').map(t => ({ text: t, image_prompt: '', image_url: '' })),
      });
    } catch (e) {
      if (status) status.textContent = '';
      _log('✗ Lỗi tạo truyện: ' + (e.message || e), 'error');
      _toast('Lỗi tạo truyện: ' + (e.message || e), 'error');
    } finally { _aiSetBusy(false); }
  }

  function _parseScenes(text) {
    // Split text into paragraphs (separated by blank lines)
    return (text || '').split(/\n\s*\n/).map(s => s.trim()).filter(s => s.length > 0);
  }

  // Render a sticky next-step banner under the story textarea so users who
  // just generated text-only know what to do next. Idempotent — calling it
  // twice replaces the previous banner instead of duplicating.
  function _showAiNextStepHint(storyText) {
    const oldBanner = document.getElementById('sw-ai-next-step-banner');
    if (oldBanner) oldBanner.remove();

    const sceneCount = _parseScenes(storyText).length;
    const textArea = document.getElementById('sw-text');
    if (!textArea) return;

    const banner = document.createElement('div');
    banner.id = 'sw-ai-next-step-banner';
    banner.className = 'alert-info';
    banner.style.cssText = 'margin-top:10px;padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between';

    const txt = document.createElement('div');
    txt.style.cssText = 'flex:1;min-width:240px;font-size:13px;line-height:1.5';
    txt.innerHTML =
      `<b>✓ Đã tạo truyện ${sceneCount} cảnh.</b> ` +
      `Bước tiếp theo: bấm <b>🎨 Sinh ảnh AI</b> để tạo ảnh cho từng cảnh, ` +
      `hoặc <b>📤 Gửi sang Panels</b> nếu bạn muốn dán ảnh thủ công.`;
    banner.appendChild(txt);

    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap';

    const btnImages = document.createElement('button');
    btnImages.className = 'btn btn-primary btn-sm';
    btnImages.type = 'button';
    btnImages.textContent = '🎨 Sinh ảnh AI cho ' + sceneCount + ' cảnh';
    btnImages.onclick = () => {
      banner.remove();
      // Re-run the full pipeline; it will reuse the prompt/characters from the
      // form and the text already in #sw-text. Pipeline detects existing text
      // and skips re-writing it… but currently it always re-writes. So we
      // route through aiFullPipeline which is the canonical "everything" path.
      aiFullPipeline();
    };
    actions.appendChild(btnImages);

    const btnPanels = document.createElement('button');
    btnPanels.className = 'btn btn-secondary btn-sm';
    btnPanels.type = 'button';
    btnPanels.textContent = '📤 Gửi sang Panels (ảnh thủ công)';
    btnPanels.onclick = () => {
      banner.remove();
      // Build empty-image panels from scenes so user can paste images later
      const scenes = _parseScenes(textArea.value || '');
      if (!scenes.length) return _toast('Truyện trống.', 'warning');
      const panels = scenes.map(t => ({ image_url: '', text: t, end_image_url: '' }));
      setPanels(panels);
      _toast(`Đã đẩy ${panels.length} cảnh sang Panels. Cuộn xuống để dán/upload ảnh.`, 'info');
      document.getElementById('sw-panels-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    actions.appendChild(btnPanels);

    const btnDismiss = document.createElement('button');
    btnDismiss.className = 'btn-icon';
    btnDismiss.type = 'button';
    btnDismiss.title = 'Đóng gợi ý';
    btnDismiss.style.cssText = 'font-size:16px;line-height:1';
    btnDismiss.textContent = '✕';
    btnDismiss.onclick = () => banner.remove();
    actions.appendChild(btnDismiss);

    banner.appendChild(actions);

    // Insert right after the textarea's parent .field
    const insertAfter = textArea.closest('.field') || textArea;
    insertAfter.parentNode.insertBefore(banner, insertAfter.nextSibling);
  }

  async function aiFullPipeline() {
    const prompt = (document.getElementById('sw-ai-prompt').value || '').trim();
    if (!prompt) return _toast('Nhập đề bài / ý tưởng truyện trước.', 'warning');

    const status = document.getElementById('sw-ai-status');
    const progressWrap = document.getElementById('sw-ai-progress');
    const progressBar = document.getElementById('sw-ai-progress-bar');
    const progressMsg = document.getElementById('sw-ai-progress-msg');
    const progressPct = document.getElementById('sw-ai-progress-pct');

    const genre = document.getElementById('sw-ai-genre')?.value || '';
    const numPanels = parseInt(document.getElementById('sw-ai-panels')?.value || '8', 10);
    const language = document.getElementById('sw-ai-lang')?.value || 'vi';
    const location = (document.getElementById('sw-ai-location')?.value || '').trim();
    const characters = _getCharacters();
    const artStyle = document.getElementById('sw-ai-art-style')?.value || '';
    const imgRatio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
    const imgNote = (document.getElementById('sw-ai-img-note')?.value || '').trim();
    const imgModel = (document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image').trim();
    const imgQuality = document.getElementById('sw-ai-img-quality')?.value || 'standard';

    // Use the SAME seed for all images of this story → keeps style consistent
    // (deterministic seed from prompt hash so re-runs of the same prompt look similar)
    const storySeed = _hashSeed(prompt + '|' + genre + '|' + characters.map(c => c.name).join(','));

    progressWrap.classList.remove('hidden');
    _aiScenes = [];
    _aiCancelled = false;
    _aiSetBusy(true);
    // Each run gets its own session folder so previous runs don't pollute it.
    window._aiSessionId = '';

    _log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'banner');
    _log('🚀 Bắt đầu pipeline tạo truyện + sinh ảnh', 'banner');
    _log(`Đề bài: "${prompt.slice(0, 100)}${prompt.length > 100 ? '...' : ''}"`, 'info');
    _log(`Cấu hình: thể loại=${genre || 'tự do'} · ${numPanels} cảnh · ${language}`, 'detail');
    if (characters.length) _log(`Nhân vật: ${characters.map(c => c.name + ' (' + (c.description || '').slice(0, 30) + ')').join(' | ')}`, 'detail');
    if (location) _log(`Địa điểm: ${location}`, 'detail');
    _log(`Hình ảnh: model=${imgModel} · style=${artStyle || 'AI tự chọn'} · ratio=${imgRatio} · seed=${storySeed}`, 'detail');

    let totalSteps = numPanels + 2; // 1 text + 1 prompts + N images
    let step = 0;
    function updateProgress(msg) {
      step++;
      const pct = Math.round((step / totalSteps) * 100);
      progressBar.style.width = pct + '%';
      progressPct.textContent = pct + '%';
      progressMsg.textContent = msg;
    }

    try {
      // Step 1: Generate story text
      if (_aiCancelled) throw new Error('CANCELLED');
      updateProgress('Đang viết truyện...');
      if (status) status.textContent = '⏳ Bước 1: Viết truyện...';
      _log('▶ Bước 1/3: Gọi LLM viết truyện...', 'info');
      const t1 = Date.now();
      const textRes = await API.post('/api/story/ai_generate', {
        prompt, genre, num_panels: numPanels, language, characters, location,
      }, { silent: true });
      if (!textRes.ok) throw new Error(textRes.error || 'Text generation failed');
      const storyText = textRes.text || '';
      document.getElementById('sw-text').value = storyText;
      _updateComicPageEstimate();
      _log(`  ✓ Hoàn tất sau ${((Date.now() - t1) / 1000).toFixed(1)}s · ${storyText.length} ký tự · ${textRes.usage?.total_tokens || '?'} tokens`, 'success');

      // Parse scenes
      const scenes = _parseScenes(storyText);
      if (!scenes.length) throw new Error('AI không tạo được đoạn nào.');
      _log(`  📑 Đã chia thành ${scenes.length} cảnh`, 'detail');

      const comicPageMode = !!document.getElementById('sw-ai-comic-page-mode')?.checked;
      if (comicPageMode) {
        const panelsPerPage = _getComicPanelsPerPage();
        const pageCount = Math.ceil(scenes.length / panelsPerPage);
        totalSteps = 1 + pageCount;
        _log(`▶ Bước 2/2: Sinh ${pageCount} trang manhua, mỗi trang tối đa ${panelsPerPage} khung`, 'info');
        await _generateComicPageImagesFromScenes(scenes, {
          characters, location, genre, artStyle, imgNote, imgModel, imgQuality,
          imgRatio, storySeed, updateProgress, status
        });

        progressBar.style.width = '100%';
        progressPct.textContent = '100%';
        progressMsg.textContent = '✓ Hoàn tất!';
        if (status) status.textContent = `✓ Xong ${_aiScenes.length} trang manhua · ${imgModel}`;
        _log('🎉 Đã sinh xong trang manhua nhiều khung. Bấm "Tạo video ngay" để render MP4.', 'banner');
        _toast(`Đã tạo ${_aiScenes.length} trang manhua nhiều khung.`, 'success');

        _autoSaveSession({
          prompt, genre, numPanels, language, characters, location,
          artStyle, imgRatio: document.getElementById('sw-ai-img-ratio')?.value || '9:16', imgNote, imgModel, imgQuality,
          storyText, scenes: _aiScenes, comicPageMode: true, panelsPerPage,
        });
        _log('💾 Đã lưu session để có thể tái tạo lần sau.', 'detail');
        return;
      }

      // Step 2: Generate consistent image prompts (one LLM call, all scenes)
      if (_aiCancelled) throw new Error('CANCELLED');
      updateProgress(`Đang tạo prompt ảnh nhất quán cho ${scenes.length} cảnh...`);
      if (status) status.textContent = '⏳ Bước 2: Tạo prompt ảnh (style nhất quán)...';
      _log(`▶ Bước 2/3: Gọi LLM tạo ${scenes.length} image prompts (1 lượt, style nhất quán)...`, 'info');
      const t2 = Date.now();
      const promptRes = await API.post('/api/story/ai_image_prompts', {
        scenes, characters, art_style: artStyle, location, img_note: imgNote, img_ratio: imgRatio, genre,
      }, { silent: true });
      const imgPrompts = (promptRes.ok && promptRes.prompts) ? promptRes.prompts : scenes.map(s => `${artStyle || 'cinematic'}, ${s.slice(0, 100)}`);
      if (promptRes.fallback) {
        _log(`  ⚠ Dùng prompt fallback (lý do: ${promptRes.error_hint || 'LLM không trả JSON'})`, 'warning');
        _toast('Lưu ý: dùng prompt fallback (LLM không trả JSON hợp lệ).', 'warning');
      } else {
        _log(`  ✓ Hoàn tất sau ${((Date.now() - t2) / 1000).toFixed(1)}s · ${imgPrompts.length} prompts`, 'success');
      }
      // Print first prompt as a sample so user sees the style anchor
      if (imgPrompts[0]) {
        _log(`  📝 Sample prompt: "${imgPrompts[0].slice(0, 150)}${imgPrompts[0].length > 150 ? '...' : ''}"`, 'detail');
      }

      // Step 3: Generate images one by one with the SAME seed for consistency
      _aiScenes = scenes.map((text, i) => ({
        text,
        image_prompt: imgPrompts[i] || '',
        image_url: '',
        end_image_url: '',
      }));
      _renderAiScenes();

      // ── Step 2.5 (NEW): Generate the master "anchor" image so every panel
      // can reference it. This is the single most impactful change for visual
      // continuity — without an anchor, each panel is generated independently
      // and characters / lighting / palette drift between scenes.

      // Allocate a fresh session id so anchor / portraits / scenes / end-frames
      // all land in one folder under .../ai_images/<sid>/. This lets us clean
      // up old sessions later and keeps the output directory tidy.
      try {
        if (!window._aiSessionId) {
          const sidRes = await API.post('/api/story/ai_session_new', {}, { silent: true });
          window._aiSessionId = (sidRes && sidRes.ok) ? sidRes.session_id : '';
        }
      } catch {
        window._aiSessionId = '';
      }

      let anchorUrl = '';
      try {
        if (status) status.textContent = '⏳ Tạo ảnh anchor (master shot)...';
        _log('▶ Bước 2.5/3: Sinh ảnh anchor (master shot) — dùng làm tham chiếu xuyên suốt câu chuyện', 'info');
        const tA = Date.now();
        const customRef = document.getElementById('sw-ai-ref-image-url')?.value?.trim() || '';
        const sceneRefs = _getSceneRefs();
        const anchorRes = await API.post('/api/story/ai_generate_anchor', {
          characters, location, art_style: artStyle, genre,
          model: imgModel, quality: imgQuality, ratio: imgRatio, seed: storySeed,
          session_id: window._aiSessionId || '',
          reference_image_urls: [...(customRef ? [customRef] : []), ...sceneRefs],
        }, { silent: true });
        if (anchorRes.ok && anchorRes.image_url) {
          anchorUrl = anchorRes.image_url;
          _log(`  ⚓ Anchor: ${anchorUrl} · ${((Date.now() - tA) / 1000).toFixed(1)}s`, 'success');
        } else {
          _log(`  ⚠ Không tạo được anchor (sẽ tiếp tục không có anchor): ${anchorRes.error || ''}`, 'warning');
        }
      } catch (anchorErr) {
        _log(`  ⚠ Lỗi anchor: ${anchorErr.message || anchorErr}`, 'warning');
      }

      // ── Step 2.6 (NEW): Generate one portrait per named character so the
      // model has a clean head-on reference for each face. Skip silently when
      // no characters are defined — anchor alone is enough in that case.
      const portraits = {};   // {name: image_url}
      if (characters && characters.length) {
        if (status) status.textContent = `⏳ Tạo chân dung ${characters.length} nhân vật...`;
        _log(`▶ Bước 2.6/3: Sinh chân dung cho ${characters.length} nhân vật`, 'info');
        // Run portraits in parallel (independent of each other) — typically 2-4×
        // faster than sequential without overloading 9Router.
        const portraitJobs = characters.map(async (c) => {
          if (!c.name) return;
          try {
            const tP = Date.now();
            const customRef = document.getElementById('sw-ai-ref-image-url')?.value?.trim() || '';
            const sceneRefs = _getSceneRefs();
            const r = await API.post('/api/story/ai_generate_portrait', {
              name: c.name, description: c.description || '',
              art_style: artStyle, model: imgModel, quality: imgQuality,
              ratio: '1:1', seed: storySeed, anchor_url: anchorUrl,
              session_id: window._aiSessionId || '',
              reference_image_urls: [...(customRef ? [customRef] : []), ...(c.reference_images || []), ...sceneRefs],
            }, { silent: true });
            if (r.ok && r.image_url) {
              portraits[c.name] = r.image_url;
              _log(`  👤 ${c.name}: ${((Date.now() - tP) / 1000).toFixed(1)}s`, 'detail');
            } else {
              _log(`  ⚠ Bỏ qua chân dung ${c.name}: ${r.error || ''}`, 'warning');
            }
          } catch (pErr) {
            _log(`  ⚠ Lỗi chân dung ${c.name}: ${pErr.message || pErr}`, 'warning');
          }
        });
        await Promise.all(portraitJobs);
      }

      _log(`▶ Bước 3/3: Sinh ${scenes.length} ảnh qua ${imgModel} (seed=${storySeed}, anchor=${anchorUrl ? 'có' : 'không'}, portraits=${Object.keys(portraits).length})...`, 'info');

      // Heuristic: detect which named characters appear in a scene's text so
      // we can include only the relevant portraits (sending all 5 portraits
      // for a 1-character scene confuses the model).
      function _charsInScene(sceneText) {
        const lower = (sceneText || '').toLowerCase();
        return Object.keys(portraits).filter(name =>
          lower.includes((name || '').toLowerCase())
        );
      }

      // Build the per-scene generation task. Two modes:
      //   - "chain"    (default, slower, best quality): each scene gets the
      //                previous scene's image as a reference → maximum
      //                continuity, but must run sequentially.
      //   - "parallel" (fast mode): scenes only reference anchor + portraits,
      //                so they can be generated concurrently (4 at a time).
      //                Slightly less continuity but ~4× faster.
      const fastMode = !!document.getElementById('sw-ai-fast-mode')?.checked;

      function _buildRefs(sceneIdx, prevImageUrl) {
        const refs = [];
        const customRef = document.getElementById('sw-ai-ref-image-url')?.value?.trim() || '';
        if (customRef) {
          refs.push(customRef);
        }
        if (anchorUrl) refs.push(anchorUrl);

        // Find character names appearing in this scene
        const detectedNames = _charsInScene(scenes[sceneIdx]);
        
        // For each detected character, add their user-provided reference images
        for (const name of detectedNames) {
          const charData = characters.find(c => (c.name || '').toLowerCase() === name.toLowerCase());
          if (charData && Array.isArray(charData.reference_images)) {
            for (const imgUrl of charData.reference_images) {
              if (refs.length >= 3) break;
              if (imgUrl && !refs.includes(imgUrl)) {
                refs.push(imgUrl);
              }
            }
          }
        }

        // Fallback to AI-generated portraits if we still have space
        for (const name of detectedNames) {
          if (refs.length >= 3) break;
          if (portraits[name] && !refs.includes(portraits[name])) {
            refs.push(portraits[name]);
          }
        }

        // Scenery-heavy scenes (no character detected) lean on the background
        // references pulled from the source comic so the environment matches.
        if (!detectedNames.length) {
          for (const sref of _getSceneRefs()) {
            if (refs.length >= 4) break;
            if (sref && !refs.includes(sref)) refs.push(sref);
          }
        }

        if (prevImageUrl && refs.length < 4) refs.push(prevImageUrl);
        return refs;
      }

      async function _genSingleScene(i, prevImageUrl) {
        const refs = _buildRefs(i, prevImageUrl);
        const ti = Date.now();
        
        const nTitle = document.getElementById('sn-char-novel-title')?.value?.trim() || '';
        let basePrompt = imgPrompts[i] || '';
        if (!basePrompt) {
          let text = scenes[i].slice(0, 150);
          const detectedNames = _charsInScene(scenes[i]);
          if (detectedNames.length > 0 && nTitle) {
            detectedNames.forEach(name => {
              const regex = new RegExp(`\\b${name}\\b`, 'gi');
              if (regex.test(text)) {
                text = text.replace(regex, `${name} from ${nTitle} manhua`);
              } else {
                text = `${name} from ${nTitle} manhua, ${text}`;
              }
            });
          } else if (nTitle) {
            text = `${nTitle} manhua comic style, ${text}`;
          }
          basePrompt = `${artStyle || 'cinematic film still'}, ${text}`;
        } else if (nTitle) {
          if (!basePrompt.toLowerCase().includes(nTitle.toLowerCase())) {
            basePrompt = `${basePrompt}, in the style of ${nTitle} manhua`;
          }
        }

        const imgRes = await API.post('/api/story/ai_generate_image', {
          prompt: basePrompt,
          model: imgModel,
          quality: imgQuality,
          ratio: imgRatio,
          scene_index: i + 1,
          seed: storySeed,
          reference_image_urls: refs,
          session_id: window._aiSessionId || '',
        }, { silent: true });
        return { ok: !!(imgRes.ok && imgRes.image_url), imgRes, dt: Date.now() - ti };
      }

      let okCount = 0, failCount = 0;
      const t3 = Date.now();

      if (fastMode) {
        _log(`  ⚡ Chế độ nhanh (parallel): bỏ qua chain, chạy ${Math.min(4, scenes.length)} ảnh song song`, 'detail');
        // Parallel pool with concurrency = 4
        const CONCURRENCY = Math.min(4, scenes.length);
        let next = 0;
        let done = 0;
        async function worker() {
          while (true) {
            const i = next++;
            if (i >= scenes.length) return;
            if (_aiCancelled) return;
            try {
              const { ok, imgRes, dt } = await _genSingleScene(i, '');
              if (ok) {
                _aiScenes[i].image_url = imgRes.image_url;
                okCount++;
                _log(`  ✓ Cảnh ${i + 1}/${scenes.length}: ${(dt / 1000).toFixed(1)}s · refs=${imgRes.used_references || 0}`, 'success');
              } else {
                failCount++;
                _log(`  ✗ Cảnh ${i + 1}/${scenes.length}: ${imgRes.error || 'unknown'}`, 'error');
              }
            } catch (e) {
              failCount++;
              _log(`  ✗ Cảnh ${i + 1}/${scenes.length}: ${e.message || e}`, 'error');
            }
            done++;
            updateProgress(`Đang sinh ảnh ${done}/${scenes.length}...`);
            if (status) status.textContent = `⏳ Sinh ảnh ${done}/${scenes.length}...`;
            _renderAiScenes();
          }
        }
        await Promise.all(Array(CONCURRENCY).fill(0).map(worker));
      } else {
        // Sequential chain mode — each scene references the previous one.
        let prevImageUrl = '';
        for (let i = 0; i < scenes.length; i++) {
          if (_aiCancelled) throw new Error('CANCELLED');
          updateProgress(`Đang sinh ảnh cảnh ${i + 1}/${scenes.length}...`);
          if (status) status.textContent = `⏳ Sinh ảnh ${i + 1}/${scenes.length}...`;
          try {
            const { ok, imgRes, dt } = await _genSingleScene(i, prevImageUrl);
            if (ok) {
              _aiScenes[i].image_url = imgRes.image_url;
              prevImageUrl = imgRes.image_url;
              okCount++;
              _log(`  ✓ Cảnh ${i + 1}/${scenes.length}: ${(dt / 1000).toFixed(1)}s · refs=${imgRes.used_references || 0}`, 'success');
            } else {
              failCount++;
              _log(`  ✗ Cảnh ${i + 1}/${scenes.length}: ${imgRes.error || 'unknown'}`, 'error');
            }
          } catch (imgErr) {
            failCount++;
            _log(`  ✗ Cảnh ${i + 1}/${scenes.length}: ${imgErr.message || imgErr}`, 'error');
          }
          _renderAiScenes();
        }
      }
      _log(`  ─ Tổng kết: ${okCount} thành công, ${failCount} lỗi · tổng ${((Date.now() - t3) / 1000).toFixed(1)}s`, okCount > 0 ? 'info' : 'error');

      if (_aiCancelled) throw new Error('CANCELLED');

      // Done
      progressBar.style.width = '100%';
      progressPct.textContent = '100%';
      progressMsg.textContent = '✓ Hoàn tất!';
      if (status) status.textContent = `✓ Xong ${scenes.length} cảnh · ${imgModel}`;
      _log('🎉 Pipeline hoàn tất! Bấm "Tạo video ngay" để render MP4.', 'banner');
      _toast(`Đã tạo ${scenes.length} cảnh với ảnh AI! Bấm "Tạo video ngay" để render.`, 'success');

      // Auto-save session for future reuse
      _autoSaveSession({
        prompt, genre, numPanels, language, characters, location,
        artStyle, imgRatio, imgNote, imgModel, imgQuality,
        storyText, scenes: _aiScenes,
      });
      _log('💾 Đã lưu session để có thể tái tạo lần sau.', 'detail');

    } catch (e) {
      if (e.message === 'CANCELLED') {
        progressMsg.textContent = '⏹ Đã hủy';
        if (status) status.textContent = '⏹ Đã hủy';
        _log('⏹ Người dùng đã hủy tiến trình.', 'warning');
        _toast('Đã hủy tiến trình.', 'info');
      } else {
        if (status) status.textContent = '';
        progressMsg.textContent = 'Lỗi: ' + (e.message || e);
        _log('✗ Pipeline thất bại: ' + (e.message || e), 'error');
        _toast('Lỗi pipeline: ' + (e.message || e), 'error');
      }
    } finally {
      _aiSetBusy(false);
    }
  }

  // ── Helpers: busy state + cancel + deterministic seed ─────────────────
  function _aiSetBusy(busy, _msg) {
    const card = document.querySelector('#page-story .story-source[data-source="text"]');
    const cancelBtn = document.getElementById('sw-ai-cancel-btn');
    const mainBtns = document.querySelectorAll(
      '#page-story .story-source[data-source="text"] button:not(#sw-ai-cancel-btn)'
    );
    if (busy) {
      if (cancelBtn) cancelBtn.classList.remove('hidden');
      // Disable other buttons & inputs in the AI source pane (but NOT the cancel button)
      if (card) {
        card.querySelectorAll('input, select, textarea, button').forEach(el => {
          if (el.id === 'sw-ai-cancel-btn') return;
          el.disabled = true;
        });
        card.classList.add('ai-busy');
      }
    } else {
      if (cancelBtn) cancelBtn.classList.add('hidden');
      if (card) {
        card.querySelectorAll('input, select, textarea, button').forEach(el => {
          el.disabled = false;
        });
        card.classList.remove('ai-busy');
      }
    }
  }

  function aiCancel() {
    _aiCancelled = true;
    _log('⏹ Đang yêu cầu hủy... đợi step hiện tại kết thúc.', 'warning');
    _toast('Đang hủy... đợi step hiện tại kết thúc.', 'warning');
  }

  function toggleSection(bodyId, btnId) {
    const body = document.getElementById(bodyId);
    if (!body) return;
    const btn = btnId ? document.getElementById(btnId) : null;
    const shouldHide = !body.classList.contains('hidden');
    body.classList.toggle('hidden', shouldHide);
    if (btn) {
      btn.textContent = shouldHide ? '▸ Mở' : '▾ Thu gọn';
      btn.setAttribute('aria-expanded', String(!shouldHide));
    }
  }

  async function aiUploadRefImage() {
    const f = document.getElementById('sw-ai-ref-image-file').files[0];
    if (!f) return;
    const urlInput = document.getElementById('sw-ai-ref-image-url');
    const previewWrap = document.getElementById('sw-ai-ref-image-preview-wrap');
    const previewImg = document.getElementById('sw-ai-ref-image-preview');
    const clearBtn = document.getElementById('sw-ai-ref-image-clear');

    const fd = new FormData();
    fd.append('file', f);

    try {
      LoadingUI.start && LoadingUI.start('Đang tải ảnh lên...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
      const r = await fetch('/api/story/ai_upload_ref', { method: 'POST', body: fd, headers })
        .then(res => res.json());

      if (!r.ok) throw new Error(r.error || 'Upload thất bại');
      
      urlInput.value = r.image_url;
      previewImg.src = r.image_url;
      previewWrap.classList.remove('hidden');
      clearBtn.classList.remove('hidden');
      _toast('Tải ảnh tham chiếu lên thành công!', 'success');
      _log(`  ✓ Đã upload ảnh tham chiếu: ${r.image_url}`, 'success');
    } catch (e) {
      _toast(String(e.message || e), 'error');
      _log(`✗ Lỗi tải ảnh tham chiếu: ${e.message || e}`, 'error');
    } finally {
      LoadingUI.stop && LoadingUI.stop();
    }
  }

  function aiClearRefImage() {
    const fileInput = document.getElementById('sw-ai-ref-image-file');
    const urlInput = document.getElementById('sw-ai-ref-image-url');
    const previewWrap = document.getElementById('sw-ai-ref-image-preview-wrap');
    const previewImg = document.getElementById('sw-ai-ref-image-preview');
    const clearBtn = document.getElementById('sw-ai-ref-image-clear');

    if (fileInput) fileInput.value = '';
    if (urlInput) urlInput.value = '';
    if (previewImg) previewImg.src = '';
    if (previewWrap) previewWrap.classList.add('hidden');
    if (clearBtn) clearBtn.classList.add('hidden');
    _toast('Đã xoá ảnh tham chiếu.', 'info');
  }

  function _initRefImagePreview() {
    const urlInput = document.getElementById('sw-ai-ref-image-url');
    const previewWrap = document.getElementById('sw-ai-ref-image-preview-wrap');
    const previewImg = document.getElementById('sw-ai-ref-image-preview');
    const clearBtn = document.getElementById('sw-ai-ref-image-clear');

    if (!urlInput) return;

    const updatePreview = () => {
      const val = urlInput.value.trim();
      if (val) {
        previewImg.src = val;
        previewWrap.classList.remove('hidden');
        clearBtn.classList.remove('hidden');
      } else {
        previewImg.src = '';
        previewWrap.classList.add('hidden');
        clearBtn.classList.add('hidden');
      }
    };

    urlInput.addEventListener('input', updatePreview);
    urlInput.addEventListener('change', updatePreview);
  }

  // ── Novel (Truyện chữ) Scraper Logic ────────────────────────────────────
  let _selectedNovelUrl = '';
  let _selectedNovelPage = 1;
  let _totalChaptersPages = 1;
  let _chaptersCache = {}; // Cache chapter lists by page number: { 1: [...], 2: [...] }
  let _currentSelectedChapterUrl = '';
  let _importedChapters = []; // Selected and loaded chapters [{ url, title, content }]

  async function novelSearch() {
    const q = (document.getElementById('sn-query')?.value || '').trim();
    if (!q) return _toast('Nhập từ khoá tìm truyện chữ.', 'warning');
    const results = document.getElementById('sn-results');
    const meta = document.getElementById('sn-search-meta');
    const aiSearch = !!document.getElementById('sn-ai-search')?.checked;
    
    if (results) {
      results.innerHTML = '<div class="empty-state" style="grid-column:1/-1">⏳ Đang tìm kiếm...</div>';
    }
    if (meta) meta.textContent = 'Đang tìm...';

    try {
      const r = await API.post('/api/story/novel/search', { q, ai_search: aiSearch }, { silent: true });
      if (!r.ok) throw new Error(r.error || 'Tìm kiếm thất bại');
      
      if (meta) meta.textContent = `Tìm thấy ${r.count} kết quả`;
      
      if (!r.items || !r.items.length) {
        results.innerHTML = '<div class="empty-state" style="grid-column:1/-1">Không tìm thấy kết quả nào.</div>';
        if (r.ai_note) {
          results.replaceChildren();
          const noteBox = _el('div', {
            class: 'alert-info text-sm',
            style: 'grid-column: 1 / -1; margin-bottom: 8px; border: 1px solid var(--accent); border-left-width: 4px; padding: 10px; border-radius: 6px'
          });
          noteBox.innerHTML = `🤖 <b>Gợi ý từ AI:</b> ${r.ai_note}`;
          results.appendChild(noteBox);
          results.appendChild(_el('div', { class: 'empty-state', style: 'grid-column: 1 / -1' }, 'Không tìm thấy kết quả nào với tên này.'));
        }
        return;
      }

      results.replaceChildren();
      if (r.ai_note) {
        const noteBox = _el('div', {
          class: 'alert-info text-sm',
          style: 'grid-column: 1 / -1; margin-bottom: 8px; border: 1px solid var(--accent); border-left-width: 4px; padding: 10px; border-radius: 6px'
        });
        noteBox.innerHTML = `🤖 <b>Trí tuệ nhân tạo (AI) gợi ý:</b> ${r.ai_note}`;
        results.appendChild(noteBox);
      }
      r.items.forEach(novel => {
        const card = _el('div', {
          class: 'manga-card',
          style: 'padding:8px;display:flex;flex-direction:column;gap:6px'
        });
        const img = _el('img', {
          class: 'manga-thumb',
          src: novel.cover || '/static/img/cover_fallback.png',
          style: 'width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:4px'
        });
        const title = _el('div', {
          class: 'manga-title',
          style: 'font-weight:700;font-size:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden'
        }, novel.title);
        const author = _el('div', {
          class: 'manga-meta',
          style: 'font-size:10px;color:var(--text-muted)'
        }, `Tác giả: ${novel.author}`);

        card.appendChild(img);
        card.appendChild(title);
        card.appendChild(author);

        card.addEventListener('click', () => {
          document.querySelectorAll('#sn-results .manga-card').forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          selectNovel(novel);
        });

        results.appendChild(card);
      });
    } catch (e) {
      _toast(String(e.message || e), 'error');
      if (results) {
        results.innerHTML = `<div class="empty-state" style="grid-column:1/-1;color:var(--error)">Lỗi: ${e.message || e}</div>`;
      }
      if (meta) meta.textContent = 'Lỗi';
    } finally {
    }
  }

  async function selectNovel(novel) {
    _selectedNovelUrl = novel.url;
    _selectedNovelPage = 1;
    _totalChaptersPages = 1;
    _chaptersCache = {};
    _currentSelectedChapterUrl = '';
    _importedChapters = []; // Clear previous selection when a new novel is loaded
    
    const card = document.getElementById('sn-detail-card');
    const title = document.getElementById('sn-detail-title');
    const cover = document.getElementById('sn-detail-cover');
    const author = document.getElementById('sn-detail-author');
    const desc = document.getElementById('sn-detail-desc');
    const select = document.getElementById('sn-chapter-select');
    const meta = document.getElementById('sn-chapter-meta');

    if (card) card.classList.remove('hidden');
    if (title) title.textContent = novel.title;
    if (cover) cover.src = novel.cover || '';
    if (author) author.textContent = `Tác giả: ${novel.author}`;
    if (desc) desc.textContent = 'Đang tải chi tiết truyện...';

    const charNovelTitleInput = document.getElementById('sn-char-novel-title');
    if (charNovelTitleInput) {
      let cleanTitle = novel.title || '';
      cleanTitle = cleanTitle.replace(/\[[^\]]+\]/g, '').trim();
      cleanTitle = cleanTitle.replace(/\(\d+\s*chương\)/g, '').trim();
      charNovelTitleInput.value = cleanTitle;
    }
    if (select) select.replaceChildren();
    if (meta) meta.textContent = 'Đang tải danh sách chương...';

    // Expand chapters panel by default
    const panel = document.getElementById('sn-chapters-grid-panel');
    const btn = document.getElementById('sn-toggle-chapters-btn');
    if (panel) {
      panel.classList.remove('hidden');
      panel.style.display = 'block';
    }
    if (btn) btn.textContent = '✕ Ẩn danh sách chương';

    // Render empty imported view initially
    _renderImportedChapters();

    try {
      // Bước 1: Tải trang 1 để lấy metadata (mô tả, tổng số trang)
      const r = await API.post('/api/story/novel/chapters', { url: novel.url, page: 1 }, { silent: true });
      if (!r.ok) throw new Error(r.error || 'Tải chi tiết thất bại');

      if (desc) desc.textContent = r.description || '(Không có mô tả)';
      _totalChaptersPages = parseInt(r.total_pages, 10) || 1;
      _chaptersCache[1] = r.chapters;

      // Bước 2: Tải trang cuối để hiển thị chương mới nhất
      const lastPage = _totalChaptersPages;
      if (lastPage > 1) {
        if (meta) meta.textContent = `Đang tải trang cuối (${lastPage})...`;
        try {
          const rLast = await API.post('/api/story/novel/chapters', { url: novel.url, page: lastPage }, { silent: true });
          if (rLast.ok && rLast.chapters && rLast.chapters.length > 0) {
            _chaptersCache[lastPage] = rLast.chapters;
            _selectedNovelPage = lastPage;
            if (select) {
              select.replaceChildren();
              rLast.chapters.forEach(c => {
                select.appendChild(_el('option', { value: c.url }, c.title));
              });
            }
            if (meta) meta.textContent = `(Trang ${lastPage}/${lastPage} - ${rLast.chapters.length} ch. mới nhất)`;
            _renderChaptersGrid(lastPage);
            _renderChaptersPagination();
            return; // Không auto-import chương nào
          }
        } catch (_lastErr) { /* fallback trang 1 */ }
      }

      // Fallback: 1 trang duy nhất
      _selectedNovelPage = 1;
      if (select) {
        select.replaceChildren();
        r.chapters.forEach(c => {
          select.appendChild(_el('option', { value: c.url }, c.title));
        });
      }
      if (meta) meta.textContent = `(Trang 1/${_totalChaptersPages} - ${r.chapters.length} ch.)`;
      _renderChaptersGrid(1);
      _renderChaptersPagination();
      // Không auto-import chương nào
    } catch (e) {
      _toast(String(e.message || e), 'error');
      if (desc) desc.textContent = 'Lỗi tải chi tiết: ' + (e.message || e);
    }
  }

  async function novelLoadChapter() {
    const select = document.getElementById('sn-chapter-select');
    if (!select) return;
    const url = select.value;
    const title = select.options[select.selectedIndex]?.textContent || '';
    if (url) {
      _loadChapterByUrl(url, title);
    }
  }

  function toggleChaptersGrid() {
    const panel = document.getElementById('sn-chapters-grid-panel');
    const btn = document.getElementById('sn-toggle-chapters-btn');
    if (!panel) return;
    if (panel.classList.contains('hidden') || panel.style.display === 'none') {
      panel.classList.remove('hidden');
      panel.style.display = 'block';
      if (btn) btn.textContent = '✕ Ẩn danh sách chương';
    } else {
      panel.classList.add('hidden');
      panel.style.display = 'none';
      if (btn) btn.textContent = '📋 Hiện danh sách chương';
    }
  }

  let _chaptersPageLoading = false; // guard against concurrent requests

  function _renderChaptersGrid(page, isLoading = false) {
    const grid = document.getElementById('sn-chapters-grid');
    if (!grid) return;

    grid.replaceChildren();
    const chapters = _chaptersCache[page] || [];
    if (isLoading || chapters.length === 0) {
      grid.innerHTML = isLoading
        ? '<div class="text-xs text-muted" style="grid-column:1/-1;text-align:center;padding:15px"><span style="display:inline-block;animation:spin 1s linear infinite;margin-right:6px">⏳</span> Đang tải danh sách chương trang ' + page + '...</div>'
        : '<div class="text-xs text-muted" style="grid-column:1/-1;text-align:center;padding:15px">Không có chương nào.</div>';
      return;
    }

    chapters.forEach(c => {
      // Highlight: btn-primary if currently loading, btn-info if in imported list, btn-outline-secondary if default
      const isImported = _importedChapters.some(item => item.url === c.url);
      const isActive = (c.url === _currentSelectedChapterUrl);
      
      let btnClass = 'btn-outline-secondary';
      if (isActive) {
        btnClass = 'btn-primary';
      } else if (isImported) {
        btnClass = 'btn-info';
      }

      const btn = _el('button', {
        type: 'button',
        class: 'btn btn-xs ' + btnClass,
        style: 'font-size:11px;padding:6px 8px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block;width:100%;border-radius:4px;border:1px solid var(--border);cursor:pointer',
        title: c.title
      }, c.title);

      btn.addEventListener('click', () => {
        _loadChapterByUrl(c.url, c.title);
      });

      grid.appendChild(btn);
    });
  }

  function _renderChaptersPagination() {
    const pag = document.getElementById('sn-chapters-pagination');
    if (!pag) return;
    pag.replaceChildren();

    const tot = parseInt(_totalChaptersPages, 10) || 1;
    if (tot <= 1) return;

    const cur = parseInt(_selectedNovelPage, 10) || 1;

    const addBtn = (label, targetPage, isCurrent = false, isDisabled = false) => {
      const btn = _el('button', {
        type: 'button',
        class: 'btn btn-xs ' + (isCurrent ? 'btn-primary' : 'btn-light'),
        style: 'font-size:11px;padding:4px 8px;min-width:28px;border:1px solid var(--border);cursor:pointer;pointer-events:auto !important;position:relative;z-index:999',
        disabled: isDisabled
      }, label);
      
      if (!isDisabled && !isCurrent) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          _changeChaptersPage(targetPage);
        });
      }
      pag.appendChild(btn);
    };

    // First & Prev
    addBtn('«', 1, false, cur === 1);
    addBtn('‹', cur - 1, false, cur === 1);

    // Dynamic page numbers display
    let pages = [];
    if (tot <= 7) {
      for (let i = 1; i <= tot; i++) pages.push(i);
    } else {
      pages.push(1);
      
      let start = Math.max(2, cur - 1);
      let end = Math.min(tot - 1, cur + 1);

      if (cur <= 3) {
        end = 4;
      }
      if (cur >= tot - 2) {
        start = tot - 3;
      }

      if (start > 2) {
        pages.push('...');
      }

      for (let i = start; i <= end; i++) {
        pages.push(i);
      }

      if (end < tot - 1) {
        pages.push('...');
      }

      pages.push(tot);
    }

    pages.forEach(p => {
      if (p === '...') {
        const span = _el('span', { style: 'font-size:11px;padding:4px;color:var(--text-muted)' }, '...');
        pag.appendChild(span);
      } else {
        addBtn(p.toString(), p, p === cur);
      }
    });

    // Next & Last
    addBtn('›', cur + 1, false, cur === tot);
    addBtn('»', tot, false, cur === tot);
  }

  async function _changeChaptersPage(targetPage) {
    // Prevent concurrent page-load requests
    if (_chaptersPageLoading) return;

    const pageNum = parseInt(targetPage, 10);
    const totalPages = parseInt(_totalChaptersPages, 10) || 1;

    if (isNaN(pageNum) || pageNum < 1 || pageNum > totalPages) return;

    _selectedNovelPage = pageNum;

    const meta = document.getElementById('sn-chapter-meta');
    if (meta) meta.textContent = `(Trang ${pageNum}/${totalPages} - Đang tải...)`;

    // Re-render pagination (marks current page as active)
    _renderChaptersPagination();

    // Use cached list if available — instant, no spinner needed
    if (_chaptersCache[pageNum]) {
      _renderChaptersGrid(pageNum);
      if (meta) meta.textContent = `(Trang ${pageNum}/${_totalChaptersPages} - ${_chaptersCache[pageNum].length} ch.)`;
      return;
    }

    // Show loading spinner in grid + disable pagination buttons
    _chaptersPageLoading = true;
    _renderChaptersGrid(pageNum, true);
    _setPaginationDisabled(true);
    _toast(`⏳ Đang tải chương trang ${pageNum}... (vài giây)`, 'info');

    try {
      const r = await API.post('/api/story/novel/chapters', { url: _selectedNovelUrl, page: pageNum }, { silent: true });
      if (!r.ok) throw new Error(r.error || 'Tải trang chương thất bại');

      const chapters = r.chapters || [];
      _chaptersCache[pageNum] = chapters;

      // Update total pages if backend returned a better value
      if (r.total_pages && parseInt(r.total_pages, 10) > _totalChaptersPages) {
        _totalChaptersPages = parseInt(r.total_pages, 10);
      }

      const select = document.getElementById('sn-chapter-select');
      if (select) {
        select.replaceChildren();
        chapters.forEach(c => {
          select.appendChild(_el('option', { value: c.url }, c.title));
        });
      }

      _renderChaptersGrid(pageNum);
      _renderChaptersPagination();
      if (meta) meta.textContent = `(Trang ${pageNum}/${_totalChaptersPages} - ${chapters.length} ch.)`;
      if (chapters.length === 0) {
        _toast(`Trang ${pageNum} không có chương nào.`, 'warning');
      }
    } catch (e) {
      _toast(`Lỗi tải trang ${pageNum}: ${e.message || e}`, 'error');
      if (meta) meta.textContent = `(Trang ${pageNum}/${_totalChaptersPages} - Lỗi tải)`;
      _renderChaptersGrid(pageNum); // clear spinner
    } finally {
      _chaptersPageLoading = false;
      _setPaginationDisabled(false);
    }
  }

  function _setPaginationDisabled(disabled) {
    const pag = document.getElementById('sn-chapters-pagination');
    if (!pag) return;
    pag.querySelectorAll('button').forEach(btn => {
      btn.disabled = disabled;
      btn.style.opacity = disabled ? '0.5' : '';
    });
  }

  async function _loadChapterByUrl(url, title) {
    _currentSelectedChapterUrl = url;
    
    // Add to imported list if not already present
    let chapterItem = _importedChapters.find(item => item.url === url);
    if (!chapterItem) {
      chapterItem = {
        url: url,
        title: title,
        content: ''
      };
      _importedChapters.push(chapterItem);
    }
    
    const select = document.getElementById('sn-chapter-select');
    if (select) {
      select.value = url;
    }

    // Render grid to update highlighting classes immediately
    _renderChaptersGrid(_selectedNovelPage);
    _renderImportedChapters();

    // If content is already fetched and cached, just render it immediately
    if (chapterItem.content) {
      const txt = document.getElementById('sn-imported-text');
      const cnt = document.getElementById('sn-imported-char-count');
      if (txt) txt.value = chapterItem.content;
      if (cnt) cnt.textContent = `${chapterItem.content.length} ký tự`;
      _renderImportedChapters(); // Refresh highlight active badge
      return;
    }

    // Otherwise, fetch it from the server
    const txt = document.getElementById('sn-imported-text');
    if (txt) txt.value = '⏳ Đang tải nội dung chương truyện...';

    try {
      const r = await API.post('/api/story/novel/chapter_content', { 
        url: url,
        novel_title: document.getElementById('sn-detail-title')?.textContent || '',
        chapter_title: title
      });
      if (!r.ok) throw new Error(r.error || 'Tải nội dung chương thất bại');
      
      chapterItem.content = r.content || '';
      
      // If this chapter is still the currently active visible chapter, update text
      if (_currentSelectedChapterUrl === url) {
        if (txt) txt.value = chapterItem.content;
        const cnt = document.getElementById('sn-imported-char-count');
        if (cnt) cnt.textContent = `${chapterItem.content.length} ký tự`;
      }
      
      _renderImportedChapters();
      
      if (r.ai_generated) {
        _toast('⚠️ Không thể kết nối TruyenFull. Nội dung chương đã được tự động tái tạo bằng AI!', 'warning');
      } else {
        _toast(`Đã tải xong & nạp chương: ${title}!`, 'success');
      }
    } catch (e) {
      _toast(String(e.message || e), 'error');
      if (_currentSelectedChapterUrl === url && txt) {
        txt.value = 'Lỗi tải nội dung chương: ' + (e.message || e);
      }
    }
  }

  function _renderImportedChapters() {
    const list = document.getElementById('sn-imported-list');
    const txt = document.getElementById('sn-imported-text');
    const cnt = document.getElementById('sn-imported-char-count');
    const globalTxt = document.getElementById('sw-text');

    if (!list) return;

    if (_importedChapters.length === 0) {
      list.replaceChildren(_el('span', { class: 'text-xs text-muted', id: 'sn-no-imported-hint' }, 'Chưa có chương nào được nạp. Hãy chọn một chương ở trên!'));
      if (txt) txt.value = '';
      if (cnt) cnt.textContent = '0 ký tự';
      return;
    }

    list.replaceChildren();
    _importedChapters.forEach(item => {
      // Highlight: badge-accent (blue/glowing) if this is the currently visible active chapter preview, badge-info otherwise
      const isActive = (item.url === _currentSelectedChapterUrl);
      const badge = _el('span', {
        class: 'badge ' + (isActive ? 'badge-accent' : 'badge-info'),
        style: 'display:inline-flex;align-items:center;gap:6px;padding:5px 10px;font-size:11px;border-radius:4px;cursor:pointer;border:1px solid var(--border);transition:all .15s;' + 
               (isActive ? 'background:var(--accent) !important;color:#fff !important;box-shadow:0 0 6px var(--accent-light)' : 'background:var(--accent-light);color:var(--accent-text)')
      }, item.title);

      // Clicking on the badge text loads/switches display to this chapter's content
      badge.addEventListener('click', (e) => {
        // Prevent trigger if clicking on the close cross button
        if (e.target.closest('.sn-remove-badge-btn')) return;
        _loadChapterByUrl(item.url, item.title);
      });

      const removeBtn = _el('span', {
        class: 'sn-remove-badge-btn',
        style: 'cursor:pointer;font-weight:bold;margin-left:6px;color:red;display:inline-block;padding:0 2px',
        title: 'Xóa chương này khỏi danh sách đã chọn'
      }, '✕');

      removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        storyNovelRemoveImported(item.url);
      });

      badge.appendChild(removeBtn);
      list.appendChild(badge);
    });

    // Mirror current visible chapter content to global textarea if needed
    const activeItem = _importedChapters.find(item => item.url === _currentSelectedChapterUrl);
    if (activeItem) {
      if (txt && txt.value !== '⏳ Đang tải nội dung chương truyện...') {
        txt.value = activeItem.content || '';
      }
      if (cnt && activeItem.content) {
        cnt.textContent = `${activeItem.content.length} ký tự`;
      }
    }

    // Re-render grid to update highlighting classes
    _renderChaptersGrid(_selectedNovelPage);
  }

  function removeImported(url) {
    _importedChapters = _importedChapters.filter(item => item.url !== url);
    _toast('Đã bỏ chọn chương!', 'info');
    
    // If the active visibly previewed chapter was removed, switch to another remaining chapter (if any)
    if (_currentSelectedChapterUrl === url) {
      if (_importedChapters.length > 0) {
        _currentSelectedChapterUrl = _importedChapters[0].url;
        _loadChapterByUrl(_importedChapters[0].url, _importedChapters[0].title);
      } else {
        _currentSelectedChapterUrl = '';
      }
    }
    
    _renderImportedChapters();
  }

  function clearImported() {
    _importedChapters = [];
    _currentSelectedChapterUrl = '';
    _toast('Đã xóa sạch danh sách chương đã nạp!', 'info');
    _renderImportedChapters();
  }

  function sendToAiScript() {
    const txt = document.getElementById('sn-imported-text')?.value || '';
    if (!txt) {
      return _toast('Chưa có nội dung truyện chữ nào được gộp. Hãy nạp ít nhất một chương trước!', 'warning');
    }
    const globalTxt = document.getElementById('sw-text');
    if (globalTxt) {
      globalTxt.value = txt;
    }
    const novelTitle = document.getElementById('sn-detail-title')?.textContent || '';
    const promptInput = document.getElementById('sw-ai-prompt');
    if (promptInput) {
      promptInput.value = `Chuyển thể nội dung tiểu thuyết "${novelTitle}" thành kịch bản phân cảnh chi tiết, có mô tả hình ảnh sống động và chuyển động camera mượt mà.`;
    }
    
    // Switch active tab view to the text pipeline tab
    switchSource('text');
    _toast('Đã chuyển toàn bộ nội dung gộp sang tab Tạo kịch bản AI!', 'success');
  }

  let _analyzedCharacters = []; // Stores characters analyzed from the novel

  const _CHAR_PROFILE_STORAGE_KEY = 'story_novel_character_profiles_v1';

  function _normalizeCharacterKey(name) {
    return String(name || '')
      .replace(/[đĐ]/g, 'd')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .trim();
  }

  function _canonicalCharacterName(name) {
    const key = _normalizeCharacterKey(name);
    const known = {
      'ly van tieu': 'Lý Vân Tiêu',
      'ly van tieu ': 'Lý Vân Tiêu',
    };
    return known[key] || String(name || '').trim();
  }

  function _getCurrentNovelProfileTitle() {
    return (
      document.getElementById('sn-char-novel-title')?.value?.trim()
      || document.getElementById('sn-detail-title')?.textContent?.trim()
      || document.getElementById('sw-ai-prompt')?.value?.trim()
      || 'default'
    );
  }

  function _characterImageItems(c) {
    const items = [];
    const pushUrl = (url, thumbnail) => {
      url = String(url || '').trim();
      if (!url || items.some(x => x.url === url)) return;
      items.push({ url, thumbnail: String(thumbnail || url).trim() || url });
    };
    (c.images || []).forEach(img => pushUrl(img.url || img.image_url || img.thumbnail, img.thumbnail || img.url));
    (c.reference_images || []).forEach(url => pushUrl(url, url));
    pushUrl(c.selected_image_url, c.selected_image_url);
    return items;
  }

  function _removeImageUrlFromCharacter(c, url) {
    url = String(url || '').trim();
    if (!c || !url) return;

    if (Array.isArray(c.images)) {
      c.images = c.images.filter(img => {
        const imgUrl = String(img?.url || img?.image_url || '').trim();
        const thumbUrl = String(img?.thumbnail || '').trim();
        return imgUrl !== url && thumbUrl !== url;
      });
    }
    if (Array.isArray(c.reference_images)) {
      c.reference_images = c.reference_images.filter(u => String(u || '').trim() !== url);
    }
    if (String(c.selected_image_url || '').trim() === url) {
      c.selected_image_url = _characterImageItems(c)[0]?.url || '';
    }
  }

  function _mergeCharacterProfiles(existing = [], incoming = []) {
    const byName = new Map();
    const add = (c, preferSelected = false) => {
      const key = _normalizeCharacterKey(c.name);
      if (!key) return;
      const prev = byName.get(key) || { images: [] };
      const mergedImages = [..._characterImageItems(prev)];
      for (const img of _characterImageItems(c)) {
        if (!mergedImages.some(x => x.url === img.url)) mergedImages.push(img);
      }
      const selected = preferSelected
        ? (c.selected_image_url || prev.selected_image_url || mergedImages[0]?.url || '')
        : (prev.selected_image_url || c.selected_image_url || mergedImages[0]?.url || '');
      byName.set(key, {
        ...prev,
        ...c,
        name: prev.name || c.name,
        description: c.description || prev.description || '',
        role: c.role || prev.role || '',
        images: mergedImages,
        selected_image_url: selected,
      });
    };
    existing.forEach(c => add(c, false));
    incoming.forEach(c => add(c, true));
    return Array.from(byName.values());
  }

  function _loadAllCharacterProfiles() {
    try {
      return JSON.parse(localStorage.getItem(_CHAR_PROFILE_STORAGE_KEY) || '{}') || {};
    } catch (_) {
      return {};
    }
  }

  function _saveNovelCharacterProfile(title = _getCurrentNovelProfileTitle(), characters = _analyzedCharacters) {
    const key = _normalizeCharacterKey(title);
    if (!key || !characters.length) return;
    const profiles = _loadAllCharacterProfiles();
    profiles[key] = {
      title,
      updated_at: new Date().toISOString(),
      characters,
    };
    localStorage.setItem(_CHAR_PROFILE_STORAGE_KEY, JSON.stringify(profiles));
  }

  function _loadNovelCharacterProfile(title = _getCurrentNovelProfileTitle()) {
    const profile = _loadAllCharacterProfiles()[_normalizeCharacterKey(title)];
    return profile?.characters || [];
  }

  function _charactersFromAiRows() {
    return _getCharacters().map(c => ({
      name: c.name,
      description: c.description,
      images: (c.reference_images || []).map(url => ({ url, thumbnail: url })),
      selected_image_url: (c.reference_images || [])[0] || '',
    }));
  }

  function _isProbablyNonCharacterName(name) {
    const key = _normalizeCharacterKey(name);
    const blocked = new Set([
      'thien mo', 'trung chau', 'dau thanh', 'de canh', 'linh hon de canh',
      'cuu huyen kim loi', 'loi kiep dan', 'tam khong chi', 'thien dia vo phap',
      'chan long kiem', 'yeu dan', 'hoa khi toan qua'
    ]);
    if (blocked.has(key)) return true;
    return [' dan', ' kiem', ' chi', ' mo', ' de canh', ' dau thanh'].some(suffix => key.endsWith(suffix));
  }

  function _nameCandidateHasCharacterContext(storyText, start, end) {
    const after = _normalizeCharacterKey(storyText.slice(start, Math.min(storyText.length, end + 110)));
    const before = _normalizeCharacterKey(storyText.slice(Math.max(0, start - 80), end));
    const afterMarkers = [
      ' noi', ' cuoi noi', ' hoi', ' quat', ' het', ' lanh lung noi',
      ' nhin', ' muon', ' dinh', ' cam', ' phong', ' bay', ' chem',
      ' danh', ' chinh la', ' hien ra', ' bien sac', ' kho coi',
      ' mung ro', ' ngac nhien', ' tuc gian', ' xoay', ' bi ', ' duoc '
    ];
    const beforeMarkers = ['nhin qua ', 'nhin ve phia ', 'ben canh ', 'chi vao ', 'goi ', 've phia ', 'cua ', 'voi '];
    return afterMarkers.some(marker => after.includes(marker)) || beforeMarkers.some(marker => before.includes(marker));
  }

  function _storySnippetForName(storyText, name) {
    const key = _normalizeCharacterKey(name);
    const parts = String(storyText || '').split(/(?<=[.!?。！？])\s+|\n+/);
    const hit = parts.find(part => _normalizeCharacterKey(part).includes(key)) || '';
    const clean = hit.replace(/\s+/g, ' ').trim();
    return clean.length > 420 ? clean.slice(0, 419).trim() + '...' : clean;
  }

  function _supplementCharactersFromText(characters, storyText) {
    const out = (characters || []).map(c => ({
      ...c,
      name: _canonicalCharacterName(c.name || '')
    })).filter(c => c.name);
    const hasName = (name) => out.some(c => _normalizeCharacterKey(c.name) === _normalizeCharacterKey(name));
    const seen = new Set(out.map(c => _normalizeCharacterKey(c.name)));
    const text = String(storyText || '');
    const re = /(^|[^\p{L}\p{N}_])(\p{Lu}\p{Ll}+(?:\s+\p{Lu}\p{Ll}+){1,3})(?![\p{L}\p{N}_])/gu;
    let m;
    while ((m = re.exec(text))) {
      let name = _canonicalCharacterName((m[2] || '').trim());
      const start = m.index + (m[1] || '').length;
      const end = start + (m[2] || '').length;
      const key = _normalizeCharacterKey(name);
      if (!key || seen.has(key) || _isProbablyNonCharacterName(name)) continue;
      if (!_nameCandidateHasCharacterContext(text, start, end)) continue;
      if (key === 'lao long') continue;
      seen.add(key);
      const snippet = _storySnippetForName(text, name);
      out.push({
        name,
        pinyin_name: '',
        chinese_name: '',
        aliases: [],
        description: snippet
          ? `Nhân vật được nhắc trực tiếp trong đoạn trích. Ngữ cảnh: ${snippet}`
          : 'Nhân vật được nhắc trực tiếp trong đoạn trích.',
        role: 'Nhân vật',
        images: [],
        selected_image_url: ''
      });
    }
    if (_normalizeCharacterKey(text).includes('lao long') && hasName('Xa Vưu')) {
      const xaVuu = out.find(c => _normalizeCharacterKey(c.name) === 'xa vuu');
      if (xaVuu) {
        const aliases = Array.isArray(xaVuu.aliases) ? xaVuu.aliases : [];
        if (!aliases.includes('Lão Long')) aliases.push('Lão Long');
        xaVuu.aliases = aliases;
      }
    }
    return out;
  }

  function _ensureSceneCharactersKnown() {
    if (!_aiScenes.length) return false;
    const sceneText = _aiScenes
      .filter(s => s && !s.comic_page)
      .map(s => `${s.text || ''}\n${s.image_prompt || ''}`)
      .join('\n\n');
    if (!sceneText.trim()) return false;

    const currentRows = _charactersFromAiRows();
    const supplemented = _supplementCharactersFromText(currentRows, sceneText);
    if (supplemented.length <= currentRows.length) return false;

    _analyzedCharacters = _mergeCharacterProfiles(_analyzedCharacters, supplemented);
    _saveNovelCharacterProfile();
    novelImportCharactersToAi(true, {
      preserveCurrentRows: false,
      skipSceneAutoFill: true
    });
    return true;
  }

  function novelLoadSavedCharacters() {
    const saved = _loadNovelCharacterProfile();
    if (!saved.length) return _toast('Chua co bo nhan vat da luu cho truyen nay.', 'info');
    _analyzedCharacters = _mergeCharacterProfiles(_analyzedCharacters, saved);
    _renderAnalyzedCharacters();
    novelImportCharactersToAi(true);
    _toast(`Da tai ${saved.length} nhan vat da luu cho truyen nay.`, 'success');
  }

  async function novelAnalyzeCharacters() {
    // Gather all content from selected chapters
    let combinedContent = '';
    _importedChapters.forEach(ch => {
      if (ch.content) {
        combinedContent += `=== ${ch.title} ===\n\n${ch.content}\n\n`;
      }
    });

    const cleanContent = combinedContent.trim();
    if (!cleanContent) {
      return _toast('Chưa có nội dung chương nào được tải. Vui lòng nạp ít nhất một chương ở danh sách phía trên trước!', 'warning');
    }

    const btn = document.getElementById('sn-char-analyze-btn');
    let novelTitle = document.getElementById('sn-char-novel-title')?.value?.trim() || '';
    if (!novelTitle) {
      novelTitle = document.getElementById('sn-detail-title')?.textContent || '';
    }
    
    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Đang phân tích bằng AI...';
    }

    _toast('Đang gọi AI phân tích nhân vật & tìm ảnh tham chiếu. Quá trình này có thể mất 15-30 giây...', 'info');

    try {
      const r = await API.post('/api/story/novel/analyze_characters', {
        story_text: cleanContent,
        novel_title: novelTitle
      });

      if (!r.ok) throw new Error(r.error || 'Phân tích nhân vật thất bại');

      let extractedCharacters = r.characters || [];
      
      // Auto-set the first found image as the selected reference for each character
      extractedCharacters.forEach(c => {
        c.name = _canonicalCharacterName(c.name || '');
        if (c.images && c.images.length > 0) {
          c.selected_image_url = c.images[0].url;
        } else {
          c.selected_image_url = '';
        }
      });
      extractedCharacters = _supplementCharactersFromText(extractedCharacters, cleanContent);
      _analyzedCharacters = _mergeCharacterProfiles(
        _loadNovelCharacterProfile(novelTitle),
        extractedCharacters
      );
      _saveNovelCharacterProfile(novelTitle, _analyzedCharacters);

      _renderAnalyzedCharacters();
      _toast(`Thành công! Đã trích xuất được ${_analyzedCharacters.length} nhân vật.`, 'success');
      
      // Also automatically push them directly into the Advanced Settings form!
      novelImportCharactersToAi(true); // silent = true

    } catch (e) {
      _toast(String(e.message || e), 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '🤖 Phân tích nhân vật & Tìm ảnh tham chiếu';
      }
    }
  }

  async function _searchCharacterImages(idx, queryText) {
    const c = _analyzedCharacters[idx];
    if (!c) return;

    queryText = queryText.trim();
    if (!queryText) {
      _toast('Vui lòng nhập từ khóa tìm kiếm!', 'warning');
      return;
    }

    try {
      _toast(`Đang tìm kiếm ảnh cho "${queryText}"...`, 'info');
      
      const novelTitle = document.getElementById('sn-char-novel-title')?.value?.trim() || '';
      const res = await API.post('/api/story/novel/search_character_images', {
        query: queryText,
        name: c.name || '',
        pinyin_name: c.pinyin_name || '',
        chinese_name: c.chinese_name || '',
        novel_title: novelTitle
      });
      if (res.ok && Array.isArray(res.images)) {
        c.images = res.images;
        if (res.images.length > 0) {
          c.selected_image_url = res.images[0].url;
        } else {
          c.selected_image_url = '';
        }
        _saveNovelCharacterProfile();
        _renderAnalyzedCharacters();
        novelImportCharactersToAi(true); // Sync silently
        _toast(`Tìm thấy ${res.images.length} ảnh!`, 'success');
      } else {
        _toast(res.error || 'Không tìm thấy kết quả', 'error');
      }
    } catch (e) {
      _toast(`Lỗi: ${e.message || e}`, 'error');
    }
  }

  async function _uploadCharacterRefLocal(idx, fileInput) {
    const c = _analyzedCharacters[idx];
    if (!c) return;

    const files = fileInput.files;
    if (!files.length) return;

    try {
      LoadingUI.start && LoadingUI.start(`Đang tải ảnh lên...`);
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
      
      for (let f of files) {
        const fd = new FormData();
        fd.append('file', f);
        
        const r = await fetch('/api/story/ai_upload_ref', { method: 'POST', body: fd, headers })
          .then(res => res.json());

        if (!r.ok) throw new Error(r.error || 'Upload thất bại');
        
        if (!Array.isArray(c.images)) c.images = [];
        c.images.unshift({
          url: r.image_url,
          thumbnail: r.image_url
        });
        c.selected_image_url = r.image_url;
      }

      _saveNovelCharacterProfile();
      _renderAnalyzedCharacters();
      novelImportCharactersToAi(true); // Sync silently
      _toast('Đã tải ảnh lên thành công!', 'success');
    } catch (e) {
      _toast(String(e.message || e), 'error');
    } finally {
      LoadingUI.stop && LoadingUI.stop();
      fileInput.value = '';
    }
  }

  function _renderAnalyzedCharacters() {
    const card = document.getElementById('sn-characters-analysis-card');
    const list = document.getElementById('sn-characters-list');
    if (!card || !list) return;

    card.classList.remove('hidden');
    list.replaceChildren();

    if (_analyzedCharacters.length === 0) {
      list.innerHTML = '<div class="text-xs text-muted">Không tìm thấy nhân vật nào trong đoạn trích.</div>';
      return;
    }

    _analyzedCharacters.forEach((c, idx) => {
      const row = _el('div', {
        style: 'background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:10px;margin-bottom:10px'
      });

      // Header Row
      const titleRow = _el('div', { style: 'display:flex;align-items:center;justify-content:space-between' });
      const name = _el('span', { style: 'font-weight:700;font-size:14px;color:var(--text)' }, `👤 ${c.name}`);
      const role = _el('span', { class: 'badge badge-accent', style: 'font-size:10px;padding:2px 6px' }, c.role || 'Phụ');
      titleRow.appendChild(name);
      titleRow.appendChild(role);
      row.appendChild(titleRow);

      // Description Row
      const desc = _el('div', { style: 'font-size:11px;color:var(--text2);line-height:1.4' }, `📝 ${c.description || 'Không có mô tả chi tiết'}`);
      row.appendChild(desc);

      // Custom Re-query Search Controls
      const searchControls = _el('div', {
        style: 'display:grid;grid-template-columns:1fr auto;gap:6px;align-items:center;background:var(--bg3);padding:6px;border-radius:6px;border:1px solid var(--border)'
      });
      const nTitle = document.getElementById('sn-char-novel-title')?.value?.trim() || '';
      const initialQuery = `${c.name} ${nTitle ? nTitle + ' ' : ''}manhua`.replace(/\s+/g, ' ').trim();
      const sInput = _el('input', {
        type: 'text',
        placeholder: 'Từ khóa tìm kiếm ảnh...',
        value: initialQuery,
        style: 'font-size:11px;padding:4px 8px;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--text)'
      });
      const sBtn = _el('button', {
        class: 'btn btn-secondary btn-xs',
        type: 'button',
        style: 'font-size:10px;padding:4px 8px'
      }, '🔍 Tìm lại');
      sBtn.addEventListener('click', () => {
        _searchCharacterImages(idx, sInput.value);
      });
      searchControls.appendChild(sInput);
      searchControls.appendChild(sBtn);
      row.appendChild(searchControls);

      // Upload and URL actions row
      const actionRow = _el('div', { style: 'display:flex;align-items:center;gap:8px;flex-wrap:wrap' });
      
      const fileInput = _el('input', {
        type: 'file',
        accept: 'image/*',
        multiple: 'multiple',
        style: 'display:none'
      });
      fileInput.addEventListener('change', () => {
        _uploadCharacterRefLocal(idx, fileInput);
      });

      const upBtn = _el('button', {
        class: 'btn btn-outline-info btn-xs',
        type: 'button',
        style: 'font-size:10px;padding:4px 8px;border-radius:4px'
      }, '📤 Tải ảnh lên');
      upBtn.addEventListener('click', () => fileInput.click());
      actionRow.appendChild(fileInput);
      actionRow.appendChild(upBtn);

      const urlBtn = _el('button', {
        class: 'btn btn-outline-secondary btn-xs',
        type: 'button',
        style: 'font-size:10px;padding:4px 8px;border-radius:4px'
      }, '🔗 Dán URL ảnh');
      actionRow.appendChild(urlBtn);

      // Toggleable URL input wrap
      const urlInputWrap = _el('div', {
        class: 'hidden',
        style: 'display:grid;grid-template-columns:1fr auto;gap:6px;width:100%;margin-top:4px'
      });
      const urlInput = _el('input', {
        type: 'text',
        placeholder: 'Nhập link ảnh tham chiếu trực tiếp (https://...)',
        style: 'font-size:11px;padding:4px 8px;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--text)'
      });
      const urlSaveBtn = _el('button', {
        class: 'btn btn-primary btn-xs',
        type: 'button',
        style: 'font-size:10px;padding:4px 8px'
      }, 'Lưu');
      
      urlSaveBtn.addEventListener('click', () => {
        const val = urlInput.value.trim();
        if (val) {
          if (!Array.isArray(c.images)) c.images = [];
          c.images.unshift({ url: val, thumbnail: val });
          c.selected_image_url = val;
          urlInput.value = '';
          urlInputWrap.classList.add('hidden');
          _saveNovelCharacterProfile();
          _renderAnalyzedCharacters();
          novelImportCharactersToAi(true); // Sync silently
        }
      });
      urlInputWrap.appendChild(urlInput);
      urlInputWrap.appendChild(urlSaveBtn);

      urlBtn.addEventListener('click', () => {
        urlInputWrap.classList.toggle('hidden');
      });

      row.appendChild(actionRow);
      row.appendChild(urlInputWrap);

      // Gallery of images
      const galleryContainer = _el('div', { style: 'display:flex;flex-direction:column;gap:4px;margin-top:4px' });
      galleryContainer.appendChild(_el('span', { class: 'text-xs text-muted', style: 'font-weight:600' }, '🖼️ Ảnh tham chiếu đã tìm thấy/tải lên:'));

      const gallery = _el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;margin-top:4px' });
      
      if (c.images && c.images.length > 0) {
        c.images.forEach((img, imgIdx) => {
          const isSelected = (c.selected_image_url === img.url);
          const thumbWrap = _el('div', {
            style: 'position:relative;width:64px;height:64px;border-radius:6px;overflow:hidden;background:var(--bg3)'
          });
          const imgEl = _el('img', {
            src: img.thumbnail || img.url,
            style: 'width:100%;height:100%;object-fit:cover;border-radius:6px;border:2px solid ' + (isSelected ? 'var(--accent)' : 'transparent') + ';cursor:pointer;transition:all .12s;' +
                   (isSelected ? 'box-shadow:0 0 6px var(--accent-light);transform:scale(1.05)' : ''),
            title: 'Nhấp để chọn ảnh này'
          });
          const delImgBtn = _el('button', {
            type: 'button',
            style: 'position:absolute;top:2px;right:2px;width:18px;height:18px;border:0;border-radius:999px;background:rgba(0,0,0,.72);color:#fff;font-size:12px;line-height:18px;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0',
            title: 'Xoa anh tham chieu nay'
          }, 'x');

          imgEl.addEventListener('click', () => {
            c.selected_image_url = img.url;
            _saveNovelCharacterProfile();
            _renderAnalyzedCharacters();
            novelImportCharactersToAi(true); // Sync silently
          });
          delImgBtn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            _removeImageUrlFromCharacter(c, img.url);
            _saveNovelCharacterProfile();
            _renderAnalyzedCharacters();
            novelImportCharactersToAi(true, { preserveCurrentRows: false }); // Sync silently
            _toast('Da xoa anh tham chieu.', 'info');
          });

          thumbWrap.appendChild(imgEl);
          thumbWrap.appendChild(delImgBtn);
          gallery.appendChild(thumbWrap);
        });
      } else {
        gallery.innerHTML = '<span class="text-xs text-muted" style="font-style:italic">Chưa có ảnh nào. Vui lòng bấm tìm ảnh hoặc tải ảnh từ máy lên!</span>';
      }

      galleryContainer.appendChild(gallery);
      row.appendChild(galleryContainer);

      list.appendChild(row);
    });
  }

  function novelImportCharactersToAi(silent = false, options = {}) {
    const wrap = document.getElementById('sw-ai-chars');
    if (!wrap) return;

    if (_analyzedCharacters.length === 0) {
      if (!silent) _toast('Chưa có nhân vật nào được phân tích. Hãy chạy phân tích trước!', 'warning');
      return;
    }

    if (options.preserveCurrentRows !== false) {
      _analyzedCharacters = _mergeCharacterProfiles(_charactersFromAiRows(), _analyzedCharacters);
    }
    _saveNovelCharacterProfile();

    wrap.replaceChildren();
    _analyzedCharacters.forEach(c => {
      const card = _el('div', {
        class: 'sw-ai-char-row',
        style: 'background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px;display:flex;flex-direction:column;gap:8px'
      });

      const topRow = _el('div', {
        style: 'display:grid;grid-template-columns:120px 1fr 32px;gap:8px;align-items:center'
      });
      const nameInput = _el('input', {
        type: 'text',
        placeholder: 'Tên nhân vật',
        class: 'sw-ai-char-name',
        value: c.name || '',
        style: 'font-size:12px;padding:6px 8px;font-weight:700'
      });
      const descInput = _el('input', {
        type: 'text',
        placeholder: 'Mô tả ngoại hình',
        class: 'sw-ai-char-desc',
        value: c.description || '',
        style: 'font-size:12px;padding:6px 8px'
      });
      const delBtn = _el('button', {
        class: 'btn btn-danger btn-sm',
        type: 'button',
        style: 'padding:4px 8px',
        title: 'Xoá nhân vật'
      }, '✕');
      delBtn.addEventListener('click', () => card.remove());

      topRow.appendChild(nameInput);
      topRow.appendChild(descInput);
      topRow.appendChild(delBtn);

      const refsContainer = _el('div', {
        class: 'char-refs-container',
        style: 'display:flex;flex-direction:column;gap:4px;padding-top:4px;border-top:1px dashed var(--border)'
      });

      const labelRow = _el('div', {
        style: 'display:flex;align-items:center;justify-content:space-between;gap:8px'
      });
      const labelSpan = _el('span', {
        class: 'text-xs font-semibold text-muted'
      }, '🖼️ Ảnh tham chiếu nhân vật (Style/Face References):');

      const btnWrap = _el('div', { style: 'display:flex;gap:4px' });
      const fileInput = _el('input', {
        class: 'sw-ai-char-ref-file',
        type: 'file',
        accept: 'image/*',
        multiple: 'multiple',
        style: 'display:none'
      });
      fileInput.addEventListener('change', () => uploadCharRef(fileInput));

      const addBtn = _el('button', {
        class: 'btn btn-secondary btn-sm',
        type: 'button',
        style: 'font-size:10px;padding:2px 8px'
      }, '📤 Thêm ảnh');
      addBtn.addEventListener('click', () => fileInput.click());

      btnWrap.appendChild(fileInput);
      btnWrap.appendChild(addBtn);
      labelRow.appendChild(labelSpan);
      labelRow.appendChild(btnWrap);

      const previewDiv = _el('div', {
        class: 'sw-ai-char-refs-preview',
        style: 'display:flex;gap:6px;flex-wrap:wrap;margin-top:4px'
      });

      // Render thumbnails for image-search results so user sees them inside the Advanced Form as well.
      if (c.images && c.images.length > 0) {
        c.images.forEach((img, imgIdx) => {
          const isSelected = (c.selected_image_url === img.url);
          const thumbWrap = _el('div', {
            style: 'position:relative;width:44px;height:44px;border-radius:4px;overflow:hidden;background:var(--bg3)'
          });
          const thumb = _el('img', {
            src: img.thumbnail || img.url,
            style: 'width:100%;height:100%;object-fit:cover;border-radius:4px;border:2px solid ' + (isSelected ? 'var(--accent)' : 'transparent') + ';cursor:pointer;transition:all .12s;' +
                   (isSelected ? 'box-shadow:0 0 4px var(--accent-light)' : ''),
            title: 'Chọn ảnh này làm ảnh tham chiếu mặt'
          });
          const delImgBtn = _el('button', {
            type: 'button',
            style: 'position:absolute;top:1px;right:1px;width:16px;height:16px;border:0;border-radius:999px;background:rgba(0,0,0,.72);color:#fff;font-size:10px;line-height:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0',
            title: 'Xoa anh tham chieu nay'
          }, 'x');
          thumb.addEventListener('click', () => {
            c.selected_image_url = img.url;
            _saveNovelCharacterProfile();
            _renderAnalyzedCharacters();
            novelImportCharactersToAi(true);
          });
          delImgBtn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            _removeImageUrlFromCharacter(c, img.url);
            _saveNovelCharacterProfile();
            _renderAnalyzedCharacters();
            novelImportCharactersToAi(true, { preserveCurrentRows: false });
            _toast('Da xoa anh tham chieu.', 'info');
          });
          thumbWrap.appendChild(thumb);
          thumbWrap.appendChild(delImgBtn);
          previewDiv.appendChild(thumbWrap);
        });
      }

      // Add a hidden input to hold selected + backup reference image URLs.
      // The selected image stays first, while a few backups help the model keep
      // face/clothing consistency when the provider accepts multiple refs.
      const selectedUrls = _referenceUrlsForCharacter(c, 3);
      const hiddenUrls = _el('input', {
        type: 'hidden',
        class: 'sw-ai-char-ref-urls',
        value: JSON.stringify(selectedUrls)
      });

      refsContainer.appendChild(labelRow);
      refsContainer.appendChild(previewDiv);
      refsContainer.appendChild(hiddenUrls);

      card.appendChild(topRow);
      card.appendChild(refsContainer);
      wrap.appendChild(card);
    });

    if (!options.skipSceneAutoFill) {
      _autoFillMissingSceneCharacters();
    }

    if (!silent) {
      switchSource('text');
      // Automatically expand Advanced Settings Details element so they see their characters!
      const details = document.querySelector('#page-story details');
      if (details) details.open = true;
      _toast('Đã đồng bộ thành công toàn bộ nhân vật và ảnh tham chiếu sang cấu hình AI!', 'success');
    }
  }

  async function uploadCharRef(fileInput) {
    const files = fileInput.files;
    if (!files.length) return;
    const row = fileInput.closest('.sw-ai-char-row');

    for (let f of files) {
      const fd = new FormData();
      fd.append('file', f);

      try {
        LoadingUI.start && LoadingUI.start(`Đang tải ảnh lên...`);
        const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
        const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
        const r = await fetch('/api/story/ai_upload_ref', { method: 'POST', body: fd, headers })
          .then(res => res.json());

        if (!r.ok) throw new Error(r.error || 'Upload thất bại');
        _addCharRefThumbnail(row, r.image_url);
      } catch (e) {
        _toast(String(e.message || e), 'error');
        _log(`✗ Lỗi tải ảnh tham chiếu nhân vật: ${e.message || e}`, 'error');
      } finally {
        LoadingUI.stop && LoadingUI.stop();
      }
    }
    fileInput.value = ''; // Reset file input
  }

  // ── Add a thumbnail (+ delete control, click-to-view) to a char row ───
  function _addCharRefThumbnail(row, url) {
    const previewWrap = row.querySelector('.sw-ai-char-refs-preview');
    const urlsInput = row.querySelector('.sw-ai-char-ref-urls');
    if (!previewWrap || !urlsInput || !url) return;
    let urls = [];
    try { urls = JSON.parse(urlsInput.value || '[]'); } catch (_) { urls = []; }
    if (!urls.includes(url)) urls.push(url);
    urlsInput.value = JSON.stringify(urls);

    const thumb = _el('div', {
      style: 'position:relative;width:100%;aspect-ratio:3/4;border-radius:6px;border:1px solid var(--border);overflow:hidden;background:var(--bg3);cursor:zoom-in'
    });
    const img = _el('img', { src: url, style: 'width:100%;height:100%;object-fit:cover' });
    thumb.addEventListener('click', () => window.open(url, '_blank', 'noopener'));
    const delBtn = _el('button', {
      type: 'button',
      style: 'position:absolute;top:2px;right:2px;background:rgba(0,0,0,0.6);color:#fff;border:none;width:18px;height:18px;font-size:11px;line-height:1;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;border-radius:4px',
      title: 'Xoá ảnh'
    }, '✕');
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      thumb.remove();
      let cur = [];
      try { cur = JSON.parse(urlsInput.value || '[]'); } catch (_) { cur = []; }
      urlsInput.value = JSON.stringify(cur.filter(u => u !== url));
    });
    thumb.appendChild(img);
    thumb.appendChild(delBtn);
    previewWrap.appendChild(thumb);
  }

  // ── Generate a clean "standard" character image from the row's refs ───
  // Uses /ai_generate_portrait which builds a consistent front-view prompt,
  // then registers the result as a new reference image for that character so
  // every later scene anchors to the same face/appearance.
  async function storyAiGenerateCharImage(btn) {
    const row = btn.closest('.sw-ai-char-row');
    if (!row) return;
    const name = (row.querySelector('.sw-ai-char-name')?.value || '').trim();
    const desc = (row.querySelector('.sw-ai-char-desc')?.value || '').trim();
    if (!name && !desc) {
      return _toast('Nhập tên hoặc mô tả nhân vật trước khi tạo ảnh.', 'warning');
    }
    const urlsInput = row.querySelector('.sw-ai-char-ref-urls');
    let refUrls = [];
    try { refUrls = JSON.parse(urlsInput?.value || '[]'); } catch (_) { refUrls = []; }

    const artStyle = document.getElementById('sw-ai-art-style')?.value || '';
    const imgModel = document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image';
    const imgQuality = document.getElementById('sw-ai-img-quality')?.value || 'standard';
    const sceneRefs = _getSceneRefs();

    // Ensure a session so the portrait lands in the same folder as the story.
    try {
      if (!window._aiSessionId) {
        const sidRes = await API.post('/api/story/ai_session_new', {}, { silent: true });
        window._aiSessionId = (sidRes && sidRes.ok) ? sidRes.session_id : '';
      }
    } catch { /* non-fatal */ }

    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳...';
    try {
      LoadingUI.start && LoadingUI.start(`Đang tạo ảnh nhân vật ${name || ''}...`);
      const r = await API.post('/api/story/ai_generate_portrait', {
        name: name || 'nhân vật',
        description: desc,
        art_style: artStyle,
        model: imgModel,
        quality: imgQuality,
        ratio: '1:1',
        seed: 42,
        session_id: window._aiSessionId || '',
        reference_image_urls: [...refUrls, ...sceneRefs],
      }, { silent: true });
      if (!r.ok || !r.image_url) throw new Error(r.error || 'Không tạo được ảnh');
      _addCharRefThumbnail(row, r.image_url);
      _toast(`Đã tạo ảnh nhân vật ${name || ''}.`, 'success');
      _log(`🎨 Tạo ảnh nhân vật ${name}: ${r.image_url}`, 'success');
    } catch (e) {
      _toast(String(e.message || e), 'error');
      _log(`✗ Lỗi tạo ảnh nhân vật: ${e.message || e}`, 'error');
    } finally {
      LoadingUI.stop && LoadingUI.stop();
      btn.disabled = false;
      btn.textContent = orig;
    }
  }

  // ── Scene / background reference images (taken from the comic) ─────────
  function _getSceneRefs() {
    const input = document.getElementById('sw-ai-scene-refs');
    if (!input) return [];
    try { return JSON.parse(input.value || '[]'); } catch (_) { return []; }
  }

  function _setSceneRefs(urls) {
    const input = document.getElementById('sw-ai-scene-refs');
    if (input) input.value = JSON.stringify(urls || []);
  }

  function _renderSceneRefs() {
    const wrap = document.getElementById('sw-ai-scene-refs-preview');
    if (!wrap) return;
    const urls = _getSceneRefs();
    wrap.replaceChildren();
    if (!urls.length) return;
    urls.forEach(url => {
      const thumb = _el('div', {
        style: 'position:relative;width:72px;height:72px;border-radius:6px;border:1px solid var(--border);overflow:hidden;background:var(--bg3)'
      });
      const img = _el('img', { src: url, style: 'width:100%;height:100%;object-fit:cover' });
      const delBtn = _el('button', {
        type: 'button',
        style: 'position:absolute;top:2px;right:2px;background:rgba(0,0,0,0.6);color:#fff;border:none;width:16px;height:16px;font-size:10px;line-height:1;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;border-radius:3px',
        title: 'Xoá'
      }, '✕');
      delBtn.addEventListener('click', () => {
        _setSceneRefs(_getSceneRefs().filter(u => u !== url));
        _renderSceneRefs();
      });
      thumb.appendChild(img);
      thumb.appendChild(delBtn);
      wrap.appendChild(thumb);
    });
  }

  async function storyAiUploadSceneRef(fileInput) {
    const files = fileInput.files;
    if (!files || !files.length) return;
    const urls = _getSceneRefs();
    for (let f of files) {
      const fd = new FormData();
      fd.append('file', f);
      try {
        LoadingUI.start && LoadingUI.start('Đang tải ảnh bối cảnh...');
        const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
        const headers = csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
        const r = await fetch('/api/story/ai_upload_ref', { method: 'POST', body: fd, headers })
          .then(res => res.json());
        if (!r.ok) throw new Error(r.error || 'Upload thất bại');
        if (!urls.includes(r.image_url)) urls.push(r.image_url);
      } catch (e) {
        _toast(String(e.message || e), 'error');
        _log(`✗ Lỗi tải ảnh bối cảnh: ${e.message || e}`, 'error');
      } finally {
        LoadingUI.stop && LoadingUI.stop();
      }
    }
    _setSceneRefs(urls);
    _renderSceneRefs();
    fileInput.value = '';
  }

  function storyAiAddSceneRefUrl() {
    const input = document.getElementById('sw-ai-scene-ref-url-input');
    if (!input) return;
    const url = (input.value || '').trim();
    if (!url) return;
    const urls = _getSceneRefs();
    if (!urls.includes(url)) urls.push(url);
    _setSceneRefs(urls);
    _renderSceneRefs();
    input.value = '';
  }

  // ── Scene splitting & detail configuration editor ─────────────────────
  function novelSplitScenes() {
    const textEl = document.getElementById('sw-text');
    if (!textEl) return;
    const storyText = textEl.value.trim();
    if (!storyText) {
      _toast('Vui lòng nhập nội dung truyện trước khi phân cảnh!', 'warning');
      return;
    }

    const scenes = _parseScenes(storyText);
    if (!scenes.length) {
      _toast('Không thể phân tích cảnh nào từ nội dung truyện!', 'warning');
      return;
    }

    // Adapt _aiScenes to match the split scenes
    const newAiScenes = [];
    const chars = _getCharacters();
    scenes.forEach((text, i) => {
      const existing = _aiScenes[i];
      const detectedCharacters = _detectSceneCharacterNames(`${text} ${existing?.image_prompt || ''}`, chars);
      if (existing && existing.text === text) {
        newAiScenes.push({
          text: text,
          image_prompt: existing.image_prompt || '',
          image_url: existing.image_url || '',
          end_image_url: existing.end_image_url || '',
          characters: (existing.characters && existing.characters.length) ? existing.characters : detectedCharacters
        });
      } else {
        newAiScenes.push({
          text: text,
          image_prompt: '',
          image_url: '',
          end_image_url: '',
          characters: detectedCharacters
        });
      }
    });

    _aiScenes = newAiScenes;
    _updateComicPageEstimate();

    // Show the editor card
    const editorCard = document.getElementById('sw-scenes-editor-card');
    if (editorCard) editorCard.classList.remove('hidden');

    _renderScenesEditor();
    _toast(`Đã phân tích ${scenes.length} cảnh. Hãy cấu hình chi tiết bên dưới!`, 'success');
  }

  function storyAiAutoAssignSceneCharacters(silent = false) {
    _ensureSceneCharactersKnown();
    const chars = _getCharacters();
    if (!_aiScenes.length || !chars.length) {
      if (!silent) _toast('Chua co canh hoac nhan vat de tu gan.', 'warning');
      return;
    }

    let assigned = 0;
    _aiScenes.forEach(scene => {
      if (scene.comic_page) return;
      const names = _detectSceneCharacterNames(`${scene.text || ''} ${scene.image_prompt || ''}`, chars);
      scene.characters = names;
      if (names.length) assigned++;
    });
    _renderScenesEditor();
    if (!silent) _toast(`Da tu gan nhan vat cho ${assigned}/${_aiScenes.length} canh.`, 'success');
  }

  function _autoFillMissingSceneCharacters() {
    _ensureSceneCharactersKnown();
    const chars = _getCharacters();
    if (!_aiScenes.length || !chars.length) return 0;
    let filled = 0;
    _aiScenes.forEach(scene => {
      if (scene.comic_page || (Array.isArray(scene.characters) && scene.characters.length)) return;
      const names = _detectSceneCharacterNames(`${scene.text || ''} ${scene.image_prompt || ''}`, chars);
      if (names.length) {
        scene.characters = names;
        filled++;
      }
    });
    if (filled) _renderScenesEditor();
    return filled;
  }

  function _renderScenesEditor() {
    const list = document.getElementById('sw-scenes-editor-list');
    if (!list) return;
    list.replaceChildren();

    _ensureSceneCharactersKnown();
    const chars = _getCharacters();

    _aiScenes.forEach((scene, idx) => {
      const card = _el('div', {
        class: 'scene-editor-card',
        style: 'background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:10px'
      });

      // Header row
      const headerRow = _el('div', { style: 'display:flex;justify-content:space-between;align-items:center' });
      const title = _el('span', { style: 'font-weight:700;font-size:13px;color:var(--text)' }, `🎬 Cảnh ${idx + 1}`);
      
      const statusSpan = _el('span', {
        id: `scene-status-${idx}`,
        style: 'font-size:11px;color:var(--text-muted)'
      });
      headerRow.appendChild(title);
      headerRow.appendChild(statusSpan);
      card.appendChild(headerRow);

      // Text Area (Narration)
      const textGroup = _el('div', { style: 'display:flex;flex-direction:column;gap:4px' });
      textGroup.appendChild(_el('label', { style: 'font-size:11px;font-weight:600;color:var(--text2)' }, 'Lời thoại / Dẫn truyện:'));
      const textInput = _el('textarea', {
        rows: 2,
        style: 'font-size:12px;padding:6px;width:100%;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--text);resize:vertical'
      }, scene.text);
      textInput.addEventListener('input', () => {
        scene.text = textInput.value;
        _updateMainStoryText();
      });
      textGroup.appendChild(textInput);
      card.appendChild(textGroup);

      // Image Prompt
      const promptGroup = _el('div', { style: 'display:flex;flex-direction:column;gap:4px' });
      promptGroup.appendChild(_el('label', { style: 'font-size:11px;font-weight:600;color:var(--text2)' }, 'Gợi ý vẽ ảnh (Prompt) - Nhập hoặc để tự động sinh:'));
      const promptInput = _el('input', {
        type: 'text',
        placeholder: 'Mô tả bối cảnh, hành động nhân vật...',
        style: 'font-size:12px;padding:6px 8px;width:100%;border-radius:4px;border:1px solid var(--border);background:var(--bg);color:var(--text)'
      });
      promptInput.value = scene.image_prompt || '';
      promptInput.addEventListener('input', () => {
        scene.image_prompt = promptInput.value;
      });
      promptGroup.appendChild(promptInput);
      card.appendChild(promptGroup);

      // Character Checkboxes / Pills with Avatars
      if (chars.length > 0) {
        const charGroup = _el('div', { style: 'display:flex;flex-direction:column;gap:4px' });
        charGroup.appendChild(_el('label', { style: 'font-size:11px;font-weight:600;color:var(--text2)' }, 'Nhân vật xuất hiện trong cảnh:'));
        
        const charList = _el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' });
        chars.forEach(c => {
          const isChecked = Array.isArray(scene.characters) && scene.characters.includes(c.name);
          const wrapper = _el('label', {
            style: 'display:flex;align-items:center;gap:6px;background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:4px 10px;font-size:11px;cursor:pointer;user-select:none;transition:all .12s;' +
                   (isChecked ? 'border-color:var(--accent);background:rgba(var(--accent-rgb), 0.1)' : '')
          });

          if (c.reference_images && c.reference_images.length > 0) {
            const avatar = _el('img', {
              src: c.reference_images[0],
              style: 'width:20px;height:20px;border-radius:50%;object-fit:cover;border:1px solid var(--border)'
            });
            wrapper.appendChild(avatar);
          }

          const cb = _el('input', {
            type: 'checkbox',
            checked: isChecked,
            style: 'margin:0;cursor:pointer'
          });
          cb.addEventListener('change', () => {
            if (!Array.isArray(scene.characters)) scene.characters = [];
            if (cb.checked) {
              if (!scene.characters.includes(c.name)) scene.characters.push(c.name);
              wrapper.style.borderColor = 'var(--accent)';
              wrapper.style.background = 'rgba(var(--accent-rgb), 0.1)';
            } else {
              scene.characters = scene.characters.filter(x => x !== c.name);
              wrapper.style.borderColor = 'var(--border)';
              wrapper.style.background = 'var(--bg3)';
            }
          });

          wrapper.appendChild(cb);
          wrapper.appendChild(document.createTextNode(c.name));
          charList.appendChild(wrapper);
        });
        charGroup.appendChild(charList);
        card.appendChild(charGroup);
      }

      // Preview row
      const previewRow = _el('div', {
        id: `scene-preview-${idx}`,
        style: 'display:flex;gap:8px;margin-top:4px'
      });
      _renderSceneCardPreview(idx, previewRow);
      card.appendChild(previewRow);

      // Actions Row
      const actionRow = _el('div', { style: 'display:flex;gap:6px' });
      const genStartBtn = _el('button', {
        class: 'btn btn-primary btn-sm',
        style: 'font-size:11px;padding:6px 12px;border-radius:4px',
        type: 'button'
      }, scene.image_url ? '🔄 Vẽ lại ảnh start' : '🎨 Sinh ảnh start');
      genStartBtn.addEventListener('click', () => {
        storyAiGenerateSingleSceneImage(idx);
      });

      const genEndBtn = _el('button', {
        class: 'btn btn-secondary btn-sm',
        style: 'font-size:11px;padding:6px 12px;border-radius:4px',
        type: 'button',
        disabled: !scene.image_url
      }, scene.end_image_url ? '🔄 Vẽ lại ảnh end' : '✨ Sinh ảnh end');
      genEndBtn.addEventListener('click', () => {
        storyAiGenerateSingleSceneImage(idx, true);
      });

      actionRow.appendChild(genStartBtn);
      actionRow.appendChild(genEndBtn);
      card.appendChild(actionRow);

      list.appendChild(card);
    });
  }

  function _renderSceneCardPreview(idx, container) {
    const scene = _aiScenes[idx];
    if (!scene) return;
    container.replaceChildren();

    const ratio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
    const aspectCSS = ratio.replace(':', '/');

    if (scene.image_url) {
      const wrapA = _el('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:2px' });
      const imgA = _el('img', {
        src: scene.image_url,
        style: `width:80px;aspect-ratio:${aspectCSS};object-fit:cover;border-radius:4px;border:1px solid var(--border);cursor:pointer`
      });
      imgA.addEventListener('click', () => window.open(scene.image_url, '_blank'));
      wrapA.appendChild(imgA);
      wrapA.appendChild(_el('span', { style: 'font-size:9px;color:var(--text-muted)' }, 'Ảnh Start'));
      container.appendChild(wrapA);
    }
    if (scene.end_image_url) {
      const wrapB = _el('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:2px' });
      const imgB = _el('img', {
        src: scene.end_image_url,
        style: `width:80px;aspect-ratio:${aspectCSS};object-fit:cover;border-radius:4px;border:1px solid var(--border);cursor:pointer`
      });
      imgB.addEventListener('click', () => window.open(scene.end_image_url, '_blank'));
      wrapB.appendChild(imgB);
      wrapB.appendChild(_el('span', { style: 'font-size:9px;color:var(--text-muted)' }, 'Ảnh End'));
      container.appendChild(wrapB);
    }
  }

  function _updateMainStoryText() {
    const textEl = document.getElementById('sw-text');
    if (!textEl) return;
    textEl.value = _aiScenes.map(s => s.text).join('\n\n');
  }

  async function storyAiGenerateSingleSceneImage(idx, endFrame = false) {
    const scene = _aiScenes[idx];
    if (!scene) return;

    if (endFrame && !scene.image_url) {
      _toast('Vui lòng sinh ảnh start trước khi sinh ảnh end!', 'warning');
      return;
    }

    const statusEl = document.getElementById(`scene-status-${idx}`);
    if (statusEl) statusEl.innerHTML = `<span class="spinner" style="display:inline-block;width:10px;height:10px;border:2px solid var(--text-muted);border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:4px"></span> Đang sinh ${endFrame ? 'end' : 'start'}...`;

    const cardEl = document.querySelectorAll('.scene-editor-card')[idx];
    const btns = cardEl ? cardEl.querySelectorAll('button') : [];
    btns.forEach(btn => btn.disabled = true);

    try {
      const artStyle = document.getElementById('sw-ai-art-style')?.value || '';
      const imgModel = (document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image').trim();
      const imgQuality = document.getElementById('sw-ai-img-quality')?.value || 'standard';
      const imgRatio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
      
      if (!window._aiSessionId) {
        try {
          const sidRes = await API.post('/api/story/ai_session_new', {}, { silent: true });
          window._aiSessionId = (sidRes && sidRes.ok) ? sidRes.session_id : '';
        } catch (_) {
          window._aiSessionId = '';
        }
      }

      if (endFrame) {
        const seed = _hashSeed(scene.text + '|end');
        const r = await API.post('/api/story/ai_generate_end_frame', {
          start_image_url: scene.image_url,
          scene_text: scene.text,
          art_style: artStyle,
          model: imgModel,
          quality: imgQuality,
          ratio: imgRatio,
          seed,
          session_id: window._aiSessionId || '',
        }, { silent: true });

        if (r.ok && r.image_url) {
          scene.end_image_url = r.image_url;
          _toast(`Đã sinh xong ảnh end cho cảnh ${idx + 1}`, 'success');
        } else {
          throw new Error(r.error || 'Lỗi sinh ảnh end');
        }
      } else {
        const seed = _hashSeed(scene.text + '|start');
        
        const refs = [];
        const customRef = document.getElementById('sw-ai-ref-image-url')?.value?.trim() || '';
        if (customRef) refs.push(customRef);

        const chars = _getCharacters();
        let linkedCharNames = scene.characters || [];
        if (linkedCharNames.length === 0) {
          linkedCharNames = _detectSceneCharacterNames(`${scene.text || ''} ${scene.image_prompt || ''}`, chars);
          scene.characters = linkedCharNames;
        }

        linkedCharNames.forEach(charName => {
          const cData = chars.find(c => (c.name || '').toLowerCase() === charName.toLowerCase());
          if (cData) {
            _referenceUrlsForCharacter(cData, 3).forEach(imgUrl => {
              if (refs.length < 3 && imgUrl && !refs.includes(imgUrl)) {
                refs.push(imgUrl);
              }
            });
          }
        });

        const nTitle = document.getElementById('sn-char-novel-title')?.value?.trim() || '';
        let finalPrompt = scene.image_prompt || '';
        if (!finalPrompt) {
          let text = scene.text.slice(0, 150);
          if (linkedCharNames.length > 0 && nTitle) {
            linkedCharNames.forEach(charName => {
              const regex = new RegExp(`\\b${charName}\\b`, 'gi');
              if (regex.test(text)) {
                text = text.replace(regex, `${charName} from ${nTitle} manhua`);
              } else {
                text = `${charName} from ${nTitle} manhua, ${text}`;
              }
            });
          } else if (nTitle) {
            text = `${nTitle} manhua comic style, ${text}`;
          }
          finalPrompt = `${artStyle || 'cinematic film still'}, ${text}`;
        } else if (nTitle) {
          if (!finalPrompt.toLowerCase().includes(nTitle.toLowerCase())) {
            finalPrompt = `${finalPrompt}, in the style of ${nTitle} manhua`;
          }
        }
        if (linkedCharNames.length) {
          const charHints = linkedCharNames.map(charName => {
            const cData = chars.find(c => (c.name || '').toLowerCase() === charName.toLowerCase());
            return cData ? `${charName}: ${cData.description || ''}` : charName;
          }).join('; ');
          finalPrompt += `\nCharacters in this scene: ${charHints}. Must match the attached reference images for face, hair, outfit, age and identity. Do not invent a different character design.`;
        }

        const imgRes = await API.post('/api/story/ai_generate_image', {
          prompt: finalPrompt,
          model: imgModel,
          quality: imgQuality,
          ratio: imgRatio,
          scene_index: idx + 1,
          seed: seed,
          reference_image_urls: refs,
          session_id: window._aiSessionId || '',
        }, { silent: true });

        if (imgRes.ok && imgRes.image_url) {
          scene.image_url = imgRes.image_url;
          if (!scene.image_prompt && imgRes.prompt) {
            scene.image_prompt = imgRes.prompt;
            const pInput = cardEl.querySelector('input[type="text"]');
            if (pInput) pInput.value = imgRes.prompt;
          }
          _toast(`Đã sinh xong ảnh start cho cảnh ${idx + 1}`, 'success');
        } else {
          throw new Error(imgRes.error || 'Lỗi sinh ảnh start');
        }
      }

      const previewRow = document.getElementById(`scene-preview-${idx}`);
      if (previewRow) _renderSceneCardPreview(idx, previewRow);

      _renderAiScenes();

    } catch (err) {
      _toast(`Cảnh ${idx + 1}: ${err.message || err}`, 'error');
      if (statusEl) statusEl.innerHTML = `<span style="color:var(--danger)">✗ Lỗi</span>`;
    } finally {
      if (statusEl) {
        statusEl.innerHTML = scene.image_url ? '<span style="color:var(--success)">✓ Hoàn thành</span>' : '';
      }
      btns.forEach(btn => btn.disabled = false);
      const endBtn = cardEl ? cardEl.querySelectorAll('button')[1] : null;
      if (endBtn) endBtn.disabled = !scene.image_url;
    }
  }

  async function storyAiGenerateAllScenesImages() {
    if (!_aiScenes.length) {
      _toast('Chưa có cảnh nào để sinh ảnh!', 'warning');
      return;
    }

    _toast(`Bắt đầu sinh ảnh cho ${_aiScenes.length} cảnh...`, 'info');
    
    const bulkBtn = document.getElementById('sw-gen-all-scenes-btn');
    if (bulkBtn) bulkBtn.disabled = true;

    try {
      for (let i = 0; i < _aiScenes.length; i++) {
        if (_aiScenes[i].image_url) continue;

        try {
          await storyAiGenerateSingleSceneImage(i);
        } catch (e) {
          console.error(`Lỗi sinh ảnh cảnh ${i + 1}:`, e);
        }
      }
      _toast('Đã hoàn thành sinh ảnh toàn bộ các cảnh!', 'success');
    } finally {
      if (bulkBtn) bulkBtn.disabled = false;
    }
  }

  // Convert string → 32-bit positive int (deterministic seed)
  function _hashSeed(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = ((h << 5) - h) + str.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h) || 42;
  }

  function _getComicPanelsPerPage() {
    const raw = parseInt(document.getElementById('sw-ai-comic-panels-per-page')?.value || '12', 10);
    if (!Number.isFinite(raw)) return 12;
    return Math.max(2, Math.min(16, raw));
  }

  function _getComicEstimateSceneCount() {
    const storyText = document.getElementById('sw-text')?.value || '';
    const parsedScenes = _parseScenes(storyText);
    if (parsedScenes.length) return parsedScenes.length;

    const normalScenes = _aiScenes.filter(s => !s.comic_page);
    if (normalScenes.length) return normalScenes.length;

    const comicPanelCount = _aiScenes.reduce((sum, s) => sum + (s.comic_page ? (s.panel_count || 0) : 0), 0);
    if (comicPanelCount) return comicPanelCount;

    const requested = parseInt(document.getElementById('sw-ai-panels')?.value || '0', 10);
    return Number.isFinite(requested) && requested > 0 ? requested : 0;
  }

  function _updateComicPageEstimate() {
    const el = document.getElementById('sw-ai-comic-page-estimate');
    if (!el) return;
    const panelsPerPage = _getComicPanelsPerPage();
    const sceneCount = _getComicEstimateSceneCount();
    if (!sceneCount) {
      el.textContent = `Mỗi ảnh API sẽ chứa tối đa ${panelsPerPage} khung.`;
      return;
    }
    const pageCount = Math.ceil(sceneCount / panelsPerPage);
    const lastPagePanels = sceneCount % panelsPerPage || panelsPerPage;
    const lastText = pageCount > 1 ? `, trang cuối ${lastPagePanels} khung` : '';
    el.textContent = `${sceneCount} cảnh / ${panelsPerPage} khung mỗi trang = ${pageCount} ảnh API${lastText}. Mỗi khung lấy 1 cảnh.`;
  }

  function _initComicPageEstimate() {
    ['sw-ai-comic-panels-per-page', 'sw-ai-panels', 'sw-text', 'sw-ai-comic-page-mode'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', _updateComicPageEstimate);
      el.addEventListener('change', _updateComicPageEstimate);
    });
    _updateComicPageEstimate();
  }

  function _clipText(text, maxLen = 180) {
    const s = String(text || '').replace(/\s+/g, ' ').trim();
    return s.length > maxLen ? s.slice(0, maxLen - 1).trim() + '…' : s;
  }

  function _getNovelTitleForImage() {
    return (
      document.getElementById('sn-char-novel-title')?.value?.trim()
      || document.getElementById('sn-detail-title')?.textContent?.trim()
      || ''
    );
  }

  function _chunkArray(items, size) {
    const chunks = [];
    for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
    return chunks;
  }

  function _characterNamesInTexts(texts, characters) {
    const lower = texts.join('\n').toLowerCase();
    return (characters || [])
      .map(c => c.name || '')
      .filter(name => name && lower.includes(name.toLowerCase()));
  }

  function _referenceImagesForComicPage(pageScenes, characters) {
    const refs = [];
    const customRef = document.getElementById('sw-ai-ref-image-url')?.value?.trim() || '';
    if (customRef) refs.push(customRef);

    const sceneItems = _sceneItemsFromScenes(pageScenes, characters);
    const names = _uniqueSceneCharacterNames(sceneItems, characters);
    for (const name of names) {
      const c = (characters || []).find(x => (x.name || '').toLowerCase() === name.toLowerCase());
      for (const imgUrl of _referenceUrlsForCharacter(c, 2)) {
        if (refs.length >= 4) return refs;
        if (imgUrl && !refs.includes(imgUrl)) refs.push(imgUrl);
      }
    }
    return refs;
  }

  function _buildComicPagePrompt(pageScenes, pageIndex, totalPages, opts = {}) {
    const novelTitle = _getNovelTitleForImage();
    const location = (opts.location || '').trim();
    const artStyle = (opts.artStyle || '').trim();
    const imgNote = (opts.imgNote || '').trim();
    const characters = opts.characters || [];
    const sceneItems = _sceneItemsFromScenes(pageScenes, characters);
    const pageCharNames = _uniqueSceneCharacterNames(sceneItems, characters);
    const pageCharacters = pageCharNames
      .map(name => characters.find(c => (c.name || '').toLowerCase() === name.toLowerCase()))
      .filter(Boolean);
    const pageTitle = totalPages > 1 ? `Trang ${pageIndex + 1}/${totalPages}` : 'Trang truyện';
    const sceneLines = sceneItems.map((scene, i) => {
      const names = _sceneItemCharacters(scene, characters);
      const charHint = names.length
        ? ` Nhân vật trong khung: ${names.join(', ')}. Giữ đúng gương mặt, tóc, trang phục theo ảnh tham chiếu.`
        : '';
      return `- Khung ${i + 1}: ${_clipText(scene.text, 220)}${charHint}`;
    }).join('\n');
    const dialogueLines = sceneItems.slice(0, 8).map((scene, i) => {
      const line = _clipText(scene.text, 52).replace(/["“”]/g, '');
      return `- Khung ${i + 1}: “${line}”`;
    }).join('\n');
    const charBlock = pageCharacters.length
      ? pageCharacters.map(c => `- ${c.name}: ${_clipText(c.description || '', 140)}. Must match attached reference image exactly.`).join('\n')
      : '- Không cố định nhân vật; giữ đúng nhân vật xuất hiện trong mô tả từng khung.';

    return [
      `Tạo một trang truyện tranh/manhua cinematic hoàn chỉnh (${pageTitle}) theo phong cách ${novelTitle || 'Chinese fantasy manhua'}, bố cục nhiều khung truyện như storyboard điện ảnh, tỷ lệ ảnh dọc.`,
      '',
      `Phong cách bắt buộc: Chinese fantasy manhua, wuxia xianxia, cinematic lighting, ultra detailed, volumetric light, dramatic atmosphere, realistic anime face, dynamic composition, movie storyboard, epic fantasy comic page, 4k.`,
      artStyle ? `Phong cách bổ sung: ${artStyle}.` : '',
      location ? `Bối cảnh chính: ${location}.` : '',
      imgNote ? `Ghi chú thêm: ${imgNote}.` : '',
      '',
      'Nhân vật tham chiếu:',
      charBlock,
      pageCharacters.length ? 'Chỉ đưa nhân vật vào đúng khung được liệt kê. Không tự thay mặt, đổi giới tính, đổi tóc hoặc đổi trang phục của nhân vật đã có ảnh tham chiếu.' : '',
      '',
      'Các khung truyện phải xuất hiện theo thứ tự sau:',
      sceneLines,
      '',
      'Chèn textbox tiếng Việt trong từng khung truyện giống manga/manhua, chữ đen rõ trên hộp trắng hoặc bong bóng thoại. Dùng ít chữ, dễ đọc, không che mặt nhân vật. Gợi ý textbox/hội thoại:',
      dialogueLines,
      '',
      'Yêu cầu bố cục: nhiều panel rõ ràng, có đường viền phân tách khung, nhịp kể chuyện điện ảnh, không tạo một ảnh đơn lẻ. Mỗi khung là một khoảnh khắc khác nhau của cùng chuỗi phân cảnh. Giữ nhân vật, phục trang, ánh sáng và màu sắc nhất quán giữa các khung.',
    ].filter(Boolean).join('\n');
  }

  async function _ensureAiSession() {
    if (window._aiSessionId) return window._aiSessionId;
    try {
      const sidRes = await API.post('/api/story/ai_session_new', {}, { silent: true });
      window._aiSessionId = (sidRes && sidRes.ok) ? sidRes.session_id : '';
    } catch (_) {
      window._aiSessionId = '';
    }
    return window._aiSessionId;
  }

  async function _generateComicPageImagesFromScenes(scenes, opts = {}) {
    const panelsPerPage = _getComicPanelsPerPage();
    const sceneItems = _sceneItemsFromScenes(scenes, opts.characters || []);
    const groups = _chunkArray(sceneItems, panelsPerPage);
    const imgRatio = ['9:16', '3:4'].includes(opts.imgRatio || '') ? opts.imgRatio : '9:16';
    const ratioEl = document.getElementById('sw-ai-img-ratio');
    if (ratioEl) ratioEl.value = imgRatio;
    await _ensureAiSession();

    _aiScenes = groups.map((group, i) => ({
      text: group.map(scene => scene.text).join('\n\n'),
      image_prompt: _buildComicPagePrompt(group, i, groups.length, opts),
      image_url: '',
      end_image_url: '',
      comic_page: true,
      panel_count: group.length,
      characters: _uniqueSceneCharacterNames(group, opts.characters || []),
    }));
    _renderAiScenes();

    let okCount = 0;
    let failCount = 0;
    for (let i = 0; i < _aiScenes.length; i++) {
      if (_aiCancelled) throw new Error('CANCELLED');
      opts.updateProgress && opts.updateProgress(`Đang sinh trang manhua ${i + 1}/${_aiScenes.length}...`);
      if (opts.status) opts.status.textContent = `⏳ Sinh trang manhua ${i + 1}/${_aiScenes.length}...`;
      const refs = _referenceImagesForComicPage(groups[i], opts.characters || []);
      const t0 = Date.now();
      try {
        const imgRes = await API.post('/api/story/ai_generate_image', {
          prompt: _aiScenes[i].image_prompt,
          model: opts.imgModel || 'cx/gpt-5.5-image',
          quality: opts.imgQuality || 'standard',
          ratio: imgRatio,
          scene_index: i + 1,
          seed: (opts.storySeed || 42) + i,
          reference_image_urls: refs,
          session_id: window._aiSessionId || '',
        }, { silent: true });
        if (imgRes.ok && imgRes.image_url) {
          _aiScenes[i].image_url = imgRes.image_url;
          okCount++;
          _log(`  ✓ Trang ${i + 1}/${_aiScenes.length}: ${((Date.now() - t0) / 1000).toFixed(1)}s · ${groups[i].length} khung · refs=${imgRes.used_references || 0}`, 'success');
        } else {
          failCount++;
          _log(`  ✗ Trang ${i + 1}/${_aiScenes.length}: ${imgRes.error || 'unknown'}`, 'error');
        }
      } catch (err) {
        failCount++;
        _log(`  ✗ Trang ${i + 1}/${_aiScenes.length}: ${err.message || err}`, 'error');
      }
      _renderAiScenes();
    }
    _log(`  ─ Tổng kết trang manhua: ${okCount} thành công, ${failCount} lỗi`, okCount ? 'info' : 'error');
    return _aiScenes;
  }

  async function storyAiGenerateComicPages() {
    let sourceScenes = _aiScenes
      .filter(s => s && !s.comic_page && (s.text || '').trim())
      .map(s => ({
        text: s.text || '',
        image_prompt: s.image_prompt || '',
        characters: Array.isArray(s.characters) ? s.characters : [],
      }));
    if (!sourceScenes.length) {
      sourceScenes = _parseScenes(document.getElementById('sw-text')?.value || '');
    }
    if (!sourceScenes.length) return _toast('Chưa có phân cảnh nào để sinh trang manhua.', 'warning');

    const btn = document.getElementById('sw-gen-comic-pages-btn');
    if (btn) btn.disabled = true;
    try {
      const characters = _getCharacters();
      const location = (document.getElementById('sw-ai-location')?.value || '').trim();
      const genre = document.getElementById('sw-ai-genre')?.value || '';
      const artStyle = document.getElementById('sw-ai-art-style')?.value || '';
      const imgNote = (document.getElementById('sw-ai-img-note')?.value || '').trim();
      const imgModel = (document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image').trim();
      const imgQuality = document.getElementById('sw-ai-img-quality')?.value || 'standard';
      const imgRatio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
      const sourceSceneText = sourceScenes.map(_sceneItemText);
      const storySeed = _hashSeed(sourceSceneText.join('|') + '|' + characters.map(c => c.name).join(','));
      _toast(`Đang sinh trang manhua từ ${sourceScenes.length} phân cảnh...`, 'info');
      await _generateComicPageImagesFromScenes(sourceScenes, {
        characters, location, genre, artStyle, imgNote, imgModel, imgQuality,
        imgRatio, storySeed,
        updateProgress: null,
        status: document.getElementById('sw-ai-status'),
      });
      _autoSaveSession({
        prompt: document.getElementById('sw-ai-prompt')?.value || '',
        genre, numPanels: sourceScenes.length, language: document.getElementById('sw-ai-lang')?.value || 'vi',
        characters, location, artStyle, imgRatio: document.getElementById('sw-ai-img-ratio')?.value || '9:16',
        imgNote, imgModel, imgQuality, storyText: document.getElementById('sw-text')?.value || sourceSceneText.join('\n\n'),
        scenes: _aiScenes, comicPageMode: true, panelsPerPage: _getComicPanelsPerPage(),
      });
      _toast(`Đã sinh ${_aiScenes.length} trang manhua.`, 'success');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function _renderAiScenes() {
    const card = document.getElementById('sw-ai-scenes-card');
    const wrap = document.getElementById('sw-ai-scenes');
    if (!card || !wrap) return;
    card.classList.remove('hidden');
    wrap.replaceChildren();
    const ratio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
    const aspectCSS = ratio.replace(':', '/');
    _aiScenes.forEach((scene, idx) => {
      const item = _el('div', {
        style: 'border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg2);display:flex;flex-direction:column',
      });

      // Top: image (or two thumbs side by side when there's an end frame)
      if (scene.image_url) {
        if (scene.end_image_url) {
          const row = _el('div', {
            style: 'display:grid;grid-template-columns:1fr 1fr;gap:2px;background:var(--bg3)',
          });
          const imgA = _el('img', {
            src: scene.image_url,
            style: `width:100%;aspect-ratio:${aspectCSS};object-fit:cover;display:block`,
            loading: 'lazy',
            title: 'Ảnh bắt đầu cảnh',
          });
          const imgB = _el('img', {
            src: scene.end_image_url,
            style: `width:100%;aspect-ratio:${aspectCSS};object-fit:cover;display:block`,
            loading: 'lazy',
            title: 'Ảnh kết thúc cảnh (sẽ morph tới đây)',
          });
          imgA.onerror = () => { imgA.style.display = 'none'; };
          imgB.onerror = () => { imgB.style.display = 'none'; };
          row.appendChild(imgA);
          row.appendChild(imgB);
          item.appendChild(row);
        } else {
          const img = _el('img', {
            src: scene.image_url,
            style: `width:100%;aspect-ratio:${aspectCSS};object-fit:cover;display:block;background:var(--bg3)`,
            loading: 'lazy',
          });
          img.onerror = () => { img.style.display = 'none'; };
          item.appendChild(img);
        }
      } else {
        item.appendChild(_el('div', {
          style: `width:100%;aspect-ratio:${aspectCSS};background:var(--bg3);display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:24px`,
        }, '⏳'));
      }

      const meta = _el('div', { style: 'padding:8px;display:flex;flex-direction:column;gap:6px;flex:1' });
      const sceneLabel = scene.comic_page
        ? `Trang ${idx + 1}${scene.panel_count ? ` · ${scene.panel_count} khung` : ''}`
        : `Cảnh ${idx + 1}`;
      meta.appendChild(_el('div', { class: 'badge badge-accent', style: 'align-self:flex-start' }, sceneLabel));
      meta.appendChild(_el('div', {
        style: 'font-size:11px;color:var(--text2);line-height:1.4;max-height:60px;overflow:hidden;flex:1',
      }, scene.text.slice(0, 120) + (scene.text.length > 120 ? '...' : '')));

      // Per-scene actions: regenerate start frame, generate/regenerate end frame
      if (scene.image_url) {
        const actions = _el('div', {
          style: 'display:flex;gap:4px;flex-wrap:wrap;margin-top:auto',
        });
        const endBtn = _el('button', {
          class: 'btn btn-secondary btn-sm',
          style: 'flex:1;min-width:0;font-size:10px;padding:4px 6px',
          onclick: () => aiGenerateEndFrame(idx),
          title: 'Sinh ảnh kết thúc cảnh để có chuyển động khi render',
        }, scene.end_image_url ? '🔄 Đổi ảnh end' : '✨ Sinh ảnh end');
        actions.appendChild(endBtn);
        if (scene.end_image_url) {
          const clearBtn = _el('button', {
            class: 'btn btn-secondary btn-sm',
            style: 'font-size:10px;padding:4px 6px',
            onclick: () => { scene.end_image_url = ''; _renderAiScenes(); },
            title: 'Xoá ảnh end (về hiệu ứng tĩnh + Ken Burns)',
          }, '✖');
          actions.appendChild(clearBtn);
        }
        meta.appendChild(actions);
      }

      item.appendChild(meta);
      wrap.appendChild(item);
    });
  }

  // ── End-frame generation for a specific scene ───────────────────────────
  // Calls /api/story/ai_generate_end_frame, which edits the scene's start
  // image to produce a slightly different end-frame for the morph effect.
  async function aiGenerateEndFrame(idx) {
    const scene = _aiScenes[idx];
    if (!scene || !scene.image_url) return _toast('Cảnh chưa có ảnh start.', 'warning');

    const artStyle = document.getElementById('sw-ai-art-style')?.value || '';
    const imgModel = (document.getElementById('sw-ai-img-model')?.value || 'cx/gpt-5.5-image').trim();
    const imgQuality = document.getElementById('sw-ai-img-quality')?.value || 'standard';
    const imgRatio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
    const seed = _hashSeed(scene.text + '|end');

    _toast(`Đang sinh ảnh kết thúc cho cảnh ${idx + 1}...`, 'info');
    _log(`▶ Sinh end-frame cho cảnh ${idx + 1}...`, 'info');
    const t0 = Date.now();
    try {
      const r = await API.post('/api/story/ai_generate_end_frame', {
        start_image_url: scene.image_url,
        scene_text: scene.text,
        art_style: artStyle,
        model: imgModel,
        quality: imgQuality,
        ratio: imgRatio,
        seed,
        session_id: window._aiSessionId || '',
      }, { silent: true });
      if (r.ok && r.image_url) {
        _aiScenes[idx].end_image_url = r.image_url;
        _renderAiScenes();
        _log(`  ✓ Cảnh ${idx + 1}: end-frame OK trong ${((Date.now() - t0) / 1000).toFixed(1)}s`, 'success');
        _toast(`Đã có ảnh kết thúc cho cảnh ${idx + 1}. Render sẽ tự động morph.`, 'success');
      } else {
        _log(`  ✗ End-frame cảnh ${idx + 1}: ${r.error || ''}`, 'error');
        _toast(`Lỗi: ${r.error || 'không tạo được ảnh end'}`, 'error');
      }
    } catch (e) {
      _log(`  ✗ End-frame cảnh ${idx + 1}: ${e.message || e}`, 'error');
      _toast(`Lỗi: ${e.message || e}`, 'error');
    }
  }

  // ── Bulk: generate end-frames for ALL scenes that don't have one yet ────
  async function aiGenerateAllEndFrames() {
    const todo = _aiScenes
      .map((s, i) => ({ s, i }))
      .filter(({ s }) => s.image_url && !s.end_image_url);
    if (!todo.length) {
      return _toast(_aiScenes.length
        ? 'Tất cả cảnh đều đã có ảnh end (hoặc chưa có ảnh start).'
        : 'Chưa có cảnh nào.', 'info');
    }
    _log(`▶ Sinh end-frame song song cho ${todo.length} cảnh...`, 'info');
    const t0 = Date.now();

    // Limit concurrency to avoid 9Router rate limit. 4 is a safe default.
    const CONCURRENCY = 4;
    let next = 0;
    let okCount = 0, failCount = 0;
    async function worker() {
      while (true) {
        const cur = next++;
        if (cur >= todo.length) return;
        const { i } = todo[cur];
        try {
          await aiGenerateEndFrame(i);
          okCount++;
        } catch {
          failCount++;
        }
      }
    }
    await Promise.all(Array(CONCURRENCY).fill(0).map(worker));
    _log(`  ─ Bulk end-frame: ${okCount}/${todo.length} thành công · tổng ${((Date.now() - t0) / 1000).toFixed(1)}s`, okCount === todo.length ? 'success' : 'warning');
  }

  function aiSendToPanels() {
    if (!_aiScenes.length) return _toast('Chưa có cảnh nào.', 'warning');
    const panels = _aiScenes.map(s => ({
      image_url: s.image_url || '',
      end_image_url: s.end_image_url || '',
      text: s.text || '',
    }));
    setPanels(panels);
    _toast(`Đã gửi ${panels.length} cảnh sang Panels & Render. Cuộn xuống để render video.`, 'success');
    document.getElementById('sw-panels-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // ── One-click: send to panels + auto trigger render with sensible defaults ─
  async function aiCreateVideo() {
    if (!_aiScenes.length) return _toast('Chưa có cảnh nào.', 'warning');
    const withImages = _aiScenes.filter(s => s.image_url).length;
    if (!withImages) return _toast('Chưa có ảnh — hãy chạy "Tạo truyện + Sinh ảnh" trước.', 'warning');

    _log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━', 'banner');
    _log(`🎬 Bắt đầu render video từ ${withImages} cảnh có ảnh`, 'banner');

    // Send scenes to panels — pass end_image_url so the renderer can morph
    // between the two frames if both are available (Step 2 — "khung hình động")
    const panels = _aiScenes.map(s => ({
      image_url: s.image_url || '',
      end_image_url: s.end_image_url || '',
      text: s.text || '',
    }));
    setPanels(panels);
    _log(`  → Đã đẩy ${panels.length} panels sang phần render`, 'detail');

    // Pick render preset matching the chosen image ratio (so images aren't squashed)
    const imgRatio = document.getElementById('sw-ai-img-ratio')?.value || '9:16';
    const presetSel = document.getElementById('sw-render-preset');
    if (presetSel) {
      if (imgRatio === '16:9') presetSel.value = 'youtube';
      else if (imgRatio === '1:1') presetSel.value = 'square';
      else presetSel.value = 'shorts';
    }
    _log(`  → Preset video: ${presetSel?.value} (theo ratio ${imgRatio})`, 'detail');

    // Set TTS language to match story language
    const lang = document.getElementById('sw-ai-lang')?.value || 'vi';
    const targetLangSel = document.getElementById('sw-target-lang');
    if (targetLangSel) targetLangSel.value = lang;
    refreshVoices();

    // Wait one tick so voice list rebuilds
    await new Promise(r => setTimeout(r, 100));

    // Ensure a voice is picked
    const voiceSel = document.getElementById('sw-tts-voice');
    if (voiceSel && !voiceSel.value && voiceSel.options.length > 0) {
      // Pick first non-disabled option
      for (const opt of voiceSel.options) {
        if (!opt.disabled && opt.value) { voiceSel.value = opt.value; break; }
      }
    }
    _log(`  → TTS: ${document.getElementById('sw-tts-engine')?.value} · giọng ${voiceSel?.value || '(auto)'}`, 'detail');

    _toast('🎬 Bắt đầu tạo video... Cuộn xuống để xem tiến trình.', 'info');

    // Scroll to render section
    document.getElementById('sw-render-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Trigger render after a small delay (so UI updates)
    setTimeout(() => {
      try {
        if (typeof window.storyRender === 'function') {
          window.storyRender();
        } else {
          render();
        }
      } catch (e) {
        _log('✗ Lỗi gọi render: ' + (e.message || e), 'error');
        _toast('Lỗi khi gọi render: ' + (e.message || e), 'error');
      }
    }, 300);
  }

  function aiClear() {
    const textArea = document.getElementById('sw-text');
    if (textArea) textArea.value = '';
    const status = document.getElementById('sw-ai-status');
    if (status) status.textContent = '';
    _aiScenes = [];
    document.getElementById('sw-ai-scenes-card')?.classList.add('hidden');
    document.getElementById('sw-ai-progress')?.classList.add('hidden');
    _toast('Đã xoá nội dung.', 'info');
  }

  // ── Session save/load ─────────────────────────────────────────────────
  async function _autoSaveSession(data) {
    try {
      const payload = {
        prompt: data.prompt || '',
        title: (data.prompt || '').slice(0, 50),
        genre: data.genre || '',
        num_panels: data.numPanels || 8,
        language: data.language || 'vi',
        characters: data.characters || [],
        location: data.location || '',
        art_style: data.artStyle || '',
        img_ratio: data.imgRatio || '9:16',
        img_note: data.imgNote || '',
        img_model: data.imgModel || 'cx/gpt-5.5-image',
        img_quality: data.imgQuality || 'standard',
        comic_page_mode: !!data.comicPageMode,
        comic_panels_per_page: data.panelsPerPage || 12,
        story_text: data.storyText || '',
        scenes: (data.scenes || []).map(s => ({
          text: s.text || '',
          image_prompt: s.image_prompt || '',
          image_url: s.image_url || '',
          end_image_url: s.end_image_url || '',
          comic_page: !!s.comic_page,
          panel_count: s.panel_count || 0,
          characters: Array.isArray(s.characters) ? s.characters : [],
        })),
      };
      await API.post('/api/story/ai_sessions/save', payload);
    } catch (e) {
      console.warn('Auto-save session failed:', e);
    }
  }

  async function aiLoadSessions() {
    try {
      const r = await fetch('/api/story/ai_sessions').then(res => res.json());
      if (!r.ok || !r.sessions?.length) {
        _toast('Chưa có session nào được lưu.', 'info');
        return;
      }
      // Show a simple selection
      const items = r.sessions.slice(0, 20);
      const msg = items.map((s, i) => `${i + 1}. [${s.created_at}] ${s.title} (${s.num_scenes} cảnh, ${s.genre || 'tự do'})`).join('\n');
      const choice = prompt('Chọn session (nhập số):\n\n' + msg);
      if (!choice) return;
      const idx = parseInt(choice, 10) - 1;
      if (idx < 0 || idx >= items.length) return _toast('Lựa chọn không hợp lệ.', 'warning');
      const loadRes = await API.post('/api/story/ai_sessions/load', { id: items[idx].id });
      if (!loadRes.ok) return _toast('Lỗi load: ' + (loadRes.error || ''), 'error');
      _applySession(loadRes.session);
      _toast('Đã load session: ' + items[idx].title, 'success');
    } catch (e) {
      _toast('Lỗi: ' + (e.message || e), 'error');
    }
  }

  function _applySession(s) {
    if (!s) return;
    // Fill form fields
    const setVal = (id, v) => { const el = document.getElementById(id); if (el && v) el.value = v; };
    setVal('sw-ai-prompt', s.prompt);
    setVal('sw-ai-genre', s.genre);
    setVal('sw-ai-panels', s.num_panels);
    setVal('sw-ai-lang', s.language);
    setVal('sw-ai-location', s.location);
    setVal('sw-ai-art-style', s.art_style);
    setVal('sw-ai-img-ratio', s.img_ratio);
    setVal('sw-ai-img-note', s.img_note);
    setVal('sw-ai-img-model', s.img_model);
    setVal('sw-ai-img-quality', s.img_quality);
    const comicMode = document.getElementById('sw-ai-comic-page-mode');
    if (comicMode) comicMode.checked = !!s.comic_page_mode;
    setVal('sw-ai-comic-panels-per-page', s.comic_panels_per_page);
    setVal('sw-text', s.story_text);

    // Restore characters
    const charsWrap = document.getElementById('sw-ai-chars');
    if (charsWrap && s.characters?.length) {
      charsWrap.replaceChildren();
      for (const c of s.characters) {
        const row = _el('div', { class: 'sw-ai-char-row', style: 'display:grid;grid-template-columns:140px 1fr 36px;gap:6px;margin-bottom:5px;align-items:center' });
        const nameInput = _el('input', { type: 'text', placeholder: 'Tên', class: 'sw-ai-char-name', style: 'font-size:12px;padding:6px 8px' });
        nameInput.value = c.name || '';
        const descInput = _el('input', { type: 'text', placeholder: 'Mô tả', class: 'sw-ai-char-desc', style: 'font-size:12px;padding:6px 8px' });
        descInput.value = c.description || '';
        const btn = _el('button', { class: 'btn btn-danger btn-sm', type: 'button', style: 'padding:4px 8px' }, '✕');
        btn.addEventListener('click', () => row.remove());
        row.appendChild(nameInput);
        row.appendChild(descInput);
        row.appendChild(btn);
        charsWrap.appendChild(row);
      }
    }

    // Restore scenes preview
    if (s.scenes?.length) {
      _aiScenes = s.scenes.map(sc => ({
        text: sc.text || '',
        image_prompt: sc.image_prompt || '',
        image_url: sc.image_url || '',
        end_image_url: sc.end_image_url || '',
        comic_page: !!sc.comic_page,
        panel_count: sc.panel_count || 0,
        characters: Array.isArray(sc.characters) ? sc.characters : [],
      }));
      _renderAiScenes();
    }
    _updateComicPageEstimate();
  }

  // ── Export ─────────────────────────────────────────────────────────────
  Object.assign(window, {
    storySwitchSource: switchSource,
    storyCatalogSwitch: catalogSwitch,
    // Multi-source search
    storyMultiSearch: multiSearch,
    storyMangaPlusSwitchLang: mangaPlusSwitchLang,
    // NetTruyen (legacy alias — still callable)
    storyNtSearch: ntSearch,
    // MangaDex
    storyMangaSearch: mangaSearch,
    storyMangaReloadChapters: reloadChapters,
    storyMangaClearSelection: clearMangaSelection,
    // Smart chapter URL extractor
    storyExtractChapter: extractChapter,
    // Manual URL list (legacy advanced)
    storyUrlsLoad: urlsLoad,
    // Comic OCR (legacy)
    storyComicUpload: comicUpload,
    storyComicOcr: comicOcr,
    // AI Story Generation
    storyAiGenerate: aiGenerate,
    storyAiFullPipeline: aiFullPipeline,
    storyAiAddChar: addChar,
    storyAiUploadRefImage: aiUploadRefImage,
    storyAiClearRefImage: aiClearRefImage,
    storyAiUploadCharRef: uploadCharRef,
    storyAiGenerateCharImage: storyAiGenerateCharImage,
    storyAiUploadSceneRef: storyAiUploadSceneRef,
    storyAiAddSceneRefUrl: storyAiAddSceneRefUrl,
    storyNovelSearch: novelSearch,
    storyNovelLoadChapter: novelLoadChapter,
    storyToggleChaptersGrid: toggleChaptersGrid,
    storyNovelRemoveImported: removeImported,
    storyNovelClearImported: clearImported,
    storyNovelSendToAiScript: sendToAiScript,
    storyNovelAnalyzeCharacters: novelAnalyzeCharacters,
    storyNovelImportCharactersToAi: novelImportCharactersToAi,
    storyNovelLoadSavedCharacters: novelLoadSavedCharacters,
    storyNovelSplitScenes: novelSplitScenes,
    storyAiAutoAssignSceneCharacters: storyAiAutoAssignSceneCharacters,
    storyAiGenerateSingleSceneImage: storyAiGenerateSingleSceneImage,
    storyAiGenerateAllScenesImages: storyAiGenerateAllScenesImages,
    storyAiGenerateComicPages: storyAiGenerateComicPages,
    storyAiSendToPanels: aiSendToPanels,
    storyAiCreateVideo: aiCreateVideo,
    storyAiClear: aiClear,
    storyAiLoadSessions: aiLoadSessions,
    storyToggleSection: toggleSection,
    storyAiCancel: aiCancel,
    // End-frame morph helpers (per-scene + bulk)
    storyAiGenerateEndFrame: aiGenerateEndFrame,
    storyAiGenerateAllEndFrames: aiGenerateAllEndFrames,
    // Panels
    storyBuildNarration: buildNarration,
    storyPanelsClearTexts: panelsClearTexts,
    storyPanelsReverse: panelsReverse,
    storyDownloadZip: downloadZip,
    // Render
    storyTtsPreview: ttsPreview,
    storyRender: render,
    storyCancelRender: cancelRender,
  });

  // Load available image models from 9Router → populate the model dropdown.
  // The newest model (highest version number) is auto-selected as default.
  async function _loadAiImageModels() {
    const sel = document.getElementById('sw-ai-img-model');
    if (!sel) return;
    try {
      const r = await fetch('/api/story/ai_image_models').then(res => res.json());
      if (!r.ok || !Array.isArray(r.models) || !r.models.length) return;

      // Pick newest = highest version-like suffix (e.g. cx/gpt-5.5-image > cx/gpt-5.4-image)
      // Falls back to first item if no version pattern detected.
      const newestId = _pickNewestModel(r.models);

      sel.replaceChildren();
      // Group by prefix (cx/, dalle/, etc.)
      const grouped = {};
      for (const m of r.models) {
        const prefix = (m.id || '').split('/')[0] || 'other';
        (grouped[prefix] = grouped[prefix] || []).push(m);
      }
      
      // Add optgroups for each provider
      const _labelMap = {
        openai: '🟢 OpenAI', cx: '⭐ Codex (SSE streaming)', nb: '🍌 NanoBanana',
        google: '🔷 Google', sdwebui: '🖥 Local (SD WebUI)', flux: '⚡ FLUX',
      };
      for (const prefix of Object.keys(grouped)) {
        const grp = document.createElement('optgroup');
        grp.label = _labelMap[prefix] || prefix;
        for (const m of grouped[prefix]) {
          const opt = document.createElement('option');
          opt.value = m.id;
          // Mark newest with a star prefix in label
          const isNewest = m.id === newestId;
          opt.textContent = (isNewest ? '⭐ ' : '') + (m.label || m.id);
          if (isNewest) opt.selected = true;
          grp.appendChild(opt);
        }
        sel.appendChild(grp);
      }
      
      // Always default to the newest model (override any existing selection)
      sel.value = newestId;
      _log(`📸 Đã load ${r.models.length} image models · mặc định: ${newestId} (mới nhất)`, 'detail');
    } catch (e) {
      _log(`⚠ Không thể load image models từ 9Router: ${e.message}`, 'warning');
      // Keep the static defaults from HTML
    }
  }

  // Score a model id to find the newest. Higher score = newer.
  // For "cx/gpt-5.5-image" → version=5.5 → score=5.5
  // Falls back to lexical order so unknown models still rank consistently.
  function _pickNewestModel(models) {
    if (!models.length) return '';
    let best = models[0].id;
    let bestScore = -Infinity;
    for (const m of models) {
      const id = m.id || '';
      // Extract first version-like number: "5.5", "4", "3.2"
      const versionMatch = id.match(/(\d+(?:\.\d+)?)/g);
      let score = 0;
      if (versionMatch) {
        // Combine all numbers in the id (newer naming usually has higher numbers throughout)
        score = versionMatch.reduce((acc, v) => acc + parseFloat(v), 0);
      }
      // Prefer 'cx/' (Codex) over generic
      if (id.startsWith('cx/')) score += 100;
      if (id.includes('image')) score += 10;
      if (score > bestScore) {
        bestScore = score;
        best = id;
      }
    }
    return best;
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('page-story')) {
      _initLangPills();
      _initSourcePills();
      loadVoices();
      _loadAiImageModels();
      _initRefImagePreview();
      _initComicPageEstimate();
    }
  });
})();

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
    try {
      const r = await fetch('/api/story/voices').then(r => r.json());
      _ttsEngines = r.engines || [];
      engineSel.replaceChildren();
      for (const eng of _ttsEngines) {
        engineSel.appendChild(_el('option', { value: eng.id }, eng.label));
      }
      engineSel.value = (_ttsEngines.find(e => e.id === 'edge-tts')?.id) || (_ttsEngines[0]?.id || 'edge-tts');
      engineSel.addEventListener('change', refreshVoices);
      const langSel = document.getElementById('sw-target-lang');
      if (langSel) langSel.addEventListener('change', refreshVoices);
      refreshVoices();
    } catch (_) {}
  }

  function refreshVoices() {
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
      tts_engine: document.getElementById('sw-tts-engine')?.value || 'edge-tts',
      tts_voice: document.getElementById('sw-tts-voice')?.value || '',
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
      tts_engine: document.getElementById('sw-tts-engine').value,
      tts_voice: document.getElementById('sw-tts-voice').value,
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
      if (name) chars.push({ name, description: desc });
    });
    return chars;
  }

  function addChar() {
    const wrap = document.getElementById('sw-ai-chars');
    if (!wrap) return;
    const row = _el('div', { class: 'sw-ai-char-row', style: 'display:grid;grid-template-columns:150px 1fr 40px;gap:8px;margin-bottom:6px;align-items:start' });
    row.appendChild(_el('input', { type: 'text', placeholder: 'Tên nhân vật', class: 'sw-ai-char-name' }));
    row.appendChild(_el('input', { type: 'text', placeholder: 'Mô tả ngoại hình', class: 'sw-ai-char-desc' }));
    const btn = _el('button', { class: 'btn btn-danger btn-sm', type: 'button' }, '✕');
    btn.addEventListener('click', () => row.remove());
    row.appendChild(btn);
    wrap.appendChild(row);
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

    const totalSteps = numPanels + 2; // 1 text + 1 prompts + N images
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
      _log(`  ✓ Hoàn tất sau ${((Date.now() - t1) / 1000).toFixed(1)}s · ${storyText.length} ký tự · ${textRes.usage?.total_tokens || '?'} tokens`, 'success');

      // Parse scenes
      const scenes = _parseScenes(storyText);
      if (!scenes.length) throw new Error('AI không tạo được đoạn nào.');
      _log(`  📑 Đã chia thành ${scenes.length} cảnh`, 'detail');

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
        const anchorRes = await API.post('/api/story/ai_generate_anchor', {
          characters, location, art_style: artStyle, genre,
          model: imgModel, quality: imgQuality, ratio: imgRatio, seed: storySeed,
          session_id: window._aiSessionId || '',
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
            const r = await API.post('/api/story/ai_generate_portrait', {
              name: c.name, description: c.description || '',
              art_style: artStyle, model: imgModel, quality: imgQuality,
              ratio: '1:1', seed: storySeed, anchor_url: anchorUrl,
              session_id: window._aiSessionId || '',
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
        if (anchorUrl) refs.push(anchorUrl);
        for (const name of _charsInScene(scenes[sceneIdx])) {
          if (refs.length >= 3) break;
          if (portraits[name]) refs.push(portraits[name]);
        }
        if (prevImageUrl && refs.length < 4) refs.push(prevImageUrl);
        return refs;
      }

      async function _genSingleScene(i, prevImageUrl) {
        const refs = _buildRefs(i, prevImageUrl);
        const ti = Date.now();
        const imgRes = await API.post('/api/story/ai_generate_image', {
          prompt: imgPrompts[i] || `${artStyle || 'cinematic film still'}, ${scenes[i].slice(0, 100)}`,
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

  // Convert string → 32-bit positive int (deterministic seed)
  function _hashSeed(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = ((h << 5) - h) + str.charCodeAt(i);
      h |= 0;
    }
    return Math.abs(h) || 42;
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
      meta.appendChild(_el('div', { class: 'badge badge-accent', style: 'align-self:flex-start' }, `Cảnh ${idx + 1}`));
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
        story_text: data.storyText || '',
        scenes: (data.scenes || []).map(s => ({
          text: s.text || '',
          image_prompt: s.image_prompt || '',
          image_url: s.image_url || '',
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
      }));
      _renderAiScenes();
    }
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
    storyAiSendToPanels: aiSendToPanels,
    storyAiCreateVideo: aiCreateVideo,
    storyAiClear: aiClear,
    storyAiLoadSessions: aiLoadSessions,
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
      for (const prefix of Object.keys(grouped)) {
        const grp = document.createElement('optgroup');
        grp.label = prefix;
        for (const m of grouped[prefix]) {
          const opt = document.createElement('option');
          opt.value = m.id;
          // Mark newest with a star prefix in label
          opt.textContent = (m.id === newestId ? '⭐ ' : '') + (m.label || m.id);
          grp.appendChild(opt);
        }
        sel.appendChild(grp);
      }
      // Always default to the newest model (override any existing selection)
      sel.value = newestId;
      _log && _log(`📦 Đã load ${r.models.length} model · mặc định: ${newestId} (mới nhất)`, 'detail');
    } catch (_) {
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
    }
  });
})();

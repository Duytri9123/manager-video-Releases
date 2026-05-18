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
      return _toast('Nhập văn bản truyện trong tab "📝 Văn bản thuần" rồi thử lại, hoặc chuyển sang chế độ "Tự nhập từng panel".', 'warning');
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
      zoom: document.getElementById('sw-zoom').checked,
      bgm_url: document.getElementById('sw-bgm').value.trim(),
      bgm_volume: parseFloat(document.getElementById('sw-bgm-vol').value || '0.10'),
    };
    if (!payload.tts_voice) return _toast('Chưa chọn giọng đọc.', 'warning');
    try {
      const r = await API.post('/api/story/manga/render', payload);
      if (!r.ok) throw new Error(r.error || 'render failed');
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
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function pollRender(jobId) {
    if (_renderPoll) clearInterval(_renderPoll);
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
        if (r.status === 'done' || r.status === 'error') {
          clearInterval(_renderPoll); _renderPoll = null;
          const res = document.getElementById('sw-render-result');
          const txt = document.getElementById('sw-render-result-text');
          if (r.status === 'done') {
            res.classList.remove('hidden');
            txt.textContent = '✓ Hoàn tất: ' + (r.output_video_rel || r.output_video || '');

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
            }
            if (srtName) {
              dlSrt.href = '/api/story/manga/render_video?kind=srt&download=1&name=' + encodeURIComponent(srtName);
              dlSrt.style.display = '';
            } else { dlSrt.style.display = 'none'; }
            if (assName) {
              dlAss.href = '/api/story/manga/render_video?kind=ass&download=1&name=' + encodeURIComponent(assName);
              dlAss.style.display = '';
            } else { dlAss.style.display = 'none'; }

            _toast('Render xong!', 'success');
          } else {
            txt.textContent = '✗ Lỗi: ' + (r.error || 'unknown');
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

  // ── Bootstrap ─────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('page-story')) {
      _initLangPills();
      _initSourcePills();
      loadVoices();
    }
  });
})();

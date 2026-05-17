/* ─────────────────────────────────────────────────────────────────────────
 * Movie review page — UI logic.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  let _selectedInfo = null;
  let _selectedSource = 'vsmov';
  let _lastReview = null;

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

  async function refreshStatus() {
    const badge = document.getElementById('movie-status');
    if (!badge) return;
    try {
      const r = await fetch('/api/movie/status').then(r => r.json());
      const src = document.getElementById('mv-source')?.value || 'all';
      if (src === 'all') {
        badge.className = 'badge badge-green';
        badge.textContent = '📺 VSMOV + OPhim + KKPhim';
      } else if (['vsmov', 'ophim', 'kkphim'].includes(src)) {
        badge.className = 'badge badge-green';
        badge.textContent = src.toUpperCase() + ' ✓';
      } else if (r.configured) {
        badge.className = 'badge badge-green';
        badge.textContent = r.auth_method === 'v4_bearer' ? 'TMDb v4 ✓' : 'TMDb v3 ✓';
      } else {
        badge.className = 'badge badge-yellow';
        badge.textContent = 'Chưa có TMDb key';
      }
    } catch (_) { badge.className = 'badge badge-red'; badge.textContent = 'Không kết nối được API'; }
  }

  function _currentSource() {
    return document.getElementById('mv-source')?.value || 'all';
  }

  function _isVnSource(s) {
    return s === 'vsmov' || s === 'ophim' || s === 'kkphim' || s === 'all';
  }

  // Helper: route any external image URL through our proxy so the browser
  // doesn't choke on referer/CORS issues, and TMDb/OPhim/VSMOV images load
  // reliably.
  function _proxiedImg(url) {
    if (!url) return '';
    if (url.startsWith('/')) return url;
    return '/api/movie/image_proxy?url=' + encodeURIComponent(url);
  }

  async function vsmovLatest() {
    // Always honor active quick filter when called as the "default suggestion".
    return applyQuickFilter();
  }

  async function search() {
    const q = document.getElementById('mv-query').value.trim();
    if (!q) {
      return _isVnSource(_currentSource()) ? vsmovLatest() : trending();
    }
    const src = _currentSource();
    if (_isVnSource(src)) {
      try {
        // Search across all VN sources if "all", else single source
        if (src === 'all') {
          const sources = ['vsmov', 'ophim', 'kkphim'];
          const results = await Promise.all(sources.map(s =>
            API.post('/api/movie/source/' + s + '/search', { keyword: q, limit: 12 }).catch(() => ({ items: [] }))
          ));
          // Merge + dedupe by tmdb_id+title
          const seen = new Set();
          const merged = [];
          for (const r of results) {
            for (const it of (r.items || [])) {
              const key = (it.tmdb_id || '') + '|' + (it.original_title || it.title || '');
              if (!seen.has(key)) { seen.add(key); merged.push(it); }
            }
          }
          renderResults(merged, 'movie', 'all');
        } else {
          const r = await API.post('/api/movie/source/' + src + '/search', { keyword: q, limit: 24 });
          renderResults(r.items || [], 'movie', src);
        }
      } catch (e) { _toast(String(e.message || e), 'error'); }
      return;
    }
    // TMDb path
    const kind = document.getElementById('mv-kind').value;
    const lang = document.getElementById('mv-lang').value;
    try {
      const r = await API.post('/api/movie/search', { query: q, kind, language: lang });
      renderResults(r.items || [], kind, 'tmdb');
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  async function trending() {
    const src = _currentSource();
    if (_isVnSource(src)) return vsmovLatest();
    try {
      const r = await fetch('/api/movie/trending').then(r => r.json());
      if (!r.ok) throw new Error(r.error || 'API error');
      renderResults(r.items || [], 'movie', 'tmdb');
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function onSourceChange() {
    refreshStatus();
    const filters = document.getElementById('mv-vsmov-filters');
    const src = _currentSource();
    // Show VN filters only when a SINGLE VN source is picked
    if (filters) filters.style.display = (src === 'vsmov' || src === 'ophim' || src === 'kkphim') ? '' : 'none';
    if (src === 'vsmov' || src === 'ophim' || src === 'kkphim') {
      loadVsmovFilters(src);
    }
    setTimeout(trending, 50);
  }

  // ── VN-source filters (per current single source) ──
  async function loadVsmovFilters(source) {
    source = source || _currentSource();
    if (!['vsmov', 'ophim', 'kkphim'].includes(source)) return;
    try {
      const r = await fetch('/api/movie/source/' + source + '/filters').then(r => r.json());
      _fillSelect('mv-vsmov-category', r.categories || [], '— Tất cả thể loại —');
      _fillSelect('mv-vsmov-country', r.countries || [], '— Tất cả quốc gia —');
      _fillSelect('mv-vsmov-year', r.years || [], '— Tất cả năm —');
    } catch (_) {}
  }

  async function vsmovBrowse() {
    const src = _currentSource();
    if (!['vsmov', 'ophim', 'kkphim'].includes(src)) return;
    const params = {
      category: document.getElementById('mv-vsmov-category')?.value || '',
      country: document.getElementById('mv-vsmov-country')?.value || '',
      year: document.getElementById('mv-vsmov-year')?.value || '',
      limit: 24,
    };
    if (!params.category && !params.country && !params.year) return vsmovLatest();
    try {
      const r = await API.post('/api/movie/source/' + src + '/browse', params);
      renderResults(r.items || [], 'movie', src);
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function vsmovResetFilters() {
    ['mv-vsmov-category', 'mv-vsmov-country', 'mv-vsmov-year'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    vsmovLatest();
  }

  async function loadDetail(idOrSlug, kind, source) {
    const src = source || _currentSource();
    try {
      let info;
      if (['vsmov', 'ophim', 'kkphim'].includes(src) || src === 'all') {
        // Need actual source — falls back to vsmov for "all"
        const realSrc = src === 'all' ? 'vsmov' : src;
        const r = await API.post('/api/movie/source/' + realSrc + '/details', { slug: idOrSlug });
        info = r.info;
      } else {
        const r = await API.post('/api/movie/details', { tmdb_id: idOrSlug, kind });
        info = r.info;
      }
      _selectedInfo = info;
      _selectedSource = info?.source || src;
      renderDetail(info, kind, _selectedSource);
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function renderResults(items, kind, source) {
    const wrap = document.getElementById('movie-results');
    if (!wrap) return;
    wrap.replaceChildren();
    if (!items.length) {
      wrap.appendChild(_el('div', { class: 'empty-state' }, 'Không tìm thấy phim phù hợp.'));
      return;
    }
    const src = source || _currentSource();
    const currentYear = new Date().getFullYear();
    for (const it of items) {
      const id = src === 'vsmov' || src === 'ophim' || src === 'kkphim' || (src === 'all' && it.source !== 'tmdb')
        ? it.slug : it.id;
      const card = _el('div', { class: 'vcard', onclick: () => loadDetail(id, kind, src === 'all' ? it.source : src) });
      const thumb = _el('div', { class: 'vcard-thumb' });
      const posterUrl = it.poster_url || it.thumb_url || '';
      if (posterUrl) {
        const img = _el('img', { src: _proxiedImg(posterUrl), alt: '', loading: 'lazy' });
        // Fallback to placeholder on error
        img.onerror = () => {
          img.style.display = 'none';
          if (!thumb.querySelector('.vcard-thumb-ph')) {
            thumb.appendChild(_el('div', { class: 'vcard-thumb-ph' }, '🎬'));
          }
        };
        thumb.appendChild(img);
      } else {
        thumb.appendChild(_el('div', { class: 'vcard-thumb-ph' }, '🎬'));
      }

      // "MỚI" badge for current/last year, "RẠP" if chieurap flag set
      const yearNum = parseInt(it.year || (it.release_date || '').slice(0, 4), 10);
      const badges = _el('div', {
        style: 'position:absolute;top:6px;left:6px;display:flex;gap:4px;z-index:1'
      });
      if (it.chieurap) {
        badges.appendChild(_el('span', {
          style: 'background:#dc2626;color:#fff;font-size:9px;padding:2px 5px;border-radius:3px;font-weight:700'
        }, 'RẠP'));
      } else if (yearNum && yearNum >= currentYear - 1) {
        badges.appendChild(_el('span', {
          style: 'background:#16a34a;color:#fff;font-size:9px;padding:2px 5px;border-radius:3px;font-weight:700'
        }, 'MỚI'));
      }
      thumb.appendChild(badges);

      const meta = _el('div', { class: 'vcard-meta' },
        _el('div', { class: 'vcard-desc' }, it.title || ''),
        _el('div', { class: 'vcard-stats' },
          _el('span', null, '★ ' + (it.vote_average ? Number(it.vote_average).toFixed(1) : '—')),
          _el('span', null, String(it.year || (it.release_date || '').slice(0, 4) || '')),
          _el('span', { class: 'badge badge-gray', style: 'font-size:9px' }, (it.source || src).toUpperCase()),
        ),
      );
      card.appendChild(thumb); card.appendChild(meta);
      wrap.appendChild(card);
    }
  }

  // Need to remove the old loadDetail since we redefined it above
  // (Original removed)

  function _fillSelect(id, items, placeholder) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.replaceChildren(_el('option', { value: '' }, placeholder));
    for (const it of items) {
      sel.appendChild(_el('option', { value: it.slug }, it.name));
    }
  }

  function renderDetail(info, kind, source) {
    const card = document.getElementById('movie-detail-card');
    const reviewCard = document.getElementById('movie-review-card');
    const titleEl = document.getElementById('mv-detail-title');
    const body = document.getElementById('mv-detail-body');
    if (!card || !body || !titleEl) return;

    const year = (info.release_date || info.first_air_date || '').slice(0, 4) || info.year || '';
    titleEl.textContent = (info.title || info.name || '') + (year ? ' (' + year + ')' : '');
    body.replaceChildren();

    // ── Layout: poster 200px fixed-width on left, info on right ──
    const grid = _el('div', { style: 'display:grid;grid-template-columns:200px 1fr;gap:18px;align-items:start' });

    const posterCol = _el('div', null);
    const posterUrl = info.poster_url || (info.poster_path ? 'https://image.tmdb.org/t/p/w500' + info.poster_path : '');
    if (posterUrl) {
      posterCol.appendChild(_el('img', {
        src: _proxiedImg(posterUrl),
        alt: '',
        style: 'width:200px;max-width:100%;border-radius:8px;display:block;box-shadow:0 4px 16px rgba(0,0,0,.18)'
      }));
    }

    const infoCol = _el('div', null);
    const dirCrew = (info.credits?.crew || []).find(c => c.job === 'Director');
    const cast = (info.credits?.cast || []).slice(0, 6).map(c => c.name).join(', ');
    const genres = (info.genres || []).map(g => g.name).join(', ');
    const lines = [
      ['Đạo diễn', dirCrew ? dirCrew.name : '—'],
      ['Diễn viên', cast || '—'],
      ['Thể loại', genres || '—'],
      ['Thời lượng', (info.runtime || (info.episode_run_time || [])[0] || '—') + ' phút'],
      ['Điểm TMDb', info.vote_average != null ? info.vote_average.toFixed(1) + '/10' : '—'],
      ['Ngày phát hành', info.release_date || info.first_air_date || '—'],
    ];
    for (const [k, v] of lines) {
      infoCol.appendChild(_el('div', { class: 'mb-4 text-sm' },
        _el('span', { class: 'text-muted' }, k + ': '),
        _el('span', null, String(v)),
      ));
    }
    if (info.overview) {
      infoCol.appendChild(_el('div', {
        class: 'mt-12 text-sm',
        style: 'line-height:1.55;background:var(--bg3);border:1px solid var(--border);padding:10px 12px;border-radius:6px'
      }, info.overview));
    } else {
      infoCol.appendChild(_el('div', {
        class: 'mt-8 text-sm text-muted',
        style: 'background:var(--warning-bg);border:1px solid rgba(183,121,31,.2);padding:8px 12px;border-radius:6px'
      }, '⚠ Nguồn không có mô tả. Kịch bản sẽ tạo dựa trên metadata + Wikipedia (nếu có). Bạn có thể bổ sung trong "Ghi chú thêm".'));
    }

    // Source-specific extras: AI enrich button + watch link + embed player + episode list
    const isVnSource = ['vsmov', 'ophim', 'kkphim'].includes(source);
    if (isVnSource || (info.episode_servers && info.episode_servers.length)) {
      const extras = _el('div', { class: 'mt-12' });

      // AI enrich button — visible whenever overview is missing
      if (!info.overview || info.overview.length < 80) {
        const aiBtn = _el('button', {
          type: 'button',
          class: 'btn btn-primary btn-sm',
          onclick: () => movieAiEnrich(),
        }, '🤖 Dùng AI lấy nội dung phim');
        extras.appendChild(_el('div', { class: 'mt-8' }, aiBtn));
      }

      // Watch link
      const watchUrl = info.watch_url || info.vsmov_url;
      if (watchUrl) {
        extras.appendChild(_el('div', { class: 'mt-8 mb-8' },
          _el('a', { href: watchUrl, target: '_blank', rel: 'noopener',
                     class: 'btn btn-secondary btn-sm' },
              '🌐 Xem trên ' + (info.source_label || (source || '').toUpperCase())),
          ' ',
          _el('button', {
            type: 'button',
            class: 'btn btn-success btn-sm',
            onclick: () => movieToggleEmbed(),
          }, '▶ Xem ngay tại đây'),
        ));
      }

      // Embed player container (hidden by default)
      const eps = info.episode_servers || [];
      if (eps.length) {
        const embedWrap = _el('div', {
          id: 'mv-embed-wrap',
          class: 'hidden',
          style: 'margin-top:10px;background:#000;border-radius:6px;overflow:hidden',
        });
        const iframe = _el('iframe', {
          id: 'mv-embed-iframe',
          src: '',
          allow: 'autoplay; encrypted-media; fullscreen',
          allowfullscreen: 'true',
          style: 'width:100%;height:380px;border:0;display:block',
        });
        embedWrap.appendChild(iframe);
        extras.appendChild(embedWrap);

        const wrap = _el('div', { class: 'mt-8' });
        wrap.appendChild(_el('div', { class: 'section-title' }, `▶ ${eps.length} tập / nguồn`));
        const grid = _el('div', {
          style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px;max-height:160px;overflow-y:auto'
        });
        eps.forEach((ep, i) => {
          const epLabel = ep.name || ('Tập ' + (i + 1));
          const link = ep.embed || ep.m3u8 || '';
          grid.appendChild(_el('button', {
            type: 'button',
            class: 'btn btn-secondary btn-sm',
            style: 'padding:4px 8px;font-size:11px;text-align:center',
            title: ep.server || '',
            onclick: () => movieLoadEpisode(link, ep),
          }, epLabel));
        });
        wrap.appendChild(grid);
        extras.appendChild(wrap);
      }

      if (extras.childNodes.length) infoCol.appendChild(extras);
    }

    grid.appendChild(posterCol);
    grid.appendChild(infoCol);

    // CTA: scroll to review section
    const cta = _el('div', { class: 'btn-group', style: 'margin-top:14px' },
      _el('button', { class: 'btn btn-primary', onclick: () => {
        document.getElementById('movie-review-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }}, '👇 Tạo kịch bản review'),
    );

    body.appendChild(grid);
    body.appendChild(cta);
    card.classList.remove('hidden');
    reviewCard.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function clearDetail() {
    _selectedInfo = null;
    document.getElementById('movie-detail-card')?.classList.add('hidden');
    document.getElementById('movie-review-card')?.classList.add('hidden');
    const out = document.getElementById('mv-review-output');
    if (out) { out.classList.add('hidden'); out.style.display = ''; }
  }

  async function generateReview() {
    if (!_selectedInfo) return _toast('Hãy chọn một phim trước.', 'warning');
    const payload = {
      info: _selectedInfo,
      source: _selectedSource,
      template: document.getElementById('mv-template').value,
      length_sec: parseInt(document.getElementById('mv-length').value || '90', 10),
      provider: document.getElementById('mv-provider').value,
      target_lang: document.getElementById('mv-lang').value,
      extra_notes: document.getElementById('mv-extra').value.trim(),
    };
    try {
      const r = await API.post('/api/movie/review', payload);
      _lastReview = r.review || {};
      const out = document.getElementById('mv-review-output');
      const ta = document.getElementById('mv-script-text');
      const meta = document.getElementById('mv-script-meta');
      const rev = _lastReview;
      const text = (rev.hook ? rev.hook + '\n\n' : '') + (rev.script || '');
      ta.value = text;
      ta.style.minHeight = '260px';

      const parts = [];
      if (rev._fallback) parts.push('⚠ Fallback (chưa có LLM key cho ' + payload.provider + ')');
      else parts.push('✓ ' + (payload.provider === 'auto' ? 'LLM (auto)' : payload.provider.toUpperCase()));
      parts.push('Hashtags: ' + ((rev.hashtags || []).join(' ') || '—'));
      if (rev.thumbnail_idea) parts.push('Thumbnail: ' + rev.thumbnail_idea);
      meta.textContent = parts.join(' · ');

      // Force visible regardless of cached css state
      out.classList.remove('hidden');
      out.style.display = 'block';
      out.scrollIntoView({ behavior: 'smooth', block: 'start' });

      // Render gallery
      renderGallery(rev.images || []);

      if (rev._fallback) {
        const wikiNote = rev.wiki_chars ? ` (kèm ${rev.wiki_chars} ký tự Wikipedia)` : '';
        _toast('Kịch bản tạo ở chế độ fallback' + wikiNote + '. Đặt API key DeepSeek/Groq/OpenAI để có chất lượng cao hơn.', 'warning');
      } else {
        _toast('Đã tạo kịch bản (' + text.length + ' ký tự, ' + (rev.images || []).length + ' ảnh).', 'success');
      }
    } catch (e) {
      console.error(e);
      _toast(String(e.message || e), 'error');
    }
  }

  function copyScript() {
    const v = document.getElementById('mv-script-text').value;
    if (!v) return _toast('Chưa có kịch bản.', 'warning');
    navigator.clipboard?.writeText(v);
    _toast('Đã copy ' + v.length + ' ký tự.', 'success');
  }

  function sendToTTS() {
    const v = document.getElementById('mv-script-text').value;
    if (!v) return _toast('Chưa có kịch bản.', 'warning');
    window._pendingTTSText = v;
    if (window.switchPage) switchPage('process');
    _toast('Đã gửi sang trang Xử lý — paste vào ô TTS.', 'info');
  }

  // ── Voice list (engines + grouped voices per language) ──
  let _engines = [];

  async function loadVoices() {
    const engineSel = document.getElementById('mv-render-engine');
    if (!engineSel) return;
    try {
      const r = await fetch('/api/movie/voices').then(r => r.json());
      _engines = r.engines || [];
      engineSel.replaceChildren();
      for (const eng of _engines) {
        engineSel.appendChild(_el('option', { value: eng.id }, eng.label));
      }
      // Default engine = edge-tts
      engineSel.value = (_engines.find(e => e.id === 'edge-tts')?.id) || (_engines[0]?.id || 'edge-tts');
      engineSel.addEventListener('change', refreshVoices);
      refreshVoices();
    } catch (_) {}
  }

  function refreshVoices() {
    const engineId = document.getElementById('mv-render-engine')?.value || 'edge-tts';
    const lang = document.getElementById('mv-lang')?.value || 'vi';
    const voiceSel = document.getElementById('mv-render-voice');
    if (!voiceSel) return;
    voiceSel.replaceChildren();

    const eng = _engines.find(e => e.id === engineId);
    if (!eng) {
      voiceSel.appendChild(_el('option', { value: '' }, '(không có)'));
      return;
    }
    const list = (eng.voices && eng.voices[lang]) || [];
    if (!list.length) {
      // Fall back to vi if user picked an engine that doesn't support the language
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
    // Set default voice for this engine if none selected
    voiceSel.value = voiceSel.value || eng.default || (list[0] && list[0][0]) || '';

    // Show/hide rate vs fpt-speed depending on engine
    const rateField = document.getElementById('mv-render-rate')?.closest('.field');
    const fptField = document.getElementById('mv-render-fpt-speed')?.closest('.field');
    if (rateField) rateField.style.display = (engineId === 'edge-tts') ? '' : 'none';
    if (fptField) fptField.style.display = (engineId === 'fpt-ai') ? '' : 'none';
  }

  async function ttsPreview() {
    const text = (document.getElementById('mv-script-text').value || '').trim().split('\n').filter(l => l.trim())[0]
      || 'Đây là đoạn nghe thử giọng đọc.';
    const payload = {
      text,
      tts_engine: document.getElementById('mv-render-engine')?.value || 'edge-tts',
      tts_voice: document.getElementById('mv-render-voice')?.value || '',
      tts_rate: document.getElementById('mv-render-rate')?.value || '+0%',
      tts_pitch: '+0Hz',
      fpt_speed: parseInt(document.getElementById('mv-render-fpt-speed')?.value || '0', 10),
    };
    if (!payload.tts_voice) return _toast('Chưa chọn giọng.', 'warning');
    try {
      LoadingUI.start('Đang tổng hợp...');
      const csrf = document.cookie.match(/dt_csrf=([^;]*)/)?.[1] || '';
      const headers = { 'Content-Type': 'application/json' };
      if (csrf) headers['X-CSRF-Token'] = decodeURIComponent(csrf);
      const r = await fetch('/api/tts_preview', {
        method: 'POST', headers, body: JSON.stringify(payload),
      });
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
    } finally { LoadingUI.stop(); }
  }

  // ── Render ──
  let _renderPoll = null;

  function _selectedImageUrls() {
    const grid = document.getElementById('mv-gallery');
    if (!grid) return [];
    const tiles = Array.from(grid.querySelectorAll('.mv-tile'));
    const sel = tiles.filter(t => t.classList.contains('selected'));
    return (sel.length ? sel : tiles).map(t => t.dataset.url).filter(Boolean);
  }

  async function render() {
    const script = document.getElementById('mv-script-text').value.trim();
    if (!script) return _toast('Kịch bản trống.', 'warning');
    const images = _selectedImageUrls();
    if (!images.length) return _toast('Cần ít nhất 1 ảnh.', 'warning');

    const payload = {
      script,
      images,
      title: (_selectedInfo?.title || _selectedInfo?.name || 'movie_review'),
      preset: document.getElementById('mv-render-preset').value,
      fps: parseInt(document.getElementById('mv-render-fps').value || '30', 10),
      tts_engine: document.getElementById('mv-render-engine').value,
      tts_voice: document.getElementById('mv-render-voice').value,
      tts_rate: document.getElementById('mv-render-rate').value,
      tts_lang: document.getElementById('mv-lang').value,
      fpt_speed: parseInt(document.getElementById('mv-render-fpt-speed').value || '0', 10),
      crossfade_sec: parseFloat(document.getElementById('mv-render-fade').value || '0.6'),
      zoom: document.getElementById('mv-render-zoom').checked,
      bgm_url: document.getElementById('mv-render-bgm').value.trim(),
      bgm_volume: parseFloat(document.getElementById('mv-render-bgm-vol').value || '0.12'),
    };
    if (!payload.tts_voice) return _toast('Chưa chọn giọng đọc — kiểm tra dropdown.', 'warning');
    try {
      const r = await API.post('/api/movie/render', payload);
      if (!r.ok) throw new Error(r.error || 'render failed');
      _toast('Đã bắt đầu render. Tiến trình hiển thị bên dưới.', 'info');
      const wrap = document.getElementById('mv-render-status');
      const bar = document.getElementById('mv-render-bar');
      const msg = document.getElementById('mv-render-msg');
      const pct = document.getElementById('mv-render-pct');
      const res = document.getElementById('mv-render-result');
      wrap.classList.remove('hidden');
      res.classList.add('hidden');
      bar.style.width = '0%'; pct.textContent = '0%'; msg.textContent = 'Đang khởi tạo...';
      _pollRender(r.job_id);
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  function _pollRender(jobId) {
    if (_renderPoll) clearInterval(_renderPoll);
    _renderPoll = setInterval(async () => {
      try {
        const r = await fetch('/api/movie/render_status?job_id=' + encodeURIComponent(jobId)).then(r => r.json());
        if (!r.ok) return;
        const bar = document.getElementById('mv-render-bar');
        const pct = document.getElementById('mv-render-pct');
        const msg = document.getElementById('mv-render-msg');
        bar.style.width = (r.progress || 0) + '%';
        pct.textContent = (r.progress || 0) + '%';
        msg.textContent = r.message || r.status;
        if (r.status === 'done' || r.status === 'error') {
          clearInterval(_renderPoll); _renderPoll = null;
          const res = document.getElementById('mv-render-result');
          const txt = document.getElementById('mv-render-result-text');
          const link = document.getElementById('mv-render-open');
          if (r.status === 'done') {
            res.classList.remove('hidden');
            const player = document.getElementById('mv-render-player');
            const downloadLink = document.getElementById('mv-render-download');
            const fileName = (r.output_rel || r.output_path || '').replace(/^.*[\\/]/, '');
            txt.textContent = '✓ Hoàn tất: ' + (r.output_rel || r.output_path);
            // In-page preview via streaming endpoint
            if (fileName) {
              player.src = '/api/movie/render_video?name=' + encodeURIComponent(fileName);
              player.classList.remove('hidden');
              try { player.load(); } catch (_) {}
              if (downloadLink) {
                downloadLink.href = '/api/movie/render_video?download=1&name=' + encodeURIComponent(fileName);
              }
            }
            link.href = downloadLink ? downloadLink.href : '#';
            _toast('Render xong: ' + (r.output_rel || r.output_path), 'success');
          } else {
            txt.textContent = '✗ Lỗi: ' + (r.error || 'unknown');
            link.removeAttribute('href');
            _toast('Render lỗi: ' + (r.error || ''), 'error');
          }
        }
      } catch (_) {}
    }, 1500);
  }

  function cancelRender() {
    if (_renderPoll) { clearInterval(_renderPoll); _renderPoll = null; }
    document.getElementById('mv-render-status')?.classList.add('hidden');
    const player = document.getElementById('mv-render-player');
    if (player) {
      try { player.pause(); player.removeAttribute('src'); player.load(); } catch (_) {}
      player.classList.add('hidden');
    }
  }

  function goToContent() {
    if (window.switchPage) switchPage('content');
  }

  // ── Embed player ──
  function toggleEmbed() {
    const wrap = document.getElementById('mv-embed-wrap');
    if (!wrap) return _toast('Phim này không có nguồn xem nhúng.', 'warning');
    if (wrap.classList.contains('hidden')) {
      // Auto-load first episode
      const firstEp = (_selectedInfo?.episode_servers || [])[0];
      if (firstEp) loadEpisode(firstEp.embed || firstEp.m3u8 || '', firstEp);
      wrap.classList.remove('hidden');
      wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      wrap.classList.add('hidden');
      const iframe = document.getElementById('mv-embed-iframe');
      if (iframe) iframe.src = '';
    }
  }

  function loadEpisode(url, ep) {
    if (!url) return _toast('Tập này không có link.', 'warning');
    const wrap = document.getElementById('mv-embed-wrap');
    const iframe = document.getElementById('mv-embed-iframe');
    if (!wrap || !iframe) return;
    iframe.src = url;
    wrap.classList.remove('hidden');
    wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (ep) _toast('Đang phát: ' + (ep.name || 'tập') + (ep.server ? ' (' + ep.server + ')' : ''), 'info');
  }

  // ── AI enrich (for movies with empty/short overview) ──
  async function aiEnrich() {
    if (!_selectedInfo) return _toast('Chưa chọn phim.', 'warning');
    const provider = document.getElementById('mv-provider')?.value || 'auto';
    const targetLang = document.getElementById('mv-lang')?.value || 'vi';
    try {
      LoadingUI.start('AI đang tra cứu phim...');
      const r = await API.post('/api/movie/ai_enrich', {
        info: _selectedInfo,
        provider,
        target_lang: targetLang,
      });
      if (r.unknown) return _toast(r.error || 'AI không có thông tin về phim này.', 'warning');
      if (!r.ok) return _toast(r.error || 'AI không trả về dữ liệu.', 'error');

      // Merge into selectedInfo so /review uses it
      _selectedInfo.overview = r.overview || _selectedInfo.overview;
      _selectedInfo.tagline = r.tagline || _selectedInfo.tagline;
      _selectedInfo.wiki_plot = r.plot || _selectedInfo.wiki_plot;
      _selectedInfo._ai_themes = r.themes || [];
      _selectedInfo._ai_audience = r.audience || '';

      // Re-render detail to show the new overview
      renderDetail(_selectedInfo, 'movie', _selectedSource);

      const meta = [];
      meta.push((r.overview || '').length + ' ký tự overview');
      if ((r.plot || '').length) meta.push((r.plot || '').length + ' ký tự cốt truyện');
      _toast('🤖 AI đã bổ sung: ' + meta.join(', '), 'success');
    } catch (e) {
      _toast(String(e.message || e), 'error');
    } finally { LoadingUI.stop(); }
  }

  // ── Image gallery ──
  function renderGallery(urls) {
    const wrap = document.getElementById('mv-gallery-wrap');
    const grid = document.getElementById('mv-gallery');
    if (!wrap || !grid) return;
    grid.replaceChildren();
    if (!urls || !urls.length) { wrap.classList.add('hidden'); return; }
    wrap.classList.remove('hidden');
    urls.forEach((u, i) => {
      const tile = _el('div', {
        class: 'mv-tile',
        style: 'position:relative;border:2px solid var(--border);border-radius:6px;overflow:hidden;cursor:pointer;aspect-ratio:16/9;background:var(--bg1)',
        onclick: (e) => {
          // Cmd/Ctrl-click toggles selection
          if (e.metaKey || e.ctrlKey) {
            tile.classList.toggle('selected');
            tile.style.borderColor = tile.classList.contains('selected') ? 'var(--accent)' : 'var(--border)';
            tile.style.boxShadow = tile.classList.contains('selected') ? '0 0 0 2px rgba(26,115,232,.25)' : '';
          } else {
            window.open(u, '_blank', 'noopener');
          }
        },
      });
      const img = _el('img', {
        src: _proxiedImg(u), alt: '', loading: 'lazy',
        style: 'width:100%;height:100%;object-fit:cover;display:block',
      });
      img.onerror = () => { tile.style.display = 'none'; };
      const idx = _el('div', {
        style: 'position:absolute;top:4px;left:4px;background:rgba(0,0,0,.65);color:#fff;font-size:10px;padding:1px 6px;border-radius:3px;font-weight:600',
      }, '#' + (i + 1));
      tile.appendChild(img);
      tile.appendChild(idx);
      tile.dataset.url = u;
      grid.appendChild(tile);
    });
  }

  async function downloadImages() {
    const grid = document.getElementById('mv-gallery');
    if (!grid) return;
    const tiles = Array.from(grid.querySelectorAll('.mv-tile'));
    const selected = tiles.filter(t => t.classList.contains('selected'));
    const urls = (selected.length ? selected : tiles).map(t => t.dataset.url).filter(Boolean);
    if (!urls.length) return _toast('Chưa có ảnh nào.', 'warning');
    _toast(`Đang tải ${urls.length} ảnh qua proxy...`, 'info');
    for (let i = 0; i < urls.length; i++) {
      const a = document.createElement('a');
      // Use backend image proxy so the browser respects Content-Disposition=attachment
      a.href = '/api/movie/image_proxy?download=1&url=' + encodeURIComponent(urls[i]);
      a.download = `movie_${String(i + 1).padStart(3, '0')}.jpg`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      await new Promise(r => setTimeout(r, 150));
    }
  }

  function toggleSelectAll() {
    const grid = document.getElementById('mv-gallery');
    if (!grid) return;
    const tiles = Array.from(grid.querySelectorAll('.mv-tile'));
    const allSelected = tiles.every(t => t.classList.contains('selected'));
    tiles.forEach(t => {
      if (allSelected) {
        t.classList.remove('selected');
        t.style.borderColor = 'var(--border)';
        t.style.boxShadow = '';
      } else {
        t.classList.add('selected');
        t.style.borderColor = 'var(--accent)';
        t.style.boxShadow = '0 0 0 2px rgba(26,115,232,.25)';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    refreshStatus();
    loadVoices();
    loadVsmovFilters();
    document.querySelectorAll('[data-page="movie"]').forEach(el =>
      el.addEventListener('click', () => {
        setTimeout(() => {
          refreshStatus();
          const wrap = document.getElementById('movie-results');
          if (wrap && wrap.querySelector('.empty-state')) trending();
        }, 80);
      }));
    document.getElementById('mv-lang')?.addEventListener('change', refreshVoices);
    if (location.pathname.includes('/movie')) {
      setTimeout(trending, 200);
    }
    onSourceChange();
  });

  // "All latest" feed: simple recently-modified across sources, no year filter
  async function allLatest() {
    try {
      const src = _currentSource();
      const url = src === 'all' || ['vsmov', 'ophim', 'kkphim'].includes(src)
        ? '/api/movie/latest?source=' + (src === 'all' ? 'all' : src) + '&per_source=10'
        : '/api/movie/trending';
      const r = await fetch(url).then(r => r.json());
      renderResults(r.items || [], 'movie', src);
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  // ── Quick filter pills ──
  let _activeQuickFilter = 'new';

  function quickFilter(btn) {
    if (!btn) return;
    const filter = btn.dataset.filter || 'new';
    _activeQuickFilter = filter;
    // Update visual state
    document.querySelectorAll('#mv-quick-filters .mv-pill').forEach(b =>
      b.classList.toggle('active', b.dataset.filter === filter));
    applyQuickFilter();
  }

  async function applyQuickFilter() {
    const src = _currentSource();
    const filter = _activeQuickFilter;
    const isVn = src === 'all' || ['vsmov', 'ophim', 'kkphim'].includes(src);
    if (!isVn) {
      // TMDb path — quick filter just calls trending
      return trending();
    }
    const sourceParam = src === 'all' ? 'all' : src;
    let url;
    if (filter === 'cinema') {
      // Cinema-priority feed
      url = '/api/movie/cinema?limit=30&source=' + sourceParam;
    } else if (filter === 'new') {
      // Anything modified in the last ~30 days
      url = '/api/movie/cinema?limit=30&pages=2&source=' + sourceParam;
    } else if (filter === 'all') {
      url = '/api/movie/latest?per_source=12&source=' + sourceParam;
    } else if (/^\d{4}$/.test(filter)) {
      url = '/api/movie/cinema?limit=30&pages=4&min_year=' + filter + '&source=' + sourceParam;
    } else {
      url = '/api/movie/cinema?limit=30&source=' + sourceParam;
    }
    try {
      const r = await fetch(url).then(r => r.json());
      let items = r.items || [];
      // Client-side post-filter for "new" (last 30 days by `modified`)
      if (filter === 'new') {
        const cutoff = Date.now() - 30 * 24 * 3600 * 1000;
        items = items.filter(it => {
          const t = Date.parse(it.modified || '');
          return !isNaN(t) ? t >= cutoff : true;
        });
      }
      renderResults(items, 'movie', src);
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  async function clearCache() {
    try {
      const r = await fetch('/api/movie/cache_clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: 'all' }),
      }).then(r => r.json());
      _toast('Đã xóa cache (' + (r.scope || 'all') + ')', 'info');
      // Reload current view
      applyQuickFilter();
    } catch (e) { _toast(String(e.message || e), 'error'); }
  }

  Object.assign(window, {
    movieSearch: search, movieTrending: trending, movieClearDetail: clearDetail,
    movieGenerateReview: generateReview, movieCopyScript: copyScript, movieSendToTTS: sendToTTS,
    movieDownloadImages: downloadImages, movieToggleSelectAll: toggleSelectAll,
    movieRender: render, movieCancelRender: cancelRender, movieGoToContent: goToContent,
    movieTtsPreview: ttsPreview, movieOnSourceChange: onSourceChange,
    movieVsmovBrowse: vsmovBrowse, movieVsmovResetFilters: vsmovResetFilters,
    movieToggleEmbed: toggleEmbed, movieLoadEpisode: loadEpisode,
    movieAiEnrich: aiEnrich, movieAllLatest: allLatest,
    movieQuickFilter: quickFilter, movieClearCache: clearCache,
  });
})();

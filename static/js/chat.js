/* ─────────────────────────────────────────────────────────────────────────
 * Chat Bot tab — talks to 9Router via /api/chatbot/*.
 * Wire format mirrors 9Router's own dashboard chat:
 *   - Models grouped by `owned_by` (kr=Kiro, gemini, ag=Antigravity, gc=GitHub Copilot, combo=user-defined).
 *   - Auth = Bearer sk-{machineId}-{keyId}-{crc8}; managed server-side.
 * Streaming uses SSE passthrough so the API key never reaches the browser.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  const state = {
    loadedConfig: false,
    loadedModels: false,
    history: [],     // [{role, content}]
    sending: false,
    abortCtl: null,
    defaultModel: '',
    models: [],
    status: null,    // last /api/chatbot/status response
  };
  window._chatState = state;

  function _toast(msg, kind = 'info') {
    if (typeof toast === 'function') return toast(msg, kind);
    if (typeof showToast === 'function') return showToast(msg, kind);
    console.log('[chat]', kind, msg);
  }

  async function _post(url, body, opts = {}) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
      signal: opts.signal,
    });
    let data = null;
    try { data = await r.json(); } catch (_) { /* ignore */ }
    return { ok: r.ok, status: r.status, data: data || {} };
  }
  async function _get(url) {
    const r = await fetch(url);
    let data = null;
    try { data = await r.json(); } catch (_) { /* ignore */ }
    return { ok: r.ok, status: r.status, data: data || {} };
  }

  function _setBadge(text, kind = 'gray') {
    const badge = document.getElementById('chat-cfg-status');
    if (!badge) return;
    badge.textContent = text;
    badge.className = 'badge ' + (
      kind === 'green'  ? 'badge-green'  :
      kind === 'red'    ? 'badge-red'    :
      kind === 'yellow' ? 'badge-yellow' :
      kind === 'accent' ? 'badge-accent' : 'badge-gray'
    );
  }

  function _setSendBusy(busy) {
    state.sending = busy;
    const btnSend = document.getElementById('chat-send-btn');
    const btnStop = document.getElementById('chat-stop-btn');
    const inp = document.getElementById('chat-input');
    const stat = document.getElementById('chat-status');
    if (btnSend) {
      btnSend.disabled = busy;
      btnSend.textContent = busy ? '⏳ Đang gửi…' : 'Gửi';
    }
    if (btnStop) btnStop.classList.toggle('hidden', !busy);
    if (inp) inp.disabled = busy;
    if (stat && busy) stat.textContent = 'Đang chờ phản hồi từ 9Router…';
  }

  // ── Config + status ───────────────────────────────────────────────────
  async function chatLoadConfig() {
    try {
      const { data } = await _get('/api/chatbot/config');
      if (!data || data.ok === false) throw new Error(data?.error || 'Không tải được cấu hình');
      const ep   = document.getElementById('chat-endpoint');
      const sp   = document.getElementById('chat-system-prompt');
      const t    = document.getElementById('chat-temperature');
      const mt   = document.getElementById('chat-max-tokens');
      const hint = document.getElementById('chat-key-hint');
      if (ep) ep.value = data.endpoint || 'http://localhost:20128/v1';
      if (sp) sp.value = data.system_prompt || '';
      if (t)  t.value  = String(data.temperature ?? 0.7);
      if (mt) mt.value = String(data.max_tokens ?? 4096);
      if (hint) {
        if (data.has_key) {
          hint.innerHTML = '✓ Đã có key đã lưu: <code>' + (data.masked_key || '***') + '</code> — để trống ô input để giữ nguyên.';
          hint.style.color = 'var(--success)';
        } else {
          hint.textContent = 'Chưa có key. Bấm 🪄 Tự động lấy key (nếu chung máy với 9Router) hoặc dán key thủ công.';
          hint.style.color = 'var(--text-muted)';
        }
      }
      state.defaultModel = data.default_model || 'duytris';
      state.loadedConfig = true;
    } catch (e) {
      _toast('Không tải được cấu hình chat: ' + e.message, 'error');
    }
  }

  async function chatRefreshStatus() {
    _setBadge('Đang kiểm tra…', 'gray');
    const { data } = await _get('/api/chatbot/status');
    state.status = data;
    const banner = document.getElementById('chat-cfg-banner');
    const autoBtn = document.getElementById('chat-btn-auto');
    if (!data || !data.reachable) {
      _setBadge('9Router offline', 'red');
      if (banner) banner.innerHTML = '⚠ Không kết nối được 9Router tại <b>' + (data?.endpoint || 'localhost:20128') + '</b>. Mở app 9Router và Start Server.';
      if (autoBtn) autoBtn.disabled = true;
      return data;
    }
    let line = '✓ Kết nối 9Router';
    if (data.version) line += ' v' + data.version;
    if (data.require_api_key) line += ' · yêu cầu API key';
    else line += ' · không yêu cầu key';
    if (data.has_key) line += ' · đã có key (' + (data.masked_key || '***') + ')';
    else line += ' · chưa có key';
    if (data.has_cli_token) line += ' · CLI token sẵn sàng (auto-setup OK)';
    else line += ' · không có CLI token (cần dán key tay)';
    if (banner) banner.textContent = line;

    if (data.has_key)         _setBadge('Sẵn sàng', 'green');
    else if (data.has_cli_token) _setBadge('Cần auto-setup', 'yellow');
    else                      _setBadge('Cần API key', 'red');

    if (autoBtn) autoBtn.disabled = !data.has_cli_token;

    // Reflect 9Router output-shaping settings on the toggles.
    const s = data.settings || {};
    const rtk = document.getElementById('chat-rtk-toggle');
    const cav = document.getElementById('chat-caveman-toggle');
    const lvl = document.getElementById('chat-caveman-level');
    const warn = document.getElementById('chat-caveman-warn');
    const writableSettings = !!data.has_cli_token && data.settings_ok;
    if (rtk) {
      rtk.checked = !!s.rtk_enabled;
      rtk.disabled = !writableSettings;
    }
    if (cav) {
      cav.checked = !!s.caveman_enabled;
      cav.disabled = !writableSettings;
    }
    if (lvl) {
      lvl.value = s.caveman_level || 'full';
      lvl.disabled = !writableSettings || !s.caveman_enabled;
    }
    if (warn) warn.classList.toggle('hidden', !s.caveman_enabled);

    return data;
  }

  async function chatToggleSetting(key, value) {
    const body = {};
    body[key] = value;
    const { data, ok } = await _post('/api/chatbot/settings', body);
    if (!ok || data?.ok === false) {
      _toast('Không cập nhật được settings: ' + (data?.message || data?.error || ok), 'error');
      // Revert UI to whatever the server says.
      await chatRefreshStatus();
      return;
    }
    _toast('Đã cập nhật ' + key + '.', 'success');
    await chatRefreshStatus();
  }

  async function chatSaveConfig() {
    const endpoint = document.getElementById('chat-endpoint')?.value?.trim() || '';
    const apiKey   = document.getElementById('chat-api-key')?.value || '';
    const dmodel   = document.getElementById('chat-default-model')?.value || '';
    const sysp     = document.getElementById('chat-system-prompt')?.value || '';
    const temp     = parseFloat(document.getElementById('chat-temperature')?.value || '0.7');
    const mtok     = parseInt(document.getElementById('chat-max-tokens')?.value || '1024', 10);

    const payload = { endpoint, system_prompt: sysp, temperature: temp, max_tokens: mtok };
    if (dmodel) payload.default_model = dmodel;
    if (apiKey) payload.api_key = apiKey;

    const { data, ok } = await _post('/api/chatbot/config', payload);
    if (!ok || data?.ok === false) {
      _toast('Lưu cấu hình thất bại: ' + (data?.error || data?.message || ok), 'error');
      return;
    }
    const keyEl = document.getElementById('chat-api-key');
    if (keyEl) keyEl.value = '';
    _toast('Đã lưu cấu hình 9Router.', 'success');
    await chatLoadConfig();
    await chatRefreshStatus();
    chatLoadModels();
  }

  async function chatAutoSetup() {
    if (!state.status) await chatRefreshStatus();
    if (!state.status?.has_cli_token) {
      _toast('Không lấy được CLI token — auto-setup cần tool và 9Router chung máy.', 'error');
      return;
    }
    const { data, ok } = await _post('/api/chatbot/auto_setup', { create_if_missing: true });
    if (!ok || data?.ok === false) {
      _toast('Auto-setup thất bại: ' + (data?.message || data?.error || 'unknown'), 'error');
      return;
    }
    _toast('✓ Đã liên kết key ' + (data.masked || '') + (data.created ? ' (vừa tạo mới)' : ''), 'success');
    await chatLoadConfig();
    await chatRefreshStatus();
    chatLoadModels();
  }

  async function chatShowKeys() {
    const wrap = document.getElementById('chat-keys-wrap');
    const tbody = document.getElementById('chat-keys-body');
    if (wrap) wrap.classList.remove('hidden');
    if (tbody) tbody.replaceChildren(_tdRow(['Đang tải…'], 4)); // colspan helper

    const { data, ok } = await _get('/api/chatbot/keys');
    if (!ok || data?.ok === false) {
      const msg = data?.message || data?.error || 'không tải được key';
      tbody?.replaceChildren(_tdRow(['Lỗi: ' + JSON.stringify(msg)], 4));
      return;
    }
    if (!data.keys?.length) {
      tbody?.replaceChildren(_tdRow(['Chưa có API key nào — bấm Tự động lấy key.'], 4));
      return;
    }
    tbody?.replaceChildren();
    for (const k of data.keys) {
      const tr = document.createElement('tr');
      tr.appendChild(_td(k.name || '(no name)'));
      tr.appendChild(_td(k.masked || '***'));
      tr.appendChild(_td(k.is_active ? '✓' : '✗'));
      tr.appendChild(_td(k.created_at || ''));
      tbody?.appendChild(tr);
    }
  }
  function _td(text) { const td = document.createElement('td'); td.textContent = text; return td; }
  function _tdRow(cols, colspan) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = colspan || 1;
    td.className = 'empty-state';
    td.textContent = cols.join(' ');
    tr.appendChild(td);
    return tr;
  }

  async function chatClearKey() {
    if (!confirm('Xoá API key đã lưu trong toolvideo?\n(Key trên 9Router không bị ảnh hưởng — vẫn có thể auto-setup lại.)')) return;
    const { data, ok } = await _post('/api/chatbot/config', { clear_key: true, api_key: '' });
    if (!ok || data?.ok === false) {
      _toast('Không xoá được key: ' + (data?.error || ok), 'error');
      return;
    }
    _toast('Đã xoá API key đã lưu.', 'success');
    chatLoadConfig();
    chatRefreshStatus();
  }

  function chatTogglePw() {
    const el = document.getElementById('chat-api-key');
    if (!el) return;
    el.type = (el.type === 'password') ? 'text' : 'password';
  }

  // ── Routing config ────────────────────────────────────────────────────
  async function chatLoadRouting() {
    const { data } = await _get('/api/chatbot/routing');
    if (!data || data.ok === false) return;
    const tiers = data.tiers || {};
    const th = data.thresholds || {};
    const setVal = (id, v) => { const el = document.getElementById(id); if (el && v != null) el.value = v; };
    setVal('chat-routing-mode', data.mode || 'auto');
    setVal('chat-th-fast', th.fast_max_chars ?? 80);
    setVal('chat-th-power', th.power_min_chars ?? 1500);
    setVal('chat-th-history', th.history_balanced_after ?? 4);
    state.routingTiers = tiers;
    _renderTierSelects(tiers);
  }

  function _renderTierSelects(currentTiers) {
    const tiers = currentTiers || state.routingTiers || {};
    for (const [tierKey, selId] of [['fast', 'chat-tier-fast'], ['balanced', 'chat-tier-balanced'], ['power', 'chat-tier-power']]) {
      const sel = document.getElementById(selId);
      if (!sel) continue;
      sel.replaceChildren();
      const blank = document.createElement('option');
      blank.value = ''; blank.textContent = '— chọn —';
      sel.appendChild(blank);
      // Use the same grouping logic as the main model dropdown.
      const groups = new Map();
      for (const m of (state.models || [])) {
        const k = m.owned_by || 'others';
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(m);
      }
      for (const [owner, items] of groups) {
        const og = document.createElement('optgroup');
        og.label = owner;
        for (const m of items) {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.id;
          og.appendChild(opt);
        }
        sel.appendChild(og);
      }
      const want = tiers[tierKey];
      if (want) sel.value = want;
    }
  }

  async function chatSaveRouting() {
    const payload = {
      mode: document.getElementById('chat-routing-mode')?.value || 'auto',
      tiers: {
        fast: document.getElementById('chat-tier-fast')?.value || '',
        balanced: document.getElementById('chat-tier-balanced')?.value || '',
        power: document.getElementById('chat-tier-power')?.value || '',
      },
      thresholds: {
        fast_max_chars: parseInt(document.getElementById('chat-th-fast')?.value || '80', 10),
        power_min_chars: parseInt(document.getElementById('chat-th-power')?.value || '1500', 10),
        history_balanced_after: parseInt(document.getElementById('chat-th-history')?.value || '4', 10),
      },
    };
    const { data, ok } = await _post('/api/chatbot/routing', payload);
    if (!ok || data?.ok === false) {
      _toast('Lưu routing thất bại: ' + (data?.error || ok), 'error');
      return;
    }
    _toast('✓ Đã lưu routing.', 'success');
    state.routingTiers = data.tiers || payload.tiers;
  }

  async function chatPreviewRouting() {
    const txt = (document.getElementById('chat-input')?.value || '').trim()
      || prompt('Nhập câu test để xem sẽ route đến model nào:');
    if (!txt) return;
    const messages = [...(state.history || []), { role: 'user', content: txt }];
    const { data, ok } = await _post('/api/chatbot/route_preview', { messages });
    const box = document.getElementById('chat-routing-preview');
    if (!box) return;
    if (!ok || data?.ok === false) {
      box.innerHTML = '❌ ' + (data?.error || 'preview lỗi');
      return;
    }
    const tier = data.routing?.tier ? `[${data.routing.tier}]` : '';
    box.innerHTML = `→ Sẽ gọi <code>${data.model}</code> ${tier} · <i>${data.routing?.reason || ''}</i>`;
  }
  async function chatLoadModels() {
    const select1 = document.getElementById('chat-default-model');
    const select2 = document.getElementById('chat-active-model');
    const setLoading = (el, label) => {
      if (!el) return;
      el.replaceChildren();
      const opt = document.createElement('option');
      opt.value = ''; opt.textContent = label;
      el.appendChild(opt);
    };
    setLoading(select1, '⏳ Đang tải…');
    setLoading(select2, '⏳ Đang tải…');

    const { data, ok } = await _get('/api/chatbot/models');
    if (!ok || data?.ok === false) {
      const msg = data?.message || data?.error || 'Không tải được model';
      setLoading(select1, '— lỗi: ' + msg + ' —');
      setLoading(select2, '— lỗi —');
      _toast('Không tải được model: ' + msg, 'error');
      state.models = [];
      return;
    }
    state.models = data.models || [];
    state.defaultModel = data.default || state.defaultModel;
    state.loadedModels = true;

    const renderInto = (el, includeBlank) => {
      if (!el) return;
      el.replaceChildren();
      if (includeBlank) {
        const opt = document.createElement('option');
        opt.value = ''; opt.textContent = '(model mặc định)';
        el.appendChild(opt);
      }
      const ownerLabel = (k) => ({
        'kr': '🥝 Kiro (FREE)',
        'gemini': '🔷 Gemini',
        'gc': '🐙 GitHub Copilot',
        'ag': '🌌 Antigravity',
        'combo': '✨ Combo (custom)',
      })[k] || (k || 'others');

      const groups = new Map();
      for (const m of state.models) {
        const key = m.owned_by || 'others';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(m);
      }
      for (const [owner, items] of groups) {
        const og = document.createElement('optgroup');
        og.label = ownerLabel(owner);
        for (const m of items) {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.id;
          og.appendChild(opt);
        }
        el.appendChild(og);
      }
      if (state.defaultModel && !includeBlank) {
        el.value = state.defaultModel;
      }
    };
    renderInto(select1, false);
    renderInto(select2, true);

    // Refresh tier dropdowns now that we have live model list.
    _renderTierSelects(state.routingTiers);
  }

  // ── Test connection ───────────────────────────────────────────────────
  async function chatTestConn() {
    _setBadge('Đang test…', 'accent');
    const { data, ok } = await _post('/api/chatbot/test', {});
    if (!ok || data?.ok === false) {
      _setBadge('Test fail', 'red');
      const msg = data?.message || data?.error || 'unknown error';
      _toast('Test thất bại: ' + (typeof msg === 'string' ? msg : JSON.stringify(msg)), 'error');
      return;
    }
    _setBadge('OK · ' + (data.elapsed_ms || 0) + 'ms', 'green');
    _toast('9Router OK (' + (data.model || '') + '): ' + (data.content || '(rỗng)').slice(0, 80), 'success');
  }

  // ── Chat UI ───────────────────────────────────────────────────────────
  function _appendBubble(role, text, modelLabel) {
    const wrap = document.getElementById('chat-messages');
    if (!wrap) return null;
    const empty = document.getElementById('chat-empty');
    if (empty) empty.remove();

    const isUser = role === 'user';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;flex-direction:column;align-items:' + (isUser ? 'flex-end' : 'flex-start');

    const meta = document.createElement('div');
    meta.style.cssText = 'font-size:11px;color:var(--text-muted);margin-bottom:2px;display:flex;gap:6px;align-items:center';
    const tag = document.createElement('span');
    tag.textContent = isUser ? '👤 Bạn' : '🤖 ' + (modelLabel || 'AI');
    meta.appendChild(tag);

    const bubble = document.createElement('div');
    bubble.style.cssText = [
      'max-width:80%',
      'padding:10px 14px',
      'border-radius:12px',
      'white-space:pre-wrap',
      'word-break:break-word',
      'font-size:13px',
      'line-height:1.5',
      'border:1px solid var(--border)',
      'box-shadow:var(--shadow)',
      isUser
        ? 'background:var(--accent);color:#fff;border-color:var(--accent)'
        : 'background:var(--bg2);color:var(--text)'
    ].join(';');
    bubble.textContent = text || '';

    row.appendChild(meta);
    row.appendChild(bubble);
    wrap.appendChild(row);
    wrap.scrollTop = wrap.scrollHeight;
    return { row, bubble, meta };
  }

  // Streaming via SSE passthrough ----------------------------------------
  async function _sendStream(payload, modelLabel) {
    const placeholder = _appendBubble('assistant', '⏳ Đang nghĩ…', modelLabel);
    state.abortCtl = new AbortController();

    let resp;
    try {
      resp = await fetch('/api/chatbot/chat_stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify(payload),
        signal: state.abortCtl.signal,
      });
    } catch (e) {
      if (e.name === 'AbortError') {
        placeholder.bubble.textContent = '⏹ Đã huỷ.';
        placeholder.bubble.style.background = 'var(--warning-bg)';
        placeholder.bubble.style.color = 'var(--warning)';
        return { ok: false, content: '' };
      }
      placeholder.bubble.textContent = '❌ Không kết nối được tới /api/chatbot/chat_stream: ' + e.message;
      return { ok: false, content: '' };
    }

    if (!resp.ok) {
      let msg = '';
      try { msg = await resp.text(); } catch (_) { /* ignore */ }
      placeholder.bubble.textContent = '❌ HTTP ' + resp.status + ' từ /api/chatbot/chat_stream' + (msg ? ': ' + msg.slice(0, 240) : '');
      placeholder.bubble.style.background = 'var(--error-bg)';
      placeholder.bubble.style.color = 'var(--error)';
      return { ok: false, content: '' };
    }

    if (!resp.body) {
      // Fallback: download whole body and parse offline.
      console.warn('[chat] response.body is null — falling back to text() parse');
      const text = await resp.text();
      const events = text.split(/\r?\n\r?\n/);
      let assembledFb = '';
      for (const ev of events) {
        const lines = ev.split(/\r?\n/);
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const dataStr = line.slice(5).trim();
          if (!dataStr || dataStr === '[DONE]') continue;
          try {
            const j = JSON.parse(dataStr);
            const c = (j.choices || [])[0]?.delta?.content;
            if (typeof c === 'string') assembledFb += c;
          } catch (_) {}
        }
      }
      placeholder.bubble.textContent = assembledFb || '⚠ Không có nội dung';
      return { ok: !!assembledFb, content: assembledFb };
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let assembled = '';
    let usage = null;
    let actualModel = modelLabel;
    let finishReason = '';
    let errored = false;

    placeholder.bubble.textContent = '';
    placeholder.bubble.style.background = '';
    placeholder.bubble.style.color = '';
    placeholder.bubble.style.borderColor = '';

    let firstChunkLogged = false;

    while (true) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (e) {
        if (e.name !== 'AbortError') {
          placeholder.bubble.textContent = (placeholder.bubble.textContent || '') + '\n[lỗi đọc stream: ' + e.message + ']';
        }
        break;
      }
      if (chunk.done) break;
      buf += decoder.decode(chunk.value, { stream: true });
      if (!firstChunkLogged) {
        firstChunkLogged = true;
        console.debug('[chat] first chunk bytes=', chunk.value?.byteLength, 'preview=', buf.slice(0, 120));
      }

      // Split by SSE event boundary (\n\n).
      const events = buf.split(/\r?\n\r?\n/);
      buf = events.pop() || '';

      for (const ev of events) {
        const lines = ev.split(/\r?\n/);
        let eventName = 'message';
        let dataParts = [];
        for (const line of lines) {
          if (!line) continue;
          if (line.startsWith(':')) continue; // comment/keepalive
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataParts.push(line.slice(5).trim());
          }
        }
        const dataStr = dataParts.join('\n');
        if (eventName === 'error') {
          errored = true;
          let msg = dataStr;
          try { msg = JSON.parse(dataStr); } catch (_) { /* keep raw */ }
          placeholder.bubble.textContent = '❌ ' + (typeof msg === 'string' ? msg : JSON.stringify(msg));
          placeholder.bubble.style.background = 'var(--error-bg)';
          placeholder.bubble.style.color = 'var(--error)';
          placeholder.bubble.style.borderColor = 'rgba(192,57,43,.3)';
          continue;
        }
        if (eventName === 'route') {
          // Synthetic event from our backend describing routing decision.
          let info;
          try { info = JSON.parse(dataStr); } catch (_) { continue; }
          const tier = info?.routing?.tier;
          const reason = info?.routing?.reason || '';
          if (info?.requested_model) actualModel = info.requested_model;
          // Update bubble meta with a "routed" badge so the user sees why.
          if (placeholder.meta) {
            const span = document.createElement('span');
            const tierColor = ({ fast: 'var(--success)', balanced: 'var(--accent)', power: 'var(--warning)' })[tier] || 'var(--text-muted)';
            span.style.cssText = `color:${tierColor};font-weight:600`;
            span.textContent = ` · ⚡ ${tier || 'route'}`;
            span.title = `${info.requested_model || ''} — ${reason}`;
            placeholder.meta.appendChild(span);
          }
          continue;
        }
        if (!dataStr || dataStr === '[DONE]') continue;

        let chunkData;
        try { chunkData = JSON.parse(dataStr); } catch (_) { continue; }
        if (chunkData.model) actualModel = chunkData.model;
        const choice = (chunkData.choices || [])[0] || {};
        const delta = choice.delta || {};
        if (typeof delta.content === 'string') {
          assembled += delta.content;
          placeholder.bubble.textContent = assembled;
        } else if (typeof choice.message?.content === 'string') {
          // Some upstreams send the whole message in one shot.
          assembled = choice.message.content;
          placeholder.bubble.textContent = assembled;
        }
        if (choice.finish_reason) finishReason = choice.finish_reason;
        if (chunkData.usage) usage = chunkData.usage;

        // Auto-scroll while streaming
        const wrap = document.getElementById('chat-messages');
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      }
    }

    if (errored) return { ok: false, content: '' };

    if (!assembled) {
      // Some reasoning models return [DONE] without ever emitting a
      // delta.content (e.g. when reasoning_tokens consumed the budget
      // before producing visible output). Surface that explicitly.
      placeholder.bubble.textContent = finishReason === 'max_tokens'
        ? '⚠ Model dừng vì hết max_tokens trước khi xuất nội dung. Tăng "Max tokens" lên 4096+ rồi thử lại.'
        : '⚠ Không có nội dung trả về (model: ' + (actualModel || modelLabel) + '). Thử model khác hoặc tăng max_tokens.';
      placeholder.bubble.style.background = 'var(--warning-bg)';
      placeholder.bubble.style.color = 'var(--warning)';
      placeholder.bubble.style.borderColor = 'rgba(183,121,31,.3)';
    }

    // Update meta with usage info if any
    if (usage && placeholder.meta) {
      const span = document.createElement('span');
      span.style.color = 'var(--text-muted)';
      span.textContent = ` · ${usage.total_tokens || 0} tokens (in ${usage.prompt_tokens || 0} / out ${usage.completion_tokens || 0})${finishReason ? ' · ' + finishReason : ''} · ${actualModel}`;
      placeholder.meta.appendChild(span);
    } else if (placeholder.meta && actualModel && actualModel !== modelLabel) {
      const span = document.createElement('span');
      span.style.color = 'var(--text-muted)';
      span.textContent = ' · ' + actualModel;
      placeholder.meta.appendChild(span);
    }
    return { ok: true, content: assembled };
  }

  async function _sendNonStream(payload, modelLabel) {
    const placeholder = _appendBubble('assistant', '⏳ Đang nghĩ…', modelLabel);
    const { data, ok } = await _post('/api/chatbot/chat', payload);
    if (!ok || data?.ok === false) {
      const errStr = (typeof data?.message === 'string') ? data.message
                   : (typeof data?.error   === 'string') ? data.error
                   : JSON.stringify(data?.error || 'Lỗi không xác định');
      placeholder.bubble.textContent = '❌ ' + errStr;
      placeholder.bubble.style.background = 'var(--error-bg)';
      placeholder.bubble.style.color = 'var(--error)';
      placeholder.bubble.style.borderColor = 'rgba(192,57,43,.3)';
      return { ok: false, content: '' };
    }
    placeholder.bubble.textContent = data.content || '(không có nội dung)';
    if (data.routing && placeholder.meta) {
      const tier = data.routing.tier;
      const tierColor = ({ fast: 'var(--success)', balanced: 'var(--accent)', power: 'var(--warning)' })[tier] || 'var(--text-muted)';
      const span = document.createElement('span');
      span.style.cssText = `color:${tierColor};font-weight:600`;
      span.textContent = ` · ⚡ ${tier || 'route'}`;
      span.title = `${data.requested_model || data.model || ''} — ${data.routing.reason || ''}`;
      placeholder.meta.appendChild(span);
    }
    if (data.usage && placeholder.meta) {
      const u = data.usage;
      const span = document.createElement('span');
      span.style.color = 'var(--text-muted)';
      span.textContent = ` · ${u.total_tokens || 0} tokens (in ${u.prompt_tokens||0} / out ${u.completion_tokens||0}) · ${data.model || modelLabel}`;
      placeholder.meta.appendChild(span);
    }
    return { ok: true, content: data.content || '' };
  }

  async function chatSend() {
    if (state.sending) return;
    const inp = document.getElementById('chat-input');
    const text = (inp?.value || '').trim();
    if (!text) return;
    if (!state.loadedConfig) await chatLoadConfig();
    if (!state.status) await chatRefreshStatus();

    const model = document.getElementById('chat-active-model')?.value || '';
    const stream = !!document.getElementById('chat-stream-toggle')?.checked;
    const modelLabel = model || state.defaultModel || 'AI';

    _appendBubble('user', text);
    state.history.push({ role: 'user', content: text });
    if (inp) inp.value = '';

    _setSendBusy(true);
    const stat = document.getElementById('chat-status');

    const payload = { messages: state.history };
    if (model) payload.model = model;

    let result;
    if (stream) {
      result = await _sendStream(payload, modelLabel);
    } else {
      result = await _sendNonStream(payload, modelLabel);
    }

    _setSendBusy(false);
    state.abortCtl = null;
    if (stat) stat.textContent = 'Sẵn sàng.';

    if (!result.ok) {
      // Pop the failed user turn so retries are clean.
      state.history.pop();
      return;
    }
    state.history.push({ role: 'assistant', content: result.content });
  }

  function chatStop() {
    if (state.abortCtl) {
      state.abortCtl.abort();
    }
  }

  function chatNewSession() {
    if (state.history.length && !confirm('Bắt đầu cuộc hội thoại mới? Lịch sử hiện tại sẽ bị xoá khỏi context.')) {
      return;
    }
    state.history = [];
    const wrap = document.getElementById('chat-messages');
    if (wrap) {
      wrap.replaceChildren();
      const empty = document.createElement('div');
      empty.id = 'chat-empty';
      empty.className = 'text-muted text-sm';
      empty.style.cssText = 'text-align:center;padding:24px';
      empty.textContent = 'Cuộc mới đã mở. Gửi câu đầu tiên để bắt đầu.';
      wrap.appendChild(empty);
    }
    _toast('Đã mở cuộc hội thoại mới.', 'info');
  }

  // ── Wiring ────────────────────────────────────────────────────────────
  function _bindKeyboard() {
    const inp = document.getElementById('chat-input');
    if (inp && !inp._chatBound) {
      inp.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && !ev.shiftKey) {
          ev.preventDefault();
          chatSend();
        }
      });
      inp._chatBound = true;
    }
    if (!document._chatGlobalBound) {
      document.addEventListener('keydown', (ev) => {
        const onChat = document.getElementById('page-chat')?.classList.contains('active');
        if (!onChat) return;
        if (ev.ctrlKey && (ev.key === 'l' || ev.key === 'L')) {
          ev.preventDefault();
          chatNewSession();
        }
      });
      document._chatGlobalBound = true;
    }
  }

  async function chatInit() {
    _bindKeyboard();
    if (!state.loadedConfig) await chatLoadConfig();
    await chatRefreshStatus();
    if (!state.loadedModels) await chatLoadModels();
    await chatLoadRouting();
  }

  // ── Tool tabs (Chat / Vision / Image / TTS / STT / Embed) ─────────────
  const _MEDIA_KIND_FOR_TOOL = {
    vision: null,           // vision uses chat completions (no separate kind)
    image:  'image',
    tts:    'tts',
    stt:    'stt',
    embed:  'embedding',
  };
  const _mediaModelsCache = {};

  function chatToolSwitch(tool) {
    document.querySelectorAll('.chat-tool-panel').forEach(p => {
      const on = p.getAttribute('data-tool') === tool;
      p.classList.toggle('hidden', !on);
      p.style.display = on ? '' : 'none';
    });
    document.querySelectorAll('[data-tool]').forEach(el => {
      if (el.classList.contains('platform-tab')) {
        el.classList.toggle('active', el.getAttribute('data-tool') === tool);
      }
    });
    // Lazy-load model lists for the selected tool.
    const kind = _MEDIA_KIND_FOR_TOOL[tool];
    if (tool === 'vision') {
      _populateVisionModels();
    } else if (kind) {
      _populateMediaSelect(kind, _mediaSelectIdFor(tool));
    }
  }
  function _mediaSelectIdFor(tool) {
    return ({ image: 'chat-img-model', tts: 'chat-tts-model', stt: 'chat-stt-model', embed: 'chat-emb-model' })[tool] || '';
  }

  async function _populateMediaSelect(kind, selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    if (sel._loaded) return;
    sel.replaceChildren(_optionEl('', '⏳ Đang tải…'));
    let items = _mediaModelsCache[kind];
    if (!items) {
      const { data, ok } = await _get('/api/chatbot/media_models?kind=' + encodeURIComponent(kind));
      if (!ok || data?.ok === false) {
        sel.replaceChildren(_optionEl('', 'lỗi: ' + (data?.error || 'unknown')));
        return;
      }
      items = data.models || [];
      _mediaModelsCache[kind] = items;
    }
    if (!items.length) {
      sel.replaceChildren(_optionEl('', '— chưa có provider nào cho ' + kind + ' —'));
      return;
    }
    sel.replaceChildren();
    const groups = new Map();
    for (const m of items) {
      const k = m.owned_by || 'others';
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(m);
    }
    for (const [owner, arr] of groups) {
      const og = document.createElement('optgroup');
      og.label = owner;
      for (const m of arr) og.appendChild(_optionEl(m.id, m.id));
      sel.appendChild(og);
    }
    sel._loaded = true;
  }
  function _optionEl(value, label) {
    const o = document.createElement('option');
    o.value = value; o.textContent = label;
    return o;
  }

  // ── Vision (uses chat completions with image_url content parts) ───────
  function _populateVisionModels() {
    const sel = document.getElementById('chat-vision-model');
    if (!sel || sel._loaded) return;
    sel.replaceChildren();
    // Heuristic: surface multimodal-capable models from the main chat list.
    // We can't fully validate vision support without trying, so we hint at
    // the obvious candidates first.
    const VISION_HINTS = [/claude/i, /gemini/i, /gpt-4/i, /sonnet/i, /opus/i, /pro/i, /vision/i];
    const items = state.models || [];
    const ranked = items.slice().sort((a, b) => {
      const score = (s) => VISION_HINTS.some(rx => rx.test(s.id)) ? 1 : 0;
      return score(b) - score(a);
    });
    for (const m of ranked) {
      sel.appendChild(_optionEl(m.id, m.id));
    }
    if (state.defaultModel) sel.value = state.defaultModel;
    sel._loaded = true;
  }

  async function chatVisionSend() {
    const file = document.getElementById('chat-vision-file')?.files?.[0];
    const prompt = (document.getElementById('chat-vision-prompt')?.value || '').trim();
    const model = document.getElementById('chat-vision-model')?.value || '';
    const result = document.getElementById('chat-vision-result');
    const preview = document.getElementById('chat-vision-preview');
    if (!file) return _toast('Chọn 1 ảnh trước.', 'warning');
    if (!prompt) return _toast('Nhập câu hỏi về ảnh.', 'warning');

    if (preview) preview.replaceChildren();
    if (result) result.textContent = '⏳ Uploading & xử lý…';

    // Step 1 — upload to backend, get a data URL.
    const fd = new FormData();
    fd.append('file', file);
    let upload;
    try {
      const resp = await fetch('/api/chatbot/upload_image', { method: 'POST', body: fd });
      upload = await resp.json();
      if (!resp.ok || upload?.ok === false) throw new Error(upload?.message || upload?.error || ('HTTP ' + resp.status));
    } catch (e) {
      if (result) result.textContent = '❌ Upload lỗi: ' + e.message;
      return;
    }
    if (preview) {
      const img = document.createElement('img');
      img.src = upload.data_url;
      img.style.cssText = 'max-width:240px;max-height:240px;border-radius:8px;border:1px solid var(--border)';
      preview.appendChild(img);
    }

    // Step 2 — call /api/chatbot/chat with image_url content part.
    const messages = [{
      role: 'user',
      content: [
        { type: 'text', text: prompt },
        { type: 'image_url', image_url: { url: upload.data_url } },
      ],
    }];
    const payload = { messages };
    if (model) payload.model = model;

    try {
      const { data, ok } = await _post('/api/chatbot/chat', payload);
      if (!ok || data?.ok === false) {
        if (result) result.textContent = '❌ ' + (data?.message || data?.error || 'lỗi');
        return;
      }
      if (result) {
        result.replaceChildren();
        const meta = document.createElement('div');
        meta.className = 'text-muted text-xs';
        meta.textContent = '✓ ' + (data.model || model) + ' · ' + (data.usage?.total_tokens || 0) + ' tokens';
        const body = document.createElement('div');
        body.style.cssText = 'white-space:pre-wrap;margin-top:6px';
        body.textContent = data.content || '(không có nội dung)';
        result.appendChild(meta);
        result.appendChild(body);
      }
    } catch (e) {
      if (result) result.textContent = '❌ ' + e.message;
    }
  }

  // ── Image generation (DALL-E / Gemini Imagen) ─────────────────────────
  async function chatImageGen() {
    const prompt = (document.getElementById('chat-img-prompt')?.value || '').trim();
    if (!prompt) return _toast('Nhập prompt.', 'warning');
    const payload = {
      prompt,
      model: document.getElementById('chat-img-model')?.value || '',
      n: parseInt(document.getElementById('chat-img-n')?.value || '1', 10),
    };
    const size = document.getElementById('chat-img-size')?.value || '';
    if (size) payload.size = size;

    const result = document.getElementById('chat-img-result');
    if (result) result.replaceChildren(_textDiv('⏳ Đang sinh ảnh…'));

    const { data, ok } = await _post('/api/chatbot/image', payload);
    if (!result) return;
    if (!ok || data?.ok === false) {
      result.replaceChildren(_textDiv('❌ ' + (data?.message || data?.error || 'lỗi')));
      return;
    }
    result.replaceChildren();
    for (const img of (data.images || [])) {
      const wrap = document.createElement('div');
      wrap.style.cssText = 'border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg2)';
      const el = document.createElement('img');
      el.style.cssText = 'width:100%;display:block';
      if (img.url) el.src = img.url;
      else if (img.b64_json) el.src = 'data:image/png;base64,' + img.b64_json;
      const meta = document.createElement('div');
      meta.style.cssText = 'padding:6px;font-size:11px;color:var(--text-muted);display:flex;gap:6px';
      meta.appendChild(_textNode(data.model || ''));
      if (img.url) {
        const a = document.createElement('a');
        a.href = img.url; a.target = '_blank'; a.textContent = '↗ open';
        a.style.color = 'var(--accent)';
        meta.appendChild(a);
      }
      wrap.appendChild(el);
      wrap.appendChild(meta);
      result.appendChild(wrap);
    }
    if (!data.images?.length) {
      result.appendChild(_textDiv('(không có ảnh trả về)'));
    }
  }

  // ── TTS ───────────────────────────────────────────────────────────────
  async function chatTtsRun() {
    const text = (document.getElementById('chat-tts-input')?.value || '').trim();
    if (!text) return _toast('Nhập văn bản.', 'warning');
    const payload = {
      input: text,
      model: document.getElementById('chat-tts-model')?.value || '',
      voice: document.getElementById('chat-tts-voice')?.value || '',
      format: document.getElementById('chat-tts-format')?.value || 'mp3',
    };
    const result = document.getElementById('chat-tts-result');
    if (result) result.replaceChildren(_textDiv('⏳ Đang tạo giọng đọc…'));

    try {
      const resp = await fetch('/api/chatbot/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j?.message || j?.error || ('HTTP ' + resp.status));
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      if (result) {
        result.replaceChildren();
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.autoplay = true;
        audio.src = url;
        audio.style.width = '100%';
        const meta = document.createElement('div');
        meta.className = 'text-xs text-muted mt-4';
        meta.innerHTML = '✓ ' + (payload.model || '') + ' · <a download="tts.' + payload.format + '" href="' + url + '" style="color:var(--accent)">⬇ tải về</a>';
        result.appendChild(audio);
        result.appendChild(meta);
      }
    } catch (e) {
      if (result) result.replaceChildren(_textDiv('❌ ' + e.message));
    }
  }

  // ── STT ───────────────────────────────────────────────────────────────
  async function chatSttRun() {
    const file = document.getElementById('chat-stt-file')?.files?.[0];
    if (!file) return _toast('Chọn file audio/video.', 'warning');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('model', document.getElementById('chat-stt-model')?.value || 'openai/whisper-1');
    const lang = document.getElementById('chat-stt-lang')?.value?.trim();
    if (lang) fd.append('language', lang);
    const fmt = document.getElementById('chat-stt-format')?.value || 'json';
    fd.append('response_format', fmt);

    const result = document.getElementById('chat-stt-result');
    if (result) result.textContent = '⏳ Đang phiên âm…';
    try {
      const resp = await fetch('/api/chatbot/stt', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok || data?.ok === false) {
        throw new Error(typeof data?.error === 'string' ? data.error : JSON.stringify(data?.error || data));
      }
      if (result) {
        if (typeof data.text === 'string') {
          result.textContent = data.text;
        } else if (data.result) {
          // Whisper JSON: { text, segments[] } or just { text }
          if (data.result.text) {
            result.textContent = data.result.text;
            if (Array.isArray(data.result.segments) && data.result.segments.length) {
              const trail = document.createElement('details');
              const sum = document.createElement('summary');
              sum.textContent = `+ ${data.result.segments.length} segments (timestamps)`;
              trail.appendChild(sum);
              const pre = document.createElement('pre');
              pre.style.cssText = 'font-size:11px;max-height:240px;overflow:auto';
              pre.textContent = data.result.segments.map(s => `[${s.start?.toFixed?.(2)}-${s.end?.toFixed?.(2)}] ${s.text}`).join('\n');
              trail.appendChild(pre);
              result.appendChild(document.createElement('br'));
              result.appendChild(trail);
            }
          } else {
            result.textContent = JSON.stringify(data.result, null, 2);
          }
        } else {
          result.textContent = JSON.stringify(data, null, 2);
        }
      }
    } catch (e) {
      if (result) result.textContent = '❌ ' + e.message;
    }
  }

  // ── Embeddings ────────────────────────────────────────────────────────
  async function chatEmbRun() {
    const raw = (document.getElementById('chat-emb-input')?.value || '').trim();
    if (!raw) return _toast('Nhập văn bản.', 'warning');
    const inputs = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const payload = {
      input: inputs.length === 1 ? inputs[0] : inputs,
      model: document.getElementById('chat-emb-model')?.value || '',
    };
    const result = document.getElementById('chat-emb-result');
    if (result) result.textContent = '⏳ Đang tính…';

    const { data, ok } = await _post('/api/chatbot/embeddings', payload);
    if (!result) return;
    if (!ok || data?.ok === false) {
      result.textContent = '❌ ' + (data?.message || data?.error || 'lỗi');
      return;
    }
    const vectors = data.result?.data || [];
    const dim = vectors[0]?.embedding?.length || 0;
    result.replaceChildren();
    const summary = document.createElement('div');
    summary.className = 'text-muted text-xs mb-8';
    summary.textContent = `✓ ${data.model} · ${vectors.length} vector × ${dim} dim · ${data.result?.usage?.total_tokens || 0} tokens`;
    result.appendChild(summary);
    for (let i = 0; i < vectors.length; i++) {
      const v = vectors[i].embedding || [];
      const row = document.createElement('div');
      row.style.cssText = 'border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:6px;background:var(--bg3);font-family:monospace;font-size:11px';
      const head = document.createElement('div');
      head.style.cssText = 'font-weight:600;margin-bottom:4px';
      head.textContent = `[${i}] ${(inputs[i] || '').slice(0, 80)}`;
      const preview = v.slice(0, 8).map(n => n.toFixed(4)).join(', ') + (v.length > 8 ? `, … (+${v.length - 8})` : '');
      const body = document.createElement('div');
      body.textContent = preview;
      row.appendChild(head);
      row.appendChild(body);
      result.appendChild(row);
    }
  }

  function _textDiv(text) { const d = document.createElement('div'); d.textContent = text; return d; }
  function _textNode(text) { return document.createTextNode(text); }

  // Expose
  window.chatInit         = chatInit;
  window.chatSend         = chatSend;
  window.chatStop         = chatStop;
  window.chatLoadConfig   = chatLoadConfig;
  window.chatSaveConfig   = chatSaveConfig;
  window.chatLoadModels   = chatLoadModels;
  window.chatNewSession   = chatNewSession;
  window.chatTestConn     = chatTestConn;
  window.chatClearKey     = chatClearKey;
  window.chatTogglePw     = chatTogglePw;
  window.chatRefreshStatus = chatRefreshStatus;
  window.chatAutoSetup    = chatAutoSetup;
  window.chatShowKeys     = chatShowKeys;
  window.chatToggleSetting = chatToggleSetting;
  window.chatLoadRouting   = chatLoadRouting;
  window.chatSaveRouting   = chatSaveRouting;
  window.chatPreviewRouting = chatPreviewRouting;
  window.chatToolSwitch    = chatToolSwitch;
  window.chatVisionSend    = chatVisionSend;
  window.chatImageGen      = chatImageGen;
  window.chatTtsRun        = chatTtsRun;
  window.chatSttRun        = chatSttRun;
  window.chatEmbRun        = chatEmbRun;
})();

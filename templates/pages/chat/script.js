/* ─────────────────────────────────────────────────────────────────────────
 * Chat Bot — Modern AI Studio & Assistant.
 * Multi-session SQLite persistence (/api/chatbot/sessions)
 * Direct AI Providers (Antigravity, Gemini, OpenAI, etc.)
 * Streaming tokens via SSE (/api/chatbot/chat_stream)
 * Multimodal vision, image generation, TTS, STT, and embeddings.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  window.copyToClipboard = window.copyToClipboard || function(btn) {
    const code = btn.nextElementSibling?.querySelector('code')?.innerText || btn.nextElementSibling?.innerText || '';
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
      const originalHtml = btn.innerHTML;
      btn.innerHTML = `<svg style="width:14px;height:14px;color:#10b981" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`;
      btn.style.background = 'rgba(16,185,129,0.15)';
      setTimeout(() => {
        btn.innerHTML = originalHtml;
        btn.style.background = '';
      }, 1500);
    }).catch(err => {
      console.error('Failed to copy: ', err);
    });
  };

  const state = {
    loadedConfig: false,
    loadedModels: false,
    sessions: [],          // [{id, title, model, created_at, updated_at}]
    activeSessionId: null, // current s_xxxxx
    history: [],           // [{role, content}]
    pendingAttachment: null, // { kind:'image', name, mime, dataUrl }
    sending: false,
    abortCtl: null,
    defaultModel: '',
    models: [],
    status: null,
    sidebarCollapsed: false,
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

  function _timeAgo(ts) {
    if (!ts) return '';
    const now = Date.now();
    const diff = Math.floor((now - ts) / 1000);
    if (diff < 60) return 'Vừa xong';
    if (diff < 3600) return Math.floor(diff / 60) + ' phút trước';
    if (diff < 86400) return Math.floor(diff / 3600) + ' giờ trước';
    if (diff < 604800) return Math.floor(diff / 86400) + ' ngày trước';
    const d = new Date(ts);
    return `${d.getDate()}/${d.getMonth() + 1}`;
  }

  function _setSendBusy(busy) {
    state.sending = busy;
    const btnSend = document.getElementById('chat-send-btn');
    const btnStop = document.getElementById('chat-stop-btn');
    const inp = document.getElementById('chat-input');
    const stat = document.getElementById('chat-status');

    if (btnSend) {
      btnSend.disabled = busy;
      btnSend.classList.toggle('opacity-50', busy);
      btnSend.classList.toggle('cursor-not-allowed', busy);
    }
    if (btnStop) btnStop.classList.toggle('hidden', !busy);
    if (inp) inp.disabled = busy;
    if (stat) stat.textContent = busy ? '⏳ Trợ lý AI đang xử lý câu trả lời...' : 'Sẵn sàng.';
  }

  // ── Session Management (SQLite persistent) ────────────────────────────
  async function chatLoadSessions() {
    const { ok, data } = await _get('/api/chatbot/sessions');
    const listEl = document.getElementById('chat-session-list');
    if (!ok || data?.ok === false) {
      if (listEl) listEl.innerHTML = '<div class="p-4 text-center text-slate-400 text-xs">Không tải được lịch sử.</div>';
      return;
    }
    state.sessions = data.sessions || [];
    renderSessionList();

    // Restore last active session if valid, otherwise select the first session or open fresh
    const lastSid = localStorage.getItem('chatLastSessionId');
    if (lastSid && state.sessions.some(s => s.id === lastSid)) {
      if (state.activeSessionId !== lastSid) {
        await chatSelectSession(lastSid);
      }
    } else if (state.sessions.length > 0 && !state.activeSessionId) {
      await chatSelectSession(state.sessions[0].id);
    } else if (!state.activeSessionId) {
      chatNewSession(false);
    }
  }

  function renderSessionList(filterText = '') {
    const listEl = document.getElementById('chat-session-list');
    if (!listEl) return;
    listEl.replaceChildren();

    const query = filterText.toLowerCase().trim();
    const filtered = state.sessions.filter(s => (s.title || 'Cuộc trò chuyện mới').toLowerCase().includes(query));

    if (!filtered.length) {
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'p-6 text-center text-slate-400 dark:text-slate-500 text-xs';
      emptyDiv.textContent = query ? 'Không tìm thấy cuộc trò chuyện nào.' : 'Chưa có cuộc trò chuyện nào.';
      listEl.appendChild(emptyDiv);
      return;
    }

    for (const sess of filtered) {
      const item = document.createElement('div');
      const isActive = sess.id === state.activeSessionId;
      item.className = `chat-session-item group flex items-center justify-between gap-2 p-2.5 rounded-xl border border-transparent cursor-pointer transition-all duration-150 text-slate-700 dark:text-slate-200 hover:bg-slate-100/90 dark:hover:bg-slate-800/60 ${isActive ? 'active' : ''}`;
      item.setAttribute('data-sid', sess.id);

      const left = document.createElement('div');
      left.className = 'flex items-center gap-2.5 min-w-0 flex-1';

      const icon = document.createElement('div');
      icon.className = `w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-xs ${isActive ? 'bg-blue-600 text-white' : 'bg-slate-200/60 dark:bg-slate-800 text-slate-500 dark:text-slate-400'}`;
      icon.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>`;

      const info = document.createElement('div');
      info.className = 'min-w-0 flex-1';

      const title = document.createElement('div');
      title.className = 'text-xs font-medium truncate leading-tight';
      title.textContent = sess.title || 'Cuộc trò chuyện mới';
      title.title = sess.title || '';

      const time = document.createElement('div');
      time.className = 'text-[10px] text-slate-400 dark:text-slate-500 mt-0.5 truncate';
      time.textContent = _timeAgo(sess.updated_at || sess.created_at);

      info.appendChild(title);
      info.appendChild(time);
      left.appendChild(icon);
      left.appendChild(info);
      item.appendChild(left);

      // Actions (Rename, Delete)
      const actions = document.createElement('div');
      actions.className = 'flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0';

      const btnRename = document.createElement('button');
      btnRename.className = 'p-1 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 rounded-md hover:bg-slate-200/60 dark:hover:bg-slate-700/60 transition-colors';
      btnRename.title = 'Đổi tên';
      btnRename.innerHTML = `<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>`;
      btnRename.onclick = (e) => chatRenameSession(sess.id, e);

      const btnDel = document.createElement('button');
      btnDel.className = 'p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 rounded-md hover:bg-slate-200/60 dark:hover:bg-slate-700/60 transition-colors';
      btnDel.title = 'Xoá cuộc trò chuyện';
      btnDel.innerHTML = `<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>`;
      btnDel.onclick = (e) => chatDeleteSession(sess.id, e);

      actions.appendChild(btnRename);
      actions.appendChild(btnDel);
      item.appendChild(actions);

      item.onclick = () => chatSelectSession(sess.id);
      listEl.appendChild(item);
    }
  }

  function chatFilterSessions(text) {
    renderSessionList(text);
  }

  async function chatSelectSession(sid) {
    if (!sid) return;
    document.getElementById('page-chat')?.classList.remove('chat-sessions-open');
    state.activeSessionId = sid;
    localStorage.setItem('chatLastSessionId', sid);
    renderSessionList();

    const wrap = document.getElementById('chat-messages');
    if (!wrap) return;
    const msgContainer = wrap.querySelector('.max-w-4xl');
    if (!msgContainer) return;
    msgContainer.replaceChildren();

    const { ok, data } = await _get(`/api/chatbot/sessions/${sid}`);
    if (!ok || data?.ok === false) {
      _renderEmptyState();
      state.history = [];
      return;
    }

    const messages = data.messages || [];
    state.history = [];

    if (!messages.length) {
      _renderEmptyState();
      return;
    }

    for (const msg of messages) {
      state.history.push({ role: msg.role, content: msg.content });
      _appendBubble(msg.role, msg.content, msg.role === 'assistant' ? (data.session?.model || 'AI') : null);
    }
    wrap.scrollTop = wrap.scrollHeight;
  }

  function chatNewSession(notify = true) {
    document.getElementById('page-chat')?.classList.remove('chat-sessions-open');
    state.activeSessionId = 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    state.history = [];
    localStorage.removeItem('chatLastSessionId');

    const wrap = document.getElementById('chat-messages');
    if (wrap) {
      const msgContainer = wrap.querySelector('.max-w-4xl');
      if (msgContainer) {
        msgContainer.replaceChildren();
        _renderEmptyState();
      }
    }
    const inp = document.getElementById('chat-input');
    if (inp) {
      inp.value = '';
      inp.style.height = '44px';
      inp.focus();
    }
    chatClearInlineImage();
    renderSessionList();
    if (notify) _toast('Đã mở cuộc trò chuyện mới.', 'info');
  }

  async function chatDeleteSession(sid, e) {
    if (e) e.stopPropagation();
    if (!confirm('Bạn có chắc chắn muốn xoá cuộc trò chuyện này?')) return;

    const res = await fetch(`/api/chatbot/sessions/${sid}?hard=1`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (data?.ok) {
      _toast('Đã xoá cuộc trò chuyện.', 'success');
      state.sessions = state.sessions.filter(s => s.id !== sid);
      if (state.activeSessionId === sid) {
        if (state.sessions.length > 0) {
          await chatSelectSession(state.sessions[0].id);
        } else {
          chatNewSession(false);
        }
      } else {
        renderSessionList();
      }
    } else {
      _toast('Không xoá được cuộc trò chuyện: ' + (data?.error || ''), 'error');
    }
  }

  async function chatRenameSession(sid, e) {
    if (e) e.stopPropagation();
    const current = state.sessions.find(s => s.id === sid);
    const newTitle = prompt('Nhập tiêu đề mới cho cuộc trò chuyện:', current?.title || '');
    if (!newTitle || !newTitle.trim()) return;

    const res = await fetch(`/api/chatbot/sessions/${sid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    const data = await res.json().catch(() => ({}));
    if (data?.ok) {
      _toast('Đã đổi tên cuộc trò chuyện.', 'success');
      if (current) current.title = newTitle.trim();
      renderSessionList();
    } else {
      _toast('Không đổi được tên: ' + (data?.error || ''), 'error');
    }
  }

  function _renderEmptyState() {
    const wrap = document.getElementById('chat-messages');
    if (!wrap) return;
    const msgContainer = wrap.querySelector('.max-w-4xl');
    if (!msgContainer) return;
    if (msgContainer.querySelector('#chat-empty')) return;

    const empty = document.createElement('div');
    empty.id = 'chat-empty';
    empty.className = 'my-auto py-10 px-4 flex flex-col items-center text-center animate-fade-in';
    empty.innerHTML = `
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-sky-400 p-0.5 shadow-lg shadow-blue-500/20 mb-4 ai-pulse-dot flex items-center justify-center">
        <div class="w-full h-full bg-white dark:bg-slate-900 rounded-[14px] flex items-center justify-center text-blue-600 dark:text-blue-400">
          <svg class="w-8 h-8" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 7V4"/><circle cx="12" cy="3" r="1" fill="currentColor"/><circle cx="9" cy="13" r="1.4" fill="currentColor"/><circle cx="15" cy="13" r="1.4" fill="currentColor"/><path d="M9.5 16.5h5"/></svg>
        </div>
      </div>
      <h2 class="text-xl font-bold text-slate-800 dark:text-slate-100 mb-2">Xin chào! Bạn muốn tạo nội dung gì hôm nay?</h2>
      <p class="text-xs text-slate-500 dark:text-slate-400 max-w-lg mb-8 leading-relaxed">
        Trợ lý AI sẵn sàng hỗ trợ viết kịch bản, sáng tạo nội dung, dịch thuật và phân tích video với các model AI tiên tiến nhất.
      </p>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3.5 w-full max-w-2xl text-left">
        <div onclick="chatInsertStarterPrompt('Viết kịch bản video ngắn TikTok 60 giây review công nghệ, mở đầu bằng hook thu hút trong 3 giây đầu.')" class="chat-starter-card p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur-xs cursor-pointer hover:border-blue-500/40 dark:hover:border-blue-500/40">
          <div class="flex items-center gap-2 mb-1.5"><span class="text-base">🎬</span><span class="text-xs font-bold text-slate-800 dark:text-slate-200">Kịch bản TikTok 60s</span></div>
          <p class="text-[11.5px] text-slate-500 dark:text-slate-400 line-clamp-2">Review công nghệ có hook 3 giây đầu giữ chân người xem.</p>
        </div>
        <div onclick="chatInsertStarterPrompt('Tạo 5 caption hấp dẫn kèm bộ hashtag thịnh hành cho video review du lịch trải nghiệm.')" class="chat-starter-card p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur-xs cursor-pointer hover:border-blue-500/40 dark:hover:border-blue-500/40">
          <div class="flex items-center gap-2 mb-1.5"><span class="text-base">✍️</span><span class="text-xs font-bold text-slate-800 dark:text-slate-200">Caption &amp; Hashtag Viral</span></div>
          <p class="text-[11.5px] text-slate-500 dark:text-slate-400 line-clamp-2">Tạo tiêu đề thu hút người xem và danh sách hashtag trending.</p>
        </div>
        <div onclick="chatInsertStarterPrompt('Dịch đoạn hội thoại sau sang tiếng Anh tự nhiên và chuẩn phong cách đời thường trẻ trung:')" class="chat-starter-card p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur-xs cursor-pointer hover:border-blue-500/40 dark:hover:border-blue-500/40">
          <div class="flex items-center gap-2 mb-1.5"><span class="text-base">🌐</span><span class="text-xs font-bold text-slate-800 dark:text-slate-200">Dịch &amp; Tối ưu Phụ đề</span></div>
          <p class="text-[11.5px] text-slate-500 dark:text-slate-400 line-clamp-2">Dịch tự nhiên sang tiếng Anh/Hàn/Trung chuẩn ngữ cảnh video.</p>
        </div>
        <div onclick="chatInsertStarterPrompt('Gợi ý 10 ý tưởng video ngắn triệu view trong tuần này kèm góc nhìn độc đáo, ít bị cạnh tranh.')" class="chat-starter-card p-4 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-white/70 dark:bg-slate-900/60 backdrop-blur-xs cursor-pointer hover:border-blue-500/40 dark:hover:border-blue-500/40">
          <div class="flex items-center gap-2 mb-1.5"><span class="text-base">💡</span><span class="text-xs font-bold text-slate-800 dark:text-slate-200">10 Ý tưởng Video Triệu View</span></div>
          <p class="text-[11.5px] text-slate-500 dark:text-slate-400 line-clamp-2">Khám phá chủ đề hot xu hướng và góc khai thác độc đáo.</p>
        </div>
      </div>
    `;
    msgContainer.appendChild(empty);
  }

  function chatInsertStarterPrompt(text) {
    const inp = document.getElementById('chat-input');
    if (inp) {
      inp.value = text;
      inp.focus();
      _autoresize(inp);
      chatSend();
    }
  }

  // ── Layout Sidebar Toggle ─────────────────────────────────────────────
  function chatToggleSidebar() {
    const sidebar = document.getElementById('chat-sidebar');
    if (!sidebar) return;
    if (window.matchMedia('(max-width: 768px)').matches) {
      sidebar.classList.remove('w-0', 'p-0', 'overflow-hidden', 'border-r-0');
      document.getElementById('page-chat')?.classList.toggle('chat-sessions-open');
      return;
    }
    state.sidebarCollapsed = !state.sidebarCollapsed;
    if (state.sidebarCollapsed) {
      sidebar.classList.add('w-0', 'p-0', 'overflow-hidden', 'border-r-0');
      sidebar.classList.remove('w-72', 'lg:w-80');
    } else {
      sidebar.classList.remove('w-0', 'p-0', 'overflow-hidden', 'border-r-0');
      sidebar.classList.add('w-72', 'lg:w-80');
    }
  }

  // ── Settings Modal ────────────────────────────────────────────────────
  function chatOpenSettingsModal() {
    const m = document.getElementById('chat-settings-modal');
    if (m) m.classList.remove('hidden');
  }

  function chatCloseSettingsModal() {
    const m = document.getElementById('chat-settings-modal');
    if (m) m.classList.add('hidden');
  }

  async function chatSaveConfigModal() {
    await chatSaveConfig();
    await chatSaveRouting();
    chatCloseSettingsModal();
  }

  // ── Inline Image Attachment for Vision ────────────────────────────────
  function chatAttachInlineImage(event) {
    const file = event.target?.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      state.pendingAttachment = {
        kind: 'image',
        name: file.name,
        mime: file.type || 'image/jpeg',
        dataUrl: e.target.result,
      };
      _renderInputAttachmentPreview();
    };
    reader.readAsDataURL(file);
    event.target.value = '';
  }

  function chatClearInlineImage() {
    state.pendingAttachment = null;
    _renderInputAttachmentPreview();
  }

  function _renderInputAttachmentPreview() {
    const box = document.getElementById('chat-input-attachments');
    if (!box) return;
    if (!state.pendingAttachment) {
      box.classList.add('hidden');
      box.replaceChildren();
      return;
    }
    box.classList.remove('hidden');
    box.replaceChildren();

    const chip = document.createElement('div');
    chip.className = 'inline-flex items-center gap-2 px-2.5 py-1 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-xl text-xs text-blue-700 dark:text-blue-300 shadow-2xs';

    const img = document.createElement('img');
    img.src = state.pendingAttachment.dataUrl;
    img.className = 'w-6 h-6 rounded-md object-cover border border-blue-300';

    const span = document.createElement('span');
    span.className = 'truncate max-w-[140px] font-medium';
    span.textContent = state.pendingAttachment.name || 'Ảnh đính kèm';

    const del = document.createElement('button');
    del.className = 'p-0.5 hover:bg-blue-200/50 dark:hover:bg-blue-900 rounded-full transition-colors';
    del.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>`;
    del.onclick = chatClearInlineImage;

    chip.appendChild(img);
    chip.appendChild(span);
    chip.appendChild(del);
    box.appendChild(chip);
  }

  // ── Config + Status ───────────────────────────────────────────────────
  async function chatLoadConfig() {
    try {
      const { data } = await _get('/api/chatbot/config');
      if (!data || data.ok === false) return;
      const sp = document.getElementById('chat-system-prompt');
      const t  = document.getElementById('chat-temperature');
      const mt = document.getElementById('chat-max-tokens');
      if (sp) sp.value = data.system_prompt || '';
      if (t)  t.value  = String(data.temperature ?? 0.7);
      if (mt) mt.value = String(data.max_tokens ?? 4096);
      state.defaultModel = data.default_model || 'gemini-3.8-flash-high';
      state.loadedConfig = true;
    } catch (e) {
      console.error('[chat] load config failed:', e);
    }
  }

  async function chatRefreshStatus(force = false) {
    const url = force ? '/api/chatbot/status?force=1' : '/api/chatbot/status';
    const { data } = await _get(url);
    state.status = data;

    const sidebarText = document.getElementById('chat-sidebar-status-text');
    const banner = document.getElementById('chat-cfg-banner');

    if (data?.online || data?.active_provider_available || data?.status_text === 'onl' || data?.has_key) {
      const provs = (data.active_providers || []).join(', ') || 'Antigravity';
      if (sidebarText) sidebarText.textContent = `${provs} • onl`;
      if (banner) banner.innerHTML = `🟢 Đang kết nối trực tiếp qua <b>${provs}</b> (Hệ thống AI khép kín).`;
      return data;
    }

    if (sidebarText) sidebarText.textContent = 'Chưa có kết nối';
    if (banner) banner.innerHTML = '⚠ Chưa có AI Provider nào hoạt động. Hãy kích hoạt kết nối tại trang AI Providers.';
    return data;
  }

  async function chatSaveConfig() {
    const dmodel = document.getElementById('chat-default-model')?.value || '';
    const sysp   = document.getElementById('chat-system-prompt')?.value || '';
    const temp   = parseFloat(document.getElementById('chat-temperature')?.value || '0.7');
    const mtok   = parseInt(document.getElementById('chat-max-tokens')?.value || '4096', 10);

    const payload = { system_prompt: sysp, temperature: temp, max_tokens: mtok };
    if (dmodel) payload.default_model = dmodel;

    const { data, ok } = await _post('/api/chatbot/config', payload);
    if (!ok || data?.ok === false) {
      _toast('Lưu cấu hình thất bại: ' + (data?.error || ok), 'error');
      return;
    }
    _toast('Đã lưu cấu hình AI.', 'success');
    await chatLoadConfig();
    chatLoadModels();
  }

  // ── Models Loading & Dropdowns ─────────────────────────────────────────
  async function chatLoadModels() {
    const selectActive  = document.getElementById('chat-active-model');
    const selectDefault = document.getElementById('chat-default-model');

    const { data, ok } = await _get('/api/chatbot/models');
    if (!ok || data?.ok === false) {
      state.models = [];
      if (selectActive) selectActive.innerHTML = '<option value="">(Không tải được model)</option>';
      return;
    }

    state.models = data.models || [];
    state.defaultModel = data.default || state.defaultModel || 'gemini-3.8-flash-high';
    state.loadedModels = true;

    const renderInto = (el, autoSelectSaved = false) => {
      if (!el) return;
      el.replaceChildren();

      const groups = new Map();
      for (const m of state.models) {
        const key = m.owned_by || 'others';
        const label = m.provider_name || (key.charAt(0).toUpperCase() + key.slice(1));
        if (!groups.has(key)) groups.set(key, { label, items: [] });
        groups.get(key).items.push(m);
      }

      for (const [owner, grp] of groups) {
        const og = document.createElement('optgroup');
        og.label = grp.label;
        for (const m of grp.items) {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name || m.id;
          og.appendChild(opt);
        }
        el.appendChild(og);
      }

      // Pre-select model
      const saved = localStorage.getItem('chatActiveModel');
      if (autoSelectSaved && saved && state.models.some(m => m.id === saved)) {
        el.value = saved;
      } else if (state.defaultModel && state.models.some(m => m.id === state.defaultModel)) {
        el.value = state.defaultModel;
      } else if (state.models.length > 0) {
        el.value = state.models[0].id;
      }
    };

    renderInto(selectActive, true);
    renderInto(selectDefault, false);

    // Update bottom dock hint
    const hintEl = document.getElementById('chat-dock-model-hint');
    if (hintEl && selectActive?.value) {
      hintEl.textContent = selectActive.options[selectActive.selectedIndex]?.text || selectActive.value;
    }

    if (selectActive && !selectActive._boundChange) {
      selectActive.addEventListener('change', (e) => {
        localStorage.setItem('chatActiveModel', e.target.value);
        if (hintEl) hintEl.textContent = e.target.options[e.target.selectedIndex]?.text || e.target.value;
      });
      selectActive._boundChange = true;
    }

    _renderTierSelects(state.routingTiers);
  }

  // ── Routing Config ────────────────────────────────────────────────────
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
          opt.textContent = m.name || m.id;
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
    box.innerHTML = `→ Sẽ gọi <b>${data.model}</b> ${tier} · <i>${data.routing?.reason || ''}</i>`;
  }

  async function chatToggleSetting(key, value) {
    const body = {};
    body[key] = value;
    await _post('/api/chatbot/settings', body);
    _toast('Đã cập nhật cấu hình.', 'success');
  }

  // ── Markdown Parser & Message Bubbles ─────────────────────────────────
  function parseMarkdownToHtml(text) {
    if (!text) return '';
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    html = html.replace(/```([\s\S]*?)```/g, (match, codePart) => {
      const lines = codePart.split('\n');
      let lang = '';
      let code = codePart;
      if (lines.length > 1 && lines[0].trim().match(/^[a-zA-Z0-9_-]+$/)) {
        lang = lines[0].trim().toLowerCase();
        code = lines.slice(1).join('\n');
      }
      return `<div class="cw-code-container my-2 bg-slate-100 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl p-3 relative overflow-hidden font-mono text-xs">`
        + `<div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-200/60 dark:border-slate-800/60 text-[11px] text-slate-500 font-sans">`
          + `<span>${lang || 'code'}</span>`
          + `<button onclick="window.copyToClipboard(this)" class="px-2 py-0.5 bg-slate-200/60 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 rounded text-slate-700 dark:text-slate-300 transition-all cursor-pointer flex items-center gap-1">`
            + `<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`
            + `Sao chép`
          + `</button>`
        + `</div>`
        + `<pre class="overflow-x-auto whitespace-pre leading-relaxed"><code>${code.trim()}</code></pre>`
      + `</div>`;
    });

    html = html.replace(/`([^`\n]+)`/g, '<code class="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200/60 dark:border-slate-700/60 rounded text-[12px] font-mono text-blue-600 dark:text-blue-400">$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/^(#{1,6})\s+(.+)$/gm, (match, hashes, content) => {
      const level = hashes.length;
      const sizeClass = level === 1 ? 'text-base font-bold mt-3 mb-1.5 block' : 'text-sm font-bold mt-2.5 mb-1 block';
      return `<span class="${sizeClass}">${content}</span>`;
    });
    html = html.replace(/^\s*[-*+]\s+(.+)$/gm, '<li class="ml-4 list-disc">$1</li>');
    html = html.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1" class="max-w-full max-h-80 rounded-xl my-2 block shadow-xs">');
    html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 underline underline-offset-2">$1</a>');
    html = html.replace(/(?<!["=>])(https?:\/\/[^\s<>")\]]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 underline underline-offset-2 break-all">$1</a>');
    return html;
  }

  function enrichBubble(bub, rawText) {
    if (!bub || typeof rawText !== 'string') return;
    let t = rawText;
    t = t.replace(/<\s*(web_search|web-search|websearch|search|tool_use|tool-use|invoke|function_calls|antml:function_calls)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, '');
    t = t.replace(/<\s*(web_search|tool_use|invoke|function_calls|antml:function_calls)\b[^>]*\/?\s*>/gi, '');
    t = t.replace(/<\s*\/?\s*(query|max_results|parameter|antml:parameter)\s*>/gi, '');
    t = t.replace(/\n{3,}/g, '\n\n').trim();
    bub.innerHTML = parseMarkdownToHtml(t);
  }

  function _appendBubble(role, text, modelLabel, attachment = null) {
    const wrap = document.getElementById('chat-messages');
    if (!wrap) return null;
    const msgContainer = wrap.querySelector('.max-w-4xl') || wrap;

    const empty = document.getElementById('chat-empty');
    if (empty) empty.remove();

    const isUser = role === 'user';
    const row = document.createElement('div');
    row.className = `flex gap-3 items-start animate-fade-in ${isUser ? 'justify-end' : 'justify-start'}`;

    const contentCol = document.createElement('div');
    contentCol.className = `flex flex-col min-w-0 max-w-[90%] sm:max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`;

    // Meta Header (Sender Name & Tag)
    const meta = document.createElement('div');
    meta.className = 'text-[11px] text-slate-400 dark:text-slate-500 mb-1 flex items-center gap-1.5 px-1';
    meta.textContent = isUser ? 'Bạn' : (modelLabel || 'AI Assistant');
    contentCol.appendChild(meta);

    // Optional user attachment preview
    if (attachment && attachment.dataUrl) {
      const img = document.createElement('img');
      img.src = attachment.dataUrl;
      img.className = 'max-w-[240px] max-h-[200px] rounded-xl object-cover border border-slate-200 dark:border-slate-800 mb-2 shadow-xs';
      contentCol.appendChild(img);
    }

    // Main Bubble
    const bubble = document.createElement('div');
    bubble.className = isUser
      ? 'bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-2xl rounded-tr-xs px-4 py-2.5 shadow-sm text-[13px] leading-relaxed break-words'
      : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl rounded-tl-xs px-4 py-3 shadow-2xs text-[13px] text-slate-800 dark:text-slate-200 leading-relaxed break-words w-full';

    if (text) {
      enrichBubble(bubble, text);
    } else {
      bubble.textContent = '';
    }

    contentCol.appendChild(bubble);
    row.appendChild(contentCol);
    msgContainer.appendChild(row);

    wrap.scrollTop = wrap.scrollHeight;
    return { row, bubble, meta };
  }

  function formatChatError(rawError) {
    let msg = '';
    if (typeof rawError === 'string') msg = rawError;
    else if (rawError && typeof rawError === 'object') {
      msg = rawError.body || rawError.message || rawError.error || JSON.stringify(rawError);
    } else {
      msg = String(rawError || 'Lỗi không xác định');
    }
    const lower = msg.toLowerCase();
    if (lower.includes('chưa có ai provider') || lower.includes('offline') || lower.includes('unreachable') || lower.includes('failed to connect')) {
      return `Chưa có kết nối AI Provider nào đang hoạt động.
💡 Hướng dẫn:
1. Vào tab Cấu hình -> AI Providers để kiểm tra kết nối.
2. Bật kết nối Antigravity hoặc Google Gemini hợp lệ.`;
    }
    return msg;
  }

  // ── Send & Stream Flow ─────────────────────────────────────────────────
  async function chatSend() {
    if (state.sending) return;
    const inp = document.getElementById('chat-input');
    const text = (inp?.value || '').trim();
    if (!text && !state.pendingAttachment) return;

    // Ensure session ID exists
    if (!state.activeSessionId) {
      state.activeSessionId = 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    }

    const currentAttachment = state.pendingAttachment;
    chatClearInlineImage();

    _setSendBusy(true);
    if (inp) {
      inp.value = '';
      inp.style.height = '44px';
    }

    try {
      if (!state.loadedConfig) await chatLoadConfig();
      if (!state.status) await chatRefreshStatus();
    } catch (_) {}

    const model = document.getElementById('chat-active-model')?.value || '';
    const stream = !!document.getElementById('chat-stream-toggle')?.checked;
    const modelLabel = model || state.defaultModel || 'AI';

    // First user turn: persist or update session title
    const isFirstTurn = state.history.length === 0;
    if (isFirstTurn) {
      const cleanTitle = (text || 'Hình ảnh').slice(0, 32);
      await _post('/api/chatbot/sessions', { id: state.activeSessionId, title: cleanTitle, model: modelLabel });
    }

    // Append User Bubble
    _appendBubble('user', text, null, currentAttachment);
    state.history.push({ role: 'user', content: text });

    // Persist user turn to SQLite
    _post(`/api/chatbot/sessions/${state.activeSessionId}/messages`, {
      role: 'user',
      content: text,
    });

    let payload;
    if (currentAttachment && currentAttachment.dataUrl) {
      // Multimodal vision payload
      payload = {
        model,
        messages: [
          ...state.history.slice(0, -1),
          {
            role: 'user',
            content: [
              { type: 'text', text: text || 'Mô tả bức ảnh này.' },
              { type: 'image_url', image_url: { url: currentAttachment.dataUrl } }
            ]
          }
        ]
      };
    } else {
      payload = { messages: state.history, model };
    }

    let result;
    if (stream) {
      result = await _sendStream(payload, modelLabel);
    } else {
      result = await _sendNonStream(payload, modelLabel);
    }

    _setSendBusy(false);
    state.abortCtl = null;

    if (!result.ok) {
      state.history.pop(); // Revert user message on error
      return;
    }

    state.history.push({ role: 'assistant', content: result.content });

    // Persist assistant turn to SQLite
    await _post(`/api/chatbot/sessions/${state.activeSessionId}/messages`, {
      role: 'assistant',
      content: result.content,
    });

    // Refresh session list to show updated title & timestamp
    chatLoadSessions();
  }

  function chatStop() {
    if (state.abortCtl) {
      state.abortCtl.abort();
    }
  }

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
        placeholder.bubble.textContent = '⏹ Đã dừng phản hồi.';
        placeholder.bubble.className += ' text-amber-600 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800';
        return { ok: false, content: '' };
      }
      placeholder.bubble.textContent = '❌ Lỗi kết nối stream: ' + e.message;
      return { ok: false, content: '' };
    }

    if (!resp.ok) {
      let msg = '';
      try { msg = await resp.text(); } catch (_) {}
      placeholder.bubble.textContent = '❌ Lỗi phản hồi HTTP ' + resp.status + (msg ? ': ' + msg.slice(0, 180) : '');
      return { ok: false, content: '' };
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let assembled = '';
    let actualModel = '';
    let errored = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() || '';

      for (const ev of events) {
        const lines = ev.split(/\r?\n/);
        let eventName = '';
        let dataStr = '';
        for (const line of lines) {
          if (line.startsWith('event:')) eventName = line.slice(6).trim();
          if (line.startsWith('data:')) dataStr = line.slice(5).trim();
        }
        if (!dataStr || dataStr === '[DONE]') continue;

        let chunkData;
        try { chunkData = JSON.parse(dataStr); } catch (_) { continue; }
        if (chunkData && chunkData.error) {
          errored = true;
          placeholder.bubble.textContent = '❌ ' + formatChatError(chunkData.error);
          break;
        }
        if (chunkData.model) actualModel = chunkData.model;
        const choice = (chunkData.choices || [])[0] || {};
        const delta = choice.delta || {};
        if (typeof delta.content === 'string') {
          if (assembled === '') placeholder.bubble.innerHTML = '';
          assembled += delta.content;
          placeholder.bubble.textContent = assembled;
        } else if (typeof choice.message?.content === 'string') {
          if (assembled === '') placeholder.bubble.innerHTML = '';
          assembled = choice.message.content;
          placeholder.bubble.textContent = assembled;
        }

        const wrap = document.getElementById('chat-messages');
        if (wrap) wrap.scrollTop = wrap.scrollHeight;
      }
    }

    if (errored) return { ok: false, content: '' };

    if (!assembled) {
      placeholder.bubble.textContent = '⚠ Model không trả về nội dung. Hãy thử chọn model khác.';
      return { ok: false, content: '' };
    }

    if (actualModel && placeholder.meta) {
      placeholder.meta.textContent = `${actualModel} · Hoàn thành`;
    }

    enrichBubble(placeholder.bubble, assembled);
    return { ok: true, content: assembled };
  }

  async function _sendNonStream(payload, modelLabel) {
    const placeholder = _appendBubble('assistant', '⏳ Đang nghĩ…', modelLabel);
    const { data, ok } = await _post('/api/chatbot/chat', payload);
    if (!ok || data?.ok === false) {
      placeholder.bubble.textContent = '❌ ' + formatChatError(data);
      return { ok: false, content: '' };
    }
    const content = data.content || '(không có nội dung)';
    enrichBubble(placeholder.bubble, content);
    if (data.model && placeholder.meta) {
      placeholder.meta.textContent = `${data.model} · Hoàn thành`;
    }
    return { ok: true, content };
  }

  // ── Auto-resize Input Textarea ────────────────────────────────────────
  function _autoresize(ta) {
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(160, Math.max(44, ta.scrollHeight)) + 'px';
  }

  // ── Keyboard Binding ──────────────────────────────────────────────────
  function _bindKeyboard() {
    const inp = document.getElementById('chat-input');
    if (inp && !inp._chatBound) {
      inp.addEventListener('input', () => _autoresize(inp));
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

  // ── Tool Tabs (Chat / Vision / Image / TTS / STT / Embed) ─────────────
  const _MEDIA_KIND_FOR_TOOL = {
    vision: null,
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
      p.style.display = on ? (tool === 'chat' ? 'flex' : 'block') : 'none';
    });

    document.querySelectorAll('.chat-tab-btn').forEach(btn => {
      const active = btn.getAttribute('data-tool') === tool;
      btn.classList.toggle('active', active);
      if (active) {
        btn.classList.add('bg-white', 'dark:bg-slate-700', 'text-blue-600', 'dark:text-blue-400', 'shadow-2xs', 'font-semibold');
        btn.classList.remove('text-slate-600', 'dark:text-slate-400');
      } else {
        btn.classList.remove('bg-white', 'dark:bg-slate-700', 'text-blue-600', 'dark:text-blue-400', 'shadow-2xs', 'font-semibold');
        btn.classList.add('text-slate-600', 'dark:text-slate-400');
      }
    });

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
    if (!sel || sel._loaded) return;
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
      for (const m of arr) og.appendChild(_optionEl(m.id, m.name || m.id));
      sel.appendChild(og);
    }
    if (selectId === 'chat-img-model') {
      const imgOpt = sel.querySelector('option[value="gemini-3.1-flash-image"]') || sel.querySelector('option');
      if (imgOpt) sel.value = imgOpt.value;
    }
    sel._loaded = true;
  }

  function _optionEl(value, label) {
    const o = document.createElement('option');
    o.value = value; o.textContent = label;
    return o;
  }

  function _populateVisionModels() {
    const sel = document.getElementById('chat-vision-model');
    if (!sel || sel._loaded) return;
    sel.replaceChildren();
    const items = state.models || [];
    for (const m of items) sel.appendChild(_optionEl(m.id, m.name || m.id));
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
      img.className = 'max-w-xs max-h-60 rounded-xl border border-slate-200 dark:border-slate-800 my-2';
      preview.appendChild(img);
    }

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
        meta.className = 'text-slate-400 text-xs mb-1';
        meta.textContent = '✓ ' + (data.model || model);
        const body = document.createElement('div');
        body.className = 'p-3 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl text-xs leading-relaxed whitespace-pre-wrap';
        body.textContent = data.content || '(không có nội dung)';
        result.appendChild(meta);
        result.appendChild(body);
      }
    } catch (e) {
      if (result) result.textContent = '❌ ' + e.message;
    }
  }

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
    if (result) result.innerHTML = '<div class="col-span-full p-4 text-center text-xs text-slate-500">⏳ Đang sinh ảnh AI...</div>';

    const { data, ok } = await _post('/api/chatbot/image', payload);
    if (!result) return;
    if (!ok || data?.ok === false) {
      result.innerHTML = `<div class="col-span-full p-4 text-center text-xs text-rose-500">❌ ${data?.message || data?.error || 'lỗi'}</div>`;
      return;
    }
    result.replaceChildren();
    for (const img of (data.images || [])) {
      const wrap = document.createElement('div');
      wrap.className = 'border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-slate-50 dark:bg-slate-950 shadow-2xs';
      const el = document.createElement('img');
      el.className = 'w-full aspect-square object-cover';
      if (img.url) el.src = img.url;
      else if (img.b64_json) {
        const mime = img.mime || (img.b64_json.startsWith('/9j/') ? 'image/jpeg' : 'image/png');
        el.src = `data:${mime};base64,` + img.b64_json;
      }
      const meta = document.createElement('div');
      meta.className = 'p-2 flex items-center justify-between text-xs text-slate-500';
      meta.textContent = data.model || 'AI Image';
      if (img.url) {
        const a = document.createElement('a');
        a.href = img.url; a.target = '_blank'; a.textContent = 'Mở ảnh';
        a.className = 'text-blue-600 hover:underline';
        meta.appendChild(a);
      }
      wrap.appendChild(el);
      wrap.appendChild(meta);
      result.appendChild(wrap);
    }
  }

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
    if (result) result.innerHTML = '<div class="p-3 text-xs text-slate-500">⏳ Đang tạo giọng đọc...</div>';

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
        audio.className = 'w-full my-2';
        const meta = document.createElement('div');
        meta.className = 'text-xs text-slate-500 flex items-center gap-3';
        meta.innerHTML = `<span>✓ ${payload.model || ''}</span> <a download="tts.${payload.format}" href="${url}" class="text-blue-600 hover:underline">⬇ Tải về</a>`;
        result.appendChild(audio);
        result.appendChild(meta);
      }
    } catch (e) {
      if (result) result.innerHTML = `<div class="p-3 text-xs text-rose-500">❌ ${e.message}</div>`;
    }
  }

  async function chatSttRun() {
    const file = document.getElementById('chat-stt-file')?.files?.[0];
    if (!file) return _toast('Chọn file audio/video.', 'warning');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('model', document.getElementById('chat-stt-model')?.value || 'openai/whisper-1');
    const lang = document.getElementById('chat-stt-lang')?.value?.trim();
    if (lang) fd.append('language', lang);
    const fmt = document.getElementById('chat-stt-format')?.value || 'text';
    fd.append('response_format', fmt);

    const result = document.getElementById('chat-stt-result');
    if (result) result.textContent = '⏳ Đang phiên âm…';
    try {
      const resp = await fetch('/api/chatbot/stt', { method: 'POST', body: fd });
      const data = await resp.json();
      if (!resp.ok || data?.ok === false) throw new Error(data?.error || 'Lỗi phiên âm');
      if (result) {
        result.textContent = typeof data.text === 'string' ? data.text : JSON.stringify(data.result || data, null, 2);
      }
    } catch (e) {
      if (result) result.textContent = '❌ ' + e.message;
    }
  }

  async function chatEmbRun() {
    const raw = (document.getElementById('chat-emb-input')?.value || '').trim();
    if (!raw) return _toast('Nhập văn bản.', 'warning');
    const inputs = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const payload = {
      input: inputs.length === 1 ? inputs[0] : inputs,
      model: document.getElementById('chat-emb-model')?.value || '',
    };
    const result = document.getElementById('chat-emb-result');
    if (result) result.textContent = '⏳ Đang tính embedding…';

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
    summary.className = 'text-slate-500 text-xs mb-2';
    summary.textContent = `✓ ${data.model} · ${vectors.length} vector × ${dim} chiều`;
    result.appendChild(summary);
    for (let i = 0; i < vectors.length; i++) {
      const v = vectors[i].embedding || [];
      const row = document.createElement('div');
      row.className = 'border border-slate-200 dark:border-slate-800 rounded-lg p-2.5 mb-2 bg-slate-50 dark:bg-slate-950 font-mono text-[11px]';
      const head = document.createElement('div');
      head.className = 'font-bold mb-1 text-slate-700 dark:text-slate-300';
      head.textContent = `[${i}] ${(inputs[i] || '').slice(0, 70)}`;
      const preview = v.slice(0, 8).map(n => n.toFixed(4)).join(', ') + (v.length > 8 ? `, … (+${v.length - 8})` : '');
      const body = document.createElement('div');
      body.className = 'text-slate-500';
      body.textContent = preview;
      row.appendChild(head);
      row.appendChild(body);
      result.appendChild(row);
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────
  async function chatInit() {
    _bindKeyboard();
    await chatLoadConfig();
    await chatRefreshStatus();
    await chatLoadModels();
    await chatLoadRouting();
    await chatLoadSessions();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', chatInit);
  } else {
    chatInit();
  }

  // Expose global functions to window
  window.chatInit               = chatInit;
  window.chatSend               = chatSend;
  window.chatStop               = chatStop;
  window.chatLoadSessions       = chatLoadSessions;
  window.chatSelectSession      = chatSelectSession;
  window.chatNewSession         = chatNewSession;
  window.chatDeleteSession      = chatDeleteSession;
  window.chatRenameSession      = chatRenameSession;
  window.chatFilterSessions     = chatFilterSessions;
  window.chatToggleSidebar      = chatToggleSidebar;
  window.chatOpenSettingsModal  = chatOpenSettingsModal;
  window.chatCloseSettingsModal = chatCloseSettingsModal;
  window.chatSaveConfigModal    = chatSaveConfigModal;
  window.chatInsertStarterPrompt= chatInsertStarterPrompt;
  window.chatAttachInlineImage  = chatAttachInlineImage;
  window.chatClearInlineImage   = chatClearInlineImage;
  window.chatLoadConfig         = chatLoadConfig;
  window.chatSaveConfig         = chatSaveConfig;
  window.chatLoadModels         = chatLoadModels;
  window.chatRefreshStatus      = chatRefreshStatus;
  window.chatToggleSetting      = chatToggleSetting;
  window.chatLoadRouting         = chatLoadRouting;
  window.chatSaveRouting        = chatSaveRouting;
  window.chatPreviewRouting     = chatPreviewRouting;
  window.chatToolSwitch         = chatToolSwitch;
  window.chatVisionSend         = chatVisionSend;
  window.chatImageGen           = chatImageGen;
  window.chatTtsRun             = chatTtsRun;
  window.chatSttRun             = chatSttRun;
  window.chatEmbRun             = chatEmbRun;
})();

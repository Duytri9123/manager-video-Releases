/* ── Sales Video Editor wizard ──────────────────────────────────────────────
 * Mirrors the Process Video tab's 5-step flow, tailored for sales videos:
 *   1. Source  2. Product info  3. AI script + voiceover  4. Render  5. Publish
 * Reuses the .proc-* wizard styles. All state lives on window._salesState.
 * ------------------------------------------------------------------------- */

window._salesState = window._salesState || { source: null, output: '' };
let _salesWizStep = 1;
const _SALES_MAX = 5;

function salesInit() {
  salesWizGo(1);
}

function salesWizGo(n) {
  n = Math.max(1, Math.min(_SALES_MAX, n));
  // Forward guards
  if (n >= 2 && !window._salesState.source) {
    toast('Hãy chọn nguồn video trước (Bước 1).', 'warning');
    return;
  }
  if (n >= 5 && !window._salesState.output) {
    toast('Hãy render video xong trước khi đăng.', 'warning');
    return;
  }
  _salesWizStep = n;
  const root = document.getElementById('page-sales');
  if (!root) return;
  root.querySelectorAll('.proc-step').forEach(s => {
    s.style.display = (parseInt(s.dataset.salesStep, 10) === n) ? 'block' : 'none';
  });
  root.querySelectorAll('.proc-wiz-item').forEach(it => {
    const sn = parseInt(it.dataset.step, 10);
    it.classList.toggle('active', sn === n);
    it.classList.toggle('done', sn < n);
  });
  const c = document.getElementById('content'); if (c) c.scrollTop = 0;
}

/* ── Step 1: source ── */
async function salesUploadFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  document.getElementById('sales-file-name').textContent = '⏳ Đang tải lên...';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/upload_process_video', { method: 'POST', body: fd });
    const d = await r.json();
    if (d.ok) {
      document.getElementById('sales-video').value = d.path;
      document.getElementById('sales-file-name').textContent = '✓ ' + d.name;
      document.getElementById('sales-url').value = '';
    } else {
      document.getElementById('sales-file-name').textContent = '✗ ' + (d.error || 'Lỗi');
      toast('Tải lên thất bại', 'error');
    }
  } catch (e) {
    document.getElementById('sales-file-name').textContent = '✗ ' + e.message;
  }
}

function salesSetSource() {
  const path = document.getElementById('sales-video').value.trim();
  const url = document.getElementById('sales-url').value.trim();
  const val = path || url;
  if (!val) { toast('Chọn file hoặc nhập URL/đường dẫn.', 'warning'); return; }
  const isUrl = /^https?:\/\//i.test(val);
  window._salesState.source = { type: isUrl ? 'url' : 'file', val };
  const info = document.getElementById('sales-source-info');
  info.className = 'alert-info text-xs';
  info.innerHTML = `${isUrl ? '🔗 URL' : '📁 File'}: <span class="break-all">${val}</span>`;
  document.getElementById('sales-step1-next').style.display = 'flex';
  toast('✓ Đã chọn nguồn video', 'success');
}

/* ── Step 3: AI script + voiceover ── */
function _salesBuildPrompt() {
  const g = id => (document.getElementById(id)?.value || '').trim();
  const dur = g('sales-duration') || '30';
  return `Bạn là copywriter quảng cáo. Viết KỊCH BẢN LỒNG TIẾNG cho video bán hàng dài khoảng ${dur} giây bằng tiếng Việt, giọng điệu ${g('sales-tone') || 'năng động'}.
Sản phẩm: ${g('sales-name')}
Giá: ${g('sales-price') || 'liên hệ'}
Tính năng nổi bật:
${g('sales-features') || '(không có)'}
Đối tượng khách hàng: ${g('sales-audience') || 'phổ thông'}
Kêu gọi hành động: ${g('sales-cta') || 'Mua ngay'}
Hotline: ${g('sales-hotline') || ''}

Yêu cầu:
- Chỉ viết lời thoại để đọc (không ghi chú cảnh quay, không markdown).
- Hấp dẫn, dễ nghe, kết thúc bằng lời kêu gọi hành động.
- Sau kịch bản, xuống dòng và ghi "===CAPTION===" rồi viết 1 caption ngắn kèm 3-5 hashtag để đăng mạng xã hội.`;
}

async function salesGenScript() {
  const name = document.getElementById('sales-name').value.trim();
  if (!name) { toast('Nhập tên sản phẩm (Bước 2) trước.', 'warning'); salesWizGo(2); return; }
  const btn = document.getElementById('btn-sales-ai');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang viết...'; }
  try {
    const r = await fetch('/api/chatbot/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: _salesBuildPrompt() }] }),
    });
    const d = await r.json();
    if (d.ok && d.content) {
      let script = d.content, caption = '';
      const idx = d.content.indexOf('===CAPTION===');
      if (idx >= 0) {
        script = d.content.slice(0, idx).trim();
        caption = d.content.slice(idx + '===CAPTION==='.length).trim();
      }
      document.getElementById('sales-script').value = script;
      if (caption) document.getElementById('sales-caption').value = caption;
      toast('✨ AI đã viết kịch bản', 'success');
    } else {
      toast('❌ ' + (d.message || d.error || 'AI lỗi'), 'error');
    }
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '✨ AI viết kịch bản'; } }
}

async function salesPreviewVoice() {
  const text = document.getElementById('sales-script').value.trim();
  if (!text) { toast('Chưa có kịch bản để đọc.', 'warning'); return; }
  const btn = document.getElementById('btn-sales-preview');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang tạo...'; }
  try {
    const r = await fetch('/api/tts_to_mp3', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text.slice(0, 800),
        tts_engine: document.getElementById('sales-tts-engine').value,
        tts_voice: document.getElementById('sales-tts-voice').value,
      }),
    });
    if (!r.ok) {
      let msg = 'TTS lỗi';
      try { const j = await r.json(); msg = j.error || msg; } catch (e) {}
      toast('❌ ' + msg, 'error');
      return;
    }
    const blob = await r.blob();
    const audio = document.getElementById('sales-audio');
    audio.src = URL.createObjectURL(blob);
    audio.style.display = 'block';
    audio.play().catch(() => {});
    toast('▶ Nghe thử giọng', 'success');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '▶ Nghe thử giọng'; } }
}

/* ── Step 4: render ── */
function _salesLog(msg, level) {
  const box = document.getElementById('sales-log');
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'log-' + (level || 'info');
  div.textContent = msg;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function _salesProgress(pct) {
  const bar = document.getElementById('sales-pb');
  const lbl = document.getElementById('sales-pb-pct');
  if (bar) bar.style.width = pct + '%';
  if (lbl) lbl.textContent = pct + '%';
}

async function salesRun() {
  const src = window._salesState.source;
  if (!src) { toast('Chưa có nguồn video.', 'warning'); salesWizGo(1); return; }
  if (src.type === 'url') {
    toast('Hiện chỉ render được file đã tải lên. Hãy chọn file ở Bước 1.', 'warning');
    return;
  }
  const btn = document.getElementById('btn-sales-run');
  if (btn) btn.disabled = true;
  document.getElementById('sales-log').innerHTML = '';
  document.getElementById('sales-done').style.display = 'none';
  _salesProgress(0);

  const body = {
    video_path: src.val,
    script: document.getElementById('sales-script').value.trim(),
    tts_voice: document.getElementById('sales-tts-voice').value.trim(),
    voiceover: document.getElementById('sales-voiceover').checked,
    burn_sub: document.getElementById('sales-burn-sub').checked,
  };

  try {
    const r = await fetch('/api/sales/render', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    // Stream NDJSON
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch (e) { continue; }
        if (msg.log) _salesLog(msg.log, msg.level);
        if (typeof msg.overall === 'number') _salesProgress(msg.overall);
        if (msg.done) {
          if (msg.ok && msg.output_path) {
            window._salesState.output = msg.output_path;
            document.getElementById('sales-output').value = msg.output_path;
            document.getElementById('sales-final-caption').value =
              document.getElementById('sales-caption').value;
            document.getElementById('sales-done').style.display = 'block';
            toast('✅ Render xong!', 'success');
          } else {
            toast('❌ Render thất bại', 'error');
          }
        }
      }
    }
  } catch (e) {
    _salesLog('✗ Lỗi: ' + e.message, 'error');
    toast('❌ ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ── Step 5: publish handoff ── */
function salesSendToPublish() {
  const out = window._salesState.output;
  if (!out) { toast('Chưa có video kết quả.', 'warning'); return; }
  // Hand the output + caption to the Publish tab if its globals exist
  window._publishLastOutputPath = out;
  window._publishPrefillCaption = document.getElementById('sales-final-caption').value;
  if (typeof switchPage === 'function') switchPage('publish');
  toast('👉 Đã chuyển sang tab Đăng video', 'success');
}

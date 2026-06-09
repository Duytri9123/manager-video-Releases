/* ── Ad Video Editor wizard ──────────────────────────────────────────────
 * Mirrors the Sales Video tab's 5-step flow, tailored for ad/marketing clips:
 *   1. Source  2. Campaign info  3. AI script + voiceover  4. Render  5. Publish
 * Reuses the .proc-* wizard styles. All state lives on window._adsState.
 * ------------------------------------------------------------------------- */

window._adsState = window._adsState || { source: null, output: '' };
let _adsWizStep = 1;
const _ADS_MAX = 5;

function adsInit() {
  adsWizGo(1);
}

function adsWizGo(n) {
  n = Math.max(1, Math.min(_ADS_MAX, n));
  // Forward guards
  if (n >= 2 && !window._adsState.source) {
    toast('Hãy chọn nguồn video trước (Bước 1).', 'warning');
    return;
  }
  if (n >= 5 && !window._adsState.output) {
    toast('Hãy render video xong trước khi đăng.', 'warning');
    return;
  }
  _adsWizStep = n;
  const root = document.getElementById('page-ads');
  if (!root) return;
  root.querySelectorAll('.proc-step').forEach(s => {
    s.style.display = (parseInt(s.dataset.adsStep, 10) === n) ? 'block' : 'none';
  });
  root.querySelectorAll('.proc-wiz-item').forEach(it => {
    const sn = parseInt(it.dataset.step, 10);
    it.classList.toggle('active', sn === n);
    it.classList.toggle('done', sn < n);
  });
  const c = document.getElementById('content'); if (c) c.scrollTop = 0;
}

/* ── Step 1: source ── */
async function adsUploadFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  document.getElementById('ads-file-name').textContent = '⏳ Đang tải lên...';
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/upload_process_video', { method: 'POST', body: fd });
    const d = await r.json();
    if (d.ok) {
      document.getElementById('ads-video').value = d.path;
      document.getElementById('ads-file-name').textContent = '✓ ' + d.name;
      document.getElementById('ads-url').value = '';
    } else {
      document.getElementById('ads-file-name').textContent = '✗ ' + (d.error || 'Lỗi');
      toast('Tải lên thất bại', 'error');
    }
  } catch (e) {
    document.getElementById('ads-file-name').textContent = '✗ ' + e.message;
  }
}

function adsSetSource() {
  const path = document.getElementById('ads-video').value.trim();
  const url = document.getElementById('ads-url').value.trim();
  const val = path || url;
  if (!val) { toast('Chọn file hoặc nhập URL/đường dẫn.', 'warning'); return; }
  const isUrl = /^https?:\/\//i.test(val);
  window._adsState.source = { type: isUrl ? 'url' : 'file', val };
  const info = document.getElementById('ads-source-info');
  info.className = 'alert-info text-xs';
  info.innerHTML = `${isUrl ? '🔗 URL' : '📁 File'}: <span class="break-all">${val}</span>`;
  document.getElementById('ads-step1-next').style.display = 'flex';
  toast('✓ Đã chọn nguồn video', 'success');
}

/* ── Step 3: AI script + voiceover ── */
function _adsBuildPrompt() {
  const g = id => (document.getElementById(id)?.value || '').trim();
  const dur = g('ads-duration') || '20';
  return `Bạn là copywriter quảng cáo chuyên nghiệp. Viết KỊCH BẢN LỒNG TIẾNG cho video quảng cáo dài khoảng ${dur} giây bằng tiếng Việt, giọng điệu ${g('ads-tone') || 'năng động, cuốn hút'}.
Thương hiệu/Sản phẩm: ${g('ads-brand')}
Mục tiêu chiến dịch: ${g('ads-goal') || 'tăng nhận diện thương hiệu'}
Thông điệp chính / USP:
${g('ads-message') || '(không có)'}
Hook 3 giây đầu: ${g('ads-hook') || '(AI tự nghĩ một hook gây chú ý mạnh)'}
Đối tượng mục tiêu: ${g('ads-audience') || 'phổ thông'}
Kêu gọi hành động: ${g('ads-cta') || 'Tìm hiểu ngay'}

Yêu cầu:
- Mở đầu bằng một HOOK mạnh trong 3 giây đầu để giữ chân người xem.
- Chỉ viết lời thoại để đọc (không ghi chú cảnh quay, không markdown).
- Ngắn gọn, nhịp nhanh, nhấn mạnh lợi ích, kết thúc bằng lời kêu gọi hành động rõ ràng.
- Sau kịch bản, xuống dòng và ghi "===CAPTION===" rồi viết 1 caption ngắn kèm 3-5 hashtag để đăng mạng xã hội.`;
}

async function adsGenScript() {
  const brand = document.getElementById('ads-brand').value.trim();
  if (!brand) { toast('Nhập thương hiệu/sản phẩm (Bước 2) trước.', 'warning'); adsWizGo(2); return; }
  const btn = document.getElementById('btn-ads-ai');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang viết...'; }
  try {
    const r = await fetch('/api/chatbot/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: _adsBuildPrompt() }] }),
    });
    const d = await r.json();
    if (d.ok && d.content) {
      let script = d.content, caption = '';
      const idx = d.content.indexOf('===CAPTION===');
      if (idx >= 0) {
        script = d.content.slice(0, idx).trim();
        caption = d.content.slice(idx + '===CAPTION==='.length).trim();
      }
      document.getElementById('ads-script').value = script;
      if (caption) document.getElementById('ads-caption').value = caption;
      toast('✨ AI đã viết kịch bản', 'success');
    } else {
      toast('❌ ' + (d.message || d.error || 'AI lỗi'), 'error');
    }
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '✨ AI viết kịch bản'; } }
}

async function adsPreviewVoice() {
  const text = document.getElementById('ads-script').value.trim();
  if (!text) { toast('Chưa có kịch bản để đọc.', 'warning'); return; }
  const btn = document.getElementById('btn-ads-preview');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Đang tạo...'; }
  try {
    const r = await fetch('/api/tts_to_mp3', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text.slice(0, 800),
        tts_engine: document.getElementById('ads-tts-engine').value,
        tts_voice: document.getElementById('ads-tts-voice').value,
      }),
    });
    if (!r.ok) {
      let msg = 'TTS lỗi';
      try { const j = await r.json(); msg = j.error || msg; } catch (e) {}
      toast('❌ ' + msg, 'error');
      return;
    }
    const blob = await r.blob();
    const audio = document.getElementById('ads-audio');
    audio.src = URL.createObjectURL(blob);
    audio.style.display = 'block';
    audio.play().catch(() => {});
    toast('▶ Nghe thử giọng', 'success');
  } catch (e) { toast('❌ ' + e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '▶ Nghe thử giọng'; } }
}

/* ── Step 4: render ── */
function _adsLog(msg, level) {
  const box = document.getElementById('ads-log');
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'log-' + (level || 'info');
  div.textContent = msg;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}
function _adsProgress(pct) {
  const bar = document.getElementById('ads-pb');
  const lbl = document.getElementById('ads-pb-pct');
  if (bar) bar.style.width = pct + '%';
  if (lbl) lbl.textContent = pct + '%';
}

async function adsRun() {
  const src = window._adsState.source;
  if (!src) { toast('Chưa có nguồn video.', 'warning'); adsWizGo(1); return; }
  if (src.type === 'url') {
    toast('Hiện chỉ render được file đã tải lên. Hãy chọn file ở Bước 1.', 'warning');
    return;
  }
  const btn = document.getElementById('btn-ads-run');
  if (btn) btn.disabled = true;
  document.getElementById('ads-log').innerHTML = '';
  document.getElementById('ads-done').style.display = 'none';
  _adsProgress(0);

  const body = {
    video_path: src.val,
    script: document.getElementById('ads-script').value.trim(),
    tts_voice: document.getElementById('ads-tts-voice').value.trim(),
    voiceover: document.getElementById('ads-voiceover').checked,
    burn_sub: document.getElementById('ads-burn-sub').checked,
  };

  try {
    const r = await fetch('/api/ads/render', {
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
        if (msg.log) _adsLog(msg.log, msg.level);
        if (typeof msg.overall === 'number') _adsProgress(msg.overall);
        if (msg.done) {
          if (msg.ok && msg.output_path) {
            window._adsState.output = msg.output_path;
            document.getElementById('ads-output').value = msg.output_path;
            document.getElementById('ads-final-caption').value =
              document.getElementById('ads-caption').value;
            document.getElementById('ads-done').style.display = 'block';
            toast('✅ Render xong!', 'success');
          } else {
            toast('❌ Render thất bại', 'error');
          }
        }
      }
    }
  } catch (e) {
    _adsLog('✗ Lỗi: ' + e.message, 'error');
    toast('❌ ' + e.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ── Step 5: publish handoff ── */
function adsSendToPublish() {
  const out = window._adsState.output;
  if (!out) { toast('Chưa có video kết quả.', 'warning'); return; }
  // Hand the output + caption to the Publish tab if its globals exist
  window._publishLastOutputPath = out;
  window._publishPrefillCaption = document.getElementById('ads-final-caption').value;
  if (typeof switchPage === 'function') switchPage('publish');
  toast('👉 Đã chuyển sang tab Đăng video', 'success');
}

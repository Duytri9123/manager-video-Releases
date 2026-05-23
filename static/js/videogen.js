/* ── videogen.js — Gemini Veo 2 Video Generation ────────────────────────── */

window._vgInited = false;
window._vgPolling = null;
window._vgImage = null; // { name, dataUrl, file }

/* ───────── Init ───────── */
function vgInit() {
  if (window._vgInited) return;
  window._vgInited = true;
  vgLoadConfig();
  vgSetupDragDrop();
}

/* ───────── Load saved config ───────── */
async function vgLoadConfig() {
  try {
    const r = await fetch('/api/videogen/config');
    const d = await r.json();
    if (d.ok && d.config) {
      if (d.config.api_key) document.getElementById('vg-api-key').value = d.config.api_key;
      if (d.config.model) document.getElementById('vg-model').value = d.config.model;
      if (d.config.aspect_ratio) document.getElementById('vg-aspect').value = d.config.aspect_ratio;
      if (d.config.duration) document.getElementById('vg-duration').value = d.config.duration;
    }
  } catch (e) {
    console.warn('vgLoadConfig error:', e);
  }
}

/* ───────── Check API Key ───────── */
async function vgCheckApi() {
  const key = document.getElementById('vg-api-key').value.trim();
  if (!key) { toast('Vui lòng nhập API Key', 'warning'); return; }

  const statusEl = document.getElementById('vg-api-status');
  statusEl.className = 'vg-status status-run';
  statusEl.innerHTML = '<span class="dot dot-blue"></span> Đang kiểm tra...';

  try {
    const r = await fetch('/api/videogen/check_key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key })
    });
    const d = await r.json();
    if (d.ok) {
      statusEl.className = 'vg-status status-done';
      statusEl.innerHTML = '<span class="dot dot-green"></span> API Key hợp lệ';
      toast('API Key hợp lệ!', 'success');
    } else {
      statusEl.className = 'vg-status status-error';
      statusEl.innerHTML = '<span class="dot dot-red"></span> Lỗi: ' + (d.error || 'Không hợp lệ');
      toast('API Key không hợp lệ: ' + (d.error || ''), 'error');
    }
  } catch (e) {
    statusEl.className = 'vg-status status-error';
    statusEl.innerHTML = '<span class="dot dot-red"></span> Lỗi kết nối';
    toast('Lỗi kết nối server', 'error');
  }
}

/* ───────── Drag & Drop image ───────── */
function vgSetupDragDrop() {
  const zone = document.getElementById('vg-drop-zone');
  if (!zone) return;

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) vgSetImage(file);
  });
}

function vgOnImageSelect(event) {
  const file = event.target.files[0];
  if (file) vgSetImage(file);
}

function vgSetImage(file) {
  const reader = new FileReader();
  reader.onload = e => {
    window._vgImage = { name: file.name, dataUrl: e.target.result, file };
    document.getElementById('vg-img-preview').src = e.target.result;
    document.getElementById('vg-img-preview-wrap').style.display = 'flex';
    document.getElementById('vg-drop-zone').style.display = 'none';
  };
  reader.readAsDataURL(file);
}

function vgClearImage() {
  window._vgImage = null;
  document.getElementById('vg-img-preview-wrap').style.display = 'none';
  document.getElementById('vg-drop-zone').style.display = '';
  document.getElementById('vg-img-input').value = '';
}

/* ───────── Sample prompts ───────── */
const VG_SAMPLES = [
  "A cinematic aerial shot of a coastal city at golden hour, waves crashing against cliffs, seagulls flying, warm sunlight reflecting off glass buildings, slow camera pan from left to right, 4K cinematic quality",
  "A cute cartoon cat sitting at a tiny desk, typing on a laptop, coffee cup steaming beside it, cozy room with bookshelves, soft ambient lighting, Studio Ghibli style animation",
  "Timelapse of a flower blooming in a garden, morning dew drops on petals, soft bokeh background, macro lens, natural lighting transitioning from dawn to midday",
  "A astronaut floating in space with Earth in the background, stars twinkling, slow rotation, cinematic lighting, sci-fi atmosphere, Hans Zimmer style epic feeling",
  "Underwater scene of colorful coral reef with tropical fish swimming, sunlight rays penetrating through clear blue water, gentle current moving seaweed, National Geographic quality"
];

function vgLoadSample() {
  const idx = Math.floor(Math.random() * VG_SAMPLES.length);
  document.getElementById('vg-prompt').value = VG_SAMPLES[idx];
  toast('Đã load prompt mẫu', 'info');
}

/* ───────── Log helper ───────── */
function vgLog(msg, level) {
  const el = document.getElementById('vg-log');
  const time = new Date().toLocaleTimeString('vi-VN');
  const colors = { info: 'var(--text)', success: 'var(--success)', error: 'var(--error)', warn: 'var(--warning)' };
  const color = colors[level] || colors.info;
  el.innerHTML += `<div style="color:${color}">[${time}] ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

/* ───────── Generate video ───────── */
async function vgGenerate() {
  const prompt = document.getElementById('vg-prompt').value.trim();
  if (!prompt) { toast('Vui lòng nhập prompt mô tả video', 'warning'); return; }

  const apiKey = document.getElementById('vg-api-key').value.trim();
  if (!apiKey) { toast('Vui lòng nhập Gemini API Key', 'warning'); return; }

  const model = document.getElementById('vg-model').value;
  const aspect = document.getElementById('vg-aspect').value;
  const duration = document.getElementById('vg-duration').value;
  const count = document.getElementById('vg-count').value;

  // Prepare form data (for image upload)
  const formData = new FormData();
  formData.append('prompt', prompt);
  formData.append('api_key', apiKey);
  formData.append('model', model);
  formData.append('aspect_ratio', aspect);
  formData.append('duration', duration);
  formData.append('count', count);

  if (window._vgImage && window._vgImage.file) {
    formData.append('image', window._vgImage.file);
  }

  // UI state
  document.getElementById('vg-btn-generate').disabled = true;
  document.getElementById('vg-btn-stop').classList.remove('hidden');
  document.getElementById('vg-progress-row').style.display = '';
  document.getElementById('vg-results').style.display = 'none';

  const statusEl = document.getElementById('vg-gen-status');
  statusEl.className = 'vg-status status-run';
  statusEl.innerHTML = '<span class="dot dot-blue"></span> Đang tạo video...';

  vgLog('🚀 Bắt đầu tạo video...', 'info');
  vgLog(`Model: ${model} | Tỷ lệ: ${aspect} | Thời lượng: ${duration}s | Số lượng: ${count}`, 'info');
  if (window._vgImage) vgLog(`📷 Image-to-Video mode (ảnh: ${window._vgImage.name})`, 'info');

  try {
    const r = await fetch('/api/videogen/generate', { method: 'POST', body: formData });
    const d = await r.json();

    if (d.ok) {
      vgLog('✅ Đã gửi request. Task ID: ' + d.task_id, 'success');
      vgStartPolling(d.task_id);
    } else {
      vgLog('❌ Lỗi: ' + (d.error || 'Unknown'), 'error');
      vgResetUI();
      toast('Lỗi tạo video: ' + (d.error || ''), 'error');
    }
  } catch (e) {
    vgLog('❌ Lỗi kết nối: ' + e.message, 'error');
    vgResetUI();
    toast('Lỗi kết nối server', 'error');
  }
}

/* ───────── Poll status ───────── */
function vgStartPolling(taskId) {
  let progress = 10;
  const bar = document.getElementById('vg-progress-bar');
  const pct = document.getElementById('vg-progress-pct');
  const label = document.getElementById('vg-progress-label');

  window._vgPolling = setInterval(async () => {
    try {
      const r = await fetch('/api/videogen/status/' + taskId);
      const d = await r.json();

      if (d.state === 'ACTIVE' || d.state === 'PROCESSING') {
        progress = Math.min(progress + 5, 90);
        bar.style.width = progress + '%';
        pct.textContent = progress + '%';
        label.textContent = 'Đang xử lý... (có thể mất 1-3 phút)';
        if (d.message) vgLog('⏳ ' + d.message, 'info');
      } else if (d.state === 'SUCCEEDED' || d.state === 'COMPLETE') {
        clearInterval(window._vgPolling);
        window._vgPolling = null;
        bar.style.width = '100%';
        pct.textContent = '100%';
        label.textContent = 'Hoàn thành!';
        vgLog('🎉 Video đã tạo xong!', 'success');
        vgShowResults(d.videos || []);
        vgResetUI();

        const statusEl = document.getElementById('vg-gen-status');
        statusEl.className = 'vg-status status-done';
        statusEl.innerHTML = '<span class="dot dot-green"></span> Hoàn thành';
      } else if (d.state === 'FAILED') {
        clearInterval(window._vgPolling);
        window._vgPolling = null;
        vgLog('❌ Thất bại: ' + (d.error || 'Unknown error'), 'error');
        vgResetUI();
        toast('Tạo video thất bại: ' + (d.error || ''), 'error');
      }
    } catch (e) {
      console.warn('Poll error:', e);
    }
  }, 5000); // Poll every 5 seconds
}

/* ───────── Cancel ───────── */
function vgCancel() {
  if (window._vgPolling) {
    clearInterval(window._vgPolling);
    window._vgPolling = null;
  }
  vgLog('⏹ Đã huỷ.', 'warn');
  vgResetUI();
}

/* ───────── Reset UI ───────── */
function vgResetUI() {
  document.getElementById('vg-btn-generate').disabled = false;
  document.getElementById('vg-btn-stop').classList.add('hidden');
}

/* ───────── Show results ───────── */
function vgShowResults(videos) {
  const container = document.getElementById('vg-results');
  const grid = document.getElementById('vg-preview-grid');
  const countEl = document.getElementById('vg-result-count');

  container.style.display = '';
  countEl.textContent = `${videos.length} video`;
  grid.innerHTML = '';

  videos.forEach((v, i) => {
    const card = document.createElement('div');
    card.className = 'vg-video-card';
    card.innerHTML = `
      <video controls preload="metadata">
        <source src="${v.url}" type="video/mp4">
      </video>
      <div class="vg-card-actions">
        <span class="text-xs text-muted">Video ${i + 1}</span>
        <a href="${v.url}" download="gemini_video_${i + 1}.mp4" class="btn btn-secondary btn-sm" style="margin-left:auto">
          💾 Tải về
        </a>
      </div>
    `;
    grid.appendChild(card);
  });
}

/* ───────── Expose to switchPage ───────── */
// Called from app.js switchPage when tab = 'videogen'

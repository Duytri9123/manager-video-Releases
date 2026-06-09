/**
 * ai_studio.js — Unified AI Studio (Video + Image + Idea→Video)
 */
(function(){
'use strict';

let _vImage = null; // {file, dataUrl}
let _vTaskId = null, _vPoll = null;
let _iTaskId = null, _iPoll = null;
let _ideaJobId = null, _ideaPoll = null;

// ── Mode switching ───────────────────────────────────────────────────────────
window.aiSwitchMode = function(mode) {
  document.querySelectorAll('#page-ai_studio .mode-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.mode === mode);
  });
  document.querySelectorAll('#page-ai_studio .mode-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'panel-' + mode);
  });
};

// ── Config ───────────────────────────────────────────────────────────────────
// Nạp danh sách model ảnh THẬT từ 9Router (/v1/models/image) vào dropdown,
// chèn trước các nhóm tĩnh (Gemini/OpenAI). Dùng chung nguồn với Thumbnail & Truyện.
let _aiImgModelsLoaded = false;
window.aiLoadImageModels = async function() {
  const sel = document.getElementById('ai-image-model');
  if (!sel || _aiImgModelsLoaded) return;
  _aiImgModelsLoaded = true;
  try {
    const r = await fetch('/api/story/ai_image_models').then(res => res.json());
    if (!r || !r.ok || !Array.isArray(r.models) || !r.models.length) {
      _aiImgModelsLoaded = false;
      return;
    }
    sel.querySelectorAll('optgroup[data-nr="1"]').forEach(g => g.remove());
    const existing = new Set(Array.from(sel.options).map(o => o.value));
    const groups = {};
    r.models.forEach(function(m) {
      const id = (m && (m.id || m)) || '';
      if (!id || existing.has(id)) return;
      const prefix = id.includes('/') ? id.split('/')[0] : (m.owned_by || 'khác');
      (groups[prefix] = groups[prefix] || []).push(id);
    });
    const labelMap = {
      openai: '🟢 OpenAI', cx: '⭐ Codex (SSE)', nb: '🍌 NanoBanana',
      google: '🔷 Google', sdwebui: '🖥 Local (SD WebUI)', flux: '⚡ FLUX',
    };
    const staticGroups = sel.querySelectorAll('optgroup[data-static="1"]');
    const beforeNode = staticGroups.length > 1 ? staticGroups[1] : (staticGroups[0] || null);
    Object.keys(groups).forEach(function(prefix) {
      const grp = document.createElement('optgroup');
      grp.setAttribute('data-nr', '1');
      grp.label = labelMap[prefix] || ('9Router · ' + prefix);
      groups[prefix].forEach(function(id) {
        const opt = document.createElement('option');
        opt.value = id; opt.textContent = id;
        grp.appendChild(opt);
      });
      sel.insertBefore(grp, beforeNode);
    });
  } catch (_) {
    _aiImgModelsLoaded = false;
  }
};

window.aiLoadConfig = async function() {
  try {
    await aiLoadImageModels();
    const r = await fetch('/api/ai/config');
    const d = await r.json();
    if (!d.ok) return;
    const keyEl = document.getElementById('ai-api-key');
    if (d.gemini_key_masked && keyEl) keyEl.placeholder = d.gemini_key_masked + ' (đã lưu)';
    if (d.video_model) document.getElementById('ai-video-model').value = d.video_model;
    if (d.image_model) document.getElementById('ai-image-model').value = d.image_model;
    if (d.llm_model) document.getElementById('ai-llm-model').value = d.llm_model;
    const badge = document.getElementById('ai-key-badge');
    const configCard = document.getElementById('ai-config-card');
    if (d.has_gemini_key) {
      badge.textContent = '✅ Key OK'; badge.className = 'badge badge-green';
      // Collapse config nếu đã có key
      if (configCard) configCard.classList.add('card-collapsible', 'collapsed');
    } else {
      badge.textContent = '⚠️ Cần API Key'; badge.className = 'badge badge-yellow';
      // Mở config nếu chưa có key
      if (configCard) configCard.classList.remove('collapsed');
    }
  } catch(e) { console.warn('aiLoadConfig:', e); }
};

window.aiSaveConfig = async function() {
  const key = document.getElementById('ai-api-key').value.trim();
  const body = {
    video_model: document.getElementById('ai-video-model').value,
    image_model: document.getElementById('ai-image-model').value,
    llm_model: document.getElementById('ai-llm-model').value,
  };
  if (key && !key.includes('...')) body.api_key = key;
  try {
    await fetch('/api/ai/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    showToast('Đã lưu cấu hình', 'success');
    aiLoadConfig();
  } catch(e) { showToast('Lỗi lưu config', 'error'); }
};

// ══════════════════════════════════════════════════════════════════════════════
// VIDEO NHANH
// ══════════════════════════════════════════════════════════════════════════════
window.aiVOnImage = function(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    _vImage = {file, dataUrl: ev.target.result};
    document.getElementById('ai-v-img-preview').src = ev.target.result;
    document.getElementById('ai-v-img-wrap').style.display = 'flex';
    document.getElementById('ai-v-dropzone').style.display = 'none';
  };
  reader.readAsDataURL(file);
};

window.aiVClearImage = function() {
  _vImage = null;
  document.getElementById('ai-v-img-wrap').style.display = 'none';
  document.getElementById('ai-v-dropzone').style.display = '';
  document.getElementById('ai-v-file').value = '';
};

window.aiVideoGen = async function() {
  const prompt = document.getElementById('ai-v-prompt').value.trim();
  if (!prompt) { showToast('Nhập prompt mô tả video', 'warning'); return; }

  const fd = new FormData();
  fd.append('prompt', prompt);
  fd.append('model', document.getElementById('ai-video-model').value);
  fd.append('aspect_ratio', document.getElementById('ai-v-aspect').value);
  fd.append('duration', document.getElementById('ai-v-duration').value);
  fd.append('count', document.getElementById('ai-v-count').value);
  if (_vImage) fd.append('image', _vImage.file);

  _setStatus('ai-v-status', 'run', '⏳ Đang tạo...');
  document.getElementById('btn-ai-v-gen').disabled = true;
  document.getElementById('ai-v-progress').style.display = '';
  document.getElementById('ai-v-results').style.display = 'none';
  _log('ai-v-log', '🚀 Bắt đầu tạo video...', 'info');
  _log('ai-v-log', `Model: ${document.getElementById('ai-video-model').value} | ${document.getElementById('ai-v-aspect').value} | ${document.getElementById('ai-v-duration').value}s`, 'info');
  if (_vImage) _log('ai-v-log', '📷 Image-to-Video mode', 'info');

  try {
    const r = await fetch('/api/ai/video/generate', {method:'POST', body:fd});
    const d = await r.json();
    if (!d.ok) { _setStatus('ai-v-status','error','❌ '+d.error); _log('ai-v-log','❌ '+d.error,'error'); _resetVBtn(); return; }
    _vTaskId = d.task_id;
    _log('ai-v-log', '✅ Task: '+d.task_id+' — đang chờ Gemini xử lý (1-3 phút)...', 'success');
    _vPoll = setInterval(_pollVideo, 5000);
  } catch(e) {
    _setStatus('ai-v-status','error','❌ Lỗi kết nối');
    _log('ai-v-log', '❌ '+e.message, 'error');
    _resetVBtn();
  }
};

function _pollVideo() {
  if (!_vTaskId) return;
  fetch('/api/ai/video/status/'+_vTaskId).then(r=>r.json()).then(d => {
    if (!d.ok) return;
    if (d.state === 'SUCCEEDED') {
      clearInterval(_vPoll); _vPoll = null;
      _setStatus('ai-v-status','done','✅ Hoàn thành');
      document.getElementById('ai-v-bar').style.width = '100%';
      document.getElementById('ai-v-pct').textContent = '100%';
      _log('ai-v-log', '🎉 Video đã tạo xong! '+(d.videos||[]).length+' video.', 'success');
      _showVideoResults(d.videos || []);
      _resetVBtn();
    } else if (d.state === 'FAILED') {
      clearInterval(_vPoll); _vPoll = null;
      _setStatus('ai-v-status','error','❌ '+(d.error||'Lỗi'));
      _log('ai-v-log', '❌ Thất bại: '+(d.error||''), 'error');
      _resetVBtn();
      showToast('Tạo video thất bại: '+(d.error||''), 'error');
    } else {
      const bar = document.getElementById('ai-v-bar');
      const w = Math.min(90, parseInt(bar.style.width||'10') + 5);
      bar.style.width = w+'%';
      document.getElementById('ai-v-pct').textContent = w+'%';
      if (d.message) _log('ai-v-log', '⏳ '+d.message, 'info');
    }
  }).catch(()=>{});
}

function _showVideoResults(videos) {
  const grid = document.getElementById('ai-v-results');
  grid.style.display = '';
  grid.innerHTML = videos.map((v,i) => `
    <div class="result-card">
      <video controls><source src="${v.url}" type="video/mp4"></video>
      <div class="card-actions">
        <span class="text-xs text-muted">Video ${i+1}</span>
        <a href="${v.url}" download class="btn btn-secondary btn-sm" style="margin-left:auto">💾 Tải</a>
      </div>
    </div>
  `).join('');
}

function _resetVBtn() {
  document.getElementById('btn-ai-v-gen').disabled = false;
}

// ══════════════════════════════════════════════════════════════════════════════
// TẠO ẢNH
// ══════════════════════════════════════════════════════════════════════════════
window.aiImageGen = async function() {
  const prompt = document.getElementById('ai-i-prompt').value.trim();
  if (!prompt) { showToast('Nhập prompt mô tả ảnh', 'warning'); return; }

  _setStatus('ai-i-status','run','⏳ Đang tạo...');
  document.getElementById('ai-i-progress').style.display = '';
  document.getElementById('ai-i-results').style.display = 'none';
  document.getElementById('btn-ai-i-gen').disabled = true;
  _log('ai-i-log', '🚀 Bắt đầu tạo ảnh...', 'info');
  _log('ai-i-log', `Model: ${document.getElementById('ai-image-model').value} | ${document.getElementById('ai-i-aspect').value} | x${document.getElementById('ai-i-count').value}`, 'info');

  try {
    const r = await fetch('/api/ai/image/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        prompt,
        model: document.getElementById('ai-image-model').value,
        count: parseInt(document.getElementById('ai-i-count').value),
        aspect_ratio: document.getElementById('ai-i-aspect').value,
      })
    });
    const d = await r.json();
    if (!d.ok) { _setStatus('ai-i-status','error','❌ '+d.error); _log('ai-i-log','❌ '+d.error,'error'); document.getElementById('btn-ai-i-gen').disabled=false; return; }
    _iTaskId = d.task_id;
    _log('ai-i-log', '✅ Task: '+d.task_id+' — đang xử lý...', 'success');
    _iPoll = setInterval(_pollImage, 2000);
  } catch(e) {
    _setStatus('ai-i-status','error','❌ Lỗi kết nối');
    _log('ai-i-log', '❌ '+e.message, 'error');
    document.getElementById('btn-ai-i-gen').disabled = false;
  }
};

function _pollImage() {
  if (!_iTaskId) return;
  fetch('/api/ai/image/status/'+_iTaskId).then(r=>r.json()).then(d => {
    if (!d.ok) return;
    if (d.state === 'SUCCEEDED') {
      clearInterval(_iPoll); _iPoll = null;
      _setStatus('ai-i-status','done','✅ '+(d.images||[]).length+' ảnh');
      document.getElementById('ai-i-progress').style.display = 'none';
      document.getElementById('btn-ai-i-gen').disabled = false;
      _log('ai-i-log', '🎉 Hoàn thành! '+(d.images||[]).length+' ảnh.', 'success');
      _showImageResults(d.images || []);
    } else if (d.state === 'FAILED') {
      clearInterval(_iPoll); _iPoll = null;
      _setStatus('ai-i-status','error','❌ '+(d.error||'Lỗi'));
      document.getElementById('ai-i-progress').style.display = 'none';
      document.getElementById('btn-ai-i-gen').disabled = false;
      _log('ai-i-log', '❌ Thất bại: '+(d.error||''), 'error');
      showToast('Tạo ảnh thất bại: '+(d.error||''), 'error');
    }
  }).catch(()=>{});
}

function _showImageResults(images) {
  const grid = document.getElementById('ai-i-results');
  grid.style.display = '';
  grid.innerHTML = images.map((img,i) => `
    <div class="result-card">
      <img src="${img.url}" alt="Generated ${i+1}" style="cursor:pointer" onclick="window.open('${img.url}','_blank')">
      <div class="card-actions">
        <span class="text-xs text-muted">Ảnh ${i+1}</span>
        <a href="${img.url}" download class="btn btn-secondary btn-sm" style="margin-left:auto">💾 Tải</a>
      </div>
    </div>
  `).join('');
}

// ══════════════════════════════════════════════════════════════════════════════
// IDEA → VIDEO
// ══════════════════════════════════════════════════════════════════════════════
window.aiIdeaStart = async function() {
  const idea = document.getElementById('ai-idea-input').value.trim();
  if (!idea) { showToast('Nhập ý tưởng', 'warning'); return; }

  _setStatus('ai-idea-status','run','⏳ Đang chạy pipeline...');
  document.getElementById('btn-ai-idea').disabled = true;
  document.getElementById('ai-idea-progress').style.display = '';
  document.getElementById('ai-idea-result').style.display = 'none';
  _resetIdeaSteps();
  document.getElementById('ai-idea-log').innerHTML = '';
  _log('ai-idea-log', '✨ Bắt đầu pipeline Idea→Video...', 'info');
  _log('ai-idea-log', `Ý tưởng: "${idea.substring(0,80)}..."`, 'info');

  try {
    const r = await fetch('/api/ai/idea2video/start', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        idea,
        user_requirement: document.getElementById('ai-idea-req').value.trim(),
        style: document.getElementById('ai-idea-style').value,
      })
    });
    const d = await r.json();
    if (!d.ok) { _setStatus('ai-idea-status','error','❌ '+d.error); _log('ai-idea-log','❌ '+d.error,'error'); document.getElementById('btn-ai-idea').disabled=false; return; }
    _ideaJobId = d.job_id;
    _log('ai-idea-log', '✅ Job: '+d.job_id+' — pipeline đang chạy...', 'success');
    _ideaPoll = setInterval(_pollIdea, 3000);
  } catch(e) {
    _setStatus('ai-idea-status','error','❌ Lỗi kết nối');
    _log('ai-idea-log', '❌ '+e.message, 'error');
    document.getElementById('btn-ai-idea').disabled = false;
  }
};

function _pollIdea() {
  if (!_ideaJobId) return;
  fetch('/api/ai/idea2video/status/'+_ideaJobId).then(r=>r.json()).then(d => {
    if (!d.ok) return;
    document.getElementById('ai-idea-bar').style.width = (d.progress||0)+'%';
    document.getElementById('ai-idea-pct').textContent = (d.progress||0)+'%';
    document.getElementById('ai-idea-msg').textContent = d.message || 'Đang xử lý...';
    _updateIdeaSteps(d.message || '', d.progress || 0);
    if (d.message) _log('ai-idea-log', d.message, 'info');

    if (d.state === 'done') {
      clearInterval(_ideaPoll); _ideaPoll = null;
      _setStatus('ai-idea-status','done','✅ Hoàn thành');
      document.getElementById('ai-idea-progress').style.display = 'none';
      document.getElementById('ai-idea-result').style.display = '';
      document.getElementById('ai-idea-video').src = '/api/ai/idea2video/download/'+_ideaJobId;
      document.getElementById('btn-ai-idea').disabled = false;
      _log('ai-idea-log', '🎉 Video đã tạo xong!', 'success');
      // Mark all steps done
      document.querySelectorAll('#ai-idea-steps .step-item').forEach(el => {
        el.className = 'step-item done';
        const b = el.querySelector('.badge');
        if (b) { b.textContent = '✅'; b.className = 'badge badge-green'; }
      });
    } else if (d.state === 'error') {
      clearInterval(_ideaPoll); _ideaPoll = null;
      _setStatus('ai-idea-status','error','❌ '+(d.error||d.message||'Lỗi'));
      document.getElementById('btn-ai-idea').disabled = false;
      _log('ai-idea-log', '❌ '+(d.error||d.message), 'error');
      showToast('Pipeline thất bại', 'error');
    }
  }).catch(()=>{});
}

window.aiIdeaDownload = function() {
  if (!_ideaJobId) return;
  const a = document.createElement('a');
  a.href = '/api/ai/idea2video/download/'+_ideaJobId;
  a.download = 'idea2video_'+_ideaJobId+'.mp4';
  a.click();
};

window.aiIdeaReset = function() {
  _ideaJobId = null;
  document.getElementById('ai-idea-result').style.display = 'none';
  document.getElementById('ai-idea-progress').style.display = 'none';
  document.getElementById('ai-idea-log').innerHTML = 'Nhập ý tưởng và nhấn Tạo Video để bắt đầu.';
  _setStatus('ai-idea-status','idle','Sẵn sàng');
  _resetIdeaSteps();
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function _setStatus(id, state, text) {
  const el = document.getElementById(id);
  if (!el) return;
  const map = {idle:'badge-gray', run:'badge-accent', done:'badge-green', error:'badge-red'};
  el.textContent = text;
  el.className = 'badge ' + (map[state]||'badge-gray');
}

function _log(boxId, msg, type) {
  const box = document.getElementById(boxId);
  if (!box) return;
  const ts = new Date().toLocaleTimeString('vi-VN', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const colors = {info:'var(--text2)', success:'var(--success)', error:'var(--error)', warn:'var(--warning)'};
  box.innerHTML += `<div style="color:${colors[type]||colors.info}">[${ts}] ${msg}</div>`;
  box.scrollTop = box.scrollHeight;
}

// ── Prompt mẫu ───────────────────────────────────────────────────────────────
const _V_SAMPLES = [
  "A cinematic aerial shot of a coastal city at golden hour, waves crashing against cliffs, seagulls flying, warm sunlight, slow camera pan, 4K",
  "A cute cartoon cat sitting at a tiny desk typing on a laptop, coffee steaming, cozy room, Studio Ghibli style",
  "Timelapse of a flower blooming, morning dew on petals, soft bokeh, macro lens, natural lighting from dawn to midday",
  "An astronaut floating in space with Earth in background, stars twinkling, slow rotation, cinematic, epic atmosphere",
  "Underwater coral reef with tropical fish, sunlight rays through clear blue water, gentle current, National Geographic quality",
];
const _I_SAMPLES = [
  "A majestic dragon perched on a mountain peak at sunset, fantasy art, detailed scales, glowing eyes, dramatic clouds",
  "A cozy coffee shop interior, rainy day outside, warm lighting, watercolor illustration style, peaceful atmosphere",
  "Portrait of a cyberpunk samurai, neon city background, rain reflections, detailed armor, cinematic lighting",
  "A magical forest with bioluminescent mushrooms, fairy lights, misty atmosphere, fantasy landscape, ultra detailed",
  "Minimalist logo design for a tech startup called 'NovaSpark', clean lines, gradient blue to purple, modern",
];

window.aiVSample = function() {
  document.getElementById('ai-v-prompt').value = _V_SAMPLES[Math.floor(Math.random()*_V_SAMPLES.length)];
  showToast('Đã load prompt mẫu', 'info');
};
window.aiISample = function() {
  document.getElementById('ai-i-prompt').value = _I_SAMPLES[Math.floor(Math.random()*_I_SAMPLES.length)];
  showToast('Đã load prompt mẫu', 'info');
};

// ── Idea pipeline step tracking ──────────────────────────────────────────────
const _STEP_KEYWORDS = {
  story: ['câu chuyện','story','develop'],
  script: ['kịch bản','script'],
  chars: ['nhân vật','character'],
  board: ['storyboard','thiết kế','shot','visual'],
  gen: ['tạo video','generate','gemini','mock','Shot'],
  concat: ['ghép','concat','cuối','final','Hoàn thành'],
};

function _updateIdeaSteps(msg, pct) {
  if (!msg) return;
  const m = msg.toLowerCase();
  const steps = document.querySelectorAll('#ai-idea-steps .step-item');
  const thresholds = [8,15,20,30,85,95];
  const stepKeys = ['story','script','chars','board','gen','concat'];

  let activeKey = null;
  for (const [key, kws] of Object.entries(_STEP_KEYWORDS)) {
    if (kws.some(kw => m.includes(kw))) { activeKey = key; break; }
  }

  steps.forEach((el, i) => {
    const key = stepKeys[i];
    const badge = el.querySelector('.badge');
    if (pct >= thresholds[i] && key !== activeKey) {
      el.className = 'step-item done';
      if (badge) { badge.textContent = '✅'; badge.className = 'badge badge-green'; }
    } else if (key === activeKey) {
      el.className = 'step-item active';
      if (badge) { badge.textContent = '⏳'; badge.className = 'badge badge-accent'; }
    }
  });
}

function _resetIdeaSteps() {
  document.querySelectorAll('#ai-idea-steps .step-item').forEach(el => {
    el.className = 'step-item';
    const badge = el.querySelector('.badge');
    if (badge) { badge.textContent = 'Chờ'; badge.className = 'badge badge-gray'; }
  });
}

// ── Init on page switch ──────────────────────────────────────────────────────
const _origSP = window.switchPage;
window.switchPage = function(page) {
  if (typeof _origSP === 'function') _origSP(page);
  if (page === 'ai_studio') aiLoadConfig();
};

if (typeof window.showToast !== 'function') {
  window.showToast = function(msg, type) { console.log('['+type+'] '+msg); };
}

})();

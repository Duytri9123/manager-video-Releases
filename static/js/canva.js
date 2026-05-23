/* ── canva.js — Canva auto-fill + export via Playwright ─────────────────── */

window._canvaImages = []; // [{ id, name, dataUrl, file }]
window._canvaSession = null;
window._canvaPollTimer = null;

/* ───────── Stick Figure default sample ───────── */
const CANVA_STICK_FIGURE_SAMPLE = {
  bulk: `Cảnh 1 — Buổi sáng
(Stick figure nằm ngủ. Báo thức reo inh ỏi.)
Báo thức: "TING TING TING!!!"
(Nhân vật tắt báo thức… rồi ngủ tiếp.)
5 phút sau…
Báo thức: "TING TING TING!!!"
(Nhân vật bật dậy hoảng loạn.)
Text hiện màn hình: "Cuộc sống trưởng thành bắt đầu bằng việc chiến đấu với báo thức."

Cảnh 2 — Đi làm / đi học
(Stick figure chạy vội, vừa mang dép vừa ăn bánh mì.)
(Xe bus vừa chạy mất.)
Nhân vật: "Đợi tôi với…"
(Xe chạy luôn.)
Text màn hình: "Đời không chờ ai… xe bus cũng vậy."

Cảnh 3 — Giờ nghỉ trưa
(Mở ví ra chỉ còn vài đồng.)
Nhân vật nhìn menu:
Cơm gà: 45k
Bún bò: 50k
Trà sữa: 60k
(Nhân vật im lặng… rồi mua mì ly.)
Text màn hình: "Người trưởng thành giỏi nhất là… giả vờ ổn."

Cảnh 4 — Buổi chiều
(Ngồi làm việc/học bài trước laptop.)
Màn hình: "Deadline: 2 giờ nữa"
(Nhân vật mở tab YouTube/TikTok.)
5 phút sau → 2 tiếng sau.
Nhân vật: "Ơ?"

Cảnh 5 — Buổi tối
(Stick figure đi bộ về nhà một mình.)
(Trời mưa nhẹ.)
(Nhân vật đứng nhìn thành phố.)
Voice over nhẹ nhàng: "Có những ngày mệt thật đấy… nhưng chỉ cần còn cố gắng… thì mình vẫn đang đi đúng hướng."

Cảnh cuối
(Nhân vật về tới nhà.)
(Con mèo nhỏ chạy ra đón / hoặc chiếc giường hiện ra.)
Nhân vật cười nhẹ.
Text kết: "Ngày mai… lại tiếp tục nhé."`,
  voiceover:
`Cuộc sống trưởng thành… là những buổi sáng chiến đấu với báo thức… những lần chạy vội ngoài đường… và những bữa ăn chọn theo số tiền còn lại trong ví.

Có những ngày tưởng mình rất ổn… nhưng chỉ một câu nói nhỏ… cũng đủ làm mình mệt.

Deadline vẫn tới. Áp lực vẫn còn. Và đôi khi… ta chỉ muốn nằm im một chút thôi.

Nhưng rồi sau tất cả… mình vẫn tiếp tục thức dậy, tiếp tục cố gắng, tiếp tục bước đi.

Vì cuộc sống không cần bạn hoàn hảo. Chỉ cần bạn chưa bỏ cuộc.

Nếu hôm nay bạn đã rất mệt… thì nghỉ một chút cũng được.

Ngày mai… mình lại bắt đầu tiếp nhé.`,
  caption: '#stickfigure #animation #cuocsong #dailylife #shorts #tiktokvn #healing #story #viralvideo',
};

/* ───────── Init when page first opened ───────── */
function canvaInit() {
  if (window._canvaInited) return;
  window._canvaInited = true;
  if (!document.querySelectorAll('#cv-scenes .scene-row').length) {
    canvaLoadStickFigureSample();
  }
}

/* ───────── Sample loader ───────── */
function canvaLoadStickFigureSample() {
  const bulkEl = document.getElementById('cv-bulk-text');
  const voEl = document.getElementById('cv-voiceover');
  const capEl = document.getElementById('cv-caption');
  if (bulkEl) bulkEl.value = CANVA_STICK_FIGURE_SAMPLE.bulk;
  if (voEl)   voEl.value   = CANVA_STICK_FIGURE_SAMPLE.voiceover;
  if (capEl)  capEl.value  = CANVA_STICK_FIGURE_SAMPLE.caption;
  canvaParseFromBigText();
  if (typeof toast === 'function') toast('🎭 Đã nạp kịch bản Stick Figure mẫu', 'success');
}

/* ───────── Scene helpers ───────── */
/* Default keywords for the Stick Figure sample (matches scene order).
 * Combined with the search prefix in the UI (default "stickman"), each scene
 * searches Canva Elements as e.g. "stickman alarm", "stickman run". English
 * keywords match Canva's element library best. */
const CANVA_STICK_FIGURE_KEYWORDS = [
  'alarm',
  'run',
  'eat',
  'laptop',
  'walk rain',
  'sleep',
];

/* Available element categories on Canva. The values must EXACTLY match the
 * Vietnamese labels rendered on the category cards (Canva VN). */
const CANVA_CATEGORIES = [
  'Đồ họa',
  'Hiệu ứng động',
  'Video',
  'Ảnh',
  'Âm thanh',
  'Khung',
  'Hình dạng',
  '3D',
  'Lưới',
  'Mockup',
  'Biểu đồ',
  'Biểu mẫu',
  'Bảng',
  'Sheets',
];

/** Heuristic: pick the most fitting Canva category from a keyword/text. */
function _guessCategory(keyword, text) {
  // Prioritize KEYWORD over the loose scene text — scene text often contains
  // misleading words like "2 tiếng sau" (= "2 hours later") which would otherwise
  // pull the category to "Âm thanh" (Sounds).
  const kw = (keyword || '').toLowerCase();
  // Strict keyword-only patterns first
  if (/\b(nhạc|music|sound effect|sfx)\b/.test(kw)) return 'Âm thanh';
  if (/\b(video|footage|clip|reel)\b/.test(kw)) return 'Video';
  if (/\b(photo|chụp ảnh|chân dung)\b/.test(kw)) return 'Ảnh';
  if (/\b(khung|frame|border)\b/.test(kw)) return 'Khung';
  if (/\b(shape|hình tròn|hình vuông|đường|line)\b/.test(kw)) return 'Hình dạng';
  if (/\b(chart|biểu đồ|graph)\b/.test(kw)) return 'Biểu đồ';
  if (/\b(table|bảng dữ liệu)\b/.test(kw)) return 'Bảng';
  // Anything else = graphic / illustration
  return 'Đồ họa';
}

function canvaParseFromBigText() {
  const txt = (document.getElementById('cv-bulk-text')?.value || '').trim();
  if (!txt) return;
  // Split on blank lines
  let blocks = txt.split(/\n\s*\n+/).map(b => b.trim()).filter(Boolean);
  // If we have less than 2 blocks, also try splitting by "Cảnh N" headings
  if (blocks.length < 2) {
    const lines = txt.split(/\n/);
    const grouped = [];
    let cur = [];
    for (const line of lines) {
      if (/^\s*Cảnh\s+(?:\d+|cuối)/i.test(line) && cur.length) {
        grouped.push(cur.join('\n').trim());
        cur = [];
      }
      cur.push(line);
    }
    if (cur.length) grouped.push(cur.join('\n').trim());
    if (grouped.length > blocks.length) blocks = grouped.filter(Boolean);
  }
  // Render scene rows
  const wrap = document.getElementById('cv-scenes');
  if (!wrap) return;
  wrap.innerHTML = '';
  blocks.forEach((b, i) => {
    const kw = CANVA_STICK_FIGURE_KEYWORDS[i] || _guessKeywordFromText(b);
    canvaAddScene(b, kw);
  });
}

function _guessKeywordFromText(text) {
  const lower = (text || '').toLowerCase();
  // Map VN script content → short EN keywords that pair well with a prefix
  // like "stickman" / "chibi" in Canva Elements search.
  const map = [
    ['báo thức', 'alarm'],
    ['ngủ',      'sleep'],
    ['chạy',     'run'],
    ['xe bus',   'bus'],
    ['ăn',       'eat'],
    ['laptop',   'laptop'],
    ['deadline', 'work'],
    ['mưa',      'rain'],
    ['về nhà',   'home'],
    ['mèo',      'cat'],
    ['giường',   'bed'],
    ['vui',      'happy'],
    ['buồn',     'sad'],
    ['mệt',      'tired'],
  ];
  for (const [kw, out] of map) if (lower.includes(kw)) return out;
  return '';
}

function canvaAddScene(initial = '', keyword = '', category = '') {
  const wrap = document.getElementById('cv-scenes');
  if (!wrap) return;
  const idx = wrap.querySelectorAll('.scene-row').length + 1;
  const row = document.createElement('div');
  row.className = 'scene-row';
  const cat = category || _guessCategory(keyword, initial);
  const catOptions = CANVA_CATEGORIES.map(c =>
    `<option value="${c}"${c === cat ? ' selected' : ''}>${c}</option>`).join('');
  row.innerHTML = `
    <div class="scene-idx">#${idx}</div>
    <textarea class="cv-scene-text" rows="3" placeholder="Lời thoại / text cho cảnh ${idx}..."></textarea>
    <input class="scene-keyword" type="text" placeholder="Từ khoá (vd: eat, run, sleep)">
    <select class="scene-category" title="Danh mục Canva để search">${catOptions}</select>
    <div class="scene-pick empty" title="Click để chọn hình từ thư viện" onclick="canvaOpenLibPicker(this)">
      <span>📚<br>Chọn<br>thư viện</span>
    </div>
    <div style="display:flex;flex-direction:column;gap:4px">
      <button class="btn btn-secondary btn-sm" type="button" title="Copy lời thoại vào clipboard của Chromium → Ctrl+V vào Canva" onclick="canvaPushSceneClipboard(this)">📋</button>
      <button class="btn btn-secondary btn-sm" type="button" onclick="canvaMoveScene(this,-1)">▲</button>
      <button class="btn btn-secondary btn-sm" type="button" onclick="canvaMoveScene(this,1)">▼</button>
      <button class="btn btn-danger btn-sm" type="button" onclick="canvaRemoveScene(this)">✕</button>
    </div>
  `;
  row.querySelector('textarea').value = initial || '';
  row.querySelector('.scene-keyword').value = keyword || '';
  wrap.appendChild(row);
  canvaRenumberScenes();
}

function canvaRemoveScene(btn) {
  const row = btn.closest('.scene-row');
  if (row) row.remove();
  canvaRenumberScenes();
}

function canvaMoveScene(btn, dir) {
  const row = btn.closest('.scene-row');
  if (!row) return;
  if (dir < 0 && row.previousElementSibling) {
    row.parentNode.insertBefore(row, row.previousElementSibling);
  } else if (dir > 0 && row.nextElementSibling) {
    row.parentNode.insertBefore(row.nextElementSibling, row);
  }
  canvaRenumberScenes();
}

function canvaRenumberScenes() {
  document.querySelectorAll('#cv-scenes .scene-row').forEach((r, i) => {
    const idx = r.querySelector('.scene-idx');
    if (idx) idx.textContent = `#${i + 1}`;
    const ta = r.querySelector('textarea');
    if (ta) ta.placeholder = `Nội dung paste vào ô text trang ${i + 1}...`;
  });
}

function canvaGetScenes() {
  return Array.from(document.querySelectorAll('#cv-scenes .scene-row'))
    .map(r => ({
      text: (r.querySelector('textarea')?.value || '').trim(),
      keyword: (r.querySelector('.scene-keyword')?.value || '').trim(),
      category: (r.querySelector('.scene-category')?.value || '').trim(),
      library_image: r.querySelector('.scene-pick')?.dataset?.libRel || '',
    }))
    .filter(s => s.text.length || s.keyword.length || s.library_image);
}

/* ───────── Image helpers ───────── */
function canvaOnImageInput(ev) {
  const files = Array.from(ev.target.files || []);
  files.forEach(f => {
    const reader = new FileReader();
    reader.onload = e => {
      const id = 'img-' + Math.random().toString(36).slice(2, 8);
      window._canvaImages.push({ id, name: f.name, dataUrl: e.target.result, file: f });
      canvaRenderImageList();
    };
    reader.readAsDataURL(f);
  });
  ev.target.value = '';
}

function canvaRemoveImage(id) {
  window._canvaImages = window._canvaImages.filter(i => i.id !== id);
  canvaRenderImageList();
}

function canvaClearImages() {
  window._canvaImages = [];
  canvaRenderImageList();
}

function canvaRenderImageList() {
  const wrap = document.getElementById('cv-img-list');
  const empty = document.getElementById('cv-img-empty');
  if (!wrap) return;
  wrap.innerHTML = '';
  if (!window._canvaImages.length) {
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';
  window._canvaImages.forEach(img => {
    const tile = document.createElement('div');
    tile.className = 'img-tile';
    if (img.isAudio) {
      tile.innerHTML = `
        <div class="img-thumb" style="display:flex;align-items:center;justify-content:center;
             flex-direction:column;font-size:11px;text-align:center;padding:4px;
             background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;font-weight:600">
          <div style="font-size:24px">🎙</div>
          <div>${img.name.replace(/voiceover_/, '').replace(/\.mp3$/, '').slice(0, 14)}</div>
        </div>
        <button class="del" onclick="canvaRemoveImage('${img.id}')" title="Xoá">✕</button>
      `;
    } else {
      tile.innerHTML = `
        <img class="img-thumb" src="${img.dataUrl}" alt="${img.name}" title="${img.name}">
        <button class="del" onclick="canvaRemoveImage('${img.id}')" title="Xoá">✕</button>
      `;
    }
    wrap.appendChild(tile);
  });
}

/* ───────── Login state ───────── */
async function canvaCheckLogin() {
  _canvaSetLoginBadge('waiting', 'Đang kiểm tra...');
  try {
    const r = await fetch('/api/canva/check_login');
    const d = await r.json();
    if (d.ok && d.logged_in) {
      _canvaSetLoginBadge('done', 'Đã có session');
    } else {
      _canvaSetLoginBadge('idle', 'Chưa login');
    }
  } catch (e) {
    _canvaSetLoginBadge('error', 'Lỗi: ' + e);
  }
}

async function canvaOpenLogin() {
  if (!confirm('Mở cửa sổ Chromium để bạn login Canva.\nSau khi login xong, bấm nút "Kiểm tra login" rồi đóng cửa sổ này.')) return;
  try {
    const r = await fetch('/api/canva/open_login', { method: 'POST' });
    const d = await r.json();
    if (!d.ok) {
      if (typeof toast === 'function') toast('Lỗi: ' + (d.error || 'unknown'), 'error');
      return;
    }
    if (typeof toast === 'function') toast('🌐 Đã mở Canva — đăng nhập trong cửa sổ vừa hiện.', 'info');
    // Auto-poll login state every 5s for 5 minutes
    const start = Date.now();
    const tick = async () => {
      if (Date.now() - start > 5 * 60 * 1000) return;
      const rr = await fetch('/api/canva/check_login');
      const dd = await rr.json().catch(() => ({}));
      if (dd && dd.logged_in) {
        _canvaSetLoginBadge('done', 'Đã có session');
        return;
      }
      setTimeout(tick, 5000);
    };
    setTimeout(tick, 5000);
  } catch (e) {
    if (typeof toast === 'function') toast('Lỗi: ' + e, 'error');
  }
}

async function canvaProfileReset() {
  if (!confirm('Xoá profile Canva? Lần sau sẽ phải đăng nhập lại.')) return;
  try {
    const r = await fetch('/api/canva/profile_reset', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      _canvaSetLoginBadge('idle', 'Chưa login');
      if (typeof toast === 'function') toast('🔄 Đã reset profile', 'success');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('Lỗi: ' + e, 'error');
  }
}

function _canvaSetLoginBadge(kind, text) {
  const el = document.getElementById('canva-login-state');
  if (!el) return;
  const cls = {
    idle:    ['status-idle',    'dot-gray'],
    run:     ['status-run',     'dot-blue'],
    waiting: ['status-waiting', 'dot-yellow'],
    done:    ['status-done',    'dot-green'],
    error:   ['status-error',   'dot-red'],
  }[kind] || ['status-idle', 'dot-gray'];
  el.className = 'canva-status ' + cls[0];
  el.innerHTML = `<span class="dot ${cls[1]}"></span> ${text}`;
}

function _canvaSetRunBadge(kind, text) {
  const el = document.getElementById('cv-run-status');
  if (!el) return;
  const cls = {
    idle:    ['status-idle',    'dot-gray'],
    run:     ['status-run',     'dot-blue'],
    waiting: ['status-waiting', 'dot-yellow'],
    done:    ['status-done',    'dot-green'],
    error:   ['status-error',   'dot-red'],
  }[kind] || ['status-idle', 'dot-gray'];
  el.className = 'canva-status ' + cls[0];
  el.innerHTML = `<span class="dot ${cls[1]}"></span> ${text}`;
}

/* ───────── Log helpers ───────── */
function _canvaAppendLog(msg, level) {
  const box = document.getElementById('cv-log');
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'log-' + (level || 'info');
  const ts = new Date().toTimeString().slice(0, 8);
  div.textContent = `[${ts}] ${msg}`;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function _canvaSetProgress(pct, label) {
  const bar = document.getElementById('cv-progress-bar');
  const pctEl = document.getElementById('cv-progress-pct');
  const lblEl = document.getElementById('cv-progress-label');
  if (bar)   bar.style.width = (pct || 0) + '%';
  if (pctEl) pctEl.textContent = (pct || 0) + '%';
  if (lblEl) lblEl.textContent = label || '';
}

/* ───────── Run pipeline ───────── */
async function canvaRun() {
  const templateUrl = (document.getElementById('cv-template-url')?.value || '').trim();
  const voiceover = (document.getElementById('cv-voiceover')?.value || '').trim();
  const script = (document.getElementById('cv-bulk-text')?.value || '').trim();
  const exportMp4 = !!document.getElementById('cv-export-mp4')?.checked;
  const aspect = (document.getElementById('cv-aspect')?.value || '16:9');
  const searchPrefix = (document.getElementById('cv-search-prefix')?.value || '').trim();

  // Auto-run AI Storyboard if not done yet
  if (!window._canvaPlan || !window._canvaPlan.length) {
    if (script || voiceover) {
      // Generate voiceover MP3 FIRST so we have accurate duration for planning
      if (voiceover) {
        const hasFreshAudio = (window._canvaImages || [])
          .some(i => i.isAudio && (i.name || '').startsWith('voiceover_'));
        if (!hasFreshAudio) {
          _canvaAppendLog('🎙 Tạo MP3 voiceover từ text...', 'info');
          _canvaSetProgress(2, 'Generate giọng đọc');
          try {
            await canvaGenerateVoiceover();
          } catch (e) {
            _canvaAppendLog('⚠ Lỗi TTS: ' + e + ' — tiếp tục không có voiceover.', 'warning');
          }
        }
      }
      _canvaAppendLog('🧠 Chưa có storyboard — tự chạy AI Storyboard...', 'info');
      await canvaPlanScenes();
    }
  }

  // Convert plan to scenes (each component = 1 scene)
  const plan = window._canvaPlan || [];
  const scenes = plan.length
    ? plan.map(c => ({
        text: '',                    // text comes from voiceover MP3, not per-scene
        keyword: c.keyword || '',
        category: c.category || 'Đồ họa',
        x: c.x, y: c.y,
        start_s: c.start_s, end_s: c.end_s,
        animation: c.animation || 'Hiện lên',
        note: c.note || '',
      }))
    : [];

  if (!scenes.length && !voiceover) {
    if (typeof toast === 'function') toast('Chưa có kịch bản hoặc voiceover', 'warning');
    return;
  }

  document.getElementById('cv-btn-run')?.classList.add('hidden');
  document.getElementById('cv-btn-stop')?.classList.remove('hidden');

  const box = document.getElementById('cv-log');
  if (box) box.innerHTML = '';
  _canvaSetProgress(0, 'Đang khởi tạo...');
  _canvaSetRunBadge('run', 'Đang chạy');

  // Step 0: auto-generate voiceover MP3 if user typed text + no MP3 exists yet
  if (voiceover) {
    const hasFreshAudio = (window._canvaImages || [])
      .some(i => i.isAudio && (i.name || '').startsWith('voiceover_'));
    if (!hasFreshAudio) {
      _canvaAppendLog('🎙 Tạo MP3 voiceover từ text...', 'info');
      _canvaSetProgress(2, 'Generate giọng đọc');
      try {
        await canvaGenerateVoiceover();
      } catch (e) {
        _canvaAppendLog('⚠ Lỗi TTS: ' + e + ' — tiếp tục không có voiceover.', 'warning');
      }
    }
  }

  // Step 1: upload all assets (voiceover MP3 etc.)
  const imagePaths = [];
  if ((window._canvaImages || []).length) {
    _canvaAppendLog(`📤 Upload ${window._canvaImages.length} file lên server...`, 'info');
    for (const img of window._canvaImages) {
      try {
        const fd = new FormData();
        fd.append('image', img.file, img.name);
        const r = await fetch('/api/canva/upload_image', { method: 'POST', body: fd });
        const d = await r.json();
        if (d.ok && d.path) {
          imagePaths.push(d.path);
          _canvaAppendLog(`  ✓ ${img.name}`, 'success');
        } else {
          _canvaAppendLog(`  ✗ ${img.name}: ${d.error || 'lỗi'}`, 'warning');
        }
      } catch (e) {
        _canvaAppendLog(`  ✗ ${img.name}: ${e}`, 'error');
      }
    }
  }

  // Step 2: prepare session
  try {
    const r = await fetch('/api/canva/prepare_design', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        template_url: templateUrl,
        scenes,
        voiceover,
        caption: '',
        image_paths: imagePaths,
        export_mp4: exportMp4,
        set_animation: false,
        animation: '',
        aspect,
        search_prefix: searchPrefix,
        scene_duration: 5,
        add_elements: true,
      })
    });
    const d = await r.json();
    if (!d.ok) {
      _canvaAppendLog('❌ ' + (d.error || 'Không khởi tạo được phiên'), 'error');
      _canvaSetRunBadge('error', 'Lỗi khởi tạo');
      _canvaResetButtons();
      return;
    }
    window._canvaSession = d.session_id;
    _canvaAppendLog('🚀 Phiên Playwright bắt đầu (' + d.session_id + ')', 'info');
    _canvaPollStatus();
  } catch (e) {
    _canvaAppendLog('❌ Lỗi: ' + e, 'error');
    _canvaSetRunBadge('error', 'Lỗi mạng');
    _canvaResetButtons();
  }
}

function _canvaPollStatus() {
  if (window._canvaPollTimer) clearTimeout(window._canvaPollTimer);
  const sid = window._canvaSession;
  if (!sid) return;
  let lastIdx = 0;
  const tick = async () => {
    try {
      const r = await fetch('/api/canva/prepare_status?session_id=' + encodeURIComponent(sid));
      const d = await r.json();
      if (!d.ok) {
        _canvaAppendLog('⚠ Mất phiên: ' + (d.error || ''), 'warning');
        _canvaSetRunBadge('error', 'Mất phiên');
        _canvaResetButtons();
        return;
      }
      // Append new log entries
      const log = d.log || [];
      for (let i = lastIdx; i < log.length; i++) {
        const l = log[i];
        _canvaAppendLog(l.msg, l.level || 'info');
      }
      lastIdx = log.length;

      // Update progress
      if (typeof d.progress === 'number') _canvaSetProgress(d.progress, d.progress_label || d.status);

      // Map status to badge
      const s = d.status || '';
      if (s === 'launching' || s === 'opening_template' || s === 'filling' ||
          s === 'uploading_images' || s === 'exporting') {
        _canvaSetRunBadge('run', 'Đang chạy: ' + s);
      } else if (s === 'waiting_login' || s === 'waiting_login_gate') {
        _canvaSetRunBadge('waiting', 'Chờ đăng nhập');
      } else if (s === 'done') {
        _canvaSetRunBadge('done', 'Hoàn thành');
      } else if (s === 'error') {
        _canvaSetRunBadge('error', 'Lỗi: ' + (d.error || ''));
      }

      if (d.done) {
        _canvaSetProgress(100, d.status === 'error' ? 'Lỗi' : 'Hoàn tất — cửa sổ vẫn mở');
        _canvaResetButtons();
        // Keep session id around so "📋 copy scene" still works while
        // the Chromium window is open. We will clear it when the user
        // explicitly clicks Stop (canvaStop sets _canvaSession=null elsewhere).
        // Show a "Stop" button still since browser is alive
        document.getElementById('cv-btn-stop')?.classList.remove('hidden');
        document.getElementById('cv-btn-run')?.classList.remove('hidden');
        return;
      }
    } catch (e) {
      _canvaAppendLog('⚠ ' + e, 'warning');
    }
    window._canvaPollTimer = setTimeout(tick, 1500);
  };
  tick();
}

async function canvaStop() {
  if (!window._canvaSession) {
    _canvaResetButtons();
    return;
  }
  try {
    await fetch('/api/canva/prepare_close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: window._canvaSession })
    });
    _canvaAppendLog('⏹ Đã yêu cầu đóng phiên', 'info');
  } catch (e) {
    _canvaAppendLog('⚠ ' + e, 'warning');
  }
  window._canvaSession = null;
}

/* Push a single scene's text to the open Chromium's clipboard so the user can
 * Ctrl+V into Canva. Useful when auto-fill misses (e.g. text inside iframe).
 */
async function canvaPushSceneClipboard(btn) {
  const row = btn?.closest('.scene-row');
  const ta = row?.querySelector('textarea');
  const text = (ta?.value || '').trim();
  if (!text) {
    if (typeof toast === 'function') toast('Cảnh đang trống', 'warning');
    return;
  }
  if (!window._canvaSession) {
    if (typeof toast === 'function') toast('Chưa có phiên Canva đang chạy. Bấm "Bắt đầu tự động" trước.', 'warning');
    return;
  }
  try {
    const r = await fetch('/api/canva/copy_scene', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: window._canvaSession, text })
    });
    const d = await r.json();
    if (d.ok) {
      if (typeof toast === 'function') toast('📋 Đã đẩy vào clipboard. Click ô text Canva → Ctrl+V', 'success');
    } else {
      if (typeof toast === 'function') toast('Lỗi: ' + (d.error || ''), 'error');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('Lỗi: ' + e, 'error');
  }
}

function _canvaResetButtons() {
  document.getElementById('cv-btn-run')?.classList.remove('hidden');
  document.getElementById('cv-btn-stop')?.classList.add('hidden');
}

// Hook page switch
document.addEventListener('DOMContentLoaded', () => {
  // If user lands directly on canva tab via URL, init
  if (location.hash === '#canva' || (window.location.pathname || '').includes('canva')) {
    setTimeout(canvaInit, 100);
  }
});


/* ─────────────────────────────────────────────────────────────────────────
 * Library: pre-scrape creator portfolio → cache PNGs locally → pick per scene
 * ────────────────────────────────────────────────────────────────────────── */

window._canvaLibItems = [];          // last loaded list
window._canvaLibBuildSession = null; // current scrape session id
window._canvaLibPollTimer = null;
window._canvaActivePickerEl = null;  // .scene-pick element being assigned

function _canvaLibCreator() {
  return (document.getElementById('cv-lib-creator')?.value || 'zdeneksasek').trim();
}

async function canvaLibLoad() {
  const creator = _canvaLibCreator();
  if (!creator) return;
  try {
    const r = await fetch('/api/canva/library/list?creator=' + encodeURIComponent(creator));
    const d = await r.json();
    if (!d.ok) {
      _canvaLibStatus('⚠ ' + (d.error || ''));
      return;
    }
    window._canvaLibItems = d.items || [];
    _canvaLibRenderGrid();
    _canvaLibStatus(`Đã tải ${d.count} hình từ cache.`);
    document.getElementById('cv-lib-count').textContent = d.count + ' hình';
  } catch (e) {
    _canvaLibStatus('⚠ ' + e);
  }
}

async function canvaLibBuild() {
  const creator = _canvaLibCreator();
  const kind = (document.getElementById('cv-lib-kind')?.value || 'graphics');
  const max_items = parseInt(document.getElementById('cv-lib-max')?.value || '200', 10);
  if (!creator) {
    if (typeof toast === 'function') toast('Nhập tên creator trước', 'warning');
    return;
  }
  if (!confirm(`Sẽ mở Chromium, vào https://www.canva.com/p/${creator}\n` +
               `Lọc "${kind}", scroll cuối, và tải tối đa ${max_items} thumbnails.\n` +
               `Có thể mất 1-3 phút. Tiếp tục?`)) return;

  document.getElementById('cv-lib-progress')?.classList.remove('hidden');
  _canvaLibSetProgress(0, 'Khởi tạo...');
  _canvaLibStatus('Đang chạy...');

  try {
    const r = await fetch('/api/canva/library/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creator, kind, max_items }),
    });
    const d = await r.json();
    if (!d.ok) {
      _canvaLibStatus('❌ ' + (d.error || 'Lỗi'));
      return;
    }
    window._canvaLibBuildSession = d.session_id;
    _canvaLibPollBuild();
  } catch (e) {
    _canvaLibStatus('❌ ' + e);
  }
}

function _canvaLibPollBuild() {
  if (window._canvaLibPollTimer) clearTimeout(window._canvaLibPollTimer);
  const sid = window._canvaLibBuildSession;
  if (!sid) return;
  let lastIdx = 0;
  const tick = async () => {
    try {
      const r = await fetch('/api/canva/library/status?session_id=' + encodeURIComponent(sid));
      const d = await r.json();
      if (!d.ok) {
        _canvaLibStatus('⚠ Mất phiên: ' + (d.error || ''));
        return;
      }
      const log = d.log || [];
      for (let i = lastIdx; i < log.length; i++) {
        const l = log[i];
        // Show last log line as status
        _canvaLibStatus(l.msg);
      }
      lastIdx = log.length;
      if (typeof d.progress === 'number') {
        _canvaLibSetProgress(d.progress, d.progress_label || d.status);
      }
      if (d.done) {
        document.getElementById('cv-lib-progress')?.classList.add('hidden');
        if (d.status === 'done') {
          if (typeof toast === 'function') toast(`✅ Đã tải ${d.items_count} hình về thư viện`, 'success');
          await canvaLibLoad();
        } else if (d.error) {
          if (typeof toast === 'function') toast('❌ ' + d.error, 'error');
        }
        window._canvaLibBuildSession = null;
        return;
      }
    } catch (e) {
      _canvaLibStatus('⚠ ' + e);
    }
    window._canvaLibPollTimer = setTimeout(tick, 1500);
  };
  tick();
}

async function canvaLibClear() {
  const creator = _canvaLibCreator();
  if (!confirm(`Xoá thư viện local của @${creator}?`)) return;
  try {
    const r = await fetch('/api/canva/library/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creator }),
    });
    const d = await r.json();
    if (d.ok) {
      window._canvaLibItems = [];
      _canvaLibRenderGrid();
      document.getElementById('cv-lib-count').textContent = '0 hình';
      _canvaLibStatus('Đã xoá thư viện.');
    }
  } catch (e) {
    _canvaLibStatus('⚠ ' + e);
  }
}

function _canvaLibStatus(text) {
  const el = document.getElementById('cv-lib-status');
  if (el) el.textContent = text || '';
}

function _canvaLibSetProgress(pct, label) {
  const bar = document.getElementById('cv-lib-progress-bar');
  const pctEl = document.getElementById('cv-lib-progress-pct');
  const lblEl = document.getElementById('cv-lib-progress-label');
  if (bar)   bar.style.width = (pct || 0) + '%';
  if (pctEl) pctEl.textContent = (pct || 0) + '%';
  if (lblEl) lblEl.textContent = label || '';
}

function _canvaLibRenderGrid() {
  const grid = document.getElementById('cv-lib-grid');
  if (!grid) return;
  const items = window._canvaLibItems || [];
  if (!items.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      Chưa có hình nào. Bấm "Build / cập nhật thư viện".
    </div>`;
    return;
  }
  grid.innerHTML = items.map(it => {
    const url = '/api/canva/library/image?creator=' +
                encodeURIComponent(_canvaLibCreator()) +
                '&name=' + encodeURIComponent((it.file || '').split(/[\\/]/).pop());
    return `<div class="lib-tile" title="${(it.alt || it.name || '').replace(/"/g, '&quot;')}"
                 data-rel="${it.rel}" onclick="canvaLibTileClick(this)">
              <img src="${url}" loading="lazy" alt="">
            </div>`;
  }).join('');
  document.getElementById('cv-lib-count').textContent = items.length + ' hình';
}

/**
 * Open the picker for a scene row. Tile click then assigns the chosen library
 * image to the row.
 */
function canvaOpenLibPicker(pickEl) {
  if (!window._canvaLibItems.length) {
    if (typeof toast === 'function') toast('Thư viện trống — bấm "Build" trước', 'warning');
    return;
  }
  window._canvaActivePickerEl = pickEl;
  // Scroll the library card into view + visually flag tiles
  const grid = document.getElementById('cv-lib-grid');
  grid?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  // Highlight currently-assigned tile (if any)
  document.querySelectorAll('#cv-lib-grid .lib-tile.selected').forEach(t => t.classList.remove('selected'));
  const cur = pickEl.dataset.libRel || '';
  if (cur) {
    const sel = document.querySelector(`#cv-lib-grid .lib-tile[data-rel="${CSS.escape(cur)}"]`);
    if (sel) sel.classList.add('selected');
  }
  if (typeof toast === 'function') toast('Click 1 hình trong thư viện để gán cho cảnh này', 'info');
}

function canvaLibTileClick(tile) {
  const rel = tile.dataset.rel;
  const pick = window._canvaActivePickerEl;
  if (!pick) {
    // No active picker — just toggle visual selection for browsing
    document.querySelectorAll('#cv-lib-grid .lib-tile.selected').forEach(t => t.classList.remove('selected'));
    tile.classList.add('selected');
    return;
  }
  // Assign to scene
  const url = tile.querySelector('img')?.src || '';
  pick.dataset.libRel = rel;
  pick.classList.remove('empty');
  pick.innerHTML = `<img src="${url}" alt="">`;
  pick.title = 'Click để đổi hình';
  // Add a tiny clear button on hover
  pick.addEventListener('contextmenu', _canvaPickContextClear, { once: false });
  if (typeof toast === 'function') toast('✅ Đã gán hình cho cảnh', 'success');
  window._canvaActivePickerEl = null;
  document.querySelectorAll('#cv-lib-grid .lib-tile.selected').forEach(t => t.classList.remove('selected'));
  tile.classList.add('selected');
}

function _canvaPickContextClear(ev) {
  ev.preventDefault();
  const pick = ev.currentTarget;
  pick.dataset.libRel = '';
  pick.classList.add('empty');
  pick.innerHTML = '<span>📚<br>Chọn<br>thư viện</span>';
  pick.title = 'Click để chọn hình từ thư viện';
}

/* Auto-load library on first canva tab open */
const _canvaInitOriginal = window.canvaInit || canvaInit;
window.canvaInit = function () {
  try { _canvaInitOriginal(); } catch (e) {}
  // Defer the library list fetch a tick so the network call doesn't block UI
  setTimeout(() => { canvaLibLoad().catch(() => {}); }, 50);
};

/* ─────────────────────────────────────────────────────────────────────────
 * Voiceover MP3 generation — calls /api/tts_preview, then injects the
 * resulting blob as a "fake file" into the upload list so the regular
 * Canva upload flow picks it up.
 * ────────────────────────────────────────────────────────────────────────── */

function _canvaTtsParams() {
  return {
    text: (document.getElementById('cv-voiceover')?.value || '').trim(),
    tts_engine: (document.getElementById('cv-tts-engine')?.value || 'edge-tts'),
    tts_voice: (document.getElementById('cv-tts-voice')?.value || 'vi-VN-HoaiMyNeural'),
    tts_rate: (document.getElementById('cv-tts-rate')?.value || '+0%'),
    tts_pitch: '+0Hz',
    tts_emotion: 'default',
  };
}

/* Voice options per TTS engine */
const _CANVA_TTS_VOICES = {
  'edge-tts': [
    {value: 'vi-VN-HoaiMyNeural', label: 'HoaiMy (nữ)'},
    {value: 'vi-VN-NamMinhNeural', label: 'NamMinh (nam)'},
  ],
  'gtts': [
    {value: 'vi', label: 'Tiếng Việt'},
  ],
  'fpt-ai': [
    {value: 'banmai', label: 'Ban Mai (nữ)'},
    {value: 'leminh', label: 'Lê Minh (nam)'},
    {value: 'thuminh', label: 'Thu Minh (nữ)'},
    {value: 'giahuy', label: 'Gia Huy (nam)'},
    {value: 'myan', label: 'Mỹ An (nữ)'},
    {value: 'lannhi', label: 'Lan Nhi (nữ)'},
  ],
};

/** When user changes TTS engine, update the voice dropdown to match */
function canvaOnTtsEngineChange() {
  const engine = document.getElementById('cv-tts-engine')?.value || 'edge-tts';
  const voiceSel = document.getElementById('cv-tts-voice');
  if (!voiceSel) return;

  const voices = _CANVA_TTS_VOICES[engine] || _CANVA_TTS_VOICES['edge-tts'];
  voiceSel.innerHTML = voices.map(v =>
    `<option value="${v.value}">${v.label}</option>`
  ).join('');

  // Clear cached voiceover since engine changed
  _canvaClearCachedVoiceover();
}

/** When user changes voice, clear cached voiceover to force regeneration */
function canvaOnTtsVoiceChange() {
  _canvaClearCachedVoiceover();
}

/** Remove any previously generated voiceover MP3 from the upload list */
function _canvaClearCachedVoiceover() {
  const before = (window._canvaImages || []).length;
  window._canvaImages = (window._canvaImages || []).filter(
    i => !(i.isAudio && (i.name || '').startsWith('voiceover_'))
  );
  window._canvaVoiceoverDurationS = 0;
  if (window._canvaImages.length !== before) {
    canvaRenderImageList();
    // Also clear the plan since duration may change
    window._canvaPlan = null;
    const card = document.getElementById('cv-plan-card');
    if (card) card.style.display = 'none';
    if (typeof toast === 'function') toast('🔄 Đã xóa voiceover cũ — sẽ tạo lại khi chạy', 'info');
  }
  // Hide audio player
  const audio = document.getElementById('cv-tts-audio');
  if (audio) { audio.src = ''; audio.style.display = 'none'; }
  _canvaTtsStatus('');
}

function _canvaTtsStatus(text, kind = 'info') {
  const el = document.getElementById('cv-tts-status');
  if (!el) return;
  el.textContent = text || '';
  el.style.color = kind === 'error' ? 'var(--error)'
                  : kind === 'success' ? 'var(--success)'
                  : 'var(--text-muted)';
}

async function _canvaFetchTts() {
  const params = _canvaTtsParams();
  if (!params.text) {
    if (typeof toast === 'function') toast('Voiceover trống', 'warning');
    return null;
  }
  _canvaTtsStatus('Đang generate giọng đọc...');
  const r = await fetch('/api/tts_preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!r.ok) {
    const errJson = await r.json().catch(() => ({}));
    const msg = errJson.error || `HTTP ${r.status}`;
    _canvaTtsStatus('❌ ' + msg, 'error');
    if (typeof toast === 'function') toast('TTS lỗi: ' + msg, 'error');
    return null;
  }
  const blob = await r.blob();
  if (!blob || blob.size === 0) {
    _canvaTtsStatus('❌ MP3 rỗng', 'error');
    return null;
  }
  return blob;
}

/** Listen to the voiceover without uploading. */
async function canvaPreviewVoiceover() {
  const blob = await _canvaFetchTts();
  if (!blob) return;
  const url = URL.createObjectURL(blob);
  const audio = document.getElementById('cv-tts-audio');
  if (audio) {
    audio.src = url;
    audio.style.display = '';
    audio.play().catch(() => {});
  }
  _canvaTtsStatus(`▶ Preview ${(blob.size / 1024).toFixed(0)} KB — sẵn sàng`, 'success');
}

/** Generate MP3 + add it to the upload list as a real File. */
async function canvaGenerateVoiceover() {
  const blob = await _canvaFetchTts();
  if (!blob) return;

  // Wrap the blob in a File so the existing upload flow treats it like
  // anything else picked through "Thêm ảnh".
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  const fname = `voiceover_${ts}.mp3`;
  const file = new File([blob], fname, { type: 'audio/mpeg' });

  // Measure duration by loading the blob into an <audio>
  let durationS = 0;
  try {
    durationS = await _canvaMeasureAudioDuration(blob);
  } catch (e) {
    console.warn('measure duration failed', e);
  }
  window._canvaVoiceoverDurationS = durationS;

  // Read it as data URL so we can show a tiny audio waveform tile.
  const dataUrl = await new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result);
    reader.readAsDataURL(file);
  });

  // Drop any previous voiceover entries (only keep the latest)
  window._canvaImages = (window._canvaImages || []).filter(
    i => !(i.name || '').startsWith('voiceover_')
  );
  const id = 'aud-' + Math.random().toString(36).slice(2, 8);
  window._canvaImages.push({ id, name: fname, dataUrl, file, isAudio: true, durationS });
  canvaRenderImageList();

  // Also expose in the small audio player
  const audio = document.getElementById('cv-tts-audio');
  if (audio) {
    audio.src = URL.createObjectURL(blob);
    audio.style.display = '';
  }
  const durStr = durationS ? ` · ${durationS.toFixed(1)}s` : '';
  _canvaTtsStatus(`✅ ${fname} (${(blob.size / 1024).toFixed(0)} KB${durStr})`, 'success');
  if (typeof toast === 'function')
    toast(`🎙 MP3 ${durationS.toFixed(1)}s đã thêm vào upload`, 'success');
}

/** Read MP3 blob duration by loading into an Audio element. */
function _canvaMeasureAudioDuration(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio();
    audio.preload = 'metadata';
    audio.src = url;
    audio.addEventListener('loadedmetadata', () => {
      const d = audio.duration;
      URL.revokeObjectURL(url);
      resolve(isFinite(d) ? d : 0);
    }, { once: true });
    audio.addEventListener('error', e => {
      URL.revokeObjectURL(url);
      reject(e);
    }, { once: true });
    setTimeout(() => reject(new Error('timeout')), 5000);
  });
}


/* ─────────────────────────────────────────────────────────────────────────
 * AI Storyboard Planner — calls /api/canva/plan_scenes to generate
 * components with timing, position, animation from voiceover text.
 * ────────────────────────────────────────────────────────────────────────── */

window._canvaPlan = null; // last generated plan (array of components)

async function canvaPlanScenes() {
  // AI reads the SCRIPT (bulk text) to generate components.
  // Voiceover is used only for timing reference (total duration).
  const script = (document.getElementById('cv-bulk-text')?.value || '').trim();
  const voiceover = (document.getElementById('cv-voiceover')?.value || '').trim();
  if (!script && !voiceover) {
    if (typeof toast === 'function') toast('Nhập kịch bản hoặc voiceover trước', 'warning');
    return;
  }
  const style = (document.getElementById('cv-search-prefix')?.value || 'stickman').trim();
  _canvaTtsStatus('🧠 Đang phân tích kịch bản...');

  try {
    const r = await fetch('/api/canva/plan_scenes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script: script,
        voiceover: voiceover,
        style,
        duration_s: window._canvaVoiceoverDurationS || 0,
      }),
    });
    const d = await r.json();
    if (!d.ok) {
      _canvaTtsStatus('❌ ' + (d.error || 'Lỗi'), 'error');
      return;
    }
    window._canvaPlan = d.components || [];
    _canvaTtsStatus(`✅ ${d.components.length} components (${d.method})`, 'success');

    // Render plan table
    const card = document.getElementById('cv-plan-card');
    const summary = document.getElementById('cv-plan-summary');
    const table = document.getElementById('cv-plan-table');
    if (card) card.style.display = '';
    if (summary) {
      summary.textContent = `${d.components.length} components · ${d.total_duration_s?.toFixed(1)}s · ${d.method}`;
    }
    if (table) {
      table.innerHTML = `<table class="plan-table">
        <thead><tr>
          <th>#</th><th>Keyword</th><th>Start</th><th>End</th><th>X</th><th>Y</th><th>Animation</th><th>Note</th>
        </tr></thead>
        <tbody>
        ${d.components.map((c, i) => `<tr>
          <td>${i+1}</td>
          <td><b>${c.keyword || ''}</b></td>
          <td>${c.start_s}s</td>
          <td>${c.end_s}s</td>
          <td>${c.x}</td>
          <td>${c.y}</td>
          <td>${c.animation || ''}</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(c.note||'').replace(/"/g,'&quot;')}">${c.note || ''}</td>
        </tr>`).join('')}
        </tbody>
      </table>`;
    }

    // Scroll plan into view
    card?.scrollIntoView({behavior: 'smooth', block: 'start'});

    if (typeof toast === 'function')
      toast(`🧠 Storyboard: ${d.components.length} components, ${d.total_duration_s?.toFixed(1)}s`, 'success');
  } catch (e) {
    _canvaTtsStatus('❌ ' + e, 'error');
  }
}

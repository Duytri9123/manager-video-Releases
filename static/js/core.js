/* ══════════════════════════════════════════════════════════════
   core.js — Unified core module
   Merges: utils.js, api.js, socket.js, i18n.js, theme.js,
           and core navigation from app.js
   ══════════════════════════════════════════════════════════════ */

/* ── Theme toggle ────────────────────────────────────────────── */
(function initTheme() {
  const saved = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  if (saved === 'dark' || (!saved && prefersDark)) {
    document.documentElement.classList.add('dark');
  }
  _updateThemeIcon();
})();

function _updateThemeIcon() {
  const icon = document.getElementById('theme-icon');
  if (icon) icon.textContent = document.documentElement.classList.contains('dark') ? '☀️' : '🌙';
}

function toggleTheme() {
  document.documentElement.classList.toggle('dark');
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  _updateThemeIcon();
}

/* ── Utility helpers (from utils.js) ─────────────────────────── */
function toast(msg, type = 'info', dur = 3500) {
  const c = document.getElementById('toasts'); if (!c) return;
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = '<span>' + msg + '</span>';
  c.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0'; el.style.transform = 'translateX(20px)';
    el.style.transition = '.2s'; setTimeout(() => el.remove(), 200);
  }, dur);
}

function appendLog(id, msg, level) {
  const box = document.getElementById(id); if (!box) return;
  const line = document.createElement('div');
  line.className = 'log-' + (level || 'info');
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  line.textContent = `[${ts}] ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function clearLog(id) { const el = document.getElementById(id); if (el) el.innerHTML = ''; }

function setProgress(pbId, lblId, pct, label) {
  const pb = document.getElementById(pbId);
  const lb = document.getElementById(lblId);
  if (pb) pb.style.width = pct + '%';
  if (lb) lb.textContent = label || '';
  const pctEl = document.getElementById(pbId + '-pct');
  if (pctEl) pctEl.textContent = Math.round(pct) + '%';
}

function fmtNum(n) {
  if (!n) return '0';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return '' + n;
}

function fmtDur(ms) {
  if (!ms) return '';
  const s = ms > 1000 ? Math.round(ms / 1000) : ms;
  if (s <= 0) return '';
  const m = Math.floor(s / 60), sec = s % 60;
  return m > 0 ? m + ':' + String(sec).padStart(2, '0') : '0:' + String(sec).padStart(2, '0');
}

function escHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _getTtsApiProvider(engine) {
  if (!engine) return '';
  if (engine === 'fpt-ai') return 'fpt';
  if (engine === 'elevenlabs') return 'elevenlabs';
  if (engine === 'fish-audio') return 'fish-audio';
  if (engine === '9router') return '9router';
  return '';
}

/* ── Tab Switching Helpers ────────────────────────────────────── */
function switchSubTab(el, tabId, itemClass, pageClass) {
  if (!el || !tabId) return;
  const target = document.getElementById(tabId);
  if (!target) return;
  document.querySelectorAll('.' + itemClass).forEach(m => m.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.' + pageClass).forEach(p => p.classList.remove('active'));
  target.classList.add('active');
}

function switchProcTab(el, id) { switchSubTab(el, id, 'proc-menu-item', 'proc-subpage'); }

/* ── Loading overlay (from api.js) ───────────────────────────── */
// Stub — overlay disabled by default
const LoadingUI = { start() {}, stop() {}, forceHide() {} };

/* ── API wrapper (from api.js) ───────────────────────────────── */
const API = {
  async _parseResponse(r) {
    const contentType = (r.headers.get('Content-Type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
      const raw = await r.text();
      const preview = (raw || '').replace(/\s+/g, ' ').trim().slice(0, 180);
      throw new Error(`Server trả về dữ liệu không phải JSON (HTTP ${r.status}). ${preview || 'Vui lòng kiểm tra log backend.'}`);
    }
    let data;
    try { data = await r.json(); }
    catch (_err) { throw new Error(`Không thể đọc JSON từ server (HTTP ${r.status}).`); }
    if (!r.ok) {
      const msg = data?.error || data?.message || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return data;
  },
  async get(url, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try { const r = await fetch(url); return await API._parseResponse(r); }
    finally { if (!silent) LoadingUI.stop(); }
  },
  async post(url, data, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try {
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      return await API._parseResponse(r);
    } finally { if (!silent) LoadingUI.stop(); }
  },
  async postRaw(url, data, opts) {
    const silent = !!(opts && opts.silent);
    if (!silent) LoadingUI.start();
    try {
      return await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    } finally { if (!silent) LoadingUI.stop(); }
  }
};

/* ── Socket.IO setup (from socket.js) ────────────────────────── */
let socket = null;
try { socket = io(); }
catch(e) {
  console.warn('Socket.IO not available:', e.message);
  socket = { on: () => {}, emit: () => {}, connected: false };
}

function _clampPct(v) { return Math.max(0, Math.min(100, Number(v) || 0)); }

socket.on('log', d => {
  appendLog('proc-log', d.msg, d.level || 'info');
  if (d && d.file_path) {
    window._publishLastOutputPath = d.file_path;
    window._ytLastOutputPath = d.file_path;
  }
});

socket.on('progress', d => {
  if (d.type === 'overall' || d.type === 'step' || d.type === 'item' || d.type === 'post') {
    const pct = _clampPct(d.pct);
    const label = d.label || '';
    if (typeof _setProcProgress === 'function') {
      _setProcProgress(pct, label);
    } else {
      setProgress('pb-proc-overall', 'lbl-proc-overall', pct, label);
    }
    const targetUrl = d.url || _downloadingUrl;
    if (targetUrl && typeof setQueueItemProgress === 'function') {
      setQueueItemProgress(targetUrl, d.pct, label);
    }
  }
});

socket.on('downloading_url', d => {
  _downloadingUrl = d.url || null;
  if (_downloadingUrl && typeof markQueueItemState === 'function') {
    markQueueItemState(_downloadingUrl, 'running');
  }
  renderQueue();
  const cnt = document.getElementById('queue-count');
  if (cnt && d.total) cnt.textContent = _queue.length + ' (' + d.index + '/' + d.total + ')';
});

socket.on('queue_item_state', d => {
  const url = d?.url || '';
  if (!url || typeof markQueueItemState !== 'function') return;
  markQueueItemState(url, d.state || '');
});

socket.on('queue_update', data => {
  _queue = data || [];
  renderQueue();
  if (typeof onQueueStateChanged === 'function') onQueueStateChanged();
});

socket.on('done', d => {
  const btn = document.getElementById('btn-dl');
  if (btn) { btn.disabled = false; btn.textContent = 'Chạy hàng chờ'; }
  if (typeof _setProcProgress === 'function') {
    _setProcProgress(d.ok ? 100 : 0, d.ok ? 'Hoàn tất hàng chờ' : 'Hàng chờ lỗi');
  }
  _dlRunning = false;
  _downloadingUrl = null;
  renderQueue();
  if (typeof onQueueStateChanged === 'function') onQueueStateChanged();
  toast(d.ok ? t('toast_dl_done') : t('toast_dl_error'), d.ok ? 'success' : 'error');
});

/* ── i18n (from i18n.js) ─────────────────────────────────────── */
const I18N = {
  vi: {
    nav_user: 'Tìm người dùng', nav_download: 'Tải xuống', nav_config: 'Cấu hình',
    nav_cookies: 'Cookies', nav_transcribe: 'Phiên âm', nav_history: 'Lịch sử',
    nav_process: 'Xử lý Video',
    proc_tab_main: 'Chuẩn bị & Xử lý',
    proc_tab_vertical: 'Chuyển Video Dọc',
    proc_tab_publish: 'Đăng tải & Hàng chờ',
    proc_tab_log: 'Nhật ký & Tiến trình',
    cfg_tab_general: 'Chung',
    cfg_tab_process: 'Xử lý Video',
    cfg_tab_afp: 'Bảo mật & AFP',
    cfg_tab_integration: 'Dịch & Đăng tải',
    title_user: 'Tìm người dùng', title_download: 'Tải xuống',
    title_config: 'Cấu hình', title_cookies: 'Cookies',
    title_transcribe: 'Phiên âm', title_history: 'Lịch sử',
    title_process: 'Xử lý Video',
    search_placeholder: 'https://www.douyin.com/user/MS4wLjABAAAA...',
    btn_search: 'Tìm kiếm', lbl_vi_toggle: 'Tiếng Việt',
    lbl_posts: 'Bài đăng', lbl_followers: 'Người theo dõi', lbl_following: 'Đang theo dõi',
    lbl_loading_user: 'Đang tải dữ liệu người dùng...',
    lbl_videos: 'Video', lbl_type: 'Loại', lbl_sort: 'Sắp xếp',
    lbl_search_title: 'Tìm tiêu đề', lbl_filter_all: 'Tất cả',
    lbl_filter_video: 'Video', lbl_filter_gallery: 'Ảnh',
    lbl_sort_newest: 'Mới nhất', lbl_sort_oldest: 'Cũ nhất',
    lbl_sort_play: 'Xem nhiều nhất', lbl_sort_like: 'Thích nhiều nhất',
    btn_select_all: 'Chọn tất cả', btn_clear_sel: 'Bỏ chọn',
    lbl_selected: 'đã chọn', btn_add_queue: 'Thêm vào hàng chờ',
    btn_prev: 'Trước', btn_next: 'Tiếp',
    lbl_jump_page: 'Đi tới trang', btn_go_page: 'Đi',
    lbl_page: 'Trang', lbl_of: '/',
    lbl_translate_provider: 'Tạo phụ đề bằng', lbl_retranslate: 'Dịch lại',
    lbl_transcribe_provider: 'Phiên âm bằng',
    lbl_subtitle_opts: 'Phụ đề & dịch',
    lbl_process_settings: 'Cài đặt xử lý video',
    lbl_output_files: 'File đầu ra',
    lbl_model_settings: 'Mô hình xử lý',
    lbl_process_mode_ai: 'Xử lý AI',
    lbl_process_mode_model: 'Xử lý mô hình',
    lbl_import_file: 'Import file',
    btn_import_file: 'Import',
    btn_process_video: 'Xử lý Video',
    lbl_queue: 'Hàng chờ', btn_clear_queue: 'Xóa hàng chờ',
    placeholder_manual_url: 'Dán URL video...',
    btn_add: 'Thêm', btn_start_dl: 'Bắt đầu tải',
    lbl_dl_download: 'Tải',
    lbl_progress: 'Tiến trình', lbl_overall: 'Tổng thể',
    lbl_step: 'Bước', lbl_items: 'Mục', lbl_post_processing: 'Hậu xử lý', lbl_log: 'Nhật ký',
    btn_clear_log: 'Xóa', lbl_queue_empty: 'Hàng chờ trống',
    lbl_dl_control: 'Điều khiển tải xuống',
    lbl_dl_toggle_process: 'Xử lý video',
    lbl_dl_toggle_subtitle: 'Chèn phụ đề',
    lbl_dl_toggle_voice: 'Tạo giọng nói',
    lbl_dl_post_process: 'Xử lý video, chèn phụ đề, tạo giọng nói',
    lbl_dl_burn_vi: 'Chèn phụ đề tiếng Việt lên video',
    lbl_dl_voice_vi: 'Giọng nói tiếng Việt',
    lbl_queue_failed: 'Lỗi',
    lbl_queue_item_progress: 'Tiến trình mục',
    lbl_queue_downloading: 'Đang tải...',
    lbl_queue_next: 'Tiếp theo',
    ttl_remove_queue_item: 'Xóa',
    ttl_queue_item_locked: 'Đang tải',
    toast_url_exists: 'URL đã tồn tại trong hàng đợi',
    lbl_dl_settings: 'Cài đặt tải xuống',
    lbl_urls: 'Danh sách URL (mỗi dòng một URL)',
    lbl_save_path: 'Thư mục lưu', lbl_proxy: 'Proxy',
    lbl_threads: 'Luồng', lbl_retries: 'Thử lại',
    lbl_start_date: 'Ngày bắt đầu', lbl_end_date: 'Ngày kết thúc',
    lbl_dl_modes: 'Chế độ tải', lbl_max_items: 'Số lượng tối đa (0 = không giới hạn)',
    lbl_options: 'Tùy chọn', lbl_translation: 'Dịch thuật',
    lbl_preferred_provider: 'Dịch phụ đề bằng',
    lbl_groq_api_key: 'Groq API Key cho phiên âm video',
    lbl_groq_model: 'Mô hình Groq Whisper',
    btn_save_config: 'Lưu cấu hình', btn_reload: 'Tải lại',
    lbl_music: 'Nhạc', lbl_cover: 'Ảnh bìa', lbl_json: 'JSON', lbl_folder: 'Thư mục',
    lbl_cookie_mode: 'Chế độ Cookie',
    lbl_use_custom: 'Dùng Cookie tùy chỉnh',
    lbl_cookie_default: 'Mặc định', lbl_cookie_custom: 'Tùy chỉnh',
    lbl_cookie_default_desc: 'Đang dùng cookie mặc định (tự động dự phòng)',
    lbl_cookie_custom_desc: 'Đang dùng cookie tùy chỉnh từ cấu hình',
    lbl_parse_browser: 'Phân tích từ trình duyệt',
    lbl_paste_cookie: 'Dán chuỗi cookie từ DevTools trình duyệt',
    btn_parse: 'Phân tích', btn_auto_fetch: 'Tự động lấy',
    lbl_cookie_fields: 'Các trường Cookie',
    lbl_not_validated: 'Chưa xác thực',
    btn_save: 'Lưu', btn_validate: 'Xác thực',
    lbl_tr_settings: 'Cài đặt phiên âm',
    lbl_video_folder: 'Thư mục video',
    lbl_video_file: 'File video',
    lbl_video_url: 'URL video (tải và xử lý)',
    lbl_single_file: 'File đơn (tùy chọn)',
    lbl_output_dir: 'Thư mục xuất (tùy chọn)',
    lbl_model: 'Mô hình Whisper', lbl_language: 'Ngôn ngữ',
    lbl_export_srt: 'Xuất SRT', lbl_skip_existing: 'Bỏ qua đã có',
    lbl_simplified: 'Chữ giản thể',
    btn_start_tr: 'Bắt đầu phiên âm',
    lbl_history: 'Lịch sử tải xuống',
    btn_refresh: 'Làm mới', btn_clear_history: 'Xóa lịch sử',
    th_time: 'Thời gian', th_url: 'URL', th_type: 'Loại',
    th_total: 'Tổng', th_success: 'Thành công',
    lbl_no_history: 'Chưa có lịch sử',
    lbl_vp_title: 'Hậu xử lý video sau khi tải', lbl_enable: 'Bật',
    lbl_voice_convert: 'Đổi giọng tiếng Việt',
    lbl_enable_voice: 'Bật',
    lbl_voice_note: 'Cần: pip install edge-tts (hoặc gtts).',
    lbl_vp_note: 'Cần: pip install openai-whisper edge-tts.',
    lbl_loading: 'Đang tải...',
    lbl_deepseek_api_key: 'DeepSeek API Key',
    lbl_openai_api_key: 'OpenAI API Key',
    lbl_hf_token: 'HuggingFace Token',
    opt_auto_fallback: 'Tự động (Fallback)',
    lbl_burn_subs: 'Chèn phụ đề lên video',
    lbl_blur_original: 'Làm mờ chữ gốc',
    lbl_translate_subs: 'Tạo bản dịch tiếng Việt',
    lbl_burn_vi_subs: 'Chèn phụ đề tiếng Việt lên video',
    lbl_keep_bg: 'Giữ nhạc nền',
    lbl_blur_zone: 'Vùng làm mờ',
    lbl_subtitle_position: 'Vị trí phụ đề',
    opt_blur_bottom: 'Dưới',
    opt_blur_top: 'Trên',
    opt_blur_none: 'Không',
    lbl_tts_engine: 'TTS Engine',
    lbl_tts_voice: 'Giọng đọc',
    lbl_tts_speed: 'Tốc độ giọng',
    lbl_tts_pitch: 'Điều chỉnh cao độ',
    lbl_auto_speed: 'Tự động tốc độ',
    lbl_auto_speed_desc: 'Tự động điều chỉnh theo đoạn',
    lbl_font_size: 'Cỡ chữ phụ đề',
    lbl_font_color: 'Màu chữ',
    lbl_margin_v: 'Khoảng cách đáy (px)',
    lbl_bg_volume: 'Âm lượng nhạc nền (0.0 - 1.0)',
    lbl_blur_height: 'Vùng mờ (%)',
    lbl_source_language: 'Ngôn ngữ gốc',
    opt_lang_zh: 'Tiếng Trung',
    opt_lang_en: 'Tiếng Anh',
    opt_lang_ja: 'Tiếng Nhật',
    opt_lang_ko: 'Tiếng Hàn',
    toast_config_saved: 'Đã lưu cấu hình',
    toast_cookies_saved: 'Đã lưu cookies',
    toast_queue_cleared: 'Đã xóa hàng chờ',
    toast_history_cleared: 'Đã xóa lịch sử',
    toast_added_queue: 'Đã thêm vào hàng chờ',
    toast_tr_done: 'Phiên âm hoàn tất',
    toast_dl_done: 'Tải xuống hoàn tất',
    toast_dl_error: 'Tải xuống có lỗi',
    confirm_clear_queue: 'Xóa tất cả hàng chờ?',
    confirm_clear_history: 'Xóa toàn bộ lịch sử tải xuống?',
    lbl_queue_running: 'Đang chạy...',
    lbl_translating: 'Đang dịch...',
    lbl_provider_badge: 'Provider:',
    lbl_retranslate_confirm: 'Dịch lại toàn bộ với provider mới?',
    badge_done: 'Xong', badge_error: 'Lỗi',
    badge_running: 'Đang chạy', badge_waiting: 'Chờ',
    lbl_tts_rate: 'Tốc độ',
  },
  en: {
    nav_user: 'Search User', nav_download: 'Download', nav_config: 'Config',
    nav_cookies: 'Cookies', nav_transcribe: 'Transcribe', nav_history: 'History',
    nav_process: 'Video Process',
    proc_tab_main: 'Prep & Process',
    proc_tab_vertical: '9:16 Vertical',
    proc_tab_publish: 'Publish & Queue',
    proc_tab_log: 'Logs & Progress',
    cfg_tab_general: 'General',
    cfg_tab_process: 'Processing',
    cfg_tab_afp: 'Anti-Fingerprint',
    cfg_tab_integration: 'Integrations',
    title_user: 'Search User', title_download: 'Download',
    title_config: 'Configuration', title_cookies: 'Cookies',
    title_transcribe: 'Transcribe', title_history: 'History',
    title_process: 'Video Process',
    search_placeholder: 'https://www.douyin.com/user/MS4wLjABAAAA...',
    btn_search: 'Search', lbl_vi_toggle: 'Vietnamese',
    lbl_posts: 'Posts', lbl_followers: 'Followers', lbl_following: 'Following',
    lbl_loading_user: 'Loading user data...',
    lbl_videos: 'Videos', lbl_type: 'Type', lbl_sort: 'Sort',
    lbl_search_title: 'Search title', lbl_filter_all: 'All',
    lbl_filter_video: 'Video', lbl_filter_gallery: 'Gallery',
    lbl_sort_newest: 'Newest', lbl_sort_oldest: 'Oldest',
    lbl_sort_play: 'Most Played', lbl_sort_like: 'Most Liked',
    btn_select_all: 'Select All', btn_clear_sel: 'Clear',
    lbl_selected: 'selected', btn_add_queue: 'Add to Queue',
    btn_prev: 'Prev', btn_next: 'Next',
    lbl_jump_page: 'Go to page', btn_go_page: 'Go',
    lbl_page: 'Page', lbl_of: '/',
    lbl_translate_provider: 'Generate subtitles with', lbl_retranslate: 'Re-translate',
    lbl_transcribe_provider: 'Transcribe with',
    lbl_subtitle_opts: 'Subtitle & translation',
    lbl_process_settings: 'Video processing settings',
    lbl_output_files: 'Output files',
    lbl_model_settings: 'Model settings',
    lbl_process_mode_ai: 'AI processing',
    lbl_process_mode_model: 'Model processing',
    lbl_import_file: 'Import file',
    btn_import_file: 'Import',
    btn_process_video: 'Process Video',
    lbl_queue: 'Queue', btn_clear_queue: 'Clear',
    placeholder_manual_url: 'Paste video URL...',
    btn_add: 'Add', btn_start_dl: 'Start Download',
    lbl_dl_download: 'Download',
    lbl_progress: 'Progress', lbl_overall: 'Overall',
    lbl_step: 'Step', lbl_items: 'Items', lbl_post_processing: 'Post process', lbl_log: 'Log',
    btn_clear_log: 'Clear', lbl_queue_empty: 'Queue is empty',
    lbl_dl_control: 'Download Control',
    lbl_dl_toggle_process: 'Process video',
    lbl_dl_toggle_subtitle: 'Insert subtitles',
    lbl_dl_toggle_voice: 'Create voice',
    lbl_dl_post_process: 'Process video, insert subtitles, create voice',
    lbl_dl_burn_vi: 'Insert Vietnamese subtitles into video',
    lbl_dl_voice_vi: 'Vietnamese voice',
    lbl_queue_failed: 'Failed',
    lbl_queue_item_progress: 'Item progress',
    lbl_queue_downloading: 'Downloading...',
    lbl_queue_next: 'Next',
    ttl_remove_queue_item: 'Remove',
    ttl_queue_item_locked: 'Downloading',
    toast_url_exists: 'URL already exists in queue',
    lbl_dl_settings: 'Download Settings',
    lbl_urls: 'URLs (one per line)',
    lbl_save_path: 'Save Path', lbl_proxy: 'Proxy',
    lbl_threads: 'Threads', lbl_retries: 'Retries',
    lbl_start_date: 'Start Date', lbl_end_date: 'End Date',
    lbl_dl_modes: 'Download Modes', lbl_max_items: 'Max items per mode (0 = unlimited)',
    lbl_options: 'Options', lbl_translation: 'Translation',
    lbl_preferred_provider: 'Generate subtitles with',
    lbl_groq_api_key: 'Groq API key for video transcription',
    lbl_groq_model: 'Groq Whisper model',
    btn_save_config: 'Save Config', btn_reload: 'Reload',
    lbl_music: 'Music', lbl_cover: 'Cover', lbl_json: 'JSON', lbl_folder: 'Folder',
    lbl_cookie_mode: 'Cookie Mode',
    lbl_use_custom: 'Use Custom Cookies',
    lbl_cookie_default: 'Default', lbl_cookie_custom: 'Custom',
    lbl_cookie_default_desc: 'Using built-in default cookies (auto-fallback)',
    lbl_cookie_custom_desc: 'Using your custom cookies from config',
    lbl_parse_browser: 'Parse from Browser',
    lbl_paste_cookie: 'Paste raw cookie string from browser DevTools',
    btn_parse: 'Parse', btn_auto_fetch: 'Auto Fetch',
    lbl_cookie_fields: 'Cookie Fields',
    lbl_not_validated: 'Not validated',
    btn_save: 'Save', btn_validate: 'Validate',
    lbl_tr_settings: 'Transcription Settings',
    lbl_video_folder: 'Video Folder',
    lbl_video_file: 'Video file',
    lbl_video_url: 'Video URL (download and process)',
    lbl_single_file: 'Single File (optional)',
    lbl_output_dir: 'Output Directory (optional)',
    lbl_model: 'Whisper Model', lbl_language: 'Language',
    lbl_export_srt: 'Export SRT', lbl_skip_existing: 'Skip existing',
    lbl_simplified: 'Simplified CN',
    btn_start_tr: 'Start Transcribe',
    lbl_history: 'Download History',
    btn_refresh: 'Refresh', btn_clear_history: 'Clear',
    th_time: 'Time', th_url: 'URL', th_type: 'Type',
    th_total: 'Total', th_success: 'Success',
    lbl_no_history: 'No history yet',
    lbl_vp_title: 'Post-download video processing', lbl_enable: 'Enable',
    lbl_voice_convert: 'Convert to Vietnamese voice',
    lbl_enable_voice: 'Enable',
    lbl_voice_note: 'Requires: pip install edge-tts (or gtts).',
    lbl_vp_note: 'Requires: pip install openai-whisper edge-tts.',
    lbl_loading: 'Loading...',
    lbl_deepseek_api_key: 'DeepSeek API Key',
    lbl_openai_api_key: 'OpenAI API Key',
    lbl_hf_token: 'HuggingFace Token',
    opt_auto_fallback: 'Auto (Fallback)',
    lbl_burn_subs: 'Insert subtitles into video',
    lbl_blur_original: 'Blur original text',
    lbl_translate_subs: 'Create Vietnamese subtitle translation',
    lbl_burn_vi_subs: 'Insert Vietnamese subtitles into video',
    lbl_keep_bg: 'Keep background music',
    lbl_blur_zone: 'Blur zone',
    lbl_subtitle_position: 'Subtitle position',
    opt_blur_bottom: 'Bottom', opt_blur_top: 'Top', opt_blur_none: 'None',
    lbl_tts_engine: 'TTS Engine',
    lbl_tts_voice: 'TTS voice',
    lbl_tts_speed: 'Speech speed',
    lbl_tts_pitch: 'Pitch adjustment',
    lbl_auto_speed: 'Auto speed',
    lbl_auto_speed_desc: 'Auto-fit per segment',
    lbl_font_size: 'Subtitle font size',
    lbl_font_color: 'Font color',
    lbl_margin_v: 'Bottom margin (px)',
    lbl_bg_volume: 'Background volume (0.0 - 1.0)',
    lbl_blur_height: 'Blur region (%)',
    lbl_source_language: 'Source language',
    opt_lang_zh: 'Chinese', opt_lang_en: 'English', opt_lang_ja: 'Japanese', opt_lang_ko: 'Korean',
    toast_config_saved: 'Config saved',
    toast_cookies_saved: 'Cookies saved',
    toast_queue_cleared: 'Queue cleared',
    toast_history_cleared: 'History cleared',
    toast_added_queue: 'Added to queue',
    toast_tr_done: 'Transcription done',
    toast_dl_done: 'Download complete',
    toast_dl_error: 'Download finished with errors',
    confirm_clear_queue: 'Clear all queue items?',
    confirm_clear_history: 'Clear all download history?',
    lbl_queue_running: 'Running...',
    lbl_translating: 'Translating...',
    lbl_provider_badge: 'Provider:',
    lbl_retranslate_confirm: 'Re-translate all with new provider?',
    badge_done: 'Done', badge_error: 'Error',
    badge_running: 'Running', badge_waiting: 'Waiting',
    lbl_tts_rate: 'Rate',
  }
};

let _lang = localStorage.getItem('ui_lang') || 'vi';
function t(key) { return (I18N[_lang] || I18N.vi)[key] || key; }

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const attr = el.getAttribute('data-i18n-attr');
    if (attr) el.setAttribute(attr, t(key));
    else el.textContent = t(key);
  });
  const active = document.querySelector('.nav-item.active');
  if (active) {
    const page = active.getAttribute('data-page');
    const el = document.getElementById('topbar-title');
    if (el && page) el.textContent = t('title_' + page);
  }
  const btn = document.getElementById('btn-lang');
  if (btn) btn.textContent = _lang === 'vi' ? 'EN' : 'VI';
}

function toggleLang() {
  _lang = _lang === 'vi' ? 'en' : 'vi';
  localStorage.setItem('ui_lang', _lang);
  applyI18n();
}

/* ── Core navigation (from app.js) ───────────────────────────── */
function switchPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item,.mobile-nav-item').forEach(n => n.classList.remove('active'));
  const page = document.getElementById('page-' + name);
  const navs = document.querySelectorAll('[data-page="' + name + '"]');
  if (page) page.classList.add('active');
  navs.forEach(n => n.classList.add('active'));
  const el = document.getElementById('topbar-title');
  const titles = {
    user:'Tìm người dùng', process:'Xử lý Video', transcribe:'Phiên âm', subtitle:'Phụ đề & Khung',
    publish:'Đăng video', content:'Quản lý bài đăng', history:'Lịch sử', config:'Cấu hình', cookies:'Cookies',
    movie:'Review phim', story:'Truyện → Video', proxies:'Proxy & Router', chat:'Chat Bot · 9Router',
    videogen:'Video AI', ai_studio:'AI Studio', n8n:'Điều phối n8n', sales:'Video bán hàng', ads:'Video quảng cáo'
  };
  if (el) el.textContent = titles[name] || t('title_' + name) || name;
  if (name === 'config' && !window._configLoaded) {
    loadConfig();
    loadCookieMode();
    loadCookieFields();
    window._configLoaded = true;
  }
  if (name === 'history') { loadHistory(); if (typeof loadFiles === 'function') loadFiles(''); }
  if (name === 'content') cptSwitch('files');
  if (name === 'publish') {
    if (typeof window._pubQueueRefresh === 'function') window._pubQueueRefresh();
  }
  if (name === 'process') {
    if (typeof window._procQueueRefresh === 'function') window._procQueueRefresh();
    loadQueue();
    requestAnimationFrame(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
        _refreshTtsEngineSelects();
        _onTargetLangChange();
      } else {
        _loadTtsEngineCatalog().then(() => {
          _refreshTtsEngineSelects();
          _onTargetLangChange();
        });
      }
    });
  }
  if (name === 'transcribe') {
    requestAnimationFrame(() => {
      if (TTS_ENGINE_CATALOG && TTS_ENGINE_CATALOG.length) {
        _refreshTtsEngineSelects();
        _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
        renderTranscribeVoiceLibrary();
      } else {
        _loadTtsEngineCatalog().then(() => {
          _refreshTtsEngineSelects();
          _syncVoiceOptions('tr-tts-engine', 'tr-tts-voice');
          renderTranscribeVoiceLibrary();
        });
      }
    });
  }
  if (name === 'proxies') { if (typeof proxyLoadList === 'function') proxyLoadList(); if (typeof routerLoadList === 'function') routerLoadList(); }
  if (name === 'chat' && typeof chatInit === 'function') chatInit();
  if (name === 'videogen' && typeof vgInit === 'function') vgInit();
  if (name === 'n8n' && typeof n8nInit === 'function') n8nInit();
  if (name === 'sales' && typeof salesInit === 'function') salesInit();
  if (name === 'ads' && typeof adsInit === 'function') adsInit();
}

/* ── Content platform sub-tabs ───────────────────────────────── */
const _CPT_PANELS = ['files', 'facebook', 'youtube', 'tiktok'];

function cptSwitch(tab) {
  _CPT_PANELS.forEach(p => {
    const btn   = document.getElementById('cpt-tab-' + p);
    const panel = document.getElementById('cpt-panel-' + p);
    if (btn)   btn.classList.toggle('active', p === tab);
    if (panel) panel.style.display = (p === tab) ? 'block' : 'none';
  });
  if (tab === 'files')    { if (typeof loadContentList === 'function') loadContentList(); }
  if (tab === 'facebook') { if (typeof fbMgrInit === 'function') fbMgrInit(); }
  if (tab === 'youtube')  { if (typeof ytMgrInit === 'function') ytMgrInit(); }
}

/* ── Sidebar toggle ──────────────────────────────────────────── */
function toggleSidebar() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.classList.toggle('collapsed');
  const btn = document.getElementById('sidebar-toggle-btn');
  if (btn) btn.textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}

/* ── Mobile menu ─────────────────────────────────────────────── */
function toggleMobileMenu() {
  const existing = document.getElementById('mobile-menu-overlay');
  if (existing) { existing.remove(); return; }
  const ov = document.createElement('div');
  ov.id = 'mobile-menu-overlay';
  ov.className = 'fixed inset-0 bg-black/40 dark:bg-black/60 z-[300] flex items-start';
  const pages = [
    ['user','🔍','Tìm người dùng'],['process','🎬','Xử lý Video'],
    ['transcribe','🎙','Phiên âm'],['publish','📤','Đăng video'],
    ['content','📋','Quản lý nội dung'],
    ['chat','🤖','Chat Bot'],
    ['config','⚙️','Cấu hình']
  ];
  ov.innerHTML = `<div class="bg-white dark:bg-slate-800 w-60 h-full p-5 shadow-2xl overflow-y-auto">
    <div class="font-bold text-base mb-4 pb-3 border-b border-slate-200 dark:border-slate-700">📱 Menu</div>
    ${pages.map(([p,i,l]) => `<div onclick="switchPage('${p}');document.getElementById('mobile-menu-overlay')?.remove()" class="flex items-center gap-2.5 p-3 rounded-lg cursor-pointer text-slate-500 dark:text-slate-400 font-medium mb-1 hover:bg-blue-50 dark:hover:bg-slate-700 transition-colors">${i} ${l}</div>`).join('')}
  </div>`;
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
  document.body.appendChild(ov);
}

/* ── Card collapse toggle ────────────────────────────────────── */
function toggleCard(header) {
  const card = header.closest('.card-collapsible');
  if (card) card.classList.toggle('collapsed');
}

/* ── Sidebar collapsed CSS support ───────────────────────────── */
const _sidebarStyle = document.createElement('style');
_sidebarStyle.textContent = `
  #sidebar.collapsed { width: 60px; min-width: 60px; }
  #sidebar.collapsed .nav-label,
  #sidebar.collapsed #sidebar-logo-text,
  #sidebar.collapsed .text-\\[10px\\] { display: none; }
`;
document.head.appendChild(_sidebarStyle);

/* ── Version check (stub — defined in app.js originally) ─────── */
function checkForUpdate() {
  const versionEl = document.getElementById('sidebar-version-text');
  fetch('/api/version', { method: 'GET' })
    .then(r => r.json())
    .then(data => {
      if (versionEl && data.version) versionEl.textContent = 'v' + data.version;
    })
    .catch(() => {});
}

// Auto-load version on init
document.addEventListener('DOMContentLoaded', () => { checkForUpdate(); });

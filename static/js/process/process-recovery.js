function procAssReviewSkipAlways() {
    window._procSkipReviewSession = true;
    toast('Đã bỏ qua — các video tiếp theo trong lần chạy này sẽ không hỏi nữa', 'info');
    procAssReviewContinue();
  }
  async function procAssReviewContinue() {
    // Save edited content back to server
    const content = document.getElementById('proc-ass-review-content')?.value;
    const path    = window._procAssPath;
    if (typeof content === 'string' && path) {
      try {
        const res = await fetch('/api/proc_save_ass', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, content })
        });
        const rd = await res.json().catch(() => ({}));
        if (!res.ok || rd.ok === false) {
          toast('Lưu ASS thất bại, chưa tiếp tục xử lý để tránh dùng file cũ', 'error');
          return;
        }
        window._publishLastSubtitlePath = path;
      } catch (_) {
        toast('Lưu ASS thất bại, chưa tiếp tục xử lý để tránh dùng file cũ', 'error');
        return;
      }
    }
    // Hide review panel
    const card = document.getElementById('proc-ass-review-card');
    if (card) card.style.display = 'none';

    // ── Auto-publish hook: let AI read ASS and fill publish form ──
    if (typeof pPubOnAssConfirmed === 'function') {
      // Fire-and-forget — don't block pipeline resume
      pPubOnAssConfirmed(path, content).catch(() => {});
    }

    window._step3Confirmed = true;
    procWizGo(4);
    _procDoResume();
  }
  async function _procDoResume() {
    if (window._procReviewResolve) {
      window._procReviewResolve('continue');
      window._procReviewResolve = null;
    }
    try {
      await fetch('/api/proc_resume', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'continue' })
      });
    } catch (_) {}
  }
  async function procThumbPickContinue() { await _procDoResume(); }
  async function procThumbPickSkip() { await _procDoResume(); }
  function _showTtsFailModal(data) {
    _hideTtsFailModal();
    const missing = Array.isArray(data?.missing_segments) ? data.missing_segments : [];
    const modal = document.createElement('div');
    modal.id = 'proc-tts-fail-modal';
    modal.style.cssText = 'position:fixed;inset:0;z-index:12000;background:rgba(15,23,42,.58);display:flex;align-items:center;justify-content:center;padding:20px';
    const rows = missing.slice(0, 12).map(seg => {
      const start = Number(seg.start || 0).toFixed(2);
      const end = Number(seg.end || 0).toFixed(2);
      const text = String(seg.text || '').replace(/[&<>"']/g, ch => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
      })[ch]);
      return `<div style="padding:7px 9px;border-bottom:1px solid var(--border);font-size:12px">
        <b>#${Number(seg.index) + 1}</b> · ${start}s → ${end}s<br>
        <span style="color:var(--text-muted)">${text}</span>
      </div>`;
    }).join('');
    modal.innerHTML = `
      <div style="width:min(680px,96vw);max-height:86vh;background:var(--surface,#fff);border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.28);overflow:hidden">
        <div style="padding:15px 18px;background:#fff7ed;border-bottom:1px solid #fed7aa;display:flex;align-items:center;gap:10px">
          <div style="font-size:18px">⚠</div>
          <div style="flex:1">
            <div style="font-weight:800;color:#9a3412">TTS chưa đọc đủ đoạn</div>
            <div style="font-size:12px;color:#c2410c">Đã tạo ${data.success_count || 0}/${data.total_count || 0}, còn thiếu ${missing.length} đoạn.</div>
          </div>
        </div>
        <div style="padding:14px 18px">
          <div class="alert-info" style="font-size:12px;margin-bottom:10px">
            Burn phụ đề có thể đã hoàn tất ở nhánh song song. Video chưa được ghép giọng cuối cho tới khi bạn xử lý các đoạn thiếu.
          </div>
          <div style="max-height:300px;overflow:auto;border:1px solid var(--border);border-radius:8px">${rows || 'Không có chi tiết đoạn lỗi.'}</div>
          ${missing.length > 12 ? `<div style="font-size:11px;color:var(--text-muted);margin-top:6px">Và ${missing.length - 12} đoạn khác.</div>` : ''}
          <div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:14px">
            <button class="btn btn-secondary" onclick="procTtsFailCancel()">Bỏ lồng tiếng</button>
            <button class="btn btn-secondary" onclick="procTtsFailContinue()">Tiếp tục dù thiếu</button>
            <button class="btn btn-primary" onclick="procTtsFailRetry()">🔄 Thử lại đoạn thiếu</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(modal);
  }
  window._showTtsFailModal = _showTtsFailModal;
  function procTogglePause() {
    const btn = document.getElementById('btn-proc-pause');
    if (!window._procPaused) {
      window._procPaused = true;
      if (btn) { btn.textContent = '▶ Tiếp tục'; btn.style.background = 'var(--success)'; btn.style.color = '#fff'; btn.style.borderColor = 'var(--success)'; }
      toast('⏸ Đã dừng — bấm Tiếp tục để tiếp tục', 'info');
      // Signal server to pause
      fetch('/api/proc_resume', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'pause' })
      }).catch(() => {});
    } else {
      window._procPaused = false;
      if (btn) { btn.textContent = '⏸ Dừng'; btn.style.background = ''; btn.style.color = ''; btn.style.borderColor = ''; }
      toast('▶ Tiếp tục xử lý', 'info');
      fetch('/api/proc_resume', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'resume' })
      }).catch(() => {});
    }
  }


if (typeof procAssReviewSkipAlways !== "undefined") window.procAssReviewSkipAlways = procAssReviewSkipAlways;


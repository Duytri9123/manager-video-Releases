/* ─────────────────────────────────────────────────────────────────────────
 * Floating Chat Widget — bong bóng AI nổi trên viewport.
 * Tái dùng các endpoint /api/chatbot/* (status / models / chat_stream / chat)
 * giống tab "Chat Bot · 9Router". Không phụ thuộc chat.js — có thể tồn tại
 * song song. Trạng thái mở/đóng + size + history nhẹ lưu trong localStorage.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  'use strict';
  if (window._chatWidgetInited) return;
  window._chatWidgetInited = true;

  const LS_KEY      = 'chatWidget.v1';            // legacy single-session (migrated)
  const LS_SESSIONS = 'chatWidget.sessions.v2';   // [{id, title, messages, ts}]
  const LS_ACTIVE   = 'chatWidget.activeId';
  const LS_MODEL    = 'chatWidget.model';
  const LS_OPEN     = 'chatWidget.open';
  const LS_POS      = 'chatWidget.pos';
  const LS_SIZE     = 'chatWidget.size';
  const LS_FAB_POS  = 'chatWidget.fabPos';
  const LS_STREAM   = 'chatWidget.stream';

  const state = {
    sessions: [],        // [{id, title, messages, ts}]
    activeId: null,
    history: [],         // alias to active session messages
    pending: [],         // [{kind:'image'|'audio'|'file', name, mime, size, dataUrl?, transcript?}]
    sending: false,
    abortCtl: null,
    models: [],
    defaultModel: '',
    statusOk: null,
    loadedModels: false,
    recorder: null,      // MediaRecorder
    recordBlobs: [],
    recordStream: null,
    recordStart: 0,
    recordTimer: null,
  };

  // ── Styles (scoped via #cw- prefix) ───────────────────────────────────
  const css = `
  #cw-fab{position:fixed;right:20px;bottom:20px;width:58px;height:58px;border-radius:50%;
    background:linear-gradient(135deg,#1a73e8 0%,#4f8ef7 50%,#38bdf8 100%);color:#fff;border:none;cursor:grab;
    box-shadow:0 8px 24px rgba(26,115,232,.4),0 2px 6px rgba(26,115,232,.2);z-index:9990;
    display:flex;align-items:center;justify-content:center;transition:transform .18s cubic-bezier(.4,0,.2,1),box-shadow .18s;
    -webkit-tap-highlight-color:transparent;padding:0;line-height:0;touch-action:none;user-select:none;
    will-change:left,top,transform}
  #cw-fab.dragging{cursor:grabbing;transition:none!important;box-shadow:0 14px 36px rgba(26,115,232,.55),0 6px 14px rgba(26,115,232,.3);transform:scale(1.08)}
  #cw-fab:hover:not(.dragging){transform:translateY(-3px) scale(1.06);box-shadow:0 12px 32px rgba(26,115,232,.5),0 4px 10px rgba(26,115,232,.25)}
  #cw-fab:active:not(.dragging){transform:translateY(-1px) scale(1.02)}
  #cw-fab.open .cw-fab-icon{transform:scale(.88)}
  #cw-fab .cw-fab-icon{transition:transform .2s ease;filter:drop-shadow(0 1px 2px rgba(0,0,0,.2))}
  #cw-fab::before{content:'';position:absolute;inset:-4px;border-radius:50%;border:2px solid rgba(255,255,255,.3);
    opacity:0;animation:cw-ring 2.4s ease-out infinite}
  #cw-fab:hover::before{animation:none;opacity:0}
  @keyframes cw-ring{0%{opacity:.6;transform:scale(.95)}100%{opacity:0;transform:scale(1.18)}}
  #cw-fab .cw-dot{position:absolute;bottom:4px;right:4px;width:12px;height:12px;border-radius:50%;
    background:#10b981;border:2.5px solid #fff;box-shadow:0 0 0 0 rgba(16,185,129,.6);animation:cw-pulse-dot 2s infinite}
  #cw-fab .cw-dot.off{background:#9ca3af;animation:none}
  #cw-fab .cw-dot.warn{background:#f59e0b;animation:none}
  @keyframes cw-pulse-dot{0%{box-shadow:0 0 0 0 rgba(16,185,129,.6)}70%{box-shadow:0 0 0 8px rgba(16,185,129,0)}100%{box-shadow:0 0 0 0 rgba(16,185,129,0)}}

  #cw-panel{position:fixed;right:20px;bottom:90px;width:380px;height:560px;
    background:#fff;border:1px solid rgba(199,217,245,.6);border-radius:16px;
    box-shadow:0 20px 60px rgba(26,115,232,.22),0 4px 16px rgba(0,0,0,.06);
    display:none;flex-direction:column;overflow:hidden;z-index:9991;
    font-family:'Inter',system-ui,sans-serif;font-size:13px;color:#1a2332;
    will-change:left,top}
  #cw-panel.show{display:flex;animation:cw-in .22s cubic-bezier(.4,0,.2,1)}
  @keyframes cw-in{from{opacity:0;transform:translateY(16px) scale(.96)}to{opacity:1;transform:none}}
  #cw-panel.minimized{height:60px!important}
  #cw-panel.minimized .cw-body,#cw-panel.minimized .cw-foot,#cw-panel.minimized .cw-meta{display:none}

  /* Header */
  .cw-head{display:flex;align-items:center;gap:10px;padding:12px 14px;
    background:linear-gradient(135deg,#1a73e8 0%,#4f8ef7 60%,#38bdf8 100%);color:#fff;
    cursor:grab;user-select:none;flex-shrink:0;position:relative;overflow:hidden;touch-action:none}
  .cw-head:active{cursor:grabbing}
  #cw-panel.dragging{transition:none!important;box-shadow:0 24px 60px rgba(26,115,232,.3),0 8px 24px rgba(0,0,0,.12)}
  .cw-head::after{content:'';position:absolute;inset:0;background:radial-gradient(circle at 20% 0%,rgba(255,255,255,.18),transparent 60%);pointer-events:none}
  .cw-avatar{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.22);
    display:flex;align-items:center;justify-content:center;flex-shrink:0;backdrop-filter:blur(8px);
    border:1.5px solid rgba(255,255,255,.35);position:relative;z-index:1}
  .cw-head-info{flex:1;min-width:0;position:relative;z-index:1}
  .cw-head-name{font-weight:700;font-size:14px;letter-spacing:-.1px;display:flex;align-items:center;gap:6px;line-height:1.1}
  .cw-head-sub{font-size:10.5px;opacity:.85;font-weight:500;margin-top:2px;display:flex;align-items:center;gap:5px}
  .cw-head-sub .cw-status-dot{width:6px;height:6px;border-radius:50%;background:#10b981;
    box-shadow:0 0 6px rgba(16,185,129,.7);flex-shrink:0}
  .cw-head-sub .cw-status-dot.off{background:#9ca3af;box-shadow:none}
  .cw-head-sub .cw-status-dot.warn{background:#fbbf24;box-shadow:0 0 6px rgba(251,191,36,.6)}
  .cw-head-actions{display:flex;gap:4px;position:relative;z-index:1}
  .cw-head button{background:rgba(255,255,255,.16);border:none;color:#fff;width:28px;height:28px;
    border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;
    transition:background .15s,transform .1s;padding:0}
  .cw-head button:hover{background:rgba(255,255,255,.3)}
  .cw-head button:active{transform:scale(.92)}
  .cw-head button svg{width:15px;height:15px;display:block}

  /* Toolbar */
  .cw-meta{display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid #eef2ff;
    background:#fafbff;flex-shrink:0;font-size:11px;color:#3d5a80}
  .cw-meta select{flex:1;min-width:0;padding:5px 8px;font-size:11px;border:1px solid #d8e2f5;
    border-radius:6px;background:#fff;color:#1a2332;font-family:inherit;cursor:pointer;
    transition:border-color .15s}
  .cw-meta select:hover{border-color:#a8c4f0}
  .cw-meta .cw-toggle{display:flex;align-items:center;gap:6px;cursor:pointer;font-size:11px;
    padding:4px 8px;border-radius:6px;border:1px solid transparent;transition:all .15s;user-select:none}
  .cw-meta .cw-toggle:hover{background:#eef2ff}
  .cw-meta .cw-toggle.on{color:#1a73e8;font-weight:600}
  .cw-meta input[type=checkbox]{accent-color:#1a73e8;margin:0;width:13px;height:13px}

  /* Body */
  .cw-body{flex:1;overflow-y:auto;padding:14px;background:linear-gradient(180deg,#f8faff 0%,#f1f5fe 100%);
    display:flex;flex-direction:column;gap:12px;scroll-behavior:smooth}
  .cw-body::-webkit-scrollbar{width:6px}
  .cw-body::-webkit-scrollbar-thumb{background:#c7d9f5;border-radius:3px}
  .cw-body::-webkit-scrollbar-thumb:hover{background:#a8c4f0}

  /* Bubbles */
  .cw-bubble-row{display:flex;gap:8px;max-width:100%;align-items:flex-start}
  .cw-bubble-row.me{justify-content:flex-end}
  .cw-bubble-row.bot{justify-content:flex-start}
  .cw-msg-avatar{width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;
    background:linear-gradient(135deg,#1a73e8,#38bdf8);color:#fff;box-shadow:0 2px 6px rgba(26,115,232,.3)}
  .cw-msg-avatar svg{width:16px;height:16px}
  .cw-bubble-row.me .cw-msg-avatar{display:none}
  .cw-bubble-wrap{display:flex;flex-direction:column;max-width:78%;min-width:0}
  .cw-bubble-row.me .cw-bubble-wrap{align-items:flex-end}
  .cw-bubble{padding:9px 13px;border-radius:14px;line-height:1.5;
    white-space:pre-wrap;word-break:break-word;font-size:13px;animation:cw-bubble-in .25s ease}
  @keyframes cw-bubble-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  .cw-bubble-row.me .cw-bubble{background:linear-gradient(135deg,#1a73e8,#3b82f6);color:#fff;
    border-bottom-right-radius:5px;box-shadow:0 2px 8px rgba(26,115,232,.25)}
  .cw-bubble-row.bot .cw-bubble{background:#fff;color:#1a2332;border:1px solid #eef2ff;
    border-bottom-left-radius:5px;box-shadow:0 1px 4px rgba(26,115,232,.06)}
  .cw-bubble.err{background:#fdecea!important;color:#c0392b!important;border-color:#f5c1bb!important}
  .cw-bubble.warn{background:#fef3cd!important;color:#7a5a1a!important;border-color:#f0d97c!important}
  .cw-tag{font-size:10px;color:#8fa8c8;margin-top:3px;padding:0 4px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .cw-tag b{color:#3d5a80;font-weight:600}

  /* Message images (in user bubbles) */
  .cw-msg-images{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;justify-content:flex-end}
  .cw-msg-img{max-width:200px;max-height:200px;border-radius:10px;cursor:zoom-in;
    border:1px solid #d8e2f5;box-shadow:0 2px 8px rgba(26,115,232,.15);object-fit:cover;
    transition:transform .15s}
  .cw-msg-img:hover{transform:scale(1.02)}
  .cw-bubble-row.bot .cw-msg-images{justify-content:flex-start}

  /* Lightbox */
  .cw-lightbox{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;
    display:flex;align-items:center;justify-content:center;cursor:zoom-out;animation:cw-bubble-in .2s}
  .cw-lightbox img{max-width:92vw;max-height:92vh;border-radius:6px;box-shadow:0 12px 40px rgba(0,0,0,.5)}
  .cw-lightbox-close{position:absolute;top:18px;right:18px;width:40px;height:40px;border-radius:50%;
    background:rgba(255,255,255,.15);color:#fff;border:none;cursor:pointer;font-size:24px;
    display:flex;align-items:center;justify-content:center}
  .cw-lightbox-close:hover{background:rgba(255,255,255,.25)}

  /* Inline rich content rendered inside bot bubbles */
  .cw-bubble a{color:#1a73e8;text-decoration:none;border-bottom:1px dashed rgba(26,115,232,.4);word-break:break-all}
  .cw-bubble a:hover{border-bottom-style:solid}
  .cw-bubble-row.me .cw-bubble a{color:#fff;border-bottom-color:rgba(255,255,255,.5)}
  .cw-inline-img{display:block;max-width:100%;max-height:280px;border-radius:10px;margin:6px 0;
    cursor:zoom-in;border:1px solid #e3ebf7;box-shadow:0 2px 8px rgba(26,115,232,.1);object-fit:cover}
  .cw-inline-img:hover{filter:brightness(1.03)}
  .cw-vid-card{display:block;border:1px solid #e3ebf7;border-radius:12px;overflow:hidden;
    margin:6px 0;background:#f8faff;text-decoration:none!important;border-bottom:1px solid #e3ebf7!important;
    transition:transform .15s,box-shadow .15s;max-width:340px}
  .cw-vid-card:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(26,115,232,.18)}
  .cw-vid-thumb{position:relative;width:100%;aspect-ratio:16/9;background:#0b1220;
    display:flex;align-items:center;justify-content:center;overflow:hidden}
  .cw-vid-thumb img{width:100%;height:100%;object-fit:cover;display:block;border:none;border-radius:0}
  .cw-vid-play{position:absolute;width:48px;height:48px;border-radius:50%;
    background:rgba(0,0,0,.65);color:#fff;display:flex;align-items:center;justify-content:center;
    box-shadow:0 4px 12px rgba(0,0,0,.4);transition:transform .15s,background .15s;pointer-events:none}
  .cw-vid-card:hover .cw-vid-play{transform:scale(1.1);background:rgba(220,38,38,.95)}
  .cw-vid-play svg{width:22px;height:22px;margin-left:3px;fill:#fff}
  .cw-vid-meta{padding:8px 10px;font-size:11.5px;color:#3d5a80;display:flex;align-items:center;gap:6px}
  .cw-vid-meta .cw-vid-host{font-weight:600;color:#1a2332;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .cw-vid-meta .cw-vid-domain{margin-left:auto;font-size:10.5px;color:#8fa8c8;flex-shrink:0}

  /* Empty state */
  .cw-empty{margin:auto;text-align:center;color:#5b7aa6;padding:20px;font-size:13px;line-height:1.6;animation:cw-bubble-in .3s}
  .cw-empty-bot{width:64px;height:64px;border-radius:18px;margin:0 auto 14px;
    background:linear-gradient(135deg,#1a73e8,#38bdf8);display:flex;align-items:center;justify-content:center;
    box-shadow:0 8px 24px rgba(26,115,232,.3);color:#fff}
  .cw-empty-bot svg{width:38px;height:38px}
  .cw-empty-title{font-weight:700;color:#1a2332;font-size:15px;margin-bottom:4px}
  .cw-empty-sub{font-size:12px;color:#8fa8c8}
  .cw-suggestions{display:flex;flex-direction:column;gap:6px;margin-top:14px;max-width:100%}
  .cw-sugg{padding:8px 12px;background:#fff;border:1px solid #d8e2f5;border-radius:10px;
    cursor:pointer;font-size:12px;color:#3d5a80;text-align:left;transition:all .15s;
    box-shadow:0 1px 3px rgba(26,115,232,.04)}
  .cw-sugg:hover{border-color:#1a73e8;color:#1a73e8;transform:translateY(-1px);box-shadow:0 3px 8px rgba(26,115,232,.12)}

  /* Footer / input */
  .cw-foot{padding:10px 12px 12px;background:#fff;border-top:1px solid #eef2ff;flex-shrink:0;position:relative}

  /* Attach menu */
  .cw-attach-wrap{position:relative;flex-shrink:0}
  .cw-attach{background:#eef2ff;color:#1a73e8;border:none;width:34px;height:34px;border-radius:50%;
    cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;padding:0;margin-bottom:0}
  .cw-attach:hover{background:#dbe7fb;transform:scale(1.05)}
  .cw-attach svg{width:18px;height:18px;transition:transform .2s ease}
  .cw-attach.open svg{transform:rotate(45deg)}
  .cw-attach-menu{position:absolute;left:0;bottom:44px;background:#fff;border:1px solid #d8e2f5;
    border-radius:12px;padding:6px;min-width:180px;
    box-shadow:0 12px 30px rgba(26,115,232,.18),0 4px 10px rgba(0,0,0,.06);
    display:none;z-index:10;animation:cw-bubble-in .15s ease}
  .cw-attach-menu.show{display:flex;flex-direction:column;gap:2px}
  .cw-attach-item{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;
    cursor:pointer;font-size:12.5px;color:#1a2332;border:none;background:transparent;width:100%;
    text-align:left;font-family:inherit;transition:background .12s}
  .cw-attach-item:hover{background:#eef2ff}
  .cw-attach-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;color:#fff}
  .cw-attach-icon svg{width:15px;height:15px}
  .cw-att-img{background:linear-gradient(135deg,#10b981,#34d399)}
  .cw-att-vid{background:linear-gradient(135deg,#f59e0b,#fbbf24)}
  .cw-att-aud{background:linear-gradient(135deg,#8b5cf6,#a78bfa)}
  .cw-att-file{background:linear-gradient(135deg,#3b82f6,#60a5fa)}
  .cw-att-mic{background:linear-gradient(135deg,#ef4444,#f87171)}

  /* Attachment chips above input */
  .cw-attachments{display:flex;gap:6px;flex-wrap:wrap;padding:0 4px 8px;max-height:140px;overflow-y:auto}
  .cw-chip{display:flex;align-items:center;gap:6px;padding:4px 6px 4px 4px;background:#f5f8ff;
    border:1px solid #d8e2f5;border-radius:10px;font-size:11.5px;color:#3d5a80;max-width:200px;position:relative}
  .cw-chip-thumb{width:32px;height:32px;border-radius:6px;background:#dbe7fb;flex-shrink:0;
    display:flex;align-items:center;justify-content:center;color:#1a73e8;overflow:hidden}
  .cw-chip-thumb img{width:100%;height:100%;object-fit:cover}
  .cw-chip-thumb svg{width:14px;height:14px}
  .cw-chip-info{display:flex;flex-direction:column;gap:1px;min-width:0;padding-right:18px}
  .cw-chip-name{font-weight:600;color:#1a2332;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px}
  .cw-chip-meta{font-size:10px;color:#8fa8c8}
  .cw-chip-close{position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;
    background:rgba(0,0,0,.08);color:#3d5a80;border:none;cursor:pointer;font-size:11px;line-height:1;
    display:flex;align-items:center;justify-content:center;padding:0}
  .cw-chip-close:hover{background:#fdecea;color:#c0392b}

  /* Recording bar */
  .cw-rec-bar{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#fef2f2;
    border:1px solid #fca5a5;border-radius:10px;margin:0 4px 8px;color:#c0392b;font-size:12px;font-weight:500}
  .cw-rec-dot{width:10px;height:10px;border-radius:50%;background:#ef4444;animation:cw-rec 1s infinite}
  @keyframes cw-rec{0%,100%{opacity:1}50%{opacity:.3}}
  .cw-rec-time{font-family:monospace;font-weight:600}
  .cw-rec-actions{margin-left:auto;display:flex;gap:6px}
  .cw-rec-btn{background:#fff;border:1px solid #fca5a5;color:#c0392b;padding:4px 10px;
    border-radius:6px;cursor:pointer;font-size:11px;font-weight:600}
  .cw-rec-btn.primary{background:#ef4444;color:#fff;border-color:#ef4444}
  .cw-rec-btn:hover{filter:brightness(.95)}

  /* History drawer */
  .cw-drawer{position:absolute;left:0;top:0;bottom:0;width:230px;background:#fff;
    border-right:1px solid #eef2ff;z-index:5;display:flex;flex-direction:column;
    transform:translateX(-100%);transition:transform .22s cubic-bezier(.4,0,.2,1);box-shadow:4px 0 16px rgba(26,115,232,.08)}
  .cw-drawer.show{transform:translateX(0)}
  .cw-drawer-head{padding:12px 12px 8px;border-bottom:1px solid #eef2ff;display:flex;align-items:center;gap:6px}
  .cw-drawer-title{flex:1;font-weight:700;font-size:12px;color:#3d5a80;text-transform:uppercase;letter-spacing:.5px}
  .cw-drawer-new{background:linear-gradient(135deg,#1a73e8,#3b82f6);color:#fff;border:none;
    padding:5px 10px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;display:flex;align-items:center;gap:4px}
  .cw-drawer-new:hover{filter:brightness(1.05)}
  .cw-drawer-list{flex:1;overflow-y:auto;padding:6px}
  .cw-drawer-list::-webkit-scrollbar{width:5px}
  .cw-drawer-list::-webkit-scrollbar-thumb{background:#c7d9f5;border-radius:3px}
  .cw-sess{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;cursor:pointer;
    margin-bottom:2px;border:1px solid transparent;transition:all .12s;position:relative}
  .cw-sess:hover{background:#eef2ff}
  .cw-sess.active{background:#dbe7fb;border-color:#a8c4f0}
  .cw-sess-info{flex:1;min-width:0}
  .cw-sess-title{font-size:12px;font-weight:600;color:#1a2332;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}
  .cw-sess-time{font-size:10px;color:#8fa8c8;margin-top:1px}
  .cw-sess-del{background:none;border:none;color:#8fa8c8;cursor:pointer;width:22px;height:22px;
    border-radius:5px;display:none;align-items:center;justify-content:center;padding:0;flex-shrink:0}
  .cw-sess:hover .cw-sess-del{display:flex}
  .cw-sess-del:hover{background:#fdecea;color:#c0392b}
  .cw-sess-del svg{width:13px;height:13px}
  .cw-drawer-empty{text-align:center;color:#8fa8c8;font-size:11px;padding:24px 12px}

  .cw-input-wrap{display:flex;gap:6px;align-items:flex-end;background:#f5f8ff;border:1.5px solid #d8e2f5;
    border-radius:20px;padding:4px 4px 4px 6px;transition:all .15s}
  .cw-input-wrap:focus-within{border-color:#1a73e8;background:#fff;box-shadow:0 0 0 3px rgba(26,115,232,.1)}
  .cw-foot textarea{flex:1;min-height:32px;max-height:120px;padding:7px 4px 7px 8px;
    border:none;background:transparent;resize:none;font-family:inherit;font-size:13px;
    line-height:1.4;outline:none;color:#1a2332}
  .cw-foot textarea::placeholder{color:#8fa8c8}
  .cw-send{background:linear-gradient(135deg,#1a73e8,#3b82f6);color:#fff;border:none;
    width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;
    flex-shrink:0;transition:all .15s;padding:0}
  .cw-send:hover{transform:scale(1.06);box-shadow:0 4px 10px rgba(26,115,232,.4)}
  .cw-send:active{transform:scale(.95)}
  .cw-send:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
  .cw-send svg{width:16px;height:16px}
  .cw-stop{background:#fdecea;color:#c0392b;border:none;width:34px;height:34px;
    border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;
    transition:all .15s}
  .cw-stop:hover{background:#fbd5d2}
  .cw-stop svg{width:14px;height:14px}
  .cw-foot-hint{margin-top:6px;font-size:10px;color:#a8c4f0;display:flex;justify-content:space-between;padding:0 4px}
  .cw-foot-hint kbd{background:#eef2ff;border:1px solid #d8e2f5;border-radius:3px;padding:1px 5px;
    font-family:inherit;font-size:9.5px;color:#5b7aa6}

  /* Resize handles */
  .cw-resize{position:absolute;left:0;top:58px;width:6px;height:calc(100% - 58px);cursor:ew-resize;background:transparent}
  .cw-resize-tl{position:absolute;left:0;top:58px;width:14px;height:14px;cursor:nwse-resize;background:transparent}

  /* Typing indicator */
  .cw-typing{display:inline-flex;gap:4px;padding:2px 0}
  .cw-typing span{width:7px;height:7px;border-radius:50%;background:#a8c4f0;animation:cw-typing 1.3s infinite}
  .cw-typing span:nth-child(2){animation-delay:.15s}
  .cw-typing span:nth-child(3){animation-delay:.3s}
  @keyframes cw-typing{0%,60%,100%{opacity:.3;transform:translateY(0)}30%{opacity:1;transform:translateY(-3px)}}

  /* Mobile */
  @media(max-width:560px){
    #cw-fab{right:14px;bottom:74px;width:54px;height:54px}
    #cw-panel{right:0!important;left:0!important;bottom:0!important;top:auto!important;
      width:auto!important;height:85vh!important;
      border-radius:18px 18px 0 0;border-left:none;border-right:none;border-bottom:none}
    #cw-panel .cw-resize,#cw-panel .cw-resize-tl{display:none}
  }
  `;

  function injectStyle() {
    if (document.getElementById('cw-style')) return;
    const s = document.createElement('style');
    s.id = 'cw-style';
    s.textContent = css;
    document.head.appendChild(s);
  }

  // ── DOM ───────────────────────────────────────────────────────────────
  // Reusable robot SVG — shared between FAB, header avatar, empty state, bot bubbles.
  const ROBOT_SVG = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="4" y="7" width="16" height="12" rx="3"/>
      <path d="M12 7V4"/>
      <circle cx="12" cy="3" r="1" fill="currentColor"/>
      <circle cx="9" cy="13" r="1.4" fill="currentColor" stroke="none"/>
      <circle cx="15" cy="13" r="1.4" fill="currentColor" stroke="none"/>
      <path d="M9.5 16.5h5"/>
      <path d="M2.5 12v3"/>
      <path d="M21.5 12v3"/>
    </svg>`;

  function buildDom() {
    const fab = document.createElement('button');
    fab.id = 'cw-fab';
    fab.title = 'Hỏi AI';
    fab.innerHTML = `<span class="cw-fab-icon" style="display:inline-flex;color:#fff;width:30px;height:30px">${ROBOT_SVG}</span>
      <span class="cw-dot off" id="cw-fab-dot"></span>`;

    const panel = document.createElement('div');
    panel.id = 'cw-panel';
    panel.innerHTML = `
      <div class="cw-head" id="cw-head">
        <div class="cw-avatar">
          <span style="display:inline-flex;color:#fff;width:20px;height:20px">${ROBOT_SVG}</span>
        </div>
        <div class="cw-head-info">
          <div class="cw-head-name">AI Assistant</div>
          <div class="cw-head-sub">
            <span class="cw-status-dot off" id="cw-status-dot"></span>
            <span id="cw-status">đang kiểm tra…</span>
          </div>
        </div>
        <div class="cw-head-actions">
          <button id="cw-history" title="Lịch sử">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 1.5-5"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/></svg>
          </button>
          <button id="cw-new" title="Cuộc mới">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button id="cw-min" title="Thu nhỏ">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14"/></svg>
          </button>
          <button id="cw-close" title="Đóng">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
        </div>
      </div>
      <div class="cw-meta">
        <select id="cw-model" title="Chọn model"><option value="">⚡ Auto (model mặc định)</option></select>
        <label class="cw-toggle on" id="cw-stream-label" title="Stream từng token">
          <input type="checkbox" id="cw-stream" checked>
          <span>Stream</span>
        </label>
      </div>
      <div class="cw-body" id="cw-body">
        <div class="cw-empty" id="cw-empty">
          <div class="cw-empty-bot">${ROBOT_SVG}</div>
          <div class="cw-empty-title">Xin chào! 👋</div>
          <div class="cw-empty-sub">Tôi có thể giúp gì cho bạn hôm nay?</div>
          <div class="cw-suggestions">
            <button class="cw-sugg" data-q="Tóm tắt công cụ này có thể làm những gì?">💡 Công cụ này làm được gì?</button>
            <button class="cw-sugg" data-q="Viết caption TikTok hấp dẫn cho video du lịch Đà Lạt 60 giây">✍️ Viết caption TikTok</button>
            <button class="cw-sugg" data-q="Gợi ý 5 hashtag thịnh hành cho video review phim ngắn">#️⃣ Gợi ý hashtag</button>
          </div>
        </div>
      </div>
      <div class="cw-foot">
        <div class="cw-attachments" id="cw-attachments" style="display:none"></div>
        <div class="cw-rec-bar" id="cw-rec-bar" style="display:none">
          <span class="cw-rec-dot"></span>
          <span>Đang ghi âm</span>
          <span class="cw-rec-time" id="cw-rec-time">0:00</span>
          <div class="cw-rec-actions">
            <button class="cw-rec-btn" id="cw-rec-cancel">Huỷ</button>
            <button class="cw-rec-btn primary" id="cw-rec-stop">Dừng &amp; gắn</button>
          </div>
        </div>
        <div class="cw-input-wrap">
          <div class="cw-attach-wrap">
            <button class="cw-attach" id="cw-attach" title="Đính kèm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            </button>
            <div class="cw-attach-menu" id="cw-attach-menu">
              <button class="cw-attach-item" data-act="image">
                <span class="cw-attach-icon cw-att-img">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                </span>
                <span>Ảnh</span>
              </button>
              <button class="cw-attach-item" data-act="video">
                <span class="cw-attach-icon cw-att-vid">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>
                </span>
                <span>Video</span>
              </button>
              <button class="cw-attach-item" data-act="audio">
                <span class="cw-attach-icon cw-att-aud">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                </span>
                <span>Âm thanh</span>
              </button>
              <button class="cw-attach-item" data-act="file">
                <span class="cw-attach-icon cw-att-file">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </span>
                <span>Tệp khác</span>
              </button>
              <button class="cw-attach-item" data-act="record">
                <span class="cw-attach-icon cw-att-mic">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2"/><path d="M12 19v3"/></svg>
                </span>
                <span>Ghi âm</span>
              </button>
            </div>
          </div>
          <textarea id="cw-input" rows="1" placeholder="Hỏi tôi bất cứ điều gì..."></textarea>
          <button class="cw-stop" id="cw-stop" style="display:none" title="Dừng">
            <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
          </button>
          <button class="cw-send" id="cw-send" title="Gửi (Enter)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>
            </svg>
          </button>
        </div>
        <div class="cw-foot-hint">
          <span id="cw-hint">Sẵn sàng</span>
          <span><kbd>Enter</kbd> gửi · <kbd>Ctrl+L</kbd> mới</span>
        </div>
      </div>
      <input type="file" id="cw-file-image" accept="image/*" style="display:none" multiple>
      <input type="file" id="cw-file-video" accept="video/*" style="display:none">
      <input type="file" id="cw-file-audio" accept="audio/*" style="display:none">
      <input type="file" id="cw-file-any" style="display:none">
      <div class="cw-drawer" id="cw-drawer">
        <div class="cw-drawer-head">
          <div class="cw-drawer-title">Lịch sử chat</div>
          <button class="cw-drawer-new" id="cw-drawer-new">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
            Mới
          </button>
        </div>
        <div class="cw-drawer-list" id="cw-drawer-list"></div>
      </div>
      <div class="cw-resize" id="cw-resize"></div>
      <div class="cw-resize-tl" id="cw-resize-tl"></div>
    `;
    document.body.appendChild(fab);
    document.body.appendChild(panel);

    // Wire suggestion chips.
    panel.querySelectorAll('.cw-sugg').forEach(btn => {
      btn.addEventListener('click', () => {
        const q = btn.getAttribute('data-q') || btn.textContent;
        const inp = document.getElementById('cw-input');
        if (inp) { inp.value = q; inp.focus(); autoresize(inp); }
      });
    });

    return { fab, panel };
  }

  // ── Helpers ───────────────────────────────────────────────────────────
  function $(id){ return document.getElementById(id); }
  function setStatus(text, color){
    const s = $('cw-status'); if (s) s.textContent = text;
    const subDot = $('cw-status-dot');
    if (subDot){
      subDot.classList.remove('off','warn');
      if (color === 'red' || !color) subDot.classList.add('off');
      else if (color === 'yellow') subDot.classList.add('warn');
    }
    const fabDot = $('cw-fab-dot');
    if (fabDot){
      fabDot.classList.remove('off','warn');
      if (color === 'red' || !color) fabDot.classList.add('off');
      else if (color === 'yellow') fabDot.classList.add('warn');
    }
  }
  function setHint(t){ const e=$('cw-hint'); if (e) e.textContent = t; }

  async function api(method, url, body){
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let r, data = null;
    try { r = await fetch(url, opts); } catch(e){ return { ok:false, status:0, data:{ error: e.message } }; }
    try { data = await r.json(); } catch(_){}
    return { ok: r.ok, status: r.status, data: data || {} };
  }

  // ── Bubble rendering ──────────────────────────────────────────────────
  function appendBubble(role, text, opts){
    const wrap = $('cw-body');
    const empty = $('cw-empty');
    if (empty) empty.remove();

    const row = document.createElement('div');
    row.className = 'cw-bubble-row ' + (role === 'user' ? 'me' : 'bot');

    if (role !== 'user') {
      const av = document.createElement('div');
      av.className = 'cw-msg-avatar';
      av.innerHTML = ROBOT_SVG;
      row.appendChild(av);
    }

    const wrapEl = document.createElement('div');
    wrapEl.className = 'cw-bubble-wrap';

    // Image previews above the text bubble for user messages.
    const images = (opts?.attachments || []).filter(a => a.kind === 'image' && a.thumbDataUrl);
    if (images.length){
      const gallery = document.createElement('div');
      gallery.className = 'cw-msg-images';
      for (const img of images){
        const el = document.createElement('img');
        el.src = img.thumbDataUrl;
        el.alt = img.name || 'image';
        el.className = 'cw-msg-img';
        el.addEventListener('click', () => {
          // Open in a lightbox-like modal.
          openLightbox(img.thumbDataUrl, img.name);
        });
        gallery.appendChild(el);
      }
      wrapEl.appendChild(gallery);
    }

    if (text) {
      const bub = document.createElement('div');
      bub.className = 'cw-bubble';
      bub.textContent = text;
      wrapEl.appendChild(bub);
    }

    const tag = document.createElement('div');
    tag.className = 'cw-tag';
    wrapEl.appendChild(tag);

    row.appendChild(wrapEl);
    wrap.appendChild(row);
    wrap.scrollTop = wrap.scrollHeight;
    // Return the *last* bubble element if any (for streaming patches).
    const lastBub = wrapEl.querySelector('.cw-bubble');
    return { row, bub: lastBub, tag, wrap: wrapEl };
  }

  function openLightbox(src, name){
    const modal = document.createElement('div');
    modal.className = 'cw-lightbox';
    modal.innerHTML = `<img src="${src}" alt="${name||''}"><button class="cw-lightbox-close">×</button>`;
    modal.addEventListener('click', () => modal.remove());
    document.body.appendChild(modal);
  }

  // ── Rich content enrichment ─────────────────────────────────────────
  // Turns plain text (often containing markdown like ![alt](url),
  // [title](url), bare image URLs, or YouTube/Vimeo/TikTok links) into
  // proper DOM nodes: inline images, link cards with video thumbnails,
  // clickable links. Run *after* streaming finishes to avoid flicker.
  const URL_RX = /(https?:\/\/[^\s<>")\]]+)/gi;
  const IMG_EXT_RX = /\.(?:png|jpe?g|gif|webp|bmp|svg|avif)(?:\?[^\s)]*)?$/i;
  const MD_IMG_RX = /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
  const MD_LINK_RX = /\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;

  function _videoInfo(url){
    try {
      const u = new URL(url);
      const host = u.hostname.replace(/^www\./, '');
      // YouTube: youtu.be/<id>, youtube.com/watch?v=<id>, /shorts/<id>, /embed/<id>
      if (/(^|\.)youtu\.be$/.test(host)){
        const id = u.pathname.split('/').filter(Boolean)[0] || '';
        if (/^[A-Za-z0-9_-]{6,}$/.test(id))
          return { kind:'youtube', id, host:'YouTube', domain:host,
                   thumb:`https://i.ytimg.com/vi/${id}/hqdefault.jpg` };
      }
      if (/(^|\.)youtube\.com$/.test(host) || host === 'm.youtube.com'){
        let id = u.searchParams.get('v') || '';
        if (!id){
          const parts = u.pathname.split('/').filter(Boolean);
          const i = parts.findIndex(p => p === 'shorts' || p === 'embed' || p === 'live');
          if (i >= 0 && parts[i+1]) id = parts[i+1];
        }
        if (/^[A-Za-z0-9_-]{6,}$/.test(id))
          return { kind:'youtube', id, host:'YouTube', domain:host,
                   thumb:`https://i.ytimg.com/vi/${id}/hqdefault.jpg` };
      }
      // Vimeo: vimeo.com/<id>
      if (/(^|\.)vimeo\.com$/.test(host)){
        const id = u.pathname.split('/').filter(Boolean)[0] || '';
        if (/^\d{5,}$/.test(id))
          return { kind:'vimeo', id, host:'Vimeo', domain:host,
                   thumb:`https://vumbnail.com/${id}.jpg` };
      }
      // TikTok / Douyin / Facebook / Instagram — no public thumbnail API.
      // Show a generic video card using a domain favicon as a placeholder.
      const VIDEO_HOSTS = {
        'tiktok.com':'TikTok', 'vm.tiktok.com':'TikTok', 'vt.tiktok.com':'TikTok',
        'douyin.com':'Douyin', 'iesdouyin.com':'Douyin', 'v.douyin.com':'Douyin',
        'facebook.com':'Facebook', 'fb.watch':'Facebook',
        'instagram.com':'Instagram',
        'twitter.com':'X', 'x.com':'X',
        'dailymotion.com':'Dailymotion',
        'twitch.tv':'Twitch',
        'bilibili.com':'Bilibili',
      };
      for (const [h, label] of Object.entries(VIDEO_HOSTS)){
        if (host === h || host.endsWith('.' + h)){
          return { kind:'generic', host:label, domain:host,
                   thumb:`https://www.google.com/s2/favicons?domain=${host}&sz=128` };
        }
      }
    } catch(_){}
    return null;
  }

  function _isImageUrl(url){
    if (!url) return false;
    if (/^data:image\//i.test(url)) return true;
    try {
      const u = new URL(url);
      if (IMG_EXT_RX.test(u.pathname)) return true;
      // Common image CDNs
      const host = u.hostname;
      if (/(^|\.)ytimg\.com$/.test(host)) return true;
      if (/(^|\.)googleusercontent\.com$/.test(host)) return true;
      if (/(^|\.)imgur\.com$/.test(host)) return /\.(?:png|jpe?g|gif|webp)$/i.test(u.pathname);
      if (/(^|\.)staticflickr\.com$/.test(host)) return true;
      if (/(^|\.)unsplash\.com$/.test(host)) return true;
    } catch(_){}
    return false;
  }

  function _makeInlineImg(src, alt){
    const img = document.createElement('img');
    img.className = 'cw-inline-img';
    img.loading = 'lazy';
    img.alt = alt || '';
    img.src = src;
    img.addEventListener('error', () => {
      // If broken, swap for a plain link so the user still sees the URL.
      const a = document.createElement('a');
      a.href = src; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = src;
      img.replaceWith(a);
    });
    img.addEventListener('click', () => openLightbox(src, alt));
    return img;
  }

  function _makeVideoCard(url, info, label){
    const card = document.createElement('a');
    card.className = 'cw-vid-card';
    card.href = url;
    card.target = '_blank';
    card.rel = 'noopener noreferrer';

    const thumb = document.createElement('div');
    thumb.className = 'cw-vid-thumb';
    if (info.thumb){
      const im = document.createElement('img');
      im.loading = 'lazy';
      im.referrerPolicy = 'no-referrer';
      im.src = info.thumb;
      im.alt = info.host;
      im.addEventListener('error', () => { im.style.display = 'none'; });
      thumb.appendChild(im);
    }
    const play = document.createElement('div');
    play.className = 'cw-vid-play';
    play.innerHTML = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
    thumb.appendChild(play);

    const meta = document.createElement('div');
    meta.className = 'cw-vid-meta';
    const host = document.createElement('span');
    host.className = 'cw-vid-host';
    host.textContent = label || info.host;
    const dom = document.createElement('span');
    dom.className = 'cw-vid-domain';
    dom.textContent = info.domain;
    meta.appendChild(host);
    meta.appendChild(dom);

    card.appendChild(thumb);
    card.appendChild(meta);
    return card;
  }

  // Some Kiro-routed models (sonnet via Kiro proxy) leak pseudo-tool tags
  // like <web_search>...</web_search>, <invoke>...</invoke>, <tool_use>...
  // because they think they have tools they don't. Strip these so the user
  // sees a clean answer instead of XML soup.
  function _stripFakeToolTags(text){
    if (!text) return text;
    let t = text;
    // Block-level pseudo tools.
    t = t.replace(/<\s*(web_search|web-search|websearch|search|tool_use|tool-use|invoke|function_calls|antml:function_calls)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, '');
    // Self-closing variants.
    t = t.replace(/<\s*(web_search|tool_use|invoke|function_calls|antml:function_calls)\b[^>]*\/?\s*>/gi, '');
    // Stray opening/closing tags left over.
    t = t.replace(/<\s*\/?\s*(query|max_results|parameter|antml:parameter)\s*>/gi, '');
    // Collapse empty lines created by the strip.
    t = t.replace(/\n{3,}/g, '\n\n').trim();
    return t;
  }

  function enrichBubble(bub, rawText){
    if (!bub || typeof rawText !== 'string') return;
    const text = _stripFakeToolTags(rawText);

    // Pre-collect markdown image / link spans so we can avoid double-rendering.
    const mdImages = [];   // [{start, end, alt, url}]
    const mdLinks  = [];   // [{start, end, label, url}]
    let m;
    MD_IMG_RX.lastIndex = 0;
    while ((m = MD_IMG_RX.exec(text)) !== null){
      mdImages.push({ start: m.index, end: m.index + m[0].length, alt: m[1] || '', url: m[2] });
    }
    MD_LINK_RX.lastIndex = 0;
    while ((m = MD_LINK_RX.exec(text)) !== null){
      // Skip if this match is actually inside an md image (preceded by '!')
      if (m.index > 0 && text[m.index - 1] === '!') continue;
      mdLinks.push({ start: m.index, end: m.index + m[0].length, label: m[1], url: m[2] });
    }

    // Build a list of "tokens" — plain text spans + special spans.
    const spans = [];
    const reserved = [...mdImages, ...mdLinks].sort((a,b) => a.start - b.start);
    let cursor = 0;
    for (const s of reserved){
      if (s.start < cursor) continue; // overlap, skip
      if (s.start > cursor){
        spans.push({ kind:'text', text: text.slice(cursor, s.start) });
      }
      spans.push(s.alt !== undefined
        ? { kind:'mdimg', alt: s.alt, url: s.url }
        : { kind:'mdlink', label: s.label, url: s.url });
      cursor = s.end;
    }
    if (cursor < text.length) spans.push({ kind:'text', text: text.slice(cursor) });

    // Now walk each text span and split out bare URLs.
    const out = []; // DOM-buildable parts
    for (const sp of spans){
      if (sp.kind !== 'text'){ out.push(sp); continue; }
      const t = sp.text;
      let last = 0;
      let mm;
      URL_RX.lastIndex = 0;
      while ((mm = URL_RX.exec(t)) !== null){
        if (mm.index > last) out.push({ kind:'text', text: t.slice(last, mm.index) });
        // Strip trailing punctuation often glued to URLs.
        let url = mm[0];
        let trail = '';
        const trailMatch = url.match(/[)\].,;:!?'"”»]+$/);
        if (trailMatch){ trail = trailMatch[0]; url = url.slice(0, -trail.length); }
        out.push({ kind:'url', url });
        if (trail) out.push({ kind:'text', text: trail });
        last = mm.index + mm[0].length;
      }
      if (last < t.length) out.push({ kind:'text', text: t.slice(last) });
    }

    // Render: clear bubble and rebuild.
    bub.replaceChildren();
    bub.style.whiteSpace = 'pre-wrap';
    let mediaCount = 0;

    for (const part of out){
      if (part.kind === 'text'){
        if (part.text) bub.appendChild(document.createTextNode(part.text));
        continue;
      }
      if (part.kind === 'mdimg'){
        bub.appendChild(_makeInlineImg(part.url, part.alt));
        mediaCount++;
        continue;
      }
      if (part.kind === 'mdlink'){
        const url = part.url;
        const vinfo = _videoInfo(url);
        if (vinfo){
          bub.appendChild(_makeVideoCard(url, vinfo, part.label));
          mediaCount++;
        } else if (_isImageUrl(url)){
          bub.appendChild(_makeInlineImg(url, part.label));
          mediaCount++;
        } else {
          const a = document.createElement('a');
          a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
          a.textContent = part.label;
          bub.appendChild(a);
        }
        continue;
      }
      if (part.kind === 'url'){
        const url = part.url;
        if (_isImageUrl(url)){
          bub.appendChild(_makeInlineImg(url, ''));
          mediaCount++;
          continue;
        }
        const vinfo = _videoInfo(url);
        if (vinfo){
          bub.appendChild(_makeVideoCard(url, vinfo, vinfo.host));
          mediaCount++;
          continue;
        }
        const a = document.createElement('a');
        a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = url;
        bub.appendChild(a);
      }
    }

    // If everything was media (e.g. just a YouTube link), don't keep an
    // empty paragraph styling.
    if (mediaCount && !bub.textContent.trim()){
      bub.style.background = 'transparent';
      bub.style.border = 'none';
      bub.style.boxShadow = 'none';
      bub.style.padding = '4px 0';
    }
  }
  function appendTyping(){
    const wrap = $('cw-body');
    const empty = $('cw-empty');
    if (empty) empty.remove();
    const row = document.createElement('div');
    row.className = 'cw-bubble-row bot';
    row.innerHTML = `
      <div class="cw-msg-avatar">${ROBOT_SVG}</div>
      <div class="cw-bubble-wrap">
        <div class="cw-bubble"><span class="cw-typing"><span></span><span></span><span></span></span></div>
        <div class="cw-tag"></div>
      </div>`;
    wrap.appendChild(row);
    wrap.scrollTop = wrap.scrollHeight;
    return { row, bub: row.querySelector('.cw-bubble'), tag: row.querySelector('.cw-tag') };
  }

  // ── Backend status / models ───────────────────────────────────────────
  async function refreshStatus(){
    setStatus('đang kiểm tra…', '');
    const { ok, data } = await api('GET','/api/chatbot/status');
    if (!ok || !data?.reachable){
      setStatus('offline', 'red');
      state.statusOk = false;
      return false;
    }
    if (data.has_key) setStatus('online', 'green');
    else if (data.has_cli_token) setStatus('cần auto-setup', 'yellow');
    else setStatus('cần API key', 'red');
    state.statusOk = !!data.has_key;
    return true;
  }

  async function loadModels(){
    if (state.loadedModels) return;
    const { ok, data } = await api('GET','/api/chatbot/models');
    if (!ok || data?.ok === false) return;
    state.models = data.models || [];
    state.defaultModel = data.default || '';
    state.loadedModels = true;
    const sel = $('cw-model');
    if (!sel) return;
    sel.replaceChildren();
    const blank = document.createElement('option');
    blank.value = ''; blank.textContent = '(mặc định)';
    sel.appendChild(blank);
    const groups = new Map();
    for (const m of state.models) {
      const k = m.owned_by || 'others';
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(m);
    }
    const ownerLabel = (k) => ({
      cx:'⚡ ChatGPT (Codex)', kr:'🥝 Kiro', gemini:'🔷 Gemini',
      gc:'🐙 Copilot', ag:'🌌 AG', combo:'✨ Combo',
    })[k] || k;
    // Render owners in a stable, "useful first" order. Anything not listed
    // falls to the end alphabetically. We DO want cx (ChatGPT/Codex) at
    // the top because gpt-5.5 is the user's preferred default.
    const OWNER_ORDER = ['cx', 'kr', 'gemini', 'gc', 'ag', 'combo'];
    const ownerKeys = [...groups.keys()].sort((a, b) => {
      const ai = OWNER_ORDER.indexOf(a), bi = OWNER_ORDER.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
    for (const owner of ownerKeys) {
      const og = document.createElement('optgroup');
      og.label = ownerLabel(owner);
      for (const m of groups.get(owner)) {
        const o = document.createElement('option');
        o.value = m.id; o.textContent = m.id;
        og.appendChild(o);
      }
      sel.appendChild(og);
    }
    const saved = localStorage.getItem(LS_MODEL);
    if (saved) sel.value = saved;
  }

  // ── Send (stream) ─────────────────────────────────────────────────────
  function setBusy(busy){
    state.sending = busy;
    const send = $('cw-send'), stop = $('cw-stop'), inp = $('cw-input');
    if (send){ send.disabled = busy; send.textContent = busy ? '⏳' : 'Gửi'; }
    if (stop) stop.style.display = busy ? '' : 'none';
    if (inp) inp.disabled = busy;
    setHint(busy ? 'Đang chờ phản hồi…' : 'Sẵn sàng');
  }

  async function sendStream(payload, holder){
    state.abortCtl = new AbortController();
    let resp;
    try {
      resp = await fetch('/api/chatbot/chat_stream', {
        method:'POST',
        headers:{'Content-Type':'application/json','Accept':'text/event-stream'},
        body: JSON.stringify(payload),
        signal: state.abortCtl.signal,
      });
    } catch(e){
      if (e.name === 'AbortError'){
        holder.bub.textContent = '⏹ Đã huỷ.';
        holder.bub.classList.add('warn');
        return { ok:false, content:'' };
      }
      holder.bub.textContent = '❌ Không kết nối được: ' + e.message;
      holder.bub.classList.add('err');
      return { ok:false, content:'' };
    }
    if (!resp.ok){
      let msg=''; try{ msg = await resp.text(); }catch(_){}
      holder.bub.textContent = '❌ HTTP ' + resp.status + (msg ? ': '+msg.slice(0,200) : '');
      holder.bub.classList.add('err');
      return { ok:false, content:'' };
    }
    if (!resp.body){
      const text = await resp.text();
      let assembled = '';
      for (const ev of text.split(/\r?\n\r?\n/)){
        for (const line of ev.split(/\r?\n/)){
          if (!line.startsWith('data:')) continue;
          const d = line.slice(5).trim();
          if (!d || d === '[DONE]') continue;
          try { const j = JSON.parse(d);
            const c = (j.choices||[])[0]?.delta?.content;
            if (typeof c === 'string') assembled += c;
          } catch(_){}
        }
      }
      holder.bub.textContent = assembled || '⚠ Không có nội dung';
      return { ok: !!assembled, content: assembled };
    }

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '', assembled = '', actualModel = '', finishReason = '', errored = false;
    holder.bub.textContent = '';
    holder.bub.classList.remove('err','warn');

    while (true){
      let chunk;
      try { chunk = await reader.read(); }
      catch(e){ if (e.name !== 'AbortError') holder.bub.textContent += '\n[lỗi: ' + e.message + ']'; break; }
      if (chunk.done) break;
      buf += dec.decode(chunk.value, { stream:true });
      const evts = buf.split(/\r?\n\r?\n/);
      buf = evts.pop() || '';
      for (const ev of evts){
        let evName = 'message', dataParts = [];
        for (const line of ev.split(/\r?\n/)){
          if (!line || line.startsWith(':')) continue;
          if (line.startsWith('event:')) evName = line.slice(6).trim();
          else if (line.startsWith('data:')) dataParts.push(line.slice(5).trim());
        }
        const d = dataParts.join('\n');
        if (evName === 'error'){
          errored = true;
          let m = d; try { m = JSON.parse(d); } catch(_){}
          holder.bub.textContent = '❌ ' + (typeof m === 'string' ? m : JSON.stringify(m));
          holder.bub.classList.add('err');
          continue;
        }
        if (evName === 'route'){
          try { const info = JSON.parse(d);
            if (info?.routing?.tier && holder.tag){
              const span = document.createElement('span');
              span.style.color = '#1a73e8';
              span.textContent = ' · ⚡' + info.routing.tier;
              span.title = (info.requested_model||'') + ' — ' + (info.routing.reason||'');
              holder.tag.appendChild(span);
            }
            // If the server performed a real web search, surface a small
            // "sources" footer above the bubble so the user can click out.
            const ws = info?.routing?.web_search;
            if (ws && Array.isArray(ws.sources) && ws.sources.length){
              holder._webSources = ws.sources;
              const note = document.createElement('span');
              note.style.color = '#10b981';
              note.style.fontWeight = '600';
              note.textContent = ' · 🔎 ' + ws.sources.length + ' nguồn';
              note.title = 'Đã tra cứu web cho: ' + (ws.query || '');
              holder.tag.appendChild(note);
            }
          } catch(_){}
          continue;
        }
        if (!d || d === '[DONE]') continue;
        let cd; try { cd = JSON.parse(d); } catch(_){ continue; }
        if (cd.model) actualModel = cd.model;
        const choice = (cd.choices||[])[0] || {};
        const delta = choice.delta || {};
        if (typeof delta.content === 'string'){
          assembled += delta.content;
          holder.bub.textContent = assembled;
        } else if (typeof choice.message?.content === 'string'){
          assembled = choice.message.content;
          holder.bub.textContent = assembled;
        }
        if (choice.finish_reason) finishReason = choice.finish_reason;
        const wrap = $('cw-body'); if (wrap) wrap.scrollTop = wrap.scrollHeight;
      }
    }
    if (errored) return { ok:false, content:'' };
    if (!assembled){
      holder.bub.textContent = finishReason === 'max_tokens'
        ? '⚠ Hết max_tokens. Tăng lên 4096+ trong tab Chat.'
        : '⚠ Không có nội dung trả về.';
      holder.bub.classList.add('warn');
    } else {
      // Replace plain text with rich content (images, video preview cards).
      enrichBubble(holder.bub, assembled);
    }
    // After enrichment, append a clickable sources panel if a web search
    // was performed for this turn.
    if (holder._webSources && holder._webSources.length){
      const panel = document.createElement('div');
      panel.style.cssText = 'margin-top:8px;padding:8px 10px;border:1px solid #d8e2f5;'
        + 'border-radius:10px;background:#f5f8ff;font-size:11.5px;color:#3d5a80';
      const title = document.createElement('div');
      title.style.cssText = 'font-weight:600;color:#1a2332;margin-bottom:4px';
      title.textContent = '🔎 Nguồn đã tra cứu (' + holder._webSources.length + ')';
      panel.appendChild(title);
      const list = document.createElement('div');
      list.style.cssText = 'display:flex;flex-direction:column;gap:3px';
      holder._webSources.forEach((s, i) => {
        const a = document.createElement('a');
        a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = '[' + (i + 1) + '] ' + (s.title || s.url);
        a.style.cssText = 'color:#1a73e8;text-decoration:none;border-bottom:none;'
          + 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block';
        a.title = s.url;
        list.appendChild(a);
      });
      panel.appendChild(list);
      holder.bub.appendChild(panel);
    }
    if (actualModel && holder.tag){
      const span = document.createElement('span');
      span.style.opacity = .6;
      span.textContent = ' · ' + actualModel;
      holder.tag.appendChild(span);
    }
    return { ok:true, content: assembled };
  }

  async function sendNonStream(payload, holder){
    const { ok, data } = await api('POST','/api/chatbot/chat', payload);
    if (!ok || data?.ok === false){
      holder.bub.textContent = '❌ ' + (data?.message || data?.error || 'Lỗi');
      holder.bub.classList.add('err');
      return { ok:false, content:'' };
    }
    const content = data.content || '';
    if (content) {
      holder.bub.textContent = content;
      enrichBubble(holder.bub, content);
    } else {
      holder.bub.textContent = '(không có nội dung)';
    }
    if (data.model && holder.tag){
      const span = document.createElement('span');
      span.style.opacity = .6;
      span.textContent = ' · ' + data.model;
      holder.tag.appendChild(span);
    }
    return { ok:true, content: data.content || '' };
  }

  // Convert a (possibly large) image data URL into a small thumbnail
  // suitable for embedding in a chat bubble + persisting in SQLite.
  function makeThumb(dataUrl, maxSide){
    return new Promise((resolve) => {
      if (!dataUrl){ resolve(null); return; }
      try {
        const img = new Image();
        img.onload = () => {
          const W = img.naturalWidth, H = img.naturalHeight;
          const m = maxSide || 360;
          const s = Math.min(1, m / Math.max(W, H));
          const w = Math.round(W * s), h = Math.round(H * s);
          const c = document.createElement('canvas');
          c.width = w; c.height = h;
          const ctx = c.getContext('2d');
          ctx.drawImage(img, 0, 0, w, h);
          try { resolve(c.toDataURL('image/jpeg', 0.78)); }
          catch(_){ resolve(dataUrl); }  // tainted? fall back to original
        };
        img.onerror = () => resolve(dataUrl);
        img.src = dataUrl;
      } catch(_){ resolve(dataUrl); }
    });
  }

  // ── Image generation triggered from chat input ───────────────────────
  // Mirrors the logic in chat.js so the floating widget can also produce
  // images when the user types "vẽ ...", "tạo ảnh ...", "draw ...", v.v.
  // Without this, the LLM (text-only) just refuses with "Tôi không tạo
  // được ảnh" — even though we have /api/chatbot/image fully wired.
  // The verb and the noun can be separated by filler ("cho tôi", "giúp
  // mình", "1", "một"...). We allow up to ~30 chars between them.
  const IMAGE_TRIGGERS = [
    // Vietnamese: "vẽ ...", "vẽ cho tôi ảnh ..."
    /^vẽ(?=\s|$)/i,
    // Vietnamese: "(tạo|sinh|làm) [optional filler ending with space] (ảnh|hình|image|picture|photo)"
    // Filler is optional so "tạo ảnh cô gái" matches without any filler.
    /^(?:tạo|sinh|làm)\s+(?:[^\n]{0,30}?\s)?(?:ảnh|hình|image|picture|photo)(?=\s|$|[,.;:!?])/i,
    // English
    /^draw(?=\s|$)/i, /^paint(?=\s|$)/i, /^imagine(?=\s|$)/i,
    /^(?:generate|create|make)\s+(?:[^\n]{0,30}?\s)?(?:image|picture|photo|drawing|illustration)(?=\s|$|[,.;:!?])/i,
  ];

  function _stripImageTrigger(text){
    // Strip the prefix up to and including the image-noun, so the rest
    // becomes the actual image prompt. Examples:
    //   "tạo cho tôi 1 hình ảnh cô gái việt nam" → "cô gái việt nam"
    //   "vẽ một con mèo dễ thương" → "con mèo dễ thương"
    //   "draw a sunset over mountains" → "a sunset over mountains"
    let p = text;
    p = p.replace(/^vẽ\s+(?:cho\s+(?:tôi|mình|tao|t)\s+)?(?:một\s+|1\s+)?(?:hình\s+ảnh|hình|ảnh\s+về|ảnh)?\s*(?:của\s+|về\s+)?/i, '');
    p = p.replace(/^(?:tạo|sinh|làm)\s+(?:cho\s+(?:tôi|mình|tao|t)\s+)?(?:một\s+|1\s+)?(?:hình\s+ảnh|bức\s+ảnh|tấm\s+ảnh|hình|ảnh|image|picture|photo)\s*(?:về\s+|của\s+|cho\s+)?/i, '');
    p = p.replace(/^(?:draw|paint|imagine)\s+(?:an?\s+)?/i, '');
    p = p.replace(/^(?:generate|create|make)\s+(?:an?\s+)?(?:image|picture|photo|drawing|illustration)\s+(?:of\s+|about\s+)?/i, '');
    p = p.trim();
    return p || text;
  }

  async function handleImageGen(text, holder){
    const prompt = _stripImageTrigger(text);
    holder.bub.textContent = '🎨 Đang tạo ảnh…';
    const { ok, data } = await api('POST', '/api/chatbot/image', {
      prompt, model: 'cx/gpt-5.5-image',
    });
    if (!ok || data?.ok === false){
      const msg = data?.message || data?.error || 'Lỗi tạo ảnh';
      holder.bub.textContent = '❌ ' + (typeof msg === 'string' ? msg : JSON.stringify(msg));
      holder.bub.classList.add('err');
      return { ok: false, content: '' };
    }
    const images = data.images || [];
    if (!images.length){
      holder.bub.textContent = '⚠ Không có ảnh trả về.';
      holder.bub.classList.add('warn');
      return { ok: false, content: '' };
    }
    // Replace the bubble content with the gallery.
    holder.bub.textContent = '';
    holder.bub.style.padding = '6px';
    holder.bub.style.background = 'transparent';
    holder.bub.style.border = 'none';
    holder.bub.style.boxShadow = 'none';
    const gallery = document.createElement('div');
    gallery.className = 'cw-msg-images';
    gallery.style.justifyContent = 'flex-start';
    for (const img of images){
      const el = document.createElement('img');
      el.className = 'cw-msg-img';
      el.alt = prompt.slice(0, 60);
      if (img.url) el.src = img.url;
      else if (img.b64_json) el.src = 'data:image/png;base64,' + img.b64_json;
      el.addEventListener('click', () => openLightbox(el.src, prompt));
      gallery.appendChild(el);
    }
    holder.bub.appendChild(gallery);
    if (holder.tag){
      const span = document.createElement('span');
      span.style.opacity = .7;
      span.textContent = '🎨 ' + (data.model || 'image') + ' · ' + prompt.slice(0, 50);
      holder.tag.appendChild(span);
    }
    return { ok: true, content: '[Đã tạo ảnh: ' + prompt.slice(0, 80) + ']' };
  }

  async function send(){
    if (state.sending) return;
    const inp = $('cw-input');
    const text = (inp?.value || '').trim();
    if (!text && !state.pending.length) return;
    if (state.statusOk == null) await refreshStatus();

    setBusy(true);
    // Transcribe pending audio/video before composing user content.
    if (state.pending.some(a => (a.kind === 'audio' || a.kind === 'video' || a.kind === 'record') && !a.transcript)){
      await transcribePending();
      renderAttachments();
    }

    const userContent = buildUserContent(text);

    // Build display attachments for the bubble (with thumbnails).
    const displayAtts = [];
    for (const a of state.pending){
      if (a.kind === 'image' && a.dataUrl){
        const thumb = await makeThumb(a.dataUrl, 360);
        displayAtts.push({ kind:'image', name:a.name, size:a.size, mime:a.mime, thumbDataUrl: thumb });
      } else {
        displayAtts.push({
          kind: a.kind, name: a.name, size: a.size, mime: a.mime,
          transcript: a.transcript || null,
        });
      }
    }

    // Bubble shows: text + non-image attachments as inline notes; images render above as gallery.
    const noteLines = displayAtts
      .filter(a => a.kind !== 'image')
      .map(a => {
        const icon = a.kind === 'video' ? '🎞' : (a.kind === 'audio' ? '🎵' : (a.kind === 'record' ? '🎙' : '📎'));
        const tail = a.transcript ? ` → "${a.transcript.slice(0,60)}…"` : '';
        return `${icon} ${a.name}${tail}`;
      });
    const bubbleText = [text, ...noteLines].filter(Boolean).join('\n');
    appendBubble('user', bubbleText, { attachments: displayAtts });

    // Persist user turn (in-memory + SQLite).
    state.history.push({ role:'user', content: userContent, attachments: displayAtts });
    persistHistory();
    syncMessageToServer('user', userContent, displayAtts);

    if (inp){ inp.value = ''; autoresize(inp); }
    state.pending = [];
    renderAttachments();

    const model = $('cw-model')?.value || '';
    const stream = !!$('cw-stream')?.checked;
    const payload = { messages: state.history.map(({ role, content }) => ({ role, content })) };
    if (model) payload.model = model;

    const holder = appendTyping();

    // Image generation shortcut: only for plain-text prompts (no images
    // attached — those are vision inputs, not image-gen).
    const hasImageAttachment = (displayAtts || []).some(a => a.kind === 'image');
    const wantsImage = !hasImageAttachment && IMAGE_TRIGGERS.some(rx => rx.test(text));
    let result;
    if (wantsImage){
      result = await handleImageGen(text, holder);
    } else if (stream){
      result = await sendStream(payload, holder);
    } else {
      result = await sendNonStream(payload, holder);
    }
    setBusy(false);
    state.abortCtl = null;
    if (!result.ok){
      state.history.pop(); persistHistory();
      return;
    }
    state.history.push({ role:'assistant', content: result.content });
    persistHistory();
    syncMessageToServer('assistant', result.content, null);
  }

  function stop(){ if (state.abortCtl) state.abortCtl.abort(); }

  function newSession(){
    // Always create a fresh session — keep history of older ones in drawer.
    const s = { id: genId(), title: 'Cuộc mới', messages: [], ts: Date.now() };
    state.sessions.push(s);
    state.activeId = s.id;
    state.history = s.messages;
    state.pending = [];
    renderAttachments();
    saveSessions();
    renderEmptyState();
    renderDrawer();
  }

  // ── Sessions persistence ─────────────────────────────────────────────
  function genId(){ return 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2,7); }

  function loadSessions(){
    try {
      const raw = localStorage.getItem(LS_SESSIONS);
      if (raw){
        const arr = JSON.parse(raw);
        if (Array.isArray(arr)) state.sessions = arr;
      }
    } catch(_){}
    // One-time migration from legacy single-session storage.
    if (!state.sessions.length){
      try {
        const legacy = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
        if (Array.isArray(legacy) && legacy.length){
          state.sessions = [{ id: genId(), title: deriveTitle(legacy), messages: legacy, ts: Date.now() }];
        }
      } catch(_){}
    }
    if (!state.sessions.length){
      const s = { id: genId(), title: 'Cuộc mới', messages: [], ts: Date.now() };
      state.sessions.push(s);
    }
    state.activeId = localStorage.getItem(LS_ACTIVE) || state.sessions[0].id;
    if (!state.sessions.find(s => s.id === state.activeId)) state.activeId = state.sessions[0].id;
    state.history = state.sessions.find(s => s.id === state.activeId).messages;
  }

  function saveSessions(){
    try {
      // Cap each session at 60 messages to avoid bloating storage.
      const trimmed = state.sessions.slice(-30).map(s => ({
        ...s,
        messages: (s.messages || []).slice(-60),
      }));
      localStorage.setItem(LS_SESSIONS, JSON.stringify(trimmed));
      localStorage.setItem(LS_ACTIVE, state.activeId);
    } catch(_){}
  }

  function deriveTitle(messages){
    const firstUser = (messages || []).find(m => m.role === 'user');
    if (!firstUser) return 'Cuộc mới';
    const txt = typeof firstUser.content === 'string'
      ? firstUser.content
      : Array.isArray(firstUser.content)
        ? (firstUser.content.find(p => p?.type === 'text')?.text || '[multimodal]')
        : String(firstUser.content || '');
    return (txt || 'Cuộc mới').replace(/\s+/g,' ').trim().slice(0, 40);
  }

  function activeSession(){ return state.sessions.find(s => s.id === state.activeId); }

  function persistHistory(){
    const sess = activeSession();
    if (!sess) return;
    sess.messages = state.history;
    sess.ts = Date.now();
    let titleChanged = false;
    if (sess.title === 'Cuộc mới' || !sess.title){
      const t = deriveTitle(state.history);
      if (t && t !== 'Cuộc mới'){
        sess.title = t;
        titleChanged = true;
      }
    }
    saveSessions();
    renderDrawer();
    if (titleChanged) renameSessionOnServer(sess.id, sess.title);
  }

  function restoreActive(){
    const wrap = $('cw-body');
    if (!wrap) return;
    wrap.replaceChildren();
    if (!state.history.length){
      renderEmptyState();
      return;
    }
    for (const m of state.history){
      const role = m.role === 'user' ? 'user' : 'assistant';
      const txt = typeof m.content === 'string'
        ? m.content
        : Array.isArray(m.content) ? (m.content.find(p => p?.type === 'text')?.text || '')
        : String(m.content || '');
      const atts = m.attachments || [];
      // For non-image attachments stored on a previous turn, surface them in the
      // text portion so they remain visible after reload.
      let displayText = txt;
      const noteLines = atts.filter(a => a.kind && a.kind !== 'image').map(a => {
        const icon = a.kind === 'video' ? '🎞' : (a.kind === 'audio' ? '🎵' : (a.kind === 'record' ? '🎙' : '📎'));
        const tail = a.transcript ? ` → "${a.transcript.slice(0,60)}…"` : '';
        return `${icon} ${a.name}${tail}`;
      });
      if (noteLines.length){
        displayText = [displayText, ...noteLines].filter(Boolean).join('\n');
      }
      const built = appendBubble(role, displayText, { attachments: atts });
      // Re-render rich content for bot replies pulled from history.
      if (role === 'assistant' && built?.bub && displayText){
        enrichBubble(built.bub, displayText);
      }
    }
  }

  // ── Server sync (SQLite) ──────────────────────────────────────────────
  // Tolerant of network failure: localStorage stays canonical client-side.
  async function ensureSessionOnServer(){
    if (!state.activeId) return;
    try {
      await fetch('/api/chatbot/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: state.activeId,
          title: activeSession()?.title || 'Cuộc mới',
          model: localStorage.getItem(LS_MODEL) || '',
        }),
      });
    } catch(_){}
  }

  function _persistableAttachment(a){
    if (!a) return null;
    // Strip giant data URLs from non-image attachments (we only need the
    // metadata server-side). For images, keep the resized thumbDataUrl (we
    // already capped it at 360px JPEG @ q0.78 — typically <40 KB).
    const out = { kind: a.kind, name: a.name, size: a.size, mime: a.mime };
    if (a.kind === 'image' && a.thumbDataUrl) out.thumbDataUrl = a.thumbDataUrl;
    if (a.transcript) out.transcript = a.transcript;
    return out;
  }

  async function syncMessageToServer(role, content, attachments){
    if (!state.activeId) return;
    try {
      // For multimodal user content, drop the giant image_url data URLs in
      // the *content* before persisting — the thumbnail in `attachments`
      // is enough for replay. The next turn rebuilds full content from
      // `state.pending` anyway, so we don't need bytes-perfect history.
      let toSave = content;
      if (Array.isArray(content)){
        toSave = content.map(p => {
          if (p?.type === 'image_url') return { type: 'image_url', image_url: { url: '[image]' } };
          return p;
        });
      }
      const atts = (attachments || []).map(_persistableAttachment).filter(Boolean);
      await ensureSessionOnServer();
      await fetch(`/api/chatbot/sessions/${encodeURIComponent(state.activeId)}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role,
          content: toSave,
          attachments: atts.length ? atts : null,
          title: activeSession()?.title || null,
        }),
      });
    } catch(_){
      // Non-fatal — we still have localStorage.
    }
  }

  async function loadSessionsFromServer(){
    try {
      const r = await fetch('/api/chatbot/sessions');
      if (!r.ok) return;
      const j = await r.json();
      if (!j?.ok || !Array.isArray(j.sessions)) return;
      // Merge: prefer server data when ids match (server is canonical for
      // older sessions; local pending session wins until first sync).
      const localById = new Map(state.sessions.map(s => [s.id, s]));
      for (const srv of j.sessions){
        const local = localById.get(srv.id);
        if (!local){
          state.sessions.push({
            id: srv.id,
            title: srv.title || 'Cuộc mới',
            messages: [],
            ts: srv.updated_at || Date.now(),
            _stub: true,        // messages not loaded yet
          });
        } else {
          local.title = srv.title || local.title;
          local.ts = srv.updated_at || local.ts;
        }
      }
      saveSessions();
      renderDrawer();
    } catch(_){}
  }

  async function loadSessionMessagesFromServer(id){
    try {
      const r = await fetch(`/api/chatbot/sessions/${encodeURIComponent(id)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (!j?.ok || !Array.isArray(j.messages)) return;
      const sess = state.sessions.find(s => s.id === id);
      if (!sess) return;
      sess.messages = j.messages.map(m => ({
        role: m.role,
        content: m.content,
        attachments: m.attachments || [],
      }));
      sess._stub = false;
      if (state.activeId === id){
        state.history = sess.messages;
        restoreActive();
      }
      saveSessions();
    } catch(_){}
  }

  async function deleteSessionOnServer(id){
    try {
      await fetch(`/api/chatbot/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
    } catch(_){}
  }

  async function renameSessionOnServer(id, title){
    try {
      await fetch(`/api/chatbot/sessions/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
    } catch(_){}
  }

  function switchSession(id){
    const s = state.sessions.find(x => x.id === id);
    if (!s) return;
    state.activeId = id;
    state.history = s.messages;
    saveSessions();
    if (s._stub){
      // Lazy-load messages on first switch.
      loadSessionMessagesFromServer(id);
    } else {
      restoreActive();
    }
    renderDrawer();
    closeDrawer();
  }

  function deleteSession(id){
    const idx = state.sessions.findIndex(s => s.id === id);
    if (idx < 0) return;
    if (!confirm('Xoá cuộc trò chuyện này?')) return;
    state.sessions.splice(idx, 1);
    if (!state.sessions.length){
      state.sessions.push({ id: genId(), title: 'Cuộc mới', messages: [], ts: Date.now() });
    }
    if (state.activeId === id){
      state.activeId = state.sessions[0].id;
      state.history = state.sessions[0].messages;
      restoreActive();
    }
    saveSessions();
    renderDrawer();
    deleteSessionOnServer(id);
  }

  function renderDrawer(){
    const list = $('cw-drawer-list');
    if (!list) return;
    list.replaceChildren();
    const sorted = state.sessions.slice().sort((a,b) => (b.ts||0) - (a.ts||0));
    if (!sorted.length){
      const e = document.createElement('div');
      e.className = 'cw-drawer-empty';
      e.textContent = 'Chưa có cuộc nào.';
      list.appendChild(e);
      return;
    }
    for (const s of sorted){
      const row = document.createElement('div');
      row.className = 'cw-sess' + (s.id === state.activeId ? ' active' : '');
      const info = document.createElement('div');
      info.className = 'cw-sess-info';
      const t = document.createElement('div');
      t.className = 'cw-sess-title';
      t.textContent = s.title || 'Cuộc mới';
      const ts = document.createElement('div');
      ts.className = 'cw-sess-time';
      ts.textContent = formatTs(s.ts);
      info.appendChild(t); info.appendChild(ts);
      const del = document.createElement('button');
      del.className = 'cw-sess-del';
      del.title = 'Xoá';
      del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>';
      del.addEventListener('click', (e) => { e.stopPropagation(); deleteSession(s.id); });
      row.appendChild(info);
      row.appendChild(del);
      row.addEventListener('click', () => switchSession(s.id));
      list.appendChild(row);
    }
  }

  function formatTs(ts){
    if (!ts) return '';
    const d = new Date(ts), now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return d.toLocaleTimeString('vi-VN', { hour:'2-digit', minute:'2-digit' });
    const diff = (now - d) / 86400000;
    if (diff < 7) return d.toLocaleDateString('vi-VN', { weekday:'short', hour:'2-digit', minute:'2-digit' });
    return d.toLocaleDateString('vi-VN');
  }

  function openDrawer(){ $('cw-drawer')?.classList.add('show'); renderDrawer(); }
  function closeDrawer(){ $('cw-drawer')?.classList.remove('show'); }
  function toggleDrawer(){ $('cw-drawer')?.classList.toggle('show'); renderDrawer(); }

  function renderEmptyState(){
    const wrap = $('cw-body');
    wrap.replaceChildren();
    const e = document.createElement('div');
    e.className = 'cw-empty'; e.id = 'cw-empty';
    e.innerHTML = `
      <div class="cw-empty-bot">${ROBOT_SVG}</div>
      <div class="cw-empty-title">Xin chào! 👋</div>
      <div class="cw-empty-sub">Tôi có thể giúp gì cho bạn hôm nay?</div>
      <div class="cw-suggestions">
        <button class="cw-sugg" data-q="Tóm tắt công cụ này có thể làm những gì?">💡 Công cụ này làm được gì?</button>
        <button class="cw-sugg" data-q="Viết caption TikTok hấp dẫn cho video du lịch Đà Lạt 60 giây">✍️ Viết caption TikTok</button>
        <button class="cw-sugg" data-q="Gợi ý 5 hashtag thịnh hành cho video review phim ngắn">#️⃣ Gợi ý hashtag</button>
      </div>`;
    wrap.appendChild(e);
    e.querySelectorAll('.cw-sugg').forEach(btn => {
      btn.addEventListener('click', () => {
        const q = btn.getAttribute('data-q') || btn.textContent;
        const inp = $('cw-input');
        if (inp) { inp.value = q; inp.focus(); autoresize(inp); }
      });
    });
  }

  // ── Attachments (image/video/audio/file/record) ──────────────────────
  function fmtBytes(n){
    if (!n) return '';
    if (n < 1024) return n + 'B';
    if (n < 1024*1024) return (n/1024).toFixed(0) + 'KB';
    return (n/1024/1024).toFixed(1) + 'MB';
  }
  function kindIconSvg(kind){
    if (kind === 'image') return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    if (kind === 'video') return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>';
    if (kind === 'audio' || kind === 'record') return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  }

  function renderAttachments(){
    const box = $('cw-attachments');
    if (!box) return;
    box.replaceChildren();
    if (!state.pending.length){ box.style.display = 'none'; return; }
    box.style.display = 'flex';
    state.pending.forEach((att, idx) => {
      const chip = document.createElement('div');
      chip.className = 'cw-chip';
      const thumb = document.createElement('div');
      thumb.className = 'cw-chip-thumb';
      if (att.kind === 'image' && att.dataUrl) {
        const img = document.createElement('img'); img.src = att.dataUrl;
        thumb.appendChild(img);
      } else {
        thumb.innerHTML = kindIconSvg(att.kind);
      }
      const info = document.createElement('div');
      info.className = 'cw-chip-info';
      const name = document.createElement('div');
      name.className = 'cw-chip-name';
      name.textContent = att.name || (att.kind + ' file');
      const meta = document.createElement('div');
      meta.className = 'cw-chip-meta';
      const parts = [];
      if (att.size) parts.push(fmtBytes(att.size));
      if (att.transcript) parts.push('✓ đã chuyển sang văn bản');
      else if (att.kind === 'audio' || att.kind === 'video' || att.kind === 'record') parts.push('sẽ phiên âm khi gửi');
      meta.textContent = parts.join(' · ') || att.kind;
      info.appendChild(name); info.appendChild(meta);
      const close = document.createElement('button');
      close.className = 'cw-chip-close';
      close.innerHTML = '×';
      close.title = 'Bỏ';
      close.addEventListener('click', () => {
        state.pending.splice(idx, 1);
        renderAttachments();
      });
      chip.appendChild(thumb); chip.appendChild(info); chip.appendChild(close);
      box.appendChild(chip);
    });
  }

  function readAsDataURL(file){
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = () => rej(r.error);
      r.readAsDataURL(file);
    });
  }

  async function attachImage(file){
    if (!file) return;
    if (file.size > 8 * 1024 * 1024){
      alert('Ảnh > 8MB. Resize trước khi đính kèm.');
      return;
    }
    try {
      // Use backend upload to validate mime + get clean data URL.
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch('/api/chatbot/upload_image', { method:'POST', body: fd });
      const j = await r.json();
      if (!r.ok || j?.ok === false){
        // Fallback: read locally.
        const url = await readAsDataURL(file);
        state.pending.push({ kind:'image', name:file.name, mime:file.type, size:file.size, dataUrl:url });
      } else {
        state.pending.push({ kind:'image', name:file.name, mime:j.mime || file.type,
                              size:j.size || file.size, dataUrl: j.data_url });
      }
    } catch(e){
      const url = await readAsDataURL(file);
      state.pending.push({ kind:'image', name:file.name, mime:file.type, size:file.size, dataUrl:url });
    }
    renderAttachments();
  }

  function attachMediaForTranscribe(file, kind){
    if (!file) return;
    if (file.size > 50 * 1024 * 1024){
      alert('Tệp > 50MB — STT có thể fail. Cắt nhỏ trước.');
    }
    state.pending.push({ kind, name:file.name, mime:file.type, size:file.size, file });
    renderAttachments();
  }

  function attachOther(file){
    if (!file) return;
    state.pending.push({ kind:'file', name:file.name, mime:file.type, size:file.size, file });
    renderAttachments();
  }

  // Transcribe queued audio/video/record items via /api/chatbot/stt before sending.
  async function transcribePending(){
    for (const att of state.pending){
      if (att.transcript || !(att.kind === 'audio' || att.kind === 'video' || att.kind === 'record')) continue;
      if (!att.file){ continue; }
      const fd = new FormData();
      fd.append('file', att.file, att.name || 'audio.webm');
      fd.append('response_format', 'json');
      try {
        setHint('Đang phiên âm: ' + att.name);
        const r = await fetch('/api/chatbot/stt', { method:'POST', body: fd });
        const j = await r.json();
        if (r.ok && j?.ok !== false){
          att.transcript = (j.text || j.result?.text || '').trim();
        } else {
          att.transcript = '[Không phiên âm được: ' + (j?.message || j?.error || 'lỗi') + ']';
        }
      } catch(e){
        att.transcript = '[Lỗi STT: ' + e.message + ']';
      }
    }
    setHint('Sẵn sàng');
  }

  // Build user content (string or multimodal array) from input + pending attachments.
  function buildUserContent(text){
    const images = state.pending.filter(a => a.kind === 'image' && a.dataUrl);
    const transcripts = state.pending
      .filter(a => a.transcript)
      .map(a => `[Nội dung từ ${a.name}]:\n${a.transcript}`);
    const fileNotes = state.pending
      .filter(a => a.kind === 'file')
      .map(a => `[Đính kèm: ${a.name} (${fmtBytes(a.size)})]`);

    const fullText = [text, ...transcripts, ...fileNotes].filter(Boolean).join('\n\n');

    if (!images.length){
      return fullText || text || '';
    }
    // Multimodal content array (vision-capable models).
    const parts = [];
    if (fullText) parts.push({ type:'text', text: fullText });
    for (const img of images){
      parts.push({ type:'image_url', image_url:{ url: img.dataUrl } });
    }
    return parts;
  }

  // Attach menu controller.
  function toggleAttachMenu(force){
    const menu = $('cw-attach-menu'), btn = $('cw-attach');
    if (!menu) return;
    const willShow = force === true ? true : force === false ? false : !menu.classList.contains('show');
    menu.classList.toggle('show', willShow);
    btn?.classList.toggle('open', willShow);
  }

  function pickFile(kind){
    toggleAttachMenu(false);
    if (kind === 'image') $('cw-file-image').click();
    else if (kind === 'video') $('cw-file-video').click();
    else if (kind === 'audio') $('cw-file-audio').click();
    else if (kind === 'file') $('cw-file-any').click();
    else if (kind === 'record') startRecording();
  }

  // ── Voice recording ──────────────────────────────────────────────────
  async function startRecording(){
    if (state.recorder){ return; }
    if (!navigator.mediaDevices?.getUserMedia){
      alert('Trình duyệt không hỗ trợ ghi âm.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio:true });
      state.recordStream = stream;
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus'
                 : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      state.recordBlobs = [];
      rec.addEventListener('dataavailable', (e) => { if (e.data.size) state.recordBlobs.push(e.data); });
      rec.addEventListener('stop', () => {
        const blob = new Blob(state.recordBlobs, { type: rec.mimeType || 'audio/webm' });
        const ext = (rec.mimeType || '').includes('webm') ? 'webm' : 'wav';
        const file = new File([blob], `recording-${Date.now()}.${ext}`, { type: blob.type });
        state.pending.push({ kind:'record', name:file.name, mime:file.type, size:file.size, file });
        renderAttachments();
        cleanupRecording();
      });
      state.recorder = rec;
      state.recordStart = Date.now();
      rec.start();
      $('cw-rec-bar').style.display = 'flex';
      state.recordTimer = setInterval(() => {
        const sec = Math.floor((Date.now() - state.recordStart) / 1000);
        const m = Math.floor(sec/60), s = sec%60;
        const t = $('cw-rec-time');
        if (t) t.textContent = m + ':' + String(s).padStart(2,'0');
      }, 250);
    } catch(e){
      alert('Không truy cập được mic: ' + e.message);
    }
  }

  function stopRecording(){
    if (!state.recorder) return;
    try { state.recorder.stop(); } catch(_){}
  }
  function cancelRecording(){
    if (!state.recorder){ cleanupRecording(); return; }
    try { state.recorder.removeEventListener?.('stop', () => {}); } catch(_){}
    try { state.recorder.stop(); } catch(_){}
    // Discard blobs.
    state.recordBlobs = [];
    cleanupRecording();
  }
  function cleanupRecording(){
    if (state.recordTimer){ clearInterval(state.recordTimer); state.recordTimer = null; }
    if (state.recordStream){
      state.recordStream.getTracks().forEach(t => { try { t.stop(); } catch(_){} });
      state.recordStream = null;
    }
    state.recorder = null;
    const bar = $('cw-rec-bar'); if (bar) bar.style.display = 'none';
    const t = $('cw-rec-time'); if (t) t.textContent = '0:00';
  }

  // ── Drag the floating bot icon (FAB) ─────────────────────────────────
  // Distinguish drag from click: only treat as drag once cursor moves
  // > THRESHOLD pixels. Mouse + touch both supported. Snap to the nearest
  // horizontal edge on release so the icon never feels stranded.
  function makeFabDraggable(){
    const fab = $('cw-fab');
    if (!fab) return;
    const THRESHOLD = 4;
    let down = false, dragging = false;
    let sx = 0, sy = 0, ox = 0, oy = 0;
    let pointerId = null;

    function getPos(e){
      if (e.touches && e.touches[0]) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
      return { x: e.clientX, y: e.clientY };
    }

    function onDown(e){
      if (e.button != null && e.button !== 0) return;
      const r = fab.getBoundingClientRect();
      const p = getPos(e);
      down = true; dragging = false;
      sx = p.x; sy = p.y; ox = r.left; oy = r.top;
      fab.style.right = 'auto'; fab.style.bottom = 'auto';
      fab.style.left = ox + 'px'; fab.style.top = oy + 'px';
      if (e.pointerId != null && fab.setPointerCapture){
        pointerId = e.pointerId;
        try { fab.setPointerCapture(pointerId); } catch(_){}
      }
    }

    let pendingMove = null, rafId = 0;
    function applyMove(){
      rafId = 0;
      if (!pendingMove) return;
      const { dx, dy } = pendingMove;
      pendingMove = null;
      const w = fab.offsetWidth, h = fab.offsetHeight, m = 4;
      // Clamp so the FAB never leaves the viewport even mid-drag.
      const minDx = m - ox, maxDx = (window.innerWidth  - w - m) - ox;
      const minDy = m - oy, maxDy = (window.innerHeight - h - m) - oy;
      const dxc = Math.max(minDx, Math.min(maxDx, dx));
      const dyc = Math.max(minDy, Math.min(maxDy, dy));
      fab.style.transform = `translate3d(${dxc}px, ${dyc}px, 0)`;
      // Move the open panel along by the same delta — using transform avoids
      // layout work each frame. Also clamp the panel.
      const panel = $('cw-panel');
      if (panel?.classList.contains('show')){
        // Panel origin was snapshotted in onMove when dragging started.
        const pLeft = panel._dragOriginLeft || 0;
        const pTop  = panel._dragOriginTop  || 0;
        const pw = panel.offsetWidth, ph = panel.offsetHeight;
        const pMinDx = m - pLeft, pMaxDx = (window.innerWidth  - pw - m) - pLeft;
        const pMinDy = m - pTop,  pMaxDy = (window.innerHeight - ph - m) - pTop;
        const pdx = Math.max(pMinDx, Math.min(pMaxDx, dxc));
        const pdy = Math.max(pMinDy, Math.min(pMaxDy, dyc));
        panel.style.transform = `translate3d(${pdx}px, ${pdy}px, 0)`;
      }
    }

    function onMove(e){
      if (!down) return;
      const p = getPos(e);
      const dx = p.x - sx, dy = p.y - sy;
      if (!dragging){
        if (Math.abs(dx) < THRESHOLD && Math.abs(dy) < THRESHOLD) return;
        dragging = true;
        fab.classList.add('dragging');
        const panel = $('cw-panel');
        if (panel?.classList.contains('show')){
          panel.classList.add('dragging');
          // Snapshot panel origin for a clean transform commit on mouseup.
          const pr = panel.getBoundingClientRect();
          panel._dragOriginLeft = pr.left;
          panel._dragOriginTop  = pr.top;
          panel.style.left = pr.left + 'px';
          panel.style.top  = pr.top + 'px';
          panel.style.right = 'auto'; panel.style.bottom = 'auto';
        }
      }
      e.preventDefault?.();
      pendingMove = { dx, dy };
      if (!rafId) rafId = requestAnimationFrame(applyMove);
    }

    function onUp(e){
      if (!down) return;
      const wasDragging = dragging;
      down = false; dragging = false;
      if (pointerId != null && fab.releasePointerCapture){
        try { fab.releasePointerCapture(pointerId); } catch(_){}
        pointerId = null;
      }
      fab.classList.remove('dragging');
      if (rafId){ cancelAnimationFrame(rafId); rafId = 0; pendingMove = null; }
      if (!wasDragging) return;
      // Suppress the click that follows a drag.
      fab._suppressNextClick = true;
      // Commit transform → real left/top, then clear transform so hover/press
      // animations don't double-apply. Hard-clamp so icon never escapes viewport.
      const fr = fab.getBoundingClientRect();
      fab.style.transform = '';
      const fw = fab.offsetWidth, fh = fab.offsetHeight, fMargin = 4;
      const fabLeft = Math.max(fMargin, Math.min(window.innerWidth  - fw - fMargin, fr.left));
      const fabTop  = Math.max(fMargin, Math.min(window.innerHeight - fh - fMargin, fr.top));
      fab.style.left = fabLeft + 'px';
      fab.style.top  = fabTop  + 'px';
      try { localStorage.setItem(LS_FAB_POS, JSON.stringify({ left: fabLeft, top: fabTop })); } catch(_){}
      const panel = $('cw-panel');
      if (panel?.classList.contains('show')){
        const pr = panel.getBoundingClientRect();
        panel.style.transform = '';
        const pMargin = 4;
        const panelLeft = Math.max(pMargin, Math.min(window.innerWidth  - panel.offsetWidth  - pMargin, pr.left));
        const panelTop  = Math.max(pMargin, Math.min(window.innerHeight - panel.offsetHeight - pMargin, pr.top));
        panel.style.left = panelLeft + 'px';
        panel.style.top  = panelTop  + 'px';
        panel.classList.remove('dragging');
      }
    }

    // Listen on window for move/up so drag continues even if the pointer
    // moves out of the (transform-translated) FAB.
    fab.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', guardedUp);
    window.addEventListener('pointercancel', guardedUp);
    fab.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', guardedUp);
    fab.addEventListener('touchstart', onDown, { passive: true });
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('touchend', guardedUp);
    window.addEventListener('touchcancel', guardedUp);

    function guardedUp(e){
      const wasDragging = dragging;
      onUp(e);
      if (wasDragging) fab._suppressNextClick = true;
    }

    // Capture-phase click guard runs before the regular click handler.
    fab.addEventListener('click', (e) => {
      if (fab._suppressNextClick){
        fab._suppressNextClick = false;
        e.preventDefault(); e.stopPropagation();
      }
    }, true);

    // Keep onscreen if window resizes.
    window.addEventListener('resize', () => {
      const r = fab.getBoundingClientRect();
      const w = fab.offsetWidth, h = fab.offsetHeight, margin = 8;
      const nx = Math.max(margin, Math.min(window.innerWidth  - w - margin, r.left));
      const ny = Math.max(margin, Math.min(window.innerHeight - h - margin, r.top));
      if (nx !== r.left || ny !== r.top){
        fab.style.left = nx + 'px'; fab.style.top = ny + 'px';
      }
      // Keep the panel anchored too.
      if ($('cw-panel')?.classList.contains('show')) repositionPanelNearFab();
    });
  }

  function applyFabSavedPos(){
    try {
      const p = JSON.parse(localStorage.getItem(LS_FAB_POS) || 'null');
      if (!p || !Number.isFinite(p.left) || !Number.isFinite(p.top)) return;
      const fab = $('cw-fab');
      if (!fab) return;
      fab.style.right = 'auto'; fab.style.bottom = 'auto';
      const w = 58, h = 58, m = 4;
      const left = Math.max(m, Math.min(window.innerWidth  - w - m, p.left));
      const top  = Math.max(m, Math.min(window.innerHeight - h - m, p.top));
      fab.style.left = left + 'px';
      fab.style.top  = top  + 'px';
    } catch(_){}
  }

  function repositionPanelNearFab(){
    const panel = $('cw-panel');
    const fab = $('cw-fab');
    if (!panel || !fab) return;
    const fr = fab.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const margin = 8;
    const gap = 8;

    // Cap panel to viewport.
    const PMIN_W = 300, PMIN_H = 360;
    const maxW = Math.max(PMIN_W, Math.min(panel.offsetWidth || 380, vw - 2 * margin));
    const maxH = Math.max(PMIN_H, Math.min(panel.offsetHeight || 560, vh - 2 * margin));
    if (panel.offsetWidth  > maxW) panel.style.width  = maxW + 'px';
    if (panel.offsetHeight > maxH) panel.style.height = maxH + 'px';
    const pw = panel.offsetWidth || maxW;
    const ph = panel.offsetHeight || maxH;
    const fw = fab.offsetWidth, fh = fab.offsetHeight;

    // FAB center.
    const fcx = fr.left + fw / 2;
    const fcy = fr.top  + fh / 2;

    // Space from FAB edge to viewport edge.
    const spaceAbove = fr.top - margin;
    const spaceBelow = vh - fr.bottom - margin;
    const spaceLeft  = fr.left - margin;
    const spaceRight = vw - fr.right - margin;

    let panelTop, panelLeft;
    let fabNewLeft = fr.left, fabNewTop = fr.top;
    let placed = false;

    // Priority: panel ABOVE fab (fab stays below) → panel BELOW → panel LEFT → panel RIGHT.
    if (spaceAbove >= ph + gap){
      // Panel above, FAB stays where it is (below the panel).
      panelTop  = fr.top - ph - gap;
      panelLeft = clampX(fcx - pw / 2, pw, margin);
      placed = true;
    } else if (spaceBelow >= ph + gap){
      // Panel below, FAB stays above.
      panelTop  = fr.bottom + gap;
      panelLeft = clampX(fcx - pw / 2, pw, margin);
      placed = true;
    } else if (spaceLeft >= pw + gap){
      // Panel to the left, FAB stays to the right.
      panelLeft = fr.left - pw - gap;
      panelTop  = clampY(fcy - ph / 2, ph, margin);
      placed = true;
    } else if (spaceRight >= pw + gap){
      // Panel to the right, FAB stays to the left.
      panelLeft = fr.right + gap;
      panelTop  = clampY(fcy - ph / 2, ph, margin);
      placed = true;
    }

    if (!placed){
      // Not enough room anywhere without overlap. Place panel in the largest
      // available area and push the FAB to the outside edge.
      // Place panel centered in viewport, then move FAB outside.
      panelLeft = clampX((vw - pw) / 2, pw, margin);
      panelTop  = clampY((vh - ph) / 2, ph, margin);

      // Push FAB to the nearest edge outside the panel.
      const panelRight  = panelLeft + pw;
      const panelBottom = panelTop + ph;

      // Try below panel.
      if (panelBottom + gap + fh <= vh - margin){
        fabNewLeft = clampX(fcx - fw/2, fw, margin);
        fabNewTop  = panelBottom + gap;
      }
      // Try above panel.
      else if (panelTop - gap - fh >= margin){
        fabNewLeft = clampX(fcx - fw/2, fw, margin);
        fabNewTop  = panelTop - gap - fh;
      }
      // Try right of panel.
      else if (panelRight + gap + fw <= vw - margin){
        fabNewLeft = panelRight + gap;
        fabNewTop  = clampY(fcy - fh/2, fh, margin);
      }
      // Try left of panel.
      else {
        fabNewLeft = Math.max(margin, panelLeft - gap - fw);
        fabNewTop  = clampY(fcy - fh/2, fh, margin);
      }

      // Apply FAB move.
      fab.style.left = fabNewLeft + 'px';
      fab.style.top  = fabNewTop  + 'px';
      try { localStorage.setItem(LS_FAB_POS, JSON.stringify({ left: fabNewLeft, top: fabNewTop })); } catch(_){}
    }

    // Final hard clamp panel.
    panelLeft = clampX(panelLeft, panel.offsetWidth, margin);
    panelTop  = clampY(panelTop,  panel.offsetHeight, margin);

    panel.style.right = 'auto'; panel.style.bottom = 'auto';
    panel.style.left = panelLeft + 'px';
    panel.style.top  = panelTop  + 'px';
  }
  function clampX(x, w, m){ return Math.max(m, Math.min(window.innerWidth  - w - m, x)); }
  function clampY(y, h, m){ return Math.max(m, Math.min(window.innerHeight - h - m, y)); }

  function makeDraggable(){
    // Drag the panel by its header — the FAB tags along so the icon and
    // the conversation always stay together. Move both with the same delta.
    const head = $('cw-head'), panel = $('cw-panel'), fab = $('cw-fab');
    if (!head || !panel || !fab) return;
    let down = false, dragging = false;
    let sx = 0, sy = 0;       // pointer at down
    let pox = 0, poy = 0;     // panel left/top at down
    let fox = 0, foy = 0;     // FAB left/top at down
    let pointerId = null;
    const THRESHOLD = 3;

    function getPos(e){
      if (e.touches && e.touches[0]) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
      return { x: e.clientX, y: e.clientY };
    }

    function onDown(e){
      // Don't hijack clicks on header buttons (close / new / minimize / history).
      if (e.target.closest('button')) return;
      if (e.button != null && e.button !== 0) return;
      const p = getPos(e);
      const pr = panel.getBoundingClientRect();
      const fr = fab.getBoundingClientRect();
      down = true; dragging = false;
      sx = p.x; sy = p.y;
      pox = pr.left; poy = pr.top;
      fox = fr.left; foy = fr.top;
      panel.style.right = 'auto'; panel.style.bottom = 'auto';
      panel.style.left = pox + 'px'; panel.style.top = poy + 'px';
      fab.style.right = 'auto'; fab.style.bottom = 'auto';
      fab.style.left = fox + 'px'; fab.style.top = foy + 'px';
      if (e.pointerId != null && head.setPointerCapture){
        pointerId = e.pointerId;
        try { head.setPointerCapture(pointerId); } catch(_){}
      }
    }

    let pendingMove = null, rafId = 0;
    function scheduleApply(){
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (!pendingMove) return;
        const { dx, dy } = pendingMove;
        pendingMove = null;
        const margin = 8;
        const pw = panel.offsetWidth, ph = panel.offsetHeight;
        const minDx = margin - pox, maxDx = (window.innerWidth - pw - margin) - pox;
        const minDy = margin - poy, maxDy = (window.innerHeight - ph - margin) - poy;
        const dxc = Math.max(minDx, Math.min(maxDx, dx));
        const dyc = Math.max(minDy, Math.min(maxDy, dy));
        // Use translate3d for cheap GPU compositing — clear it on mouseup.
        panel.style.transform = `translate3d(${dxc}px, ${dyc}px, 0)`;
        fab.style.transform = `translate3d(${dxc}px, ${dyc}px, 0)`;
      });
    }

    function onMove(e){
      if (!down) return;
      const p = getPos(e);
      const dx = p.x - sx, dy = p.y - sy;
      if (!dragging){
        if (Math.abs(dx) < THRESHOLD && Math.abs(dy) < THRESHOLD) return;
        dragging = true;
        head.style.cursor = 'grabbing';
        panel.classList.add('dragging');
        fab.classList.add('dragging');
      }
      e.preventDefault?.();
      pendingMove = { dx, dy };
      scheduleApply();
    }

    function onUp(e){
      if (!down) return;
      down = false;
      head.style.cursor = '';
      panel.classList.remove('dragging');
      fab.classList.remove('dragging');
      if (pointerId != null && head.releasePointerCapture){
        try { head.releasePointerCapture(pointerId); } catch(_){}
        pointerId = null;
      }
      if (rafId){ cancelAnimationFrame(rafId); rafId = 0; pendingMove = null; }
      if (!dragging){ return; }
      // Commit transform → real left/top. Hard-clamp both to viewport.
      const pr = panel.getBoundingClientRect();
      const fr = fab.getBoundingClientRect();
      panel.style.transform = '';
      fab.style.transform = '';
      const m = 4;
      const panelLeft = Math.max(m, Math.min(window.innerWidth  - panel.offsetWidth  - m, pr.left));
      const panelTop  = Math.max(m, Math.min(window.innerHeight - panel.offsetHeight - m, pr.top));
      panel.style.left = panelLeft + 'px';
      panel.style.top  = panelTop  + 'px';
      const fabLeft = Math.max(m, Math.min(window.innerWidth  - fab.offsetWidth  - m, fr.left));
      const fabTop  = Math.max(m, Math.min(window.innerHeight - fab.offsetHeight - m, fr.top));
      fab.style.left = fabLeft + 'px';
      fab.style.top  = fabTop  + 'px';
      try { localStorage.setItem(LS_FAB_POS, JSON.stringify({ left: fabLeft, top: fabTop })); } catch(_){}
      dragging = false;
    }

    head.style.cursor = 'grab';
    // Listen on window for move/up so the drag survives even when the
    // pointer leaves the (visually moved) header. Pointer capture also
    // helps but window listeners are the reliable fallback.
    head.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    // Mouse / touch fallbacks for old browsers without pointer events.
    head.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    head.addEventListener('touchstart', onDown, { passive: true });
    window.addEventListener('touchmove', onMove, { passive: false });
    window.addEventListener('touchend', onUp);
    window.addEventListener('touchcancel', onUp);
  }
  function makeResizable(){
    const panel = $('cw-panel');
    const left = $('cw-resize'), tl = $('cw-resize-tl');
    if (!panel) return;
    function bind(handle, mode){
      if (!handle) return;
      let down=false, sx, sy, sw, sh, sl, st;
      handle.addEventListener('mousedown', (e) => {
        const r = panel.getBoundingClientRect();
        down = true; sx = e.clientX; sy = e.clientY;
        sw = r.width; sh = r.height; sl = r.left; st = r.top;
        panel.style.right = 'auto'; panel.style.bottom = 'auto';
        panel.style.left = sl + 'px'; panel.style.top = st + 'px';
        e.preventDefault(); e.stopPropagation();
      });
      window.addEventListener('mousemove', (e) => {
        if (!down) return;
        const dx = e.clientX - sx, dy = e.clientY - sy;
        if (mode === 'l'){
          const nw = Math.max(300, Math.min(700, sw - dx));
          panel.style.width = nw + 'px';
          panel.style.left = (sl + (sw - nw)) + 'px';
        } else if (mode === 'tl'){
          const nw = Math.max(300, Math.min(700, sw - dx));
          const nh = Math.max(360, Math.min(window.innerHeight - 40, sh - dy));
          panel.style.width = nw + 'px';
          panel.style.height = nh + 'px';
          panel.style.left = (sl + (sw - nw)) + 'px';
          panel.style.top  = (st + (sh - nh)) + 'px';
        }
      });
      window.addEventListener('mouseup', () => {
        if (!down) return;
        down = false;
        try { localStorage.setItem(LS_SIZE, JSON.stringify({ w: panel.offsetWidth, h: panel.offsetHeight })); } catch(_){}
        // Re-anchor to FAB after the resize finishes so the panel still
        // tracks the bot icon.
        repositionPanelNearFab();
      });
    }
    bind(left, 'l');
    bind(tl, 'tl');
  }

  function applySaved(){
    try {
      const sz = JSON.parse(localStorage.getItem(LS_SIZE) || 'null');
      if (sz?.w && sz?.h){
        $('cw-panel').style.width = sz.w + 'px';
        $('cw-panel').style.height = sz.h + 'px';
      }
    } catch(_){}
    // LS_POS is intentionally ignored now — panel always tracks the FAB.
    const stream = localStorage.getItem(LS_STREAM);
    if (stream != null) $('cw-stream').checked = stream === '1';
  }

  function autoresize(ta){
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(120, ta.scrollHeight) + 'px';
  }

  function open(){
    $('cw-panel').classList.add('show');
    $('cw-fab').classList.add('open');
    localStorage.setItem(LS_OPEN, '1');
    // Panel always follows the FAB. Reposition twice — once now (best effort
    // with cached size) and once after the panel has actually laid out.
    repositionPanelNearFab();
    requestAnimationFrame(repositionPanelNearFab);
    setTimeout(() => $('cw-input')?.focus(), 60);
    if (!state.loadedModels) loadModels();
    if (state.statusOk == null) refreshStatus();
  }
  function close(){
    $('cw-panel').classList.remove('show');
    $('cw-fab').classList.remove('open');
    localStorage.setItem(LS_OPEN, '0');
  }

  // ── Init ──────────────────────────────────────────────────────────────
  function init(){
    injectStyle();
    buildDom();
    applySaved();
    loadSessions();
    restoreActive();
    renderDrawer();

    $('cw-fab').addEventListener('click', () => {
      if ($('cw-panel').classList.contains('show')) close(); else open();
    });
    $('cw-close').addEventListener('click', close);
    $('cw-min').addEventListener('click', () => $('cw-panel').classList.toggle('minimized'));
    $('cw-new').addEventListener('click', () => newSession());
    $('cw-history').addEventListener('click', toggleDrawer);
    $('cw-drawer-new').addEventListener('click', () => { newSession(); closeDrawer(); });
    $('cw-send').addEventListener('click', send);
    $('cw-stop').addEventListener('click', stop);

    // Attach menu + file inputs
    $('cw-attach').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleAttachMenu();
    });
    $('cw-attach-menu').querySelectorAll('.cw-attach-item').forEach(item => {
      item.addEventListener('click', () => pickFile(item.getAttribute('data-act')));
    });
    document.addEventListener('click', (e) => {
      const menu = $('cw-attach-menu');
      if (!menu?.classList.contains('show')) return;
      if (!menu.contains(e.target) && e.target !== $('cw-attach')) toggleAttachMenu(false);
    });

    $('cw-file-image').addEventListener('change', async (e) => {
      const files = Array.from(e.target.files || []);
      for (const f of files) await attachImage(f);
      e.target.value = '';
    });
    $('cw-file-video').addEventListener('change', (e) => {
      const f = e.target.files?.[0]; if (f) attachMediaForTranscribe(f, 'video');
      e.target.value = '';
    });
    $('cw-file-audio').addEventListener('change', (e) => {
      const f = e.target.files?.[0]; if (f) attachMediaForTranscribe(f, 'audio');
      e.target.value = '';
    });
    $('cw-file-any').addEventListener('change', (e) => {
      const f = e.target.files?.[0]; if (f) attachOther(f);
      e.target.value = '';
    });

    // Recording bar buttons
    $('cw-rec-stop').addEventListener('click', stopRecording);
    $('cw-rec-cancel').addEventListener('click', cancelRecording);

    const inp = $('cw-input');
    inp.addEventListener('input', () => autoresize(inp));
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); send(); }
    });
    // Paste image directly into chat.
    inp.addEventListener('paste', (e) => {
      const items = e.clipboardData?.items || [];
      for (const it of items){
        if (it.kind === 'file' && it.type.startsWith('image/')){
          const f = it.getAsFile();
          if (f){ attachImage(f); e.preventDefault(); }
        }
      }
    });
    // Drag & drop files anywhere in panel.
    const panelEl = $('cw-panel');
    panelEl.addEventListener('dragover', (e) => { e.preventDefault(); });
    panelEl.addEventListener('drop', (e) => {
      e.preventDefault();
      const files = Array.from(e.dataTransfer?.files || []);
      for (const f of files){
        if (f.type.startsWith('image/')) attachImage(f);
        else if (f.type.startsWith('audio/')) attachMediaForTranscribe(f, 'audio');
        else if (f.type.startsWith('video/')) attachMediaForTranscribe(f, 'video');
        else attachOther(f);
      }
    });

    $('cw-stream').addEventListener('change', (e) => {
      localStorage.setItem(LS_STREAM, e.target.checked ? '1' : '0');
      $('cw-stream-label')?.classList.toggle('on', e.target.checked);
    });
    $('cw-stream-label')?.classList.toggle('on', !!$('cw-stream').checked);
    $('cw-model').addEventListener('change', (e) => {
      localStorage.setItem(LS_MODEL, e.target.value || '');
    });

    document.addEventListener('keydown', (e) => {
      if (!$('cw-panel').classList.contains('show')) return;
      if (e.ctrlKey && (e.key === 'l' || e.key === 'L')){
        e.preventDefault(); newSession();
      }
    });

    makeDraggable();
    makeResizable();
    makeFabDraggable();
    applyFabSavedPos();

    if (localStorage.getItem(LS_OPEN) === '1') open();
    refreshStatus();
    // Pull sessions from SQLite — non-blocking.
    loadSessionsFromServer();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Public API for callers who want to programmatically open or send.
  window.chatWidget = {
    open, close, newSession,
    ask: (text) => {
      open();
      const inp = $('cw-input');
      if (inp) inp.value = text;
      autoresize(inp);
      return send();
    },
    listSessions: () => state.sessions.slice(),
    switchSession,
    deleteSession,
  };
})();

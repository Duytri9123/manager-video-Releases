/* ─────────────────────────────────────────────────────────────────────────
 * Lightweight CSRF + auth integration.
 *
 * - Reads `dt_csrf` cookie (set by /api/auth/login).
 * - Patches window.fetch so every state-changing request automatically
 *   carries the X-CSRF-Token header. No-op when auth is disabled.
 * - Adds a small helper (window.DTAuth) for explicit usage.
 * ───────────────────────────────────────────────────────────────────────── */
(function () {
  function getCookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }

  function isStateChanging(method) {
    const m = (method || 'GET').toUpperCase();
    return m === 'POST' || m === 'PUT' || m === 'DELETE' || m === 'PATCH';
  }

  const _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    if (isStateChanging(init.method)) {
      const csrf = getCookie('dt_csrf');
      if (csrf) {
        const headers = new Headers(init.headers || {});
        if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrf);
        init = Object.assign({}, init, { headers });
      }
    }
    return _fetch(input, init).then((resp) => {
      // Handle auth-required responses globally
      if (resp.status === 401 && !String(input).includes('/api/auth/')) {
        try {
          if (window.toast) toast('Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.', 'warning');
        } catch (_) {}
        setTimeout(() => { try { location.href = '/login'; } catch (_) {} }, 600);
      } else if (resp.status === 403) {
        // Possible CSRF failure
        try {
          if (window.toast) toast('Yêu cầu bị từ chối (CSRF). Tải lại trang.', 'error');
        } catch (_) {}
      }
      return resp;
    });
  };

  window.DTAuth = {
    csrf: () => getCookie('dt_csrf'),
    async logout() {
      try {
        await fetch('/api/auth/logout', { method: 'POST' });
      } catch (_) {}
      location.href = '/login';
    },
    async status() {
      try {
        const r = await fetch('/api/auth/status');
        return r.ok ? r.json() : null;
      } catch (_) { return null; }
    }
  };
})();

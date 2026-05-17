"""
Resolve which proxy URL to use for outbound requests.

Priority:
  1. proxies pool (when proxies.enabled == true) — picks via configured strategy
  2. legacy `proxy` field in config.yml
  3. None
"""
from __future__ import annotations

from typing import Optional


def resolve_proxy(cfg) -> Optional[str]:
    """Return a proxy URL string or None.

    Accepts either a plain dict (load_cfg() result) or any object with `.get()`.
    """
    def _g(key, default=None):
        try:
            return cfg.get(key, default)
        except TypeError:
            return getattr(cfg, key, default)

    # Pool first
    proxies_cfg = _g("proxies", None) or {}
    if isinstance(proxies_cfg, dict) and proxies_cfg.get("enabled"):
        try:
            from core.proxy_manager import get_proxy_manager
            mode = (proxies_cfg.get("rotation") or {}).get("mode") or "round_robin"
            mgr = get_proxy_manager()
            picked = mgr.pick(mode=mode)
            if picked and picked.url:
                return picked.url
        except Exception:
            pass

    # Legacy single-proxy fallback
    legacy = _g("proxy", "") or ""
    return legacy.strip() or None

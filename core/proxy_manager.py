"""
Proxy pool manager — supports HTTP, HTTPS, SOCKS4, SOCKS5 proxies with
rotation strategies, health-check, and a small health-aware ban-list.

Storage: JSON file under `.state/proxies.json`. Updates trigger immediate
persistence. The manager is process-local (singleton) and uses a Lock for
thread safety. Keep the API simple and synchronous so any caller (sync HTTP,
aiohttp, requests, urllib) can request a proxy URL.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── URL parsing ──────────────────────────────────────────────────────────────
_PROXY_RE = re.compile(
    r"^(?P<scheme>https?|socks4|socks5)://"
    r"(?:(?P<user>[^:@/]+)(?::(?P<password>[^@/]*))?@)?"
    r"(?P<host>[^:/?#]+)"
    r"(?::(?P<port>\d+))?$"
)


def parse_proxy_url(url: str) -> dict:
    """Parse `scheme://[user[:pass]@]host[:port]`."""
    if not url:
        raise ValueError("empty proxy url")
    m = _PROXY_RE.match(url.strip())
    if not m:
        # Allow `host:port` shorthand (assume http)
        if re.match(r"^[A-Za-z0-9_\-\.]+:\d+$", url.strip()):
            host, port = url.strip().split(":", 1)
            return {"scheme": "http", "user": None, "password": None,
                    "host": host, "port": int(port)}
        raise ValueError(f"invalid proxy url: {url}")
    return {
        "scheme": m.group("scheme"),
        "user": m.group("user"),
        "password": m.group("password"),
        "host": m.group("host"),
        "port": int(m.group("port")) if m.group("port") else (443 if m.group("scheme") == "https" else 80),
    }


def build_proxy_url(parts: dict) -> str:
    scheme = parts["scheme"]
    auth = ""
    if parts.get("user"):
        u = urllib.parse.quote(parts["user"], safe="")
        if parts.get("password"):
            p = urllib.parse.quote(parts["password"], safe="")
            auth = f"{u}:{p}@"
        else:
            auth = f"{u}@"
    return f"{scheme}://{auth}{parts['host']}:{parts['port']}"


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class Proxy:
    id: str
    label: str = ""
    url: str = ""           # full URL: http://user:pass@host:port  (or socks5://...)
    country: str = ""
    tags: list = field(default_factory=list)
    active: bool = True
    last_ok: float = 0.0    # epoch seconds
    last_fail: float = 0.0
    fail_streak: int = 0
    last_latency_ms: int = 0
    last_ip: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Manager ──────────────────────────────────────────────────────────────────
class ProxyManager:
    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items: Dict[str, Proxy] = {}
        self._cursor = 0
        self._sticky_id: Optional[str] = None
        self._load()

    # ── persistence ──
    def _load(self):
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            for item in data.get("proxies") or []:
                p = Proxy(**{k: item.get(k) for k in Proxy.__dataclass_fields__})
                self._items[p.id] = p
            self._sticky_id = data.get("sticky_id") or None
        except Exception:
            pass

    def _save(self):
        with self._lock:
            data = {
                "proxies": [p.to_dict() for p in self._items.values()],
                "sticky_id": self._sticky_id,
                "saved_at": int(time.time()),
            }
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception:
            pass

    # ── CRUD ──
    def list(self) -> List[Proxy]:
        with self._lock:
            return list(self._items.values())

    def get(self, pid: str) -> Optional[Proxy]:
        with self._lock:
            return self._items.get(pid)

    def add(self, url: str, label: str = "", country: str = "",
            tags: Optional[list] = None, pid: Optional[str] = None) -> Proxy:
        parts = parse_proxy_url(url)  # validate
        normalized = build_proxy_url(parts)
        new_id = pid or self._next_id()
        with self._lock:
            if new_id in self._items:
                raise ValueError(f"id exists: {new_id}")
            p = Proxy(id=new_id, label=label or f"{parts['host']}:{parts['port']}",
                      url=normalized, country=country, tags=list(tags or []), active=True)
            self._items[new_id] = p
        self._save()
        return p

    def update(self, pid: str, **fields) -> Proxy:
        with self._lock:
            p = self._items.get(pid)
            if not p:
                raise KeyError(pid)
            if "url" in fields and fields["url"]:
                parts = parse_proxy_url(fields["url"])
                fields["url"] = build_proxy_url(parts)
            for k, v in fields.items():
                if k in Proxy.__dataclass_fields__:
                    setattr(p, k, v)
        self._save()
        return p

    def delete(self, pid: str):
        with self._lock:
            self._items.pop(pid, None)
            if self._sticky_id == pid:
                self._sticky_id = None
        self._save()

    def bulk_import(self, raw_text: str, default_scheme: str = "http") -> int:
        """Accept lines of `host:port[:user:password]` or full URLs. Returns count added."""
        added = 0
        for raw_line in (raw_text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            url = self._coerce_url(line, default_scheme)
            if not url:
                continue
            try:
                self.add(url, label=line)
                added += 1
            except Exception:
                continue
        return added

    @staticmethod
    def _coerce_url(line: str, default_scheme: str) -> Optional[str]:
        line = line.strip()
        if "://" in line:
            return line
        # host:port
        # host:port:user:password
        parts = line.split(":")
        if len(parts) == 2:
            return f"{default_scheme}://{parts[0]}:{parts[1]}"
        if len(parts) == 4:
            return f"{default_scheme}://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        if len(parts) == 3 and parts[1].isdigit():
            return f"{default_scheme}://{parts[2]}@{parts[0]}:{parts[1]}"
        return None

    # ── selection ──
    def _alive(self) -> List[Proxy]:
        return [p for p in self._items.values() if p.active]

    def _next_id(self) -> str:
        i = 1
        while True:
            cand = f"px_{i:04d}"
            if cand not in self._items:
                return cand
            i += 1

    def pick(self, mode: str = "round_robin") -> Optional[Proxy]:
        with self._lock:
            alive = [p for p in self._items.values() if p.active]
            if not alive:
                return None
            if mode == "sticky" and self._sticky_id:
                hit = self._items.get(self._sticky_id)
                if hit and hit.active:
                    return hit
            if mode == "random":
                p = random.choice(alive)
                self._sticky_id = p.id
                return p
            # round_robin
            self._cursor = (self._cursor + 1) % len(alive)
            p = alive[self._cursor]
            self._sticky_id = p.id
            return p

    def set_sticky(self, pid: str):
        with self._lock:
            if pid in self._items:
                self._sticky_id = pid

    # ── health ──
    def mark_ok(self, pid: str, latency_ms: int = 0, ip: str = ""):
        with self._lock:
            p = self._items.get(pid)
            if not p:
                return
            p.last_ok = time.time()
            p.fail_streak = 0
            p.last_latency_ms = int(latency_ms)
            if ip:
                p.last_ip = ip
        self._save()

    def mark_fail(self, pid: str):
        with self._lock:
            p = self._items.get(pid)
            if not p:
                return
            p.last_fail = time.time()
            p.fail_streak += 1
            if p.fail_streak >= 5:
                p.active = False  # auto-disable after repeated failures
        self._save()

    def test(self, pid: str, test_url: str = "https://ifconfig.me/ip",
             timeout: int = 8) -> dict:
        """Synchronous proxy probe via urllib. Returns dict with status."""
        p = self.get(pid)
        if not p:
            return {"ok": False, "error": "not_found"}
        try:
            handler_args = {p.url.split("://", 1)[0]: p.url}
            # urllib's ProxyHandler doesn't support socks; fall back to env hint
            if p.url.startswith(("socks4://", "socks5://")):
                return {"ok": False, "error": "socks_requires_pysocks"}
            handler = urllib.request.ProxyHandler(handler_args)
            opener = urllib.request.build_opener(handler)
            t0 = time.time()
            with opener.open(test_url, timeout=timeout) as resp:
                body = resp.read(2048).decode("utf-8", "replace").strip()
                ok = 200 <= resp.status < 400
            latency = int((time.time() - t0) * 1000)
            if ok:
                self.mark_ok(pid, latency_ms=latency, ip=body[:120])
                return {"ok": True, "latency_ms": latency, "ip": body[:120]}
            self.mark_fail(pid)
            return {"ok": False, "error": f"http_{resp.status}"}
        except Exception as e:
            self.mark_fail(pid)
            return {"ok": False, "error": str(e)[:200]}


# ── Singleton accessor ──────────────────────────────────────────────────────
_singleton: Optional[ProxyManager] = None
_singleton_lock = threading.Lock()


def get_proxy_manager(state_file: Optional[Path] = None) -> ProxyManager:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                from core_app import STATE_DIR
                _singleton = ProxyManager(state_file or STATE_DIR / "proxies.json")
    return _singleton


# ── HTTP integration helpers ────────────────────────────────────────────────
def proxy_to_requests_dict(url: str) -> dict:
    """Translate a proxy URL into a `requests`/`httpx` proxies dict."""
    if not url:
        return {}
    return {"http": url, "https": url}


def proxy_to_aiohttp(url: str) -> Optional[str]:
    """aiohttp accepts the proxy URL as-is for HTTP(S). SOCKS needs aiohttp-socks."""
    return url or None

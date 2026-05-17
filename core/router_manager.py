"""
4G/LTE router rotation manager — call a configurable HTTP endpoint to force
the router to drop and re-acquire its WAN IP, giving you a new public IP
for scraping/upload sessions.

Each router config defines:
  id, label, type, endpoint, method, headers, body, success_check, cooldown_sec

Supported types out of the box (others fall through to "generic_http"):
  • huawei_hilink   POST /api/dialup/mobile-dataswitch (toggle data on/off)
  • tplink_4g       POST /cgi-bin/luci/api/network with reconnect
  • mikrotik_api    GET /rest/ip/dhcp-client/release+renew
  • generic_http    your own URL & method/headers/body (e.g. AdsPower, 9Proxy gateway)
  • shell           run a local shell command (last-resort, e.g. `nmcli con down/up`)

The manager records last-used time and enforces a cooldown to avoid
hammering the router. Result includes the new IP if `verify_url` is set.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Router:
    id: str
    label: str = ""
    type: str = "generic_http"
    endpoint: str = ""
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    body: str = ""              # raw string (JSON or form-encoded)
    success_check: str = ""     # substring expected in response body for success
    cooldown_sec: int = 30
    verify_url: str = "https://ifconfig.me/ip"
    auth_user: str = ""         # basic auth (rarely used)
    auth_pass: str = ""
    last_used: float = 0.0
    last_ip: str = ""
    last_status: str = ""
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class RouterManager:
    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items: Dict[str, Router] = {}
        self._load()

    # ── persistence ──
    def _load(self):
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            for it in raw.get("routers") or []:
                fields = {k: it.get(k) for k in Router.__dataclass_fields__}
                self._items[fields["id"]] = Router(**fields)
        except Exception:
            pass

    def _save(self):
        with self._lock:
            data = {"routers": [r.to_dict() for r in self._items.values()],
                    "saved_at": int(time.time())}
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception:
            pass

    def _next_id(self) -> str:
        i = 1
        while True:
            cand = f"rt_{i:03d}"
            if cand not in self._items:
                return cand
            i += 1

    # ── CRUD ──
    def list(self) -> List[Router]:
        with self._lock:
            return list(self._items.values())

    def get(self, rid: str) -> Optional[Router]:
        with self._lock:
            return self._items.get(rid)

    def add(self, **fields) -> Router:
        rid = fields.get("id") or self._next_id()
        with self._lock:
            if rid in self._items:
                raise ValueError(f"id exists: {rid}")
            valid = {k: fields.get(k) for k in Router.__dataclass_fields__ if k in fields}
            valid["id"] = rid
            self._items[rid] = Router(**valid)
        self._save()
        return self._items[rid]

    def update(self, rid: str, **fields) -> Router:
        with self._lock:
            r = self._items.get(rid)
            if not r:
                raise KeyError(rid)
            for k, v in fields.items():
                if k in Router.__dataclass_fields__ and k != "id":
                    setattr(r, k, v)
        self._save()
        return r

    def delete(self, rid: str):
        with self._lock:
            self._items.pop(rid, None)
        self._save()

    # ── rotation ──
    def rotate(self, rid: str, *, force: bool = False, log=None) -> dict:
        """Trigger the rotation action. Returns {ok, message, new_ip, status_code, body}."""
        r = self.get(rid)
        if not r:
            return {"ok": False, "message": "Router không tồn tại."}
        if not r.active:
            return {"ok": False, "message": "Router đang tắt."}
        now = time.time()
        if not force and (now - r.last_used) < r.cooldown_sec:
            wait = int(r.cooldown_sec - (now - r.last_used))
            return {"ok": False, "message": f"Cooldown còn {wait}s."}

        if log:
            try:
                log(f"🔄 Đang xoay IP qua router '{r.label or r.id}' ({r.type})...")
            except Exception:
                pass

        if r.type == "shell":
            result = self._run_shell(r)
        else:
            result = self._run_http(r)

        # Optional: verify new IP
        new_ip = ""
        if r.verify_url:
            try:
                time.sleep(2)  # give modem a moment
                with urllib.request.urlopen(r.verify_url, timeout=10) as resp:
                    new_ip = resp.read(120).decode("utf-8", "replace").strip()
            except Exception:
                new_ip = ""

        with self._lock:
            r.last_used = time.time()
            r.last_ip = new_ip or r.last_ip
            r.last_status = "ok" if result.get("ok") else f"err:{result.get('message','')[:80]}"
        self._save()

        result["new_ip"] = new_ip
        return result

    # ── implementations ──
    def _run_http(self, r: Router) -> dict:
        try:
            url = r.endpoint
            data = r.body.encode("utf-8") if r.body else None
            req = urllib.request.Request(url, data=data, method=(r.method or "GET").upper())
            for k, v in (r.headers or {}).items():
                req.add_header(str(k), str(v))
            if r.auth_user:
                import base64
                creds = f"{r.auth_user}:{r.auth_pass}".encode()
                req.add_header("Authorization", "Basic " + base64.b64encode(creds).decode())
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read(4096).decode("utf-8", "replace")
                ok = 200 <= resp.status < 400
                if ok and r.success_check:
                    ok = r.success_check in body
                return {
                    "ok": ok,
                    "status_code": resp.status,
                    "body": body[:600],
                    "message": "OK" if ok else f"HTTP {resp.status}",
                }
        except urllib.error.HTTPError as e:
            return {"ok": False, "status_code": e.code, "message": f"HTTP {e.code}",
                    "body": e.read(2048).decode("utf-8", "replace") if e.fp else ""}
        except Exception as e:
            return {"ok": False, "message": str(e)[:300], "body": ""}

    def _run_shell(self, r: Router) -> dict:
        if not r.endpoint:
            return {"ok": False, "message": "Thiếu lệnh shell trong endpoint."}
        try:
            # Use list form on POSIX for safety; allow string on Windows for built-in cmds
            cmd = r.endpoint
            proc = subprocess.run(
                shlex.split(cmd) if not _is_windows_shell(cmd) else cmd,
                shell=_is_windows_shell(cmd),
                capture_output=True, text=True, timeout=60,
            )
            ok = proc.returncode == 0
            if ok and r.success_check:
                ok = r.success_check in (proc.stdout + proc.stderr)
            return {
                "ok": ok,
                "status_code": proc.returncode,
                "body": (proc.stdout or proc.stderr)[:1000],
                "message": "OK" if ok else f"exit {proc.returncode}",
            }
        except Exception as e:
            return {"ok": False, "message": str(e)[:300], "body": ""}


def _is_windows_shell(cmd: str) -> bool:
    import os
    return os.name == "nt"


# ── presets ──────────────────────────────────────────────────────────────────
PRESETS = [
    {
        "id": "huawei_hilink",
        "label": "Huawei HiLink (toggle data)",
        "type": "huawei_hilink",
        "endpoint": "http://192.168.8.1/api/dialup/mobile-dataswitch",
        "method": "POST",
        "headers": {"Content-Type": "application/xml"},
        "body": "<?xml version='1.0' encoding='UTF-8'?><request><dataswitch>0</dataswitch></request>",
        "success_check": "<response>OK</response>",
    },
    {
        "id": "tplink_4g_lte",
        "label": "TP-Link 4G/LTE (luci reconnect)",
        "type": "tplink_4g",
        "endpoint": "http://192.168.1.1/cgi-bin/luci/api/network/reconnect",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": "{}",
        "success_check": "",
    },
    {
        "id": "mikrotik_renew",
        "label": "MikroTik (DHCP release+renew)",
        "type": "generic_http",
        "endpoint": "http://192.168.88.1/rest/ip/dhcp-client/release",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": "{}",
        "success_check": "",
    },
    {
        "id": "9proxy_rotate",
        "label": "9Proxy gateway rotate (residential)",
        "type": "generic_http",
        "endpoint": "http://api.9proxy.com/rotate",
        "method": "POST",
        "headers": {"Authorization": "Bearer YOUR_TOKEN"},
        "body": "{}",
        "success_check": "ok",
    },
    {
        "id": "shell_airplane",
        "label": "Shell — airplane mode toggle (Android via adb)",
        "type": "shell",
        "endpoint": "adb shell cmd connectivity airplane-mode enable && timeout 3 && adb shell cmd connectivity airplane-mode disable",
        "method": "",
        "headers": {},
        "body": "",
        "success_check": "",
    },
]


# ── Singleton ───────────────────────────────────────────────────────────────
_singleton: Optional[RouterManager] = None
_lock = threading.Lock()


def get_router_manager(state_file: Optional[Path] = None) -> RouterManager:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                from core_app import STATE_DIR
                _singleton = RouterManager(state_file or STATE_DIR / "routers.json")
    return _singleton

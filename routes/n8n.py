"""n8n orchestration blueprint.

toolvideo is the *worker*; n8n is the *conductor*. This blueprint lets the UI:
  • read/save n8n connection settings (persisted in config.yml under "n8n"),
  • test connectivity to a self-hosted n8n instance,
  • list workflows via the n8n REST API (needs an API key),
  • trigger an n8n webhook workflow (server-side proxy → avoids browser CORS),
  • expose a curated cheat-sheet of toolvideo endpoints n8n can call back into.

Security notes:
  • The n8n API key is read from env N8N_API_KEY first, then config.
  • Webhook triggers do NOT require the API key — they're public-by-design in
    n8n, so treat the webhook URL itself as the secret.
  • All outbound calls have a bounded timeout and never echo the API key back.
"""
import json
import os

from flask import Blueprint, jsonify, request

from core_app import load_cfg, save_cfg, _deep_merge_dict, STATE_DIR, LOGGER

bp = Blueprint("n8n", __name__)

_FLOW_FILE = STATE_DIR / "n8n_flow.json"


# ── Simple Cron Scheduler (threading-based, no external deps) ─────────────
import threading
import time as _time
from datetime import datetime as _dt

_SCHEDULER_THREAD = None
_SCHEDULER_STOP = threading.Event()
_SCHEDULER_CRON = ""     # active cron expression
_SCHEDULER_ENABLED = False


def _cron_matches(cron_expr: str, now: "_dt") -> bool:
    """Check if a 5-field cron expression matches the given datetime (min-level).
    Supports: number, *, */N, ranges (2-5), lists (1,3,5).
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    checks = [now.minute, now.hour, now.day, now.month, now.weekday()]
    # weekday: cron uses 0=Sun..6=Sat; Python uses 0=Mon..6=Sun
    # Convert Python weekday to cron: (py+1)%7 => 0=Sun
    checks[4] = (now.weekday() + 1) % 7
    ranges_max = [60, 24, 32, 13, 7]
    for i, field in enumerate(fields):
        if field == "*":
            continue
        if field.startswith("*/"):
            try:
                step = int(field[2:])
                if step <= 0 or checks[i] % step != 0:
                    return False
            except ValueError:
                return False
            continue
        # List (1,3,5) or range (2-5) or single number
        ok = False
        for part in field.split(","):
            if "-" in part:
                lo, hi = part.split("-", 1)
                try:
                    if int(lo) <= checks[i] <= int(hi):
                        ok = True; break
                except ValueError:
                    pass
            else:
                try:
                    if int(part) == checks[i]:
                        ok = True; break
                except ValueError:
                    pass
        if not ok:
            return False
    return True


def _scheduler_loop():
    """Background thread that checks cron every 30s and triggers the flow."""
    import requests as _req
    last_triggered_minute = -1
    while not _SCHEDULER_STOP.is_set():
        _SCHEDULER_STOP.wait(30)
        if _SCHEDULER_STOP.is_set():
            break
        if not _SCHEDULER_ENABLED or not _SCHEDULER_CRON:
            continue
        now = _dt.now()
        current_minute = now.hour * 60 + now.minute
        if current_minute == last_triggered_minute:
            continue
        if _cron_matches(_SCHEDULER_CRON, now):
            last_triggered_minute = current_minute
            LOGGER.info("[n8n-scheduler] Cron matched at %s — triggering flow run", now.strftime("%H:%M"))
            try:
                _req.post("http://127.0.0.1:5000/api/n8n/flow/run", timeout=120)
            except Exception as exc:
                LOGGER.warning("[n8n-scheduler] trigger failed: %s", exc)


def _ensure_scheduler():
    global _SCHEDULER_THREAD
    if _SCHEDULER_THREAD and _SCHEDULER_THREAD.is_alive():
        return
    _SCHEDULER_STOP.clear()
    _SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, daemon=True, name="n8n-cron")
    _SCHEDULER_THREAD.start()


def _cfg() -> dict:
    return load_cfg() or {}


def _n8n_cfg(cfg: dict) -> dict:
    return dict((cfg or {}).get("n8n") or {})


def _base_url(n: dict) -> str:
    return str(n.get("base_url") or "http://localhost:5678").strip().rstrip("/")


def _api_key(n: dict) -> str:
    return (os.getenv("N8N_API_KEY") or n.get("api_key") or "").strip()


def _timeout(n: dict) -> int:
    try:
        return max(1, min(120, int(n.get("timeout_sec") or 30)))
    except Exception:
        return 30


def _requests():
    import requests  # type: ignore
    return requests


def _safe_view(n: dict) -> dict:
    """Config for the UI. Reveal whether a key exists without leaking env keys."""
    api_key_cfg = str(n.get("api_key") or "")
    return {
        "enabled": bool(n.get("enabled", False)),
        "base_url": _base_url(n),
        "api_key": api_key_cfg,
        "api_key_from_env": bool(os.getenv("N8N_API_KEY")),
        "webhook_url": str(n.get("webhook_url") or ""),
        "default_payload": str(n.get("default_payload") or '{\n  "source": "toolvideo"\n}'),
        "timeout_sec": _timeout(n),
    }


# ── Config ────────────────────────────────────────────────────────────────────
@bp.route("/api/n8n/config", methods=["GET"])
def n8n_get_config():
    return jsonify({"ok": True, "config": _safe_view(_n8n_cfg(_cfg()))})


@bp.route("/api/n8n/config", methods=["POST"])
def n8n_save_config():
    data = request.get_json(silent=True) or {}
    cfg = _cfg()
    current = _n8n_cfg(cfg)

    updates = {}
    if "enabled" in data:
        updates["enabled"] = bool(data.get("enabled"))
    if "base_url" in data:
        updates["base_url"] = str(data.get("base_url") or "").strip()
    if "webhook_url" in data:
        updates["webhook_url"] = str(data.get("webhook_url") or "").strip()
    if "default_payload" in data:
        updates["default_payload"] = str(data.get("default_payload") or "")
    if "timeout_sec" in data:
        try:
            updates["timeout_sec"] = max(1, min(120, int(data.get("timeout_sec"))))
        except Exception:
            pass
    # Only overwrite api_key when a non-empty value is supplied, so the UI can
    # leave the field blank to keep the existing key.
    if "api_key" in data and str(data.get("api_key") or "").strip():
        updates["api_key"] = str(data.get("api_key")).strip()

    cfg["n8n"] = _deep_merge_dict(current, updates)
    save_cfg(cfg)
    return jsonify({"ok": True, "config": _safe_view(cfg["n8n"])})


# ── Connectivity test ───────────────────────────────────────────────────────
@bp.route("/api/n8n/test", methods=["POST"])
def n8n_test():
    n = _n8n_cfg(_cfg())
    base = _base_url(n)
    if not base:
        return jsonify({"ok": False, "error": "missing_base_url"}), 400
    try:
        requests = _requests()
    except Exception as exc:
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    try:
        r = requests.get(f"{base}/healthz", timeout=_timeout(n))
        healthy = r.status_code == 200
        return jsonify({
            "ok": healthy,
            "status": r.status_code,
            "base_url": base,
            "message": "n8n đang chạy và phản hồi." if healthy
                       else f"n8n phản hồi HTTP {r.status_code}.",
        })
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": "unreachable",
            "base_url": base,
            "message": f"Không kết nối được tới n8n: {exc}",
        }), 502


# ── List workflows (needs REST API key) ───────────────────────────────────────
@bp.route("/api/n8n/workflows", methods=["GET"])
def n8n_workflows():
    n = _n8n_cfg(_cfg())
    base = _base_url(n)
    key = _api_key(n)
    if not key:
        return jsonify({
            "ok": False,
            "error": "missing_api_key",
            "message": "Cần n8n API key (Settings → n8n API) để liệt kê workflow.",
        }), 400
    try:
        requests = _requests()
    except Exception as exc:
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    try:
        r = requests.get(
            f"{base}/api/v1/workflows",
            headers={"X-N8N-API-KEY": key, "accept": "application/json"},
            params={"limit": 100},
            timeout=_timeout(n),
        )
        if r.status_code == 401:
            return jsonify({"ok": False, "error": "unauthorized",
                            "message": "API key không hợp lệ."}), 401
        r.raise_for_status()
        payload = r.json()
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        workflows = [
            {
                "id": str(w.get("id", "")),
                "name": w.get("name", "(no name)"),
                "active": bool(w.get("active", False)),
            }
            for w in (items or [])
            if isinstance(w, dict)
        ]
        return jsonify({"ok": True, "workflows": workflows, "count": len(workflows)})
    except Exception as exc:
        return jsonify({"ok": False, "error": "request_failed", "message": str(exc)}), 502


# ── Trigger a webhook workflow ────────────────────────────────────────────────
@bp.route("/api/n8n/trigger", methods=["POST"])
def n8n_trigger():
    data = request.get_json(silent=True) or {}
    n = _n8n_cfg(_cfg())

    webhook_url = str(data.get("webhook_url") or n.get("webhook_url") or "").strip()
    if not webhook_url:
        return jsonify({"ok": False, "error": "missing_webhook_url",
                        "message": "Chưa cấu hình Webhook URL."}), 400

    method = str(data.get("method") or "POST").upper()
    if method not in ("GET", "POST"):
        method = "POST"

    # Accept payload as dict or JSON string
    raw_payload = data.get("payload", n.get("default_payload"))
    payload = raw_payload
    if isinstance(raw_payload, str):
        raw_payload = raw_payload.strip()
        if raw_payload:
            try:
                payload = json.loads(raw_payload)
            except Exception:
                return jsonify({"ok": False, "error": "invalid_json",
                                "message": "Payload không phải JSON hợp lệ."}), 400
        else:
            payload = {}

    try:
        requests = _requests()
    except Exception as exc:
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    try:
        if method == "GET":
            r = requests.get(webhook_url, params=payload if isinstance(payload, dict) else None,
                             timeout=_timeout(n))
        else:
            r = requests.post(webhook_url, json=payload, timeout=_timeout(n))

        body_text = r.text or ""
        body_json = None
        try:
            body_json = r.json()
        except Exception:
            pass

        return jsonify({
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "response_json": body_json,
            "response_text": None if body_json is not None else body_text[:4000],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": "request_failed", "message": str(exc)}), 502


# ── Cheat-sheet: toolvideo endpoints n8n can call back into ────────────────────
@bp.route("/api/n8n/endpoints", methods=["GET"])
def n8n_endpoints():
    """Return the public base URL + a curated list of useful toolvideo
    endpoints so users can wire them into n8n HTTP Request nodes."""
    cfg = _cfg()
    # Reuse the app's public-url resolver (handles ngrok automatically).
    try:
        import core_app
        host = os.getenv("FLASK_HOST", "127.0.0.1")
        port = int(os.getenv("FLASK_PORT", "5000"))
        base = core_app._public_base_url(host if host != "0.0.0.0" else "127.0.0.1", port)
    except Exception:
        base = "http://127.0.0.1:5000"

    endpoints = [
        {"method": "GET",  "path": "/api/_routes",
         "desc": "Liệt kê toàn bộ route đang chạy (kiểm tra nhanh)."},
        {"method": "POST", "path": "/api/user_info",
         "desc": "Lấy thông tin người dùng Douyin (body: {url})."},
        {"method": "POST", "path": "/api/user_videos_page",
         "desc": "Lấy video của người dùng theo trang (body: {url, ...})."},
        {"method": "POST", "path": "/api/queue/add",
         "desc": "Thêm video vào hàng chờ xử lý (body: danh sách item)."},
        {"method": "GET",  "path": "/api/queue",
         "desc": "Xem trạng thái hàng chờ xử lý."},
        {"method": "POST", "path": "/api/process_video",
         "desc": "Chạy pipeline xử lý 1 video."},
        {"method": "GET",  "path": "/api/content/list",
         "desc": "Liệt kê nội dung/bài đăng đã xử lý."},
        {"method": "GET",  "path": "/api/files",
         "desc": "Duyệt file trong thư mục Downloaded."},
    ]
    return jsonify({
        "ok": True,
        "public_base_url": base,
        "note": "Dùng base URL này trong n8n HTTP Request node. Nếu n8n chạy "
                "ngoài máy, bật ngrok ở tab Cấu hình để có URL public.",
        "endpoints": endpoints,
    })


# ── Flow (drag-and-drop workflow graph) persistence ───────────────────────────
@bp.route("/api/n8n/flow", methods=["GET"])
def n8n_flow_get():
    try:
        if _FLOW_FILE.exists():
            flow = json.loads(_FLOW_FILE.read_text(encoding="utf-8"))
        else:
            flow = {"nodes": [], "connections": []}
        return jsonify({"ok": True, "flow": flow})
    except Exception as exc:
        return jsonify({"ok": False, "error": "read_failed", "message": str(exc)}), 500


@bp.route("/api/n8n/flow", methods=["POST"])
def n8n_flow_save():
    data = request.get_json(silent=True) or {}
    flow = {
        "nodes": data.get("nodes") or [],
        "connections": data.get("connections") or [],
        "meta": data.get("meta") or {},
    }
    if not isinstance(flow["nodes"], list) or not isinstance(flow["connections"], list):
        return jsonify({"ok": False, "error": "invalid_flow"}), 400
    try:
        _FLOW_FILE.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "saved": True, "node_count": len(flow["nodes"])})
    except Exception as exc:
        return jsonify({"ok": False, "error": "write_failed", "message": str(exc)}), 500


# ── Schedule (cron) management ────────────────────────────────────────────────
@bp.route("/api/n8n/schedule", methods=["GET"])
def n8n_schedule_get():
    return jsonify({
        "ok": True,
        "enabled": _SCHEDULER_ENABLED,
        "cron": _SCHEDULER_CRON,
    })


@bp.route("/api/n8n/schedule", methods=["POST"])
def n8n_schedule_set():
    global _SCHEDULER_ENABLED, _SCHEDULER_CRON
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        _SCHEDULER_ENABLED = bool(data.get("enabled"))
    if "cron" in data:
        expr = str(data.get("cron") or "").strip()
        parts = expr.split()
        if expr and len(parts) != 5:
            return jsonify({"ok": False, "error": "invalid_cron",
                            "message": "Cần 5 field: phút giờ ngày tháng thứ"}), 400
        _SCHEDULER_CRON = expr
    if _SCHEDULER_ENABLED:
        _ensure_scheduler()
    return jsonify({"ok": True, "enabled": _SCHEDULER_ENABLED, "cron": _SCHEDULER_CRON})


# ── Server-side flow execution (called by cron scheduler or manual trigger) ──
@bp.route("/api/n8n/flow/run", methods=["POST"])
def n8n_flow_run():
    """Execute the saved flow server-side (sequential, synchronous).
    Each node is executed in topological order. Only toolvideo + action nodes
    are executed server-side; AI nodes call local endpoints."""
    if not _FLOW_FILE.exists():
        return jsonify({"ok": False, "error": "no_flow"}), 400
    try:
        flow = json.loads(_FLOW_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return jsonify({"ok": False, "error": "read_failed", "message": str(exc)}), 500

    nodes = flow.get("nodes") or []
    conns = flow.get("connections") or []
    if not nodes:
        return jsonify({"ok": False, "error": "empty_flow"}), 400

    import requests as _req

    node_map = {n["id"]: n for n in nodes}
    has_incoming = set(c["to"] for c in conns)
    # Find trigger/start nodes
    triggers = [n for n in nodes if n["type"].startswith("trigger.")]
    if not triggers:
        triggers = [n for n in nodes if n["id"] not in has_incoming]
    if not triggers:
        triggers = [nodes[0]]

    log_lines = []
    ctx_by_id = {}
    visited = set()
    queue_items = [(t, None) for t in triggers]

    def resolve_tpl(s, prev):
        """Minimal {{input}} / {{input.field}} resolver for server-side."""
        if not isinstance(s, str) or "{{" not in s:
            return s
        import re
        def repl(m):
            expr = m.group(1).strip()
            if expr == "input" or expr == "json":
                return json.dumps(prev) if isinstance(prev, (dict, list)) else str(prev or "")
            mm = re.match(r"^(?:input|json)\.(.+)$", expr)
            if mm:
                parts = mm.group(1).split(".")
                obj = prev
                for p in parts:
                    if isinstance(obj, dict):
                        obj = obj.get(p)
                    else:
                        obj = None
                        break
                return json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj or "")
            return m.group(0)
        return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", repl, s)

    def resolve_config(node, prev):
        cfg = node.get("config") or {}
        return {k: resolve_tpl(v, prev) for k, v in cfg.items()}

    def exec_node(node, prev):
        ntype = node.get("type", "")
        cfg = resolve_config(node, prev)

        if ntype.startswith("trigger."):
            log_lines.append(f"⚡ {ntype}")
            return {"trigger": ntype}

        if ntype == "util.notify":
            log_lines.append(f"🔔 {cfg.get('message', '')}")
            return {"message": cfg.get("message")}

        if ntype == "logic.if":
            expr = cfg.get("condition", "false")
            # Unsafe eval — acceptable in local tool
            try:
                result = bool(eval(expr, {"__builtins__": {}}, {"input": prev, "json": prev}))
            except Exception:
                result = False
            log_lines.append(f"🔀 IF: {expr} → {result}")
            return {"_pass": result, "value": prev}

        if ntype == "logic.loop":
            try:
                items = json.loads(cfg.get("array", "[]"))
            except Exception:
                items = []
            limit = min(int(cfg.get("limit", 10) or 10), 100)
            items = items[:limit] if isinstance(items, list) else [items]
            mode = str(cfg.get("mode", "") or "").lower()
            parallel = "song" in mode  # "Song song"
            try:
                concurrency = max(1, min(20, int(cfg.get("concurrency", 3) or 3)))
            except Exception:
                concurrency = 3
            log_lines.append(
                f"🔁 Loop: {len(items)} items"
                + (f" (song song ×{concurrency})" if parallel else " (tuần tự)")
            )
            return {"_items": items, "_parallel": parallel, "_concurrency": concurrency}

        # Nodes with local endpoint
        from . import n8n as _self_mod  # noqa — unused, just ensures defs are available
        # Map known node types to their endpoint+payload
        _ENDPOINT_MAP = {
            "tv.user_info":   ("/api/user_info", "POST"),
            "tv.user_videos": ("/api/user_videos_page", "POST"),
            "tv.queue_add":   ("/api/queue/add", "POST"),
            "tv.process":     ("/api/process_video", "POST"),
            "ai.chat":        ("/api/chatbot/chat", "POST"),
            "ai.translate":   ("/api/translate", "POST"),
            "ai.tts":         ("/api/chatbot/tts?json=1", "POST"),
            "ai.tts_file":    ("/api/tts_to_mp3", "POST"),
            "ai.stt":         ("/api/chatbot/stt", "POST"),
            "action.n8n":     (None, "POST"),  # special
            "action.http":    (None, "POST"),  # special
        }

        if ntype == "action.n8n":
            url = cfg.get("webhook_url", "")
            if url:
                try:
                    payload = json.loads(cfg.get("payload", "{}"))
                except Exception:
                    payload = {}
                r = _req.request(cfg.get("method", "POST"), url, json=payload, timeout=30)
                log_lines.append(f"🔗 n8n {r.status_code}")
                try:
                    return r.json()
                except Exception:
                    return {"status": r.status_code, "text": r.text[:500]}
            return {}

        if ntype == "action.http":
            url = cfg.get("url", "")
            if url:
                method = cfg.get("method", "POST")
                try:
                    payload = json.loads(cfg.get("payload", "{}"))
                except Exception:
                    payload = None
                r = _req.request(method, url, json=payload, timeout=30)
                log_lines.append(f"🌐 HTTP {method} {url} → {r.status_code}")
                try:
                    return r.json()
                except Exception:
                    return {"status": r.status_code, "text": r.text[:500]}
            return {}

        ep_info = _ENDPOINT_MAP.get(ntype)
        if ep_info and ep_info[0]:
            endpoint, method = ep_info
            # Build payload from cfg
            try:
                if ntype == "ai.chat":
                    msgs = []
                    if cfg.get("system"):
                        msgs.append({"role": "system", "content": cfg["system"]})
                    msgs.append({"role": "user", "content": cfg.get("prompt", "")})
                    payload = {"messages": msgs}
                    if cfg.get("model"):
                        payload["model"] = cfg["model"]
                elif ntype == "ai.translate":
                    payload = {"text": cfg.get("text", ""), "provider": cfg.get("provider", "auto")}
                elif ntype == "ai.tts":
                    payload = {"input": cfg.get("input", ""), "model": cfg.get("model", "openai/tts-1"),
                               "voice": cfg.get("voice", "")}
                elif ntype == "ai.tts_file":
                    payload = {"text": cfg.get("text", ""), "tts_engine": cfg.get("tts_engine", "edge-tts"),
                               "tts_voice": cfg.get("tts_voice", "")}
                elif ntype == "ai.stt":
                    payload = {"model": cfg.get("model", "openai/whisper-1")}
                elif ntype == "tv.user_info":
                    payload = {"url": cfg.get("url", "")}
                elif ntype == "tv.user_videos":
                    payload = {"url": cfg.get("url", ""), "page": int(cfg.get("page", 1) or 1)}
                elif ntype == "tv.queue_add":
                    try:
                        payload = json.loads(cfg.get("items", "[]"))
                    except Exception:
                        payload = []
                elif ntype == "tv.process":
                    try:
                        payload = json.loads(cfg.get("payload", "{}"))
                    except Exception:
                        payload = {}
                else:
                    payload = cfg

                r = _req.request(method, f"http://127.0.0.1:5000{endpoint}",
                                 json=payload, timeout=120)
                log_lines.append(f"→ {ntype} {r.status_code}")
                try:
                    return r.json()
                except Exception:
                    return {"status": r.status_code}
            except Exception as exc:
                log_lines.append(f"✗ {ntype}: {exc}")
                return {"error": str(exc)}

        log_lines.append(f"ℹ {ntype}: no server action")
        return {}

    # BFS execution
    while queue_items:
        node, prev = queue_items.pop(0)
        if not node or node["id"] in visited:
            continue
        visited.add(node["id"])
        out = exec_node(node, prev)
        ctx_by_id[node["id"]] = out

        # IF logic
        if node["type"] == "logic.if":
            if out.get("_pass"):
                for c in conns:
                    if c["from"] == node["id"]:
                        t = node_map.get(c["to"])
                        if t and t["id"] not in visited:
                            queue_items.append((t, out.get("value")))
            continue

        # Loop logic
        if node["type"] == "logic.loop":
            items = out.get("_items") or []
            parallel = bool(out.get("_parallel"))
            concurrency = int(out.get("_concurrency") or 3)
            children = [node_map[c["to"]] for c in conns if c["from"] == node["id"] and c["to"] in node_map]

            def _run_subtree(start_node, prev_val, local_visited):
                if not start_node or start_node["id"] in local_visited:
                    return
                local_visited.add(start_node["id"])
                sub_out = exec_node(start_node, prev_val)
                for cc in conns:
                    if cc["from"] == start_node["id"]:
                        nxt = node_map.get(cc["to"])
                        if nxt:
                            _run_subtree(nxt, sub_out, local_visited)

            def _run_item(item):
                for child in children:
                    _run_subtree(child, item, set(visited))

            if parallel and len(items) > 1:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=min(concurrency, len(items))) as pool:
                    list(pool.map(_run_item, items))
            else:
                for item in items:
                    _run_item(item)

            # Mark the whole loop subtree as visited to avoid re-running in BFS
            def _mark(n_node, seen):
                if not n_node or n_node["id"] in seen:
                    return
                seen.add(n_node["id"])
                visited.add(n_node["id"])
                for cc in conns:
                    if cc["from"] == n_node["id"]:
                        _mark(node_map.get(cc["to"]), seen)
            for child in children:
                _mark(child, set())
            continue

        for c in conns:
            if c["from"] == node["id"]:
                t = node_map.get(c["to"])
                if t and t["id"] not in visited:
                    queue_items.append((t, out))

    return jsonify({"ok": True, "log": log_lines, "nodes_executed": len(visited)})


# ── Generic outbound proxy (used by HTTP Request nodes — avoids browser CORS) ──
@bp.route("/api/n8n/proxy", methods=["POST"])
def n8n_proxy():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "missing_url"}), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"ok": False, "error": "invalid_url",
                        "message": "URL phải bắt đầu bằng http:// hoặc https://"}), 400

    method = str(data.get("method") or "POST").upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        method = "POST"

    headers = data.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}

    raw_payload = data.get("payload")
    payload = raw_payload
    if isinstance(raw_payload, str) and raw_payload.strip():
        try:
            payload = json.loads(raw_payload)
        except Exception:
            payload = raw_payload  # send as-is (form/text)

    n = _n8n_cfg(_cfg())
    try:
        requests = _requests()
    except Exception as exc:
        return jsonify({"ok": False, "error": "requests_unavailable", "message": str(exc)}), 500

    try:
        kwargs = {"timeout": _timeout(n), "headers": {k: str(v) for k, v in headers.items()}}
        if method == "GET":
            kwargs["params"] = payload if isinstance(payload, dict) else None
        elif isinstance(payload, (dict, list)):
            kwargs["json"] = payload
        elif payload is not None:
            kwargs["data"] = str(payload)
        r = requests.request(method, url, **kwargs)
        body_json = None
        try:
            body_json = r.json()
        except Exception:
            pass
        return jsonify({
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "response_json": body_json,
            "response_text": None if body_json is not None else (r.text or "")[:4000],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": "request_failed", "message": str(exc)}), 502

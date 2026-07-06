"""Proxy + Router blueprint — REST API for managing the proxy pool and 4G routers."""
from flask import Blueprint, jsonify, request

from core.proxy_manager import get_proxy_manager
from core.router_manager import PRESETS as ROUTER_PRESETS, get_router_manager

bp = Blueprint("proxies", __name__)


# ── Proxies ──────────────────────────────────────────────────────────────────
@bp.route("/api/proxies/list", methods=["GET"])
def proxies_list():
    mgr = get_proxy_manager()
    return jsonify({"ok": True, "items": [p.to_dict() for p in mgr.list()]})


@bp.route("/api/proxies/add", methods=["POST"])
def proxies_add():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "Thiếu URL proxy."}), 400
    try:
        mgr = get_proxy_manager()
        p = mgr.add(
            url=url,
            label=(data.get("label") or "").strip(),
            country=(data.get("country") or "").strip(),
            tags=data.get("tags") or [],
        )
        return jsonify({"ok": True, "item": p.to_dict()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/proxies/bulk_import", methods=["POST"])
def proxies_bulk_import():
    data = request.get_json(silent=True) or {}
    raw = data.get("text") or ""
    scheme = data.get("default_scheme") or "http"
    mgr = get_proxy_manager()
    n = mgr.bulk_import(raw, default_scheme=scheme)
    return jsonify({"ok": True, "added": n})


@bp.route("/api/proxies/update", methods=["POST"])
def proxies_update():
    data = request.get_json(silent=True) or {}
    pid = data.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    fields = {k: v for k, v in data.items() if k != "id"}
    try:
        p = get_proxy_manager().update(pid, **fields)
        return jsonify({"ok": True, "item": p.to_dict()})
    except KeyError:
        return jsonify({"ok": False, "error": "Không tìm thấy proxy."}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/proxies/delete", methods=["POST"])
def proxies_delete():
    data = request.get_json(silent=True) or {}
    pid = data.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    get_proxy_manager().delete(pid)
    return jsonify({"ok": True})


@bp.route("/api/proxies/test", methods=["POST"])
def proxies_test():
    data = request.get_json(silent=True) or {}
    pid = data.get("id")
    if not pid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    test_url = data.get("test_url") or "https://ifconfig.me/ip"
    timeout = int(data.get("timeout") or 8)
    res = get_proxy_manager().test(pid, test_url=test_url, timeout=timeout)
    return jsonify(res)


@bp.route("/api/proxies/test_all", methods=["POST"])
def proxies_test_all():
    data = request.get_json(silent=True) or {}
    test_url = data.get("test_url") or "https://ifconfig.me/ip"
    timeout = int(data.get("timeout") or 8)
    mgr = get_proxy_manager()
    results = []
    for p in mgr.list():
        results.append({"id": p.id, **mgr.test(p.id, test_url=test_url, timeout=timeout)})
    return jsonify({"ok": True, "results": results})


@bp.route("/api/proxies/pick", methods=["POST"])
def proxies_pick():
    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "round_robin").strip()
    p = get_proxy_manager().pick(mode=mode)
    if not p:
        return jsonify({"ok": False, "error": "Không có proxy nào đang bật."}), 404
    return jsonify({"ok": True, "item": p.to_dict()})


# ── Routers ──────────────────────────────────────────────────────────────────
@bp.route("/api/routers/list", methods=["GET"])
def routers_list():
    return jsonify({"ok": True, "items": [r.to_dict() for r in get_router_manager().list()]})


@bp.route("/api/routers/presets", methods=["GET"])
def routers_presets():
    return jsonify({"ok": True, "items": ROUTER_PRESETS})


@bp.route("/api/routers/add", methods=["POST"])
def routers_add():
    data = request.get_json(silent=True) or {}
    if not data.get("endpoint"):
        return jsonify({"ok": False, "error": "Thiếu endpoint."}), 400
    try:
        r = get_router_manager().add(**data)
        return jsonify({"ok": True, "item": r.to_dict()})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/routers/update", methods=["POST"])
def routers_update():
    data = request.get_json(silent=True) or {}
    rid = data.get("id")
    if not rid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    fields = {k: v for k, v in data.items() if k != "id"}
    try:
        r = get_router_manager().update(rid, **fields)
        return jsonify({"ok": True, "item": r.to_dict()})
    except KeyError:
        return jsonify({"ok": False, "error": "Không tìm thấy router."}), 404


@bp.route("/api/routers/delete", methods=["POST"])
def routers_delete():
    data = request.get_json(silent=True) or {}
    rid = data.get("id")
    if not rid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    get_router_manager().delete(rid)
    return jsonify({"ok": True})


@bp.route("/api/routers/rotate", methods=["POST"])
def routers_rotate():
    data = request.get_json(silent=True) or {}
    rid = data.get("id")
    force = bool(data.get("force"))
    if not rid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    res = get_router_manager().rotate(rid, force=force)
    return jsonify(res)


# ── Bulk add (e.g. 9 routers from a single IP/host list) ────────────────────
@bp.route("/api/routers/bulk_add", methods=["POST"])
def routers_bulk_add():
    """Create N routers in one shot from a preset + a list of host:port lines.

    Body::
        {
          "preset_id":   "huawei_hilink",        # required, must match a preset.id
          "hosts":       ["192.168.8.1", ...],   # OR
          "hosts_text":  "192.168.8.1\n192.168.8.2\n...",
          "label_prefix":"Router 4G",            # optional, "{label_prefix} #N — {host}"
          "cooldown_sec":30,
          "verify_url":  "https://ifconfig.me/ip"
        }
    """
    data = request.get_json(silent=True) or {}
    preset_id = (data.get("preset_id") or "").strip()
    preset = next((p for p in ROUTER_PRESETS if p.get("id") == preset_id), None)
    if not preset:
        return jsonify({
            "ok": False,
            "error": "Preset không hợp lệ.",
            "available": [p["id"] for p in ROUTER_PRESETS],
        }), 400

    hosts = data.get("hosts") or []
    if isinstance(data.get("hosts_text"), str) and not hosts:
        hosts = [
            line.strip()
            for line in data["hosts_text"].splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    if not hosts:
        return jsonify({"ok": False, "error": "Thiếu danh sách hosts."}), 400

    label_prefix = (data.get("label_prefix") or preset.get("label") or "Router").strip()
    cooldown = int(data.get("cooldown_sec") or 30)
    verify_url = (data.get("verify_url") or "https://ifconfig.me/ip").strip()

    # Replace the host portion of the preset endpoint (URL or shell).
    import urllib.parse as _up
    base_endpoint = preset.get("endpoint") or ""
    base_is_url = base_endpoint.startswith(("http://", "https://"))

    mgr = get_router_manager()
    created = []
    errors = []
    for idx, host in enumerate(hosts, start=1):
        try:
            host_clean = host.strip()
            if base_is_url:
                u = _up.urlparse(base_endpoint)
                # If user provided a host like ``192.168.8.5:8080`` keep the port.
                if "://" in host_clean:
                    target = host_clean
                    new_host = _up.urlparse(host_clean).netloc
                else:
                    new_host = host_clean
                target = u._replace(netloc=new_host).geturl()
                endpoint = target
            else:
                # Shell command — substitute literal {host} placeholder if present.
                endpoint = (base_endpoint.replace("{host}", host_clean)
                            if "{host}" in base_endpoint
                            else f"{base_endpoint} {host_clean}".strip())

            label = f"{label_prefix} #{idx} — {host_clean}"
            r = mgr.add(
                label=label,
                type=preset.get("type") or "generic_http",
                endpoint=endpoint,
                method=preset.get("method") or "POST",
                headers=dict(preset.get("headers") or {}),
                body=preset.get("body") or "",
                success_check=preset.get("success_check") or "",
                cooldown_sec=cooldown,
                verify_url=verify_url,
            )
            created.append(r.to_dict())
        except Exception as e:
            errors.append({"host": host, "error": str(e)[:200]})

    return jsonify({
        "ok": True,
        "created": len(created),
        "items": created,
        "errors": errors,
        "preset": preset_id,
    })


# ── Rotate all (with delay between each to avoid hammering the modem) ──────
@bp.route("/api/routers/rotate_all", methods=["POST"])
def routers_rotate_all():
    import time

    data = request.get_json(silent=True) or {}
    only = data.get("ids") or []          # subset; empty = all active routers
    only = [str(x) for x in only]
    delay = float(data.get("delay_sec") or 1.0)
    force = bool(data.get("force"))

    mgr = get_router_manager()
    results = []
    targets = mgr.list()
    if only:
        targets = [r for r in targets if r.id in only]
    targets = [r for r in targets if r.active]

    for r in targets:
        res = mgr.rotate(r.id, force=force)
        results.append({
            "id": r.id,
            "label": r.label,
            "ok": bool(res.get("ok")),
            "new_ip": res.get("new_ip", ""),
            "message": res.get("message", ""),
        })
        if delay > 0:
            time.sleep(delay)

    ok_count = sum(1 for x in results if x["ok"])
    return jsonify({
        "ok": True,
        "total": len(results),
        "ok_count": ok_count,
        "failed_count": len(results) - ok_count,
        "results": results,
    })


# ── Test connection (does the endpoint respond?) ───────────────────────────
@bp.route("/api/routers/test", methods=["POST"])
def routers_test():
    """HEAD-style check that the router endpoint is reachable. Does NOT
    rotate the IP — just verifies that the box is on the network."""
    import socket
    import urllib.parse as _up
    import urllib.error as _ue
    import urllib.request as _ur

    data = request.get_json(silent=True) or {}
    rid = (data.get("id") or "").strip()
    if not rid:
        return jsonify({"ok": False, "error": "Thiếu id."}), 400
    r = get_router_manager().get(rid)
    if not r:
        return jsonify({"ok": False, "error": "Không tìm thấy router."}), 404

    if r.type == "shell":
        return jsonify({
            "ok": True,
            "reachable": True,
            "message": "Type=shell — bỏ qua kiểm tra mạng, vui lòng thử Rotate trực tiếp.",
        })

    target = r.endpoint
    if not target.startswith(("http://", "https://")):
        return jsonify({"ok": False, "reachable": False, "message": "Endpoint không phải URL HTTP."})

    try:
        u = _up.urlparse(target)
        host = u.hostname or ""
        port = u.port or (443 if u.scheme == "https" else 80)
        # Quick TCP probe (3 s timeout) — works even when the device returns
        # 401/403 to the GET (still proves it's online).
        with socket.create_connection((host, port), timeout=3) as _:
            pass
        # Then try a HEAD/GET to surface auth status.
        try:
            head = _ur.Request(target, method="HEAD")
            with _ur.urlopen(head, timeout=4) as resp:
                code = resp.status
        except _ue.HTTPError as e:
            code = e.code        # treat any HTTP response as "reachable"
        except Exception:
            code = 0
        return jsonify({
            "ok": True,
            "reachable": True,
            "host": host,
            "port": port,
            "http_status": code,
            "message": f"OK ({host}:{port}, HTTP {code or 'n/a'})",
        })
    except Exception as e:
        return jsonify({
            "ok": True,
            "reachable": False,
            "message": str(e)[:200],
        })

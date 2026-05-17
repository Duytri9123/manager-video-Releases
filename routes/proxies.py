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

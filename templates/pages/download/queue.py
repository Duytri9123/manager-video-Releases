"""Download queue Blueprint — /api/queue* endpoints."""
from flask import Blueprint, jsonify, request
from core_app import _dl_queue, _queue_lock, socketio

bp = Blueprint("queue", __name__)


@bp.route("/api/queue", methods=["GET"])
def get_queue():
    with _queue_lock:
        return jsonify(list(_dl_queue))


@bp.route("/api/queue/add", methods=["POST"])
def queue_add():
    items = request.json or []
    if isinstance(items, dict):
        items = [items]
    with _queue_lock:
        existing = {i["url"] for i in _dl_queue}
        added = 0
        for item in items:
            if item.get("url") and item["url"] not in existing:
                _dl_queue.append(item)
                existing.add(item["url"])
                added += 1
    socketio.emit("queue_update", list(_dl_queue))
    return jsonify({"ok": True, "added": added, "total": len(_dl_queue)})


@bp.route("/api/queue/remove", methods=["POST"])
def queue_remove():
    url = (request.json or {}).get("url", "")
    with _queue_lock:
        for i, item in enumerate(_dl_queue):
            if item.get("url") == url:
                del _dl_queue[i]
                break
    socketio.emit("queue_update", list(_dl_queue))
    return jsonify({"ok": True})


@bp.route("/api/queue/reorder", methods=["POST"])
def queue_reorder():
    urls = request.json or []
    with _queue_lock:
        by_url = {i["url"]: i for i in _dl_queue}
        _dl_queue.clear()
        for u in urls:
            if u in by_url:
                _dl_queue.append(by_url[u])
    socketio.emit("queue_update", list(_dl_queue))
    return jsonify({"ok": True})


@bp.route("/api/queue/update", methods=["POST"])
def queue_update():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    desc = (data.get("desc") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "missing url"}), 400
    with _queue_lock:
        updated = False
        for item in _dl_queue:
            if item.get("url") == url:
                item["desc"] = desc or url
                updated = True
                break
    if updated:
        socketio.emit("queue_update", list(_dl_queue))
    return jsonify({"ok": updated})


@bp.route("/api/queue/clear", methods=["POST"])
def queue_clear():
    with _queue_lock:
        _dl_queue.clear()
    socketio.emit("queue_update", [])
    return jsonify({"ok": True})

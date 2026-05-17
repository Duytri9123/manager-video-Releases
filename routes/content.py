"""Content Management Blueprint — /api/content/list, /api/content/delete, /api/content/rename.

Hardened against path traversal: every filename arg is resolved through
`utils.security.safe_join` to ensure it stays within the configured download dir.
"""
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from core_app import ROOT, load_cfg
from utils.security import safe_filename, safe_join

bp = Blueprint("content", __name__)


def get_download_dir() -> Path:
    cfg = load_cfg()
    dpath = cfg.get("path", "./Downloaded/")
    p = Path(dpath)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    """Strip path separators / control chars; keep only the leaf filename."""
    return safe_filename(name)


@bp.route("/api/content/list", methods=["GET"])
def list_content():
    try:
        ddir = get_download_dir()
        files = []
        for entry in os.scandir(ddir):
            if not entry.is_file():
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            files.append({
                "name": entry.name,
                "size": st.st_size,
                "mtime": st.st_mtime,
                "ext": Path(entry.name).suffix.lower(),
                "path": str(Path(entry.path).relative_to(ROOT)) if str(entry.path).startswith(str(ROOT)) else entry.name,
            })
        files.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify({"ok": True, "files": files})
    except Exception as e:
        return jsonify({"ok": False, "error": "Không thể liệt kê thư mục: " + str(e)}), 500


@bp.route("/api/content/delete", methods=["POST"])
def delete_content():
    try:
        data = request.get_json(silent=True) or {}
        raw = data.get("filename")
        if not raw:
            return jsonify({"ok": False, "error": "Thiếu filename."}), 400
        leaf = _safe_name(raw)
        if not leaf:
            return jsonify({"ok": False, "error": "Tên file không hợp lệ."}), 400
        ddir = get_download_dir()
        try:
            fpath = safe_join(ddir, leaf)
        except ValueError:
            return jsonify({"ok": False, "error": "Đường dẫn không an toàn."}), 400
        if not fpath.exists() or not fpath.is_file():
            return jsonify({"ok": False, "error": "Không tìm thấy file."}), 404
        fpath.unlink()
        return jsonify({"ok": True, "message": f"Đã xóa {leaf}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/api/content/rename", methods=["POST"])
def rename_content():
    try:
        data = request.get_json(silent=True) or {}
        old_raw = data.get("old_name")
        new_raw = data.get("new_name")
        if not old_raw or not new_raw:
            return jsonify({"ok": False, "error": "Thiếu tên cũ hoặc tên mới."}), 400
        old_leaf = _safe_name(old_raw)
        new_leaf = _safe_name(new_raw)
        if not old_leaf or not new_leaf:
            return jsonify({"ok": False, "error": "Tên file không hợp lệ."}), 400
        ddir = get_download_dir()
        try:
            old_path = safe_join(ddir, old_leaf)
            new_path = safe_join(ddir, new_leaf)
        except ValueError:
            return jsonify({"ok": False, "error": "Đường dẫn không an toàn."}), 400
        if not old_path.exists():
            return jsonify({"ok": False, "error": "File gốc không tồn tại."}), 404
        if new_path.exists():
            return jsonify({"ok": False, "error": "Tên đích đã tồn tại."}), 400
        old_path.rename(new_path)
        return jsonify({"ok": True, "message": f"Đã đổi tên thành {new_leaf}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
